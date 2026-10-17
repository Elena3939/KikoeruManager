import { describe, expect, it } from 'vitest'
import { getDownloadBatchPercent } from './downloadProgress.js'

describe('百度下载字节进度', () => {
  it('实时字节优先于任务阶段进度和工作台缓存的旧文件行', () => {
    expect(getDownloadBatchPercent([{
      status: 'processing',
      progress: 80,
      download_runtime: { total_bytes: 1000, transferred_bytes: 79 },
      download_files: [{ size: 1000, downloaded: 500 }],
    }])).toBe(7)
  })

  it('多个任务按实际字节汇总，不按百分比等权平均', () => {
    expect(getDownloadBatchPercent([
      { status: 'completed', download_runtime: { total_bytes: 100 } },
      { status: 'processing', download_runtime: { total_bytes: 900, transferred_bytes: 90 } },
    ])).toBe(19)
  })

  it('尚未完成、部分失败和下载后处理中的任务最高显示 99%', () => {
    for (const status of ['processing', 'paused', 'failed', 'partial_failed']) {
      expect(getDownloadBatchPercent([{
        status: status === 'partial_failed' ? 'completed' : status,
        display_status: status,
        progress: 100,
        download_runtime: { total_bytes: 100, transferred_bytes: 100 },
      }])).toBe(99)
    }
  })

  it('全部任务确认完成才显示 100%，空队列为 0%', () => {
    expect(getDownloadBatchPercent([])).toBe(0)
    expect(getDownloadBatchPercent([{ status: 'completed' }])).toBe(100)
  })

  it('运行态已下载为零时不使用过时文件行的字节', () => {
    expect(getDownloadBatchPercent([{
      status: 'processing',
      download_runtime: { total_bytes: 1000, transferred_bytes: 0 },
      download_files: [{ size: 1000, downloaded: 500 }],
    }])).toBe(0)
  })

  it('无运行态字节时从文件行计算，已完成文件计入已下载大小', () => {
    expect(getDownloadBatchPercent([{
      status: 'processing',
      download_files: [
        { status: 'completed', size: 100 },
        { status: 'downloading', size_bytes: 900, downloaded: 90 },
      ],
    }])).toBe(19)
  })

  it('兼容嵌套运行态，截断明细不影响完整下载进度', () => {
    expect(getDownloadBatchPercent([{
      status: 'processing',
      download_files_truncated: true,
      download_files: [{ size: 10, downloaded: 10 }],
      task_metadata: {
        performance_metrics: { download_runtime: { total_bytes: 1000, transferred_bytes: 790 } },
      },
    }])).toBe(79)
  })

  it('未知大小的等待任务参与汇总，异常数字不污染显示', () => {
    expect(getDownloadBatchPercent([
      { status: 'completed', download_runtime: { total_bytes: 100 } },
      { status: 'pending', progress: 0 },
    ])).toBe(50)
    expect(getDownloadBatchPercent([{
      status: 'processing',
      progress: Infinity,
      download_runtime: { total_bytes: 'invalid', transferred_bytes: -10 },
    }])).toBe(0)
  })
})
