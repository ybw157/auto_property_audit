<template>
  <div class="page-stack">
    <div class="card card-pad">
      <div class="head-row">
        <div>
          <h2 class="h2">项目管理</h2>
          <p class="text-muted desc">集团端按项目+业态查看保安/保洁的合同、排班和审核状态，快速识别哪些项目未上传资料。</p>
        </div>
        <button class="btn-secondary" :disabled="loading" @click="loadProjects">{{ loading ? '刷新中...' : '刷新状态' }}</button>
      </div>

      <div class="grid-5 mt-20">
        <div class="stat-box">
          <div class="stat-label">项目业态总数</div>
          <div class="stat-value">{{ projects.length }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">保安已启用合同</div>
          <div class="stat-value">{{ securityContractActive }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">保洁已启用合同</div>
          <div class="stat-value">{{ cleaningContractActive }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">已上传排班</div>
          <div class="stat-value">{{ scheduleUploaded }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">审核完成</div>
          <div class="stat-value">{{ auditCompleted }}</div>
        </div>
      </div>

      <div class="filter-row">
        <label class="field">
          <span>搜索项目/业态</span>
          <el-input v-model="keyword" placeholder="例如：江宁、商业" style="margin-top: 8px" clearable />
        </label>
        <label class="field">
          <span>合同状态</span>
          <el-select v-model="contractFilter" style="width: 100%; margin-top: 8px">
              <el-option value="全部" label="全部" />
              <el-option value="已上传" label="已上传" />
              <el-option value="未上传" label="未上传" />
          </el-select>
        </label>
        <label class="field">
          <span>排班状态</span>
          <el-select v-model="scheduleFilter" style="width: 100%; margin-top: 8px">
              <el-option value="全部" label="全部" />
              <el-option value="已上传" label="已上传" />
              <el-option value="未上传" label="未上传" />
          </el-select>
        </label>
        <label class="field">
          <span>审核状态</span>
          <el-select v-model="auditFilter" style="width: 100%; margin-top: 8px">
              <el-option value="全部" label="全部" />
              <el-option value="待上传" label="待上传" />
              <el-option value="待审核" label="待审核" />
              <el-option value="审核完成" label="审核完成" />
              <el-option value="已确认" label="已确认" />
          </el-select>
        </label>
        <div class="field-end">
          <button class="btn-primary full-btn" @click="resetFilters">重置筛选</button>
        </div>
      </div>

      <div v-if="message" class="notice">{{ message }}</div>
    </div>

    <div class="card card-pad">
      <div class="row-between">
        <h2 class="h3">项目状态明细</h2>
        <span class="text-xs text-muted">当前显示 {{ filteredProjects.length }} 条</span>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="filteredProjects" border stripe style="width: 100%">
          <el-table-column label="项目" width="150">
            <template #default="{ row }"><span class="text-strong break">{{ row.project_name }}</span></template>
          </el-table-column>
          <el-table-column label="业态" width="70">
            <template #default="{ row }">{{ row.business_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="保安合同" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.security_contract_status)">{{ row.security_contract_status }}</span></template>
          </el-table-column>
          <el-table-column label="保洁合同" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.cleaning_contract_status)">{{ row.cleaning_contract_status }}</span></template>
          </el-table-column>
          <el-table-column label="保安排班" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.security_schedule_status)">{{ row.security_schedule_status }}</span></template>
          </el-table-column>
          <el-table-column label="保洁排班" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.cleaning_schedule_status)">{{ row.cleaning_schedule_status }}</span></template>
          </el-table-column>
          <el-table-column label="保安审核" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.security_audit_status)">{{ row.security_audit_status }}</span></template>
          </el-table-column>
          <el-table-column label="保洁审核" align="center" width="86">
            <template #default="{ row }"><span class="badge" :class="statusBadgeClass(row.cleaning_audit_status)">{{ row.cleaning_audit_status }}</span></template>
          </el-table-column>
          <el-table-column label="保安完成时间" min-width="110">
            <template #default="{ row }"><span class="text-xs nowrap text-muted">{{ row.security_audit_time || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="保洁完成时间" min-width="110">
            <template #default="{ row }"><span class="text-xs nowrap text-muted">{{ row.cleaning_audit_time || '-' }}</span></template>
          </el-table-column>
          <template #empty><span class="text-muted">没有符合筛选条件的项目</span></template>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '../api'

type ProjectStatus = {
  project_name: string
  project_code: string
  business_type: string
  contract_status: string
  security_contract_status: string
  cleaning_contract_status: string
  schedule_status: string
  security_schedule_status: string
  cleaning_schedule_status: string
  audit_status: string
  security_audit_status: string
  cleaning_audit_status: string
  security_audit_time: string
  cleaning_audit_time: string
}

function statusBadgeClass(status: string): string {
  if (status === '—') return 'badge-slate'
  if (status === '已启用' || status === '已确认' || status === '审核完成') return 'badge-green'
  if (status === '已上传' || status === '已重新提交' || status === '审核中' || status === '待审核') return 'badge-blue'
  if (status === '审核失败' || status === '校验失败') return 'badge-red'
  return 'badge-amber'
}

const projects = ref<ProjectStatus[]>([])
const contractFilter = ref('全部')
const scheduleFilter = ref('全部')
const auditFilter = ref('全部')
const keyword = ref('')
const loading = ref(false)
const message = ref('')

async function loadProjects() {
  loading.value = true
  try {
    const rows = await request<ProjectStatus[]>('/api/v1/management/projects')
    projects.value = rows
    message.value = `已加载 ${rows.length} 条项目业态状态`
  } catch (error) {
    projects.value = []
    message.value = error instanceof Error ? error.message : '项目状态读取失败'
  } finally {
    loading.value = false
  }
}

const filteredProjects = computed(() => projects.value.filter((item) => {
  const contractOk = contractFilter.value === '全部' || (contractFilter.value === '已上传'
    ? item.security_contract_status.includes('已上传') || item.cleaning_contract_status.includes('已上传')
    : !item.security_contract_status.includes('已上传') && !item.cleaning_contract_status.includes('已上传'))
  const scheduleOk = scheduleFilter.value === '全部' || (scheduleFilter.value === '已上传'
    ? item.security_schedule_status.includes('已上传') || item.security_schedule_status.includes('已重新提交') || item.cleaning_schedule_status.includes('已上传') || item.cleaning_schedule_status.includes('已重新提交')
    : !item.security_schedule_status.includes('已上传') && !item.security_schedule_status.includes('已重新提交') && !item.cleaning_schedule_status.includes('已上传') && !item.cleaning_schedule_status.includes('已重新提交'))
  const auditOk = auditFilter.value === '全部' || item.security_audit_status === auditFilter.value || item.cleaning_audit_status === auditFilter.value
  const keywordOk = !keyword.value || `${item.project_name}${item.business_type}`.includes(keyword.value)
  return contractOk && scheduleOk && auditOk && keywordOk
}))

const securityContractActive = computed(() => projects.value.filter((item) => item.security_contract_status === '已启用').length)
const cleaningContractActive = computed(() => projects.value.filter((item) => item.cleaning_contract_status === '已启用').length)
const scheduleUploaded = computed(() => projects.value.filter((item) =>
  item.security_schedule_status.includes('已上传') || item.security_schedule_status.includes('已重新提交') ||
  item.cleaning_schedule_status.includes('已上传') || item.cleaning_schedule_status.includes('已重新提交'),
).length)
const auditCompleted = computed(() => projects.value.filter((item) =>
  item.security_audit_status === '审核完成' || item.cleaning_audit_status === '审核完成',
).length)

function resetFilters() {
  keyword.value = ''
  contractFilter.value = '全部'
  scheduleFilter.value = '全部'
  auditFilter.value = '全部'
}

onMounted(loadProjects)
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.head-row { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 16px; }
.desc { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.filter-row {
  margin-top: 20px; display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px;
  border-radius: 16px; border: 1px solid var(--slate-200); background: #fff; padding: 16px;
}
.field { display: block; }
.field span { font-size: 14px; font-weight: 500; color: var(--slate-700); }
.field .input { margin-top: 8px; width: 100%; }
.field-end { display: flex; align-items: flex-end; }
.full-btn { width: 100%; }
.table-xs { font-size: 12px; }
.table-xs th, .table-xs td { padding: 8px; }
.nowrap { white-space: nowrap; }
.break { word-break: break-word; }
.text-center { text-align: center; }
</style>
