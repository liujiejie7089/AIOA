"""StateGraph 装配与编译。

拓扑（与重建前的线性循环一一对应）：
    START → prepare → (fatal ? END : agent)
    agent → (还有工具调用且未达上限 ? tools : finalize)
    tools → agent            # 这是「循环」在图上的表达
    finalize → END

checkpointer：
  - **缺省不挂**（``build()``）——当前功能集里没有「暂停 / 续跑」需求，挂上却不用即属
    「未使用的框架部件」，且会带来两个真实代价：
      a) 状态必须可被 msgpack 序列化（未注册的类实例会直接抛错，曾实测踩到）；
      b) 每个 thread_id 的 checkpoint 常驻内存，长期运行会随 run 数无界增长。
  - 要做 HITL（ask_user 暂停 / resume）时再显式传入持久化实现（PostgresSaver / RedisSaver）：
        build(checkpointer=RedisSaver(...))
    状态已按**可序列化**约束设计（只放 dict/list/原始类型，运行期对象在节点内重建），
    所以届时不需要重构状态或节点，只是把 checkpointer 接上。
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from aios_ai.config import settings
from aios_ai.graph import checkpoint, nodes
from aios_ai.graph.state import RunState


def build(checkpointer=None):
    """装配并编译图。``checkpointer`` 缺省为 None（不挂检查点，见模块 docstring）。"""
    builder = StateGraph(RunState)
    builder.add_node("prepare", nodes.prepare)
    builder.add_node("agent", nodes.agent)
    builder.add_node("tools", nodes.tools)
    builder.add_node("clarify", nodes.clarify)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", nodes.route_after_prepare,
                                  {"end": END, "agent": "agent"})
    builder.add_conditional_edges("agent", nodes.route_after_agent,
                                  {"tools": "tools", "clarify": "clarify", "finalize": "finalize"})
    builder.add_edge("tools", "agent")
    builder.add_conditional_edges("clarify", nodes.route_after_clarify,
                                  {"tools": "tools", "agent": "agent"})
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def graph():
    """进程内单例：编译有开销，复用同一份编译结果。

    HITL 开启（``AIOS_HITL=true``）时挂上 checkpointer（本地=内存 / 生产=Redis，见
    ``checkpoint.py``）—— ``interrupt()`` 必须有它才能暂停与恢复。关闭时为 None，
    与既有实现逐字节一致（零回归）。
    """
    cp = checkpoint.saver() if settings.agent_hitl else None
    return build(checkpointer=cp)


def reset() -> None:
    """清空已编译图缓存。启动时 ``checkpoint.setup()`` 之后调用一次，
    避免「先编译出无 checkpointer 的图、再 setup」这种顺序错误留下陈旧单例。"""
    graph.cache_clear()
