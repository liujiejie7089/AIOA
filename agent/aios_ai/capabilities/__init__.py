"""能力层（capabilities）：工具 / 技能的统一注册、加载与生命周期管理。

对外只需记住三件事：

    from aios_ai.capabilities import get_registry
    reg = get_registry()                       # ① 取进程级注册表
    tools, states = await reg.load(ctx)        # ② 加载 => 模型工具表 + 各能力状态
    reg.health()                               # ③ 观测：谁 READY / 谁 ERROR / 谁被停用
"""
from __future__ import annotations

from aios_ai.capabilities.models import (
    CapabilityKind,
    CapabilitySpec,
    CapabilityState,
    IllegalTransition,
    LifecycleState,
    can_transit,
)
from aios_ai.capabilities.providers import (
    HitlProvider,
    McpProvider,
    SkillProvider,
    WebProvider,
    build_default_registry,
    get_registry,
    reset_registry,
)
from aios_ai.capabilities.registry import CapabilityProvider, CapabilityRegistry, StaticProvider

__all__ = [
    "CapabilityKind", "CapabilitySpec", "CapabilityState", "LifecycleState",
    "IllegalTransition", "can_transit",
    "CapabilityRegistry", "CapabilityProvider", "StaticProvider",
    "HitlProvider", "McpProvider", "WebProvider", "SkillProvider",
    "build_default_registry", "get_registry", "reset_registry",
]
