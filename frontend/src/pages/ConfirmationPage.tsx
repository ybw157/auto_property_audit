import { useEffect, useState } from 'react'
import { request } from '../services/api'

interface ExceptionRecord {
  work_date: string
  position: string
  shift_name: string
  clock_times: string
  exception_type: string
  exception_reason: string
  project_confirmed?: boolean | null
  confirm_note: string
}

interface ConfirmData {
  batch_id: number
  total_exceptions: number
  employees: string[]
  by_employee: Record<string, ExceptionRecord[]>
}

interface Props {
  batchId: number | null
}

export function ConfirmationPage({ batchId }: Props) {
  const [data, setData] = useState<ConfirmData | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedEmployee, setSelectedEmployee] = useState('')
  const [confirmMap, setConfirmMap] = useState<Record<string, boolean>>({})
  const [noteMap, setNoteMap] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [message, setMessage] = useState('')
  const [finalizeResult, setFinalizeResult] = useState<{ confirmed_count: number; total_deduction: number; first_exception_rate: number; confirmed_exception_rate: number; message: string } | null>(null)

  useEffect(() => {
    if (batchId) loadData()
  }, [batchId])

  useEffect(() => {
    if (data && data.employees.length && !selectedEmployee) {
      setSelectedEmployee(data.employees[0])
    }
  }, [data])

  async function loadData() {
    if (!batchId) return
    setLoading(true)
    try {
      const res = await request<ConfirmData>(`/api/v1/results/${batchId}/confirmation-page`)
      setData(res)
      // 初始化确认状态
      const cMap: Record<string, boolean> = {}
      const nMap: Record<string, string> = {}
      for (const [emp, records] of Object.entries(res.by_employee)) {
        for (const r of records) {
          const key = `${emp}|${r.work_date}`
          cMap[key] = r.project_confirmed ?? false
          nMap[key] = r.confirm_note || ''
        }
      }
      setConfirmMap(cMap)
      setNoteMap(nMap)
    } catch {
      setMessage('加载失败')
    }
    setLoading(false)
  }

  function toggleConfirm(emp: string, date: string) {
    const key = `${emp}|${date}`
    setConfirmMap({ ...confirmMap, [key]: !confirmMap[key] })
  }

  function updateNote(emp: string, date: string, note: string) {
    const key = `${emp}|${date}`
    setNoteMap({ ...noteMap, [key]: note })
  }

  function selectAll(emp: string) {
    const records = data?.by_employee[emp] || []
    const updates: Record<string, boolean> = {}
    const allChecked = records.every((r) => confirmMap[`${emp}|${r.work_date}`])
    for (const r of records) {
      updates[`${emp}|${r.work_date}`] = !allChecked
    }
    setConfirmMap({ ...confirmMap, ...updates })
  }

  async function saveConfirm() {
    if (!batchId || !data) return
    setSaving(true)
    setMessage('')
    const records: Array<{ employee_name: string; work_date: string; confirmed: boolean; confirm_note: string }> = []
    for (const [emp, recs] of Object.entries(data.by_employee)) {
      for (const r of recs) {
        const key = `${emp}|${r.work_date}`
        records.push({
          employee_name: emp,
          work_date: r.work_date,
          confirmed: confirmMap[key] ?? false,
          confirm_note: noteMap[key] || '',
        })
      }
    }
    try {
      const confirmRes = await request<{ updated_count: number; message: string }>(`/api/v1/results/${batchId}/confirm-exceptions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed_records: records, confirmed_by: '项目确认' }),
      })
      setMessage(confirmRes.message || '确认已提交')
      await loadData()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '提交失败')
    }
    setSaving(false)
  }

  async function generateReport() {
    if (!batchId) return
    setGenerating(true)
    setMessage('')
    try {
      const finalizeRes = await request<{ confirmed_count: number; skipped_count: number; total_deduction: number; first_exception_rate: number; confirmed_exception_rate: number; message: string }>(`/api/v1/results/${batchId}/finalize`, {
        method: 'POST',
      })
      setFinalizeResult({ confirmed_count: finalizeRes.confirmed_count, total_deduction: finalizeRes.total_deduction, first_exception_rate: finalizeRes.first_exception_rate, confirmed_exception_rate: finalizeRes.confirmed_exception_rate, message: finalizeRes.message })
      setMessage(finalizeRes.message)
      await loadData()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '报告生成失败')
    }
    setGenerating(false)
  }

  if (!batchId) return <div className="text-slate-500">请先选择审核批次</div>
  if (loading) return <div className="text-slate-500">加载中...</div>
  if (!data) return <div className="text-slate-500">暂无数据</div>
  if (data.total_exceptions === 0) return <div className="card p-8 text-center text-slate-500">本次审核无异常记录</div>

  const currentRecords = data.by_employee[selectedEmployee] || []
  const confirmedCount = Object.values(confirmMap).filter(Boolean).length

  return (
    <div className="space-y-4">
      {/* 顶部信息栏 */}
      <div className="card flex items-center justify-between p-5">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">考勤异常确认表</h2>
          <p className="mt-1 text-sm text-slate-500">
            批次 #{batchId} | 共 {data.total_exceptions} 条异常 | 已确认 {confirmedCount} 条
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            className="btn-secondary"
            disabled={saving || generating}
            onClick={saveConfirm}
          >
            {saving ? '提交中...' : '提交确认'}
          </button>
          <button
            className="btn-primary"
            disabled={saving || generating}
            onClick={generateReport}
          >
            {generating ? '生成报告中...' : '生成扣款报告'}
          </button>
        </div>
      </div>

      {message && <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</div>}

      {/* 操作说明 */}
      <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-700">
        <p className="font-medium">操作说明：</p>
        <p className="mt-1">1. 勾选异常记录表示项目确认该异常属实</p>
        <p>2. 未勾选的记录表示项目有异议，可在备注栏说明原因</p>
        <p>3. 点击"提交确认"保存确认状态</p>
        <p>4. 点击"生成扣款报告"按确认结果重新计算扣款金额并生成AI审核汇总与扣款PDF报告</p>
        <p>5. 生成完成后请到"审核结果"页面查看扣款明细并点击"确认最终版"锁定</p>
        <p>6. 可多次修改并重新提交、重新生成</p>
      </div>

      {/* 扣款生成结果 */}
      {finalizeResult && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-slate-900">扣款报告已生成</h3>
          <div className="mt-3 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-lg bg-slate-50 p-4 text-center">
              <div className="text-2xl font-bold text-slate-900">{finalizeResult.confirmed_count}</div>
              <div className="text-sm text-slate-500">确认异常条数</div>
            </div>
            <div className="rounded-lg bg-red-50 p-4 text-center">
              <div className="text-2xl font-bold text-red-600">{finalizeResult.total_deduction}</div>
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
          <p className="mt-2 text-xs text-slate-400">请到"审核结果"页面查看扣款明细并点击"确认最终版"锁定</p>
        </div>
      )}

      <div className="flex gap-4">
        {/* 左侧员工列表 */}
        <div className="w-48 shrink-0">
          <div className="card p-3">
            <h3 className="mb-3 px-2 text-sm font-medium text-slate-700">员工列表</h3>
            <div className="space-y-1">
              {data.employees.map((emp) => {
                const empRecords = data.by_employee[emp] || []
                const empConfirmed = empRecords.filter((r) => confirmMap[`${emp}|${r.work_date}`]).length
                return (
                  <button
                    key={emp}
                    className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                      selectedEmployee === emp ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50'
                    }`}
                    onClick={() => setSelectedEmployee(emp)}
                  >
                    <span>{emp}</span>
                    <span className="text-xs text-slate-400">{empConfirmed}/{empRecords.length}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* 右侧异常记录表格 */}
        <div className="flex-1">
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
              <h3 className="text-sm font-medium text-slate-700">
                {selectedEmployee} 的异常记录（{currentRecords.length}条）
              </h3>
              <button
                className="text-xs text-brand-600 underline"
                onClick={() => selectAll(selectedEmployee)}
              >
                全选/取消全选
              </button>
            </div>
            <div className="overflow-auto">
              <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="w-12 px-4 py-3 text-center font-medium text-slate-600">确认</th>
                    <th className="w-28 px-4 py-3 text-left font-medium text-slate-600">日期</th>
                    <th className="w-24 px-4 py-3 text-left font-medium text-slate-600">岗位</th>
                    <th className="w-32 px-4 py-3 text-left font-medium text-slate-600">班次</th>
                    <th className="w-40 px-4 py-3 text-left font-medium text-slate-600">打卡记录</th>
                    <th className="w-28 px-4 py-3 text-left font-medium text-slate-600">异常类型</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">异常说明</th>
                    <th className="w-32 px-4 py-3 text-left font-medium text-slate-600">备注</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {currentRecords.map((r, idx) => {
                    const key = `${selectedEmployee}|${r.work_date}`
                    const checked = confirmMap[key] ?? false
                    return (
                      <tr key={idx} className={checked ? 'bg-green-50' : 'hover:bg-slate-50'}>
                        <td className="px-4 py-3 text-center">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleConfirm(selectedEmployee, r.work_date)}
                            className="h-5 w-5 cursor-pointer rounded border-slate-300 text-brand-600"
                          />
                        </td>
                        <td className="px-4 py-3 text-slate-700">{r.work_date}</td>
                        <td className="px-4 py-3 text-slate-700">{r.position}</td>
                        <td className="px-4 py-3 text-slate-700">{r.shift_name}</td>
                        <td className="px-4 py-3 text-slate-600">{r.clock_times || '-'}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-block rounded-full px-2 py-1 text-xs font-medium ${
                            r.exception_type.includes('缺勤') ? 'bg-red-100 text-red-700' :
                            r.exception_type.includes('疑似漏打卡') ? 'bg-amber-100 text-amber-700' :
                            r.exception_type.includes('迟到') ? 'bg-orange-100 text-orange-700' :
                            r.exception_type.includes('早退') ? 'bg-orange-100 text-orange-700' :
                            r.exception_type.includes('打卡时间异常') ? 'bg-purple-100 text-purple-700' :
                            'bg-slate-100 text-slate-700'
                          }`}>
                            {r.exception_type}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{r.exception_reason}</td>
                        <td className="px-4 py-3">
                          <input
                            type="text"
                            value={noteMap[key] || ''}
                            onChange={(e) => updateNote(selectedEmployee, r.work_date, e.target.value)}
                            placeholder="备注..."
                            className="w-full rounded border border-slate-200 px-2 py-1 text-xs"
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
