# AIOS 长期记忆（索引）

> 仓库根 `D:\aios`。**≤3000 字节**（超出截断）⇒ 只放索引：铁律 `topics/iron-rules.md`，
> 明细 `topics/`，故事 `YYYY-MM-DD.md`。
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
| 已知缺口 / git / 进度 | `topics/known-gaps.md` · `topics/git-remote.md` · `docs/28 §6` |
| 连接器接入 MCP | `docs/59 §10` · hub :8099 · V97 三表 |
| 企微旧通道（**已删码**） | `docs/61`–`63` 仅设计参考，回滚只能 revert，见 `docs/64 §9.7` |
| **企微扫码** | `docs/64 §九` · `wecom_cli/` 5 工具 · `_verify_wecom_cli`(18)/`_verify_oa_qr_modal`(13) |
| **连接态同源** | `wecom/sync.py` → `connector_connection` 唯一源 · `_verify_connector_state_sync`(7) |
| **联网检索** | `agent/aios_ai/tools/web_search.py` · `docs/03 §6` · `_verify_agent_web_search`(20) |
| **H5 顶栏随滚动隐藏** | `docs/39 §11.3` · `#oaRoot.bar-hidden` · `_verify_h5_inputbar`(59) |

## 最常踩的五条（全文见 iron-rules）

- **7/12**：不放宽断言；「界面展示了 X」须回接口/库再取。
- **14/26**：后台起的服务会被回收；本机 shell 工具可能恒返空。
- **18/24**：看运行实例不看 mtime；Java 改动需重启，打包前先停。
- **34/30**：探活加 `--noproxy '*'`；agent 哨兵用 `agent/.venv`。

## 新增坑（见 pitfalls）

- 工具描述决定调不调；凭据会从**依赖日志**漏（`_RedactKeyFilter`）。
- `mcp_server_tool` 是 trust 快照 ⇒ 扩工具重跑 trust；下线必清快照（V104）。
- 哨兵要「快照→复位→跑→恢复」。**mock 掩盖真机差异**。
- H5 生效文件 `user-client/index.html`（`_oa_app.js` 未引用）。
- `SERVER__PORT` 被宽松绑定成 `server.port` ⇒ 起服务前 `unset`。
- **`#oaRoot` 自己带 `.oa`** ⇒ 别写 `.oa #oaRoot.xxx`（永不匹配）；透明描边仍占 1px。
- **`task.completed` 必带 `tool`**（否则 `name=null`）；**模型不知「今天」** ⇒ 每轮注入时间。
- **个人数据禁编**（只准原值/缺则说没有）；**调用原文不得外发**（救援≠收回，流式也要扣）。
