import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useActivityDetailModels, humanAction } from './useActivityDetailModels.js'

it('聚合母任务按解压结果展示，不再描述为部分提交', () => {
  expect(humanAction({ category: 'auto_import', action: 'batch_start', result_status: 'partial_success' })).toBe('部分解压成功')
  expect(humanAction({ category: 'auto_import', action: 'batch_start', result_status: 'success' })).toBe('解压成功')
})

it('批删详情直接使用后端文件树，不拿首个文件代表整批路径', () => {
  const sections = [{ key: 'delete-succeeded-items', title: '已删除（2 项）', rows: [
    { key: 'root', label: '作品', type: 'dir', children: [
      { key: 'nested', label: '作品', type: 'dir', children: [] },
    ] },
  ] }]
  const model = useActivityDetailModels(ref({
    category: 'pipeline_delete', action: 'batch_api_delete', source_path: '/作品/first.vtt',
    detail: { delete_tree_sections: sections, results: [{ path: '/wrong', success: true }] },
  }))
  expect(model.entrySections.value).toEqual(sections)
  expect(model.pathCompare.value).toBeNull()
})

it('解压历史区分任务总耗时和包含等待的解包阶段', () => {
  const model = useActivityDetailModels(ref({
    category: 'auto_import',
    detail: { duration_ms: 120000, extract_phase_duration_ms: 30000, extract_execution_duration_ms: 12000 },
  }))
  expect(model.highlights.value.map(item => item.k)).toContain('任务总耗时')
  expect(model.highlights.value.map(item => item.k)).toContain('解包阶段（含等待）')
  expect(model.highlights.value.map(item => item.k)).toContain('解压耗时（不含等待）')
})

it('批次优先展示后端汇总容量并区分候选和实际参与数量', () => {
  const model = useActivityDetailModels(ref({
    category: 'auto_import', action: 'batch_start',
    detail: {
      participating_archive_count: 600, archive_count: 650, result_task_count: 600,
      aggregate_archive_size_bytes: 1024, aggregate_extract_output_bytes: 2048,
      batch_duration_ms: 30000,
    },
  }))
  const highlights = model.highlights.value
  expect(highlights[0]).toEqual({ k: '参与解压包数', v: '600' })
  expect(highlights.map(item => item.k)).toContain('批量压缩包大小')
  expect(highlights).toContainEqual({ k: '候选压缩包数', v: '650' })
})

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
