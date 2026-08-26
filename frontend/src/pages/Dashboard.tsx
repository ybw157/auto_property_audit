import { useEffect, useState } from 'react'
import { request } from '../services/api'

type Detail = {
  batch_id: number
  project_name: string
  business_type: string
  audit_month: string
  status: string
  schedule_count: number
  shortage_count: number
  exception_count: number
  deduction_amount: number
  exception_rate: number
  finished_at: string
  confirmed_at: string
}

type Summary = {
  monthly_project_count: number
  shortage_count: number
  exception_count: number
  deduction_amount: number
  completion_rate: number
  details?: Detail[]
  role?: string
  project_name?: string
}

type Props = {
  userRole?: string
  projectName?: string
}

export function Dashboard({ userRole = '集团管理员', projectName = '' }: Props) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const isProjectAccount = userRole === '项目账号'

  useEffect(() => {
    request<Summary>('/api/v1/dashboard/summary').then(setSummary).catch(() => setSummary(null))
  }, [userRole, projectName])

  // 项目账号：展示本项目确认的最终版明细
  if (isProjectAccount) {
    const details = summary?.details ?? []
    const cards = [
      ['已确认最终版', summary?.monthly_project_count ?? 0],
      ['排班任务数', details.reduce((s, d) => s + d.schedule_count, 0)],
      ['异常人数', summary?.exception_count ?? 0],
      ['扣款金额', `¥${summary?.deduction_amount ?? 0}`],
    ]
    return (
      <div className="space-y-6">
        <div className="card p-6">
          <h2 className="text-lg font-semibold">{projectName} - 已确认最终版</h2>
          <p className="mt-2 text-sm text-slate-500">
            以下为本项目已由集团确认的最终版审核结果。过程版本（V1、V2等）不计入统计。
          </p>
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
                  <th className="px-4 py-2 text-center">排班数</th>
                  <th className="px-4 py-2 text-center">异常人数</th>
                  <th className="px-4 py-2 text-center">异常率</th>
                  <th className="px-4 py-2 text-center">扣款金额</th>
                  <th className="px-4 py-2 text-center">状态</th>
                  <th className="px-4 py-2 text-left">确认时间</th>
                </tr>
              </thead>
              <tbody>
                {details.map((d) => (
                  <tr key={d.batch_id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-slate-800">{d.audit_month || '-'}</td>
                    <td className="px-4 py-2 text-slate-600">{d.business_type || '-'}</td>
                    <td className="px-4 py-2 text-center text-slate-600">{d.schedule_count}</td>
                    <td className="px-4 py-2 text-center text-slate-600">{d.exception_count}</td>
                    <td className="px-4 py-2 text-center">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${d.exception_rate > 5 ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                        {d.exception_rate}%
                      </span>
                    </td>
                    <td className="px-4 py-2 text-center text-slate-600">¥{d.deduction_amount}</td>
                    <td className="px-4 py-2 text-center">
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        {d.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{d.confirmed_at || d.finished_at || '-'}</td>
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

  // 集团管理员：保持原有汇总视图
  const cards = [
    ['已确认最终版', summary?.monthly_project_count ?? 0],
    ['过程版本不计入', '仅统计最终版'],
    ['异常人数', summary?.exception_count ?? 0],
    ['扣款金额', `¥${summary?.deduction_amount ?? 0}`],
    ['审核完成率', `${summary?.completion_rate ?? 0}%`],
  ]
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-5 gap-4">
        {cards.map(([label, value]) => (
          <div key={label} className="card p-5">
            <div className="text-sm text-slate-500">{label}</div>
            <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-6">
        <div className="card p-6">
          <h2 className="text-base font-semibold">审核概览</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">首页只汇总集团已确认的最终版数据。项目重新审核产生的V1、V2等过程版本，不计入Dashboard汇总。</p>
        </div>
        <div className="card p-6">
          <h2 className="text-base font-semibold">风险提示</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">如排班与BI不一致，系统只提示项目核实排班，不自动判断顶岗、调班或修正排班。</p>
        </div>
      </div>
      {summary?.details && summary.details.length > 0 && (
        <div className="card p-6">
          <h3 className="text-base font-semibold">已确认最终版明细</h3>
          <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-4 py-2 text-left">项目</th>
                  <th className="px-4 py-2 text-left">月份</th>
                  <th className="px-4 py-2 text-left">业态</th>
                  <th className="px-4 py-2 text-center">排班数</th>
                  <th className="px-4 py-2 text-center">异常</th>
                  <th className="px-4 py-2 text-center">异常率</th>
                  <th className="px-4 py-2 text-center">扣款</th>
                  <th className="px-4 py-2 text-left">确认时间</th>
                </tr>
              </thead>
              <tbody>
                {summary.details.map((d) => (
                  <tr key={d.batch_id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-slate-800">{d.project_name}</td>
                    <td className="px-4 py-2 text-slate-600">{d.audit_month || '-'}</td>
                    <td className="px-4 py-2 text-slate-600">{d.business_type || '-'}</td>
                    <td className="px-4 py-2 text-center text-slate-600">{d.schedule_count}</td>
                    <td className="px-4 py-2 text-center text-slate-600">{d.exception_count}</td>
                    <td className="px-4 py-2 text-center">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${d.exception_rate > 5 ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                        {d.exception_rate}%
                      </span>
                    </td>
                    <td className="px-4 py-2 text-center text-slate-600">¥{d.deduction_amount}</td>
                    <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{d.confirmed_at || d.finished_at || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
