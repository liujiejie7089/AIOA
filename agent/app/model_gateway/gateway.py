"""兼容垫片（deprecation shim）：``from app.model_gateway import gateway`` 的历史挂载点。

实现已搬迁到 ``aioa_ai.llm`` / ``aioa_ai.llm.gateway``。
"""
from __future__ import annotations

from aioa_ai.llm.gateway import *  # noqa: F401,F403
from aioa_ai.llm.gateway import GatewayError, Provider, configured_providers, resolve  # noqa: F401
