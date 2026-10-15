"""对外唯一入口：`run(req)` / `resume(run_id, answer)` → `AsyncIterator[SseEvent]`。

这是整个 aioa_ai 包与「服务接入层」（`app/`）之间的唯一契约点：
  - 入参是 `RunRequest`，出参是 `SseEvent` 流，**与重建前完全一致**；
  - 图内部的实现（LangGraph、节点、状态）对外不可见；
  - `seq` 在这里按事件到达顺序统一编号 —— 事件顺序即图执行顺序，
    因此 `message.delta` 与 `tool.*` 的先后关系与重建前一致（契约要求 seq 从 1 单调递增）。

HITL 澄清（`ask_user`）
----------------------
模型调用内置工具 ``ask_user`` 时，图在 `clarify` 节点 ``interrupt()`` 暂停。本门面在
**流跑完之后**观察图状态：若停在 interrupt，就发一条 ``need_clarification``
（载荷 ``{question, suggested_options}``，见契约第 133 行）并结束本轮 —— 暂停态已由
checkpointer 落盘，等 ``resume(run_id, answer)`` 取回后继续。
（事件在 facade 统一发、而不是在节点里发，是为了避免 ``interrupt`` 恢复重跑节点时重复发事件。）

错误语义（与重建前一致）：
  - `GuardError`：**向上抛**，由 `app/main.py` 的 event_stream 统一转成 error + run.failed；
  - 上游模型非 200：产出 error(MODEL_UPSTREAM_ERROR) + run.failed；
  - 其他异常：产出 error(MODEL_STREAM_ERROR) + run.failed。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command

from aioa_ai.contracts import RunRequest, SseEvent
from aioa_ai.guard import GuardError
from aioa_ai.graph.builder import graph
from aioa_ai.llm.upstream import UpstreamError

logger = logging.getLogger("aioa.ai.graph.facade")

# 首个事件的 seq（契约要求 seq 从 1 单调递增）
FIRST_SEQ = 1


async def run(req: RunRequest, seq_start: int = FIRST_SEQ) -> AsyncIterator[SseEvent]:
    """执行一次 agent 运行，返回事件流（可能在 ask_user 处暂停并发出 need_clarification）。"""
    compiled = graph()
    config = _config(compiled, req.run_id)
    # 状态里存 dict 而非 pydantic 实例（挂 checkpointer 后整份状态要可序列化，见 state.py）
    async for event in _stream(compiled, {"req": req.model_dump()}, config, seq_start, req.run_id):
        yield event


async def resume(run_id: str, answer: Any, seq_start: int = FIRST_SEQ) -> AsyncIterator[SseEvent]:
    """把用户在澄清卡上的选择塞回图里，从断点继续跑。

    暂停态按 ``thread_id=run_id`` 从 checkpointer 取回；**已完成的工具调用不会重跑**
    （状态里已有它们的结果，图从 interrupt 点继续）。
    """
    compiled = graph()
    if not compiled.checkpointer:
        yield SseEvent(seq=seq_start, type="error",
                       data={"code": "NEED_CHECKPOINTER",
                             "message": "HITL 未启用（AIOA_HITL=false）：无挂起态可恢复",
                             "retryable": False})
        yield SseEvent(seq=seq_start + 1, type="run.failed",
                       data={"reason": "no checkpointer", "error_code": "NEED_CHECKPOINTER"})
        return
    config = _config(compiled, run_id)
    async for event in _stream(compiled, Command(resume=answer), config, seq_start, run_id):
        yield event


def _config(compiled, run_id: str) -> dict | None:
    """有 checkpointer 才传 thread_id（= run_id）；没有续跑语义时传了只会误导。"""
    return {"configurable": {"thread_id": run_id}} if compiled.checkpointer else None


async def _stream(compiled, stream_input, config: dict | None, seq_start: int,
                  run_id: str) -> AsyncIterator[SseEvent]:
    """抽干一次图执行的事件，处理错误语义，并在「停在 interrupt」时补发 need_clarification。"""
    seq = seq_start
    try:
        async for chunk in compiled.astream(stream_input, config, stream_mode="custom"):
            if not isinstance(chunk, dict) or "type" not in chunk:
                continue
            yield SseEvent(seq=seq, type=chunk["type"], data=chunk.get("data") or {})
            seq += 1
        # 流正常结束：若图停在 interrupt（等用户输入），补发 need_clarification 后结束本轮
        async for event in _pause_events(compiled, config, seq):
            yield event
            seq = event.seq + 1
    except GuardError:
        raise  # 交由 app/main.py 的 event_stream 统一转成 error + run.failed
    except UpstreamError as exc:  # 上游非 200：可重试的上游错误
        yield SseEvent(seq=seq, type="error",
                       data={"code": "MODEL_UPSTREAM_ERROR", "message": str(exc)[:200],
                             "retryable": True})
        seq += 1
        yield SseEvent(seq=seq, type="run.failed",
                       data={"reason": "upstream error", "error_code": "MODEL_UPSTREAM_ERROR"})
    except Exception as exc:  # 网络/解析等：流内异常按 error + run.failed 上报，不中断服务
        logger.exception("graph run %s failed", run_id)
        yield SseEvent(seq=seq, type="error",
                       data={"code": "MODEL_STREAM_ERROR", "message": str(exc)[:200],
                             "retryable": True})
        seq += 1
        yield SseEvent(seq=seq, type="run.failed",
                       data={"reason": str(exc)[:200], "error_code": "MODEL_STREAM_ERROR"})


async def _pause_events(compiled, config: dict | None, seq: int) -> AsyncIterator[SseEvent]:
    """图停在 interrupt 时产出 need_clarification 事件（每个中断点一条）。"""
    if not config:
        return
    try:
        snapshot = await compiled.aget_state(config)
    except Exception as exc:  # 取状态失败不应把正常结束搞成错误
        logger.warning("get_state failed: %s", exc)
        return
    for task in getattr(snapshot, "tasks", ()) or ():
        for itr in getattr(task, "interrupts", ()) or ():
            payload = getattr(itr, "value", itr)
            data = payload if isinstance(payload, dict) else {"question": str(payload)}
            yield SseEvent(seq=seq, type="need_clarification", data=data)
            seq += 1
