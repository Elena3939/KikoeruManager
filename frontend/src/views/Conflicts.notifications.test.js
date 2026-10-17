import { describe, expect, it, vi } from 'vitest'
import source from './Conflicts.vue?raw'

function createHarness(items) {
  const bindings = {
    conflicts: { value: items },
    pendingSkipConflictIds: new Set(),
    handledTerminalTaskEvents: new Set(),
    conflictApi: { resolve: vi.fn() },
    updateConflictLinkedTask: vi.fn(),
    markConflictRetrying: vi.fn(),
    isConflictRetrying: conflict => Boolean(conflict.new_metadata?.retry_from_conflicts),
    ElMessage: { success: vi.fn(), warning: vi.fn() },
  }
  bindings.removeConflict = vi.fn(id => {
    bindings.conflicts.value = bindings.conflicts.value.filter(item => item.id !== id)
  })
  bindings.fetchConflicts = vi.fn(async () => { bindings.conflicts.value = [] })
  const names = ['getConflictTaskId', 'getConflictResolutionAction', 'handleConflictTaskPayload', 'resolveSkip']
  const functions = names.map(name => {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
    if (start < 0) throw new Error(`找不到函数 ${name}`)
    return source.slice(start, source.indexOf('\n}', start) + 2)
  })
  const handlers = new Function(...Object.keys(bindings), `${functions.join('\n')}\nreturn { handleConflictTaskPayload, resolveSkip }`)(...Object.values(bindings))
  return { ...bindings, ...handlers }
}

function conflict(id, action = '') {
  return { id, task_id: `task-${id}`, new_metadata: { resolution_action: action } }
}

function completed(id) {
  return { type: 'task_center_changed', engine_task_id: `task-${id}`, status: 'completed' }
}

describe('问题作品处理完成通知', () => {
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
