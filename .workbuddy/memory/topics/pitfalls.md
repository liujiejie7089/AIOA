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
    `scripts/_check_single_port.py`（现 **11 项 + 22 项负向 mutation**）确认 `/web` 的 302 跳转语义与
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
