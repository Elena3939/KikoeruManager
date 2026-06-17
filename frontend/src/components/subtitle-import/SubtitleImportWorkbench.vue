<template>
  <div class="subtitle-import-workbench">
    <section class="siw-shell" aria-label="字幕补配工作台">
      <header class="siw-header">
        <div class="siw-title-wrap">
          <div class="siw-brand" aria-hidden="true">
            <Captions class="siw-brand-icon" :stroke-width="2.15" />
          </div>
          <div class="siw-title-copy">
            <div class="siw-title-line">
              <h2>字幕补配工作台</h2>
              <span class="siw-live-pill"><span></span>Live</span>
            </div>
            <div class="siw-focus-row">
              <span class="siw-focus-code">{{ activeTask ? getTaskDisplayRJCode(activeTask) : '等待任务' }}</span>
              <span class="siw-focus-name">
                {{ activeTask ? (activeTask.folder_name || getFileName(activeTask.folder_path) || getTaskStatusLabel(activeTask)) : '队列、筛选、配对和字幕树上下文会保留在这里' }}
              </span>
            </div>
          </div>
        </div>

        <div class="siw-actions" aria-label="工作台操作">
          <button
            type="button"
            class="siw-action-btn"
            :disabled="manualRefreshing || taskRefreshing"
            title="刷新状态"
            @click="refreshTaskStatus(true, { inspect: true, forceInspect: true, showOverlay: false })"
          >
            <RefreshCw class="siw-action-icon" :class="{ 'is-spinning': manualRefreshing || taskRefreshing }" :stroke-width="2.3" />
            <span>刷新</span>
          </button>
          <button
            type="button"
            class="siw-action-btn"
            :disabled="!clearableTaskCount || queueClearing"
            title="清空已结束、失败或待配对任务"
            @click="clearFinishedTasks"
          >
            <Trash2 class="siw-action-icon" :class="{ 'is-spinning': queueClearing }" :stroke-width="2.3" />
            <span>清空</span>
          </button>
          <button
            type="button"
            class="siw-action-btn"
            title="隐藏到后台"
            @click="emit('hide-background')"
          >
            <Minimize2 class="siw-action-icon" :stroke-width="2.3" />
            <span>后台</span>
          </button>
          <button
            type="button"
            class="siw-action-btn is-close"
            :disabled="workbenchClosing"
            title="关闭工作台，并只清理已完成或失败任务；待配对任务会保留"
            @click="closeWorkbenchAndCleanupCompleted"
          >
            <component :is="workbenchClosing ? Loader2 : X" class="siw-action-icon" :class="{ 'is-spinning': workbenchClosing }" :stroke-width="2.4" />
            <span>关闭</span>
          </button>
        </div>
      </header>

      <main
        class="siw-stage-wrap"
        v-app-loading="{ loading: workbenchLoading, text: '正在整理字幕工作台...', description: '同步批次、候选字幕和配对状态', size: 136 }"
      >
        <SubtitleWorkbenchStage :ctx="subtitleWorkbenchStageCtx" />
      </main>
    </section>

    <Teleport to="body">
      <Transition name="siw-dialog-fade">
        <div
          v-if="subtitleRenameDialogVisible"
          class="siw-rename-overlay"
          role="presentation"
          @click="subtitleRenameDialogVisible = false"
        >
          <form
            class="siw-rename-card"
            role="dialog"
            aria-modal="true"
            aria-label="重命名字幕文件"
            @click.stop
            @submit.prevent="confirmSubtitleRename"
          >
            <header class="siw-rename-head">
              <div>
                <h3>重命名字幕文件</h3>
                <p>只修改字幕工作区里的当前文件名。</p>
              </div>
              <button
                type="button"
                class="siw-icon-btn"
                aria-label="关闭"
                @click="subtitleRenameDialogVisible = false"
              >
                <X :size="16" :stroke-width="2.4" />
              </button>
            </header>

            <div class="siw-rename-fields">
              <label class="siw-field">
                <span>当前名称</span>
                <input :value="subtitleRenameForm.currentName" type="text" readonly />
              </label>
              <label class="siw-field">
                <span>新名称</span>
                <input
                  v-model="subtitleRenameForm.newName"
                  type="text"
                  autocomplete="off"
                  placeholder="输入新的字幕文件名"
                  @keydown.stop
                />
              </label>
              <div class="siw-preview">
                <span>预览</span>
                <strong>{{ subtitleRenameForm.newName || subtitleRenameForm.currentName }}</strong>
              </div>
            </div>

            <footer class="siw-rename-actions">
              <button
                type="button"
                class="siw-form-btn"
                :disabled="subtitleRenameLoading"
                @click="subtitleRenameDialogVisible = false"
              >
                取消
              </button>
              <button
                type="submit"
                class="siw-form-btn is-primary"
                :disabled="subtitleRenameLoading"
              >
                <Loader2 v-if="subtitleRenameLoading" class="siw-action-icon is-spinning" :stroke-width="2.4" />
                <span>{{ subtitleRenameLoading ? '重命名中' : '确认重命名' }}</span>
              </button>
            </footer>
          </form>
        </div>
      </Transition>
    </Teleport>

    <FilterDeleteDialog
      v-model="filterDeleteDialogVisible"
      :library-id="filterDeleteDialogLibraryId"
      :current-path="filterDeleteDialogPath"
      :target-paths="filterDeleteDialogTargetPaths"
      :rules="subtitleInspectorFilterDeleteRules"
      :scope-label="filterDeleteDialogScopeLabel"
      :is-remote="filterDeleteDialogIsRemote"
      @deleted="handleFilterDeleteDeleted"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Captions, Folder, FolderOpen, Loader2, Minimize2, RefreshCw, Trash2, X } from 'lucide-vue-next'
import { showSystemConfirm } from '../../composables/useSystemPrompt'
import { aiSubtitleMatchApi, libraryApi, rjSubtitleApi, subtitleImportApi } from '../../api'
import { runWithConcurrency } from '../../composables/useAsyncBatch'
import { normalizeTaskCenterRealtimePayloads } from '../../composables/taskCenterEventUtils'
import { useRealtimeEvents } from '../../composables/useRealtimeEvents'
import { libraryEntryIconFor, libraryEntryMetaFor } from '../library/_libraryFileKind'
import FilterDeleteDialog from '../library/FilterDeleteDialog.vue'
import SubtitleWorkbenchStage from '../library/subtitle-workbench/SubtitleWorkbenchStage.vue'

const props = defineProps({
  taskId: {
    type: String,
    default: ''
  },
  visible: {
    type: Boolean,
    default: false
  },
  backgroundActive: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'hide-background', 'select-task', 'state-change'])
const realtimeEvents = useRealtimeEvents()

const LEGACY_SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'
const SUBTITLE_IMPORT_OPTIONS_KEY = 'kikoeru.ui.subtitleImport.workbenchOptions'
const SUBTITLE_IMPORT_QUEUE_STATE_KEY = 'kikoeru.ui.subtitleImport.workbenchQueueState'
const SUBTITLE_IMPORT_TASK_DRAFTS_KEY = 'kikoeru.ui.subtitleImport.taskDrafts'

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch (_) {
    return fallback
  }
}

function saveJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch (_) {}
}

function createSubtitleFilterRule(overrides = {}) {
  return {
    id: `subtitle-filter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    target: 'name',
    name: '',
    pattern: '',
    enabled: true,
    ...overrides
  }
}

function normalizeSubtitleFilterRule(rule = {}) {
  return createSubtitleFilterRule({
    id: rule.id || undefined,
    target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',
    name: String(rule.name || ''),
    pattern: String(rule.pattern || ''),
    enabled: rule.enabled !== false
  })
}

function normalizeAISubtitleMatchMode(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return ['rule', 'ai_auto', 'rule_ai_auto', 'ai_assist'].includes(normalized)
    ? normalized
    : 'rule_ai_auto'
}

function normalizeAISubtitleConfidenceThreshold(value, fallback = 85) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

function sanitizeSubtitleFilterRules(rules = []) {
  return (rules || [])
    .map(rule => normalizeSubtitleFilterRule(rule))
    .filter(rule => rule.pattern.trim())
    .map(rule => ({
      target: rule.target,
      name: rule.name.trim(),
      pattern: rule.pattern.trim(),
      enabled: rule.enabled !== false
    }))
}

function loadSubtitleImportOptions() {
  const saved = loadJson(SUBTITLE_IMPORT_OPTIONS_KEY, null)
  if (saved && typeof saved === 'object') return saved
  const legacy = loadJson(LEGACY_SUBTITLE_OPTIONS_KEY, {})
  if (legacy && typeof legacy === 'object') {
    saveJson(SUBTITLE_IMPORT_OPTIONS_KEY, legacy)
  }
  return legacy
}

function getSubtitleWorkbenchOptions() {
  const saved = loadSubtitleImportOptions()
  return {
    namingStrategy: saved?.namingStrategy === 'subtitle' ? 'subtitle' : 'audio',
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: (saved?.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule)).filter(rule => rule.pattern.trim()),
    aiMatchMode: normalizeAISubtitleMatchMode(saved?.aiMatchMode || saved?.ai_match_mode),
    aiConfidenceThreshold: normalizeAISubtitleConfidenceThreshold(saved?.aiConfidenceThreshold ?? saved?.ai_confidence_threshold)
  }
}

const subtitleOptions = ref(getSubtitleWorkbenchOptions())
const taskLoading = ref(false)
const manualRefreshing = ref(false)
const taskLoadedOnce = ref(false)
const taskRefreshing = ref(false)
const linkedTasks = ref([])
const activeTask = ref(null)
const queueState = loadJson(SUBTITLE_IMPORT_QUEUE_STATE_KEY, {})
const selectedTaskId = ref(String(queueState.selectedTaskId || ''))
const queuePageSize = 8
const queuePage = ref(Math.max(1, Number(queueState.page || 1)))
const queueClearing = ref(false)
const workbenchClosing = ref(false)
const retryingTaskId = ref('')
const subtitleRenameDialogVisible = ref(false)
const subtitleRenameForm = ref({ currentName: '', newName: '', path: '' })
const subtitleRenameLoading = ref(false)
const filterDeleteDialogVisible = ref(false)
const filterDeleteDialogLibraryId = ref('')
const filterDeleteDialogPath = ref('')
const filterDeleteDialogTargetPaths = ref([])
const filterDeleteDialogScopeLabel = ref('')
const filterDeleteDialogIsRemote = ref(false)
const subtitleCleanupLoading = ref(false)
const subtitleCleanupSummary = ref('')
const retargetPreviewLoading = ref(false)
const retargetPreview = ref(null)
const retargetCandidateSelection = ref('')
const retargetPreviewTaskId = ref('')
const retargetingTaskId = ref('')

const subtitleInspectorLoading = ref(false)
const subtitleInspectorDeleting = ref(false)
const subtitleInspectorSearch = ref('')
const subtitleInspectorItems = ref([])
const subtitleInspectorAudioItems = ref([])
const subtitleInspectorAudioSearch = ref('')
const subtitleInspectorSubtitleSearch = ref('')
const subtitleInspectorExpandedIds = ref(new Set())
const subtitleInspectorSelectedIds = ref(new Set())
const subtitleInspectorLastSelectedId = ref('')
const subtitleInspectorInfo = ref({
  taskId: '',
  libraryId: '',
  audioLibraryId: '',
  subtitleLibraryId: '',
  folderPath: '',
  subtitleDir: '',
  sourceMode: '',
  audioLoadError: '',
  subtitleLoadError: '',
  totalFiles: 0,
  totalSize: 0
})

const subtitleMatchSelection = ref({ audioPath: '', subtitlePath: '' })
const subtitleSequenceMode = ref(false)
const subtitleSequenceSelection = ref({ audioPaths: [], subtitlePaths: [] })
const subtitleLastPairBuildMode = ref('')
const subtitleManualPairs = ref([])
const subtitleSelectedManualPairId = ref('')
const subtitlePairApplying = ref(false)
const subtitleAutoPairing = ref(false)
const subtitleAudioFilterMode = ref('all')
const subtitleSubtitleFilterMode = ref('all')
const TASK_STATUS_REFRESH_MS = 30000
let taskStatusTimer = null
let skipTaskDraftPersistence = false
let subtitleInspectRequestSeq = 0

const workbenchLoading = computed(() => {
  return taskLoading.value && !taskLoadedOnce.value
})

function loadTaskDraftMap() {
  const saved = loadJson(SUBTITLE_IMPORT_TASK_DRAFTS_KEY, {})
  return saved && typeof saved === 'object' ? saved : {}
}

function saveTaskDraftMap(value) {
  saveJson(SUBTITLE_IMPORT_TASK_DRAFTS_KEY, value)
}

function normalizeDraftPair(pair = {}) {
  const audioPath = String(pair.audio_path || '').trim()
  const subtitlePath = String(pair.subtitle_path || '').trim()
  if (!audioPath || !subtitlePath) return null
  return {
    id: String(pair.id || `${audioPath}::${subtitlePath}`),
    audio_path: audioPath,
    audio_name: String(pair.audio_name || ''),
    audio_relative_path: String(pair.audio_relative_path || pair.audio_name || ''),
    subtitle_path: subtitlePath,
    subtitle_name: String(pair.subtitle_name || ''),
    subtitle_relative_path: String(pair.subtitle_relative_path || pair.subtitle_name || ''),
    confidenceLevel: ['high', 'medium', 'low'].includes(pair.confidenceLevel) ? pair.confidenceLevel : 'medium',
    matchReason: String(pair.matchReason || '手动配对')
  }
}

function buildTaskDraftState() {
  return {
    selectedTaskId: String(selectedTaskId.value || ''),
    audioSearch: String(subtitleInspectorAudioSearch.value || ''),
    subtitleSearch: String(subtitleInspectorSubtitleSearch.value || ''),
    audioFilterMode: String(subtitleAudioFilterMode.value || 'all'),
    subtitleFilterMode: String(subtitleSubtitleFilterMode.value || 'all'),
    matchSelection: {
      audioPath: String(subtitleMatchSelection.value.audioPath || ''),
      subtitlePath: String(subtitleMatchSelection.value.subtitlePath || '')
    },
    sequenceMode: Boolean(subtitleSequenceMode.value),
    sequenceSelection: {
      audioPaths: [...(subtitleSequenceSelection.value.audioPaths || [])].map(path => String(path || '')).filter(Boolean),
      subtitlePaths: [...(subtitleSequenceSelection.value.subtitlePaths || [])].map(path => String(path || '')).filter(Boolean)
    },
    lastPairBuildMode: String(subtitleLastPairBuildMode.value || ''),
    selectedManualPairId: String(subtitleSelectedManualPairId.value || ''),
    manualPairs: (subtitleManualPairs.value || []).map(pair => normalizeDraftPair(pair)).filter(Boolean)
  }
}

function persistQueueState() {
  saveJson(SUBTITLE_IMPORT_QUEUE_STATE_KEY, {
    page: queuePage.value,
    selectedTaskId: String(selectedTaskId.value || '')
  })
}

function persistSubtitleTaskDraft(taskId = '') {
  if (skipTaskDraftPersistence) return
  const normalizedTaskId = String(taskId || subtitleInspectorInfo.value.taskId || activeTask.value?.id || '').trim()
  if (!normalizedTaskId) return
  const draftMap = loadTaskDraftMap()
  draftMap[normalizedTaskId] = buildTaskDraftState()
  saveTaskDraftMap(draftMap)
}

function clearSubtitleTaskDraft(taskId = '') {
  const normalizedTaskId = String(taskId || '').trim()
  if (!normalizedTaskId) return
  const draftMap = loadTaskDraftMap()
  if (!(normalizedTaskId in draftMap)) return
  delete draftMap[normalizedTaskId]
  saveTaskDraftMap(draftMap)
}

function findDraftItem(items, pair, kind) {
  const targetPath = String(kind === 'audio' ? pair.audio_path : pair.subtitle_path || '').trim()
  const targetRelativePath = String(kind === 'audio' ? pair.audio_relative_path : pair.subtitle_relative_path || '').trim()
  const targetName = String(kind === 'audio' ? pair.audio_name : pair.subtitle_name || '').trim()
  return items.find(item => item.path === targetPath)
    || items.find(item => String(item.relative_path || item.name || '').trim() === targetRelativePath)
    || items.find(item => String(item.name || '').trim() === targetName)
    || null
}

function restoreSubtitleTaskDraft(taskId = '') {
  const normalizedTaskId = String(taskId || '').trim()
  if (!normalizedTaskId) return false
  const draft = loadTaskDraftMap()[normalizedTaskId]
  if (!draft || typeof draft !== 'object') return false

  const restoredPairs = (draft.manualPairs || [])
    .map(pair => normalizeDraftPair(pair))
    .filter(Boolean)
    .map(pair => {
      const audio = findDraftItem(subtitleInspectorAudioFiles.value, pair, 'audio')
      const subtitle = findDraftItem(subtitleInspectorSubtitleFiles.value, pair, 'subtitle')
      if (!audio || !subtitle) return null
      return createSubtitlePair(audio, subtitle, {
        confidenceLevel: pair.confidenceLevel,
        matchReason: pair.matchReason
      })
    })
    .filter(Boolean)

  const audioPathSet = new Set(subtitleInspectorAudioFiles.value.map(item => item.path))
  const subtitlePathSet = new Set(subtitleInspectorSubtitleFiles.value.map(item => item.path))

  subtitleInspectorAudioSearch.value = String(draft.audioSearch || '')
  subtitleInspectorSubtitleSearch.value = String(draft.subtitleSearch || '')
  subtitleAudioFilterMode.value = ['all', 'paired', 'unpaired'].includes(draft.audioFilterMode) ? draft.audioFilterMode : 'all'
  subtitleSubtitleFilterMode.value = ['all', 'paired', 'unpaired'].includes(draft.subtitleFilterMode) ? draft.subtitleFilterMode : 'all'
  subtitleMatchSelection.value = {
    audioPath: audioPathSet.has(String(draft.matchSelection?.audioPath || '')) ? String(draft.matchSelection.audioPath || '') : '',
    subtitlePath: subtitlePathSet.has(String(draft.matchSelection?.subtitlePath || '')) ? String(draft.matchSelection.subtitlePath || '') : ''
  }
  subtitleSequenceMode.value = Boolean(draft.sequenceMode)
  subtitleSequenceSelection.value = {
    audioPaths: [...(draft.sequenceSelection?.audioPaths || [])].map(path => String(path || '')).filter(path => audioPathSet.has(path)),
    subtitlePaths: [...(draft.sequenceSelection?.subtitlePaths || [])].map(path => String(path || '')).filter(path => subtitlePathSet.has(path))
  }
  subtitleLastPairBuildMode.value = String(draft.lastPairBuildMode || '')
  subtitleManualPairs.value = restoredPairs
  subtitleSelectedManualPairId.value = restoredPairs.some(pair => pair.id === draft.selectedManualPairId)
    ? String(draft.selectedManualPairId || '')
    : (restoredPairs[0]?.id || '')
  return Boolean(
    restoredPairs.length
    || subtitleSequenceSelection.value.audioPaths.length
    || subtitleSequenceSelection.value.subtitlePaths.length
    || subtitleMatchSelection.value.audioPath
    || subtitleMatchSelection.value.subtitlePath
    || subtitleInspectorAudioSearch.value
    || subtitleInspectorSubtitleSearch.value
  )
}

watch(() => subtitleOptions.value.namingStrategy, () => {
  syncSubtitlePairTargetNames()
})

watch(subtitleOptions, (value) => {
  saveJson(SUBTITLE_IMPORT_OPTIONS_KEY, {
    namingStrategy: value.namingStrategy === 'subtitle' ? 'subtitle' : 'audio',
    useFilterRules: value.useFilterRules !== false,
    subtitleFilterRules: (value.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule)),
    aiMatchMode: normalizeAISubtitleMatchMode(value.aiMatchMode),
    aiConfidenceThreshold: normalizeAISubtitleConfidenceThreshold(value.aiConfidenceThreshold)
  })
}, { deep: true })

watch(() => props.taskId, async (value) => {
  if (value) selectedTaskId.value = String(value || '')
  if (!props.visible && !props.backgroundActive) return
  await refreshTaskStatus(false, { inspect: true, forceInspect: true })
}, { immediate: true })

watch(queuePage, (value) => {
  persistQueueState()
})

watch(selectedTaskId, () => {
  persistQueueState()
})

watch(linkedTasks, (tasks) => {
  const maxPage = Math.max(1, Math.ceil(tasks.length / queuePageSize))
  if (queuePage.value > maxPage) queuePage.value = maxPage
}, { deep: false })

watch([
  () => subtitleInspectorInfo.value.taskId,
  () => subtitleInspectorAudioSearch.value,
  () => subtitleInspectorSubtitleSearch.value,
  () => subtitleAudioFilterMode.value,
  () => subtitleSubtitleFilterMode.value,
  () => subtitleMatchSelection.value,
  () => subtitleSequenceMode.value,
  () => subtitleSequenceSelection.value,
  () => subtitleLastPairBuildMode.value,
  () => subtitleManualPairs.value,
  () => subtitleSelectedManualPairId.value
], () => {
  persistSubtitleTaskDraft()
}, { deep: true })

function normalizeRJSubtitleTaskPayload(task) {
  const trimTail = (items, limit) => Array.isArray(items) ? items.slice(-limit) : []
  const normalized = {
    ...task,
    search_attempts: Array.isArray(task?.search_attempts) ? task.search_attempts : [],
    download_files: trimTail(task?.download_files, 24),
    progress_log: trimTail(task?.progress_log, 24)
  }
  const subtitleDir = getTaskWorkbenchSubtitleDir(normalized)
  if (subtitleDir && !String(normalized.subtitle_dir || '').trim()) {
    normalized.subtitle_dir = subtitleDir
  }
  return normalized
}

function getFileName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

function getTaskWorkbenchSubtitleDir(task) {
  const subtitleDir = String(task?.subtitle_dir || '').trim()
  if (subtitleDir) return subtitleDir
  const workbenchRoot = String(task?.linked_workbench_root_dir || '').trim()
  return workbenchRoot ? joinFolderPath(workbenchRoot, 'subtitles') : ''
}

function candidateKey(candidate) {
  return `${candidate?.library_id || ''}::${candidate?.folder_path || ''}`
}

function getTaskTargetCandidateKey(task) {
  return candidateKey({
    library_id: task?.target_library_id || task?.library_id || '',
    folder_path: task?.target_folder_path || task?.folder_path || ''
  })
}

function getTaskDisplayRJCode(task) {
  return task?.rjcode || task?.actual_rjcode || '未知RJ'
}

function getTaskSourceRJCode(task) {
  const sourceRJ = String(task?.actual_rjcode || '').trim()
  const folderRJ = String(task?.rjcode || '').trim()
  return sourceRJ && sourceRJ !== folderRJ ? sourceRJ : ''
}

function preserveSubtitleTaskWorkspaceFields(task, previousTask) {
  if (!task || !previousTask || task.id !== previousTask.id) return task
  const next = { ...task }
  ;[
    'subtitle_dir',
    'subtitle_library_id',
    'target_library_id',
    'library_id',
    'target_folder_path',
    'folder_path',
    'source_mode',
    'source_archive_path',
    'source_subtitle_folder_path',
    'linked_workbench_root_dir'
  ].forEach(key => {
    if ((next[key] === undefined || next[key] === null || next[key] === '') && previousTask[key]) {
      next[key] = previousTask[key]
    }
  })
  const subtitleDir = getTaskWorkbenchSubtitleDir(next)
  if (subtitleDir && !String(next.subtitle_dir || '').trim()) {
    next.subtitle_dir = subtitleDir
  }
  return next
}

function getRJSubtitleTaskStatusType(task) {
  const state = getTaskStateClass(task)
  if (state === 'failed') return 'danger'
  if (state === 'awaiting') return 'warning'
  if (state === 'completed') return 'success'
  if (state === 'processing') return 'primary'
  return 'info'
}

function getTaskStatusLabel(task) {
  if (!task) return '未知状态'
  if (task.manual_match_completed) return '已完成补配'
  if (task.awaiting_manual_match) return '待筛选与配对'
  if (task.status === 'processing') return '处理中'
  if (task.status === 'pending') return '排队中'
  if (task.status === 'failed') return '执行失败'
  if (task.status === 'completed') return '已完成'
  return task.status || '未知状态'
}

function getTaskManualStateText(task) {
  if (!task) return ''
  if (task.manual_match_completed) return `已应用 ${task.manual_match_applied_pairs || 0} 组`
  if (task.awaiting_manual_match) return '等待你筛选和配对'
  return ''
}

function isLinkedSubtitleWorkbenchTask(task) {
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  return ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)
}

function isFailedTask(task) {
  return String(task?.status || '').toLowerCase() === 'failed'
}

function isCompletedTask(task) {
  return Boolean(task?.manual_match_completed)
}

function isProcessingTask(task) {
  return Boolean(String(task?.status || '').toLowerCase() === 'processing' || String(task?.status || '').toLowerCase() === 'pending')
}

function isAwaitingManualTask(task) {
  return Boolean(task?.awaiting_manual_match && !task?.manual_match_completed && !isFailedTask(task))
}

function getTaskStateClass(task) {
  if (isFailedTask(task)) return 'failed'
  if (isAwaitingManualTask(task)) return 'awaiting'
  if (isCompletedTask(task)) return 'completed'
  if (isProcessingTask(task)) return 'processing'
  return 'idle'
}

function getTaskFailureReason(task) {
  if (!task) return ''
  return String(task?.error_message || task?.current_step || '').trim()
}

function getTaskProgressText(task) {
  if (!task) return '-'
  if (isFailedTask(task)) return task.current_step || '执行失败'
  if (task.manual_match_completed) return `已完成 ${task.manual_match_applied_pairs || 0} 组`
  if (task.awaiting_manual_match) return `待配对 ${task.downloaded_count || 0} 字幕`
  if (Number.isFinite(Number(task.progress))) return `${Math.max(0, Math.min(100, Number(task.progress || 0)))}%`
  return task.current_step || '-'
}

function buildDefaultSubtitleTaskDetailPanels(task) {
  if (!task) return []
  const panels = []
  if (Array.isArray(task?.progress_log) && task.progress_log.length) panels.push('log')
  if (Array.isArray(task?.download_files) && task.download_files.length) panels.push('download')
  if (
    (Array.isArray(task?.written_files) && task.written_files.length) ||
    (Array.isArray(task?.skipped_files) && task.skipped_files.length) ||
    Number(task?.manual_match_applied_pairs || 0) > 0
  ) panels.push('written')
  if (
    (Array.isArray(task?.write_errors) && task.write_errors.length) ||
    (Array.isArray(task?.failed_files) && task.failed_files.length) ||
    String(task?.status || '').toLowerCase() === 'failed'
  ) panels.push('issues')
  if (
    task?.activity_context ||
    task?.restore_payload ||
    task?.source_label ||
    task?.source_mode ||
    task?.created_at ||
    task?.subtitle_dir ||
    task?.folder_path ||
    task?.snapshot
  ) panels.push('meta')
  return [...new Set(panels)]
}

function formatTaskTimeline(task) {
  const value = task?.completed_at || task?.started_at || task?.created_at
  if (!value) return '时间未知'
  return formatDate(value)
}

function sortLinkedTasks(tasks = []) {
  return [...tasks].sort((left, right) => {
    const leftTime = new Date(left?.completed_at || left?.started_at || left?.created_at || 0).getTime() || 0
    const rightTime = new Date(right?.completed_at || right?.started_at || right?.created_at || 0).getTime() || 0
    return rightTime - leftTime
  })
}

function canRetryTask(task) {
  if (!isFailedTask(task)) return false
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  if (sourceMode === 'linked_translation_archive_import') return Boolean(task?.source_archive_path)
  if (sourceMode === 'subtitle_folder_import') return Boolean(task?.source_subtitle_folder_path)
  return false
}

function canRetargetTask(task) {
  if (!task) return false
  if (task?.manual_match_completed) return false
  if (!getTaskWorkbenchSubtitleDir(task)) return false
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  return ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)
}

function canClearTask(task) {
  return Boolean(task && (isFailedTask(task) || task.manual_match_completed))
}

function canAutoClearTaskOnClose(task) {
  if (!task) return false
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  if (!['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)) {
    return false
  }
  return Boolean(task.manual_match_completed)
}

async function selectWorkbenchTask(taskId, options = {}) {
  const normalized = String(taskId || '')
  if (!normalized) return
  selectedTaskId.value = normalized
  const matchedTask = linkedTasks.value.find(task => task.id === normalized)
  if (matchedTask) activeTask.value = matchedTask
  if (props.visible && options.sync !== false && props.taskId !== normalized) {
    emit('select-task', normalized)
  }
  if (getTaskWorkbenchSubtitleDir(matchedTask) && options.inspect !== false) {
    await inspectSubtitleTask(matchedTask, { force: true })
  } else if (matchedTask && !getTaskWorkbenchSubtitleDir(matchedTask)) {
    clearSubtitleInspectorState()
  }
}

function buildRetargetSourceRJCode(task) {
  return String(task?.actual_rjcode || task?.rjcode || task?.target_rjcode || '').trim().toUpperCase()
}

function ensureSelectedWorkbenchTask(tasks = []) {
  const preferredId = String(selectedTaskId.value || props.taskId || '')
  const matched = (preferredId && tasks.find(task => task.id === preferredId)) || tasks[0] || null
  if (!matched) {
    selectedTaskId.value = ''
    queuePage.value = 1
    return null
  }
  if (selectedTaskId.value !== matched.id) {
    selectedTaskId.value = matched.id
  }
  const matchedIndex = tasks.findIndex(task => task.id === matched.id)
  if (matchedIndex >= 0) {
    queuePage.value = Math.max(1, Math.floor(matchedIndex / queuePageSize) + 1)
  }
  if (props.visible && props.taskId !== matched.id) {
    emit('select-task', matched.id)
  }
  return matched
}

function addSubtitleFilterRule() {
  subtitleOptions.value.subtitleFilterRules.push(createSubtitleFilterRule())
}

function removeSubtitleFilterRule(ruleId) {
  subtitleOptions.value.subtitleFilterRules = subtitleOptions.value.subtitleFilterRules.filter(rule => rule.id !== ruleId)
}

function buildCleanupSummary(result = {}) {
  const lrc = result?.lrc_clean || {}
  const simplify = result?.simplify_chinese || {}
  return [
    `LRC 广告清理 ${lrc.enabled ? '已执行' : '未启用'}，处理 ${Number(lrc.total_files || 0)} 个，清理 ${Number(lrc.cleaned_files || 0)} 个，移除广告行 ${Number(lrc.total_removed_lines || 0)}`,
    `繁体转简体 ${simplify.enabled ? '已执行' : '未启用'}，处理 ${Number(simplify.total_files || 0)} 个，转换 ${Number(simplify.converted_files || 0)} 个`
  ].join('；')
}

async function refreshTaskStatus(showMessage = false, options = {}) {
  const { inspect = true, forceInspect = false, showOverlay, silent = false } = options
  const shouldShowOverlay = typeof showOverlay === 'boolean'
    ? showOverlay
    : (!silent && !taskLoadedOnce.value && !taskLoading.value)

  if (taskRefreshing.value) {
    return
  }

  manualRefreshing.value = showMessage
  const shouldShowLoading = shouldShowOverlay || (!silent && (!linkedTasks.value.length || showMessage))
  taskRefreshing.value = true
  if (shouldShowLoading) {
    taskLoading.value = true
  }
  try {
    const data = await rjSubtitleApi.status()
    const previousTasksById = new Map(linkedTasks.value.map(task => [task.id, task]))
    linkedTasks.value = sortLinkedTasks(
      (data.tasks || [])
        .filter(task => isLinkedSubtitleWorkbenchTask(task))
        .map(task => normalizeRJSubtitleTaskPayload(task))
        .map(task => preserveSubtitleTaskWorkspaceFields(task, previousTasksById.get(task.id)))
    )
    taskLoadedOnce.value = true

    const found = ensureSelectedWorkbenchTask(linkedTasks.value)
    if (!found) {
      activeTask.value = null
      clearSubtitleInspectorState()
      subtitleCleanupSummary.value = ''
      if (showMessage) ElMessage.warning('当前没有可用的字幕补配任务')
      return
    }

    activeTask.value = found
    subtitleCleanupSummary.value = activeTask.value?.linked_subtitle_cleanup_result
      ? buildCleanupSummary(activeTask.value.linked_subtitle_cleanup_result)
      : ''
    if (inspect && getTaskWorkbenchSubtitleDir(activeTask.value)) {
      await inspectSubtitleTask(activeTask.value, { force: forceInspect })
    } else if (inspect && !getTaskWorkbenchSubtitleDir(activeTask.value)) {
      clearSubtitleInspectorState()
    }
    if (showMessage) ElMessage.success('字幕补配任务状态已刷新')
  } catch (error) {
    ElMessage.error('获取字幕补配任务状态失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    manualRefreshing.value = false
    taskRefreshing.value = false
    if (shouldShowLoading) {
      taskLoading.value = false
    }
  }
}

async function clearFinishedTasks() {
  const targets = linkedTasks.value.filter(task => canClearTask(task))
  if (!targets.length) {
    ElMessage.warning('当前没有可清理的已完成、待配对或失败任务')
    return
  }

  try {
    await showSystemConfirm({
      title: '清空队列确认',
      message: `确定清空 ${targets.length} 条已完成、待配对或失败任务吗？正在下载/写入的任务会保留。`,
      confirmText: '清空队列',
      cancelText: '取消',
      tone: 'warning'
    })
  } catch (_) {
    return
  }

  queueClearing.value = true
  try {
    // 之前是串行 await，N 条任务等 N×100-300ms；改并发 6 让"清空队列"几乎瞬完成
    await runWithConcurrency(targets, 6, async (task) => {
      await rjSubtitleApi.clearTask(task.id)
    })
    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    ElMessage.success(`已清空 ${targets.length} 条历史任务`)
  } catch (error) {
    ElMessage.error('清空队列失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    queueClearing.value = false
  }
}

async function closeWorkbenchAndCleanupCompleted() {
  if (workbenchClosing.value) return
  workbenchClosing.value = true
  try {
    const clearableTasks = linkedTasks.value.filter(task => canAutoClearTaskOnClose(task))
    await runWithConcurrency(clearableTasks, 6, async (task) => {
      try {
        await rjSubtitleApi.clearTask(task.id)
        clearSubtitleTaskDraft(task.id)
      } catch (error) {
        console.warn('[字幕补配] 关闭工作台时清理任务失败', task.id, error)
      }
    })
    const remainingTasks = linkedTasks.value.filter(task => !canAutoClearTaskOnClose(task))
    emit('close', { preserveSession: remainingTasks.length > 0 })
  } finally {
    workbenchClosing.value = false
  }
}

async function retryWorkbenchTask(task) {
  if (!canRetryTask(task)) return

  retryingTaskId.value = String(task.id || '')
  try {
    const commonOptions = {
      preferredLibraryId: task.target_library_id || undefined,
      targetLibraryId: task.target_library_id || undefined,
      targetFolderPath: task.target_folder_path || undefined,
      useFilterRules: subtitleOptions.value.useFilterRules !== false,
      subtitleFilterRules: (subtitleOptions.value.subtitleFilterRules || [])
        .map(rule => normalizeSubtitleFilterRule(rule))
        .filter(rule => String(rule.pattern || '').trim())
    }

    let result = null
    if (String(task.source_mode || '').trim().toLowerCase() === 'linked_translation_archive_import') {
      result = await subtitleImportApi.importArchive(task.source_archive_path, commonOptions)
    } else if (String(task.source_mode || '').trim().toLowerCase() === 'subtitle_folder_import') {
      result = await subtitleImportApi.importFolder(task.source_subtitle_folder_path, commonOptions)
    }

    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    if (result?.task?.id) {
      selectWorkbenchTask(result.task.id)
    }
    ElMessage.success('已重新创建字幕补配任务')
  } catch (error) {
    ElMessage.error('重试字幕补配任务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    retryingTaskId.value = ''
  }
}

async function loadRetargetPreview(task = activeTask.value, options = {}) {
  const { force = false, showMessage = false } = options
  if (!task || !canRetargetTask(task)) {
    retargetPreview.value = null
    retargetCandidateSelection.value = ''
    retargetPreviewTaskId.value = ''
    return
  }

  const taskId = String(task.id || '')
  if (!force && retargetPreviewTaskId.value === taskId && retargetPreview.value) {
    return
  }

  retargetPreviewLoading.value = true
  try {
    const previewResult = await subtitleImportApi.previewFolder(getTaskWorkbenchSubtitleDir(task), {
      preferredLibraryId: task.target_library_id || task.library_id || undefined,
      sourceRJCodeHint: buildRetargetSourceRJCode(task)
    })
    retargetPreview.value = previewResult?.preview || null
    retargetPreviewTaskId.value = taskId

    const currentTargetKey = getTaskTargetCandidateKey(task)
    const candidates = previewResult?.preview?.candidates || []
    const matchedCurrent = candidates.find(candidate => candidateKey(candidate) === currentTargetKey)
    const selectedCandidate = matchedCurrent || previewResult?.preview?.selected_candidate || null
    retargetCandidateSelection.value = selectedCandidate ? candidateKey(selectedCandidate) : ''

    if (showMessage) {
      ElMessage.success('已刷新可切换目标目录候选')
    }
  } catch (error) {
    retargetPreview.value = null
    retargetCandidateSelection.value = ''
    retargetPreviewTaskId.value = ''
    if (showMessage) {
      ElMessage.error('加载目标目录候选失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    retargetPreviewLoading.value = false
  }
}

async function retargetActiveTask() {
  const task = activeTask.value
  const candidate = selectedRetargetCandidate.value
  if (!task || !candidate || !canRetargetActiveTask.value) return

  retargetingTaskId.value = String(task.id || '')
  try {
    const commonOptions = {
      preferredLibraryId: candidate.library_id || task.target_library_id || task.library_id || undefined,
      targetLibraryId: candidate.library_id,
      targetFolderPath: candidate.folder_path,
      sourceRJCodeHint: buildRetargetSourceRJCode(task),
      useFilterRules: subtitleOptions.value.useFilterRules !== false,
      subtitleFilterRules: (subtitleOptions.value.subtitleFilterRules || [])
        .map(rule => normalizeSubtitleFilterRule(rule))
        .filter(rule => String(rule.pattern || '').trim())
    }

    const result = await subtitleImportApi.importFolder(getTaskWorkbenchSubtitleDir(task), commonOptions)
    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    if (result?.task?.id) {
      selectWorkbenchTask(result.task.id)
    }
    ElMessage.success('已切换目标目录并重建字幕补配任务')
  } catch (error) {
    ElMessage.error('切换目标目录失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    retargetingTaskId.value = ''
  }
}

function decodePossibleMojibake(value) {
  return String(value || '').trim()
}

function isSubtitleDirectoryMissingError(error) {
  const detail = decodePossibleMojibake(error?.response?.data?.detail || error?.message || '')
  return /目标文件夹不存在|未找到目录摘要/.test(detail)
}

function compareSubtitleWorkbenchNames(left, right) {
  return String(left || '').localeCompare(String(right || ''), 'zh-Hans-CN-u-kn-true')
}

function isAudioFileName(name = '') {
  return /\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)
}

function isSubtitleFileName(name = '') {
  return /\.(lrc|srt|ass|ssa|vtt)$/i.test(name)
}

function isSubtitleRelativePath(relativePath = '') {
  const normalized = String(relativePath || '').replace(/\\/g, '/').toLowerCase().replace(/^\/+/, '')
  return normalized === 'subtitles' || normalized.startsWith('subtitles/')
}

function joinFolderPath(basePath, relativePath) {
  if (!relativePath) return basePath
  return `${String(basePath || '').replace(/[\\/]+$/, '')}/${String(relativePath || '').replace(/^[/\\]+/, '')}`
}

function buildTree(items) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => (a.relative_path || '').localeCompare(b.relative_path || ''))
  for (const item of sorted) {
    const parts = (item.relative_path || item.name).split('/').filter(Boolean)
    let children = root
    let path = ''
    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = { id: key, name: parts[index], type: 'dir', relative_path: path, size: 0, modified_time: null, children: [] }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({ ...item, id: `file:${item.path}`, type: 'file' })
  }
  const walk = node => {
    let total = 0
    let latest = null
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += child.size || 0
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }
  root.forEach(node => { if (node.type === 'dir') walk(node) })
  return root
}

function filterTree(nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = String(node.name || '').toLowerCase().includes(keyword) || String(node.relative_path || '').toLowerCase().includes(keyword)
    if (node.type === 'file') {
      if (matched) result.push(node)
      continue
    }
    const children = filterTree(node.children || [], keyword)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree(nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

// 原本这里是个局部 fileIcon，调 element-plus 的 Headset / Picture / Tickets / VideoPlay / Document。
// 现在完全交给 _libraryFileKind helper，走 9 类色盘（与操作记录文件树对齐）。
function fileIcon(name = '') {
  return libraryEntryIconFor({ type: 'file', name })
}

function formatFileSize(bytes) {
  if (bytes === null || bytes === undefined) return '-'
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function clearSubtitleInspectorState() {
  persistSubtitleTaskDraft()
  skipTaskDraftPersistence = true
  subtitleInspectorInfo.value = {
    taskId: '',
    libraryId: '',
    audioLibraryId: '',
    subtitleLibraryId: '',
    folderPath: '',
    subtitleDir: '',
    sourceMode: '',
    audioLoadError: '',
    subtitleLoadError: '',
    totalFiles: 0,
    totalSize: 0
  }
  subtitleInspectorItems.value = []
  subtitleInspectorAudioItems.value = []
  subtitleInspectorExpandedIds.value = new Set()
  subtitleInspectorSelectedIds.value = new Set()
  subtitleInspectorLastSelectedId.value = ''
  resetSubtitleManualMatchState()
  skipTaskDraftPersistence = false
}

async function inspectSubtitleTask(task, options = {}) {
  const { force = false, preserveSnapshotOnMissing = false } = options
  const subtitleDir = getTaskWorkbenchSubtitleDir(task)
  if (!subtitleDir) return
  const inspectSeq = ++subtitleInspectRequestSeq
  if (task?.id && task.id !== selectedTaskId.value) {
    await selectWorkbenchTask(task.id, { inspect: false })
  }
  if (
    !force &&
    subtitleInspectorInfo.value.taskId === task.id &&
    subtitleInspectorInfo.value.subtitleDir === subtitleDir &&
    !subtitleInspectorLoading.value
  ) {
    return
  }

  subtitleInspectorLoading.value = true
  try {
    persistSubtitleTaskDraft()
    const audioLibraryId = task.target_library_id || task.library_id || ''
    const subtitleLibraryId = task.subtitle_library_id || audioLibraryId
    const audioFolderPath = String(task.target_folder_path || task.folder_path || '').trim()
    const [subtitleResult, audioResult] = await Promise.allSettled([
      libraryApi.browserFolderContents(subtitleLibraryId, subtitleDir),
      audioFolderPath ? libraryApi.browserFolderContents(audioLibraryId, audioFolderPath) : Promise.resolve({ items: [] })
    ])
    const subtitleData = subtitleResult.status === 'fulfilled' ? subtitleResult.value : null
    const audioData = audioResult.status === 'fulfilled' ? audioResult.value : { items: [] }
    if (!subtitleData) {
      throw subtitleResult.reason
    }
    if (inspectSeq !== subtitleInspectRequestSeq || (activeTask.value?.id && activeTask.value.id !== task.id)) {
      return
    }
    skipTaskDraftPersistence = true
    subtitleInspectorSearch.value = ''
    subtitleInspectorItems.value = subtitleData.items || []
    subtitleInspectorAudioItems.value = audioData.items || []
    resetSubtitleManualMatchState()
    subtitleInspectorInfo.value = {
      taskId: task.id,
      libraryId: audioLibraryId,
      audioLibraryId,
      subtitleLibraryId,
      folderPath: audioFolderPath,
      subtitleDir: subtitleData.folder_path || subtitleDir,
      sourceMode: task.source_mode || '',
      audioLoadError: audioResult.status === 'rejected'
        ? decodePossibleMojibake(audioResult.reason?.response?.data?.detail || audioResult.reason?.message || '音频目录读取失败')
        : '',
      subtitleLoadError: '',
      totalFiles: subtitleData.total_files || 0,
      totalSize: (subtitleData.items || []).reduce((sum, item) => sum + (item.size || 0), 0)
    }
    const opened = new Set()
    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    subtitleInspectorExpandedIds.value = opened
    subtitleInspectorSelectedIds.value = new Set()
    subtitleInspectorLastSelectedId.value = ''
    try {
      await nextTick()
    } catch (nextTickError) {
      if (nextTickError instanceof TypeError && /parentNode/.test(nextTickError.message || '')) {
        console.warn('[subtitle-inspector] 忽略 Vue 过渡残留错误 (nextTick):', nextTickError.message)
      } else {
        throw nextTickError
      }
    }
    const restored = restoreSubtitleTaskDraft(task.id)
    if (!restored) buildRuleSubtitlePairs({ silent: true })
    skipTaskDraftPersistence = false
    persistSubtitleTaskDraft(task.id)
  } catch (error) {
    if (error instanceof TypeError && /parentNode/.test(error.message || '')) {
      console.warn('[subtitle-inspector] 忽略 Vue 过渡残留错误:', error.message)
    } else {
      const message = decodePossibleMojibake(error.response?.data?.detail || error.message)
      if (inspectSeq !== subtitleInspectRequestSeq || (activeTask.value?.id && activeTask.value.id !== task.id)) {
        return
      }
      if (isSubtitleDirectoryMissingError(error)) {
        const hasCurrentTaskSnapshot = subtitleInspectorInfo.value.taskId === task.id && (
          subtitleInspectorItems.value.length ||
          subtitleInspectorAudioItems.value.length ||
          subtitleManualPairs.value.length
        )
        if (hasCurrentTaskSnapshot) {
          subtitleInspectorInfo.value = {
            ...subtitleInspectorInfo.value,
            subtitleLoadError: message || '字幕目录读取失败'
          }
          if (!preserveSnapshotOnMissing) {
            ElMessage.warning('字幕目录暂时不可用，已保留当前配对快照')
          }
        } else {
          clearSubtitleInspectorState()
          ElMessage.info(task.status === 'processing'
            ? '字幕任务仍在执行，目录生成后会自动可见'
            : '当前字幕目录还未生成，或历史恢复的旧目录已失效')
        }
      } else {
        skipTaskDraftPersistence = true
        subtitleInspectorSearch.value = ''
        subtitleInspectorItems.value = []
        subtitleInspectorAudioItems.value = []
        subtitleInspectorExpandedIds.value = new Set()
        subtitleInspectorSelectedIds.value = new Set()
        subtitleInspectorLastSelectedId.value = ''
        resetSubtitleManualMatchState()
        subtitleInspectorInfo.value = {
          taskId: task.id,
          libraryId: task.target_library_id || task.library_id || '',
          audioLibraryId: task.target_library_id || task.library_id || '',
          subtitleLibraryId: task.subtitle_library_id || task.target_library_id || task.library_id || '',
          folderPath: String(task.target_folder_path || task.folder_path || '').trim(),
          subtitleDir,
          sourceMode: task.source_mode || '',
          audioLoadError: '',
          subtitleLoadError: message || '字幕目录读取失败',
          totalFiles: 0,
          totalSize: 0
        }
        skipTaskDraftPersistence = false
        ElMessage.error('加载字幕目录失败: ' + message)
      }
    }
  } finally {
    skipTaskDraftPersistence = false
    subtitleInspectorLoading.value = false
  }
}

async function reloadSubtitleInspector() {
  if (!getTaskWorkbenchSubtitleDir(activeTask.value)) return
  await inspectSubtitleTask(activeTask.value, { force: true })
}

async function reloadCurrentSubtitleInspectorSnapshot() {
  const taskId = String(subtitleInspectorInfo.value.taskId || activeTask.value?.id || props.taskId || '').trim()
  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || getTaskWorkbenchSubtitleDir(activeTask.value) || '').trim()
  const subtitleLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || activeTask.value?.subtitle_library_id || activeTask.value?.target_library_id || activeTask.value?.library_id || ''
  const audioLibraryId = subtitleInspectorInfo.value.audioLibraryId || activeTask.value?.target_library_id || activeTask.value?.library_id || subtitleLibraryId
  const audioFolderPath = String(subtitleInspectorInfo.value.folderPath || activeTask.value?.target_folder_path || activeTask.value?.folder_path || '').trim()
  if (!subtitleDir || !subtitleLibraryId) return null

  const inspectSeq = ++subtitleInspectRequestSeq
  subtitleInspectorLoading.value = true
  try {
    const [subtitleResult, audioResult] = await Promise.allSettled([
      libraryApi.browserFolderContents(subtitleLibraryId, subtitleDir),
      audioFolderPath ? libraryApi.browserFolderContents(audioLibraryId, audioFolderPath) : Promise.resolve({ items: [] })
    ])
    if (inspectSeq !== subtitleInspectRequestSeq) return false
    if (subtitleResult.status !== 'fulfilled') throw subtitleResult.reason

    const subtitleData = subtitleResult.value || {}
    const audioData = audioResult.status === 'fulfilled' ? (audioResult.value || {}) : { items: [] }
    skipTaskDraftPersistence = true
    subtitleInspectorSearch.value = ''
    subtitleInspectorItems.value = subtitleData.items || []
    subtitleInspectorAudioItems.value = audioData.items || []
    subtitleInspectorInfo.value = {
      ...subtitleInspectorInfo.value,
      taskId,
      libraryId: audioLibraryId || subtitleLibraryId,
      audioLibraryId,
      subtitleLibraryId,
      folderPath: audioFolderPath,
      subtitleDir: subtitleData.folder_path || subtitleDir,
      sourceMode: activeTask.value?.source_mode || subtitleInspectorInfo.value.sourceMode || '',
      audioLoadError: audioResult.status === 'rejected'
        ? decodePossibleMojibake(audioResult.reason?.response?.data?.detail || audioResult.reason?.message || '音频目录读取失败')
        : '',
      subtitleLoadError: '',
      totalFiles: subtitleData.total_files || 0,
      totalSize: (subtitleData.items || []).reduce((sum, item) => sum + (item.size || 0), 0)
    }
    const opened = new Set()
    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    subtitleInspectorExpandedIds.value = opened
    subtitleInspectorSelectedIds.value = new Set()
    subtitleInspectorLastSelectedId.value = ''
    skipTaskDraftPersistence = false
    persistSubtitleTaskDraft(taskId)
    return true
  } catch (error) {
    const message = decodePossibleMojibake(error.response?.data?.detail || error.message)
    subtitleInspectorInfo.value = {
      ...subtitleInspectorInfo.value,
      subtitleLoadError: message || '字幕目录读取失败'
    }
    return false
  } finally {
    skipTaskDraftPersistence = false
    if (inspectSeq === subtitleInspectRequestSeq) {
      subtitleInspectorLoading.value = false
    }
  }
}

async function refreshSubtitleInspectorAfterManualApply(taskId) {
  skipTaskDraftPersistence = true
  resetSubtitleManualMatchState()
  clearSubtitleTaskDraft(taskId)
  skipTaskDraftPersistence = false
  await refreshTaskStatus(false, { inspect: false, silent: true })
  const refreshedTask = linkedTasks.value.find(task => task.id === taskId) || activeTask.value
  if (refreshedTask?.id) {
    activeTask.value = refreshedTask
    selectedTaskId.value = refreshedTask.id
  }
  if (getTaskWorkbenchSubtitleDir(refreshedTask)) {
    await inspectSubtitleTask(refreshedTask, { force: true, preserveSnapshotOnMissing: true })
  } else {
    await reloadCurrentSubtitleInspectorSnapshot()
  }
}

function onSubtitleInspectorSearchInput() {
  if (subtitleInspectorSearch.value.trim()) expandSubtitleInspectorTree()
}

function toggleSubtitleInspectorExpand(node) {
  const next = new Set(subtitleInspectorExpandedIds.value)
  next.has(node.id) ? next.delete(node.id) : next.add(node.id)
  subtitleInspectorExpandedIds.value = next
}

function expandSubtitleInspectorTree() {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => {
    if (node.type === 'dir') {
      next.add(node.id)
      walk(node.children || [])
    }
  })
  walk(subtitleInspectorFilteredRoot.value)
  subtitleInspectorExpandedIds.value = next
}

function collapseSubtitleInspectorTree() {
  subtitleInspectorExpandedIds.value = new Set()
}

function resolveSubtitleTreeIcon(row) {
  if (row?.type === 'dir') {
    return subtitleInspectorExpandedIds.value.has(row.id) ? FolderOpen : Folder
  }
  return libraryEntryIconFor(row)
}

// 同步提供推荐着色（交给消费方以 inline :style 上色）
function resolveSubtitleTreeIconStyle(row) {
  const meta = libraryEntryMetaFor(row)
  return {
    color: meta.color,
    fill: meta.fillIcon ? 'currentColor' : 'none',
  }
}

function getSubtitleInspectorSelectableIds() {
  return subtitleInspectorSelectableRows.value.map(row => row.id)
}

function selectSubtitleInspectorRange(targetId, preserveExisting = true) {
  const rowIds = getSubtitleInspectorSelectableIds()
  const targetIndex = rowIds.indexOf(targetId)
  if (targetIndex < 0) return
  const anchorId = subtitleInspectorLastSelectedId.value && rowIds.includes(subtitleInspectorLastSelectedId.value)
    ? subtitleInspectorLastSelectedId.value
    : targetId
  const anchorIndex = rowIds.indexOf(anchorId)
  const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex]
  const next = preserveExisting ? new Set(subtitleInspectorSelectedIds.value) : new Set()
  rowIds.slice(start, end + 1).forEach(id => next.add(id))
  subtitleInspectorSelectedIds.value = next
  subtitleInspectorLastSelectedId.value = targetId
}

function toggleSubtitleInspectorSelect(row, event = null) {
  if (subtitleInspectorBusy.value || !row?.id) return
  if (event?.shiftKey) {
    selectSubtitleInspectorRange(row.id, true)
    return
  }
  const next = new Set(subtitleInspectorSelectedIds.value)
  next.has(row.id) ? next.delete(row.id) : next.add(row.id)
  subtitleInspectorSelectedIds.value = next
  subtitleInspectorLastSelectedId.value = row.id
}

function toggleAllSubtitleInspectorRows() {
  if (subtitleInspectorBusy.value) return
  const checked = !subtitleInspectorAllSelected.value
  subtitleInspectorSelectedIds.value = checked
    ? new Set(subtitleInspectorSelectableRows.value.map(row => row.id))
    : new Set()
  subtitleInspectorLastSelectedId.value = checked ? subtitleInspectorSelectableRows.value.at(-1)?.id || '' : ''
}

function clearSubtitleInspectorSelection() {
  if (subtitleInspectorBusy.value) return
  subtitleInspectorSelectedIds.value = new Set()
  subtitleInspectorLastSelectedId.value = ''
}

function handleSubtitleInspectorRowClick(row, event) {
  if (subtitleInspectorBusy.value || !row?.id) return
  toggleSubtitleInspectorSelect(row, event)
}

function resolveSubtitleEntryPath(row) {
  const rowPath = String(row?.path || '').replace(/\\/g, '/')
  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').replace(/\\/g, '/')
  if (rowPath && subtitleDir && rowPath.startsWith(subtitleDir)) return row.path
  return joinFolderPath(subtitleInspectorInfo.value.subtitleDir, row.relative_path || row.name || '')
}

function applySubtitleRenameResultToSnapshot(rowPath, newName, result = {}) {
  const normalizedOldPath = String(rowPath || '').replace(/\\/g, '/')
  const normalizedNewPath = String(result?.new_path || result?.path || '').trim()
  const nextName = String(newName || '').trim()
  if (!normalizedOldPath || !nextName) return
  const replaceBasename = (value) => {
    const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean)
    if (!parts.length) return nextName
    parts[parts.length - 1] = nextName
    return parts.join('/')
  }

  const updateItem = (item) => {
    const itemPath = String(item?.path || '').replace(/\\/g, '/')
    if (itemPath !== normalizedOldPath) return item
    const nextPath = normalizedNewPath || replaceBasename(item.path)
    return {
      ...item,
      path: nextPath,
      name: nextName,
      display_name: item.display_name === item.name ? nextName : item.display_name,
      relative_path: item.relative_path ? replaceBasename(item.relative_path) : nextName
    }
  }

  subtitleInspectorItems.value = subtitleInspectorItems.value.map(updateItem)
}

function openSubtitleRenameDialog(row) {
  if (row?.type !== 'file') return
  subtitleRenameForm.value = { currentName: row.name, newName: row.name, path: row.path }
  subtitleRenameDialogVisible.value = true
}

async function confirmSubtitleRename() {
  if (!subtitleRenameForm.value.newName || subtitleRenameForm.value.newName === subtitleRenameForm.value.currentName) {
    ElMessage.warning('请输入不同的新名称')
    return
  }

  subtitleRenameLoading.value = true
  try {
    const result = await libraryApi.browserRename(subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId, subtitleRenameForm.value.path, subtitleRenameForm.value.newName)
    applySubtitleRenameResultToSnapshot(subtitleRenameForm.value.path, subtitleRenameForm.value.newName, result)
    subtitleRenameDialogVisible.value = false
    ElMessage.success('字幕文件重命名成功')
    const reloaded = await reloadCurrentSubtitleInspectorSnapshot()
    if (reloaded === null) await reloadSubtitleInspector()
  } catch (error) {
    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleRenameLoading.value = false
  }
}

function buildDeletePreviewMessage(preview) {
  if (preview?.size_disabled) {
    return `确定删除 ${preview?.name || '该项'} 吗？\n\n此操作不可恢复！`
  }
  return `确定删除 ${preview?.name || '该项'} 吗？\n大小: ${formatFileSize(preview?.size)}\n\n此操作不可恢复！`
}

async function deleteSubtitleTreeEntry(row) {
  if (subtitleInspectorBusy.value) return
  const path = resolveSubtitleEntryPath(row)
  const inspectorLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId
  try {
    const preview = await libraryApi.browserDelete(inspectorLibraryId, path, false)
    await showSystemConfirm({
      title: '删除确认',
      message: buildDeletePreviewMessage(preview),
      confirmText: '确定删除',
      cancelText: '取消',
      tone: 'danger'
    })
    subtitleInspectorDeleting.value = true
    try {
      await libraryApi.browserDelete(inspectorLibraryId, path, true)
      ElMessage.success('删除成功')
      const reloaded = await reloadCurrentSubtitleInspectorSnapshot()
      if (reloaded === null) await reloadSubtitleInspector()
    } finally {
      subtitleInspectorDeleting.value = false
    }
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function batchDeleteSubtitleTreeEntries() {
  const rows = [...subtitleInspectorSelectedRows.value]
  if (!rows.length) {
    ElMessage.warning('请先选择要删除的字幕文件或目录')
    return
  }
  const sortedRows = rows.sort((left, right) => (right.path || right.relative_path || '').length - (left.path || left.relative_path || '').length)
  try {
    await showSystemConfirm({
      title: '批量删除确认',
      message: `确定批量删除 ${sortedRows.length} 项字幕文件/目录吗？此操作不可恢复。`,
      confirmText: '确定删除',
      cancelText: '取消',
      tone: 'danger'
    })
  } catch (_) {
    return
  }

  subtitleInspectorDeleting.value = true
  try {
    const targetLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId
    const paths = sortedRows.map(row => resolveSubtitleEntryPath(row)).filter(Boolean)
    const result = await libraryApi.browserBatchDelete(targetLibraryId, paths, true, {
      batchId: `subtitle-tree-delete-${Date.now()}`
    })
    const failed = result?.failed_paths || []
    if (failed.length) {
      throw new Error(failed[0]?.error || failed[0]?.path || '部分字幕文件删除失败')
    }
    clearSubtitleInspectorSelection()
    ElMessage.success(`已删除 ${sortedRows.length} 项`)
    const reloaded = await reloadCurrentSubtitleInspectorSnapshot()
    if (reloaded === null) await reloadSubtitleInspector()
  } catch (error) {
    ElMessage.error('删除失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))
  } finally {
    subtitleInspectorDeleting.value = false
  }
}

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function normalizeSubtitleMatchName(value = '') {
  return stripTrailingAudioExtension(String(value || '').replace(/\.[^.]+$/, ''))
    .toLowerCase()
    .replace(/^(track|trk|tr)[_\-\s]*/i, '')
    .replace(/[\s_\-]+/g, '')
    .replace(/[^\w\u4e00-\u9fff\u3040-\u30ff]+/g, '')
}

function normalizeSubtitlePairPath(value = '') {
  return String(value || '').trim().replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/+$/, '').toLowerCase()
}

function buildSubtitlePairPathKeys(item = {}) {
  const keys = new Set()
  const path = normalizeSubtitlePairPath(item.path || item.subtitle_path || '')
  const relativePath = normalizeSubtitlePairPath(item.relative_path || item.subtitle_relative_path || '')
  const name = normalizeSubtitlePairPath(item.name || item.subtitle_name || '')
  if (path) keys.add(`path:${path}`)
  if (relativePath) keys.add(`rel:${relativePath}`)
  if (name) keys.add(`name:${name}`)
  return keys
}

function isSameSubtitlePairItem(item, pair) {
  const itemKeys = buildSubtitlePairPathKeys(item)
  const pairKeys = buildSubtitlePairPathKeys({
    path: pair?.subtitle_path,
    relative_path: pair?.subtitle_relative_path,
    name: pair?.subtitle_name
  })
  for (const key of pairKeys) {
    if (itemKeys.has(key)) return true
  }
  return false
}

function extractSubtitleTrackNumber(value = '') {
  const match = String(value || '').match(/(?:^|[^0-9])(?:tr|track)?[_\-\s]*0*([0-9]{1,3})(?![0-9])/i)
  return match ? Number(match[1]) : null
}

function clearSubtitleSequenceSelection() {
  subtitleSequenceSelection.value = { audioPaths: [], subtitlePaths: [] }
}

function resetSubtitleManualMatchState() {
  subtitleInspectorAudioSearch.value = ''
  subtitleInspectorSubtitleSearch.value = ''
  subtitleAudioFilterMode.value = 'all'
  subtitleSubtitleFilterMode.value = 'all'
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
  subtitleSequenceMode.value = false
  clearSubtitleSequenceSelection()
  subtitleLastPairBuildMode.value = ''
  subtitleManualPairs.value = []
  subtitleSelectedManualPairId.value = ''
}

function toggleSubtitleSequencePath(kind, path) {
  if (!path) return
  const current = kind === 'audio'
    ? [...subtitleSequenceSelection.value.audioPaths]
    : [...subtitleSequenceSelection.value.subtitlePaths]
  const existingIndex = current.indexOf(path)
  if (existingIndex >= 0) current.splice(existingIndex, 1)
  else current.push(path)
  subtitleSequenceSelection.value = {
    ...subtitleSequenceSelection.value,
    [kind === 'audio' ? 'audioPaths' : 'subtitlePaths']: current
  }
}

function getSubtitleSequenceIndex(kind, path) {
  const list = kind === 'audio' ? subtitleSequenceSelection.value.audioPaths : subtitleSequenceSelection.value.subtitlePaths
  const index = list.indexOf(path)
  return index >= 0 ? index + 1 : 0
}

function selectSubtitleAudio(audio) {
  if (subtitleSequenceMode.value) {
    toggleSubtitleSequencePath('audio', audio?.path || '')
    return
  }
  subtitleMatchSelection.value = {
    ...subtitleMatchSelection.value,
    audioPath: audio?.path || ''
  }
}

function selectSubtitleFile(subtitle) {
  if (subtitleSequenceMode.value) {
    toggleSubtitleSequencePath('subtitle', subtitle?.path || '')
    return
  }
  subtitleMatchSelection.value = {
    ...subtitleMatchSelection.value,
    subtitlePath: subtitle?.path || ''
  }
}

function buildSubtitlePairTargets(audio, subtitle) {
  const audioExt = String(audio?.name || '').match(/\.[^.]+$/)?.[0] || ''
  const subtitleExt = String(subtitle?.name || '').match(/\.[^.]+$/)?.[0] || '.vtt'
  const subtitleBase = stripTrailingAudioExtension(String(subtitle?.name || '').replace(/\.[^.]+$/, ''))
  const audioBase = String(audio?.name || '').replace(/\.[^.]+$/, '')
  const targetBase = subtitleOptions.value.namingStrategy === 'subtitle' ? subtitleBase : audioBase
  return {
    targetBase,
    targetAudioName: `${targetBase}${audioExt}`,
    targetSubtitleName: `${targetBase}${subtitleExt}`
  }
}

function createSubtitlePair(audio, subtitle, options = {}) {
  const targets = buildSubtitlePairTargets(audio, subtitle)
  return {
    id: `${audio.path}::${subtitle.path}`,
    audio_path: audio.path,
    audio_name: audio.name,
    audio_relative_path: audio.relative_path || audio.name,
    subtitle_path: subtitle.path,
    subtitle_name: subtitle.name,
    subtitle_relative_path: subtitle.relative_path || subtitle.name,
    target_base: targets.targetBase,
    target_audio_name: targets.targetAudioName,
    target_subtitle_name: targets.targetSubtitleName,
    confidenceLevel: options.confidenceLevel || 'medium',
    matchReason: options.matchReason || '手动配对'
  }
}

function syncSubtitlePairTargetNames() {
  subtitleManualPairs.value = subtitleManualPairs.value.map(pair => ({
    ...pair,
    ...buildSubtitlePairTargets(
      { name: pair.audio_name, path: pair.audio_path, relative_path: pair.audio_relative_path },
      { name: pair.subtitle_name, path: pair.subtitle_path, relative_path: pair.subtitle_relative_path }
    )
  }))
}

function addSubtitleManualPair() {
  const audio = subtitleInspectorAudioFiles.value.find(item => item.path === subtitleMatchSelection.value.audioPath)
  const subtitle = subtitleInspectorSubtitleFiles.value.find(item => item.path === subtitleMatchSelection.value.subtitlePath)
  if (!audio || !subtitle) {
    ElMessage.warning('请先分别选择音频和字幕')
    return
  }

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.audio_path !== audio.path && pair.subtitle_path !== subtitle.path)
  subtitleManualPairs.value.push({
    ...createSubtitlePair(audio, subtitle, { confidenceLevel: 'medium', matchReason: '手动指定' })
  })
  subtitleLastPairBuildMode.value = 'manual'
  subtitleSelectedManualPairId.value = `${audio.path}::${subtitle.path}`
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
}

function removeSubtitleManualPair(pairId) {
  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.id !== pairId)
  if (subtitleSelectedManualPairId.value === pairId) subtitleSelectedManualPairId.value = ''
}

function buildOrderedSubtitlePairs() {
  const audioList = filteredSubtitleInspectorAudioFiles.value
  const subtitleList = filteredSubtitleInspectorSubtitleFiles.value
  const pairCount = Math.min(audioList.length, subtitleList.length)
  if (!pairCount) {
    ElMessage.warning('当前没有可用于顺序配对的音频或字幕')
    return
  }
  const nextPairs = []
  for (let index = 0; index < pairCount; index++) {
    nextPairs.push(createSubtitlePair(audioList[index], subtitleList[index], { confidenceLevel: 'low', matchReason: '顺序配对' }))
  }
  subtitleManualPairs.value = nextPairs
  subtitleLastPairBuildMode.value = 'ordered'
  subtitleSelectedManualPairId.value = nextPairs[0]?.id || ''
}

function buildSequenceSubtitlePairs() {
  const audioList = subtitleSequenceSelection.value.audioPaths
    .map(path => subtitleInspectorAudioFiles.value.find(item => item.path === path))
    .filter(Boolean)
  const subtitleList = subtitleSequenceSelection.value.subtitlePaths
    .map(path => subtitleInspectorSubtitleFiles.value.find(item => item.path === path))
    .filter(Boolean)

  const pairCount = Math.min(audioList.length, subtitleList.length)

  if (!pairCount) {
    ElMessage.warning('请先按顺序点选至少 1 个音频和 1 个字幕')
    return
  }

  const pairedAudioList = audioList.slice(0, pairCount)
  const pairedSubtitleList = subtitleList.slice(0, pairCount)
  const nextPairs = []
  for (let index = 0; index < pairCount; index++) {
    nextPairs.push(createSubtitlePair(pairedAudioList[index], pairedSubtitleList[index], {
      confidenceLevel: 'medium',
      matchReason: '点选顺序'
    }))
  }

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => (
    !pairedAudioList.some(item => item.path === pair.audio_path) &&
    !pairedSubtitleList.some(item => item.path === pair.subtitle_path)
  ))
  subtitleManualPairs.value.push(...nextPairs)
  subtitleLastPairBuildMode.value = 'sequence'
  subtitleSelectedManualPairId.value = nextPairs[0]?.id || subtitleSelectedManualPairId.value
  clearSubtitleSequenceSelection()
  subtitleSequenceMode.value = false
}

function buildSequenceOrOrderedSubtitlePairs() {
  if (subtitleSequenceMode.value) {
    buildSequenceSubtitlePairs()
    return
  }
  buildOrderedSubtitlePairs()
}

function buildRuleSubtitlePairs({ silent = false } = {}) {
  const audioList = [...subtitleInspectorAudioFiles.value]
  const subtitleList = [...subtitleInspectorSubtitleFiles.value]
  const usedSubtitlePaths = new Set()
  const pairs = []

  const subtitleByExact = new Map()
  const subtitleByNormalized = new Map()
  const subtitleByTrack = new Map()
  for (const subtitle of subtitleList) {
    const name = String(subtitle.name || '')
    const baseName = stripTrailingAudioExtension(name.replace(/\.[^.]+$/, ''))
    const normalized = normalizeSubtitleMatchName(name)
    const trackNumber = extractSubtitleTrackNumber(name)
    subtitleByExact.set(baseName.toLowerCase(), subtitleByExact.get(baseName.toLowerCase()) || [])
    subtitleByExact.get(baseName.toLowerCase()).push(subtitle)
    if (normalized) {
      subtitleByNormalized.set(normalized, subtitleByNormalized.get(normalized) || [])
      subtitleByNormalized.get(normalized).push(subtitle)
    }
    if (trackNumber !== null) {
      subtitleByTrack.set(trackNumber, subtitleByTrack.get(trackNumber) || [])
      subtitleByTrack.get(trackNumber).push(subtitle)
    }
  }

  function consumeCandidate(candidates = []) {
    for (const item of candidates) {
      if (usedSubtitlePaths.has(item.path)) continue
      usedSubtitlePaths.add(item.path)
      return item
    }
    return null
  }

  for (const audio of audioList) {
    const audioName = String(audio.name || '')
    const audioBase = audioName.replace(/\.[^.]+$/, '')
    const audioNormalized = normalizeSubtitleMatchName(audioName)
    const audioTrack = extractSubtitleTrackNumber(audioName)
    let matchedSubtitle = consumeCandidate(subtitleByExact.get(audioBase.toLowerCase()))
    let confidenceLevel = 'high'
    let matchReason = '精确文件名'
    if (!matchedSubtitle && audioTrack !== null) {
      matchedSubtitle = consumeCandidate(subtitleByTrack.get(audioTrack))
      if (matchedSubtitle) {
        confidenceLevel = 'high'
        matchReason = `轨道号 ${audioTrack}`
      }
    }
    if (!matchedSubtitle && audioNormalized) {
      matchedSubtitle = consumeCandidate(subtitleByNormalized.get(audioNormalized))
      if (matchedSubtitle) {
        confidenceLevel = 'medium'
        matchReason = '规范化标题'
      }
    }
    if (!matchedSubtitle) continue
    pairs.push(createSubtitlePair(audio, matchedSubtitle, { confidenceLevel, matchReason }))
  }

  if (!pairs.length) {
    if (!silent) ElMessage.warning('没有生成可用的规则预匹配结果')
    return false
  }
  subtitleManualPairs.value = pairs
  subtitleLastPairBuildMode.value = 'auto'
  subtitleSelectedManualPairId.value = pairs[0]?.id || ''
  return true
}

function normalizeAIPairConfidenceLevel(score) {
  const numeric = Number(score)
  if (!Number.isFinite(numeric)) return 'medium'
  const threshold = Number(subtitleOptions.value.aiConfidenceThreshold || 85)
  if (numeric >= Math.max(90, threshold)) return 'high'
  if (numeric < threshold) return 'low'
  return 'medium'
}

function buildSubtitlePairFromAIMatch(match, audioByPath, subtitleByPath, subtitleByName) {
  const audioPath = String(match?.audio_path || '')
  const subtitlePath = String(match?.subtitle_path || '')
  const audio = audioByPath.get(audioPath)
  const subtitle = subtitleByPath.get(subtitlePath) || subtitleByName.get(String(match?.subtitle_name || ''))
  if (!audio || !subtitle) return null
  return createSubtitlePair(audio, subtitle, {
    confidenceLevel: normalizeAIPairConfidenceLevel(match?.ai_confidence ?? match?.match_score),
    matchReason: `AI 草稿${match?.match_reason ? `：${match.match_reason}` : ''}`
  })
}

async function buildAISubtitlePairs() {
  if (subtitleAutoPairing.value) return false
  const audioList = [...subtitleInspectorAudioFiles.value]
  const subtitleList = [...subtitleInspectorSubtitleFiles.value]
  if (!audioList.length || !subtitleList.length) {
    ElMessage.warning('当前没有可用于 AI 配对的音频或字幕')
    return false
  }

  subtitleAutoPairing.value = true
  try {
    const data = await aiSubtitleMatchApi.preview({
      audioFiles: audioList.map(item => ({
        path: item.path,
        name: item.name,
        relative_path: item.relative_path || item.name
      })),
      subtitleFiles: subtitleList.map(item => ({
        path: item.path,
        name: item.name,
        relative_path: item.relative_path || item.name
      })),
      aiMatchMode: 'ai_assist',
      namingStrategy: subtitleOptions.value.namingStrategy,
      enableMetadataMatch: false,
      useFilterRules: subtitleOptions.value.useFilterRules,
      subtitleFilterRules: sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules),
      aiConfidenceThreshold: subtitleOptions.value.aiConfidenceThreshold
    })

    if (data?.status === 'disabled' || data?.status === 'skipped' || data?.success === false) {
      if (data?.error?.message) ElMessage.warning(`AI 配对不可用：${data.error.message}`)
      else ElMessage.warning('AI 配对不可用')
      return false
    }

    const audioByPath = new Map(audioList.map(item => [String(item.path || ''), item]))
    const subtitleByPath = new Map(subtitleList.map(item => [String(item.path || ''), item]))
    const subtitleByName = new Map()
    subtitleList.forEach(item => {
      const name = String(item.name || '')
      if (name && !subtitleByName.has(name)) subtitleByName.set(name, item)
    })

    const pairs = []
    const usedAudio = new Set()
    const usedSubtitle = new Set()
    for (const match of data?.match_result?.matches || []) {
      const pair = buildSubtitlePairFromAIMatch(match, audioByPath, subtitleByPath, subtitleByName)
      if (!pair || usedAudio.has(pair.audio_path) || usedSubtitle.has(pair.subtitle_path)) continue
      usedAudio.add(pair.audio_path)
      usedSubtitle.add(pair.subtitle_path)
      pairs.push(pair)
    }

    if (!pairs.length) {
      ElMessage.warning('AI 没有生成可用配对草稿')
      return false
    }

    subtitleManualPairs.value = pairs
    subtitleLastPairBuildMode.value = 'ai'
    subtitleSelectedManualPairId.value = pairs[0]?.id || ''
    ElMessage.success(`AI 已生成 ${pairs.length} 组配对草稿`)
    return true
  } catch (error) {
    ElMessage.warning('AI 配对失败: ' + (error.response?.data?.detail || error.message))
    return false
  } finally {
    subtitleAutoPairing.value = false
  }
}

async function buildAutoSubtitlePairs(options = {}) {
  const { preferAi = true, silent = false } = options || {}
  if (preferAi && await buildAISubtitlePairs()) return true
  return buildRuleSubtitlePairs({ silent })
}

function clearSubtitleManualPairs() {
  subtitleManualPairs.value = []
  subtitleLastPairBuildMode.value = ''
  subtitleSelectedManualPairId.value = ''
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
  clearSubtitleSequenceSelection()
}

function isAudioPaired(audioPath) {
  return subtitleManualPairs.value.some(pair => pair.audio_path === audioPath)
}

function isSubtitlePaired(subtitlePath) {
  return subtitleManualPairs.value.some(pair => pair.subtitle_path === subtitlePath)
}

function findSubtitlePairByAudioPath(audioPath) {
  return subtitleManualPairs.value.find(pair => pair.audio_path === audioPath) || null
}

function findSubtitlePairBySubtitlePath(subtitlePath) {
  return subtitleManualPairs.value.find(pair => pair.subtitle_path === subtitlePath) || null
}

function isAudioSuspicious(audioPath) {
  return findSubtitlePairByAudioPath(audioPath)?.confidenceLevel === 'low'
}

function isSubtitleSuspicious(subtitlePath) {
  return findSubtitlePairBySubtitlePath(subtitlePath)?.confidenceLevel === 'low'
}

function getSubtitlePairConfidenceLabel(level) {
  if (level === 'high') return '高置信'
  if (level === 'low') return '低置信'
  return '中等'
}

function joinPath(basePath, name) {
  return `${String(basePath || '').replace(/[\\/]+$/, '')}/${String(name || '').replace(/^[/\\]+/, '')}`
}

const canOpenSubtitleInspectorFilterDeleteDialog = computed(() => Boolean(
  (subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId) &&
  String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim()
))

async function applySubtitleCleanup() {
  const currentTaskId = activeTask.value?.id || props.taskId
  if (!currentTaskId) return

  subtitleCleanupLoading.value = true
  try {
    const data = await subtitleImportApi.cleanupTask(currentTaskId)
    subtitleCleanupSummary.value = buildCleanupSummary(data.result || {})
    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    ElMessage.success('当前工作台字幕清理完成')
  } catch (error) {
    ElMessage.error('执行字幕清理失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleCleanupLoading.value = false
  }
}

async function applySubtitleManualPairs() {
  if (!subtitleManualPairs.value.length) {
    ElMessage.warning('请先添加至少一组配对')
    return
  }

  const audioLibraryId = subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId
  const subtitleLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || audioLibraryId
  const appliedPairCount = subtitleManualPairs.value.length
  const unusedSubtitleRows = subtitleInspectorSubtitleFiles.value.filter(
    item => !subtitleManualPairs.value.some(pair => isSameSubtitlePairItem(item, pair))
  )
  const unusedSubtitlePathSet = new Set(unusedSubtitleRows.flatMap(item => [...buildSubtitlePairPathKeys(item)]))
  if (unusedSubtitleRows.length >= subtitleInspectorSubtitleFiles.value.length) {
    ElMessage.error('配对结果没有命中当前工作台字幕，已阻止删除全部字幕')
    return
  }

  const audioConflicts = subtitleManualPairs.value.filter(pair => {
    const existing = subtitleInspectorAudioFiles.value.find(item => item.name === pair.target_audio_name)
    return existing && existing.path !== pair.audio_path
  })
  if (audioConflicts.length) {
    ElMessage.error(`存在目标音频名冲突，无法直接应用：${audioConflicts[0].target_audio_name}`)
    return
  }

  const subtitleConflicts = subtitleManualPairs.value.filter(pair => {
    const existing = subtitleInspectorSubtitleFiles.value.find(item => item.name === pair.target_subtitle_name)
    if (existing && isSameSubtitlePairItem(existing, pair)) return false
    if (existing) {
      for (const key of buildSubtitlePairPathKeys(existing)) {
        if (unusedSubtitlePathSet.has(key)) return false
      }
    }
    return existing && !isSameSubtitlePairItem(existing, pair)
  })
  if (subtitleConflicts.length) {
    ElMessage.error(`存在目标字幕名冲突，无法直接应用：${subtitleConflicts[0].target_subtitle_name}`)
    return
  }

  const namingStrategyLabel = subtitleOptions.value.namingStrategy === 'subtitle' ? '以字幕名为准' : '以音频名为准'
  try {
    await showSystemConfirm({
      title: '应用配对确认',
      message: `确定处理 ${subtitleManualPairs.value.length} 组配对结果吗？\n\n同名依据：${namingStrategyLabel}${unusedSubtitleRows.length ? `\n当前未使用的 ${unusedSubtitleRows.length} 个原始字幕会一并删除。` : ''}\n确认后会先在工作区完成重命名，再导入目标库存。`,
      confirmText: '重命名并导入',
      cancelText: '取消',
      tone: 'warning'
    })
  } catch (_) {
    return
  }

  subtitlePairApplying.value = true
  const phaseOneRenamed = []
  const phaseTwoRenamed = []
  try {
    const currentSubtitleFiles = [...subtitleInspectorSubtitleFiles.value]
    const resolveCurrentSubtitleSourcePath = (pair) => {
      const exactMatch = currentSubtitleFiles.find(item => isSameSubtitlePairItem(item, pair))
      if (exactMatch?.path) return exactMatch.path
      const sameNameMatches = currentSubtitleFiles.filter(item => item.name === pair.subtitle_name)
      if (sameNameMatches.length === 1) return sameNameMatches[0].path
      const sameRelativeMatches = currentSubtitleFiles.filter(item => (item.relative_path || item.name) === pair.subtitle_relative_path)
      if (sameRelativeMatches.length === 1) return sameRelativeMatches[0].path
      return pair.subtitle_path
    }

    const operations = subtitleManualPairs.value.flatMap(pair => {
      const next = []
      if (pair.audio_name !== pair.target_audio_name) {
        next.push({ kind: 'audio', source_path: pair.audio_path, current_name: pair.audio_name, target_name: pair.target_audio_name })
      }
      if (pair.subtitle_name !== pair.target_subtitle_name) {
        next.push({ kind: 'subtitle', source_path: resolveCurrentSubtitleSourcePath(pair), current_name: pair.subtitle_name, target_name: pair.target_subtitle_name })
      }
      return next
    })

    const phaseOne = operations
      .filter(item => item.current_name !== item.target_name)
      .map((pair, index) => ({
        ...pair,
        temp_name: `__manual_match_${pair.kind}_${String(index + 1).padStart(3, '0')}_${Date.now()}.tmp${pair.current_name.match(/\.[^.]+$/)?.[0] || ''}`
      }))

    // ============================================================
    //  应用配对（性能彻底重做）：
    //
    //  之前：30 对配对 = phase1 30 次串行 rename + phase2 30 次串行 rename
    //        + phase3 N 次串行 delete = 60+ 次 HTTP 往返 + 60+ 次后端
    //        数据库 commit + 60+ 次清搜索缓存 + 60+ 次 stats_log 写文件。
    //        群晖 Docker 上单条耗时 50-300ms，整体 5-30 秒。
    //
    //  现在：phase1 / phase2 各 1 次 batchRename API 调用（按 library 分桶最多
    //        2 次），后端在一个事务里完成所有 rename + 1 次索引同步 + 1 次
    //        缓存清理。整体降到 0.5-2 秒。
    //
    //  仍然保留：phase1→phase2 之间的串行（phase2 依赖 phase1 的 temp_path）；
    //          phase3 删除走并发（删除接口暂无 batch endpoint，延后再批化）。
    // ============================================================
    const groupByLibrary = (operations) => {
      const buckets = new Map()
      for (const op of operations) {
        const libId = op.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        if (!buckets.has(libId)) buckets.set(libId, [])
        buckets.get(libId).push(op)
      }
      return buckets
    }

    // 把 batch 返回的 results 按"原始 items 索引"建表，方便容忍部分失败 + 错位回填
    const buildResultMap = (result) => {
      const map = new Map()
      ;(result?.results || []).forEach((r, fallbackIndex) => {
        if (!r) return
        const resultIndex = Number(r.index)
        const index = Number.isInteger(resultIndex) ? resultIndex : fallbackIndex
        if (!map.has(index)) map.set(index, r)
      })
      return map
    }

    const getBatchRenameFailedItems = (result) => {
      const failed = [
        ...(Array.isArray(result?.failed) ? result.failed : []),
        ...(Array.isArray(result?.failed_items) ? result.failed_items : [])
      ]
      const seen = new Set()
      return failed.filter(item => {
        const key = `${item?.index ?? ''}::${item?.path || item?.source_path || ''}::${item?.error || ''}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
    }

    const assertBatchRenameSucceeded = (result, phaseLabel) => {
      const failedFirst = getBatchRenameFailedItems(result)[0]
      if (failedFirst) {
        throw new Error(`${phaseLabel}失败：${failedFirst.error || '未知错误'}（${failedFirst.path || failedFirst.source_path || ''}）`)
      }
    }

    const scheduleFinalIndexMoves = (renamedPairs) => {
      const buckets = groupByLibrary(renamedPairs || [])
      const jobs = []
      for (const [libraryId, bucketPairs] of buckets) {
        const moves = bucketPairs
          .map(pair => ({ source: pair.source_path, destination: pair.final_path }))
          .filter(item => item.source && item.destination && item.source !== item.destination)
        if (moves.length) jobs.push(libraryApi.browserNotifyIndexMoves(libraryId, moves))
      }
      if (!jobs.length) return
      Promise.allSettled(jobs).then(results => {
        const failed = results.find(item => item.status === 'rejected')
        if (failed) console.warn('字幕补配最终索引移动调度失败', failed.reason)
      })
    }

    // —— Phase 1：source_path → temp_name
    const phaseOneBuckets = groupByLibrary(phaseOne)
    for (const [libraryId, bucketPairs] of phaseOneBuckets) {
      const items = bucketPairs.map(pair => ({ path: pair.source_path, new_name: pair.temp_name }))
      const result = await libraryApi.browserBatchRename(libraryId, items, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair',
        skipIndexMutation: true
      })
      const resultMap = buildResultMap(result)
      // 先回填成功项到 phaseOneRenamed，确保后续 throw 时回滚能找到这些已 rename 的 pair
      bucketPairs.forEach((pair, i) => {
        const r = resultMap.get(i)
        if (r?.new_path) {
          pair.temp_path = r.new_path
          phaseOneRenamed.push(pair)
        }
      })
      assertBatchRenameSucceeded(result, '重命名为临时名')
      const missingTempPath = bucketPairs.find(pair => !pair.temp_path)
      if (missingTempPath) {
        throw new Error(`重命名为临时名失败：后端未返回新路径（${missingTempPath.source_path || missingTempPath.current_name || ''}）`)
      }
    }

    // —— Phase 2：temp_path → target_name
    const phaseTwoBuckets = groupByLibrary(phaseOne)
    for (const [libraryId, bucketPairs] of phaseTwoBuckets) {
      const items = bucketPairs.map(pair => ({ path: pair.temp_path, new_name: pair.target_name }))
      const result = await libraryApi.browserBatchRename(libraryId, items, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair',
        skipIndexMutation: true
      })
      const resultMap = buildResultMap(result)
      bucketPairs.forEach((pair, i) => {
        const r = resultMap.get(i)
        if (r?.new_path) {
          pair.final_path = r.new_path
          phaseTwoRenamed.push(pair)
        }
      })
      assertBatchRenameSucceeded(result, '重命名为目标名')
      const missingFinalPath = bucketPairs.find(pair => !pair.final_path)
      if (missingFinalPath) {
        throw new Error(`重命名为目标名失败：后端未返回新路径（${missingFinalPath.temp_path || missingFinalPath.target_name || ''}）`)
      }
    }

    // —— Phase 3：删除未用字幕
    if (unusedSubtitleRows.length) {
      const deletePaths = unusedSubtitleRows.map(subtitle => resolveSubtitleEntryPath(subtitle)).filter(Boolean)
      const deleteResult = await libraryApi.browserBatchDelete(subtitleLibraryId, deletePaths, true, {
        skipActivityLog: true,
        batchId: `subtitle-manual-unused-${Date.now()}`
      })
      const failedDelete = (deleteResult?.failed_paths || [])[0]
      if (failedDelete) {
        throw new Error(`删除未用字幕失败：${failedDelete.error || failedDelete.path || '未知错误'}`)
      }
    }

    const currentTaskId = activeTask.value?.id || props.taskId
    await rjSubtitleApi.completeManual(currentTaskId, {
      appliedPairs: appliedPairCount,
      deletedSubtitles: unusedSubtitleRows.length,
      namingStrategy: subtitleOptions.value.namingStrategy || 'audio'
    })

    await refreshSubtitleInspectorAfterManualApply(currentTaskId)
    scheduleFinalIndexMoves(phaseTwoRenamed)
    ElMessage.success(`已重命名并导入 ${appliedPairCount} 组配对${unusedSubtitleRows.length ? `，并删除 ${unusedSubtitleRows.length} 个未使用字幕` : ''}`)
  } catch (error) {
    const rollbackErrors = []
    try {
      for (const pair of [...phaseTwoRenamed].reverse()) {
        const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        try {
          await libraryApi.browserRename(operationLibraryId, pair.final_path || pair.target_path || pair.temp_path, pair.current_name, {
            skipActivityLog: true,
            renameContext: 'subtitle_manual_match_pair',
            skipIndexMutation: true
          })
        } catch (rollbackError) {
          rollbackErrors.push(`${pair.target_name} -> ${pair.current_name}: ${rollbackError.response?.data?.detail || rollbackError.message}`)
        }
      }
      for (const pair of [...phaseOneRenamed].reverse()) {
        if (phaseTwoRenamed.includes(pair)) continue
        const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        try {
          await libraryApi.browserRename(operationLibraryId, pair.temp_path || pair.source_path, pair.current_name, {
            skipActivityLog: true,
            renameContext: 'subtitle_manual_match_pair',
            skipIndexMutation: true
          })
        } catch (rollbackError) {
          rollbackErrors.push(`${pair.temp_name} -> ${pair.current_name}: ${rollbackError.response?.data?.detail || rollbackError.message}`)
        }
      }
    } catch (_) {
      // Ignore outer rollback aggregation failures; detailed per-item errors are already collected.
    }
    const detail = error.response?.data?.detail || error.message
    if (rollbackErrors.length) {
      ElMessage.error(`重命名并导入失败，且自动回滚未完全成功: ${detail}；回滚异常 ${rollbackErrors[0]}`)
    } else {
      ElMessage.error('重命名并导入失败，已自动回滚已改名文件: ' + detail)
    }
  } finally {
    subtitlePairApplying.value = false
  }
}

async function openSubtitleInspectorFilterDeleteDialog() {
  const folderPath = String(subtitleInspectorInfo.value.folderPath || '').trim()
  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').trim()
  const useFolderPath = Boolean(folderPath)
  const libraryId = useFolderPath
    ? (subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId)
    : (subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId)
  const targetPath = useFolderPath ? folderPath : subtitleDir
  if (!libraryId || !targetPath) return
  filterDeleteDialogLibraryId.value = libraryId
  filterDeleteDialogPath.value = targetPath
  filterDeleteDialogTargetPaths.value = [targetPath]
  filterDeleteDialogScopeLabel.value = `${getTaskDisplayRJCode(activeTask.value) || getFileName(targetPath) || '当前任务'} RJ 目录`
  filterDeleteDialogIsRemote.value = targetPath.startsWith('/')
  filterDeleteDialogVisible.value = true
}

async function handleFilterDeleteDeleted() {
  const reloaded = await reloadCurrentSubtitleInspectorSnapshot()
  if (reloaded === null) await reloadSubtitleInspector()
}

const subtitleInspectorRoot = computed(() => buildTree(subtitleInspectorItems.value))
const subtitleInspectorFilteredRoot = computed(() => {
  const keyword = subtitleInspectorSearch.value.trim().toLowerCase()
  return keyword ? filterTree(subtitleInspectorRoot.value, keyword) : subtitleInspectorRoot.value
})
const subtitleInspectorFlatTree = computed(() => flattenTree(subtitleInspectorFilteredRoot.value, 0, subtitleInspectorExpandedIds.value))
const subtitleInspectorHasDirectories = computed(() => subtitleInspectorItems.value.some(item => item?.type === 'dir'))
const subtitleInspectorBusy = computed(() => subtitleInspectorLoading.value || subtitleInspectorDeleting.value || subtitlePairApplying.value || subtitleAutoPairing.value)
const subtitleInspectorAudioFiles = computed(() => (
  (subtitleInspectorAudioItems.value || [])
    .filter(item => isAudioFileName(item?.name || '') && !isSubtitleRelativePath(item?.relative_path || item?.name || ''))
    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))
))
const subtitleInspectorSubtitleFiles = computed(() => (
  (subtitleInspectorItems.value || [])
    .filter(item => isSubtitleFileName(item?.name || ''))
    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))
))
const filteredSubtitleInspectorAudioFiles = computed(() => {
  const keyword = subtitleInspectorAudioSearch.value.trim().toLowerCase()
  const items = subtitleInspectorAudioFiles.value.filter(item => {
    if (subtitleAudioFilterMode.value === 'paired') return isAudioPaired(item.path)
    if (subtitleAudioFilterMode.value === 'unpaired') return !isAudioPaired(item.path)
    return true
  })
  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items
})
const filteredSubtitleInspectorSubtitleFiles = computed(() => {
  const keyword = subtitleInspectorSubtitleSearch.value.trim().toLowerCase()
  const items = subtitleInspectorSubtitleFiles.value.filter(item => {
    if (subtitleSubtitleFilterMode.value === 'paired') return isSubtitlePaired(item.path)
    if (subtitleSubtitleFilterMode.value === 'unpaired') return !isSubtitlePaired(item.path)
    return true
  })
  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items
})
const canAddSubtitleManualPair = computed(() => Boolean(subtitleMatchSelection.value.audioPath && subtitleMatchSelection.value.subtitlePath))
const canBuildSequenceSubtitlePairs = computed(() => {
  const audioCount = subtitleSequenceSelection.value.audioPaths.length
  const subtitleCount = subtitleSequenceSelection.value.subtitlePaths.length
  return audioCount > 0 && subtitleCount > 0
})
const subtitleInspectorSelectableRows = computed(() => subtitleInspectorFlatTree.value.filter(row => row?.type === 'file' || row?.type === 'dir'))
const subtitleInspectorAllSelected = computed(() => subtitleInspectorSelectableRows.value.length > 0 && subtitleInspectorSelectableRows.value.every(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleInspectorSomeSelected = computed(() => !subtitleInspectorAllSelected.value && subtitleInspectorSelectableRows.value.some(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleInspectorSelectedRows = computed(() => subtitleInspectorFlatTree.value.filter(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleInspectorFilterDeleteRules = computed(() => (
  subtitleOptions.value.useFilterRules !== false
    ? sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules || [])
    : []
))
const totalQueuePages = computed(() => Math.max(1, Math.ceil(linkedTasks.value.length / queuePageSize)))
const pagedLinkedTasks = computed(() => {
  const currentPage = Math.min(Math.max(1, queuePage.value), totalQueuePages.value)
  const start = (currentPage - 1) * queuePageSize
  return linkedTasks.value.slice(start, start + queuePageSize)
})
const processingTaskCount = computed(() => linkedTasks.value.filter(task => isProcessingTask(task)).length)
const completedTaskCount = computed(() => linkedTasks.value.filter(task => isCompletedTask(task)).length)
const failedTaskCount = computed(() => linkedTasks.value.filter(task => isFailedTask(task)).length)
const clearableTaskCount = computed(() => linkedTasks.value.filter(task => canClearTask(task)).length)
const awaitingTaskCount = computed(() => linkedTasks.value.filter(task => isAwaitingManualTask(task)).length)
const activeTaskSupportsRetarget = computed(() => canRetargetTask(activeTask.value))
const retargetCandidates = computed(() => retargetPreview.value?.candidates || [])
const selectedRetargetCandidate = computed(() => (
  retargetCandidates.value.find(candidate => candidateKey(candidate) === retargetCandidateSelection.value) || null
))
const canRetargetActiveTask = computed(() => {
  if (!activeTaskSupportsRetarget.value) return false
  if (!selectedRetargetCandidate.value) return false
  if (retargetPreviewLoading.value) return false
  return candidateKey(selectedRetargetCandidate.value) !== getTaskTargetCandidateKey(activeTask.value)
})

function stopTaskStatusPolling() {
  if (taskStatusTimer) {
    window.clearTimeout(taskStatusTimer)
    taskStatusTimer = null
  }
}

function startTaskStatusPolling() {
  if (taskStatusTimer || (!props.visible && !props.backgroundActive)) return
  taskStatusTimer = window.setTimeout(async () => {
    taskStatusTimer = null
    if (!props.visible && !props.backgroundActive) return
    if (!realtimeEvents.connected.value) {
      await refreshTaskStatus(false, { inspect: false, silent: true })
    }
    startTaskStatusPolling()
  }, TASK_STATUS_REFRESH_MS)
}

function patchLinkedTaskFromRealtimeEvent(payload = {}) {
  const taskId = String(payload.engine_task_id || payload.entity_id || '').trim()
  if (!taskId) return false
  const domain = String(payload.domain || '').trim()
  if (domain && domain !== 'subtitle_import') return false
  let changed = false
  linkedTasks.value = sortLinkedTasks(linkedTasks.value.map(task => {
    if (String(task?.id || '') !== taskId) return task
    changed = true
    return preserveSubtitleTaskWorkspaceFields({
      ...task,
      status: payload.status || task.status,
      progress: Number(payload.progress ?? task.progress ?? 0),
      current_step: payload.current_step || task.current_step,
    }, task)
  }))
  if (activeTask.value?.id === taskId) {
    activeTask.value = linkedTasks.value.find(task => task.id === taskId) || activeTask.value
  }
  return changed
}

function handleTaskRealtimeEvent(event) {
  const payloads = normalizeTaskCenterRealtimePayloads(event?.detail || {})
    .filter(payload => payload?.type === 'task_center_changed')
  let shouldRefresh = false
  for (const payload of payloads) {
    if (!patchLinkedTaskFromRealtimeEvent(payload)) continue
    const status = String(payload.status || '').trim()
    if (['completed', 'failed', 'cancelled', 'waiting_manual'].includes(status)) {
      shouldRefresh = true
    }
  }
  if (shouldRefresh) {
    refreshTaskStatus(false, { inspect: props.visible, forceInspect: props.visible, silent: true })
  }
}

watch(() => [props.visible, props.backgroundActive], async ([visible, backgroundActive]) => {
  if (!visible && !backgroundActive) {
    stopTaskStatusPolling()
    return
  }
  startTaskStatusPolling()
  await refreshTaskStatus(false, { inspect: visible, forceInspect: visible, silent: linkedTasks.value.length > 0 })
}, { immediate: true })

watch(activeTask, async (task) => {
  if (!task || !props.visible || !canRetargetTask(task)) {
    retargetPreview.value = null
    retargetCandidateSelection.value = ''
    retargetPreviewTaskId.value = ''
    return
  }
  await loadRetargetPreview(task, { force: false, showMessage: false })
}, { immediate: true })

onMounted(() => {
  window.addEventListener('kikoerumanager:events:message', handleTaskRealtimeEvent)
})

onUnmounted(() => {
  window.removeEventListener('kikoerumanager:events:message', handleTaskRealtimeEvent)
  stopTaskStatusPolling()
})

const workbenchStatePayload = computed(() => ({
  total: linkedTasks.value.length,
  processing: processingTaskCount.value,
  awaiting: awaitingTaskCount.value,
  completed: completedTaskCount.value,
  manualCompleted: linkedTasks.value.filter(task => task.manual_match_completed).length,
  failed: failedTaskCount.value,
  clearable: clearableTaskCount.value,
  selectedTaskId: String(selectedTaskId.value || ''),
  activeTask: activeTask.value ? {
    id: activeTask.value.id,
    rjcode: getTaskDisplayRJCode(activeTask.value),
    title: activeTask.value.folder_name || getFileName(activeTask.value.folder_path),
    statusLabel: getTaskStatusLabel(activeTask.value),
    progressText: getTaskProgressText(activeTask.value),
    currentStep: String(activeTask.value.current_step || ''),
    downloadedCount: Number(activeTask.value.downloaded_count || 0),
    manualMatchCompleted: Boolean(activeTask.value.manual_match_completed),
    awaitingManualMatch: Boolean(activeTask.value.awaiting_manual_match)
  } : null
}))

watch(workbenchStatePayload, (value) => {
  emit('state-change', value)
}, { deep: true, immediate: true })


const activeSubtitleWorkbenchStage = ref('overview')
const subtitleWorkbenchRailMode = ref('tasks')
const subtitleWorkbenchContextMode = ref('pairing')
const subtitleWorkbenchDrawerCollapsed = ref(false)
const subtitleTaskManualFilter = ref('all')

// 切换当前任务时自动拉取字幕目录快照；之前只有 refreshTaskStatus(inspect:true)
// 会触发 inspect，导致用户从任务队列里点另一条任务后，"筛选与配对" / "字幕文件树"
// 两个 stage 里的音频 / 字幕列表为空、看起来像"配对列表显示不出来"。
watch(() => activeTask.value?.id, async (taskId) => {
  if (!taskId || !props.visible) return
  const task = activeTask.value
  const subtitleDir = getTaskWorkbenchSubtitleDir(task)
  if (!subtitleDir) {
    clearSubtitleInspectorState()
    return
  }
  if (subtitleInspectorInfo.value.taskId === taskId
      && subtitleInspectorInfo.value.subtitleDir === subtitleDir
      && subtitleInspectorItems.value.length) {
    return
  }
  await inspectSubtitleTask(task)
}, { immediate: true })

// 切到 "筛选与配对" / "字幕文件树" stage 时兜底再 inspect 一次，
// 避免 overview 阶段打开工作台后、没自动 inspect 过就切 tab 导致列表空。
watch(activeSubtitleWorkbenchStage, async (stage) => {
  subtitleWorkbenchContextMode.value = stage === 'overview'
    ? 'settings'
    : stage === 'tree'
      ? 'tree'
      : 'pairing'
  if (stage !== 'pairing' && stage !== 'tree') return
  const task = activeTask.value
  const subtitleDir = getTaskWorkbenchSubtitleDir(task)
  if (!subtitleDir) return
  const hasLoadedSubtitleContext = subtitleInspectorInfo.value.taskId === task.id
    && subtitleInspectorInfo.value.subtitleDir === subtitleDir
    && subtitleInspectorItems.value.length
  const hasLoadedPairingContext = hasLoadedSubtitleContext
    && (stage !== 'pairing' || subtitleInspectorAudioItems.value.length || subtitleInspectorInfo.value.folderPath)
  if (subtitleInspectorInfo.value.taskId === task.id
      && hasLoadedPairingContext) {
    return
  }
  await inspectSubtitleTask(task, { force: stage === 'pairing' })
})

const subtitleClearableTaskCounts = computed(() => ({
  all: linkedTasks.value.filter(task => canClearTask(task)).length,
  completed: linkedTasks.value.filter(task => isCompletedTask(task)).length,
  failed: linkedTasks.value.filter(task => isFailedTask(task)).length,
  finished: linkedTasks.value.filter(task => canClearTask(task)).length
}))
const subtitleTaskManualOverview = computed(() => ([
  { key: 'all', label: '\u5168\u90e8', value: linkedTasks.value.length },
  { key: 'processing', label: '\u8fdb\u884c\u4e2d', value: processingTaskCount.value },
  { key: 'awaiting', label: '\u5f85\u914d\u5bf9', value: awaitingTaskCount.value },
  { key: 'completed', label: '\u5df2\u5b8c\u6210', value: completedTaskCount.value },
  { key: 'failed', label: '\u5931\u8d25', value: failedTaskCount.value },
  { key: 'clearable', label: '\u53ef\u6e05\u7406', value: clearableTaskCount.value }
]))
const visibleSubtitleTasks = computed(() => {
  if (subtitleTaskManualFilter.value === 'processing') return linkedTasks.value.filter(task => isProcessingTask(task))
  if (subtitleTaskManualFilter.value === 'awaiting') return linkedTasks.value.filter(task => isAwaitingManualTask(task))
  if (subtitleTaskManualFilter.value === 'completed') return linkedTasks.value.filter(task => isCompletedTask(task))
  if (subtitleTaskManualFilter.value === 'failed') return linkedTasks.value.filter(task => isFailedTask(task))
  if (subtitleTaskManualFilter.value === 'clearable') return linkedTasks.value.filter(task => canClearTask(task))
  return linkedTasks.value
})
const activeSubtitleTaskProgressLogs = computed(() => Array.isArray(activeTask.value?.progress_log) ? activeTask.value.progress_log : [])
const activeSubtitleWorkbenchStageLabel = computed(() => ({
  overview: '\u4efb\u52a1\u603b\u89c8',
  pairing: '\u7b5b\u9009\u4e0e\u914d\u5bf9',
  tree: '\u5b57\u5e55\u6811'
}[activeSubtitleWorkbenchStage.value] || '\u4efb\u52a1\u603b\u89c8'))
const subtitleConfigCtx = computed(() => ({
  subtitleOptions: subtitleOptions.value,
  canClearSequenceSelection: Boolean(subtitleSequenceSelection.value.audioPaths.length || subtitleSequenceSelection.value.subtitlePaths.length),
  canClearManualPairs: Boolean(subtitleManualPairs.value.length),
  treeSelectedCount: subtitleInspectorSelectedRows.value.length,
  treeVisibleCount: subtitleInspectorFlatTree.value.length,
  treeSearchText: subtitleInspectorSearch.value,
  setTreeSearch: value => {
    subtitleInspectorSearch.value = value
    onSubtitleInspectorSearchInput()
  },
  setSubtitleOption: (key, value) => { subtitleOptions.value[key] = value },
  addSubtitleFilterRule,
  removeSubtitleFilterRule,
  clearSubtitleSequenceSelection,
  clearSubtitleManualPairs,
  openSubtitleInspectorFilterDeleteDialog,
  canOpenSubtitleInspectorFilterDeleteDialog: canOpenSubtitleInspectorFilterDeleteDialog.value,
  activeTask: activeTask.value,
  subtitleCleanupLoading: subtitleCleanupLoading.value,
  subtitleCleanupSummary: subtitleCleanupSummary.value,
  applySubtitleCleanup,
  activeTaskSupportsRetarget: activeTaskSupportsRetarget.value,
  retargetPreviewLoading: retargetPreviewLoading.value,
  retargetingTaskId: retargetingTaskId.value,
  retargetCandidates: retargetCandidates.value,
  selectedRetargetCandidate: selectedRetargetCandidate.value,
  retargetCandidateSelection: retargetCandidateSelection.value,
  canRetargetActiveTask: canRetargetActiveTask.value,
  candidateKey,
  loadRetargetPreview,
  retargetActiveTask,
  setRetargetCandidateSelection: value => { retargetCandidateSelection.value = value }
}))
const subtitleTaskStageCtx = computed(() => ({
  subtitleQueueTasks: linkedTasks.value,
  visibleSubtitleTasks: visibleSubtitleTasks.value,
  subtitleQueueLoading: taskLoading.value && !taskLoadedOnce.value && !linkedTasks.value.length,
  subtitleQueueRefreshing: taskRefreshing.value,
  activeSubtitleTask: activeTask.value,
  selectedSubtitleTaskId: String(selectedTaskId.value || ''),
  activeSubtitleWorkbenchStageLabel: activeSubtitleWorkbenchStageLabel.value,
  subtitleClearableTaskCounts: subtitleClearableTaskCounts.value,
  subtitleBulkClearingScope: queueClearing.value ? 'finished' : '',
  subtitleTaskDetailPanels: buildDefaultSubtitleTaskDetailPanels(activeTask.value),
  subtitleOptions: subtitleOptions.value,
  subtitleCancelingId: '',
  subtitleTaskRerunId: retryingTaskId.value,
  subtitleTaskManualOverview: subtitleTaskManualOverview.value,
  subtitleTaskManualFilter: subtitleTaskManualFilter.value,
  activeSubtitleTaskProgressLogs: activeSubtitleTaskProgressLogs.value,
  getTaskDisplayRJCode,
  getTaskSourceRJCode,
  getRJSubtitleTaskBaseStatusType: getRJSubtitleTaskStatusType,
  getRJSubtitleTaskBaseStatusLabel: getTaskStatusLabel,
  getRJSubtitleTaskStatusLabel: getTaskStatusLabel,
  getRJSubtitleTaskStatusClass: getTaskStateClass,
  getRJSubtitleProgressStatus: getTaskProgressText,
  getRJSubtitleLangLabel: value => value || '-',
  getFileName,
  getLibraryLabelById: value => value || '-',
  isHistoryRestoredSubtitleTask: () => false,
  isSelectionBackfillSubtitleTask: () => false,
  isSubtitleTaskSelected: task => task?.id === selectedTaskId.value,
  canCancelRJSubtitleTask: () => false,
  canClearCurrentSubtitleTask: canClearTask,
  canRerunSubtitleTask: canRetryTask,
  getSubtitleTaskInspectLabel: () => '\u67e5\u770b',
  cancelRJSubtitleTask: () => {},
  clearCurrentSubtitleTask: async task => {
    if (!task || !canClearTask(task)) return
    await rjSubtitleApi.clearTask(task.id)
    clearSubtitleTaskDraft(task.id)
    await refreshTaskStatus(false, { inspect: false, silent: true })
  },
  rerunSubtitleTask: retryWorkbenchTask,
  clearSubtitleTasksByScope: async (scope) => {
    const tasks = linkedTasks.value.filter(task => {
      if (scope === 'completed') return isCompletedTask(task)
      if (scope === 'failed') return isFailedTask(task)
      return canClearTask(task)
    })
    if (!tasks.length) return
    const ids = tasks.map(t => t.id)
    for (const id of ids) {
      try { await rjSubtitleApi.clearTask(id) } catch (_) {}
      clearSubtitleTaskDraft(id)
    }
    await refreshTaskStatus(false, { inspect: false, silent: true })
  },
  inspectSubtitleTask,
  selectSubtitleTask: task => selectWorkbenchTask(task?.id || task),
  setSubtitleTaskManualFilter: value => { subtitleTaskManualFilter.value = value },
  getSubtitleDownloadFiles: task => Array.isArray(task?.download_files) ? task.download_files : [],
  getSubtitleDownloadDisplayName: file => file?.name || file?.relative_path || file?.path || '-',
  allSubtitleDownloadsCompleted: task => (Array.isArray(task?.download_files) ? task.download_files : []).every(file => file?.status === 'completed'),
  isSubtitleDownloadExpanded: () => false,
  toggleSubtitleDownloadExpanded: () => {},
  visibleSubtitleDownloadFiles: task => Array.isArray(task?.download_files) ? task.download_files : [],
  hiddenSubtitleDownloadCount: () => 0,
  isSubtitleIssueExpanded: () => false,
  toggleSubtitleIssueExpanded: () => {},
  visibleSubtitleWriteErrors: task => Array.isArray(task?.write_errors) ? task.write_errors : [],
  visibleSubtitleFailedFiles: task => Array.isArray(task?.failed_files) ? task.failed_files : [],
  hiddenSubtitleIssueCount: () => 0,
  formatRJSubtitleAttempt: value => value || '',
  formatProgressLogTime: value => formatDate(value),
  getProgressLogLevelLabel: value => value || '',
  getSubtitleMatchedPairCount: task => Number(task?.manual_match_applied_pairs || task?.matched_pair_count || 0),
  getSubtitleAppliedWrittenFiles: task => (Array.isArray(task?.written_files) ? task.written_files : []).filter(f => f?.match_type !== 'raw_workbench_stage')
}))
const subtitleWorkbenchStageCtx = computed(() => ({
  railModes: [{ key: 'tasks', label: '\u6267\u884c\u961f\u5217' }],
  railMode: subtitleWorkbenchRailMode.value,
  setRailMode: value => { subtitleWorkbenchRailMode.value = value },
  stageTabs: [
    { key: 'overview', label: '\u4efb\u52a1\u603b\u89c8', tip: '\u9636\u6bb5\u8fdb\u5ea6\u3001\u5199\u5165\u548c\u5f02\u5e38\u56de\u770b' },
    { key: 'pairing', label: '\u7b5b\u9009\u4e0e\u914d\u5bf9', tip: '\u97f3\u9891\u8f68\u3001\u5b57\u5e55\u8f68\u548c\u9884\u914d\u5bf9\u5de5\u4f4d' },
    { key: 'tree', label: '\u5b57\u5e55\u6587\u4ef6\u6811', tip: '\u68c0\u7d22\u3001\u6539\u540d\u4e0e\u6279\u91cf\u6e05\u7406' }
  ],
  activeStage: activeSubtitleWorkbenchStage.value,
  activeStageLabel: activeSubtitleWorkbenchStageLabel.value,
  setActiveStage: value => { activeSubtitleWorkbenchStage.value = value },
  contextMode: subtitleWorkbenchContextMode.value,
  scanCtx: {},
  taskNavigatorCtx: subtitleTaskStageCtx.value,
  taskOverviewCtx: subtitleTaskStageCtx.value,
  workbenchCtx: subtitleWorkbenchCtx.value,
  configCtx: subtitleConfigCtx.value,
  contextDrawerCtx: {
    modeTitle: ({
      settings: '\u53c2\u6570\u9762\u677f',
      pairing: '\u914d\u5bf9\u52a9\u624b',
      tree: '\u6587\u4ef6\u5de5\u5177'
    })[subtitleWorkbenchContextMode.value] || '\u53c2\u6570\u9762\u677f',
    modeTip: ({
      settings: '\u6267\u884c\u7b56\u7565\u3001\u8fc7\u6ee4\u89c4\u5219\u548c\u4efb\u52a1\u5c55\u793a\u90fd\u5728\u8fd9\u91cc\u7edf\u4e00\u63a7\u5236\u3002',
      pairing: '\u987a\u5e8f\u70b9\u9009\u3001\u914d\u5bf9\u6570\u91cf\u548c\u5173\u952e\u52a8\u4f5c\u63d0\u793a\u90fd\u96c6\u4e2d\u5728\u53f3\u4fa7\u3002',
      tree: '\u641c\u7d22\u8303\u56f4\u3001\u9009\u4e2d\u89c4\u6a21\u548c\u5220\u9664\u98ce\u9669\u63d0\u793a\u5728\u8fd9\u91cc\u67e5\u770b\u3002'
    })[subtitleWorkbenchContextMode.value] || '',
    contextMode: subtitleWorkbenchContextMode.value,
    setContextMode: value => { subtitleWorkbenchContextMode.value = value },
    drawerCollapsed: subtitleWorkbenchDrawerCollapsed.value,
    toggleDrawer: () => { subtitleWorkbenchDrawerCollapsed.value = !subtitleWorkbenchDrawerCollapsed.value },
    modeOptions: [
      { key: 'settings', label: '\u53c2\u6570', shortLabel: '\u53c2', icon: 'Sliders' },
      { key: 'pairing', label: '\u914d\u5bf9', shortLabel: '\u914d', icon: 'Link2' },
      { key: 'tree', label: '\u6587\u4ef6', shortLabel: '\u6587', icon: 'FolderTree' }
    ]
  }
}))

const subtitleWorkbenchCtx = computed(() => ({
  subtitleInspectorInfo: subtitleInspectorInfo.value,
  subtitleInspectorBusy: subtitleInspectorBusy.value,
  subtitleInspectorLoading: subtitleInspectorLoading.value,
  subtitleInspectorDeleting: subtitleInspectorDeleting.value,
  subtitleInspectorHasDirectories: subtitleInspectorHasDirectories.value,
  subtitleInspectorAudioFiles: subtitleInspectorAudioFiles.value,
  subtitleInspectorFlatTree: subtitleInspectorFlatTree.value,
  subtitleInspectorSelectedRows: subtitleInspectorSelectedRows.value,
  subtitleInspectorSelectedIds: subtitleInspectorSelectedIds.value,
  subtitleInspectorExpandedIds: subtitleInspectorExpandedIds.value,
  subtitleInspectorSearch: subtitleInspectorSearch.value,
  subtitleInspectorAudioSearch: subtitleInspectorAudioSearch.value,
  subtitleInspectorSubtitleSearch: subtitleInspectorSubtitleSearch.value,
  subtitleInspectorAllSelected: subtitleInspectorAllSelected.value,
  subtitleInspectorSomeSelected: subtitleInspectorSomeSelected.value,
  inspectableSubtitleTasks: linkedTasks.value,
  activeSubtitleInspectTask: activeTask.value,
  subtitleSequenceMode: subtitleSequenceMode.value,
  subtitleSequenceSelection: subtitleSequenceSelection.value,
  subtitleManualPairs: subtitleManualPairs.value,
  subtitleSelectedManualPairId: subtitleSelectedManualPairId.value,
  subtitleNamingStrategy: subtitleOptions.value.namingStrategy,
  subtitlePairApplying: subtitlePairApplying.value,
  subtitleAutoPairing: subtitleAutoPairing.value,
  subtitleManualApplyLabel: '重命名并导入',
  isLinkedSubtitleImportWorkbench: true,
  canOpenSubtitleInspectorFilterDeleteDialog: canOpenSubtitleInspectorFilterDeleteDialog.value,
  subtitleAudioFilterMode: subtitleAudioFilterMode.value,
  subtitleSubtitleFilterMode: subtitleSubtitleFilterMode.value,
  subtitleMatchSelection: subtitleMatchSelection.value,
  filteredSubtitleInspectorAudioFiles: filteredSubtitleInspectorAudioFiles.value,
  filteredSubtitleInspectorSubtitleFiles: filteredSubtitleInspectorSubtitleFiles.value,
  canBuildSequenceSubtitlePairs: canBuildSequenceSubtitlePairs.value,
  canAddSubtitleManualPair: canAddSubtitleManualPair.value,
  reloadSubtitleInspector,
  expandSubtitleInspectorTree,
  collapseSubtitleInspectorTree,
  inspectSubtitleTask,
  getTaskDisplayRJCode,
  getTaskSourceRJCode,
  getFileName,
  formatFileSize,
  buildAutoSubtitlePairs,
  buildAISubtitlePairs,
  buildRuleSubtitlePairs,
  buildSequenceOrOrderedSubtitlePairs,
  applySubtitleManualPairs,
  openSubtitleInspectorFilterDeleteDialog,
  setSubtitleSequenceMode: value => { subtitleSequenceMode.value = value },
  setSubtitleAudioFilterMode: value => { subtitleAudioFilterMode.value = value },
  setSubtitleSubtitleFilterMode: value => { subtitleSubtitleFilterMode.value = value },
  setSubtitleInspectorAudioSearch: value => { subtitleInspectorAudioSearch.value = value },
  setSubtitleInspectorSubtitleSearch: value => { subtitleInspectorSubtitleSearch.value = value },
  setSubtitleInspectorSearch: value => {
    subtitleInspectorSearch.value = value
    onSubtitleInspectorSearchInput()
  },
  setSubtitleSelectedManualPairId: value => { subtitleSelectedManualPairId.value = value },
  isAudioPaired,
  isAudioSuspicious,
  getSubtitleSequenceIndex,
  selectSubtitleAudio,
  addSubtitleManualPair,
  clearSubtitleSequenceSelection,
  clearSubtitleManualPairs,
  getSubtitlePairConfidenceLabel,
  removeSubtitleManualPair,
  isSubtitlePaired,
  isSubtitleSuspicious,
  selectSubtitleFile,
  batchDeleteSubtitleTreeEntries,
  clearSubtitleInspectorSelection,
  toggleAllSubtitleInspectorRows,
  handleSubtitleInspectorRowClick,
  toggleSubtitleInspectorSelect,
  toggleSubtitleInspectorExpand,
  resolveSubtitleTreeIcon,
  resolveSubtitleTreeIconStyle,
  formatDate,
  openSubtitleRenameDialog,
  deleteSubtitleTreeEntry
}))
</script>

<style scoped>
.subtitle-import-workbench {
  --siw-bg: #ffffff;
  --siw-surface: #ffffff;
  --siw-surface-soft: #ffffff;
  --siw-border: rgba(226, 232, 240, 0.92);
  --siw-border-strong: rgba(203, 213, 225, 0.95);
  --siw-text: #0f172a;
  --siw-muted: #64748b;
  --siw-soft: #94a3b8;
  --siw-shadow: none;
  position: relative;
  width: 100%;
  min-width: 0;
  color: var(--siw-text);
}

.siw-shell {
  display: flex;
  width: 100%;
  height: min(940px, calc(100dvh - 32px));
  min-height: min(780px, calc(100dvh - 32px));
  max-height: calc(100dvh - 32px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--siw-border);
  border-radius: 22px;
  background: var(--siw-surface);
  box-shadow: var(--siw-shadow);
}

.siw-header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 68px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--siw-border);
  background: var(--siw-surface);
}

.siw-title-wrap {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
}

.siw-brand {
  display: inline-flex;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: #6d28d9;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.siw-brand:hover {
  transform: translateY(-2px) scale(1.02);
}

.siw-brand-icon {
  width: 18px;
  height: 18px;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.siw-brand:hover .siw-brand-icon {
  transform: rotate(-6deg) scale(1.12);
}

.siw-title-copy {
  min-width: 0;
}

.siw-title-line {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.siw-title-line h2 {
  margin: 0;
  overflow: hidden;
  color: var(--siw-text);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.siw-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid rgba(34, 197, 94, 0.28);
  border-radius: 999px;
  background: rgba(240, 253, 244, 0.92);
  padding: 2px 8px;
  color: #15803d;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1.2;
}

.siw-live-pill span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #22c55e;
}

.siw-focus-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  margin-top: 5px;
  color: var(--siw-muted);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.35;
}

.siw-focus-code {
  flex: 0 0 auto;
  max-width: 108px;
  overflow: hidden;
  border: 1px solid var(--siw-border);
  border-radius: 8px;
  background: var(--siw-surface-soft);
  padding: 2px 7px;
  color: var(--siw-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.siw-focus-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.siw-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
}

.siw-action-btn,
.siw-form-btn,
.siw-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--siw-border);
  background: var(--siw-surface);
  color: var(--siw-text);
  cursor: pointer;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.siw-action-btn {
  min-height: 34px;
  gap: 6px;
  border-radius: 10px;
  padding: 0 10px;
  font-size: 12px;
}

.siw-action-btn:hover:enabled,
.siw-form-btn:hover:enabled,
.siw-icon-btn:hover:enabled {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--siw-border-strong);
  background: var(--siw-surface-soft);
}

.siw-action-btn:active:enabled,
.siw-form-btn:active:enabled,
.siw-icon-btn:active:enabled {
  transform: scale(0.96);
}

.siw-action-btn:disabled,
.siw-form-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.siw-action-btn.is-close {
  border-color: rgba(244, 63, 94, 0.24);
  background: rgba(255, 241, 242, 0.82);
  color: #be123c;
}

.siw-action-btn.is-close:hover:enabled {
  border-color: rgba(244, 63, 94, 0.38);
  background: rgba(255, 228, 230, 0.95);
}

.siw-action-icon {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.siw-action-btn:hover:enabled .siw-action-icon,
.siw-form-btn:hover:enabled .siw-action-icon,
.siw-icon-btn:hover:enabled svg {
  transform: rotate(-8deg) scale(1.12);
}

.is-spinning {
  animation: siw-spin 0.8s linear infinite;
}

.siw-stage-wrap {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
  background: #ffffff;
}

.siw-shell :deep(button:focus),
.siw-shell :deep(button:focus-visible),
.siw-shell :deep(input:focus),
.siw-shell :deep(input:focus-visible),
.siw-shell :deep([tabindex]:focus),
.siw-shell :deep([tabindex]:focus-visible) {
  outline: none !important;
  box-shadow: none !important;
}

.siw-stage-wrap :deep(.bg-slate-50),
.siw-stage-wrap :deep(.bg-slate-50\/30),
.siw-stage-wrap :deep(.bg-slate-50\/40),
.siw-stage-wrap :deep(.bg-slate-50\/60),
.siw-stage-wrap :deep(.bg-slate-50\/80),
.siw-stage-wrap :deep(.bg-slate-100),
.siw-stage-wrap :deep(.bg-slate-100\/80) {
  background-color: #ffffff !important;
  background-image: none !important;
}

.siw-stage-wrap :deep(.shadow-sm),
.siw-stage-wrap :deep(.shadow),
.siw-stage-wrap :deep(.shadow-md),
.siw-stage-wrap :deep(.shadow-lg),
.siw-stage-wrap :deep(.shadow-xl),
.siw-stage-wrap :deep([class*="shadow-"]) {
  box-shadow: none !important;
}

.siw-stage-wrap :deep(.ring-1),
.siw-stage-wrap :deep(.ring-2),
.siw-stage-wrap :deep([class*="ring-"]) {
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
  box-shadow: none !important;
}

.siw-stage-wrap > :deep(.subtitle-workbench-stage) {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  min-height: 0;
}

.siw-rename-overlay {
  position: fixed;
  inset: 0;
  z-index: 3200;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgba(15, 23, 42, 0.52);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.siw-rename-card {
  width: min(520px, calc(100vw - 24px));
  overflow: hidden;
  border: 1px solid var(--siw-border);
  border-radius: 18px;
  background: var(--siw-surface);
  box-shadow: none;
}

.siw-rename-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--siw-border);
}

.siw-rename-head h3 {
  margin: 0;
  color: var(--siw-text);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0;
}

.siw-rename-head p {
  margin: 4px 0 0;
  color: var(--siw-muted);
  font-size: 12px;
  line-height: 1.5;
}

.siw-icon-btn {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border-radius: 9px;
  color: var(--siw-muted);
}

.siw-rename-fields {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
}

.siw-field {
  display: grid;
  gap: 6px;
}

.siw-field span,
.siw-preview span {
  color: var(--siw-muted);
  font-size: 11px;
  font-weight: 800;
}

.siw-field input {
  width: 100%;
  min-width: 0;
  height: 38px;
  border: 1px solid var(--siw-border);
  border-radius: 10px;
  background: var(--siw-surface-soft);
  color: var(--siw-text);
  font-size: 13px;
  font-weight: 650;
  outline: none;
  padding: 0 11px;
  transition: all 0.2s ease;
}

.siw-field input:focus {
  border-color: var(--siw-border-strong);
  background: var(--siw-surface);
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.18);
}

.siw-field input[readonly] {
  color: var(--siw-muted);
}

.siw-preview {
  display: grid;
  gap: 6px;
  min-width: 0;
  border: 1px dashed var(--siw-border-strong);
  border-radius: 12px;
  background: var(--siw-surface-soft);
  padding: 10px 11px;
}

.siw-preview strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--siw-text);
  font-size: 13px;
  line-height: 1.45;
}

.siw-rename-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--siw-border);
}

.siw-form-btn {
  min-height: 34px;
  gap: 6px;
  border-radius: 10px;
  padding: 0 13px;
  font-size: 12px;
}

.siw-form-btn.is-primary {
  border-color: #111827;
  background: #111827;
  color: #ffffff;
}

.siw-dialog-fade-enter-active,
.siw-dialog-fade-leave-active {
  transition: opacity 0.2s ease;
}

.siw-dialog-fade-enter-active .siw-rename-card,
.siw-dialog-fade-leave-active .siw-rename-card {
  transition: transform 0.22s ease, opacity 0.22s ease;
}

.siw-dialog-fade-enter-from,
.siw-dialog-fade-leave-to {
  opacity: 0;
}

.siw-dialog-fade-enter-from .siw-rename-card,
.siw-dialog-fade-leave-to .siw-rename-card {
  opacity: 0;
}

@keyframes siw-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 760px) {
  .siw-shell {
    height: 100dvh;
    min-height: 100dvh;
    max-height: 100dvh;
    border-radius: 0;
    border: 0;
  }

  .siw-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
    padding: 12px;
  }

  .siw-actions {
    display: grid;
    width: 100%;
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .siw-action-btn {
    width: 100%;
    padding: 0 7px;
  }

  .siw-stage-wrap {
    padding: 8px;
  }
}

:global(html.kikoerumanager-dark .subtitle-import-workbench),
:global(body.kikoerumanager-dark .subtitle-import-workbench),
:global(.kikoerumanager-dark .subtitle-import-workbench) {
  --siw-bg: var(--km-dark-bg);
  --siw-surface: var(--km-dark-surface);
  --siw-surface-soft: var(--km-dark-elevated);
  --siw-border: var(--km-dark-border);
  --siw-border-strong: var(--km-dark-border-strong);
  --siw-text: var(--km-dark-text-strong);
  --siw-muted: var(--km-dark-text-muted);
  --siw-soft: var(--km-dark-text-subtle);
  --siw-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-shell),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-shell),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-shell),
:global(html.kikoerumanager-dark .siw-rename-card),
:global(body.kikoerumanager-dark .siw-rename-card),
:global(.kikoerumanager-dark .siw-rename-card) {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-header),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-header),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-header) {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-stage-wrap),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-stage-wrap),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-stage-wrap) {
  background: var(--km-dark-surface) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-brand),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-brand),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-brand) {
  border-color: rgba(167, 139, 250, 0.38);
  background: transparent;
  color: #c4b5fd;
}

:global(html.kikoerumanager-dark .siw-form-btn.is-primary),
:global(body.kikoerumanager-dark .siw-form-btn.is-primary),
:global(.kikoerumanager-dark .siw-form-btn.is-primary) {
  border-color: var(--km-dark-border-strong);
  background: var(--km-dark-primary-button-bg);
  color: var(--km-dark-primary-button-text);
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-live-pill),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-live-pill),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-live-pill) {
  border-color: rgba(126, 211, 169, 0.26);
  background: rgba(126, 211, 169, 0.12);
  color: var(--km-dark-green);
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn) {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn:hover:enabled),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn:hover:enabled),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn:hover:enabled) {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn.is-close),
:global(body.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn.is-close),
:global(.kikoerumanager-dark .subtitle-import-workbench .siw-action-btn.is-close) {
  border-color: rgba(251, 113, 133, 0.24);
  background: rgba(251, 113, 133, 0.1);
  color: var(--km-dark-red);
}

:global(html.kikoerumanager-dark) .siw-rename-overlay,
:global(body.kikoerumanager-dark) .siw-rename-overlay,
:global(.kikoerumanager-dark) .siw-rename-overlay {
  background: rgba(0, 0, 0, 0.34);
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .bg-white),
:global(body.kikoerumanager-dark .subtitle-import-workbench .bg-white),
:global(.kikoerumanager-dark .subtitle-import-workbench .bg-white),
:global(html.kikoerumanager-dark .subtitle-import-workbench [class*="bg-white"]),
:global(body.kikoerumanager-dark .subtitle-import-workbench [class*="bg-white"]),
:global(.kikoerumanager-dark .subtitle-import-workbench [class*="bg-white"]) {
  background-color: var(--km-dark-surface) !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .bg-slate-50),
:global(body.kikoerumanager-dark .subtitle-import-workbench .bg-slate-50),
:global(.kikoerumanager-dark .subtitle-import-workbench .bg-slate-50),
:global(html.kikoerumanager-dark .subtitle-import-workbench .bg-slate-100),
:global(body.kikoerumanager-dark .subtitle-import-workbench .bg-slate-100),
:global(.kikoerumanager-dark .subtitle-import-workbench .bg-slate-100),
:global(html.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-50"]),
:global(body.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-50"]),
:global(.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-50"]),
:global(html.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-100"]),
:global(body.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-100"]),
:global(.kikoerumanager-dark .subtitle-import-workbench [class*="bg-slate-100"]) {
  background-color: var(--km-dark-elevated) !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .border-slate-100),
:global(body.kikoerumanager-dark .subtitle-import-workbench .border-slate-100),
:global(.kikoerumanager-dark .subtitle-import-workbench .border-slate-100),
:global(html.kikoerumanager-dark .subtitle-import-workbench .border-slate-200),
:global(body.kikoerumanager-dark .subtitle-import-workbench .border-slate-200),
:global(.kikoerumanager-dark .subtitle-import-workbench .border-slate-200),
:global(html.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-100"]),
:global(body.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-100"]),
:global(.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-100"]),
:global(html.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-200"]),
:global(body.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-200"]),
:global(.kikoerumanager-dark .subtitle-import-workbench [class*="border-slate-200"]) {
  border-color: var(--km-dark-border) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-900),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-900),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-900),
:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-800),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-800),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-800),
:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-700),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-700),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-700) {
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-600),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-600),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-600),
:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-500),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-500),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-500),
:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-400),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-400),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-400),
:global(html.kikoerumanager-dark .subtitle-import-workbench .text-slate-300),
:global(body.kikoerumanager-dark .subtitle-import-workbench .text-slate-300),
:global(.kikoerumanager-dark .subtitle-import-workbench .text-slate-300) {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench :is([class*="shadow-"], .shadow-sm, .shadow, .shadow-md, .shadow-lg, .shadow-xl, .shadow-2xl)),
:global(body.kikoerumanager-dark .subtitle-import-workbench :is([class*="shadow-"], .shadow-sm, .shadow, .shadow-md, .shadow-lg, .shadow-xl, .shadow-2xl)),
:global(.kikoerumanager-dark .subtitle-import-workbench :is([class*="shadow-"], .shadow-sm, .shadow, .shadow-md, .shadow-lg, .shadow-xl, .shadow-2xl)) {
  box-shadow: none !important;
}
</style>
