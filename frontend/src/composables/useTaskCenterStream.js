import { readonly, ref } from 'vue'
import { apiUrl } from '../api'

const STREAM_URL = apiUrl('/task-center/stream')
const MAX_RETRY_DELAY = 30000

const connected = ref(false)
const lastEvent = ref(null)
const lastErrorAt = ref(0)

let source = null
let retryTimer = null
let retryDelay = 2000
let consumers = 0
let manuallyClosed = false

function dispatchTaskCenterEvent(payload) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('kikoerumanager:task-center:changed', { detail: payload }))
}

function clearRetryTimer() {
  if (!retryTimer) return
  clearTimeout(retryTimer)
  retryTimer = null
}

function connect() {
  if (typeof window === 'undefined') return
  if (source && source.readyState !== EventSource.CLOSED) return

  manuallyClosed = false
  clearRetryTimer()
  source = new EventSource(STREAM_URL, { withCredentials: true })

  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      lastEvent.value = payload
      if (payload.type === 'connected') {
        connected.value = true
        retryDelay = 2000
      }
      dispatchTaskCenterEvent(payload)
    } catch {
      // 跳过无法解析的事件，SSE 连接本身继续保留。
    }
  }

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

export function useTaskCenterStream() {
  function start() {
    consumers += 1
    connect()
  }

  function stop() {
    consumers = Math.max(0, consumers - 1)
    if (consumers <= 0) disconnect()
  }

  return {
    connected: readonly(connected),
    lastEvent: readonly(lastEvent),
    lastErrorAt: readonly(lastErrorAt),
    start,
    stop,
  }
}
