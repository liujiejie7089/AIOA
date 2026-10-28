# -*- coding: utf-8 -*-
"""企业微信双模式连接器（A：snsapi_privateinfo OAuth；B：企业邮箱客户端专用密码）。

挂载点：/mcp/wechat_work（原生 MCP 服务器，见 server.py）
REST 面：/api/v1/wecom/*（见 admin_api.py）
设计文档：docs/60__wecom-dual-mode-connector.md
"""

from . import admin_api, catalog, crypto, gate, graph, identity, mail, models, oauth, server, store, wecom_api  # noqa: F401
