# 64 · 用 wecom-cli（wecom-unified skill）接入企业微信：可行性与旧代码处置计划

> 状态：**计划（未执行）**。本文只回答三件事：能不能做、怎么做、已有代码怎么处置。
> 决策依据全部来自 2026-10-30 对 CLI 1.3.4 的实测（命令面、隔离性、权限语义），不是文档推测。
> 相关：`docs/61`（双模式）、`docs/62`（连接器体系）、`docs/63`（按用户授权方案）。

## 一、结论摘要

1. **能做，而且能绕开备案域名** —— `wecom-cli` 的鉴权模型是「智能机器人 + 真人扫码」，
   无需可信域名/可信 IP，这条正好解决 `docs/63 §9.5` 那个唯一外部阻塞。
2. **但有一个必须先验证的前提（P0 Spike）**：一份 `credentials.enc` 里同时装着
   「机器人身份」和**一个**「授权真人身份」（`identity whoami` 实测只返回一个真人）。
   若「一个 Bot 只能挂一个真人」，多租户就要每用户一个 Bot —— 那就不划算，应退回 MCP 自建应用路线。
   ⇒ **先花半天做这个验证，再决定是否动工**（见 §五）。
3. **旧代码不能整体废弃**。可废的只有「A 模式 snsapi_privateinfo 自建应用链路」这一条；
   多租户控制面、manifest 闸门、连接态同源、群机器人 webhook **仍然必需**，
   因为 CLI 没有 tenantId 概念、没有按用户裁剪、也没有 webhook 群推送。
4. **skill 与 CLI 存在命令漂移**（实测）：skill 写 `wecom-cli contact search`，
   CLI 1.3.4 实际是 `contact users search`，且 CLI 自己回「该接口不存在……请更新到最新 skill」。
   ⇒ 接入时 **以 `--schema` / `--doc` 为唯一权威**，不照 skill 文本拼命令。

## 二、实测事实（决定架构的六条）

| # | 事实 | 证据 | 对架构的影响 |
|---|---|---|---|
| F1 | CLI 版本 1.3.4，满足 skill 要求的 ≥1.2.1 | `wecom-cli --version` | 可直接用 |
| F2 | 配置目录决定身份：空目录 `unauthorized`，已有目录 `authorized` | `WECOM_CLI_CONFIG_DIR=$(mktemp -d) wecom-cli auth show --status` | **多用户隔离靠「每人一个 config dir」** |
| F3 | 授权可被程序驱动：`auth init --noninteractive --no-browser --output-qrcode <png>` | `auth init --help` | 可做成 H5 弹层里的二维码 + 轮询 |
| F4 | 身份需两段：`identity whoami` 同时给「机器人名/ID」与「授权真人名/ID」 | 实测输出 | 一对机器人 = 一个授权真人（见 §五 前提） |
| F5 | 权限语义：**读取**真人数据可以；**写入**只有 doc/sheet/smartsheet/smartpage 四类允许跨身份，其余品类只能写机器人创建的数据 | `identity whoami` 的 `extra_identity_context`；`todo --help` 自称「机器人视角」 | 「替用户发消息/建待办」的可行性需逐域实测，不能想当然 |
| F6 | 输出天然结构化：子命令支持 `--json <body>`、`--schema`、`--doc`、`--dry-run`、`-o <file>` | `message send --help` | 解析成本低；`--dry-run` 让哨兵可无副作用验证 |

**额外发现（有用且我们完全没有）**：`wecom-cli chat messages list` 可按时间范围拉取会话消息 ⇒
**入站消息可读**。我们现有实现（自建应用）没有接收能力，之前只能「发」。

## 三、目标架构

原则：**控制面不动，只替换数据面**。Java 仍是身份与状态权威，hub 仍是「给模型暴露工具」的地方，
CLI 只作为「具体怎么和企微说话」的执行器。

```
H5 连接器面板
   │ ①点「连接企业微信」
   ▼
Java 控制面（保留）  ConnectorController / ConnectorConnectionService
   │ ②转发到 hub（服务间令牌 svc=server，已有机制）
   ▼
mcp-hub :8099（保留）
   ├─ wecom_cli/ 新执行层
   │    ├─ 解析用户 → 取该用户 config dir：data/wecom-cli/<tenantId>/<userId>/
   │    ├─ 起子进程 auth init --noninteractive --no-browser --output-qrcode <dir>/qr.png
   │    ├─ 返回二维码 PNG（Base64）与轮询令牌
   │    └─ 轮询 auth show --status → authorized 后调 identity whoami 取姓名
   ├─ 状态回写（复用同步通道）POST /internal/v1/connectors/wecom_cli/connection
   └─ MCP 工具层：把 CLI 子命令包成 mcp__wecom_cli__* 工具（按域分批）
            ▼
        wecom-cli 子进程（每用户独立 config dir）
```

关键设计决策（每条都指向一个已知坑）：

| 决策 | 取值 | 理由 |
|---|---|---|
| 谁跑 CLI | **hub**，不是 agent 也不是 Java | hub 已有 per-user 身份解析（`identity.py`）、模式闸门（`gate.py`）、审计；agent 只负责把工具给模型，不该碰凭据 |
| 配置目录布局 | `data/wecom-cli/<tenantId>/<userId>/`，目录 0700 | F2 证明隔离按目录；tenantId 入路径是防止「换租户复用同一份凭据」 |
| 授权入口 | 后端代起 `auth init`，前端轮询 | F3；这样 H5 不需要用户碰命令行 |
| 身份落库 | 只落「姓名」做 `accountLabel`，**不落 userid** | skill 明文规定 ID 不许外露；且我们 UI 也不需要 |
| 连接态判定 | `auth show --status` 为 `authorized` 且 `whoami` 能取到姓名 | 单看 status 不够：目录里可能残留上一个人的过期凭据 |
| 工具命名 | 新连接器码 `wecom_cli`，工具名 `mcp__wecom_cli__*` | 与旧 `wechat_work` 并存一段时间，便于回滚；收口后再决定是否合并 |
| 命令来源 | 一律 `--schema` 现取，模板不硬编码 | F6 + 命令漂移（`contact users search` 事件） |
| 反注入 | 保留 CLI 自带的 `security_notice`，工具结果不整段回灌给模型 | CLI 已内置「外部内容不可信」提示，我们的 hub 目前没有等价物 |

## 四、分阶段计划

### P0 · Spike（0.5 天，**先做，决定要不要继续**）

只验一件事：**一个 Bot 能否承载多个真人授权者**。

做法：用两个空 config dir，`auth init --manual` 输入**同一个** Bot ID/Secret，分别扫两个不同同事的码，
看第二个能否成功、两次 `whoami` 是否各自返回对应的人。

| 结果 | 结论 | 后续 |
|---|---|---|
| 两个都成功、各自返回对应真人 | 一 Bot 多用户成立 | 走 P1，多租户可行 |
| 第二个失败/覆盖第一个 | 一 Bot 一用户 | **停**：每用户一个 Bot 不可维护，退回 `docs/63` 的 MCP 自建应用路线，本次不动代码 |

附带验（同批做完，都是只读或 `--dry-run`）：
- `mail send --dry-run` 的发件人身份是机器人还是真人；
- `todo create --dry-run` 是否能指定真人参与人；
- `message aibot send` 能否发给「非最近会话」的同事（决定是否能替我们现有的 `send_text_message`）。

### P1 · 打通最小闭环（2–3 天）

范围只做「连接 + 一个工具」，把架构钉死：连接态 + 扫码授权 + 一个域（建议**消息**，与我们现有能力可比）。

交付物：
1. `mcp-hub/mcp_hub/wecom_cli/`：`profiles.py`（config dir 管理）、`runner.py`（子进程执行 + 超时 + 脱敏）、
   `auth.py`（init/status/whoami）、`catalog.py`（工具目录）、`gate.py`（租户内按连接态裁剪）。
2. 连接器注册：`connector_def` 新增 `wecom_cli`（auth_mode=`CLI_QR`），V10x 迁移。
3. 授权接口：`POST /api/v1/connectors/wecom_cli/connect/qr`（返回 PNG+token）、
   `GET /api/v1/connectors/wecom_cli/connect/status`（轮询）。
4. 状态回写：复用 `sync.py` 同一内部通道（`/internal/v1/connectors/{code}/connection`）。
5. H5 弹层：显示二维码 PNG + 「已扫码」轮询；授权成功后 chip 变「已连接」。

验收判据（必须回第二源，不能只看接口自述）：
- 空目录发起 → 拿到 PNG；扫码后同一目录 `auth show --status` 变 `authorized`；
- Java `connector_connection` 出现 CONNECTED 行；`/api/v1/mcp/manifest` 含 `wecom_cli`；
- 断开后两者同时消失；
- hub 日志无 `credentials.enc`/Bot Secret 明文（沿用 `_RedactKeyFilter` 的思路）。

### P2 · 扩域（按需，每个域 1–2 天）

顺序按业务价值：消息 → 日程 → 会议 → 待办 → 文档/表格 → 邮件 → 微盘 → 媒体。

每个域的固定动作：读 `--schema` → 包成 1–3 个工具 → 写进 `catalog.py` + `_PARAMS`（**启动自检会拦不一致**）
→ 补哨兵 → 重跑 `trust` 刷新 `mcp_server_tool` 快照。

### P3 · 收口（0.5 天）

- 旧 A 模式链路下线（详见 §五 废弃清单）；
- 决定 `wechat_work` 与 `wecom_cli` 是否合并成一个连接器；
- docs/61–63 增「已被 CLI 方案取代」的标注，避免后来人按旧文档走弯路。

## 五、旧代码处置表

判据只有一条：**这段代码解决的是「和企微说话」还是「管住多用户和多租户」**。前者可换，后者不能删。

### 5.1 可以废弃（条件：P0 Spike 通过 + P1 验收通过）

| 模块 | 现在做什么 | 为什么可废 | 处置 |
|---|---|---|---|
| `mcp-hub/mcp_hub/wecom/oauth.py` | 自建应用 access_token 缓存 | CLI 自己管 token，不暴露也不再需要 | 删 |
| `wecom_api.py` 的 `exchange_code` / `get_user_detail` / `get_member` | A 模式换身份、换敏感字段 | 扫码授权不再走 `snsapi_privateinfo` | 删（`send_text`/`search_contact` 若改为 CLI 后端则一并删） |
| `wecom/admin_api.py` 的 `/oauth/authorize`、`/oauth/callback` | state + 回跳 + 写连接 | 改为扫码轮询 | 删 |
| `wecom/server.py` 的 A 模式 `_connect_a` / `_wait_connected` | 等回调落库 | 同上 | 删 |
| Java `WeComOAuthService`（含 state 一次性、开放重定向防护） | 服务端 OAuth | 同上 | 归档（保留 git 历史，不再调用） |
| 表 `connector_oauth_state`（V96 建） | state 一次性校验 | 扫码模式无 state | 保留表不删（历史数据），停止写入 |
| `docs/63 §3.1/§3.2` 的 UA 分流、`snsapi_privateinfo` 说明 | 方案设计 | 已不适用 | 加「已被 `docs/64` 取代」标注 |

### 5.2 必须保留（CLI 完全没有对应物）

| 模块 | 承担什么 | 为什么 CLI 替不了 |
|---|---|---|
| `wecom/group.py` + `group_server.py`（2 工具） | webhook 群机器人推送 | CLI 只能发「授权人 / 机器人最近会话」，**发不了指定群**；而这条通道零授权零域名，是唯一不依赖任何人的通道 |
| `wecom/store.py` / `crypto.py` / `models.py` | 多租户连接态 + 加密 | CLI 凭据在文件系统里，没有 tenant 维度 |
| `wecom/identity.py` | 从请求解析 tenantId/userId | CLI 无身份概念 |
| `wecom/gate.py` + `catalog.py` 的 modes | 按用户/模式裁剪工具 | CLI 只要拿到 Bash 就能调全部域 |
| `wecom/sync.py` + `InternalConnectorController` | hub → Java 状态同源 | 无对应；且 P1 的授权结果也要走它 |
| Java `ConnectorCatalogService` / `ConnectorConnectionService` | 目录 + 连接态唯一真相源 | 无对应 |
| Java `ConnectorCredentialGateway` | 控制面→数据面凭据下发 | 无对应（CLI 方案里改为「下发配置目录」） |
| V96/V97/V99/V101 迁移、`mcp_server_tool` 快照 | 表结构 + 工具快照 | 无对应 |
| `user-client` 连接器面板、管理端 `ConnectorConfigView` | 授权 UI | 改造（加二维码弹层），不重写 |
| 11 套 `_verify_*` 哨兵 | 回归面 | 全部保留，其中 4 套需改断言口径 |

### 5.3 需要改造（保留骨架，换后端）

| 模块 | 改造点 |
|---|---|
| `wecom/server.py` 的 `send_text_message` / `contact_search` / `get_my_profile` / `check_connection` | 执行体换成 CLI 调用；越权闸门（`confirmed`）与 `isSelf` 语义保留 —— 这是我们的产品语义，不是 CLI 的 |
| `wecom/mail.py` + 6 个 `mail_*` | 若 P0 实测 `mail send` 能替真人发信 ⇒ 后端换 CLI、`mail.py` 废弃；否则**保留 B 模式 IMAP/SMTP** |
| Java `ConnectorMailDraft`（幂等草稿） | CLI **没有草稿能力**（skill 明说）⇒ 保留，仍是我们的差异点 |
| `ConnectorProperties.wechatWork`（corpId/agentId/corpSecret） | 改为 Bot ID/Secret；语义与用途都变，需改注释与校验 |
| `_verify_wecom_dual_mode_p0.py`（24 项） | A/B 双模式断言整体改写为 CLI 模式的等价断言；S17（DB 无明文）改为「目录无明文 + 日志无明文」 |
| `docs/61` · `docs/62 §5` · `docs/63 §9` | 标注取代关系，避免后人按旧路径排查 |

## 六、废弃执行顺序（不能倒着来）

1. P0 Spike 通过 → 2. P1 验收通过（新链路可授权、可回写、可裁剪）→ 3. 切默认入口（H5 只显示新连接器）
→ 4. 观察一个迭代 → 5. 才删 §5.1 的代码。

**任何情况下都不要在 P1 验收前删 A 模式代码** —— 它现在是唯一能证明「按用户授权」语义还能跑通的实现，
先删等于把回滚路径也删了。

## 七、风险与未决问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| 一 Bot 只能一用户（P0 未定） | 多租户不可行 | P0 先验；不通过就停，退回 MCP 路线 |
| 凭据在文件系统（`credentials.enc` + 同目录 `.encryption_key`） | 多租户弱隔离，泄露=可冒充 | 目录 0700、放在独立卷、备份加密；hub 不提供任何「读凭据」工具 |
| CLI 是子进程 | 超时/僵尸进程/并发写同一目录 | 每用户一把文件锁；执行超时 30s；`--output` 落临时文件读后即删 |
| 写入权限受「机器人创建/拥有」限制（F5） | 「替用户改他的待办/发他的邮件」可能不成立 | 每个域接入前用 `--dry-run` 与一次真实验证确认，不确定就只做只读 |
| skill 文本与 CLI 漂移 | 照 skill 拼命令会失败 | 一律 `--schema` 现取；把「命令来源必须来自 schema」写进 hub 代码注释与哨兵 |
| 命令行的 ID 外露约束 | 可能把 userid 带进模型上下文 | 工具结果统一脱敏：ID 字段改内部句柄，只回姓名/标题 |

## 八、与既有文档的关系

- `docs/63`（按用户授权方案）：**仍然成立的是「三层凭据模型」「manifest 闸门」「多用户隔离 5 必做」**；
  被取代的是「A 模式只能靠备案域名」与「`snsapi_privateinfo` 具体接口」。
- 本文不替代 `docs/62` 的连接器体系设计，只是在它下面新增一个 `QR` 类型的连接器。

## 九、实施记录（2026-10-30：连接器入口 + 扫码绑定 + 数字人读数 已打通）

本节把上面的「计划」升级为「已实装」，并记下实施时发现、计划阶段没料到的四件事。
判据一律回第二源（磁盘 / 库 / 真实 MCP 调用），不看接口自述。

### 9.1 落地清单

| 层 | 文件 | 作用 |
|---|---|---|
| hub 数据面 | `mcp-hub/mcp_hub/wecom_cli/{__init__,profiles,runner,auth,catalog,identity,server,admin_api}.py` | 按目录隔离身份；5 个只读工具；`/api/v1/wecom_cli/{status,qr,bind,disconnect}` |
| hub 路由 | `mcp_hub/app.py` | `/api/v1/wecom_cli` 必须**排在** `/api/v1/wecom` 之前（前缀包含关系） |
| hub 注册 | `connectors/manifest.py`（新增 `AUTH_QR`）、`connectors/registry.py` | 注册 `wecom_cli` manifest，`server_factory` 指向原生 FastMCP |
| Java 目录 | `V102__wecom_cli_connector.sql` | `connector_def`（`auth_mode='QR'`, `config_keys='[]'`）+ `mcp_server`（**trusted=0**） |
| Java 网关 | `connector/service/WeComCliGateway.java` | `/api/v1/wecom_cli/**` 专用；契约是 `{code,message,data}`，**不能**复用凭据网关 |
| Java 控制面 | `connector/controller/ConnectorController.java` | `start` 对 QR 回 `mode=QR`；新增 `POST /{code}/qr`、`GET /{code}/qr-status`、`POST /{code}/qr-bind`；`disconnect` 对 QR 先删 hub 目录再改库 |
| Java 实体 | `connector/entity/ConnectorDef.java` | `AUTH_MODE_QR` |
| H5 | `user-client/index.html`（**不是** `_oa_app.js`） | `openConnector` 增 QR 分支 + `openQrModal`（出图 / 轮询 / bind）+ `.oa-qr-*` 样式 |
| 启动 | `start-all.sh` | `unset SERVER__PORT` + 显式 `--server.port=8080`；WECOM_MOCK=1 时给共享授权目录兜底 |
| 哨兵 | `scripts/_verify_wecom_cli.py`（15 项，在线）、`scripts/_verify_oa_qr_modal.py`（10 项，离线 UI） | 见 9.4 |

### 9.2 计划阶段没料到、实施时必须先修的四个坑

1. **`credentials.enc` 的层级**（最致命）。实测：CLI 的 `credentials.enc`、`.encryption_key`、`cache/`
   **直接**落在 `WECOM_CLI_CONFIG_DIR` 下，CLI 不会自己再套一层 `personal/`。
   证据：变量指向空目录 → `unauthorized` 且目录里什么都不生成；指向 WorkBuddy 自己的
   `.../wecom-cli/personal` → `authorized`；指向它的上一级 → 又变 `unauthorized`。
   ⇒ 判据若写成 `<base>/personal/credentials.enc` 而 CLI 目录是 `<base>`，现象就是
   **「扫码成功了，但系统一直说未绑定」**。落地方案：`profiles.cli_dir(base)` 单点决定，
   并兼容「调用方直接给了 CLI 目录」（共享 profile 就是这种），见 9.1 的哨兵 S2。
2. **ASGI helper 忘 `await`**。`def _ok(...): return _send_json(...)` 这种写法返回的是协程，
   `return _ok(...)` 既不 await 也没人消费 ⇒ uvicorn 报
   `ASGI callable returned without starting response` + 客户端 500，**但业务逻辑已经跑完了**
   （实测库里已 CONNECTED、接口却回 500，极易误判成写库失败）。helper 必须是 `async def` 且调用处 `await`。
3. **`SERVER__PORT` 劫持 Spring 端口**。Spring 宽松绑定把环境变量 `SERVER__PORT`（双下划线→点）
   认成 `server.port`。从工作台/IDE 终端启动时该变量常被注入成临时端口（实测 61302），
   而那个端口已被宿主进程占用 ⇒ 后端启动失败，报的却是与 8080 毫无关系的
   「Port 61302 was already in use」。`start-all.sh` 里已 `unset` 并显式 `--server.port=8080`。
4. **`_oa_app.js` 不是生效文件**。`user-client/index.html`（Oct 28，673KB）才是自包含产物，
   `_oa_app.js`（Oct 21，164KB）没有被打包引用。改错文件的症状是「改了但页面没变」。
   **改 H5 一律改 `index.html`**。

### 9.3 产品流程（对应用户口径：必须先在连接器里选企业微信并授权）

```
连接器面板「企业微信（扫码）」→ 连接
  → POST /v1/connectors/wecom_cli/connect/start   → {mode:"QR"}
  → POST /v1/connectors/wecom_cli/qr              → {qr:"data:image/png;base64,…"}（阻塞 ≤20s 等出图）
  → 手机企业微信扫码
  → GET  /v1/connectors/wecom_cli/qr-status       → {authorized:true, accountLabel}（前端每 2s 轮询）
  → POST /v1/connectors/wecom_cli/qr-bind         → Java 自己写 CONNECTED（不依赖服务令牌回写）
  → 下一轮 /api/v1/mcp/manifest 放行 → 模型手里出现 mcp__wecom_cli__*
```

**连接态由 Java 自己落库**，不靠 hub 用服务令牌回写：hub 已确认 `bound=true`（读的是 CLI 真实授权
状态），Java 据此写 CONNECTED 是可信的；反过来依赖 `AIOS_SERVICE_TOKEN_SECRET` 会在
「开发环境没配密钥」时出现「扫码成功、界面未连接、数字人没工具」——用户完全无法自查。

### 9.4 验收数字（2026-10-30 全部实跑）

| 套件 | 结果 |
|---|---|
| `_verify_wecom_cli.py`（新） | **15/15** |
| `_verify_oa_qr_modal.py`（新） | **10/10** |
| `_verify_connectors.py` | 19/19（C1 计数 3→4） |
| `_verify_mcp_registry.py` | 13/13（M1 期望表加 `wecom_cli:5`） |
| `_verify_connector_state_sync.py` | 7/7 |
| `_verify_agent_mcp_wiring.py` | 6/6 |
| `_verify_mcp_hub.py` / `_verify_oa_connector_ui.py` / `_verify_oa_mcp_panel.py` | 全通过 / 17/17 / 19/19 |

真实对话（MiniMax-Text-01，zhangsan 账号，绑定后）：

```
问：我绑定的企业微信是哪个账号？我叫什么名字？
  [tool.call] mcp__wecom_cli__whoami {}
  [tool.result] {"bound": true, "userName": "刘洋", "botName": "刘洋的机器人"}
答：我绑定的企业微信账号是刘洋，机器人名称是"刘洋的机器人"。

问：用企业微信通讯录查一下「刘洋」在哪个部门？
  [tool.call] mcp__wecom_cli__contact_search {"keywords":"刘洋"}
答：刘洋在成都易构部门。
```

### 9.5 旧连接器下线（V103，2026-10-30）

> ⚠️ **本节记录的「只下线、不删码」已被 §9.7 取代**：2026-10-30 当天下午按用户要求把两个旧通道的
> 代码**物理删除**了。本节保留作为历史决策记录（为什么当初选择只下线），现状请看 §9.7。

按产品决定：**「协作与办公」里只保留「企业微信（扫码）」一个企微入口**，
`wechat_work`（自建应用 OAuth2）与 `wecom_group`（群机器人 Webhook）已下线。

`V103__retire_legacy_wecom_connectors.sql` 做三件事：

| 动作 | 效果 |
|---|---|
| `connector_def.status='DISABLED'` | 用户端目录 `list()` 只查 ACTIVE ⇒ 两张卡不再出现 |
| `mcp_server.trusted=0, status='UNKNOWN'` | `/api/v1/mcp/manifest` 只查 trusted=1 ⇒ 旧工具不再进模型上下文 |
| `connector_connection` 置 NEED_AUTH + 清凭据 | 避免「看不见却算已连接」的脏状态 |

**为什么是下线不是删行**：`mcp_server_tool`（工具快照）与 `connector_connection`（历史连接态）
都靠这两行存在；物理删除会让回滚变成「重新造数据」，也让审计断掉。真正的开关只有
`status` 与 `trusted` 两个，置位后对用户与模型都不可见，效果等同删除但可一键回滚：

```sql
UPDATE connector_def SET status='ACTIVE' WHERE code IN ('wechat_work','wecom_group');
-- 需要哪个就重新 trust 哪个刷新工具快照：
-- POST /api/v1/mcp/servers/{code}/trust
```

**代码没删**：`mcp-hub/mcp_hub/wecom/`（双模式）、`specs.py` 里的 `wecom_group`、
`WeComOAuthService`、`docs/61`–`docs/63` 全部保留。理由：A 模式是唯一能「替用户发消息」
的现成通道（B 模式自带真实邮箱身份），扫码通道目前只有只读工具；真机多用户验证若发现
CLI 侧写入受限，回滚成本 = 一条 SQL。

**连带调整的哨兵**（都不能靠删断言变绿）：

| 套件 | 调整 | 现结果 |
|---|---|---|
| `_verify_connectors.py` | C1 期望改为 `['qq_mail','wecom_cli']` 并加「已下线的不许出现」；C2 改验 wecom_cli 无应用配置也恒就绪；C9b 就绪度改读管理端 `configured`；C10b 第二源改读库 | 19/19 |
| `_verify_connector_tenant_config.py` | 前置临时把 wechat_work 置 ACTIVE 跑完复原（验的是「租户凭据中心」机制，机制还在） | 9/9 |
| `_verify_connector_state_sync.py` | 主体从 wechat_work 换成 wecom_cli（验的是同源机制，与主体无关） | 7/7 |
| `_verify_mcp_registry.py` | 新增 M1b：已下线的两行必须保留且 trusted=false | 14/14 |
| `_verify_wecom_dual_mode_p0.py` | 未改（验 hub 侧双模式，不读 connector_def.status） | 24/24 |
| `_verify_wecom_group.py` | 未改（读 hub 自己的清单，仍需 `--key` 前置） | 需 key |

真实界面复核（zhangsan 登录，`logs/proof/connectors_after_retire.png`）：
目录只有 2 张卡 —— QQ邮箱（未连接）、企业微信（扫码）（已连接 · 刘洋 · MCP 已启用）。

### 9.6 仍然未做 / 需注意

- **一 Bot 能否挂多真人（原 P0 Spike）仍未验**：本地只有一个真机授权，无法在单个 hub 上造第二个
  真实扫码。当前 dev 用 `AIOS_WECOM_CLI_SHARED_PROFILE` 让所有 AIOS 用户共用同一份授权
  （`start-all.sh` 仅在 `WECOM_MOCK=1` 时给默认值）。**生产必须清空该变量**，否则等于把一个人的
  企微数据串给所有账号。这条是本次唯一「逻辑上通了、物理上没验」的点。
- 只开放 5 个只读工具。写操作（发消息/建待办/发邮件）的权限边界（F5）未实测，故未开放。
- 旧通道已**物理删除**（不是下线），见 §9.7。A 模式（自建应用）原本是唯一「替用户发消息」的现成
  通道；删掉之后若确认 CLI 侧写入确实受限，要重新引入必须走 git revert，成本是「重新评审 + 重新
  部署」，不再是一条 SQL。

### 9.7 旧通道代码物理删除（2026-10-30，承接 9.5）

用户要求：「只保留最新的，之前的两个删掉」+「同时删掉没用的文件，包括之前写的代码」。
9.5 当时选择只停用不删码（理由是「回滚成本低」），本条把代码真的删掉。**删完不再有 A 模式**。

#### 9.7.1 删了什么

| 侧 | 文件 | 行数 | 说明 |
|---|---|---|---|
| hub | `mcp_hub/wecom/server.py` | 646 | `wechat_work` 原生 MCP 服务器（13 工具） |
| hub | `mcp_hub/wecom/wecom_api.py` | 307 | 企微开放接口客户端（token 缓存、通讯录、发消息） |
| hub | `mcp_hub/wecom/catalog.py` | 240 | 13 工具目录 + 单工具模式闸门元数据 |
| hub | `mcp_hub/wecom/mail.py` | 212 | B 模式 IMAP/SMTP 后端 |
| hub | `mcp_hub/wecom/admin_api.py` | 199 | `/api/v1/wecom/*` REST 面（含 OAuth 回跳） |
| hub | `mcp_hub/wecom/group_server.py` | 163 | `wecom_group` 群机器人 MCP 服务器（2 工具） |
| hub | `mcp_hub/wecom/graph.py` | 143 | LangGraph 双模式工作流（P0 骨架 + checkpoint） |
| hub | `mcp_hub/wecom/oauth.py` | 113 | snsapi_privateinfo 授权链 |
| hub | `mcp_hub/wecom/group.py` | 111 | 群机器人 webhook 发送 |
| hub | `mcp_hub/wecom/gate.py` | 49 | A/B 模式闸门 |
| Java | `connector/service/WeComOAuthService.java` | 388 | 自建应用 OAuth + access_token 缓存 + get_my_profile |
| Java | `connector/wecom/WeComMcpHandler.java` | 116 | `wechat_work` 的内置工具实现（MCP 桥） |
| Java | `connector/wecom/WeComApiClient.java` | 74 | 企微 API 客户端 |
| Java | `connector/config/ConnectorProperties.java` | 33 | `aios.connector.wechat-work.*` 平台级三件套 |
| 前端 | `user-client/index.html` 的 `openOauthModal` + `API.connectorStart` | ~45 | OAUTH2 整页跳转弹层 |
| 脚本 | `_verify_wecom_dual_mode_p0.py` / `_verify_wecom_group.py` | 24+7 项 | 主体已不存在 |
| 脚本 | `wecom_ip_check.py` / `wecom_webhook_send.py` | — | 一次性真机诊断/发信工具 |

合计约 **2900 行**（hub 2183 + Java 611 + 前端/脚本若干）。

**必须保留的五个模块**（不是「企微代码」，是所有连接器共用的底座）：

| 模块 | 为什么留 | 谁在用 |
|---|---|---|
| `wecom/crypto.py` | AES-256-GCM `enc:` 密文与掩码 | `store`、`connectors/vault` |
| `wecom/models.py`（已裁到只剩 `Identity`） | 调用方身份 | `identity`、`connectors/admin_api` |
| `wecom/store.py`（已裁到只剩 `db_path/is_mock/init/key`） | 库文件位置 + 主密钥（缺密钥 fail fast） | `app` lifespan、`connectors/vault` |
| `wecom/identity.py` | 把 Authorization 转发 `/api/v1/auth/me` 换身份 | `connectors/admin_api` |
| `wecom/sync.py` | 连接态回写 Java（真相源） | `wecom_cli/admin_api` |
| `connectors/vault.py` | 通用应用凭据保险库 | 未来任何「需要管理员配凭据」的连接器 |

包名仍叫 `wecom/` 只是为了不动 `WECOM_DB_PATH` / `data/wecom.db` / 既有备份口径。

#### 9.7.2 删除过程中暴露的两个真问题（都已修）

这两个都不是「删错了」，而是**原来就有、被删码掩盖住的漏洞**：新加的哨兵一跑就红。

1. **`connector_def` 停了但接口照旧可取**：`ConnectorCatalogService.requireDef()` 只按
   `tenant_id + code` 查，不看 `status`。于是 `GET /api/v1/connectors/wechat_work` 仍回
   200 + 一条没人维护的定义，`connect/start` 还会掉进「暂不支持网页授权」这种开发者才看得懂
   的分支。修法：`requireDef` 加 `status=ACTIVE` 过滤 ⇒ 已下线连接器一律「不存在」（HTTP 404）。
2. **MCP 工具快照没清**：`V103` 只把 `mcp_server.trusted` 关了，`mcp_server_tool` 里 13+2 行
   还在，于是 `GET /api/v1/mcp/servers/wechat_work/tools` 仍能查出 13 个工具，界面还会对着
   一台「代码已经删干净、探测必然失败」的服务器报「13 个工具」——**这比报错更危险**。
   修法：`V104__purge_retired_mcp_tool_snapshots.sql` 删掉这两台的工具快照（`mcp_server` 行
   按 V103 约定留痕），toolCount 自然归零。

#### 9.7.3 哨兵调整（一条断言都没放宽，只有换主体 / 加严）

| 套件 | 调整 | 现行结果 |
|---|---|---|
| `_verify_connectors.py` | 原 C9/C9b（按就绪度出 authUrl）、C10（伪造 state→302）验的是 OAuth 链路，主体没了 ⇒ 换成更硬的断言：C9a/C9b「已下线连接器详情与 start 必须 404 不存在」、C9c「wecom_cli start 只回 QR、无 authUrl」、C10a「回调匿名不可达 401」、C10b「带 token 仍 404」、C15 改 5 工具全只读、C15b「已下线服务器的 tools 必须为空」 | **25/25** |
| `_verify_connectors_registry.py` | 主体从 `provider=wecom` 换成运行期登记的 `provider=vault`（验的是同一套「按 provider 落库 + 掩码 + 保留旧值 + 清除」）；新增 S8 两个 vault 连接器互不覆盖；S13 库文件明文扫描移到清除**之前**并先用密钥解出真值（否则扫的是空库）；S11b 加「已下线 code 在注册表里 404」 | **15/15** |
| `_verify_connector_tenant_config.py` | **整体换主体**（文件同名）：现在存活连接器都不需要管理员配凭据 ⇒ 改验「无需配置的形态必须表现正确」：清单为空、单项视图明确拒绝、PUT 不静默成功且不落库、已下线的在管理端也 404 | **8/8** |
| `_verify_mcp_registry.py` | M1 期望表 retired 改 0；M1b 加「工具目录必须为空」；M13 只比存活服务器，并反向断言「hub 里不许再出现已下线 code」 | **14/14** |
| `_verify_mcp_hub.py` | 真实 MCP 客户端连的对象从 `/mcp/wechat_work`（13）换成 `/mcp/wecom_cli`（5），required 与 `wecom_cli/catalog.py` 逐字对齐 | 全通过 |
| `_verify_oa_connector_ui.py` | 打桩的第二张卡从 `wechat_work` 换成 `wecom_cli`（验的是 chip 文案 / configReady=false 按钮禁用这段渲染逻辑，与主体无关） | **17/17** |
| `_verify_wecom_dual_mode_p0.py` / `_verify_wecom_group.py` | **删除**（被测对象不存在，无法「换主体」：A/B 双模式与群机器人本身就是被删的能力） | — |

**覆盖损失（显式记账，别当成已验证）**：
- 原 24 项双模式验收（OAuth 回跳/state 一次性/13 工具/模式闸门/邮件闭环/`/health` 计数）
  与群机器人 7 项（真实 webhook 发送、空内容被拒）**随能力一起消失**。
- 「管理端保存应用凭据 → 运行时生效」端到端链路**当前没有活的被测主体**：hub 侧由
  `_verify_connectors_registry` 的 `provider=vault` 覆盖，Java→hub 透传要等下一个需要
  管理员配凭据的连接器接进来才能真验（届时把 T2/T3 扩回「保存→回查 hub→configReady 翻转」）。

#### 9.7.4 怎么恢复（如果将来真要 A 模式）

代码已不在工作树里，只能 `git revert` 对应提交（2026-10-30「删旧企微通道」那一个），然后：

```sql
UPDATE connector_def SET status='ACTIVE' WHERE code IN ('wechat_work','wecom_group');
-- 重新部署后端（V104 删掉的工具快照会在 trust 时从 hub 重新拉取）
-- POST /api/v1/mcp/servers/wechat_work/trust
```

⚠️ 恢复后要同步撤销 9.7.3 里那些「必须 404」的断言，否则哨兵会红 —— **这是设计如此**
（下线没删干净时有人盯着）。
