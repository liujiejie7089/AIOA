# 把 Gitee 换成 Gitea：改造清单与工作量评估

> 编制：2026-09-18 · 依据：本仓库代码实测盘点（非估算）+ Gitea 官方文档核对
> 范围：`server/aioa-gitee`（42 文件 / 6683 行）+ 前端 7 文件 / 2691 行 + 9 张表 + 5 个 E2E 套件

---

## 0. 一句话结论

**技术上完全可行，而且比想象中便宜** —— 因为 Gitea 的 API 是**刻意对齐 GitHub** 的，
而 Gitee 的 V5 API 骨架也是 GitHub 风格，**~25 个端点里有 ~19 个是同形的**。
真正要动的只有 **5 个硬分歧点**（下表），其中 2 个（Webhook 签名、仓库命名）是**会静默出错**的那类，必须实机验证。

| 路线 | 工作量（1 名熟悉本仓库的后端，含测试与文档） | 适用 |
|---|---|---|
| **A. 整体替换**（换掉 Gitee，不再支持） | **约 14–20 人天** | 确定只走私有化 Gitea |
| **B. 抽象适配层**（Gitee/Gitea 并存可切换） | **约 19–26 人天** | 推荐 —— 只比 A 贵 ~30%，但换来「地级市可选私有化/可选 SaaS」的能力 |
| **MVP 先落地**（只做令牌 + 建仓 + 文件读写） | **约 5–8 人天** | 想快速看到东西、Webhook/OAuth 后置 |

**推荐路线 B + 先交 MVP。** 理由见 §5。

---

## 1. 现状盘点（实测数字，不是估的）

| 维度 | 实测 |
|---|---|
| 后端模块 | `server/aioa-gitee`，**42 个 java 文件 / 6683 行** |
| 出网客户端 | `GiteeClient` **592 行**，**~25 个 API 方法**，**无接口抽象**（具体类被 7 个服务直接注入） |
| 注入点 | `GiteeAccountService` / `GiteeContentService` / `GiteeMemberService` / `GiteeMemberTaskHandler` / `GiteeRepoTaskHandler` / `GiteeTenantConfigService` / `GiteeTenantInitService` / `GiteeTokenService`（共 8 处） |
| 跨模块耦合 | **极小**：`aioa-security`（权限码 3 个）、`aioa-resource`（4 个通知文件里只是文案/通道名）。`aioa-chat` / `aioa-org` / `aioa-bridge` **零引用** |
| 权限码 | `project:view` / `project:manage` / **`gitee:bind`** —— **只有 1 个带提供商字样** |
| 数据库 | 9 张 `gitee_*` 表；5 个 Flyway 迁移（V48/V49/V50/V51/V53） |
| 前端 | `web/apps/shell` 7 文件 / **2691 行**（`api/gitee.ts` 643 + 两个视图 2048）；H5 **0 引用** |
| 配置 | `application.yml` 里 **15 个** `AIOA_GITEE_*` 环境变量键 |
| 测试 | `gitee_stub.py` 假桩 + 5 个套件：`e2e_v48_gitee`(116) · `e2e_v50_tenant_org`(54) · `e2e_v51_gitee_init`(50) · `SMOKE_v48`(32) · `verify_v51_repo_urls`(23) |

**关键有利条件**：`docs/30` 已有完整的接口契约文档（225 行）；`gitee_stub.py` 已经是「可替换后端」的雏形
⇒ **抽象成本已经被部分验证过**，不是从零猜。

---

## 2. 兼容性三分类

### ✅ 同形，几乎不用改（~19 个端点）

Gitea 与 Gitee 在这些路径上**同名同形**（Gitea 对齐 GitHub，Gitee 也仿 GitHub）：

| 能力 | 端点 | 备注 |
|---|---|---|
| 当前用户 | `GET /user` | 返回 `id`（数字）、`login`、`name`、`avatar_url` — 字段名一致 |
| 我的组织 | `GET /user/orgs` | 一致 |
| 组织信息 | `GET /orgs/{org}` | 一致 |
| 组织成员 | `GET /orgs/{org}/members` | ⚠ 分页参数不同，见 §3.5 |
| **组织下建仓** | `POST /orgs/{org}/repos` | 一致（`name`/`private`/`description`/`auto_init`） |
| **用户下建仓** | `POST /user/repos` | 一致 |
| 仓库详情/删除 | `GET|DELETE /repos/{o}/{r}` | 一致 |
| **写文件** | `POST|PUT /repos/{o}/{r}/contents/{path}` | 一致（`content` base64 / `message` / `branch` / `sha`） |
| 读文件/目录 | `GET /repos/{o}/{r}/contents/{path}` | 一致 |
| 分支 / 提交 | `GET /repos/{o}/{r}/branches|commits` | 一致 |
| 协作者增删查 | `GET|PUT|DELETE /repos/{o}/{r}/collaborators[/{u}]` | 一致（`permission`: read/write/admin） |
| Webhook 列表/删除 | `GET|DELETE /repos/{o}/{r}/hooks[/{id}]` | 路径一致，**请求体不一致**，见 §3.3 |
| 令牌传法 | `Authorization: token xxx` | **Gitea 同样接受** ✅ |
| 仓库字段 | `html_url` / `ssh_url` / `clone_url` | 一致；**Gitea 的 `html_url` 不带 `.git`** ⇒ 我们那套剥后缀逻辑对 Gitea 是**幂等无害**的 |

### ⚠ 必须改（5 个硬分歧点）

见 §3。

### ❌ 无对应物（要重新设计或砍掉）

| 能力 | Gitee | Gitea |
|---|---|---|
| **仓库级团队** | `GET /repos/{o}/{r}/teams` + `PUT /repos/{o}/{r}/teams/{team}`（`GiteeTeam` 实体 + 成员同步逻辑） | **没有仓库级团队**。只有组织级 `/orgs/{org}/teams` 与 `PUT /teams/{id}/repos/{org}/{repo}` ⇒ 要把「仓库挂团队」重写为「团队挂仓库」（语义反转） |
| **企业(enterprise)层级** | scope 里有 `enterprises`、组织之上还有企业 | 只有 `org`，**无 enterprise 层** ⇒ 若平台租户↔Gitee 企业有映射，需降级为 org |
| 仓库显示名与 URL 分离 | `name`（可中文）+ `path`（URL slug）**两个字段** | **只有一个 `name`，它就是 slug** ⇒ 详见 §3.4 |
| Webhook 明文口令校验 | `X-Gitee-Token` 明文比对 | HMAC-SHA256，需**改用摘要比对**，见 §3.3 |

---

## 3. 五个硬分歧点（按「会不会静默出事」排序）

### 3.1 ⚠⚠⚠ 仓库命名：Gitea 没有独立的 `path`

- **现状**：`createOrgRepo(..., name, path, ...)` 同时传 `name` 与 `path`。平台把
  `name` 存成中文显示名（如「AIOA 真机验证 1789630096」）、`repo_name` 存 slug（`dept11-aioa-1789630096`）。
- **Gitea**：`POST /orgs/{org}/repos` **不认 `path`**，`name` 即 slug。
- **后果**：不改的话，**`path` 被静默忽略**，仓库 URL 变成中文名（百分号编码、不可分享），
  而平台库里 `repo_name` 仍记录 slug ⇒ **平台展示的地址与真站不一致**（这正是我们在 Gitee 上刚踩过的
  `html_url` 带 `.git` 那类「库里存的和真站不一样」的坑）。
- **建议**：产品决策 —— Gitea 下**放弃中文显示名**，`name` 直接用 slug，另用 `description` 承载中文名；
  或接受 URL 用中文。**这会影响 `GiteeNaming` 的命名生成规则**。

### 3.2 ⚠⚠⚠ Webhook 签名：明文比对 → HMAC-SHA256

- **现状**：`GiteeWebhookService.verifyToken()` 从 `X-Gitee-Token` 取明文，`MessageDigest.isEqual` 比对
  （`GiteeClient.createHook` 里写 `password` + `encryption_type: 1`）。
- **Gitea**（官方文档原文核对）：
  - `X-Gitea-Signature` = **原始请求体的 hex HMAC-SHA256，无前缀**
  - 兼容头 `X-Hub-Signature-256` = 同值带 `sha256=` 前缀
  - **必须对「原始报文」算摘要** ⇒ 要先缓存 body 再解析 JSON（顺序错就永远校验失败）
  - 事件头 `X-Gitea-Event`（规范名），另有更细的 `X-Gitea-Event-Type`
- **后果**：不改 ⇒ **Webhook 全部 401/403，且是「平台拒收」而非「Gitee 没发」**，排障方向容易走反。

### 3.3 ⚠⚠ Webhook 请求体与事件名

| | Gitee | Gitea |
|---|---|---|
| 建 hook 请求体 | `url` / `password` / `push_events` / `merge_requests_events` / `issues_events` / `note_events` / `encryption_type` | `{type, config:{url, content_type, secret}, events:[...], active}` |
| 事件名 | `Push Hook` / `Merge Request Hook` / `Issue Hook` / `Note Hook` | `push` / `pull_request` / `issues` / **`issue_comment`** |

**现有 `classify()` 有个已经存在的隐患会被放大**：它按**子串**顺序判断
（`push` → `merge request`/`pull request` → `issue` → `note`）。
Gitea 的 `issue_comment` **含 `issue` 子串 ⇒ 会被误判成「Issue 事件」，永远进不到 `note` 分支**。
⇒ 事件映射必须**改成精确映射表**，不能继续用子串匹配。

### 3.4 ⚠⚠ OAuth 端点与 scope 词表整体不同

| | Gitee | Gitea |
|---|---|---|
| 授权端点 | `/oauth/authorize` | **`/login/oauth/authorize`** |
| 换令牌 | `/oauth/token`（网页域） | **`/login/oauth/access_token`** |
| scope 词表 | `user_info projects hook pull_requests issues notes …` | **`repo` / `read:repository` / `write:repository` / `read:organization` / `write:organization` / `read:user` / `notification` / `issue`…** —— **没有一个同名** |
| scope 是否生效 | 返回**应用登记时的权限集**（实测：请求 6 个拿到 11 个） | 官方文档**版本间口径不一致**：老文档写「不支持 scope，第三方应用获得用户全部资源」，新文档写「支持按路由分组的 read:/write:」 |
| 改 scope 的后果 | — | 文档明确：**已授权应用若改变请求的 scope，整个流程会失败，用户必须重新授权** |
| 回调 URI | 我们现用 `localhost`（实测可用） | 文档明确建议 **用 `127.0.0.1` 而非 `localhost`**（RFC 8252） |

⇒ **scope 必须整表重写并按目标 Gitea 版本实测**，这是「锁版本」的硬理由。

### 3.5 ⚠ 分页参数：`per_page` → `limit`（会**静默截断**）

- 现状：`listOrgMembers` / `listCollaborators` 传 `per_page=100`。
- Gitea：`ListOptions` 是 **`page` + `limit`**；`per_page` 不被识别 ⇒ **被忽略、回落默认页大小**。
- **后果**：成员/协作者列表**静默少一截**，而且因为不报错，测试也发现不了（和我们在 Gitee 上踩的
  「桩不校验 scope」是同一类：**参数被忽略 ≠ 报错**）。共约 6 处要改。

---

## 4. 工作量分解

单位：**人天**（1 名熟悉本仓库的后端；前端/测试含在内）。区间含 20% 缓冲。

| # | 工作包 | 路线 A（替换） | 路线 B（并存） | 说明 |
|---|---|---|---|---|
| 0 | **决策 + 锁定 Gitea 版本** | 1 | 1 | 版本决定 scope 口径；内网已有一个 Gitea 实例可先探版本 |
| 1 | 抽象层与配置装配 | 0.5 | **2.5** | 抽 `RepoProviderClient` 接口（~25 方法）、8 个注入点改接口、`@ConditionalOnProperty` 装两套实现、配置拆分为「公共 + 提供商」 |
| 2 | `GiteaClient` 实现 | **4** | 5 | 19 个同形端点照搬，5 个硬分歧点重写；错误形态归一化 |
| 3 | Webhook 双形态 | 2 | **3** | HMAC 校验（原始报文）、事件映射表（修 §3.3 的子串 bug）、幂等键字段适配、按项目 provider 分流 |
| 4 | OAuth + scope 词表 | 1.5 | 2 | 端点路径、scope 映射表、回调 URI、刷新链路 |
| 5 | 数据层 | 0.5 | **1.5** | 9 张表加 `provider` 列 + 存量回填（**建议不改表名**，理由见 §6） |
| 6 | 前端 | 1 | 1.5 | 文案 provider 化（「Gitee 侧添加」等）、`GITEE_*` 常量改名（机械）、`gitee:bind` 权限码迁移 |
| 7 | **测试（最容易低估）** | **5** | **8** | 桩要能模拟 Gitea 形态；4 个套件 252 条断言的口径改写 + 新增 Gitea 套件 + 真机跑 |
| 8 | 文档收口 | 1 | 1.5 | `docs/30` 改写、`docs/19` 审计表、README |
| | **合计** | **15.5** | **26** | |
| | **区间（含缓冲）** | **14–20** | **19–26** | 2 人并行墙钟约 ×0.6 |

**最小可用（MVP，约 5–8 人天）**：只做「令牌（个人/企业）→ 建仓 → 文件读写 → 成员同步」，
**不做 Webhook、不做浏览器 OAuth 授权**。这条路能把 §3.1/3.2/3.4 全部后置，风险最小、见效最快。

---

## 5. 为什么推荐路线 B（并存）而不是 A（替换）

1. **成本差只有 ~30%**，但省下来的不是「另一个提供商的适配」，而是**把已经跑通的 Gitee 链路一次性废掉**。
   你昨天刚在真站上把 Gitee 的 OAuth、建仓、写文件、删仓、4 个真实缺陷全修完并验证 —— 这些资产在路线 A 下**全部作废**。
2. **Gitea 的适配量并不因「只支持它」而变小**：5 个硬分歧点、Webhook 签名、OAuth、scope 一个都躲不掉。
3. **地级市项目的现实**：信创/私有化诉求常见，但也不排除有单位愿意用 SaaS。
   并存 = 一次投入换两种交付形态；对产品是**卖点**而不是负担。
4. **抽象层已被部分验证**：`gitee_stub.py` 就是「换后端」的先例，说明这套代码的替换成本可控。

---

## 6. 几个关键决策建议（省力气的地方）

| 决策 | 建议 | 理由 |
|---|---|---|
| 表名 `gitee_*` 要不要改 | **不改**，只加 `provider` 列 | 改 = 9 张表重命名迁移 + 全库 Mapper/实体/XML 改动，纯成本零收益 |
| 权限码 `gitee:bind` | 改 `repo:bind`（1 个）+ 加 Flyway 迁移 | 只有 1 个码带提供商字样，成本极低；`project:view`/`project:manage` 本来就是中性的 |
| 前端 `GITEE_*` 常量 | 可暂不改 | 纯命名，用户不可见；等真要上第二个提供商再统一改 |
| 中文仓库显示名（§3.1） | **需产品决策** | Gitea 无独立 slug 字段；这是**唯一的破坏性语义变更** |
| 团队同步（仓库级 team） | **建议直接砍掉**，或改成组织级团队 | Gitea 无对应端点，属「重写一个功能」而不是「换个 API」 |
| 表里已有数据 | 存量行回填 `provider='gitee'` | 保证历史项目仍按 Gitee 调用 |

---

## 7. 风险清单

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| 1 | **Gitea 版本间 scope 口径不一致** | 高 | 第 0 步锁版本 + 实测换回令牌的 scope；scope 词表做成配置 |
| 2 | **分页参数被静默忽略** ⇒ 列表少数据 | 高 | 全库替换 `per_page`→`limit`；补一条「条数=总数」的断言（现有套件已有此纪律） |
| 3 | **Webhook 假成功**（建 hook 返回 200 但收不到事件） | 高 | 必须有公网可达地址；没有就**如实标为未验证**，别用「配置成功」当通过 |
| 4 | **私有化 Gitea 常用自签证书** | 高 | 当前 `HttpClient` **无任何 TLS/信任配置**（已核对）⇒ 需加可配置 truststore 或显式跳过校验开关（且要能审计） |
| 5 | 中文仓库名进 URL | 中 | §3.1 的产品决策 |
| 6 | `issue_comment` 被误判为 issue 事件 | 中 | 事件映射改精确表（现状是子串匹配，**Gitea 下必错**） |
| 7 | 回调 URI 用 `localhost` | 低 | 改 `127.0.0.1`（Gitea 文档明确建议） |
| 8 | 桩环境覆盖真实绑定（**我们刚发现的那个坑**） | 中 | 切桩前先解绑；或给 `callback()` 加覆盖保护 |

---

## 8. 建议的落地顺序

1. **第 0 步（1 天）**：探内网 Gitea `172.16.8.249:3000` 的版本与 scope 行为 —— 这决定了后面所有 scope 配置。
2. **MVP（5–8 天）**：抽接口 → `GiteaClient` 只实现「令牌 + 建仓 + 内容 + 成员」→ 真机建一次仓。
   **这一步就能验证 §3.1（命名）与 §3.5（分页）两个会静默出错的点。**
3. **补 Webhook（2–3 天）**：需要公网可达地址，否则明确标注未验证。
4. **补 OAuth 浏览器授权（1–2 天）**：按锁定的版本实测 scope。
5. **收口（2 天）**：前端文案、权限码迁移、套件口径、文档。

---

## 9. 附：与本次 Gitee 真机验证的关联

我们在 Gitee 上刚验证过的 4 个真实缺陷里，**有 2 个在 Gitea 上会以另一副面孔重现**：

- `html_url` 带 `.git` 后缀 → Gitea **不带**，我们那套 `webUrl()` 剥后缀逻辑**幂等无害**（属白拿的兼容性）；
- 「桩不校验 scope」→ Gitea 下变成**「桩不校验 `limit`，`per_page` 被忽略也全绿」**，同一类陷阱。

⇒ **这次迁移必须沿用同一套纪律**：凡是「参数被忽略不报错」「字段名不同不报错」的地方，
**只有真机实测才算数**，桩环境全绿不能作为通过依据。
