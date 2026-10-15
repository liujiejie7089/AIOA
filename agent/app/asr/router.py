"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.speech.router``。"""
from __future__ import annotations

from aioa_ai.speech.router import *  # noqa: F401,F403
from aioa_ai.speech.router import router, status, transcribe  # noqa: F401
