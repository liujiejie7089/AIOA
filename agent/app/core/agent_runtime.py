"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai``。

本模块**不再包含任何实现**，只做再导出，保证历史 import 路径仍可用：

  - 历史代码 ``from app.core import agent_runtime`` / ``agent_runtime.run(...)`` 继续可用；
  - 新代码请直接使用 ``aios_ai.entry`` / ``aios_ai.graph`` / ``aios_ai.prompt.builder``
    等模块（见 ``aios_ai/README.md``）。

保留的若干「非公开名」（``_build_messages`` 等）是为了兼容既有测试与历史调用点；
它们只是 ``aios_ai`` 里同名实现的别名，逻辑只有一份。
"""
from __future__ import annotations

import httpx  # noqa: F401  保留模块属性：历史测试会 patch `agent_runtime.httpx.AsyncClient`

from aios_ai.config import settings  # noqa: F401
from aios_ai.entry import run  # noqa: F401
from aios_ai.knowledge.kb import _citations_from_tool  # noqa: F401
from aios_ai.llm.upstream import (  # noqa: F401
    UpstreamError,
    _post_non_stream,
    _post_stream,
)
from aios_ai.prompt.builder import (  # noqa: F401
    _INJECTION_MASK,
    _neutralize_injection,
    _wrap_field,
    build_messages as _build_messages,
)
from aios_ai.tools.client import (  # noqa: F401
    MAX_TOOL_ROUNDS,
    ToolClient,
    ToolOutcome,
)

__all__ = [
    "run",
    "settings",
    "UpstreamError",
    "ToolClient",
    "ToolOutcome",
    "MAX_TOOL_ROUNDS",
]
