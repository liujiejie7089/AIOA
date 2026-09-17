# 30 · 企业 Gitee 主动初始化 · 统一消息中心与多通道触达 · P1 实施排期

> 编制：2026-09-17 · 迁移：**V51**（Gitee 企业初始化）、**V52**（消息通道与投递）
> 本轮交付：§1 与 §2 **已实现**；§3 为 P1 其余三项的排期，**未开工**（理由见 §3.0）。

---

# 一、企业 Gitee 主动初始化

## 1.1 为什么是「主动初始化」，而不是自动初始化

**现状（已核实）**：租户开通（`TenantProvisionedEvent`）的监听者只有审批流、职务、假种、数字员工模板四个，**Gitee 不在其中**；每个用户是各自通过 OAuth 绑定自己的 Gitee 账号。

**产品口径：保持「不自动初始化」**，理由：
- 自动初始化必须凭空获得一份**有效令牌**与一个**已存在的组织**；平台既没有，也不应该在开通时替企业创建外部资源（会造成"看似开通、实则不可用"的假象）。
- Gitee 的组织与令牌属于**企业的外部资产**，其授权、配额、合规责任在企业侧，应由企业显式发起并确认。

**因此新增**：企业（租户）主动触发的初始化流程，由企业提供**企业级访问令牌 + 组织名**，平台校验通过后落库并激活。

## 1.2 触发条件（明确）

| 维度 | 规则 |
|---|---|
| **何时需要初始化** | 企业要使用「项目与仓库」能力时。未初始化时：`initStatus=PENDING`，组织回落平台默认（既有 V50 语义不变），企业令牌为空 |
| **谁能触发** | 租户管理员（`ROLE_TENANT_ADMIN`）。平台管理员可代企业操作，需显式传 `?tenantId=`；**租户管理员跨租户会被拒** |
| **幂等性** | 重复初始化 = 更新同一行（`gitee_tenant_config.tenant_id` 唯一键），不产生多行 |
| **不触发 / 拒绝的情形** | ① 平台级开关关闭（`aioa.gitee.enabled=false`）；② 本企业 Gitee 联动已被显式关闭且本次未显式启用；③ 令牌格式非法；④ 组织名非法；⑤ 令牌无效/过期；⑥ 令牌无权访问该组织 |
| **不会自动发生的事** | 开通企业不会自动初始化；初始化不会自动创建 Gitee 组织（Gitee V5 无「建组织」接口）；不会修改既有组织名与开关（那是 `/gitee/tenant-config` 的职责） |

## 1.3 参数项与校验规则

| 参数 | 必填 | 校验规则 | 失败文案 |
|---|---|---|---|
| `accessToken` | **首次必填**；已初始化后可留空（表示只改组织名/开关，不轮换令牌） | 非空白；长度 8~512；不含空白字符；匹配 `^[A-Za-z0-9._\-]{8,512}$`；**并通过 Gitee 实际校验** | `访问令牌格式不合法（长度需 8~512，仅允许字母/数字/._-）：<回显非法值>` |
| `orgName` | 是 | 非空白；匹配 `^[A-Za-z0-9._-]{1,128}$`（与 V50 同一正则）；**并通过组织可访问性校验** | `组织「<org>」不存在，或该令牌的账号不是该组织成员、无权访问` |
| `enabled` | 否（默认 `true`） | 布尔 | —— |
| `note` | 否 | ≤255 字符 | `备注过长（≤255）` |
| `rotateToken` | 否（默认 `false`） | 布尔。`false` 且已有令牌 → **保留原令牌**；`true` 或当前无令牌 → `accessToken` 必填 | —— |

**为什么要回显非法值**：令牌与组织名都会被插进外部请求路径/请求头，运维需要立刻看到"到底哪个字符不合法"，而不是拿到一句泛化错误。

**`accessToken` 留空的两种成因必须分开报**（旧实现把 `null` 直接拼进文案，产出 `…不合法：null`）：

| 场景 | 判定条件 | 文案 |
|---|---|---|
| 本企业从未配置过企业令牌 | 无存量令牌 | `请填写访问令牌：本企业尚未配置企业令牌，首次初始化必须提供（留空仅适用于已配置令牌的企业）` |
| 显式开启轮换却未给新令牌 | `rotateToken=true` 且留空 | `访问令牌不能为空：本次提交开启了令牌轮换却未填写新令牌；若要沿用已有企业令牌，请留空且不轮换后提交` |

留空**不会静默成功**：平台不存在"共享企业令牌"可回落，能复用的只有本企业自己的令牌（`enterpriseToken` 只读本租户行）。前端据此把该字段按 `tokenConfigured` 动态设为必填，并在提交前本地拦截。

## 1.4 校验步骤（顺序执行，逐步记录，硬失败即中止）

| # | 步骤码 | 检查内容 | 失败时 |
|---|---|---|---|
| 1 | `GLOBAL_ENABLED` | 平台开关 `aioa.gitee.enabled` | 中止 |
| 2 | `TENANT_ENABLED` | 本企业开关（已关闭且本次未显式启用） | 中止 |
| 3 | `TOKEN_FORMAT` | 令牌格式（见 §1.3） | 中止 |
| 4 | `ORG_FORMAT` | 组织名格式 | 中止 |
| 5 | `TOKEN_VALID` | 用令牌调 `GET /user`，取回 `login` 作为 `token_owner` | 中止 |
| 6 | `ORG_ACCESSIBLE` | 用令牌调 `GET /orgs/{org}`；`404`→组织不存在/非成员；`403`→权限不足 | 中止 |
| 7 | `PERSIST` | 仅前面全通过才落库 + 写审计 | —— |

**与 V50 的关键差别**：V50 保存组织时的可见性探测是**建议性**的（探测失败也保存，因为普通组织成员本来就可能看不到组织）。而**初始化必须硬校验**：它是一次性的明确动作，静默成功比报错更有害。

## 1.5 成功处理

1. 落库：`org_name / enabled / note / access_token(加密) / token_owner / token_scope / init_status='ACTIVE' / init_at / init_by / org_verified=true / last_check_at`，`last_error` 清空。
2. 写 `audit_log`。
3. 返回状态视图 + `steps`（每步 `{code,label,ok,message}` 全为 ok）。
4. **能力即刻生效**：新建项目将使用该企业组织；组织级操作（建仓、配 Webhook）在发起人无个人令牌时**回落到企业令牌**。

## 1.6 失败处理（**不破坏既有可用配置**）

- **任何硬失败都中止，且绝不写入/覆盖可用的 `org_name`、`enabled`、`access_token`。**
- 此前**已有配置行** → 只把该行置 `init_status='FAILED'`、`last_error=<失败原因>`、`last_check_at=now`（留下痕迹供界面提示），其余字段一字不改；随后抛业务错误（HTTP 200 + `code≠0`）。
- **从未配置过** → **不落行**，直接抛业务错误。
- 前端：`ElMessage.error` 展示 `message`，并**立即刷新状态**，使 `lastError` 可见；用户可反复点「校验配置」（`/init/verify`，**永不落库**，连 `last_error` 都不写）先排错再正式初始化。
- **撤销**（`DELETE /gitee/init`）：清空令牌与 `org_verified`，`init_status='PENDING'`，清 `last_error`；**保留 `org_name` 与 `enabled`**（职责分离）；无可撤销内容时报业务错误，不静默成功。

## 1.7 企业令牌的定位（与既有设计原则的协调）

`GiteeAccountService` 的注释明确论证过「不让用户贴私人令牌」：私人令牌无法刷新、权限全量、用户无法自行撤销。**这条原则对"个人"依然成立，本设计并未推翻它**：

| 场景 | 用什么令牌 |
|---|---|
| 个人操作（成员增删、个人提交、内容读写） | **仍走个人 OAuth 绑定**（可刷新、可撤销、有 scope） |
| 组织级自动化（建仓、配 Webhook、后台同步任务） | 发起人无个人令牌时**回落企业令牌** |
| 初始化的校验调用 | 企业令牌 |

**必须实现的三条约束**：
1. 企业令牌**没有 `refresh_token`，绝不走既有 `validToken()` 的刷新逻辑** —— 直接返回原值。
2. 回落**只增路径、不改既有语义**：既无个人令牌也无企业令牌时，抛**与改动前完全相同的异常类型与消息**（既有 170 条 Gitee 断言依赖它）。
3. 企业令牌失效时给出**专属清晰错误**：`企业访问令牌已失效，请重新初始化`（包装在使用处，不改既有消息）。

## 1.8 接口清单（租户管理员；平台管理员可 `?tenantId=`）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/gitee/init` | 初始化状态视图（**绝不回传令牌明文或前缀**） |
| `POST` | `/api/v1/gitee/init/verify` | 只校验不落库（`{accessToken?, orgName}`）。**返回校验报告而非错误**：恒为 HTTP200 + `code=0`，body 含 `passed:boolean` + `steps[]` |
| `POST` | `/api/v1/gitee/init` | 执行初始化（`{accessToken?, orgName, enabled?, note?, rotateToken?}`）。失败走业务错误（`code≠0`，`message` = 失败步骤原因） |
| `DELETE` | `/api/v1/gitee/init` | 撤销企业初始化 |

**为什么 `/verify` 失败也要返回 `code=0`**：校验是一次**诊断**——接口成功执行了校验并报告"第 5 步没过"，这本身是一个**正常结果**，不是接口错误。若按业务错误返回，`data` 会被 `non_null` 序列化丢弃，前端拿到 `ApiError` 后**只剩一句字符串 `message`、丢掉结构化的 `steps`**，用户就看不到"到底哪一步失败、前几步是否通过"。因此：**诊断类接口返回报告，动作类接口才返回错误**。
（`POST /gitee/init` 是动作，失败必须 `code≠0`，并同时把原因写入 `last_error` 供界面回显。）

## 1.9 数据模型（V51）

`gitee_tenant_config` 追加列：`access_token`(加密) · `token_owner` · `token_scope` · `init_status`(默认 `PENDING`) · `init_at` · `init_by` · `last_error` · `org_verified` · `last_check_at`。
**不播种任何租户行** —— 与 V50 同理：留空才能持续验证"未初始化时回落平台默认"这条路径。

---

# 二、统一消息中心与多通道触达（P1-2）

## 2.1 现状与问题

- `notification` 表**只有站内单一通道**（`tenant_id/user_id/type/title/content/ref_id/read_at`，**无 channel 字段**）。
- 通知写入**分散在两处**：`aioa-resource` 的 `NotificationService.notifyUser/notifyAdmins`，以及 `aioa-org` 的 `ApprovalFlowService.notify(...)` —— 后者因为 **`aioa-org` 不依赖 `aioa-resource`**，是**用自己的 mapper 直插通知表**的。
- 后果：审批到了**只能靠用户主动登录才能看见**；投递是否成功**完全不可观测**。

## 2.2 设计（事件解耦 + 通道 SPI + 投递可观测 + 用户偏好）

**为什么用事件解耦**：`aioa-org` 与 `aioa-resource` 互不依赖，而两条写入路径都必须能被同一套分发逻辑覆盖。用 `aioa-common` 里的事件解耦是项目**已有先例**（`TenantProvisionedEvent` 由 `aioa-org` 发、`aioa-resource` 的 `WorkerTemplateProvisioner` 收）。

```
写入方(aioa-org / aioa-resource)
  └─ 先写站内信（既有行为不变，任何情况下都必须落库）
  └─ 再发布 NotificationRequested 事件（aioa-common）
        └─ aioa-resource: NotificationDispatcher 监听
              ├─ 读租户通道配置 + 用户偏好
              ├─ 逐通道投递（try/catch 隔离，单通道失败不影响其它通道，更不影响调用方）
              └─ 写 notification_delivery（每个通道一行：状态/次数/错误/时间）
```

**关键约束**：站内信写入**永远先做且必须成功**；通道分发**不得反噬调用方**（审批流程不能因为短信网关挂了而失败）。

## 2.3 通道与传输方式（含一条硬约束）

| 通道码 | 语义 | 传输 |
|---|---|---|
| `INAPP` | 站内信（既有） | 直接落库，恒可用 |
| `EMAIL` | 邮件 | **可配置 HTTP 邮件网关** |
| `SMS` | 短信 | **可配置 HTTP 短信网关** |
| `PUSH` | 移动推送 | **可配置 HTTP 推送网关** |

**为什么非站内通道统一走 HTTP 网关，而不是 SMTP/厂商 SDK**：
本项目是 **Spring Boot 3.3.5**，而本地 Maven 仓库只有 `spring-boot-starter-mail` **3.5.5**（版本不匹配），**离线环境无法解析 3.3.5 的邮件依赖 → 构建会失败**。硬加 JavaMail 会让整个构建不可复现。
因此统一走 HTTP 网关（项目里 `GiteeClient` 已用 JDK 自带 `java.net.http.HttpClient`，**零新增依赖**），这也正是政企环境对接企业微信/钉钉/短信网关/邮件网关的常见形态。
**后续项（已登记）**：若要直连 SMTP，需联网一次拉取 `spring-boot-starter-mail:3.3.5` 后再切实现；通道 SPI 已为此预留（新增实现类即可，不改分发逻辑）。

## 2.4 配置项与校验（启用通道时必填校验，失败即拒绝保存）

| 通道 | 必填配置 | 校验规则 |
|---|---|---|
| `EMAIL` / `SMS` / `PUSH` | `url` | 非空、以 `http://` 或 `https://` 开头 |
| 同上 | `token` | 非空（作为 `Authorization: Bearer` 或请求体字段，按网关约定） |
| `SMS` / `EMAIL` | `signName` / `from` | 非空（短信签名 / 发件人） |
| `PUSH` | `titleTemplate` | 可选（≤64） |
| 全部 | `config_json` | 仅允许已知键；未知键原样保留（**无损往返**，避免管理员"打开-保存"丢配置） |

**时间/重试**：单通道失败不阻塞其它通道；`notification_delivery` 记录 `attempts` 与 `last_error`；提供手动重试接口。

## 2.5 数据模型（V52）

- `notification_channel_config`：`tenant_id` + `channel_code` **UNIQUE**、`enabled`、`config_json`、审计列。
- `notification_delivery`：`tenant_id`、`notification_id`、`channel_code`、`status`(`PENDING`/`SENT`/`FAILED`/`SKIPPED`)、`attempts`、`last_error`、`sent_at`、审计列；索引 `notification_id`、`(tenant_id,status)`。
- `notification_preference`：`tenant_id` + `user_id` + `type`（`NULL`=该用户默认）+ `channels`(CSV)；`UNIQUE(tenant_id,user_id,type)`。

## 2.6 接口清单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/notifications/channels` | 租户管理员 | 通道列表与启用态 |
| `PUT` | `/api/v1/notifications/channels/{code}` | 租户管理员 | 保存（启用时按 §2.4 校验） |
| `POST` | `/api/v1/notifications/channels/{code}/test` | 租户管理员 | 发测试消息并返回真实投递结果 |
| `GET` | `/api/v1/notifications/deliveries` | 租户管理员 | 投递记录（可按状态/通知过滤） |
| `POST` | `/api/v1/notifications/deliveries/{id}/retry` | 租户管理员 | 单条重试 |
| `GET`/`PUT` | `/api/v1/notifications/preferences` | 本人 | 个人通道偏好 |
| **不变** | 既有 `GET/POST /api/v1/notifications*` | 本人 | **H5 与既有套件依赖，签名与行为保持不变** |

---

# 三、P1 其余三项的实施排期

## 3.0 为什么本轮只交付 P1-2

P1 的四项各自都是**独立子系统**（都要动数据库、后端、前端、回归）。本轮集中交付 **P1-2（统一消息中心）**，因为它是**唯一能彻底做完并且立刻见效**的一项，且它补的是"审批到了却没人知道"这种**已在生产造成实际影响**的缺口。
把四项都塞进一轮的结果只会是四个半成品 —— 而半成品比没做更糟（用户会以为能用）。**其余三项按下列拆解推进，未开工状态明确。**

## 3.1 P1-1 通用流程引擎 + 可视化表单/流程设计器（依赖最重，建议第二个做）

拆解（建议顺序）：
1. **表单模型层**：`form_def`（字段定义 JSON Schema 化）+ 渲染器（读写态分离）；
2. **流程模型层**：把现有 `approval_flow_def.steps_json` 升级为通用节点模型（保留兼容读取，**老流程定义不改**）；
3. **设计器**：拖拽表单设计器 + 流程画布（节点/连线/条件/会签，复用已有 `levels`/`cc` 语义）；
4. **运行时**：把现有审批运行时泛化为"业务单据 + 流程实例"，请假单作为**第一个迁移到通用模型的样例**；
5. **回归**：既有审批套件（`e2e_v39/v41/v43/v45` 等）必须全绿 —— **兼容性是本项的验收硬指标**。

预期作用：各局可**自助**定义报销/请示/备案等流程与表单，平台才算能承接真实业务，而非"只有一个请假单样例"。

## 3.2 P1-3 云文档/文件管理（与知识库打通）

拆解：存储抽象（本地/对象存储）→ 版本与历史 → 在线预览（按类型降级）→ 细粒度权限（复用既有三级作用域）→ **与知识库打通**（受权限约束的文档直接作为 RAG 数据源，不再另建副本）。
预期作用：补 OA 刚需的同时，让数字员工**在权限边界内**读取真实文档。

## 3.3 P1-4 日程 / 会议 / 考勤

拆解建议**先做会议+日程**（与既有待办/通知联动，收益最快），考勤视客户要求再做。
预期作用：把"AI 平台"用成"能日常办公的 OA"。
**注意**：本系统代码里的 `schedule` 关键字命中项是**定时任务**、`push` 是 **git push**，**都不是**日程/推送 —— 开工前勿误判为已有能力。

## 3.4 P1 之外与本轮同批的既有 P0 项（提醒）

报告 `artifacts/v51-repo-url-diagnosis.md` 的 P0 清单（链接配置自检 / 清理 `web-base-url` 死配置 / 刷新仓库信息接口 / 生产配置基线）**仍待办**，其中"生产配置基线"与本次 Gitee 初始化强相关，建议与 §1 一起上线。

---

# 四、验收方式

| 范围 | 方式 |
|---|---|
| §1 Gitee 初始化 | 新增 E2E：未初始化基线 / 格式非法（含回显）/ 令牌无效 / 组织不可访问 / 成功落库 / 失败不破坏既有配置 / 撤销 / 幂等 / 企业令牌回落建仓 |
| §2 消息中心 | 新增 E2E：通道配置校验 / 站内信不受影响 / 多通道投递记录 / 单通道失败隔离 / 重试 / 偏好 / 既有通知接口不变 |
| 无回归 | `e2e_v48_gitee`（116）· `e2e_v50_tenant_org`（54）· `verify_v51_repo_urls`（23）· `verify_v51_repo_urls_ui`（18）· `e2e_full_system --no-browser` · 管理端 `pnpm typecheck` 零错误 |
