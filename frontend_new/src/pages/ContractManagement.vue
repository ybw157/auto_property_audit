<template>
  <div class="page-stack">
    <div class="card card-pad">
      <h2 class="h2">项目合同库</h2>
      <p class="text-muted desc">
        直接上传合同 PDF / Word，系统会自动识别合同信息和扣款条款。合同解析有误时，可点击"编辑"手动填写扣款规则后启用。
      </p>
      <div class="contract-upload-row">
        <el-upload
          class="contract-upload"
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".pdf,.doc,.docx"
          :on-change="handleUploadChange"
        >
          <span class="drop-name">{{ uploading ? uploadFileName : contractFile ? contractFile.name : '拖入合同文件，或点击选择 PDF / Word 文件' }}</span>
          <span class="drop-note">支持 .pdf、.doc、.docx；拖拽到当前区域即可选中文件。系统将自动识别合同中的所有信息。</span>
        </el-upload>
        <button class="btn-primary" :disabled="uploading" @click="uploadContract">
          {{ uploading ? '上传解析中...' : '上传合同' }}
        </button>
      </div>
      <div v-if="uploading || message" class="notice" :class="uploading ? 'notice-info' : ''">
        {{ uploading ? uploadMessage : message }}
      </div>
      <!-- 未入库草稿横幅 -->
      <div v-if="draftBanner" class="notice notice-warn draft-banner">
        <span class="break">
          存在未保存的解析草稿：<span class="font-medium">{{ draftBanner.fileName }}</span>
          （{{ new Date(draftBanner.createdAt).toLocaleString() }} 解析），尚未入库，取消编辑也不会丢失。
        </span>
        <div class="row gap-3 shrink-0">
          <button class="link-amber" @click="openDraftEditor(draftBanner.parsed, draftBanner.tempFile, draftBanner.fileName)">继续编辑</button>
          <button class="link-red" @click="discardDraft">丢弃</button>
        </div>
      </div>
      <div class="table-wrap mt-20">
        <el-table :data="contracts" border stripe style="width: 100%">
          <el-table-column label="项目" width="150">
            <template #default="{ row }"><span class="break">{{ row.project_name }}</span></template>
          </el-table-column>
          <el-table-column label="业态" width="80">
            <template #default="{ row }">{{ row.business_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="服务类型" width="86">
            <template #default="{ row }">{{ row.service_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="合同" width="220">
            <template #default="{ row }">
              <a class="link-brand break" :href="row.download_url" target="_blank">{{ row.contract_name }}</a>
              <div class="text-xs text-muted-light break">{{ row.contract_no || row.version || row.original_name }}</div>
            </template>
          </el-table-column>
          <el-table-column label="供应商" width="110">
            <template #default="{ row }"><span class="break">{{ row.supplier || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="有效期" width="150">
            <template #default="{ row }"><span class="break">{{ row.start_date || '-' }} 至 {{ row.end_date || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="扣款规则" min-width="240">
            <template #default="{ row }"><span class="text-xs text-muted break">{{ formatRules(row.rules) }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="86">
            <template #default="{ row }">{{ row.is_active ? '启用' : row.status === 'parse_failed' ? '解析失败' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <div class="op-col">
                <button class="link-brand" @click="setContractActive(row, !row.is_active)">{{ row.is_active ? '停用' : '启用' }}</button>
                <button class="link-blue" @click="openManualEditor(row)">编辑</button>
                <button class="link-red" @click="deleteContract(row)">删除</button>
              </div>
            </template>
          </el-table-column>
          <template #empty><span class="text-muted">暂无合同</span></template>
        </el-table>
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <div v-if="editingContract" class="modal-mask">
      <div class="modal-card-lg">
        <div class="modal-scroll">
          <div class="row-between mb-16">
            <h3 class="h2 row gap-2">
              编辑合同信息
              <span v-if="draftMeta" class="badge badge-amber">缓存草稿 · 未入库</span>
              <span v-else class="badge badge-slate">已入库</span>
            </h3>
            <button class="icon-btn" @click="closeEditor">✕</button>
          </div>
          <p v-if="draftMeta" class="notice notice-warn mb-16">
            当前展示的是本次解析的缓存数据，尚未入库；点「取消」不会丢失，可随时从页面顶部「未保存草稿」继续编辑或丢弃。保存后才会写入合同库。
          </p>
          <p v-else-if="editingContract?.status === 'parse_failed'" class="notice notice-warn mb-16">
            合同解析失败，请手动填写合同信息和扣款细则后启用。修改会直接保存到已入库的这条合同。
          </p>
          <div class="form-stack">
            <!-- 基本信息 -->
            <div class="form-panel">
              <h4 class="panel-title">基本信息 <span class="text-xs text-muted-light">（所有字段均为必填）</span></h4>
              <div class="grid-2" style="gap: 12px">
                <label class="field">
                  <span class="req">*</span> 项目名称
                  <el-select v-if="isAdmin" :class="errCls('project_name')" v-model="editFields.project_name" placeholder="请选择项目" style="width: 100%; margin-top: 4px" @change="editFields.business_type = ''; clearErr('project_name')">
                    <el-option v-for="p in allProjects" :key="p" :value="p" :label="p" />
                    <el-option v-if="editFields.project_name && !allProjects.includes(editFields.project_name)" :value="editFields.project_name" :label="editFields.project_name" />
                  </el-select>
                  <input v-else type="text" class="input" :class="errCls('project_name')" v-model="editFields.project_name" readonly placeholder="从登录信息自动获取" />
                </label>
                <label class="field">
                  <span class="req">*</span> 业态
                  <el-select :class="errCls('business_type')" v-model="editFields.business_type" placeholder="请选择业态" style="width: 100%; margin-top: 4px" @change="clearErr('business_type')">
                    <el-option v-for="bt in businessTypeOptions" :key="bt" :value="bt" :label="bt" />
                    <el-option v-if="editFields.business_type && !businessTypeOptions.includes(editFields.business_type)" :value="editFields.business_type" :label="editFields.business_type" />
                  </el-select>
                </label>
                <label class="field">
                  <span class="req">*</span> 服务类型
                  <el-select :class="errCls('service_type')" v-model="editFields.service_type" placeholder="请选择服务类型" style="width: 100%; margin-top: 4px" @change="clearErr('service_type')">
                    <el-option value="保安" label="保安" />
                    <el-option value="保洁" label="保洁" />
                  </el-select>
                </label>
                <label class="field">
                  <span class="req">*</span> 合同名称
                  <input type="text" class="input" :class="errCls('contract_name')" v-model="editFields.contract_name" placeholder="如 2026年保洁外包服务合同" @input="clearErr('contract_name')" />
                </label>
                <label class="field">
                  <span class="req">*</span> 供应商
                  <input type="text" class="input" :class="errCls('supplier')" v-model="editFields.supplier" placeholder="如 XX保洁公司" @input="clearErr('supplier')" />
                </label>
                <label class="field">
                  <span class="req">*</span> 开始日期
                  <input type="date" class="input" :class="errCls('start_date')" v-model="editFields.start_date" @input="clearErr('start_date')" />
                </label>
                <label class="field">
                  <span class="req">*</span> 结束日期
                  <input type="date" class="input" :class="errCls('end_date')" v-model="editFields.end_date" @input="clearErr('end_date')" />
                </label>
              </div>
            </div>

            <!-- 迟到/早退分档 -->
            <div class="form-panel">
              <div class="row-between mb-12">
                <h4 class="panel-title">迟到/早退分档扣款 <span class="text-xs text-muted-light">（所有字段均为必填）</span></h4>
                <button type="button" class="tier-add" @click="lateEarlyTiers.push({ max_minutes: 90, amount: '' })">
                  + 添加分档
                </button>
              </div>
              <label class="field mb-12">
                <span class="req">*</span> 超过多少分钟按缺勤处理
                <input type="number" class="input" :class="errCls('late_early_over')" v-model="manualRules.late_early_over" placeholder="如 60" @input="clearErr('late_early_over')" />
              </label>
              <div class="tier-list">
                <div v-for="(tier, idx) in lateEarlyTiers" :key="idx" class="tier-row">
                  <div v-if="editingTierIdx === idx" class="row gap-1 text-sm">
                    <span class="text-muted">≤</span>
                    <input
                      type="number" step="1" min="1" class="input tier-min"
                      :value="tier.max_minutes"
                      @input="(e) => { tier.max_minutes = parseInt((e.target as HTMLInputElement).value) || 0 }"
                      @keydown.enter="editingTierIdx = -1"
                    />
                    <span class="text-muted">分钟</span>
                    <button type="button" class="link-brand text-xs ml-4" @click="editingTierIdx = -1">完成</button>
                  </div>
                  <span v-else class="text-muted">≤{{ tier.max_minutes }}分钟扣款</span>
                  <input
                    type="number" step="0.01"
                    class="input tier-amount"
                    :class="validationErrors[`tier_amount_${idx}`] ? 'err' : ''"
                    v-model="tier.amount" placeholder="如 20" @input="clearErr(`tier_amount_${idx}`)"
                  />
                  <span class="text-muted">元/次</span>
                  <button type="button" class="tier-edit-btn" @click="editingTierIdx = editingTierIdx === idx ? -1 : idx">
                    修改时间
                  </button>
                  <button
                    v-if="lateEarlyTiers.length > 1" type="button" title="删除此分档"
                    class="tier-del"
                    @click="lateEarlyTiers.splice(idx, 1); editingTierIdx = -1"
                  >✕</button>
                </div>
              </div>
              <p v-if="lateEarlyTiers.length === 0" class="text-xs text-muted-light mt-8">无分档，点击右上角"添加分档"新增</p>
            </div>

            <!-- 漏打卡 -->
            <div class="form-panel">
              <h4 class="panel-title">漏打卡扣款 <span class="text-xs text-muted-light">（金额和次数为必填）</span></h4>
              <div class="grid-2" style="gap: 12px">
                <label class="field">
                  <span class="req">*</span> 漏打卡扣款（元/人次）
                  <input type="number" step="0.01" class="input" :class="errCls('missing_clock_deduction')" v-model="manualRules.missing_clock_deduction" placeholder="如 50" @input="clearErr('missing_clock_deduction')" />
                </label>
                <label class="field">
                  <span class="req">*</span> 每月免扣次数
                  <input type="number" class="input" :class="errCls('missing_clock_free_times')" v-model="manualRules.missing_clock_free_times" placeholder="如 3" @input="clearErr('missing_clock_free_times')" />
                </label>
              </div>
              <label class="row gap-2 mt-12 text-sm">
                <input type="checkbox" v-model="manualRules.missing_clock_proof" />
                免扣需提供出勤证明
              </label>
            </div>

            <!-- 缺勤 -->
            <div class="form-panel">
              <h4 class="panel-title">缺勤/工时不足扣款 <span class="text-xs text-muted-light">（扣款系数必填）</span></h4>
              <label class="block text-sm">
                <span class="req">*</span> 缺勤扣款系数
                <input type="number" step="0.01" class="input" :class="errCls('deduction_coefficient')" v-model="manualRules.deduction_coefficient" placeholder="如 1.2" @input="clearErr('deduction_coefficient')" />
              </label>
            </div>
          </div>
          <p v-if="Object.values(validationErrors).some(Boolean)" class="notice notice-danger">
            请填写所有标 <span class="req">*</span> 的必填项
          </p>
          <div class="row gap-3 mt-24" style="justify-content:flex-end">
            <button class="btn-secondary" @click="closeEditor">取消</button>
            <button class="btn-primary" :disabled="savingRules" @click="saveManualRules">{{ savingRules ? '保存中...' : '保存' }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '../api'
import { fetchBusinessTypes, fetchContracts, invalidateConfig, CONFIG_KEYS } from '../api/configCache'
import { clearContractDraft, readContractDraft, writeContractDraft, type ContractParseDraft } from '../api/contractDraft'
import { useAuthStore } from '../stores/auth'

type ProjectContract = {
  id: number
  project_name: string
  project_code: string
  business_type: string
  supplier: string
  contract_no: string
  contract_name: string
  service_type: string
  version: string
  start_date: string
  end_date: string
  original_name: string
  file_format: string
  download_url: string
  is_active: number
  status: string
  rules: Record<string, unknown>
  updated_at: string
}

function formatRules(rules: Record<string, unknown>) {
  if (!rules || !Object.keys(rules).length) return '未解析出合同扣款细则'
  const parts: string[] = []
  const tiers = rules.late_early_tiers as Array<{ max_minutes: number; amount: number }> | undefined
  if (tiers?.length) {
    parts.push(`迟到/早退：${tiers.map((item) => `≤${item.max_minutes}分钟${item.amount}元`).join('，')}，超时按缺勤`)
  }
  if (rules.missing_clock_deduction) {
    const freeTimes = rules.missing_clock_free_times_per_month
    const proofText = rules.missing_clock_free_requires_attendance_proof ? '且需有效出勤证明，' : ''
    parts.push(`漏打卡：${freeTimes ? `每月前${freeTimes}次${proofText}不扣，` : ''}${rules.missing_clock_deduction}元/次`)
  }
  if (rules.contract_deduction_coefficient) {
    parts.push(`缺编/缺岗：工时单价×${rules.contract_deduction_coefficient}×缺勤总时长`)
  }
  return parts.join('；') || '已解析合同规则'
}

const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'group_admin')

const contracts = ref<ProjectContract[]>([])
const contractFile = ref<File | null>(null)
const message = ref('')
const businessTypeMapping = ref<Record<string, string[]>>({})
const allProjects = ref<string[]>([])

// 上传解析状态
const uploading = ref(false)
const uploadFileName = ref('')
const uploadMessage = ref('')

// 草稿状态
const draftMeta = ref<{ tempFile: string; fileName: string } | null>(null)
const draftBanner = ref<ContractParseDraft | null>(null)

// 编辑弹窗状态
const editingContract = ref<ProjectContract | null>(null)
const editFields = ref({ project_name: '', business_type: '', service_type: '', contract_name: '', supplier: '', start_date: '', end_date: '' })
const manualRules = ref({ late_early_over: '60', missing_clock_deduction: '50', missing_clock_free_times: '3', missing_clock_proof: true, deduction_coefficient: '1.2', daily_cap: '' })
const lateEarlyTiers = ref<Array<{ max_minutes: number; amount: string }>>([{ max_minutes: 30, amount: '' }, { max_minutes: 60, amount: '' }])
const editingTierIdx = ref(-1)
const savingRules = ref(false)
const validationErrors = ref<Record<string, boolean>>({})

function errCls(field: string) {
  return validationErrors.value[field] ? 'err' : ''
}
function clearErr(field: string) {
  if (validationErrors.value[field]) validationErrors.value[field] = false
}

async function loadContracts() {
  try {
    contracts.value = await fetchContracts<ProjectContract[]>(true)
  } catch {
    // 保留已有列表，不清空
  }
}

function isContractFile(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.pdf') || name.endsWith('.doc') || name.endsWith('.docx')
}

function selectContractFile(file: File) {
  if (!isContractFile(file)) {
    message.value = '合同仅支持 PDF、Word（.doc/.docx）文件'
    return
  }
  contractFile.value = file
  message.value = `已选择合同文件：${file.name}`
}

function handleUploadChange(uploadFile: { raw?: File; name: string }) {
  if (uploadFile.raw) selectContractFile(uploadFile.raw)
}

async function uploadContract() {
  if (!contractFile.value) {
    message.value = '请选择合同文件'
    return
  }
  const file = contractFile.value
  uploading.value = true
  uploadFileName.value = file.name
  uploadMessage.value = '合同解析中，正在自动识别合同信息和扣款条款，可能需要几十秒，请稍等。'
  contractFile.value = null
  try {
    // 只解析不入库：结果先进 sessionStorage 草稿，确认细则后才入库
    const form = new FormData()
    form.append('file', file)
    const parsed = await request<Record<string, any>>('/api/v2/contracts/parse', { method: 'POST', data: form })
    const fileName = parsed.original_name || file.name
    const tempFile = parsed.temp_file || ''
    if (!tempFile) throw new Error('解析结果缺少临时文件路径，请重新上传')
    const draft: ContractParseDraft = { parsed, tempFile, fileName, createdAt: Date.now() }
    writeContractDraft(draft)
    draftBanner.value = draft
    openDraftEditor(parsed, tempFile, fileName)
    message.value = '解析完成，已生成「未入库草稿」：请核对细则后保存入库；现在点取消也不会丢失本次解析。'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '合同解析失败'
  } finally {
    uploading.value = false
    uploadFileName.value = ''
  }
}

function validateContractForActivation(item: ProjectContract): string | null {
  const missing: string[] = []
  if (!item.project_name) missing.push('项目名称')
  if (!item.business_type) missing.push('业务类型')
  if (!item.contract_name) missing.push('合同名称')
  if (!item.supplier) missing.push('供应商')
  if (!item.start_date) missing.push('开始日期')
  if (!item.end_date) missing.push('结束日期')
  const rules = item.rules as Record<string, unknown>
  const tiers = rules['late_early_tiers'] as Array<{ max_minutes: number; amount: number }> | undefined
  if (!tiers?.length) missing.push('迟到/早退扣款')
  if (!rules['missing_clock_deduction']) missing.push('漏打卡扣款')
  if (!rules['contract_deduction_coefficient']) missing.push('缺编系数')
  if (missing.length === 0) return null
  return `以下必填项未填写：${missing.join('、')}，请先编辑补全后再启用`
}

async function setContractActive(item: ProjectContract, isActive: boolean) {
  if (isActive) {
    const error = validateContractForActivation(item)
    if (error) {
      window.alert(error)
      return
    }
  }
  try {
    await request(`/api/v2/contracts/${item.id}/status`, { method: 'PUT', data: { is_active: isActive } })
    message.value = isActive ? '合同已启用' : '合同已停用'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '合同状态更新失败'
  } finally {
    invalidateConfig(CONFIG_KEYS.CONTRACTS)
    loadContracts()
  }
}

async function deleteContract(item: ProjectContract) {
  if (!window.confirm(`确定删除合同「${item.contract_name || item.original_name}」吗？删除后将不再展示，但不会影响历史审核记录。`)) return
  try {
    if (item.is_active) {
      await request(`/api/v2/contracts/${item.id}/status`, { method: 'PUT', data: { is_active: false } })
    }
    await request(`/api/v2/contracts/${item.id}`, { method: 'DELETE' })
    message.value = '合同已删除'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '删除失败'
  } finally {
    invalidateConfig(CONFIG_KEYS.CONTRACTS)
    loadContracts()
  }
}

function openManualEditor(item: ProjectContract) {
  draftMeta.value = null
  editingContract.value = item
  validationErrors.value = {}
  editFields.value = {
    project_name: item.project_name || (isAdmin.value ? '' : auth.projectName) || '',
    business_type: item.business_type || '',
    service_type: item.service_type || '',
    contract_name: item.contract_name || '',
    supplier: item.supplier || '',
    start_date: item.start_date || '',
    end_date: item.end_date || '',
  }
  const rules = item.rules as Record<string, unknown>
  const tiers = (rules['late_early_tiers'] as Array<{ max_minutes: number; amount: number }>) || []
  lateEarlyTiers.value = tiers.length > 0
    ? tiers.map((t) => ({ max_minutes: t.max_minutes, amount: String(t.amount) }))
    : [{ max_minutes: 30, amount: '' }, { max_minutes: 60, amount: '' }]
  editingTierIdx.value = -1
  manualRules.value = {
    late_early_over: String(rules['late_early_over_minutes_as_absence'] || '60'),
    missing_clock_deduction: String(rules['missing_clock_deduction'] || ''),
    missing_clock_free_times: String(rules['missing_clock_free_times_per_month'] || ''),
    missing_clock_proof: rules['missing_clock_free_requires_attendance_proof'] !== false,
    deduction_coefficient: String(rules['contract_deduction_coefficient'] || ''),
    daily_cap: String(rules['single_person_daily_cap'] || ''),
  }
}

/** 打开「未入库草稿」编辑：展示缓存里本次解析的数据，保存才入库 */
function openDraftEditor(parsed: Record<string, any>, tempFile: string, fileName: string) {
  const pseudo: ProjectContract = {
    id: 0,
    project_name: parsed.project_name || '',
    project_code: '',
    business_type: parsed.business_type || '',
    supplier: parsed.supplier || '',
    contract_no: parsed.contract_no || '',
    contract_name: parsed.contract_name || '',
    service_type: parsed.service_type || '',
    version: parsed.version || '',
    start_date: parsed.start_date || '',
    end_date: parsed.end_date || '',
    original_name: fileName,
    file_format: '',
    download_url: '',
    is_active: 0,
    status: parsed.extract_status === 'failed' ? 'parse_failed' : 'draft',
    rules: parsed.rules || {},
    updated_at: '',
  }
  openManualEditor(pseudo)
  draftMeta.value = { tempFile, fileName }
}

function closeEditor() {
  editingContract.value = null
  validationErrors.value = {}
}

function discardDraft() {
  clearContractDraft()
  draftBanner.value = null
  message.value = '已丢弃未入库的解析草稿'
}

function validateRequiredFields(): boolean {
  const errors: Record<string, boolean> = {}
  for (const field of ['project_name', 'business_type', 'contract_name', 'supplier', 'start_date', 'end_date']) {
    if (!(editFields.value as Record<string, string>)[field]) errors[field] = true
  }
  for (const field of ['late_early_over', 'missing_clock_deduction', 'missing_clock_free_times', 'deduction_coefficient']) {
    if (!(manualRules.value as Record<string, string | boolean>)[field]) errors[field] = true
  }
  lateEarlyTiers.value.forEach((tier, idx) => {
    if (!tier.amount || parseFloat(tier.amount) <= 0) errors[`tier_amount_${idx}`] = true
  })
  validationErrors.value = errors
  return Object.keys(errors).length === 0
}

async function saveManualRules() {
  if (!editingContract.value) return
  if (!validateRequiredFields()) {
    message.value = '请填写所有必填项'
    return
  }
  savingRules.value = true
  try {
    const tiers = lateEarlyTiers.value
      .filter((t) => t.amount && parseFloat(t.amount) > 0)
      .map((t) => ({ max_minutes: t.max_minutes, amount: parseFloat(t.amount) }))
    const rulesPayload: Record<string, unknown> = { late_early_tiers: tiers }
    if (manualRules.value.late_early_over) rulesPayload['late_early_over_minutes_as_absence'] = parseFloat(manualRules.value.late_early_over)
    if (manualRules.value.missing_clock_deduction) rulesPayload['missing_clock_deduction'] = parseFloat(manualRules.value.missing_clock_deduction)
    if (manualRules.value.missing_clock_free_times) rulesPayload['missing_clock_free_times_per_month'] = parseFloat(manualRules.value.missing_clock_free_times)
    rulesPayload['missing_clock_free_requires_attendance_proof'] = manualRules.value.missing_clock_proof
    if (manualRules.value.deduction_coefficient) rulesPayload['contract_deduction_coefficient'] = parseFloat(manualRules.value.deduction_coefficient)
    if (manualRules.value.daily_cap) rulesPayload['single_person_daily_cap'] = parseFloat(manualRules.value.daily_cap)

    const payload: Record<string, unknown> = {
      project_name: editFields.value.project_name || undefined,
      business_type: editFields.value.business_type || undefined,
      service_type: editFields.value.service_type || undefined,
      contract_name: editFields.value.contract_name || undefined,
      supplier: editFields.value.supplier || undefined,
      start_date: editFields.value.start_date || undefined,
      end_date: editFields.value.end_date || undefined,
      rules: rulesPayload,
    }

    if (draftMeta.value) {
      // 草稿分支：凭 temp_file 走创建接口入库
      await request('/api/v2/contracts', {
        method: 'POST',
        data: { temp_file: draftMeta.value.tempFile, original_name: draftMeta.value.fileName, ...payload },
      })
      clearContractDraft()
      draftBanner.value = null
      draftMeta.value = null
      message.value = '合同已保存入库'
    } else {
      await request(`/api/v2/contracts/${editingContract.value.id}`, { method: 'PUT', data: payload })
      message.value = '合同信息已保存'
    }
    editingContract.value = null
    invalidateConfig(CONFIG_KEYS.CONTRACTS)
    await loadContracts()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    savingRules.value = false
  }
}

// 业态下拉映射键：项目账号锁定登录项目；集团管理员按当前编辑所选的项目
const businessTypeOptions = computed(() => {
  const key = isAdmin.value ? editFields.value.project_name : auth.projectName
  return businessTypeMapping.value[key] || []
})

onMounted(() => {
  // 恢复上次未保存的解析草稿
  const draft = readContractDraft()
  if (draft) draftBanner.value = draft
  loadContracts()
  fetchBusinessTypes()
    .then((data) => {
      businessTypeMapping.value = data.mapping || {}
      allProjects.value = data.projects || []
    })
    .catch(() => {})
})
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.desc { margin-top: 8px; }
.mt-8 { margin-top: 8px; }
.mt-12 { margin-top: 12px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.mt-24 { margin-top: 24px; }
.mb-12 { margin-bottom: 12px; }
.mb-16 { margin-bottom: 16px; }
.ml-4 { margin-left: 4px; }
.shrink-0 { flex-shrink: 0; }
.break { word-break: break-word; }
.text-sm { font-size: 14px; }
.td-top { vertical-align: top; }

/* 上传拖放区（el-upload drag） */
.contract-upload-row { display: flex; align-items: stretch; gap: 16px; margin-top: 16px; }
.contract-upload { flex: 1; }
.contract-upload :deep(.el-upload-dragger) {
  display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
  border-radius: 12px; background: #fff; padding: 16px; text-align: left;
  border: 1px dashed var(--slate-300);
}
.contract-upload :deep(.el-upload-dragger:hover) { border-color: var(--accent); }
.drop-name { font-weight: 500; color: var(--slate-800); }
.drop-note { margin-top: 4px; display: block; font-size: 12px; color: var(--slate-400); }
.draft-banner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }

/* 链接按钮 */
.link-brand { color: var(--brand-700); text-decoration: underline; }
.link-blue { color: #2563eb; text-decoration: underline; }
.link-red { color: var(--red-600); text-decoration: underline; }
.link-amber { color: #b45309; text-decoration: underline; font-weight: 500; }
.op-col { display: flex; flex-direction: column; gap: 4px; }
.contract-table { min-width: 980px; table-layout: fixed; }

/* 弹窗 */
.modal-mask {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.4); padding: 16px;
}
.modal-card-lg {
  display: flex; max-height: 90vh; width: 720px; flex-direction: column;
  overflow: hidden; border-radius: 16px; background: #fff;
  box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1);
}
.modal-scroll { overflow-y: auto; padding: 24px; }
.icon-btn { color: var(--slate-400); }
.icon-btn:hover { color: var(--slate-600); }
.form-stack { display: flex; flex-direction: column; gap: 16px; }
.form-panel { border-radius: 8px; background: var(--slate-50); padding: 16px; }
.panel-title { font-size: 14px; font-weight: 500; color: var(--slate-700); margin: 0 0 12px; }
.field { font-size: 14px; display: block; }
.req { color: #ef4444; }
.field .input { margin-top: 4px; width: 100%; }
.input.err { border-color: #ef4444; box-shadow: 0 0 0 1px #fecaca; }

/* 迟到分档 */
.tier-add {
  display: inline-flex; align-items: center; gap: 4px;
  border-radius: 6px; background: var(--brand-500); padding: 4px 10px;
  font-size: 12px; font-weight: 500; color: #fff;
}
.tier-add:hover { background: var(--brand-600); }
.tier-list { display: flex; flex-direction: column; gap: 8px; }
.tier-row {
  display: flex; align-items: center; gap: 8px;
  border-radius: 8px; background: #fff; padding: 8px 12px;
}
.tier-min { width: 80px; padding: 4px 8px; font-size: 14px; }
.tier-amount { width: 96px; padding: 4px 8px; font-size: 14px; }
.tier-edit-btn {
  display: inline-flex; align-items: center; border-radius: 6px;
  background: var(--slate-200); padding: 2px 8px; font-size: 12px; color: var(--slate-600);
}
.tier-edit-btn:hover { background: var(--slate-300); }
.tier-del {
  margin-left: auto; display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 999px; color: var(--slate-400);
}
.tier-del:hover { background: #fee2e2; color: var(--red-600); }
</style>
