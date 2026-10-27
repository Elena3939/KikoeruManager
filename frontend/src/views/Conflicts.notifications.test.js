import { describe, expect, it, vi } from 'vitest'
import source from './Conflicts.vue?raw'

function createHarness(items) {
  const bindings = {
    conflicts: { value: items },
    pendingSkipConflictIds: new Set(),
    handledTerminalTaskEvents: new Set(),
    conflictApi: { resolve: vi.fn(), retry: vi.fn() },
    updateConflictLinkedTask: vi.fn(),
    markConflictRetrying: vi.fn(),
    isConflictRetrying: conflict => Boolean(conflict.new_metadata?.retry_from_conflicts),
    ElMessage: { success: vi.fn(), warning: vi.fn() },
  }
  bindings.removeConflict = vi.fn(id => {
    bindings.conflicts.value = bindings.conflicts.value.filter(item => item.id !== id)
  })
  bindings.fetchConflicts = vi.fn(async () => { bindings.conflicts.value = [] })
  const names = ['getConflictTaskId', 'getConflictResolutionAction', 'handleConflictTaskPayload', 'resolveSkip', 'startRetry']
  const functions = names.map(name => {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
    if (start < 0) throw new Error(`找不到函数 ${name}`)
    return source.slice(start, source.indexOf('\n}', start) + 2)
  })
  const handlers = new Function(...Object.keys(bindings), `${functions.join('\n')}\nreturn { handleConflictTaskPayload, resolveSkip, startRetry }`)(...Object.values(bindings))
  return { ...bindings, ...handlers }
}

function conflict(id, action = '') {
  return { id, task_id: `task-${id}`, new_metadata: { resolution_action: action } }
}

function completed(id) {
  return { type: 'task_center_changed', engine_task_id: `task-${id}`, status: 'completed' }
}

describe('问题作品处理完成通知', () => {
  it('旧失败任务被重试替代时不会误报新一轮重试失败', () => {
    const harness = createHarness([conflict('1', 'RETRY')])
    harness.handleConflictTaskPayload({
      ...completed('1'), reason: 'retry_superseded', status: 'failed',
    })
    expect(harness.updateConflictLinkedTask).not.toHaveBeenCalled()
    expect(harness.fetchConflicts).not.toHaveBeenCalled()
    expect(harness.ElMessage.warning).not.toHaveBeenCalled()
  })

  it('新的处理任务 ID 优先于列表尚未刷新的旧关联任务', () => {
    const item = conflict('1', 'RETRY')
    item.linked_task = { id: 'task-1', status: 'failed' }
    item.new_metadata.resolution_task_id = 'new-task'
    const harness = createHarness([item])
    harness.handleConflictTaskPayload({ ...completed('1'), status: 'failed' })
    expect(harness.updateConflictLinkedTask).not.toHaveBeenCalled()
    expect(harness.fetchConflicts).not.toHaveBeenCalled()
  })

  it('旧任务终态等待刷新期间切换到新重试任务时不再弹旧失败通知', async () => {
    const harness = createHarness([conflict('1', 'RETRY')])
    let finishRefresh
    harness.fetchConflicts.mockImplementation(() => new Promise(resolve => { finishRefresh = resolve }))
    harness.handleConflictTaskPayload({ ...completed('1'), reason: 'failed', status: 'failed' })
    harness.conflicts.value[0].new_metadata.resolution_task_id = 'new-task'
    finishRefresh()
    await Promise.resolve()
    expect(harness.ElMessage.warning).not.toHaveBeenCalled()
  })

  it.each([false, true])('重试接口返回后立即绑定当前任务，already_running=%s', async alreadyRunning => {
    const item = conflict('1', 'RETRY')
    const harness = createHarness([item])
    const result = { task_id: 'new-task', already_running: alreadyRunning }
    harness.conflictApi.retry.mockResolvedValue(result)
    expect(await harness.startRetry(item, { passwords: ['test'] })).toBe(result)
    expect(harness.updateConflictLinkedTask).toHaveBeenCalledWith('1', {
      engine_task_id: 'new-task', status: alreadyRunning ? 'processing' : 'pending',
    }, 'RETRY')
  })

  it('当前重试任务真正失败时仍然提示失败原因', async () => {
    const harness = createHarness([conflict('1', 'RETRY')])
    harness.handleConflictTaskPayload({
      ...completed('1'), reason: 'failed', status: 'failed', error_message: '密码错误',
    })
    await vi.waitFor(() => expect(harness.ElMessage.warning).toHaveBeenCalledWith('重试失败：密码错误'))
  })

  it.each(['', 'SKIP'])('动作为 %s 的原任务完成事件不会误报保留新版', action => {
    const harness = createHarness([conflict('1', action)])
    harness.handleConflictTaskPayload(completed('1'))
    expect(harness.updateConflictLinkedTask).not.toHaveBeenCalled()
    expect(harness.fetchConflicts).not.toHaveBeenCalled()
    expect(harness.ElMessage.success).not.toHaveBeenCalled()
  })

  it('批量跳过期间即使残留保留新版或重试动作，也不产生逐项完成通知', async () => {
    const harness = createHarness(['KEEP_NEW', 'RETRY', '', 'KEEP_NEW'].map((action, index) => conflict(String(index), action)))
    const finishRequests = []
    harness.conflictApi.resolve.mockImplementation(() => new Promise(resolve => finishRequests.push(resolve)))
    const requests = harness.conflicts.value.map(item => harness.resolveSkip(item))
    for (let index = 0; index < 4; index++) harness.handleConflictTaskPayload(completed(String(index)))
    expect(harness.pendingSkipConflictIds.size).toBe(4)
    expect(harness.updateConflictLinkedTask).not.toHaveBeenCalled()
    expect(harness.fetchConflicts).not.toHaveBeenCalled()
    finishRequests.forEach(resolve => resolve())
    await Promise.all(requests)
    expect(harness.conflictApi.resolve).toHaveBeenCalledTimes(4)
    expect(harness.conflictApi.resolve).toHaveBeenCalledWith('0', { action: 'SKIP' })
    expect(harness.conflicts.value).toEqual([])
    expect(harness.pendingSkipConflictIds.size).toBe(0)
    expect(harness.ElMessage.success).not.toHaveBeenCalled()
  })

  it('跳过失败后释放动作标记并保留问题项', async () => {
    const harness = createHarness([conflict('1')])
    harness.conflictApi.resolve.mockRejectedValue(new Error('请求失败'))
    await expect(harness.resolveSkip(harness.conflicts.value[0])).rejects.toThrow('请求失败')
    expect(harness.pendingSkipConflictIds.size).toBe(0)
    expect(harness.removeConflict).not.toHaveBeenCalled()
    expect(harness.conflicts.value).toHaveLength(1)
  })

  it.each([
    ['KEEP_NEW', '保留新版完成，已自动刷新'],
    ['RETRY', '重试成功，已移出问题作品'],
  ])('%s 正常完成仍然提示，重复事件只提示一次', async (action, message) => {
    const harness = createHarness([conflict('1', action)])
    harness.handleConflictTaskPayload(completed('1'))
    harness.handleConflictTaskPayload(completed('1'))
    await vi.waitFor(() => expect(harness.ElMessage.success).toHaveBeenCalledTimes(1))
    expect(harness.ElMessage.success).toHaveBeenCalledWith(message)
    expect(harness.fetchConflicts).toHaveBeenCalledTimes(1)
  })
})

describe('问题作品批量重试', () => {
  it('整批只调用一次接口，并分别绑定成功任务与保留提交失败项', async () => {
    const targets = [conflict('1'), conflict('2'), conflict('3')]
    const bindings = {
      batchRetryTargets: { value: targets },
      setBatchState: vi.fn(),
      buildConflictRetryPayload: vi.fn((_item, input) => input),
      conflictApi: {
        retryBatch: vi.fn().mockResolvedValue({ items: [
          { conflict_id: '1', success: true, task_id: 'retry-1' },
          { conflict_id: '2', success: false, message: '源文件不存在' },
          { conflict_id: '3', success: true, already_running: true, task_id: 'running-3' },
        ] }),
      },
      updateConflictLinkedTask: vi.fn(),
      markConflictRetrying: vi.fn(),
      startRetryPoller: vi.fn(),
      fetchConflicts: vi.fn(),
      presentBatchResult: vi.fn(),
      resolveErrorMessage: vi.fn(),
      ElMessage: { error: vi.fn() },
    }
    const start = source.indexOf('async function handleBatchRetryConfirm(')
    const fn = source.slice(start, source.indexOf('\n}', start) + 2)
    const run = new Function(...Object.keys(bindings), `${fn}\nreturn handleBatchRetryConfirm`)(...Object.values(bindings))
    await run([{ conflictId: '1', passwords: ['specified'] }])
    expect(bindings.conflictApi.retryBatch).toHaveBeenCalledTimes(1)
    expect(bindings.conflictApi.retryBatch.mock.calls[0][0]).toHaveLength(3)
    expect(bindings.updateConflictLinkedTask).toHaveBeenCalledTimes(2)
    expect(bindings.updateConflictLinkedTask).toHaveBeenCalledWith('3', {
      engine_task_id: 'running-3', status: 'processing',
    }, 'RETRY')
    expect(bindings.presentBatchResult.mock.calls[0][1]).toEqual([targets[0], targets[2]])
    expect(bindings.presentBatchResult.mock.calls[0][2]).toEqual([
      { conflict: targets[1], message: '源文件不存在' },
    ])
    expect(bindings.setBatchState).toHaveBeenLastCalledWith('', false)
  })
})
