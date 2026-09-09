import { useEffect, useState, type DragEvent } from 'react'
import { Upload, Loader2, FileSpreadsheet, RefreshCw } from 'lucide-react'
import { request } from '../services/api'

type BiHistoryRecord = {
  bi_month: string
  project_name: string
  record_count: number
  last_updated: string
}

export function BiUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [biMonth, setBiMonth] = useState('')
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [history, setHistory] = useState<BiHistoryRecord[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)

  useEffect(() => {
    loadHistory()
  }, [])

  async function loadHistory() {
    setLoadingHistory(true)
    try {
      const data = await request<BiHistoryRecord[]>('/api/v2/bi/history')
      setHistory(data || [])
    } catch {
      setHistory([])
    } finally {
      setLoadingHistory(false)
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault()
    setDragOver(false)
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped && (dropped.name.endsWith('.xlsx') || dropped.name.endsWith('.xls'))) {
      setFile(dropped)
      setMessage('')
    } else {
      setMessage('仅支持 .xlsx 或 .xls 格式的 Excel 文件')
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0]
    if (selected) {
      setFile(selected)
      setMessage('')
    }
  }

  async function handleUpload() {
    if (!file) {
      setMessage('请选择 BI 考勤文件')
      return
    }
    if (!biMonth) {
      setMessage('请选择上传月份')
      return
    }
    setUploading(true)
    setMessage('')
    try {
      const form = new FormData()
      form.append('file', file)
      const result = await request<{ message: string }>('/api/v2/bi/upload?bi_month=' + biMonth.replace('-', ''), {
        method: 'POST',
        body: form,
      })
      setMessage(result.message || 'BI 考勤数据上传成功')
      setFile(null)
      loadHistory()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'BI 考勤数据上传失败')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h2 className="text-lg font-semibold">上传 BI 考勤数据</h2>
        <p className="mt-2 text-sm text-slate-500">
          上传 BI 导出的考勤 Excel 文件，系统将自动解析并导入对应项目的考勤记录。集团管理员可导入所有项目数据。
        </p>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">考勤月份</span>
            <input
              className="input mt-2 w-full"
              type="month"
              value={biMonth}
              onChange={(e) => setBiMonth(e.target.value)}
            />
          </label>
        </div>

        <div className="mt-5">
          <span className="text-sm font-medium text-slate-700">考勤文件</span>
          <div
            className={`mt-2 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
              dragOver
                ? 'border-brand-400 bg-brand-50'
                : file
                ? 'border-emerald-300 bg-emerald-50'
                : 'border-slate-300 bg-slate-50'
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {file ? (
              <>
                <FileSpreadsheet size={40} className="text-emerald-600" />
                <div className="mt-3 text-sm font-medium text-slate-800">{file.name}</div>
                <div className="mt-1 text-xs text-slate-500">{(file.size / 1024).toFixed(1)} KB</div>
                <button
                  className="mt-3 text-xs text-brand-600 hover:text-brand-700"
                  onClick={() => setFile(null)}
                >
                  重新选择
                </button>
              </>
            ) : (
              <>
                <Upload size={40} className="text-slate-400" />
                <div className="mt-3 text-sm text-slate-600">拖拽 Excel 文件到此处，或</div>
                <label className="mt-2 cursor-pointer text-sm font-medium text-brand-600 hover:text-brand-700">
                  点击选择文件
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                </label>
                <div className="mt-1 text-xs text-slate-400">仅支持 .xlsx 或 .xls 格式</div>
              </>
            )}
          </div>
        </div>

        <div className="mt-5 flex items-center gap-3">
          <button
            className="btn-primary flex items-center gap-2"
            disabled={uploading || !file || !biMonth}
            onClick={handleUpload}
          >
            {uploading && <Loader2 size={16} className="animate-spin" />}
            {uploading ? '上传中...' : '上传'}
          </button>
        </div>

        {message && (
          <div className={`mt-4 rounded-xl px-4 py-3 text-sm ${
            message.includes('失败') || message.includes('仅支持')
              ? 'bg-red-50 text-red-600'
              : 'bg-emerald-50 text-emerald-700'
          }`}>
            {message}
          </div>
        )}
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">上传历史记录</h2>
          <button
            className="btn-secondary flex items-center gap-2 text-xs"
            disabled={loadingHistory}
            onClick={loadHistory}
          >
            <RefreshCw size={14} className={loadingHistory ? 'animate-spin' : ''} />
            {loadingHistory ? '刷新中...' : '刷新'}
          </button>
        </div>
        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-[600px] table-fixed text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="w-32 px-4 py-3 text-left">考勤月份</th>
                <th className="px-4 py-3 text-left">项目名称</th>
                <th className="w-28 px-4 py-3 text-left">记录数</th>
                <th className="w-48 px-4 py-3 text-left">最后更新时间</th>
              </tr>
            </thead>
            <tbody>
              {history.map((item, idx) => (
                <tr key={`${item.bi_month}-${item.project_name}-${idx}`} className="border-t border-slate-100">
                  <td className="px-4 py-3">{item.bi_month}</td>
                  <td className="px-4 py-3 break-words">{item.project_name}</td>
                  <td className="px-4 py-3">{item.record_count}</td>
                  <td className="px-4 py-3 text-slate-500">{item.last_updated}</td>
                </tr>
              ))}
              {!history.length && !loadingHistory && (
                <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={4}>暂无上传记录</td></tr>
              )}
              {loadingHistory && (
                <tr><td className="px-4 py-8 text-center text-slate-500" colSpan={4}>加载中...</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
