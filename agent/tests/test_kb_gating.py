"""知识库检索门槛（docs/60 P0-3，2026-10-26）：闲聊分流 + 阈值保守默认。

旧行为的两处缺陷（未实现时下列断言会失败）：
  ① 「你好」也走预检索 ⇒ 问候语拖出「来源：xxx.docx」且污染上下文；
  ② 专家未配置 threshold ⇒ ``or 0.0`` 把「没配」当「配了 0」⇒ 向量召回 0 分结果
     也进参考块。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aios_ai.knowledge import retrieval
from aios_ai.tools.client import ToolClient

from tests.test_aios_ai_graph import _collect, _req, _stub

KB_DEF = {"type": "function", "function": {
    "name": "search_kb_documents", "description": "kb search",
    "parameters": {"type": "object", "properties": {}}}}


# ---------- ① is_chitchat 判定（纯函数，保守口径） ----------

def test_is_chitchat_positive():
    for t in ["你好", "您好！", "hi", "hello~", "在吗", "谢谢啦", "辛苦了！", "再见",
              "拜拜", "好的", "嗯嗯", "ok", "收到。", "早上好", "明白了"]:
        assert retrieval.is_chitchat(t), f"应判为闲聊：{t!r}"


def test_is_chitchat_negative():
    # 带实际内容的消息必须不命中（宁可漏判多检索一次，也不误判该查不查）
    for t in ["报销流程", "表格第三行是什么", "你好我要请假", "请问这是什么",
              "帮我看看附件里的数据", "谢谢，另外问一下报销额度"]:
        assert not retrieval.is_chitchat(t), f"不应判为闲聊：{t!r}"


def test_is_chitchat_length_guard():
    assert not retrieval.is_chitchat("好" * 25)  # 超长不算闲聊
    assert not retrieval.is_chitchat("")
    assert not retrieval.is_chitchat(None)


# ---------- ② 图级：闲聊跳过预检索、实义消息照常预检索 ----------

def _run_once(monkeypatch, text: str, invoke_mock, **req_kw):
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        yield ("done", {"role": "assistant", "content": "好"},
               {"prompt_tokens": 3, "completion_tokens": 1})

    ctx = _stub(None, fake_stream,
                patch.object(ToolClient, "list_tools",
                             AsyncMock(return_value=[KB_DEF])),
                patch.object(ToolClient, "invoke", invoke_mock))
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(text, user_token="tok", **req_kw)))
    finally:
        for c in ctx:
            c.stop()
    return events


def test_chitchat_skips_pre_retrieve(monkeypatch):
    """「你好」+ 知识库工具在表里 ⇒ 不得发起任何检索调用（invoke 零调用）。"""
    invoke = AsyncMock()
    _run_once(monkeypatch, "你好", invoke)
    invoke.assert_not_awaited()


def test_substantive_text_still_pre_retrieves(monkeypatch):
    """负向对照：实义消息（「报销制度是什么」）必须照常预检索。

    2026-11-06（docs/74 根因 5）起改为**多查询变体**：原句 + 清洗句各查一次，
    因此断言口径从「恰好一次」改为「至少一次」，并校验**首次调用用的是原句**
    （变体顺序即优先级，原句的正文召回不能被丢）。
    """
    async def invoke(name, args):
        return None  # pre_retrieve 对 falsy outcome 走「无数据」分支，足够判定

    invoke_mock = AsyncMock(side_effect=invoke)
    _run_once(monkeypatch, "报销制度是什么", invoke_mock)
    assert invoke_mock.await_count >= 1, "实义消息必须预检索"
    first = invoke_mock.await_args_list[0].args
    assert first[0] == "search_kb_documents", first
    assert first[1]["keyword"] == "报销制度是什么", first


# ---------- ③ 阈值：未配置走保守默认，显式配置（含 0）优先 ----------

def test_threshold_default_when_unset(monkeypatch):
    """expert_settings 不带 threshold ⇒ 预检索收到 DEFAULT_KB_THRESHOLD（0.5）。"""
    pre = AsyncMock(return_value=("", []))
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        yield ("done", {"role": "assistant", "content": "好"},
               {"prompt_tokens": 3, "completion_tokens": 1})

    ctx = _stub(None, fake_stream,
                patch.object(ToolClient, "list_tools",
                             AsyncMock(return_value=[KB_DEF])),
                patch("aios_ai.knowledge.retrieval.pre_retrieve", pre))
    for c in ctx:
        c.start()
    try:
        asyncio.run(_collect(_req("报销制度是什么", user_token="tok")))
    finally:
        for c in ctx:
            c.stop()
    # pre_retrieve(tool_client, text, top_k, threshold, mode, kb_scope)
    assert pre.await_args.args[3] == retrieval.DEFAULT_KB_THRESHOLD
    assert retrieval.DEFAULT_KB_THRESHOLD == 0.5


def test_threshold_explicit_config_wins(monkeypatch):
    """专家显式配置 threshold=0.2 ⇒ 0.2 优先于默认值（运营配置永远说了算）。"""
    pre = AsyncMock(return_value=("", []))
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        yield ("done", {"role": "assistant", "content": "好"},
               {"prompt_tokens": 3, "completion_tokens": 1})

    ctx = _stub(None, fake_stream,
                patch.object(ToolClient, "list_tools",
                             AsyncMock(return_value=[KB_DEF])),
                patch("aios_ai.knowledge.retrieval.pre_retrieve", pre))
    for c in ctx:
        c.start()
    try:
        asyncio.run(_collect(_req("报销制度是什么", user_token="tok",
                                  expert_settings={"threshold": 0.2})))
    finally:
        for c in ctx:
            c.stop()
    assert pre.await_args.args[3] == 0.2
