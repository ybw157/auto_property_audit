import { useEffect, useState } from 'react'
import { API_BASE_URL, request } from '../services/api'

type Report = {
  id: number
  report_type: string
  file_format: string
  created_at: string
}

export function ReportDownloads({ batchId }: { batchId: number | null }) {
  const [reports, setReports] = useState<Report[]>([])
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  async function loadReports() {
    if (!batchId) return
    const rows = await request<Report[]>(`/api/v1/reports/${batchId}`)
    setReports(rows)
  }

  useEffect(() => {
    loadReports().catch(() => setReports([]))
  }, [batchId])

  async function generate() {
    if (!batchId) return
    setLoading(true)
    setMessage('')
    try {
      await request(`/api/v1/reports/${batchId}/pdf`, { method: 'POST' })
      await loadReports()
      setMessage('保洁考勤明细已生成，可以下载。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '报告生成失败')
    } finally {
      setLoading(false)
    }
  }

  const pdfReports = reports.filter((item) => item.file_format === 'pdf' && (item.report_type.endsWith('考勤明细') || item.report_type.endsWith('AI审核汇总与扣款报告')))

  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">报告下载</h2>
          <p className="mt-2 text-sm text-slate-500">第一次审核生成考勤明细PDF（自动识别保安/保洁）；项目确认异常后生成AI审核汇总与扣款报告（合并为一份PDF）。</p>
        </div>
        <div className="flex gap-3">
          <button className="btn-primary" disabled={loading} onClick={generate}>{loading ? '生成中...' : '生成考勤明细'}</button>
        </div>
      </div>
      {message && <p className="mt-3 text-sm text-slate-500">{message}</p>}
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {pdfReports.map((item) => (
          <ReportCard key={item.id} item={item} />
        ))}
        {!reports.length && <div className="rounded-2xl border border-dashed border-slate-200 p-5 text-sm text-slate-500">暂无已生成报告，请先点击"生成保洁考勤明细"。</div>}
      </div>
    </div>
  )
}

function ReportCard({ item }: { item: Report }) {
  const isPdf = item.file_format === 'pdf'
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-slate-900">{item.report_type}</div>
          <div className="mt-1 text-xs text-slate-400">{item.created_at}</div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${isPdf ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}>
          {item.file_format.toUpperCase()}
        </span>
      </div>
      <a
        className="mt-4 inline-flex w-full items-center justify-center rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        href={`${API_BASE_URL}/api/v1/reports/${item.id}/download`}
        target="_blank"
        rel="noreferrer"
      >
        下载{isPdf ? 'PDF' : 'Excel'}
      </a>
    </div>
  )
}
