import { useEffect, useState } from 'react'
import { BarChart3, Bot, ClipboardList, Database, FileText, Home, ShieldCheck, BookOpen, Building2, CheckSquare, LogOut, Users } from 'lucide-react'
import { Dashboard } from '../pages/Dashboard'
import { AiAudit } from '../pages/AiAudit'
import { AuditResults } from '../pages/AuditResults'
import { PdfReports } from '../pages/PdfReports'
import { ContractManagement } from '../pages/ContractManagement'
import { BiSync } from '../pages/BiSync'
import { ProjectManagement } from '../pages/ProjectManagement'
import { ConfirmationPage } from '../pages/ConfirmationPage'
import { UserManagement } from '../pages/UserManagement'
import { Login } from '../pages/Login'
import { request, getToken, setToken, clearToken } from '../services/api'

const menus = [
  { key: 'dashboard', label: '首页 Dashboard', icon: Home, roles: ['集团管理员', '项目账号'] },
  { key: 'audit', label: 'AI审核', icon: Bot, roles: ['集团管理员', '项目账号'] },
  { key: 'results', label: '审核结果', icon: ClipboardList, roles: ['集团管理员', '项目账号'] },
  { key: 'confirmation', label: '异常确认', icon: CheckSquare, roles: ['集团管理员', '项目账号'] },
  { key: 'reports', label: 'PDF报告', icon: FileText, roles: ['集团管理员', '项目账号'] },
  { key: 'contracts', label: '合同管理', icon: BookOpen, roles: ['项目账号'] },
  { key: 'project-management', label: '项目管理', icon: Building2, roles: ['集团管理员'] },
  { key: 'bi-sync', label: 'BI数据同步', icon: Database, roles: ['集团管理员'] },
  { key: 'user-management', label: '用户管理', icon: Users, roles: ['集团管理员'] },
]

type LoginUser = {
  username: string
  role: string
  display_name: string
  project_name: string
  project_code: string
}

export function App() {
  const [logged, setLogged] = useState(() => !!getToken())
  const [currentUser, setCurrentUser] = useState<LoginUser | null>(null)
  const [page, setPage] = useState('dashboard')
  const [batchId, setBatchId] = useState<number | null>(() => {
    const saved = localStorage.getItem('batchId')
    return saved ? Number(saved) : null
  })

  // 角色与项目由登录用户决定，不再可随意切换
  const role = currentUser?.role || '集团管理员'
  const projectName = currentUser?.project_name || ''

  useEffect(() => {
    if (batchId) localStorage.setItem('batchId', String(batchId))
  }, [batchId])

  // 持久化角色/项目，兼容其他页面读取 localStorage 的逻辑
  useEffect(() => {
    localStorage.setItem('appRole', role)
    localStorage.setItem('appProjectName', projectName)
  }, [role, projectName])

  // 已有 token 时，启动校验并获取当前用户
  useEffect(() => {
    if (!getToken()) return
    request<LoginUser>('/api/v1/auth/me')
      .then((user) => {
        setCurrentUser(user)
        setLogged(true)
      })
      .catch(() => {
        // token 无效，api.ts 已清除并派发事件
        setLogged(false)
        setCurrentUser(null)
      })
  }, [])

  // 监听 401 失效事件，回到登录页
  useEffect(() => {
    const handler = () => {
      setLogged(false)
      setCurrentUser(null)
    }
    window.addEventListener('auth:logout', handler)
    return () => window.removeEventListener('auth:logout', handler)
  }, [])

  // 角色变化后，若当前页不可见则回到首页
  const visibleMenus = menus.filter((item) => item.roles.includes(role))
  useEffect(() => {
    if (logged && !visibleMenus.some((item) => item.key === page)) setPage('dashboard')
  }, [role, logged])

  function handleLoginSuccess(token: string, user: LoginUser) {
    setToken(token)
    setCurrentUser(user)
    setLogged(true)
    setPage('dashboard')
    // 清除上一个用户残留的 batchId，避免新用户看到无关批次数据
    localStorage.removeItem('batchId')
    setBatchId(null)
  }

  function handleLogout() {
    clearToken()
    localStorage.removeItem('batchId')
    setBatchId(null)
    setLogged(false)
    setCurrentUser(null)
  }

  // 未登录：显示登录页
  if (!logged || !currentUser) {
    return <Login onSuccess={handleLoginSuccess} />
  }

  const title = visibleMenus.find((item) => item.key === page)?.label

  return (
    <div className="flex min-h-screen">
      <aside className="w-72 border-r border-slate-200 bg-slate-950 text-white">
        <div className="flex items-center gap-3 border-b border-white/10 px-6 py-6">
          <div className="rounded-2xl bg-brand-600 p-3"><ShieldCheck size={24} /></div>
          <div>
            <div className="text-base font-semibold">智能审核平台</div>
            <div className="text-xs text-slate-400">物业集团统一审核</div>
          </div>
        </div>
        <nav className="space-y-2 p-4">
          {visibleMenus.map((item) => {
            const Icon = item.icon
            const active = item.key === page
            return (
              <button key={item.key} onClick={() => setPage(item.key)} className={`flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm transition ${active ? 'bg-brand-600 text-white' : 'text-slate-300 hover:bg-white/10'}`}>
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>
      </aside>
      <main className="flex-1">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-8 py-5">
          <div>
            <h1 className="text-xl font-semibold text-slate-950">{title}</h1>
            <p className="text-sm text-slate-500">项目上传资料，集团统一查看审核结果；以月度排班表为唯一审核依据。</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="flex items-center gap-2 rounded-2xl bg-slate-100 px-3 py-2 text-sm text-slate-600">
              <ShieldCheck size={16} />
              <span>{currentUser.display_name}</span>
              <span className="text-slate-400">·</span>
              <span>{role}</span>
              {role === '项目账号' && projectName && (
                <>
                  <span className="text-slate-400">·</span>
                  <span>{projectName}</span>
                </>
              )}
            </div>
            <div className="flex items-center gap-3 rounded-2xl bg-slate-100 px-4 py-2 text-sm text-slate-600">
              <BarChart3 size={16} />
              当前批次：{batchId ?? '未选择'}
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              <LogOut size={16} />
              退出登录
            </button>
          </div>
        </header>
        <section className="p-8" key={`${role}-${projectName}-${page}`}>
          {page === 'dashboard' && <Dashboard userRole={role} projectName={projectName} />}
          {page === 'audit' && <AiAudit onBatchChange={setBatchId} currentBatchId={batchId} userRole={role} projectName={projectName} />}
          {page === 'results' && <AuditResults batchId={batchId} />}
          {page === 'confirmation' && <ConfirmationPage batchId={batchId} />}
          {page === 'reports' && <PdfReports batchId={batchId} />}
          {page === 'contracts' && <ContractManagement userRole={role} projectName={projectName} />}
          {role === '集团管理员' && page === 'project-management' && <ProjectManagement />}
          {role === '集团管理员' && page === 'bi-sync' && <BiSync />}
          {role === '集团管理员' && page === 'user-management' && <UserManagement />}
        </section>
      </main>
    </div>
  )
}
