<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden text-neutral-900">
    <!-- 顶部一体化卡片：标题 + 概览 + 筛选 -->
    <div class="flex flex-shrink-0 flex-col rounded-[14px] border border-slate-200/80 bg-white shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] overflow-hidden">
      <TasksHeader />
      <TasksMetricsBar :metrics="metricsPanel" />
      <TasksFilters
        :domain-options="domainOptions"
        :status-options="statusOptions"
        :current-domain="currentDomain"
        :current-status="currentStatus"
        :search-query="searchQuery"
        :sort-key="sortKey"
        :active-only="activeOnly"
        :get-domain-count="getDomainCount"
        @update:current-domain="(v) => (currentDomain = v)"
        @update:current-status="(v) => (currentStatus = v)"
        @update:search-query="(v) => (searchQuery = v)"
        @update:sort-key="(v) => (sortKey = v)"
        @update:active-only="(v) => (activeOnly = v)"
        @reset="resetFilters"
      />
    </div>

    <section class="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden pt-2 lg:grid-cols-[minmax(280px,0.75fr)_minmax(0,1.5fr)]">
      <TaskListPane
        :filtered-items="filteredItems"
        :total-items="totalItems"
        :current-offset="currentOffset"
        :page-size="pageSize"
        :selected-id="selectedItem?.id || ''"
        :digest="listDigest"
        :format-r-j-code="formatRJCode"
        :show-progress="showProgress"
        :should-show-step="shouldShowTaskMetaStep"
        :get-recovered-notice="getRecoveredNotice"
        :get-task-summary="getTaskSummary"
        @select="(id) => (selectedItemId = id)"
        @quick-filter="applyQuickFilter"
        @prev-page="handlePrevPage"
        @next-page="handleNextPage"
      />

      <TaskDetailPane
        :item="selectedItem"
        :detail-loading="detailLoading"
        :file-tree-sections="selectedItemFileTreeSections"
        :circle-meta="getCircleIndexMetaEntries(selectedItem)"
        :circle-log="getCircleIndexProgressLog(selectedItem)"
        :tree-filter-mode="treeFilterMode"
        :format-r-j-code="formatRJCode"
        :format-date-time="formatDateTime"
        :show-progress="showProgress"
        :get-recovered-notice="getRecoveredNotice"
        :get-d-lsite-failure-reason="getDLsiteFailureReason"
        :get-output-path="getOutputPath"
        @open-route="openTaskRoute"
        @action="handleTaskAction"
        @update:tree-filter-mode="(v) => (treeFilterMode = v)"
        @expand-section="setTreeSectionExpanded"
        @toggle-node="toggleTreeNode"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Activity,
  Captions,
  Database,
  FileArchive,
  ListChecks,
  PauseCircle,
  RotateCcw,
  Sparkles,
  Upload,
  UploadCloud,
  XCircle,
} from 'lucide-vue-next'
import { taskCenterApi } from '../api'
import TasksHeader from '../components/tasks/TasksHeader.vue'
import TasksMetricsBar from '../components/tasks/TasksMetricsBar.vue'
import TasksFilters from '../components/tasks/TasksFilters.vue'
import TaskListPane from '../components/tasks/TaskListPane.vue'
import TaskDetailPane from '../components/tasks/TaskDetailPane.vue'

const router = useRouter()

const loading = ref(false)
const refreshing = ref(false)
const items = ref([])
const totalItems = ref(0)
const pageSize = ref(80)
const currentOffset = ref(0)
const selectedItemId = ref('')
const selectedItemDetail = ref(null)
const detailLoading = ref(false)
const currentDomain = ref('all')
const currentStatus = ref('all')
const searchQuery = ref('')
const debouncedSearchQuery = ref('')
const overviewHighlightCounts = ref({})
const overviewDomainCounts = ref({})
const pollingEnabled = ref(true)
const sortKey = ref('updated_desc')
const activeOnly = ref(false)
const treeExpandedState = ref({})
const treeFilterMode = ref('all')

let intervalId = null
let queuedRefresh = false
let searchDebounceTimer = null
const DETAIL_REFRESH_INTERVAL_MS = 15000
let lastDetailFetchedAt = 0
let lastDetailSyncSignature = ''

const domainOptions = [
  { value: 'all', label: '全部', icon: ListChecks },
  { value: 'import', label: '导入处理', icon: FileArchive },
  { value: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
  { value: 'subtitle_import', label: '字幕补配', icon: Sparkles },
  { value: 'asmr_sync', label: 'ASMR 同步', icon: UploadCloud },
  { value: 'upload', label: '库存上传', icon: Upload },
  { value: 'circle_completion', label: '社团补全', icon: Database },
  { value: 'system', label: '系统任务', icon: Activity },
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'processing', label: '处理中' },
  { value: 'waiting_manual', label: '等待人工' },
  { value: 'waiting_retry', label: '等待重试' },
  { value: 'pending', label: '待处理' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
  { value: 'completed', label: '已完成' },
]

function getDomainCount(domain) {
  return Number(overviewDomainCounts.value[domain] || 0) || ''
}

const metricsPanel = computed(() => [
  {
    key: 'processing',
    label: '处理中',
    value: Number(overviewHighlightCounts.value.processing || 0),
    icon: Activity,
    click: () => { currentStatus.value = 'processing' },
  },
  {
    key: 'waiting_manual',
    label: '等待人工',
    value: Number(overviewHighlightCounts.value.waiting_manual || 0),
    icon: PauseCircle,
    click: () => { currentStatus.value = 'waiting_manual' },
  },
  {
    key: 'waiting_retry',
    label: '等待重试',
    value: Number(overviewHighlightCounts.value.waiting_retry || 0),
    icon: RotateCcw,
    click: () => { currentStatus.value = 'waiting_retry' },
  },
  {
    key: 'failed',
    label: '失败',
    value: Number(overviewHighlightCounts.value.failed || 0),
    icon: XCircle,
    click: () => { currentStatus.value = 'failed' },
  },
])

const ACTIVE_STATUSES = new Set(['processing', 'pending', 'paused', 'waiting_manual', 'waiting_retry'])

function safeTimestamp(value) {
  const ts = new Date(value || 0).getTime()
  return Number.isFinite(ts) ? ts : 0
}

function statusPriority(status) {
  const map = {
    processing: 0,
    waiting_manual: 1,
    waiting_retry: 2,
    pending: 3,
    paused: 4,
    failed: 5,
    completed: 6,
  }
  return map[String(status || '')] ?? 99
}

const filteredItems = computed(() => {
  let next = Array.isArray(items.value) ? [...items.value] : []
  if (activeOnly.value) {
    next = next.filter((item) => ACTIVE_STATUSES.has(String(item?.status || '').trim()))
  }
  next.sort((a, b) => {
    if (sortKey.value === 'created_desc') {
      return safeTimestamp(b?.created_at) - safeTimestamp(a?.created_at)
    }
    if (sortKey.value === 'progress_desc') {
      const p = Number(b?.progress || 0) - Number(a?.progress || 0)
      if (p !== 0) return p
      return safeTimestamp(b?.updated_at || b?.created_at) - safeTimestamp(a?.updated_at || a?.created_at)
    }
    if (sortKey.value === 'status_priority') {
      const s = statusPriority(a?.status) - statusPriority(b?.status)
      if (s !== 0) return s
      return safeTimestamp(b?.updated_at || b?.created_at) - safeTimestamp(a?.updated_at || a?.created_at)
    }
    return safeTimestamp(b?.updated_at || b?.created_at) - safeTimestamp(a?.updated_at || a?.created_at)
  })
  return next
})

const listDigest = computed(() => {
  const digest = { active: 0, completed: 0, failed: 0 }
  for (const item of filteredItems.value) {
    const status = String(item?.status || '').trim()
    if (ACTIVE_STATUSES.has(status)) digest.active += 1
    if (status === 'completed') digest.completed += 1
    if (status === 'failed' || status === 'canceled' || status === 'cancelled') digest.failed += 1
  }
  return digest
})

const selectedItem = computed(() => {
  if (!filteredItems.value.length) return null
  const summary = filteredItems.value.find((item) => item.id === selectedItemId.value) || filteredItems.value[0]
  if (selectedItemDetail.value?.id === summary?.id) {
    return { ...summary, ...selectedItemDetail.value }
  }
  return summary
})

watch(filteredItems, (nextItems) => {
  if (!nextItems.length) {
    selectedItemId.value = ''
    return
  }
  if (!nextItems.some((item) => item.id === selectedItemId.value)) {
    selectedItemId.value = nextItems[0].id
  }
}, { immediate: true })

watch(selectedItemId, async (nextId) => {
  if (!nextId) {
    selectedItemDetail.value = null
    lastDetailSyncSignature = ''
    lastDetailFetchedAt = 0
    treeExpandedState.value = {}
    treeFilterMode.value = 'all'
    return
  }
  selectedItemDetail.value = null
  treeExpandedState.value = {}
  treeFilterMode.value = 'all'
  await fetchSelectedItemDetail(nextId, { force: true })
}, { immediate: true })

function buildSummarySyncSignature(summary) {
  if (!summary) return ''
  return [
    String(summary.id || ''),
    String(summary.status || ''),
    String(summary.progress ?? ''),
    String(summary.current_step || ''),
    String(summary.error_message || ''),
    String(summary.started_at || ''),
    String(summary.completed_at || ''),
    String(summary.updated_at || ''),
  ].join('|')
}

function shouldRefreshDetail(nextItems) {
  if (!selectedItemId.value) return false
  const summary = nextItems.find((item) => item.id === selectedItemId.value)
  if (!summary) return false
  const currentSignature = buildSummarySyncSignature(summary)
  const now = Date.now()
  const bySignature = currentSignature !== lastDetailSyncSignature
  const byInterval = now - lastDetailFetchedAt >= DETAIL_REFRESH_INTERVAL_MS
  return bySignature || byInterval
}

watch([currentDomain, currentStatus], () => {
  currentOffset.value = 0
  refreshTaskCenter(false, { silent: true }).catch((error) => {
    console.error('任务中心筛选刷新失败:', error)
  })
})

watch(searchQuery, () => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    debouncedSearchQuery.value = String(searchQuery.value || '').trim()
    currentOffset.value = 0
    refreshTaskCenter(false, { silent: true }).catch((error) => {
      console.error('任务中心搜索刷新失败:', error)
    })
  }, 350)
})

watch(pollingEnabled, (enabled) => {
  if (enabled) startPolling()
  else stopPolling()
})

onMounted(async () => {
  await refreshTaskCenter(false, { silent: false })
  startPolling()
})

onUnmounted(() => {
  stopPolling()
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
})

function startPolling() {
  if (intervalId || !pollingEnabled.value) return
  intervalId = setInterval(() => {
    refreshTaskCenter(false, { silent: true }).catch((error) => {
      console.error('任务中心轮询失败:', error)
    })
  }, 5000)
}

function stopPolling() {
  if (!intervalId) return
  clearInterval(intervalId)
  intervalId = null
}

function resetFilters() {
  currentDomain.value = 'all'
  currentStatus.value = 'all'
  activeOnly.value = false
  searchQuery.value = ''
  debouncedSearchQuery.value = ''
  currentOffset.value = 0
  refreshTaskCenter(false, { silent: true }).catch((error) => {
    console.error('任务中心重置筛选失败:', error)
  })
}

function applyQuickFilter(domain, status) {
  currentDomain.value = domain
  currentStatus.value = status
  currentOffset.value = 0
  refreshTaskCenter(false, { silent: true }).catch((error) => {
    console.error('任务中心快速筛选失败:', error)
  })
}

function handlePrevPage() {
  currentOffset.value = Math.max(0, currentOffset.value - pageSize.value)
  refreshTaskCenter(false, { silent: true })
}

function handleNextPage() {
  currentOffset.value += pageSize.value
  refreshTaskCenter(false, { silent: true })
}

async function refreshTaskCenter(showMessage = false, options = {}) {
  const { silent = false } = options
  if (refreshing.value) {
    queuedRefresh = true
    return
  }
  try {
    refreshing.value = true
    if (!silent) loading.value = true

    const params = {
      mode: 'summary',
      limit: pageSize.value,
      offset: currentOffset.value,
      _t: Date.now(),
    }
    if (currentDomain.value !== 'all') params.domain = currentDomain.value
    if (currentStatus.value !== 'all') params.status = currentStatus.value
    if (debouncedSearchQuery.value) params.search = debouncedSearchQuery.value

    const [overviewData, listData] = await Promise.all([
      taskCenterApi.overview({ _t: Date.now() }),
      taskCenterApi.list(params),
    ])

    overviewHighlightCounts.value = overviewData?.highlight_counts || {}
    overviewDomainCounts.value = overviewData?.counts_by_domain || {}

    const nextItems = Array.isArray(listData) ? listData : (listData?.items || [])
    items.value = nextItems
    totalItems.value = Number(listData?.total ?? nextItems.length)

    if (totalItems.value > 0 && currentOffset.value >= totalItems.value) {
      currentOffset.value = Math.max(0, Math.floor((totalItems.value - 1) / pageSize.value) * pageSize.value)
      queuedRefresh = true
      return
    }

    if (shouldRefreshDetail(nextItems)) {
      fetchSelectedItemDetail(selectedItemId.value).catch((error) => {
        console.error('任务详情同步刷新失败:', error)
      })
    }

    if (showMessage) ElMessage.success('任务中心已刷新')
  } catch (error) {
    console.error('获取任务中心失败:', error)
    if (!silent) {
      ElMessage.error('获取任务中心失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    refreshing.value = false
    if (!silent) loading.value = false
    if (queuedRefresh) {
      queuedRefresh = false
      refreshTaskCenter(false, { silent: true }).catch((error) => {
        console.error('任务中心补偿刷新失败:', error)
      })
    }
  }
}

async function fetchSelectedItemDetail(itemId, options = {}) {
  const { force = false } = options
  if (!force && detailLoading.value) return
  detailLoading.value = true
  try {
    const detail = await taskCenterApi.getItem({ item_id: itemId, _t: Date.now() })
    if (selectedItemId.value === itemId) {
      selectedItemDetail.value = detail || null
      lastDetailSyncSignature = buildSummarySyncSignature(detail || {})
      lastDetailFetchedAt = Date.now()
    }
  } catch (error) {
    console.error('获取任务详情失败:', error)
  } finally {
    detailLoading.value = false
  }
}

function showProgress(item) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(item?.status)
}

function getFileName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

function pickMetricValue(item, label) {
  const metrics = Array.isArray(item?.metrics) ? item.metrics : []
  return metrics.find((metric) => metric?.label === label)?.value || ''
}

function containsRJ(value) {
  return /[RVB]J(?:\d{8}|\d{6})(?!\d)/i.test(String(value || ''))
}

function formatRJCode(value) {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''
  const match = raw.match(/(?:RJ)+\s*(\d{6,8})/i)
  if (match) return `RJ${match[1]}`
  const fallback = raw.match(/[RVB]J\s*(\d{6,8})/i)
  if (fallback) return `RJ${fallback[1]}`
  return raw
}

function formatBytes(value) {
  const size = Number(value || 0)
  if (!size || Number.isNaN(size)) return ''
  if (size < 1024) return `${Math.round(size)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = size / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(2)} ${units[unitIndex]}`
}

function buildTreeRows(treeItems = []) {
  const roots = []
  const nodeMap = new Map()
  const ensureNode = (key, label, type, parentKey = '') => {
    if (nodeMap.has(key)) return nodeMap.get(key)
    const node = { key, label, type, status: 'default', sizeText: '', children: [] }
    nodeMap.set(key, node)
    if (parentKey && nodeMap.has(parentKey)) nodeMap.get(parentKey).children.push(node)
    else roots.push(node)
    return node
  }
  for (const item of treeItems) {
    const rawPath = String(item?.relative_path || item?.name || item?.path || '').replace(/^[/\\]+|[/\\]+$/g, '')
    if (!rawPath) continue
    const parts = rawPath.split('/').filter(Boolean)
    let parentKey = ''
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const node = ensureNode(joined, part, isLeaf ? (item?.type || 'file') : 'dir', parentKey)
      if (isLeaf) {
        node.type = item?.type || 'file'
        node.status = item?.status || node.status
        node.sizeText = item?.sizeText || formatBytes(item?.size)
      }
      parentKey = joined
    })
  }
  const compareNodes = (left, right) => {
    if (left.type !== right.type) return left.type === 'dir' ? -1 : 1
    return left.label.localeCompare(right.label, 'zh-Hans-CN-u-kn-true')
  }
  const rows = []
  const walk = (nodes, depth = 0) => {
    const sorted = [...nodes].sort(compareNodes)
    for (const node of sorted) {
      const hasChildren = node.children.length > 0
      const defaultExpanded = depth < 1
      const expanded = hasChildren
        ? (treeExpandedState.value[node.key] ?? defaultExpanded)
        : false
      rows.push({
        key: node.key,
        label: node.label,
        type: node.type,
        status: node.status,
        sizeText: node.sizeText,
        depth,
        hasChildren,
        childCount: node.children.length,
        expanded,
        defaultExpanded,
      })
      if (hasChildren && expanded) walk(node.children, depth + 1)
    }
  }
  walk(roots)
  return rows
}

function toggleTreeNode(key, defaultExpanded = false) {
  treeExpandedState.value = {
    ...treeExpandedState.value,
    [key]: !(treeExpandedState.value[key] ?? defaultExpanded),
  }
}

function setTreeSectionExpanded(section, expanded) {
  const nextState = { ...treeExpandedState.value }
  for (const key of section?.directoryKeys || []) {
    nextState[key] = expanded
  }
  treeExpandedState.value = nextState
}

function getImportFailureStageLabel(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const stage = String(metadata.failure_stage || '').trim().toLowerCase()
  const stageMap = {
    extract: '解压失败',
    metadata: '元数据失败',
    rename: '重命名失败',
    filter: '过滤失败',
    classify: '分类失败',
    archive: '归档失败',
    process: '处理失败',
  }
  if (stageMap[stage]) return stageMap[stage]
  if (String(item?.status || '') === 'failed') return '处理失败'
  return ''
}

function getOutputPath(item) {
  if (!item) return ''
  const details = item.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  return (
    item.target_path ||
    metadata.subtitle_dir ||
    metadata.target_folder_path ||
    metadata.folder_path ||
    preview.selected_candidate?.folder_path ||
    ''
  )
}

function normalizeRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  const repeated = text.match(/(?:RJ)+(\d{4,})/i)
  if (repeated) return `RJ${repeated[1]}`
  const standard = text.match(/RJ\d{4,}/i)
  return standard ? standard[0].toUpperCase() : ''
}

function dedupeSummaryPieces(pieces) {
  const out = []
  const seen = new Set()
  for (const piece of pieces) {
    const text = String(piece || '').trim()
    if (!text) continue
    const normalizedRJ = normalizeRJ(text)
    const key = normalizedRJ ? `RJ:${normalizedRJ}` : text
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

function getTaskSummary(item) {
  if (!item) return []
  const details = item.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  const pieces = []
  const recoveredFailureCount = pickMetricValue(item, '此前失败')
  const recoveredConflictCount = pickMetricValue(item, '问题作品')

  if (item.domain === 'import') {
    const targetLibrary = pickMetricValue(item, '目标库')
    const failureStage = getImportFailureStageLabel(item)
    if (failureStage) pieces.push(failureStage)
    if (targetLibrary) pieces.push(`目标库 ${targetLibrary}`)
    const normalizedRJ = formatRJCode(item.rjcode)
    if (!pieces.length && normalizedRJ && !containsRJ(item.title) && !containsRJ(item.subtitle)) {
      pieces.push(normalizedRJ)
    }
  } else if (item.domain === 'rj_subtitle') {
    const downloadCount = pickMetricValue(item, '下载')
    const writtenCount = pickMetricValue(item, '写入')
    const subtitleDir = item.target_path || metadata.subtitle_dir || ''
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (downloadCount) pieces.push(`下载 ${downloadCount}`)
    if (writtenCount) pieces.push(`写入 ${writtenCount}`)
    if (subtitleDir) pieces.push(`目录 ${getFileName(subtitleDir)}`)
  } else if (item.domain === 'subtitle_import') {
    const subtitleCount = pickMetricValue(item, '来源字幕') || preview.subtitle_count
    const candidateCount = pickMetricValue(item, '可执行候选') || pickMetricValue(item, '候选目录')
    const targetFolder = item.target_path || preview.selected_candidate?.folder_path || ''
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`目标 ${normalizedRJ}`)
    if (subtitleCount) pieces.push(`候选字幕 ${subtitleCount}`)
    if (candidateCount) pieces.push(`候选目录 ${candidateCount}`)
    if (targetFolder) pieces.push(`目标目录 ${getFileName(targetFolder)}`)
  } else if (item.domain === 'asmr_sync') {
    const downloadFiles = pickMetricValue(item, '下载文件')
    const failedFiles = pickMetricValue(item, '失败文件')
    const uploadedCount = pickMetricValue(item, '已上传')
    const uploadedBytes = pickMetricValue(item, '上传大小')
    const averageUpload = pickMetricValue(item, '平均上传')
    const duration = pickMetricValue(item, '耗时')
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (downloadFiles) pieces.push(`文件 ${downloadFiles}`)
    if (uploadedCount) pieces.push(`上传 ${uploadedCount}`)
    if (uploadedBytes) pieces.push(uploadedBytes)
    if (averageUpload) pieces.push(averageUpload)
    if (duration) pieces.push(duration)
    if (failedFiles) pieces.push(`失败 ${failedFiles}`)
    if (item.subtitle) pieces.push(`来源 ${getFileName(item.subtitle)}`)
  } else if (item.domain === 'circle_completion') {
    const dlsiteCount = pickMetricValue(item, 'DLsite')
    const downloadableCount = pickMetricValue(item, '可下载')
    const localCount = pickMetricValue(item, '本地')
    const missingCount = pickMetricValue(item, '缺失')
    if (dlsiteCount) pieces.push(`DLsite ${dlsiteCount}`)
    if (downloadableCount) pieces.push(`可下载 ${downloadableCount}`)
    if (localCount) pieces.push(`本地 ${localCount}`)
    if (missingCount) pieces.push(`缺失 ${missingCount}`)
  } else {
    const outputName = pickMetricValue(item, '输出') || item.target_path
    const targetLibrary = pickMetricValue(item, '目标库')
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (outputName) pieces.push(`输出 ${getFileName(outputName)}`)
    if (targetLibrary) pieces.push(`目标库 ${targetLibrary}`)
  }

  if (recoveredFailureCount) pieces.push(`已恢复 ${recoveredFailureCount}`)
  if (recoveredConflictCount) pieces.push(recoveredConflictCount)
  return dedupeSummaryPieces(pieces).slice(0, 6)
}

function mapFilteredItems(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const rawItems = [
    ...(Array.isArray(metadata.filtered_items) ? metadata.filtered_items : []),
    ...(Array.isArray(metadata.filtered_files) ? metadata.filtered_files : []),
    ...(Array.isArray(metadata.filtered_dirs) ? metadata.filtered_dirs : []),
  ]
  const mapped = []
  const seen = new Set()
  for (const current of rawItems) {
    if (!current) continue
    const asObject = typeof current === 'object' ? current : { path: String(current) }
    const relativePath = String(asObject.relative_path || asObject.path || asObject.name || '').replace(/^[/\\]+|[/\\]+$/g, '')
    if (!relativePath || seen.has(relativePath)) continue
    seen.add(relativePath)
    mapped.push({
      key: relativePath,
      relative_path: relativePath,
      type: asObject.type === 'dir' || asObject.is_dir ? 'dir' : 'file',
      status: 'removed',
      sizeText: asObject.size !== undefined && asObject.size !== null ? formatBytes(asObject.size) : '',
    })
  }
  return mapped
}

function mapUploadedFiles(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const sourceFiles = Array.isArray(metadata.upload_files) && metadata.upload_files.length
    ? metadata.upload_files
    : Array.isArray(metadata.uploaded_files) ? metadata.uploaded_files : []
  return sourceFiles.map((current, index) => ({
    key: String(current?.relative_path || current?.name || current?.upload_path || `${index}`),
    relative_path: String(current?.relative_path || current?.name || current?.upload_path || ''),
    name: String(current?.name || current?.relative_path || current?.upload_path || '未命名文件'),
    type: 'file',
    size: Number(current?.size_bytes || 0),
    status: 'added',
  })).filter((row) => row.relative_path || row.name)
}

function mapDownloadFiles(item) {
  const metadata = item?.details?.metadata || {}
  const downloadFiles = Array.isArray(metadata.download_files) ? metadata.download_files : []
  return downloadFiles.map((current, index) => ({
    key: String(current?.relative_path || current?.path || current?.name || `${index}`),
    relative_path: String(current?.relative_path || current?.path || current?.name || ''),
    name: String(current?.name || current?.relative_path || current?.path || '未命名文件'),
    type: current?.type === 'dir' || current?.is_dir ? 'dir' : 'file',
    size: Number(current?.size_bytes || current?.size || 0),
    status: 'added',
  })).filter((row) => row.relative_path || row.name)
}

function mapFileTreeItems(item) {
  const metadata = item?.details?.metadata || {}
  const treeItems = Array.isArray(metadata.file_tree_items) ? metadata.file_tree_items : []
  return treeItems.map((current, index) => ({
    key: String(current?.relative_path || current?.path || current?.name || `${index}`),
    relative_path: String(current?.relative_path || current?.path || current?.name || ''),
    name: String(current?.name || current?.relative_path || current?.path || '未命名项'),
    type: current?.type === 'dir' || current?.is_dir ? 'dir' : 'file',
    size: current?.size,
    status: 'default',
  })).filter((row) => row.relative_path || row.name)
}

function buildTaskFileTreeSections(item) {
  if (!item) return []
  const metadata = item?.details?.metadata || {}
  const removedItems = mapFilteredItems(item)
  const filterMode = treeFilterMode.value
  const sectionDefinitions = []

  if (Array.isArray(metadata.file_tree_items) && metadata.file_tree_items.length) {
    sectionDefinitions.push({ key: 'extracted', label: '解压文件树', items: mapFileTreeItems(item) })
  }
  if (Array.isArray(metadata.upload_files) && metadata.upload_files.length) {
    sectionDefinitions.push({ key: 'upload', label: '新增文件树', items: mapUploadedFiles(item) })
  } else if (!sectionDefinitions.length && Array.isArray(metadata.uploaded_files) && metadata.uploaded_files.length) {
    sectionDefinitions.push({ key: 'upload', label: '新增文件树', items: mapUploadedFiles(item) })
  }
  if (Array.isArray(metadata.download_files) && metadata.download_files.length) {
    sectionDefinitions.push({ key: 'download', label: '下载文件树', items: mapDownloadFiles(item) })
  }
  if (!sectionDefinitions.length && removedItems.length) {
    sectionDefinitions.push({ key: 'removed-only', label: '过滤移除清单', items: [] })
  }

  return sectionDefinitions.map((section) => {
    const mergedMap = new Map()
    for (const current of section.items) {
      const path = String(current?.relative_path || current?.name || '').replace(/^[/\\]+|[/\\]+$/g, '')
      if (!path) continue
      mergedMap.set(path, { ...current, relative_path: path })
    }
    for (const removed of removedItems) {
      const path = String(removed?.relative_path || removed?.name || '').replace(/^[/\\]+|[/\\]+$/g, '')
      if (!path) continue
      const previous = mergedMap.get(path)
      mergedMap.set(path, { ...(previous || {}), ...removed, relative_path: path, status: 'removed' })
    }
    const mergedItems = Array.from(mergedMap.values())
    const filtered = mergedItems.filter((entry) => {
      if (filterMode === 'added') return entry.status === 'added'
      if (filterMode === 'removed') return entry.status === 'removed'
      return true
    })
    const directoryKeys = new Set()
    for (const entry of mergedItems) {
      const rawPath = String(entry?.relative_path || '').replace(/^[/\\]+|[/\\]+$/g, '')
      if (!rawPath) continue
      const parts = rawPath.split('/').filter(Boolean)
      let joined = ''
      parts.slice(0, -1).forEach((part) => {
        joined = joined ? `${joined}/${part}` : part
        directoryKeys.add(joined)
      })
      if (entry.type === 'dir') directoryKeys.add(rawPath)
    }
    const directoryKeyList = Array.from(directoryKeys)
    const allExpanded = directoryKeyList.length
      ? directoryKeyList.every((key) => treeExpandedState.value[key] ?? true)
      : true
    return {
      key: section.key,
      label: section.label,
      rows: buildTreeRows(filtered),
      totalCount: mergedItems.length,
      addedCount: mergedItems.filter((entry) => entry.status === 'added').length,
      removedCount: mergedItems.filter((entry) => entry.status === 'removed').length,
      directoryKeys: directoryKeyList,
      allExpanded,
    }
  }).filter((section) => section.rows.length)
}

const selectedItemFileTreeSections = computed(() => buildTaskFileTreeSections(selectedItem.value))

function getRecoveredNotice(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  return String(metadata.recovered_notice || '').trim()
}

function getDLsiteFailureReason(item) {
  if (!item) return ''
  const details = item.details || {}
  const metadata = details.metadata || {}
  const indexMeta = metadata.index_meta || {}
  return String(indexMeta.dlsite_failure_reason || metadata.dlsite_failure_reason || '').trim()
}

function getCircleIndexMetaEntries(item) {
  if (item?.kind !== 'circle_completion_index') return []
  const metadata = item?.details?.metadata || {}
  const indexMeta = metadata.index_meta || {}
  const indexedCounts = metadata.indexed_counts || {}
  const entries = [
    ['社团', metadata.circle_name || metadata.circle_query || ''],
    ['Maker ID', indexMeta.maker_id || ''],
    ['来源模式', indexMeta.dlsite_source_mode || ''],
    ['DLsite失败原因', getDLsiteFailureReason(item)],
    ['本地候选', indexMeta.local_candidates_count],
    ['Kikoeru', indexMeta.kikoeru_candidates_count],
    ['DLsite原作', indexMeta.dlsite_profile_total || indexMeta.dlsite_candidates_count],
    ['合并候选', indexMeta.combined_candidates_count || indexMeta.aggregated_count],
    ['已检查下载', indexMeta.asmr_checked_count],
    ['可下载', indexMeta.asmr_available_count || indexedCounts.downloadable_count],
    ['最终作品', indexedCounts.works],
    ['服务器缺失', indexedCounts.missing_count],
  ]
  return entries
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([label, value]) => ({ label, value: String(value) }))
}

function getCircleIndexProgressLog(item) {
  if (item?.kind !== 'circle_completion_index') return []
  const metadata = item?.details?.metadata || {}
  const logs = Array.isArray(metadata.progress_log) ? metadata.progress_log : []
  return logs.slice().reverse()
}

function shouldShowTaskMetaStep(item) {
  const step = String(item?.current_step || '').trim()
  const statusLabel = String(item?.status_label || '').trim()
  if (!step) return false
  if (step === statusLabel) return false
  if (['完成', '已完成', '处理中', '等待中', '待处理', '已暂停', '失败', '等待重试', '等待人工'].includes(step)) {
    return false
  }
  return true
}

async function handleTaskAction(item, action) {
  try {
    const result = await taskCenterApi.action(item.id, action)
    if (result?.route_hint) await router.push(result.route_hint)
    ElMessage.success(result?.message || '操作成功')
    await refreshTaskCenter()
  } catch (error) {
    console.error('执行任务动作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openTaskRoute(item) {
  if (!item?.route_hint) return
  router.push(item.route_hint)
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
</script>
