export type AuditContext = {
  project_name: string
  audit_month: string
  business_type: string
}

export type LoginUser = {
  username: string
  role: boolean
  display_name: string
  project_name: string
  project_code: string
}

export type MenuItem = {
  key: string
  label: string
  icon: React.ComponentType<{ size?: number }>
  roles: string[]
}