"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.contracts``。

本模块不再包含实现，仅做再导出；历史 import 路径 ``from app.schemas import RunRequest``
继续可用。新代码请直接 ``from aios_ai.contracts import ...``。
"""
from __future__ import annotations

from aios_ai.contracts import *  # noqa: F401,F403
from aios_ai.contracts import (  # noqa: F401
    AttachmentDoc,
    CompleteRequest,
    CompleteResponse,
    PageContext,
    RunRequest,
    SseEvent,
    SubTaskSpec,
    TaskPlanRequest,
    Usage,
    UserContext,
)
