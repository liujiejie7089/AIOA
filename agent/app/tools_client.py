"""业务工具网关客户端：Agent 调用业务系统接口的唯一通道。

对应 Java 侧 /api/v1/tools（清单）与 /api/v1/tools/invoke（执行）。
鉴权：透传发起方用户 accessToken —— 工具权限 = 用户权限，越权数据天然不可达。
设计约定（技术方案「工具调用按权限码白名单放行」）：Java 侧注册表即白名单，
Agent 侧不做二次授权，只负责把模型输出的 tool_calls 转发给网关执行。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger("aioa.agent.tools")

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

    @classmethod
    def from_request(cls, user_token: str | None) -> "ToolClient":
        return cls(settings.aioa_server_base_url, user_token)

    @property
    def enabled(self) -> bool:
        """无用户 token 时工具不可用（回声/纯推理模式）。"""
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def list_tools(self) -> list[dict]:
        """拉取工具清单（OpenAI function 格式）；网关不可达/为空时返回 []，推理照常。"""
        if not self.enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/api/v1/tools", headers=self._headers())
                body = resp.json()
            if resp.status_code == 200 and isinstance(body.get("data"), list):
                return body["data"]
            logger.warning("list_tools unexpected response: status=%s", resp.status_code)
            return []
        except Exception as exc:
            logger.warning("list_tools failed: %s", exc)
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
