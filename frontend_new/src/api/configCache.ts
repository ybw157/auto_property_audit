/**
 * 配置类接口缓存（完整对齐 React 版 configCache）。
 *
 * 适用对象：/user/me、/business-types、/contracts 这类「低变动、高频读取」的配置接口。
 *
 * 策略：
 *  1. 首次拉取后写入浏览器存储（localStorage / sessionStorage），后续直接读缓存；
 *  2. 进程内 in-flight 去重 —— 同一 key 只发一个真实请求；
 *  3. cache-first（默认）：有缓存就直接返回，不发任何请求；
 *     真正打接口只有两种情况：写操作后 invalidateConfig()，或缓存超 maxAge 硬过期（2h 兜底）；
 *  4. 登录成功后 preloadConfigs() 统一灌一次。
 */
import { request } from './index'
import type { LoginUser } from '../types'

/** 统一的缓存 key */
export const CONFIG_KEYS = {
  USER_ME: 'user/me',
  BUSINESS_TYPES: 'business-types',
  CONTRACTS: 'contracts',
} as const

export type CacheKey = (typeof CONFIG_KEYS)[keyof typeof CONFIG_KEYS]

/** 软过期：仅 revalidate=true 时生效，默认 30 分钟 */
const DEFAULT_TTL = 30 * 60 * 1000

/** 硬过期：超过则缓存作废重新请求，默认 2 小时 */
const DEFAULT_MAX_AGE = 2 * 60 * 60 * 1000

const STORAGE_PREFIX = 'cfg:'

type CacheEntry<T> = {
  data: T
  ts: number
}

type CacheOptions = {
  ttl?: number
  maxAge?: number
  storage?: 'local' | 'session'
  force?: boolean
  revalidate?: boolean
}

/** 进程内并发去重表 */
const inflight = new Map<string, Promise<unknown>>()

function pickStorage(kind: 'local' | 'session'): Storage {
  return kind === 'session' ? sessionStorage : localStorage
}

function readCache<T>(key: string, kind: 'local' | 'session'): CacheEntry<T> | null {
  try {
    const raw = pickStorage(kind).getItem(STORAGE_PREFIX + key)
    if (!raw) return null
    return JSON.parse(raw) as CacheEntry<T>
  } catch {
    return null
  }
}

function writeCache<T>(key: string, value: T, kind: 'local' | 'session') {
  try {
    pickStorage(kind).setItem(STORAGE_PREFIX + key, JSON.stringify({ data: value, ts: Date.now() }))
    notifyConfigChanged(key)
  } catch {
    // 存储配额已满 / 隐私模式：静默降级为每次请求
  }
}

/* ---------- 变更订阅：同页面事件 + 跨标签页 storage 事件 ---------- */

type Listener = () => void

const listeners = new Map<string, Set<Listener>>()

/** 订阅某个配置的变更（同页面写入 / 其他标签页同步），返回取消订阅函数 */
export function subscribeConfig(key: CacheKey | string, listener: Listener): () => void {
  let set = listeners.get(key)
  if (!set) {
    set = new Set()
    listeners.set(key, set)
  }
  set.add(listener)
  return () => {
    const current = listeners.get(key)
    if (!current) return
    current.delete(listener)
    if (current.size === 0) listeners.delete(key)
  }
}

function notifyConfigChanged(key: string) {
  const set = listeners.get(key)
  if (set) {
    for (const listener of Array.from(set)) {
      try {
        listener()
      } catch (e) {
        console.error('[configCache] 订阅回调执行异常:', e)
      }
    }
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('config:updated', { detail: { key } }))
  }
}

// 跨标签页同步：其他标签页写/删了同一个 key 时，本页同步失效并通知订阅者
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event: StorageEvent) => {
    if (!event.key || !event.key.startsWith(STORAGE_PREFIX)) return
    const key = event.key.slice(STORAGE_PREFIX.length)
    inflight.delete(key)
    notifyConfigChanged(key)
  })
}

/** 同一 key 只发一次请求，其余调用共享同一个 Promise */
function dedupe<T>(key: string, task: () => Promise<T>): Promise<T> {
  const existing = inflight.get(key) as Promise<T> | undefined
  if (existing) return existing
  const promise = task().finally(() => {
    inflight.delete(key)
  })
  inflight.set(key, promise)
  return promise
}

/**
 * 带缓存的请求封装（默认 cache-first）。
 * - 有缓存且未硬过期：直接返回缓存，不发请求
 * - 硬过期：重新请求并写回
 * - revalidate=true 且软过期：返回旧值同时后台静默刷新
 * - force=true：跳过缓存强制请求（写操作后刷新用）
 */
export async function cachedRequest<T>(
  key: CacheKey | string,
  fetcher: () => Promise<T>,
  options: CacheOptions = {},
): Promise<T> {
  const {
    ttl = DEFAULT_TTL,
    maxAge = DEFAULT_MAX_AGE,
    storage = 'local',
    force = false,
    revalidate = false,
  } = options

  const fetchAndCache = () =>
    dedupe(key, async () => {
      const data = await fetcher()
      writeCache(key, data, storage)
      return data
    })

  if (force) return fetchAndCache()

  const cached = readCache<T>(key, storage)
  if (cached) {
    const age = Date.now() - cached.ts
    if (age >= maxAge) return fetchAndCache()
    if (revalidate && age >= ttl) {
      fetchAndCache().catch(() => {})
    }
    return cached.data
  }

  return fetchAndCache()
}

/** 同步读取缓存，不发起请求（首屏立即渲染用） */
export function getCachedConfig<T>(
  key: CacheKey | string,
  storage: 'local' | 'session' = 'local',
): T | null {
  const entry = readCache<T>(key, storage)
  return entry ? entry.data : null
}

/** 把已知数据直接写入缓存（登录接口已返回用户信息时省一次 /user/me） */
export function primeConfig<T>(
  key: CacheKey | string,
  data: T,
  storage: 'local' | 'session' = 'local',
) {
  writeCache(key, data, storage)
}

/** 让某个配置缓存失效（数据被修改后调用） */
export function invalidateConfig(key: CacheKey | string, storage: 'local' | 'session' = 'local') {
  inflight.delete(key)
  try {
    pickStorage(storage).removeItem(STORAGE_PREFIX + key)
  } catch {
    // 忽略
  }
}

/** 清空全部配置缓存（登录/登出时调用，避免串号） */
export function clearConfigCache() {
  inflight.clear()
  for (const key of Object.values(CONFIG_KEYS)) {
    try {
      localStorage.removeItem(STORAGE_PREFIX + key)
    } catch {
      // 忽略
    }
    try {
      sessionStorage.removeItem(STORAGE_PREFIX + key)
    } catch {
      // 忽略
    }
  }
}

/* ---------------- 具体的配置接口封装 ---------------- */

export type BusinessTypeConfig = {
  projects: string[]
  mapping: Record<string, string[]>
}

/** 当前登录用户信息 —— sessionStorage，跟随标签页会话 */
export function fetchUserMe() {
  return cachedRequest<LoginUser>(CONFIG_KEYS.USER_ME, () => request<LoginUser>('/api/v2/user/me'), {
    storage: 'session',
    ttl: 10 * 60 * 1000,
  })
}

/** 项目 → 业态映射 */
export function fetchBusinessTypes() {
  return cachedRequest<BusinessTypeConfig>(CONFIG_KEYS.BUSINESS_TYPES, () =>
    request<BusinessTypeConfig>('/api/v2/business-types'),
  )
}

/** 合同列表（force 用于写操作后强制刷新） */
export function fetchContracts<T>(force = false) {
  return cachedRequest<T>(CONFIG_KEYS.CONTRACTS, () => request<T>('/api/v2/contracts'), { force })
}

/** 应用挂载后统一预拉取配置（不阻塞渲染，失败静默） */
export function preloadConfigs() {
  fetchBusinessTypes().catch(() => {})
  fetchContracts<any[]>().catch(() => {})
}
