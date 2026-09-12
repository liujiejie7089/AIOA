# AIOA 项目长期记忆

## 项目本质与方向
- AIOA = 地级市 AI 公共服务平台 · AI 工作台。现仓库 = 管理端 shell(`web/apps/shell`, Vue3+Vite+ElementPlus) + Java Spring Boot 单体(`server/`, 7 个 Maven 模块) + MySQL8(本地库 `aioa`, root 无密码) + Python FastAPI agent(:8000)。
- 设计蓝图（uni-app 小程序 + AgentScope + PostgreSQL + 8 微服务域）与代码**严重偏离**；用户 2026-09-07 拍板「**改代码对齐设计文档**」，按五层演进。核对报告 `AIOA_设计文档与运行代码核对报告.md`。
- 改动前必读规格源：`docs/10-数字员工职责边界与权限规则.md`、`docs/15-数字员工权限矩阵.md`、`docs/16-组织与员工作用域模型.md`、`docs/11-用户端体验改进计划.md`。

## 构建与运行
- 后端：**先停 :8080 的 JVM**（`netstat -ano | grep :8080` → PowerShell `Stop-Process -Id`），再
  `cd server && bash mvnw -DskipTests -q package`，然后用
  `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`。
  系统 `mvn` 损坏，一律用 `mvnw`。**必须带 `validate-on-migrate=false`**（见 Flyway 段）。
- 一键启动 `bash start-all.sh`（幂等，按端口 skip，日志 `logs/`）。端口：8080 后端 / 8000 agent / **5181 用户端 H5（只绑 127.0.0.1）** / 5173 shell / 5174 工单 / 5175 调度。
- 联调代理：`.../python/versions/3.13.12/python.exe user-client/serve.py 5181`（同源托管 + `/api/*` 反代 :8080）。
- **长驻服务必须用后台常驻任务启动**；`nohup ... &` 会在 tool call 结束后被沙箱回收。
- 探端口用 `netstat -ano | grep LISTENING | grep ":<port> "`，**不要接 `| head`**（MySQL ESTABLISHED 行会挤掉目标行）。
- 演示账号：admin/Admin@123(ROLE_ADMIN)、zhangsan/User@123(ROLE_USER)、租户管理员如 jyj_admin。

## Flyway（重要）
- 本库 `flyway_schema_history` 长期只有一条失败记录，靠 `-Dspring.flyway.validate-on-migrate=false` 起；不带该 flag → `Detected failed migration to version 1` 起不来。
- 修复用 `scripts/repair_flyway_history.py`（重建历史表，V1–Vn 插成 success=1）。**不要**靠 baseline-on-migrate 重放（V1 无 IF NOT EXISTS，V2+ 是 ALTER，必撞表）。
- **新增迁移前先 `ls db/migration` 取最大版本 +1**（当前到 V34）；已执行迁移只增不改。
- `rm -rf <target>` 会被 safe-delete 拦并短路 `&&`；后端已停时直接原地 `mvnw package` 覆盖即可。

## 接口 / E2E 约定
- 基址 **`/api/v1`**。登录 `POST /api/v1/auth/login` → `data.accessToken`（**不是 `token`**）。少写 `v1` 会 401「未认证」，易误诊为密码错。
- **业务错误 = HTTP 200 + `code != 0`**；只有 401/403/404 改 HTTP 状态。断言写 `st in (200,400,403,404) and code != 0`，**不要**写 `st == 400`。
- 企业端控制器基路径 `/api/v1/org`（租户端 `/api/v1/tenant`）。漏 `/org` → 404 `NoResourceFoundException`，看着像 500。
- 审计链 `GET /api/v1/tenant/audit/verify` → 需 `verifiedRows==count && legacyRows==0` 才叫「真校验」。
- **租户端作用域（V33）**：`/api/v1/tenant/*` 用 `OrgGuard.resolveRequestTenant(u)`——租户管理员硬绑本租户（跨租户 404），平台管理员按 `?tenantId=` 切换、缺省落「机构数最多」的租户。`GET /api/v1/tenant/scope` 返回可切换清单；前端 `api/tenantScope.ts` 拦截器自动带参。
- 请假域在 **`/api/v1/leave/*`**（不是 `/workflow/leave/*`）；提交体字段 `leaveTypeCode`（不是 leaveTypeId），返回 `{leaveRequestId, orderId, timeline[0].taskId}`；额度 `POST /org/leave/balances` 同样用 `leaveTypeCode`。
- 审批动作 `POST /api/v1/workflow/tasks/{taskId}/decide`，决策字段 `decision`（APPROVE/REJECT 或 approve:true）。待办 `GET /workflow/tasks?scope=todo|mine`。
- **`/api/v1/tenant/grants` 必须带 `institutionId`**：授权以机构为落点，不存在纯租户级授权。
- 公开配置读取 `GET /api/v1/configs?keys=`（白名单，非白名单 403），回落顺序 租户 → 平台(0) → 空。
- 脚本用 `httpx` 必须 **`trust_env=False`**（否则走系统代理 → ConnectError）。
- Playwright 脚本必须用 `.../python/envs/default/Scripts/python.exe`（装了 playwright），`channel="msedge"` 免下载浏览器；`3.13.12` 那个没装。

## 权限模型（V21/V22/V29–V32）
- 三段链：`WorkerRole` → `requiredPermission` → `PermissionCatalog`（权限码→角色集合）。权限码：worker:use/create/manage、approval:leave、chat:basic、kb:read、doc:draft。未知码默认拒绝。
- 角色：ROLE_ADMIN(平台，org 域**只读**) / ROLE_TENANT_ADMIN / ROLE_ORG_ADMIN / ROLE_DEPT_LEADER / ROLE_MEMBER / ROLE_USER。
- `WORKER_MANAGERS = ADMIN+TENANT_ADMIN+ORG_ADMIN+DEPT_LEADER`；DEPT_LEADER 仅能管**本部门**员工（强制 visibleScope=DEPT + [ownDeptId]）。
- **三级数据域 scope**：机构成员硬绑本机构 / 租户管理员可选本租户机构 / 平台管理员全球只读。入口 `OrgGuard.selectableInstitutions()` → `GET /api/v1/org/institutions` 返回 `{items,total,canWrite,boundInstitutionId,scope}`。
- `OrgGuard.requireOrgUser()` 含 TENANT_ADMIN/ADMIN；写用 `requireOrgWriter()`(=TENANT_ADMIN/ORG_ADMIN)；审批用 `requireApprover()`（机构成员或租户管理员）。
- 入驻自动铺模板：`TenantProvisionedEvent` → `WorkerTemplateProvisioner`（幂等，institution_id=null 的租户级资产）。
- 审计 before/after：V32 加 `before_value/after_value`，只存配置类快照（不含运行输出）。
- 用户端 H5 权限分档：`isAdmin`(审批) 与 `canManageWorker`(worker:manage 角色) 两个独立标志，勿混用。

## 权限模型（V33/V34 增补）
- `worker:create` **已下放全体登录用户**（普通成员可自建 AI 助理）；新增 `worker:edit:self`（创建者改自己的）。
- 非管理者创建的数字员工强制 `visible_scope=SELF`（**源头就不接收前端 scope 入参**，改包也提不上去）；
  列表过滤 SELF 他人数据；**删除仍只认 `worker:manage`**（能建≠能删）。
- 新增权限码 `expert:manage`（ADMIN/TENANT_ADMIN/ORG_ADMIN）→ `ExpertConfigController` 改按权限码判定。
- `WorkerView` 带 `createdBy/mine/editable/auditStatus`，前端逐卡 `canEdit`（不再是整页 canManage）。
- **V34 内容审核**：租户管理员（非平台管理员）创建的数字员工/专家落 `audit_status=PENDING`，
  需平台管理员经 `GET/POST /api/v1/admin/content-reviews[/{type}/{id}/review]` 放行；
  开关 `sys_config.approval.tenant.content`（默认 true）。待审对普通成员不可见、不参与调度，
  创建者本人与管理员可见；**驳回强制填意见**；「从模板创建」同口径（防旁路）。
  管理端页面 `/content-reviews`（仅平台管理员，菜单+路由守卫同步）。
- 前端权限常量唯一入口 `web/apps/shell/src/constants/permissions.ts`，与后端 `PermissionCatalog` 必须同源同步
  （菜单/路由/接口三处不一致会导致「菜单能进但 403」或「接口开了菜单藏起来」）。

## 关键坑（已修，勿回退）
1. `aioa-common` 不引 spring-security → `@RestControllerAdvice(Exception)` 会吞 AccessDeniedException 成 500。统一 `BizException.forbidden()` → 403。
   同源问题：`NoResourceFoundException`（路径不存在）也落该兜底 → 500。已在 `GlobalExceptionHandler` 补显式 **404**，
   拼错路径不会再被误诊成「后端崩了」。
2. 前端 `api/index.ts` 的 `unwrap` 需在 body 含 `code`+`data` 时**再剥一层**取 `body.data`，否则 token 存成 `"undefined"` → 登录后 401 卡 `/login`。
3. `repackage` 时后端 JVM 必须停，否则 fat-jar 被 rename 成 20KB stripped-jar → 运行中 JVM 立刻 NoClassDefFoundError 崩。
4. **改 Python agent 代码后必须重启 uvicorn**（非 --reload），否则跑旧代码 → 「E2E 全绿但 scope 未生效」假绿。
5. 接口返回结构不统一，前端用 `asArray()` 兼容 数组/`{list|items|records|data|rows}`；`renderAll` 每块 try/catch 隔离（否则一块炸全页空白）。
6. 用户端 H5 是**单文件**（~134KB），页面靠 `go('page-xxx')`；session 存 `localStorage['aioa_session']={token,user}`，无头校验可用 `add_init_script` 注入。
7. H5 图标只能引用 sprite 真实存在的 `#i-*`，未定义的**静默留白**（不报错）；走 `ICON_MAP` 别名。弹窗统一 `askDialog`，**勿用原生 confirm/prompt/alert**。
8. 手机壳 Tab 高 76px，flush 页（`#page-chat` 等 padding:0）需单独 `padding-bottom:76px`。
9. 额度闸门判据用服务端 `state.quotaInfo.exhausted===true`，**勿用 `state.left<=0`**（默认值会被当业务事实而堵死对话）。复位 `scripts/reset_demo_quota.py`。**会话类 E2E 突然失败先查额度**（admin 走租户共享行 tenant_id=0/user_id=0，反复跑会耗干）。
10. 成果列表不含 body，详情走 `GET /api/v1/results/{id}`；e2e 要等正文落地。
11. 审批流优先级：机构专属 > 租户默认(institution_id=0) > 内置单级兜底。`audit_log` **永不 UPDATE**（复位时唯一例外：删 tenant_id=2 的演示审计行）。
12. 假种 `quota_days_per_year=0`（无薪事假）= 不占额度只走审批，返回 `quotaTracked:false / availableAfterPending:null`。

## E2E 套件矩阵（`scripts/` 与仓库根）
- V32 组织作用域：`scripts/e2e_v32_org_scope.py`（48，含 reset_fixture 物理删 E2E-V32% 机构 + 时间戳编码防撞）、`scripts/check_org_structure_render.py`（4，Playwright）。
- V33/V34（2026-09-13）：`scripts/e2e_v33_roles.py`（41，多角色全流程）、`scripts/h5_v33_render.py`（15，H5 空态折叠/场景/AI解读）、`scripts/admin_v34_review_render.py`（8，审核台渲染）、`scripts/smoke_v33.py`（配置+AI解读+自建自改）、`scripts/restart_backend.py`（停→打包→校验 jar≥20MB）。
- 权限回归：`e2e_worker_permission.py`（16；V33 起断言已改：普通成员可建但强制 SELF、他人不可见、不能删除；并在创建后补「平台放行」步骤）。
- **改权限模型后必须全局搜索既有套件里的旧口径断言**（否则旧断言把新行为报成 FAIL）。
- V24 入驻/请假：`scripts/reset_v24_demo.py` 可用；**`e2e_v24_onboarding.py` / `e2e_v24_leave_flow.py` 磁盘上已不存在**（未 git-tracked），需重跑时先确认。
- 用户端：`e2e_ux_fixes.py`(29) / `e2e_ux_fixes_b2.py`(30) / 批次三(32) / `e2e_worker_chat_scope.py` / `e2e_expert_employee_tabs.py` / `e2e_user_leave_intake.py`。
- 固定顺序：先 reset 再跑（阶段间有依赖）。三批次+既有 5 套历史总验收 180/180。

## Git 远端
- `origin` = 内网 Gitea `http://172.16.8.249:3000/liujiejie/AIOA_System.git`：沙箱不可达，且 Push-to-create 关闭（403）。
- 推 GitHub 用 `github` remote，且**必须绕开沙箱代理**（环境变量 `https_proxy=http://127.0.0.1:60448` 会让 git 连接超时）：
  `git -c http.proxy= -c https.proxy= -c http.sslVerify=false push github main`
  （**无需 PAT**，失败根因是 Schannel 吊销检查 `CRYPT_E_NO_REVOCATION_CHECK`）。`ls-remote` 同样要带这几个 `-c`。
- 提交若索引里有无关的预暂存删除，用 `git commit -m msg -- <我的路径...>` 只提交指定路径。
