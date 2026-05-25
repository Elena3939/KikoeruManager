import { useSyncExternalStore } from 'react'

const DEFAULT_CANCEL_REASON = 'cancel'
const DEFAULT_CLOSE_REASON = 'cancel'
const listeners = new Set()

let state = {
  queue: [],
  current: null,
  sequence: 0
}

function emit() {
  listeners.forEach(listener => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot() {
  return state
}

function normalizeTone(tone) {
  if (tone === 'success' || tone === 'warning' || tone === 'danger') return tone
  return 'info'
}

function normalizeMode(mode) {
  if (mode === 'alert' || mode === 'prompt') return mode
  return 'confirm'
}

function normalizeDetails(details) {
  if (!Array.isArray(details)) return []
  return details
    .map(item => ({
      label: String(item?.label || '').trim(),
      value: item?.value === null || item?.value === undefined ? '' : String(item.value)
    }))
    .filter(item => item.label || item.value)
}

function normalizeOptions(mode, options = {}) {
  return {
    mode: normalizeMode(mode),
    title: String(options.title || '').trim(),
    message: String(options.message || '').trim(),
    description: String(options.description || '').trim(),
    badge: String(options.badge || '').trim(),
    tone: normalizeTone(options.tone),
    currentLabel: String(options.currentLabel || '').trim(),
    currentValue: options.currentValue === null || options.currentValue === undefined ? '' : String(options.currentValue),
    details: normalizeDetails(options.details),
    html: Boolean(options.html),
    confirmText: String(options.confirmText || (mode === 'alert' ? '知道了' : mode === 'prompt' ? '确认' : '确定')).trim(),
    cancelText: String(options.cancelText || '取消').trim(),
    closeOnClickModal: options.closeOnClickModal !== false,
    closeOnPressEscape: options.closeOnPressEscape !== false,
    showClose: options.showClose !== false,
    placeholder: String(options.placeholder || '').trim(),
    modelValue: options.modelValue === null || options.modelValue === undefined ? '' : String(options.modelValue),
    inputType: options.inputType === 'textarea' ? 'textarea' : (options.inputType || 'text'),
    width: Number(options.width) > 0 ? Number(options.width) : 420,
    validator: typeof options.validator === 'function' ? options.validator : null,
    confirmLoading: Boolean(options.confirmLoading),
    confirmDisabled: Boolean(options.confirmDisabled)
  }
}

function shouldSuppressAlert(mode, options = {}) {
  if (mode !== 'alert') return false
  const title = String(options.title || '').trim()
  const eventType = String(options.eventType || options.event_type || '').trim()
  return eventType === 'email_watcher_new_release' || title === '新作索引完成' || title === '新作索引失败'
}

function flushQueue() {
  if (state.current || !state.queue.length) return
  state = { ...state, current: state.queue[0], queue: state.queue.slice(1) }
  emit()
}

function enqueue(mode, options = {}) {
  if (shouldSuppressAlert(mode, options)) return Promise.resolve(null)
  return new Promise((resolve, reject) => {
    const sequence = state.sequence + 1
    const prompt = {
      id: `system-prompt-${sequence}`,
      options: normalizeOptions(mode, options),
      resolve,
      reject
    }
    state = { ...state, sequence, queue: [...state.queue, prompt] }
    flushQueue()
    emit()
  })
}

function settleCurrent(action, payload) {
  if (!state.current) return
  const current = state.current
  state = { ...state, current: null }
  if (action === 'resolve') current.resolve(payload)
  else current.reject(payload)
  emit()
  flushQueue()
}

export function showSystemConfirm(options = {}) {
  return enqueue('confirm', options)
}

export function showSystemAlert(options = {}) {
  return enqueue('alert', options)
}

export function showSystemPrompt(options = {}) {
  return enqueue('prompt', options)
}

export function resolveSystemPrompt(payload) {
  settleCurrent('resolve', payload)
}

export function rejectSystemPrompt(reason = DEFAULT_CANCEL_REASON) {
  settleCurrent('reject', reason)
}

export function useSystemPromptState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

export const systemPromptReasons = {
  cancel: DEFAULT_CANCEL_REASON,
  close: DEFAULT_CLOSE_REASON
}
