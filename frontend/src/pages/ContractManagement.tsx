import { DragEvent, useEffect, useState } from 'react'
import { request } from '../services/api'

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
type RuleCenterItem = {
  id: number
  project_name: string
  project_code: string
  business_type: string
  service_type: string
  status: string
  version_label: string
  rules: Record<string, unknown>
  updated_at: string
  confirmed_at?: string
}
type MasterProject = { project_name: string; project_code: string }
type BusinessTypeItem = { project_name: string; project_code: string; business_type: string }
type Props = { userRole?: string; projectName?: string }

const emptyContractForm = {
  project_name: '',
  project_code: '',
  business_type: '',
  service_type: '保洁',
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

export function ContractManagement({ userRole = '集团管理员', projectName = '' }: Props) {
  const currentRole = userRole
  const currentProjectName = projectName
  const isProjectAccount = currentRole === '项目账号'
  const [contracts, setContracts] = useState<ProjectContract[]>([])
  const [ruleCenter, setRuleCenter] = useState<RuleCenterItem[]>([])
  const [projects, setProjects] = useState<MasterProject[]>([])
  const [businessTypes, setBusinessTypes] = useState<BusinessTypeItem[]>([])
  const [contractForm, setContractForm] = useState(emptyContractForm)
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [message, setMessage] = useState('')
  const [contractUploading, setContractUploading] = useState(false)
  const [draggingContract, setDraggingContract] = useState(false)
  const [reparsing, setReparsing] = useState(false)

  useEffect(() => {
    // 项目账号：同步设置 project_name，避免异步 API 返回前显示"未绑定项目"
    if (isProjectAccount && currentProjectName) {
      setContractForm((old) => ({ ...old, project_name: currentProjectName }))
    }
    loadProjects()
    loadContracts()
    loadRuleCenter()
  }, [currentRole, currentProjectName])

  useEffect(() => {
    if (contractForm.project_name) {
      loadBusinessTypes(contractForm.project_name)
    } else {
      setBusinessTypes([])
    }
  }, [contractForm.project_name])

  async function loadProjects() {
    try {
      const rows = await request<MasterProject[]>('/api/v1/projects')
      setProjects(rows)
      if (isProjectAccount && currentProjectName) {
        const selected = rows.find((item) => item.project_name === currentProjectName)
        setContractForm((old) => ({ ...old, project_name: currentProjectName, project_code: selected?.project_code || '' }))
      } else if (rows.length && !contractForm.project_name) {
        setContractForm((old) => ({ ...old, project_name: rows[0].project_name, project_code: rows[0].project_code || '' }))
      }
    } catch {
      setProjects([])
    }
  }
  async function loadBusinessTypes(projectName: string) {
    try {
      const rows = await request<BusinessTypeItem[]>(`/api/v1/projects/${encodeURIComponent(projectName)}/business-types`)
      setBusinessTypes(rows)
      if (rows.length && !contractForm.business_type) {
        setContractForm((old) => ({ ...old, business_type: rows[0].business_type }))
      }
    } catch {
      setBusinessTypes([])
    }
  }
  async function loadContracts() {
    try {
      const rows = await request<ProjectContract[]>('/api/v1/contracts', {
        headers: {
          'X-User-Role': isProjectAccount ? 'project_user' : 'group_admin',
          'X-Project-Name': isProjectAccount ? encodeURIComponent(currentProjectName) : '',
        },
      })
      setContracts(rows)
    } catch {
      setContracts([])
    }
  }
  async function loadRuleCenter() {
    try {
      const rows = await request<RuleCenterItem[]>('/api/v1/rule-center', {
        headers: {
          'X-User-Role': isProjectAccount ? 'project_user' : 'group_admin',
          'X-Project-Name': isProjectAccount ? encodeURIComponent(currentProjectName) : '',
        },
      })
      setRuleCenter(rows)
    } catch {
      setRuleCenter([])
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

  async function reparseAll() {
    setReparsing(true)
    try {
      const res = await request<{ total: number; results: Array<{ id: number; project_name: string; status: string; rules_keys?: string[] }> }>('/api/v1/contracts/reparse-all?include_active=true', { method: 'POST' })
      const successCount = res.results.filter((r) => r.status === 'active').length
      const failedCount = res.results.filter((r) => r.status === 'parse_failed').length
      setMessage(`批量重新解析完成：${successCount}个成功，${failedCount}个仍失败，共${res.total}个`)
      await loadContracts()
    } catch (e: any) {
      setMessage(`批量重新解析失败：${e.message || e}`)
    }
    setReparsing(false)
  }

  async function uploadContract() {
    if (!contractFile) {
      setMessage('请选择合同文件')
      return
    }
    if (!contractForm.project_name || !contractForm.business_type) {
      setMessage('请先选择项目和业态')
      return
    }
    setContractUploading(true)
    setMessage('合同上传中，正在自动识别项目和扣款条款。扫描版 PDF 需要 OCR，可能需要几十秒，请稍等。')
    try {
      const form = new FormData()
      Object.entries(contractForm).forEach(([key, value]) => form.append(key, value))
      form.append('is_active', 'true')
      form.append('file', contractFile)
      const result = await request<ProjectContract>('/api/v1/contracts', {
        method: 'POST',
        headers: {
          'X-User-Role': isProjectAccount ? 'project_user' : 'group_admin',
          'X-Project-Name': isProjectAccount ? encodeURIComponent(currentProjectName) : '',
        },
        body: form,
      })
      setMessage(result.is_active ? '合同已上传、解析并启用。后续审核将严格按合同扣款规则执行。' : '合同已上传，但未解析出迟到、早退、漏打卡扣款细则，未启用。请上传包含清晰扣款条款的合同。')
      setContractForm({
        ...emptyContractForm,
        project_name: isProjectAccount ? currentProjectName : contractForm.project_name,
        project_code: contractForm.project_code,
        business_type: '',
      })
      setContractFile(null)
      await loadContracts()
      await loadRuleCenter()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '合同上传失败')
    } finally {
      setContractUploading(false)
    }
  }
  async function confirmRule(item: RuleCenterItem) {
    try {
      await request(`/api/v1/rule-center/${item.id}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: '已确认' }),
      })
      setMessage('规则已确认，后续审核将读取Rule Center')
      loadRuleCenter()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '规则确认失败')
    }
  }
  async function setContractActive(item: ProjectContract, isActive: boolean) {
    try {
      await request(`/api/v1/contracts/${item.id}/active`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: isActive }),
      })
      setMessage(isActive ? '合同已启用' : '合同已停用')
      loadContracts()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '合同状态更新失败')
    }
  }

  // === 手动编辑扣款细则 ===
  const [editingContract, setEditingContract] = useState<ProjectContract | null>(null)
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

  function openManualEditor(item: ProjectContract) {
    setEditingContract(item)
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
    setSavingRules(true)
    try {
      const tiers: Array<{ max_minutes: number; amount: number }> = []
      if (manualRules.late_early_tier_30) {
        tiers.push({ max_minutes: 30, amount: parseFloat(manualRules.late_early_tier_30) })
      }
      if (manualRules.late_early_tier_60) {
        tiers.push({ max_minutes: 60, amount: parseFloat(manualRules.late_early_tier_60) })
      }
      const payload: Record<string, unknown> = { late_early_tiers: tiers }
      if (manualRules.late_early_over) payload['late_early_over_minutes_as_absence'] = parseFloat(manualRules.late_early_over)
      if (manualRules.missing_clock_deduction) payload['missing_clock_deduction'] = parseFloat(manualRules.missing_clock_deduction)
      if (manualRules.missing_clock_free_times) payload['missing_clock_free_times_per_month'] = parseFloat(manualRules.missing_clock_free_times)
      payload['missing_clock_free_requires_attendance_proof'] = manualRules.missing_clock_proof
      if (manualRules.deduction_coefficient) payload['contract_deduction_coefficient'] = parseFloat(manualRules.deduction_coefficient)
      if (manualRules.daily_cap) payload['single_person_daily_cap'] = parseFloat(manualRules.daily_cap)

      await request(`/api/v1/contracts/${editingContract.id}/manual-rules`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      setMessage('扣款细则已保存')
      setEditingContract(null)
      await loadContracts()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    }
    setSavingRules(false)
  }

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h2 className="text-lg font-semibold">项目合同库</h2>
        <p className="mt-2 text-sm text-slate-500">
          直接上传合同 PDF / Word，系统会自动识别项目和扣款条款。合同解析失败时，可点击"编辑细则"手动填写扣款规则后启用。
        </p>
        <div
          className={`mt-4 rounded-2xl border border-dashed p-4 transition ${draggingContract ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-slate-300 bg-slate-50'}`}
          onDragOver={handleContractDragOver}
          onDragLeave={() => setDraggingContract(false)}
          onDrop={handleContractDrop}
        >
          <div className="mb-4 grid grid-cols-3 gap-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">当前项目</span>
              {isProjectAccount ? (
                <div className="mt-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800">
                  {contractForm.project_name || '未绑定项目，请先在顶部选择项目账号对应项目'}
                </div>
              ) : (
                <select
                  className="input mt-2 w-full"
                  value={contractForm.project_name}
                  onChange={(event) => {
                    const selected = projects.find((item) => item.project_name === event.target.value)
                    setContractForm((old) => ({
                      ...old,
                      project_name: event.target.value,
                      project_code: selected?.project_code || '',
                      business_type: '',
                    }))
                  }}
                >
                  <option value="">请选择项目</option>
                  {projects.map((item) => <option key={item.project_name} value={item.project_name}>{item.project_name}</option>)}
                </select>
              )}
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">选择业态</span>
              <select className="input mt-2 w-full" value={contractForm.business_type} onChange={(event) => setContractForm((old) => ({ ...old, business_type: event.target.value }))}>
                <option value="">请选择业态</option>
                <option value="住宅">住宅</option>
                <option value="商业">商业</option>
                <option value="外场">物业</option>
                <option value="酒店">酒店</option>
                <option value="街区">街区</option>
                <option value="写字楼">写字楼</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">合同类型</span>
              <select className="input mt-2 w-full" value={contractForm.service_type} onChange={(event) => setContractForm((old) => ({ ...old, service_type: event.target.value }))}>
                <option value="保洁">保洁</option>
                <option value="保安">保安</option>
              </select>
            </label>
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="flex-1 cursor-pointer rounded-xl bg-white px-4 py-4 text-sm text-slate-600">
              <span className="font-medium text-slate-800">{contractFile ? contractFile.name : '拖入合同文件，或点击选择 PDF / Word 文件'}</span>
              <span className="mt-1 block text-xs text-slate-400">支持 .pdf、.doc、.docx；拖拽到当前区域即可选中文件。</span>
              <input className="sr-only" type="file" accept=".pdf,.doc,.docx" onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) selectContractFile(file)
              }} />
            </label>
            <button className="btn-primary" disabled={contractUploading} onClick={uploadContract}>
              {contractUploading ? '上传解析中...' : '上传并启用合同'}
            </button>
          </div>
        </div>
        {contracts.length > 0 && (
          <div className="mt-3 flex items-center gap-3 rounded-xl bg-blue-50 px-4 py-3">
            <span className="text-sm text-blue-700">用最新OCR纠错逻辑重新解析所有合同规则（包括已启用的）</span>
            <button className="btn-secondary" disabled={reparsing} onClick={reparseAll}>
              {reparsing ? '重新解析中...' : '批量重新解析所有合同'}
            </button>
          </div>
        )}
        {message && <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600 break-words">{message}</div>}
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
                      <button className="text-blue-600 underline" onClick={() => openManualEditor(item)}>编辑细则</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!contracts.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={8}>暂无合同</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">Rule Center 规则中心</h2>
            <p className="mt-2 text-sm text-slate-500">合同上传解析后写入这里。项目可修改、确认规则；后续审核只读取Rule Center，不重复解析合同。</p>
          </div>
          <button className="btn-secondary" onClick={loadRuleCenter}>刷新规则</button>
        </div>
        <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-[1080px] table-fixed text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-48 px-4 py-3 text-left">项目</th>
                <th className="w-20 px-4 py-3 text-left">业态</th>
                <th className="w-20 px-4 py-3 text-left">类型</th>
                <th className="w-20 px-4 py-3 text-left">版本</th>
                <th className="w-24 px-4 py-3 text-left">状态</th>
                <th className="w-[420px] px-4 py-3 text-left">规则摘要/编辑</th>
                <th className="w-40 px-4 py-3 text-left">更新时间</th>
                <th className="w-32 px-4 py-3 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              {ruleCenter.map((item) => (
                <tr key={item.id} className="border-t border-slate-100">
                  <td className="px-4 py-3 align-top break-words">{item.project_name}</td>
                  <td className="px-4 py-3 align-top">{item.business_type || '-'}</td>
                  <td className="px-4 py-3 align-top">{item.service_type}</td>
                  <td className="px-4 py-3 align-top">{item.version_label}</td>
                  <td className="px-4 py-3 align-top">
                    <span className={`rounded-full px-3 py-1 text-xs font-medium ${item.status === '已确认' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{item.status}</span>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="text-xs leading-5 text-slate-500 break-words">{formatRules(item.rules)}</div>
                  </td>
                  <td className="px-4 py-3 align-top text-slate-500">{item.updated_at}</td>
                  <td className="px-4 py-3 align-top">
                    <button className="text-emerald-700 underline" onClick={() => confirmRule(item)}>确认</button>
                  </td>
                </tr>
              ))}
              {!ruleCenter.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={8}>暂无规则，请先上传合同</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* 手动编辑扣款细则弹窗 */}
      {editingContract && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[600px] max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold">手动编辑扣款细则</h3>
              <button className="text-slate-400 hover:text-slate-600" onClick={() => setEditingContract(null)}>✕</button>
            </div>
            <p className="mb-4 text-sm text-slate-500">
              项目：{editingContract.project_name} | 业态：{editingContract.business_type || '-'}
              {editingContract.status === 'parse_failed' && <span className="ml-2 text-amber-600">（合同解析失败，可手动补充细则后启用）</span>}
            </p>
            <div className="space-y-4">
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">迟到/早退分档扣款</h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    ≤30分钟扣款（元/次）
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.late_early_tier_30} onChange={(e) => setManualRules({ ...manualRules, late_early_tier_30: e.target.value })} placeholder="如 20" />
                  </label>
                  <label className="text-sm">
                    ≤60分钟扣款（元/次）
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.late_early_tier_60} onChange={(e) => setManualRules({ ...manualRules, late_early_tier_60: e.target.value })} placeholder="如 50" />
                  </label>
                  <label className="text-sm">
                    超过多少分钟按缺勤处理
                    <input type="number" className="input mt-1 w-full" value={manualRules.late_early_over} onChange={(e) => setManualRules({ ...manualRules, late_early_over: e.target.value })} placeholder="如 60" />
                  </label>
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">漏打卡扣款</h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    漏打卡扣款（元/人次）
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.missing_clock_deduction} onChange={(e) => setManualRules({ ...manualRules, missing_clock_deduction: e.target.value })} placeholder="如 50" />
                  </label>
                  <label className="text-sm">
                    每月免扣次数
                    <input type="number" className="input mt-1 w-full" value={manualRules.missing_clock_free_times} onChange={(e) => setManualRules({ ...manualRules, missing_clock_free_times: e.target.value })} placeholder="如 3" />
                  </label>
                </div>
                <label className="mt-3 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={manualRules.missing_clock_proof} onChange={(e) => setManualRules({ ...manualRules, missing_clock_proof: e.target.checked })} />
                  免扣需提供出勤证明
                </label>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <h4 className="mb-3 text-sm font-medium text-slate-700">缺勤/工时不足扣款</h4>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm">
                    缺勤扣款系数
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.deduction_coefficient} onChange={(e) => setManualRules({ ...manualRules, deduction_coefficient: e.target.value })} placeholder="如 1.2" />
                  </label>
                  <label className="text-sm">
                    单人单日扣款上限（元）
                    <input type="number" step="0.01" className="input mt-1 w-full" value={manualRules.daily_cap} onChange={(e) => setManualRules({ ...manualRules, daily_cap: e.target.value })} placeholder="选填" />
                  </label>
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button className="btn-secondary" onClick={() => setEditingContract(null)}>取消</button>
              <button className="btn-primary" disabled={savingRules} onClick={saveManualRules}>
                {savingRules ? '保存中...' : '保存细则'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
