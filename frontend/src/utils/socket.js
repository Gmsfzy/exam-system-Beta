import { io } from 'socket.io-client'

let socket = null

/**
 * 获取全局 Socket.IO 单例（懒加载）。
 * 未连接成功时调用方应保留轮询兜底。
 */
export const getSocket = () => {
  if (!socket) {
    socket = io(import.meta.env.VITE_API_BASE_URL || window.location.origin.replace(/:\d+$/, ':5000'), {
      transports: ['websocket', 'polling'],
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
