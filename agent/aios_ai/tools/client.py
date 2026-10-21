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

# MCP 连接器接入（契约 docs/59 §10）：把上游 MCP server 的工具变成 LangChain Tool，
# 再归一成 OpenAI function 形状注入模型。这两个包已在 agent pyproject 声明（mcp / langchain-mcp-adapters）。
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient

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

    # ★ 跨节点 MCP 工具缓存（2026-10-21 修根因）：graph 的 tools 节点与执行节点各自
    # from_request() 重建实例（运行期对象不进 checkpointer 状态），实例属性 _mcp_tools
    # 只存在于拉清单的那个实例上 ⇒ 执行节点的新实例查不到 —— 模型明明看到了工具，
    # invoke 却报「MCP 工具不存在或服务器未就绪」（实测复现）。故镜像一份按 token 键
    # （与 from_request 的配对键一致）挂在类上；同 token 每次 list 覆盖，不跨用户泄漏。
    _MCP_TOOLS_BY_TOKEN: dict[str, dict[str, tuple[object, str]]] = {}

    def __init__(self, base_url: str, user_token: str | None, timeout: float = 10.0,
                 mcp_manifest: list[dict] | None = None):
        self._base_url = base_url.rstrip("/")
        self._token = (user_token or "").strip()
        self._timeout = timeout
        # list_tools 的失败原因。调用方据此区分「真的没有工具（200+空数组）」与
        # 「网关不可用/非 200（本来该有工具）」—— 两者都返回 []，但后者会导致
        # 知识库被静默跳过（见 graph/nodes.py 的 kb 降级提示）。
        self.list_error: str | None = None
        # 注入的 manifest（**仅测试用**：生产路径仍走 HTTP 拉取 /api/v1/mcp/manifest）。
        # 哨兵脚本用它绕过不可达的 Java 后端，构造一个本地可用的 MCP server 清单。
        self._mcp_manifest = mcp_manifest
        # MCP 连接器的失败原因（与 list_error 同口径：不抛，供 nodes.py 显式降级）。
        # 单个 server 连不上只记原因、其它 server 照常返回；全部失败也返回 []。
        self.mcp_error: str | None = None
        # 全名(mcp__<code>__<tool>) → (BaseTool 原对象, 原名)，供 invoke 按前缀回派。
        self._mcp_tools: dict[str, tuple[object, str]] = {}

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

    async def list_mcp_tools(self) -> list[dict]:
        """拉取 MCP 连接器工具并归一成 OpenAI function 形状（前缀 ``mcp__<serverCode>__<toolName>``）。

        与 ``list_tools`` 的失败语义同口径（契约 docs/59 §10.4 判据 4：失败不静默、但也不让整轮挂掉）：
          - ``mcp_hub_enabled`` 为假或无用户 token ⇒ 直接返回 ``[]`` 且 ``mcp_error is None``（不算失败）；
          - manifest 非 200 / 异常 ⇒ 记 ``mcp_error``、**不抛**、返回 ``[]``；
          - 单个 server 连不上 ⇒ 记原因（可拼接多个，截断 300 字），其它 server 照常；全部失败也返回 ``[]``。

        多个 server 用 ``asyncio.gather(return_exceptions=True)`` 并发拉取，不串行等。
        """
        self.mcp_error = None
        self._mcp_tools = {}
        # 任何一次 list 都先作废该 token 的跨节点缓存：开关关闭/清单拉取失败时，
        # 执行节点不得回落到上一轮的旧工具（W6 负向判据）。
        ToolClient._MCP_TOOLS_BY_TOKEN.pop(self._token, None)
        # 关闭开关或无 token ⇒ 与改造前逐字节一致：不连 hub、不发 manifest 请求、不注入任何 mcp__* 工具。
        if not settings.mcp_hub_enabled or not self.enabled:
            return []

        # 1) 取 manifest：测试可注入，否则走 Java /api/v1/mcp/manifest。
        try:
            if self._mcp_manifest is None:
                async with httpx.AsyncClient(timeout=settings.mcp_hub_timeout) as client:
                    resp = await client.get(f"{self._base_url}/api/v1/mcp/manifest",
                                            headers=self._headers())
                    body = resp.json()
                if resp.status_code != 200 or not isinstance(body.get("data"), list):
                    self.mcp_error = f"manifest status={resp.status_code}"
                    return []
                servers = body["data"]
            else:
                servers = self._mcp_manifest
        except Exception as exc:            # noqa: BLE001 —— 统一收敛成可读原因
            self.mcp_error = f"{type(exc).__name__}: {exc}"
            return []
        if not servers:
            return []

        # 2) 并发拉每个 server 的工具，并归一成 OpenAI function 形状（加前缀）。
        async def _load_one(srv: dict) -> list[dict]:
            code = srv.get("code")
            url = srv.get("url")
            mcp_client = MultiServerMCPClient({
                code: {"transport": "streamable_http", "url": url,
                       "headers": {"Authorization": f"Bearer {self._token}"}}
            })
            raw_tools = await mcp_client.get_tools()     # list[BaseTool]
            out: list[dict] = []
            for t in raw_tools:
                oai = convert_to_openai_tool(t)
                full = f"mcp__{code}__{t.name}"
                oai["function"]["name"] = full           # 仅改名字，description/parameters 不动
                self._mcp_tools[full] = (t, t.name)
                out.append(oai)
            return out

        results = await asyncio.gather(
            *[_load_one(s) for s in servers], return_exceptions=True)
        merged: list[dict] = []
        reasons: list[str] = []
        for r in results:
            if isinstance(r, Exception):
                reasons.append(str(r))
            else:
                merged.extend(r)
        if reasons:
            self.mcp_error = "; ".join(reasons)[:300]
        if self._token:
            ToolClient._MCP_TOOLS_BY_TOKEN[self._token] = self._mcp_tools
        return merged

    async def invoke(self, name: str, arguments: dict | None = None) -> ToolOutcome:
        """执行单个工具；网络/契约异常统一收敛为 ok=False，交由模型组织失败回答。

        ``mcp__`` 前缀 ⇒ 走 MCP 连接器通道（按 _mcp_tools 回派到对应 BaseTool）；
        其余名称 ⇒ 既有 Java 网关路径，行为完全不变。
        """
        args = arguments or {}
        # ★ MCP 连接器分支：前缀分流。先查本实例（同一实例拉过清单，如哨兵 W3/W5），
        #   再查类级跨节点缓存（生产主路径：tools 节点拉清单、执行节点新实例）。
        #   找不到映射是负向判据（必须显式报错，不能回落 Java 网关）。
        if name.startswith("mcp__"):
            entry = self._mcp_tools.get(name) or \
                ToolClient._MCP_TOOLS_BY_TOKEN.get(self._token, {}).get(name)
            if entry is None:
                return ToolOutcome(name=name, arguments=args, ok=False,
                                   error="MCP 工具不存在或服务器未就绪：" + name)
            tool_obj = entry[0]
            try:
                resp = await tool_obj.ainvoke(args)     # BaseTool：内部完成 MCP tools/call
                # 归一 content blocks（list[dict]）与直接返回值两种形状。
                if isinstance(resp, list) and resp and isinstance(resp[0], dict):
                    parts: list[str] = []
                    is_error = False
                    for c in resp:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "text":
                            parts.append(c.get("text", ""))
                        if c.get("isError"):
                            is_error = True
                        # hub 按 docs/59 §10.3 返回 isError=True 的 CallToolResult，但
                        # langchain-mcp-adapters 归一成纯 text block 时**丢掉 isError 标记**，
                        # 只留下 FastMCP 客户端的固定错误前缀（实测：空参调用返回
                        # ok=true + "Error executing tool …" 文本，模型误以为成功）。
                        # 该前缀是 FastMCP 客户端包装层固有的，按前缀判失败不是猜。
                        if str(c.get("text", "")).startswith("Error executing tool"):
                            is_error = True
                    data = "\n".join(parts)
                    if is_error:
                        return ToolOutcome(name=name, arguments=args, ok=False,
                                           error=data or "MCP 工具返回错误")
                    return ToolOutcome(name=name, arguments=args, ok=True, data=data)
                return ToolOutcome(name=name, arguments=args, ok=True, data=resp)
            except Exception as exc:
                logger.warning("mcp invoke %s failed: %s", name, exc)
                return ToolOutcome(name=name, arguments=args, ok=False, error=str(exc)[:300])
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
