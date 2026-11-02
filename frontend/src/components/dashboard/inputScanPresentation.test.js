import { describe, expect, it } from 'vitest'
import { describeCandidate, skipReasonLabel } from './inputScanPresentation'

describe('扫描结果说明', () => {
  it('区分等待重试和归档占用', () => {
    expect(skipReasonLabel('task_waiting_retry')).toBe('等待重试占用')
    expect(skipReasonLabel('deferred_archive')).toBe('归档占用')
    expect(describeCandidate({ state: 'skipped', reason: 'deferred_archive:abc' })).toBe('归档占用')
  })
  it('区分交接、分流、稳定超时和未知跳过原因', () => {
    expect(describeCandidate({ state: 'submitted' })).toBe('已交接')
    expect(describeCandidate({ state: 'routed', destination: 'problem' })).toBe('已转入问题作品')
    expect(describeCandidate({ state: 'failed', reason: 'source_not_stable' })).toBe('失败：文件稳定等待超时')
    expect(describeCandidate({ state: 'skipped', reason: 'unknown:abc' })).toBe('其他占用或跳过原因')
  })
})
