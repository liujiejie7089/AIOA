"""注册表内核：一处注册、一处加载、一套生命周期。

对外只有三个动作：``register(provider)``、``load(ctx)``、``lifecycle 控制 + health``。
之所以把三者放同一个类而不是拆成 Registry / Loader / Health 三个服务：本进程里它们是
**同一份状态**（能力的 Identity + 状态 + 清单）的三个视图，拆开就要维护同步，是纯粹的成本。
真要横向扩展（多进程、远端注册中心）时，只需把 :meth:`CapabilityRegistry._store` 换成
远端读写即可，接口不变。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Iterable

from aios_ai.capabilities.models import (
    CapabilityKind,
    CapabilitySpec,
    CapabilityState,
    IllegalTransition,
    LifecycleState,
    can_transit,
)

logger = logging.getLogger("aios.ai.capabilities")


class CapabilityProvider(ABC):
    """能力提供者接口：**这是后续接入 skills / connectors 的唯一扩展点**。

    实现一个新来源只需要三件事：给 ``code``、说清 ``kind``、实现 ``list_specs``。
    ``available`` 用于「依赖没到位」这种**不算故障**的情况（返回 False ⇒ UNRESOLVED，
    不设 ERROR，免得一个没开开关的能力把健康检查染红）。
    """

    code: str = ""
    kind: CapabilityKind = CapabilityKind.BUILTIN

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        """依赖是否到位。默认 True（内置能力永远可用）。"""
        return True

    @abstractmethod
    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        """列出本 provider 当前能提供能力清单。抛异常 ⇒ 该能力进 ERROR（由 Registry 捕获）。"""
        raise NotImplementedError


class StaticProvider(CapabilityProvider):
    """通用静态提供者：把一组固定 spec 包成 provider（内置工具/常量清单用它）。"""

    def __init__(self, code: str, kind: CapabilityKind, specs: Iterable[CapabilitySpec],
                 available: bool = True):
        self.code = code
        self.kind = kind
        self._specs = list(specs)
        self._available = available

    def available(self, ctx: dict[str, Any] | None = None) -> bool:
        return self._available

    async def list_specs(self, ctx: dict[str, Any] | None = None) -> list[CapabilitySpec]:
        return list(self._specs)


class CapabilityRegistry:
    """能力注册表（进程级单例语义，但本身是可实例化的对象，便于单测隔离）。"""

    def __init__(self) -> None:
        self._store: dict[str, CapabilityState] = {}
        self._providers: dict[str, CapabilityProvider] = {}
        self._order: list[str] = []            # 注册顺序 ⇒ 注入顺序的唯一权威（dict 也有序，留作显式契约）
        self._disabled: set[str] = set()       # 显式停用：即使重新注册也不恢复到 READY

    # ------------------------------------------------------------------ 注册

    def register(self, provider: CapabilityProvider) -> CapabilityState:
        """登记一个 provider。重复注册按 code **覆盖**（幂等），并从 REGISTERED 重来。

        为什么不去重报错：热重载/多次 import 是常态，报异常会让进程起不来，
        而「同 code 后覆盖前」是我们真正想要的语义（配置变了要生效）。
        """
        if not provider.code:
            raise ValueError("provider 必须给 code（它是 disable/enable/health 的定位键）")
        spec = CapabilitySpec(code=provider.code, kind=provider.kind, source=provider.code)
        prev = self._store.get(provider.code)
        st = CapabilityState(spec=spec, state=LifecycleState.REGISTERED)
        # 继承历史计数：health 里的累计错误数不该因为重载被洗白
        if prev:
            st.load_count = prev.load_count
            st.error_count = prev.error_count
            st.error = prev.error
        self._store[provider.code] = st
        self._providers[provider.code] = provider
        if provider.code not in self._order:
            self._order.append(provider.code)
        return st

    def unregister(self, code: str) -> bool:
        """注销（测试/热卸载用）。生产上一律用 ``disable`` —— 停用的能力要留痕。"""
        self._disabled.discard(code)
        self._order = [c for c in self._order if c != code]
        self._providers.pop(code, None)
        return self._store.pop(code, None) is not None

    # ------------------------------------------------------------------ 加载

    async def load(self, ctx: dict[str, Any] | None = None) -> tuple[list[dict], list[CapabilityState]]:
        """按注册顺序加载所有能力，产出（工具清单，各能力状态快照）。

        三条纪律：
          1. **顺序即注册顺序**（现有行为依赖它：MCP 在前、联网在前、HITL 三工具在最前）；
          2. **失败隔离**：单个 provider 抛错只把它打到 ERROR，其余照常；
          3. **停用优先**：``_disabled`` 里的能力连 ``available()`` 都不问，直接 DISABLED。
        """
        ctx = ctx or {}
        tools: list[dict] = []
        states: list[CapabilityState] = []
        for code in list(self._order):
            st = self._store[code]
            states.append(st)
            provider = self._providers.get(code)
            if provider is None:                       # 理论不可达：register 一定会塞
                self._transit(st, LifecycleState.ERROR, "注册中心里没有 provider 实例")
                continue
            if code in self._disabled:
                self._transit(st, LifecycleState.DISABLED, None)
                continue
            try:
                if not provider.available(ctx):
                    self._transit(st, LifecycleState.UNRESOLVED, None)
                    continue
                # 依赖确认到位 ⇒ RESOLVED，再由下面「清单真的取到了」推到 READY。
                # 中间这一步不是形式主义：UNRESOLVED/RESOLVED 的区分让我们能把
                # 「开关没开」与「开了但拉清单失败」在 health 里分开看。
                self._transit(st, LifecycleState.RESOLVED, None)
                specs = await provider.list_specs(ctx)
            except Exception as exc:                   # noqa: BLE001 ——失败必须隔离到能力粒度
                self._transit(st, LifecycleState.ERROR, f"{type(exc).__name__}: {exc}"[:300])
                st.error_count += 1
                logger.warning("capability %s load failed: %s", code, exc)
                continue
            st.spec.tools = [t for spec in specs for t in spec.tools]
            st.spec.version = ";".join(s.version for s in specs if s.version) or st.spec.version
            st.spec.source = ";".join(s.source for s in specs if s.source) or st.spec.source
            st.load_count += 1
            self._transit(st, LifecycleState.READY, None)
            for spec in specs:
                tools.extend(spec.tools)
        return tools, states

    # ------------------------------------------------------------------ 生命周期

    def _transit(self, st: CapabilityState, dst: LifecycleState, error: str | None) -> None:
        """唯一的状态写入口：非法迁移抛异常，合法迁移顺带维护 error 字段。"""
        if not can_transit(st.state, dst):
            raise IllegalTransition(f"{st.spec.code}: {st.state.value} → {dst.value} 非法迁移")
        st.state = dst
        if dst is LifecycleState.ERROR:
            st.error = error or "未知错误"
        elif dst in (LifecycleState.READY, LifecycleState.RESOLVED):
            st.error = None

    def disable(self, code: str, reason: str = "运维停用") -> bool:
        """停用：跨注册存活（重注册也不自动回来）—— 「我关了就不要自己开」是最低要求。"""
        st = self._store.get(code)
        if st is None:
            return False
        self._disabled.add(code)
        self._transit(st, LifecycleState.DISABLED, None)
        st.error = reason
        return True

    def enable(self, code: str) -> bool:
        """解除停用。回到 REGISTERED 等下一次 load 重新判定，而不是直接声称 READY
        —— 「我没验证过就说它好了」是最典型的假绿。"""
        st = self._store.get(code)
        if st is None:
            return False
        self._disabled.discard(code)
        self._transit(st, LifecycleState.REGISTERED, None)
        return True

    # ------------------------------------------------------------------ 观测

    def health(self) -> dict[str, Any]:
        """全量健康快照：给日志 / 健康检查端点用。**OK 与否只看有无 ERROR**。"""
        items = [self._store[c].as_dict() for c in self._order]
        return {
            "total": len(items),
            "ready": sum(1 for i in items if i["state"] == LifecycleState.READY.value),
            "errors": [i for i in items if i["state"] == LifecycleState.ERROR.value],
            "unresolved": [i["code"] for i in items if i["state"] == LifecycleState.UNRESOLVED.value],
            "disabled": sorted(self._disabled),
            "items": items,
        }

    def get(self, code: str) -> CapabilityState | None:
        return self._store.get(code)

    def codes(self) -> list[str]:
        return list(self._order)
