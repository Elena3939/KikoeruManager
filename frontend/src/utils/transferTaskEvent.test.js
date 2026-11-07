import { describe, expect, it } from 'vitest'
import { mergeTransferTaskSnapshot, patchTransferTaskEvent } from './transferTaskEvent.js'

describe('传输 SSE 运行态', () => {
  const task = { id: 'one', status: 'processing', updated_at: '2026-11-07T12:00:02',
    upload_runtime: { snapshot_at_ms: 2000, transferred_bytes: 360, total_bytes: 1000 } }
  it('保留明细，合并独立的上传和下载运行态', () => {
    const files = [{ name: 'a.wav' }]
    const next = patchTransferTaskEvent({ ...task, upload_files: files }, { engine_task_id: 'one', status: 'processing',
      upload_runtime: { snapshot_at_ms: 3000, transferred_bytes: 500 },
      download_runtime: { transferred_bytes: 800, total_bytes: 2000 } })
    expect(next.upload_files).toBe(files)
    expect(next.upload_runtime).toEqual({ snapshot_at_ms: 3000, transferred_bytes: 500, total_bytes: 1000 })
    expect(next.download_runtime.transferred_bytes).toBe(800)
  })
  it('忽略其它任务、旧事件与旧运行态', () => {
    expect(patchTransferTaskEvent(task, { engine_task_id: 'other' })).toBe(task)
    expect(patchTransferTaskEvent(task, { engine_task_id: 'one', updated_at: '2026-11-07T12:00:01' })).toBe(task)
    expect(patchTransferTaskEvent(task, { engine_task_id: 'one', upload_runtime: { snapshot_at_ms: 1000 } })).toBe(task)
  })
  it('迟到快照可以补明细，但不能覆盖最新进度', () => {
    const next = mergeTransferTaskSnapshot(task, { id: 'one', status: 'pending', progress: 1,
      upload_runtime: { snapshot_at_ms: 1000, transferred_bytes: 10 }, upload_files: [{ name: 'a.wav' }] })
    expect(next.status).toBe('processing')
    expect(next.upload_runtime.transferred_bytes).toBe(360)
    expect(next.upload_files).toHaveLength(1)
  })
  it('结束后不接受无时间戳的进行中事件，允许明确更新的重试', () => {
    const done = { ...task, status: 'completed' }
    expect(patchTransferTaskEvent(done, { task_id: 'one', status: 'processing' })).toBe(done)
    expect(patchTransferTaskEvent(done, { task_id: 'one', status: 'processing', updated_at: '2026-11-07T12:00:03' }).status).toBe('processing')
  })
})
