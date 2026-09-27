import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearServiceHealthCache,
  getCachedServiceHealth,
  loadServiceHealth,
} from './serviceHealthCache.js'

describe('服务健康检查缓存', () => {
  beforeEach(() => {
    window.localStorage.clear()
    clearServiceHealthCache('http')
    clearServiceHealthCache('baidu')
  })

  it('把健康结果持久化，并在 TTL 内复用结果', async () => {
    let calls = 0
    const loader = async () => {
      calls += 1
      return { ok: true, version: { version: '1.37.0' } }
    }

    const first = await loadServiceHealth('http', loader, { force: true })
    const second = await loadServiceHealth('http', loader)

    expect(first).toEqual(second)
    expect(calls).toBe(1)
    expect(getCachedServiceHealth('http')?.isFresh).toBe(true)
    expect(window.localStorage.getItem('kikoerumanager.service-health-cache.v1')).toContain('1.37.0')
  })

  it('同一服务的并发强制检测只发一个请求', async () => {
    let calls = 0
    let resolveLoader
    const loader = () => {
      calls += 1
      return new Promise(resolve => {
        resolveLoader = resolve
      })
    }

    const first = loadServiceHealth('baidu', loader, { force: true })
    const second = loadServiceHealth('baidu', loader, { force: true })
    await Promise.resolve()
    expect(calls).toBe(1)

    resolveLoader({ ok: false, message: '缺少 BDUSS' })
    await expect(Promise.all([first, second])).resolves.toEqual([
      { ok: false, message: '缺少 BDUSS' },
      { ok: false, message: '缺少 BDUSS' },
    ])
  })
})
