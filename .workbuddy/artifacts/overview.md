# AIOA · 企业管理 → 项目管理 **Gitea 真机流程**交付概览

> 2026-09-18 · 仓库 `C:/Users/刘尖尖/WorkBuddy/aioa` · 实例 `http://172.16.8.249:3000`（Gitea 1.26.2）· 组织 `AI-OA`
> 详细证据：`gitea-live-verification.md`（真机跑通报告）· 交接单：`gitea-switch-readiness.md`
> 接口契约：`gitea-api-contract-1.26.2.md` · 上一轮（Gitee 真机建仓）记录归档在 `gitee-real-machine-delivery-archive.md`

## 1. 一句话结论

**「企业管理 → 项目管理」已在真实 Gitea 上端到端跑通，账号绑定（OAuth）也已经真实绑定成功**
（`gitee_account` id=98：tenant 0 / 平台管理员 `admin` → Gitea 账号 `liujiejie`，2026-09-18 15:20:50）。
五轮共抓出 **14 个「编译能过、启动能起、真机才炸」的缺陷**（全部已修 + 已加防回归），
另修掉三处**会掩盖真回归的等待/归因错误**、补上**一条此前完全没被覆盖的路径**。
仍受网络限制未闭环的是 **Gitea 主动回调平台**（入站）—— 已用证据定性并给出两条可行路径。
绑定链路的完整定位过程与证据：`gitea-oauth-bind-closure.md`。

> **第五轮（你复报「创建仓库失败」那一张截图）**：截图里的项目 `999 / dept101-999` 已修复，
> 现在 `ACTIVE`、仓库在 `aioa-demo-org/dept101-999` 上真实存在（`http=200`）。
> 顺着它查下去又抓出**两个新的真缺陷**（13、14），都在同一条「建仓闭环」上，详见 §3 末。

## 2. 实测结果

| 验证 | 结果 |
|---|---|
| `scripts/e2e_gitea_live.py`（**新增真机套件**，11 段，含新增 `G0a` 列宽闸门与 `G4.7/G5.4/G5.5` 事件词表断言） | **81 / 81 PASS**（连跑两次），0 FAIL，0 BLOCKED |
| `scripts/_check_gitea_ui_provider.py`（**新增**，浏览器实渲染核对托管方文案） | **17 / 17 PASS** |
| `scripts/_check_gitea_cfg_failure_ui.py`（**新增**，配置拉取失败的归因核对） | **16 / 16 PASS**（abort / HTTP 500 两种失败形态 + 「重试」自愈） |
| `aioa-gitee` 单测（含防回归 + 1 条源码审计） | **165 / 165**（`mvnw clean package` 全量，0 失败 0 错误） |
| 前端类型检查 `vue-tsc --noEmit` | **exit 0** |
| `e2e_v51_gitee_init` · `e2e_v48_gitee` · `e2e_full_system --no-browser` | **50/50 · 116/116（连跑两次）· 145/145**（已知缺口 0） |
| **绑定已真实成功**（最强证据） | 绑定行密文 **1188 字符** —— 旧列 `VARCHAR(1024)` 必被截断；日志 `Gitea 绑定成功 tenant=0 user=1 gitee=liujiejie(11)` |
| **存进去的令牌是活的**（闭环终验） | 解出密文：明文 **858** 字符（与日志 `token=858` 一致，未截断）→ 拿去真实 Gitea：`GET /user` **200** `id=11 liujiejie`（与库中登记一致）· 可读 **11** 个仓库 · 组织 `['AI-OA']` |
| 真库容量实证 | 严格模式下 4096 字符密文写入并读回等长 |

真机实测产物：项目终态 `ACTIVE`；仓库 `AI-OA/dept11-*` 存在、`default_branch=main`、私有；
Webhook `active=true`/`type=gitea`/事件覆盖 push·pull_request·issues；删项目后远端仓库回查 404。
界面实测：页头「项目与仓库（Gitea 联动）」、卡片「我的 Gitea 账号 / 本企业 Gitea 组织 / 企业 Gitea 初始化」、
表头「Gitea 账号 / Gitea 事件」、危险操作「删除 Gitea 仓库」，**整页不出现「Gitee」字样**。

## 3. 修掉的 14 个真机缺陷

> 第一轮（建仓→Webhook→成员→事件）抓到 1–3；第二轮补做**界面与文案面**，抓到 4–7；
> 第三轮（你发来绑定失败截图后）抓到 8；第四轮（绑定成功后你复报两个现象）抓到 9–12；
> 第五轮（你复报「创建仓库失败」）抓到 13–14。
> 定位全过程见 `gitea-oauth-bind-closure.md`。
> **注意 9–12 与 13–14 的共同点**：都是「把系统自己造成的现象说成别的原因」，
> 或者反过来 —— **系统失败了却不告诉用户**（13）。这就是这个项目里反复出现的同一类缺陷。

1. **建项目 500**（阻塞级）：切托管方后个人绑定密文解不开（`AEADBadTagException: Tag mismatch`），
   而代码只在「查不到绑定」时才回落企业令牌 ⇒ 硬 500。
   **修**：解密失败按「本平台无此绑定」处理并回落企业令牌；无企业令牌才报错，且文案指名**当前生效**的密钥键。
2. **`gitee_account` 没有托管方维度**（正确性级）：绑定行存的其实是某一平台的身份（uid/登录名/该平台密钥加密的令牌）。
   切平台后 Gitee 的登录名会被拿去 Gitea 加协作者 → 404 静默失败；同一用户也无法并存两平台绑定。
   **修（V54 迁移）**：加 `provider` 列（74 条老行回填 `gitee`）+ 唯一键并入 `provider`/`gitee_uid` + 查询按 provider 过滤。
3. **密钥报错说错配置键**（可运维级）：gitea 下让用户去改 `aioa.gitee.token-enc-key`。
   **修**：新增 `RepoProviderSettings.tokenEncKeyProperty()`，文案随 provider。
4. **整页界面文案写死「Gitee」**（界面级）：页头/卡片/表头/按钮/确认框/Toast/OAuth 结果页一律「Gitee」，
   而仓库地址全指向 `172.16.8.249:3000`；「未启用」提示还让人去改 `aioa.gitee.*`；
   初始化对话框说「令牌需具备 `projects` 权限」（Gitea 令牌页没有这个选项）。
   **修**：端口加 `providerLabel()` / `configKeyPrefix()` / `tokenRequirementHint()`；
   `/gitee/config` 回 `provider / providerLabel / configKey / tokenRequirementHint` 作为**前端文案唯一来源**；
   前端两页按 `pName` 渲染；后端 13 处用户可见文案改拼接；
   **新增源码审计测试**：`service|controller|support` 下 `Gitee ` 只准出现在注释或 `log.*`。

同轮真机确认：`auto_init` 建仓默认分支是 **`main`**（非 `master`，写死会让读写文件全 404）；
服务层不得 `catch (GiteeApiException)`（Gitea 抛中立基类，分支不可达）。

5. **删项目后成员同步任务空转到重试上限**（队列卫生级）：`softDelete()` 只撤 `biz_type='PROJECT'`
   的任务，而成员任务的 `biz_id` 是成员行 id ⇒ 撤不到；handler 又把「项目已不存在」（终态）
   与「仓库还没建出来」（瞬时）合并成同一个可重试异常。**修**：`project == null` 直接作废
   （与同方法里「成员已被移除」同一口径），只有「项目在、仓库未建出」才重试。
6. **失败原因把托管方原文抛给用户**（界面级）：`member.lastError` / `project.errorMsg` 里是
   `GetUserByName`、`Rate Limit Exceeded`、`401 Unauthorized: Access token does not exist`
   —— 而这两个字段**直接渲染给租户管理员**（成员表悬浮说明、项目详情红字告警）。
   两条成因：① `extractMessage()` 只取 Gitea 错误体的 `message`，丢了唯一含人话的 `errors[]`
   （Gitea 的 `message` 可能是内部操作名 `GetUserByName`）；② 落库前不做本地化与归因。
   **修**：`errors[]` 优先；新增纯函数 `ProviderFailureText` 按状态给「中文归因 + 可执行动作」
   并把原文附末尾；两个落库点改走它；单测 20 条 + 真机断言 3 条。
7. **422「用户不存在」被当成「已是协作者」→ 成员假绿**（正确性级，最危险）：
   Gitea 对 `PUT .../collaborators/{不存在的用户}` 回 **422**，而
   `isAlreadyCollaborator()` 把 **422 一律**当「已在协作者中」⇒ 权限根本没加上，
   管理端却显示绿色「已同步」。**修**：判据改为「4xx **且**文案明确说已是协作者」
   （Gitea 真正重复添加时回 204，不走该分支）；单测 6 条 + 真机断言（必须落 FAILED 而非 SYNCED）。
   *这条是在为缺陷 6 写真机探针时反查出来的 —— 探针拿不到 FAILED，追下去才发现是产品判错了。*

同轮一并修掉一个静默失效：`setErrorMsg(null)` / `setLastError(null)` 这类「清空」写法在
MyBatis-Plus 默认 `NOT_NULL` 策略下**一直是空转**（库里 17 个 ACTIVE 项目仍挂着旧的
`Rate Limit Exceeded`）。给这两个字段显式声明 `updateStrategy = ALWAYS`，并用真机断言
（写脏 → 重试 → 回读为空）钉死。

8. **换令牌失败的具体原因被丢弃**（可运维级，第三轮）：**你那张截图里只剩
   `原因：unauthorized_client`**，无法据此定位。成因有两层：
   ① 托管方侧 —— Gitea 登记的那个 OAuth 应用密钥**形态不对**（登记页显示 `qto_` 前缀，
   而该版本生成/校验的是 `gto_` 前缀），**怎么传都过不了校验**；编辑页把库里的失效值原样显示，
   所以「复制无误」这个直觉是错的。
   ② 我们这侧 —— `firstDetail()` 只取错误体的 `error`，而 Gitea 把 `error` 恒写成通用码
   `unauthorized_client`，**真正的原因在 `error_description`**（`invalid client secret` /
   `client is not authorized`），被整段丢掉 ⇒ 两种截然不同的故障显示成同一句话。
   **修**：换用新应用（新 `client_id` 已写入 `.env.gitea-real`，旧应用已删除）；
   `firstDetail()` 改为 `error_description` 优先并保留 `error` 码（页面现在显示
   `client is not authorized（unauthorized_client）`）；`errors[]` 的优先级**不变**
   （不破坏上一轮缺陷 6 的修复）；单测 6 条，含「两种故障不得被判成同一字符串」。
   同时把绑定失败页也接上 `ProviderFailureText.forOauthBind()`：原因从**托管方英文短语**
   改为「中文归因 + 可执行动作 + 原文附尾」，并把「平台配置问题」与「授权码问题」
   分成**两句不同指引**（前者让用户找运维，后者让用户重新发起），单测再 +6 条。

9. **令牌写库被列宽截断**（阻塞级，第三轮后你第二次点授权）：回调页只剩一句裸 SQL
   `失败原因：Data too long for column 'access_token'`。这一条**不是猜的**：日志里被拒的是
   `GiteeAccountMapper.insert` 的 `INSERT INTO gitee_account`（`MysqlDataTruncation`，15:01:53 / 15:02:05 各一次），
   而取身份那行代码在 INSERT **之前** ⇒ **授权、换令牌、取身份三步都已通过**，
   缺陷 8 确实已消失，卡在最后一步写库。
   成因：列宽是照 **Gitee 的令牌形状**定的（32~40 字符短随机串 → `VARCHAR(1024)` 从没被顶到过），
   而 **Gitea 签的是 600~1000 字符的 JWT**（RS256 签名本身就 ≈342 字符），
   入库前再经 AES-256-GCM + base64（≈×4/3）⇒ **≈850~1400 > 1024**。
   **修（V55 迁移）**：`gitee_account.access_token` / `refresh_token` → `TEXT`，
   `scope` 255→1024；`gitee_tenant_config` 同步放宽。**只动这 5 列**：
   `gitee_username`(128/实测 9)、`gitee_name`(128)、`avatar_url`(512/实测 86) 上界由**托管方身份字段**定，
   与令牌形态无关，**没有跟着一起改**（避免投机式扩宽）。
   同轮两处加固：① 写库**之前**打一行**只记长度不记值**的日志（`令牌长度 token=861 refresh=0 scope=46`），
   下次同类问题日志里直接有实际规模；② 失败文案新增「截断」分支，
   排在 `scope`/`permission` **之前**（列名恰叫 `scope` 时也含 "scope"，顺序错会误判成「用户没勾权限」），
   文案点明「**属平台缺陷，与你的账号无关**」。
   *这一条最值得记的是它暴露的**覆盖缺口**：事发的当下 21 个套件全绿 —— 不是断言写松，
   而是「没有覆盖」（所有套件都不做真实浏览器授权，「加密→写库」这一步从没被测过）。
   已补 `[G0a] 列宽闸门` 4 条断言（容量 + 严格模式），且**放在 `main()` 最前面、不依赖凭据与网络**。*

> **绑定此后真实成功**（15:20:50，见 §2）。你随后复报「认证通过但解绑刷新失败，切换部门时也出现」——
> 直接成因是**我为让 V55 生效重启了后端**（日志侧：15:20:50 之后后端零条记录，
> 那次解绑请求根本没到，绑定行至今 `alive=1`）。
> 但它顺带暴露下面三个**与重启无关、会再犯**的缺陷 —— 它们和你截图里那三句错话一一对应：

10. **把「服务不可达」说成「去改配置」**（界面级，归因错误）：
    你截图里那句 `后端尚未配置 aioa.gitee.*…请联系系统管理员开启配置` 是**假的** —— 配置一切正常，
    只是服务当时不在。成因：`loadConfig()` 的 catch 与 `enabled===false` **共用同一个
    `moduleEnabled=false`**，于是网络错误/5xx 也落进「未启用」分支。
    **修**：拆出 `configError` 独立状态 + 专属 error 横幅 + **「重试」按钮**；
    只有**服务明确回 `enabled=false`** 才显示「未启用」。
    *判据是「服务有没有说」而不是「拿没拿到」—— 这两件事必须在状态上就分开。*
11. **不知道托管方，却自称托管方**（界面级）：页头用 `pName`（回落 `'Gitee'`）拼串，
    gitea 接线下**服务不可达**时整页回落成「项目与仓库（**Gitee** 联动）」——
    截图里那句正是这么来的。**修**：新增 `providerKnown`（= 配置是否真的取到），
    不知道时页头只写「项目与仓库」、副标题也不再指名托管方。
    *回落值不能冒充事实：「不知道」就说不知道。*
12. **绑定成功页反向告警**（界面级，最讽刺的一条）：`GiteeOauthController` 的
    「非官方站点」告警**写死比 `gitee.com`**。而自建 Gitea 的真实站点 `172.16.8.249:3000`
    **本来就不是** gitee.com ⇒ 判定为「桩」⇒ **绑定成功后**页面上出现
    「⚠ 本次授权未经过真实 Gitea」。
    **修**：判定收进随 provider 变的 `RepoProviderSettings.authorizeHostIsSandbox()`
    （Gitee 侧参照 `gitee.com`；Gitea 侧参照配置里的 `web-base-url` 域），控制器不再自行比较域名；
    单测 4 条 + 设置端单测 4 条钉死「真实站点不得被判成可疑」。
    另修 `unbind()` 的**归因混淆**：解绑成功后的「刷新」失败也报「解绑失败」，
    会让人以为没解开而反复点 —— 现在拆成「解绑失败」与「已解绑，但刷新页面数据失败」两句。

13. **项目永久卡在「创建中」、且界面上没有任何失败提示**（阻塞级，第五轮，**你截图那条的真正同类问题**）：
    状态机是 `CREATING --(建仓 + 配 Webhook 都成功)--> ACTIVE`，而建仓与配 Webhook 是**两条任务**。
    `GiteeRepoTaskHandler` 只在**建仓**失败时回写项目状态，**配 Webhook** 失败时只把**任务**判死 ——
    项目因此**永远停在 `CREATING`**：列表页显示「创建中」，没有红字、没有原因，
    而定时校准只处理 `ACTIVE` 项目 ⇒ **没有任何东西会再来动它**。用户唯一的感受是「点了没反应」。
    真库实测受害 4 条（69/77 租户 2 · 82/83 租户 9）。
    **修**：`configureWebhook` 与 `createRepo` 对称 —— 失败即 `markFailed` 回写项目；
    新增纯函数 `ProviderFailureText.forWebhookStep()`，文案讲清「**建仓其实已经成功**、
    卡在配 Webhook 这一步、点「重试建仓」只重跑这一步」；
    单测 +3 条（含「原因为空时不得拼出 `：。`」与「托管方名按入参走」）。
    **V56 迁移**把已经卡死的历史行补成同样的终态（判定条件含「无在途任务」与「确有 FAILED 的
    CONFIGURE_WEBHOOK 任务」，不会误伤正在创建中的项目）。
    *这条正是缺陷 9–12 的镜像：那几条是「说错原因」，这条是「**不给原因**」。*
14. **项目详情页「事件」列把 Gitee 词表显示给 Gitea 项目**（界面级，第五轮）：
    `saveWebhook()` 落库写死 `push,merge_requests,issues,notes`（Gitee 词表），
    而已知缺陷 4 修的是**界面模板**、这一处是**落库的展示字段**，所以漏网。
    后果：详情页逐条渲染成标签，用户可以拿着它去仓库的 Webhook 设置页核对 —— **一核就是错的**
    （Gitea 上真实订阅的是 `pull_request` / `issue_comment`，`merge_requests` / `notes` 在 Gitea 上不存在）。
    **修**：接口新增 `RepoProviderClient.hookEventNames()`，两家各自实现
    （Gitea 直接复用建钩子用的 `hookEvents()` ⇒ 展示与事实**同源**）；
    `saveWebhook` 改走它；新增 `RepoProviderHookEventsTest` 4 条，其中一条断言**两家词表互斥**；
    真机套件 +3 条断言（`G4.7` 平台登记词表 / `G5.4` `G5.5` 接口出的词表）。
    **V57 迁移**把 120 条历史行改回托管方真实词表 —— 而**在 gitee.com 上的 4 行原样保留**
    （那些行的 Gitee 词表本来就是对的）。
    *真机套件确实把它变成红色：`G5.1` 回读的就是 `push,pull_request,pull_request_review,issues,issue_comment,pull_request_review_comment`。*

> **V56 自己踩了同一个坑（值得单记）**：V56 回填时**照抄了任务队列里的历史原文**，
> 而那段原文产生于平台还是 Gitee 接线的时候，里面带着「Gitee 无法回调本机地址」——
> 于是修复动作把「错误托管方」从代码搬进了**数据**。**是 `_check_gitea_ui_provider.py` 的
> `L3 整页不出现「Gitee」字样` 把它抓红的**（16/17 → 定位 → 改；V58 迁移改成
> 与托管方无关的说明后回到 17/17）。
> 教训：**回填数据时，历史原文不是「事实」，它带着当时的环境**；用户可见字段宁可中性化，
> 细节指向唯一权威位置（任务队列）。

## 4. 关键决策

- **默认仍 `provider=gitee`**：现有部署行为逐字节不变（文案回落值也取 `Gitee`），切 Gitea 只需改环境变量 + 重启。
- **老绑定不自动清理**，只在查询时按 provider 过滤跳过（老绑定是审计事实，自动删数据不可逆）。
- **成员未绑定时保持 `PENDING` + 可执行原因**，而不是 FAILED/静默——这是「不静默失败」的一贯口径。
- **断言不写死计数**：Webhook 事件名会被 Gitea 自动扩展（请求 4 个实落 14 个），断言用**子集**关系。
- **失败文案不丢原文**：中文归因在前、托管方原文在末尾括号 —— 用户看得懂，运维仍可追溯。
- **历史「假绿」成员行不改数据**：定时校准只补非 SYNCED 的成员，不复核 SYNCED 行 ⇒ 桩时代的演示行
  会一直显示绿色。本轮**刻意不批量改状态**（那是改演示数据，不是修缺陷），新代码已能阻止新假绿产生；
  详见 `gitea-live-verification.md` 第六节第 5 条（含「为什么不引入老化重验」的代价说明）。
- **日志仍叫「Gitee」**（模块名、`gitee_*` 表名也是）：审计显式豁免日志，彻底改属纯改名重构，不与本次混做。

## 5. 需要你决定 / 后续

1. **Webhook 入站**（唯一未闭环）：本机在 NAT 后且防火墙未放行，Gitea 无法回调。
   可行路径：① 平台与 Gitea **同网段部署**并把 `AIOA_GITEA_WEBHOOK_BASE_URL` 配成 Gitea 可达地址（生产常态）；
   ② 用**定时校准 + 只读接口**（无需入站，已实测可用）。
2. **账号绑定（OAuth）✅ 已闭环**（2026-09-18 15:20:50 实测成功）。
   三处故障全部修复并验证：① 旧应用密钥在托管方侧**无法通过校验**（已换用新应用，
   `client_id` = `a2e8f7bd-8f0b-4a2f-a1e5-345b5741b0cd`，旧应用已删除）；
   ② 回调写库时令牌被列宽截断（**V55** 把令牌列放宽为 `TEXT`）；
   ③ 成功页把真实自建 Gitea 误判成桩而反向告警（判定已收进随 provider 变的设置端）。
   完整过程、证据与「为什么不是你的密钥复制错了」见 `gitea-oauth-bind-closure.md`。
   **若要换绑**：先在「我的 Gitea 账号」点「解绑」，再点「绑定 Gitea 账号」走一次授权即可。
3. **你截图里那条「创建仓库失败」的处置结果（第五轮）**：
   根因是**租户 9 的 Gitea 组织配的是桩时代的名字 `aioa-demo-org`，而真实实例上没有这个组织**
   （该配置行还是桩时代写下的：`enabled=1`、`org_name=aioa-demo-org`、**没有企业令牌**、
   `init_status=PENDING`），建仓自然 404。已在真实 Gitea 上补建该组织，
   并让租户 9 管理员重跑一次「重试建仓」⇒ 项目 `999 / dept101-999` 现在 **ACTIVE**，
   仓库 `aioa-demo-org/dept101-999` 真实存在（`http=200`、`default_branch=main`、你选的 public）。
   **仍建议你做一次（可选但推荐）**：用租户 9 管理员进「项目与仓库 → 企业 Gitea 初始化」，
   用**真实企业令牌**重跑一次初始化，把那一行的 `org_name` 改成你真正想用的组织
   （例如 `AI-OA`）并让 `org_verified` 落上 —— 否则那一行会一直「能用但来路不明」。
4. 建议（非必须，按性价比）：
   - 给令牌密文加 `enc:gitee:`/`enc:gitea:` 前缀，即可程序化区分「异平台遗留密文」与「密钥被误改」
     （目前两者都是 Tag mismatch，只能靠日志提示）。
   - `gitee_*` 类名/表名/日志文案统一改名（纯重构，风险低但改动面大）。

## 6. 本轮收口

| 项 | 值 |
|---|---|
| 提交 | `b829432` `feat(V53-V58): Gitea 托管方迁移收口 —— provider 抽象、绑定闭环与 14 项真机缺陷`（130 files，+10720/−2144；工作树已清空） |
| 推送 | GitHub `github/main` **`b829432`** —— 与本地 `git rev-parse HEAD` **逐字符一致**（不靠 push 返回码判定） |
| 库态 | Flyway 至 **V58**；创建中项目 **0** 条；`error_msg` 含「Gitee」的 **0** 条；队列无 `PENDING`/`RUNNING` 残留 |
| 目标项目 | `999 / dept101-999` → `ACTIVE`，接口回读 `events = push,pull_request,pull_request_review,issues,issue_comment,pull_request_review_comment` |
| 运行态 | 后端 :8080（`provider=gitea`，V58）· agent :8000 · 前端 :5173 均在监听 |
| 未入库 | `scripts/e2e_*.py` 按仓库既有约定 gitignore（本次新增的 3 条真机断言因此只在本机可见，已在记忆与技能中留档） |
| 新增忽略 | `scripts/_diag_*` `_tmp_*` `_q.py` `_*.png`（一次性诊断产物）；`_check_*.py` **刻意不入此列**，它们是要留的回归探针 |
