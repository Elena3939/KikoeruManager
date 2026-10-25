const detailKeys = ['upload_files', 'uploaded_files', 'failed_files', 'verification_failures', 'source_lock_failures', 'progress_log']
const terminalStatuses = ['completed', 'failed', 'cancelled']

export function mergeUploadTaskSnapshot(current = {}, incoming = {}, { compact = false } = {}) {
  const next = {
    ...current,
    ...incoming,
    task_metadata: { ...current.task_metadata, ...incoming.task_metadata },
    upload_runtime: { ...current.upload_runtime, ...incoming.upload_runtime },
  }
  if (compact) {
    for (const key of detailKeys) next[key] = current[key] || []
  }
  const currentAt = Number(current.upload_runtime?.snapshot_at_ms || 0)
  const incomingAt = Number(incoming.upload_runtime?.snapshot_at_ms || 0)
  const terminalRegression = terminalStatuses.includes(current.status) && !terminalStatuses.includes(incoming.status || current.status)
  if ((terminalRegression && incomingAt <= currentAt) || (currentAt > incomingAt && !terminalStatuses.includes(incoming.status))) {
    for (const key of ['status', 'display_status', 'progress', 'current_step', 'updated_at', 'upload_runtime']) next[key] = current[key]
  }
  return next
}

export function getBackendUploadEta(tasks = []) {
  const active = tasks.filter(task => task.status === 'processing')
  if (!active.length) return null
  const seconds = active.map(task => Number(task.upload_runtime?.eta_seconds))
  if (seconds.some(value => !Number.isFinite(value) || value <= 0)) return null
  return Math.max(...seconds)
}
