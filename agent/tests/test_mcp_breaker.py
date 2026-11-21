"""MCP 工具熔断（docs/89 §8.2）。

线上现场：非遗数据库断连时，模型一轮内并发调 15 个 scfy 工具，全部 20s 超时、
全部 ok:false，页面出现「继续尝试其他接口」这种无法兑现的承诺。

两层保护（判据回被测面，铁律 7/12）：
  ① 单轮内同一 server 最多放行 MCP_MAX_CALLS_PER_SERVER 个真实调用（其余短路）；
  ② 同一 server 连续失败 MCP_FAILURES_TO_TRIP 次 ⇒ 本 run 后续调用全短路（跨轮）。
  ③ 短路调用**仍回注 ok=False 的 tool 消息**（协议要求），文案明确、不带上游原文。
  ④ 非 MCP 工具零影响；有任一成功即清零熔断态。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from aios_ai.graph import nodes
from aios_ai.tools.client import ToolClient, ToolOutcome

from tests.test_aios_ai_graph import _collect, _req, _stub


def _call(cid: str, name: str) -> dict:
    return {"id": cid, "name": name, "arguments": {}}


# ---------- 纯函数层 ----------

def test_plan_mcp_calls_limits_per_server_in_one_round():
    calls = [_call(f"c{i}", "mcp__scfy__project_count_by_area") for i in range(10)]
    calls.append(_call("other", "search_kb_documents"))
    executed, shorted = nodes._plan_mcp_calls(calls, None)

    mcp_executed = [c for c in executed if c["id"] != "other"]
    assert len(mcp_executed) == nodes.MCP_MAX_CALLS_PER_SERVER
    assert len(shorted) == 10 - nodes.MCP_MAX_CALLS_PER_SERVER
    assert [c["id"] for c in mcp_executed] == [f"c{i}" for i in range(nodes.MCP_MAX_CALLS_PER_SERVER)]
    assert [c["id"] for c in shorted] == [f"c{i}" for i in range(nodes.MCP_MAX_CALLS_PER_SERVER, 10)]
    # 上限短路不是数据源故障，文案必须区分（2026-11-20 真机缺陷）
    assert all(c["_breaker_reason"] == nodes.MCP_RATE_LIMIT_ERROR for c in shorted)
    # 非 MCP 工具不受上限影响
    assert any(c["id"] == "other" for c in executed)


def test_plan_mcp_calls_tripped_server_shorted_all():
    breakers = {"scfy": {"consecutive_failures": 3, "tripped": True}}
    calls = [_call("a", "mcp__scfy__project_count_by_area"),
             _call("b", "mcp__scfy__project_list_by_area"),
             _call("c", "mcp__qq_mail__mail_search")]
    executed, shorted = nodes._plan_mcp_calls(calls, breakers)

    assert [c["id"] for c in executed] == ["c"]
    assert [c["id"] for c in shorted] == ["a", "b"]
    assert all(c["_breaker_reason"] == nodes.MCP_BREAKER_ERROR for c in shorted)


def test_update_breakers_trips_after_consecutive_failures():
    out = nodes._update_breakers(None, [
        {"name": "mcp__scfy__a", "ok": False},
        {"name": "mcp__scfy__b", "ok": False},
    ])
    assert out["scfy"] == {"consecutive_failures": 2, "tripped": False}

    out = nodes._update_breakers(out, [{"name": "mcp__scfy__c", "ok": False}])
    assert out["scfy"] == {"consecutive_failures": 3, "tripped": True}


def test_update_breakers_success_resets():
    tripped = {"scfy": {"consecutive_failures": 9, "tripped": True}}
    out = nodes._update_breakers(tripped, [{"name": "mcp__scfy__a", "ok": True}])
    assert out["scfy"] == {"consecutive_failures": 0, "tripped": False}

    # 同 server 本轮有成功 ⇒ 失败不累加（真恢复优先于失败计数）
    out = nodes._update_breakers(tripped, [
        {"name": "mcp__scfy__a", "ok": True},
        {"name": "mcp__scfy__b", "ok": False},
    ])
    assert out["scfy"]["tripped"] is False


def test_update_breakers_other_server_unaffected():
    out = nodes._update_breakers({"qq_mail": {"consecutive_failures": 1, "tripped": False}},
                                 [{"name": "mcp__scfy__a", "ok": False}])
    assert out["qq_mail"] == {"consecutive_failures": 1, "tripped": False}
    assert "scfy" in out


def test_breaker_message_has_no_upstream_raw():
    # 熔断文案只说数据源不可用，不得带上游错误原文（铁律：原文只进日志）
    msg = nodes.MCP_BREAKER_ERROR
    assert "余额" not in msg and "HTTP" not in msg and "timed out" not in msg
    assert "不要继续尝试" in msg


# ---------- 图级：短路调用仍回注 tool 消息、触发熔断 ----------

def test_tools_node_shorts_excess_calls_and_keeps_tool_messages(monkeypatch):
    """一轮 10 个同 server 调用：只真实执行 4 个，其余 6 个短路但都回注。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    calls = {"n": 0}
    seen_messages: list[list[dict]] = []

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen_messages.append(list(messages))
        calls["n"] += 1
        if calls["n"] == 1:
            tcs = [{"id": f"c{i}", "type": "function",
                    "function": {"name": "mcp__scfy__project_count_by_area", "arguments": "{}"}}
                   for i in range(10)]
            yield ("done", {"role": "assistant", "content": None, "tool_calls": tcs},
                   {"prompt_tokens": 5, "completion_tokens": 1})
        else:
            yield ("done", {"role": "assistant", "content": "数据源暂时不可用"},
                   {"prompt_tokens": 8, "completion_tokens": 2})

    invoke_mock = AsyncMock(side_effect=lambda name, args: ToolOutcome(
        name=name, arguments=args, ok=False, error="调用非遗服务失败：timed out"))
    ctx = _stub(
        None, fake_stream,
        patch("aios_ai.graph.nodes.settings.mcp_hub_enabled", True),
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
            {"type": "function", "function": {"name": "mcp__scfy__project_count_by_area",
                                              "description": "q", "parameters": {}}}])),
        patch.object(ToolClient, "invoke", invoke_mock),
    )
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(text="非遗", user_token="tok")))
    finally:
        for c in ctx:
            c.stop()

    # 真实执行只 4 个，不是 10 个
    assert invoke_mock.await_count == nodes.MCP_MAX_CALLS_PER_SERVER
    result_events = [d for _, t, d in events if t == "tool.result"]
    assert len(result_events) == 10  # 每个 tool_call_id 都有结果事件
    shorted = [d for d in result_events if d.get("summary") == nodes.MCP_RATE_LIMIT_ERROR]
    assert len(shorted) == 10 - nodes.MCP_MAX_CALLS_PER_SERVER
    assert all("数据源不可用" not in str(d.get("summary") or "") for d in shorted)
    # 真机 21:19：模型把「本轮未调用」的 1411 条当成公开基准值写进回答，
    # 限流文案必须明确禁止引用未返回的任何数字/名录/记忆补数（铁律 7/12）。
    assert "记忆或常识补数" in nodes.MCP_RATE_LIMIT_ERROR
    assert "公开基准值" in nodes.MCP_RATE_LIMIT_ERROR

    # 第二轮模型必须看到全部 10 条 tool 消息（协议完整）
    second = seen_messages[1]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert len(tool_msgs) == 10
    assert {m["tool_call_id"] for m in tool_msgs} == {f"c{i}" for i in range(10)}
    breaker_msgs = [m for m in tool_msgs if nodes.MCP_RATE_LIMIT_ERROR in m["content"]]
    assert len(breaker_msgs) == 6
    for m in breaker_msgs:
        body = json.loads(m["content"])
        assert body["ok"] is False and body["data"] is None
        assert "timed out" not in body["error"]  # 上游原文不外发到模型文案


def test_breaker_state_trips_across_rounds(monkeypatch):
    """连续两轮失败后 tripped，第三轮全部短路（真实调用数不再增加）。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    seen_states: list[dict] = []

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        n = sum(1 for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))
        # 前 4 轮都试图调工具：第 1~3 轮真实执行（累计 3 次失败 ⇒ tripped），
        # 第 4 轮应被熔断短路、不再真实 invoke；第 5 轮纯文本收口。
        if n < 4:
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"r{n}c0", "type": "function",
                 "function": {"name": "mcp__scfy__a", "arguments": "{}"}}]},
                {"prompt_tokens": 1, "completion_tokens": 1})
        else:
            yield ("done", {"role": "assistant", "content": "数据源不可用，暂时无法查询"},
                   {"prompt_tokens": 1, "completion_tokens": 1})

    invoke_mock = AsyncMock(side_effect=lambda name, args: ToolOutcome(
        name=name, arguments=args, ok=False, error="上游失败"))

    # 用真实图跑三轮，观察 tool 调用次数不再增长
    async def run_and_count():
        from aios_ai import entry
        result = []
        async for ev in entry.run(_req(text="非遗", user_token="tok")):
            result.append(ev)
        return result

    ctx = _stub(
        None, fake_stream,
        patch("aios_ai.graph.nodes.settings.mcp_hub_enabled", True),
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
            {"type": "function", "function": {"name": "mcp__scfy__a",
                                              "description": "a", "parameters": {}}}])),
        patch.object(ToolClient, "invoke", invoke_mock),
    )
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(run_and_count())
    finally:
        for c in ctx:
            c.stop()

    types = [ev.type for ev in events]
    assert types[-2:] == ["message.completed", "run.completed"]
    # 第 1~3 轮各真实执行 1 次（累计 3 次失败 ⇒ tripped）；第 4 轮短路、0 次真实执行
    assert invoke_mock.await_count == nodes.MCP_FAILURES_TO_TRIP
    breaker_results = [ev.data for ev in events
                       if ev.type == "tool.result"
                       and ev.data.get("summary") == nodes.MCP_BREAKER_ERROR]
    assert len(breaker_results) >= 1
