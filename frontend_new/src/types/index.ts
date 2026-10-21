/** 全局类型定义（与后端接口契约一致） */

export interface LoginUser {
  id: number
  username: string
  display_name: string
  /** 布尔位：true=集团管理员，false=项目账号 */
  role: boolean
  project_name: string
}

export interface MenuItem {
  key: string
  label: string
  icon: any
  roles: string[]
}
