import { beforeEach, describe, expect, it, vi } from 'vitest'
import { asmrSyncApi, taskApi, taskCenterApi } from '../api'
import { cleanupFailedDownloadTask } from './failedDownloadTaskCleanup.js'

vi.mock('../api', () => ({
  asmrSyncApi: { cancelSession: vi.fn() },
  taskApi: { batchCancelCleanup: vi.fn() },
  taskCenterApi: { action: vi.fn() },
}))

beforeEach(() => {
  vi.resetAllMocks()
  taskApi.batchCancelCleanup.mockResolvedValue({ errors: [] })
})

describe('失败下载关闭清理', () => {
  it.each(['completed', 'cancelled', 'processing', 'pending'])('%s 不删除文件和任务', async status => {
    await cleanupFailedDownloadTask({ id: 'keep', status })
    expect(asmrSyncApi.cancelSession).not.toHaveBeenCalled()
    expect(taskApi.batchCancelCleanup).not.toHaveBeenCalled()
    expect(taskCenterApi.action).not.toHaveBeenCalled()
  })

  it.each(['failed', 'partial_failed'])('%s 先清理 ASMR 缓存，再删除真实引擎任务', async status => {
    asmrSyncApi.cancelSession.mockImplementation(async () => {
      expect(taskCenterApi.action).not.toHaveBeenCalled()
    })
    await cleanupFailedDownloadTask({
      id: 'session:asmr', status,
      source_task_ids: ['first', 'second', 'first'],
      task_metadata: { session_id: 'asmr' },
    })
    expect(asmrSyncApi.cancelSession).toHaveBeenCalledWith('asmr', { cleanup: true })
    expect(taskApi.batchCancelCleanup).not.toHaveBeenCalled()
    expect(taskCenterApi.action.mock.calls).toEqual([['engine:first', 'delete'], ['engine:second', 'delete']])
  })

  it('YAAS 合并任务清理所有分卷，不把引擎会话当成 ASMR 会话', async () => {
    await cleanupFailedDownloadTask({
      id: 'session:engine::RJ123456', status: 'failed',
      active_task_id: 'engine', source_task_ids: ['engine', 'volume'],
      task_metadata: { session_id: 'engine', resource_source: 'imoutoheaven' },
    })
    expect(asmrSyncApi.cancelSession).not.toHaveBeenCalled()
    expect(taskApi.batchCancelCleanup).toHaveBeenCalledWith(['engine', 'volume'])
    expect(taskCenterApi.action.mock.calls).toEqual([['engine:engine', 'delete'], ['engine:volume', 'delete']])
  })

  it('没有缓存文件时仍可删除失败任务', async () => {
    taskApi.batchCancelCleanup.mockResolvedValue({ cleaned: 0, errors: [] })
    await cleanupFailedDownloadTask({ id: 'empty', status: 'failed' })
    expect(taskCenterApi.action).toHaveBeenCalledWith('engine:empty', 'delete')
  })

  it('清理接口失败时不删除任务', async () => {
    asmrSyncApi.cancelSession.mockRejectedValue(new Error('文件被占用'))
    await expect(cleanupFailedDownloadTask({
      id: 'engine', status: 'failed', session_id: 'asmr',
    })).rejects.toThrow('文件被占用')
    expect(taskCenterApi.action).not.toHaveBeenCalled()
  })

  it('清理返回文件删除错误时不删除任务', async () => {
    taskApi.batchCancelCleanup.mockResolvedValue({ errors: ['文件被占用'] })
    await expect(cleanupFailedDownloadTask({ id: 'engine', status: 'failed' })).rejects.toThrow('下载缓存清理失败')
    expect(taskCenterApi.action).not.toHaveBeenCalled()
  })

  it('合并任务部分删除后可重试，跳过已经删除的分卷', async () => {
    taskCenterApi.action
      .mockRejectedValueOnce({ response: { status: 400, data: { detail: '任务不存在' } } })
      .mockResolvedValueOnce({ success: true })
    await cleanupFailedDownloadTask({ status: 'failed', source_task_ids: ['removed', 'remaining'] })
    expect(taskCenterApi.action).toHaveBeenLastCalledWith('engine:remaining', 'delete')
  })

  it('真实任务删除失败不能被忽略', async () => {
    taskCenterApi.action.mockRejectedValue(new Error('删除失败'))
    await expect(cleanupFailedDownloadTask({ id: 'engine', status: 'failed' })).rejects.toThrow('删除失败')
  })
})
