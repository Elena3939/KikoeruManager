import { computed, readonly, shallowReactive } from 'vue'

const DEFAULT_CANCEL_REASON = 'cancel'
const DEFAULT_CLOSE_REASON = 'cancel'

const state = shallowReactive({
  queue: [],
  current: null,
  sequence: 0
})

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
    confirmText: String(
      options.confirmText ||
        (mode === 'alert' ? '知道了' : mode === 'prompt' ? '确认' : '确定')
    ).trim(),
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

function flushQueue() {
  if (state.current || !state.queue.length) return
  state.current = state.queue.shift() || null
}

function enqueue(mode, options = {}) {
  return new Promise((resolve, reject) => {
    state.sequence += 1
    state.queue.push({
      id: `system-prompt-${state.sequence}`,
      options: normalizeOptions(mode, options),
      resolve,
      reject
    })
    flushQueue()
  })
}

function settleCurrent(action, payload) {
  if (!state.current) return
  const current = state.current
  state.current = null
  if (action === 'resolve') current.resolve(payload)
  else current.reject(payload)
  flushQueue()
}

export function resolveSystemPrompt(payload) {
  settleCurrent('resolve', payload)
}

export function rejectSystemPrompt(reason = DEFAULT_CANCEL_REASON) {
  settleCurrent('reject', reason)
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

export function useSystemPromptHost() {
  return {
    state: readonly(state),
    currentPrompt: computed(() => state.current),
    hasPrompt: computed(() => Boolean(state.current)),
    resolveSystemPrompt,
    rejectSystemPrompt,
    cancelReason: DEFAULT_CANCEL_REASON,
    closeReason: DEFAULT_CLOSE_REASON
  }
}
