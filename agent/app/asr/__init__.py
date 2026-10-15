"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.speech``。

对外只有两个函数：``status()`` 与 ``transcribe()``。
"""
from __future__ import annotations

from aioa_ai.speech.engine import (  # noqa: F401
    AsrBadAudio,
    AsrTooLong,
    AsrUnavailable,
    status,
    transcribe,
    warmup,
)

__all__ = ["AsrBadAudio", "AsrTooLong", "AsrUnavailable", "status", "transcribe", "warmup"]
