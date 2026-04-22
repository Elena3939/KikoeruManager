import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { rjSubtitleApi } from '../api'
import { showSystemConfirm } from '../composables/useSystemPrompt'

export function useSubtitleTask ({
  selectedLibraryId,
  subtitleDialogVisible,
  subtitleDialogBackgroundActive,
  subtitleInspectorInfo,
  subtitlePreferredSelectionKey,
  subtitleDialogSelection,
  subtitleForceQueueKey,
  subtitleOptions,
  clearSubtitleInspectorState,
  syncSubtitleInspectorTaskState,
  ensureSubtitleInspectorFocus
}) {
  // ─── Owned reactive state ────────────────────────────────────────────────
  const subtitleTasks = ref([])
  const subtitleActiveTaskId = ref('')
  const subtitleTaskFilter = ref('all')
  const subtitleTaskManualFilter = ref('all')
  const subtitleCancelingId = ref('')
  const subtitleTasksLoading = ref(false)
  const subtitleBulkClearingScope = ref('')
  const subtitleTaskDetailPanels = ref([])
  const subtitleDownloadExpandedMap = ref({})
  const subtitleIssueExpandedMap = ref({})
  const subtitleTaskRerunId = ref('')
  let subtitleStatusPollTimer = null

  // ─── Constants ───────────────────────────────────────────────────────────
  const linkedSubtitleImportSourceModes = new Set(['linked_translation_archive_import', 'subtitle_folder_import'])

  // ─── Inline utilities ────────────────────────────────────────────────────
  function getFileName (path) {
    if (!path) return ''
    return String(path).split(/[\\/]/).pop()
  }

  function extractRJCode (value) {
    if (!value) return null
    const match = String(value).match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)
    return match ? match[0].toUpperCase() : null
  }

  function stripTrailingAudioExtension (value = '') {
    let current = String(value || '')
    while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
      current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
    }
    return current
  }

  function decodePossibleMojibake (value) {
    const text = String(value || '')
    if (!/[ÃÂÐæçéèêïîöôåäüë鈥]/.test(text) && !/[鐩鍙彇瀛]/.test(text)) return text
    try {
      const bytes = Uint8Array.from(Array.from(text).map(char => char.charCodeAt(0) & 0xff))
      const decoded = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
      return decoded && /[\u4e00-\u9fff]/.test(decoded) ? decoded : text
    } catch (_) {
      return text
    }
  }

  function uniqueSubtitleItems (items) {
    const seen = new Set()
    return items.filter(item => {
      if (!item?.folder_path || !item?.rjcode) return false
      const dedupeKey = `${item.library_id || ''}::${item.folder_path}`
      if (seen.has(dedupeKey)) return false
      seen.add(dedupeKey)
      return true
    })
  }

  // ─── Subtitle filter rule helpers ────────────────────────────────────────
  function createSubtitleFilterRule (overrides = {}) {
    return {
      id: `subtitle-filter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      target: 'name',
      name: '',
      pattern: '',
      enabled: true,
      ...overrides
    }
  }

  function normalizeSubtitleFilterRule (rule = {}) {
    return createSubtitleFilterRule({
      id: rule.id || undefined,
      target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',
      name: String(rule.name || ''),
      pattern: String(rule.pattern || ''),
      enabled: rule.enabled !== false
    })
  }

  function sanitizeSubtitleFilterRules (rules = []) {
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

  // ─── Pure task utility functions ─────────────────────────────────────────
  function normalizeSubtitleTaskSourceMode (value) {
    return String(value || '').trim().toLowerCase()
  }

  function isLinkedSubtitleImportSourceMode (value) {
    return linkedSubtitleImportSourceModes.has(normalizeSubtitleTaskSourceMode(value))
  }

  function isRJSubtitleTaskCancelled (taskOrStatus) {
    if (!taskOrStatus) return false
    if (typeof taskOrStatus === 'object') {
      return Boolean(taskOrStatus.is_cancelled) || taskOrStatus.error_message === '用户取消'
    }
    return false
  }

  function isSubtitleTaskAwaitingManualWork (task) {
    if (!task || isRJSubtitleTaskCancelled(task)) return false
    if (task.manual_match_completed) return false
    return Boolean(task.awaiting_manual_match || task.status === 'completed')
  }

  function subtitleTaskTimeValue (task, field = 'created_at') {
    const raw = task?.[field]
    const value = raw ? Date.parse(raw) : NaN
    return Number.isFinite(value) ? value : 0
  }

  function sortSubtitleTasksByCreatedAt (tasks = []) {
    return [...tasks].sort((left, right) => subtitleTaskTimeValue(right) - subtitleTaskTimeValue(left))
  }

  function subtitleTaskSortWeight (task) {
    if (!task) return 99
    if (task.status === 'processing') return 0
    if (task.status === 'pending') return 1
    if (task.status === 'paused') return 2
    if (isSubtitleTaskAwaitingManualWork(task)) return 3
    if (task.status === 'failed') return 4
    if (task.manual_match_completed) return 5
    if (task.status === 'completed') return 6
    return 7
  }

  function sortSubtitleTasksForWorkbench (tasks = []) {
    return [...tasks].sort((left, right) => {
      const weightDiff = subtitleTaskSortWeight(left) - subtitleTaskSortWeight(right)
      if (weightDiff !== 0) return weightDiff
      return subtitleTaskTimeValue(right) - subtitleTaskTimeValue(left)
    })
  }

  function compareSubtitleWorkbenchNames (left, right) {
    return String(left || '').localeCompare(String(right || ''), 'zh-Hans-CN-u-kn-true')
  }

  function matchesSubtitleTaskFilter (task, filter = subtitleTaskFilter.value) {
    if (filter === 'all') return true
    if (filter === 'processing') return task?.status === 'processing'
    if (filter === 'pending') return task?.status === 'pending'
    if (filter === 'completed') return task?.status === 'completed' && !task?.manual_match_completed
    if (filter === 'matched') return Boolean(task?.manual_match_completed)
    if (filter === 'failed') return task?.status === 'failed' || isRJSubtitleTaskCancelled(task)
    return true
  }

  function matchesSubtitleTaskManualFilter (task, filter = subtitleTaskManualFilter.value) {
    if (filter === 'all') return true
    if (filter === 'awaiting_manual_match') return isSubtitleTaskAwaitingManualWork(task)
    if (filter === 'manual_match_completed') return Boolean(task?.manual_match_completed)
    if (filter === 'processing') return task?.status === 'processing'
    if (filter === 'pending') return task?.status === 'pending'
    if (filter === 'failed') return task?.status === 'failed' || isRJSubtitleTaskCancelled(task)
    return true
  }

  function getSubtitleTaskFilterResultCount (taskFilter = subtitleTaskFilter.value, manualFilter = subtitleTaskManualFilter.value) {
    return subtitleTasks.value.filter(task => (
      matchesSubtitleTaskFilter(task, taskFilter)
      && matchesSubtitleTaskManualFilter(task, manualFilter)
    )).length
  }

  function normalizeSubtitleTaskFilterSelection (nextTaskFilter, nextManualFilter) {
    const taskFilter = nextTaskFilter || 'all'
    const manualFilter = nextManualFilter || 'all'
    if (!subtitleTasks.value.length) {
      return { taskFilter: 'all', manualFilter: 'all' }
    }
    if (getSubtitleTaskFilterResultCount(taskFilter, manualFilter) > 0) {
      return { taskFilter, manualFilter }
    }
    if (manualFilter !== 'all' && getSubtitleTaskFilterResultCount(taskFilter, 'all') > 0) {
      return { taskFilter, manualFilter: 'all' }
    }
    if (taskFilter !== 'all' && getSubtitleTaskFilterResultCount('all', manualFilter) > 0) {
      return { taskFilter: 'all', manualFilter }
    }
    return { taskFilter: 'all', manualFilter: 'all' }
  }

  function estimateSubtitleTaskAudioCount (task) {
    if (!task) return null
    const matchedGroups = Number(task.match_result?.matched_group_count || 0)
    const unmatchedAudio = Number(task.match_result?.unmatched_audio?.length || 0)
    const estimated = matchedGroups + unmatchedAudio
    return estimated > 0 ? estimated : null
  }

  function estimateSubtitleTaskExistingCount (task) {
    if (!task) return null
    const explicitCount = Number(task.existing_subtitle_count)
    if (Number.isFinite(explicitCount) && explicitCount > 0) return explicitCount
    const written = Number(task.written_files?.length || 0)
    const skipped = Number(task.skipped_files?.length || 0)
    const matched = Number(task.match_result?.matched_subtitle_count || 0)
    return Math.max(written + skipped, matched, 0)
  }

  function buildSubtitleSelectionKey (item) {
    if (!item?.folder_path) return ''
    return `${item.library_id || selectedLibraryId.value || ''}::${String(item.folder_path).replace(/\\/g, '/')}`
  }

  function buildSubtitleTaskSelectionKey (task) {
    if (!task?.folder_path) return ''
    return `${task.library_id || selectedLibraryId.value || ''}::${String(task.folder_path).replace(/\\/g, '/')}`
  }

  function findSubtitleTaskBySelection (item, tasks = subtitleTasks.value) {
    const selectionKey = buildSubtitleSelectionKey(item)
    if (!selectionKey) return null
    return sortSubtitleTasksByCreatedAt(tasks).find(task => buildSubtitleTaskSelectionKey(task) === selectionKey) || null
  }

  function findTaskMatchingPreferredSelection (tasks = subtitleTasks.value) {
    if (!subtitlePreferredSelectionKey.value) return null
    return sortSubtitleTasksByCreatedAt(tasks).find(task => buildSubtitleTaskSelectionKey(task) === subtitlePreferredSelectionKey.value) || null
  }

  function buildSubtitleSelectionItemFromTask (task = {}) {
    return {
      library_id: task.library_id || selectedLibraryId.value,
      folder_path: task.folder_path || '',
      folder_name: task.folder_name || getFileName(task.folder_path),
      rjcode: task.rjcode || task.actual_rjcode || '',
      audio_count: task.audio_count ?? null,
      existing_subtitle_count: task.existing_subtitle_count ?? 0,
      status: Number(task.existing_subtitle_count || 0) > 0 ? 'existing' : 'ready'
    }
  }

  function getTaskDisplayRJCode (task) {
    return (
      task?.rjcode ||
      task?.actual_rjcode ||
      extractRJCode(task?.folder_path || '') ||
      extractRJCode(task?.folder_name || '') ||
      '未知RJ'
    )
  }

  function getTaskSourceRJCode (task) {
    const sourceRJ = String(task?.actual_rjcode || '').trim()
    const folderRJ = String(task?.rjcode || '').trim()
    return sourceRJ && sourceRJ !== folderRJ ? sourceRJ : ''
  }

  function getRJSubtitleTaskStatusLabel (taskOrStatus) {
    if (isRJSubtitleTaskCancelled(taskOrStatus)) return '已取消'
    if (typeof taskOrStatus === 'object') {
      if (taskOrStatus.manual_match_completed) return '已匹配完成'
      if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) {
        return taskOrStatus.awaiting_manual_match ? '筛选并匹配' : '待处理'
      }
    }
    const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
    const labels = { pending: '待处理', processing: '处理中', completed: '已完成', failed: '失败' }
    return labels[status] || status
  }

  function getRJSubtitleTaskBaseStatusLabel (taskOrStatus) {
    if (isRJSubtitleTaskCancelled(taskOrStatus)) return '已取消'
    if (typeof taskOrStatus === 'object') {
      if (taskOrStatus.manual_match_completed) return '已完成'
      if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return '待处理'
    }
    const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
    const labels = { pending: '待处理', processing: '处理中', completed: '已完成', failed: '失败' }
    return labels[status] || status
  }

  function getRJSubtitleTaskStatusType (taskOrStatus) {
    if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'info'
    if (typeof taskOrStatus === 'object') {
      if (taskOrStatus.manual_match_completed) return 'success'
      if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'warning'
    }
    const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
    const types = { pending: 'info', processing: 'warning', completed: 'success', failed: 'danger' }
    return types[status] || 'info'
  }

  function getRJSubtitleTaskBaseStatusType (taskOrStatus) {
    if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'info'
    if (typeof taskOrStatus === 'object') {
      if (taskOrStatus.manual_match_completed) return 'success'
      if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'warning'
    }
    const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
    const types = { pending: 'info', processing: 'warning', completed: 'success', failed: 'danger' }
    return types[status] || 'info'
  }

  function getRJSubtitleTaskStatusClass (taskOrStatus) {
    if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'cancelled'
    if (typeof taskOrStatus === 'object') {
      if (taskOrStatus.manual_match_completed) return 'manual_match_completed'
      if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'awaiting_manual_match'
      return taskOrStatus.status || 'pending'
    }
    return taskOrStatus || 'pending'
  }

  function getRJSubtitleProgressStatus (task) {
    if (!task) return ''
    if (isRJSubtitleTaskCancelled(task)) return undefined
    if (task.status === 'failed') return 'exception'
    if (task.manual_match_completed) return 'success'
    if (isSubtitleTaskAwaitingManualWork(task)) return 'warning'
    return ''
  }

  function canCancelRJSubtitleTask (task) {
    if (!task?.id) return false
    if (subtitleCancelingId.value === task.id) return false
    if (isRJSubtitleTaskCancelled(task)) return false
    return ['pending', 'processing'].includes(task.status)
  }

  function canClearCurrentSubtitleTask (task) {
    if (!task?.id) return false
    if (['pending', 'processing'].includes(task.status)) return false
    return true
  }

  function canRerunSubtitleTask (task) {
    if (!task?.folder_path || !task?.id) return false
    if (['pending', 'processing'].includes(task.status)) return false
    return !subtitleTaskRerunId.value && !subtitleForceQueueKey.value
  }

  function getSubtitleTaskInspectLabel (task) {
    if (!task?.subtitle_dir) return '等待字幕生成'
    if (task.manual_match_completed) return '已匹配完成'
    if (isSubtitleTaskAwaitingManualWork(task)) {
      return task.awaiting_manual_match ? '筛选并匹配' : '检查字幕树'
    }
    return '检查字幕树'
  }

  function getSubtitleTaskManualStateText (task) {
    if (!task) return ''
    if (task.manual_match_completed) return `已匹配完成 ${task.manual_match_applied_pairs || 0}`
    if (isSubtitleTaskAwaitingManualWork(task)) {
      return task.awaiting_manual_match ? '筛选并匹配' : '待处理'
    }
    return ''
  }

  function getSubtitleTaskManualStateChipClass (task) {
    if (!task) return ''
    if (task.manual_match_completed) return 'is-success'
    if (isSubtitleTaskAwaitingManualWork(task)) return 'is-warning'
    return ''
  }

  function isSubtitleTaskSelected (task) {
    if (!task?.id) return false
    return activeSubtitleTask.value?.id === task.id || subtitleInspectorInfo.value.taskId === task.id
  }

  function buildDefaultSubtitleTaskDetailPanels (task) {
    if (!task) return []
    if (task.status === 'processing') return ['download', 'log']
    if (task.status === 'failed' || isRJSubtitleTaskCancelled(task)) return ['issues', 'log']
    if (task.manual_match_completed) return ['written', 'log']
    if (isSubtitleTaskAwaitingManualWork(task)) return ['written', 'download']
    if (task.status === 'completed') return ['written']
    return []
  }

  function buildSubtitleManualMatchSummary (payload = {}) {
    const appliedPairs = Math.max(0, Number(payload.appliedPairs || 0))
    const deletedSubtitles = Math.max(0, Number(payload.deletedSubtitles || 0))
    let summary = `已应用 ${appliedPairs} 组配对`
    if (deletedSubtitles > 0) summary += `，并删除 ${deletedSubtitles} 个未使用字幕`
    return summary
  }

  function getRJSubtitleLangLabel (lang) {
    const labels = { CHI_HANS: '简中', CHI_SIMP: '简中', CHI_HANT: '繁中', CHI_TRAD: '繁中', JPN: '日文', JAP: '日文', ENG: '英文' }
    return labels[lang] || lang || '-'
  }

  function formatRJSubtitleAttempt (attempt) {
    if (!attempt) return '-'
    if (attempt.reason) return attempt.reason
    return `${attempt.subtitle_count || 0} 个字幕`
  }

  function getProgressLogLevelLabel (level) {
    const labels = { info: '信息', success: '完成', warning: '注意', error: '错误' }
    return labels[level] || '信息'
  }

  function formatProgressLogTime (value) {
    if (!value) return '--:--:--'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleTimeString('zh-CN', { hour12: false })
  }

  function normalizeSubtitleWriteError (value) {
    const raw = decodePossibleMojibake(String(value || '').trim())
    if (!raw) return { name: '未知文件', detail: '' }
    const separatorIndex = raw.indexOf(':')
    if (separatorIndex === -1) return { name: raw, detail: '' }
    const name = raw.slice(0, separatorIndex).trim() || '未知文件'
    let detail = decodePossibleMojibake(raw.slice(separatorIndex + 1).trim())
    if (detail.includes('Attempt to decode JSON with unexpected mimetype: text/plain')) {
      detail = '群晖上传接口返回了 text/plain 响应，旧版客户端把它误判成 JSON 解析失败。刷新后重新执行即可。'
    } else if (detail.includes('"code": 401') || detail.includes("'code': 401")) {
      detail = '群晖返回文件操作错误（401）。这通常不是字幕匹配失败，而是远程上传阶段对文件名编码或 multipart 参数不兼容导致的写入失败。'
    }
    return { name, detail }
  }

  function normalizeSubtitleWriteErrors (items) {
    return (items || []).map(normalizeSubtitleWriteError)
  }

  function isAudioFileName (name = '') {
    return /\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)
  }

  function isSubtitleFileName (name = '') {
    return /\.(lrc|srt|ass|ssa|vtt)$/i.test(name)
  }

  function isSubtitleRelativePath (relativePath = '') {
    const normalized = String(relativePath || '').replace(/\\/g, '/').toLowerCase().replace(/^\/+/, '')
    return normalized === 'subtitles' || normalized.startsWith('subtitles/')
  }

  function normalizeSubtitleDownloadKey (name) {
    let current = String(name || '')
    const subtitleExts = ['.lrc', '.vtt', '.srt', '.ass', '.ssa']
    const audioExts = ['.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac']
    let subtitleExt = ''
    for (const ext of subtitleExts) {
      if (current.toLowerCase().endsWith(ext)) {
        subtitleExt = ext
        current = current.slice(0, -ext.length)
        break
      }
    }
    while (audioExts.some(ext => current.toLowerCase().endsWith(ext))) {
      const matchedExt = audioExts.find(ext => current.toLowerCase().endsWith(ext))
      current = current.slice(0, -matchedExt.length)
    }
    return `${current.toLowerCase()}${subtitleExt}`
  }

  function getSubtitleDownloadFiles (task) {
    const deduped = new Map()
    for (const file of task?.download_files || []) {
      const name = String(file?.name || '')
      const key = normalizeSubtitleDownloadKey(file?.name || '')
      const existing = deduped.get(key)
      if (!existing) {
        deduped.set(key, file)
        continue
      }
      const currentIsWav = name.toLowerCase().includes('.wav.')
      const existingIsWav = String(existing?.name || '').toLowerCase().includes('.wav.')
      if (currentIsWav && !existingIsWav) {
        deduped.set(key, file)
        continue
      }
      if (currentIsWav === existingIsWav && Number(file?.progress || 0) > Number(existing?.progress || 0)) {
        deduped.set(key, file)
      }
    }
    return Array.from(deduped.values())
  }

  function getSubtitleDownloadDisplayName (file) {
    const displayName = String(file?.display_name || file?.name || '字幕文件')
    const extMatch = displayName.match(/\.[^.]+$/)
    const subtitleExt = extMatch?.[0] || ''
    const baseName = subtitleExt ? displayName.slice(0, -subtitleExt.length) : displayName
    const normalizedBase = stripTrailingAudioExtension(baseName)
    return subtitleExt ? `${normalizedBase}${subtitleExt}` : normalizedBase
  }

  function allSubtitleDownloadsCompleted (task) {
    const files = getSubtitleDownloadFiles(task)
    return files.length > 0 && files.every(file => Number(file?.progress || 0) >= 100)
  }

  function isSubtitleDownloadExpanded (taskId) {
    return Boolean(subtitleDownloadExpandedMap.value[taskId])
  }

  function toggleSubtitleDownloadExpanded (taskId) {
    if (!taskId) return
    subtitleDownloadExpandedMap.value = {
      ...subtitleDownloadExpandedMap.value,
      [taskId]: !subtitleDownloadExpandedMap.value[taskId]
    }
  }

  function visibleSubtitleDownloadFiles (task) {
    const files = getSubtitleDownloadFiles(task)
    if (!files.length) return []
    if (!allSubtitleDownloadsCompleted(task) || isSubtitleDownloadExpanded(task?.id)) return files
    return files.slice(0, 6)
  }

  function hiddenSubtitleDownloadCount (task) {
    return Math.max(0, getSubtitleDownloadFiles(task).length - visibleSubtitleDownloadFiles(task).length)
  }

  function isSubtitleIssueExpanded (taskId) {
    return Boolean(subtitleIssueExpandedMap.value[taskId])
  }

  function toggleSubtitleIssueExpanded (taskId) {
    if (!taskId) return
    subtitleIssueExpandedMap.value = {
      ...subtitleIssueExpandedMap.value,
      [taskId]: !subtitleIssueExpandedMap.value[taskId]
    }
  }

  function visibleSubtitleWriteErrors (task) {
    const items = normalizeSubtitleWriteErrors(task?.write_errors)
    if (isSubtitleIssueExpanded(task?.id)) return items
    return items.slice(0, 6)
  }

  function visibleSubtitleFailedFiles (task) {
    const items = task?.failed_files || []
    if (isSubtitleIssueExpanded(task?.id)) return items
    const remainingSlots = Math.max(0, 6 - visibleSubtitleWriteErrors(task).length)
    return items.slice(0, remainingSlots)
  }

  function hiddenSubtitleIssueCount (task) {
    const writeErrorCount = normalizeSubtitleWriteErrors(task?.write_errors).length
    const failedFileCount = (task?.failed_files || []).length
    const visibleCount = visibleSubtitleWriteErrors(task).length + visibleSubtitleFailedFiles(task).length
    return Math.max(0, writeErrorCount + failedFileCount - visibleCount)
  }

  // ─── Computed properties ─────────────────────────────────────────────────
  const subtitleDialogSessionActive = computed(() => subtitleDialogVisible.value || subtitleDialogBackgroundActive.value)
  const showSubtitleBackgroundCard = computed(() => subtitleDialogBackgroundActive.value && !subtitleDialogVisible.value)

  const visibleSubtitleTasks = computed(() => subtitleTasks.value.filter(task => matchesSubtitleTaskFilter(task) && matchesSubtitleTaskManualFilter(task)))

  const subtitleTaskSummary = computed(() => ({
    total: visibleSubtitleTasks.value.length,
    pending: visibleSubtitleTasks.value.filter(task => task.status === 'pending').length,
    processing: visibleSubtitleTasks.value.filter(task => task.status === 'processing').length,
    completed: visibleSubtitleTasks.value.filter(task => task.status === 'completed').length,
    failed: visibleSubtitleTasks.value.filter(task => task.status === 'failed').length
  }))

  const subtitleTaskOverview = computed(() => ([
    { key: 'all', label: '任务', value: subtitleTasks.value.length },
    { key: 'processing', label: '执行中', value: subtitleTasks.value.filter(task => task.status === 'processing').length },
    { key: 'pending', label: '等待中', value: subtitleTasks.value.filter(task => task.status === 'pending').length },
    { key: 'completed', label: '已完成', value: subtitleTasks.value.filter(task => task.status === 'completed' && !task.manual_match_completed).length },
    { key: 'matched', label: '已匹配完成', value: subtitleTasks.value.filter(task => task.manual_match_completed).length },
    { key: 'failed', label: '失败', value: subtitleTasks.value.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length }
  ]).filter(item => item.key === 'all' || item.value > 0))

  const subtitleTaskManualOverview = computed(() => ([
    { key: 'all', label: '全部', value: subtitleTasks.value.length },
    { key: 'awaiting_manual_match', label: '待处理', value: subtitleTasks.value.filter(task => isSubtitleTaskAwaitingManualWork(task)).length },
    { key: 'processing', label: '执行中', value: subtitleTasks.value.filter(task => task.status === 'processing').length },
    { key: 'pending', label: '等待中', value: subtitleTasks.value.filter(task => task.status === 'pending').length },
    { key: 'manual_match_completed', label: '已匹配完成', value: subtitleTasks.value.filter(task => task.manual_match_completed).length },
    { key: 'failed', label: '失败', value: subtitleTasks.value.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length }
  ]))

  const orderedSubtitleTasks = computed(() => sortSubtitleTasksForWorkbench(visibleSubtitleTasks.value))
  const subtitleQueueTasks = computed(() => orderedSubtitleTasks.value)

  const inspectableSubtitleTasks = computed(() => {
    const tasks = orderedSubtitleTasks.value.filter(task => task.subtitle_dir)
    const preferredTask = findTaskMatchingPreferredSelection(tasks)
    if (!preferredTask) return tasks
    return [preferredTask, ...tasks.filter(task => task.id !== preferredTask.id)]
  })

  const activeSubtitleTask = computed(() => {
    if (!orderedSubtitleTasks.value.length) return null
    if (subtitleActiveTaskId.value) {
      const manualTask = orderedSubtitleTasks.value.find(task => task.id === subtitleActiveTaskId.value)
      if (manualTask) return manualTask
    }
    return resolveAutoActiveSubtitleTask(orderedSubtitleTasks.value)
  })

  const compactSubtitleTasks = computed(() => orderedSubtitleTasks.value.filter(task => task.id !== activeSubtitleTask.value?.id))

  const subtitleClearableTaskCounts = computed(() => {
    const clearable = subtitleQueueTasks.value.filter(task => canClearCurrentSubtitleTask(task))
    return {
      completed: clearable.filter(task => task.status === 'completed' && !isRJSubtitleTaskCancelled(task)).length,
      failed: clearable.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length,
      finished: clearable.length
    }
  })

  const activeSubtitleInspectTask = computed(() => subtitleTasks.value.find(task => task.id === subtitleInspectorInfo.value.taskId) || null)

  const subtitleBackgroundActiveTask = computed(() => (
    activeSubtitleTask.value
    || sortSubtitleTasksForWorkbench(subtitleTasks.value).find(task => ['processing', 'pending'].includes(task?.status))
    || sortSubtitleTasksForWorkbench(subtitleTasks.value)[0]
    || null
  ))

  const activeSubtitleTaskProgressLogs = computed(() => {
    const entries = activeSubtitleTask.value?.progress_log || []
    return [...entries.slice(-12)].reverse()
  })

  // ─── State management functions ──────────────────────────────────────────
  function resolveAutoActiveSubtitleTask (tasks = visibleSubtitleTasks.value) {
    const orderedTasks = sortSubtitleTasksForWorkbench(tasks)
    const preferredTask = findTaskMatchingPreferredSelection(orderedTasks)
    if (preferredTask) return preferredTask
    const processing = orderedTasks.find(task => task.status === 'processing')
    if (processing) return processing
    const pending = orderedTasks.find(task => task.status === 'pending')
    if (pending) return pending
    const manualMatched = orderedTasks.find(task => Boolean(task?.manual_match_completed))
    if (manualMatched) return manualMatched
    const completed = orderedTasks.find(task => task.status === 'completed')
    if (completed) return completed
    const failed = orderedTasks.find(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task))
    if (failed) return failed
    return orderedTasks[0] || null
  }

  function resolveCurrentSubtitleTaskId (tasks = visibleSubtitleTasks.value) {
    const orderedTasks = sortSubtitleTasksForWorkbench(tasks)
    if (subtitleActiveTaskId.value && orderedTasks.some(task => task.id === subtitleActiveTaskId.value)) {
      return subtitleActiveTaskId.value
    }
    return resolveAutoActiveSubtitleTask(orderedTasks)?.id || ''
  }

  function setSubtitleTaskFilter (filter) {
    const normalized = normalizeSubtitleTaskFilterSelection(filter || 'all', subtitleTaskManualFilter.value)
    subtitleTaskFilter.value = normalized.taskFilter
    subtitleTaskManualFilter.value = normalized.manualFilter
    syncSubtitleTaskListState()
  }

  function setSubtitleTaskManualFilter (filter) {
    const normalized = normalizeSubtitleTaskFilterSelection(subtitleTaskFilter.value, filter || 'all')
    subtitleTaskFilter.value = normalized.taskFilter
    subtitleTaskManualFilter.value = normalized.manualFilter
    syncSubtitleTaskListState()
  }

  function syncSubtitleTaskListState () {
    const visibleTasks = visibleSubtitleTasks.value
    if (!visibleTasks.length) {
      subtitleActiveTaskId.value = ''
      return
    }
    if (subtitleActiveTaskId.value && visibleTasks.some(task => task.id === subtitleActiveTaskId.value)) return
    const preferredTask = findTaskMatchingPreferredSelection(visibleTasks)
    if (preferredTask && ['pending', 'processing'].includes(preferredTask.status)) {
      subtitleActiveTaskId.value = preferredTask.id
      return
    }
    subtitleActiveTaskId.value = ''
  }

  function focusSubtitleTask (taskId) {
    if (!taskId) return
    if (!visibleSubtitleTasks.value.some(task => task.id === taskId)) return
    subtitleActiveTaskId.value = taskId
  }

  function getSubtitleTasksByClearScope (scope) {
    const clearable = subtitleQueueTasks.value.filter(task => canClearCurrentSubtitleTask(task))
    if (scope === 'completed') {
      return clearable.filter(task => task.status === 'completed' && !isRJSubtitleTaskCancelled(task))
    }
    if (scope === 'failed') {
      return clearable.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task))
    }
    return clearable
  }

  function markSubtitleTaskManualMatchCompleted (taskId, payload = {}) {
    if (!taskId) return
    subtitleTasks.value = subtitleTasks.value.map(task => {
      if (task.id !== taskId) return task
      return {
        ...task,
        status: 'completed',
        progress: 100,
        awaiting_manual_match: false,
        manual_match_completed: true,
        manual_match_applied_pairs: payload.appliedPairs ?? task.manual_match_applied_pairs ?? 0,
        manual_match_deleted_subtitles: payload.deletedSubtitles ?? task.manual_match_deleted_subtitles ?? 0,
        naming_strategy: payload.namingStrategy || task.naming_strategy || 'audio',
        current_step: payload.currentStep || task.current_step
      }
    })
  }

  function markSubtitleSelectionManualMatchCompleted (item, payload = {}) {
    if (!item?.folder_path) return
    const summary = `${buildSubtitleManualMatchSummary(payload)}。可继续重新筛选后再次应用。`
    upsertSubtitleSelectionEntry(item, {
      queue_state: 'manual_match_completed',
      queue_message: summary,
      manual_match_completed: true,
      manual_match_applied_pairs: Math.max(0, Number(payload.appliedPairs || 0)),
      manual_match_deleted_subtitles: Math.max(0, Number(payload.deletedSubtitles || 0)),
      status: 'existing'
    })
  }

  function upsertSubtitleSelectionEntry (item = {}, patch = {}) {
    if (!item?.folder_path) return null
    const key = buildSubtitleSelectionKey(item)
    const nextItem = {
      library_id: item.library_id || selectedLibraryId.value,
      folder_path: item.folder_path,
      folder_name: item.folder_name || getFileName(item.folder_path),
      rjcode: item.rjcode || '',
      audio_count: item.audio_count ?? null,
      existing_subtitle_count: item.existing_subtitle_count ?? 0,
      status: item.status || 'ready',
      queue_state: '',
      queue_message: '',
      task_id: '',
      manual_match_completed: false,
      manual_match_applied_pairs: 0,
      manual_match_deleted_subtitles: 0,
      ...item,
      ...patch
    }
    const next = [...subtitleDialogSelection.value]
    const index = next.findIndex(entry => buildSubtitleSelectionKey(entry) === key)
    if (index >= 0) next[index] = { ...next[index], ...nextItem }
    else next.unshift(nextItem)
    subtitleDialogSelection.value = uniqueSubtitleItems(next)
    if (!subtitlePreferredSelectionKey.value) subtitlePreferredSelectionKey.value = key
    return nextItem
  }

  function syncSubtitleSelectionState () {
    if (!subtitleDialogSelection.value.length) return
    const tasksBySelectionKey = new Map(sortSubtitleTasksByCreatedAt(subtitleTasks.value).map(task => [buildSubtitleTaskSelectionKey(task), task]))
    subtitleDialogSelection.value = subtitleDialogSelection.value
      .map(item => {
        const task = tasksBySelectionKey.get(buildSubtitleSelectionKey(item))
        if (!task) return item
        const nextAudioCount = item.audio_count ?? estimateSubtitleTaskAudioCount(task)
        const nextExistingCount = Math.max(
          Number(item.existing_subtitle_count || 0),
          Number(estimateSubtitleTaskExistingCount(task) || 0),
          subtitleInspectorInfo.value.folderPath === item.folder_path ? Number(subtitleInspectorInfo.value.totalFiles || 0) : 0
        )
        return {
          ...item,
          task_id: task.id,
          queue_state: item.queue_state === 'create_failed'
            ? item.queue_state
            : (task.manual_match_completed ? 'manual_match_completed' : 'queued'),
          queue_message: item.queue_state === 'create_failed'
            ? item.queue_message
            : (task.current_step || getRJSubtitleTaskStatusLabel(task)),
          rjcode: task.rjcode || item.rjcode,
          audio_count: nextAudioCount,
          existing_subtitle_count: nextExistingCount,
          manual_match_completed: Boolean(task.manual_match_completed),
          manual_match_applied_pairs: Number(task.manual_match_applied_pairs || 0),
          manual_match_deleted_subtitles: Number(task.manual_match_deleted_subtitles || 0),
          status: nextExistingCount > 0 ? 'existing' : (item.status || '')
        }
      })
  }

  function upsertSubtitleTaskLocal (task) {
    if (!task?.id) return
    const next = [...subtitleTasks.value]
    const index = next.findIndex(item => item.id === task.id)
    if (index >= 0) next[index] = { ...next[index], ...task }
    else next.unshift(task)
    subtitleTasks.value = sortSubtitleTasksForWorkbench(next)
  }

  function normalizeRJSubtitleTaskPayload (task, options = {}) {
    const { preserveDetail = false } = options
    const trimTail = (items, limit) => Array.isArray(items) ? items.slice(-limit) : []
    return {
      ...task,
      is_optimistic: false,
      search_attempts: Array.isArray(task?.search_attempts) ? task.search_attempts : [],
      download_files: preserveDetail ? trimTail(task?.download_files, 24) : trimTail(task?.download_files, 8),
      progress_log: preserveDetail ? trimTail(task?.progress_log, 24) : trimTail(task?.progress_log, 8)
    }
  }

  function mergeSubtitleTasksWithOptimistic (remoteTasks = []) {
    const remoteIds = new Set(remoteTasks.map(task => task.id).filter(Boolean))
    const now = Date.now()
    const optimisticTasks = subtitleTasks.value.filter(task => (
      task?.id &&
      !remoteIds.has(task.id) &&
      task?.is_optimistic &&
      ['pending', 'processing'].includes(task?.status) &&
      now - Number(task.optimistic_created_at || now) < 120000
    ))
    return sortSubtitleTasksForWorkbench([...remoteTasks, ...optimisticTasks])
  }

  function createOptimisticSubtitleTask (item, taskId) {
    return {
      id: taskId,
      is_optimistic: true,
      optimistic_created_at: Date.now(),
      rjcode: item.rjcode || '',
      actual_rjcode: '',
      folder_name: item.folder_name || getFileName(item.folder_path),
      folder_path: item.folder_path,
      library_id: item.library_id || selectedLibraryId.value,
      status: 'pending',
      is_cancelled: false,
      progress: 0,
      current_step: '等待字幕生成',
      error_message: '',
      created_at: new Date().toISOString(),
      started_at: null,
      completed_at: null,
      source_lang: '',
      source_work_type: '',
      source_title: '',
      downloaded_count: 0,
      existing_subtitle_count: item.existing_subtitle_count || 0,
      subtitle_dir: '',
      written_files: [],
      skipped_files: [],
      write_errors: [],
      failed_files: [],
      match_result: {},
      search_attempts: [],
      download_files: [],
      content_deduped_count: 0,
      content_deduped_files: [],
      progress_log: [],
      awaiting_manual_match: false,
      manual_match_completed: false,
      manual_match_applied_pairs: 0,
      manual_match_deleted_subtitles: 0,
      naming_strategy: subtitleOptions.value.namingStrategy
    }
  }

  // ─── Poll management ─────────────────────────────────────────────────────
  function clearSubtitleStatusPoll () {
    if (subtitleStatusPollTimer) {
      clearTimeout(subtitleStatusPollTimer)
      subtitleStatusPollTimer = null
    }
  }

  function scheduleSubtitleStatusPoll (items) {
    clearSubtitleStatusPoll()
    if (!subtitleDialogSessionActive.value) return
    if ((items || []).some(item => ['pending', 'processing'].includes(item?.status))) {
      subtitleStatusPollTimer = setTimeout(() => refreshRJSubtitleStatus(false, { silent: true }), 3000)
    }
  }

  // ─── Async API functions ─────────────────────────────────────────────────
  async function refreshRJSubtitleStatus (showMessage = false, options = {}) {
    const { silent = false } = options
    clearSubtitleStatusPoll()
    if (!silent) subtitleTasksLoading.value = true
    try {
      const data = await rjSubtitleApi.status()
      const detailTaskIds = new Set([
        subtitleActiveTaskId.value,
        subtitleInspectorInfo.value.taskId
      ].filter(Boolean))
      const remoteTasks = (data.tasks || [])
        .filter(task => !isLinkedSubtitleImportSourceMode(task?.source_mode))
        .map(task => normalizeRJSubtitleTaskPayload(task, {
          preserveDetail: detailTaskIds.has(task.id)
        }))
      subtitleTasks.value = mergeSubtitleTasksWithOptimistic(remoteTasks)
      if (!subtitleTasks.value.length) {
        clearSubtitleInspectorState()
      }
      syncSubtitleInspectorTaskState()
      syncSubtitleSelectionState()
      if (subtitleInspectorInfo.value.taskId && !subtitleTasks.value.some(task => task.id === subtitleInspectorInfo.value.taskId && task.subtitle_dir)) {
        clearSubtitleInspectorState()
      }
      await ensureSubtitleInspectorFocus()
      scheduleSubtitleStatusPoll(subtitleTasks.value)
      if (showMessage) ElMessage.success('字幕任务状态已刷新')
    } catch (error) {
      if (!silent) {
        ElMessage.error('获取字幕任务状态失败: ' + (error.response?.data?.detail || error.message))
      }
    } finally {
      if (!silent) subtitleTasksLoading.value = false
    }
  }

  async function clearCurrentSubtitleTask (task) {
    if (!canClearCurrentSubtitleTask(task)) return
    try {
      await rjSubtitleApi.clearTask(task.id)
      if (subtitleInspectorInfo.value.taskId === task.id) clearSubtitleInspectorState()
      if (subtitleActiveTaskId.value === task.id) subtitleActiveTaskId.value = ''
      await refreshRJSubtitleStatus(false, { silent: true })
      ElMessage.success('任务已清理')
    } catch (error) {
      ElMessage.error('清理字幕任务失败: ' + (error.response?.data?.detail || error.message))
    }
  }

  async function clearSubtitleTasksByScope (scope) {
    const targets = getSubtitleTasksByClearScope(scope)
    if (!targets.length) {
      ElMessage.warning(scope === 'completed' ? '没有可清理的成功任务' : scope === 'failed' ? '没有可清理的失败任务' : '没有可清理的已结束任务')
      return
    }
    const label = scope === 'completed' ? '成功任务' : scope === 'failed' ? '失败任务' : '已结束任务'
    try {
      await showSystemConfirm({
        title: '批量清空任务确认',
        message: `确定清空 ${targets.length} 个${label}吗？运行中的任务不会被清掉。`,
        tone: 'warning',
        confirmText: '确定清空',
        cancelText: '取消'
      })
    } catch (_) {
      return
    }
    subtitleBulkClearingScope.value = scope
    try {
      let successCount = 0
      let failedCount = 0
      for (const task of targets) {
        try {
          await rjSubtitleApi.clearTask(task.id)
          successCount += 1
          if (subtitleInspectorInfo.value.taskId === task.id) clearSubtitleInspectorState()
          if (subtitleActiveTaskId.value === task.id) subtitleActiveTaskId.value = ''
        } catch (error) {
          failedCount += 1
          console.error('批量清理字幕任务失败:', task.id, error)
        }
      }
      await refreshRJSubtitleStatus(false, { silent: true })
      if (failedCount) {
        ElMessage.warning(`批量清空完成：成功 ${successCount}，失败 ${failedCount}`)
      } else {
        ElMessage.success(`已清空 ${successCount} 个${label}`)
      }
    } finally {
      subtitleBulkClearingScope.value = ''
    }
  }

  async function cancelRJSubtitleTask (task) {
    if (!canCancelRJSubtitleTask(task)) return
    try {
      await showSystemConfirm({
        title: '取消任务确认',
        message: `确定取消任务 ${task.actual_rjcode || task.rjcode || '未知RJ'} 吗？`,
        tone: 'warning',
        confirmText: '确定取消',
        cancelText: '继续执行'
      })
    } catch (_) {
      return
    }
    subtitleCancelingId.value = task.id
    try {
      const data = await rjSubtitleApi.cancel(task.id)
      ElMessage.success(data.message || '任务已取消')
      await refreshRJSubtitleStatus(false, { silent: true })
    } catch (error) {
      ElMessage.error('取消任务失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      subtitleCancelingId.value = ''
    }
  }

  async function rerunSubtitleTask (task) {
    if (!canRerunSubtitleTask(task)) return
    subtitleTaskRerunId.value = task.id
    subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)
    try {
      const data = await rjSubtitleApi.rerunTask(task.id, {
        overwriteExisting: subtitleOptions.value.overwriteExisting,
        enableMetadataMatch: subtitleOptions.value.enableMetadataMatch,
        namingStrategy: subtitleOptions.value.namingStrategy,
        useFilterRules: subtitleOptions.value.useFilterRules,
        subtitleFilterRules: sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules)
      })
      if (data?.task_id) {
        subtitleActiveTaskId.value = data.task_id
        upsertSubtitleTaskLocal({
          ...task,
          status: 'pending',
          progress: 0,
          current_step: data.message || '等待重新抓取字幕',
          error_message: '',
          subtitle_dir: '',
          awaiting_manual_match: false,
          manual_match_completed: false,
          manual_match_applied_pairs: 0,
          manual_match_deleted_subtitles: 0,
          written_files: [],
          skipped_files: [],
          failed_files: [],
          write_errors: [],
          match_result: {},
          download_files: [],
          downloaded_count: 0,
          force_rerun: true
        })
        await refreshRJSubtitleStatus(false, { silent: true })
        ElMessage.success(data.message || '任务已重新加入抓取队列')
        if (subtitleInspectorInfo.value.taskId === task.id) {
          clearSubtitleInspectorState()
        }
        const selectionItem = buildSubtitleSelectionItemFromTask(task)
        upsertSubtitleSelectionEntry(selectionItem, {
          task_id: task.id,
          queue_state: 'queued',
          queue_message: data.message || '已重置当前任务并重新抓取'
        })
      }
    } finally {
      if (subtitleTaskRerunId.value === task.id) subtitleTaskRerunId.value = ''
    }
  }

  // ─── Internal watches ────────────────────────────────────────────────────
  watch(subtitleTasks, () => {
    const normalized = normalizeSubtitleTaskFilterSelection(subtitleTaskFilter.value, subtitleTaskManualFilter.value)
    if (normalized.taskFilter !== subtitleTaskFilter.value) {
      subtitleTaskFilter.value = normalized.taskFilter
    }
    if (normalized.manualFilter !== subtitleTaskManualFilter.value) {
      subtitleTaskManualFilter.value = normalized.manualFilter
    }
    syncSubtitleTaskListState()
  })

  watch(visibleSubtitleTasks, tasks => {
    if (!subtitleDialogVisible.value) return
    if (tasks.length) return
    clearSubtitleInspectorState()
  }, { deep: true })

  watch(activeSubtitleTask, task => {
    subtitleTaskDetailPanels.value = buildDefaultSubtitleTaskDetailPanels(task)
  }, { immediate: true })

  watch(inspectableSubtitleTasks, tasks => {
    if (!subtitleDialogVisible.value) return
    if (tasks.length) return
    clearSubtitleInspectorState()
  }, { deep: true })

  // ─── Public API ──────────────────────────────────────────────────────────
  return {
    sortSubtitleTasksByCreatedAt,
    sortSubtitleTasksForWorkbench,
    subtitleTasks,
    subtitleActiveTaskId,
    subtitleTaskFilter,
    subtitleTaskManualFilter,
    subtitleCancelingId,
    subtitleTasksLoading,
    subtitleBulkClearingScope,
    subtitleTaskDetailPanels,
    subtitleDownloadExpandedMap,
    subtitleIssueExpandedMap,
    subtitleTaskRerunId,
    subtitleDialogSessionActive,
    showSubtitleBackgroundCard,
    visibleSubtitleTasks,
    subtitleTaskSummary,
    subtitleTaskOverview,
    subtitleTaskManualOverview,
    orderedSubtitleTasks,
    subtitleQueueTasks,
    inspectableSubtitleTasks,
    activeSubtitleTask,
    compactSubtitleTasks,
    subtitleClearableTaskCounts,
    activeSubtitleInspectTask,
    subtitleBackgroundActiveTask,
    activeSubtitleTaskProgressLogs,
    linkedSubtitleImportSourceModes,
    normalizeSubtitleTaskSourceMode,
    isLinkedSubtitleImportSourceMode,
    isRJSubtitleTaskCancelled,
    isSubtitleTaskAwaitingManualWork,
    matchesSubtitleTaskFilter,
    matchesSubtitleTaskManualFilter,
    getSubtitleTaskFilterResultCount,
    normalizeSubtitleTaskFilterSelection,
    estimateSubtitleTaskAudioCount,
    estimateSubtitleTaskExistingCount,
    buildSubtitleSelectionKey,
    buildSubtitleTaskSelectionKey,
    findSubtitleTaskBySelection,
    findTaskMatchingPreferredSelection,
    buildSubtitleSelectionItemFromTask,
    getTaskDisplayRJCode,
    getTaskSourceRJCode,
    getRJSubtitleTaskStatusLabel,
    getRJSubtitleTaskBaseStatusLabel,
    getRJSubtitleTaskStatusType,
    getRJSubtitleTaskBaseStatusType,
    getRJSubtitleTaskStatusClass,
    getRJSubtitleProgressStatus,
    canCancelRJSubtitleTask,
    canClearCurrentSubtitleTask,
    canRerunSubtitleTask,
    getSubtitleTaskInspectLabel,
    getSubtitleTaskManualStateText,
    getSubtitleTaskManualStateChipClass,
    buildDefaultSubtitleTaskDetailPanels,
    buildSubtitleManualMatchSummary,
    isSubtitleTaskSelected,
    getRJSubtitleLangLabel,
    formatRJSubtitleAttempt,
    getProgressLogLevelLabel,
    formatProgressLogTime,
    normalizeSubtitleWriteError,
    normalizeSubtitleWriteErrors,
    isAudioFileName,
    isSubtitleFileName,
    isSubtitleRelativePath,
    compareSubtitleWorkbenchNames,
    normalizeSubtitleDownloadKey,
    getSubtitleDownloadFiles,
    getSubtitleDownloadDisplayName,
    allSubtitleDownloadsCompleted,
    isSubtitleDownloadExpanded,
    toggleSubtitleDownloadExpanded,
    visibleSubtitleDownloadFiles,
    hiddenSubtitleDownloadCount,
    isSubtitleIssueExpanded,
    toggleSubtitleIssueExpanded,
    visibleSubtitleWriteErrors,
    visibleSubtitleFailedFiles,
    hiddenSubtitleIssueCount,
    sanitizeSubtitleFilterRules,
    resolveAutoActiveSubtitleTask,
    resolveCurrentSubtitleTaskId,
    setSubtitleTaskFilter,
    setSubtitleTaskManualFilter,
    syncSubtitleTaskListState,
    focusSubtitleTask,
    getSubtitleTasksByClearScope,
    markSubtitleTaskManualMatchCompleted,
    markSubtitleSelectionManualMatchCompleted,
    upsertSubtitleSelectionEntry,
    syncSubtitleSelectionState,
    upsertSubtitleTaskLocal,
    normalizeRJSubtitleTaskPayload,
    mergeSubtitleTasksWithOptimistic,
    createOptimisticSubtitleTask,
    clearSubtitleStatusPoll,
    scheduleSubtitleStatusPoll,
    refreshRJSubtitleStatus,
    clearCurrentSubtitleTask,
    clearSubtitleTasksByScope,
    cancelRJSubtitleTask,
    rerunSubtitleTask
  }
}
