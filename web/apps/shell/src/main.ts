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
import './styles/index.css'

const app = createApp(App)

app.use(createPinia())
// 401 由 axios 拦截器统一触发跳转登录，避免 api → router 的循环依赖
setUnauthorizedHandler(() => {
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
