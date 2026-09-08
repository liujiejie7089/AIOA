"""M2 真实运行时（DeepSeek Harness）单元测试：用 mock 驱动 httpx SSE 解析，

不依赖真实模型密钥即可验证：
  - 事件序列 run.started → message.delta×N → message.completed → run.completed
  - 多轮 delta 正确拼接
  - usage（token 计量）被正确提取，作为运营计费计量源头
  - 上游非 200 / 异常时按 error + run.failed 收口
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import agent_runtime
from app.schemas import PageContext, RunRequest, UserContext


def _make_req(model_ref: str | None = "deepseek") -> RunRequest:
    return RunRequest(
        run_id="r_test",
        conversation_id=1,
        text="hi",
        context=PageContext(appCode="ticket", page="list"),
        model_ref=model_ref,
        user_context=UserContext(user_id=1, tenant_id=0, roles=["ROLE_ADMIN"], trace_id="t"),
    )


async def _drain(req: RunRequest):
    return [ev async for ev in agent_runtime.run(req)]


def _fake_client(lines: list[str]):
    """构造一个 mock 的 httpx.AsyncClient，其 stream().aiter_lines() 产出给定 SSE 行。"""

    async def fake_aiter_lines():
        for ln in lines:
            yield ln

    resp = MagicMock()
    resp.status_code = 200
    resp.aread = AsyncMock(return_value=b"")
    resp.aiter_lines = fake_aiter_lines

    stream_cm = AsyncMock()
    stream_cm.__aenter__.return_value = resp
    stream_cm.__aexit__.return_value = False

    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client_cm
    client_cm.__aexit__.return_value = False
    client_cm.stream = MagicMock(return_value=stream_cm)
    return client_cm


def test_agent_runtime_streams_and_meters():
    os.environ["DEEPSEEK_API_KEY"] = "test-key"  # 让 gateway.resolve 认为已配置
    chunks = [
        '{"choices":[{"delta":{"role":"assistant"}}]}',
        '{"choices":[{"delta":{"content":"你好"}}]}',
        '{"choices":[{"delta":{"content":"世界"}}],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
        "[DONE]",
    ]
    lines = ["data: " + c for c in chunks] + [""]
    client_cm = _fake_client(lines)

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=client_cm):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert types[0] == "run.started", types
    assert types[-1] == "run.completed", types
    assert "message.completed" in types

    deltas = [e for e in events if e.type == "message.delta"]
    assert "".join(d.data["text"] for d in deltas) == "你好世界"

    completed = next(e for e in events if e.type == "message.completed")
    assert completed.data["usage"]["prompt_tokens"] == 5
    assert completed.data["usage"]["completion_tokens"] == 2

    run_done = events[-1]
    assert run_done.data["status"] == "SUCCEEDED"
    assert run_done.data["usage"]["completion_tokens"] == 2


def test_agent_runtime_upstream_error_is_caught():
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    resp = MagicMock()
    resp.status_code = 401
    resp.aread = AsyncMock(return_value=b'{"error":"unauthorized"}')
    stream_cm = AsyncMock()
    stream_cm.__aenter__.return_value = resp
    stream_cm.__aexit__.return_value = False
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client_cm
    client_cm.__aexit__.return_value = False
    client_cm.stream = MagicMock(return_value=stream_cm)

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=client_cm):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert "error" in types
    assert types[-1] == "run.failed"
    assert events[-1].data["error_code"] == "MODEL_UPSTREAM_ERROR"
