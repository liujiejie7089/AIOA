"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.intent.intake``。"""
from __future__ import annotations

from aioa_ai.intent.intake import *  # noqa: F401,F403
from aioa_ai.intent.intake import WorkerIntent, classify, detect_action  # noqa: F401
