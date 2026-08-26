type Props = {
  rows: Record<string, unknown>[]
  emptyText?: string
  columns?: string[]
  labels?: Record<string, string>
  getRowClassName?: (row: Record<string, unknown>) => string
}

export function DataTable({ rows, emptyText = '暂无数据', columns, labels = {}, getRowClassName }: Props) {
  if (!rows.length) return <div className="card p-8 text-center text-sm text-slate-500">{emptyText}</div>
  const headers = (columns?.length ? columns : Object.keys(rows[0])).filter((key) => key in rows[0]).slice(0, 12)
  return (
    <div className="card overflow-hidden">
      <div className="overflow-auto">
        <table className="min-w-full table-fixed divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              {headers.map((header) => <th key={header} className="min-w-28 px-4 py-3 text-left font-medium text-slate-600 break-words">{labels[header] ?? header}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row, idx) => (
              <tr key={idx} className={`${getRowClassName?.(row) ?? 'hover:bg-slate-50'}`}>
                {headers.map((header) => <td key={header} className="max-w-64 px-4 py-3 align-top text-slate-700 break-words">{String(row[header] ?? '')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
