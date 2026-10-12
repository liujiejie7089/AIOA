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


# ------------------------------------------------------------------- 动作意图（与角色正交）

@pytest.mark.parametrize("text,expected_action", [
    ("帮我上传一下这个文件", "UPLOAD_FILE"),
    ("把项目合同传上去", "UPLOAD_FILE"),
    ("我要上报一笔差旅花费", "REPORT_EXPENSE"),
    ("这个月报销 500 元", "REPORT_EXPENSE"),
])
def test_action_intent(text, expected_action):
    out = classify(text)
    assert out["action"] == expected_action
    # actionName 与 action 必须同源（映射恒存在），actionMatched 非空
    assert out["actionName"] == {
        "UPLOAD_FILE": "上传文件", "REPORT_EXPENSE": "上报花费",
    }[expected_action]
    assert out["actionMatched"]


@pytest.mark.parametrize("text", [
    # 公文类诉求不应触发上传/上报动作
    "帮我起草一份通知",
    # 审批类诉求不应触发动作
    "帮我处理员工的请假审批",
    # 制度/问答类诉求：含动作相关词但属提问，绝不能误判成 REPORT_EXPENSE
    "公司费用报销制度是怎么规定的",
    # 知识库检索诉求不应触发动作
    "帮我查一下知识库里的制度文件",
    # 宾语在前的「发送给别人」类诉求，绝不能误判成「上传到项目」
    "帮我生成这个月的销售报表发给客户",
    "把文件发给同事",
    "给客户发一份合同",
    # 上传能力的疑问（限制/大小），属提问而非要上传
    "可以上传多大的文件",
    "上传有大小限制吗",
])
def test_action_intent_not_triggered_for_questions(text):
    out = classify(text)
    assert out["action"] is None, (text, out["action"])
    assert out["actionName"] is None
    assert out["actionMatched"] == []


def test_action_keys_present_on_every_path():
    """action 三键在三条出口（空文本 / 低分 / 正常）都必须存在，schema 恒定。"""
    for text in ("", "随便聊聊", "帮我上传一下合同"):
        out = classify(text)
        for key in ("action", "actionName", "actionMatched"):
            assert key in out, (text, key)


# --------------------------------------------------------------------------- 回答结构

def test_rules_do_not_mandate_sections():
    """2026-10-12 契约变更：六段**不再是每次回答的必给模板**。

    回归背景：旧实现把六段逐条下发、并明令「不要整段省略」，于是用户上传文件问
    「这里面有什么」也会被撑成五段（结论／状态卡／能力边界／唯一下一步／管理员话术），
    其中后三段与提问无关（用户反馈：回答太多，只需要回答用户提问相关的）。
    故这里**反向**断言：提示词不得再逐段下发、不得再出现强制齐备的口径，
    且必须显式要求「只答所问」。
    """
    joined = "\n".join(answer_shape.rules({"duty": "受理请假申请"}))
    assert "必须齐备" not in joined, f"不得再强制逐段齐备：{joined}"
    assert "按顺序组织" not in joined, f"不得再要求按顺序组织六段：{joined}"
    for _, name, _ in answer_shape.SECTIONS:
        assert f"{name}：" not in joined, f"不得再把「{name}」当作必填段落下发：{joined}"
    assert "只回答用户问到的内容" in joined
    assert "最多 3-5 条" in joined


def test_rules_keep_next_step_only_on_permission_questions():
    """原意图里真正有用的部分必须保留，但**只在权限话题**上条件触发。

    口径收窄过两次：最早是「无条件必给」，后改为「用户想做的事做不了才补」，
    用户最终明确要求**只限权限话题** —— 答不了、超出职责、查不到数据都不该出现
    「下一步 / 找谁放行」。故这里把触发条件锁死在「权限」二字上，并反向断言
    「做不了」这类更宽的口径已不在场（否则又会把非权限场景带进来）。
    """
    joined = "\n".join(answer_shape.rules(None))
    assert "涉及权限" in joined, "触发条件必须写明是「涉及权限」，而不是更宽的「做不了」"
    assert "仅当" in joined, "必须是条件句，不能退化成无条件要求"
    assert "除权限问题外" in joined, "必须显式排除非权限场景，否则易被放宽解读"
    assert "做不了" not in joined, "旧的「做不了就补」口径已被收窄，不得残留"
    assert "下一步" in joined and "转述" in joined, "权限场景下该补的两项仍要在场"


def test_rules_scope_adds_only_one_boundary_line():
    """绑定了数字员工时只多一条「越界一句话拒答」，不要求展开——这是本次变更的一部分。"""
    plain = answer_shape.rules(None)
    scoped = answer_shape.rules({"duty": "受理请假申请"})
    assert len(scoped) == len(plain) + 1, (plain, scoped)
    assert "一句话说明" in scoped[-1], scoped[-1]


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
