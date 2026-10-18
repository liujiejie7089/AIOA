"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.events``。"""
from __future__ import annotations

from aios_ai.events import *  # noqa: F401,F403
from aios_ai.events import dumps, to_frame  # noqa: F401
