<template>
  <!--
    社团补全下载工作台新视觉原型。
    当前只作为独立 V1 原型文件存在，不接入、不替换正式组件。
    数据契约与旧组件保持兼容，便于后续在 CircleCompletion 中切换验收。
  -->
  <Teleport to="body">
    <transition name="el-fade-in">
      <div v-if="visible" class="v1-overlay">
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
              :class="{ expanded: expandedTaskIds.has(task.id) }"
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
                      <h3 class="v1-task-name">{{ task.work_title || task.source_label || '未命名任务' }}</h3>
                      <div class="v1-task-rj">{{ getTaskSecondaryLabel(task) }}</div>
                    </div>

                    <div class="v1-task-actions" @click.stop>
                      <template v-if="isTaskProcessing(task)">
                        <button type="button" class="v1-inline-action" @click="emit('pause-task', task)" title="暂停">
                          <Pause :size="13" />
                          暂停
                        </button>
                        <button type="button" class="v1-inline-action danger" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="isTaskPaused(task)">
                        <button type="button" class="v1-inline-action primary" @click="emit('resume-task', task)" title="恢复">
                          <Play :size="13" />
                          恢复
                        </button>
                        <button type="button" class="v1-inline-action danger" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="['pending', 'waiting_retry'].includes(String(task?.status || ''))">
                        <button type="button" class="v1-inline-action danger" @click="emit('cancel-task', task)" title="取消">
                          <XCircle :size="13" />
                          取消
                        </button>
                      </template>
                      <template v-else-if="canRetryDownloadTask(task)">
                        <button
                          type="button"
                          class="v1-inline-action danger"
                          :disabled="retryingSet.has(task.id)"
                          @click.stop="emit('retry-task', task)"
                        >
                          {{ retryingSet.has(task.id) ? '重试中' : '重试失败项' }}
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
                          <div class="v1-path-value">{{ getFinalOutputPath(task) }}</div>
                        </div>
                      </div>

                      <div v-if="getUnifiedFileRows(task).length" class="v1-detail-section">
                        <div class="v1-file-list">
                          <div
                            v-for="file in getUnifiedFileRows(task)"
                            :key="`${task.id}-${file.relative_path || file.name}-detail`"
                            class="v1-file-row"
                          >
                            <div class="v1-file-row-top">
                              <div class="v1-file-row-main">
                                <span class="v1-file-row-name">{{ file.name }}</span>
                                <span v-if="file.tone === 'success'" class="v1-file-chip success">{{ file.statusText }}</span>
                                <span v-else-if="file.tone === 'danger'" class="v1-file-chip danger">{{ file.statusText }}</span>
                              </div>
                              <div class="v1-file-row-side">
                                <span>{{ file.progress }}% • {{ file.sizeText }}</span>
                                <span v-if="showDownloadMetrics && file.downloadSpeedVisible">下载 {{ formatSpeed(file.downloadSpeed) }}</span>
                                <span v-if="file.uploadSpeedVisible">上传 {{ formatSpeed(file.uploadSpeed) }}</span>
                                <button
                                  v-if="file.retryable"
                                  type="button"
                                  class="v1-file-retry"
                                  :disabled="retryingSet.has(`${task.id}:${file.relative_path || file.name}`)"
                                  @click.stop="emit('retry-file', { task, file })"
                                >
                                  {{ retryingSet.has(`${task.id}:${file.relative_path || file.name}`) ? '重试中' : '重试' }}
                                </button>
                              </div>
                            </div>
                            <div class="v1-strip-track">
                              <div class="v1-strip-fill" :class="fileToneClass(file)" :style="{ width: `${file.progress}%` }"></div>
                            </div>
                            <div v-if="file.reason" class="v1-file-reason">{{ file.reason }}</div>
                          </div>
                        </div>
                      </div>

                      <div v-if="task.progress_log?.length" class="v1-detail-section">
                        <div class="v1-detail-section-label">最近日志</div>
                        <div class="v1-log-list">
                          <div
                            v-for="entry in task.progress_log.slice(-6)"
                            :key="`${task.id}-${entry.time}-${entry.message}`"
                            class="v1-log-row"
                          >
                            <span class="v1-log-time">{{ formatLogTime(entry.time) }}</span>
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
              <div class="v1-footer-block">
                <span class="v1-footer-label">上传速度</span>
                <span class="v1-footer-value">{{ totalUploadSpeed }}</span>
              </div>
              <div class="v1-footer-divider"></div>
              <div class="v1-footer-block">
                <span class="v1-footer-label">剩余大小</span>
                <span class="v1-footer-value">{{ remainingTransferSize }}</span>
              </div>
              <div class="v1-footer-divider"></div>
              <div class="v1-footer-block">
                <span class="v1-footer-label">预计时间</span>
                <span class="v1-footer-value">{{ aggregatedUploadEta }}</span>
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
import { Archive, AlertCircle, ArrowUpToLine, CheckCircle2, Clock3, Download, HardDriveUpload, Minimize2, Pause, Play, RefreshCw, Search, TriangleAlert, X, XCircle, Zap } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
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
  title: { type: String, default: 'Download Manager' },
  subtitle: { type: String, default: '社团补全下载任务' },
  emptyTitle: { type: String, default: '暂无符合筛选的下载任务' },
  sourcePathLabel: { type: String, default: '下载目录' },
  showDownloadMetrics: { type: Boolean, default: true },
  showUploadEta: { type: Boolean, default: false },
  preferUploadIcon: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
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
])

const activeFilter = ref('all')
const searchQuery = ref('')
const expandedTaskIds = ref(new Set())
const localSpinning = ref(false)

function handleRefresh() {
  emit('refresh')
  localSpinning.value = true
  setTimeout(() => { localSpinning.value = false }, 900)
}

const retryingSet = computed(() => new Set((props.retryingKeys || []).map(item => String(item || ''))))
const mergedTasks = computed(() => buildMergedTasks(props.tasks || []))
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

const pausedTasks = computed(() => mergedTasks.value.filter(task => isTaskPaused(task)))
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
const totalRemainingUploadBytes = computed(() => {
  return processingTasks.value.reduce((sum, task) => {
    return sum + getTaskRemainingBytes(task)
  }, 0)
})
const remainingTransferSize = computed(() => formatSize(totalRemainingUploadBytes.value))
const aggregatedUploadEta = computed(() => {
  const speed = processingTasks.value.reduce((sum, task) => sum + getVisibleUploadSpeed(task), 0)
  const remainingBytes = totalRemainingUploadBytes.value
  if (speed > 0 && remainingBytes > 0) return formatEtaSeconds(Math.ceil(remainingBytes / speed))
  if (remainingBytes <= 0 && processingTasks.value.some(task => isUploadEnabled(task))) return '已接近完成'
  return '—'
})
const remainingTaskSummary = computed(() => {
  const remaining = processingTasks.value.length + pendingTasks.value.length
  return remaining ? `${remaining} 个` : '已全部完成'
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

function getTaskSecondaryLabel(task) {
  return String(task?.task_metadata?.workbench_subtitle || task?.rjcode || task?.task_metadata?.rjcode || '').trim() || '未知 RJ'
}

function getTaskSourceAction(task) {
  return String(task?.task_metadata?.source_action || task?.source_action || '').trim()
}

function getTaskLocalDownloadRoot(task) {
  return String(task?.task_metadata?.local_download_root || task?.session_state?.local_download_root || task?.task_metadata?.download_root || '').trim()
}

function getTaskMergeKey(task) {
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

function isUploadEnabled(task) {
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
  if (isTaskPaused(task)) return 0
  const runtime = getUploadRuntime(task)
  const runtimeSpeed = Number(runtime?.speed_bytes_per_sec || 0)
  const hasActiveUploadHint = hasActiveUploadRuntime(task) || Boolean(String(runtime?.current_relative_path || '').trim())
  return isTaskProcessing(task) && hasActiveUploadHint && runtimeSpeed > 0 ? runtimeSpeed : 0
}

function getUploadEtaSeconds(task) {
  const runtime = getUploadRuntime(task)
  const runtimeEta = Number(runtime?.eta_seconds || 0)
  if (runtimeEta > 0) return runtimeEta
  const speed = getVisibleUploadSpeed(task)
  const remainingBytes = getUploadRemainingBytes(task)
  if (speed > 0 && remainingBytes > 0) return Math.ceil(remainingBytes / speed)
  return 0
}

function getTaskRemainingBytes(task) {
  const transferTotal = getTaskTransferBytes(task)
  const downloadRemaining = Math.max(0, transferTotal - getTaskDownloadedBytes(task))
  if (!isUploadEnabled(task)) return downloadRemaining
  const uploadRemaining = Math.max(0, getUploadTotalBytes(task) - getTaskUploadedBytes(task))
  return downloadRemaining + uploadRemaining
}

function getUploadRemainingBytes(task) {
  return Math.max(0, getUploadTotalBytes(task) - getTaskUploadedBytes(task))
}

function getUploadTotalBytes(task) {
  const runtimeBytes = Number(getUploadRuntime(task)?.total_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const totalBytes = uploadFiles.reduce((sum, item) => sum + Number(item?.size_bytes || item?.total || 0), 0)
  if (totalBytes > 0) return totalBytes
  return getTaskTransferBytes(task)
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
  if (currentStep.startsWith('已由后续成功任务覆盖')) return '已由其他任务完成，此条任务已合并'

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
  if (status === 'pending') return '等待开始'
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
  const rows = getUnifiedFileRows(task)
  if (rows.length) {
    const progress = rows.reduce((sum, item) => sum + Number(item.progress || 0), 0) / rows.length
    return Math.max(0, Math.min(99, Math.floor(progress)))
  }
  const downloadedBytes = Math.max(0, getTaskDownloadedBytes(task))
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
  if (getTaskTone(task) === 'success' && isUploadEnabled(task)) return `已上传 ${getUploadCompletedCount(task)} / ${total}`
  if (stage === '上传 / 入库中' || stage === '上传准备中') return `上传 ${getUploadCompletedCount(task)} / ${total}`
  if (getDownloadCompletedCount(task) >= 0 && getDownloadCompletedCount(task) < total) return `下载 ${getDownloadCompletedCount(task)} / ${total}`
  if (getTaskTone(task) === 'warning') return `成功 ${Math.max(0, total - getFailureCount(task))} / ${total}`
  return `文件 ${getDownloadCompletedCount(task)} / ${total}`
}

function getPrimarySizeText(task) {
  const total = formatSize(getTaskTransferBytes(task))
  const tone = getTaskTone(task)
  const stage = getTaskStageLabel(task)
  const downloadSpeedVisible = getVisibleDownloadSpeed(task) > 0
  const uploadSpeedVisible = getVisibleUploadSpeed(task) > 0
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
      key: rowKey,
      name: payload.name || payload.file_name || payload.relative_path || '未知文件',
      relative_path: payload.relative_path || '',
      total: Number(payload.size_bytes || 0),
      downloadedBytes: 0,
      uploadedBytes: 0,
      sourceTaskStatus: '',
      progress: 0,
      tone: 'neutral',
      reason: '',
      retryable: false,
      statusText: '等待中',
      stageLabel: '等待中',
      sizeText: payload.size_bytes ? `下载大小 ${formatSize(payload.size_bytes)}` : '下载大小 0 B',
      downloadSpeed: 0,
      uploadSpeed: 0,
      downloadSpeedVisible: false,
      uploadSpeedVisible: false,
      index: Number(payload.index || 0),
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
    row.reason = String(file.reason || file.exception_type || '失败').trim()
    row.retryable = Boolean(row.relative_path)
    row.tone = 'danger'
    const failedStage = String(file.stage || '').trim()
    row.stageLabel = failedStage === 'upload' ? '上传失败' : '下载失败'
    row.statusText = row.stageLabel
    row.sizeText = failedStage === 'upload' ? `上传 ${formatSize(file.uploaded || 0)} / ${formatSize(row.total)}` : `下载 ${formatSize(file.downloaded || 0)} / ${formatSize(row.total)}`
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
}

.v1-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1320px;
  height: min(90vh, 920px);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.42);
  border-radius: 38px;
  background: rgba(255, 255, 255, 0.15);
  box-shadow:
    0 30px 80px rgba(15, 23, 42, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(16px) saturate(200%);
  -webkit-backdrop-filter: blur(16px) saturate(200%);
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
  height: 128px;
  border-radius: 37px 37px 24px 24px;
  background: linear-gradient(180deg, rgba(255,255,255,0.36) 0%, rgba(255,255,255,0.1) 58%, rgba(255,255,255,0) 100%);
  opacity: 0.95;
}

.v1-shell::after {
  border-radius: inherit;
  background:
    linear-gradient(115deg, rgba(191, 219, 254, 0.16) 0%, transparent 22%),
    linear-gradient(245deg, rgba(186, 230, 253, 0.12) 0%, transparent 18%),
    linear-gradient(180deg, rgba(255,255,255,0.08) 0%, transparent 28%, transparent 72%, rgba(148, 163, 184, 0.08) 100%);
  mix-blend-mode: screen;
}

.v1-header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  padding: 32px 40px 20px;
  background: rgba(255, 255, 255, 0.12);
  border-bottom: 1px solid rgba(217, 228, 236, 0.7);
}

.v1-header-copy { display: flex; flex-direction: column; justify-content: center; min-height: 88px; }
.v1-title { color: #111827; font-size: 24px; font-weight: 800; letter-spacing: -0.03em; line-height: 1; }
.v1-subtitle { margin-top: 6px; color: #60707a; font-size: 12px; font-weight: 600; letter-spacing: 0.02em; }
.v1-tabs { display: flex; gap: 24px; margin-top: 20px; flex-wrap: wrap; align-items: center; }
.v1-tab { display: inline-flex; align-items: center; gap: 8px; padding: 0 0 10px; border: none; border-bottom: 3px solid transparent; background: transparent; color: #5d7184; font-size: 15px; font-weight: 600; cursor: pointer; transition: color .18s ease, transform .18s ease, border-color .18s ease; }
.v1-tab.active { color: #2563eb; border-bottom-color: #2563eb; }
.v1-tab:hover { color: #334155; transform: translateY(-1px); }
.v1-tab-badge { min-width: 24px; padding: 0 8px; border-radius: 999px; background: #d9e4ec; color: #58708a; font-size: 11px; line-height: 22px; text-align: center; }
.v1-header-tools { display: flex; align-items: center; gap: 12px; min-height: 88px; }
.v1-search { display: inline-flex; align-items: center; gap: 10px; width: 274px; height: 44px; padding: 0 16px; border-radius: 999px; background: rgba(255, 255, 255, 0.3); color: #7b8793; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.045), inset 0 1px 0 rgba(255,255,255,.3); backdrop-filter: blur(16px) saturate(140%); transition: box-shadow .18s ease, transform .18s ease, background-color .18s ease, border-color .18s ease; border: 1px solid rgba(255,255,255,.18); }
.v1-search:focus-within { background: rgba(255,255,255,.5); box-shadow: 0 0 0 3px rgba(59,130,246,.12), 0 2px 8px rgba(15, 23, 42, 0.045), inset 0 1px 0 rgba(255,255,255,.35); transform: translateY(-1px); border-color: rgba(96,165,250,.4); }
.v1-search input { width: 100%; border: none; background: transparent; color: #334155; font-size: 14px; outline: none; }
.v1-icon-button { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border: none; border-radius: 999px; background: rgba(255,255,255,.16); color: #475569; cursor: pointer; transition: background-color .18s ease, transform .18s ease, color .18s ease, box-shadow .18s ease; box-shadow: inset 0 1px 0 rgba(255,255,255,.24); }
.v1-icon-button:hover { background: rgba(255,255,255,.34); color: #1f2937; transform: translateY(-1px) scale(1.03); box-shadow: 0 8px 18px rgba(148, 163, 184, 0.14), inset 0 1px 0 rgba(255,255,255,.28); }
.v1-icon-button:active { transform: translateY(0) scale(0.98); }
.v1-icon-button.spinning svg { animation: v1-refresh-spin .9s linear infinite; }
.v1-body { flex: 1; overflow-y: auto; padding: 18px 40px 14px; background: rgba(231, 239, 245, 0.32); }
.v1-task-card { position: relative; margin-bottom: 20px; border: 1px solid rgba(255, 255, 255, 0.36); border-radius: 32px; background: linear-gradient(180deg, rgba(255,255,255,.34), rgba(255,255,255,.16)); box-shadow: 0 10px 24px rgba(15, 23, 42, 0.045), inset 0 1px 0 rgba(255,255,255,.4), inset 0 0 0 1px rgba(255,255,255,.05); overflow: hidden; cursor: pointer; transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease, background-color .22s ease; }
.v1-task-card::before {
  content: "";
  position: absolute;
  inset: 1px 1px auto 1px;
  height: 64px;
  border-radius: 31px 31px 16px 16px;
  background: linear-gradient(180deg, rgba(255,255,255,.24) 0%, rgba(255,255,255,.06) 100%);
  pointer-events: none;
}
.v1-task-card:hover { transform: translateY(-2px); box-shadow: 0 16px 28px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255,255,255,.38), inset 0 0 0 1px rgba(255,255,255,.06); border-color: rgba(255,255,255,.46); background: linear-gradient(180deg, rgba(255,255,255,.38), rgba(255,255,255,.16)); }
.v1-task-card.expanded { box-shadow: 0 18px 34px rgba(15, 23, 42, 0.1), inset 0 1px 0 rgba(255,255,255,.4), inset 0 0 0 1px rgba(255,255,255,.08); }
.v1-task-summary { display: flex; align-items: center; gap: 16px; padding: 18px 22px; min-height: 92px; }
.v1-task-icon { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 88px; height: 88px; flex-shrink: 0; overflow: visible; }
.v1-task-icon-fallback { position: absolute; z-index: 1; opacity: 0.92; }
.v1-task-icon-lottie { width: 72px; height: 72px; pointer-events: none; filter: drop-shadow(0 10px 24px rgba(59,130,246,.12)); background: transparent; }
.v1-task-icon-lottie { position: relative; z-index: 2; }
.v1-task-icon-lottie :deep(canvas) { background: transparent !important; background-color: transparent !important; }
/* 上传动画画布 4:3(1024×768)；用 aspect-ratio 让容器跟随比例，消除上下空白 */
.v1-task-icon-lottie.is-upload-anim { height: auto; aspect-ratio: 4 / 3; }
.v1-task-icon-lottie.paused { opacity: 0.52; filter: grayscale(0.25) saturate(0.7) drop-shadow(0 10px 24px rgba(59,130,246,.08)); }
.v1-task-icon.processing { color: #123f67; }
.v1-task-icon.pending { color: #566167; }
.v1-task-icon.success { color: #415866; }
.v1-task-icon.warning { color: #9a5b00; }
.v1-task-icon.danger { color: #b91c1c; }
.v1-task-main { flex: 1; min-width: 0; }
.v1-task-head { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.v1-task-name-wrap { min-width: 0; flex: 1; }
.v1-task-name { margin: 0; color: #1f2937; font-size: 14px; font-weight: 800; line-height: 1.18; letter-spacing: -0.02em; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.v1-task-rj { margin-top: 5px; color: #2563eb; font-size: 12px; font-weight: 700; line-height: 1; }
.v1-task-actions { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; padding-left: 12px; }
.v1-inline-action { border: 1px solid rgba(255,255,255,.24); background: rgba(255,255,255,.22); color: #475569; font-size: 12px; font-weight: 700; cursor: pointer; transition: color .18s ease, transform .18s ease, opacity .18s ease, box-shadow .18s ease, background-color .18s ease; min-height: 30px; padding: 0 12px; border-radius: 999px; box-shadow: 0 2px 8px rgba(15,23,42,.04), inset 0 1px 0 rgba(255,255,255,.3); backdrop-filter: blur(12px) saturate(140%); }
.v1-inline-action.primary { color: #2563eb; }
.v1-inline-action.danger { color: #dc2626; }
.v1-inline-action:hover { transform: translateY(-1px); opacity: .95; background: rgba(255,255,255,.38); box-shadow: 0 8px 16px rgba(148, 163, 184, 0.12), inset 0 1px 0 rgba(255,255,255,.34); }
.v1-inline-action:active { transform: translateY(0); }
.v1-task-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 8px; color: #556474; font-size: 12px; line-height: 1.1; }
.v1-summary-progress { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.v1-summary-progress :deep(.app-lottie-progress) { flex: 1; }
.v1-summary-progress-text { color: #456074; font-size: 12px; font-weight: 800; min-width: 36px; text-align: right; font-variant-numeric: tabular-nums; }
.v1-status-line,.v1-speed-line,.v1-eta-line { display: inline-flex; align-items: center; gap: 5px; }
.v1-status-line.processing,.v1-speed-line { color: #2563eb; }
.v1-speed-line.upload { color: #4f8f96; }
.v1-eta-line { color: #667788; }
.v1-status-line.pending { color: #7c8b96; }
.v1-status-line.success { color: #3e5560; }
.v1-status-line.upload-success { color: #4f8f96; }
.v1-status-line.warning { color: #9a5b00; }
.v1-status-line.danger { color: #b91c1c; }
.v1-status-icon { flex-shrink: 0; opacity: .92; }
.v1-expanded-strip { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(225, 233, 240, 0.9); }
.v1-strip-row + .v1-strip-row { margin-top: 12px; }
.v1-strip-top { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; margin-bottom: 6px; color: #475569; font-size: 12px; align-items: end; }
.v1-strip-name.waiting { font-style: italic; color: #7b8793; }
.v1-strip-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.v1-strip-size { white-space: nowrap; color: #64748b; font-variant-numeric: tabular-nums; }
.v1-strip-track { width: 100%; height: 6px; overflow: hidden; border-radius: 999px; background: #d8e2ea; }
.v1-strip-fill { height: 100%; border-radius: 999px; background: #346290; transition: width 0.8s cubic-bezier(0.22, 1, 0.36, 1), background 0.4s ease; }
.v1-strip-fill.processing,.v1-strip-fill.neutral { background: linear-gradient(90deg, #2f5f92 0%, #3f729f 100%); }
.v1-strip-fill.upload { background: linear-gradient(90deg, #4f8f96 0%, #6aaeb5 100%); }
.v1-strip-fill.upload-success { background: linear-gradient(90deg, #4b8d95 0%, #79bcc2 100%); }
.v1-strip-fill.success { background: linear-gradient(90deg, #415866 0%, #5e7480 100%); }
.v1-strip-fill.danger { background: #dc2626; }
.v1-task-detail { position: relative; padding: 0 22px 18px; background: linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,.08)); border-top: 1px solid rgba(225, 233, 240, 0.55); box-shadow: inset 0 1px 0 rgba(255,255,255,.18); }
.v1-task-detail::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 0 0 32px 32px;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.16);
}
.v1-error-box { display: flex; gap: 10px; margin-top: 18px; padding: 14px 16px; border-radius: 16px; background: rgba(254, 226, 226, 0.45); color: #b91c1c; border: 1px solid rgba(255,255,255,.28); box-shadow: inset 0 1px 0 rgba(255,255,255,.24); }
.v1-error-title { font-size: 12px; font-weight: 800; }
.v1-error-text { margin-top: 4px; font-size: 12px; line-height: 1.55; word-break: break-word; }
.v1-path-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 18px; }
.v1-path-card { padding: 14px 16px; border-radius: 16px; background: linear-gradient(180deg, rgba(255,255,255,.28), rgba(255,255,255,.12)); border: 1px solid rgba(255, 255, 255, 0.3); box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04), inset 0 1px 0 rgba(255,255,255,.32), inset 0 0 0 1px rgba(255,255,255,.04); }
.v1-path-label,.v1-detail-section-label { color: #76838f; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
.v1-path-value { margin-top: 8px; color: #334155; font-size: 13px; line-height: 1.55; word-break: break-all; }
.v1-detail-section { margin-top: 16px; }
.v1-file-list,.v1-log-list { margin-top: 8px; }
.v1-file-row { padding: 9px 0; }
.v1-file-row + .v1-file-row { border-top: 1px solid rgba(225, 233, 240, 0.8); }
.v1-file-row-top { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; align-items: flex-end; }
.v1-file-row-main,.v1-file-row-side { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.v1-file-row-main { min-width: 0; flex: 1; }
.v1-file-row-name { color: #1f2937; font-size: 12px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.v1-file-row-side { color: #556474; font-size: 11px; justify-content: flex-end; white-space: nowrap; font-variant-numeric: tabular-nums; }
.v1-file-chip { display: inline-flex; align-items: center; min-height: 22px; padding: 0 9px; border-radius: 999px; font-size: 10px; font-weight: 800; }
.v1-file-chip.success { background: #dcecf5; color: #3e5560; }
.v1-file-chip.danger { background: #fee2e2; color: #b91c1c; }
.v1-file-retry { border: none; background: transparent; color: #dc2626; font-size: 12px; font-weight: 700; cursor: pointer; }
.v1-file-reason { margin-top: 8px; color: #b91c1c; font-size: 12px; line-height: 1.5; }
.v1-log-row { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 10px; color: #556474; font-size: 12px; line-height: 1.5; }
.v1-log-row + .v1-log-row { margin-top: 6px; }
.v1-log-time { color: #94a3b8; }
.v1-log-message { word-break: break-word; }

.v1-shell.is-compact .v1-body { padding-top: 12px; padding-bottom: 10px; }
.v1-shell.is-compact .v1-task-card { margin-bottom: 12px; border-radius: 24px; }
.v1-shell.is-compact .v1-task-card::before { height: 46px; border-radius: 23px 23px 12px 12px; }
.v1-shell.is-compact .v1-task-summary { gap: 12px; padding: 12px 16px; min-height: 72px; }
.v1-shell.is-compact .v1-task-icon { width: 60px; height: 60px; }
.v1-shell.is-compact .v1-task-icon-fallback { font-size: 18px; }
.v1-shell.is-compact .v1-task-icon-lottie { width: 48px; height: 48px; filter: drop-shadow(0 6px 14px rgba(59,130,246,.1)); }
.v1-shell.is-compact .v1-task-icon-lottie.is-upload-anim { height: auto; aspect-ratio: 4 / 3; }
.v1-shell.is-compact .v1-task-name { font-size: 13px; line-height: 1.15; }
.v1-shell.is-compact .v1-task-rj { margin-top: 2px; font-size: 11px; }
.v1-shell.is-compact .v1-task-meta { margin-top: 4px; gap: 8px; font-size: 11px; }
.v1-shell.is-compact .v1-summary-progress { margin-top: 8px; gap: 8px; }
.v1-shell.is-compact .v1-inline-action { min-height: 26px; padding: 0 10px; font-size: 11px; }
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
.v1-empty-state { display: grid; justify-items: center; gap: 8px; padding: 110px 24px; color: #71808d; }
.v1-empty-title { color: #334155; font-size: 18px; font-weight: 800; }
.v1-empty-text { font-size: 13px; }
.v1-footer { display: flex; justify-content: space-between; align-items: flex-end; gap: 18px; padding: 22px 40px 28px; background: rgba(255, 255, 255, 0.12); border-top: 1px solid rgba(217, 228, 236, 0.42); }
.v1-footer-metrics,.v1-footer-actions { display: flex; align-items: flex-end; gap: 18px; flex-wrap: wrap; }
.v1-footer-block { display: grid; gap: 4px; }
.v1-footer-label { color: #64748b; font-size: 10px; font-weight: 800; letter-spacing: 0.18em; }
.v1-footer-value { color: #111827; font-size: 16px; font-weight: 800; }
.v1-footer-divider { width: 1px; height: 44px; background: rgba(169, 179, 187, 0.32); }
.v1-footer-actions { gap: 28px; }
.v1-footer-action { border: none; background: transparent; color: #64748b; font-size: 13px; font-weight: 800; letter-spacing: 0.16em; cursor: pointer; transition: color .18s ease, transform .18s ease, opacity .18s ease, text-shadow .18s ease; }
.v1-footer-action.primary { color: #2563eb; }
.v1-footer-action:hover { color: #1d4ed8; transform: translateY(-1px); opacity: .95; text-shadow: 0 0 18px rgba(37,99,235,.16); }
.v1-footer-action:active { transform: translateY(0); }

@keyframes v1-refresh-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.v1-scrollbar::-webkit-scrollbar { width: 6px; }
.v1-scrollbar::-webkit-scrollbar-track { background: transparent; }
.v1-scrollbar::-webkit-scrollbar-thumb { background: #b4c1cb; border-radius: 999px; }
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
