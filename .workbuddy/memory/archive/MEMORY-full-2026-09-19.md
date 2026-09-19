# AIOA 长期记忆（精简版；日期细节见同目录 YYYY-MM-DD.md）

## 1. 项目与运行
- AIOA=地级市 AI 公共服务平台。Vue3 管理端 shell(`web/apps/shell`) + SpringBoot 单体(`server/` **9** Maven 模块) + MySQL8(库`aioa`,root 无密码) + FastAPI agent(:8000) + 用户端单文件 H5(`user-client/index.html`)。方向：**改代码对齐设计文档**（五层架构）。
- 规格源：`docs/10` 职责边界 · `14` 账号 · `15` 权限矩阵 · `16` 组织作用域 · `19` 七项优先事项(**进度只回写此文**) · `20` 全链路 E2E · `21` 层级流转 · `22` 登录口径 · `23` 权限审批与组织关联 · **`28` 未开工项规划（"未开工项"唯一进度权威，收口记录在 §6）** · `29/30` Gitee 仓库联动 · `31` 模型网关规范 · **`32` 向量库迁移 Milvus 计划**。
- 重打包：**先停 :8080** → `cd server && bash mvnw -DskipTests -q clean package` → `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`。系统 `mvn` 损坏只能用 `mvnw`；**勿 `rm -rf target`**（用 `mvnw clean`）。判据：fat-jar 应 ~82MB；若变 ~20KB **stripped-jar** 说明没停 JVM 就重打包了。**同一时刻只允许一个 Maven 构建**；`-pl <m>` **必须带 `-am`**。
- 改 `agent/app/**` 必须重启 uvicorn（非 `--reload`）。`bash start-all.sh` 一键起（幂等，日志 `logs/`）。**长驻服务必须作为后台任务的「前台进程」跑**（重定向到日志、不加 `&`；`nohup &` / 脚本内 `&` 会被沙箱回收 ⇒ 起来又立刻死，日志只到 "profile is active"）。停后端用 `PowerShell: Get-NetTCPConnection -LocalPort 8080 -State Listen | Stop-Process -Force`（`taskkill //PID` 在 git bash 下被转义成 `//PID` 会失败）。
- 端口 8080/8000/5173(5174/5175)；H5 :5181 **只绑 127.0.0.1**。探端口 `netstat -ano|grep LISTENING|grep ":<port> "`，**不接 `| head`**。
- **环境变量两套文件**：`deploy/.env.development`（本地）/ `deploy/.env.production`（生产），**键序完全一致（77 项）**，对照表 `deploy/ENV.md`。用法 `set -a && . deploy/.env.development && set +a`。占位约定 `CHANGE_ME__`（必替换）/`DEV_ONLY__`（仅本地）/`<xxx>`（按实填）/留空（能力未启用）。**★含空格、`&`、`<`、`>`、`*` 的值必须加双引号**，否则 shell 当运算符 ⇒ 整份文件解析中断（实测生产文件只加载 4/78 键）。
- 口令：租户侧全 `User@123`（含 `dsj_admin`）；平台 `admin/Admin@123`。账号：`zhangsan`(t0) · `dsj_admin`(t2 租户管理员) · `fagai_admin`(t2 inst1 机构管理员) · `fagai_liu`(t2 dept10 负责人) · `fagai_li`(t2 **dept11** 成员) · t9 全链 `znkj_admin`(3142)/`znkjyf_admin`(3143)/`znsfb_ldr`(3144)/`znsfb_m01`。
- Flyway：新增前 `ls .../db/migration | sort -V | tail -3` 取实际最大+1（**当前 V60**：V59 bridge 工具网关 / V60 工作流加签·子流程·定义版本）。已应用迁移**不可改**（checksum），只能追加。文档里的版本号只是预测。

## 2. 接口与权限
- 基址 `/api/v1`。登录 `POST /api/v1/auth/login` `{username,password,tenantName?}` → `data.accessToken`（**不是** `token`）。少写 `v1`→401，易误诊为密码错。
- **业务错误=HTTP200+`code!=0`**；仅 401/403/404 改状态。**跨租户一律 404**（不泄露存在性），同租户越权才 403。`/auth/logout` **V46 起服务端吊销令牌**（access+refresh 的 `jti` 写 `revoked_token`，旧 token 立即 401）——登出时**两个令牌都要带**，只带 access 则 refresh 仍能换新令牌 = 没登出。
- 企业端 `/api/v1/org`，租户端 `/api/v1/tenant`（漏 `/org`→404 `NoResourceFoundException`，日志像 500）。
- 审批：`POST /api/v1/workflow/tasks/{taskId}/decide` `{decision:APPROVE|REJECT}`；待办 `GET /workflow/tasks?scope=todo|mine|cc`，行 `id` 当单据号；计数 `GET /workflow/tasks/summary`。
- 脚本 `httpx` 必须 `trust_env=False`。Playwright 用 `envs/default/Scripts/python.exe`+`channel="msedge"`（`versions/3.13.12` 无 playwright）。
- 角色层级 `ROLE_ADMIN`>`ROLE_TENANT_ADMIN`>`ROLE_ORG_ADMIN`>`ROLE_DEPT_LEADER`>`ROLE_MEMBER`。`OrgGuard`：读 `requireOrgUser()`、写 `requireOrgWriter()`、审批 `requireApprover()`（**含 TENANT_ADMIN+ROLE_ADMIN**；用 requireOrgUser 会把末级/平台审批人全挡掉）。
- 三段链 `WorkerRole`→`requiredPermission`→`PermissionCatalog`，**未知码默认拒绝**。前端常量唯一入口 `constants/permissions.ts` 须与后端同源；**菜单/路由/接口三层必须同源**（漂移=菜单不显示+路由重定向+403→页面全空）。
- 新增请求体字段一律「**缺省兼容**」（`null` 跳过校验，显式空白才拒），否则既有 E2E+H5 集体变红。

## 3. 关键坑（已修，勿回退）

### 3A 框架 / 构建
1. `aioa-common` **不引 spring-security** → `@RestControllerAdvice(Exception)` 把 `AccessDeniedException` 吞成 500。统一 `BizException.forbidden()`→403；`NoResourceFoundException` 已补 404。
2. repackage 前必须停 JVM，否则 fat-jar 被 rename 成 20KB stripped-jar，运行中 JVM `NoClassDefFoundError` 崩。
3. 给 Java `record` 加字段要全局搜构造点（`grep -rn "new XxxView(" server/ --include=*.java`），漏一处即编译失败，且 `mvnw -q package` 失败可能很安静。
4. MyBatis-Plus「清空字段」默认 `update-strategy=NOT_NULL` 会把 **null 字段排除在 `SET` 外** ⇒ `setErrorMsg(null)` 是**空转**（症状：库里还挂着旧 `Rate Limit Exceeded`）。修法：字段加 `@TableField(updateStrategy = FieldStrategy.ALWAYS)` 或改用 `LambdaUpdateWrapper.set()`。断言「清空生效」= **写脏 → 走一次真实动作 → 回读必须为空**。
5. **`decide()` 判定顺序**：CC 任务 `status='CC'`（不是 PENDING），**必须先判 `task_role=CC` 再判状态**；反过来「知会无需审批」分支**永不可达**。

### 3B 前端
6. 前端 `api/index.ts` 的 `unwrap` **必须校验 `code`**：body 含「数字 `code`+`message`」即按信封处理，`code≠0` 抛 `ApiError`。旧实现只在含 `code`+`data` 时剥壳，而后端 `non_null` 让失败响应 `data` 键消失 → 整封信封当业务数据。「页面空白无数据」基本都此根因。
7. 接口返回结构不统一 → 前端 `asArray()` 兼容 数组/`{list|items|records|data|rows}`；`renderAll` 每块独立 try/catch（否则一块抛异常后续全空白）。比对分页总量用 `total`，**不能用 `len(list)`**。
8. H5 单文件：页面 `go('page-xxx')`；session `localStorage['aioa_session']={token,user}`；无头校验用 `add_init_script` 注入；改完先 `node scripts/_syntax_h5.js`。图标只引用 sprite 真实存在的 `#i-*`（不存在**静默留白**）。Tab 栏高 76px，flush 页需单独 `padding-bottom:76px`。
9. 成果列表接口**不含 body**，详情走 `GET /api/v1/results/{id}`。登出先 `clearSession()` 再 best-effort 远端；`<router-view>` 必须带 `sessionActive &&` 闸门。
10. **合并两个菜单不能用 `alias`**：`alias` **继承**被别名路由的 `allowRoles` ⇒ 普通成员深链旧路径不再被拦截 = 顺手放宽边界。正解=**独立路由**沿用原 `allowRoles`。两条路由共用同一组件时默认页签须用 `watch(immediate)` 而非 `onMounted`；目标页签不可见时**必须回落**（否则整页空白）；`:default-active` 要做「旧路径→合并入口」映射。
11. **侧栏滚动隔离的根因是 flex 高度链，不是 `overflow` 一处**：`.el-container` 是 `flex:1; flex-basis:auto`，flex 项默认 `min-height:auto` ⇒ 内侧 flex 行被整棵菜单撑高且无法收缩。四处齐改才成立：`.layout{overflow:hidden}` + **内侧 flex 行 `min-height:0`** + `.layout-aside{overflow-y:auto}` + `.layout-menu{min-height:100%}`（**不能 `height:100%`**）。判据：`document.scrollHeight == clientHeight`。探针 `scripts/_check_menu_scroll.py`（27 项）。
12. **管理端菜单分组**：21 个一级项 → **5 个一级 + 6 个分组子菜单**（智能服务/成果与项目/运营管理/租户与机构/安全与治理/平台管理）。分组的 `v-if` = 子项可见性之「或」，**子项守卫与路由 `index` 一律不动**。改分组归属**必须同步 `MainLayout.vue` 的 `PATH_GROUP`**，否则深链进来该分组不展开 = 「菜单一项都不高亮」。

### 3C 权限 / 审批 / 组织
13. 额度闸门判据 `state.quotaInfo.exhausted===true`（**勿**用数字型默认值表达「未知」，`state.left` 初值 0 曾致误判「额度用完」）。复位 `scripts/reset_demo_quota.py`。
14. 审批流解析优先级：机构专属 > 租户默认(`institution_id=0`) > 内置单级兜底。`audit_log` **永不 UPDATE**。假种 `quota_days_per_year=0`=不占额度只走审批（`quotaTracked=false`）。
15. 审核态闸门：V34 起租户管理员建的内容 `audit_status=PENDING`，对成员不可见、不被调度；V36 权限申请**终态回调才置 ACTIVE 并发放**（`granted_by/at`=终态处理人/时间）；`expert_config` 生效解析**必须过滤 `audit_status='APPROVED'`**。终态回调里 `order` 是**决策前**快照，意见/审批人须回查 `approval_task`。
16. `aioa-resource` 与 `aioa-org` **互不依赖**；只有 `aioa-chat` 同时依赖二者。需同时读「权限/计费/工具」与「组织/审批/假种/知识库」的功能只能落 `aioa-chat`。
17. **审批链递推(V39)**：`ApprovalFlowService.expandNodes()` 遇 `APPLICANT_SUPERIOR` **不展开固定 steps_json**，改用 `superiorLadder()` 从「申请人层级+1」起逐级展开，跳过 null/申请人本人(自审防护)/重复人。兜底分支必须把 `effectiveType` 置为**实际生效类型**。
18. **V41/V42 职务与知会**：`org_duty`(租户级职务字典 DEPT_PRINCIPAL/DEPT_DEPUTY/ORG_LEADER/STAFF)+`org_member.duty_code` 是「谁是部门负责人」的**唯一权威口径**（原 27/8/3 三口径已收敛）。steps_json 新增 `levels`(1=只批一级) 与 `cc`(知会→生成 `task_role='CC'` 任务，**不阻塞**流程、不进 todo、不可 decide)。
19. **V43 二期/三期（部门申请 + 知会已读）**：`approval_order.applicant_type`(`USER`|`DEPARTMENT`)+`applicant_department_id`、`permission_grant.applicant_type`、`approval_task.cc_read_at`。口径：① 部门申请起点 = **`ORG_ADMIN`**（跳过 DEPT_LEADER，保留自审防护与 levels 截断）；② 负责人判定**只认 `duty_code='DEPT_PRINCIPAL'`**，`job_title` 不作权限依据；③ 跨机构/跨租户/平台 → **404**、同机构非正职 → **403** 且**均不落库**；④ `summary.cc` 固定为**总条数**（不因已读减少），未读另开 `ccUnread`；⑤ **底部「待办」角标不计入 CC 的站内通知**（`tab = 待审数 + 未读通知数(剔除 refId ∈ 我的抄送单)`，仅 `user-client/index.html` 前端一处）；⑥ 授权仍发给**提交人本人**（部门共享权限未排期）。
20. **V45 四期/五期（策略族 + 节点组）**：审批人解析改走 `cn.aioa.org.support.approver` 策略族（`ApproverResolver` 门面 + `DutyApproverStrategy` 抽象 + `DeptDuty`/`UnitDuty`/`DeptLeader` 三实现 + 4 个固定口径 Bean）。**策略返回「有序候选列表」**，消费层才决定用几个 ⇒ 会签/抢占的基础。同 `seq` = 同一「级」，`isCurrentNode` **按 `seq` 比较**（不是 id）、`countTasksOfOrder` 用 `COUNT(DISTINCT seq)`（前端「共 N 级」同理，**不能用时间线行数**）。`mode`=single/parallel/grab；`when`={field,op,value} 条件路由 —— **运行期宽容**（未知模式退 single、坏条件不拦）、**保存期严格**（`writeSteps` 校验 mode/when/cc，非法 400），且**永远至少留一个生效节点**。`cc` 支持对象形态 `{"type":"SPECIFIC","user_id":N}`。
21. **V46 令牌吊销**：`revoked_token` 表 + JWT 带 `jti`；`JwtAuthenticationFilter` 在**验签与过期通过之后**再查吊销表（顺序不能反）。`TokenRevocationChecker` 是接口、`DbTokenRevocationChecker` 是实现（放 `aioa-admin`）。
22. **V47 回填 + 新租户播种**：① `LeaveTypeProvisioner` 只对**零 `leave_type`** 的租户播种 6 类标准假种（常量与 tenant 2 逐字节一致）；② `cc` 回填**机构级**定义；③ `org_member.duty_code` 回填**不触碰 `job_title` 含「负责人」的行**、也不把局长/总经理强升 `ORG_LEADER`；④ 无负责人部门补人。
23. **同类播种器必须实测**：`ApprovalFlowProvisioner` / `LeaveTypeProvisioner`(`@EventListener(TenantProvisionedEvent)`) 只在建机构时触发 + 内部 try/catch 吞异常 = **失败静默**。
24. **管理端配置页 = 能力的唯一入口**：引擎支持的能力若配置页配不出来，等于**能力事实上不可用**。`web/apps/shell/src/constants/permissions.ts` 是审批人类型/职务/模式/条件字段的**唯一常量入口**（曾导致 `DEPT_DUTY`/`UNIT_DUTY` 在下拉里显示成裸码）。配置页须做 `_extra` **无损往返**，否则管理员每次「打开-保存」都悄悄丢配置。

### 3D 数据 / 状态机 / 一致性
25. **软删+唯一键**：`sys_user.username` 唯一键**覆盖软删行**，`AccountProvisioner.resolveOrCreate` 须先查软删行再 `reviveUser`，否则重建同名管理员 500。
26. **MySQL 唯一键不约束 NULL ⇒ `type IS NULL` 的"默认行"绝不能用无 limit 的 `selectOne`**：`notification_preference` 的 NULL 默认行可被重复插入 ⇒ `TooManyResultsException`；在 `@Async @EventListener` 里异常沿 `dispatch` 冒泡被最外层 try/catch 吞掉 ⇒ **整轮分发静默中断**（现象「通知有记录但无投递」）。一律 `.last("limit 1")`。
27. **多步状态机：每一步失败都要有终态**（gitee_project 实测）：`CREATING --(建仓+配 Webhook 都成功)--> ACTIVE` 是**两条任务**，只有建仓侧 `markFailed`，配 Webhook 失败只判死**任务** ⇒ 项目**永远停在 CREATING**、界面无红字、校准只扫 `ACTIVE` ⇒ **无人再动它**。凡「A 步成功才入队 B 步」，B 的终态失败必须回写主对象。
28. **同一决策点必须在「一处」判定，否则视图会说谎**：`GiteeTenantConfigService` 的 `effectiveOrg`（行存在 **且** `enabled=1` **且** org 非空）与 `buildView` 的 `source`（只看 `row != null`）是**两个谓词** ⇒ 「有行但 `enabled=0`」时界面显示「企业自配置」却指向**共享**组织。修法：抽单一判定供两条路径共用（**不要在展示层打补丁**）。此类「新增一个可配置维度 → 造出旧状态机从未有过的组合」是最易漏的缺陷类型，**必须为该组合补断言**。
29. **展示字段与事实必须同源**：`gitee_project.webhook_events` 落库写死 Gitee 词表，Gitea 项目详情页据此渲染标签 ⇒ **明确说错自己订了什么**。修法：接口层 `RepoProviderClient.hookEventNames()` 复用**建钩子用的同一函数**，不要各写一份。
30. **回填用户可见字段时不准照抄历史原文**：历史原文带着**当时的环境**（托管方名/配置键/路径），照抄等于把旧环境的错话印给今天的用户。判据：「这行文本放到**今天**的配置下，还是真的吗？」
31. **「先软删、再异步入队执行」的动作，执行段一律不得 `selectById`，必须从 payload 取值**：`@TableLogic` 读到 null → 静默 `return` → 任务记 **DONE** 但真站资源还在（假成功）。**同一个坑改了一个漏了另一个**是常态，改时要全局搜同类。修后信息不全**抛错判 FAILED** —— 不可逆动作绝不允许静默成功。
32. **tenant 覆盖 + 回落全局默认**是加配置维度时的**首选形态**：不播种任何租户行 = 回落路径天然被既有数据与既有套件持续验证；强制必填会把所有存量数据变成迁移问题。
33. **「留空」类语义先查有没有可回落的东西**：平台**不存在**共享企业令牌 ⇒ 首次留空**本就应当失败**；正解是「必填 + 文案可读 + 前端按 `tokenConfigured` 动态必填」，**不是**让它静默成功。且报错文案**绝不回显 `null`**。
34. **状态字段契约不留 `null`**：如 `initStatus` 恒 `PENDING|ACTIVE|FAILED`，无配置行/空值一律归一化为 `PENDING`；「是否落过行」由 `configured` 单独表达。留 null 会逼前端各自写兜底分支。
35. **诊断端点必须回「报告」，不能回「错误」**：恒 `HTTP200 + code=0` + 顶层 `passed`/`failedStep` + 全量 `steps`（永不落库）；**动作端点**才失败即抛。`passed` 必须与 `steps` **同源推导**，否则「顶层说通过、明细里有红字」。
36. **收件人角色必须按租户口径取，且必须实测**：`selectTenantAdminIds` 曾硬编码 `role_code='ROLE_ADMIN'`（平台管理员，全库仅 1 个且挂 tenant 0）叠加 `tenant_id` ⇒ **每个真实租户命中 0 人**，租户管理员从未收到通知。正确 `IN ('ROLE_ADMIN','ROLE_TENANT_ADMIN')`。"给某人的通知"类 SQL 必须逐租户实测命中数。
37. **核实关键字命中语义再下结论**：本系统 `schedule` 实为**定时任务**（非日程）、`push` 实为 **git push**、`notification` 表**仅站内单通道**。做差距分析前必须先 `SHOW TABLES` + 看命中文件名。
38. **「展示值来自外部接口」必须用对照实验定性，不能靠读代码断言**：仓库地址**不是本地拼的**，是接口响应原样写库原样读出（前端无兜底域名）。故只能靠**让桩返回生产形态**来验证（`POST /_stub/public-base`；默认 None = 历史行为逐字节不变）。

### 3E 流程 / 工具纪律
39. **长驻服务绝不能由子代理启动**：子代理被 kill（如 429 限流）时其**子进程随之死亡**，桩/后端会静默消失，后续套件全红且原因难查。桩(8090)、后端(8080)**一律由主代理以后台常驻任务启动**。
40. **子代理被限流中断会留下"半成品"，比没做更危险**：可能「已改好 router 并新建视图，但菜单没改」，且引入的 `alias` 放宽了权限 —— 这些**能通过 `vue-tsc`**，只看编译结果会误判"已改好"。接手前必须**逐文件核对"改到哪一步"**。
41. **`git rm` 在本环境不可信 —— 一次误删把整个目录清空了**（2026-09-18 事故）。**纪律：本环境禁用 `git rm`**，改为 `rm 明确文件列表` + `git add`；清理必须小步走、每批后核对 `git status`。**恢复路径**（已验证）：① 删 0 字节 `index.lock` → `git restore --worktree -- <dirs>`；② **未跟踪文件从 `~/.workbuddy/projects/<conv>/*.jsonl` 重放 `Write`+`Edit`** 还原（本次找回 51 个）；③ `~/.workbuddy/file-history/<proj>/<hash>@vN` 做**内容级校验**；④ 跟踪文件一律以 git 为准覆盖。**恢复正确性必须用「跑套件」判定，不能用文件大小**。
42. **E2E 反模式**：① **toast 断言必须轮询**（`ElMessage` 3000ms 自动关，"固定 sleep 后一次性读"必读到空数组）；② **禁硬编码项目/单据 id**（桩是**内存态**，重启后旧项目消失 ≠ 前端 bug；正解：现建一个）；③ **单条检查要 try 兜底**（否则一条超时让整场崩溃、零信号）。
43. **测试里的「恒真断言」比没有断言更危险**：`chk(name, True, "")` 会让用例永远绿。另有一类**依赖校验顺序**的用例 —— "不传令牌却断言组织名格式"必然先卡在位数更靠前的 `TOKEN_FORMAT`；**必须构造前置步骤可通过的输入**，让失败点确定落在被测步骤。

## 4. 已知缺口 —— **当前为空**（docs/20 发现项已全量收口）
- `docs/28` 是「未开工项」唯一进度权威，收口记录见其 §6。已修：D-1 令牌吊销(V46) · D-2 路径参数类型(→400) · D-3 H5 待办 403 · D-4 favicon · D-8 新租户播种 · G-1 无负责人部门 · G-3 `duty_code`(27/116→116/116)。
- **判定「有效数据，不改」**：D-5/6/7 —— tenant 4 假种被 17 条余额 + 35 条申请**引用**，删除会让单据失去类型定义；tenant 2 的 6 条越权部门**已软删**（=审计留痕）。G-2 —— tenant 9 重复昵称 = **同一自然人兼多角色**（同一 `sys_user`）。
- 结论：`e2e_full_system` 的 `GAP` 桶**当前为空**；`kchk()` 保留供将来用。**修好缺口后必须同步删/升这些分桶**。
- **V50 收口遗留观察项（非缺陷，勿当回归）**：`GET /gitee/tenant-config` 不带操作人 → 必回 `orgVerified=false` + `verifyMessage="未提供操作人"`。若要 GET 也给出可信结论，需引入三态（`null`=未探测）。

## 5. E2E 套件矩阵（`scripts/e2e_*.py` 已 gitignore，不入库）
- **收口必跑**：`e2e_full_system.py` **155/155**（13 段跨层串联；`--no-browser` 跳渲染段，缺口 0）。
- **按钮级全量 UI（2026-09-19 新增）**：`e2e_v61_h5_all_buttons.py`（H5 **27/27**，运行时枚举 onclick 逐点，冒烟点 93 键）· `e2e_v61_shell_all_buttons.py`（管理端 **145/145，0 JS 异常**；逐角色：admin 49 · znkj_admin 45 · znkjyf_admin 19 · znsfb_ldr 17 · znsfb_m01 15）· wrapper `run_v61_shell_buttons.sh`。
  **铁律：管理端按钮级测试必须逐角色分进程**（单浏览器连跑 20+ 路由+上百点击会 Edge renderer 资源耗尽挂起）。稳定三板斧 = `goto(wait_until="commit")` + 越权断言用 `page.url`（免 evaluate 挂起）+ 按钮枚举单次 `evaluate`；点击 `locator.click(timeout=2000, no_wait_after=True, force=True)` + 每次 `Escape` 关弹层；只跳破坏性/真实网络按钮，空文本按钮（树箭头）也跳。跳过清单**过宽会「点 0 个」失去意义**。
- **当前基线（2026-09-17~19）**：`e2e_v48_gitee` 116/116 · `e2e_v51_gitee_init` 50/50 · `e2e_v50_tenant_org` 54/54 · `e2e_v52_message_center` 47/47 · `e2e_leave_flow_notify` 19/19（连跑两次）· `e2e_v45_approver_modes` 44/44 · `e2e_v45_misc_fixes` 27/27 · `e2e_v45_config_ui` 25/25 · `e2e_v43_dept_applicant` 41/41 · `e2e_v43_cc_read` 41/41 · `e2e_v41_duty_levels` 48/48 · `e2e_v39_applicant_superior` 49/49 · `e2e_v36_grant_expert_review` 64/64 · `e2e_admin_personnel_scope` 57/57 · `e2e_v32_org_scope` 51/51 · `e2e_v36_stats_clamp` 66/66 · `e2e_v33_roles` 41/41 · `verify_v51_repo_urls` 23/23 · `verify_v51_repo_urls_ui` 18/18 · `verify_v50_ui` 28/28 · `h5_v33_render` 28/28 · `admin_v39_todo_badge` 17/17 · `agent/tests` 42 passed · `aioa-gitee` 单测 165/165。
- **本地哨兵**（非 e2e 命名）：`_syntax_h5.js`（H5 语法）· `_refaudit_h5.js`（**H5 内联 `onX="fn()"` 的悬空函数引用** —— 单文件 H5 无打包器无类型检查）· `_check_menu_scroll.py`（管理端布局/菜单 27 项）。改 H5/管理端布局后顺手跑。
- `h5_v33_render` 假红排查：其「AI 解读」段依赖 agent。若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 → 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判。
- **套件会凭空消失**（gitignore）→ 跑前先 `ls scripts/ | grep -E "^e2e_"`，别照抄本表。只改前端也必须跑 `vue-tsc --noEmit`（少 import 常量表现为页面空白）。

### 断言纪律（写新套件必读）
- **禁固定页长/绝对条数**：用 `len(items)==min(total,size)`。判据：数据涨 10 倍、清库后该断言还成立吗？
- **审批用例先确认「申请人所在部门」的负责人**：首节点指派=该部门 `org_department.leader_user_id`。`fagai_li` 在 **dept 11**，负责人是 `fagai_admin`(user 4)，**不是** dept10 的 `fagai_liu`(user 7)；用错人→`decided=0`。
- **配额类套件必须自治**：`fagai_li` 年假仅 10 天；段首顶到「已用+10」；撤销链路用**不占额度**的事假；不传 `days` 且落周日返回「申请天数为 0」。
- **分清「口令/选择器改动」与「真回归」**：1001=口令错，1004=租户名不匹配。**按 `password_hash` 反查真实口令**再断言。
- **改权限/可见性/生效态/登录口径后必须全局搜既有套件旧口径断言并连跑两次**。历史遗留行≠代码 bug：可回填就**加 Flyway 回填迁移修数据、断言原样保留**。**绝不为转绿而放宽断言。**
- **动真实租户级配置的验收，`finally` 必须按「原字节」还原**（先登记 `(id, 原 steps_json)`，不要用「内置兜底版本」猜着还原）。
- **管理端配置页验收要「渲染 + 往返」**：必须浏览器渲染出控件（用 **label 文本**匹配），并做「**打开弹窗后不改动直接保存**，断言与保存前完全一致」，再种一个**页面没建模的键**确认它活下来。范本 `scripts/e2e_v45_config_ui.py`。

## 6. Git 远端
- `origin`=内网 Gitea `172.16.8.249:3000`：**HTTP 层沙箱可达**；公共接口免认证可读（`/api/v1/version`→1.26.2），但**仓库/组织/用户级全需令牌**，push-to-create 关闭(403)。**契约以实例自述规范为准**：`GET /swagger.v1.json`（已存 `logs/gitea-swagger-1.26.2.json`，gitignored）。
- ⚠️ **2026-09-17 起：本沙箱内推不了** —— 读 `~/.ssh` 被沙箱策略**硬拒**（`dangerouslyDisableSandbox` 同样无效）。⇒ **本地提交照做，推送这一步把命令原样交给用户在本机终端执行；绝不写成「已推送」，也不要反复重试同一路径。**
- 若换到允许读密钥的环境：**推 GitHub 只有 SSH over 443 一条路**（HTTPS 需凭证且当前无；22 端口被拒）。
  ```bash
  GIT_SSH_COMMAND='ssh -i "C:/Users/刘尖尖/.ssh/id_rsa" -o IdentitiesOnly=yes \
    -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' \
    git push ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git main
  ```
  **必须显式 `-i`**（默认路径会因 HOME 中文用户名被 ssh 展开成乱码而找不到 key）。约 5–8 分钟，**用后台任务**。收口校验**不靠 push 返回码**：比对本地 `git rev-parse HEAD` 与远端 `git ls-remote ssh://… refs/heads/main` 两个 SHA。
- 收口前必查**两类脏文件，缺一不可**：① 已跟踪 `git status --porcelain | grep -v '^??'` 应为空（`h5_v33_render.py`/`SMOKE_v48.py`/`gitee_stub.py` 等**老脚本是跟踪文件**）；② **未跟踪但属源码** `grep '^??'` **逐条判过** —— `git diff` **只显示已跟踪文件**，只看它会**整块漏掉新增文件**。另：`git status` 的 `??` 列表**常被 `head` 截断**，必须看全量。属 scratch 按既有约定不入库（别误当漏提交）：`scripts/_*` · 根目录 `probe*.txt` · `.workbuddy/artifacts/`。

## 7. 托管方抽象（Gitee → Gitea）
- **`RepoProviderClient`**（`aioa-gitee/client/`，21 方法）是上层唯一依赖；8 个服务只注入接口。`RepoProviderException` 为中立基类。**勿**把 `providerName()` 的 Gitee 覆写删掉 —— 文案会变。
- **`RepoProviderSettings`** 解决「平台侧配置长什么样」：访问器取名与 `GiteeProperties` getter **完全相同** ⇒ 11 处调用点一行未改。**三类取数规则**：①**协议类随 provider 切**（`org`/`webhook-base-url`/`webhook-secret`/`redirect-uri`/`oauth-authorize-base-url`/`token-enc-key`/`repo-name-max-length`）；②**运行参数仍取 `aioa.gitee.*`**（`sync-enabled`/`purge-repo-on-delete`/`max-attempts`/`task-batch-size`/`bind-return-url`）；③**OAuth 报错与警示文案随 provider 变，且必须指名当前 provider 的属性键**。
- **托管方切换开关**：`aioa.repo.provider`（默认 `gitee`）。两个实现**互斥装配**（`@ConditionalOnProperty`；Gitee 侧 `matchIfMissing=true`）⇒ **条件写反 = 整个应用起不来**（已由 `RepoProviderWiringTest` 守住）。改配置后**必须重启**。
- **5 条硬分歧点**：①建仓 `name`/`path` 双字段 vs 单 `name`（Gitea 无独立 `path`，`name` 即 slug）；②Webhook 校验 **Gitee 明文共享密钥** vs **Gitea HMAC-SHA256**（`X-Gitea-Signature` 无前缀 / 兼容 `X-Hub-Signature-256` 带 `sha256=` 前缀；**须用原始字节**算，不能先 getReader）；③事件名下划线风格 + 子串包含（`issue_comment` 含 `issue`）⇒ 必须**归一化+精确映射表**；④OAuth 路径与 scope 词表**全不同**；⑤分页 `per_page`→`page`+`limit`，Gitea 硬上限 50。
  - **Webhook 校验在托管方实现里，不在控制器**：报文入口必须收 **`byte[]`**；控制器**不得**按托管方 if/else。日志只记**头名**不记头值。
  - **翻页结束条件必须是「本页为空」**，不能写「本页条数<请求条数」（Gitea 请求 100 实回 50 会被误判末页 ⇒ 第 2 页起静默丢失）。另加「整页与上页相同即停」。
  - **桩/替身必须忠实**（`gitee_stub.py` 已加 `_paginate()`）。**替身越宽容越会替真实服务掩盖缺陷**。
- **`/gitee/config` 是界面文案的唯一来源**（回 `provider`/`providerLabel`/`configKey`/`tokenRequirementHint`）。**前端整页文案必须按 `providerLabel` 渲染**；前端回落值取 `'Gitee'`（保证 Gitee 桩套件旧锚点不漂移）。
- **判据铁律**
  - `GiteaProviderClient.extractMessage()` 必须 **`errors[]` 优先**（Gitea 的 `message` 可能是**内部操作名**，如 `GetUserByName`）；落库前过 `support/ProviderFailureText`（中文归因+动作在前、托管方原文附尾）。
  - **⚠️ Gitea 对「协作者用户不存在」回 422（不是 404）**，**重复添加（已是协作者）回 204** ⇒ `isAlreadyCollaborator()` **绝不能把 422 一律当成功**（旧写法 = 假绿）。判据必须是「4xx **且**文案明确说已是协作者」。**判定「目标已达成」要锚定文案，不要只看状态码。**
  - OAuth 换令牌错误体的 `error` 是通用码，**人话在 `error_description`** ⇒ `firstDetail()` 必须 `error_description` 优先并保留 `error`。
  - **`client_secret` 可能「登记页显示的值永远校验不过」**：判据三分 ①不存在 client_id → `cannot load client with client id`；②空密钥 → `invalid empty client secret`；③正确值≡错值 ⇒ **该应用已废**，只能**新建应用**（`POST /user/applications/oauth2` 的**创建响应**才返回明文 secret）。当前有效 `client_id=a2e8f7bd-8f0b-4a2f-a1e5-345b5741b0cd`。
  - **`/oauth/authorize` 不接受私人令牌**，Gitea 也不支持 `client_credentials` ⇒ 浏览器那半程必须由人完成。
- **源码审计三条**（`RepoProviderNeutralityTest`）：①服务层不得 `catch (GiteeApiException)`；②`gitee_account` 条件查询必须带 `getProvider`；③`service|controller|support` 下 `Gitee `（含**句中**写法）只准出现在注释或 `log.*`。
- **切 provider ⇒ 既有令牌不可解密是预期行为**（两段各一个 `token-enc-key`），需重新授权绑定，**不是 bug**。原实现只在 `acc == null` 时回落 ⇒ 建项目 500；现 `decryptTolerant()`：解不开 = 本平台下没这条绑定 → 回落企业令牌。
- **V54 迁移**：`gitee_account` 加 `provider` 列，唯一键并入 `provider` + `gitee_uid` ⇒ 一个用户可同时持有两个身份。漏掉 provider 过滤的症状：建项目 500 / 拿异平台登录名加协作者 404（**同步静默失败**）。
- **沙箱回调覆盖真实绑定的守卫**：`GiteeAccountService.clobberRealBinding()` + `STUB_UID_CEILING=1_000_000`。判据：**桩签发 5 位 uid，真实账号 8 位**。沙箱 + 既有 uid ≥ 10^6 + uid 不同 ⇒ 拒绝。⚠️ 该判据常数依赖「桩 uid 是 5 位」，桩若改签发 8 位会把桩套件全拦红。
- **同一时刻只许起一个后端实例**：两实例共库会**互抢同一个任务队列**。`AIOA_GITEE_SYNC_ENABLED=false` **只停 cron，不停 worker**。
- **不要用真实接线跑 `e2e_full_system`**：平台会**在真实组织上真的建仓**留下残留。该套件必须在桩接线下跑；切桩接线要重启且会碰「桩覆盖真实绑定」陷阱。
- **Gitea 1.26.2 实测契约**：默认分支 `main`（非 `master`）· Webhook `secret` **只写不读** · 请求 4 个事件实际落 **14 个**（断言用**子集**）· `/hooks/{id}/deliveries` → 404 · SSH 端口 **2222** · 协作者 `PUT` 需 **JSON body**（query 形式 422）。详见 `.workbuddy/artifacts/gitea-api-contract-1.26.2.md`。
- **真机验证配方**：`e2e_gitea_live.py`（81 条，自净）· `_check_gitea_ui_provider.py`（17 条，自净）· `_check_gitea_cfg_failure_ui.py`（16 条，自净）。基线：真机 **81/81**（连跑两次）· 界面 17/17 · 配置失败 16/16 · `e2e_v51_gitee_init` 50/50 · `e2e_v48_gitee` 116/116。⚠️ **套件分两种接线，不能同时接**（`e2e_gitea_live`/`_check_gitea_*` 要真机接线 `.env.gitea-real`；`e2e_v48_gitee`/`e2e_v51_gitee_init`/`e2e_full_system` 要**桩接线** `scripts/gitee-e2e-env.sh`）。切换只需重启后端，**不用重新打包**；跑完必须切回真机接线。⚠️ **改断言/改可见文案后要连跑两次**，且 `_check_gitea_ui_provider.py` 的 L3「整页不出现 Gitee」是**数据面**哨兵（回填文案被它抓红过）。
- **⚠️ 真机专属环境限制：Webhook 入站不可达**（本机经两层 NAT，无回程路由）。**出站全正常**。要真验入站必须同网段部署。套件用「本地构造报文 + 正确 HMAC 签名」直投平台端点，验的是**协议正确性**，**不等于网络可达性**。
- 接线文件（均 gitignored）：`.env.gitee-real` / `.env.gitea-real` → `set -a && . ./.env.gitea-real && set +a` + 启动 jar。关键项：`AIOA_REPO_PROVIDER=gitea` · `AIOA_GITEA_BASE_URL=http://172.16.8.249:3000/api/v1`（**必须带 `/api/v1`**）· `AIOA_GITEA_ORG=AI-OA` · `AIOA_GITEA_WEBHOOK_BASE_URL`（**必须 Gitea 能访问到**）。
- **仍叫 `Gitee` 的地方**（有意保留）：`log.*` 文案、类名、`gitee_*` 表名 —— 改名属纯重构。

## 8. 环境变量与向量库
- **env 两套文件**见 §1。**前端 env 单独一档**（vite 只读各应用自己的 `.env`：`web/apps/shell/.env` 的 `VITE_PORT`/`VITE_API_TARGET`、`user-client/.env` 的 `PORT`/`BACKEND_HOST`/`BACKEND_PORT`）—— 写进 `deploy/.env` **无效**。`.gitignore` 已加 `!deploy/.env.development` / `!deploy/.env.production` 例外（两份只含占位值）。
- **向量库现状（与设计文档不符）**：向量存储在 **Java 侧** `aioa-resource/store/`，不在 agent。SPI = `KnowledgeStore`（9 方法），实现 `MysqlKnowledgeStore`（默认 `matchIfMissing=true`，文档+切片在 MySQL、embedding 存 float32 小端 BLOB、检索 = n-gram 关键词 + 余弦 + **RRF k=60**）与 `ElasticKnowledgeStore`（**骨架**：写抛异常、读**静默返回空**）。配置 `aioa.kb.store`（默认 mysql）。嵌入 = `EmbeddingProvider.local()` = **256 维 char 2-gram 哈希（无语义！）**，`EmbeddingConfig` 硬编码。唯一注入点 `KbService`（`ToolGatewayService.searchKb` 经它）。数据：21 文档 / 556 切片 / **已向量化仅 62 条**。`docs/01` 写的 pgvector 与现状不一致。
- **Milvus 迁移计划见 `docs/32`**。核心判断：**只换 Milvus 不换嵌入 ⇒ 检索质量几乎不变**，故「换库+换嵌入」绑为一个目标、**拆两步交付**（Ph1 先升嵌入 → Ph2 再接 Milvus）。MySQL 保留为**切片权威底座**，Milvus = 可重建的索引副本 ⇒ 回滚 = 改一行配置。6 决策点（推荐）：`bge-small-zh-v1.5`(512) · 嵌入走 **HTTP**（复用 compose 已有的 ollama/vllm，`local` 留兜底）· Milvus **2.5.x** · Milvus 存「向量+内容+过滤元数据」· `partition_key=tenant_id` + expr 过滤 · 不可用 **fail-fast**（禁重蹈 ES 骨架静默空结果）。硬风险：集合维度创建后不可改（须先锁）、`milvus-sdk-java` 对 2.5 原生 BM25 支持需实测（不通则退回客户端 RRF）。
