<template>
  <div class="page-stack">
    <!-- 上传入口 + 审核进度：嵌在结果页顶部，一左一右 -->
    <AuditEntryPanel />

    <div v-if="loading" class="card empty-state">加载中…</div>
    <template v-else-if="!ctxStore.context">
      <!-- 未审核过时不渲染下方结果区，上传卡片即引导 -->
    </template>
    <div v-else-if="isServiceTypeUnaudited" class="page-stack">
      <div class="card card-pad">
        <h2 class="h3">审核确认</h2>
        <p class="text-muted desc">
          {{ projectName }} {{ auditMonth }} {{ businessType ? `· ${businessType}` : '' }}{{ effectiveServiceType ? ` · ${effectiveServiceType}` : '' }}
        </p>
        <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />
      </div>
      <div class="card empty-state">该服务类型的审核尚未完成，暂无相关数据可查看</div>
    </div>
    <div v-else class="page-stack">
    <div class="card card-pad">
      <div class="row-between row-wrap gap-3">
        <div>
          <h2 class="h3">审核确认</h2>
          <p class="text-muted desc">
            {{ projectName }} {{ auditMonth }} {{ businessType ? `· ${businessType}` : '' }}{{ effectiveServiceType ? ` · ${effectiveServiceType}` : '' }} · 版本 {{ String(detailData?.version ?? '-') }}
          </p>
        </div>
        <span class="badge badge-lg" :class="String(detailData?.status || '') === '已确认' ? 'badge-green' : 'badge-amber'">
          {{ String(detailData?.status || '已审核') }}
        </span>
      </div>
      <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />
      <div v-if="message" class="notice">{{ message }}</div>
    </div>

    <div v-if="detailLoading" class="card empty-state">数据加载中…</div>
    <template v-else>
      <AuditDashboard :data="dashboard" />
      <div class="row gap-2">
        <button v-for="[key, label] in tabs" :key="key" :class="key === tab ? 'btn-primary' : 'btn-secondary'" @click="switchTab(key)">{{ label }}</button>
      </div>
      <DataTable :rows="rows" :columns="tabColumns[tab]" :labels="columnLabels" :get-row-class-name="getResultRowClassName">
        <template v-if="tab === 'exceptions'" #cell="{ row, field }">
          <template v-if="field === 'overtime_warning'">
            <span v-if="!(row.overtime_warnings as any[])?.length" class="text-muted-light">—</span>
            <span
              v-else
              class="badge badge-amber"
              :title="(row.overtime_warnings as any[]).map((w) => `${w.date}：${w.total_hours}h (${(w.positions || []).join(' / ')})`).join('\n')"
            >⚠ {{ (row.overtime_warnings as any[]).length }} 天</span>
          </template>
          <template v-else-if="field === 'total_deduction'">
            <div>
              <div class="font-medium">{{ toNumber(row.total_deduction) ? toNumber(row.total_deduction).toFixed(2) : '0' }}</div>
              <div v-if="row.deduction_formula" class="formula-text">{{ row.deduction_formula }}</div>
            </div>
          </template>
          <template v-else>{{ String(row[field] ?? '') }}</template>
        </template>
      </DataTable>
    </template>

    <!-- 漏打卡出勤证明管理 -->
    <div v-if="tab === 'attendance-deductions' && dashboard.attendanceDeductions.some((d: Record<string, unknown>) => String(d.exception_type || '') === '漏打卡')" class="card p-5">
      <h3 class="h3">漏打卡 - 出勤证明管理</h3>
      <p class="text-muted desc">合同约定每人每月有免扣次数（见"人员异常统计"表），提供出勤证明可免扣款。审核员核实后协助计算免扣次数。点击"已提供证明"切换状态。</p>
      <div class="mt-4 overflow-auto">
        <el-table :data="dashboard.attendanceDeductions.filter((d: Record<string, unknown>) => String(d.exception_type || '') === '漏打卡')" border stripe style="width: 100%">
          <el-table-column prop="employee_name" label="姓名" min-width="112" />
          <el-table-column prop="position" label="岗位" min-width="112" />
          <el-table-column label="扣款金额" min-width="112">
            <template #default="{ row }">
              <span v-if="row.has_attendance_proof" class="text-success">0元（已免扣）</span>
              <span v-else class="text-danger">{{ row.deduction_amount }}元</span>
            </template>
          </el-table-column>
          <el-table-column label="出勤证明" min-width="160">
            <template #default="{ row }">
              <button
                class="badge badge-btn"
                :class="row.has_attendance_proof ? 'badge-green' : 'badge-amber'"
                :style="proofUpdating === String(row.employee_name || '') ? 'opacity:.5' : ''"
                :disabled="proofUpdating === String(row.employee_name || '')"
                @click="toggleAttendanceProof(String(row.employee_name || ''), '', Boolean(row.has_attendance_proof))"
              >
                {{ proofUpdating === String(row.employee_name || '') ? '更新中...' : row.has_attendance_proof ? '已提供证明 ✓' : '未提供证明，点击切换' }}
              </button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import DataTable from '../components/DataTable.vue'
import ServiceTypeTabs from '../components/ServiceTypeTabs.vue'
import AuditDashboard from '../components/AuditDashboard.vue'
import AuditEntryPanel from '../components/AuditEntryPanel.vue'
import { request } from '../api'
import { useAuthStore } from '../stores/auth'
import { useAuditContextStore, type AuditContext } from '../stores/auditContext'
import { useServiceTypes } from '../composables/useServiceTypes'

const tabs: Array<[string, string]> = [
  ['exceptions', '人员异常统计'],
  ['attendance-deductions', '人员考勤扣款'],
  ['deductions', '扣款汇总'],
]

const columnLabels: Record<string, string> = {
  work_date: '日期',
  employee_name: '姓名',
  position: '岗位',
  area: '区域',
  scheduled: '排班人员',
  actual_present: '实际到岗',
  status: '状态',
  note: '说明',
  exception_type: '异常类型',
  deduction_amount: '扣款金额',
  detail: '详情',
  missing_clock_count: '漏打卡次数',
  late_count: '迟到次数',
  early_leave_count: '早退次数',
  absence_count: '缺勤次数',
  absence_daily_rate: '日服务费',
  total_deduction: '扣款合计',
  summary_item: '汇总项目',
  missing_clock_free_limit: '免扣次数',
  overtime_warning: '工时异常',
}

const tabColumns: Record<string, string[]> = {
  exceptions: ['employee_name', 'position', 'missing_clock_count', 'late_count', 'early_leave_count', 'absence_count', 'overtime_warning', 'absence_daily_rate', 'total_deduction'],
  'attendance-deductions': ['employee_name', 'position', 'exception_type', 'deduction_amount'],
  deductions: ['summary_item', 'deduction_amount'],
}

type ConfirmState = { confirmed?: boolean; free_deduction?: boolean }

/** 异常确认键：{类型}|{员工}|{日期}[|{窗口}]（与后端 audit_common.confirm_key 同格式） */
function exceptionConfKey(type: string, emp: string, date: string, window = ''): string {
  return window ? `${type}|${emp}|${date}|${window}` : `${type}|${emp}|${date}`
}

/** 唯一「计入」规则：未标记免扣 且 未被显式取消确认 → 计入扣款 */
function isChargedConf(conf: ConfirmState | undefined): boolean {
  if (!conf) return true
  return (conf.confirmed ?? true) && !conf.free_deduction
}

function detailConfirmations(d: Record<string, unknown>): Record<string, ConfirmState> {
  return (d.confirmations || {}) as Record<string, ConfirmState>
}

import { getDetailCache, setDetailCache } from '../api/detailCache'

const auth = useAuthStore()
const ctxStore = useAuditContextStore()
const auditContext = computed(() => ctxStore.context)

const tab = ref(tabs[0][0])
const rows = ref<Record<string, unknown>[]>([])
const message = ref('')
const loading = ref(!auditContext.value)
const detailLoading = ref(false)
const dashboard = ref<any>({
  attendanceDetails: [],
  positionFulfillment: [],
  exceptions: [],
  attendanceDeductions: [],
  deductions: [],
  s04Summary: {},
  deductionDetails: [],
  crossProjectReview: [],
  crossProjectResolved: [],
})
const proofUpdating = ref('')
const detailData = ref<Record<string, unknown> | null>(null)

const projectName = computed(() => auditContext.value?.project_name || '')
const auditMonth = computed(() => auditContext.value?.audit_month || '')
const businessType = computed(() => auditContext.value?.business_type || '')
const serviceType = computed(() => auditContext.value?.service_type || '')

const ctxRef = computed<AuditContext | null>(() => auditContext.value)
const { options: serviceTypeOptions, active: activeServiceType } = useServiceTypes(ctxRef)
const effectiveServiceType = computed(() => activeServiceType.value || serviceType.value)

const activeOption = computed(() => serviceTypeOptions.value.find((o) => o.value === activeServiceType.value))
const isServiceTypeUnaudited = computed(() => activeOption.value ? !activeOption.value.hasResult : false)

// auditContext 为空时自动查最近的审核结果
onMounted(() => {
  if (auditContext.value) {
    loading.value = false
    return
  }
  request<Record<string, unknown>[]>('/api/v2/audit-results')
    .then((list) => {
      if (list && list.length > 0) {
        const userProjectName = auth.projectName
        const filtered = userProjectName
          ? list.filter((item) => String(item.project_name || '').includes(userProjectName.replace('项目', '')))
          : list
        const latest = filtered[0]
        if (latest) {
          ctxStore.set({
            project_name: String(latest.project_name || ''),
            audit_month: String(latest.audit_month || ''),
            business_type: String(latest.business_type || ''),
            service_type: String(latest.service_type || ''),
          })
        }
      }
      loading.value = false
    })
    .catch(() => {
      loading.value = false
    })
})

function parseResultsJson(raw: unknown) {
  if (!raw || typeof raw !== 'object') return { slotDetails: [], summary: [], s04: {}, deductionDetails: [], crossProjectReview: [], crossProjectResolved: [] }
  const r = raw as Record<string, unknown>
  const slotDetails = Array.isArray(r.slot_details) ? r.slot_details as Record<string, unknown>[] : []
  const summary = Array.isArray(r.summary) ? r.summary as Record<string, unknown>[] : []
  const s04 = (r.s04_attendance_audit && typeof r.s04_attendance_audit === 'object') ? r.s04_attendance_audit as Record<string, unknown> : {}
  const deductionDetails = Array.isArray(s04.deduction_details) ? s04.deduction_details as Record<string, unknown>[] : []
  const crossProjectReview = Array.isArray(r.cross_project_substitute_review) ? r.cross_project_substitute_review as Array<Record<string, unknown>> : []
  const crossProjectResolved = Array.isArray(r.cross_project_substitute_resolved) ? r.cross_project_substitute_resolved as Array<Record<string, unknown>> : []
  return { slotDetails, summary, s04, deductionDetails, crossProjectReview, crossProjectResolved }
}

function buildTabRows(tabKey: string, parsed: ReturnType<typeof parseResultsJson>): Record<string, unknown>[] {
  if (tabKey === 'position-fulfillment') {
    return parsed.slotDetails.map((s) => ({
      work_date: s.work_date || '',
      position: s.position || '',
      area: s.area || '',
      scheduled: Array.isArray(s.scheduled) ? (s.scheduled as string[]).join('、') : '',
      actual_present: Array.isArray(s.actual_present) ? (s.actual_present as string[]).join('、') : '',
      status: s.status || '',
      note: s.note || '',
    }))
  }
  if (tabKey === 'attendance-details') {
    const rows: Record<string, unknown>[] = []
    for (const d of parsed.deductionDetails) {
      const empName = String(d.employee_name || '')
      const position = String(d.position || '')
      const confs = detailConfirmations(d)
      const missingDates = Array.isArray(d.missing_clock_dates) ? d.missing_clock_dates as string[] : []
      const absenceDates = Array.isArray(d.absence_dates) ? d.absence_dates as string[] : []
      const lateDetails = Array.isArray(d.late_details) ? d.late_details as Record<string, unknown>[] : []
      const earlyDetails = Array.isArray(d.early_leave_details) ? d.early_leave_details as Record<string, unknown>[] : []
      const midIssues = Array.isArray(d.mid_clock_issues) ? d.mid_clock_issues as Record<string, unknown>[] : []
      const absenceDailyRate = Number(d.absence_daily_rate || 0)
      const absenceMultiplier = Number(d.absence_multiplier || 2.5)
      const absenceRateByDate = new Map<string, number>()
      const absenceMarkByDate = new Map<string, string>()
      for (const ar of (Array.isArray(d.absence_records) ? d.absence_records : []) as Record<string, unknown>[]) {
        if (ar.date && ar.daily_rate != null) absenceRateByDate.set(String(ar.date), Number(ar.daily_rate))
        if (ar.date && ar.mark) absenceMarkByDate.set(String(ar.date), String(ar.mark))
      }

      for (const date of missingDates) {
        if (!isChargedConf(confs[exceptionConfKey('missing_clock', empName, date)])) continue
        rows.push({ employee_name: empName, position, work_date: date, exception_type: '漏打卡', deduction_amount: 0 })
      }
      for (const mi of midIssues) {
        const date = String(mi.date || '')
        const window = String(mi.window || '')
        const conf = confs[exceptionConfKey('missing_clock', empName, date, window)]
          || confs[exceptionConfKey('mid_clock', empName, date, window)]
        if (!isChargedConf(conf)) continue
        rows.push({ employee_name: empName, position, work_date: date, exception_type: '漏打卡', deduction_amount: 0, detail: `中间卡缺失 ${window} 应打${mi.required || 0}次实打${mi.actual || 0}次` })
      }
      for (const date of absenceDates) {
        if (!isChargedConf(confs[exceptionConfKey('absence', empName, date)])) continue
        const dayRate = absenceRateByDate.get(date) ?? absenceDailyRate
        // 金额口径：四舍五入到两位小数，与后端逐日取整求和恒等
        const absenceAmount = Number((dayRate * absenceMultiplier).toFixed(2))
        const mark = absenceMarkByDate.get(date)
        const isReduction = mark === '减岗'
        rows.push({ employee_name: empName, position, work_date: date, exception_type: isReduction ? '减岗' : '缺勤', deduction_amount: absenceAmount, detail: isReduction ? `减岗（计划性减员），日服务费${dayRate}元×${absenceMultiplier}` : `日服务费${dayRate}元×${absenceMultiplier}` })
      }
      for (const ld of lateDetails) {
        const lateAmount = Number((Number(ld.amount) || 0).toFixed(2))
        if (lateAmount <= 0) continue  // 超阈值已转漏打卡，不渲染
        if (!isChargedConf(confs[exceptionConfKey('late', empName, String(ld.date || ''))])) continue
        rows.push({ employee_name: empName, position, work_date: ld.date || '', exception_type: '迟到', deduction_amount: lateAmount, detail: `迟到${ld.minutes || 0}分钟` })
      }
      for (const ed of earlyDetails) {
        const earlyAmount = Number((Number(ed.amount) || 0).toFixed(2))
        if (earlyAmount <= 0) continue
        if (!isChargedConf(confs[exceptionConfKey('early_leave', empName, String(ed.date || ''))])) continue
        rows.push({ employee_name: empName, position, work_date: ed.date || '', exception_type: '早退', deduction_amount: earlyAmount, detail: `早退${ed.minutes || 0}分钟` })
      }
    }
    return rows
  }
  if (tabKey === 'exceptions') {
    return parsed.deductionDetails.map((d) => ({
      employee_name: d.employee_name || '',
      position: d.position || '',
      missing_clock_count: Number(d.missing_clock_count || 0),
      missing_clock_free_limit: d.missing_clock_free_limit ?? 0,
      late_count: Number(d.late_count || 0),
      early_leave_count: Number(d.early_leave_count || 0),
      absence_count: Number(d.absence_count || 0),
      absence_daily_rate: Number(d.absence_daily_rate || 0),
      total_deduction: Number(d.total_deduction || 0),
      overtime_count: Array.isArray(d.overtime_warnings) ? d.overtime_warnings.length : 0,
      overtime_warnings: d.overtime_warnings || [],
      deduction_formula: buildDeductionFormula(d),
    }))
  }
  if (tabKey === 'attendance-deductions') {
    const rows: Record<string, unknown>[] = []
    for (const d of parsed.deductionDetails) {
      const empName = String(d.employee_name || '')
      const position = String(d.position || '')
      const missingAmount = Number(d.missing_clock_amount || 0)
      const lateTotal = Number(d.late_total || 0)
      const earlyTotal = Number(d.early_leave_total || 0)
      const absenceAmount = Number(d.absence_amount || 0)
      if (missingAmount > 0) rows.push({ employee_name: empName, position, exception_type: '漏打卡', deduction_amount: missingAmount })
      if (lateTotal > 0) rows.push({ employee_name: empName, position, exception_type: '迟到', deduction_amount: lateTotal })
      if (earlyTotal > 0) rows.push({ employee_name: empName, position, exception_type: '早退', deduction_amount: earlyTotal })
      if (absenceAmount > 0) rows.push({ employee_name: empName, position, exception_type: '缺勤', deduction_amount: absenceAmount })
    }
    return rows
  }
  if (tabKey === 'deductions') {
    const s04Summary = parsed.s04.summary as Record<string, unknown> | undefined || {}
    return [
      { summary_item: '漏打卡扣款', deduction_amount: Number(s04Summary.total_missing_clock_amount || 0) },
      { summary_item: '迟到扣款', deduction_amount: Number(s04Summary.total_late_amount || 0) },
      { summary_item: '早退扣款', deduction_amount: Number(s04Summary.total_early_leave_amount || 0) },
      { summary_item: '缺勤扣款', deduction_amount: Number(s04Summary.total_absence_amount || 0) },
      { summary_item: '合计扣款', deduction_amount: Number(s04Summary.total_deduction || 0) },
    ]
  }
  return []
}

function applyDetail(detail: Record<string, unknown>) {
  detailData.value = detail
  const resultsJson = typeof detail.results_json === 'string' ? JSON.parse(detail.results_json as string) : detail.results_json
  const parsed = parseResultsJson(resultsJson)
  dashboard.value = {
    attendanceDetails: buildTabRows('attendance-details', parsed),
    positionFulfillment: buildTabRows('position-fulfillment', parsed),
    exceptions: buildTabRows('exceptions', parsed),
    attendanceDeductions: buildTabRows('attendance-deductions', parsed),
    deductions: buildTabRows('deductions', parsed),
    s04Summary: parsed.s04.summary as Record<string, unknown> || {},
    deductionDetails: parsed.deductionDetails,
    crossProjectReview: parsed.crossProjectReview,
    crossProjectResolved: parsed.crossProjectResolved,
  }
  rows.value = buildTabRows(tab.value, parsed)
}

function loadDetail() {
  if (!auditContext.value) return
  // 目标服务类型尚未审核：清空数据并交由页面层提示
  const opt = serviceTypeOptions.value.find((o) => o.value === effectiveServiceType.value)
  if (opt && !opt.hasResult) {
    detailLoading.value = false
    detailData.value = null
    rows.value = []
    dashboard.value = { attendanceDetails: [], positionFulfillment: [], exceptions: [], attendanceDeductions: [], deductions: [], s04Summary: {}, deductionDetails: [], crossProjectReview: [], crossProjectResolved: [] }
    return
  }
  const params = new URLSearchParams({
    project_name: projectName.value,
    business_type: businessType.value,
    audit_month: auditMonth.value,
    service_type: effectiveServiceType.value,
  })
  const cacheKey = `${projectName.value}|${businessType.value}|${auditMonth.value}|${effectiveServiceType.value}`

  const cached = getDetailCache(cacheKey)
  if (cached) {
    applyDetail(cached)
    detailLoading.value = false
    // 后台静默刷新
    request<Record<string, unknown>>(`/api/v2/audit-results/detail?${params}`)
      .then((detail) => {
        setDetailCache(cacheKey, detail)
        applyDetail(detail)
      })
      .catch(() => {})
    return
  }

  detailLoading.value = true
  request<Record<string, unknown>>(`/api/v2/audit-results/detail?${params}`)
    .then((detail) => {
      setDetailCache(cacheKey, detail)
      applyDetail(detail)
      detailLoading.value = false
    })
    .catch(() => {
      detailData.value = null
      rows.value = []
      dashboard.value = { attendanceDetails: [], positionFulfillment: [], exceptions: [], attendanceDeductions: [], deductions: [], s04Summary: {}, deductionDetails: [], crossProjectReview: [], crossProjectResolved: [] }
      detailLoading.value = false
    })
}

watch([auditContext, effectiveServiceType, serviceTypeOptions], loadDetail, { immediate: true })

function switchTab(key: string) {
  tab.value = key
  if (!auditContext.value || !detailData.value) return
  const resultsJson = typeof detailData.value.results_json === 'string' ? JSON.parse(detailData.value.results_json as string) : detailData.value.results_json
  const parsed = parseResultsJson(resultsJson)
  rows.value = buildTabRows(key, parsed)
}

async function toggleAttendanceProof(employeeName: string, _workDate: string, _currentProof: boolean) {
  proofUpdating.value = employeeName
  try {
    // V2 暂无 attendance-proof 端点，待后端补充
    message.value = '出勤证明切换已记录（V2 待实现）'
  } finally {
    proofUpdating.value = ''
  }
}

function getResultRowClassName(row: Record<string, unknown>) {
  const exception = String(row.exception_type || '')
  const status = String(row.result_status || row.status || '')
  if ((exception && exception !== '正常') || status === '异常' || toNumber(row.shortage_count) > 0 || toNumber(row.deduction_amount) > 0) {
    return 'row-danger'
  }
  return ''
}

/** 扣款合计的计算公式 */
function buildDeductionFormula(d: Record<string, unknown>): string {
  const parts: string[] = []
  const missingCount = toNumber(d.missing_clock_count)
  const missingAmount = toNumber(d.missing_clock_amount)
  if (missingCount > 0) {
    const unitPrice = missingAmount / missingCount
    parts.push(`漏打卡${missingCount}次×${trimNum(unitPrice)}元/次`)
  }
  const absenceCount = toNumber(d.absence_count)
  const dailyRate = toNumber(d.absence_daily_rate)
  const multiplier = toNumber(d.absence_multiplier)
  if (absenceCount > 0) {
    parts.push(`缺勤${absenceCount}次×日服务费${trimNum(dailyRate)}元×${trimNum(multiplier)}`)
  }
  const lateTotal = toNumber(d.late_total)
  if (lateTotal > 0) parts.push(`迟到扣${trimNum(lateTotal)}元`)
  const earlyTotal = toNumber(d.early_leave_total)
  if (earlyTotal > 0) parts.push(`早退扣${trimNum(earlyTotal)}元`)
  return parts.join(' + ')
}

function trimNum(value: number): string {
  return String(Math.round(value * 100) / 100)
}

function toNumber(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}
</script>

<style scoped>
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.desc { margin-top: 4px; }
.mt-16 { margin-top: 16px; }
.badge-lg { padding: 4px 12px; }
.formula-text { margin-top: 4px; font-size: 12px; line-height: 1.6; color: var(--slate-500); word-break: break-word; }
.text-muted-light { color: var(--slate-400); }
.font-medium { font-weight: 500; }
.badge-btn { cursor: pointer; padding: 4px 12px; border-radius: 4px; }
.badge-btn:disabled { cursor: not-allowed; }
</style>
