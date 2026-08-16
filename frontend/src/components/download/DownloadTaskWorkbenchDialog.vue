<template>
  <!--
    社团补全下载工作台新视觉原型。
    当前只作为独立 V1 原型文件存在，不接入、不替换正式组件。
    数据契约与旧组件保持兼容，便于后续在 CircleCompletion 中切换验收。
  -->
  <Teleport to="body">
    <transition name="el-fade-in">
      <div v-if="visible" class="v1-overlay" @click.self="emit('background')">
        <div class="v1-shell" :class="{ 'is-compact': compact }">
          <header class="v1-header">
            <div class="v1-header-copy">
              <div class="v1-title">{{ titleText }}</div>
              <div class="v1-subtitle">{{ subtitleText }}</div>

              <div class="v1-tabs">
                <button
                  v-for="tab in filterTabs"
                  :key="tab.value"
                  type="button"
                  class="v1-tab"
                  :class="{ active: activeFilter === tab.value }"
                  @click="activeFilter = tab.value"
                >
                  <span>{{ tab.label }}</span>
                  <span v-if="tab.count !== null" class="v1-tab-badge">{{ tab.count }}</span>
                </button>
              </div>
            </div>

            <div class="v1-header-tools">
              <label class="v1-search">
                <Search :size="16" />
                <input v-model.trim="searchQuery" type="text" placeholder="搜索任务..." />
              </label>
              <button
                type="button"
                class="v1-icon-button"
                :class="{ spinning: refreshing || localSpinning }"
                title="刷新"
                @click.stop="handleRefresh"
              >
                <RefreshCw :size="18" />
              </button>
              <button type="button" class="v1-icon-button" title="隐藏到后台" @click.stop="emit('background')">
                <Minimize2 :size="18" />
              </button>
              <button type="button" class="v1-icon-button" title="关闭" @click.stop="emit('close')">
                <X :size="18" />
              </button>
            </div>
          </header>

          <main class="v1-body v1-scrollbar">
            <article
              v-for="task in filteredTasks"
              :key="task.id"
              class="v1-task-card"
              :class="[taskCardToneClass(task), { expanded: expandedTaskIds.has(task.id) }]"
              @click="toggleExpanded(task.id)"
            >
              <div class="v1-task-summary">
                <div class="v1-task-icon" :class="iconToneClass(task)">
                  <component
                    :is="getTaskIcon(task)"
                    v-if="!getTaskLottie(task)"
                    class="v1-task-icon-fallback"
                    :size="24"
                  />
                  <DotLottieVue
                    v-if="getTaskLottie(task)"
                    class="v1-task-icon-lottie"
                    :class="{ 'is-upload-anim': isUploadLottie(task) }"
                    :src="getTaskLottie(task)"
                    :autoplay="true"
                    :loop="isTaskProcessing(task)"
                    :keep-last-frame="isTaskSuccess(task)"
                  />
                </div>

                <div class="v1-task-main">
                  <div class="v1-task-head">
                    <div class="v1-task-name-wrap">
                      <h3 class="v1-task-name">{{ getTaskPrimaryTitle(task) }}</h3>
                      <div v-if="getTaskSecondaryLabel(task)" class="v1-task-rj">{{ getTaskSecondaryLabel(task) }}</div>
                    </div>

                    <div class="v1-task-actions" @click.stop>
                      <template v-if="isTaskProcessing(task)">
                        <button type="button" class="v1-inline-action" aria-label="暂停任务" @click="emit('pause-task', task)" title="暂停">
                          <Pause :size="13" />
                          暂停
                        </button>
                        <button type="button" class="v1-inline-action danger" aria-label="取消任务" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="isTaskPaused(task)">
                        <button type="button" class="v1-inline-action primary" aria-label="恢复任务" @click="emit('resume-task', task)" title="恢复">
                          <Play :size="13" />
                          恢复
                        </button>
                        <button type="button" class="v1-inline-action danger" aria-label="取消任务" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="['pending', 'waiting_retry'].includes(String(task?.status || ''))">
                        <button type="button" class="v1-inline-action danger" aria-label="取消任务" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="canRetryDownloadTask(task)">
                        <button
                          type="button"
                          class="v1-inline-action danger retry"
                          :disabled="isTaskRetrying(task)"
                          @click.stop="emit('retry-task', task)"
                        >
                          <RefreshCw :size="13" :class="{ spinning: isTaskRetrying(task) }" />
                          {{ isTaskRetrying(task) ? '重试中' : '重试失败项' }}
                        </button>
                      </template>
                    </div>
                  </div>

                  <div class="v1-task-meta">
                    <span class="v1-status-line" :class="statusToneClass(task)">
                      <component :is="getTaskStatusMetaIcon(task)" :size="12" class="v1-status-icon" />
                      {{ getDownloadTaskStatusLabel(task) }}
                    </span>
                    <span>{{ getPrimarySizeText(task) }}</span>
                    <span>{{ getPrimaryFileProgressLabel(task) }}</span>
                    <span v-if="showDownloadMetrics && getVisibleDownloadSpeed(task) > 0" class="v1-speed-line">
                      <Zap :size="12" />
                      下载 {{ formatSpeed(getVisibleDownloadSpeed(task)) }}
                    </span>
                    <span v-else-if="showDownloadMetrics && isTaskPaused(task)" class="v1-speed-line">
                      <Zap :size="12" />
                      下载 0 B/s
                    </span>
                    <span v-if="getVisibleUploadSpeed(task) > 0" class="v1-speed-line upload">
                      <Zap :size="12" />
                      上传 {{ formatSpeed(getVisibleUploadSpeed(task)) }}
                    </span>
                    <span v-else-if="isTaskPaused(task) && isUploadEnabled(task)" class="v1-speed-line upload">
                      <Zap :size="12" />
                      上传 0 B/s
                    </span>
                    <span v-if="showUploadEta && getVisibleUploadSpeed(task) > 0" class="v1-eta-line">
                      预计剩余 {{ formatEtaSeconds(getUploadEtaSeconds(task)) }}
                    </span>
                    <span v-if="getTaskSummaryStepText(task)">{{ getTaskSummaryStepText(task) }}</span>
                  </div>

                  <div v-if="!expandedTaskIds.has(task.id) && shouldShowSummaryProgress(task)" class="v1-summary-progress">
                    <AppLottieProgressBar :percentage="getTaskOverallPercent(task)" size="sm" :show-text="false" />
                    <span class="v1-summary-progress-text">{{ getTaskOverallPercent(task) }}%</span>
                  </div>

                </div>
              </div>

              <transition
                enter-active-class="transition-all duration-300 ease-out grid"
                enter-from-class="grid-rows-[0fr] opacity-0"
                enter-to-class="grid-rows-[1fr] opacity-100"
                leave-active-class="transition-all duration-200 ease-in grid"
                leave-from-class="grid-rows-[1fr] opacity-100"
                leave-to-class="grid-rows-[0fr] opacity-0"
              >
                <div v-show="expandedTaskIds.has(task.id)" class="grid overflow-hidden" @click.stop>
                  <div class="min-h-0">
                    <div class="v1-task-detail">
                      <div v-if="task.error_message || task?.task_metadata?.failure_reason" class="v1-error-box">
                        <AlertCircle :size="16" />
                        <div class="v1-error-copy">
                          <div class="v1-error-title">失败信息</div>
                          <div class="v1-error-text">{{ task.error_message || task?.task_metadata?.failure_reason }}</div>
                        </div>
                      </div>

                      <div class="v1-path-grid">
                        <div class="v1-path-card">
                          <div class="v1-path-label">{{ sourcePathLabel }}</div>
                          <div class="v1-path-value">{{ getDownloadRoot(task) }}</div>
                        </div>
                        <div class="v1-path-card">
                          <div class="v1-path-label">最终路径</div>
                          <div class="v1-path-value">{{ getFinalOutputDisplay(task) }}</div>
                        </div>
                      </div>

                      <div v-if="getUnifiedFileRows(task).length" class="v1-detail-section">
                        <div class="v1-detail-section-head">
                          <div>
                            <div class="v1-detail-section-label">文件明细</div>
                            <div class="v1-detail-section-subtitle">
                              {{ getPrimaryFileProgressLabel(task) }}
                              <span v-if="getFailureCount(task) > 0"> · 失败 {{ getFailureCount(task) }} 个</span>
                            </div>
                          </div>
                          <div class="v1-detail-section-count">
                            <template v-if="task?.download_files_truncated">预览 {{ getUnifiedFileRows(task).length }} / {{ task.download_files_total }} 项</template>
                            <template v-else>{{ getUnifiedFileRows(task).length }} 项</template>
                          </div>
                        </div>
                        <div
                          class="v1-file-list"
                          :class="{ 'is-virtualized': isVirtualizedFileTask(task) }"
                          :ref="isVirtualizedFileTask(task) ? setVirtualFileListRef : undefined"
                        >
                          <div
                            :class="{ 'v1-file-virtual-canvas': isVirtualizedFileTask(task) }"
                            :style="isVirtualizedFileTask(task) ? { height: `${virtualFileTotalSize}px` } : undefined"
                          >
                            <div
                              v-for="entry in getRenderedFileEntries(task)"
                              :key="`${task.id}-${entry.file.relative_path || entry.file.name}-detail`"
                              class="v1-file-row"
                              :ref="entry.virtualRow ? measureVirtualFileRow : undefined"
                              :data-index="entry.virtualRow?.index"
                              :style="entry.virtualRow ? { transform: `translate3d(0, ${entry.virtualRow.start}px, 0)` } : undefined"
                            >
                            <div class="v1-file-row-top">
                              <div class="v1-file-row-main">
                                <span class="v1-file-row-name">{{ entry.file.name }}</span>
                                <span v-if="['success', 'upload-success'].includes(entry.file.tone)" class="v1-file-chip success">{{ entry.file.statusText }}</span>
                                <span v-else-if="entry.file.tone === 'danger'" class="v1-file-chip danger">{{ entry.file.statusText }}</span>
                              </div>
                              <div class="v1-file-row-side">
                                <span>{{ entry.file.progress }}% • {{ entry.file.sizeText }}</span>
                                <span v-if="showDownloadMetrics && entry.file.downloadSpeedVisible">下载 {{ formatSpeed(entry.file.downloadSpeed) }}</span>
                                <span v-if="entry.file.uploadSpeedVisible">上传 {{ formatSpeed(entry.file.uploadSpeed) }}</span>
                                <button
                                  v-if="entry.file.retryable"
                                  type="button"
                                  class="v1-file-retry"
                                  :disabled="isFileRetrying(task, entry.file)"
                                  @click.stop="emit('retry-file', { task, file: entry.file })"
                                >
                                  <RefreshCw :size="11" :class="{ spinning: isFileRetrying(task, entry.file) }" />
                                  {{ isFileRetrying(task, entry.file) ? '重试中' : '重试' }}
                                </button>
                              </div>
                            </div>
                            <div class="v1-strip-track">
                              <div class="v1-strip-fill" :class="fileToneClass(entry.file)" :style="{ width: `${entry.file.progress}%` }"></div>
                            </div>
                            <div v-if="entry.file.reason" class="v1-file-reason">{{ entry.file.reason }}</div>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div v-if="getVisibleProgressLogs(task).length" class="v1-detail-section">
                        <div class="v1-detail-section-label">最近日志</div>
                        <div class="v1-log-list">
                          <div
                            v-for="entry in getVisibleProgressLogs(task)"
                            :key="`${task.id}-${entry.timeKey}-${entry.message}`"
                            class="v1-log-row"
                          >
                            <span class="v1-log-time">{{ formatLogTime(entry.timeKey) }}</span>
                            <span class="v1-log-message">{{ entry.message }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </transition>
            </article>

            <AppEmptyState v-if="!filteredTasks.length" :description="emptyTitleText" size="lg" />
          </main>

          <footer class="v1-footer">
            <div class="v1-footer-metrics">
              <div v-if="showDownloadMetrics" class="v1-footer-block">
                <span class="v1-footer-label">下载速度</span>
                <span class="v1-footer-value">{{ totalDownloadSpeed }}</span>
              </div>
              <div v-if="showDownloadMetrics" class="v1-footer-divider"></div>
              <div v-if="shouldShowUploadMetrics" class="v1-footer-block">
                <span class="v1-footer-label">上传速度</span>
                <span class="v1-footer-value">{{ totalUploadSpeed }}</span>
              </div>
              <div v-if="shouldShowUploadMetrics" class="v1-footer-divider"></div>
              <div class="v1-footer-block">
                <span class="v1-footer-label">剩余大小</span>
                <span class="v1-footer-value">{{ remainingTransferSize }}</span>
              </div>
              <div class="v1-footer-divider"></div>
              <div class="v1-footer-block">
                <span class="v1-footer-label">预计时间</span>
                <span class="v1-footer-value">{{ aggregatedTransferEta }}</span>
              </div>
              <div class="v1-footer-divider"></div>
              <div class="v1-footer-block">
                <span class="v1-footer-label">剩余任务</span>
                <span class="v1-footer-value">{{ remainingTaskSummary }}</span>
              </div>
            </div>

            <div class="v1-footer-actions">
              <button type="button" class="v1-footer-action primary" @click.stop="handleRefresh">刷新</button>
              <button type="button" class="v1-footer-action" @click.stop="emit('background')">隐藏到后台</button>
              <button type="button" class="v1-footer-action" @click.stop="emit('close')">关闭</button>
            </div>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { Archive, AlertCircle, ArrowUpToLine, CheckCircle2, Clock3, Cloud, CloudDownload, Download, HardDriveUpload, Minimize2, Pause, Play, RefreshCw, Search, TriangleAlert, X, XCircle, Zap } from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import downloadIconAnimation from '../../assets/anime/download-icon-clean.json?url'
import uploadToCloudAnimation from '../../assets/anime/Uploading to cloud.lottie'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'
import AppLottieProgressBar from '../common/AppLottieProgressBar.vue'
import AppEmptyState from '../common/AppEmptyState.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tasks: { type: Array, default: () => [] },
  refreshing: { type: Boolean, default: false },
  retryingKeys: { type: Array, default: () => [] },
  retryingSessionIds: { type: Array, default: () => [] },
  title: { type: String, default: 'Download Manager' },
  subtitle: { type: String, default: '社团补全下载任务' },
  emptyTitle: { type: String, default: '暂无符合筛选的下载任务' },
  sourcePathLabel: { type: String, default: '下载目录' },
  showDownloadMetrics: { type: Boolean, default: true },
  showUploadEta: { type: Boolean, default: false },
  preferUploadIcon: { type: Boolean, default: false },
  transferMode: { type: String, default: 'download' },
  mergeTasks: { type: Boolean, default: true },
  compact: { type: Boolean, default: false },
  enableFileRetry: { type: Boolean, default: false },
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
  'pause-task',
  'resume-task',
  'cancel-task',
  'load-files',
])

const activeFilter = ref('all')
const searchQuery = ref('')
const expandedTaskIds = ref(new Set())
const localSpinning = ref(false)
const virtualFileListRef = ref(null)
const unifiedRowsCache = new WeakMap()
const isUploadMode = computed(() => props.transferMode === 'upload')

function handleRefresh() {
  emit('refresh')
  localSpinning.value = true
  setTimeout(() => { localSpinning.value = false }, 900)
}

const retryingSet = computed(() => new Set((props.retryingKeys || []).map(item => String(item || ''))))
const retryingSessionSet = computed(() => new Set((props.retryingSessionIds || []).map(item => String(item || ''))))
const mergedTasks = computed(() => props.mergeTasks === false ? (props.tasks || []) : buildMergedTasks(props.tasks || []))
const titleText = computed(() => String(props.title || 'Download Manager'))
const subtitleText = computed(() => String(props.subtitle || '社团补全下载任务'))
const emptyTitleText = computed(() => String(props.emptyTitle || '暂无符合筛选的下载任务'))
const processingTasks = computed(() => mergedTasks.value.filter(task => isTaskProcessing(task)))
const pendingTasks = computed(() => mergedTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.display_status || task?.status || ''))))
const partialFailedTasks = computed(() => mergedTasks.value.filter(task => getTaskTone(task) === 'warning'))
const completedTasks = computed(() => mergedTasks.value.filter(task => getTaskTone(task) === 'success'))

const filterTabs = computed(() => ([
  { value: 'all', label: '全部', count: mergedTasks.value.length },
  { value: 'processing', label: '进行中', count: processingTasks.value.length },
  { value: 'pending', label: '等待中', count: pendingTasks.value.length },
  { value: 'partial_failed', label: '部分失败', count: partialFailedTasks.value.length },
  { value: 'completed', label: '已完成', count: completedTasks.value.length },
]))

const filteredTasks = computed(() => {
  let list = mergedTasks.value || []
  if (activeFilter.value === 'processing') list = list.filter(task => isTaskProcessing(task))
  else if (activeFilter.value === 'pending') list = list.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.display_status || task?.status || '')))
  else if (activeFilter.value === 'partial_failed') list = list.filter(task => getTaskTone(task) === 'warning')
  else if (activeFilter.value === 'completed') list = list.filter(task => getTaskTone(task) === 'success')

  const keyword = searchQuery.value.trim().toLowerCase()
  if (!keyword) return list
  return list.filter((task) => {
    const haystack = [task?.rjcode, task?.work_title, task?.source_label, getDownloadRoot(task), getFinalOutputPath(task)]
      .map(item => String(item || '').toLowerCase())
      .join(' ')
    return haystack.includes(keyword)
  })
})

const virtualFileTask = computed(() => {
  let candidate = null
  let candidateLength = 0
  for (const task of mergedTasks.value) {
    if (!expandedTaskIds.value.has(task.id)) continue
    const length = getUnifiedFileRows(task).length
    if (length > candidateLength) {
      candidate = task
      candidateLength = length
    }
  }
  return candidateLength >= 80 ? candidate : null
})
const virtualFileRows = computed(() => {
  const task = virtualFileTask.value
  return task ? getUnifiedFileRows(task) : []
})
const fileRowVirtualizer = useVirtualizer(computed(() => ({
  count: virtualFileRows.value.length,
  getScrollElement: () => virtualFileListRef.value,
  estimateSize: () => 36,
  measureElement: element => element?.getBoundingClientRect().height || 36,
  overscan: 12,
})))
const virtualFileItems = computed(() => fileRowVirtualizer.value.getVirtualItems())
const virtualFileTotalSize = computed(() => fileRowVirtualizer.value.getTotalSize())

function isVirtualizedFileTask(task) {
  return Boolean(task?.id && virtualFileTask.value?.id === task.id)
}

function setVirtualFileListRef(element) {
  virtualFileListRef.value = element || null
}

function measureVirtualFileRow(element) {
  if (element) fileRowVirtualizer.value.measureElement(element)
}

function getRenderedFileEntries(task) {
  const rows = getUnifiedFileRows(task)
  if (!isVirtualizedFileTask(task)) {
    return rows.map((file, index) => ({ file, index, virtualRow: null }))
  }
  return virtualFileItems.value
    .map(virtualRow => ({
      file: rows[virtualRow.index],
      index: virtualRow.index,
      virtualRow,
    }))
    .filter(entry => entry.file)
}

function getFileRetryKey(task, file) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  const fileKey = String(file?.relative_path || file?.name || file?.selection_key || 'file').trim()
  return `${taskId}:${fileKey || 'file'}`
}

function isTaskRetrying(task) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  return retryingSet.value.has(taskId)
    || retryingSessionSet.value.has(getTaskSessionId(task))
    || [...retryingSet.value].some(key => key.startsWith(`${taskId}:`))
}

function isFileRetrying(task, file) {
  return retryingSessionSet.value.has(getTaskSessionId(task))
    || retryingSet.value.has(getFileRetryKey(task, file))
}

const pausedTasks = computed(() => mergedTasks.value.filter(task => isTaskPaused(task)))
const shouldShowUploadMetrics = computed(() => {
  if (isUploadMode.value || props.showUploadEta) return true
  return mergedTasks.value.some((task) => {
    return (
      isUploadEnabled(task) ||
      hasActiveUploadRuntime(task) ||
      (Array.isArray(task?.upload_files) && task.upload_files.length > 0) ||
      (Array.isArray(task?.uploaded_files) && task.uploaded_files.length > 0)
    )
  })
})
const totalDownloadSpeed = computed(() => {
  const speed = processingTasks.value.reduce((sum, task) => sum + getVisibleDownloadSpeed(task), 0)
  if (speed > 0) return formatSpeed(speed)
  if (!processingTasks.value.length && pausedTasks.value.length) return '已暂停'
  return '—'
})
const totalUploadSpeed = computed(() => {
  const speed = processingTasks.value.reduce((sum, task) => sum + getVisibleUploadSpeed(task), 0)
  if (speed > 0) return formatSpeed(speed)
  if (!processingTasks.value.length && pausedTasks.value.length) return '已暂停'
  return '—'
})
const totalRemainingTransferBytes = computed(() => {
  return processingTasks.value.reduce((sum, task) => {
    return sum + getTaskRemainingBytes(task)
  }, 0)
})
const remainingTransferSize = computed(() => formatSize(totalRemainingTransferBytes.value))
const aggregatedTransferEta = computed(() => {
  const downloadSpeed = processingTasks.value.reduce((sum, task) => sum + getVisibleDownloadSpeed(task), 0)
  const uploadSpeed = processingTasks.value.reduce((sum, task) => sum + getVisibleUploadSpeed(task), 0)
  const downloadRemainingBytes = processingTasks.value.reduce((sum, task) => sum + getDownloadRemainingBytes(task), 0)
  const uploadRemainingBytes = processingTasks.value.reduce((sum, task) => sum + getUploadRemainingBytes(task), 0)
  const downloadEta = downloadSpeed > 0 && downloadRemainingBytes > 0 ? Math.ceil(downloadRemainingBytes / downloadSpeed) : 0
  const uploadEta = uploadSpeed > 0 && uploadRemainingBytes > 0 ? Math.ceil(uploadRemainingBytes / uploadSpeed) : 0
  const etaSeconds = downloadEta + uploadEta
  if (etaSeconds > 0) return formatEtaSeconds(etaSeconds)
  if (totalRemainingTransferBytes.value <= 0 && processingTasks.value.length) return '已接近完成'
  return '—'
})
const remainingTaskSummary = computed(() => {
  const remaining = processingTasks.value.length + pendingTasks.value.length
  if (remaining) return `${remaining} 个`
  if (partialFailedTasks.value.length > 0) return '有失败'
  return '已全部完成'
})

watch(() => mergedTasks.value.map(task => task.id).join(':'), () => {
  const taskIds = mergedTasks.value.map(task => task.id)
  const activeIds = new Set(taskIds)
  const nextExpanded = new Set([...expandedTaskIds.value].filter(id => activeIds.has(id)))
  if (taskIds.length === 1) nextExpanded.add(taskIds[0])
  expandedTaskIds.value = nextExpanded
}, { immediate: true })

function toggleExpanded(taskId) {
  const task = mergedTasks.value.find(item => item.id === taskId)
  const next = new Set(expandedTaskIds.value)
  if (next.has(taskId)) next.delete(taskId)
  else {
    next.add(taskId)
    if (task?.download_files_truncated) emit('load-files', task)
  }
  expandedTaskIds.value = next
}

watch(
  () => [virtualFileTask.value?.id || '', virtualFileRows.value.length].join(':'),
  () => {
    nextTick(() => fileRowVirtualizer.value.measure())
  },
  { immediate: true },
)

function iconToneClass(task) {
  const tone = getTaskTone(task)
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  if (['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))) return 'pending'
  return 'processing'
}

function statusToneClass(task) {
  const tone = getTaskTone(task)
  if (tone === 'success' && isUploadEnabled(task)) return 'upload-success'
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  if (['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))) return 'pending'
  return 'processing'
}

function taskCardToneClass(task) {
  const tone = getTaskTone(task)
  if (tone === 'warning') return 'is-warning'
  if (tone === 'danger') return 'is-danger'
  if (tone === 'success') return 'is-success'
  if (isTaskProcessing(task)) return 'is-processing'
  if (isTaskPaused(task)) return 'is-paused'
  return 'is-pending'
}

function fileToneClass(file) {
  if (file.tone === 'success') return 'success'
  if (file.tone === 'upload-success') return 'upload-success'
  if (file.tone === 'danger') return 'danger'
  if (file.tone === 'upload') return 'upload'
  if (file.tone === 'processing') return 'processing'
  return 'neutral'
}

function compactFileSizeText(file) {
  if (file.sizeText) return file.sizeText.replace(/^下载大小\s*/, '').replace(/^下载\s*/, '').replace(/^上传\s*/, '')
  return '0 B'
}

function getTaskIcon(task) {
  const tone = getTaskTone(task)
  if (tone === 'success') return CheckCircle2
  if (tone === 'warning' || tone === 'danger') return TriangleAlert
  if (props.preferUploadIcon && isUploadEnabled(task)) return ArrowUpToLine
  if (getTaskStageLabel(task).includes('上传')) return HardDriveUpload
  const mode = String(task?.task_metadata?.download_mode || task?.download_mode || '').trim()
  if (mode === 'baidu_netdisk') return CloudDownload
  if (mode === 'pikpak') return Cloud
  if (['pending', 'waiting_retry'].includes(String(task?.display_status || task?.status || ''))) return Clock3
  return Download
}

function getTaskLottie(task) {
  if (isTaskSuccess(task)) return successConfettiAnimation
  const tone = getTaskTone(task)
  if (tone === 'warning' || tone === 'danger') return ''
  const stage = getTaskStageLabel(task)
  if (props.preferUploadIcon && isUploadEnabled(task)) return uploadToCloudAnimation
  if (stage.includes('上传')) return uploadToCloudAnimation
  return downloadIconAnimation
}

function isUploadLottie(task) {
  return getTaskLottie(task) === uploadToCloudAnimation
}

function isTaskSuccess(task) {
  return getTaskTone(task) === 'success'
}

function getTaskStatusMetaIcon(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'completed') return CheckCircle2
  if (status === 'failed' || status === 'partial_failed') return TriangleAlert
  if (status === 'paused' || status === 'pending' || status === 'waiting_retry') return Clock3
  return Archive
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

function getLogTimeValue(entry) {
  return entry?.time || entry?.timestamp || entry?.created_at || entry?.ts || ''
}

function getLogMessage(entry) {
  return String(entry?.message || entry?.text || '').trim()
}

function getLogTimestamp(entry) {
  const value = getLogTimeValue(entry)
  if (!value) return 0
  const date = new Date(value)
  if (!Number.isNaN(date.getTime())) return date.getTime()
  const match = String(value).match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/)
  if (!match) return 0
  const hours = Number(match[1] || 0)
  const minutes = Number(match[2] || 0)
  const seconds = Number(match[3] || 0)
  return hours * 3600 + minutes * 60 + seconds
}

function shouldSkipUploadLogNoise(entry, index, entries) {
  if (!isUploadMode.value) return false
  const message = entry.message
  const nextMessage = entries[index + 1]?.message || ''
  if (message === '准备上传目录' && /^准备上传\s*\d+\s*个目录$/.test(nextMessage)) return true
  const startMatch = message.match(/^上传目录\s*(\d+\/\d+)[:：]\s*(.+)$/)
  if (startMatch && nextMessage === `开始上传目录 ${startMatch[2]}`) return true
  return false
}

function getVisibleProgressLogs(task) {
  const entries = (Array.isArray(task?.progress_log) ? task.progress_log : [])
    .map((entry) => ({
      ...entry,
      timeKey: getLogTimeValue(entry),
      message: getLogMessage(entry),
      progress: entry?.progress,
      level: entry?.level || 'info',
    }))
    .filter(entry => entry.message)

  const compacted = []
  entries.forEach((entry, index) => {
    if (shouldSkipUploadLogNoise(entry, index, entries)) return
    const last = compacted[compacted.length - 1]
    if (
      last &&
      last.message === entry.message &&
      last.progress === entry.progress &&
      String(last.level || '') === String(entry.level || '')
    ) return
    compacted.push(entry)
  })

  return compacted.slice(-6)
}

function formatLogTime(value) {
  if (!value) return '--:--:--'
  if (/^\d{1,2}:\d{2}(?::\d{2})?$/.test(String(value))) return String(value)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function getTaskSessionId(task) {
  return String(task?.task_metadata?.session_id || task?.session_id || task?.id || '').trim()
}

function getTaskRjcode(task) {
  return String(task?.rjcode || task?.task_metadata?.rjcode || '').trim().toUpperCase()
}

function normalizeLabel(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function labelsEqual(left, right) {
  return normalizeLabel(left).toLowerCase() === normalizeLabel(right).toLowerCase()
}

function getTaskPrimaryTitle(task) {
  return normalizeLabel(task?.work_title || task?.task_metadata?.work_title || task?.source_label || task?.task_metadata?.source_label) || '未命名任务'
}

function getTaskSecondaryLabel(task) {
  const primaryTitle = getTaskPrimaryTitle(task)
  const pickDistinctLabel = (labels = []) => {
    for (const label of labels) {
      const normalized = normalizeLabel(label)
      if (normalized && !labelsEqual(normalized, primaryTitle)) return normalized
    }
    return ''
  }

  if (isUploadMode.value) {
    return pickDistinctLabel([
      task?.task_metadata?.workbench_subtitle,
      task?.task_metadata?.source_label,
      task?.source_label,
      task?.task_metadata?.rjcode,
      task?.rjcode,
    ]) || '上传任务'
  }
  const mode = String(task?.task_metadata?.download_mode || task?.download_mode || '').trim()
  if (mode === 'http' || mode === 'pikpak' || mode === 'mixed' || mode === 'baidu_netdisk') {
    return pickDistinctLabel([
      task?.task_metadata?.workbench_subtitle,
      task?.task_metadata?.source_label,
      task?.source_label,
      task?.task_metadata?.rjcode,
      task?.rjcode,
    ]) || (mode === 'baidu_netdisk' ? '百度网盘下载' : mode === 'pikpak' ? 'PikPak 下载' : 'HTTP 下载')
  }
  return pickDistinctLabel([task?.task_metadata?.workbench_subtitle, task?.rjcode, task?.task_metadata?.rjcode]) || '未知 RJ'
}

function getTaskSourceAction(task) {
  return String(task?.task_metadata?.source_action || task?.source_action || '').trim()
}

function getTaskLocalDownloadRoot(task) {
  return String(task?.task_metadata?.local_download_root || task?.session_state?.local_download_root || task?.task_metadata?.download_root || '').trim()
}

function getTaskMergeKey(task) {
  if (isUploadMode.value) return `task:${String(task?.id || '').trim()}`
  const mode = String(task?.task_metadata?.download_mode || task?.download_mode || '').trim()
  if (mode === 'http' || mode === 'pikpak' || mode === 'mixed' || mode === 'baidu_netdisk') return `task:${String(task?.id || '').trim()}`
  const sessionId = getTaskSessionId(task)
  const rjcode = getTaskRjcode(task)
  if (sessionId) return `session:${sessionId}::${rjcode || 'unknown'}`
  const sourceAction = getTaskSourceAction(task)
  const localDownloadRoot = getTaskLocalDownloadRoot(task)
  if ((sourceAction === 'reimport_local_download_root' || sourceAction === 'reimport_downloaded_session') && rjcode && localDownloadRoot) return `reimport:${rjcode}::${localDownloadRoot.toLowerCase()}`
  if (rjcode && localDownloadRoot) return `download-root:${rjcode}::${localDownloadRoot.toLowerCase()}`
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
  const mergedFileCollections = mergeLatestFileCollections(sorted)
  const mergedLogs = [...sorted]
    .flatMap(task => Array.isArray(task?.progress_log) ? task.progress_log : [])
    .sort((a, b) => getLogTimestamp(a) - getLogTimestamp(b))
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
    download_files: mergedFileCollections.download_files,
    upload_files: mergedFileCollections.upload_files,
    uploaded_files: mergedFileCollections.uploaded_files,
    failed_files: mergedFileCollections.failed_files,
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
  const hasSuccess = rows.some(item => isSuccessfulFileTone(item.tone))
  const allCompleted = rows.every(item => isSuccessfulFileTone(item.tone))
  return { rows, allCompleted, hasDanger, hasSuccess }
}

function deriveMergedStatus(task, sourceTasks) {
  const statuses = (sourceTasks || []).map(item => String(item?.status || ''))
  const { allCompleted, hasDanger, hasSuccess } = getTaskRowsCompletionState(task)
  const hasFinalOutputPath = getFinalOutputPath(task) !== '处理中'
  const percent = getTaskOverallPercent(task)
  if (statuses.includes('paused')) return 'paused'
  if (hasAnyActiveRuntime(task)) return 'processing'
  if (allCompleted && percent >= 100 && hasFinalOutputPath) return 'completed'
  if (hasDanger) return hasSuccess ? 'partial_failed' : 'failed'
  if (statuses.includes('pending')) return 'pending'
  if (statuses.includes('waiting_retry')) return 'waiting_retry'
  if (statuses.includes('completed')) return 'completed'
  if (statuses.includes('failed')) return 'failed'
  if (statuses.includes('processing')) return 'processing'
  return String(sourceTasks?.[0]?.status || 'pending')
}

function deriveMergedDisplayStatus(task, sourceTasks, mergedStatus) {
  const { allCompleted, hasDanger, hasSuccess } = getTaskRowsCompletionState(task)
  if ((sourceTasks || []).some(item => String(item?.status || '') === 'paused')) return 'paused'
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

function mergeLatestFileCollections(tasks) {
  const latestByPath = new Map()
  const pushFiles = (bucket, items, task) => {
    ;(Array.isArray(items) ? items : []).forEach((file, index) => {
      const key = String(file?.relative_path || file?.name || file?.file_name || `row-${index}`).trim()
      if (!key || latestByPath.has(key)) return
      latestByPath.set(key, {
        bucket,
        file: { ...file, __task_status: String(task?.status || '') },
      })
    })
  }

  ;(tasks || []).forEach((task) => {
    pushFiles('uploaded_files', task?.uploaded_files, task)
    pushFiles('failed_files', task?.failed_files, task)
    pushFiles('upload_files', task?.upload_files, task)
    pushFiles('download_files', task?.download_files, task)
  })

  const merged = {
    download_files: [],
    upload_files: [],
    uploaded_files: [],
    failed_files: [],
  }
  latestByPath.forEach(({ bucket, file }) => {
    merged[bucket].push(file)
  })
  return merged
}

function formatEtaSeconds(value) {
  const seconds = Math.max(0, Number(value || 0))
  if (!seconds) return '—'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return secs > 0 ? `${mins}分${secs}秒` : `${mins}分`
  }
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return mins > 0 ? `${hours}时${mins}分` : `${hours}时`
}

function isSuccessfulFileTone(tone) {
  return ['success', 'upload-success'].includes(String(tone || ''))
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

function isTaskPaused(task) {
  return String(task?.display_status || task?.status || '') === 'paused'
}

function getDownloadTaskDomain(task) {
  return String(
    task?.task_domain ||
    task?.type ||
    task?.task_kind ||
    task?.task_metadata?.task_domain ||
    task?.task_metadata?.task_kind ||
    task?.task_metadata?.download_mode ||
    task?.download_mode ||
    '',
  ).trim()
}

function isDownloadOnlyTask(task) {
  const domain = getDownloadTaskDomain(task)
  return [
    'baidu_netdisk',
    'baidu_netdisk_download',
    'http_download',
    'http',
    'pikpak',
    'mixed',
  ].includes(domain)
}

function isUploadEnabled(task) {
  if (isUploadMode.value) return true
  if (isDownloadOnlyTask(task)) return false
  const explicitUpload = Boolean(
    task?.task_metadata?.upload_options?.enabled ||
    task?.upload_options?.enabled ||
    ['local', 'synology'].includes(String(task?.task_metadata?.upload_mode || task?.upload_mode || '').trim())
  )
  if (explicitUpload) return true

  const hasUploadRows = (Array.isArray(task?.upload_files) && task.upload_files.length > 0) || (Array.isArray(task?.uploaded_files) && task.uploaded_files.length > 0)
  if (hasUploadRows) return true

  const finalPath = String(getFinalOutputPath(task) || '').trim()
  const downloadRoot = String(getDownloadRoot(task) || '').trim()
  if (finalPath && finalPath !== '处理中' && downloadRoot && finalPath !== downloadRoot) return true

  const progressLogs = Array.isArray(task?.progress_log) ? task.progress_log : []
  if (progressLogs.some(entry => /已入库|上传完成|上传成功|入库完成/.test(String(entry?.message || '')))) return true

  return false
}

function getVisibleDownloadSpeed(task) {
  if (isTaskPaused(task)) return 0
  const runtime = getDownloadRuntime(task)
  const runtimeSpeed = Number(runtime?.speed_bytes_per_sec || 0)
  return isTaskProcessing(task) && hasActiveDownloadRuntime(task) && runtimeSpeed > 0 ? runtimeSpeed : 0
}

function getVisibleUploadSpeed(task) {
  if (!isUploadMode.value && !isUploadEnabled(task)) return 0
  if (isTaskPaused(task)) return 0
  const runtime = getUploadRuntime(task)
  const runtimeSpeed = Number(runtime?.speed_bytes_per_sec || 0)
  const hasActiveUploadHint = hasActiveUploadRuntime(task) || Boolean(String(runtime?.current_relative_path || '').trim())
  return isTaskProcessing(task) && hasActiveUploadHint && runtimeSpeed > 0 ? runtimeSpeed : 0
}

function getUploadEtaSeconds(task) {
  if (!isUploadMode.value && !isUploadEnabled(task)) return 0
  const runtime = getUploadRuntime(task)
  const runtimeEta = Number(runtime?.eta_seconds || 0)
  if (runtimeEta > 0) return runtimeEta
  const speed = getVisibleUploadSpeed(task)
  const remainingBytes = getUploadRemainingBytes(task)
  if (speed > 0 && remainingBytes > 0) return Math.ceil(remainingBytes / speed)
  return 0
}

function getTaskRemainingBytes(task) {
  if (isUploadMode.value) return Math.max(0, getUploadTotalBytes(task) - getTaskUploadedBytes(task))
  const downloadRemaining = getDownloadRemainingBytes(task)
  if (!isUploadEnabled(task)) return downloadRemaining
  const uploadRemaining = Math.max(0, getUploadTotalBytes(task) - getTaskUploadedBytes(task))
  return downloadRemaining + uploadRemaining
}

function getDownloadRemainingBytes(task) {
  if (isUploadMode.value) return 0
  return Math.max(0, getDownloadTotalBytes(task) - getTaskDownloadedBytes(task))
}

function getUploadRemainingBytes(task) {
  if (!isUploadMode.value && !isUploadEnabled(task)) return 0
  return Math.max(0, getUploadTotalBytes(task) - getTaskUploadedBytes(task))
}

function getDownloadTotalBytes(task) {
  if (isUploadMode.value) return 0
  const runtimeBytes = Number(getDownloadRuntime(task)?.total_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const downloadFiles = Array.isArray(task?.download_files) ? task.download_files : []
  const totalBytes = downloadFiles.reduce((sum, item) => sum + Number(item?.size_bytes || item?.size || item?.total || 0), 0)
  if (totalBytes > 0) return totalBytes
  return getTaskTransferBytes(task)
}

function getUploadTotalBytes(task) {
  if (!isUploadMode.value && !isUploadEnabled(task)) return 0
  const runtimeBytes = Number(getUploadRuntime(task)?.total_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const totalBytes = uploadFiles.reduce((sum, item) => sum + Number(item?.size_bytes || item?.size || item?.total || 0), 0)
  if (totalBytes > 0) return totalBytes
  return getTaskTransferBytes(task)
}

function getTaskTransferBytes(task) {
  if (isUploadMode.value) {
    const runtimeBytes = Number(getUploadRuntime(task)?.total_bytes || 0)
    if (runtimeBytes > 0) return runtimeBytes
    const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
    const uploadBytes = uploadFiles.reduce((sum, item) => sum + Number(item?.size_bytes || item?.size || item?.total || 0), 0)
    if (uploadBytes > 0) return uploadBytes
  }
  const rowTotal = getUnifiedFileRows(task).reduce((sum, row) => sum + Number(row.total || 0), 0)
  if (rowTotal > 0) return rowTotal
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const selectedBytes = selectedResources.reduce((sum, item) => sum + Number(item?.size_bytes || item?.size || 0), 0)
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
  return getUnifiedFileRows(task).filter(item => ['success', 'upload-success'].includes(String(item.tone || ''))).length
}

function getFailureCount(task) {
  return getUnifiedFileRows(task).filter(item => item.tone === 'danger').length
}

function hasTaskFailures(task) {
  return getFailureCount(task) > 0 || Boolean(String(task?.task_metadata?.failure_reason || '').trim() || String(task?.error_message || '').trim())
}

function getDownloadTaskStatusLabel(task) {
  const status = String(task?.display_status || task?.status || '')
  const map = { pending: '等待中', processing: '处理中', completed: '已完成', partial_failed: '部分失败', failed: '失败', paused: '已暂停', waiting_retry: '等待重试' }
  if (status === 'completed' && isUploadEnabled(task)) return '已上传 / 已入库'
  return map[status] || (status || '未知')
}

function normalizeTaskMessage(message) {
  return String(message || '')
    .trim()
    .replace(/^失败[:：]\s*/u, '')
}

function getTaskSummaryStepText(task) {
  const currentStep = String(task?.current_step || '').trim()
  if (!currentStep) return ''

  // 被后续任务覆盖：显示简洁文案，不要露出 UUID
  if (currentStep.startsWith('已由后续成功任务覆盖')) {
    return isUploadMode.value ? '上传任务状态已恢复，请刷新后继续查看' : '已由其他任务完成，此条任务已合并'
  }

  const errorMessage = String(task?.error_message || task?.task_metadata?.failure_reason || '').trim()
  if (!errorMessage) return currentStep

  const normalizedStep = normalizeTaskMessage(currentStep)
  const normalizedError = normalizeTaskMessage(errorMessage)

  if (normalizedStep && normalizedError && normalizedStep === normalizedError) {
    return ''
  }

  return currentStep
}

function getTaskTone(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'failed') return 'danger'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return 'warning'
  if (status === 'completed') return 'success'
  return 'neutral'
}

function getTaskStageLabel(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'waiting_retry') return '等待重试'
  if (status === 'pending') return isUploadMode.value ? '等待上传' : '等待开始'
  if (status === 'paused') return '已暂停'
  if (status === 'failed') return '失败'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return '部分失败'
  if (status === 'completed') return isUploadEnabled(task) ? '已上传 / 已入库' : '已完成'
  const uploadRuntime = getUploadRuntime(task)
  const downloadRuntime = getDownloadRuntime(task)
  if (Number(uploadRuntime?.active_file_count || 0) > 0) return '上传 / 入库中'
  if (Number(downloadRuntime?.active_file_count || 0) > 0) return '下载中'
  if (Number(uploadRuntime?.is_waiting_turn || 0) > 0 && String(uploadRuntime?.current_relative_path || '').trim()) return '上传准备中'
  if (isUploadEnabled(task) && getUploadCompletedCount(task) > 0 && getDownloadCompletedCount(task) > getUploadCompletedCount(task)) return '上传准备中'
  return '处理中'
}

function getTaskOverallPercent(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'completed') return 100
  const transferTotal = getTaskTransferBytes(task)
  if (!transferTotal) return Math.max(0, Math.min(99, Math.floor(Number(task?.progress || 0))))
  // 上传专用任务（无下载文件）：直接按上传进度 0-100%
  const hasDownloadFiles = Array.isArray(task?.download_files) && task.download_files.length > 0
  if (!hasDownloadFiles && isUploadEnabled(task)) {
    const uploadTotal = getUploadTotalBytes(task) || transferTotal
    const uploadedBytes = Math.max(0, getTaskUploadedBytes(task))
    const percent = Math.max(0, Math.min(100, Math.floor(Math.min(1, uploadedBytes / uploadTotal) * 100)))
    return uploadedBytes < uploadTotal ? Math.min(percent, 99) : Math.min(percent, 99)
  }
  // 下载+上传并行任务：下载和上传各贡献 0-50%，合并为 0-100%
  if (isUploadEnabled(task)) {
    const uploadTotal = getUploadTotalBytes(task) || transferTotal
    const downloadFraction = Math.min(1, getTaskDownloadedBytes(task) / transferTotal)
    const uploadFraction = Math.min(1, getTaskUploadedBytes(task) / uploadTotal)
    const percent = Math.max(0, Math.min(100, Math.floor((downloadFraction + uploadFraction) / 2 * 100)))
    return Math.min(percent, 99)
  }
  const downloadedBytes = Math.max(0, getTaskDownloadedBytes(task))
  const downloadTotal = Math.max(0, getDownloadTotalBytes(task) || transferTotal)
  if (downloadTotal > 0) {
    const percent = Math.max(0, Math.min(100, Math.floor(downloadedBytes / downloadTotal * 100)))
    return downloadedBytes < downloadTotal ? Math.min(percent, 99) : Math.min(percent, 99)
  }
  const rows = getUnifiedFileRows(task)
  if (rows.length) {
    const weighted = rows.reduce((summary, item) => {
      const total = Math.max(0, Number(item.total || 0))
      const downloaded = Math.max(0, Number(item.downloadedBytes || 0))
      return {
        total: summary.total + total,
        downloaded: summary.downloaded + Math.min(downloaded, total),
      }
    }, { total: 0, downloaded: 0 })
    if (weighted.total > 0) {
      const percent = Math.floor(weighted.downloaded / weighted.total * 100)
      return Math.max(0, Math.min(99, percent))
    }
  }
  const percent = Math.max(0, Math.min(100, Math.floor((downloadedBytes / transferTotal) * 100)))
  return downloadedBytes < transferTotal ? Math.min(percent, 99) : Math.min(percent, 99)
}

function shouldShowSummaryProgress(task) {
  const status = String(task?.display_status || task?.status || '')
  return !(status === 'completed' && getTaskOverallPercent(task) >= 100)
}

function getPrimaryFileProgressLabel(task) {
  const stage = getTaskStageLabel(task)
  const total = getTaskResourceCount(task)
  if (!total) return '文件 0 / 0'
  if (isUploadMode.value) {
    const uploadedCount = getUploadCompletedCount(task)
    if (getTaskTone(task) === 'success') return `已上传 ${uploadedCount} / ${total}`
    if (getTaskTone(task) === 'warning') return `成功 ${Math.max(0, total - getFailureCount(task))} / ${total}`
    return `上传 ${uploadedCount} / ${total}`
  }
  if (getTaskTone(task) === 'success' && isUploadEnabled(task)) return `已上传 ${getUploadCompletedCount(task)} / ${total}`
  if (stage === '上传 / 入库中' || stage === '上传准备中') return `上传 ${getUploadCompletedCount(task)} / ${total}`
  if (getDownloadCompletedCount(task) >= 0 && getDownloadCompletedCount(task) < total) return `下载 ${getDownloadCompletedCount(task)} / ${total}`
  if (getTaskTone(task) === 'warning') return `成功 ${Math.max(0, total - getFailureCount(task))} / ${total}`
  return `文件 ${getDownloadCompletedCount(task)} / ${total}`
}

function getPrimarySizeText(task) {
  const totalBytes = isUploadMode.value ? (getUploadTotalBytes(task) || getTaskTransferBytes(task)) : getTaskTransferBytes(task)
  const total = formatSize(totalBytes)
  const tone = getTaskTone(task)
  const stage = getTaskStageLabel(task)
  const downloadSpeedVisible = getVisibleDownloadSpeed(task) > 0
  const uploadSpeedVisible = getVisibleUploadSpeed(task) > 0
  if (isUploadMode.value) {
    const uploaded = tone === 'success' ? Math.max(getTaskUploadedBytes(task), totalBytes) : getTaskUploadedBytes(task)
    return `上传 ${formatSize(uploaded)} / ${total}`
  }
  if (downloadSpeedVisible && uploadSpeedVisible) {
    return `下载 ${formatSize(getTaskDownloadedBytes(task))} / ${total}  上传 ${formatSize(getTaskUploadedBytes(task))} / ${total}`
  }
  if (tone === 'success') {
    if (isUploadEnabled(task)) {
      const uploaded = Math.max(getTaskUploadedBytes(task), getTaskTransferBytes(task))
      return `上传 ${formatSize(uploaded)} / ${total}`
    }
    return `下载大小 ${total}`
  }
  if (stage === '上传 / 入库中' || stage === '上传准备中') return `上传 ${formatSize(getTaskUploadedBytes(task))} / ${total}`
  return `下载 ${formatSize(getTaskDownloadedBytes(task))} / ${total}`
}

function getDownloadRoot(task) {
  if (isUploadMode.value) {
    return task?.task_metadata?.source_root || task?.task_metadata?.source_base_path || task?.source_path || '来源目录处理中'
  }
  return task?.task_metadata?.local_download_root || task?.session_state?.local_download_root || task?.task_metadata?.download_root || task?.task_metadata?.download_base_path || '默认临时目录'
}

function getFinalOutputPath(task) {
  return task?.task_metadata?.final_output_path || task?.task_metadata?.renamed_output_path || task?.output_path || task?.task_metadata?.target_path || '处理中'
}

function getFinalOutputDisplay(task) {
  const resolved = String(task?.task_metadata?.final_output_path || task?.task_metadata?.renamed_output_path || task?.output_path || task?.task_metadata?.target_path || '').trim()
  if (resolved) return resolved
  const status = String(task?.display_status || task?.status || '')
  if (isUploadMode.value) return ['completed', 'partial_failed', 'failed'].includes(status) ? '目标路径未返回' : '目标路径处理中'
  if (status === 'completed' || status === 'partial_failed' || status === 'failed') {
    return '未配置入库目标 · 仍在下载目录'
  }
  return '处理中'
}

function canRetryDownloadTask(task) {
  if (isUploadMode.value) return false
  const domain = String(task?.task_domain || task?.task_metadata?.task_domain || task?.task_metadata?.download_mode || '').trim()
  if (domain === 'http_download' || domain === 'http' || domain === 'baidu_netdisk') {
    return ['failed', 'partial_failed', 'completed'].includes(String(task?.display_status || task?.status || '')) && hasTaskFailures(task)
  }
  return Boolean(String(task?.task_metadata?.session_id || task?.session_id || '').trim() && getFailureCount(task) > 0)
}

function getUnifiedFileRows(task) {
  if (!task || typeof task !== 'object') return []

  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const downloadFiles = Array.isArray(task?.download_files) ? task.download_files : []
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const uploadedFiles = Array.isArray(task?.uploaded_files) ? task.uploaded_files : []
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files : []
  const downloadRuntime = getDownloadRuntime(task)
  const uploadRuntime = getUploadRuntime(task)
  const signature = [
    isUploadMode.value ? 'upload' : 'download',
    task?.status,
    task?.display_status,
    task?.progress,
    task?.updated_at,
    selectedResources.length,
    downloadFiles.length,
    uploadFiles.length,
    uploadedFiles.length,
    failedFiles.length,
    downloadRuntime?.transferred_bytes,
    downloadRuntime?.speed_bytes_per_sec,
    downloadRuntime?.current_relative_path,
    uploadRuntime?.transferred_bytes,
    uploadRuntime?.speed_bytes_per_sec,
    uploadRuntime?.current_relative_path,
  ].map(item => String(item ?? '')).join('|')
  const cached = unifiedRowsCache.get(task)
  if (cached?.signature === signature) return cached.rows

  const rows = buildUnifiedFileRows(task)
  unifiedRowsCache.set(task, { signature, rows })
  return rows
}

function buildUnifiedFileRows(task) {
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
      key: rowKey,
      name: payload.name || payload.file_name || payload.relative_path || '未知文件',
      relative_path: payload.relative_path || '',
      total: Number(payload.size_bytes || payload.size || 0),
      downloadedBytes: 0,
      uploadedBytes: 0,
      sourceTaskStatus: '',
      progress: 0,
      tone: 'neutral',
      reason: '',
      retryable: false,
      statusText: '等待中',
      stageLabel: '等待中',
      sizeText: (payload.size_bytes || payload.size)
        ? `${isUploadMode.value ? '上传大小' : '下载大小'} ${formatSize(payload.size_bytes || payload.size)}`
        : `${isUploadMode.value ? '上传大小' : '下载大小'} 0 B`,
      downloadSpeed: 0,
      uploadSpeed: 0,
      downloadSpeedVisible: false,
      uploadSpeedVisible: false,
      index: Number(payload.index || 0),
      rawFile: {},
    }
    const next = {
      ...existing,
      name: payload.name || payload.file_name || existing.name,
      relative_path: payload.relative_path || existing.relative_path,
      total: Math.max(Number(payload.total || payload.size_bytes || payload.size || 0), Number(existing.total || 0)),
      index: Number(payload.index || existing.index || 0),
      rawFile: { ...(existing.rawFile || {}), ...(payload.rawFile || payload || {}) },
    }
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
    } else {
      row.stageLabel = progress >= 100 ? (uploadEnabled ? '上传准备中' : '已下载') : (fileTaskProcessing ? '下载中' : '等待重试')
      row.statusText = row.stageLabel
      row.tone = progress >= 100 ? (uploadEnabled ? 'upload' : 'neutral') : (fileTaskProcessing ? 'processing' : 'neutral')
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
    row.stageLabel = Number(file.progress || 0) >= 100 ? '已上传' : '上传中'
    row.statusText = row.stageLabel
    row.sizeText = Number(file.progress || 0) >= 100 ? `上传 ${formatSize(row.total)} / ${formatSize(row.total)}` : `上传 ${formatSize(file.uploaded || 0)} / ${formatSize(row.total)}`
    row.tone = Number(file.progress || 0) >= 100 ? 'upload-success' : 'upload'
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
    row.stageLabel = uploadEnabled ? '已上传' : '已完成'
    row.statusText = row.stageLabel
    row.sizeText = uploadEnabled ? `上传 ${formatSize(sizeBytes)} / ${formatSize(sizeBytes)}` : `下载大小 ${formatSize(sizeBytes)}`
    row.tone = uploadEnabled ? 'upload-success' : 'success'
  })

  failedFiles.forEach((file) => {
    const row = ensureRow(file.relative_path || file.name, file)
    if (!row) return
    const keepActiveState = String(row.sourceTaskStatus || '') === 'processing' && ['processing', 'upload', 'success'].includes(String(row.tone || ''))
    if (keepActiveState) return
    row.downloadedBytes = Number(file.stage === 'upload' ? (row.total || 0) : (file.downloaded || row.downloadedBytes || 0))
    row.uploadedBytes = Number(file.stage === 'upload' ? (file.uploaded || 0) : 0)
    row.reason = String(file.reason || file.failure_reason || file.error_message || file.exception_type || '失败').trim()
    row.rawFile = { ...(row.rawFile || {}), ...file }
    row.retryable = props.enableFileRetry && Boolean(
      row.relative_path ||
      file.relative_path ||
      file.selection_key ||
      file.file_id ||
      file.download_file_id ||
      file.content_id ||
      file.name ||
      file.filename
    )
    row.tone = 'danger'
    const failedStage = String(file.stage || '').trim()
    const resolvedFailedStage = isUploadMode.value && !failedStage ? 'upload' : failedStage
    row.stageLabel = resolvedFailedStage === 'upload' ? '上传失败' : '下载失败'
    row.statusText = row.stageLabel
    row.sizeText = resolvedFailedStage === 'upload' ? `上传 ${formatSize(file.uploaded || 0)} / ${formatSize(row.total)}` : `下载 ${formatSize(file.downloaded || 0)} / ${formatSize(row.total)}`
  })

  const taskCompleted = String(task?.display_status || task?.status || '') === 'completed'
  const taskHasFailures = failedFiles.length > 0 || Boolean(String(task?.task_metadata?.failure_reason || '').trim() || String(task?.error_message || '').trim())
  const taskHasFinalOutput = getFinalOutputPath(task) !== '处理中'
  if (taskCompleted && !taskHasFailures && taskHasFinalOutput) {
    rows.forEach((row) => {
      if (row.tone === 'danger') return
      const totalBytes = Number(row.total || 0)
      if (totalBytes <= 0) return
      if (Number(row.downloadedBytes || 0) <= 0) row.downloadedBytes = totalBytes
      if (isUploadEnabled(task)) {
        if (Number(row.uploadedBytes || 0) <= 0) row.uploadedBytes = totalBytes
        row.stageLabel = '已上传'
        row.statusText = '已上传'
        row.sizeText = `上传 ${formatSize(totalBytes)} / ${formatSize(totalBytes)}`
        row.tone = 'upload-success'
      } else {
        row.stageLabel = '已完成'
        row.statusText = '已完成'
        row.sizeText = `下载大小 ${formatSize(totalBytes)}`
        row.tone = 'success'
      }
      row.progress = 100
      row.downloadSpeed = 0
      row.uploadSpeed = 0
      row.downloadSpeedVisible = false
      row.uploadSpeedVisible = false
    })
  }

  return [...rows.values()].sort((a, b) => {
    return (a.index || 0) - (b.index || 0)
  })
}
</script>

<style scoped>
.v1-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 16px;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.v1-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1320px;
  height: min(90vh, 920px);
  overflow: hidden;
  border: 1px solid rgba(24, 24, 27, 0.08);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(22px) saturate(1.08);
  -webkit-backdrop-filter: blur(22px) saturate(1.08);
  box-shadow:
    0 24px 64px rgba(24, 24, 27, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  font-family: "Manrope", "Inter", "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
  isolation: isolate;
}

.v1-shell::before,
.v1-shell::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.v1-shell::before {
  inset: 1px 1px auto 1px;
  height: 118px;
  border-radius: 23px 23px 16px 16px;
  background: linear-gradient(180deg, rgba(255,255,255,0.72) 0%, rgba(255,255,255,0.28) 72%, rgba(255,255,255,0) 100%);
  opacity: 0.74;
}

.v1-shell::after {
  display: none;
}

.v1-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  padding: 26px 36px 16px;
  background: rgba(255, 255, 255, 0.62);
  border-bottom: 1px solid rgba(24, 24, 27, 0.08);
}

.v1-header-copy { display: flex; flex-direction: column; justify-content: center; min-height: 76px; }
.v1-title { color: #18181b; font-size: 23px; font-weight: 800; letter-spacing: 0; line-height: 1; }
.v1-subtitle { margin-top: 6px; color: #71717a; font-size: 12px; font-weight: 600; letter-spacing: 0; }
.v1-tabs { display: flex; gap: 20px; margin-top: 16px; flex-wrap: wrap; align-items: center; }
.v1-tab { display: inline-flex; align-items: center; gap: 8px; padding: 0 0 9px; border: none; border-bottom: 2px solid transparent; background: transparent; color: #71717a; font-size: 14px; font-weight: 700; cursor: pointer; transition: color .18s ease, transform .18s ease, border-color .18s ease; }
.v1-tab.active { color: #18181b; border-bottom-color: #18181b; }
.v1-tab:hover { color: #27272a; transform: translateY(-1px); }
.v1-tab-badge { min-width: 23px; padding: 0 8px; border-radius: 999px; background: #f4f4f5; color: #3f3f46; font-size: 11px; line-height: 21px; text-align: center; }
.v1-header-tools { display: flex; align-items: center; gap: 10px; min-height: 76px; }
.v1-search { display: inline-flex; align-items: center; gap: 10px; width: 274px; height: 40px; padding: 0 14px; border-radius: 999px; background: rgba(255, 255, 255, 0.72); color: #71717a; box-shadow: 0 1px 4px rgba(24, 24, 27, 0.06); transition: box-shadow .18s ease, transform .18s ease, background-color .18s ease, border-color .18s ease; border: 1px solid rgba(24, 24, 27, 0.1); }
.v1-search:focus-within { background: rgba(255, 255, 255, 0.9); box-shadow: 0 0 0 3px rgba(24,24,27,.09), 0 8px 20px rgba(24, 24, 27, 0.08); transform: translateY(-1px); border-color: rgba(24,24,27,.24); }
.v1-search input { width: 100%; border: none; background: transparent; color: #27272a; font-size: 13px; outline: none; }
.v1-icon-button { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border: 1px solid rgba(24, 24, 27, 0.1); border-radius: 999px; background: rgba(255, 255, 255, 0.72); color: #52525b; cursor: pointer; transition: background-color .18s ease, transform .18s ease, color .18s ease, box-shadow .18s ease, border-color .18s ease; box-shadow: 0 1px 4px rgba(24,24,27,.06); }
.v1-icon-button:hover { background: rgba(244, 244, 245, 0.92); color: #18181b; transform: translateY(-1px) scale(1.03); border-color: rgba(24, 24, 27, 0.18); box-shadow: 0 8px 18px rgba(24, 24, 27, 0.1); }
.v1-icon-button:active { transform: translateY(0) scale(0.98); }
.v1-icon-button.spinning svg { animation: v1-refresh-spin .9s linear infinite; }
.v1-body { flex: 1; overflow-y: auto; padding: 14px 36px 12px; background: rgba(248, 250, 252, 0.74); }
.v1-task-card { position: relative; margin-bottom: 10px; border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 14px; background: rgba(255, 255, 255, 0.9); box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045); overflow: hidden; cursor: pointer; transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease, background-color .22s ease; }
.v1-task-card::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: #64748b;
  opacity: 0.7;
}
.v1-task-card.is-processing::before { background: #2563eb; }
.v1-task-card.is-success::before { background: #0f766e; }
.v1-task-card.is-warning::before { background: #d97706; }
.v1-task-card.is-danger::before { background: #dc2626; }
.v1-task-card.is-paused::before,
.v1-task-card.is-pending::before { background: #94a3b8; }
.v1-task-card.is-warning { border-color: rgba(217, 119, 6, 0.28); background: linear-gradient(90deg, rgba(255, 251, 235, 0.72), rgba(255, 255, 255, 0.92) 22%); }
.v1-task-card.is-danger { border-color: rgba(220, 38, 38, 0.26); background: linear-gradient(90deg, rgba(254, 242, 242, 0.74), rgba(255, 255, 255, 0.92) 22%); }
.v1-task-card:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08); border-color: rgba(100, 116, 139, 0.3); background: rgba(255, 255, 255, 0.96); }
.v1-task-card.expanded { box-shadow: 0 14px 30px rgba(15, 23, 42, 0.09); border-color: rgba(100, 116, 139, 0.34); }
.v1-task-summary { display: flex; align-items: center; gap: 14px; padding: 13px 16px; min-height: 76px; }
.v1-task-icon { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 64px; flex-shrink: 0; overflow: visible; }
.v1-task-icon-fallback { position: absolute; z-index: 1; opacity: 0.92; }
.v1-task-icon-lottie { width: 54px; height: 54px; pointer-events: none; filter: drop-shadow(0 8px 18px rgba(24,24,27,.12)); background: transparent; }
.v1-task-icon-lottie { position: relative; z-index: 2; }
.v1-task-icon-lottie :deep(canvas) { background: transparent !important; background-color: transparent !important; }
/* 上传动画画布 4:3(1024×768)；用 aspect-ratio 让容器跟随比例，消除上下空白 */
.v1-task-icon-lottie.is-upload-anim { height: auto; aspect-ratio: 4 / 3; }
.v1-task-icon-lottie.paused { opacity: 0.52; filter: grayscale(0.35) saturate(0.65) drop-shadow(0 8px 18px rgba(24,24,27,.08)); }
.v1-task-icon.processing { color: #27272a; }
.v1-task-icon.pending { color: #71717a; }
.v1-task-icon.success { color: #52525b; }
.v1-task-icon.warning { color: #9a5b00; }
.v1-task-icon.danger { color: #b91c1c; }
.v1-task-main { flex: 1; min-width: 0; }
.v1-task-head { display: flex; justify-content: space-between; gap: 14px; align-items: center; }
.v1-task-name-wrap { min-width: 0; flex: 1; }
.v1-task-name { margin: 0; color: #27272a; font-size: 13px; font-weight: 800; line-height: 1.2; letter-spacing: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.v1-task-rj { margin-top: 4px; color: #3f3f46; font-size: 11px; font-weight: 700; line-height: 1; }
.v1-task-actions { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; padding-left: 10px; }
.v1-inline-action { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 54px; min-height: 30px; padding: 0 10px; border: 1px solid rgba(24, 24, 27, 0.1); border-radius: 999px; background: rgba(255, 255, 255, 0.62); color: #3f3f46; font-size: 11px; font-weight: 800; line-height: 1; white-space: nowrap; cursor: pointer; box-shadow: inset 0 1px 0 rgba(255,255,255,.76), 0 4px 12px rgba(24,24,27,.06); transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.v1-inline-action svg { flex-shrink: 0; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.v1-inline-action.primary { color: #18181b; background: rgba(250, 250, 250, 0.8); }
.v1-inline-action.danger { color: #b91c1c; background: rgba(254, 242, 242, 0.72); border-color: rgba(248, 113, 113, 0.24); }
.v1-inline-action.retry { color: #991b1b; background: #fee2e2; border-color: rgba(220, 38, 38, 0.36); box-shadow: inset 0 1px 0 rgba(255,255,255,.78), 0 6px 14px rgba(220, 38, 38, 0.12); }
.v1-inline-action:hover { transform: translateY(-2px) scale(1.02); opacity: .98; background: rgba(255, 255, 255, 0.94); border-color: rgba(24, 24, 27, 0.18); box-shadow: inset 0 1px 0 rgba(255,255,255,.88), 0 10px 18px rgba(24, 24, 27, 0.1); }
.v1-inline-action:hover svg { transform: rotate(-8deg) scale(1.08); }
.v1-inline-action.primary:hover svg { transform: translateX(1px) scale(1.1); }
.v1-inline-action.danger:hover { background: rgba(254, 226, 226, 0.92); border-color: rgba(220, 38, 38, 0.28); color: #991b1b; }
.v1-inline-action.retry:hover { background: #fecaca; border-color: rgba(185, 28, 28, 0.48); color: #7f1d1d; box-shadow: inset 0 1px 0 rgba(255,255,255,.84), 0 10px 18px rgba(220, 38, 38, 0.18); }
.v1-inline-action.danger:hover svg { transform: rotate(10deg) scale(1.08); }
.v1-inline-action:active { transform: translateY(0) scale(0.96); box-shadow: inset 0 1px 3px rgba(24,24,27,.12); }
.v1-inline-action:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }
.v1-inline-action.retry:disabled { opacity: .68; }
.v1-inline-action.retry svg.spinning { animation: v1-refresh-spin .75s linear infinite; }
.v1-task-meta { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-top: 6px; color: #71717a; font-size: 11px; line-height: 1.1; }
.v1-summary-progress { display: flex; align-items: center; gap: 10px; margin-top: 9px; }
.v1-summary-progress :deep(.app-lottie-progress) { flex: 1; }
.v1-summary-progress-text { color: #52525b; font-size: 11px; font-weight: 800; min-width: 34px; text-align: right; font-variant-numeric: tabular-nums; }
.v1-status-line,.v1-speed-line,.v1-eta-line { display: inline-flex; align-items: center; gap: 5px; }
.v1-status-line.processing,.v1-speed-line { color: #27272a; }
.v1-speed-line.upload { color: #3f3f46; }
.v1-eta-line { color: #71717a; }
.v1-status-line.pending { color: #71717a; }
.v1-status-line.success { color: #52525b; }
.v1-status-line.upload-success { color: #52525b; }
.v1-status-line.warning { color: #9a5b00; }
.v1-status-line.danger { color: #b91c1c; }
.v1-status-icon { flex-shrink: 0; opacity: .92; }
.v1-strip-track { width: 100%; height: 5px; overflow: hidden; border-radius: 999px; background: rgba(24, 24, 27, 0.08); }
.v1-strip-fill { height: 100%; border-radius: 999px; background: #52525b; transition: width 0.8s cubic-bezier(0.22, 1, 0.36, 1), background 0.4s ease; }
.v1-strip-fill.processing,.v1-strip-fill.neutral { background: linear-gradient(90deg, #27272a 0%, #52525b 100%); }
.v1-strip-fill.upload { background: linear-gradient(90deg, #3f3f46 0%, #71717a 100%); }
.v1-strip-fill.upload-success { background: linear-gradient(90deg, #52525b 0%, #71717a 100%); }
.v1-strip-fill.success { background: linear-gradient(90deg, #52525b 0%, #71717a 100%); }
.v1-strip-fill.danger { background: #dc2626; }
.v1-task-detail { position: relative; padding: 0 16px 14px; background: rgba(248, 250, 252, 0.76); border-top: 1px solid rgba(148, 163, 184, 0.2); }
.v1-task-detail::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 0 0 16px 16px;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75);
}
.v1-error-box { display: flex; gap: 10px; margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.v1-error-title { font-size: 12px; font-weight: 800; }
.v1-error-text { margin-top: 4px; font-size: 12px; line-height: 1.55; word-break: break-word; }
.v1-path-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.v1-path-card { padding: 10px 12px; border-radius: 12px; background: rgba(255, 255, 255, 0.78); border: 1px solid rgba(24, 24, 27, 0.1); box-shadow: 0 2px 10px rgba(24, 24, 27, 0.04); }
.v1-path-label,.v1-detail-section-label { color: #71717a; font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.v1-path-value { margin-top: 5px; color: #3f3f46; font-size: 12px; line-height: 1.45; word-break: break-all; }
.v1-detail-section { margin-top: 12px; }
.v1-detail-section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.v1-detail-section-subtitle { margin-top: 3px; color: #64748b; font-size: 11px; font-weight: 650; }
.v1-detail-section-count { flex-shrink: 0; border-radius: 999px; border: 1px solid rgba(148, 163, 184, 0.28); background: rgba(255, 255, 255, 0.86); color: #475569; font-size: 10.5px; font-weight: 800; line-height: 20px; padding: 0 8px; }
.v1-file-list,.v1-log-list { margin-top: 8px; }
.v1-file-list {
  display: grid;
  gap: 0;
  max-height: 520px;
  overflow: auto;
  content-visibility: auto;
  contain-intrinsic-size: 520px;
  overscroll-behavior: contain;
}
.v1-file-list.is-virtualized {
  display: block;
  contain: strict;
}
.v1-file-virtual-canvas {
  position: relative;
  width: 100%;
  contain: layout style paint;
}
.v1-file-row {
  padding: 6px 0 8px;
  border: 0;
  border-radius: 0;
  background: transparent;
  content-visibility: auto;
  contain: layout style paint;
  contain-intrinsic-size: 36px;
}
.v1-file-list.is-virtualized .v1-file-row {
  position: absolute;
  right: 0;
  left: 0;
  width: 100%;
}
.v1-file-row + .v1-file-row { border-top: 1px solid rgba(226, 232, 240, 0.78); padding-top: 8px; }
.v1-file-row-top { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; align-items: flex-end; }
.v1-file-row-main,.v1-file-row-side { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.v1-file-row-main { min-width: 0; flex: 1; }
.v1-file-row-name { color: #27272a; font-size: 11px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.v1-file-row-side { color: #71717a; font-size: 10px; justify-content: flex-end; white-space: nowrap; font-variant-numeric: tabular-nums; }
.v1-file-chip { display: inline-flex; align-items: center; min-height: 19px; padding: 0 7px; border-radius: 999px; font-size: 9px; font-weight: 800; }
.v1-file-chip.success { background: #f4f4f5; color: #52525b; }
.v1-file-chip.danger { background: #fee2e2; color: #b91c1c; }
.v1-file-retry { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-height: 23px; border: 1px solid rgba(220, 38, 38, 0.34); border-radius: 999px; background: #fee2e2; color: #b91c1c; font-size: 11px; font-weight: 800; line-height: 1; padding: 0 8px; cursor: pointer; box-shadow: inset 0 1px 0 rgba(255,255,255,.78), 0 4px 10px rgba(220, 38, 38, 0.1); transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.v1-file-retry svg { flex-shrink: 0; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.v1-file-retry:hover:not(:disabled) { transform: translateY(-1px) scale(1.02); background: #fecaca; border-color: rgba(185, 28, 28, 0.46); color: #991b1b; box-shadow: inset 0 1px 0 rgba(255,255,255,.84), 0 8px 16px rgba(220, 38, 38, 0.16); }
.v1-file-retry:hover:not(:disabled) svg:not(.spinning) { transform: rotate(-18deg) scale(1.08); }
.v1-file-retry:active:not(:disabled) { transform: scale(0.96); }
.v1-file-retry:disabled { opacity: .62; cursor: not-allowed; box-shadow: none; }
.v1-file-retry svg.spinning { animation: v1-refresh-spin .75s linear infinite; }
.v1-file-reason { margin-top: 6px; color: #b91c1c; font-size: 11px; line-height: 1.45; }
.v1-log-row { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 9px; color: #52525b; font-size: 11px; line-height: 1.45; }
.v1-log-row + .v1-log-row { margin-top: 4px; }
.v1-log-time { color: #71717a; }
.v1-log-message { word-break: break-word; }

.v1-shell.is-compact .v1-body { padding-top: 12px; padding-bottom: 10px; }
.v1-shell.is-compact .v1-task-card { margin-bottom: 10px; border-radius: 16px; }
.v1-shell.is-compact .v1-task-card::before { display: none; }
.v1-shell.is-compact .v1-task-summary { gap: 12px; padding: 12px 16px; min-height: 72px; }
.v1-shell.is-compact .v1-task-icon { width: 60px; height: 60px; }
.v1-shell.is-compact .v1-task-icon-fallback { font-size: 18px; }
.v1-shell.is-compact .v1-task-icon-lottie { width: 48px; height: 48px; filter: drop-shadow(0 6px 14px rgba(24,24,27,.1)); }
.v1-shell.is-compact .v1-task-icon-lottie.is-upload-anim { height: auto; aspect-ratio: 4 / 3; }
.v1-shell.is-compact .v1-task-name { font-size: 13px; line-height: 1.15; }
.v1-shell.is-compact .v1-task-rj { margin-top: 2px; font-size: 11px; }
.v1-shell.is-compact .v1-task-meta { margin-top: 4px; gap: 8px; font-size: 11px; }
.v1-shell.is-compact .v1-summary-progress { margin-top: 8px; gap: 8px; }
.v1-shell.is-compact .v1-inline-action { min-width: 50px; min-height: 28px; padding: 0 9px; font-size: 11px; }
.v1-shell.is-compact .v1-task-detail { padding: 0 16px 12px; }
.v1-shell.is-compact .v1-error-box { margin-top: 12px; padding: 10px 12px; }
.v1-shell.is-compact .v1-path-grid { margin-top: 12px; gap: 10px; }
.v1-shell.is-compact .v1-path-card { padding: 10px 12px; border-radius: 12px; }
.v1-shell.is-compact .v1-path-value { margin-top: 4px; font-size: 12px; line-height: 1.4; }
.v1-shell.is-compact .v1-detail-section { margin-top: 10px; }
.v1-shell.is-compact .v1-file-row { padding: 6px 0; }
.v1-shell.is-compact .v1-file-row-top { margin-bottom: 4px; }
.v1-shell.is-compact .v1-file-row-main,
.v1-shell.is-compact .v1-file-row-side { gap: 8px; }
.v1-shell.is-compact .v1-file-row-name { font-size: 11px; }
.v1-shell.is-compact .v1-file-row-side { font-size: 10px; }
.v1-shell.is-compact .v1-file-chip { min-height: 18px; padding: 0 6px; font-size: 9px; }
.v1-shell.is-compact .v1-strip-track { height: 5px; }
.v1-shell.is-compact .v1-log-row { font-size: 11px; gap: 8px; }
.v1-shell.is-compact .v1-log-row + .v1-log-row { margin-top: 4px; }
.v1-footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 14px 36px 16px; background: rgba(255, 255, 255, 0.66); border-top: 1px solid rgba(24, 24, 27, 0.08); }
.v1-footer-metrics,.v1-footer-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.v1-footer-block { display: grid; gap: 2px; }
.v1-footer-label { color: #71717a; font-size: 9px; font-weight: 800; letter-spacing: 0.12em; }
.v1-footer-value { color: #27272a; font-size: 14px; font-weight: 800; }
.v1-footer-divider { width: 1px; height: 30px; background: rgba(24, 24, 27, 0.12); }
.v1-footer-actions { gap: 18px; }
.v1-footer-action { border: none; background: transparent; color: #71717a; font-size: 12px; font-weight: 800; letter-spacing: 0.1em; cursor: pointer; transition: color .18s ease, transform .18s ease, opacity .18s ease; }
.v1-footer-action.primary { color: #18181b; }
.v1-footer-action:hover { color: #27272a; transform: translateY(-1px); opacity: .95; }
.v1-footer-action:active { transform: translateY(0); }

@keyframes v1-refresh-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.v1-scrollbar::-webkit-scrollbar { width: 6px; }
.v1-scrollbar::-webkit-scrollbar-track { background: transparent; }
.v1-scrollbar::-webkit-scrollbar-thumb { background: #a1a1aa; border-radius: 999px; }

:global(html.kikoerumanager-dark .v1-shell) {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(18, 18, 19, 0.88);
  backdrop-filter: blur(22px) saturate(1.02);
  -webkit-backdrop-filter: blur(22px) saturate(1.02);
  box-shadow:
    0 22px 58px rgba(0, 0, 0, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  color: #e4e4e7;
}

:global(html.kikoerumanager-dark .v1-shell::before) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0) 100%);
  opacity: 0.72;
}

:global(html.kikoerumanager-dark .v1-shell::after) {
  display: none;
}

:global(html.kikoerumanager-dark .v1-header),
:global(html.kikoerumanager-dark .v1-footer) {
  background: rgba(24, 24, 27, 0.82);
  border-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark .v1-body) {
  background: rgba(10, 10, 11, 0.76);
}

:global(html.kikoerumanager-dark .v1-title),
:global(html.kikoerumanager-dark .v1-footer-value),
:global(html.kikoerumanager-dark .v1-task-name),
:global(html.kikoerumanager-dark .v1-file-row-name) {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark .v1-subtitle),
:global(html.kikoerumanager-dark .v1-task-meta),
:global(html.kikoerumanager-dark .v1-file-row-side),
:global(html.kikoerumanager-dark .v1-log-row),
:global(html.kikoerumanager-dark .v1-footer-label) {
  color: #a1a1aa;
}

:global(html.kikoerumanager-dark .v1-tab) {
  color: #a1a1aa;
}

:global(html.kikoerumanager-dark .v1-tab:hover) {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark .v1-tab.active) {
  color: #ffffff;
  border-bottom-color: #ffffff;
}

:global(html.kikoerumanager-dark .v1-tab-badge) {
  background: rgba(255, 255, 255, 0.1);
  color: #e4e4e7;
}

:global(html.kikoerumanager-dark .v1-search),
:global(html.kikoerumanager-dark .v1-icon-button),
:global(html.kikoerumanager-dark .v1-inline-action) {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(39, 39, 42, 0.78);
  color: #d4d4d8;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 4px 12px rgba(0,0,0,.18);
}

:global(html.kikoerumanager-dark .v1-search:focus-within) {
  border-color: rgba(255, 255, 255, 0.24);
  background: rgba(39, 39, 42, 0.92);
  box-shadow: none;
  transform: none;
}

:global(html.kikoerumanager-dark .v1-search input) {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark .v1-search input::placeholder) {
  color: #71717a;
}

:global(html.kikoerumanager-dark .v1-icon-button:hover),
:global(html.kikoerumanager-dark .v1-inline-action:hover) {
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(63, 63, 70, 0.9);
  color: #ffffff;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 10px 20px rgba(0,0,0,.24);
}

:global(html.kikoerumanager-dark .v1-task-card) {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(24, 24, 27, 0.86);
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.24);
}

:global(html.kikoerumanager-dark .v1-task-card.is-warning) {
  border-color: rgba(245, 158, 11, 0.3);
  background:
    linear-gradient(90deg, rgba(146, 64, 14, 0.26), rgba(24, 24, 27, 0.92) 24%),
    rgba(24, 24, 27, 0.94);
}

:global(html.kikoerumanager-dark .v1-task-card.is-danger) {
  border-color: rgba(248, 113, 113, 0.28);
  background:
    linear-gradient(90deg, rgba(127, 29, 29, 0.3), rgba(24, 24, 27, 0.92) 24%),
    rgba(24, 24, 27, 0.94);
}

:global(html.kikoerumanager-dark .v1-task-card::before) {
  display: none;
}

:global(html.kikoerumanager-dark .v1-task-card:hover),
:global(html.kikoerumanager-dark .v1-task-card.expanded) {
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(32, 32, 35, 0.96);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
}

:global(html.kikoerumanager-dark .v1-task-card.is-warning:hover),
:global(html.kikoerumanager-dark .v1-task-card.is-warning.expanded) {
  border-color: rgba(245, 158, 11, 0.38);
  background:
    linear-gradient(90deg, rgba(146, 64, 14, 0.34), rgba(32, 32, 35, 0.96) 24%),
    rgba(32, 32, 35, 0.96);
}

:global(html.kikoerumanager-dark .v1-task-card.is-danger:hover),
:global(html.kikoerumanager-dark .v1-task-card.is-danger.expanded) {
  border-color: rgba(248, 113, 113, 0.38);
  background:
    linear-gradient(90deg, rgba(127, 29, 29, 0.38), rgba(32, 32, 35, 0.96) 24%),
    rgba(32, 32, 35, 0.96);
}

:global(html.kikoerumanager-dark .v1-inline-action.primary),
:global(html.kikoerumanager-dark .v1-task-rj),
:global(html.kikoerumanager-dark .v1-status-line.processing),
:global(html.kikoerumanager-dark .v1-speed-line),
:global(html.kikoerumanager-dark .v1-summary-progress-text),
:global(html.kikoerumanager-dark .v1-footer-action.primary) {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark .v1-inline-action.primary) {
  background: rgba(63, 63, 70, 0.78);
}

:global(html.kikoerumanager-dark .v1-task-icon.warning),
:global(html.kikoerumanager-dark .v1-status-line.warning) {
  color: #fbbf24;
}

:global(html.kikoerumanager-dark .v1-task-icon.danger) {
  color: #f87171;
}

:global(html.kikoerumanager-dark .v1-inline-action.danger),
:global(html.kikoerumanager-dark .v1-status-line.danger),
:global(html.kikoerumanager-dark .v1-file-retry),
:global(html.kikoerumanager-dark .v1-file-reason) {
  color: #f87171;
}

:global(html.kikoerumanager-dark .v1-inline-action.danger) {
  border-color: rgba(248, 113, 113, 0.22);
  background: rgba(127, 29, 29, 0.18);
}

:global(html.kikoerumanager-dark .v1-inline-action.danger:hover) {
  border-color: rgba(248, 113, 113, 0.34);
  background: rgba(127, 29, 29, 0.28);
  color: #fca5a5;
}

:global(html.kikoerumanager-dark .v1-inline-action.retry) {
  border-color: rgba(248, 113, 113, 0.58);
  background: linear-gradient(180deg, rgba(153, 27, 27, 0.92), rgba(127, 29, 29, 0.78));
  color: #fee2e2;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12), 0 8px 18px rgba(127, 29, 29, 0.28);
}

:global(html.kikoerumanager-dark .v1-inline-action.retry:hover:not(:disabled)) {
  border-color: rgba(252, 165, 165, 0.72);
  background: linear-gradient(180deg, rgba(185, 28, 28, 0.96), rgba(153, 27, 27, 0.88));
  color: #ffffff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 12px 24px rgba(127, 29, 29, 0.34);
}

:global(html.kikoerumanager-dark .v1-inline-action.retry:disabled) {
  opacity: 0.72;
  color: #fecaca;
}

:global(html.kikoerumanager-dark .v1-file-retry) {
  border-color: rgba(248, 113, 113, 0.58);
  background: linear-gradient(180deg, rgba(153, 27, 27, 0.9), rgba(127, 29, 29, 0.76));
  color: #fee2e2;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12), 0 6px 14px rgba(127, 29, 29, 0.24);
}

:global(html.kikoerumanager-dark .v1-file-retry:hover:not(:disabled)) {
  border-color: rgba(252, 165, 165, 0.72);
  background: linear-gradient(180deg, rgba(185, 28, 28, 0.96), rgba(153, 27, 27, 0.86));
  color: #ffffff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 10px 20px rgba(127, 29, 29, 0.32);
}

:global(html.kikoerumanager-dark .v1-file-retry:disabled) {
  opacity: 0.66;
  color: #fecaca;
}

:global(html.kikoerumanager-dark .v1-task-detail) {
  background: rgba(18, 18, 19, 0.92);
  border-top-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark .v1-task-detail::before) {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

:global(html.kikoerumanager-dark .v1-path-card) {
  border-color: rgba(255, 255, 255, 0.08);
  background: rgba(39, 39, 42, 0.72);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .v1-path-label),
:global(html.kikoerumanager-dark .v1-detail-section-label),
:global(html.kikoerumanager-dark .v1-log-time) {
  color: #71717a;
}

:global(html.kikoerumanager-dark .v1-detail-section-count) {
  background: rgba(39, 39, 42, 0.82);
  border-color: rgba(255, 255, 255, 0.1);
  color: #d4d4d8;
}

:global(html.kikoerumanager-dark .v1-path-value),
:global(html.kikoerumanager-dark .v1-footer-action) {
  color: #d4d4d8;
}

:global(html.kikoerumanager-dark .v1-file-row + .v1-file-row) {
  border-top-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark .v1-file-row) {
  background: transparent;
}

:global(html.kikoerumanager-dark .v1-strip-track) {
  background: rgba(255, 255, 255, 0.1);
}

:global(html.kikoerumanager-dark .v1-strip-fill.processing),
:global(html.kikoerumanager-dark .v1-strip-fill.neutral) {
  background: linear-gradient(90deg, #ffffff 0%, #dbeafe 100%);
}

:global(html.kikoerumanager-dark .v1-strip-fill.upload) {
  background: linear-gradient(90deg, #ffffff 0%, #e0e7ff 100%);
}

:global(html.kikoerumanager-dark .v1-strip-fill.upload-success),
:global(html.kikoerumanager-dark .v1-strip-fill.success) {
  background: linear-gradient(90deg, #ffffff 0%, #dcfce7 100%);
}

:global(html.kikoerumanager-dark .v1-strip-fill.danger) {
  background: #f87171;
}

:global(html.kikoerumanager-dark .v1-footer-divider) {
  background: rgba(255, 255, 255, 0.1);
}

:global(html.kikoerumanager-dark .v1-footer-action:hover) {
  color: #ffffff;
  text-shadow: none;
}

:global(html.kikoerumanager-dark .v1-file-chip.success) {
  background: rgba(255, 255, 255, 0.1);
  color: #d4d4d8;
}

:global(html.kikoerumanager-dark .v1-file-chip.danger),
:global(html.kikoerumanager-dark .v1-error-box) {
  background: rgba(248, 113, 113, 0.12);
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.26);
}

:global(html.kikoerumanager-dark .v1-scrollbar::-webkit-scrollbar-thumb) {
  background: #52525b;
}

@media (max-width: 900px) {
  .v1-header,.v1-task-head,.v1-footer { flex-direction: column; }
  .v1-header-tools,.v1-task-actions,.v1-footer-actions { width: 100%; justify-content: flex-start; }
  .v1-search { width: 100%; }
  .v1-path-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .v1-header,.v1-body,.v1-footer { padding-left: 18px; padding-right: 18px; }
  .v1-shell { border-radius: 28px; }
  .v1-task-summary { padding: 18px; }
  .v1-task-detail { padding-left: 18px; padding-right: 18px; }
  .v1-log-row { grid-template-columns: 1fr; gap: 2px; }
}
</style>
