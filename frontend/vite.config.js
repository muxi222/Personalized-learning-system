import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 8000,
    // Proxy 配置：将所有 API 请求从 8000 端口转发到对应的后端模块端口
    // 前端使用相对路径 /api/{module}/v1/...，通过 proxy 转发到 http://localhost:{port}/api/v1/...
    proxy: {
      // RPJ 模块 (6001): 语文、英语、政治
      '/api/rpj': {
        target: 'http://localhost:6001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/rpj/, '/api'),
      },
      // XMX 模块 (6002): 经济学
      '/api/xmx': {
        target: 'http://localhost:6002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/xmx/, '/api'),
      },
      // WZY 模块 (6003): 数学、物理
      '/api/wzy': {
        target: 'http://localhost:6003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/wzy/, '/api'),
      },
      // WZM 模块 (6004): 化学
      '/api/wzm': {
        target: 'http://localhost:6004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/wzm/, '/api'),
      },
      // TONY 模块 (6005): 历史、地理、其他
      '/api/tony': {
        target: 'http://localhost:6005',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/tony/, '/api'),
      },
      // Default 模块 (6100): 跨学科查询
      '/api/default': {
        target: 'http://localhost:6100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/default/, '/api'),
      },
      // Health check endpoints for each module
      '/health/rpj': {
        target: 'http://localhost:6001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/rpj/, '/health'),
      },
      '/health/xmx': {
        target: 'http://localhost:6002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/xmx/, '/health'),
      },
      '/health/wzy': {
        target: 'http://localhost:6003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/wzy/, '/health'),
      },
      '/health/wzm': {
        target: 'http://localhost:6004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/wzm/, '/health'),
      },
      '/health/tony': {
        target: 'http://localhost:6005',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/tony/, '/health'),
      },
      '/health/default': {
        target: 'http://localhost:6100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/health\/default/, '/health'),
      },
    },
  },
})
