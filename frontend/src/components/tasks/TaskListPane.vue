<template>
  <div class="task-list-pane">
    <div
      v-if="filteredItems.length"
      class="task-list-scroll flex flex-1 min-h-0 flex-col gap-2 overflow-auto p-2.5"
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

    <!-- 空态：移动端 wrapper padding 收紧到 px-3 py-4，桌面保留宽松 px-6 py-10 -->
    <div v-else class="flex flex-1 min-h-0 items-center justify-center px-3 py-4 md:px-6 md:py-10">
      <AppEmptyState description="当前筛选条件下没有任务" size="lg" />
    </div>

    <div v-if="totalItems > pageSize" class="flex items-center justify-center gap-2 border-t border-slate-200 px-3 py-2.5">
      <button
        type="button"
        class="group inline-flex h-7 w-7 items-center justify-center rounded-[8px] border border-slate-200 bg-white text-slate-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-110 hover:border-slate-300 hover:bg-slate-50 active:scale-90 disabled:pointer-events-none disabled:opacity-40"
        :disabled="currentOffset <= 0"
        @click="$emit('prev-page')"
      >
        <ChevronLeft :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:-translate-x-0.5" />
      </button>
      <span class="text-[11.5px] tabular-nums text-slate-600">
        {{ Math.floor(currentOffset / pageSize) + 1 }} / {{ Math.ceil(totalItems / pageSize) }}
      </span>
      <button
        type="button"
        class="group inline-flex h-7 w-7 items-center justify-center rounded-[8px] border border-slate-200 bg-white text-slate-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-110 hover:border-slate-300 hover:bg-slate-50 active:scale-90 disabled:pointer-events-none disabled:opacity-40"
        :disabled="currentOffset + pageSize >= totalItems"
        @click="$emit('next-page')"
      >
        <ChevronRight :size="13" :stroke-width="2.3" class="transition-transform duration-300 group-hover:translate-x-0.5" />
      </button>
    </div>
  </div>
</template>

<script setup>
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
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

defineProps({
  filteredItems: { type: Array, default: () => [] },
  totalItems: { type: Number, default: 0 },
  currentOffset: { type: Number, default: 0 },
  pageSize: { type: Number, default: 80 },
  selectedId: { type: String, default: '' },
  digest: { type: Object, default: () => ({ active: 0, completed: 0, failed: 0 }) },
  formatRJCode: { type: Function, required: true },
  showProgress: { type: Function, required: true },
  shouldShowStep: { type: Function, required: true },
  getRecoveredNotice: { type: Function, required: true },
})

defineEmits(['select', 'quick-filter', 'prev-page', 'next-page'])

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

/* ---- 滚动条 ---- */
.task-list-scroll::-webkit-scrollbar {
  width: 6px;
}
.task-list-scroll::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 999px;
}
.task-list-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.55);
}
</style>
