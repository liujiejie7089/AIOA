import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 强制 Vite 代理到本地后端时不走系统 HTTP_PROXY，避免本地调试被外部代理 401/404 拦截
const localHosts = ['localhost', '127.0.0.1']
process.env.NO_PROXY = [...new Set([...(process.env.NO_PROXY || '').split(',').filter(Boolean), ...localHosts])].join(',')
process.env.no_proxy = process.env.NO_PROXY

// 模块配置：web/apps/shell/.env（VITE_PORT / VITE_API_TARGET，见 .env.example），已被 gitignore
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const port = Number(env.VITE_PORT || 5173)
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8080'

  // 单端口部署（docs/33）：生产由 aioa-server 在 /aioa/web/ 下发这份产物 ⇒ 产物内资源
  // 必须是绝对前缀路径，否则挂到 /aioa/web/ 下会去请求 /assets/... 直接白屏。
  // dev 保持 '/'：本地有 10+ 个管理端 UI 套件都按 http://localhost:5173/xxx 跑，
  // 把 dev 也搬进前缀会让它们全部失效（而这不是本次要改的东西）。
  const base = command === 'build' ? '/aioa/web/' : '/'

  return {
    base,
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
      proxy: {
        // 后端 aioa-server 地址来自 .env 的 VITE_API_TARGET；仅 dev 生效
        '/api': {
          target: apiTarget,
          changeOrigin: true
        }
      }
    },
    build: {
      outDir: 'dist',
      chunkSizeWarningLimit: 1500
    }
  }
})
