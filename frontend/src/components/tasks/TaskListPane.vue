<template>
  <div ref="paneRef" class="task-list-pane">
    <Transition :name="pageTransitionName" mode="out-in" @after-enter="schedulePageSizeMeasure">
      <div
        v-if="filteredItems.length"
        :key="pageKey"
        class="task-list-scroll flex flex-1 min-h-0 flex-col gap-2 p-2.5"
      >
        <button
          v-for="item in filteredItems"
          :key="item.id"
          type="button"
          class="task-card group"
          :class="{ 'is-active': selectedId === item.id }"
          @click="$emit('select', item.id)"
        >
          <component
            :is="taskIcon(item)"
            :size="16"
            :stroke-width="2"
            class="mt-[3px] flex-shrink-0 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
            :class="taskIconClass(item)"
          />

          <div class="flex min-w-0 flex-col gap-1">
            <!-- 第一行：标题 | 域 chip（无 icon） + 状态 -->
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-[12.5px] font-bold text-slate-900 leading-tight">{{ item.title }}</span>
              <div class="flex flex-shrink-0 items-center gap-1">
                <span
                  class="task-domain-chip inline-flex h-[18px] items-center rounded-full px-2 text-[10px] font-semibold"
                  :class="[domainMeta(item.domain).chipBg, domainMeta(item.domain).chipText]"
                >
                  {{ taskDomainLabel(item) }}
                </span>
                <StatusPill :status="statusForPill(item)" :label="statusLabelForPill(item)" />
              </div>
            </div>

            <!-- 第二行：RJ + 副标题/来源/步骤 一行内联 -->
            <div v-if="formatRJCode(item.rjcode) || item.subtitle || shouldShowStep(item) || (item.source_label && item.source_label !== item.title && item.source_label !== item.subtitle)" class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10.5px] text-slate-500 leading-tight">
              <span v-if="formatRJCode(item.rjcode)" class="flex-shrink-0 font-bold tabular-nums text-amber-700">{{ formatRJCode(item.rjcode) }}</span>
              <span v-if="item.subtitle" class="min-w-0 break-words">{{ item.subtitle }}</span>
              <span
                v-if="item.source_label && item.source_label !== item.title && item.source_label !== item.subtitle"
                class="min-w-0 break-words text-slate-400"
              >· {{ item.source_label }}</span>
              <span
                v-if="shouldShowStep(item)"
                class="inline-flex min-w-0 items-start gap-0.5 text-slate-400"
              >
                <Activity :size="9" :stroke-width="2.3" class="mt-[2px] flex-shrink-0" />
                <span class="break-words">{{ displayStep(item) }}</span>
              </span>
            </div>

            <!-- 进度条 -->
            <div v-if="showProgress(item)" class="flex items-center gap-1.5">
              <div class="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full transition-all duration-700 ease-out" :class="domainMeta(item.domain).bar" :style="{ width: `${item.progress}%` }" />
              </div>
              <span class="text-[10px] font-bold tabular-nums text-slate-600">{{ item.progress }}%</span>
            </div>

            <!-- 已恢复 -->
            <div v-if="getRecoveredNotice(item)" class="flex items-start gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
              <CheckCircle :size="10" :stroke-width="2.3" class="mt-px flex-shrink-0 text-emerald-600" />
              <span>{{ getRecoveredNotice(item) }}</span>
            </div>

            <!-- 摘要：图标 + 数字 紧凑 stat strip（hover 显示标签） -->
            <div v-if="item.summaryPieces?.length" class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span
                v-for="(piece, sIndex) in item.summaryPieces"
                :key="`${item.id}-summary-${sIndex}`"
                class="inline-flex items-center gap-0.5 text-[11px] font-bold tabular-nums leading-tight"
                :class="summaryColor(piece, item.domain)"
                :title="extractSummaryLabel(piece) || piece"
              >
                <component
                  :is="summaryIcon(piece)"
                  :size="11"
                  :stroke-width="2.3"
                />
                {{ extractSummaryValue(piece) }}
              </span>
            </div>
          </div>
        </button>
      </div>
      <div v-else :key="`empty-${pageKey}`" class="flex flex-1 min-h-0 items-center justify-center px-3 py-4 md:px-6 md:py-10">
        <AppEmptyState description="当前筛选条件下没有任务" size="lg" />
      </div>
    </Transition>

    <div v-if="totalItems > pageSize" ref="pagerRef" class="task-list-pager">
      <div class="task-list-pager-summary">
        <span class="task-list-pager-range">{{ pageStart }}-{{ pageEnd }}</span>
        <span>共 {{ totalItems }} 条</span>
      </div>

      <div class="task-list-pager-controls">
        <button
          type="button"
          class="task-list-pager-button task-list-pager-icon group"
          :disabled="currentPage <= 1"
          title="第一页"
          @click="goToPage(1)"
        >
          <ChevronsLeft :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:-translate-x-0.5" />
        </button>
        <button
          type="button"
          class="task-list-pager-button task-list-pager-icon group"
          :disabled="currentPage <= 1"
          title="上一页"
          @click="$emit('prev-page')"
        >
          <ChevronLeft :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:-translate-x-0.5" />
        </button>

        <button
          v-for="page in visiblePages"
          :key="page"
          type="button"
          class="task-list-pager-button task-list-pager-number"
          :class="{ 'is-active': page === currentPage }"
          @click="goToPage(page)"
        >
          {{ page }}
        </button>

        <button
          type="button"
          class="task-list-pager-button task-list-pager-icon group"
          :disabled="currentPage >= totalPages"
          title="下一页"
          @click="$emit('next-page')"
        >
          <ChevronRight :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:translate-x-0.5" />
        </button>
        <button
          type="button"
          class="task-list-pager-button task-list-pager-icon group"
          :disabled="currentPage >= totalPages"
          title="最后一页"
          @click="goToPage(totalPages)"
        >
          <ChevronsRight :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:translate-x-0.5" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Circle,
  CloudDownload,
  Database,
  Download,
  FileArchive,
  Globe,
  HardDrive,
  Hash,
  Search,
  XCircle,
} from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatusPill from '../dashboard/StatusPill.vue'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'
import { getHttpDownloadDisplayMeta } from '../common/httpDownloadPlatformMeta.js'

const props = defineProps({
  filteredItems: { type: Array, default: () => [] },
  totalItems: { type: Number, default: 0 },
  currentOffset: { type: Number, default: 0 },
  pageSize: { type: Number, default: 80 },
  pageDirection: { type: String, default: 'next' },
  selectedId: { type: String, default: '' },
  digest: { type: Object, default: () => ({ active: 0, completed: 0, failed: 0 }) },
  formatRJCode: { type: Function, required: true },
  showProgress: { type: Function, required: true },
  shouldShowStep: { type: Function, required: true },
  getRecoveredNotice: { type: Function, required: true },
})

const emit = defineEmits(['select', 'quick-filter', 'page-size-change', 'prev-page', 'next-page', 'go-page'])

const paneRef = ref(null)
const pagerRef = ref(null)

let resizeObserver = null
let measureRaf = 0
let measureTimer = 0

const pageKey = computed(() => `${props.currentOffset}-${props.pageSize}-${props.filteredItems.map(item => item?.id || '').join('|')}`)
const pageTransitionName = computed(() => props.pageDirection === 'prev' ? 'task-page-prev' : 'task-page-next')
const totalPages = computed(() => Math.max(1, Math.ceil(props.totalItems / Math.max(props.pageSize, 1))))
const currentPage = computed(() => Math.min(totalPages.value, Math.floor(props.currentOffset / Math.max(props.pageSize, 1)) + 1))
const pageStart = computed(() => props.totalItems ? props.currentOffset + 1 : 0)
const pageEnd = computed(() => Math.min(props.totalItems, props.currentOffset + props.filteredItems.length))
const visiblePages = computed(() => {
  const total = totalPages.value
  const current = currentPage.value
  const windowSize = total >= 10 ? 5 : Math.min(total, 7)
  let start = Math.max(1, current - Math.floor(windowSize / 2))
  let end = Math.min(total, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})

function goToPage(page) {
  const normalized = Math.min(Math.max(1, Number(page) || 1), totalPages.value)
  if (normalized === currentPage.value) return
  emit('go-page', normalized)
}

function numericCssValue(style, property, fallback = 0) {
  if (!style) return fallback
  const value = Number.parseFloat(style.getPropertyValue(property))
  return Number.isFinite(value) ? value : fallback
}

function estimatePageSize() {
  const pane = paneRef.value
  if (!pane) return
  const paneHeight = pane.clientHeight || 0
  if (paneHeight <= 0) return

  const list = pane.querySelector('.task-list-scroll')
  const listStyle = typeof window !== 'undefined' && list ? window.getComputedStyle(list) : null
  const paddingTop = numericCssValue(listStyle, 'padding-top', 10)
  const paddingBottom = numericCssValue(listStyle, 'padding-bottom', 10)
  const cardGap = numericCssValue(listStyle, 'row-gap', 8) || numericCssValue(listStyle, 'gap', 8)
  const safetySpace = 8
  const listHeight = list?.clientHeight || Math.max(0, paneHeight - (pagerRef.value?.offsetHeight || 48))
  const availableHeight = Math.max(0, listHeight - paddingTop - paddingBottom - safetySpace)
  const cards = Array.from(pane.querySelectorAll('.task-card'))
  if (props.filteredItems.length && cards.length === 0) {
    scheduleDelayedPageSizeMeasure()
    return
  }

  const measuredHeights = cards
    .map((card) => card.getBoundingClientRect?.().height || card.offsetHeight || 0)
    .filter((height) => Number.isFinite(height) && height > 0)
  const averageCardHeight = measuredHeights.length
    ? measuredHeights.reduce((total, height) => total + height, 0) / measuredHeights.length
    : 82

  let usedHeight = 0
  let exactFitCount = 0
  for (const height of measuredHeights) {
    const nextUsedHeight = usedHeight + height + (exactFitCount > 0 ? cardGap : 0)
    if (nextUsedHeight > availableHeight) break
    usedHeight = nextUsedHeight
    exactFitCount += 1
  }

  let nextSize = Math.max(1, exactFitCount || Math.floor((availableHeight + cardGap) / (averageCardHeight + cardGap)))
  if (exactFitCount >= cards.length && props.currentOffset + props.filteredItems.length < props.totalItems) {
    const sortedHeights = [...measuredHeights].sort((a, b) => a - b)
    const typicalHeight = sortedHeights[Math.floor(sortedHeights.length / 2)] || averageCardHeight
    const remainingHeight = Math.max(0, availableHeight - usedHeight)
    const extraCount = Math.floor((remainingHeight + cardGap) / (typicalHeight + cardGap))
    nextSize += Math.max(0, extraCount)
  }

  if (Number.isFinite(nextSize) && nextSize !== props.pageSize) {
    emit('page-size-change', nextSize)
  }
}

function schedulePageSizeMeasure() {
  if (typeof window === 'undefined') return
  if (measureRaf) window.cancelAnimationFrame(measureRaf)
  measureRaf = window.requestAnimationFrame(() => {
    measureRaf = 0
    estimatePageSize()
  })
}

function scheduleDelayedPageSizeMeasure() {
  if (typeof window === 'undefined') return
  if (measureTimer) window.clearTimeout(measureTimer)
  measureTimer = window.setTimeout(() => {
    measureTimer = 0
    schedulePageSizeMeasure()
  }, 360)
}

watch(() => [pageKey.value, props.totalItems], () => {
  nextTick(schedulePageSizeMeasure)
})

onMounted(() => {
  nextTick(schedulePageSizeMeasure)
  if (typeof ResizeObserver !== 'undefined' && paneRef.value) {
    resizeObserver = new ResizeObserver(schedulePageSizeMeasure)
    resizeObserver.observe(paneRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (measureRaf && typeof window !== 'undefined') window.cancelAnimationFrame(measureRaf)
  if (measureTimer && typeof window !== 'undefined') window.clearTimeout(measureTimer)
})

function domainMeta(domain) {
  return getTaskDomainMeta(domain)
}

function isDownloadProviderTask(item) {
  return ['http_download', 'baidu_netdisk'].includes(String(item?.domain || '').trim())
}

function httpDisplayMeta(item) {
  return getHttpDownloadDisplayMeta(item)
}

function taskIcon(item) {
  if (isDownloadProviderTask(item)) return httpDisplayMeta(item).icon || domainMeta(item.domain).icon
  return domainMeta(item.domain).icon
}

function taskIconClass(item) {
  return isDownloadProviderTask(item) && httpDisplayMeta(item).icon
    ? 'task-platform-icon'
    : ['task-domain-icon', domainMeta(item.domain).taskIconClass || 'task-domain-icon--system']
}

function taskDomainLabel(item) {
  if (isDownloadProviderTask(item)) return httpDisplayMeta(item).label || item.domain_label || domainMeta(item.domain).label
  return item.domain_label
}

function isCancelledTask(item) {
  const status = String(item?.status || '').trim().toLowerCase()
  const text = [item?.status_label, item?.error_message, item?.current_step].join(' ')
  return status === 'cancelled' || status === 'canceled' || text.includes('用户取消')
}

function statusForPill(item) {
  return isCancelledTask(item) ? 'cancelled' : item?.status
}

function statusLabelForPill(item) {
  return isCancelledTask(item) ? '已取消' : item?.status_label
}

function displayStep(item) {
  return isCancelledTask(item) ? '用户取消' : item?.current_step
}

// 摘要 piece 形如 "候选 66" / "DLsite 39"，把数字和名称拆开渲染成 stat strip
function extractSummaryValue(piece) {
  const text = String(piece || '').trim()
  const match = text.match(/(-?\d[\d,.\s%]*)\s*$/)
  return match ? match[1].trim() : text
}

function extractSummaryLabel(piece) {
  const text = String(piece || '').trim()
  const match = text.match(/(-?\d[\d,.\s%]*)\s*$/)
  if (!match) return ''
  return text.slice(0, match.index).trim()
}

// 按摘要文字关键字选个语义图标
function summaryIcon(piece) {
  const text = String(piece || '').toLowerCase()
  if (text.includes('dlsite') || text.includes('dl')) return Database
  if (text.includes('可下载')) return CloudDownload
  if (text.includes('下载')) return Download
  if (text.includes('本地')) return HardDrive
  if (text.includes('缺失')) return AlertCircle
  if (text.includes('候选') || text.includes('搜索')) return Search
  if (text.includes('链接') || text.includes('远程')) return Globe
  if (text.includes('完成') || text.includes('成功')) return CheckCircle
  if (text.includes('失败') || text.includes('错误')) return XCircle
  if (text.includes('总') || text.includes('合计')) return Hash
  return Circle
}

// 按语义关键字给颜色
function summaryColor(piece, domain) {
  const text = String(piece || '').toLowerCase()
  if (text.includes('缺失') || text.includes('失败') || text.includes('错误')) return 'text-rose-600'
  if (text.includes('可下载')) return 'text-emerald-600'
  if (text.includes('本地')) return 'text-amber-600'
  if (text.includes('dlsite') || text.includes('dl')) return 'text-sky-600'
  if (text.includes('完成') || text.includes('成功')) return 'text-emerald-600'
  return getTaskDomainMeta(domain).chipIcon || 'text-slate-600'
}
</script>

<style scoped>
/* ============================================================
 * 任务列表面板：简约白底容器 + 无边框卡片
 * ============================================================ */

.task-list-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 2px 8px -6px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.task-list-scroll {
  overflow: hidden;
}

.task-list-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 48px;
  padding: 8px 10px;
  border-top: 1px solid rgb(226 232 240);
}

.task-list-pager-summary {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.task-list-pager-range {
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.task-list-pager-controls {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
}

.task-list-pager-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: #ffffff;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-list-pager-button:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  color: #0f172a;
}

.task-list-pager-button:active:not(:disabled) {
  transform: scale(0.96);
}

.task-list-pager-button:disabled {
  pointer-events: none;
  opacity: 0.42;
}

.task-list-pager-icon {
  width: 28px;
}

.task-list-pager-number {
  min-width: 28px;
  padding: 0 8px;
}

.task-list-pager-number.is-active {
  border-color: #0f172a;
  background: #0f172a;
  color: #ffffff;
}

/* ---- 任务卡片 ---- */
.task-card {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 10px;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  border-left: 2px solid transparent;
  border-radius: 10px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
.task-card:hover {
  background: rgb(248 250 252);
}
.task-card.is-active {
  background: rgba(15, 23, 42, 0.04);
  border-left-color: #0f172a;
}

.task-domain-icon {
  color: var(--task-domain-icon-color, #475569);
  stroke: currentColor;
  filter: none;
  opacity: 1;
}

.task-domain-icon--import {
  --task-domain-icon-color: #d97706;
}

.task-domain-icon--existing_folder {
  --task-domain-icon-color: #0284c7;
}

.task-domain-icon--rj_subtitle {
  --task-domain-icon-color: #0284c7;
}

.task-domain-icon--subtitle_import {
  --task-domain-icon-color: #7c3aed;
}

.task-domain-icon--asmr_sync {
  --task-domain-icon-color: #059669;
}

.task-domain-icon--http_download {
  --task-domain-icon-color: #ea580c;
}

.task-domain-icon--upload {
  --task-domain-icon-color: #2563eb;
}

.task-domain-icon--circle_completion {
  --task-domain-icon-color: #0f766e;
}

.task-domain-icon--system {
  --task-domain-icon-color: #64748b;
}

.task-platform-icon {
  width: 16px;
  height: 16px;
  object-fit: contain;
  border-radius: 3px;
  filter: none;
  opacity: 1;
}

/* ---- 动画过渡 ---- */
.task-card-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.task-card-enter-to {
  opacity: 1;
  transform: translateY(0);
}
.task-card-enter-active {
  transition: opacity 0.35s ease, transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-card-move {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-page-next-enter-active,
.task-page-next-leave-active,
.task-page-prev-enter-active,
.task-page-prev-leave-active {
  transition: opacity 0.22s ease, transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-page-next-enter-from {
  opacity: 0;
  transform: translateX(18px);
}

.task-page-next-leave-to {
  opacity: 0;
  transform: translateX(-18px);
}

.task-page-prev-enter-from {
  opacity: 0;
  transform: translateX(-18px);
}

.task-page-prev-leave-to {
  opacity: 0;
  transform: translateX(18px);
}

@media (max-width: 520px) {
  .task-list-pager {
    align-items: flex-start;
    flex-direction: column;
  }

  .task-list-pager-controls {
    width: 100%;
    overflow: hidden;
  }
}
</style>
