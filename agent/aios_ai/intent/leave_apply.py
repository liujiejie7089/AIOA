"""请假发起：把「帮我请个假，审批人王启铭」变成**一张后端定义的表单 + 一步负责人确认**。

## 为什么不再在 agent 侧合成字段卡（2026-11-06 改）

原先这里拼一张 ``ask_user`` 字段卡（假种 / 起止 / 事由 / handler 五项）。真机截图暴露两个问题：

1. **字段与后端定义漂移**：``form_template`` 里请假是 6 个字段（含 ``days`` 与 ``proof``），
   而卡片自己拼 5 个 —— ``days`` 丢了、``proof`` 没有，用户填完还可能被后端以
   「缺必填」拒一次。
2. **负责人被挤进业务表单**，而且只要本闸没命中（旧正则只认「交给张三代批」，
   不认「审批人王启铭」），模型就会自己临时造卡，把负责人造成**自由文本框** ——
   用户要的是「选人」，不是「敲名字」。

现在的分工（与 ``tools/request_form.py`` 的单一事实源约束一致）：

  - 本模块**只挑表单码**，产出 ``request_form{form_code}``；
  - 字段、必填、选项由 **Java 从 ``form_template.schema_json`` 补全**（不在这里生成 fields）；
  - 负责人留到**提交时**由 H5 的选择器问（``askHandlers``：默认负责人 / 指定负责人），
    与业务字段彻底分开，互不挤占。

## 表单码从哪来

Java 已在 run 请求里下发 ``available_forms: [{code,name,module_code,biz_type}]``
（``RunService`` 从 form_template 查得）。本模块**只挑码、不造码**：优先 ``biz_type=LEAVE``，
其次 ``module_code=leave``，最后 ``code`` 里带 ``leave``。挑不到返回 ``None``
（宁可退回模型，也不猜一个可能不存在的 code —— 猜错的表现是「点了提交 404」）。

## 触发面（仍然收窄）

只认「请假类词 + 指派语义」：

  ✅ 帮我请个假，交给张三代批 / 我明天调休，让李四处理 / 请假，指定王五审批
  ✅ 帮我请假，审批人王启铭 / 请假，负责人：张大大          ← 2026-11-06 补：这类句式原先漏判
  ❌ 帮我请假（没有指派语义 ⇒ 走既有表单链路，行为零变化）
  ❌ 请假流程是什么 / 请假要给谁看（问句，不触发）

## 与既有 `intake.APPLY_LEAVE` 的关系

``intake`` 那套只判「要不要打开请假表单」，服务于**页面形态**的办理入口；
本模块补的是**对话内直接请后端开口表单**。两者互不替代：本模块命中时优先开表单，
未命中时仍由既有链路处理。
"""
from __future__ import annotations

import re
from typing import Any

# 请假类词：与 intake 的 _LEAVE_WORDS 同义但更窄（这里只要"发起"语境的强词）。
# ★ 必须容忍「请个假 / 请一天假」这种**插入量词**的说法：口语里极少有人说「请假」两个字连写。
#   实测「帮我请个假，交给张三代批」在只看 `请假` 时判不出来（漏触发）。
LEAVE_RE = re.compile(
    r"(请假|休假|年假|调休|病假|事假|婚假|产假|丧假|陪产假|带薪假)"
    r"|请\s*(个|一天|两天|三天|半天|几|一)?\s*假"
)

# 指派语义：必须出现「交给谁」的动作词或明确的人名字段，避免把「请假要给谁看」这类误判。
# ★ 2026-11-06 扩充第二条：真机里用户更常说「审批人王启铭」「负责人：张大大」，
#   旧正则只认「审批人是/选/指」，这类**直接跟名字**的句式全部漏判 ⇒ 落到模型自造卡。
ASSIGN_RE = re.compile(
    r"(交给|交由|指派|指定|安排|让|找)\s*[^，。；,;]{0,8}?(审批|批|处理|负责|签|审)"
    r"|(审批人|处理人|负责人)\s*[:：=]?\s*[\u4e00-\u9fa5A-Za-z]"
)

# 这些是「问政策」，不是发起
_QUESTION_RE = re.compile(r"(流程|制度|规定|政策|怎么|如何|几天|多少天|能不能|可以吗|额度|余额|谁|哪)")
# 这些是「查已有单据」，不是发起
_QUERY_RE = re.compile(r"(查一下|查查|看看|我的请假记录|批了吗|到哪了|进度)")

SYNTH_CALL_ID = "call_leave_apply"

# 请假表单的识别顺序（见模块 docstring「表单码从哪来」）
_LEAVE_BIZ_TYPES = ("LEAVE",)
_LEAVE_MODULE = "leave"


def needs_leave_form(text: str | None) -> bool:
    """是否该直接请出「请假表单」（而不是让模型自由发挥）。"""
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if not LEAVE_RE.search(t):
        return False
    if _QUESTION_RE.search(t) or _QUERY_RE.search(t):
        return False
    return bool(ASSIGN_RE.search(t))


def pick_leave_form(available_forms: list[dict] | None) -> str | None:
    """从 Java 下发的表单清单里挑出请假表单码；挑不到返回 None。

    只读不改：清单里的 code 是**唯一可信来源**，本函数绝不拼接或猜测编码。
    """
    forms = [f for f in (available_forms or []) if isinstance(f, dict)]
    if not forms:
        return None

    def _code(f: dict) -> str:
        return str(f.get("code") or "").strip()

    for f in forms:
        if _code(f) and str(f.get("biz_type") or "").strip().upper() in _LEAVE_BIZ_TYPES:
            return _code(f)
    for f in forms:
        if _code(f) and str(f.get("module_code") or "").strip().lower() == _LEAVE_MODULE:
            return _code(f)
    for f in forms:
        if _code(f) and "leave" in _code(f).lower():
            return _code(f)
    return None


def build_request(available_forms: list[dict] | None,
                  text: str | None = None) -> dict[str, Any] | None:
    """合成一次 ``request_form`` 调用（供 graph 的确定性短路直接抛出）。

    返回 ``{"id", "name": "request_form", "arguments": {form_code, reason, prefill}}``；
    挑不到表单码时返回 ``None`` —— **不生成 fields**，字段一律由 Java 从 DB 补全。
    """
    code = pick_leave_form(available_forms)
    if not code:
        return None
    prefill: dict[str, Any] = {}
    # 只做「几乎不会错」的预填：把原话当请假事由会让用户看到一句「帮我请个假交给张三代批」，
    # 比空着更糟 ⇒ 这里刻意留空，交给用户在表单里写。
    return {
        "id": SYNTH_CALL_ID,
        "name": "request_form",
        "arguments": {
            "form_code": code,
            "reason": "请假申请",
            "prefill": prefill,
        },
    }


def build_block(available_forms: list[dict] | None, form_code: str | None = None) -> str:
    """把「这单走哪张表」写进系统提示，供模型在表单回执后继续（不追问、不重复开口）。

    注意：这里**不列字段、不列候选人**。字段是 Java/DB 的事；负责人由 H5 的选择器问。
    """
    code = form_code or pick_leave_form(available_forms)
    if not code:
        return ""
    return (
        "\n\n【请假这单已开表单】（代码已开出，无需你再调 request_form）\n"
        f"- 表单码：{code}（字段与校验由后端定义，你**不要**自己罗列字段或改字段名）\n"
        "- 负责人不在表单里：用户提交时会另行确认「默认负责人 / 指定负责人」，"
        "你**不要**再追问审批人，也不要把审批人写进正文。\n"
        "- 用户提交后你会收到表单回执：据此确认受理结果即可，不要重复提交、不要重新开表。"
    )
