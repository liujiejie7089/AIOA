# -*- coding: utf-8 -*-
"""能力层（capabilities）测试 —— 2026-10-31 重构引入的统一注册/加载/生命周期。

核心判据是 **K7：注册表路径必须与改造前的手写拼接逐项同序**。
改造前 prepare 里是三段手工前置拼接（MCP / 联网 / HITL），顺序靠 `tools = [A] + tools`
的叠加技巧隐式决定，任何一次顺序变动都会静默改变模型看到的工具优先级。
把它搬进注册表之后，顺序变成注册顺序 —— 必须有一条断言盯着，否则移植过程中
「看起来都注入了、顺序反了」这类缺陷没人会发现。

其余判据对应「失败隔离 / 生命周期不允许假绿 / 停用要跨注册存活 / 状态机不可绕过」。
"""
from __future__ import annotations

import asyncio

import pytest

from aios_ai import capabilities
from aios_ai.capabilities.models import (
    CapabilityKind,
    CapabilitySpec,
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
    reset_registry,
)
from aios_ai.capabilities.registry import CapabilityProvider, CapabilityRegistry, StaticProvider


def names(tools):
    out = []
    for t in tools:
        n = (t.get("function") or {}).get("name") if isinstance(t, dict) else None
        out.append(n or (t.get("name") if isinstance(t, dict) else None))
    return out


class Boom(CapabilityProvider):
    """永远失败的 provider：用于验证「一个上门的门失灵，别的照常用」."""

    code = "boom"
    kind = CapabilityKind.PLUGIN

    def __init__(self, exc=None):
        self.exc = exc or RuntimeError("清单服务不可用")

    async def list_specs(self, ctx=None):
        raise self.exc


def _spec(code, tool):
    return CapabilitySpec(code=code, kind=CapabilityKind.BUILTIN,
                          tools=[{"type": "function", "function": {"name": tool}}])


# --------------------------------------------------------------------------- K1 顺序零回归

def test_registry_order_matches_hand_written_assembly(monkeypatch):
    """K1（最关键）：注册表产出的 head 顺序 == 旧手写拼接的顺序。"""
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "agent_hitl", True, raising=False)
    monkeypatch.setattr(settings, "web_search_enabled", True, raising=False)
    monkeypatch.setattr(settings, "mcp_hub_enabled", True, raising=False)

    reg = build_default_registry()
    mcp_tools = [{"type": "function", "function": {"name": "mcp__mail__read"}}]
    tools, states = asyncio.run(reg.load({"mcp_tools": mcp_tools}))

    # 旧实现：mcp → + web → + hitl，最终 [ask_user, request_form, request_confirm, web_search, web_fetch, mcp...]
    assert names(tools) == ["ask_user", "request_form", "request_confirm",
                            "web_search", "web_fetch", "mcp__mail__read"], names(tools)
    assert all(s.state is LifecycleState.READY for s in states if s.spec.code != "skill")


def test_all_switches_off_produces_empty_head(monkeypatch):
    """K2：三个开关全关 ⇒ head 为空，且是 UNRESOLVED（缺依赖）而不是 ERROR（故障）。"""
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "agent_hitl", False, raising=False)
    monkeypatch.setattr(settings, "web_search_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mcp_hub_enabled", False, raising=False)

    reg = build_default_registry()
    tools, states = asyncio.run(reg.load({}))
    assert tools == [], tools
    assert [s.state for s in states] == [LifecycleState.UNRESOLVED] * 4, [s.state for s in states]
    assert reg.health()["errors"] == [], "开关没开不算故障，不允许把健康检查染红"


# --------------------------------------------------------------------------- K3 失败隔离

def test_single_provider_failure_does_not_kill_others():
    """K3：一个 provider 抛异常只把它自己打成 ERROR，其余能力照常注入。"""
    reg = CapabilityRegistry()
    reg.register(StaticProvider("web", CapabilityKind.BUILTIN, [_spec("web", "web_search")]))
    reg.register(Boom())
    reg.register(StaticProvider("hitl", CapabilityKind.BUILTIN, [_spec("hitl", "ask_user")]))

    tools, states = asyncio.run(reg.load({}))
    assert names(tools) == ["web_search", "ask_user"], names(tools)
    boom_state = next(s for s in states if s.spec.code == "boom")
    assert boom_state.state is LifecycleState.ERROR
    assert "清单服务不可用" in (boom_state.error or "")
    assert boom_state.error_count == 1
    health = reg.health()
    assert [e["code"] for e in health["errors"]] == ["boom"]


def test_error_is_recoverable_on_next_load():
    """K4：恢复后能从 ERROR 回到 READY（否则一次抖动就永久停用），且累计错误数不清零。"""
    reg = CapabilityRegistry()
    boom = Boom()
    reg.register(boom)
    asyncio.run(reg.load({}))
    assert reg.get("boom").state is LifecycleState.ERROR

    boom.exc = None

    class _Ok(type(boom)):                      # 同 code，行为改正常
        async def list_specs(self, ctx=None):
            return [_spec("boom", "recovered_tool")]

    reg.register(_Ok())
    tools, states = asyncio.run(reg.load({}))
    assert names(tools) == ["recovered_tool"], names(tools)
    st = reg.get("boom")
    assert st.state is LifecycleState.READY
    assert st.error_count == 1, "历史错误计数不得被重载洗白"


# --------------------------------------------------------------------------- K5 生命周期不允许假绿

def test_enable_returns_to_registered_not_ready():
    """K5：enable 只能回到 REGISTERED，**不许**直接标 READY —— 没重新验证就说好了是典型的假绿。"""
    reg = CapabilityRegistry()
    reg.register(StaticProvider("web", CapabilityKind.BUILTIN, [_spec("web", "web_search")]))
    asyncio.run(reg.load({}))
    assert reg.disable("web") is True
    tools, _ = asyncio.run(reg.load({}))
    assert tools == [], "停用后不得再注入"

    assert reg.enable("web") is True
    assert reg.get("web").state is LifecycleState.REGISTERED, reg.get("web").state
    tools2, _ = asyncio.run(reg.load({}))
    assert names(tools2) == ["web_search"]


def test_disable_survives_re_registration():
    """K6：人工停用必须跨注册存活 —— 否则热重载/重新 regist er 就把停用的能力悄悄放回来。"""
    reg = CapabilityRegistry()
    reg.register(StaticProvider("risky", CapabilityKind.PLUGIN, [_spec("risky", "delete_all")]))
    reg.disable("risky", reason="安全风险，暂停使用")
    reg.register(StaticProvider("risky", CapabilityKind.PLUGIN, [_spec("risky", "delete_all")]))
    tools, _ = asyncio.run(reg.load({}))
    assert tools == [], tools
    assert reg.health()["disabled"] == ["risky"]


def test_unregister_removes_completely():
    reg = CapabilityRegistry()
    reg.register(StaticProvider("a", CapabilityKind.BUILTIN, [_spec("a", "tool_a")]))
    reg.unregister("a")
    tools, states = asyncio.run(reg.load({}))
    assert tools == [] and states == []
    assert reg.health()["total"] == 0


def test_disable_unknown_code_returns_false():
    reg = CapabilityRegistry()
    assert reg.disable("nope") is False
    assert reg.enable("nope") is False


# --------------------------------------------------------------------------- K7 状态机

def test_illegal_transition_is_rejected():
    """K7：非法迁移必须抛异常。状态机能静默跳转的话，没人会再信 health 里的状态。"""
    assert can_transit(LifecycleState.REGISTERED, LifecycleState.REGISTERED) is True
    assert can_transit(LifecycleState.REGISTERED, LifecycleState.RESOLVED) is True
    assert can_transit(LifecycleState.REGISTERED, LifecycleState.READY) is False
    assert can_transit(LifecycleState.DISABLED, LifecycleState.READY) is False

    reg = CapabilityRegistry()
    reg.register(StaticProvider("x", CapabilityKind.BUILTIN, []))
    with pytest.raises(IllegalTransition):
        reg._transit(reg.get("x"), LifecycleState.READY, None)


# --------------------------------------------------------------------------- K8 MCP / 技能扩展位

def test_mcp_tools_from_ctx_and_source_aggregated(monkeypatch):
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "mcp_hub_enabled", True, raising=False)
    p = McpProvider()
    assert p.available() is True
    specs = asyncio.run(p.list_specs({"mcp_tools": [
        {"name": "mcp__mail__read", "source": "mail"},
        {"name": "mcp__mail__send", "source": "mail"},
    ]}))
    assert len(specs) == 1 and specs[0].tool_names == ["mcp__mail__read", "mcp__mail__send"]
    assert specs[0].source == "mail"
    # 空清单 ⇒ 空 spec（不留一个 “假的 mcp 能力” 占着 READY）
    assert asyncio.run(p.list_specs({"mcp_tools": []})) == []


def test_skill_extension_point_is_inert_by_default(monkeypatch):
    """K8：技能扩展位默认不可用 ⇒ 不产出任何工具（今天的工具表必须与改动前一致）。"""
    from aios_ai.config import settings

    monkeypatch.delattr(settings, "skill_registry_enabled", raising=False)
    p = SkillProvider()
    assert p.available() is False
    assert asyncio.run(p.list_specs({})) == []
    reg = build_default_registry()
    tools, states = asyncio.run(reg.load({}))
    sk = next(s for s in states if s.spec.code == "skill")
    assert sk.state is LifecycleState.UNRESOLVED
    assert "skill" not in names(tools)


def test_health_snapshot_leaks_no_tool_schema():
    """观测安全：health() 里只报工具**个数**，不把 schema 全文塞进日志/端点。"""
    reg = CapabilityRegistry()
    reg.register(StaticProvider("web", CapabilityKind.BUILTIN, [_spec("web", "web_search")]))
    asyncio.run(reg.load({}))
    h = reg.health()
    item = next(i for i in h["items"] if i["code"] == "web")
    assert item["tools"] == 1
    assert "tools" not in item or isinstance(item["tools"], int)
    assert h["ready"] == 1 and h["total"] == 1


def test_default_registry_is_singleton_and_resettable():
    a = capabilities.get_registry()
    b = capabilities.get_registry()
    assert a is b, "默认注册表必须是进程级单例（否则累计错误数与人工停用会丢）"
    c = reset_registry()
    assert c is not a
    assert capabilities.get_registry() is c


def test_register_requires_code():
    class Nameless(CapabilityProvider):
        code = ""
        async def list_specs(self, ctx=None):
            return []

    with pytest.raises(ValueError):
        CapabilityRegistry().register(Nameless())


def test_hitl_and_web_providers_respect_switches(monkeypatch):
    from aios_ai.config import settings

    monkeypatch.setattr(settings, "agent_hitl", False, raising=False)
    assert HitlProvider().available() is False
    monkeypatch.setattr(settings, "agent_hitl", True, raising=False)
    assert HitlProvider().available() is True
    specs = asyncio.run(HitlProvider().list_specs({}))
    assert specs[0].tool_names == ["ask_user", "request_form", "request_confirm"]

    monkeypatch.setattr(settings, "web_search_enabled", False, raising=False)
    assert WebProvider().available() is False
    monkeypatch.setattr(settings, "web_search_enabled", True, raising=False)
    assert asyncio.run(WebProvider().list_specs({}))[0].tool_names == ["web_search", "web_fetch"]
