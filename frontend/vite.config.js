import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  assetsInclude: ['**/*.lottie'],
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5556,
    // host=true 等价于 0.0.0.0：让 dev server 同时绑所有网卡，允许局域网其他机器
    // 通过 http://<本机IP>:5556 访问。本机仍然走 localhost。
    host: true,
    // HMR 显式锁死 host=localhost + protocol=ws，避免 Clash / Verge 等系统级代理
    // 拦截 WebSocket Upgrade 握手导致 ws://localhost:5556/?token=xxx failed。
    // 这只是开发态热更新，断了也不影响应用功能。
    // 注意：从其他机子访问时，浏览器会尝试连 ws://localhost:5556 失败，HMR 不可用，
    // 但页面功能正常；本机访问 HMR 仍然有效。
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
      // 跨库搜索流：NDJSON 渐进推送，确保不被任何中间层缓冲
      '/api/library/index/global-search/stream': {
        target: 'http://localhost:5555',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers['cache-control'] = 'no-cache, no-store, must-revalidate'
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
