import { useEffect, useState } from 'react'
import { request } from '../services/api'
import type { AuditContext } from '../types'
import { useAuditContext } from '../hooks/useAuditContext'
import { useAuth } from '../hooks/useAuth'

interface DeductionDetail {
  employee_name: string
  position: string
  missing_clock_count: number
  missing_clock_free_limit: number
  missing_clock_free_remaining: number
  missing_clock_deductible: number
  missing_clock_amount: number
  missing_clock_dates: string[]
  missing_clock_records?: Array<{ date: string; shift_start: string; shift_end: string; clock_times: string[] }>
  missing_clock_extra: number
  late_details: any[]
  late_total: number
  early_leave_details: any[]
  early_leave_total: number
  mid_clock_issues: any[]
  absence_dates: string[]
  absence_records?: Array<{ date: string; shift_start: string; shift_end: string; clock_times: string[] }>
  absence_amount: number
  absence_daily_rate: number
  absence_multiplier?: number
  total_deduction: number
  confirmations?: Record<string, { confirmed: boolean; note: string; confirmed_by: string; confirmed_at: string; free_deduction?: boolean }>
}

interface ExceptionRecord {
  key: string
  employee_name: string
  work_date: string
  exception_type: string
  exception_label: string
  amount: number
  detail: string
  shift_time: string
  clock_times: string
  confirmed?: boolean
  note?: string
  free_deduction?: boolean
}

interface S04AuditData {
  deduction_details: DeductionDetail[]
  summary: {
    total_missing_clock_amount: number
    total_late_amount: number
    total_early_leave_amount: number
    total_absence_amount: number
    total_deduction: number
    affected_employees: number
  }
}

function buildExceptionRecords(details: DeductionDetail[]): ExceptionRecord[] {
  const records: ExceptionRecord[] = []
  for (const d of details) {
    const confs = d.confirmations || {}
    // 建 (date -> record) 索引，便于按日期查班次与打卡时间
    const missingByDate = new Map<string, { shift_start: string; shift_end: string; clock_times: string[] }>()
    for (const r of d.missing_clock_records || []) {
      missingByDate.set(r.date, r)
    }
    const absenceByDate = new Map<string, { shift_start: string; shift_end: string; clock_times: string[] }>()
    for (const r of d.absence_records || []) {
      absenceByDate.set(r.date, r)
    }
    const midByKey = new Map<string, { shift_start: string; shift_end: string; clock_times: string[] }>()
    for (const m of d.mid_clock_issues || []) {
      if (m.date) {
        midByKey.set(`${m.date}|${m.window || ''}`, m)
      }
    }

    for (const dateStr of d.missing_clock_dates || []) {
      const conf = confs[dateStr]
      const rec = missingByDate.get(dateStr)
      const shift = rec ? `${rec.shift_start || ''}-${rec.shift_end || ''}` : ''
      const clocks = rec ? (rec.clock_times || []).join(' / ') : ''
      records.push({
        key: `missing|${d.employee_name}|${dateStr}`,
        employee_name: d.employee_name,
        work_date: dateStr,
        exception_type: 'missing_clock',
        exception_label: '漏打卡',
        amount: 50,
        detail: `漏打卡，扣款50元`,
        shift_time: shift,
        clock_times: clocks,
        confirmed: conf?.confirmed ?? false,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const issue of d.mid_clock_issues || []) {
      const dateStr = issue.date || ''
      const confKey = `mid|${d.employee_name}|${dateStr}|${issue.window || ''}`
      const conf = confs[confKey]
      const missing = issue.missing || 0
      const meta = midByKey.get(`${dateStr}|${issue.window || ''}`)
      const shift = meta ? `${meta.shift_start || ''}-${meta.shift_end || ''}` : ''
      const clocks = meta ? (meta.clock_times || []).join(' / ') : ''
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        exception_type: 'mid_clock',
        exception_label: '中间卡缺失',
        amount: missing * 50,
        detail: `${issue.window || ''} 缺${missing}次，扣款${missing * 50}元`,
        shift_time: shift,
        clock_times: clocks,
        confirmed: conf?.confirmed ?? false,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const late of d.late_details || []) {
      const dateStr = late.date || ''
      const confKey = `late|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const tierLabel = late.tier === 'S04-2' ? '迟到≤30min' : late.tier === 'S04-3' ? '迟到30-60min' : '迟到>60min(转缺勤)'
      const shift = late.shift_start ? `${late.shift_start}-${late.shift_end || ''}` : ''
      const clocks = late.clock_in ? String(late.clock_in) : ''
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        exception_type: 'late',
        exception_label: '迟到',
        amount: late.amount || 0,
        detail: `${tierLabel}，迟到${late.minutes || 0}分钟，扣款${late.amount || 0}元`,
        shift_time: shift,
        clock_times: clocks,
        confirmed: conf?.confirmed ?? false,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const early of d.early_leave_details || []) {
      const dateStr = early.date || ''
      const confKey = `early|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const tierLabel = early.tier === 'S04-2' ? '早退≤30min' : early.tier === 'S04-3' ? '早退30-60min' : '早退>60min(转漏打卡)'
      const shift = early.shift_start ? `${early.shift_start}-${early.shift_end || ''}` : ''
      const clocks = early.clock_out ? String(early.clock_out) : ''
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        exception_type: 'early_leave',
        exception_label: '早退',
        amount: early.amount || 0,
        detail: `${tierLabel}，早退${early.minutes || 0}分钟，扣款${early.amount || 0}元`,
        shift_time: shift,
        clock_times: clocks,
        confirmed: conf?.confirmed ?? false,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const dateStr of d.absence_dates || []) {
      const confKey = `absence|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const dailyRate = d.absence_daily_rate || 0
      const multiplier = Number(d.absence_multiplier || 2.5)
      const amount = round2(dailyRate * multiplier)
      const rec = absenceByDate.get(dateStr)
      const shift = rec ? `${rec.shift_start || ''}-${rec.shift_end || ''}` : ''
      const clocks = rec ? (rec.clock_times || []).join(' / ') : ''
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        exception_type: 'absence',
        exception_label: '脱岗/缺勤',
        amount,
        detail: `脱岗/缺勤，日服务费${dailyRate}×${multiplier}=${amount}元`,
        shift_time: shift,
        clock_times: clocks,
        confirmed: conf?.confirmed ?? false,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
  }
  return records
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function exceptionBadgeClass(type: string): string {
  if (type === 'absence') return 'bg-red-100 text-red-700'
  if (type === 'missing_clock') return 'bg-amber-100 text-amber-700'
  if (type === 'late' || type === 'early_leave') return 'bg-orange-100 text-orange-700'
  if (type === 'mid_clock') return 'bg-purple-100 text-purple-700'
  return 'bg-slate-100 text-slate-700'
}

export function ConfirmationPage() {
  const { auditContext } = useAuditContext()
  const { user } = useAuth()
  const [s04Data, setS04Data] = useState<S04AuditData | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedEmployee, setSelectedEmployee] = useState('')
  const [confirmMap, setConfirmMap] = useState<Record<string, boolean>>({})
  const [freeDeductionMap, setFreeDeductionMap] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [message, setMessage] = useState('')
  const [finalizeResult, setFinalizeResult] = useState<{
    confirmed_count: number
    total_deduction: number
    first_exception_rate: number
    confirmed_exception_rate: number
    message: string
  } | null>(null)
  const [allRecords, setAllRecords] = useState<ExceptionRecord[]>([])
  const [isLocked, setIsLocked] = useState(false)

  useEffect(() => {
    if (auditContext) loadData()
  }, [auditContext])

  useEffect(() => {
    if (s04Data && s04Data.deduction_details.length && !selectedEmployee) {
      setSelectedEmployee(s04Data.deduction_details[0].employee_name)
    }
  }, [s04Data])

  async function loadData() {
    if (!auditContext) return
    setLoading(true)
    setMessage('')
    try {
      const params = new URLSearchParams({
        project_name: auditContext.project_name,
        business_type: auditContext.business_type,
        audit_month: auditContext.audit_month,
      })
      const detail = await request<any>(`/api/v2/audit-results/detail?${params}`)
      const resultsJson = typeof detail?.results_json === 'string' ? JSON.parse(detail.results_json) : detail?.results_json
      const raw = resultsJson?.s04_attendance_audit || {}
      const s04Audit: S04AuditData = {
        deduction_details: raw.deduction_details || [],
        summary: raw.summary || {},
      }
      setS04Data(s04Audit)
      setIsLocked(!!detail?.locked)
      const records = buildExceptionRecords(s04Audit.deduction_details || [])
      setAllRecords(records)
      const cMap: Record<string, boolean> = {}
      const fMap: Record<string, boolean> = {}
      for (const r of records) {
        cMap[r.key] = r.confirmed ?? false
        fMap[r.key] = r.free_deduction ?? false
      }
      setConfirmMap(cMap)
      setFreeDeductionMap(fMap)
      setFinalizeResult(null)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '加载失败')
    }
    setLoading(false)
  }

  function toggleConfirm(key: string) {
    if (isLocked) return
    setConfirmMap({ ...confirmMap, [key]: !confirmMap[key] })
  }

  function getEmployeeFreeUsed(emp: string): number {
    return allRecords.filter(r => r.employee_name === emp && freeDeductionMap[r.key]).length
  }

  function handleFreeDeduction(key: string) {
    if (isLocked) return
    const record = allRecords.find(r => r.key === key)
    if (!record) return
    if (freeDeductionMap[key]) {
      if (confirm('确定取消该记录的免扣状态吗？取消后将重新计入扣款。')) {
        setFreeDeductionMap({ ...freeDeductionMap, [key]: false })
      }
      return
    }
    if (!confirmMap[key]) {
      setMessage('请先勾选确认该记录，再使用免打卡')
      return
    }
    const freeLimit = s04Data?.deduction_details.find(d => d.employee_name === record.employee_name)?.missing_clock_free_limit ?? 3
    const used = getEmployeeFreeUsed(record.employee_name)
    if (used >= freeLimit) {
      setMessage(`${record.employee_name} 的${freeLimit}次免打卡机会已用完`)
      return
    }
    if (confirm(`确定将"${record.exception_label}"记录设为免打卡吗？\n${record.employee_name} 剩余免打卡机会：${freeLimit - used - 1}次`)) {
      setFreeDeductionMap({ ...freeDeductionMap, [key]: true })
    }
  }

  function selectAllForEmployee(emp: string) {
    if (isLocked) return
    const empRecords = allRecords.filter(r => r.employee_name === emp)
    const allChecked = empRecords.every(r => confirmMap[r.key])
    const updates: Record<string, boolean> = {}
    for (const r of empRecords) {
      updates[r.key] = !allChecked
    }
    setConfirmMap({ ...confirmMap, ...updates })
  }

  async function saveConfirm() {
    if (!auditContext || !s04Data || isLocked) return
    setSaving(true)
    setMessage('')
    const records: Array<{ employee_name: string; work_date: string; exception_type: string; confirmed: boolean; confirm_note: string; free_deduction: boolean }> = []
    for (const r of allRecords) {
      records.push({
        employee_name: r.employee_name,
        work_date: r.work_date,
        exception_type: r.exception_type,
        confirmed: confirmMap[r.key] ?? false,
        confirm_note: '',
        free_deduction: freeDeductionMap[r.key] ?? false,
      })
    }
    try {
      await request(`/api/v2/audit-results/confirm-exceptions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: auditContext.project_name,
          business_type: auditContext.business_type,
          audit_month: auditContext.audit_month,
          confirmed_records: records,
          confirmed_by: user?.username || '审核员',
        }),
      })
      setMessage('确认已提交')
      await loadData()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '提交失败')
    }
    setSaving(false)
  }

  async function generateReport() {
    if (!auditContext || isLocked) return
    if (!confirm('生成扣款报告将按确认结果重新计算扣款金额，并生成审核汇总报告。是否继续？')) return
    setFinalizing(true)
    setMessage('')
    try {
      const result = await request<any>(`/api/v2/audit-results/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: auditContext.project_name,
          business_type: auditContext.business_type,
          audit_month: auditContext.audit_month,
        }),
      })
      setFinalizeResult({
        confirmed_count: result.confirmed_count ?? result.confirmedCount ?? 0,
        total_deduction: result.total_deduction,
        first_exception_rate: result.first_exception_rate ?? 0,
        confirmed_exception_rate: result.confirmed_exception_rate ?? 0,
        message: result.message,
      })
      setMessage('审核结果已锁定，正在生成审核汇总与扣款报告...')
      // "生成扣款报告"即生成汇总与扣款报告（内含扣款明细）
      await request(
        `/api/v2/reports/generate?project_name=${encodeURIComponent(auditContext.project_name)}&business_type=${encodeURIComponent(auditContext.business_type)}&audit_month=${encodeURIComponent(auditContext.audit_month)}&report_type=summary`,
        { method: 'POST' }
      )
      setMessage(result.message || '审核汇总与扣款报告已生成，可前往"PDF报告"页下载。')
      await loadData()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '报告生成失败')
    }
    setFinalizing(false)
  }

  if (!auditContext) return <div className="text-slate-500">请先完成一次审核</div>
  if (loading) return <div className="text-slate-500">加载中...</div>
  if (!s04Data || !s04Data.deduction_details.length) return <div className="card p-8 text-center text-slate-500">本次审核无异常记录</div>

  const employeeList = s04Data.deduction_details.map(d => d.employee_name)
  const empRecordsMap: Record<string, ExceptionRecord[]> = {}
  for (const r of allRecords) {
    if (!empRecordsMap[r.employee_name]) empRecordsMap[r.employee_name] = []
    empRecordsMap[r.employee_name].push(r)
  }

  const currentRecords = selectedEmployee ? (empRecordsMap[selectedEmployee] || []) : []
  const totalExceptions = allRecords.length
  const confirmedCount = allRecords.filter(r => confirmMap[r.key] && !freeDeductionMap[r.key]).length
  const freeDeductionCount = allRecords.filter(r => freeDeductionMap[r.key]).length

  const currentDetail = s04Data.deduction_details.find(d => d.employee_name === selectedEmployee)

  return (
    <div className="space-y-4">
      {/* 顶部信息栏 */}
      <div className="card flex items-center justify-between p-5">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">考勤异常确认表</h2>
          <p className="mt-1 text-sm text-slate-500">
            {auditContext.project_name} {auditContext.audit_month} | 共 {totalExceptions} 条异常 | 已确认 {confirmedCount} 条 | 免打卡 {freeDeductionCount} 条
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isLocked ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700">
              已锁定
            </span>
          ) : (
            <>
              <button
                className="btn-secondary"
                disabled={saving || finalizing}
                onClick={saveConfirm}
              >
                {saving ? '提交中...' : '提交确认'}
              </button>
              <button
                className="btn-primary"
                disabled={saving || finalizing}
                onClick={generateReport}
              >
                {finalizing ? '生成报告中...' : '生成扣款报告'}
              </button>
            </>
          )}
        </div>
      </div>

      {message && <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</div>}

      {isLocked && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-700">
          <p className="font-medium">该审核结果已确认并锁定，不可再修改。</p>
        </div>
      )}

      {/* 操作说明 */}
      <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-700">
        <p className="font-medium">操作说明：</p>
        <p className="mt-1">1. 勾选异常记录表示项目确认该异常属实，将计入扣款</p>
        <p>2. 未勾选的记录表示项目有异议，将不计入扣款</p>
        <p>3. 点击"免打卡"可将该条异常标记为免打卡，免打卡的记录不扣款（每人每月有免打卡次数上限）</p>
        <p>4. 点击"提交确认"保存确认与免打卡状态</p>
        <p>5. 点击"生成扣款报告"按确认结果重新计算扣款金额，并生成审核汇总与扣款报告</p>
        <p>6. 生成完成后审核结果将被锁定，可多次修改并重新提交、重新生成</p>
      </div>

      {/* 报告生成结果 */}
      {finalizeResult && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-slate-900">扣款报告已生成</h3>
          <div className="mt-3 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-lg bg-slate-50 p-4 text-center">
              <div className="text-2xl font-bold text-slate-900">{finalizeResult.confirmed_count}</div>
              <div className="text-sm text-slate-500">确认异常条数</div>
            </div>
            <div className="rounded-lg bg-red-50 p-4 text-center">
              <div className="text-2xl font-bold text-red-600">¥{finalizeResult.total_deduction.toFixed(2)}</div>
              <div className="text-sm text-slate-500">总扣款金额（元）</div>
            </div>
            <div className="rounded-lg bg-amber-50 p-4 text-center">
              <div className="text-2xl font-bold text-amber-600">{finalizeResult.first_exception_rate}%</div>
              <div className="text-sm text-slate-500">第一次审核异常率</div>
            </div>
            <div className="rounded-lg bg-blue-50 p-4 text-center">
              <div className="text-2xl font-bold text-blue-600">{finalizeResult.confirmed_exception_rate}%</div>
              <div className="text-sm text-slate-500">确认后异常率</div>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">{finalizeResult.message}</p>
          <p className="mt-2 text-xs text-slate-400">审核结果已锁定，请到"审核结果"页面查看扣款明细</p>
        </div>
      )}

      <div className="flex gap-4">
        {/* 左侧员工列表 */}
        <div className="w-48 shrink-0">
          <div className="card p-3">
            <h3 className="mb-3 px-2 text-sm font-medium text-slate-700">员工列表</h3>
            <div className="space-y-1">
              {employeeList.map((emp) => {
                const empRecords = empRecordsMap[emp] || []
                const empConfirmed = empRecords.filter(r => confirmMap[r.key] && !freeDeductionMap[r.key]).length
                const empTotal = empRecords.length
                const empFreeUsed = empRecords.filter(r => freeDeductionMap[r.key]).length
                const empDetail = s04Data?.deduction_details.find(d => d.employee_name === emp)
                const freeLimit = empDetail?.missing_clock_free_limit ?? 3
                return (
                  <button
                    key={emp}
                    className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                      selectedEmployee === emp ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                    onClick={() => setSelectedEmployee(emp)}
                  >
                    <div className="flex flex-col">
                      <span>{emp}</span>
                      {empFreeUsed > 0 && (
                        <span className="text-xs text-amber-600">免打卡{empFreeUsed}/{freeLimit}</span>
                      )}
                    </div>
                    <span className="text-xs text-slate-400">{empConfirmed}/{empTotal}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* 右侧异常记录表格 */}
        <div className="flex-1">
          {currentDetail && (
            <div className="card overflow-hidden">
              <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
                <h3 className="text-sm font-medium text-slate-700">
                  {selectedEmployee} 的异常记录（{currentRecords.length}条）
                </h3>
                {!isLocked && (
                  <button
                    className="text-xs text-brand-600 underline"
                    onClick={() => selectAllForEmployee(selectedEmployee)}
                  >
                    全选/取消全选
                  </button>
                )}
              </div>
              <div className="overflow-auto">
                <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="w-12 px-4 py-3 text-center font-medium text-slate-600">确认</th>
                      <th className="w-28 px-4 py-3 text-left font-medium text-slate-600">日期</th>
                      <th className="w-24 px-4 py-3 text-left font-medium text-slate-600">岗位</th>
                      <th className="w-32 px-4 py-3 text-left font-medium text-slate-600">异常类型</th>
                      <th className="w-36 px-4 py-3 text-left font-medium text-slate-600">规定考勤时间</th>
                      <th className="w-44 px-4 py-3 text-left font-medium text-slate-600">实际BI打卡</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-600">异常说明</th>
                      <th className="w-24 px-4 py-3 text-right font-medium text-slate-600">金额</th>
                      <th className="w-28 px-4 py-3 text-center font-medium text-slate-600">是否免打卡</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {currentRecords.map((r) => {
                      const checked = confirmMap[r.key] ?? false
                      const free = freeDeductionMap[r.key] ?? false
                      const freeLimit = currentDetail.missing_clock_free_limit ?? 3
                      const freeUsed = getEmployeeFreeUsed(r.employee_name)
                      const freeDisabled = isLocked || (!checked && !free) || (checked && freeUsed >= freeLimit && !free)
                      return (
                        <tr key={r.key} className={free ? 'bg-amber-50' : checked ? 'bg-green-50' : 'hover:bg-slate-50'}>
                          <td className="px-4 py-3 text-center">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleConfirm(r.key)}
                              disabled={isLocked}
                              className={`h-5 w-5 rounded border-slate-300 text-brand-600 ${isLocked ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                            />
                          </td>
                          <td className="px-4 py-3 text-slate-700">{r.work_date}</td>
                          <td className="px-4 py-3 text-slate-700">{currentDetail.position}</td>
                          <td className="px-4 py-3">
                            <span className={`inline-block rounded-full px-2 py-1 text-xs font-medium ${exceptionBadgeClass(r.exception_type)}`}>
                              {r.exception_label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-700">{r.shift_time || '—'}</td>
                          <td className="px-4 py-3 text-xs text-slate-700">{r.clock_times || '—'}</td>
                          <td className="px-4 py-3 text-xs text-slate-500">{r.detail}</td>
                          <td className={`px-4 py-3 text-right font-medium ${free ? 'text-slate-400 line-through' : 'text-slate-900'}`}>
                            ¥{r.amount.toFixed(2)}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <button
                              className={`rounded px-2 py-1 text-xs font-medium transition ${
                                free
                                  ? 'bg-amber-200 text-amber-800 hover:bg-amber-300'
                                  : freeDisabled
                                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                                  : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                              } ${isLocked ? 'opacity-50 cursor-not-allowed' : ''}`}
                              disabled={freeDisabled}
                              onClick={() => handleFreeDeduction(r.key)}
                              title={free ? '点击取消免打卡' : `免打卡机会剩余：${freeLimit - freeUsed}次`}
                            >
                              {free ? '已免打卡' : '免打卡'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
