import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/list' },
  { path: '/list', name: 'list', component: () => import('@/views/TicketList.vue') },
  { path: '/detail/:id', name: 'detail', component: () => import('@/views/TicketDetail.vue') }
]

// 子应用用 hash 路由：wujie/iframe 下不依赖主应用 history 同步
export default createRouter({
  history: createWebHashHistory(),
  routes
})
