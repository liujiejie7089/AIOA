"""知识库检索：专家配置参数注入 + 进入工具循环前的预检索。

原寄居在 `app/core/agent_runtime.py`。独立出来的理由：
  - 检索策略（topK / threshold / 模式 / 范围）属于**知识层**，不随编排框架变化；
  - 预检索必须「失败不中断 run」（检索异常只记日志），这条纪律应当收敛在一处、
    而不是散落在运行时循环里。
"""
from __future__ import annotations

import logging
import re

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
    """进入工具循环前的知识库预检索。

    返回 (参考块文本, 引用条目列表)。**任何异常都不上抛**——检索失败只记日志，
    保证 run 能跑完（这是既有产品行为，勿改成抛错）。
    """
    try:
        args = inject_search_params(KB_TOOL, {"keyword": question},
                                    top_k, threshold, mode, kb_scope)
        outcome = await tool_client.invoke(KB_TOOL, args)
    except Exception as exc:  # 检索失败不冒泡成 error，保证 run 能跑完
        logger.warning("kb pre-retrieval failed (ignored): %s", exc)
        return "", []
    if not (outcome.ok and isinstance(outcome.data, list) and outcome.data):
        logger.info("kb pre-retrieval returned no data")
        return "", []
    block = build_kb_reference_block(outcome.data)
    logger.info("kb pre-retrieval hit %d docs", len(outcome.data))
    return block, _citations_from_tool(KB_TOOL, outcome)
