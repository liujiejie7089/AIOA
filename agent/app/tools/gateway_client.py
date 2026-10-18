"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.tools.gateway_client``。"""
from __future__ import annotations

from aios_ai.tools.gateway_client import *  # noqa: F401,F403
from aios_ai.tools.gateway_client import base_url, invoke_tool  # noqa: F401
