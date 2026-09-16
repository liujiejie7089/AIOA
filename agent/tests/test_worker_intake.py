"""数字员工准入链路（意图识别 + 回答结构契约）单元测试。

不依赖后端与模型：只验证两个模块的**确定性** —— 分类阈值、边界文案口径、
结构自检的判定边界。这三处一旦漂移，现象分别是「问非所答」「边界前后不一致」
「自检形同虚设」，都属于必须靠单测锁住的行为。
"""
from __future__ import annotations

import pytest

from app.core import answer_shape
from app.core.worker_intake import classify


# --------------------------------------------------------------------------- 意图识别

@pytest.mark.parametrize("text,expected", [
    ("帮我处理员工的请假审批", "LEAVE_APPROVER"),
    ("我要请年假三天", "LEAVE_APPROVER"),
    ("公司考勤制度里请假怎么算", "LEAVE_APPROVER"),
    ("我要问劳动合同法怎么规定的", "KB_ASSISTANT"),
    ("查一下公司的报销制度", "KB_ASSISTANT"),
    ("帮我起草一份通知", "DOC_DRAFTER"),
    ("写个请示给上级单位", "DOC_DRAFTER"),
    ("工作总结怎么拟稿", "DOC_DRAFTER"),
    ("随便聊聊今天天气", "GENERAL"),
    ("帮我整理一下会议要点", "GENERAL"),
    # 组合否定：同为「报告/通知」，带数据线索时应归通用（数据分析产出），而非公文
    ("帮我写一份销售报告", "GENERAL"),
    ("统计本月订单并出一份报告", "GENERAL"),
])
def test_classify_roles(text, expected):
    assert classify(text)["role"] == expected


def test_classify_returns_serialisable_dict():
    """返回必须是可 JSON 序列化的 dict（Java 侧直接 readTree，返回对象会 500）。"""
    out = classify("帮我处理请假审批")
    assert isinstance(out, dict)
    for key in ("role", "roleName", "confidence", "boundary", "formFields", "nextStep"):
        assert key in out, key
    assert 0.0 <= out["confidence"] <= 1.0


def test_classify_empty_text_is_general():
    out = classify("")
    assert out["role"] == "GENERAL"
    assert out["confidence"] == 0.0


# --------------------------------------------------------------------------- 回答结构

def test_rules_cover_six_sections_in_order():
    rules = answer_shape.rules({"duty": "受理请假申请"})
    joined = "\n".join(rules)
    pos = [joined.index(name) for _, name, _ in answer_shape.SECTIONS]
    assert pos == sorted(pos), "六段顺序必须稳定：位置本身就是结构的一部分"
    assert "受理请假申请" in joined, "第 3 段（能力边界）必须绑定本条职责"


def test_rules_apply_without_scope():
    """未绑定数字员工的通用对话同样要受结构约束。"""
    rules = answer_shape.rules(None)
    assert any("唯一下一步" in r for r in rules)


def test_card_is_deterministic_and_matches_role_meta():
    """边界卡不经模型：同样的类型必须给出逐字相同的结果，且与类型元数据同源。"""
    a = answer_shape.card("LEAVE_APPROVER")
    b = answer_shape.card("leave_approver")
    assert a == b, "大小写不应改变结果"
    assert "不代为审批" in a["boundary"]
    assert a["roleName"] == "请假审批数字人"
    assert [s["key"] for s in a["sections"]] == answer_shape.SECTION_KEYS


def test_card_unknown_role_falls_back_to_general():
    assert answer_shape.card("NOT_A_ROLE")["role"] == "GENERAL"
    assert answer_shape.card(None)["role"] == "GENERAL"


def test_audit_flags_missing_sections():
    thin = "不行。"
    r = answer_shape.audit(thin)
    assert r["ok"] is False
    assert "next_step" in r["missing"]
    assert answer_shape.audit_hint(r), "缺失时必须有可展示的提示语"


def test_audit_passes_complete_answer():
    good = (
        "结论：现在不能创建，缺一项权限。\n"
        "当前状态：\n- 权限：缺少 approval:leave\n- 审批人：本部门未设负责人\n"
        "能力边界：本职责只受理请假类申请，不代为审批。\n"
        "下一步：请点「我的 → 权限申请」提交 approval:leave 申请。\n"
        "可转述给管理员：请为本单位成员开通「请假审批」权限。\n"
        "审批通过后会自动发放该权限并即时生效，无需再次提交。"
    )
    r = answer_shape.audit(good)
    assert r["ok"] is True, r
    assert answer_shape.audit_hint(r) == ""


def test_audit_tolerates_empty_answer():
    """空回答不该抛异常（流中断时会走到这里），只如实报缺失。"""
    r = answer_shape.audit("")
    assert r["ok"] is False
    assert len(r["missing"]) == len(answer_shape.SECTION_KEYS)
