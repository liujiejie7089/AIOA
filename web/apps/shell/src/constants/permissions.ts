/**
 * 前端角色与权限归属常量（V33）。
 *
 * <p>与后端 {@code cn.aioa.resource.support.PermissionCatalog} 一一对应。
 * 二者必须同步修改 —— 历史上正是因为前端菜单、路由层级、后端权限三处各写一套，
 * 才出现「菜单能进但接口 403」「接口放开了但菜单藏起来」两类互为镜像的缺陷。</p>
 */

export const ROLE = {
  ADMIN: 'ROLE_ADMIN',
  TENANT_ADMIN: 'ROLE_TENANT_ADMIN',
  ORG_ADMIN: 'ROLE_ORG_ADMIN',
  DEPT_LEADER: 'ROLE_DEPT_LEADER',
  MEMBER: 'ROLE_MEMBER',
  USER: 'ROLE_USER'
} as const

/** 数字员工创建/管理（= 后端 worker:create / worker:manage）。 */
export const WORKER_MANAGER_ROLES: readonly string[] = [
  ROLE.ADMIN, ROLE.TENANT_ADMIN, ROLE.ORG_ADMIN, ROLE.DEPT_LEADER
]

/** 专家创建/配置（= 后端 expert:manage）。 */
export const EXPERT_MANAGER_ROLES: readonly string[] = [
  ROLE.ADMIN, ROLE.TENANT_ADMIN, ROLE.ORG_ADMIN
]

/** 租户端（机构/配额/授权/分摊）—— 仅系统管理员与租户管理员。 */
export const TENANT_SCOPE_ROLES: readonly string[] = [ROLE.ADMIN, ROLE.TENANT_ADMIN]

/** 组织与员工可见范围。 */
export const ORG_VIEW_ROLES: readonly string[] = [
  ROLE.ADMIN, ROLE.TENANT_ADMIN, ROLE.ORG_ADMIN, ROLE.DEPT_LEADER, ROLE.MEMBER
]

/** 平台级专属（V34 内容审核台）：只有系统管理员，租户管理员是被审对象。 */
export const PLATFORM_ONLY_ROLES: readonly string[] = [ROLE.ADMIN]

export function hasAnyRole(roles: string[] | undefined | null, allowed: readonly string[]): boolean {
  return !!roles && roles.some((r) => allowed.includes(r))
}
