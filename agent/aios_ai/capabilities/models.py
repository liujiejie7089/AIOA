"""能力层统一模型（capabilities）。

为什么要有这一层
================
接入一个「能力」在改造前是**四条互不相识的路径**：

  1. 内置工具（``web_search`` / ``ask_user`` / ``request_form`` / ``request_confirm``）
     —— 在 ``graph/nodes.py#prepare`` 里用模块级常量**手工往列表头拼**；
  2. MCP 工具 —— ``ToolClient.list_mcp_tools()`` 运行时从 Java manifest 拉取并改名；
  3. 插件 / Bridge 工具 —— 走另一份 manifest；
  4. 「技能」—— ``ai_skill`` 表只做**会话模板**，与上面三条零关联，没有注册也没有生命周期。

每加一类能力就要在 prepare 里再加一段拼接、再自己处理开关/失败降级，四个地方各自演化，
且没有任何一处能回答「现在到底注册了哪些能力、各自处于什么状态、上次探测是否健康」。
本模块把这些收敛成**一处注册 + 一处加载 + 一套生命周期**，后续大量接入 skills /
connectors 只需要实现一个 :class:`CapabilityProvider` 并注册进来，不动图、不动工具网关。

设计取舍（不要回退）
====================
* **纯数据 + 纯函数为主**：Provider 只做「列出我能提供什么」，网络 IO 由调用方注入
  （见 :meth:`CapabilityProvider.list_specs` 允许 async，但 Registry 不替它做任何重试）。
  这样单测不需要起服务。
* **失败隔离在「能力」粒度**：单个 provider 抛异常只让它自己进 ERROR，其余能力照常注入，
  整轮的可用性由 :meth:`CapabilityRegistry.load` 的 results 决定，绝不因为一门没接好的
  MCP 就把整问答死。
* **零回归是硬约束**：注册表产出的工具清单必须与手写拼接**逐项同序**（详见
  :func:`aios_ai.capabilities.providers.builtin_specs` 的顺序注释），现有 200+ 条
  单测与流水哨兵会盯着这点。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapabilityKind(str, Enum):
    """能力来源分类。用 ``str`` 混入以便直接进 JSON / 日志。"""

    BUILTIN = "builtin"      # 进程内实现，无需外部依赖（如联网检索、HITL 控制链）
    MCP = "mcp"              # MCP 连接器工具（经 mcp-hub）
    PLUGIN = "plugin"        # Bridge 插件工具
    SKILL = "skill"          # 技能（本次为后续接入预留的扩展位）


class LifecycleState(str, Enum):
    """生命周期状态机。

    ``REGISTERED → RESOLVED → READY`` 是主链；``READY`` 之外还有三个终态/旁支：

      * ``DISABLED``：被开关或运维显式关掉（不是故障，恢复后回 READY）；
      * ``UNRESOLVED``：依赖没到位（例如 MCP hub 没配地址）⇒ 本轮不注入，**不算失败**；
      * ``ERROR``：加载真的抛了异常 ⇒ 本轮不注入且要在 health 里暴露原因。

    为什么不直接沿用 Kubernetes 式 READY/RUNNING/RUNNING_UNHEALTHY：这里的能力大多是
    **无状态、按 run 组装**的（每次 run 现拉工具表），没有常驻进程要 RUNNING；真正的
    长生命周期进程（mcp-hub、connector daemon）由它们各自的宿主负责，这里只维护
    「注册表视角的健康度」，不假装能替它们管进程。
    """

    REGISTERED = "REGISTERED"    # 刚注册，还没解析依赖
    RESOLVED = "RESOLVED"        # 依赖已确认存在，还没加载清单
    READY = "READY"              # 清单已加载，可以注入给模型
    DISABLED = "DISABLED"        # 显式停用
    UNRESOLVED = "UNRESOLVED"    # 依赖缺失，注入不了
    ERROR = "ERROR"              # 加载失败


# 允许从一个状态迁移到哪些状态（唯一的合法性裁决点，避免各 provider 自己改给自己放水）
_ALLOWED_TRANSITIONS: dict[LifecycleState, tuple[LifecycleState, ...]] = {
    LifecycleState.REGISTERED: (LifecycleState.RESOLVED, LifecycleState.DISABLED,
                                LifecycleState.UNRESOLVED),
    LifecycleState.RESOLVED: (LifecycleState.READY, LifecycleState.ERROR,
                              LifecycleState.DISABLED, LifecycleState.UNRESOLVED),
    LifecycleState.READY: (LifecycleState.RESOLVED, LifecycleState.ERROR,
                           LifecycleState.DISABLED, LifecycleState.UNRESOLVED),
    LifecycleState.ERROR: (LifecycleState.RESOLVED, LifecycleState.READY,
                           LifecycleState.DISABLED, LifecycleState.UNRESOLVED),
    LifecycleState.DISABLED: (LifecycleState.RESOLVED, LifecycleState.REGISTERED),
    LifecycleState.UNRESOLVED: (LifecycleState.RESOLVED, LifecycleState.READY,
                                LifecycleState.DISABLED, LifecycleState.ERROR),
}


class IllegalTransition(RuntimeError):
    """非法状态迁移。刻意做成异常而不是静默忽略：状态机一旦能静默跳转，就没人再信它。"""


def can_transit(src: LifecycleState, dst: LifecycleState) -> bool:
    """src → dst 是否合法（**纯函数**，便于单测直接用）。"""
    if src is dst:
        return True
    return dst in _ALLOWED_TRANSITIONS.get(src, ())


@dataclass
class CapabilitySpec:
    """一个能力的最小登记信息（Provider 的产物，Registry 的输入）。

    ``code`` 全局唯一（跨 kind 也唯一），用于 disable/enable/health 定位；
    ``tools`` 是 OpenAI function-calling schema 列表；``version`` 留给用户可读的
    来源版本刻印（例如 mcp server 的 tool 目录版本），暂不参与注入决策。
    """

    code: str
    kind: CapabilityKind
    tools: list[dict[str, Any]] = field(default_factory=list)
    version: str = ""
    description: str = ""
    source: str = ""                      # 来源标识（如 mcp server code / 内置模块名）
    enabled: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_names(self) -> list[str]:
        """本能力包含的工具名（兼容 ``{function:{name}}`` 与 ``{name}`` 两种 schema 形态）。"""
        out: list[str] = []
        for t in self.tools:
            n = (t.get("function") or {}).get("name") if isinstance(t, dict) else None
            n = n or (t.get("name") if isinstance(t, dict) else None)
            if n:
                out.append(n)
        return out


@dataclass
class CapabilityState:
    """某个能力的运行时状态快照（Registry 的产物，供 health / 观测使用）。"""

    spec: CapabilitySpec
    state: LifecycleState = LifecycleState.REGISTERED
    error: str | None = None
    last_error_at: str | None = None      # ISO 串；不引入时间依赖，由调用方填
    load_count: int = 0
    error_count: int = 0

    @property
    def healthy(self) -> bool:
        return self.state is LifecycleState.READY

    def as_dict(self) -> dict[str, Any]:
        """观测用字典（日志 / 健康检查端点友好，不含 tool schema 全文）。"""
        return {
            "code": self.spec.code,
            "kind": self.spec.kind.value,
            "source": self.spec.source,
            "version": self.spec.version,
            "state": self.state.value,
            "healthy": self.healthy,
            "tools": len(self.spec.tools),
            "error": self.error,
            "load_count": self.load_count,
            "error_count": self.error_count,
        }
