import { readonly, ref } from 'vue'
import { apiUrl } from '../api'

const STREAM_URL = apiUrl('/events/stream')
const MAX_RETRY_DELAY = 30000

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

function clearRetryTimer() {
  if (!retryTimer) return
  clearTimeout(retryTimer)
  retryTimer = null
}

function emitDomEvent(name, detail) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(name, { detail }))
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

function handleMessage(messageEvent) {
  try {
    const event = JSON.parse(messageEvent.data)
    lastEvent.value = event
    lastEventAt.value = Date.now()
    if (event.type === 'connected') {
      connected.value = true
      retryDelay = 2000
    }
    emitDomEvent('kikoerumanager:events:message', event)
    dispatchCompatibilityEvent(event)
    notifySubscribers(event)
  } catch {
    // 跳过无法解析的事件，SSE 连接继续保留。
  }
}

function connect() {
  if (typeof window === 'undefined') return
  if (source && source.readyState !== EventSource.CLOSED) return

  manuallyClosed = false
  clearRetryTimer()
  source = new EventSource(STREAM_URL, { withCredentials: true })
  source.onmessage = handleMessage
  source.onerror = () => {
    connected.value = false
    lastErrorAt.value = Date.now()
    source?.close()
    source = null
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
