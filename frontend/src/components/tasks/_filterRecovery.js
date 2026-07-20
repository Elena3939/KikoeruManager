export function normalizeRecoveryStatus(entry) {
  const status = String(entry?.recoveryStatus || entry?.recovery_status || '').trim().toLowerCase()
  return status || (entry?.recoveryId || entry?.recovery_id ? 'available' : 'unavailable')
}

export function isRestoredFilterEntry(entry) {
  return normalizeRecoveryStatus(entry) === 'restored' || entry?.status === 'restored'
}

export function getFilterRestoreAvailability(entry, task) {
  if (!entry || (entry.status !== 'removed' && entry.status !== 'restored')) {
    return { enabled: false, reason: '该项不是过滤删除内容' }
  }
  if (isRestoredFilterEntry(entry)) {
    return { enabled: false, reason: '该项已经还原' }
  }
  if (entry.removedByDirectory) {
    return { enabled: false, reason: '请还原对应的上级目录' }
  }
  const recoveryId = String(entry.recoveryId || entry.recovery_id || '').trim()
  if (!recoveryId) {
    return { enabled: false, reason: '旧任务没有恢复数据' }
  }
  const metadata = task?.details?.metadata || {}
  if (!metadata.filter_recovery?.target_ready) {
    return { enabled: false, reason: '任务尚未确定最终入库位置' }
  }
  if (!['completed', 'waiting_manual'].includes(String(task?.status || '').trim())) {
    return { enabled: false, reason: '任务尚未完成' }
  }
  return { enabled: true, reason: '', recoveryId }
}

export function countRemovedFilterEntries(entries) {
  return (entries || []).filter(entry => entry?.status === 'removed' && !isRestoredFilterEntry(entry)).length
}
