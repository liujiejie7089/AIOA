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
from app.schemas import RunRequest, SseEvent

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


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("bad request %s: %s", request.url.path, json.dumps(exc.errors(), ensure_ascii=False, default=str))
    return JSONResponse(status_code=422, content={"code": "BAD_REQUEST", "message": "invalid request body", "errors": exc.errors()})


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": str(exc)})
