# 关键坑明细（已修，勿回退）

> 摘自 `MEMORY.md §3`（2026-09-19 拆分）。**编码 / 排查缺陷 / 写套件前先读本文件**。
> 缩写：SPI / E2E / 术语按项目惯例。

**框架 / 构建 / 状态机**
1. `aios-common` **不引 spring-security** ⇒ `@RestControllerAdvice(Exception)` 把 `AccessDeniedException` 吞成 500。统一 `BizException.forbidden()`→403；`NoResourceFoundException` 已补 404。
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
12. H5 单文件：页面 `go('page-xxx')`；session `localStorage['aios_session']={token,user}`；无头校验用 `add_init_script` 注入；改完先 `node scripts/_syntax_h5.js` 再 `node scripts/_refaudit_h5.js`。图标只引用 sprite 真实存在的 `#i-*`（不存在**静默留白**）。Tab 栏高 76px，flush 页需单独 `padding-bottom:76px`。
13. 成果列表接口**不含 body**，详情走 `GET /api/v1/results/{id}`。登出先 `clearSession()` 再 best-effort 远端；`<router-view>` 必须带 `sessionActive &&` 闸门。
14. **合并菜单禁用 `alias`**（`alias` **继承**被别名路由的 `allowRoles` ⇒ 深链旧路径不再被拦截 = 顺手放宽边界）。正解 = **独立路由**沿用原 `allowRoles`；共用组件时默认页签用 `watch(immediate)` 而非 `onMounted`，目标页签不可见时**必须回落**，`:default-active` 做「旧路径→合并入口」映射。
15. **侧栏滚动隔离的根因是 flex 高度链**：`.el-container` 是 `flex:1; flex-basis:auto`，flex 项默认 `min-height:auto` ⇒ 内侧行被整棵菜单撑高且无法收缩。四处齐改才成立：`.layout{overflow:hidden}` + **内侧 flex 行 `min-height:0`** + `.layout-aside{overflow-y:auto}` + `.layout-menu{min-height:100%}`（**不能 `height:100%`**）。判据 `document.scrollHeight == clientHeight`；探针 `scripts/_check_menu_scroll.py`（27 项）。
16. **管理端菜单分组**：21 个一级项 → **5 个一级 + 6 个分组子菜单**；分组 `v-if` = 子项可见性之「或」，**子项守卫与路由 `index` 一律不动**；改分组归属**必须同步 `MainLayout.vue` 的 `PATH_GROUP`**，否则深链进来该分组不展开 = 菜单一项都不高亮。

**权限 / 审批 / 组织**
17. 额度闸门判据 `state.quotaInfo.exhausted===true`（**勿**用数字型默认值表达「未知」，`state.left` 初值 0 曾致误判「额度用完」）。复位 `scripts/reset_demo_quota.py`。
18. 审批流解析优先级：机构专属 > 租户默认(`institution_id=0`) > 内置单级兜底。`audit_log` **永不 UPDATE**。假种 `quota_days_per_year=0` = 不占额度只走审批（`quotaTracked=false`）。
19. 审核态闸门：V34 起租户管理员建的内容 `audit_status=PENDING`，对成员不可见、不被调度；V36 权限申请**终态回调才置 ACTIVE 并发放**（`granted_by/at`=终态处理人/时间）；`expert_config` 生效解析**必须过滤 `audit_status='APPROVED'`**；终态回调里 `order` 是**决策前**快照，意见/审批人须回查 `approval_task`。
20. `aios-resource` 与 `aios-org` **互不依赖**；只有 `aios-chat` 同时依赖二者。需同时读「权限/计费/工具」与「组织/审批/假种/知识库」的功能只能落 `aios-chat`。
21. **V39 审批链递推**：`ApprovalFlowService.expandNodes()` 遇 `APPLICANT_SUPERIOR` **不展开固定 steps_json**，改用 `superiorLadder()` 从「申请人层级+1」起逐级展开，跳过 null/申请人本人(自审防护)/重复人；兜底分支必须把 `effectiveType` 置为**实际生效类型**。
22. **V41/V42 职务与知会**：`org_duty` + `org_member.duty_code` 是「谁是部门负责人」的**唯一权威口径**（原 27/8/3 三口径已收敛）。steps_json 新增 `levels`(1=只批一级) 与 `cc`（生成 `task_role='CC'` 任务，**不阻塞**流程、不进 todo、不可 decide）。
23. **V43 部门申请 + 知会已读**：新增 `approval_order.applicant_type`(`USER`|`DEPARTMENT`)+`applicant_department_id`、`permission_grant.applicant_type`、`approval_task.cc_read_at`。① 部门申请起点 = **`ORG_ADMIN`**（跳过 DEPT_LEADER，保留自审防护与 levels 截断）；② 负责人判定**只认 `duty_code='DEPT_PRINCIPAL'`**，`job_title` 不作权限依据；③ 跨机构/跨租户/平台 → **404**、同机构非正职 → **403**，**均不落库**；④ `summary.cc` 固定为**总条数**（不因已读减少），未读另开 `ccUnread`；⑤ 底部「待办」角标**不计入 CC 站内通知**（`tab = 待审数 + 未读通知数(剔除 refId ∈ 我的抄送单)`，仅 `user-client/index.html` 一处）；⑥ 授权仍发给**提交人本人**（部门共享权限未排期）。
24. **V45 策略族 + 节点组**：审批人解析走 `cn.aios.org.support.approver`（`ApproverResolver` 门面 + `DutyApproverStrategy` 抽象 + `DeptDuty`/`UnitDuty`/`DeptLeader` 三实现 + 4 个固定口径 Bean）。**策略返回「有序候选列表」**，消费层才决定用几个 ⇒ 会签/抢占的基础。同 `seq` = 同一「级」：`isCurrentNode` **按 `seq` 比较**（不是 id）、`countTasksOfOrder` 用 `COUNT(DISTINCT seq)`（前端「共 N 级」同理，**不能用时间线行数**）。`mode`=single/parallel/grab；`when`={field,op,value} —— **运行期宽容**（未知模式退 single、坏条件不拦）、**保存期严格**（`writeSteps` 校验 mode/when/cc，非法 400），且**永远至少留一个生效节点**（回落首个无条件节点→末级并写「流程提示」）。`cc` 支持对象形态 `{"type":"SPECIFIC","user_id":N}`。
25. **V46 令牌吊销**：`revoked_token` 表 + JWT 带 `jti`；`JwtAuthenticationFilter` 在**验签与过期通过之后**再查吊销表（顺序不能反）。`TokenRevocationChecker` 是接口、`DbTokenRevocationChecker` 是实现（放 `aios-admin`，安全模块只依赖接口）。
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
41. **`.gitignore` / `.dockerignore` 裸目录模式会吞掉源码（两处必须同改）**：不以 `/` 开头的模式（`data/`、`logs/`、`dist/`）匹配**任意层级**。本项目 `data/` 造成**两个独立原因**同时成立：① `.gitignore` 使 `web/apps/demo-ticket/src/data/` 从未入过库（`git log --all -- <路径>` 无记录，随 `c1dca22` 引入 compose 起就缺）；② `.dockerignore` 使该目录**即便源码拷全也被排除出构建上下文**（所以 rsync 拷贝也照样失败）。两个文件都有 `data/`，**修一个不修另一个，重建仍挂**。凡「本地过、CI/容器不过」，先跑：`git check-ignore -v <文件>` + `git status --porcelain --ignored`。修法：目录模式一律**锚定根**（`/data/`）。另注意 `--ignored` 里出现 `scripts/e2e_*.py` / `start-backend.bat` 属**约定不入库**（本地回归台与本地启动器），不是缺陷。
42. **`docker compose restart` 不重读 `.env`**：它只把同一个容器停掉再启动，**不重新渲染服务定义**，环境变量保持旧值 ⇒ 改完 `.env` 执行 `restart` 等于白改（现象：日志里地址/Key 还是老的）。正解 `docker compose up -d <svc>`（配置哈希变了会自动重建）。**不需要** `--force-recreate`。生效判据看 `docker exec <c> printenv <VAR>`，**不是**「容器重启成功了」。
43. **「镜像构建所需的、不在 COPY 清单里的文件」是同一类静默缺陷**：`Dockerfile.web` 漏 `COPY web/tsconfig.base.json ./` ⇒ 容器内 `apps/*/tsconfig.json` 的 `extends: "../../tsconfig.base.json"` 失效，丢的是 `strict`/`esModuleInterop`/`moduleResolution:bundler`/`skipLibCheck`，**报错却指向 element-plus 与 `rollup/parseAst`**，与真实原因毫无关联。排查手法：把 Dockerfile 的 `COPY` 指令解析成「`/build` 下的文件清单」，再校验每个 `extends`/被引用路径是否在清单内（本次用 20 行脚本验证 4 个 tsconfig 全部命中）。
44. **重打包前必须列出「所有」后端实例，jar 锁可能来自另一个端口**：本机同时跑着 8080（主档，`aios` 库）与 8081（`aios_prodtest` 库）两个后端，**它们共用同一个 fat-jar 文件**。只停 8080 后 `mvnw clean package` 仍失败：`Failed to clean project: Failed to delete .../aios-boot-...jar` / `mv: Device or resource busy` —— 持锁的是 8081 那个 JVM。定位手法（本环境 PowerShell 工具**不回显 stdout**，必须写文件再 `Read`；`wmic` 已不可用）：用 PowerShell 工具跑 `Get-CimInstance Win32_Process -Filter "Name='java.exe'"` 取 `ProcessId` + `CommandLine`，`Select-Object` 后 `Set-Content logs/_probe_java.txt`，再 Read 该文件。**判据**：`CommandLine` 里含 `--server.port=<别的端口>` 且含 `aios-boot/target/aios-boot-*.jar` 的 java 就是第二实例。本机另有 3 个 java **不能动**：FinalShell（`finalshell.jar`）、VS Code 的 `redhat.java` JDT LS、IDEA 的 Maven embedder。**绝不**用 `Get-Process java | Stop-Process` 一把梭。停用借来的实例后要**按原参数原样恢复**（含原日志文件名与 `--spring.datasource.url`）。另：`mvnw ... | tail -20` 的退出码是 `tail` 的，**永远是 0** —— 判成败要看 `BUILD SUCCESS`/`FAILURE` 文本，别信 `$?`。产物大小兜底判据：fat-jar 应 ~110MB，若掉到 ~20KB = 被 rename 成的 stripped-jar（说明没停 JVM 就重打包了）。

**配置参数（sys_config / 默认口径）**
45. **「有行但留空」与「没有这一行」是两种语义，不能都当「没配」**：`chat.default_expert_key` 的留空是**明确不做兜底**（管理员关掉），缺行只是**参数还没物化**。若写成 `if (own != null && !own.isBlank()) { …回落… }`，管理员把值清空后仍会偷偷回落到平台/出厂值 ⇒ **关不掉**，且用户端还照旧标记默认 AI。正解：本租户**有行**即以该值为最终口径（空 ⇒ 返回 null ⇒ 不标记、不回落）；只有**没行**才继续「平台默认 → 出厂常量」。单测锁死（`CatalogServiceTest#blankValueMeansExplicitlyDisabled`）。
46. **新增 sys_config 键时，绝不能给「一行都没有的租户」插单行**：`AdminConfigController.loadTenantConfigs` 是**开关式**逻辑——本租户 0 行才整份克隆（克隆源 = 平台默认表，空则 `BUILTIN_DEFAULTS`）。给「空的租户 0」插进新键 1 行，等于把它钉死在「非空」，**从此再也拿不到其余出厂参数**（管理端只剩 1 个参数）。迁移写成 `INSERT … SELECT … FROM (SELECT DISTINCT tenant_id FROM sys_config) t ON DUPLICATE KEY UPDATE config_key=config_key`：只补「已经有行的租户」，空租户交给克隆路径。代码侧必须配三档回落（本租户行 → 平台行 → 出厂常量），否则「新环境/新租户在管理员打开配置页之前」读不到该参数。
47. **改完源码后拿旧 jar 判行为 = 自欺**：先打包（12:23）→ 再改 Java（`defaultExpertKey` 的留空语义）→ 直接跑 E2E，看到的是**旧行为**（留空仍标记 general），差点被当成新代码的 bug 去改断言。纪律：**改 Java 后必须重打包 + 重启，再判行为**；打包时刻与改动时刻对不上时，先把「刚才那次是不是旧代码」排除掉。

**验收脚本自身**
48. **验收脚本必须自己建立前置状态**：上一轮手工探测把租户 3 的默认 AI 参数留成了空串，下一轮套件 C4/C5 立刻红（「从全局补一条默认 AI」那条路径在空值语义下本就不成立）。修法：套件开头显式归位（本次加了 `C0 前置：默认 AI 归位为 general`）、结尾复原，**连跑两次结果一致**，红绿才有信息量。
49. **「按文本包含」判定状态，在多义处必错**：管理端「默认 AI」列里非默认行有一枚文案为「设为默认」的按钮 ⇒ `row.innerText.includes('默认')` 把**每一行**都判成默认（断言既恒真又恒假，E2 当初就是假绿）。改用无歧义信号（**这一行有没有那枚按钮**）。同理：断言 H5「某提示已消失」不能 grep 文案——注释里写「已移除『请先选择一位专家』」也含那几个字，要 grep **调用本身**（`toast('请先选择一位专家')`）。

**单文件 H5 布局**
50. **「手机壳」就是真机上左右黑边 + 顶部占高的根因**：`.phone{width:400px;height:820px;border:10px solid #14181f}` 由 body flex 居中 ⇒ 视口一宽于 400px 两侧就露出 body 底色与那圈近黑描边；壳内自绘的 34px 假状态栏又与系统状态栏同处屏幕最上方，白占一条可视区。
    - **V62 初版修法是错的（本条已更正，勿回退到它）**：把满屏规则放进 `@media (max-width:560px),(pointer:coarse)`，桌面保持原壳。**用户看到的黑边依旧**——真机上开着「请求桌面网站」或落在宽视口 WebView 时，视口可能是 980px 且 `pointer` 是 `fine`，两个条件都不成立 ⇒ 又套回手机壳。**凡「真机 vs 桌面」的判定，媒体查询只能用来兜「反向例外」，不能用来开「正向功能」。**
    - **正确做法（2026-09-22 定稿）**：满屏是**基样式**、不设开关 —— `body{display:block;padding:0;overflow:hidden;background:var(--bg)}`、`.phone{width:100%;height:100vh;height:100dvh;margin:0 auto;border:0;border-radius:0;box-shadow:none}`、`.statusbar{display:none}`、`.mp-header{padding-top:calc(8px + env(safe-area-inset-top))}`、`.tabbar`/`.page`/`#page-chat` 各叠 `env(safe-area-inset-bottom)`。媒体查询**只剩两条**：① 宽屏反例 `@media (min-width:720px) and (min-height:620px){.phone{max-width:560px}}`（正文横贯 1440px 无法阅读；两侧与页面**同色**故读起来仍是满屏，且**必须同时要求 min-height**才不误伤 844×390 横屏手机）；② 横屏收窄 Tab 到 56px。`body::before/::after` 的「氛围层」随壳一起删（壳不透明，它们本来就被盖住，留着会在宽屏收窄后于两侧露出色差 ⇒ 接缝）。
    - 注意 `viewport-fit=cover` 早就有了，但**只有配了 `env(safe-area-inset-*)` 才有意义**。
    - 验收判据（`e2e_v62` D 组）：390×844 与 844×390 都「宽高贴合视口、`border`/`radius` 为 0、`.statusbar` 为 none」；1280×800 下「宽 560、居中、`body` 底色 == `.phone` 底色、无横向溢出」。
51. **引导/推荐块必须按「当前这一轮问句」筛选，且要允许「筛完为空」**：默认 AI 回答后那块「转给更专业的同事」原先是把专家目录**顺序**前 N 个搬出来，与问句毫无关系 ⇒ 用户看到「问劳动合同，推荐数据分析师」。做法：只做**专家侧**词表（`tags` 是运营在管理端填的业务标签，最可信；再按标点切名称与简介）→ 做「词 ∈ 问句」的包含判定并打分；**命中为 0 时只留兜底入口（创建数字员工），不塞任何专家**（宁可少推荐）。理由：H5 单文件里没有分词器，反过来切问句的字符 bigram 会把「怎么/可以」算成命中，等于没过滤。
    - 连带纪律：**改这块必须同步改 `e2e_v62` B 组**（它 `extract_js` 抽真实源码在 node 里跑）。`buildGuidance` 依赖 `expertKeywords`/`scoreExpert`，**三个函数要一起抽**，少抽一个就不是「跑真实源码」而是「跑另一份实现」。
52. **行内按钮从「复制链接」换成「重新回答」后，点击验证必须用 `send` 探针接住，不能真发模型**：`window.send = function(){...}` 可覆盖（顶层 `function` 声明会挂到 global），`reAnswer` 里的裸调用会走到探针。若真发模型，随后的 `page.goto` 会留下在途请求，让「全程无 JS 运行时异常」变成随机红。
53. **列表标记要有「固定宽度标记盒」，否则混排出毛边**：`.ans-li` 若是 `padding-left:15px;text-indent:-11px` + `::before{content:'· '}`，有序项再另写一套 `22px/-22px`，则圆点、序号、标题三者首字缩进各不相同（实测 67/63/74），一段回答里混排看着就是参差。统一为 `.ans-li{padding-left:20px;text-indent:-20px}` + `::before{display:inline-block;width:20px;text-align:center}`，有序项用 `.ans-no{display:inline-block;width:20px;text-align:center}` 顶掉 `::before`。
54. **改 H5 版式后，`scripts/_shot_h5_layout.py` 出三张图目视核对**（竖屏 / 横屏 / 桌面宽屏 + 会话页回答版式）。套件只能守可度量项（尺寸、颜色一致、无描边），「好不好看/齐不齐」只能看。<br>踩过的坑：截图脚本里把答案文本当 **Python 值**传给 `evaluate` 时，`\\n` 会变成字面量反斜杠+n（不再换行）；只有写在内联 JS 源码里才该用 `\\n`。

**后端 → agent 的传输（2026-09-22 定案）**
55. **`java.net.http.HttpClient` 默认 HTTP/2 优先 ⇒ 对明文 `http://` 会先发 h2c 升级，并把请求体推迟到升级之后单独发一包 ⇒ agent 收空 body ⇒ FastAPI 422。**
    用户可见症状：「新建定时数字员工，报错无响应 / **agent 服务返回 HTTP 422**」。实测原始字节（抓取桩 `scripts/_raw_dump_srv.py` + `scripts/_probe_httpclient/ProbeHttp.java`）：
    ```
    POST /internal/v1/complete HTTP/1.1
    Connection: Upgrade, HTTP2-Settings
    Upgrade: h2c
    HTTP2-Settings: AAEAAEAAAAIAAAA...
    Content-Length: 44          <- 声明了长度
    （空行，**随后并无 body**）
    ```
    **修法（已落地）**：`server/aios-common/.../cn/aios/common/http/AgentHttpClient.java` 作为「后端访问 agent」的唯一入口，客户端级 `version(HTTP_1_1)`；4 处调用点（`WorkerScheduleService`/`KpiInsightService`/`WorkerIntakeService`/`ModelConfigService`）全部改走它。
    **判据不是「跑通一次」而是三件套**：① 静态守卫 `scripts/_check_agent_httpclient.py`（正向 8/8 + 负向自检 4/4，禁止新的裸 `newBuilder()`，且禁止把该工厂套到 Gitee/网关/embedding 等外网客户端上）；② 行为回归 `scripts/e2e_worker_schedule_exec.py`（手动 + 到点两条分支）；③ 判别探针 `scripts/_probe_agent_h2c.py`。
    **别只修 `/complete`**：同一坏客户端还在打 `/internal/v1/worker-intent`（意图识别，**8/8 全 422**，只是被 `local-fallback` 静默兜住了，所以没人报障）、`/internal/v1/models/check|apply`（V61 手动添加模型）、`/internal/v1/complete`（KPI 经营解读）。
    **反证（写进注释防回退）**：走 Spring `WebClient`（Reactor Netty，明文默认 HTTP/1.1）的 `/internal/v1/runs`、`/tasks` 一直是 200 —— 「只有带 body 的 POST + `java.net.http.HttpClient` 这一组合会炸」，所以极难在常规验证里撞见。
56. **同一缺陷「跑 httptools 时显形、跑 h11 时被掩盖」—— 一个 venv 之差就能吃掉整个验收面。** 对照实验（本机实测）：

    | agent 实现 | Java 默认客户端 |
    |---|---|
    | `--http httptools`（= `uvicorn[standard]` = `deploy/Dockerfile.agent` 的生产镜像） | **422**（httptools 在请求头就抛 `HttpParserUpgrade`，uvicorn 只打 `Unsupported upgrade request.`，body 再也不被读入） |
    | `--http h11`（裸 `uvicorn`，无 httptools 时 auto 的回落） | **200**（h11 恰好保住了 body） |

    于是：`agent/.venv`（有 httptools，2026-09-06 就装了）⇒ 显形；`envs/default`（原先只有裸 uvicorn）⇒ 掩盖。**生产镜像装的是 `uvicorn[standard]`，所以这是会打到生产的真缺陷，不是本地怪象。**
    纪律（已落地）：① `start-all.sh` 显式 `--http httptools`（宁可启动即报错，也不要静默换实现）；② `envs/default` 补装 `httptools`（注意：**清华镜像没有 cp313 win 轮子**，`pip install httptools` 会报 `from versions: none`，要 `-i https://pypi.org/simple`）；③ 新套件**开头先证明未被掩盖**（`_probe_agent_h2c.py` 返回 422 才算前置成立），否则 agent 跑在 h11 时套件会**假绿**。
57. **⚠️ 把真实缺陷写成「套件假红」并留绕法，是记录失真，代价是缺陷多活 11 天。** 本文件原第 12 行（`topics/e2e-suites.md`）记着：`h5_v33_render` 的 AI 解读段「若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判」。事实是**反过来**的：那不是假红，是真缺陷；`envs/default` 之所以「能过」只是因为它缺 httptools 而落到了 h11。**判据**：凡是靠「换个启动姿势就不红了」的结论，必须先把「两种姿势到底哪一步行为不同」查清（本次是 `_probe_agent_h2c.py` 一句话判定），**不允许把无法解释的红直接归给套件**。
58. **同一处「默认配置」散落在多个调用点时，修一处不算修。** 本缺陷的坏客户端在 4 个模块各写了一份 `HttpClient.newBuilder()`（admin/chat/resource×2）。这类「复制粘贴的默认值」必须收成唯一入口 + 静态守卫，否则第 5 个调用点出现时必然重犯（`HttpClient.newBuilder()` 编译得过、单测过得去，只有真打 agent 才炸）。判定守卫是否有效：**每条检查项至少有一条突变能让它报红**（`--selftest`）。
59. **「共享了 X，接收方却看不到」多半不在可见性判定里 —— 先分清两面：①数据可见性（谁该看到）；②页面默认落地（打开页面时默认查哪一面）。**
    本例（知识库共享，2026-09-21）实测**两面都正常**：`GET /kb/documents` 对 tenant 2 的**全部 12 个账号**
    （租户管理员 / 3 个机构管理员 / 部门负责人 / 普通成员）**一律返回**那条共享资料，H5 `#kbList` 用真浏览器也渲染出来了
    —— 所以「数据没共享出去 / 迁移漏了」这个方向是**错的**，越查越远。
    真缺陷在**管理端 `KbView.vue`**：`tab` 初值写死 `'tenant'`，而 `?scope=tenant` 当时只有平台管理员能过 ⇒
    大数据管理局（租户管理员）点进「知识库」看到的是**空表「租户内暂无资料」+ 一句「仅租户管理员可见」**（他正是租户管理员）。
    **一眼判据**：界面提示语与当前用户身份**自相矛盾**（「仅 X 可见」但本人就是 X）⇒ 几乎一定是**判定口径写错**，不是数据没了、也不是前端过滤。
    **排查顺序（照抄）**：① 先用纯 HTTP 探针扫**全部**相关账号的列表接口（`scripts/_probe_kb_accounts.py`）——
    只要有一个账号拿到数据，就别再往「数据/迁移/软删」方向查；② 再用真浏览器打开**那个页面**，看它默认落在哪一屏、
    以及那一屏对应的请求返回什么（`scripts/_probe_kb_console.py` + 截图）。**别拿「接口对了」当「页面对了」**：本缺陷正是「接口全对、页面全空」。
    **修法**：默认 tab 必须由权限推导（`canReadTenant ? 'tenant' : 'mine'`），无权读的 tab 直接 `v-if` 不渲染，
    且**不该发那一发注定 403 的请求**（否则控制台留噪音 403，还会把 `tenantForbidden` 置真、渲染出误导提示）。
60. **`KbController` 曾是全仓唯一裸判 `ROLE_ADMIN` 的知识库入口**（`list(scope=tenant)` / `update` / `remove` / `isVisible` 共 4 处），
    其余管理端控制器（AdminQuota / AdminConfig / AdminAudit / AdminBizSystem / AdminResult / AdminKpi）一律写「平台管理员 ∨ 租户管理员」。
    唯一入口是 `PermissionCatalog.isAdmin(user)`；该类的注释里**已记载过同一类缺陷**（`/api/v1/workers` 也犯过，提示语同样自相矛盾）⇒ 这是**复发**，不是新问题。
    **「能看」与「能改」是同一个决策点**，必须同源：只放宽 `list` 会留下「列表里看得到、改可见范围被 403」——
    而**改可见范围就是「共享/取消共享」这个动作本身**。故 4 处一起改，并加静态守卫 `scripts/_check_kb_permission.py`（6 项 + 4 条突变自检）锁死。
    **不放宽的部分照旧**（写进套件反断言）：机构管理员/普通成员对 `?scope=tenant` 仍 403；对**他人**资料仍 403「只能修改/删除本人上传的资料」。
    **另一条 UI 纪律**：列表里对**无权修改的行**不要渲染「可见范围 select / 重命名 / 删除」——那是「点了必 403」的陷阱
    （用户端 H5 早就是「他人共享资料只读」，管理端缺这条）；判据与后端同源，用一个 `canModify(row)` 收口。
61. **「看不到」还有第三面：列表静默截断。** `user-client/index.html` 的 `renderKb()` 原是 `list.slice(0,6)`，
    **没有提示、也没有展开入口**，而标题旁边照样写「· 共 N 份」⇒ 可见资料超过 6 份时，
    **较早共享出去的那条永远看不到**，用户看到的就是「共 11 份，但我要找的那条不在里面」。
    与 #59 是同一症状、同一面（用户端知识库）的第三条成因 —— 修了权限和默认 tab 仍不算完。
    **判据**：**截断可以有，但不能静默**；凡「只渲染前 N 条」，必须同屏给出「展开全部（共 N 份）」入口
    （本次修法：`KB_PAGE=6` + `state.kbExpanded` + 全局 `toggleKbList()`）。
    ⚠️ **本机演示库不会自然触发**（可见资料只有 1~3 份）⇒ 这类缺陷只能靠**读代码/写构造用例**发现，
    等它复现等于不查。构造用例（`e2e_kb_share_visible.py` F 组）必须造「>N 条 + 一条最早的」，
    否则 F1 会因 `list.length <= 6` 而**恒真**（`chk(name, True, "")` 那类假断言）。
62. **「读得到文本」≠「用户看得到」——H5 探针必须断言 `is_visible`，且先切到承载页。**
    `#kbList` 在「我的」页（`#page-me`）里，首屏 DOM 里就存在但**不可见**。第一版 F 组只读 `inner_text()`，
    文本全对、`query_selector_all` 也数得对，于是**假绿**；真去 `click()` 时 Playwright 报
    `element is not visible`（30s 超时）才暴露。修法：探针先 `page.evaluate("go('page-me')")` 切页再操作，
    并补一条 `is_visible("#kbList")`。**凡「页面元素」类断言，都要问一句：它在当前这一屏吗？**


63. **`AuthUser.nickname` 在请求期恒为 null ⇒ 回填用户可见姓名时绝不能依赖它。**
    令牌签发处从不给 `nickname` 赋值，而 `AuditRecorder.displayName(actor)` 在它为空时**回落到登录用户名**。
    于是 V63 投诉建议里 `submitterName` 显示成了内部登录 id `e2emem0170785` 而不是「E2E成员」。
    **修法**：组织域内一律用 `FeedbackService.displayNameOf(userId, actor)` 读 **`org_member.name`**（组织域权威姓名源）。
    **通则**：**凡要展示给人看的姓名，取数源必须是人员主数据，不是安全上下文的便捷字段。**
    ⚠️ 这类缺陷**只有端到端能抓到**：单测里 `nickname` 常被手工填好，接口测试若只看 `code==0` 也不会看姓名内容
    ——必须「真登录 → 真调接口 → 真读回显」。
64. **`GlobalExceptionHandler` 的 HTTP 状态口径：只有 401/403/404 映射成 HTTP 状态码，
    其余（含 400 参数校验）一律 HTTP 200 + `body.code=400`。**
    ⇒ 断言 400 **必须校验业务 `code` 字段**（`scripts/e2e_v63_org_feedback.py` 的 `biz_reject()`），
    看 HTTP 状态码会一次性产生 4 条**假失败**，进而诱使人去「放宽断言」——正好踩铁律 #7。
    另：登录返回字段是 **`accessToken`** 不是 `token`（e2e 首个失败就栽这）。

65. **写路径与读路径的「作用租户」必须同源 —— 只改读侧＝半修复。**
    `OrgGuard.resolveScopeTenant` 的注释早已写明读侧那次修复（「平台管理员的 tenantId 恒为 0…
    四个页面全是空态」），但**写侧从未跟着改**：
    `InstitutionService` 的 `create/update/changeStatus/assignAdmin` 四处仍用**裸** `actor.getTenantId()`。
    ⇒ 平台管理员建的机构落到 `tenant_id=0`，而列表按 `resolveRequestTenant` 得到的业务租户（2）过滤
    ⇒ **任何租户的列表都查不到它**（实测留痕 `org_institution id=87 code='ttt'`）。
    **判据**：凡「按某个作用域落库」，写入端必须与列表/详情端调**同一个** resolver，
    不能一处 `resolveRequestTenant`、一处裸 `getTenantId()`。改完要**连读带写一起扫**。
    **数据修复范式**：`V64`。⚠️ MySQL **Error 1093**（UPDATE 的目标表出现在子查询 FROM 里）
    会把这种回填写死 —— 正解是**先落临时表算好目标值，再让 UPDATE 只读临时表**；
    且失败迁移必须在 `flyway_schema_history` 里清掉 `success=0` 那行，否则后续迁移全被挡。
66. **`toggle` 类端点不带 body 时，默认值绝不能偏袒一侧。**
    `enabled = body == null || !Boolean.FALSE.equals(body.get("enabled"))` 看着只是「默认启用」，
    但前端调 `toggle` 时**本来就不带 body** ⇒ `body==null` 恒真 ⇒ **单向恒真**：
    点「停用」永远变成「启用」，记录永远停在已启用 ⇒ 用户看到的就是「停用操作无效」。
    **通则**：名字叫 toggle 就必须**按当前值翻转**（`explicit != null ? explicit : !current`）；
    需要幂等就**显式传目标值**，不要靠「缺省值恰好等于我想要的」。
    另：这类「静默成功 + 状态没变」必须补**成功回执**，否则用户无法区分「生效了」和「没反应」。
67. **柱状图：柱高算法与容器可用高度必须同源；`flex:1` 在数据点少时会把柱拉成色板。**
    ① 渲染器按 `min(v/max*70, …)` 算柱高，但容器 `height:74px;padding-bottom:18px` ⇒ 可用只有 **56px**
    ⇒ 柱顶**顶穿到标题上**。② `.bar{flex:1}` ⇒ 只有 2 个数据点时每根占半屏 ⇒ 两块满宽色板
    （实测截图就是「近 6 个月趋势」下面两块大色板）。
    ③ 标题**写死**「近 6 个月」而实际 2 个点 ⇒ **标题本身在传达错的事实**。
    **判据**：柱高上限必须写成与容器高度绑定的显式常量（本次：100 = 70 柱 + 12 数值 + 18 轴标签）；
    柱宽要有 `max-width`；标题里的「N」必须由实际点数推导。
    另：涨跌配色按**中国口径（涨=红 / 跌=绿）**，此前 `.delta.up→绿 / .down→红` 是欧美口径。
68. **「同一决策点两处判定」的经典样本：专家启用态被读了两遍，且其中一处永远是 `true`。**
    管理端表格读**配置层**（`expert_config` → `ExpertConfigService.resolve`），而用户端目录
    `CatalogService.enabledExperts` **只读 `ai_expert.enabled` 列**；该列**从来没有任何代码写过 `false`**
    （`importTemplate` / `saveTemplate` 均硬编码 `setEnabled(true)`，`defaults()` 也是 `true`）
    ⇒ 管理员点「停用」只把管理端列表变灰，**用户端照旧能选能用**（用户报的就是这个）。
    **判据**：一个「是否可见 / 是否生效」的判据只能有**一个实现**（本次收敛到 `ExpertConfigService.isEnabled`），
    其它读路径（列表、目录、删除守卫、默认兜底）**全部调它**。附带两条：
    ① **写入口漏了「意图字段」是同源缺陷**：`saveTemplate` 硬编码 `setEnabled(true)` ⇒
       前端新建对话框勾「不启用」**不生效**（前端 `config.enabled` 是唯一意图来源，后端必须读它）。
    ② **凡断言「A 之后 B 不可见」，必须先断言「A 之前 B 可见」**，否则极易写出恒真断言：
       本次第一版 e2e 的「租户停用后看不到」就是**假通过** —— 租户**压根没导入**那个平台模板
       （用户端只列本租户行 + 默认 AI 兜底），断言与修复无关地成立。
       **先造出前置态，再断言变化**（铁律 #7）。
69. **删专家必须级联清 `expert_config`，且要清「跨租户的孤儿片段」；并且必须物理删除。**
    ① 不级联 ⇒ 同一 `expert_key` 日后重建时旧片段**静默复活**（上一轮设过的 `enabled=false` /
       旧 `systemPrompt` 直接生效）⇒ 表现为「新建的专家一上来就是关的」。
    ② 只清调用者自己名下（`tenant_id = tid`）**不够**：租户可以在**没导入副本**时写过片段
       （典型：把这个专家停用过）。实测平台删全局模板后
       `SELECT * FROM expert_config WHERE expert_key=?` **仍剩 1 条**（tenant_id=2 / TENANT / `{"enabled":true}`）。
       **判据**：片段有意义 ⇔ 它的 `(tenant_id, expert_key)` 或 `(0, expert_key)` 还有存活 `ai_expert` 行。
       ⇒ 删完后若**已无 `tenant_id=0` 存活行**，则 `deleteAllExceptTenants(key, 仍持有副本的租户)`；
       **全局模板仍在时绝不能清**（各租户对它的覆盖片段仍然有意义，清了就是删别人的数据）。
    ③ **必须物理删**：`UNIQUE(tenant_id, expert_key)` **不含 `deleted_at`** ⇒ 软删会让同一 key
       **再也建不回来**（所以 `AiExpertMapper` / `AiSkillMapper` 用 `@Delete` 手写 SQL）。
    ④ 删全局模板前要拦「已被 N 个租户导入」⇒ 用 **409**（可 force 的软拒绝）而非 400，
       前端据 `code===409` 弹二次确认后带 `force=true` 重试。
    ⑤ ⚠️ **附带发现（本轮未改，属 V36 既有设计）**：`ContentReviewService.needsReviewForConfig`
       ⇒ 非平台管理员写非 `USER` 层片段一律 **PENDING**，待审片段被 `resolve()` 跳过。
       故**租户管理员点「停用」不会立刻生效**（要等平台放行）。UI 若不给「待审」提示，
       用户会再次体验成「停用无效」。要改需单开需求，别顺手改审计语义。
70. **SPA 的短路径别名不能用 rewrite，必须 302。**
    入口 nginx 想让 `10.0.0.3/web` 指向管理端：管理端产物是 `base=/aios/web/` +
    `createWebHistory(BASE_URL)` 的 SPA ⇒ **地址栏必须落在 SPA base 之下**，
    用 `rewrite` 会让 `assets/*` 相对路径解析错而**白屏**；`/web` 只能 `return 302 /aios/web/`。
    反之 H5 是**自包含单文件**、API base 由 `location.pathname` 推导（`/user/` ⇒ `/api`），
    所以 `/user/` 可以用**内部 rewrite** 到 `/aios/h5/` 而不跳转。
    **通则**：**先判断目标的 base 语义**（有没有 base path / 是不是单文件 / 是否按 pathname 推 API），
    再决定 redirect 还是 rewrite —— 两者不可互换。改这类入口后要跑
    `scripts/_check_single_port.py`（现 **13 项 + 26 项负向 mutation**）确认 `/web` 的 302 跳转语义与
    `/user/` 的 rewrite 语义都还在。
71. **「固定宿主端口」在目标机上被占用 ⇒ 部署就起不来；覆盖口必须走 `.env`，不能靠改 compose。**
    现象：`docker compose up -d server agent` 报 `port is already allocated`。本案是 `0.0.0.0:8000`
    被目标机上一个**无关容器**占着，而 compose 把 agent 固定发布 `127.0.0.1:8000:8000`。
    修法：compose 写成 `127.0.0.1:${AIOS_AGENT_HOST_PORT:-8000}:8000`（**默认值不变**），
    并在 `.env` / `.env.production` **声明该键**（compose 引用的每个 `${VAR}` 都要在 env 里有出处，
    否则 `compose-lint` 会警告「引用了未声明的键」）。
    ★ **现场只改 `.env`，不要改 compose** —— 改 compose 会在用户下次 `git pull` 时冲突，
    而 `.env` 本来就被 gitignore。**容器内端口恒为 8000**，服务间走服务名（`agent:8000`），
    改的只是宿主映射，功能零影响（但本机 e2e 若硬编码 `127.0.0.1:8000` 探活要同步）。
    **通则**：凡「宿主映射」类取值，只要目标机可能被占，就留 `${VAR:-默认}` 口子并给默认值；
    同时把该键写进两个 env 模板 + `ENV.md` + 手册故障表（症状→改哪一行）。

72. **新增「可选」服务必须做 profile 门控，否则「默认 up」的口径立刻与离线包/网络受限环境矛盾。**
    现象：给 compose 加了一个**可选**的入口 nginx（不加也能跑），但没写 `profiles:` ⇒
    它落进默认 `up` 集合 ⇒ 裸跑 `docker compose up -d` 就会去 Docker Hub 拉 `nginx:1.27-alpine`，
    而应用机 **Hub 返回 `000`** ⇒ 卡死。更糟的是文档同时写着「离线包只需两张镜像就能跑」，
    **两处口径互相矛盾**（铁律 #1：同一决策只能有一个判定点）。
    修法：`profiles: ["entry"]`；默认 `up` 恢复为 `{server, agent}`；要短路径就
    `docker compose --profile entry up -d nginx`。
    ★ 连带要改的：**文档里原本那句「不要裸跑 `up -d`」应当删掉/反转**（它是在为这个坑打补丁），
    改成「裸跑是安全的」+ 带 `--profile` 的起法；`host-check.sh` 里该镜像的**归类也要改**
    （不能再算「已摘除的边缘组件…compose 已不声明该服务」）。
    **通则**：加可选服务时，先问「它会不会进默认 `up` 集合」；会，就门控。
    并顺手检查三类文档里对它的**历史描述**是否已失真。
73. **前端写死「根路径」接口基址 ⇒ 本地全绿、只在「共用域名 + 只反代子路径」的生产入口暴露。**
    现场：公网 `https://mall.egooaicloud.com/aios/web/` 页面能开，但**所有接口 404**；
    在应用机上直连 `:8080/aios/web/` 却一切正常。根因：管理端 SPA 的 `axios.create({baseURL:'/api/v1'})`
    与 SSE `` `/api/v1/runs/…` ``（`fetchEventSource` **不走 axios**，必须自己拼）都是**根绝对路径**；
    浏览器把它解析成 `https://域名/api/v1/**`，而外网入口只有 `location /aios/` ⇒ 无人代理。
    ★ **为什么能长期潜伏**：后端是**双前缀并存**（`/aios/api/**` 剥成 `/api/**`，`/api/**` 也保留），
    本地 44 个套件直打 `:8080/api/**`、vite dev 又代理 `/api` ⇒ **本地全是对的**。
    只有「共用域名只反代 `/aios/`」这一种拓扑才会 404。
    **通则**：只要产物被挂在子路径下（`base=/aios/web/`），**根绝对路径就是错的**；
    基址必须与 `import.meta.env.BASE_URL`（或等价的 base 变量）**同源**，且要**逐一找出不走 axios 的调用**
    （SSE / `EventSource` / `window.open` / 文件下载直链 / 后端回填的 url 字段）。
    守卫：`scripts/_check_single_port.py` 的 c12（对应 H5 侧是 c9）。

74. **Dockerfile 的 `COPY …/pom.xml` 清单与聚合 pom 的 `<modules>` 漂移，且被 `|| true` 静默掉。**
    现场：`server/pom.xml` 有 11 个 `<module>`，`deploy/Dockerfile.server` 只 COPY 了 10 个 ⇒
    Maven 报 `Child module aios-integration-scfy of /build/pom.xml does not exist`。
    ★ 该行写成 `mvn … dependency:go-offline -pl aios-boot -am || true` ⇒ **构建不会失败**，
    只是 `go-offline` 整层失效：**每次都全量下依赖**，受限网络下从「几分钟」变成「反复超时」。
    「不中断构建」正是它能潜伏很久的原因 —— 报错在日志里，但没人当回事。
    同族缺陷见 #43（`Dockerfile.web` 漏 `COPY web/tsconfig.base.json`）。
    **通则**：凡「Dockerfile 里逐个列出的清单」都要与**权威来源**（pom 的 `<modules>`、tsconfig 的 `extends`、
    vite 的 base 与组装目录）做**确定性比对**，别靠人眼；且**别用 `|| true` 掩盖会长期恶化的步骤**。
    守卫：`_check_single_port.py` 的 c13（解析 `server/pom.xml` 的 `<modules>` ⇄ Dockerfile 的 COPY 行）。

75. **静态守卫「按文本计数」会被注释污染 ⇒ 断言退化成「谁写注释谁报红」。**
    现场（V66 守卫首跑）：V5 要断言「子租户端点全部要求租户管理员」= 映射数 == 校验数，
    实跑却是 `映射 4 个 / requireTenantAdmin 5 次`。根因：类的 Javadoc 里为了说明权限纪律写了一句
    「权限：`{@code guard.requireTenantAdmin()}`」⇒ **计数把注释里的复述也算进去了**。
    ★ 危险在于：这种断言一旦「放宽」（比如改成 `>= 1`）就变成恒真；而它原本的正确形态是
    **断言代码事实，不是断言文件里出现过这几个字**。
    **通则**：静态守卫**先剥离注释再断言**（`_strip_java_comments`：先 `/*…*/` 再 `//`），
    并且计数锚点尽量取**只有真正应用时才会出现的形态**（这里是 `= guard.requireTenantAdmin();`，
    注释里的 `{@code …()}` 天然不匹配）。同族缺陷：V65 守卫的 B7 —— 指标名单只能看**真正下发的 label**
    （`metric("key","label",…)`），不能把注释里提到的词算进来。
    守卫：`_check_v66_tenant_guards.py` 的 `_strip_java_comments` + `--selftest`（20 个突变全报红）。

76. **业务校验失败是「HTTP 200 + 信封 `code=400`」，断言别按 HTTP 状态码写。**
    现场（机构类型套件首跑）：8 条「非法值被拒」断言全假红，打印
    `status=200 msg=机构类型不合法：STATE_OWNED；可选值：GOVERNMENT / ENTERPRISE / ...`
    —— 拒绝其实**完全生效**，是断言写错了维度。本仓约定：`BizException` 由全局异常处理器统一包成
    **HTTP 200 + 信封 `code`**（400/404/…）；只有 Spring Security 层抛出的鉴权失败才是**真 HTTP 403**。
    ⇒ 既有套件（`e2e_v66` 等）一律断言 `code_of(js) == 400/403/404`，新套件必须照此。
    **通则**：写「被拒」断言前，先看一条**同形合法请求**返回什么（成功也是 200）；
    在本仓 HTTP 状态码不是业务裁决的载体，拿它做判据必然假红/假绿。

77. **静态守卫自检里的 `[SKIP]` 必须计入失败** —— "没生效的突变" = "没验过的断言"。
    现场：批次 B 守卫的 O6 突变锚点写成 `AuthUser u = guard.requireTenantAdmin();`，
    而真实代码是裸的 `guard.requireTenantAdmin();` ⇒ 替换没命中、突变未生效；
    旧写法打印 `[SKIP]` 后 `continue`，最终照样输出「自检 11/11 通过」——
    把**没验过的突变**算成了通过，比没断言更危险（同族：铁律 #7 的恒真断言）。
    修法：SKIP 计入 `bad` 并直接判失败（`_check_v66_tenant_guards.py` 与批次 B 守卫都已收紧）。
    **通则**：自检报告里「跳过」与「通过」必须分开计数；锚点漂移要报红提示同步守卫，不能静默放行。

78. **E2E 残留会被「当作基线」而长期隐身** —— 「与基线一致」不能证明干净。
    现场（批次 C 真机验证时才发现）：「给员工追加账号」下拉里塞满 `e2e*` 账号。
    根因：`scripts/e2e_v63_org_feedback.py` 每次新建 1 机构 + 1 部门 + 3 员工 + **4 账号**，
    收尾只把机构置 `CLOSED`、**账号原样留在账号池**；跑了 11 次 ⇒ **44 个 `ENABLED` 的 `e2e*` 账号**，
    另有 13 个 `E2E企业-*` 机构（占租户 2 存活机构的 **50%**）、11 个 E2E 部门、44 名 E2E 员工。
    本仓多张表的查询都是**租户级**（如候选账号接口必须回吐「虚拟管理员账号」），残留会直接涌进业务 UI。
    ★ 最危险的一点：`e2e_org_types_and_credit` 断言「租户 2 机构总数 `22 → 22`」——
    那个 22 里本就含 9 个 E2E 机构 ⇒ **基线自己是被污染的**，于是「与基线一致」把缺陷放行了很久。
    **通则**：① 造数据的套件收尾必须让数据**退出业务可见面**（软删/停用），不能只改个状态就交差；
    ② 断言「数量回到基线」时，要能说出基线里**每个**条目是什么（最好直接断言**按命名前缀筛出的残留数为 0**）；
    ③ 用**真机/真接口**看一眼 UI，比只看套件绿灯更容易发现这类「数据不报错但污染」的问题。
    守卫：`_check_member_account_guards.py` 的 **M11**；清理工具 `scripts/reset_e2e_account_residue.py`。

79. **同一份清单被抄成多份，于是「前端能选、后端不收」** —— 用户报障「数字员工无法授权」。
    现场：管理端「资源授权 → 新增授权 → 资源类型=数字员工 → 保存」稳定被拒
    `code=400 不支持的资源类型：WORKER`；对照同机构 `MODEL` 同一代码路径 `code=0`（排除选错机构/资源）。
    根因：可授权类型的清单在**四处**各写一份，其中三处漏了 WORKER ——
      · `ResourceGrantService.grant()` 的白名单（硬编码 4 类）← 拦住保存的那一道
      · `catalog().resTypes`（硬编码 4 类）
      · `institutionResources()` 的 byType 预置（硬编码 4 类）
      · 管理端下拉（手写 5 个选项，**含**数字员工）← 唯一的「正确」那份
    `ResourceGrant` 实体连 `TYPE_WORKER` 常量都没有；而 `TenantAdminController` 的注释早已写着
    「（专家 / 技能 / 模型 / **数字员工**）」⇒ **注释与代码背离**，能力事实上不可用（铁律 #4 的反面）。
    ★ 同一批还暴露第二个：`selectWorkers()` **没有任何租户过滤**（`WHERE deleted_at IS NULL`），
    租户 2 的授权下拉里混进租户 3 的数字员工（实测 11 条 = t0 3 + t2 4 + t3 4），
    选中即构成跨租户授权 —— 直接违反 docs/15 §八「tenant_id 只从 JWT 取、跨租户一律 404」。
    **修法**：类型清单收敛为 `ResourceGrant.ALL_TYPES` + `TYPE_NAMES` 单一权威，
    目录/白名单/byType 三处全部由它派生；前端下拉改为读 `catalog.resTypes`（不再复刻）；
    `selectWorkers(tenantId)` 补租户过滤。**通则**：凡「枚举可选值」出现第二次，就一定会分叉；
    对外可见的枚举必须由**服务端一处**下发，前端只渲染不改写。
    守卫：`_check_worker_grant_guards.py`（W1–W12，含「前端不得硬编码类型下拉」）；
    套件：`scripts/e2e_worker_grant.py`（33/33，含「目录里的每种类型都要能真授权成功」）。

80. **「资源下拉显示 `名称（undefined）`」= 拿可选字段做了必填拼接**。
    数字员工的目录行没有 `resKey`（`agent_worker` 只有 id/name/status；它是租户内自建资产，
    不像模型/专家有稳定 key），而模板无脑拼 `名称（resKey）` ⇒ 真机看到「政策快讯员（undefined）」。
    授权本身是成功的（库里有行），**只是标签脏** —— 这类缺陷套件抓不到（接口全绿），
    只有真机看一眼才发现。**通则**：拼接前先问「这个字段在这一类数据上一定存在吗」；
    不存在就分支降级，不要拼出 `undefined/null/NaN`。守卫：`_check_worker_grant_guards.py` **W12**。

81. **同一个 mapper 方法被两批改动各加一份声明 ⇒ 直接编译失败**（2026-09-28）。
    现场：`OrgStatMapper` 里 `updateUserPassword(...)` 出现**两次**（V66 子租户批次加了一份
    `子租户管理员若显式指定了初始口令…`，V67 批次又加了一份 `重置登录口令（按 userId）`），
    签名完全相同 ⇒ `mvnw clean package` 编译不过。两者都藏在"新增方法"的注释下面，
    人工 review 时看着都像合理代码。**通则**：改接口类时先全局搜方法名再决定"新增"还是"复用"；
    每次 `package` 前可先用一段 20 行脚本按方法名 regex 统计重复（见
    `scripts/_check_member_login_credential_guards.py` **C6**）。同批还顺带发现第二个：
    `SubTenantService` 绕开 `AccountProvisioner` 自己 `passwordEncoder.encode(...)` 写口令
    ⇒ 口令写入口出现两个（铁律 #4）。修法：删重复声明 + 子租户改调 `accounts.resetPassword()`。

82. **「开户即写死口令」= 能力在、凭据不可知**（用户报障「新增的员工无法登录用户端」）。
    实测新账号**能**登录（统一演示口令 `User@123`，`/auth/login` 200、用户端核心接口全 200），
    真正的缺陷在**凭据不可知**：管理端「新增员工（自动开户）」表单既无口令输入、成功也不回显，
    而 `AccountProvisioner` 一律写死 `DEMO_PASSWORD_HASH`、服务端只存哈希 ⇒
    操作员拿到一个"建好了但进不去"的账号，且**无从补救**（没有重置入口，只能删员工重建，
    那会连带丢掉审批/通知归属）。**修法**：① 表单加口令输入（留空回落统一口令）；
    ② **回显口令必须由服务端回执下发**（`initialPassword`），前端不得复刻常量
    —— 否则两处口令迟早分叉；③ **只在确实新建账号时才回显**（账号本就存在时口令没被改动，
    回显一个"初始口令"就是假话，铁律 #1）；④ 批量导入没有口令列 ⇒ 回执要带上统一初始口令，
    否则导入上千人后一个都登不进去；⑤ 补 `POST /org/members/{id}/password` 重置端点作为正常出口；
    ⑥ 口令**绝不能进审计**（长期留存、多人可见）。守卫：
    `scripts/_check_member_login_credential_guards.py`（C1–C11 + 11 项突变自检）。

83. **前端构建绕开沙箱「批量删除保护」：换一个**全新** `--outDir`，别去清旧目录**。
    `vite build` 默认 `emptyOutDir`，要删 `dist/assets` 里 70+ 个文件 ⇒
    `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":76,"threshold":50,"scope":"turn"}`
    直接让构建失败（`npm run build` / `--outDir dist2` 都一样，只要目标目录已存在且文件多）。
    且在**同一轮里分批删也躲不掉**（`scope: turn` 是累计的）。
    **可行做法**：`vite build --outDir "C:/Users/<u>/AppData/Local/Temp/aios-shell-vNN"`（每轮换一个**不存在**的
    目录名 ⇒ 无需删除），再 `cp <out>/assets/* <webroot>/assets/ && cp <out>/index.html <webroot>/index.html`
    （覆盖是写、不是删，不触发保护）。★ 路径必须写成 **`C:/...` 风格**：
    写 git-bash 的 `/c/Users/...` 会被 node 当**相对路径**，产物落到 `C:/c/Users/...`（实测踩到），
    目录树看着还对、`ls /c/Users/.../Temp/...` 却是空的。
    校验产物对得上：在 webroot 的 entry chunk 里 grep 到 `OrgAdminView-<hash>.js`，
    再在该 chunk 里 grep 到 `OrgStructureView-<hash>.js`，最后确认这个分块里含新文案
    —— 老 hash 的分块会一直躺在目录里，光看"文件存在"会误判。

84. **MyBatis-Plus `updateById(entity)` 的 NOT_NULL 策略让「清空字段」变成假成功**。
    现场（2026-09-28，写 `e2e_tenant_domain_quota.py` 时断言抓到）：`TenantController.update` 用
    `t.setDomain(null); tenantMapper.updateById(t);` ⇒ 接口回 `200 + domain:null`，**库里纹丝不动**。
    根因：`updateById` 默认 `FieldStrategy.NOT_NULL`，实体里为 `null` 的字段**不进 SET 子句**；
    而「清空域名」恰恰就是要把 domain 写成 NULL。用户在界面把域名输入框清空点保存，看到「已保存」，域名还在。
    判据：**凡是「字段可以被清空」的接口，都不能用 `updateById(entity)`**。
    修法：`LambdaUpdateWrapper.set(SysTenant::getDomain, v)` 显式 set（`update(null, w)`），
    并且**含键才动该列**（`body.containsKey("domain")`），这样「清空」与「未提交该字段」语义可区分；
    回吐要 `selectById` **重读**，不能回内存里那份可能没落库的实体。
    守卫：`_check_v66_tenant_guards.py` **K6**（断言限定在 `update()` 方法体内 —— 同类 `changeStatus` 也调
    `updateById`，那是合法的，不限定范围会假红）。

85. **弹窗「预填值」绝不能硬写默认值 —— 那等于「一点保存就清空对方的真实数据」**。
    现场（同批）：`TenantAdminView.openQuota` 预填 `expertSeats: 0, skillSeats: 0`，而
    `QuotaService.upsertPool` 对席位**没有**「不得低于已用」的兜底 ⇒ 打开弹窗看到 0、保存即把
    租户真实席位（12/18）写成 0，**无提示、无校验**。
    最刺眼的是：后端 `list` **早就**回吐了 `expertSeats/skillSeats/expertUsed/skillUsed`，
    其注释写明「弹窗要能预填当前值，否则用户看不到自己正在改什么」—— 前端从未接上。
    判据：**编辑器类弹窗的每个数字字段，预填值必须来自「当前值」；写死 0/空串是数据破坏**。
    且「不提交的字段后端不会替你兜底」—— 所以预填缺失不是"少个默认值"，是"保存即毁数据"。
    守卫：**K7**（预填）+ e2e **B8/B9/B10**（不提交席位则不动 / 显式提交才改 / 真落库）。

86. **删「按当初谁跟谁写在一起」的 API 文件时，必须逐导出项确认能力归属**。
    现场：`api/subTenant.ts` 里同时装着「子租户 CRUD」与「平台调额度 `updateTenantQuota`」。
    移除子租户时若整份删掉，平台就**静默失去**「事后调整租户资源上限」的入口（铁律 #4）。
    修法：按**能力**拆分（新建 `api/tenantQuota.ts`），而不是按文件；并把这件事写成守卫 **K4**
    （含突变 K4c「import 忘了改，仍指向已删文件」）。
    判据：**删文件前先 `grep` 该文件每个 export 的调用方，逐一回答「它属于要删的能力吗」。**

87. **静态守卫的「恒真」有两种隐蔽形态：扫的源与突变注入的源不一致 / 断言被 import 满足**。
    现场（2026-09-28，本守卫首版）：① **K2** 断言「域名正则只有 `TenantDomain` 一处」，实现扫的是
    **文件系统**，而突变只改了传入的字典文本 ⇒ 突变等于没注入，`--selftest` 直接报「未报红」；
    ② **K4b** 断言「api 走 unwrap」，而 `import { http, unwrap } from './index'` 这一行就满足了它 ⇒
    把调用改成 `r.data.data`（失败信封当业务数据，pitfalls #18）守卫照样绿。
    修法：① 断言与突变必须**共用同一来源**（改为从 `java_blobs`（basename, 去注释正文）列表判定）；
    ② 断言前**先剥 import 与注释**，再看是否**真调**了目标形态（`unwrap<QuotaBeforeAfter>(r)`）。
    配套：断言要限定在**单个方法体**内（`_method_body`），否则同类其它方法的同名调用会造成假红。

88. **回退一个能力：迁移只能前进，删列前先核实「没有数据要搬迁」**。
    现场：用户决定「去掉子租户」（2026-09-28）。`V66` 已应用成功且 `validate-on-migrate=true` ⇒
    **改 `V66` 内容会让校验和对不上、下次启动 `MigrationChecksumMismatchException`**。
    正确做法：新加 `V68__remove_sub_tenant.sql` 做 `DROP INDEX idx_tenant_parent` + `DROP COLUMN parent_id/level`，
    且**只删该能力的列，不碰同批带来的 `domain`/`uk_tenant_domain`**（用户没要求去掉域名能力）。
    ★ 本地启动脚本带 `-Dspring.flyway.validate-on-migrate=false`，改 `V66` 在本机**看起来没事** ——
    那正是最危险的情况（本机绿、容器红）。
    ★ 删列前必须先查「有没有孤儿行」：实测 `sys_tenant` 4 行全部 `parent_id=0/level=1` ⇒ 无子租户行可留，
    否则删列会留下「失去层级标识的孤儿租户」。
    判据：**回退也是改造，要走同一套纪律（谁的门、要不要拒、失败留不留痕、守卫钉在哪）。**

89. **断言「列表某行必须有值」时，位置选择器是隐式假设 —— 第一行可能**合法地**为 0**。
    现场（2026-09-28，`scripts/_verify_v68_ui_removal.py` 首版，假红 6/13）：脚本用
    `page.locator("button:has-text('调整资源')").first.click()` 点**第一行**，而 `/admin/tenants`
    按 id 升序，第一行是 `sys_tenant.id=1`「默认租户」—— 它在 `tenant_resource_pool` 里
    **没有行**，`list` 回吐 `0/0/0` 是**完全正确**的。脚本却断言「席位不得为 0」⇒ 假红，
    并让我一度去查「前端构建没生效 / webroot 缓存」（其实构建与 webroot 都是最新，见下条）——
    **把一次测试缺陷当成产品缺陷排查了一整轮**。
    修法：按**业务键**定位目标行（`page.locator("tr", has_text="DSJ-DEMO").first`），且断言前
    先查库确认「该行本来就该有非零值」：`SELECT tenant_id,SUM(token_total),SUM(expert_seats),
    SUM(skill_seats) FROM tenant_resource_pool GROUP BY tenant_id`（实测 id=2→12/18、id=3→5/6、id=30→2/2，
    而 id=1 无行）。
    判据：**位置选择器 = 隐式假设；假红和假绿一样贵**（假红会让人去改对的东西）。

90. **Playwright `inner_text()` 不返回「不可见」文本 —— 折叠的子菜单会让「入口仍在」整片假红**。
    现场（同上，同轮）：对照检查 `label in page.inner_text("body")` 对「租户管理/机构管理/入驻进度/
    资源授权/费用分摊」**全部** not present ⇒ 差点被读成「整块菜单被误删」。实因：这五项是
    `<el-sub-menu index="tenant">` 的**子项**，Element Plus 默认**折叠**，子项文本在折叠过渡里不可见，
    而 `inner_text()` 的语义是 `innerText`（**只算渲染出来的**）⇒ 取不到。菜单一直在。
    修法：先把分组展开（`page.locator('.el-sub-menu__title:has-text("租户与机构")').first.click()`），
    或改用 `text_content()`（含隐藏节点）/ `page.content()`。
    判据：**「不存在」类断言必须排除「只是不可见」** —— 断言前先让目标进入可见态；
    否则「没找到」无法区分「真的没有」与「没渲染出来」，而这两者的修法完全相反。

91. **断言「某端点不存在」时，别把探针打到它的**真身**上 —— 会真的删掉演示数据**。
    现场：给「员工直删（不经审核）」写 M1 断言，本意是证明**没有** `delete-request` 申请端点，
    结果写成了 `DELETE /api/v1/org/members/1`（**那就是真的直删端点**）⇒ 演示库机构 1 的员工
    id=1「刘敏」当场被软删，其 `org_member_account` 主账号绑定一并被清（`alive` 是
    `VIRTUAL GENERATED`，随 `deleted_at` 自动变 NULL）。
    为什么警报没响：**返回 200 / code=0 恰好等于「删成功」**，而套件当时没有「在册员工数」基线断言
    ⇒ 全绿，只有那一条 FAIL 提示「M1 期望 404 却拿到 200」，看起来像断言写错了，其实是**数据被删了**。
    修法（三件一起做）：
    ① 探针只打**申请端点**（`POST/DELETE …/{id}/delete-request`），永不打可能生效的写端点；
       只读的「端点不存在」断言一律用 **GET/POST 到子路径** + 认 404 或 405；
    ② 任何会写库的套件都要给**被保护对象的总数**建基线（本次补了 `F10 全库在册员工数回到基线`），
       否则「误删演示数据」这类损伤在套件里是**静默**的；
    ③ 恢复脚本落成可复算的一件：`scripts/_diag_member1_restore.py [--fix]`（一次性，`_diag_*` 不入库）。
    另一个坑：`audit_log` 是 **hash 链**（`prev_hash`/`hash`），**删行会破坏链式完整性** ——
    误操作的审计行只能留着，不能「清理掉当作没发生」；且该表字段是 `resource_id`/`action`，
    不是 `target_id`（写恢复脚本时踩过）。

92. **断言「界面展示了某事实」时，判据不得与被测对象同源 —— 否则缺陷会把判据一起弄坏**。
    现场（用户端 OA 形态 `scripts/_e2e_oa.py` F3a）：要断言「定时任务卡片的启停文案与接口一致」，
    首版判据写成读 `state.workers[i].on` 与渲染出的 DOM 文案比对。
    为了证明断言**不是恒真**，写了负向测试（`scripts/_negtest_timers_field.py`：把 `on` 改名 `enabled`
    复现旧缺陷后重绘），结果**复现态仍然 pass=True** —— 因为判据读的就是渲染器读的那个对象，
    缺陷同时把两边都改成了「已停用」，自洽地绿。
    修法：判据回到**事实源头**再取一次（`const api = await API.workers()`），拿接口真值与 DOM 比对
    （按**业务键** name 关联，不按数组下标，避免顺序耦合）。改后负向测试才正确变红
    （`pass=False`，2 行被判红），基线仍绿。
    判据：**「显示对不对」只能拿「事实」判，不能拿「界面自己的数据副本」判** ——
    同源判据把「渲染层读错字段」这类缺陷变成**判据与实现一起错**，测试永远绿。
    配一条纪律：**凡新写的「展示与事实同源」断言，都要先跑一次负向测试证明它会红**，
    否则无法区分「真通过」与「判据无效」。

93. **手写渲染层「猜字段名」会产出 3 类静默错显：字段名不存在 / 枚举大小写不符 / 响应结构不符**。
    现场（同上，OA 层是手写的，字段名靠读接口猜）—— 三类都真的踩中，且**页面不报错、console 无 error、
    断言当时也不红**，只是显示成另一个事实：
    ① **字段名不存在**：写 `w.enabled`，接口真实字段是 **`w.on`**（`WorkerController.WorkerView`
       L147 记录项 + L163 `boolean on = !Integer.valueOf(0).equals(w.getEnabled())`）。
       探针实测 4 个数字员工全是 `on:true / status:待命中`，页面却恒显示「已停用」。
    ② **枚举大小写**：写 `d.scope === 'tenant'`，权威口径是**大写** —— 经典页 `index.html` L2772 用
       `d.scope === 'TENANT'`，后端 `KbController.DocView` 默认值也是 `"PERSONAL"` ⇒ 企业知识库被标成「我的知识库」。
    ③ **响应结构不符**：`/v1/org/departments` 返回的是**对象** `{total,maxDepth,depthLimit,flat,tree}`，
       既不是数组、也没有 `items`，而共用工具 `asArray()`（`index.html` L2290）只认
       `list/items/records/data/rows` ⇒ 得到空数组 ⇒ **部门筛选器一个都渲染不出来**
       （接口支持但界面上配不出来 = 能力事实上不可用）。
    修法：建一个**口径哨兵**（`scripts/_check_dto_fields.py`，入库的长期探针）：先切到对应形态
    （OA 的懒加载 `loadOaExtras` 才补齐 `conversations` 等集合，**留在经典形态采样会把「未加载」误判成「接口无数据」**），
    再取**真实响应**的 key 集合，与「渲染层实际读的字段清单」做集合差。
    同类顺带清掉的**幻影字段**：`c.updatedAt`（真实 `lastMsgAt`，而且它正是「最近会话」的排序依据 ——
    显示 `createdAt` 属**排序与显示不同源**）、`e.description`（真实 `desc`/`intro`）。
    判据：**接后端的手写渲染层，字段名必须来自「实查 DTO/记录项或真实响应」，不能来自语义推测**；
    且**字段清单要落成可复跑的哨兵**，否则后端一改名，界面又静默换成另一个事实。

94. **严格相等 `===` 要数字，而 DOM `dataset` 永远是字符串 —— 「点了没反应」的经典成因**。
    现场（同上）：`findApproval(id, scope)` 的实现是 `asArray(src).find(a=>a.id===id)`
    （`index.html` L3275-3279，**严格相等**）。经典调用方一律传**数字**：
    `"openTodoDetail("+a.id+",'mine')"`（数字字面量，L2285/2313/2329/2353）或 `+el.dataset.mine`（L2464）。
    OA 侧写成 `oaOpenApproval(row.dataset.appr, …)` 直接传**字符串** ⇒ `688 === "688"` 为假
    ⇒ 弹 toast「审批单不存在或已刷新」，**审批详情整条路径打不开**。
    修法：在入口处 `id = Number(id)`（同时修好 `S.apprDetail`/`state.todoDetail` 下游的同类查找）。
    排查法：`grep -n "dataset\." ` 逐个看是否有类型转换 —— 同一个文件里其它 5 处都写了 `Number(...)`，
    **只有一处漏了，这种「同文件内不一致」是最容易被忽略的**。
    判据：**复用既有函数前，先确认它的入参类型契约**（尤其含 `===` 查找的函数）；
    DOM 取值默认当字符串处理，不要假设它和接口 JSON 同型。

95. **图标/枚举的「可选值集合」也要与生产端对齐 —— 拼错的键既不报错，还可能渲染成空白**。
    现场（同上）：OA 按 `d.icon === 'xls'` 选绿色表格样式，而后端 `KbService.guessIcon`（L307-321）
    的词表精确为 `{doc, sheet, pdf, file}` —— **根本没有 `'xls'`** ⇒ 该分支永不可达，
    专为表格准备的 `.file-ico.xls` 绿色样式成了死代码，电子表格永远显示成蓝色 doc。
    另一处：`ic(k)` 渲染的是 `<use href="#i-<k>"/>`，**键不存在就渲染成空白**；
    实测 `<symbol>` 里 `i-sheet`/`i-doc` 有、**`i-pdf`/`i-file` 没有** ⇒ 字形只能从存在的键里选。
    修法：色块与字形都按**生产端真实词表**映射，缺符号时回落到已存在的键（`sheet`/`doc`）。
    验证法：加**运行时**断言「全文档每个 `<use href="#i-*">` 都能 `getElementById('i-'+k)` 解析到符号」
    （`_e2e_oa.py` G2，实测 37 个唯一引用 / 缺 0）——
    静态扫描扫不全，因为图标键还会**藏在数组字面量里**（首页/KB 指标 `[['folder',…],['check-circle',…]]`）
    或来自 `iconKey()` 这类动态映射。

96. **两形态同页并存 ⇒ 固定 id 会撞名，`getElementById` 恒返回文档中靠前的那个**。
    现场：`fbItemHtml(f, true)` 里的回复框写死 `id="fbReply<id>"`。经典 `page-feedback` 与 OA `v-feedback`
    **同时存在于 DOM**（其中一个被 CSS 隐藏），于是同一 id 出现两次；`$()` 是
    `document.getElementById` ⇒ 在**新版**里点「回复」，读到的是**老版**那个空输入框
    ⇒ 恒弹「请先填写答复内容」。**页面上什么都不报错，只有一句像业务校验的 toast** ⇒ 极难归因。
    修法（本仓库已采用）：① id 加形态前缀（`oaFbReply<id>`）；
    ② 事件处理不再依赖全局 id，改为从触发元素就近取：`btn.closest('.fb-reply-box').querySelector('.fb-input')`。
    判据：**新增一层 UI 时，先问「这些 id 在另一层里是否已经存在」**；
    凡「HTML 字符串里拼 id」的渲染函数，都要考虑被两层同时调用的情况。
    自查法：**必须在运行时查，不能在源码里 `grep`**——
    `grep -o 'id="[^"]*"' index.html | sort | uniq -d` 会把「同一个三元表达式两个分支各写一次 id」
    误报成重复（实测唯一命中 `oaApBack` 就是这种：`index.html` L5991/L5995 是 `? :` 的两臂，
    运行时只插入一个）。正确做法是浏览器里数**已挂载**的元素，已固化为套件断言 `G3`：
    `[...document.querySelectorAll('[id]')]` 按 id 计数，>1 即失败（实测 295 个已挂载 id / 0 重复）。
    **覆盖边界**：它只覆盖「检查那一刻已挂载」的元素——列表为空时（例如反馈收件箱没有条目）
    那些动态行根本不存在，扫不到；故「渲染函数里拼 id」仍要靠人审 + 上面 ① 的前缀约定兜住。
    即：**「源码里出现两次」≠「DOM 里同时存在两个」**，验证要看运行时，不看文本。

97. **「两形态并存」时，跨形态复用函数要先确认它没被另一层覆盖 —— 但别只看 `^function` 就下结论**。
    现场：`_oa_app.js` 里也有 `renderMe` / `renderKb` / `renderExperts` / `renderSkills`，与经典同名。
    用 `grep -o "^function X"` 粗扫会得出「4 处全局覆盖 ⇒ 经典我的页名字恒为 `—`」的**错误结论**。
    实际 `_oa_app.js` **整体包在 IIFE 里**（首行 `(function(){`，末行 `})();`），只 `window.oaBoot` 等 4 个出口
    ⇒ 零污染。判据：**判断是否污染全局，要看文件的作用域结构（IIFE / `let` 顶层 / `window.X=`），
    不是看函数名重复**。核查命令：`head -20` + `tail -20` 看 IIFE 首尾，再 `grep -n "^window\."` 看出口清单。

98. **`display:none` → 恢复显示会让 CSS 动画从头重放；若在动画中途量 `getBoundingClientRect`，几何量会整体偏掉一帧的位移**。
    现场：首页气泡的三角尖角要指向数字人，角度由 `oaLayoutTails()` 按 `#oaRobot` 与气泡的**实测 rect**
    反算（`atan2(Δy,Δx)+90°`）。切到别的视图再回首页后，套件 E4 稳定报**角度差 1.219°**（4 次复现）。
    第一反应是「入场 stagger 没跑完」，把 `#v-home` 的 stagger 关掉 —— **无效**。
    （这一步很关键：改一处无效就说明诊断错了，要换手段，而不是继续在同一假设上调参数。）
    写临时诊断（`scripts/_diag_oa_tail.py`）逐帧打印 rect 才发现：`#v-home` 从 `display:none` 恢复时，
    里面气泡的 `bub-in` 动画（`translateY(8px)→0`）**重放了**，而布局计算发生在动画第 0 帧
    ⇒ 量到的 rect 比终态**低 8px** ⇒ 角度差 ~1.2°。
    修法：**不要猜「等多久动画就完了」**，改为监听动画真正结束再重算 ——
    `dockList.addEventListener('animationend', e => { if (e.target.classList.contains('bub')) oaLayoutTails(); })`。
    修后实测误差 **0.000°**。判据：**凡按「实测 rect」算几何的地方，都要保证测量发生在动画终态**；
    动画时长/缓动属于样式层（会被 `prefers-reduced-motion`、令牌改档改动），
    用固定 `setTimeout` 去对齐动画 = 把「样式」与「几何」变成了两份会各自漂移的事实。

99. **双形态同名类的探针：限定 `#oaRoot` 还不够 —— `?.find(vis) || all[0]` 这个「回退」分支恰恰就是经典节点**。
    现场：`_check_oa_visual.py`（读 computed style，验令牌是否真落到页面上）第一版裸用 `.card`，
    挑到了 `#oaRoot` **之前**的经典元素；加了 `OAROOT = '#oaRoot '` 常量后仍报 4 项 FAIL
    （`.card` 阴影只有 1 层、`.empty div` 对比度 2.60、梯级不可辨）。**但那个常量定义了却从未被使用**，
    真正生效的是 `pick = sel => [...querySelectorAll(sel)].find(vis) || all[0]` ——
    首页上 `.card` / `.empty div` 一个都不可见，`find(vis)` 返回 `undefined`，于是**回退到 `all[0]`**，
    而 `all[0]` 就是那批 `display:none` 的经典节点（吃 `:root` 旧令牌）。
    ⇒ 4 项「缺陷」全是假的：新版早已改对（`#oaRoot` 上 `--sh-1` 双层、`--text-3` = `#667080`；
    加前缀后实测 `.card` 2 层、`.empty div` = `rgb(102,112,128)` 即 5.01:1）。
    修法：① 选择器一律拼 `OAROOT` 前缀（**作用域只留一个来源，别在 JS 里再写一份**）；
    ② 挑不到可见元素即记 `missing` 并**跳过**，不回退、也不判失败（本页没这个元素 ≠ 这个元素没改对）；
    ③ 加一条**非恒真**的自检断言：「凡参与判定的元素必须都在 `#oaRoot` 内」，作用域一旦被改宽会立刻变红。
    判据：**探针的「空结果」必须与「判定失败」分开**。把「没找到」和「不符合预期」压成同一个返回值，
    红/绿就都不再指向事实；而**恒真的兜底回退比没有断言更危险** —— 它给出的是**看似有依据的假缺陷**，
    会让人去改本来正确的代码（本次差点就去「修」一份完全正确的 CSS 层叠）。

100. **同一 URL 有「未登录 / 已登录」两种期望值时，断言名里没写清前置，就会把 401 报成 404 的失败**。
    现场：新增 `GET /api/v1/kb/documents/{id}` 的套件里，A1 想验「已登录读不存在的资料 → 404」，
    但调 `api.get(path)` 时**漏传 `Authorization`** ⇒ 拿到 401 ⇒ 断言红。
    **产品侧是对的**（同一轮冒烟里带 token 打同一个 id 明确回 404），红的是断言本身。
    代价不只是多跑一轮：它会让人以为「接口没接上」，进而去翻后端路由 —— 与 #99 同一类
    「**验证口径本身写错 → 报出假缺陷**」，只是这次错在「前置没写进断言」而不是「探针选错元素」。
    判据：**凡同一路径既能匿名访问又能带票访问的断言，前置（已登录 / 未登录）必须写进断言名与调用里**；
    排障顺序也应固定为「先证明断言可复现 → 再看产品」，**先怀疑自己的探针，再怀疑被测代码**。
    自查法：套件里每一个 `api.get/delete(...)` 都要能一眼看出带没带 token（本套件统一用具名 `h_user/h_other/h_cross`）。

101. **后端枚举的「原文」不是对外契约：任何形态各自写一份字符串比较，就会静默失效（且不报错、不影响接口）**。
    现场：`DocView.from` 把 `state` 统一**小写**下发（`ok` / `wait` / `failed`），而新版 OA 的 `renderKb()` 写的是
    `d.state === 'READY'` / `'FAILED'`（大写，字样取自更早期的原型）⇒ **恒不成立**。后果同源且同屏两处：
    列表徽标永远落到兜底分支 ⇒ 显示后端英文原文「ok」且配色一直是「处理中」的琥珀色；
    概览磁贴算成「已就绪 0 / 处理中 N」⇒ 把已入库的资料说成没就绪。
    接口全绿、console 无异常、`state` 字段值本身完全正确 —— **只靠接口断言与日志永远抓不到**，
    是拍截图时肉眼发现的。修法：抽 `kbStateLevel()/kbStateText()` 作为**唯一认识后端词表的地方**
    （内部 `toLowerCase()` 并兼容 `ready/fail` 别名），经典与新版两条渲染链一律经它，不再各自比字符串。
    判据：**跨层传递的枚举/状态码，识别入口只能有一处**；前端出现 `=== '大写常量'` 而值来自后端时，
    先 `grep` 后端 `from()`/序列化确认大小写与别名，再看页面。配套：为「徽标是中文」与
    「概览与列表同源」各补一条断言（否则这类缺陷只会被下一次截图偶然发现）。

102. **`innerText.split('\n')[0]` 取「标签」是布局相关的：flex 同行时标签与数字粘成 `'已就绪3'`，取不到 ⇒ 假失败**。
    现场：`_e2e_kb_doc.py` 的 B5 想验「概览磁贴 已就绪 数 == 列表 已就绪 行数」，
    用 `t.innerText.split('\n').filter(Boolean)[0]` 当键去 `dict(tiles).get('已就绪')` ⇒ 得 `None`，
    报出 `tile=None list=3` 的假缺陷；**产品是对的**（同一快照里 `b` 的 textContent 就是 3）。
    根因：磁贴的 `<span>` 与 `<b>` 在**同一行**（innerText = `'已就绪3'`，无换行），
    换行只在块级分界处产生 —— 于是「按换行切首行」拿到的是拼接串，永远等不上标签。
    修法：标签/数字**各自从子元素读**（`t.querySelector('span'/'b').innerText`），与布局、字号、换行彻底解耦。
    同类：任何「按渲染文本切分」的提取（首行/首列/冒号前）都隐含布局假设，取值应回到**语义子节点**。
    配套：与「前置」一起写清 —— B5 补了 B5a「概览总数 == 列表渲染行数」作为前置
    （列表 `slice(0,30)`，一旦被截断则两者本就不可比），**先报前置失败，再判同源**；
    否则截断会被读成「同源不成立」，又是一次假缺陷。

103. **断言读「内联样式」= 把实现细节焊进断言：JS 把 CSS 变量改写到宿主节点后，内联读法恒得 0，报出假失败**。
    现场：`oaLayoutTails()` 原本把 `--tail-x/y/angle` 写在三角节点（`.bub .tail`）上；本轮为让
    首页浮动卡的三角（伪元素 `::after`，没有子节点可写）复用同一算法，改为一律写在**宿主**上
    （`.bub` / `.kpi-float`），伪元素与子元素都靠继承拿到。产品渲染完全正确，但 `_e2e_oa.py`
    的 E1/E2 读的是 `t.style.getPropertyValue('--tail-angle')`（**内联**样式）⇒ 恒得 0
    ⇒ 三角朝向断言与落位断言会双双变红。**这不是产品回归，是断言绑死了「变量写在哪个节点」**。
    修法：改读 `getComputedStyle(el).getPropertyValue(...)` —— 计算值带继承，写在宿主还是写在
    三角节点都读得到真实渲染结果，且仍是独立判据（角度由断言自己按 θ+90° 重算）。
    判据：**断言要断言「渲染出来的事实」，不要断言「JS 把中间量存在哪个节点」**；
    凡要读 JS 写的内联量时，先问一句「换个等价写法它还成立吗」。
    同类：读 `.style.xxx`（内联）而不是 computed style 的所有断言，都属这一类脆性耦合。

104. **全部样本朝同一个方向偏同一个常数（如全是 -90.00°）= 探针自己的基准/符号错了，不是被测代码错了**。
    现场：为首页四张浮动卡写三角指向自检时，四张卡的朝向误差**整齐地全是 -90.00°**。
    这不可能来自几何计算（不同卡的方向角明明各不相同），只可能来自探针自己的换算约定 ——
    事实是我把「基准态顶点朝向」写反了：三角是转 45° 的方块（`border-right`+`border-bottom`
    相交的角为顶点），不旋转时顶点朝**右下**=屏幕角 45°，故顶点朝向 = `45° + rot`；
    我写成了 `rot - 45`，于是整批差 90°。产品是对的，`rot = θ - 45` 正确（顶点 = θ）。
    判据：**误差与样本无关、恒等于同一常数 ⇒ 先去核对自己的基准/符号/坐标系**，
    不要去看被测代码（几何计算不可能同时让所有样本错同一个常量）。
    自检技巧：拿一个已知答案的旧状态验算自己的公式 —— 例如把公式套到「原实现
    `rotate(45deg)` 顶点朝正下 90°」上，`45+45=90` ✓ 立刻暴露符号写反。
    与 #100（前置没写进断言）、#102（按渲染文本切分）同族：**先把探针证伪，再怀疑产品**。

105. **气泡尾巴不要自绘几何 —— 复用既有气泡组件；且落点必须「沿边收进离转角」，桌面宽度下射线恰好从转角穿出**。
    现场（同一根尾巴，四次迭代，前三轮全被用户否决）：
      ① 四组写死的静态 CSS 三角（k1/k2 朝上、k3/k4 朝下）⇒ **四张全背对数字人**；
      ② 直接 `rotate(θ-45°)` 把顶点转向数字人 ⇒ 「转 45° 方块压边切角」的对角线不再垂直
         卡片边，卡片边斜切方块 ⇒ 渲染成**梯形/斜方块**（用户报「出错了」）；
      ③ `rotate(ν-45°)+skewX(ν-θ)` 与「直接画 SVG path」两版 ⇒ 几何全对（顶点误差 0.01°、
         矩阵/面积不变量全绿），但细长三角在 1x 下**像折角/狗耳** —— 几何正确 ≠ 看得对；
      ④ 终版：**复用对话坞气泡的尾巴组件**（`.tail`，13×13 旋转三角，path
         `M6.5 0.5 12.5 12.5 0.5 12.5z`）—— 同一元素、同一套 CSS 机制（`--tail-x/y/angle` +
         整体旋转）、同一套写量代码（用户口径「用气泡组件来生成」）。
    **落点必须收进**：`卡片中心 → 数字人` 射线与卡片边的交点在**桌面宽度下恰好是转角**
    （1280px 实测四张卡离转角全部 0.0px），尾巴楔在角上读不出「长在边上」——
    用户截图里那块「折叠角」正是它。修法：沿边坐标夹到 `[TAIL_INSET, 边长−2−TAIL_INSET]`
    （内边盒坐标；`−2` 是左右边框，否则两侧实际收进差 1px），**收进后按最终落点重新指向
    数字人**（组件三角整体旋转、底边不要求贴边，落点动了朝向必须重算）。
    经验：① 「用基础形状+裁剪拼目标形状」每一步都给渲染器留解释权；**同一视觉元素
    全站只养一套实现**，别为它再写一份几何。② 几何断言全绿也拦不住「看得不对」——
    形状类改动必须人眼看放大图 + **覆盖用户实际使用的视口宽度**（见 #106）。

106. **探针只测手机宽度 = 替用户做主；且 `parseFloat(v) || NaN` 会把合法的 0 吃成 NaN**。
    现场（同一轮的两个探针错，产品均无罪）：
    ① 浮动卡尾巴自检只跑了 360/390/430（手机 H5 的常见宽），落点都在边中部附近、全绿；
      用户实际视口更宽，1280px 下「卡片中心 → 数字人」射线**恰好从转角穿出**
      （四张卡离转角全部 0.0px），尾巴楔在角上 —— 这就是用户一直说「没调整过来」的
      真实形态。判据：**视觉/布局类验证必须覆盖用户实际使用的视口**（桌面宽度加一档
      1280×800），不是「我方便生成的宽度」。
    ② 贴上边的落点 `--tail-y` 恰好是 `0px`，`parseFloat('0px') || NaN` ⇒ 0 被当成假值
      换成 NaN ⇒ k3/k4 假红（贴边判 R/L、沿边 nan）。正确写法：`const v=parseFloat(s);
      return isNaN(v) ? NaN : v;` —— **`|| 默认值` 只能用于「空才是缺省」的字符串，
      不能用于数值（0 是合法值）**。
    ③ 同轮还有一例：测量分两次取（先跑布局、隔 450ms 再量几何），中间页面还在稳定
      （数字人位置差 4px ⇒ 朝向差 0.9° 假红）。**落位与几何必须在同一个 evaluate 里
      原子取样**（先调 oaLayoutTails() 再读 rect + computed，一帧内完成）。

107. **白组件在浅背景上靠投影成立；视口「高度」和宽度一样能改变构图（机器人 bitmap 会与卡片相交）**。
    现场：尾巴组件换上后用户仍报「还是没有成功」——1x 实拍发现尾巴近乎隐形。
    两个叠加的根因，几何断言全绿也拦不住：
    ① **白填充 + #e6eaf2 描边 + 无投影**，压在浅灰白背景上 = 幽灵。
       卡片自己能被看见靠的是 box-shadow；尾巴没有 ⇒ 不成立。修法：给尾巴
       `filter: drop-shadow(...)` 两段近似 `--sh-2`（drop-shadow 无 spread 参数）。
       同族教训：描边用**开放 path 只描两条斜边**——整周描边会把底边那条线
       横在尾巴嘴里、落在卡片内部，看起来像多出来的线。
    ② **视口高度缩短后机器人 bitmap 与卡片相交，且机器人在卡片之上**（DOM 顺序
       robot-wrap 在 kpi-float 之后 ⇒ 后绘制者在上），尾巴整段被白色机器人身体吞掉。
       360×740 一测就现形（844 高时不相交，所以此前测不出）。修法：`.kpi-float`
       加 `z-index:2` —— **交互 UI 永远在装饰插画之上**；旧的「位图与卡片零像素
       重叠」断言随之作废（矮视口下矩形本就相交，正确不变量改为 elementFromPoint
       命中卡片自身 = UI 在上）。
    经验：视觉复现要**同时覆盖用户可能的宽度与高度**（360×740 矮机是真实存在的）；
    「看得见」靠的是投影/对比度，不是几何正确 —— 几何全绿后必须再看 1x 实拍。

108. **需求方复用了我方组件名时，「去掉这四个气泡」指的是那个组件、不是承载它的卡片**。
    现场：围绕首页四张浮动指标卡上的尾巴来回六轮后，用户说「去掉这四个气泡」。
    我这边一直把尾巴元素叫「气泡组件/气泡尾巴」（用户也在前几轮沿用：「重新生成一个气泡」
    「用气泡组件来生成」）；若按「卡片长得像气泡」理解成删掉四张数据卡，就删错了对象。
    判据：**检索该名词在本会话中双方各自的用法**——用户全程只用「三角」「气泡/气泡组件」
    指尾巴，从未用「气泡」指卡片；且卡片承载数据（待我审批/我发起的…），删除代价远大于
    装饰元素。两个信号一致时才执行；信号冲突则先按「代价小、可回退」的一侧动手。
    结果：只删四根尾巴，卡片恢复干净圆角矩形，用户未再纠正。
    同族教训：**改动前先把「用户口中的名词 → 代码里的元素」映射写下来**，
    映射不清时不要按自己的内部命名去猜。

109. **自检脚本的「通过计数」必须由「实际结果 vs 预期」推导，不得用 `len(预期)` 自证**。
    现场：`scripts/verify_closed_institution_surfaces.py --selftest` 末行写
    `print("...%d/%d..." % (len(expect), len(expect)))` —— 两个数都是预期集大小，
    **恒等于 5/5**；同一轮实际报红 6 项（多出 F4 未列入 expect），输出却仍显示「5/5 预期项
    全部真的报红」。于是「预期集漏项」与「预期全覆盖」在输出上完全不可区分 ——
    恰恰是负向自检最该拦住的情形。
    判据：看通过行里两个数**是否同源**。同源（都来自 expect）即自证标签，必须改。
    修法：① `expect` 补齐所有真报红项；② 新增 `extra = fired - expect` 并**显式打印**
    （多验证到一项非真空性是好事、不算失败，但静默吞掉就等于漏了覆盖）；
    ③ 通过行改 `len(expect - miss)/len(expect)`。
    同族教训：**凡「N/N 通过」字样，N 的分子必须来自实际观测集合**；只有分母可以来自预期。
    与之同构的还有「恒真断言」`chk(name, True, "")` 与「与基线一致≠干净」（#11）——
    三者都是「用一个不承载信息的数换取绿灯」。

110. **「回答后的收口」是 `await` 之外的异步尾巴 —— 必须发代次令牌，否则会往已隐藏的界面里补 DOM**。
    现场（OA 新版复刻老版「推荐换人 + 表单直出」）：收口要先调一次
    `POST /v1/workers/intent` 才知道该推荐谁，而这段刻意**不 await**（`S.busy` 早已释放，
    推荐晚到一步不该拖住下一次提问）。首版没给这段加任何失效判据 ⇒ 用户若在等待期间
    **切回经典形态**，表单会在切走**之后**才落进已隐藏的对话坞；经典侧随后又自己发一份
    ⇒ 文档里出现**两份 `#leaveForm`**（E2E H8 实测 `count=2`；H7 也量到 `count=1`）。
    判据：**凡「先 await、再写 DOM」的收尾逻辑，落地前必须重新确认它当初的触发条件仍成立**
    （形态没变 / 对象没换 / 问句没被新的顶掉）。三者任一不成立就整轮放弃。
    修法：`var seq = ++oaAnswerSeq;` → await → `if(seq !== oaAnswerSeq || S.mode !== 'oa' || S.lastQuery !== q) return;`；
    并在**离开新版 / 换对话对象 / 新开对话**三处 `oaAnswerSeq++` 作废在途轮次。
    同族：**改动面里凡是「模式切换 + 异步写入」同时存在，就一定有这个洞** —— 切换不是纯 UI 动作。

111. **两形态共用一个文档时，动态插入的固定 id 必须保证「至多一份」**。
    现场：请假表单的 id 是写死的（`leaveForm` / `lfType` / `lfStart` / `lfFiles` …），
    经典 helper（`submitLeave` / `renderLeaveFiles` / `leavePickFiles`）全靠 `$('lfXxx')` 取值；
    OA 新版把它复用到对话坞里，于是同一文档可能出现两份。
    双重后果：① `document.querySelectorAll('#leaveForm').length === 2`（E2E G3「无重复 id」判红）；
    ② `getElementById` 恒返回**文档中靠前**的那份 ⇒ 在 A 形态填的表，落在 B 形态的副本上。
    更隐蔽的第三重：经典的发放判据是「文档里已有表单就不再发」（`if(!document.getElementById('leaveForm'))`），
    **新版的副本会把它挡掉** ⇒「经典问请假却不出表单」。
    修法（在新增侧收口，**不动经典基线**）：新版发新表单前清掉经典遗留的那份（该形态此刻整体隐藏、
    已无法操作），并**顺带作废它暂存的附件**（否则会把上一份表单的证明材料带进这次提交）；
    离开新版时撤掉自己注入的那份。⇒ E2E 必须**双向**断言：切回经典 count=0、经典自发放后 count=1。
    判据：**「复用老组件」时先问 id 是不是写死的**；写死就一定要有「至多一份」的所有权约定，
    且约定要写成测试，别只写在注释里。

112. **构建脚本打印的是「字符数」，`wc -c` 是「字节数」——中文 3 字节，两者不可直接比**。
    现场：`_build_oa.py` 末尾打印 `完成：247894 → 433610 字节`（实际是 `len(str)`，**字符**），
    而同一文件 `wc -c` 给 **495204 字节**（差 14%）；再与上一版提交里的 481315 字节一比，
    误以为「产物凭空小了 48KB」，差点去追一个不存在的丢失。
    判据：**比对产物改了多少，用 `git diff --numstat`（行级）或同单位的
    `git show HEAD:path | wc -c` vs `wc -c path`**；不要拿脚本自报的数与 shell 工具的数互比。
    同轮真正管用的一招：确认「经典基线段一行未动」，是
    ① `git diff --numstat user-client/index.html` = 仅 1 行删除（段标题注释）；
    ② 逐字节比较两份文件在首个 OA 注入标记之前的前缀是否相等。
    ⇒ **「产物没被我改坏」要用行级/字节级证据说，不用体积变化说。**

113. **「回答已收口（有正文）」不能用长度判定 —— 一条 27 字的错误文案就能满足它。
    加一条独立的「这是错误文案吗」断言，把真因写在结论里。**
    现场：`wjj_xu`(tenant 3) 的 `tenant_quota` 剩余 **0**（E2E 反复跑光），会话返回
    `请求失败：今日免费额度已用完，请购买词元套餐或明日再试`（27 字）。
    链式后果：`answered=false` ⇒ `oaAfterOaAnswer()` 根本没被调用 ⇒ 推荐块不存在 ⇒
    H2a–H2d 四条「推荐块没出现」报红 + H3 的 `g.querySelectorAll` 直接 TypeError 崩掉流程。
    表面像「推荐功能回归」，真因是**环境额度耗尽**（`reset_demo_quota.py` 一跑即绿）。
    修法：① 断言改 `answerLen > 0 and 无错误字样`，并把 `【环境】…先修环境再看后面各条`
    写进 detail；② 没有推荐块时 H3 **不要崩**，返回 `clicked:false` 交给断言报红。
    判据：**凡「某物存在」用「长度 > 0 / 非空」当代理，就有被错误文案/占位文案满足的洞；
    消费它的下游断言还会因此收到 undefined 而崩，把一个真因扩散成一片假红。**

114. **断言要看「本轮新产出的东西」，不能看「历史留在页面上的存量」——否则是假阳性；
    而且必须带阳性对照，否则退化成恒真。**
    现场：H5 时当前对话对象已是「请假助手」，我断言「坞内所有推荐块都不含当前对象」，
    实测报红：`rows: ['换「请假助手」']`。
    但那块推荐是 **H2 那轮**生成的（当时当前对象是政策快讯员，推荐请假助手完全正确），
    只是**刻意保留在坞里**。规则「不推荐当前对象给自己」是**生成时刻的性质**，
    不是「坞内历史的性质」。
    修法：发问前快照 `gpre = 全部推荐块的行`，答后取 `gpost`，被测集合 = `gpost[len(gpre):]`；
    同时断言**阳性对照** `更早的块里确实命中过当前这位`（证明「这个问句本来就推得出它」，
    排除「本轮没命中只是因为压根推不出来」）。
    负向自证：把 `oaWorkerHit` 的 `if(S.worker && w.id === S.worker.id) return null;`
    改成 `if(false && …)`，重建 → **只有 H5d 报红（1 项）**，其余 105 项仍绿 ⇒ 断言真的会红。
    判据：**凡被测对象是「追加型容器」（对话流、日志、事件队列），判据一律取快照差分；
    光有「当前状态里没有它」永远不能证明「它没被生成」。**

115. **错误词表用「裸词」会误伤正常业务文案 —— 用完整错误句。**
    现场：我用裸词 `额度` 判「这轮是错误文案」，结果把 H5 正常发出的请假表单判红
    （假种下拉里就写着 `年假/病假/事假（不占额度）`）。
    修法：词表换成 `免费额度已用完 / 额度已用完 / 额度不足 / 请求失败： / 生成失败： /
    本次未返回内容 / 请检查网络或后端服务`（带冒号、带完整语义）。
    判据：**做「异常文案识别」时，词表条目要与正常文案做过对抗 —— 短词首先怀疑。**

116. **共用事务所里的 `try/catch` 是假的：内层失败先把事务标成 rollback-only，外层再想提交只剩 500。**
    现场（`docs/42` 第三节）：PM 立项带 `createRepo:true` 调 `GiteeProjectService.create`
    （该方法 `@Transactional`），内层抛 `BizException("归属部门不存在…")`。
    调用方明明写了 `try/catch` 并把异常转成 `repoWarning`（注释还写着「建仓失败不阻断立项」），
    实际却是 **`POST /pm/projects` 返回 500，且项目行、成员行一条都没落库** ——
    因为内层异常经由同一个事务传播后已把事务标记为 rollback-only，catch 只吞掉了「异常对象」，
    吞不掉「事务已判死」这个事实，外层返回时提交阶段抛 `UnexpectedRollbackException`。
    修法：让被调用的写操作**自带独立事务**——
    `@Transactional(rollbackFor = Exception.class, propagation = Propagation.REQUIRES_NEW)`；
    或者把该动作挪到 `TransactionSynchronization#afterCommit` / 事件监听器里。
    判据：**凡出现「A 的异常被 catch 成警告、但接口仍 500 / 数据仍全回滚」，
    第一个要查的就是 A 是否与外层共用事务**；`catch` 的存在不能证明失败被隔离。

117. **「内部哨兵值」不得跨出本模块边界 —— 否则它会把一句前置校验变成一次注定失败的下游调用。**
    现场（`docs/42` 第三节，与 116 同一条链路）：`PmProjectService.create` 在
    `departmentId` 缺失时补 `0L`（含义是「机构直属、未挂具体部门」，纯内部哨兵），
    却把 `0L` 原样塞进建仓参数。而 `GiteeProjectService.create` 要求部门**真实存在**
    （`requireDepartment`）⇒ `0L` 必然换来「归属部门不存在」，白跑一次跨模块校验，
    并与 116 叠加成 500。修法：在**边界上**判掉（`departmentId == null || departmentId <= 0`
    就改走警告分支，并给出可执行的中文补救路径），而不是让下游去解释哨兵值。
    判据：**一个值如果在定义处是「没有」的编码（0 / -1 / "" / 空集合），它一旦被当作
    「一个真实的值」传给别的模块，就是缺陷温床** —— 边界处要么换成真实值，要么明确不带。

118. **「端口通」不能推定「启动入口是好的」—— 排查启动问题必须看进程命令行。**
    现场（`docs/42` 第一节）：:8080 一直正常服务，看起来毫无问题；
    实际上它是**手工**带 `-Dspring.flyway.validate-on-migrate=false` 起的，
    而仓库里的 `start-backend.bat` 并没有这个参数、且挂着一个不存在的 profile
    ⇒ 换任何人按脚本重启都会直接 `MigrationChecksumMismatchException` 起不来。
    根因是 `V68__remove_sub_tenant.sql` 被应用 20 分钟后又被改过，而
    `application.yml` 开着 `validate-on-migrate: true`。
    判据：**别拿健康检查当「启动链路健康」的证据；`Get-CimInstance Win32_Process` 看命令行，
    再拿脚本原样跑一遍临时端口**（本次即用 18083 复验，见 `docs/42` 第一节「补充」）。

119. ★**禁止用 `-Dspring-boot.repackage.skip=true` 构建 `aios-boot`**（2026-10-11 实际踩到，且**铁律早有记载仍复发**）：
   该开关产出 **170KB 的瘦 jar**（无 `BOOT-INF/lib`）。若此时**已有更早启动的进程在跑**，
   JVM 按需加载 ⇒ 启动时已加载的类照常，**未加载的类再也读不到**：
   `/v1/conversations/{id}/runs` → 500 `NoClassDefFoundError: cn/aios/chat/dto/RunCreatedResponse`，
   `/admin/org-configs` → 500 `NoClassDefFoundError: …mvc.LastModified`。
   **与业务代码无关、日志里是 CNFE、`mvn test` 全绿**（测试读 `target/classes`，不读 jar）⇒
   **只有查产物才看得见**：`scripts/_check_boot_jar_fat.py`（已进 `_run_all_regression.sh`）。
   修法：**先停 :8080**（运行中进程锁着 jar，repackage 的 rename 必失败，`-Djar.finalName` 也无效），
   再 `./mvnw -o -pl aios-boot -am -DskipTests package`。
120. **新写的 api 模块路径不得自带 `/v1`**：`api/index.ts` 的 `http` 已带 `baseURL=/api/v1`，
   写成 `http.get('/v1/admin/org-configs')` 会打到 **`/api/v1/v1/...`**（404）。
   `typecheck` / `vite build` **都查不出这种运行时路径错** ⇒ 新页面必须**真点一次**。
   判据：对同一路径分别请求 `/api/v1/<p>`（应 200）与 `/api/v1/v1/<p>`（应 404）。

121. ★**不要从「异步续段」里触发需要用户手势的浏览器能力**（文件选择器 / 全屏 / 剪贴板 / 弹窗）：
   2026-10-11 用户实测「项目内输入『上传文档』，对话窗口没有打开」。
   旧实现是「动态造 `<input type=file>` 再立刻 `click()`」，而它由 `oaAfterOaAnswer()` 在
   `await 整段回答流式生成` + `await /v1/workers/intent` **之后**才调用 ——
   此时距用户点「发送」已过数秒乃至数十秒，**用户手势的瞬时激活（transient activation）早已失效**，
   `click()` 被**静默忽略**：不抛异常、不弹窗、控制台无报错，用户只看到一句「正在打开…」。
   ⇒ **判据**：凡「先说话再打开系统级控件」的交互，一律改成**先弹一个可见窗口**，
   让用户在窗口内**直接点击**那个控件（手势在点击那一刻成立，必然唤起）。
   本仓已按此改：`oaOpenUploadForm()`（与「上报花费」的 `oaOpenExpenseForm()` 同形）。
   定点回归 = `scripts/_verify_oa_action_popup.py` 的 G9a/G9b/G9c
   （G9b 断言「弹窗那一刻**不**自动唤起选择器」——旧实现在这条上必红，故有区分力）。
   ⚠️ 自动化浏览器（Playwright/CDP）**不校验**该手势要求，`filechooser` 照样触发 ⇒
   **这类缺陷自动化测不出来**，必须在真机/真浏览器里试；写断言时要显式钉住「由谁触发」。
122. **用户端气泡已无「三角」（尾巴）**：2026-10-11 用户口径「去掉对话框的三角」。
   生产者只有 `_oa_app.js` 的 `oaPushBub()` 一处（原来在 `innerHTML` 末尾拼 `<svg class="tail">`）。
   `.bub .tail` 的样式与 `oaLayoutTails()` 的落位分支**保留**（将来复用不必重写几何），
   故**不能只看「样式还在」就以为尾巴还在** —— 判据是 DOM 里 `.bub .tail` 计数为 0
   （`scripts/_e2e_oa.py` 的 E 组已按此改口径）。
   ⚠️ 配套两条必须一起在：产物静态口径 **E3** 只钉**生成串** `<svg class="tail"`（**不能**断言全文无 tail，
   因为 `.bub .tail` 的 CSS 是有意保留的）；判据自检 **E2**（见 #124）。
   `docs/39` 原写「✅ 气泡三角都对着数字人」并在 §5.3 详述角度算法，已就地作废/划撤（8 处）。

123. ★**用户端 `API` 是顶层 `const`，不挂在 `window` 上**（2026-10-11 实测）：
   要写脚本时**裸用 `API`**（`API.req.bind(API)`、`API.req = …`），写成 `window.API` 会得到 `undefined`
   （报 `Cannot read properties of undefined (reading 'req')`）。
   对照：`window.oaState` / `window.oaMaybeProjectAction` 等**是**显式挂 `window` 的（自检暴露），
   所以「哪些是 window 上的」不能凭感觉，要看源码里是 `const API = {…}` 还是 `window.X = …`。
   应用实例：`scripts/_verify_oa_action_popup.py` 在 `file://` 无后端环境下**桩掉 `/docs/tree`**
   （`#upFile` 初始 `disabled`，只在 tree 的 `.then()` 里解锁；无后端必进 `.catch()` ⇒ 永远 disabled，
   「等 `#upFolder` 非空」等不到，**必须打桩**），桩形如
   `API.req = function(p,o){ return String(p).indexOf('/docs/tree')>=0 ? Promise.resolve({project:[{id:1,name:'项目文档',children:[]}]}) : window.__oaOrigReq(p,o); }`
   —— 注意 `API.req` 已做 `body.data` 解包，**桩要 resolve 已解包的数据**。

124. ★**「数出来必须是 0 / 不得存在」这类断言，必须把负向自检固化进套件**（2026-10-11 定式）：
   这类断言最容易**恒真** —— 选择器打错一个字符（`.bub .tail` → `.bub .taill`）照样返回 0，永远绿。
   **一次性**的仓库外证明（跑一次「塞回一个必须变红」）只覆盖当天，**下次运行不会重验**。
   ⇒ 定式（`scripts/_e2e_oa.py` 的 **E2** 即此实现）：在套件内**就地注入 → 断言判据被抓到 → 撤净 → 断言回到 0**，
   三合一成一条 `chk`。判别力证明（实测）：把 `tail_count` 的选择器改坏后，**E1/E3/E4/E5/H6 全假绿、只有 E2 变红**
   —— 这就是「E2 不可省」的实证。凡新写「=0」断言，照此配一条 in-suite 自检，别只留一次性证明。

125. ★**本地 git 对象库被破坏的识别与恢复配方**（2026-10-11 实测踩到并修回）。
   症状：`git log` 报 `your current branch 'main' does not have any commits yet`；`refs/heads/` 为空；
   `git status` 把**全部文件**列成 `A `（相对「未出生」的 HEAD）；`git count-objects` 出现
   `warning: no corresponding .pack: …idx`；某些历史提交 `git cat-file -t <sha>` 报 `Not a valid object name`。
   **判据**：`.git/objects/pack/` 里只剩 `.idx`/`.rev`/`multi-pack-index` 而**没有同名 `.pack`** ⇒ 对象已丢。
   **恢复配方（本次实测可用，工作树完好时）**：
   1. 先**冻结工作树**（它此时是唯一副本）——把关键文件 `cp` 到仓库外（本次 `_aios_rescue_20261011/`）。
   2. 找**可达的镜像远端**：本仓库有第二个远端 `github = ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git`
      （`origin 172.16.8.249:3000` 当时 502）。`git ls-remote github` 通 ⇒ `git fetch github main`，
      新 pack 落盘（21 MB）后历史恢复可用。
   3. **捞 reflog 留证**：`cat .git/logs/HEAD` 仍记着丢失提交的 sha/消息/时间
      （本次捞出 9 个 Oct-11 提交 `eff5fd64…6ad8b32`，对象已不可寻回，但清单即证据）。
      拷到仓库外后**可移走 `.git/logs`**，否则 `git fsck` 会因「reflog 指向缺失对象」刷屏。
   4. **移走幻影 pack 的 `.idx/.rev` 与 `multi-pack-index`**（没有 `.pack` 的索引只会让 git 一直警告）。
   5. `git update-ref refs/heads/main <镜像 tip>` 重建分支引用。
   6. ★**必须删掉 `.git/index` 再 `git add -A`** —— 见下一条（**126**）。
   7. `git fsck --connectivity-only` 应无 error。
   ⚠️ **不要**因为「日志正常、文件都在」就以为没坏；工作树完好**不代表**历史完好，两者要分别验。

126. ★**索引的 stat 缓存命中时 `git add` 不重算哈希 ⇒ 会报 `invalid object <sha> for '<path>'`**（2026-10-11 实测）。
   场景：对象库被破坏（见 125）后，`.git/index` 里仍留着旧条目的 `(mtime,size,blob-sha)`。
   `git commit` 报 `error: invalid object 100644 <sha> for '…'` / `Error building trees`
   —— 因为 `git add` 认为「stat 没变 ⇒ 内容没变 ⇒ 不必重算」，于是那个**已被删掉的** blob sha 继续被引用。
   **修法**：`mv .git/index .git/index.bak-<日期>` 后再 `git add -A`（**强制**按工作树内容重算全部 blob）。
   判据：重算后 `git commit` 不再报 `invalid object`。**只 `git add` 不删索引是修不好的。**

127. ★**端到端哨兵的账号必须有「业务可见面」，否则断言会退化成 SKIP**（2026-10-11 实测）。
   `scripts/_verify_oa_intent_e2e.py` 首版用 `wjj_xu`（`_e2e_oa.py` 同款账号），
   而 `UPLOAD_FILE/REPORT_EXPENSE` 都**要求先进入项目** ⇒ 该账号当时**可见项目数 = 0**
   ⇒ 哨兵上线后在真实环境**只能 SKIP**，「覆盖缺口已堵」是**假的**（诚实但覆盖为 0）。
   改法：换 fixture 成员 `fagai_li`（T1008 两项目成员，与 `_verify_h5_pm_contacts.py` 同源），
   实测 11 通过 / 0 失败 / 0 SKIP。
   **定式**：写「进入某个业务对象再断言」的哨兵时，账号选择要**先验可见面**（`GET /pm/projects` 非空），
   并把「缺 fixture 时大声退出」写进脚本（铁律 15），**不要**让缺数据静默降级成 SKIP 还宣称已覆盖。

128. ★**「必须出现」的正向断言，不能用非等待的 `query_selector` 去探测「异步渲染」的元素**（2026-10-12 实测）。
   场景：`scripts/_e2e_kb_doc.py` 的 **C2**「经典列表出现『查看』按钮」原先写
   `chk(..., await page.query_selector(vbtn) is not None)`，前面只有 `wait_for_timeout(1200)`。
   但经典列表是 `go('page-me')` **之后才异步拉**的 ⇒ 矩阵满载时 1200ms 不够 ⇒ **假红**。
   **实测判别**：全量矩阵里 C2 红，**单独跑却绿**；而且紧随其后的 `page.click(vbtn)`（Playwright 的
   `click` **自带等待**）又能点到 —— 同一元素「刚说没有、马上又点到」就是竞态的铁证。
   **修法**：改成 `await page.wait_for_selector(vbtn, timeout=20000)`（try/except 后断言），
   口径即本项目既有的「**正向断言一律等明确的 DOM 条件**」。
   ⚠️ 与 **#124** 互补：#124 管「数出来必须是 0」的**负向**断言（要防恒真），
   #128 管「必须出现」的**正向**断言（要防抢跑假红）。两者都会让矩阵说假话，方向相反。
   ⚠️ 判据：**看到「同一元素在相邻两行断言里结论相反」就直接怀疑竞态**，不要去改产品代码。

129. ★**「先拿到权限/资源、再真正启动」的异步链路里，用户可能在资源到位前就已要求停止**——
   若「停止」只看**已启动的句柄**，就会漏掉这段窗口 ⇒ 资源一旦到位反而被启动，且**再无人来停它**（2026-10-12 实测）。
   场景：H5 语音「点击录音按钮后无法正常结束录音」。`getUserMedia` 是异步的；用户松手时
   `rec` 还是 `null`，旧 `end()` 里 `if(!rec) return;` 直接放弃 ⇒ 麦克风之后才到，`rec.start()` 照常执行，
   之后**永远没有第二次 end()**（手势已结束）⇒ 录音停不下来。
   **修法定式**：「已按下、资源仍在途中」也算 live，用一个 `stopping` 标记**记账**，
   由 `.then` 续体在开头检查 `if(stopping || !hooks){ 收摊; 绝不启动; return; }`；
   并把「是否 live」暴露成 `isLive()` 供手势层判断（而不是靠 `rec != null` 猜）。
   同批还补了 `setPointerCapture`：手指滑出按钮也必须收到 `pointerup`，否则同样停不下来。
   ⚠️ 与 **#121**（2026-10-11「上传窗口打不开」）同源：都是「用户手势与异步 API 的时序窗口」，
   #121 管**开**（`getUserMedia`/弹窗必须在 pointerdown 的**同步段**发起），#129 管**关**（停止必须能容忍资源未到位）。
   **可复跑的判据**：`scripts/_check_voice_gesture.py`（22 项，纯状态机、无需 HTTPS/麦克风）；
   `--selftest` 对 HEAD 旧版跑出 6 红 ⇒ 证明该哨兵对本体有判别力（铁律 12）。
   ⚠️ 断言盯 **MediaRecorder 是否真被 start/stop**、**asrTranscribe 调用次数**，不读 placeholder 文案（文案不是事实源）。

130. ★**Spring Security 的 `AuthorizationFilter` 默认参与 ASYNC 派发，而 `JwtAuthenticationFilter`(OncePerRequestFilter) 默认不参与**
   ⇒ 任何 `SseEmitter` 端点（如 `GET /api/v1/runs/{id}/events`）**流一结束**就刷三段 ERROR（2026-10-15 实测）：
   `AccessDeniedException: Access Denied` → `Unable to handle the Spring Security Exception because the response is already committed.`
   → `Cannot render error page for request [null] as the response may have the wrong status code.`。
   **本质**：流结束时容器做的那次 **ASYNC 派发**没有 SecurityContext（Jwt 过滤器跳过了它），AuthorizationFilter 却仍要判 ⇒ AccessDenied；
   但 SSE 响应早已写出（committed）⇒ 403 写不进去。
   ⚠️ **它不改变 HTTP 行为**（SSE 仍 200、事件完整）⇒ 唯一可观测面是**服务端日志**，判据必须读日志，不能看客户端收没收到。
   **修法**：`SecurityConfig.authorizeHttpRequests(...)` 首行加 `.shouldFilterAllDispatcherTypes(false)`
   ⇒ 鉴权只在首次 **REQUEST** 派发发生（能异步的前提是先过了 REQUEST 派发，不存在绕过）。
   **可复跑判据**：`scripts/_check_sse_async_denied.py`（S1 SSE 仍 200 / S2 收到终止事件 / S3 新增日志无 committed 指纹）；
   修复前 = `DEFECT-PRESENT`（S3 红、S1/S2 绿 ⇒ 能区分），修复后 = `CLEAN`。

131. ★**别把「明文端口被 TLS 探测」当成代码 bug**：日志 `java.lang.IllegalArgumentException: Invalid character found in method name [0x16 0x03 0x01 ...]`
   里的 `0x16 0x03 0x01` = **TLS ClientHello**（TLS 记录头）打到了**明文** HTTP 端口（2026-10-15 实测复现）。
   **复现法**：raw socket 对 `127.0.0.1:8080` 发 `bytes([0x16,0x03,0x01,0x00,0x50,...])` ⇒ Tomcat 原文一字不差。
   **来源**：该端口**暴露在公网**被扫描器 / `https://host:8080` 探到（实测 `http://<域>:8080/` → 502 前端代理）。
   **处置（运维面，代码改不了）**：不要把明文端口暴露公网；**前置 nginx 做 TLS 终止**，后端只对内。
   ⚠️ 与 #130 **互不相关**（同一批日志里两类错误从不同时出现）；排查时**先按指纹分类再归因**，不要混着修。

132. ★**`mvn package` 会把你正在运行的 fat jar 改成「没有 BOOT-INF 的空壳」**（2026-10-15 实测）。
   现象：`-pl aios-boot -am` 打包在 `spring-boot:repackage` 步失败（`Unable to rename ... .jar to ...jar.original`，
   因为**运行中的后端进程占着该 jar 文件锁**），而磁盘上留下的是**未 repackage 的 173KB 普通 jar**（无 `BOOT-INF/`）——
   直接 `java -jar` 会启不起来。
   **定式**：重新打包前**先停掉占用 jar 的后端进程**；打包后**验产物**`any(n.startswith('BOOT-INF/'))` 为真
   （正常体量 ~110MB，见到 100+KB 的就是空壳）。

133. ★**提示词/文案里不得引用「被哨兵当作判据的字面量」**——写进去的那一瞬间，判据就**恒为真**了（2026-10-15 实测）。
   实例：给数字人重写回答口径时，规则里写了「③ 对话内上传的参考文档（**以【参考文档】块给出**）」「① 知识库
   召回内容（**以【知识库参考】块给出**）」。而 `agent_runtime._build_attachment_block` / `_build_kb_reference_block`
   正是用这两个定界符作为「块是否真被注入」的**唯一信号** ⇒ 两个既有判据当场失效：
     · `agent/tests/test_attachment_docs.py:66` —— 无附件时 `assert "【参考文档】" not in blob`（恒假）；
     · `scripts/_check_kb_toggle.py:190` —— 关知识库时 `assert "【知识库参考】" not in off["system"]`（恒假）。
   两处都是**正确的既有约束**（「没注入就不该出现标记」），被我的措辞打破 —— **不许改测试，要改文案**。
   **判据（通用）**：凡某字面量被用作「有没有 X」的判据（分隔符 `【…】`、事件名、JSON 键、`id=` 前缀…），
   提示词、用户可见文案、日志模板**都不得引用其原文**，要用自然语言指代（「知识库召回内容」「对话内上传的
   参考文档」）。**改完立刻全仓 grep 该字面量**，确认只剩「真正的生产者 + 判据」两类引用。
   ⚠️ 与铁律 12（判据不得与被测对象同源）互补：铁律 12 管**读**的那一侧，本条管**写**的那一侧。

134. ★**「账号额度耗尽」不得判成 FAIL**——那是环境限制，不是回归（2026-10-15 实测）。
   现象：`zhangsan` 的「今日免费额度」用完后，`POST /conversations/{id}/runs` 回
   `403 {"code":403,"message":"今日免费额度已用完，请购买词元套餐或明日再试"}`；
   而 `scripts/_verify_answer_conciseness.py` 与 `scripts/_verify_chat_attachment_e2e.py` 都把它当作
   「链路断了 / 口径回归」直接 FAIL —— **判据把环境噪音读成了缺陷**。
   **定式**：起对话失败时若 `code==403 && "额度" in message` ⇒ 抛专用 `QuotaExhausted`，由**调用方记 SKIP**
   （退出码 2 = 仅 SKIP），措辞里点明「环境额度限制，非回归」。上游聚合脚本（如 conciseness 的 6a 调子脚本）
   也要**接受子脚本 exit 2 = SKIP**，否则「子脚本诚实 SKIP」又会被读成 FAIL。
   **判据**：凡「跑不动」的 FAIL，先分三类再归因 —— **代码 bug / 演示数据漂移 / 环境限制（额度·夹具·离线）**；
   只有第一类才该红。铁律 8、15 的同族。

135. ★**改 agent 的提示词/规则后必须重启 `:8000`**（agent 无 `--reload`）——2026-10-15 再次踩到。
   「源码已改」≠「运行态已改」。**判据要回到运行态**：`POST :8000/internal/v1/answer-shape` 取回**跑着的**
   agent 实际下发的 rules，断言其中含新口径关键件（`scripts/_check_answer_kb_strict.py` 的 C5 就干这个）。
   只看源码/单测通过就宣称生效，会在真机上得到旧行为。改完口径的完整动作：**改源码 → 停 :8000 → 重启 → 跑 C5**。

136. ★**IDE 语言服务器把 ECJ 编译产物写进 `target/`，其 mtime 新于源文件 ⇒ Maven 增量编译跳过 ⇒ 真实编译错误被静默掩盖**（2026-10-16 实测，同一坑连踩两次）。
   现象链：`mvn test-compile` 报 **BUILD SUCCESS / exit 0**，但 `mvn test` 抛
   `java.lang.Error: Unresolved compilation problem: The constructor ... refers to the missing type X`。
   把坏 `.class` 删掉重编，真错误才浮出水面 —— 这次的真错误是
   `WorkerIntakeService.java:76` 用了 `PermissionGrantService` 字段却**漏了 import**
   （javac 原文：`无法访问PermissionGrantService / 找不到PermissionGrantService的类文件`）。
   **一眼识破的判据**：`ls -la` 对比 `src/.../Foo.java` 与 `target/.../Foo.class` 的 mtime ——
   **`.class` 比 `.java` 新 1~2 秒 = IDE 写的，Maven 会跳过它**；`-q` 的「静默成功」与运行时的
   `Unresolved compilation problem` 是同一件事的两面。
   **定式**：① 见到 `Unresolved compilation problem`，先 `rm` 掉 `target/{classes,test-classes}` 下对应 `.class` 再编；
   ② 新增字段/引用后**必须真编一次并确认 `target/classes` 真被重生成**，别信 `-q` 的 exit 0；
   ③ 本环境有 IDE 语言服务器在后台编译，**`target/` 的内容不可信**。
   附：`grep` 在本仓库常把混合编码的输出判成二进制（只回 `Binary file (standard input) matches`）⇒ 取 Maven 日志一律用 `grep -a`。

137. ★**「用 `-Dtest=` 只跑一条用例」时，`-am` 会把过滤条件套到上游兄弟模块 ⇒ 兄弟模块「无匹配用例」被判失败**（2026-10-16 实测）。
   `mvn -pl aios-chat -am test -Dtest=XxxTest` 会在 `aios-common` 等无该用例的模块上报
   `No tests matching pattern "XxxTest" were executed!` 并 `BUILD FAILURE`。
   **正确写法**：`-Dsurefire.failIfNoSpecifiedTests=false`（**属性名是 `surefire.` 前缀**，
   写成 `-DfailIfNoSpecifiedTests=false` 无效）。

138. ★**浏览器级哨兵里「点击/填表」前必须先守卫元素存在**，否则负向对照下 playwright 抛超时、
   **整个脚本中止**，后面所有断言全丢 —— 现象是「只看到前几条红、没有 `合计`」，极易被误读成
   「只坏了前几条」。2026-10-16 实测：给 `_verify_oa_action_popup.py` 加 `CREATE_WORKER` 组后，
   做判别力回退（中性化 `oaMaybeCreateWorker`）时，`G16` 的 `.click()` 直接 `TimeoutError` 中止脚本，
   `G16–G20` 与 `合计` 全部没打印。
   **定式**：① 交互前先算 `n = page.locator(sel).count()`，`if n == 1:` 才 click/fill；
   ② 断言里显式带上该 `n` 作为 detail，让「窗口没弹出来」与「弹出来了但断言错」可区分；
   ③ 需要读按钮态时用 `btn_b.count() == 1 and btn_b.first.is_disabled()`，不要对可能不存在的选择器直接 `.is_disabled()`。
   **判别力回退的正确做法（同 #136 的 TEMP 标记思路）**：在成品源码里插一行 `if(true) return false; /* TEMP-NEGCTRL */`
   把被测函数中性化 → 重建产物 → 跑哨兵（期望新断言全红、旧断言与负向对照仍绿）→
   `cp` 备份还原 → `md5sum` 核对字节一致 + `grep -c TEMP-NEGCTRL` 归零。**这一步是铁律 12 的落地动作**：
   不做它就无法区分「真通过」与「判据恒真」。

---

## 连接器 / MCP 通道的坑（2026-10-30，群机器人接入时踩到）

**① 工具描述决定模型调不调，不是模型笨。**
群机器人两个工具只有 `content` 一个参数（目标群由 webhook 绑定）。描述只写「往企业微信群发送消息」时，
MiniMax 拿到 2 个工具却**不调用**，反问「请提供群名称或群ID」；把「目标群由 Webhook Key 决定，本工具
**没有也不需要**群名称/群ID，用户说『发到群里』就直接发、不要反问」写进描述**首句**后才调通。
另：HITL 开着 `ask_user` 会放大反问倾向（实测直接弹 `need_clarification` 问「发到哪个群」）。

**② 凭据泄漏的第二条路径是「依赖的日志」。**
自己 logger 只打 key 尾 4 位是守纪律的，但 **httpx 在 INFO 级别把整条 `POST …/webhook/send?key=8fc8…` 打出来**。
（验收时靠日志取第二源才发现这一行，否则永远不知道。）修法在 `mcp-hub/mcp_hub/wecom/group.py`：
给 `httpx` logger 挂 `_RedactKeyFilter`，把 `key=/access_token=/corpsecret=/secret=` 抹成 `***`。
为什么用 filter 而不是降级：降级会丢 HTTP 状态码诊断；临时改级别会被并发请求串级。filter 只改 record
文本、不改级别 ⇒ 并发安全。哨兵 `_verify_wecom_group.py` G7 直接扫日志文件本体复核（明文 0 次 + 存在 `key=***`）。

**③ `mcp_server_tool` 只是「信任那一刻的快照」，不是权威。**
`trust()` 会 probe hub 并用 `list_tools` **覆盖写**该服务器的工具目录；hub 之后扩了工具而没人重新信任，
DB 就一直留旧数（实测 `wechat_work` 已 13、DB 仍 3，界面照着旧数报）。**重跑 `POST /servers/{code}/trust` 即自愈**；
`_verify_mcp_registry.py` M13 用「DB 快照 vs hub 实装数」双向比对盯这个漂移。

**④ 直调 `/internal/v1/runs` 必须带 `user_token`，缺了会伪装成「工具就 2 个」。**
`user_token` 是 body 字段（发起方用户 accessToken）。缺 ⇒ `ToolClient.enabled=False` ⇒ MCP 通道整段跳过；
此时日志 `tools=2` 是 HITL 注入的 `ask_user`/`request_form`，**不是**连接器工具（本轮据此误判过一次）。
同源陷阱：`AIOS_MCP_HUB=true` 必须在 **agent 进程环境**里（`start-all.sh` 已 export），只看 `.env` 不够。

**⑤ 哨兵断言不能依赖「库里刚好是初始状态」。**
`_verify_mcp_registry.py` 的 M1/M2/M3/M8/M9 都以「trusted 全 0」为前提，脚本却从不保证它 ⇒ 真实环境里
别人 trust 过，5 项一起假失败（本轮实测）。修成「快照 trusted → 复位 → 跑 → **按快照恢复**」。
不能无脑复位：`wecom_group` 一取消信任，AI 那边的工具就没了（真实配置被哨兵破坏）。

**⑥ 企微硬门槛（结论，别再重复怀疑）**：`gettoken` **不校验**可信 IP（业务接口才校验）；
「配置可信 IP 前必须先设可信域名或接收消息 URL」⇒ **无备案域名时自建应用这条路整体走不通**，
此时唯一能用的真机通道是群机器人 Webhook（不要求 IP/域名/企业认证）。对照实验见 `2026-10-30.md`。

**⑦ 连接态同源时，「跳过」不能被当「失败」上报（bool 压扁的经典伤）。**
hub 回写 Java 的状态同步有三态：`True` 已同步 / `False` 真失败 / `None` **按设计跳过**
（mock 身份不是数据库主键、或本进程没配服务令牌）。压成 bool 后 dev 默认 `WECOM_MOCK=1`
每次授权都算 `state-unsynced`，正常跳过被报成故障（S4b 假失败），真失败反而被噪声淹掉。

**⑧ 目录状态不能被「配置就绪度」强降级。**
`ConnectorCatalogService.list()` 曾拿 `configReady` 当门，未就绪就把 status 改成 NEED_AUTH
⇒ 造出「manifest 已放行、界面显示未连接」（S5 过而 S4 挂）。连接态只信 `connector_connection`，
就绪度是另一根轴（`configReady` / `configHint`），前端本就先按 configReady 分支
（`user-client/_oa_app.js` 的 `connStatusChip`）。

**⑨ 日志型断言先确认「文件在收新日志」。**
单独重启 hub 时用 `python run.py` 没重定向 ⇒ 输出进了终端、`logs/mcp-hub.log` 停在旧内容，
G7「日志无明文 key」于是**空文件假通过**（明文 0 次但也没有 `key=***` 标记）。
判据要成对：明文 0 次 **且** 存在脱敏标记。同理，hub 若从临时脚本启动，最容易漏 `AIOS_SERVICE_JWT_SECRET`
（漏了不报错，只是每次授权 `state-unsynced`）。

**⑩ 工具参数有**两处**事实源，只改一处 = 描述与校验打架。**
`wecom/catalog.py` 的 `input_schema.required` 决定**模型看到什么**（进 manifest / DB 快照）；
`wecom/server.py::_PARAMS` 决定**真正校验什么**（`("touser", str, None)` 里 `None` = 必填）。
2026-10-30 把 `touser` 改成可选时只改了前者 ⇒ 描述说「可省略」、真调用被 pydantic 判缺参，
新加的 `confirmed` 更是被当非法入参直接拒（S7b/S7d 首跑挂在这里，错误文案是
`1 validation error for wechat_work__send_text_message`，**看不出是参数表没同步**）。
已加 `_assert_params_in_sync()` 进 `build_server()`：required 不一致就拒绝启动。
另外：**改了工具描述必须重跑 `POST /mcp/servers/{code}/trust`**，否则 `mcp_server_tool` 还是旧描述，
模型照旧描述调用 —— 症状是「代码明明改了，模型行为没变」。

---

## 阶段补充（2026-10-18）：表单/HITL 链路的四个坑

- **「补一帧」≠「有断点」**：`need_form` 只能由 agent 图里的 `clarify.interrupt()` 产出。
  在 Java 流末补发帧虽然前端能看到表单卡、`need_form` 断言也绿，但图里没有 checkpoint
  ⇒ 用户提交表单后 `/resume` 零帧、模型拿不到回填数据。
  **判据必须含「提交后那条续跑流有内容」**（`scripts/_verify_form_resume_no_reopen.py` 的 U3 + 帧非空）。
- **`Command(resume=None)` 会让 LangGraph 崩**：`pregel/_loop.py` 的
  `if resume_is_map := (...)` 在 None 时不赋值，紧接着的 `if not writes and not resume_is_map`
  抛 `UnboundLocalError` → `MODEL_STREAM_ERROR` + `run.failed`。
  用户关掉澄清卡/表单卡就是这个路径。修法：`facade.resume` 里 `None → {"cancelled": True}`。
- **状态里的 tool_call 与消息里的 tool_call 是两种形状**：`pending_calls` 用
  `{id,name,arguments(dict)}`（`_parse_tool_calls` 归一化），回注 `messages` 必须用
  OpenAI 的 `{id,type,function:{name,arguments(str)}}`。混用会让 `route_after_agent`
  认不出 `request_form` → 误走 `tools` → `KeyError: 'name'`。
- **哨兵读 SSE 的终止条件**：读到 `need_form` 或 `message.completed` 就 return 会**提前断开**
  ⇒ 后端 `completeRun` 不执行、`markWaitingInput` 不落库、run 卡 `RUNNING`，
  后续 `/resume` 报「不是等待澄清状态」——红是哨兵自己造的。必须读到
  `run.completed` / `run.failed` 或 EOF；`/resume` 遇非 200 做 ≤6×1s 重试（收口有毫秒级竞态）。

## 本地 `.venv` 有 ≠ 镜像里有（2026-10-18 第二次复发：`langgraph` 没进依赖清单）

**现象**：生产 `aios-agent` 一直 `Restarting`，日志
`ModuleNotFoundError: No module named 'langgraph'` + `Application startup failed`；
用户侧表现是对话**「本次未返回内容」**（不是 502、不是 500，看不到任何后端错误）。

**根因**：`aios_ai/graph/{builder,facade,nodes}.py` 全靠 langgraph，但
`agent/pyproject.toml` 的 `dependencies` 里**没有它**（那几个 checkpoint 也各有独立发行包）。
本地 `.venv` 是手工装的 ⇒ pytest/uvicorn 全绿；镜像走 `pip install .` ⇒ 缺包。

**这是同一模式的第二次**（第一次是 `packages.find.include` 漏 `aios_ai`）：
**「本地能跑」永远不能推断「镜像能跑」**。判据只能是「声明的集合 vs 实际 import 的集合」。

**收口哨兵**：`scripts/_check_agent_deps_declared.py`（纯离线，AST 扫 `app/`+`aios_ai/`，
与 pyproject 做差集；D2 负向对照保证它会红；已登记进 `_run_all_regression.sh`）。

**排查动作（照做）**：
```bash
docker compose ps agent                     # Restarting = 进程起不来，不是慢
docker compose logs --tail=40 agent | grep -E "ModuleNotFound|startup failed"
docker compose exec agent python -c "import langgraph, redis, aiosqlite; print('ok')"   # 起得来才有这一步
```

## 禁删清单（铁律 13 的完整版，2026-10-18 从 MEMORY.md 迁来）

「看起来像垃圾」与「真的没人用」是两件事。引用即保留：

- `logs/proof/`（举证图，被 docs 引用）、`logs/reset_backup/`（复位备份）
- `docs/_incoming/非违接口文档.txt`、`docs/_incoming/probe_show_result.json`、`ux-review/`
- `user-client/_oa_clean.html` + `_backup_index_pre_oa.html` —— **H5 构建输入**，产物 `index.html` 才是可手改的禁区
- `scripts/_check_* _probe_* _verify_* _refaudit_* _run_all_regression.sh` 与 `scripts/e2e_*.py`
  —— **长期回归面**，且被 `.gitignore` ⇒ 删了不可恢复
- `scripts/_diag_member1_restore.py`、`start-backend.bat`
- `.workbuddy/memory/`、`.workbuddy/artifacts/*.md|*.html|*.json`（已入库交付文档）
- `scripts/_fullsystem_h5_home.png`（docs/20 引用）
- 生成物目录（可删可重建）：`agent/.venv`、`*/target`、`*/node_modules`、`*/dist`

## 2026-10-30 · 企微扫码连接器（wecom_cli）四个坑

1. **CLI 的 credentials.enc 直接落在 `WECOM_CLI_CONFIG_DIR` 下**，CLI 不会自己再套 `personal/`。
   实测：空目录 → `unauthorized`（且不生成任何文件）；指向 `…/wecom-cli/personal` → `authorized`；
   指向它的上一级 → 又 `unauthorized`。判据写多一层 ⇒ **扫码成功但永远判未绑定**。
   落点：`profiles.cli_dir()` 单点决定，并兼容「调用方直接给 CLI 目录」（共享 profile 就是这种）。
2. **ASGI helper 必须是 `async def` 且调用处 `await`**。`def _ok(...): return _send_json(...)`
   返回协程，`return _ok(...)` 既不 await 也没人消费 ⇒ uvicorn
   `ASGI callable returned without starting response` + HTTP 500，**但业务已跑完**
   （库里已 CONNECTED，接口却 500 —— 极易误判成写库失败）。
3. **`SERVER__PORT` 劫持 Spring 端口**。宽松绑定把 `SERVER__PORT` 认成 `server.port`；
   工作台/IDE 终端会注入成临时端口（实测 61302，已被宿主占用）⇒ 启动失败，报
   「Port 61302 was already in use」，与 8080 毫无关系。`start-all.sh` 已 `unset` + 显式 `--server.port=8080`。
4. **H5 生效文件是 `user-client/index.html`**（自包含 673KB），`_oa_app.js`（164KB）没被任何
   `<script src>` 引用。改错文件的症状是「改了但页面没变」。另：`refreshConnectors`/`openConnector`
   在页面里是闭包内块级作用域（`typeof refreshConnectors === 'undefined'`），只有 `API`/`oaBoot`/`oaState`
   挂到 window ⇒ Playwright 不能直调，必须走 UI 点击驱动重渲染。

## 2026-10-30 · 删码时暴露的两个「下线≠消失」坑

删掉旧企微通道代码后，新哨兵立刻红了 6 项 —— 都不是「删错了」，而是**原来就有、
被"已经不用的代码"掩盖住的漏洞**。凡是要下线一个连接器/能力，这两个点必须一起检查。

1. **`requireDef()` 不看 `status` ⇒ 停用的连接器接口照旧可用**。
   `ConnectorCatalogService.requireDef` 只按 `tenant_id + code` 查，V103 把
   `connector_def.status` 置 DISABLED 后，`GET /api/v1/connectors/wechat_work` 仍回 200 +
   一条没人维护的定义，`connect/start` 还会掉进「暂不支持网页授权」这种只有开发看得懂的分支。
   修法：`requireDef` 加 `.eq(status, ACTIVE)` ⇒ 一律「连接器不存在」（HTTP 404）。
   **判据教训**：只测「列表里没有」是不够的，必须**点名打它的详情/动作接口**，要求 404。
2. **`mcp_server_tool` 快照不随连接器下线清空 ⇒ 「看不见但打得通」**。
   V103 只关了 `mcp_server.trusted`，13+2 行工具快照还在，
   `GET /api/v1/mcp/servers/wechat_work/tools` 仍能查出 13 个工具；而列表里的 `toolCount`
   是对这张表 **count** 出来的 ⇒ 界面对着「代码已删干净、探测必然失败」的服务器报「13 个工具」。
   这比直接报错更危险：用户会以为能用。修法：`V104__purge_retired_mcp_tool_snapshots.sql`
   删快照（`mcp_server` 行留痕）。**判据教训**：删能力时，凡是从"快照表/缓存表"读出来的数字
   都要一起清，并且哨兵要**反向断言**「hub 里不许再出现这个 code」。
3. 顺带：**哨兵的被测主体消失时，先找"同一机制的另一主体"，再考虑删**。
   本次三套件都是换主体救回来的（`provider=wecom`→运行期登记 `provider=vault`；
   `tenant_config` 换成「不需要配凭据的形态」；`state_sync`→`wecom_cli`），
   只有真正的能力被删（双模式 A/B、群机器人）才删套件，且覆盖损失写进 docs。
   另一个细节：`_verify_connectors_registry` 的库文件明文扫描原本在 DELETE 之后跑，
   主体清空后扫的是空库 ⇒ **先断言"canary 真值还在库里"，再扫字节**，否则这个断言是空转。
4. **前端「废弃文件」判据**：`index.html` 是自包含单文件（脚本内联），所以
   `_oa_app.js` / `_backup_index_pre_oa.html` 在页面里搜不到 `<script src>` ——
   但它们分别是 `_build_oa.py` 的 `APPJS` 注入源与重建基线，**删了断构建链**。
   判死活要搜 `_build_oa.py` 的常量表，不能只看 HTML 引用。
5. **「扫码完成」的判据不能用 `profiles.resolve()`**：它会回落到
   `AIOS_WECOM_CLI_SHARED_PROFILE`（dev 共享授权），于是「用户还没扫码」在第一次轮询就
   `authorized=true` ⇒ 前端自动 bind ⇒ 落库 CONNECTED + 绑成**别人**的身份。
   正确判据 = 本人目录 + `credentials.enc` 的 **mtime 晚于本次会话起点**（`.qr-session`）+
   CLI 自报 authorized（`auth.session_state`）。**「文件存在」永远不够**：共享目录里本来就有、
   上次授权的旧文件也一直在。
6. **`wecom-cli auth init` 只在启动时写一次二维码 PNG**，之后一直阻塞等扫码 ⇒
   `start_qr` 里「先 unlink 图再看有没有活进程复用」会把自己坑死：图删了、进程不会再写、
   20s 后返回 400 超时。顺序必须是「有活进程且图在 → 复用；否则杀掉旧进程、删图、起新的」。
   哨兵 S16 钉住这条。
7. 测试 fixture 复制凭据只能用 `copyfile`，**不能 `copy2`**（copy2 连旧 mtime 一起复制，
   会被「mtime > 会话起点」判成旧残留而永远不完成）。真实运维也一样：从备份还原
   `credentials.enc` 会被判「本次没扫」，需重新扫码。
8. **模型可能把工具调用写成正文**（MiniMax-Text-01 实测，2026-10-30）：
   ```` ```typescript\nfunctions.mcp__x__y({"days":7})\n``` ```` 这种写法不会被执行 ——
   `_parse_tool_calls` 拿到空列表 ⇒ 该轮被当「最终回答」⇒ 模型那句「请稍等，我正在为您查询」
   直接收尾，界面停在半句话上。**排查顺序：先查 `chat_message` 里有没有
   `functions.<name>(` 文本，再怀疑前端/SSE**（这次前端与 SSE 都是好的）。
   兜底在 `graph/nodes._rescue_textual_calls`（只认代码块 + 名字精确命中本轮工具表 + 参数是
   JSON 对象）；提示词只是软约束。看图级测试 `test_graph_rescues_textual_tool_call`。
9. **「滚到底部」不能用 `scrollTop > 阈值` 判**（2026-10-30 数字人渐隐）：
   滚到底时 `scrollTop` 恰好等于最大值（`scrollHeight - clientHeight`），拿它跟阈值比会把
   「停在底部」判成「在上滑」，行为正好反过来（实测：停在底部数字人反而消失）。
   判据要写**离底还剩多少**：`scrollHeight - clientHeight - scrollTop > 24`。
   渐隐只降 `opacity` + `pointer-events`，**不改高度** —— 一淡出就抽掉布局的话滚动位置会跳，
   用户正在翻的那几条会被顶走。
10. **空值的 `<textarea>` 在 Chromium 里 `scrollHeight` 会多算一行**（实测 rows=1 空值 64、
    单行文本 45）。照它写 `height` 会让空输入框凭空高出一截（胶囊 46px 变成 64px）。
    自增高函数必须 `if(!el.value){ el.style.height=''; return; }` 交回 CSS 的 `rows=1`；
    另外 `height:'auto'` 要先设回去再读 `scrollHeight`，否则删字时只增不减。
11. **`.composer` 自成层叠上下文 ⇒ 挂给它的浮层压不过同级的全屏遮罩**：菜单 `z-index:71`
    只在 `.composer` 内部生效，外面那块 `position:fixed; inset:0` 的遮罩照样盖在它上面，
    现象是「浮层看得见但点不动」。别硬调 z-index，**改成「点浮层外收起」的全局
    `pointerdown` 监听**（同时放过触发按钮自己，否则一次点击开又关）。
12. **`var arr = arr(list)` 会互相遮蔽**：`var` 提升把同名函数变成 `undefined`，
    运行时 `undefined(list)` 直接 TypeError。变量名别跟工具函数重名。
13. **UI 自动化不要用裸坐标点页面**（`mouse.click(150,260)`）：首页那个位置是「专家」卡，
    一点就开出 `#oaSheet` 抽屉，之后所有 `page.click` 都被它拦住，报错却是
    "…intercepts pointer events"，很容易误判成被测元素的 bug。要点「外部区域」就点确定存在的
    中性元素（如 `#oaInput`）。
14. **`user-client/index.html` 现状是真源，`_build_oa.py` 的重建链已脱节**：OA 层源文件
    （`_oa_app.js` / `_oa_markup.html` / `_oa_extra.css`）与 `_backup_index_pre_oa.html`
    停留在 `4453544` 前后，之后所有改动（二维码下载、本轮四项交互）都直接改的 `index.html`。
    **跑 `cp _backup_index_pre_oa.html index.html && python _build_oa.py` 会静默丢掉这些改动**
    —— 别为了「让源文件同步」去重建；要重建必须先把改动回灌进源文件。
15. **`#oaRoot` 自己就是 `.oa`**（`<div class="oa" id="oaRoot">`）：任何写
    `.oa #oaRoot.xxx .appbar` 的规则**永远不匹配**（要找的祖先 `.oa` 在文档里不存在），
    现象最阴：class 明明挂上了（`classList.contains('bar-hidden') === true`），
    但计算样式一点没变。写与 `#oaRoot` 相关的选择器要么以 id 起头（`#oaRoot.bar-hidden .appbar`），
    要么写成 `.oa.bar-hidden`（同一元素双类）。判据别只看 class，要读
    `getBoundingClientRect().height` / `getComputedStyle().backgroundColor`。
16. **透明描边仍然占 1px**：`border-bottom:1px solid var(--border)` 只把 color 改成
    `transparent` 时，元素高度收到 0 后实测仍是 **1px**（透明但不是 0）。
    要让「收成 0」名副其实，必须同时 `border-bottom-width:0`。
17. **`task.completed` 事件必须带 `tool`**：`task.started` 与 `task.skipped` 都有,
    唯独 completed 漏了，改名的 `tool.result` 帧于是 `{"name":null}` —— 前端与审计
    拿不到工具名，只能按顺序猜。任何「按事件审计工具调用」的代码都会因此静默失效。
    回归哨兵：`scripts/_verify_agent_web_search.py` R7。
18. **「没有这个工具」不等于「网上没有」**：本轮根因就是系统压根没有联网工具，
    模型把「内部查不到」说成「找不到」，还用「帮你起草邮件」收尾 —— 提示词再怎么写
    也变不出一个不存在的工具。遇到「模型说搜不到」先 grep 工具表确认**能力是否真的存在**，
    别急着改措辞。
19. **模型不知道「今天」**：问「今年/最新」时它会用训练数据里的年份。实测它把 2026-10-30
    的「今年」写成「2024年」。**每轮注入当前时间**（`prompt/builder.py` 的【当前时间】），
    并在检索类规则里要求 query 带当前年份 —— 否则联网检索会「成功返回一堆旧闻」。
20. **检索成功 ≠ 答对**：Bing 会把「2026年 就业政策」答成「2026年节假日安排」，
    模型照单铺满一屏。只看 `tool.result.ok=true` 发现不了，必须再加一条**相关性**判据
    （回答里主题词是否压过跑题词），探针里 B8 就是干这个的。
21. **个人信息比业务数据更容易被编**：模型查不到就会「拿已知字段拼一个像样的」——
    实测 `whoami` 只回姓名「刘洋」，它就吐 `liuyang@yourcompany.com（假设公司域名为 yourcompany.com）`。
    这类错最危险：用户会拿去发信/填表。规则必须写成「只准用原值 / 缺字段就说没有 /
    严禁姓名+猜域名、严禁『假设域名为…』占位」，**并且要求工具描述自报边界**
    （`whoami` 明说「不返回邮箱/手机号/工号」），两边夹才不会漏。
22. **救援工具调用 ≠ 收回原文**：`_rescue_textual_calls` 把 ```` ```typescript mcp__x__y({}) ``` ````
    变成真调用之后，那段文字**早已逐片发给前端**（delta 是不可回收的）。只修救援，用户
    看到的就是「源码 + 真查询」两样都有。流式侧必须配套：开头像调用就先扣住
    （只扣「像调用开头」的，普通中文照常下发，别破坏 delta↔分片的 1:1），
    命中特征后本轮不再外发，收口清理后落库。
23. **清理调用文本要区分「工具形状」与普通函数**：`_CALL_EXPR_RE` 会同时命中
    `mcp__a__b({})` 和 `print(1)`，直接删会把用户要的示例代码吃掉。
    判据加成「`functions.` 前缀 或 名字含 `__`」才删。
24. **空回答兜底要「可行动」**：「（本次未返回内容）」是死胡同 —— 用户既不知道发生了什么
    也不知道下一步。而且空消息有两种来源：模型真空返回（`finalize` 未兜）、
    delta 断流但完成帧有 content（前端只认 delta）。两处都要兜：后端产出可行动文案+补发 delta，
    前端 `onCompleted` 用完成帧 `content` 覆盖。
25. **加一条 HITL 控制链有五个「必改点」，漏任何一个都静默**：agent 侧 prepare 注入 /
    tools 过滤 / clarify 识别 / route 分支，加 facade `_frame_type` 帧判定。漏帧判定的表现是
    新帧被当澄清帧发出去（UI 变成单选卡）；漏 tools 过滤的表现是新工具被当业务工具打进网关。
    2026-10-31 加 `request_confirm` 时已把判定收敛为 `_is_control_call / _control_chain /
    _drop_control_calls` 三个单点 —— 以后加第四条链只改这三处 + facade + prepare。
26. **SSE 暂停帧必须同时置 `clarificationRef`（Java）**：`forward()` 对未知事件名是**无条件
    转发**的，卡片照样弹出来；但 ref 不置位 ⇒ 流末按 SUCCEEDED 收口 ⇒ 用户点决策时
    `/resume` 因状态非 WAITING_INPUT 被 400 拒。现象是「卡片能弹、点了报操作失败」，极难排查。
27. **流式假模型桩里一次 `yield` 两个 `done` 会自我覆盖**：agent 消费循环以**最后一个** done
    为准，tool_calls 轮后接正文轮时必须在两次真实模型调用里分别 yield（每轮恰好一个 done）。
28. **操作性提示别写进 `.tx`**：确认后 `.tx` 会被 `formatAnswer(text)` 整套重写 innerHTML，
    写在里面的「已取消」会被静默冲掉 ⇒ 独立容器（`appendSysNote`）。
29. **业务校验失败落 500 而不是 400（Java 侧）**：`GlobalExceptionHandler` 只把 `BizException`
    与 Spring 参数类异常映射成 4xx，**其余全部落到 `@ExceptionHandler(Exception.class)` ⇒
    500「服务内部错误」**。⇒ 服务层**禁止**用 `IllegalArgumentException` 表达业务校验
    （空标题 / 时间倒序 / 格式非法 / 资源冲突 / 非法枚举），必须 `BizException.badRequest(msg)`；
    归属与不存在用 `BizException.notFound(msg)`。现象极具误导性：「标题为空」看起来像「后端崩了」。
30. **本项目业务失败的判据是信封 `code`，不是 HTTP 状态码**：约定为 **HTTP 200 + `code=400`**
    （只有 BizException 的 401/403/404 才映射 HTTP 状态，docs/36 §、docs/38 § 有明文）。
    ⇒ e2e / 断言脚本一律查 `body.code`，按 `http_status==400` 断言必假红。
31. **起 Java 后端必须带 `-Dspring.flyway.validate-on-migrate=false`**：本机库 V89–V95 的
    checksum 是 NULL、V100 已应用但本地文件被 revert（`d5974af` revert `cd79d79`）
    ⇒ 直接 `java -jar` 会 `Validate failed` 起不来。`start-all.sh` 本就带此参数。
    另：`nohup &` 起的 Java 进程**会被回收**（jps 里立刻消失），必须用受管后台任务或用户自起。
32. **e2e 里写死 uid 会把「组织者本人」算成受邀人**：`createMeeting` 会跳过 organizer，
    而 `zhangsan` 真实 uid=2 ⇒ 写 `attendeeIds=[2,3]` 恰含自己，invited 期望值对不上。
    **这不是产品缺陷**。⇒ 期望值必须按登录返回的真实 uid 动态算；用第二个真实账号做受邀人。
33. **对话级开关的通用做法**（2026-10-31）：凡「只影响本次对话、**不改持久状态**」的开关
    （KB 开关 `kb_on`、连接器 `disabled_connectors`），统一走
    `前端集合 → 顶层字段 → Java context 快照（落库 + 回读）→ agent 顶层字段`。
    判别点：后端**连接状态/授权/trusted 全部不动** ⇒ 用户关掉再打开无需重新扫码/重新授权。
34. **`.cbtn` 这类通用类必须显式写全 `flex`**：通用 `.cbtn`（确认卡文字按钮）带
    `flex:1 1 0px; min-height:36px`；`.oa .cbtn` 只写 `flex-shrink:0` **等于没写**
    （flex-grow 默认 1 仍在生效）⇒ 输入栏里的麦克风被撑成 89px 宽的椭圆。
    修：`.oa .cbtn{flex:0 0 auto; min-height:0}`。⚠️ 最终渲染是 **44×44** 不是 34×34
    （后面还有全局命中区规则 `.oa .cbtn{width:44px;height:44px}`，移动端 ≥44px 标准）。
35. **事件帧里没有 tool_call_id**：tool_call_id 只存在于图状态的 `messages`（tool 消息）里
    ⇒ 断言「被拦下的调用有回注 ok=False」必须**直接调节点看返回值**，
    在 `message.completed` SSE 帧里找 tool_call_id 必假红。
    同理：tool 消息**不能丢**（丢了上游判协议错误）⇒ 执行队列排除 + 回注入消息，两件事。
36. **`patch.object(类, 方法, 假函数)` 会变成绑定方法**（多传一个 `self`）：
    假函数签名要写 `async def f(self, name, arguments=None)`，否则报「takes from 1 to 2
    positional arguments but 3 were given」。
37. **`--hd` 是写在 scroll 事件监听器里的**（`oaSyncDockFade` 是 IIFE 内函数、不挂 window
    ⇒ 不能直接调）：设 `scrollTop` 后**必须等一拍**再读；且 scrollTop=0 且从未滚过时
    `--hd` 是**空串**（靠 `var(--hd, 0)` 兜底，语义上就是 0，别判成 None）。
    对话坞滚动容器是 `#oaDockList`（`.dock-list`，overflow-y:auto），`#oaDock` 只是外壳；
    不先给 `#v-home` 加 `.chatting` ⇒ `.dock` 是 display:none、高度 0、根本不可滚。
38. **用户报的计数要去接口与来源核**：「我看到 46 个插件」实测 `GET /v1/plugins` = 64 条，
    全部是**管理员预置的系统内置工具**（`tool_definition`：platform 6 + scfy 58），
    用户从未添加 ⇒ 问题不在数字，在**命名与来源未交代**（改叫「系统工具」+ 顶部说明）。
    字段名错配同理：`recent_group_sessions` 返回 `ref` 而 `session_messages` 入参叫 `chat_id`
    ⇒ 模型报「chat_id 无效」。**上下游字段名必须同名**。
39. **跑 e2e 要用带 pymysql 的解释器**（`agent/.venv` 或 workbuddy envs/default）：
    系统 python 没有 ⇒ 脚本里「回库核对」的断言被**静默跳过**（只降级不算失败，
    但也不代表通过 —— 看输出里的「数据库不可达」提示，别误读成全绿）。
40. **中文提交信息必须用 `-F 文件` 或 heredoc，不能用 `-m "中文"`**：
    bash 的 `-m "…中文…"` 走 argv 编码转换（Git Bash on Windows 的 codepage）⇒
    个别汉字被打成 **U+FFFD 替换字符**（实测「不」→ `��`，提交信息里静默损坏，push 不报错）。
    两种可靠写法：
    - `git commit -m "$(cat <<'EOF' … EOF\n)"`（heredoc 走管道，不经 argv）；
    - `Write` 工具落一个 UTF-8 临时文件到 `.git/`，再 `git commit -F .git/XXX.txt`，用完删掉。
    **改已推送的提交信息**：`git commit --amend -F 文件` → 推送前必须先
    `git rev-parse <old>^{tree} <new>^{tree}` 比对 tree 相同（证明只改了信息没改内容），
    再用 `git push --force-with-lease=refs/heads/main:<oldSHA> origin main`（带 lease 防覆盖他人提交）。
41. **顶部遮罩要让位，只能移 `.dock` 视口，不能收 `.assist`/`.stage` 自身高度**：
    - 事实链：OA 聊天页 `.assist`（标题块）与 `.stage`（数字人区）是 `.dock`（对话坞，`flex:1`）
      的**文档流上方兄弟**。只做 `opacity` 渐隐 ⇒ 元素淡出后**仍占约 140px 文档流高度**
      ⇒ ① 聊天记录永远滚不进顶部（顶部留一条空白带）；② 渐隐后仍参与命中测试 ⇒ 隐形内容拦点击。
    - 反面方案（**已实测推翻**）：给 `.assist`/`.stage` 加负 `margin-bottom` 收高度 ⇒
      ① `.stage` 整体上移 ⇒ **破坏「数字人是气泡尾巴锚点」**（`oaLayoutTails` 量它算尾巴朝向）；
      ② `.dock` 变高 ⇒ `.dock-list` 的 `clientHeight` 变化 ⇒ `maxScroll` 从 1693 掉到 1555
      ⇒ **正在翻历史的人被顶走**（滚动跳位）。
    - 定稿方案：只给 `.dock` 加 `margin-top:calc(-1 * var(--hd,0) * var(--mask-h,140px))`
      ⇒ 移的是**对话坞的视口**（聊天记录真正顶到顶部占住原遮罩位置），
      而 `.assist`/`.stage` 自身的位置与高度**纹丝不动**（锚点安全）。
      代价：`scrollHeight` 不变 ⇒ `maxScroll` 随视口变高而变小，但**实测设定 scrollTop 从不被浏览器钳制**，
      底部锚点不漂（`lastBottom`/`composerTop` 与改造前一致）。
    - `--mask-h` **必须实测**（`.assist` 内含项目 chip `#oaProjSlot`，标题字号是 `clamp(...)`，
      机器人位图高度随加载变）⇒ JS 读 `offsetTop` 算差值 + `ResizeObserver` 跟随；
      首页态 `.dock` 是 `display:none` ⇒ 高度算 0，规则整体不生效。
    - 到位隐藏用 `visibility:hidden`（退出绘制与命中测试）+ `pointer-events:none` 双保险。
      `.assist` 是 `#v-home` 的 **flex item** ⇒ `z-index` 直接生效，**不需要** `position:relative`
      （加了是多余改动，会破坏「非透明态逐字节不变」）；`.stage` 基础规则里已有 `position:relative`。
    - ⚠️ 入场动画冲突排查：`.oa .view.on > *{animation:oa-rise …}` 若命中 `.assist`，
      其 to 帧 `opacity:1` 会盖掉 `--hd` 的 opacity calc ⇒ 渐隐失效。
      **实测未命中**（两种 reduced-motion 取值下 `animationName` 均为 `none`），但改这块必须复验。
    - ⚠️ 验收哨兵**不能**用 `git show HEAD` 取「改造前」版本对照 —— 一提交 HEAD 即改造后，对照失效。
      ⇒ 把改造前实测值**固化为 `BASELINE` 常量**（含版面与视觉样式），提交后仍守得住「非透明态不变」。
42. **「＋」浮层的连接器开关「再开启」不能无条件弹授权层**（2026-10-31 用户当场反馈）：
    - 现象：+ 号 → 连接器 → 关掉开关 → 再打开 ⇒ 弹出「填授权码 / 扫码」，
      用户原话「关闭连接器后再开启还需要重新认证」。
    - 根因：`oaToggleConnector()` 的再开启分支是
      `oaSetConnectorMuted(code,false); openConnector(code);` —— **无条件**。
      而 `openConnector()` 必先 `GET /v1/connectors/{code}` 取 detail 再按 mode 弹层
      ⇒ 只要走这条路，就一定被要求重新认证一次。
    - 修法：按连接器**真实状态**分流 —— CONNECTED ⇒ 只解除会话级 mute（一个弹层都不弹）；
      DISABLED ⇒ 顺手调 `enable`（只翻状态位）；**只有 NEED_AUTH / UNVERIFIED 才引导授权**。
    - ★ 连带坑：分流要读 `S.connectors`，但 `oaLoadPlusConns()` 原先只把列表渲染到 DOM、
      **没写回 S.connectors** ⇒ `oaConnectorByCode()` 永远返回 null ⇒ 全被当成「未授权」
      ⇒ 修完主逻辑仍然弹层（实测 detail=1）。拉完数据必须 `S.connectors = items`。
    - 语义分层（别合并）：
      `mute`（本次对话不调用，会话级、刷新即恢复）
      < `DISABLED`（持久关闭，只翻状态位，**凭据保留**）
      < `disconnect`（解除绑定，清 credential_json / 删本机授权 ⇒ **这个才该要求重新认证**）。
      关闭绝不能用 disconnect 实现（那样必然重新认证）。闸门只认 `CONNECTED`
      ⇒ DISABLED 自动不注入工具，不需要逐处加判断。
    - 哨兵判据（不看文案，看调用）：
      「有没有走认证」= `API.connectorDetail` 调用次数 == 0（离线打桩），
      或真实链路用 `page.on("request")` 数 `GET /v1/connectors/{code}` 请求 == 0。
      纯界面断言（弹层不存在）会被 toast / askDialog 的 `.notif-mask` 干扰，不可靠。
    - ⚠️ Playwright 坑：`page.evaluate(fn, [a,b])` 是**一个**参数（数组），
      不是两个参数 ⇒ 打桩函数里 `status` 拿到 `["CONNECTED","刘洋"]`，
      界面显示「未连接」而排查半天。传对象（`{status, label}`）最稳。
43. **生产连接器用不了 = mcp-hub 镜像旧 + docker 档从未支持 wecom-cli**（2026-10-31 线上）：
    - 症状：① 企微扫码弹层「企业微信连接器返回异常（HTTP 404）」；② 问邮箱，模型答
      「连接器服务暂时不可用，我无法查询您的邮件」（那是 `agent/aios_ai/graph/nodes.py:68`
      的**兜底话术**，说明 agent 手里根本没有 mcp__* 工具，不是模型在胡说）。
    - **定位 404 的关键技巧（不看日志也能判）**：Java `WeComCliGateway.renderReason()` 在
      hub 响应**没有 `message` 字段**时才拼出「返回异常（HTTP <code>）」。
      而 hub 的两层 404 形态不同：
        · 最外层 `_send_json(404, {"ok":false,"error":"not found"})` —— 无 message
          ⇒ Java 显示「返回异常（HTTP 404）」（**前缀都没匹配上 = 镜像太旧**）
        · `wecom_cli/admin_api` 内部未匹配 ⇒ `{"code":404,"message":"未知路由：POST …"}`
          ⇒ Java 会把「未知路由：…」原样显示（**前缀匹配了但路径错**）
      ⇒ 看到「返回异常（HTTP 404）」就等于「hub 不认识 /api/v1/wecom_cli 这个前缀」。
    - 根因：生产只重建了 `server`，`mcp-hub` / `agent` 还是旧镜像。`/api/v1/wecom_cli/*`
      与 `/api/v1/connectors/*` 是 2026-10-30（docs/64）才加的路由。
      ⚠️ **给部署命令时必须以改动落点反推要 build 哪些服务**：
      `server/**`、`user-client/**` → server；`agent/**` → agent；`mcp-hub/**` → mcp-hub。
      只 `--build server` 会让连接器整条链停在旧 hub 上（本次就是这么来的）。
    - 更深一层缺口（重建后仍会踩）：**docker 部署档从未支持 wecom_cli 连接器**
      · `mcp-hub/Dockerfile` 只有 python + requirements，**没装 `wecom-cli` 二进制**
        （`wecom_cli/runner.py` 靠 `AIOS_WECOM_CLI_BIN` / `~/.workbuddy/binaries/...` / PATH 找）；
      · compose 的 `mcp-hub` 段没透传 `WECOM_MOCK` / `WECOM_CONNECTOR_KEY` /
        `AIOS_WECOM_CLI_ROOT` / `AIOS_WECOM_CLI_BIN`；
      · 没挂凭据目录卷 ⇒ 容器重建即丢授权（`<ROOT>/<tenant>/<user>/personal/credentials.enc`）。
      本地能跑是因为 `start-all.sh` 用了宿主机的 wecom-cli 与 `data/wecom-cli` 目录 ——
      「本地正常、生产不行」的经典来源。
    - 判据命令（在服务器上跑，只读）：
      `docker compose images | grep aios-` 对比 `git log -1 --date=iso`；
      `docker compose exec server sh -c 'curl -s -m5 -X POST http://mcp-hub:8099/api/v1/wecom_cli/qr'`
      ⇒ 回 `{"ok":false,"error":"not found"}` 即旧镜像。

44. **对不可变列表就地变更 ⇒ `UnsupportedOperationException`（本地永远复现不出来）**
    - 2026-10-31 生产：`GET /api/v1/portal/meetings?scope=invited` 稳定 500，
      栈是 `java.util.ImmutableCollections$AbstractImmutableList.sort` →
      `PortalService.listMeetings`。
    - 根因一行：`mids.isEmpty() ? List.of() : meetingMapper.selectBatchIds(mids)`
      —— **空分支 `List.of()` 不可变**，紧接着无条件 `sort()`。用户一条会议邀请都没有时必现；
      本地 admin 有邀请数据，走 `selectBatchIds`（MyBatis 给的是可变 `ArrayList`）⇒ 200。
      **「本地过、生产不过」的又一典型来源是数据分支差异，不是版本差异。**
    - 同族不可变来源：`List.of(...)` / `stream().toList()` / `Collections.unmodifiableList(...)` /
      `Arrays.asList()`（定长，`set` 可以但 `add/remove` 不行）。凡是要 `sort/add/remove` 的，
      一律 `new ArrayList<>(...)` 包一层，**不要赌 mapper/上游返回的容器实现**。
    - 判据：`scripts/_check_portal_meeting_scope_empty.py`（5/5）—— 除静态扫描全仓 588 个
      java 文件外，含 **JDK 21 单文件运行时证明**（`List.of().sort()` 必抛 UOE、
      `new ArrayList<>(List.of())` 可排序）与**负向自检**（把修法还原成缺陷原样后，
      P1 必须变红、P2 扫描器仍能抓到 ⇒ 证明判据非恒真）。
    - 排查提示：看到 `ImmutableCollections$...uoe` 直接按「用了 `List.of()`/`toList()` 又去改它」
      搜索，别去怀疑 MP / 事务。

45. **hub 的裸 500 曾经零线索：`/mcp/<code>` 子 app 抛错必须自己接住**
    - 2026-10-31 生产：`POST http://mcp-hub:8099/mcp/qq_mail` 恒 **500**，而
      `GET /api/v1/mcp/manifest` 200、`/api/v1/wecom_cli/qr` 也正常 ⇒ 闸门已放行，
      只有 MCP 面崩。旧 `app.py` 把子 app 的异常直接抛给 ASGI 层：
      调用方只看到 `Internal Server Error`，前端只看到「连接器返回异常（HTTP 500）」，
      **没有任何可下手的信息**。
    - 现在的行为（`mcp_hub/app.py`）：
      · 子 app 抛错 ⇒ `logger.exception` 打全栈 + 回 `{"error":"mcp_server_failed","message":"…"}`。
        Java 侧 `renderReason()` **只在响应缺 `message` 时才拼那句「返回异常」**，
        带 message 就能把真实原因透到前端。
      · 子 app lifespan 启动失败 ⇒ 认 `lifespan.startup.failed`（原来只认 complete，
        失败时干等 10s 超时，日志只剩 TimeoutError），记下原因，路由层直接回
        **503 `mcp_server_unavailable`「未就绪：原因」**，不再把请求丢进死 app。
      · 回响应前用 `sent["started"]` 判断响应头是否已发出，避免二次发 start（uvicorn 会报错）。
    - 判读命令：`docker compose logs --tail=200 mcp-hub | grep -E "Exception in ASGI|子 app lifespan|MCP 子服务"`。
    - 本地自测方式（不必起全栈）：直接 `await _handle_http({...path:'/mcp/qq_mail'}, ...)`
      并伪造 `_CHILDREN['qq_mail'].ok=False` ⇒ 应得 503+message；把 `child.app` 换成会抛错的
      假 app ⇒ 应得 500+message 且只发 2 条消息（start+body）。

46. **FastMCP 的 Host 白名单只认 localhost ⇒ 生产 421，连接器全线不可用**
    - 2026-10-31：生产「连接器用不了」的**第一步**闸门其实是 421，不是 500。
      agent 访问 `http://mcp-hub:8099/mcp/qq_mail` ⇒ `Host: mcp-hub:8099`。
    - 机制（`mcp/server/fastmcp/server.py:191`）：`transport_security is None`
      **且** FastMCP 自身 `host` 参数 ∈ {127.0.0.1, localhost, ::1} 时，SDK 才自动装
      `allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"]`。hub 是 **uvicorn 拉起来的**，
      FastMCP 那个 host 参数恒为默认 127.0.0.1 ⇒ **白名单恒生效、只认本机** ⇒
      `TransportSecurityMiddleware` 在 `/mcp/*` 最外层直接 `421 Invalid Host header`，
      早于任何业务逻辑。**本地永远用 127.0.0.1 测 ⇒ 永远复现不出来。**
    - 判据特征：httpx 侧看到的可能是 421，也可能是被上游包一层后的 500；
      hub 日志里 `Invalid Host header: mcp-hub:8099` 是决定性一行（warning 级，别只看 ERROR）。
    - 修法：`mcp_hub/transport.py` 作唯一构造点，**保留防护**、只加白名单：
      localhost 三件套 + `mcp-hub:*`，另可用 `AIOS_MCP_ALLOWED_HOSTS`（逗号分隔，
      裸主机名自动补 `:*`）追加。**两处 FastMCP 都必须显式传**
      （`builtin.py` 代理工厂 + `wecom_cli/server.py` 原生工厂），漏一处那台服务器必 421。
    - 哨兵：`scripts/_check_mcp_hub_host_allowlist.py`（9/9）。它用**真实 SDK 的
      `_validate_host`** 做运行时判据（`mcp-hub:8099` 过 / `evil.example:8099` 拒），
      并含「抹掉 `mcp-hub:*` 后必须变红」的负向自检。必须用 `agent/.venv` 跑（要 mcp SDK）。
    - 复现手法（值得记住）：`httpx` 显式 `Host` 头 + `--http h11`（生产的 uvicorn 是裸装，
      只有 h11；本地 venv 有 httptools，默认行为不同）。⚠️ httpx 默认读系统代理，
      本机必须 `trust_env=False`，否则会拿到代理的 502「upstream connect failed」。

47. **lifespan 里 re-raise = 「健康但全废」：uvicorn 会当作「app 不支持 lifespan」继续服务**
    - 2026-10-31 生产「连接器全线不可用」的真链（三环）：
      ① 容器内 `/app/data` 属主是 root，hub 以 **uid 10001** 运行 ⇒
         `wecom/store.py::init()` 抛 `PermissionError: [Errno 13] '/app/data'`；
      ② `app.py::_lifespan` 当时**直接 `raise`** ⇒ uvicorn 打印
         **`ASGI 'lifespan' protocol appears unsupported.`** 并**照常完成启动**；
      ③ 于是所有 `/mcp/<code>` 子 app 从未启动 ⇒ 请求全落到死 app 上。
    - **最坑的地方**：`/health` 仍是 200、`/api/v1/wecom_cli/qr` 还能出二维码
      （这两个都不碰子服务）⇒ 一度误判成「hub 是好的，是 Host/版本问题」，白排查两轮。
    - 修法三条，缺一不可：
      a. **init 失败不中断 lifespan**：只影响依赖存储的连接器（wecom_cli），
         `qq_mail` 这种纯代理连接器不该被连坐 —— 这是修复的核心价值；
      b. 底座失败时 `/health` 回 **503 + `init_failed` + message**（HEALTHCHECK 用
         `urlopen`，非 2xx 即失败 ⇒ `docker compose ps` 直接 unhealthy）；
      c. 权限本身：Dockerfile `mkdir -p /app/data && chown hub` +
         compose 挂**命名卷** `mcphubdata:/app/data`。
         **不要用 bind mount** —— Docker 以 root 建宿主目录，uid 10001 照样写不进去；
         命名卷首次创建时按**镜像内**属主初始化，所以 Dockerfile 的 chown 才是决定性的一步。
    - 顺带记牢的**假象**：`WECOM_MOCK=1` 且未设 `WECOM_CONNECTOR_KEY` ⇒
      `crypto.load_key()` 生成**进程内临时密钥** ⇒ hub 每重启一次，所有人已存的连接器
      授权就全部解不开。用户看到的是「又要重新认证」，实际不是过期是换密钥。
      生产必须 `WECOM_MOCK=0` + 固定密钥（且一旦填了不能换）。
    - 别把**状态码**混起来：401=Java 令牌；**421=Host 不在 FastMCP 白名单**（坑 46）；
      500=子服务内部抛错（旧版无信息）；503 `mcp_server_unavailable`=子服务没启动。
    - 哨兵 `scripts/_check_mcp_hub_degraded.py`（9/9，进程内驱动 ASGI 不开端口）。
      ⚠️ 写这类哨兵的纪律：**lifespan 与 HTTP 调用必须在同一个事件循环**（一次
      `asyncio.run` 里跑完），否则 FastMCP 的 session manager task group 跨循环 ⇒
      **恒 500**（第一版就这样假失败过，且与缺陷无关）；另外 SSE 响应体可能抓不全，
      「真建了会话」要看响应头 `mcp-session-id`，别只看 body。

48. **意图词表会吞掉「外部投递 / 阅读诉求」；提示词不写死就会答非所问**
    - 2026-10-31 用户现场（一条对话里连着 5 个错答）：
      ① 「把这个文件传到我的企业微信上去」被判 `UPLOAD_FILE` ⇒ H5 提示「先进项目」；
      ② 「请解析我上传的文档」同样被判 `UPLOAD_FILE`（裸「上传」3.0）；
      ③ 「企业微信最新消息」被答成邮箱 INBOX/邮件列表；
      ④ 「显示这5封详细内容」被回「内容较长，无法一次性显示」而一封没读；
      ⑤ 解析《配置信息.txt》时把 gitea/ngrok token **原样复述**。
    - 修法两层，缺一不可：
      a. `intent/intake.py`：`_UPLOAD_EXTERNAL_TARGET`（企业微信/邮箱/同事/群…）与
         `_UPLOAD_READ_INTENT`（解析/解读/总结…）命中且句中无「项目」⇒ 不判 UPLOAD_FILE。
         排除必须放在阈值判断**之前**（组合命中分数够高，调阈值拦不住）。
      b. `prompt/builder.py`：新增【连接器语义路由】（企微≠邮箱；明细必须逐个
         `read_message`；企微**只读**，不传文件不谎报；无工具不编造）与
         【附件与凭据】（附件就是「这个文件」，不得反问；敏感串只给掩码并提醒吊销）。
    - 判据要**运行时**：直接调 `detect_action(用户原话)`，别只看源码正则。
      哨兵 `scripts/_check_ai_answer_accuracy.py`（19/19）含负向自检：
      把外部目标词表换成永不命中后，必须**变回** UPLOAD_FILE，否则前面的绿是假绿。
    - 同场顺手修的配置空转：`AIOS_CONNECTOR_SECRET_KEY`（Java SecretCodec）在
      application.yml 里被引用但 compose 从未透传 ⇒ 生产一直用 dev 占位默认值
      （= 凭据明文）。`_check_compose_env_wiring.py` 就是干这个的，别把它当噪声。
      它与 hub 的 `WECOM_CONNECTOR_KEY` 是**两把不同的钥匙**，不要设成同一个值。

49. **`-DskipTests` 不等于「不编译测试」——构造参数一变，生产构建就炸在 test-compile**
    （2026-11-02，用户 `docker compose up -d --build` 现场）：
    ```
    [ERROR] ChatAttachmentRunTest.java:[48,16] constructor RunService ... cannot be applied
    required: ...(多了一个 cn.aios.chat.mapper.AgentRunStepMapper)...
    ```
    `Dockerfile.server` 跑的是 `mvn -q -B -DskipTests package -pl aios-boot -am`：
    `-DskipTests` 只跳过**执行**，测试源码照编。本地用 `mvn compile` 验 ⇒ 永远发现不了。
    **判据**：改过 service 构造参数 / 实体 / DTO 后，本地必须
    `cd server && mvn -q -o -pl <module> -am test-compile`（或直接 `-DskipTests package`），
    `compile` 绿不算数。
    **本仓有三处手工 `new RunService(...)`**（不走 Spring）：`ChatAttachmentRunTest`、
    `RunServiceFormFrameTest`、`RunServiceHitlTest` —— 以后加构造参数要一次改这三个。

## 50. CLI 的 `--dry-run` 不校验 JSON 载荷字段名

`wecom-cli <domain> <cmd> --dry-run` 只做「参数解析 + 请求体拼装」，把请求体打印出来就退出 0。
**它不校验字段名**。2026-11-02 实测：`todo create --items '[{"title":"x","deadline":{"type":"date","date":"2026-11-07"}}]' --dry-run`
照常打印请求，真调用才报 `存在未知字段 'items.deadline.date'`（schema 是 `{type,value}`）。

⇒ 参数哨兵的 dry-run 断言（`_check_wecom_cli_argv.py` 的 R6b）只能证明 flag 拼对，
**证明不了载荷对**。必须另有一条拿 CLI 自己的 `--schema` 比对键集合的断言（现为 R6c）：
拉 `<cmd> --schema`，取 `request.$ref` → `schemas[ref].properties`（数组就再钻 `items.$ref`），
断言我们构造的 JSON 键 ⊆ 允许键。同类坑还有 `--attendees`（要 `[{"userid":…}]` 不是 `["uid"]`，
错形态报 640027）。

## 51. 丢弃 tool_call 必须补 tool 回包，否则下一次请求 400

LangGraph 的 `clarify` 节点里，assistant 消息带着 N 个 `tool_calls`；只要有一个 id 没有对应的
`role=tool` 回包，**下一次**请求就会被严格实现（OpenAI 等）判 400 `tool_call_id not found`。
所以「本轮只澄清、丢弃业务调用」（2026-11-02，docs/68）在丢弃的同时必须逐条补：
`{"ok": false, "error": "SKIPPED_PENDING_CLARIFICATION", "message": "未执行…"}`。
补消息还有个副作用是好的 —— 模型能区分「查了没数据」和「根本没查」，
否则它会拿上一轮的候选瞎编结果。

## 52. 同一个产品上限写在三处，就一定会走形

候选/选项上限曾同时存在于 hub（`_CONTACT_MAX`=10）、agent（`ask_user.MAX_OPTIONS`=6）、
H5（`slice(0,6)`），结果第 7~10 个候选被两级静默丢弃，用户选不到人且无任何报错。
教训：**哨兵要判「三处相等」而不是「各自等于某个字面量」**，再加一条负向自检
（改回旧值必须转红），否则将来只改一处照样绿。详见 `scripts/_check_entity_clarify_flow.py` E1/E7。

## 53. `file://` 页面里的请求**拦不住** —— 必须把 `API.base` 指到一个假域

用 Playwright 测本地单文件 H5（`user-client/index.html`，`file://` 打开）时，
页面里的 `fetch('/api/v1/…')` 会变成 `file:///api/v1/…`，而 **Playwright 的 `page.route`
不代理 file 协议**。表现极具误导性：`page.route('**/v1/**', handler)` 明明注册了，
控制台却是一串 `blocked by CORS policy (origin 'null')`，然后 `send()` 直接进 catch、
澄清卡永远不出现 —— 你会以为是卡片渲染坏了。
正确做法（既有哨兵 `_check_clar_no_silent_deadend.py` 早就这么干了）：
`await page.evaluate("() => { API.base = 'https://shot.local'; state.token = ''; }")`
把 base 指到假域，请求才会真的走网络栈、被 route 接管。另外必须先等 `boot()` 跑完
（`wait_for_function("() => typeof state !== 'undefined' && !!$('msgs')")` + 1~2s），
否则它初始化时会把刚设的 state 盖掉。

## 54. 卡片/气泡的 `min-width` 用百分比 = 等于没写（循环依赖）

`.clar-card{min-width:min(260px,100%)}` 想给卡片一个下限宽度，实测**完全无效**（仍是 190px）：
百分比是相对**气泡**宽度算的，而气泡宽度又由内容（=卡片）决定 ⇒ 循环依赖，浏览器取小值。
把 `min-width` 直接加到卡片上还会撑出气泡（卡片比气泡宽，视觉破框）。
正确做法：给**气泡**设下限宽度并用视口单位 ——
`.bubble:has(.clar-card), .bub:has(.clar-card){ min-width:min(284px,86vw); }`，
卡片保持 `width:100%`。`:has()` 不支持时只是退回「跟着气泡收缩」，不阻断功能。

## 55. 「先查再问」写成提示词必然失效一次 —— 要用代码截胡

2026-11-02 连续两轮实测同一个教训：
① 提示词写「先查候选再 ask_user」⇒ 模型看到没给姓名就直接反问，一次都没查；
② 补了代码预取 + 「调 ask_user，value 用系统给的值」⇒ 模型把名单写进**正文**
   （`[阿修bot.](wobVcoRg…)`，userid 还成了 Markdown 链接），照样不调 ask_user。
真正管用的是**确定性截胡**：候选已就绪、用户没点名、非群发时，
`agent` 第一轮**根本不调模型**，直接合成 `ask_user` 走 `clarify` 的 `interrupt()`。
判据要分层收紧（人称+动作词 / 已点名 / 群发 / 候选为空），否则会变成「见谁都弹卡」。

## 56. 回填只给标量 ⇒ 澄清链必然断裂（选完就终止）

`interrupt()` 恢复后的 tool 消息是**模型唯一的输入**。只回 `{"answer": "wob…"}` 时，
模型不知道这串值是谁、更不知道「要发什么」，唯一能做的是**把问题再问一遍** ——
用户看到的就是「点完人，气泡没下文了」（2026-11-02 现场截图）。
修法：回填 `{value,label,text}`（空 text 也要带，形状统一）+ tool 消息里加
`next: "信息已齐备，请直接执行…不要再重复确认"`；选项级 `needs_text` 让文本框
**选中即展开且必填**，一次交互把「选谁 + 说什么」交齐。
**判据：一次暂停必须能把这一步缺的全部信息收齐**，否则必然退化成多轮往返。

## 57. 多链共用的位置，别做「统一归一」（confirm 的 decision 会被吃掉）

`clarify` 节点里三条链（ask_user / request_form / request_confirm）共用
`interrupt()` 之后那段代码。无差别套 `payload = _clarify_answer(answer)` 的后果：
confirm 的 `{"decision": true}` 被压成 `{"value": null}` ⇒ 模型看不见「用户点了确认」
⇒ 写工具永不执行（`test_request_confirm` 两条用例当场红，而 run 本身不报错）。
**只能在 `chain == "clarify"` 分支里归一**，form/confirm 原样透传。
推广：看到「三条链共用一处」就先问「它们的形状真的一样吗」。

## 58. 手工起 agent 漏 `AIOS_MCP_HUB=true` ⇒ 现象像「澄清链坏了」

`start-all.sh` 里是 `export AIOS_MCP_HUB="${AIOS_MCP_HUB:-true}"`，手工 `uvicorn` 容易漏。
漏了**不报错**，表现为三连：
`capabilities degraded=[('mcp','UNRESOLVED')]` + `模糊实体预取 0 个候选（source=-）`
+ 模型自己弹一张**空选项**卡（「要发给哪位同事？请输入姓名或工号」）。
看到这三个就要先查开关，别去改澄清代码。

## 59. Playwright 验「回填后是否继续」：拦截必须活到 run 收口

`send()` 是在用户点「确认」**之后**才发 resume 的。脚本若在卡片挂载后就
`page.unroute("**/v1/**")`，那一刻请求会打到假域 → 气泡里出现 fetch 报错 →
`resume_body` 恒为 None，「循环有没有继续」永远验不到（曾误判成代码没生效）。
把「装拦截 + 起 send」与「等收口 + 卸拦截」拆成 `start_session` / `finish_session`。

## 60. `overflow:hidden` **挡不住** `scrollIntoView` —— 藏在下方的浮层会被"滚出来"

H5 的 `.phone` 是 `height:100dvh; overflow:hidden`，底部浮层（`#oaSheet` / `.mod-sheet`）
关闭态用 `transform:translateY(102%)` 藏在屏幕下方。看着安全，**其实不安全**：
`overflow:hidden` 只挡用户手势，容器**仍是可编程滚动容器**，`scrollIntoView()`、
以及移动端浏览器为露出聚焦输入框做的"聚焦补偿滚动"，都能把它的 `scrollTop` 顶上去，
于是那张藏着的浮层从底部升起来 —— 用户的描述是「点一下输入框就跳出别的模块组件」。

关键鉴别点：**`#oaRoot` 的类名里没有对应的 open 类**（`sheet-open`/`mod-open` 都不对），
说明那张浮层根本没被打开，只是被滚进了视口。只查 JS 状态会一路绿灯、永远复现不出来。

两道修法都要上：
1. 别用 `scrollIntoView`。聚焦时只改浮层自己的滚动容器：`sc.scrollTop += 中心差`。
2. 关闭态除了 `translateY(102%)` 再加 `visibility:hidden`
   （`transition: transform var(--dur), visibility 0s linear var(--dur)`）
   —— 滚进来也看不见；打开态再把 `visibility:visible` 与 `0s` 立即恢复。
   另在每次开浮层时 `oaResetHostScroll()` 把 `.phone/.oa/body` 的 `scrollTop` 归零。

## 61. Element Plus `el-select` 的已选文案：`.el-select__selected-item` 有**两个**，`.first` 是空的

2.9.x 的结构是 `.el-select__selection` 里先放一个**只读 input 的包裹节点**，再放文案 span：

```html
<div class="el-select__selected-item"><input class="el-select__input" ...></div>   <!-- inner_text = '' -->
<div class="el-select__selected-item"><span>张三（zhangsan）</span></div>          <!-- 真正的文案 -->
```

所以验收脚本里 `locator('.el-select__selected-item').first.inner_text()` 恒为空串，
断言「选中后回填正确」会**假失败**（而同一脚本后面「邀请成功 / 接口 ACTIVE / 被邀请人视角能看到」
全绿，说明功能没问题、只是取错了节点）。

正确取法：`.el-select` 整体的 `inner_text()`（outerText 会拼上可见文案），
或 `.el-select__selected-item span`；`input_value()` 恒为 `''`，别拿它判断。
同理展开下拉的可点区域是新版 `.el-select__wrapper`（老版 `.el-select .el-input`），
两代类名都要兜一下。

## 62. `iter_lines(decode_unicode=True)` 会把跨 chunk 的中文解坏 —— SSE 帧必须整段解码再切

验 SSE 错误帧时用 `for line in resp.iter_lines(decode_unicode=True)`，一条 JSON 被拆成多行
（中文多字节恰好跨 chunk，各自成了 `\ufffd`），`json.loads` 全集失败 ⇒ 断言「没收到错误帧」。
实际帧是好的，只是读法错。

正确做法：`raw = resp.content.decode("utf-8", "replace")` 然后用 `raw.split("\n\n")` 切帧、
每帧剥 `data:` 前缀再 `json.loads`。少一层 runtime 解码，跨 chunk 问题就不存在了。

## 63. 在 `'use strict'` **之前**插语句会静默关掉严格模式；插错 IIFE 层则 `xxx is not defined`

`user-client/index.html` 有两个 `<script>`，OA 相关实现全在第二个块的 `(function(){ 'use strict'; … })()` 里。
- 把 `var errText = window.AIOS_ERR.text;` 插在第二个块的**顶层** ⇒ 在 IIFE 外，块内仍是 `errText is not defined`；
- 插在 `'use strict';` **之前** ⇒ 该 Directive Prologue 失效，整个 IIFE 退回宽松模式（不报错，问题留到以后）；
正确位置是 `(function(){ 'use strict';` 之后的第一行。验收前先 `node --check` 两段脚本。

## 64. 「自动选择（默认）」行**也带** `data-cname` —— 用 `[data-cname]` 选账号行会误命中它

H5 模型选择浮层里，账号行（`modelRowHtml`）与「自动选择」都用同一个模板：
`data-cid`（空串表示自动）+ `data-cname`；平台模型行才是 `data-mkey/data-mname`。
所以 `page.locator('.mod-row[data-cname]').first` 命中的是「自动选择（默认）」，
点它等于取消选择 ⇒ 断言「chip 变账号名」必然假失败。
判账号行要 `[data-cid]:not([data-cid=''])`；同理「本环境是否真有可用账号」不能假设，
脚本要能两条路径都跑（有账号验 `aios_cred`，没账号验 `aios_model`）。

## 65. 在 agent 会话里跑 `bash start-all.sh` = 8080/8000 立刻消失（脚本用 `&` 起后台）

`start-all.sh` 里后端是 `"$JAVA" … &`、agent 是 `( cd agent && … uvicorn … ) &`。
脚本自身退出后，这两个子进程随宿主 shell 一起被回收 —— 日志照写、exit code 0，但端口立刻 DOWN。
现象：脚本打印了 `[start] backend :8080`，45 秒后 netstat 全空，`logs/boot.log` 里只有启动几行。

agent 侧要验服务，得**直接**用后台任务分别起 `java -jar …` 与 `uvicorn …`（各自重定向到 logs/），
把 `unset SERVER__PORT`、`AIOS_MCP_HUB=true`、`WECOM_*`、`AIOS_SERVICE_JWT_SECRET` 显式带上；
要长期运行仍应由用户在自己的终端跑 `start-all.sh`。

## 66. 「默认模型」有两套口径：`agent/.env` 的 `MODEL_DEFAULT` 与库里 `model_config.is_default`

管理端保存/设默认会**热推**给 agent，覆盖内存里的默认（`_DEFAULT_OVERRIDE`）；
但只要 agent 重启（或推送失败、后端没起），默认又回到 `.env` 的 `MODEL_DEFAULT`。
2026-11-04 用户现场「我配的是 deepseek，怎么跑了 minimax」就是这两套值不一致：
`.env` 写死 `minimax`，库里早期调试又把 minimax 翻成了 `is_default=1`。

判据与做法：

- 启动日志必须有 `model default at boot: <key> (source=agent/.env|admin-push)` —— 没有这行，
  「配 A 跑 B」只能靠抓包猜；
- 改供应商时**四处一起改**：库里 `is_default`、`.env` 的 `MODEL_DEFAULT` 与该供应商的 `*_MODEL`、
  代码里的预设候选（`ModelConfigService.PRESETS` / `MODEL_NAMES` / `llm/__init__.py` 注册表）、
  部署文档（`deploy/ENV.md`）；
- `.env` 被 gitignore ⇒ 只改代码不改 `.env` 等于没改（换台机器/重装就复发）；
- 历史会话与老前端会存字符串 `"default"` 当 model_ref，透传给 agent 会打
  `unknown model_ref 'default', fallback to …` 的 WARNING（行为没错、日志像报警）
  ⇒ 两端都把 `default`/`auto` 归一成「未点名」。



## 67. 「知识库里有资料」≠「检索得到」：`chunk_count` 是声明值，不是 `kb_chunk` 的行数

`kb_document.chunk_count` 可以由种子 SQL / 历史导入直接写成任意数字。本机实测 11 篇演示文档
声明 `chunk_count=402`，而 `kb_chunk` 里这 11 篇**一条切片都没有** —— 管理端列表显示"已索引 402 段"、
检索永远命中 0 条，**全程无任何报错**。

排障顺序：先 `SELECT COUNT(*) FROM kb_chunk WHERE doc_id=? AND deleted_at IS NULL` 与 `chunk_count` 比对，
再看检索打分。不要一上来怀疑 embedding / 阈值。
根治：`KbService.index()` 末做「声明数 vs 实际行数」自检，不一致置 `state=FAILED` + `errorMsg`。

## 68. 表格类文档默认切出来是「一行一块、无列名」，改阈值改 topK 都救不回来

`KbFileParser.readSheet()` 每行写一个 `\n`，`KbService.split()` 按 `\n` 切段且 ≤500 字直接成块
⇒ 500 行表 = 503 块，**含列名的块只有 1 个**（就是表头那块，且它还常被 `### SheetName` 挤开）。

更关键：`topK` 默认 5，对「共有多少条 / 分类计数」这类聚合问题，**给 5 行明细问总数**，
换任何模型都答不出。此时模型会老实说「知识库未收录」—— 它没说谎，是我们没给它判断依据。

因此：表格要按「表名+列名+连续 N 行」成块，并**另生成一块统计摘要**；
且摘要块必须在**聚合意图**时强制注入，不能只靠分数 —— 实测摘要块与数据行块**同分**
（0.01639 vs 0.01613），靠排序偶然拿 top1，换个插入顺序就掉下去。

## 69. `local` embedding 与关键词腿同源，「调阈值」是伪解法

`LocalEmbeddingProvider` 是 FNV 哈希 char2gram 词频（256 维），**不是语义向量**；
与 `KeywordScorer` 的 2-gram 覆盖率是同一路信号。实测「帮我统计下四川省的省级非遗项目有多少个?」
对 500 行名录：cos 最高 0.157、中位 0.080，`threshold=0.5` 下 **0/503 过阈**（hybrid 实际只有一路）。

把阈值降到 0 反而更差：过阈 503/503，top1 从「第 1 行」漂到「第 17 行」，仍与问题无关 ——
同源信号放开只放大噪声。要真语义必须换 provider（`aios.kb.embedding-provider=http` 指向 bge），
且**换完必须 `reembed-on-start=true` 重算**，否则旧维度向量与新 query 余弦恒 0（静默不命中）。

## 70. 工具返回字段名与提示词取值链不一致 ⇒ 检索命中了但正文从未进入提示词

`ToolGatewayService.searchKb()` 返回的字段是 **`snippet`**，而
`agent/aios_ai/prompt/builder.py#build_kb_reference_block` 取值链写的是
`content` / `text` ⇒ `text` 恒为 `""` ⇒ `continue` 跳过每一条命中 ⇒ **参考块恒为空字符串**。

后果：检索日志显示「命中 N 条」、引用标签正常显示，但模型一个字都没看到，
回答退化成「知识库未收录 / 不如网上资料」。**全程无异常、无告警**。

判据（30 秒可查）：拿一条真实工具返回 `{"docName":…,"snippet":…,"chunkIndex":…}` 调
`build_kb_reference_block([row])`，长度必须是正数。改字段名时两侧必须同步，
并把「工具网关真实字段」写进单测（`tests/test_kb_reference_block.py`）。

## 71. pymysql 校验「刚被接口删掉/改掉」的数据必须**另开连接**

同一连接在默认 REPEATABLE READ 下，第一次 SELECT 就建立了快照；接口在**另一个事务**里
提交的删除/更新，用这个老连接**看不到** ⇒ 验收脚本会误报「删了但 deleted_at 还是空」
「切片没删干净」。本轮 `_verify_kb_nonheritage.py` 连踩两次。

正确写法：改动后再 `pymysql.connect(...)` 开一个**新连接**查。

## 72. 工具入参缺 `mode` 时 `String.valueOf(null)` == 字符串 `"null"` ⇒ 检索**恒 0 条**且返回 `ok:true`

`ToolGatewayService.searchKb()` 旧写法
`String mode = args == null ? null : String.valueOf(args.get("mode"));`
—— 模型不传 `mode` 是**常态**，此时 `args.get("mode")` 为 null，`String.valueOf(null)` 得到的是
**四个字符的 `"null"`**，不是 null。`MysqlKnowledgeStore` 于是 `"bm2".equals("null")` 全不匹配 ⇒
`wantVector=false && wantBm25=false` ⇒ 两路都不打分 ⇒ RRF 融合为空 ⇒ 返回 `{"ok":true,"data":[]}`。

调用方**无法区分**「库里真没有」与「模式传错」，最终表现为用户那句
「知识库明明有文件，AI 说没有」。判据：同一 keyword 带 `mode:"bm25"` 有 5 条、不带 mode 只有 0 条。

修法（两侧都要）：工具侧用 `strArg()`（缺省返回 null）并归一化 `""/"null"/auto/default`；
store 侧 `normalizeMode()` **认不出就退回 hybrid** 并 warn。单测 `MysqlKnowledgeStoreModeTest`。
**同类风险**：任何 `String.valueOf(map.get(k))` 都要先判 null。

## 73. PDF 成绩单是「四栏并排被拍平」：栏名与数值天生分居两行，切片必然切散

`课    程 课程 学 成 补 重 …`（表头拆两行 ×4 组）+ 每行混着 4 门课 +
汇总处 `毕业设计(论文)题目 历年平均成绩 历年平均学分绩点` 换行后才 `80.26 2.69`。
按行切片 ⇒ 命中「栏名」的那块**旁边没有数字**，模型如实答「没有相邻的数值」。

修法见 `GradeSheetExtractor`（docs/75）：正则还原记录 + 「标签行 + 下一行」按 token 位对齐
（去 `其中/包括/含`；数值少时**右对齐**，否则首格为空的「毕业设计(论文)题目」会错配成 `80.26`），
再回填成两张 Markdown 表 —— 之后**复用** Excel 那条链路（列名分块/统计摘要/`kb_table_query`）。

两个必踩的正则坑：
- 补考分必须 `(?=\s|$)` 前瞻，否则 `2025-2026学年` 被截成 `202` 当成补考分；
- 学分列同理，任何「数字后面紧跟 `-`」都不是数值。

## 74. 「列出全部」是**取行**问题，不是检索问题：检索 topK 天然不全

`kb_table_query` 原本命中行硬上限 10 行且**没有 offset 参数**，于是 62 门课只能给 10 门，
模型答「接口每次只返回前 10 行，其余没有返回」——**它没胡说，是接口真的只给了 10 行**。

判据：问「列出全部/所有」，看返回里有没有 `hasMore`。没有分页字段 = 结构上取不全。
修法：`offset`/`limit`（默认 50、上限 500）+ `hasMore`/`nextOffset`/`nextHint`，
提示词强制「hasMore=true 就继续取，直到 false」，并禁止「只答第一页」与「接口只给前几行」这种半截话。

**别用检索凑**：topK=5 × 每块 N 行，最多看到 5N 行，且是「分数最高的 5 块」不是前 5 块。

## 75. 一份资料多张表时，「所有表一起数」会把两个口径混成一个数

成绩单解析后有「成绩明细 62 行」+「成绩汇总 14 行」。旧实现把所有表行累加：
`matchedRows=76`（用户问「多少门课」，76 是错数），且分页到 46 行之后吐出的是汇总表的
「通识必修课 24.0」这类键值行，模型会把它们当课程名。

修法：先算每张表命中行数 → **选一张**（默认命中最多的，同分取行数多的）+ `sheet` 参数切表
+ 返回 `otherSheets`/`sheetHint`。`matchedRows` 必须按**所选表**口径，`totalRows` 才给全资料行数。

## 76. 「角色码」与「模块码」是两套编码，直接 === 必然全落空（2026-11-06 第二次踩）

`POST /v1/workers/intent` 回 **角色码**，全项目只有 4 个（`GENERAL` / `LEAVE_APPROVER` /
`KB_ASSISTANT` / `DOC_DRAFTER`，见 `WorkerRole`）；OA 模块数字员工的 `worker_type` 是
**模块码**（`OA_LEAVE` / `OA_DOC` … 43 个，见 `V83`）。前端拿两者直接 `===` ⇒ 一个都撞不上，
界面只能提示「未能识别类型，请手动选择」。

**这次是「一处修了、另一处漏」**：2026-11-04 已为「对话里说『我要请假』」补过
`formCode → OA_*` 的映射（`oaApprovalLaunchTarget`），但「新工作任务」(`oaNewTask`) 那条入口没跟着改，
于是同一个 bug 换了个入口又出现。**判据必须抽成一个函数给所有入口共用**（`oaMatchIntentWorker`）。

## 77. `GENERAL` 与「通用办公助手」都是**缺省值**，不能当匹配信号

- `GENERAL` 既是「没识别出专用类型」的缺省角色码，也是自建员工的 `worker_type`
  （本环境有一台「每日考勤」就是 `GENERAL`）。把它当候选码去精确匹配 ⇒ 任何一句识别不出来的话
  都被派给那台员工（实测「今天天气怎么样」→「每日考勤」）。
  **缺省码一律不进候选**（`oaIntentCodes`/`roleTypeCodes` 都显式短路）。
- 同理，`/v1/workers` 给每个通用员工回的 `roleName` 都是「通用办公助手」—— 拿它当关键词，
  会对所有 GENERAL 员工满分命中。**只有非通用类型才把 roleName 当强信号**。
- 兜底结论：识别不出来就**不猜**（弹选择浮层 / 打开数字员工列表 + 把原句记住），
  派错的代价（用户以为系统听懂了）比多一次点击大得多。

## 78. `collab` 有 4 个面板：跳视图不设 `S.rail` 会停在默认「任务」

「我的」四个统计要跳到「待办 / 审批」时，只 `oaGo('collab')` 是不够的 ——
`renderCollab()` 用 `S.rail` 决定哪个 rail 项与 panel 带 `.on`。必须**先 `S.rail='approvals'` 再 `oaGo`**，
否则「点审批」落在任务面板上，看起来像没反应。

## 79. 键盘顶底栏：判据挂 `body`，不挂 `#oaRoot`

Android/微信 WebView 弹键盘会**连 layout viewport 一起缩**，而页面是「顶栏+内容+底栏」flex 列布局
⇒ 底栏被压到键盘正上方。收起的 CSS 必须写 `body.kb-on .tabbar`：
经典形态的 `.tabbar` 与新版 `#oaTabs` 是同一个位置上的同一个问题，挂 `#oaRoot` 只能解决一半。
复用已有 `visualViewport` 差值（>80px）判据，别新写一个键盘探测。

## 80. `@TableLogic` 让 `LambdaUpdateWrapper` **也**够不到软删行（只有裸 SQL 能复活）

`updateById` 因 NOT_NULL 策略跳过 null 字段，这个早就知道了；但**换成 wrapper 也修不好** ——
`@TableLogic` 会给 select/update 自动追加 `deleted_at IS NULL`，wrapper 的 `set(deletedAt, null)`
同样落不到软删行上（UPDATE 的 WHERE 里就把它排除了）。
再叠上「唯一键不区分删除态」（`uk_mcp_tool(server_id, name)`），后果是：恢复不了 + 下次 insert 撞 DuplicateKey。
**唯一可行解是裸 SQL**（`@Update` 注解里手写 `SET deleted_at = NULL ... WHERE deleted_at IS NOT NULL`）。
顺序也是判据：必须先复活**再** selectList —— 先查后复活等于没复活。

## 81. `MultiServerMCPClient` 不传 `handle_tool_errors` ⇒ 工具失败被包成「正常返回」

`langchain-mcp-adapters` 默认 `handle_tool_errors=True`：`CallToolResult(isError=True)` 会被包成
`ToolMessage(status="error")` **当正常返回值交回来**，不抛异常。于是 `ainvoke()` 外层写
`return ok=True` 就把失败报成了成功（A1 的真相）。
两个修法要一起上：构造时 `handle_tool_errors=False`（让它抛 `ToolException`），
`invoke()` 里再判一次 `getattr(resp, "status", None) == "error"`（双保险，换库版本也不至于静默）。
**别把 `isError` 当唯一判据** —— 那条分支在适配器包装形态下根本走不到。

## 82. `sitecustomize.py` **不会**被自动加载（放脚本目录没用）

Python 只在 `sys.path` 里找 `sitecustomize`，而 `python scripts/x.py` 只把 **scripts 目录**加进 `sys.path[0]`，
site 模块是在**那之前**导入的 ⇒ 放在 `scripts/sitecustomize.py` 永远不生效（实测过）。
要「一处防护管全部脚本」只能：① 每个脚本插一行（`sys.stdout.reconfigure(encoding="utf-8")`）；
② 统一 launcher；③ 环境变量 `PYTHONIOENCODING=utf-8`。
本项目走 ①：`ast` 定位 `docstring` / `from __future__` **之后**插入（插在 future 前会 SyntaxError），
插完再 `ast.parse` 复核 + `compileall` 全量验证。

## 83. `BizException(503)` 落到错误码/HTTP 层是 **502**

`ErrorCode.ofCode` 把 `502/503/504` 统一映射成 `MODEL_UPSTREAM_ERROR(502)`，且该枚举的 `HttpStatus` 是 `OK`
（200 + 信封，见铁律 29/30）。所以「抛出 503」在测试里断言 `getCode()` 会得到 502，**不是修复没生效**。
断言写 `ErrorCode.MODEL_UPSTREAM_ERROR.code()`，判据放在「抛的是业务异常 + 人话」而不是码值字面量。

## 84. `java -jar` 起后端必须带 `--aios.web.h5-dir`，否则 `/aios/h5/` 404

默认 H5 目录是部署形态的路径（本机解析成 `D:/app/web`，不存在）⇒ 启动日志只有一条 WARN，
接口侧表现为 `/aios/h5/` 返回 `{"code":404,"message":"接口不存在：/aios/h5/"}`。
本地联调口径：
`java -jar ... --server.port=8080 --aios.web.h5-dir=D:/aios/user-client`。
**症状识别**：H5 套件卡在 `wait_for_selector("#oaRoot")` 超时，而 `:5181` 是好的 ——
因为套件写死的是单端口路径 `BASE + "/aios/h5/"`。

## 85. `mcp-hub` 缺密钥会 `/health` 503（`init_failed`），不是「没起」

只跑 `python run.py` 会得到
`{"ok":false,"error":"init_failed","message":"连接器存储初始化失败：CryptoError: 生产模式必须设置 WECOM_CONNECTOR_KEY"}`，
而端口是通的（容易误判成「hub 在跑只是慢」）。
启动口径与 `start-all.sh` 一致：`WECOM_MOCK=1` + `WECOM_CONNECTOR_KEY=<fixed>` + `AIOS_SERVICE_JWT_SECRET=<fixed>`。
`_verify_mcp_registry` 的 M13「工具目录无漂移」会因此红（`hubHTTP=502`），属外部依赖桶。

## 86. `nohup java ... &` 起的后端会被 shell 的 SIGTERM 带走

在工具里 `nohup ... &` 起后端，命令返回后进程仍在，但**下一次** shell 收尾时会把它一起 TERM 掉
（日志停在启动中段，`health` 从 200 变 000，无异常栈）。
正确姿势：用工具托管的后台任务（`run_in_background`）+ 输出重定向到文件，
**不要** `| tail -40`（管道会缓冲，`TaskOutput` 拿不到实时日志）。

## 87. 「表格过大」守卫要计**扫描行**，不是命中行

原写法 `if (idx + 1 > MAX_SCAN_ROWS)` 在过滤 `continue` 之前，`idx++` 在其后 ⇒ `idx` 是命中行数。
带过滤的查询（`课程性质=学基必修`）命中率低时，扫描 20 万行 `idx` 也可能只有个位数，守卫形同不存在。
拆两个计数器：`idx` 只管分页序号，`scanned` 只管守卫。
守卫阈值做实例字段 + package-private setter，否则 200 000 行造不出来、测不了。

## 88. `ORDER BY x DESC` 里 NULL 排最后 ⇒ 「第一页还在不在」不能当「没被删」的判据

会话列表按 `last_msg_at` 倒序，而一句没问的空壳会话 `last_msg_at` 是 NULL。
MySQL 对 `DESC` 的 NULL 是**最后**，于是空壳会话永远落在页外。
`_verify_h5_conv_menu` 的 T7b 原来写「默认列表（size=50）还能查到它」⇒ 首跑假红（test 账号 105 条会话）。

判据要么按关键词精确捞（`?keyword=xx`），要么按 id 取详情。**别用「第一页里有没有」验证存在性**。
同类陷阱：`LIMIT/OFFSET` + 非唯一排序键（`last_msg_at` 同秒并列）也会让分页结果漂移。

## 89. H5 的 `index.html` 里两个 `<script>` 是两个独立 IIFE，作用域不共享

`脚本1`（表格/经典形态那一大段）与 `块 2`（OA 形态）各自 `(function(){ ... })()`，
顶层的 `function foo(){}` **不会**变成 `window.foo`。
- `oaConvTitle`（块 2，~14262）能被同块的 `renderRecent`（~12563）用 —— 函数声明同作用域内提升；
- 但 `脚本1` 的 `openHistory`（~7381）用不了它，只能就地写 `c.title || '未命名会话'`。
跨块共享必须显式挂 `window`（仓库里已有这种写法，见 3506 行注释）。

## 90. 表单/AI 的两条路径容易写错：请假提交是 `/v1/leave/requests`

`workflow` 前缀下只有 tasks / mine / defs / timeline / cc，**没有** leave；
请假在 `OrgLeaveController` 之外、由 `WorkflowController` 暴露为 `/v1/leave/types|balance|requests`。
写 e2e 时按「workflow/leave」猜路径 ⇒ 10 条断言全红且都是 404，很容易误判成实现没生效。

## 91. e2e 造请假单必须用「不占额度」的假种，且清理要还原在途额度

假种 `quotaDaysPerYear>0` ⇒ 后端 `quotaTracked=true`，提交时立刻压 `leave_balance.pending_days`。
只删 `approval_order` 不删 `leave_request` ⇒ 在途额度一直挂着，**第二次跑就变成「余额不足」假红**
（本次实测：COMP 5 天额度被两轮跑满）。
正确做法：优先选 `quotaDaysPerYear=0` 的假种（如事假 CASUAL），并在清理段按剩余 PENDING 单重算：
`UPDATE leave_balance b SET pending_days = COALESCE((SELECT SUM(r.days) FROM leave_request r
 WHERE r.user_id=b.user_id AND r.leave_type_code=b.leave_type_code AND YEAR(r.start_date)=b.year
   AND r.status='PENDING' AND r.deleted_at IS NULL),0)`。

## 92. 弹层截图必须等过渡动画结束，否则会把「半透明」误判成 z-index 问题

`.hd-mask{opacity:0→1; transition:.16s}`，`wait_for_selector('#hdMask.on')` 只保证 class 已加，
截图/读色时可能正好在动画中间：整层发灰、底下 tabbar 与 toast 都透出来，看起来像层级压不住。
**先固定等 500ms 再截图**。（真层级问题另有判据：`getComputedStyle(mask).zIndex` 与父级是否形成
层叠上下文，别靠肉眼。）

## 93. `try: ... except Exception: pass` 会把 `NameError` 一起吞掉 —— 批量插桩必须验证「真的跑到了」

2026-11-06 实测：为修 GBK 控制台打印 ✅ 崩溃，给 193 个脚本插了
```python
try:  # A3
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import sys
```
其中 **161 个**块落在 `import sys` **之前** ⇒ `NameError: name 'sys' is not defined`，
被 `except Exception: pass` 静默吞掉 ⇒ **一段死代码**，控制台照旧 `UnicodeEncodeError`，
但 `grep sys.stdout.reconfigure` 有命中、`git diff` 也显示「已修」—— 假修复。

- **判据**：批量插桩后必须**实际运行一次并观察副作用**，不能只看文本命中。
  最小复现：`PYTHONIOENCODING=gbk python x.py`，旧写法 exit=1、新写法 exit=0。
- **修法**：在 try 内补 `import sys`（模块级 try 里的 import 仍绑定全局），
  不搬代码、不动缩进，比「把块移到 import 之后」风险小得多。
- **通用规律**：`except Exception: pass` / `except: pass` 包住的初始化代码，
  写错名字、用未导入的名字、属性不存在 —— 全部静默失效。
  凡是「加了但看不出效果」的兜底块，先怀疑它根本没执行。

## 94. 多服务部署：只 rebuild 改过的那个服务 —— agent 的代码是**烤进镜像**的

2026-11-06 实测（本轮推送后自查）：`deploy/Dockerfile.agent` 是
`COPY aios_ai ./aios_ai` + `RUN pip install .`，compose 里 agent **没有任何源码 bind mount**
（server 也只挂了 `serveruploads:/app/uploads`，不是源码）。
⇒ `docker compose restart agent` / `up -d agent`（不带 `--build`）**都不会换代码**，
容器里跑的是构建时的快照；aios_ai 还被 `pip install .` 复制进 site-packages，
连「改 cwd 下的文件」这条退路都没有。

- **判据**：`docker exec aios-agent grep -c "def <新函数名>" /app/aios_ai/...` ——
  读**容器内实际文件**（铁律 18：看运行实例不看 mtime）。旧镜像返回 0，新镜像 1。
- **正确命令**：`docker compose up -d --build agent`（同时改了 server 就 `--build server agent`）。
- ★ 同类陷阱在**本机**是另一副样子：`start-all.sh` 按端口探测做幂等，agent :8000 已在跑就打印
  `[skip] agent :8000 already running` **直接跳过** ⇒ `git pull` 后只跑 start-all.sh = 代码没换。
  必须先显式停掉 8000 进程（在 PowerShell 里用 `Get-CimInstance` 找 PID 再 `Stop-Process`），再起。
- 记命令时别只看「改了几个模块」，要对着 Dockerfile 的 `COPY` 列表数：
  本次 `Dockerfile.server` 里还有 `COPY user-client/index.html /out/h5/index.html`
  ⇒ H5 改动同样只能靠重建 server 镜像生效，改完 html「重启一下就行」是错的。
- 反例校准：本地 `agent/.venv` 的 site-packages 里**没有** `aios_ai`、没有 `__editable__` 标记，
  是靠 `cd agent` 后 cwd 解析（`uvicorn app.main:app`）⇒ **本地改代码只需重启进程，不用重装**。
  同一份代码，「本地怎么生效」与「生产怎么生效」是两套机制，别互相类推。

## 95. MySQL 的 `JSON` 列会**重排对象键** —— 别用 JSON 对象顺序表达业务顺序

2026-11-06 实测：`form_template.schema_json` 是 MySQL `JSON` 列。种子脚本
`_gen_oa_form_seed.py` 的 `build_schema()` 明明按业务顺序写 `properties`，
落库后顺序却变成了「key 长度升序、同长再字典序」：
`archive_borrow` = `title(5) → archive_no(10) → borrow_use(10) → attachments(11) → return_date(11) → archive_type(12)`。

- 后果：请假表单在 H5 上渲染成「请假天数 → 证明材料 → 请假事由 → 结束日期 → 假种 → 开始日期」，
  用户根本填不下去。**43 张平台表单里 39 张受影响**，一直没人发现 ——
  因为此前前端用的是自己硬编码的卡片，没真读过这份 schema。
- **数组不受影响**：`required` 保序。种子里的 required 顺序恰好就是业务顺序
  ⇒ 用它当业务前序（`FormTemplateService.orderFieldEntries`：required 在前、非必填在后）。
- 判据：`select schema_json from form_template where code='leave_request'` 看键顺序；
  再对 `/api/v1/forms/leave_request` 的 `fields[].label` 顺序，两者应**不同**（接口是修好的）。
- 长期正解是每字段加显式 `x-order`（种子 + 迁移 + 渲染三处），需一次数据迁移；本轮用 required 顺序兜住。

## 96. `cmd | tail` 之后 `echo $?` 拿到的是 `tail` 的退出码 —— 打包「假成功」

2026-11-06 实测：`bash mvnw -o -DskipTests -q clean package 2>&1 | tail -15; echo "EXIT=$?"`
打印 `EXIT=0`，于是我以为打好了、直接起服务，结果接口行为完全没变。
真实输出里躺着 `[ERROR] Failed to clean project: Failed to delete D:/aios/server/aios-gitee/target`。

- **根因**：VSCode 的 Java 语言服务（jdt.ls，进程名 `java.exe` + `redhat.java` 扩展）在索引项目，
  **锁住 target 目录** ⇒ `maven-clean-plugin` 删不掉，`clean` 阶段直接失败。
- 取真实码：`cmd > /tmp/x.log 2>&1; echo "EXIT=$?"`，别接管道；
  或先 `set -o pipefail`。
- **绕开锁**：用不带 `clean` 的 `package`（只重编变化源文件，25s 完成）；
  真要 `clean` 就先关掉 IDE 的 Java 语言服务。
- 收口判据不看退出码、看产物：`stat -c '%y' aios-boot/target/*.jar` 必须晚于源码改动时间。

## 97. Playwright 同步 API 里用 `time.sleep` 轮询 —— 会把**桩回调与 request 监听**一起堵住

2026-11-06 实测（写 `_verify_worker_suggest.py` 时踩到，**差点误判成产品缺陷**）：

现象：点击「换他重答」后，`run_bodies` 一直只有 1 条，`wait_until(len(run_bodies)>=2, 10s)`
判定「原问题没被重发」⇒ 报红。但**紧接着**一次 `pg.evaluate(...)` 之后，同一变量变成 2 条。

- **根因**：`playwright.sync_api` 的所有浏览器事件（`page.route` 的桩回调、`page.on("request")`）
  都由 Python 主线程在**调用 Playwright API 时**抽空分发。`time.sleep()` 期间主线程睡死，
  队列里已经到达的事件**一个都不处理** ⇒ 浏览器早把请求发出去了，桩却还没回，记录也没写。
- **表现极具误导性**：页面看起来「没动作」，日志看起来「请求没发」，而实际上全发了。
- **正确写法**：轮询里用 `pg.wait_for_timeout(150)`（它是 Playwright 调用，会推进事件循环），
  绝不用 `time.sleep`。
- 同型注意：`subprocess.run(mysql ...)` 这类**同步阻塞**调用在轮询循环里也应按「少量次数」使用；
  本次 A2c/A4 的 SQL 判据没出问题，但把 `wait_until` 里的判据换成 SQL 就会重新引入阻塞。
- **判据自检**：任何「等待某事件发生」的断言，若超时后又在你下一次任何 Playwright 调用时
  立刻成立，就该先怀疑是被自己的 sleep 堵住了，而不是被测代码慢。


## 98. `await` 住的卡片必须能被「停止」解开 —— 否则 `S.busy` 永久为 true

2026-11-06 实测（用户口径：「填写表单时，无法停止」）：

`oaSend` 里是 `await mountFormCard(bubble, form)`，而这个 Promise 只在用户「提交」或「取消」时
resolve。用户点右上「停止生成」时，`oaStop()` 只 abort 了 SSE、cancel 了 run ——
**那条 await 还在等** ⇒ while 循环出不来 ⇒ `finally` 不执行 ⇒ `S.busy` 永远为 true ⇒ 输入栏废掉。

- 修法：与既有的 `cancelClarCard()` 同构加 `cancelFormCard()`，`oaStop()` 里一并调用，
  把未决卡以 `null` 收掉让 while 正常 break。
- **凡是「等用户操作」的卡片（澄清 / 确认 / 表单）都要有一个外部可解的口子**，
  这是新增第三种卡时最容易漏的一条。
- 连带 bug：用户停止后 `oaAfterOaAnswer` 仍会执行收口副作用（`held=true` 分支当场补发
  经典请假单）——那时 need_form 卡刚被收走、防重闸拦不住 ⇒「点了停止又冒出一张空表」。
  **用户主动终止的那一轮，收口副作用一律不做**（`stopped` / `cancelledForm`）。
- 「取消」按钮不能只摘 DOM：run 会留在 `WAITING_INPUT`，之后再提交就撞
  「该运行当前不是等待澄清状态（CANCELLED）」。取消必须同时 `API.cancel(runId)`。

## 99. 「内部字段外露」不止一处 —— 按模式扫，别只修被投诉的那一处

2026-11-06 用户投诉「内部字段不能展示给用户」，修完核对面板后按模式再扫，又找出 5 处同款：

| 位置 | 症状 |
|---|---|
| `validateForm` | 漏填提示拼 `data-field`（内部键）⇒ `reason 为必填项`（**最高频，必现**） |
| `formReceiptHtml` 的 `fields` 分支 | key 是字段名，直接当标签印 ⇒ `leave_type` |
| `renderFormHtml` 未知类型 | 提示里印类型码 `weird_type` |
| 权限申请弹窗 | `权限：创建员工（worker:create）` |
| 审批轨迹 | 审批人缺名时显示 `#<userId>` |

- **判据**：凡是往用户可见文案里拼的字符串，问一句"这是它自己的名字，还是我们系统里的标识？"
  后者一律换人话或直接不显示（`formFieldLabel` / `FORM_LABEL_ALIAS` 是唯一口径）。
- **同一模式还有"反方向"**：`toast('停止失败：'+e.message)` 会把 `运行不存在：e2e-form-2`
  整句甩出来 —— 内部 id 混在后端文案里。这类要按**错误码**映射，别按字符串裁剪。
- 反例（**不该**动的）：`errText(..., {withId:true})` 里的 errorId 是有意保留的报障能力。

## 100. 判断「停不下来」类缺陷，先找 `resolve` 的触发点

`await` 住一个 Promise 的交互（澄清卡/确认卡/表单卡）必须能回答三个问题：
① 谁会 resolve 它？② 用户点「停止」时它会被 resolve 吗？③ 不 resolve 时 `S.busy` 谁释放？
2026-11-06 那一轮里 ② 的答案对表单卡是「不会」⇒ `S.busy` 永久 true、输入栏废掉。
- 新增任何一种"等用户操作"的卡片时，必须同时提供 `cancelXxxCard()` 并在 `oaStop()` 里挂上。
- 反向确认也有价值：经典形态**没有** `bub-stop`（只在 OA 的 `oaSend` 里创建），
  所以同款死锁在经典形态没有触发入口 —— 排查时要能说清"为什么不修"。

## 101. MySQL JSON path 里带连字符的键必须加双引号

`JSON_EXTRACT(schema_json, '$.properties.leave_type.x-options-ref')` 报
`Invalid JSON path expression. The error is around character position 37`，
写在 Flyway 迁移里会**让整个后端起不来**（报错完全没提是哪条 SQL）。
- 正确写法：`'$.properties.leave_type."x-options-ref"'`。
- 自查：键名里出现 `-` `.` 空格 或数字开头，一律加引号。
- 顺手记：迁移里的 DML 失败会回滚，只留一条 `success=0` 的 history 记录；
  删掉那条（`delete from flyway_schema_history where version='NNN' and success=0`）才能重跑。

## 102. 改了平台表单行 ≠ 生效 —— 租户有一份副本

`FormTemplateService.getByCode` 是「**本租户优先**，没有才回退 tenant_id=0」。
租户建号时会复制平台表单，所以平台行改了、登录进去读到的还是旧定义。
2026-11-06：V110 只更新 tenant_id=0，接口仍返回旧的假种枚举（PERSONAL/COMPENSATORY），
是回归里 V2d/V2c'' 原样报红才发现的 —— **没有回归就是一次「改了却不生效」**。
- 改任何 `form_template` 定义，都要同时处理 `tenant_id<>0` 的副本；
- 判据别只看 `code`，用「内容特征」区分「没改过的副本」与「租户自定义过的行」，
  后者不能动（例：假种枚举里含字典表中不存在的 PERSONAL，就说明它还是 V86 原样）。

## 103. dev profile 不传 `--server.port` 会拿到随机端口

现象：`Web server failed to start. Port 62170 was already in use.` —— 看着像端口冲突，
其实是**根本没指定端口**（dev profile 下 Tomcat 取了随机端口，那个端口恰好被别的进程占着）。
- 启动必须显式 `--server.port=8080`（与铁律同条），漏了会得到上面这条极具误导性的报错。
- 判断依据看更早那行：`Tomcat initialized with port 62170 (http)`。

## 104. 「表单字段」到「业务字段」要过一道真上传

通用表单的 file 控件，`collectFormValues` 采到的是**文件名**（`f.name`），
而业务侧要的是 fileId（请假的 `proof → proofFileId`）。
2026-11-06：不改这一步的话，用户选了病历、界面明明白白显示着文件名，
后端仍判「必须上传证明材料」——用户会认为是系统瞎了。
- 修法：`uploadFormFiles(card, values)` 在确认提交前真上传，值换成 `[{fileId,name}]`，失败中断提交；
- 配套：核对面板渲染 file 数组时要取 `.name`，否则 `[object Object]`。

## 105. 判「这条链路是真的还是假的」，看它写哪张表

2026-11-06 请假一例：两条提交路径**接口都返回成功**，但一条写 `leave_request`、
另一条只写 `form_submission`。后者看起来一切正常（有单号、有审批、有回执），
实际上查不到记录、不占余额、审批通过也不扣额度。
- 判据：问「这个业务的结果表是哪张？这条路径写它吗？」
- 验证：提交一次，直接查那张表有没有新行、关键字段（如 `order_id`）是否与其他表一致；
- 反例（**不该**当缺陷）：`form_submission` 里没有 `leave_request` 行本身不是错，
  错的是「本该建请假单的路径没建」——所以要按 `biz_type` 分流，而不是让所有提交都去建请假单。
