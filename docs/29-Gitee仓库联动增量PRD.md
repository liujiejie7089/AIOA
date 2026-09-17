# 29 · Gitee 仓库联动 · 增量 PRD

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0（增量 PRD） |
| 日期 | 2026-09-16 |
| 作者 | 许清楚（产品经理） |
| 上游依据 | `docs/25-权限审批与组织关联改造二期三期增量PRD.md`（文档体例与缺口编号规范）；`docs/23-权限审批流程与组织关联改造方案.md`（项目文档语气）；迁移 `V48__gitee_integration.sql` / `V49__gitee_member_username_nullable.sql` |
| 基线 | **后端已实现并完成端到端回归（本地 Gitee V5 桩，116 断言全绿）**。本文件是对**已建成能力的忠实产品化描述**，用于冻结口径、指导前端接入与后续验收；非对未来的提案。 |
| 范围声明 | 只描述「平台项目 ↔ Gitee 仓库联动」这一增量能力。平台侧的权限审批、组织模型、多租户隔离沿用既有实现（`docs/23`、`docs/25`），**不重复设计**。不写竞品分析与市场定位。 |
| 编程栈（沿用） | SpringBoot 单体（`server/`，新增 Maven 模块 `aioa-gitee`）+ MySQL8（`aioa`）+ Vue3 管理端 shell + 用户端单文件 H5 |

---

## 1. 文档信息

| 项 | 内容 |
|---|---|
| 需求线 | 多部门协作场景下「平台建项目 → 代码实际托管在 Gitee」的打通 |
| 关联需求编号 | 平台侧权限码 `project:view` / `project:manage` / `gitee:bind`（`docs/15` 权限矩阵增量） |
| 关联迁移 | `V48`（8 张表 + 3 个权限码播种）、`V49`（成员登录名可空缺陷修正） |
| 关联模块 | `server/aioa-gitee`（client / config / controller / entity / mapper / service / support） |
| 关联接口前缀 | `/api/v1/gitee`（业务）、`/api/v1/gitee/bind`（OAuth2）、`/api/v1/gitee/webhook`（回调） |
| 关联测试 | `scripts/gitee_stub.py`（本地 Gitee V5 桩）、`scripts/e2e_v48_gitee.py`（端到端回归套件） |

---

## 2. 背景与目标

### 2.1 背景

平台承接的是**多部门协作型组织**的项目与成果管理。现实中，代码不会只躺在平台里 —— 各部门的研发成果最终要落到 Git 仓库上。当前存在三个断点：

1. **项目与代码仓库脱节**：平台里能看到「XX 部门的数据中台项目」，但对应的代码仓库在哪儿、由谁维护、有多少提交，平台一无所知。
2. **部门之间的代码边界靠人治**：没有部门级的仓库隔离口径，跨部门成员该不该看到某个仓库只能靠口头约定。
3. **代码动态回不到平台**：谁提交了、提了什么 PR、有没有评论，只存在于 Gitee 站内，平台侧没有可追溯的统一视图。

### 2.2 产品目标（三个正交目标）

| # | 目标 | 一句话口径 |
|---|---|---|
| **G-1** | **项目即仓库** | 在平台新建项目，平台自动在 Gitee 组织的对应部门命名空间下建出仓库，并保存映射；平台成为项目管理入口，Gitee 成为代码底层存储。 |
| **G-2** | **部门隔离可观测、可执行** | 每个部门的仓库带部门命名空间前缀，跨部门成员必须被**显式加为协作者**才可见；权限从平台自动同步到 Gitee 协作者。 |
| **G-3** | **代码动态统一回流** | Gitee 的提交 / 合并请求 / 任务 / 评论通过 Webhook 回传平台，形成按时间倒序的事件流，且**可把操作人映射回平台成员**。 |

### 2.3 非目标（明确不做，见 §3.3）

不改变既有权限审批链路；不引入消息中间件；不做组织级 Gitee Team 的真实创建（受 Gitee 开放能力限制，见 §11）。

---

## 3. 名词与范围界定

### 3.1 名词表

| 名词 | 界定 |
|---|---|
| **Gitee 组织（org）** | 全局唯一的 Gitee 组织（login），所有部门仓库都建在它下面。由平台配置 `aioa.gitee.org` 指定。 |
| **命名空间（namespace）** | 部门隔离在**仓库名**上的可观测落点，形如 `dept<部门id>-`。用它替代「Gitee 组织团队」做部门聚类（原因见 §11 风险 R-1）。 |
| **平台团队（gitee_team）** | 平台侧的「部门 ↔ 组织团队」逻辑记录。`provider=NAMESPACE` 时仅登记命名空间；保留 `gitee_team_id` 字段供企业版 / 未来 API 对接。 |
| **仓库（repo）** | 一个平台项目对应一个 Gitee 仓库；`repo_name` 含部门命名空间前缀，`gitee_owner` 为总组织。 |
| **协作者（collaborator）** | Gitee 的仓库级成员，认**登录名**而非平台 id。平台成员角色（READ/WRITE/ADMIN）映射为其协作者权限。 |
| **Webhook** | 平台在仓库上挂的回调，订阅 Push / 合并请求 / 任务 / 评论四类事件；校验方式是**明文共享密钥**（`X-Gitee-Token` 头，Gitee 不做 HMAC 签名）。 |
| **事件流** | Webhook 回传事件在平台的落库视图，按 id 倒序、分页，可按类型过滤。 |
| **身份映射** | 用 Gitee 数字 id（`gitee_uid`）把 Gitee 操作人反查为平台用户；未绑定的操作人落 NULL，前端展示其 Gitee 登录名。 |
| **异步任务队列（outbox）** | `gitee_task` 表 + 定时轮询。所有对外写操作（建仓 / 配 Webhook / 同步成员 / 删仓 / 摘钩子 / 校准）都经它执行，以规避 Gitee 限流并避免接口超时。 |

### 3.2 本期做（In Scope）

- Gitee OAuth2 授权码绑定的**全流程**（授权 / 回调 / 令牌加密存储 / 自动续期 / 解绑）。
- 新建项目 → 异步建仓 → 回写仓库地址与默认分支 → 自动配 Webhook。
- 成员增删改 → 异步同步到 Gitee 协作者；未绑定成员的挂起与后续补齐。
- 两种提交方式：**网页上传**（平台调 contents 接口）与**本地 git push**（经 Webhook 回流）。
- Webhook 接收：密钥校验、幂等去重、事件落库、身份映射。
- 分支 / 目录 / 文件预览、跳转 Gitee、提交与事件流展示。
- 周期校准（定时 + 手动触发）与删除回收链路（软删项目 → 摘 Webhook / 可选删仓）。

### 3.3 本期不做（Out of Scope）

| 明确排除 | 说明 |
|---|---|
| 组织级 Gitee Team 的真实创建 / 列举 | gitee.com V5 未开放 `/orgs/{org}/teams`（实测返回 HTML 404）。本期以「命名空间 + 协作者」落地，字段预留。 |
| 代码评审（PR review 决策）、合并操作 | 平台只**展示**PR 事件，不代用户在 Gitee 上执行合并 / 打回。 |
| CI/CD、制品管理、Issue 双向同步 | 仅单向展示；不做从平台改建 Gitee Issue。 |
| 多组织 / 多 Gitee 实例 | 单平台实例对接单 Gitee 组织。 |
| 大文件上传 | 单文件走网页上传上限 512KB，超出提示改用 git push。 |
| 引入 MQ / Redis 作为队列 | 本部署无可用 Redis，采用「落库 + 定时轮询」最简单可靠方案。 |

---

## 4. 用户角色与场景

### 4.1 四类角色各自能做什么

| 角色 | 能做什么 | 边界 |
|---|---|---|
| **租户管理员** | 查看本租户全部部门的项目；读运维任务统计；手动触发**本租户**校准 | 不能创建项目（平台管理员同理）；跨租户一律 404 |
| **机构管理员** | 在本机构管辖部门内创建 / 管理项目、加删成员、上传文件、删项目 | 越本机构管辖范围 → 403；跨租户 → 404 |
| **部门负责人** | 在本部门内创建 / 管理项目（含改配置 / 加成员 / 删项目） | 越本部门 → 403；跨租户 → 404 |
| **成员** | 看到**本部门项目**与自己**被显式加为成员**的项目；浏览分支 / 文件 / 提交 / 事件流 | 对非成员项目只读不可见（越权写 → 403） |
| **平台管理员** | 跨租户**只读**查看项目与事件流，便于运维排障 | 不可写（建项目 / 改配置 / 删项目一律 403） |

> 全体登录用户默认持有 `project:view` / `project:manage` / `gitee:bind` 三个权限码；**真正的可见范围由部门作用域收紧**（与 `docs/15` 权限矩阵的「码 × 作用域」双层口径一致）。

### 4.2 端到端用户故事（3-5 个）

| # | 故事 | 验收要点 |
|---|---|---|
| **S-1** | 作为**机构管理员**，我想先绑定自己的 Gitee 账号，这样后续建的仓库才归属正确、提交作者才是「我」 | OAuth 授权后 `bound=true`、登录名正确、有 refresh_token；绑定视图不出现任何令牌字段 |
| **S-2** | 作为**机构管理员**，我想在平台新建一个「政务数据中台项目」并指定归属部门，这样它自动成为部门空间下的一个 Gitee 仓库 | 接口毫秒级返回 `CREATING`；后台任务推进到 `ACTIVE`；仓库名带 `dept<部门id>-` 前缀；仓库地址（html/ssh/https）与 clone 命令可回读 |
| **S-3** | 作为**机构管理员**，我想把部门里的同事加为项目成员并给他「只读」权限，这样他只能看代码不能推送 | 成员初始 `PENDING`；异步同步后 `SYNCED`；Gitee 侧协作者权限为 `read`；改角色为 `ADMIN` 后 Gitee 侧同步为 `admin`（幂等更新不新建） |
| **S-4** | 作为**成员**，我想在平台网页直接改一个小文件提交，也想在自己电脑上 `git clone` 后 push，两种方式的提交都能在平台看到 | 网页上传返回提交 sha 且来源 `WEB`；本地 push 经 Webhook 回流落 `GIT` 提交；提交列表**两路合流**（同时含 `WEB` 与 `GIT`） |
| **S-5** | 作为**部门负责人**，我想在项目里看到本仓库最近的提交 / 合并请求 / 评论，并且知道每条动态对应平台上的哪位同事 | 事件流按时间倒序、分页、可按类型过滤；能映射的操作人显示平台用户，未绑定的显示 Gitee 登录名并标注 `actorMapped=false` |

---

## 5. 功能需求 FR-1 .. FR-10

> 每条含：编号、名称、描述、前置条件、主流程、异常流、验收标准。
> 验收层级标注：**API 级** = `scripts/e2e_v48_gitee.py` 断言；**渲染级** = 前端渲染断言。

### FR-1 · Gitee OAuth2 应用接入与个人账号绑定

- **描述**：平台用户通过 Gitee OAuth2 授权码模式绑定个人 Gitee 账号。令牌以 AES-256-GCM 加密入库（密文带 `enc:` 前缀），过期前 5 分钟自动续期，支持解绑。
- **前置条件**：`aioa.gitee.enabled=true` 且已配置 `client-id` / `client-secret` / `redirect-uri`。
- **主流程**：`POST /gitee/bind/authorize` 生成一次性 state（TTL 10 分钟）并返回授权跳转地址 → 用户在 Gitee 完成授权 → `GET /gitee/bind/callback`（公开端点）校验 state → 换令牌 → 拉取用户真实身份 → 落库 / 更新。
- **授权跳转域与服务端域必须解耦**（`aioa.gitee.oauth-authorize-base-url`，默认 `https://gitee.com`）：
  `web-base-url` 是**服务器**在调（`POST /oauth/token`、跳转原仓库链接），而 `/oauth/authorize` 是**用户浏览器**要去的地方。
  曾复用同一个键，于是「把服务端接口桩化以做端到端回归」的部署顺手把用户也送进了桩 ——
  用户看不到 Gitee 的授权同意页，被桩直接签发一个假身份（如 `gitee_dev_152`）后回跳显示「绑定成功」，
  **看似绑定成功、实则从未经过真实 Gitee 授权**。因此 `bindUrl` 额外返回：

  | 字段 | 含义 |
  |---|---|
  | `authorizeHost` | 浏览器实际要去的授权域（生产为 `gitee.com`） |
  | `sandbox` | 该域是否为非生产域（非 `gitee.com`/`www.gitee.com`） |
  | `warning` | `sandbox=true` 时的中文警示，前端弹窗提示；结果页同时注入警示条 |

  验收：`scripts/_probe_authorize_host.py` 用**同一份 jar、只改配置**跑两个实例对照 ——
  端到端接线（三项基址都指向桩）应得 `authorizeHost=127.0.0.1` + `sandbox=true`；
  生产默认（不设任何 `AIOA_GITEE_*` 基址）应得 `authorizeHost=gitee.com` + `sandbox=false`。
- **异常流**：
  - state 不存在 / 已消费 / 已过期 → 业务错误，返回可读失败 HTML 页，链接不可复用；
  - 换码未返回 access_token → 提示「授权可能被拒绝」；
  - 未启用或未配置 → 明确报「Gitee 集成未启用 / OAuth 应用未配置」，而非后续 401 误判；
  - 未绑定时解绑 → 业务错误（不静默成功）。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-1.1 | 未绑定时 `bound=false` 且不回传任何令牌字段 | API |
| FR-1.2 | 未绑定时解绑返回业务错误（非静默成功） | API |
| FR-1.3/1.4 | 授权地址含 `client_id`/`redirect_uri`/`response_type=code`/`state`/`scope` | API |
| FR-1.5 | state 为不可猜随机串（长度 ≥ 32） | API |
| FR-1.6 | 授权后 302 回跳平台回调并带 code+state | API |
| FR-1.7~1.10 | 回调返回可读 HTML 结果页，含登录名与回跳脚本，**不回显任何令牌** | API |
| FR-1.11 | state 一次性：重复使用同一回调被拒绝 | API |
| FR-1.12/1.13 | 绑定回读：`bound=true`、登录名正确、有 refresh_token，且**无令牌明文键** | API |
| FR-1.15/1.16 | 重复绑定为「更新」语义，仍只有一条绑定、一个有效令牌 | API |

> **安全约束**：任何接口不得把 `access_token` / `refresh_token` 回传前端。刷新实行**按用户单飞**（串行），避免 refresh_token 轮换竞争导致绑定失效。

### FR-2 · 新建项目自动创建 Gitee 仓库并保存映射

- **描述**：在平台新建项目时指定归属部门，平台据部门命名空间生成合法仓库名，异步在 Gitee 组织下建仓，成功后回写仓库地址、默认分支并保存映射。
- **前置条件**：操作者具备 `project:manage`；有本部门（或本机构管辖范围）建项目权限；**创建者已绑定有效 Gitee 令牌**（前置校验，避免落库后才在异步任务里失败）。
- **主流程**：`POST /gitee/projects`（毫秒级返回 `CREATING`）→ 入队 `CREATE_REPO` → 后台建仓 → 成功入队 `CONFIGURE_WEBHOOK` → 配钩子成功后项目转 `ACTIVE`。
- **异常流**：
  - 项目名称为空 / 未选部门 / 部门不存在或跨租户 → 业务错误；
  - 同租户仓库路径重名 → 明确拒绝并提示换名；
  - 建仓遇「已存在」（多为上次成功但写库失败）→ **认领**已存在仓库而非报错；
  - 建仓或配钩子失败 → 状态 `FAILED` 且记 `error_msg`，可 `POST .../retry` 重试。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-2.1/2.2 | 可选部门含本机构部门；命名空间形如 `dept<id>-` | API |
| FR-2.3 | 建项目接口同步返回 `CREATING`（不等待外网建仓） | API |
| FR-2.4 | 仓库路径带部门命名空间前缀 | API |
| FR-2.5 | 同租户重名项目被拒绝 | API |
| FR-2.6 | 后台任务把项目推进到 `ACTIVE` | API |
| FR-2.7/2.8/2.9 | 回写 html/ssh/https 与默认分支；提供 clone 命令；`giteeOwner` 为配置组织 | API |
| FR-2.10/2.11 | Gitee 侧确实建出对应仓库，且建在组织命名空间下 | API |

### FR-3 · 自动配置 Webhook

- **描述**：仓库就绪后自动在仓库上配置 Webhook，订阅 Push / 合并请求 / 任务 / 评论四类事件；回调地址指向平台 `/api/v1/gitee/webhook/{projectId}`；使用**明文共享密钥**（`X-Gitee-Token`）。
- **前置条件**：仓库已 `ACTIVE`（配钩子在建仓成功后才入队）。
- **主流程**：入队 `CONFIGURE_WEBHOOK` → 列出现有 hooks（自愈清理指向**别的项目**的平台钩子）→ 若回调地址已存在则复用其 id（幂等）→ 否则用每仓库独立密钥创建钩子 → 回写 `webhook_id`/`webhook_events`，项目转 `ACTIVE`，并登记创建者为仓库管理员成员。
- **异常流**：未配置 `webhook-base-url` → 明确报错（Gitee 无法回调本机地址）；清理遗留钩子失败 → 记日志不阻塞本次配置。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-3.1/3.2 | 详情报告 Webhook 已配置、密钥已写入（**只回布尔，不回原文**） | API |
| FR-3.3 | 订阅事件恰为 `push,merge_requests,issues,notes` | API |
| FR-3.4 | Gitee 侧确有 1 个钩子（未重复挂载） | API |
| FR-3.5 | 回调地址指向平台 Webhook 端点 | API |
| FR-3.6/3.7 | 钩子携带明文共享密钥（长度 ≥ 16）；四个事件开关全开 | API |

### FR-4 · 成员自动同步为仓库协作者

- **描述**：平台增删项目成员、变更角色时，自动同步到 Gitee 仓库协作者。角色映射：`READ→read`、`WRITE→write`、`ADMIN→admin`。成员未绑定 Gitee 时挂起 `PENDING`（`gitee_username` 留 NULL），绑定后由校准补齐；移除成员时回收权限；项目创建者不可移除。
- **前置条件**：成员记录存在且属于该项目；操作者具备该项目写权限。
- **主流程**：`POST /projects/{id}/members` → 记录成员（新成员 `PENDING`）→ 入队 `SYNC_MEMBER(op=add)` → 后台同步协作者权限 → 置 `SYNCED`。
- **异常流**：
  - 成员尚未绑定 Gitee → 不报错，标 `PENDING` 并记 `last_error`（管理员本就可先把人加进来）；
  - 试图移除项目创建者 → 业务错误「项目创建者的仓库权限不可移除」；
  - 重复添加同一成员 → **幂等更新**（改角色/登录名），不新建第二条。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-4.2 | 项目创建者被自动登记为仓库 `ADMIN` | API |
| FR-4.4 | 创建者在 Gitee 侧成为协作者且权限为 `admin` | API |
| FR-4.5/4.6 | 可添加候选为「本租户已绑定 Gitee 的成员」，已加入者标 `alreadyMember=true` | API |
| FR-4.8/4.9 | 新成员初始 `PENDING`，同步后 `SYNCED` 且无错误 | API |
| FR-4.10 | Gitee 侧协作者权限 = `read`（平台 READ 映射正确） | API |
| FR-4.11/4.12 | 重复添加为幂等更新；改角色同步到 Gitee（read→admin） | API |
| FR-4.13 | 项目创建者的仓库权限不可移除 | API |
| FR-4.14/4.15 | 移除成员后 Gitee 协作者被回收、平台成员列表同步收缩 | API |
| FR-4.16/4.17 | 可按 Gitee 登录名直接加外部协作者（`source=PLATFORM`、`external=false`） | API |

> **缺陷修正（V49）**：未绑定成员的登录名必须留 NULL，**不得**用 `user-<id>` 占位名 —— 占位名会被当作真实 Gitee 用户拉进仓库或产生一串 404 重试。

### FR-5 · 两种提交方式

- **描述**：① 网页端上传文件（平台调 Gitee contents 接口，同步返回并立刻落 `source=WEB` 提交）；② 本地 `git clone` + `push`（平台不知情，由 Webhook 回流落 `source=GIT` 提交）。两者共用 `gitee_commit` 表与 `(project_id, sha)` 唯一键，天然合流。
- **前置条件**：项目 `ACTIVE`；上传需操作者具备写权限且本人已绑定 Gitee（**用当前登录用户令牌**，非创建者令牌，保证提交作者正确）。
- **主流程**：网页上传 → 先 `POST` 新建；若已存在则取现有 blob sha 改 `PUT` 覆盖 → 落提交记录并返回跳转地址。
- **异常流**：路径为 `..` 或越出仓库 → 业务错误「非法路径」；单文件 > 512KB → 提示改用 git push；令牌无效 → 提示重新绑定。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-5.1~5.3 | 网页上传新建成功、返回 sha、来源 `WEB`、返回可跳转 blob 地址 | API |
| FR-5.4 | 覆盖已存在文件自动改用 PUT + 旧 sha（不报 422） | API |
| FR-5.5/5.6 | 文件内容可回读且一致；文本标记为非二进制 | API |
| FR-5.7/5.8 | 根目录与子目录可浏览 | API |
| FR-5.9 | 路径穿越（`..`）被拒绝 | API |
| FR-5.10/5.11 | 分支列表可读且含默认分支，非降级态 | API |
| FR-5.12~5.14 | 桩以仓库真实密钥投递 push 成功，平台接受并落 1 条提交明细 | API |
| FR-5.15/5.16 | 提交列表同时含 `WEB` 与 `GIT`（双路合流）；`total == len(items)` | API |

### FR-6 · Webhook 接收

- **描述**：`POST /api/v1/gitee/webhook/{projectId}` 为**公开写入口**，三重防线：① 路径 projectId 必须存在；② `X-Gitee-Token` 与项目密钥**常量时间明文比对**；③ `event_key` 唯一索引兜底幂等。接收后事件落库，并把操作人按 `gitee_uid`（登录名兜底）映射为平台用户。
- **前置条件**：项目存在且已配置 Webhook 密钥。
- **主流程**：校验密钥 → 解析事件类型（PUSH/MERGE_REQUEST/ISSUE/NOTE）→ 构造幂等键 → 落 `gitee_event`；PUSH 事件顺带落提交明细（单次最多 20 条）。
- **异常流**：
  - 项目不存在 → `accepted=false`（不泄露内部状态），HTTP 仍 200；
  - 密钥错误 / 为空 → `accepted=false`、`reason=BAD_TOKEN`，**不放行匿名写入**；
  - 重复投递 → 命中唯一键判为**正常路径**，返回 `duplicated=true`、`commits=0`，不新增记录；
  - 未预期异常 → 兜底返回 200，避免 Gitee 持续重投。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-6.1~6.3 | 重复投递 `duplicated=true`、不新增提交明细、事件总数不变 | API |
| FR-6.4/6.5 | 事件类型归一化为 `PUSH`；记录原始 Gitee 事件头 | API |
| FR-6.6/6.7 | 分支名去 `refs/heads` 前缀；摘要含分支与「推送」可读 | API |
| FR-6.8 | 未绑定操作人映射为空但保留登录名（不强行归属） | API |
| FR-6.9/6.10 | 错误密钥 / 空密钥被拒且 HTTP 仍 200 | API |
| FR-6.11 | 被拒投递未污染事件表 | API |
| FR-6.12/6.13 | MR / Issue / Note / Push 四类事件均入库 | API |
| FR-6.14~6.16 | 列表倒序；MR 标题与动作解析正确；评论正文作摘要并挂对应分支 | API |
| FR-6.17~6.19 | 支持按类型过滤；分页 `len==min(total,size)`；列表不返回原始 payload | API |

> **为什么永远返回 HTTP 200**：Gitee 对非 2xx 会持续重投。对不接受的请求返回 200 + `accepted=false`，避免把无效请求变成持续重投循环。

### FR-7 · 分支与文件预览、跳转 Gitee、项目软删

- **描述**：提供分支列表、目录 / 文件内容预览（含二进制识别），并给出「跳转原仓库」的 html 地址；项目删除为**软删**，可选是否连仓删除。
- **前置条件**：项目可见（作用域内且租户匹配）。
- **主流程**：`GET /branches`（远端实时，失败降级为默认分支且带 `degraded=true`）→ `GET /contents?path=&ref=`（目录或文件）→ `DELETE /projects/{id}?purgeRepo=`。
- **异常流**：远端不可用 / 限流 → 分支列表降级不抛错，说明 `degradedReason`；越界或不存在项目 → 404。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-7.1 | 分支列表可读且含默认分支；远端可用时 `degraded=false`；不可用时降级且带原因 | API |
| FR-7.2 | 目录 / 文件可浏览；文件含 `downloadUrl` 与二进制标记 | API |
| FR-7.3 | 项目视图提供 `htmlUrl`（跳转 Gitee 原仓库） | API |

### FR-8 · 事件流展示

- **描述**：`GET /projects/{id}/events` 展示提交 / 合并请求 / 任务 / 评论事件，按 id 倒序、分页、可按 `eventType` 过滤；列表不返回原始 payload；每行标注 `actorMapped`。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-8.1 | 事件列表按 id 倒序（最新在前） | API |
| FR-8.2 | 分页 `len(items) == min(total, size)`，`size` 上限 100、默认 20 | API |
| FR-8.3 | 支持按 `eventType` 过滤 | API |
| FR-8.4 | 列表不返回原始 payload（防大字段拖垮列表） | API |
| FR-8.5 | 每行含 `actorMapped`，可直接判断身份是否映射成功 | API |

### FR-9 · 定时校准与手动触发

- **描述**：定时（默认每小时第 17 分）或手动触发成员校准：把本地 `PENDING` 成员补推为协作者，并把 Gitee 侧手工添加的外部协作者**纳入平台成员列表**（`source=GITEE`）。校准只入队，由队列限速执行。
- **前置条件**：手动触发需租户管理员；平台管理员可校准全部租户。
- **主流程**：`POST /gitee/calibrate` → 按租户作用域为每个 ACTIVE 项目入队 `SYNC_ALL`（单轮上限 200、每条错峰 2 秒）。
- **异常流**：非 ACTIVE 项目跳过（建仓未成 / 已失败，无仓可校）；读取远端协作者失败 → 记日志返回，不中断整轮。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-9.1 | 手动触发返回入队条数；租户管理员只能校准本租户 | API |
| FR-9.2 | Gitee 侧手工添加的协作者被纳入平台成员列表 | API |
| FR-9.3 | 该成员来源标 `GITEE`、`external=true`（可区分外部来源） | API |

### FR-10 · 删除与回收链路

- **描述**：删除项目为**软删**（`deleted_at` 置位、列表不再返回、同名可重建）。`purgeRepo=false`（默认）时保留 Gitee 仓库但**必须摘掉平台自己挂的 Webhook**；`purgeRepo=true` 时异步删除 Gitee 仓库。
- **前置条件**：操作者具备该项目写权限。
- **主流程**：软删前**先取消该项目下未执行的任务**（否则「删项目」后建仓任务还会把仓库建出来）→ 置状态 `DELETED` → 软删记录 → 据 `purgeRepo` 入队 `DELETE_REPO` 或 `DELETE_WEBHOOK`。
- **异常流**：远端仓库已不存在（404）= 目标已达成，跳过不算失败；摘钩子缺操作人 → 跳过（由下次建仓自愈清理）。
- **验收标准**：

| 编号 | 验收条目 | 层级 |
|---|---|---|
| FR-10.1~10.4 | 软删成功并说明「仓库保留」；删除后详情 404、列表不再返回、Gitee 仓库仍在 | API |
| FR-10.5/10.6 | 同名项目可重建（软删后唯一键让位）；重建能走 ACTIVE（认领已存在仓库） | API |
| FR-10.7 | 认领路径不会重复挂 Webhook（幂等） | API |
| FR-10.8/10.9 | 显式 `purgeRepo=true` 时标注删仓，Gitee 侧仓库确实被删除 | API |

---

## 6. 非功能需求

| 维度 | 要求 | 实现口径 |
|---|---|---|
| **性能 / 限流** | 所有对外写操作不得在接口内同步执行；遇 Gitee `403 Rate Limit Exceeded` 必须可退避重试而非永久失败 | DB outbox（`gitee_task`）+ 固定延迟 3s 轮询 + `batch=5` 限速；退避 `10s × 2^attempts`，封顶 10 分钟；仅对可重试错误重试，参数类错误直接判死 |
| **优先 Webhook、禁止轮询** | 提交与事件**以 Webhook 推送为主**，不轮询 Gitee 拉取；浏览类优先读本地库 | 提交 / 事件读本地 `gitee_commit` / `gitee_event`；仅分支、文件树等实时性要求高的走远端 |
| **安全 · 令牌** | 令牌加密存储、**任何接口不落前端** | AES-256-GCM，密文带 `enc:` 前缀，密钥来自 `aioa.gitee.token-enc-key`；绑定视图与项目视图均不含令牌字段 |
| **安全 · 密钥比对** | Webhook 密钥使用**恒定时间比较** | `MessageDigest.isEqual(...)`；项目未配置密钥时**拒绝**而非放行 |
| **安全 · 越界** | 跨租户 / 跨机构一律 404（不泄露存在性）；同租户越权才 403 | 服务层统一 `requireVisible(forWrite)`，控制器不做二次鉴权 |
| **可用性 · 降级** | Gitee 不可用时降级不阻塞主流程 | 分支列表失败降级为默认分支并带 `degradedReason`；成员补齐失败只记日志，不回退「项目已就绪」主结论 |
| **可用性 · 幂等** | 外部调用可能成功但本地写库失败，重试必须安全 | 建仓遇已存在→认领；配钩子先列现有 hooks→复用；事件 / 提交靠唯一键去重 |
| **审计** | 关键动作可追溯 | 事件表存原始报文（截断上限 60000 字符）、请求 id、收件时间；成员表存 `source`（PLATFORM/GITEE）与 `synced_at`；解绑保留审计痕迹 |
| **配置** | 关键参数可外部化 | `aioa.gitee.*`：`enabled` / `base-url` / `client-id` / `client-secret` / `redirect-uri` / `org` / `webhook-base-url` / `token-enc-key` / `sync-cron` / `purge-repo-on-delete` 等 |

---

## 7. 权限矩阵

权限码（与 `PermissionCatalog` 同源，缺一不可，否则前端菜单 / 路由 / 接口三层会漂移）：

| 权限码 | 名称 | 类型 | 默认授予 |
|---|---|---|---|
| `project:view` | 项目与代码仓库（查看） | APP | 全体登录用户 |
| `project:manage` | 项目与代码仓库（管理） | APP | 全体登录用户 |
| `gitee:bind` | Gitee 账号绑定 | API | 全体登录用户 |

> **重要**：权限码是「**能用哪个接口**」的闸门；「**能看见哪些数据**」由**部门作用域**收紧。两个闸门同时生效。

权限码 × 角色 × 作用域：

| 能力 / 角色 | 平台管理员 | 租户管理员 | 机构管理员 | 部门负责人 | 成员 |
|---|---|---|---|---|---|
| 读项目列表 / 详情 | 跨租户只读 | 本租户全部部门 | 本机构管辖部门 | 本部门 | 本部门 + 被加为成员的项目 |
| 创建项目 | ✗（403） | ✗（403） | 本机构管辖部门内 | 本部门内 | ✗ |
| 改配置 / 加删成员 / 上传 | ✗ | ✓（本租户） | ✓（本机构） | ✓（本部门） | ✗（非成员 403） |
| 删项目 | ✗ | ✓ | ✓ | ✓ | ✗ |
| 读运维任务统计 / 手动校准 | 全部租户 | 本租户 | ✗（403） | ✗ | ✗ |

错误语义约定：

| 场景 | 返回 |
|---|---|
| 业务错误（参数、状态、重复等） | HTTP **200** + `code != 0` |
| 跨租户 / 跨机构越界、项目不存在 | HTTP **404**（不泄露存在性） |
| 同租户 / 同机构越权（如成员写非成员项目） | HTTP **403** |
| 未认证访问受保护接口 | HTTP **401** |
| Webhook 密钥错误 / 项目不存在 | HTTP **200** + `accepted=false`（避免 Gitee 重投） |

---

## 8. 数据模型

8 张新表（迁移 `V48`，`V49` 修正其中一张的列约束），全部遵循仓库统一「软删 + `alive` 生成列」约定：`alive TINYINT GENERATED ALWAYS AS (IF(deleted_at IS NULL,1,NULL)) VIRTUAL`，仅用于配合唯一键让软删行不占位。

| # | 表 | 用途 | 关键字段 | 唯一键 / 幂等键 | 软删 |
|---|---|---|---|---|---|
| 1 | `gitee_account` | 平台用户 ↔ Gitee 账号绑定与令牌 | `gitee_uid`（身份映射锚点）、`access_token`/`refresh_token`（密文）、`token_expires_at` | `(tenant_id, user_id, alive)`；`(tenant_id, gitee_uid, alive)` | ✓ |
| 2 | `gitee_oauth_state` | 授权码模式 state（防 CSRF + 防重放） | `state`、`consumed`、`expires_at`、`redirect_uri` | `(state)` | ✗（一次性消费） |
| 3 | `gitee_team` | 部门 ↔ 组织团队（部门隔离落点） | `namespace`、`gitee_team_id`、`provider`（NAMESPACE/API） | `(tenant_id, department_id, alive)` | ✓ |
| 4 | `gitee_project` | 平台项目 ↔ Gitee 仓库映射 | `repo_name`、`gitee_owner`/`gitee_repo`、`webhook_id`、`webhook_secret`、`status`、`purge_repo` | `(tenant_id, gitee_owner, gitee_repo, alive)` | ✓ |
| 5 | `gitee_repo_member` | 仓库成员与权限同步记账 | `gitee_username`（协作者键，**可空**）、`role`、`source`、`sync_status` | `(project_id, gitee_username, alive)` | ✓ |
| 6 | `gitee_event` | Webhook 事件日志 | `event_type`、`event_key`（幂等）、`actor_gitee_uid`、`actor_user_id`、`payload` | `event_key`（唯一） | ✗ |
| 7 | `gitee_commit` | 提交记录（网页 + push 合流） | `sha`、`branch`、`source`（WEB/GIT）、`author_user_id` | `(project_id, sha)` | ✗ |
| 8 | `gitee_task` | 异步任务队列（outbox） | `task_type`、`status`、`attempts`、`next_run_at`、`locked_by` | `(status, next_run_at, id)` 取件索引 | ✗ |

**状态机与枚举**：

| 对象 | 取值 |
|---|---|
| `gitee_project.status` | `CREATING` → `ACTIVE`；`CREATING` → `FAILED`（可重试）；`ACTIVE` → `DELETED` |
| `gitee_task.task_type` | `CREATE_REPO` / `CONFIGURE_WEBHOOK` / `SYNC_MEMBER` / `DELETE_REPO` / `DELETE_WEBHOOK` / `SYNC_ALL` |
| `gitee_task.status` | `PENDING` / `RUNNING` / `DONE` / `FAILED` |
| `gitee_repo_member.role` | `READ` / `WRITE` / `ADMIN` |
| `gitee_repo_member.sync_status` | `SYNCED` / `PENDING` / `FAILED` |
| `gitee_repo_member.source` | `PLATFORM` / `GITEE` |
| `gitee_commit.source` | `WEB` / `GIT` |
| `gitee_event.event_type` | `PUSH` / `MERGE_REQUEST` / `ISSUE` / `NOTE` / `OTHER` |

**幂等键构造（`event_key`）**：由「事件类型 + 业务稳定标识」拼成，再取 SHA-256。PUSH 用 `after`（兜底 `head_commit.id`）、MR 用 `id+action+updated_at`、Issue 用 `id+action+updated_at`、评论用 `comment.id+action`；都取不到时才退化为整报文哈希。

---

## 9. 接口契约摘要

> 统一响应封装：业务错误 = HTTP 200 + `code != 0`；`data` 为业务载荷。

**A. 元信息 / 配置**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/gitee/config` | 前端初始化：是否启用、组织是否配置、回调地址是否配置、同步开关、角色选项 |
| GET | `/api/v1/gitee/departments` | 建项目可选部门（受作用域限制） |
| GET | `/api/v1/gitee/tasks/stats` | 队列概况（**租户管理员**） |
| POST | `/api/v1/gitee/calibrate` | 手动触发校准（租户管理员本租户；平台管理员全部） |

**B. 账号绑定（OAuth2）**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/gitee/bind` | 我的绑定状态 |
| POST | `/api/v1/gitee/bind/authorize` | 生成授权跳转地址 |
| DELETE | `/api/v1/gitee/bind` | 解绑 |
| GET | `/api/v1/gitee/bind/callback` | 授权回调（**公开**，返回 HTML） |

**C. 项目**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/gitee/projects` | 项目列表（按作用域过滤） |
| POST | `/api/v1/gitee/projects` | 新建项目（异步建仓） |
| GET | `/api/v1/gitee/projects/{projectId}` | 项目详情（仓库 / Webhook / 成员 / canManage） |
| POST | `/api/v1/gitee/projects/{projectId}/retry` | 建仓失败重试 |
| DELETE | `/api/v1/gitee/projects/{projectId}?purgeRepo=` | 软删项目（可选删仓） |

**D. 成员**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/gitee/projects/{projectId}/members` | 成员列表 |
| GET | `/api/v1/gitee/projects/{projectId}/members/candidates` | 可添加候选 |
| POST | `/api/v1/gitee/projects/{projectId}/members` | 添加成员（异步同步协作者） |
| DELETE | `/api/v1/gitee/projects/{projectId}/members/{memberId}` | 移除成员（异步回收） |

**E. 内容与事件**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/gitee/projects/{projectId}/branches` | 分支列表 |
| GET | `/api/v1/gitee/projects/{projectId}/contents?path=&ref=` | 目录 / 文件内容 |
| POST | `/api/v1/gitee/projects/{projectId}/contents` | 网页上传提交 |
| GET | `/api/v1/gitee/projects/{projectId}/commits?branch=&page=&size=` | 提交记录 |
| GET | `/api/v1/gitee/projects/{projectId}/events?eventType=&page=&size=` | 事件流 |

**F. Webhook 接收**

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/gitee/webhook/{projectId}` | Gitee 回调入口（**公开**，密钥校验 + 幂等） |

---

## 10. 验收标准与测试策略

### 10.1 可验证的验收点（汇总）

- 10 条功能需求 FR-1..FR-10 各自的验收标准表（§5）全部通过。
- 权限矩阵（§7）的 404 / 403 / 401 语义被逐条验证：跨租户读写 404、机构管理员读运维统计 403、未认证 401、不存在项目 404。
- 安全约束：绑定视图与项目视图不含令牌字段；Webhook 空密钥 / 错误密钥被拒；路径穿越被拒。
- 幂等约束：重复投递事件不新增记录；重复添加成员不新建；重建项目不重复挂 Webhook。
- 一致性：提交列表 `total == len(items)`（无分页时不允许不等）；事件列表严格倒序。

### 10.2 测试策略：本地 Gitee V5 stub 端到端回归

- **为什么用 stub**：真实 Gitee 有速率限制、会产生不可回收的外部状态、且 CI 不可依赖公网；桩服务在本地复刻 V5 的关键端点（建仓 / 钩子 / 协作者 / contents / 分支 / 换码 / 刷新）与限流行为，使回归可重复。
- **套件**：`scripts/e2e_v48_gitee.py` + 常驻桩 `scripts/gitee_stub.py`。
- **断言纪律**（继承仓库规范）：
  - 不写死条数，一律用**关系式断言**（`total == len(items)`、包含关系、单调变化）；
  - 等待异步任务用**轮询 + 明确上限**，不用固定 `sleep`；
  - 每条断言失败打印实际值，便于归因「代码 bug」还是「数据漂移」；
  - 套件可重复运行：每轮先复位绑定与桩状态（**测试夹具复位，不是放宽断言**）。
- **当前结果**：**116 断言全绿**（覆盖 FR-1..FR-10 与 PRE 前置）。

### 10.3 回归约束（硬性）

- 迁移纪律：**只追加、不改已应用**（`V48` 已应用则 `V49` 追加修正，`checksum` 不可变）。
- 缺省兼容：新增请求字段缺省时必须复现旧行为。
- 越界语义：跨租户 / 跨机构一律 **404**；同租户越权才 **403**；与全站一致。

---

## 11. 里程碑与风险

### 11.1 里程碑（按已完成的实现顺序回述）

| 阶段 | 交付物 | 状态 |
|---|---|---|
| M1 | 迁移 `V48`（8 表 + 3 权限码）、`aioa-gitee` 模块骨架、OAuth2 绑定 | 已完成 |
| M2 | 建仓 / 配 Webhook / 成员同步 / 异步队列与退避 | 已完成 |
| M3 | 网页上传 + 本地 push 回流 + Webhook 接收与身份映射 | 已完成 |
| M4 | 分支文件预览、事件流、软删与回收链路 | 已完成 |
| M5 | 定时 / 手动校准；`V49` 缺陷修正 | 已完成 |
| M6 | 本地 Gitee V5 桩 + 端到端回归（116 断言全绿） | 已完成 |
| M7 | 前端接入（管理端 shell + 用户端 H5）与生产参数落地 | 待推进 |

### 11.2 风险与对策

| # | 风险 | 影响 | 对策 / 现状 |
|---|---|---|---|
| **R-1** | 真实 Gitee（开源 gitee.com）**无组织级 Team API**（`/orgs/{org}/teams` 实测返回 HTML 404） | 无法把仓库真正挂到组织团队下做部门隔离 | 采用「**命名空间 + 协作者权限**」隔离模型：仓库名带 `dept<id>-` 前缀，跨部门成员须显式加为协作者；保留 `gitee_team_id` 与 `provider=API` 供企业版 / 未来 API 对接 |
| **R-2** | 生产前需**重新生成** OAuth 应用与令牌 | 当前测试用的 client / 令牌不可用于生产 | 上线前在 Gitee 侧新建 OAuth 应用，配置正式 `client-id` / `client-secret` / `redirect-uri`；`token-enc-key` 必须覆盖默认值 |
| **R-3** | Gitee 限流（未认证 / 高频请求 `403 Rate Limit Exceeded`） | 建仓 / 同步集中失败 | 全部写操作走 outbox + 限速 + 指数退避；已实现 |
| **R-4** | Webhook 明文共享密钥弱于 HMAC 签名 | 密钥泄露即可伪造事件 | 每仓库独立随机密钥（默认 24 字节十六进制），恒定时间比较；密钥不下发前端 |
| **R-5** | `gitee_username` 曾用占位名导致权限误授 | 把仓库权限授给外部真实用户或产生 404 重试 | `V49` 修正为可空，未绑定成员写 NULL 并原地 `PENDING`，绑定后由校准补齐 |
| **R-6** | 队列无 MQ，依赖单库 + 定时轮询 | 极端并发下吞吐受限于批量与轮询间隔 | 抢占式领取（条件 UPDATE）保证多实例安全；参数类错误直接判死不重试 |

### 11.3 待确认问题（仅列真正需要业务决策项，均给默认建议）

| # | 问题 | 默认建议 |
|---|---|---|
| Q-1 | 删除项目时默认是否连仓删除？ | **默认不删**（`purge-repo-on-delete=false`）；代码删除不可恢复，需要真删必须显式传 `purgeRepo=true`。 |
| Q-2 | 未绑定 Gitee 的成员能否加入项目？ | **能**，以 `PENDING` 挂起，绑定后自动补齐；候选列表只返回**已绑定**成员，避免管理员加了没反应。 |
| Q-3 | 一个 Gitee 账号能否在同一租户绑定多个平台用户？ | **不能**（`(tenant_id, gitee_uid, alive)` 唯一）；避免身份映射歧义。 |
| Q-4 | 平台管理员是否可代租户操作项目？ | **不可**，仅跨租户只读；运维视角不写租户数据。 |

---

> **给下游（前端 / 架构）的三条输入要点**
> 1. **一切写操作都不要在前端等外网**：建项目、加成员、删项目均为「入队 + 稍后刷新」，前端应以列表状态（`CREATING`/`PENDING`）与轮询呈现进度，而非同步阻塞。
> 2. **令牌与密钥永不下发前端**：前端只消费 `bound` / `configured` / `secretConfigured` 等布尔与地址字段。
> 3. **越界一律 404**：前端不要把 404 当「网络错误」，它是权限边界的正常表达；同租户越权才是 403。
