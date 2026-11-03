# -*- coding: utf-8 -*-
"""跨源数据聚合：意图闸 / 工具解析 / 失败隔离 / 素材包口径。

## 为什么这些用例重要

聚合会**多发若干次工具调用**，所以两类错误代价都很高：
  * 误触发（用户只是问「我上周请了几天假」却扇出五个源）⇒ 慢且费配额；
  * 静默失败（某个源挂了却不说）⇒ 模型把半份数据写成完整周报，用户无法察觉。

故 A1–A3 锁触发面，A4–A6 锁「失败要说出来」，A7–A8 锁素材包形状。
"""
from __future__ import annotations

import asyncio

from aios_ai import aggregate as ag

# ---------------------------------------------------------------- A1–A3 意图闸

def test_aggregate_positive():
    for t in ("帮我总结一下这周的周报", "汇总本周工作进展", "写个日报", "复盘一下这个月",
              "出个述职材料", "最近的工作情况整理一下"):
        assert ag.is_aggregate_request(t), t


def test_aggregate_negative():
    """单点查询/寒暄不触发 —— 误触发要真金白银地多打几次工具。"""
    for t in ("我上周请了几天假", "你好", "帮我给张三发个消息",
              "周报模板在哪里", "周报怎么写", ""):
        assert not ag.is_aggregate_request(t), t


def test_template_question_not_aggregate():
    """问「怎么写周报」是要模板，不是要我们真去汇总。"""
    assert not ag.is_aggregate_request("周报模板给我一份")
    assert not ag.is_aggregate_request("周报的格式要求是什么")


# ---------------------------------------------------------------- A4 工具解析

def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_resolve_only_available_tools():
    tools = [_tool("mcp__wecom_cli__recent_group_sessions"), _tool("list_my_approvals")]
    pairs = ag.resolve_plan(tools)
    actual = {n for _, n in pairs}
    # 只解析出「本轮真的挂了」的两个；日历/邮箱没挂 ⇒ 静默跳过而不是报错
    assert actual == {"mcp__wecom_cli__recent_group_sessions", "list_my_approvals"}
    assert len(pairs) == 2


def test_resolve_prefers_same_code_server():
    """同名工具挂在多个 server 上时，优先选与计划 code 同名的那个。"""
    tools = [_tool("mcp__other__todo_list"), _tool("mcp__wecom_cli__todo_list")]
    pairs = ag.resolve_plan(tools, (ag.SourceCall("wecom_cli", "todo_list", {}, "待办", 1),))
    assert pairs[0][1] == "mcp__wecom_cli__todo_list"


def test_resolve_empty_when_no_tools():
    assert ag.resolve_plan([]) == []
    assert ag.resolve_plan(None) == []


# ---------------------------------------------------------------- A5–A6 执行与失败隔离

class _Outcome:
    def __init__(self, ok=True, data=None, error=""):
        self.ok = ok
        self.data = data
        self.error = error


class _FakeClient:
    """按工具名返回预置结果；``boom`` 里的工具抛异常，``slow`` 里的超时。"""

    def __init__(self, results, boom=(), slow=()):
        self.results = results
        self.boom = set(boom)
        self.slow = set(slow)
        self.calls: list[str] = []

    async def invoke(self, name, args=None):
        self.calls.append(name)
        if name in self.boom:
            raise RuntimeError("boom")
        if name in self.slow:
            await asyncio.sleep(5)
        return self.results.get(name, _Outcome(ok=True, data=[]))


TOOLS = [_tool("mcp__wecom_cli__recent_group_sessions"),
         _tool("mcp__wecom_cli__todo_list"),
         _tool("list_my_approvals")]


def test_gather_collects_and_isolates_failure():
    client = _FakeClient({
        "mcp__wecom_cli__recent_group_sessions": _Outcome(data=[{"chat_id": "c1"}]),
        "mcp__wecom_cli__todo_list": _Outcome(data=[{"title": "交周报"}]),
        "list_my_approvals": _Outcome(ok=False, error="gateway 502"),
    })
    results, citations = asyncio.run(ag.gather(client, TOOLS))
    by_label = {r.label: r for r in results}
    # 同一 code（wecom_cli）下的两个调用各自独立成条，不能互相覆盖
    assert by_label["最近会话"].ok is True
    assert by_label["待办"].ok is True
    # 网关失败只影响自己，不传染给其它源
    assert by_label["我的审批"].ok is False
    assert by_label["我的审批"].error == "gateway 502"
    assert sum(1 for r in results if r.ok) == 2


def test_gather_exception_does_not_raise():
    client = _FakeClient({}, boom={"mcp__wecom_cli__todo_list"})
    results, _ = asyncio.run(ag.gather(client, TOOLS))
    todo = [r for r in results if r.label == "待办"][0]
    assert todo.ok is False
    assert "boom" in todo.error


def test_gather_timeout_isolated(monkeypatch):
    monkeypatch.setattr(ag.plan, "SOURCE_TIMEOUT", 0.01)
    client = _FakeClient({"mcp__wecom_cli__todo_list": _Outcome(data=[])},
                         slow={"mcp__wecom_cli__todo_list"})
    results, _ = asyncio.run(ag.gather(client, TOOLS))
    todo = [r for r in results if r.label == "待办"][0]
    assert todo.ok is False
    assert "超时" in todo.error


def test_empty_source_is_success_not_failure():
    """「查到了但为空」是有效结论（本周没待办），必须区别于「没查成」。"""
    client = _FakeClient({"mcp__wecom_cli__todo_list": _Outcome(data=[])})
    results, _ = asyncio.run(ag.gather(client, TOOLS))
    todo = [r for r in results if r.label == "待办"][0]
    assert todo.ok is True
    assert todo.count == 0


def test_mcp_string_payload_parsed():
    """MCP 通道返回的是 JSON **字符串**；不解析就抽不出条目引用。"""
    client = _FakeClient({"mcp__wecom_cli__todo_list":
                          _Outcome(data='[{"title": "提交周报", "id": 1}]')})
    results, citations = asyncio.run(ag.gather(client, TOOLS))
    todo = [r for r in results if r.label == "待办"][0]
    assert todo.ok is True
    assert todo.count == 1
    assert any("提交周报" in c["title"] for c in citations)


# ---------------------------------------------------------------- A7–A8 素材包

def test_block_lists_failed_sources():
    results = [
        ag.SourceResult("wecom_cli", "最近会话", 10, ok=True, text="[会话]", count=1),
        ag.SourceResult("qq_mail", "邮件列表", 40, ok=False, error="未授权"),
    ]
    block = ag.build_block(results, 2)
    assert "成功 1 个源" in block
    assert "失败 1 个" in block
    # 关键：失败源必须显式出现，否则模型会当成「已覆盖」
    assert "本轮未能获取的源" in block
    assert "QQ邮箱" in block
    assert "未授权" in block


def test_block_requires_source_attribution():
    results = [ag.SourceResult("wecom_cli", "最近会话", 10, ok=True, text="x", count=1)]
    block = ag.build_block(results, 1)
    assert "据企业微信会话" in block
    assert "如实说明该源缺失" in block


def test_block_empty_when_no_results():
    assert ag.build_block([], 0) == ""


def test_block_includes_kb_hit():
    """内部知识库必须进来源覆盖面：命中了就写「已命中 N 个片段」。"""
    results = [ag.SourceResult("wecom_cli", "最近会话", 10, ok=True, text="x", count=1)]
    block = ag.build_block(results, 1, kb={"ok": True, "count": 3})
    assert "内部知识库" in block
    assert "已命中 3 个片段" in block
    assert "成功 2 个源" in block          # 1 个结构化源 + 知识库


def test_block_reports_kb_miss_honestly():
    """检索了但没命中 ≠ 没检索：要如实说「未命中」，不能让模型以为有依据。"""
    block = ag.build_block([], 0, kb={"ok": False, "count": 0})
    assert "未命中" in block
    assert "成功 0 个源" in block


def test_collect_noop_for_non_aggregate():
    client = _FakeClient({})
    block, cites, obs = asyncio.run(ag.collect(client, TOOLS, "我上周请了几天假"))
    assert (block, cites, obs) == ("", [], [])
    assert client.calls == []          # 一次工具都没打


# ---------------------------------------------------------------- A9 表单抑制

def test_strip_form_for_aggregate():
    """聚合轮次必须收起 request_form。

    实测（2026-11-03）：'总结一下我这周的工作，写个周报' 被 intake 判成公文起草意图，
    模型弹了一张「工作报告」空表 —— 5 个源的数据一条没用上，界面只有一张表。
    """
    from aios_ai.graph.nodes import strip_form_for_aggregate

    tools = [_tool("request_form"), _tool("search_kb_documents"), _tool("web_search")]
    kept = strip_form_for_aggregate(tools)
    assert [t["function"]["name"] for t in kept] == ["search_kb_documents", "web_search"]


def test_strip_form_idempotent():
    from aios_ai.graph.nodes import strip_form_for_aggregate

    tools = [_tool("search_kb_documents")]
    assert strip_form_for_aggregate(tools) == tools
