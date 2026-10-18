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


def test_classify_role_carries_form_code_and_empty_fields():
    """话术与事实同源：_ROLES 只持 form_code，不再写死表单字段。

    - 每个专用类型的 formCode 指向库里真实的表单码；
    - formFields 必须是空数组（字段标签改由 Java 侧按 formCode 从表单库取回），
      证明「字段定义」已不再是 Python 这边的第二份真相。
    """
    cases = {
        "帮我处理请假审批": "leave_request",
        "我要问劳动合同法怎么规定的": "knowledge_upload",
        "帮我起草一份通知": "doc_draft",
    }
    for text, expected_code in cases.items():
        out = classify(text)
        assert out["formCode"] == expected_code, (text, out)
        assert out["formFields"] == [], "formFields 必须为空数组，字段定义只来自库：" + str(out)
    # 通用助手不绑定表单，formCode 为 None
    out = classify("随便聊聊今天天气")
    assert out["formCode"] is None, out
    assert out["formFields"] == []



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


@pytest.mark.parametrize("text", [
    # 正例：必须表达「我要去办」的意愿动词，命中 APPLY_LEAVE
    "我要请假",
    "帮我请个年假",
    "我想休假",
    "帮我申请年假",
    "提交请假",
    "请个假",
])
def test_action_apply_leave_positive(text):
    out = classify(text)
    assert out["action"] == "APPLY_LEAVE", (text, out["action"])
    assert out["actionName"] == "请假", (text, out["actionName"])
    assert out["actionMatched"], (text, out["actionMatched"])


@pytest.mark.parametrize("text", [
    # 反例（必须不命中）：这些是「问政策」，缺「要去办」的意愿动词，应保持 action=null
    "年假有几天",
    "请假流程是什么",
    "考勤制度怎么规定",
    "我想知道年假怎么算",
])
def test_action_apply_leave_negative(text):
    out = classify(text)
    assert out["action"] is None, (text, out["action"])
    assert out["actionName"] is None
    assert out["actionMatched"] == []


@pytest.mark.parametrize("text", [
    # 反例（**必须不命中 APPLY_LEAVE**）：这些是「申请权限」诉求，走 V36「用户通过 AI 提交申请」，
    # 不是「去办请假」。旧口径 `帮我\s*(请|休|申请|提交)` 会把它们吞成请假，后果有二（2026-10-17 实测）：
    #   ① prompt 的 APPLY_LEAVE 分支（「不得调用权限申请类工具」）与全局硬规则
    #      （「用户显式要求提交/申请权限时应照常调用」）**自相矛盾**，V36 能否可用全凭模型仲裁；
    #   ② 同一句还会让 H5 弹出「请假」卡片，与「AI 已提交申请」的事实冲突（违反铁律 1）。
    # 注：「帮我申请年假」这类带**假种**的表达仍应命中（见上面的正例），所以不能一刀切删规则。
    "请直接调用工具帮我提交 approval:leave 权限申请",
    "帮我提交 approval:leave 权限申请",
    "帮我申请一下请假权限",
])
def test_action_apply_leave_not_triggered_for_permission_apply(text):
    out = classify(text)
    assert out["action"] is None, (text, out["action"])
    assert out["actionName"] is None
    assert out["actionMatched"] == []


@pytest.mark.parametrize("text,expected", [
    # 回归：既有动作意图不得被新分支抢走
    ("帮我上传这个文件", "UPLOAD_FILE"),
    ("帮我创建一个数字员工", "CREATE_WORKER"),
    ("我要上报一笔差旅花费", "REPORT_EXPENSE"),
])
def test_action_intent_regression(text, expected):
    out = classify(text)
    assert out["action"] == expected, (text, out["action"])


def test_action_keys_present_on_every_path():
    """action 三键在三条出口（空文本 / 低分 / 正常）都必须存在，schema 恒定。"""
    for text in ("", "随便聊聊", "帮我上传一下合同"):
        out = classify(text)
        for key in ("action", "actionName", "actionMatched"):
            assert key in out, (text, key)


# --------------------------------------------------------------------------- 回答结构

def test_rules_enforce_strict_kb_contract():
    """2026-10-15 契约变更：回答口径改为**严格知识库口径**。

    时间线：2026-10-12 用户两次要求收窄（原话「回答太多，只需要回答用户提问相关的」）；
    2026-10-15 用户给出新口径 —— 严格基于已提供资料、逐维度覆盖不跳项、缺失项标注到具体维度、
    统计/对比类必须用表格、输出前强制自检。故本用例把旧断言（「只回答用户问到的内容」/
    「最多 3-5 条」）替换为新口径关键件。

    ⚠️ 同时**反向**钉住两件不许丢的东西，否则新旧口径都会走偏：
      - 六段不得再被下发为必填模板（丢了就回到 2026-10-12 ① 的冗长）；
      - 必须保留「不得为用户没问到的维度凑段落」的护栏 —— 新口径的「全覆盖」指的是覆盖
        **用户问到的**维度；没有这条护栏，模型会把「全覆盖」执行成「每题都展开」，
        等于把用户之前投诉的那个毛病换个理由请回来。
    """
    joined = "\n".join(answer_shape.rules({"duty": "受理请假申请"}))
    # 新口径关键件
    for must in ("知识库暂未收录", "当前检索未返回相关内容", "不得跳过任何一项",
                 "应答清单", "数据来源", "自检"):
        assert must in joined, f"新口径缺少关键件「{must}」：{joined}"
    # 统计类表格固定三列
    assert "维度层级" in joined and "数量" in joined, \
        f"统计类表格需固定三列（维度层级/数量/数据来源）：{joined}"
    # 不得把「只依据知识库」写成来源白名单（会误伤工具事实 → 「知识库暂未收录」回归）
    assert "工具" in joined and "参考文档" in joined, \
        f"来源白名单必须包含工具返回与对话内参考文档：{joined}"
    # 六段不得再当必填模板
    assert "必须齐备" not in joined, f"不得再强制逐段齐备：{joined}"
    assert "按顺序组织" not in joined, f"不得再要求按顺序组织六段：{joined}"
    for _, name, _ in answer_shape.SECTIONS:
        assert f"{name}：" not in joined, f"不得再把「{name}」当作必填段落下发：{joined}"
    # 护栏：不许为没问到的维度凑段落
    assert "没问到的维度" in joined, \
        f"必须保留「不得为用户没问到的维度凑段落」的护栏：{joined}"


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
