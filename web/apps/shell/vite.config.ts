import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 强制 Vite 代理到本地后端时不走系统 HTTP_PROXY，避免本地调试被外部代理 401/404 拦截
const localHosts = ['localhost', '127.0.0.1']
process.env.NO_PROXY = [...new Set([...(process.env.NO_PROXY || '').split(',').filter(Boolean), ...localHosts])].join(',')
process.env.no_proxy = process.env.NO_PROXY

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: true,
    strictPort: true,
    proxy: {
      // 后端 aioa-server 默认 8080；仅 dev 生效
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500
  }
})
