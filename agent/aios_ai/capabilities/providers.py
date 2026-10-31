"""内置/外部能力的 Provider 实现。

顺序纪律（**零回归硬约束**）
==========================
改造前 ``graph/nodes.py#prepare`` 的装配是三段前置拼接，最终顺序为：

    [web_search, web_fetch] + [ask_user, request_form, request_confirm] + [原有网关工具…]
    （MCP 工具更早，已在前一步 ``tools`` 列表里）

注意 **web_search 被放在 HITL 三工具之前**、而 HITL 三工具又被放在列表最前 —— 由于
``prepare`` 里是 ``tools = [A,B] + tools`` 再 ``tools = [C,D,E] + tools``，最终头部顺序
实际是 ``C,D,E,A,B``。本模块用 :func:`builtin_specs` 显式产出 ``C,D,E,A,B``，
使注册表路径与手写路径**逐项同序**，不依赖拼接技巧。
"""
from __future__ import annotations

import logging
from typing import Any

from aios_ai.capabilities.models import CapabilityKind, CapabilitySpec
from aios_ai.capabilities.registry import CapabilityProvider
from aios_ai.config import settings
from aios_ai.tools import ask_user as ask_user_tool
from aios_ai.tools import request_confirm as request_confirm_tool
from aios_ai.tools import request_form as request_form_tool
from aios_ai.tools import web_search as web_search_tool

logger = logging.getLogger("aios.ai.capabilities")


def _hitl_enabled() -> bool:
    """HITL 总开关（与 graph/nodes.py 同口径，``getattr`` 兜底是为了兼容精简 settings shim 的哨兵）。"""
    return bool(getattr(settings, "agent_hitl", False))


class HitlProvider(CapabilityProvider):
    """HITL 三条控制链（澄清 / 表单 / 确认）。关开关时 ``available=False`` ⇒ UNRESOLVED。"""

    code = "hitl"
    kind = CapabilityKind.BUILTIN

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        return _hitl_enabled()

    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        # 顺序 = 旧实现的常量顺序：ask_user / request_form / request_confirm
        return [CapabilitySpec(
            code="hitl",
            kind=CapabilityKind.BUILTIN,
            source="aios_ai.tools.{ask_user,request_form,request_confirm}",
            description="HITL 三条控制链：澄清提问 / 结构化表单 / 二值确认",
            tools=[ask_user_tool.ASK_USER_TOOL,
                   request_form_tool.REQUEST_FORM_TOOL,
                   request_confirm_tool.REQUEST_CONFIRM_TOOL],
        )]


class WebProvider(CapabilityProvider):
    """内置联网检索（免密钥）。``web_search_enabled`` 关掉 ⇒ UNRESOLVED（不是 ERROR）。"""

    code = "web"
    kind = CapabilityKind.BUILTIN

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        return bool(getattr(settings, "web_search_enabled", True))

    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        return [CapabilitySpec(
            code="web",
            kind=CapabilityKind.BUILTIN,
            source="aios_ai.tools.web_search",
            description="内置联网检索（免密钥）：联网搜索 / 抓取正文",
            tools=[web_search_tool.WEB_SEARCH_TOOL, web_search_tool.WEB_FETCH_TOOL],
        )]


class McpProvider(CapabilityProvider):
    """MCP 连接器工具（经 mcp-hub / Java manifest）。

    拉取本身由 ``ToolClient.list_mcp_tools()`` 完成（那里已有按 token 的类级缓存与降级语义），
    这里只负责把它纳入统一注册与生命周期 —— 不重写网络逻辑，避免两处事实源。
    """

    code = "mcp"
    kind = CapabilityKind.MCP

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        return bool(getattr(settings, "mcp_hub_enabled", False))

    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        tools = (ctx or {}).get("mcp_tools") or []
        sources = sorted({str(t.get("source") or "") for t in tools
                          if isinstance(t, dict) and t.get("source")})
        return [CapabilitySpec(
            code="mcp",
            kind=CapabilityKind.MCP,
            source=",".join(sources) or "mcp-hub",
            description="MCP 连接器工具（运行时由 Java manifest 发现）",
            tools=list(tools),
        )] if tools else []


class SkillProvider(CapabilityProvider):
    """**技能扩展位**（本次为后续批量接入预留，默认不产出任何能力）。

    落点说明：现网「技能」存在 ``ai_skill`` 表，但那是 V3 时代的**会话模板 / 动态表单**
    配置（无 status / version / 无注册中心 / 与连接器零关联）。本 Provider 是真正的
    统一入口的预留实现：

      * 默认 :meth:`available` 返回 ``False`` ⇒ 状态 UNRESOLVED，**工具表与改造前逐字节一致**；
      * 将来无论技能来源是 DB、远端注册中心还是本地目录，只需实现 :meth:`list_specs`；
      * 生命周期、停用、-health 观测全部复用注册表，不再各写一套。
    """

    code = "skill"
    kind = CapabilityKind.SKILL

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        return bool(getattr(settings, "skill_registry_enabled", False))

    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        # 扩展位：真实实现应按 skill source 产出 {skill_code: tools}。这里刻意留空并在
        # 日志里点名 —— 「静默什么都不做」和「还没接入」在观测上必须能区分。
        logger.info("skill registry enabled but no skill source configured（扩展位，尚无技能源）")
        return []


def build_default_registry():
    """构造进程默认注册表并完成注册（**不加载**，加载在每次 run 的 prepare 里）。

    注册顺序 = 最终注入顺序，**必须与旧手写拼接逐项同序**（零回归硬约束）：
      HITL 三工具 → 联网两工具 → MCP 工具 → 技能（当前扩展位，恒空）
    再往后才是业务网关工具，由 prepare 在调用方拼上（注册表不碰网关清单）。
    """
    from aios_ai.capabilities.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register(HitlProvider())
    reg.register(WebProvider())
    reg.register(McpProvider())
    reg.register(SkillProvider())
    return reg


# 进程级默认注册表。为什么是模块级单例而不是每次现建：能力注册是**进程级**事实
# （开关在进程生命周期内不变），每次 run 现建会让「累计错误数」「人工停用」丢失。
_DEFAULT_REGISTRY = None


def get_registry():
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY


def reset_registry() -> None:
    """重建默认注册表（测试用，或配置热更新后重建）。"""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY
