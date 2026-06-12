import { readonly, ref } from 'vue'
import { apiUrl, redirectIfSecurityGateExpired } from '../api'

const STREAM_URL = apiUrl('/events/stream')
const MAX_RETRY_DELAY = 30000
const TASK_EVENT_BATCH_WINDOW_MS = 80
const TASK_EVENT_NAVIGATION_BATCH_WINDOW_MS = 260
const NAVIGATION_GRACE_MS = 420

const connected = ref(false)
const lastEvent = ref(null)
const lastEventAt = ref(0)
const lastErrorAt = ref(0)

let source = null
let retryTimer = null
let retryDelay = 2000
let consumers = 0
let manuallyClosed = false

const subscribers = new Map()
const pendingTaskEvents = new Map()
let taskEventBatchTimer = null
let routeNavigationActiveUntil = 0
let routeNavigationListenersBound = false

function clearRetryTimer() {
  if (!retryTimer) return
  clearTimeout(retryTimer)
  retryTimer = null
}

function emitDomEvent(name, detail) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

function taskEventBatchDelay() {
  return Date.now() < routeNavigationActiveUntil
    ? TASK_EVENT_NAVIGATION_BATCH_WINDOW_MS
    : TASK_EVENT_BATCH_WINDOW_MS
}

function taskEventBatchKey(event) {
  const payload = event?.payload || {}
  return String(
    payload.item_id
      || payload.engine_task_id
      || payload.entity_id
      || payload.record_id
      || event?.id
      || `${event?.domain || 'task'}:${event?.updated_at || Date.now()}`
  )
}

function dispatchCompatibilityEvent(event) {
  const payload = event?.payload || {}
  if (event?.type === 'task.center.changed' && payload.type) {
    emitDomEvent('kikoerumanager:task-center:changed', payload)
    return
  }
  if (event?.type === 'processed_archive.changed') {
    emitDomEvent('kikoerumanager:task-center:changed', {
      type: 'processed_archive_changed',
      ...payload,
    })
    return
  }
  if (event?.type === 'library.index.status.changed') {
    emitDomEvent('kikoerumanager:task-center:changed', {
      type: 'library_index_status_changed',
      ...payload,
    })
    return
  }
  if (event?.type === 'circle.owned.synced') {
    emitDomEvent('kikoerumanager:circle:owned-synced', payload)
  }
}

function dispatchTaskBatchCompatibilityEvent(batchEvent) {
  const payloads = Array.isArray(batchEvent?.payload?.events) ? batchEvent.payload.events : []
  emitDomEvent('kikoerumanager:task-center:changed', {
    type: 'task_center_changed_batch',
    events: payloads,
    count: payloads.length,
    updated_at: batchEvent?.updated_at || new Date().toISOString(),
  })
}

function notifySubscribers(event) {
  const direct = subscribers.get(event?.type)
  if (direct) {
    for (const handler of [...direct]) {
      try { handler(event) } catch {}
    }
  }
  const wildcard = subscribers.get('*')
  if (wildcard) {
    for (const handler of [...wildcard]) {
      try { handler(event) } catch {}
    }
  }
}

function dispatchEventNow(event) {
  emitDomEvent('kikoerumanager:events:message', event)
  dispatchCompatibilityEvent(event)
  notifySubscribers(event)
}

function flushTaskEventBatch() {
  if (taskEventBatchTimer) {
    clearTimeout(taskEventBatchTimer)
    taskEventBatchTimer = null
  }
  const events = [...pendingTaskEvents.values()]
  pendingTaskEvents.clear()
  if (!events.length) return
  if (events.length === 1) {
    dispatchEventNow(events[0])
    return
  }
  const latest = events[events.length - 1]
  const batchEvent = {
    type: 'task.center.changed.batch',
    reason: 'batch',
    id: latest?.id || '',
    domain: latest?.domain || '',
    status: latest?.status || '',
    progress: Number(latest?.progress || 0),
    current_step: latest?.current_step || '',
    updated_at: latest?.updated_at || new Date().toISOString(),
    payload: {
      type: 'task_center_changed_batch',
      events: events.map((event) => event.payload || {}),
    },
  }
  emitDomEvent('kikoerumanager:events:message', batchEvent)
  dispatchTaskBatchCompatibilityEvent(batchEvent)
  notifySubscribers(batchEvent)
}

function scheduleTaskEventBatch(event) {
  pendingTaskEvents.set(taskEventBatchKey(event), event)
  if (taskEventBatchTimer) return
  taskEventBatchTimer = setTimeout(flushTaskEventBatch, taskEventBatchDelay())
}

function postponeTaskEventBatchForNavigation() {
  routeNavigationActiveUntil = Date.now() + NAVIGATION_GRACE_MS
  if (!pendingTaskEvents.size || !taskEventBatchTimer) return
  clearTimeout(taskEventBatchTimer)
  taskEventBatchTimer = setTimeout(flushTaskEventBatch, taskEventBatchDelay())
}

function bindRouteNavigationListeners() {
  if (routeNavigationListenersBound || typeof window === 'undefined') return
  window.addEventListener('kikoerumanager:route:navigation-start', () => {
    postponeTaskEventBatchForNavigation()
  })
  window.addEventListener('kikoerumanager:route:navigation-end', () => {
    postponeTaskEventBatchForNavigation()
  })
  routeNavigationListenersBound = true
}

function handleMessage(messageEvent) {
  try {
    const event = JSON.parse(messageEvent.data)
    lastEvent.value = event
    lastEventAt.value = Date.now()
    if (event.type === 'connected') {
      connected.value = true
      retryDelay = 2000
    }
    if (event.type === 'task.center.changed') {
      scheduleTaskEventBatch(event)
      return
    }
    dispatchEventNow(event)
  } catch {
    // 跳过无法解析的事件，SSE 连接继续保留。
  }
}

function connect() {
  if (typeof window === 'undefined') return
  if (source && source.readyState !== EventSource.CLOSED) return

  bindRouteNavigationListeners()
  manuallyClosed = false
  clearRetryTimer()
  source = new EventSource(STREAM_URL, { withCredentials: true })
  source.onmessage = handleMessage
  source.onerror = async () => {
    connected.value = false
    lastErrorAt.value = Date.now()
    source?.close()
    source = null
    if (await redirectIfSecurityGateExpired()) return
    if (manuallyClosed || consumers <= 0) return
    clearRetryTimer()
    retryTimer = setTimeout(() => {
      connect()
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY)
    }, retryDelay)
  }
}

function disconnect() {
  manuallyClosed = true
  clearRetryTimer()
  flushTaskEventBatch()
  if (source) {
    source.close()
    source = null
  }
  connected.value = false
}

export function useRealtimeEvents() {
  function start() {
    consumers += 1
    connect()
  }

  function stop() {
    consumers = Math.max(0, consumers - 1)
    if (consumers <= 0) disconnect()
  }

  function subscribe(type, handler) {
    const key = String(type || '*')
    if (!subscribers.has(key)) subscribers.set(key, new Set())
    subscribers.get(key).add(handler)
    return () => {
      const set = subscribers.get(key)
      if (!set) return
      set.delete(handler)
      if (set.size === 0) subscribers.delete(key)
    }
  }

  return {
    connected: readonly(connected),
    lastEvent: readonly(lastEvent),
    lastEventAt: readonly(lastEventAt),
    lastErrorAt: readonly(lastErrorAt),
    start,
    stop,
    subscribe,
  }
}
