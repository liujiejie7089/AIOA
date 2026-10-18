"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.intent.intake``。"""
from __future__ import annotations

from aios_ai.intent.intake import *  # noqa: F401,F403
from aios_ai.intent.intake import WorkerIntent, classify, detect_action  # noqa: F401
