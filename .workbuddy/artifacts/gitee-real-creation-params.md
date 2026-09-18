# 在 Gitee 上真实建仓 · 需要你提供的参数清单

> 编制：2026-09-15 · 依据：`docs/30-企业Gitee主动初始化与统一消息中心.md` §1.3、`GiteeController`、`GiteeProperties`、`application.yml`
> 当前状态：本地跑的是 **桩接线**（`POST /gitee/bind/authorize` 实测回显 `authorizeHost=127.0.0.1`、`sandbox=true`）。桩接线下的"建仓成功"是本地 Gitee V5 桩伪造的，**不等于真实 Gitee**。

---

## 0. 一句话结论

真实建仓**只需要你给 2 个参数**：一个 **Gitee 访问令牌** + 一个 **组织名（org login）**。
其余（切接线、重启服务、调接口、轮询、打开仓库页验证）都由我这边做，**不需要改一行代码**。

---

## 1. 必需参数（最小集合）

| # | 参数 | 说明 | 从哪里拿 |
|---|---|---|---|
| 1 | `accessToken` | Gitee 访问令牌。**需勾选 `projects`（仓库读写）权限**；若要配 Webhook 还需 `projects` 覆盖 hooks。 | gitee.com → 头像 → 设置 → **私人令牌**（个人令牌）；或企业/组织的访问令牌 |
| 2 | `orgName` | 仓库要建在哪个 **Gitee 组织**的 login（不是中文显示名）。令牌所属账号必须**是该组织成员且有建仓权限**。 | 组织主页 URL `gitee.com/<这里就是 orgName>` |

**校验规则（服务端硬校验，不通过直接中止）：**

| 参数 | 规则 |
|---|---|
| `accessToken` | 非空白；长度 **8~512**；不含空白字符；正则 `^[A-Za-z0-9._\-]{8,512}$`；**且必须通过 Gitee 实测**（`GET /user` 取回 `login`） |
| `orgName` | 非空白；正则 `^[A-Za-z0-9._-]{1,128}$`；**且必须通过组织可访问性实测**（`GET /orgs/{org}`；404=组织不存在/非成员，403=权限不足） |

> 注意：规则里**不允许空格**。Gitee 的令牌本身是字母数字串，一般天然满足；如果你用的是带特殊符号的自建令牌，需要先确认。

---

## 2. 可选参数（不提供也能建仓成功）

| 参数 | 缺省行为 | 什么时候需要 |
|---|---|---|
| `webhookBaseUrl` | 留空 → Webhook 配置会失败（**不影响仓库本体创建**，仅 Webhook 状态为失败） | 你希望 Gitee 能真实回调到平台时，需要一个 **Gitee 可访问的公网地址**（如 `https://aioa.example.com`）。`127.0.0.1` 无效 |
| `webhookSecret` | 留空 → 每仓库随机生成（更安全） | 需要所有仓库共用同一回调密钥时 |
| `enabled` | `true` | 临时关闭某租户联动 |
| `note` | 空 | ≤255 字符备注 |
| `rotateToken` | `false` | 已有令牌、这次只想改组织名 → 留空令牌；想换令牌 → `true` 且必须重填 `accessToken` |

---

## 3. 第二条路径（可选）：个人 OAuth 绑定

若你希望走**真实浏览器跳转授权**（而不是企业令牌），额外还需要：

| 参数 | 说明 |
|---|---|
| `clientId` / `clientSecret` | 在 gitee.com → 设置 → **第三方应用** 创建一个 OAuth 应用后给出 |
| `redirectUri` | 应用登记的回调地址，**必须与服务端 `aioa.gitee.redirect-uri` 完全一致**，默认 `http://localhost:8080/api/v1/gitee/bind/callback` |
| `scope` | 需含 `projects`（默认值 `user_info projects pull_requests issues notes` 已含） |

> 这条路径参数更多、还要登记回调；**只做"真实建仓"的话走第 1 节就够了**（企业令牌会在个人未绑定时自动回落使用，见 `GiteeTokenService.enterpriseToken`）。

---

## 4. 我方负责、不需要你提供的东西

| 项 | 现状 |
|---|---|
| 切到真实 Gitee 接线 | **默认值本来就是真实 Gitee**（`base-url=https://gitee.com/api/v5`、`oauth-authorize-base-url=https://gitee.com`）。当前是**桩接线**（由 `scripts/gitee-e2e-env.sh` 注入 9 个环境变量造成）→ 我重启服务时不注入这些变量即可 |
| 代码改动 | 不需要 |
| 建仓接口 | `POST /api/v1/gitee/projects`，body `{name, departmentId, description?, visibility?}` + 后台异步任务完成建仓 |
| 初始化接口 | `POST /api/v1/gitee/init`，body `{accessToken, orgName, enabled?, note?, rotateToken?}` |
| 只校验不落库 | `POST /api/v1/gitee/init/verify`（先排错，永不写库） |
| 验证 | 轮询 `GET /api/v1/gitee/projects/{id}` 直到 `status=READY`，用真实 HTTP 打开返回的仓库 URL 取 200，并截图留证 |

---

## 5. 你提供参数后，我将执行的步骤

1. 用真实接线重启后端（不注入桩环境变量），确认 `POST /gitee/bind/authorize` 回显 `authorizeHost=gitee.com`、`sandbox=false`。
2. 用租户管理员登录（`dsj_admin` / `User@123`，租户 t2），调 `POST /api/v1/gitee/init/verify` 先跑一遍**只校验**（令牌有效性 + 组织可访问性），把 `steps` 逐步结果给你看。
3. 校验全绿后调 `POST /api/v1/gitee/init` 正式落库（`init_status=ACTIVE`）。
4. 调 `POST /api/v1/gitee/projects` 建仓 → 轮询项目状态至 `READY`。
5. 用真实 HTTP 请求打开仓库 URL 确认 200（必要时真实浏览器打开截图），并检查 Webhook/成员/双提交链路状态。
6. 汇总报告：真实仓库 URL、各环节实测结果、失败项与原因（含 Webhook 若因无公网地址而失败的定性）。

---

## 6. 已知前置风险

| 风险 | 现状与对策 |
|---|---|
| 出口 IP 被 Gitee 限流 | 实测本机 **未认证**请求 `GET /api/v5/version` 返回 `403 Rate Limit Exceeded`。带令牌的请求通常按令牌计额，预计不受影响；若命中，会明确报出而不是静默失败 |
| 组织建仓权限 | 若令牌账号只是组织普通成员且组织关闭了成员建仓权限，`ORG_ACCESSIBLE` 会通过但真正建仓时 403 —— 届时会原文回显 Gitee 报错 |
| Webhook 无法真实回调 | 本机是内网地址，Gitee 回调不到；这一环节会标注为"环境限制"，不计为代码缺陷 |
