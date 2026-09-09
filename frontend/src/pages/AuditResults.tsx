import { useEffect, useMemo, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { ReportDownloads } from '../components/ReportDownloads'
import { request } from '../services/api'
import type { AuditContext } from '../types'
import { useAuditContext } from '../hooks/useAuditContext'
import { useAuth } from '../hooks/useAuth'

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
  scheduled: '排班人员',
  actual_present: '实际到岗',
  status: '状态',
  note: '说明',
  exception_type: '异常类型',
  deduction_amount: '扣款金额',
  detail: '详情',
  missing_clock_count: '漏打卡次数',
  late_count: '迟到次数',
  early_leave_count: '早退次数',
  absence_count: '缺勤次数',
  absence_daily_rate: '日服务费',
  total_deduction: '扣款合计',
  summary_item: '汇总项目',
  missing_clock_free_limit: '免扣次数',
}

const tabColumns: Record<string, string[]> = {
  'attendance-details': ['employee_name', 'position', 'work_date', 'exception_type', 'deduction_amount', 'detail'],
  'position-fulfillment': ['work_date', 'position', 'area', 'scheduled', 'actual_present', 'status', 'note'],
  exceptions: ['employee_name', 'position', 'missing_clock_count', 'late_count', 'early_leave_count', 'absence_count', 'absence_daily_rate', 'total_deduction'],
  'attendance-deductions': ['employee_name', 'position', 'exception_type', 'deduction_amount'],
  deductions: ['summary_item', 'deduction_amount'],
}

export function AuditResults() {
  const { auditContext, setAuditContext } = useAuditContext()
  const { projectName: userProjectName } = useAuth()
  const [tab, setTab] = useState(tabs[0][0])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(!auditContext)
  const [dashboard, setDashboard] = useState({
    attendanceDetails: [] as Record<string, unknown>[],
    positionFulfillment: [] as Record<string, unknown>[],
    exceptions: [] as Record<string, unknown>[],
    attendanceDeductions: [] as Record<string, unknown>[],
    deductions: [] as Record<string, unknown>[],
    s04Summary: {} as Record<string, unknown>,
  })
  const [proofUpdating, setProofUpdating] = useState<string>('')
  const [detailData, setDetailData] = useState<Record<string, unknown> | null>(null)

  const projectName = auditContext?.project_name || ''
  const auditMonth = auditContext?.audit_month || ''
  const businessType = auditContext?.business_type || ''

  // 当 auditContext 为空时，自动从后端查询最近的审核结果
  useEffect(() => {
    if (auditContext) {
      setLoading(false)
      return
    }
    // 查询最近的审核结果
    request<Record<string, unknown>[]>('/api/v2/audit-results', { method: 'GET' })
      .then((list) => {
        if (list && list.length > 0) {
          // 项目账号只显示自己项目的结果
          const filtered = userProjectName
            ? list.filter((item) => String(item.project_name || '').includes(userProjectName.replace('项目', '')))
            : list
          // 取最近的一条
          const latest = filtered[0]
          if (latest) {
            const ctx = {
              project_name: String(latest.project_name || ''),
              audit_month: String(latest.audit_month || ''),
              business_type: String(latest.business_type || ''),
            }
            setAuditContext(ctx)
          } else {
            setLoading(false)
          }
        } else {
          setLoading(false)
        }
      })
      .catch(() => {
        setLoading(false)
      })
  }, [auditContext, setAuditContext, userProjectName])

  function parseResultsJson(raw: unknown): {
    slotDetails: Record<string, unknown>[]
    summary: Record<string, unknown>[]
    s04: Record<string, unknown>
    deductionDetails: Record<string, unknown>[]
  } {
    if (!raw || typeof raw !== 'object') return { slotDetails: [], summary: [], s04: {}, deductionDetails: [] }
    const r = raw as Record<string, unknown>
    const slotDetails = Array.isArray(r.slot_details) ? r.slot_details as Record<string, unknown>[] : []
    const summary = Array.isArray(r.summary) ? r.summary as Record<string, unknown>[] : []
    const s04 = (r.s04_attendance_audit && typeof r.s04_attendance_audit === 'object') ? r.s04_attendance_audit as Record<string, unknown> : {}
    const deductionDetails = Array.isArray(s04.deduction_details) ? s04.deduction_details as Record<string, unknown>[] : []
    return { slotDetails, summary, s04, deductionDetails }
  }

  function buildTabRows(tabKey: string, parsed: ReturnType<typeof parseResultsJson>): Record<string, unknown>[] {
    if (tabKey === 'position-fulfillment') {
      return parsed.slotDetails.map((s) => ({
        work_date: s.work_date || '',
        position: s.position || '',
        area: s.area || '',
        scheduled: Array.isArray(s.scheduled) ? (s.scheduled as string[]).join('、') : '',
        actual_present: Array.isArray(s.actual_present) ? (s.actual_present as string[]).join('、') : '',
        status: s.status || '',
        note: s.note || '',
      }))
    }
    if (tabKey === 'attendance-details') {
      const rows: Record<string, unknown>[] = []
      for (const d of parsed.deductionDetails) {
        const empName = String(d.employee_name || '')
        const position = String(d.position || '')
        const missingDates = Array.isArray(d.missing_clock_dates) ? d.missing_clock_dates as string[] : []
        const absenceDates = Array.isArray(d.absence_dates) ? d.absence_dates as string[] : []
        const lateDetails = Array.isArray(d.late_details) ? d.late_details as Record<string, unknown>[] : []
        const earlyDetails = Array.isArray(d.early_leave_details) ? d.early_leave_details as Record<string, unknown>[] : []
        const midIssues = Array.isArray(d.mid_clock_issues) ? d.mid_clock_issues as Record<string, unknown>[] : []
        const absenceDailyRate = Number(d.absence_daily_rate || 0)
        const absenceMultiplier = Number(d.absence_multiplier || 2.5)

        for (const date of missingDates) {
          rows.push({ employee_name: empName, position, work_date: date, exception_type: '漏打卡', deduction_amount: 0 })
        }
        for (const mi of midIssues) {
          rows.push({ employee_name: empName, position, work_date: mi.date || '', exception_type: '漏打卡', deduction_amount: 0, detail: `中间卡缺失 ${mi.window || ''} 应打${mi.required || 0}次实打${mi.actual || 0}次` })
        }
        for (const date of absenceDates) {
          const absenceAmount = Number((absenceDailyRate * absenceMultiplier).toFixed(2))
          rows.push({ employee_name: empName, position, work_date: date, exception_type: '缺勤', deduction_amount: absenceAmount, detail: `日服务费${absenceDailyRate}元×${absenceMultiplier}` })
        }
        for (const ld of lateDetails) {
          const lateAmount = Number((Number(ld.amount) || 0).toFixed(2))
          rows.push({ employee_name: empName, position, work_date: ld.date || '', exception_type: '迟到', deduction_amount: lateAmount, detail: `迟到${ld.minutes || 0}分钟` })
        }
        for (const ed of earlyDetails) {
          const earlyAmount = Number((Number(ed.amount) || 0).toFixed(2))
          rows.push({ employee_name: empName, position, work_date: ed.date || '', exception_type: '早退', deduction_amount: earlyAmount, detail: `早退${ed.minutes || 0}分钟` })
        }
      }
      return rows
    }
    if (tabKey === 'exceptions') {
      return parsed.deductionDetails.map((d) => ({
        employee_name: d.employee_name || '',
        position: d.position || '',
        missing_clock_count: d.missing_clock_count ?? 0,
        missing_clock_free_limit: d.missing_clock_free_limit ?? 0,
        late_count: Array.isArray(d.late_details) ? (d.late_details as unknown[]).length : 0,
        early_leave_count: Array.isArray(d.early_leave_details) ? (d.early_leave_details as unknown[]).length : 0,
        absence_count: d.absence_count ?? (Array.isArray(d.absence_dates) ? (d.absence_dates as unknown[]).length : 0),
        absence_daily_rate: Number(d.absence_daily_rate || 0),
        total_deduction: Number(d.total_deduction || 0),
      }))
    }
    if (tabKey === 'attendance-deductions') {
      const rows: Record<string, unknown>[] = []
      for (const d of parsed.deductionDetails) {
        const empName = String(d.employee_name || '')
        const position = String(d.position || '')
        const missingAmount = Number(d.missing_clock_amount || 0)
        const lateTotal = Number(d.late_total || 0)
        const earlyTotal = Number(d.early_leave_total || 0)
        const absenceAmount = Number(d.absence_amount || 0)
        if (missingAmount > 0) rows.push({ employee_name: empName, position, exception_type: '漏打卡', deduction_amount: missingAmount })
        if (lateTotal > 0) rows.push({ employee_name: empName, position, exception_type: '迟到', deduction_amount: lateTotal })
        if (earlyTotal > 0) rows.push({ employee_name: empName, position, exception_type: '早退', deduction_amount: earlyTotal })
        if (absenceAmount > 0) rows.push({ employee_name: empName, position, exception_type: '缺勤', deduction_amount: absenceAmount })
      }
      return rows
    }
    if (tabKey === 'deductions') {
      const s04Summary = parsed.s04.summary as Record<string, unknown> | undefined || {}
      const missingAmount = Number(s04Summary.total_missing_clock_amount || 0)
      const lateAmount = Number(s04Summary.total_late_amount || 0)
      const earlyAmount = Number(s04Summary.total_early_leave_amount || 0)
      const absenceAmount = Number(s04Summary.total_absence_amount || 0)
      const totalAmount = Number(s04Summary.total_deduction || 0)
      return [
        { summary_item: '漏打卡扣款', deduction_amount: missingAmount },
        { summary_item: '迟到扣款', deduction_amount: lateAmount },
        { summary_item: '早退扣款', deduction_amount: earlyAmount },
        { summary_item: '缺勤扣款', deduction_amount: absenceAmount },
        { summary_item: '合计扣款', deduction_amount: totalAmount },
      ]
    }
    return []
  }

  useEffect(() => {
    if (!auditContext) return
    const params = new URLSearchParams({ project_name: projectName, business_type: businessType, audit_month: auditMonth })
    request<Record<string, unknown>>(`/api/v2/audit-results/detail?${params}`)
      .then((detail) => {
        setDetailData(detail)
        const resultsJson = typeof detail.results_json === 'string' ? JSON.parse(detail.results_json as string) : detail.results_json
        const parsed = parseResultsJson(resultsJson)
        setDashboard({
          attendanceDetails: buildTabRows('attendance-details', parsed),
          positionFulfillment: buildTabRows('position-fulfillment', parsed),
          exceptions: buildTabRows('exceptions', parsed),
          attendanceDeductions: buildTabRows('attendance-deductions', parsed),
          deductions: buildTabRows('deductions', parsed),
          s04Summary: parsed.s04.summary as Record<string, unknown> || {},
        })
        setRows(buildTabRows(tab, parsed))
      })
      .catch(() => {
        setDetailData(null)
        setRows([])
        setDashboard({ attendanceDetails: [], positionFulfillment: [], exceptions: [], attendanceDeductions: [], deductions: [], s04Summary: {} })
      })
  }, [auditContext])

  useEffect(() => {
    if (!auditContext || !detailData) return
    const resultsJson = typeof detailData.results_json === 'string' ? JSON.parse(detailData.results_json as string) : detailData.results_json
    const parsed = parseResultsJson(resultsJson)
    setRows(buildTabRows(tab, parsed))
  }, [tab])

  async function toggleAttendanceProof(employeeName: string, workDate: string, currentProof: boolean) {
    const key = `${employeeName}|${workDate}`
    setProofUpdating(key)
    try {
      // TODO: V2 暂无 attendance-proof 端点，待后端补充
      setMessage('出勤证明切换已记录（V2 待实现）')
    } catch {
      // ignore
    }
    setProofUpdating('')
  }

  async function confirmFinal() {
    if (!auditContext) return
    try {
      const params = new URLSearchParams({ project_name: projectName, business_type: businessType, audit_month: auditMonth })
      await request(`/api/v2/audit-results/confirm?${params}`, { method: 'POST' })
      setMessage('审核结果已确认并锁定')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '确认失败')
    }
  }

  if (loading) return <div className="card p-8 text-center text-sm text-slate-500">加载中…</div>
  if (!auditContext) return <div className="card p-8 text-center text-sm text-slate-500">请先完成一次审核</div>

  const isLocked = detailData ? Boolean((detailData as Record<string, unknown>).locked) : false

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">审核确认</h2>
            <p className="mt-1 text-sm text-slate-500">
              {projectName} {auditMonth} {businessType ? `· ${businessType}` : ''} · 版本 {String(detailData?.version ?? '-')}
              {isLocked ? ' · 已锁定' : ''}
            </p>
          </div>
          <button className="btn-primary" disabled={isLocked} onClick={confirmFinal}>{isLocked ? '已确认' : '确认最终版'}</button>
        </div>
        {message && <div className="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</div>}
      </div>
      <AuditDashboard data={dashboard} />
      <ReportDownloads auditContext={auditContext} />
      <div className="flex gap-2">
        {tabs.map(([key, label]) => <button key={key} className={key === tab ? 'btn-primary' : 'btn-secondary'} onClick={() => setTab(key)}>{label}</button>)}
      </div>
      <DataTable rows={rows} columns={tabColumns[tab]} labels={columnLabels} getRowClassName={getResultRowClassName} />

      {tab === 'attendance-deductions' && dashboard.attendanceDeductions.some((d) => String(d.exception_type || '') === '漏打卡') && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-slate-900">漏打卡 - 出勤证明管理</h3>
          <p className="mt-1 text-sm text-slate-500">合同约定每人每月有免扣次数（见"人员异常统计"表），提供出勤证明可免扣款。审核员核实后协助计算免扣次数。点击"已提供证明"切换状态。</p>
          <div className="mt-4 overflow-auto">
            <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">姓名</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">岗位</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">扣款金额</th>
                  <th className="min-w-28 px-4 py-3 text-left font-medium text-slate-600">出勤证明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {dashboard.attendanceDeductions
                  .filter((d) => String(d.exception_type || '') === '漏打卡')
                  .map((d, idx) => {
                    const empName = String(d.employee_name || '')
                    const position = String(d.position || '')
                    const key = empName
                    const hasProof = Boolean(d.has_attendance_proof)
                    const amount = Number(d.deduction_amount || 0)
                    return (
                      <tr key={idx} className="hover:bg-slate-50">
                        <td className="px-4 py-3 text-slate-700">{empName}</td>
                        <td className="px-4 py-3 text-slate-700">{position}</td>
                        <td className="px-4 py-3 text-slate-700">{hasProof ? <span className="text-green-600">0元（已免扣）</span> : <span className="text-red-600">{amount}元</span>}</td>
                        <td className="px-4 py-3">
                          <button
                            className={`rounded px-3 py-1 text-xs font-medium ${hasProof ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'} ${proofUpdating === key ? 'opacity-50' : ''}`}
                            disabled={proofUpdating === key}
                            onClick={() => toggleAttendanceProof(empName, '', hasProof)}
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
  s04Summary: Record<string, unknown>
}

function AuditDashboard({ data }: { data: DashboardData }) {
  const view = useMemo(() => buildDashboardView(data), [data])
  const s04Summary = data.s04Summary || {}
  const missingAmount = Number(s04Summary.total_missing_clock_amount || 0)
  const lateAmount = Number(s04Summary.total_late_amount || 0)
  const earlyAmount = Number(s04Summary.total_early_leave_amount || 0)
  const absenceAmount = Number(s04Summary.total_absence_amount || 0)
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-5">
        <MetricCard title="总扣款金额" value={`${formatMoney(view.totalDeduction)} 元`} tone="red" helper="人员考勤扣款汇总" />
        <MetricCard title="排班任务" value={`${view.scheduleTaskCount} 条`} tone="amber" helper="以月度排班表为唯一依据" />
        <MetricCard title="异常记录" value={`${view.exceptionCount} 条`} tone="blue" helper={`涉及 ${view.exceptionPeopleCount} 人`} />
        <MetricCard title="审核覆盖" value={`${view.auditedPeopleCount} 人`} tone="green" helper={`${view.auditedDays} 个日期`} />
        <MetricCard title="异常率" value={`${view.firstExceptionRate.toFixed(1)}%`} tone="purple" helper="异常记录占比" />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="card p-5 xl:col-span-1">
          <h2 className="text-base font-semibold text-slate-900">扣款构成</h2>
          <div className="mt-5 space-y-4">
            <RatioBar label="漏打卡扣款" value={missingAmount} total={view.totalDeduction} color="bg-red-500" />
            <RatioBar label="迟到扣款" value={lateAmount} total={view.totalDeduction} color="bg-orange-500" />
            <RatioBar label="早退扣款" value={earlyAmount} total={view.totalDeduction} color="bg-yellow-500" />
            <RatioBar label="缺勤扣款" value={absenceAmount} total={view.totalDeduction} color="bg-purple-500" />
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
  const s04Summary = data.s04Summary || {}
  const totalDeduction = Number(s04Summary.total_deduction || 0)
  const missingAmount = Number(s04Summary.total_missing_clock_amount || 0)
  const lateAmount = Number(s04Summary.total_late_amount || 0)
  const earlyAmount = Number(s04Summary.total_early_leave_amount || 0)
  const absenceAmount = Number(s04Summary.total_absence_amount || 0)
  const attendanceDeduction = missingAmount + lateAmount + earlyAmount + absenceAmount
  const exceptionRows = data.attendanceDetails
  const exceptionPeople = new Set(exceptionRows.map((item) => String(item.employee_name || '')).filter(Boolean))
  const allAuditedPeople = new Set(data.exceptions.map((item) => String(item.employee_name || '')).filter(Boolean))
  const auditedDays = new Set(data.positionFulfillment.map((item) => String(item.work_date || '')).filter(Boolean)).size
  // 异常记录 = 每条 deductionDetails（即每个员工的扣款汇总）一行，与 MetricCard「异常记录」口径一致
  const exceptionCount = data.exceptions.length
  const scheduleTaskCount = data.positionFulfillment.length
  // 异常率 = 异常记录数 / 排班任务数（与 AiAudit 进度条 / 后端 finalize 同口径）
  const firstExceptionRate = scheduleTaskCount > 0
    ? Number(((exceptionCount / scheduleTaskCount) * 100).toFixed(1))
    : 0

  const exceptionTypeCounts = new Map<string, number>()
  exceptionRows.forEach((item) => {
    const type = String(item.exception_type || '异常')
    exceptionTypeCounts.set(type, (exceptionTypeCounts.get(type) ?? 0) + 1)
  })
  const exceptionRanks = Array.from(exceptionTypeCounts.entries())
    .map(([name, value]) => ({ name, value }))
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
    attendanceDeduction,
    totalDeduction,
    scheduleTaskCount,
    exceptionCount: exceptionRows.length,
    firstExceptionRate,
    exceptionPeopleCount: exceptionPeople.size,
    auditedPeopleCount: allAuditedPeople.size,
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
  if (view.totalDeduction <= 0) suggestions.push('本次审核未产生扣款，建议保留审核记录并归档。')
  if (view.exceptionRanks[0]) suggestions.push(`最高频异常为"${view.exceptionRanks[0].name}"，共 ${view.exceptionRanks[0].value} 次，建议核查合同规则和BI原始记录。`)
  if (view.positionExceptionRanks[0]) suggestions.push(`异常最集中的岗位是"${view.positionExceptionRanks[0].name}"，建议由项目核实排班后重新提交。`)
  if (view.riskyPeople[0]) suggestions.push(`人员异常扣款最高的是"${view.riskyPeople[0].name}"，主要异常为"${view.riskyPeople[0].mainType}"。`)
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
