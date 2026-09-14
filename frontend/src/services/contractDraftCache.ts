/**
 * 合同解析草稿缓存。
 *
 * 场景：上传合同 → POST /contracts/parse 只解析不入库，解析结果先写进
 * sessionStorage 草稿，再弹出细则编辑卡片；用户点「取消」不丢本次解析，
 * 从页面顶部「未保存草稿」可继续编辑或丢弃；点「保存」才凭 temp_file
 * 调 POST /contracts 转正入库并清掉草稿。
 *
 * 用 sessionStorage（跟随标签页生命周期）：换账号/关标签页草稿自然消失，
 * 不会串号；后端临时文件由下次同名覆盖或定期清理，无需前端干预。
 */

export type ContractParseDraft = {
  /** /contracts/parse 返回的完整字段（含 rules、extract_status） */
  parsed: Record<string, unknown>
  /** 后端临时文件路径，保存入库时原样回传 */
  tempFile: string
  /** 原始文件名（= original_name，入库去重键之一） */
  fileName: string
  /** 解析时间戳，用于横幅展示 */
  createdAt: number
}

const DRAFT_KEY = 'contract_parse_draft'

export function readContractDraft(): ContractParseDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const draft = JSON.parse(raw) as ContractParseDraft
    if (!draft?.tempFile || !draft?.fileName) return null
    return draft
  } catch {
    return null
  }
}

export function writeContractDraft(draft: ContractParseDraft): void {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
  } catch {
    // 存储已满/被禁用时静默失败：草稿仅退化为「取消即丢」，流程不受阻
  }
}

export function clearContractDraft(): void {
  try {
    sessionStorage.removeItem(DRAFT_KEY)
  } catch {
    // ignore
  }
}
