"""兼容垫片（deprecation shim）：实现已搬迁到 ``aios_ai.prompt.answer``。"""
from __future__ import annotations

from aios_ai.prompt.answer import *  # noqa: F401,F403
from aios_ai.prompt.answer import (  # noqa: F401
    SECTION_KEYS,
    SECTIONS,
    audit,
    audit_hint,
    card,
    rules,
)
