"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.llm``。

``resolve`` / ``Provider`` 等与运行中的实现是同一对象。
"""
from __future__ import annotations

from aios_ai.llm import *  # noqa: F401,F403
from aios_ai.llm import (  # noqa: F401
    GatewayError,
    Provider,
    apply_overrides,
    configured_providers,
    current_default_key,
    get_provider,
    resolve,
)
