<template>
  <el-dialog
    :model-value="visible"
    width="980px"
    title="社团补全下载任务"
    class="circle-download-workbench"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="workbench-toolbar">
      <div class="workbench-summary">
        <div class="workbench-stat"><span class="workbench-stat-label">任务</span><strong class="workbench-stat-value">{{ mergedTasks.length }}</strong></div>
        <div class="workbench-stat"><span class="workbench-stat-label">进行中</span><strong class="workbench-stat-value">{{ processingTasks.length }}</strong></div>
        <div class="workbench-stat"><span class="workbench-stat-label">等待中</span><strong class="workbench-stat-value">{{ pendingTasks.length }}</strong></div>
        <div class="workbench-stat"><span class="workbench-stat-label">部分失败</span><strong class="workbench-stat-value">{{ partialFailedTasks.length }}</strong></div>
        <div class="workbench-stat"><span class="workbench-stat-label">已完成</span><strong class="workbench-stat-value">{{ completedTasks.length }}</strong></div>
      </div>
      <div class="workbench-actions">
        <button class="workbench-action-btn" :disabled="refreshing" @click.stop="emit('refresh')">刷新</button>
        <button class="workbench-action-btn" @click.stop="emit('background')">隐藏到后台</button>
        <button class="workbench-action-btn" @click.stop="emit('close')">关闭</button>
      </div>
    </div>

    <div class="workbench-filter-row">
      <button v-for="item in filterOptions" :key="item.value" class="filter-pill" :class="{ active: activeFilter === item.value }" @click="activeFilter = item.value">
        {{ item.label }}
      </button>
    </div>

    <div v-if="filteredTasks.length" class="download-task-list">
      <article
        v-for="task in filteredTasks"
        :key="task.id"
        class="download-task-card"
        :class="{
          expanded: expandedTaskIds.has(task.id),
          'is-success': getTaskTone(task) === 'success',
          'is-warning': getTaskTone(task) === 'warning',
          'is-danger': getTaskTone(task) === 'danger',
        }"
        @click="toggleExpanded(task.id)"
      >
        <div class="download-task-topline">
          <div class="download-task-badges">
            <span class="task-rjcode">{{ task.rjcode || '未知 RJ' }}</span>
            <span v-if="isTaskDownloaded(task)" class="task-pill success">已下载</span>
            <span v-if="getFailureCount(task)" class="task-pill danger">失败 {{ getFailureCount(task) }}</span>
          </div>
          <span class="task-pill" :class="getTaskTone(task)">{{ getDownloadTaskStatusLabel(task) }}</span>
        </div>
        <div class="download-task-title">{{ task.work_title || task.source_label || '未命名任务' }}</div>
        <div class="task-progress-row">
          <el-progress :percentage="getTaskOverallPercent(task)" :status="getProgressStatus(task)" :stroke-width="8" :show-text="false" class="task-progress" />
          <span class="task-progress-value">{{ getTaskOverallPercent(task) }}%</span>
        </div>
        <div class="download-task-meta-strip">
          <span class="meta-pill">{{ getTaskStageLabel(task) }}</span>
          <span class="meta-pill">{{ getPrimarySizeText(task) }}</span>
          <span class="meta-pill">总大小 {{ formatSize(getTaskTransferBytes(task)) }}</span>
          <span class="meta-pill">下载速度 {{ formatSpeed(getVisibleDownloadSpeed(task)) }}</span>
          <span class="meta-pill">上传速度 {{ formatSpeed(getVisibleUploadSpeed(task)) }}</span>
          <span class="meta-pill">{{ getPrimaryFileProgressLabel(task) }}</span>
        </div>
        <div v-if="task.current_step" class="download-task-step">{{ task.current_step }}</div>
        <div class="download-task-footer">
          <div class="download-task-footer-spacer"></div>
          <button v-if="canRetryDownloadTask(task)" class="task-retry-btn" :disabled="retryingSet.has(task.id)" @click.stop="emit('retry-task', task)">
            {{ retryingSet.has(task.id) ? '重试中' : '重试失败项' }}
          </button>
        </div>
        <div v-if="expandedTaskIds.has(task.id)" class="download-task-detail" @click.stop>
          <div class="download-detail-grid">
            <div class="download-detail-item"><span class="download-detail-label">下载目录</span><span class="download-detail-value">{{ getDownloadRoot(task) }}</span></div>
            <div class="download-detail-item"><span class="download-detail-label">最终路径</span><span class="download-detail-value">{{ getFinalOutputPath(task) }}</span></div>
          </div>
          <div v-if="getUnifiedFileRows(task).length" class="download-file-panel">
            <div class="download-file-title">文件流水线</div>
            <div v-for="file in getUnifiedFileRows(task)" :key="`${task.id}-${file.relative_path || file.name}`" class="download-file-item" :class="`is-${file.tone}`">
              <div class="download-file-head">
                <div class="download-file-main">
                  <div class="download-file-name">{{ file.name }}</div>
                  <div class="download-file-subline">
                    <span>{{ file.stageLabel }}</span>
                    <span>{{ file.sizeText }}</span>
                    <span v-if="file.downloadSpeedVisible">下载 {{ formatSpeed(file.downloadSpeed) }}</span>
                    <span v-if="file.uploadSpeedVisible">上传 {{ formatSpeed(file.uploadSpeed) }}</span>
                  </div>
                </div>
                <span class="task-pill small" :class="file.tone">{{ file.statusText }}</span>
              </div>
              <div class="task-progress-row file-progress-row">
                <el-progress :percentage="file.progress" :stroke-width="6" :show-text="false" :status="file.progressStatus" :color="file.color" class="task-progress" />
                <span class="task-progress-value">{{ file.progress }}%</span>
              </div>
              <div v-if="file.reason" class="download-file-error">{{ file.reason }}</div>
              <div v-if="file.retryable" class="download-file-footer">
                <div class="download-file-footer-spacer"></div>
                <button class="file-retry-btn" :disabled="retryingSet.has(`${task.id}:${file.relative_path || file.name}`)" @click.stop="emit('retry-file', { task, file })">
                  {{ retryingSet.has(`${task.id}:${file.relative_path || file.name}`) ? '重试中' : '重试' }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="task.progress_log?.length" class="download-log-list">
            <div class="download-file-title">最近日志</div>
            <div v-for="entry in task.progress_log.slice(-6)" :key="`${task.id}-${entry.time}-${entry.message}`" class="download-log-item" :class="entry.level || 'info'">
              <span class="download-log-time">{{ formatLogTime(entry.time) }}</span>
              <span class="download-log-message">{{ entry.message }}</span>
            </div>
          </div>
        </div>
      </article>
    </div>
    <el-empty v-else description="暂无符合筛选的下载任务" :image-size="72" />
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tasks: { type: Array, default: () => [] },
  refreshing: { type: Boolean, default: false },
  retryingKeys: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:visible',
  'refresh',
  'background',
  'close',
  'retry-task',
  'retry-waiting',
  'retry-file',
  'reimport-task',
])

const activeFilter = ref('all')
const expandedTaskIds = ref(new Set())

const filterOptions = [
  { value: 'all', label: '全部' },
  { value: 'processing', label: '进行中' },
  { value: 'pending', label: '等待中' },
  { value: 'partial_failed', label: '部分失败' },
  { value: 'completed', label: '已完成' },
]

const retryingSet = computed(() => new Set((props.retryingKeys || []).map(item => String(item || ''))))
const mergedTasks = computed(() => buildMergedTasks(props.tasks || []))
const processingTasks = computed(() => mergedTasks.value.filter(task => String(task?.status || '') === 'processing'))
const pendingTasks = computed(() => mergedTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))))
const partialFailedTasks = computed(() => mergedTasks.value.filter(task => getTaskTone(task) === 'warning'))
const completedTasks = computed(() => mergedTasks.value.filter(task => getTaskTone(task) === 'success'))

const filteredTasks = computed(() => {
  const list = mergedTasks.value || []
  if (activeFilter.value === 'all') return list
  if (activeFilter.value === 'processing') return list.filter(task => String(task?.status || '') === 'processing')
  if (activeFilter.value === 'pending') return list.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.status || '')))
  if (activeFilter.value === 'partial_failed') return list.filter(task => getTaskTone(task) === 'warning')
  if (activeFilter.value === 'completed') return list.filter(task => getTaskTone(task) === 'success')
  return list
})

watch(() => mergedTasks.value.map(task => task.id).join(':'), () => {
  const taskIds = mergedTasks.value.map(task => task.id)
  const activeIds = new Set(taskIds)
  const nextExpanded = new Set([...expandedTaskIds.value].filter(id => activeIds.has(id)))
  if (taskIds.length === 1) nextExpanded.add(taskIds[0])
  expandedTaskIds.value = nextExpanded
}, { immediate: true })

function toggleExpanded(taskId) {
  const next = new Set(expandedTaskIds.value)
  if (next.has(taskId)) next.delete(taskId)
  else next.add(taskId)
  expandedTaskIds.value = next
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function formatSpeed(bytesPerSec) {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatSize(value)}/s` : '—'
}

function formatLogTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString()
}

function getTaskSessionId(task) {
  return String(task?.task_metadata?.session_id || task?.session_id || task?.id || '').trim()
}

function getTaskRjcode(task) {
  return String(task?.rjcode || task?.task_metadata?.rjcode || '').trim().toUpperCase()
}

function getTaskSourceAction(task) {
  return String(task?.task_metadata?.source_action || task?.source_action || '').trim()
}

function getTaskLocalDownloadRoot(task) {
  return String(
    task?.task_metadata?.local_download_root
    || task?.session_state?.local_download_root
    || task?.task_metadata?.download_root
    || ''
  ).trim()
}

function getTaskMergeKey(task) {
  const sessionId = getTaskSessionId(task)
  const rjcode = getTaskRjcode(task)
  if (sessionId) return `session:${sessionId}::${rjcode || 'unknown'}`

  const sourceAction = getTaskSourceAction(task)
  const localDownloadRoot = getTaskLocalDownloadRoot(task)
  if ((sourceAction === 'reimport_local_download_root' || sourceAction === 'reimport_downloaded_session') && rjcode && localDownloadRoot) {
    return `reimport:${rjcode}::${localDownloadRoot.toLowerCase()}`
  }
  if (rjcode && localDownloadRoot) {
    return `download-root:${rjcode}::${localDownloadRoot.toLowerCase()}`
  }
  if (rjcode) return `rj:${rjcode}`
  return `task:${String(task?.id || '').trim()}`
}

function getTaskSortScore(task) {
  const status = String(task?.status || '')
  if (status === 'processing') return 500
  if (status === 'pending') return 400
  if (status === 'waiting_retry') return 350
  if (status === 'paused') return 300
  if (status === 'failed') return 200
  if (status === 'completed') return 100
  return 0
}

function getTaskTimestamp(task) {
  const value = task?.updated_at || task?.start_time || task?.created_at || task?.end_time || ''
  const time = value ? new Date(value).getTime() : 0
  return Number.isFinite(time) ? time : 0
}

function buildMergedTasks(tasks) {
  const groups = new Map()
  ;(tasks || []).forEach((task) => {
    const key = getTaskMergeKey(task)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(task)
  })
  return [...groups.values()].map(mergeTaskGroup)
}

function mergeTaskGroup(group) {
  const sorted = [...group].sort((a, b) => getTaskSortScore(b) - getTaskSortScore(a) || getTaskTimestamp(b) - getTaskTimestamp(a))
  const primary = sorted[0] || {}
  const base = [...sorted].sort((a, b) => getTaskResourceCount(b) - getTaskResourceCount(a) || getTaskTimestamp(b) - getTaskTimestamp(a))[0] || primary
  const mergedSelectedResources = dedupeByRelativePath(sorted.flatMap(task => Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []))
  const mergedDownloadFiles = dedupeByRelativePath(sorted.flatMap(task => Array.isArray(task?.download_files) ? task.download_files.map(file => ({ ...file, __task_status: String(task?.status || '') })) : []))
  const mergedUploadFiles = dedupeByRelativePath(sorted.flatMap(task => Array.isArray(task?.upload_files) ? task.upload_files.map(file => ({ ...file, __task_status: String(task?.status || '') })) : []))
  const mergedUploadedFiles = dedupeByRelativePath(sorted.flatMap(task => Array.isArray(task?.uploaded_files) ? task.uploaded_files.map(file => ({ ...file, __task_status: String(task?.status || '') })) : []))
  const mergedFailedFiles = dedupeByRelativePath([...sorted].reverse().flatMap(task => Array.isArray(task?.failed_files) ? task.failed_files.map(file => ({ ...file, __task_status: String(task?.status || '') })) : []))
  const mergedLogs = [...sorted].flatMap(task => Array.isArray(task?.progress_log) ? task.progress_log : []).sort((a, b) => new Date(a?.time || 0).getTime() - new Date(b?.time || 0).getTime())

  const mergedTask = {
    ...base,
    ...primary,
    id: getTaskMergeKey(base),
    session_id: getTaskSessionId(base),
    rjcode: getTaskRjcode(primary) || getTaskRjcode(base),
    task_metadata: {
      ...(base?.task_metadata || {}),
      ...(primary?.task_metadata || {}),
      session_id: getTaskSessionId(base),
      selected_resources: mergedSelectedResources,
      selected_resource_count: mergedSelectedResources.length || Number(base?.task_metadata?.selected_resource_count || 0),
    },
    download_files: mergedDownloadFiles,
    upload_files: mergedUploadFiles,
    uploaded_files: mergedUploadedFiles,
    failed_files: mergedFailedFiles,
    progress_log: mergedLogs,
    source_task_ids: sorted.map(item => item.id).filter(Boolean),
    active_task_id: primary?.id || base?.id || '',
  }
  const mergedStatus = deriveMergedStatus(mergedTask, sorted)
  mergedTask.status = mergedStatus
  mergedTask.display_status = deriveMergedDisplayStatus(mergedTask, sorted, mergedStatus)
  return mergedTask
}

function hasActiveDownloadRuntime(task) {
  return Number(getDownloadRuntime(task)?.active_file_count || 0) > 0
}

function hasActiveUploadRuntime(task) {
  return Number(getUploadRuntime(task)?.active_file_count || 0) > 0
}

function hasAnyActiveRuntime(task) {
  return hasActiveDownloadRuntime(task) || hasActiveUploadRuntime(task)
}

function getTaskRowsCompletionState(task) {
  const rows = getUnifiedFileRows(task)
  if (!rows.length) return { rows, allCompleted: false, hasDanger: false, hasSuccess: false }
  const hasDanger = rows.some(item => item.tone === 'danger')
  const hasSuccess = rows.some(item => item.tone === 'success')
  const allCompleted = rows.every(item => item.tone === 'success')
  return { rows, allCompleted, hasDanger, hasSuccess }
}

function deriveMergedStatus(task, sourceTasks) {
  const statuses = (sourceTasks || []).map(item => String(item?.status || ''))
  const { allCompleted, hasDanger, hasSuccess } = getTaskRowsCompletionState(task)
  const hasFinalOutputPath = getFinalOutputPath(task) !== '处理中'
  const percent = getTaskOverallPercent(task)

  if (hasAnyActiveRuntime(task)) return 'processing'
  if (allCompleted && percent >= 100 && hasFinalOutputPath) return 'completed'
  if (hasDanger) return hasSuccess ? 'partial_failed' : 'failed'
  if (statuses.includes('pending')) return 'pending'
  if (statuses.includes('waiting_retry')) return 'waiting_retry'
  if (statuses.includes('paused')) return 'paused'
  if (statuses.includes('completed')) return 'completed'
  if (statuses.includes('failed')) return 'failed'
  if (statuses.includes('processing')) return 'processing'
  return String(sourceTasks?.[0]?.status || 'pending')
}

function deriveMergedDisplayStatus(task, sourceTasks, mergedStatus) {
  const { allCompleted, hasDanger, hasSuccess } = getTaskRowsCompletionState(task)
  if (hasAnyActiveRuntime(task)) return 'processing'
  if (allCompleted && getTaskOverallPercent(task) >= 100 && getFinalOutputPath(task) !== '处理中') return 'completed'
  if (hasDanger) return hasSuccess ? 'partial_failed' : 'failed'
  if (mergedStatus === 'partial_failed') return 'partial_failed'
  return String(mergedStatus || sourceTasks?.[0]?.display_status || sourceTasks?.[0]?.status || 'pending')
}

function dedupeByRelativePath(items) {
  const map = new Map()
  ;(items || []).forEach((item, index) => {
    const key = String(item?.relative_path || item?.name || item?.file_name || `row-${index}`).trim()
    if (!key) return
    if (!map.has(key)) map.set(key, item)
  })
  return [...map.values()]
}

function getDownloadRuntime(task) {
  const runtime = task?.download_runtime || task?.performance_metrics?.download_runtime || task?.task_metadata?.performance_metrics?.download_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function getUploadRuntime(task) {
  const runtime = task?.upload_runtime || task?.performance_metrics?.upload_runtime || task?.task_metadata?.performance_metrics?.upload_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function isTaskProcessing(task) {
  return String(task?.display_status || task?.status || '') === 'processing'
}

function isUploadEnabled(task) {
  return Boolean(task?.task_metadata?.upload_options?.enabled || task?.upload_options?.enabled || ['local', 'synology'].includes(String(task?.task_metadata?.upload_mode || task?.upload_mode || '').trim()))
}

function getVisibleDownloadSpeed(task) {
  const runtime = getDownloadRuntime(task)
  const runtimeSpeed = Number(runtime?.speed_bytes_per_sec || 0)
  if (isTaskProcessing(task) && runtimeSpeed > 0) return runtimeSpeed
  return 0
}

function getVisibleUploadSpeed(task) {
  const runtime = getUploadRuntime(task)
  const runtimeSpeed = Number(runtime?.speed_bytes_per_sec || 0)
  if (isTaskProcessing(task) && runtimeSpeed > 0) return runtimeSpeed
  return 0
}

function getTaskTransferBytes(task) {
  const rowTotal = getUnifiedFileRows(task).reduce((sum, row) => sum + Number(row.total || 0), 0)
  if (rowTotal > 0) return rowTotal
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const selectedBytes = selectedResources.reduce((sum, item) => sum + Number(item?.size_bytes || 0), 0)
  if (selectedBytes > 0) return selectedBytes
  return Number(getDownloadRuntime(task)?.total_bytes || 0)
}

function getTaskDownloadedBytes(task) {
  const rowDownloaded = getUnifiedFileRows(task).reduce((sum, row) => sum + Number(row.downloadedBytes || 0), 0)
  if (rowDownloaded > 0) return rowDownloaded
  return Number(getDownloadRuntime(task)?.transferred_bytes || 0)
}

function getTaskUploadedBytes(task) {
  const rowUploaded = getUnifiedFileRows(task).reduce((sum, row) => sum + Number(row.uploadedBytes || 0), 0)
  if (rowUploaded > 0) return rowUploaded
  return Number(getUploadRuntime(task)?.transferred_bytes || 0)
}

function getTaskResourceCount(task) {
  const explicit = Number(task?.task_metadata?.selected_resource_count || task?.session_state?.selected_resource_count || 0)
  if (explicit > 0) return explicit
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources.length : 0
  if (selectedResources > 0) return selectedResources
  return Math.max(Array.isArray(task?.download_files) ? task.download_files.length : 0, Array.isArray(task?.upload_files) ? task.upload_files.length : 0, Array.isArray(task?.uploaded_files) ? task.uploaded_files.length : 0)
}

function getDownloadCompletedCount(task) {
  return getUnifiedFileRows(task).filter(item => Number(item.total || 0) > 0 && Number(item.downloadedBytes || 0) >= Number(item.total || 0)).length
}

function getUploadCompletedCount(task) {
  return getUnifiedFileRows(task).filter(item => item.tone === 'success').length
}

function getFailureCount(task) {
  return getUnifiedFileRows(task).filter(item => item.tone === 'danger').length
}

function hasTaskFailures(task) {
  return getFailureCount(task) > 0 || Boolean(String(task?.task_metadata?.failure_reason || '').trim() || String(task?.error_message || '').trim())
}

function isTaskDownloaded(task) {
  const persistedReady = Boolean(task?.task_metadata?.local_download_ready || task?.session_state?.local_download_ready)
  const downloadRoot = String(task?.task_metadata?.local_download_root || task?.session_state?.local_download_root || task?.task_metadata?.download_root || '').trim()
  return Boolean((persistedReady || getDownloadCompletedCount(task) > 0) && downloadRoot)
}

function getDownloadTaskStatusLabel(task) {
  const status = String(task?.display_status || task?.status || '')
  const map = { pending: '等待中', processing: '处理中', completed: '已完成', partial_failed: '部分失败', failed: '失败', paused: '已暂停', waiting_retry: '等待重试' }
  return map[status] || (status || '未知')
}

function getTaskTone(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'failed') return 'danger'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return 'warning'
  if (status === 'completed') return 'success'
  return 'neutral'
}

function getProgressStatus(task) {
  const tone = getTaskTone(task)
  if (tone === 'danger') return 'exception'
  if (tone === 'warning') return 'warning'
  if (tone === 'success') return 'success'
  return ''
}

function getTaskStageLabel(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'waiting_retry') return '等待重试'
  if (status === 'pending') return '等待开始'
  if (status === 'paused') return '已暂停'
  if (status === 'failed') return '失败'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return '部分失败'
  if (status === 'completed') return '已完成'
  const uploadRuntime = getUploadRuntime(task)
  const downloadRuntime = getDownloadRuntime(task)
  if (Number(uploadRuntime?.active_file_count || 0) > 0) return '上传 / 入库中'
  if (Number(downloadRuntime?.active_file_count || 0) > 0) return '下载中'
  if (Number(uploadRuntime?.is_waiting_turn || 0) > 0 && String(uploadRuntime?.current_relative_path || '').trim()) return '上传准备中'
  if (isUploadEnabled(task) && getUploadCompletedCount(task) > 0 && getDownloadCompletedCount(task) > getUploadCompletedCount(task)) return '上传准备中'
  return '处理中'
}

function getTaskOverallPercent(task) {
  const transferTotal = getTaskTransferBytes(task)
  if (!transferTotal) return Math.min(100, Number(task?.progress || 0))
  const rows = getUnifiedFileRows(task)
  if (rows.length) {
    const progress = rows.reduce((sum, item) => sum + Number(item.progress || 0), 0) / rows.length
    return Math.max(0, Math.min(100, Math.round(progress)))
  }
  return Math.max(0, Math.min(100, Math.round((getTaskDownloadedBytes(task) / transferTotal) * 100)))
}

function getPrimaryFileProgressLabel(task) {
  const stage = getTaskStageLabel(task)
  const total = getTaskResourceCount(task)
  if (!total) return '文件 0 / 0'
  if (stage === '上传 / 入库中' || stage === '上传准备中') return `上传 ${getUploadCompletedCount(task)} / ${total}`
  if (getDownloadCompletedCount(task) > 0 && getDownloadCompletedCount(task) < total) return `下载 ${getDownloadCompletedCount(task)} / ${total}`
  if (getTaskTone(task) === 'warning') return `成功 ${Math.max(0, total - getFailureCount(task))} / ${total}`
  return `文件 ${getDownloadCompletedCount(task)} / ${total}`
}

function getPrimarySizeText(task) {
  const total = formatSize(getTaskTransferBytes(task))
  const tone = getTaskTone(task)
  const stage = getTaskStageLabel(task)
  if (tone === 'success') return `下载大小 ${total}`
  if (stage === '上传 / 入库中' || stage === '上传准备中') return `上传 ${formatSize(getTaskUploadedBytes(task))} / ${total}`
  return `下载 ${formatSize(getTaskDownloadedBytes(task))} / ${total}`
}

function getDownloadRoot(task) {
  return task?.task_metadata?.local_download_root || task?.session_state?.local_download_root || task?.task_metadata?.download_root || task?.task_metadata?.download_base_path || '默认临时目录'
}

function getFinalOutputPath(task) {
  return task?.task_metadata?.final_output_path || task?.output_path || task?.task_metadata?.target_path || '处理中'
}

function canRetryDownloadTask(task) {
  return Boolean(String(task?.task_metadata?.session_id || task?.session_id || '').trim() && getFailureCount(task) > 0)
}

function getUnifiedFileRows(task) {
  const uploadRuntime = getUploadRuntime(task)
  const uploadCurrentRelativePath = String(uploadRuntime?.current_relative_path || '').trim()
  const uploadWaitingTurn = Boolean(uploadRuntime?.is_waiting_turn)
  const uploadEnabled = isUploadEnabled(task)
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const downloadFiles = Array.isArray(task?.download_files) ? task.download_files : []
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const uploadedFiles = Array.isArray(task?.uploaded_files) ? task.uploaded_files : []
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files : []
  const rows = new Map()

  const ensureRow = (key, payload = {}) => {
    const rowKey = String(key || payload.relative_path || payload.name || '').trim()
    if (!rowKey) return null
    const existing = rows.get(rowKey) || {
      key: rowKey, name: payload.name || payload.file_name || payload.relative_path || '未知文件', relative_path: payload.relative_path || '',
      total: Number(payload.size_bytes || 0), downloadedBytes: 0, uploadedBytes: 0, sourceTaskStatus: '', progress: 0, tone: 'neutral',
      color: '#262626', progressStatus: '', reason: '', retryable: false, statusText: '等待中', stageLabel: '等待中',
      sizeText: payload.size_bytes ? `下载大小 ${formatSize(payload.size_bytes)}` : '下载大小 0 B', downloadSpeed: 0, uploadSpeed: 0,
      downloadSpeedVisible: false, uploadSpeedVisible: false, index: Number(payload.index || 0),
    }
    const next = { ...existing, name: payload.name || payload.file_name || existing.name, relative_path: payload.relative_path || existing.relative_path, total: Math.max(Number(payload.total || payload.size_bytes || 0), Number(existing.total || 0)), index: Number(payload.index || existing.index || 0) }
    rows.set(rowKey, next)
    return next
  }

  selectedResources.forEach((item, index) => ensureRow(item.relative_path || item.file_name, { ...item, index: index + 1 }))

  downloadFiles.forEach((file, index) => {
    const row = ensureRow(file.relative_path || file.name, { ...file, index: file.index || index + 1 })
    if (!row) return
    const progress = Math.max(0, Math.min(100, Math.round(Number(file.progress || 0))))
    const fileTaskProcessing = String(file.__task_status || '') === 'processing'
    const rowRelativePath = String(row.relative_path || row.name || '').trim()
    const isCurrentUploadTarget = progress >= 100 && uploadCurrentRelativePath && uploadCurrentRelativePath === rowRelativePath
    row.progress = progress
    row.downloadedBytes = Number(file.downloaded || 0)
    row.uploadedBytes = 0
    row.sourceTaskStatus = String(file.__task_status || '')
    row.downloadSpeed = Number(file.speed_bytes_per_sec || 0)
    row.downloadSpeedVisible = fileTaskProcessing && progress < 100 && row.downloadSpeed > 0
    row.uploadSpeed = 0
    row.uploadSpeedVisible = false
    if (progress >= 100 && uploadEnabled && isCurrentUploadTarget) {
      row.stageLabel = uploadWaitingTurn ? '上传准备中' : '上传中'
      row.statusText = row.stageLabel
      row.tone = 'neutral'
      row.color = '#d4d4d4'
    } else {
      row.stageLabel = progress >= 100 ? '已下载' : (fileTaskProcessing ? '下载中' : '等待重试')
      row.statusText = row.stageLabel
      row.tone = progress >= 100 ? 'neutral' : (fileTaskProcessing ? 'processing' : 'neutral')
      row.color = progress >= 100 ? '#d4d4d4' : (fileTaskProcessing ? '#000000' : '#c7c7cc')
    }
    row.sizeText = `下载 ${formatSize(file.downloaded || 0)} / ${formatSize(row.total)}`
  })

  uploadFiles.forEach((file, index) => {
    const row = ensureRow(file.relative_path || file.name, { ...file, index: file.index || index + 1 })
    if (!row) return
    row.progress = Math.max(0, Math.min(100, Math.round(Number(file.progress || 0))))
    row.downloadedBytes = Number(row.total || file.size_bytes || 0)
    row.uploadedBytes = Number(file.uploaded || 0)
    row.sourceTaskStatus = String(file.__task_status || '')
    row.downloadSpeed = 0
    row.downloadSpeedVisible = false
    row.uploadSpeed = Number(file.speed_bytes_per_sec || 0)
    row.uploadSpeedVisible = isTaskProcessing(task) && Number(file.progress || 0) < 100 && row.uploadSpeed > 0
    row.stageLabel = Number(file.progress || 0) >= 100 ? '已完成' : '上传中'
    row.statusText = row.stageLabel
    row.sizeText = Number(file.progress || 0) >= 100 ? `下载大小 ${formatSize(row.total)}` : `上传 ${formatSize(file.uploaded || 0)} / ${formatSize(row.total)}`
    row.tone = Number(file.progress || 0) >= 100 ? 'success' : 'upload'
    row.color = Number(file.progress || 0) >= 100 ? '#737373' : '#000000'
  })

  uploadedFiles.forEach((file) => {
    const row = ensureRow(file.relative_path || file.name, file)
    if (!row) return
    const sizeBytes = Math.max(Number(file.size_bytes || 0), Number(row.total || 0))
    row.downloadedBytes = sizeBytes
    row.uploadedBytes = sizeBytes
    row.sourceTaskStatus = String(file.__task_status || '')
    row.progress = 100
    row.downloadSpeedVisible = false
    row.uploadSpeedVisible = false
    row.stageLabel = '已完成'
    row.statusText = '已完成'
    row.sizeText = `下载大小 ${formatSize(sizeBytes)}`
    row.tone = 'success'
    row.color = '#737373'
  })

  failedFiles.forEach((file) => {
    const row = ensureRow(file.relative_path || file.name, file)
    if (!row) return
    const keepActiveState = String(row.sourceTaskStatus || '') === 'processing' && ['processing', 'upload', 'success'].includes(String(row.tone || ''))
    if (keepActiveState) return
    row.downloadedBytes = Number(file.stage === 'upload' ? (row.total || 0) : (file.downloaded || row.downloadedBytes || 0))
    row.uploadedBytes = Number(file.stage === 'upload' ? (file.uploaded || 0) : 0)
    row.reason = String(file.reason || file.exception_type || '失败').trim()
    row.retryable = Boolean(row.relative_path)
    row.tone = 'danger'
    row.color = '#ef4444'
    row.progressStatus = 'exception'
    const failedStage = String(file.stage || '').trim()
    row.stageLabel = failedStage === 'upload' ? '上传失败' : '下载失败'
    row.statusText = row.stageLabel
    row.sizeText = failedStage === 'upload' ? `上传 ${formatSize(file.uploaded || 0)} / ${formatSize(row.total)}` : `下载 ${formatSize(file.downloaded || 0)} / ${formatSize(row.total)}`
  })

  return [...rows.values()].sort((a, b) => {
    const rank = { danger: 0, upload: 1, processing: 2, neutral: 3, success: 4 }
    return (rank[a.tone] ?? 9) - (rank[b.tone] ?? 9) || (a.index || 0) - (b.index || 0)
  }).slice(0, 14)
}
</script>

<style scoped>
.circle-download-workbench,
.circle-download-workbench * { box-sizing: border-box; }
.workbench-toolbar,.workbench-summary,.download-task-card,.workbench-actions,.filter-pill,.task-pill,.task-retry-btn,.file-retry-btn { font-family: "SF Pro Rounded","SF Pro Text","PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif; }
.workbench-toolbar { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:12px; }
.workbench-summary { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; flex:1; }
.workbench-stat { border:1px solid #e5e5e5; border-radius:8px; background:#fff; padding:10px 12px; display:grid; gap:2px; }
.workbench-stat-label { font-size:11px; color:#86868b; }
.workbench-stat-value { font-size:16px; font-weight:600; color:#1d1d1f; }
.workbench-actions { display:flex; gap:8px; flex-wrap:wrap; }
.workbench-action-btn,.filter-pill,.task-retry-btn,.file-retry-btn { min-height:30px; border-radius:9999px; border:1px solid #d2d2d7; background:#fff; color:#1d1d1f; padding:0 12px; font-size:12px; font-weight:500; cursor:pointer; transition:background-color .14s ease,border-color .14s ease,color .14s ease; }
.workbench-action-btn { appearance:none; outline:none; box-shadow:none; transition:none; }
.workbench-action-btn:focus,
.workbench-action-btn:focus-visible,
.workbench-action-btn:active { outline:none; box-shadow:none; }
.workbench-action-btn:hover,.filter-pill:hover,.task-retry-btn:hover,.file-retry-btn:hover { background:#fbfbfd; border-color:#b5b5bc; }
.workbench-action-btn:disabled,.task-retry-btn:disabled,.file-retry-btn:disabled { cursor:default; opacity:.55; }
.workbench-filter-row { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; }
.filter-pill.active { background:#0071e3; border-color:#0071e3; color:#fff; }
.download-task-list { display:grid; gap:10px; max-height:70vh; overflow:auto; padding-right:4px; }
.download-task-card { display:grid; gap:10px; border:1px solid #e5e5e7; border-radius:8px; background:#fff; padding:12px; cursor:pointer; }
.download-task-card.expanded { background:#fbfbfd; }
.download-task-card.is-success { border-color:#9ed9ad; box-shadow:0 0 0 1px rgba(52,199,89,.16) inset; background:#fbfffc; }
.download-task-card.is-warning { border-color:#f3d3a1; }
.download-task-card.is-danger { border-color:#f0b2aa; }
.download-task-topline { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
.download-task-badges { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.task-rjcode { font-size:12px; font-weight:600; color:#0071e3; }
.task-pill { display:inline-flex; align-items:center; min-height:22px; padding:0 10px; border-radius:9999px; border:1px solid #d2d2d7; background:#fff; font-size:11px; color:#515154; white-space:nowrap; }
.task-pill.small { min-height:20px; padding:0 8px; font-size:10px; }
.task-pill.success { border-color:#b8e6c3; background:#f1fff4; color:#19703a; }
.task-pill.danger { border-color:#ffd2cc; background:#fff5f3; color:#c93420; }
.task-pill.warning { border-color:#ffe0b2; background:#fff8ed; color:#b45f06; }
.task-pill.neutral { color:#515154; }
.download-task-title { font-size:15px; line-height:1.3; font-weight:600; color:#1d1d1f; word-break:break-word; }
.task-progress-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; }
.task-progress-value { font-size:11px; color:#6e6e73; white-space:nowrap; }
.download-task-meta-strip { display:flex; gap:6px; flex-wrap:wrap; }
.meta-pill { display:inline-flex; align-items:center; min-height:26px; padding:0 10px; border-radius:9999px; background:#fff; border:1px solid #e5e5e7; color:#515154; font-size:11px; }
.download-task-step { font-size:12px; color:#6e6e73; line-height:1.35; }
.download-task-footer { display:flex; justify-content:flex-end; align-items:center; gap:10px; }
.download-task-footer-spacer,.download-file-footer-spacer { flex:1; }
.task-retry-btn,.file-retry-btn { background:#0071e3; border-color:#0071e3; color:#fff; }
.task-retry-btn:hover,.file-retry-btn:hover { background:#0077ed; border-color:#0077ed; }
.download-task-detail { display:grid; gap:10px; padding-top:2px; }
.download-detail-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.download-detail-item,.download-file-panel,.download-log-list { display:grid; gap:6px; border:1px solid #e5e5e7; border-radius:8px; background:#fff; padding:10px 12px; }
.download-detail-label,.download-file-title { font-size:11px; color:#86868b; }
.download-detail-value { font-size:12px; color:#1d1d1f; word-break:break-all; }
.download-file-panel { gap:8px; }
.download-file-item { display:grid; gap:3px; border:1px solid #e5e5e7; border-radius:8px; background:#fff; padding:6px 9px; }
.download-file-item.is-danger { border-color:#ef4444; }
.download-file-head { display:flex; justify-content:space-between; gap:6px; align-items:flex-start; }
.download-file-main { min-width:0; display:grid; gap:1px; }
.download-file-name { font-size:11px; color:#1d1d1f; word-break:break-word; line-height:1.2; }
.download-file-subline { display:flex; gap:4px 6px; flex-wrap:wrap; font-size:10px; color:#6e6e73; line-height:1.15; }
.file-progress-row { align-items:center; gap:6px; margin-top:1px; }
.download-file-error { font-size:10px; color:#c93420; line-height:1.3; }
.download-file-footer { display:flex; justify-content:space-between; align-items:flex-end; min-height:0; margin-top:1px; }
.download-log-item { display:grid; grid-template-columns:68px minmax(0,1fr); gap:8px; font-size:11px; }
.download-log-time { color:#a1a1a6; }
.download-log-message { color:#515154; word-break:break-word; }
:deep(.circle-download-workbench .el-dialog) { border-radius:10px; overflow:hidden; box-shadow:none; }
:deep(.circle-download-workbench .el-dialog__header) { margin-right:0; padding:16px 18px 10px; border-bottom:1px solid #e5e5e7; background:#f5f5f7; }
:deep(.circle-download-workbench .el-dialog__title) { font-size:18px; font-weight:600; color:#1d1d1f; }
:deep(.circle-download-workbench .el-dialog__body) { padding:16px 18px 18px; background:#f5f5f7; }
:deep(.circle-download-workbench .el-progress-bar__outer) { background:#e9e9ee; }
:deep(.circle-download-workbench .el-progress-bar__inner) { background:linear-gradient(90deg,#0071e3 0%,#2f8fff 100%); }

@media (max-width:760px) {
  .workbench-toolbar,.download-task-topline,.download-file-head,.download-task-footer { display:grid; grid-template-columns:1fr; }
  .workbench-summary,.download-detail-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .task-progress-row { grid-template-columns:1fr auto; }
}
</style>
