import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  assetsInclude: ['**/*.lottie'],
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5556,
    proxy: {
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
