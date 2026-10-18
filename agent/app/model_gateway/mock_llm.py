"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.llm.mock``。"""
from __future__ import annotations

from aios_ai.llm.mock import *  # noqa: F401,F403
from aios_ai.llm.mock import (  # noqa: F401
    MockGeneration,
    sample_temperature_demo,
    summarize_tool_result,
)
from aios_ai.llm.mock import _fuzzy, _seeded_rng, _summarize_sql  # noqa: F401
