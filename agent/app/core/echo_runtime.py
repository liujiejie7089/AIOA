"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.runtimes.echo``。"""
from __future__ import annotations

from aioa_ai.runtimes.echo import *  # noqa: F401,F403
from aioa_ai.runtimes.echo import echo_text, pick_tool, run, summarize  # noqa: F401
