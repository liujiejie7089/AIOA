# E2E 套件矩阵与断言纪律

> 摘自 `MEMORY.md §5`（2026-09-19 拆分）。**收口验收 / 写新套件前先读本文件**。
> 套件脚本在 `scripts/` 且已 gitignore，不入库。

## 5. E2E 套件矩阵（`scripts/e2e_*.py`，已 gitignore 不入库）
- **收口必跑**：`e2e_full_system.py` **155/155**（13 段跨层串联；`--no-browser` 跳渲染段）。跑前先 `ls scripts/ | grep -E "^e2e_"`（套件会因 gitignore 凭空消失，别照抄本表）。只改前端也必须跑 `vue-tsc --noEmit`。
- **按钮级全量 UI（2026-09-19 新增）**：`e2e_v61_h5_all_buttons.py`（H5 **27/27**，运行时枚举 `onclick`，冒烟点 93 键）· `e2e_v61_shell_all_buttons.py`（管理端 **145/145，0 JS 异常**：admin 49 · znkj_admin 45 · znkjyf_admin 19 · znsfb_ldr 17 · znsfb_m01 15）· wrapper `run_v61_shell_buttons.sh`。
  **铁律：管理端按钮级测试必须逐角色分进程**（单浏览器连跑 20+ 路由 + 上百点击 ⇒ Edge renderer 资源耗尽挂起）。稳定三板斧 = `goto(wait_until="commit")` + 越权断言用 `page.url`（免 evaluate 挂起）+ 按钮枚举单次 `evaluate`；点击 `locator.click(timeout=2000, no_wait_after=True, force=True)` + 每次 `Escape` 关弹层；只跳破坏性/真实网络/空文本（树箭头）按钮，跳过清单**过宽会「点 0 个」失去意义**。
- **基线（2026-09-17~19）**：`e2e_v48_gitee`116 · `e2e_v51_gitee_init`50 · `e2e_gitea_live`81 · `e2e_v50_tenant_org`54 · `e2e_v52_message_center`47 · `e2e_leave_flow_notify`19 · `e2e_v45_approver_modes`44 · `e2e_v45_misc_fixes`27 · `e2e_v45_config_ui`25 · `e2e_v43_dept_applicant`41 · `e2e_v43_cc_read`41 · `e2e_v41_duty_levels`48 · `e2e_v39_applicant_superior`49 · `e2e_v36_grant_expert_review`64 · `e2e_admin_personnel_scope`57 · `e2e_v32_org_scope`51 · `e2e_v36_stats_clamp`66 · `e2e_v33_roles`41 · `verify_v51_repo_urls`23 · `verify_v51_repo_urls_ui`18 · `verify_v50_ui`28 · `h5_v33_render`28 · `admin_v39_todo_badge`17 · `_check_gitea_ui_provider`17 · `_check_gitea_cfg_failure_ui`16 · `agent/tests` 42 passed · `aioa-gitee` 单测 165 · **`e2e_v62_milvus_kb` 25（mysql 档；milvus 档未跑）**（以上均为 `N/N` 全绿）。
- **本地哨兵**（非 e2e 命名）：`_syntax_h5.js` · `_refaudit_h5.js`（H5 内联 `onX="fn()"` 悬空引用——单文件 H5 无打包器无类型检查）· `_check_menu_scroll.py`（27 项）。改 H5/管理端布局后顺手跑。
- `h5_v33_render` **（该套件现已不在 `scripts/`）**：本条曾把它的红写成「假红」，2026-09-22 查明**是误判**，保留原文以记住教训 ——
  原文：「其『AI 解读』段依赖 agent，若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判。」
  **真相**：那不是假红，是**真缺陷**（后端默认 HTTP/2 客户端发 h2c 升级 ⇒ uvicorn 丢请求体 ⇒ 422），见 `pitfalls.md` #55–#57。
  `envs/default` 当时「能过」只是因为它装着裸 uvicorn（落到 h11，h11 恰好保住 body），而 `agent/.venv` 与**生产镜像**都是 httptools ⇒ 会显形。
  **结论**：agent 现在由 `start-all.sh` 显式 `--http httptools` 起（与生产一致）；凡「换个启动姿势就不红了」的结论，必须先把两种姿势的行为差异查清再下判。
- **后端→agent 传输三件套（2026-09-22 新增）**：`_check_agent_httpclient.py`（静态守卫，正向 8/8 + 负向自检 4/4）· `e2e_worker_schedule_exec.py`（**18/18**：反掩盖前置 + 手动执行 + 到点执行 + 意图识别走 agent，**约 80s，含等整分**）· `_probe_agent_h2c.py`（判别 agent 在 httptools 还是 h11）。
  **前置依赖**：`e2e_worker_schedule_exec` 会先跑 `_probe_agent_h2c`，若 agent 跑在 h11（返回 200）则该用例**故意报红**并说明「本套件通过说明不了问题」——这是刻意的，别为了让红变绿去改它。
- **知识库共享可见性三件套（2026-09-21 新增）**：`e2e_kb_share_visible.py`（**31/31**，两次连跑均绿；A 权限口径 / B 共享可见性+跨租户零泄露+PERSONAL 不外泄 / B6 列表与检索同源 / C 看与改同源含 3 条反断言 / D 管理端真浏览器 / E 用户端 H5 渲染且断言 `is_visible` / **F 静默截断 5 项**）· `_check_kb_permission.py`（静态守卫，正向 6/6 + 负向自检 4/4）· 探针 `_probe_kb_accounts.py`（纯 HTTP 扫全部账号的列表/租户/机构三口径）、`_probe_kb_console.py`、`_probe_kb_share.py`。
  套件用 `finally` 保证清理；造的资料带 `KBVIS<run>` 前缀。**写「看不到数据」类缺陷先跑 `_probe_kb_accounts.py`**：只要有一个账号拿到数据，「数据/迁移」方向即为错。
  **探针注意**：`#kbList` 在 H5 的「我的」页（`#page-me`）里，先 `go('page-me')` 再操作，否则元素「读得到文本但不可见」，`click()` 会 30s 超时。

### 断言纪律（写新套件必读）
- **禁固定页长/绝对条数**：用 `len(items)==min(total,size)`。判据：数据涨 10 倍、清库后该断言还成立吗？
- **审批用例先确认「申请人所在部门」的负责人**：首节点指派 = 该部门 `org_department.leader_user_id`。`fagai_li` 在 **dept 11**，负责人是 `fagai_admin`(user 4)，**不是** dept10 的 `fagai_liu`(user 7)；用错人 → `decided=0`。
- **配额类套件必须自治**：`fagai_li` 年假仅 10 天；段首顶到「已用+10」；撤销链路用**不占额度**的事假；不传 `days` 且落周日返回「申请天数为 0」。
- **分清「口令/选择器改动」与「真回归」**：1001=口令错，1004=租户名不匹配；**按 `password_hash` 反查真实口令**再断言。
- **改权限/可见性/生效态/登录口径后必须全局搜既有套件旧口径断言并连跑两次**。历史遗留行 ≠ 代码 bug；可回填就**加 Flyway 回填迁移修数据、断言原样保留**。**绝不为转绿而放宽断言。**
- **动真实租户级配置的验收，`finally` 必须按「原字节」还原**（先登记 `(id, 原 steps_json)`）。
- **管理端配置页验收要「渲染 + 往返」**：用 **label 文本**匹配渲染出的控件，做「打开弹窗不改动直接保存 → 断言与保存前完全一致」，再种一个**页面没建模的键**确认它活下来。范本 `scripts/e2e_v45_config_ui.py`。

## 5.3 ⚠️ `_run_all_regression.sh` 在本机**不能当零回归判据**（2026-09-22 实测）

**背景**：2026-09-20「批次 4」有意把本地库收敛到与生产首启一致（Flyway 只播 tenant 0/2/3），
tenant 9 全清（5866 行 / 44 表）。当时记录了代价，本轮把它**量化为四桶**（34 个 runner 套件：通过 3 / 失败 31）：

| 桶 | 数 | 判据（怎么一眼认出来） |
|---|---|---|
| A 演示数据集换代 | 21 | 首错是 `登录失败 <t9/jyj 账号>：code=1001`。**查库定案**：`SELECT COUNT(*) FROM sys_user` = 16，且这些名字**连软删行都没有** |
| B Gitee 桩未启动 | 4 | `httpx.ConnectError [WinError 10061]`，目标 `:8090` |
| C runner 引用的套件文件已不存在 | 5 | `python: can't open file` → exit=2 |
| D 套件期望 vs 现行实现 | 1 | `_check_menu_scroll.py` 断言分组名「安全与治理」，**HEAD 版就已改名「权限与安全」**（`git show HEAD:...MainLayout.vue` 为证） |

**在这个环境里真正有效的回归面 = 面向现库的套件**（跑 `_run_all_regression.sh` **之后**补跑）：
`e2e_v59_bridge_tool_invoke` · `e2e_v59b_tool_sdk` · `e2e_v60_workflow_ext` · `e2e_v61_h5_all_buttons` 27/27 ·
`e2e_v62_default_ai` **79/79** · `e2e_v62_admin_default_ai_ui` 9/9 · `e2e_agent_orchestrator` · `verify_config_effect` 11/11 ·
`e2e_v63_single_port` 51/51 · `e2e_v64_expert_template` 25/25。
`e2e_sdk_token_origin` 红在 `E0-1 子应用 iframe`：根因是 **`app_registry` 表 0 行**（demo 子应用未注册）= A 桶。

**`e2e_v62` 的 79 项构成（2026-09-22 扩容，由 64 项而来）**：A 静态 26（新增 A6b/A6c/A9/A10/A2b，把「满屏是基样式、媒体查询只留宽屏反例」「手机壳色值 `#14181f` 与死尺寸已清零」「回答层级渲染对所有会话生效」「copyText/guide-copy 无残留」都锁住）；B 纯函数 15（**推荐精准匹配语义全在这里**：相关⇒只出命中、无关⇒只留兜底、多命中按分排序、cap 不挤兜底）；C 接口 14；D 浏览器 24。
**分层原则**：**语义（该不该推荐某位专家）放 B 用真实源码在 node 里跑；接线（DOM 是否渲染、按钮点了会不会重发）放 D**。D 组验「精准匹配」用的手法是**直接调 `guidanceBlock()` 造块**（真实源码 + 真实目录 + 造好的问句），而不是真发两次模型 —— 后者既慢又不可控。
**纪律**：向用户报回归时，**先查库/查日志把每条失败归到桶**，再决定说不说「零回归」。
把「不可运行」写成「通过」、或把「需要重建演示数据」写成「已零回归」，都是报告失真。
2026-09-28 复核一例：`e2e_login_tenant_name.py` 属**桶 A**（不是回归）。它的第 3/4 节硬编码账号
`znkjyf_admin`（tenant 9），而 t9 连同 `znkjyf_admin` 在库里**连软删行都没有**（`org_tenant id=9` 也是 0 行）；
第 1 节的租户枚举是 `id >= 2` 的**全部**租户，于是把遗留租户 30 的 `test` 账号也卷进来，
而该账号口令**不在**候选集（`User@123/Admin@123/123456`）里，`resolve_password` 静默回落到 `User@123`
⇒ 拿到的 1001 被报成「租户名被拒」。**判据**：见到 `1001`（而非 `1004`）先查库确认是口令还是口径，
别把它当口径回归。
`seed_multi_tenant.py` 能重建租户但**给不出旧的硬编码 id**（套件里写死 3142–3145）⇒ 恢复旧基线 = 改套件，
属明确不做。

## 5.4 写「校验器 + 负向自检」时的坑：替换机制必须够得到被测代码

`scripts/_check_single_port.py` 的负向自检靠 `_OVERRIDES = {rel: 替换文本}` 让 `read()/exists()/hit()` 返回假内容。
**若某段逻辑直接 `p.read_text()` 读盘，就绕过了 `_OVERRIDES` ⇒ 那段永远无法被负向自检证明「被写坏会报红」。**
真实踩到：c4（叠加文件已清理）的文本扫描就是直接读盘，加了一条针对它的突变却**不报红**，
看上去像「白名单把检查吞了」，实为机制够不到。修法：扫描也走 `read(rel_key)` + `exists(rel_key)`。
**判据：每条检查项至少要有一条突变能让它报红**；加断言时必须同步加突变，否则等于没有防线。

## 5.5 2026-09-27 复证：`_run_all_regression.sh` 的失败**仍是同一批桶**，且**必须先把外部依赖起全**

本轮（用户反馈 8 项修复后的收口）重跑，结论与 §5.3 **完全一致**，并补三条可复用事实：

1. **桶 A/B 判定照旧成立**：`jyfzyjy_admin` / `jyj_admin` / `znkj_admin` / `znkjsc_admin` 在库里**连软删行都没有**
   （`SELECT username FROM sys_user` 只有 16 个业务账号 + E2E 账号）⇒ 这些套件**不是回归**，是演示数据集换代。
   `e2e_v50_tenant_org` 还额外需要 Gitee 桩 `:8090`（桶 B）⇒ 双重阻塞，直接跳过。

2. **失败的第一归因是「外部服务没起」，不是代码**。本轮先跑了一次「有效回归面」，
   5 个套件 exit=1，**全部**落在三类外部依赖上：
   | 症状 | 缺什么 |
   |---|---|
   | `ConnectException`（`agent_health*` 工具调用失败） | agent `:8000` |
   | `httpx.ConnectError [WinError 10061]`（orchestrator） | agent `:8000` |
   | `Page.goto: net::ERR_CONNECTION_REFUSED at 127.0.0.1:5181` | H5 `serve.py` |
   | `... at localhost:5173/experts` | 管理端 `pnpm dev` |
   | `[FAIL] D11 agent(:8000) 在线` | agent `:8000` |
   **起全 4 个服务后原样重跑，5/5 转绿**（v59_bridge ✅、orchestrator ✅、single_port **44/44**、v62_default_ai **79/79**、v62_admin_default_ai_ui **9/9**）。
   ⇒ **判「零回归」之前，先确认 8080/8000/5181/5173 都在监听**；否则会把环境当回归，或更糟——把回归当环境。

3. **`&` 起的服务会随 bash 调用结束被杀**（子进程组一起走），现象与「被外部回收」一样是**静默消失**。
   本会话内应急用后台任务（`run_in_background`）能活得久些，但要长期跑仍须用户在自有终端执行 `start-all.sh`。

### 5.5.1 一个**未解释**的环境现象（写下来避免下次重踩）

`POST /api/v1/admin/content-reviews/expert_config/{id}/review` 在**某些脚本上下文里稳定 401**
（`未认证或令牌无效`），而**同一令牌**紧邻的 `GET /api/v1/admin/roles` 返 200。已排除：
- 令牌吊销（`revoked_token` 无新增行，最近一条是 09-24）
- 令牌为空（debug 打印过 `tok_is_none=False`）
- 权限不足（那是 403；用租户管理员打确实返 403，说明鉴权链本身正常）
- 请求体编码（ASCII note 与中文 note 都复现）
同款代码在**另一个脚本里 3/3 通过**，说明是**间歇性**的。⇒ 收口时改用**确定性路径**：
临时把 `sys_config` id=59（`approval.tenant.content`）置 `false`（写库即生效、finally 原字节还原），
让租户管理员的团队层配置**直接 APPROVED**，**绕开这个放行调用**。
若日后要动审核链路，**第一件事是把这个抖动查清**（它是真缺陷还是环境所致，目前不敢定）。

## 5.6 本轮新增/更新的验证件（面向现库，可直接复用）

- **`scripts/e2e_org_types_and_credit.py`（docs/38 批次 B 正式套件，47/47，连跑两次）** ——
  机构类型收敛 + 信用代码校验。**P0** 前置（账号可用、字典端点可达、记录机构总数基线）/
  **A** 字典是唯一权威（5 类、顺序、标签、只回吐 code+label）/ **B** 五类都能建且**直连库**断言落库值是 canonical /
  **C** 编辑侧同样收口（非法值被拒且**原值不变**）/ **D** 信用代码三道（17/19 位、禁用字母 O/I/Z、行政区划段非数字、
  含中文 全部被拒且不留行；重复被拒；编辑自身允许、编辑成他人值被拒）/ **E** 按 code 前缀清理 +
  **机构总数回基线**（`22 → 22`）。
  ★ **最关键的一条是 B9**：旧前端取值 `STATE_OWNED`/`PRIVATE` **必须 400** —— 不写它，
  「枚举收敛」就可能只是"前端不显示了、后端照收不误"。
  ★ **别按 HTTP 状态码断言**：本仓业务校验失败 = HTTP 200 + 信封 `code=400`（见 `pitfalls.md` #76），
  第一版写成 `st == 400` 导致 8 条假红。
- **`scripts/_check_org_types_and_credit_guards.py`（批次 B 静态守卫，正向 9/9 + `--selftest` 11/11，无 SKIP）** ——
  O1 清单只由 `OrgInstitution` **定义**（判据是定义、不是"出现过"）/ O2 五类标签与规格一致 /
  O3 写入侧一律经 `requireOrgType`（`setOrgType` 的实参只允许"已校验局部变量"或"内联 requireOrgType"）/
  O4 信用代码字符集判定只在 `CreditCode.java` / O5 唯一性在建行之前且排除自身 /
  O6 字典端点存在且与机构端点同权限口径 / O7 前端不得硬编码类型选项与标签表、必须用字典渲染 /
  O8 前端不得自写信用代码正则 / O9 种子脚本不得再发旧取值。
  ★ 自检的 `[SKIP]`（突变锚点漂移、未生效）**计入失败**（见 `pitfalls.md` #77）；`.vue`/`.ts` 断言前同样**先剥离注释**。
- **`scripts/e2e_tenant_domain_quota.py`（原 `e2e_v66_tenant_hierarchy.py`，2026-09-28 改名，44/44 连跑两次）** ——
  改名原因：用户决定**去掉子租户**后，该文件已无法再测「租户层级」，名字与实际不符即失真。
  覆盖：**P** 前置防恒真（域名已分配 + 池 > 0 + 席位非零 + 已排出配额 > 0）/ **A** 租户登录域名
  （格式非法拒 / 重复拒 / **改成自身原值允许**（唯一性校验必须排除自身）/ **可清空且必须真落库** / 还原）/
  **B** 平台调整租户资源上限（回执 before-after、周期取服务端权威值、不得低于已分配到机构的量、
  **只提交词元则席位不动**、显式提交席位才改且真落库）/
  **R** 「子租户已移除」的运行时证据（四个 `/api/v1/tenant/sub-tenants*` 端点一律 **404**、被拒请求不留行、
  库层无 `parent_id/level` 列且 `idx_tenant_parent` 已删、`domain`/`uk_tenant_domain` 仍在、
  ★ **对照**：同租户域 `/api/v1/admin/tenants` 仍 200+code=0 —— 否则 404 可能只是「服务坏了」）/
  **F** 精确还原（域名/词元/席位/租户数全部回基线 + 无残留行与账号）。
  基线一律**运行时读取**（不写死常量），故演示库漂移不会假红。
  **基线采样纪律（V66 时代踩过，仍适用）**：额度基线必须**紧邻**被测操作采样 —— 首跑 `B12` 假红，
  因为基线取在更早的 P0，中途 A 段"扩额度又还原"与"子租户 −100 万"**互相抵消**，差值恒为 0。
  ⇒ 判据加严为：**采样点与被测操作之间不得夹任何会改动同一量的操作，哪怕它最终还原了**。
- **`scripts/_check_v66_tenant_guards.py`（2026-09-28 重写，正向 13/13 + `--selftest` 29/29）** ——
  ★ **编号方案已换**：原 V1–V12 里 V1–V5/V7/V9/V10/V12 断言的都是**已被删除的子租户代码**，
  代码没了就无法再断言 ⇒ 改为两类，语义一眼可辨：
  **`K1–K7` 保留能力仍在**（被误删 = 能力丢失）：K1 平台调额度仅平台管理员且回执带前后值 /
  K2 域名归一化只有 `TenantDomain` 一处 / K3 `V66` 仍保留 `domain`+`uk_tenant_domain`（别把保留能力一起回退）/
  K4 前端调额度入口与域名控件齐备（**从 `@/api/tenantQuota` 引入**，拆分 api 时未被误删）/
  K5 平台停用租户仍同步冻结账号 / **K6 编辑租户用显式 `set` 写域名为 NULL**（见 `pitfalls.md` #84）/
  **K7 调额度弹窗预填席位当前值**（见 `pitfalls.md` #85）。
  **`R1–R6` 子租户真的不在**（被动复活 = 能力边界无声变化，这类改动不会有编译错误）：
  R1 后端产物已删（两文件不存在 + 全仓 Java 无 `SubTenant`）/ R2 `SysTenant` 不再映射 `parentId/level`
  （列已删，实体残留 ⇒ 查询直接 500）/ R3 `OrgStatMapper` 无 `parent_id` 与子租户方法名，且
  `selectTenantWithHierarchy` 仍在（平台调额度依赖它）/ R4 `TenantController` 不再回吐 `level/parentId/subTenantCount` /
  R5 `V68` 真删三样且不碰 `domain` / R6 前端入口已清除（视图/api/路由/菜单/常量）。
  ★ **断言前必须剥离 Java 注释**（`_strip_java_comments`）：`pitfalls.md` #75 同型 ——
  注释里为说明纪律必然复述关键字，连注释一起数 = 禁止解释。`.ts/.vue` 同理要剥注释与 `import`
  （`_ts_code_body`：否则 `import { unwrap }` 一行就让「真调 unwrap」恒真，见 `pitfalls.md` #87）。
  ★ **断言要限定在单个方法体内**（`_method_body`）：K6 断言「`update()` 不许用 `updateById`」，
  而同类 `changeStatus()` 合法地用了它 —— 不限定范围就是假红，还会逼后人删掉正确代码。
- **`scripts/_verify_v68_ui_removal.py`（真机 Edge headless，2026-09-28 修正后 18/18）** ——
  第三层证据：静态守卫（源码）+ `e2e_tenant_domain_quota.py`（接口/库）之外，补**真机 DOM**。
  考两件事：① 侧栏无「子租户」且**旧路由 `/sub-tenants` 不再渲染子租户页**（路由级，不只靠文案），
  同时**对照**「租户与机构」分组仍在且五个兄弟入口（租户管理/机构管理/入驻进度/资源授权/费用分摊）都还在
  ——否则「整块菜单被删」会被当成通过；② 「租户管理 → 调整资源」弹窗**预填当前席位**
  （DSJ-DEMO 实测 `统计期 2026-09 / 词元上限 20000000 / 专家席位 12 / 技能席位 18`，按
  `.el-form-item__label` 精确定位而非按 input 下标），证明 K7 的源码修复**真的在浏览器里生效**。
  ★ 本套件首版假红 6/13，两条**都是测试自身缺陷**（不是产品缺陷），已写成 `pitfalls.md` **#89/#90**：
  （a）用 `btns.first.click()` 点第一行 ⇒ 点到没有资源池的 `id=1 默认租户`，回吐 `0/0/0` 本就正确；
  **必须按业务键定位行**（`tr:has-text("DSJ-DEMO")`）并先查库确认该行该有值；
  （b）用 `inner_text()` 查折叠子菜单的子项 ⇒ 折叠态文本不可见，`innerText` 取不到，五项全假红；
  **先展开分组或改读 `text_content()`**。
  附带核实：运行中的 `--aioa.web.web-dir` 指向 `%TEMP%\aioa-webroot`，其 `index.html` 与入口 bundle
  与当次构建（`%TEMP%\aioa-shell-v68c`）同时间戳，且 webroot **已无任何 `SubTenant*` chunk** ⇒
  「陈旧产物未清理」这条假设被排除（排查顺序：先证载体，再怀疑代码）。
- **`scripts/e2e_v65_expert_visibility.py`（50/50，连跑两次 + `--selftest` 通过）** ——
  把「专家可见范围必须在**用户端目录**真实生效」（#6 的行为半边）从探针固化成回归套件：
  四档维度（`INSTITUTION`/`DEPT`/`USER`/`TENANT`）× 目标在/不在清单 × **空清单** × 大小写 × **未知枚举** × 管理员豁免
  × 落库位置 × 精确还原 × 无残留，共 **50** 条；`A9/A10` 静态断言「H5 调的确实是 `/v1/experts`」。
  **防恒真三件套**：写配置**之前**先证两位成员都看得见（A7/A8）+ 每条"看不见"都配对照组（另一位仍看得到**别的**专家、目录非空，B6）
  + 清单翻转后必须反转（B7/C3/D3）。**负向自检**（`--selftest`）：对**可见的**专家断言"不可见"，要求**必须报红**。
  **取证路径**：平台管理员写 `TENANT#<租户>` 片段在 `needsReviewForConfig` 里被 `isPlatformAdmin` **豁免** ⇒ 天然 APPROVED，
  所以这条套件**不需要动 `sys_config` 审核开关、也不用过"审核放行"接口**；`G11` 断言开关前后同值，把这条纪律锁死。
  （踩过的坑：基线值若在写完 `visibleScope='all'` **之后**才采样，`G4` 会假红 —— **基线必须在施加任何干预之前采样**。）
- `scripts/_probe_v65_changes.py`（**25/25**）—— 本轮 8 项修复的**直连接口证据探针**：
  P1 `GET /org/members` 回吐 `username`+`departmentName`；P2 `GET /tenant/scope` 带 `currentPeriod`；
  P3 `/admin/roles`(`roleName`/`name`/`dataScope`)、`/admin/permissions`(`permName`/`name`)；
  P4 专家配置 `visibleTargets` 无损往返（PUT 要 `scopeType` 包裹，DELETE 精确还原）；
  **P5 可见范围在用户端目录真正生效**（`INSTITUTION` targets=[1] → 机构1 可见/机构2 不可见，翻转后相反，
  管理员豁免，全部精确还原）—— 这是 #6 的**行为半边**，已由上面的正式套件固化。
  注意：本探针写入方是**租户管理员** ⇒ 仍需「临时关 `sys_config` id=59 + finally 原字节还原」的旧路径（新套件已不再需要）。
- `scripts/_check_v65_scope_and_field_guards.py`（正向 **18/18** + 负向自检 **18/18**）—— 新增
  **B5**（判定实现必须在 `ExpertSettings.visibleTo`）、**B6**（用户端目录必须用同一判据）、
  **B8**（管理端 `visible()` 只能转发，不得再自行实现 `switch`）。
- 面向现库的有效回归面（本轮实测全绿）：`e2e_v59b_tool_sdk` · `e2e_v60_workflow_ext` · `verify_config_effect`
  · `e2e_v63_org_feedback` **56/56**（原 55/55；09-27 补了「收尾软删自建账号」断言，见下）
  · `e2e_v64_fixes` · `e2e_v64_expert_template` · `e2e_v65_expert_gate` **50/50**
  · `e2e_v65_expert_visibility` **50/50** · `e2e_tenant_domain_quota` **44/44**（原 `e2e_v66_tenant_hierarchy`，子租户移除后改名） · `e2e_org_types_and_credit` **47/47** · `e2e_v63_single_port` **44/44** · `e2e_v62_default_ai` **79/79**
  · `e2e_v62_admin_default_ai_ui` **9/9** · `e2e_v59_bridge_tool_invoke` · `e2e_agent_orchestrator`
  · `e2e_member_accounts` **35/35**（V67 批次 C：建档即主账号 / 多对多 / 主账号不可解绑 / 解绑后可重绑 / 虚拟账号判据 / 精确还原）
  · `_check_member_account_guards.py`（正向 **11/11** + 负向自检 **11/11**；M8 前端真接出、M10 旧文案、M11 候选池不被残留反噬）
  · `reset_e2e_account_residue.py`（**清理工具**，非套件：软删 `e2e%` 残留账号，`--dry-run` + 整行 JSON 备份）

**造数据的套件收尾纪律（09-27 新增，见 `pitfalls.md` #78）**：收尾必须让自建数据**退出业务可见面**
（账号要软删/停用，不能只把机构置 `CLOSED`）—— 否则残留会涌进租户级查询的业务 UI；
且「数量回到基线」的断言要能指出基线里**每条**是什么，否则残留会被当基线长期隐身。

**另**：校验器的白名单（如「允许提及已删文件名」）必须是**显式集合 + 每条写明理由**，
不能写成前缀/目录级通配 —— 那是把洞开成门。


## 2026-09-28 新增验证件

- **`scripts/e2e_worker_grant.py`（资源授权 / 数字员工，**33/33**，连跑两次 33/33，零残留）** ——
  目录（5 类含 WORKER、每类都有候选分组键）/ 授权（成功、幂等 upsert、清单可读）/
  **机构侧真的生效**（`/org/grants` 的 `byType.WORKER` 出现 → 停用立刻不可见 → 恢复）/
  收尾回基线 / 白名单负向（未知类型被拒且提示含 WORKER）/ 权限（401·403）/
  **跨租户目录无交集**（A7–A9 钉 `selectWorkers` 的租户过滤）。
  ★ 含 `KNOWN_MISSING_CAT = {"KB"}` + **A5b**：KB 目录键缺失是**已登记缺口**，缺口一变就报红。
- **`scripts/_check_onboarding_step_guards.py`（入驻 8 步，正向 **9/9** + 自检 **10/10**）** ——
  S1 STEPS==TOTAL_STEPS==8 且步骤号连续 / S2 每步有 route+routeLabel /
  S3 定义接口与进度接口同源 / S4 unlocked 由「通过或已确认」累积 /
  S5 满 8 步 currentStep=null / S6 **前端不得复刻路由字面量** / S7 前端处理 null /
  S8 每步 route 在前端路由表真实存在 / S9 未解锁给「需先完成第 N 步」。
- **`scripts/e2e_onboarding_8steps.py`（入驻 8 步端到端，**29/29**，只读）** ——
  定义/状态/当前位置与顺序/目标页面/权限/只读无副作用。
- **`scripts/_check_worker_grant_guards.py`（授权类型清单与租户隔离，正向 **13/13** + 自检 **13/13**）** ——
  W1/W1b 类型清单唯一权威 · W2 白名单同源 · W3 目录同源 · W4 byType 同源 ·
  W5/W6 `selectWorkers` 租户过滤（含「有参数不传=仍全表」）· W7/W8 前端目录驱动 ·
  W9 分组键覆盖全部类型码 · W10 TS 声明 · W11 套件收尾防残留 · W12 下拉标签不拼 undefined。

**真实机（agent-browser）登录要点（09-28 实测）**：管理端登录页**没有 placeholder/id**，
`fill`/`click "… >> nth=0"` 这类选择器**不可靠**（会报 Done 但值没进 Vue）；
可靠做法是 `agent-browser eval --stdin` + 原生 value setter + `input` 事件：
```js
var ins=document.querySelectorAll('.el-input__inner');
var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
function set(v,el){setter.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}))}
set('DSJ-DEMO',ins[0]); set('dsj_admin',ins[1]); set('User@123',ins[2]);
```
（租户名可用**租户编码 `DSJ-DEMO`**，不必输中文全称。）
另：**每次 bash 调用之间浏览器上下文不保留**（localStorage/页面都会丢），
所以「登录 → 导航 → 点按钮 → 截图」必须写在**同一个 bash 调用**里；
且每条 `agent-browser` 命令都要 `timeout N … > 文件 2>&1`，否则会被 SIGTERM 掉。
Element Plus 的下拉选项要 `querySelectorAll('.el-select-dropdown__item')` 再按
`offsetParent !== null` 过滤可见项后 `click()`。

## 2026-09-28 二批新增验证件（配额租户切换 / 知识库授权 / 员工开户口令）

- **`scripts/e2e_quota_kb_fix.py`（**46/46**，需 8080 起来）** ——
  A 配额随租户切换（A1–A13：带/不带 tenantId、t2 与 t3 成员集合无交集、跨租户 404、
  租户管理员越界 404、企业管理员被拒）；B 知识库授权（B1–B17：目录 `kb` 键存在、
  授权→机构侧生效→停用/启用→撤销、幂等、跨租户负向）；C 专线一致性（C1–C6：
  `/org/kb` attach/detach 与 `resource_grant` 账本同源）；D 收尾回基线（D1–D5 无残留）。
  ★ 两条踩坑记录（已写进套件注释）：① 负向用例必须挑**本租户独有**资料 ——
  第一次用平台级共享资料（`tenant_id=0`，对谁都合法）⇒ 误判通过；
  ② 占用守卫用例必须在**授权前**取第三方目录 —— 授权后该资料已从目录消失。
- **`scripts/_check_scope_kb_guards.py`（无需起服务，正向 **18/18** + 自检 **15/15**）** ——
  Q1–Q6 配额作用域（前端声明 / 后端接参 / 走 `ResourceTenantGuard` / 回执带 `tenantId` / 前端同源展示）；
  K1–K12 知识库（catalog `kb` 键、`institution_id=0` 筛选、grant/setEnabled/revoke 的 KB 分支、
  占用守卫、存在性判据、`/org/kb` 专线同步账本、前端读 `catalog.kb`、套件含负向+基线）。
  ★ 工具：`_seg` / `_before` / `_between` 三个切片器 —— **MyBatis 的 SQL 注解写在方法签名上方**，
  只向后切会切到空段，必须用 `_before` 向前切。
- **`scripts/_probe_v67_member_password.py`（P1–P9，需 8080 起来；会新建再软删自建账号）** ——
  指定口令 / 留空回落统一口令 / 错误口令负向 / 重置后新口令生效且旧口令立即失效 /
  **账号已存在时不得回吐 initialPassword** / 批量导入回吐 `newAccounts`+统一口令 / 收尾回基线。
  ★ 收尾用 `soft_delete_accounts()`（软删，让账号退出 `/org/accounts` 候选池）—— 见 pitfall M11。
- **`scripts/_check_member_login_credential_guards.py`（无需起服务，正向 **12/12** + 自检 **12/12**）** ——
  C1 明文与哈希同一决策点 · C2 回显分支与写库分支同源 · C3 表单口令真被传递 ·
  C4（**判据必须取反**：`!usernameExists`）· C5 导入也回吐 · C6 mapper 方法声明唯一（重复=编译失败）·
  C7 重置走唯一写入口且不静默 · C8 重置端点权限 · C9 前端有入口且不复刻常量 ·
  C10 口令只写不读 · C11 口令不进审计 · C12 角色授权先 revive 再 insert（软删占唯一键 ⇒ 500）。
  ★ 切片辅助 `_method_body(src, name)`：同一关键字会在多处出现（`Vals.str(body,"password")`
  在新建与重置各一次），**全文匹配会被别处顶替而误判通过**（自检 C3 第一版即如此）。

**真机（agent-browser）踩到的三条新细节（2026-09-28 二批实测）**：
1. 管理端登录页提交按钮的文案是 **`登 录`（中间有空格）**：按 `textContent.indexOf('登录')` 匹配会
   直接落空（现象是"找不到按钮"）。一律用 `b.textContent.replace(/\s+/g,'') === '登录'`。
2. **每次 bash 调用开头必须重新 `open` 目标 URL**：上一轮结束时 daemon 可能停在导航错误页，
   此时 `eval` 读 `localStorage` 会抛 `SecurityError: Access is denied for this document`，
   `document.querySelectorAll('.el-input__inner')` 返回 **0**（假象是"页面没有输入框"）。
   注意这条与"页面没渲染完"长得一样，别误判成前端缺陷。
3. 登录页三个 `.el-input__inner` 的顺序 = **[租户/机构名, 用户名, 密码]**（与 LoginView 模板一致），
   可用 `DSJ-DEMO`（租户编码）填第一格，不必输中文全称。
4. 验证"值真进了 Vue"的**唯一可靠判据**：原生 setter 派发 `input` 事件后**回读 `el.value`**。
   本次新增员工弹窗回读得到
   `[{姓名:'真机探针466781'},{登录账号:'zz_ui_466781'},{初始口令,type=password,value:'UiPw#2026466781'}…]`，
   保存后 `ElMessageBox` 文案为「登录账号：… / 初始口令：… / 请立即留档…」⇒ 白名单外的字段也能验。
   证据图：`logs/proof/v67-member-password-ui.png`（弹窗回显 + 名册行新增「口令」按钮）。
5. `agent-browser screenshot` 落在 `C:/Users/<u>/.agent-browser/tmp/screenshots/`，
   该目录会被清理 ⇒ 要留证就 `cp` 到 `logs/proof/`。


## 2026-09-28 新增验证件（级联删除：前置校验 + 逐级审核）

- **`scripts/e2e_cascade_delete.py`（**76/76**，连跑两次，零残留）** —— 四层各一组：
  **A 机构**（18）· **B 租户**（13）· **C 部门**（14）· **M 员工直删**（13）· **P 前置**（8）· **F 还原**（10）。
  前三层各自覆盖：**无直删端点**（配对照断言）→ 有下级时**精确拒绝**且不落审批单 →
  申请 ≠ 删除 → **审批人 = 申请人的上一级**（不是兜底 `ORG_ADMIN`）→ 驳回保原状且可再申请 →
  批准**真删** → **审批期间前置条件被破坏 ⇒ 拒绝开启删除**（TOCTOU）。
  租户组另有：批准后**冻结该租户全部账号** + 已签发令牌**立刻 401**（配「平台管理员仍可用」对照）。
  前置组先证「有下级对象存在 + 流程定义已播种」，否则后续断言会恒真。
  **M 组（2026-09-28 下午补）** 反向守界：员工层**不走审核** —— 直删成功、**一张审批单都不产生**
  （全库单数前后相等）、账号绑定被清、对已删员工再删不静默成功（证明「直删成功」不是接口恒真）、
  企业管理员被拒且行仍在、用别家机构 institutionId ⇒ 404 且未误删。
  ★★ **F10 = 全库在册员工数回基线**：这是「套件自己误删了演示数据」的兜底断言。
  M1 首版把探针打成 `DELETE /org/members/1`（**真删端点**而非申请端点），当场删掉演示员工
  「刘敏」，而因为当时没有这条基线断言，损伤在套件里是**静默**的（只报一条看似「断言写错」的 FAIL）。
  ⇒ 纪律：**任何会写库的套件都要给被保护对象的总数建基线**；负向「端点不存在」断言只打
  申请/只读子路径（`…/{id}/delete-request`），永不打可能生效的写端点。
  恢复手法见 `pitfalls.md` #91 + `scripts/_diag_member1_restore.py --fix`（`_diag_*` 不入库）。
- **`scripts/_check_delete_guards.py`（正向 **12/12** + 负向自检 **35/35**，无 SKIP）** ——
  D1 无直删端点 · D2 申请入口不删（**只扫写动作**，不能拿 `deleted_at` 一概而论：
  申请里有「同一对象只允许一条在途申请」的去重查询，那是读）· D3 `onApproved` 重校验且**抛错** ·
  D4 取不到业务对象 id 必抛错 · D5 **先冻账号再软删租户**（顺序反转会留下「租户查不到、账号仍可登录」）·
  D6 顶端不当申请人 · D7 V69/V70/播种器**三处口径一致** · D8 新建租户必播种 ·
  D9 前端只有申请入口 · D10 三处 api 都 unwrap · D11 部门判定**只在一处** ·
  **D12 员工层保持直删**（端点仍在 / `deleteMember` 无审批调用 / 受审层级**恰为**三层 /
  播种器与迁移无 `MEMBER` 流 / **界面真的调用了 `deleteMember(`** / api 走 unwrap）。
  ★ D12f 专打一种最阴的形态：**api 函数存在但没有任何视图调用（死代码）** ——
  能力事实上不可用，而所有既有套件仍全绿（接口层套件不经过界面）。
  ★ 三条容易写错的断言（自检抓出）：① 突变锚点里**不能带注释**（`_strip_java_comments` 已去过标注，
  注释会留下只剩缩进的空白行）② 突变 key 必须与 `load()` 的键名一致（写错不会被判「突变未生效」，
  而是**静默不报红**，比报错更难发现）③ 突变体里**不能靠注释保留原调用**（`checks()` 收到的是
  已去注释的文本，突变阶段再写注释不会被再去一次 ⇒ 断言照样通过 = 假绿）。
- **口径联动改动**：`scripts/verify_v39_provisioner.py` 的默认流期望值由**写死 4** 改为
  `len(DEFAULTS)` 推导（本轮 `DEFAULTS` 4 → 7，新增三条删除流）。写死数字在下次加流时**假红**，
  而「把 4 改成 6」又看不出是「口径变了」还是「为了让红变绿」。
  ★ 该套件依赖 tenant 9（`znkj_admin`），现库已清除 ⇒ 本地**不可运行**（桶 A），不是「已通过」。
- **新增三层「直接删除」端点的禁令**：`DELETE /api/v1/org/departments/{id}` 已**下线**
  （原本就有级联前置校验，缺的是审核闸门）。注意断言要看 **404 或 405 都算通过**：
  部门路径上还挂着 `PUT`（编辑），Spring 会回 **405 而非 404**；只认 404 会把正确实现判红。
