"""对话级「本次对话不调用某连接器」开关（2026-10-31）。

用户口径：「关闭时**不解绑**连接器，只是本次对话不调用对应的应用」。
⇒ 本轮只屏蔽工具可见性，**不改任何持久状态**（授权 / trusted / manifest 可见性都不动）。

被测面（按铁律 7/12：判据回被测对象，不与被测对象同源）：
  ① prepare：被屏蔽连接器的 MCP 工具**不进**工具清单（模型看不到）；
     未被屏蔽的照常在（零回归：缺省时工具清单与改动前一致）。
  ② tools 节点：模型**硬编**出被屏蔽连接器的工具名时，执行前被拦下，
     但**仍回注一条 ok=False 的 tool 结果**（丢弃会让 tool_call_id 找不到对应
     tool 消息，上游判协议错误）。
  ③ 契约：disabled_connectors 缺省 ⇒ 一切行为与改动前逐字节一致。

⚠️ 两处口径说明（都是踩过的坑，别改回去）：
  · MCP 工具能不能进清单，取决于 ``settings.mcp_hub_enabled``（默认 false）。
    不显式打开，McpProvider.available() 返回 False ⇒ 工具清单里根本没有 MCP 工具，
    测试会以「断言不成立」的形式**假红**（与被测逻辑无关）。
  · ``message.completed`` 帧里**没有** tool_call_id —— tool_call_id 只存在于图状态的
    messages 里（tool 消息）。要判「tool_call_id 有对应结果」必须直接看 tools 节点
    返回的 messages，不能在事件帧里找。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from aios_ai.graph import nodes
from aios_ai.tools.client import ToolClient

from tests.test_aios_ai_graph import _collect, _req, _stub

MCP_TOOL = {
    "type": "function",
    "function": {
        "name": "mcp__wecom_cli__whoami",
        "description": "企业微信：我是谁",
        "parameters": {"type": "object", "properties": {}},
    },
}
OTHER_MCP_TOOL = {
    "type": "function",
    "function": {
        "name": "mcp__qq_mail__mail_search",
        "description": "邮箱搜索",
        "parameters": {"type": "object", "properties": {}},
    },
}
# 带 source 的形状（manifest 里可能带，也可能不带 —— 两条路径都要判）
MCP_TOOL_WITH_SOURCE = dict(MCP_TOOL, source="wecom_cli")


# ---------- 纯函数层：工具名 ↔ 连接器 code 的解析 ----------

def test_connector_of_tool_name():
    assert nodes._connector_of_tool_name("mcp__wecom_cli__whoami") == "wecom_cli"
    assert nodes._connector_of_tool_name("mcp__qq_mail__mail_search") == "qq_mail"
    # 非 MCP 工具 / 畸形名 → 空串（不得误判成某个连接器）
    assert nodes._connector_of_tool_name("search_kb_documents") == ""
    assert nodes._connector_of_tool_name("mcp__only_two") == ""
    assert nodes._connector_of_tool_name("") == ""
    assert nodes._connector_of_tool_name(None) == ""


def test_blocked_connector_calls():
    calls = [
        {"id": "c1", "name": "mcp__wecom_cli__whoami", "arguments": {}},
        {"id": "c2", "name": "mcp__qq_mail__mail_search", "arguments": {}},
        {"id": "c3", "name": "search_kb_documents", "arguments": {}},
    ]
    # 未屏蔽 → 不拦任何调用
    assert nodes._blocked_connector_calls(calls, None) == []
    assert nodes._blocked_connector_calls(calls, []) == []
    # 屏蔽 wecom_cli → 只拦它，别的照常
    blocked = nodes._blocked_connector_calls(calls, ["wecom_cli"])
    assert [c["id"] for c in blocked] == ["c1"]
    # 屏蔽多个 + 大小写/空白容错
    blocked = nodes._blocked_connector_calls(calls, [" wecom_cli ", "qq_mail"])
    assert [c["id"] for c in blocked] == ["c1", "c2"]


# ---------- 图级：prepare 的工具清单过滤 ----------

def _run_prepare(monkeypatch, mcp_tools, disabled):
    """跑一次 prepare，返回（交给模型的工具名列表, effective_params）。"""
    from aios_ai.config import settings

    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    # ⚠️ 不开这个开关，McpProvider.available() 为 False ⇒ 工具清单里根本没有 MCP 工具
    monkeypatch.setattr(settings, "mcp_hub_enabled", True, raising=False)
    captured: dict = {}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        # 真实流式协议是「先 delta 再 done」。只给 done 等于模拟「零正文回答」，
        # 会被完成判定闸判成中间态并触发补齐自环（补齐轮不挂工具，tools=None），
        # 与本用例要验的「prepare 工具清单过滤」无关。这里按真实协议发一条正常短答。
        captured["tools"] = list(tools or [])
        yield ("delta", "好")
        yield ("done", {"role": "assistant", "content": "好"},
               {"prompt_tokens": 3, "completion_tokens": 1})

    ctx = _stub(None, fake_stream,
                patch.object(ToolClient, "list_tools", AsyncMock(return_value=[])),
                patch.object(ToolClient, "list_mcp_tools",
                            AsyncMock(return_value=list(mcp_tools))))
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(disabled_connectors=disabled)))
    finally:
        for c in ctx:
            c.stop()
    completed = next((d for _, t, d in events if t == "message.completed"), {})
    return captured.get("tools") or [], completed.get("effective_params") or {}


def _names(tools) -> list[str]:
    return [t["function"]["name"] for t in tools if isinstance(t, dict) and t.get("function")]


def test_prepare_keeps_all_when_not_disabled(monkeypatch):
    """零回归基线：不传 disabled_connectors ⇒ 全部 MCP 工具照常在。"""
    tools, _ = _run_prepare(monkeypatch, [MCP_TOOL, OTHER_MCP_TOOL], None)
    names = _names(tools)
    assert "mcp__wecom_cli__whoami" in names
    assert "mcp__qq_mail__mail_search" in names


def test_prepare_drops_disabled_connector_tools(monkeypatch):
    """被屏蔽的连接器：其工具不进清单；未屏蔽的照常在。"""
    tools, effective = _run_prepare(monkeypatch, [MCP_TOOL, OTHER_MCP_TOOL], ["wecom_cli"])
    names = _names(tools)
    assert "mcp__wecom_cli__whoami" not in names, "被屏蔽连接器的工具不该出现在清单里"
    assert "mcp__qq_mail__mail_search" in names, "未屏蔽连接器不受影响"
    # 观测：effective_params 里要能解释「为什么模型没看到某个连接器的工具」
    assert effective.get("disabledConnectors") == ["wecom_cli"], effective.get("disabledConnectors")


def test_prepare_drops_by_source_even_without_name_hint(monkeypatch):
    """manifest 带 source 时按 source 判；两条路径都覆盖。"""
    tools, _ = _run_prepare(monkeypatch, [MCP_TOOL_WITH_SOURCE, OTHER_MCP_TOOL], ["wecom_cli"])
    names = _names(tools)
    assert "mcp__wecom_cli__whoami" not in names
    assert "mcp__qq_mail__mail_search" in names


def test_prepare_empty_disabled_is_noop(monkeypatch):
    """空表 / 空白项 ⇒ 等同不屏蔽（不能因为传了空数组就少工具）。"""
    tools, _ = _run_prepare(monkeypatch, [MCP_TOOL], [])
    assert "mcp__wecom_cli__whoami" in _names(tools)
    tools, _ = _run_prepare(monkeypatch, [MCP_TOOL], ["  "])
    assert "mcp__wecom_cli__whoami" in _names(tools)


# ---------- 节点级：tools 节点的执行前拦截 ----------

def _tools_state(disabled, calls):
    """构造 tools 节点的最小状态。"""
    return {
        "req": _req(disabled_connectors=disabled).model_dump(),
        "pending_calls": calls,
        "messages": [],
        "tool_calls_log": [],
        "citations": [],
        "search_params": (5, 0.5, "hybrid", "ALL"),
    }


def test_tools_node_blocks_disabled_connector_call():
    """模型硬编出被屏蔽连接器的工具 ⇒ 不执行，但回注 ok=False（不能丢 tool 消息）。

    直接调用 tools 节点（而不是跑整图）：tool_call_id 只存在于节点返回的 messages 里，
    事件帧里根本没有它 —— 在事件帧里找 tool_call_id 会假红。
    """
    invoked: list = []

    async def invoke_mock(self, name, arguments=None):   # 打在类上 ⇒ 会多传一个 self
        invoked.append(name)
        return None

    state = _tools_state(
        ["wecom_cli"],
        [
            {"id": "call_x", "name": "mcp__wecom_cli__whoami", "arguments": {}},
            {"id": "call_y", "name": "search_kb_documents", "arguments": {"query": "x"}},
        ],
    )
    with patch.object(ToolClient, "invoke", invoke_mock):
        out = asyncio.run(nodes.tools(state))

    # ① 被屏蔽的没执行；未屏蔽的照常执行
    assert invoked == ["search_kb_documents"], f"被屏蔽连接器的工具不该被执行，实际调了：{invoked}"

    # ② 每个 tool_call_id 都必须有对应的 tool 消息（否则上游判协议错误）
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    by_id = {m["tool_call_id"]: m for m in tool_msgs}
    assert set(by_id) == {"call_x", "call_y"}, by_id.keys()
    blocked = json.loads(by_id["call_x"]["content"])
    assert blocked["ok"] is False
    assert "已被关闭" in blocked["error"], blocked["error"]
    assert "未被解绑" in blocked["error"], blocked["error"]

    # ③ 调用日志里也要留痕（前端能看到「这一步失败了」）
    logged = {c["name"]: c for c in out["tool_calls_log"]}
    assert logged["mcp__wecom_cli__whoami"]["ok"] is False
    assert logged["search_kb_documents"]["ok"] is False


def test_tools_node_no_disabled_means_all_executed():
    """零回归基线：没传 disabled_connectors ⇒ 不拦任何调用。"""
    invoked: list = []

    async def invoke_mock(self, name, arguments=None):   # 打在类上 ⇒ 会多传一个 self
        invoked.append(name)
        return None

    state = _tools_state(None, [{"id": "call_x", "name": "mcp__wecom_cli__whoami",
                                 "arguments": {}}])
    with patch.object(ToolClient, "invoke", invoke_mock):
        out = asyncio.run(nodes.tools(state))

    assert invoked == ["mcp__wecom_cli__whoami"]
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["tool_call_id"] == "call_x"


# ---------- 图级：端到端（模型硬编 → 拦下 → 收尾如实告知） ----------

def test_graph_end_to_end_blocked_connector_is_not_invoked(monkeypatch):
    """整图跑一轮：模型硬编被屏蔽连接器的工具 ⇒ 该工具零执行，且日志里如实标失败。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    invoked: list = []
    rounds = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        rounds["n"] += 1
        if rounds["n"] == 1:
            # 第一轮：模型「硬编」一个被屏蔽连接器的工具调用
            yield ("done", {"role": "assistant", "content": "",
                            "tool_calls": [{"id": "call_x", "type": "function",
                                            "function": {"name": "mcp__wecom_cli__whoami",
                                                         "arguments": "{}"}}]},
                   {"prompt_tokens": 3, "completion_tokens": 1})
        else:
            # 第二轮：正常收尾（否则模型反复编同一个调用会空转）
            yield ("done", {"role": "assistant", "content": "该应用在本次对话中未启用。"},
                   {"prompt_tokens": 3, "completion_tokens": 1})

    async def invoke_mock(self, name, arguments=None):   # 打在类上 ⇒ 会多传一个 self
        invoked.append(name)
        return None

    ctx = _stub(None, fake_stream,
                patch.object(ToolClient, "list_tools", AsyncMock(return_value=[])),
                patch.object(ToolClient, "list_mcp_tools", AsyncMock(return_value=[])),
                patch.object(ToolClient, "invoke", invoke_mock))
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(disabled_connectors=["wecom_cli"])))
    finally:
        for c in ctx:
            c.stop()

    assert invoked == [], f"被屏蔽连接器的工具不该被执行，实际调了：{invoked}"
    completed = next(d for _, t, d in events if t == "message.completed")
    logged = {c["name"]: c for c in completed["tool_calls"]}
    assert logged["mcp__wecom_cli__whoami"]["ok"] is False, completed["tool_calls"]
    # 观测字段同样要带上，便于线上追「为什么模型没看到这个连接器」
    assert completed["effective_params"].get("disabledConnectors") == ["wecom_cli"]
