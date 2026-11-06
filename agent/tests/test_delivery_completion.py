"""agent loop 完成判定：纯函数 + 图级闭环（2026-11-06，docs/86）。

现场缺陷：用户说「帮我写一份周报」，代码已把多源素材注入 system，
模型只回「我先把本周的原始素材拉齐，再整理成周报。」就停了。
旧 loop 只要「本轮没有 tool_calls」就 finalize ⇒ 一句导语被当成最终答案，
run 记 SUCCEEDED，界面只剩导语 + 数据来源卡。

这里验的是三层：
  1. 完成判定本身（中间态必须判红、成稿必须判绿、闲聊不能被误伤）；
  2. 图级补齐（导语 ⇒ 真的回 agent 再跑一轮 ⇒ 最终 content 含成稿）；
  3. 补齐用尽（如实标注未完成 + 未决项，不伪装成功）。
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from aios_ai.contracts import RunRequest, UserContext
from aios_ai.graph import delivery
from aios_ai.llm import Provider

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOS_TEST_FAKE_KEY")

LEAD = "我先把本周的原始素材拉齐，再整理成周报。"
REPORT = (
    "\n\n一、本周进展\n"
    "1. 完成请假链路改造：后端表单提交现在会建立请假单并占用在途额度，据审批单据与知识库文档。\n"
    "2. 补齐跨源聚合：企业微信会话、待办、日历与邮箱邮件已纳入本周汇总范围，逐条核对了来源。\n"
    "3. 修复表单停止与内部字段外露两处体验问题，并新增回归判据，据本周会话记录。\n"
    "二、下周计划\n"
    "1. 跟进请假天数的派生口径，确认余额扣减与审批终态一致。\n"
    "2. 把管理端与用户端的错误提示口径统一。\n"
    "完成状态：已完成。\n"
    "已覆盖的需求：本周进展、下周计划、逐条来源标注。\n"
    "完成依据：据企业微信会话、待办清单、日历、邮箱邮件、审批单据与知识库检索片段。"
)


def _req(text: str = "帮我写一份周报") -> RunRequest:
    return RunRequest(run_id="run_delivery_0001", conversation_id=1, text=text,
                      model_ref="fake",
                      user_context=UserContext(user_id=1, tenant_id=1))


async def _collect(req: RunRequest):
    from aios_ai import entry

    out: list[tuple[int, str, dict]] = []
    async for event in entry.run(req):
        out.append((event.seq, event.type, event.data))
    return out


def _stub(stream_stub):
    return [
        patch("aios_ai.entry.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes._post_stream", stream_stub),
    ]


# ---------------------------------------------------------------- 1. 纯函数判定

@pytest.mark.parametrize("text,delivery_task,expect_ok", [
    ("", False, False),
    ("我先把本周的原始素材拉齐，再整理成周报。", True, False),
    ("请稍等，我正在为您查询审批记录。", False, False),
    ("以上就是初步内容，稍后补充完整。", False, False),
    ("剩余部分请自行处理。", False, False),
    (REPORT, True, True),
    ("你好", False, True),                       # 闲聊不得被误伤
    ("今天天气不错，适合出门。", False, True),    # 普通短答不得被误伤
    ("我先说结论：这份周报可以直接交付。", False, True),  # 有结论的短句不是计划句
])
def test_assess_delivery(text, delivery_task, expect_ok):
    ok, reason = delivery.assess_delivery(text, delivery_task)
    assert ok is expect_ok, f"reason={reason}"


def test_short_report_is_still_incomplete():
    """交付类任务即便有分节，太短也不算成稿（半份周报必须被拦下）。"""
    ok, reason = delivery.assess_delivery("一、本周进展\n1. 完成了一件事。", True)
    assert not ok and "过短" in reason


def test_delivery_without_evidence_is_incomplete():
    """有结构、够长，但完全不交代依据 ⇒ 仍不算完整交付。"""
    text = ("一、本周进展\n" + "1. 完成了若干项改造与联调工作，进度符合预期安排。\n" * 8)
    ok, reason = delivery.assess_delivery(text, True)
    assert not ok and ("依据" in reason or "结构" in reason)


@pytest.mark.parametrize("missing", ["完成状态", "已覆盖", "完成依据"])
def test_delivery_requires_all_three_elements(missing):
    """用户原话要求三要素齐全：缺任意一项（哪怕写了「数据来源」）都必须判红。"""
    text = ("一、本周进展\n" + "1. 完成了若干项改造与联调工作，据审批单据与本周会话记录。\n" * 8
            + "数据来源：企业微信会话、审批单据。\n")
    for k in delivery.DELIVERY_REQUIRED:
        if k != missing:
            text += f"{k}：已按要求交代。\n"
    ok, reason = delivery.assess_delivery(text, True)
    assert not ok and missing in reason, f"缺 {missing} 却判绿：{reason}"


def test_aggregated_request_is_always_delivery():
    assert delivery.is_delivery_request("你好", aggregated=True) is True
    assert delivery.is_delivery_request("你好", aggregated=False) is False


# ---------------------------------------------------------------- 2. 图级补齐

def test_graph_completes_half_answer(monkeypatch):
    """第一轮只回导语 ⇒ 真的回 agent 再跑一轮 ⇒ 最终 content 含成稿，且只收口一次。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    calls = {"n": 0, "messages": []}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        calls["messages"].append([dict(m) for m in messages])
        text = LEAD if calls["n"] == 1 else REPORT
        yield ("delta", text)
        yield ("done", {"role": "assistant", "content": text},
               {"prompt_tokens": 3, "completion_tokens": 20})

    ctx = _stub(fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    assert calls["n"] == 2, "必须真的回到 agent 再跑一轮补齐，而不是直接 finalize"
    # 第二轮上下文里带着「继续完成」指令
    assert any("继续完成" in str(m.get("content") or "")
               for m in calls["messages"][1]), "补齐指令没有回注给模型"
    # 补齐轮必须带上本轮 assistant 导语：模型要「接着写」就得看见自己上一句说了什么；
    # 且不能出现两条连续 user 消息（部分 openai_compatible 网关会直接 400）。
    tail = calls["messages"][1][-2:]
    assert [m.get("role") for m in tail] == ["assistant", "user"], (
        f"补齐轮上下文不是 assistant→user：{[m.get('role') for m in tail]}")
    assert LEAD in str(tail[0].get("content") or ""), "导语没有并入补齐轮上下文"
    roles = [m.get("role") for m in calls["messages"][1]]
    assert all(a != "user" or b != "user"
               for a, b in zip(roles, roles[1:])), f"出现连续 user 消息：{roles}"

    types = [t for _, t, _ in events]
    assert types[-2:] == ["message.completed", "run.completed"]
    assert types.count("message.completed") == 1

    completed = next(d for _, t, d in events if t == "message.completed")
    assert "一、本周进展" in completed["content"]
    assert "完成依据" in completed["content"]
    assert "我先把本周的原始素材拉齐" in completed["content"], "导语保留，成稿接在后面（无撤回通道）"
    deltas = "".join(d["text"] for _, t, d in events if t == "message.delta")
    assert deltas == completed["content"], "界面 delta 与落库 content 必须同源"


def test_graph_exhausted_is_honest(monkeypatch):
    """一直只给导语 ⇒ 用尽补齐轮数后如实标注未完成 + 未决项，绝不伪装成功。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    calls = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        yield ("delta", LEAD)
        yield ("done", {"role": "assistant", "content": LEAD},
               {"prompt_tokens": 3, "completion_tokens": 8})

    ctx = _stub(fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    assert calls["n"] == delivery.MAX_DELIVERY_RETRIES + 1
    completed = next(d for _, t, d in events if t == "message.completed")
    assert "本轮未完成" in completed["content"]
    assert "未决项" in completed["content"]
    assert "当前状态" in completed["content"]
    assert "下一步可行路径" in completed["content"]
    assert "待续" not in completed["content"]
    assert [t for _, t, _ in events].count("message.completed") == 1


def test_continuation_round_drops_hallucinated_tool_calls(monkeypatch):
    """真机缺陷（2026-11-06 MiniMax）：补齐轮模型惯性再吐 tool_calls。

    旧实现会让 `delivery_pending` 的 `not calls` 变假 ⇒ 补齐中断 ⇒ finalize 把
    「已完成的工具查询结果」清单当成交付还记 SUCCEEDED。补齐轮必须丢弃这些调用、
    只写正文，并保证上下文里没有孤儿 tool_calls / 两条连续 assistant。
    """
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    calls = {"n": 0, "messages": []}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        calls["messages"].append([dict(m) for m in messages])
        if calls["n"] == 1:
            yield ("delta", LEAD)
            yield ("done", {"role": "assistant", "content": LEAD},
                   {"prompt_tokens": 3, "completion_tokens": 8})
        else:
            # 第二轮：模型既吐了一点正文，又惯性返回 tool_calls（幻觉）
            yield ("delta", REPORT)
            yield ("done", {"role": "assistant", "content": REPORT,
                            "tool_calls": [{"id": "ghost", "type": "function",
                                            "function": {"name": "sql_query",
                                                         "arguments": "{}"}}]},
                   {"prompt_tokens": 9, "completion_tokens": 40})

    ctx = _stub(fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    assert calls["n"] == 2, "补齐轮不该再被路由去 tools"
    completed = next(d for _, t, d in events if t == "message.completed")
    assert "一、本周进展" in completed["content"], "成稿没写出来"
    assert "本轮未完成" not in completed["content"], "不该误标未完成"
    # 上下文里不能留下没有 tool 消息回应的孤儿 tool_calls
    assert not any(m.get("tool_calls") for m in calls["messages"][1]), \
        "补齐轮的幻觉 tool_calls 没有丢弃，会触发上游 400"
    roles = [m.get("role") for m in calls["messages"][1]]
    assert all(not (a == "user" and b == "user") and not (a == "assistant" and b == "assistant")
               for a, b in zip(roles, roles[1:])), f"消息序列不合法：{roles}"


def test_finalize_fallback_never_masquerades_as_delivery(monkeypatch):
    """零正文 + 一堆工具结果：finalize 的兜底清单不许被当成成稿，也不许静默记成功。

    这是真机在 MiniMax 通道跑出来的中间态（chat_message#2970 原文）：
    「已完成的工具查询结果：· list_todo_approvals：失败…」249 字、SUCCEEDED、无标注。
    """
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    rounds = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        rounds["n"] += 1
        # 每轮都返回空正文（模拟推理模型把内容全放进 reasoning_content）
        yield ("done", {"role": "assistant", "content": ""},
               {"prompt_tokens": 3, "completion_tokens": 0})

    ctx = _stub(fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    completed = next(d for _, t, d in events if t == "message.completed")
    run_done = next(d for _, t, d in events if t == "run.completed")
    assert "本轮未完成" in completed["content"], "空正文收口必须如实标注未完成"
    assert "未决项" in completed["content"] and "当前状态" in completed["content"]
    assert run_done.get("delivery_complete") is False, "不许把中间态记成完整交付"


def test_graph_normal_chat_has_no_extra_round(monkeypatch):
    """零回归：普通闲聊不得触发补齐自环。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    calls = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        yield ("delta", "你好")
        yield ("done", {"role": "assistant", "content": "你好"},
               {"prompt_tokens": 3, "completion_tokens": 2})

    ctx = _stub(fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req("你好")))
    finally:
        for c in ctx:
            c.stop()

    assert calls["n"] == 1
    completed = next(d for _, t, d in events if t == "message.completed")
    assert completed["content"] == "你好"
