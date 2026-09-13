import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as ElementPlusIcons from '@element-plus/icons-vue'
import WujieVue from 'wujie-vue3'
import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler } from './api'
import { useAuthStore } from './stores/auth'
import './styles/index.css'

const app = createApp(App)

app.use(createPinia())
// 401 由 axios 拦截器统一触发跳转登录，避免 api → router 的循环依赖
setUnauthorizedHandler(() => {
  // 拦截器只清了 localStorage，Pinia 里的登录态还在 —— 不同步清掉的话，
  // MainLayout 会继续把当前页面当作「已登录」渲染，页面在无令牌下继续发请求。
  try {
    useAuthStore().clearSession()
  } catch {
    // Pinia 尚未就绪（极端时序）时忽略：localStorage 已清，下次导航仍是未登录态
  }
  if (router.currentRoute.value.path !== '/login') {
    void router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.use(WujieVue)

for (const [name, component] of Object.entries(ElementPlusIcons)) {
  app.component(name, component)
}

app.mount('#app')
