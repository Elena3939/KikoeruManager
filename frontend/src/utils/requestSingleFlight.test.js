import { describe, expect, it, vi } from 'vitest'

import { createRequestSingleFlight } from './requestSingleFlight.js'

describe('请求 single-flight 闸门', () => {
  it('同一键的并发调用只执行一次 HTTP 工厂', async () => {
    let resolveRequest
    const requestFactory = vi.fn(() => new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const guard = createRequestSingleFlight()

    const first = guard.run('session-1', requestFactory)
    const second = guard.run('session-1', requestFactory)
    await Promise.resolve()
    resolveRequest({ taskId: 'task-1' })

    await expect(first).resolves.toEqual({ taskId: 'task-1' })
    await expect(second).resolves.toEqual({ taskId: 'task-1' })
    expect(requestFactory).toHaveBeenCalledTimes(1)
  })

  it('冷却期内复用最近结果而不再次请求', async () => {
    let currentTime = 1000
    const requestFactory = vi.fn().mockResolvedValue({ taskId: 'task-1' })
    const guard = createRequestSingleFlight({
      cooldownMs: 2000,
      now: () => currentTime,
    })

    await expect(guard.run('session-1', requestFactory)).resolves.toEqual({ taskId: 'task-1' })
    currentTime = 2500
    await expect(guard.run('session-1', requestFactory)).resolves.toEqual({ taskId: 'task-1' })
    expect(requestFactory).toHaveBeenCalledTimes(1)

    currentTime = 3001
    await guard.run('session-1', requestFactory)
    expect(requestFactory).toHaveBeenCalledTimes(2)
  })
})
