# -*- coding: utf-8 -*-
"""``request_confirm`` 确认链（2026-10-31 新增的第三条 HITL 链）。

为什么要这套断言：三条 HITL 链（ask_user / request_form / request_confirm）共用
interrupt 底座，靠 **payload 形状**区分发哪一帧。加第三条链时有四个必须改的点
（prepare 注入 / tools 过滤 / clarify 识别 / route 分支 + facade 帧判定），
漏任何一处的表现都是「静默降级」——最常见的是 ``_frame_type`` 没跟上，
确认帧被当成澄清帧发出去，前端渲染成**单选卡**，用户拿不到「确认 / 取消」两个按钮，
只能看到一个问题和一个「确认」提交键，需求当场作废且没人报错。

判据分组：
  C1 payload 归一化形状（标题缺省兜底 / 全空 ⇒ None / 按钮限长 / danger 只认真布尔）；
  C2 帧类型判定：confirm / form / clarify 三帧互不串台；
  C3 控制调用判定：三条链都算「控制调用」、都被 _drop_control_calls 剔除（绝不进业务网关）；
  C4 工具表注入：HITL 开 ⇒ request_confirm 在模型工具表里；关 ⇒ 逐字节不变（零回归）；
  C5 提示词纪律：危险动作必须走确认卡、且禁止在正文里索要确认。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from aios_ai.graph import nodes
from aios_ai.graph.facade import _frame_type
from aios_ai.tools import request_confirm as confirm_tool
from aios_ai.prompt.builder import build_messages


# --------------------------------------------------------------------------- C1 payload 归一化

def test_full_payload_shape() -> None:
    spec = confirm_tool.build_confirm_request({
        "title": "向张三发送这封邮件",
        "description": "收件人 1 人，发送后无法撤回。",
        "confirm_label": "确认发送",
        "cancel_label": "暂不发送",
        "danger": True,
    })
    assert spec is not None
    # kind 必须是 confirm：Java 侧与前端都只看这个键区分帧
    assert spec["kind"] == "confirm"
    assert spec["title"] == "向张三发送这封邮件"
    assert spec["description"] == "收件人 1 人，发送后无法撤回。"
    assert spec["confirm_label"] == "确认发送"
    assert spec["cancel_label"] == "暂不发送"
    assert spec["danger"] is True


def test_defaults_when_only_description() -> None:
    """只有描述没有标题 ⇒ 用默认标题兜底（描述已说明白了，弹比不弹好）。"""
    spec = confirm_tool.build_confirm_request({"description": "将删除 3 条历史记录"})
    assert spec is not None
    assert spec["title"] == "请确认是否继续", "缺标题时应给默认标题"
    assert spec["description"] == "将删除 3 条历史记录"
    assert spec["confirm_label"] == "确认"
    assert spec["cancel_label"] == "取消"
    assert spec["danger"] is False


def test_title_and_description_both_empty_is_rejected() -> None:
    """两个都空 ⇒ None：图会把这个调用当「无效内置调用」剔除后放行、不暂停。

    一个没有文案的空确认卡比不弹更糟 —— 用户不知道自己在确认什么。
    """
    assert confirm_tool.build_confirm_request({}) is None
    assert confirm_tool.build_confirm_request(None) is None
    assert confirm_tool.build_confirm_request({"title": "   ", "description": ""}) is None


def test_overlong_label_falls_back_not_truncated() -> None:
    """按钮文案超长：退回默认，**不截断**（截断会产出「确认发」这种残句，比默认值更难读）。"""
    spec = confirm_tool.build_confirm_request(
        {"title": "删除这 5 条记录", "confirm_label": "我确认要永久删除这些数据", "cancel_label": ""})
    assert spec is not None
    assert spec["confirm_label"] == "确认"
    assert spec["cancel_label"] == "取消"


def test_danger_only_accepts_real_boolean() -> None:
    """``danger`` 只认真布尔：字符串 "true" 不当真 —— 弱模型爱传字符串，误判会让删除操作低调通过。"""
    assert confirm_tool.build_confirm_request({"title": "删", "danger": "true"})["danger"] is False
    assert confirm_tool.build_confirm_request({"title": "删", "danger": True})["danger"] is True


# --------------------------------------------------------------------------- C2 帧类型判定

def test_frame_type_confirm() -> None:
    spec = confirm_tool.build_confirm_request({"title": "确认发送"})
    assert _frame_type(spec) == "need_confirm", "确认载荷必须判成 need_confirm 帧"


def test_frame_type_three_chains_do_not_cross() -> None:
    """三帧互不串台：漏改 _frame_type 会把确认降级成澄清（UI 立刻变成单选卡）。"""
    assert _frame_type({"kind": "confirm", "title": "t"}) == "need_confirm"
    assert _frame_type({"kind": "form", "form_code": "leave"}) == "need_form"
    assert _frame_type({"question": "你指的是哪一个？", "suggested_options": []}) == "need_clarification"
    assert _frame_type(None) == "need_clarification"      # 非 dict 兜底，不抛


# --------------------------------------------------------------------------- C3 控制调用判定

def test_three_chains_are_all_control_calls() -> None:
    for name in ("ask_user", "request_form", "request_confirm"):
        assert nodes._is_control_call(name), f"{name} 必须是内置控制调用"
    assert not nodes._is_control_call("web_search")
    assert not nodes._is_control_call(None)


def test_drop_control_calls_keeps_business_tools() -> None:
    """业务调用必须原样留下，控制调用一个不留（漏一个就会被当业务工具打进网关 ⇒ 404/越权）。"""
    calls = [{"name": "web_search"}, {"name": "request_confirm"},
             {"name": "list_my_permission_grants"}, {"name": "ask_user"},
             {"name": "request_form"}]
    left = nodes._drop_control_calls(calls)
    assert [c["name"] for c in left] == ["web_search", "list_my_permission_grants"]
    assert nodes._drop_control_calls(None) == []


# --------------------------------------------------------------------------- C4 工具表注入（零回归）

def test_route_routes_confirm_to_clarify(monkeypatch) -> None:
    """路由：request_confirm 与 ask_user / request_form 一样进 clarify（那里才 interrupt）。"""
    monkeypatch.setattr(nodes, "_hitl_enabled", lambda: True)
    st = {"pending_calls": [{"id": "c1", "name": "request_confirm",
                             "arguments": {"title": "确认发送"}}]}
    assert nodes.route_after_agent(st) == "clarify"


def test_route_ignores_confirm_when_hitl_off(monkeypatch) -> None:
    """HITL 关闭时绝不进 clarify —— 那里会 interrupt()，而关闭态没有 checkpointer，必抛。

    此时模型本不该拿到这个工具；若它（或因缓存/伪造）仍返回同名调用，宁可让它掉到 tools
    被当成未知业务工具失败，也不能把整条 run 打成异常。
    """
    monkeypatch.setattr(nodes, "_hitl_enabled", lambda: False)
    st = {"pending_calls": [{"id": "c1", "name": "request_confirm"}], "allow_tools": True}
    assert nodes.route_after_agent(st) == "tools"


def test_confirm_tool_schema_has_title_required() -> None:
    schema = confirm_tool.REQUEST_CONFIRM_TOOL
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "request_confirm"
    assert "title" in fn["parameters"]["required"], "title 必填，模型才知道该写什么"


# --------------------------------------------------------------------------- C5 提示词纪律

def _system_blob(text: str = "帮我发封邮件", run_id: str = "r_cfm") -> str:
    from aios_ai.contracts import RunRequest, UserContext

    req = RunRequest(run_id=run_id, conversation_id=1, text=text, user_token="t",
                     user_context=UserContext(user_id=2, tenant_id=1,
                                              username="zhangsan", roles=["ROLE_USER"]))
    return "\n".join(m.get("content") or "" for m in build_messages(req)
                     if m.get("role") == "system")


def test_prompt_has_confirm_discipline(monkeypatch) -> None:
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "agent_hitl", True, raising=False)
    blob = _system_blob()
    assert "request_confirm" in blob, "提示词未提及确认工具，模型不会用"
    assert "不要重复确认" in blob, "缺「已确认过就不再弹卡」的边界，用户会被反复拦截"
    assert "不要在正文里索要确认" in blob, "缺「禁止写『请回复确认』」的禁令，仍是文字流程"
    # 场景必须点名用户提的三类（发送 / 删除 / 提交），只写「危险动作」这种抽象词模型认不出场景
    assert "删除" in blob and "发送" in blob and "提交" in blob


# --------------------------------------------------------------------------- C6 整图层（interrupt → resume）
#
# 离线静态断言（C1–C5）证明不了「点了确认之后动作真的执行」：那是把
# ask_user / ToolClient / LangGraph checkpoint 串起来的结果。这里不连真实模型，
# 用与 test_aios_ai_hitl.py 同一套打桩跑完整图（依赖已在文件头导入）。

from aios_ai.contracts import RunRequest, UserContext
from aios_ai.llm import Provider
from aios_ai.tools.client import ToolClient, ToolOutcome

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOS_TEST_FAKE_KEY")


def _req(run_id: str, text: str = "把这封邮件发给张三") -> RunRequest:
    return RunRequest(run_id=run_id, conversation_id=1, text=text,
                      model_ref="fake", user_token="tok",
                      user_context=UserContext(user_id=1, tenant_id=1))


def _stub(stream_stub, *extra):
    return [
        patch("aios_ai.entry.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


async def _enable_hitl():
    from aios_ai.config import settings
    from aios_ai.graph import builder, checkpoint

    settings.agent_hitl = True
    settings.checkpoint_url = ""
    await checkpoint.setup()
    builder.reset()


async def _disable_hitl():
    from aios_ai.config import settings
    from aios_ai.graph import builder, checkpoint

    settings.agent_hitl = False
    await checkpoint.aclose()
    builder.reset()


def _confirm_stream():
    """一条「倒影」式假模型：每一轮只产一次 done（流式消费者以**最后一个** done 为准，
    一次调用里 yields 两个 done 会把 tool_calls 覆盖成正文 —— 那是桩写错，不是产品行为）。

      n=1 调 request_confirm（应暂停）
      n=2 看得见 decision=true ⇒ 调 send_mail；decision=false ⇒ 直接回「已取消」
      n=3 工具结果已回 ⇒ 回「已发送」
    """
    calls = {"n": 0}

    def _decision(messages):
        for m in messages:
            if m.get("role") != "tool":
                continue
            body = m.get("content") or ""
            try:
                payload = json.loads(body) if isinstance(body, str) else body
            except ValueError:
                continue
            answer = (payload or {}).get("data", {}).get("answer")
            if isinstance(answer, dict) and "decision" in answer:
                return bool(answer.get("decision"))
        return None

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        n = calls["n"]
        decided = _decision(messages)
        if n == 1:
            yield ("done", {"role": "assistant", "content": "好的，我先跟你确认一下。",
                            "tool_calls": [{"id": "c1", "type": "function",
                                            "function": {"name": "request_confirm",
                                                         "arguments": '{"title":"向张三发送这封邮件",'
                                                                      '"description":"收件人 1 人",'
                                                                      '"confirm_label":"确认发送",'
                                                                      '"danger":false}'}}]},
                   {"prompt_tokens": 6, "completion_tokens": 4})
        elif n == 2:
            assert decided is not None, "resume 的决策没有回填进模型上下文"
            if decided:
                # 确认 ⇒ 真的调用写工具（这是「点击确认执行对应操作」的落点）
                yield ("done", {"role": "assistant", "content": None,
                                "tool_calls": [{"id": "s1", "type": "function",
                                                "function": {"name": "send_mail",
                                                             "arguments": '{"to":"张三"}'}}]},
                       {"prompt_tokens": 7, "completion_tokens": 3})
            else:
                yield ("delta", "已取消")
                yield ("done", {"role": "assistant", "content": "已取消"},
                       {"prompt_tokens": 7, "completion_tokens": 2})
        else:
            yield ("delta", "已发送")
            yield ("done", {"role": "assistant", "content": "已发送"},
                   {"prompt_tokens": 8, "completion_tokens": 2})
    return fake_stream


def _run_confirm_scenario(run_id: str, decision: bool):
    tool_hits = {"send_mail": 0}

    async def counting_invoke(self, name, arguments=None):
        if name == "send_mail":
            tool_hits["send_mail"] += 1
        return ToolOutcome(name=name, arguments=arguments or {}, ok=True, data={"id": 7})

    async def scenario():
        from aios_ai import entry

        ctx = _stub(_confirm_stream(),
                    patch.object(ToolClient, "list_tools", AsyncMock(return_value=[])),
                    patch.object(ToolClient, "invoke", counting_invoke))
        await _enable_hitl()
        for c in ctx:
            c.start()
        try:
            first = [(e.seq, e.type, e.data) async for e in entry.run(_req(run_id))]
            second = [(e.seq, e.type, e.data)
                      async for e in entry.resume(run_id, {"decision": decision})]
        finally:
            for c in ctx:
                c.stop()
            await _disable_hitl()
        return first, second, tool_hits
    return asyncio.run(scenario())


def test_confirm_pause_then_decision_true_executes_write(monkeypatch):
    """Q1/Q3：确认链暂停发 need_confirm（不是 need_clarification），确认后真执行并把结果追加到对话。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    first, second, hits = _run_confirm_scenario("run_cfm_true_0001", True)

    types1 = [t for _, t, _ in first]
    assert "need_confirm" in types1, f"应产出 need_confirm，实际={types1}"
    assert "need_clarification" not in types1, "确认帧不得降级成澄清帧（UI 会变成单选卡）"
    assert "run.completed" not in types1, "暂停不是结束"

    frame = next(d for _, t, d in first if t == "need_confirm")
    assert frame["title"] == "向张三发送这封邮件"
    assert frame["description"] == "收件人 1 人"
    assert frame["confirm_label"] == "确认发送"
    assert frame["cancel_label"] == "取消"
    assert frame["danger"] is False

    # 确认 ⇒ 写工具被执行且只执行一次（resume 不重跑）
    assert hits["send_mail"] == 1, f"确认后必须执行一次发送，实际={hits['send_mail']}"
    completed = next(d for _, t, d in second if t == "message.completed")
    assert completed["content"] == "已发送", completed
    assert "need_confirm" not in [t for _, t, _ in second], "已回填，不应再次暂停"


def test_confirm_decision_false_never_touches_write_tool(monkeypatch):
    """取消分支的完整判据：decision=false ⇒ 写工具**一次都不被调用**，且不得以 run.failed 收口。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    first, second, hits = _run_confirm_scenario("run_cfm_false_0001", False)

    assert "need_confirm" in [t for _, t, _ in first]
    assert hits["send_mail"] == 0, f"取消后绝不能触达发送工具，实际调用 {hits['send_mail']} 次"
    types2 = [t for _, t, _ in second]
    assert "run.failed" not in types2, f"取消不是失败，实际={types2}"
    assert "run.completed" in types2, f"取消也要正常收口，实际={types2}"
    completed = next(d for _, t, d in second if t == "message.completed")
    assert completed["content"] == "已取消", completed


def test_prompt_omits_confirm_when_hitl_off(monkeypatch) -> None:
    """HITL 关闭时工具表里没有 request_confirm —— 提示词提它就是让模型幻觉调用不存在的工具。"""
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "agent_hitl", False, raising=False)
    assert "request_confirm" not in _system_blob(run_id="r_cfm_off")
