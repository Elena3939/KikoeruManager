export function mergeTrackedDownloadTaskIds(currentTaskIds = [], newTaskIds = []) {
  const merged = [...newTaskIds, ...currentTaskIds]
    .map(id => String(id || '').trim())
    .filter(Boolean)

  return [...new Set(merged)]
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
