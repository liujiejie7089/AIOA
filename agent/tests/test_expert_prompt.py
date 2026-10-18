"""专家人设（V88 链路补齐）注入系统提示的单测。

覆盖 aios_ai.prompt.builder.build_messages 对 RunRequest.expert 的消费：
  E1 有 expert+prompt → 系统提示含「你是 AIOS 智能办公平台上的「公文写作专家」专家 AI」与提示词正文，
     且不含通用助手那句「你是 AIOS 智能办公基座（AI Office Agent）的对话助手」；
  E2 无 expert → 仍含通用助手那句（逐字回归）；
  E3 scope + expert 同时给 → 出现「你的职责边界」，且不含专家那句（worker 优先）；
  E4 expert 有 name 无 prompt → 仍是通用助手 + 追加「本次会话用户选择了「X」专家」；
  E5 expert 为 None / 空 dict → 与 E2 输出一致。

构造 RunRequest 直接调 build_messages，不需要后端。每条断言指向具体事实，未实现时应失败。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aios_ai.contracts import RunRequest, UserContext
from aios_ai.graph.nodes import filter_expert_tools
from aios_ai.llm import Provider
from aios_ai.prompt import builder
from aios_ai.tools.client import ToolClient

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOS_TEST_FAKE_KEY")


def _make_req(expert=None, scope=None) -> RunRequest:
    req = RunRequest(
        run_id="r_expert",
        conversation_id=1,
        text="帮我写一份通知",
        user_context=UserContext(user_id=1, tenant_id=1),
    )
    req.expert = expert
    req.scope = scope
    return req


def _system(messages: list[dict]) -> str:
    """取 system 消息正文（build_messages 始终把 system 放在消息列表首位）。"""
    return messages[0]["content"]


GENERAL_ASSISTANT = "你是 AIOS 智能办公基座（AI Office Agent）的对话助手"


def test_expert_with_prompt_replaces_general():
    """E1：有 expert+prompt → 专家身份 + 提示词正文，且无通用助手那句。"""
    req = _make_req(expert={
        "key": "doc_writer",
        "name": "公文写作专家",
        "system_prompt": "请按公文规范撰写，结构清晰、用语正式。",
    })
    sys_text = _system(builder.build_messages(req))
    assert "你是 AIOS 智能办公平台上的「公文写作专家」专家 AI" in sys_text, sys_text
    assert "请按公文规范撰写，结构清晰、用语正式。" in sys_text, sys_text
    assert GENERAL_ASSISTANT not in sys_text, "专家会话不应出现通用助手身份句"


def test_no_expert_keeps_general_verbatim():
    """E2：无 expert → 仍含通用助手那句（逐字回归）。"""
    req = _make_req(expert=None)
    sys_text = _system(builder.build_messages(req))
    assert GENERAL_ASSISTANT in sys_text, sys_text


def test_scope_beats_expert_worker_priority():
    """E3：scope + expert 同时给 → 职责边界出现，且不含专家那句（worker 优先）。"""
    req = _make_req(
        expert={"key": "doc_writer", "name": "公文写作专家",
                "system_prompt": "公文规范。"},
        scope={"name": "报销助手", "role": "GENERAL", "duty": "费用报销"},
    )
    sys_text = _system(builder.build_messages(req))
    assert "你的职责边界" in sys_text, "scope 应优先，出现职责边界"
    assert "你是 AIOS 智能办公平台上的「公文写作专家」专家 AI" not in sys_text, \
        "worker 优先，不应出现专家身份句"


def test_expert_name_without_prompt_appends_hint():
    """E4：expert 有 name 无 prompt → 通用助手 + 追加「本次会话用户选择了「X」专家」。"""
    req = _make_req(expert={"key": "translator", "name": "翻译专家"})
    sys_text = _system(builder.build_messages(req))
    assert GENERAL_ASSISTANT in sys_text, "无 prompt 时仍走通用助手"
    assert "本次会话用户选择了「翻译专家」专家，请围绕该领域回答。" in sys_text, sys_text


def test_expert_none_or_empty_same_as_no_expert():
    """E5：expert 为 None / 空 dict → 与 E2（无 expert）输出一致。"""
    base = _system(builder.build_messages(_make_req(expert=None)))
    none_out = _system(builder.build_messages(_make_req(expert=None)))
    empty_out = _system(builder.build_messages(_make_req(expert={})))
    assert none_out == base, none_out
    assert empty_out == base, empty_out
    assert GENERAL_ASSISTANT in none_out, none_out


# ===== 专家会话不暴露 request_form（V88 缺陷修复）=====
# 业务表单是数字员工的能力，专家 AI 是顾问；专家会话下发 request_form 会让模型把咨询当成办理
# （实测法律专家问「试用期最长多久」被弹「合同起草」表、正文为空）。
# filter_expert_tools 是确定性闸：有 expert 且无 scope 时剔掉 request_form，但仍保留 ask_user（澄清能力）。

RF_DEF = {"type": "function", "function": {"name": "request_form", "description": "f", "parameters": {}}}
ASK_DEF = {"type": "function", "function": {"name": "ask_user", "description": "a", "parameters": {}}}
KB_DEF = {"type": "function", "function": {"name": "kb_search", "description": "k", "parameters": {}}}
_SRC = [RF_DEF, ASK_DEF, KB_DEF]


def _names(tools: list[dict]) -> list[str]:
    return [(t.get("function", {}).get("name") or t.get("name")) for t in tools]


def test_expert_session_strips_request_form_keeps_ask_user():
    """F1：有 expert、无 scope ⇒ 不含 request_form，且仍含 ask_user（澄清能力保留）。"""
    out = filter_expert_tools(_SRC, {"key": "legal", "name": "法务专家"}, None)
    names = _names(out)
    assert "request_form" not in names, names
    assert "ask_user" in names, names
    assert "kb_search" in names, names


def test_expert_with_scope_keeps_forms():
    """F2：有 expert 且有 scope（办理类会话）⇒ 原样返回（零回归）。"""
    out = filter_expert_tools(_SRC, {"key": "legal", "name": "法务专家"},
                              {"name": "报销助手", "role": "GENERAL", "duty": "费用报销"})
    assert "request_form" in _names(out), "绑数字员工的办理类会话必须保留 request_form"


def test_no_expert_keeps_forms():
    """F3：无 expert（普通会话）⇒ 原样返回。"""
    out = filter_expert_tools(_SRC, None, None)
    assert "request_form" in _names(out), "无 expert 的普通会话必须保留 request_form"


# ===== 变异/接线证明：filter_expert_tools 是否真的接进了运行路径 =====
# F1-F3 只验证「闸函数本身」逻辑；下面这条直接跑图（打桩 list_tools 与上游），
# 断言专家会话实际下发给模型的工具里已不见 request_form —— 这才是「闸真的被调用」的证据。
# 把 nodes.py 里 `tools = filter_expert_tools(...)` 那行注释掉，本条应变红（回归为含 request_form）。

def _req(text: str = "你好", **kw) -> RunRequest:
    return RunRequest(run_id="run_test_0001", conversation_id=1, text=text,
                      model_ref="fake", user_context=UserContext(user_id=1, tenant_id=1), **kw)


async def _collect(req: RunRequest) -> list[tuple]:
    from aios_ai import entry
    out: list[tuple] = []
    async for event in entry.run(req):
        out.append((event.seq, event.type, event.data))
    return out


def _stub(stream_stub, *extra):
    return [
        patch("aios_ai.entry.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


def test_expert_session_gate_wired_in_graph(monkeypatch):
    """接线证明：专家会话（expert 无 scope）实际下发给模型的工具里不含 request_form，且仍含 ask_user。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    seen: list[list[str]] = []

    async def spy_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen.append([(t.get("function", {}).get("name") or t.get("name")) for t in (tools or [])])

        async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
            yield ("delta", "ok")
            yield ("done", {"role": "assistant", "content": "ok"}, {})

        async for item in fake_stream(http, provider, api_key, messages, tools, temperature):
            yield item

    ctx = _stub(spy_stream,
               patch.object(ToolClient, "list_tools", AsyncMock(return_value=[RF_DEF, ASK_DEF, KB_DEF])))
    for c in ctx:
        c.start()
    try:
        asyncio.run(_collect(_req(text="劳动合同的试用期最长多久",
                                 expert={"key": "legal", "name": "法务专家"})))
    finally:
        for c in ctx:
            c.stop()
    names = seen[0]
    assert "request_form" not in names, names
    assert "ask_user" in names, names
