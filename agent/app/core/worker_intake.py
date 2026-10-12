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

# 「动作意图」：与「角色类型」正交 —— 用户说「上传文件 / 上报花费」时要的是**打开一个操作窗口**，
# 不是换一个数字员工。判定点与角色分类同在 classify() 一处，H5 只消费 action，不另写词表。
_ACTION_RULES = [
    ("UPLOAD_FILE", [
        (r"上传", 3.0),
        (r"(传|交|发)(一?下|个)?(文件|文档|资料|附件|材料|合同|报表|表)", 2.8),
        (r"附件", 1.8),
        (r"导入.{0,4}(文件|文档|资料|表|数据)", 2.4),
        # 兼容「把项目合同传上去」这类「宾语在前、动词在后」的语序；
        # 只允许上传语义的补语（传上去/传上/传一下/交上去/上传），不要裸「发」，
        # 否则「把文件发给同事」「报表发给客户」会被误判成上传。
        (r"(文件|文档|资料|附件|材料|合同|报表).{0,4}(传上去|传上|传一下|交上去|上传)", 2.8),
        # 任务书 §4 上传触发词：覆盖「加个文件 / 添加一份资料」这类口语化表达
        # （原词表只认「上传/传/交/发 + 宾语」，漏掉了「加/添加/新增 + 宾语」）。
        (r"(加|添加|新增)(一?个|个)?(文件|文档|资料|附件)", 2.8),
    ]),
    ("REPORT_EXPENSE", [
        (r"(上报|报|记|录入|登记|补录|添加).{0,6}(花费|费用|支出|开销|成本|报销)", 3.0),
        (r"(花费|费用|支出|开销|成本).{0,6}(上报|报一笔|记一笔|录入|登记)", 3.0),
        (r"报销(单|一下|一笔|申请|\s*\d)", 2.8),
        (r"报账", 2.8),
        (r"记一笔", 2.4),
    ]),
    # 创建数字员工：界面能力（用户端「专家与员工」页「＋ 创建数字员工」入口；管理端亦可），
    # 所需权限 worker:create 对全体登录用户默认开放——**不是** worker:manage（那是「管理」且不可申请）。
    # 与动作意图正交：用户说「建个数字人」要的是打开创建界面，不是换角色类型。
    ("CREATE_WORKER", [
        (r"(新建|创建|建一个|建个|生成|添加)(一?个|个)?(数字人|数字员工|数字机器人)", 3.0),
        (r"(数字人|数字员工|数字机器人).{0,4}(新建|创建|建一个)", 2.8),
    ]),
]

_ACTION_META = {"UPLOAD_FILE": "上传文件", "REPORT_EXPENSE": "上报花费", "CREATE_WORKER": "创建数字员工"}
# 疑问 / 制度类语句优先按「问答」处理：命中这些词且动作得分不强时，不判为动作意图，
# 否则「公司费用报销制度是怎么规定的」会被误判成「要上报花费」。
_ACTION_QUESTION = re.compile(r"(制度|规定|政策|流程|办法|标准|指南|手册|怎么|如何|为什么|是什么|哪些|可以吗|能不能|多大|上限|限制|大小|最大)")

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


def detect_action(text: str) -> str | None:
    """公开接口：返回与角色正交的「动作意图」码（UPLOAD_FILE / REPORT_EXPENSE / CREATE_WORKER），
    无动作返回 None。供 H5 / agent_runtime 直接用 action 码决定「开哪个窗口 / 给哪句提示」，
    无需命中词。内部委托 ``_detect_action``（返回 (action, hits) 元组，仅供 classify 拼装出口字典）。
    """
    action, _ = _detect_action(text)
    return action


def _detect_action(text: str) -> tuple[str | None, list[str]]:
    """检测与角色正交的「动作意图」（上传文件 / 上报花费 / 创建数字员工）。

    返回 (动作码, 命中词列表)；无动作时返回 (None, [])。
    """
    best, best_score, best_hits = None, 0.0, []
    for code, words in _ACTION_RULES:
        s, hits = _score(text, words)
        if s > best_score:
            best, best_score, best_hits = code, s, hits
    if best is None:
        return None, []
    # 疑问/制度类语境需要更强的证据：光有裸动词「上传/上报」(单条 3.0) 不够，
    # 必须带宾语的组合命中（如「上传文件」=5.8）才判动作意图；否则「可以上传多大的文件」
    # 会因裸「上传」(3.0) 被误判成要上传。普通语境阈值仍为 2.0。
    if _ACTION_QUESTION.search(text):
        if best_score <= 3.0:
            return None, []
    elif best_score < 2.0:
        return None, []
    return best, sorted(set(best_hits))


def _with_action(d: dict, action: str | None, hits: list[str]) -> dict:
    """在返回的 dict 上补 action 三键，保证三条出口 schema 恒定。

    action 为 None 时三个键照样存在（H5 据此区分「要开窗口」还是「正常对话」）。
    """
    d["action"] = action
    d["actionName"] = _ACTION_META.get(action)
    d["actionMatched"] = hits
    return d


def classify(text: str) -> dict:
    """把自然语言诉求归类到数字员工类型。

    返回 {@link WorkerIntent.to_dict} 的结构，并附带与角色正交的 action 维度；
    无任何命中时归为 GENERAL 且 confidence=0。
    """
    raw = (text or "").strip()
    action, action_hits = _detect_action(raw)
    if not raw:
        return _with_action(
            WorkerIntent(role="GENERAL", confidence=0.0).to_dict(),
            action, action_hits)

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
        return _with_action(
            WorkerIntent(role="GENERAL", confidence=0.0, matched=[]).to_dict(),
            action, action_hits)

    alternatives = [
        {"role": role, "roleName": _ROLES[role]["roleName"], "score": round(score, 2)}
        for role, score, _ in ranked if score > 0 and role != top_role
    ]
    return _with_action(
        WorkerIntent(
            role=top_role,
            confidence=_confidence(top_score, second_score),
            matched=sorted(set(top_hits)),
            alternatives=alternatives[:2],
        ).to_dict(),
        action, action_hits)
