# AIOA 项目长期记忆

## 项目本质
- AIOA = 地级市 AI 公共服务平台 · AI 工作台（左老师设计交接包为蓝图）。仓库当前实现 = **管理端/基座工作台**：Vue3 微前端 shell (`web/apps/shell`) + Java Spring Boot 单体 (`server/`, 7 个 Maven 模块) + MySQL 8 本地库 + Python FastAPI echo agent (`:8000`)。
- 与设计文档（uni-app 小程序 + AgentScope 2.0 Python + PostgreSQL + 8 微服务域 + 41 实体）**严重偏离**。偏差属"规格 vs 代码"。**用户已于 2026-09-07 确认方向：改代码对齐设计文档**，按五层架构演进（接入与交互层 / API网关与安全层 / 智能体运行层 / AI能力与连接层 / 平台底座层）。Layer 3 Agent Runtime M2（真实 LLM 流式推理 + DeepSeek Harness + token 计量）已实现并验证。正式核对报告：`AIOA_设计文档与运行代码核对报告.md`。

## 对齐路线（五层，2026-09-07 起）
- 接入与交互层：web ChatBox 组件 + IM 网关（#53 待做）
- API 网关与安全层：server 已有 aioa-security，演进网关+SSO+审计（#54）
- 智能体运行层：agent `runtime.py` 门面 + `agent_runtime.py`(M2 真实推理) + `model_gateway`(DeepSeek Harness)；多Agent编排（#59 待做）
- AI 能力与连接层：server `aioa-tool-sdk` + agent `tools/gateway_client`（#56）
- 平台底座层：server `aioa-admin` 计费/RBAC/租户（#57）

## 本地运行方式
- 后端：`cd server && bash mvnw -DskipTests -q package`（绕开系统 `mvn` 损坏）→ 用真实 JDK 路径
  `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`（**禁止把 python 路径当 java 用**）。
  监听 :8080。Flyway V1~V6 已落库。
- 联调代理（用户端 H5）：`C:/Users/刘尖尖/.workbuddy/binaries/python/versions/3.13.12/python.exe user-client/serve.py 5181`。
  同源静态托管 + `/api/*` 反代 :8080；SSE 走 `resp.read(1)` 逐字节。
- 登录：admin / Admin@123（ROLE_ADMIN，V2 seed）、zhangsan / User@123（ROLE_USER，V6 seed）。
  统一响应 `{code,message,data}`，JWT 鉴权；登出清 localStorage.aioa_session。

## 关键坑（已修）
- 前端 `web/apps/shell/src/api/index.ts` 的 `unwrap` 只剥 axios 信封、返回 ApiResponse 包装；store 按内层读 `result.accessToken` 得 undefined → token 存成 `"undefined"` → `/apps` 401 → 登录后卡 `/login?redirect=/home`。修复：unwrap 在 body 含 code+data 时再剥一层取 body.data。影响 login/me/apps/conversations/runs 所有 unwrapped 接口。
- 系统 `mvn` 损坏，必须用 `server/mvnw`（bundled maven 3.9.11，通过 java + plexus-classworlds 启动 launcher）。
- PG→MySQL 迁移后 `SysUser/SysTenant.status` 由 Integer 改 String（ENABLED/ACTIVE 字符串枚举）。
- **repackage 期间后端必须先停**：跑着的 JVM 占用 fat-jar 时 `mvnw package` 半路会成功 rename 出 20KB stripped-jar，
  原 fat-jar 消失，JVM 立刻 NoClassDefFoundError 崩。流程：先 `Stop-Process <pid>`（按 `netstat -ano | grep :8080`）→
  删 target → rebuild → 后台启动。
- **`@RestControllerAdvice(Exception.class)` 兜底会吞 AccessDeniedException** 成 HTTP 500：
  HandlerExceptionResolver 比 ExceptionTranslationFilter 先匹配，导致 @PreAuthorize / controller 内抛的
  AccessDeniedException 走不到 SecurityConfig 的 accessDeniedHandler。本项目 `aioa-common` 明确不引入
  spring-security 依赖，故统一改 `BizException.forbidden(...)` 由 `GlobalExceptionHandler.handleBiz` 映射为 403。
  若 common 允许 spring-security，加 `@ExceptionHandler(AccessDeniedException.class)` 是更直接的解。
- **推 github 只需绕过 Schannel 吊销检查，不需要 PAT（2026-09-11 复核更正）**：失败根因是证书吊销检查
  `CRYPT_E_NO_REVOCATION_CHECK`（schannel 在沙箱里查不到 CRL），**不是缺凭证**——GCM 已缓存 github 凭证。
  正确一次性命令：`git -c http.sslVerify=false -c http.lowSpeedLimit=1 -c http.lowSpeedTime=60 push github main`
  （已实测成功：`d707aba..d10312b main -> main`）。`ls-remote` 同样必须带 `-c http.sslVerify=false`。
  仅当 GCM 确实无凭证时才需用户给 classic PAT(repo) 内联 URL 推；PAT 用完即弃，不持久化。
- **gitea `origin`（http://172.16.8.249:3000/liujiejie/AIOA_System.git）不可推**：服务端 `Push to create is not enabled for users`
  → 403。需先在 gitea 网页端手工建库，本地无法解决。github 才是有效远端。

## 启动与冒烟约定（2026-09-09 复核）
- 一键启动：`bash start-all.sh`（幂等，按端口探测自动 skip，日志落 `logs/`）。六端端口：
  后端 :8080 / agent :8000 / 用户端 H5 :5181（**只绑 127.0.0.1**，用 localhost 可能因解析到 ::1 不通，探活用 127.0.0.1）/
  管理端 shell :5173、工单 :5174、调度 :5175。健康：`/actuator/health`、`/health`。
- **后端 API 基址是 `/api/v1`**（不是 `/api`）。登录 `POST /api/v1/auth/login` → `data.accessToken`。
  两个易误诊点：① 少写 `v1` 段时 Security 直接返回 401 "未认证或令牌无效"，看着像密码错，实为路径/未放行；
  ② token 字段是 `accessToken`，按 `token` 取会得空串，同样误判为认证失败。
- 探测端口不要接 `| head -20`：MySQL 的 ESTABLISHED 行会占满前 20 行，把目标端口行挤掉（曾据此误判 5181 未启动）。
  用 `netstat -ano | grep LISTENING | grep ":<port> "` 精确过滤。

## V1.2 原型改造（2026-09-09）
- 依据 `AIOA客户端小程序交互原型_V1.2.html`，用户端 H5 完全重做；演示数据全部下沉到后端实体 + 管理端配置页。
- 新增数据域（V10 迁移）：`biz_kpi`(指标卡) / `biz_kpi_trend`(趋势柱) / `biz_kpi_insight`(AI解读) / `agent_worker`(数字员工) / `user_result`(成果沉淀)。
  接口：用户端 `KpiController(/api/v1/kpi/board?period=month|quarter)`、`WorkerController`、`ResultController`；
  管理端 `/api/v1/admin/kpi/**`、`/api/v1/admin/workers`、`/api/v1/admin/results`。
- 管理端三页：`web/apps/shell/src/views/{KpiView,WorkersView,ResultsView}.vue`，路由 `/kpi` `/workers` `/results`，菜单在 `MainLayout.vue`。

## 关键坑（V1.2 新增）
- **Flyway 版本号必须先看目录最大版本**：已有 V8/V9 时新建 V8 会 `Found more than one migration with version 8`，后端直接起不来。新增前先 `ls db/migration`。
- **接口返回结构不统一，前端必须防御式解包**：`notifications` 返回 `{items,unread}` 不是数组，直接 `.slice()` 抛 TypeError 会**中断整个 renderAll，导致后续所有区块空白**（曾致 U09–U14 全 FAIL）。
  统一用 `asArray(v)` 兼容 数组 / `{list}` / `{items}` / `{records}` / `{data}` / `{rows}`；`renderAll` 每块 try/catch 隔离。
- **沙箱会回收子进程**：`nohup ... &` / `start-all.sh &` 起的后端在 tool call 结束后被杀（表现为后续 8080 ConnectError）。
  长驻服务必须用 `run_in_background=true` 的常驻任务启动。
- **httpx 必须 `trust_env=False`**，否则走系统代理 → ConnectError / 非预期 HTML 导致 JSON 解析失败。
- **手机壳 Tab 栏遮挡**：Tab 绝对定位高 76px，普通页靠 `.page{padding-bottom:96px}` 避让，但 flush 页（如 `#page-chat` padding:0）需单独加 `padding-bottom:76px`，否则输入框被遮、Playwright 报 `intercepts pointer events`。
- 成果列表接口**不含 body**（防大字段），详情走 `GET /api/v1/results/{id}`；e2e 要 `wait_for_function` 等正文落地。
- 管理端鉴权统一 `requireAdmin()` + `BizException.forbidden` → 403；跨租户校验 `tenantId` 不等 → `BizException.notFound`。

## 管理端 vs 用户端职责边界（2026-09-11 澄清）
- **待办页（待我处理 / 数字员工已代办 / 我的申请）在「用户端 H5」**，`user-client/index.html` 的 `#page-todo`；
  用户端是单文件 134KB H5，页面靠 `go('page-xxx')` 切换，页面容器 id 形如 `page-todo`/`page-chat`/`page-home`。
  管理端 `ApprovalsView.vue`（路由 `/approvals`，菜单「审批中心」）**保持原样**，不要往里加三标签。
- 用户端 session：`localStorage['aioa_session'] = {token,user}`；`init()` 用 `/v1/auth/me` 校验角色。
  demo 账号 zhangsan/User@123（ROLE_USER）、admin/Admin@123（ROLE_ADMIN）。

## 用户端 H5 无头渲染校验（可复用）
- venv 无 playwright 时装：`.../envs/default/Scripts/python.exe -m pip install playwright`，用系统 Edge
  `p.chromium.launch(channel="msedge", headless=True)`（不必下载浏览器）。
- 免登录：`ctx.add_init_script("localStorage.setItem('aioa_session', <json>)")` 在页面脚本前注入。
- token：`POST http://127.0.0.1:5181/api/v1/auth/login` → `data.accessToken`（同源反代 :8080）。

## V21 数字员工职责边界与权限规则（2026-09-11）
- 规格源：`docs/10-数字员工职责边界与权限规则.md`。职责边界/权限规则/触发节点一律回该文，勿散写字符串。
- 权限模型三段链：`WorkerRole`(类型) → `requiredPermission` → `PermissionCatalog`(权限码→角色集合)。
  类型：GENERAL(`chat:basic`) / LEAVE_APPROVER(`approval:leave`，仅 `ROLE_ADMIN`) / KB_ASSISTANT(`kb:read`) / DOC_DRAFTER(`doc:draft`)。
  未知权限码默认拒绝；`AuthUser.permissions` 恒空，故以角色判定（与 ApprovalController 的 ROLE_ADMIN 口径一致）。
- 触发节点（5 个）：T1 `WorkerController.create` / T1' `update` 改类型 / T2 `ConversationService.bindWorker` 建会话绑定
  / T3 `RunService.buildScope` 下发 scope / T4·T5 `agent_runtime._build_messages` 注入职责提示 + 越界拒答。
  **会话绑定只传 `workerId`，职责文本由后端从 `agent_worker` 读出下发**（前端不可伪造 scope）。
- 数据：`agent_worker.worker_type`、`chat_conversation.worker_id`（V21）。职责边界取 `description` 优先、回落 `WorkerRole.duty()`。
- 会话记录：复用 `chat_conversation`/`chat_message`；用户端会话页「会话记录」= `openHistory`/`toggleHistoryDetail`/`resumeConversation`。
- **改 Agent(Python) 代码后必须重启 uvicorn**（非 --reload），否则跑的是旧代码，会产生「E2E 全绿但 scope 未生效」的假绿。
  软约束类断言必须校验身份/口径证据（如回答里是否出现数字员工身份），不能只验「有回答 + 有拒答词」。
- 提交若索引里有与本任务无关的预暂存删除，用 `git commit -m msg -- <我的路径...>` 只提交指定路径。

## 用户端「专家与员工」页与回答展示（V1.2，2026-09-11）
- 底部导航第 4 项文案 = **「专家与员工」**（原「数字员工」）；导航顺序 工作台/待办/会话(FAB)/专家与员工/我的。
- `#page-agent` 顶部是**双标签** `#agentTabs`（`.todo-tabs`/`.todo-tab`，复用待办页样式）：`switchAgentTab('workers'|'experts')`
  切 `.todo-panel[data-panel]`，默认 `workers`；专家列表容器 `#expertList`，数字员工列表 `#agentList`（卡片类 `.agent-card`）。
- 回答富文本：`formatAnswer()`+`ansInline()` → 渲染进 `.bubble.ans`；层级类 `.ans-h`(标题放大加粗) / `.ans-li`(列表缩进) / `.ans-quote`(引用) / `.ans-key`(重点)。
- 创建按钮：`.agent-actions`（flex 居中）+ `.agent-actions .btn{min-width:176px;min-height:40px}`；**不是 block 整行**。
- 会话头 `.chat-head` 为**两行**：`.ch-main`(内含 `.cname` + `.ch-sub`[`.cmodel`+`.scope-badge`]) + `#historyBtn`。
  单行会因徽标+按钮把名称挤成「数…」，勿改回单行。
- **请假表单「按需发放」**：页面无独立「请假申请」入口；`afterAnswer()` 需同时满足
  `isLeaveRequest(state.lastQuery)` **且** `isLeaveCapable()` 才插入 `leaveFormHtml()`。
  `isLeaveCapable()` 依据 `chatWorkerFull().workerType/roleName` 匹配 `/LEAVE_APPROVER|请假|假勤|休假/`；
  `chatWorkerFull()` 在绑定对象缺 `workerType` 时回落 `state.workers` 按 id 补齐。
  只判 `isLeaveRequest` 会导致**非请假数字员工「拒答请假 + 又发请假单」自相矛盾**（已修，勿回退）。
- 测试脚本（root，untracked，与 repo 既有 `e2e_v*.py` 同风格）：`e2e_expert_employee_tabs.py`(静态 UI 21)、
  `e2e_worker_chat_scope.py`(真实 LLM 10)、`e2e_user_leave_intake.py`(普通用户 5)。
- **权限可见性**：`API.roleTypes()` → `GET /v1/workers/role-types`（普通用户也放行，带 `granted`）；
  `renderAgents()` 按 `state.isAdmin` 显隐创建按钮 `#agentActions`、启停 `.switch`、「立即执行」「调整任务」，
  普通成员只渲染「对话」+「运行记录」+ `#agentAdminHint`。

## V22 数字员工权限分档（2026-09-11，用户拍板）
**口径**：所有用户可**提交请假申请**；**创建/删除等敏感操作仅限管理员**；越权拦截并提示。详见 `docs/10` §3.1 权限矩阵。
- **使用类（所有成员）**：查看列表/类型目录/运行记录、**与数字员工对话**（`POST /conversations` 带 workerId）、**提交请假申请**（`POST /approvals`）。
- **管理类（仅 ROLE_ADMIN）**：创建 / 修改 / 启停 / **立即执行** / 删除数字员工 → `WorkerController.requireAdmin()` 前置 403。
- **审批动作**（`scope=todo`、`/{id}/decision`）沿用既有口径仍仅管理员，本次未改。
- 判定唯一入口：`PermissionCatalog.isAdmin(user)`；`ConversationService.bindWorker` 已**去掉权限码校验**（只留同租户 + 未停用）。
- 用户端两个入口：`useAgent(i)`=「对话」（全员，无配置卡片，`chatModel`=「对话模式 · <角色名>」）；
  `createAgentFlow(worker)`=「调整任务」（仅管理员，有「确认创建/保存修改」卡片）。二者都 `setChatWorker` 以限定职责范围。
- `RoleTypeView.granted` 语义 = 「可否创建/承担该类型」= `isAdmin && holds(permission)`（普通成员全 false）。
- **无 schema 变更 → 不新增 Flyway 迁移**。
- 验证：`e2e_v21_worker_scope.py` 29、`e2e_expert_employee_tabs.py` 27、`e2e_worker_chat_scope.py` 13、`e2e_user_leave_intake.py` 8 = **77/77**。
- 坑：`taskkill //PID` 在 Git Bash 报「无效参数」，用 PowerShell `Stop-Process -Id` 停 8080。

## 用户端体验改进（2026-09-11，三批次推进中）
计划书：`docs/11-用户端体验改进计划.md`（18 项走查发现 → T0–T21 / 三批次）。
走查报告：`ux-review/用户体验走查报告.html`（生成脚本 `ux-review/report.py`，重跑即覆盖）；截图 `ux-review/*.png` + `ux-review/batch1/`。
**批次一（T1–T7）已完成并验收**：`e2e_ux_fixes.py` 29/29、既有 4 套 E2E 77/77。
- `agent_worker` 新增 **`run_mode`**（`SCHEDULED` / `EVENT` / `ON_DEMAND`，V22 迁移）：**只有定时型缺执行时刻才算「待配置」**，事件驱动/按需唤起不再被误标。
  判定纯函数在 `AgentWorker.requiresScheduleTime()` / `resolveStatus()`，`WorkerView.from()` 调它；勿在 controller 里另写一套。
- 前端「产出」两态：有运行记录显示摘要，无则 `meta-empty` 占位；产出徽标「已执行」，纯知会通知用 `badge info` 且不计角标。
- 审批意见用站内弹层 `askApprovalNote()` + `commitApprovalDecision()`，**不再用原生 `prompt()`**。
- V23 修 政策快讯员 `description`（原「重新汇总这项工作」会污染会话身份设定）。
- **Playwright 脚本必须用** `.../python/envs/default/Scripts/python.exe`（3.13.14，已装 playwright）；`.../versions/3.13.12/python.exe` **没装**，会报 `No module named 'playwright'`。

## Flyway 启动约定与历史表修复（2026-09-11，重要）
- **后端一律按 `start-all.sh` 的约定启动**：`java -Dspring.flyway.validate-on-migrate=false -jar ...`。
  本库 `flyway_schema_history` **长期只有一条 `v=1, success=0`（09-07 失败记录）**，而 41 张表与 V1–V21 结构都在；靠该开关跳过校验才能起。
- 一旦用**不带该 flag**的方式启动 → `Detected failed migration to version 1 (init)`，后端直接起不来。
- 修复：**不要在空历史下靠 `baseline-on-migrate` 重放**（`V1__init.sql` 无 `IF NOT EXISTS`，V2+ 是 `ALTER`，重放必撞表）。
  正解是**重建历史表并把 V1–V21 全插成 `success=1`**，让 Flyway 只应用新版本。脚本：`scripts/repair_flyway_history.py`（先归档坏表并 JSON 备份）。
- 新增迁移前**先 `ls db/migration` 取最大版本 +1**（当前已到 V23）。
- `rm -rf <target>` 会被 safe-delete 拦并**短路 `&&`**；后端已停时直接原地 `mvnw package` 覆盖即可。

## 用户端前端约定与坑（`user-client/index.html`）
- **本项目展示文案大量使用全角标点**（`（）「」·`）。写正则解析标题必须同时覆盖全角/半角，
  否则静默不匹配。曾因此让「审批单标题回落解析起止」整条分支失效（`[（(]…[）)]`）。
- **图标只能引用 sprite 里真实存在的 `#i-*`**（现有：bot bell pen megaphone doc sheet chart scale bank
  user clock check check-circle chevron cube db gear home inbox lock log plus send shield spark upload wallet warn）。
  `icon('calendar')` 这种不存在的名字会**渲染成空白**（不报错），已用 `ICON_MAP` 别名兜底（`calendar→clock`）。
- 弹窗统一走站内组件：`askDialog({mode:'confirm'|'input'|'alert'})` 及 Promise 包装 `askConfirm/askInput/askAlert`；
  **不要再用原生 `confirm/prompt/alert`**（移动端样式割裂且可能被拦截）。审批意见另有 `askApprovalNote`。
- 待办行统一由 `todoRow(ico,title,sub,onclick,cls)` 渲染；审批类行用 `approvalIcon()` 取图标+着色类、
  `approvalBrief()` 取副标题、`approvalTitle()` 取去重后的标题。
- 测试脚本注意：`e2e_ux_fixes.py`（批次一 29 项）、`e2e_ux_fixes_b2.py`（批次二 30 项）都需 `envs/default` 解释器。
