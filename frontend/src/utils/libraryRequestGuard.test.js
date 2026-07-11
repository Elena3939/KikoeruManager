import { describe, expect, it } from 'vitest'
import {
  createLatestRequestGate,
  normalizeSuccessfulDeletePaths,
} from './libraryRequestGuard'

describe('createLatestRequestGate', () => {
  it('拒绝删除前的晚到响应和旧 finally', () => {
    const gate = createLatestRequestGate()
    const first = gate.begin()
    const second = gate.begin()

    expect(first.controller.signal.aborted).toBe(true)
    expect(gate.isCurrent(first)).toBe(false)
    expect(gate.finish(first)).toBe(false)
    expect(gate.isCurrent(second)).toBe(true)
    expect(gate.finish(second)).toBe(true)
  })

  it('invalidate 后正在飞行的请求不能再提交', () => {
    const gate = createLatestRequestGate()
    const request = gate.begin()

    gate.invalidate()

    expect(request.controller.signal.aborted).toBe(true)
    expect(gate.isCurrent(request)).toBe(false)
    expect(gate.diagnostics()).toMatchObject({
      discardedResponses: 1,
      requestInFlight: false,
    })
  })
})

describe('normalizeSuccessfulDeletePaths', () => {
  it('批删部分失败时只采用 success_paths', () => {
    const result = {
      success_paths: ['A/ok.txt', { path: 'A/ok-dir' }],
      failed_paths: [{ path: 'A/failed.txt', error: 'locked' }],
    }

    expect(normalizeSuccessfulDeletePaths(result)).toEqual([
      'A/ok.txt',
      'A/ok-dir',
    ])
  })
})
