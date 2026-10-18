"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.runtimes.echo``。"""
from __future__ import annotations

from aios_ai.runtimes.echo import *  # noqa: F401,F403
from aios_ai.runtimes.echo import echo_text, pick_tool, run, summarize  # noqa: F401
