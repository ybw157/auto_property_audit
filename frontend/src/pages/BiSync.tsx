import { useEffect, useState } from 'react'
import { request } from '../services/api'

type BiSyncRecord = {
  project_name: string
  project_code: string
  audit_month: string
  business_type: string
  file_name: string
  storage_path: string
  sync_status: string
  synced_at: string
}

type MasterProject = {
  project_name: string
  project_code: string
}

export function BiSync() {
  const [records, setRecords] = useState<BiSyncRecord[]>([])
  const [projects, setProjects] = useState<MasterProject[]>([])
  const [projectName, setProjectName] = useState('')
  const [auditMonth, setAuditMonth] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    request<MasterProject[]>('/api/v1/projects').then(setProjects).catch(() => setProjects([]))
    loadRecords()
  }, [])

  async function loadRecords() {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (projectName) params.set('project_name', projectName)
      if (auditMonth) params.set('audit_month', auditMonth)
      const query = params.toString()
      const rows = await request<BiSyncRecord[]>(`/api/v1/management/bi-sync${query ? `?${query}` : ''}`)
      setRecords(rows)
      setMessage(rows.length ? `已找到 ${rows.length} 个BI同步文件` : '未找到符合条件的BI同步文件')
    } catch (error) {
      setRecords([])
      setMessage(error instanceof Error ? error.message : 'BI同步状态读取失败')
    } finally {
      setLoading(false)
    }
  }

  const syncedCount = records.filter((item) => item.sync_status === '已同步').length
  const projectCount = new Set(records.map((item) => item.project_name).filter(Boolean)).size
  const monthCount = new Set(records.map((item) => item.audit_month).filter(Boolean)).size

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">BI数据同步</h2>
            <p className="mt-2 text-sm text-slate-500">
              系统只读取服务器 BI_Data 目录中的同步文件，不在网站内保存BI账号密码。审核时会按项目名称、审核月份和业态自动匹配。
            </p>
          </div>
          <button className="btn-secondary" disabled={loading} onClick={loadRecords}>
            {loading ? '刷新中...' : '刷新状态'}
          </button>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">同步文件数</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{records.length}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">涉及项目数</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{projectCount}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">涉及月份数</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{monthCount}</div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-4 rounded-2xl border border-slate-200 bg-white p-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">项目</span>
            <select className="input mt-2 w-full" value={projectName} onChange={(event) => setProjectName(event.target.value)}>
              <option value="">全部项目</option>
              {projects.map((item) => <option key={item.project_name} value={item.project_name}>{item.project_name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">审核月份</span>
            <input className="input mt-2 w-full" type="month" value={auditMonth} onChange={(event) => setAuditMonth(event.target.value)} />
          </label>
          <div className="flex items-end">
            <button className="btn-primary w-full" disabled={loading} onClick={loadRecords}>查询同步状态</button>
          </div>
        </div>

        {message && <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</div>}
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">同步文件明细</h2>
          <span className="text-xs text-slate-500">已同步：{syncedCount} 个</span>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-[1100px] table-fixed text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-48 px-4 py-3 text-left">项目</th>
                <th className="w-24 px-4 py-3 text-left">月份</th>
                <th className="w-24 px-4 py-3 text-left">业态</th>
                <th className="w-80 px-4 py-3 text-left">文件名</th>
                <th className="w-24 px-4 py-3 text-left">状态</th>
                <th className="w-40 px-4 py-3 text-left">同步时间</th>
                <th className="px-4 py-3 text-left">存储路径</th>
              </tr>
            </thead>
            <tbody>
              {records.map((item) => (
                <tr key={`${item.storage_path}-${item.file_name}`} className="border-t border-slate-100">
                  <td className="px-4 py-3 break-words">{item.project_name || '-'}</td>
                  <td className="px-4 py-3">{item.audit_month || '-'}</td>
                  <td className="px-4 py-3">{item.business_type || '-'}</td>
                  <td className="px-4 py-3 break-words">{item.file_name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">{item.sync_status}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{item.synced_at || '-'}</td>
                  <td className="px-4 py-3 text-xs text-slate-400 break-words">{item.storage_path}</td>
                </tr>
              ))}
              {!records.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={7}>暂无BI同步文件</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
