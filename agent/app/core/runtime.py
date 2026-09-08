"""运行时门面。

对外只暴露 `async def run(req) -> AsyncIterator[SseEvent]`。
M1 委托 echo_runtime；当 model_gateway 解析到的 provider 为真实 LLM（driver=openai_compatible
且已配置 api_key）时，自动切换到 agent_runtime（M2 真实推理）。

事件序列在 echo 与 real 两条路径下完全一致，契约不变。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core import agent_runtime, echo_runtime
from app.model_gateway import gateway
from app.schemas import RunRequest, SseEvent

# 首个事件的 seq（契约要求 seq 从 1 单调递增）
FIRST_SEQ = 1


async def run(req: RunRequest) -> AsyncIterator[SseEvent]:
    """执行一次 agent 运行，返回事件流。"""
    provider = gateway.resolve(req.model_ref)
    if provider.driver == "echo":
        async for event in echo_runtime.run(req, seq_start=FIRST_SEQ):
            yield event
        return
    async for event in agent_runtime.run(req, seq_start=FIRST_SEQ):
        yield event
