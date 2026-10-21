/** API 请求封装：axios 版。行为与 React 版 fetch 封装一致：
 * - 请求拦截器：自动携带 token + 角色/项目头（兼容旧逻辑）
 * - 响应拦截器：统一解包 Result（code=0 成功）、401 广播登出、错误统一抛中文 message
 */
import axios, { AxiosError, AxiosRequestConfig } from 'axios'

const TOKEN_KEY = 'appToken'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const service = axios.create({ timeout: 30000 })

// 请求拦截器：注入 token 与角色/项目头
service.interceptors.request.use((config) => {
  const token = getToken()
  if (token && !config.headers.has('Authorization')) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  const role = localStorage.getItem('appRole') || 'group_admin'
  const projectName = localStorage.getItem('appProjectName') || ''
  if (!config.headers.has('X-User-Role')) {
    config.headers.set('X-User-Role', role === 'project_user' ? 'project_user' : 'group_admin')
  }
  if (projectName && !config.headers.has('X-Project-Name')) {
    config.headers.set('X-Project-Name', encodeURIComponent(projectName))
  }
  return config
})

// 响应拦截器：统一解包 + 错误处理
service.interceptors.response.use(
  (response) => {
    const json: any = response.data
    // 后端统一响应壳 { code, message, data }
    if (json && typeof json === 'object' && 'code' in json && 'data' in json) {
      if (json.code !== 0) {
        return Promise.reject(new Error(json.message || '请求失败'))
      }
      return json.data
    }
    return json
  },
  (error: AxiosError<any>) => {
    if (error.response?.status === 401) {
      clearToken()
      window.dispatchEvent(new CustomEvent('auth:logout'))
      const detail = error.response?.data?.detail
      return Promise.reject(new Error(detail || '登录已过期，请重新登录'))
    }
    if (error.response) {
      const detail = error.response.data?.detail || error.response.data?.message
      return Promise.reject(new Error(detail || '请求失败'))
    }
    // 网络层失败（后端未启动/断连）
    return Promise.reject(new Error('服务未启动或已断开，请确认后端正在运行'))
  },
)

export async function request<T>(path: string, options?: AxiosRequestConfig): Promise<T> {
  return service.request({ url: path, ...options }) as Promise<T>
}
