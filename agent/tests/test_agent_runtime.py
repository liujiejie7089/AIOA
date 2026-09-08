"""M2 真实运行时（DeepSeek Harness）单元测试：mock httpx 非流式决策轮 + 工具循环。

不依赖真实模型密钥即可验证：
  - 事件序列 run.started → message.delta×N → message.completed → run.completed
  - usage（token 计量，多轮累加）被正确提取，作为运营计费计量源头
  - 工具循环：tool.call → tool.result → 结果回注 → 正文轮
  - 上游非 200 / 异常时按 error + run.failed 收口
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import agent_runtime
from app.schemas import PageContext, RunRequest, UserContext
from app.tools_client import ToolClient, ToolOutcome


def _make_req(model_ref: str | None = "deepseek", user_token: str | None = None) -> RunRequest:
    return RunRequest(
        run_id="r_test",
        conversation_id=1,
        text="hi",
        context=PageContext(appCode="ticket", page="list"),
        model_ref=model_ref,
        user_token=user_token,
        user_context=UserContext(user_id=1, tenant_id=0, roles=["ROLE_ADMIN"], trace_id="t"),
    )


async def _drain(req: RunRequest):
    return [ev async for ev in agent_runtime.run(req)]


def _resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=payload)
    return resp


def _mock_http() -> MagicMock:
    """支持 `async with httpx.AsyncClient() as http:` 的 mock 客户端。"""
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.post = AsyncMock()
    return http


def _chat(message: dict, usage: dict | None = None) -> dict:
    data = {"choices": [{"message": message}]}
    if usage is not None:
        data["usage"] = usage
    return data


def _text_message(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _tool_call_message(calls: list[dict]) -> dict:
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": c["id"], "type": "function",
                            "function": {"name": c["name"],
                                         "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                           for c in calls]}


def test_agent_runtime_streams_and_meters():
    """无工具：非流式决策轮直接产出正文，本地切片为 delta，usage 透传。"""
    payload = _chat(_text_message("你好世界"), {"prompt_tokens": 5, "completion_tokens": 2})
    http = _mock_http()
    http.post = AsyncMock(return_value=_resp(payload))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http):
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
    assert completed.data["tool_calls"] == []

    run_done = events[-1]
    assert run_done.data["status"] == "SUCCEEDED"
    assert run_done.data["usage"]["completion_tokens"] == 2


def test_agent_runtime_tool_loop():
    """工具循环：决策轮产出 tool_calls → 执行 → 结果回注 → 正文轮汇总；usage 累加。

    注意：agent_runtime 与 tools_client 引用同一个 httpx 模块单例，若同时按模块
    patch httpx.AsyncClient 会相互覆盖（后者胜出）。因此这里直接 mock
    ToolClient 的方法（工具网关 HTTP 契约由 test_tools_client.py 覆盖）。
    """
    calls = [{"id": "call_1", "name": "list_my_approvals", "arguments": {}}]
    first = _chat(_tool_call_message(calls), {"prompt_tokens": 30, "completion_tokens": 8})
    second = _chat(_text_message("你有 2 条审批单"), {"prompt_tokens": 60, "completion_tokens": 6})
    http = _mock_http()
    http.post = AsyncMock(side_effect=[_resp(first), _resp(second)])

    tools = [{"type": "function", "function": {"name": "list_my_approvals",
                                               "description": "x", "parameters": {}}}]
    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(ToolClient, "list_tools", AsyncMock(return_value=tools)), \
         patch.object(ToolClient, "invoke",
                      AsyncMock(return_value=ToolOutcome(name="list_my_approvals",
                                                         arguments={}, ok=True, data=[]))):
        events = asyncio.run(_drain(_make_req(user_token="tok")))

    types = [e.type for e in events]
    assert types[0] == "run.started"
    assert "tool.call" in types and "tool.result" in types
    assert types[-1] == "run.completed"

    tool_call = next(e for e in events if e.type == "tool.call")
    assert tool_call.data["name"] == "list_my_approvals"

    completed = next(e for e in events if e.type == "message.completed")
    assert completed.data["tool_calls"][0]["name"] == "list_my_approvals"
    assert completed.data["tool_calls"][0]["ok"] is True
    # 两轮 usage 累加（决策轮 + 正文轮）
    assert completed.data["usage"]["prompt_tokens"] == 90
    assert completed.data["usage"]["completion_tokens"] == 14


def test_agent_runtime_upstream_error_is_caught():
    resp = MagicMock()
    resp.status_code = 401
    resp.text = '{"error":"unauthorized"}'
    http = _mock_http()
    http.post = AsyncMock(return_value=resp)

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert "error" in types
    assert types[-1] == "run.failed"
    assert events[-1].data["error_code"] == "MODEL_UPSTREAM_ERROR"
