"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.prompt.answer``。"""
from __future__ import annotations

from aioa_ai.prompt.answer import *  # noqa: F401,F403
from aioa_ai.prompt.answer import (  # noqa: F401
    SECTION_KEYS,
    SECTIONS,
    audit,
    audit_hint,
    card,
    rules,
)
