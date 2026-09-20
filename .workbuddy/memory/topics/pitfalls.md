# 关键坑明细（已修，勿回退）

> 摘自 `MEMORY.md §3`（2026-09-19 拆分）。**编码 / 排查缺陷 / 写套件前先读本文件**。
> 缩写：SPI / E2E / 术语按项目惯例。

**框架 / 构建 / 状态机**
1. `aioa-common` **不引 spring-security** ⇒ `@RestControllerAdvice(Exception)` 把 `AccessDeniedException` 吞成 500。统一 `BizException.forbidden()`→403；`NoResourceFoundException` 已补 404。
2. 给 Java `record` 加字段必须全局搜构造点（`grep -rn "new XxxView(" server/ --include=*.java`）——漏一处即编译失败，且 `mvnw -q package` 失败可能很安静。
3. MyBatis-Plus 清空字段默认 `update-strategy=NOT_NULL` ⇒ `setErrorMsg(null)` **是空转**（库里还挂旧文案）。修法：`@TableField(updateStrategy=ALWAYS)` 或 `LambdaUpdateWrapper.set()`。验证「清空生效」= 写脏 → 走真实动作 → 回读必须为空。
4. `decide()` 判定顺序：CC 任务 `status='CC'`（非 PENDING），**必须先判 `task_role=CC` 再判状态**，否则「知会无需审批」分支**永不可达**。
5. **多步状态机每一步失败都要有终态**（gitee_project 实测）：`CREATING --(建仓 + 配 Webhook 都成功)--> ACTIVE` 是**两条任务**，只有建仓侧 `markFailed` ⇒ 配 Webhook 失败时项目**永远停在 CREATING**、界面无红字、校准只扫 ACTIVE ⇒ 无人再动它。凡「A 步成功才入队 B 步」，B 的终态失败必须回写主对象。
6. **「先软删、再异步入队」的动作，执行段一律不得 `selectById`，必须从 payload 取值**：`@TableLogic` 读到 null → 静默 `return` → 任务记 DONE 但真站资源还在（假成功）。改这类坑要**全局搜同类**（改一个漏一个是常态）；信息不全必须**抛错判 FAILED**——不可逆动作绝不静默成功。
7. **收件人角色必须按租户口径取且必须实测**：`selectTenantAdminIds` 曾硬编码 `role_code='ROLE_ADMIN'`（平台管理员仅 1 个且挂 tenant 0）叠加 `tenant_id` ⇒ **每个真实租户命中 0 人**，租户管理员从未收到通知。正确 `IN ('ROLE_ADMIN','ROLE_TENANT_ADMIN')`。
8. **MySQL 唯一键不约束 NULL ⇒「默认行」绝不能用无 limit 的 `selectOne`**：`notification_preference` 的 NULL 默认行可重复插入 ⇒ `TooManyResultsException`；在 `@Async @EventListener` 里异常沿 `dispatch` 冒泡被最外层 try/catch 吞掉 ⇒ **整轮分发静默中断**（现象「有记录无投递」）。一律 `.last("limit 1")`。
9. 软删 + 唯一键：`sys_user.username` 唯一键**覆盖软删行**，`AccountProvisioner.resolveOrCreate` 须先查软删行再 `reviveUser`，否则重建同名管理员 500。

**前端**
10. `api/index.ts` 的 `unwrap` **必须校验 `code`**：body 含「数字 `code`+`message`」即按信封处理，`code≠0` 抛 `ApiError`。旧实现只在含 `code`+`data` 时剥壳，而后端 `non_null` 让失败响应 `data` 键消失 ⇒ 整封信封当业务数据。「页面空白无数据」基本都此根因。
11. 接口返回结构不统一 ⇒ 前端 `asArray()` 兼容 数组/`{list|items|records|data|rows}`；`renderAll` 每块独立 try/catch（否则一块抛异常后续全空白）。比对分页总量用 `total`，**不能用 `len(list)`**。
12. H5 单文件：页面 `go('page-xxx')`；session `localStorage['aioa_session']={token,user}`；无头校验用 `add_init_script` 注入；改完先 `node scripts/_syntax_h5.js` 再 `node scripts/_refaudit_h5.js`。图标只引用 sprite 真实存在的 `#i-*`（不存在**静默留白**）。Tab 栏高 76px，flush 页需单独 `padding-bottom:76px`。
13. 成果列表接口**不含 body**，详情走 `GET /api/v1/results/{id}`。登出先 `clearSession()` 再 best-effort 远端；`<router-view>` 必须带 `sessionActive &&` 闸门。
14. **合并菜单禁用 `alias`**（`alias` **继承**被别名路由的 `allowRoles` ⇒ 深链旧路径不再被拦截 = 顺手放宽边界）。正解 = **独立路由**沿用原 `allowRoles`；共用组件时默认页签用 `watch(immediate)` 而非 `onMounted`，目标页签不可见时**必须回落**，`:default-active` 做「旧路径→合并入口」映射。
15. **侧栏滚动隔离的根因是 flex 高度链**：`.el-container` 是 `flex:1; flex-basis:auto`，flex 项默认 `min-height:auto` ⇒ 内侧行被整棵菜单撑高且无法收缩。四处齐改才成立：`.layout{overflow:hidden}` + **内侧 flex 行 `min-height:0`** + `.layout-aside{overflow-y:auto}` + `.layout-menu{min-height:100%}`（**不能 `height:100%`**）。判据 `document.scrollHeight == clientHeight`；探针 `scripts/_check_menu_scroll.py`（27 项）。
16. **管理端菜单分组**：21 个一级项 → **5 个一级 + 6 个分组子菜单**；分组 `v-if` = 子项可见性之「或」，**子项守卫与路由 `index` 一律不动**；改分组归属**必须同步 `MainLayout.vue` 的 `PATH_GROUP`**，否则深链进来该分组不展开 = 菜单一项都不高亮。

**权限 / 审批 / 组织**
17. 额度闸门判据 `state.quotaInfo.exhausted===true`（**勿**用数字型默认值表达「未知」，`state.left` 初值 0 曾致误判「额度用完」）。复位 `scripts/reset_demo_quota.py`。
18. 审批流解析优先级：机构专属 > 租户默认(`institution_id=0`) > 内置单级兜底。`audit_log` **永不 UPDATE**。假种 `quota_days_per_year=0` = 不占额度只走审批（`quotaTracked=false`）。
19. 审核态闸门：V34 起租户管理员建的内容 `audit_status=PENDING`，对成员不可见、不被调度；V36 权限申请**终态回调才置 ACTIVE 并发放**（`granted_by/at`=终态处理人/时间）；`expert_config` 生效解析**必须过滤 `audit_status='APPROVED'`**；终态回调里 `order` 是**决策前**快照，意见/审批人须回查 `approval_task`。
20. `aioa-resource` 与 `aioa-org` **互不依赖**；只有 `aioa-chat` 同时依赖二者。需同时读「权限/计费/工具」与「组织/审批/假种/知识库」的功能只能落 `aioa-chat`。
21. **V39 审批链递推**：`ApprovalFlowService.expandNodes()` 遇 `APPLICANT_SUPERIOR` **不展开固定 steps_json**，改用 `superiorLadder()` 从「申请人层级+1」起逐级展开，跳过 null/申请人本人(自审防护)/重复人；兜底分支必须把 `effectiveType` 置为**实际生效类型**。
22. **V41/V42 职务与知会**：`org_duty` + `org_member.duty_code` 是「谁是部门负责人」的**唯一权威口径**（原 27/8/3 三口径已收敛）。steps_json 新增 `levels`(1=只批一级) 与 `cc`（生成 `task_role='CC'` 任务，**不阻塞**流程、不进 todo、不可 decide）。
23. **V43 部门申请 + 知会已读**：新增 `approval_order.applicant_type`(`USER`|`DEPARTMENT`)+`applicant_department_id`、`permission_grant.applicant_type`、`approval_task.cc_read_at`。① 部门申请起点 = **`ORG_ADMIN`**（跳过 DEPT_LEADER，保留自审防护与 levels 截断）；② 负责人判定**只认 `duty_code='DEPT_PRINCIPAL'`**，`job_title` 不作权限依据；③ 跨机构/跨租户/平台 → **404**、同机构非正职 → **403**，**均不落库**；④ `summary.cc` 固定为**总条数**（不因已读减少），未读另开 `ccUnread`；⑤ 底部「待办」角标**不计入 CC 站内通知**（`tab = 待审数 + 未读通知数(剔除 refId ∈ 我的抄送单)`，仅 `user-client/index.html` 一处）；⑥ 授权仍发给**提交人本人**（部门共享权限未排期）。
24. **V45 策略族 + 节点组**：审批人解析走 `cn.aioa.org.support.approver`（`ApproverResolver` 门面 + `DutyApproverStrategy` 抽象 + `DeptDuty`/`UnitDuty`/`DeptLeader` 三实现 + 4 个固定口径 Bean）。**策略返回「有序候选列表」**，消费层才决定用几个 ⇒ 会签/抢占的基础。同 `seq` = 同一「级」：`isCurrentNode` **按 `seq` 比较**（不是 id）、`countTasksOfOrder` 用 `COUNT(DISTINCT seq)`（前端「共 N 级」同理，**不能用时间线行数**）。`mode`=single/parallel/grab；`when`={field,op,value} —— **运行期宽容**（未知模式退 single、坏条件不拦）、**保存期严格**（`writeSteps` 校验 mode/when/cc，非法 400），且**永远至少留一个生效节点**（回落首个无条件节点→末级并写「流程提示」）。`cc` 支持对象形态 `{"type":"SPECIFIC","user_id":N}`。
25. **V46 令牌吊销**：`revoked_token` 表 + JWT 带 `jti`；`JwtAuthenticationFilter` 在**验签与过期通过之后**再查吊销表（顺序不能反）。`TokenRevocationChecker` 是接口、`DbTokenRevocationChecker` 是实现（放 `aioa-admin`，安全模块只依赖接口）。
26. **V47 回填 + 新租户播种**：① `LeaveTypeProvisioner` 只对**零 `leave_type`** 的租户播种 6 类标准假种（常量与 tenant 2 逐字节一致）；② `cc` 回填**机构级**定义；③ `org_member.duty_code` 回填**不触碰 `job_title` 含「负责人」的行**、也不把局长/总经理强升 `ORG_LEADER`；④ 无负责人部门补人。
27. **同类播种器必须实测**：`ApprovalFlowProvisioner` / `LeaveTypeProvisioner`(`@EventListener(TenantProvisionedEvent)`) 只在建机构时触发 + 内部 try/catch 吞异常 = **失败静默**。
28. **管理端配置页 = 能力的唯一入口**：引擎支持但配置页配不出来 = 能力**事实上不可用**。`constants/permissions.ts` 是审批人类型/职务/模式/条件字段的**唯一常量入口**（视图里不得再抄字面量）；配置页须做 `_extra` **无损往返**，否则管理员每次「打开-保存」都悄悄丢配置。

**展示 / 一致性 / 外部接口**
29. **同一决策点必须在「一处」判定**：`GiteeTenantConfigService.effectiveOrg`（行存在 **且** `enabled=1` **且** org 非空）与 `buildView` 的 `source`（只看 `row != null`）是两个谓词 ⇒ 「有行但 `enabled=0`」时界面显示「企业自配置」却指向**共享**组织。修法：抽单一判定共用（**不要在展示层打补丁**）。「新增一个可配置维度 ⇒ 造出旧状态机从未有过的组合」是最易漏的缺陷类型，**必须为该组合补断言**。
30. **展示字段与事实必须同源**：`gitee_project.webhook_events` 落库写死 Gitee 词表，Gitea 详情页据此渲染 ⇒ **明确说错自己订了什么**。修法：接口层 `RepoProviderClient.hookEventNames()` 复用建钩子的同一函数。**回填用户可见字段时不准照抄历史原文**——原文带着当时环境（托管方名/配置键/路径），判据「这行文本放到**今天**的配置下，还是真的吗？」（V56→V58 实测）。
31. **「tenant 覆盖 + 回落全局默认」是加配置维度的首选形态**：不播种任何租户行 ⇒ 回落路径天然被既有数据与套件持续验证；强制必填会把存量数据变成迁移问题。**「留空」类语义先查有没有可回落的东西**：平台**不存在**共享企业令牌 ⇒ 首次留空**本就应当失败**，正解是「必填 + 文案可读 + 前端按 `tokenConfigured` 动态必填」，**不是**让它静默成功；报错文案**绝不回显 `null`**。
32. **状态字段契约不留 `null`**：如 `initStatus` 恒 `PENDING|ACTIVE|FAILED`，无配置行/空值归一化为 `PENDING`，「是否落过行」由 `configured` 单独表达。留 null 会逼前端各自写兜底分支。
33. **诊断端点必须回「报告」不能回「错误」**：恒 `HTTP200 + code=0` + 顶层 `passed`/`failedStep` + 全量 `steps`（永不落库）；**动作端点**才失败即抛。`passed` 必须与 `steps` **同源推导**，否则「顶层说通过、明细里有红字」。
34. **核实关键字命中语义再下结论**：本系统 `schedule` 实为**定时任务**（非日程）、`push` 实为 **git push**、`notification` 表**仅站内单通道**。做差距分析前先 `SHOW TABLES` + 看命中文件名。
35. **「展示值来自外部接口」必须用对照实验定性**，不能靠读代码断言：仓库地址是接口响应原样写库原样读出（前端无兜底域名），只能靠**让桩返回生产形态**验证（`POST /_stub/public-base`；默认 None = 历史行为逐字节不变）。

**工具 / 流程纪律**
36. **长驻服务绝不能由子代理启动**：子代理被 kill（如 429）时其**子进程随之死亡**，桩/后端静默消失，后续套件全红且难查。桩(8090)、后端(8080) 一律由主代理以后台常驻任务启动。
37. **子代理被限流中断会留下「半成品」，比没做更危险**：可能「已改 router 并新建视图，但菜单没改」，且引入的 `alias` 放宽了权限——这些**能通过 `vue-tsc`**。接手前必须**逐文件核对改到哪一步**。
38. **本环境禁用 `git rm`**（2026-09-18 一次误删把整个目录清空）：改为 `rm 明确文件列表` + `git add`，清理小步走、每批后核对 `git status`。恢复路径：① 删 0 字节 `index.lock` → `git restore --worktree -- <dirs>`；② 未跟踪文件从 `~/.workbuddy/projects/<conv>/*.jsonl` 重放 `Write`+`Edit`；③ `~/.workbuddy/file-history/<proj>/<hash>@vN` 做内容级校验；④ 跟踪文件以 git 为准。**恢复正确性用「跑套件」判定，不能用文件大小**。
39. **E2E 反模式**：① **toast 断言必须轮询**（`ElMessage` 3000ms 自动关，"固定 sleep 后一次性读"必读到空数组）；② **禁硬编码项目/单据 id**（桩是**内存态**，重启后旧项目消失 ≠ 前端 bug；正解：现建一个）；③ **单条检查要 try 兜底**（否则一条超时让整场崩溃、零信号）。
40. **测试里的「恒真断言」比没有断言更危险**：`chk(name, True, "")` 让用例永远绿。另有一类**依赖校验顺序**的用例 —— 必须构造前置步骤可通过的输入，让失败点确定落在被测步骤。

**构建 / 打包**
41. **`.gitignore` 裸目录模式会吞掉源码**：不以 `/` 开头的模式（`data/`、`logs/`、`dist/`）匹配**任意层级**。本项目 `data/` 曾把 `web/apps/demo-ticket/src/data/` 整个忽略，而该文件 `git log --all -- <路径>` **无任何记录** ⇒ **从未入过库**（随 `c1dca22` 引入 compose 起就缺），本地能编只因文件在磁盘上。凡「本地过、CI/容器不过」，先跑：`git check-ignore -v <文件>` + `git status --porcelain --ignored`。修法：目录模式一律**锚定根**（`/data/`）。另注意 `--ignored` 里出现 `scripts/e2e_*.py` 属**约定不入库**（本地回归台），不是缺陷。

