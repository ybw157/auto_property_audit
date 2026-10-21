/** 审核详情内存缓存（stale-while-revalidate）：结果页与确认页共用，
 * 定稿/重新审核后调用 invalidateDetailCache 失效。 */
const detailCache = new Map<string, Record<string, unknown>>()

export function getDetailCache(key: string) {
  return detailCache.get(key)
}

export function setDetailCache(key: string, value: Record<string, unknown>) {
  detailCache.set(key, value)
}

export function invalidateDetailCache() {
  detailCache.clear()
}
