<template>
  <section
    ref="panelRef"
    class="dashboard-archive flex min-h-0 flex-1 flex-col rounded-[14px] border border-slate-200/80 bg-white p-3.5 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]"
    data-section="dashboard-archive"
  >
    <header class="dash-archive-head flex flex-shrink-0 items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2.5">
        <Archive :size="20" :stroke-width="2" class="flex-shrink-0 text-slate-700" />
        <div class="min-w-0 leading-tight">
          <h2 class="m-0 text-[14px] font-bold tracking-tight text-slate-900">最近归档</h2>
          <p class="m-0 mt-0.5 text-[11.5px] text-slate-500">
            {{ archives.length ? `共 ${archives.length} 条记录` : '暂无归档记录' }}
          </p>
        </div>
      </div>
      <el-button
        class="dash-archive-refresh-btn"
        :loading="archivesLoading"
        :disabled="archivesLoading"
        circle
        plain
        size="small"
        title="刷新归档记录"
        @click="$emit('refresh')"
      >
        <template #icon>
          <RefreshCw :size="14" :stroke-width="2.2" />
        </template>
      </el-button>
    </header>

    <!-- 搜索 -->
    <div class="mt-3 flex-shrink-0">
      <el-input
        :model-value="searchQuery"
        size="small"
        placeholder="搜索 RJ / 文件名"
        clearable
        class="dash-archive-search"
        @update:model-value="$emit('update:searchQuery', $event)"
      >
        <template #prefix>
          <Search :size="13" :stroke-width="2.2" class="text-slate-400" />
        </template>
      </el-input>
    </div>

    <!-- 域 tabs：极简 pill、无图标、活动态黑底白字、count 紧贴 label 的圆形 badge -->
    <div class="mt-2 flex-shrink-0">
      <el-radio-group
        :model-value="domainFilter"
        size="small"
        class="dash-archive-tabs flex flex-wrap gap-1.5"
        @update:model-value="$emit('update:domainFilter', $event)"
      >
        <el-radio-button
          v-for="tab in tabs"
          :key="tab.key"
          :value="tab.key"
          class="dash-archive-tab"
        >
          <span class="inline-flex items-center gap-1.5">
            <span>{{ tab.label }}</span>
            <span
              v-if="tab.count > 0"
              class="dash-archive-tab-count"
              :class="domainFilter === tab.key ? 'dash-archive-tab-count--on' : 'dash-archive-tab-count--off'"
            >
              {{ tab.count }}
            </span>
          </span>
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 归档列表（前端分页切片，pageSize 按容器高度动态计算） -->
    <div v-if="filteredArchives.length" class="mt-2.5 flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
      <article
        v-for="(archive, index) in pagedArchives"
        :key="archive.id"
        class="dash-fade-up group grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-[10px] border border-slate-100 bg-white p-2.5 transition-colors duration-300 hover:border-slate-200 hover:bg-slate-50/50"
        :style="{ animationDelay: `${index * 35}ms` }"
      >
        <component
          :is="getMeta(archive).icon"
          :size="18"
          :stroke-width="2"
          class="mt-0.5 flex-shrink-0 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
          :class="getMeta(archive).chipIcon || 'text-slate-500'"
        />

        <div class="min-w-0">
          <!-- 标题行：文件名 + (解压入库 RJ 号紧邻) + 日期右对齐 -->
          <div class="flex items-start gap-2">
            <div class="flex min-w-0 flex-1 items-center gap-1.5">
              <h3 class="m-0 min-w-0 truncate text-[13px] font-semibold leading-tight text-slate-900">{{ archive.filename }}</h3>
              <span
                v-if="archive.rjcode && getMeta(archive).key === 'import'"
                class="inline-flex flex-shrink-0 items-center rounded-[5px] bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-slate-600"
              >{{ archive.rjcode }}</span>
            </div>
            <div class="flex flex-shrink-0 flex-col items-end gap-0.5">
              <span
                v-if="archive.rjcode && getMeta(archive).key !== 'import'"
                class="text-[11px] font-bold tabular-nums text-slate-500"
              >{{ archive.rjcode }}</span>
              <span class="text-[11px] tabular-nums text-slate-400">{{ formatDate(archive.processed_at) }}</span>
            </div>
          </div>
          <!-- 标签行：domain（同色系无 icon，与左侧色块呼应） + status（留 icon） + 文件大小 -->
          <div class="mt-1.5 flex items-center justify-between gap-1.5">
            <div class="flex flex-wrap items-center gap-1.5">
              <span
                class="inline-flex h-[20px] items-center rounded-[5px] px-1.5 text-[11px] font-semibold"
                :class="[getMeta(archive).chipBg || 'bg-slate-100', getMeta(archive).chipText || 'text-slate-600']"
              >
                {{ getMeta(archive).label }}
              </span>
              <span class="inline-flex h-[20px] items-center gap-1 rounded-[5px] bg-slate-50 px-1.5 text-[11px] font-medium text-slate-600">
                <component :is="statusIcon(getStatusMeta(archive.status).key)" :size="11" :stroke-width="2" :class="statusIconColor(getStatusMeta(archive.status).key)" />
                {{ getStatusMeta(archive.status).label }}
              </span>
              <span v-if="archive.isVolumeGroup" class="inline-flex h-[20px] items-center rounded-[5px] bg-amber-50 px-1.5 text-[11px] font-semibold text-amber-700">{{ archive.volumes.length }} 分卷</span>
            </div>
            <span v-if="archive.file_size" class="flex-shrink-0 text-[11px] tabular-nums text-slate-400">{{ formatFileSize(archive.file_size) }}</span>
          </div>
        </div>

        <button
          v-if="archive.source === 'processed_archive' && getStatusMeta(archive.status).key === 'failed'"
          type="button"
          class="group/btn inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-[7px] border border-slate-300 bg-slate-50 text-slate-600 shadow-[0_1px_0_rgba(15,23,42,0.04),inset_0_1px_0_rgba(255,255,255,0.8)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-110 hover:border-slate-400 hover:bg-white hover:text-slate-900 hover:shadow-[0_4px_10px_-4px_rgba(15,23,42,0.18)] active:scale-90 disabled:pointer-events-none disabled:opacity-50"
          :disabled="reprocessingId === archive.id"
          title="重新解压"
          @click="$emit('reprocess', archive.id)"
        >
          <RotateCcw
            :size="13"
            :stroke-width="2.4"
            :class="reprocessingId === archive.id ? 'animate-spin' : 'transition-transform duration-500 group-hover/btn:-rotate-180'"
          />
        </button>
      </article>
    </div>

    <div v-else class="mt-3 flex flex-1 items-center justify-center">
      <AppEmptyState description="暂无归档记录" size="default" />
    </div>

    <div
      v-if="showPager"
      class="dash-archive-pager mt-2.5 flex flex-shrink-0 items-center justify-between gap-2 border-t border-slate-100 pt-2.5"
    >
      <span class="text-[11px] font-medium tracking-wide text-slate-400">
        共 <b class="text-slate-700 tabular-nums">{{ filteredArchives.length }}</b> 条
      </span>

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="dash-archive-pager-btn group"
          :disabled="internalPage <= 1"
          aria-label="上一页"
          @click="goPrevPage"
        >
          <ChevronLeft :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:-translate-x-0.5" />
        </button>

        <div class="dash-archive-pager-indicator">
          <span class="dash-archive-pager-current">{{ internalPage }}</span>
          <span class="dash-archive-pager-divider">/</span>
          <span class="dash-archive-pager-total">{{ totalPages }}</span>
        </div>

        <button
          type="button"
          class="dash-archive-pager-btn group"
          :disabled="internalPage >= totalPages"
          aria-label="下一页"
          @click="goNextPage"
        >
          <ChevronRight :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-0.5" />
        </button>
      </div>
    </div>
  </section>
</template>

<script setup>
import {
  Archive,
  Activity,
  ChevronLeft,
  ChevronRight,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  XCircle,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppEmptyState from '../common/AppEmptyState.vue'

const props = defineProps({
  archives: { type: Array, default: () => [] },
  filteredArchives: { type: Array, default: () => [] },
  tabs: { type: Array, default: () => [] },
  domainFilter: { type: String, default: 'all' },
  searchQuery: { type: String, default: '' },
  archivesLoading: { type: Boolean, default: false },
  reprocessingId: { type: [String, Number, null], default: null },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 6 },
  getMeta: { type: Function, required: true },
  getStatusMeta: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  formatFileSize: { type: Function, required: true },
})

defineEmits(['refresh', 'reprocess', 'change-page', 'update:searchQuery', 'update:domainFilter'])

// 单条卡片估算高度（含 8px gap）：article p-2.5 + 两行内容 ≈ 66px + 8px gap = 74px
const ITEM_HEIGHT = 74
// 面板内除列表区以外固定占用的高度（header + search + tabs + pager + 内外边距估算）
const FIXED_OVERHEAD = 44 + 38 + 34 + 46 + 28

const panelRef = ref(null)
const panelHeight = ref(0)
let resizeObserver = null

function measurePanel() {
  const el = panelRef.value
  if (!el) return
  panelHeight.value = el.clientHeight || 0
}

onMounted(() => {
  measurePanel()
  if (typeof ResizeObserver !== 'undefined' && panelRef.value) {
    resizeObserver = new ResizeObserver(measurePanel)
    resizeObserver.observe(panelRef.value)
  }
})

onBeforeUnmount(() => {
  if (resizeObserver) {
    try { resizeObserver.disconnect() } catch (_) {}
    resizeObserver = null
  }
})

// 数据 / 过滤变化时重新测一遍，避免布局抖动错位
watch(() => props.filteredArchives.length, () => {
  requestAnimationFrame(measurePanel)
})

// 动态 pageSize：用面板总高减固定占位算可用列表空间
const effectivePageSize = computed(() => {
  const h = panelHeight.value
  if (!h) return Math.max(3, Number(props.pageSize) || 6)
  const listSpace = Math.max(0, h - FIXED_OVERHEAD)
  return Math.max(3, Math.floor(listSpace / ITEM_HEIGHT))
})

// 内部维护当前页，避免被父组件的轮询/反应式更新反复重置回 1
const internalPage = ref(1)

const totalPages = computed(() => {
  const list = props.filteredArchives.length || 0
  return Math.max(1, Math.ceil(list / effectivePageSize.value))
})

// 当前页切片显示
const pagedArchives = computed(() => {
  const list = Array.isArray(props.filteredArchives) ? props.filteredArchives : []
  const size = effectivePageSize.value
  const safePage = Math.min(Math.max(1, internalPage.value), totalPages.value)
  const start = (safePage - 1) * size
  return list.slice(start, start + size)
})

const showPager = computed(() => props.filteredArchives.length > effectivePageSize.value)

// 总页数缩水（搜索、切 tab、resize 后）时，把当前页夹到合法范围
watch(totalPages, (max) => {
  if (internalPage.value > max) internalPage.value = max
  if (internalPage.value < 1) internalPage.value = 1
})

// 搜索词或域过滤变化时，回到第 1 页
watch(() => `${props.searchQuery}|${props.domainFilter}`, () => {
  internalPage.value = 1
})

function goPrevPage() {
  if (internalPage.value > 1) internalPage.value -= 1
}
function goNextPage() {
  if (internalPage.value < totalPages.value) internalPage.value += 1
}

const STATUS_ICON = {
  completed: Sparkles,
  failed: XCircle,
  processing: Activity,
  pending: PauseCircle,
  unknown: Activity,
}

function statusIcon(key) {
  return STATUS_ICON[key] || Activity
}

function statusIconColor(key) {
  if (key === 'completed') return 'text-emerald-600'
  if (key === 'failed') return 'text-rose-600'
  if (key === 'processing') return 'text-amber-600'
  if (key === 'pending') return 'text-indigo-600'
  return 'text-slate-500'
}

function statusChipClass(key) {
  if (key === 'completed') return 'bg-emerald-50 text-emerald-700'
  if (key === 'failed') return 'bg-rose-50 text-rose-700'
  if (key === 'processing') return 'bg-amber-50 text-amber-700'
  if (key === 'pending') return 'bg-slate-100 text-slate-600'
  return 'bg-slate-50 text-slate-500'
}
</script>

<style scoped>
.dash-fade-up {
  animation: dash-fade-up 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
@keyframes dash-fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 刷新按钮 */
.dash-archive-refresh-btn {
  --el-button-size: 28px;
  width: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0;
  border-radius: 8px;
  border-color: rgba(148, 163, 184, 0.48);
  color: rgb(71 85 105);
  background: rgba(255, 255, 255, 0.95);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-refresh-btn:hover {
  color: rgb(15 23 42);
  border-color: rgba(100, 116, 139, 0.62);
  background: rgb(255 255 255);
  transform: translateY(-1px) scale(1.08);
}
.dash-archive-refresh-btn:active {
  transform: translateY(0) scale(0.92);
}

/* 搜索框对齐列表卡片风格 */
.dash-archive-search :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: rgb(255 255 255);
  box-shadow: 0 0 0 1px rgb(241 245 249) inset;
  padding: 0 8px;
  transition: box-shadow 0.3s ease;
}
.dash-archive-search :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgb(226 232 240) inset;
}
.dash-archive-search :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgb(148 163 184) inset;
}
.dash-archive-search :deep(.el-input__inner) {
  height: 28px;
  font-size: 13px;
  color: rgb(30 41 59);
}
.dash-archive-search :deep(.el-input__inner::placeholder) {
  color: rgb(148 163 184);
}
.dash-archive-search :deep(.el-input__prefix) {
  margin-right: 4px;
}

/* 域 tabs：用 el-radio-button 重写成极简 pill 风格 */
.dash-archive-tabs {
  --el-border-radius-base: 999px;
}
.dash-archive-tabs :deep(.el-radio-button__inner) {
  height: 26px;
  padding: 0 11px;
  font-size: 12px;
  font-weight: 500;
  line-height: 24px;
  border-radius: 999px !important;
  border: 1px solid transparent;
  background: rgb(241 245 249);
  color: rgb(71 85 105);
  box-shadow: none;
  transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.dash-archive-tabs :deep(.el-radio-button__inner:hover) {
  color: rgb(15 23 42);
  background: rgb(226 232 240);
}
.dash-archive-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  color: #fff;
  background: rgb(15 23 42);
  border-color: rgb(15 23 42);
  box-shadow: none;
}
.dash-archive-tabs :deep(.el-radio-button) {
  margin: 0;
}

/* count badge：圆形、跟 label 紧贴 */
.dash-archive-tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: color 0.2s ease, background-color 0.2s ease;
}
.dash-archive-tab-count--off {
  color: rgb(100 116 139);
  background: rgba(148, 163, 184, 0.22);
}
.dash-archive-tab-count--on {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(255, 255, 255, 0.2);
}

/* 分页 */
.dash-archive-pager-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid rgb(226 232 240);
  border-radius: 7px;
  background: #fff;
  color: rgb(71 85 105);
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-pager-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgb(15 23 42);
  background: rgb(15 23 42);
  color: #fff;
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.4);
}
.dash-archive-pager-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.92);
}
.dash-archive-pager-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
}

/* 页码指示器 */
.dash-archive-pager-indicator {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  height: 24px;
  padding: 0 9px;
  border-radius: 7px;
  background: rgb(248 250 252);
  border: 1px solid rgb(241 245 249);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.dash-archive-pager-current {
  font-size: 12px;
  font-weight: 700;
  color: rgb(15 23 42);
  line-height: 1;
}
.dash-archive-pager-divider {
  font-size: 10px;
  color: rgb(203 213 225);
  margin: 0 1px;
}
.dash-archive-pager-total {
  font-size: 10.5px;
  font-weight: 600;
  color: rgb(100 116 139);
  line-height: 1;
}
</style>
