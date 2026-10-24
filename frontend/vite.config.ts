/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    // 5173 在本机落入 Windows 保留端口段(5172-5271)无法绑定，改用 5171
    // 后端默认 CORS 也按 5171 配置（backend/app/infrastructure/settings.py）
    port: 5171,
    watch: {
      // Windows 上编辑器/工具的原子写会留下 `.xxx.tmpdir` 临时目录，
      // chokidar 监视到它被删除时抛 EBUSY 会**直接崩掉 dev server**（已实测）。
      // 这些本来就是中间产物，直接忽略即可。
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/.*.swp'],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{ts,js}'],
    globals: true,
  },
})
