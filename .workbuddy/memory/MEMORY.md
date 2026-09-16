# AIOA 长期记忆（精简版；日期细节见同目录 YYYY-MM-DD.md）

## 1. 项目与运行
- AIOA=地级市 AI 公共服务平台。Vue3 管理端 shell(`web/apps/shell`) + SpringBoot 单体(`server/` 8 Maven 模块) + MySQL8(库`aioa`,root 无密码) + FastAPI agent(:8000) + 用户端单文件 H5(`user-client/index.html`)。方向：**改代码对齐设计文档**（五层架构）。
- 规格源：`docs/10` 职责边界 · `docs/14` 账号 · `docs/15` 权限矩阵 · `docs/16` 组织作用域 · `docs/19` 七项优先事项(**进度只回写此文**) · `docs/20` 全链路 E2E · `docs/21` 层级流转 · `docs/22` 登录口径 · `docs/23` 权限审批与组织关联改造。
- 重打包：**先停 :8080** → `cd server && bash mvnw -DskipTests -q clean package` → `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`。系统 `mvn` 损坏只能用 `mvnw`；**勿 `rm -rf target`**（用 `mvnw clean`）。
- 改 `agent/app/**` 必须重启 uvicorn（非 `--reload`）。`bash start-all.sh` 一键起（幂等，日志 `logs/`）。
- 端口 8080/8000/5173；H5 :5181 **只绑 127.0.0.1**。探端口 `netstat -ano|grep LISTENING|grep ":<port> "`，**不接 `| head`**。**长驻服务必须用后台常驻任务**（`nohup &` 被沙箱回收→ConnectError）。
- 口令：租户侧全 `User@123`（含 `dsj_admin`）；平台 `admin/Admin@123`。账号：`zhangsan`(t0) · `dsj_admin`(t2 租户管理员) · `fagai_admin`(t2 inst1 机构管理员) · `fagai_liu`(t2 dept10 负责人) · `fagai_li`(t2 **dept11** 成员) · t9 全链 `znkj_admin`(3142)/`znkjyf_admin`(3143)/`znsfb_ldr`(3144)。
- Flyway：新增前 `ls .../db/migration | sort -V | tail -3` 取实际最大+1（**当前 V44**）。已应用迁移**不可改**（checksum），只能追加。文档里的版本号只是预测。

## 2. 接口与权限
- 基址 `/api/v1`。登录 `POST /api/v1/auth/login` `{username,password,tenantName?}` → `data.accessToken`（**不是** `token`）。少写 `v1`→401，易误诊为密码错。
- **业务错误=HTTP200+`code!=0`**；仅 401/403/404 改状态。**跨租户一律 404**（不泄露存在性），同租户越权才 403。`/auth/logout` 只留审计、**不吊销令牌**。
- 企业端 `/api/v1/org`，租户端 `/api/v1/tenant`（漏 `/org`→404 `NoResourceFoundException`，日志像 500）。
- 审批：`POST /api/v1/workflow/tasks/{taskId}/decide` `{decision:APPROVE|REJECT}`；待办 `GET /workflow/tasks?scope=todo|mine|cc`，行 `id` 当单据号；计数 `GET /workflow/tasks/summary`。
- 脚本 `httpx` 必须 `trust_env=False`。Playwright 用 `envs/default/Scripts/python.exe`+`channel="msedge"`（`versions/3.13.12` 无 playwright）。
- 角色层级 `ROLE_ADMIN`>`ROLE_TENANT_ADMIN`>`ROLE_ORG_ADMIN`>`ROLE_DEPT_LEADER`>`ROLE_MEMBER`。`OrgGuard`：读 `requireOrgUser()`、写 `requireOrgWriter()`、审批 `requireApprover()`（**含 TENANT_ADMIN+ROLE_ADMIN**；用 requireOrgUser 会把末级/平台审批人全挡掉）。
- 三段链 `WorkerRole`→`requiredPermission`→`PermissionCatalog`，**未知码默认拒绝**。前端常量唯一入口 `constants/permissions.ts` 须与后端同源；**菜单/路由/接口三层必须同源**（漂移=菜单不显示+路由重定向+403→页面全空）。
- 新增请求体字段一律「**缺省兼容**」（`null` 跳过校验，显式空白才拒），否则既有 E2E+H5 集体变红。

## 3. 关键坑（已修，勿回退）
1. `aioa-common` **不引 spring-security** → `@RestControllerAdvice(Exception)` 把 `AccessDeniedException` 吞成 500。统一 `BizException.forbidden()`→403；`NoResourceFoundException` 已补 404。
2. 前端 `api/index.ts` 的 `unwrap` **必须校验 `code`**：body 含「数字 `code`+`message`」即按信封处理，`code≠0` 抛 `ApiError`。旧实现只在含 `code`+`data` 时剥壳，而后端 `non_null` 让失败响应 `data` 键消失 → 整封信封当业务数据。「页面空白无数据」基本都此根因。
3. repackage 前必须停 JVM，否则 fat-jar 被 rename 成 20KB stripped-jar，运行中 JVM `NoClassDefFoundError` 崩。
4. 给 Java `record` 加字段要全局搜构造点（`grep -rn "new XxxView(" server/ --include=*.java`），漏一处即编译失败，且 `mvnw -q package` 失败可能很安静。
5. 接口返回结构不统一 → 前端 `asArray()` 兼容 数组/`{list|items|records|data|rows}`；`renderAll` 每块独立 try/catch（否则一块抛异常后续全空白）。比对分页总量用 `total`，**不能用 `len(list)`**。
6. H5 单文件：页面 `go('page-xxx')`；session `localStorage['aioa_session']={token,user}`；无头校验用 `add_init_script` 注入；改完先 `node scripts/_syntax_h5.js`。图标只引用 sprite 真实存在的 `#i-*`（不存在**静默留白**）。Tab 栏高 76px，flush 页需单独 `padding-bottom:76px`。
7. 额度闸门判据 `state.quotaInfo.exhausted===true`（**勿**用数字型默认值表达「未知」，`state.left` 初值 0 曾致误判「额度用完」）。复位 `scripts/reset_demo_quota.py`。
8. 审批流解析优先级：机构专属 > 租户默认(`institution_id=0`) > 内置单级兜底。`audit_log` **永不 UPDATE**。假种 `quota_days_per_year=0`=不占额度只走审批（`quotaTracked=false`）。
9. 审核态闸门：V34 起租户管理员建的内容 `audit_status=PENDING`，对成员不可见、不被调度；V36 权限申请**终态回调才置 ACTIVE 并发放**（`granted_by/at`=终态处理人/时间）；`expert_config` 生效解析**必须过滤 `audit_status='APPROVED'`**。终态回调里 `order` 是**决策前**快照，意见/审批人须回查 `approval_task`。
10. 成果列表接口**不含 body**，详情走 `GET /api/v1/results/{id}`。登出先 `clearSession()` 再 best-effort 远端；`<router-view>` 必须带 `sessionActive &&` 闸门。
11. `aioa-resource` 与 `aioa-org` **互不依赖**；只有 `aioa-chat` 同时依赖二者。需同时读「权限/计费/工具」与「组织/审批/假种/知识库」的功能只能落 `aioa-chat`。
12. **审批链递推(V39)**：`ApprovalFlowService.expandNodes()` 遇 `APPLICANT_SUPERIOR` **不展开固定 steps_json**，改用 `superiorLadder()` 从「申请人层级+1」起逐级展开，跳过 null/申请人本人(自审防护)/重复人。兜底分支必须把 `effectiveType` 置为**实际生效类型**。
13. **V41/V42 职务与知会**：`org_duty`(租户级职务字典 DEPT_PRINCIPAL/DEPT_DEPUTY/ORG_LEADER/STAFF)+`org_member.duty_code` 是「谁是部门负责人」的**唯一权威口径**（原 27/8/3 三口径已收敛）。steps_json 新增 `levels`(1=只批一级) 与 `cc`(知会→生成 `task_role='CC'` 任务，**不阻塞**流程、不进 todo、不可 decide)。
16. **V43 二期/三期（部门申请 + 知会已读）**：`approval_order.applicant_type`(`USER`|`DEPARTMENT`)+`applicant_department_id`、`permission_grant.applicant_type`、`approval_task.cc_read_at`。口径：① 部门申请起点 = **`ORG_ADMIN`**（跳过 DEPT_LEADER，保留自审防护与 levels 截断）；② 负责人判定**只认 `duty_code='DEPT_PRINCIPAL'`**，`job_title` 不作权限依据；③ 跨机构/跨租户/平台 → **404**、同机构非正职 → **403** 且**均不落库**；④ `summary.cc` 固定为**总条数**（不因已读减少），未读另开 `ccUnread`；⑤ **底部「待办」角标不计入 CC 的站内通知**（`tab = 待审数 + 未读通知数(剔除 refId ∈ 我的抄送单)`，仅 `user-client/index.html` 前端一处）；⑥ 授权仍发给**提交人本人**（部门共享权限未排期）。知会引擎侧无需改动——`expandCcNodes` 与 `bizType` 无关且四重过滤齐备。
14. **同类播种器必须实测**：`ApprovalFlowProvisioner(@EventListener(TenantProvisionedEvent))` 只在建机构时触发 + 内部 try/catch 吞异常 = **失败静默**。
15. **软删+唯一键**：`sys_user.username` 唯一键**覆盖软删行**，`AccountProvisioner.resolveOrCreate` 须先查软删行再 `reviveUser`，否则重建同名管理员 500。

## 4. 已知缺口（docs/20 发现；勿当回归，也不要用放宽断言掩盖）
- D-1 无状态 JWT 无服务端吊销（logout 后旧 token 仍可用）。D-2 路径参数类型不匹配→500（应 400）。D-3 H5 对 `/approvals?scope=todo` 无条件调用致成员 403（已 try/catch）。D-4 无 favicon → 每次 404。
- D-5/6/7 孤儿与残留（`leave_balance` 3 行、`org_department` 6 条越权残留、`leave_type` 9 条 `V33ANNUAL*` 假种），均 tenant 4。D-8 新租户初始化缺口（审批流已由 Provisioner 修复，假种播种待补）。D-9 审批链固定模板**已 V39 修复**；残留 cosmetic：3142/3143 昵称均「傅宸」。

## 5. E2E 套件矩阵（`scripts/e2e_*.py` 已 gitignore，不入库）
- `e2e_full_system.py` **152/152**（13 段跨层串联；`--no-browser` 跳渲染段）——**每轮收口必跑**。内置 `kchk()` 把「已知缺口」与「跑红」分桶（`GAP` 不计失败）。
- 最近实测（V44 收口）：`e2e_v43_dept_applicant` 41/41 · `e2e_v43_cc_read` 40/40 · `e2e_v41_duty_levels` 48/48 · `e2e_v39_applicant_superior` 49/49 · `e2e_v36_grant_expert_review` 64/64 · `e2e_admin_personnel_scope` 57/57 · `e2e_v32_org_scope` 51/51 · `e2e_v36_stats_clamp` 66/66 · `e2e_v33_roles` 41/41 · `e2e_p0a_worker_intake` 41/41 · `e2e_worker_permission` 16/16 · `e2e_leave_flow_notify` 19/19 · `verify_v39_provisioner` 11/11 · `verify_config_effect` 11/11 · `e2e_login_tenant_name` 15/15 · `h5_v33_render` 28/28 · `admin_v39_todo_badge` 17/17 · `admin_v34_review_render` 8/8 · `check_org_structure_render` ALL PASS · `agent/tests/` 42 passed。
- **`h5_v33_render` 假红排查**：其「AI 解读」段依赖 agent。若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 → 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判。
- **套件会凭空消失**（gitignore）→ 跑前先 `ls scripts/ | grep -E "^e2e_"`，别照抄本表。只改前端也必须跑 `vue-tsc --noEmit`（少 import 常量表现为页面空白）。

### 断言纪律（写新套件必读）
- **禁固定页长/绝对条数**：用 `len(items)==min(total,size)`。判据：数据涨 10 倍、清库后该断言还成立吗？
- **审批用例先确认「申请人所在部门」的负责人**：首节点指派=该部门 `org_department.leader_user_id`。`fagai_li` 在 **dept 11**，负责人是 `fagai_admin`(user 4)，**不是** dept10 的 `fagai_liu`(user 7)；用错人→`decided=0`、状态全挂。
- **配额类套件必须自治**：`fagai_li` 年假仅 10 天；段首顶到「已用+10」；撤销链路用**不占额度**的事假；不传 `days` 且落周日返回「申请天数为 0」。
- **分清「口令/选择器改动」与「真回归」**：1001=口令错，1004=租户名不匹配。**按 `password_hash` 反查真实口令**再断言。
- **改权限/可见性/生效态/登录口径后必须全局搜既有套件旧口径断言并连跑两次**。历史遗留行≠代码 bug：可回填就**加 Flyway 回填迁移修数据、断言原样保留**，不可回填才限定本次运行数据并记因。**绝不为转绿而放宽断言。**

## 6. Git 远端
- `origin`=内网 Gitea `172.16.8.249:3000`：沙箱不可达 + push-to-create 关闭(403)，本地无解。
- **推 GitHub 只有 SSH over 443 这一条路（2026-09-16 实测修正）**：
  - HTTPS（`github` remote = `https://github.com/liujiejie7089/AIOA.git`）**现在需要凭证且当前无可用凭证**
    → `remote: Invalid username or token. Password authentication is not supported`。旧记录「无需 PAT」**已证伪**，不要再照抄。
  - SSH **22 端口被拒**（`Connection refused`）；**443 可用**：`ssh.github.com:443`（实测 `Hi liujiejie7089! You've successfully authenticated`）。
  - **必须显式 `-i` 指定私钥**：默认路径会因 HOME 中文用户名被 ssh 展开成乱码
    （`/c/Users/\301\365\274\342\274\342/.ssh`）而找不到 key → 误报 `Permission denied (publickey)`。
  ```bash
  GIT_SSH_COMMAND='ssh -i "C:/Users/刘尖尖/.ssh/id_rsa" -o IdentitiesOnly=yes \
    -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' \
    git push ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git main
  ```
- 约 5–8 分钟，**用后台任务**跑，别放前台等。
- 收口校验不靠 push 返回码：比对 `git rev-parse HEAD` 与 `git -c http.sslVerify=false ls-remote github refs/heads/main`
  （`ls-remote` 是读操作，**无需凭证**）。
