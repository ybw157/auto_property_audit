import { useEffect, useState } from 'react'
import { Users, UserPlus, RefreshCw, Trash2, KeyRound, Copy, Check, X } from 'lucide-react'
import { request } from '../services/api'

type User = {
  id: number
  username: string
  role: boolean
  display_name: string
  project_name: string
  project_code: string
  status: string
  created_at: string
  updated_at: string
}

type Project = { project_name: string; project_code: string }

type CreatedAccount = { username: string; password: string; project_name: string }

export function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({
    username: '',
    password: '',
    display_name: '',
    role: 'project_user',
    project_name: '',
  })
  const [creating, setCreating] = useState(false)

  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetting, setResetting] = useState(false)

  const [batchResult, setBatchResult] = useState<CreatedAccount[] | null>(null)
  const [batching, setBatching] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)

  useEffect(() => {
    loadUsers()
    loadProjects()
  }, [])

  async function loadUsers() {
    setLoading(true)
    try {
      const rows = await request<User[]>('/api/v2/user/users')
      setUsers(rows)
      setMessage(`共 ${rows.length} 个账号`)
    } catch (err: any) {
      setMessage(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadProjects() {
    try {
      const contracts = await request<any[]>('/api/v2/contracts')
      const seen = new Set<string>()
      const list: Project[] = []
      for (const c of contracts) {
        if (c.project_name && !seen.has(c.project_name)) {
          seen.add(c.project_name)
          list.push({ project_name: c.project_name, project_code: c.project_code || '' })
        }
      }
      setProjects(list)
    } catch {
      setProjects([])
    }
  }

  async function handleCreate() {
    if (!createForm.username.trim()) return setMessage('用户名不能为空')
    if (createForm.password.length < 6) return setMessage('密码至少 6 位')
    setCreating(true)
    try {
      // TODO: V2用户创建接口待后端提供
      await request('/api/v1/auth/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...createForm, role: createForm.role === 'group_admin' }),
      })
      setMessage(`用户 ${createForm.username} 创建成功`)
      setShowCreate(false)
      setCreateForm({ username: '', password: '', display_name: '', role: 'project_user', project_name: '' })
      await loadUsers()
    } catch (err: any) {
      setMessage(err.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  async function handleReset() {
    if (!resetTarget) return
    if (newPassword.length < 6) return setMessage('新密码至少 6 位')
    setResetting(true)
    try {
      // TODO: V2 change-password需要old_password，管理员重置场景待后端支持
      await request(`/api/v1/auth/users/${resetTarget.id}/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPassword }),
      })
      setMessage(`用户 ${resetTarget.username} 密码已重置`)
      setResetTarget(null)
      setNewPassword('')
    } catch (err: any) {
      setMessage(err.message || '重置失败')
    } finally {
      setResetting(false)
    }
  }

  async function handleDelete(user: User) {
    if (!confirm(`确认删除用户「${user.display_name || user.username}」？此操作不可撤销。`)) return
    try {
      // TODO: V2用户删除接口待后端提供
      await request(`/api/v1/auth/users/${user.id}`, { method: 'DELETE' })
      setMessage(`用户 ${user.username} 已删除`)
      await loadUsers()
    } catch (err: any) {
      setMessage(err.message || '删除失败')
    }
  }

  async function handleBatchCreate() {
    if (!confirm('将为所有未创建账号的项目批量生成项目账号，确认继续？')) return
    setBatching(true)
    try {
      // TODO: V2批量创建接口待后端提供
      const data = await request<{ created: CreatedAccount[]; count: number; message: string }>(
        '/api/v1/auth/users/batch-projects',
        { method: 'POST' },
      )
      setBatchResult(data.created)
      setMessage(data.message)
      await loadUsers()
    } catch (err: any) {
      setMessage(err.message || '批量创建失败')
    } finally {
      setBatching(false)
    }
  }

  async function handleRegeneratePasswords() {
    if (!confirm('将重新生成所有项目账号的密码（旧密码失效），并在页面显示新密码。确认继续？')) return
    setRegenerating(true)
    try {
      // TODO: V2重新生成密码接口待后端提供
      const data = await request<{ accounts: CreatedAccount[]; count: number; message: string }>(
        '/api/v1/auth/users/regenerate-passwords',
        { method: 'POST' },
      )
      setBatchResult(data.accounts)
      setMessage(data.message + '，请立即复制保存')
      await loadUsers()
    } catch (err: any) {
      setMessage(err.message || '重新生成失败')
    } finally {
      setRegenerating(false)
    }
  }

  async function copyToClipboard(text: string, key: string) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        ta.style.top = '0'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('execCommand copy failed')
      }
      setCopied(key)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '0'
      ta.style.top = '0'
      ta.style.width = '500px'
      ta.style.height = '300px'
      ta.style.zIndex = '9999'
      ta.style.fontSize = '14px'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      setMessage('自动复制失败，请手动 Ctrl+C 复制文本框内容')
      setTimeout(() => document.body.removeChild(ta), 10000)
    }
  }

  function copyAllAccounts() {
    if (!batchResult) return
    const text = batchResult.map((a) => `${a.project_name}\t${a.username}\t${a.password}`).join('\n')
    copyToClipboard(text, 'all')
  }

  const roleLabel = (role: boolean) => role ? '集团管理员' : '项目账号'
  const roleBadge = (role: boolean) =>
    role
      ? 'bg-purple-100 text-purple-700'
      : 'bg-blue-100 text-blue-700'

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Users size={20} />
              用户管理
            </h2>
            <p className="mt-2 text-sm text-slate-500">
              管理系统账号。集团管理员可查看所有数据，项目账号只能访问自己项目的页面。
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              className="btn-secondary flex items-center gap-2"
              disabled={loading}
              onClick={loadUsers}
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
            <button
              className="btn-secondary flex items-center gap-2"
              disabled={batching}
              onClick={handleBatchCreate}
            >
              <Users size={16} />
              {batching ? '生成中...' : '批量生成项目账号'}
            </button>
            <button
              className="btn-secondary flex items-center gap-2"
              disabled={regenerating}
              onClick={handleRegeneratePasswords}
            >
              <KeyRound size={16} />
              {regenerating ? '生成中...' : '查看所有项目账号密码'}
            </button>
            <button
              className="btn-primary flex items-center gap-2"
              onClick={() => setShowCreate(!showCreate)}
            >
              <UserPlus size={16} />
              新建用户
            </button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">总账号数</div>
            <div className="mt-1 text-2xl font-semibold text-slate-950">{users.length}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">集团管理员</div>
            <div className="mt-1 text-2xl font-semibold text-slate-950">
              {users.filter((u) => u.role === true).length}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">项目账号</div>
            <div className="mt-1 text-2xl font-semibold text-slate-950">
              {users.filter((u) => u.role === false).length}
            </div>
          </div>
        </div>

        {message && (
          <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</div>
        )}
      </div>

      {showCreate && (
        <div className="card p-6">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold">新建用户</h3>
            <button onClick={() => setShowCreate(false)} className="text-slate-400 hover:text-slate-600">
              <X size={20} />
            </button>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">用户名</span>
              <input
                className="input mt-1.5 w-full"
                value={createForm.username}
                onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                placeholder="登录用户名"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">密码</span>
              <input
                className="input mt-1.5 w-full"
                value={createForm.password}
                onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                placeholder="至少 6 位"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">显示名称</span>
              <input
                className="input mt-1.5 w-full"
                value={createForm.display_name}
                onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                placeholder="留空则用用户名"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">角色</span>
              <select
                className="input mt-1.5 w-full"
                value={createForm.role}
                onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
              >
                <option value="project_user">项目账号</option>
                <option value="group_admin">集团管理员</option>
              </select>
            </label>
            {createForm.role === 'project_user' && (
              <label className="block col-span-2">
                <span className="text-sm font-medium text-slate-700">绑定项目</span>
                <select
                  className="input mt-1.5 w-full"
                  value={createForm.project_name}
                  onChange={(e) => setCreateForm({ ...createForm, project_name: e.target.value })}
                >
                  <option value="">请选择项目</option>
                  {projects.map((p) => (
                    <option key={p.project_name} value={p.project_name}>
                      {p.project_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="mt-4 flex gap-3">
            <button className="btn-primary" disabled={creating} onClick={handleCreate}>
              {creating ? '创建中...' : '确认创建'}
            </button>
            <button className="btn-secondary" onClick={() => setShowCreate(false)}>
              取消
            </button>
          </div>
        </div>
      )}

      {batchResult && (
        <div className="card p-6">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold">项目账号密码（{batchResult.length} 个）</h3>
            <div className="flex gap-3">
              <button
                className="btn-secondary flex items-center gap-2"
                onClick={copyAllAccounts}
              >
                {copied === 'all' ? <Check size={16} /> : <Copy size={16} />}
                {copied === 'all' ? '已复制' : '复制全部'}
              </button>
              <button className="btn-secondary" onClick={() => setBatchResult(null)}>
                关闭
              </button>
            </div>
          </div>
          <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-4 py-2 text-left">项目名称</th>
                  <th className="px-4 py-2 text-left">用户名</th>
                  <th className="px-4 py-2 text-left">密码</th>
                  <th className="px-4 py-2 text-center">复制</th>
                </tr>
              </thead>
              <tbody>
                {batchResult.map((acc) => {
                  const key = acc.username
                  return (
                    <tr key={key} className="border-t border-slate-100">
                      <td className="px-4 py-2 font-medium text-slate-800">{acc.project_name}</td>
                      <td className="px-4 py-2 text-slate-600">{acc.username}</td>
                      <td className="px-4 py-2 font-mono text-slate-600">{acc.password}</td>
                      <td className="px-4 py-2 text-center">
                        <button
                          className="text-slate-400 hover:text-brand-600"
                          onClick={() => copyToClipboard(`${acc.username}\t${acc.password}`, key)}
                        >
                          {copied === key ? <Check size={16} /> : <Copy size={16} />}
                        </button>
                      </td>
                    </tr>
                  )
                })}
                {batchResult.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                      所有项目已创建账号，无需新增
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">账号列表</h3>
          <span className="text-xs text-slate-500">共 {users.length} 条</span>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-2 text-left">用户名</th>
                <th className="px-4 py-2 text-left">显示名称</th>
                <th className="px-4 py-2 text-left">角色</th>
                <th className="px-4 py-2 text-left">绑定项目</th>
                <th className="px-4 py-2 text-left">状态</th>
                <th className="px-4 py-2 text-left">创建时间</th>
                <th className="px-4 py-2 text-center">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-800">{u.username}</td>
                  <td className="px-4 py-2 text-slate-600">{u.display_name || u.username}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${roleBadge(u.role)}`}>
                      {roleLabel(u.role)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{u.project_name || '—'}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        u.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      {u.status === 'active' ? '正常' : '禁用'}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{u.created_at || '-'}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center justify-center gap-2">
                      <button
                        className="text-slate-400 hover:text-brand-600"
                        title="重置密码"
                        onClick={() => {
                          setResetTarget(u)
                          setNewPassword('')
                        }}
                      >
                        <KeyRound size={16} />
                      </button>
                      <button
                        className="text-slate-400 hover:text-red-600"
                        title="删除用户"
                        onClick={() => handleDelete(u)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!users.length && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    暂无用户数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {resetTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="card w-96 p-6">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">重置密码</h3>
              <button
                onClick={() => setResetTarget(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X size={20} />
              </button>
            </div>
            <p className="mt-3 text-sm text-slate-500">
              正在为用户「{resetTarget.display_name || resetTarget.username}」重置密码
            </p>
            <label className="mt-4 block">
              <span className="text-sm font-medium text-slate-700">新密码</span>
              <input
                className="input mt-1.5 w-full"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="至少 6 位"
                autoFocus
              />
            </label>
            <div className="mt-4 flex gap-3">
              <button className="btn-primary" disabled={resetting} onClick={handleReset}>
                {resetting ? '重置中...' : '确认重置'}
              </button>
              <button className="btn-secondary" onClick={() => setResetTarget(null)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
