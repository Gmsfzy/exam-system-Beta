import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
  withCredentials: true
})

let csrfToken = ''

const fetchCsrfToken = async () => {
  try {
    const response = await axios.get('/api/csrf-token', {
      baseURL: import.meta.env.VITE_API_BASE_URL || '',
      withCredentials: true
    })
    csrfToken = response.data.csrf_token
  } catch (error) {
    csrfToken = ''
  }
}

fetchCsrfToken()

request.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (csrfToken) {
    config.headers['X-CSRF-TOKEN'] = csrfToken
  }
  return config
})

request.interceptors.response.use(
  response => response,
  error => {
    const status = error.response?.status
    // 浏览器侧超时（无 response）单独说：这类只会落到「请求失败」，用户不知道该稍后重试还是找运维。
    // 长耗时接口（如 AI 出题）应在调用处按后端超时传更大的 per-request timeout，不依这里兼顾。
    const timeoutLike = !error.response &&
      (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT' || /timeout/i.test(error.message || ''))
    const msg = error.response?.data?.message || (timeoutLike ? '请求超时，服务处理较慢，请稍后重试' : '请求失败')
    
    if (status === 429) {
      ElMessage.error('请求过于频繁，请稍后重试')
    } else if (status === 403) {
      ElMessage.error(msg || '访问被拒绝')
      fetchCsrfToken()
    } else {
      ElMessage.error(msg)
    }
    
    if (status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      // 带 redirect 参数保留原路径，登录后可跳回（防止用户在编辑页 token 过期丢失草稿位置）
      const redirect = window.location.pathname + window.location.search
      window.location.href = `/home?redirect=${encodeURIComponent(redirect)}`
    }
    
    return Promise.reject(error)
  }
)

export default request