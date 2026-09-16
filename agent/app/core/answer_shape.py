"""数字员工回答结构契约（需求项 6「数字员工标准流程」的最后一段）。

职责边界有两种落法，缺一不可：

  1. **事前**：职责限定写进系统提示，让模型不去答边界外的问题
     （见 ``agent_runtime._build_messages`` 的 scope 分支）。
  2. **事后**：回答的**信息结构**必须固定。只写「不要越界」是不够的 ——
     用户真正卡住的场景是「AI 说不行，但没说找谁办、也没说下一步做什么」。

故本模块定义六段式回答结构，并提供两个能力：

  * :func:`rules` —— 生成注入系统提示的结构规则（只影响生成，是软约束）。
  * :func:`audit` —— 对已生成回答做结构自检（是硬判定），返回缺失了哪几段。
    自检结果由调用方决定怎么用（当前是随流下发 SHAPE 事件，前端展示为提示条），
    **不在此处改写模型原文** —— 事后改写真假难辨，也破坏了「回答即原文」的可审计性。

结构六段的来源是需求原文的链路：
前置检查 → 权限申请 → 审批授权 → 创建向导 → 表单配置 → 运行计费审计回收。
对应到一次回答就是：先给结论，再说清当前状态与卡点，然后划边界、给唯一下一步、
给出可转述给管理员的话术，最后说明放行后会自动接上什么。
"""
from __future__ import annotations

import re

# 六段结构：key、中文名、以及「这一段的写作要求」。
SECTIONS: list[tuple[str, str, str]] = [
    ("conclusion", "结论先行",
     "第一句直接给结论：能做 / 不能做 / 需要先补什么。不要用铺垫开头。"),
    ("status", "状态卡",
     "用 2-4 行短句列清当前事实（已具备什么、缺什么、卡在哪一项），每行一个事实，可被逐条核对。"),
    ("boundary", "能力边界",
     "明确说明你这条职责能覆盖到哪、覆盖不到哪；覆盖不到的部分指出应由谁承担。"),
    ("next_step", "唯一下一步",
     "只给一个动作（最多再补一个备选），写清操作路径。多条并列会把选择成本推回用户。"),
    ("admin_script", "管理员话术",
     "若需他人放行，给出一段可直接转述给管理员的话，含具体权限码/资源名与办理路径。"),
    ("after_approval", "通过后续接",
     "说明对方放行后会自动发生什么（谁受理、多长时间、结果推到哪里），让用户知道不用再追问。"),
]

SECTION_KEYS: list[str] = [k for k, _, _ in SECTIONS]

# 自检用的弱标记：命中任一即认为该段存在。
# 刻意保持「弱」——结构自检是为了提示，不是为了扣分，误报比漏报更伤可用性。
_MARKERS: dict[str, list[str]] = {
    "conclusion": [r"^[^。\n]{0,60}[。！\n]", r"结论", r"建议", r"不能", r"可以", r"需要先"],
    "status": [r"当前状态", r"状态：", r"^[-·•\d]", r"已具备", r"缺少", r"卡在"],
    "boundary": [r"职责", r"范围", r"边界", r"只能", r"不负责", r"不处理"],
    "next_step": [r"下一步", r"你(可以|需要|要)", r"请(先|在|点|到)", r"建议你"],
    "admin_script": [r"管理员", r"可转述", r"联系.*(开通|授权)", r"申请"],
    "after_approval": [r"通过后", r"审批通过", r"放行后", r"生效后", r"之后会"],
}


def rules(scope: dict | None = None) -> list[str]:
    """六段式回答结构 → 系统提示行。

    ``scope`` 为空（通用助手、未绑定数字员工）时同样适用 —— 通用办公问答一样存在
    「说了不行却没给出处」的问题，只是第 3 段（能力边界）退化为「说明这条信息我为什么不确定」。
    """
    lines = ["【回答结构 · 必须遵守】下列六段按顺序组织，段名不必写出，但内容必须齐备："]
    lines.extend(f"{i}. {name}：{hint}" for i, (_, name, hint) in enumerate(SECTIONS, start=1))
    lines.append("若某一类信息确实不存在（如无需审批），对应段落用一句「无需 XX」带过，不要整段省略"
                 "—— 省略会让用户无法区分「没有」与「忘了说」。")
    if scope:
        duty = scope.get("duty") or ""
        if duty:
            lines.append(f"第 3 段（能力边界）以本条职责为准：{duty}。")
    return lines


def card(role: str) -> dict:
    """按类型给出确定性的「能力边界卡」。

    与 :func:`rules` 不同，这里**不经模型**：边界文案来自类型元数据的固定定义，
    因此前端可以直接渲染成卡片，不依赖 LLM 是否听话。这也让「边界」在
    「创建前预览」与「会话中提示」两处口径完全一致。

    文案源与 ``worker_intake._ROLES`` 同源（后者是类型元数据的唯一出处），
    这里只负责把它整理成卡片的形状，避免第二份定义。
    """
    from app.core.worker_intake import _ROLES  # 局部导入：避免模块级循环

    key = (role or "").upper()
    if key not in _ROLES:
        # 与 Java 侧 WorkerRole.of 同口径：未知类型一律降级 GENERAL。
        # 只降级文案而不降级 role 字段，会出现「标签写着 X、边界却是通用助手」的自相矛盾。
        key = "GENERAL"
    meta = _ROLES[key]
    return {
        "role": key,
        "roleName": meta["roleName"],
        "boundary": meta["boundary"],
        "nextStep": meta["nextStep"],
        "formFields": list(meta.get("formFields") or []),
        "sections": [{"key": k, "name": n, "hint": h} for k, n, h in SECTIONS],
    }


def audit(answer: str) -> dict:
    """对回答做六段结构自检，返回 ``{ok, missing, sections}``。

    只做**存在性**判断，不判断质量；命中即通过，宁可漏报也不误报。
    """
    text = answer or ""
    sections = {}
    for key in SECTION_KEYS:
        sections[key] = any(re.search(p, text, re.M | re.I) for p in _MARKERS[key])
    missing = [k for k in SECTION_KEYS if not sections[k]]
    return {"ok": not missing, "missing": missing, "sections": sections}


def audit_hint(result: dict) -> str:
    """把自检结果转成一句给用户看的提示（缺失段用中文名回显）。"""
    missing = (result or {}).get("missing") or []
    if not missing:
        return ""
    names = {k: n for k, n, _ in SECTIONS}
    return "本次回答缺少结构段：" + "、".join(names.get(k, k) for k in missing) + \
        "。可直接追问「下一步我该做什么」。"
