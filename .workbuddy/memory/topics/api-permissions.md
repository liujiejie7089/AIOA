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

## 兼容性纪律
- 新增请求体字段一律「**缺省兼容**」（`null` 跳过校验，显式空白才拒），否则既有 E2E + H5 集体变红。

## 脚本环境
- `httpx` 必须 `trust_env=False`。
- Playwright 用 `envs/default/Scripts/python.exe` + `channel="msedge"`（`versions/3.13.12` 无 playwright）。
