"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.tools.gateway_client``。"""
from __future__ import annotations

from aioa_ai.tools.gateway_client import *  # noqa: F401,F403
from aioa_ai.tools.gateway_client import base_url, invoke_tool  # noqa: F401
