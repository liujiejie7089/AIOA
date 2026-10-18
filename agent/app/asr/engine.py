"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.speech.engine``。"""
from __future__ import annotations

from aios_ai.speech.engine import *  # noqa: F401,F403
from aios_ai.speech.engine import (  # noqa: F401
    AsrBadAudio,
    AsrTooLong,
    AsrUnavailable,
    status,
    transcribe,
    warmup,
)
