"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.tools.orchestrator``。"""
from __future__ import annotations

from aioa_ai.tools.orchestrator import *  # noqa: F401,F403
from aioa_ai.tools.orchestrator import (  # noqa: F401
    DEFAULT_MAX_CONCURRENCY,
    Event,
    Orchestrator,
    PlanError,
    SubTask,
    TaskResult,
    plan_waves,
    resolve_refs,
    stream_run,
)
