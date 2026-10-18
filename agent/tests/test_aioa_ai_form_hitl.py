"""HITL 表单链（``request_form`` → ``need_form`` → ``resume`` 回执对象）测试。

复用 `test_aioa_ai_hitl.py` 的 harness 思路（provider / 上游 HTTP 全打桩，不连真实模型）。
对应判据：
  - **Q1 表单中断**：模型调 ``request_form`` ⇒ 产出 ``need_form``（含 form_code/reason/prefill）、
    且本段**不发** ``need_clarification``、也不发 ``run.completed``（是暂停，不是结束）；
  - **Q2 精确恢复**：resume 传**对象**回执 ⇒ 续跑完成、业务工具只执行一次（防副作用重复）、
    不再发 ``need_form``、首段只暂停一次；
  - **Q3 负向对照**：同样场景但模型调 ``ask_user`` ⇒ 仍发 ``need_clarification``（证明分帧不是恒定）；
  - **Q4** ``build_form_request`` 纯函数：缺 form_code ⇒ None；prefill 非 dict 被丢弃；
  - **Q5** ``_frame_type`` 纯函数：form / clarification 两种 payload 各自判定正确。

两条控制链（ask_user / request_form）共用 interrupt/resume/checkpoint 底座，不新建状态机。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from aioa_ai.contracts import RunRequest, UserContext
from aioa_ai.graph.facade import _frame_type
from aioa_ai.llm import Provider
from aioa_ai.tools import request_form as request_form_tool
from aioa_ai.tools.client import ToolClient, ToolOutcome

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOA_TEST_FAKE_KEY")


def _req(text: str = "帮我处理一下") -> RunRequest:
    return RunRequest(run_id="run_form_0001", conversation_id=1, text=text,
                      model_ref="fake", user_token="tok",
                      user_context=UserContext(user_id=1, tenant_id=1))


def _stub(stream_stub, *extra):
    return [
        patch("aioa_ai.entry.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


async def _enable_hitl():
    """打开开关 + 建内存 checkpointer + 重编译图（顺序不能反：先 setup 再 reset）。"""
    from aioa_ai.config import settings
    from aioa_ai.graph import builder, checkpoint

    settings.agent_hitl = True
    settings.checkpoint_url = ""            # 内存
    await checkpoint.setup()
    builder.reset()


async def _disable_hitl():
    from aioa_ai.config import settings
    from aioa_ai.graph import builder, checkpoint

    settings.agent_hitl = False
    await checkpoint.aclose()
    builder.reset()


def _control_scenario(control_name: str, control_args: dict, resume_answer):
    """跑一个「业务工具 → 内置控制工具 → 续跑」的三轮场景，返回 (first, second, tool_hits)。

    ``control_name`` 为 ``request_form`` 或 ``ask_user``；``resume_answer`` 为回填值
    （表单链传回执**对象**，澄清链传**标量**），用于验证两条链都能工作。
    """
    calls = {"n": 0}
    tool_hits = {"n": 0}
    ctrl_args_json = json.dumps(control_args, ensure_ascii=False)

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第 1 轮：先调一个业务工具（其结果必须被「冻结」到 resume 之后也不重跑）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "get_my_quota", "arguments": "{}"}}]},
                {"prompt_tokens": 5, "completion_tokens": 1})
        elif calls["n"] == 2:
            # 第 2 轮：调内置控制工具（本轮应暂停）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": control_name, "arguments": ctrl_args_json}}]},
                {"prompt_tokens": 5, "completion_tokens": 2})
        else:
            # 第 3 轮（resume 之后）：据回填答案作答
            for piece in "已收到，继续处理":
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "已收到，继续处理"},
                   {"prompt_tokens": 6, "completion_tokens": 3})

    async def counting_invoke(self, name, arguments=None):
        if name == "get_my_quota":
            tool_hits["n"] += 1
        return ToolOutcome(name=name, arguments=arguments or {}, ok=True, data={"left": 10})

    async def scenario():
        from aioa_ai import entry

        ctx = _stub(
            fake_stream,
            patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
                {"type": "function", "function": {"name": "get_my_quota",
                                                  "description": "q", "parameters": {}}}])),
            patch.object(ToolClient, "invoke", counting_invoke),
        )
        await _enable_hitl()
        for c in ctx:
            c.start()
        try:
            first = [(e.seq, e.type, e.data) async for e in entry.run(_req())]
            second = [(e.seq, e.type, e.data)
                      async for e in entry.resume("run_form_0001", resume_answer)]
        finally:
            for c in ctx:
                c.stop()
            await _disable_hitl()
        return first, second, tool_hits

    return asyncio.run(scenario())


def test_q1_request_form_emits_need_form(monkeypatch):
    """Q1：模型调 request_form ⇒ 只发 need_form，不发 need_clarification / run.completed，data 正确。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")
    first, _, _ = _control_scenario(
        "request_form",
        {"form_code": "leave_request", "reason": "需要请假信息才能送审",
         "prefill": {"startDate": "2026-10-18"}},
        {"form_code": "leave_request", "submission_id": 123, "status": "APPROVING",
         "data": {}, "receipt": {}},
    )

    types = [t for _, t, _ in first]
    assert "need_form" in types, f"应产出 need_form，实际={types}"
    assert "need_clarification" not in types, "表单链不得误发 need_clarification"
    assert "run.completed" not in types, "暂停不是结束：本轮不应发 run.completed"

    nf = next(d for _, t, d in first if t == "need_form")
    assert nf["form_code"] == "leave_request", nf
    assert nf["reason"] == "需要请假信息才能送审", nf
    assert nf["prefill"] == {"startDate": "2026-10-18"}, nf
    assert nf.get("kind") == "form", "form payload 应带 kind=form 标记"


def test_q2_resume_object_completes_and_no_repeat(monkeypatch):
    """Q2：resume 传回执对象 ⇒ 续跑完成、业务工具只执行一次、不再发 need_form、首段仅暂停一次。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")
    form_receipt = {
        "form_code": "leave_request", "submission_id": 123, "status": "APPROVING",
        "data": {"startDate": "2026-10-18"},
        "receipt": {"title": "请假已提交", "lines": [{"label": "开始", "value": "2026-10-18"}]},
    }
    first, second, tool_hits = _control_scenario(
        "request_form",
        {"form_code": "leave_request", "reason": "需要请假信息才能送审",
         "prefill": {"startDate": "2026-10-18"}},
        form_receipt,
    )

    # —— 续跑完成 ——
    types2 = [t for _, t, _ in second]
    assert "run.completed" in types2, f"resume 应跑完，实际={types2}"
    assert "need_form" not in types2, "已回填，不应再次暂停"

    # —— 精确恢复：已完成的业务工具不得重跑 ——
    assert tool_hits["n"] == 1, f"resume 不得重跑已完成工具，实际 {tool_hits['n']} 次"

    # —— 控制调用（request_form）只暂停一次：首段有且仅有 1 条 need_form ——
    types1 = [t for _, t, _ in first]
    assert types1.count("need_form") == 1, f"首段应只暂停一次，实际 need_form 次数={types1.count('need_form')}"


def test_q3_ask_user_still_need_clarification(monkeypatch):
    """Q3 负向对照：同样场景但模型调 ask_user ⇒ 仍发 need_clarification（证明分帧不是恒定）。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")
    first, _, _ = _control_scenario(
        "ask_user",
        {"question": "你要处理哪一类？", "options": [
            {"value": "contract", "label": "合同"},
            {"value": "expense", "label": "报销"}]},
        "contract",
    )

    types = [t for _, t, _ in first]
    assert "need_clarification" in types, f"ask_user 应仍发 need_clarification，实际={types}"
    assert "need_form" not in types, "ask_user 必须仍走 need_clarification，分帧不是恒定"
    nc = next(d for _, t, d in first if t == "need_clarification")
    assert nc["question"] == "你要处理哪一类？"
    assert [o["value"] for o in nc["suggested_options"]] == ["contract", "expense"]


def test_q4_build_form_request_pure():
    """Q4：build_form_request 纯函数行为。"""
    # 正常：保留 kind/form_code/reason/prefill
    ok = request_form_tool.build_form_request(
        {"form_code": "leave_request", "reason": "r", "prefill": {"a": 1}})
    assert ok == {"kind": "form", "form_code": "leave_request", "reason": "r", "prefill": {"a": 1}}, ok

    # 缺 form_code（各种形态）⇒ None（图据此剔除、不暂停）
    assert request_form_tool.build_form_request({"reason": "r"}) is None
    assert request_form_tool.build_form_request({}) is None
    assert request_form_tool.build_form_request(None) is None
    assert request_form_tool.build_form_request({"form_code": "   "}) is None

    # prefill 非 dict ⇒ 丢弃为空对象（绝不擅自制造字段）
    dropped = request_form_tool.build_form_request({"form_code": "x", "prefill": "notadict"})
    assert dropped["prefill"] == {}
    dropped2 = request_form_tool.build_form_request({"form_code": "x", "prefill": [1, 2]})
    assert dropped2["prefill"] == {}

    # reason 缺省为空串
    no_reason = request_form_tool.build_form_request({"form_code": "x"})
    assert no_reason["reason"] == ""
    assert no_reason["kind"] == "form"


def test_q5_frame_type_pure():
    """Q5：_frame_type 纯函数对两种 payload 的判定。"""
    # form 判定（两条互为兜底的路径）
    assert _frame_type({"kind": "form", "form_code": "leave_request"}) == "need_form"
    assert _frame_type({"form_code": "leave_request", "reason": "r"}) == "need_form"  # 无 question 兜底
    # 显式 kind=form 优先（即使混入 question）
    assert _frame_type({"kind": "form", "question": "x"}) == "need_form"
    # clarification 判定（历史 ask_user 形状）
    assert _frame_type({"question": "q", "suggested_options": []}) == "need_clarification"
    # 退化输入一律澄清帧（不会误判成表单）
    assert _frame_type("not a dict") == "need_clarification"
    assert _frame_type({}) == "need_clarification"
    assert _frame_type({"foo": 1}) == "need_clarification"


def test_form_hint_opens_form_when_model_does_not(monkeypatch):
    """``form_hint``（后端判定「单表单 + 用户点名任务」）：模型没调工具时**由图**补开表。

    为什么必须在图里补：``request_form`` 的语义是走到 ``clarify`` 节点 ``interrupt()``，
    只有 ``interrupt()`` 才把挂起态写进 checkpointer。若改由 Java 在流末补发一帧，
    图里没有断点，用户提交表单后 ``/resume`` 无从恢复（实测续跑零帧、模型不再确认）。
    本测试同时钉住两点：① 首段出 ``need_form`` 且 form_code 来自 hint；
    ② 续跑（``clarifications`` 已非空）**不得**再开一次表。
    """
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")
    calls = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        if calls["n"] == 1:
            # 典型失败形态：只在正文反问，不调任何工具
            for piece in ("请问您要办理哪项", "业务？"):
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "请问您要办理哪项业务？"},
                   {"prompt_tokens": 5, "completion_tokens": 3})
        else:
            yield ("delta", "已收到")
            yield ("done", {"role": "assistant", "content": "已收到"},
                   {"prompt_tokens": 6, "completion_tokens": 2})

    async def scenario():
        from aioa_ai import entry

        req = RunRequest(run_id="run_form_hint_0001", conversation_id=1,
                         text="帮我办理工会事项办理", model_ref="fake", user_token="tok",
                         user_context=UserContext(user_id=1, tenant_id=1),
                         available_forms=[{"code": "union_apply", "name": "工会事项申请"}],
                         form_hint={"form_code": "union_apply", "reason": "工会事项办理"})
        ctx = _stub(fake_stream,
                    patch.object(ToolClient, "list_tools", AsyncMock(return_value=[])))
        await _enable_hitl()
        for c in ctx:
            c.start()
        try:
            first = [(e.type, e.data) async for e in entry.run(req)]
            second = [(e.type, e.data)
                      async for e in entry.resume(req.run_id, {"form_code": "union_apply"})]
        finally:
            for c in ctx:
                c.stop()
            await _disable_hitl()
        return first, second

    first, second = asyncio.run(scenario())

    t1 = [t for t, _ in first]
    assert "need_form" in t1, f"模型没调工具时 form_hint 应在图里补开表，实际={t1}"
    nf = next(d for t, d in first if t == "need_form")
    assert nf["form_code"] == "union_apply", f"表单码应取自 form_hint，实际={nf}"
    assert "run.completed" not in t1, "开表是暂停，不是结束"

    t2 = [t for t, _ in second]
    assert "need_form" not in t2, f"续跑不得重复开表，实际={t2}"
    assert "run.completed" in t2, f"续跑应正常收尾，实际={t2}"
