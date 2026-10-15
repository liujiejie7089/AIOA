"""知识库检索：专家配置参数注入 + 进入工具循环前的预检索。

原寄居在 `app/core/agent_runtime.py`。独立出来的理由：
  - 检索策略（topK / threshold / 模式 / 范围）属于**知识层**，不随编排框架变化；
  - 预检索必须「失败不中断 run」（检索异常只记日志），这条纪律应当收敛在一处、
    而不是散落在运行时循环里。
"""
from __future__ import annotations

import logging

from aioa_ai.knowledge.kb import KB_TOOL, _citations_from_tool
from aioa_ai.prompt.builder import build_kb_reference_block

logger = logging.getLogger("aioa.ai.knowledge")


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
