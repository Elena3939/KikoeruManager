import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useActivityDetailModels } from './useActivityDetailModels.js'

function createBaiduRow(downloadFiles, failedFiles) {
  return {
    category: 'baidu_netdisk',
    status: 'failed',
    detail: {
      download_files: downloadFiles,
      failed_files: failedFiles,
    },
  }
}

const failedFile = {
  name: 'RJ01583281(0721)',
  relative_path: 'RJ01583281(0721)',
  size: 2716954426,
  status: 'failed',
  failure_reason: '[2] 下载文件失败, Get "https://yq-ct20.baidupcs.com/file/example?token=masked": context deadline exceeded',
}

describe('百度网盘操作历史文件详情', () => {
  it('失败文件不会在下载文件和下载失败中重复显示', () => {
    const model = useActivityDetailModels(ref(createBaiduRow([failedFile], [failedFile])))

    expect(model.entrySections.value.map((section) => section.key)).toEqual(['baidu-failed-files'])
    const rows = model.flattenEntryRows(model.entrySections.value[0].rows)
    expect(rows).toHaveLength(1)
    expect(rows[0].label).toBe('RJ01583281(0721)')
    expect(rows[0].error).toContain('context deadline exceeded')
  })

  it('成功和失败文件分别进入对应区块', () => {
    const completedFile = {
      name: 'RJ01600000.zip',
      relative_path: 'RJ01600000.zip',
      size: 1024,
      status: 'completed',
    }
    const model = useActivityDetailModels(ref(createBaiduRow(
      [completedFile, failedFile],
      [failedFile],
    )))

    expect(model.entrySections.value.map((section) => section.key)).toEqual([
      'baidu-download-files',
      'baidu-failed-files',
    ])
    expect(model.flattenEntryRows(model.entrySections.value[0].rows)[0].label).toBe('RJ01600000.zip')
    expect(model.flattenEntryRows(model.entrySections.value[1].rows)[0].label).toBe('RJ01583281(0721)')
  })
})
