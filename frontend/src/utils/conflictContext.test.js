import { describe, expect, it } from 'vitest'
import { getExistingConflictPath, preserveConflictStats, shouldRefreshConflictTarget } from './conflictContext'

const waiting = { id: 'conflict', task_id: 'extract-task', existing_path: '正在处理中', context: { existing: { path: '' } } }
const path = '/library_anime/マヨタマ/[マヨタマ][RJ01657203]'

describe('问题作品真实目标目录更新', () => {
  it('优先显示解析出的真实目录，解析失败显示具体原因', () => {
    expect(getExistingConflictPath({ ...waiting, context: { existing: { path } } })).toBe(path)
    expect(getExistingConflictPath({ ...waiting, context: { existing: { path: '', unavailable_reason: '未找到已入库目录' } } })).toBe('未找到已入库目录')
  })

  it('另一条入库任务完成或索引更新时刷新待解析的目标', () => {
    expect(shouldRefreshConflictTarget([waiting], {}, [{ type: 'task_center_changed', engine_task_id: 'different-import-task', status: 'completed' }])).toBe(true)
    expect(shouldRefreshConflictTarget([waiting], { type: 'library.index.status.changed' }, [])).toBe(true)
    expect(shouldRefreshConflictTarget([waiting], {}, [{ type: 'task_center_changed', status: 'processing' }])).toBe(false)
  })

  it('已找到真实目录后不随每次索引事件重新加载', () => {
    expect(shouldRefreshConflictTarget([{ ...waiting, context: { existing: { path } } }], { type: 'library.index.status.changed' }, [])).toBe(false)
  })

  it('目标从占位变为真实目录时丢弃旧统计，保留源文件统计', () => {
    const previous = { ...waiting, context: { source: { path: '/down/source.zip', stats: { size: 10 } }, existing: { path: '', stats: { size: 0 } } } }
    const next = { ...waiting, context: { source: { path: '/down/source.zip' }, existing: { path } } }
    const merged = preserveConflictStats(next, previous)
    expect(merged.context.existing.path).toBe(path)
    expect(merged.context.existing.stats).toBeNull()
    expect(merged.context.source.stats).toEqual({ size: 10 })
    expect(preserveConflictStats(next, { ...next, context: { existing: { path, stats: { size: 200 } } } }).context.existing.stats).toEqual({ size: 200 })
  })
})
