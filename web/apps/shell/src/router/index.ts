import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { TOKEN_KEY } from '@/api'

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
        meta: { title: '数字员工', minTier: 'tenant'  }
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
        component: () => import('@/views/OrgStructureView.vue'),
        meta: { title: '组织与员工', minTier: 'org'  }
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
      { path: 'admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { title: '系统管理', minTier: 'platform'  } },
      { path: 'tenants', name: 'tenants', component: () => import('@/views/TenantAdminView.vue'), meta: { title: '租户管理', minTier: 'platform'  } },
      { path: 'experts', name: 'experts', component: () => import('@/views/ExpertConfigView.vue'), meta: { title: '专家配置', minTier: 'tenant' } },
      { path: 'tools', name: 'tools', component: () => import('@/views/ToolRegistryView.vue'), meta: { title: '业务工具', minTier: 'tenant' } },
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
  history: createWebHistory(),
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
  const need = to.meta.minTier as 'platform' | 'tenant' | 'org' | undefined
  if (need && tierOf(auth.roles) < TIER[need]) {
    return { path: '/home' }
  }
  return true
})

export default router
