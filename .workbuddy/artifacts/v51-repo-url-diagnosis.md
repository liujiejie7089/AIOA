# 仓库地址本地化 / 点击跳不到 Gitee —— 排查结论与改进建议

> 编制：2026-09-16 · 涉及迁移：无（本次未改数据库结构）· 取证脚本：3 个（见 §7）
> 现象：详情页的「克隆命令 / SSH / HTTPS / Gitee 网页」四个地址全部指向 `127.0.0.1:8090`，点击后打开的是本地服务，不是 Gitee。

---

## 0. 结论（先给答案）

**不是代码缺陷，是部署接线（配置）问题。** 但排查过程中发现**两个真实的健壮性缺口**，一并列出，避免用"配置问题"四个字把问题糊过去。

| # | 结论项 | 定性 | 决定性证据 |
|---|---|---|---|
| 1 | 四个地址全是 `127.0.0.1` | **配置问题** —— 本机后端被指向了本地 Gitee 桩 | **对照实验**：把 Gitee 侧改为返回 `gitee.com`，四个地址**即刻全部变成公网形态，零代码改动** |
| 2 | 点击后跳不到 Gitee | **配置问题的必然结果**（跳转实现本身是对的） | **真点击取证**：本地地址 → 新标签页落在 `127.0.0.1:8090`；公网地址 → 新标签页落在 `https://gitee.com/...` |
| 3 | `aioa.gitee.web-base-url` 配置了却没用 | **代码缺陷（轻微）· 死配置** | 该字段全代码库**零引用**（只在 `GiteeProperties` 声明 + yml 绑定） |
| 4 | 地址是建仓时的快照，**无刷新路径** | **设计缺口** | 全库仅 `GiteeRepoTaskHandler:98-100` 一处赋值；快照不变性实验证明改配置不会修复存量行 |
| 5 | Webhook 回调地址注册成了 `127.0.0.1` | **配置问题，且会静默失效** | 桩侧钩子 URL 取证：`http://127.0.0.1:8080/api/v1/gitee/webhook/{id}` |

**一句话**：平台忠实地展示了 Gitee 告诉它的内容 —— 而当前"Gitee"是本机的一个桩服务。换成真实 Gitee 就正常；但**已写坏的存量行不会自动恢复**，需要 §5 的回填。

---

## 1. 环节一：地址生成 —— 为什么会是本地地址

### 1.1 地址不是本地拼的，是**照抄 Gitee 接口响应**

完整的代码路径只有两跳，且都不含任何域名拼接：

```
Gitee 接口响应 {html_url, ssh_url, https_url}
   ↓  GiteeRepoTaskHandler.java:98-100   原样写库
gitee_project.gitee_html_url / gitee_ssh_url / gitee_https_url
   ↓  GiteeProjectService.java:221-227  原样读出
详情接口 → 前端 el-link :href          （克隆命令 = "git clone " + sshUrl，:227）
```

- `GiteeRepoTaskHandler.java:98-100`：`upd.setGiteeHtmlUrl(str(repo.get("html_url"), null))` 等三行（html/ssh/https），值全部取自接口响应。
- `GiteeProjectService.java:221-227`：`htmlUrl`/`sshUrl`/`httpsUrl` 三个字段直读库列（221/222/223）；`cloneCommand = "git clone " + giteeSshUrl`（227）。
- **前端无任何兜底域名**：全仓库搜索 `gitee.com`，`web/apps/shell/src` 与 `user-client` 均**零命中** → 展示完全由库值决定。

### 1.2 那"Gitee"是谁？—— 本机的桩服务

本机后端的 `aioa.gitee.base-url` 被指向了本地 Gitee 桩（`http://127.0.0.1:8090/api/v5`，用于无凭证做端到端回归）。而桩在 `scripts/gitee_stub.py:117-119`（`_repo_urls`，默认分支）**自己编造**了三个地址：

```python
"html_url":  f"http://127.0.0.1:{PORT}/{owner}/{path}",
"ssh_url":   f"git@127.0.0.1:{owner}/{path}.git",
"https_url": f"http://127.0.0.1:{PORT}/{owner}/{path}.git",
```

于是"Gitee 说的地址"就是本地地址。**平台没有做错任何事 —— 它把桩告诉它的话一字不差地展示了出来。**

### 1.3 对照实验（这就是定性依据）

为把"换成真实 Gitee 后地址会不会变"从**阅读代码后的推断**变成**可真实执行的验证**，我给桩加了一个控制端点（默认关闭，行为与历史逐字节一致）：

```bash
POST /_stub/public-base  {"base": "https://gitee.com"}    # 让桩按公网域名返回地址
```

| 断言 | 桩返回本机地址（基线） | 桩返回公网地址（对照） |
|---|---|---|
| Gitee 网页 | `http://127.0.0.1:8090/aioa-demo-org/dept101-url-…` | `https://gitee.com/aioa-demo-org/dept101-url-…` |
| SSH | `git@127.0.0.1:aioa-demo-org/….git` | `git@gitee.com:aioa-demo-org/….git` |
| HTTPS | `http://127.0.0.1:8090/aioa-demo-org/….git` | `https://gitee.com/aioa-demo-org/….git` |
| 克隆命令 | `git clone git@127.0.0.1:…` | `git clone git@gitee.com:…` |

**零代码改动、只换接口返回，四项全部随动** → 地址生成环节**代码无缺陷**。
另外用桩自身的仓库登记（= Gitee 侧事实）交叉验证：桩登记的 `html_url/ssh_url/https_url` 与平台展示**逐字一致**，排除"平台自己拼"。

### 1.4 但地址是**快照**，不是实时计算（设计缺口）

`GiteeRepoTaskHandler` 的三行赋值是**全代码库唯一**写入点，只在**新建仓库时**执行一次；此后没有任何刷新/重同步路径。实验证明：撤销 `public-base` 后，**已存在项目的地址不变**（仍显示先前写入的值）。

后果：**一旦写入错误域名（或 Gitee 侧改名/迁移），链接永久失效，平台无法自愈。**

---

## 2. 环节二：点击跳转 —— 实现是对的，错的是地址

前端实现（`GiteeProjectDetailView.vue:126-128`、`:625`）：

```html
<el-link :href="repository.sshUrl"   target="_blank" rel="noopener">SSH …</el-link>
<el-link :href="repository.httpsUrl" target="_blank" rel="noopener">HTTPS …</el-link>
<el-link :href="repository.htmlUrl"  target="_blank" rel="noopener">Gitee 网页 …</el-link>
<!-- 顶部按钮： --> window.open(project.value.htmlUrl, '_blank', 'noopener')
```

**真点击取证**（无头 Edge，捕获新标签页 URL，而非只读 href）：

| 项目 | 点击「Gitee 网页」后新标签页的 URL | 判定 |
|---|---|---|
| 本地地址项目 | `http://127.0.0.1:8090/aioa-demo-org/dept101-url-1789554921` | **复现投诉**：跳到桩，不是 Gitee |
| 公网地址项目 | `https://gitee.com/aioa-demo-org/dept101-url-1789554925` | **证明**：配置对了，跳转就对 |

同时断言：三链接 `href` 与接口值**逐字一致**、`target` 均为 `_blank`、克隆命令输入框值 == 接口 `cloneCommand`、无控制台错误、无 5xx。

**→ 跳转机制无缺陷；"点不开"完全是地址错误的下游表现。**

---

## 3. 环节三：链接配置审计

参与链接生成的配置项共 5 个，本机现状与生产要求对照如下（本机值即上文实验时注入的环境变量）：

| 配置项 | 作用 | 本机现值 | 生产要求 | 判定 |
|---|---|---|---|---|
| `aioa.gitee.base-url` | **API 基址**（地址的唯一来源） | `http://127.0.0.1:8090/api/v5`（桩） | `https://gitee.com/api/v5`（**默认值本来就是它**） | 本机为回归而改，生产用默认即可 |
| `aioa.gitee.web-base-url` | 原设计意图：网页域 | `http://127.0.0.1:8090` | —— | ❌ **死配置：配了不生效**（零引用） |
| `aioa.gitee.redirect-uri` | OAuth 回调 | `http://127.0.0.1:8080/api/v1/gitee/bind/callback` | 公网域名，且须与 Gitee 应用登记**完全一致** | 生产必改 |
| `aioa.gitee.webhook-base-url` | Webhook 回调基址 | `http://127.0.0.1:8080` | **必须公网可达** | ⚠️ 生产必改，否则静默失效 |
| `aioa.gitee.bind-return-url` | 授权后前端回跳 | `http://127.0.0.1:5173/gitee/projects` | 前端公网域名 | 生产必改 |

另有两项与安全/开关相关，同样**必须在生产覆盖**：
- `aioa.gitee.client-id` / `client-secret`：本机为回归假值（`aioa-e2e-client` / `aioa-e2e-secret`）。
- `aioa.gitee.token-enc-key`：默认值 `aioa-dev-gitee-token-key-please-change` **可离线解密已授权的 Gitee 令牌**，生产必须替换。

### 3.1 关于 Webhook 的"静默失效"（值得单独强调）

实测已注册到 Gitee 侧的回调地址是 `http://127.0.0.1:8080/api/v1/gitee/webhook/{id}`。真实 Gitee **回调不到本地地址**。两种可能都有害：

- 若 Gitee 接受注册 → 平台侧显示"Webhook 已配置"，而事件**永远收不到** → **静默失效**，最危险；
- 若 Gitee 拒绝注册 → 任务直接失败并报错（尚可见）。

本机是本地桩，**无法验证真实 Gitee 的校验行为**，故不臆断属于哪一种；但两种情况在生产都不可用，区别只是"报不报错"。

---

## 4. 明确判定：代码缺陷 vs 缺少配置

| 你问的问题 | 判定 |
|---|---|
| 地址为什么是本地地址 | **缺少/错误的配置**（后端 API 基址指向本地桩）。**代码按设计正确工作** |
| 点击为什么跳不到 Gitee | **配置问题的下游结果**。跳转实现（href + `target=_blank` + `window.open`）**无缺陷** |
| 有没有代码问题 | **有，但不是本投诉的成因**：① `web-base-url` 死配置（会误导运维"改了它就能换域名"）；② 地址快照**无刷新路径**，存量写坏无法自愈 |
| 换到真实 Gitee 就好了吗 | **新项目会正常；已存在的存量行不会自动修复** —— 见 §5 |

---

## 5. 修复方案

### 5.1 生产配置矩阵（照此覆盖即可）

```bash
# 通常无需设置（默认已是生产值）
AIOA_GITEE_BASE_URL=https://gitee.com/api/v5
AIOA_GITEE_ORG=<全局默认组织，或留空由各租户自行配置>

# 必须按实际公网域名设置
AIOA_GITEE_CLIENT_ID=<Gitee 第三方应用 client_id>
AIOA_GITEE_CLIENT_SECRET=<对应 secret>
AIOA_GITEE_REDIRECT_URI=https://<平台域名>/api/v1/gitee/bind/callback
AIOA_GITEE_WEBHOOK_BASE_URL=https://<平台域名>          # 必须公网可达，否则 webhook 静默失效
AIOA_GITEE_BIND_RETURN_URL=https://<前端域名>/gitee/projects

# 安全：必须替换默认值
AIOA_GITEE_TOKEN_ENC_KEY=<32 字节随机串>

# 不要设置 AIOA_GITEE_WEB_URL —— 当前是死配置，设了无效（待清理）
```

配套检查：Gitee「设置 → 第三方应用」里登记的**回调地址必须与 `redirect-uri` 逐字一致**；平台域名需能从公网访问到 Webhook 路径。

### 5.2 存量数据回填（本机 10 个项目中有 9 个需要）

因地址是快照，改配置**不会**修好已写坏的行。已提供回填工具（**默认干跑，必须显式 `--apply` 才写库**）：

```bash
python scripts/backfill_gitee_repo_urls.py --base https://gitee.com              # 干跑，列出将改的行
python scripts/backfill_gitee_repo_urls.py --base https://gitee.com --apply       # 落库
```

干跑结果（真实输出）：`扫描 10 个项目 → 需要回填 9 项`，逐行给出 html/ssh/https 的 before→after。
它只改这三个地址列，不碰 owner/repo_name/状态。**局限**：按 base 重写，若仓库在 Gitee 侧已**改名**则修不了（需按 §6 的 P0-3 增加重新拉取能力）。

---

## 6. 对标 o2oa：本系统还应补充什么

### 6.1 o2oa 的功能范围（取自其代码库 `o2server` 模块，非宣传口径）

| 能力域 | 对应模块 |
|---|---|
| 流程平台 | `x_processplatform_*`：流程/表单**可视化设计器**、运行时、引擎、**BAM 流程数据分析** |
| 组织与权限 | `x_organization_*`：组织管理、认证、个人、轻量查询 |
| 门户与内容 | `x_portal_*`（门户设计器 + 渲染）、`x_cms_*`（内容管理/信息发布） |
| 协同办公 | `x_attendance_*`（考勤）、`x_meeting_*`（会议）、`x_calendar_*`（日程）、`x_file_*`（云文件） |
| 数据与报表 | `x_query_*`：数据建模 + 展现 + 处理（自助报表/统计） |
| 沟通与协同 | `x_message_*`（消息）、`x_jpush_*`（移动推送）、`x_bbs_*`（论坛）、`x_mind_*`（脑图） |
| 平台底座 | `x_program_center` / `x_console`（控制台）/ `x_component_*`（组件与应用管理）/ 多 OS 启停脚本 |
| AI（新增中） | `x_ai_assemble_control` / `x_ai_core_entity`（AI 对话、文档索引与权限） |
| 移动端 | `o2android` / `o2ios` 独立仓库 |
| 信创 | 支持麒麟 OS、达梦 / 人大金仓数据库 |

**关键差异（决定怎么对标才对）**：o2oa 是**单组织部署**的通用 OA；本系统是**多租户 SaaS 化 + AI 数字员工**平台。所以不能"它有什么就抄什么"，而要看**能力是否服务于"AI 公共服务平台"的定位**。

### 6.2 本系统现状（脚本实测，非印象）

已具备：账号/角色/权限矩阵与组织作用域、审批流（含职务知会与逐级递推）、数字员工与专家、知识库（RAG）、工具注册与调用、子应用注册（shell / demo-ticket / demo-dispatch）、业务系统数据接入（客户/合同/库存/销售/财务 KPI）、额度与计费、成本分摊、内容审核、成果、审计、Gitee 仓库联动、H5 用户端、待办与站内通知。

实测确认**缺失**（`grep` + `SHOW TABLES` 双证据）：无日程、无会议、无考勤、无云文档、无门户/CMS、无报表设计器、无通用表单/页面设计器、无论坛/脑图；`notification` 表**只有站内信单一通道**（无 channel 字段，无短信/邮件/推送）；`schedule` 命中项实为**定时任务**、`push` 命中项实为 **git push**，均非对应功能。

### 6.3 建议清单（按优先级，每项含预期作用）

#### P0 — 先让"已上线的东西真的能用"（都是本次暴露或强相关的）

| # | 事项 | 预期作用 |
|---|---|---|
| P0-1 | **链接与回调配置自检**：扩展已有的 `StartupCheckRunner`，在启动时对 `webhook-base-url` / `redirect-uri` / `bind-return-url` 指向 `127.0.0.1`/`localhost` 的情况**打 WARN**，并写入 `audit_log` | 把"静默失效"变成"启动即告警"。这是本次最危险的发现：Webhook 显示已配置但永不触发，运维无从察觉 |
| P0-2 | **清理 `web-base-url` 死配置**：二选一 —— 让它真正参与地址生成（作为兜底域名），或删除并补文档 | 消除会误导运维的配置项。当前形态下，运维改了它却毫无效果，会浪费排查时间（本次投诉正是从这类困惑开始） |
| P0-3 | **新增「刷新仓库信息」能力**（后端接口 + 详情页按钮）：调 `GET /repos/{owner}/{repo}` 重新拉取并回填三地址，同时更新默认分支等 | 让快照可自愈：仓库在 Gitee 侧改名/迁移、或曾指向错误环境后，管理员点一下即可修复，无需运维写 SQL。回填脚本只能治"域名错"，治不了"改名" |
| P0-4 | **生产配置基线固化**：把 §5.1 写成部署检查单（含 `token-enc-key` 必须替换） | 避免下一套环境重演同一问题；同时堵住默认加密密钥可离线解密令牌的风险 |

#### P1 — 补齐"平台化"的骨架能力（对标 o2oa 最有价值的部分）

| # | 事项 | 预期作用 |
|---|---|---|
| P1-1 | **通用流程引擎 + 可视化表单/流程设计器**（对标 `x_processplatform_*`） | 当前只有"审批链配置"，业务单据只能靠开发（请假是唯一业务样例）。补上后，各局可**自助**定义报销、请示、备案等流程与表单，平台才算能承接真实业务 |
| P1-2 | **统一消息中心 + 多通道触达**（站内/邮件/短信/移动推送） | `notification` 表现只有站内单一通道。多通道才保证"审批到了"能真正触达人，而不依赖用户主动登录 |
| P1-3 | **云文档/文件管理**（版本、在线预览、细粒度权限），并与知识库打通 | 既补 OA 刚需，又让数字员工直接在受权限约束的文档上做 RAG，而不是另建一套知识库副本 |
| P1-4 | **日程 / 会议 / 考勤**三件套（对标 `x_calendar_*` / `x_meeting_*` / `x_attendance_*`） | 政府单位日常刚需，是把"AI 平台"用成"能日常办公的 OA"的关键。建议**先做会议+日程**（与现有审批待办联动），考勤视客户要求 |

#### P2 — 数据与治理

| # | 事项 | 预期作用 |
|---|---|---|
| P2-1 | **自助报表/数据查询设计器**（对标 `x_query_*`） | 现在 KPI 靠接入外部业务系统数据。让业务处室自助取数出表，可大幅减少定制开发 |
| P2-2 | **流程效率分析（BAM）**（对标 `x_processplatform_assemble_bam`） | 统计各节点耗时、积压、超时，支撑内部考核与流程优化 —— 管理端目前只有待办计数 |
| P2-3 | **门户/内容发布（CMS）**（对标 `x_portal_*` / `x_cms_*`） | 地市级平台通常需要对外信息发布与门户栏目。可与内容审核打通，形成"发布即过审"闭环 |
| P2-4 | **子应用与工具的上架治理**（对标 `x_component_*`） | 本系统已有 `app_registry` 与工具注册，但缺版本、灰度、上下架与配额治理。作为"平台"这是必备能力，也直接服务于多租户计费 |

#### P3 — 生态与合规（按客户与信创要求排期）

| # | 事项 | 预期作用 |
|---|---|---|
| P3-1 | **信创适配与认证**：麒麟/统信 OS、达梦/人大金仓数据库、国密算法（对标 o2oa 的信创资质） | 地市级政务项目的准入门槛，往往是能否投标的硬条件 |
| P3-2 | **移动端强化**：现仅有 H5，建议补 PWA/原生壳 + 推送（对标 o2oa 的 `o2android`/`o2ios` + `x_jpush_*`） | 移动办公体验与到达率；与 P1-2 的多通道共用推送通道 |
| P3-3 | **低代码扩展**：自定义页面/组件的可视化搭建 | 与 P1-1 配套，降低后续定制成本 |
| P3-4 | 论坛 / 脑图等协同小工具 | 价值有限，建议仅在有明确客户诉求时做，不主动投入 |

### 6.4 不要照抄的地方（保住差异优势）

o2oa 是单组织通用 OA，本系统的**差异化优势恰恰在 o2oa 没有的部分**，对标时不要被稀释：
**多租户 SaaS 化隔离**（租户/机构/部门三级作用域 + 跨租户 404 不泄露存在性）、**AI 数字员工与专家体系**、**知识库 RAG**、**额度计费与成本分摊**、**内容审核**。
建议原则：**以 AI 与多租户为主线**，按 P1 补齐"能办公"的骨架，而不是把 o2oa 的功能清单整表搬过来。

---

## 7. 取证与复现

| 脚本 | 内容 | 实测结果 |
|---|---|---|
| `scripts/verify_v51_repo_urls.py` | 地址生成（基线复现 + 公网对照）、接口↔库一致性、链接配置审计、快照不变性 | **23 / 23 PASS** |
| `scripts/verify_v51_repo_urls_ui.py` | 浏览器：三链接 href / target、克隆命令、**真点击捕获新标签页 URL** | **18 / 18 PASS** |
| `scripts/backfill_gitee_repo_urls.py` | 存量回填工具（默认干跑） | 干跑：`10 个项目 → 需回填 9 项` |
| `scripts/gitee_stub.py` | 新增 `/_stub/public-base` 控制端点（默认关闭，历史行为逐字节不变）；已补充文档并修正其中关于 `web-base-url` 的误导性说明 | 桩语法校验通过，默认输出与历史一致 |

截图：`.workbuddy/artifacts/v51-ui/本地地址项目.png`（复现投诉）、`公网地址项目.png`（配置正确时的正确形态）。

**本机无法验证的部分（如实说明）**：本环境用本地桩，**没有真实 Gitee 凭证**，因此"真实 Gitee 是否按此形态返回地址""真实 Gitee 是否接受 `127.0.0.1` 的 Webhook 注册"无法在本机证明。前者由 Gitee OpenAPI 的字段约定保证，后者需在预发环境用真实应用实测。
