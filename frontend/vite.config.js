import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // HTTP API
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      },
      // Socket.IO 实时推送（ws: true 开启 WebSocket 升级；
      // 未升级时自动回退长轮询，两者 Vite 都能代理）
      '/socket.io': {
        target: 'http://127.0.0.1:5000',
        ws: true,
        changeOrigin: true
      },
      // 用户上传的附件（图片/视频）
      '/uploads': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      }
    }
  }
})
