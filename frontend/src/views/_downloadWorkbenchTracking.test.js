import { describe, expect, it } from 'vitest'

import {
  createLatestRequestGuard,
  mergeTrackedDownloadTaskIds,
  replaceTrackedDownloadTaskId,
  resolveTrackedDownloadBatch,
  selectTrackedDownloadTasks,
} from './_downloadWorkbenchTracking.js'
import { getDownloadBatchPercent } from '../utils/downloadProgress.js'

describe('下载工作台任务跟踪', () => {
  it('追加任务时把新任务置顶并去重', () => {
    expect(mergeTrackedDownloadTaskIds(['old-1', 'old-2'], ['new-1', 'old-1']))
      .toEqual(['new-1', 'old-1', 'old-2'])
  })

  it('legacy 等待重试创建新任务后替换旧跟踪 ID', () => {
    expect(replaceTrackedDownloadTaskId(
      ['legacy-waiting', 'other-task'],
      'legacy-waiting',
      'retry-task',
    )).toEqual(['retry-task', 'other-task'])
  })

  it('旧状态快照缺少新任务时不修改跟踪 ID', () => {
    const trackedIds = ['new-1', 'old-1']
    const visibleTasks = selectTrackedDownloadTasks(trackedIds, [
      { id: 'old-1', status: 'processing' },
    ])

    expect(visibleTasks.map(task => task.id)).toEqual(['old-1'])
    expect(trackedIds).toEqual(['new-1', 'old-1'])
  })

  it('状态返回顺序变化时仍按工作台跟踪顺序展示', () => {
    const visibleTasks = selectTrackedDownloadTasks(
      ['task-2', 'task-1'],
      [{ id: 'task-1' }, { id: 'task-2' }],
    )

    expect(visibleTasks.map(task => task.id)).toEqual(['task-2', 'task-1'])
  })

  it('只接受最后发起的状态请求', () => {
    const guard = createLatestRequestGuard()
    const firstRequest = guard.begin()
    const secondRequest = guard.begin()

    expect(guard.isLatest(firstRequest)).toBe(false)
    expect(guard.isLatest(secondRequest)).toBe(true)
  })

  it('关闭工作台后拒绝仍在途的状态响应', () => {
    const guard = createLatestRequestGuard()
    const pendingRequest = guard.begin()

    guard.invalidate()

    expect(guard.isLatest(pendingRequest)).toBe(false)
  })

  it('社团补全追加批次后拒绝旧批次状态覆盖', () => {
    const guard = createLatestRequestGuard()
    const oldBatchRequest = guard.begin()
    const trackedIds = mergeTrackedDownloadTaskIds(['old-task'], ['new-task'])
    const newBatchRequest = guard.begin()

    expect(guard.isLatest(oldBatchRequest)).toBe(false)
    expect(guard.isLatest(newBatchRequest)).toBe(true)
    expect(trackedIds).toEqual(['new-task', 'old-task'])
    expect(selectTrackedDownloadTasks(trackedIds, [{ id: 'old-task' }]))
      .toEqual([{ id: 'old-task' }])
    expect(trackedIds).toEqual(['new-task', 'old-task'])
  })

  it('新下载排除四个早已完成的任务，小窗恢复为当前下载的 7%', () => {
    const current = {
      id: 'new-task',
      status: 'processing',
      created_at: '2026-10-12T10:00:00',
      progress: 7,
      download_runtime: { total_bytes: 1000, transferred_bytes: 79 },
    }
    const history = [1, 2, 3, 4].map(index => ({
      id: `old-${index}`,
      status: 'completed',
      progress: 100,
      completed_at: '2026-10-11T10:00:00',
    }))
    const snapshot = [...history, current]
    const ids = mergeTrackedDownloadTaskIds(history.map(task => task.id), [current.id])
    const batch = resolveTrackedDownloadBatch(ids, [current.id], snapshot)

    expect(batch.taskIds).toEqual(['new-task'])
    expect(getDownloadBatchPercent(selectTrackedDownloadTasks(batch.taskIds, snapshot))).toBe(7)
  })

  it('新下载继续跟踪此前正在下载、暂停和等待重试的任务', () => {
    const snapshot = [
      { id: 'new-task', status: 'pending', created_at: '2026-10-12T10:00:00' },
      ...['processing', 'paused', 'pending', 'waiting_retry'].map(status => ({ id: status, status })),
      { id: 'failed', status: 'failed', completed_at: '2026-10-11T10:00:00' },
      { id: 'cancelled', status: 'cancelled', completed_at: '2026-10-11T10:00:00' },
    ]
    const batch = resolveTrackedDownloadBatch(snapshot.map(task => task.id), ['new-task'], snapshot)

    expect(batch.taskIds).toEqual(['new-task', 'processing', 'paused', 'pending', 'waiting_retry'])
  })

  it('本批次完成项和本次提交之后才完成的旧活跃任务继续留在队列', () => {
    const snapshot = [
      {
        id: 'new-task',
        status: 'completed',
        created_at: '2026-10-12T10:00:00',
        completed_at: '2026-10-12T10:02:00',
      },
      { id: 'old-active', status: 'completed', completed_at: '2026-10-12T10:01:00' },
      { id: 'old-failed', status: 'failed', completed_at: '2026-10-12T10:01:00' },
    ]

    expect(resolveTrackedDownloadBatch(
      snapshot.map(task => task.id), ['new-task'], snapshot,
    ).taskIds).toEqual(['new-task', 'old-active', 'old-failed'])
  })

  it('恢复旧缓存时以置顶的新任务为批次边界，移除历史完成项', () => {
    const savedIds = ['latest', 'history']
    const batch = resolveTrackedDownloadBatch(savedIds, savedIds.slice(0, 1), [
      { id: 'latest', status: 'processing', created_at: '2026-10-12T10:00:00' },
      { id: 'history', status: 'completed', completed_at: '2026-10-11T10:00:00' },
    ])
    const restored = resolveTrackedDownloadBatch(
      batch.taskIds, ['latest'], [], batch.batchStartedAt,
    )

    expect(batch.taskIds).toEqual(['latest'])
    expect(restored).toEqual(batch)
  })

  it('快照暂时缺少新任务和未返回的旧任务时不丢跟踪 ID', () => {
    const ids = ['new-task', 'unknown', 'history']
    const snapshot = [{ id: 'history', status: 'completed', completed_at: '2026-10-11T10:00:00' }]
    const batch = resolveTrackedDownloadBatch(ids, ['new-task'], snapshot)

    expect(batch.taskIds).toEqual(ids)
    expect(resolveTrackedDownloadBatch(
      ids, ['new-task'], snapshot, '2026-10-12T10:00:00',
    ).taskIds).toEqual(['new-task', 'unknown'])
  })

  it('提交后旧轮询响应无法把历史完成项重新加入队列', () => {
    const guard = createLatestRequestGuard()
    const oldRequest = guard.begin()
    const ids = mergeTrackedDownloadTaskIds(['history'], ['new-task'])
    const newRequest = guard.begin()
    const batch = resolveTrackedDownloadBatch(ids, ['new-task'], [
      { id: 'new-task', status: 'pending', created_at: '2026-10-12T10:00:00' },
      { id: 'history', status: 'completed', completed_at: '2026-10-11T10:00:00' },
    ])

    expect(guard.isLatest(oldRequest)).toBe(false)
    expect(guard.isLatest(newRequest)).toBe(true)
    expect(batch.taskIds).toEqual(['new-task'])
  })
})
