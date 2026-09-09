import { useState, useEffect, useCallback } from 'react'
import type { AuditContext } from '../types'

const STORAGE_KEY = 'auditContext'

function loadFromStorage(): AuditContext | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

export function useAuditContext() {
  const [auditContext, setAuditContext] = useState<AuditContext | null>(loadFromStorage)

  useEffect(() => {
    if (auditContext) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(auditContext))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [auditContext])

  const clearAuditContext = useCallback(() => setAuditContext(null), [])

  return { auditContext, setAuditContext, clearAuditContext }
}