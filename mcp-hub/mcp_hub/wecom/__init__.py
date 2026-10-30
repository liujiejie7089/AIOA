# -*- coding: utf-8 -*-
"""连接器共享底座（加密 / 身份 / 持久化 / 连接态回报）。

<b>本包已不是「企业微信双模式连接器」</b>。2026-10-30 起旧的两个企微通道
（{@code wechat_work} 自建应用 OAuth + {@code wecom_group} 群机器人）连同其
原生 MCP 服务器、REST 面、目录、邮件后端一并物理删除（见 docs/64 §9.7）。
企业微信统一改走 {@code wecom_cli}（官方 CLI 扫码，见 docs/64）。

这里保留的四个模块是**与具体连接器无关**的公共设施，被仍存活的模块依赖：

| 模块 | 作用 | 谁在用 |
|---|---|---|
| {@code crypto.py}    | AES-256-GCM `enc:` 密文与掩码            | `store`、`connectors/vault` |
| {@code models.py}    | 调用方身份 {@code Identity}              | `identity`、`connectors/admin_api` |
| {@code store.py}     | 单文件 SQLite 路径与主密钥（fail fast）   | `app` lifespan、`connectors/vault` |
| {@code identity.py}  | 转发 Authorization 到 Java 换身份        | `connectors/admin_api`、旧 oauth/server（已删） |
| {@code sync.py}      | 连接态回写 Java（真相源）                | `wecom_cli/admin_api` |

包名沿用 `wecom` 只是为了避免动 `WECOM_DB_PATH` / `data/wecom.db` 与既有备份口径；
新增连接器请直接用 `connectors/vault.py`（同一 SQLite 文件、同一把密钥）。
"""

from . import crypto, identity, models, store, sync  # noqa: F401
