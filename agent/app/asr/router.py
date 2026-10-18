"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.speech.router``。"""
from __future__ import annotations

from aios_ai.speech.router import *  # noqa: F401,F403
from aios_ai.speech.router import router, status, transcribe  # noqa: F401
