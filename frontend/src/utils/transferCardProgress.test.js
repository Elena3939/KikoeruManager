import { describe, expect, it } from 'vitest'
import { getTransferCardProgress } from './transferCardProgress.js'

describe('传输小窗统一统计', () => {
  it.each(['upload', 'download'])('%s 使用实时字节覆盖阶段进度和过时文件行', mode => {
    const result = getTransferCardProgress([{ status: 'processing', progress: 11,
      [`${mode}_runtime`]: { total_bytes: 1000, transferred_bytes: 360, speed_bytes_per_sec: 10 },
      [`${mode}_files`]: [{ size: 1000, uploaded: 100, downloaded: 100 }] }], mode, 1_800_000_000_000)
    expect(result.percentage).toBe(36)
    expect(result.metaText).toContain('360.00 B / 1000.00 B')
    expect(result.metaText).toContain('10.00 B/s')
    expect(result.timingText).toContain('1 分 4 秒')
    expect(result.timingText).not.toContain('计算中')
  })
  it('嵌套运行态、零字节与暂停速度正确处理', () => {
    const result = getTransferCardProgress([{ status: 'paused', performance_metrics: { upload_runtime: {
      total_bytes: 1000, transferred_bytes: 0, speed_bytes_per_sec: 100 } }, upload_files: [{ size: 1000, uploaded: 800 }] }], 'upload')
    expect(result.percentage).toBe(0)
    expect(result.metaText).toContain('速度 0.00 B/s')
    expect(result.timingText).toContain('已暂停')
  })
  it('按字节加权并包含等待任务的剩余量', () => {
    const result = getTransferCardProgress([
      { status: 'completed', upload_runtime: { total_bytes: 100 } },
      { status: 'processing', upload_runtime: { total_bytes: 900, transferred_bytes: 90, speed_bytes_per_sec: 10 } },
      { status: 'pending', upload_runtime: { total_bytes: 1000 } }
    ], 'upload')
    expect(result.percentage).toBe(9)
    expect(result.timingText).toContain('3 分 1 秒')
  })
  it('未知大小不估算完成时间，确认期间不展示旧速度', () => {
    const result = getTransferCardProgress([{ status: 'processing', upload_runtime: { total_bytes: 1000, transferred_bytes: 1000, phase: 'verifying', speed_bytes_per_sec: 200 } }], 'upload')
    expect(result.percentage).toBe(99)
    expect(result.timingText).toBe('正在确认远端文件')
    expect(result.metaText).toContain('速度 0.00 B/s')
    expect(getTransferCardProgress([{ status: 'pending' }]).timingText).toContain('计算中')
    expect(getTransferCardProgress([{ status: 'completed' }]).percentage).toBe(100)
  })
})
