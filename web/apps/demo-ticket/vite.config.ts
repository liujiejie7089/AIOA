import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 模块配置：web/apps/demo-ticket/.env（VITE_PORT，见 .env.example），已被 gitignore
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const port = Number(env.VITE_PORT || 5174)

  return {
    // 子应用以独立入口被 wujie/iframe 加载，必须用绝对 base
    base: '/',
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      port,
      host: true,
      strictPort: true,
      // wujie 通过 fetch 拉取子应用资源，必须允许跨域
      cors: true,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
        'Access-Control-Allow-Headers': '*'
      }
    }
  }
})
