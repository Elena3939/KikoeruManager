import { ref, computed } from 'vue'
import { notificationApi } from '../api'

const _unreadCount = ref(0)
const _items = ref([])
const _total = ref(0)
const _loading = ref(false)
const _panelOpen = ref(false)

// SSE 状态（模块级单例，避免多组件重复连接）
let _sse = null
let _sseRetryTimer = null
let _sseRetryDelay = 2000
const SSE_MAX_DELAY = 30000
const SSE_URL = '/api/notifications/stream'

// ─────────────────────────────────────────────
// SSE 连接管理
// ─────────────────────────────────────────────
function _connectSSE() {
  if (_sse && _sse.readyState !== EventSource.CLOSED) return

  _sse = new EventSource(SSE_URL)

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
        if (_panelOpen.value) {
          // 面板打开中，实时追加到列表顶部
          if (data.item) {
            const exists = _items.value.some(i => i.id === data.item.id)
            if (!exists) {
              _items.value = [data.item, ..._items.value]
              _total.value += 1
            }
          }
        }
      }
    } catch { /* ignore */ }
  }

  _sse.onerror = () => {
    _sse?.close()
    _sse = null
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
  try {
    const data = await notificationApi.list({ page: 1, limit: 50, ...params })
    _items.value = data.items || []
    _total.value = data.total || 0
  } catch {
  } finally {
    _loading.value = false
  }
}

async function markRead(ids) {
  await notificationApi.markRead(ids)
  _items.value = _items.value.map(item =>
    ids.includes(item.id) ? { ...item, is_read: true } : item
  )
  await fetchUnreadCount()
}

async function markAllRead() {
  await notificationApi.markAllRead()
  _items.value = _items.value.map(item => ({ ...item, is_read: true }))
  _unreadCount.value = 0
}

async function deleteItem(id) {
  await notificationApi.delete(id)
  _items.value = _items.value.filter(item => item.id !== id)
  _total.value = Math.max(0, _total.value - 1)
  await fetchUnreadCount()
}

// ─────────────────────────────────────────────
// Composable 导出
// ─────────────────────────────────────────────
export function useNotifications() {
  const unreadCount = computed(() => _unreadCount.value)
  const loading = computed(() => _loading.value)
  const panelOpen = computed({
    get: () => _panelOpen.value,
    set: (v) => { _panelOpen.value = v },
  })

  async function openPanel() {
    _panelOpen.value = true
    await fetchList()
    const unreadIds = _items.value.filter(i => !i.is_read).map(i => i.id)
    if (unreadIds.length > 0) {
      await markRead(unreadIds)
    }
  }

  function closePanel() {
    _panelOpen.value = false
  }

  function startSSE() {
    _connectSSE()
  }

  function stopSSE() {
    _disconnectSSE()
  }

  return {
    unreadCount,
    items: _items,
    total: _total,
    loading,
    panelOpen,
    fetchUnreadCount,
    fetchList,
    markRead,
    markAllRead,
    deleteItem,
    openPanel,
    closePanel,
    startSSE,
    stopSSE,
  }
}
