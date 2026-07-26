import { describe, expect, it } from 'vitest'

import {
  createLatestRequestGuard,
  mergeTrackedDownloadTaskIds,
  selectTrackedDownloadTasks,
} from './_downloadWorkbenchTracking.js'

describe('下载工作台任务跟踪', () => {
  it('追加任务时把新任务置顶并去重', () => {
    expect(mergeTrackedDownloadTaskIds(['old-1', 'old-2'], ['new-1', 'old-1']))
      .toEqual(['new-1', 'old-1', 'old-2'])
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
})
