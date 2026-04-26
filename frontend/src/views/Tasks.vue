<template>
  <div class="task-center-shell">
    <header class="workspace-bar">
      <div class="workspace-title-wrap">
        <ListChecks :size="18" :stroke-width="2.3" class="workspace-title-icon" />
        <div class="workspace-title-content">
          <h1 class="workspace-title">任务中心</h1>
          <p class="workspace-subtitle">导入处理、RJ 字幕、字幕补配、ASMR 同步与系统任务的统一视图</p>
        </div>
      </div>
      <button
        type="button"
        class="dash-btn"
        :disabled="loading"
        @click="refreshTaskCenter(true)"
      >
        <RefreshCw :size="14" :stroke-width="2.3" :class="{ 'spin': loading }" />
        刷新
      </button>
      <button
        type="button"
        class="dash-btn"
        :class="{ 'is-active': pollingEnabled }"
        @click="pollingEnabled = !pollingEnabled"
      >
        <Activity :size="14" :stroke-width="2.3" />
        {{ pollingEnabled ? '轮询中' : '轮询暂停' }}
      </button>
    </header>

    <section class="workspace-metrics-panel">
      <button
        v-for="metric in metricsPanel"
        :key="metric.key"
        type="button"
        class="metric-pill"
        :class="`is-${metric.key}`"
        @click="metric.click"
      >
        <component :is="metric.icon" :size="13" :stroke-width="2.3" />
        <span>{{ metric.label }}</span>
        <b>{{ metric.value }}</b>
      </button>
    </section>

    <section class="filters-panel">
      <div class="filters-group">
        <span class="filters-label">任务类型</span>
        <div class="filters-row">
          <button
            v-for="option in domainOptions"
            :key="option.value"
            type="button"
            class="filter-chip"
            :class="[{ active: currentDomain === option.value }, `is-${option.value}`]"
            @click="currentDomain = option.value"
          >
            <component :is="option.icon" :size="11" :stroke-width="2.3" />
            <span>{{ option.label }}</span>
            <span v-if="option.value !== 'all' && getDomainCount(option.value)" class="chip-count">{{ getDomainCount(option.value) }}</span>
          </button>
        </div>
      </div>

      <div class="filters-group">
        <span class="filters-label">任务状态</span>
        <div class="filters-row">
          <button
            v-for="option in statusOptions"
            :key="option.value"
            type="button"
            class="filter-chip"
            :class="[{ active: currentStatus === option.value }, `is-${option.value}`]"
            @click="currentStatus = option.value"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <div class="search-wrap">
        <Search :size="13" :stroke-width="2.3" class="search-icon" />
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索标题、RJ、路径、当前步骤"
        >
        <button v-if="searchQuery" type="button" class="search-clear" @click="searchQuery = ''">
          <X :size="12" :stroke-width="2.3" />
        </button>
      </div>

      <div class="filters-tools-row">
        <label class="tools-label" for="task-sort-select">排序</label>
        <select id="task-sort-select" v-model="sortKey" class="tools-select">
          <option value="updated_desc">最近更新优先</option>
          <option value="created_desc">最近创建优先</option>
          <option value="progress_desc">进度高优先</option>
          <option value="status_priority">状态优先级</option>
        </select>

        <button type="button" class="dash-btn" :class="{ 'is-active': activeOnly }" @click="activeOnly = !activeOnly">
          {{ activeOnly ? '仅活跃' : '全部任务' }}
        </button>
        <button type="button" class="dash-btn" @click="resetFilters">重置筛选</button>
      </div>
    </section>

    <section class="task-center-layout">
      <div class="pane task-list-pane">
        <div class="pane-head">
          <span class="pane-title">任务列表</span>
          <span class="pane-count">{{ totalItems }} 项</span>
        </div>

        <div class="pane-subhead">
          <span class="mini-kpi">当前页 {{ filteredItems.length }}</span>
          <span class="mini-kpi is-active">活跃 {{ listDigest.active }}</span>
          <span class="mini-kpi is-done">完成 {{ listDigest.completed }}</span>
          <span class="mini-kpi is-failed">失败 {{ listDigest.failed }}</span>
        </div>

        <div v-if="filteredItems.length" class="task-list">
          <button
            v-for="item in filteredItems"
            :key="item.id"
            type="button"
            class="task-row"
            :class="[`is-${item.domain || 'system'}`, { active: selectedItem?.id === item.id }]"
            @click="selectedItemId = item.id"
          >
            <span class="task-icon">
              <component :is="domainMeta(item.domain).icon" :size="14" :stroke-width="2.3" />
            </span>

            <div class="task-main">
              <div class="task-main-head">
                <span class="task-title">{{ item.title }}</span>
                <span class="status-pill" :class="`is-${item.status}`">{{ item.status_label }}</span>
              </div>

              <p v-if="item.subtitle" class="task-subtitle">{{ item.subtitle }}</p>

              <div class="task-chip-row">
                <span class="task-chip task-chip-domain" :class="`is-${item.domain}`">{{ item.domain_label }}</span>
                <span v-if="item.source_label" class="task-chip">{{ item.source_label }}</span>
                <span v-if="shouldShowTaskMetaStep(item)" class="task-chip is-step">
                  <Activity :size="11" :stroke-width="2.3" />
                  {{ item.current_step }}
                </span>
                <span v-if="formatRJCode(item.rjcode)" class="task-chip is-rj">
                  <FileArchive :size="11" :stroke-width="2.3" />
                  {{ formatRJCode(item.rjcode) }}
                </span>
              </div>

              <div v-if="showProgress(item)" class="task-progress-row">
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${item.progress}%` }"></div>
                </div>
                <span class="progress-text">{{ item.progress }}%</span>
              </div>

              <div v-if="getRecoveredNotice(item)" class="task-recovered">
                <CheckCircle :size="12" :stroke-width="2.3" />
                {{ getRecoveredNotice(item) }}
              </div>

              <div v-if="getTaskSummary(item).length" class="task-summary-row">
                <span
                  v-for="(piece, index) in getTaskSummary(item)"
                  :key="`${item.id}-summary-${index}`"
                  class="metric-pill mini"
                >
                  {{ piece }}
                </span>
              </div>
            </div>
          </button>
        </div>

        <div v-else class="task-empty-workbench">
          <AppEmptyState description="当前筛选条件下没有任务" size="default" />
          <div class="empty-actions">
            <button type="button" class="dash-btn" @click="applyQuickFilter('all', 'all')">查看全部</button>
            <button type="button" class="dash-btn" @click="applyQuickFilter('rj_subtitle', 'processing')">查看 RJ 处理中</button>
            <button type="button" class="dash-btn" @click="applyQuickFilter('circle_completion', 'waiting_manual')">查看待人工任务</button>
          </div>
          <div class="empty-tips">
            <span class="task-chip">当前域：{{ domainOptions.find((d) => d.value === currentDomain)?.label || '全部' }}</span>
            <span class="task-chip">当前状态：{{ statusOptions.find((s) => s.value === currentStatus)?.label || '全部状态' }}</span>
            <span v-if="debouncedSearchQuery" class="task-chip">关键词：{{ debouncedSearchQuery }}</span>
          </div>
        </div>

        <div v-if="totalItems > pageSize" class="task-pagination">
          <button
            type="button"
            class="pager-btn"
            :disabled="currentOffset <= 0"
            @click="currentOffset = Math.max(0, currentOffset - pageSize); refreshTaskCenter(false, { silent: true })"
          >
            <ChevronLeft :size="14" :stroke-width="2.3" />
          </button>
          <span class="pager-text">{{ Math.floor(currentOffset / pageSize) + 1 }} / {{ Math.ceil(totalItems / pageSize) }}</span>
          <button
            type="button"
            class="pager-btn"
            :disabled="currentOffset + pageSize >= totalItems"
            @click="currentOffset += pageSize; refreshTaskCenter(false, { silent: true })"
          >
            <ChevronRight :size="14" :stroke-width="2.3" />
          </button>
        </div>
      </div>

      <div class="pane task-detail-pane">
        <div class="pane-head">
          <span class="pane-title">任务详情</span>
          <button
            v-if="selectedItem?.route_hint"
            type="button"
            class="command-btn"
            @click="openTaskRoute(selectedItem)"
          >
            <ArrowRight :size="13" :stroke-width="2.3" />
            打开关联页面
          </button>
        </div>

        <template v-if="selectedItem">
          <div v-if="detailLoading" class="detail-loading">
            <RefreshCw :size="14" :stroke-width="2.3" class="spin" />
            正在读取完整任务详情...
          </div>

          <div class="detail-hero">
            <span class="task-icon" :class="`is-${selectedItem.domain || 'system'}`">
              <component :is="domainMeta(selectedItem.domain).icon" :size="15" :stroke-width="2.3" />
            </span>
            <div class="detail-hero-main">
              <div class="detail-hero-head">
                <h2 class="detail-title">{{ selectedItem.title }}</h2>
                <span class="status-pill" :class="`is-${selectedItem.status}`">{{ selectedItem.status_label }}</span>
              </div>
              <p v-if="selectedItem.subtitle" class="detail-subtitle">{{ selectedItem.subtitle }}</p>
              <div class="task-chip-row">
                <span class="task-chip task-chip-domain" :class="`is-${selectedItem.domain}`">{{ selectedItem.domain_label }}</span>
                <span v-if="formatRJCode(selectedItem.rjcode)" class="task-chip is-rj">{{ formatRJCode(selectedItem.rjcode) }}</span>
              </div>
            </div>
          </div>

          <div class="detail-grid">
            <div class="detail-block">
              <span class="detail-block-label">来源</span>
              <span class="detail-block-value">{{ selectedItem.source_label || '-' }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">RJ</span>
              <span class="detail-block-value">{{ formatRJCode(selectedItem.rjcode) || '-' }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">创建时间</span>
              <span class="detail-block-value">{{ formatDateTime(selectedItem.created_at) }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">完成时间</span>
              <span class="detail-block-value">{{ formatDateTime(selectedItem.completed_at) }}</span>
            </div>
          </div>

          <div class="detail-section">
            <span class="detail-section-label">当前状态</span>

            <div v-if="getRecoveredNotice(selectedItem)" class="recovered-banner">
              <CheckCircle :size="14" :stroke-width="2.3" />
              <div>
                <div class="recovered-title">已恢复</div>
                <div class="recovered-text">{{ getRecoveredNotice(selectedItem) }}</div>
              </div>
            </div>

            <div class="detail-step">{{ selectedItem.current_step || '-' }}</div>

            <div v-if="showProgress(selectedItem)" class="detail-progress">
              <div class="progress-track progress-lg">
                <div class="progress-fill" :style="{ width: `${selectedItem.progress}%` }"></div>
              </div>
              <span class="progress-text">{{ selectedItem.progress }}%</span>
            </div>

            <div v-if="selectedItem.error_message" class="detail-error">
              <AlertTriangle :size="13" :stroke-width="2.3" />
              {{ selectedItem.error_message }}
            </div>
            <div v-if="getDLsiteFailureReason(selectedItem)" class="detail-error">
              <AlertTriangle :size="13" :stroke-width="2.3" />
              DLsite 抓取失败原因：{{ getDLsiteFailureReason(selectedItem) }}
            </div>
          </div>

          <div v-if="selectedItem.metrics?.length" class="detail-section">
            <span class="detail-section-label">关键指标</span>
            <div class="detail-metrics-grid">
              <div v-for="metric in selectedItem.metrics" :key="`${selectedItem.id}-${metric.label}`" class="detail-metric-card">
                <span class="detail-metric-label">{{ metric.label }}</span>
                <span class="detail-metric-value">{{ metric.value }}</span>
              </div>
            </div>
          </div>

          <div v-if="getCircleIndexMetaEntries(selectedItem).length" class="detail-section">
            <span class="detail-section-label">进度元信息</span>
            <div class="detail-metrics-grid">
              <div v-for="entry in getCircleIndexMetaEntries(selectedItem)" :key="`${selectedItem.id}-${entry.label}`" class="detail-metric-card">
                <span class="detail-metric-label">{{ entry.label }}</span>
                <span class="detail-metric-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>

          <div v-if="getCircleIndexProgressLog(selectedItem).length" class="detail-section">
            <span class="detail-section-label">进度日志</span>
            <div class="detail-progress-log">
              <div
                v-for="(entry, index) in getCircleIndexProgressLog(selectedItem)"
                :key="`${selectedItem.id}-progress-${index}`"
                class="detail-progress-log-row"
              >
                <span class="detail-progress-log-time">{{ formatDateTime(entry.time) }}</span>
                <span class="detail-progress-log-progress">{{ entry.progress }}%</span>
                <span class="detail-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>
          </div>

          <div v-for="section in selectedItemFileTreeSections" :key="`${selectedItem.id}-${section.key}`" class="detail-section">
            <div class="detail-section-head">
              <span class="detail-section-label">{{ section.label }}</span>
              <div class="detail-tree-toolbar">
                <div class="detail-tree-filters">
                  <button type="button" class="detail-tree-filter-btn" :class="{ 'is-active': treeFilterMode === 'all' }" @click="treeFilterMode = 'all'">全部</button>
                  <button type="button" class="detail-tree-filter-btn" :class="{ 'is-active': treeFilterMode === 'added' }" @click="treeFilterMode = 'added'">只看新增</button>
                  <button type="button" class="detail-tree-filter-btn" :class="{ 'is-active': treeFilterMode === 'removed' }" @click="treeFilterMode = 'removed'">只看删除</button>
                  <button type="button" class="detail-tree-filter-btn" @click="setTreeSectionExpanded(section, true)">展开全部</button>
                  <button type="button" class="detail-tree-filter-btn" @click="setTreeSectionExpanded(section, false)">收起全部</button>
                </div>
                <div class="detail-tree-summary">
                  <span v-if="section.totalCount" class="detail-tree-summary-pill">共 {{ section.totalCount }} 项</span>
                  <span v-if="section.addedCount" class="detail-tree-summary-pill is-added">新增 {{ section.addedCount }}</span>
                  <span v-if="section.removedCount" class="detail-tree-summary-pill is-removed">删除 {{ section.removedCount }}</span>
                </div>
              </div>
            </div>
            <div class="detail-entry-tree-box">
              <div
                v-for="entry in section.rows"
                :key="`${selectedItem.id}-${section.key}-${entry.key}`"
                class="detail-tree-row"
                :class="[
                  `is-${entry.type || 'file'}`,
                  { 'is-removed': entry.status === 'removed', 'is-added': entry.status === 'added', 'is-expandable': entry.hasChildren }
                ]"
                :style="{ paddingLeft: `${12 + entry.depth * 18}px` }"
              >
                <div class="detail-tree-main">
                  <button
                    v-if="entry.hasChildren"
                    type="button"
                    class="detail-tree-toggle"
                    @click="toggleTreeNode(entry.key, entry.defaultExpanded)"
                  >
                    <component :is="entry.expanded ? ChevronDown : ChevronRight" :size="12" :stroke-width="2.4" />
                  </button>
                  <span v-else class="detail-tree-toggle detail-tree-toggle-placeholder"></span>
                  <span class="detail-tree-icon" :class="`is-${entry.type || 'file'}`">
                    <component :is="entry.type === 'dir' ? Folder : File" :size="13" :stroke-width="2.3" />
                  </span>
                  <span class="detail-tree-name">{{ entry.label }}</span>
                  <span v-if="entry.status === 'added'" class="detail-tree-state-pill is-added">新增</span>
                </div>
                <span v-if="entry.sizeText" class="detail-tree-size">{{ entry.sizeText }}</span>
              </div>
            </div>
          </div>

          <div class="detail-section">
            <span class="detail-section-label">路径信息</span>
            <div class="detail-path-row">
              <span class="detail-path-label">源路径</span>
              <code class="detail-path-value">{{ selectedItem.source_path || '-' }}</code>
            </div>
            <div class="detail-path-row">
              <span class="detail-path-label">输出路径</span>
              <code class="detail-path-value">{{ getOutputPath(selectedItem) || '-' }}</code>
            </div>
          </div>

          <div class="detail-actions">
            <button
              v-for="action in selectedItem.actions || []"
              :key="`${selectedItem.id}-${action}`"
              type="button"
              class="command-btn"
              :class="`is-${action}`"
              @click="handleTaskAction(selectedItem, action)"
            >
              <component :is="actionIcon(action)" :size="13" :stroke-width="2.3" />
              {{ getActionLabel(action) }}
            </button>
          </div>
        </template>

        <AppEmptyState v-else description="选择左侧任务查看详情" size="sm" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Captions,
  CheckCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  File,
  FileArchive,
  Folder,
  ListChecks,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Upload,
  UploadCloud,
  X,
  XCircle,
} from 'lucide-vue-next'
import { taskCenterApi } from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'

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
  { value: 'system', label: '系统任务', icon: Activity }
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'processing', label: '处理中' },
  { value: 'waiting_manual', label: '等待人工' },
  { value: 'waiting_retry', label: '等待重试' },
  { value: 'pending', label: '待处理' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
  { value: 'completed', label: '已完成' }
]

function domainMeta(domain) {
  return domainOptions.find((d) => d.value === domain) || { icon: Activity }
}

function getDomainCount(domain) {
  return Number(overviewDomainCounts.value[domain] || 0) || ''
}

const metricsPanel = computed(() => [
  {
    key: 'processing',
    label: '处理中',
    value: Number(overviewHighlightCounts.value.processing || 0),
    icon: Activity,
    click: () => { currentStatus.value = 'processing' }
  },
  {
    key: 'waiting_manual',
    label: '等待人工',
    value: Number(overviewHighlightCounts.value.waiting_manual || 0),
    icon: PauseCircle,
    click: () => { currentStatus.value = 'waiting_manual' }
  },
  {
    key: 'waiting_retry',
    label: '等待重试',
    value: Number(overviewHighlightCounts.value.waiting_retry || 0),
    icon: RotateCcw,
    click: () => { currentStatus.value = 'waiting_retry' }
  },
  {
    key: 'failed',
    label: '失败',
    value: Number(overviewHighlightCounts.value.failed || 0),
    icon: XCircle,
    click: () => { currentStatus.value = 'failed' }
  }
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
  const digest = {
    active: 0,
    completed: 0,
    failed: 0,
  }
  for (const item of filteredItems.value) {
    const status = String(item?.status || '').trim()
    if (ACTIVE_STATUSES.has(status)) digest.active += 1
    if (status === 'completed') digest.completed += 1
    if (status === 'failed' || status === 'canceled' || status === 'cancelled') digest.failed += 1
  }
  return digest
})

const selectedItem = computed(() => {
  if (!filteredItems.value.length) {
    return null
  }
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
  // 修复切换任务时短暂显示上一条详情的问题
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
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  searchDebounceTimer = setTimeout(() => {
    debouncedSearchQuery.value = String(searchQuery.value || '').trim()
    currentOffset.value = 0
    refreshTaskCenter(false, { silent: true }).catch((error) => {
      console.error('任务中心搜索刷新失败:', error)
    })
  }, 350)
})

watch(pollingEnabled, (enabled) => {
  if (enabled) {
    startPolling()
    return
  }
  stopPolling()
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
  if (intervalId || !pollingEnabled.value) {
    return
  }
  intervalId = setInterval(() => {
    refreshTaskCenter(false, { silent: true }).catch((error) => {
      console.error('任务中心轮询失败:', error)
    })
  }, 5000)
}

function stopPolling() {
  if (!intervalId) {
    return
  }
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

async function refreshTaskCenter(showMessage = false, options = {}) {
  const { silent = false } = options
  if (refreshing.value) {
    queuedRefresh = true
    return
  }
  try {
    refreshing.value = true
    if (!silent) {
      loading.value = true
    }

    const params = {
      mode: 'summary',
      limit: pageSize.value,
      offset: currentOffset.value,
      _t: Date.now()
    }
    if (currentDomain.value !== 'all') params.domain = currentDomain.value
    if (currentStatus.value !== 'all') params.status = currentStatus.value
    if (debouncedSearchQuery.value) params.search = debouncedSearchQuery.value

    const [overviewData, listData] = await Promise.all([
      taskCenterApi.overview({ _t: Date.now() }),
      taskCenterApi.list(params)
    ])

    overviewHighlightCounts.value = overviewData?.highlight_counts || {}
    overviewDomainCounts.value = overviewData?.counts_by_domain || {}

    const nextItems = Array.isArray(listData) ? listData : (listData?.items || [])
    items.value = nextItems
    totalItems.value = Number(listData?.total ?? nextItems.length)

    // Hidden bug fix: 如果后端总量变小导致 offset 越界，会出现“空页但有数据”
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

    if (showMessage) {
      ElMessage.success('任务中心已刷新')
    }
  } catch (error) {
    console.error('获取任务中心失败:', error)
    if (!silent) {
      ElMessage.error('获取任务中心失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    refreshing.value = false
    if (!silent) {
      loading.value = false
    }
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
  if (!force && detailLoading.value) {
    return
  }
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
  if (!path) {
    return ''
  }
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
  if (match) {
    return `RJ${match[1]}`
  }
  const fallback = raw.match(/[RVB]J\s*(\d{6,8})/i)
  if (fallback) {
    return `RJ${fallback[1]}`
  }
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

function buildTreeRows(items = []) {
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

  for (const item of items) {
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
      if (hasChildren && expanded) {
        walk(node.children, depth + 1)
      }
    }
  }

  walk(roots)
  return rows
}

function toggleTreeNode(key, defaultExpanded = false) {
  treeExpandedState.value = {
    ...treeExpandedState.value,
    [key]: !(treeExpandedState.value[key] ?? defaultExpanded)
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
    process: '处理失败'
  }
  if (stageMap[stage]) {
    return stageMap[stage]
  }
  if (String(item?.status || '') === 'failed') {
    return '处理失败'
  }
  return ''
}

function getOutputPath(item) {
  if (!item) {
    return ''
  }
  const details = item.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  return item.target_path ||
    metadata.subtitle_dir ||
    metadata.target_folder_path ||
    metadata.folder_path ||
    preview.selected_candidate?.folder_path ||
    ''
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
  if (!item) {
    return []
  }

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
    const candidateCount = pickMetricValue(item, '候选')
    const dlsiteCount = pickMetricValue(item, 'DLsite')
    const downloadableCount = pickMetricValue(item, '可下载')
    if (item.title) pieces.push(item.title)
    if (candidateCount) pieces.push(`候选 ${candidateCount}`)
    if (dlsiteCount) pieces.push(`DLsite ${dlsiteCount}`)
    if (downloadableCount) pieces.push(`可下载 ${downloadableCount}`)
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

  return dedupeSummaryPieces(pieces).slice(0, 4)
}

function mapFilteredItems(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const rawItems = [
    ...(Array.isArray(metadata.filtered_items) ? metadata.filtered_items : []),
    ...(Array.isArray(metadata.filtered_files) ? metadata.filtered_files : []),
    ...(Array.isArray(metadata.filtered_dirs) ? metadata.filtered_dirs : [])
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
      sizeText: asObject.size !== undefined && asObject.size !== null ? formatBytes(asObject.size) : ''
    })
  }
  return mapped
}

function mapUploadedFiles(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const sourceFiles = Array.isArray(metadata.upload_files) && metadata.upload_files.length
    ? metadata.upload_files
    : (Array.isArray(metadata.uploaded_files) ? metadata.uploaded_files : [])
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
    const filteredItems = mergedItems.filter((entry) => {
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
      if (entry.type === 'dir') {
        directoryKeys.add(rawPath)
      }
    }
    return {
      key: section.key,
      label: section.label,
      rows: buildTreeRows(filteredItems),
      totalCount: mergedItems.length,
      addedCount: mergedItems.filter((entry) => entry.status === 'added').length,
      removedCount: mergedItems.filter((entry) => entry.status === 'removed').length,
      directoryKeys: Array.from(directoryKeys),
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
  if (item?.kind !== 'circle_completion_index') {
    return []
  }
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
  if (item?.kind !== 'circle_completion_index') {
    return []
  }
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

function getActionLabel(action) {
  const labels = {
    pause: '暂停',
    resume: '恢复',
    cancel: '取消',
    retry_waiting: '立即重试',
    delete_waiting_retry: '移除等待重试',
    open_subtitle_import: '前往字幕补配',
    open_circle_completion: '前往社团补全',
    reindex_circle: '重新索引',
  }
  return labels[action] || action
}

function actionIcon(action) {
  const map = {
    pause: PauseCircle,
    resume: PlayCircle,
    cancel: XCircle,
    retry_waiting: RotateCcw,
    delete_waiting_retry: XCircle,
    open_subtitle_import: ArrowRight,
    open_circle_completion: ArrowRight,
    reindex_circle: RotateCcw,
  }
  return map[action] || Activity
}

async function handleTaskAction(item, action) {
  try {
    const result = await taskCenterApi.action(item.id, action)
    if (result?.route_hint) {
      await router.push(result.route_hint)
    }
    ElMessage.success(result?.message || '操作成功')
    await refreshTaskCenter()
  } catch (error) {
    console.error('执行任务动作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openTaskRoute(item) {
  if (!item?.route_hint) {
    return
  }
  router.push(item.route_hint)
}

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
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
.task-center-shell {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  color: #1f2328;
}

.workspace-bar {
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  gap: 16px;
  padding: 2px 0 16px;
  border-bottom: 1px solid #ebebea;
}

.workspace-bar > .dash-btn {
  margin-left: auto;
}

.workspace-bar > .dash-btn + .dash-btn {
  margin-left: 0;
}

.workspace-title-wrap {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.workspace-title-icon {
  margin-top: 3px;
  color: #2563eb;
}

.workspace-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
}

.workspace-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
}

.dash-btn,
.command-btn,
.pager-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
  color: #374151;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.dash-btn.is-active {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

.dash-btn:hover:not(:disabled),
.command-btn:hover:not(:disabled),
.pager-btn:hover:not(:disabled) {
  border-color: #d1d5db;
  background: #f8fafc;
  transform: translateY(-2px) scale(1.02);
}

.dash-btn:active:not(:disabled),
.command-btn:active:not(:disabled),
.pager-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.dash-btn:disabled,
.command-btn:disabled,
.pager-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.workspace-metrics-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 0;
  border-bottom: 1px solid #f0f1f3;
}

.metric-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border: 1px solid #e8eaee;
  border-radius: 999px;
  background: #fff;
  color: #4b5563;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.15s ease;
}

.metric-pill b {
  color: #111827;
}

.metric-pill:hover {
  border-color: #d5d9e0;
  background: #f8fafc;
}

.metric-pill.is-processing {
  color: #1d4ed8;
}

.metric-pill.is-waiting_manual,
.metric-pill.is-waiting_retry {
  color: #b45309;
}

.metric-pill.is-failed {
  color: #dc2626;
}

.metric-pill.mini {
  padding: 3px 8px;
  border-color: #eef1f5;
  color: #667085;
  background: #fbfcfd;
}

.filters-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  padding: 14px 0 16px;
  border-bottom: 1px solid #f0f1f3;
}

.filters-group {
  display: grid;
  gap: 7px;
  min-width: min(100%, 560px);
}

.filters-tools-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

.tools-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.tools-select {
  height: 32px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0 10px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  outline: none;
}

.tools-select:focus {
  border-color: #93c5fd;
  box-shadow: 0 0 0 3px rgba(147, 197, 253, 0.2);
}

.filters-label {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.filters-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid #e7e9ee;
  border-radius: 999px;
  background: #fff;
  color: #4b5563;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.filter-chip svg {
  color: #64748b;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.2s ease;
}

.filter-chip.is-import svg {
  color: #b45309;
}

.filter-chip.is-rj_subtitle svg,
.filter-chip.is-subtitle_import svg {
  color: #7c3aed;
}

.filter-chip.is-asmr_sync svg,
.filter-chip.is-upload svg {
  color: #0e7490;
}

.filter-chip.is-circle_completion svg,
.filter-chip.is-system svg,
.filter-chip.is-all svg {
  color: #2563eb;
}

.filter-chip:hover {
  border-color: #d9dee7;
  background: #f8fafc;
  transform: translateY(-2px) scale(1.02);
}

.filter-chip:hover svg {
  transform: rotate(-10deg) scale(1.05);
}

.filter-chip:active {
  transform: scale(0.96);
}

.filter-chip.active {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

.chip-count {
  min-width: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #e5e7eb;
  color: #475569;
  font-size: 11px;
  line-height: 1.5;
  text-align: center;
}

.search-wrap {
  display: flex;
  align-items: center;
  width: min(380px, 100%);
  height: 34px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  padding: 0 9px;
  margin-left: auto;
}

.search-wrap:focus-within {
  border-color: #93c5fd;
  box-shadow: 0 0 0 3px rgba(147, 197, 253, 0.2);
}

.search-icon {
  color: #9ca3af;
}

.search-input {
  flex: 1;
  height: 100%;
  border: 0;
  outline: none;
  padding: 0 8px;
  font-size: 13px;
  color: #1f2937;
  background: transparent;
}

.search-clear {
  border: 0;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.task-center-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(420px, 1.05fr);
  gap: 14px;
  padding-top: 14px;
  min-height: 0;
  flex: 1;
}

.pane {
  border: 1px solid #ebebea;
  border-radius: 10px;
  background: #fff;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #f0f1f3;
}

.pane-subhead {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f1f3;
  background: linear-gradient(120deg, #fafcff 0%, #f8fbff 40%, #fbfdff 100%);
}

.mini-kpi {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
}

.mini-kpi.is-active {
  color: #1d4ed8;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.mini-kpi.is-done {
  color: #15803d;
  border-color: #bbf7d0;
  background: #ecfdf3;
}

.mini-kpi.is-failed {
  color: #be123c;
  border-color: #fecdd3;
  background: #fff1f2;
}

.pane-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.pane-count {
  font-size: 12px;
  color: #6b7280;
}

.task-list {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
  min-height: 0;
}

.task-row {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: 1px solid #ebebea;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  animation: fade-up 0.35s ease both;
}

.task-row:hover {
  border-color: #dce2ea;
  background: #fafcff;
  transform: translateY(-2px);
}

.task-row.active {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.task-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  color: #64748b;
}

.task-row.is-import .task-icon {
  color: #b45309;
}

.task-row.is-rj_subtitle .task-icon,
.task-row.is-subtitle_import .task-icon {
  color: #7c3aed;
}

.task-row.is-asmr_sync .task-icon,
.task-row.is-upload .task-icon {
  color: #0e7490;
}

.task-row.is-circle_completion .task-icon,
.task-row.is-system .task-icon {
  color: #2563eb;
}

.task-icon.is-import {
  color: #b45309;
}

.task-icon.is-rj_subtitle,
.task-icon.is-subtitle_import {
  color: #7c3aed;
}

.task-icon.is-asmr_sync,
.task-icon.is-upload {
  color: #0e7490;
}

.task-icon.is-circle_completion,
.task-icon.is-system {
  color: #2563eb;
}

.task-main {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.task-main-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-title {
  min-width: 0;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-subtitle {
  margin: 0;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}

.status-pill {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid #dbe0e7;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f8fafc;
}

.status-pill.is-processing {
  color: #b45309;
  border-color: #f8d9a6;
  background: #fff7e8;
}

.status-pill.is-waiting_manual,
.status-pill.is-waiting_retry,
.status-pill.is-pending {
  color: #1d4ed8;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.status-pill.is-paused {
  color: #6b7280;
  border-color: #d1d5db;
  background: #f3f4f6;
}

.status-pill.is-completed {
  color: #166534;
  border-color: #bbf7d0;
  background: #ecfdf3;
}

.status-pill.is-failed,
.status-pill.is-cancelled,
.status-pill.is-canceled {
  color: #be123c;
  border-color: #fecdd3;
  background: #fff1f2;
}

.task-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.task-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid #e7e9ee;
  background: #fff;
  color: #64748b;
  font-size: 11px;
  line-height: 1.3;
}

.task-chip svg {
  color: inherit;
}

.task-chip-domain.is-import {
  color: #b45309;
  border-color: #f8d9a6;
  background: #fffaf0;
}

.task-chip-domain.is-rj_subtitle,
.task-chip-domain.is-subtitle_import {
  color: #7c3aed;
  border-color: #ddd6fe;
  background: #f5f3ff;
}

.task-chip-domain.is-asmr_sync,
.task-chip-domain.is-upload {
  color: #0e7490;
  border-color: #bae6fd;
  background: #f0fdff;
}

.task-chip-domain.is-circle_completion,
.task-chip-domain.is-system {
  color: #1d4ed8;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.task-row.is-import .task-chip svg {
  color: #b45309;
}

.task-row.is-rj_subtitle .task-chip svg,
.task-row.is-subtitle_import .task-chip svg {
  color: #7c3aed;
}

.task-row.is-asmr_sync .task-chip svg,
.task-row.is-upload .task-chip svg {
  color: #0e7490;
}

.task-row.is-circle_completion .task-chip svg,
.task-row.is-system .task-chip svg {
  color: #2563eb;
}

.task-progress-row,
.detail-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-track {
  flex: 1;
  height: 7px;
  border-radius: 999px;
  background: #e8edf3;
  overflow: hidden;
}

.progress-track.progress-lg {
  height: 9px;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb 0%, #1d4ed8 100%);
}

.progress-text {
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  white-space: nowrap;
}

.task-recovered,
.recovered-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #bbf7d0;
  background: #ecfdf3;
  color: #166534;
  font-size: 12px;
}

.recovered-title {
  font-weight: 700;
}

.recovered-text {
  margin-top: 1px;
}

.task-summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.task-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 10px 12px 12px;
  border-top: 1px solid #f0f1f3;
}

.task-empty-workbench {
  position: relative;
  margin: 14px;
  min-height: 260px;
  border: 1px dashed #dbe4f0;
  border-radius: 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  overflow: hidden;
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.empty-tips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
}

.pager-text,
.detail-loading {
  font-size: 12px;
  color: #6b7280;
}

.task-detail-pane {
  overflow: auto;
}

.task-detail-pane :deep(.app-empty-state) {
  margin: 24px auto;
}

.detail-loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 0;
}

.detail-hero {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px 8px;
}

.detail-hero-main {
  flex: 1;
  min-width: 0;
}

.detail-hero-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.detail-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #111827;
}

.detail-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 0 14px;
}

.detail-block {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid #f0f1f3;
  border-radius: 8px;
  background: #fafbfc;
}

.detail-block-label {
  font-size: 11px;
  color: #94a3b8;
}

.detail-block-value {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  word-break: break-all;
}

.detail-section {
  margin-top: 10px;
  padding: 0 14px 12px;
  border-bottom: 1px solid #f3f4f6;
}

.detail-section:last-of-type {
  border-bottom: 0;
}

.detail-section-label {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.detail-step {
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
}

.detail-error {
  margin-top: 8px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #fecdd3;
  background: #fff1f2;
  color: #be123c;
  font-size: 12px;
}

.detail-metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.detail-metric-card {
  display: grid;
  gap: 2px;
  border: 1px solid #f0f1f3;
  border-radius: 8px;
  background: #fafbfc;
  padding: 8px 9px;
}

.detail-metric-label {
  font-size: 11px;
  color: #94a3b8;
}

.detail-metric-value {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.detail-progress-log {
  display: grid;
  gap: 6px;
}

.detail-progress-log-row {
  display: grid;
  grid-template-columns: 120px 54px 1fr;
  gap: 8px;
  align-items: center;
  padding: 7px 8px;
  border: 1px solid #eef1f4;
  border-radius: 7px;
  font-size: 12px;
}

.detail-progress-log-time {
  color: #64748b;
}

.detail-progress-log-progress {
  color: #1d4ed8;
  font-weight: 700;
}

.detail-progress-log-message {
  color: #334155;
}

.detail-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.detail-tree-summary {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.detail-tree-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.detail-tree-filters {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-tree-filter-btn {
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.detail-tree-filter-btn:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: #cbd5e1;
  background: #f8fafc;
}

.detail-tree-filter-btn:active {
  transform: scale(0.96);
}

.detail-tree-filter-btn.is-active {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.detail-tree-summary-pill,
.detail-tree-state-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}

.detail-tree-summary-pill {
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #64748b;
}

.detail-tree-summary-pill.is-added,
.detail-tree-state-pill.is-added {
  border: 1px solid #bbf7d0;
  background: #ecfdf3;
  color: #15803d;
}

.detail-tree-summary-pill.is-removed,
.detail-tree-state-pill.is-removed {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
}

.detail-entry-tree-box {
  border: 1px solid #edf0f3;
  border-radius: 8px;
  background: #fafbfc;
  overflow: hidden;
  max-height: 320px;
  overflow-y: auto;
}

.detail-tree-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 34px;
  padding-top: 4px;
  padding-bottom: 4px;
  padding-right: 10px;
  border-bottom: 1px solid #f0f2f4;
  transition: background 0.2s ease, color 0.2s ease;
}

.detail-tree-row.is-expandable:hover {
  background: rgba(255, 255, 255, 0.72);
}

.detail-tree-row.is-added {
  background: linear-gradient(90deg, rgba(236, 253, 243, 0.82) 0%, rgba(250, 251, 252, 0) 100%);
}

.detail-tree-row.is-removed {
  background: linear-gradient(90deg, rgba(248, 250, 252, 0.98) 0%, rgba(250, 251, 252, 0.88) 100%);
}

.detail-tree-row:last-child {
  border-bottom: 0;
}

.detail-tree-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.detail-tree-toggle {
  width: 18px;
  height: 18px;
  border: 0;
  background: transparent;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  border-radius: 5px;
  flex: 0 0 18px;
}

.detail-tree-toggle:hover {
  background: #eef2f7;
  color: #475569;
}

.detail-tree-toggle-placeholder {
  cursor: default;
}

.detail-tree-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: #eef2f7;
  color: #64748b;
}

.detail-tree-icon.is-dir {
  background: #eff6ff;
  color: #2563eb;
}

.detail-tree-name {
  min-width: 0;
  font-size: 12px;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-tree-row.is-removed .detail-tree-icon {
  background: #f1f5f9;
  color: #94a3b8;
}

.detail-tree-row.is-removed .detail-tree-name,
.detail-tree-row.is-removed .detail-tree-size {
  color: #94a3b8;
  text-decoration: line-through;
}

.detail-tree-size {
  font-size: 11px;
  color: #94a3b8;
  flex: 0 0 auto;
}

.detail-path-row {
  display: grid;
  gap: 4px;
  margin-bottom: 8px;
}

.detail-path-row:last-child {
  margin-bottom: 0;
}

.detail-path-label {
  font-size: 11px;
  color: #94a3b8;
}

.detail-path-value {
  display: block;
  width: 100%;
  padding: 8px 9px;
  border-radius: 8px;
  border: 1px solid #eef1f4;
  background: #fafbfc;
  color: #334155;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 14px 14px;
}

.command-btn.is-cancel,
.command-btn.is-delete_waiting_retry {
  border-color: #fecdd3;
  color: #be123c;
  background: #fff1f2;
}

.command-btn.is-pause {
  border-color: #fde68a;
  color: #b45309;
  background: #fffbeb;
}

.command-btn.is-resume,
.command-btn.is-retry_waiting,
.command-btn.is-open_subtitle_import,
.command-btn.is-open_circle_completion,
.command-btn.is-reindex_circle {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1280px) {
  .filters-panel {
    align-items: stretch;
  }

  .search-wrap,
  .filters-tools-row {
    margin-left: 0;
  }

  .task-center-layout {
    grid-template-columns: 1fr;
  }

  .task-detail-pane {
    max-height: none;
  }
}

@media (max-width: 900px) {
  .detail-grid,
  .detail-metrics-grid {
    grid-template-columns: 1fr;
  }

  .detail-progress-log-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .workspace-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .search-wrap {
    width: 100%;
  }

  .task-main-head,
  .detail-hero-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .status-pill {
    align-self: flex-start;
  }
}
</style>
