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
    const msg = error.response?.data?.message || '请求失败'
    
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
      window.location.href = '/home'
    }
    
    return Promise.reject(error)
  }
)

export default request