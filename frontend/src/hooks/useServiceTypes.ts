import { useEffect, useState } from 'react'
import { request } from '../services/api'
import type { AuditContext } from '../types'

/** 服务类型展示顺序：已知的排在前面，未指定的排在最后 */
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

/**
 * 拉取当前（项目 + 月份 + 业态）下已有的服务类型列表，并维护当前选中的服务类型。
 *
 * 两个页面（审核结果页 / 异常确认页）共用，保证交互与默认选中一致：
 * - 初始选中 auditContext.service_type；
 * - 列表加载完成后，若初始选中项在列表中不存在，自动回退到第一项；
 * - 服务类型为空的历史数据统一归为「未指定」，仍可切换查看。
 */
export function useServiceTypes(auditContext: AuditContext | null) {
  const projectName = auditContext?.project_name || ''
  const auditMonth = auditContext?.audit_month || ''
  const businessType = auditContext?.business_type || ''

  const [options, setOptions] = useState<ServiceTypeOption[]>([])
  const [active, setActive] = useState<string>(auditContext?.service_type || '')

  // 切换上下文时先把选中项对齐到 context 的值，避免残留上一个项目的服务类型
  useEffect(() => {
    setActive(auditContext?.service_type || '')
  }, [projectName, auditMonth, businessType, auditContext?.service_type])

  useEffect(() => {
    if (!projectName || !auditMonth) {
      setOptions([])
      return
    }
    let cancelled = false
    const params = new URLSearchParams({ project_name: projectName, audit_month: auditMonth })
    request<AuditResultListItem[]>(`/api/v2/audit-results?${params.toString()}`, { method: 'GET' })
      .then((list) => {
        if (cancelled) return
        const scoped = (list || []).filter(
          (it) =>
            String(it.project_name || '') === projectName &&
            String(it.audit_month || '') === auditMonth &&
            String(it.business_type || '') === businessType
        )
        const hasMap = new Map<string, boolean>()
        for (const it of scoped) {
          const svc = String(it.service_type || '')
          hasMap.set(svc, true)
        }
        // 上下文里指定的服务类型即使没有结果也保留，避免用户看不到自己刚审核的类型
        if (auditContext?.service_type && !hasMap.has(auditContext.service_type)) {
          hasMap.set(auditContext.service_type, false)
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
        setOptions(
          values.map((v) => ({
            value: v,
            label: v || '未指定',
            hasResult: hasMap.get(v) ?? false,
          }))
        )
        setActive((cur) => {
          if (values.length === 0) return cur
          if (cur && values.includes(cur)) return cur
          return values[0]
        })
      })
      .catch(() => {
        if (!cancelled) setOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [projectName, auditMonth, businessType, auditContext?.service_type])

  return { options, active, setActive, serviceType: active }
}
