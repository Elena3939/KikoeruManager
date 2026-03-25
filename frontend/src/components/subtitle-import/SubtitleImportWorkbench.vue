<template>
  <el-card shadow="never" class="import-workbench-card">
    <template #header>
      <div class="import-workbench-head">
        <div>
          <div class="import-workbench-title">字幕补配工作台</div>
          <div class="import-workbench-desc">这里只处理当前字幕补配任务的筛选、配对和导入，不再带库存任务队列和下载进度。</div>
        </div>
        <div class="import-workbench-actions">
          <el-button size="small" :loading="taskLoading" @click="refreshTaskStatus(true, { inspect: true, forceInspect: true })">刷新状态</el-button>
          <el-button size="small" @click="handleClearTask">关闭工作台</el-button>
        </div>
      </div>
    </template>

    <el-empty v-if="!taskId" description="执行字幕补配后，这里会直接进入当前补配任务工作台。" />

    <div v-else class="import-workbench-layout">
      <el-card shadow="never" class="import-queue-card">
        <template #header>
          <div class="import-config-head">
            <span>补配队列</span>
            <el-tag size="small" type="info">待处理 {{ linkedTasks.length }}</el-tag>
          </div>
        </template>

        <el-empty v-if="!linkedTasks.length && !taskLoading" description="当前没有待处理的字幕补配任务。" />

        <div v-else class="import-queue-list">
          <button
            v-for="task in linkedTasks"
            :key="task.id"
            type="button"
            class="import-queue-item"
            :class="{ active: task.id === selectedTaskId }"
            @click="selectWorkbenchTask(task.id)"
          >
            <div class="import-queue-head">
              <strong>{{ task.folder_name || getFileName(task.folder_path) }}</strong>
              <el-tag size="small" :type="task.id === selectedTaskId ? 'primary' : 'info'">
                {{ task.manual_match_completed ? '已完成' : '待补配' }}
              </el-tag>
            </div>
            <div class="import-queue-meta">
              <span>{{ getTaskDisplayRJCode(task) }}</span>
              <span v-if="getTaskSourceRJCode(task)">来源 {{ getTaskSourceRJCode(task) }}</span>
              <span>{{ task.downloaded_count || 0 }} 字幕</span>
            </div>
            <div class="import-queue-path">{{ task.folder_path || '-' }}</div>
          </button>
        </div>
      </el-card>

      <div class="import-workbench-shell">
      <div v-if="activeTask" class="import-workbench-summary" :class="{ active: activeTask.id === selectedTaskId }">
        <div class="import-workbench-summary-main" :class="{ active: activeTask.id === selectedTaskId }">
          <div class="import-workbench-summary-title">{{ activeTask.folder_name || getFileName(activeTask.folder_path) }}</div>
          <div class="import-workbench-summary-path">{{ activeTask.folder_path || '-' }}</div>
          <div class="import-workbench-summary-chips">
            <span class="import-chip import-chip-primary">{{ getTaskDisplayRJCode(activeTask) }}</span>
            <span v-if="getTaskSourceRJCode(activeTask)" class="import-chip">来源 {{ getTaskSourceRJCode(activeTask) }}</span>
            <span class="import-chip">{{ getTaskStatusLabel(activeTask) }}</span>
            <span v-if="getTaskManualStateText(activeTask)" class="import-chip">{{ getTaskManualStateText(activeTask) }}</span>
          </div>
        </div>

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
                  <div class="import-config-tip">进入工作台前的过滤规则改成在这里维护，支持总开关、单条启停和即时编辑。</div>
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
          </div>
        </el-card>
      </div>

      <el-alert
        v-if="activeTask && !activeTask.subtitle_dir"
        title="当前任务还在准备字幕目录"
        type="info"
        :closable="false"
        show-icon
      >
        <template #default>
          {{ activeTask.current_step || '稍后刷新状态即可进入字幕补配工作台。' }}
        </template>
      </el-alert>

      <el-empty v-else-if="!taskLoading && !activeTask" description="没有找到当前字幕补配任务，可能已被清理或任务 ID 已失效。" />

      <SubtitleInspectorWorkbench
        v-else
        :ctx="subtitleWorkbenchCtx"
      />
    </div>

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
  </el-card>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, FolderOpened, Document, Picture, VideoPlay, Headset, Tickets } from '@element-plus/icons-vue'
import { libraryApi, rjSubtitleApi, subtitleImportApi } from '../../api'
import SubtitleInspectorWorkbench from '../library/SubtitleInspectorWorkbench.vue'

const props = defineProps({
  taskId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['clear-task', 'task-finished', 'select-task'])
const taskId = computed(() => props.taskId)

const SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'

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

function getSubtitleWorkbenchOptions() {
  const saved = loadJson(SUBTITLE_OPTIONS_KEY, {})
  return {
    namingStrategy: saved?.namingStrategy === 'subtitle' ? 'subtitle' : 'audio',
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: (saved?.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule)).filter(rule => rule.pattern.trim())
  }
}

const subtitleOptions = ref(getSubtitleWorkbenchOptions())
const taskLoading = ref(false)
const linkedTasks = ref([])
const activeTask = ref(null)
const selectedTaskId = ref('')
const subtitleRenameDialogVisible = ref(false)
const subtitleRenameForm = ref({ currentName: '', newName: '', path: '' })
const subtitleRenameLoading = ref(false)
const subtitleCleanupLoading = ref(false)
const subtitleCleanupSummary = ref('')

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

watch(() => subtitleOptions.value.namingStrategy, () => {
  syncSubtitlePairTargetNames()
})

watch(subtitleOptions, (value) => {
  saveJson(SUBTITLE_OPTIONS_KEY, {
    namingStrategy: value.namingStrategy === 'subtitle' ? 'subtitle' : 'audio',
    useFilterRules: value.useFilterRules !== false,
    subtitleFilterRules: (value.subtitleFilterRules || []).map(rule => normalizeSubtitleFilterRule(rule))
  })
}, { deep: true })

watch(() => props.taskId, async (value) => {
  selectedTaskId.value = String(value || '')
  if (!value) {
    activeTask.value = null
    linkedTasks.value = []
    clearSubtitleInspectorState()
    return
  }
  await refreshTaskStatus(false, { inspect: true, forceInspect: true })
}, { immediate: true })

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

function isPendingLinkedSubtitleWorkbenchTask(task) {
  return isLinkedSubtitleWorkbenchTask(task) && !task?.manual_match_completed && Boolean(task?.awaiting_manual_match || task?.subtitle_dir)
}

function selectWorkbenchTask(taskId, options = {}) {
  const normalized = String(taskId || '')
  if (!normalized) return
  selectedTaskId.value = normalized
  if (options.sync !== false && props.taskId !== normalized) {
    emit('select-task', normalized)
  }
}

function ensureSelectedWorkbenchTask(tasks = []) {
  const preferredId = String(props.taskId || selectedTaskId.value || '')
  const matched = (preferredId && tasks.find(task => task.id === preferredId)) || tasks[0] || null
  if (!matched) {
    selectedTaskId.value = ''
    return null
  }
  if (selectedTaskId.value !== matched.id) {
    selectedTaskId.value = matched.id
  }
  if (props.taskId !== matched.id) {
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

function canCloseWorkbenchTask(task) {
  if (linkedTasks.value.length) return false
  if (!task) return true
  return Boolean(task.manual_match_completed || !task.awaiting_manual_match)
}

function handleClearTask() {
  if (!canCloseWorkbenchTask(activeTask.value)) {
    ElMessage.warning('这条字幕补配还没完成重命名导入，页面刷新后也会继续回到当前工作台')
    return
  }
  emit('clear-task')
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
  const { inspect = true, forceInspect = false } = options
  if (!props.taskId && !selectedTaskId.value) return

  taskLoading.value = true
  try {
    const data = await rjSubtitleApi.status()
    linkedTasks.value = (data.tasks || [])
      .filter(task => isPendingLinkedSubtitleWorkbenchTask(task))
      .map(task => normalizeRJSubtitleTaskPayload(task))

    const found = ensureSelectedWorkbenchTask(linkedTasks.value)
    if (!found) {
      activeTask.value = null
      clearSubtitleInspectorState()
      subtitleCleanupSummary.value = ''
      emit('task-finished', props.taskId || selectedTaskId.value)
      if (showMessage) ElMessage.warning('没有找到待处理的字幕补配任务')
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
    taskLoading.value = false
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
    const audioLibraryId = task.library_id || ''
    const subtitleLibraryId = task.subtitle_library_id || audioLibraryId
    const [subtitleData, audioData] = await Promise.all([
      libraryApi.browserFolderContents(subtitleLibraryId, task.subtitle_dir),
      libraryApi.browserFolderContents(audioLibraryId, task.folder_path)
    ])
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
    buildAutoSubtitlePairs()
  } catch (error) {
    ElMessage.error('加载字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))
  } finally {
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
  const sequenceCleanupRows = subtitleLastPairBuildMode.value === 'sequence'
    ? subtitleInspectorSubtitleFiles.value.filter(item => !subtitleManualPairs.value.some(pair => pair.subtitle_path === item.path))
    : []

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
    return existing && existing.path !== pair.subtitle_path
  })
  if (subtitleConflicts.length) {
    ElMessage.error(`存在目标字幕名冲突，无法直接应用：${subtitleConflicts[0].target_subtitle_name}`)
    return
  }

  const namingStrategyLabel = subtitleOptions.value.namingStrategy === 'subtitle' ? '以字幕名为准' : '以音频名为准'
  try {
    await ElMessageBox.confirm(
      `确定处理 ${subtitleManualPairs.value.length} 组配对结果吗？\n\n同名依据：${namingStrategyLabel}${sequenceCleanupRows.length ? `\n未纳入顺序配对的 ${sequenceCleanupRows.length} 个原始字幕会一并删除。` : ''}\n确认后会先在工作区完成重命名，再导入目标库存。`,
      '应用配对确认',
      { confirmButtonText: '重命名并导入', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }

  subtitlePairApplying.value = true
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
    }

    for (const pair of phaseOne) {
      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
      await libraryApi.browserRename(operationLibraryId, pair.temp_path, pair.target_name)
    }

    for (const subtitle of sequenceCleanupRows) {
      await libraryApi.browserDelete(subtitleLibraryId, resolveSubtitleEntryPath(subtitle), true)
    }

    const currentTaskId = activeTask.value?.id || props.taskId
    await rjSubtitleApi.completeManual(currentTaskId, {
      appliedPairs: appliedPairCount,
      deletedSubtitles: sequenceCleanupRows.length,
      namingStrategy: subtitleOptions.value.namingStrategy || 'audio'
    })

    await refreshTaskStatus(false, { inspect: true, forceInspect: true })
    emit('task-finished', currentTaskId)
    ElMessage.success(`已重命名并导入 ${appliedPairCount} 组配对${sequenceCleanupRows.length ? `，并删除 ${sequenceCleanupRows.length} 个未选字幕` : ''}`)
    clearSubtitleManualPairs()
  } catch (error) {
    ElMessage.error('重命名并导入失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitlePairApplying.value = false
  }
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
.import-workbench-card {
  border: 1px solid #e6edf7;
  border-radius: 22px;
  background:
    radial-gradient(circle at top right, rgba(116, 164, 255, 0.10), transparent 26%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, #ffffff 100%);
  box-shadow: 0 12px 30px rgba(31, 46, 67, 0.07);
  overflow: hidden;
}

.import-workbench-card :deep(.el-card__header) {
  padding: 16px 18px 12px;
  border-bottom-color: #edf2f8;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.92) 0%, rgba(255, 255, 255, 0.96) 100%);
}

.import-workbench-card :deep(.el-card__body) {
  padding: 16px 18px 18px;
}

.import-workbench-card :deep(.el-empty) {
  padding: 24px 0 8px;
}

.import-workbench-card :deep(.el-empty__image) {
  width: 88px;
  height: 88px;
  margin-bottom: 8px;
}

.import-workbench-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.import-workbench-title {
  font-size: 22px;
  font-weight: 700;
  color: #20344d;
}

.import-workbench-desc {
  margin-top: 4px;
  max-width: 920px;
  font-size: 12px;
  line-height: 1.6;
  color: #667a93;
}

.import-workbench-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.import-workbench-layout {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

.import-workbench-shell {
  display: grid;
  gap: 12px;
}

.import-queue-card {
  border: 1px solid #e7edf6;
  border-radius: 18px;
  position: sticky;
  top: 14px;
  overflow: hidden;
}

.import-queue-card :deep(.el-card__header) {
  padding: 12px 14px 10px;
  border-bottom-color: #edf2f8;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.import-queue-card :deep(.el-card__body) {
  padding: 12px;
}

.import-queue-list {
  display: grid;
  gap: 8px;
  max-height: calc(100vh - 280px);
  overflow: auto;
  padding-right: 4px;
}

.import-queue-item {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid #e5ecf7;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.import-queue-item:hover {
  border-color: #bfd4f6;
  box-shadow: 0 10px 24px rgba(59, 88, 135, 0.08);
  transform: translateY(-1px);
}

.import-queue-item.active {
  border-color: #6ea8ff;
  background: linear-gradient(180deg, #f6faff 0%, #eef5ff 100%);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.12);
  transform: translateY(-1px);
  position: relative;
}

.import-queue-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 4px;
  border-radius: 999px;
  background: linear-gradient(180deg, #409eff 0%, #66b1ff 100%);
}

.import-queue-head,
.import-queue-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.import-queue-meta,
.import-queue-path {
  font-size: 12px;
  line-height: 1.6;
  color: #70829a;
}

.import-workbench-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 12px;
  align-items: start;
}

.import-workbench-summary-main,
.import-config-card {
  border-radius: 18px;
}

.import-workbench-summary-main {
  padding: 14px 16px;
  border: 1px solid #e4ecf7;
  background: linear-gradient(135deg, #f8fbff 0%, #f3f8ff 100%);
  min-height: 112px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.import-workbench-summary-main.active {
  border-color: #6ea8ff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.10);
  background: linear-gradient(135deg, #f4f9ff 0%, #edf5ff 100%);
}

.import-workbench-summary-title {
  font-size: 16px;
  font-weight: 700;
  color: #223754;
}

.import-workbench-summary-path {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #70829a;
  word-break: break-all;
}

.import-workbench-summary-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.import-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid #d8e4f5;
  background: #ffffff;
  color: #33527e;
  font-size: 12px;
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
  height: 100%;
}

.import-config-card :deep(.el-card__header) {
  padding: 12px 14px 10px;
  border-bottom-color: #edf2f8;
}

.import-config-card :deep(.el-card__body) {
  padding: 12px 14px 14px;
}

.import-config-stack {
  display: grid;
  gap: 10px;
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
  font-size: 14px;
  font-weight: 700;
  color: #223754;
}

.import-config-tip {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.5;
  color: #70829a;
}

.import-filter-list {
  display: grid;
  gap: 8px;
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
  gap: 6px;
  padding: 8px;
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

.import-workbench-shell > :deep(.el-alert) {
  border-radius: 16px;
}

.import-workbench-shell > :deep(.el-empty) {
  min-height: 240px;
  border-radius: 18px;
  border: 1px dashed #dbe6f5;
  background: linear-gradient(180deg, #fbfdff 0%, #ffffff 100%);
}

.import-workbench-shell > :deep(.subtitle-inspector-workbench),
.import-workbench-shell > :deep(.el-card) {
  border-radius: 18px;
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
  .import-workbench-layout {
    grid-template-columns: 1fr;
  }

  .import-workbench-summary {
    grid-template-columns: 1fr;
  }

  .import-queue-card {
    position: static;
  }

  .import-queue-list {
    max-height: none;
    padding-right: 0;
  }
}
</style>
