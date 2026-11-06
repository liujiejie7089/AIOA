"""请假发起：把「帮我请个假，交给张三代批」变成一张**一次填完**的字段卡。

## 为什么需要确定性闸

已实测两次同类失败（模糊实体 / 企微写操作）：工具与提示都齐备，模型仍然不调工具，
而是用正文反问「请提供假种、起止日期、审批人」。请假尤其吃亏 —— 它要**四到五项**信息，
靠多轮往返问完，用户点了五六次才提交得上去。

因此这里在 `prepare` 阶段就把候选查好（假种目录 + 可审批人），
再合成一张字段卡：所有缺项一次问全，选项来自真实库表，不是模型编的。

## 触发面（刻意收窄）

只认「请假类词 + 指派语义」：
  ✅ 帮我请个假，交给张三代批 / 我明天调休，让李四处理 / 请假，指定王五审批
  ❌ 帮我请假（没有指派语义 ⇒ 走既有表单链路，行为零变化）
  ❌ 请假流程是什么（问政策，不触发）

## 与既有 `intake.APPLY_LEAVE` 的关系

`intake` 那套只判「要不要打开请假表单」，服务于**页面形态**的办理入口；
本模块补的是**对话内一次填完 + 指定处理人**，两者互不替代：
本模块命中时优先出字段卡（信息更全），未命中时仍由既有链路处理。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("aios.ai.intent.leave_apply")

# 请假类词：与 intake 的 _LEAVE_WORDS 同义但更窄（这里只要"发起"语境的强词）。
# ★ 必须容忍「请个假 / 请一天假」这种**插入量词**的说法：口语里极少有人说「请假」两个字连写。
#   实测「帮我请个假，交给张三代批」在只看 `请假` 时判不出来（漏触发）。
LEAVE_RE = re.compile(
    r"(请假|休假|年假|调休|病假|事假|婚假|产假|丧假|陪产假|带薪假)"
    r"|请\s*(个|一天|两天|三天|半天|几|一)?\s*假"
)

# 指派语义：必须出现「交给谁」的动作词，避免把「请假要给谁看」这类误判。
ASSIGN_RE = re.compile(
    r"(交给|交由|指派|指定|安排|让|找)\s*[^，。；,;]{0,8}?(审批|批|处理|负责|签|审)"
    r"|(审批人|处理人)\s*[是选指]"
)

# 这些是「问政策」，不是发起
_QUESTION_RE = re.compile(r"(流程|制度|规定|政策|怎么|如何|几天|多少天|能不能|可以吗|额度|余额)")
# 这些是「查已有单据」，不是发起
_QUERY_RE = re.compile(r"(查一下|查查|看看|我的请假记录|批了吗|到哪了|进度)")

SYNTH_CALL_ID = "call_leave_apply"

# 假种候选上限（字段卡是选择器，不是目录浏览）
MAX_LEAVE_TYPES = 12
# 处理人候选上限（同上；超过就让用户用搜索框筛）
MAX_HANDLERS = 40


def needs_handler_pick(text: str | None) -> bool:
    """是否该弹「请假 + 选处理人」字段卡。"""
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if not LEAVE_RE.search(t):
        return False
    if _QUESTION_RE.search(t) or _QUERY_RE.search(t):
        return False
    return bool(ASSIGN_RE.search(t))


async def prefetch(tool_client) -> tuple[list[dict], list[dict]]:
    """并行拉「假种」与「可审批人」。任一侧失败都吞掉（返回空），不能因为查候选打挂 run。"""
    async def _safe(name: str) -> list[dict]:
        try:
            outcome = await asyncio.wait_for(tool_client.invoke(name, {}), timeout=10.0)
        except Exception as exc:                      # noqa: BLE001
            logger.info("leave prefetch %s failed: %s", name, exc)
            return []
        if not getattr(outcome, "ok", False):
            logger.info("leave prefetch %s not ok: %s", name,
                        getattr(outcome, "error", "")[:120])
            return []
        data = getattr(outcome, "data", None)
        return data if isinstance(data, list) else []

    types, handlers = await asyncio.gather(
        _safe("list_leave_types"), _safe("list_approval_handlers"))
    logger.info("leave prefetch: %d 个假种、%d 个可审批人", len(types), len(handlers))
    return types, handlers


def _opt(value, label) -> dict:
    return {"value": value, "label": label}


def build_card(types: list[dict] | None, handlers: list[dict] | None,
               text: str | None = None) -> dict[str, Any] | None:
    """合成字段卡。缺关键候选（假种或可审批人）时返回 None —— 宁可退回模型问答，
    也不弹一张「选项为空」的死控件。"""
    if not handlers:
        return None
    handler_opts = []
    for h in (handlers or [])[:MAX_HANDLERS]:
        uid = h.get("userId")
        if uid is None:
            continue
        name = h.get("name") or f"用户#{uid}"
        title = (h.get("jobTitle") or h.get("dutyCode") or "").strip()
        handler_opts.append(_opt(uid, f"{name}（{title}）" if title else name))
    if not handler_opts:
        return None

    fields: list[dict] = []
    type_opts = []
    for t in (types or [])[:MAX_LEAVE_TYPES]:
        code = t.get("code")
        if not code:
            continue
        label = t.get("name") or code
        if t.get("needProof"):
            label += "（需证明）"
        type_opts.append(_opt(code, label))
    if type_opts:
        fields.append({"id": "leave_type", "label": "假种", "type": "select",
                       "required": True, "options": type_opts})
    else:
        # 查不到假种目录时退化为文本输入：用户可能自己知道编码（如 annual）
        fields.append({"id": "leave_type", "label": "假种", "type": "text",
                       "required": True, "placeholder": "如：年假 / 调休 / 事假"})

    fields += [
        {"id": "start", "label": "开始日期", "type": "date", "required": True},
        {"id": "end", "label": "结束日期", "type": "date", "required": True},
        {"id": "reason", "label": "请假事由", "type": "textarea", "required": True,
         "placeholder": "会展示给审批人，例如：家中有事需回老家处理"},
        {"id": "handler", "label": "交给谁处理", "type": "select", "searchable": True,
         "required": True, "placeholder": "输入姓名筛选…", "options": handler_opts,
         "hint": "他批完后，若后台配置了审批流会继续自动流转"},
    ]
    return {"id": SYNTH_CALL_ID, "name": "ask_user",
            "arguments": {"question": "请假的几项信息，填完一次提交：", "fields": fields}}


def build_block(types: list[dict] | None, handlers: list[dict] | None) -> str:
    """把候选写进系统提示：模型拿到回填值后要能直接调 submit_leave_request。"""
    if not handlers:
        return ""
    lines = ["\n\n【请假候选已查好】（代码已预取，可直接使用）"]
    if types:
        brief = "、".join(f"{t.get('code')}={t.get('name')}" for t in types[:MAX_LEAVE_TYPES])
        lines.append(f"- 假种码：{brief}")
    lines.append("- 可指定处理人（**必须用 userId**，不要编）：")
    for h in handlers[:10]:
        title = h.get("jobTitle") or h.get("dutyCode") or ""
        lines.append(f"  · userId={h.get('userId')} {h.get('name')}"
                     + (f"（{title}）" if title else ""))
    lines.append(
        "提交用工具 submit_leave_request，参数：leaveTypeCode / startDate(YYYY-MM-DD) / "
        "endDate(YYYY-MM-DD) / reason / assigneeUserId（单个）或 assigneeUserIds（多个，数组顺序即审批顺序）。"
        "**不要**再用正文追问这些值 —— 用户已在卡片里选过。")
    return "\n".join(lines)
