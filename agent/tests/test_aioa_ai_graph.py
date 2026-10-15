"""LangGraph 图运行时（``aioa_ai.graph``）冒烟测试。

不连真实模型：把 provider 解析与上游 HTTP 全部打桩，验证重建后的图产出的事件序列
与重建前契约一致：

    run.started → [tool.call → tool.result] → message.delta×N
                → message.completed → run.completed

（seq 从 1 单调递增；这是 Java / H5 唯一依赖的对外契约，必须逐项验到。）
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aioa_ai.contracts import RunRequest, UserContext
from aioa_ai.llm import Provider
from aioa_ai.tools.client import ToolClient, ToolOutcome

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOA_TEST_FAKE_KEY")


def _req(text: str = "你好", **kw) -> RunRequest:
    return RunRequest(run_id="run_test_0001", conversation_id=1, text=text,
                      model_ref="fake",
                      user_context=UserContext(user_id=1, tenant_id=1), **kw)


async def _collect(req: RunRequest) -> list[tuple[int, str, dict]]:
    from aioa_ai import entry

    out: list[tuple[int, str, dict]] = []
    async for event in entry.run(req):
        out.append((event.seq, event.type, event.data))
    return out


def _stub(resolve_patches, stream_stub, *extra):
    """把「分派解析 + 图内解析 + 上游调用」一起打桩，返回 contexts 列表。"""
    return [
        patch("aioa_ai.entry.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


def test_graph_streams_message(monkeypatch):
    """纯推理（无工具）：run.started → message.delta×2 → message.completed → run.completed。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        for piece in ("你", "好"):
            yield ("delta", piece)
        yield ("done", {"role": "assistant", "content": "你好"},
               {"prompt_tokens": 3, "completion_tokens": 2})

    ctx = _stub(None, fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    types = [t for _, t, _ in events]
    assert types[0] == "run.started"
    assert types[-2:] == ["message.completed", "run.completed"]
    assert set(types[1:-2]) == {"message.delta"}
    assert [s for s, _, _ in events] == list(range(1, len(events) + 1))

    deltas = "".join(d["text"] for _, t, d in events if t == "message.delta")
    assert deltas == "你好"

    completed = next(d for _, t, d in events if t == "message.completed")
    assert completed["content"] == "你好"
    assert completed["citations"] == []
    assert completed["tool_calls"] == []
    assert completed["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert events[0][2]["model"] == "fake-1" and events[0][2]["gateway_key"] == "fake"


def test_graph_tool_round(monkeypatch):
    """带一轮工具调用：message.delta 之前先出 tool.call / tool.result，且结果回注上下文。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")

    calls = {"n": 0}
    seen_messages: list[list[dict]] = []

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen_messages.append(list(messages))
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一轮：模型决定调工具（不带正文）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "get_my_quota", "arguments": "{}"}}]},
                {"prompt_tokens": 5, "completion_tokens": 1})
        else:
            # 第二轮：依据回注的工具结果作答
            for piece in ("剩余", "10"):
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "剩余10"},
                   {"prompt_tokens": 8, "completion_tokens": 2})

    ctx = _stub(
        None, fake_stream,
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
            {"type": "function", "function": {"name": "get_my_quota",
                                              "description": "q", "parameters": {}}}])),
        patch.object(ToolClient, "invoke", AsyncMock(return_value=ToolOutcome(
            name="get_my_quota", arguments={}, ok=True,
            data={"quota": 100, "used": 90, "left": 10}))),
    )
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(text="我还有多少额度", user_token="tok")))
    finally:
        for c in ctx:
            c.stop()

    types = [t for _, t, _ in events]
    assert types[0] == "run.started"
    assert types.count("tool.call") == 1 and types.count("tool.result") == 1
    # 工具事件必须早于正文分片
    assert types.index("tool.call") < types.index("message.delta")
    assert types[-2:] == ["message.completed", "run.completed"]
    assert [s for s, _, _ in events] == list(range(1, len(events) + 1))

    completed = next(d for _, t, d in events if t == "message.completed")
    assert completed["content"] == "剩余10"
    assert completed["tool_calls"] == [{"name": "get_my_quota", "arguments": {}, "ok": True}]
    assert completed["usage"] == {"prompt_tokens": 13, "completion_tokens": 3}

    # 第二轮模型调用必须能看到回注的工具结果（role=tool）
    assert calls["n"] == 2
    second = seen_messages[1]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in second)
