import { io } from 'socket.io-client'

let socket = null

/**
 * 获取全局 Socket.IO 单例（懒加载）。
 * 未连接成功时调用方应保留轮询兜底。
 */
export const getSocket = () => {
  if (!socket) {
    // 服务器 URL：显式配置则直连，否则走同源（Vite 代理会把 /socket.io 转发到后端）
    // 之前的 origin.replace(/:\d+$/, ':5000') 会在 dev 模式下绕过 Vite 代理直连后端，
    // 导致 /socket.io 路径无法被 Vite 的 ws:true 规则正确转发，现在已修正
    const serverUrl = import.meta.env.VITE_API_BASE_URL || window.location.origin
    socket = io(serverUrl, {
      // polling 优先（socket.io 官方默认顺序）：连接后自动升级 websocket。
      // 不能写成 ['websocket','polling']：engine.io-client 首连只试 transports[0]，
      // tryAllTransports 默认 false 不会降级回退——waitress 生产模式无 ws 时
      // 会重连耗尽直接放弃（v5.30 浏览器复验实测）。轮询优先在 dev（Vite ws 代理）
      // 和生产（waitress 纯轮询）两种形态下都能工作。
      transports: ['polling', 'websocket'],
      reconnectionAttempts: 5,
      timeout: 5000,
    })
  }
  return socket
}

export const closeSocket = () => {
  if (socket) {
    socket.disconnect()
    socket = null
  }
}

/** 读取本地 JWT（用于 Socket.IO 房间鉴权） */
export const authToken = () => localStorage.getItem('token') || ''

/** 加入个人房间（段位/积分/勋章实时推送）；后端会用 token 鉴权 */
export const joinUserRoom = (userId, token) => {
  if (!userId || !token) return
  getSocket().emit('join_user', { user_id: userId, token })
}

export const leaveUserRoom = (userId) => {
  if (!userId) return
  getSocket().emit('leave_user', { user_id: userId })
}
