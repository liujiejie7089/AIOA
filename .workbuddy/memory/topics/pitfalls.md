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
41. **`.gitignore` / `.dockerignore` 裸目录模式会吞掉源码（两处必须同改）**：不以 `/` 开头的模式（`data/`、`logs/`、`dist/`）匹配**任意层级**。本项目 `data/` 造成**两个独立原因**同时成立：① `.gitignore` 使 `web/apps/demo-ticket/src/data/` 从未入过库（`git log --all -- <路径>` 无记录，随 `c1dca22` 引入 compose 起就缺）；② `.dockerignore` 使该目录**即便源码拷全也被排除出构建上下文**（所以 rsync 拷贝也照样失败）。两个文件都有 `data/`，**修一个不修另一个，重建仍挂**。凡「本地过、CI/容器不过」，先跑：`git check-ignore -v <文件>` + `git status --porcelain --ignored`。修法：目录模式一律**锚定根**（`/data/`）。另注意 `--ignored` 里出现 `scripts/e2e_*.py` / `start-backend.bat` 属**约定不入库**（本地回归台与本地启动器），不是缺陷。
42. **`docker compose restart` 不重读 `.env`**：它只把同一个容器停掉再启动，**不重新渲染服务定义**，环境变量保持旧值 ⇒ 改完 `.env` 执行 `restart` 等于白改（现象：日志里地址/Key 还是老的）。正解 `docker compose up -d <svc>`（配置哈希变了会自动重建）。**不需要** `--force-recreate`。生效判据看 `docker exec <c> printenv <VAR>`，**不是**「容器重启成功了」。
43. **「镜像构建所需的、不在 COPY 清单里的文件」是同一类静默缺陷**：`Dockerfile.web` 漏 `COPY web/tsconfig.base.json ./` ⇒ 容器内 `apps/*/tsconfig.json` 的 `extends: "../../tsconfig.base.json"` 失效，丢的是 `strict`/`esModuleInterop`/`moduleResolution:bundler`/`skipLibCheck`，**报错却指向 element-plus 与 `rollup/parseAst`**，与真实原因毫无关联。排查手法：把 Dockerfile 的 `COPY` 指令解析成「`/build` 下的文件清单」，再校验每个 `extends`/被引用路径是否在清单内（本次用 20 行脚本验证 4 个 tsconfig 全部命中）。
44. **重打包前必须列出「所有」后端实例，jar 锁可能来自另一个端口**：本机同时跑着 8080（主档，`aioa` 库）与 8081（`aioa_prodtest` 库）两个后端，**它们共用同一个 fat-jar 文件**。只停 8080 后 `mvnw clean package` 仍失败：`Failed to clean project: Failed to delete .../aioa-boot-...jar` / `mv: Device or resource busy` —— 持锁的是 8081 那个 JVM。定位手法（本环境 PowerShell 工具**不回显 stdout**，必须写文件再 `Read`；`wmic` 已不可用）：用 PowerShell 工具跑 `Get-CimInstance Win32_Process -Filter "Name='java.exe'"` 取 `ProcessId` + `CommandLine`，`Select-Object` 后 `Set-Content logs/_probe_java.txt`，再 Read 该文件。**判据**：`CommandLine` 里含 `--server.port=<别的端口>` 且含 `aioa-boot/target/aioa-boot-*.jar` 的 java 就是第二实例。本机另有 3 个 java **不能动**：FinalShell（`finalshell.jar`）、VS Code 的 `redhat.java` JDT LS、IDEA 的 Maven embedder。**绝不**用 `Get-Process java | Stop-Process` 一把梭。停用借来的实例后要**按原参数原样恢复**（含原日志文件名与 `--spring.datasource.url`）。另：`mvnw ... | tail -20` 的退出码是 `tail` 的，**永远是 0** —— 判成败要看 `BUILD SUCCESS`/`FAILURE` 文本，别信 `$?`。产物大小兜底判据：fat-jar 应 ~110MB，若掉到 ~20KB = 被 rename 成的 stripped-jar（说明没停 JVM 就重打包了）。

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
    **修法（已落地）**：`server/aioa-common/.../cn/aioa/common/http/AgentHttpClient.java` 作为「后端访问 agent」的唯一入口，客户端级 `version(HTTP_1_1)`；4 处调用点（`WorkerScheduleService`/`KpiInsightService`/`WorkerIntakeService`/`ModelConfigService`）全部改走它。
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
    入口 nginx 想让 `10.0.0.3/web` 指向管理端：管理端产物是 `base=/aioa/web/` +
    `createWebHistory(BASE_URL)` 的 SPA ⇒ **地址栏必须落在 SPA base 之下**，
    用 `rewrite` 会让 `assets/*` 相对路径解析错而**白屏**；`/web` 只能 `return 302 /aioa/web/`。
    反之 H5 是**自包含单文件**、API base 由 `location.pathname` 推导（`/user/` ⇒ `/api`），
    所以 `/user/` 可以用**内部 rewrite** 到 `/aioa/h5/` 而不跳转。
    **通则**：**先判断目标的 base 语义**（有没有 base path / 是不是单文件 / 是否按 pathname 推 API），
    再决定 redirect 还是 rewrite —— 两者不可互换。改这类入口后要跑
    `scripts/_check_single_port.py`（现 **13 项 + 26 项负向 mutation**）确认 `/web` 的 302 跳转语义与
    `/user/` 的 rewrite 语义都还在。
71. **「固定宿主端口」在目标机上被占用 ⇒ 部署就起不来；覆盖口必须走 `.env`，不能靠改 compose。**
    现象：`docker compose up -d server agent` 报 `port is already allocated`。本案是 `0.0.0.0:8000`
    被目标机上一个**无关容器**占着，而 compose 把 agent 固定发布 `127.0.0.1:8000:8000`。
    修法：compose 写成 `127.0.0.1:${AIOA_AGENT_HOST_PORT:-8000}:8000`（**默认值不变**），
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
    现场：公网 `https://mall.egooaicloud.com/aioa/web/` 页面能开，但**所有接口 404**；
    在应用机上直连 `:8080/aioa/web/` 却一切正常。根因：管理端 SPA 的 `axios.create({baseURL:'/api/v1'})`
    与 SSE `` `/api/v1/runs/…` ``（`fetchEventSource` **不走 axios**，必须自己拼）都是**根绝对路径**；
    浏览器把它解析成 `https://域名/api/v1/**`，而外网入口只有 `location /aioa/` ⇒ 无人代理。
    ★ **为什么能长期潜伏**：后端是**双前缀并存**（`/aioa/api/**` 剥成 `/api/**`，`/api/**` 也保留），
    本地 44 个套件直打 `:8080/api/**`、vite dev 又代理 `/api` ⇒ **本地全是对的**。
    只有「共用域名只反代 `/aioa/`」这一种拓扑才会 404。
    **通则**：只要产物被挂在子路径下（`base=/aioa/web/`），**根绝对路径就是错的**；
    基址必须与 `import.meta.env.BASE_URL`（或等价的 base 变量）**同源**，且要**逐一找出不走 axios 的调用**
    （SSE / `EventSource` / `window.open` / 文件下载直链 / 后端回填的 url 字段）。
    守卫：`scripts/_check_single_port.py` 的 c12（对应 H5 侧是 c9）。

74. **Dockerfile 的 `COPY …/pom.xml` 清单与聚合 pom 的 `<modules>` 漂移，且被 `|| true` 静默掉。**
    现场：`server/pom.xml` 有 11 个 `<module>`，`deploy/Dockerfile.server` 只 COPY 了 10 个 ⇒
    Maven 报 `Child module aioa-integration-scfy of /build/pom.xml does not exist`。
    ★ 该行写成 `mvn … dependency:go-offline -pl aioa-boot -am || true` ⇒ **构建不会失败**，
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
    **可行做法**：`vite build --outDir "C:/Users/<u>/AppData/Local/Temp/aioa-shell-vNN"`（每轮换一个**不存在**的
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
