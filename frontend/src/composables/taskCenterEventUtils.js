const STATUS_LABELS = {
  processing: '处理中',
  pending: '待处理',
  paused: '已暂停',
  waiting_manual: '等待人工',
  waiting_retry: '等待重试',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  partial_failed: '部分成功',
}

export function getTaskCenterItemKeys(item = {}) {
  return [
    String(item?.id || '').trim(),
    String(item?.engine_task_id || '').trim(),
    String(item?.entity_id || '').trim(),
    String(item?.record_id || '').trim(),
  ].filter(Boolean)
}

export function getTaskCenterEventKeys(event = {}) {
  return [
    String(event?.item_id || '').trim(),
    String(event?.engine_task_id || '').trim(),
    String(event?.entity_id || '').trim(),
    String(event?.record_id || '').trim(),
  ].filter(Boolean)
}

export function matchesTaskCenterEvent(item = {}, event = {}) {
  const itemKeys = getTaskCenterItemKeys(item)
  if (!itemKeys.length) return false
  const eventKeys = new Set(getTaskCenterEventKeys(event))
  return itemKeys.some((key) => eventKeys.has(key))
}

export function applyTaskCenterEventPatch(item = {}, event = {}) {
  if (!matchesTaskCenterEvent(item, event)) return item

  const status = String(event?.status || item.status || '').trim()
  const next = {
    ...item,
    status: status || item.status,
    progress: Number.isFinite(Number(event?.progress)) ? Number(event.progress) : Number(item.progress || 0),
    current_step: String(event?.current_step ?? item.current_step ?? '').trim() || item.current_step,
    updated_at: String(event?.updated_at || item.updated_at || '').trim() || item.updated_at,
  }

  if (status && STATUS_LABELS[status]) {
    next.status_label = STATUS_LABELS[status]
  }

  if (status === 'completed' || status === 'failed' || status === 'cancelled') {
    next.completed_at = next.completed_at || event?.updated_at || item.completed_at || item.started_at || item.created_at
  }

  return next
}

export function patchTaskCenterItemList(items = [], event = {}) {
  return Array.isArray(items)
    ? items.map((item) => applyTaskCenterEventPatch(item, event))
    : items
}

export function patchTaskCenterItemListBatch(items = [], events = []) {
  if (!Array.isArray(items) || !Array.isArray(events) || !events.length) return items

  const patchByKey = new Map()
  for (const event of events) {
    for (const key of getTaskCenterEventKeys(event)) {
      patchByKey.set(key, event)
    }
  }
  if (!patchByKey.size) return items

  let changed = false
  const nextItems = items.map((item) => {
    const keys = getTaskCenterItemKeys(item)
    const event = keys.map((key) => patchByKey.get(key)).find(Boolean)
    if (!event) return item
    const next = applyTaskCenterEventPatch(item, event)
    if (next !== item) changed = true
    return next
  })
  return changed ? nextItems : items
}

export function normalizeTaskCenterRealtimePayloads(detail = {}) {
  if (detail.type === 'task.center.changed') {
    return detail.payload?.type ? [detail.payload] : []
  }
  if (detail.type === 'task.center.changed.batch') {
    const events = detail.payload?.events
    return Array.isArray(events) ? events.filter(item => item?.type) : []
  }
  if (detail.type === 'task_center_changed_batch') {
    const events = detail.events
    return Array.isArray(events) ? events.filter(item => item?.type) : []
  }
  return detail?.type ? [detail] : []
}
