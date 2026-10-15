"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.tools.client``。

本模块不再包含实现，仅做再导出；历史 import 路径
``from app.tools_client import ToolClient`` 继续可用。

**重要**：``ToolClient`` 是同一个类对象（不是副本），所以在任一模块上
``patch.object(ToolClient, "invoke", ...)`` 都会作用于运行中的实现。
"""
from __future__ import annotations

from aioa_ai.tools.client import *  # noqa: F401,F403
from aioa_ai.tools.client import MAX_TOOL_ROUNDS, ToolClient, ToolOutcome  # noqa: F401
