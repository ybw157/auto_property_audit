import { useEffect, useMemo, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { ReportDownloads } from '../components/ReportDownloads'
import { request } from '../services/api'

const tabs = [
  ['attendance-details', '保洁考勤明细'],
  ['position-fulfillment', '排班审核汇总'],
  ['exceptions', '人员异常统计'],
  ['attendance-deductions', '人员考勤扣款'],
  ['deductions', '扣款汇总'],
]

const columnLabels: Record<string, string> = {
  work_date: '日期',
  employee_name: '姓名',
  position: '岗位',
  area: '区域',
  shift_name: '班次',
  clock_times: '打卡时间',
  status: '状态',
  exception_type: '异常类型',
  exception_reason: '异常原因',
  deduction_amount: '扣款金额',
  issue_summary: '问题汇总',
  issue_days: '问题天数',
  issue_dates: '涉及日期',
  contract_headcount: '合同人数(不参与审核)',
  scheduled_headcount: '排班人数',
  actual_attendance_count: '实际出勤人数',
  shortage_count: '缺编人数(停用)',
  shortage_hours: '缺编工时(停用)',
  hourly_rate: '工时单价',
  position_deduction_amount: '岗位扣款金额',
  total_days: '统计天数',
  exception_count: '异常次数',
  exception_days: '异常天数',
  late_count: '迟到次数',
  early_leave_count: '早退次数',
  missing_clock_count: '漏打卡次数',
  absence_count: '缺勤次数',
  insufficient_hours_count: '工时不足次数',
  rule_name: '规则名称',
  rule_type: '规则类型',
  source: '来源',
  amount: '金额',
  summary_item: '汇总项目',
  value: '数值',
  business_type: '业态',
  source_row_no: '来源行号',
  result_status: '审核状态',
  calculation_detail: '审核说明',
}

const tabColumns: Record<string, string[]> = {
  'attendance-details': ['issue_summary', 'employee_name', 'position', 'area', 'exception_type', 'issue_days', 'issue_dates', 'deduction_amount'],
  'position-fulfillment': ['work_date', 'position', 'area', 'scheduled_headcount', 'actual_attendance_count', 'result_status', 'calculation_detail'],
  exceptions: ['employee_name', 'position', 'total_days', 'exception_days', 'exception_count', 'late_count', 'early_leave_count', 'missing_clock_count', 'absence_count', 'insufficient_hours_count', 'deduction_amount', 'exception_type'],
  'attendance-deductions': ['work_date', 'employee_name', 'position', 'exception_type', 'deduction_amount', 'rule_name'],
  deductions: ['summary_item', 'deduction_amount'],
}

export function AuditResults({ batchId }: { batchId: number | null }) {
  const [tab, setTab] = useState(tabs[0][0])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [versions, setVersions] = useState<Record<string, unknown>[]>([])
  const [workflowMessage, setWorkflowMessage] = useState('')
  const [dashboard, setDashboard] = useState({
    attendanceDetails: [] as Record<string, unknown>[],
    positionFulfillment: [] as Record<string, unknown>[],
    exceptions: [] as Record<string, unknown>[],
    attendanceDeductions: [] as Record<string, unknown>[],
    deductions: [] as Record<string, unknown>[],
  })
  const [proofUpdating, setProofUpdating] = useState<string>('')

  async function toggleAttendanceProof(employeeName: string, workDate: string, currentProof: boolean) {
    const key = `${employeeName}|${workDate}`
    setProofUpdating(key)
    try {
      await request(`/api/v1/results/${batchId}/attendance-proof`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ employee_name: employeeName, work_date: workDate, has_proof: !currentProof }),
      })
      // 刷新数据
      const [attendanceDetails, positionFulfillment, exceptions, attendanceDeductions, deductions] = await Promise.all([
        request<Record<string, unknown>[]>(`/api/v1/results/attendance-details?batch_id=${batchId}`),
        request<Record<string, unknown>[]>(`/api/v1/results/position-fulfillment?batch_id=${batchId}`),
        request<Record<string, unknown>[]>(`/api/v1/results/exceptions?batch_id=${batchId}`),
        request<Record<string, unknown>[]>(`/api/v1/results/attendance-deductions?batch_id=${batchId}`),
        request<Record<string, unknown>[]>(`/api/v1/results/deductions?batch_id=${batchId}`),
      ])
      setDashboard({ attendanceDetails, positionFulfillment, exceptions, attendanceDeductions, deductions })
      // 刷新当前tab数据
      const items = tab === 'attendance-details' ? attendanceDetails : tab === 'attendance-deductions' ? attendanceDeductions : await request<Record<string, unknown>[]>(`/api/v1/results/${tab}?batch_id=${batchId}`)
      setRows(buildRowsForTab(tab, items))
    } catch {
      // ignore
    }
    setProofUpdating('')
  }
  useEffect(() => {
    if (!batchId) return
    request<Record<string, unknown>[]>(`/api/v1/results/${tab}?batch_id=${batchId}`)
      .then((items) => setRows(buildRowsForTab(tab, items)))
      .catch(() => setRows([]))
  }, [batchId, tab])
  useEffect(() => {
    if (!batchId) return
    Promise.all([
      request<Record<string, unknown>[]>(`/api/v1/results/attendance-details?batch_id=${batchId}`),
      request<Record<string, unknown>[]>(`/api/v1/results/position-fulfillment?batch_id=${batchId}`),
      request<Record<string, unknown>[]>(`/api/v1/results/exceptions?batch_id=${batchId}`),
      request<Record<string, unknown>[]>(`/api/v1/results/attendance-deductions?batch_id=${batchId}`),
      request<Record<string, unknown>[]>(`/api/v1/results/deductions?batch_id=${batchId}`),
    ])
      .then(([attendanceDetails, positionFulfillment, exceptions, attendanceDeductions, deductions]) => {
        setDashboard({ attendanceDetails, positionFulfillment, exceptions, attendanceDeductions, deductions })
      })
      .catch(() => setDashboard({ attendanceDetails: [], positionFulfillment: [], exceptions: [], attendanceDeductions: [], deductions: [] }))
  }, [batchId])
  useEffect(() => {
    if (!batchId) return
    request<Record<string, unknown>[]>(`/api/v1/audit-batches/${batchId}/versions`).then(setVersions).catch(() => setVersions([]))
  }, [batchId])
  async function confirmFinal() {
    if (!batchId) return
    try {
      await request(`/api/v1/audit-batches/${batchId}/confirm-final`, { method: 'POST' })
      setWorkflowMessage('最终版已确认并锁定')
      const rows = await request<Record<string, unknown>[]>(`/api/v1/audit-batches/${batchId}/versions`)
      setVersions(rows)
    } catch (error) {
      setWorkflowMessage(error instanceof Error ? error.message : '确认失败')
    }
  }
  if (!batchId) return <div className="card p-8 text-center text-sm text-slate-500">请先完成一次审核</div>
  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">版本与确认</h2>
            <p className="mt-1 text-sm text-slate-500">项目在异常确认页面提交确认后，系统自动生成带扣款金额的最终版。项目在此页面查看扣款明细并点击确认最终版后锁定。</p>
          </div>
          <button className="btn-primary" onClick={confirmFinal}>确认最终版</button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {versions.map((item, index) => (
            <span key={`${item.version_label}-${index}`} className={`rounded-full px-3 py-1 text-xs font-medium ${item.is_current ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-600'}`}>
              {String(item.version_label || '-')} {item.is_current ? '当前版' : '历史版'} {item.is_locked ? '已锁定' : ''}
            </span>
          ))}
          {!versions.length && <span className="text-sm text-slate-500">暂无版本记录</span>}
        </div>
        {workflowMessage && <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">{workflowMessage}</div>}
      </div>
      <AuditDashboard data={dashboard} />
      <ReportDownloads batchId={batchId} />
      <div className="flex gap-2">
        {tabs.map(([key, label]) => <button key={key} className={key === tab ? 'btn-primary' : 'btn-secondary'} onClick={() => setTab(key)}>{label}</button>)}
      </div>
      <DataTable rows={rows} columns={tabColumns[tab]} labels={columnLabels} getRowClassName={getResultRowClassName} />

      {/* 疑似漏打卡出勤证明操作区 */}
      {tab === 'attendance-deductions' && dashboard.attendanceDeductions.some((d) => String(d.exception_type || '').includes('疑似漏打卡')) && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-slate-900">疑似漏打卡 - 出勤证明管理</h3>
          <p className="mt-1 text-sm text-slate-500">合同约定每人每月有3次补卡机会，提供出勤证明可免扣款。点击"已提供证明"切换状态。</p>
          <div className="mt-4 overflow-auto">
            <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">姓名</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">日期</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">异常类型</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">扣款金额</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">出勤证明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {dashboard.attendanceDeductions
                  .filter((d) => String(d.exception_type || '').includes('疑似漏打卡'))
                  .map((d, idx) => {
                    const empName = String(d.employee_name || '')
                    const workDate = String(d.work_date || '')
                    const key = `${empName}|${workDate}`
                    const hasProof = Boolean(d.has_attendance_proof)
                    const amount = Number(d.deduction_amount || 0)
                    return (
                      <tr key={idx} className="hover:bg-slate-50">
                        <td className="px-4 py-3 text-slate-700">{empName}</td>
                        <td className="px-4 py-3 text-slate-700">{workDate}</td>
                        <td className="px-4 py-3 text-slate-700">疑似漏打卡</td>
                        <td className="px-4 py-3 text-slate-700">{hasProof ? <span className="text-green-600">0元（已免扣）</span> : <span className="text-red-600">{amount}元</span>}</td>
                        <td className="px-4 py-3">
                          <button
                            className={`rounded px-3 py-1 text-xs font-medium ${hasProof ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'} ${proofUpdating === key ? 'opacity-50' : ''}`}
                            disabled={proofUpdating === key}
                            onClick={() => toggleAttendanceProof(empName, workDate, hasProof)}
                          >
                            {proofUpdating === key ? '更新中...' : hasProof ? '已提供证明 ✓' : '未提供证明，点击切换'}
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
  )
}

function buildRowsForTab(tab: string, items: Record<string, unknown>[]) {
  if (tab === 'attendance-details') {
    return summarizeAttendanceIssues(items)
  }
  if (tab === 'deductions') {
    return transformDeductionSummary(items)
  }
  return sortRowsForTab(tab, items)
}

function transformDeductionSummary(items: Record<string, unknown>[]) {
  const item = items[0] || {}
  // 兼容两种格式：
  // 1. 原始审核/finalize新格式: {position_deduction_amount, attendance_deduction_amount, total_deduction_amount}
  // 2. finalize旧格式: {employee_name, total_deduction, ...}（按员工汇总）
  if (item.position_deduction_amount !== undefined || item.attendance_deduction_amount !== undefined || item.total_deduction_amount !== undefined) {
    const attendanceAmount = Number(item.attendance_deduction_amount || 0)
    const positionAmount = Number(item.position_deduction_amount || 0)
    const totalAmount = Number(item.total_deduction_amount || 0) || attendanceAmount + positionAmount
    return [
      { summary_item: '人员考勤扣款', deduction_amount: attendanceAmount.toFixed(2) },
      { summary_item: '岗位扣款', deduction_amount: positionAmount.toFixed(2) },
      { summary_item: '合计扣款', deduction_amount: totalAmount.toFixed(2) },
    ]
  }
  // 旧格式：按员工汇总的数据，直接展示
  return items.map((row) => ({
    summary_item: String(row.employee_name || row.position || '-'),
    deduction_amount: Number(row.total_deduction || 0).toFixed(2),
  }))
}

function summarizeAttendanceIssues(items: Record<string, unknown>[]) {
  const groups = new Map<string, {
    employee_name: string
    position: string
    area: string
    exception_type: string
    dates: Set<string>
    deduction_amount: number
  }>()
  items.forEach((item) => {
    if (!isAbnormalRow(item)) return
    const employeeName = String(item.employee_name || '')
    const position = String(item.position || '')
    const area = String(item.area || '')
    const exceptionType = String(item.exception_type || '异常')
    const key = [position, employeeName, exceptionType, area].join('|')
    const current = groups.get(key) ?? {
      employee_name: employeeName,
      position,
      area,
      exception_type: exceptionType,
      dates: new Set<string>(),
      deduction_amount: 0,
    }
    const workDate = String(item.work_date || '')
    if (workDate) current.dates.add(workDate)
    current.deduction_amount += toNumber(item.deduction_amount)
    groups.set(key, current)
  })
  return Array.from(groups.values())
    .map((item) => {
      const dates = Array.from(item.dates).sort()
      const issueDays = dates.length
      return {
        employee_name: item.employee_name,
        position: item.position,
        area: item.area,
        exception_type: item.exception_type,
        issue_days: issueDays,
        issue_dates: formatIssueDates(dates),
        deduction_amount: Number(item.deduction_amount.toFixed(2)),
        issue_summary: `${item.position} ${item.employee_name} ${item.exception_type}出现${issueDays}天问题`,
      }
    })
    .sort((a, b) => toNumber(b.deduction_amount) - toNumber(a.deduction_amount) || toNumber(b.issue_days) - toNumber(a.issue_days))
}

function formatIssueDates(dates: string[]) {
  if (!dates.length) return ''
  if (dates.length <= 8) return dates.map((date) => date.slice(5)).join('、')
  return `${dates[0].slice(5)} 至 ${dates[dates.length - 1].slice(5)}，共${dates.length}天`
}

function sortRowsForTab(tab: string, items: Record<string, unknown>[]) {
  const sorted = [...items]
  if (tab === 'attendance-details') {
    return sorted.sort((a, b) => Number(isAbnormalRow(b)) - Number(isAbnormalRow(a)) || String(a.work_date || '').localeCompare(String(b.work_date || '')))
  }
  if (tab === 'position-fulfillment') {
    return sorted.sort((a, b) => toNumber(b.shortage_count) - toNumber(a.shortage_count) || toNumber(b.position_deduction_amount) - toNumber(a.position_deduction_amount))
  }
  if (tab === 'exceptions') {
    return sorted.sort((a, b) => toNumber(b.deduction_amount) - toNumber(a.deduction_amount) || toNumber(b.exception_count ?? b.count) - toNumber(a.exception_count ?? a.count))
  }
  if (tab === 'attendance-deductions') {
    return sorted.sort((a, b) => toNumber(b.deduction_amount) - toNumber(a.deduction_amount) || String(a.work_date || '').localeCompare(String(b.work_date || '')))
  }
  return sorted
}

function getResultRowClassName(row: Record<string, unknown>) {
  if (isAbnormalRow(row) || toNumber(row.shortage_count) > 0 || toNumber(row.deduction_amount) > 0) {
    return 'bg-red-50 hover:bg-red-100 [&_td]:!text-red-800'
  }
  return 'hover:bg-slate-50'
}

function isAbnormalRow(row: Record<string, unknown>) {
  const exception = String(row.exception_type || '')
  const status = String(row.result_status || row.status || '')
  return Boolean(exception && exception !== '正常') || status === '异常'
}

type DashboardData = {
  attendanceDetails: Record<string, unknown>[]
  positionFulfillment: Record<string, unknown>[]
  exceptions: Record<string, unknown>[]
  attendanceDeductions: Record<string, unknown>[]
  deductions: Record<string, unknown>[]
}

function AuditDashboard({ data }: { data: DashboardData }) {
  const view = useMemo(() => buildDashboardView(data), [data])
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-5">
        <MetricCard title="总扣款金额" value={`${formatMoney(view.totalDeduction)} 元`} tone="red" helper="人员考勤扣款汇总" />
        <MetricCard title="排班任务" value={`${view.scheduleTaskCount} 条`} tone="amber" helper="以月度排班表为唯一依据" />
        <MetricCard title="异常记录" value={`${view.exceptionCount} 条`} tone="blue" helper={`涉及 ${view.exceptionPeopleCount} 人 · 确认${view.confirmedExceptionCount}条`} />
        <MetricCard title="审核覆盖" value={`${view.auditedPeopleCount} 人`} tone="green" helper={`${view.auditedDays} 个日期`} />
        <MetricCard title="异常率" value={`${view.firstExceptionRate.toFixed(1)}%`} tone="purple" helper={`第一次异常率 · 确认后${view.confirmedExceptionRate.toFixed(1)}%`} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="card p-5 xl:col-span-1">
          <h2 className="text-base font-semibold text-slate-900">扣款构成</h2>
          <div className="mt-5 space-y-4">
            <RatioBar label="人员考勤扣款" value={view.attendanceDeduction} total={view.totalDeduction} color="bg-red-500" />
          </div>
        </div>

        <div className="card p-5 xl:col-span-1">
          <h2 className="text-base font-semibold text-slate-900">异常类型排行</h2>
          <RankList items={view.exceptionRanks} emptyText="暂无异常" color="bg-blue-500" />
        </div>

        <div className="card p-5 xl:col-span-1">
          <h2 className="text-base font-semibold text-slate-900">异常岗位排行</h2>
          <RankList items={view.positionExceptionRanks} emptyText="暂无异常岗位" color="bg-amber-500" suffix="次" />
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <div className="card p-5">
          <h2 className="text-base font-semibold text-slate-900">高风险人员</h2>
          <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-100">
            <table className="min-w-[560px] table-fixed text-sm">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="w-28 px-4 py-3 text-left">姓名</th>
                  <th className="w-24 px-4 py-3 text-left">异常次数</th>
                  <th className="w-24 px-4 py-3 text-left">扣款金额</th>
                  <th className="px-4 py-3 text-left">主要异常</th>
                </tr>
              </thead>
              <tbody>
                {view.riskyPeople.map((item) => (
                  <tr key={item.name} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-medium text-slate-800 break-words">{item.name}</td>
                    <td className="px-4 py-3">{item.count}</td>
                    <td className="px-4 py-3 text-red-600">{formatMoney(item.amount)}</td>
                    <td className="px-4 py-3 text-slate-500 break-words">{item.mainType}</td>
                  </tr>
                ))}
                {!view.riskyPeople.length && <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={4}>暂无高风险人员</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card p-5">
          <h2 className="text-base font-semibold text-slate-900">审核建议</h2>
          <div className="mt-4 space-y-3">
            {view.suggestions.map((item) => (
              <div key={item} className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">{item}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function MetricCard({ title, value, helper, tone }: { title: string; value: string; helper: string; tone: 'red' | 'amber' | 'blue' | 'green' | 'purple' }) {
  const toneClass = {
    red: 'from-red-50 to-white text-red-700 ring-red-100',
    amber: 'from-amber-50 to-white text-amber-700 ring-amber-100',
    blue: 'from-blue-50 to-white text-blue-700 ring-blue-100',
    green: 'from-emerald-50 to-white text-emerald-700 ring-emerald-100',
    purple: 'from-purple-50 to-white text-purple-700 ring-purple-100',
  }[tone]
  return (
    <div className={`rounded-3xl bg-gradient-to-br p-5 ring-1 ${toneClass}`}>
      <div className="text-sm font-medium text-slate-500">{title}</div>
      <div className="mt-3 text-2xl font-semibold">{value}</div>
      <div className="mt-2 text-xs text-slate-500">{helper}</div>
    </div>
  )
}

function RatioBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const percent = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-medium text-slate-900">{formatMoney(value)} 元 · {percent}%</span>
      </div>
      <div className="mt-2 h-3 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(percent, value > 0 ? 4 : 0)}%` }} />
      </div>
    </div>
  )
}

function RankList({ items, emptyText, color, suffix = '次' }: { items: Array<{ name: string; value: number }>; emptyText: string; color: string; suffix?: string }) {
  const max = Math.max(...items.map((item) => item.value), 1)
  if (!items.length) return <div className="mt-8 text-center text-sm text-slate-500">{emptyText}</div>
  return (
    <div className="mt-4 space-y-3">
      {items.map((item) => (
        <div key={item.name}>
          <div className="flex items-center justify-between text-sm">
            <span className="max-w-[65%] truncate text-slate-700">{item.name}</span>
            <span className="font-medium text-slate-900">{item.value}{suffix}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max((item.value / max) * 100, 6)}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function buildDashboardView(data: DashboardData) {
  const deduction = data.deductions[0] ?? {}
  const positionDeduction = toNumber(deduction.position_deduction_amount)
  // 兼容两种格式：原始审核用 attendance_deduction_amount，finalize 旧版用 total_deduction
  const attendanceDeduction = toNumber(deduction.attendance_deduction_amount) || toNumber(deduction.total_deduction)
  // 优先使用 deduction_summary 中的总额，如果没有则从 attendanceDeductions 中汇总
  const totalDeduction = toNumber(deduction.total_deduction_amount) || positionDeduction + attendanceDeduction || sum(data.attendanceDeductions, 'deduction_amount')
  const scheduleTaskCount = data.attendanceDetails.length || sum(data.positionFulfillment, 'scheduled_headcount')
  const auditedPeople = new Set(data.attendanceDetails.map((item) => String(item.employee_name || '')).filter(Boolean))
  const auditedDays = new Set(data.attendanceDetails.map((item) => String(item.work_date || '')).filter(Boolean)).size
  const exceptionRows = data.attendanceDetails.filter((item) => String(item.exception_type || '') && String(item.exception_type) !== '正常')
  const confirmedExceptionRows = exceptionRows.filter((item) => item.project_confirmed === true)
  const exceptionPeople = new Set(exceptionRows.map((item) => String(item.employee_name || '')).filter(Boolean))
  const firstExceptionRate = scheduleTaskCount > 0 ? (exceptionRows.length / scheduleTaskCount * 100) : 0
  const confirmedExceptionRate = scheduleTaskCount > 0 ? (confirmedExceptionRows.length / scheduleTaskCount * 100) : 0

  const exceptionRanks = data.exceptions
    .map((item) => ({ name: String(item.exception_type || '异常'), value: toNumber(item.count ?? item.exception_count) }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)

  const exceptionByPosition = new Map<string, number>()
  exceptionRows.forEach((item) => {
    const key = String(item.position || '未命名岗位')
    exceptionByPosition.set(key, (exceptionByPosition.get(key) ?? 0) + 1)
  })
  const positionExceptionRanks = Array.from(exceptionByPosition.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)

  const peopleMap = new Map<string, { name: string; count: number; amount: number; types: Map<string, number> }>()
  data.attendanceDeductions.forEach((item) => {
    const name = String(item.employee_name || '')
    if (!name) return
    const current = peopleMap.get(name) ?? { name, count: 0, amount: 0, types: new Map<string, number>() }
    current.count += 1
    current.amount += toNumber(item.deduction_amount)
    const type = String(item.exception_type || '异常')
    current.types.set(type, (current.types.get(type) ?? 0) + 1)
    peopleMap.set(name, current)
  })
  const riskyPeople = Array.from(peopleMap.values())
    .map((item) => ({
      name: item.name,
      count: item.count,
      amount: item.amount,
      mainType: Array.from(item.types.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '异常',
    }))
    .sort((a, b) => b.amount - a.amount || b.count - a.count)
    .slice(0, 6)

  const suggestions = buildSuggestions({ totalDeduction, exceptionRanks, positionExceptionRanks, riskyPeople })
  return {
    positionDeduction,
    attendanceDeduction,
    totalDeduction,
    scheduleTaskCount,
    exceptionCount: exceptionRows.length,
    confirmedExceptionCount: confirmedExceptionRows.length,
    firstExceptionRate,
    confirmedExceptionRate,
    exceptionPeopleCount: exceptionPeople.size,
    auditedPeopleCount: auditedPeople.size,
    auditedDays,
    exceptionRanks,
    positionExceptionRanks,
    riskyPeople,
    suggestions,
  }
}

function buildSuggestions(view: {
  totalDeduction: number
  exceptionRanks: Array<{ name: string; value: number }>
  positionExceptionRanks: Array<{ name: string; value: number }>
  riskyPeople: Array<{ name: string; count: number; amount: number; mainType: string }>
}) {
  const suggestions: string[] = []
  if (view.totalDeduction <= 0) suggestions.push('本批次未产生扣款，建议保留审核记录并归档。')
  if (view.exceptionRanks[0]) suggestions.push(`最高频异常为“${view.exceptionRanks[0].name}”，共 ${view.exceptionRanks[0].value} 次，建议核查Rule Center规则和BI原始记录。`)
  if (view.positionExceptionRanks[0]) suggestions.push(`异常最集中的岗位是“${view.positionExceptionRanks[0].name}”，建议由项目核实排班后重新提交。`)
  if (view.riskyPeople[0]) suggestions.push(`人员异常扣款最高的是“${view.riskyPeople[0].name}”，主要异常为“${view.riskyPeople[0].mainType}”。`)
  if (!suggestions.length) suggestions.push('暂无明显风险项，可直接查看下方明细表进行抽查。')
  return suggestions.slice(0, 4)
}

function sum(rows: Record<string, unknown>[], key: string) {
  return rows.reduce((total, item) => total + toNumber(item[key]), 0)
}

function toNumber(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatNumber(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
