<template>
  <div class="dashboard-page-shell flex h-full min-h-0 w-full flex-col overflow-hidden px-2 pb-2 pt-1 text-slate-900">
    <DashboardHero
      :watcher-running="watcherRunning"
      :loading="loading"
      :kpi-cards="kpiCards"
      @refresh="refreshDashboardOnResume(false)"
      @kpi-click="openKpiTarget"
      @upload-success="handleUploadSuccess"
    />

    <DashboardCommandStrip
      :scanning="scanning"
      :watcher-running="watcherRunning"
      @scan="handleManualScan"
      @toggle-watcher="handleWatcherToggle"
      @go="(path) => router.push(path)"
    />

    <main class="grid min-h-0 flex-1 grid-cols-1 items-stretch gap-3 overflow-hidden lg:grid-cols-[minmax(0,1fr)_360px]">
      <DashboardActiveTasks
        :tasks="recentTasks"
        :status-cards="statusCards"
        class="min-h-0"
        @go="(path) => router.push(path)"
        @action="handleTaskCenterAction"
      />

      <DashboardArchive
        :archives="displayedArchives"
        :filtered-archives="filteredArchives"
        :tabs="archiveDomainTabs"
        :domain-filter="archiveDomainFilter"
        :search-query="archiveSearchQuery"
        :archives-loading="archivesLoading"
        :reprocessing-id="reprocessingId"
        :total="filteredArchives.length"
        :page="archivePage"
        :page-size="archivePageSize"
        :get-meta="getArchiveTaskMeta"
        :get-status-meta="getArchiveStatusMeta"
        :format-date="formatDate"
        :format-file-size="formatFileSize"
        class="min-h-0"
        @refresh="refreshArchivePanel"
        @reprocess="reprocessArchive"
        @change-page="handleArchivePageChange"
        @update:search-query="onArchiveSearchInput"
        @update:domain-filter="(v) => (archiveDomainFilter = v)"
      />
    </main>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Activity,
  Archive,
  Captions,
  CloudDownload,
  Database,
  Download,
  FileArchive,
  ShieldAlert,
  Sparkles,
  Upload,
  UploadCloud,
} from 'lucide-vue-next'
import { conflictApi, processedArchiveApi, scanApi, taskCenterApi, watcherApi } from '../api'
import { getTaskDomainMeta } from '../components/common/taskDomainMeta.js'
import { getHttpDownloadDisplayMeta } from '../components/common/httpDownloadPlatformMeta.js'
import DashboardHero from '../components/dashboard/DashboardHero.vue'
import DashboardCommandStrip from '../components/dashboard/DashboardCommandStrip.vue'
import DashboardActiveTasks from '../components/dashboard/DashboardActiveTasks.vue'
import DashboardArchive from '../components/dashboard/DashboardArchive.vue'
import { patchTaskCenterItemList } from '../composables/taskCenterEventUtils'
import { showSystemConfirm } from '../composables/useSystemPrompt'

const router = useRouter()

const loading = ref(false)
const scanning = ref(false)
const watcherRunning = ref(false)
const taskCenterOverview = ref({
  recent_items: [],
  active_items: [],
  counts_by_domain: {},
  counts_by_status: {},
  highlight_counts: {},
  total: 0,
})
const stats = ref({ pending: 0, processing: 0, completed: 0, conflicts: 0 })

const archives = ref([])
const archiveTotal = ref(0)
const archivesLoading = ref(false)
const reprocessingId = ref(null)
const archivePage = ref(1)
const archivePageSize = ref(10)
const archiveSearchQuery = ref('')
const archiveSortBy = ref('processed_at')
const archiveSortOrder = ref('desc')
let archiveSearchTimeout = null

let intervalId = null
let dashboardInitialized = false
let dashboardViewActive = false
let refreshRunning = false
let refreshPending = false
let refreshRequestId = 0
let visibilityBound = false
let lastConflictRefreshTime = 0
let cachedConflictCount = 0
let streamRefreshTimer = null
let archiveStreamRefreshTimer = null
let lastTaskCenterStreamEventAt = 0
const CONFLICT_REFRESH_INTERVAL = 30000
const STREAM_REFRESH_DEBOUNCE_MS = 500
const ARCHIVE_STREAM_REFRESH_DEBOUNCE_MS = 350
const FALLBACK_POLL_INTERVAL_MS = 30000
const STREAM_FULL_REFRESH_MIN_INTERVAL_MS = 2500
const DASHBOARD_ARCHIVE_LIMIT = 120
let lastTaskCenterFullRefreshAt = 0
let archivesRequestId = 0

const domainCounts = computed(() => ({
  import: Number(taskCenterOverview.value?.counts_by_domain?.import || 0),
  rj_subtitle: Number(taskCenterOverview.value?.counts_by_domain?.rj_subtitle || 0),
  subtitle_import: Number(taskCenterOverview.value?.counts_by_domain?.subtitle_import || 0),
  asmr_sync: Number(taskCenterOverview.value?.counts_by_domain?.asmr_sync || 0),
  http_download: Number(taskCenterOverview.value?.counts_by_domain?.http_download || 0),
  baidu_netdisk: Number(taskCenterOverview.value?.counts_by_domain?.baidu_netdisk || 0),
  upload: Number(taskCenterOverview.value?.counts_by_domain?.upload || 0),
  circle_completion: Number(taskCenterOverview.value?.counts_by_domain?.circle_completion || 0),
}))

const recentTasks = computed(() => {
  const active = Array.isArray(taskCenterOverview.value?.active_items) ? taskCenterOverview.value.active_items : []
  const recent = Array.isArray(taskCenterOverview.value?.recent_items) ? taskCenterOverview.value.recent_items : []
  return active.length ? active : recent.slice(0, 10)
})

const kpiCards = computed(() => [
  { key: 'import', label: '导入处理', value: domainCounts.value.import, icon: FileArchive, route: '/library' },
  { key: 'rj', label: 'RJ 字幕', value: domainCounts.value.rj_subtitle, icon: Captions, route: '/library' },
  { key: 'subtitle', label: '字幕补配', value: domainCounts.value.subtitle_import, icon: Sparkles, route: '/subtitle-import' },
  { key: 'asmr', label: 'ASMR 同步', value: domainCounts.value.asmr_sync, icon: UploadCloud, route: { path: '/asmr-sync', query: { tab: 'enhanced' } } },
  { key: 'http', label: 'HTTP 下载', value: domainCounts.value.http_download, icon: Download, route: { path: '/asmr-sync', query: { tab: 'http' } } },
  { key: 'upload', label: '库存上传', value: domainCounts.value.upload, icon: Upload, route: '/library' },
  { key: 'conflicts', label: '问题作品', value: stats.value.conflicts, icon: ShieldAlert, route: '/conflicts' },
])

const statusCards = computed(() => [
  { key: 'processing', label: '处理中', value: Number(taskCenterOverview.value?.highlight_counts?.processing || 0) },
  {
    key: 'waiting_total',
    label: '等待中',
    value: Number(
      taskCenterOverview.value?.highlight_counts?.waiting_total
      ?? (
        Number(taskCenterOverview.value?.counts_by_status?.pending || 0)
        + Number(taskCenterOverview.value?.counts_by_status?.paused || 0)
        + Number(taskCenterOverview.value?.counts_by_status?.waiting_manual || 0)
        + Number(taskCenterOverview.value?.counts_by_status?.waiting_retry || 0)
      )
    ),
  },
  { key: 'completed', label: '已完成', value: Number(taskCenterOverview.value?.highlight_counts?.completed || taskCenterOverview.value?.counts_by_status?.completed || 0) },
  { key: 'waiting', label: '等待人工', value: Number(taskCenterOverview.value?.highlight_counts?.waiting_manual || 0) },
  { key: 'retry', label: '等待重试', value: Number(taskCenterOverview.value?.highlight_counts?.waiting_retry || 0) },
  { key: 'failed', label: '失败', value: Number(taskCenterOverview.value?.highlight_counts?.failed || 0) },
])

function parseVolumeArchiveFilename(filename) {
  const text = String(filename || '').trim()
  if (!text) return null

  let match = text.match(/^(.*)\.part(\d+)\.(rar|zip|7z|exe)$/i)
  if (match) {
    return {
      groupKey: `${match[1].toLowerCase()}::${match[3].toLowerCase()}`,
      displayName: `${match[1]}.${match[3].toLowerCase()}`,
      volumeIndex: Number(match[2] || 0),
    }
  }

  match = text.match(/^(.*)\.(zip|7z|rar)\.(\d{2,3})$/i)
  if (match) {
    return {
      groupKey: `${match[1].toLowerCase()}::${match[2].toLowerCase()}`,
      displayName: `${match[1]}.${match[2].toLowerCase()}`,
      volumeIndex: Number(match[3] || 0),
    }
  }

  match = text.match(/^(.*)\.(z|r)(\d{2,3})$/i)
  if (match) {
    const family = String(match[2] || '').toLowerCase()
    return {
      groupKey: `${match[1].toLowerCase()}::${family}`,
      displayName: `${match[1]}.${family}`,
      volumeIndex: Number(match[3] || 0),
    }
  }

  return null
}

const groupedArchives = computed(() => {
  const groups = new Map()
  const singles = []
  for (const archive of archives.value) {
    const filename = String(archive.filename || '')
    const volumeInfo = parseVolumeArchiveFilename(filename)
    if (!volumeInfo) {
      singles.push({ ...archive, source: 'processed_archive', isVolumeGroup: false })
      continue
    }
    const groupKey = volumeInfo.groupKey
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        id: archive.id,
        rjcode: archive.rjcode,
        filename: `${volumeInfo.displayName}（分卷组）`,
        file_size: 0,
        process_count: archive.process_count || 1,
        processed_at: archive.processed_at || new Date(0).toISOString(),
        status: archive.status,
        isVolumeGroup: true,
        volumes: [],
        volumeIndex: volumeInfo.volumeIndex || 0,
      })
    }
    const group = groups.get(groupKey)
    group.volumes.push(archive)
    group.file_size += Number(archive.file_size || 0)
    if (archive.rjcode && !group.rjcode) group.rjcode = archive.rjcode
    if (archive.status && group.status !== 'failed') group.status = archive.status
    if (volumeInfo.volumeIndex && (!group.volumeIndex || volumeInfo.volumeIndex < group.volumeIndex)) {
      group.volumeIndex = volumeInfo.volumeIndex
      group.id = archive.id
    }
    if (filename.toLowerCase().includes('.part1.')) {
      group.id = archive.id
    }
  }
  return [...groups.values(), ...singles]
    .map((item) => {
      if (!item.isVolumeGroup || !Array.isArray(item.volumes) || !item.volumes.length) {
        return { ...item, source: item.source || 'processed_archive' }
      }
      const latestArchive = item.volumes.reduce((latest, current) => {
        const latestTime = new Date(latest?.processed_at || 0).getTime()
        const currentTime = new Date(current?.processed_at || 0).getTime()
        return currentTime >= latestTime ? current : latest
      }, item.volumes[0])
      return {
        ...item,
        id: item.id || latestArchive?.id,
        rjcode: item.rjcode || latestArchive?.rjcode,
        processed_at: latestArchive?.processed_at || item.processed_at,
        process_count: Math.max(...item.volumes.map((volume) => Number(volume?.process_count || 1))),
        source: 'processed_archive',
      }
    })
})

const taskArchiveItems = computed(() => {
  const items = Array.isArray(taskCenterOverview.value?.recent_items) ? taskCenterOverview.value.recent_items : []
  const active = Array.isArray(taskCenterOverview.value?.active_items) ? taskCenterOverview.value.active_items : []
  return [...active, ...items]
    .filter((task, index, list) => list.findIndex((item) => item.id === task.id) === index)
    .map((task) => {
      const domain = String(task.domain || 'system').trim()
      const title = String(task.title || task.subtitle || task.id || '未命名任务').trim()
      return {
        id: `task-${task.id}`,
        source: 'task_center',
        filename: title,
        rjcode: formatRJ(task.rjcode),
        status: task.status,
        task_domain: domain,
        domain,
        task_kind: task.kind || task.type || '',
        processed_at: task.completed_at || task.updated_at || task.started_at || task.created_at,
        file_size: 0,
        summary: task.subtitle || task.current_step || '',
        status_label: task.status_label || '',
        error_message: task.error_message || '',
        current_step: task.current_step || '',
        source_label: task.source_label || '',
        platform_label: task.platform_label || task.details?.metadata?.platform_label || '',
        platforms: Array.isArray(task.platforms) ? task.platforms : (task.details?.metadata?.platforms || []),
        download_mode: task.download_mode || task.details?.metadata?.download_mode || '',
        source_modes: Array.isArray(task.source_modes) ? task.source_modes : (task.details?.metadata?.source_modes || []),
        details: task.details || {},
        route_hint: task.route_hint,
      }
    })
})

const displayedArchives = computed(() => {
  const archiveItems = groupedArchives.value
  const taskItems = taskArchiveItems.value.filter((item) => item.task_domain !== 'import')
  return [...taskItems, ...archiveItems]
    .sort((a, b) => new Date(b.processed_at || 0).getTime() - new Date(a.processed_at || 0).getTime())
})

const archiveDomainFilter = ref('all')

const archiveDomainTabMeta = {
  all: { key: 'all', label: '全部', icon: Archive, chipIcon: 'text-slate-500', chipBg: 'bg-slate-100', chipText: 'text-slate-600' },
  import: { key: 'import', label: '解压入库', icon: FileArchive, chipIcon: 'text-amber-600', chipBg: 'bg-amber-50', chipText: 'text-amber-700' },
  subtitle_import: { key: 'subtitle_import', label: '字幕补配', icon: Sparkles, chipIcon: 'text-violet-600', chipBg: 'bg-violet-50', chipText: 'text-violet-700' },
  rj_subtitle: { key: 'rj_subtitle', label: 'RJ 字幕', icon: Captions, chipIcon: 'text-sky-600', chipBg: 'bg-sky-50', chipText: 'text-sky-700' },
  asmr_sync: { key: 'asmr_sync', label: 'ASMR', icon: UploadCloud, chipIcon: 'text-emerald-600', chipBg: 'bg-emerald-50', chipText: 'text-emerald-700' },
  http_download: { key: 'http_download', label: 'HTTP 下载', icon: Download, chipIcon: 'text-orange-600', chipBg: 'bg-orange-50', chipText: 'text-orange-700' },
  baidu_netdisk: { key: 'baidu_netdisk', label: '百度网盘', icon: CloudDownload, chipIcon: 'text-blue-600', chipBg: 'bg-blue-50', chipText: 'text-blue-700' },
  upload: { key: 'upload', label: '库存上传', icon: Upload, chipIcon: 'text-blue-600', chipBg: 'bg-blue-50', chipText: 'text-blue-700' },
  circle_completion: { key: 'circle_completion', label: '社团补全', icon: Database, chipIcon: 'text-teal-600', chipBg: 'bg-teal-50', chipText: 'text-teal-700' },
  system: { key: 'system', label: '系统', icon: Activity, chipIcon: 'text-slate-600', chipBg: 'bg-slate-100', chipText: 'text-slate-700' },
}

const archiveDomainOrder = ['import', 'http_download', 'baidu_netdisk', 'subtitle_import', 'rj_subtitle', 'asmr_sync', 'upload', 'circle_completion', 'system']

const archiveDomainTabs = computed(() => {
  const domainCountMap = new Map()
  for (const item of displayedArchives.value) {
    const key = getArchiveTaskMeta(item).key
    if (!key) continue
    domainCountMap.set(key, (domainCountMap.get(key) || 0) + 1)
  }
  const tabs = [{ ...archiveDomainTabMeta.all, count: displayedArchives.value.length }]
  for (const key of archiveDomainOrder) {
    const count = domainCountMap.get(key) || 0
    if (count > 0) tabs.push({ ...archiveDomainTabMeta[key], count })
  }
  return tabs
})

watch(
  archiveDomainTabs,
  (tabs) => {
    const isCurrentFilterAvailable = tabs.some((tab) => tab.key === archiveDomainFilter.value)
    if (!isCurrentFilterAvailable) archiveDomainFilter.value = 'all'
  },
  { immediate: true }
)

const filteredArchives = computed(() => {
  const keyword = archiveSearchQuery.value.trim().toLowerCase()
  const all = keyword
    ? displayedArchives.value.filter((item) => {
        const text = [item.filename, item.rjcode, item.summary, item.task_domain, item.domain]
          .join(' ')
          .toLowerCase()
        return text.includes(keyword)
      })
    : displayedArchives.value
  if (archiveDomainFilter.value === 'all') return all
  return all.filter((a) => {
    const domain = String(a?.task_domain || a?.domain || a?.task_kind || a?.kind || 'import')
      .trim()
      .toLowerCase()
    return domain === archiveDomainFilter.value
  })
})

onMounted(async () => {
  await initializeDashboardPage()
  dashboardViewActive = true
  bindDashboardVisibilityRefresh()
  bindTaskCenterStreamEvents()
  startDashboardPolling()
})

onActivated(async () => {
  if (dashboardViewActive) return
  dashboardViewActive = true
  await refreshDashboardOnResume()
  bindTaskCenterStreamEvents()
  startDashboardPolling()
})

onDeactivated(() => {
  dashboardViewActive = false
  unbindTaskCenterStreamEvents()
  stopDashboardPolling()
})

onUnmounted(() => {
  dashboardViewActive = false
  stopDashboardPolling()
  unbindDashboardVisibilityRefresh()
  unbindTaskCenterStreamEvents()
  if (archiveSearchTimeout) {
    clearTimeout(archiveSearchTimeout)
    archiveSearchTimeout = null
  }
})

function stopDashboardPolling() {
  if (intervalId) {
    clearInterval(intervalId)
    intervalId = null
  }
}

function startDashboardPolling() {
  stopDashboardPolling()
  intervalId = setInterval(() => {
    if (Date.now() - lastTaskCenterStreamEventAt < FALLBACK_POLL_INTERVAL_MS) return
    refreshData({ silent: true })
  }, FALLBACK_POLL_INTERVAL_MS)
}

function bindDashboardVisibilityRefresh() {
  if (visibilityBound) return
  visibilityBound = true
  window.addEventListener('focus', handleDashboardVisibilityRefresh)
  document.addEventListener('visibilitychange', handleDashboardVisibilityRefresh)
}

function unbindDashboardVisibilityRefresh() {
  if (!visibilityBound) return
  visibilityBound = false
  window.removeEventListener('focus', handleDashboardVisibilityRefresh)
  document.removeEventListener('visibilitychange', handleDashboardVisibilityRefresh)
}

function handleDashboardVisibilityRefresh() {
  if (!dashboardViewActive || document.visibilityState === 'hidden') return
  refreshData({ silent: true })
}

function bindTaskCenterStreamEvents() {
  window.removeEventListener('kikoerumanager:task-center:changed', handleTaskCenterStreamEvent)
  window.addEventListener('kikoerumanager:task-center:changed', handleTaskCenterStreamEvent)
}

function unbindTaskCenterStreamEvents() {
  window.removeEventListener('kikoerumanager:task-center:changed', handleTaskCenterStreamEvent)
  if (streamRefreshTimer) {
    clearTimeout(streamRefreshTimer)
    streamRefreshTimer = null
  }
  if (archiveStreamRefreshTimer) {
    clearTimeout(archiveStreamRefreshTimer)
    archiveStreamRefreshTimer = null
  }
}

function scheduleDashboardStreamRefresh() {
  if (!dashboardViewActive) return
  if (streamRefreshTimer) clearTimeout(streamRefreshTimer)
  streamRefreshTimer = setTimeout(() => {
    streamRefreshTimer = null
    const now = Date.now()
    if (now - lastTaskCenterFullRefreshAt < STREAM_FULL_REFRESH_MIN_INTERVAL_MS) return
    refreshData({ silent: true })
  }, STREAM_REFRESH_DEBOUNCE_MS)
}

function scheduleArchiveStreamRefresh() {
  if (!dashboardViewActive) return
  if (archiveStreamRefreshTimer) clearTimeout(archiveStreamRefreshTimer)
  archiveStreamRefreshTimer = setTimeout(() => {
    archiveStreamRefreshTimer = null
    fetchProcessedArchives({ silent: true })
  }, ARCHIVE_STREAM_REFRESH_DEBOUNCE_MS)
}

function patchDashboardTaskOverview(payload) {
  const current = taskCenterOverview.value || {}
  taskCenterOverview.value = {
    ...current,
    active_items: patchTaskCenterItemList(current.active_items || [], payload),
    recent_items: patchTaskCenterItemList(current.recent_items || [], payload),
  }
}

function handleTaskCenterStreamEvent(event) {
  const payload = event?.detail || {}
  if (!payload?.type) return
  lastTaskCenterStreamEventAt = Date.now()
  if (payload.type === 'processed_archive_changed') {
    scheduleArchiveStreamRefresh()
    return
  }
  if (payload.type === 'connected') {
    refreshData({ silent: true })
    fetchProcessedArchives({ silent: true })
    return
  }
  if (payload.type !== 'task_center_changed') return
  patchDashboardTaskOverview(payload)
  scheduleDashboardStreamRefresh()
}

async function initializeDashboardPage() {
  if (dashboardInitialized) return
  await refreshDashboardOnResume(false)
  dashboardInitialized = true
}

async function refreshDashboardOnResume(silent = true) {
  await refreshData({ silent, forceConflictRefresh: true })
  await fetchWatcherStatus()
  await fetchProcessedArchives({ silent: true })
}

async function refreshData(options = {}) {
  const { silent = false, forceConflictRefresh = false } = options
  if (refreshRunning) {
    refreshPending = true
    return
  }
  refreshRunning = true
  const currentRequestId = ++refreshRequestId
  if (!silent) loading.value = true
  try {
    const now = Date.now()
    const shouldRefreshConflicts =
      forceConflictRefresh || !lastConflictRefreshTime || now - lastConflictRefreshTime >= CONFLICT_REFRESH_INTERVAL

    const overviewPromise = taskCenterApi.overview({ _t: now })
    const conflictCountPromise = shouldRefreshConflicts
      ? conflictApi.count().catch((error) => {
          console.error('获取问题作品数量失败:', error)
          return null
        })
      : Promise.resolve(null)

    const [overview, conflictCount] = await Promise.all([overviewPromise, conflictCountPromise])
    if (currentRequestId !== refreshRequestId) return
    taskCenterOverview.value = overview || taskCenterOverview.value
    lastTaskCenterFullRefreshAt = Date.now()

    if (conflictCount) {
      cachedConflictCount = Number(conflictCount?.count || 0)
      lastConflictRefreshTime = now
    }

    stats.value = {
      pending: Number(overview?.counts_by_status?.pending || 0),
      processing: Number(overview?.counts_by_status?.processing || 0),
      completed: Number(overview?.counts_by_status?.completed || 0),
      conflicts: cachedConflictCount,
    }
  } catch (error) {
    console.error('获取概览失败:', error)
    if (!silent) {
      ElMessage.error('获取概览失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    refreshRunning = false
    if (!silent) loading.value = false
    if (refreshPending) {
      refreshPending = false
      refreshData({ silent: true })
    }
  }
}

async function handleManualScan() {
  scanning.value = true
  try {
    const data = await scanApi.scan()
    ElMessage.success(data.message)
    await refreshData()
  } catch (error) {
    console.error('扫描失败:', error)
    ElMessage.error('扫描失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    scanning.value = false
  }
}

async function handleWatcherToggle() {
  try {
    if (watcherRunning.value) {
      await watcherApi.stop()
      watcherRunning.value = false
      ElMessage.success('监视器已停止')
    } else {
      await watcherApi.start()
      watcherRunning.value = true
      ElMessage.success('监视器已启动')
    }
  } catch (error) {
    console.error('操作监视器失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function handleUploadSuccess() {
  refreshData()
  fetchProcessedArchives({ silent: true })
}

async function fetchWatcherStatus() {
  try {
    const data = await watcherApi.status()
    watcherRunning.value = Boolean(data?.is_running)
  } catch (error) {
    console.error('获取监视器状态失败:', error)
  }
}

async function fetchProcessedArchives(options = {}) {
  const { silent = false, scan = false } = options
  const currentRequestId = ++archivesRequestId
  archivesLoading.value = true
  try {
    if (scan) {
      await processedArchiveApi.scan()
    }
    const params = {
      sort_by: archiveSortBy.value,
      sort_order: archiveSortOrder.value,
      limit: DASHBOARD_ARCHIVE_LIMIT,
      offset: 0,
    }
    if (archiveSearchQuery.value) params.search = archiveSearchQuery.value
    const data = await processedArchiveApi.list(params)
    if (currentRequestId !== archivesRequestId) return
    archives.value = data?.archives || []
    archiveTotal.value = Number(data?.total || archives.value.length)
    if (!silent) ElMessage.success('刷新成功')
  } catch (error) {
    console.error('获取已处理压缩包列表失败:', error)
    if (!silent) ElMessage.error('获取已处理压缩包列表失败')
  } finally {
    if (currentRequestId === archivesRequestId) {
      archivesLoading.value = false
    }
  }
}

async function refreshArchivePanel() {
  await refreshData({ silent: true })
  await fetchProcessedArchives({ scan: true })
}

function onArchiveSearchInput(value) {
  archiveSearchQuery.value = String(value || '')
  if (archiveSearchTimeout) clearTimeout(archiveSearchTimeout)
  archiveSearchTimeout = setTimeout(() => {
    archivePage.value = 1
    fetchProcessedArchives({ silent: true })
  }, 400)
}

function handleArchivePageChange(page) {
  const totalPages = Math.max(1, Math.ceil((displayedArchives.value?.length || 0) / archivePageSize.value))
  archivePage.value = Math.min(Math.max(1, page), totalPages)
}

async function reprocessArchive(archiveId) {
  reprocessingId.value = archiveId
  try {
    const data = await processedArchiveApi.reprocess(archiveId)
    ElMessage.success(data.message)
    await refreshData()
    await fetchProcessedArchives({ silent: true })
  } catch (error) {
    console.error('重新处理失败:', error)
    ElMessage.error('重新处理失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    reprocessingId.value = null
  }
}

async function handleTaskCenterAction(task, action) {
  if (action === 'delete') {
    try {
      await showSystemConfirm({
        title: '删除任务记录',
        message: `确认删除「${task?.title || '该任务'}」的任务记录？`,
        description: '只会清理任务中心记录，不会删除业务文件。',
        tone: 'danger',
        confirmText: '删除',
      })
    } catch (_) {
      return
    }
  }
  try {
    const result = await taskCenterApi.action(task.id, action)
    if (result?.route_hint) await router.push(result.route_hint)
    ElMessage.success(result?.message || '操作成功')
    await refreshData()
  } catch (error) {
    console.error('执行任务中心动作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openKpiTarget(item) {
  if (item.route) router.push(item.route)
}

function formatRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const match = text.match(/[RVB]J\s*(\d{4,})/i)
  return match ? `RJ${match[1]}` : text
}

function formatFileSize(bytes) {
  const size = Number(bytes || 0)
  if (!size) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let current = size
  let index = 0
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024
    index += 1
  }
  return `${current.toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function formatDate(dateString) {
  if (!dateString) return '-'
  const raw = String(dateString).trim()
  const hasExplicitTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const normalized = hasExplicitTimezone ? raw : raw.replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return String(dateString)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function getArchiveTaskMeta(archive) {
  const domain = String(
    archive?.task_domain || archive?.domain || archive?.task_kind || archive?.kind || 'import'
  )
    .trim()
    .toLowerCase()
  const known = ['import', 'rj_subtitle', 'subtitle_import', 'asmr_sync', 'http_download', 'baidu_netdisk', 'upload', 'circle_completion', 'system']
  const key = known.includes(domain) ? domain : 'import'
  const meta = getTaskDomainMeta(key)
  if (key === 'http_download') {
    const httpMeta = getHttpDownloadDisplayMeta(archive)
    return {
      key,
      label: meta.label,
      icon: httpMeta.icon || meta.icon,
      iconWrap: meta.iconWrap,
      chip: meta.chip,
      chipIcon: httpMeta.icon ? 'dash-archive-platform-icon' : meta.chipIcon,
      chipBg: meta.chipBg,
      chipText: meta.chipText,
      bar: meta.bar,
    }
  }
  return {
    key,
    label: meta.label,
    icon: meta.icon,
    iconWrap: meta.iconWrap,
    chip: meta.chip,
    chipIcon: meta.chipIcon,
    chipBg: meta.chipBg,
    chipText: meta.chipText,
    bar: meta.bar,
  }
}

function getArchiveStatusMeta(value) {
  const item = value && typeof value === 'object' ? value : null
  const normalized = String(item?.status || value || '').trim().toLowerCase()
  const cancelText = [
    item?.status_label,
    item?.error_message,
    item?.current_step,
    item?.summary,
    item?.details?.metadata?.cancel_reason,
  ].join(' ')
  if (normalized === 'cancelled' || normalized === 'canceled' || cancelText.includes('用户取消')) {
    return { key: 'cancelled', label: '已取消' }
  }
  if (!normalized) return { key: 'unknown', label: '状态未知' }
  if (['completed', 'success', 'finished'].includes(normalized)) return { key: 'completed', label: '已完成' }
  if (['partial_failed', 'partial_success'].includes(normalized)) return { key: 'partial_failed', label: '部分成功' }
  if (['failed', 'error'].includes(normalized)) return { key: 'failed', label: '失败' }
  if (['processing', 'running'].includes(normalized)) return { key: 'processing', label: '处理中' }
  if (['waiting_manual', 'awaiting_manual_match', 'manual_required'].includes(normalized)) return { key: 'waiting_manual', label: '等待人工' }
  if (['waiting_retry', 'retry_waiting'].includes(normalized)) return { key: 'waiting_retry', label: '等待重试' }
  if (['pending', 'waiting', 'queued'].includes(normalized)) return { key: 'pending', label: '待处理' }
  return { key: 'unknown', label: normalized }
}
</script>

<style scoped>
/* ============================================================
 * 移动端 (≤1024)：整页切到 stream 模式
 * 桌面端零改动：仅 @media 内覆盖
 * 痛点：桌面是 h-full + overflow-hidden + 双栏 grid 各自滚，
 *      移动端会把 main 压成两个被挤死的小框（任务流只显 1 条、归档无内容）。
 * 解法：让主壳 / main / 子组件 root / 子组件内部滚动区 都松绑高度，
 *      改成自然内容高度 + 外层 .content-shell 整页滚动。
 * ============================================================ */
@media (max-width: 1024px) {
  .dashboard-page-shell {
    height: auto !important;
    min-height: 100%;
    overflow: visible !important;
  }
  .dashboard-page-shell main {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    overflow: visible !important;
  }
  /* 任务流 + 归档：root 解锁高度 */
  .dashboard-page-shell :deep([data-section="dashboard-tasks"]),
  .dashboard-page-shell :deep([data-section="dashboard-archive"]) {
    height: auto !important;
    min-height: 0 !important;
    flex: 0 0 auto !important;
  }
  /* 子组件内部的 overflow-auto / overflow-hidden + flex-1 列表区松绑：
     让内容自然撑开高度（整页滚动而不是内部小框滚动） */
  .dashboard-page-shell :deep([data-section="dashboard-tasks"] .overflow-auto),
  .dashboard-page-shell :deep([data-section="dashboard-archive"] .overflow-auto) {
    overflow: visible !important;
    flex: 0 0 auto !important;
    min-height: 0 !important;
    max-height: none !important;
  }
}
</style>
