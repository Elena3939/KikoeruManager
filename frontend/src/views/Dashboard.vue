<template>
  <div class="dashboard">
    <section class="overview-top">
      <el-card class="action-card compact-top-card">
        <template #header>
          <div class="card-header">
            <span>快捷操作</span>
          </div>
        </template>
        <div class="action-buttons">
          <el-button
            class="action-button action-button-primary"
            size="large"
            @click="handleManualScan"
            :loading="scanning"
          >
            <el-icon><Search /></el-icon>
            扫描处理
          </el-button>
          <el-button
            class="action-button"
            size="large"
            @click="handleWatcherToggle"
          >
            <el-icon><VideoPlay v-if="!watcherRunning" /><VideoPause v-else /></el-icon>
            {{ watcherRunning ? '停止监视' : '启动监视' }}
          </el-button>
          <el-button
            class="action-button"
            size="large"
            @click="$router.push('/conflicts')"
          >
            <el-icon><Warning /></el-icon>
            问题作品
          </el-button>
        </div>
        <el-divider />
        <FileUploader @upload-success="handleUploadSuccess" />
      </el-card>

      <el-card class="stats-panel" shadow="never">
        <div class="stats-panel-header">
          <span class="stats-panel-title">处理概况</span>
          <span class="stats-panel-subtitle">当前队列与结果摘要</span>
        </div>

        <div class="stats-strip">
          <button type="button" class="stat-chip" @click.stop>
            <span class="stat-chip-icon stat-icon stat-icon-import">
              <el-icon :size="18"><Document /></el-icon>
            </span>
            <span class="stat-chip-body">
              <span class="stat-chip-label">导入处理</span>
              <span class="stat-chip-value">{{ domainCounts.import }}</span>
            </span>
          </button>

          <button type="button" class="stat-chip stat-chip-clickable" @click="$router.push('/library')">
            <span class="stat-chip-icon stat-icon stat-icon-rj-subtitle">
              <el-icon :size="18"><Search /></el-icon>
            </span>
            <span class="stat-chip-body">
              <span class="stat-chip-label">RJ 字幕</span>
              <span class="stat-chip-value">{{ domainCounts.rj_subtitle }}</span>
            </span>
          </button>

          <button type="button" class="stat-chip stat-chip-clickable" @click="$router.push('/subtitle-import')">
            <span class="stat-chip-icon stat-icon stat-icon-subtitle-import">
              <el-icon :size="18"><CircleCheck /></el-icon>
            </span>
            <span class="stat-chip-body">
              <span class="stat-chip-label">字幕补配</span>
              <span class="stat-chip-value">{{ domainCounts.subtitle_import }}</span>
            </span>
          </button>

          <button type="button" class="stat-chip stat-chip-clickable" @click="$router.push('/asmr-sync')">
            <span class="stat-chip-icon stat-icon stat-icon-asmr-sync">
              <el-icon :size="18"><Warning /></el-icon>
            </span>
            <span class="stat-chip-body">
              <span class="stat-chip-label">ASMR 同步</span>
              <span class="stat-chip-value">{{ domainCounts.asmr_sync }}</span>
            </span>
          </button>
        </div>

        <div class="stats-summary">
          <div class="summary-card">
            <span class="summary-label">监视器状态</span>
            <span class="summary-value">{{ watcherRunning ? '运行中' : '已停止' }}</span>
            <span class="summary-meta">
              {{ watcherRunning ? '正在自动监听并处理新进入队列的文件。' : '当前需要你手动触发扫描和处理。' }}
            </span>
          </div>

          <div class="summary-card">
            <span class="summary-label">任务总数</span>
            <span class="summary-value">{{ taskCenterOverview.total || 0 }}</span>
            <span class="summary-meta">任务中心当前聚合到的全部任务项总数。</span>
          </div>
        </div>

        <div class="stats-summary-actions">
          <el-button link @click="$router.push('/tasks')">查看任务队列</el-button>
          <el-button link @click="$router.push('/library')">打开库存管理</el-button>
        </div>
      </el-card>
    </section>

    <!-- 当前任务 -->
    <el-card class="tasks-card">
      <template #header>
        <div class="card-header">
          <span>当前任务</span>
          <el-button link @click="$router.push('/tasks')">查看全部</el-button>
        </div>
      </template>

      <el-table :data="recentTasks" v-app-loading="{ loading, text: '正在加载近期任务...', size: 96 }" style="width: 100%" row-key="id">

        <el-table-column prop="title" label="源文件" show-overflow-tooltip min-width="260">
          <template #default="{ row }">
            <div class="source-file-cell">
              <span class="filename">{{ row.title }}</span>
              <span v-if="row.subtitle" class="task-subline">{{ row.subtitle }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="domain_label" label="类型" width="140">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.domain_label }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="关键信息" min-width="260">
          <template #default="{ row }">
            <div class="task-summary-cell">
              <span v-if="getDashboardRJLabel(row)" class="task-summary-pill">{{ getDashboardRJLabel(row) }}</span>
              <span v-else class="task-summary-empty">-</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="getRowStatusType(row)"
              size="small"
              class="dashboard-status-tag"
              :class="`is-${getRowStatusClass(row)}`"
            >
              {{ getRowStatusLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="progress" label="进度" width="320">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="row.progress"
                :status="getRowProgressStatus(row)"
                :stroke-width="12"
                :show-text="false"
              />
              <span class="progress-label">{{ row.current_step }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="220" fixed="right" align="center">
          <template #default="{ row }">
            <div class="task-action-group">
              <el-button
                v-for="action in row.actions || []"
                :key="`${row.id}-${action}`"
                size="small"
                class="task-action-btn"
                :class="`is-${action}`"
                :type="getDashboardActionType(action)"
                :plain="action !== 'cancel'"
                @click="handleTaskCenterAction(row, action)"
              >
                {{ getActionLabel(action) }}
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 已处理压缩包 -->
    <el-card class="archives-card">
      <template #header>
        <div class="card-header">
          <span>已处理压缩包</span>
          <div class="archives-header-actions">
            <!-- 搜索框 -->
            <el-input
              v-model="archiveSearchQuery"
              placeholder="搜索RJ号或文件名"
              style="width: 200px; margin-right: 12px;"
              clearable
              @input="handleArchiveSearch"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>

            <!-- 排序选择器 -->
            <el-select v-model="archiveSortBy" style="width: 140px; margin-right: 8px;" @change="handleArchiveSortChange">
              <el-option label="处理时间" value="processed_at" />
              <el-option label="RJ号" value="rjcode" />
              <el-option label="文件大小" value="file_size" />
              <el-option label="处理次数" value="process_count" />
              <el-option label="状态" value="status" />
            </el-select>

            <!-- 排序方向 -->
            <el-button
              link
              @click="toggleArchiveSortOrder"
              :title="archiveSortOrder === 'desc' ? '降序' : '升序'"
            >
              <el-icon>
                <SortDown v-if="archiveSortOrder === 'desc'" />
                <SortUp v-else />
              </el-icon>
            </el-button>

            <el-button link @click="fetchProcessedArchives" :loading="archivesLoading">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button link @click="showAllArchives = !showAllArchives">
              {{ showAllArchives ? '收起' : '查看全部' }}
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="displayedArchives"
        v-app-loading="{ loading: archivesLoading, text: '正在加载最近入库...', size: 124 }"
        style="width: 100%"
        row-key="id"
      >
        <template #empty>
          <AppEmptyState description="暂无已处理压缩包" size="default" />
        </template>
        <el-table-column type="expand" width="40" v-if="displayedArchives.some(a => a.isVolumeGroup)">
          <template #default="{ row }">
            <div v-if="row.isVolumeGroup && row.volumes" class="volume-list">
              <div class="volume-list-title">分卷文件列表：</div>
              <div v-for="(vol, idx) in row.volumes" :key="idx" class="volume-item">
                <span class="volume-name">{{ vol.filename }}</span>
                <span class="volume-size">{{ formatFileSize(vol.file_size) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="rjcode" label="RJ号" width="120">
          <template #default="{ row }">
            <el-tag type="primary" size="small" v-if="row.rjcode">{{ row.rjcode }}</el-tag>
            <span v-else class="text-gray">-</span>
          </template>
        </el-table-column>

        <el-table-column prop="filename" label="文件名" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.filename }}
            <el-tag v-if="row.isVolumeGroup" type="warning" size="small" class="volume-tag">
              {{ row.volumes.length }}个分卷
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="file_size" label="大小" width="120">
          <template #default="{ row }">
            {{ formatFileSize(row.file_size) }}
          </template>
        </el-table-column>

        <el-table-column prop="process_count" label="处理次数" width="120">
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ row.process_count || 1 }} 次</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="processed_at" label="处理时间" width="220">
          <template #default="{ row }">
            <span class="time-text">{{ formatDate(row.processed_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'completed' ? 'success' : (row.status === 'reprocessing' ? 'warning' : 'info')"
              size="small"
            >
              {{ row.status === 'completed' ? '已完成' : (row.status === 'reprocessing' ? '重新处理中' : '处理中') }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="120" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              @click="reprocessArchive(row.id)"
              :loading="reprocessingId === row.id"
            >
              重新解压
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onActivated, onDeactivated, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Document, CircleCheck, CircleCheckFilled, Warning, Search, VideoPlay, VideoPause, Refresh, SortDown, SortUp } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { conflictApi, scanApi, watcherApi, processedArchiveApi, taskCenterApi } from '../api'
import FileUploader from '../components/FileUploader.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'

const router = useRouter()
const loading = ref(false)
const scanning = ref(false)
const watcherRunning = ref(false)
const dashboardTaskItems = ref([])
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
const domainCounts = computed(() => ({
  import: Number(taskCenterOverview.value?.counts_by_domain?.import || 0),
  rj_subtitle: Number(taskCenterOverview.value?.counts_by_domain?.rj_subtitle || 0),
  subtitle_import: Number(taskCenterOverview.value?.counts_by_domain?.subtitle_import || 0),
  asmr_sync: Number(taskCenterOverview.value?.counts_by_domain?.asmr_sync || 0)
}))
const dashboardActiveStatuses = new Set(['processing', 'pending', 'paused', 'waiting_manual', 'waiting_retry'])
const dashboardDomains = ['import', 'rj_subtitle', 'subtitle_import', 'asmr_sync', 'system']

function getFileName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

const recentTasks = computed(() => {
  const taskItems = Array.isArray(dashboardTaskItems.value) ? dashboardTaskItems.value : []
  const activeItems = taskItems.filter(item => dashboardActiveStatuses.has(String(item?.status || '').trim()))
  return activeItems.length ? activeItems.slice(0, 6) : taskItems.slice(0, 5)
})

function buildDashboardOverview(taskItems) {
  const countsByDomain = Object.fromEntries(dashboardDomains.map((key) => [key, 0]))
  const countsByStatus = {
    pending: 0,
    processing: 0,
    paused: 0,
    waiting_manual: 0,
    waiting_retry: 0,
    completed: 0,
    failed: 0
  }

  for (const item of taskItems) {
    const domain = String(item?.domain || '').trim()
    const status = String(item?.status || '').trim()
    if (domain in countsByDomain) countsByDomain[domain] += 1
    if (status in countsByStatus) countsByStatus[status] += 1
  }

  const activeItems = taskItems.filter(item => dashboardActiveStatuses.has(String(item?.status || '').trim()))
  return {
    total: taskItems.length,
    recent_items: taskItems.slice(0, 5),
    active_items: activeItems.slice(0, 6),
    counts_by_domain: countsByDomain,
    counts_by_status: countsByStatus,
    highlight_counts: {
      processing: countsByStatus.processing,
      waiting_manual: countsByStatus.waiting_manual,
      waiting_retry: countsByStatus.waiting_retry,
      failed: countsByStatus.failed
    }
  }
}

// 已处理压缩包相关
const archives = ref([])
const archivesLoading = ref(false)
const reprocessingId = ref(null)
const showAllArchives = ref(false)
const archiveSearchQuery = ref('')
const archiveSortBy = ref('processed_at')
const archiveSortOrder = ref('desc')
let archiveSearchTimeout = null

// 合并分卷压缩包组
const groupedArchives = computed(() => {
  const groups = new Map()
  const singles = []

  archives.value.forEach(archive => {
    const filename = archive.filename
    // 检查是否是分卷压缩包（支持 .part1.rar, .part2.rar, .part1.exe 等）
    const volumeMatch = filename.match(/^(.*)\.part(\d+)\.(rar|zip|7z|exe)$/i)

    if (volumeMatch) {
      // 提取基础组名（如：RJ01207739，不包含 .part 和扩展名）
      const baseName = volumeMatch[1]
      const groupKey = baseName + '_volume_group'

      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          id: archive.id,
          rjcode: archive.rjcode,
          filename: baseName + '（分卷组）',
          originalFilename: filename,
          file_size: 0,
          process_count: archive.process_count || 1,
          processed_at: archive.processed_at || new Date(0).toISOString(),
          status: archive.status,
          isVolumeGroup: true,
          groupKey: groupKey,
          volumes: []
        })
      }

      const group = groups.get(groupKey)
      group.volumes.push(archive)
      group.file_size += (archive.file_size || 0)

      // 使用最新的处理时间和状态（使用 Date 对象比较，避免字符串比较问题）
      const archiveTime = archive.processed_at ? new Date(archive.processed_at).getTime() : 0
      const groupTime = group.processed_at ? new Date(group.processed_at).getTime() : 0
      if (archiveTime > groupTime) {
        group.processed_at = archive.processed_at
        // 同时更新状态为最新的状态
        group.status = archive.status
        group.process_count = archive.process_count || 1
      }
      // 优先使用 part1 作为组的ID
      if (filename.toLowerCase().includes('.part1.')) {
        group.id = archive.id
      }
      // 如果没有 part1，使用第一个作为ID
      if (!group.id) {
        group.id = archive.id
      }
    } else {
      // 非分卷文件，直接添加
      singles.push({
        ...archive,
        isVolumeGroup: false
      })
    }
  })

  // 合并组和非分卷文件
  const result = [...groups.values(), ...singles]

  // 按处理时间排序（降序，最新的在前）
  result.sort((a, b) => {
    const timeA = a.processed_at ? new Date(a.processed_at).getTime() : 0
    const timeB = b.processed_at ? new Date(b.processed_at).getTime() : 0
    return timeB - timeA
  })

  return result
})

// 显示的归档列表（根据showAllArchives控制数量）
const displayedArchives = computed(() => {
  if (showAllArchives.value) {
    return groupedArchives.value
  }
  return groupedArchives.value.slice(0, 5)
})

let intervalId
let dashboardInitialized = false
let dashboardViewActive = false
let refreshRunning = false
let refreshPending = false
let refreshRequestId = 0
let visibilityBound = false

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

let previousCompletedCount = 0
let lastRefreshTime = 0

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

function handleDashboardVisibilityRefresh() {
  if (!dashboardViewActive) return
  if (document.visibilityState === 'hidden') return
  refreshData({ silent: true })
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

async function initializeDashboardPage() {
  if (dashboardInitialized) return
  await refreshDashboardOnResume(false)
  dashboardInitialized = true
}

async function refreshDashboardOnResume(silent = true) {
  await refreshData({ silent })
  await fetchWatcherStatus()
  await fetchProcessedArchivesSilently()
}

async function refreshData(options = {}) {
  const { silent = false } = options
  if (refreshRunning) {
    refreshPending = true
    return
  }

  refreshRunning = true
  const currentRequestId = ++refreshRequestId
  if (!silent) {
    loading.value = true
  }

  try {
    const cacheBust = Date.now()
    const listData = await taskCenterApi.list({ limit: 300, _t: cacheBust })
    if (currentRequestId !== refreshRequestId) {
      return
    }
    const taskItems = Array.isArray(listData) ? listData : []
    dashboardTaskItems.value = taskItems
    const derivedOverview = buildDashboardOverview(taskItems)
    taskCenterOverview.value = derivedOverview

    // 获取当前完成的任务数
    const currentCompletedCount = Number(derivedOverview?.counts_by_status?.completed || 0)

    // 如果完成的任务数增加了，或者距离上次刷新已处理压缩包已超过30秒，则刷新
    const now = Date.now()
    const shouldRefreshArchives =
      currentCompletedCount > previousCompletedCount ||
      (now - lastRefreshTime > 30000 && recentTasks.value.length > 0)

    if (shouldRefreshArchives) {
      console.log('检测到任务状态变化，刷新已处理压缩包列表')
      await fetchProcessedArchivesSilently()
      lastRefreshTime = now
    }

    previousCompletedCount = currentCompletedCount

    // 获取问题作品数量
    let conflictCount = 0
    try {
      const data = await conflictApi.list()
      conflictCount = data.conflicts?.length || 0
    } catch (error) {
      console.error('获取问题作品数量失败:', error)
    }

    stats.value = {
      pending: Number(derivedOverview?.counts_by_status?.pending || 0),
      processing: Number(derivedOverview?.counts_by_status?.processing || 0),
      completed: Number(derivedOverview?.counts_by_status?.completed || 0),
      conflicts: conflictCount
    }
  } catch (error) {
    console.error('获取任务中心概览失败:', error)
    dashboardTaskItems.value = []
    taskCenterOverview.value = {
      recent_items: [],
      active_items: [],
      counts_by_domain: {},
      counts_by_status: {},
      highlight_counts: {},
      total: 0
    }
  } finally {
    refreshRunning = false
    if (!silent) {
      loading.value = false
    }
    if (refreshPending) {
      refreshPending = false
      refreshData({ silent: true })
    }
  }
}

function getTaskTypeLabel(type) {
  const labels = {
    'auto_process': '自动处理',
    'extract': '解压',
    'filter': '过滤',
    'metadata': '元数据',
    'rename': '重命名'
  }
  return labels[type] || type
}

function getStatusLabel(status) {
  const labels = {
    'pending': '等待中',
    'processing': '处理中',
    'paused': '已暂停',
    'waiting_manual': '等待手动处理',
    'waiting_retry': '等待重试',
    'completed': '已完成',
    'failed': '失败',
    'cancelled': '已取消',
    'canceled': '已取消'
  }
  return labels[status] || status
}

function getStatusType(status) {
  const types = {
    'pending': 'info',
    'processing': 'warning',
    'paused': '',
    'waiting_manual': 'warning',
    'waiting_retry': 'danger',
    'completed': 'success',
    'failed': 'danger',
    'cancelled': 'info',
    'canceled': 'info'
  }
  return types[status] || ''
}

function isCancelledTask(row) {
  if (!row) return false
  if (row.status === 'cancelled' || row.status === 'canceled') return true
  if (row.error_message === '用户取消') return true
  const metadata = row?.details?.metadata || {}
  return Boolean(metadata.is_cancelled || metadata.cancelled || metadata.canceled)
}

function getRowStatusLabel(row) {
  if (isCancelledTask(row)) return '已取消'
  return row?.status_label || getStatusLabel(row?.status)
}

function getRowStatusType(row) {
  if (isCancelledTask(row)) return getStatusType('cancelled')
  return getStatusType(row?.status)
}

function getRowStatusClass(row) {
  if (isCancelledTask(row)) return 'cancelled'
  return String(row?.status || '').trim() || 'default'
}

function pickMetricValue(row, label) {
  const metrics = Array.isArray(row?.metrics) ? row.metrics : []
  return metrics.find(metric => metric?.label === label)?.value || ''
}

function getDashboardRJLabel(row) {
  const rjcode = String(row?.rjcode || '').trim().toUpperCase()
  return rjcode || ''
}

function getRecoveredNotice(row) {
  const details = row?.details || {}
  const metadata = details.metadata || {}
  return String(metadata.recovered_notice || '').trim()
}

function getRowProgressStatus(row) {
  if (isCancelledTask(row) || row?.status === 'failed' || row?.status === 'waiting_retry') return 'exception'
  if (row?.status === 'completed') return 'success'
  return ''
}

async function pauseTask(taskId) {
  await taskCenterApi.action(taskId, 'pause')
}

async function resumeTask(taskId) {
  await taskCenterApi.action(taskId, 'resume')
}

async function cancelTask(taskId) {
  await taskCenterApi.action(taskId, 'cancel')
}

function handleUploadSuccess() {
  refreshData()
}

async function handleManualScan() {
  scanning.value = true
  try {
    ElMessage.info('正在扫描文件夹...')
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
      ElMessage.success('监视器已停止')
      watcherRunning.value = false
    } else {
      await watcherApi.start()
      ElMessage.success('监视器已启动')
      watcherRunning.value = true
    }
  } catch (error) {
    console.error('操作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function getActionLabel(action) {
  const labels = {
    pause: '暂停',
    resume: '恢复',
    cancel: '取消',
    retry: '重试',
    retry_waiting: '重试',
    delete_waiting_retry: '移除',
    open_subtitle_import: '前往处理'
  }
  return labels[action] || action
}

function getDashboardActionType(action) {
  const types = {
    pause: 'warning',
    resume: 'primary',
    cancel: 'danger',
    retry: 'primary',
    retry_waiting: 'primary',
    delete_waiting_retry: 'danger',
    open_subtitle_import: 'primary'
  }
  return types[action] || 'info'
}

async function handleTaskCenterAction(row, action) {
  try {
    const result = await taskCenterApi.action(row.id, action)
    if (result?.route_hint) {
      await router.push(result.route_hint)
    }
    ElMessage.success(result?.message || '操作成功')
    await refreshData()
  } catch (error) {
    console.error('执行任务中心动作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function fetchWatcherStatus() {
  try {
    const data = await watcherApi.status()
    watcherRunning.value = data.is_running
  } catch (error) {
    console.error('获取监视器状态失败:', error)
  }
}

// 获取已处理压缩包列表
async function fetchProcessedArchives(options = {}) {
  const { silent = false } = options
  archivesLoading.value = true
  try {
    await processedArchiveApi.scan()
    const params = {
      sort_by: archiveSortBy.value,
      sort_order: archiveSortOrder.value
    }
    if (archiveSearchQuery.value) {
      params.search = archiveSearchQuery.value
    }
    const data = await processedArchiveApi.list(params)
    archives.value = data.archives || []
    console.log('获取到已处理压缩包:', archives.value.length, '条记录')
    if (archives.value.length > 0) {
      console.log('第一条记录:', archives.value[0].filename, '时间:', archives.value[0].processed_at)
    }
    ElMessage.success('刷新成功')
  } catch (error) {
    console.error('获取已处理压缩包列表失败:', error)
    ElMessage.error('获取已处理压缩包列表失败')
  } finally {
    archivesLoading.value = false
  }
}

// 处理搜索输入（防抖）
function handleArchiveSearch() {
  if (archiveSearchTimeout) {
    clearTimeout(archiveSearchTimeout)
  }
  archiveSearchTimeout = setTimeout(() => {
    fetchProcessedArchives()
  }, 500)
}

// 处理排序字段变化
function handleArchiveSortChange() {
  fetchProcessedArchives()
}

// 切换排序方向
function toggleArchiveSortOrder() {
  archiveSortOrder.value = archiveSortOrder.value === 'desc' ? 'asc' : 'desc'
  fetchProcessedArchives()
}

// 重新处理压缩包
async function fetchProcessedArchivesSilently() {
  try {
    await processedArchiveApi.scan()
    const params = {
      sort_by: archiveSortBy.value,
      sort_order: archiveSortOrder.value
    }
    if (archiveSearchQuery.value) {
      params.search = archiveSearchQuery.value
    }
    const data = await processedArchiveApi.list(params)
    archives.value = data.archives || []
  } catch (error) {
    console.error('Silent refresh of processed archives failed:', error)
  }
}

async function reprocessArchive(archiveId) {
  reprocessingId.value = archiveId
  try {
    const data = await processedArchiveApi.reprocess(archiveId)
    ElMessage.success(data.message)
    await refreshData()
    await fetchProcessedArchives()
  } catch (error) {
    console.error('重新处理失败:', error)
    ElMessage.error('重新处理失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    reprocessingId.value = null
  }
}

// 格式化文件大小
function formatFileSize(bytes) {
  if (bytes === 0 || !bytes) return '-'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 格式化日期
function formatDate(dateString) {
  if (!dateString) return '-'
  // 处理不同的日期格式
  let date
  if (typeof dateString === 'string') {
    if (dateString.includes('T')) {
      // 如果是ISO 8601格式，它是UTC时间，添加'Z'以正确解析为本地时间
      date = new Date(dateString + 'Z')
    } else {
      date = new Date(dateString)
    }
  } else {
    date = new Date(dateString)
  }
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}
</script>

<style scoped>
.dashboard {
  --apple-blue: #0071e3;
  --apple-link-blue: #0066cc;
  --apple-bg: #f5f5f7;
  --apple-surface: #ffffff;
  --apple-text: #1d1d1f;
  --apple-muted: rgba(29, 29, 31, 0.68);
  --apple-subtle: rgba(29, 29, 31, 0.4);
  --apple-line: rgba(29, 29, 31, 0.08);
  --apple-shadow: 0 18px 44px rgba(0, 0, 0, 0.08);
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 8px 28px;
  color: var(--apple-text);
}

.overview-top {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.9fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stats-grid {
  display: block;
}

.stats-panel {
  border: none;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: var(--apple-shadow);
  backdrop-filter: blur(18px);
}

.stats-panel :deep(.el-card__body) {
  padding: 18px 20px 20px;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.stats-panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.stats-panel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--apple-text);
}

.stats-panel-subtitle {
  font-size: 12px;
  color: var(--apple-muted);
}

.stats-strip {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stats-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  min-height: 92px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, #fcfcfd 0%, #f4f4f7 100%);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
}

.summary-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(29, 29, 31, 0.46);
}

.summary-value {
  margin-top: 8px;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--apple-text);
}

.summary-meta {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--apple-muted);
}

.stats-summary-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: auto;
  padding-top: 14px;
}

.stat-chip {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 82px;
  padding: 14px 16px;
  border: 0;
  border-radius: 18px;
  background: #f7f7fa;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
  text-align: left;
}

.stat-chip-clickable {
  cursor: pointer;
  transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
}

.stat-chip-clickable:hover {
  transform: translateY(-1px);
  background: #f0f6ff;
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.08);
}

.stat-chip-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.stat-chip-label {
  font-size: 13px;
  color: var(--apple-muted);
}

.stat-chip-value {
  font-size: 28px;
  font-weight: 600;
  line-height: 1;
  color: var(--apple-text);
}

.stat-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--apple-text);
  flex-shrink: 0;
  background: #f2f2f4;
}

.stat-icon-import {
  background: #f2f6ff;
  color: var(--apple-link-blue);
}

.stat-icon-rj-subtitle {
  background: #eef7ff;
  color: #0c76c5;
}

.stat-icon-subtitle-import {
  background: #f4f0ff;
  color: #6952d6;
}

.stat-icon-asmr-sync {
  background: #fff3ec;
  color: #c7651a;
}

.upload-card {
  margin-bottom: 24px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 28px;
}

.card-header > span {
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.18px;
  color: var(--apple-text);
}

.task-id {
  font-family: monospace;
  color: var(--apple-muted);
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.progress-cell :deep(.el-progress) {
  flex: 1;
  margin-bottom: 0;
  max-width: 100px;
}

.progress-label {
  font-size: 13px;
  color: var(--apple-muted);
  white-space: nowrap;
  min-width: 40px;
}

.source-file-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  overflow: hidden;
}

.recovered-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.16), rgba(134, 239, 172, 0.22));
  box-shadow: inset 0 0 0 1px rgba(34, 197, 94, 0.18);
  color: #166534;
}

.recovered-banner-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.76);
  color: #16a34a;
  flex-shrink: 0;
}

.recovered-banner-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.recovered-banner-title {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
}

.recovered-banner-text {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  white-space: normal;
}

.filename {
  color: var(--apple-text);
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-subline {
  max-width: 100%;
  font-size: 12px;
  color: var(--apple-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-summary-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.task-summary-pill {
  display: inline-flex;
  max-width: 100%;
  padding: 5px 10px;
  border-radius: 999px;
  background: #f4f4f7;
  color: rgba(29, 29, 31, 0.72);
  font-size: 12px;
  line-height: 1.4;
}

.task-summary-empty {
  font-size: 13px;
  color: var(--apple-subtle);
}

.task-action-group {
  display: flex;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  width: 100%;
  max-width: 160px;
  margin: 0 auto;
}

.task-action-btn {
  min-width: 76px;
  height: 28px;
  margin: 0;
  padding: 0 10px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  line-height: 28px;
  box-shadow: none;
}

.task-action-btn:deep(span) {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  width: 100%;
}

.task-action-btn.is-pause,
.task-action-btn.is-resume,
.task-action-btn.is-retry,
.task-action-btn.is-open_subtitle_import,
.task-action-btn.is-retry_waiting {
  background: #5aa7ff;
  color: #fff;
}

.task-action-btn.is-cancel,
.task-action-btn.is-delete_waiting_retry {
  background: #ff7875;
  color: #fff;
}

.task-action-btn:hover,
.task-action-btn:focus {
  opacity: 0.92;
  transform: none;
}

.task-id {
  font-family: monospace;
  color: var(--apple-muted);
  white-space: nowrap;
}

.action-card,
.tasks-card,
.archives-card {
  margin-bottom: 24px;
  border: none;
  border-radius: 28px;
  background: var(--apple-surface);
  box-shadow: var(--apple-shadow);
}

.compact-top-card {
  height: 100%;
}

.action-card :deep(.el-card__header),
.tasks-card :deep(.el-card__header),
.archives-card :deep(.el-card__header) {
  padding: 24px 28px 0;
  border-bottom: none;
}

.action-card :deep(.el-card__body),
.tasks-card :deep(.el-card__body),
.archives-card :deep(.el-card__body) {
  padding: 20px 28px 28px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.action-button {
  min-width: 132px;
  height: 40px;
  padding: 0 16px;
  border: 1px solid var(--apple-line);
  border-radius: 999px;
  background: #fafafc;
  color: var(--apple-text);
  font-size: 14px;
  box-shadow: none;
}

.action-button:hover,
.action-button:focus {
  color: var(--apple-text);
  border-color: rgba(29, 29, 31, 0.12);
  background: #f1f1f3;
}

.action-button-primary {
  border-color: transparent;
  background: var(--apple-blue);
  color: #fff;
}

.action-button-primary:hover,
.action-button-primary:focus {
  color: #fff;
  background: #0077ed;
}

.action-buttons .el-icon {
  margin-right: 8px;
}

.archives-card {
  margin-top: 24px;
}

.archives-card .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.archives-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.archives-card .el-button-group {
  margin-left: 8px;
}

.text-gray {
  color: var(--apple-subtle);
}

.volume-tag {
  margin-left: 8px;
}

.volume-list {
  padding: 16px 20px;
  background-color: var(--apple-bg);
  border-radius: 18px;
  margin: 8px 0;
}

.volume-list-title {
  font-weight: 600;
  color: var(--apple-text);
  margin-bottom: 8px;
  font-size: 13px;
}

.time-text {
  font-size: 12px;
  color: var(--apple-muted);
  font-family: 'Consolas', 'Monaco', monospace;
}

.volume-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 12px;
  margin: 4px 0;
  background-color: white;
  border-radius: 12px;
  font-size: 13px;
}

.volume-name {
  color: var(--apple-text);
  font-family: 'Consolas', 'Monaco', monospace;
}

.volume-size {
  color: var(--apple-muted);
  font-size: 12px;
}

:deep(.el-table__expand-icon) {
  color: var(--apple-link-blue);
}

:deep(.el-divider) {
  margin: 0 0 18px;
  border-color: var(--apple-line);
}

:deep(.el-table) {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: #fbfbfd;
  --el-table-row-hover-bg-color: #f7f7f9;
  --el-table-text-color: var(--apple-text);
  --el-table-header-text-color: rgba(29, 29, 31, 0.76);
  border-radius: 20px;
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  font-weight: 600;
}

:deep(.el-table td.el-table__cell),
:deep(.el-table th.el-table__cell) {
  padding-top: 15px;
  padding-bottom: 15px;
}

:deep(.el-progress-bar__outer) {
  background: #e9e9ed;
}

:deep(.el-progress-bar__inner) {
  background: linear-gradient(90deg, #0071e3 0%, #2a8cff 100%);
}

:deep(.el-button.is-link) {
  color: var(--apple-link-blue);
  font-weight: 500;
}

:deep(.el-button.is-link:hover) {
  color: var(--apple-blue);
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  border-radius: 14px;
  box-shadow: 0 0 0 1px rgba(29, 29, 31, 0.08) inset;
}

:deep(.el-tag) {
  border-radius: 999px;
  font-weight: 500;
}

:deep(.dashboard-status-tag.el-tag) {
  height: 24px;
  padding: 0 10px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
  line-height: 22px;
  letter-spacing: 0.01em;
}

:deep(.dashboard-status-tag.is-completed.el-tag) {
  color: #2f7d32;
  background: linear-gradient(180deg, #eef9ef 0%, #e4f6e6 100%);
  border-color: #c8ebcf;
}

:deep(.dashboard-status-tag.is-processing.el-tag) {
  color: #b86a00;
  background: linear-gradient(180deg, #fff6e8 0%, #ffedd2 100%);
  border-color: #ffd7a0;
}

:deep(.dashboard-status-tag.is-pending.el-tag),
:deep(.dashboard-status-tag.is-paused.el-tag) {
  color: #51606f;
  background: linear-gradient(180deg, #f4f6f8 0%, #eceff3 100%);
  border-color: #dde3ea;
}

:deep(.dashboard-status-tag.is-waiting_manual.el-tag),
:deep(.dashboard-status-tag.is-waiting_retry.el-tag) {
  color: #8f5a17;
  background: linear-gradient(180deg, #fff5df 0%, #ffe8bf 100%);
  border-color: #f3d39a;
}

:deep(.dashboard-status-tag.is-failed.el-tag),
:deep(.dashboard-status-tag.is-cancelled.el-tag) {
  color: #a63f3f;
  background: linear-gradient(180deg, #fff0f0 0%, #ffe3e3 100%);
  border-color: #f3c4c4;
}

@media (max-width: 1200px) {
  .overview-top {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .dashboard {
    padding: 0 0 20px;
  }

  .stats-grid {
    width: 100%;
  }

  .stats-strip {
    grid-template-columns: 1fr;
  }

  .stats-summary {
    grid-template-columns: 1fr;
  }

  .card-header,
  .archives-card .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .archives-header-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .action-buttons {
    gap: 12px;
  }

  .action-button {
    width: 100%;
  }
}
</style>
