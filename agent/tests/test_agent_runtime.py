"""M2 真实运行时（DeepSeek Harness）单元测试：流式决策轮 + 工具循环 + 多工具并发。

不依赖真实模型密钥即可验证：
  - 事件序列 run.started → message.delta×N → message.completed → run.completed
  - usage（token 计量，多轮累加）被正确提取，作为运营计费计量源头
  - 工具循环：tool.call → tool.result → 结果回注 → 正文轮
  - 一轮内多个工具调用并发执行（改造前是串行）
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
    """支持 `async with httpx.AsyncClient() as http:` + `http.post(...)` 的 mock（非流式）。"""
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


# ---------- 流式 mock（httpx client.stream 的异步上下文管理器） ----------

class _AsyncCM:
    """`async with client.stream(...) as resp:` 的最小实现。"""

    def __init__(self, resp: MagicMock):
        self._resp = resp

    async def __aenter__(self) -> MagicMock:
        return self._resp

    async def __aexit__(self, *exc) -> bool:
        return False


def _frame(delta: dict) -> str:
    return "data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False)


def _usage_frame(usage: dict) -> str:
    return "data: " + json.dumps({"choices": [], "usage": usage}, ensure_ascii=False)


def _tool_frame(index: int, call_id: str | None = None, name: str | None = None,
                arguments: str | None = None) -> str:
    fn: dict = {}
    if name is not None:
        fn["name"] = name
    if arguments is not None:
        fn["arguments"] = arguments
    tc: dict = {"index": index, "function": fn}
    if call_id is not None:
        tc["id"] = call_id
    return _frame({"tool_calls": [tc]})


DONE = "data: [DONE]"


def _stream_resp(frames: list[str], status: int = 200, err_text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.aread = AsyncMock(return_value=err_text.encode("utf-8"))

    async def aiter_lines():
        for f in frames:
            yield f

    resp.aiter_lines = aiter_lines
    return resp


def _mock_stream_http(*rounds: MagicMock) -> MagicMock:
    """mock 出 `client.stream(...)`，每轮返回给定的 resp（按调用顺序）。

    必须包一层 _AsyncCM：MagicMock 自带的 __aenter__ 返回的是另一个 mock，
    `async with` 拿到的就不是我们要的 resp，status_code 会变成 mock 而误判为非 200。
    """
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.stream = MagicMock(side_effect=[_AsyncCM(r) for r in rounds])
    return http


def _tools(*names: str) -> list[dict]:
    return [{"type": "function", "function": {"name": n, "description": "x", "parameters": {}}}
            for n in names]


# ---------- 用例 ----------

def test_agent_runtime_streams_and_meters():
    """流式：上游分片直接转成 message.delta，usage 从 usage 帧提取。"""
    frames = [_frame({"content": "你好"}), _frame({"content": "世界"}),
              _usage_frame({"prompt_tokens": 5, "completion_tokens": 2}), DONE]
    http = _mock_stream_http(_stream_resp(frames))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert types[0] == "run.started", types
    assert types[-1] == "run.completed", types
    assert "message.completed" in types

    deltas = [e for e in events if e.type == "message.delta"]
    assert [d.data["text"] for d in deltas] == ["你好", "世界"], deltas
    assert "".join(d.data["text"] for d in deltas) == "你好世界"

    completed = next(e for e in events if e.type == "message.completed")
    assert completed.data["usage"]["prompt_tokens"] == 5
    assert completed.data["usage"]["completion_tokens"] == 2
    assert completed.data["tool_calls"] == []

    run_done = events[-1]
    assert run_done.data["status"] == "SUCCEEDED"
    assert run_done.data["usage"]["completion_tokens"] == 2


def test_agent_runtime_non_stream_fallback():
    """关闭流式开关时回退到非流式决策（本地切片为 delta，事件契约不变）。"""
    payload = _chat(_text_message("你好世界"), {"prompt_tokens": 5, "completion_tokens": 2})
    http = _mock_http()
    http.post = AsyncMock(return_value=_resp(payload))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(agent_runtime.settings, "agent_stream", False):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    deltas = [e for e in events if e.type == "message.delta"]
    assert "".join(d.data["text"] for d in deltas) == "你好世界"
    completed = next(e for e in events if e.type == "message.completed")
    assert completed.data["usage"]["prompt_tokens"] == 5


def test_agent_runtime_tool_loop():
    """工具循环：流式决策轮产出 tool_calls → 执行 → 结果回注 → 正文轮；usage 多轮累加。

    注意：agent_runtime 与 tools_client 引用同一个 httpx 模块单例，若同时按模块
    patch httpx.AsyncClient 会相互覆盖（后者胜出）。因此这里直接 mock
    ToolClient 的方法（工具网关 HTTP 契约由 test_tools_client.py 覆盖）。
    """
    round1 = [_tool_frame(0, "call_1", "list_my_approvals", "{}"), _frame({}),
              _usage_frame({"prompt_tokens": 30, "completion_tokens": 8}), DONE]
    round2 = [_frame({"content": "你有 2 条审批单"}),
              _usage_frame({"prompt_tokens": 60, "completion_tokens": 6}), DONE]
    http = _mock_stream_http(_stream_resp(round1), _stream_resp(round2))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(ToolClient, "list_tools", AsyncMock(return_value=_tools("list_my_approvals"))), \
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


def test_stream_tool_arguments_are_accumulated_across_chunks():
    """function.arguments 是分片到达的（OpenAI 流式事实），必须按 index 拼回完整 JSON。"""
    round1 = [
        _tool_frame(0, "call_1", "search_kb_documents"),
        _tool_frame(0, None, None, '{"keyword":'),
        _tool_frame(0, None, None, '"差旅"}'),
        _frame({}),
        _usage_frame({"prompt_tokens": 1, "completion_tokens": 1}),
        DONE,
    ]
    round2 = [_frame({"content": "见制度"}), _usage_frame({"prompt_tokens": 1, "completion_tokens": 1}), DONE]
    http = _mock_stream_http(_stream_resp(round1), _stream_resp(round2))

    seen: dict = {}

    async def fake_invoke(name, arguments):
        seen[name] = arguments
        return ToolOutcome(name=name, arguments=arguments, ok=True, data=[])

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(ToolClient, "list_tools", AsyncMock(return_value=_tools("search_kb_documents"))), \
         patch.object(ToolClient, "invoke", AsyncMock(side_effect=fake_invoke)):
        events = asyncio.run(_drain(_make_req(user_token="tok")))

    # 分片拼回完整 JSON：keyword 必须还原（检索类工具另会注入 topK/threshold 等专家参数）
    assert seen.get("search_kb_documents", {}).get("keyword") == "差旅", seen
    assert next(e for e in events if e.type == "tool.result").data["ok"] is True


def test_agent_runtime_runs_parallel_tool_calls():
    """一轮内 2 个独立工具调用应并发：两个 tool.call 都先于任何一个 tool.result。

    改造前是串行 for 循环，事件序为 call→result→call→result；并发后为 call→call→result→result。
    """
    async def slow_invoke(name, arguments):
        await asyncio.sleep(0.05)  # 慢工具：串行与并发的耗时差异可观测
        return ToolOutcome(name=name, arguments=arguments, ok=True, data=name)

    round1 = [
        _tool_frame(0, "c1", "get_my_quota", "{}"),
        _tool_frame(1, "c2", "list_my_approvals", "{}"),
        _frame({}),
        _usage_frame({"prompt_tokens": 9, "completion_tokens": 1}),
        DONE,
    ]
    round2 = [_frame({"content": "汇总完毕"}),
              _usage_frame({"prompt_tokens": 1, "completion_tokens": 1}), DONE]
    http = _mock_stream_http(_stream_resp(round1), _stream_resp(round2))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(ToolClient, "list_tools",
                      AsyncMock(return_value=_tools("get_my_quota", "list_my_approvals"))), \
         patch.object(ToolClient, "invoke", AsyncMock(side_effect=slow_invoke)):
        events = asyncio.run(_drain(_make_req(user_token="tok")))

    tool_events = [e for e in events if e.type in ("tool.call", "tool.result")]
    assert [e.type for e in tool_events] == ["tool.call", "tool.call", "tool.result", "tool.result"], \
        [e.type for e in tool_events]
    names = {e.data["name"] for e in tool_events if e.type == "tool.call"}
    assert names == {"get_my_quota", "list_my_approvals"}, names

    completed = next(e for e in events if e.type == "message.completed")
    assert [c["name"] for c in completed.data["tool_calls"]] == ["get_my_quota", "list_my_approvals"]


def test_agent_runtime_parallel_can_be_disabled():
    """关闭并发开关后回落串行：call→result→call→result（事件契约不变）。"""
    round1 = [
        _tool_frame(0, "c1", "get_my_quota", "{}"),
        _tool_frame(1, "c2", "list_my_approvals", "{}"),
        _frame({}),
        _usage_frame({"prompt_tokens": 9, "completion_tokens": 1}),
        DONE,
    ]
    round2 = [_frame({"content": "ok"}), _usage_frame({"prompt_tokens": 1, "completion_tokens": 1}), DONE]
    http = _mock_stream_http(_stream_resp(round1), _stream_resp(round2))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(agent_runtime.settings, "agent_parallel_tools", False), \
         patch.object(ToolClient, "list_tools",
                      AsyncMock(return_value=_tools("get_my_quota", "list_my_approvals"))), \
         patch.object(ToolClient, "invoke",
                      AsyncMock(side_effect=lambda n, a: ToolOutcome(name=n, arguments=a, ok=True, data=n))):
        events = asyncio.run(_drain(_make_req(user_token="tok")))

    tool_events = [e.type for e in events if e.type in ("tool.call", "tool.result")]
    assert tool_events == ["tool.call", "tool.result", "tool.call", "tool.result"], tool_events


def test_agent_runtime_kb_citations():
    """知识库检索工具的结果回写 citations（FR-D5 引用溯源），同文档去重。"""
    round1 = [_tool_frame(0, "call_1", "search_kb_documents", '{"keyword":"差旅"}'),
              _frame({}), _usage_frame({"prompt_tokens": 20, "completion_tokens": 5}), DONE]
    round2 = [_frame({"content": "相关制度见知识库"}),
              _usage_frame({"prompt_tokens": 40, "completion_tokens": 4}), DONE]
    http = _mock_stream_http(_stream_resp(round1), _stream_resp(round2))

    kb_rows = [{"id": 7, "docName": "差旅费管理办法"}, {"id": 3, "docName": "发文审批流程"},
               {"id": 7, "docName": "差旅费管理办法"}]  # 重复 id 应去重
    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http), \
         patch.object(ToolClient, "list_tools", AsyncMock(return_value=_tools("search_kb_documents"))), \
         patch.object(ToolClient, "invoke",
                      AsyncMock(return_value=ToolOutcome(name="search_kb_documents",
                                                         arguments={"keyword": "差旅"},
                                                         ok=True, data=kb_rows))):
        events = asyncio.run(_drain(_make_req(user_token="tok")))

    completed = next(e for e in events if e.type == "message.completed")
    assert completed.data["citations"] == [
        {"docId": 7, "title": "差旅费管理办法", "source": "knowledge_base"},
        {"docId": 3, "title": "发文审批流程", "source": "knowledge_base"},
    ], completed.data["citations"]
    assert completed.data["tool_calls"][0]["name"] == "search_kb_documents"


def test_build_messages_history():
    """history 中的 user/assistant/system 消息按序进入上下文（FR-C2 多轮会话）。"""
    req = _make_req()
    req.history = [
        {"role": "user", "content": "上一问"},
        {"role": "assistant", "content": "上一答"},
        {"role": "tool", "content": "应被过滤"},
        {"role": "user", "content": ""},  # 空内容过滤
    ]
    msgs = agent_runtime._build_messages(req)
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user"], roles
    assert msgs[-1]["content"] == "hi"


def test_agent_runtime_upstream_error_is_caught():
    """上游非 200（流式路径）：按 error + run.failed 收口，错误码 MODEL_UPSTREAM_ERROR。"""
    http = _mock_stream_http(_stream_resp([], status=401, err_text='{"error":"unauthorized"}'))

    with patch("app.core.agent_runtime.httpx.AsyncClient", return_value=http):
        events = asyncio.run(_drain(_make_req()))

    types = [e.type for e in events]
    assert "error" in types
    assert types[-1] == "run.failed"
    assert events[-1].data["error_code"] == "MODEL_UPSTREAM_ERROR"
