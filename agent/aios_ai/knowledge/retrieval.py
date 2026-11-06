"""知识库检索：专家配置参数注入 + 进入工具循环前的预检索。

原寄居在 `app/core/agent_runtime.py`。独立出来的理由：
  - 检索策略（topK / threshold / 模式 / 范围）属于**知识层**，不随编排框架变化；
  - 预检索必须「失败不中断 run」（检索异常只记日志），这条纪律应当收敛在一处、
    而不是散落在运行时循环里。
"""
from __future__ import annotations

import logging
import re

from types import SimpleNamespace

from aios_ai.knowledge.kb import KB_TOOL, _citations_from_tool
from aios_ai.prompt.builder import build_kb_reference_block

logger = logging.getLogger("aios.ai.knowledge")

# 相似度阈值保守默认（docs/60 P0-3a，2026-10-26）：专家未配置 threshold 时，旧实现
# fallback 0.0 ⇒ 向量召回 0 分结果也进参考块，「你好」都能拖出「来源：xxx.docx」。
# 显式配置（含显式 0）永远优先；此值只兜「没配」的空档。注意 threshold 仅作用于
# 向量召回（见 KbController 内部检索语义），关键词/BM25 召回不受它管——那条路靠
# is_chitchat 分流兜底。
DEFAULT_KB_THRESHOLD = 0.5

# 闲聊判定（docs/60 P0-3b）：整句匹配的问候/感谢/告别/应答短句才认，刻意保守——
# 任何带实际内容的消息（哪怕很短，如「报销流程」）都不会命中。
_CHITCHAT_RE = re.compile(
    r"^(?:你?好|您好|hi|hello|嗨|哈喽|hiya|hey|在吗|在么|有人吗"
    r"|谢(?:谢|了|啦)|多谢|感谢|辛苦了|麻烦了"
    r"|再(?:见|会)|拜拜|晚安|早安|早上好|下午好|晚上好"
    r"|好(?:的|滴|呀|嘞|勒)|嗯+|哦+|噢+|ok|okay|收到|明白|了解了?"
    r"|[!！。.，,~～?？\s呀啦哈哟呢了]"
    r")+$",
    re.IGNORECASE,
)

# 查询清洗（2026-11-06，docs/74 根因 5）：原先直接把**整句**当关键词丢给检索，
# 「帮我统计下四川省的省级非遗项目有多少个?」被拆成 19 个 2-gram，其中
# 「帮我/我统/计下/有多/少个」全是噪声，真正有区分度的只有「非遗」——
# 覆盖率被稀释，排序也随之失准。
_ASK_PREFIX = re.compile(
    r"^(?:那么|那个|然后|另外)?"
    # 长词必须排在短词**前面**：Python 的交替是最左优先，`替我` 写在 `替我看看` 之前
    # 会先吃掉短词，把「看看」留在查询里当噪声；`(?:...)+` 只会拿同一批分支反复匹配，
    # 补不回已经被漏掉的更长的词（B4）。同理 `麻烦` 先前置会被 `麻烦你` 顶掉。
    r"(?:请帮我|麻烦你|替我看看|替我瞧瞧|帮我看看|帮我看下|告诉我"
    r"|请|麻烦|帮我|帮忙|给我|替我|我想|我要|我需要|你能|能否|可以"
    r"|看看|瞧瞧|查一下|看一下)+"
)
_ASK_TAIL = re.compile(
    r"(?:一共有|共有|总共有|总共|合计)?"
    r"(?:有多少个|有多少项|有多少条|有多少|多少个|多少项|多少条|多少人|多少"
    r"|是哪些|是什么|有哪些|有什么|怎么样|如何|吗|呢|吧)"
    r"[\s。.!！?？]*$"
)
_QUOTED = re.compile(r"[「『\"“《]([^」』\"”》]{2,30})[」』\"”》]")


def query_variants(question: str | None) -> list[str]:
    """把问句拆成 1~3 条检索变体（原句 + 清洗句 + 引号内的书名/词条）。

    只做**确定性**清洗，不额外调用模型：去掉口语前缀与疑问尾缀，
    让「四川省 省级 非遗 项目 名录」这类核心词不被"帮我/多少个"稀释。
    顺序即优先级；去重后返回，最少一条（原句）。
    """
    if not question:
        return []
    out: list[str] = []
    raw = question.strip()
    if raw:
        out.append(raw)
    cleaned = _ASK_PREFIX.sub("", raw)
    cleaned = _ASK_TAIL.sub("", cleaned)
    cleaned = re.sub(r"[\s，,。.、!！?？~～]+", " ", cleaned).strip()
    if cleaned and cleaned != raw:
        out.append(cleaned)
    for q in _QUOTED.findall(raw):
        q = q.strip()
        if q and q not in out:
            out.append(q)
    # 变体最多 3 条：再多只是重复打同一个库，白白拉长首字延迟
    return out[:3]


def _merge_hits(groups: list[list]) -> list:
    """多路召回合并：按 (docId, chunkIndex) 去重，同片段取最高分，按分数降序。

    为什么要合并而不是取第一路：清洗句召回的是「标题/统计块」这类高区分度片段，
    原句召回的是「正文命中」。两条都要 —— 只留一条会丢另一条的收益。
    """
    best: dict = {}
    order: list = []
    for rows in groups:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = (row.get("id"), row.get("chunkIndex"))
            if key not in best:
                best[key] = row
                order.append(key)
                continue
            prev = best[key]
            try:
                if float(row.get("score") or 0) > float(prev.get("score") or 0):
                    best[key] = row
            except (TypeError, ValueError):
                pass
    merged = [best[k] for k in order]
    merged.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    return merged


def is_chitchat(text: str | None) -> bool:
    """问候/寒暄/感谢/告别类短句：对知识库检索没有价值，调用方应跳过预检索。

    只认**整句**由寒暄词与标点构成的短消息（长度上限 24 字符），长句、含实词的
    短句（如「报销流程」「表格第三行是什么」）一律不命中——宁可漏判（多检索一次，
    无害）也不误判（该检索的不检索）。"""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 24:
        return False
    return bool(_CHITCHAT_RE.match(t))


def inject_search_params(name: str, arguments: dict, top_k: int, threshold: float,
                         mode: str, kb_scope: str) -> dict:
    """检索类工具注入专家配置参数（topK/threshold/mode/kbScope 真实生效）。

    非检索工具原样返回。用 setdefault：模型已显式给了参数就不覆盖。
    """
    if name != KB_TOOL:
        return arguments
    arguments.setdefault("topK", top_k)
    arguments.setdefault("threshold", threshold)
    arguments.setdefault("mode", mode)
    arguments.setdefault("kbScope", kb_scope)
    return arguments


def has_kb_tool(tools: list[dict]) -> bool:
    """候选工具里是否含知识库检索工具（兼容两种 schema 形态）。"""
    return any((t.get("function", {}).get("name") or t.get("name")) == KB_TOOL for t in tools)


def strip_kb_tool(tools: list[dict]) -> list[dict]:
    """剔除知识库检索工具（kb_on=False 时使用：模型即使想检索也无工具可调）。"""
    return [t for t in tools if (t.get("function", {}).get("name") or t.get("name")) != KB_TOOL]


async def pre_retrieve(tool_client, question: str, top_k: int, threshold: float,
                       mode: str, kb_scope: str) -> tuple[str, list[dict]]:
    """进入工具循环前的知识库预检索（多查询变体 + 合并去重）。

    返回 (参考块文本, 引用条目列表)。**任何异常都不上抛**——检索失败只记日志，
    保证 run 能跑完（这是既有产品行为，勿改成抛错）。

    为什么打多路（2026-11-06，docs/74 根因 5）：整句直查时「帮我/多少个」这类词会把
    覆盖率稀释掉，真正有区分度的词（非遗、名录）被淹没。这里用原句 + 清洗句各查一次
    （清洗句只做确定性去前后缀，不额外调模型），按片段去重后合并 —— 原句负责正文命中，
    清洗句负责标题/统计块命中，两条都要。
    """
    variants = query_variants(question) or ([question] if question else [])
    groups: list[list] = []
    for v in variants:
        try:
            args = inject_search_params(KB_TOOL, {"keyword": v},
                                        top_k, threshold, mode, kb_scope)
            outcome = await tool_client.invoke(KB_TOOL, args)
        except Exception as exc:  # 检索失败不冒泡成 error，保证 run 能跑完
            logger.warning("kb pre-retrieval failed (ignored): %s", exc)
            continue
        data = getattr(outcome, "data", None)
        if not getattr(outcome, "ok", False) or not isinstance(data, list) or not data:
            continue
        groups.append(data)
    if not groups:
        logger.info("kb pre-retrieval returned no data")
        return "", []
    merged = _merge_hits(groups)
    if not merged:
        return "", []
    # 上限 = 2×topK（默认 10 条）：多路召回要保留清洗句带回来的高区分度片段，
    # 但也不能让参考块无界膨胀（每条 ≤500 字，10 条约 5KB，已是上限）。
    merged = merged[: max(top_k * 2, top_k)]
    block = build_kb_reference_block(merged)
    logger.info("kb pre-retrieval hit %d rows (variants=%d, merged=%d)",
                sum(len(g) for g in groups), len(groups), len(merged))
    # 引用条目按合并结果给：只按第一路给会漏掉清洗句召回的那几份文档
    return block, _citations_from_tool(KB_TOOL, SimpleNamespace(ok=True, data=merged))
