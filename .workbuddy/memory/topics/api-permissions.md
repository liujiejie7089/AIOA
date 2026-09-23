# 接口口径与权限（原 MEMORY.md §2，2026-09-19 拆分）

## 登录 / 状态码口径
- 基址 `/api/v1`。登录 `POST /api/v1/auth/login` `{username,password,tenantName?}` → `data.accessToken`（**不是** `token`）。少写 `v1` → 401，易误诊为密码错。
- **业务错误 = HTTP200 + `code!=0`**；仅 401/403/404 改状态。
- **跨租户一律 404**（不泄露存在性），同租户越权才 403。
- 企业端前缀 `/api/v1/org`，租户端前缀 `/api/v1/tenant`（漏 `/org` → 404 `NoResourceFoundException`，日志像 500）。
- `/auth/logout` **V46 起服务端吊销令牌**（access+refresh 的 `jti` 写 `revoked_token`）——登出**两个令牌都要带**，只带 access 则 refresh 仍能换新令牌 = 没登出。

## 审批接口
- `POST /api/v1/workflow/tasks/{taskId}/decide` `{decision:APPROVE|REJECT}`。
- 待办 `GET /workflow/tasks?scope=todo|mine|cc`（行 `id` 当单据号）。
- 计数 `GET /workflow/tasks/summary`（`cc` 固定为总条数，未读另开 `ccUnread`）。

## 角色与守卫
- 层级 `ROLE_ADMIN` > `ROLE_TENANT_ADMIN` > `ROLE_ORG_ADMIN` > `ROLE_DEPT_LEADER` > `ROLE_MEMBER`。
- `OrgGuard`：读 `requireOrgUser()`、写 `requireOrgWriter()`、审批 `requireApprover()`（**含 TENANT_ADMIN + ROLE_ADMIN**；误用 `requireOrgUser` 会把末级/平台审批人全挡掉）。

## 权限链与前端常量
- 三段链 `WorkerRole` → `requiredPermission` → `PermissionCatalog`，**未知码默认拒绝**。
- 前端常量唯一入口 `web/apps/shell/src/constants/permissions.ts` 须与后端同源；**菜单 / 路由 / 接口三层必须同源**（漂移 = 菜单不显示 + 路由重定向 + 403 ⇒ 页面全空）。

## 专家模板（平台产 → 租户消费）
- `POST /api/v1/expert-config/templates` —— **仅平台管理员**（`PermissionCatalog.isPlatformAdmin`，即 `ROLE_ADMIN`）
  可建/改**全局模板**（`ai_expert.tenant_id=0`）。租户管理员/企业管理员调用 ⇒ 403（全局模板是全平台共享内容，
  文案要写「请用『从模板导入』」）。
- 幂等：同一 `(tenant_id=0, expert_key)` 重复提交 = 更新，不产生第二份；`key` 正则 `^[a-z][a-z0-9_]{1,31}$`
  且 `*` 是保留字（默认 AI 的 key）必须拒。
- **平台自建即生效**（`audit_status=APPROVED`）；租户「从模板导入」产生的**租户副本落 PENDING**，
  出现在平台管理员的内容审核台 —— 这条差异是刻意的，别顺手统一。
- 验收：`scripts/e2e_v64_expert_template.py`（25 项，用 `created` 标志同次闭环，可无限重跑）。

## 知识库（FR-F）可见性与管理口径（2026-09-21 定案）
- 列表口径 `KbStore.listVisible(tenantId, userId)`（MySQL / Milvus 同源，`MilvusFilter` 与 `KbRelationalDao` 必须逐字一致）
  = `tenant_id = 本租户 AND (user_id = 本人 OR user_id = 0 公共资源 OR scope = 'TENANT' 租户共享)`；跨租户零泄露（FR-B3）。
  **无机构/部门维度**：`kb_document.institution_id/department_id` 列存在（V24），但资源模块实体 `KbDocument` 没映射它们、可见性判定也没用。
- `GET /api/v1/kb/documents`（默认）= 上面那条口径，登录即可读（`kb:read` 全员）。
- `GET /api/v1/kb/documents?scope=tenant` = 租户全部资料，判据 **`PermissionCatalog.isAdmin`（平台管理员 ∨ 租户管理员）**；
  机构管理员 / 普通成员 → 403（**不放宽**）。
- `PUT` / `DELETE /api/v1/kb/documents/{id}`：跨租户一律 403；租户管理员（含平台）可管本租户**任意**资料；其余只能管本人上传的。
  改可见范围（PERSONAL ↔ TENANT）**就是「共享 / 取消共享」这个动作**，与 `scope=tenant` 同一判据，勿分叉。
- 管理端页面 `web/apps/shell/src/views/KbView.vue`：默认 tab 由 `canReadTenant = hasAnyRole(auth.roles, TENANT_SCOPE_ROLES)` 推导；
  非租户管理员不渲染「租户全部资料」tab、不发 `?scope=tenant` 请求；行级操作用 `canModify(row)` 收口（无权行显示「只读」）。
- 用户端 H5「我的知识库」（`user-client/index.html` 的 `renderKb()`）：默认只渲染前 **6** 条
  （`KB_PAGE=6`，后端按 `createdAt` 倒序 ⇒ 溢出的是**最早**那条），**超出时必须在同屏给「展开全部（共 N 份）」入口**
  （`state.kbExpanded` + `toggleKbList()`）。**截断可以有，但不能静默** —— 否则较早共享出去的资料永远看不到，
  而标题照写「共 N 份」。⚠️ 本机演示库只有 1~3 份，**不会自然触发**，改这块必须靠构造用例验。
- 机构知识库（FR-I，`/org/kb*`，`OrgKbService` + `OrgGuard`）：**后端能力完整但管理端零入口**
  （全仓 `web/apps` 搜不到 `/org/kb`）⇒ 按铁律「配置页 = 能力的唯一入口」，属**事实上不可用**；
  且 `attach(departmentId != 0)` 会写 `scope='DEPT'`，而 `listVisible` / `MilvusFilter` **都不认 `DEPT`**
  ⇒ 该档资料**除 owner 外无人可见**（FR-I1「按部门配置可见范围」名存实亡）。**待做项，非本次缺陷。**

## 兼容性纪律
- 新增请求体字段一律「**缺省兼容**」（`null` 跳过校验，显式空白才拒），否则既有 E2E + H5 集体变红。

## 脚本环境
- `httpx` 必须 `trust_env=False`。
- Playwright 用 `envs/default/Scripts/python.exe` + `channel="msedge"`（`versions/3.13.12` 无 playwright）。
