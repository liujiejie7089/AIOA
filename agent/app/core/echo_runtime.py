"""M1 回声运行时：把输入文本逐字符回显。

事件序列：
    run.started{run_id,conversation_id}
    → message.delta{text} × N（每帧 1 个字符，间隔 30ms）
    → message.completed{content,citations,tool_calls,usage}
    → run.completed{status:"SUCCEEDED",usage}
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.guards import ECHO_DELTA_INTERVAL, WallClock, check_text_len
from app.schemas import RunRequest, SseEvent


def echo_text(req: RunRequest) -> str:
    """回显文本 = f"[{appCode}/{page}] " + text（context 为空则仅 text）。"""
    ctx = req.context
    if ctx is not None and ctx.appCode and ctx.page:
        return f"[{ctx.appCode}/{ctx.page}] {req.text}"
    return req.text


async def run(req: RunRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """产出回声事件流，seq 从 seq_start 单调递增。"""
    seq = seq_start
    check_text_len(req.text)
    clock = WallClock()

    yield SseEvent(seq=seq, type="run.started", data={"run_id": req.run_id, "conversation_id": req.conversation_id, "model": "echo", "gateway_key": "echo"})
    seq += 1

    content = echo_text(req)
    for ch in content:
        yield SseEvent(seq=seq, type="message.delta", data={"text": ch})
        seq += 1
        await clock.sleep(ECHO_DELTA_INTERVAL)

    usage = {"prompt_tokens": 0, "completion_tokens": len(content)}
    yield SseEvent(
        seq=seq,
        type="message.completed",
        data={"content": content, "citations": [], "tool_calls": [], "usage": usage},
    )
    seq += 1

    yield SseEvent(seq=seq, type="run.completed", data={"status": "SUCCEEDED", "usage": usage})
