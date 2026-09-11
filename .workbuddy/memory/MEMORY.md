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
- **GCM 在 headless 沙箱静默挂死**：Git Credential Manager 无缓存 GitHub 凭证时卡在 Schannel 吊销检查
  `CRYPT_E_NO_REVOCATION_CHECK`。解决：用户给 classic PAT(repo)，一次性内联 URL 推：
  `git -c http.sslVerify=false -c http.lowSpeedLimit=1 -c http.lowSpeedTime=30 push "https://<user>:<PAT>@github.com/<repo>.git" main`
  验证远端 `ls-remote` 必须带 `sslVerify=false`，否则报错信息里 URL 会被 git 自动抹凭证。PAT 用完即弃，不持久化。

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
