export function createRequestSingleFlight({ cooldownMs = 2000, now = () => Date.now() } = {}) {
  const inflight = new Map()
  const recent = new Map()

  function normalizeKey(value) {
    return String(value || '').trim()
  }

  function readRecent(key) {
    const cached = recent.get(key)
    if (!cached) return null
    if (cached.expiresAt <= now()) {
      recent.delete(key)
      return null
    }
    return cached
  }

  function pruneExpired() {
    const currentTime = now()
    for (const [key, cached] of recent.entries()) {
      if (cached.expiresAt <= currentTime) recent.delete(key)
    }
  }

  return {
    run(value, requestFactory) {
      const key = normalizeKey(value)
      if (!key) return Promise.reject(new Error('请求去重键不能为空'))
      pruneExpired()

      const active = inflight.get(key)
      if (active) return active

      const cached = readRecent(key)
      if (cached) {
        return cached.ok
          ? Promise.resolve(cached.value)
          : Promise.reject(cached.error)
      }

      const request = Promise.resolve()
        .then(requestFactory)
        .then(
          (result) => {
            recent.set(key, {
              ok: true,
              value: result,
              expiresAt: now() + Math.max(0, Number(cooldownMs) || 0),
            })
            return result
          },
          (error) => {
            recent.set(key, {
              ok: false,
              error,
              expiresAt: now() + Math.max(0, Number(cooldownMs) || 0),
            })
            throw error
          },
        )
        .finally(() => {
          if (inflight.get(key) === request) inflight.delete(key)
        })

      inflight.set(key, request)
      return request
    },
    isBlocked(value) {
      const key = normalizeKey(value)
      return Boolean(key && (inflight.has(key) || readRecent(key)))
    },
    clear(value) {
      const key = normalizeKey(value)
      if (!key) return
      recent.delete(key)
    },
  }
}
