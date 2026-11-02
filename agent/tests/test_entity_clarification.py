# -*- coding: utf-8 -*-
"""模糊实体澄清：ask_user 轮「只澄清」的确定性闸 + 选项上限 10。

## 为什么要这套断言（2026-11-02 产品口径）

用户说「查我同事考勤」时，模型有两种坏习惯：
  ① 直接猜一个人（常常猜成用户自己）就把业务查询跑了；
  ② 只反问一句「是哪位同事？」，用户只能手打全名。

产品定的流程是：`contact_search` 枚举候选 → `ask_user` 把候选渲染成按钮 →
用户点了之后才用选中的 userid 执行原查询。其中**「本轮只澄清」必须是确定性闸**：
提示词挡不住模型在同一轮里先跑一遍查询，而那一跑会带着猜出来的 userid，
用户选完之后澄清卡下面就已经躺着一份「看起来很像对的」错误结果。

## 判据

  E1  ask_user 轮夹带的业务调用：pending_calls 清空、不执行
  E2  被丢弃的调用**必须补 tool 消息**（否则 assistant.tool_calls 悬空 ⇒ 下次请求 400）
  E3  被丢弃的调用要在 tool_calls_log 里留 SKIPPED 痕迹（审计不能「凭空少一次调用」）
  E4  request_confirm / request_form 链**不受影响**（余量照旧交回 tools，零回归）
  E5  ask_user 选项上限是 10（不是 6）：否则第 7~10 个候选被静默丢掉，用户选不到人
"""
from __future__ import annotations

import asyncio

import pytest

from aios_ai.graph import nodes
from aios_ai.tools import ask_user as ask_user_tool


def _calls(*names: str) -> list[dict]:
    return [{"id": f"c{i}", "name": n, "arguments": {"q": "x"}} for i, n in enumerate(names)]


def _state(*names: str) -> dict:
    calls = _calls(*names)
    return {
        "req": {"run_id": "r_entity"},
        "messages": [{"role": "assistant", "content": "",
                      "tool_calls": [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": "{}"}}
                                     for c in calls]}],
        "pending_calls": calls,
    }


def _run(state: dict, answer="wobVcoRgAAwZdjMSCNmVIBRHqFTQwuAQ", monkeypatch=None) -> dict:
    monkeypatch.setattr(nodes, "interrupt", lambda spec: answer)
    return asyncio.run(nodes.clarify(state))


# ---------------------------------------------------------------- E1~E3 只澄清

def test_ask_user_drops_business_calls_in_same_turn(monkeypatch) -> None:
    """模型「一边问是哪位同事、一边先查了考勤」⇒ 那次查询必须被整轮丢弃。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    assert out["pending_calls"] == [], "ask_user 轮不允许再把业务调用交给 tools 执行"
    assert out["clarifications"][0]["answer"].startswith("wob"), "用户的选择要落进 clarifications"


def test_dropped_call_gets_a_tool_message(monkeypatch) -> None:
    """丢弃必须补 tool 回包：assistant.tool_calls 有两个 id，就得有两条 tool 消息。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    ids = [m.get("tool_call_id") for m in tool_msgs]
    assert ids == ["c0", "c1"], f"控制调用 + 被丢弃调用各一条，实际 {ids}"
    skipped = [m for m in tool_msgs if "SKIPPED_PENDING_CLARIFICATION" in (m.get("content") or "")]
    assert len(skipped) == 1 and skipped[0]["tool_call_id"] == "c1"
    assert "未执行" in skipped[0]["content"], "要让模型看懂为什么没结果"


def test_dropped_call_is_audited(monkeypatch) -> None:
    """审计口径：被丢弃也要留痕，否则事后无法解释「这一轮为什么没查」。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    log = out["tool_calls_log"]
    assert len(log) == 1 and log[0]["status"] == "SKIPPED"
    assert log[0]["name"] == "mcp__wecom_cli__attendance_list"


def test_ask_user_alone_keeps_behaviour(monkeypatch) -> None:
    """只有 ask_user 时行为不变：仍是一条 tool 消息 + 不产生 SKIPPED 日志。"""
    out = _run(_state("ask_user"), monkeypatch=monkeypatch)
    assert out["pending_calls"] == []
    assert len([m for m in out["messages"] if m.get("role") == "tool"]) == 1
    assert not out.get("tool_calls_log")


# ---------------------------------------------------------------- E4 其它链零回归

def test_confirm_chain_still_forwards_business_calls(monkeypatch) -> None:
    """确认链的余量照旧交回 tools —— 这条是回归哨兵，别把闸门做成全局的。"""
    out = _run(_state("request_confirm", "mcp__qq_mail__send_draft"), monkeypatch=monkeypatch)
    assert [c["name"] for c in out["pending_calls"]] == ["mcp__qq_mail__send_draft"]


def test_form_chain_still_forwards_business_calls(monkeypatch) -> None:
    st = _state("request_form", "mcp__qq_mail__send_draft")
    # request_form 需要 form_code，否则 build_form_request 归一化失败、整轮不暂停
    st["pending_calls"][0]["arguments"] = {"form_code": "leave", "reason": "测试"}
    out = _run(st, monkeypatch=monkeypatch)
    assert [c["name"] for c in out["pending_calls"]] == ["mcp__qq_mail__send_draft"]


# ---------------------------------------------------------------- E5 选项上限

def test_option_cap_is_ten_not_six() -> None:
    """候选澄清要能列到 10 个：6 的时代第 7 个联系人会被静默吃掉。"""
    assert ask_user_tool.MAX_OPTIONS == 10
    opts = [{"value": f"uid{i}", "label": f"张三({i})"} for i in range(14)]
    out = ask_user_tool._as_options(opts)
    assert len(out) == 10, f"应截到 10，实际 {len(out)}"
    assert out[-1]["value"] == "uid9"


def test_clarification_payload_shape_unchanged() -> None:
    """契约形状不动：前端只认 question + suggested_options。"""
    p = ask_user_tool.build_clarification(
        {"question": "是哪位同事？",
         "options": [{"value": "u1", "label": "张三（研发部/工程师）"},
                     {"value": "u2", "label": "张三（销售部/经理）"}]})
    assert p["question"] == "是哪位同事？"
    assert [o["value"] for o in p["suggested_options"]] == ["u1", "u2"]
    assert p["suggested_options"][0]["label"] == "张三（研发部/工程师）"


# ---------------------------------------------------------------- E6 提示词纪律

def _system_blob() -> str:
    from aios_ai.contracts import RunRequest, UserContext
    from aios_ai.prompt.builder import build_messages

    req = RunRequest(run_id="r_entity", conversation_id=1, text="查我同事考勤", user_token="t",
                     user_context=UserContext(user_id=2, tenant_id=1,
                                              username="zhangsan", roles=["ROLE_USER"]))
    return "\n".join(m.get("content") or "" for m in build_messages(req)
                     if m.get("role") == "system")


def test_prompt_has_entity_clarify_rule(monkeypatch) -> None:
    """HITL 开着才写这条规则（关掉时 ask_user 根本不在工具表里，写了就是骗模型）。"""
    from aios_ai.prompt import builder as prompt_builder

    monkeypatch.setattr(prompt_builder.settings, "agent_hitl", True, raising=False)
    blob = _system_blob()
    assert "模糊的人先澄清" in blob
    assert "searchMode=list" in blob, "不传 list 只回热度前 3，同名同事会被吃掉"
    assert "这一轮只澄清" in blob
    # 四个边界都要写死，否则模型只会「反问一句」而不是枚举候选
    for kw in ("hasMore=true", "不许编人", "降级请用户直接给姓名或工号", "就此终止"):
        assert kw in blob, f"缺边界：{kw}"


def test_prompt_omits_rule_when_hitl_off(monkeypatch) -> None:
    from aios_ai.prompt import builder as prompt_builder

    monkeypatch.setattr(prompt_builder.settings, "agent_hitl", False, raising=False)
    assert "模糊的人先澄清" not in _system_blob()


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))