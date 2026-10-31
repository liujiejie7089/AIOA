# AIOS 长期记忆（索引）

> 仓库根 `D:\aios`。**≤3000 字节**（超出静默截断）⇒ 只放索引；铁律 `topics/iron-rules.md`，
> 明细 `topics/`，故事 `YYYY-MM-DD.md`。

## 索引

| 主题 | 文件 |
|---|---|
| **铁律 1–36（引用只报编号）** | `topics/iron-rules.md` |
| 功能域要点（H5/OA/表单三道闸/HITL/多租户） | `topics/features.md` |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（**已修坑勿回退**；禁删清单） | `topics/pitfalls.md` |
| 跑套件·验收·收口（项数与前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 向量库 / Gitee / 模型 / 部署 | `topics/vector-store-milvus.md` · `repo-provider-gitea.md` · `model-config.md` · `production-deploy.md` |
| 缺口 / git / 进度 | `topics/known-gaps.md` · `topics/git-remote.md` · `docs/28 §6` |
| 连接器接入 MCP（已实装） | `docs/59 §10` · hub :8099 · V97 三表 |
| 企微扫码 + 连接态同源 | `docs/64 §九` · `wecom/sync.py` → `connector_connection` |
| **能力层扩展点 + 日程/会议** | `aios_ai/capabilities/` · `docs/65` · `PortalService` 6 端点 · `_e2e_portal…`(24) |

## 最常踩的五条（全文见 iron-rules）

- **7 / 12**：不为转绿放宽断言；「界面展示了 X」须回接口/库再取（不得与被测对象同源）。
- **14 / 26**：`nohup &` 起的服务会被回收；shell 工具可能恒返空。
- **18 / 24**：看运行实例不看 mtime；**Java 改动必须重启**，`mvn package` 前先停进程
  （否则 `NoClassDefFoundError`）。
- **34**：curl 走系统代理，探活加 `--noproxy '*'`。
- **30**：agent pytest/哨兵用 `agent/.venv/Scripts/python.exe`。

## 新增坑（全文见 pitfalls，引用只报编号）

- 工具描述决定调不调；凭据从**依赖日志**漏。`mcp_server_tool` 是 trust 快照 ⇒ 扩工具重跑
  trust、下线清快照（V104）。
- 哨兵要「快照→复位→跑→恢复」。**mock 掩盖真机差异**。H5 生效文件 `user-client/index.html`。
  `SERVER__PORT` 绑定成 `server.port` ⇒ 起前 `unset`。
- **`#oaRoot` 自己带 `.oa`** ⇒ 别写 `.oa #oaRoot.xxx`（永不匹配）。
- **`task.completed` 必带 `tool`**（否则 `name=null`）；**模型不知「今天」** ⇒ 每轮注入时间。
- **个人数据禁编**（只准原值/缺则说没有）；**调用原文不得外发**（流式也扣）。
- **29 / 30**：业务校验失败 **≠ HTTP 400** —— 本仓约定 **HTTP 200 + 信封 `code=400`**
  （只有 401/403/404 映射状态码）⇒ 断言查 `body.code`。Java 侧**禁用
  `IllegalArgumentException`**（落 500），用 `BizException.badRequest`。
- **31 / 32**：起后端要 `-Dspring.flyway.validate-on-migrate=false`；e2e 写死 uid 会把组织者
  算成受邀人（期望值按真实 uid 动态算）。
