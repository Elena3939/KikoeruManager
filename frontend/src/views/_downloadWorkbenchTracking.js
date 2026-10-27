export function mergeTrackedDownloadTaskIds(currentTaskIds = [], newTaskIds = []) {
  const merged = [...newTaskIds, ...currentTaskIds]
    .map(id => String(id || '').trim())
    .filter(Boolean)

  return [...new Set(merged)]
}

export function replaceTrackedDownloadTaskId(currentTaskIds = [], previousTaskId = '', nextTaskId = '') {
  const previous = String(previousTaskId || '').trim()
  const next = String(nextTaskId || '').trim()
  if (!next) return mergeTrackedDownloadTaskIds(currentTaskIds)

  return mergeTrackedDownloadTaskIds(
    currentTaskIds.filter(id => String(id || '').trim() !== previous),
    [next],
  )
}

export function selectTrackedDownloadTasks(taskIds = [], tasks = []) {
  const tasksById = new Map(
    tasks
      .filter(task => task?.id)
      .map(task => [String(task.id), task]),
  )

  return taskIds
    .map(id => tasksById.get(String(id)))
    .filter(Boolean)
}

export function resolveTrackedDownloadBatch(taskIds = [], batchTaskIds = [], tasks = [], batchStartedAt = '') {
  const normalizedIds = mergeTrackedDownloadTaskIds(taskIds)
  const batchIds = new Set(mergeTrackedDownloadTaskIds(batchTaskIds))
  const tasksById = new Map(tasks.map(task => [String(task?.id || ''), task]))
  const batchTasks = selectTrackedDownloadTasks([...batchIds], tasks)
  const createdTimes = batchTasks
    .map(task => Date.parse(task.created_at))
    .filter(Number.isFinite)
  const startedTime = Date.parse(batchStartedAt)
  const boundary = Number.isFinite(startedTime)
    ? startedTime
    : createdTimes.length ? Math.min(...createdTimes) : NaN

  // 旧缓存按新任务置顶；失败项保留供重试，只排除提交前已成功或取消的任务。
  if (!Number.isFinite(boundary)) return { taskIds: normalizedIds, batchStartedAt }
  return {
    taskIds: normalizedIds.filter(id => {
      if (batchIds.has(id)) return true
      const task = tasksById.get(id)
      const status = String(task?.display_status || task?.status || '').trim().toLowerCase()
      if (!task || !['completed', 'success', 'succeeded', 'cancelled', 'canceled'].includes(status)) return true
      return Date.parse(task.completed_at) >= boundary
    }),
    batchStartedAt: new Date(boundary).toISOString(),
  }
}

export function createLatestRequestGuard() {
  let sequence = 0

  return {
    begin() {
      sequence += 1
      return sequence
    },
    invalidate() {
      sequence += 1
    },
    isLatest(requestSequence) {
      return requestSequence === sequence
    },
  }
}
