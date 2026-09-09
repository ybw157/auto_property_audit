import { useState, useEffect, useCallback } from 'react'
import { getToken, setToken, clearToken } from '../services/api'
import {
  fetchUserMe,
  clearConfigCache,
  invalidateConfig,
  subscribeConfig,
  CONFIG_KEYS,
} from '../services/configCache'
import type { LoginUser } from '../types'

export function useAuth() {
  const [user, setUser] = useState<LoginUser | null>(null)
  const [loading, setLoading] = useState(true)

  const role = user?.role === true ? 'group_admin' : 'project_user'
  const projectName = user?.project_name || ''

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    // 走 sessionStorage 缓存：同一标签页内多个组件共用一份，不会每个组件都打接口
    fetchUserMe()
      .then((u) => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  // 用户信息变更时同步（同页面写入 / 其他标签页更新），保持所有 useAuth 实例一致
  useEffect(() => {
    return subscribeConfig(CONFIG_KEYS.USER_ME, () => {
      if (!getToken()) return
      fetchUserMe()
        .then((u) => setUser(u))
        .catch(() => setUser(null))
    })
  }, [])

  useEffect(() => {
    const handler = () => setUser(null)
    window.addEventListener('auth:logout', handler)
    return () => window.removeEventListener('auth:logout', handler)
  }, [])

  useEffect(() => {
    localStorage.setItem('appRole', role)
    localStorage.setItem('appProjectName', projectName)
  }, [role, projectName])

  const login = useCallback((token: string, u: LoginUser) => {
    clearConfigCache() // 换账号，清掉上个用户的缓存
    setToken(token)
    setUser(u)
    invalidateConfig(CONFIG_KEYS.USER_ME, 'session')
  }, [])

  const logout = useCallback(() => {
    clearToken()
    clearConfigCache() // 登出清空全部配置缓存，避免串号
    localStorage.removeItem('appRole')
    localStorage.removeItem('appProjectName')
    localStorage.removeItem('auditContext')
    setUser(null)
  }, [])

  return { user, role, projectName, loading, login, logout }
}
