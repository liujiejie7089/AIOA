# -*- coding: utf-8 -*-
"""请假发起：意图闸 / 表单码挑选 / request_form 载荷。

## 为什么要有这一层

请假要 4~5 项信息（假种、起止、事由、处理人）。若交给模型用正文追问，实测会变成
五六轮往返；而让模型自己拼字段卡，实测更糟：字段与 ``form_template`` 漂移
（漏 ``days``/``proof``）、负责人被造成**自由文本框**。

所以这里只做一件事：**挑出后端已定义的那张请假表单的 code**，产出
``request_form{form_code}``；字段由 Java 从 DB 补全，负责人留到提交时由前端选择器问。

## 用例口径

  L1  触发面：请假类词 + 指派语义（含「审批人王启铭」这类直接跟名字的句式）
  L2  表单码只从 Java 下发的 available_forms 里挑，挑不到返回 None（绝不猜）
  L3  request_form 载荷：只有 form_code/reason/prefill，**绝不生成 fields**
  L4  提示块：不列字段、不列候选人、明确「别再追问审批人」
"""
from __future__ import annotations

from aios_ai.intent import leave_apply as la

# ---------------------------------------------------------------- L1 触发面

def test_trigger_with_assign():
    for t in ("帮我请个假，交给张三代批", "我明天调休，让李四处理",
              "年假交给王五审批", "请一天假，指定赵六负责"):
        assert la.needs_leave_form(t), t


def test_trigger_with_name_right_after_role_word():
    """2026-11-06 补：真机里用户更常说「审批人王启铭」「负责人：张大大」。

    旧正则只认「审批人是/选/指」，这类句式全部漏判 ⇒ 落到模型自造卡（负责人变文本框）。
    """
    for t in ("帮我请假，审批人王启铭", "请个事假，负责人：张大大",
              "请假 3 天，审批人=李四", "帮我请个假,处理人 张三"):
        assert la.needs_leave_form(t), t


def test_no_trigger_without_assign():
    """只说「帮我请假」⇒ 走既有表单链路，本闸不介入（零回归）。"""
    for t in ("帮我请假", "我要休年假", "帮我请个假"):
        assert not la.needs_leave_form(t), t


def test_no_trigger_for_question_or_query():
    for t in ("请假流程是什么", "年假有几天", "请假要给谁看", "负责人是谁",
              "我的请假记录查一下", "上个月的请假批了吗"):
        assert not la.needs_leave_form(t), t


def test_no_trigger_for_short_or_empty():
    assert not la.needs_leave_form("")
    assert not la.needs_leave_form(None)
    assert not la.needs_leave_form("假")


# ---------------------------------------------------------------- L2 表单码挑选

FORMS = [
    {"code": "notice_publish", "name": "通知发布", "module_code": "notice", "biz_type": ""},
    {"code": "leave_request", "name": "请假申请", "module_code": "leave", "biz_type": "LEAVE"},
    {"code": "expense_apply", "name": "报销申请", "module_code": "expense", "biz_type": ""},
]


def test_pick_prefers_biz_type_leave():
    assert la.pick_leave_form(FORMS) == "leave_request"


def test_pick_falls_back_to_module_code():
    forms = [{"code": "custom_leave", "module_code": "leave", "biz_type": ""}]
    assert la.pick_leave_form(forms) == "custom_leave"


def test_pick_falls_back_to_code_containing_leave():
    forms = [{"code": "leave_request_v2", "module_code": "", "biz_type": ""}]
    assert la.pick_leave_form(forms) == "leave_request_v2"


def test_pick_returns_none_when_absent():
    """清单里没有请假表单 ⇒ None。**不猜 code**：猜错的表现是「点了提交 404」。"""
    assert la.pick_leave_form(None) is None
    assert la.pick_leave_form([]) is None
    assert la.pick_leave_form([{"code": "notice_publish", "module_code": "notice"}]) is None
    # 脏数据（缺 code）不得被当成命中
    assert la.pick_leave_form([{"module_code": "leave", "biz_type": "LEAVE"}]) is None


# ---------------------------------------------------------------- L3 request_form 载荷

def test_request_shape():
    call = la.build_request(FORMS, "帮我请假，审批人王启铭")
    assert call is not None
    assert call["name"] == "request_form"
    args = call["arguments"]
    assert args["form_code"] == "leave_request"
    assert args["reason"]
    assert isinstance(args["prefill"], dict)
    # ★ 核心约束：绝不生成 fields —— 字段定义在 Java/DB
    assert "fields" not in args
    # 纯 A 段：载荷里不得出现任何字段名/候选人，避免又退回"agent 拼表单"
    assert set(args) == {"form_code", "reason", "prefill"}


def test_request_none_without_form():
    assert la.build_request([], "帮我请假，审批人王启铭") is None
    assert la.build_request(None, "帮我请假，审批人王启铭") is None


def test_prefill_is_empty_on_purpose():
    """刻意不预填：把原话当事由会得到「帮我请个假交给张三代批」这种垃圾值。"""
    call = la.build_request(FORMS, "帮我请个假交给张三代批")
    assert call["arguments"]["prefill"] == {}


# ---------------------------------------------------------------- L4 提示块

def test_block_forbids_asking_assignee_again():
    block = la.build_block(FORMS, "leave_request")
    assert "leave_request" in block
    # 负责人不在表单里：不允许模型再追问审批人
    assert "不要再追问审批人" in block or "不要" in block
    # 不得再引导模型去调 submit_leave_request（提交由表单链路完成）
    assert "submit_leave_request" not in block
    # 不得列出任何 userId 候选（那是旧字段卡的做法）
    assert "userId=" not in block


def test_block_resolves_code_itself():
    block = la.build_block(FORMS)
    assert "leave_request" in block


def test_block_empty_without_form():
    assert la.build_block([]) == ""
    assert la.build_block(None) == ""
