<template>
  <div class="card card-pad">
    <div class="head-row">
      <div>
        <h2 class="h2">报告下载</h2>
        <p class="text-muted desc">审核完成后生成考勤明细 PDF；确认异常后生成 AI 审核汇总与扣款报告。</p>
        <ServiceTypeTabs :options="options" :value="active" @change="(v) => (active = v)" />
      </div>
      <div class="row gap-3">
        <button class="btn-primary" :disabled="loadingAttendance || loadingDeduction" @click="generate('attendance')">
          {{ loadingAttendance ? '生成中...' : '生成考勤明细' }}
        </button>
        <button class="btn-amber" :disabled="loadingAttendance || loadingDeduction" @click="generate('summary')">
          {{ loadingDeduction ? '生成中...' : '生成扣款报告' }}
        </button>
      </div>
    </div>
    <p v-if="message" class="notice">{{ message }}</p>
    <div class="report-grid">
      <ReportCard v-for="item in pdfReports" :key="item.id" :item="item" />
      <div v-if="!pdfReports.length" class="empty-box">
        暂无已生成报告，请先点击"生成考勤明细"。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, type PropType } from 'vue'
import { request } from '../api'
import type { AuditContext } from '../stores/auditContext'
import { useServiceTypes } from '../composables/useServiceTypes'
import ServiceTypeTabs from './ServiceTypeTabs.vue'
import ReportCard, { type ReportItem } from './ReportCard.vue'

const props = defineProps({
  auditContext: { type: Object as PropType<AuditContext | null>, default: null },
})

const reports = ref<ReportItem[]>([])
const message = ref('')
const loadingAttendance = ref(false)
const loadingDeduction = ref(false)

const ctxRef = computed(() => props.auditContext)
const { options, active } = useServiceTypes(ctxRef)
const effectiveServiceType = computed(() => active.value || props.auditContext?.service_type || '')

async function loadReports() {
  const ctx = props.auditContext
  if (!ctx) return
  reports.value = await request<ReportItem[]>(
    `/api/v2/reports?project_name=${encodeURIComponent(ctx.project_name)}&audit_month=${encodeURIComponent(ctx.audit_month)}&business_type=${encodeURIComponent(ctx.business_type)}`,
  )
}

watch(() => props.auditContext, () => {
  loadReports().catch(() => (reports.value = []))
}, { immediate: true })

async function generate(reportType: 'attendance' | 'summary') {
  const ctx = props.auditContext
  if (!ctx) return
  const loading = reportType === 'attendance' ? loadingAttendance : loadingDeduction
  loading.value = true
  message.value = ''
  try {
    await request(
      `/api/v2/reports/generate?project_name=${encodeURIComponent(ctx.project_name)}&business_type=${encodeURIComponent(ctx.business_type)}&audit_month=${encodeURIComponent(ctx.audit_month)}&service_type=${encodeURIComponent(effectiveServiceType.value)}&report_type=${reportType}`,
      { method: 'POST' },
    )
    await loadReports()
    message.value = reportType === 'attendance' ? '考勤明细报告已生成，可以下载。' : '扣款报告已生成，可以下载。'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '报告生成失败'
  } finally {
    loading.value = false
  }
}

const pdfReports = computed(() => reports.value.filter((item) => item.file_format === 'pdf'))
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.head-row { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 16px; }
.desc { margin-top: 8px; }
.btn-amber {
  border-radius: 12px; background: #d97706; padding: 8px 16px;
  font-size: 14px; font-weight: 500; color: #fff; transition: background 0.15s;
}
.btn-amber:hover:not(:disabled) { background: #b45309; }
.btn-amber:disabled { opacity: 0.5; }
.report-grid { margin-top: 20px; display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
.empty-box {
  border-radius: 16px; border: 1px dashed var(--slate-200);
  padding: 20px; font-size: 14px; color: var(--slate-500);
}
</style>
