import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

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
      { path: 'admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { title: '系统管理' } }
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
  if (to.meta.public) {
    // 已登录访问 /login 直接回首页
    return auth.isLogin ? { path: '/home' } : true
  }
  if (!auth.isLogin) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  return true
})

export default router
