"""FastAPI 应用：路由挂载、健康检查、SSE 运行接口、全局异常。"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app.core import multi_task, runtime
from app.core.events import to_frame
from app.core.guards import GuardError
from app.schemas import CompleteRequest, RunRequest, SseEvent, TaskPlanRequest

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


@app.post("/internal/v1/tasks")
async def create_task_plan(req: TaskPlanRequest, request: Request) -> StreamingResponse:
    """多任务协同：执行一份显式计划（子任务 + 依赖 + 入参引用），响应为 SSE 事件流。

    与 /internal/v1/runs 的区别：runs 由模型逐步决定调什么工具；tasks 由调用方
    先把计划写出来，运行时只负责「依赖分层 → 同层并发 → 依赖失败则下游跳过」。
    对应架构第 8 条「主 agent 编排式」的执行侧。
    """
    logger.info("task plan %s start: tasks=%d (trace=%s)", req.run_id, len(req.tasks),
                req.user_context.trace_id)

    async def event_stream():
        seq = 1
        try:
            async for event in multi_task.run(req):
                seq = event.seq + 1
                yield to_frame(event)
        except GuardError as exc:
            yield to_frame(SseEvent(seq=seq, type="error",
                                    data={"code": exc.code, "message": exc.message, "retryable": exc.retryable}))
            yield to_frame(SseEvent(seq=seq + 1, type="run.failed",
                                    data={"reason": exc.message, "error_code": exc.code}))
        except Exception as exc:
            logger.exception("task plan %s failed", req.run_id)
            yield to_frame(SseEvent(seq=seq, type="error",
                                    data={"code": "INTERNAL_ERROR", "message": str(exc), "retryable": True}))
            yield to_frame(SseEvent(seq=seq + 1, type="run.failed",
                                    data={"reason": str(exc), "error_code": "INTERNAL_ERROR"}))
        finally:
            logger.info("task plan %s finished", req.run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/internal/v1/models")
async def list_models_state() -> dict:
    """运维/管理端观测：当前注册表状态（密钥只暴露「是否已配置」）。"""
    from app.model_gateway import configured_providers, current_default_key

    return {"providers": configured_providers(), "default": current_default_key()}


@app.post("/internal/v1/models/check")
async def check_model(payload: dict) -> dict:
    """连通性校验：用**本进程实际会用的配置**（含管理端推送下来的 Key）打一次最小补全。

    校验必须在持有密钥的一侧做：服务端进程通常没有供应商 Key，由它直接探测会
    把「服务端没配 Key」误报成「模型连不通」。返回 {ok, message, latency_ms}。
    """
    import time

    import httpx

    from app.model_gateway import get_provider

    key = str(payload.get("key") or "").strip().lower()
    if not key:
        raise GuardError("BAD_REQUEST", "key 不能为空")
    provider = get_provider(key)
    if provider is None:
        return {"ok": False, "message": f"模型未注册：{key}（请先在管理端保存一次以推送配置）", "latency_ms": 0}
    if provider.driver == "echo":
        return {"ok": True, "message": "回声模型为本地兜底实现，无需联网校验", "latency_ms": 0}

    api_key = provider.api_key()
    if not api_key:
        return {"ok": False, "latency_ms": 0,
                "message": f"未配置 API Key：环境变量 {provider.api_key_env} 未设置，且管理端未填写密钥"}

    body: dict = {"model": provider.model, "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1, "stream": False}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=15) as client_http:
            resp = await client_http.post(
                provider.base_url.rstrip("/") + "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
        cost = int((time.time() - started) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "message": "连通性校验通过（HTTP 200）", "latency_ms": cost}
        return {"ok": False, "message": _describe_upstream(resp.status_code, resp.text or ""), "latency_ms": cost}
    except Exception as exc:  # noqa: BLE001
        cost = int((time.time() - started) * 1000)
        return {"ok": False, "message": f"连接失败：{exc}", "latency_ms": cost}


def _describe_upstream(status: int, body: str) -> str:
    detail = " ".join((body or "").split())
    if len(detail) > 160:
        detail = detail[:160] + "…"
    hint = {401: "API Key 无效或无权限", 403: "API Key 无效或无权限",
            404: "接口地址或模型名不存在（请检查接入地址与模型名）",
            429: "被供应商限流，请稍后重试"}.get(status, "供应商服务异常" if status >= 500 else "上游拒绝请求")
    return f"{hint}（HTTP {status}）" + (f"：{detail}" if detail else "")


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
    async with httpx.AsyncClient(timeout=120) as client_http:
        try:
            # 温度取模型配置（管理端可配），max_tokens 由调用方显式指定时才下发；
            # 请求体统一由 _post_non_stream 组装，避免「配了但没发出去」。
            message, usage = await _post_non_stream(
                client_http, provider, api_key, messages, None,
                getattr(provider, "temperature", 0.3) or 0.3, req.max_tokens)
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
