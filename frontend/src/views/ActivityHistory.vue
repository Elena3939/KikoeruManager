<template>
  <div class="activity-page">
    <!-- 页头走共享组件 AppPageHeader，右侧 slot 保留原本的搜索框 + 两个操作按钮 -->
    <AppPageHeader
      :icon="History"
      icon-color="var(--km-nav-history-icon)"
      title="操作记录"
      subtitle="字幕、解压、入库、删除、ASMR 同步等任务的完整审计"
    >
      <div class="page-head-search-wrap">
        <div class="page-head-search">
          <Search :size="14" :stroke-width="2.4" class="page-head-search-icon" />
          <input
            v-model="filters.q"
            class="page-head-search-input"
            :placeholder="searchPlaceholder"
            @input="onSearchInput"
            @keyup.enter="applySearchImmediately"
          />
          <!-- 搜索期间右侧 spinner 提示「正在搜」，比之前页面级遮罩更明确 -->
          <span v-if="loading && filters.q" class="page-head-search-spinner">
            <Loader2 :size="13" :stroke-width="2.6" class="animate-spin" />
          </span>
          <button v-if="filters.q" class="page-head-search-clear" type="button" @click="onClearSearch">
            <X :size="13" :stroke-width="2.6" />
          </button>
        </div>
        <!-- 搜索引擎状态条：只在「降级 / 需升级 / 重建中」时显示，平时隐藏不打扰 -->
        <div v-if="searchEngineHint" class="search-engine-hint" :class="`tone-${searchEngineHint.tone}`">
          <component :is="searchEngineHint.icon" :size="11" :stroke-width="2.4" class="hint-icon" />
          <span class="hint-text">{{ searchEngineHint.text }}</span>
          <button
            v-if="searchEngineHint.action"
            class="hint-action"
            type="button"
            :disabled="searchStatus.rebuild?.running"
            @click="searchEngineHint.action"
          >
            {{ searchEngineHint.actionLabel }}
          </button>
        </div>
      </div>
      <button
        class="page-head-btn ghost btn-archive"
        type="button"
        :disabled="loading"
        :title="compactHint"
        @click="onCompactClick"
      >
        <span class="page-head-btn-icon-wrap">
          <Archive :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
        </span>
        <span class="page-head-btn-label">归档老记录</span>
        <span v-if="compactSavingsLabel" class="page-head-btn-hint">{{ compactSavingsLabel }}</span>
      </button>
      <button class="page-head-btn primary btn-refresh" type="button" :disabled="loading" @click="loadAll">
        <span class="page-head-btn-icon-wrap">
          <!-- 两个图标始终在 DOM 中，通过 opacity + scale 平滑切换显示，避免 v-if 瞬切 -->
          <span class="page-head-btn-icon-slot" :class="{ 'is-visible': loading }">
            <Loader2 :size="13" :stroke-width="2.6" class="animate-spin" />
          </span>
          <span class="page-head-btn-icon-slot" :class="{ 'is-visible': !loading }">
            <RefreshCcw :size="13" :stroke-width="2.6" class="page-head-btn-icon" />
          </span>
        </span>
        <span class="page-head-btn-label">{{ loading ? '刷新中…' : '刷新' }}</span>
      </button>
    </AppPageHeader>

    <section class="activity-command-strip">
      <div class="activity-range-copy">
        <span class="activity-kicker">审计范围</span>
        <div class="activity-range-line">
          <strong>{{ statsRangeText }}</strong>
          <span>{{ formatNumber(stats.total_in_range) }} 条记录</span>
          <span v-if="lastLoadedAtText">{{ lastLoadedAtText }}</span>
        </div>
      </div>
      <AppDropdown
        v-model="statsDays"
        :options="statsDaysOptions"
        :width="128"
        :menu-min-width="150"
        :show-trigger-badge="false"
        @update:model-value="loadStats"
      />
    </section>

    <section class="activity-insight-board" aria-label="操作记录概览">
      <div class="activity-metric-rail">
        <article
          v-for="m in metricCards"
          :key="m.key"
          class="activity-metric-card"
          :title="m.hint"
        >
          <span class="activity-metric-label">{{ m.label }}</span>
          <strong class="activity-metric-value" :style="{ color: m.color }">
            <span>{{ metricSplit(m.value).num }}</span>
            <small v-if="metricSplit(m.value).unit">{{ metricSplit(m.value).unit }}</small>
          </strong>
        </article>
      </div>

      <div class="activity-context-band">
        <div class="activity-trend-panel">
          <div class="activity-panel-title">
            <span>每日操作量</span>
            <strong>{{ formatNumber(stats.total_in_range) }}</strong>
          </div>
          <AppEmptyState v-if="!sparkPoints.length" description="暂无趋势" size="sm" />
          <div v-else class="activity-sparkline-wrap">
            <svg
              class="activity-sparkline"
              :viewBox="`0 0 ${sparkBox.width} ${sparkBox.height}`"
              preserveAspectRatio="none"
            >
              <defs>
                <linearGradient :id="sparkGradientId" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#71717a" stop-opacity="0.24" />
                  <stop offset="100%" stop-color="#71717a" stop-opacity="0" />
                </linearGradient>
              </defs>
              <path :d="sparkAreaPath" :fill="`url(#${sparkGradientId})`" />
              <path :d="sparkLinePath" fill="none" stroke="#71717a" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
              <circle :cx="sparkLastPoint.x" :cy="sparkLastPoint.y" r="3.2" fill="#71717a" />
            </svg>
            <div class="activity-sparkline-foot">
              <span>{{ formatShortDate(sparkPoints[0]?.date) }}</span>
              <span>{{ formatShortDate(sparkPoints[sparkPoints.length - 1]?.date) }}</span>
            </div>
          </div>
        </div>

        <div class="activity-category-panel">
          <div class="activity-panel-title">
            <span>分类分布</span>
            <strong>{{ formatNumber(allCategories.length) }} 项</strong>
          </div>
          <AppEmptyState v-if="!allCategories.length" description="暂无数据" size="sm" />
          <div v-else class="activity-category-list">
            <div
              v-for="(cat, idx) in allCategories"
              :key="cat.category"
              class="activity-category-row"
            >
              <span class="activity-category-dot" :style="{ background: catPaletteColor(idx) }"></span>
              <span class="activity-category-name">{{ cat.label }}</span>
              <div class="activity-category-track">
                <span
                  class="activity-category-fill"
                  :style="{ width: cat.pct + '%', background: catPaletteColor(idx) }"
                />
              </div>
              <span class="activity-category-count">{{ formatNumber(cat.count) }}</span>
            </div>
          </div>
        </div>

        <div class="activity-filter-panel">
          <div class="activity-panel-title">
            <span>筛选记录流</span>
            <button
              v-if="hasActiveFilters"
              class="activity-filter-reset"
              type="button"
              title="清空所有筛选条件"
              @click="resetFilters"
            >
              <FilterX :size="13" :stroke-width="2.4" />
              <span>重置</span>
            </button>
          </div>
          <div class="activity-filter-controls">
            <AppDropdown
              v-model="filters.category"
              :options="categoryDropdownOptions"
              label="分类"
              placeholder="全部分类"
              :width="0"
              :menu-min-width="240"
              @update:model-value="applyFilters"
            />
            <AppDropdown
              v-model="filters.status"
              :options="statusDropdownOptions"
              label="状态"
              placeholder="全部状态"
              :width="0"
              :menu-min-width="200"
              @update:model-value="applyFilters"
            />
          </div>
        </div>
      </div>
    </section>

    <main class="activity-reader">
      <header class="activity-reader-head">
        <div>
          <span class="activity-kicker">记录流</span>
          <h2>按时间聚合阅读</h2>
        </div>
        <div class="activity-reader-meta">
          <span>匹配 {{ formatNumber(total) }} 条</span>
          <span>第 {{ formatNumber(page) }} / {{ formatNumber(totalPages) }} 页</span>
        </div>
      </header>

      <section
        class="activity-timeline-shell"
        v-app-loading="{ loading, text: '正在加载操作记录…', description: '同步索引、统计与状态聚合', size: 168, minHeight: 360, delay: 80, minVisible: 360, maskClass: 'activity-loading-mask' }"
      >
        <AppEmptyState
          v-if="!timelineGroups.length && !loading"
          description="没有匹配的操作记录"
          size="md"
        />
        <div v-else class="activity-timeline">
          <section
            v-for="group in timelineGroups"
            :key="group.key"
            class="activity-day-section"
          >
            <header class="activity-day-header">
              <span class="activity-day-label">{{ group.label }}</span>
              <span class="activity-day-count">{{ formatNumber(group.items.length) }} 条</span>
            </header>
            <div class="activity-log-list">
              <article
                v-for="row in group.items"
                :key="row.id"
                class="activity-log-row"
                :class="[`tone-${row._statusTone}`, { 'is-active': selectedRowId === String(row.id) }]"
                role="button"
                tabindex="0"
                @click="openDetail(row)"
                @keydown.enter.prevent="openDetail(row)"
                @keydown.space.prevent="openDetail(row)"
              >
                <div class="activity-log-time">
                  <time>{{ formatTime(row.created_at) }}</time>
                  <span class="activity-log-dot">
                    <component
                      :is="row._statusIcon"
                      :size="11"
                      :stroke-width="3"
                    />
                  </span>
                </div>
                <div class="activity-log-content">
                  <div class="activity-log-topline">
                    <span
                      class="activity-category-chip"
                      :class="row._categoryToneClass"
                    >
                      <component
                        :is="row._categoryIcon"
                        :size="12"
                        :stroke-width="2.6"
                        :class="row._categoryIconClass"
                      />
                      <span>{{ row.category_label }}</span>
                    </span>
                    <span
                      class="activity-action-label"
                      :class="row._actionToneClass"
                    >
                      {{ row._humanAction }}
                    </span>
                    <span v-if="row.rjcode" class="activity-rj-chip">{{ row.rjcode }}</span>
                    <span
                      v-if="row.compacted"
                      class="activity-flag-chip tone-neutral"
                      title="已归档：detail 已被压缩"
                    >
                      已归档
                    </span>
                    <span v-if="row.rerun" class="activity-flag-chip tone-warn">已重试</span>
                    <span v-if="row.has_children" class="activity-flag-chip tone-info">有子任务</span>
                    <span
                      v-if="row._isRecovered"
                      class="activity-recovery-chip"
                      title="此次失败后被人工处理或重试修复"
                    >
                      <CheckCircle2 :size="11" :stroke-width="2.6" />
                      已修复
                    </span>
                  </div>
                  <div
                    v-if="row._rename"
                    class="activity-log-summary activity-rename-summary"
                    :class="{ 'is-failed': row._rename.failed }"
                  >
                    <span class="activity-rename-old" :title="row._rename.oldName">{{ row._rename.oldName }}</span>
                    <span class="activity-rename-arrow">--&gt;</span>
                    <span class="activity-rename-new" :title="row._rename.newName">{{ row._rename.newName }}</span>
                    <span
                      v-if="row._rename.reason"
                      class="activity-rename-reason"
                      :title="row._rename.reason"
                    >· {{ row._rename.reason }}</span>
                  </div>
                  <div v-else class="activity-log-summary">{{ row.summary || '—' }}</div>
                  <div v-if="row.chips?.length || row.source_path" class="activity-log-meta">
                    <span
                      v-for="chip in row.chips || []"
                      :key="`${row.id}-${chip.label}`"
                      class="activity-meta-chip"
                      :class="chipToneClasses(chip.tone)"
                    >
                      <span>{{ chip.label }}</span>
                      <strong>{{ chip.value }}</strong>
                    </span>
                    <span v-if="row.source_path" class="activity-path-chip" :title="row.source_path">
                      <FolderOpen :size="12" :stroke-width="2.4" />
                      <span>{{ compactPath(row.source_path) }}</span>
                    </span>
                  </div>
                </div>
                <div class="activity-log-cue">
                  <ChevronRight :size="15" :stroke-width="2.4" />
                </div>
              </article>
            </div>
          </section>
        </div>
      </section>

      <footer class="activity-footer">
        <nav class="activity-pager km-pagination-wrap" aria-label="操作记录分页">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="limit"
            :page-sizes="pageSizeOptions"
            :total="total"
            :disabled="loading"
            layout="total, sizes, prev, pager, next, jumper"
            popper-class="km-pagination-size-popper"
            background
            @size-change="onActivityPageSizeChange"
            @current-change="onActivityPageChange"
          />
        </nav>
      </footer>
    </main>

    <!-- 详情抽屉：自定义 Teleport 面板，避免 Element 默认蓝色 / 暗黑模式漏色 -->
    <Teleport to="body">
      <Transition name="activity-overlay" @after-leave="onDrawerClosed">
        <div
          v-if="detailDrawerVisible"
          class="activity-detail-overlay"
          :class="{ 'is-resizing': isDrawerResizing }"
          @click.self="closeDetail"
        >
          <aside
            class="activity-detail-panel"
            :style="{ width: `${detailDrawerWidth}px` }"
            role="dialog"
            aria-modal="true"
            aria-label="操作记录详情"
            @click.stop
          >
            <ActivityDetailBody
              :row="selectedRow"
              :loading="detailLoading"
              :category-config="selectedCategoryConfig"
              :status-config="selectedStatusConfig"
              :status-tone="statusTone"
              :format-date-time="formatDateTime"
              :compact-path="compactPath"
              :human-action="humanAction"
              @close="closeDetail"
              @open-row="openDetailById"
              @navigate="handleDetailNavigate"
            />
          </aside>
        </div>
      </Transition>
    </Teleport>

    <!-- 详情面板左缘拖拽手柄：fixed 定位到面板外面，不受内容滚动影响 -->
    <Teleport to="body">
      <div
        v-if="detailDrawerVisible"
        ref="drawerResizerRef"
        class="activity-drawer-resizer-fixed"
        :class="{ 'is-active': isDrawerResizing }"
        :style="{ right: `${detailDrawerWidth}px` }"
        title="拖拽调整面板宽度"
        @mousedown.prevent="onDrawerResizeStart"
      ></div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  CloudDownload,
  Loader2,
  ChevronRight,
  Clock,
  Database,
  FileDown,
  ListFilter as Filter,
  FilterX,
  Folder,
  FolderOpen,
  History,
  Link as LinkIcon,
  Mail,
  MinusCircle,
  Package,
  PlayCircle,
  RefreshCcw,
  RefreshCw,
  Scissors,
  Search,
  ShieldAlert,
  Sparkles,
  Tag,
  Upload,
  Users,
  X,
  XCircle
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useActivityHistoryLite } from '../composables/useActivityHistoryLite'
import { isPurelyProblemListPartial } from '../composables/useActivityDetailModels'
import api from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import ActivityDetailBody from '../components/activity/ActivityDetailBody.vue'
import { getHttpDownloadDisplayMeta } from '../components/common/httpDownloadPlatformMeta.js'

const router = useRouter()

const {
  loading,
  detailLoading,
  items,
  total,
  page,
  limit,
  lastLoadedAt,
  stats,
  statsDays,
  filters,
  searchBackend,
  searchStatus,
  loadStats,
  loadList,
  loadAll,
  loadDetail,
  invalidateDetail,
  loadSearchStatus,
  rebuildFts,
  applyFilters,
  onPageSizeChange,
  shouldSoftRefresh,
  handleVisibilityRefresh
} = useActivityHistoryLite()

// ==================== 搜索框：debounce + loading 指示 + 状态徽章 ====================
// 之前用户连续在搜索框输入时，每次回车都直接发请求，老请求未取消、后端 LIKE 全表扫又
// 把内存炸了。现在策略：
//   1) input 触发 350ms debounce 自动搜（v-model 已绑值，函数只负责发请求）
//   2) Enter 立即清掉 debounce timer 直接搜，给老用户回车肌肉记忆兜底
//   3) Composable 层 AbortController 取消上一未完请求；后端再也不会跌进 LIKE 炸弹
//   4) 搜索框右侧 spinner + 状态徽章（unicode61 / 升级到 trigram / 重建中）
const SEARCH_DEBOUNCE_MS = 350
let _searchDebounceTimer = null

function onSearchInput() {
  if (_searchDebounceTimer) {
    clearTimeout(_searchDebounceTimer)
    _searchDebounceTimer = null
  }
  _searchDebounceTimer = setTimeout(() => {
    _searchDebounceTimer = null
    applyFilters()
  }, SEARCH_DEBOUNCE_MS)
}

function applySearchImmediately() {
  if (_searchDebounceTimer) {
    clearTimeout(_searchDebounceTimer)
    _searchDebounceTimer = null
  }
  applyFilters()
}

const searchPlaceholder = computed(() => {
  if (searchStatus.value?.rebuild?.running) {
    return '索引重建中…'
  }
  return '搜索 RJ、摘要、路径、任务 ID…'
})

// 搜索引擎状态徽章。返回 null 表示「不显示」（默认状态：trigram 已就绪 + 没在重建）。
const searchEngineHint = computed(() => {
  const st = searchStatus.value || {}
  const rb = st.rebuild || {}
  const backend = String(searchBackend.value || '')

  // 优先级 1：正在重建索引
  if (rb.running) {
    const total = Number(rb.total || 0)
    const copied = Number(rb.copied || 0)
    const pct = total > 0 ? Math.min(100, Math.round((copied / total) * 100)) : 0
    return {
      tone: 'info',
      icon: Loader2,
      text: `搜索引擎升级中 ${copied.toLocaleString('zh-CN')} / ${total.toLocaleString('zh-CN')}（${pct}%）`,
      action: null,
      actionLabel: ''
    }
  }

  // 优先级 2：搜索失败（FTS 异常 / 不可用）
  if (backend && (backend === 'unavailable' || backend.endsWith('_error'))) {
    return {
      tone: 'danger',
      icon: ShieldAlert,
      text: backend === 'unavailable' ? '搜索引擎不可用' : '搜索引擎异常，请重建索引',
      action: () => onClickRebuildFts(),
      actionLabel: '重建'
    }
  }

  // 优先级 3：可升级到 trigram（unicode61 → trigram）
  if (st.needs_upgrade && st.fts_enabled && st.trigram_supported) {
    return {
      tone: 'warn',
      icon: Sparkles,
      text: '中文搜索可显著提升：升级到 Trigram 索引',
      action: () => onClickRebuildFts(),
      actionLabel: '一键升级'
    }
  }

  // 默认隐藏
  return null
})

let _searchStatusPollTimer = null
function startSearchStatusPolling() {
  // 重建中每 1.5s 拉一次进度，结束后再拉一次状态切换 hint
  if (_searchStatusPollTimer) return
  _searchStatusPollTimer = setInterval(async () => {
    await loadSearchStatus()
    if (!searchStatus.value?.rebuild?.running) {
      stopSearchStatusPolling()
    }
  }, 1500)
}
function stopSearchStatusPolling() {
  if (_searchStatusPollTimer) {
    clearInterval(_searchStatusPollTimer)
    _searchStatusPollTimer = null
  }
}

async function onClickRebuildFts() {
  try {
    await rebuildFts('trigram')
    ElMessage.success('已开始后台重建搜索引擎索引')
    await loadSearchStatus()
    startSearchStatusPolling()
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message || '重建失败'
    ElMessage.error(`无法启动重建：${detail}`)
  }
}

// ==================== 配置 / 常量 ====================
const categoryOptions = [
  { value: 'subtitle_crawl', label: '字幕爬取' },
  { value: 'subtitle_pair', label: '字幕配对' },
  { value: 'subtitle_import', label: '字幕补配' },
  { value: 'http_download', label: 'HTTP 下载' },
  { value: 'baidu_netdisk', label: '百度网盘' },
  { value: 'extract', label: '解压' },
  { value: 'auto_import', label: '解压入库' },
  { value: 'process_existing', label: '已有目录处理' },
  { value: 'pipeline_filter', label: '筛选' },
  { value: 'pipeline_metadata', label: '元数据' },
  { value: 'pipeline_rename', label: '重命名' },
  { value: 'pipeline_delete', label: '删除' },
  { value: 'asmr_sync', label: 'ASMR 同步' },
  { value: 'upload', label: '库存上传' },
  { value: 'circle_completion', label: '社团补全' },
  { value: 'email_watcher', label: '邮件监听' },
  { value: 'conflict_resolution', label: '问题作品处理' }
]

// category → tone 映射：每个 category 独占一个 tone，避免视觉撞色看不出区别。
// 颜色语义大致按"业务领域"分组：字幕系（紫蓝系）、库存系（绿系）、Pipeline 工具系（暖色 / 灰）、
// 远端通信系（蓝青粉）。即使列表里多种 category 混排，也能一眼定位到自己关心的那一类。
const categoryConfigs = {
  subtitle_crawl: { icon: Search, label: '字幕爬取', tone: 'indigo' },
  subtitle_pair: { icon: LinkIcon, label: '字幕配对', tone: 'violet' },
  subtitle_import: { icon: FileDown, label: '字幕补配', tone: 'fuchsia' },
  http_download: { icon: FileDown, label: 'HTTP 下载', tone: 'cyan' },
  baidu_netdisk: { icon: CloudDownload, label: '百度网盘', tone: 'sky' },
  extract: { icon: Package, label: '解压', tone: 'teal' },
  auto_import: { icon: Database, label: '解压入库', tone: 'emerald' },
  process_existing: { icon: Folder, label: '已有目录处理', tone: 'lime' },
  pipeline_filter: { icon: Filter, label: '筛选', tone: 'amber' },
  pipeline_metadata: { icon: Tag, label: '元数据', tone: 'slate' },
  pipeline_rename: { icon: Tag, label: '重命名', tone: 'orange' },
  pipeline_delete: { icon: Scissors, label: '删除', tone: 'rose' },
  asmr_sync: { icon: RefreshCw, label: 'ASMR 同步', tone: 'cyan' },
  upload: { icon: Upload, label: '库存上传', tone: 'sky' },
  circle_completion: { icon: Users, label: '社团补全', tone: 'blue' },
  // pink/rose 这两个暖色会让邮件监听的 chip 看起来像失败 / 删除警告。
  // 换成 purple 中紫：与字幕系的 violet/fuchsia/indigo 在 chip 背景色上能区分，
  // 也是邮箱类产品的传统同调色（不会让人联想错误状态）。
  email_watcher: { icon: Mail, label: '邮件监听', tone: 'purple' },
  conflict_resolution: { icon: ShieldAlert, label: '问题作品处理', tone: 'blue' },
  default: { icon: Tag, label: '其他', tone: 'slate' }
}

const statusConfigs = {
  success: { icon: CheckCircle2, label: '成功', tone: 'success' },
  completed: { icon: CheckCircle2, label: '完成', tone: 'success' },
  partial_success: { icon: AlertCircle, label: '部分成功', tone: 'warn' },
  failed: { icon: XCircle, label: '失败', tone: 'danger' },
  error: { icon: XCircle, label: '错误', tone: 'danger' },
  cancelled: { icon: MinusCircle, label: '已取消', tone: 'neutral' },
  waiting: { icon: Clock, label: '等待中', tone: 'info' },
  incomplete: { icon: PlayCircle, label: '未完成', tone: 'info' },
  info: { icon: PlayCircle, label: '信息', tone: 'info' },
  default: { icon: MinusCircle, label: '—', tone: 'neutral' }
}

function categoryConfig(category) {
  return categoryConfigs[category] || categoryConfigs.default
}

function categoryIcon(category) {
  return categoryConfig(category).icon
}

function statusConfig(status) {
  return statusConfigs[status] || statusConfigs.default
}

function statusTone(status) {
  return statusConfig(status).tone
}

function statusIcon(status) {
  return statusConfig(status).icon
}

function statusLabel(status) {
  return statusConfig(status).label
}

// ==================== AppDropdown 选项数据 ====================
// 给「分类」筛选准备 dropdown 数据：以 categoryOptions 为基础，从 categoryConfigs 拿 icon
// '' value 表示"全部分类"，匹配 useActivityHistoryLite 里 filters.category 默认值
const categoryDropdownOptions = computed(() => [
  { value: '', label: '全部分类', icon: Filter },
  ...categoryOptions.map((opt) => ({
    value: opt.value,
    label: opt.label,
    icon: categoryConfig(opt.value).icon,
  })),
])

// 给「状态」筛选准备 dropdown 数据，icon 取自 statusConfigs
const statusDropdownOptions = computed(() => [
  { value: '', label: '全部状态', icon: Filter },
  { value: 'success', label: '成功', icon: CheckCircle2 },
  { value: 'partial_success', label: '部分成功', icon: AlertCircle },
  { value: 'failed', label: '失败', icon: XCircle },
  { value: 'cancelled', label: '已取消', icon: MinusCircle },
  { value: 'waiting', label: '等待中', icon: Clock },
  { value: 'incomplete', label: '未完成', icon: PlayCircle },
])

// 是否存在活动筛选条件，用于控制「重置筛选」按钮的显示
const hasActiveFilters = computed(() =>
  Boolean(filters.category) || Boolean(filters.status) || Boolean((filters.q || '').trim())
)

// 「关键指标」下拉：时间范围选项
const statsDaysOptions = [
  { value: 0, label: '所有时间' },
  { value: 7, label: '近 7 天' },
  { value: 14, label: '近 14 天' },
  { value: 30, label: '近 30 天' },
]

const pageSizeOptions = [30, 50, 100, 200]

const totalPages = computed(() => {
  const size = Math.max(1, Number(limit.value || 50))
  return Math.max(1, Math.ceil(Number(total.value || 0) / size))
})

function normalizeActivityPage(nextPage) {
  const next = Math.min(totalPages.value, Math.max(1, Number(nextPage || 1)))
  return Number.isFinite(next) ? next : 1
}

function onActivityPageChange(value) {
  const next = normalizeActivityPage(value)
  if (next !== Number(page.value || 1)) page.value = next
  loadList()
}

function onActivityPageSizeChange(value) {
  const nextLimit = Number(value || limit.value || 50)
  limit.value = Number.isFinite(nextLimit) && nextLimit > 0 ? nextLimit : 50
  onPageSizeChange()
}

// 一键重置所有筛选条件并立即重新查询
function resetFilters() {
  filters.category = ''
  filters.status = ''
  filters.q = ''
  applyFilters()
}

// 列表渲染统一走这个 effective status：兜底把"实际进了问题作品列表但 status 写成 success"的
// 任务降级成 partial_success，避免列表里出现"入库完成✔"和摘要"已加入问题作品列表"自相矛盾。
const PARTIAL_SUCCESS_KEYWORDS = [
  '加入问题作品列表',
  '已转入问题作品',
  '按重复作品处理',
  '转入问题作品列表'
]

function effectiveStatus(row) {
  if (!row) return ''
  const raw = String(row.status || '')

  // 批次父行的子任务状态感知（lite 路径专用）：
  // 后端 _enrich_lite_items_with_batch_summary 把同 batch_id 的子任务 failed/success
  // /partial_success 计数挂到父行。当父行写日志时 status="success"（创建任务那一刻
  // 成功），但子任务实际有失败 / 部分成功时，把状态升级为 partial_success / failed，
  // 避免出现"批次完成 ✓"但点开看到子任务失败 / 加入问题作品列表的认知错位。
  // 注意只升级 success/completed/partial_success 这三种"看起来 OK"的态；
  // 父行本身已经是 failed/cancelled/error 等"看起来不 OK"的态不动它，
  // 留给 isRowRecovered 的"已修复"逻辑去处理。
  if (raw === 'success' || raw === 'completed' || raw === 'partial_success') {
    const failedChildren = Number(row.child_failed_count || 0)
    const partialChildren = Number(row.child_partial_count || 0)
    const successChildren = Number(row.child_success_count || 0)
    if (failedChildren > 0) {
      // 有失败子任务：还有成功 / 部分成功 → 部分成功；全失败 → 失败
      const okChildren = successChildren + partialChildren
      return okChildren > 0 ? 'partial_success' : 'failed'
    }
    if (partialChildren > 0) {
      // 没失败但子任务里有 partial_success（如"加入问题作品列表"），
      // 父行也应该跟着升级为 partial_success，避免黄变绿。
      return 'partial_success'
    }
  }

  if (raw !== 'success') return raw
  const summary = String(row.summary || '')
  if (PARTIAL_SUCCESS_KEYWORDS.some(kw => summary.includes(kw))) return 'partial_success'
  const detail = row.detail || {}
  if (detail && (detail.linked_subtitle_problem || detail.existing_subtitle_problem)) {
    return 'partial_success'
  }
  const sourceMode = String((detail && detail.source_mode) || '')
  if (sourceMode.endsWith('_existing_subtitle_conflict')) return 'partial_success'
  return raw
}

// 列表行是否要挂"已修复"徽章：后端 aggregator 给覆盖的失败行写了 detail.recovered_by_success
// （或顶层 recovered_badge），lite 路径里 chip 也会带"已恢复"。这里聚合一次，方便模板调用。
const RECOVERY_CATEGORIES = new Set(['extract', 'auto_import', 'process_existing', 'asmr_sync'])

function isRowRecovered(row) {
  if (!row) return false
  const status = String(row.status || '')
  // 只在明确失败的行上挂"已修复"，避免和"成功"行抢眼球
  if (status !== 'failed') return false
  const cat = String(row.category || '')
  if (!RECOVERY_CATEGORIES.has(cat)) return false
  // lite 路径直接给顶层加了 recovered_by_success / recovered_badge；
  // 非 lite（聚合）路径会把同样的标记藏在 detail 里。两条路都兼容。
  if (row.recovered_by_success) return true
  if (row.recovered_badge) return true
  const detail = row.detail || {}
  if (detail && detail.recovered_by_success) return true
  return false
}

// 分类标签 tone → Tailwind 配色（柔和底色 + 内嵌细 ring，避免后台 pill 感）
// 15 种 tone 让所有 category 各占一色（含 default = slate），避免与状态色（success/warn/danger）撞色。
// pink 留着作未来备选，但不再默认给邮件监听用（暖红容易被误读为失败）。
const CATEGORY_TONE_CLASS = {
  indigo: 'cat-tone-indigo',
  violet: 'cat-tone-violet',
  purple: 'cat-tone-purple',
  fuchsia: 'cat-tone-fuchsia',
  amber: 'cat-tone-amber',
  orange: 'cat-tone-orange',
  emerald: 'cat-tone-emerald',
  teal: 'cat-tone-teal',
  lime: 'cat-tone-lime',
  rose: 'cat-tone-rose',
  pink: 'cat-tone-pink',
  sky: 'cat-tone-sky',
  blue: 'cat-tone-blue',
  cyan: 'cat-tone-cyan',
  slate: 'cat-tone-slate'
}

const ACTION_TONE_CLASS = {
  success: 'action-tone-success',
  warn: 'action-tone-warn',
  danger: 'action-tone-danger',
  info: 'action-tone-info',
  neutral: 'action-tone-neutral'
}

const CHIP_TONE_CLASS = {
  success: 'chip-tone-success',
  warn: 'chip-tone-warn',
  danger: 'chip-tone-danger',
  info: 'chip-tone-info',
  neutral: 'chip-tone-neutral'
}

function categoryToneClasses(tone) {
  return CATEGORY_TONE_CLASS[tone] || CATEGORY_TONE_CLASS.slate
}

function actionToneClasses(tone) {
  return ACTION_TONE_CLASS[tone] || ACTION_TONE_CLASS.neutral
}

function chipToneClasses(tone) {
  return CHIP_TONE_CLASS[tone] || CHIP_TONE_CLASS.neutral
}

const palette = ['#0a84ff', '#34c759', '#ff9500', '#af52de', '#ff2d55', '#5ac8fa', '#ffcc00', '#5856d6', '#00c7be', '#8e8e93']
function catPaletteColor(idx) {
  return palette[idx % palette.length]
}

// ==================== 详情抽屉 ====================
const detailDrawerVisible = ref(false)
const selectedRow = ref(null)
const selectedRowId = ref('')

const selectedCategoryConfig = computed(() => categoryConfig(selectedRow.value?.category))
// 状态徽章统一走 effectiveStatus，让"已加入问题作品列表"这种特殊 success 也能在详情面板里
// 显示成"部分成功"，与列表行保持一致。
const selectedStatusConfig = computed(() => statusConfig(effectiveStatus(selectedRow.value)))

// ===== 详情抽屉宽度：用户可拖拽，记忆到 localStorage =====
const DRAWER_WIDTH_MIN = 480
const DRAWER_WIDTH_DEFAULT = 640
const DRAWER_WIDTH_STORAGE_KEY = 'kikoerumanager.activityDetailDrawerWidth'

function getMaxDrawerWidth() {
  if (typeof window === 'undefined') return 1600
  // 留 80px 给左侧主页面，避免拖到完全遮住列表
  return Math.max(DRAWER_WIDTH_MIN, Math.floor(window.innerWidth - 80))
}

function loadDrawerWidth() {
  if (typeof window === 'undefined') return DRAWER_WIDTH_DEFAULT
  try {
    const saved = Number(window.localStorage.getItem(DRAWER_WIDTH_STORAGE_KEY))
    if (Number.isFinite(saved) && saved >= DRAWER_WIDTH_MIN) {
      return Math.min(saved, getMaxDrawerWidth())
    }
  } catch {}
  return DRAWER_WIDTH_DEFAULT
}

const detailDrawerWidth = ref(loadDrawerWidth())
const isDrawerResizing = ref(false)
const drawerResizerRef = ref(null)

let _drawerResizeStartX = 0
let _drawerResizeStartWidth = 0
let _drawerResizeMaxWidth = 0
let _drawerResizeEl = null
let _drawerResizeHandleEl = null
let _drawerResizePendingWidth = 0
let _drawerResizeRafId = 0

function _flushDrawerResize() {
  _drawerResizeRafId = 0
  const w = _drawerResizePendingWidth
  if (_drawerResizeEl) {
    _drawerResizeEl.style.width = `${w}px`
  }
  if (_drawerResizeHandleEl) {
    _drawerResizeHandleEl.style.right = `${w}px`
  }
}

function onDrawerResizeStart(event) {
  _drawerResizeStartX = event.clientX
  _drawerResizeStartWidth = detailDrawerWidth.value
  _drawerResizeMaxWidth = getMaxDrawerWidth()
  // 拖拽过程中只改实际 DOM，不走 Vue 响应式，避免每帧重新渲染整个详情内容
  _drawerResizeEl = document.querySelector('.activity-detail-panel')
  _drawerResizeHandleEl = drawerResizerRef.value || event.currentTarget
  _drawerResizePendingWidth = _drawerResizeStartWidth
  isDrawerResizing.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  document.addEventListener('mousemove', onDrawerResizeMove)
  document.addEventListener('mouseup', onDrawerResizeEnd, { once: true })
}

function onDrawerResizeMove(event) {
  // RTL 抽屉：鼠标向左拖（clientX 减小）= 抽屉变宽
  const delta = _drawerResizeStartX - event.clientX
  const next = Math.min(_drawerResizeMaxWidth, Math.max(DRAWER_WIDTH_MIN, _drawerResizeStartWidth + delta))
  _drawerResizePendingWidth = next
  // 用 rAF 合并多次 mousemove，单帧只改一次 DOM，丝滑很多
  if (!_drawerResizeRafId) {
    _drawerResizeRafId = requestAnimationFrame(_flushDrawerResize)
  }
}

function onDrawerResizeEnd() {
  if (_drawerResizeRafId) {
    cancelAnimationFrame(_drawerResizeRafId)
    _drawerResizeRafId = 0
  }
  // 把最终宽度同步回响应式状态，下次开抽屉用这个值
  if (_drawerResizeEl) {
    _drawerResizeEl.style.width = `${_drawerResizePendingWidth}px`
  }
  if (_drawerResizeHandleEl) {
    _drawerResizeHandleEl.style.right = `${_drawerResizePendingWidth}px`
  }
  detailDrawerWidth.value = _drawerResizePendingWidth
  _drawerResizeEl = null
  _drawerResizeHandleEl = null
  isDrawerResizing.value = false
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  document.removeEventListener('mousemove', onDrawerResizeMove)
  try {
    window.localStorage.setItem(DRAWER_WIDTH_STORAGE_KEY, String(detailDrawerWidth.value))
  } catch {}
}

async function openDetail(row) {
  if (!row || !row.id) return
  selectedRowId.value = String(row.id)
  // 先把 lite 数据塞进抽屉，立刻给反馈，再异步拉完整 detail
  selectedRow.value = { ...row, __isLite: true }
  detailDrawerVisible.value = true
  try {
    const fullRow = await loadDetail(row.id)
    if (fullRow && selectedRowId.value === String(row.id)) {
      selectedRow.value = fullRow
    }
  } catch (err) {
    console.warn('[活动记录] 拉取详情失败', err)
    ElMessage.warning('拉取完整详情失败，已显示基础信息')
    if (selectedRowId.value === String(row.id) && selectedRow.value?.__isLite) {
      const { __isLite, ...fallback } = selectedRow.value
      selectedRow.value = fallback
    }
  }
}

async function openDetailById(id) {
  if (!id) return
  selectedRowId.value = String(id)
  detailDrawerVisible.value = true
  try {
    const fullRow = await loadDetail(id)
    if (fullRow && selectedRowId.value === String(id)) {
      selectedRow.value = fullRow
    }
  } catch (err) {
    console.warn('[活动记录] 拉取子任务详情失败', err)
  }
}

function closeDetail() {
  detailDrawerVisible.value = false
}

// 处理 RichBlock 透传上来的导航事件，跳转到对应工作台
function handleDetailNavigate(payload) {
  if (!payload || typeof payload !== 'object') return
  const { action, row, taskId, folderPath, libraryId, items: batchItems } = payload
  switch (action) {
    case 'subtitle-pair': {
      // 跳到库存页打开字幕配对工作台
      router.push({
        name: 'Library',
        query: {
          subtitleTask: taskId || '',
          subtitlePath: folderPath || '',
          libraryId: libraryId || ''
        }
      })
      detailDrawerVisible.value = false
      break
    }
    case 'subtitle-batch': {
      // 跳到库存页打开字幕批量工作台，携带选中项 key 列表
      const keys = Array.isArray(batchItems) ? batchItems.map((it) => it.key).filter(Boolean) : []
      router.push({
        name: 'Library',
        query: {
          subtitleBatch: keys.join(',') || '1',
          batchActivityId: String(row?.id || '')
        }
      })
      detailDrawerVisible.value = false
      break
    }
    case 'open-circle': {
      router.push({ name: 'CircleCompletion' })
      detailDrawerVisible.value = false
      break
    }
    default:
      // 其他自定义动作暂不处理，方便后续扩展
      break
  }
}

function onDrawerBeforeClose(done) {
  done()
}

function onDrawerClosed() {
  selectedRow.value = null
  selectedRowId.value = ''
}

// ==================== 概览数据 ====================
const statsRangeText = computed(() => {
  const days = Number(stats.days || 0)
  if (!days) return '所有时间'
  return `近 ${days} 天`
})

const sparkPoints = computed(() => {
  const days = Array.isArray(stats.by_day) ? stats.by_day : []
  return days.map(d => ({ date: d.date, count: Number(d.count || 0) }))
})

const sparkBox = { width: 240, height: 56 }
const sparkGradientId = `spark-gradient-${Math.random().toString(36).slice(2, 7)}`

function buildSparkPath(closed) {
  const pts = sparkPoints.value
  if (!pts.length) return ''
  const max = Math.max(1, ...pts.map(p => p.count))
  const min = 0
  const w = sparkBox.width
  const h = sparkBox.height
  const stepX = pts.length > 1 ? w / (pts.length - 1) : 0
  const xy = (i) => {
    const x = stepX * i
    const v = (pts[i].count - min) / Math.max(1, max - min)
    const y = h - 4 - v * (h - 8)
    return [x, y]
  }
  let d = ''
  for (let i = 0; i < pts.length; i += 1) {
    const [x, y] = xy(i)
    d += i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)} ` : `L ${x.toFixed(1)} ${y.toFixed(1)} `
  }
  if (closed) {
    d += `L ${w.toFixed(1)} ${h.toFixed(1)} L 0 ${h.toFixed(1)} Z`
  }
  return d
}

const sparkLinePath = computed(() => buildSparkPath(false))
const sparkAreaPath = computed(() => buildSparkPath(true))
const sparkLastPoint = computed(() => {
  const pts = sparkPoints.value
  if (!pts.length) return { x: 0, y: 0 }
  const max = Math.max(1, ...pts.map(p => p.count))
  const stepX = pts.length > 1 ? sparkBox.width / (pts.length - 1) : 0
  const i = pts.length - 1
  const v = (pts[i].count - 0) / Math.max(1, max)
  return {
    x: stepX * i,
    y: sparkBox.height - 4 - v * (sparkBox.height - 8)
  }
})

// 全部分类（不限于前 5），给可滑动列表用
const allCategories = computed(() => {
  const arr = Array.isArray(stats.by_category) ? stats.by_category : []
  if (!arr.length) return []
  const sorted = [...arr].sort((a, b) => (b.count || 0) - (a.count || 0))
  const max = Math.max(1, ...sorted.map(item => item.count || 0))
  return sorted.map(item => ({
    ...item,
    pct: Math.round(((item.count || 0) / max) * 100)
  }))
})

// 关键指标（原版 8 项：解压大小 / 字幕下载 / 删除大小 / 解压个数 等）
function formatGb(size) {
  const value = Number(size || 0)
  if (!value) return '0.00 GB'
  const gb = value / (1024 ** 3)
  if (gb > 0 && gb < 0.01) return '<0.01 GB'
  return `${gb.toFixed(2)} GB`
}
function formatCount(value) {
  return String(Number(value || 0))
}
function formatMetricHint(text) {
  return Number(stats.days || 0) ? `${stats.days} 天内${text}` : `所有时间${text}`
}
// 数字 + 单位拆分：「8.06 GB」→ {num: '8.06', unit: 'GB'}
function metricSplit(value) {
  const s = String(value ?? '').trim()
  if (!s) return { num: '—', unit: '' }
  const m = s.match(/^([+\-]?[\d.,<>= ]+)\s*([^\s].*?)$/)
  if (m) return { num: m[1].trim(), unit: m[2].trim() }
  return { num: s, unit: '' }
}
const metricCards = computed(() => {
  const m = stats.metrics || {}
  return [
    {
      key: 'subtitle_download_count',
      label: '字幕下载',
      value: formatCount(m.subtitle_download_count),
      hint: formatMetricHint('成功抓取到的字幕文件数'),
      color: '#0a84ff'
    },
    {
      key: 'subtitle_match_count',
      label: '手动配对',
      value: formatCount(m.subtitle_match_count),
      hint: formatMetricHint('手动配对实际应用的组数'),
      color: '#5856d6'
    },
    {
      key: 'subtitle_crawl_count',
      label: '匹配 RJ',
      value: formatCount(m.subtitle_crawl_count),
      hint: formatMetricHint('成功匹配并创建抓取任务的 RJ 目录数'),
      color: '#007aff'
    },
    {
      key: 'subtitle_import_count',
      label: '补配个数',
      value: formatCount(m.subtitle_import_count),
      hint: formatMetricHint('成功补配写入的文件数'),
      color: '#ff9500'
    },
    {
      key: 'extract_count',
      label: '解压个数',
      value: formatCount(m.extract_count),
      hint: formatMetricHint('成功完成的解压任务数'),
      color: '#34c759'
    },
    {
      key: 'delete_count',
      label: '删除个数',
      value: formatCount(m.delete_count),
      hint: formatMetricHint('删除过滤实际删除的项数（含部分成功）'),
      color: '#ff3b30'
    },
    {
      key: 'delete_bytes',
      label: '删除大小',
      value: formatGb(m.delete_bytes || 0),
      hint: formatMetricHint('按删除成功项累计'),
      color: '#ff2d55'
    },
    {
      key: 'extract_bytes',
      label: '解压大小',
      value: formatGb(m.extract_bytes || 0),
      hint: formatMetricHint('解压后产物大小累计'),
      color: '#00c7be'
    }
  ]
})

// ==================== 时间线分组 ====================
const timelineGroups = computed(() => {
  const groups = []
  const map = new Map()
  const today = dayjs().startOf('day')
  const yesterday = today.subtract(1, 'day')

  for (const row of items.value) {
    if (!row || !row.id) continue
    const effective = effectiveStatus(row)
    const statusToneValue = statusTone(effective)
    const catConfig = categoryConfig(row.category)
    const viewRow = {
      ...row,
      _effectiveStatus: effective,
      _statusTone: statusToneValue,
      _statusIcon: statusIcon(effective),
      _categoryIcon: catConfig.icon,
      _categoryIconClass: '',
      _categoryToneClass: categoryToneClasses(catConfig.tone),
      _actionToneClass: actionToneClasses(statusToneValue),
      _humanAction: humanAction(row),
      _isRecovered: isRowRecovered(row),
      _rename: renameSegments(row)
    }
    if (row.category === 'http_download') {
      const httpMeta = getHttpDownloadDisplayMeta(row)
      viewRow._categoryIcon = httpMeta.icon || catConfig.icon
      viewRow._categoryIconClass = httpMeta.icon ? 'activity-platform-icon' : ''
      viewRow.category_label = httpMeta.label && httpMeta.label !== 'HTTP'
        ? `${httpMeta.label} 下载`
        : 'HTTP 下载'
    }
    const dt = row.created_at ? dayjs(row.created_at) : null
    let key
    let label
    if (!dt || !dt.isValid()) {
      key = '__unknown'
      label = '未知时间'
    } else {
      const start = dt.startOf('day')
      key = start.format('YYYY-MM-DD')
      if (start.isSame(today)) label = '今天'
      else if (start.isSame(yesterday)) label = '昨天'
      else if (start.isAfter(today.subtract(7, 'day'))) label = `${start.format('M月D日')}（${weekDayName(start)}）`
      else if (start.isAfter(today.subtract(30, 'day'))) label = start.format('M月D日')
      else label = start.format('YYYY年M月D日')
    }
    if (!map.has(key)) {
      const group = { key, label, items: [] }
      map.set(key, group)
      groups.push(group)
    }
    map.get(key).items.push(viewRow)
  }
  return groups
})

function weekDayName(dt) {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][dt.day()]
}

function formatTime(value) {
  if (!value) return ''
  const dt = dayjs(value)
  if (!dt.isValid()) return ''
  return dt.format('HH:mm')
}

function formatDateTime(value) {
  if (!value) return ''
  const dt = dayjs(value)
  if (!dt.isValid()) return ''
  return dt.format('YYYY-MM-DD HH:mm:ss')
}

function formatShortDate(value) {
  if (!value) return ''
  const dt = dayjs(value)
  if (!dt.isValid()) return ''
  return dt.format('M/D')
}

function formatNumber(value) {
  const n = Number(value || 0)
  if (!n) return '0'
  return n.toLocaleString('zh-CN')
}

const lastLoadedAtText = computed(() => {
  const ts = Number(lastLoadedAt.value || 0)
  if (!ts) return ''
  return `上次刷新 ${dayjs(ts).format('HH:mm:ss')}`
})

function compactPath(path) {
  const text = String(path || '').trim()
  if (!text) return ''
  if (text.length <= 64) return text
  const head = text.slice(0, 18)
  const tail = text.slice(-44)
  return `${head}…${tail}`
}

function onClearSearch() {
  filters.q = ''
  applyFilters()
}

// ==================== humanAction 简化版 ====================
// 旧版页面有 200+ 行逐 action 翻译；lite 模式后端已经提供 summary，
// 这里只对常见 status 给个简短标题，兜底用 status 标签。
function humanAction(row) {
  if (!row) return ''
  const cat = String(row.category || '')
  const action = String(row.action || '')
  // 走 effectiveStatus，让"已加入问题作品列表"等情况也能展示"部分入库"
  const status = effectiveStatus(row)

  // 一些高频组合给个更友好的中文动作名（足够在 chip 行展示）
  if (cat === 'subtitle_crawl') {
    if (action === 'batch_start') return statusLabel(status)
    if (status === 'success') return '抓取完成'
    if (status === 'failed') return '抓取失败'
    if (status === 'waiting') return '等待中'
  }
  if (cat === 'subtitle_pair') {
    return status === 'success' ? '配对完成' : '手动配对'
  }
  if (cat === 'subtitle_import') {
    return status === 'success' ? '补配完成' : '补配失败'
  }
  if (cat === 'extract') {
    return status === 'success' ? '解压完成' : '解压失败'
  }
  if (cat === 'auto_import') {
    if (status === 'success') return '入库完成'
    if (status === 'partial_success') {
      // 真有失败子任务才叫"部分入库"；纯转入问题作品 / 软失败 → "转入问题作品"
      return isPurelyProblemListPartial(row) ? '转入问题作品' : '部分入库'
    }
    if (status === 'failed') return '入库失败'
    if (status === 'incomplete') return '未正常结束'
  }
  if (cat === 'process_existing') {
    if (status === 'success') return '处理完成'
    if (status === 'partial_success') return '部分处理'
    if (status === 'failed') return '处理失败'
    return statusLabel(status)
  }
  if (cat === 'asmr_sync') {
    if (action === 'session_completed' || status === 'success') return 'ASMR 下载完成'
    if (action === 'session_partial_failed' || status === 'partial_success') return 'ASMR 部分失败'
    if (status === 'failed') return 'ASMR 下载失败'
    return statusLabel(status)
  }
  if (cat === 'upload') {
    if (status === 'success') return '上传完成'
    if (status === 'failed') return '上传失败'
    if (status === 'cancelled') return '上传取消'
  }
  if (cat === 'pipeline_filter') {
    if (action === 'filter_delete_preview') return '删除预审'
    if (action === 'filter_delete_apply') return '删除执行'
    if (action === 'filter_delete_preview_retry') return '失败项重试'
    return statusLabel(status)
  }
  // 重命名 / 删除：左侧 category chip 已经写了"重命名 / 删除"，右侧再写一遍纯属噪音。
  // 这里只输出状态文案（完成 / 失败 / 部分成功），让用户的注意力直接落到下面的对比块。
  if (cat === 'pipeline_rename' || cat === 'pipeline_delete') {
    if (status === 'success') return '完成'
    if (status === 'partial_success') return '部分成功'
    if (status === 'failed') return '失败'
    if (status === 'cancelled') return '已取消'
    return statusLabel(status)
  }
  if (cat === 'circle_completion') {
    if (action === 'index_completed') return '索引完成'
    if (action === 'refresh_selected_works') return '刷新作品'
    if (action === 'download_batch_start') return '创建下载任务'
    return statusLabel(status)
  }
  if (cat === 'email_watcher') {
    if (action === 'fetch_check') return '监视邮件'
    if (action === 'circle_index_triggered') return '触发索引'
    return statusLabel(status)
  }
  return statusLabel(status)
}

// ==================== 重命名行：单行高亮 ====================
// 截图反馈：摘要里 'oldName -> newName' 一行平铺直叙，箭头不显眼。
// 这里把 oldName / newName 拆出来，让模板渲染成一行内"灰名 + 醒目箭头 + 绿名"。
// 单条 api_rename / 单条 manual_rename 才需要美化；批量行 (batch_*) 仍用普通 summary。
//
// 数据来源优先级：
// 1) row.detail.old_name / new_name —— 后端 lite 路径会精简下发（routes.py / activity_log_lite.py）
// 2) 从 row.summary 字符串里解析 " -> " —— 后端没重启 / 旧数据兜底用
function renameSegments(row) {
  if (!row || row.category !== 'pipeline_rename') return null
  const action = String(row.action || '')
  if (action === 'batch_api_rename' || action === 'batch_manual_rename') return null

  const failed = String(row.status || '') === 'failed'
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  let oldName = String(detail.old_name || '').trim()
  let newName = String(detail.new_name || '').trim()
  let reason = String(detail.error || detail.reason || '').trim()

  // 兜底：从 summary 字符串里 split ' -> '。后端模板写的就是 'old -> new'，失败时尾巴加 '：err'。
  if (!oldName && !newName) {
    const summary = String(row.summary || '').trim()
    const arrowIdx = summary.indexOf(' -> ')
    if (arrowIdx > 0) {
      oldName = summary.slice(0, arrowIdx).trim()
      let rest = summary.slice(arrowIdx + 4).trim()
      if (failed && !reason) {
        // failed summary 形态：'old -> new：错误描述'，把 '：' 后面切给 reason
        const colonIdx = rest.lastIndexOf('：')
        if (colonIdx > 0) {
          reason = rest.slice(colonIdx + 1).trim()
          rest = rest.slice(0, colonIdx).trim()
        }
      }
      newName = rest
    }
  }

  if (!oldName && !newName) return null
  return {
    oldName: oldName || '原名称未知',
    newName: newName || (failed ? '（保留原名）' : '未命名'),
    failed,
    reason: failed ? reason : '',
  }
}

// ==================== 归档压缩 ====================
const compactEstimate = ref(null)

const compactSavingsLabel = computed(() => {
  const est = compactEstimate.value
  if (!est) return ''
  const saved = Number(est.estimated_saved_bytes || 0)
  if (saved <= 0) return ''
  const mb = saved / 1024 / 1024
  if (mb < 0.5) return ''
  return `预计省 ${mb.toFixed(1)} MB`
})

const compactHint = computed(() => {
  const est = compactEstimate.value
  if (!est) return '裁剪 30 天前的大型 detail（不删除任何记录），让数据库继续轻盈'
  const total = Number(est.estimated_compactable_total || 0)
  if (!total) return '当前没有需要归档的旧记录'
  const mb = (Number(est.estimated_saved_bytes || 0) / 1024 / 1024).toFixed(1)
  return `估算可压缩 ${total} 行，预计释放 ${mb} MB`
})

async function refreshCompactEstimate() {
  try {
    compactEstimate.value = await api.activityLog.compactEstimate({ older_than_days: 30 })
  } catch (err) {
    console.warn('[活动记录] 压缩估算失败', err)
  }
}

let compactRunning = false
async function onCompactClick() {
  if (compactRunning) return
  compactRunning = true
  try {
    let totalUpdated = 0
    let totalSaved = 0
    let safety = 10
    while (safety-- > 0) {
      const result = await api.activityLog.compact({ older_than_days: 30, time_budget_seconds: 5 })
      totalUpdated += Number(result.updated || 0)
      totalSaved += Number(result.saved_bytes || 0)
      if (result.done) break
    }
    invalidateDetail()
    if (totalUpdated > 0) {
      const mb = (totalSaved / 1024 / 1024).toFixed(2)
      ElMessage.success(`已归档 ${totalUpdated} 条旧记录，释放 ${mb} MB`)
    } else {
      ElMessage.info('当前没有需要归档的旧记录')
    }
    await Promise.all([refreshCompactEstimate(), loadAll()])
  } catch (err) {
    console.error('[活动记录] 归档失败', err)
    ElMessage.error('归档失败，请稍后再试')
  } finally {
    compactRunning = false
  }
}

// ==================== 生命周期 / 软刷新 ====================
let visibilityHandler = null

onMounted(async () => {
  loadAll()
  refreshCompactEstimate()
  // 加载搜索引擎状态：用于显示徽章 + 升级提示。如果发现已经在重建则启动进度轮询。
  await loadSearchStatus()
  if (searchStatus.value?.rebuild?.running) {
    startSearchStatusPolling()
  }
  if (typeof document !== 'undefined') {
    visibilityHandler = () => handleVisibilityRefresh()
    document.addEventListener('visibilitychange', visibilityHandler)
  }
})

onActivated(() => {
  if (shouldSoftRefresh()) loadAll()
})

onBeforeUnmount(() => {
  if (visibilityHandler && typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', visibilityHandler)
    visibilityHandler = null
  }
  // 清掉 debounce 定时器，避免组件销毁后仍触发 applyFilters
  if (_searchDebounceTimer) {
    clearTimeout(_searchDebounceTimer)
    _searchDebounceTimer = null
  }
  // 清掉搜索引擎状态轮询定时器
  stopSearchStatusPolling()
  // 兜底：组件销毁时清掉可能残留的抽屉拖拽监听
  document.removeEventListener('mousemove', onDrawerResizeMove)
  if (typeof document !== 'undefined' && document.body) {
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
  }
})

watch(() => filters.q, (val, old) => {
  // 清空搜索：立即触发 applyFilters，不再等 debounce
  if (val === '' && old !== '') {
    if (_searchDebounceTimer) {
      clearTimeout(_searchDebounceTimer)
      _searchDebounceTimer = null
    }
    applyFilters()
  }
})

watch(totalPages, (val) => {
  if (Number(page.value || 1) > val) {
    page.value = val
  }
})
</script>

<style scoped>
/* ============= 新版审计工作台布局 ============= */
.activity-page,
.activity-detail-overlay {
  --activity-bg: #f6f7f8;
  --activity-surface: #ffffff;
  --activity-surface-soft: #f4f4f5;
  --activity-surface-raised: #fafafa;
  --activity-border: rgba(24, 24, 27, 0.1);
  --activity-border-strong: rgba(24, 24, 27, 0.18);
  --activity-text: #18181b;
  --activity-muted: #71717a;
  --activity-subtle: #a1a1aa;
  --activity-accent: #52525b;
  --activity-shadow: 0 18px 44px rgba(24, 24, 27, 0.08);
  --activity-success: #059669;
  --activity-warn: #b45309;
  --activity-danger: #dc2626;
  --activity-info: #4b5563;
}

.activity-page {
  position: relative;
  max-width: 1480px;
  margin: 0 auto;
  padding: 12px 24px 40px;
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    'SF Pro Text',
    'Segoe UI',
    Roboto,
    'Helvetica Neue',
    Arial,
    sans-serif;
  color: var(--activity-text);
}

:deep(.activity-loading-mask) {
  inset: 0;
  border-radius: 0;
  background: rgba(250, 250, 250, 0.78);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  z-index: 10;
}

.page-head-search-wrap {
  display: inline-flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  min-width: 280px;
}

.page-head-search {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 280px;
  height: 36px;
  padding: 0 56px 0 34px;
  border: 1px solid var(--activity-border);
  border-radius: 10px;
  background: var(--activity-surface);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.page-head-search:focus-within {
  border-color: var(--activity-border-strong);
  box-shadow: 0 0 0 3px rgba(82, 82, 91, 0.1);
}

.page-head-search-icon {
  position: absolute;
  left: 11px;
  color: var(--activity-muted);
  pointer-events: none;
}

.page-head-search-input {
  width: 100%;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--activity-text);
  font-size: 13px;
}

.page-head-search-input::placeholder {
  color: var(--activity-subtle);
}

.page-head-search-spinner {
  position: absolute;
  right: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--activity-muted);
  pointer-events: none;
}

.page-head-search-clear {
  position: absolute;
  right: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--activity-muted);
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.page-head-search-clear:hover {
  background: var(--activity-surface-soft);
  color: var(--activity-text);
}

.search-engine-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 11px;
  line-height: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.search-engine-hint .hint-icon,
.search-engine-hint .hint-action {
  flex-shrink: 0;
}

.search-engine-hint .hint-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.search-engine-hint .hint-action {
  padding: 1px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: 11px;
  font-weight: 680;
  cursor: pointer;
  transition: background-color 0.18s ease, opacity 0.18s ease;
}

.search-engine-hint .hint-action:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.search-engine-hint.tone-info {
  color: #3f3f46;
  background: rgba(113, 113, 122, 0.1);
  border-color: rgba(113, 113, 122, 0.2);
}

.search-engine-hint.tone-warn {
  color: #92400e;
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.24);
}

.search-engine-hint.tone-danger {
  color: #be123c;
  background: rgba(244, 63, 94, 0.1);
  border-color: rgba(244, 63, 94, 0.24);
}

.page-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid var(--activity-border);
  border-radius: 10px;
  background: var(--activity-surface);
  color: var(--activity-text);
  font-size: 13px;
  font-weight: 680;
  white-space: nowrap;
  cursor: pointer;
  overflow: hidden;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
}

.page-head-btn-icon-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
}

.page-head-btn :deep(svg) {
  flex-shrink: 0;
}

.page-head-btn :deep(.page-head-btn-icon) {
  transition: transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}

.page-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(24, 24, 27, 0.08);
}

.page-head-btn:active {
  transform: scale(0.96);
}

.page-head-btn:disabled {
  cursor: not-allowed;
  opacity: 0.68;
}

.page-head-btn.primary {
  border-color: transparent;
  background: #27272a;
  color: #fafafa;
}

.page-head-btn.ghost:hover {
  background: var(--activity-surface-soft);
  border-color: var(--activity-border-strong);
}

.page-head-btn.btn-refresh:hover:not(:disabled) :deep(.page-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
}

.page-head-btn.btn-archive:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: translateY(1px) scale(1.12);
}

.page-head-btn-label {
  display: inline-block;
  text-align: center;
}

.page-head-btn.primary .page-head-btn-label {
  min-width: 56px;
}

.page-head-btn.ghost .page-head-btn-label {
  min-width: 70px;
}

.page-head-btn-icon-slot {
  position: absolute;
  top: 50%;
  left: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transform: translate(-50%, -50%) scale(0.5) rotate(-90deg);
  opacity: 0;
  pointer-events: none;
  transition:
    opacity 0.16s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.page-head-btn-icon-slot.is-visible {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1) rotate(0deg);
}

.page-head-btn-hint {
  margin-left: 4px;
  padding: 2px 6px;
  border-radius: 999px;
  background: rgba(82, 82, 91, 0.1);
  color: var(--activity-muted);
  font-size: 10px;
  font-weight: 720;
}

.activity-command-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--activity-border);
  border-radius: 16px;
  background: var(--activity-surface);
}

.activity-kicker {
  display: block;
  color: var(--activity-muted);
  font-size: 10.5px;
  font-weight: 720;
  letter-spacing: 0.12em;
  line-height: 1;
  text-transform: uppercase;
}

.activity-range-copy {
  min-width: 0;
}

.activity-range-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.activity-range-line strong {
  color: var(--activity-text);
  font-size: 18px;
  font-weight: 780;
  line-height: 1.1;
}

.activity-range-line span {
  color: var(--activity-muted);
  font-size: 12px;
  font-weight: 650;
}

.activity-insight-board {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.activity-metric-rail {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 8px;
}

.activity-metric-card {
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid var(--activity-border);
  border-radius: 12px;
  background: var(--activity-surface);
  cursor: help;
}

.activity-metric-label {
  display: block;
  color: var(--activity-muted);
  font-size: 11px;
  font-weight: 680;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-metric-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 6px;
  min-width: 0;
  font-size: 18px;
  font-weight: 780;
  line-height: 1.08;
  font-variant-numeric: tabular-nums;
}

.activity-metric-value span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-metric-value small {
  flex: 0 0 auto;
  color: var(--activity-muted);
  font-size: 10px;
  font-weight: 720;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.activity-context-band {
  display: grid;
  grid-template-columns: minmax(240px, 0.95fr) minmax(300px, 1.35fr) minmax(280px, 0.9fr);
  gap: 10px;
  align-items: stretch;
}

.activity-trend-panel,
.activity-category-panel,
.activity-filter-panel {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--activity-border);
  border-radius: 14px;
  background: var(--activity-surface);
}

.activity-panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  color: var(--activity-muted);
  font-size: 12px;
  font-weight: 700;
}

.activity-panel-title strong {
  color: var(--activity-text);
  font-size: 12px;
  font-weight: 760;
  font-variant-numeric: tabular-nums;
}

.activity-sparkline {
  width: 100%;
  height: 78px;
}

.activity-sparkline-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.activity-sparkline-foot {
  display: flex;
  justify-content: space-between;
  color: var(--activity-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.activity-category-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  max-height: 132px;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(113, 113, 122, 0.28) transparent;
}

.activity-category-list::-webkit-scrollbar {
  width: 4px;
}

.activity-category-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(113, 113, 122, 0.28);
}

.activity-category-row {
  display: grid;
  grid-template-columns: 8px minmax(76px, 1fr) minmax(58px, 0.8fr) 38px;
  gap: 7px;
  align-items: center;
  min-width: 0;
  color: var(--activity-text);
  font-size: 12px;
}

.activity-category-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.activity-category-name {
  color: var(--activity-text);
  font-weight: 620;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-category-track {
  height: 6px;
  border-radius: 999px;
  background: var(--activity-surface-soft);
  overflow: hidden;
}

.activity-category-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  opacity: 0.9;
  transition: width 0.35s ease;
}

.activity-category-count {
  color: var(--activity-muted);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.activity-filter-controls {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.activity-filter-controls :deep(.app-dd-root),
.activity-filter-controls :deep(.app-dd-trigger-anchor),
.activity-filter-controls :deep(.app-dd-trigger) {
  width: 100%;
}

.activity-filter-reset {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--activity-border);
  border-radius: 9px;
  background: var(--activity-surface-raised);
  color: var(--activity-muted);
  font-size: 12px;
  font-weight: 680;
  cursor: pointer;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease;
}

.activity-filter-reset:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--activity-border-strong);
  background: var(--activity-surface-soft);
  color: var(--activity-text);
}

.activity-filter-reset:active {
  transform: scale(0.96);
}

.activity-reader {
  min-width: 0;
  border: 1px solid var(--activity-border);
  border-radius: 18px;
  background: var(--activity-surface);
  overflow: hidden;
  box-shadow: var(--activity-shadow);
}

.activity-reader-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--activity-border);
  background: var(--activity-surface);
}

.activity-reader-head h2 {
  margin: 3px 0 0;
  color: var(--activity-text);
  font-size: 18px;
  font-weight: 780;
  line-height: 1.2;
}

.activity-reader-meta {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  color: var(--activity-muted);
  font-size: 12px;
  font-weight: 650;
}

.activity-reader-meta span + span::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 3px;
  margin-right: 8px;
  border-radius: 999px;
  background: var(--activity-subtle);
  vertical-align: middle;
}

.activity-timeline-shell {
  min-height: 430px;
  padding: 18px 20px 8px;
  background: var(--activity-surface);
}

.activity-timeline {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.activity-day-section {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.activity-day-header {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-top: 7px;
}

.activity-day-label {
  color: var(--activity-text);
  font-size: 14px;
  font-weight: 780;
  line-height: 1.2;
}

.activity-day-count {
  color: var(--activity-muted);
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.activity-log-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.activity-log-row {
  --activity-row-accent: var(--activity-subtle);
  position: relative;
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) 24px;
  gap: 12px;
  align-items: stretch;
  min-width: 0;
  padding: 12px 12px 12px 0;
  border: 1px solid var(--activity-border);
  border-radius: 14px;
  background: var(--activity-surface-raised);
  cursor: pointer;
  outline: none;
  overflow: hidden;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease;
  contain: layout paint;
}

.activity-log-row:hover,
.activity-log-row.is-active,
.activity-log-row:focus-visible {
  border-color: var(--activity-border-strong);
  background: color-mix(in srgb, var(--activity-surface-raised) 86%, var(--activity-row-accent) 14%);
}

.activity-log-row:active {
  border-color: color-mix(in srgb, var(--activity-row-accent) 48%, var(--activity-border-strong));
}

.activity-log-row.tone-success { --activity-row-accent: var(--activity-success); }
.activity-log-row.tone-warn { --activity-row-accent: var(--activity-warn); }
.activity-log-row.tone-danger { --activity-row-accent: var(--activity-danger); }
.activity-log-row.tone-info { --activity-row-accent: var(--activity-info); }
.activity-log-row.tone-neutral { --activity-row-accent: var(--activity-subtle); }

.activity-log-time {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
  padding-left: 14px;
  color: var(--activity-muted);
  font-size: 11px;
  font-weight: 720;
  font-variant-numeric: tabular-nums;
}

.activity-log-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border: 1px solid color-mix(in srgb, var(--activity-row-accent) 44%, transparent);
  border-radius: 50%;
  background: var(--activity-surface);
  color: var(--activity-row-accent);
}

.activity-log-content {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.activity-log-topline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  min-width: 0;
}

.activity-category-chip,
.activity-rj-chip,
.activity-flag-chip,
.activity-recovery-chip,
.activity-meta-chip,
.activity-path-chip {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  border-radius: 8px;
  line-height: 1;
}

.activity-category-chip {
  gap: 5px;
  padding: 4px 8px;
  border: 1px solid var(--tw-ring-color);
  font-size: 11px;
  font-weight: 720;
}

.activity-platform-icon {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
  border-radius: 2px;
  object-fit: contain;
}

.activity-action-label {
  color: var(--activity-muted);
  font-size: 12px;
  font-weight: 780;
  line-height: 1;
}

.activity-rj-chip {
  padding: 4px 7px;
  border: 1px solid var(--activity-border);
  background: var(--activity-surface-soft);
  color: var(--activity-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 0;
}

.activity-flag-chip {
  padding: 3px 7px;
  border: 1px solid var(--activity-border);
  background: transparent;
  color: var(--activity-muted);
  font-size: 10.5px;
  font-weight: 720;
}

.activity-flag-chip.tone-warn {
  border-color: rgba(245, 158, 11, 0.24);
  color: var(--activity-warn);
}

.activity-flag-chip.tone-info {
  border-color: rgba(82, 82, 91, 0.22);
  color: var(--activity-info);
}

.activity-recovery-chip {
  gap: 4px;
  padding: 3px 7px;
  border: 1px solid rgba(16, 185, 129, 0.25);
  background: rgba(16, 185, 129, 0.09);
  color: #047857;
  font-size: 10.5px;
  font-weight: 760;
}

.activity-log-summary {
  max-width: 100%;
  color: var(--activity-text);
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.activity-rename-summary {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
  letter-spacing: 0;
  word-break: break-all;
}

.activity-rename-old,
.activity-rename-new {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 6px;
  font-weight: 720;
}

.activity-rename-old {
  color: #92400e;
  background: rgba(245, 158, 11, 0.14);
}

.activity-rename-arrow {
  display: inline-block;
  margin: 0 6px;
  color: var(--activity-muted);
  font-weight: 760;
}

.activity-rename-new {
  color: #047857;
  background: rgba(16, 185, 129, 0.12);
}

.activity-rename-summary.is-failed .activity-rename-arrow,
.activity-rename-reason {
  color: #be123c;
}

.activity-rename-summary.is-failed .activity-rename-new {
  color: #be123c;
  background: rgba(244, 63, 94, 0.1);
}

.activity-rename-reason {
  margin-left: 8px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 11.5px;
}

.activity-log-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  min-width: 0;
}

.activity-meta-chip {
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid var(--tw-ring-color);
  font-size: 11px;
}

.activity-meta-chip span {
  opacity: 0.74;
  font-weight: 650;
}

.activity-meta-chip strong {
  font-weight: 780;
  font-variant-numeric: tabular-nums;
}

.activity-path-chip {
  gap: 5px;
  max-width: min(520px, 100%);
  padding: 4px 8px;
  background: var(--activity-surface-soft);
  color: var(--activity-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
}

.activity-path-chip span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-log-cue {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--activity-subtle);
  transition: color 0.18s ease;
}

.activity-log-row:hover .activity-log-cue,
.activity-log-row:focus-visible .activity-log-cue {
  color: var(--activity-muted);
}

.cat-tone-indigo { background: rgba(99, 102, 241, 0.1); color: #4338ca; --tw-ring-color: rgba(99, 102, 241, 0.24); }
.cat-tone-violet { background: rgba(139, 92, 246, 0.1); color: #6d28d9; --tw-ring-color: rgba(139, 92, 246, 0.24); }
.cat-tone-purple { background: rgba(147, 51, 234, 0.1); color: #7e22ce; --tw-ring-color: rgba(147, 51, 234, 0.24); }
.cat-tone-fuchsia { background: rgba(217, 70, 239, 0.1); color: #a21caf; --tw-ring-color: rgba(217, 70, 239, 0.24); }
.cat-tone-amber { background: rgba(245, 158, 11, 0.12); color: #92400e; --tw-ring-color: rgba(245, 158, 11, 0.26); }
.cat-tone-orange { background: rgba(249, 115, 22, 0.11); color: #9a3412; --tw-ring-color: rgba(249, 115, 22, 0.25); }
.cat-tone-emerald { background: rgba(16, 185, 129, 0.1); color: #047857; --tw-ring-color: rgba(16, 185, 129, 0.24); }
.cat-tone-teal { background: rgba(20, 184, 166, 0.1); color: #0f766e; --tw-ring-color: rgba(20, 184, 166, 0.24); }
.cat-tone-lime { background: rgba(132, 204, 22, 0.12); color: #4d7c0f; --tw-ring-color: rgba(132, 204, 22, 0.25); }
.cat-tone-rose { background: rgba(244, 63, 94, 0.1); color: #be123c; --tw-ring-color: rgba(244, 63, 94, 0.25); }
.cat-tone-pink { background: rgba(236, 72, 153, 0.1); color: #be185d; --tw-ring-color: rgba(236, 72, 153, 0.24); }
.cat-tone-sky { background: rgba(14, 165, 233, 0.1); color: #0369a1; --tw-ring-color: rgba(14, 165, 233, 0.24); }
.cat-tone-blue { background: rgba(59, 130, 246, 0.1); color: #1d4ed8; --tw-ring-color: rgba(59, 130, 246, 0.24); }
.cat-tone-cyan { background: rgba(6, 182, 212, 0.1); color: #0e7490; --tw-ring-color: rgba(6, 182, 212, 0.24); }
.cat-tone-slate { background: rgba(100, 116, 139, 0.1); color: #475569; --tw-ring-color: rgba(100, 116, 139, 0.22); }

.action-tone-success { color: var(--activity-success); }
.action-tone-warn { color: var(--activity-warn); }
.action-tone-danger { color: var(--activity-danger); }
.action-tone-info { color: var(--activity-info); }
.action-tone-neutral { color: var(--activity-muted); }

.chip-tone-success { background: rgba(16, 185, 129, 0.09); color: #047857; --tw-ring-color: rgba(16, 185, 129, 0.2); }
.chip-tone-warn { background: rgba(245, 158, 11, 0.1); color: #92400e; --tw-ring-color: rgba(245, 158, 11, 0.22); }
.chip-tone-danger { background: rgba(244, 63, 94, 0.09); color: #be123c; --tw-ring-color: rgba(244, 63, 94, 0.22); }
.chip-tone-info { background: rgba(82, 82, 91, 0.09); color: #52525b; --tw-ring-color: rgba(82, 82, 91, 0.2); }
.chip-tone-neutral { background: rgba(113, 113, 122, 0.1); color: #52525b; --tw-ring-color: rgba(113, 113, 122, 0.2); }

.activity-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--activity-border);
  background: var(--activity-surface);
}

.activity-pager {
  width: 100%;
  margin-top: 0;
}

.activity-pager :deep(.el-pagination) {
  width: 100%;
  justify-content: flex-end;
}

.activity-detail-overlay {
  position: fixed;
  inset: 0;
  z-index: 2600;
  display: flex;
  justify-content: flex-end;
  background: rgba(24, 24, 27, 0.28);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.activity-detail-panel {
  height: 100dvh;
  max-width: calc(100vw - 72px);
  min-width: min(480px, 100vw);
  overflow: hidden;
  border-left: 1px solid var(--activity-border);
  background: var(--activity-surface);
  box-shadow: -28px 0 60px rgba(24, 24, 27, 0.18);
}

.activity-detail-panel :deep(.detail-body) {
  height: 100dvh;
  background: var(--activity-surface);
  color: var(--activity-text);
}

.activity-overlay-enter-active,
.activity-overlay-leave-active {
  transition: opacity 0.22s ease;
}

.activity-overlay-enter-active .activity-detail-panel,
.activity-overlay-leave-active .activity-detail-panel {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}

.activity-overlay-enter-from,
.activity-overlay-leave-to {
  opacity: 0;
}

.activity-overlay-enter-from .activity-detail-panel,
.activity-overlay-leave-to .activity-detail-panel {
  transform: translateX(28px);
}

.activity-drawer-resizer-fixed {
  position: fixed;
  top: 0;
  bottom: 0;
  width: 10px;
  transform: translateX(50%);
  cursor: col-resize;
  z-index: 2700;
  background: transparent;
  user-select: none;
}

.activity-drawer-resizer-fixed::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  right: 4px;
  background: rgba(113, 113, 122, 0.28);
  transition: background 0.18s ease, left 0.18s ease, right 0.18s ease;
}

.activity-drawer-resizer-fixed:hover::before,
.activity-drawer-resizer-fixed.is-active::before {
  background: #71717a;
  left: 3px;
  right: 3px;
}

:global(html.kikoerumanager-dark .activity-page),
:global(html.kikoerumanager-dark .activity-detail-overlay) {
  --activity-bg: #08090c;
  --activity-surface: #111216;
  --activity-surface-soft: #202126;
  --activity-surface-raised: #17181d;
  --activity-border: rgba(255, 255, 255, 0.11);
  --activity-border-strong: rgba(255, 255, 255, 0.2);
  --activity-text: #f4f4f5;
  --activity-muted: rgba(212, 212, 216, 0.68);
  --activity-subtle: rgba(161, 161, 170, 0.7);
  --activity-accent: #d4d4d8;
  --activity-shadow: none;
  --activity-success: #8ddfbb;
  --activity-warn: #f4ce75;
  --activity-danger: #f3a2a8;
  --activity-info: #c8c8cf;
}

:global(html.kikoerumanager-dark .activity-page) {
  color: var(--activity-text);
}

:global(html.kikoerumanager-dark .activity-page .page-head-search),
:global(html.kikoerumanager-dark .activity-page .page-head-btn.ghost) {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: var(--activity-text) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .activity-page .page-head-search:focus-within) {
  background: #1d1e23 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.06) !important;
}

:global(html.kikoerumanager-dark .activity-page .page-head-search-input) {
  color: #ffffff;
  background: transparent !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .activity-page .page-head-search-input::placeholder) {
  color: rgba(212, 212, 216, 0.55);
}

:global(html.kikoerumanager-dark .activity-page .page-head-search-icon),
:global(html.kikoerumanager-dark .activity-page .page-head-search-spinner),
:global(html.kikoerumanager-dark .activity-page .page-head-search-clear) {
  color: var(--activity-muted);
}

:global(html.kikoerumanager-dark .activity-page .page-head-btn.primary) {
  background: #17181d;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12);
  color: #d7dde7;
  box-shadow: none;
}

:global(html.kikoerumanager-dark .activity-page .page-head-btn.primary:hover) {
  background: #202126;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .activity-page .activity-log-row:hover),
:global(html.kikoerumanager-dark .activity-page .activity-log-row.is-active),
:global(html.kikoerumanager-dark .activity-page .activity-log-row:focus-visible) {
  box-shadow: none;
}

:global(html.kikoerumanager-dark .activity-detail-overlay) {
  background: rgba(0, 0, 0, 0.48);
}

:global(html.kikoerumanager-dark .activity-detail-panel) {
  background: #0b0c10 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  box-shadow: -28px 0 60px rgba(0, 0, 0, 0.42) !important;
}

:global(html.kikoerumanager-dark .activity-page .search-engine-hint) {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark .activity-page .search-engine-hint.tone-info),
:global(html.kikoerumanager-dark .activity-page .search-engine-hint.tone-warn),
:global(html.kikoerumanager-dark .activity-page .search-engine-hint.tone-danger) {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark .activity-page .search-engine-hint .hint-action) {
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark .activity-page .search-engine-hint .hint-action:hover) {
  background: #202126 !important;
}

:global(html.kikoerumanager-dark) .cat-tone-indigo { background: rgba(129, 140, 248, 0.16); color: #c7d2fe; --tw-ring-color: rgba(129, 140, 248, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-violet { background: rgba(167, 139, 250, 0.16); color: #ddd6fe; --tw-ring-color: rgba(167, 139, 250, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-purple { background: rgba(192, 132, 252, 0.15); color: #e9d5ff; --tw-ring-color: rgba(192, 132, 252, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-fuchsia { background: rgba(232, 121, 249, 0.14); color: #f5d0fe; --tw-ring-color: rgba(232, 121, 249, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-amber { background: rgba(251, 191, 36, 0.15); color: #fde68a; --tw-ring-color: rgba(251, 191, 36, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-orange { background: rgba(251, 146, 60, 0.15); color: #fed7aa; --tw-ring-color: rgba(251, 146, 60, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-emerald { background: rgba(52, 211, 153, 0.14); color: #a7f3d0; --tw-ring-color: rgba(52, 211, 153, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-teal { background: rgba(45, 212, 191, 0.14); color: #99f6e4; --tw-ring-color: rgba(45, 212, 191, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-lime { background: rgba(163, 230, 53, 0.13); color: #d9f99d; --tw-ring-color: rgba(163, 230, 53, 0.25); }
:global(html.kikoerumanager-dark) .cat-tone-rose { background: rgba(251, 113, 133, 0.14); color: #fecdd3; --tw-ring-color: rgba(251, 113, 133, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-pink { background: rgba(244, 114, 182, 0.14); color: #fbcfe8; --tw-ring-color: rgba(244, 114, 182, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-sky { background: rgba(56, 189, 248, 0.13); color: #bae6fd; --tw-ring-color: rgba(56, 189, 248, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-blue { background: rgba(96, 165, 250, 0.14); color: #bfdbfe; --tw-ring-color: rgba(96, 165, 250, 0.28); }
:global(html.kikoerumanager-dark) .cat-tone-cyan { background: rgba(34, 211, 238, 0.13); color: #a5f3fc; --tw-ring-color: rgba(34, 211, 238, 0.26); }
:global(html.kikoerumanager-dark) .cat-tone-slate { background: rgba(212, 212, 216, 0.1); color: #e4e4e7; --tw-ring-color: rgba(212, 212, 216, 0.18); }

:global(html.kikoerumanager-dark) .chip-tone-success { background: rgba(52, 211, 153, 0.13); color: #a7f3d0; --tw-ring-color: rgba(52, 211, 153, 0.24); }
:global(html.kikoerumanager-dark) .chip-tone-warn { background: rgba(251, 191, 36, 0.14); color: #fde68a; --tw-ring-color: rgba(251, 191, 36, 0.25); }
:global(html.kikoerumanager-dark) .chip-tone-danger { background: rgba(251, 113, 133, 0.13); color: #fecdd3; --tw-ring-color: rgba(251, 113, 133, 0.25); }
:global(html.kikoerumanager-dark) .chip-tone-info,
:global(html.kikoerumanager-dark) .chip-tone-neutral { background: rgba(212, 212, 216, 0.1); color: #e4e4e7; --tw-ring-color: rgba(212, 212, 216, 0.18); }

@media (max-width: 1180px) {
  .activity-metric-rail {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .activity-context-band {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .activity-filter-panel {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .activity-page {
    padding: 8px 10px 32px;
  }

  .activity-command-strip,
  .activity-reader-head,
  .activity-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .activity-metric-rail,
  .activity-context-band,
  .activity-filter-controls {
    grid-template-columns: 1fr;
  }

  .activity-category-list {
    grid-template-columns: 1fr;
    max-height: 180px;
  }

  .activity-timeline-shell {
    padding: 12px 10px 4px;
  }

  .activity-day-section {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .activity-day-header {
    position: relative;
    top: auto;
    flex-direction: row;
    align-items: baseline;
    padding-top: 0;
  }

  .activity-log-row {
    grid-template-columns: 58px minmax(0, 1fr) 14px;
    gap: 8px;
    padding: 10px 10px 10px 0;
  }

  .activity-log-time {
    flex-direction: column;
    align-items: flex-end;
    gap: 5px;
    padding-left: 10px;
  }

  .activity-reader-meta {
    justify-content: flex-start;
  }

  .activity-pager {
    justify-content: flex-start;
  }

  .activity-pager :deep(.el-pagination) {
    justify-content: flex-start;
  }

  .activity-detail-panel {
    width: 100vw !important;
    max-width: 100vw;
    min-width: 0;
  }
}
</style>
