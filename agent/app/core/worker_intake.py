"""数字员工「意图识别」—— 把用户的自然语言诉求归类到数字员工类型。

对应需求项 6 的标准流程第一步「意图识别」，以及「按意图自动推荐权限，而非让普通用户选择权限码」。

<div class="boundary">
本模块只做一件事：<b>自然语言 → 数字员工类型</b>。
类型 → 权限码 → 角色集合的映射由 Java 侧（WorkerRole / PermissionCatalog）负责，
因为那是权限治理事实，不是 AI 推断；本模块<b>不复制</b>那份映射，避免两处真相。
</div>

设计取舍：不调用 LLM，用关键词 + 正则 + 打分。
理由与 `intent_router` 一致 —— 规则可配置、可单测、mock 环境下闭环稳定可复现；
「推荐类型」是准入链路的入口，必须确定性可复现，不能因模型抖动而让用户看到不同结论。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 各类型的触发词（命中即加分）与权重。顺序无关，取总分最高者。
_LEAVE_WORDS = [
    (r"请假", 3.0), (r"休假", 3.0), (r"年假", 2.6), (r"调休", 2.6), (r"病假", 2.6),
    (r"事假", 2.6), (r"婚假", 2.4), (r"产假", 2.4), (r"考勤", 1.8), (r"销假", 2.0),
    (r"批假", 2.4), (r"假期", 1.6),
]
_KB_WORDS = [
    (r"知识库", 3.0), (r"制度", 2.4), (r"规章", 2.4), (r"政策", 2.0), (r"手册", 2.0),
    (r"规范", 1.8), (r"资料", 1.6), (r"查资料", 2.6), (r"检索", 2.2), (r"问答", 1.6),
    (r"依据", 1.6), (r"条款", 1.8),
    # 制度/法规类提问同样是「据实作答」的诉求，归知识库问答而非通用闲聊。
    # 必须有足够权重，否则「我要问劳动合同法怎么规定的」会因得分低于阈值被判成 GENERAL。
    (r"怎么规定", 2.4), (r"规定", 2.0), (r"法规", 1.8), (r"法律", 1.8), (r"条例", 1.8),
]
_DOC_WORDS = [
    (r"公文", 3.0), (r"起草", 3.0), (r"通知", 2.4), (r"请示", 2.8), (r"函", 2.2),
    (r"纪要", 2.6), (r"文稿", 2.6), (r"工作报告", 2.6), (r"工作总结", 2.4),
    (r"写一份", 1.8), (r"写个", 1.6), (r"拟稿", 2.6), (r"发文", 2.2),
]

# 组合否定：出现这些词时，「报告/通知」更可能是数据分析产出而非公文
_DATA_HINT = re.compile(r"(销量|销售额|营收|业绩|订单|客户|库存|环比|同比|统计|占比|排行|top\s*\d*)", re.I)

# 类型元数据：中文名、能力边界（不做什么）、建议表单字段、唯一下一步。
_ROLES: dict[str, dict] = {
    "LEAVE_APPROVER": {
        "roleName": "请假审批数字人",
        "boundary": "只受理请假类申请并按其制度送审；不解答与请假无关的业务问题，也不代为审批（终审权在人）。",
        "formFields": ["假种", "起止时间", "请假事由", "证明材料"],
        "nextStep": "补齐「假种 / 起止时间」等信息后提交审批",
    },
    "KB_ASSISTANT": {
        "roleName": "知识库问答数字人",
        "boundary": "只依据企业知识库检索结果作答并标注来源；检索不到时明确说「知识库中没有」，不凭常识编造。",
        "formFields": ["检索范围", "关键词"],
        "nextStep": "在对话中直接提出制度类问题",
    },
    "DOC_DRAFTER": {
        "roleName": "公文起草数字人",
        "boundary": "只起草通知、请示、报告、函等公文并遵循公文格式；不代签、不对外发送、不处理数据统计类需求。",
        "formFields": ["文种", "主题与要点", "字数要求"],
        "nextStep": "确认文种与要点后生成文稿",
    },
    "GENERAL": {
        "roleName": "通用办公助手",
        "boundary": "处理通用办公问答、文案撰写与信息整理；涉及审批权、企业数据或知识库专有内容时，需相应类型数字员工承担。",
        "formFields": [],
        "nextStep": "直接开始对话，或补充职责描述让助手更聚焦",
    },
}


@dataclass
class WorkerIntent:
    """一次意图识别的结果。"""

    role: str
    confidence: float
    matched: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        meta = _ROLES.get(self.role, _ROLES["GENERAL"])
        return {
            "role": self.role,
            "roleName": meta["roleName"],
            "confidence": round(self.confidence, 3),
            "matched": self.matched,
            "boundary": meta["boundary"],
            "formFields": meta["formFields"],
            "nextStep": meta["nextStep"],
            "alternatives": self.alternatives,
        }


def _score(text: str, words: list[tuple[str, float]]) -> tuple[float, list[str]]:
    total = 0.0
    hits: list[str] = []
    for pattern, weight in words:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            total += weight
            hits.append(m.group(0))
    return total, hits


def _confidence(top: float, second: float) -> float:
    """归一化置信度：既看绝对得分，也看与次优的差距（避免「都命中一点」时给出高位结论）。"""
    if top <= 0:
        return 0.0
    base = min(1.0, top / 3.0)
    gap = 0.0 if second <= 0 else min(1.0, (top - second) / max(top, 1e-6))
    return round(min(1.0, 0.45 * base + 0.55 * (0.5 + 0.5 * gap) * base + 0.1), 3)


def classify(text: str) -> dict:
    """把自然语言诉求归类到数字员工类型。

    返回 {@link WorkerIntent.to_dict} 的结构；无任何命中时归为 GENERAL 且 confidence=0。
    """
    raw = (text or "").strip()
    if not raw:
        return WorkerIntent(role="GENERAL", confidence=0.0).to_dict()

    leave, leave_hits = _score(raw, _LEAVE_WORDS)
    kb, kb_hits = _score(raw, _KB_WORDS)
    doc, doc_hits = _score(raw, _DOC_WORDS)

    # 消歧：用户说「写一份销量报告」时，DOC_WORDS 的「报告」会误命中文书类型。
    # 若同时出现明确的数据指标词，则判定为分析类需求（GENERAL），把公文得分压下去。
    if _DATA_HINT.search(raw) and doc > 0:
        doc *= 0.25

    ranked = sorted(
        [("LEAVE_APPROVER", leave, leave_hits),
         ("DOC_DRAFTER", doc, doc_hits),
         ("KB_ASSISTANT", kb, kb_hits)],
        key=lambda item: item[1],
        reverse=True,
    )
    top_role, top_score, top_hits = ranked[0]
    second_score = ranked[1][1]

    # 阈值：得分过低不下结论，避免把随便一句话都推荐成专用类型
    if top_score < 2.0:
        return WorkerIntent(role="GENERAL", confidence=0.0, matched=[]).to_dict()

    alternatives = [
        {"role": role, "roleName": _ROLES[role]["roleName"], "score": round(score, 2)}
        for role, score, _ in ranked if score > 0 and role != top_role
    ]
    return WorkerIntent(
        role=top_role,
        confidence=_confidence(top_score, second_score),
        matched=sorted(set(top_hits)),
        alternatives=alternatives[:2],
    ).to_dict()
