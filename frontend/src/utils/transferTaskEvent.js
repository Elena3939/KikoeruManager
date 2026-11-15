import { getTransferRuntime } from './transferCardProgress.js'

const terminal = new Set(['completed', 'failed', 'cancelled'])
const runtimeAt = runtime => {
  if (Number(runtime.snapshot_at_ms)) return Number(runtime.snapshot_at_ms)
  const stamp = runtime.updated_at || ''
  const milliseconds = Date.parse(stamp) || 0
  // Python 时间戳包含微秒；只用 Date.parse 会把同一毫秒内的旧文件快照当成新状态。
  const fraction = String(stamp).match(/\.(\d+)(?:Z|[+-]\d{2}:?\d{2})?$/)?.[1] || ''
  return milliseconds + (fraction.length > 3 ? Number(`0.${fraction.slice(3)}`) : 0)
}

const fileKey = file => String(file?.relative_path || file?.name || '')

export function mergeTransferFiles(previous = [], incoming = [], preserveMissing = true) {
  const oldRows = new Map(previous.map(file => [fileKey(file), file]))
  const rows = preserveMissing ? [...previous] : []
  const positions = new Map(rows.map((file, index) => [fileKey(file), index]))
  for (const file of incoming) {
    const key = fileKey(file)
    if (!key) continue
    const old = oldRows.get(key)
    const next = old && runtimeAt(old) > runtimeAt(file) ? old : { ...old, ...file }
    if (positions.has(key)) rows[positions.get(key)] = next
    else { positions.set(key, rows.length); rows.push(next) }
  }
  return rows
}

// 同一任务在一个渲染窗口内的事件必须合并文件变化，不能只保留最后一条。
export function mergeTransferRealtimeEvents(previous, incoming) {
  if (!previous) return incoming
  const old = previous.payload || {}
  const next = incoming.payload || {}
  const older = runtimeAt(old) > runtimeAt(next)
  const first = older ? next : old
  const last = older ? old : next
  const payload = { ...first, ...last }
  for (const mode of ['upload', 'download']) {
    const key = `${mode}_runtime`
    if (first[key] || last[key]) payload[key] = { ...first[key], ...last[key] }
  }
  if (old.download_file_changes || next.download_file_changes) {
    payload.download_file_changes = mergeTransferFiles(old.download_file_changes, next.download_file_changes)
  }
  return { ...(older ? previous : incoming), payload }
}

export function mergeTransferTaskSnapshot(current, incoming) {
  if (!current) return incoming
  const next = { ...current, ...incoming }
  if (incoming.status && !incoming.display_status) next.display_status = incoming.status
  const currentAt = runtimeAt(current)
  const incomingAt = runtimeAt(incoming)
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
  if (Array.isArray(incoming.download_files)) {
    const preserveFull = current.download_files_truncated === false && incoming.download_files_truncated
    next.download_files = mergeTransferFiles(current.download_files, incoming.download_files, stale || preserveFull || incoming.download_files_truncated)
    if (preserveFull) {
      next.download_files_total = current.download_files_total
      next.download_files_truncated = false
    }
  }
  return next
}

export function patchTransferTaskEvent(task, event) {
  if (String(task?.id) !== String(event?.engine_task_id || event?.task_id || '')) return task
  const previousAt = runtimeAt(task)
  const incomingAt = runtimeAt(event)
  const stale = (previousAt > 0 && incomingAt > 0 && incomingAt < previousAt)
    || ['upload', 'download'].some(mode => event[`${mode}_runtime`]
      && runtimeAt(getTransferRuntime(task, mode)) > runtimeAt(event[`${mode}_runtime`]))
    || (terminal.has(task.status) && !terminal.has(event.status || task.status)
      && (!incomingAt || incomingAt <= previousAt))
  const next = stale ? task : { ...task, status: event.status || task.status,
    display_status: event.display_status || event.status || task.display_status,
    progress: event.progress ?? task.progress, current_step: event.current_step ?? task.current_step,
    updated_at: event.updated_at || task.updated_at,
    error_message: event.failure_reason ?? task.error_message }
  for (const mode of ['upload', 'download']) {
    const runtime = event[`${mode}_runtime`]
    if (runtime && !stale) next[`${mode}_runtime`] = { ...getTransferRuntime(task, mode), ...runtime }
  }
  if (event.download_file_changes?.length) return { ...next,
    download_files: mergeTransferFiles(task.download_files, event.download_file_changes) }
  return next
}
