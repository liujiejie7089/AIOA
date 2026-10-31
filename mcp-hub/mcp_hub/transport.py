# -*- coding: utf-8 -*-
"""MCP 传输层安全设置（Host 白名单）—— 唯一构造点。

为什么必须有这个文件：
    `mcp` 的 FastMCP 只在 **`transport_security` 为 None 且自身 bind host 是
    127.0.0.1 / localhost / ::1** 时，才自动装上「只信 localhost」的白名单
    （见 mcp/server/fastmcp/server.py:191）。hub 是被 uvicorn 拉起来的，FastMCP 那个
    host 参数一直是默认值 127.0.0.1 ⇒ **白名单恒生效，且只认本机**。

2026-10-31 生产实测后果：
    agent 用 `http://mcp-hub:8099/mcp/qq_mail` 访问，Host 头是 `mcp-hub:8099`，
    不在 `["127.0.0.1:*", "localhost:*", "[::1]:*"]` 里 ⇒
    **421 Invalid Host header** ⇒ 模型手里一个 `mcp__*` 工具都没有
    ⇒ 前端只看到「连接器服务暂时不可用」。
    本地一律用 127.0.0.1 测，所以永远复现不出来 —— 这是又一个「本地过、生产不过」，
    而且它在 `/mcp/*` 的最外层，早于任何业务逻辑。

做法：**不关闭** DNS-rebinding 防护（保留浏览器侧防护能力），只把「受信 Host」补上：
    默认 localhost 三件套 + `mcp-hub`（compose 里的服务名），
    另可用 `AIOS_MCP_ALLOWED_HOSTS`（逗号分隔）追加，例如换 compose 服务名或上 ingress。

注意 host 匹配用的是「带端口的 pattern」：`mcp-hub` 会自动补成 `mcp-hub:*`；
已经是 `example.com:*` 这种形态的按原样透传。
"""

import os

from mcp.server.transport_security import TransportSecuritySettings

# 与 mcp SDK 的默认值保持一致（不弱化本机访问）
_BASE_PATTERNS = ("127.0.0.1:*", "localhost:*", "[::1]:*")

# compose 里的服务名。agent 的 manifest 里给的就是 http://mcp-hub:8099/...，
# 所以 Host 头必然是 mcp-hub:<port>。漏了它 = 生产必然 421。
_DEFAULT_PATTERNS = ("mcp-hub:*",)


def allowed_hosts() -> "list[str]":
    """受信 Host pattern 列表（带端口通配）。"""
    hosts = list(_BASE_PATTERNS) + list(_DEFAULT_PATTERNS)
    for item in os.environ.get("AIOS_MCP_ALLOWED_HOSTS", "").split(","):
        item = item.strip()
        if not item:
            continue
        # 裸主机名补端口通配；已带端口/通配的按原样用
        hosts.append(item if (":" in item or "*" in item) else item + ":*")
    return hosts


def security_settings() -> TransportSecuritySettings:
    """给每台 FastMCP 用的传输层安全设置（构造 FastMCP 时必须显式传入）。"""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts(),
    )
