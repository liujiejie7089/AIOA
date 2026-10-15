"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.events``。"""
from __future__ import annotations

from aioa_ai.events import *  # noqa: F401,F403
from aioa_ai.events import dumps, to_frame  # noqa: F401
