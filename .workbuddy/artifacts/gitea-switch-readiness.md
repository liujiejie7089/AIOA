# Gitee → Gitea 改造 · 交接单

> 2026-09-18 · 仓库 `C:/Users/刘尖尖/WorkBuddy/aioa`
> 配套：`gitea-live-verification.md`（**真机跑通报告，先看它**）· `overview.md` §7 · `gitea-api-contract-1.26.2.md` · `gitee-to-gitea-migration.md`

---

## 一、现在的状态：**真机流程已跑通，可切；只剩「入站 Webhook」受网络限制**

- 默认 `aioa.repo.provider=gitee` ⇒ **现有部署行为逐字节不变**（真机 Gitee 绑定 `liu-yang20` 可用）。
- 切成 `gitea` 只需**改环境变量 + 重启**，不用改代码（见 §六）。
- `企业管理 → 项目管理` 在真机 Gitea 上端到端通过（`scripts/e2e_gitea_live.py` **75/75**），
  且**界面实渲染核对**通过（`scripts/_check_gitea_ui_provider.py` **17/17**）—— 页面文案不再谎报托管方，
  同步失败也会给出中文归因与可执行动作。
- **唯一未闭环**：Gitea 主动回调平台这一段受「本机在 NAT 后、且防火墙未放行」限制，
  详见 `gitea-live-verification.md` 第三节（含 traceroute / 投递计数证据）。

## 二、已完成

| # | 事项 | 关键点 |
|---|---|---|
| 269 | `RepoProviderClient` 契约 | 8 个业务服务只注入接口；中立异常基类；Gitee 文案逐字未变 |
| 270 | 事件映射子串 bug + 真分页 | `pull_request` 曾整类丢成 OTHER、`issue_comment` 曾被抢成 ISSUE；分页结束条件改「本页为空」 |
| 271 | `GiteaProviderClient` 完整实现 | Gitea 1.26.2；`@ConditionalOnProperty` 互斥装配；默认仍是 gitee |
| 272 | Webhook 校验 + OAuth 分支中立化 | 校验下移到托管方实现（HMAC vs 明文）；控制器收 `byte[]` |
| 273 | `RepoProviderSettings` 设置端口 | 11 处原先直读 `GiteeProperties` 的点收口 |
| 274 | 沙箱覆盖真实绑定的守卫 | 桩接线的 OAuth 回调不得覆盖真实令牌 |
| 275 | **真机验证** | 探针跑遍全部用到的 Gitea 端点，抓出 3 个真机缺陷（见 §三） |
| 276 | **默认分支随托管方** | Gitea 1.26.2 实测 `auto_init` → `main`（非 `master`）；写死会让读写文件全 404 |
| 277 | **异常类型中立化** | 服务层不得 `catch (GiteeApiException)`（Gitea 抛中立基类 → 分支不可达），加源码审计守 |
| 278 | **`gitee_account` 加托管方维度（V54）** | 绑定行按平台归属；否则会把 Gitee 的身份/密文当成 Gitea 的用 |
| 279 | **切托管方后不回落企业令牌 → 建项目 500** | 解密失败按「本平台无此绑定」处理并回落；文案指名当前生效的密钥键 |
| 280 | `scripts/e2e_gitea_live.py` 真机套件 | 75 条断言，自净（删项目连带删远端仓库） |
| 281 | **界面/文案托管方中立** | 端口加 `providerLabel()`/`configKeyPrefix()`/`tokenRequirementHint()`；`/gitee/config` 成前端文案唯一来源；前端两页按 `pName` 渲染；后端 13 处用户可见文案改拼接；加源码审计守 |
| 282 | **删项目后成员同步任务空转** | `project == null`（终态）直接作废，只有「仓库未建出」才重试 |
| 283 | **失败原因「说人话」** | `extractMessage()` 改为 `errors[]` 优先（Gitea 的 `message` 可能是内部操作名 `GetUserByName`）；新增纯函数 `ProviderFailureText`（中文归因 + 动作 + 原文附尾）；两个落库点改走它 |
| 284 | **422 被误判成「已是协作者」→ 成员假绿** | 判据改为「4xx 且文案明确说已是协作者」；Gitea 对不存在的用户回 422，旧逻辑会把没权限的成员标成 SYNCED |
| 285 | **失败原因字段清不掉**（MyBatis-Plus 静默失效） | `errorMsg`/`lastError` 显式 `updateStrategy = ALWAYS`；默认 `NOT_NULL` 会把 null 排除在 `SET` 外，「清空」一直是空转 |

### 本轮最值得看的一条：**「客户端契约」≠「配置中立」≠「数据归属中立」**

三轮下来踩的是**同一条河的三处**，每处都「编译能过、启动能起」：

1. `RepoProviderClient` 只管「**怎么调**平台接口」；
2. `RepoProviderSettings` 管「平台侧**配置长什么样**」（组织/回调基址/密钥），原先散落 11 处直读 `GiteeProperties`；
3. **`gitee_account` / `gitee_tenant_config` 里存的令牌**是「**哪个平台签发的**」——
   这一层最隐蔽：它不体现在配置里，而体现在**数据**里。切 provider 后老数据既解不开、
   又与远端语义不符（Gitee 的登录名在 Gitea 上不存在）。

第 3 层本轮补齐：`provider` 列 + 查询过滤 + V54 迁移（老行回填 `gitee`）。

## 三、修掉的 7 个真机缺陷（详见 `gitea-live-verification.md` 第二节）

| 缺陷 | 症状 | 修法 |
|---|---|---|
| 老绑定密文解不开且**不回落企业令牌** | `POST /gitee/projects` → **500**；`AEADBadTagException: Tag mismatch` | 解密失败→按「本平台无此绑定」处理→回落企业令牌；无企业令牌才报错，且文案指名当前密钥键 |
| `gitee_account` 无托管方维度 | 异平台登录名被拿去 Gitea 加协作者 → **404 静默失败**；同用户无法并存两平台绑定 | **V54**：加 `provider` 列 + 唯一键并入 `provider`/`gitee_uid` + 查询按 provider 过滤 |
| 密钥报错说错配置键 | gitea 下让用户去改 `aioa.gitee.token-enc-key` | `tokenEncKeyProperty()` 随 provider |
| **整页界面文案写死「Gitee」** | 页头/卡片/表头/按钮/Toast/结果页全写「Gitee」，而仓库地址指向 Gitea；「未启用」提示让改 `aioa.gitee.*`；初始化说「令牌需 `projects` 权限」 | 端口加 `providerLabel()`/`configKeyPrefix()`/`tokenRequirementHint()`；`/gitee/config` 成前端文案唯一来源；前端两页按 `pName` 渲染；后端 13 处文案改拼接 |
| **删项目后成员同步任务空转** | 队列残留 `PENDING/attempts=5`，指向已 `DELETED` 的项目 | `project == null`（终态）直接作废；只有「仓库未建出」才重试 |
| **失败原因把托管方原文抛给用户** | 成员表/项目详情上显示 `GetUserByName`、`Rate Limit Exceeded`、`401 Unauthorized: ...` | `errors[]` 优先（人话在 `errors[]`，`message` 可能是内部操作名）；`ProviderFailureText` 按状态给中文归因+动作，原文附尾 |
| **422「用户不存在」判成「已是协作者」** | 成员显示绿色「已同步」，实际对仓库**没有权限**（假绿） | 判据改为「4xx 且文案明确说已是协作者」；Gitea 重复添加回 204，不走该分支 |

同轮另修一个静默失效：「清空失败原因」（`setErrorMsg(null)`）在 MyBatis-Plus 默认
`update-strategy=NOT_NULL` 下一直是空转 ⇒ `errorMsg`/`lastError` 显式 `updateStrategy = ALWAYS`。

## 四、我已自行拍板并写进配置的（都是可逆的，要改请说）

| 事项 | 我的默认 | 理由 |
|---|---|---|
| 中文仓库展示名 | `repo-name-source=AUTO`：优先 `path`（保 URL 为 ASCII），为空回落 `name` | Gitea 只有一个 `name` 兼作 URL 片段 |
| 是否保留 Gitee | **保留**（两个实现互斥并存，默认仍是 gitee） | 抽象成本已付；并存对信创/私有化是卖点，也不废已真机验证过的 Gitee 链路 |
| TLS 自签证书 | 优先 `trust-store` 导入自签 CA；`insecure-skip-verify` 仅作最后手段且启动打 WARN | 前者不削弱安全性 |
| 仓库级团队同步 | **暂不实现** | Gitea 无对应物（只有组织级且语义反转） |
| 老绑定处置 | 不自动清理，**保留**并在查询时按 provider 过滤跳过 | 老绑定是审计事实；自动删数据不可逆 |

## 五、验证证据（全部实测）

| 验证 | 结果 |
|---|---|
| `aioa-gitee` 单测 | **136/136**（含 providerName / providerLabel / configKeyPrefix / tokenEncKeyProperty / 令牌权限提示 / 异平台密文文案 / 失败文案映射 20 条 / 已是协作者判据 6 条 / 三类源码审计） |
| `e2e_gitea_live`（真机） | **75/75**，0 FAIL，0 BLOCKED |
| `_check_gitea_ui_provider`（浏览器实渲染） | **17/17** |
| `e2e_v51_gitee_init` | **50/50** |
| `e2e_v48_gitee` | **116/116** |
| `e2e_full_system --no-browser` | **145/145**（已知缺口 0 项） |
| 真机产物 | 项目 `ACTIVE`、仓库 `AI-OA/dept11-*` 存在、`default_branch=main`、`hook active=true`、删项目后远端仓库 404；队列 `PENDING+RUNNING=0`；`AI-OA` 下只剩 `AIOA_FrontWeb` |
| V54 迁移 | `Successfully applied 1 migration, now at version v54`；74 条老绑定回填 `provider='gitee'` |
| 收口接线 | 后端以 `.env.gitea-real` 运行：`provider=gitea` · `providerLabel=Gitea` · `configKey=aioa.gitea` |

## 六、切过去的操作要点

- 只需环境变量：`AIOA_REPO_PROVIDER=gitea` + `AIOA_GITEA_ENABLED=true` +
  `AIOA_GITEA_BASE_URL`（**必须带 `/api/v1`**）+ `AIOA_GITEA_WEB_URL` /
  `AIOA_GITEA_OAUTH_AUTHORIZE_URL` / `AIOA_GITEA_CLIENT_ID` / `..._SECRET` /
  `..._REDIRECT_URI` / `..._ORG` / `..._WEBHOOK_BASE_URL`。**改完必须重启**。
  现成模板：`.env.gitea-real`（gitignore）。
- ⚠️ **切换会让既有个人绑定不可用**（两段各有一个默认加密密钥）——有意设计（令牌按平台签发）。
  但**不再阻塞**：个人绑定不可用时自动回落**企业令牌**，企业令牌本身需重新 `POST /gitee/init`。
- ⚠️ **同一时刻只起一个后端实例**：两个实例共库会互抢任务队列，
  现象是「项目卡 `CREATING` + 套件大片红」，而**失败在另一个实例的日志里**。
  （`AIOA_GITEE_SYNC_ENABLED=false` **只停 cron，不停任务 worker**。）
- ⚠️ **`AIOA_GITEA_WEBHOOK_BASE_URL` 必须是 Gitea 能访问到的地址**；填本机内网地址时
  建仓与配钩子都会成功，但**事件永远不会进来**（本机即此情形）。
- ✅ 跑桩接线回归不再需要手工备份 `gitee_account`：覆盖守卫会拦下「用桩身份覆盖真实绑定」。
