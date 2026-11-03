import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// dev 专用:Node 默认 keepAliveTimeout=5s,而 Chrome 会复用空闲 TCP 连接最长 60s,
// 空闲 5s+ 后的首个请求(如 30s 通知轮询、路由懒加载)复用死连接被中止 →
// devtools 报 net::ERR_ABORTED(随后 Chrome 透明重试成功,功能无影响)。
// 把 keepAliveTimeout 调到 65s 超过 Chrome 复用窗口即可消除该噪声。
const keepAliveFix = {
  name: 'keep-alive-timeout-fix',
  configureServer(server) {
    server.httpServer?.once('listening', () => {
      server.httpServer.keepAliveTimeout = 65_000
      server.httpServer.headersTimeout = 66_000 // Node 要求 headersTimeout > keepAliveTimeout
    })
  }
}

export default defineConfig({
  plugins: [vue(), keepAliveFix],
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
