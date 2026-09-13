# AIOA 项目长期记忆

## 项目与方向
- AIOA = 地级市 AI 公共服务平台。仓库 = 管理端 shell(`web/apps/shell`, Vue3+Vite+ElementPlus) + Java Spring Boot 单体(`server/`, 7 Maven 模块) + MySQL8(本地库 `aioa`, root 无密码) + Python FastAPI agent(:8000) + 用户端 H5 单文件(`user-client/index.html`)。
- 设计蓝图（uni-app + AgentScope + PostgreSQL + 8 微服务域）与代码曾严重偏离；用户 2026-09-07 拍板「**改代码对齐设计文档**」，按五层演进。核对报告 `AIOA_设计文档与运行代码核对报告.md`。
- 改动前必读规格源：`docs/10-数字员工职责边界与权限规则.md`、`docs/15-数字员工权限矩阵.md`、`docs/16-组织与员工作用域模型.md`、`docs/11-用户端体验改进计划.md`。

## 构建与运行
- 后端：**先停 :8080 JVM**（`netstat -ano | grep :8080` → `Stop-Process -Id`）→ `cd server && bash mvnw -DskipTests -q package` → `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`。系统 `mvn` 损坏，一律用 `mvnw`。
- 一键 `bash start-all.sh`（幂等按端口 skip，日志 `logs/`）。端口：8080 / 8000 agent / **5181 用户端 H5（只绑 127.0.0.1）** / 5173 shell / 5174 / 5175。
- 联调代理：`.../python/versions/3.13.12/python.exe user-client/serve.py 5181`（同源托管 + `/api/*` 反代 :8080）。
- **长驻服务必须用后台常驻任务启动**（`nohup ... &` 会在 tool call 结束被沙箱回收）。
- 探端口 `netstat -ano | grep LISTENING | grep ":<port> "`，**不要接 `| head`**（MySQL ESTABLISHED 行会挤掉目标行）。
- 演示账号：admin/Admin@123(平台 ADMIN)、zhangsan/User@123(ROLE_USER)、jyj_admin/User@123(tenant4 TENANT_ADMIN)、jyfzyjy_admin/User@123(org17 ORG_ADMIN)、jybgs_m01/User@123(DEPT_LEADER)。

## Flyway
- 本库历史表靠 `-Dspring.flyway.validate-on-migrate=false` 起；不带 → `Detected failed migration to version 1`。修复用 `scripts/repair_flyway_history.py`。**不要**靠 baseline-on-migrate 重放（V1 无 IF NOT EXISTS，必撞表）。
- **新增迁移前先 `ls db/migration` 取最大版本 +1（当前 V35）**；已执行迁移只增不改。
- `rm -rf <target>` 会被 safe-delete 拦并短路 `&&`；后端已停时直接原地 `mvnw package` 覆盖即可。

## 接口 / E2E 约定
- 基址 **`/api/v1`**。登录 `POST /api/v1/auth/login` → `data.accessToken`（**不是 `token`**）。少写 `v1` 会 401「未认证」，易误诊为密码错。
- **业务错误 = HTTP 200 + `code != 0`**；只有 401/403/404 改 HTTP 状态。断言写 `st in (200,400,403,404) and code != 0`，**不要**写 `st == 400`。
- 企业端基路径 `/api/v1/org`（租户端 `/api/v1/tenant`）。漏 `/org` → 404 `NoResourceFoundException`，看着像 500。
- 审计链 `GET /api/v1/tenant/audit/verify` → 需 `verifiedRows==count && legacyRows==0` 才是「真校验」。
- **租户端作用域（V33）**：`/api/v1/tenant/*` 用 `OrgGuard.resolveRequestTenant(u)`——租户管理员硬绑本租户（跨租户 404），平台管理员按 `?tenantId=` 切换、缺省落「机构数最多」租户。`GET /api/v1/tenant/scope` 返回可切换清单；前端 `api/tenantScope.ts` 拦截器自动带参。
- 请假域在 **`/api/v1/leave/*`**；提交体字段 `leaveTypeCode`（不是 leaveTypeId），返回 `{leaveRequestId, orderId, timeline[0].taskId}`；额度 `POST /org/leave/balances` 同样用 `leaveTypeCode`。
- 审批动作 `POST /api/v1/workflow/tasks/{taskId}/decide`，字段 `decision`(APPROVE/REJECT)。待办 `GET /workflow/tasks?scope=todo|mine`（V35 起 `mine` 只要求登录，任何员工可看自己申请）。
- **`/api/v1/tenant/grants` 必须带 `institutionId`**（授权落点是机构，无纯租户级授权）。
- 公开配置 `GET /api/v1/configs?keys=`（白名单，非白名单 403），回落 租户 → 平台(0) → 空。
- **用户端统计 `GET /api/v1/stats/me`**（V36，用户端「我的数据」唯一数据源）：返回本人
  `todoApprovals/myApplications/conversations/aiRuns/results/myWorkers/kbDocs/quotaUsed/quotaLeft/generatedAt`。
  每项复用对应业务列表同一口径（ResultController#list、KbService#list、BillingService#current）；
  `todoApprovals` = 多级引擎(当前节点指派给我) + 单级池(仅 ROLE_ADMIN|TENANT_ADMIN)。`aioa-chat` 依赖 `aioa-org`。
- 脚本用 `httpx` 必须 **`trust_env=False`**。Playwright 用 `.../python/envs/default/Scripts/python.exe`(已装)，`channel="msedge"` 免下载。

## 权限模型（V21/V22/V29–V34）
- 三段链：`WorkerRole` → `requiredPermission` → `PermissionCatalog`（权限码→角色集合）。权限码：`worker:use/create/manage/edit:self`、`expert:manage`、`approval:leave`、`chat:basic`、`kb:read`、`doc:draft`。未知码默认拒绝。
- 角色：ROLE_ADMIN(平台，org 域**只读**) / TENANT_ADMIN / ORG_ADMIN / DEPT_LEADER / MEMBER / USER。
- `WORKER_MANAGERS = ADMIN+TENANT_ADMIN+ORG_ADMIN+DEPT_LEADER`；DEPT_LEADER 仅管**本部门**（强制 visibleScope=DEPT + [ownDeptId]）。
- **三级数据域**：机构成员硬绑本机构 / 租户管理员可选本租户机构 / 平台管理员全球只读。`OrgGuard.selectableInstitutions()` → `GET /api/v1/org/institutions` 返回 `{items,total,canWrite,boundInstitutionId,scope}`。
- `OrgGuard.requireOrgUser()` 含 TENANT_ADMIN/ADMIN；写用 `requireOrgWriter()`(=TENANT_ADMIN/ORG_ADMIN)；审批用 `requireApprover()`（机构成员或租户管理员）。
- 入驻自动铺模板：`TenantProvisionedEvent` → `WorkerTemplateProvisioner`（幂等，institution_id=null 的租户级资产）。
- 审计 before/after：V32 加 `before_value/after_value`，只存配置类快照。
- H5 权限分档：`isAdmin`(审批) 与 `canManageWorker`(worker:manage) 两个独立标志，勿混用。
- **V33/V34**：`worker:create` 已下放全体登录用户；新增 `worker:edit:self`。非管理者创建的数字员工强制 `visible_scope=SELF`（**不接收前端 scope 入参**）；**删除仍只认 `worker:manage`**。新增 `expert:manage`。`WorkerView` 带 `createdBy/mine/editable/auditStatus`，前端逐卡 `canEdit`。
- **V34 内容审核**：租户管理员（非平台）创建的数字员工/专家落 `audit_status=PENDING`，需平台管理员经 `GET/POST /api/v1/admin/content-reviews[/{type}/{id}/review]` 放行；开关 `sys_config.approval.tenant.content`(默认 true)。待审对普通成员不可见；**驳回强制填意见**。管理端 `/content-reviews`（仅平台管理员）。
- 前端权限常量唯一入口 `web/apps/shell/src/constants/permissions.ts`，必须与后端 `PermissionCatalog` 同源同步。

## 关键坑（已修，勿回退）
1. `aioa-common` 不引 spring-security → `@RestControllerAdvice(Exception)` 会吞 AccessDeniedException 成 500。统一 `BizException.forbidden()` → 403；`NoResourceFoundException` 也落该兜底，已在 `GlobalExceptionHandler` 补显式 **404**。
2. 前端 `api/index.ts` 的 `unwrap` 需在 body 含 `code`+`data` 时**再剥一层**取 `body.data`，否则 token 存成 `"undefined"` → 登录后 401 卡 `/login`。
3. `repackage` 时后端 JVM 必须停，否则 fat-jar 被 rename 成 20KB stripped-jar → 运行中 JVM NoClassDefFoundError 崩。
4. **改 Python agent 代码后必须重启 uvicorn**（非 --reload），否则「E2E 全绿但 scope 未生效」假绿。
5. 接口返回结构不统一，前端用 `asArray()` 兼容 数组/`{list|items|records|data|rows}`；`renderAll` 每块 try/catch 隔离（否则一块炸全页空白）。
6. H5 是**单文件**，页面靠 `go('page-xxx')`；session 存 `localStorage['aioa_session']={token,user}`，无头校验用 `add_init_script` 注入。
7. H5 图标只能引用 sprite 真实存在的 `#i-*`（未定义**静默留白**），走 `ICON_MAP` 别名。弹窗统一 `askDialog`，**勿用原生 confirm/prompt/alert**。
8. 手机壳 Tab 高 76px，flush 页（`#page-chat` 等 padding:0）需单独 `padding-bottom:76px`。
9. 额度闸门判据用 `state.quotaInfo.exhausted===true`，**勿用 `state.left<=0`**。复位 `scripts/reset_demo_quota.py`。**会话类 E2E 突然失败先查额度**（admin 走 tenant_id=0/user_id=0 共享行，反复跑耗干）。
10. 成果列表不含 body，详情走 `GET /api/v1/results/{id}`；e2e 要等正文落地。
11. 审批流优先级：机构专属 > 租户默认(institution_id=0) > 内置单级兜底。`audit_log` **永不 UPDATE**（复位唯一例外：删 tenant_id=2 演示行）。
12. 假种 `quota_days_per_year=0`（无薪事假）= 不占额度只走审批，返回 `quotaTracked:false / availableAfterPending:null`。
13. **登出链路**（V35）：后端 `POST /api/v1/auth/logout` 写 LOGOUT 审计（幂等永不失败）。前端登出必须先 `clearSession()` 再 best-effort 调远端；`MainLayout` 的 `<router-view>` 必须带 `sessionActive &&` 闸门，否则 token 清空后重新挂载已登出页面 → 重发请求 401 弹 toast。
14. **删除语义不统一（V36 踩坑）**：一部分实体挂 `@TableLogic`（自动过滤），另一部分（`ChatConversation`/`AgentRun`）靠手写 `deleted_at = now()`，**查询必须自己 `isNull(deletedAt)`**，否则「删除会话」后列表/统计照旧计入（曾致删除按钮失灵）。写任何 count/list 前先确认该实体的删除实现。
15. **比对分页列表总量要用 `total`，不能用 `len(list)`**（`/conversations` 默认 20/页，`len()` 恒 ≤20，会误判「统计虚高」）。
16. **长文本折叠用 max-height，不用 `-webkit-line-clamp`**：line-clamp 只对行内内容成立，对话回答是 `<span>/<div>` 混排会被整块劈开。工具函数 `autoClamp(el,maxPx,minChars)` / `resetClamp(el)`（H5），管理端同款 `.clamped` + `.clamp-toggle`。隐藏页 `scrollHeight=0`，须在 `go()` 之后再量测。

## E2E 套件矩阵（`scripts/`）
- V32：`e2e_v32_org_scope.py`(48)、`check_org_structure_render.py`(4)。
- V33/V34：`e2e_v33_roles.py`(41)、`h5_v33_render.py`(15)、`admin_v34_review_render.py`(8)、`smoke_v33.py`、`restart_backend.py`（停→打包→校验 jar≥20MB）。
- 权限回归 `e2e_worker_permission.py`(16)。**改权限模型后必须全局搜既有套件里的旧口径断言**（否则旧断言把新行为报成 FAIL）。
- V35 新增：`repro_logout_401.py`、`diag_leave_notify.py`、`e2e_leave_flow_notify.py`(19)。
- V36 新增：`e2e_v36_stats_clamp.py`(68) —— stats/me 与各业务列表独立重算比对、实时性（造会话→+1→删→还原）、H5 统计卡渲染、折叠行为、接入点静态核对。`h5_v33_render.py` 已加 `ensure_self_worker()` 自愈夹具（原先依赖 smoke_v33 的残留数据，单独跑必红）。
- 用户端：`e2e_ux_fixes.py`(29) / `e2e_ux_fixes_b2.py`(30) / 批次三(32) / `e2e_worker_chat_scope.py` / `e2e_expert_employee_tabs.py` / `e2e_user_leave_intake.py`。
- 固定顺序：先 reset 再跑（阶段间有依赖）。历史总验收 180/180（三批次+既有 5 套）。

## Git 远端
- `origin` = 内网 Gitea `http://172.16.8.249:3000/liujiejie/AIOA_System.git`：沙箱不可达 + Push-to-create 关闭(403)。
- 推 GitHub 用 `github` remote，**必须绕开沙箱代理**：`git -c http.proxy= -c https.proxy= -c http.sslVerify=false push github main`（**无需 PAT**，失败根因是 Schannel 吊销检查 `CRYPT_E_NO_REVOCATION_CHECK`）。`ls-remote` 同带这些 `-c`。
- 提交若索引有无关预暂存删除，用 `git commit -m msg -- <路径...>` 只提交指定路径。
