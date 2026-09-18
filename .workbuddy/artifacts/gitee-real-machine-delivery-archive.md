# AIOA · Gitee **真机建仓**端到端实测 — 交付概览

> 编制：2026-09-17 · 范围：在**真实 gitee.com**上完成「初始化 → 建仓 → 写文件 → 提交 → 删仓」闭环，并汇总真实缺陷
> 详细报告：`.workbuddy/artifacts/real-gitee-e2e-report-v2.md`
> 上一轮（P1 消息中心 + 企业初始化）交付：`.workbuddy/artifacts/p1-delivery.md`

## 1. 一句话结论

用你给的私人令牌，在真实 Gitee 组织 `yjiud` 下**真的建出了仓库**
**`https://gitee.com/yjiud/dept11-aioa-1789630096`**（`gitee_repo_id=50369702`，私有，`master`），
写文件 / 提交 / URL 校验 / 删仓全部在真站验证通过。
过程中揪出 **3 个桩环境永远测不出的真实缺陷**（均已修复并回真站验证）+ 1 个套件卫生问题。
**还差一步**：浏览器跳转授权需要你先在 Gitee 注册第三方应用并给我 Client ID / Secret（见 §5）。

## 2. 实测跑通的链路（每条都有独立于平台的证据）

| 环节 | 证据 |
|---|---|
| 真机接线生效 | 启动自检 `api=https://gitee.com/api/v5 授权跳转=https://gitee.com`，无桩警告 |
| 令牌真实性 | `GET /user` → 200，`login=liu-yang20` |
| 组织真实性 | `GET /orgs/yjiud` → 200，`type=Group`，`owner=liu-yang20` |
| 初始化只校验不落库 | `/gitee/init/verify` 6 步全 ok，且**复核库中 tenant 2 无行** |
| 初始化正式落库 + 幂等 | `/gitee/init` 7 步全 ok → `ACTIVE` / `tokenOwner=liu-yang20`；重跑仍 **1 行** |
| **真实建仓** | 任务 DONE；`GET /repos/yjiud/dept11-aioa-1789630096` → **HTTP 200** |
| 真实写文件 | 写 `docs/README.md`，真站回读**同一内容、sha 一致** |
| 真实提交历史 | 真站 `GET /commits` → `b950f1b add readme 刘尖尖` |
| 文件链接正确性 | 平台返回 URL 与 **Gitee 自身 API 的 `html_url` 逐字符一致** |
| **真实删仓** | `purgeRepo=true` → 真站回读 **HTTP 404** |
| 失败语义 | 桩接线下用真令牌 init → `FAILED` + 中文 `last_error`，且 `org_name` **未被覆盖** |

## 3. 发现并修复的真实缺陷

1. **`purgeRepo=true` 是静默假成功**（已修）— `deleteRepo()` 对已软删行 `selectById` 读到 `null` 直接 `return`，
   任务记 DONE 但真站仓库还在。改为从 payload 取值、信息不全**抛错判 FAILED**。
   → 沉淀为通用纪律：**「先软删、再异步入队执行」的动作，执行段不得 `selectById`**。
2. **真站 `html_url` 带 `.git` 后缀、`https_url` 字段不存在**（已修）— 文件链接会拼成 `.../{repo}.git/blob/...` → 404。
   新增 `webUrl()` / `cloneUrl()` + **V53 回填迁移**。
3. **OAuth scope 缺 `hook`**（已修）— Gitee 的 `projects`（仓库）与 `hook`（Webhook）是**两个独立 scope**，
   旧默认缺 `hook` ⇒ 真站**建仓成功、Webhook 被拒**。已补默认值 + 启动期接线自检（缺项只 WARN 不中断）。

**待你拍板（未改代码）**：个人令牌**存在但已失效**时不会回落企业令牌 → 建议 401 时回落并改中文文案。

## 4. 验收与环境还原

- 回归全绿：`SMOKE_v48` **32/32** · `e2e_v48_gitee` **116/116** · `e2e_v51_gitee_init` **50/50** · `e2e_v50_tenant_org` **54/54**
- 真站 `yjiud`：**恰好 1 个仓库**（无残留）；平台保留记录 项目 69（状态 `CREATING`，因 Webhook 无公网基址未配置，符合设计）
- 平台已还原：租户 2 配置行**已删除**（回到未配置态）；后端当前为**桩接线**（演示默认）

## 5. 浏览器跳转授权：**已跑通 ✅**

第一次回 `{"error":"Application does not exist"}`，根因是 **Client ID 抄错 1 个字符**（第 34 位 `e`→`b`）。
修正后用户在浏览器点「同意授权」，**回调成功落库**：

| 项 | 值 |
|---|---|
| 绑定账号 | `dsj_admin`(tenant 2) ← **`liu-yang20`**（`giteeUid=14032724`，与私人令牌独立取到的 id 一致） |
| 令牌 | `gitee_account.id=59`，AES 加密落库、refresh 有值、有效期 ~24h |
| 个人令牌真机建仓 | `CREATE_REPO` **DONE**，`gitee_repo_id=50373399` → 真站 `GET /repos/...` **HTTP 200** |

**全链路真站打通**：authorize → 登录+同意 → 回跳 code → 换令牌 → 取真实身份 → 加密落库 → 可续期。

⚠️ **注意**：`CONFIGURE_WEBHOOK` 仍 FAILED（本机无公网回调地址，`webhook-base-url` 为空），
项目因此停在 `CREATING` —— 这是**设计如此**（fail-loud，`last_error` 有可执行中文指引），不是缺陷。

⚠️ **~~别在此时跑 Gitee 桩套件~~ —— 该警告已于 2026-09-18 解除**：原先 `GiteeAccountService.callback()`
对已有绑定行没有保护，桩接线下会把这条**真实绑定覆盖成假身份**（`e2e_v50_tenant_org.py:295` 正会绑 `dsj_admin`）。
现已加**守卫**（#274）：沙箱回调用「看起来是真实账号」的 uid 覆盖既有绑定时**直接拒绝**，
并给出可执行中文报错。已用「假真实行」在桩接线下**实测拦截成功且行未被覆盖**（见 §7.2）。

真站 `yjiud` 组织现有 **2 个仓库**：`dept11-aioa-1789630096`（企业令牌路径）、`dept11-aioa-1789636649`（个人令牌路径）。
后端当前运行在**真实接线**（`.env.gitee-real`，不入库）。

## 6. 环境限制（非代码问题，如实标注）

- **Webhook 无法真实收事件**：`webhook-base-url` 无公网地址，Gitee 回调不到本机。**但不是静默失效** —
  抛清晰异常、任务 `FAILED`、项目停在 `CREATING`。要完整验证需内网穿透。
- **切真接线的硬前置**：库中存活 `gitee_account` 全是桩时代的假令牌（6 行），真接线下**会全部 401**，需先清理。

---

## 7. 后续：Gitee → Gitea 改造已开工（2026-09-18）

> 详细契约：`.workbuddy/artifacts/gitea-api-contract-1.26.2.md` · 工作量评估：`.workbuddy/artifacts/gitee-to-gitea-migration.md`

**已完成（编译 + 单测双绿）**

| # | 事项 | 结果 |
|---|---|---|
| 269 | 抽取 `RepoProviderClient` 接口 | 21 方法契约 + 中立异常基类；**8 个注入点全部改为依赖接口**；Gitee 文案逐字不变 |
| 270 | 修事件映射子串 bug + 真分页 | `pull_request` 曾整类丢成 OTHER、`issue_comment` 曾被抢成 ISSUE —— 均已修；**红绿实证 7 处失败 → 复绿** |
| 271 | 实现 `GiteaProviderClient` | 完整 Gitea 1.26.2 实现 + `GiteaProperties`/`GiteaConfig`；**provider 开关互斥装配，默认 gitee，现有部署行为不变** |
| 272 | Gitea 侧 Webhook 校验 + **OAuth 分支中立化** | 接收侧：校验改由托管方承担（`verifyWebhook`）+ 报文改 `byte[]`，已部署并在真实服务上验证 9/9。OAuth 侧：本轮**发现并修复了「设置面没中立化」**（详见 §7.2） |
| 273 | **抽出 `RepoProviderSettings` 设置端口** | 8 个业务类 + 2 个控制器原先直读 `GiteeProperties`；切 gitea 后会读到**空组织/空回调基址/错密钥**且编译期无提示。新增端口 + 适配器，**调用点形态不变**，仅换声明类型 |
| 274 | **沙箱回调覆盖真实绑定的守卫** | 桩接线的 OAuth 回调会把真实令牌换成假身份，且两条路径都返回「绑定成功」、事后无从分辨。原先只能靠「跑桩套件前先备份再比对」绕开，人一忘就出事。现由纯函数 `clobberRealBinding()` 拦截，**已在桩接线下实测** |

**新增保障**

- `aioa-gitee` **首个 Java 单测**（此前为零）：**98/98 绿**
  —— `GiteeWebhookEventClassifyTest` 31 例（Gitee + Gitea 两种事件命名风格）
  · `GiteaProviderRequestBodyTest` 29 例（请求体静默失效陷阱）
  · `RepoWebhookVerifyTest` 21 例（HMAC 校验，期望值用 **Python `hmac` 独立算出**，非回填自测）
  · `RepoProviderWiringTest` 3 例（托管方实现互斥装配）
  · `RepoProviderSettingsTest` 8 例（**设置端口分流**：切 gitea 后协议类设置必须取 gitea 段、
    运行参数必须仍取 gitee 段、报错文案必须指名当前 provider 的属性键）
  · `GiteeAccountClobberGuardTest` 6 例（沙箱覆盖真实绑定的四种组合，逐一钉死）。
- 桩服务 `gitee_stub.py` 原先**忽略 `page`/`per_page`**、每次回全量 —— 配上新翻页逻辑会累积 20 份重复。已加 `_paginate()` 按真实语义切片。

## 7.1 本轮验证证据（全部实测，非推断）

| 验证 | 期望 | 实测 |
|---|---|---|
| 模块单测 | 全绿 | **98/98** |
| `e2e_v48_gitee` | 116 | **116/116** |
| `e2e_v51_gitee_init` | 50 | **50/50** |
| `e2e_full_system --no-browser` | 145 | **145/145**（+7 渲染段 = 152）|
| **守卫实拦**（桩接线 + 假真实行） | 拒绝覆盖且行不变 | 回调返回失败页「…拒绝用它覆盖已存在的真实绑定：原 uid=14032724，本次 uid=42364…」，**行 uid 未被改写**，测试后已还原 |
| 零凭据探针 `POST /gitee/bind/authorize`（provider=gitea） | 产出 Gitea 授权地址 | `http://172.16.8.249:3000/login/oauth/authorize?...&scope=repo read:organization notification issue` |
| 配置面是否真中立（provider=gitea） | 取 gitea 段 | `config.webhookBaseUrlConfigured=true`（来源 `aioa.gitea.webhook-base-url`） |
| fail-loud 告警（Gitea，授权域≠网页域） | `sandbox=true` + 指名 `AIOA_GITEA_OAUTH_AUTHORIZE_URL` | ✅ 命中 |
| fail-loud 告警（Gitea，两端同域） | `sandbox=false`（用户确实到达真实例） | ✅ 命中 |
| 恢复真实接线 | 无桩警告 | `[gitee] 接线：api=https://gitee.com/api/v5 授权跳转=https://gitee.com` |
| 真实绑定未被破坏 | `bound=true` | `liu-yang20` / uid 14032724 / `tokenExpired=false`；租户 2 队列 `PENDING=0 RUNNING=0` |

## 7.2 本轮新发现并修复的缺陷

1. **（真缺陷，已修）授权地址仍在读 Gitee 段** —— 切 `provider=gitea` 后
   `POST /gitee/bind/authorize` 返回 `code=400`
   「Gitee OAuth 应用未配置（缺 aioa.gitee.client-id / client-secret）」，
   **gitea 接线根本绑不上**。根因：`GiteeAccountService.assertBindable()` 与授权警示文案
   直接读 `GiteeProperties`，而「客户端契约」只覆盖了「怎么调接口」，没覆盖「配置长什么样」。
   → 抽出 `RepoProviderSettings` 端口（#273）后 **红→绿实证**：`code=400` → `code=0` 且 URL 正确。
   同一根因还波及建仓/Webhook/初始化等 8 处（组织、回调基址、签名密钥、令牌密钥），一并收口。

2. **（验证方法缺陷，已固化进技能 §0.12）双实例会互抢同一个任务队列** ——
   为做 Gitea 探测在 `:8081` 另起实例（以为 `AIOA_GITEE_SYNC_ENABLED=false` 能关掉它），
   结果它把 `:8080` 队列里的 `CONFIGURE_WEBHOOK` 抢走、用 Gitea 段密钥解 Gitee 令牌而失败，
   套件大面积看起来像「设置面改造打断了建仓链路」。
   **`SYNC_ENABLED=false` 只停 cron，不停任务 worker**；正解是同一时刻只起一个实例。
   已写入 `.workbuddy/skills/aioa-e2e-regression` §0.12 / §4.5。

3. **（已澄清，非缺陷）`GiteaProviderClient.authorizeHostIsSandbox()` 一开始看着像恒 false** ——
   实为我的探测配置让授权域与网页域同域。该判据对自建实例只能以 `web-base-url` 为参照，
   两端同域返回 `false` 是**正确的**；换域名后立即命中警告。

4. **（长期靠绕开的风险，已修）沙箱回调会覆盖真实绑定** —— 这条从 2026-09-17 起就写在交付说明里，
   但一直只是「跑桩套件前先备份、事后比对」的操作纪律，本轮我靠它绕了三次。
   覆盖后真实令牌被换成桩签发的假令牌，而**两条路径的返回都叫「绑定成功」，事后无从分辨** ——
   属于不可逆的数据损坏，靠人的记性守不住。已加守卫（#274）：
   沙箱回调 + 既有行看起来是真实账号（uid ≥ 10^6）+ uid 不同 ⇒ **拒绝**并给可执行报错。
   桩套件不受影响（桩行 uid 为 5 位）；真实授权域的换号重绑仍是合法操作、不拦。
   失效方向为 fail-open；彻底修法是给绑定行加 `sandbox` 列如实标注来源（列为后续项）。

**内网 Gitea 实测（环境结论已更正）**

`172.16.8.249:3000` **沙箱可达**（1.26.2，此前「不可达」结论作废）。公共接口免认证可读，
故 API 形态已自证并锁定到字段级；但**仓库/组织/用户级全需令牌**。

## 7.3 下一步真正需要你提供的东西（只有两项，其余我都已自行决定）

1. **一个 Gitea 令牌**（`repo` + `organization` 权限）—— 这是仓库级操作唯一的硬阻塞。
   有了它我就能把「建仓 → 写文件 → 建 Webhook → 同步成员」按真机标准跑一遍，
   并把 `GiteaProviderClient` 从「单测级」提升到「真机验证级」。
   另请告知仓库该建在哪个**组织**下（实例上目前只看到 `huimao` 一个公开组织；
   `liujiejie` 是用户不是组织）。若贵方也希望走**浏览器授权**而不是私人令牌，
   请再给一个 Gitea OAuth 应用的 `client-id` / `client-secret` 及回调地址登记。
2. **公网可达的 Webhook 回调地址** —— Gitea 只能回调它自己能访问到的地址，
   本机/内网地址都不行。没有它，Webhook 会像 Gitee 那条链路一样停在 `CREATING`
   （fail-loud，不是静默失败，但无法完成端到端验证）。
   注：这一项与上面第 1 项**独立** —— 即便给了令牌，没有公网回调地址也验不了事件接收。

**我已自行拍板并写进配置的（如需改动请说，都是可逆的）**

| 事项 | 我的默认 | 理由 |
|---|---|---|
| 中文仓库展示名 | `repo-name-source=AUTO`：优先 `path`（保 URL 为 ASCII），为空回落 `name` | Gitea 只有一个 `name` 兼作 URL 片段，AUTO 是破坏性最小的口径；想保留中文可切成 `NAME` |
| 是否保留 Gitee | 保留（两个实现互斥并存，默认仍是 gitee） | 抽象成本已付；并存对信创/私有化是卖点，且不做废已真机验证过的 Gitee 链路 |
| TLS 自签证书 | 优先 `trust-store` 导入自签 CA；`insecure-skip-verify` 仅作最后手段且启动打 WARN | 前者不削弱安全性；后者关闭服务端身份校验，必须留审计痕迹 |
| 仓库级团队同步 | **暂不实现**（Gitea 无对应物，只有组织级且语义反转） | 硬套会得到语义不符的结果；需要的话应重新设计而非照搬 |
