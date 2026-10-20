import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { preloadConfigs } from '../services/configCache'
import { Layout } from '../layouts/Layout'
import { Login } from '../pages/Login'
import { Dashboard } from '../pages/Dashboard'
import { AiAudit } from '../pages/AiAudit'
import { AuditResults } from '../pages/AuditResults'
import { ConfirmationPage } from '../pages/ConfirmationPage'
import { PdfReports } from '../pages/PdfReports'
import { ContractManagement } from '../pages/ContractManagement'
import { BiSync } from '../pages/BiSync'
import { BiUpload } from '../pages/BiUpload'
import { ProjectManagement } from '../pages/ProjectManagement'
import { UserManagement } from '../pages/UserManagement'

/** 登录守卫：未登录跳 /login；登录态就绪后预拉取一次全局配置（整个会话一次）。 */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && !user) {
      navigate('/login', { replace: true })
    }
  }, [user, loading, navigate])

  // AuthGuard 不随路由切换卸载，因此整个会话只执行一次
  useEffect(() => {
    if (user) preloadConfigs()
  }, [user])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">加载中...</div>
      </div>
    )
  }

  if (!user) {
    return null
  }

  return <Layout>{children}</Layout>
}

/** 受保护区域的路由表：path → 页面组件（菜单显隐由 Layout 的 roles 控制） */
const protectedRoutes: Array<{ path: string; element: React.ReactNode }> = [
  { path: '/dashboard', element: <Dashboard /> },
  { path: '/audit', element: <AiAudit /> },
  { path: '/results', element: <AuditResults /> },
  { path: '/confirmation', element: <ConfirmationPage /> },
  { path: '/reports', element: <PdfReports /> },
  { path: '/contracts', element: <ContractManagement /> },
  { path: '/project-management', element: <ProjectManagement /> },
  { path: '/bi-upload', element: <BiUpload /> },
  { path: '/bi-sync', element: <BiSync /> },
  { path: '/user-management', element: <UserManagement /> },
]

/** 按角色决定落地页：集团管理员进驾驶舱，项目账号进 AI 审核页 */
function RoleHomeRedirect() {
  const { role } = useAuth()  // useAuth 已把布尔位转为 'group_admin' / 'project_user'
  return <Navigate to={role === 'group_admin' ? '/dashboard' : '/audit'} replace />
}

export function AppRouter() {
  return (
    <BrowserRouter basename="/audit">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={
          <AuthGuard>
            <Routes>
              {protectedRoutes.map((r) => (
                <Route key={r.path} path={r.path} element={r.element} />
              ))}
              {/* 根路径与未知路径都按角色落到各自首页 */}
              <Route path="/" element={<RoleHomeRedirect />} />
              <Route path="*" element={<RoleHomeRedirect />} />
            </Routes>
          </AuthGuard>
        } />
      </Routes>
    </BrowserRouter>
  )
}
