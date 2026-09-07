"""运行时门面。

对外只暴露 `async def run(req) -> AsyncIterator[SseEvent]`。
M1 委托 echo_runtime；M2 换成 langgraph graph 实现时，本接口与事件序列保持不变。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core import echo_runtime
from app.schemas import RunRequest, SseEvent

# 首个事件的 seq（契约要求 seq 从 1 单调递增）
FIRST_SEQ = 1


async def run(req: RunRequest) -> AsyncIterator[SseEvent]:
    """执行一次 agent 运行，返回事件流。"""
    async for event in echo_runtime.run(req, seq_start=FIRST_SEQ):
        yield event
