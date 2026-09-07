"""Java aioa-server 回调客户端（M1 桩，M2 实现）。

调用契约（M2）：
    POST {AIOA_SERVER_BASE_URL}/internal/v1/tools/invoke
    Headers:
        Authorization: Bearer <service JWT>   # 由 Java 透传，agent 原样带回
        Content-Type: application/json
        X-Trace-Id: <user_context.trace_id>
    Body:
        {
          "run_id": str,
          "tool_code": str,          # 如 ticket.list / order.query
          "args": object,            # 工具入参（已按 schema 校验）
          "user_context": {...}      # 原样透传，Java 侧做鉴权与数据隔离
        }
    Response 200:
        { "ok": true, "data": object, "duration_ms": int, "summary": str }
    Response 非 200 / 超时：
        ok=false，agent 侧发 tool.result{ok:false} 并继续（不中断 run）
    约定：
        - 超时 10s，最多重试 1 次（仅对 5xx/网络错误）
        - 敏感入参在事件里以 args_masked 输出，原始 args 不出现在 SSE 中
"""
from __future__ import annotations

from typing import Any

from app.config import settings


async def invoke_tool(
    run_id: str,
    tool_code: str,
    args: dict[str, Any],
    user_context: dict[str, Any] | None = None,
    authorization: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """调用 Java 侧工具；M1 未实现。"""
    raise NotImplementedError("M2")


def base_url() -> str:
    """Java 后端地址（供 M2 使用）。"""
    return settings.aioa_server_base_url
