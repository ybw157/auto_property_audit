/** 服务类型子分类（保安/保洁/未指定）：审核结果/异常确认/PDF报告三处共用同一口径 */
import { ref, watch, type Ref } from 'vue'
import { request } from '../api'
import type { AuditContext } from '../stores/auditContext'

const KNOWN_ORDER = ['保安', '保洁']

export interface ServiceTypeOption {
  value: string
  label: string
  hasResult: boolean
}

interface AuditResultListItem {
  project_name?: string
  business_type?: string
  audit_month?: string
  service_type?: string
}

export function useServiceTypes(auditContext: Ref<AuditContext | null>) {
  const options = ref<ServiceTypeOption[]>([])
  const active = ref<string>(auditContext.value?.service_type || '')

  async function load() {
    const ctx = auditContext.value
    const projectName = ctx?.project_name || ''
    const auditMonth = ctx?.audit_month || ''
    const businessType = ctx?.business_type || ''
    if (!projectName || !auditMonth) {
      options.value = []
      return
    }
    try {
      const params = new URLSearchParams({ project_name: projectName, audit_month: auditMonth })
      const list = await request<AuditResultListItem[]>(`/api/v2/audit-results?${params.toString()}`)
      const scoped = (list || []).filter(
        (it) =>
          String(it.project_name || '') === projectName &&
          String(it.audit_month || '') === auditMonth &&
          String(it.business_type || '') === businessType,
      )
      const hasMap = new Map<string, boolean>()
      for (const it of scoped) {
        hasMap.set(String(it.service_type || ''), true)
      }
      if (ctx?.service_type && !hasMap.has(ctx.service_type)) {
        hasMap.set(ctx.service_type, false)
      }
      const values = Array.from(hasMap.keys())
      values.sort((a, b) => {
        const ia = KNOWN_ORDER.indexOf(a)
        const ib = KNOWN_ORDER.indexOf(b)
        if (ia !== -1 && ib !== -1) return ia - ib
        if (ia !== -1) return -1
        if (ib !== -1) return 1
        if (a === '') return 1
        if (b === '') return -1
        return a.localeCompare(b, 'zh-Hans-CN')
      })
      options.value = values.map((v) => ({ value: v, label: v || '未指定', hasResult: hasMap.get(v) ?? false }))
      if (values.length && !(active.value && values.includes(active.value))) {
        active.value = values[0]
      }
    } catch {
      options.value = []
    }
  }

  watch(
    () => [auditContext.value?.project_name, auditContext.value?.audit_month, auditContext.value?.business_type, auditContext.value?.service_type],
    () => {
      active.value = auditContext.value?.service_type || ''
      load()
    },
    { immediate: true },
  )

  return { options, active }
}
