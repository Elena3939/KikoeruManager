import { computed, reactive } from 'vue'

const STORAGE_KEY = 'kikoerumanager.ui.backgroundWorkbenches'

const definitions = reactive({})
const runtimeMap = reactive({})

function loadPersistedSnapshots() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return raw && typeof raw === 'object' ? raw : {}
  } catch (_) {
    return {}
  }
}

const persistedSnapshots = loadPersistedSnapshots()

function createDefaultRuntime(id, definition = {}) {
  return {
    id,
    type: definition.type || 'generic',
    title: definition.title || '',
    visible: false,
    backgroundActive: false,
    cardVisible: false,
    dismissed: false,
    closable: definition.closable !== false,
    priority: Number(definition.priority || 0),
    summary: {
      subtitle: '',
      text: ''
    },
    metrics: [],
    progress: {
      percentage: 0,
      status: '',
      label: ''
    },
    status: {
      key: 'idle',
      label: '空闲',
      tone: 'neutral'
    },
    actions: Array.isArray(definition.actions) && definition.actions.length
      ? [...definition.actions]
      : ['resume', 'close'],
    payload: {},
    restorable: false,
    updatedAt: Date.now()
  }
}

function cloneMetrics(metrics = []) {
  return Array.isArray(metrics)
    ? metrics
      .filter(Boolean)
      .map(item => ({
        key: String(item.key || item.label || ''),
        label: String(item.label || ''),
        value: item.value ?? '',
        tone: String(item.tone || 'neutral')
      }))
      .filter(item => item.label || item.value !== '')
    : []
}

function mergeRuntime(target, patch = {}) {
  if (!patch || typeof patch !== 'object') return target

  if (Object.prototype.hasOwnProperty.call(patch, 'type')) target.type = String(patch.type || target.type || '')
  if (Object.prototype.hasOwnProperty.call(patch, 'title')) target.title = String(patch.title || '')
  if (Object.prototype.hasOwnProperty.call(patch, 'visible')) target.visible = Boolean(patch.visible)
  if (Object.prototype.hasOwnProperty.call(patch, 'backgroundActive')) target.backgroundActive = Boolean(patch.backgroundActive)
  if (Object.prototype.hasOwnProperty.call(patch, 'cardVisible')) target.cardVisible = Boolean(patch.cardVisible)
  if (Object.prototype.hasOwnProperty.call(patch, 'dismissed')) target.dismissed = Boolean(patch.dismissed)
  if (Object.prototype.hasOwnProperty.call(patch, 'closable')) target.closable = Boolean(patch.closable)
  if (Object.prototype.hasOwnProperty.call(patch, 'priority')) target.priority = Number(patch.priority || 0)
  if (Object.prototype.hasOwnProperty.call(patch, 'restorable')) target.restorable = Boolean(patch.restorable)
  if (Object.prototype.hasOwnProperty.call(patch, 'summary')) {
    const next = patch.summary && typeof patch.summary === 'object' ? patch.summary : {}
    target.summary = {
      subtitle: String(next.subtitle || ''),
      text: String(next.text || '')
    }
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'metrics')) {
    target.metrics = cloneMetrics(patch.metrics)
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'progress')) {
    const next = patch.progress && typeof patch.progress === 'object' ? patch.progress : {}
    target.progress = {
      percentage: Math.max(0, Math.min(100, Number(next.percentage || 0))),
      status: String(next.status || ''),
      label: String(next.label || '')
    }
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'status')) {
    const next = patch.status && typeof patch.status === 'object' ? patch.status : {}
    target.status = {
      key: String(next.key || 'idle'),
      label: String(next.label || '空闲'),
      tone: String(next.tone || 'neutral')
    }
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'actions')) {
    target.actions = Array.isArray(patch.actions) ? patch.actions.filter(Boolean).map(item => String(item)) : []
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'payload')) {
    const nextPayload = patch.payload && typeof patch.payload === 'object' ? patch.payload : {}
    target.payload = {
      ...target.payload,
      ...nextPayload
    }
  }
  target.updatedAt = Date.now()
  return target
}

function persistRuntimeMap() {
  try {
    const snapshots = {}
    Object.values(runtimeMap).forEach((runtime) => {
      const shouldPersist = runtime.restorable || runtime.visible || runtime.backgroundActive || runtime.cardVisible
      if (!shouldPersist) return
      snapshots[runtime.id] = {
        id: runtime.id,
        type: runtime.type,
        title: runtime.title,
        visible: runtime.visible,
        backgroundActive: runtime.backgroundActive,
        cardVisible: runtime.cardVisible,
        dismissed: runtime.dismissed,
        closable: runtime.closable,
        priority: runtime.priority,
        summary: runtime.summary,
        metrics: runtime.metrics,
        progress: runtime.progress,
        status: runtime.status,
        actions: runtime.actions,
        payload: runtime.payload,
        restorable: runtime.restorable,
        updatedAt: runtime.updatedAt
      }
    })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshots))
  } catch (_) {}
}

function ensureWorkbench(id) {
  const normalizedId = String(id || '').trim()
  if (!normalizedId) return null
  if (!runtimeMap[normalizedId]) {
    const definition = definitions[normalizedId] || {}
    const runtime = reactive(createDefaultRuntime(normalizedId, definition))
    const persisted = persistedSnapshots[normalizedId]
    if (persisted && typeof persisted === 'object') {
      mergeRuntime(runtime, persisted)
    }
    runtimeMap[normalizedId] = runtime
  }
  return runtimeMap[normalizedId]
}

function resetWorkbenchRuntime(runtime, definition = {}) {
  const next = createDefaultRuntime(runtime.id, definition)
  Object.keys(runtime).forEach((key) => {
    delete runtime[key]
  })
  Object.assign(runtime, next)
}

function getDefinition(id) {
  return definitions[String(id || '').trim()] || {}
}

function invokeDefinitionAction(id, action) {
  const definition = getDefinition(id)
  const runtime = ensureWorkbench(id)
  if (!runtime) return
  if (typeof definition.onAction === 'function') {
    definition.onAction(action, runtime, managerApi)
  }
}

function registerWorkbench(definition = {}) {
  const id = String(definition.id || '').trim()
  if (!id) return null
  definitions[id] = {
    ...definitions[id],
    ...definition,
    id
  }
  const runtime = ensureWorkbench(id)
  mergeRuntime(runtime, {
    type: definition.type || runtime.type,
    title: definition.title || runtime.title,
    closable: definition.closable ?? runtime.closable,
    priority: definition.priority ?? runtime.priority,
    actions: Array.isArray(definition.actions) && definition.actions.length ? definition.actions : runtime.actions
  })
  persistRuntimeMap()
  return runtime
}

function patchWorkbenchState(id, partial = {}) {
  const runtime = ensureWorkbench(id)
  if (!runtime) return null
  mergeRuntime(runtime, partial)
  persistRuntimeMap()
  return runtime
}

function openWorkbench(id, payload = null) {
  const runtime = ensureWorkbench(id)
  if (!runtime) return null
  const nextPatch = {
    visible: true,
    backgroundActive: false,
    cardVisible: false,
    dismissed: false,
    restorable: true
  }
  if (payload && typeof payload === 'object') {
    nextPatch.payload = payload
  }
  patchWorkbenchState(id, nextPatch)
  return runtime
}

function backgroundWorkbench(id) {
  return patchWorkbenchState(id, {
    visible: false,
    backgroundActive: true,
    cardVisible: true,
    dismissed: false,
    restorable: true
  })
}

function resumeWorkbench(id) {
  return patchWorkbenchState(id, {
    visible: true,
    backgroundActive: false,
    cardVisible: false,
    dismissed: false,
    restorable: true
  })
}

function dismissWorkbench(id) {
  return patchWorkbenchState(id, {
    cardVisible: false,
    dismissed: true,
    visible: false
  })
}

function closeWorkbench(id) {
  const runtime = ensureWorkbench(id)
  if (!runtime) return
  const definition = getDefinition(id)
  if (typeof definition.onClose === 'function') {
    definition.onClose(runtime, managerApi)
  }
  if (definition.retainSnapshotOnClose) {
    patchWorkbenchState(id, {
      visible: false,
      backgroundActive: false,
      cardVisible: false,
      dismissed: false
    })
    return
  }
  resetWorkbenchRuntime(runtime, definition)
  persistRuntimeMap()
}

function removeWorkbench(id) {
  const normalizedId = String(id || '').trim()
  if (!normalizedId) return
  delete definitions[normalizedId]
  delete runtimeMap[normalizedId]
  persistRuntimeMap()
}

function invokeWorkbenchAction(id, action) {
  const normalizedAction = String(action || '').trim()
  if (!normalizedAction) return
  if (normalizedAction === 'resume') {
    resumeWorkbench(id)
    return
  }
  if (normalizedAction === 'close') {
    closeWorkbench(id)
    return
  }
  if (normalizedAction === 'dismiss') {
    dismissWorkbench(id)
    return
  }
  invokeDefinitionAction(id, normalizedAction)
}

const allWorkbenches = computed(() => (
  Object.values(runtimeMap)
    .slice()
    .sort((left, right) => {
      if (right.priority !== left.priority) return right.priority - left.priority
      return (right.updatedAt || 0) - (left.updatedAt || 0)
    })
))

const backgroundCards = computed(() => allWorkbenches.value.filter(item => item.cardVisible && !item.visible && !item.dismissed))

function getWorkbenchState(id) {
  return computed(() => ensureWorkbench(id))
}

const managerApi = {
  STORAGE_KEY,
  allWorkbenches,
  backgroundCards,
  getWorkbenchState,
  registerWorkbench,
  openWorkbench,
  backgroundWorkbench,
  resumeWorkbench,
  dismissWorkbench,
  closeWorkbench,
  patchWorkbenchState,
  removeWorkbench,
  invokeWorkbenchAction
}

export function useBackgroundWorkbenchManager() {
  return managerApi
}
