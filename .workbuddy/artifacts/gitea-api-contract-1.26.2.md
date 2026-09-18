# Gitea 1.26.2 对接契约（实例实测版）

> 数据来源：**本平台要对接的那个实例自己吐出来的 OpenAPI 规范**
> `http://172.16.8.249:3000/swagger.v1.json`（839 KB / 300 条路径 / Swagger 2.0），
> 已落盘到 `logs/gitea-swagger-1.26.2.json`（`logs/` 已 gitignore，不入库）。
>
> **为什么以实例规范为准而不是查官网文档**：官网文档描述的是「当前最新版」，
> 而我们要对接的是自建的 **1.26.2**；字段增删在版本间是常事，拿官网文档写代码
> 会把「版本差异」误当成「我写错了」。这份规范是该实例的自我描述，可直接当契约用。

---

## 1. 实例探测结论（可复现）

| 探测 | 结果 | 含义 |
|---|---|---|
| `GET /api/v1/version` | `{"version":"1.26.2"}` HTTP 200 | 沙箱**可达**内网 Gitea |
| `GET /api/v1/settings/api` | `max_response_items: 50`、`default_paging_num: 30` | **分页硬上限 50**，必须翻页 |
| `GET /login/oauth/authorize?...` | HTTP 303 → `/user/login?redirect_to=…` | OAuth2 提供方**已启用**（非登录态只能拿到跳登录） |
| `GET /api/v1/orgs` | 仅 1 个公开组织：`huimao` | 可用的组织宿主候选 |
| `GET /api/v1/repos/liujiejie/AIOA_System` | HTTP 404 | 匿名读**仓库级**接口不可用 |
| `git ls-remote origin` | `Repository not found` | git 层同样需认证 |

> **结论**：实例的**公共**接口（version / settings / 公开组织）无需认证即可读，
> 因此 API 形态可以自证；但**任何仓库 / 组织 / 用户级写操作都需要令牌**。
> 这是「真机端到端验证」的唯一硬阻塞 —— 没有令牌就连一个仓库都建不出来。

---

## 2. 端点对照（Gitee → Gitea）

`✅ 同形` = 路径与语义基本一一对应，改参数名即可；`⚠ 需改写` = 有实质差异。

| 能力 | Gitee（现实现） | Gitea 1.26.2 | 判定 |
|---|---|---|---|
| 建组织仓 | `POST /orgs/{org}/repos` | `POST /orgs/{org}/repos` | ⚠ 请求体字段不同（见 §3.1） |
| 建用户仓 | `POST /user/repos` | `POST /user/repos` | ⚠ 同上 |
| 仓库详情 | `GET /repos/{o}/{r}` | `GET /repos/{o}/{r}` | ✅ 同形 |
| 删仓库 | `DELETE /repos/{o}/{r}` | `DELETE /repos/{o}/{r}` | ✅ 同形 |
| 建 Webhook | `POST /repos/{o}/{r}/hooks` | `POST /repos/{o}/{r}/hooks` | ⚠ 请求体与签名机制不同（见 §3.2） |
| Webhook 列表 | `GET …/hooks`（`per_page`） | `GET …/hooks`（`page`+`limit`） | ⚠ 分页参数名不同 |
| 删 Webhook | `DELETE …/hooks/{id}` | `DELETE …/hooks/{id}` | ✅ 同形 |
| 读文件/目录 | `GET …/contents/{path}` | `GET …/contents/{filepath}`（`ref` 在 query） | ✅ 同形 |
| 新建文件 | `POST …/contents/{path}` | `POST …/contents/{filepath}` | ✅ 同形（`content` 同为 Base64） |
| 更新文件 | `PUT …/contents/{path}`（须带 sha） | `PUT …/contents/{filepath}`（**无 sha 则创建**） | ⚠ 语义更宽（见 §3.3） |
| 分支列表 | `GET …/branches`（`per_page`） | `GET …/branches`（`page`+`limit`） | ⚠ 分页参数名不同 |
| 协作者列表 | `GET …/collaborators` | `GET …/collaborators`（`page`+`limit`） | ⚠ 分页参数名不同 |
| 增/改协作者 | `PUT …/collaborators/{username}` | `PUT …/collaborators/{collaborator}` | ✅ 同形，路径变量改名 |
| 删协作者 | `DELETE …/collaborators/{username}` | `DELETE …/collaborators/{collaborator}` | ✅ 同形 |
| 提交列表 | `GET …/commits`（`per_page`） | `GET …/commits`（`page`+`limit`，多 `path/since/until/stat`） | ⚠ 分页参数名不同 |
| 当前用户 | `GET /user` | `GET /user` | ✅ 同形（`login`/`id` 同名） |
| 组织信息 | `GET /orgs/{org}` | `GET /orgs/{org}` | ✅ 同形 |
| 换令牌 | `POST /oauth/token`（网页域） | `POST /login/oauth/access_token` | ⚠ 路径不同 |
| 授权页 | `GET /oauth/authorize` | `GET /login/oauth/authorize` | ⚠ 路径不同 |
| 仓库级团队 | `GET|PUT /repos/{o}/{r}/teams…` | **无对应物**（只有组织级 `/orgs/{org}/teams` + `PUT /teams/{id}/repos/…`，语义反转） | ❌ 无对应物 |

> 统计：**14 / 21 同形**，5 处需改写，1 处无对应物。
> 与迁移评估文档（`gitee-to-gitea-migration.md`）的 19/25 口径一致（该文含团队、协作等另外 4 个端点）。

---

## 3. 请求体字段实测（**这是最容易写错的地方**）

### 3.1 `CreateRepoOption` —— ⚠ **没有 `path` 字段**

```
name*        string    ← 必填，且**同时是 URL 片段**（Gitea 无独立的 path）
description  string
private      boolean
auto_init    boolean   ← 自动建 README 以初始化仓库（对应我们的 autoInit）
default_branch string
readme / gitignores / license / template / trust_model / object_format_name
```

**三条要点**：

1. **`path` 不存在**。Gitee 的 `name`（可含中文的展示名）与 `path`（URL 片段）是
   两个字段；Gitea 只有 `name` 一个。⇒ **产品决策点**：中文展示名要么丢，要么进 URL。
2. **`has_issues` / `has_wiki` 不在创建体里**。现有 Gitee 实现会带
   `has_issues=true, has_wiki=false`；Gitea 建仓时不接受这两个键（属
   `EditRepoOption`，得建完再 `PATCH`，或干脆不管）。**带了不会报错但无效果**，
   属于「以为设了其实没设」的静默失效，需显式去掉。
3. `auto_init` 语义一致（建 README 初始化默认分支），可直接映射。

### 3.2 `CreateHookOption` —— ⚠ **两个静默失效陷阱**

```
type*   string  enum=[dingtalk,discord,gitea,gogs,msteams,slack,telegram,feishu,wechatwork,packagist]
                ← 通用 Webhook 用 "gitea"
config* object  ← CreateHookOptionConfig，swagger 里是空 schema（自由键值）
                  Gitea 通用 Webhook 实际用 { url, content_type, secret }
events  array   ← 事件名清单（下划线风格：push / pull_request / issues / issue_comment …）
active  boolean ← **default = false**
```

| 陷阱 | 后果 | 对策 |
|---|---|---|
| **`active` 默认 `false`** | Webhook 建好了但**是关闭状态**，回调一条不来，而创建接口返回 200 成功 | 必须显式 `active = true` |
| `type` 不传或传错 | 不是「普通 webhook」 | 必须传 `"gitea"` |

> 这两个坑与我们在 Gitee 上踩的「桩不校验 scope / 建仓成功但 Webhook 静默失败」
> **完全同类**：接口返回成功，功能却没生效。因此实现后**必须验证回调真的到达**，
> 不能只看创建接口的返回码。

`secret` 放在 `config.secret` 里，用于 HMAC 签名（见 §4）。

### 3.3 `CreateFileOptions` / `UpdateFileOptions`

```
content*  string   ← Base64（与 Gitee 一致）
message   string
branch    string
sha       string   ← 仅 UpdateFileOptions 有
from_path string   ← 仅 UpdateFileOptions 有（改名用）
author / committer / signoff / force_push / new_branch / dates
```

**`PUT` 的语义比 Gitee 宽**：官方描述为
*"Update a file in a repository **if SHA is set, or create the file if SHA is not set**"*。
⇒ Gitea 用 `PUT` 一个动词就能覆盖「新建 + 覆盖」，而 Gitee 必须
`POST`（新建）/ `PUT`（覆盖，须带 sha）。实现时**两种都能走通**：
在我们的 `putFile()` 里用 `POST`、`updateFile()` 里用 `PUT`，与 Gitea 语义天然吻合。

### 3.4 `AddCollaboratorOption`

```
permission: enum = [read, write, admin]
```

与 Gitee **完全一致**，`addCollaborator` 的权限映射可直接复用。

---

## 4. Webhook 回调契约（两家不通用）

| | Gitee | Gitea 1.26.2 |
|---|---|---|
| 事件头 | `X-Gitee-Event`，值如 `Push Hook` | `X-Gitea-Event`，值如 `push` |
| 校验方式 | **共享密钥明文比对**：`X-Gitee-Token` == 建 hook 时的 password | **HMAC-SHA256**：`X-Gitea-Signature` = HMAC-SHA256(原始报文体, config.secret) 的**十六进制，无前缀** |
| 兼容头 | 无 | `X-Hub-Signature-256: sha256=<hex>`（GitHub 风格，**带前缀**） |
| 校验算法 | 常量时间字符串比对 | 常量时间比对**HMAC 摘要**，须用**原始字节**，不能先 `getReader()` 再转字符串 |

> 二者的「secret」字面相同但**算法完全不通用**：
> 用 Gitee 的明文比对去校验 Gitea 回调 ⇒ 100% 拒绝；
> 反过来则等于把校验退化成「谁能猜中密钥谁就能写」。切换时必须整段替换，
> 不能只换头名。

**事件名对照**（Java 侧 `classify()` 已按两家统一归一化，见
`GiteeWebhookService.normalizeEvent`）：

| 平台枚举 | Gitee | Gitea |
|---|---|---|
| PUSH | `Push Hook` / `Tag Push Hook` | `push` |
| MERGE_REQUEST | `Merge Request Hook` | `pull_request` / `pull_request_review` |
| ISSUE | `Issue Hook` | `issues` / `issue_label` / `issue_assign` |
| NOTE | `Note Hook` | `issue_comment` / `pull_request_comment` |

> ⚠ **回调请求体形状仍需真机验证**：Gitea 的 `sender` 在 API `User` 模型里是
> `login` / `id`，但规范里另有一个 `PayloadUser`（字段为 `username` / `name` / `email`）。
> 我们的身份映射读的是 `sender.id` + `sender.login`，**必须以真实回调报文确认**
> 命中的是哪一种 —— 这一点只有把 Webhook 真正打通（需要公网可达回调地址）才能证实。

---

## 5. 分页：`per_page` → `page` + `limit`

所有列表端点统一为 `page`（页码）+ `limit`（页大小）：

- `per_page` 在 Gitea 上**被忽略**，回落默认页大小 ⇒ 静默少一截数据；
- 服务端**硬上限 50**（`max_response_items`），即便 `limit=100` 也只回 50。

**因此翻页逻辑的结束条件不能写成「本页条数 < 请求条数」** ——
请求 100、实回 50，会被误判成「已是最后一页」，第 2 页起全部丢失。
正确做法是**「本页为空才停」**（已在 `GiteeClient.listAllPaged()` 落实，
并对「服务端忽略分页参数导致整页重复」加了第三道保险）。

---

## 6. 仍需产品/运维拍板的事项

| # | 事项 | 影响 |
|---|---|---|
| 1 | **中文仓库展示名**（§3.1-1） | 唯一**破坏性**变更：要么丢中文名，要么中文进 URL |
| 2 | Gitee 是否保留（并存适配 vs 整体替换） | 决定接口层是否要长期维护双实现 |
| 3 | **TLS**：私有化 Gitea 常用自签证书，当前 `HttpClient` 无任何信任配置 | 不改则直接 `SSLHandshakeException` |
| 4 | 仓库级团队同步（§2 末行「无对应物」） | 建议砍掉或改为组织级语义 |
| 5 | 公网可达的 **Webhook 回调地址** | 没有它就无法验证 Webhook（会停在「建仓成功但 Webhook 失败」） |

---

## 7. 真机复核补充（2026-09-18，全链路跑通后回填）

> 来源：`scripts/e2e_gitea_live.py`（64/64）与 `scripts/_diag_gitea_live.py` 的实测输出。
> 本节只记**上一轮靠文档/推断拿不到**的事实。

### 7.1 `auto_init=true` 建出的默认分支是 `main`

```
POST /orgs/AI-OA/repos {name, private:true, auto_init:true} → 201
响应: default_branch = "main"   empty = false
```
⚠️ **不要写死 `master`**：Gitea 默认分支由实例的 `DEFAULT_BRANCH` 决定（本实例为 `main`）。
写死会让后续「写文件（需 `branch` 参数）/ 读目录 / 文件网页链接」**全部 404**。
平台侧对策：`RepoProviderClient.defaultBranch()` 按托管方给值，
且建仓后用**接口返回的 `default_branch` 覆盖**占位值。

### 7.2 Webhook 的 `secret` 是**只写不读**

```
GET /repos/{o}/{r}/hooks/{id}
→ config = { "url": "...", "content_type": "json" }    ← 没有 secret
```
密钥**不会**被回读（安全设计）。因此：
- 不能靠「读回来比对」验证密钥配对了没有；
- **唯一**的验证手段是「发一条**带正确 HMAC 签名**的投递，看是否被接受」。
  （套件 G6 正是这么做的：本地构造 Gitea 格式 push 报文 + `HMAC-SHA256(原始字节, secret)`。）

### 7.3 请求的事件名会被**自动扩展**

```
请求 events=["push","pull_request","issues","issue_comment"]
实际落库 14 个: push, pull_request, pull_request_assign/label/milestone/comment/review/review_request/sync,
                issues, issue_assign, issue_label, issue_milestone, issue_comment
```
⇒ 断言必须用**子集关系**（`期望 ⊇`），**不能**用「逐字相等」或「个数 == 4」。

### 7.4 `/hooks/{id}/deliveries` 在该版本**不存在**（404）

想「从 Gitea 侧看投递明细」此路不通。判断回调是否到达，只能：
① 在接收端计数；② 用 `/hooks/{id}/tests`（204）触发一次并观察接收端。

### 7.5 SSH 地址端口随实例配置（本实例 **2222**）

```
ssh_url = ssh://git@172.16.8.249:2222/AI-OA/{repo}.git
```
⇒ 展示「克隆命令」时必须用**接口返回的 `ssh_url`**，不要自己拼 `:22`。

### 7.6 协作者接口必须用 JSON body

```
PUT /repos/{o}/{r}/collaborators/{u}   body {"permission":"write"}  → 204
（把 permission 放 query 参数 → 422 "Empty Content-Type"）
```

### 7.7 事件分类顺序不能动（真机事件名验证）

Gitea 的 `pull_request_comment` / `issue_comment` 归一到空格后**同时含** `pull request`/`issue`，
而 `classify()` 把「评论」排在最前判定 ⇒ 这两类正确落 `NOTE` 而不是被抢成
`MERGE_REQUEST`/`ISSUE`。此顺序在真机事件名上复核通过（单测 `GiteeWebhookEventClassifyTest` 31 条）。

