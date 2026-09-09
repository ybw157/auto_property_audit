import { ReportDownloads } from '../components/ReportDownloads'
import { useAuditContext } from '../hooks/useAuditContext'

export function PdfReports() {
  const { auditContext } = useAuditContext()
  if (!auditContext) return <div className="card p-8 text-center text-sm text-slate-500">请先完成一次审核</div>
  return (
    <ReportDownloads auditContext={auditContext} />
  )
}
