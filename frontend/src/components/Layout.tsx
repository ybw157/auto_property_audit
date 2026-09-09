import { useNavigate, useLocation } from 'react-router-dom'
import { Bot, ClipboardList, FileText, Home, ShieldCheck, BookOpen, Building2, CheckSquare, LogOut, Users, Upload } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import type { MenuItem } from '../types'

const menus: MenuItem[] = [
  { key: '/', label: '首页', icon: Home, roles: ['group_admin'] },
  { key: '/audit', label: 'AI审核', icon: Bot, roles: ['group_admin', 'project_user'] },
  { key: '/results', label: '审核结果', icon: ClipboardList, roles: ['group_admin', 'project_user'] },
  { key: '/confirmation', label: '异常确认', icon: CheckSquare, roles: ['group_admin', 'project_user'] },
  { key: '/reports', label: 'PDF报告', icon: FileText, roles: ['group_admin', 'project_user'] },
  { key: '/contracts', label: '合同管理', icon: BookOpen, roles: ['group_admin', 'project_user'] },
  { key: '/project-management', label: '项目管理', icon: Building2, roles: ['group_admin'] },
  { key: '/bi-upload', label: 'BI考勤', icon: Upload, roles: ['group_admin'] },
  { key: '/user-management', label: '用户管理', icon: Users, roles: ['group_admin'] },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, role, projectName, logout } = useAuth()

  const roleLabelMap: Record<string, string> = { group_admin: '集团管理员', project_user: '项目账号' }
  const roleLabel = roleLabelMap[role] || role

  const visibleMenus = menus.filter((item) => item.roles.includes(role))
  const currentMenu = visibleMenus.find((item) => item.key === location.pathname)
  const title = currentMenu?.label || '智能审核平台'

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r border-slate-200 bg-slate-950 text-white">
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
            const active = item.key === location.pathname
            return (
              <button
                key={item.key}
                onClick={() => navigate(item.key)}
                className={`flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm transition ${active ? 'bg-brand-600 text-white' : 'text-slate-300 hover:bg-white/10'}`}
              >
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
              <span>{user?.display_name}</span>
              <span className="text-slate-400">·</span>
              <span>{roleLabel}</span>
              {role === 'project_user' && projectName && (
                <>
                  <span className="text-slate-400">·</span>
                  <span>{projectName}</span>
                </>
              )}
            </div>
            <button
              onClick={() => { logout(); navigate('/login', { replace: true }) }}
              className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              <LogOut size={16} />
              退出登录
            </button>
          </div>
        </header>
        <section className="p-8" key={`${role}-${projectName}-${location.pathname}`}>
          {children}
        </section>
      </main>
    </div>
  )
}