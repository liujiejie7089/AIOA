"""兼容入口：历史代码 `from app.model_gateway import gateway` 的挂载点。

真正的实现在包 `__init__.py`（Provider 注册表 + 三级降级解析，
配置来自 agent/.env / 环境变量的 {KEY}_API_KEY / {KEY}_BASE_URL / {KEY}_MODEL）。
本模块仅 re-export 保持旧 import 路径可用；新代码请直接
`from app.model_gateway import resolve`。
"""
from __future__ import annotations

from app.model_gateway import (  # noqa: F401
    GatewayError,
    Provider,
    configured_providers,
    resolve,
)

__all__ = ["Provider", "GatewayError", "resolve", "configured_providers"]
