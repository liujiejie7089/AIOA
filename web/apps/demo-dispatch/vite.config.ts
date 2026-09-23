import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 模块配置：web/apps/demo-dispatch/.env（VITE_PORT，见 .env.example），已被 gitignore
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const port = Number(env.VITE_PORT || 5175)

  return {
    // 生产（docs/33 单端口）由 aioa-server 从 /aioa/web/ 下发，本子应用产物落在其下
    // subapps/demo-dispatch/；dev 仍在自己的端口根路径（:5175）。
    base: command === 'build' ? '/aioa/web/subapps/demo-dispatch/' : '/',
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
      cors: true,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
        'Access-Control-Allow-Headers': '*'
      }
    }
  }
})
