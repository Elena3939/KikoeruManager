import { describe, expect, it, vi } from 'vitest'
import circleSource from './CircleCompletion.vue?raw'
import asmrSource from './ASMRSync.vue?raw'
import { getAsmrDownloadSessionId, getDownloadEngineTaskId } from '../utils/downloadTaskIdentity.js'

function load(source, name, bindings) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  const body = source.slice(start, source.indexOf('\n}', start) + 2)
  return new Function(...Object.keys(bindings), `${body}; return ${name}`)(...Object.values(bindings))
}

describe('YAAS 工作台任务控制', () => {
  const task = {
    id: 'session:engine-id::RJ123456', active_task_id: 'engine-id',
    source_task_ids: ['engine-id', 'other-volume'],
    task_metadata: { session_id: 'engine-id', resource_source: 'imoutoheaven' },
  }

  it('引擎会话不冒充 ASMR 会话，合并行保留真实任务标识', () => {
    expect(getAsmrDownloadSessionId(task)).toBe('')
    expect(getDownloadEngineTaskId(task)).toBe('engine-id')
    expect(getAsmrDownloadSessionId({ task_metadata: { session_id: 'asmr-session' } })).toBe('asmr-session')
  })

  for (const [source, suffix, refresh] of [
    [circleSource, 'DownloadTask', 'refreshDownloadWorkbench'],
    [asmrSource, 'EnhancedDownloadTask', 'refreshEnhancedDownloadWorkbench'],
  ]) {
    it(`${suffix} 的整任务重试保留行加载态并使用真实任务标识`, async () => {
      const httpDownloadApi = { retry: vi.fn() }
      const asmrSyncApi = { retry: vi.fn(), retryFailedSession: vi.fn() }
      const retryingTaskIds = { value: new Set() }
      const acquireEnhancedRetryScope = vi.fn().mockReturnValue('retry-scope')
      const handler = load(source, suffix === 'DownloadTask' ? 'retryDownloadTask' : 'retryEnhancedDownloadTask', {
        getAsmrDownloadSessionId, getDownloadEngineTaskId,
        getEnhancedRetrySessionId: getAsmrDownloadSessionId,
        httpDownloadApi, asmrSyncApi, retryingTaskIds,
        acquireEnhancedRetryScope, releaseEnhancedRetryScope: vi.fn(),
        ElMessage: { success: vi.fn(), error: vi.fn() },
        [refresh]: vi.fn(() => {
          if (suffix === 'DownloadTask') expect(retryingTaskIds.value.has(task.id)).toBe(true)
        }),
      })
      await handler(task)
      expect(httpDownloadApi.retry).toHaveBeenCalledWith('engine-id')
      expect(asmrSyncApi.retryFailedSession).not.toHaveBeenCalled()
      expect(asmrSyncApi.retry).not.toHaveBeenCalled()
      if (suffix === 'EnhancedDownloadTask') {
        expect(acquireEnhancedRetryScope).toHaveBeenCalledWith(expect.objectContaining({ visibleKey: task.id }))
      }
      expect(retryingTaskIds.value.size).toBe(0)
    })

    it.each(['Pause', 'Resume', 'Cancel'])(`${suffix} 的 %s 使用真实任务接口`, async action => {
      const httpDownloadApi = { pause: vi.fn(), resume: vi.fn() }
      const taskApi = { batchCancelCleanup: vi.fn() }
      const asmrSyncApi = { pauseSession: vi.fn(), resumeSession: vi.fn(), cancelSession: vi.fn() }
      const handler = load(source, `handle${action}${suffix}`, {
        getAsmrDownloadSessionId, getDownloadEngineTaskId, httpDownloadApi, taskApi, asmrSyncApi,
        showSystemConfirm: vi.fn().mockResolvedValue(true),
        ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
        [refresh]: vi.fn(),
      })
      await handler(task)
      if (action === 'Cancel') expect(taskApi.batchCancelCleanup).toHaveBeenCalledWith(['engine-id', 'other-volume'])
      else expect(httpDownloadApi[action.toLowerCase()]).toHaveBeenCalledWith('engine-id')
      for (const method of Object.values(asmrSyncApi)) expect(method).not.toHaveBeenCalled()
    })
  }
})
