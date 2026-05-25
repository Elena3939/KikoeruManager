import { useSyncExternalStore } from 'react'
import { apiUrl, notificationApi } from '../../api'

const listeners = new Set()
const SSE_MAX_DELAY = 30000
const SSE_URL = apiUrl('/notifications/stream')
const SYNC_CHANNEL_NAME = 'kikoerumanager.notification.sync'
const SYNC_STORAGE_KEY = 'kikoerumanager:notification:sync'
const windowId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
const seenSyncIds = new Set()

let state = {
  unreadCount: 0,
  items: [],
  total: 0,
  loading: false,
  loadingMore: false,
  page: 1,
  pageSize: 20,
  panelOpen: false
}

let sse = null
let sseRetryTimer = null
let sseRetryDelay = 2000
let sseConsumers = 0
let syncChannel = null

function emit() {
  listeners.forEach(listener => listener())
}

function setState(patch) {
  state = { ...state, ...patch }
  emit()
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot() {
  return state
}

function rememberSyncId(id) {
  if (!id || seenSyncIds.has(id)) return false
  seenSyncIds.add(id)
  if (seenSyncIds.size > 80) {
    seenSyncIds.delete(seenSyncIds.values().next().value)
  }
  return true
}

function appendNotificationItem(item) {
  if (!item?.id || state.items.some(current => current.id === item.id)) return
  setState({ items: [item, ...state.items], total: state.total + 1 })
}

function broadcastSync(type, payload = {}) {
  if (typeof window === 'undefined') return
  const message = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    source: windowId,
    type,
    payload,
    at: Date.now()
  }

  try {
    syncChannel?.postMessage(message)
  } catch {}

  try {
    window.localStorage.setItem(SYNC_STORAGE_KEY, JSON.stringify(message))
  } catch {}
}

function applyCrossWindowSync(message) {
  if (!message || message.source === windowId || !rememberSyncId(message.id)) return
  const payload = message.payload || {}

  if (message.type === 'new') {
    if (typeof payload.unread_count === 'number') setState({ unreadCount: payload.unread_count })
    else fetchUnreadCount()
    if (state.panelOpen && payload.item) appendNotificationItem(payload.item)
    return
  }

  if (message.type === 'read') {
    const ids = Array.isArray(payload.ids) ? payload.ids : []
    if (ids.length) {
      setState({ items: state.items.map(item => ids.includes(item.id) ? { ...item, is_read: true } : item) })
    }
    fetchUnreadCount()
    return
  }

  if (message.type === 'read_all') {
    setState({ items: state.items.map(item => ({ ...item, is_read: true })), unreadCount: 0 })
    return
  }

  if (message.type === 'delete') {
    if (payload.id) {
      setState({ items: state.items.filter(item => item.id !== payload.id), total: Math.max(0, state.total - 1) })
    }
    fetchUnreadCount()
    return
  }

  fetchUnreadCount()
  if (state.panelOpen) fetchList()
}

function initCrossWindowSync() {
  if (typeof window === 'undefined') return
  if ('BroadcastChannel' in window && !syncChannel) {
    try {
      syncChannel = new BroadcastChannel(SYNC_CHANNEL_NAME)
      syncChannel.onmessage = event => applyCrossWindowSync(event.data)
    } catch {
      syncChannel = null
    }
  }
  window.addEventListener('storage', event => {
    if (event.key !== SYNC_STORAGE_KEY || !event.newValue) return
    try {
      applyCrossWindowSync(JSON.parse(event.newValue))
    } catch {}
  })
}

function connectSSE() {
  if (sse && sse.readyState !== EventSource.CLOSED) return
  sse = new EventSource(SSE_URL, { withCredentials: true })

  sse.onmessage = event => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'connected') {
        sseRetryDelay = 2000
        fetchUnreadCount()
        return
      }
      if (data.type === 'new_notification') {
        const unreadCount = data.unread_count ?? state.unreadCount + 1
        setState({ unreadCount })
        broadcastSync('new', { unread_count: unreadCount, item: data.item || null })
        window.dispatchEvent(new CustomEvent('kikoerumanager:notification:new', { detail: data.item || data }))
        if (state.panelOpen && data.item) appendNotificationItem(data.item)
        return
      }
      if (data.type === 'circle_owned_synced') {
        window.dispatchEvent(new CustomEvent('kikoerumanager:circle:owned-synced', { detail: data }))
      }
    } catch {}
  }

  sse.onerror = () => {
    sse?.close()
    sse = null
    if (sseRetryTimer) window.clearTimeout(sseRetryTimer)
    sseRetryTimer = window.setTimeout(() => {
      connectSSE()
      sseRetryDelay = Math.min(sseRetryDelay * 2, SSE_MAX_DELAY)
    }, sseRetryDelay)
  }
}

function disconnectSSE() {
  if (sseRetryTimer) {
    window.clearTimeout(sseRetryTimer)
    sseRetryTimer = null
  }
  sse?.close()
  sse = null
}

export async function fetchUnreadCount() {
  try {
    const data = await notificationApi.unreadCount()
    setState({ unreadCount: data.count ?? 0 })
  } catch {}
}

export async function fetchList(params = {}) {
  setState({ loading: true, page: 1 })
  try {
    const data = await notificationApi.list({ page: 1, limit: state.pageSize, ...params })
    setState({ items: data.items || [], total: data.total || 0, loading: false })
  } catch {
    setState({ loading: false })
  }
}

export async function loadMore() {
  if (state.loadingMore) return
  setState({ loadingMore: true })
  try {
    const nextPage = state.page + 1
    const data = await notificationApi.list({ page: nextPage, limit: state.pageSize })
    const nextItems = (data.items || []).filter(item => !state.items.some(current => current.id === item.id))
    setState({ items: [...state.items, ...nextItems], total: data.total || state.total, page: nextPage, loadingMore: false })
  } catch {
    setState({ loadingMore: false })
  }
}

export async function markRead(ids) {
  await notificationApi.markRead(ids)
  setState({ items: state.items.map(item => ids.includes(item.id) ? { ...item, is_read: true } : item) })
  await fetchUnreadCount()
  broadcastSync('read', { ids })
}

export async function markAllRead() {
  await notificationApi.markAllRead()
  setState({ items: state.items.map(item => ({ ...item, is_read: true })), unreadCount: 0 })
  broadcastSync('read_all')
}

export async function deleteItem(id) {
  await notificationApi.delete(id)
  setState({ items: state.items.filter(item => item.id !== id), total: Math.max(0, state.total - 1) })
  await fetchUnreadCount()
  broadcastSync('delete', { id })
}

export async function openPanel() {
  setState({ panelOpen: true })
  await fetchList()
  const unreadIds = state.items.filter(item => !item.is_read).map(item => item.id)
  if (unreadIds.length) {
    window.setTimeout(() => markRead(unreadIds), 420)
  }
}

export function closePanel() {
  setState({ panelOpen: false })
}

export function startSSE() {
  sseConsumers += 1
  connectSSE()
}

export function stopSSE() {
  sseConsumers = Math.max(0, sseConsumers - 1)
  if (sseConsumers === 0) disconnectSSE()
}

export function useNotificationState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

initCrossWindowSync()
