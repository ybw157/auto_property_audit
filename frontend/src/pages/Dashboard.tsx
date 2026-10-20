import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ResponsiveContainer,
  Tooltip,
  Legend,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import { request } from '../services/api'
import { useAuth } from '../hooks/useAuth'

// ---------- 类型定义（与后端 dashboard_service 返回结构对齐） ----------

type GroupKpi = {
  total_projects: number
  /** 有审核记录的项目（已确认 + 待确认） */
  audited_projects: number
  /** status 全部为「已确认」的项目数 */
  confirmed_projects: number
  /** 仍有「已审核」未确认的项目数 */
  pending_confirm_projects: number
  /** 完全没跑审核的项目数 */
  pending_projects: number
  /** 已确认 / 项目总数 */
  completion_rate: number
  /** 已审核（含待确认）/ 项目总数 */
  audit_coverage_rate: number
  /** 已确认 / 已审核，反映确认环节转化 */
  confirm_rate: number
  total_deduction: number
  avg_exception_rate: number
  over_threshold_projects: number
  prev_month: string
  prev_deduction: number
  prev_exception_rate: number
  deduction_mom_pct: number | null
  rate_mom_pt: number | null
}

type ProjectUsage = {
  project_name: string
  business_types: string
  service_types: string
  audit_status: string
  schedule_uploaded: boolean
  exception_count: number
  exception_rate: number
  deduction_amount: number
  last_audit_at: string
}

type ExceptionTypeItem = { type: string; count: number }
type TrendItem = { month: string; exception_rate: number; deduction: number }
type RiskProject = {
  project_name: string
  exception_rate: number
  audit_status: string
  reason: string
}
type BusinessTypeStat = {
  business_type: string
  project_count: number
  exception_rate: number
  deduction_amount: number
}
/** 扣款归因：某类异常造成的金额、占比、次数与单次成本 */
type DeductionItem = {
  type: string
  amount: number
  share_pct: number
  count: number
  unit_cost: number
}
/** 不产生扣款、但需要关注的预警项 */
type WarningStats = {
  mid_clock_issue_count: number
  overtime_warning_count: number
  affected_employees: number
}
type SupplierItem = {
  supplier: string
  deduction: number
  share_pct: number
  project_count: number
  projects: string[]
}

type GroupSummary = {
  audit_month: string
  // 项目总数口径：用户表中非管理员账号绑定的项目数
  available_months: string[]
  exception_rate_threshold: number
  generated_at: string
  kpi: GroupKpi
  project_usage: ProjectUsage[]
  exception_type_distribution: ExceptionTypeItem[]
  deduction_breakdown: DeductionItem[]
  warning_stats: WarningStats
  supplier_ranking: SupplierItem[]
  monthly_trend: TrendItem[]
  risk_projects: RiskProject[]
  business_type_stats: BusinessTypeStat[]
}

/** 每类异常的整改动作指向（文案属展示层，放在前端维护） */
const DEDUCTION_ACTION: Record<string, string> = {
  缺勤: '供应商未派满岗 → 约谈并按合同索赔',
  漏打卡: '补卡流程未闭环 → 限期补卡即可追回',
  早退: '频次高、金额小 → 现场纪律日常管控',
  迟到: '频次高、金额小 → 现场纪律日常管控',
}

type ProjectDetail = {
  project_name: string
  business_type: string
  service_type: string
  audit_month: string
  status: string
  schedule_count: number
  exception_count: number
  exception_rate: number
  deduction_amount: number
  confirmed_at: string
}

type ProjectSummary = {
  project_name: string
  kpi: {
    confirmed_count: number
    schedule_count: number
    exception_count: number
    deduction_amount: number
  }
  details: ProjectDetail[]
}

// ---------- 常量 ----------

const BUSINESS_COLORS = ['#6366f1', '#0ea5e9', '#8b5cf6', '#f59e0b', '#10b981']

function formatMonth(m: string) {
  return m.length === 6 ? `${m.slice(0, 4)}-${m.slice(4)}` : m
}

function fmtMoney(n: number) {
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtMoneyShort(n: number) {
  if (n >= 10000) return `¥${(n / 10000).toFixed(1)}万`
  return fmtMoney(n)
}

// ---------- 项目账号视图 ----------

function ProjectDashboard() {
  const { projectName } = useAuth()
  const [summary, setSummary] = useState<ProjectSummary | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    request<ProjectSummary>('/api/v2/dashboard/project-summary')
      .then(setSummary)
      .catch((e) => setError(e.message || '加载失败'))
  }, [])

  const details = summary?.details ?? []
  const cards: Array<[string, string | number]> = [
    ['已确认最终版', summary?.kpi.confirmed_count ?? 0],
    ['排班任务数', summary?.kpi.schedule_count ?? 0],
    ['异常人数', summary?.kpi.exception_count ?? 0],
    ['扣款金额', fmtMoney(summary?.kpi.deduction_amount ?? 0)],
  ]

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h2 className="text-lg font-semibold">{summary?.project_name || projectName} - 已确认最终版</h2>
        <p className="mt-2 text-sm text-slate-500">
          以下为本项目已由集团确认的最终版审核结果。过程版本（V1、V2等）不计入统计。
        </p>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>
      <div className="grid grid-cols-4 gap-4">
        {cards.map(([label, value]) => (
          <div key={label} className="card p-5">
            <div className="text-sm text-slate-500">{label}</div>
            <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
          </div>
        ))}
      </div>
      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">确认明细</h3>
          <span className="text-xs text-slate-500">共 {details.length} 条</span>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-2 text-left">审核月份</th>
                <th className="px-4 py-2 text-left">业态</th>
                <th className="px-4 py-2 text-left">服务类型</th>
                <th className="px-4 py-2 text-center">排班数</th>
                <th className="px-4 py-2 text-center">异常人数</th>
                <th className="px-4 py-2 text-center">异常率</th>
                <th className="px-4 py-2 text-center">扣款金额</th>
                <th className="px-4 py-2 text-left">确认时间</th>
              </tr>
            </thead>
            <tbody>
              {details.map((d) => (
                <tr key={`${d.business_type}-${d.service_type}-${d.audit_month}`} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-800">{formatMonth(d.audit_month) || '-'}</td>
                  <td className="px-4 py-2 text-slate-600">{d.business_type || '-'}</td>
                  <td className="px-4 py-2 text-slate-600">{d.service_type || '-'}</td>
                  <td className="px-4 py-2 text-center text-slate-600">{d.schedule_count}</td>
                  <td className="px-4 py-2 text-center text-slate-600">{d.exception_count}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${d.exception_rate > 10 ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                      {d.exception_rate}%
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-slate-600">{fmtMoney(d.deduction_amount)}</td>
                  <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{d.confirmed_at || '-'}</td>
                </tr>
              ))}
              {!details.length && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                    暂无已确认的最终版数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ---------- 集团管理员视图（面向集团领导） ----------

function GroupDashboard() {
  const navigate = useNavigate()
  // 空串代表「由后端自动取最近一个有数据的月份」，避免月初打开就是空面板
  const [month, setMonth] = useState('')
  const [summary, setSummary] = useState<GroupSummary | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<'all' | 'pending' | 'confirm' | 'over'>('all')

  useEffect(() => {
    const query = month ? `?audit_month=${month.replace('-', '')}` : ''
    request<GroupSummary>(`/api/v2/dashboard/group-summary${query}`)
      .then((data) => {
        setSummary(data)
        setError('')
      })
      .catch((e) => setError(e.message || '加载失败'))
  }, [month])

  const kpi = summary?.kpi
  const threshold = summary?.exception_rate_threshold ?? 10

  const trendData = useMemo(
    () => (summary?.monthly_trend ?? []).map((t) => ({ ...t, month: formatMonth(t.month) })),
    [summary],
  )

  // 三件事：异常率超标 / 超期未审核 / 扣款 Top3
  const overList = useMemo(() => summary?.risk_projects ?? [], [summary])
  const pendingList = useMemo(
    () => (summary?.project_usage ?? []).filter((p) => p.audit_status === '待审核'),
    [summary],
  )
  const deductionTop = useMemo(
    () =>
      [...(summary?.project_usage ?? [])]
        .filter((p) => p.deduction_amount > 0)
        .sort((a, b) => b.deduction_amount - a.deduction_amount)
        .slice(0, 3),
    [summary],
  )

  const visibleProjects = useMemo(() => {
    const list = summary?.project_usage ?? []
    const filtered =
      filter === 'pending'
        ? list.filter((p) => p.audit_status === '待审核')
        : filter === 'confirm'
          ? list.filter((p) => p.audit_status === '待确认')
          : filter === 'over'
            ? list.filter((p) => p.exception_rate > threshold)
            : list
    return [...filtered]
      .sort((a, b) => b.exception_rate - a.exception_rate || b.deduction_amount - a.deduction_amount)
      .slice(0, 10)
  }, [summary, filter, threshold])

  const monthOptions = useMemo(() => {
    const months = summary?.available_months ?? []
    return months.map((m) => ({ value: `${m.slice(0, 4)}-${m.slice(4)}`, label: `${m.slice(0, 4)}-${m.slice(4)}` }))
  }, [summary])
  const currentMonthValue = month || formatMonth(summary?.audit_month ?? '')

  const drillDown = (p: ProjectUsage) => {
    localStorage.setItem(
      'auditContext',
      JSON.stringify({
        project_name: p.project_name,
        audit_month: summary?.audit_month ?? '',
        business_type: (p.business_types || '').split('、')[0] || '',
        service_type: (p.service_types || '').split('、')[0] || '',
      }),
    )
    navigate('/results')
  }

  const momText = () => {
    if (!kpi) return ''
    const parts: string[] = []
    if (kpi.prev_deduction > 0 && kpi.deduction_mom_pct !== null) {
      const up = kpi.deduction_mom_pct > 0
      parts.push(`扣款较上月 ${up ? '+' : ''}${kpi.deduction_mom_pct}%`)
    } else {
      parts.push('上月无审核数据，暂不可比')
    }
    if (kpi.rate_mom_pt !== null && kpi.prev_deduction > 0) {
      parts.push(`异常率 ${kpi.rate_mom_pt > 0 ? '+' : ''}${kpi.rate_mom_pt}pt`)
    }
    parts.push(
      `已确认 ${kpi.confirmed_projects ?? 0} 个 · 待确认 ${kpi.pending_confirm_projects ?? 0} 个 · 未开始 ${kpi.pending_projects ?? 0} 个`,
    )
    if (summary?.generated_at) parts.push(`数据更新于 ${summary.generated_at}`)
    return parts.join(' · ')
  }

  const kpiCards: Array<{ label: string; value: string; note: string; tone: string }> = [
    {
      label: '项目总数',
      value: `${kpi?.total_projects ?? 0}`,
      note: `待确认 ${kpi?.pending_confirm_projects ?? 0} · 未开始 ${kpi?.pending_projects ?? 0}`,
      tone: 'text-slate-950',
    },
    {
      label: '审核完成率',
      value: `${kpi?.completion_rate ?? 0}%`,
      note: `已确认 ${kpi?.confirmed_projects ?? 0} 个 · 覆盖率 ${kpi?.audit_coverage_rate ?? 0}%`,
      tone: (kpi?.completion_rate ?? 0) >= 90 ? 'text-emerald-600' : 'text-amber-600',
    },
    {
      label: '平均异常率',
      value: `${kpi?.avg_exception_rate ?? 0}%`,
      note: `预警线 ${threshold}%`,
      tone: (kpi?.avg_exception_rate ?? 0) > threshold ? 'text-red-600' : 'text-emerald-600',
    },
    {
      label: '异常率超标项目',
      value: `${kpi?.over_threshold_projects ?? 0}`,
      note: `异常率 > ${threshold}%`,
      tone: (kpi?.over_threshold_projects ?? 0) > 0 ? 'text-red-600' : 'text-slate-950',
    },
  ]

  return (
    <div className="space-y-6">
      {/* 结论条 */}
      <div className="card border-l-4 border-l-brand-600 p-6">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">
              {formatMonth(summary?.audit_month ?? '') || '—'}：{kpi?.total_projects ?? 0} 个项目中{' '}
              {kpi?.audited_projects ?? 0} 个完成审核，扣款 {fmtMoney(kpi?.total_deduction ?? 0)}，
              平均异常率 {kpi?.avg_exception_rate ?? 0}%
            </h2>
            <p className="mt-2 text-sm text-slate-500">{momText()}</p>
          </div>
          <label className="flex flex-shrink-0 items-center gap-2 text-sm text-slate-600">
            审核月份
            {monthOptions.length > 0 ? (
              <select
                value={currentMonthValue}
                onChange={(e) => setMonth(e.target.value)}
                className="rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                {monthOptions.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            ) : (
              <input
                type="month"
                value={currentMonthValue}
                onChange={(e) => e.target.value && setMonth(e.target.value)}
                className="rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-800 focus:border-brand-500 focus:outline-none"
              />
            )}
          </label>
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      {/* KPI 卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {kpiCards.map((c) => (
          <div key={c.label} className="card p-5">
            <div className="text-sm text-slate-500">{c.label}</div>
            <div className={`mt-3 text-3xl font-semibold ${c.tone}`}>{c.value}</div>
            <div className="mt-2 text-xs text-slate-400">{c.note}</div>
          </div>
        ))}
      </div>

      {/* 本月需要关注的三件事 */}
      <div>
        <h3 className="mb-3 text-base font-semibold">本月需要关注的三件事</h3>
        <div className="grid grid-cols-3 gap-4">
          <div className="card border-red-100 p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-800">异常率超标</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${overList.length ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                {overList.length} 个
              </span>
            </div>
            <div className="mt-3 space-y-1.5 text-sm text-slate-600">
              {overList.length ? (
                overList.slice(0, 3).map((r) => (
                  <div key={r.project_name} className="flex items-center justify-between">
                    <span>{r.project_name}</span>
                    <span className="text-red-600">{r.exception_rate}%</span>
                  </div>
                ))
              ) : (
                <p className="text-slate-500">本月无项目异常率超过 {threshold}%</p>
              )}
            </div>
          </div>

          <div className="card border-amber-100 p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-800">超期未审核</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pendingList.length ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>
                {pendingList.length} 个
              </span>
            </div>
            <div className="mt-3 space-y-1.5 text-sm text-slate-600">
              {pendingList.length ? (
                <>
                  {pendingList.slice(0, 3).map((p) => (
                    <div key={p.project_name}>{p.project_name}</div>
                  ))}
                  <p className="pt-1 text-xs text-slate-400">需督促各项目本月内完成审核</p>
                </>
              ) : (
                <p className="text-slate-500">全部项目已完成本月审核</p>
              )}
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-800">扣款金额 Top3</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                {fmtMoneyShort(kpi?.total_deduction ?? 0)}
              </span>
            </div>
            <div className="mt-3 space-y-1.5 text-sm text-slate-600">
              {deductionTop.length ? (
                deductionTop.map((p) => (
                  <div key={p.project_name} className="flex items-center justify-between">
                    <span>{p.project_name}</span>
                    <span>{fmtMoney(p.deduction_amount)}</span>
                  </div>
                ))
              ) : (
                <p className="text-slate-500">本月暂无扣款</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 趋势 + 业态对比 */}
      <div className="grid grid-cols-5 gap-4">
        <div className="card col-span-3 p-6">
          <h3 className="text-base font-semibold">近 6 个月趋势</h3>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={trendData} margin={{ top: 10, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="month" tick={{ fontSize: 12, fill: '#64748b' }} />
                <YAxis yAxisId="left" tick={{ fontSize: 12, fill: '#64748b' }} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12, fill: '#64748b' }} unit="%" />
                <Tooltip />
                <Legend />
                <Bar yAxisId="left" dataKey="deduction" name="扣款金额(元)" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={38} />
                <Line yAxisId="right" type="monotone" dataKey="exception_rate" name="异常率" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card col-span-2 p-6">
          <h3 className="text-base font-semibold">业态对比</h3>
          <div className="mt-5 space-y-4">
            {(summary?.business_type_stats ?? []).length ? (
              summary!.business_type_stats.map((b, i) => {
                const over = b.exception_rate > threshold
                return (
                  <div key={b.business_type}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-700">{b.business_type}</span>
                      <span className={over ? 'text-red-600' : 'text-slate-600'}>
                        {b.exception_rate}% · {fmtMoneyShort(b.deduction_amount)}
                      </span>
                    </div>
                    <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
                      <div
                        className="h-2 rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(b.exception_rate * 5, 3))}%`,
                          background: over ? '#ef4444' : BUSINESS_COLORS[i % BUSINESS_COLORS.length],
                        }}
                      />
                    </div>
                    <div className="mt-1 text-xs text-slate-400">{b.project_count} 个项目</div>
                  </div>
                )
              })
            ) : (
              <p className="text-sm text-slate-400">当月暂无业态数据</p>
            )}
          </div>
        </div>
      </div>

      {/* 项目明细：默认异常率 Top10 */}
      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">项目明细</h3>
          <div className="flex gap-2">
            <button
              onClick={() => setFilter('all')}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${filter === 'all' ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              全部 {kpi?.total_projects ?? 0}
            </button>
            <button
              onClick={() => setFilter('pending')}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${filter === 'pending' ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              待审核 {kpi?.pending_projects ?? 0}
            </button>
            <button
              onClick={() => setFilter('confirm')}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${filter === 'confirm' ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              待确认 {kpi?.pending_confirm_projects ?? 0}
            </button>
            <button
              onClick={() => setFilter('over')}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition ${filter === 'over' ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              异常超标 {kpi?.over_threshold_projects ?? 0}
            </button>
          </div>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-2 text-left">项目</th>
                <th className="px-4 py-2 text-left">业态</th>
                <th className="px-4 py-2 text-center">状态</th>
                <th className="px-4 py-2 text-center">异常人数</th>
                <th className="px-4 py-2 text-center">异常率</th>
                <th className="px-4 py-2 text-center">扣款金额</th>
                <th className="px-4 py-2 text-left">最近审核时间</th>
              </tr>
            </thead>
            <tbody>
              {visibleProjects.map((p) => (
                <tr key={p.project_name} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <button onClick={() => drillDown(p)} className="font-medium text-brand-700 hover:underline">
                      {p.project_name}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{p.business_types}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      p.audit_status === '已确认'
                        ? 'bg-emerald-100 text-emerald-700'
                        : p.audit_status === '待确认'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-slate-100 text-slate-500'
                    }`}>
                      {p.audit_status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-slate-600">{p.exception_count}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${p.exception_rate > threshold ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                      {p.exception_rate}%
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-slate-600">{fmtMoney(p.deduction_amount)}</td>
                  <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{p.last_audit_at}</td>
                </tr>
              ))}
              {!visibleProjects.length && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    当前筛选下暂无项目
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-400">
          默认按异常率降序展示前 10 个项目，点击项目名可下钻查看该项目的审核结果
        </p>
      </div>

      {/* 扣款归因 + 供应商追责 */}
      {summary && summary.deduction_breakdown.length > 0 && (
        <div className="grid grid-cols-5 gap-4">
          <div className="card col-span-3 p-6">
            <h3 className="text-base font-semibold">扣款归因与整改优先级</h3>
            <p className="mt-1 text-sm text-slate-500">
              本月扣款 {fmtMoney(kpi?.total_deduction ?? 0)}，其中
              <span className="font-medium text-slate-800">
                {summary.deduction_breakdown[0].type}占 {summary.deduction_breakdown[0].share_pct}%
              </span>
              ，是第一大损失来源
            </p>
            <div className="mt-4 space-y-3">
              {summary.deduction_breakdown.map((b, i) => (
                <div key={b.type}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-700">
                      {b.type}
                      <span className="ml-2 text-xs text-slate-400">
                        {b.count} 次 · {fmtMoney(b.unit_cost)}/次
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">{b.share_pct}%</span>
                      <span className="w-20 text-right font-medium text-slate-900">
                        {fmtMoney(b.amount)}
                      </span>
                    </span>
                  </div>
                  <div className="mt-1.5 h-2 w-full rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full"
                      style={{
                        width: `${Math.max(b.share_pct, 1.5)}%`,
                        background: i === 0 ? '#ef4444' : i === 1 ? '#f59e0b' : '#94a3b8',
                      }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{DEDUCTION_ACTION[b.type] ?? '—'}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-100 pt-3 text-xs text-slate-500">
              <span>涉及员工 {summary.warning_stats.affected_employees} 人</span>
              <span>中间卡异常 {summary.warning_stats.mid_clock_issue_count} 次（预警，不扣款）</span>
              <span
                className={summary.warning_stats.overtime_warning_count > 0 ? 'text-red-600' : ''}
              >
                加班预警 {summary.warning_stats.overtime_warning_count} 次
              </span>
            </div>
          </div>

          <div className="card col-span-2 p-6">
            <h3 className="text-base font-semibold">供应商扣款排行</h3>
            <p className="mt-1 text-sm text-slate-500">按扣款金额降序，可直接据此追责</p>
            <div className="mt-4 space-y-3">
              {summary.supplier_ranking.map((s, i) => (
                <div key={s.supplier}>
                  <div className="flex items-start justify-between gap-2 text-sm">
                    <span className="text-slate-700">
                      <span className="mr-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-slate-100 text-[10px] text-slate-500">
                        {i + 1}
                      </span>
                      {s.supplier}
                    </span>
                    <span className="flex-shrink-0 font-medium text-slate-900">
                      {fmtMoney(s.deduction)}
                    </span>
                  </div>
                  <div className="mt-1.5 h-2 w-full rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full"
                      style={{
                        width: `${Math.max(s.share_pct, 1.5)}%`,
                        background: i === 0 ? '#ef4444' : '#f59e0b',
                      }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    占 {s.share_pct}% · {s.project_count} 个项目
                  </p>
                </div>
              ))}
              {!summary.supplier_ranking.length && (
                <p className="text-sm text-slate-400">当月暂无供应商扣款数据</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function Dashboard() {
  const { role } = useAuth()
  return role === 'project_user' ? <ProjectDashboard /> : <GroupDashboard />
}
