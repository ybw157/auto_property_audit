/**
 * 配置类接口缓存。
 *
 * 适用对象：/user/me、/business-types、/contracts 这类「低变动、高频读取」的配置接口。
 * 这些接口数据很少变化，但会被多个页面在组件挂载时各自请求一次，造成重复调用。
 *
 * 解决策略：
 *  1. 首次拉取后写入浏览器存储（localStorage / sessionStorage），后续直接读缓存；
 *  2. 进程内 in-flight 去重 —— 多个组件同时挂载时，同一 key 只发一个真实请求；
 *  3. stale-while-revalidate —— 有缓存先用旧值秒回渲染，同时后台静默刷新；
 *  4. 写操作（新增/编辑/删除合同、登录登出）后主动 invalidate，保证数据新鲜。
 */
import { request } from './api'
import type { LoginUser } from '../types'

/** 统一的缓存 key，避免各处写错字符串 */
export const CONFIG_KEYS = {
  USER_ME: 'user/me',
  BUSINESS_TYPES: 'business-types',
  CONTRACTS: 'contracts',
} as const

export type CacheKey = (typeof CONFIG_KEYS)[keyof typeof CONFIG_KEYS]

/** 默认缓存有效期：5 分钟 */
const DEFAULT_TTL = 5 * 60 * 1000

const STORAGE_PREFIX = 'cfg:'

type CacheEntry<T> = {
  data: T
  /** 写入时间戳（毫秒） */
  ts: number
}

type CacheOptions = {
  /** 有效期（毫秒），默认 5 分钟 */
  ttl?: number
  /** 存储介质：local = localStorage，session = sessionStorage，默认 local */
  storage?: 'local' | 'session'
  /** 忽略缓存强制请求（写完新数据后刷新用） */
  force?: boolean
}

/** 进程内并发去重表：同一 key 同一时刻只允许一个真实请求在飞 */
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
    // 写入成功即广播变更：同页面走监听器，跨标签页由 storage 事件触发
    notifyConfigChanged(key)
  } catch {
    // 存储配额已满 / 隐私模式禁用存储：静默降级为每次请求，不影响功能
  }
}

/* ---------- 变更订阅：同页面事件 + 跨标签页 storage 事件 ---------- */

type Listener = () => void

/** key → 订阅者集合 */
const listeners = new Map<string, Set<Listener>>()

/**
 * 订阅某个配置的变更。
 *
 * 触发时机：
 *  - 同页面：任何地方写入该配置（含其他标签页同步过来的写）
 *  - 跨标签页：另一个标签页写入/删除了同一个 key（浏览器 storage 事件）
 *
 * @returns 取消订阅函数，直接在 useEffect 里 return 即可
 */
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

/** 通知所有订阅者：该配置已更新，请重新读取 */
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
  // 同页面广播，供未使用 subscribeConfig 的地方感知
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('config:updated', { detail: { key } }))
  }
}

// 跨标签页同步：其他标签页写/删了同一个 key 时，本页同步失效并通知订阅者
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event: StorageEvent) => {
    if (!event.key || !event.key.startsWith(STORAGE_PREFIX)) return
    const key = event.key.slice(STORAGE_PREFIX.length)
    // 清掉本页正在飞的请求，避免旧响应覆盖别处刚写入的新值
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
 * 带缓存的请求封装。
 *
 * - 有未过期缓存：直接返回缓存，不发请求。
 * - 有过期缓存：立即返回旧值（保证页面秒开），同时后台静默刷新。
 * - 无缓存：真正等待请求结果。
 * - force=true：跳过读缓存，强制请求并写回（用于写操作后的刷新）。
 */
export async function cachedRequest<T>(
  key: CacheKey | string,
  fetcher: () => Promise<T>,
  options: CacheOptions = {},
): Promise<T> {
  const { ttl = DEFAULT_TTL, storage = 'local', force = false } = options

  const fetchAndCache = () =>
    dedupe(key, async () => {
      const data = await fetcher()
      writeCache(key, data, storage)
      return data
    })

  if (force) return fetchAndCache()

  const cached = readCache<T>(key, storage)
  if (cached) {
    const isFresh = Date.now() - cached.ts < ttl
    if (!isFresh) {
      // 过期了：后台悄悄刷新，本次仍用旧值，避免页面卡顿
      fetchAndCache().catch(() => {
        // 后台刷新失败静默处理，页面继续用旧缓存
      })
    }
    return cached.data
  }

  return fetchAndCache()
}

/** 让某个配置缓存失效（数据被修改后调用） */
export function invalidateConfig(key: CacheKey | string, storage: 'local' | 'session' = 'local') {
  inflight.delete(key)
  try {
    pickStorage(storage).removeItem(STORAGE_PREFIX + key)
  } catch {
    // 忽略存储异常
  }
}

/** 清空全部配置缓存（登录 / 登出时调用，避免串号） */
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

/** 当前登录用户信息 —— 走 sessionStorage，跟随标签页会话 */
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

/**
 * 应用挂载后统一预拉取配置。
 *
 * 登录成功后调用一次，把 /business-types、/contracts 提前灌进缓存，
 * 后续各页面挂载时直接命中缓存，不再重复打接口。
 * 不阻塞渲染，失败静默 —— 页面自身还有兜底请求。
 */
export function preloadConfigs() {
  fetchBusinessTypes().catch(() => {})
  fetchContracts().catch(() => {})
}
