"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.config``。

本模块不再包含实现，仅做再导出；历史 import 路径 ``from app.config import settings``
继续可用（``settings`` 与运行中的实现是同一对象）。

新代码请直接 ``from aios_ai.config import settings``。
"""
from __future__ import annotations

from aios_ai.config import Settings, get_settings, settings  # noqa: F401

__all__ = ["Settings", "get_settings", "settings"]
