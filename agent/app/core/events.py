"""SSE 事件序列化：SseEvent{seq,type,data} → SSE 帧文本。

帧格式（与契约一致）：
    id: <seq>\\n
    event: <type>\\n
    data: <json>\\n
    \\n
"""
from __future__ import annotations

import json

from app.schemas import SseEvent

def dumps(data: dict) -> str:
    """JSON 序列化：非 ASCII 原样输出，紧凑分隔。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def to_frame(event: SseEvent) -> str:
    """把一个事件渲染成一帧 SSE 文本。"""
    return f"id: {event.seq}\nevent: {event.type}\ndata: {dumps(event.data)}\n\n"
