"""兼容垫片（deprecation shim）：``from app.model_gateway import gateway`` 的历史挂载点。

实现已搬迁到 ``aios_ai.llm`` / ``aios_ai.llm.gateway``。
"""
from __future__ import annotations

from aios_ai.llm.gateway import *  # noqa: F401,F403
from aios_ai.llm.gateway import GatewayError, Provider, configured_providers, resolve  # noqa: F401
