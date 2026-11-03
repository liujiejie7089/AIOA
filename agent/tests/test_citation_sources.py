# -*- coding: utf-8 -*-
"""引用来源：把三方数据源与内部模块也纳入溯源。

## 为什么需要

改造前 ``_citations_from_tool`` 只认两个工具（``search_kb_documents`` / ``web_search``）。
后果是「本周周报总结」这类**跨源聚合**回答里，用企微会话、邮箱、审批数据拼出来的内容
一条来源都不标 —— 用户无法判断哪句来自他自己的聊天记录、哪句来自公司制度文档，
而这正是「智能数据聚合」必须成立的前提。

## 口径

  S1  MCP 工具 → 来源 = serverCode（``mcp__wecom_cli__x`` ⇒ ``wecom_cli``）
  S2  网关工具 → 查 ``GATEWAY_TOOL_SOURCES``；未登记 = 不是数据源，不产引用
  S3  能挖到条目标题 ⇒ **条目级**引用（每封邮件/每份文档各一条，单次上限 6 条）
  S4  挖不到但确有数据 ⇒ **调用级**引用（「企业微信 · 最近会话」）
  S5  空结果不产引用（「查了没查到」不是来源，标出来会误导）
  S6  ``web_search`` / ``search_kb_documents`` 的既有形状**逐字不变**
      （只追加 label/action 两个新键，老字段不动）
  S7  未登记的 code 回退成 code 本身，绝不返回空串（否则引用区会显示空白）
"""
from __future__ import annotations

from aios_ai.knowledge import sources
from aios_ai.knowledge.kb import KB_TOOL, _citations_from_tool


class _Outcome:
    """最小 outcome 替身：只需 .ok / .data（与 ToolOutcome 的可观测面一致）。"""

    def __init__(self, ok=True, data=None):
        self.ok = ok
        self.data = data


# ---------------------------------------------------------------- S1 / S2 来源判定

def test_mcp_tool_source():
    assert sources.tool_source("mcp__wecom_cli__contact_search") == "wecom_cli"
    assert sources.tool_source("mcp__qq_mail__list_messages") == "qq_mail"
    # 未登记的新连接器：仍然反解出 serverCode，而不是丢弃
    assert sources.tool_source("mcp__dingtalk__list_chats") == "dingtalk"


def test_gateway_tool_source():
    assert sources.tool_source("list_my_approvals") == "approval"
    assert sources.tool_source("search_kb_documents") == "knowledge_base"
    # 交互工具不是数据源
    assert sources.tool_source("ask_user") == ""
    assert sources.tool_source("request_form") == ""
    assert sources.tool_source("web_fetch") == ""


def test_label_fallback():
    assert sources.source_label("wecom_cli") == "企业微信"
    assert sources.source_label("qq_mail") == "QQ邮箱"
    # S7：未登记不空
    assert sources.source_label("feishu") == "feishu"
    assert sources.source_label(None) == ""


# ---------------------------------------------------------------- S3 条目级

def test_wecom_item_citations():
    out = _citations_from_tool("mcp__wecom_cli__session_messages", _Outcome(data=[
        {"msgId": "m1", "content": "周报我周五发"},
        {"msgId": "m2", "content": "项目 A 已上线"},
    ]))
    assert len(out) == 2
    assert out[0]["source"] == "wecom_cli"
    assert out[0]["label"] == "企业微信"
    assert out[0]["docId"] == "wecom_cli:m1"
    assert "周报" in out[0]["title"]


def test_mail_item_citations_prefer_subject():
    out = _citations_from_tool("mcp__qq_mail__list_messages", _Outcome(data=[
        {"msgId": "9", "subject": "Q4 预算评审", "snippet": "请本周内确认"},
    ]))
    assert len(out) == 1
    # subject 优先级高于 snippet
    assert out[0]["title"] == "Q4 预算评审"


def test_approval_item_citations():
    out = _citations_from_tool("list_my_approvals", _Outcome(data=[
        {"id": 7, "title": "张三的请假申请（2 天）", "status": "APPROVED"},
    ]))
    assert out[0]["source"] == "approval"
    assert out[0]["label"] == "审批"
    assert out[0]["docId"] == "approval:7"


def test_citations_capped_per_call():
    """S3 上限：一次 list_messages 回 200 封邮件不该把 citations 撑爆。"""
    data = [{"msgId": str(i), "subject": f"邮件 {i}"} for i in range(50)]
    out = _citations_from_tool("mcp__qq_mail__list_messages", _Outcome(data=data))
    assert len(out) == sources.MAX_CITATIONS_PER_CALL


# ---------------------------------------------------------------- S4 调用级

def test_call_level_when_no_item_titles():
    out = _citations_from_tool("mcp__wecom_cli__recent_group_sessions",
                               _Outcome(data=[{"chat_id": "c1"}, {"chat_id": "c2"}]))
    assert len(out) == 1
    assert out[0]["source"] == "wecom_cli"
    # 标题形如「企业微信 · 最近会话（2 条）」
    assert "最近会话" in out[0]["title"]
    assert "2 条" in out[0]["title"]


def test_dict_payload_gets_call_citation():
    out = _citations_from_tool("mcp__wecom_cli__whoami", _Outcome(data={"name": "张三"}))
    assert len(out) == 1
    assert out[0]["action"] == "当前身份"


# ---------------------------------------------------------------- S5 空结果

def test_empty_result_no_citation():
    for empty in (None, "", [], {}):
        assert _citations_from_tool("mcp__wecom_cli__todo_list", _Outcome(data=empty)) == []


def test_failed_tool_no_citation():
    assert _citations_from_tool("mcp__wecom_cli__todo_list",
                                _Outcome(ok=False, data=[{"title": "x"}])) == []


# ---------------------------------------------------------------- S6 既有形状不变

def test_kb_shape_unchanged():
    out = _citations_from_tool(KB_TOOL, _Outcome(data=[{"id": 3, "docName": "员工手册.docx"}]))
    assert out[0]["docId"] == 3
    assert out[0]["title"] == "员工手册.docx"
    assert out[0]["source"] == "knowledge_base"
    # 老调用方只读这三个键，必须仍在
    assert {"docId", "title", "source"} <= set(out[0])


def test_web_shape_unchanged():
    out = _citations_from_tool("web_search", _Outcome(data={
        "results": [{"url": "https://example.com/a", "title": "示例"}]}))
    assert out[0]["docId"] == "https://example.com/a"
    assert out[0]["source"] == "web"


# ---------------------------------------------------------------- 分组展示口径

def test_grouped_by_source_order_preserved():
    """前端按 label 分组：同源条目必须能聚到一起，且顺序稳定。"""
    items = []
    items += _citations_from_tool("mcp__wecom_cli__session_messages",
                                  _Outcome(data=[{"msgId": "a", "content": "会话一"}]))
    items += _citations_from_tool("list_my_approvals",
                                  _Outcome(data=[{"id": 1, "title": "请假单"}]))
    labels = [c["label"] for c in items]
    assert labels == ["企业微信", "审批"]
