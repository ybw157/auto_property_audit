import { ReportDownloads } from '../components/ReportDownloads'

export function PdfReports({ batchId }: { batchId: number | null }) {
  if (!batchId) return <div className="card p-8 text-center text-sm text-slate-500">请先完成一次审核</div>
  return (
    <ReportDownloads batchId={batchId} />
  )
}
