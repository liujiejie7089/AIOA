import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import { createAioaBridge } from '@aioa/sdk'
import App from './App.vue'
import router from './router'
import './styles.css'

// 入口最早期创建桥接：appCode 与工作台应用注册表中的 ticket 保持一致
const aioa = createAioaBridge({ appCode: 'ticket' })

if (aioa.inWorkbench) {
  console.log('[ticket] 运行在 AIOA 工作台内，桥接已启用')
} else {
  console.log('[ticket] 独立运行，@aioa/sdk 全部 API 降级为 no-op')
}

// 仅 DEV：把桥接实例挂到 window，供调试与端到端自动化（getToken / origin 白名单）使用。
// 生产构建会被摇掉（import.meta.env.DEV 为常量 false）。
if (import.meta.env.DEV) {
  ;(window as unknown as Record<string, unknown>).__aioa = aioa
}

const app = createApp(App)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
