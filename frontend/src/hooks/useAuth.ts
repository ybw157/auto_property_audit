import { useState, useEffect, useCallback } from 'react'
import { request, getToken, setToken, clearToken } from '../services/api'
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
    request<LoginUser>('/api/v2/user/me')
      .then((u) => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
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
    setToken(token)
    setUser(u)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    localStorage.removeItem('appRole')
    localStorage.removeItem('appProjectName')
    localStorage.removeItem('auditContext')
    setUser(null)
  }, [])

  return { user, role, projectName, loading, login, logout }
}
