# AIOS 长期记忆（索引）

> 仓库根 = **`D:\aios`**。**≤3000 字节**（超出注入即截断）⇒ 只放索引；铁律 1–36 在
> `topics/iron-rules.md`，明细在 `topics/`，故事在 `YYYY-MM-DD.md`。

## 索引

| 主题 | 文件 |
|---|---|
| 铁律 1–36（引用只报编号） | `topics/iron-rules.md` |
| 功能域要点（H5 双形态/OA/表单三道闸/HITL/多租户等） | `topics/features.md` |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（已修坑勿回退；禁删清单） | `topics/pitfalls.md` |
| 跑套件·验收·收口（哨兵项数与前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 知识库·检索·向量库 | `topics/vector-store-milvus.md` |
| Gitee/Gitea 联动 | `topics/repo-provider-gitea.md` |
| 模型管理（V61，默认 MiniMax） | `topics/model-config.md` |
| 生产部署（10.0.0.3） | `topics/production-deploy.md` + `deploy/生产部署手册.md` |
| 已知缺口 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（未开工项唯一权威） |
| 连接器接入 MCP（4453544） | `docs/59` §10 · `mcp-hub/` :8099 · Java V97 三表+9 端点 · agent `ToolClient.list_mcp_tools()` · 哨兵 `_verify_mcp_hub/_verify_mcp_registry(12)/_verify_mcp_e2e(11)/_verify_agent_mcp_wiring/_verify_oa_mcp_panel(12)`。三个坑（h2c 吞 body / updateById(null) / 软删占 uk）见 `topics/pitfalls.md`。`AIOS_MCP_HUB` 默认 false |
| **企微双模式连接器 P0（085a77f）** | `docs/61` · `mcp-hub/mcp_hub/wecom/` 原生 server（`/mcp/wechat_work` 不代理 Java）· A=snsapi_privateinfo（URL elicitation）· B=邮箱客户端专用密码（表单 elicitation）· 模式闸门 A/B/AB · SQLite 密文 · `WECOM_MOCK` 默认 0 · 哨兵 `_verify_wecom_dual_mode_p0.py`(20) · 开发密钥在 start-all.sh |

## 最常踩的五条（全文见 iron-rules.md）

- **7/12**：绝不为转绿放宽断言；「界面展示了 X」必须回接口或库再取一次（不得同源）。
- **14/26**：后台任务起的服务会被回收；本机 PowerShell 工具可能恒返空输出。
- **18/24**：改动生效看运行实例（jar 内嵌 class、`/openapi.json`）；Java 改动必须重启，打包前先停进程。
- **34**：本机 curl 走系统代理，探活加 `--noproxy '*'`。
- **30**：agent 侧 pytest/哨兵必须用 `agent/.venv/Scripts/python.exe`。

## 新增坑（2026-10-28，企微双模式）

- `"AB".split("+")` = `["AB"]` ⇒ 模式解析**只能走 `store.split_modes`**。
- `Connection` 默认 mode 必须空串：曾默认 AB ⇒ 只绑 A 却显示 AB，`connect(B)` 被幂等短路。
- FastMCP 可选参数 `default=None` 会被判 required ⇒ 可选参数给 `""` 等真默认值。
- elicitation：URL 模式用 `session.elicit_url`（`ctx.elicit` 只有表单变体）；Python 客户端传 `elicitation_callback` 即声明 form+url 双能力。
