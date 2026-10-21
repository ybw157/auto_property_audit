<template>
  <div class="report-card">
    <div class="row-between row-top">
      <div>
        <div class="report-type">{{ item.report_type }}</div>
        <div class="report-time">{{ item.created_at }}</div>
      </div>
      <span class="badge badge-red">PDF</span>
    </div>
    <button class="btn-primary download-btn" :disabled="downloading" @click="handleDownload">
      {{ downloading ? '下载中...' : '下载 PDF' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getToken } from '../api'

export interface ReportItem {
  id: number
  report_type: string
  file_format: string
  file_path: string
  created_at: string
}

const props = defineProps<{ item: ReportItem }>()
const downloading = ref(false)

async function handleDownload() {
  downloading.value = true
  try {
    const token = getToken()
    const res = await fetch(`/api/v2/reports/${props.item.id}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('下载失败')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 用服务端落盘的真实文件名（含服务类型前缀与审核月份）
    const fileName = props.item.file_path.split(/[\\/]/).pop()
    a.download = fileName || `${props.item.report_type}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    alert('下载失败，请重试')
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.report-card {
  border-radius: 16px;
  border: 1px solid var(--slate-200);
  background: #fff;
  padding: 16px;
  box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.05);
}
.row-top { gap: 12px; }
.report-type { font-weight: 500; color: var(--slate-900); }
.report-time { margin-top: 4px; font-size: 12px; color: var(--slate-400); }
.download-btn { margin-top: 16px; width: 100%; display: inline-flex; align-items: center; justify-content: center; }
</style>
