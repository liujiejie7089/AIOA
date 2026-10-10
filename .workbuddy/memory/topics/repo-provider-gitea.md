# 托管方抽象（Gitee -> Gitea）

> 摘自 `MEMORY.md §7`（2026-09-19 拆分）。规格见 `docs/29/30`。

## 7. 托管方抽象（Gitee → Gitea）
- `RepoProviderClient`（`aioa-gitee/client/`，21 方法）是上层唯一依赖，8 个服务只注入接口；`RepoProviderException` 中立基类；**勿删 `providerName()` 的 Gitee 覆写**（文案会变）。开关 `aioa.repo.provider`（默认 `gitee`），两实现**互斥装配**（`@ConditionalOnProperty`；Gitee 侧 `matchIfMissing=true`）⇒ **条件写反 = 整个应用起不来**（`RepoProviderWiringTest` 守住）；改配置**必须重启**。
- `RepoProviderSettings` 让 11 处调用点一行未改（访问器名与 `GiteeProperties` getter 完全相同）。三类取数规则：① **协议类随 provider 切**（org / webhook-base-url / webhook-secret / redirect-uri / oauth-authorize-base-url / token-enc-key / repo-name-max-length）；② **运行参数仍取 `aioa.gitee.*`**；③ **OAuth 报错与警示文案随 provider 变且必须指名当前 provider 的属性键**。
- **5 条硬分歧**：① 建仓 `name`/`path` 双字段 vs 单 `name`；② Webhook 校验 **Gitee 明文共享密钥** vs **Gitea HMAC-SHA256**（`X-Gitea-Signature` 无前缀 / 兼容 `X-Hub-Signature-256` 带 `sha256=`；**须用原始字节**算，不能先 getReader；**校验在托管方实现里，控制器只收 `byte[]`、不得 if/else 分流，日志只记头名不记头值**）；③ 事件名下划线风格 + 子串包含 ⇒ 必须**归一化 + 精确映射表**；④ OAuth 路径与 scope 词表全不同；⑤ 分页 `per_page`→`page`+`limit`（Gitea 硬上限 50）。**翻页结束条件必须是「本页为空」**，不能写「本页条数 < 请求条数」（Gitea 请求 100 实回 50 会被误判末页 ⇒ 第 2 页起静默丢失）；另加「整页与上页相同即停」。**桩/替身必须忠实**（`gitee_stub.py` 已加 `_paginate()`）——**替身越宽容越会替真实服务掩盖缺陷**。
- `/gitee/config` 是界面文案唯一来源（回 `provider`/`providerLabel`/`configKey`/`tokenRequirementHint`）；前端整页文案按 `providerLabel` 渲染，回落值取 `'Gitee'`（保 Gitee 桩套件旧锚点不漂移）。
- **判据铁律**：`extractMessage()` 必须 **`errors[]` 优先**（Gitea 的 `message` 可能是内部操作名如 `GetUserByName`），落库前过 `support/ProviderFailureText`（中文归因+动作在前、托管方原文附尾）。⚠️ **Gitea「协作者用户不存在」回 422（不是 404）、重复添加回 204** ⇒ `isAlreadyCollaborator()` **绝不能把 422 一律当成功**（旧写法 = 假绿），判据必须「4xx **且**文案明确说已是协作者」。OAuth 换令牌错误体人话在 `error_description` ⇒ `firstDetail()` 优先它并保留 `error`。`client_secret` 可能「登记页显示的值永远校验不过」（判据三分，唯解 = **新建应用**，`POST /user/applications/oauth2` 的**创建响应**才返回明文；当前有效 `client_id=a2e8f7bd-8f0b-4a2f-a1e5-345b5741b0cd`）。**`/oauth/authorize` 不接受私人令牌**，Gitea 也不支持 `client_credentials` ⇒ 浏览器那半程必须由人完成。
- **源码审计三条**（`RepoProviderNeutralityTest`）：① 服务层不得 `catch (GiteeApiException)`；② `gitee_account` 条件查询必须带 `getProvider`；③ `service|controller|support` 下 `Gitee `（含句中写法）只准出现在注释或 `log.*`。
- **切 provider ⇒ 既有令牌不可解密是预期行为**（两段各一个 `token-enc-key`），需重新授权绑定，**不是 bug**。原实现只在 `acc == null` 时回落 ⇒ 建项目 500；现 `decryptTolerant()`：解不开 = 本平台下没这条绑定 → 回落企业令牌。**V54**：`gitee_account` 加 `provider` 列，唯一键并入 `provider`+`gitee_uid` ⇒ 一个用户可同时持有两个身份；漏 provider 过滤的症状 = 建项目 500 / 拿异平台登录名加协作者 404（**同步静默失败**）。
- **沙箱回调覆盖真实绑定的守卫**：`GiteeAccountService.clobberRealBinding()` + `STUB_UID_CEILING=1_000_000`（桩签发 5 位 uid，真实账号 8 位）。⚠️ 该常数依赖「桩 uid 5 位」，桩若改 8 位会把桩套件全拦红。
- **同一时刻只许起一个后端实例**（两实例共库会互抢任务队列）；`AIOA_GITEE_SYNC_ENABLED=false` **只停 cron，不停 worker**。**不要用真实接线跑 `e2e_full_system`**（会在真实组织上真建仓留残留），必须在桩接线下跑。
- **Gitea 1.26.2 实测契约**：默认分支 `main` · Webhook `secret` **只写不读** · 请求 4 事件实际落 **14 个**（断言用**子集**）· `/hooks/{id}/deliveries` → 404 · SSH 端口 **2222** · 协作者 `PUT` 需 **JSON body**（query 形式 422）。详见 `.workbuddy/artifacts/gitea-api-contract-1.26.2.md`。
- **真机验证配方**：`e2e_gitea_live.py`（81 条，自净）· `_check_gitea_ui_provider.py`（17 条，自净，其 L3「整页不出现 Gitee」是**数据面**哨兵，回填文案被它抓红过）· `_check_gitea_cfg_failure_ui.py`（16 条，自净）。⚠️ **两套接线不能同时接**（`e2e_gitea_live`/`_check_gitea_*` 要真机接线 `.env.gitea-real`；`e2e_v48_gitee`/`e2e_v51_gitee_init`/`e2e_full_system` 要**桩接线** `scripts/gitee-e2e-env.sh`）；切换只需重启后端、**不用重新打包**；跑完必须切回真机接线。⚠️ 改断言/改可见文案后**连跑两次**。
- 接线文件（gitignored）：`.env.gitee-real` / `.env.gitea-real` → `set -a && . ./.env.gitea-real && set +a` + 启动 jar。关键项：`AIOA_REPO_PROVIDER=gitea` · `AIOA_GITEA_BASE_URL=http://172.16.8.249:3000/api/v1`（**必须带 `/api/v1`**）· `AIOA_GITEA_ORG=AI-OA` · `AIOA_GITEA_WEBHOOK_BASE_URL`（**必须 Gitea 能访问到**）。
- ⚠️ **真机专属限制：Webhook 入站不可达**（本机两层 NAT 无回程路由），出站全正常；套件用「本地构造报文 + 正确 HMAC 直投平台端点」，验的是**协议正确性**，**不等于网络可达性**。
- **仍叫 `Gitee` 的地方**（有意保留）：`log.*` 文案、类名、`gitee_*` 表名 —— 改名属纯重构。

## 真实 Gitee（gitee.com）接线现状（2026-10-09 实测）

- **建仓已通**：租户 2 的真实组织 `yjiud`（Gitee org id 17016656，desc `aioa`）可正常建仓；
  `dsj_admin` 的个人绑定就是真实账号 `liu-yang20`（uid 14032724，scope 含 `projects`+`hook`）。
- **企业令牌非必需**：`GiteeTokenService.requireAccessToken` 先取**个人绑定**，解不开才回落企业令牌
  （`gitee_tenant_config`）。故租户 2 `init_status=PENDING`/`tokenConfigured=false` **不影响建仓**。
- **个人令牌过期会自动刷新**：`tokenExpired=true` 但 `hasRefreshToken=true` 时，一次真实调用即刷新；
  只读端点是探活好办法：`GET /gitee/projects/{id}/branches`（真数据 = `master @ <sha>`）。
- ★**唯一阻塞 = Webhook 回调地址**：`aioa.gitee.webhook-base-url` 留空 ⇒ `GiteeRepoTaskHandler.callbackUrl()`
  抛 `IllegalStateException` ⇒ webhook 步 `markFailed(项目)`。**建仓其实已成功**，但项目停在 FAILED/未就绪
  （租户 2 现状：FAILED 10 / DELETED 39 / **ACTIVE 0**，error_msg 逐条指向 webhook-base-url）。
  回调路径固定 `{base}/api/v1/gitee/webhook/{项目id}`。**本机 127.0.0.1 不可能被 Gitee 回调** ⇒
  本地环境无法满足该步，必须给公网/内网穿透地址；配好后对失败项目点「重试建仓」只补跑 webhook 步。
- **界面完善（提交 `e46f845` / `de3f8c8`）**：`/gitee/config` 的 `webhookBaseUrlConfigured` 此前**前端从未消费**，
  管理员只有拿到 FAILED 项目才知道；现已在**两处**告警：「仓库配置」页顶部 +
  PM 项目详情「代码仓库」页签（仅 DEV；FAILED 行正在这里被看到）。
  哨兵 `scripts/_verify_gitee_webhook_hint.py`（**5 项**）：断言「界面提示 ⟺ 后端 flag」，
  两页各自与后端取数比对（本机 false / 配好 true 都有区分力）；已跑负向自检证明判据非恒真。

## 平台参数「管理端动态配置」（V77，2026-10-10 实装）

> 需求原话：「需要配置 gitee 参数的，在仓库配置中进行动态配置，**不要写死代码**」。
> 目标：平台级 Gitee 参数不再依赖 env/代码，改在**管理端「系统配置 → 仓库配置」**页可改，**保存即生效**。

- **表 `gitee_platform_config`**（迁移 `V77`，按 provider 单例）：9 列全可空，**NULL=回落 env，空串=显式清空**
  （逐字段覆盖，不用「整行覆盖」——避免首次保存就把 env 里的 secret 静默遮蔽）；`enabled` 刻意可空。
- **9 个可覆盖字段**：`enabled/clientId/clientSecret/redirectUri/oauthAuthorizeBaseUrl/scope/org/webhookBaseUrl/bindReturnUrl`。
- **刻意排除**（迁移头注释写明理由）：`token-enc-key`（解密根，改=已存令牌全解不开）、`base-url`/`web-base-url`
  （部署身份）、`webhook-secret`（每仓随机更安全）、需重启的调参项。
- **接线**：`config/PlatformConfigOverlay`（**无依赖内存持有者**，打破循环：服务→overlay←适配器）+
  `RepoProviderSettingsAdapter`（先读覆盖层，NULL 回落 `giteaActive()?gitea:gitee`）+
  `service/GiteePlatformConfigService`（`bootLoad`+`ApplicationReadyEvent` 载入、`save/clear` 后
  `reloadAndView` 立即回填、Secret 走 `GiteeCrypto` 加密落库、**任何视图都不回明文**只回 `clientSecretConfigured`）+
  `GiteeController` 三端点 `GET/PUT/DELETE /gitee/platform-config`（`PermissionCatalog.isPlatformAdmin`）。
  `/gitee/config` 新增 `oauthConfigured`（横幅判断数据化）。前端卡片只在**平台管理员**可见，
  且**放在 `moduleEnabled` 守卫之外**（它才是开总开关的地方）；字段标签由后端 `fields` 元数据下发。
- **收口**：哨兵 `scripts/_check_gitee_platform_config.py`（静态 **10** + `--selftest` + `--api` 往返 **12**）；
  单测 `PlatformConfigOverlayTest`（5）；已登记 `_run_all_regression.sh`；指南 `deploy/GITEE-两套环境配置指南.md` §3.5。
  ⚠ 该哨兵 S6 曾用**子串匹配**（`baseUrl` 撞 `webhookBaseUrl`）⇒ 已改词表精确匹配。
- **本轮实测**：新 jar 重启后启动日志出 `来源=环境变量（管理端覆盖 0 项）`；`--api` 静态 10/10 + 往返 12/12；
  收尾表无覆盖行、配置回落到 env。
- **生产边界**：服务器 `10.0.0.3:22`（可出网、外网进不来）→ 隧道机 `219.151.186.24:22`（可出网、可进服务器）；
  agent 无隧道凭据 ⇒ **不能代部署**，运行期改配置正是生产的正确路径。

### ★ 2026-10-10 死锁修复（务必别回退）
「平台参数」卡曾**被渲染在 `moduleEnabled` 守卫之内**（`<template v-else>` 那支），而注释与 `onMounted`
都声称它在守卫之外 —— 结构自相矛盾。后果：模块 `enabled=false`（生产默认）时横幅显示、**这张「开总开关」的卡
不渲染** ⇒ 管理端永远开不了它。已改为独立分支 `v-if="isPlatformAdmin && !configError"`，
原那支改为 `<template v-if="!configError && moduleEnabled">`。
**由哨兵 S11 钉死**（`_check_gitee_platform_config.py`，静态 11 项；退化自检会变红）。
编译期判据：渲染函数里卡片条件是 `(_ctx.isPlatformAdmin && !_ctx.configError) ? …`，**不含 moduleEnabled**。

### ⚠ 「已经部署了」的证伪法（本轮实证）
生产 `mall.egoaicloud.com` **从本机可达**（`/aioa/api/v1/*` 未认证 401 = 链路通）。
**直达生产取三样证据**即可判定部署物是否含某改动：①管理端入口 hash → 拉其懒加载块 grep 该特性**独有中文串**；
②**新端点是否 404**；③**既有端点是否出现本轮新加的字段**。
本轮三者全为「旧」（入口 `index-CvJ9IgLI.js`、`/gitee/platform-config` 404、`/gitee/config` 无 `oauthConfigured`）
⇒ 生产前后端都不含该特性；而该特性当时**全未提交**，本地 HEAD 与 `github/main` 同为 `772a2a9` ⇒ git 式部署不可能带上。
**别用后端下发的文案做前端探针**：「平台总开关」是 `FIELD_META` 里的**后端**标签，前端包 grep 不到（第一版即因此误判）。

### `webhook-base-url` 到底填什么（反复被问，2026-10-10 定案）
- **只填基址**，不要自己带 `/api/...`：`GiteeRepoTaskHandler.callbackUrl()` =
  `去尾斜杠(base) + "/api/v1/gitee/webhook/" + 项目id`；`isPlatformHook()` 也按同一前缀识别自家钩子。
- **生产（单端口入口）= `https://mall.egoaicloud.com/aioa`** —— 与 `deploy/.env.production:155` 的
  `AIOA_GITEE_WEBHOOK_BASE_URL` **同值**；结尾带不带 `/` 都行（代码会剥掉一个）。
- 本地**留空**即可（Gitee 回调不到 `127.0.0.1`，Webhook 这步必然失败，属预期、非 bug）。
- 该路径已在免认证白名单：`SecurityConfig.PUBLIC_ENDPOINTS` 含 `/api/v1/gitee/webhook/**`（`permitAll`）
  ⇒ Gitee 不带令牌也能回调进来，这条不需要额外配。
- ★ 存量 `.env.production` 里**本来就填对了**，但生产 `GET /gitee/config` 实测四个 flag
  （`enabled`/`orgConfigured`/`webhookBaseUrlConfigured`/`oauthConfigured`）**全为 false**
  ⇒ **生产的 env 并没有把 Gitee 段真正传进容器**；改用管理端页面配（保存即生效）可绕开这个环境问题。
- 该字段的页面提示已改写为「只填基址：后端会自动在其后追加 /api/v1/gitee/webhook/{项目id}…」
  （原提示只说「必须是公网地址」，不回答「填什么」）；指南 §3.5 亦补了同内容的「填什么」小节。


### ★ 2026-10-10 空 `client_id` 缺陷：客户端绕过端口（本次修复，勿回退）
**症状**：用户绑定 Gitee、登录后回 `{"error":"Application does not exist"}`。
抓到的授权 URL = `https://gitee.com/oauth/authorize?client_id=&redirect_uri=…` —— **`client_id=` 为空**。

**根因**：管理端「仓库配置」页把 client-id 存进了 `gitee_platform_config`（页面 `configured=true`、
`adminOverridden=9`、来源 `ADMIN`），但 `GiteeClient.authorizeUrl()` **直读原始 `GiteeProperties` bean**
（只含**环境变量**值，生产 env 又没传进容器 ⇒ 空），**绕过了「管理端覆盖层 → 回落环境变量」的
`RepoProviderSettings` 端口** ⇒ 页面改的是这个值、真正发出去的是另一个值。同一缺陷也存在于
`GiteaProviderClient`（其 `props.oauthAuthorizeUrl()` 同样从原始 bean 派生授权域）。

**修复（单一决策点）**：两个客户端对**可覆盖字段**一律改走端口 `settings.*`
（`getClientId` / `getClientSecret` / `getRedirectUri` / `getOauthAuthorizeBaseUrl` / `getScope`）；
`GiteaProviderClient` 的授权页改为 `trimSlash(settings.getOauthAuthorizeBaseUrl()) + "/login/oauth/authorize"`。
**不可覆盖项仍取原始 bean**：`getBaseUrl` / `getWebBaseUrl`（部署身份）、`getHttpTimeoutSeconds`、
分页/限速、`getRepoNameMaxLength`、TLS。为此给端口**新增 `getClientSecret()`**（此前刻意只暴露
`clientSecretConfigured()`）；`@PostConstruct` 自检的 `GiteaConfig` 也改读端口（否则日志打印 env 值、与行为不符）。
调用链：`GiteeOauthController @PostMapping("/authorize")` → `GiteeAccountService`（按接口注入
`RepoProviderClient`）→ `authorizeUrl()` → 端口。

**收口证据**：
- 单测 `GiteeAuthorizeUrlTest`（**4 项**）：①管理端配了 client-id ⇒ URL 带上它（且不含 `client_id=&`）；
  ②**负向对照**：不配就是 `client_id=&`（证明判据有效）；③Gitea 授权域/client-id 亦走端口；
  ④端口暴露 secret 的**值**。**已做负向验证**：把 `settings.getClientId()` 改回 `props.getClientId()`
  → 该用例如期变红（不是恒真）。
- 静态哨兵 `scripts/_check_gitee_platform_config.py` **新增 S12**（客户端可覆盖字段不得直读原始 bean），
  含退化自检（把一处改回 `props.` → 变红）；静态 **11 → 12/12**。
- `aioa-gitee` 全模块单测 **174/174 通过**（含更新后的 3 个老测试 + `RepoProviderWiringTest`）。

### 顺带修的两处缺陷
1. **中立性审计早就是红的**（`RepoProviderNeutralityTest.userFacingCopyMustNotHardcodeProviderName`）：
   `5e38135` 引入的 `FIELD_META` 提示里 `"真实 Gitee 为…"` / `"Gitee 的 hook…"` 写死了托管方名，
   本轮的 `afb268e` 又加了一处 `"必须是 Gitee 能访问到的公网地址"`（把原本**刻意中立**的「托管方」改成了「Gitee」）。
   已按该测试的**本意**改文案（`官方站点填…`；`托管方能访问到…`；`props.providerLabel() + " 的 "`），
   **没有放宽任何断言**。
   ⇒ 教训：`5e38135` 提交后**没跑该模块单测**，红着的套件被推了上去；改「用户可见文案」必须重跑此审计。
2. **哨兵 `--api` 会毁真实 Secret**：原 `A8` 用假值覆盖 `clientSecret`，而 Secret **读不回明文**，
   复原路径整段**排除**该字段 ⇒ 既可能毁掉生产凭据，也可能把「未配置」伪装成「已配置」。
   已改为：**原本已配置则只读校验**（不回写）；原本未配置才写假值，且复原时**显式清空**（空串＝显式清空）。
   ⇒ 结论：**不要对持有真实凭据的在线后端跑 `--api` 的旧版本**。
