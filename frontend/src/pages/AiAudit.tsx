import { DragEvent, ChangeEvent, useEffect, useState } from 'react'
import { request, API_BASE_URL } from '../services/api'
import { fetchBusinessTypes, fetchContracts } from '../services/configCache'
import type { AuditContext } from '../types'
import { useAuth } from '../hooks/useAuth'
import { useAuditContext } from '../hooks/useAuditContext'

type FileKind = 'project'
type MasterProject = { project_name: string; project_code: string }

type StartAuditResult = {
  project_name: string
  business_type: string
  audit_month: string
  version: number
  status: string
  slot_count: number
  exception_count: number
  summary: Array<Record<string, unknown>>
}

export function AiAudit() {
  const { role: currentRole, projectName: currentProjectName } = useAuth()
  const { setAuditContext } = useAuditContext()
  const isProjectAccount = currentRole === 'project_user'
  const [projectFile, setProjectFile] = useState<File | null>(null)
  const [projects, setProjects] = useState<MasterProject[]>([])
  const [businessTypeMapping, setBusinessTypeMapping] = useState<Record<string, string[]>>({})
  const [selectedProjectName, setSelectedProjectName] = useState(isProjectAccount ? currentProjectName : '')
  const [auditMonth, setAuditMonth] = useState(() => {
    const now = new Date()
    // 默认上个月（BI考勤通常是上月数据）
    const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    return `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`
  })
  const [businessType, setBusinessType] = useState('')
  const [batchId, setBatchId] = useState<number | null>(null)
  const [message, setMessage] = useState('请上传项目基础资料后开始审核，BI考勤由系统自动读取BI_Data目录')
  const [loading, setLoading] = useState(false)
  const [dragging, setDragging] = useState<FileKind | 'all' | null>(null)
  const [uploaded, setUploaded] = useState(false)

  useEffect(() => {
    fetchContracts<Array<{ project_name: string; project_code: string; business_type: string }>>().then((items) => {
      const seen = new Map<string, MasterProject>()
      for (const item of items) {
        if (!seen.has(item.project_name)) seen.set(item.project_name, { project_name: item.project_name, project_code: item.project_code })
      }
      const unique = Array.from(seen.values())
      setProjects(unique)
      if (isProjectAccount && currentProjectName) {
        setSelectedProjectName(currentProjectName)
      } else if (unique.length && !selectedProjectName) {
        setSelectedProjectName(unique[0].project_name)
      }
    }).catch(() => setProjects([]))
  }, [currentRole, currentProjectName])

  useEffect(() => {
    fetchBusinessTypes()
      .then((data) => setBusinessTypeMapping(data.mapping || {}))
      .catch(() => {})
  }, [])

  // 业态随登录项目自动映射：项目唯一业态直接选中，无业态或无映射时清空为“全部业态”
  useEffect(() => {
    const mapped = businessTypeMapping[selectedProjectName] || []
    if (mapped.length === 0) {
      setBusinessType('')
    } else if (mapped.length === 1) {
      setBusinessType(mapped[0])
    }
  }, [selectedProjectName, businessTypeMapping])

  function isExcel(file: File) {
    return file.name.toLowerCase().endsWith('.xlsx')
  }

  async function resubmitSchedule() {
    if (!batchId) return setMessage('请先选择或完成一个批次，再重新提交排班')
    if (!projectFile) return setMessage('请选择修改后的项目基础资料.xlsx')
    setLoading(true)
    try {
      const form = new FormData()
      form.append('file', projectFile)
      await request('/api/v2/positions/upload', { method: 'POST', body: form })
      const auditMonthFormatted = auditMonth.replace('-', '')
      const result = await request<StartAuditResult>('/api/v2/audit-results/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_name: selectedProjectName, business_type: businessType, audit_month: auditMonthFormatted }),
      })
      setBatchId(result.version ?? null)
      setMessage(`排班已重新提交，批次 ${result.version} 状态已改为待重新审核。集团管理员可重新点击开始AI审核。`)
      const ctx: AuditContext = { project_name: selectedProjectName, audit_month: auditMonthFormatted, business_type: businessType }
      setAuditContext(ctx)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '重新提交失败')
    } finally {
      setLoading(false)
    }
  }

  function setFile(kind: FileKind, file: File) {
    if (kind === 'project' && !isExcel(file)) {
      setMessage('项目基础资料仅支持上传 .xlsx 文件')
      return
    }
    if (kind === 'project') {
      setProjectFile(file)
      setUploaded(false)
      setMessage(`已选择项目基础资料：${file.name}`)
      return
    }
  }

  function autoSetFiles(files: File[]) {
    const validFiles = files.filter((file) => isExcel(file))
    if (!validFiles.length) {
      setMessage('请拖入项目基础资料 .xlsx 文件')
      return
    }

    for (const file of validFiles) {
      const name = file.name.toLowerCase()
      if (name.includes('项目') || name.includes('基础')) {
        setProjectFile(file)
        setUploaded(false)
        setMessage(`已拖入项目基础资料：${file.name}`)
        return
      } else if (name.includes('bi') || name.includes('考勤')) {
        setMessage('BI考勤无需在页面上传，请由同步程序放入BI_Data目录')
        return
      }
    }
    setProjectFile(validFiles[0])
    setUploaded(false)
    setMessage(`已拖入项目基础资料：${validFiles[0].name}`)
  }

  function handleFileInput(kind: FileKind, event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    if (!files.length) return
    setFile(kind, files[0])
  }

  function handleDrop(kind: FileKind | 'all', event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.stopPropagation()
    setDragging(null)
    const files = Array.from(event.dataTransfer.files)
    if (kind === 'all') {
      autoSetFiles(files)
      return
    }
    const file = files[0]
    if (file) setFile(kind, file)
  }

  function handleDragOver(kind: FileKind | 'all', event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.stopPropagation()
    setDragging(kind)
  }

  async function uploadProjectOnly() {
    if (!projectFile) return setMessage('请先选择项目基础资料 .xlsx')
    setLoading(true)
    try {
      const form = new FormData()
      form.append('file', projectFile)
      await request('/api/v2/positions/upload', { method: 'POST', body: form })
      setUploaded(true)
      setMessage(`项目基础资料已上传：${projectFile.name}，可点击「开始AI审核」发起审核。`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '上传失败')
    } finally {
      setLoading(false)
    }
  }

  async function createAndUpload() {
    if (!selectedProjectName) return setMessage('请先选择项目。项目来自系统配置里的项目合同库，请先上传并启用项目合同。')
    if (!auditMonth) return setMessage('请选择审核月份。不同月份天数不同，会影响月度审核和报告统计。')
    if (!projectFile) return setMessage('请先选择项目基础资料')
    if (!uploaded) return setMessage('请先点击「上传项目资料」完成上传，再开始审核。')
    setLoading(true)
    try {
      const auditMonthFormatted = auditMonth.replace('-', '')
      const result = await request<StartAuditResult>('/api/v2/audit-results/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_name: selectedProjectName, business_type: businessType, audit_month: auditMonthFormatted }),
      })
      setBatchId(result.version ?? null)
      // 统一口径：异常率 = 异常记录数 / 排班任务数
      const scheduleTaskCount = result.slot_count || 0
      const exceptionCount = result.exception_count || 0
      const exceptionRate = scheduleTaskCount > 0 ? ((exceptionCount / scheduleTaskCount) * 100).toFixed(1) : '0.0'
      setMessage(`审核完成：异常率 ${exceptionRate}%`)
      const ctx: AuditContext = { project_name: selectedProjectName, audit_month: auditMonthFormatted, business_type: businessType }
      setAuditContext(ctx)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '审核失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div
        className={`card p-6 transition ${dragging === 'all' ? 'border-brand-500 bg-brand-50' : ''}`}
        onDragOver={(event) => handleDragOver('all', event)}
        onDragLeave={() => setDragging(null)}
        onDrop={(event) => handleDrop('all', event)}
      >
        <h2 className="text-lg font-semibold">上传项目基础资料</h2>
        <p className="mt-2 text-sm text-slate-500">项目端只上传项目基础资料.xlsx。BI考勤由同步程序写入服务器BI_Data目录，系统审核时会按项目名称和审核月份自动读取。</p>
        <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <label className="block text-sm font-medium text-slate-700">当前项目</label>
          {isProjectAccount ? (
            <div className="mt-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800">
              {selectedProjectName || '未绑定项目，请先在顶部选择项目账号对应项目'}
            </div>
          ) : (
            <select className="input mt-2 w-full" value={selectedProjectName} onChange={(event) => setSelectedProjectName(event.target.value)}>
              <option value="">请选择项目</option>
              {projects.map((item) => (
                <option key={`${item.project_name}-${item.project_code}`} value={item.project_name}>
                  {item.project_name}
                </option>
              ))}
            </select>
          )}
          <p className="mt-2 text-xs text-slate-500">项目来自“系统配置、项目合同库”。当前审核以月度排班表为唯一依据，合同编制表仅作为基础配置数据。</p>
          <div className="mt-4 rounded-2xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            BI考勤无需页面上传。系统会自动匹配 BI_Data 目录中的同步文件；若未同步，会提示“当前月份BI未同步”。
          </div>
          <div className="mt-4">
            <label className="block text-sm font-medium text-slate-700">选择审核月份</label>
            <select className="input mt-2 w-full" value={auditMonth} onChange={(event) => setAuditMonth(event.target.value)}>
              {(() => {
                const now = new Date()
                const options: { value: string; label: string }[] = []
                for (let i = 0; i < 12; i++) {
                  const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
                  const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
                  const label = `${d.getFullYear()}年${d.getMonth() + 1}月`
                  options.push({ value, label })
                }
                return options.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))
              })()}
            </select>
            <p className="mt-2 text-xs text-slate-500">系统会按所选月份统计大小月天数，并写入审核报告。</p>
          </div>
          <div className="mt-4">
            <label className="block text-sm font-medium text-slate-700">选择审核业态</label>
            <select className="input mt-2 w-full" value={businessType} onChange={(event) => setBusinessType(event.target.value)}>
              <option value="">全部业态</option>
              {(businessTypeMapping[selectedProjectName] || []).map((bt) => (
                <option key={bt} value={bt}>{bt}</option>
              ))}
            </select>
            <p className="mt-2 text-xs text-slate-500">不同业态对应不同合同。选择后仅审核该业态的排班和考勤。</p>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4">
          <UploadBox
            title="项目基础资料.xlsx"
            description="拖到这里，或点击选择项目基础资料"
            file={projectFile}
            active={dragging === 'project'}
            onDragOver={(event) => handleDragOver('project', event)}
            onDragLeave={() => setDragging(null)}
            onDrop={(event) => handleDrop('project', event)}
            onChange={(event) => handleFileInput('project', event)}
          />
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={loading} onClick={createAndUpload}>{loading ? '审核中...' : '开始AI审核'}</button>
          <button className="btn-secondary" disabled={loading || !projectFile} onClick={uploadProjectOnly}>{uploaded ? '重新上传项目资料' : '上传项目资料'}</button>
          <button className="btn-secondary" disabled={loading || !batchId} onClick={resubmitSchedule}>重新提交排班</button>
          <a className="btn-secondary" href={`${API_BASE_URL}/api/v2/templates/project_base`}>下载项目模板</a>
        </div>
      </div>
      <div className="card p-6">
        <h2 className="text-base font-semibold">审核进度</h2>
        <div className="mt-3 rounded-xl bg-slate-100 p-4 text-sm text-slate-700">{message}</div>
        {batchId && <div className="mt-3 text-sm text-slate-500">当前批次：{batchId}</div>}
      </div>
    </div>
  )
}

type UploadBoxProps = {
  title: string
  description: string
  file?: File | null
  active: boolean
  onDragOver: (event: DragEvent<HTMLDivElement>) => void
  onDragLeave: () => void
  onDrop: (event: DragEvent<HTMLDivElement>) => void
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
}

function UploadBox({ title, description, file, active, onDragOver, onDragLeave, onDrop, onChange }: UploadBoxProps) {
  const allFileNames = file ? [file.name] : []
  return (
    <div
      className={`rounded-2xl border border-dashed p-6 transition ${
        active ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-slate-300 bg-slate-50 hover:border-brand-400 hover:bg-brand-50'
      }`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <label className="block cursor-pointer">
        <div className="text-sm font-medium text-slate-900">{title}</div>
        <div className="mt-2 text-sm text-slate-500">{description}</div>
        <div className="mt-4 rounded-xl bg-white px-4 py-3 text-sm text-slate-700">
          {allFileNames.length ? (
            <div className="space-y-1">
              <div className="font-medium">已选择 {allFileNames.length} 个文件</div>
              {allFileNames.slice(0, 4).map((name) => <div key={name} className="truncate text-slate-500">{name}</div>)}
              {allFileNames.length > 4 && <div className="text-slate-500">还有 {allFileNames.length - 4} 个文件</div>}
            </div>
          ) : '尚未选择文件'}
        </div>
          <input className="sr-only" type="file" accept=".xlsx" onChange={onChange} />
        <div className="mt-4 inline-flex rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700">
          选择文件
        </div>
      </label>
    </div>
  )
}
