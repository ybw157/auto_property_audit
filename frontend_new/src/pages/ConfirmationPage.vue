<template>
  <div v-if="!auditContext" class="text-muted">请先完成一次审核</div>
  <div v-else-if="isServiceTypeUnaudited" class="page-stack">
    <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />
    <div class="card empty-state">该服务类型的审核尚未完成，暂无相关数据可查看</div>
  </div>
  <div v-else-if="loading" class="page-stack">
    <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />
    <div class="text-muted">加载中...</div>
  </div>
  <div v-else-if="!s04Data || !s04Data.deduction_details.length" class="page-stack">
    <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />
    <div class="card empty-state">该服务类型本次审核无异常记录</div>
  </div>
  <div v-else class="page-stack">
    <ServiceTypeTabs :options="serviceTypeOptions" :value="activeServiceType" @change="(v) => (activeServiceType = v)" />

    <!-- 顶部信息栏 -->
    <div class="card row-between card-headbar">
      <div>
        <h2 class="h2">考勤异常确认表</h2>
        <p class="text-muted desc">
          {{ auditContext.project_name }} {{ auditContext.audit_month }}{{ effectiveServiceType ? ` | ${effectiveServiceType}` : '' }} | 共 {{ totalExceptions }} 条异常 | 已确认 {{ confirmedCount }} 条 | 免打卡 {{ freeDeductionCount }} 条
        </p>
      </div>
      <div class="row gap-3">
        <button class="btn-secondary" :disabled="saving || submitting" @click="saveConfirm">
          {{ saving ? '提交中...' : '提交确认' }}
        </button>
        <button class="btn-primary" :disabled="saving || submitting" @click="generateReport">
          {{ submitting ? '生成报告中...' : '生成扣款报告' }}
        </button>
      </div>
    </div>

    <div v-if="message" class="notice notice-success">{{ message }}</div>

    <!-- 操作说明 -->
    <div class="notice notice-info">
      <p class="font-medium">操作说明：</p>
      <p class="mt-1">1. 勾选异常记录表示项目确认该异常属实，将计入扣款</p>
      <p>2. 未勾选的记录表示项目有异议，将不计入扣款</p>
      <p>3. 仅「漏打卡」记录可使用"免打卡"（不扣款，每人每月有免打卡次数上限）；缺勤/减岗/迟到/早退不适用</p>
      <p>4. 点击"提交确认"保存确认与免打卡状态，并据此定稿本次审核结果</p>
      <p>5. 点击"生成扣款报告"按定稿结果生成审核汇总与扣款报告</p>
      <p>6. 可多次修改确认结果并重新提交、重新生成报告（每次提交都会按最新确认结果重新定稿）</p>
    </div>

    <!-- 报告生成结果 -->
    <div v-if="confirmResult" class="card card-pad">
      <h3 class="h3">扣款报告已生成</h3>
      <div class="grid-4 mt-12">
        <div class="result-cell">
          <div class="result-num">{{ confirmResult.confirmed_count }}</div>
          <div class="text-muted text-sm">确认异常条数</div>
        </div>
        <div class="result-cell red">
          <div class="result-num red">¥{{ confirmResult.total_deduction.toFixed(2) }}</div>
          <div class="text-muted text-sm">总扣款金额（元）</div>
        </div>
        <div class="result-cell amber">
          <div class="result-num amber">{{ confirmResult.first_exception_rate }}%</div>
          <div class="text-muted text-sm">第一次审核异常率</div>
        </div>
        <div class="result-cell blue">
          <div class="result-num blue">{{ confirmResult.confirmed_exception_rate }}%</div>
          <div class="text-muted text-sm">确认后异常率</div>
        </div>
      </div>
      <p class="text-muted mt-12">{{ confirmResult.message }}</p>
      <p class="text-xs text-muted-light mt-8">可到"审核结果"页面查看扣款明细</p>
    </div>

    <div class="confirm-body">
      <!-- 左侧员工列表 -->
      <div class="emp-side">
        <div class="card emp-card">
          <h3 class="emp-title">员工列表</h3>
          <div class="emp-list">
            <button
              v-for="emp in employeeList"
              :key="emp"
              class="emp-btn"
              :class="{ active: selectedEmployee === emp }"
              @click="selectedEmployee = emp"
            >
              <div class="emp-name-col">
                <span>{{ emp }}</span>
                <span v-if="empFreeUsed(emp) > 0" class="text-xs text-warn">
                  免打卡剩{{ freeLimitOf(emp) - empFreeUsed(emp) }}/{{ freeLimitOf(emp) }}
                </span>
              </div>
              <span class="text-xs text-muted-light">{{ empConfirmedCount(emp) }}/{{ empTotalCount(emp) }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧异常记录表格 -->
      <div class="main-side">
        <div v-if="currentDetail" class="card" style="overflow: hidden">
          <div class="row-between rec-head">
            <h3 class="rec-title">
              {{ selectedEmployee }} 的异常记录（{{ currentRecords.length }}条）
            </h3>
            <button class="link-btn" @click="selectAllForEmployee(selectedEmployee)">
              全选/取消全选
            </button>
          </div>
          <div class="table-scroll">
            <el-table
              :data="currentRecords"
              border
              style="width: 100%"
              :row-class-name="({ row }: any) => freeDeductionMap[row.key] ? 'tr-free' : confirmMap[row.key] ? 'tr-ok' : ''"
            >
              <el-table-column label="确认" align="center" width="56">
                <template #default="{ row }">
                  <input
                    type="checkbox"
                    :checked="confirmMap[row.key] ?? false"
                    class="chk"
                    @change="toggleConfirm(row.key)"
                  />
                </template>
              </el-table-column>
              <el-table-column prop="work_date" label="日期" width="100" />
              <el-table-column prop="position" label="岗位" width="100" />
              <el-table-column label="异常类型" width="110">
                <template #default="{ row }">
                  <span class="badge" :class="exceptionBadgeClass(row.exception_type, row.exception_label)">
                    {{ row.exception_label }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="规定考勤时间" width="130">
                <template #default="{ row }"><span class="text-xs nowrap">{{ row.shift_time || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="实际BI打卡" width="150">
                <template #default="{ row }"><span class="text-xs pre-wrap">{{ row.clock_times || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="异常说明" min-width="220">
                <template #default="{ row }"><span class="text-xs text-muted">{{ row.detail }}</span></template>
              </el-table-column>
              <el-table-column label="金额" align="right" width="90">
                <template #default="{ row }">
                  <span class="font-medium" :class="freeDeductionMap[row.key] ? 'strike' : 'amount-on'">¥{{ row.amount.toFixed(2) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="是否免打卡" align="center" width="120">
                <template #default="{ row }">
                  <!-- 免打卡仅适用于漏打卡 -->
                  <div v-if="row.exception_type === 'missing_clock'" class="row gap-1" style="justify-content:center">
                    <button
                      class="free-btn"
                      :class="freeDeductionMap[row.key] ? 'on' : isFreeDisabled(row) ? 'off' : ''"
                      :disabled="isFreeDisabled(row)"
                      :title="freeDeductionMap[row.key] ? '点击取消免打卡' : `免打卡机会剩余：${freeLimitOf(row.employee_name) - empFreeUsed(row.employee_name)}次`"
                      @click="handleFreeDeduction(row.key)"
                    >
                      {{ freeDeductionMap[row.key] ? '已免打卡' : '免打卡' }}
                    </button>
                    <span v-if="empFreeUsed(row.employee_name) >= freeLimitOf(row.employee_name) && !freeDeductionMap[row.key]" class="text-xs text-danger">剩余次数不足</span>
                  </div>
                  <span v-else class="text-xs text-muted-light">—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { request } from '../api'
import { useAuthStore } from '../stores/auth'
import { useAuditContextStore } from '../stores/auditContext'
import { useServiceTypes } from '../composables/useServiceTypes'
import ServiceTypeTabs from '../components/ServiceTypeTabs.vue'
import { invalidateDetailCache } from '../api/detailCache'

interface DeductionDetail {
  employee_name: string
  position: string
  missing_clock_count: number
  missing_clock_free_limit: number
  missing_clock_free_remaining: number
  missing_clock_deductible: number
  missing_clock_amount: number
  missing_clock_dates: string[]
  missing_clock_records?: Array<{ date: string; position?: string; shift_start: string; shift_end: string; clock_times: string[] }>
  missing_clock_extra: number
  late_details: any[]
  late_total: number
  early_leave_details: any[]
  early_leave_total: number
  mid_clock_issues: any[]
  absence_dates: string[]
  absence_records?: Array<{ date: string; position?: string; shift_start: string; shift_end: string; clock_times: string[]; daily_rate?: number; amount?: number; mark?: string }>
  absence_amount: number
  absence_daily_rate: number
  absence_multiplier?: number
  total_deduction: number
  confirmations?: Record<string, { confirmed: boolean; note: string; confirmed_by: string; confirmed_at: string; free_deduction?: boolean }>
}

interface ExceptionRecord {
  key: string
  employee_name: string
  work_date: string
  position: string
  exception_type: string
  exception_label: string
  amount: number
  detail: string
  shift_time: string
  clock_times: string
  confirmed?: boolean
  note?: string
  free_deduction?: boolean
  window?: string
}

interface S04AuditData {
  deduction_details: DeductionDetail[]
  summary: {
    total_missing_clock_amount: number
    total_late_amount: number
    total_early_leave_amount: number
    total_absence_amount: number
    total_deduction: number
    affected_employees: number
  }
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function buildExceptionRecords(details: DeductionDetail[]): ExceptionRecord[] {
  const records: ExceptionRecord[] = []
  for (const d of details) {
    const confs = d.confirmations || {}
    const missingByDate = new Map<string, { position?: string; shift_start: string; shift_end: string; clock_times: string[] }>()
    for (const r of d.missing_clock_records || []) missingByDate.set(r.date, r)
    const absenceByDate = new Map<string, { position?: string; shift_start: string; shift_end: string; clock_times: string[]; daily_rate?: number; amount?: number; mark?: string }>()
    for (const r of d.absence_records || []) absenceByDate.set(r.date, r)
    const midByKey = new Map<string, { position?: string; shift_start: string; shift_end: string; clock_times: string[] }>()
    for (const m of d.mid_clock_issues || []) {
      if (m.date) midByKey.set(`${m.date}|${m.window || ''}`, m)
    }

    for (const dateStr of d.missing_clock_dates || []) {
      const missingKey = `missing_clock|${d.employee_name}|${dateStr}`
      const conf = confs[missingKey]
      const rec = missingByDate.get(dateStr)
      records.push({
        key: missingKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        position: rec?.position || d.position,
        exception_type: 'missing_clock',
        exception_label: '漏打卡',
        amount: 50,
        detail: `漏打卡，扣款50元`,
        shift_time: rec ? `${rec.shift_start || ''}-${rec.shift_end || ''}` : '',
        clock_times: rec ? (rec.clock_times || []).join('\n') : '',
        confirmed: conf?.confirmed ?? true,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const issue of d.mid_clock_issues || []) {
      const dateStr = issue.date || ''
      const windowTag = issue.window || ''
      const mcKey = windowTag
        ? `missing_clock|${d.employee_name}|${dateStr}|${windowTag}`
        : `missing_clock|${d.employee_name}|${dateStr}`
      const legacyKey = windowTag
        ? `mid_clock|${d.employee_name}|${dateStr}|${windowTag}`
        : `mid_clock|${d.employee_name}|${dateStr}`
      const confKey = mcKey in confs ? mcKey : legacyKey
      const conf = confs[confKey]
      const missing = issue.missing || 0
      const meta = midByKey.get(`${dateStr}|${windowTag}`)
      records.push({
        key: mcKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        window: windowTag,
        position: meta?.position || issue.position || d.position,
        exception_type: 'missing_clock',
        exception_label: '漏打卡',
        amount: missing * 50,
        detail: `${windowTag} 缺${missing}次，扣款${missing * 50}元`,
        shift_time: meta ? `${meta.shift_start || ''}-${meta.shift_end || ''}` : '',
        clock_times: meta ? (meta.clock_times || []).join('\n') : '',
        confirmed: conf?.confirmed ?? true,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const late of d.late_details || []) {
      if ((late.amount || 0) <= 0) continue  // 超阈值已转漏打卡，不渲染
      const dateStr = late.date || ''
      const confKey = `late|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const tierLabel = late.tier === 'S04-2' ? '迟到≤30min' : late.tier === 'S04-3' ? '迟到30-60min' : '迟到>60min(转缺勤)'
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        position: late.position || d.position,
        exception_type: 'late',
        exception_label: '迟到',
        amount: late.amount || 0,
        detail: `${tierLabel}，迟到${late.minutes || 0}分钟，扣款${late.amount || 0}元`,
        shift_time: late.shift_start ? `${late.shift_start}-${late.shift_end || ''}` : '',
        clock_times: (late.clock_times && late.clock_times.length > 0) ? late.clock_times.join('\n') : (late.clock_in ? String(late.clock_in) : ''),
        confirmed: conf?.confirmed ?? true,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const early of d.early_leave_details || []) {
      if ((early.amount || 0) <= 0) continue
      const dateStr = early.date || ''
      const confKey = `early_leave|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const tierLabel = early.tier === 'S04-2' ? '早退≤30min' : early.tier === 'S04-3' ? '早退30-60min' : '早退>60min(转缺勤)'
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        position: early.position || d.position,
        exception_type: 'early_leave',
        exception_label: '早退',
        amount: early.amount || 0,
        detail: `${tierLabel}，早退${early.minutes || 0}分钟，扣款${early.amount || 0}元`,
        shift_time: early.shift_start ? `${early.shift_start}-${early.shift_end || ''}` : '',
        clock_times: (early.clock_times && early.clock_times.length > 0) ? early.clock_times.join('\n') : (early.clock_out ? String(early.clock_out) : ''),
        confirmed: conf?.confirmed ?? true,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
    for (const dateStr of d.absence_dates || []) {
      const confKey = `absence|${d.employee_name}|${dateStr}`
      const conf = confs[confKey]
      const rec = absenceByDate.get(dateStr)
      const mark = rec?.mark || '缺岗'
      const isReduction = mark === '减岗'
      // 金额口径：四舍五入到两位小数，与后端逐日取整求和恒等
      const dailyRate = Number(rec?.daily_rate ?? d.absence_daily_rate ?? 0)
      const multiplier = Number(d.absence_multiplier || 2.5)
      const amount = round2(dailyRate * multiplier)
      records.push({
        key: confKey,
        employee_name: d.employee_name,
        work_date: dateStr,
        position: rec?.position || d.position,
        exception_type: 'absence',
        exception_label: isReduction ? '减岗' : '脱岗/缺勤',
        amount,
        detail: isReduction
          ? `减岗（计划性减员），日服务费${dailyRate}×${multiplier}=${amount}元`
          : `脱岗/缺勤，日服务费${dailyRate}×${multiplier}=${amount}元`,
        shift_time: rec ? `${rec.shift_start || ''}-${rec.shift_end || ''}` : '',
        clock_times: rec ? (rec.clock_times || []).join('\n') : '',
        confirmed: conf?.confirmed ?? true,
        note: conf?.note || '',
        free_deduction: conf?.free_deduction ?? false,
      })
    }
  }
  // 按日期升序排序
  records.sort((a, b) => (a.work_date || '').localeCompare(b.work_date || ''))
  return records
}

function exceptionBadgeClass(type: string, label?: string): string {
  if (label === '减岗') return 'badge-sky'
  if (type === 'absence') return 'badge-red'
  if (type === 'missing_clock') return 'badge-amber'
  if (type === 'late' || type === 'early_leave') return 'badge-orange'
  if (type === 'mid_clock') return 'badge-purple'
  return 'badge-slate'
}

// ── 勾选草稿（localStorage 差异存储）──
// 只存"与基准状态不同"的 key，附异常记录集合指纹（djb2），重新审核导致记录集合变化时草稿自动失效
function draftStorageKey(project: string, businessType: string, month: string, serviceType: string): string {
  return `confirm_draft:${project}:${businessType}:${month}:${serviceType}`
}

function recordsFingerprint(records: Array<{ key: string }>): string {
  const s = records.map((r) => r.key).sort().join('|')
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0
  return h.toString(36)
}

const auth = useAuthStore()
const ctxStore = useAuditContextStore()
const auditContext = computed(() => ctxStore.context)

const s04Data = ref<S04AuditData | null>(null)
const loading = ref(false)
const selectedEmployee = ref('')
const confirmMap = ref<Record<string, boolean>>({})
const freeDeductionMap = ref<Record<string, boolean>>({})
const saving = ref(false)
const submitting = ref(false)
const message = ref('')
const confirmResult = ref<{
  confirmed_count: number
  total_deduction: number
  first_exception_rate: number
  confirmed_exception_rate: number
  message: string
} | null>(null)
const allRecords = ref<ExceptionRecord[]>([])

const ctxRef = computed(() => ctxStore.context)
const { options: serviceTypeOptions, active: activeServiceType } = useServiceTypes(ctxRef)
const effectiveServiceType = computed(() => activeServiceType.value || auditContext.value?.service_type || '')

const activeOption = computed(() => serviceTypeOptions.value.find((o) => o.value === activeServiceType.value))
const isServiceTypeUnaudited = computed(() => activeOption.value ? !activeOption.value.hasResult : false)

watch([auditContext, effectiveServiceType, serviceTypeOptions], () => {
  if (!auditContext.value) return
  const opt = serviceTypeOptions.value.find((o) => o.value === effectiveServiceType.value)
  if (opt && !opt.hasResult) {
    s04Data.value = null
    allRecords.value = []
    selectedEmployee.value = ''
    confirmMap.value = {}
    freeDeductionMap.value = {}
    confirmResult.value = null
    message.value = ''
    loading.value = false
    return
  }
  // 切换服务类型时清空上一类型的选择状态
  selectedEmployee.value = ''
  confirmMap.value = {}
  freeDeductionMap.value = {}
  confirmResult.value = null
  loadData()
}, { immediate: true })

// 默认选中第一个有异常记录的员工
watch([s04Data, allRecords], () => {
  if (s04Data.value?.deduction_details.length && !selectedEmployee.value) {
    const empSet = new Set(allRecords.value.map((r) => r.employee_name))
    const firstWithRecords = s04Data.value.deduction_details.find((d) => empSet.has(d.employee_name))
    if (firstWithRecords) selectedEmployee.value = firstWithRecords.employee_name
  }
})

async function loadData() {
  const ctx = auditContext.value
  if (!ctx) return
  loading.value = true
  message.value = ''
  try {
    const params = new URLSearchParams({
      project_name: ctx.project_name,
      business_type: ctx.business_type,
      audit_month: ctx.audit_month,
      service_type: effectiveServiceType.value,
      scope: 'confirmation',  // 裁剪版详情：只含 s04 扣款明细，避免 MB 级传输
    })
    const detail = await request<any>(`/api/v2/audit-results/detail?${params}`)
    const resultsJson = typeof detail?.results_json === 'string' ? JSON.parse(detail.results_json) : detail?.results_json
    const raw = resultsJson?.s04_attendance_audit || {}
    const s04Audit: S04AuditData = {
      deduction_details: raw.deduction_details || [],
      summary: raw.summary || {},
    }
    s04Data.value = s04Audit
    const records = buildExceptionRecords(s04Audit.deduction_details || [])
    allRecords.value = records
    const cMap: Record<string, boolean> = {}
    const fMap: Record<string, boolean> = {}
    for (const r of records) {
      // 默认全选：与后端 is_charged 口径一致（未确认的异常默认计入扣款）
      cMap[r.key] = r.confirmed ?? true
      fMap[r.key] = r.free_deduction ?? false
    }
    // 恢复本地草稿（指纹匹配才盖回）
    try {
      const rawDraft = localStorage.getItem(draftStorageKey(ctx.project_name, ctx.business_type, ctx.audit_month, effectiveServiceType.value))
      if (rawDraft) {
        const draft = JSON.parse(rawDraft)
        if (draft?.fp === recordsFingerprint(records)) {
          if (draft.overrides && typeof draft.overrides === 'object') {
            for (const [k, v] of Object.entries(draft.overrides)) {
              if (k in cMap && typeof v === 'boolean') cMap[k] = v
            }
          }
          if (draft.freeOverrides && typeof draft.freeOverrides === 'object') {
            for (const [k, v] of Object.entries(draft.freeOverrides)) {
              if (k in fMap && typeof v === 'boolean') fMap[k] = v
            }
          }
        }
      }
    } catch { /* 草稿损坏时忽略 */ }
    confirmMap.value = cMap
    freeDeductionMap.value = fMap
  } catch (error) {
    message.value = error instanceof Error ? error.message : '加载失败'
  }
  loading.value = false
}

// 保存草稿：只存与基准状态的差异；无差异时移除草稿
function saveDraft(nextMap: Record<string, boolean>, nextFreeMap?: Record<string, boolean>) {
  const ctx = auditContext.value
  if (!ctx) return
  const key = draftStorageKey(ctx.project_name, ctx.business_type, ctx.audit_month, effectiveServiceType.value)
  const overrides: Record<string, boolean> = {}
  for (const r of allRecords.value) {
    const base = r.confirmed ?? true
    const cur = nextMap[r.key] ?? base
    if (cur !== base) overrides[r.key] = cur
  }
  const freeMap = nextFreeMap ?? freeDeductionMap.value
  const freeOverrides: Record<string, boolean> = {}
  for (const r of allRecords.value) {
    const base = r.free_deduction ?? false
    const cur = freeMap[r.key] ?? base
    if (cur !== base) freeOverrides[r.key] = cur
  }
  if (!Object.keys(overrides).length && !Object.keys(freeOverrides).length) {
    localStorage.removeItem(key)
  } else {
    localStorage.setItem(key, JSON.stringify({ fp: recordsFingerprint(allRecords.value), overrides, freeOverrides }))
  }
}

function clearDraft() {
  const ctx = auditContext.value
  if (!ctx) return
  localStorage.removeItem(draftStorageKey(ctx.project_name, ctx.business_type, ctx.audit_month, effectiveServiceType.value))
}

function toggleConfirm(key: string) {
  const next = { ...confirmMap.value, [key]: !confirmMap.value[key] }
  confirmMap.value = next
  saveDraft(next)
}

function empFreeUsed(emp: string): number {
  return allRecords.value.filter((r) => r.employee_name === emp && freeDeductionMap.value[r.key]).length
}

function freeLimitOf(emp: string): number {
  return s04Data.value?.deduction_details.find((d) => d.employee_name === emp)?.missing_clock_free_limit ?? 3
}

function isFreeDisabled(r: ExceptionRecord): boolean {
  const checked = confirmMap.value[r.key] ?? false
  const free = freeDeductionMap.value[r.key] ?? false
  return (!checked && !free) || (checked && empFreeUsed(r.employee_name) >= freeLimitOf(r.employee_name) && !free)
}

function handleFreeDeduction(key: string) {
  const record = allRecords.value.find((r) => r.key === key)
  if (!record) return
  if (freeDeductionMap.value[key]) {
    if (confirm('确定取消该记录的免扣状态吗？取消后将重新计入扣款。')) {
      const next = { ...freeDeductionMap.value, [key]: false }
      freeDeductionMap.value = next
      saveDraft(confirmMap.value, next)
    }
    return
  }
  if (!confirmMap.value[key]) {
    message.value = '请先勾选确认该记录，再使用免打卡'
    return
  }
  const freeLimit = freeLimitOf(record.employee_name)
  const used = empFreeUsed(record.employee_name)
  if (used >= freeLimit) {
    message.value = '剩余次数不足，本月免打卡额度已用完'
    return
  }
  if (confirm(`确定将"${record.exception_label}"记录设为免打卡吗？\n${record.employee_name} 当前剩余免打卡机会：${freeLimit - used}次`)) {
    const next = { ...freeDeductionMap.value, [key]: true }
    freeDeductionMap.value = next
    saveDraft(confirmMap.value, next)
  }
}

function selectAllForEmployee(emp: string) {
  const empRecords = allRecords.value.filter((r) => r.employee_name === emp)
  const allChecked = empRecords.every((r) => confirmMap.value[r.key])
  const updates: Record<string, boolean> = {}
  for (const r of empRecords) updates[r.key] = !allChecked
  const next = { ...confirmMap.value, ...updates }
  confirmMap.value = next
  saveDraft(next)
}

function buildConfirmRecords() {
  return allRecords.value.map((r) => ({
    employee_name: r.employee_name,
    work_date: r.work_date,
    exception_type: r.exception_type,
    window: r.window || '',
    confirmed: confirmMap.value[r.key] ?? false,
    confirm_note: '',
    free_deduction: freeDeductionMap.value[r.key] ?? false,
  }))
}

// 异常确认即定稿：提交既写入确认结果，也把审核结果就地改写为唯一最终版
async function submitConfirm() {
  const ctx = auditContext.value
  if (!ctx) throw new Error('请先完成一次审核')
  return request<any>(`/api/v2/audit-results/confirm-exceptions`, {
    method: 'PUT',
    data: {
      project_name: ctx.project_name,
      business_type: ctx.business_type,
      audit_month: ctx.audit_month,
      service_type: effectiveServiceType.value,
      confirmed_records: buildConfirmRecords(),
      confirmed_by: auth.user?.username || '审核员',
    },
  })
}

async function saveConfirm() {
  const ctx = auditContext.value
  if (!ctx || !s04Data.value) return
  saving.value = true
  message.value = ''
  try {
    const result = await submitConfirm()
    clearDraft()
    invalidateDetailCache()
    message.value = `确认已保存，总扣款 ¥${Number(result?.total_deduction ?? 0).toFixed(2)}，正在后台更新报告...`
    // 后台自动重新生成报告，不阻塞用户操作
    const params = new URLSearchParams({
      project_name: ctx.project_name,
      business_type: ctx.business_type,
      audit_month: ctx.audit_month,
      service_type: effectiveServiceType.value,
      report_type: 'summary',
    })
    request(`/api/v2/reports/generate?${params}`, { method: 'POST' })
      .then(() => (message.value = `确认已保存，报告已自动更新。总扣款 ¥${Number(result?.total_deduction ?? 0).toFixed(2)}`))
      .catch(() => (message.value = '确认已保存，但报告自动更新失败，请手动点击"生成扣款报告"'))
    await loadData()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '提交失败'
  }
  saving.value = false
}

async function generateReport() {
  const ctx = auditContext.value
  if (!ctx) return
  if (!confirm('生成扣款报告将按确认结果重新计算扣款金额、定稿审核结果，并生成审核汇总报告。是否继续？')) return
  submitting.value = true
  message.value = ''
  try {
    const result = await submitConfirm()
    clearDraft()
    invalidateDetailCache()
    confirmResult.value = {
      confirmed_count: result?.confirmed_count ?? 0,
      total_deduction: result?.total_deduction ?? 0,
      first_exception_rate: result?.first_exception_rate ?? 0,
      confirmed_exception_rate: result?.confirmed_exception_rate ?? 0,
      message: result?.message || '',
    }
    message.value = '审核结果已定稿，正在生成审核汇总与扣款报告...'
    await request(
      `/api/v2/reports/generate?project_name=${encodeURIComponent(ctx.project_name)}&business_type=${encodeURIComponent(ctx.business_type)}&audit_month=${encodeURIComponent(ctx.audit_month)}&service_type=${encodeURIComponent(effectiveServiceType.value)}&report_type=summary`,
      { method: 'POST' },
    )
    message.value = '审核汇总与扣款报告已生成，可前往"PDF报告"页下载。'
    await loadData()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '报告生成失败'
  }
  submitting.value = false
}

// 员工分组
const empRecordsMap = computed(() => {
  const map: Record<string, ExceptionRecord[]> = {}
  for (const r of allRecords.value) {
    if (!map[r.employee_name]) map[r.employee_name] = []
    map[r.employee_name].push(r)
  }
  return map
})

const employeeList = computed(() =>
  (s04Data.value?.deduction_details || [])
    .map((d) => d.employee_name)
    .filter((name) => empRecordsMap.value[name]?.length > 0),
)

const currentRecords = computed(() => (selectedEmployee.value ? empRecordsMap.value[selectedEmployee.value] || [] : []))
const totalExceptions = computed(() => allRecords.value.length)
const confirmedCount = computed(() => allRecords.value.filter((r) => confirmMap.value[r.key] && !freeDeductionMap.value[r.key]).length)
const freeDeductionCount = computed(() => allRecords.value.filter((r) => freeDeductionMap.value[r.key]).length)
const currentDetail = computed(() => s04Data.value?.deduction_details.find((d) => d.employee_name === selectedEmployee.value))

function empConfirmedCount(emp: string) {
  return (empRecordsMap.value[emp] || []).filter((r) => confirmMap.value[r.key] && !freeDeductionMap.value[r.key]).length
}
function empTotalCount(emp: string) {
  return (empRecordsMap.value[emp] || []).length
}
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.desc { margin-top: 4px; }
.mt-8 { margin-top: 8px; }
.mt-12 { margin-top: 12px; }
.nowrap { white-space: nowrap; }
.pre-wrap { white-space: pre-wrap; }
.text-right { text-align: right; }
.text-center { text-align: center; }
.font-medium { font-weight: 500; }
.text-muted-light { color: var(--slate-400); }

.card-headbar { padding: 20px; }
.result-cell { border-radius: 8px; background: var(--slate-50); padding: 16px; text-align: center; }
.result-cell.red { background: #fef2f2; }
.result-cell.amber { background: #fffbeb; }
.result-cell.blue { background: #eff6ff; }
.result-num { font-size: 24px; font-weight: 700; color: var(--slate-900); }
.result-num.red { color: var(--red-600); }
.result-num.amber { color: var(--amber-600); }
.result-num.blue { color: #2563eb; }

.confirm-body { display: flex; gap: 16px; }
.emp-side { width: 192px; flex-shrink: 0; }
.main-side { flex: 1; min-width: 0; }
.emp-card { padding: 12px; }
.emp-title { margin: 0 0 12px 8px; font-size: 14px; font-weight: 500; color: var(--slate-700); }
.emp-list { display: flex; flex-direction: column; gap: 4px; }
.emp-btn {
  display: flex; width: 100%; align-items: center; justify-content: space-between;
  border-radius: 8px; padding: 8px 12px; text-align: left; font-size: 14px;
  color: var(--slate-600); transition: all 0.15s;
}
.emp-btn:hover { background: var(--slate-50); }
.emp-btn.active { background: var(--card-bg-soft); color: var(--accent); }
.emp-name-col { display: flex; flex-direction: column; }

.rec-head { border-bottom: 1px solid var(--slate-100); padding: 12px 20px; }
.rec-title { font-size: 14px; font-weight: 500; color: var(--slate-700); }
.link-btn { font-size: 12px; color: var(--accent); text-decoration: underline; }
.table-scroll { overflow: auto; }

.chk { width: 20px; height: 20px; cursor: pointer; accent-color: var(--accent); }
/* el-table 行类名渲染在组件内部 tr 上，scoped 需 :deep 穿透 */
:deep(.tr-free) { background: #fffbeb; }
:deep(.tr-ok) { background: #f0fdf4; }
.amount-on { color: var(--slate-900); }
.strike { color: var(--slate-400); text-decoration: line-through; }

.free-btn {
  border-radius: 4px; padding: 4px 8px; font-size: 12px; font-weight: 500;
  background: #d1fae5; color: #047857; transition: all 0.15s;
}
.free-btn:hover:not(.off):not(.on) { background: #a7f3d0; }
.free-btn.on { background: #fde68a; color: #92400e; }
.free-btn.on:hover { background: #fcd34d; }
.free-btn.off { background: var(--slate-100); color: var(--slate-400); cursor: not-allowed; }
</style>
