import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { TOKEN_KEY } from '@/api'
import { EXPERT_MANAGER_ROLES, GITEE_VIEW_ROLES, ORG_VIEW_ROLES, PERSONNEL_VIEW_ROLES, PLATFORM_ONLY_ROLES, REVIEW_RECORD_ROLES, TENANT_SCOPE_ROLES, WORKER_MANAGER_ROLES, hasAnyRole } from '@/constants/permissions'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/home',
    children: [
      { path: 'home', name: 'home', component: () => import('@/views/HomeView.vue'), meta: { title: '首页' } },
      { path: 'app/:appCode', name: 'app', component: () => import('@/views/AppHost.vue'), meta: { title: '子应用' } },
      {
        path: 'approvals',
        name: 'approvals',
        component: () => import('@/views/ApprovalsView.vue'),
        meta: { title: '审批中心' }
      },
      {
        // 三期 C-02/A3-9：租户端审批流配置（可视化配「知会对象」）
        path: 'approval-flows',
        name: 'approval-flows',
        component: () => import('@/views/ApprovalFlowConfigView.vue'),
        meta: { title: '审批流配置', allowRoles: TENANT_SCOPE_ROLES }
      },
      { path: 'kb', name: 'kb', component: () => import('@/views/KbView.vue'), meta: { title: '知识库' } },
      {
        path: 'kpi',
        name: 'kpi',
        component: () => import('@/views/KpiView.vue'),
        meta: { title: '经营数据', minTier: 'tenant'  }
      },
      {
        path: 'workers',
        name: 'workers',
        component: () => import('@/views/WorkersView.vue'),
        // 创建/管理归属：系统管理员 / 租户管理员 / 企业管理员 / 部门负责人
        meta: { title: '数字员工', allowRoles: WORKER_MANAGER_ROLES }
      },
      {
        path: 'biz-systems',
        name: 'biz-systems',
        component: () => import('@/views/BizSystemView.vue'),
        meta: { title: '业务系统', minTier: 'tenant'  }
      },
      {
        path: 'quotas',
        name: 'quotas',
        component: () => import('@/views/QuotaAdminView.vue'),
        meta: { title: '配额管理', minTier: 'tenant'  }
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { title: '操作审计', minTier: 'tenant'  }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SystemConfigView.vue'),
        meta: { title: '系统参数', minTier: 'tenant'  }
      },
      {
        path: 'results',
        name: 'results',
        component: () => import('@/views/ResultsView.vue'),
        meta: { title: '成果沉淀', minTier: 'tenant'  }
      },
      {
        path: 'institutions',
        name: 'institutions',
        component: () => import('@/views/InstitutionView.vue'),
        meta: { title: '机构管理', minTier: 'tenant'  }
      },
      {
        path: 'onboarding',
        name: 'onboarding',
        component: () => import('@/views/OnboardingView.vue'),
        meta: { title: '入驻进度', minTier: 'tenant'  }
      },
      {
        path: 'org-structure',
        name: 'org-structure',
        component: () => import('@/views/OrgAdminView.vue'),
        // 「组织与部门」：部门树 / 员工名册对机构成员开放（ORG_VIEW_ROLES）。
        // 与 /admin 指向同一组件（OrgAdminView 双页签容器），由入口路由决定默认落在哪个页签；
        // 页签本身仍按 PERSONNEL_VIEW_ROLES 收起，深链进来也不会越过权限边界。
        meta: { title: '组织与员工', allowRoles: ORG_VIEW_ROLES }
      },
      {
        // 「人员管理」从 /org-structure 的页签提升为独立菜单项（组织与员工 → 人员管理）。
        // 保留为**独立路由**而不是 alias：
        // alias 会继承 /org-structure 的 allowRoles（含 ROLE_MEMBER），普通成员深链 /admin
        // 就不再被拦截，等于顺手放宽了人员管理的边界。这里沿用原口径 PERSONNEL_VIEW_ROLES，
        // 使「菜单怎么摆」与「谁能进人员管理」两件事互不牵连。
        path: 'admin',
        name: 'admin',
        component: () => import('@/views/OrgAdminView.vue'),
        meta: { title: '人员管理', allowRoles: PERSONNEL_VIEW_ROLES }
      },
      /*
        平台级基线配置：原「人员管理」页内的卡片，管的是平台级基线数据与系统配置，
        与「员工 / 账号」没有从属关系，故从人员页拆出。按功能域分两处落菜单：
          · /sys-roles（角色）、/sys-permissions（权限点） → 「权限与安全」
          · /sys-apps（功能管理）、/sys-models（模型管理） → 「系统配置」
        四条路由共用 PlatformConfigView，靠 meta.section 决定渲染哪一块；
        path 与菜单 index 一一对应，可见范围沿用后端 requireAdmin() = PLATFORM_ONLY_ROLES。
      */
      {
        path: 'sys-roles',
        name: 'sys-roles',
        component: () => import('@/views/PlatformConfigView.vue'),
        meta: { title: '角色', section: 'roles', allowRoles: PLATFORM_ONLY_ROLES }
      },
      {
        path: 'sys-apps',
        name: 'sys-apps',
        component: () => import('@/views/PlatformConfigView.vue'),
        meta: { title: '功能管理', section: 'apps', allowRoles: PLATFORM_ONLY_ROLES }
      },
      {
        path: 'sys-models',
        name: 'sys-models',
        component: () => import('@/views/PlatformConfigView.vue'),
        meta: { title: '模型管理', section: 'models', allowRoles: PLATFORM_ONLY_ROLES }
      },
      {
        path: 'sys-permissions',
        name: 'sys-permissions',
        component: () => import('@/views/PlatformConfigView.vue'),
        meta: { title: '权限点', section: 'permissions', allowRoles: PLATFORM_ONLY_ROLES }
      },
      {
        path: 'resource-grants',
        name: 'resource-grants',
        component: () => import('@/views/ResourceGrantView.vue'),
        meta: { title: '资源授权', minTier: 'tenant'  }
      },
      {
        path: 'cost-alloc',
        name: 'cost-alloc',
        component: () => import('@/views/CostAllocView.vue'),
        meta: { title: '费用分摊', minTier: 'tenant'  }
      },
      {
        path: 'tenants', name: 'tenants', component: () => import('@/views/TenantAdminView.vue'), meta: { title: '租户管理', minTier: 'platform'  }
      },
      { path: 'experts', name: 'experts', component: () => import('@/views/ExpertConfigView.vue'), meta: { title: '专家配置', allowRoles: EXPERT_MANAGER_ROLES } },
      { path: 'tools', name: 'tools', component: () => import('@/views/ToolRegistryView.vue'), meta: { title: '业务工具', minTier: 'tenant' } },
      // V34：租户管理员创建的数字员工/专家需平台管理员审核后生效
      { path: 'content-reviews', name: 'content-reviews', component: () => import('@/views/ContentReviewView.vue'), meta: { title: '内容审核', allowRoles: PLATFORM_ONLY_ROLES } },
      // V36 需求④：审核记录中心（平台管理员全量 / 租户管理员本租户）
      { path: 'review-records', name: 'review-records', component: () => import('@/views/ReviewRecordsView.vue'), meta: { title: '审核记录', allowRoles: REVIEW_RECORD_ROLES } },
      { path: 'gitee/projects', name: 'gitee-projects', component: () => import('@/views/GiteeProjectsView.vue'), meta: { title: '项目与仓库', allowRoles: GITEE_VIEW_ROLES } },
      { path: 'gitee/projects/:id', name: 'gitee-project-detail', component: () => import('@/views/GiteeProjectDetailView.vue'), meta: { title: '项目详情', allowRoles: GITEE_VIEW_ROLES } },
      // V5x 消息中心：对所有已登录角色可见（人人都要看自己的通知）。
      // 通道配置 / 投递记录两个页签在页内按 isTenantAdmin 收起，非管理员不发起其接口请求（否则 403）。
      // 不加 allowRoles / minTier —— 三层同源：菜单(MainLayout) → 路由 meta → 后端都已对齐「全员可见」。
      { path: 'notifications', name: 'notifications', component: () => import('@/views/NotificationCenterView.vue'), meta: { title: '消息中心' } },
      { path: 'profile', name: 'profile', component: () => import('@/views/ProfileView.vue'), meta: { title: '个人信息' } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/home' }
]

// 权限层级：platform(平台管理员) > tenant(租户管理员) > org(机构/部门/成员)
const TIER: Record<string, number> = { org: 0, tenant: 1, platform: 2 }

function tierOf(roles: string[]): number {
  if (!roles || !roles.length) return 0
  if (roles.includes('ROLE_ADMIN')) return 2
  if (roles.includes('ROLE_TENANT_ADMIN')) return 1
  return 0
}

const router = createRouter({
  // 基址跟随构建基址：生产是 /aioa/web/（由 aioa-server 单端口下发，见 docs/33），
  // dev 是 /。写死 '/' 会让生产环境把 /aioa/web/org-structure 当成路由 /aioa/web/org-structure。
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  // 以 localStorage 中的 token 为最终登录态来源，避免 Pinia 初始化/响应式延迟导致误判
  const hasToken = !!(auth.token || localStorage.getItem(TOKEN_KEY))
  if (to.meta.public) {
    // 已登录访问 /login 直接回首页
    return hasToken ? { path: '/home' } : true
  }
  if (!hasToken) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  // 越权访问直接回首页：菜单隐藏只是 UI 层，路由层必须再兜一道
  // 优先用精确角色集合（如数字员工/专家配置这类「跨层级」能力），
  // 没有 allowRoles 时才回落到粗粒度层级判定。
  const allow = to.meta.allowRoles as readonly string[] | undefined
  if (allow && allow.length && !hasAnyRole(auth.roles, allow)) {
    return { path: '/home' }
  }
  const need = to.meta.minTier as 'platform' | 'tenant' | 'org' | undefined
  if (need && tierOf(auth.roles) < TIER[need]) {
    return { path: '/home' }
  }
  return true
})

export default router
