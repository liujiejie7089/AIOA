"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.intent.router``。"""
from __future__ import annotations

from aioa_ai.intent.router import *  # noqa: F401,F403
from aioa_ai.intent.router import Intent, route  # noqa: F401
