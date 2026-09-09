import { DragEvent, useEffect, useSyncExternalStore, useState } from 'react'
import { request } from '../services/api'
import { useAuth } from '../hooks/useAuth'

type ProjectContract = {
  id: number
  project_name: string
  project_code: string
  business_type: string
  supplier: string
  contract_no: string
  contract_name: string
  service_type: string
  version: string
  start_date: string
  end_date: string
  original_name: string
  file_format: string
  download_url: string
  is_active: number
  status: string
  rules: Record<string, unknown>
  updated_at: string
}

function formatRules(rules: Record<string, unknown>) {
  if (!rules || !Object.keys(rules).length) return '未解析出合同扣款细则'
  const parts: string[] = []
  const tiers = rules.late_early_tiers as Array<{ max_minutes: number; amount: number }> | undefined
  if (tiers?.length) {
    parts.push(`迟到/早退：${tiers.map((item) => `≤${item.max_minutes}分钟${item.amount}元`).join('，')}，超时按缺勤`)
  }
  if (rules.missing_clock_deduction) {
    const freeTimes = rules.missing_clock_free_times_per_month
    const proofText = rules.missing_clock_free_requires_attendance_proof ? '且需有效出勤证明，' : ''
    parts.push(`漏打卡：${freeTimes ? `每月前${freeTimes}次${proofText}不扣，` : ''}${rules.missing_clock_deduction}元/次`)
  }
  if (rules.contract_deduction_coefficient) {
    parts.push(`缺编/缺岗：工时单价×${rules.contract_deduction_coefficient}×缺勤总时长`)
  }
  return parts.join('；') || '已解析合同规则'
}

type ContractUploadState = {
  uploading: boolean
  fileName: string
  message: string
  result: ProjectContract | null
  error: string | null
}

let _contractUpload: ContractUploadState = {
  uploading: false,
  fileName: '',
  message: '',
  result: null,
  error: null,
}

const _uploadListeners = new Set<() => void>()

function _setContractUpload(patch: Partial<ContractUploadState>) {
  _contractUpload = { ..._contractUpload, ...patch }
  _uploadListeners.forEach((listener) => listener())
}

function useContractUpload(): ContractUploadState {
  return useSyncExternalStore(
    (listener) => {
      _uploadListeners.add(listener)
      return () => { _uploadListeners.delete(listener) }
    },
    () => _contractUpload,
    () => _contractUpload,
  )
}

export function ContractManagement() {
  const { role: currentRole, projectName: currentProjectName } = useAuth()
  const [contracts, setContracts] = useState<ProjectContract[]>([])
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [message, setMessage] = useState('')
  const uploadState = useContractUpload()
  const [draggingContract, setDraggingContract] = useState(false)
  const [businessTypeMapping, setBusinessTypeMapping] = useState<Record<string, string[]>>({})
  const [allProjects, setAllProjects] = useState<string[]>([])
  const isAdmin = currentRole === 'group_admin'

  useEffect(() => {
    loadContracts()
  }, [currentRole, currentProjectName])

  useEffect(() => {
    request<{ projects: string[]; mapping: Record<string, string[]> }>('/api/v2/business-types')
      .then((data) => {
        setBusinessTypeMapping(data.mapping)
        setAllProjects(data.projects)
      })
      .catch(() => {})
  }, [])

  async function loadContracts() {
    try {
      // 后端根据用户角色自动筛选项目，前端无需传递 project_name
      const rows = await request<ProjectContract[]>('/api/v2/contracts')
      setContracts(rows)
    } catch {
      // 保留已有列表，不清空，避免停用/启用后记录"消失"
    }
  }

  function isContractFile(file: File) {
    const name = file.name.toLowerCase()
    return name.endsWith('.pdf') || name.endsWith('.doc') || name.endsWith('.docx')
  }

  function selectContractFile(file: File) {
    if (!isContractFile(file)) {
      setMessage('合同仅支持 PDF、Word（.doc/.docx）文件')
      return
    }
    setContractFile(file)
    setMessage(`已选择合同文件：${file.name}`)
  }

  function handleContractDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDraggingContract(false)
    const file = Array.from(event.dataTransfer.files).find(isContractFile)
    if (!file) {
      setMessage('请拖入 PDF、Word（.doc/.docx）合同文件')
      return
    }
    selectContractFile(file)
  }

  function handleContractDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDraggingContract(true)
  }

  async function uploadContract() {
    if (!contractFile) {
      setMessage('请选择合同文件')
      return
    }
    const file = contractFile
    _setContractUpload({
      uploading: true,
      fileName: file.name,
      message: '合同上传中，正在自动识别合同信息和扣款条款，可能需要几十秒，请稍等。',
      result: null,
      error: null,
    })
    setContractFile(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const result = await request<ProjectContract>('/api/v2/contracts/upload', {
        method: 'POST',
        body: form,
      })
      _setContractUpload({
        uploading: false,
        fileName: '',
        result,
        message: result.is_active ? '合同已上传并解析，请核对以下明细信息，确认无误后保存。' : '合同已上传，但部分扣款细则未解析出，请补充必填项后保存。',
        error: null,
      })
    } catch (error) {
      _setContractUpload({
        uploading: false,
        fileName: '',
        result: null,
        error: error instanceof Error ? error.message : '合同上传失败',
      })
    }
  }

  function validateContractForActivation(item: ProjectContract): string | null {
    const missing: string[] = []
    if (!item.project_name) missing.push('项目名称')
    if (!item.business_type) missing.push('业务类型')
    if (!item.contract_name) missing.push('合同名称')
    if (!item.supplier) missing.push('供应商')
    if (!item.start_date) missing.push('开始日期')
    if (!item.end_date) missing.push('结束日期')
    const rules = item.rules as Record<string, unknown>
    const tiers = rules['late_early_tiers'] as Array<{ max_minutes: number; amount: number }> | undefined
    if (!tiers?.length) missing.push('迟到/早退扣款')
    if (!rules['missing_clock_deduction']) missing.push('漏打卡扣款')
    if (!rules['contract_deduction_coefficient']) missing.push('缺编系数')
    if (missing.length === 0) return null
    return `以下必填项未填写：${missing.join('、')}，请先编辑补全后再启用`
  }

  async function setContractActive(item: ProjectContract, isActive: boolean) {
    if (isActive) {
      const error = validateContractForActivation(item)
      if (error) {
        window.alert(error)
        return
      }
    }
    try {
      await request(`/api/v2/contracts/${item.id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: isActive }),
      })
      setMessage(isActive ? '合同已启用' : '合同已停用')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '合同状态更新失败')
    } finally {
      loadContracts()
    }
  }

  async function deleteContract(item: ProjectContract) {
    if (!window.confirm(`确定删除合同「${item.contract_name || item.original_name}」吗？删除后将不再展示，但不会影响历史审核记录。`)) return
    try {
      if (item.is_active) {
        await request(`/api/v2/contracts/${item.id}/status`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: false }),
        })
      }
      await request(`/api/v2/contracts/${item.id}`, { method: 'DELETE' })
      setMessage('合同已删除')
      loadContracts()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '删除失败')
      loadContracts()
    }
  }

  const [editingContract, setEditingContract] = useState<ProjectContract | null>(null)
  const [editFields, setEditFields] = useState({
    project_name: '',
    business_type: '',
    contract_name: '',
    supplier: '',
    start_date: '',
    end_date: '',
  })
  const [manualRules, setManualRules] = useState({
    late_early_tier_30: '',
    late_early_tier_60: '',
    late_early_over: '60',
    missing_clock_deduction: '50',
    missing_clock_free_times: '3',
    missing_clock_proof: true,
    deduction_coefficient: '1.2',
    daily_cap: '',
  })
  const [savingRules, setSavingRules] = useState(false)
  const [validationErrors, setValidationErrors] = useState<Record<string, boolean>>({})

  function validateRequiredFields(): boolean {
    const errors: Record<string, boolean> = {}
    const requiredFields = [
      'project_name',
      'business_type',
      'contract_name',
      'supplier',
      'start_date',
      'end_date',
      'late_early_tier_30',
      'late_early_tier_60',
      'late_early_over',
      'missing_clock_deduction',
      'missing_clock_free_times',
      'deduction_coefficient',
    ]
    for (const field of requiredFields) {
      if (field in editFields) {
        if (!(editFields as Record<string, string>)[field]) errors[field] = true
      } else if (field in manualRules) {
        if (!(manualRules as Record<string, string | boolean>)[field]) errors[field] = true
      }
    }
    setValidationErrors(errors)
    return Object.keys(errors).length === 0
  }

  function clearFieldError(field: string) {
    if (validationErrors[field]) {
      setValidationErrors({ ...validationErrors, [field]: false })
    }
  }

  function inputClass(field: string): string {
    return `input mt-1 w-full${validationErrors[field] ? ' border-red-500 ring-1 ring-red-200' : ''}`
  }

  function openManualEditor(item: ProjectContract) {
    setEditingContract(item)
    setValidationErrors({})
    setEditFields({
      project_name: item.project_name || (isAdmin ? '' : currentProjectName) || '',
      business_type: item.business_type || '',
      contract_name: item.contract_name || '',
      supplier: item.supplier || '',
      start_date: item.start_date || '',
      end_date: item.end_date || '',
    })
    const rules = item.rules as Record<string, unknown>
    const tiers = (rules['late_early_tiers'] as Array<{ max_minutes: number; amount: number }>) || []
    setManualRules({
      late_early_tier_30: String(tiers.find((t) => t.max_minutes === 30)?.amount || ''),
      late_early_tier_60: String(tiers.find((t) => t.max_minutes === 60)?.amount || ''),
      late_early_over: String(rules['late_early_over_minutes_as_absence'] || '60'),
      missing_clock_deduction: String(rules['missing_clock_deduction'] || ''),
      missing_clock_free_times: String(rules['missing_clock_free_times_per_month'] || ''),
      missing_clock_proof: rules['missing_clock_free_requires_attendance_proof'] !== false,
      deduction_coefficient: String(rules['contract_deduction_coefficient'] || ''),
      daily_cap: String(rules['single_person_daily_cap'] || ''),
    })
  }

  async function saveManualRules() {
    if (!editingContract) return
    if (!validateRequiredFields()) {
      setMessage('请填写所有必填项（单人单日扣款上限为选填）')
      return
    }
    setSavingRules(true)
    try {
      const tiers: Array<{ max_minutes: number; amount: number }> = []
      if (manualRules.late_early_tier_30) {
        tiers.push({ max_minutes: 30, amount: parseFloat(manualRules.late_early_tier_30) })
      }
      if (manualRules.late_early_tier_60) {
        tiers.push({ max_minutes: 60, amount: parseFloat(manualRules.late_early_tier_60) })
      }
      const rulesPayload: Record<string, unknown> = { late_early_tiers: tiers }
      if (manualRules.late_early_over) rulesPayload['late_early_over_minutes_as_absence'] = parseFloat(manualRules.late_early_over)
      if (manualRules.missing_clock_deduction) rulesPayload['missing_clock_deduction'] = parseFloat(manualRules.missing_clock_deduction)
      if (manualRules.missing_clock_free_times) rulesPayload['missing_clock_free_times_per_month'] = parseFloat(manualRules.missing_clock_free_times)
      rulesPayload['missing_clock_free_requires_attendance_proof'] = manualRules.missing_clock_proof
      if (manualRules.deduction_coefficient) rulesPayload['contract_deduction_coefficient'] = parseFloat(manualRules.deduction_coefficient)
      if (manualRules.daily_cap) rulesPayload['single_person_daily_cap'] = parseFloat(manualRules.daily_cap)

      const payload: Record<string, unknown> = {
        project_name: editFields.project_name || undefined,
        business_type: editFields.business_type || undefined,
        contract_name: editFields.contract_name || undefined,
        supplier: editFields.supplier || undefined,
        start_date: editFields.start_date || undefined,
        end_date: editFields.end_date || undefined,
        rules: rulesPayload,
      }

      await request(`/api/v2/contracts/${editingContract.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      setMessage('合同信息已保存')
      setEditingContract(null)
      await loadContracts()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    }
    setSavingRules(false)
  }

  useEffect(() => {
    if (uploadState.result) {
      const result = uploadState.result
      const msg = uploadState.message
      _setContractUpload({ result: null, message: '', error: null })
      setMessage(msg)
      loadContracts()
      openManualEditor(result)
    } else if (uploadState.error) {
      const errMsg = uploadState.error
      _setContractUpload({ error: null, message: '' })
      setMessage(errMsg)
    }
  }, [uploadState.result, uploadState.error])

  // 业态下拉映射键：项目账号锁定登录项目；集团管理员按当前编辑所选的项目
  const effectiveBtProject = isAdmin ? editFields.project_name : currentProjectName
  const businessTypeOptions = businessTypeMapping[effectiveBtProject] || []

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h2 className="text-lg font-semibold">项目合同库</h2>
        <p className="mt-2 text-sm text-slate-500">
          直接上传合同 PDF / Word，系统会自动识别合同信息和扣款条款。合同解析有误时，可点击"编辑"手动填写扣款规则后启用。
        </p>
        <div
          className={`mt-4 rounded-2xl border border-dashed p-4 transition ${draggingContract ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-slate-300 bg-slate-50'}`}
          onDragOver={handleContractDragOver}
          onDragLeave={() => setDraggingContract(false)}
          onDrop={handleContractDrop}
        >
          <div className="flex items-center justify-between gap-4">
            <label className="flex-1 cursor-pointer rounded-xl bg-white px-4 py-4 text-sm text-slate-600">
              <span className="font-medium text-slate-800">{uploadState.uploading ? uploadState.fileName : contractFile ? contractFile.name : '拖入合同文件，或点击选择 PDF / Word 文件'}</span>
              <span className="mt-1 block text-xs text-slate-400">支持 .pdf、.doc、.docx；拖拽到当前区域即可选中文件。系统将自动识别合同中的所有信息。</span>
              <input className="sr-only" type="file" accept=".pdf,.doc,.docx" onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) selectContractFile(file)
              }} />
            </label>
            <button className="btn-primary" disabled={uploadState.uploading} onClick={uploadContract}>
              {uploadState.uploading ? '上传解析中...' : '上传合同'}
            </button>
          </div>
        </div>
        {(uploadState.uploading || message) && (
          <div className={`mt-3 rounded-xl px-4 py-3 text-sm break-words ${uploadState.uploading ? 'bg-blue-50 text-blue-600' : 'bg-slate-50 text-slate-600'}`}>
            {uploadState.uploading ? uploadState.message : message}
          </div>
        )}
        <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-[980px] table-fixed text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-40 px-4 py-3 text-left">项目</th>
                <th className="w-20 px-4 py-3 text-left">业态</th>
                <th className="w-56 px-4 py-3 text-left">合同</th>
                <th className="w-28 px-4 py-3 text-left">供应商</th>
                <th className="w-36 px-4 py-3 text-left">有效期</th>
                <th className="w-72 px-4 py-3 text-left">扣款规则</th>
                <th className="w-20 px-4 py-3 text-left">状态</th>
                <th className="w-20 px-4 py-3 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((item) => (
                <tr key={item.id} className="border-t border-slate-100">
                  <td className="px-4 py-3 align-top break-words">{item.project_name}</td>
                  <td className="px-4 py-3 align-top">{item.business_type || '-'}</td>
                  <td className="px-4 py-3 align-top break-words">
                    <a className="text-brand-700 underline break-words" href={item.download_url} target="_blank">{item.contract_name}</a>
                    <div className="text-xs text-slate-400 break-words">{item.contract_no || item.version || item.original_name}</div>
                  </td>
                  <td className="px-4 py-3 align-top break-words">{item.supplier || '-'}</td>
                  <td className="px-4 py-3 align-top break-words">{item.start_date || '-'} 至 {item.end_date || '-'}</td>
                  <td className="px-4 py-3 align-top text-xs text-slate-500 break-words">{formatRules(item.rules)}</td>
                  <td className="px-4 py-3 align-top">{item.is_active ? '启用' : item.status === 'parse_failed' ? '解析失败' : '停用'}</td>
                  <td className="px-4 py-3 align-top">
                    <div className="flex flex-col gap-1">
                      <button className="text-brand-700 underline" onClick={() => setContractActive(item, !item.is_active)}>{item.is_active ? '停用' : '启用'}</button>
                      <button className="text-blue-600 underline" onClick={() => openManualEditor(item)}>编辑</button>
                      <button className="text-red-600 underline" onClick={() => deleteContract(item)}>删除</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!contracts.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={8}>暂无合同</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {editingContract && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[720px] max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold">编辑合同信息</h3>
              <button className="text-slate-400 hover:text-slate-600" onClick={() => setEditingContract(null)}>✕</button>
            </div>
            {editingContract.status === 'parse_failed' && (
              <p className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-700">
                合同解析失败，请手动填写合同信息和扣款细则后启用。
              </p>
            )}
            <div className="space-y-4">
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">基本信息 <span className="text-xs text-slate-400">（所有字段均为必填）</span></h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 项目名称
                    {isAdmin ? (
                      <select className={inputClass('project_name')} value={editFields.project_name} onChange={(e) => { setEditFields({ ...editFields, project_name: e.target.value, business_type: '' }); clearFieldError('project_name') }}>
                        <option value="">请选择项目</option>
                        {allProjects.map((p) => <option key={p} value={p}>{p}</option>)}
                        {editFields.project_name && !allProjects.includes(editFields.project_name) && <option value={editFields.project_name}>{editFields.project_name}</option>}
                      </select>
                    ) : (
                      <input type="text" className={inputClass('project_name')} value={editFields.project_name} readOnly placeholder="从登录信息自动获取" />
                    )}
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 业态
                    <select className={inputClass('business_type')} value={editFields.business_type} onChange={(e) => { setEditFields({ ...editFields, business_type: e.target.value }); clearFieldError('business_type') }}>
                      <option value="">请选择业态</option>
                      {businessTypeOptions.map((bt) => <option key={bt} value={bt}>{bt}</option>)}
                      {editFields.business_type && !businessTypeOptions.includes(editFields.business_type) && <option value={editFields.business_type}>{editFields.business_type}</option>}
                    </select>
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 合同名称
                    <input type="text" className={inputClass('contract_name')} value={editFields.contract_name} onChange={(e) => { setEditFields({ ...editFields, contract_name: e.target.value }); clearFieldError('contract_name') }} placeholder="如 2026年保洁外包服务合同" />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 供应商
                    <input type="text" className={inputClass('supplier')} value={editFields.supplier} onChange={(e) => { setEditFields({ ...editFields, supplier: e.target.value }); clearFieldError('supplier') }} placeholder="如 XX保洁公司" />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 开始日期
                    <input type="date" className={inputClass('start_date')} value={editFields.start_date} onChange={(e) => { setEditFields({ ...editFields, start_date: e.target.value }); clearFieldError('start_date') }} />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 结束日期
                    <input type="date" className={inputClass('end_date')} value={editFields.end_date} onChange={(e) => { setEditFields({ ...editFields, end_date: e.target.value }); clearFieldError('end_date') }} />
                  </label>
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">迟到/早退分档扣款 <span className="text-xs text-slate-400">（所有字段均为必填）</span></h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    <span className="text-red-500">*</span> ≤30分钟扣款（元/次）
                    <input type="number" step="0.01" className={inputClass('late_early_tier_30')} value={manualRules.late_early_tier_30} onChange={(e) => { setManualRules({ ...manualRules, late_early_tier_30: e.target.value }); clearFieldError('late_early_tier_30') }} placeholder="如 20" />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> ≤60分钟扣款（元/次）
                    <input type="number" step="0.01" className={inputClass('late_early_tier_60')} value={manualRules.late_early_tier_60} onChange={(e) => { setManualRules({ ...manualRules, late_early_tier_60: e.target.value }); clearFieldError('late_early_tier_60') }} placeholder="如 50" />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 超过多少分钟按缺勤处理
                    <input type="number" className={inputClass('late_early_over')} value={manualRules.late_early_over} onChange={(e) => { setManualRules({ ...manualRules, late_early_over: e.target.value }); clearFieldError('late_early_over') }} placeholder="如 60" />
                  </label>
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">漏打卡扣款 <span className="text-xs text-slate-400">（金额和次数为必填）</span></h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 漏打卡扣款（元/人次）
                    <input type="number" step="0.01" className={inputClass('missing_clock_deduction')} value={manualRules.missing_clock_deduction} onChange={(e) => { setManualRules({ ...manualRules, missing_clock_deduction: e.target.value }); clearFieldError('missing_clock_deduction') }} placeholder="如 50" />
                  </label>
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 每月免扣次数
                    <input type="number" className={inputClass('missing_clock_free_times')} value={manualRules.missing_clock_free_times} onChange={(e) => { setManualRules({ ...manualRules, missing_clock_free_times: e.target.value }); clearFieldError('missing_clock_free_times') }} placeholder="如 3" />
                  </label>
                </div>
                <label className="mt-3 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={manualRules.missing_clock_proof} onChange={(e) => setManualRules({ ...manualRules, missing_clock_proof: e.target.checked })} />
                  免扣需提供出勤证明
                </label>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">缺勤/工时不足扣款 <span className="text-xs text-slate-400">（扣款系数必填，上限选填）</span></h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    <span className="text-red-500">*</span> 缺勤扣款系数
                    <input type="number" step="0.01" className={inputClass('deduction_coefficient')} value={manualRules.deduction_coefficient} onChange={(e) => { setManualRules({ ...manualRules, deduction_coefficient: e.target.value }); clearFieldError('deduction_coefficient') }} placeholder="如 1.2" />
                  </label>
                  <label className="text-sm">
                    单人单日扣款上限（元）
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.daily_cap} onChange={(e) => setManualRules({ ...manualRules, daily_cap: e.target.value })} placeholder="选填" />
                  </label>
                </div>
              </div>
            </div>
            {Object.values(validationErrors).some(Boolean) && (
              <p className="mt-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
                请填写所有标 <span className="text-red-500">*</span> 的必填项
              </p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button className="btn-secondary" onClick={() => setEditingContract(null)}>取消</button>
              <button className="btn-primary" disabled={savingRules} onClick={saveManualRules}>
                {savingRules ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
