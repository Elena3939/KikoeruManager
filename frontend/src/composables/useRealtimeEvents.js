import { readonly, ref } from 'vue'
import { apiUrl, redirectIfSecurityGateExpired } from '../api'

const STREAM_URL = apiUrl('/events/stream')
const MAX_RETRY_DELAY = 30000
const TASK_EVENT_BATCH_WINDOW_MS = 80
const TASK_EVENT_NAVIGATION_BATCH_WINDOW_MS = 260
const NAVIGATION_GRACE_MS = 420
const SYNC_CHANNEL_NAME = 'kikoerumanager.realtime.sync'
const SYNC_STORAGE_KEY = 'kikoerumanager:realtime:sync'
const LEADER_STORAGE_KEY = 'kikoerumanager:realtime:leader'
const LEADER_TTL_MS = 10000
const LEADER_HEARTBEAT_MS = 3000
const LEADER_ELECTION_MS = 1200

const connected = ref(false)
const lastEvent = ref(null)
const lastEventAt = ref(0)
const lastErrorAt = ref(0)

let source = null
let retryTimer = null
let leaderHeartbeatTimer = null
let leaderElectionTimer = null
let retryDelay = 2000
let consumers = 0
let manuallyClosed = false
let isLeader = false
let syncChannel = null
let crossTabBound = false
const windowId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
const seenSyncIds = new Set()

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

function clearLeaderHeartbeatTimer() {
  if (!leaderHeartbeatTimer) return
  clearInterval(leaderHeartbeatTimer)
  leaderHeartbeatTimer = null
}

function clearLeaderElectionTimer() {
  if (!leaderElectionTimer) return
  clearTimeout(leaderElectionTimer)
  leaderElectionTimer = null
}

function emitDomEvent(name, detail) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

function rememberSyncId(id) {
  if (!id) return false
  if (seenSyncIds.has(id)) return false
  seenSyncIds.add(id)
  if (seenSyncIds.size > 200) {
    const first = seenSyncIds.values().next().value
    seenSyncIds.delete(first)
  }
  return true
}

function readLeaderLease() {
  if (typeof window === 'undefined') return null
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LEADER_STORAGE_KEY) || 'null')
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

function writeLeaderLease() {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(LEADER_STORAGE_KEY, JSON.stringify({
      id: windowId,
      expiresAt: Date.now() + LEADER_TTL_MS,
      connected: Boolean(connected.value),
    }))
  } catch { /* ignore */ }
}

function claimLeaderLease() {
  if (typeof window === 'undefined') return false
  const lease = readLeaderLease()
  if (lease?.id && lease.id !== windowId && Number(lease.expiresAt || 0) > Date.now()) {
    return false
  }
  writeLeaderLease()
  const confirmed = readLeaderLease()
  return confirmed?.id === windowId
}

function removeOwnLeaderLease() {
  if (typeof window === 'undefined') return
  const lease = readLeaderLease()
  if (lease?.id !== windowId) return
  try {
    window.localStorage.removeItem(LEADER_STORAGE_KEY)
  } catch { /* ignore */ }
}

function hasActiveOtherLeader() {
  const lease = readLeaderLease()
  return Boolean(lease?.id && lease.id !== windowId && Number(lease.expiresAt || 0) > Date.now())
}

function syncConnectedFromLeaderLease() {
  const lease = readLeaderLease()
  if (lease?.id && lease.id !== windowId && Number(lease.expiresAt || 0) > Date.now()) {
    connected.value = Boolean(lease.connected)
  }
  return lease
}

function broadcastSync(type, payload = {}) {
  if (typeof window === 'undefined') return
  const message = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    source: windowId,
    type,
    payload,
    at: Date.now(),
  }
  rememberSyncId(message.id)
  try {
    syncChannel?.postMessage(message)
  } catch { /* ignore */ }
  try {
    window.localStorage.setItem(SYNC_STORAGE_KEY, JSON.stringify(message))
  } catch { /* ignore */ }
}

function applyCrossTabMessage(message) {
  if (!message || message.source === windowId || !rememberSyncId(message.id)) return
  if (message.type === 'event') {
    dispatchIncomingEvent(message.payload?.event, { rebroadcast: false })
    return
  }
  if (message.type === 'connected') {
    connected.value = Boolean(message.payload?.connected)
    return
  }
  if (message.type === 'leader_changed') {
    const lease = syncConnectedFromLeaderLease()
    if (lease?.id && lease.id !== windowId) {
      connected.value = Boolean(lease.connected)
    }
    scheduleLeaderElection()
  }
}

function bindCrossTabSync() {
  if (crossTabBound || typeof window === 'undefined') return
  crossTabBound = true
  if ('BroadcastChannel' in window && !syncChannel) {
    try {
      syncChannel = new BroadcastChannel(SYNC_CHANNEL_NAME)
      syncChannel.onmessage = (event) => applyCrossTabMessage(event.data)
    } catch {
      syncChannel = null
    }
  }
  window.addEventListener('storage', (event) => {
    if (event.key === SYNC_STORAGE_KEY && event.newValue) {
      try {
        applyCrossTabMessage(JSON.parse(event.newValue))
      } catch { /* ignore */ }
      return
    }
    if (event.key === LEADER_STORAGE_KEY) {
      const lease = readLeaderLease()
      if (
        isLeader
        && lease?.id
        && lease.id !== windowId
        && Number(lease.expiresAt || 0) > Date.now()
      ) {
        resignLeader()
        return
      }
      scheduleLeaderElection()
    }
  })
  window.addEventListener('beforeunload', () => {
    if (isLeader) {
      removeOwnLeaderLease()
      broadcastSync('leader_changed')
    }
  })
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
    return
  }
  if (event?.type === 'circle.subtitle.synced') {
    emitDomEvent('kikoerumanager:circle:subtitle-synced', payload)
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

function dispatchIncomingEvent(event, options = {}) {
  const { rebroadcast = false } = options
  if (!event || typeof event !== 'object') return
  lastEvent.value = event
  lastEventAt.value = Date.now()
  if (event.type === 'connected') {
    connected.value = true
    retryDelay = 2000
    if (isLeader) {
      writeLeaderLease()
      broadcastSync('connected', { connected: true })
    }
  }
  if (rebroadcast) {
    broadcastSync('event', { event })
  }
  if (event.type === 'task.center.changed') {
    scheduleTaskEventBatch(event)
    return
  }
  dispatchEventNow(event)
}

function handleMessage(messageEvent) {
  try {
    const event = JSON.parse(messageEvent.data)
    dispatchIncomingEvent(event, { rebroadcast: true })
  } catch {
    // 跳过无法解析的事件，SSE 连接继续保留。
  }
}

function connect() {
  if (typeof window === 'undefined') return
  if (!isLeader) return
  if (source && source.readyState !== EventSource.CLOSED) return

  bindRouteNavigationListeners()
  manuallyClosed = false
  clearRetryTimer()
  source = new EventSource(STREAM_URL, { withCredentials: true })
  source.onmessage = handleMessage
  source.onerror = async () => {
    connected.value = false
    if (isLeader) {
      writeLeaderLease()
      broadcastSync('connected', { connected: false })
    }
    lastErrorAt.value = Date.now()
    source?.close()
    source = null
    if (await redirectIfSecurityGateExpired()) return
    if (manuallyClosed || consumers <= 0) return
    if (!isLeader) return
    clearRetryTimer()
    retryTimer = setTimeout(() => {
      connect()
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY)
    }, retryDelay)
  }
}

function disconnectSource(options = {}) {
  const { manual = false } = options
  if (manual) manuallyClosed = true
  clearRetryTimer()
  flushTaskEventBatch()
  if (source) {
    source.close()
    source = null
  }
  connected.value = false
  broadcastSync('connected', { connected: false })
}

function becomeLeader() {
  if (isLeader) {
    writeLeaderLease()
    return
  }
  if (!claimLeaderLease()) {
    scheduleLeaderElection()
    return
  }
  isLeader = true
  broadcastSync('leader_changed')
  clearLeaderHeartbeatTimer()
  leaderHeartbeatTimer = setInterval(() => {
    if (!isLeader || consumers <= 0) return
    const lease = readLeaderLease()
    if (lease?.id && lease.id !== windowId && Number(lease.expiresAt || 0) > Date.now()) {
      resignLeader()
      return
    }
    writeLeaderLease()
  }, LEADER_HEARTBEAT_MS)
  connect()
}

function resignLeader() {
  if (!isLeader) return
  isLeader = false
  clearLeaderHeartbeatTimer()
  removeOwnLeaderLease()
  disconnectSource()
  broadcastSync('leader_changed')
  if (consumers > 0 && !manuallyClosed) scheduleLeaderElection()
}

function scheduleLeaderElection(delay = LEADER_ELECTION_MS) {
  clearLeaderElectionTimer()
  if (typeof window === 'undefined' || consumers <= 0 || manuallyClosed) return
  leaderElectionTimer = setTimeout(() => {
    leaderElectionTimer = null
    if (consumers <= 0 || manuallyClosed) return
    if (isLeader) {
      writeLeaderLease()
      connect()
      return
    }
    const lease = syncConnectedFromLeaderLease()
    if (lease?.id && lease.id !== windowId && Number(lease.expiresAt || 0) > Date.now()) {
      scheduleLeaderElection(Math.max(500, Number(lease.expiresAt || 0) - Date.now() + 250))
      return
    }
    becomeLeader()
  }, delay)
}

function disconnect() {
  clearLeaderElectionTimer()
  manuallyClosed = true
  resignLeader()
  disconnectSource({ manual: true })
  connected.value = false
}

export function useRealtimeEvents() {
  function start() {
    consumers += 1
    bindCrossTabSync()
    manuallyClosed = false
    if (isLeader) {
      writeLeaderLease()
      connect()
      return
    }
    if (!hasActiveOtherLeader()) {
      becomeLeader()
      return
    }
    syncConnectedFromLeaderLease()
    scheduleLeaderElection()
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
