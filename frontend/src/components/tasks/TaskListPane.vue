<template>
  <div class="flex min-h-0 flex-col rounded-[12px] border border-slate-200/80 bg-white shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] overflow-hidden">
    <header class="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2">
      <span class="text-[11.5px] font-bold tracking-tight text-slate-900">任务列表</span>
      <span class="inline-flex h-5 items-center rounded-full bg-slate-100 px-1.5 text-[10px] font-bold tabular-nums text-slate-700">
        {{ totalItems }} 项
      </span>
    </header>

    <!-- 摘要 chips -->
    <div class="flex flex-wrap gap-1 border-b border-slate-200 bg-slate-50/40 px-2.5 py-1.5">
      <span class="inline-flex h-5 items-center rounded-md border border-slate-200 bg-white px-1.5 text-[10px] font-medium tabular-nums text-slate-700">
        当前页 <b class="ml-1 text-slate-900">{{ filteredItems.length }}</b>
      </span>
      <span class="inline-flex h-5 items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 text-[10px] font-medium tabular-nums text-slate-700">
        <span class="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
        活跃 <b class="text-slate-900">{{ digest.active }}</b>
      </span>
      <span class="inline-flex h-5 items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 text-[10px] font-medium tabular-nums text-slate-700">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        完成 <b class="text-slate-900">{{ digest.completed }}</b>
      </span>
      <span class="inline-flex h-5 items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 text-[10px] font-medium tabular-nums text-slate-700">
        <span class="h-1.5 w-1.5 rounded-full bg-rose-500" />
        失败 <b class="text-slate-900">{{ digest.failed }}</b>
      </span>
    </div>

    <TransitionGroup
      v-if="filteredItems.length"
      tag="div"
      name="task-card"
      class="flex flex-1 min-h-0 flex-col gap-1.5 overflow-auto p-2 task-list-scroll"
    >
      <button
        v-for="item in filteredItems"
        :key="item.id"
        type="button"
        class="task-card group grid w-full grid-cols-[22px_minmax(0,1fr)] gap-1.5 rounded-[8px] border bg-white p-1.5 text-left shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-[border-color,box-shadow,transform] duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5"
        :class="selectedId === item.id
          ? 'border-slate-900 bg-slate-50 shadow-[0_6px_14px_-10px_rgba(15,23,42,0.3)]'
          : 'border-slate-200 hover:border-slate-300 hover:shadow-[0_6px_14px_-10px_rgba(15,23,42,0.18)]'"
        @click="$emit('select', item.id)"
      >
        <span
          class="mt-0.5 inline-flex h-[22px] w-[22px] items-center justify-center rounded-[6px] border border-slate-200 bg-white transition-all duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
        >
          <component :is="domainMeta(item.domain).icon" :size="11" :stroke-width="2.3" :class="domainMeta(item.domain).chipIcon" />
        </span>

        <div class="flex min-w-0 flex-col gap-1">
          <!-- 第一行：标题 | 域 chip + 状态 -->
          <div class="flex items-center justify-between gap-2">
            <span class="truncate text-[12px] font-bold text-slate-900 leading-tight">{{ item.title }}</span>
            <div class="flex flex-shrink-0 items-center gap-1">
              <span
                class="inline-flex h-[18px] items-center gap-0.5 rounded-md px-1.5 text-[10px] font-semibold"
                :class="[domainMeta(item.domain).chipBg, domainMeta(item.domain).chipText]"
              >
                <component :is="domainMeta(item.domain).icon" :size="9" :stroke-width="2.4" />
                {{ item.domain_label }}
              </span>
              <StatusPill :status="item.status" :label="item.status_label" />
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
              <span class="break-words">{{ item.current_step }}</span>
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
          <div v-if="getTaskSummary(item).length" class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span
              v-for="(piece, sIndex) in getTaskSummary(item)"
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
    </TransitionGroup>

    <div v-else class="flex flex-1 min-h-0 items-center justify-center px-6 py-10">
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
  getTaskSummary: { type: Function, required: true },
})

defineEmits(['select', 'quick-filter', 'prev-page', 'next-page'])

function domainMeta(domain) {
  return getTaskDomainMeta(domain)
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
/* 入场：仅在新插入卡片时触发，已存在的轮询更新不会重放 */
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

/* 列表内重新排序时平滑滑动 */
.task-card-move {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

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
