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
        meta: { title: '待办' }
      },
      { path: 'kb', name: 'kb', component: () => import('@/views/KbView.vue'), meta: { title: '知识库' } },
      {
        path: 'kpi',
        name: 'kpi',
        component: () => import('@/views/KpiView.vue'),
        meta: { title: '经营数据' }
      },
      {
        path: 'workers',
        name: 'workers',
        component: () => import('@/views/WorkersView.vue'),
        meta: { title: '数字员工' }
      },
      {
        path: 'biz-systems',
        name: 'biz-systems',
        component: () => import('@/views/BizSystemView.vue'),
        meta: { title: '业务系统' }
      },
      {
        path: 'quotas',
        name: 'quotas',
        component: () => import('@/views/QuotaAdminView.vue'),
        meta: { title: '配额管理' }
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { title: '操作审计' }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SystemConfigView.vue'),
        meta: { title: '系统参数' }
      },
      {
        path: 'results',
        name: 'results',
        component: () => import('@/views/ResultsView.vue'),
        meta: { title: '成果沉淀' }
      },
      { path: 'admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { title: '系统管理' } },
      { path: 'profile', name: 'profile', component: () => import('@/views/ProfileView.vue'), meta: { title: '个人信息' } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/home' }
]

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
  return true
})

export default router
