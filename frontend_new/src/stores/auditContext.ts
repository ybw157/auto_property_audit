/** 审核上下文（项目+月份+业态+服务类型），localStorage 持久化 */
import { defineStore } from 'pinia'

export interface AuditContext {
  project_name: string
  audit_month: string
  business_type: string
  service_type: string
}

const STORAGE_KEY = 'auditContext'

function loadFromStorage(): AuditContext | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

export const useAuditContextStore = defineStore('auditContext', {
  state: () => ({
    context: loadFromStorage() as AuditContext | null,
  }),
  actions: {
    set(ctx: AuditContext | null) {
      this.context = ctx
      if (ctx) localStorage.setItem(STORAGE_KEY, JSON.stringify(ctx))
      else localStorage.removeItem(STORAGE_KEY)
    },
    clear() {
      this.set(null)
    },
  },
})
