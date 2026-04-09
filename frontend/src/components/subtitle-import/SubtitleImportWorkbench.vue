<template>
  <div class="import-workbench-modal" v-loading="workbenchLoading">
    <div class="import-workbench-head">
      <div>
        <div class="import-workbench-title">字幕补配工作台</div>
        <div class="import-workbench-desc">工作台会保留补配历史，不会因为完成、失败或临时关闭而自动清空。你可以随时回来继续处理或回看结果。</div>
      </div>
      <div class="import-workbench-actions">
        <el-button size="small" :loading="manualRefreshing" @click="refreshTaskStatus(true, { inspect: true, forceInspect: true, showOverlay: false })">刷新状态</el-button>
        <el-button size="small" :disabled="!clearableTaskCount" :loading="queueClearing" @click="clearFinishedTasks">清空队列</el-button>
        <el-button size="small" @click="emit('hide-background')">隐藏到后台</el-button>
        <el-button size="small" @click="emit('close')">关闭工作台</el-button>
      </div>
    </div>
    <div class="import-workbench-toolbar">
      <div class="import-toolbar-stats">
        <span class="toolbar-pill">全部 {{ linkedTasks.length }}</span>
        <span class="toolbar-pill toolbar-pill-primary">进行中 {{ processingTaskCount }}</span>
        <span class="toolbar-pill toolbar-pill-success">已完成 {{ completedTaskCount }}</span>
        <span class="toolbar-pill toolbar-pill-danger">失败 {{ failedTaskCount }}</span>
      </div>
      <div class="import-toolbar-tip">仅手动清理已完成或已失败任务，进行中的任务会继续保留。</div>
    </div>

    <div class="import-workbench-body">
      <section class="import-task-list-card">
        <div class="import-task-list-head">
          <div>
            <div class="import-section-title">任务列表</div>
            <div class="import-section-tip">长驻式队列视图，支持查看历史、失败原因和手动重试。</div>
          </div>
          <el-tag size="small" type="info">分页 {{ queuePage }} / {{ totalQueuePages }}</el-tag>
        </div>

        <el-empty v-if="!linkedTasks.length && !workbenchLoading" description="当前没有字幕补配任务，打开工作台后新任务会继续留在这里。" />

        <div v-else class="import-task-list-body">
          <button
            v-for="task in pagedLinkedTasks"
            :key="task.id"
            type="button"
            class="import-task-row"
            :class="[getTaskStateClass(task), { active: task.id === selectedTaskId }]"
            @click="selectWorkbenchTask(task.id)"
          >
            <div class="import-task-row-main">
              <div class="import-task-row-heading">
                <span class="import-task-row-rj">{{ getTaskDisplayRJCode(task) }}</span>
                <div class="import-task-row-title">{{ task.folder_name || getFileName(task.folder_path) }}</div>
              </div>
              <div class="import-task-row-meta">
                <span v-if="getTaskSourceRJCode(task)">来源 {{ getTaskSourceRJCode(task) }}</span>
                <span v-if="task.target_rjcode">目标 {{ task.target_rjcode }}</span>
                <span>{{ task.downloaded_count || 0 }} 字幕</span>
                <span v-if="task.manual_match_completed">已应用 {{ task.manual_match_applied_pairs || 0 }} 组</span>
                <span>{{ formatTaskTimeline(task) }}</span>
              </div>
            </div>

            <div class="import-task-row-side">
              <el-tooltip
                v-if="getTaskFailureReason(task)"
                :content="getTaskFailureReason(task)"
                placement="top"
              >
                <span
                  :class="[
                    isCompletedTask(task) ? 'task-status-text' : 'task-status-pill',
                    `state-${getTaskStateClass(task)}`
                  ]"
                >
                  {{ getTaskStatusLabel(task) }}
                </span>
              </el-tooltip>
              <span
                v-else
                :class="[
                  isCompletedTask(task) ? 'task-status-text' : 'task-status-pill',
                  `state-${getTaskStateClass(task)}`
                ]"
              >
                {{ getTaskStatusLabel(task) }}
              </span>

              <div class="import-task-row-progress">{{ getTaskProgressText(task) }}</div>

              <div class="import-task-row-actions">
                <el-button
                  size="small"
                  :type="task.id === selectedTaskId ? 'primary' : 'default'"
                  @click.stop="selectWorkbenchTask(task.id)"
                >
                  查看
                </el-button>
                <el-button
                  v-if="canRetryTask(task)"
                  size="small"
                  :loading="retryingTaskId === task.id"
                  @click.stop="retryWorkbenchTask(task)"
                >
                  重试
                </el-button>
              </div>
            </div>
          </button>
        </div>

        <div v-if="linkedTasks.length > queuePageSize" class="import-task-pagination">
          <el-pagination
            v-model:current-page="queuePage"
            small
            background
            layout="prev, pager, next"
            :page-size="queuePageSize"
            :total="linkedTasks.length"
          />
        </div>
      </section>

      <section class="import-task-detail">
        <el-empty v-if="!workbenchLoading && !linkedTasks.length" description="当前工作台没有可展示的字幕补配任务。" />

        <template v-else-if="activeTask">
          <el-card shadow="never" class="import-config-card">
            <template #header>
              <div class="import-config-head">
                <span>补配选项</span>
              </div>
            </template>

            <div class="import-config-stack">
              <div class="import-config-row">
                <div>
                  <div class="import-config-title">命名依据</div>
                  <div class="import-config-tip">最终一键应用时，决定字幕和音频按谁的名字落地。</div>
                </div>
                <el-radio-group v-model="subtitleOptions.namingStrategy" size="small">
                  <el-radio-button label="audio">以音频名为准</el-radio-button>
                  <el-radio-button label="subtitle">以字幕名为准</el-radio-button>
                </el-radio-group>
              </div>

              <div class="import-config-row import-config-row-wrap">
                <div class="import-config-title-row">
                  <div>
                    <div class="import-config-title">字幕过滤规则</div>
                    <div class="import-config-tip">规则支持实时编辑、启停和持久化，下次打开工作台会继续保留。</div>
                  </div>
                  <el-switch v-model="subtitleOptions.useFilterRules" inline-prompt active-text="开" inactive-text="关" />
                </div>

                <div class="import-filter-actions">
                  <el-button size="small" @click="addSubtitleFilterRule">添加规则</el-button>
                </div>

                <div class="import-filter-list">
                  <div v-if="!subtitleOptions.subtitleFilterRules.length" class="import-filter-empty">当前没有补配过滤规则。</div>
                  <div v-for="rule in subtitleOptions.subtitleFilterRules" :key="rule.id" class="import-filter-editor">
                    <div class="import-filter-editor-head">
                      <el-switch v-model="rule.enabled" size="small" />
                      <el-select v-model="rule.target" size="small" class="import-filter-target">
                        <el-option label="文件名" value="name" />
                        <el-option label="路径" value="path" />
                        <el-option label="全部" value="all" />
                      </el-select>
                      <el-button size="small" text type="danger" @click="removeSubtitleFilterRule(rule.id)">删除</el-button>
                    </div>
                    <el-input v-model="rule.name" size="small" placeholder="规则名，可留空" />
                    <el-input v-model="rule.pattern" size="small" placeholder="输入正则表达式，例如 \\.mp3$ 或 @[^\\s]+" />
                  </div>
                </div>
              </div>

              <div class="import-config-row">
                <div>
                  <div class="import-config-title">字幕正文清理</div>
                  <div class="import-config-tip">复用设置页里的 LRC 广告清理和繁体转简体，对当前工作台字幕执行一次处理。</div>
                </div>
                <div class="import-config-inline-actions">
                  <el-button size="small" :loading="subtitleCleanupLoading" @click="applySubtitleCleanup">应用字幕清理</el-button>
                </div>
              </div>

              <div v-if="subtitleCleanupSummary" class="import-cleanup-summary">
                {{ subtitleCleanupSummary }}
              </div>

              <div v-if="activeTaskSupportsRetarget" class="import-config-row import-config-row-wrap">
                <div class="import-config-title-row">
                  <div>
                    <div class="import-config-title">切换目标目录</div>
                    <div class="import-config-tip">从当前工作区里的原始字幕重新建一个新补配任务，不直接篡改旧任务。</div>
                  </div>
                  <div class="import-config-inline-actions">
                    <el-button size="small" :loading="retargetPreviewLoading" @click="loadRetargetPreview(activeTask, { force: true, showMessage: true })">刷新候选</el-button>
                    <el-button
                      size="small"
                      type="primary"
                      :disabled="!canRetargetActiveTask"
                      :loading="retargetingTaskId === activeTask?.id"
                      @click="retargetActiveTask"
                    >
                      切换目标并重建
                    </el-button>
                  </div>
                </div>

                <div class="import-retarget-current">
                  <div class="import-retarget-label">当前目标</div>
                  <div class="import-retarget-name">{{ activeTask.folder_name || getFileName(activeTask.target_folder_path || activeTask.folder_path) || '-' }}</div>
                  <div v-if="activeTask.target_rjcode" class="import-retarget-rj">{{ activeTask.target_rjcode }}</div>
                  <div v-if="activeTask.target_folder_path" class="import-retarget-path">{{ activeTask.target_folder_path }}</div>
                </div>

                <el-empty
                  v-if="!retargetPreviewLoading && !retargetCandidates.length"
                  description="当前没有可切换的目标目录候选"
                />

                <el-radio-group v-else v-model="retargetCandidateSelection" class="candidate-list">
                  <label
                    v-for="candidate in retargetCandidates"
                    :key="candidateKey(candidate)"
                    class="candidate-item"
                  >
                    <el-radio :label="candidateKey(candidate)">
                      <span class="candidate-title">{{ candidate.folder_name || candidate.folder_path }}</span>
                    </el-radio>
                    <div class="candidate-meta">
                      <span>{{ candidate.library_name }}</span>
                      <span>{{ candidate.library_type === 'synology_filestation' ? '远程库' : '本地库' }}</span>
                      <span>音频 {{ candidate.audio_count ?? 0 }}</span>
                      <span>现有字幕 {{ candidate.existing_subtitle_count ?? 0 }}</span>
                      <span>{{ formatFileSize(candidate.total_size || 0) }}</span>
                    </div>
                    <div class="candidate-path">{{ candidate.folder_path }}</div>
                  </label>
                </el-radio-group>
              </div>
            </div>
          </el-card>

          <div class="import-task-main">
            <el-alert
              v-if="isFailedTask(activeTask)"
              title="当前任务执行失败"
              type="error"
              :closable="false"
              show-icon
            >
              <template #default>
                {{ getTaskFailureReason(activeTask) || '请检查原因后重试该任务。' }}
              </template>
            </el-alert>

            <el-alert
              v-else-if="activeTask && !activeTask.subtitle_dir"
              title="当前任务还在准备字幕目录"
              type="info"
              :closable="false"
              show-icon
            >
              <template #default>
                {{ activeTask.current_step || '稍后刷新状态即可进入字幕补配工作台。' }}
              </template>
            </el-alert>

            <SubtitleInspectorWorkbench
              v-if="activeTask.subtitle_dir"
              :ctx="subtitleWorkbenchCtx"
            />

            <el-card v-else class="import-task-placeholder" shadow="never">
              <div class="import-task-placeholder-title">{{ getTaskStatusLabel(activeTask) }}</div>
              <div class="import-task-placeholder-text">
                {{ getTaskFailureReason(activeTask) || activeTask.current_step || '当前任务还没有可查看的字幕工作区。' }}
              </div>
            </el-card>
          </div>
        </template>

        <el-empty v-else description="请选择一条补配任务查看详情。" />
      </section>
    </div>

    <el-dialog v-model="subtitleRenameDialogVisible" title="重命名字幕文件" width="500px">
      <el-form :model="subtitleRenameForm" label-width="80px">
        <el-form-item label="当前名称"><el-input v-model="subtitleRenameForm.currentName" disabled /></el-form-item>
        <el-form-item label="新名称"><el-input v-model="subtitleRenameForm.newName" placeholder="输入新的字幕文件名" /></el-form-item>
        <el-form-item label="预览"><div class="name-preview">{{ subtitleRenameForm.newName || subtitleRenameForm.currentName }}</div></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subtitleRenameDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="subtitleRenameLoading" @click="confirmSubtitleRename">确认重命名</el-button>
      </template>
    </el-dialog>

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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderOpened, Document, Picture, VideoPlay, Headset, Tickets } from '@element-plus/icons-vue'
import { libraryApi, rjSubtitleApi, subtitleImportApi } from '../../api'
import FilterDeleteDialog from '../library/FilterDeleteDialog.vue'
import SubtitleInspectorWorkbench from '../library/SubtitleInspectorWorkbench.vue'

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
    subtitleFilterRules: (saved?.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule)).filter(rule => rule.pattern.trim())
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
const subtitleAudioFilterMode = ref('all')
const subtitleSubtitleFilterMode = ref('all')
const TASK_STATUS_REFRESH_MS = 4000
let taskStatusTimer = null
let skipTaskDraftPersistence = false

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
    subtitleFilterRules: (value.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule))
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
  return {
    ...task,
    search_attempts: Array.isArray(task?.search_attempts) ? task.search_attempts : [],
    download_files: trimTail(task?.download_files, 24),
    progress_log: trimTail(task?.progress_log, 24)
  }
}

function getFileName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
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

function getTaskStatusLabel(task) {
  if (!task) return '未知状态'
  if (task.manual_match_completed) return '已完成补配'
  if (task.status === 'processing') return '处理中'
  if (task.status === 'pending') return '排队中'
  if (task.status === 'failed') return '执行失败'
  if (task.awaiting_manual_match) return '待筛选与配对'
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
  return Boolean(task?.manual_match_completed || String(task?.status || '').toLowerCase() === 'completed')
}

function isProcessingTask(task) {
  return Boolean(String(task?.status || '').toLowerCase() === 'processing' || String(task?.status || '').toLowerCase() === 'pending' || task?.awaiting_manual_match)
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
  if (!String(task?.subtitle_dir || '').trim()) return false
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  return ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)
}

function canClearTask(task) {
  return Boolean(task && (isFailedTask(task) || isCompletedTask(task)))
}

function selectWorkbenchTask(taskId, options = {}) {
  const normalized = String(taskId || '')
  if (!normalized) return
  selectedTaskId.value = normalized
  const matchedTask = linkedTasks.value.find(task => task.id === normalized)
  if (matchedTask) activeTask.value = matchedTask
  if (props.visible && options.sync !== false && props.taskId !== normalized) {
    emit('select-task', normalized)
  }
}

function buildRetargetSourceRJCode(task) {
  return String(task?.actual_rjcode || task?.rjcode || task?.target_rjcode || '').trim().toUpperCase()
}

function ensureSelectedWorkbenchTask(tasks = []) {
  const preferredId = String(props.taskId || selectedTaskId.value || '')
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
    linkedTasks.value = sortLinkedTasks(
      (data.tasks || [])
        .filter(task => isLinkedSubtitleWorkbenchTask(task))
        .map(task => normalizeRJSubtitleTaskPayload(task))
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
    if (inspect && activeTask.value.subtitle_dir) {
      await inspectSubtitleTask(activeTask.value, { force: forceInspect })
    } else if (!activeTask.value.subtitle_dir) {
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
    ElMessage.warning('当前没有可清理的已完成或已失败任务')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定清空 ${targets.length} 条已完成或已失败任务吗？进行中的任务会保留。`,
      '清空队列确认',
      { confirmButtonText: '清空队列', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }

  queueClearing.value = true
  try {
    for (const task of targets) {
      await rjSubtitleApi.clearTask(task.id)
    }
    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    ElMessage.success(`已清空 ${targets.length} 条历史任务`)
  } catch (error) {
    ElMessage.error('清空队列失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    queueClearing.value = false
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
    const previewResult = await subtitleImportApi.previewFolder(task.subtitle_dir, {
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

    const result = await subtitleImportApi.importFolder(task.subtitle_dir, commonOptions)
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

function fileIcon(name = '') {
  const lower = String(name || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture
  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay
  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets
  return Document
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
  const { force = false } = options
  if (!task?.subtitle_dir) return
  if (task?.id && task.id !== selectedTaskId.value) {
    selectWorkbenchTask(task.id)
  }
  if (
    !force &&
    subtitleInspectorInfo.value.taskId === task.id &&
    subtitleInspectorInfo.value.subtitleDir === task.subtitle_dir &&
    !subtitleInspectorLoading.value
  ) {
    return
  }

  subtitleInspectorLoading.value = true
  try {
    persistSubtitleTaskDraft()
    const audioLibraryId = task.library_id || ''
    const subtitleLibraryId = task.subtitle_library_id || audioLibraryId
    const [subtitleData, audioData] = await Promise.all([
      libraryApi.browserFolderContents(subtitleLibraryId, task.subtitle_dir),
      libraryApi.browserFolderContents(audioLibraryId, task.folder_path)
    ])
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
      folderPath: task.folder_path || '',
      subtitleDir: subtitleData.folder_path || task.subtitle_dir,
      sourceMode: task.source_mode || '',
      totalFiles: subtitleData.total_files || 0,
      totalSize: (subtitleData.items || []).reduce((sum, item) => sum + (item.size || 0), 0)
    }
    const opened = new Set()
    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    subtitleInspectorExpandedIds.value = opened
    subtitleInspectorSelectedIds.value = new Set()
    subtitleInspectorLastSelectedId.value = ''
    await nextTick()
    const restored = restoreSubtitleTaskDraft(task.id)
    if (!restored) buildAutoSubtitlePairs()
    skipTaskDraftPersistence = false
    persistSubtitleTaskDraft(task.id)
  } catch (error) {
    ElMessage.error('加载字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))
  } finally {
    skipTaskDraftPersistence = false
    subtitleInspectorLoading.value = false
  }
}

async function reloadSubtitleInspector() {
  if (!activeTask.value?.subtitle_dir) return
  await inspectSubtitleTask(activeTask.value, { force: true })
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
    return subtitleInspectorExpandedIds.value.has(row.id) ? FolderOpened : Folder
  }
  return fileIcon(row?.name || '')
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
    await libraryApi.browserRename(subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId, subtitleRenameForm.value.path, subtitleRenameForm.value.newName)
    subtitleRenameDialogVisible.value = false
    ElMessage.success('字幕文件重命名成功')
    await reloadSubtitleInspector()
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
    await ElMessageBox.confirm(buildDeletePreviewMessage(preview), '删除确认', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger'
    })
    subtitleInspectorDeleting.value = true
    try {
      await libraryApi.browserDelete(inspectorLibraryId, path, true)
      ElMessage.success('删除成功')
      await reloadSubtitleInspector()
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
    await ElMessageBox.confirm(
      `确定批量删除 ${sortedRows.length} 项字幕文件/目录吗？此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' }
    )
  } catch (_) {
    return
  }

  subtitleInspectorDeleting.value = true
  try {
    for (const row of sortedRows) {
      const path = resolveSubtitleEntryPath(row)
      await libraryApi.browserDelete(subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId, path, true)
    }
    clearSubtitleInspectorSelection()
    ElMessage.success(`已删除 ${sortedRows.length} 项`)
    await reloadSubtitleInspector()
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

  if (!audioList.length || audioList.length !== subtitleList.length) {
    ElMessage.warning('请先按顺序点选数量一致的音频和字幕')
    return
  }

  const nextPairs = []
  for (let index = 0; index < audioList.length; index++) {
    nextPairs.push(createSubtitlePair(audioList[index], subtitleList[index], {
      confidenceLevel: 'medium',
      matchReason: '点选顺序'
    }))
  }

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => (
    !audioList.some(item => item.path === pair.audio_path) &&
    !subtitleList.some(item => item.path === pair.subtitle_path)
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

function buildAutoSubtitlePairs() {
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
    ElMessage.warning('没有生成可用的自动预匹配结果')
    return
  }
  subtitleManualPairs.value = pairs
  subtitleLastPairBuildMode.value = 'auto'
  subtitleSelectedManualPairId.value = pairs[0]?.id || ''
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
    item => !subtitleManualPairs.value.some(pair => pair.subtitle_path === item.path)
  )
  const unusedSubtitlePathSet = new Set(unusedSubtitleRows.map(item => item.path).filter(Boolean))

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
    if (existing?.path && unusedSubtitlePathSet.has(existing.path)) return false
    return existing && existing.path !== pair.subtitle_path
  })
  if (subtitleConflicts.length) {
    ElMessage.error(`存在目标字幕名冲突，无法直接应用：${subtitleConflicts[0].target_subtitle_name}`)
    return
  }

  const namingStrategyLabel = subtitleOptions.value.namingStrategy === 'subtitle' ? '以字幕名为准' : '以音频名为准'
  try {
    await ElMessageBox.confirm(
      `确定处理 ${subtitleManualPairs.value.length} 组配对结果吗？\n\n同名依据：${namingStrategyLabel}${unusedSubtitleRows.length ? `\n当前未使用的 ${unusedSubtitleRows.length} 个原始字幕会一并删除。` : ''}\n确认后会先在工作区完成重命名，再导入目标库存。`,
      '应用配对确认',
      { confirmButtonText: '重命名并导入', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }

  subtitlePairApplying.value = true
  const phaseOneRenamed = []
  const phaseTwoRenamed = []
  try {
    const currentSubtitleFiles = [...subtitleInspectorSubtitleFiles.value]
    const resolveCurrentSubtitleSourcePath = (pair) => {
      const exactMatch = currentSubtitleFiles.find(item => item.path === pair.subtitle_path)
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

    for (const pair of phaseOne) {
      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.source_path, pair.temp_name)
      pair.temp_path = renameResult?.new_path || joinPath(String(pair.source_path || '').replace(/[\\/][^\\/]+$/, ''), pair.temp_name)
      phaseOneRenamed.push(pair)
    }

    for (const pair of phaseOne) {
      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.temp_path, pair.target_name)
      pair.final_path = renameResult?.new_path || joinPath(String(pair.temp_path || '').replace(/[\\/][^\\/]+$/, ''), pair.target_name)
      phaseTwoRenamed.push(pair)
    }

    for (const subtitle of unusedSubtitleRows) {
      await libraryApi.browserDelete(subtitleLibraryId, resolveSubtitleEntryPath(subtitle), true)
    }

    const currentTaskId = activeTask.value?.id || props.taskId
    await rjSubtitleApi.completeManual(currentTaskId, {
      appliedPairs: appliedPairCount,
      deletedSubtitles: unusedSubtitleRows.length,
      namingStrategy: subtitleOptions.value.namingStrategy || 'audio'
    })

    clearSubtitleTaskDraft(currentTaskId)
    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    ElMessage.success(`已重命名并导入 ${appliedPairCount} 组配对${unusedSubtitleRows.length ? `，并删除 ${unusedSubtitleRows.length} 个未使用字幕` : ''}`)
    clearSubtitleManualPairs()
  } catch (error) {
    const rollbackErrors = []
    try {
      for (const pair of [...phaseTwoRenamed].reverse()) {
        const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        try {
          await libraryApi.browserRename(operationLibraryId, pair.final_path || pair.target_path || pair.temp_path, pair.current_name)
        } catch (rollbackError) {
          rollbackErrors.push(`${pair.target_name} -> ${pair.current_name}: ${rollbackError.response?.data?.detail || rollbackError.message}`)
        }
      }
      for (const pair of [...phaseOneRenamed].reverse()) {
        if (phaseTwoRenamed.includes(pair)) continue
        const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        try {
          await libraryApi.browserRename(operationLibraryId, pair.temp_path || pair.source_path, pair.current_name)
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
  await reloadSubtitleInspector()
}

const subtitleInspectorRoot = computed(() => buildTree(subtitleInspectorItems.value))
const subtitleInspectorFilteredRoot = computed(() => {
  const keyword = subtitleInspectorSearch.value.trim().toLowerCase()
  return keyword ? filterTree(subtitleInspectorRoot.value, keyword) : subtitleInspectorRoot.value
})
const subtitleInspectorFlatTree = computed(() => flattenTree(subtitleInspectorFilteredRoot.value, 0, subtitleInspectorExpandedIds.value))
const subtitleInspectorHasDirectories = computed(() => subtitleInspectorItems.value.some(item => item?.type === 'dir'))
const subtitleInspectorBusy = computed(() => subtitleInspectorLoading.value || subtitleInspectorDeleting.value || subtitlePairApplying.value)
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
  return audioCount > 0 && audioCount === subtitleCount
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
    window.clearInterval(taskStatusTimer)
    taskStatusTimer = null
  }
}

function startTaskStatusPolling() {
  if (taskStatusTimer || (!props.visible && !props.backgroundActive)) return
  taskStatusTimer = window.setInterval(() => {
    if (!props.visible && !props.backgroundActive) return
    refreshTaskStatus(false, { inspect: false, silent: true })
  }, TASK_STATUS_REFRESH_MS)
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

onUnmounted(() => {
  stopTaskStatusPolling()
})

const workbenchStatePayload = computed(() => ({
  total: linkedTasks.value.length,
  processing: processingTaskCount.value,
  completed: completedTaskCount.value,
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
  subtitlePairApplying: subtitlePairApplying.value,
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
  formatDate,
  openSubtitleRenameDialog,
  deleteSubtitleTreeEntry
}))
</script>

<style scoped>
.import-workbench-modal {
  display: grid;
  grid-template-rows: auto auto auto;
  gap: 12px;
  padding: 16px;
  overflow: visible;
  background:
    radial-gradient(circle at top right, rgba(116, 164, 255, 0.12), transparent 24%),
    linear-gradient(180deg, rgba(249, 252, 255, 0.98) 0%, #f4f8fe 100%);
}

.import-workbench-modal :deep(.el-empty) {
  padding: 24px 0 8px;
}

.import-workbench-modal :deep(.el-empty__image) {
  width: 80px;
  height: 80px;
  margin-bottom: 8px;
}

.import-workbench-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.import-workbench-title {
  font-size: 20px;
  font-weight: 700;
  color: #20344d;
}

.import-workbench-desc {
  margin-top: 2px;
  max-width: 780px;
  font-size: 11px;
  line-height: 1.5;
  color: #667a93;
}

.import-workbench-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.import-workbench-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border-radius: 14px;
  border: 1px solid #e3ebf7;
  background: rgba(255, 255, 255, 0.78);
}

.import-toolbar-stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid #d6e2f4;
  background: #fff;
  color: #415975;
  font-size: 11px;
  font-weight: 600;
}

.toolbar-pill-primary {
  border-color: #c9dcff;
  background: #edf4ff;
  color: #2a61ad;
}

.toolbar-pill-success {
  border-color: #cde9d0;
  background: #f2fbf3;
  color: #2f8a43;
}

.toolbar-pill-danger {
  border-color: #f0c9c9;
  background: #fff2f2;
  color: #c23d3d;
}

.import-toolbar-tip {
  font-size: 11px;
  line-height: 1.5;
  color: #6e8099;
}

.import-workbench-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  overflow: visible;
  min-width: 0;
  overflow-x: hidden;
}

.import-task-list-card,
.import-task-detail {
  border: 1px solid #e6edf7;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, #ffffff 100%);
  box-shadow: 0 8px 20px rgba(31, 46, 67, 0.05);
}

.import-task-list-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-height: 0;
  overflow: hidden;
  max-height: calc(100vh - 180px);
}

.import-task-list-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
  padding: 10px 12px 8px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.import-section-title {
  font-size: 14px;
  font-weight: 700;
  color: #24364f;
}

.import-section-tip {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: #71839b;
}

.import-task-list-body {
  display: grid;
  gap: 6px;
  max-height: calc(100vh - 150px);
  padding: 8px 12px;
  overflow: auto;
  min-width: 0;
  overflow-x: hidden;
}

.import-task-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 248px);
  gap: 14px;
  width: 100%;
  min-height: 96px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid #e4ebf7;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  text-align: left;
  align-items: start;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  min-width: 0;
}

.import-task-row:hover {
  border-color: #bfd4f6;
  box-shadow: 0 10px 24px rgba(59, 88, 135, 0.08);
  transform: translateY(-1px);
}

.import-task-row.active {
  border-color: #ffb000;
  box-shadow: 0 0 0 3px rgba(255, 176, 0, 0.5);
}

.import-task-row.failed {
  border-color: #efc4c4;
  background: linear-gradient(180deg, #fff8f8 0%, #fff2f2 100%);
}

.import-task-row.completed {
  border-color: #cce6cf;
  background: linear-gradient(180deg, #f8fff9 0%, #f1fbf2 100%);
}

.import-task-row.awaiting {
  border-color: #e4ebf7;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
}

.import-task-row.processing {
  border-color: #e4ebf7;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
}

.import-task-row-main {
  display: grid;
  gap: 6px;
  min-width: 0;
  align-content: start;
}

.import-task-row-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.import-task-row-rj {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  max-width: 100%;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 700;
  color: #2c5ea8;
  line-height: 1.2;
  white-space: nowrap;
}

.import-task-row-title {
  font-size: 14px;
  font-weight: 700;
  color: #223754;
  line-height: 1.35;
  word-break: break-word;
  min-width: 0;
  flex: 1 1 240px;
}

.import-task-row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  line-height: 1.45;
  color: #70829a;
}

.import-task-row-status {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
}

.import-task-row-side {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  justify-items: end;
  align-content: start;
  row-gap: 8px;
  min-width: 0;
  width: 100%;
}

.task-status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  min-width: 0;
  width: 100%;
  max-width: 110px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #d6e2f4;
  background: #fff;
  color: #415975;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}

.task-status-text {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

.task-status-pill.state-processing {
  border-color: #d6e2f4;
  background: #ffffff;
  color: #415975;
}

.task-status-pill.state-awaiting {
  border-color: #f1c85b;
  background: #fff7dc;
  color: #9c6a00;
}

.task-status-pill.state-completed {
  border-color: #cce6cf;
  background: #edf9ef;
  color: #2f8a43;
}

.task-status-text.state-completed {
  color: #2f8a43;
}

.task-status-pill.state-failed {
  border-color: #efc4c4;
  background: #fff1f1;
  color: #c23d3d;
}

.import-task-row-progress {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  font-size: 11px;
  line-height: 1.5;
  color: #62758f;
  text-align: right;
  white-space: normal;
}

.import-task-row-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.import-task-row-actions :deep(.el-button) {
  min-width: 58px;
  height: 28px;
  margin-left: 0;
}

.import-task-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 0 12px 12px;
}

.import-task-detail {
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  overflow: visible;
  align-items: start;
  min-width: 0;
}

.import-config-card {
  border-radius: 18px;
}

.import-task-main {
  grid-column: 2;
  display: grid;
  gap: 10px;
  min-width: 0;
}

.import-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 8px;
  border-radius: 999px;
  border: 1px solid #d8e4f5;
  background: #ffffff;
  color: #33527e;
  font-size: 11px;
  font-weight: 600;
}

.import-chip-primary {
  background: #edf4ff;
  border-color: #cfe0ff;
  color: #2458a6;
}

.import-config-head {
  font-size: 14px;
  font-weight: 700;
  color: #233750;
}

.import-config-card {
  border: 1px solid #e7edf6;
  background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
  grid-column: 1;
  position: sticky;
  top: 8px;
  align-self: start;
}

.import-config-card :deep(.el-card__header) {
  padding: 10px 12px 8px;
  border-bottom-color: #edf2f8;
}

.import-config-card :deep(.el-card__body) {
  padding: 10px 12px 12px;
  overflow-x: hidden;
}

.import-config-stack {
  display: grid;
  gap: 8px;
}

.import-config-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.import-config-row-wrap {
  padding-top: 2px;
}

.import-config-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.import-config-title {
  font-size: 13px;
  font-weight: 700;
  color: #223754;
}

.import-config-tip {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: #70829a;
}

.import-filter-list {
  display: grid;
  gap: 6px;
}

.import-filter-actions {
  display: flex;
  justify-content: flex-start;
}

.import-filter-empty {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px dashed #cfdcf2;
  color: #6a7d97;
  font-size: 12px;
  background: #fff;
}

.import-filter-item {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 8px 10px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid #e2ebfb;
  font-size: 12px;
  color: #415975;
}

.import-filter-editor {
  display: grid;
  gap: 5px;
  padding: 6px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid #e2ebfb;
}

.import-filter-editor-head {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.import-filter-target {
  width: 110px;
}

.import-config-inline-actions {
  display: flex;
  justify-content: flex-start;
}

.import-cleanup-summary {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f7fbf4;
  border: 1px solid #d8ebcf;
  color: #41603d;
  font-size: 12px;
  line-height: 1.7;
}

.import-retarget-current {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f6f9ff;
  border: 1px solid #d9e4fb;
  color: #30486f;
  font-size: 12px;
  line-height: 1.6;
  min-width: 0;
  overflow-wrap: anywhere;
}

.import-retarget-label {
  font-size: 12px;
  font-weight: 600;
  color: #6a7f9d;
}

.import-retarget-name {
  font-size: 14px;
  font-weight: 700;
  color: #223754;
  word-break: break-word;
}

.import-retarget-rj {
  display: inline-flex;
  align-self: flex-start;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(0, 113, 227, 0.08);
  color: #2458a6;
  font-size: 12px;
  font-weight: 700;
}

.import-retarget-path {
  color: #667b9e;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.candidate-list {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.candidate-item {
  display: grid;
  gap: 5px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e6edf6;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.candidate-item:hover {
  border-color: #bfd4f6;
  box-shadow: 0 8px 20px rgba(59, 88, 135, 0.08);
  transform: translateY(-1px);
}

.candidate-title {
  font-weight: 700;
  color: #24364f;
}

.candidate-meta,
.candidate-path {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11px;
  line-height: 1.5;
  color: #71839b;
}

.candidate-item :deep(.el-radio) {
  align-items: flex-start;
  white-space: normal;
}

.import-task-main > :deep(.el-alert) {
  border-radius: 16px;
}

.import-task-detail > :deep(.el-empty) {
  grid-column: 1 / -1;
  min-height: 240px;
  border-radius: 18px;
  border: 1px dashed #dbe6f5;
  background: linear-gradient(180deg, #fbfdff 0%, #ffffff 100%);
}

.import-task-main > :deep(.subtitle-inspector-workbench),
.import-task-main > :deep(.el-card) {
  border-radius: 18px;
}

.import-task-main > :deep(.subtitle-tree-card) {
  flex: 0 0 auto;
}

.import-task-main > :deep(.subtitle-tree-card .el-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 720px;
}

.import-task-placeholder {
  border: 1px dashed #d8e3f2;
  background: linear-gradient(180deg, #fbfdff 0%, #ffffff 100%);
}

.import-task-placeholder-title {
  font-size: 15px;
  font-weight: 700;
  color: #24364f;
}

.import-task-placeholder-text {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: #6d8099;
}

.name-preview {
  padding: 8px 12px;
  background: #f8f9fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  color: #606266;
  word-break: break-all;
}

@media (max-width: 960px) {
  .import-task-row {
    grid-template-columns: 1fr;
    min-height: 112px;
  }

  .import-task-row-side {
    grid-template-columns: 1fr;
  }

  .import-task-row-side,
  .import-task-row-status,
  .import-task-row-progress {
    justify-content: flex-start;
    text-align: left;
    width: 100%;
    justify-items: start;
  }

  .import-task-row-actions {
    justify-content: flex-start;
  }

  .import-task-list-body {
    max-height: none;
    padding-right: 0;
  }

  .import-workbench-modal {
    padding: 14px;
  }

  .import-task-detail {
    grid-template-columns: 1fr;
  }

  .import-config-card,
  .import-task-main {
    grid-column: 1;
  }
}

.import-workbench-modal {
  --apple-bg: #f5f5f7;
  --apple-surface: rgba(255, 255, 255, 0.94);
  --apple-surface-soft: rgba(255, 255, 255, 0.82);
  --apple-border: rgba(0, 0, 0, 0.06);
  --apple-text: #1d1d1f;
  --apple-text-soft: rgba(29, 29, 31, 0.72);
  --apple-text-muted: rgba(29, 29, 31, 0.52);
  --apple-blue: #0071e3;
  --apple-blue-soft: rgba(0, 113, 227, 0.08);
  --apple-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
  padding: 18px;
  gap: 14px;
  background:
    radial-gradient(circle at top left, rgba(0, 113, 227, 0.06), transparent 26%),
    linear-gradient(180deg, #fafafc 0%, #f5f5f7 100%);
}

.import-workbench-head {
  padding: 18px 20px;
  border: 1px solid var(--apple-border);
  border-radius: 26px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.84)),
    var(--apple-bg);
  box-shadow: var(--apple-shadow);
}

.import-workbench-title {
  font-size: 28px;
  line-height: 1.08;
  letter-spacing: -0.36px;
  color: var(--apple-text);
}

.import-workbench-desc,
.import-toolbar-tip,
.import-section-tip,
.import-task-row-meta,
.import-task-row-progress,
.import-config-tip,
.candidate-meta,
.candidate-path,
.import-task-placeholder-text {
  color: var(--apple-text-soft);
}

.import-workbench-actions :deep(.el-button),
.import-task-row-actions :deep(.el-button),
.import-config-inline-actions :deep(.el-button),
.import-filter-actions :deep(.el-button) {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.import-workbench-actions :deep(.el-button:hover),
.import-task-row-actions :deep(.el-button:hover),
.import-config-inline-actions :deep(.el-button:hover),
.import-filter-actions :deep(.el-button:hover) {
  transform: translateY(-1px);
}

.import-workbench-modal :deep(.el-button--default) {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.92);
  color: var(--apple-text);
}

.import-workbench-modal :deep(.el-button--default:hover) {
  border-color: rgba(0, 113, 227, 0.24);
  background: #ffffff;
  color: var(--apple-blue);
}

.import-workbench-modal :deep(.el-button--primary) {
  border-color: transparent;
  background: var(--apple-blue);
  box-shadow: 0 10px 20px rgba(0, 113, 227, 0.18);
}

.import-workbench-modal :deep(.el-button--primary:hover) {
  background: #0066cc;
}

.import-workbench-toolbar,
.import-task-list-card,
.import-task-detail,
.import-config-card {
  border: 1px solid var(--apple-border);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.88)),
    var(--apple-bg);
  box-shadow: var(--apple-shadow);
}

.import-workbench-toolbar {
  padding: 10px 14px;
  border-radius: 20px;
}

.toolbar-pill {
  border-color: rgba(0, 0, 0, 0.06);
  background: rgba(255, 255, 255, 0.92);
  color: var(--apple-text-soft);
}

.toolbar-pill-primary {
  border-color: rgba(0, 113, 227, 0.12);
  background: rgba(0, 113, 227, 0.08);
  color: var(--apple-blue);
}

.import-task-list-card,
.import-task-detail {
  border-radius: 24px;
}

.import-task-list-head,
.import-config-card :deep(.el-card__header) {
  border-bottom-color: rgba(0, 0, 0, 0.04);
  background: rgba(255, 255, 255, 0.68);
}

.import-section-title,
.import-config-head,
.import-config-title,
.import-task-row-title,
.candidate-title,
.import-task-placeholder-title {
  color: var(--apple-text);
}

.import-task-row {
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.import-task-row:hover {
  border-color: rgba(0, 113, 227, 0.18);
  box-shadow: 0 18px 34px rgba(15, 23, 42, 0.08);
}

.import-task-row.active {
  border-color: rgba(0, 113, 227, 0.22);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.1);
}

.import-task-row-rj,
.import-chip,
.import-chip-primary {
  border-radius: 999px;
}

.import-task-row-rj,
.import-chip-primary {
  background: rgba(0, 113, 227, 0.08);
  color: var(--apple-blue);
}

.import-task-row-rj {
  box-shadow: none;
  letter-spacing: 0.02em;
}

.task-status-pill {
  border-color: rgba(0, 0, 0, 0.06);
  background: rgba(255, 255, 255, 0.92);
}

.import-config-card {
  border-radius: 24px;
  position: sticky;
  top: 8px;
}

.import-config-card :deep(.el-card__body) {
  padding: 12px 14px 14px;
}

.import-config-row {
  padding: 10px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.import-config-row:last-child {
  border-bottom: 0;
}

.import-filter-editor,
.candidate-item,
.import-retarget-current,
.import-cleanup-summary,
.import-task-placeholder {
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.05);
}

.import-filter-editor {
  padding: 10px;
}

.candidate-item {
  padding: 12px 14px;
}

.candidate-item:hover {
  border-color: rgba(0, 113, 227, 0.18);
  box-shadow: 0 16px 30px rgba(15, 23, 42, 0.08);
}

.candidate-item :deep(.el-radio__input.is-checked .el-radio__inner) {
  background: var(--apple-blue);
  border-color: var(--apple-blue);
}

.import-workbench-modal :deep(.el-input__wrapper),
.import-workbench-modal :deep(.el-select__wrapper) {
  border-radius: 16px;
  background: rgba(250, 250, 252, 0.94);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06) inset;
}

.import-workbench-modal :deep(.el-input__wrapper.is-focus),
.import-workbench-modal :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.24) inset, 0 0 0 4px rgba(0, 113, 227, 0.08);
}

.import-workbench-modal :deep(.el-radio-button__inner) {
  border-radius: 999px;
}

.import-workbench-modal :deep(.el-alert) {
  border-radius: 18px;
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.import-task-main > :deep(.subtitle-inspector-workbench),
.import-task-main > :deep(.el-card) {
  border-radius: 24px;
  overflow: hidden;
}
</style>
