import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../utils/request'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  // localStorage 被改脏时兼容降级，避免 JSON.parse 在 store 初始化阶段报错白屏（v4.6.1）
  const readStoredUser = () => {
    try {
      return JSON.parse(localStorage.getItem('user') || 'null')
    } catch (e) {
      localStorage.removeItem('user')
      return null
    }
  }
  const user = ref(readStoredUser())

  const login = async (username, password) => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    const res = await request.post('/api/login', { username, password })
    token.value = res.data.token
    user.value = res.data.user
    localStorage.setItem('token', res.data.token)
    localStorage.setItem('user', JSON.stringify(res.data.user))
    return res.data
  }

  const logout = async () => {
    // 先通知后端置吊销水位（v4.6.1：此前置签发的 token 全部失效），失败不阻断本地清理
    try {
      await request.post('/api/logout')
    } catch (e) { /* 忽略：本地登出不依赖后端结果 */ }
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  const register = async (username, password, email = '', role = 'student') => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    const res = await request.post('/api/register', { username, password, email, role })
    token.value = res.data.token
    user.value = res.data.user
    localStorage.setItem('token', res.data.token)
    localStorage.setItem('user', JSON.stringify(res.data.user))
    return res.data
  }

  return { token, user, login, logout, register }
})