export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

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

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response
  try {
    const headers = new Headers(options?.headers)
    // 携带登录 token
    const token = getToken()
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    // 兼容旧逻辑：仍发送角色/项目头，供未改造的路由使用
    const role = localStorage.getItem('appRole') || '集团管理员'
    const projectName = localStorage.getItem('appProjectName') || ''
    if (!headers.has('X-User-Role')) headers.set('X-User-Role', role === '项目账号' ? 'project_user' : 'group_admin')
    if (projectName && !headers.has('X-Project-Name')) headers.set('X-Project-Name', encodeURIComponent(projectName))
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  } catch (error) {
    throw new Error(`后端服务未启动或已断开，请确认 ${API_BASE_URL} 正在运行`)
  }
  // 401：token 失效，清除并跳登录页
  if (res.status === 401) {
    clearToken()
    // 触发全局登录失效事件，由 App 监听后回到登录页
    window.dispatchEvent(new CustomEvent('auth:logout'))
    const error = await res.json().catch(() => ({ detail: '登录已过期，请重新登录' }))
    throw new Error(error.detail || '登录已过期，请重新登录')
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(error.detail || '请求失败')
  }
  return res.json()
}
