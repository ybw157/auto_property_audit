<template>
  <div class="page-stack">
    <!-- 工时异常警告 -->
    <div v-if="overtimeWarnings.length" class="warn-panel">
      <div class="row gap-2">
        <span class="warn-title">工时异常警告</span>
        <span class="warn-sub">（{{ overtimeWarnings.length }} 条，单日工时超 20h，当天已跳过扣款）</span>
      </div>
      <div class="warn-list">
        <div v-for="(w, i) in overtimeWarnings" :key="i" class="warn-row">
          <span class="warn-name">{{ w.employee_name }}</span>
          <span class="sep">|</span>
          <span>{{ w.date }}</span>
          <span class="sep">|</span>
          <span>{{ w.total_hours }}h</span>
          <span class="sep">|</span>
          <span>{{ w.positions?.join(' / ') }}</span>
        </div>
      </div>
    </div>

    <!-- 跨项目代班核查 -->
    <div v-if="data.crossProjectResolved.length || data.crossProjectReview.length" class="sky-panel">
      <div class="row gap-2">
        <span class="sky-title">跨项目代班核查</span>
        <span v-if="data.crossProjectResolved.length" class="sky-sub">（已自动归并 {{ data.crossProjectResolved.length }} 人）</span>
        <span v-if="data.crossProjectReview.length" class="sky-sub">（{{ data.crossProjectReview.length }} 人需人工复核）</span>
      </div>
      <div class="sky-list">
        <div v-for="(r, i) in data.crossProjectResolved" :key="`res-${i}`" class="sky-row">
          <span class="sky-name">{{ r.schedule_name || '' }}</span>
          <span class="sep">|</span>
          <span>来源项目 {{ r.source_project_name || '未知' }}</span>
          <span class="sep">|</span>
          <span>排班日 {{ (r.scheduled_dates as string[] || []).join('、') }}</span>
          <span class="sky-tag">已自动采用其 BI 考勤</span>
        </div>
        <div v-for="(r, i) in data.crossProjectReview" :key="`rev-${i}`" class="sky-card">
          <div class="sky-row">
            <span class="sky-name-dark">{{ r.schedule_name || '' }}</span>
            <span class="sep">|</span>
            <span>排班日 {{ (r.scheduled_dates as string[] || []).join('、') }}</span>
            <span class="sky-tag-review">请人工确认代班归属</span>
          </div>
          <div class="sky-candidates">
            <div v-for="(c, j) in (r.candidates as any[] || [])" :key="j" class="sky-candidate">
              <span class="sky-name">{{ c.employee_name || '' }}</span>
              <span class="sep-light">·</span>
              <span>工号 {{ c.employee_id || '-' }}</span>
              <span class="sep-light">·</span>
              <span>原属 {{ c.project_name || '未知' }}</span>
              <span class="sep-light">·</span>
              <span>
                当日打卡
                {{ Object.entries(c.clock_by_date || {}).map(([d, cl]) => `${d}: [${(cl as string[]).join(', ')}]`).join('  ') || '无' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 指标卡 -->
    <div class="grid-5">
      <div class="metric metric-red">
        <div class="metric-label">总扣款金额</div>
        <div class="metric-value">{{ formatMoney(view.totalDeduction) }} 元</div>
        <div class="metric-helper">人员考勤扣款汇总</div>
      </div>
      <div class="metric metric-amber">
        <div class="metric-label">排班任务</div>
        <div class="metric-value">{{ view.scheduleTaskCount }} 条</div>
        <div class="metric-helper">以月度排班表为唯一依据</div>
      </div>
      <div class="metric metric-blue">
        <div class="metric-label">异常记录</div>
        <div class="metric-value">{{ view.exceptionCount }} 条</div>
        <div class="metric-helper">涉及 {{ view.exceptionPeopleCount }} 人</div>
      </div>
      <div class="metric metric-green">
        <div class="metric-label">审核覆盖</div>
        <div class="metric-value">{{ view.auditedPeopleCount }} 人</div>
        <div class="metric-helper">{{ view.auditedDays }} 个日期</div>
      </div>
      <div class="metric metric-purple">
        <div class="metric-label">异常率</div>
        <div class="metric-value">{{ view.firstExceptionRate.toFixed(1) }}%</div>
        <div class="metric-helper">异常记录占比</div>
      </div>
    </div>

    <div class="grid-3eq">
      <div class="card card-pad">
        <h2 class="h3">扣款构成</h2>
        <div class="mt-20 stack">
          <RatioBar label="漏打卡扣款" :value="amounts.missing" :total="view.totalDeduction" color="bg-red-500" />
          <RatioBar label="迟到扣款" :value="amounts.late" :total="view.totalDeduction" color="bg-orange-500" />
          <RatioBar label="早退扣款" :value="amounts.early" :total="view.totalDeduction" color="bg-yellow-500" />
          <RatioBar label="缺勤扣款" :value="amounts.absence" :total="view.totalDeduction" color="bg-purple-500" />
        </div>
      </div>
      <div class="card card-pad">
        <h2 class="h3">异常类型排行</h2>
        <RankList :items="view.exceptionRanks" empty-text="暂无异常" color="bg-blue-500" />
      </div>
      <div class="card card-pad">
        <h2 class="h3">异常岗位排行</h2>
        <RankList :items="view.positionExceptionRanks" empty-text="暂无异常岗位" color="bg-amber-500" suffix="次" />
      </div>
    </div>

    <div class="grid-2eq">
      <div class="card card-pad">
        <h2 class="h3">高风险人员</h2>
        <div class="table-wrap mt-16">
          <el-table :data="view.riskyPeople" border stripe style="width: 100%">
            <el-table-column label="姓名" width="112">
              <template #default="{ row }"><span class="text-strong break">{{ row.name }}</span></template>
            </el-table-column>
            <el-table-column prop="count" label="异常次数" width="96" />
            <el-table-column label="扣款金额" width="110">
              <template #default="{ row }"><span class="text-danger">{{ formatMoney(row.amount) }}</span></template>
            </el-table-column>
            <el-table-column label="主要异常" min-width="140">
              <template #default="{ row }"><span class="text-muted break">{{ row.mainType }}</span></template>
            </el-table-column>
            <template #empty><span class="text-muted">暂无高风险人员</span></template>
          </el-table>
        </div>
      </div>
      <div class="card card-pad">
        <h2 class="h3">审核建议</h2>
        <div class="mt-16 stack-sm">
          <div v-for="item in view.suggestions" :key="item" class="suggestion">{{ item }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RatioBar from './RatioBar.vue'
import RankList from './RankList.vue'

type DashboardData = {
  attendanceDetails: Record<string, unknown>[]
  positionFulfillment: Record<string, unknown>[]
  exceptions: Record<string, unknown>[]
  attendanceDeductions: Record<string, unknown>[]
  deductions: Record<string, unknown>[]
  s04Summary: Record<string, unknown>
  deductionDetails: Record<string, unknown>[]
  crossProjectReview: Array<Record<string, unknown>>
  crossProjectResolved: Array<Record<string, unknown>>
}

const props = defineProps<{ data: DashboardData }>()

const overtimeWarnings = computed(() => props.data.deductionDetails.flatMap((d) => {
  const warnings = d.overtime_warnings as Array<{ date: string; positions: string[]; total_hours: number; message: string }> | undefined
  return (warnings || []).map((w) => ({ ...w, employee_name: String(d.employee_name || '') }))
}))

const amounts = computed(() => ({
  missing: Number(props.data.s04Summary?.total_missing_clock_amount || 0),
  late: Number(props.data.s04Summary?.total_late_amount || 0),
  early: Number(props.data.s04Summary?.total_early_leave_amount || 0),
  absence: Number(props.data.s04Summary?.total_absence_amount || 0),
}))

function toNumber(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const view = computed(() => {
  const data = props.data
  const s04Summary = data.s04Summary || {}
  const totalDeduction = Number(s04Summary.total_deduction || 0)
  const exceptionRows = data.attendanceDetails
  const exceptionPeople = new Set(exceptionRows.map((item) => String(item.employee_name || '')).filter(Boolean))
  const allAuditedPeople = new Set(data.exceptions.map((item) => String(item.employee_name || '')).filter(Boolean))
  const auditedDays = new Set(data.positionFulfillment.map((item) => String(item.work_date || '')).filter(Boolean)).size
  const scheduleTaskCount = data.positionFulfillment.filter((it) => {
    const s = String(it.status || '')
    return s !== '休息' && s !== '请假'
  }).length
  const exceptionCount = data.deductionDetails.reduce((sum, d) => {
    const missingClockDates = Array.isArray(d.missing_clock_dates) ? d.missing_clock_dates.length : 0
    const midClockIssues = Array.isArray(d.mid_clock_issues) ? d.mid_clock_issues.length : 0
    const lateDetails = Array.isArray(d.late_details) ? d.late_details.length : 0
    const earlyLeaveDetails = Array.isArray(d.early_leave_details) ? d.early_leave_details.length : 0
    const absenceDates = Array.isArray(d.absence_dates) ? d.absence_dates.length : 0
    return sum + missingClockDates + midClockIssues + lateDetails + earlyLeaveDetails + absenceDates
  }, 0)
  const firstExceptionRate = scheduleTaskCount > 0
    ? Number(((exceptionCount / scheduleTaskCount) * 100).toFixed(1))
    : 0

  const exceptionTypeCounts = new Map<string, number>()
  exceptionRows.forEach((item) => {
    const type = String(item.exception_type || '异常')
    exceptionTypeCounts.set(type, (exceptionTypeCounts.get(type) ?? 0) + 1)
  })
  const exceptionRanks = Array.from(exceptionTypeCounts.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)

  const exceptionByPosition = new Map<string, number>()
  exceptionRows.forEach((item) => {
    const key = String(item.position || '未命名岗位')
    exceptionByPosition.set(key, (exceptionByPosition.get(key) ?? 0) + 1)
  })
  const positionExceptionRanks = Array.from(exceptionByPosition.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)

  const peopleMap = new Map<string, { name: string; count: number; amount: number; types: Map<string, number> }>()
  data.attendanceDeductions.forEach((item) => {
    const name = String(item.employee_name || '')
    if (!name) return
    const current = peopleMap.get(name) ?? { name, count: 0, amount: 0, types: new Map<string, number>() }
    current.count += 1
    current.amount += toNumber(item.deduction_amount)
    const type = String(item.exception_type || '异常')
    current.types.set(type, (current.types.get(type) ?? 0) + 1)
    peopleMap.set(name, current)
  })
  const riskyPeople = Array.from(peopleMap.values())
    .map((item) => ({
      name: item.name,
      count: item.count,
      amount: item.amount,
      mainType: Array.from(item.types.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '异常',
    }))
    .sort((a, b) => b.amount - a.amount || b.count - a.count)
    .slice(0, 6)

  const suggestions: string[] = []
  if (totalDeduction <= 0) suggestions.push('本次审核未产生扣款，建议保留审核记录并归档。')
  if (exceptionRanks[0]) suggestions.push(`最高频异常为"${exceptionRanks[0].name}"，共 ${exceptionRanks[0].value} 次，建议核查合同规则和BI原始记录。`)
  if (positionExceptionRanks[0]) suggestions.push(`异常最集中的岗位是"${positionExceptionRanks[0].name}"，建议由项目核实排班后重新提交。`)
  if (riskyPeople[0]) suggestions.push(`人员异常扣款最高的是"${riskyPeople[0].name}"，主要异常为"${riskyPeople[0].mainType}"。`)
  if (!suggestions.length) suggestions.push('暂无明显风险项，可直接查看下方明细表进行抽查。')

  return {
    totalDeduction,
    scheduleTaskCount,
    exceptionCount,
    firstExceptionRate,
    exceptionPeopleCount: exceptionPeople.size,
    auditedPeopleCount: allAuditedPeople.size,
    auditedDays,
    exceptionRanks,
    positionExceptionRanks,
    riskyPeople,
    suggestions: suggestions.slice(0, 4),
  }
})
</script>

<style scoped>
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.stack { display: flex; flex-direction: column; gap: 16px; }
.stack-sm { display: flex; flex-direction: column; gap: 12px; }
.grid-3eq { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.grid-2eq { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }

/* 工时异常 */
.warn-panel { border-radius: 8px; border: 1px solid #fde68a; background: #fffbeb; padding: 16px; }
.warn-title { color: #d97706; font-weight: 500; font-size: 14px; }
.warn-sub { color: #f59e0b; font-size: 12px; }
.warn-list { margin-top: 8px; max-height: 192px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.warn-row { font-size: 14px; color: #92400e; }
.warn-name { font-weight: 500; }
.sep { margin: 0 4px; color: #f59e0b; }

/* 跨项目代班 */
.sky-panel { border-radius: 8px; border: 1px solid #bae6fd; background: #f0f9ff; padding: 16px; }
.sky-title { color: #0369a1; font-weight: 500; font-size: 14px; }
.sky-sub { color: #0ea5e9; font-size: 12px; }
.sky-list { margin-top: 8px; max-height: 240px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.sky-row { font-size: 14px; color: #0c4a6e; }
.sky-name { font-weight: 500; }
.sky-name-dark { font-weight: 500; color: #082f49; }
.sky-tag { margin-left: 8px; color: #0ea5e9; font-size: 12px; }
.sky-tag-review { margin-left: 8px; color: #0284c7; font-size: 12px; }
.sky-card { border-radius: 4px; border: 1px solid #bae6fd; background: rgba(255,255,255,0.7); padding: 8px; }
.sky-candidates { margin-top: 4px; display: flex; flex-direction: column; gap: 4px; }
.sky-candidate { padding-left: 12px; font-size: 12px; color: #075985; }
.sep-light { margin: 0 4px; color: #7dd3fc; }

/* 指标卡 */
.metric { border-radius: 24px; padding: 20px; border: 1px solid; background: #fff; }
.metric-label { font-size: 14px; font-weight: 500; color: var(--slate-500); }
.metric-value { margin-top: 12px; font-size: 24px; font-weight: 600; }
.metric-helper { margin-top: 8px; font-size: 12px; color: var(--slate-500); }
.metric-red { border-color: #fecaca; background: linear-gradient(to bottom right, #fef2f2, #fff); }
.metric-red .metric-value { color: #b91c1c; }
.metric-amber { border-color: #fde68a; background: linear-gradient(to bottom right, #fffbeb, #fff); }
.metric-amber .metric-value { color: #b45309; }
.metric-blue { border-color: #bfdbfe; background: linear-gradient(to bottom right, #eff6ff, #fff); }
.metric-blue .metric-value { color: #1d4ed8; }
.metric-green { border-color: #a7f3d0; background: linear-gradient(to bottom right, #ecfdf5, #fff); }
.metric-green .metric-value { color: #047857; }
.metric-purple { border-color: #D5DBE8; background: linear-gradient(to bottom right, #F0F3F9, #fff); }
.metric-purple .metric-value { color: #45526C; }

.suggestion {
  border-radius: 16px; border: 1px solid var(--slate-100); background: var(--slate-50);
  padding: 12px 16px; font-size: 14px; line-height: 1.6; color: var(--slate-700);
}
</style>
