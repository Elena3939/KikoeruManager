import { describe, expect, it } from 'vitest'
import { getBackendUploadEta, mergeUploadTaskSnapshot } from './uploadTaskSnapshot'

describe('上传完整明细与运行态摘要合并', () => {
  it('缩小后的空明细不能覆盖已经加载的文件和日志', () => {
    const current = { id: 'a', upload_files: [{ name: 'track.wav' }], progress_log: [{ message: '上传中' }], task_metadata: { selected_paths: ['a'] } }
    const next = mergeUploadTaskSnapshot(current, { upload_files: [], progress_log: [], progress: 42, upload_runtime: { transferred_bytes: 42 } }, { compact: true })
    expect(next.upload_files).toEqual(current.upload_files)
    expect(next.progress_log).toEqual(current.progress_log)
    expect(next.task_metadata.selected_paths).toEqual(['a'])
    expect(next.progress).toBe(42)
  })

  it('展开获取完整响应时能补回明细', () => {
    const next = mergeUploadTaskSnapshot({ upload_files: [] }, { upload_files: [{ name: 'track.wav' }] })
    expect(next.upload_files).toHaveLength(1)
  })

  it('先发出的 HTTP 旧响应不能覆盖后收到的 SSE 运行态，但仍可补回明细', () => {
    const next = mergeUploadTaskSnapshot(
      { status: 'processing', progress: 60, upload_runtime: { snapshot_at_ms: 20, speed_bytes_per_sec: 200 } },
      { status: 'processing', progress: 40, upload_runtime: { snapshot_at_ms: 10, speed_bytes_per_sec: 100 }, upload_files: [{ name: 'track.wav' }] },
    )
    expect(next.progress).toBe(60)
    expect(next.upload_runtime.speed_bytes_per_sec).toBe(200)
    expect(next.upload_files).toHaveLength(1)
  })

  it('完成状态不能被在途运行态覆盖', () => {
    expect(mergeUploadTaskSnapshot({ status: 'completed', progress: 100 }, { status: 'processing', progress: 99 }).status).toBe('completed')
  })

  it('相同任务被明确重试后，接受时间更新的后端运行态', () => {
    const next = mergeUploadTaskSnapshot(
      { status: 'failed', upload_runtime: { snapshot_at_ms: 10 } },
      { status: 'processing', upload_runtime: { snapshot_at_ms: 20 } },
    )
    expect(next.status).toBe('processing')
  })

  it('剩余时间只读取后端值，不根据浏览器的字节数和速度估算', () => {
    expect(getBackendUploadEta([{ status: 'processing', upload_runtime: { eta_seconds: 37, total_bytes: 100000, speed_bytes_per_sec: 1 } }])).toBe(37)
    expect(getBackendUploadEta([{ status: 'processing', upload_runtime: { total_bytes: 100000, speed_bytes_per_sec: 1 } }])).toBeNull()
    expect(getBackendUploadEta([{ status: 'paused', upload_runtime: { eta_seconds: 37 } }])).toBeNull()
  })
})
