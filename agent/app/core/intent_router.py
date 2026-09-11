"""本地规则意图识别与工具路由（方案 P4 / D-5）。

不依赖 LLM function-calling：用关键词 + 正则 + 打分识别意图，把用户问句路由到
合适的工具（sql_query / python_script / search_kb_documents / 审批 / 额度），
再抽取槽位。规则可配置、可单测，保证 mock 环境下闭环稳定可复现。

返回 Intent{name, tool, arguments, confidence}，无匹配则 tool=None（走兜底对话）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Intent:
    name: str
    tool: str | None
    arguments: dict = field(default_factory=dict)
    confidence: float = 0.0


# 数据分析意图：问「销量/销售额/营收/排行/TopN/客户/订单/库存/合同/收款」等
_DATA_PATTERNS = [
    (r"(销量|销售额|营收|收入|业绩|成交|下单).{0,6}(多少|排名|排行|top|最高|最低|趋势|占比|统计|汇总|分析)", 0.9),
    (r"(客户|订单|合同|库存|收款|回款).{0,4}(统计|汇总|分析|分布|排行|top|排名|多少|情况)", 0.85),
    (r"(哪个|哪些).{0,6}(客户|产品|品类|区域).{0,4}(最多|最好|最高|靠前|领先)", 0.8),
    (r"(本月|上月|本季度|今年|近三个月|近半年).{0,6}(销售|营收|业绩|订单|回款)", 0.8),
    (r"(环比|同比|增长率|增长幅度|平均值|中位数|合计|总额)", 0.7),
    (r"(库存|缺货|补货|积压).{0,4}(多少|哪些|情况|预警)", 0.7),
]

# 知识库问答意图
_KB_PATTERNS = [
    (r"(知识库|资料|文档|制度|手册|政策|规定|规范|流程|章程).{0,6}(查|找|检索|有没有|是什么|怎么|规定|哪些|有)", 0.85),
    (r"(查|找|搜).{0,4}(资料|文档|制度|政策|手册|制度文档)", 0.8),
    (r"(有哪些|有什么).{0,4}(制度|文档|资料|政策|规定|手册|流程)", 0.8),
]

# 审批意图
_APPROVAL_PATTERNS = [
    (r"(待我审批|待办审批|待审|我的审批|审批进度|审批单)", 0.9),
]

# 额度意图
_QUOTA_PATTERNS = [
    (r"(额度|词元|余额|用量|剩余)", 0.85),
]

# 需要写 Python 计算的意图（复杂计算/多步，规则兜底）
_PY_PATTERNS = [
    (r"(画图|绘图|可视化|图表|趋势图|柱状图)", 0.8),
    (r"(用python|写代码|脚本).{0,4}(计算|处理|分析|统计)", 0.8),
]


def _match_any(text: str, patterns: list[tuple[str, float]]) -> tuple[float, re.Match | None]:
    best = 0.0
    best_m = None
    for pat, w in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m and w > best:
            best = w
            best_m = m
    return best, best_m


def route(text: str, enabled_tools: dict[str, bool] | None = None) -> Intent:
    """识别意图并路由工具。enabled_tools 为专家配置的 tools 开关（None 表示全开）。"""
    enabled = enabled_tools or {}

    def on(name: str) -> bool:
        return enabled.get(name, True)

    # 数据分析（优先，覆盖最广且最有业务价值）
    conf, m = _match_any(text, _DATA_PATTERNS)
    if conf >= 0.7 and m and on("sql_query"):
        return Intent("data_analysis", "sql_query",
                      {"question": text, "sql": None}, conf)

    # 知识库问答
    conf, m = _match_any(text, _KB_PATTERNS)
    if conf >= 0.7 and m and on("search_kb_documents"):
        kw = text.replace(m.group(0), "").strip(" ？?。，,、") or text
        return Intent("kb_qa", "search_kb_documents", {"keyword": kw}, conf)

    # 审批
    conf, m = _match_any(text, _APPROVAL_PATTERNS)
    if conf >= 0.8 and m:
        tool = "list_todo_approvals" if any(k in text for k in ("待我审批", "待办审批", "待审")) else "list_my_approvals"
        if on(tool):
            return Intent("approval", tool, {}, conf)

    # 额度
    conf, m = _match_any(text, _QUOTA_PATTERNS)
    if conf >= 0.8 and m and on("get_my_quota"):
        return Intent("quota", "get_my_quota", {}, conf)

    # Python 计算（最后，兜底复杂任务）
    conf, m = _match_any(text, _PY_PATTERNS)
    if conf >= 0.7 and m and on("python_script"):
        return Intent("python_calc", "python_script", {"code": None, "question": text}, conf)

    return Intent("chat", None, {}, 0.0)
