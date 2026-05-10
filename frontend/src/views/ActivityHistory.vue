<template>
  <div class="activity-page">
    <!-- 页头走共享组件 AppPageHeader，右侧 slot 保留原本的搜索框 + 两个操作按钮 -->
    <AppPageHeader
      :icon="History"
      icon-color="#059669"
      title="操作记录"
      subtitle="字幕、解压、入库、删除、ASMR 同步等任务的完整审计"
    >
      <div class="page-head-search">
        <Search :size="14" :stroke-width="2.4" class="page-head-search-icon" />
        <input
          v-model="filters.q"
          class="page-head-search-input"
          placeholder="搜索 RJ、摘要、路径、任务 ID…"
          @keyup.enter="applyFilters"
        />
        <button v-if="filters.q" class="page-head-search-clear" type="button" @click="onClearSearch">
          <X :size="13" :stroke-width="2.6" />
        </button>
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

    <!-- 关键指标：紧凑横向数据条，hairline 分隔，不再是一个个独立卡片 -->
    <section class="metric-strip">
      <div class="metric-strip-head">
        <span class="metric-strip-label">关键指标</span>
        <AppDropdown
          v-model="statsDays"
          :options="statsDaysOptions"
          :width="140"
          :menu-min-width="160"
          :show-trigger-badge="false"
          @update:model-value="loadStats"
        />
      </div>
      <div class="metric-strip-row">
        <div
          v-for="m in metricCards"
          :key="m.key"
          class="metric-cell"
          :title="m.hint"
        >
          <div class="metric-cell-label">{{ m.label }}</div>
          <div class="metric-cell-value">
            <span class="metric-cell-num" :style="{ color: m.color }">{{ metricSplit(m.value).num }}</span>
            <span v-if="metricSplit(m.value).unit" class="metric-cell-unit">{{ metricSplit(m.value).unit }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 趋势 + 分类分布两栏 -->
    <section class="overview-strip">
      <article class="overview-card overview-trend">
        <div class="overview-card-head">
          <span class="overview-label">每日操作量</span>
          <span class="overview-meta">{{ statsRangeText }} · {{ formatNumber(stats.total_in_range) }} 条</span>
        </div>
        <AppEmptyState v-if="!sparkPoints.length" description="暂无趋势" size="sm" />
        <div v-else class="sparkline-wrap">
          <svg
            class="sparkline"
            :viewBox="`0 0 ${sparkBox.width} ${sparkBox.height}`"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient :id="sparkGradientId" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#0a84ff" stop-opacity="0.28" />
                <stop offset="100%" stop-color="#0a84ff" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path :d="sparkAreaPath" :fill="`url(#${sparkGradientId})`" />
            <path :d="sparkLinePath" fill="none" stroke="#0a84ff" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
            <circle :cx="sparkLastPoint.x" :cy="sparkLastPoint.y" r="3.2" fill="#0a84ff" />
          </svg>
          <div class="sparkline-foot">
            <span>{{ formatShortDate(sparkPoints[0]?.date) }}</span>
            <span>{{ formatShortDate(sparkPoints[sparkPoints.length - 1]?.date) }}</span>
          </div>
        </div>
      </article>

      <article class="overview-card overview-cats">
        <div class="overview-card-head">
          <span class="overview-label">分类分布</span>
          <span class="overview-meta">{{ formatNumber(allCategories.length) }} 项 · 滚动查看更多</span>
        </div>
        <AppEmptyState v-if="!allCategories.length" description="暂无数据" size="sm" />
        <div v-else class="cat-list-scroll">
          <div class="cat-list">
            <div
              v-for="(cat, idx) in allCategories"
              :key="cat.category"
              class="cat-row"
            >
              <span class="cat-dot" :style="{ background: catPaletteColor(idx) }"></span>
              <span class="cat-label">{{ cat.label }}</span>
              <div class="cat-track">
                <div
                  class="cat-fill"
                  :style="{ width: cat.pct + '%', background: catPaletteColor(idx) }"
                />
              </div>
              <span class="cat-num">{{ formatNumber(cat.count) }}</span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- 筛选栏：使用项目统一 AppDropdown，与任务中心 / 设置页保持一致 -->
    <section class="filter-bar">
      <AppDropdown
        v-model="filters.category"
        :options="categoryDropdownOptions"
        label="分类"
        placeholder="全部分类"
        :width="220"
        :menu-min-width="240"
        @update:model-value="applyFilters"
      />
      <AppDropdown
        v-model="filters.status"
        :options="statusDropdownOptions"
        label="状态"
        placeholder="全部状态"
        :width="190"
        :menu-min-width="200"
        @update:model-value="applyFilters"
      />
      <button
        v-if="hasActiveFilters"
        class="filter-reset"
        type="button"
        title="清空所有筛选条件"
        @click="resetFilters"
      >
        <FilterX :size="13" :stroke-width="2.4" />
        <span>重置筛选</span>
      </button>
    </section>

    <!-- 时间线主体：加载遮罩仅覆盖这一区，不影响顶部「刷新/归档」按钮点击 -->
    <section
      class="timeline-shell"
      v-app-loading="{ loading, text: '正在加载操作记录…', description: '同步索引、统计与状态聚合', size: 168, minHeight: 360, delay: 80, minVisible: 360, maskClass: 'activity-loading-mask' }"
    >
      <AppEmptyState
        v-if="!timelineGroups.length && !loading"
        description="没有匹配的操作记录"
        size="md"
      />
      <div v-else class="timeline">
        <section
          v-for="group in timelineGroups"
          :key="group.key"
          class="day-group"
        >
          <header class="day-marker">
            <span class="day-label">{{ group.label }}</span>
            <span class="day-meta">{{ formatNumber(group.items.length) }} 条</span>
            <span class="day-spine"></span>
          </header>
          <div class="day-events">
            <article
              v-for="row in group.items"
              :key="row.id"
              class="event-row"
              :class="[`tone-${statusTone(effectiveStatus(row))}`, { 'is-active': selectedRowId === row.id }]"
              @click="openDetail(row)"
            >
              <div class="event-rail">
                <span class="event-time">{{ formatTime(row.created_at) }}</span>
                <span class="event-dot" :class="`tone-${statusTone(effectiveStatus(row))}`">
                  <component
                    :is="statusIcon(effectiveStatus(row))"
                    :size="10"
                    :stroke-width="3"
                  />
                </span>
              </div>
              <div class="event-card">
                <div class="event-card-head">
                  <span
                    class="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-semibold leading-none ring-1 ring-inset transition-colors"
                    :class="categoryToneClasses(categoryConfig(row.category).tone)"
                  >
                    <component
                      :is="categoryIcon(row.category)"
                      :size="11"
                      :stroke-width="2.6"
                    />
                    <span>{{ row.category_label }}</span>
                  </span>
                  <span
                    v-if="row.rjcode"
                    class="inline-flex items-center px-1.5 py-[3px] rounded-md text-[11px] font-mono font-semibold leading-none tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60"
                  >
                    {{ row.rjcode }}
                  </span>
                  <span
                    class="text-[12px] font-bold leading-none tracking-tight"
                    :class="actionToneClasses(statusTone(effectiveStatus(row)))"
                  >
                    {{ humanAction(row) }}
                  </span>
                  <span
                    v-if="row.compacted"
                    class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-medium tracking-wide text-slate-500 ring-1 ring-inset ring-slate-200/70"
                    title="已归档：detail 已被压缩"
                  >
                    已归档
                  </span>
                  <span
                    v-if="row.rerun"
                    class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-medium tracking-wide text-amber-600 bg-amber-50/40 ring-1 ring-inset ring-amber-200/70"
                  >
                    已重试
                  </span>
                  <span
                    v-if="row.has_children"
                    class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-medium tracking-wide text-indigo-600 bg-indigo-50/40 ring-1 ring-inset ring-indigo-200/70"
                  >
                    有子任务
                  </span>
                  <!-- 失败但被后续重试 / 重新爬取 / 同 RJ 成功记录覆盖的，挂"已修复"绿底徽章 -->
                  <span
                    v-if="isRowRecovered(row)"
                    class="recovery-chip inline-flex items-center gap-1 px-1.5 py-[2px] rounded text-[10px] font-semibold leading-none tracking-tight text-emerald-700 bg-emerald-50 ring-1 ring-inset ring-emerald-200/70"
                    title="此次失败后被人工处理或重试修复"
                  >
                    <CheckCircle2 :size="10" :stroke-width="2.6" />
                    已修复
                  </span>
                </div>
                <div
                  v-if="renameSegments(row)"
                  class="event-summary rename-summary"
                  :class="{ 'is-failed': renameSegments(row).failed }"
                >
                  <!-- 单条重命名行：灰名（删除线）＋ 醒目箭头胶囊 ＋ 绿名（加粗），让目光聚焦在改动差异 -->
                  <span class="rename-old" :title="renameSegments(row).oldName">{{ renameSegments(row).oldName }}</span>
                  <span class="rename-arrow">--&gt;</span>
                  <span class="rename-new" :title="renameSegments(row).newName">{{ renameSegments(row).newName }}</span>
                  <span
                    v-if="renameSegments(row).reason"
                    class="rename-reason-inline"
                    :title="renameSegments(row).reason"
                  >· {{ renameSegments(row).reason }}</span>
                </div>
                <div v-else class="event-summary">{{ row.summary || '—' }}</div>
                <div v-if="row.chips?.length || row.source_path" class="event-meta">
                  <span
                    v-for="chip in row.chips || []"
                    :key="`${row.id}-${chip.label}`"
                    class="inline-flex items-baseline gap-1 px-2 py-[3px] rounded-md text-[11px] leading-none ring-1 ring-inset transition-colors"
                    :class="chipToneClasses(chip.tone)"
                  >
                    <span class="font-medium opacity-70">{{ chip.label }}</span>
                    <span class="font-semibold tabular-nums tracking-tight">{{ chip.value }}</span>
                  </span>
                  <span v-if="row.source_path" class="event-path" :title="row.source_path">
                    <FolderOpen :size="11" :stroke-width="2.4" />
                    <span class="event-path-text">{{ compactPath(row.source_path) }}</span>
                  </span>
                </div>
              </div>
              <div class="event-tail">
                <ChevronRight :size="14" :stroke-width="2.4" />
              </div>
            </article>
          </div>
        </section>
      </div>
    </section>

    <!-- 分页 -->
    <footer class="footer-bar">
      <div class="footer-meta">
        <span>共 {{ formatNumber(total) }} 条</span>
        <span v-if="lastLoadedAtText" class="footer-sep">·</span>
        <span v-if="lastLoadedAtText">{{ lastLoadedAtText }}</span>
      </div>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="limit"
        layout="sizes, prev, pager, next, jumper"
        :total="total"
        :page-sizes="[30, 50, 100, 200]"
        background
        size="small"
        class="footer-pager"
        @current-change="loadList"
        @size-change="onPageSizeChange"
      />
    </footer>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailDrawerVisible"
      class="activity-drawer"
      :class="{ 'is-resizing': isDrawerResizing }"
      direction="rtl"
      :size="`${detailDrawerWidth}px`"
      :show-close="false"
      :with-header="false"
      :before-close="onDrawerBeforeClose"
      @closed="onDrawerClosed"
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
    </el-drawer>

    <!-- 抽屉左缘的拖拽手柄：fixed 定位到抽屉外面，不受 el-drawer 内部 DOM 影响 -->
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
  Tag,
  Upload,
  Users,
  X,
  XCircle
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useActivityHistoryLite } from '../composables/useActivityHistoryLite'
import api from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import ActivityDetailBody from '../components/activity/ActivityDetailBody.vue'

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
  loadStats,
  loadList,
  loadAll,
  loadDetail,
  invalidateDetail,
  applyFilters,
  onPageSizeChange,
  shouldSoftRefresh,
  handleVisibilityRefresh
} = useActivityHistoryLite()

// ==================== 配置 / 常量 ====================
const categoryOptions = [
  { value: 'subtitle_crawl', label: '字幕爬取' },
  { value: 'subtitle_pair', label: '字幕配对' },
  { value: 'subtitle_import', label: '字幕补配' },
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
  { value: 'email_watcher', label: '邮件监听' }
]

// category → tone 映射：每个 category 独占一个 tone，避免视觉撞色看不出区别。
// 颜色语义大致按"业务领域"分组：字幕系（紫蓝系）、库存系（绿系）、Pipeline 工具系（暖色 / 灰）、
// 远端通信系（蓝青粉）。即使列表里多种 category 混排，也能一眼定位到自己关心的那一类。
const categoryConfigs = {
  subtitle_crawl: { icon: Search, label: '字幕爬取', tone: 'indigo' },
  subtitle_pair: { icon: LinkIcon, label: '字幕配对', tone: 'violet' },
  subtitle_import: { icon: FileDown, label: '字幕补配', tone: 'fuchsia' },
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
  email_watcher: { icon: Mail, label: '邮件监听', tone: 'pink' },
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
// 14 种 tone 让 14 个 category 各占一色（含 default = slate），新增 fuchsia / teal /
// lime / orange / pink 5 个，避免之前 sky / indigo / amber / emerald / slate 撞色。
const CATEGORY_TONE_CLASS = {
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-200/60',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200/60',
  fuchsia: 'bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200/60',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200/60',
  orange: 'bg-orange-50 text-orange-700 ring-orange-200/60',
  emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200/60',
  teal: 'bg-teal-50 text-teal-700 ring-teal-200/60',
  lime: 'bg-lime-50 text-lime-700 ring-lime-200/60',
  rose: 'bg-rose-50 text-rose-700 ring-rose-200/60',
  pink: 'bg-pink-50 text-pink-700 ring-pink-200/60',
  sky: 'bg-sky-50 text-sky-700 ring-sky-200/60',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200/60',
  cyan: 'bg-cyan-50 text-cyan-700 ring-cyan-200/60',
  slate: 'bg-slate-50 text-slate-700 ring-slate-200/60'
}

const ACTION_TONE_CLASS = {
  success: 'text-emerald-600',
  warn: 'text-amber-600',
  danger: 'text-rose-600',
  info: 'text-sky-600',
  neutral: 'text-slate-500'
}

const CHIP_TONE_CLASS = {
  success: 'bg-emerald-50/80 text-emerald-700 ring-emerald-100',
  warn: 'bg-amber-50/80 text-amber-700 ring-amber-100',
  danger: 'bg-rose-50/80 text-rose-700 ring-rose-100',
  info: 'bg-sky-50/80 text-sky-700 ring-sky-100',
  neutral: 'bg-slate-50/80 text-slate-700 ring-slate-100'
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
  // 拖拽过程中只改实际 DOM，不走 Vue 响应式，避免每帧重新渲染整个 drawer 内容
  _drawerResizeEl = document.querySelector('.activity-drawer .el-drawer')
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
    map.get(key).items.push(row)
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
    if (status === 'partial_success') return '部分入库'
    if (status === 'failed') return '入库失败'
    if (status === 'incomplete') return '未正常结束'
  }
  if (cat === 'process_existing') {
    return status === 'success' ? '处理完成' : '处理失败'
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

onMounted(() => {
  loadAll()
  refreshCompactEstimate()
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
  // 兜底：组件销毁时清掉可能残留的抽屉拖拽监听
  document.removeEventListener('mousemove', onDrawerResizeMove)
  if (typeof document !== 'undefined' && document.body) {
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
  }
})

watch(() => filters.q, (val, old) => {
  if (val === '' && old !== '') applyFilters()
})
</script>

<style scoped>
.activity-page {
  position: relative;
  max-width: 1280px;
  margin: 0 auto;
  padding: 12px 28px 56px;
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    'SF Pro Text',
    'Segoe UI',
    Roboto,
    'Helvetica Neue',
    Arial,
    sans-serif;
  color: #0f172a;
}

:deep(.activity-loading-mask) {
  inset: 0;
  border-radius: 0;
  background: rgba(248, 250, 252, 0.78);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  z-index: 10;
}

/* 页头现在走共享组件 components/common/AppPageHeader.vue，这里只保留页头右侧 slot 里的搜索框 + 按钮内嵌样式 */

/* 头部内嵌搜索框 */
.page-head-search {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 280px;
  height: 36px;
  padding: 0 36px 0 34px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.12);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.page-head-search:focus-within {
  border-color: rgba(15, 23, 42, 0.28);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.06);
}

.page-head-search-icon {
  position: absolute;
  left: 11px;
  color: rgba(15, 23, 42, 0.42);
  pointer-events: none;
}

.page-head-search-input {
  width: 100%;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13px;
  color: #0f172a;
}

.page-head-search-input::placeholder {
  color: rgba(15, 23, 42, 0.4);
}

.page-head-search-clear {
  position: absolute;
  right: 8px;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  border: 0;
  background: transparent;
  color: rgba(15, 23, 42, 0.45);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.page-head-search-clear:hover {
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
}

/* 操作按钮（对齐 ASMRSync.vue / LibraryBackup.vue page-head-btn 规范） */
.page-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
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
  will-change: transform, opacity;
}

/* 图标包裹层：14×14 容器锁定尺寸，避免 swap Transition 影响按钮宽高 */
.page-head-btn-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  position: relative;
}

/* 图标基础动效（Loader2 spin 不在此选择器范围，避免冲突） */
.page-head-btn :deep(.page-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.page-head-btn :deep(svg) { flex-shrink: 0; }

.page-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}

/* :active 不依赖 :not(:disabled)，让按下反馈在 click → disabled 切换瞬间也保留 */
.page-head-btn:active {
  transform: translateY(0) scale(0.94);
  box-shadow:
    0 4px 10px rgba(15, 23, 42, 0.12),
    inset 0 2px 6px rgba(15, 23, 42, 0.18);
  transition:
    transform 0.08s ease-out,
    box-shadow 0.08s ease-out;
}

.page-head-btn.primary:active {
  box-shadow:
    0 4px 10px rgba(15, 23, 42, 0.3),
    inset 0 2px 8px rgba(0, 0, 0, 0.35);
}

.page-head-btn:active :deep(.page-head-btn-icon) {
  transform: scale(0.78);
  transition: transform 0.08s ease-out;
}

/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.page-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* === Primary 黑灰渐变 + shimmer 高光扫光 === */
.page-head-btn.primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}

.page-head-btn.primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -120%;
  width: 60%;
  height: 100%;
  background: linear-gradient(
    100deg,
    transparent 0%,
    rgba(255, 255, 255, 0.05) 30%,
    rgba(255, 255, 255, 0.28) 50%,
    rgba(255, 255, 255, 0.05) 70%,
    transparent 100%
  );
  transform: skewX(-18deg);
  transition: left 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

.page-head-btn.primary:hover {
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.28), 0 0 0 4px rgba(15, 23, 42, 0.05);
}

.page-head-btn.primary:hover::before {
  left: 130%;
}

/* === Ghost 白底纯色 transition（gradient 不能 transition 会瞬切） === */
.page-head-btn.ghost {
  background-color: #fff;
}

.page-head-btn.ghost:hover {
  background-color: #f8fafc;
  border-color: rgba(15, 23, 42, 0.2);
}

/* === 各按钮专属图标动效 === */
/* 刷新：RefreshCcw hover 时反向旋转一整圈
 *  - 仅在 :not(:disabled) 时触发：loading 中按钮 disabled，避免 hover rotate 与 swap leave Transition 冲突造成图标消失
 *  - :not(.animate-spin) 进一步排除 Loader2，让 spin 动画独立运行
 */
.page-head-btn.btn-refresh:hover:not(:disabled) :deep(.page-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 归档：Archive 图标 hover 时轻微下沉 + 缩放（模拟"归档落盘"动作）+ 蓝光（同样仅 :not(:disabled)） */
.page-head-btn.btn-archive:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: translateY(1px) scale(1.12);
  filter: drop-shadow(0 2px 4px rgba(59, 130, 246, 0.35));
  color: #2563eb;
}

/* 文本 label：min-width + 居中，避免「刷新」→「刷新中…」宽度跳变 */
.page-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.page-head-btn.primary .page-head-btn-label { min-width: 56px; }
.page-head-btn.ghost .page-head-btn-label { min-width: 70px; }

/* hover 时文字微微展开间距 */
.page-head-btn:hover .page-head-btn-label {
  letter-spacing: 0.04em;
}

/* === 图标双 layer 平滑切换：Loader2 ↔ RefreshCcw 通过 opacity + scale 渐变 ===
 *  - 两个 slot 都常驻 DOM，避免 v-if 瞬切 / Vue Transition 初始挂载阶段不稳定
 *  - .is-visible 控制显示态（opacity 1, scale 1），未激活时 opacity 0 + scale 0.5 + rotate 隐藏
 *  - spin 动画在 svg 内层，与外层 transform 不冲突
 *  - 切换时间缩短到 200ms，让点击后 loader 立即出现，反馈更即时
 */
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
  will-change: transform, opacity;
}

.page-head-btn-icon-slot.is-visible {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1) rotate(0deg);
}

/* === 按下 flash：一次性白色高光从中心扩散，给点击清晰即时反馈 === */
.page-head-btn::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: radial-gradient(
    circle at center,
    rgba(255, 255, 255, 0.6) 0%,
    rgba(255, 255, 255, 0.2) 40%,
    transparent 70%
  );
  transform: translate(-50%, -50%) scale(0);
  opacity: 0;
  pointer-events: none;
}

.page-head-btn:active::after {
  animation: page-head-btn-flash 0.4s ease-out;
}

@keyframes page-head-btn-flash {
  0%   { transform: translate(-50%, -50%) scale(0);   opacity: 0.9; }
  60%  { transform: translate(-50%, -50%) scale(1.4); opacity: 0.45; }
  100% { transform: translate(-50%, -50%) scale(1.8); opacity: 0; }
}

.page-head-btn-hint {
  margin-left: 4px;
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(15, 118, 110, 0.1);
  color: #0d9488;
}

/* ============= 关键指标紧凑横向条 ============= */
.metric-strip {
  margin-bottom: 14px;
  padding: 14px 18px 12px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.metric-strip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.metric-strip-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.55);
  text-transform: uppercase;
}

/* statsDays AppDropdown 已接管宁广与状态样式（参考 width prop），这里仅保留上下文占位 */

/* 数据条本体：8 列等宽，hairline 分隔 */
.metric-strip-row {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 0;
  border-top: 1px solid rgba(15, 23, 42, 0.05);
}

.metric-cell {
  position: relative;
  padding: 12px 14px;
  border-right: 1px solid rgba(15, 23, 42, 0.05);
  min-width: 0;
  cursor: help;
}

.metric-cell:last-child {
  border-right: none;
}

.metric-cell-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.5);
  letter-spacing: 0.02em;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-cell-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
}

.metric-cell-num {
  font-size: 19px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.02em;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-cell-unit {
  font-size: 10.5px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex: 0 0 auto;
}

@media (max-width: 1100px) {
  .metric-strip-row {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .metric-cell:nth-child(4n) {
    border-right: none;
  }
  .metric-cell:nth-child(n+5) {
    border-top: 1px solid rgba(15, 23, 42, 0.05);
  }
}

@media (max-width: 640px) {
  .metric-strip-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-cell:nth-child(2n) {
    border-right: none;
  }
  .metric-cell:nth-child(n+3) {
    border-top: 1px solid rgba(15, 23, 42, 0.05);
  }
}

/* ============= 概览条（趋势 + 分类） ============= */
.overview-strip {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

.overview-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 20px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  min-width: 0;
}

.overview-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.overview-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
}

.overview-meta {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.42);
  font-variant-numeric: tabular-nums;
}

.sparkline-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sparkline {
  width: 100%;
  height: 70px;
}

.sparkline-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: rgba(15, 23, 42, 0.48);
  font-variant-numeric: tabular-nums;
}

/* 分类分布：滚动隐藏条 */
.cat-list-scroll {
  max-height: 180px;
  overflow-y: auto;
  /* 自定义薄滚动条：默认隐藏，悬停时弱显 */
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
  transition: scrollbar-color 0.2s ease;
}

.cat-list-scroll:hover {
  scrollbar-color: rgba(15, 23, 42, 0.18) transparent;
}

.cat-list-scroll::-webkit-scrollbar {
  width: 4px;
}

.cat-list-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.cat-list-scroll::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 999px;
  transition: background 0.2s ease;
}

.cat-list-scroll:hover::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.18);
}

.cat-list-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.32);
}

.cat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.cat-row {
  display: grid;
  grid-template-columns: 8px minmax(60px, 1fr) 2fr 40px;
  gap: 8px;
  align-items: center;
  font-size: 12px;
}

.cat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.cat-label {
  color: #0f172a;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cat-track {
  height: 6px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}

.cat-fill {
  height: 100%;
  border-radius: 999px;
  opacity: 0.85;
  transition: width 0.35s ease;
}

.cat-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: rgba(15, 23, 42, 0.7);
  font-weight: 600;
}

/* ============= 筛选栏：靠右对齐 + 项目统一 AppDropdown ============= */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

/* 重置筛选按钮：仅在有活动筛选时出现，hover 微动效统一规范 */
.filter-reset {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 0 0 auto;
  height: 36px;
  padding: 0 18px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease;
}

.filter-reset:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.2);
  color: #0f172a;
}

.filter-reset:active {
  transform: scale(0.96);
  transition: transform 0.1s ease;
}

@media (max-width: 720px) {
  .filter-bar {
    justify-content: stretch;
  }
  .filter-reset {
    flex: 1 0 100%;
  }
}

/* ============= Timeline ============= */
.timeline-shell {
  min-height: 320px;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.day-group {
  position: relative;
}

.day-marker {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 4px 12px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.55);
  text-transform: uppercase;
}

.day-label {
  position: relative;
  z-index: 2;
  padding: 4px 12px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(10, 132, 255, 0.1), rgba(94, 200, 250, 0.1));
  color: #0a84ff;
  font-size: 12px;
}

.day-meta {
  position: relative;
  z-index: 2;
  font-size: 11px;
  color: rgba(15, 23, 42, 0.4);
  font-weight: 600;
}

.day-spine {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgba(15, 23, 42, 0.1), transparent);
}

.day-events {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.event-row {
  position: relative;
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) 22px;
  align-items: stretch;
  cursor: pointer;
  border-radius: 16px;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.event-row:hover {
  transform: translateY(-1px);
}

.event-row:active {
  transform: scale(0.998);
}

.event-row.is-active .event-card {
  border-color: rgba(10, 132, 255, 0.45);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 16px 36px rgba(10, 132, 255, 0.16);
}

.event-rail {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 0 6px;
}

.event-rail::before {
  content: '';
  position: absolute;
  left: 21px;
  top: -8px;
  bottom: -8px;
  width: 1px;
  background: rgba(15, 23, 42, 0.08);
}

.event-row:first-child .event-rail::before {
  top: 50%;
}

.event-row:last-child .event-rail::before {
  bottom: 50%;
}

.event-time {
  min-width: 36px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: rgba(15, 23, 42, 0.55);
  font-weight: 600;
}

.event-dot {
  position: relative;
  z-index: 2;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  color: #94a3b8;
  border: 2px solid #cbd5e1;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.event-dot.tone-success {
  background: #ecfdf5;
  color: #059669;
  border-color: #34c759;
}

.event-dot.tone-warn {
  background: #fffbeb;
  color: #b45309;
  border-color: #ff9500;
}

.event-dot.tone-danger {
  background: #fef2f2;
  color: #b91c1c;
  border-color: #ff3b30;
}

.event-dot.tone-info {
  background: #eff6ff;
  color: #0a84ff;
  border-color: #0a84ff;
}

.event-dot.tone-neutral {
  background: #f1f5f9;
  color: #64748b;
  border-color: #94a3b8;
}

.event-row:hover .event-dot {
  transform: scale(1.1);
}

.event-card {
  position: relative;
  padding: 12px 16px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.05);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  transition: all 0.25s ease;
}

.event-row:hover .event-card {
  border-color: rgba(15, 23, 42, 0.1);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 12px 24px rgba(15, 23, 42, 0.08);
}

.event-card-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}

/* "已修复"徽章：失败行的复原标记，加一层柔和呼吸光晕，让用户在长列表里能注意到 */
.recovery-chip {
  position: relative;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.45);
  animation: recoveryPulse 2.4s ease-in-out infinite;
  transition: transform 0.2s ease;
}

.recovery-chip:hover {
  transform: translateY(-1px);
}

@keyframes recoveryPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
  50%      { box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.18); }
}

/* 失败但已修复的行：把卡片左边的色条由"红"切到"红→绿"的柔和渐变，告诉用户这条已经被覆盖 */
.event-row.tone-danger:has(.recovery-chip) .event-card::before {
  background: linear-gradient(180deg, #f87171 0%, #fb923c 45%, #34d399 100%);
}

.event-summary {
  font-size: 13px;
  line-height: 1.5;
  color: #1e293b;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ============= 重命名行：'黄底原名 + 箭头 + 绿底新名' 单行高亮 ============= */
.rename-summary {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
  letter-spacing: 0.01em;
  word-break: break-all;
}

/* 旧名：amber 渐变胶囊 + 加粗，第一眼就吸引到"被改掉的旧值" */
.rename-summary .rename-old {
  display: inline-block;
  padding: 1px 8px;
  font-weight: 600;
  color: #92400e; /* amber-800 */
  background: linear-gradient(180deg, rgba(251, 191, 36, 0.22) 0%, rgba(251, 191, 36, 0.10) 100%);
  border-radius: 6px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: all 0.2s ease;
}

/* 中间箭头：slate plain text，不抢前后两个胶囊的视觉焦点 */
.rename-summary .rename-arrow {
  display: inline-block;
  margin: 0 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700;
  font-size: 13px;
  letter-spacing: -0.08em;
  color: rgba(71, 85, 105, 0.78); /* slate-600 */
  vertical-align: baseline;
}

/* 新名：emerald 渐变胶囊 + 加粗，目光最终落到"改成了什么" */
.rename-summary .rename-new {
  display: inline-block;
  padding: 1px 8px;
  font-weight: 600;
  color: #065f46; /* emerald-800 */
  background: linear-gradient(180deg, rgba(16, 185, 129, 0.20) 0%, rgba(16, 185, 129, 0.08) 100%);
  border-radius: 6px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: all 0.2s ease;
}

/* 失败：箭头 + 新名都切到 rose 系，旧名 amber 保持不变（语义：改之前的状态没问题，是改这一步出错） */
.rename-summary.is-failed .rename-arrow {
  color: #b91c1c;
}

.rename-summary.is-failed .rename-new {
  color: #991b1b;
  background: linear-gradient(180deg, rgba(244, 63, 94, 0.18) 0%, rgba(244, 63, 94, 0.08) 100%);
}

.rename-summary .rename-reason-inline {
  margin-left: 8px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 11.5px;
  color: rgba(190, 18, 60, 0.85);
  letter-spacing: 0.02em;
}

/* hover：两个胶囊轻微抬升 + 微 glow，对齐项目主操作"渐变 + glow"的交互语言 */
.event-row:hover .rename-summary .rename-old {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 2px 6px rgba(251, 191, 36, 0.22);
  transform: translateY(-1px);
}

.event-row:hover .rename-summary .rename-new {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 2px 6px rgba(16, 185, 129, 0.18);
  transform: translateY(-1px);
}

.event-row:hover .rename-summary.is-failed .rename-new {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 2px 6px rgba(244, 63, 94, 0.22);
}

.event-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 2px;
}

.event-path {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 8px;
  font-size: 11px;
  background: rgba(241, 245, 249, 0.7);
  color: rgba(15, 23, 42, 0.62);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  max-width: 100%;
  min-width: 0;
}

.event-path-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 360px;
}

.event-tail {
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(15, 23, 42, 0.3);
  transition: all 0.25s ease;
}

.event-row:hover .event-tail {
  color: rgba(15, 23, 42, 0.6);
  transform: translateX(2px);
}

/* ============= 底部 ============= */
.footer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 4px 4px;
  gap: 16px;
}

.footer-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.5);
}

.footer-sep {
  opacity: 0.55;
}

/* footer-pager 走 index.css 全局规范（small 尺寸自动适配 28px 紧凑版） */

/* ============= Drawer ============= */
:deep(.activity-drawer) {
  --el-drawer-padding-primary: 0;
}

:deep(.activity-drawer .el-drawer__header) {
  display: none;
}

:deep(.activity-drawer .el-drawer__body) {
  padding: 0;
  overflow: hidden;
}

/* 拖拽手柄：fixed 到抽屉外面、贴左边缘，z-index 高于 el-overlay (默认 2000+) */
/* transform: translateX(50%) 让 10px 宽的命中区横跨抽屉左边缘（5px 在外、5px 在内）*/
.activity-drawer-resizer-fixed {
  position: fixed;
  top: 0;
  bottom: 0;
  width: 10px;
  transform: translateX(50%);
  cursor: col-resize;
  z-index: 3000;
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
  background: rgba(15, 23, 42, 0.08);
  transition: background 0.18s ease, left 0.18s ease, right 0.18s ease;
}

.activity-drawer-resizer-fixed:hover::before,
.activity-drawer-resizer-fixed.is-active::before {
  background: #3b82f6;
  left: 3px;
  right: 3px;
}

/* 拖拽过程中关掉抽屉自身的动画过渡，让宽度跟随鼠标实时贴合 */
:deep(.activity-drawer.is-resizing .el-drawer) {
  transition: none !important;
  will-change: width;
}

@media (max-width: 1080px) {
  .overview-strip {
    grid-template-columns: 1fr;
  }
  .activity-page {
    padding: 12px 16px 56px;
  }
}

@media (max-width: 720px) {
  .page-head-search {
    width: 100%;
  }
  .overview-strip {
    grid-template-columns: 1fr;
  }
  .event-row {
    grid-template-columns: 64px minmax(0, 1fr) 18px;
  }
  .event-time {
    min-width: 28px;
  }
}
</style>
