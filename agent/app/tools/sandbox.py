"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.tools.sandbox``。"""
from __future__ import annotations

from aioa_ai.tools.sandbox import *  # noqa: F401,F403
from aioa_ai.tools.sandbox import SandboxResult, run_script  # noqa: F401
