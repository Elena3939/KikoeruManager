import { getTransferRuntime } from './transferCardProgress.js'

const terminal = new Set(['completed', 'failed', 'cancelled'])
const runtimeAt = runtime => Number(runtime.snapshot_at_ms) || Date.parse(runtime.updated_at || '') || 0

export function mergeTransferTaskSnapshot(current, incoming) {
  if (!current) return incoming
  const next = { ...current, ...incoming }
  if (incoming.status && !incoming.display_status) next.display_status = incoming.status
  const currentAt = Date.parse(current.updated_at || '') || 0
  const incomingAt = Date.parse(incoming.updated_at || '') || 0
  let stale = currentAt > incomingAt && incomingAt > 0
  for (const mode of ['upload', 'download']) {
    const previous = getTransferRuntime(current, mode)
    const runtime = getTransferRuntime(incoming, mode)
    const older = runtimeAt(previous) > runtimeAt(runtime)
    if (older) stale = true
    if (Object.keys(previous).length || Object.keys(runtime).length) {
      next[`${mode}_runtime`] = older ? previous : { ...previous, ...runtime }
    }
  }
  if (stale) {
    for (const key of ['status', 'display_status', 'progress', 'current_step', 'updated_at', 'error_message']) next[key] = current[key]
  }
  return next
}

export function patchTransferTaskEvent(task, event) {
  if (String(task?.id) !== String(event?.engine_task_id || event?.task_id || '')) return task
  const previousAt = Date.parse(task.updated_at || '')
  const incomingAt = Date.parse(event.updated_at || '')
  if (Number.isFinite(previousAt) && Number.isFinite(incomingAt) && incomingAt < previousAt) return task
  if (['upload', 'download'].some(mode => event[`${mode}_runtime`]
    && runtimeAt(getTransferRuntime(task, mode)) > runtimeAt(event[`${mode}_runtime`]))) return task
  if (terminal.has(task.status) && !terminal.has(event.status || task.status)
    && (!Number.isFinite(incomingAt) || incomingAt <= previousAt)) return task
  const next = { ...task, status: event.status || task.status,
    display_status: event.display_status || event.status || task.display_status,
    progress: event.progress ?? task.progress, current_step: event.current_step ?? task.current_step,
    updated_at: event.updated_at || task.updated_at,
    error_message: event.failure_reason ?? task.error_message }
  for (const mode of ['upload', 'download']) {
    const runtime = event[`${mode}_runtime`]
    if (runtime) next[`${mode}_runtime`] = { ...getTransferRuntime(task, mode), ...runtime }
  }
  return next
}
