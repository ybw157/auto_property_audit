/** 合同解析草稿缓存（sessionStorage）：解析后未入库的数据，刷新/取消不丢 */
export interface ContractParseDraft {
  parsed: Record<string, unknown>
  tempFile: string
  fileName: string
  createdAt: number
}

const KEY = 'contractParseDraft'

export function readContractDraft(): ContractParseDraft | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function writeContractDraft(draft: ContractParseDraft) {
  sessionStorage.setItem(KEY, JSON.stringify(draft))
}

export function clearContractDraft() {
  sessionStorage.removeItem(KEY)
}
