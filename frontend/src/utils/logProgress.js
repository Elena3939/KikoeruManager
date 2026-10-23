export const TASK_PROGRESS_PREFIX = '__KIKOERUMANAGER_TASK_PROGRESS__'

const statusTones = {
  pending: 'waiting',
  processing: 'processing',
  paused: 'paused',
  waiting_manual: 'waiting',
  waiting_retry: 'waiting',
  completed: 'success',
  failed: 'error',
  partial_failed: 'error',
  cancelled: 'paused',
}

export function parseTaskProgressPayload(message) {
  if (!String(message || '').startsWith(TASK_PROGRESS_PREFIX)) return null
  try {
    const payload = JSON.parse(message.slice(TASK_PROGRESS_PREFIX.length))
    if (payload?.version !== 1 || !payload.task_id || !Object.hasOwn(statusTones, payload.status)) return null
    if (typeof payload.progress !== 'number' || !Number.isFinite(payload.progress)) return null
    return payload
  } catch {
    return null
  }
}

export function buildTaskProgress(log, order = 0) {
  const payload = log?.taskProgressPayload
  if (!payload) return null
  return {
    id: payload.task_id,
    taskId: payload.task_id,
    shortId: payload.task_id.slice(0, 8),
    status: payload.status,
    rjcode: payload.rjcode || '',
    archiveLabel: payload.source_label || '',
    title: [payload.phase, payload.rjcode || payload.source_label].filter(Boolean).join(' '),
    phase: payload.phase || '任务',
    detail: payload.step || '',
    progress: Math.max(0, Math.min(100, payload.progress)),
    tone: statusTones[payload.status],
    active: payload.status === 'processing',
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
    order,
  }
}
