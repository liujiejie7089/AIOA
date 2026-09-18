# Gitea 真机跑通报告 · 企业管理 → 项目管理

> 2026-09-18 · 仓库 `C:/Users/刘尖尖/WorkBuddy/aioa`
> 实例 `http://172.16.8.249:3000`（Gitea 1.26.2）· 组织 `AI-OA`（id 14，私有）
> 配套：`gitea-switch-readiness.md`（交接单）· `gitea-api-contract-1.26.2.md`（实例实测契约）· `overview.md`

---

## 一、结论：**正常流程已在真机跑通**，两轮共抓出 7 个「只有真机才暴露」的缺陷

`企业管理 → 项目管理` 全链路（建项目 → 建仓 → 配 Webhook → 成员登记 → 事件落库 → 只读读回 → 删仓）**在真实 Gitea 上端到端通过**：

| 验证 | 结果 |
|---|---|
| `scripts/e2e_gitea_live.py`（**新增**，真机套件，11 段 75 条） | **75 / 75 PASS**，0 FAIL，0 BLOCKED |
| `scripts/_check_gitea_ui_provider.py`（**新增**，浏览器渲染核对） | **17 / 17 PASS** |
| `aioa-gitee` 单测（含 8 条新增防回归 + 1 条源码审计） | **136 / 136** |
| `e2e_v51_gitee_init`（Gitee 桩接线，防回归） | **50 / 50** |
| `e2e_v48_gitee`（Gitee 桩接线，防回归） | **116 / 116** |
| `e2e_full_system --no-browser` | **145 / 145**（已知缺口 0 项） |

> 轮次说明：第一轮抓到缺陷 1–3（阻塞/正确性/可运维），第二轮补做**界面与文案面**，
> 抓到缺陷 4–7。第二轮新增的 7 条真机断言（G9.4~G9.7 / G10.5~G10.7）就是为缺陷 6、7 加的防回归。

真机产物（实测原文）：
```
repo: 37 AI-OA/dept11-gitea-1789703940 | default_branch= main | private= True | empty= False
hook: 6 | active= True | type= gitea | url= http://192.168.1.53:8080/api/v1/gitee/webhook/92
branches: ['main']     collaborators: []
平台行: (92, 'AI-OA', 'dept11-gitea-1789703940', 'main', webhook_id=6, status=ACTIVE)
```

## 二、修掉的 3 个缺陷（**都是「编译能过、启动能起、真机才炸」**）

### 缺陷 1（阻塞级）：切托管方后建项目直接 500 —— 老绑定密文解不开，且**不回落企业令牌**

- **实测症状**：`provider=gitea` 下，租户2 的 `dsj_admin` 建项目 → `POST /api/v1/gitee/projects` 返回
  `code=500「服务内部错误」`；日志根因：
  ```
  java.lang.IllegalStateException: Gitee 令牌解密失败：请确认 aioa.gitee.token-enc-key 未被变更
    at GiteeCrypto.decrypt → GiteeTokenService.validToken → GiteeProjectService.create
  Caused by: javax.crypto.AEADBadTagException: Tag mismatch
  ```
- **成因**：`gitee_account` 里存的密文是**写入时的托管方密钥**加密的。两个平台各有独立默认密钥，
  切换后老绑定必然 Tag mismatch。而代码路径是「查到绑定 → 解密 → 抛异常」，
  **根本没走到企业令牌回落**（回落只在 `acc == null` 时才发生）。
- **修法**：解密失败按「本平台下没有这条绑定」处理 → 回落企业令牌；确实无企业令牌才报错，
  且报错文案指名**当前生效**的密钥键（gitea 下说 gitea 的键，不再误指 gitee 的）。

### 缺陷 2（正确性级）：`gitee_account` 没有托管方维度 → 异平台身份被当成自己的用

- **成因**：V48 建表时只有 Gitee 一个实现，于是「一个用户一条绑定」进了唯一键
  `uk_gitee_account_user(tenant_id, user_id, alive)`。但这一行存的其实是**托管方身份**
  （uid、登录名、该平台密钥加密的令牌）。切到 Gitea 后：
  1. 同一用户想再绑一个 Gitea 身份 → 撞唯一键（旧行仍 alive）→ 500；
  2. 即便不炸，`gitee_username='liu-yang20'`（**Gitee** 的登录名）会被拿去 Gitea 的
     协作者接口 → 404，**成员同步静默失败**。
- **修法（V54 迁移）**：新增 `provider` 列（回填 `'gitee'`——此前唯一实现就是 Gitee，是事实不是猜测）；
  唯一键并入 `provider`（允许同一用户并存两个平台的身份）+ 并入 `gitee_uid`
  （两个平台数字 id 空间无关，数值可能相撞）；所有查询按当前 provider 过滤。
- **实测效果**：修复后建项目由 500 → `ACTIVE`；成员记录里**不再**写入异平台登录名
  （套件 G8.5 断言 `gitee_username IS NULL` 且为 `PENDING` + 可执行原因「待绑定后自动补齐」）。

### 缺陷 3（可运维级）：令牌密钥报错说错配置键

- 原文案恒为 `aioa.gitee.token-enc-key`，而当时 `provider=gitea` —— 用户会去改一个**根本不生效**的配置项。
- 修法：新增 `RepoProviderSettings.tokenEncKeyProperty()`，文案随 provider；
  并补「若刚切换过托管方，则这条密文是另一个平台写的，需要重新绑定」的下一步指引。

### 缺陷 4（界面级）：**整页文案写死「Gitee」**，切到 Gitea 后界面谎报托管方

- **实测症状**：`provider=gitea` 下打开「项目与仓库」，页头写「项目与仓库（**Gitee** 联动）」、
  卡片写「我的 **Gitee** 账号」，而仓库地址、跳转链接、协作者全部指向 `172.16.8.249:3000`。
  更糟的是「模块未启用」提示让人去改 `aioa.**gitee**.*` —— 一个在 gitea 下**根本不读**的配置段；
  企业初始化对话框还写着「令牌需具备 `projects` 权限」，而 Gitea 的个人令牌页上没有这个选项。
- **成因**：V48 只有 Gitee 一个实现，前端把平台名当常量写进文案；后端若干服务/控制器同理
  （`setLastError`、`BizException` 文案、接口返回的 `note`、初始化步骤标签、OAuth 结果页）。
  后端**适配器层早已中立**（`hintDisabled()` 等已按 provider 出文案），漏的是「展示层」与
  「业务文案」两处，而这两处编译期毫无提示。
- **修法**：
  1. 端口新增 `providerLabel()`（展示名）与 `configKeyPrefix()`（配置前缀），
     与 `providerName()` 同源；`/gitee/config` 回 `provider / providerLabel / configKey /
     tokenRequirementHint`，成为前端文案的**唯一来源**。
  2. 前端两页（列表 / 详情）改为按 `pName` 渲染，含表头、按钮、确认框、Toast、失败页；
     成员来源标签由视图按 provider 生成（`constants/permissions.ts` 里的字面量降级为兜底）。
  3. 后端 13 处面向用户的文案改为 `props.providerLabel()` 拼接。
  4. **新增源码审计测试**：`service/` `controller/` `support/` 下任何 `Gitee `（含句中写法）
     只允许出现在注释或 `log.*` 里 —— 防止以后又有人写回去。
  5. 真机套件补 `G0.5~G0.8` 四条（`/config` 自报托管方）与 `G8.4`（错误文案随托管方）。

### 缺陷 5（队列卫生级）：删项目后成员同步任务**空转到重试上限**

- **实测症状**：真机收尾时队列残留一条 `PENDING`：`SYNC_MEMBER / biz_id=143 / attempts=5/5 /
  last_error="项目或仓库信息不完整，无法同步成员权限"`，而它指向的项目 `106` **早已 `DELETED`**。
- **成因**：`GiteeProjectService.softDelete()` 只按 `biz_type='PROJECT'` 撤单
  （`taskService.cancelPending("PROJECT", projectId)`）；而成员任务的 `biz_id` 是**成员行 id**，
  撤不到。该任务于是每次重试都撞上「项目取不到」，而 handler 把
  「项目已不存在」（**终态**）与「仓库还没建出来」（**瞬时，该重试**）合并成同一个可重试异常。
- **修法**：拆开两种情形 —— `project == null` 直接作废（与同方法里「成员已被移除」同一口径：
  目标对象没了就没什么可同步的），只有「项目在、仓库还未建出」才重试。
- **影响**：功能上无害（不会写坏数据），但会污染队列计数、掩盖真实失败。

### 缺陷 6（界面级）：同步失败原因把**托管方原文**直接抛给用户（与缺陷 4 同一病灶）

- **实测症状**：`gitee_repo_member.last_error` / `gitee_project.error_msg` 里躺着
  `GetUserByName`（6 行）、`Not Found`（4 行）、`Rate Limit Exceeded`（18 行）、
  `401 Unauthorized: Access token does not exist`（2 行）—— 而这两个字段**直接渲染给租户管理员**
  （成员表 FAILED 态的悬浮说明 `GiteeProjectDetailView.vue:209`、项目详情红色告警标题
  `GiteeProjectDetailView.vue:54`、列表页红字 `GiteeProjectsView.vue:270`）。
- **两条独立成因**（都可单独证明）：
  1. **诊断信息在入口就丢了**：`GiteaProviderClient.extractMessage()` 只取错误体的 `message` 就返回。
     而 Gitea 在协作者用户不存在时 `message` 恰好是**内部操作名**：
     ```
     PUT /api/v1/repos/{o}/{r}/collaborators/dsj_admin -> HTTP 404 msg=GetUserByName
     （真正的人话在 errors[]："user does not exist [name: dsj_admin]"，被整段丢弃）
     ```
  2. **落库前不做本地化与归因**：拿到英文/操作名后原样写进用户可见字段，既看不懂也无从下手。
- **修法**：
  1. `extractMessage()` 改为「`errors[]` 优先、`message` 附后」——不再丢人话（日志与任务 `last_error` 立刻可读）。
  2. 新增纯函数 `support/ProviderFailureText`：按 HTTP 状态给出**中文归因 + 可执行动作**
     （401→重新绑定 / 403→补令牌权限 / 404→仓库或账号不存在 / 422→账号在当前实例不存在 /
     429→限流会自动重试 / 5xx→稍后自动重试），并把托管方原文**附在末尾括号**保留排障可追溯性。
     托管方名由 `label` 传入，不写死任何平台名。
  3. 两个落库点（`GiteeMemberTaskHandler.failedMember`、`GiteeRepoTaskHandler.markFailed`）改走该函数。
  4. 单测 20 条穷举各状态分支 + 真机断言 G9.4~G9.6（构造「绑定账号在实例不存在」这一真实形态）。
- **实测修复后落库文案**（真机原文）：
  ```
  在 Gitea 上找不到目标仓库 aioa-tenant2-1789551170/dept10-e2e-2-1789551170，也找不到账号「dsj_admin」：
  仓库可能尚未在该实例创建；若仓库正常，则是该成员绑定的 Gitea 账号在当前实例不存在，
  请到「我的 Gitea 账号」重新绑定后重试。（Gitea 原始返回：...）
  ```

### 缺陷 7（正确性级·最危险）：**422「用户不存在」被当成「已是协作者」→ 成员假绿**

- **怎么发现的**：为缺陷 6 写真机探针时探针拿不到 FAILED —— 成员反而被标成 `SYNCED`。
- **实测证据**（直连 Gitea 1.26.2）：
  ```
  PUT /api/v1/repos/AI-OA/AIOA_FrontWeb/collaborators/no-such-gitea-user-xyz
    -> 422 {"message":"user does not exist [uid: 0, name: no-such-gitea-user-xyz]"}
  PUT /api/v1/repos/AI-OA/AIOA_FrontWeb/collaborators/liujiejie   （已是协作者）
    -> 204 （幂等成功，根本不走异常分支）
  ```
- **成因**：`GiteeMemberTaskHandler.isAlreadyCollaborator()` 把 **422 一律**当「已在协作者中」
  （注释理由是「Gitee 对已存在的协作者可能返回 422/400」）。于是「成员绑定的托管方账号不存在」
  被判成同步成功：**管理端显示绿色「已同步」，而这个人对仓库没有任何权限**。
  这属于最危险的一类缺陷（假绿），任何只跑 happy path 的用例都照不出来 ——
  G8 段的创建者用例恰好因为「未绑定 ⇒ 走 PENDING 分支」而绕开了它。
- **影响面**：真机库中 `sync_status=SYNCED` 且带登录名的成员行 **82 条**，其登录名
  （`znkjyf_admin` / `znsfb_ldr` / `gitee_manual_dev` / `gitee_dev_152`）在 Gitea 实例上**都不存在**——
  其中相当一部分是「桩环境时代」的演示行（桩对任何登录名都返回 204），并非全部由本缺陷造成，
  但它们同样属于「界面说同步好了、实际没有权限」，见第六节第 5 条。
- **修法**：判据从「看状态码」改为「**看文案**」——状态码属 400/409/422 **且**文案明确说
  「已经是协作者」（`already` / `已存在` / `已是` / `已在` / `has been added` / `repeated`）才算目标已达成；
  其余 4xx 一律按失败处理（带中文归因）。Gitea 真正「已是协作者」时回 204，不会落到该分支。
  单测 6 条钉死各分支（`GiteeMemberAlreadyCollaboratorTest`）+ 真机断言 G9.4（必须落 FAILED 而不是 SYNCED）。

### 同轮修掉的静默失效：「清空失败原因」这句代码一直是空转

- **实测证据**：库里有 **17 个 `status=ACTIVE`（已就绪）的项目**仍挂着 `error_msg='Rate Limit Exceeded'`
  —— 说明「建仓成功 → `setErrorMsg(null)`」实际没写进去。
- **成因**：MyBatis-Plus 默认 `update-strategy = NOT_NULL`，会把**值为 null 的字段整段排除在 `SET` 之外**。
  于是 `setErrorMsg(null)` / `setLastError(null)` 这类「清空」写法**看起来执行成功、实际一个字节都没写**，
  旧失败原因会永久留在行上。这正是同文件里早已记录过的 `deletedAt + updateById` 那个坑的同一族
  （`GiteeMemberTaskHandler.softDeleteMember` 的注释里已经踩过一次）。
- **修法**：给 `GiteeProject.errorMsg` 与 `GiteeRepoMember.lastError` 显式声明
  `@TableField(updateStrategy = FieldStrategy.ALWAYS)`，让「清空」真的落库；字段级声明，不影响其他列。
- **为什么现在才暴露**：界面只在这两个字段配合 FAILED 态时才渲染（列表 `v-if="status==='FAILED'"`），
  ACTIVE 行上的残留对用户是不可见的 —— 属**潜在**缺陷，但它是「代码意图与行为不一致」，
  一旦哪天界面改成无条件展示就会立刻变成可见的谎报。
- **防回归**：真机断言 G10.5~G10.7（写脏 → 走重试 → 回读必须为空 → 回到 ACTIVE 后仍为空）。

### 同轮一并锁死（上一轮已改，本轮真机确认）

- **默认分支**：Gitea 1.26.2 实测 `auto_init` 建仓默认分支是 **`main`**（非 `master`）。
  写死 `master` 会让写文件/读目录/文件链接全 404。现由 `RepoProviderClient.defaultBranch()`
  按托管方给值，且**以接口返回的 `default_branch` 为准**。套件 G3.2/G2.4 双端断言 `main`。
- **异常类型**：服务层不得 `catch (GiteeApiException)`（Gitea 抛中立基类 → 该分支永久不可达）。
  已全部改 `RepoProviderException`，并加**源码审计测试**守住。

## 三、⚠️ 环境限制：**Webhook 入站不可达**（不是代码问题，已用证据定性）

| 证据 | 内容 |
|---|---|
| `traceroute` | `192.168.1.1`（家用路由）→ `172.16.2.254`（上级路由）→ `172.16.8.249`。本机在 `192.168.1.0/24`，经两层路由/NAT 到达 Gitea |
| 反向路由 | 本机路由表**没有**到 `172.16.8.0/24` 的表项；Gitea 无回到 `192.168.1.53` 的路由 |
| 防火墙 | Windows 防火墙**三档全开**，且无该端口的入站放行规则（加规则需管理员提权） |
| 投递计数 | 建钩子 → `POST /hooks/{id}/tests`（204）→ 15s 内**本机 0 次投递** |
| 端点可用性 | Gitea 1.26.2 的 `/hooks/{id}/deliveries` 返回 **404**（该版本无此端点），因此无法从 Gitea 侧看投递明细 |

**影响面**：仓库、Webhook、成员、分支/内容**全部正常**（这些是出站调用）；只有
「Gitea 主动回调平台」这一段不通 —— 即 `gitee_event` 不会自动增长。

**两条可行路径**（按推荐度）：
1. **平台与 Gitea 同网段部署**（生产常态）：把 `AIOA_GITEA_WEBHOOK_BASE_URL` 配成
   **Gitea 能访问到**的平台地址即可，无需改代码。
2. **用无需入站的收敛手段**：平台的**定时校准**（`SYNC_ALL`）与**只读接口**
   （分支/目录/提交按需从 Gitea 拉取）本来就与入站无关，已实测可用（套件 G9/G10）。

本套件因此用「**本地构造 Gitea 格式报文 + 正确 HMAC-SHA256 签名**」直接投递到平台端点，
验的是**协议正确性**（校验/分类/落库/幂等），并明确标注它**不等于**网络可达性。

## 四、真机验到的协议细节（Gitea 1.26.2，修正了此前的推断）

| 项 | 实测 |
|---|---|
| 建组织仓库 | `POST /orgs/{org}/repos` `{name,description,private,auto_init}` → **201** |
| 默认分支 | `auto_init=true` → `default_branch = **main**`，`empty=false` |
| Webhook 事件扩展 | 请求 `push,pull_request,issues,issue_comment` → 实际落 **14 个**事件（含 `issue_milestone`/`pull_request_milestone` 等）⇒ 断言必须用**子集**而非逐字相等 |
| Webhook 密钥 | **只写不读**：`GET .../hooks/{id}` 的 `config` 里**只有** `url` 与 `content_type`，**不返回 `secret`** ⇒ 密钥正确性只能靠「签名投递被接受」来证明 |
| 投递签名 | `X-Gitea-Signature` = `HMAC-SHA256(原始字节, config.secret)` 的十六进制（无前缀） |
| 事件头 | `X-Gitea-Event` / 投递 id `X-Gitea-Delivery` |
| SSH 地址 | 实例开在 **2222**：`ssh://git@172.16.8.249:2222/AI-OA/{repo}.git` |
| 协作者 | `PUT .../collaborators/{u}` 需 **JSON body** `{permission}`（query 参数形式会 422） |
| 协作者（重复添加） | 已是协作者 → **204**（幂等成功，不报错） |
| 协作者（用户不存在） | → **422** `{"message":"user does not exist [uid: 0, name: xxx]"}` ⇒ **不可把 422 一律当成功**（见缺陷 7） |
| 错误体结构 | `message` 可能是**内部操作名**（如 `GetUserByName`），人话在 `errors[]` ⇒ 只取 `message` 会丢诊断信息（见缺陷 6） |
| `deliveries` 端点 | **该版本不存在**（404） |

## 五、复现步骤

```bash
# ① 起 Gitea 接线后端（同一时刻只允许一个后端实例！）
source .env.gitea-real && bash start-all.sh

# ② 跑真机套件（自净：用完删项目并连带删远端仓库）
python scripts/e2e_gitea_live.py
#    --keep  保留项目与仓库，便于手工核对

# ③ 探针（可选）：验建仓/默认分支/Webhook 回连可达性
python scripts/_diag_gitea_live.py

# ④ 界面文案核对（浏览器实渲染，自净：临时建项目→连仓删除）
python scripts/_check_gitea_ui_provider.py
```

`.env.gitea-real`（已 gitignore）关键项：
`AIOA_REPO_PROVIDER=gitea` · `AIOA_GITEA_BASE_URL=http://172.16.8.249:3000/api/v1`（**必须带 `/api/v1`**）·
`AIOA_GITEA_ORG=AI-OA` · `AIOA_GITEA_CLIENT_ID/SECRET`（截图给的 OAuth 应用）·
`AIOA_GITEA_WEBHOOK_BASE_URL`（**必须是 Gitea 能访问到的地址**）。

## 六、明确**未**验证的项（不假装通过）

1. **浏览器 OAuth 授权全流程**：`POST /gitee/bind/authorize` 已实测返回正确的 Gitea 授权地址
   （`{gitea站点}/login/oauth/authorize?...&scope=repo read:organization notification issue`），
   但**完成授权需要在 Gitea 登录页输入 `liujiejie` 的密码**，我没有该凭据，故
   「授权码 → 换令牌 → 落库」这一段仍停留在单测级。
   如需闭环：在浏览器点一次授权，或提供该账号密码/改用一次性授权码。
2. **Webhook 真实入站投递**：受第三节的网络限制，无法在本机验证（已用签名投递替代）。
3. **平台管理员视角的 Gitea 运维页**：未做 UI 级验证（本轮做 UI 级验证的是租户管理员视角的
   「项目与仓库」列表页与详情页，共 17 条断言）。
4. **日志里的平台名**：`log.*` 仍统一写「Gitee」（模块名、库表名也还叫 `gitee_*`）。
   已用源码审计**显式豁免**日志，理由是它不呈现给用户；彻底改需连同类名/表名一起重命名，
   属纯改名重构，见第七节第 3 条。
5. **历史「假绿」行不会自愈**：定时校准只补「非 SYNCED」的成员（`ne(sync_status,'SYNCED')`），
   **不复核已 SYNCED 的行**。因此托管方账号被删除/改名后，平台不会自己发现，那条成员会一直是绿色。
   现状：库中 82 条 SYNCED 行带登录名，其登录名在真机 Gitea 上均不存在（含桩时代的演示行）。
   **本轮刻意不改数据**：这些是演示/历史行，批量改状态属于改演示数据、不是修缺陷；且新代码已能阻止
   新假绿产生。若要让环境自证清白，最小动作是**重新添加一次成员**（会直接入队同步并落 FAILED + 归因文案）。
   若要让平台长期自证，需要「按 `synced_at` 老化后重验」的扫描 —— 代价是每轮校准多出与成员数同量级的
   外部调用，而该实例**已经在返 429 限流**，故本轮不引入这个新失败面（属待评估项，非遗漏）。

## 七、建议的后续（按性价比排序）

1. **接上入站**：同网段部署或加一条 Gitea 可达的映射 —— 这是唯一能把 Webhook 段提到「真机验证级」的手段。
2. **绑定行加平台标记**：给密文加 `enc:gitee:` / `enc:gitea:` 前缀，即可**区分**
   「异平台遗留密文」与「密钥被误改」——目前两者都是 Tag mismatch，只能靠日志提示，无法程序化判定。
3. `gitee_account` 等表名与类名已与实际（多托管方）语义不符，重命名可读性更好（纯改名，风险低）。
