<template>
  <div class="dashboard-shell">
    <header class="workspace-bar">
      <div class="workspace-title">
        <LayoutDashboard :size="18" :stroke-width="2.3" class="workspace-title-icon" />
        <div>
          <h1 class="dash-title">概览</h1>
          <p class="dash-subtitle">处理队列、入库入口和最近归档</p>
        </div>
      </div>

      <div class="workspace-actions">
        <span class="watcher-pill" :class="{ 'is-running': watcherRunning }">
          <span class="watcher-dot"></span>
          {{ watcherRunning ? '监视中' : '已停止' }}
        </span>
        <button type="button" class="dash-btn dash-btn-ghost" :disabled="loading" @click="refreshDashboardOnResume(false)">
          <RefreshCw :size="14" :stroke-width="2.3" :class="{ 'animate-spin': loading }" />
        </button>
        <button type="button" class="dash-btn dash-btn-primary scan-entry-btn" :disabled="scanning" @click="handleManualScan">
          <Search :size="14" :stroke-width="2.3" />
          <span>{{ scanning ? '扫描中' : '扫描处理' }}</span>
        </button>
      </div>
    </header>

    <section class="workspace-metrics-panel">
      <div class="workspace-metrics">
        <button
          v-for="item in kpiCards"
          :key="item.key"
          type="button"
          class="metric-pill"
          :class="`is-${item.key}`"
          @click="openKpiTarget(item)"
        >
          <component :is="item.icon" :size="14" :stroke-width="2.3" class="metric-icon" />
          <span>{{ item.label }}</span>
          <b>{{ item.value }}</b>
        </button>
      </div>
    </section>

    <section class="command-strip">
      <div class="command-group">
        <button type="button" class="command-btn is-blue is-scan-entry" :disabled="scanning" @click="handleManualScan">
          <Search :size="15" :stroke-width="2.3" class="command-icon" />
          <span>{{ scanning ? '扫描中' : '扫描处理' }}</span>
        </button>
        <button type="button" class="command-btn is-emerald" @click="handleWatcherToggle">
          <component :is="watcherRunning ? PauseCircle : PlayCircle" :size="15" :stroke-width="2.3" class="command-icon" />
          <span>{{ watcherRunning ? '停止监视' : '启动监视' }}</span>
        </button>
        <button type="button" class="command-btn is-rose" @click="router.push('/conflicts')">
          <AlertTriangle :size="15" :stroke-width="2.3" class="command-icon" />
          <span>问题作品</span>
        </button>
        <button type="button" class="command-btn is-violet" @click="router.push('/tasks')">
          <ListChecks :size="15" :stroke-width="2.3" class="command-icon" />
          <span>任务中心</span>
        </button>
      </div>

      <div class="upload-inline">
        <FileUploader compact @upload-success="handleUploadSuccess" />
      </div>
    </section>

    <main class="workspace-grid">
      <section class="main-pane">
        <div class="section-head">
          <div>
            <h2 class="section-title">任务流</h2>
            <p class="section-subtitle">活跃任务优先，空闲时显示最近完成/失败</p>
          </div>
          <button type="button" class="mini-link" @click="router.push('/tasks')">
            查看全部
            <ArrowRight :size="14" :stroke-width="2.4" />
          </button>
        </div>

        <div v-if="recentTasks.length" class="task-list">
          <article v-for="task in recentTasks" :key="task.id" class="task-row" :class="`is-${task.domain || 'system'}`">
            <span class="task-icon"><component :is="domainMeta(task.domain).icon" :size="15" :stroke-width="2.3" /></span>
            <div class="task-main">
              <div class="task-row-top">
                <h3 class="task-title">{{ task.title }}</h3>
                <span class="status-pill" :class="`is-${statusClass(task)}`">{{ statusLabel(task) }}</span>
              </div>
              <p v-if="task.subtitle" class="task-subtitle">{{ task.subtitle }}</p>
              <div class="task-meta-line">
                <span class="task-chip">
                  <component :is="domainMeta(task.domain).icon" :size="12" :stroke-width="2.3" />
                  <span>{{ task.domain_label }}</span>
                </span>
                <span v-if="formatRJ(task.rjcode)" class="task-chip is-rj">
                  <Archive :size="12" :stroke-width="2.3" />
                  <span>{{ formatRJ(task.rjcode) }}</span>
                </span>
                <span v-if="task.current_step" class="task-chip is-step">
                  <Activity :size="12" :stroke-width="2.3" />
                  <span>{{ task.current_step }}</span>
                </span>
              </div>
              <div v-if="showProgress(task)" class="task-progress">
                <el-progress :percentage="task.progress" :stroke-width="7" :show-text="false" />
                <span>{{ task.progress }}%</span>
              </div>
            </div>
            <div v-if="task.actions?.length" class="task-actions">
              <button
                v-for="action in task.actions"
                :key="`${task.id}-${action}`"
                type="button"
                class="icon-action"
                :class="`is-${action}`"
                :title="getActionLabel(action)"
                @click="handleTaskCenterAction(task, action)"
              >
                <component :is="actionIcon(action)" :size="14" :stroke-width="2.4" />
              </button>
            </div>
          </article>
        </div>

        <AppEmptyState v-else description="当前没有需要关注的任务" size="default" />
      </section>

      <aside class="side-pane">
        <section class="side-section">
          <div class="section-head compact">
            <div>
              <h2 class="section-title">状态</h2>
              <p class="section-subtitle">队列摘要</p>
            </div>
            <Activity :size="16" :stroke-width="2.2" class="text-blue-500" />
          </div>
          <div class="status-list">
            <div v-for="item in statusCards" :key="item.key" class="status-row" :class="`is-${item.key}`">
              <div class="status-row-main">
                <component :is="statusCardIcon(item.key)" :size="14" :stroke-width="2.4" class="status-icon" />
                <span>{{ item.label }}</span>
              </div>
              <b>{{ item.value }}</b>
            </div>
          </div>
        </section>

        <section class="side-section">
          <div class="section-head compact">
            <div>
              <h2 class="section-title">最近归档</h2>
              <p class="section-subtitle">{{ filteredArchives.length ? `${filteredArchives.length} 条记录` : '暂无记录' }}</p>
            </div>
            <button type="button" class="mini-icon-btn" :disabled="archivesLoading" @click="refreshArchivePanel" title="刷新归档记录">
              <RefreshCw :size="14" :stroke-width="2.3" :class="{ 'animate-spin': archivesLoading }" />
            </button>
          </div>

          <div class="archive-tools">
            <div class="archive-search">
              <Search :size="13" :stroke-width="2.3" />
              <input v-model="archiveSearchQuery" type="text" placeholder="搜索 RJ / 文件名" @input="handleArchiveSearch" />
            </div>
          </div>

          <div class="archive-domain-tabs">
            <button
              v-for="tab in archiveDomainTabs"
              :key="tab.key"
              type="button"
              class="archive-tab-btn"
              :class="{ 'is-active': archiveDomainFilter === tab.key }"
              @click="archiveDomainFilter = tab.key"
            >
              <component :is="tab.icon" :size="12" :stroke-width="2.3" class="archive-tab-icon" :class="`is-${tab.key}`" />
              <span>{{ tab.label }}</span>
              <span v-if="tab.count > 0" class="archive-tab-count">{{ tab.count }}</span>
            </button>
          </div>

          <div v-if="filteredArchives.length" class="archive-list">
            <article v-for="archive in filteredArchives" :key="archive.id" class="archive-row">
              <span class="archive-icon" :class="`is-${getArchiveTaskMeta(archive).key}`">
                <component :is="getArchiveTaskMeta(archive).icon" :size="14" :stroke-width="2.3" />
              </span>
              <div class="archive-main">
                <div class="archive-row-top">
                  <h3 class="archive-title">{{ archive.filename }}</h3>
                  <span v-if="archive.rjcode" class="archive-rj">{{ archive.rjcode }}</span>
                </div>
                <div class="archive-badges">
                  <span class="archive-tag archive-type-tag" :class="`is-${getArchiveTaskMeta(archive).key}`">
                    <component :is="getArchiveTaskMeta(archive).icon" :size="12" :stroke-width="2.3" />
                    <span>{{ getArchiveTaskMeta(archive).label }}</span>
                  </span>
                  <span class="archive-tag archive-status-tag" :class="`is-${getArchiveStatusMeta(archive.status).key}`">
                    <component :is="archiveStatusIcon(getArchiveStatusMeta(archive.status).key)" :size="12" :stroke-width="2.3" />
                    <span>{{ getArchiveStatusMeta(archive.status).label }}</span>
                  </span>
                </div>
                <div class="archive-meta">
                  <span v-if="archive.file_size">{{ formatFileSize(archive.file_size) }}</span>
                  <span>{{ formatDate(archive.processed_at) }}</span>
                  <span v-if="archive.isVolumeGroup">{{ archive.volumes.length }} 分卷</span>
                </div>
              </div>
              <button v-if="archive.source === 'processed_archive'" type="button" class="icon-action is-retry" :disabled="reprocessingId === archive.id" title="重新解压" @click="reprocessArchive(archive.id)">
                <RotateCcw :size="14" :stroke-width="2.4" />
              </button>
            </article>
          </div>

          <AppEmptyState v-else description="暂无归档记录" size="default" />

          <div v-if="archiveTotal > archivePageSize && archiveDomainFilter === 'import'" class="archive-footer archive-pagination">
            <el-pagination
              :current-page="archivePage"
              :page-size="archivePageSize"
              :total="archiveTotal"
              layout="prev, pager, next"
              :background="true"
              :disabled="archivesLoading"
              @current-change="handleArchivePageChange"
            />
          </div>
        </section>
      </aside>
    </main>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowRight,
  Captions,
  Database,
  FileArchive,
  LayoutDashboard,
  ListChecks,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Upload,
  UploadCloud,
  XCircle,
} from 'lucide-vue-next'
import { conflictApi, processedArchiveApi, scanApi, taskCenterApi, watcherApi } from '../api'
import FileUploader from '../components/FileUploader.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'

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
  total: 0
})
const stats = ref({
  pending: 0,
  processing: 0,
  completed: 0,
  conflicts: 0
})

const archives = ref([])
const archiveTotal = ref(0)
const archivesLoading = ref(false)
const reprocessingId = ref(null)
const archivePage = ref(1)
const archivePageSize = ref(6)
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
const CONFLICT_REFRESH_INTERVAL = 30000

const domainCounts = computed(() => ({
  import: Number(taskCenterOverview.value?.counts_by_domain?.import || 0),
  rj_subtitle: Number(taskCenterOverview.value?.counts_by_domain?.rj_subtitle || 0),
  subtitle_import: Number(taskCenterOverview.value?.counts_by_domain?.subtitle_import || 0),
  asmr_sync: Number(taskCenterOverview.value?.counts_by_domain?.asmr_sync || 0),
  upload: Number(taskCenterOverview.value?.counts_by_domain?.upload || 0),
  circle_completion: Number(taskCenterOverview.value?.counts_by_domain?.circle_completion || 0)
}))

const recentTasks = computed(() => {
  const active = Array.isArray(taskCenterOverview.value?.active_items) ? taskCenterOverview.value.active_items : []
  const recent = Array.isArray(taskCenterOverview.value?.recent_items) ? taskCenterOverview.value.recent_items : []
  return active.length ? active : recent.slice(0, 10)
})

const kpiCards = computed(() => [
  { key: 'import', label: '导入处理', value: domainCounts.value.import, meta: '压缩包入库链路', icon: FileArchive, route: '/library' },
  { key: 'rj', label: 'RJ 字幕', value: domainCounts.value.rj_subtitle, meta: '抓取与配对', icon: Captions, route: '/library' },
  { key: 'subtitle', label: '字幕补配', value: domainCounts.value.subtitle_import, meta: '预检与写入', icon: Sparkles, route: '/subtitle-import' },
  { key: 'asmr', label: 'ASMR 同步', value: domainCounts.value.asmr_sync, meta: '下载与上传', icon: UploadCloud, route: '/asmr-sync' },
  { key: 'upload', label: '库存上传', value: domainCounts.value.upload, meta: '目录上传与直传入库', icon: Upload, route: '/library' },
  { key: 'conflicts', label: '问题作品', value: stats.value.conflicts, meta: '等待人工判断', icon: ShieldAlert, route: '/conflicts' },
])

const statusCards = computed(() => [
  { key: 'processing', label: '处理中', value: Number(taskCenterOverview.value?.highlight_counts?.processing || 0) },
  { key: 'waiting', label: '等待人工', value: Number(taskCenterOverview.value?.highlight_counts?.waiting_manual || 0) },
  { key: 'retry', label: '等待重试', value: Number(taskCenterOverview.value?.highlight_counts?.waiting_retry || 0) },
  { key: 'failed', label: '失败', value: Number(taskCenterOverview.value?.highlight_counts?.failed || 0) },
])

const groupedArchives = computed(() => {
  const groups = new Map()
  const singles = []
  for (const archive of archives.value) {
    const filename = String(archive.filename || '')
    const volumeMatch = filename.match(/^(.*)\.part(\d+)\.(rar|zip|7z|exe)$/i)
    if (!volumeMatch) {
      singles.push({ ...archive, source: 'processed_archive', isVolumeGroup: false })
      continue
    }
    const baseName = volumeMatch[1]
    const groupKey = `${baseName}_volume_group`
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        id: archive.id,
        rjcode: archive.rjcode,
        filename: `${baseName}（分卷组）`,
        file_size: 0,
        process_count: archive.process_count || 1,
        processed_at: archive.processed_at || new Date(0).toISOString(),
        status: archive.status,
        isVolumeGroup: true,
        volumes: []
      })
    }
    const group = groups.get(groupKey)
    group.volumes.push(archive)
    group.file_size += Number(archive.file_size || 0)
    if (filename.toLowerCase().includes('.part1.')) {
      group.id = archive.id
    }
  }
  return [...groups.values(), ...singles].map(item => ({ ...item, source: item.source || 'processed_archive' }))
})

const taskArchiveItems = computed(() => {
  const items = Array.isArray(taskCenterOverview.value?.recent_items) ? taskCenterOverview.value.recent_items : []
  const active = Array.isArray(taskCenterOverview.value?.active_items) ? taskCenterOverview.value.active_items : []
  return [...active, ...items]
    .filter((task, index, list) => list.findIndex(item => item.id === task.id) === index)
    .map(task => {
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
        route_hint: task.route_hint,
      }
    })
})

const displayedArchives = computed(() => {
  const archiveItems = groupedArchives.value
  const taskItems = taskArchiveItems.value.filter(item => item.task_domain !== 'import')
  return [...taskItems, ...archiveItems]
    .sort((a, b) => new Date(b.processed_at || 0).getTime() - new Date(a.processed_at || 0).getTime())
    .slice(0, archivePageSize.value)
})

const archiveDomainFilter = ref('all')

const archiveDomainTabMeta = {
  all: { key: 'all', label: '全部', icon: Archive },
  import: { key: 'import', label: '解压入库', icon: FileArchive },
  subtitle_import: { key: 'subtitle_import', label: '字幕补配', icon: Sparkles },
  rj_subtitle: { key: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
  asmr_sync: { key: 'asmr_sync', label: 'ASMR', icon: UploadCloud },
  upload: { key: 'upload', label: '库存上传', icon: Upload },
  circle_completion: { key: 'circle_completion', label: '社团补全', icon: Database },
  system: { key: 'system', label: '系统', icon: Activity },
}

const archiveDomainOrder = ['import', 'subtitle_import', 'rj_subtitle', 'asmr_sync', 'upload', 'circle_completion', 'system']

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

watch(archiveDomainTabs, tabs => {
  const isCurrentFilterAvailable = tabs.some(tab => tab.key === archiveDomainFilter.value)
  if (!isCurrentFilterAvailable) archiveDomainFilter.value = 'all'
}, { immediate: true })

const filteredArchives = computed(() => {
  const keyword = archiveSearchQuery.value.trim().toLowerCase()
  const all = keyword
    ? displayedArchives.value.filter(item => {
        const text = [
          item.filename,
          item.rjcode,
          item.summary,
          item.task_domain,
          item.domain,
        ].join(' ').toLowerCase()
        return text.includes(keyword)
      })
    : displayedArchives.value
  if (archiveDomainFilter.value === 'all') return all
  return all.filter(a => {
    const domain = String(a?.task_domain || a?.domain || a?.task_kind || a?.kind || 'import').trim().toLowerCase()
    return domain === archiveDomainFilter.value
  })
})

onMounted(async () => {
  await initializeDashboardPage()
  dashboardViewActive = true
  bindDashboardVisibilityRefresh()
  startDashboardPolling()
})

onActivated(async () => {
  if (dashboardViewActive) return
  dashboardViewActive = true
  await refreshDashboardOnResume()
  startDashboardPolling()
})

onDeactivated(() => {
  dashboardViewActive = false
  stopDashboardPolling()
})

onUnmounted(() => {
  dashboardViewActive = false
  stopDashboardPolling()
  unbindDashboardVisibilityRefresh()
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
    refreshData({ silent: true })
  }, 3000)
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
    const overview = await taskCenterApi.overview({ _t: Date.now() })
    if (currentRequestId !== refreshRequestId) return
    taskCenterOverview.value = overview || taskCenterOverview.value

    const now = Date.now()
    const shouldRefreshConflicts = forceConflictRefresh || !lastConflictRefreshTime || now - lastConflictRefreshTime >= CONFLICT_REFRESH_INTERVAL
    if (shouldRefreshConflicts) {
      try {
        const data = await conflictApi.count()
        cachedConflictCount = Number(data?.count || 0)
        lastConflictRefreshTime = now
      } catch (error) {
        console.error('获取问题作品数量失败:', error)
      }
    }

    stats.value = {
      pending: Number(overview?.counts_by_status?.pending || 0),
      processing: Number(overview?.counts_by_status?.processing || 0),
      completed: Number(overview?.counts_by_status?.completed || 0),
      conflicts: cachedConflictCount
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
  archivesLoading.value = true
  try {
    if (scan) {
      await processedArchiveApi.scan()
    }
    const params = {
      sort_by: archiveSortBy.value,
      sort_order: archiveSortOrder.value,
      limit: archivePageSize.value,
      offset: (archivePage.value - 1) * archivePageSize.value
    }
    if (archiveSearchQuery.value) params.search = archiveSearchQuery.value
    const data = await processedArchiveApi.list(params)
    archives.value = data?.archives || []
    archiveTotal.value = Number(data?.total || archives.value.length)
    const maxPage = Math.max(1, Math.ceil(archiveTotal.value / archivePageSize.value))
    if (archivePage.value > maxPage) {
      archivePage.value = maxPage
      await fetchProcessedArchives({ silent: true })
      return
    }
    if (!silent) ElMessage.success('刷新成功')
  } catch (error) {
    console.error('获取已处理压缩包列表失败:', error)
    if (!silent) ElMessage.error('获取已处理压缩包列表失败')
  } finally {
    archivesLoading.value = false
  }
}

async function refreshArchivePanel() {
  await refreshData({ silent: true })
  await fetchProcessedArchives({ scan: true })
}

function handleArchiveSearch() {
  if (archiveSearchTimeout) clearTimeout(archiveSearchTimeout)
  archiveSearchTimeout = setTimeout(() => {
    archivePage.value = 1
    fetchProcessedArchives({ silent: true })
  }, 400)
}

function handleArchivePageChange(page) {
  archivePage.value = page
  fetchProcessedArchives({ silent: true })
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

function domainMeta(domain) {
  const map = {
    import: { icon: FileArchive },
    rj_subtitle: { icon: Captions },
    subtitle_import: { icon: Sparkles },
    asmr_sync: { icon: UploadCloud },
    upload: { icon: Upload },
    circle_completion: { icon: Database },
    system: { icon: Activity },
  }
  return map[domain] || map.system
}

function statusCardIcon(key) {
  const map = {
    processing: Activity,
    waiting: PauseCircle,
    retry: RotateCcw,
    failed: XCircle,
  }
  return map[key] || Activity
}

function actionIcon(action) {
  const map = {
    pause: PauseCircle,
    resume: PlayCircle,
    cancel: XCircle,
    retry: RotateCcw,
    retry_waiting: RotateCcw,
    delete_waiting_retry: XCircle,
    open_subtitle_import: ArrowRight,
  }
  return map[action] || ArrowRight
}

function getActionLabel(action) {
  const labels = {
    pause: '暂停',
    resume: '恢复',
    cancel: '取消',
    retry: '重试',
    retry_waiting: '立即重试',
    delete_waiting_retry: '移除',
    open_subtitle_import: '前往字幕补配'
  }
  return labels[action] || action
}

function showProgress(task) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(task?.status)
}

function statusClass(task) {
  if (task?.error_message === '用户取消') return 'cancelled'
  return String(task?.status || 'default')
}

function statusLabel(task) {
  if (task?.error_message === '用户取消') return '已取消'
  return task?.status_label || task?.status || '-'
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
    hour12: false
  })
}

function getArchiveTaskMeta(archive) {
  const domain = String(
    archive?.task_domain || archive?.domain || archive?.task_kind || archive?.kind || 'import'
  ).trim().toLowerCase()

  const map = {
    import: { key: 'import', label: '导入处理', icon: FileArchive },
    rj_subtitle: { key: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
    subtitle_import: { key: 'subtitle_import', label: '字幕补配', icon: Sparkles },
    asmr_sync: { key: 'asmr_sync', label: 'ASMR 同步', icon: UploadCloud },
    upload: { key: 'upload', label: '库存上传', icon: Upload },
    circle_completion: { key: 'circle_completion', label: '社团补全', icon: Database },
    system: { key: 'system', label: '系统任务', icon: Activity },
  }

  return map[domain] || map.import
}

function getArchiveStatusMeta(status) {
  const normalized = String(status || '').trim().toLowerCase()
  if (!normalized) return { key: 'unknown', label: '状态未知' }
  if (['completed', 'success', 'finished'].includes(normalized)) return { key: 'completed', label: '已完成' }
  if (['failed', 'error'].includes(normalized)) return { key: 'failed', label: '失败' }
  if (['processing', 'running'].includes(normalized)) return { key: 'processing', label: '处理中' }
  if (['pending', 'waiting', 'queued'].includes(normalized)) return { key: 'pending', label: '待处理' }
  return { key: 'unknown', label: normalized }
}

function archiveStatusIcon(statusKey) {
  const icons = {
    completed: Sparkles,
    failed: XCircle,
    processing: Activity,
    pending: PauseCircle,
    unknown: Activity,
  }
  return icons[statusKey] || Activity
}
</script>

<style scoped>
.dashboard-shell {
  max-width: 1500px;
  margin: 0 auto;
  padding: 0 16px 32px;
  color: #1a1a1a;
  background: #fff;
}

.workspace-bar,
.workspace-title,
.workspace-metrics,
.workspace-actions,
.command-strip,
.command-group,
.section-head,
.archive-tools,
.task-row-top,
.archive-row-top,
.task-meta-line,
.archive-meta,
.status-row {
  display: flex;
  align-items: center;
}

/* === Page Header (Notion-style, compact) === */
.workspace-bar {
  justify-content: space-between;
  gap: 12px;
  padding: 10px 2px 10px;
  border: none;
  border-bottom: 1px solid #EBEBEA;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  min-height: auto;
  margin-bottom: 0;
}

.workspace-title {
  gap: 11px;
  min-width: 200px;
}

.workspace-title-icon {
  color: #4F7FEF;
  flex-shrink: 0;
}

.dash-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.3px;
  color: #1a1a1a;
}

.dash-subtitle {
  margin: 2px 0 0;
  font-size: 11px;
  color: #9B9A97;
}

.section-subtitle,
.task-subtitle,
.task-meta-line,
.archive-meta {
  color: #787774;
}

.workspace-actions {
  gap: 8px;
}

/* === Metrics Strip (borderless) === */
.workspace-metrics-panel {
  margin: 6px 0;
  padding: 6px 0;
  border: none;
  background: transparent;
  border-radius: 0;
}

.workspace-metrics {
  min-width: 0;
  gap: 6px;
  overflow: auto;
  padding: 2px 0;
}

/* === Shared interactive base === */
.metric-pill,
.dash-btn,
.command-btn,
.mini-link,
.mini-icon-btn,
.icon-action {
  border: 1px solid #EBEBEA;
  background: #fff;
  color: #37352f;
  cursor: pointer;
  transition: all 0.15s ease;
}

.metric-pill:hover,
.dash-btn:hover:not(:disabled),
.command-btn:hover:not(:disabled),
.mini-link:hover,
.mini-icon-btn:hover:not(:disabled),
.icon-action:hover:not(:disabled) {
  background: #F7F7F6;
  border-color: #D4D4D2;
  transform: none;
  box-shadow: none;
}

.metric-pill:active,
.dash-btn:active:not(:disabled),
.command-btn:active:not(:disabled),
.mini-link:active,
.mini-icon-btn:active:not(:disabled),
.icon-action:active:not(:disabled) {
  transform: scale(0.97);
}

.dash-btn:disabled,
.command-btn:disabled,
.mini-icon-btn:disabled,
.icon-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

/* === KPI Metric Pills === */
.metric-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  background: #FAFAF9;
  font-size: 12px;
  font-weight: 500;
  color: #787774;
}

.metric-pill b {
  min-width: 16px;
  font-size: 13px;
  font-weight: 700;
  text-align: right;
  color: #1a1a1a;
}

.metric-icon {
  color: var(--metric-icon-color, #9B9A97);
  flex-shrink: 0;
}

.metric-pill.is-import { --metric-icon-color: #F59E0B; }
.metric-pill.is-rj     { --metric-icon-color: #06B6D4; }
.metric-pill.is-subtitle { --metric-icon-color: #8B5CF6; }
.metric-pill.is-asmr   { --metric-icon-color: #10B981; }
.metric-pill.is-conflicts { --metric-icon-color: #F43F5E; }

/* === Watcher Pill === */
.watcher-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid #EBEBEA;
  background: #FAFAF9;
  color: #9B9A97;
  font-size: 12px;
  font-weight: 500;
}

.watcher-pill.is-running {
  background: #F0FDF4;
  color: #16A34A;
  border-color: #BBF7D0;
}

.watcher-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
}

/* === Header Buttons === */
.dash-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 500;
}

.dash-btn-ghost {
  width: 32px;
  padding: 0;
  color: #787774;
}

.dash-btn-primary {
  border-color: #EBEBEA;
  background: #FAFAF9;
}

.scan-entry-btn {
  border-color: #2563EB;
  background: #2563EB;
  color: #fff;
  font-weight: 600;
  height: 36px;
  padding: 0 14px;
  font-size: 13px;
  box-shadow: 0 1px 4px rgba(37,99,235,0.25);
}

.scan-entry-btn:hover:not(:disabled) {
  background: #1D4ED8 !important;
  border-color: #1D4ED8 !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 10px rgba(37,99,235,0.22) !important;
}

/* === Command Strip (borderless, just a divider row) === */
.command-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 480px);
  gap: 12px;
  margin: 8px 0 14px;
  padding: 10px 0;
  border: none;
  border-bottom: 1px solid #EBEBEA;
  border-radius: 0;
  background: transparent;
}

.command-group {
  gap: 6px;
  flex-wrap: wrap;
}

.command-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 0 0 auto;
  height: 32px;
  padding: 0 11px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 500;
}

.command-icon {
  color: var(--command-icon-color, #9B9A97);
  flex-shrink: 0;
}

.command-btn.is-blue     { --command-icon-color: #2563EB; }
.command-btn.is-emerald  { --command-icon-color: #10B981; }
.command-btn.is-rose     { --command-icon-color: #F43F5E; }
.command-btn.is-violet   { --command-icon-color: #8B5CF6; }

.command-btn.is-scan-entry {
  border-color: #BFDBFE;
  background: #EFF6FF;
  color: #1D4ED8;
  font-weight: 600;
  height: 36px;
  padding: 0 14px;
  font-size: 13px;
}

.command-btn.is-scan-entry { --command-icon-color: #2563EB; }

.command-btn.is-scan-entry:hover:not(:disabled) {
  background: #DBEAFE;
  border-color: #93C5FD;
  transform: none;
}

.upload-inline {
  min-width: 0;
}

.upload-inline :deep(.upload-card) {
  min-height: 100%;
}

/* === Main Grid === */
.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 16px;
  align-items: start;
}

.main-pane,
.side-section {
  border: 1px solid #EBEBEA;
  border-radius: 12px;
  background: #fff;
}

.main-pane {
  min-height: 500px;
  padding: 18px 16px;
}

.side-pane {
  display: grid;
  gap: 12px;
}

.side-section {
  padding: 16px;
}

/* === Section Headers === */
.section-head {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-head.compact {
  margin-bottom: 10px;
}

.section-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: #1a1a1a;
}

.section-subtitle {
  margin: 2px 0 0;
  font-size: 12px;
}

.mini-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #787774;
  font-size: 12px;
  font-weight: 500;
}

.mini-link:hover {
  color: #37352f;
  background: #F7F7F6 !important;
  border-color: #EBEBEA !important;
}

.mini-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: #787774;
}

/* === Task & Archive & Status Lists === */
.task-list,
.archive-list,
.status-list {
  display: grid;
}

.task-list {
  gap: 8px;
}

/* Task Row — clean flat card */
.task-row {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 10px;
  border: 1px solid #EBEBEA;
  border-radius: 10px;
  background: #fff;
  transition: background 0.12s ease;
}

.task-row:hover {
  background: #FAFAF9;
}

.task-main {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* Domain icon backgrounds */
.task-icon,
.archive-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #F7F7F6;
  color: #9B9A97;
  flex-shrink: 0;
}

.task-row.is-import          .task-icon { background: #FFFBEB; color: #F59E0B; }
.task-row.is-rj_subtitle     .task-icon { background: #ECFEFF; color: #06B6D4; }
.task-row.is-subtitle_import .task-icon { background: #F5F3FF; color: #8B5CF6; }
.task-row.is-asmr_sync       .task-icon { background: #F0FDF4; color: #10B981; }
.task-row.is-upload          .task-icon { background: #EFF6FF; color: #2563EB; }
.task-row.is-circle_completion .task-icon { background: #FFF7ED; color: #F97316; }

.task-row-top,
.archive-row-top {
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.task-title,
.archive-title {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #1a1a1a;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-subtitle {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.task-meta-line,
.archive-meta {
  flex-wrap: wrap;
  gap: 5px 8px;
  margin-top: 4px;
  font-size: 11px;
}

/* Archive tags */
.archive-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 5px;
}

.archive-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 19px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid #EBEBEA;
  background: #FAFAF9;
  color: #787774;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

.archive-type-tag.is-import          { border-color: #FDE68A; color: #92400E; background: #FFFDE7; }
.archive-type-tag.is-rj_subtitle     { border-color: #BAE6FD; color: #0E7490; background: #F0FDFE; }
.archive-type-tag.is-subtitle_import { border-color: #DDD6FE; color: #6D28D9; background: #F9F7FF; }
.archive-type-tag.is-asmr_sync       { border-color: #BBF7D0; color: #166534; background: #F0FDF4; }
.archive-type-tag.is-upload          { border-color: #BFDBFE; color: #1D4ED8; background: #EFF6FF; }
.archive-type-tag.is-circle_completion{ border-color: #FED7AA; color: #C2410C; background: #FFF7ED; }
.archive-type-tag.is-system          { border-color: #EBEBEA; color: #787774; background: #FAFAF9; }

.archive-status-tag.is-completed  { border-color: #BBF7D0; color: #166534; background: #F0FDF4; }
.archive-status-tag.is-failed     { border-color: #FECACA; color: #B91C1C; background: #FFF5F5; }
.archive-status-tag.is-processing { border-color: #BFDBFE; color: #1D4ED8; background: #EFF6FF; }
.archive-status-tag.is-pending,
.archive-status-tag.is-unknown    { border-color: #EBEBEA; color: #787774; background: #FAFAF9; }

/* Task chips */
.task-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid #EBEBEA;
  background: #FAFAF9;
  color: #787774;
  font-size: 11px;
  font-weight: 500;
}

.task-chip svg { color: #9B9A97; }

.task-chip.is-rj     { border-color: #FDE68A; color: #92400E; background: #FFFDE7; }
.task-chip.is-rj svg { color: #F59E0B; }

.task-chip.is-step     { border-color: #BFDBFE; color: #1D4ED8; background: #EFF6FF; }
.task-chip.is-step svg { color: #2563EB; }

/* Progress bar */
.task-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  color: #9B9A97;
  font-size: 11px;
}

.task-progress :deep(.el-progress) { flex: 1; }

.task-progress :deep(.el-progress-bar__outer) {
  height: 4px !important;
  border-radius: 999px;
  background: #F3F3F2;
}

.task-progress :deep(.el-progress-bar__inner) {
  border-radius: 999px;
  background: linear-gradient(90deg, #3B82F6 0%, #06B6D4 100%);
}

/* Status pills */
.status-pill,
.archive-rj {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.status-pill.is-processing                       { background: #FFF7ED; color: #C2410C; border-color: #FED7AA; }
.status-pill.is-waiting_manual,
.status-pill.is-waiting_retry                    { background: #FEFCE8; color: #A16207; border-color: #FDE68A; }
.status-pill.is-completed                        { background: #F0FDF4; color: #16A34A; border-color: #BBF7D0; }
.status-pill.is-failed,
.status-pill.is-cancelled                        { background: #FFF5F5; color: #B91C1C; border-color: #FECACA; }
.status-pill.is-pending,
.status-pill.is-paused,
.status-pill.is-default                          { background: #FAFAF9; color: #787774; border-color: #EBEBEA; }

/* Task action buttons */
.task-actions {
  display: flex;
  gap: 4px;
  align-self: flex-start;
}

.icon-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
}

.icon-action.is-cancel,
.icon-action.is-delete_waiting_retry {
  color: #F43F5E;
  background: #FFF5F5;
  border-color: #FECACA;
}

.icon-action.is-retry,
.icon-action.is-retry_waiting,
.icon-action.is-resume,
.icon-action.is-open_subtitle_import {
  color: #2563EB;
  background: #EFF6FF;
  border-color: #BFDBFE;
}

.icon-action.is-pause {
  color: #F59E0B;
  background: #FFFBEB;
  border-color: #FDE68A;
}

/* === Status Section === */
.status-list {
  gap: 6px;
}

.status-row {
  justify-content: space-between;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid #EBEBEA;
  border-radius: 8px;
  color: #37352f;
  background: #fff;
  font-size: 13px;
  font-weight: 500;
}

.status-row-main {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.status-icon {
  color: #9B9A97;
  flex-shrink: 0;
}

.status-row b {
  font-size: 17px;
  font-weight: 700;
  color: #1a1a1a;
  font-variant-numeric: tabular-nums;
}

.status-row.is-processing .status-icon { color: #F59E0B; }
.status-row.is-waiting    .status-icon { color: #8B5CF6; }
.status-row.is-retry      .status-icon { color: #F97316; }
.status-row.is-failed     .status-icon { color: #F43F5E; }

/* === Archive Domain Tabs === */
.archive-domain-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.archive-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid #EBEBEA;
  background: #fff;
  color: #787774;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.12s ease;
}

.archive-tab-btn:hover {
  background: #F7F7F6;
  color: #37352f;
}

.archive-tab-btn.is-active {
  background: #1a1a1a;
  border-color: #1a1a1a;
  color: #fff;
}

.archive-tab-btn.is-active .archive-tab-icon { color: #fff !important; }

.archive-tab-count {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #F3F3F2;
  color: #6A6967;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.archive-tab-btn.is-active .archive-tab-count {
  background: rgba(255, 255, 255, 0.24);
  color: #fff;
}

.archive-tab-icon.is-import          { color: #F59E0B; }
.archive-tab-icon.is-subtitle_import { color: #8B5CF6; }
.archive-tab-icon.is-rj_subtitle     { color: #06B6D4; }
.archive-tab-icon.is-asmr_sync       { color: #10B981; }
.archive-tab-icon.is-upload          { color: #2563EB; }
.archive-tab-icon.is-circle_completion { color: #F97316; }
.archive-tab-icon.is-system          { color: #6B7280; }
.archive-tab-icon.is-all             { color: #9B9A97; }

/* === Archive Section === */
.archive-tools {
  gap: 8px;
  margin-bottom: 10px;
}

.archive-search {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  height: 32px;
  padding: 0 10px;
  border: 1px solid #EBEBEA;
  border-radius: 7px;
  background: #FAFAF9;
  color: #9B9A97;
  transition: border-color 0.15s ease;
}

.archive-search:focus-within {
  border-color: #93C5FD;
  background: #fff;
}

.archive-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: none;
  font-size: 12px;
  color: #1a1a1a;
  background: transparent;
}

.archive-list {
  gap: 0;
}

.archive-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding: 10px 2px;
  border-top: 1px solid #F3F3F2;
}

.archive-row:first-child {
  border-top: 0;
}

.archive-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #FFFFFF;
  color: #9B9A97;
  border: 1px solid #EBEBEA;
}

.archive-icon.is-import { color: #F59E0B; }
.archive-icon.is-rj_subtitle { color: #06B6D4; }
.archive-icon.is-subtitle_import { color: #8B5CF6; }
.archive-icon.is-asmr_sync { color: #10B981; }
.archive-icon.is-upload { color: #2563EB; }
.archive-icon.is-circle_completion { color: #F97316; }
.archive-icon.is-system { color: #6B7280; }

.archive-rj {
  display: inline-flex;
  align-items: center;
  height: 19px;
  padding: 0 6px;
  border-radius: 4px;
  background: #F3F3F2;
  color: #787774;
  font-size: 11px;
  font-weight: 500;
  border: none;
  white-space: nowrap;
}

.archive-footer {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}

.archive-pagination :deep(.el-pagination.is-background .btn-prev),
.archive-pagination :deep(.el-pagination.is-background .btn-next),
.archive-pagination :deep(.el-pagination.is-background .el-pager li) {
  min-width: 26px;
  height: 26px;
  border-radius: 6px;
  border: 1px solid #EBEBEA;
  background: #fff;
  font-size: 12px;
}

.archive-pagination :deep(.el-pagination.is-background .el-pager li.is-active) {
  border-color: #2563EB;
  background: #2563EB;
}

:deep(.el-progress-bar__outer) {
  background: #F3F3F2;
}

:deep(.el-progress-bar__inner) {
  background: linear-gradient(90deg, #2563EB 0%, #06B6D4 100%);
}

@media (max-width: 1280px) {
  .workspace-bar {
    flex-wrap: wrap;
  }

  .command-strip {
    grid-template-columns: 1fr;
  }

  .workspace-title,
  .workspace-actions {
    flex: 0 0 auto;
  }

  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .dashboard-shell {
    padding: 0 12px 22px;
  }

  .workspace-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .workspace-title,
  .workspace-actions,
  .command-btn,
  .command-group,
  .upload-inline {
    width: 100%;
  }

  .command-group {
    justify-content: space-between;
  }

  .workspace-actions {
    justify-content: space-between;
  }

  .workspace-metrics {
    order: initial;
    flex-wrap: wrap;
    overflow: visible;
  }

  .task-row {
    grid-template-columns: 30px minmax(0, 1fr);
  }

  .task-actions {
    grid-column: 1 / -1;
    margin-top: 4px;
  }
}
</style>
