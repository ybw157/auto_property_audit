import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuth } from '../hooks/useAuth'
import { Layout } from '../components/Layout'
import { ErrorBoundary } from '../components/ErrorBoundary'
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

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && !user) {
      navigate('/login', { replace: true })
    }
  }, [user, loading, navigate])

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

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter basename="/audit">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={
            <AuthGuard>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/audit" element={<AiAudit />} />
                <Route path="/results" element={<AuditResults />} />
                <Route path="/confirmation" element={<ConfirmationPage />} />
                <Route path="/reports" element={<PdfReports />} />
                <Route path="/contracts" element={<ContractManagement />} />
                <Route path="/project-management" element={<ProjectManagement />} />
                <Route path="/bi-upload" element={<BiUpload />} />
                <Route path="/bi-sync" element={<BiSync />} />
                <Route path="/user-management" element={<UserManagement />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AuthGuard>
          } />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
