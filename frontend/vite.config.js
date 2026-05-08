import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  assetsInclude: ['**/*.lottie'],
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5556,
    // HMR 显式锁死 host=localhost + protocol=ws，避免 Clash / Verge 等系统级代理
    // 拦截 WebSocket Upgrade 握手导致 ws://localhost:5556/?token=xxx failed。
    // 这只是开发态热更新，断了也不影响应用功能。
    hmr: {
      host: 'localhost',
      protocol: 'ws',
      clientPort: 5556,
    },
    proxy: {
      '/api/notifications/stream': {
        target: 'http://localhost:5555',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['x-accel-buffering'] = 'no'
          })
        }
      },
      '/api': {
        target: 'http://localhost:5555',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
