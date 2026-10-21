# AIOS 长期记忆（索引）

> 仓库根 = **`D:\aios`**（2026-10-18 从 `C:\Users\刘尖尖\WorkBuddy\aioa` 迁入，见 `docs/56` §八）。
> **本文件必须 ≤3000 字节**（超了注入时被静默截断）⇒ 只放索引；**铁律 1–36 全在 `topics/iron-rules.md`**，
> 明细在 `topics/`，故事在 `YYYY-MM-DD.md`。
> 迁移后验收判据：`_verify_oa_action_popup.py` 25/25 · `/aios/{h5,web}/` 200 · 登录 token 263 字符。

## 索引

| 主题 | 文件 |
|---|---|
| **铁律 1–36（引用时只报编号）** | **`topics/iron-rules.md`** |
| 功能域要点（H5 双形态 / OA 43 模块 / 表单三道闸 / HITL / 服务间令牌 / KB 降级 / 多租户） | `topics/features.md` |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（**已修坑清单勿回退**；含**禁删清单**） | `topics/pitfalls.md` |
| 跑套件·验收·收口（各哨兵项数与前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 知识库·检索·向量库 | `topics/vector-store-milvus.md` |
| Gitee/Gitea 联动 | `topics/repo-provider-gitea.md` |
| 模型管理（V61，默认 MiniMax） | `topics/model-config.md` |
| 生产部署（10.0.0.3） | `topics/production-deploy.md` + `deploy/生产部署手册.md` |
| 已知缺口 /「判定不改」 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（未开工项唯一权威）· `docs/19` |
| **连接器接入 MCP（已实装，commit 4453544）** | `docs/59` §10（冻结契约）· `mcp-hub/`（FastMCP :8099）· Java `connector/mcp/`（V97 三表 + 9 端点）· agent `ToolClient.list_mcp_tools()` · H5「插件-技能-连接器」MCP 区 · 五套哨兵 `_verify_mcp_hub / _verify_mcp_registry(12) / _verify_mcp_e2e(11) / _verify_agent_mcp_wiring(W1-W6) / _verify_oa_mcp_panel(12)`。**三个必记坑**：① JDK HttpClient 默认 h2c 升级 ⇒ uvicorn 吞 body（显式 HTTP_1_1）；② `updateById(null)` 被 NOT_NULL 跳过 ⇒ 清 `lastError` 必须 `LambdaUpdateWrapper.set(...)`；③ `delete` 逻辑删除 vs `uk_mcp_server` 不含 `deleted_at` ⇒ 软删行永久占位，注册前须 `selectIncludingDeleted` 清场。开关 **`AIOS_MCP_HUB` 默认 false**（关时工具表与改造前逐字节一致）。故事 `2026-10-20.md` 末节 |

## 最常踩的五条（全文见 iron-rules.md，勿只记摘要）

- **7 / 12**：绝不为转绿放宽断言；「界面展示了 X」的判据必须回接口或库再取一次（不得与被测对象同源）。
- **14 / 26**：`nohup &` / 后台任务起的服务会被回收；本机 PowerShell 工具可能恒返回空输出，杀进程别依赖它。
- **18 / 24**：判断「改动生效」看运行实例（jar 内嵌 class、`/openapi.json`），不看源码 mtime；**Java 改动必须重启**，且 `mvn package` 前必须先停进程（否则 `NoClassDefFoundError`）。
- **34**：本机 curl 走系统代理，一切探活加 `--noproxy '*'`。
- **30**：agent 侧 pytest/哨兵必须用 `agent/.venv/Scripts/python.exe`。

## 2026-10-20 新增收口

后端错误卫生 7 项：`scripts/_check_backend_error_hygiene.py`（缺密码/短密码被拒 · SSE 错误帧 200+`event: error` ·
协商失败归 406 · `@Async` 线程池 · 首页统计与未读数）。故事见 `2026-10-20.md`「后端报错清理」。

**插件-技能-连接器 + QQ邮箱/企业微信**（`docs/58`）：V96 四表 · 哨兵 `_verify_connectors.py`(17) 与
`_verify_oa_connector_ui.py`(17)。纪律：OAuth 回跳必须进 `PUBLIC_ENDPOINTS`；`.oa-up-hd` 弹层必须并列类名。

## 2026-10-21 QQ 邮箱 MCP 发信 E2E 首次全绿

三个坑（详见 `2026-10-21.md`）：① tools/执行节点各自建 ToolClient ⇒ MCP 工具映射必须类级按 token 缓存
（`ToolClient._MCP_TOOLS_BY_TOKEN`，每次 list 先作废本 token 条目）；② QQ SMTP 250 应答多行
（`250-host` 续行），`SmtpClient.expect` 已统一 RFC 5321 循环解析；③ langchain-mcp-adapters 丢
isError ⇒ 客户端按 "Error executing tool" 前缀判失败。发信判据 = DB `connector_mail_draft.status`
+ IMAP 收件箱，**不信模型文案**（MiniMax 会零工具调用谎报已发送）。
