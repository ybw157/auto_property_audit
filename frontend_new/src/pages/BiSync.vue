<template>
  <div class="page-stack">
    <div class="card card-pad">
      <div class="head-row">
        <div>
          <h2 class="h2">BI数据同步</h2>
          <p class="text-muted desc">
            系统只读取服务器 BI_Data 目录中的同步文件，不在网站内保存BI账号密码。审核时会按项目名称、审核月份和业态自动匹配。
          </p>
        </div>
        <button class="btn-secondary" :disabled="loading" @click="loadRecords">
          {{ loading ? '刷新中...' : '刷新状态' }}
        </button>
      </div>

      <div class="grid-3 mt-20">
        <div class="stat-box">
          <div class="stat-label">同步文件数</div>
          <div class="stat-value">{{ records.length }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">涉及项目数</div>
          <div class="stat-value">{{ projectCount }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">涉及月份数</div>
          <div class="stat-value">{{ monthCount }}</div>
        </div>
      </div>

      <div class="filter-row">
        <label class="field">
          <span>项目</span>
          <el-select v-model="projectName" placeholder="全部项目" clearable style="width: 100%; margin-top: 8px">
            <el-option v-for="item in projects" :key="item.project_name" :value="item.project_name" :label="item.project_name" />
          </el-select>
        </label>
        <label class="field">
          <span>审核月份</span>
          <el-date-picker
            v-model="auditMonth"
            type="month"
            value-format="YYYY-MM"
            placeholder="全部月份"
            style="width: 100%"
          />
        </label>
        <div class="field-end">
          <button class="btn-primary full-btn" :disabled="loading" @click="loadRecords">查询同步状态</button>
        </div>
      </div>

      <div v-if="message" class="notice">{{ message }}</div>
    </div>

    <div class="card card-pad">
      <div class="row-between">
        <h2 class="h3">同步文件明细</h2>
        <span class="text-xs text-muted">已同步：{{ syncedCount }} 个</span>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="records" border stripe style="width: 100%">
          <el-table-column label="项目" width="192">
            <template #default="{ row }">{{ row.project_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="月份" width="96">
            <template #default="{ row }">{{ row.audit_month || '-' }}</template>
          </el-table-column>
          <el-table-column label="业态" width="96">
            <template #default="{ row }">{{ row.business_type || '-' }}</template>
          </el-table-column>
          <el-table-column prop="file_name" label="文件名" width="320" show-overflow-tooltip />
          <el-table-column label="状态" width="96">
            <template #default="{ row }"><span class="badge badge-green">{{ row.sync_status }}</span></template>
          </el-table-column>
          <el-table-column label="同步时间" width="160">
            <template #default="{ row }"><span class="text-muted">{{ row.synced_at || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="存储路径" min-width="200">
            <template #default="{ row }"><span class="text-xs break" style="color: var(--slate-400)">{{ row.storage_path }}</span></template>
          </el-table-column>
          <template #empty><span class="text-muted">暂无BI同步文件</span></template>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '../api'
import { fetchContracts } from '../api/configCache'

type BiSyncRecord = {
  project_name: string
  project_code: string
  audit_month: string
  business_type: string
  file_name: string
  storage_path: string
  sync_status: string
  synced_at: string
}

type MasterProject = {
  project_name: string
  project_code: string
}

const records = ref<BiSyncRecord[]>([])
const projects = ref<MasterProject[]>([])
const projectName = ref('')
const auditMonth = ref('')
const loading = ref(false)
const message = ref('')

const syncedCount = computed(() => records.value.filter((item) => item.sync_status === '已同步').length)
const projectCount = computed(() => new Set(records.value.map((item) => item.project_name).filter(Boolean)).size)
const monthCount = computed(() => new Set(records.value.map((item) => item.audit_month).filter(Boolean)).size)


async function loadRecords() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (projectName.value) params.set('project_name', projectName.value)
    if (auditMonth.value) params.set('audit_month', auditMonth.value)
    const query = params.toString()
    const rows = await request<BiSyncRecord[]>(`/api/v1/management/bi-sync${query ? `?${query}` : ''}`)
    records.value = rows
    message.value = rows.length ? `已找到 ${rows.length} 个BI同步文件` : '未找到符合条件的BI同步文件'
  } catch (error) {
    records.value = []
    message.value = error instanceof Error ? error.message : 'BI同步状态读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchContracts<any[]>().then((rows) => {
    const seen = new Set<string>()
    const list: MasterProject[] = []
    for (const r of rows) {
      if (!r.project_name || seen.has(r.project_name)) continue
      seen.add(r.project_name)
      list.push({ project_name: r.project_name, project_code: r.project_code || '' })
    }
    projects.value = list
  }).catch(() => (projects.value = []))
  loadRecords()
})
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.head-row { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 16px; }
.desc { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.filter-row {
  margin-top: 20px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
  border-radius: 16px; border: 1px solid var(--slate-200); background: #fff; padding: 16px;
}
.field { display: block; }
.field span { font-size: 14px; font-weight: 500; color: var(--slate-700); }
.field .input { margin-top: 8px; width: 100%; }
.field-end { display: flex; align-items: flex-end; }
.full-btn { width: 100%; }
.table-fixed-lg { min-width: 1100px; table-layout: fixed; }
.break { word-break: break-word; }
</style>
