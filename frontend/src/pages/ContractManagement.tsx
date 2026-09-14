import { DragEvent, useEffect, useSyncExternalStore, useState } from 'react'
import { request } from '../services/api'
import {
  fetchBusinessTypes,
  fetchContracts,
  invalidateConfig,
  subscribeConfig,
  CONFIG_KEYS,
  type BusinessTypeConfig,
} from '../services/configCache'
import {
  readContractDraft,
  writeContractDraft,
  clearContractDraft,
  type ContractParseDraft,
} from '../services/contractDraftCache'
import { useAuth } from '../hooks/useAuth'

type ContractParseFields = {
  original_name?: string
  temp_file?: string
  project_name?: string
  business_type?: string
  supplier?: string
  contract_no?: string
  contract_name?: string
  service_type?: string
  version?: string
  start_date?: string
  end_date?: string
  rules?: Record<string, unknown>
  extract_status?: string
}

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

  // 草稿状态：draftMeta 非空 = 当前弹窗编辑的是「未入库草稿」；
  // draftBanner 非空 = sessionStorage 里还有一份没保存的解析草稿
  const [draftMeta, setDraftMeta] = useState<{ tempFile: string; fileName: string } | null>(null)
  const [draftBanner, setDraftBanner] = useState<ContractParseDraft | null>(null)

  useEffect(() => {
    // 页面挂载时恢复上次未保存的解析草稿（取消过编辑的也不会丢）
    const draft = readContractDraft()
    if (draft) setDraftBanner(draft)
  }, [])

  useEffect(() => {
    loadContracts()
    // 订阅合同变更：本页写操作或其他标签页改动后，自动同步刷新列表
    return subscribeConfig(CONFIG_KEYS.CONTRACTS, () => loadContracts())
  }, [currentRole, currentProjectName])

  useEffect(() => {
    const loadBusinessTypes = () => {
      fetchBusinessTypes()
        .then((data: BusinessTypeConfig) => {
          setBusinessTypeMapping(data.mapping || {})
          setAllProjects(data.projects || [])
        })
        .catch(() => {})
    }
    loadBusinessTypes()
    return subscribeConfig(CONFIG_KEYS.BUSINESS_TYPES, loadBusinessTypes)
  }, [])

  // force=true 表示刚做过写操作，跳过缓存强制拉最新
  async function loadContracts(force = false) {
    try {
      // 后端根据用户角色自动筛选项目，前端无需传递 project_name
      const rows = await fetchContracts<ProjectContract[]>(force)
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
      message: '合同解析中，正在自动识别合同信息和扣款条款，可能需要几十秒，请稍等。',
      result: null,
      error: null,
    })
    setContractFile(null)
    try {
      // 只解析不入库：结果先进 sessionStorage 草稿，确认细则后才入库
      const parsed = await request<ContractParseFields>('/api/v2/contracts/parse', {
        method: 'POST',
        body: (() => { const f = new FormData(); f.append('file', file); return f })(),
      })
      const fileName = parsed.original_name || file.name
      const tempFile = parsed.temp_file || ''
      if (!tempFile) throw new Error('解析结果缺少临时文件路径，请重新上传')
      const draft: ContractParseDraft = { parsed: parsed as Record<string, unknown>, tempFile, fileName, createdAt: Date.now() }
      writeContractDraft(draft)
      setDraftBanner(draft)
      _setContractUpload({ uploading: false, fileName: '', message: '', result: null, error: null })
      openDraftEditor(parsed, tempFile, fileName)
      setMessage('解析完成，已生成「未入库草稿」：请核对细则后保存入库；现在点取消也不会丢失本次解析。')
    } catch (error) {
      _setContractUpload({
        uploading: false,
        fileName: '',
        result: null,
        error: error instanceof Error ? error.message : '合同解析失败',
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
      // 写操作后先让缓存失效，再强制拉最新，避免读到旧列表
      invalidateConfig(CONFIG_KEYS.CONTRACTS)
      loadContracts(true)
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
      invalidateConfig(CONFIG_KEYS.CONTRACTS)
      loadContracts(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '删除失败')
      invalidateConfig(CONFIG_KEYS.CONTRACTS)
      loadContracts(true)
    }
  }

  const [editingContract, setEditingContract] = useState<ProjectContract | null>(null)
  const [editFields, setEditFields] = useState({
    project_name: '',
    business_type: '',
    service_type: '',
    contract_name: '',
    supplier: '',
    start_date: '',
    end_date: '',
  })
  const [manualRules, setManualRules] = useState({
    late_early_over: '60',
    missing_clock_deduction: '50',
    missing_clock_free_times: '3',
    missing_clock_proof: true,
    deduction_coefficient: '1.2',
    daily_cap: '',
  })
  /** 迟到/早退分档：动态数组，每项 { max_minutes, amount } */
  const [lateEarlyTiers, setLateEarlyTiers] = useState<Array<{ max_minutes: number; amount: string }>>([
    { max_minutes: 30, amount: '' },
    { max_minutes: 60, amount: '' },
  ])
  /** 正在编辑时间的分档下标，-1 表示无 */
  const [editingTierIdx, setEditingTierIdx] = useState(-1)
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
    // 校验分档：每项金额必填且 > 0
    lateEarlyTiers.forEach((tier, idx) => {
      if (!tier.amount || parseFloat(tier.amount) <= 0) {
        errors[`tier_amount_${idx}`] = true
      }
    })
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
    // 已入库合同的编辑入口：清除草稿标记，弹窗按「已入库」展示
    setDraftMeta(null)
    setEditingContract(item)
    setValidationErrors({})
    setEditFields({
      project_name: item.project_name || (isAdmin ? '' : currentProjectName) || '',
      business_type: item.business_type || '',
      service_type: item.service_type || '',
      contract_name: item.contract_name || '',
      supplier: item.supplier || '',
      start_date: item.start_date || '',
      end_date: item.end_date || '',
    })
    const rules = item.rules as Record<string, unknown>
    const tiers = (rules['late_early_tiers'] as Array<{ max_minutes: number; amount: number }>) || []
    // 动态加载分档：有数据用数据，无数据默认两档 30/60
    if (tiers.length > 0) {
      setLateEarlyTiers(tiers.map((t) => ({ max_minutes: t.max_minutes, amount: String(t.amount) })))
    } else {
      setLateEarlyTiers([
        { max_minutes: 30, amount: '' },
        { max_minutes: 60, amount: '' },
      ])
    }
    setEditingTierIdx(-1)
    setManualRules({
      late_early_over: String(rules['late_early_over_minutes_as_absence'] || '60'),
      missing_clock_deduction: String(rules['missing_clock_deduction'] || ''),
      missing_clock_free_times: String(rules['missing_clock_free_times_per_month'] || ''),
      missing_clock_proof: rules['missing_clock_free_requires_attendance_proof'] !== false,
      deduction_coefficient: String(rules['contract_deduction_coefficient'] || ''),
      daily_cap: String(rules['single_person_daily_cap'] || ''),
    })
  }

  /** 打开「未入库草稿」编辑卡片：展示的是缓存里本次解析的数据，保存才入库 */
  function openDraftEditor(parsed: ContractParseFields, tempFile: string, fileName: string) {
    const pseudo: ProjectContract = {
      id: 0,
      project_name: parsed.project_name || '',
      project_code: '',
      business_type: parsed.business_type || '',
      supplier: parsed.supplier || '',
      contract_no: parsed.contract_no || '',
      contract_name: parsed.contract_name || '',
      service_type: parsed.service_type || '',
      version: parsed.version || '',
      start_date: parsed.start_date || '',
      end_date: parsed.end_date || '',
      original_name: fileName,
      file_format: '',
      download_url: '',
      is_active: 0,
      status: parsed.extract_status === 'failed' ? 'parse_failed' : 'draft',
      rules: parsed.rules || {},
      updated_at: '',
    }
    openManualEditor(pseudo)
    setDraftMeta({ tempFile, fileName })
  }

  /** 关闭弹窗：草稿仍在缓存里，顶部横幅可继续编辑；已入库合同的数据不受影响 */
  function closeEditor() {
    setEditingContract(null)
    setValidationErrors({})
  }

  async function saveManualRules() {
    if (!editingContract) return
    if (!validateRequiredFields()) {
      setMessage('请填写所有必填项')
      return
    }
    setSavingRules(true)
    try {
      // 从动态分档数组构建 tiers payload
      const tiers: Array<{ max_minutes: number; amount: number }> = lateEarlyTiers
        .filter((t) => t.amount && parseFloat(t.amount) > 0)
        .map((t) => ({ max_minutes: t.max_minutes, amount: parseFloat(t.amount) }))
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
        service_type: editFields.service_type || undefined,
        contract_name: editFields.contract_name || undefined,
        supplier: editFields.supplier || undefined,
        start_date: editFields.start_date || undefined,
        end_date: editFields.end_date || undefined,
        rules: rulesPayload,
      }

      if (draftMeta) {
        // 草稿分支：凭 temp_file 走创建接口入库，成功后清掉缓存草稿。
        // 入库去重由后端做：同名同业态覆盖，同名不同业态新建第二条。
        await request('/api/v2/contracts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            temp_file: draftMeta.tempFile,
            original_name: draftMeta.fileName,
            ...payload,
          }),
        })
        clearContractDraft()
        setDraftBanner(null)
        setDraftMeta(null)
        setEditingContract(null)
        setMessage('合同已保存入库')
      } else {
        // 已入库合同分支：直接更新原记录，取消/失败都不影响库中现有细则
        await request(`/api/v2/contracts/${editingContract.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setMessage('合同信息已保存')
        setEditingContract(null)
      }
      invalidateConfig(CONFIG_KEYS.CONTRACTS)
      await loadContracts(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    }
    setSavingRules(false)
  }

  useEffect(() => {
    if (uploadState.error) {
      const errMsg = uploadState.error
      _setContractUpload({ error: null, message: '' })
      setMessage(errMsg)
    }
  }, [uploadState.error])

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
        {draftBanner && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-700">
            <span className="break-words">
              存在未保存的解析草稿：<span className="font-medium">{draftBanner.fileName}</span>
              （{new Date(draftBanner.createdAt).toLocaleString()} 解析），尚未入库，取消编辑也不会丢失。
            </span>
            <div className="flex shrink-0 gap-3">
              <button className="font-medium text-amber-800 underline" onClick={() => openDraftEditor(draftBanner.parsed as ContractParseFields, draftBanner.tempFile, draftBanner.fileName)}>继续编辑</button>
              <button
                className="font-medium text-red-600 underline"
                onClick={() => {
                  clearContractDraft()
                  setDraftBanner(null)
                  setMessage('已丢弃未入库的解析草稿')
                }}
              >丢弃</button>
            </div>
          </div>
        )}
        <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full min-w-[980px] table-fixed text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-40 px-4 py-3 text-left">项目</th>
                <th className="w-20 px-4 py-3 text-left">业态</th>
                <th className="w-20 px-4 py-3 text-left">服务类型</th>
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
                  <td className="px-4 py-3 align-top">{item.service_type || '-'}</td>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          {/* 外层只负责圆角裁剪，内层负责滚动，保证四角始终是圆角卡片 */}
          <div className="flex max-h-[90vh] w-[720px] flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
            <div className="overflow-y-auto p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-lg font-semibold">
                编辑合同信息
                {draftMeta ? (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">缓存草稿 · 未入库</span>
                ) : (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">已入库</span>
                )}
              </h3>
              <button className="text-slate-400 hover:text-slate-600" onClick={closeEditor}>✕</button>
            </div>
            {draftMeta ? (
              <p className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-700">
                当前展示的是本次解析的缓存数据，尚未入库；点「取消」不会丢失，可随时从页面顶部「未保存草稿」继续编辑或丢弃。保存后才会写入合同库。
              </p>
            ) : editingContract?.status === 'parse_failed' && (
              <p className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-700">
                合同解析失败，请手动填写合同信息和扣款细则后启用。修改会直接保存到已入库的这条合同。
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
                    <span className="text-red-500">*</span> 服务类型
                    <select className={inputClass('service_type')} value={editFields.service_type} onChange={(e) => { setEditFields({ ...editFields, service_type: e.target.value }); clearFieldError('service_type') }}>
                      <option value="">请选择服务类型</option>
                      <option value="保安">保安</option>
                      <option value="保洁">保洁</option>
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
                <div className="mb-3 flex items-center justify-between">
                  <h4 className="text-sm font-medium text-slate-700">迟到/早退分档扣款 <span className="text-xs text-slate-400">（所有字段均为必填）</span></h4>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-md bg-brand-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-600"
                    onClick={() => setLateEarlyTiers([...lateEarlyTiers, { max_minutes: 90, amount: '' }])}
                  >
                    + 添加分档
                  </button>
                </div>
                {/* 超过多少分钟按缺勤处理 — 独立一行 */}
                <label className="mb-3 block text-sm">
                  <span className="text-red-500">*</span> 超过多少分钟按缺勤处理
                  <input type="number" className={inputClass('late_early_over')} value={manualRules.late_early_over} onChange={(e) => { setManualRules({ ...manualRules, late_early_over: e.target.value }); clearFieldError('late_early_over') }} placeholder="如 60" />
                </label>
                {/* 分档列表 */}
                <div className="space-y-2">
                  {lateEarlyTiers.map((tier, idx) => (
                    <div key={idx} className="flex items-center gap-2 rounded-lg bg-white px-3 py-2">
                      {/* 分档时间（展示 / 编辑切换） */}
                      {editingTierIdx === idx ? (
                        <div className="flex items-center gap-1 text-sm">
                          <span className="text-slate-500">≤</span>
                          <input
                            type="number"
                            step="1"
                            min="1"
                            className="input w-20 px-2 py-1 text-sm"
                            value={tier.max_minutes}
                            onChange={(e) => {
                              const next = [...lateEarlyTiers]
                              next[idx] = { ...tier, max_minutes: parseInt(e.target.value) || 0 }
                              setLateEarlyTiers(next)
                            }}
                            onKeyDown={(e) => { if (e.key === 'Enter') setEditingTierIdx(-1) }}
                          />
                          <span className="text-slate-500">分钟</span>
                          <button type="button" className="ml-1 text-xs text-brand-600 hover:underline" onClick={() => setEditingTierIdx(-1)}>完成</button>
                        </div>
                      ) : (
                        <span className="text-sm text-slate-600">
                          ≤{tier.max_minutes}分钟扣款
                        </span>
                      )}
                      {/* 金额输入 */}
                      <input
                        type="number"
                        step="0.01"
                        className={`input w-24 px-2 py-1 text-sm${validationErrors[`tier_amount_${idx}`] ? ' border-red-500 ring-1 ring-red-200' : ''}`}
                        value={tier.amount}
                        onChange={(e) => {
                          const next = [...lateEarlyTiers]
                          next[idx] = { ...tier, amount: e.target.value }
                          setLateEarlyTiers(next)
                          clearFieldError(`tier_amount_${idx}`)
                        }}
                        placeholder="如 20"
                      />
                      <span className="text-sm text-slate-500">元/次</span>
                      {/* 修改时间按钮 */}
                      <button
                        type="button"
                        className="inline-flex items-center rounded-md bg-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-300"
                        onClick={() => setEditingTierIdx(editingTierIdx === idx ? -1 : idx)}
                      >
                        修改时间
                      </button>
                      {/* 删除按钮 */}
                      {lateEarlyTiers.length > 1 && (
                        <button
                          type="button"
                          className="ml-auto inline-flex h-6 w-6 items-center justify-center rounded-full text-slate-400 hover:bg-red-100 hover:text-red-600"
                          title="删除此分档"
                          onClick={() => {
                            const next = lateEarlyTiers.filter((_, i) => i !== idx)
                            setLateEarlyTiers(next)
                            setEditingTierIdx(-1)
                          }}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {lateEarlyTiers.length === 0 && (
                  <p className="mt-2 text-xs text-slate-400">无分档，点击右上角"添加分档"新增</p>
                )}
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
                <h4 className="mb-3 text-sm font-medium text-slate-700">缺勤/工时不足扣款 <span className="text-xs text-slate-400">（扣款系数必填）</span></h4>
                <label className="block text-sm">
                  <span className="text-red-500">*</span> 缺勤扣款系数
                  <input type="number" step="0.01" className={inputClass('deduction_coefficient')} value={manualRules.deduction_coefficient} onChange={(e) => { setManualRules({ ...manualRules, deduction_coefficient: e.target.value }); clearFieldError('deduction_coefficient') }} placeholder="如 1.2" />
                </label>
              </div>
            </div>
            {Object.values(validationErrors).some(Boolean) && (
              <p className="mt-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
                请填写所有标 <span className="text-red-500">*</span> 的必填项
              </p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button className="btn-secondary" onClick={closeEditor}>取消</button>
              <button className="btn-primary" disabled={savingRules} onClick={saveManualRules}>
                {savingRules ? '保存中...' : '保存'}
              </button>
            </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
