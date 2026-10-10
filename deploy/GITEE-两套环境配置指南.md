# Gitee 两套环境配置指南（本地测试 / 生产）

> 面向：需要在「本地测试环境」与「生产环境」分别跑通 Gitee 仓库联动的人。
> 本文所有参数均取自本仓库真实代码（`application.yml` / `docker-compose.yml` / `deploy/.env.*` / `scripts/gitee-*.sh`），
> 不是通用 Gitee 建议。**真值（Client Secret、访问令牌）只写 `deploy/.env` 或 `.env.gitee-real`，一律不入库。**

---

## 0 · 先分清三层，混在一起必错

| 层 | 是什么 | 配在哪 | 谁产出 |
|---|---|---|---|
| **A 平台集成参数** | AIOA 后端访问 Gitee 的开关与凭据（下面第 3 节的 14 个键） | 本地 `deploy/.env.development` / 生产 `deploy/.env.production` →（服务器上）`deploy/.env` | 你，在 Gitee 建完应用/令牌后填 |
| **B Gitee 侧资源** | 组织、第三方应用、仓库 | gitee.com 网页 | 你手工创建 |
| **C 开发者 git 访问** | 你本机 `git clone/push` 到仓库 | 本机 `~/.ssh` 或 git 凭据管理器 | 你（SSH 公钥 或 私人令牌） |

**三条必须先知道的事实（本项目实测）**

1. **AIOA 不用 SSH 调 Gitee。** 平台走 HTTPS REST（`https://gitee.com/api/v5`）。SSH 地址只出现在数据表
   `gitee_project.gitee_ssh_url`（连 `gitee_https_url` / `gitee_html_url` 一起，取自建仓接口返回），
   **是留给开发者用的展示字段**，不是平台自身认证方式。
   ⇒ 「认证方式」在平台侧只有两种：**OAuth 授权** 或 **访问令牌**（见第 1 节）；SSH 属于第 C 层。
2. **仓库由平台自动创建，不需要你手建。** 建仓时 `GiteeNaming.repoPath()` 把项目名清洗成
   `[A-Za-z0-9._-]`；纯中文/符号名会退化成 **`proj-<6 位确定性哈希>`**（同一个项目名永远得到同一个仓库名，
   可重复、可追溯，刻意不用随机名）。仓库建在 `AIOA_GITEE_ORG` 指定的组织下；`ORG` 留空则建在授权用户名下。
3. **默认分支：Gitee 是 `master`。** 权威值取建仓/查询接口返回的 `default_branch`，代码里的 `master`
   只是接口没给时的兜底。**分支名写错不报「配置错」**，症状是读写文件/目录浏览全 404、页面「新项目打开就没内容」。

---

## 1 · 认证方式：两条路，可二选一（也可并存）

| | ① 个人 OAuth 授权绑定 | ② 租户级访问令牌 |
|---|---|---|
| 前置条件 | Gitee「设置 → 第三方应用」的 `Client ID` / `Client Secret` | 该组织管理员签发的**访问令牌** |
| 平台入口 | 用户在界面上点「绑定 Gitee 账号」走 OAuth | 管理端「企业 Gitee 主动初始化」里粘贴令牌 + 组织 login |
| 存在哪 | 表 `gitee_account`：`access_token` + `refresh_token`，用 `TOKEN_ENC_KEY` 做 AES-256 加密 | 表 `gitee_tenant_config`：`access_token` / `token_owner` / `token_scope` / `org_name` / `init_status` |
| 令牌校验 | 由 Gitee 授权流程保证 | 格式：长度 **8~512**，仅允许 `[A-Za-z0-9._-]` |
| 特点 | 平台**自动刷新**令牌；每个用户各自授权 | 免 OAuth 应用即可初始化；令牌过期需人工更换 |

取值优先级：**先个人绑定，解不开（无绑定/解密失败）才回落到租户令牌**。

> ⚠️ 只用 ② 时，`POST /api/v1/gitee/bind/authorize` 会返回
> 「Gitee OAuth 应用未配置（缺 aioa.gitee.client-id / client-secret）」——
> 即**个人绑定入口不可用**，但建仓/同步/Webhook 照常工作。

---

## 2 · 本地测试有两条路线，先选一条

### 路线 A：本地桩（**推荐**，零外部依赖）

```bash
python scripts/gitee_stub.py          # 起桩，监听 127.0.0.1:8090（可带端口参：gitee_stub.py 8091）
AIOA_GITEE_E2E=1 bash start-all.sh    # 后端接口与授权域一并指向桩
```

- 把 `base-url` / `web-url` / `授权跳转域` 全指向 `http://127.0.0.1:8090`（由 `scripts/gitee-e2e-env.sh` 统一注入）。
- **不需要 Gitee 账号、不需要建第三方应用、不需要建仓库，也不用手工建任何仓库**，
  就能完整跑通「绑定 → 建仓 → Webhook → 成员同步 → 文件读写」。
- 桩覆盖了与 `GiteeClient` 一一对应的全部端点（OAuth/用户/组织/仓库/钩子/内容/分支/提交/协作者）。
- 后端代码里**没有任何 if-stub 分支**，换回真实地址即生产形态 ⇒ 桩上跑通 ≈ 真实链路跑通。
- 界面会显式标注「本次授权未经过真实 Gitee」（避免把假身份误当真实授权）。
- ⚠️ 桩是**内存态**，重启即丢历史项目/仓库；任何依赖历史项目 id 的检查都会假红。
- ⚠️ 生产/演示要真实授权时**不要** source 这个文件。

### 路线 B：本地连**真实** Gitee

```bash
cp scripts/gitee-real-env.sh.example .env.gitee-real   # 模板；.env.* 已在 .gitignore
$EDITOR .env.gitee-real                                # 填 Client ID/Secret/组织/回调地址
source .env.gitee-real && bash start-all.sh
```

- **能通**：授权绑定、建仓、成员同步、文件读写。
- **不通**：Webhook —— Gitee 服务器回调不到 `127.0.0.1`。两种处理：
  - (a) 用内网穿透，把公网地址填进 `AIOA_GITEE_WEBHOOK_BASE_URL`；
  - (b) 留空，接受「建仓成功但 Webhook 步失败」。项目自带
    `scripts/_verify_gitee_webhook_hint.py` 正是验证这时界面有没有给出可读的配置提示。
- ⚠️ 模板里特别强调：**回调地址用 `localhost`，不要用 `127.0.0.1`**（与登记页逐字符一致）。

---

## 3 · 两套环境的完整参数表

「本地·桩」列 = 路线 A 由脚本注入的值（不必手填）；「本地·真实」= 路线 B 你要填的。

| 参数键 | 本地·桩（路线 A） | 本地·真实（路线 B） | 生产 | 说明 |
|---|---|---|---|---|
| `AIOA_REPO_PROVIDER` | `gitee` | `gitee` | `gitee` | 托管方档位；`gitea` 时 Gitee 段整体不生效 |
| `AIOA_GITEE_ENABLED` | `true` | `true` | `true` | 总开关；关掉则任务不入队、Webhook 不处理 |
| `AIOA_GITEE_BASE_URL` | `http://127.0.0.1:8090/api/v5` | `https://gitee.com/api/v5` | `https://gitee.com/api/v5` | 平台调用的 REST 基址 |
| `AIOA_GITEE_WEB_URL` | `http://127.0.0.1:8090` | `https://gitee.com` | `https://gitee.com` | **服务端**调用用（如 `oauth/token` 换码/刷新） |
| `AIOA_GITEE_OAUTH_AUTHORIZE_URL` | `http://127.0.0.1:8090` | `https://gitee.com` | `https://gitee.com` | **用户浏览器**授权页基址；只有桩化才改 |
| `AIOA_GITEE_CLIENT_ID` | `aioa-e2e-client` | ← 本地应用 | ← 生产应用 | 两套环境的第三方应用**不是同一个** |
| `AIOA_GITEE_CLIENT_SECRET` | `aioa-e2e-secret` | ← 本地应用密钥 | ← 生产应用密钥 | **真值只写 `.env`** |
| `AIOA_GITEE_REDIRECT_URI` | `http://127.0.0.1:8080/api/v1/gitee/bind/callback` | `http://localhost:8080/api/v1/gitee/bind/callback` | `https://mall.egoaicloud.com/aioa/api/v1/gitee/bind/callback` | 须与登记页**逐字符一致** |
| `AIOA_GITEE_SCOPE` | 未设（继承 yml 默认） | `user_info projects hook pull_requests issues notes` | 同左 | **必须同时含 `projects` 与 `hook`**，两者独立不可替代 |
| `AIOA_GITEE_ORG` | `aioa-demo-org` | ← 自建，如 `aioa-dev` | `yjiud` | 仓库建在此组织下；留空=建在授权用户名下 |
| `AIOA_GITEE_WEBHOOK_BASE_URL` | `http://127.0.0.1:8080` | 留空 或 内网穿透地址 | `https://mall.egoaicloud.com/aioa` | **必须 Gitee 可达**；回调路径 = 该值 + `/api/v1/gitee/webhook/{项目id}` |
| `AIOA_GITEE_WEBHOOK_SECRET` | 空 | 空 | 空 | 留空=每仓库随机生成密钥（推荐） |
| `AIOA_GITEE_TOKEN_ENC_KEY` | `DEV_ONLY__…` | 本地任意串 | `openssl rand -base64 48` | AES-256；换掉会让**已存令牌全部解不开** |
| `AIOA_GITEE_BIND_RETURN_URL` | `http://127.0.0.1:5173/gitee/projects` | `http://localhost:5173/gitee/projects` | `https://mall.egoaicloud.com/aioa/web/` | 授权完成后前端回跳 |
| `AIOA_GITEE_SYNC_ENABLED` | `false` | `true` | `true` | 定时轻量校准 |
| `AIOA_GITEE_SYNC_CRON` | yml 默认 `0 17 * * * *` | 同 | 同 | 每小时 17 分，避开整点高峰 |

另有 4 个**只存在于 `application.yml`、不通过环境变量配**的调优项（如需改动直接改 yml）：
`min-request-interval-ms=120` · `task-batch-size=5` · `max-attempts=5` · `http-timeout-seconds=30`；
以及 `purge-repo-on-delete=false`（删项目**不**连带删仓库，防误删代码不可恢复）。

---

## 4 · 两套环境的差异，只有这 6 处

| 差异项 | 本地 | 生产 | 为什么必须不同 |
|---|---|---|---|
| `CLIENT_ID` / `CLIENT_SECRET` | 本地应用 | 生产应用 | **回调地址不同 ⇒ 必须是两个第三方应用**（登记页的回调地址只有一个） |
| `REDIRECT_URI` | `http://localhost:8080/…` | `https://mall.egoaicloud.com/aioa/…` | 本地地址 Gitee 登记不了也不能用于生产 |
| `WEBHOOK_BASE_URL` | 空 / 穿透 | 公网 HTTPS 入口 | 本地 127.0.0.1 Gitee 回调不到 |
| `ORG` | `aioa-dev`（自建） | `yjiud` | 两套环境的仓库要隔离，避免测试仓库污染生产组织 |
| `TOKEN_ENC_KEY` | 开发用占位 | 随机 48 字节 | 本地占位串入库等于「令牌可离线解密」 |
| `SYNC_ENABLED` | 桩下 `false` | `true` | 桩是内存态，定时校准没意义 |

**其余 8 个键两套完全相同**（`BASE_URL` / `WEB_URL` / `OAUTH_AUTHORIZE_URL` / `SCOPE` 等），
因为它们指向的都是同一个真实 Gitee。

---

## 5 · 在 Gitee 上要创建什么

### 5.1 组织（每个环境一个，用于隔离仓库）

1. 登录 gitee.com → 右上头像 → **设置** → 左侧 **组织** → **新建组织**。
2. 本地测试建 `aioa-dev`（生产用 `yjiud`，已存在，组织 id 17016656）。
3. 组织 login（英文/数字）才是要填进 `AIOA_GITEE_ORG` 的值，**不是中文显示名**。

> 若你不想建组织：把 `AIOA_GITEE_ORG` 留空，仓库就建在授权用户自己的命名空间下。
> 这也是「本地想快速试」的最省事做法（但生产不建议，仓库会混在个人名下）。

### 5.2 第三方应用（**两个环境各一个**）

1. 头像 → **设置** → 左侧 **第三方应用** → **创建应用**。
2. 填应用名（如 `AIOA-本地测试` / `AIOA-生产`）、主页、**应用回调地址**：
   - 本地：`http://localhost:8080/api/v1/gitee/bind/callback`
   - 生产：`https://mall.egoaicloud.com/aioa/api/v1/gitee/bind/callback`
3. **权限勾选必须覆盖 `projects`（仓库读写）与 `hook`（Webhook 读写）**——这两项在 Gitee 是独立的，
   没有 GitHub 式聚合的 `repo`，少一个就在建仓或配钩子时失败。
4. 创建后拿到 **Client ID** 与 **Client Secret**，分别填进两套环境的 `AIOA_GITEE_CLIENT_ID` / `_CLIENT_SECRET`。

### 5.3 仓库：**不需要手工创建**

平台的 Gitee 联动是「在 AIOA 里建项目 → 平台自动在 `ORG` 下建仓 → 自动配 Webhook」。
你手工建的仓库平台**不认识**（它与自己的 `gitee_project` 记录绑定）。

> 换句话说：把「创建本地测试仓库 / 生产仓库」这件事，正确地拆成
> **「建两个组织 + 两个第三方应用」**；仓库由平台在各自的组织里自动生成。

### 5.4 仅当你需要自己 `git clone/push` 验证时才手建仓库

那就随便建，但建议命名可区分，例如 `aioa-playground`（本地测试）与 `aioa-prod-check`（生产只读校验）。
建完按第 C 层配访问方式：

- **SSH**：`ssh-keygen -t ed25519 -C "你的邮箱"` → 把 `~/.ssh/id_ed25519.pub` 贴到
  gitee.com「设置 → SSH 公钥」→ 验证 `ssh -T git@gitee.com`。
  克隆地址形如 `git@gitee.com:<owner>/<repo>.git`。
- **访问令牌（HTTPS）**：gitee.com「设置 → 私人令牌」新建（勾 `projects` 即可）→
  克隆 `https://gitee.com/<owner>/<repo>.git`，用户名填 Gitee 用户名、密码填**令牌**。

---

## 6 · 配置步骤

### 6.1 本地测试（路线 A：桩）

```bash
python scripts/gitee_stub.py                    # 终端 1：起桩（127.0.0.1:8090）
AIOA_GITEE_E2E=1 bash start-all.sh              # 终端 2：起全部服务，Gitee 指向桩
```
无需改任何配置文件，也无需任何 Gitee 凭据。验证见第 7 节。

### 6.2 本地测试（路线 B：真实 Gitee）

```bash
# 1) Gitee 侧：建组织 aioa-dev（第 5.1）、建第三方应用（回调 http://localhost:8080/...）（第 5.2）
# 2) 本机准备接线文件
cp scripts/gitee-real-env.sh.example .env.gitee-real
$EDITOR .env.gitee-real     # 填 CLIENT_ID / CLIENT_SECRET / ORG=aioa-dev / WEBHOOK_BASE_URL（可先留空）
# 3) 启动（注意：不要同时 source gitee-e2e-env.sh）
source .env.gitee-real && bash start-all.sh
```
启动日志里应看到 `[gitee] 使用生产默认：授权跳转 = https://gitee.com`。

### 6.3 生产环境

```bash
# 1) Gitee 侧：确认组织 yjiud、创建生产第三方应用（回调 https://mall.egoaicloud.com/aioa/...）
# 2) 本地仓库：deploy/.env.production 已就绪（Gitee 段已启用，公网入口已实测）
#    把真值写进 deploy/.env（该文件不入库）：
#      AIOA_GITEE_CLIENT_ID / AIOA_GITEE_CLIENT_SECRET
#      AIOA_GITEE_TOKEN_ENC_KEY=$(openssl rand -base64 48)
# 3) 送到服务器（走你的隧道机通道），然后：
cd /opt/aioa/deploy
cp .env .env.bak-$(date +%Y%m%d)                 # 回滚点
docker compose config | grep AIOA_GITEE          # 核对容器真正会收到的值
docker compose up -d server agent                # up -d 会重建才重读 .env；restart 不重读
```

---

## 7 · 验收清单

| 检查 | 手段 | 期望 |
|---|---|---|
| 配置被真正读到 | 管理端「系统配置 → 仓库配置」，或 `GET /api/v1/gitee/config` | `enabled=true`、`webhookBaseUrlConfigured=true`、`orgConfigured=true` |
| 授权绑定 | 界面点「绑定 Gitee 账号」 | 跳转到 `gitee.com/oauth/authorize?...&scope=…projects+hook…`；桩路线会标注「未经过真实 Gitee」 |
| 建仓 | 在项目管理里建项目并绑定仓库 | `POST /api/v1/gitee/projects` 毫秒级返回 `CREATING`（外呼走后台任务） |
| 建仓结果 | 查 `gitee_project` | `FAILED` → `ACTIVE`，`default_branch=master`，`gitee_ssh_url`/`gitee_https_url` 有值 |
| Webhook | `gitee_project.webhook_id` 非空 | 生产应成功；**本地 127.0.0.1 必然失败**，界面应给出可读提示 |
| 端到端 | `python scripts/e2e_v48_gitee.py`（桩路线） | 116 项通过 |

---

## 8 · 已实测的坑（照抄会踩）

1. **回调地址必须逐字符一致**，含协议/主机/端口/路径/大小写/尾斜杠。且项目模板明确要求：
   本地用 `localhost` 而非 `127.0.0.1`。注意 `deploy/.env.development` 里当前写的是 `127.0.0.1`——
   走真实 Gitee 时**这两处（登记页 vs 配置）必须一致**，否则授权静默失败。
2. **拼错 Gitee 域名没用**：生产入口是 `mall.egoaicloud.com`（`ego`+`ai`），写成双 `o` 会 DNS 不解析 + 证书名不匹配。
3. **`AIOA_GITEE_WEBHOOK_BASE_URL` 留空**不等于「功能关闭」，而是「建仓成功、Webhook 步失败」，
   项目会停在未就绪态。
4. **`TOKEN_ENC_KEY` 千万不要随便换**：换掉后已存令牌全部解密失败，报
   `Gitee 令牌解密失败：请确认 aioa.gitee.token-enc-key 未被变更`，需要重新授权绑定。
5. **平台只认接口返回的 `default_branch`**：不要凭「Gitee 一定是 master」写死分支名，
   实例可自行改默认分支。
6. **本地桩是内存态**：重启桩 → 历史仓库/项目全丢，依赖历史项目 id 的检查会假红（不是代码回归）。
7. **改前端产物后要重新构建**才能看到：`:5173` 是带 HMR 的 dev server，`:8080/aioa/web/` 是**已构建产物**，两者是不同入口。

---

## 附 · 相关文件速查

| 用途 | 文件 |
|---|---|
| 配置键字典 | `deploy/ENV.md` §3.6 |
| 本地环境变量 | `deploy/.env.development`（Gitee 段） |
| 生产环境变量 | `deploy/.env.production`（模板，入库）/ `deploy/.env`（真值，不入库） |
| 本地桩接线 | `scripts/gitee-e2e-env.sh` · `scripts/gitee_stub.py` |
| 本地真实接线模板 | `scripts/gitee-real-env.sh.example` → `.env.gitee-real` |
| 生产部署 | `deploy/生产部署手册.md` |
| 需求与契约 | `docs/29-Gitee仓库联动增量PRD.md` · `docs/30-企业Gitee主动初始化与统一消息中心.md` |
