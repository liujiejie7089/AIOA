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

/**
 * 人员管理可见范围（系统管理 → 人员管理）。
 *
 * <p>与后端 {@code AdminController#personnel} 共用同一口径：四级管理者可读，
 * 数据范围由后端按调用者档位收窄（平台=全平台 / 租户=本租户 / 机构=本机构 / 部门=本部门）。
 * 普通成员不在其中 —— 最小可见边界是部门，成员没有「管人」的职责。</p>
 *
 * <p>此前「系统管理」整块绑死 {@code PLATFORM_ONLY_ROLES}：菜单不显示、路由
 * {@code minTier:'platform'} 又把人重定向回首页，机构管理员因此看到「人员管理全空」。
 * 现在菜单 / 路由 / 接口三层都改用本常量，避免再次出现三层口径打架。</p>
 */
export const PERSONNEL_VIEW_ROLES: readonly string[] = [
  ROLE.ADMIN, ROLE.TENANT_ADMIN, ROLE.ORG_ADMIN, ROLE.DEPT_LEADER
]

/**
 * 审核记录可见范围（V36 需求④）。
 *
 * <p>平台管理员看全量（跨租户），租户管理员看本租户 —— 与后端
 * {@code ContentReviewController.requireReviewRecordReader()} 的口径一致。
 * 注意这里<b>不</b>包含企业管理员：机构级审核记录无独立数据源，
 * 放进来只会得到一个恒为空的页面。</p>
 */
export const REVIEW_RECORD_ROLES: readonly string[] = [ROLE.ADMIN, ROLE.TENANT_ADMIN]

export function hasAnyRole(roles: string[] | undefined | null, allowed: readonly string[]): boolean {
  return !!roles && roles.some((r) => allowed.includes(r))
}

/**
 * 审批流「知会对象」可选项（三期 C-02）。
 *
 * <p>与后端 {@code ApprovalFlowService.expandCcNodes} 支持的 {@code cc} 类型严格一致：
 * 引擎对未知类型 {@code default -> null} 跳过（不报错），故管理端必须在此约束内选择，
 * 非法类型由前端提示（不静默丢弃）。{@code SPECIFIC}（指定人）属 P1，本期不开放入口。</p>
 */
export const CC_TARGET_TYPES = [
  { value: 'ORG_ADMIN', label: '企业管理员' },
  { value: 'DEPT_LEADER', label: '部门负责人' },
  { value: 'TENANT_ADMIN', label: '租户管理员' },
  { value: 'PLATFORM_ADMIN', label: '平台管理员' }
] as const

/** 合法的知会对象类型码集合（用于保存前的非法值校验）。 */
export const CC_TARGET_VALUES: readonly string[] = CC_TARGET_TYPES.map((t) => t.value)
