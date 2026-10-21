<template>
  <div class="page-stack">
    <div class="card card-pad">
      <h2 class="h2">上传 BI 考勤数据</h2>
      <p class="text-muted desc">
        上传 BI 导出的考勤 Excel 文件，系统将自动解析并导入对应项目的考勤记录。集团管理员可导入所有项目数据。
      </p>

      <div class="grid-2 mt-20" style="max-width: 50%">
        <label class="field">
          <span>考勤月份</span>
          <el-date-picker
            v-model="biMonth"
            type="month"
            value-format="YYYY-MM"
            placeholder="请选择月份"
            :clearable="false"
            style="width: 100%"
          />
        </label>
      </div>

      <div class="mt-20">
        <span class="field-label">考勤文件</span>
        <el-upload
          class="upload-drag"
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".xlsx,.xls"
          :on-change="handleFileChange"
        >
          <template v-if="file">
            <el-icon :size="40" class="icon-green"><Document /></el-icon>
            <div class="file-name">{{ file.name }}</div>
            <div class="file-size">{{ (file.size / 1024).toFixed(1) }} KB</div>
            <span class="relink">重新选择</span>
          </template>
          <template v-else>
            <el-icon :size="40" class="icon-gray"><UploadFilled /></el-icon>
            <div class="drop-hint">拖拽 Excel 文件到此处，或 <em>点击选择</em></div>
            <div class="drop-note">仅支持 .xlsx 或 .xls 格式</div>
          </template>
        </el-upload>
      </div>

      <div class="row gap-3 mt-20">
        <button class="btn-primary row gap-2" :disabled="uploading || !file || !biMonth" @click="handleUpload">
          <el-icon v-if="uploading" class="is-loading"><Loading /></el-icon>
          {{ uploading ? '上传中...' : '上传' }}
        </button>
      </div>

      <div v-if="message" class="notice" :class="message.includes('失败') || message.includes('仅支持') ? 'notice-danger' : 'notice-success'">
        {{ message }}
      </div>
    </div>

    <div class="card card-pad">
      <div class="row-between">
        <h2 class="h3">上传历史记录</h2>
        <button class="btn-secondary row gap-2 text-xs" :disabled="loadingHistory" @click="loadHistory">
          <el-icon :size="14" :class="loadingHistory ? 'is-loading' : ''"><Refresh /></el-icon>
          {{ loadingHistory ? '刷新中...' : '刷新' }}
        </button>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="history" border stripe style="width: 100%" v-loading="loadingHistory">
          <el-table-column prop="bi_month" label="考勤月份" width="128" />
          <el-table-column label="项目名称" min-width="160">
            <template #default="{ row }"><span class="break">{{ row.project_name }}</span></template>
          </el-table-column>
          <el-table-column prop="record_count" label="记录数" width="112" />
          <el-table-column label="最后更新时间" width="192">
            <template #default="{ row }"><span class="text-muted">{{ row.last_updated }}</span></template>
          </el-table-column>
          <template #empty><span class="text-muted">暂无上传记录</span></template>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Document, Loading, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { request } from '../api'

type BiHistoryRecord = {
  bi_month: string
  project_name: string
  record_count: number
  last_updated: string
}

const file = ref<File | null>(null)
const biMonth = ref('')
const uploading = ref(false)
const message = ref('')
const history = ref<BiHistoryRecord[]>([])
const loadingHistory = ref(false)


async function loadHistory() {
  loadingHistory.value = true
  try {
    history.value = await request<BiHistoryRecord[]>('/api/v2/bi/history') || []
  } catch {
    history.value = []
  } finally {
    loadingHistory.value = false
  }
}

function handleFileChange(uploadFile: { raw?: File; name: string }) {
  const raw = uploadFile.raw
  if (!raw) return
  if (!raw.name.endsWith('.xlsx') && !raw.name.endsWith('.xls')) {
    message.value = '仅支持 .xlsx 或 .xls 格式的 Excel 文件'
    return
  }
  file.value = raw
  message.value = ''
}

async function handleUpload() {
  if (!file.value) {
    message.value = '请选择 BI 考勤文件'
    return
  }
  if (!biMonth.value) {
    message.value = '请选择上传月份'
    return
  }
  uploading.value = true
  message.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    const result = await request<{ message: string }>('/api/v2/bi/upload?bi_month=' + biMonth.value.replace('-', ''), {
      method: 'POST',
      data: form,
    })
    message.value = result.message || 'BI 考勤数据上传成功'
    file.value = null
    loadHistory()
  } catch (error) {
    message.value = error instanceof Error ? error.message : 'BI 考勤数据上传失败'
  } finally {
    uploading.value = false
  }
}

onMounted(loadHistory)
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.desc { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.field { display: block; }
.field span, .field-label { font-size: 14px; font-weight: 500; color: var(--slate-700); }
.field .input { margin-top: 8px; width: 100%; }
.break { word-break: break-word; }

.drop-zone {
  margin-top: 8px;
}
/* el-upload 拖拽区对齐原自绘观感 */
.upload-drag :deep(.el-upload-dragger) {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-radius: 16px; padding: 40px 24px;
  border: 2px dashed var(--slate-300); background: var(--slate-50);
}
.upload-drag :deep(.el-upload-dragger:hover) {
  border-color: var(--accent);
}
.icon-green { color: #059669; }
.icon-gray { color: var(--slate-400); }
.file-name { margin-top: 12px; font-size: 14px; font-weight: 500; color: var(--slate-800); }
.file-size { margin-top: 4px; font-size: 12px; color: var(--slate-500); }
.relink { margin-top: 12px; font-size: 12px; color: var(--brand-600); }
.relink:hover { color: var(--brand-700); }
.drop-hint { margin-top: 12px; font-size: 14px; color: var(--slate-600); }
.pick-link { margin-top: 8px; cursor: pointer; font-size: 14px; font-weight: 500; color: var(--brand-600); }
.pick-link:hover { color: var(--brand-700); }
.drop-note { margin-top: 4px; font-size: 12px; color: var(--slate-400); }
</style>
