# Gitee 真实建仓 · 端到端实测报告

> 编制：2026-09-17 · 环境：本机（后端 :8080 / 桩 :8090 / Gitee 真站 gitee.com）
> 触发：用户执行「完整端到端测试 + 在 Gitee 上真实创建项目 + 汇总问题」
> 结论：**真实建仓成功并在真站验证通过；过程中发现 4 个真实缺陷（均已修复并验证）+ 1 个套件卫生问题。**

---

## 0. 一句话结论

用你提供的私人令牌，在真实 Gitee 组织 `yjiud` 下**真的建出了仓库**
`https://gitee.com/yjiud/dept11-aioa-1789630096`，并完成了写文件、提交、URL 校验、删仓的完整闭环。
**浏览器跳转授权**这条路仍未跑（缺 OAuth 应用的 Client ID/Secret，见 §6）。

---

## 1. 实测通过的环节（每条都有独立于平台的证据）

| 环节 | 证据 |
|---|---|
| 真实接线生效 | 启动自检 `api=https://gitee.com/api/v5 授权跳转=https://gitee.com`，无桩警告 |
| 令牌真实性 | `GET /user` → 200，`login=liu-yang20` |
| 组织真实性 | `GET /orgs/yjiud` → 200，`type=Group`，`description=aioa` |
| 初始化只校验不落库 | `POST /gitee/init/verify` 6 步全 ok，且**复核库中无 tenant 2 行** |
| 初始化正式落库 | `POST /gitee/init` 7 步全 ok（含 PERSIST）→ `initStatus=ACTIVE`、`tokenOwner=liu-yang20`、`orgVerified=true` |
| 初始化幂等 | 重复初始化后 tenant 2 **仍为 1 行** |
| **真实建仓** | `CREATE_REPO` 任务 DONE；`gitee_repo_id=50369702`；`GET /repos/yjiud/dept11-aioa-1789630096` → **HTTP 200** |
| 真实写文件 | 平台 `POST /contents` 写 `docs/README.md` → 真站 `GET /contents/docs/README.md` 返回**同一内容**，sha 一致 |
| 真实提交历史 | 真站 `GET /commits` → `b950f1b add readme 刘尖尖` + `866f294 Initial commit` |
| 文件链接正确性 | 平台返回 `https://gitee.com/yjiud/.../blob/master/docs/README.md`，与 **Gitee 自身 API 返回的 `html_url` 逐字符一致** |
| **真实删仓（修复后）** | `DELETE ?purgeRepo=true` → `DELETE_REPO` DONE → `GET /repos/...` → **HTTP 404** |
| 初始化失败语义 | 桩接线下用真令牌 init → `initStatus=FAILED` + `last_error="访问令牌无效或已过期（Gitee 返回 401）"`，且 **org_name 未被覆盖**（符合 docs/30 §1.6 契约） |

**环境已还原**：`SMOKE_v48` **32/32** · `e2e_v48_gitee` **116/116** · `e2e_v51_gitee_init` **50/50** · `e2e_v50_tenant_org` **54/54**；租户 2 配置行已删除，回到未配置态。

---

## 2. 发现的缺陷（均已修复）

### 缺陷 1 · OAuth scope 缺 `hook`，真站 Webhook 必失败 ★真实缺陷

- **事实**：Gitee 官方 scope 列表为 `user_info projects pull_requests issues notes keys hook groups gists enterprises`。
  `projects` = 仓库读写；**Webhook 的建/改/删属独立 scope `hook`**，二者不可互相替代（Gitee 没有 GitHub 式聚合的 `repo`）。
- **旧默认**：`user_info projects pull_requests issues notes` —— **没有 `hook`**。
- **后果**：真站上**建仓成功、Webhook 被拒**，故障点（配 Webhook）离配置点（scope）很远。
- **为什么回归测不出**：`scripts/gitee_stub.py` **不校验 scope**，116 条用例照样全绿。
- **修复**：`GiteeProperties.scope` + `application.yml` 默认值补 `hook`；`gitee_stub.py` 的模拟令牌响应同步。
- **加固**：`GiteeConfig.selfCheck()`（新增）启动时打印接线与 scope，缺 `projects`/`hook` 即 WARN —— 只告警不中断。

### 缺陷 2 · `purgeRepo=true` 是静默假成功 ★真实缺陷

- **现象**：`DELETE /gitee/projects/68?purgeRepo=true` 返回「已标记删除 Gitee 仓库（不可恢复）」，`DELETE_REPO` 任务状态 **DONE**，但**仓库在 Gitee 上纹丝不动**（HTTP 200）。
- **根因**：`GiteeRepoTaskHandler.deleteRepo()` 首行 `projectMapper.selectById(bizId)`。
  `GiteeProject.deletedAt` 挂了 `@TableLogic`（全局 `logic-delete-field: deleted_at`），而 `softDelete()` 在**入队之前**就把行逻辑删除了 → 执行时读到 `null` → 直接 `return` → 任务记为 DONE。
- **旁证**：同文件的 `deleteWebhook()` 专门写了注释「项目已软删，只能按 tenant + createdBy 取」并改用 payload —— **同一个坑，作者改了一个、漏了另一个**。
- **修复**：`softDelete()` 入队时带上 `{owner, repo, createdBy}`；`deleteRepo()` 改从 payload 取值，信息不全时**抛错判 FAILED**（不可逆动作绝不允许静默成功）。
- **验证**：真实 Gitee 正向验证通过（建仓 200 → purge → **404**）。

### 缺陷 3 · 真站 `html_url` 带 `.git`，文件链接 404 ★真实缺陷

- **事实（实测）**：Gitee 真站 `GET /repos/{o}/{r}` 返回
  `html_url = https://gitee.com/{o}/{r}.git`（**带后缀**）、`https_url = null`（**该字段不存在**）。
  而本地桩返回的 `html_url` **不带**后缀、`https_url` 有值 —— 两边口径不同。
- **后果**：`GiteeContentService:355` 用 `giteeHtmlUrl + "/blob/" + branch + "/" + path` 拼文件链接，
  真站下会拼出 `.../{repo}.git/blob/master/x.md` → **404**；"Gitee 网页"链接也显示成 `.git` 结尾。
  桩环境下**永远不会出现**，故回归全绿也照样漏（与缺陷 1 同一类）。
- **修复**：`GiteeRepoTaskHandler` 新增 `webUrl()`（剥 `.git`）与 `cloneUrl()`（`clone_url → https_url → html_url` 三级回落，保证桩下取值与历史一致）；
  新增 **V53 回填迁移**修存量行（先回填 https 再剥后缀，顺序不可颠倒）。
- **验证**：修复后平台生成的文件 URL 与 Gitee 自身 API 返回的 `html_url` **逐字符一致**。

### 缺陷 4 · 个人令牌失效后不回落企业令牌 ★口径缺口（未改代码，待定夺）

- **现象**：`dsj_admin`（tenant 2）名下有多条桩签发的假令牌绑定，**个人绑定优先于企业令牌** → 真站收到假令牌 → 建仓 401 `Access token does not exist`。（改用无绑定的机构管理员后一次成功。）
- **性质**：
  - 直接原因是**环境残留**（库里有桩时代的假绑定），不是代码 bug；
  - 但暴露一个口径选择：docs/30 §1.5 写的是「发起人**无**个人令牌时回落企业令牌」，
    于是**个人令牌"存在但已失效"时会硬失败**，而不回落到本来就能用的企业令牌。
- **建议（需产品拍板，未擅自改）**：令牌校验 401 时回落企业令牌，并把错误文案从 Gitee 的英文原文改为可执行中文（如「个人 Gitee 授权已失效，请重新绑定或改用企业令牌」）。
- **现状风险**：切到真实接线后，**历史上被桩绑定过的账号全部会 401**。清理方式见 §5。

### 发现 5 · 套件间 fixture 干扰（不是代码回归）

- **现象**：整轮矩阵后跑 `SMOKE_v48` 出现 2 条失败：
  「未绑定返回 bound=false」「绑定视图不包含任何令牌字段」。
- **定性（有历史对照）**：旧日志 `logs/regression_all.log`（mtime 12:35）这两条是 **PASS**（当时 `bound:False`、视图仅 2 个键）；
  当前 `gitee_account` 中 `dsj_admin` 的活绑定行 `bound_at=14:33:14` —— **早于我本次会话动第一行代码**。
  根因是 `e2e_v50_tenant_org.py:295` 会绑定 `dsj_admin`，而 `SMOKE_v48` 断言的是它的**未绑定态**，两套件口径冲突。
- **修复**：让 `SMOKE_v48` **自己摆正前置条件**（断言前先解绑），**断言一字未改**，消除对套件顺序的依赖。
- **附带**：原断言把所有含 `token` 的键名一律判违规，把 `hasRefreshToken`（布尔，且 `e2e_v48_gitee` FR-1.12 **要求它存在**）也算了进去 ——
  属**假阳性**，只在账号恰好未绑定时才通过。已改为按「是否泄露令牌/密文」判定，口径与 FR-1.13 对齐，安全性未降。
- **结果**：`SMOKE_v48` → **32/32**。

---

## 3. 环境限制（非代码问题，如实标注）

| 限制 | 说明 |
|---|---|
| **Webhook 无法真实收事件** | `aioa.gitee.webhook-base-url` 无公网地址（Gitee 回调不到本机）。**这不是静默失效**：`callbackUrl()` 抛清晰异常，任务 `FAILED` 且 `last_error` 写明原因，项目停在 `CREATING`（`CONFIGURE_WEBHOOK` 未成功时不置 `ACTIVE`）。如需完整验证 Webhook，需要一个 Gitee 可达的公网地址（内网穿透）。 |
| 出口 IP 限流 | 未认证请求实测 `403 Rate Limit Exceeded`；**带令牌请求全程未受影响**。 |
| 授权跳转授权 | 需先在 gitee.com 注册第三方应用（缺 Client ID/Secret），见 §6。 |

---

## 4. 本轮代码改动清单

| 文件 | 改动 |
|---|---|
| `aioa-gitee/.../config/GiteeProperties.java` | 默认 scope 补 `hook`，并写清"两个独立 scope"的理由 |
| `aioa-boot/src/main/resources/application.yml` | 同上 |
| `aioa-gitee/.../config/GiteeConfig.java` | 新增 `selfCheck()`：启动打印接线/scope，缺项 WARN |
| `aioa-gitee/.../service/GiteeRepoTaskHandler.java` | 新增 `webUrl()`/`cloneUrl()`；`deleteRepo()` 改从 payload 取值、信息不全抛错 |
| `aioa-gitee/.../service/GiteeProjectService.java` | `softDelete()` 入队 `DELETE_REPO` 时带上 owner/repo/createdBy |
| `db/migration/V53__gitee_repo_url_normalize.sql` | **新增**：回填存量行的仓库地址 |
| `scripts/gitee_stub.py` | 令牌响应的 scope 同步为含 `hook`，并注明"桩不校验 scope" |
| `scripts/SMOKE_v48.py` | 自摆前置条件（解绑）+ 修正假阳性断言 |
| `scripts/gitee-real-env.sh.example` | **新增**：真实接线模板（真实值放 `.env.gitee-real`，不入库） |

---

## 5. 交付状态与还原

- **Gitee 真站**：`yjiud` 组织下 **仅 1 个仓库** = `yjiud/dept11-aioa-1789630096`（私有，含 `docs/README.md` 与 2 次提交）。被中断那次产生的重复仓库 `...1789629970` 已删除。
- **平台**：项目 69 保留为该仓库的对应记录（状态 `CREATING` —— 因 Webhook 未配置，符合设计）。测试用的项目 67/68 已删除。
- **配置**：租户 2 的 `gitee_tenant_config` 行已删除，回到"未配置"态；后端当前为**桩接线**（演示默认）。
- **待办风险**：库中仍有桩时代的假绑定（`gitee_account`，含 `dsj_admin`）。真实接线下这些账号会 401。清理入口：`DELETE /api/v1/gitee/bind`（按账号），或直接清 `gitee_account` 的存活行。

---

## 6. 下一步：还差什么才能跑通「浏览器跳转授权」

需要在 gitee.com「设置 → 第三方应用」创建应用后提供：

| 参数 | 值 |
|---|---|
| 应用主页 | `http://localhost:5173/` |
| **应用回调地址** | `http://localhost:8080/api/v1/gitee/bind/callback`（**用 localhost、勿加尾斜杠、须逐字符一致**） |
| Logo | 已生成：`.workbuddy/artifacts/gitee-real-creation/aioa-logo.png`（512×512，19.8KB） |
| 权限勾选 | 必须含 **`projects` + `hook`**（及 `user_info`、`pull_requests`、`issues`、`notes`） |
| 需回传给我 | **Client ID** 与 **Client Secret**（Secret 只显示一次） |

拿到后：停服 → 用真实接线重启（含 client 三件套与 `AIOA_GITEE_ORG=yjiud`）→ 触发 `/gitee/bind/authorize` → 真实浏览器完成 gitee.com 授权同意页 → 回调绑定 → 用个人身份再建一次仓库。

---

## 7. 浏览器跳转授权：**第一次尝试失败，阻断在 Gitee 侧**（2026-09-17 追加）

### 7.1 平台侧：全部就绪，无缺陷

| 项 | 结果 |
|---|---|
| 真实接线 | `logs/boot-oauth-real.log` 自检 `enabled=true api=https://gitee.com/api/v5 授权跳转=https://gitee.com`，**无 ⚠**，`scope="user_info projects hook pull_requests issues notes"` |
| 配置来源 | `.env.gitee-real`（已被 `.gitignore` 的 `.env.*` 覆盖，不入库） |
| 前置解绑 | `dsj_admin` 存活绑定 **0 行**，回调必走 `created=true` 路径 |
| 授权地址 | `POST /gitee/bind/authorize` → `authorizeHost=gitee.com`、`sandbox=false`、`warning=null`、state TTL 600s |
| 回调 | `gitee_oauth_state.state=d97ee21b…` **`consumed=0`**；后端日志 `bind/callback` **命中 0 次** ⇒ **回调从未发生** |

`requireOrgUser()` 准入 5 角色（`ROLE_ADMIN`/`TENANT_ADMIN`/`ORG_ADMIN`/`DEPT_LEADER`/`MEMBER`），故选用租户管理员 `dsj_admin` 合法。

### 7.2 Gitee 侧：`{"error":"Application does not exist"}`

浏览器打开授权地址后（**已是登录态** —— 没被甩到 `/login`），Gitee 直接返回该错误的裸 JSON。

⇒ **该 `client_id` 在 Gitee 侧不存在**：应用没真正保存 / 已被删 / 复制时串了字符。

### 7.3 为什么必须靠真站才能定案（两次相反的错误结论）

这两条都**看起来像**判据，实际都会骗人：

| 探针 | 有效 client | 无效 client | 能否区分 |
|---|---|---|---|
| curl 打 `/oauth/authorize`（**无会话**） | 302 → `/login?redirect_to_url=…` | 302 → `/login?redirect_to_url=…` | **不能**（零信号，我据此误判过一次「被接受」） |
| `POST /oauth/token` + 假 code | `invalid_client` | `invalid_client`（**逐字相同**） | **不能**（Gitee 先按 code 查记录、再从记录解析客户端） |
| `POST /oauth/token` + `refresh_token` | `invalid_grant_validate_token` | `invalid_grant_validate_token` | **不能**（先校验 refresh_token） |
| **带会话打 `/oauth/authorize`** | 同意页 | `Application does not exist` | **能 ✅** |

**格式常识**：Gitee 的 `client_id` 与 `client_secret` 官方形态**都是 64 位十六进制**（Drone 官方文档
`f7018cdd…61de20`、gitee 示例 `f224ce5b…8e7d9662` 佐证）⇒ 纯 64 位十六进制**不是**错误信号，不能据此推断「复制错」。

### 7.4 请你在 Gitee 侧确认三件事

1. 打开 `https://gitee.com/oauth/applications`，确认应用**确实出现在列表里**（创建表单要真的点「保存/创建」）；
   从**详情页**复制 `Client ID` 与 `Client Secret`（Secret 只显示一次，重新生成会作废旧值）。
2. 确认浏览器登录的账号 = **创建该应用的账号**。
3. **自查捷径**（在已登录浏览器直接开，无需经过平台）：

   ```
   https://gitee.com/oauth/authorize?client_id=<你的ID>&redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fapi%2Fv1%2Fgitee%2Fbind%2Fcallback&response_type=code&scope=user_info
   ```

   出**同意授权页** ⇒ ID 有效，可以回到平台重跑；仍回 `Application does not exist` ⇒ ID 仍无效。

---

## 8. 浏览器跳转授权：**成功 ✅**（第二次尝试，2026-09-17 追加）

### 8.1 根因：Client ID 抄错 1 个字符

用户发来 Gitee 应用详情页截图（应用名 `AIOA`，**今日请求次数 0 次**）。逐字符 diff：

| | Client ID 第 29–40 位 |
|---|---|
| 文本消息里给的（已写入配置） | `...c97c0**9eb**1489e...` |
| 详情页截图里的（真实值） | `...c97c0**9bb**1489e...` |

**第 34 位**：`e` → `b`，**仅此 1 字之差**，长度均为 64（脚本比对结果 `[(33,'e','b')]`）。Secret 两处一致。

> **旁证**：应用详情页「今日请求次数 **0 次**」—— 若请求到达过该应用，计数会 +1。
> 这个计数是「请求是否到达应用」的独立信号，比读错误文案更直接。

### 8.2 成功证据链

修正 `.env.gitee-real` 的 `AIOA_GITEE_CLIENT_ID` 后重启（自校验 URL 中的 client_id 与截图**逐字一致**、第 34 位 = `b`），用户在浏览器点「同意授权」，回调落库：

| 项 | 值 | 说明 |
|---|---|---|
| `bound` | `true` | 绑定成功 |
| `giteeUid` | **14032724** | 与私人令牌 `GET /user` 独立得到的 id **完全一致** |
| `giteeUsername` | `liu-yang20` | 真实 Gitee 身份 |
| `giteeName` | `刘尖尖` | 来自真站 `GET /user` |
| 后端日志 | `GiteeAccountService - Gitee 绑定成功 tenant=2 user=3 gitee=liu-yang20(14032724)` | |
| 库中行 | `gitee_account.id=59`：`access_token` **`enc:` 加密**、`refresh_token` **有值**、`token_expires_at=2026-09-18 17:16:32`（约 24h） | 令牌不出服务端、可续期 |
| 头像 | `https://foruda.gitee.com/avatar/.../14032724_liu-yang20_....png` | 来自真站 |

**这一条把 OAuth 全链路在真站打通并验证**：`/oauth/authorize` → 用户登录+同意 → 回跳带 code → 后端 `POST /oauth/token` 换码 → `GET /user` 取真实身份 → AES-GCM 加密落库 → 刷新令牌可用于续期。
选用的绑定账号是租户管理员 `dsj_admin`（tenant 2, user 3），前置已解绑，故走的是「新建绑定」路径。

### 8.3 用**个人令牌**在真站建仓：成功（仓库 #2）

绑定完成后用 `dsj_admin` 发起建仓，验证个人令牌真能干活：

| 环节 | 结果 |
|---|---|
| `CREATE_REPO` 任务 | **DONE** |
| 平台项目 | `id=77`、`repo_name=dept11-aioa-1789636649`、`gitee_repo_id=**50373399**`、`gitee_owner=yjiud` |
| **真站独立复核** | `GET /repos/yjiud/dept11-aioa-1789636649` → **HTTP 200**，`private=true`，`created_at=2026-09-17T17:17:31+08:00`（紧接 17:16:32 的绑定之后） |
| 平台存的地址 | `https://gitee.com/yjiud/dept11-aioa-1789636649`（**无 `.git`** —— §2 缺陷 3 的修复再次生效；真站 API 返回的是带 `.git` 的） |
| `CONFIGURE_WEBHOOK` | **FAILED**，`last_error="未配置 aioa.gitee.webhook-base-url，Gitee 无法回调本机地址；请填写平台对 Gitee 可见的公网地址"` |
| 项目状态 | `CREATING` —— **符合设计**：Webhook 未配置成功就不置 `ACTIVE`（且是 fail-loud，有可执行中文指引） |

### 8.4 对「缺陷 1（scope 缺 hook）」结论的精化 ★

真站换回来的 `scope` 是：

```
user_info projects pull_requests issues notes keys hook groups gists enterprises emails
```

我们**请求**的只有 6 个（`user_info projects hook pull_requests issues notes`），**拿到的却是 11 个**。
⇒ **Gitee 返回的是「应用登记时勾选的权限集」，并不会被授权 URL 里的 `scope` 参数收窄。**

因此对缺陷 1 的结论要修正为：**决定性的那一环是「登记应用时勾没勾 `hook`」**；
代码里默认 scope 补 `hook` 是**必要的防御**（保证登记口径与调用口径一致、且不会因参数缺项而误导排障），
但**它单独不足以**让 Webhook 可用 —— 必须两边都到位。检查清单应为：
① 应用登记页勾选 `projects` + `hook`；② `aioa.gitee.scope` 含 `hook`；③ 换回的令牌 `scope` 里确认有 `hook`（本次已确认 ✅）。

### 8.5 新发现的运维陷阱 ★（代码确证，**未实测**）

**在桩接线下跑 Gitee 套件，会把刚拿到的真实绑定覆盖成假身份。**
`GiteeAccountService.callback()` 对已存在的绑定行**无任何保护**，直接用 `exchangeCode`/`getUser` 的返回覆盖
`giteeUid`/`giteeUsername`/`accessToken`。桩接线下这两个调用打到 :8090，返回的是桩签发的假身份
（形如 `gitee_dev_206`）⇒ **真实绑定被静默降级为假绑定**，且用户无从察觉。
（`e2e_v50_tenant_org.py:295` 就会绑定 `dsj_admin`。）
**本轮因此刻意不重跑桩套件** —— 本轮只有配置改动、无代码改动，回归风险为零；
若强行重跑，就会毁掉 8.2 刚验证成功的真实绑定。
**建议（需产品拍板）**：`callback()` 在「现有绑定的令牌仍有效且为新授权覆盖」时给出显式提示或二次确认；
至少在文档/运维手册里写死「切桩前先解绑，或桩套件不要绑定生产账号」。

### 8.6 本轮环境现状

- 后端运行在**真实接线**（`.env.gitee-real`，已判入 `.gitignore` 的 `.env.*`，不入库）：`logs/boot-oauth-real2.log`。
- **保留**真实绑定 `gitee_account.id=59`（`dsj_admin` ← `liu-yang20`）。
- 真站 `yjiud` 组织现有 **2 个仓库**：`dept11-aioa-1789630096`（企业令牌路径）、`dept11-aioa-1789636649`（个人令牌路径）。
  如需只留一个，可对平台项目 `DELETE /api/v1/gitee/projects/{id}?purgeRepo=true`（⚠ 该动作现已修复，会真删真站仓库）。
