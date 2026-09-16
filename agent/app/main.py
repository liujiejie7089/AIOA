"""FastAPI 应用：路由挂载、健康检查、SSE 运行接口、全局异常。"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app.core import runtime
from app.core.events import to_frame
from app.core.guards import GuardError
from app.schemas import CompleteRequest, RunRequest, SseEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("aioa.agent")

app = FastAPI(title="AIOA Agent", version="0.1.0", description="AIOA Python agent service (M1, echo mode)")


@app.get("/health")
async def health() -> dict:
    """健康检查：{"status": "UP"}。"""
    return {"status": "UP"}


@app.post("/internal/v1/runs")
async def create_run(req: RunRequest, request: Request) -> StreamingResponse:
    """发起一次 agent 运行，响应为 SSE 事件流。

    M1 为回声模式。Authorization 头存在则记录日志，M1 不校验（M2 校验服务 JWT）。
    """
    authorization = request.headers.get("Authorization")
    if authorization:
        logger.info("run %s start (auth present, len=%d, trace=%s)", req.run_id, len(authorization), req.user_context.trace_id)
    else:
        logger.info("run %s start (no auth header, trace=%s)", req.run_id, req.user_context.trace_id)

    async def event_stream():
        seq = 1
        try:
            async for event in runtime.run(req):
                seq = event.seq + 1
                yield to_frame(event)
        except GuardError as exc:
            yield to_frame(SseEvent(seq=seq, type="error", data={"code": exc.code, "message": exc.message, "retryable": exc.retryable}))
            yield to_frame(SseEvent(seq=seq + 1, type="run.failed", data={"reason": exc.message, "error_code": exc.code}))
        except Exception as exc:  # 兜底：流内异常按 error + run.failed 上报
            logger.exception("run %s failed", req.run_id)
            yield to_frame(SseEvent(seq=seq, type="error", data={"code": "INTERNAL_ERROR", "message": str(exc), "retryable": True}))
            yield to_frame(SseEvent(seq=seq + 1, type="run.failed", data={"reason": str(exc), "error_code": "INTERNAL_ERROR"}))
        finally:
            logger.info("run %s finished", req.run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/internal/v1/models/apply")
async def apply_models(payload: dict, request: Request) -> dict:
    """管理端「模型管理」配置热加载：{models:[{key,baseUrl,model,apiKeyEnv,enabled,isDefault}], default}。

    与 /internal/v1/runs 同为内网直信端点（M1）；管理端保存模型配置后调用，变更即时生效。
    """
    from app.model_gateway import apply_overrides, configured_providers

    applied = apply_overrides(payload.get("models") or [], payload.get("default"))
    logger.info("model config applied via admin push (%d entries)", applied)
    return {"applied": applied, "providers": configured_providers()}


@app.post("/internal/v1/complete")
async def complete(req: CompleteRequest) -> dict:
    """非流式单轮补全（内部端点）：数字员工定时任务执行、批量摘要等后台调用。

    直接走模型网关（与 /internal/v1/runs 同一配置），不进入 agent 工具循环。
    """
    import httpx

    from app.core.agent_runtime import UpstreamError, _post_non_stream
    from app.model_gateway import gateway

    if not req.prompt or not req.prompt.strip():
        raise GuardError("BAD_REQUEST", "prompt 不能为空")
    provider = gateway.resolve(req.model_ref)
    api_key = provider.api_key()
    if not api_key:
        return {"content": "", "model": provider.model, "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "error": f"provider '{provider.key}' 未配置 api_key（{provider.api_key_env}）"}
    messages: list[dict] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.prompt})
    body: dict = {"model": provider.model, "messages": messages, "stream": False, "temperature": 0.3}
    if req.max_tokens:
        body["max_tokens"] = req.max_tokens
    async with httpx.AsyncClient(timeout=120) as client_http:
        try:
            message, usage = await _post_non_stream(client_http, provider, api_key, messages, None)
        except UpstreamError as exc:
            return {"content": "", "model": provider.model, "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    "error": f"模型上游错误：{exc}"}
    return {
        "content": str(message.get("content") or ""),
        "model": provider.model,
        "usage": {"prompt_tokens": int(usage.get("prompt_tokens") or 0),
                  "completion_tokens": int(usage.get("completion_tokens") or 0)},
    }


@app.post("/internal/v1/worker-intent")
async def worker_intent(payload: dict) -> dict:
    """数字员工「意图识别」：自然语言诉求 → 数字员工类型（内部端点，不调 LLM）。

    调用方：Java 侧 `POST /api/v1/workers/intent`。
    Java 收到类型后再补权限码、可申请性与申请路径 —— 权限映射属治理事实，只在 Java 侧定义一份。
    """
    from app.core.worker_intake import classify

    text = str(payload.get("text") or "").strip()
    if not text:
        raise GuardError("BAD_REQUEST", "text 不能为空")
    result = classify(text)
    logger.info("worker-intent role=%s confidence=%s", result.get("role"), result.get("confidence"))
    return result


@app.post("/internal/v1/answer-shape")
async def answer_shape(payload: dict) -> dict:
    """数字员工「回答结构」契约：确定性边界卡 + 结构规则 + 可选的自检。

    调用方：Java 侧 `GET /api/v1/workers/role-types` 的补充、以及需要展示「能力边界卡」的页面。
    三件事互相独立，因此一个端点同时返回：

      * ``card``   —— 不经模型的固定边界文案（角色类型元数据），前端可直接渲染成卡片；
      * ``rules``  —— 注入系统提示的六段结构规则（生成侧软约束）；
      * ``audit``  —— 传入 ``answer`` 时，对回答做结构自检（判定侧硬结果）。

    ``card`` 之所以不走模型：边界必须与「创建前预览」「会话中提示」两处完全一致，
    而任何经模型的改写都会让两处口径漂移。
    """
    from app.core.answer_shape import audit, audit_hint, card, rules

    role = str(payload.get("role") or "GENERAL")
    out = {"card": card(role), "rules": rules(payload.get("scope") or None)}
    answer = payload.get("answer")
    if answer is not None and str(answer).strip():
        result = audit(str(answer))
        result["hint"] = audit_hint(result)
        out["audit"] = result
    logger.info("answer-shape role=%s audit=%s", role, "audit" in out)
    return out


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("bad request %s: %s", request.url.path, json.dumps(exc.errors(), ensure_ascii=False, default=str))
    return JSONResponse(status_code=422, content={"code": "BAD_REQUEST", "message": "invalid request body", "errors": exc.errors()})


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": str(exc)})
