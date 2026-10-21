<template>
  <div class="entry-grid">
    <el-card shadow="never" class="upload-card">
      <template #header>
        <div class="card-title">项目基础资料</div>
      </template>

      <div class="form-panel">
        <label class="field-label">当前项目</label>
        <div v-if="isProjectAccount" class="project-static">
          {{ selectedProjectName || '未绑定项目，请先在顶部选择项目账号对应项目' }}
        </div>
        <el-select v-else v-model="selectedProjectName" placeholder="请选择项目" class="field-input" @change="parsedBizTypes = []">
          <el-option v-for="item in projects" :key="`${item.project_name}-${item.project_code}`" :value="item.project_name" :label="item.project_name" />
        </el-select>

        <div class="mt-16">
          <label class="field-label">选择审核月份</label>
          <el-date-picker
            v-model="auditMonth"
            type="month"
            value-format="YYYY-MM"
            placeholder="选择月份"
            :clearable="false"
            style="width: 100%; margin-top: 8px"
          />
        </div>

        <div class="mt-16">
          <label class="field-label">选择审核业态</label>
          <el-select v-model="businessType" placeholder="请选择业态" class="field-input">
            <el-option v-for="bt in mappedBizTypes" :key="bt" :value="bt" :label="bt" />
          </el-select>
          <p v-if="selectedProjectName && mappedBizTypes.length === 0" class="hint warn">
            该项目未配置业态，请联系管理员补充后再审核。
          </p>
        </div>

        <div class="mt-16">
          <label class="field-label">选择服务类型</label>
          <el-select v-model="serviceType" placeholder="请选择服务类型" class="field-input">
            <el-option v-for="st in SERVICE_TYPES" :key="st" :value="st" :label="st" />
          </el-select>
        </div>
      </div>

      <div class="mt-16">
        <label class="field-label">上传排班表</label>
        <el-upload
          class="upload-box-wrap upload-mt"
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".xlsx"
          :on-change="handleUploadChange"
        >
          <div class="upload-inner">
            <div class="upload-file">
              <template v-if="projectFile">
                <div class="upload-file-name">已选择 1 个文件</div>
                <div class="upload-file-path">{{ projectFile.name }}</div>
              </template>
              <template v-else>拖到此处，或点击选择</template>
            </div>
          </div>
        </el-upload>
      </div>
    </el-card>

    <el-card shadow="never" class="progress-card">
      <template #header>
        <div class="card-title">审核进度</div>
      </template>
      <div class="progress-box">{{ message }}</div>
      <div v-for="warning in bizTypeWarnings" :key="warning" class="notice notice-warn">
        <span class="font-medium">业态提醒：</span>{{ warning }}
      </div>
      <div v-if="batchId" class="text-muted mt-12">当前批次：{{ batchId }}</div>
      <div class="action-row">
        <button class="btn-primary" :disabled="loading" @click="createAndUpload">{{ loading ? '审核中...' : '开始审核' }}</button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request } from '../api'
import { fetchBusinessTypes, fetchContracts } from '../api/configCache'
import { useAuthStore } from '../stores/auth'
import { useAuditContextStore, type AuditContext } from '../stores/auditContext'

type MasterProject = { project_name: string; project_code: string }

/** 服务类型只有保安/保洁两类，下拉不提供「全部」：它是定位键第四列，留空会让保安保洁互相覆盖 */
const SERVICE_TYPES = ['保安', '保洁'] as const

type UploadResult = {
  project_name: string
  audit_month: string
  bi_month: string
  service_type: string
  positions?: Array<{ business_type?: string }>
}

type StartAuditResult = {
  project_name: string
  business_type: string
  audit_month: string
  version: number
  status: string
  slot_count: number
  exception_count: number
  summary: Array<Record<string, unknown>>
}

const auth = useAuthStore()
const ctxStore = useAuditContextStore()
const isProjectAccount = computed(() => auth.role === 'project_user')

const projectFile = ref<File | null>(null)
const projects = ref<MasterProject[]>([])
const businessTypeMapping = ref<Record<string, string[]>>({})
const selectedProjectName = ref(isProjectAccount.value ? auth.projectName : '')
const auditMonth = ref((() => {
  const now = new Date()
  // 默认上个月（BI考勤通常是上月数据）
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`
})())
const businessType = ref('')
const serviceType = ref('')
const batchId = ref<number | null>(null)
const message = ref('审核未开始,请上传项目基础资料后点击开始审核按钮')
const loading = ref(false)
const uploaded = ref(false)
// 最近一次上传的表格里解析出的业态名（原值，不做归一），用于和业态映射表比对
const parsedBizTypes = ref<string[]>([])

const mappedBizTypes = computed(() => businessTypeMapping.value[selectedProjectName.value] || [])

function recordParsedBizTypes(result: UploadResult) {
  const types = Array.from(
    new Set((result.positions ?? []).map((p) => (p.business_type ?? '').trim()).filter(Boolean)),
  )
  parsedBizTypes.value = types
}

// 业态随登录项目自动映射：唯一业态直接选中，多业态需用户自选
watch([selectedProjectName, businessTypeMapping], () => {
  const mapped = mappedBizTypes.value
  if (mapped.length === 0) businessType.value = ''
  else if (mapped.length === 1) businessType.value = mapped[0]
  else if (!mapped.includes(businessType.value)) businessType.value = ''
})

function validateRequired(): string {
  if (!selectedProjectName.value) return '请先选择项目。项目来自系统配置里的项目合同库，请先上传并启用项目合同。'
  if (!auditMonth.value) return '请选择审核月份。不同月份天数不同，会影响月度审核和报告统计。'
  if (!businessType.value) return '请选择审核业态。不同业态对应不同合同，选择后仅审核该业态的排班和考勤。'
  if (!serviceType.value) return '请选择服务类型（保安／保洁）。服务类型是定位键的一部分，留空会导致保安与保洁数据互相覆盖。'
  if (!projectFile.value) return '请先选择项目基础资料.xlsx'
  return ''
}

function isExcel(file: File) {
  return file.name.toLowerCase().endsWith('.xlsx')
}

// 上传时把项目/审核月/服务类型一并提交，服务端缺任一即 400
function buildUploadForm(file: File) {
  const form = new FormData()
  form.append('file', file)
  form.append('project_name', selectedProjectName.value)
  form.append('audit_month', auditMonth.value)
  form.append('service_type', serviceType.value)
  return form
}

async function autoUploadProject(file: File) {
  if (!selectedProjectName.value) {
    message.value = '请先选择项目，再上传项目基础资料.xlsx'
    return
  }
  if (!auditMonth.value) {
    message.value = '请先选择审核月份，再上传项目基础资料.xlsx'
    return
  }
  if (!serviceType.value) {
    message.value = '请先选择服务类型（保安／保洁），再上传项目基础资料.xlsx'
    return
  }
  loading.value = true
  try {
    const result = await request<UploadResult>('/api/v2/positions/upload', { method: 'POST', data: buildUploadForm(file) })
    uploaded.value = true
    recordParsedBizTypes(result)
    message.value = `项目基础资料已上传：${file.name}（项目 ${result.project_name}／审核月 ${result.audit_month}／服务类型 ${result.service_type}），可点击「开始AI审核」发起审核。`
  } catch (error) {
    message.value = error instanceof Error ? error.message : '上传失败'
  } finally {
    loading.value = false
  }
}

function pickFile(file: File) {
  if (!isExcel(file)) {
    message.value = '项目基础资料仅支持上传 .xlsx 文件'
    return
  }
  projectFile.value = file
  uploaded.value = false
  parsedBizTypes.value = []
  message.value = `正在上传：${file.name}`
  autoUploadProject(file)
}

function handleUploadChange(uploadFile: { raw?: File; name: string }) {
  if (uploadFile.raw) pickFile(uploadFile.raw)
}

async function startAudit() {
  const auditMonthFormatted = auditMonth.value.replace('-', '')
  const result = await request<StartAuditResult>('/api/v2/audit-results/start', {
    method: 'POST',
    data: {
      project_name: selectedProjectName.value,
      business_type: businessType.value,
      service_type: serviceType.value,
      audit_month: auditMonthFormatted,
    },
  })
  return { result, auditMonthFormatted }
}

function saveCtx(auditMonthFormatted: string) {
  const ctx: AuditContext = {
    project_name: selectedProjectName.value,
    audit_month: auditMonthFormatted,
    business_type: businessType.value,
    service_type: serviceType.value,
  }
  ctxStore.set(ctx)
}

async function createAndUpload() {
  const missing = validateRequired()
  if (missing) {
    message.value = missing
    return
  }
  loading.value = true
  try {
    // 若尚未上传，先上传再审核
    if (!uploaded.value && projectFile.value) {
      const uploadResult = await request<UploadResult>('/api/v2/positions/upload', { method: 'POST', data: buildUploadForm(projectFile.value) })
      uploaded.value = true
      recordParsedBizTypes(uploadResult)
    }
    const { result, auditMonthFormatted } = await startAudit()
    batchId.value = result.version ?? null
    // 统一口径：异常率 = 异常记录数 / 排班任务数
    const scheduleTaskCount = result.slot_count || 0
    const exceptionCount = result.exception_count || 0
    const exceptionRate = scheduleTaskCount > 0 ? ((exceptionCount / scheduleTaskCount) * 100).toFixed(1) : '0.0'
    message.value = `审核完成：异常率 ${exceptionRate}%`
    saveCtx(auditMonthFormatted)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '审核失败'
  } finally {
    loading.value = false
  }
}


// 业态一致性提醒：只提醒、不拦截
const bizTypeWarnings = computed<string[]>(() => {
  const warnings: string[] = []
  const mappingTypes = mappedBizTypes.value
  const unknownBizTypes = parsedBizTypes.value.filter((t) => !mappingTypes.includes(t))
  if (unknownBizTypes.length > 0) {
    warnings.push(
      `表格中解析出的业态「${unknownBizTypes.join('、')}」不在当前项目的业态映射表中` +
      `${mappingTypes.length ? `（映射表业态：${mappingTypes.join('、')}）` : '（该项目尚未配置业态映射）'}，` +
      `这些业态的排班无法审核、也无法生成报告。请检查表格「业态」列是否填写有误，或联系管理员更新业态映射表。`,
    )
  }
  const selectedBizMissing = Boolean(
    businessType.value && parsedBizTypes.value.length > 0 && !parsedBizTypes.value.includes(businessType.value),
  )
  if (selectedBizMissing) {
    warnings.push(
      `本次上传的表格中没有当前所选业态「${businessType.value}」的排班数据（表格内业态：${parsedBizTypes.value.join('、')}），` +
      `继续审核会提示「岗位缺失」。请确认是否选错了业态或传错了表格。`,
    )
  }
  return warnings
})

onMounted(() => {
  fetchContracts<Array<{ project_name: string; project_code: string; business_type: string }>>().then((items) => {
    const seen = new Map<string, MasterProject>()
    for (const item of items) {
      if (!seen.has(item.project_name)) seen.set(item.project_name, { project_name: item.project_name, project_code: item.project_code })
    }
    const unique = Array.from(seen.values())
    projects.value = unique
    if (isProjectAccount.value && auth.projectName) {
      selectedProjectName.value = auth.projectName
    } else if (unique.length && !selectedProjectName.value) {
      selectedProjectName.value = unique[0].project_name
    }
  }).catch(() => (projects.value = []))

  fetchBusinessTypes().then((data) => {
    businessTypeMapping.value = data.mapping || {}
  }).catch(() => {})
})
</script>

<style scoped>
/* 上传卡片与进度卡片左右并排、等高 */
.entry-grid { display: grid; grid-template-columns: 2fr 3fr; gap: 20px; align-items: stretch; }
@media (max-width: 900px) { .entry-grid { grid-template-columns: 1fr; } }

/* 左卡内容撑满列高 */
.upload-card { display: flex; flex-direction: column; height: 100%; }
.upload-card :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }
/* 进度卡同样撑满，开始审核按钮钉在卡片右下角 */
.progress-card { display: flex; flex-direction: column; height: 100%; }
.progress-card :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }
.action-row { margin-top: auto; padding-top: 16px; display: flex; justify-content: flex-end; }

.card-title { font-size: 16px; font-weight: 600; color: var(--text-strong); }
.desc { margin-top: 8px; }
.mt-12 { margin-top: 12px; }
.mt-16 { margin-top: 16px; }
.form-panel {
  border-radius: 12px; border: 1px solid var(--card-border);
  background: var(--card-bg); padding: 16px;
}
.field-label { display: block; font-size: 14px; font-weight: 500; color: var(--text-strong); }
.field-input { margin-top: 8px; width: 100%; }
.project-static {
  margin-top: 8px; border-radius: 12px; border: 1px solid var(--card-border);
  background: #fff; padding: 12px 16px; font-size: 14px; color: var(--text-strong);
}
.hint { margin-top: 8px; font-size: 12px; color: var(--text-weak); }
.hint.warn { color: var(--warning); }

.upload-box-wrap :deep(.el-upload-dragger) {
  border-radius: 12px; padding: 0;
  border: 1px dashed var(--slate-300); background: var(--card-bg);
}
.upload-box-wrap :deep(.el-upload-dragger):hover {
  border-color: var(--accent); background: var(--card-bg-soft);
}
.upload-mt { margin-top: 8px; }
.upload-inner { display: block; cursor: pointer; padding: 16px; }
.upload-title { font-size: 14px; font-weight: 500; color: var(--text-strong); text-align: center; }
.upload-file {
  margin-top: 12px; border-radius: 12px; background: #fff;
  padding: 10px 16px; font-size: 14px; color: var(--text-normal); text-align: center;
}
.upload-file-name { font-weight: 500; }
.upload-file-path { color: var(--text-weak); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progress-box {
  border-radius: 12px; background: var(--card-bg);
  padding: 16px; font-size: 14px; color: var(--text-normal);
}
</style>
