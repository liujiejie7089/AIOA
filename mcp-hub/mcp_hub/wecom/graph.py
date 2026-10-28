# -*- coding: utf-8 -*-
"""LangGraph 双模式工作流（P0 骨架）。

P0 只做「闸门 → 执行」两跳，但把 P3 需要的地基全部铺好：
- 检查点用 SqliteSaver（与 wecom.db 同库不同表），thread_id = wecom:<tenant>:<user>，
  SSE 断线重连后凭同一 thread_id 即可取回上下文（P3 落地）；
- 执行器注册表（register_executor）让 server.py 注入各工具的真实后端，
  state 本身保持纯 JSON 可序列化，检查点不会因闭包/回调炸掉；
- 失败不静默：闸门拒绝/后端异常都落进 state["error"]，由 server.py 原样转成
  isError 的 CallToolResult（对齐 hub 既有纪律）。

P3 扩展位：多步流程（如「读最近邮件并汇总」= list → read → summarize）在本图上加节点即可。
"""

from __future__ import annotations

import contextvars
import logging
from typing import Awaitable, Callable

import aiosqlite
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from typing_extensions import TypedDict

from . import gate
from . import store

logger = logging.getLogger("mcp_hub.wecom")

Executor = Callable[[dict], Awaitable[dict]]

# 每次工具调用的请求级上下文（identity / connection）。执行器经此取到当前调用方，
# 不进 state（state 要能进检查点，必须可序列化）。
_PAYLOAD: contextvars.ContextVar[dict] = contextvars.ContextVar("wecom_payload", default={})

_EXECUTORS: dict[str, Executor] = {}
_graph = None
_checkpointer: AsyncSqliteSaver | None = None
_conn: "aiosqlite.Connection | None" = None


class ToolExecState(TypedDict, total=False):
    mode: str | None
    tool: str
    arguments: dict
    result: dict | None
    error: str | None
    denied: bool


def register_executor(tool_name: str, fn: Executor) -> None:
    _EXECUTORS[tool_name] = fn


async def _gate_node(state: ToolExecState) -> dict:
    ok, reason = gate.check_tool(state.get("mode"), state.get("tool", ""))
    if not ok:
        return {"denied": True, "error": reason}
    return {"denied": False}


async def _execute_node(state: ToolExecState) -> dict:
    tool = state.get("tool", "")
    executor = _EXECUTORS.get(tool)
    if executor is None:
        return {"error": f"工具 {tool} 尚未注册执行器（内部错误）"}
    try:
        result = await executor(state.get("arguments") or {})
        return {"result": result, "error": None}
    except Exception as e:  # noqa: BLE001 —— 失败不静默：原样带出可读原因
        return {"error": f"{type(e).__name__}: {e}"}


async def _build():
    """编译工作流。检查点与 wecom.db 同库不同表（langgraph 自建 checkpoints/writes），
    thread_id = wecom:<tenant>:<user>，供 P3 SSE 断线重连续上下文。"""
    global _graph, _checkpointer, _conn
    if _graph is not None:
        return _graph
    store.init()
    conn = await aiosqlite.connect(store._db_path())
    _conn = conn
    saver = AsyncSqliteSaver(conn)
    try:
        await saver.setup()
    except Exception:  # noqa: BLE001 —— setup 幂等，失败不阻断启动
        pass
    _checkpointer = saver

    workflow = StateGraph(ToolExecState)
    workflow.add_node("gate", _gate_node)
    workflow.add_node("execute", _execute_node)
    workflow.set_entry_point("gate")
    workflow.add_conditional_edges(
        "gate",
        lambda s: "reject" if s.get("denied") else "run",
        {"reject": END, "run": "execute"},
    )
    workflow.add_edge("execute", END)
    _graph = workflow.compile(checkpointer=saver)
    return _graph


def thread_id_for(tenant_id: str, user_id: str) -> str:
    return f"wecom:{tenant_id}:{user_id}"


async def run_tool(mode: str | None, tool: str, arguments: dict,
                   tenant_id: str, user_id: str, payload: dict | None = None) -> dict:
    """跑一遍工作流；返回 {ok, result|error, denied}。"""
    token = _PAYLOAD.set(payload or {})
    try:
        graph = await _build()
        config = {"configurable": {"thread_id": thread_id_for(tenant_id, user_id)}}
        final = await graph.ainvoke(
            {"mode": mode, "tool": tool, "arguments": arguments, "denied": False},
            config=config,
        )
    finally:
        _PAYLOAD.reset(token)
    if final.get("denied"):
        return {"ok": False, "denied": True, "error": final.get("error") or "模式闸门拒绝"}
    if final.get("error"):
        return {"ok": False, "denied": False, "error": final["error"]}
    return {"ok": True, "result": final.get("result")}


def current_payload() -> dict:
    """执行器取当前请求级上下文（identity / connection）。"""
    return _PAYLOAD.get()


async def shutdown() -> None:
    """关闭 aiosqlite 连接。它的后台线程是非守护的，不关的话 asyncio.run 结束后
    进程不肯退出（哨兵脚本会挂住）。服务常驻无所谓，脚本必须显式调用。"""
    global _conn
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:  # noqa: BLE001
            pass
        _conn = None
