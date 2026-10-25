import { computed, onActivated, onMounted, onUnmounted, ref } from 'vue'
import { scanApi } from '../api'
import { useRealtimeEvents } from './useRealtimeEvents'

const terminal = new Set(['completed', 'cancelled', 'failed', 'interrupted'])

export function useInputScan() {
  const snapshot = ref(null)
  const starting = ref(false)
  const realtime = useRealtimeEvents()
  const scanning = computed(() => starting.value || Boolean(
    snapshot.value && !terminal.has(snapshot.value.status)
  ))
  let disposed = false
  let timer = null
  let unsubscribe = null
  let lastUpdate = 0
  let requestKey = null
  let reconnecting = null

  function apply(value) {
    if (disposed || !value?.scan_id) return
    const current = snapshot.value
    if (current?.scan_id === value.scan_id && Number(current.revision) > Number(value.revision)) return
    if (current?.scan_id !== value.scan_id && current?.created_at > value.created_at) return
    snapshot.value = value
    lastUpdate = Date.now()
  }

  function reconnect() {
    if (disposed) return Promise.resolve()
    if (reconnecting) return reconnecting
    reconnecting = scanApi.latest()
      .then(apply)
      .catch(error => console.warn('接回扫描状态失败:', error))
      .finally(() => { reconnecting = null })
    return reconnecting
  }

  async function poll() {
    try {
      if (!snapshot.value) {
        await reconnect()
      } else if (scanning.value && (
        !realtime.connected.value || Date.now() - lastUpdate > 6000
      )) {
        apply(await scanApi.status(snapshot.value.scan_id))
      }
    } catch (error) {
      console.warn('查询扫描状态失败:', error)
    } finally {
      if (!disposed) timer = setTimeout(poll, 3000)
    }
  }

  async function start() {
    if (scanning.value) return snapshot.value
    starting.value = true
    // 请求失败后保留幂等键，网络重试不会创建第二批。
    requestKey ||= globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
    try {
      const value = await scanApi.scan(requestKey)
      apply(value)
      requestKey = null
      return value
    } finally {
      starting.value = false
    }
  }

  async function cancel() {
    if (snapshot.value) apply(await scanApi.cancel(snapshot.value.scan_id))
  }

  onMounted(() => {
    realtime.start()
    unsubscribe = realtime.subscribe('input.scan.changed', event => apply(event.payload))
    reconnect()
    timer = setTimeout(poll, 3000)
  })
  onActivated(reconnect)
  onUnmounted(() => {
    disposed = true
    clearTimeout(timer)
    unsubscribe?.()
    realtime.stop()
  })
  return { snapshot, scanning, start, cancel, reconnect }
}
