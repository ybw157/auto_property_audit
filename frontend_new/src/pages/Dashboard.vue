<template>
  <!-- 项目账号视角：已确认最终版 -->
  <div v-if="auth.role === 'project_user'" class="page-stack">
    <div class="card card-pad">
      <h2 class="h2">{{ projSummary?.project_name || auth.projectName }} - 已确认最终版</h2>
      <p class="text-muted mt-8">以下为本项目已由集团确认的最终版审核结果。过程版本（V1、V2等）不计入统计。</p>
      <p v-if="projError" class="text-danger mt-8">{{ projError }}</p>
    </div>
    <div class="grid-4">
      <div v-for="[label, value] in projCards" :key="label" class="card stat-card">
        <div class="text-muted">{{ label }}</div>
        <div class="stat-num">{{ value }}</div>
      </div>
    </div>
    <div class="card card-pad">
      <div class="row-between">
        <h3 class="h3">确认明细</h3>
        <span class="text-xs text-muted">共 {{ projSummary?.details.length ?? 0 }} 条</span>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="projSummary?.details || []" border stripe style="width: 100%">
          <el-table-column prop="audit_month" label="审核月份" width="110">
            <template #default="{ row }"><span class="text-strong">{{ formatMonth(row.audit_month) || '-' }}</span></template>
          </el-table-column>
          <el-table-column prop="business_type" label="业态" width="100">
            <template #default="{ row }">{{ row.business_type || '-' }}</template>
          </el-table-column>
          <el-table-column prop="service_type" label="服务类型" width="100">
            <template #default="{ row }">{{ row.service_type || '-' }}</template>
          </el-table-column>
          <el-table-column prop="schedule_count" label="排班数" align="center" width="90" />
          <el-table-column prop="exception_count" label="异常人数" align="center" width="90" />
          <el-table-column label="异常率" align="center" width="90">
            <template #default="{ row }">
              <span class="badge" :class="row.exception_rate > 10 ? 'badge-red' : 'badge-green'">{{ row.exception_rate }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="扣款金额" align="center" width="110">
            <template #default="{ row }">{{ fmtMoney(row.deduction_amount) }}</template>
          </el-table-column>
          <el-table-column label="确认时间" min-width="150">
            <template #default="{ row }"><span class="text-xs text-muted nowrap">{{ row.confirmed_at || '-' }}</span></template>
          </el-table-column>
          <template #empty><span class="text-muted">暂无已确认的最终版数据</span></template>
        </el-table>
      </div>
    </div>
  </div>

  <!-- 集团管理员视角 -->
  <div v-else class="page-stack">
    <!-- 顶部横幅 -->
    <div class="card card-pad">
      <div class="row-between banner-row">
        <div>
          <p class="banner-main">
            {{ formatMonth(summary?.audit_month || '') }}：{{ kpi?.total_projects ?? 0 }} 个项目中
            {{ kpi?.confirmed_projects ?? 0 }} 个完成审核，扣款
            <span class="text-danger">{{ fmtMoney(kpi?.total_deduction ?? 0) }}</span>，
            平均异常率 {{ kpi?.avg_exception_rate ?? 0 }}%
          </p>
          <p class="text-muted mt-4">
            扣款较上月 {{ momText(kpi?.deduction_mom_pct) }} ·
            异常率 {{ momPtText(kpi?.rate_mom_pt) }} ·
            已确认 {{ kpi?.confirmed_projects ?? 0 }} 个 ·
            待确认 {{ kpi?.pending_confirm_projects ?? 0 }} 个 ·
            未开始 {{ kpi?.pending_projects ?? 0 }} 个
          </p>
        </div>
        <div class="row gap-2">
          <span class="text-muted">审核月份</span>
          <el-date-picker
            v-model="month"
            type="month"
            value-format="YYYYMM"
            placeholder="选择月份"
            :clearable="false"
            style="width: 140px"
            @change="load"
          />
        </div>
      </div>
    </div>

    <!-- KPI 卡 -->
    <div class="grid-4">
      <div v-for="card in kpiCards" :key="card.label" class="card stat-card">
        <p class="text-muted">{{ card.label }}</p>
        <p class="stat-num" :class="card.tone">{{ card.value }}</p>
        <p class="text-xs text-muted-light mt-4">{{ card.note }}</p>
      </div>
    </div>

    <!-- 本月需要关注的三件事 -->
    <div>
      <h3 class="h3 mb-12">本月需要关注的三件事</h3>
      <div class="grid-3">
        <div class="card stat-card">
          <div class="row-between">
            <span class="h3-sm">异常率超标</span>
            <span class="badge badge-red">{{ riskProjects.length }} 个</span>
          </div>
          <div class="list-col">
            <div v-for="p in riskProjects.slice(0, 5)" :key="p.project_name" class="row-between list-row">
              <span>{{ p.project_name }}</span>
              <span class="text-danger font-medium">{{ p.exception_rate }}%</span>
            </div>
            <p v-if="!riskProjects.length" class="text-muted-light">本月无超标项目</p>
          </div>
        </div>
        <div class="card stat-card">
          <div class="row-between">
            <span class="h3-sm">超期未审核</span>
            <span class="badge badge-amber">{{ pendingList.length }} 个</span>
          </div>
          <div class="list-col">
            <div v-for="name in pendingList.slice(0, 5)" :key="name" class="list-row">{{ name }}</div>
            <p v-if="!pendingList.length" class="text-muted-light">当月全部完成</p>
          </div>
        </div>
        <div class="card stat-card">
          <div class="row-between">
            <span class="h3-sm">扣款金额 Top3</span>
          </div>
          <div class="list-col">
            <div v-for="p in deductionTop" :key="p.project_name" class="row-between list-row">
              <span>{{ p.project_name }}</span>
              <span>{{ fmtMoney(p.deduction_amount) }}</span>
            </div>
            <p v-if="!deductionTop.length" class="text-muted-light">本月暂无扣款</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 趋势 + 业态对比 -->
    <div class="grid-2-1">
      <div class="card card-pad">
        <h3 class="h3">近 6 个月趋势</h3>
        <div ref="trendRef" class="trend-chart"></div>
      </div>
      <div class="card card-pad">
        <h3 class="h3">业态对比</h3>
        <div class="biz-list">
          <div v-for="(b, i) in summary?.business_type_stats || []" :key="b.business_type">
            <div class="row-between text-sm">
              <span>{{ b.business_type }}</span>
              <span class="text-muted">{{ b.exception_rate }}% · {{ fmtMoneyShort(b.deduction_amount) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: barWidth(b.deduction_amount, maxBusinessDeduction) + '%', background: BUSINESS_COLORS[i % BUSINESS_COLORS.length] }" />
            </div>
            <p class="text-xs text-muted-light">{{ b.project_count }} 个项目</p>
          </div>
          <p v-if="!(summary?.business_type_stats || []).length" class="text-muted-light">暂无数据</p>
        </div>
      </div>
    </div>

    <!-- 扣款归因 + 供应商追责 -->
    <div v-if="summary && summary.deduction_breakdown.length" class="grid-3-2">
      <div class="card card-pad">
        <h3 class="h3">扣款归因与整改优先级</h3>
        <p class="text-muted mt-4">
          本月扣款 {{ fmtMoney(kpi?.total_deduction ?? 0) }}，其中
          <span class="text-strong">{{ summary.deduction_breakdown[0].type }}占 {{ summary.deduction_breakdown[0].share_pct }}%</span>
          ，是第一大损失来源
        </p>
        <div class="biz-list">
          <div v-for="(b, i) in summary.deduction_breakdown" :key="b.type">
            <div class="row-between text-sm">
              <span>
                {{ b.type }}
                <span class="text-xs text-muted-light ml-8">{{ b.count }} 次 · {{ fmtMoney(b.unit_cost) }}/次</span>
              </span>
              <span class="row gap-2">
                <span class="text-xs text-muted-light">{{ b.share_pct }}%</span>
                <span class="amount-cell">{{ fmtMoney(b.amount) }}</span>
              </span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: Math.max(b.share_pct, 1.5) + '%', background: i === 0 ? '#ef4444' : i === 1 ? '#f59e0b' : '#94a3b8' }" />
            </div>
            <p class="text-xs text-muted">{{ DEDUCTION_ACTION[b.type] ?? '—' }}</p>
          </div>
        </div>
        <div class="warn-line">
          <span>涉及员工 {{ summary.warning_stats.affected_employees }} 人</span>
          <span>中间卡异常 {{ summary.warning_stats.mid_clock_issue_count }} 次（预警，不扣款）</span>
          <span :class="summary.warning_stats.overtime_warning_count > 0 ? 'text-danger' : ''">
            加班预警 {{ summary.warning_stats.overtime_warning_count }} 次
          </span>
        </div>
      </div>
      <div class="card card-pad">
        <h3 class="h3">供应商扣款排行</h3>
        <p class="text-muted mt-4">按扣款金额降序，可直接据此追责</p>
        <div class="biz-list">
          <div v-for="(s, i) in summary.supplier_ranking" :key="s.supplier">
            <div class="row-between text-sm">
              <span>
                <span class="rank-dot">{{ i + 1 }}</span>
                {{ s.supplier }}
              </span>
              <span class="font-medium text-strong nowrap">{{ fmtMoney(s.deduction) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: Math.max(s.share_pct, 1.5) + '%', background: i === 0 ? '#ef4444' : '#f59e0b' }" />
            </div>
            <p class="text-xs text-muted-light">占 {{ s.share_pct }}% · {{ s.project_count }} 个项目</p>
          </div>
          <p v-if="!summary.supplier_ranking.length" class="text-muted-light">当月暂无供应商扣款数据</p>
        </div>
      </div>
    </div>

    <!-- 项目明细表 -->
    <div class="card">
      <div class="card-head">
        <h3 class="h3">项目明细</h3>
      </div>
      <div class="table-wrap no-border">
        <el-table :data="summary?.project_usage || []" border stripe style="width: 100%">
          <el-table-column prop="project_name" label="项目" min-width="140">
            <template #default="{ row }"><span class="text-strong">{{ row.project_name }}</span></template>
          </el-table-column>
          <el-table-column label="业态 / 服务类型" min-width="150">
            <template #default="{ row }"><span class="text-muted">{{ row.business_types }} / {{ row.service_types }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><span class="badge" :class="statusTone(row.audit_status)">{{ row.audit_status }}</span></template>
          </el-table-column>
          <el-table-column prop="schedule_count" label="排班天数" align="right" width="100" />
          <el-table-column prop="exception_count" label="异常数" align="right" width="90" />
          <el-table-column label="异常率" align="right" width="90">
            <template #default="{ row }">
              <span :class="row.exception_rate > (summary?.exception_rate_threshold ?? 10) ? 'text-danger font-medium' : ''">{{ row.exception_rate }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="扣款金额" align="right" width="110">
            <template #default="{ row }">{{ fmtMoney(row.deduction_amount) }}</template>
          </el-table-column>
          <el-table-column label="最近审核" align="right" width="150">
            <template #default="{ row }"><span class="text-muted-light">{{ row.last_audit_at }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { request } from '../api'
import { useAuthStore } from '../stores/auth'

// ---------- 类型（与后端 dashboard_service 返回结构一致） ----------
type GroupKpi = {
  total_projects: number
  audited_projects: number
  confirmed_projects: number
  pending_confirm_projects: number
  pending_projects: number
  total_deduction: number
  avg_exception_rate: number
  completion_rate: number
  audit_coverage_rate: number
  confirm_rate: number
  prev_total_deduction: number
  prev_exception_rate: number
  deduction_mom_pct: number | null
  rate_mom_pt: number | null
}
type ProjectUsage = {
  project_name: string
  business_types: string
  service_types: string
  audit_status: string
  schedule_uploaded: boolean
  exception_count: number
  exception_rate: number
  deduction_amount: number
  last_audit_at: string
  schedule_count: number
}
type TrendItem = { month: string; exception_rate: number; deduction: number }
type RiskProject = { project_name: string; exception_rate: number; audit_status: string; reason: string }
type BusinessTypeStat = { business_type: string; project_count: number; exception_rate: number; deduction_amount: number }
type DeductionItem = { type: string; amount: number; share_pct: number; count: number; unit_cost: number }
type WarningStats = { mid_clock_issue_count: number; overtime_warning_count: number; affected_employees: number }
type SupplierItem = { supplier: string; deduction: number; share_pct: number; project_count: number; projects: string[] }
type GroupSummary = {
  audit_month: string
  available_months: string[]
  exception_rate_threshold: number
  kpi: GroupKpi
  project_usage: ProjectUsage[]
  deduction_breakdown: DeductionItem[]
  warning_stats: WarningStats
  supplier_ranking: SupplierItem[]
  monthly_trend: TrendItem[]
  risk_projects: RiskProject[]
  business_type_stats: BusinessTypeStat[]
}
type ProjectDetail = {
  project_name: string
  business_type: string
  service_type: string
  audit_month: string
  status: string
  schedule_count: number
  exception_count: number
  exception_rate: number
  deduction_amount: number
  confirmed_at: string
}
type ProjectSummary = {
  project_name: string
  kpi: { confirmed_count: number; schedule_count: number; exception_count: number; deduction_amount: number }
  details: ProjectDetail[]
}

const DEDUCTION_ACTION: Record<string, string> = {
  缺勤: '供应商未派满岗 → 约谈并按合同索赔',
  漏打卡: '补卡流程未闭环 → 限期补卡即可追回',
  早退: '频次高、金额小 → 现场纪律日常管控',
  迟到: '频次高、金额小 → 现场纪律日常管控',
}
const BUSINESS_COLORS = ['#5070DD', '#B6D634', '#505372', '#FF994D', '#0CA8DF', '#FFD10A', '#FB628B', '#785DB0', '#3FBE95']

const auth = useAuthStore()

// ---------- 集团视角状态 ----------
const summary = ref<GroupSummary | null>(null)
const month = ref('')
const trendRef = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null

// ---------- 项目视角状态 ----------
const projSummary = ref<ProjectSummary | null>(null)
const projError = ref('')

const kpi = computed(() => summary.value?.kpi)

const kpiCards = computed(() => [
  { label: '项目总数', value: `${kpi.value?.total_projects ?? 0}`, note: `待确认 ${kpi.value?.pending_confirm_projects ?? 0} · 未开始 ${kpi.value?.pending_projects ?? 0}`, tone: '' },
  { label: '审核完成率', value: `${kpi.value?.completion_rate ?? 0}%`, note: `已确认 ${kpi.value?.confirmed_projects ?? 0} 个`, tone: (kpi.value?.completion_rate ?? 0) >= 90 ? 'text-success' : 'text-warn' },
  { label: '平均异常率', value: `${kpi.value?.avg_exception_rate ?? 0}%`, note: `预警线 ${summary.value?.exception_rate_threshold ?? 10}%`, tone: '' },
  { label: '异常率超标项目', value: `${riskProjects.value.length}`, note: `异常率 > ${summary.value?.exception_rate_threshold ?? 10}%`, tone: riskProjects.value.length ? 'text-danger' : 'text-success' },
])

const riskProjects = computed(() => summary.value?.risk_projects || [])
const pendingList = computed(() =>
  (summary.value?.project_usage || []).filter((p) => p.audit_status === '待审核').map((p) => p.project_name),
)
const deductionTop = computed(() =>
  [...(summary.value?.project_usage || [])].sort((a, b) => b.deduction_amount - a.deduction_amount).filter((p) => p.deduction_amount > 0).slice(0, 3),
)
const maxBusinessDeduction = computed(() =>
  Math.max(1, ...(summary.value?.business_type_stats || []).map((b) => b.deduction_amount)),
)

const projCards = computed<Array<[string, string | number]>>(() => [
  ['已确认最终版', projSummary.value?.kpi.confirmed_count ?? 0],
  ['排班任务数', projSummary.value?.kpi.schedule_count ?? 0],
  ['异常人数', projSummary.value?.kpi.exception_count ?? 0],
  ['扣款金额', fmtMoney(projSummary.value?.kpi.deduction_amount ?? 0)],
])

function formatMonth(m: string) {
  return m && m.length === 6 ? `${m.slice(0, 4)}-${m.slice(4)}` : m
}
function fmtMoney(n: number) {
  return `¥${(n ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
function fmtMoneyShort(n: number) {
  if (n >= 10000) return `¥${(n / 10000).toFixed(1)}万`
  return `¥${(n ?? 0).toFixed(2)}`
}
function momText(v: number | null | undefined) {
  if (v === null || v === undefined) return '无上月数据'
  return `${v > 0 ? '+' : ''}${v}%`
}
function momPtText(v: number | null | undefined) {
  if (v === null || v === undefined) return '无上月数据'
  return `${v > 0 ? '+' : ''}${v}pt`
}
function barWidth(v: number, max: number) {
  return Math.max((v / max) * 100, 2)
}
function statusTone(s: string) {
  if (s === '已确认') return 'badge-green'
  if (s === '待确认') return 'badge-amber'
  return 'badge-slate'
}

function renderTrend() {
  if (!trendRef.value || !summary.value) return
  trendChart = trendChart || echarts.init(trendRef.value)
  const items = summary.value.monthly_trend
  trendChart.setOption({
    grid: { left: 60, right: 40, top: 30, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: items.map((i) => formatMonth(i.month)) },
    yAxis: [
      { type: 'value', name: '扣款(元)' },
      { type: 'value', name: '异常率', axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      { name: '扣款金额', type: 'bar', data: items.map((i) => i.deduction), itemStyle: { color: '#5070DD', borderRadius: [4, 4, 0, 0] } },
      { name: '异常率', type: 'line', yAxisIndex: 1, smooth: true, data: items.map((i) => i.exception_rate), itemStyle: { color: '#FF994D' } },
    ],
  })
}

async function load() {
  const qs = month.value ? `?audit_month=${month.value}` : ''
  summary.value = await request<GroupSummary>(`/api/v2/dashboard/group-summary${qs}`)
  if (!month.value) month.value = summary.value.audit_month
  await nextTick()
  renderTrend()
}

watch(() => summary.value?.audit_month, () => nextTick(renderTrend))

onMounted(() => {
  if (auth.role === 'project_user') {
    request<ProjectSummary>('/api/v2/dashboard/project-summary')
      .then((d) => (projSummary.value = d))
      .catch((e) => (projError.value = e.message || '加载失败'))
  } else {
    load()
    window.addEventListener('resize', () => trendChart?.resize())
  }
})
onBeforeUnmount(() => trendChart?.dispose())
</script>

<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3-sm { font-size: 14px; font-weight: 600; color: var(--slate-800); }
.mt-4 { margin-top: 4px; }
.mt-8 { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mb-12 { margin-bottom: 12px; }
.ml-8 { margin-left: 8px; }
.nowrap { white-space: nowrap; }
.font-medium { font-weight: 500; }
.text-muted-light { color: var(--slate-400); font-size: 12px; }
.text-center { text-align: center; }
.text-right { text-align: right; }

.stat-card { padding: 20px; }
.stat-num { margin-top: 12px; font-size: 28px; font-weight: 600; color: var(--slate-900); }

.banner-main { font-size: 18px; font-weight: 600; color: var(--slate-900); margin: 0; }
.banner-row { gap: 16px; flex-wrap: wrap; }

.list-col { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--slate-600); }
.list-row { font-size: 14px; }

.grid-2-1 { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
.grid-3-2 { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; }

.trend-chart { margin-top: 8px; height: 256px; }

.biz-list { margin-top: 16px; display: flex; flex-direction: column; gap: 14px; }
.bar-track { margin-top: 6px; height: 8px; width: 100%; border-radius: 999px; background: var(--slate-100); overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; }
.amount-cell { width: 90px; text-align: right; font-weight: 500; color: var(--slate-900); }
.rank-dot {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 999px;
  background: var(--slate-100); color: var(--slate-500);
  font-size: 10px; margin-right: 6px;
}
.warn-line {
  margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--slate-100);
  display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--slate-500);
}
.card-head { padding: 16px 24px; border-bottom: 1px solid var(--slate-100); }
.table-wrap.no-border { border: none; border-radius: 0; }
</style>
