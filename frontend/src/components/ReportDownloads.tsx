import { useEffect, useState } from 'react'
import { API_BASE_URL, request, getToken } from '../services/api'
import type { AuditContext } from '../types'

type Report = {
  id: number
  report_type: string
  file_format: string
  created_at: string
}

export function ReportDownloads({ auditContext }: { auditContext: AuditContext | null }) {
  const [reports, setReports] = useState<Report[]>([])
  const [message, setMessage] = useState('')
  const [loadingAttendance, setLoadingAttendance] = useState(false)
  const [loadingDeduction, setLoadingDeduction] = useState(false) // 控制"生成扣款报告"= 汇总报告


  async function loadReports() {
    if (!auditContext) return
    const rows = await request<Report[]>(
      `/api/v2/reports?project_name=${encodeURIComponent(auditContext.project_name)}&audit_month=${encodeURIComponent(auditContext.audit_month)}&business_type=${encodeURIComponent(auditContext.business_type)}`
    )
    setReports(rows)
  }

  useEffect(() => {
    loadReports().catch(() => setReports([]))
  }, [auditContext])

  async function generate(reportType: 'attendance' | 'summary') {
    if (!auditContext) return
    const setLoading = reportType === 'attendance' ? setLoadingAttendance : setLoadingDeduction
    setLoading(true)
    setMessage('')
    try {
      await request(
        `/api/v2/reports/generate?project_name=${encodeURIComponent(auditContext.project_name)}&business_type=${encodeURIComponent(auditContext.business_type)}&audit_month=${encodeURIComponent(auditContext.audit_month)}&report_type=${reportType}`,
        { method: 'POST' }
      )
      await loadReports()
      setMessage(reportType === 'attendance' ? '考勤明细报告已生成，可以下载。' : '扣款报告已生成，可以下载。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '报告生成失败')
    } finally {
      setLoading(false)
    }
  }

  const pdfReports = reports.filter(
    (item) => item.file_format === 'pdf'
  )

  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">报告下载</h2>
          <p className="mt-2 text-sm text-slate-500">
            审核完成后生成考勤明细 PDF；确认异常后生成 AI 审核汇总与扣款报告。
          </p>
        </div>
        <div className="flex gap-3">
          <button
            className="btn-primary"
            disabled={loadingAttendance || loadingDeduction}
            onClick={() => generate('attendance')}
          >
            {loadingAttendance ? '生成中...' : '生成考勤明细'}
          </button>
          <button
            className="rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            disabled={loadingAttendance || loadingDeduction}
            onClick={() => generate('summary')}
          >
            {loadingDeduction ? '生成中...' : '生成扣款报告'}
          </button>
        </div>
      </div>
      {message && <p className="mt-3 text-sm text-slate-500">{message}</p>}
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {pdfReports.map((item) => (
          <ReportCard key={item.id} item={item} />
        ))}
        {!pdfReports.length && (
          <div className="rounded-2xl border border-dashed border-slate-200 p-5 text-sm text-slate-500">
            暂无已生成报告，请先点击"生成考勤明细"。
          </div>
        )}
      </div>
    </div>
  )
}

function ReportCard({ item }: { item: Report }) {
  const [downloading, setDownloading] = useState(false)

  async function handleDownload() {
    setDownloading(true)
    try {
      const token = getToken()
      const res = await fetch(`${API_BASE_URL}/api/v2/reports/${item.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error('下载失败')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${item.report_type}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('下载失败，请重试')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-slate-900">{item.report_type}</div>
          <div className="mt-1 text-xs text-slate-400">{item.created_at}</div>
        </div>
        <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">
          PDF
        </span>
      </div>
      <button
        className="mt-4 inline-flex w-full items-center justify-center rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        onClick={handleDownload}
        disabled={downloading}
      >
        {downloading ? '下载中...' : '下载 PDF'}
      </button>
    </div>
  )
}
