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
      <button
        type="button"
        class="dash-archive-refresh-btn group"
        :disabled="archivesLoading"
        title="刷新归档记录"
        @click="$emit('refresh')"
      >
        <RefreshCw
          :size="14"
          :stroke-width="2.2"
          :class="archivesLoading ? 'animate-spin' : 'transition-transform duration-300 group-hover:rotate-180 group-hover:scale-110'"
        />
      </button>
    </header>

    <!-- 搜索 -->
    <div class="mt-3 flex-shrink-0">
      <div class="dash-archive-search">
        <Search :size="13" :stroke-width="2.2" class="dash-archive-search-icon" />
        <input
          class="dash-archive-search-input"
          :value="searchQuery"
          type="search"
          placeholder="搜索 RJ / 文件名"
          @input="$emit('update:searchQuery', $event.target.value)"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="dash-archive-search-clear"
          title="清空搜索"
          @click="$emit('update:searchQuery', '')"
        >
          <XCircle :size="13" :stroke-width="2.2" />
        </button>
      </div>
    </div>

    <!-- 域 tabs：固定高度横向 rail，避免标签过多时撑高归档面板 -->
    <div class="dash-archive-tab-rail mt-2">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="dash-archive-tab group"
        :class="domainFilter === tab.key ? 'is-active' : 'is-idle'"
        :aria-pressed="domainFilter === tab.key"
        @click="$emit('update:domainFilter', tab.key)"
      >
        <span>{{ tab.label }}</span>
        <span
          v-if="tab.count > 0"
          class="dash-archive-tab-count"
          :class="domainFilter === tab.key ? 'dash-archive-tab-count--on' : 'dash-archive-tab-count--off'"
        >
          {{ tab.count }}
        </span>
      </button>
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
                class="dash-archive-meta-rj"
              >{{ archive.rjcode }}</span>
              <span class="dash-archive-meta-time">{{ formatDate(archive.processed_at) }}</span>
            </div>
          </div>
          <!-- 标签行：domain（同色系无 icon，与左侧色块呼应） + status（留 icon） + 文件大小 -->
          <div class="mt-1.5 flex items-center justify-between gap-1.5">
            <div class="flex flex-wrap items-center gap-1.5">
              <span
                class="dash-archive-domain-chip"
                :class="`dash-archive-domain-chip--${getMeta(archive).key || 'default'}`"
              >
                {{ getMeta(archive).label }}
              </span>
              <span
                class="dash-archive-status-chip"
                :class="`dash-archive-status-chip--${getStatusMeta(archive).key}`"
              >
                <component :is="statusIcon(getStatusMeta(archive).key)" :size="11" :stroke-width="2" :class="statusIconColor(getStatusMeta(archive).key)" />
                {{ getStatusMeta(archive).label }}
              </span>
              <span v-if="archive.isVolumeGroup" class="dash-archive-volume-chip">{{ archive.volumes.length }} 分卷</span>
            </div>
            <span v-if="archive.file_size" class="dash-archive-meta-size">{{ formatFileSize(archive.file_size) }}</span>
          </div>
        </div>

        <button
          v-if="archive.source === 'processed_archive' && getStatusMeta(archive).key === 'failed'"
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
  AlertCircle,
  Archive,
  Activity,
  ChevronLeft,
  ChevronRight,
  MinusCircle,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  Search,
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

const DEFAULT_PAGE_SIZE = 6

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

// 固定 pageSize：归档本身已经有分页，不再按面板高度扩张当前页，避免移动端出现长列表滚动框。
const effectivePageSize = computed(() => {
  const requestedSize = Math.max(3, Number(props.pageSize) || DEFAULT_PAGE_SIZE)
  return Math.min(DEFAULT_PAGE_SIZE, requestedSize)
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
  partial_failed: AlertCircle,
  failed: XCircle,
  cancelled: MinusCircle,
  processing: Activity,
  pending: PauseCircle,
  unknown: Activity,
}

function statusIcon(key) {
  return STATUS_ICON[key] || Activity
}

function statusIconColor(key) {
  if (key === 'completed') return 'text-emerald-600'
  if (key === 'partial_failed') return 'text-amber-600'
  if (key === 'failed') return 'text-rose-600'
  if (key === 'cancelled') return 'text-slate-500'
  if (key === 'processing') return 'text-amber-600'
  if (key === 'pending') return 'text-slate-500'
  return 'text-slate-500'
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.48);
  border-radius: 8px;
  color: rgb(71 85 105);
  background: rgba(255, 255, 255, 0.95);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-refresh-btn:hover {
  color: rgb(15 23 42);
  border-color: rgba(100, 116, 139, 0.62);
  background: rgb(255 255 255);
  transform: translateY(-2px) scale(1.02);
}
.dash-archive-refresh-btn:active {
  transform: scale(0.96);
}
.dash-archive-refresh-btn:disabled {
  cursor: wait;
  opacity: 0.55;
  transform: none;
}

/* 搜索框对齐列表卡片风格 */
.dash-archive-search {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 22px;
  align-items: center;
  height: 30px;
  padding: 0 6px 0 9px;
  border: 1px solid rgb(241 245 249);
  border-radius: 8px;
  background: rgb(255 255 255);
  box-shadow: 0 0 0 1px rgb(241 245 249) inset;
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    background-color 0.3s ease;
}
.dash-archive-search:hover {
  box-shadow: 0 0 0 1px rgb(226 232 240) inset;
}
.dash-archive-search:focus-within {
  border-color: rgb(148 163 184);
  box-shadow: 0 0 0 1px rgb(148 163 184) inset;
}
.dash-archive-search-icon {
  color: rgb(148 163 184);
}
.dash-archive-search-input {
  min-width: 0;
  height: 28px;
  border: 0;
  outline: none;
  background: transparent;
  appearance: none;
  -webkit-appearance: none;
  font-size: 13px;
  color: rgb(30 41 59);
}
.dash-archive-search-input::-webkit-search-decoration,
.dash-archive-search-input::-webkit-search-cancel-button {
  display: none;
}
.dash-archive-search-input::placeholder {
  color: rgb(148 163 184);
}
.dash-archive-search-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: rgb(148 163 184);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-search-clear:hover {
  transform: translateY(-2px) scale(1.02);
  background: rgb(241 245 249);
  color: rgb(71 85 105);
}
.dash-archive-search-clear:active {
  transform: scale(0.96);
}

.dash-archive-tab {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 6px;
  max-width: none;
  height: 24px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  line-height: 22px;
  cursor: pointer;
  letter-spacing: 0;
  white-space: nowrap;
  -webkit-font-smoothing: antialiased;
  text-rendering: geometricPrecision;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
:global(#app [data-section="dashboard-archive"] .dash-archive-tab.dash-archive-tab) {
  font-family: var(--font-body), -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
  font-size: 12px;
  font-weight: 600;
  line-height: 22px;
}
.dash-archive-tab-rail {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 5px;
  min-height: 31px;
  max-height: 32px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 3px 1px 4px;
  scrollbar-width: none;
}
.dash-archive-tab-rail::-webkit-scrollbar {
  display: none;
}
.dash-archive-tab.is-idle {
  background: rgb(241 245 249);
  color: rgb(71 85 105);
  box-shadow: none;
}
.dash-archive-tab.is-idle:hover {
  transform: translateY(-2px) scale(1.02);
  color: rgb(15 23 42);
  background: rgb(226 232 240);
}
.dash-archive-tab.is-active {
  color: rgb(15 23 42);
  background: rgb(226 232 240);
  border-color: rgb(203 213 225);
  box-shadow: none;
}
.dash-archive-tab.is-active:hover {
  transform: translateY(-2px) scale(1.02);
}
.dash-archive-tab:active {
  transform: scale(0.96);
}

/* count badge：紧凑跟随 label，不抢宽度 */
.dash-archive-tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 5px;
  font-size: 10.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: color 0.2s ease, background-color 0.2s ease;
}
:global(#app [data-section="dashboard-archive"] .dash-archive-tab-count.dash-archive-tab-count) {
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1;
}
.dash-archive-tab-count--off {
  color: rgb(100 116 139);
  background: rgba(148, 163, 184, 0.22);
}
.dash-archive-tab-count--on {
  color: rgb(15 23 42);
  background: rgba(255, 255, 255, 0.58);
}

.dash-archive-domain-chip,
.dash-archive-volume-chip {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.dash-archive-domain-chip--import {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.18);
  color: rgb(146 64 14);
}

.dash-archive-domain-chip--existing_folder,
.dash-archive-domain-chip--rj_subtitle {
  background: rgba(20, 184, 166, 0.12);
  border-color: rgba(20, 184, 166, 0.18);
  color: rgb(15 118 110);
}

.dash-archive-domain-chip--subtitle_import {
  background: rgba(168, 85, 247, 0.12);
  border-color: rgba(168, 85, 247, 0.18);
  color: rgb(126 34 206);
}

.dash-archive-domain-chip--asmr_sync,
.dash-archive-domain-chip--circle_completion {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.18);
  color: rgb(4 120 87);
}

.dash-archive-domain-chip--http_download {
  background: rgba(249, 115, 22, 0.12);
  border-color: rgba(249, 115, 22, 0.18);
  color: rgb(194 65 12);
}

.dash-archive-domain-chip--baidu_netdisk,
.dash-archive-domain-chip--upload,
.dash-archive-domain-chip--system,
.dash-archive-domain-chip--default,
.dash-archive-volume-chip {
  background: rgba(100, 116, 139, 0.12);
  border-color: rgba(100, 116, 139, 0.18);
  color: rgb(51 65 85);
}

.dash-archive-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 6px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.dash-archive-status-chip--completed,
.dash-archive-status-chip--success,
.dash-archive-status-chip--finished {
  background: rgba(16, 185, 129, 0.12);
  color: rgb(4 120 87);
}

.dash-archive-status-chip--partial_failed {
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
}

.dash-archive-status-chip--failed {
  background: rgba(244, 63, 94, 0.12);
  color: rgb(190 18 60);
}

.dash-archive-status-chip--cancelled,
.dash-archive-status-chip--canceled {
  background: rgba(148, 163, 184, 0.16);
  color: rgb(71 85 105);
}

.dash-archive-status-chip--processing,
.dash-archive-status-chip--running {
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
}

.dash-archive-status-chip--pending,
.dash-archive-status-chip--waiting_manual,
.dash-archive-status-chip--waiting_retry {
  background: rgba(100, 116, 139, 0.12);
  color: rgb(71 85 105);
}

.dash-archive-status-chip--default {
  background: rgba(148, 163, 184, 0.12);
  color: rgb(71 85 105);
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
.dash-archive-pager-btn:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgb(15 23 42);
  background: rgb(15 23 42);
  color: #fff;
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.4);
}
.dash-archive-pager-btn:active:not(:disabled) {
  transform: scale(0.96);
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

.dash-archive-meta-rj {
  color: rgb(71 85 105);
  font-size: 11px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.dash-archive-meta-time,
.dash-archive-meta-size {
  color: rgb(71 85 105);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.dash-archive-meta-size {
  flex-shrink: 0;
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

.dash-archive-platform-icon {
  width: 18px;
  height: 18px;
  object-fit: contain;
  border-radius: 3px;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-refresh-btn,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-btn {
  background: var(--km-dark-surface-soft) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-refresh-btn:hover,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-btn:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search {
  background: var(--km-dark-surface-soft) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: inset 0 0 0 1px var(--km-dark-border-soft) !important;
  color-scheme: dark;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search:focus-within {
  border-color: var(--km-dark-border-strong) !important;
  box-shadow: inset 0 0 0 1px var(--km-dark-border-strong) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search-input {
  background: transparent !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
  -webkit-text-fill-color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search-input::placeholder {
  color: rgba(255, 255, 255, 0.48) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search-clear {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-search-clear:hover {
  background: var(--km-dark-surface-hover) !important;
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab.is-idle {
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab-rail {
  scrollbar-width: none;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab.is-idle:hover {
  background: rgba(255, 255, 255, 0.1) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab.is-active {
  background: rgba(255, 255, 255, 0.14) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab-count--off {
  background: rgba(255, 255, 255, 0.12) !important;
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-tab-count--on {
  background: rgba(255, 255, 255, 0.2) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-volume-chip {
  background: rgba(255, 255, 255, 0.07) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #f8fafc !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--import {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(245, 158, 11, 0.22) !important;
  color: #fde68a !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--existing_folder,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--rj_subtitle {
  background: rgba(20, 184, 166, 0.14) !important;
  border-color: rgba(45, 212, 191, 0.2) !important;
  color: #ccfbf1 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--subtitle_import {
  background: rgba(168, 85, 247, 0.14) !important;
  border-color: rgba(196, 181, 253, 0.2) !important;
  color: #ede9fe !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--asmr_sync,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--circle_completion {
  background: rgba(16, 185, 129, 0.14) !important;
  border-color: rgba(110, 231, 183, 0.2) !important;
  color: #d1fae5 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-domain-chip--http_download {
  background: rgba(249, 115, 22, 0.16) !important;
  border-color: rgba(251, 146, 60, 0.22) !important;
  color: #fed7aa !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--completed,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--success,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--finished {
  background: rgba(16, 185, 129, 0.14) !important;
  color: #d1fae5 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--partial_failed {
  background: rgba(245, 158, 11, 0.14) !important;
  color: #fde68a !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--failed {
  background: rgba(244, 63, 94, 0.14) !important;
  color: #fecdd3 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--pending,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--waiting_manual,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-status-chip--waiting_retry {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-meta-rj,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-meta-time,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-meta-size {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.22);
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager {
  border-color: var(--km-dark-border) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-indicator {
  background: var(--km-dark-surface-soft) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-current,
:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-total {
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dashboard-archive .dash-archive-pager-divider {
  color: rgba(255, 255, 255, 0.48) !important;
}
</style>
