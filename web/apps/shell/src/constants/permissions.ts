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
 * 审批流「知会对象」可选项（三期 C-02 + C-11）。
 *
 * <p>与后端 {@code ApprovalFlowService.expandCcNodes} 支持的 {@code cc} 类型严格一致：
 * 引擎对未知类型 {@code default -> null} 跳过（不报错），故管理端必须在此约束内选择，
 * 非法类型由前端提示（不静默丢弃）。</p>
 *
 * <p>{@code SPECIFIC}（指定具体人，C-11）没有固定 value —— 它是
 * {@code {"type":"SPECIFIC","user_id":N}} 形态，人由 <b>user_id</b> 决定，
 * 因此不放在本下拉里，而由管理端的「指定知会人」选择器单独写入。</p>
 */
export const CC_TARGET_TYPES = [
  { value: 'ORG_ADMIN', label: '企业管理员' },
  { value: 'DEPT_LEADER', label: '部门负责人' },
  { value: 'TENANT_ADMIN', label: '租户管理员' },
  { value: 'PLATFORM_ADMIN', label: '平台管理员' }
] as const

/** 合法的知会对象类型码集合（用于保存前的非法值校验）。 */
export const CC_TARGET_VALUES: readonly string[] = CC_TARGET_TYPES.map((t) => t.value)

// ================================================================== 四期 / 五期：节点配置
//
// 以下四组常量是「管理端能配出引擎真正支持的流程」的前提：引擎（V45）支持
// 职务型审批人、单人/会签/抢占三种处理模式、when 条件路由、指定知会人，
// 但管理端此前只能配 approver_type + levels + threshold_days + cc(角色)，
// 于是这些能力只能靠直接打接口使用 —— 配置入口缺失 = 能力事实上不可用。
// 新增口径时**必须同步改这里**（前端唯一入口，勿在视图里另起一份字面量）。

/** 审批人类型（与后端 {@code ApprovalTask.TYPE_*} 同源）。 */
export const APPROVER_TYPES = [
  { value: 'APPLICANT_SUPERIOR', label: '申请人的上级' },
  { value: 'DEPT_LEADER', label: '部门负责人' },
  { value: 'DEPT_DUTY', label: '部门职务（按职务动态取人）' },
  { value: 'UNIT_DUTY', label: '机构职务（按职务动态取人）' },
  { value: 'ORG_ADMIN', label: '企业管理员' },
  { value: 'TENANT_ADMIN', label: '租户管理员' },
  { value: 'PLATFORM_ADMIN', label: '平台管理员' },
  { value: 'SPECIFIC', label: '指定审批人' }
] as const

/** 审批人类型 → 中文名（流转路径 / 列表回显用；未收录时原样显示类型码）。 */
export const APPROVER_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  APPROVER_TYPES.map((t) => [t.value, t.label])
) as Record<string, string>

/** 职务字典（与后端 {@code OrgDuty.*} 同源），scope 决定它能配在哪种节点上。 */
export const DUTY_TYPES = [
  { value: 'DEPT_PRINCIPAL', label: '部门正职', scope: 'DEPT' },
  { value: 'DEPT_DEPUTY', label: '部门副职', scope: 'DEPT' },
  { value: 'ORG_LEADER', label: '机构负责人', scope: 'ORG' }
] as const

/** 按审批人类型给出可选职务：DEPT_DUTY 只列部门域职务，UNIT_DUTY 只列机构域职务。 */
export function dutiesForApproverType(type: string): readonly { value: string; label: string }[] {
  if (type === 'DEPT_DUTY') return DUTY_TYPES.filter((d) => d.scope === 'DEPT')
  if (type === 'UNIT_DUTY') return DUTY_TYPES.filter((d) => d.scope === 'ORG')
  return []
}

/** 节点处理模式（与后端 {@code ApprovalTask.MODE_*} 同源）。 */
export const NODE_MODES = [
  { value: 'single', label: '单人（取首个候选）' },
  { value: 'parallel', label: '会签（全部通过才推进）' },
  { value: 'grab', label: '抢占（任一人处理即完成）' }
] as const

/** 条件路由的取值字段（与后端 {@code fieldValue()} 同源）。 */
export const CONDITION_FIELDS = [
  { value: 'days', label: '申请天数' },
  { value: 'bizType', label: '业务类型' },
  { value: 'departmentId', label: '部门 ID' },
  { value: 'institutionId', label: '机构 ID' },
  { value: 'applicantType', label: '申请主体（USER / DEPARTMENT）' },
  { value: 'tokens', label: '额度（额度扩容表单：tokens）' }
] as const

/** 条件运算符（与后端 {@code compare()} 同源）。 */
export const CONDITION_OPS = [
  { value: '<=', label: '≤' },
  { value: '<', label: '<' },
  { value: '>=', label: '≥' },
  { value: '>', label: '>' },
  { value: '==', label: '=' },
  { value: '!=', label: '≠' }
] as const
