"""业务工具网关客户端：Agent 调用业务系统接口的唯一通道。

对应 Java 侧 /api/v1/tools（清单）与 /api/v1/tools/invoke（执行）。
鉴权：透传发起方用户 accessToken —— 工具权限 = 用户权限，越权数据天然不可达。
设计约定（技术方案「工具调用按权限码白名单放行」）：Java 侧注册表即白名单，
Agent 侧不做二次授权，只负责把模型输出的 tool_calls 转发给网关执行。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from aios_ai.config import settings

logger = logging.getLogger("aios.agent.tools")

# 单次 run 允许的最大工具执行轮数（防模型死循环）
MAX_TOOL_ROUNDS = 4


@dataclass
class ToolOutcome:
    """一次工具执行的结果。"""

    name: str
    arguments: dict
    ok: bool
    data: object = None
    error: str | None = None

    def summary(self) -> str:
        """给事件流/日志用的单行摘要（截断，避免大 payload 刷屏）。"""
        if not self.ok:
            return f"{self.name} failed: {self.error}"
        text = str(self.data)
        return f"{self.name} ok: {text[:120]}{'…' if len(text) > 120 else ''}"


class ToolClient:
    """面向一次 run 的工具客户端（携带该 run 用户的 token）。"""

    def __init__(self, base_url: str, user_token: str | None, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._token = (user_token or "").strip()
        self._timeout = timeout
        # list_tools 的失败原因。调用方据此区分「真的没有工具（200+空数组）」与
        # 「网关不可用/非 200（本来该有工具）」—— 两者都返回 []，但后者会导致
        # 知识库被静默跳过（见 graph/nodes.py 的 kb 降级提示）。
        self.list_error: str | None = None

    @classmethod
    def from_request(cls, user_token: str | None) -> "ToolClient":
        return cls(settings.aios_server_base_url, user_token)

    @property
    def enabled(self) -> bool:
        """无用户 token 时工具不可用（回声/纯推理模式）。"""
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def list_tools(self) -> list[dict]:
        """拉取工具清单（OpenAI function 格式）。

        返回 [] 有两种截然不同的含义，必须可区分（旧实现把两者混为一谈）：
          - 网关正常、该用户确实没有工具 ⇒ ``list_error is None``；
          - 网关不可达 / 非 200 ⇒ ``list_error`` 有值。

        为什么重要：知识库工具就在这份清单里。失败时静默返回 [] 会让
        ``has_kb_tool([])`` 为假 ⇒ 预检索整段不跑、run 照样 SUCCESS，
        用户看到的是「AI 没查知识库就答了」，且没有任何告警。
        """
        self.list_error = None
        if not self.enabled:
            return []
        last_exc: str | None = None
        for attempt in range(2):            # 一次重试：吸收网关重启/瞬时 glitch
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(f"{self._base_url}/api/v1/tools", headers=self._headers())
                    body = resp.json()
                if resp.status_code == 200 and isinstance(body.get("data"), list):
                    return body["data"]
                last_exc = f"status={resp.status_code}"
            except Exception as exc:        # noqa: BLE001 —— 统一收敛成可读原因
                last_exc = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                await asyncio.sleep(0.2)
        self.list_error = last_exc or "unknown"
        logger.error("list_tools failed after retry: %s（本轮知识库不可用，已在提示中显式告知模型）",
                     self.list_error)
        return []

    async def invoke(self, name: str, arguments: dict | None = None) -> ToolOutcome:
        """执行单个工具；网络/契约异常统一收敛为 ok=False，交由模型组织失败回答。"""
        args = arguments or {}
        if not self.enabled:
            return ToolOutcome(name=name, arguments=args, ok=False, error="工具网关不可用（缺少用户凭证）")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/v1/tools/invoke",
                    json={"name": name, "arguments": args},
                    headers=self._headers(),
                )
                body = resp.json()
            if resp.status_code != 200:
                return ToolOutcome(name=name, arguments=args, ok=False, error=f"HTTP {resp.status_code}")
            data = body.get("data")
            if isinstance(data, dict) and data.get("ok") is True:
                return ToolOutcome(name=name, arguments=args, ok=True, data=data.get("data"))
            return ToolOutcome(name=name, arguments=args, ok=False,
                               error=str((data or {}).get("error") if isinstance(data, dict) else body.get("message")))
        except Exception as exc:
            logger.warning("invoke %s failed: %s", name, exc)
            return ToolOutcome(name=name, arguments=args, ok=False, error=str(exc)[:200])
