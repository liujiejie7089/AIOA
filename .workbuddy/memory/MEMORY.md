# AIOS 长期记忆（索引）

> 仓库根 = **`D:\aios`**。**≤3000 字节**（超出注入即截断）⇒ 只放索引；铁律 1–36 在
> `topics/iron-rules.md`，明细在 `topics/`，故事在 `YYYY-MM-DD.md`。

## 索引

| 主题 | 文件 |
|---|---|
| 铁律 1–36 | `topics/iron-rules.md` |
| 功能域要点（H5/OA/表单三道闸/HITL/多租户） | `topics/features.md` |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（已修坑勿回退；禁删清单） | `topics/pitfalls.md` |
| 跑套件·验收·收口（项数与前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 知识库·检索·向量库 | `topics/vector-store-milvus.md` |
| Gitee/Gitea 联动 | `topics/repo-provider-gitea.md` |
| 模型管理（V61，默认 MiniMax） | `topics/model-config.md` |
| 生产部署（10.0.0.3） | `topics/production-deploy.md` |
| 已知缺口 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（唯一权威） |
| 连接器接入 MCP | `docs/59` §10 · hub :8099 · V97 三表 · `AIOS_MCP_HUB` 默认 false |
| 企微双模式 | `docs/61` · `wecom/` 原生 server · A=privateinfo · B=邮箱密码 · 模式闸门 · `WECOM_MOCK` 默认 0 |
| 群机器人 wecom_group | `docs/62` §5.7 · 2 工具 · V101 · `usableForAgent()` · `_verify_wecom_group.py`(7) |
| 企微按用户授权 | `docs/63`（§9.2.1 已实施）· **无用户级 token**（应用 token + userid/user_ticket）· P0 已修 `ee9ad02` |
| **连接态同源** | `wecom/sync.py` → `/internal/v1/connectors/{code}/connection` → `connector_connection` = 唯一真相源 · `synced` 三态 True/False/None(跳过) · 目录 status 只信库 · `_verify_connector_state_sync.py`(7) |

## 最常踩的五条（全文见 iron-rules.md）

- **7/12**：绝不为转绿放宽断言；「界面展示了 X」必须回接口或库再取一次（不得同源）。
- **14/26**：后台任务起的服务会被回收；本机 PowerShell 工具可能恒返空输出。
- **18/24**：改动生效看运行实例（jar 内嵌 class、`/openapi.json`）；Java 改动必须重启，打包前先停进程。
- **34**：本机 curl 走系统代理，探活加 `--noproxy '*'`。
- **30**：agent 侧 pytest/哨兵必须用 `agent/.venv/Scripts/python.exe`。

## 新增坑（明细见 `topics/pitfalls.md` 末节）

- 工具描述决定模型调不调；凭据会从**依赖的日志**漏（httpx 打整条 `?key=…`，已装 `_RedactKeyFilter`）。
- `mcp_server_tool` 是 trust 时的快照 ⇒ hub 扩工具后重跑 trust。直调 `/runs` 必须带 `user_token`。
- 哨兵要「快照→复位→跑→恢复」。**mock 会掩盖真机字段差异**（P0-1 就这么漏的）。
- 「跳过」≠「失败」：状态同步三态，压成 bool 会把 dev 正常跳过报成故障；日志断言要成对（无明文 **且** 有脱敏标记）。
