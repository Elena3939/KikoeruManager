import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { rjSubtitleApi } from '../api'

const SUBTITLE_IMPORT_QUEUE_STATE_KEY = 'kikoeru.ui.subtitleImport.workbenchQueueState'
const SUBTITLE_IMPORT_TASK_DRAFTS_KEY = 'kikoeru.ui.subtitleImport.taskDrafts'

export function useSubtitleImportWorkbench({
  route,
  workbenchManager,
  SUBTITLE_IMPORT_WORKBENCH_ID
}) {
  const router = useRouter()
  
  function clearPersistedWorkbenchSession() {
    try {
      localStorage.removeItem(SUBTITLE_IMPORT_QUEUE_STATE_KEY)
      localStorage.removeItem(SUBTITLE_IMPORT_TASK_DRAFTS_KEY)
    } catch (_) {}
  }

  function isLinkedSubtitleWorkbenchTask(task = {}) {
    const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
    return ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)
  }

  workbenchManager.registerWorkbench({
    id: SUBTITLE_IMPORT_WORKBENCH_ID,
    type: 'subtitle-import',
    title: '字幕补配工作台',
    priority: 72,
    actions: ['resume', 'close'],
    onClose: () => {
      closeImportWorkbench()
    }
  })

  const subtitleImportWorkbenchRuntime = workbenchManager.getWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID)
  
  const activeWorkbenchTaskId = ref(String(
    route.query.taskId ||
    subtitleImportWorkbenchRuntime.value?.payload?.activeTaskId ||
    ''
  ))

  const workbenchDialogVisible = computed({
    get: () => Boolean(subtitleImportWorkbenchRuntime.value?.visible),
    set: (value) => {
      workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
        visible: Boolean(value),
        restorable: Boolean(value) || Boolean(workbenchBackgroundActive.value) || Boolean(activeWorkbenchTaskId.value)
      })
    }
  })

  const workbenchBackgroundActive = computed({
    get: () => Boolean(subtitleImportWorkbenchRuntime.value?.backgroundActive),
    set: (value) => {
      workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
        backgroundActive: Boolean(value),
        cardVisible: Boolean(value),
        dismissed: false,
        restorable: Boolean(value) || Boolean(workbenchDialogVisible.value) || Boolean(activeWorkbenchTaskId.value)
      })
    }
  })

  const workbenchDialogInitialized = ref(Boolean(
    route.query.taskId ||
    activeWorkbenchTaskId.value ||
    subtitleImportWorkbenchRuntime.value?.visible ||
    subtitleImportWorkbenchRuntime.value?.backgroundActive
  ))

  const workbenchBackgroundSummary = ref({
    total: 0,
    processing: 0,
    awaiting: 0,
    completed: 0,
    manualCompleted: 0,
    failed: 0,
    clearable: 0,
    selectedTaskId: '',
    activeTask: null
  })

  function syncSubtitleImportWorkbenchCardState() {
    const summary = workbenchBackgroundSummary.value || {}
    const total = Number(summary.total || 0)
    const processing = Number(summary.processing || 0)
    const awaiting = Number(summary.awaiting || 0)
    const completed = Number(summary.completed || 0)
    const failed = Number(summary.failed || 0)
    const activeTask = summary.activeTask || null
    const percentage = total > 0 ? Math.max(0, Math.min(100, Math.round(((completed + failed) / total) * 100))) : 0
    const tone = processing > 0 ? 'info' : awaiting > 0 ? 'warning' : failed > 0 ? 'warning' : completed > 0 ? 'success' : 'neutral'
    const label = processing > 0 ? '后台运行中' : awaiting > 0 ? '待配对' : failed > 0 ? '可回看' : completed > 0 ? '已完成' : '待处理'

    workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
      title: '字幕补配工作台',
      cardVisible: Boolean(workbenchBackgroundActive.value),
      dismissed: false,
      payload: {
        activeTaskId: String(activeWorkbenchTaskId.value || '')
      },
      status: {
        key: tone,
        label,
        tone
      },
      progress: {
        percentage,
        status: failed > 0 && processing <= 0 ? 'warning' : completed > 0 && processing <= 0 && failed <= 0 ? 'success' : '',
        label: activeTask?.progressText || activeTask?.statusLabel || ''
      },
      summary: {
        subtitle: activeTask
          ? `${activeTask.rjcode || '当前任务'} · ${activeTask.title || '-'}`
          : '保留当前队列与人工补配上下文',
        text: activeTask?.progressText || activeTask?.statusLabel || '隐藏后继续保留任务队列、自动轮询和手动补配上下文。'
      },
      metrics: [
        { key: 'total', label: '全部', value: total, tone: 'neutral' },
        { key: 'processing', label: '进行中', value: processing, tone: processing > 0 ? 'info' : 'neutral' },
        { key: 'awaiting', label: '待配对', value: awaiting, tone: awaiting > 0 ? 'warning' : 'neutral' },
        { key: 'completed', label: '完成', value: completed, tone: completed > 0 ? 'success' : 'neutral' },
        { key: 'failed', label: '失败', value: failed, tone: failed > 0 ? 'danger' : 'neutral' }
      ]
    })
  }

  function resetImportWorkbenchSession(options = {}) {
    const { clearDrafts = true } = options
    workbenchDialogVisible.value = false
    workbenchBackgroundActive.value = false
    workbenchDialogInitialized.value = false
    activeWorkbenchTaskId.value = ''
    workbenchBackgroundSummary.value = {
      total: 0,
      processing: 0,
      awaiting: 0,
      completed: 0,
      manualCompleted: 0,
      failed: 0,
      clearable: 0,
      selectedTaskId: '',
      activeTask: null
    }
    if (clearDrafts) {
      clearPersistedWorkbenchSession()
    }
  }

  watch(() => route.query.taskId, (value) => {
    if (value) {
      activeWorkbenchTaskId.value = String(value || '')
      workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
        activeTaskId: activeWorkbenchTaskId.value
      })
      workbenchDialogInitialized.value = true
      workbenchBackgroundActive.value = false
      workbenchDialogVisible.value = true
      return
    }
    if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) {
      activeWorkbenchTaskId.value = ''
    }
  }, { immediate: true })

  watch(activeWorkbenchTaskId, (taskId) => {
    const normalized = String(taskId || '')
    workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
      payload: {
        activeTaskId: normalized
      },
      restorable: Boolean(normalized) || Boolean(workbenchDialogVisible.value) || Boolean(workbenchBackgroundActive.value)
    })
    if (!workbenchDialogVisible.value) return
    if (String(route.query.taskId || '') === normalized) {
      return
    }
    const nextQuery = { ...route.query }
    if (normalized) nextQuery.taskId = normalized
    else delete nextQuery.taskId
    router.replace({
      path: '/subtitle-import',
      query: nextQuery
    })
  })

  watch(() => workbenchBackgroundSummary.value, () => {
    syncSubtitleImportWorkbenchCardState()
  }, { deep: true, immediate: true })

  async function restoreActiveWorkbenchTask(options = {}) {
    const { silent = false } = options
    try {
      const requestedId = String(
        route.query.taskId ||
        activeWorkbenchTaskId.value ||
        subtitleImportWorkbenchRuntime.value?.payload?.activeTaskId ||
        ''
      )
      const data = await rjSubtitleApi.status()
      const candidates = (data.tasks || []).filter(task => isLinkedSubtitleWorkbenchTask(task))
      const matchedTask = (requestedId && candidates.find(task => task.id === requestedId)) || candidates.at(-1) || null
      if (!matchedTask) {
        activeWorkbenchTaskId.value = ''
        workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
          payload: {
            activeTaskId: ''
          }
        })
        if (route.query.taskId) {
          const nextQuery = { ...route.query }
          delete nextQuery.taskId
          router.replace({
            path: '/subtitle-import',
            query: nextQuery
          })
        }
        return
      }
      activeWorkbenchTaskId.value = String(matchedTask.id || '')
      workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
        payload: {
          activeTaskId: activeWorkbenchTaskId.value
        }
      })
      if (workbenchDialogVisible.value && route.query.taskId !== activeWorkbenchTaskId.value) {
        router.replace({
          path: '/subtitle-import',
          query: {
            ...route.query,
            taskId: activeWorkbenchTaskId.value
          }
        })
      }
    } catch (error) {
      // Ignore silent errors
    }
  }

  function openImportedTask(taskId) {
    const nextTaskId = String(taskId || '')
    workbenchDialogInitialized.value = true
    workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
      activeTaskId: nextTaskId
    })
    if (!nextTaskId) return
    if (activeWorkbenchTaskId.value === nextTaskId && route.query.taskId === nextTaskId) return
    activeWorkbenchTaskId.value = nextTaskId
  }

  function openImportWorkbench() {
    workbenchDialogInitialized.value = true
    workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
      activeTaskId: String(activeWorkbenchTaskId.value || '')
    })
  }

  function hideImportWorkbenchToBackground() {
    workbenchDialogInitialized.value = true
    workbenchManager.backgroundWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID)
  }

  function closeImportWorkbench(options = {}) {
    const summary = workbenchBackgroundSummary.value || {}
    const total = Number(summary.total || 0)
    const manualCompleted = Number(summary.manualCompleted || 0)
    const defaultPreserveSession = total <= 0 || manualCompleted < total
    const { preserveSession = defaultPreserveSession } = options
    if (preserveSession) {
      workbenchDialogVisible.value = false
      workbenchBackgroundActive.value = false
      workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
        visible: false,
        backgroundActive: false,
        cardVisible: false,
        dismissed: true,
        restorable: Boolean(activeWorkbenchTaskId.value),
        payload: {
          activeTaskId: String(activeWorkbenchTaskId.value || '')
        }
      })
      return
    }
    resetImportWorkbenchSession({ clearDrafts: true })
  }

  function handleWorkbenchStateChange(payload) {
    workbenchBackgroundSummary.value = {
      total: Number(payload?.total || 0),
      processing: Number(payload?.processing || 0),
      awaiting: Number(payload?.awaiting || 0),
      completed: Number(payload?.completed || 0),
      manualCompleted: Number(payload?.manualCompleted || 0),
      failed: Number(payload?.failed || 0),
      clearable: Number(payload?.clearable || 0),
      selectedTaskId: String(payload?.selectedTaskId || ''),
      activeTask: payload?.activeTask || null
    }
    syncSubtitleImportWorkbenchCardState()
  }

  return {
    workbenchDialogVisible,
    workbenchBackgroundActive,
    workbenchDialogInitialized,
    workbenchBackgroundSummary,
    activeWorkbenchTaskId,
    
    restoreActiveWorkbenchTask,
    openImportedTask,
    openImportWorkbench,
    hideImportWorkbenchToBackground,
    closeImportWorkbench,
    handleWorkbenchStateChange
  }
}
