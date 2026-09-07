import { defineConfig } from 'vite'

// 库构建：ESM + CJS，类型声明由 tsc 先行产出到 dist，故 emptyOutDir=false 避免被清掉
export default defineConfig({
  build: {
    emptyOutDir: false,
    sourcemap: true,
    lib: {
      entry: 'src/index.ts',
      name: 'AioaSdk',
      formats: ['es', 'cjs'],
      fileName: (format) => (format === 'cjs' ? 'aioa-sdk.cjs' : 'aioa-sdk.js')
    }
  }
})
