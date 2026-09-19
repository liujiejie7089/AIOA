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

