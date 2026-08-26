import { useState, type FormEvent } from 'react'
import { ShieldCheck, Loader2 } from 'lucide-react'
import { request } from '../services/api'

type LoginUser = {
  username: string
  role: string
  display_name: string
  project_name: string
  project_code: string
}

export function Login({ onSuccess }: { onSuccess: (token: string, user: LoginUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await request<{ token: string; user: LoginUser }>('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      onSuccess(data.token, data.user)
    } catch (err: any) {
      setError(err.message || '登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="rounded-2xl bg-brand-600 p-4">
            <ShieldCheck size={32} className="text-white" />
          </div>
          <h1 className="mt-5 text-xl font-semibold text-white">物业集团保安保洁智能审核平台</h1>
          <p className="mt-2 text-sm text-slate-400">请登录后使用</p>
        </div>
        <form onSubmit={handleSubmit} className="card space-y-4 p-6">
          <div>
            <label className="text-sm font-medium text-slate-700">用户名</label>
            <input
              className="input mt-1.5 w-full"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
              autoFocus
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700">密码</label>
            <input
              type="password"
              className="input mt-1.5 w-full"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </div>
          {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600">{error}</div>}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary flex w-full items-center justify-center gap-2"
          >
            {loading && <Loader2 size={16} className="animate-spin" />}
            {loading ? '登录中…' : '登录'}
          </button>
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">
            默认账号：group_admin / admin123（集团管理员）
            <br />
            project_user / proj123（项目账号）
          </div>
        </form>
      </div>
    </div>
  )
}
