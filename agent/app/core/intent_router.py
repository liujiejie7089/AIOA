"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.intent.router``。"""
from __future__ import annotations

from aios_ai.intent.router import *  # noqa: F401,F403
from aios_ai.intent.router import Intent, route  # noqa: F401
