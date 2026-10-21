/** 认证状态（Pinia）：与 React 版 useAuth 语义一致，配置缓存走 configCache */
import { defineStore } from 'pinia'
import { getToken, setToken, clearToken } from '../api'
import {
  fetchUserMe,
  clearConfigCache,
  primeConfig,
  subscribeConfig,
  CONFIG_KEYS,
} from '../api/configCache'
import type { LoginUser } from '../types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as LoginUser | null,
    loading: true,
  }),
  getters: {
    /** 布尔位转字符串角色 */
    role: (s): 'group_admin' | 'project_user' =>
      s.user?.role === true ? 'group_admin' : 'project_user',
    projectName: (s) => s.user?.project_name || '',
  },
  actions: {
    /** 应用启动时恢复登录态（走 sessionStorage 缓存，同标签页内不重拉） */
    async restore() {
      if (!getToken()) {
        this.loading = false
        return
      }
      try {
        this.user = await fetchUserMe()
      } catch {
        this.user = null
      } finally {
        this.loading = false
      }
      // 其他标签页/写入方更新用户信息时同步
      subscribeConfig(CONFIG_KEYS.USER_ME, async () => {
        if (!getToken()) return
        try {
          this.user = await fetchUserMe()
        } catch {
          this.user = null
        }
      })
    },
    login(token: string, u: LoginUser) {
      clearConfigCache() // 换账号，清掉上个用户的缓存
      setToken(token)
      this.user = u
      localStorage.setItem('appRole', this.role)
      localStorage.setItem('appProjectName', u.project_name || '')
      // 登录接口已返回用户信息，直接落缓存，省掉其他组件挂载时那次 /user/me
      primeConfig(CONFIG_KEYS.USER_ME, u, 'session')
    },
    logout() {
      clearToken()
      clearConfigCache() // 登出清空全部配置缓存，避免串号
      localStorage.removeItem('appRole')
      localStorage.removeItem('appProjectName')
      localStorage.removeItem('auditContext')
      this.user = null
    },
  },
})
