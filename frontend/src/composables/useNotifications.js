import { ref, computed } from 'vue'
import { apiUrl, notificationApi, redirectIfSecurityGateExpired } from '../api'

const _unreadCount = ref(0)
const _items = ref([])
const _total = ref(0)
const _loading = ref(false)
const _loadingMore = ref(false)
const _page = ref(1)
const _pageSize = 20
const _panelOpen = ref(false)

// SSE 状态（模块级单例，避免多组件重复连接）
let _sse = null
let _sseRetryTimer = null
let _sseRetryDelay = 2000
const SSE_MAX_DELAY = 30000
const SSE_URL = apiUrl('/notifications/stream')
const SYNC_CHANNEL_NAME = 'kikoerumanager.notification.sync'
const SYNC_STORAGE_KEY = 'kikoerumanager:notification:sync'
const _windowId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
const _seenSyncIds = new Set()
let _syncChannel = null
let _sseConsumers = 0

function _rememberSyncId(id) {
  if (!id) return false
  if (_seenSyncIds.has(id)) return false
  _seenSyncIds.add(id)
  if (_seenSyncIds.size > 80) {
    const first = _seenSyncIds.values().next().value
    _seenSyncIds.delete(first)
  }
  return true
}

function _appendNotificationItem(item) {
  if (!item?.id) return
  const exists = _items.value.some(i => i.id === item.id)
  if (!exists) {
    _items.value = [item, ..._items.value]
    _total.value += 1
  }
}

function _broadcastSync(type, payload = {}) {
  if (typeof window === 'undefined') return
  const message = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    source: _windowId,
    type,
    payload,
    at: Date.now(),
  }

  try {
    _syncChannel?.postMessage(message)
  } catch { /* ignore */ }

  try {
    window.localStorage.setItem(SYNC_STORAGE_KEY, JSON.stringify(message))
  } catch { /* ignore */ }
}

function _applyCrossWindowSync(message) {
  if (!message || message.source === _windowId || !_rememberSyncId(message.id)) return
  const payload = message.payload || {}

  if (message.type === 'new') {
    if (typeof payload.unread_count === 'number') {
      _unreadCount.value = payload.unread_count
    } else {
      fetchUnreadCount()
    }
    if (_panelOpen.value && payload.item) {
      _appendNotificationItem(payload.item)
    }
    return
  }

  if (message.type === 'read') {
    const ids = Array.isArray(payload.ids) ? payload.ids : []
    if (ids.length > 0) {
      _items.value = _items.value.map(item =>
        ids.includes(item.id) ? { ...item, is_read: true } : item
      )
    }
    fetchUnreadCount()
    return
  }

  if (message.type === 'read_all') {
    _items.value = _items.value.map(item => ({ ...item, is_read: true }))
    _unreadCount.value = 0
    return
  }

  if (message.type === 'delete') {
    const id = payload.id
    if (id) {
      _items.value = _items.value.filter(item => item.id !== id)
      _total.value = Math.max(0, _total.value - 1)
    }
    fetchUnreadCount()
    return
  }

  fetchUnreadCount()
  if (_panelOpen.value) {
    fetchList()
  }
}

function _initCrossWindowSync() {
  if (typeof window === 'undefined') return

  if ('BroadcastChannel' in window && !_syncChannel) {
    try {
      _syncChannel = new BroadcastChannel(SYNC_CHANNEL_NAME)
      _syncChannel.onmessage = (event) => _applyCrossWindowSync(event.data)
    } catch {
      _syncChannel = null
    }
  }

  window.addEventListener('storage', (event) => {
    if (event.key !== SYNC_STORAGE_KEY || !event.newValue) return
    try {
      _applyCrossWindowSync(JSON.parse(event.newValue))
    } catch { /* ignore */ }
  })
}

_initCrossWindowSync()

// ─────────────────────────────────────────────
// SSE 连接管理
// ─────────────────────────────────────────────
function _connectSSE() {
  if (_sse && _sse.readyState !== EventSource.CLOSED) return

  _sse = new EventSource(SSE_URL, { withCredentials: true })

  _sse.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'connected') {
        _sseRetryDelay = 2000  // 连接成功，重置退避
        fetchUnreadCount()     // 拉一次当前未读数（初始同步）
        return
      }
      if (data.type === 'new_notification') {
        _unreadCount.value = data.unread_count ?? (_unreadCount.value + 1)
        _broadcastSync('new', {
          unread_count: _unreadCount.value,
          item: data.item || null,
        })
        window.dispatchEvent(new CustomEvent('kikoerumanager:notification:new', { detail: data.item || data }))
        if (_panelOpen.value) {
          // 面板打开中，实时追加到列表顶部
          if (data.item) {
            _appendNotificationItem(data.item)
          }
        }
        return
      }
      // 数据变更类信号事件：不进通知中心，只透传给关心它的页面/组件。
      // - circle_owned_synced：某 RJ 已成功入库并写入 LibraryOwnedWork，前端 CircleCompletion 收到后可秒级刷新对应社团。
      //   payload: { type, rjcode, canonicals: string[], circle_ids: string[] }
      if (data.type === 'circle_owned_synced') {
        window.dispatchEvent(new CustomEvent('kikoerumanager:circle:owned-synced', { detail: data }))
        return
      }
      if (data.type === 'circle_subtitle_synced') {
        window.dispatchEvent(new CustomEvent('kikoerumanager:circle:subtitle-synced', { detail: data }))
        return
      }
    } catch { /* ignore */ }
  }

  _sse.onerror = async () => {
    _sse?.close()
    _sse = null
    if (await redirectIfSecurityGateExpired()) return
    if (_sseRetryTimer) clearTimeout(_sseRetryTimer)
    _sseRetryTimer = setTimeout(() => {
      _connectSSE()
      _sseRetryDelay = Math.min(_sseRetryDelay * 2, SSE_MAX_DELAY)
    }, _sseRetryDelay)
  }
}

function _disconnectSSE() {
  if (_sseRetryTimer) {
    clearTimeout(_sseRetryTimer)
    _sseRetryTimer = null
  }
  if (_sse) {
    _sse.close()
    _sse = null
  }
}

// ─────────────────────────────────────────────
// 公共操作
// ─────────────────────────────────────────────
async function fetchUnreadCount() {
  try {
    const data = await notificationApi.unreadCount()
    _unreadCount.value = data.count ?? 0
  } catch { /* 静默失败 */ }
}

async function fetchList(params = {}) {
  _loading.value = true
  _page.value = 1
  try {
    const data = await notificationApi.list({ page: 1, limit: _pageSize, ...params })
    _items.value = data.items || []
    _total.value = data.total || 0
  } catch {
  } finally {
    _loading.value = false
  }
}

async function loadMore() {
  if (_loadingMore.value) return
  _loadingMore.value = true
  try {
    const nextPage = _page.value + 1
    const data = await notificationApi.list({ page: nextPage, limit: _pageSize })
    const newItems = (data.items || []).filter(ni => !_items.value.some(i => i.id === ni.id))
    _items.value = [..._items.value, ...newItems]
    _total.value = data.total || _total.value
    _page.value = nextPage
  } catch {
  } finally {
    _loadingMore.value = false
  }
}

async function markRead(ids) {
  await notificationApi.markRead(ids)
  _items.value = _items.value.map(item =>
    ids.includes(item.id) ? { ...item, is_read: true } : item
  )
  await fetchUnreadCount()
  _broadcastSync('read', { ids })
}

async function markAllRead() {
  await notificationApi.markAllRead()
  _items.value = _items.value.map(item => ({ ...item, is_read: true }))
  _unreadCount.value = 0
  _broadcastSync('read_all')
}

async function deleteItem(id) {
  await notificationApi.delete(id)
  _items.value = _items.value.filter(item => item.id !== id)
  _total.value = Math.max(0, _total.value - 1)
  await fetchUnreadCount()
  _broadcastSync('delete', { id })
}

// ─────────────────────────────────────────────
// Composable 导出
// ─────────────────────────────────────────────
export function useNotifications() {
  const unreadCount = computed(() => _unreadCount.value)
  const loading = computed(() => _loading.value)
  const loadingMore = computed(() => _loadingMore.value)
  const hasMore = computed(() => _items.value.length < _total.value)
  const panelOpen = computed({
    get: () => _panelOpen.value,
    set: (v) => { _panelOpen.value = v },
  })

  async function openPanel() {
    _panelOpen.value = true
    await fetchList()
    const unreadIds = _items.value.filter(i => !i.is_read).map(i => i.id)
    if (unreadIds.length > 0) {
      // 延迟 420ms 标已读，让用户先看到未读状态，再触发 CSS 渐变灰过渡
      setTimeout(async () => {
        await markRead(unreadIds)
      }, 420)
    }
  }

  function closePanel() {
    _panelOpen.value = false
  }

  function startSSE() {
    _sseConsumers += 1
    _connectSSE()
  }

  function stopSSE() {
    _sseConsumers = Math.max(0, _sseConsumers - 1)
    if (_sseConsumers === 0) {
      _disconnectSSE()
    }
  }

  return {
    unreadCount,
    items: _items,
    total: _total,
    loading,
    loadingMore,
    hasMore,
    panelOpen,
    fetchUnreadCount,
    fetchList,
    loadMore,
    markRead,
    markAllRead,
    deleteItem,
    openPanel,
    closePanel,
    startSSE,
    stopSSE,
  }
}
