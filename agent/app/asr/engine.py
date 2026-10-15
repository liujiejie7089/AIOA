"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.speech.engine``。"""
from __future__ import annotations

from aioa_ai.speech.engine import *  # noqa: F401,F403
from aioa_ai.speech.engine import (  # noqa: F401
    AsrBadAudio,
    AsrTooLong,
    AsrUnavailable,
    status,
    transcribe,
    warmup,
)
