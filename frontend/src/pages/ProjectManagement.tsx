import { useEffect, useState } from 'react'
import { request } from '../services/api'

type ProjectStatus = {
  project_name: string
  project_code: string
  business_type: string
  contract_status: string
  security_contract_status: string
  cleaning_contract_status: string
  schedule_status: string
  security_schedule_status: string
  cleaning_schedule_status: string
  audit_status: string
  security_audit_status: string
  cleaning_audit_status: string
  security_audit_time: string
  cleaning_audit_time: string
}

function statusBadgeClass(status: string): string {
  if (status === '—') return 'bg-slate-50 text-slate-300'
  if (status === '已启用' || status === '已确认' || status === '审核完成') return 'bg-green-100 text-green-700'
  if (status === '已上传' || status === '已重新提交' || status === '审核中' || status === '待审核') return 'bg-blue-100 text-blue-700'
  if (status === '审核失败' || status === '校验失败') return 'bg-red-100 text-red-700'
  return 'bg-amber-100 text-amber-700'
}

export function ProjectManagement() {
  const [projects, setProjects] = useState<ProjectStatus[]>([])
  const [contractFilter, setContractFilter] = useState('全部')
  const [scheduleFilter, setScheduleFilter] = useState('全部')
  const [auditFilter, setAuditFilter] = useState('全部')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadProjects()
  }, [])

  async function loadProjects() {
    setLoading(true)
    try {
      const rows = await request<ProjectStatus[]>('/api/v1/management/projects')
      setProjects(rows)
      setMessage(`已加载 ${rows.length} 条项目业态状态`)
    } catch (error) {
      setProjects([])
      setMessage(error instanceof Error ? error.message : '项目状态读取失败')
    } finally {
      setLoading(false)
    }
  }

  const filteredProjects = projects.filter((item) => {
    const contractOk = contractFilter === '全部' || (contractFilter === '已上传'
      ? item.security_contract_status.includes('已上传') || item.cleaning_contract_status.includes('已上传')
      : !item.security_contract_status.includes('已上传') && !item.cleaning_contract_status.includes('已上传'))
    const scheduleOk = scheduleFilter === '全部' || (scheduleFilter === '已上传'
      ? item.security_schedule_status.includes('已上传') || item.security_schedule_status.includes('已重新提交') || item.cleaning_schedule_status.includes('已上传') || item.cleaning_schedule_status.includes('已重新提交')
      : !item.security_schedule_status.includes('已上传') && !item.security_schedule_status.includes('已重新提交') && !item.cleaning_schedule_status.includes('已上传') && !item.cleaning_schedule_status.includes('已重新提交'))
    const auditOk = auditFilter === '全部' || item.security_audit_status === auditFilter || item.cleaning_audit_status === auditFilter
    const keywordOk = !keyword || `${item.project_name}${item.business_type}`.includes(keyword)
    return contractOk && scheduleOk && auditOk && keywordOk
  })

  const securityContractActive = projects.filter((item) => item.security_contract_status === '已启用').length
  const cleaningContractActive = projects.filter((item) => item.cleaning_contract_status === '已启用').length
  const scheduleUploaded = projects.filter((item) =>
    item.security_schedule_status.includes('已上传') || item.security_schedule_status.includes('已重新提交') ||
    item.cleaning_schedule_status.includes('已上传') || item.cleaning_schedule_status.includes('已重新提交')
  ).length
  const auditCompleted = projects.filter((item) =>
    item.security_audit_status === '审核完成' || item.cleaning_audit_status === '审核完成'
  ).length

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">项目管理</h2>
            <p className="mt-2 text-sm text-slate-500">集团端按项目+业态查看保安/保洁的合同、排班和审核状态，快速识别哪些项目未上传资料。</p>
          </div>
          <button className="btn-secondary" disabled={loading} onClick={loadProjects}>{loading ? '刷新中...' : '刷新状态'}</button>
        </div>

        <div className="mt-5 grid grid-cols-5 gap-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">项目业态总数</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{projects.length}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">保安已启用合同</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{securityContractActive}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">保洁已启用合同</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{cleaningContractActive}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">已上传排班</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{scheduleUploaded}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-sm text-slate-500">审核完成</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950">{auditCompleted}</div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-5 gap-4 rounded-2xl border border-slate-200 bg-white p-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">搜索项目/业态</span>
            <input className="input mt-2 w-full" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="例如：江宁、商业" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">合同状态</span>
            <select className="input mt-2 w-full" value={contractFilter} onChange={(event) => setContractFilter(event.target.value)}>
              <option value="全部">全部</option>
              <option value="已上传">已上传</option>
              <option value="未上传">未上传</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">排班状态</span>
            <select className="input mt-2 w-full" value={scheduleFilter} onChange={(event) => setScheduleFilter(event.target.value)}>
              <option value="全部">全部</option>
              <option value="已上传">已上传</option>
              <option value="未上传">未上传</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">审核状态</span>
            <select className="input mt-2 w-full" value={auditFilter} onChange={(event) => setAuditFilter(event.target.value)}>
              <option value="全部">全部</option>
              <option value="待上传">待上传</option>
              <option value="待审核">待审核</option>
              <option value="审核完成">审核完成</option>
              <option value="已确认">已确认</option>
            </select>
          </label>
          <div className="flex items-end">
            <button className="btn-primary w-full" onClick={() => {
              setKeyword('')
              setContractFilter('全部')
              setScheduleFilter('全部')
              setAuditFilter('全部')
            }}>重置筛选</button>
          </div>
        </div>

        {message && <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</div>}
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">项目状态明细</h2>
          <span className="text-xs text-slate-500">当前显示 {filteredProjects.length} 条</span>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full table-fixed text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-28 px-2 py-2 text-left">项目</th>
                <th className="w-12 px-2 py-2 text-left">业态</th>
                <th className="w-14 px-2 py-2 text-center">保安<br/>合同</th>
                <th className="w-14 px-2 py-2 text-center">保洁<br/>合同</th>
                <th className="w-14 px-2 py-2 text-center">保安<br/>排班</th>
                <th className="w-14 px-2 py-2 text-center">保洁<br/>排班</th>
                <th className="w-14 px-2 py-2 text-center">保安<br/>审核</th>
                <th className="w-14 px-2 py-2 text-center">保洁<br/>审核</th>
                <th className="w-20 px-2 py-2 text-left">保安完成<br/>时间</th>
                <th className="w-20 px-2 py-2 text-left">保洁完成<br/>时间</th>
              </tr>
            </thead>
            <tbody>
              {filteredProjects.map((item) => (
                <tr key={`${item.project_name}-${item.project_code}-${item.business_type}`} className="border-t border-slate-100">
                  <td className="px-2 py-2 font-medium text-slate-800 break-words">{item.project_name}</td>
                  <td className="px-2 py-2">{item.business_type || '-'}</td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.security_contract_status)}`}>{item.security_contract_status}</span>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.cleaning_contract_status)}`}>{item.cleaning_contract_status}</span>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.security_schedule_status)}`}>{item.security_schedule_status}</span>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.cleaning_schedule_status)}`}>{item.cleaning_schedule_status}</span>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.security_audit_status)}`}>{item.security_audit_status}</span>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${statusBadgeClass(item.cleaning_audit_status)}`}>{item.cleaning_audit_status}</span>
                  </td>
                  <td className="px-2 py-2 text-xs text-slate-600 whitespace-nowrap">{item.security_audit_time || '-'}</td>
                  <td className="px-2 py-2 text-xs text-slate-600 whitespace-nowrap">{item.cleaning_audit_time || '-'}</td>
                </tr>
              ))}
              {!filteredProjects.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={10}>没有符合筛选条件的项目</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
