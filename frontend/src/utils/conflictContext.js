export function getExistingConflictPath(conflict) {
  const existing = conflict?.context?.existing
  return existing?.path || existing?.unavailable_reason || conflict?.existing_path || '-'
}

export function preserveConflictStats(next, previous) {
  if (!previous) return next
  const context = { ...(next.context || {}) }
  for (const side of ['source', 'existing']) {
    const incoming = next.context?.[side]
    const old = previous.context?.[side]
    context[side] = {
      ...(incoming || {}),
      stats: incoming?.stats ?? (incoming?.path && incoming.path === old?.path ? old.stats : null) ?? null,
    }
  }
  return { ...next, context }
}

export function shouldRefreshConflictTarget(conflicts, detail, taskPayloads) {
  if (!conflicts.some(item => item.existing_path === '正在处理中' && !item.context?.existing?.path)) return false
  return detail?.type === 'library.index.status.changed' || taskPayloads.some(payload =>
    payload.type === 'task_center_changed' &&
    ['completed', 'failed', 'cancelled', 'canceled'].includes(String(payload.status || '').trim().toLowerCase()))
}
