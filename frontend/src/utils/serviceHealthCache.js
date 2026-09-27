const STORAGE_KEY = 'kikoerumanager.service-health-cache.v1'
const CACHE_TTL_MS = 5 * 60 * 1000

const memoryCache = new Map()
const pendingRequests = new Map()

function readStorage() {
  if (typeof window === 'undefined') return {}
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}')
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
}

function writeStorage(cache) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache))
  } catch {
    // localStorage 不可用时保留内存缓存，不影响健康检查。
  }
}

function normalizeEntry(value) {
  if (!value || typeof value !== 'object' || !value.data || !value.cachedAt) return null
  const cachedAt = Number(value.cachedAt)
  if (!Number.isFinite(cachedAt) || cachedAt <= 0) return null
  return { data: value.data, cachedAt }
}

export function getCachedServiceHealth(provider) {
  const key = String(provider || '').trim() || 'http'
  const memoryEntry = normalizeEntry(memoryCache.get(key))
  const storedEntry = memoryEntry || normalizeEntry(readStorage()[key])
  if (!storedEntry) return null
  memoryCache.set(key, storedEntry)
  return {
    data: storedEntry.data,
    cachedAt: storedEntry.cachedAt,
    isFresh: Date.now() - storedEntry.cachedAt <= CACHE_TTL_MS
  }
}

function saveServiceHealth(provider, data) {
  const key = String(provider || '').trim() || 'http'
  const entry = { data, cachedAt: Date.now() }
  memoryCache.set(key, entry)
  const storage = readStorage()
  storage[key] = entry
  writeStorage(storage)
  return data
}

export function loadServiceHealth(provider, loader, { force = false } = {}) {
  const key = String(provider || '').trim() || 'http'
  const cached = getCachedServiceHealth(key)
  if (!force && cached?.isFresh) return Promise.resolve(cached.data)
  if (pendingRequests.has(key)) return pendingRequests.get(key)

  const request = Promise.resolve()
    .then(loader)
    .then(data => saveServiceHealth(key, data))
    .finally(() => pendingRequests.delete(key))
  pendingRequests.set(key, request)
  return request
}

export function clearServiceHealthCache(provider) {
  const key = String(provider || '').trim() || 'http'
  memoryCache.delete(key)
  const storage = readStorage()
  delete storage[key]
  writeStorage(storage)
}

