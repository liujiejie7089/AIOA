"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.guard``。"""
from __future__ import annotations

from aioa_ai.guard import *  # noqa: F401,F403
from aioa_ai.guard import ECHO_DELTA_INTERVAL, GuardError, WallClock, check_text_len  # noqa: F401
