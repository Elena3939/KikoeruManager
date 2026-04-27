<template>
  <div class="flex min-h-0 flex-col overflow-auto rounded-[12px] border border-slate-200/80 bg-white shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] detail-scroll">
    <header class="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-100 bg-white/95 px-4 py-3 backdrop-blur">
      <span class="text-[13px] font-bold tracking-tight text-slate-900">任务详情</span>
      <button
        v-if="item?.route_hint"
        type="button"
        class="group inline-flex h-7 cursor-pointer items-center gap-1 rounded-[8px] border border-slate-200 bg-white px-2.5 text-[11.5px] font-medium text-slate-700 shadow-[0_1px_3px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.03] hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 active:scale-95"
        @click="$emit('open-route', item)"
      >
        <ArrowRight :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-1" />
        <span>打开关联页面</span>
      </button>
    </header>

    <template v-if="item">
      <div v-if="detailLoading" class="flex items-center gap-2 px-4 pt-3 text-[12px] text-slate-500">
        <RefreshCw :size="13" :stroke-width="2.3" class="animate-spin" />
        <span>正在读取完整任务详情...</span>
      </div>

      <!-- Hero -->
      <div class="flex items-start gap-3 px-4 pt-3.5 pb-3">
        <span
          class="mt-0.5 inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[10px] border border-slate-200 bg-white transition-all duration-300 hover:scale-105 hover:rotate-[-6deg]"
        >
          <component :is="domainMeta(item.domain).icon" :size="16" :stroke-width="2.2" :class="domainMeta(item.domain).chipIcon" />
        </span>
        <div class="flex-1 min-w-0">
          <div class="flex items-start justify-between gap-2.5">
            <h2 class="m-0 text-[16px] font-bold tracking-tight text-slate-900 leading-tight">{{ item.title }}</h2>
            <StatusPill :status="item.status" :label="item.status_label" />
          </div>
          <p v-if="item.subtitle" class="m-0 mt-1 text-[12px] leading-snug text-slate-500">{{ item.subtitle }}</p>
          <div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
            <span class="inline-flex items-center gap-1 font-medium" :class="domainMeta(item.domain).chipIcon">
              <component :is="domainMeta(item.domain).icon" :size="11" :stroke-width="2.3" />
              <span class="text-slate-700">{{ item.domain_label }}</span>
            </span>
            <span v-if="formatRJCode(item.rjcode)" class="font-bold tabular-nums text-slate-700">{{ formatRJCode(item.rjcode) }}</span>
          </div>
        </div>
      </div>

      <!-- 元信息：定义列表 2 列，无独立边框 -->
      <div class="mx-4 grid grid-cols-2 gap-x-6 gap-y-2 border-y border-slate-100 py-3">
        <div class="flex flex-col">
          <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">来源</span>
          <span class="mt-0.5 break-all text-[12px] font-semibold text-slate-800">{{ item.source_label || '—' }}</span>
        </div>
        <div class="flex flex-col">
          <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">RJ</span>
          <span class="mt-0.5 break-all text-[12px] font-bold tabular-nums text-slate-800">{{ formatRJCode(item.rjcode) || '—' }}</span>
        </div>
        <div class="flex flex-col">
          <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">创建时间</span>
          <span class="mt-0.5 text-[12px] font-semibold tabular-nums text-slate-800">{{ formatDateTime(item.created_at) }}</span>
        </div>
        <div class="flex flex-col">
          <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">完成时间</span>
          <span class="mt-0.5 text-[12px] font-semibold tabular-nums text-slate-800">{{ formatDateTime(item.completed_at) }}</span>
        </div>
      </div>

      <!-- 当前状态 -->
      <section class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-indigo-500" />
          当前状态
        </span>

        <div v-if="getRecoveredNotice(item)" class="mb-2 flex items-start gap-2 rounded-[10px] border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white px-3 py-2 text-[11.5px] text-emerald-800 shadow-[0_2px_8px_-4px_rgba(16,185,129,0.2)]">
          <CheckCircle :size="13" :stroke-width="2.3" class="mt-px flex-shrink-0 text-emerald-600" />
          <div>
            <div class="font-bold">已恢复</div>
            <div class="mt-0.5">{{ getRecoveredNotice(item) }}</div>
          </div>
        </div>

        <div class="max-h-[96px] overflow-y-auto break-words text-[12.5px] leading-relaxed text-slate-700 detail-scroll">
          {{ item.current_step || '-' }}
        </div>

        <div v-if="showProgress(item)" class="mt-2 flex items-center gap-2">
          <div class="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full transition-all duration-700 ease-out" :class="domainMeta(item.domain).bar" :style="{ width: `${item.progress}%` }" />
          </div>
          <span class="text-[10.5px] font-bold tabular-nums text-slate-600">{{ item.progress }}%</span>
        </div>

        <div
          v-if="item.error_message"
          class="mt-2 flex max-h-[160px] items-start gap-1.5 overflow-y-auto rounded-[10px] border px-3 py-2 text-[11.5px] break-words detail-scroll"
          :class="item.status === 'completed'
            ? 'border-emerald-200 bg-gradient-to-br from-emerald-50 to-white text-emerald-800 shadow-[0_2px_8px_-4px_rgba(16,185,129,0.2)]'
            : 'border-rose-200 bg-gradient-to-br from-rose-50 to-white text-rose-700 shadow-[0_2px_8px_-4px_rgba(225,29,72,0.18)]'"
        >
          <component
            :is="item.status === 'completed' ? CheckCircle : AlertTriangle"
            :size="12"
            :stroke-width="2.3"
            class="mt-px flex-shrink-0"
          />
          <span>
            <b v-if="item.status === 'completed'" class="mr-0.5 font-bold">已修复 ·</b>
            {{ item.error_message }}
          </span>
        </div>

        <div
          v-if="getDLsiteFailureReason(item)"
          class="mt-2 flex max-h-[160px] items-start gap-1.5 overflow-y-auto rounded-[10px] border px-3 py-2 text-[11.5px] break-words detail-scroll"
          :class="item.status === 'completed'
            ? 'border-emerald-200 bg-gradient-to-br from-emerald-50 to-white text-emerald-800 shadow-[0_2px_8px_-4px_rgba(16,185,129,0.2)]'
            : 'border-rose-200 bg-gradient-to-br from-rose-50 to-white text-rose-700 shadow-[0_2px_8px_-4px_rgba(225,29,72,0.18)]'"
        >
          <component
            :is="item.status === 'completed' ? CheckCircle : AlertTriangle"
            :size="12"
            :stroke-width="2.3"
            class="mt-px flex-shrink-0"
          />
          <span>
            <b v-if="item.status === 'completed'" class="mr-0.5 font-bold">已修复 ·</b>
            DLsite 抓取失败原因：{{ getDLsiteFailureReason(item) }}
          </span>
        </div>
      </section>

      <!-- 关键指标：横向数据条，无独立框 -->
      <section v-if="item.metrics?.length" class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2.5 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-amber-500" />
          关键指标
        </span>
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div
            v-for="(metric, mIndex) in item.metrics"
            :key="`${item.id}-${metric.label}`"
            class="detail-fade-up flex items-baseline gap-1.5"
            :style="{ animationDelay: `${mIndex * 30}ms` }"
          >
            <span class="text-[20px] font-bold tabular-nums text-slate-900 leading-none">{{ metric.value }}</span>
            <span class="text-[11px] text-slate-500">{{ metric.label }}</span>
          </div>
        </div>
      </section>

      <!-- 进度元信息：定义列表 2 列，无独立边框 -->
      <section v-if="circleMeta.length" class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2.5 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-violet-500" />
          进度元信息
        </span>
        <div class="grid grid-cols-2 gap-x-6 gap-y-2.5">
          <div
            v-for="(entry, eIndex) in circleMeta"
            :key="`${item.id}-${entry.label}`"
            class="detail-fade-up flex flex-col"
            :style="{ animationDelay: `${eIndex * 25}ms` }"
          >
            <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">{{ entry.label }}</span>
            <span class="mt-0.5 break-all text-[12px] font-semibold text-slate-800">{{ entry.value }}</span>
          </div>
        </div>
      </section>

      <!-- 进度日志（终端风） -->
      <section v-if="circleLog.length" class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-sky-500" />
          进度日志
        </span>
        <div class="max-h-[280px] overflow-y-auto rounded-[10px] border border-slate-900 bg-gradient-to-br from-slate-950 to-slate-900 p-3 font-mono text-[11px] leading-[1.7] text-slate-300 shadow-[inset_0_2px_8px_rgba(0,0,0,0.4)] detail-scroll">
          <div
            v-for="(entry, lIndex) in circleLog"
            :key="`${item.id}-progress-${lIndex}`"
            class="grid grid-cols-[110px_42px_1fr] items-baseline gap-2.5 border-b border-dashed border-slate-700/50 py-0.5 last:border-b-0 transition-colors hover:bg-slate-800/40"
          >
            <span class="truncate text-slate-500 tabular-nums">{{ formatDateTime(entry.time) }}</span>
            <span class="text-right font-bold tabular-nums text-sky-400">{{ entry.progress }}%</span>
            <span class="break-words text-slate-200">{{ entry.message }}</span>
          </div>
        </div>
      </section>

      <!-- 文件树 -->
      <section
        v-for="section in fileTreeSections"
        :key="`${item.id}-${section.key}`"
        class="border-b border-slate-200 px-4 pt-3.5 pb-3.5"
      >
        <div class="mb-2 flex items-start justify-between gap-2 flex-wrap">
          <span class="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
            <span class="h-1 w-1 rounded-full bg-emerald-500" />
            {{ section.label }}
          </span>
          <div class="flex flex-wrap items-center gap-2">
            <div class="flex flex-wrap gap-1">
              <button
                v-for="mode in [
                  { value: 'all', label: '全部' },
                  { value: 'added', label: '只看新增' },
                  { value: 'removed', label: '只看删除' },
                ]"
                :key="mode.value"
                type="button"
                class="group inline-flex h-6 items-center rounded-[7px] border px-2 text-[10.5px] font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:scale-[1.04] active:scale-95"
                :class="treeFilterMode === mode.value
                  ? 'border-slate-900 bg-slate-900 text-white shadow-[0_3px_10px_-4px_rgba(15,23,42,0.4)]'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'"
                @click="$emit('update:treeFilterMode', mode.value)"
              >
                {{ mode.label }}
              </button>
              <button type="button" class="inline-flex h-6 items-center rounded-[7px] border border-slate-200 bg-white px-2 text-[10.5px] font-semibold text-slate-600 transition-all duration-300 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 active:scale-95" @click="$emit('expand-section', section, true)">展开全部</button>
              <button type="button" class="inline-flex h-6 items-center rounded-[7px] border border-slate-200 bg-white px-2 text-[10.5px] font-semibold text-slate-600 transition-all duration-300 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-slate-300 hover:bg-slate-50 active:scale-95" @click="$emit('expand-section', section, false)">收起全部</button>
            </div>
            <div class="flex flex-wrap gap-1">
              <span v-if="section.totalCount" class="inline-flex h-5 items-center rounded-md border border-slate-200 bg-white px-1.5 text-[10px] font-bold tabular-nums text-slate-700">共 {{ section.totalCount }} 项</span>
              <span v-if="section.addedCount" class="inline-flex h-5 items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 text-[10px] font-bold tabular-nums text-emerald-700">
                <span class="h-1 w-1 rounded-full bg-emerald-500" /> 新增 {{ section.addedCount }}
              </span>
              <span v-if="section.removedCount" class="inline-flex h-5 items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 text-[10px] font-bold tabular-nums text-slate-500">
                <span class="h-1 w-1 rounded-full bg-slate-400" /> 删除 {{ section.removedCount }}
              </span>
            </div>
          </div>
        </div>

        <div class="max-h-[320px] overflow-y-auto rounded-[10px] border border-slate-200 bg-slate-50/50 detail-scroll">
          <div
            v-for="entry in section.rows"
            :key="`${item.id}-${section.key}-${entry.key}`"
            class="flex items-center justify-between gap-2 border-b border-slate-200/70 py-1 pr-2.5 last:border-b-0 transition-colors duration-200 hover:bg-white"
            :class="[
              entry.status === 'added' ? 'bg-gradient-to-r from-emerald-50/60 to-transparent' : '',
              entry.status === 'removed' ? 'bg-slate-100/40 line-through opacity-70' : '',
            ]"
            :style="{ paddingLeft: `${12 + entry.depth * 18}px` }"
          >
            <div class="flex min-w-0 flex-1 items-center gap-1.5">
              <button
                v-if="entry.hasChildren"
                type="button"
                class="group inline-flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded text-slate-400 transition-all duration-200 hover:bg-slate-200 hover:text-slate-700"
                @click="$emit('toggle-node', entry.key, entry.defaultExpanded)"
              >
                <component :is="entry.expanded ? ChevronDown : ChevronRight" :size="11" :stroke-width="2.4" class="transition-transform duration-200 group-hover:scale-110" />
              </button>
              <span v-else class="inline-block h-[18px] w-[18px] flex-shrink-0" />
              <span
                class="inline-flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded transition-transform duration-200 hover:scale-110"
                :class="entry.type === 'dir' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'"
              >
                <component :is="entry.type === 'dir' ? Folder : File" :size="11" :stroke-width="2.3" />
              </span>
              <span class="min-w-0 truncate text-[11.5px] text-slate-800">{{ entry.label }}</span>
              <span v-if="entry.status === 'added'" class="inline-flex h-[18px] items-center rounded-md border border-emerald-200 bg-emerald-50 px-1.5 text-[9.5px] font-bold text-emerald-700">新增</span>
            </div>
            <span v-if="entry.sizeText" class="flex-shrink-0 text-[10.5px] tabular-nums text-slate-400">{{ entry.sizeText }}</span>
          </div>
        </div>
      </section>

      <!-- 路径信息：label + 行内 code，无重边框 -->
      <section class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2.5 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-slate-500" />
          路径信息
        </span>
        <div class="space-y-2.5">
          <div class="flex flex-col">
            <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">源路径</span>
            <code class="mt-1 block max-h-[120px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-700 break-all whitespace-pre-wrap detail-scroll">{{ item.source_path || '—' }}</code>
          </div>
          <div class="flex flex-col">
            <span class="text-[10px] font-medium uppercase tracking-wider text-slate-400">输出路径</span>
            <code class="mt-1 block max-h-[120px] overflow-y-auto rounded-[8px] bg-slate-50 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-700 break-all whitespace-pre-wrap detail-scroll">{{ getOutputPath(item) || '—' }}</code>
          </div>
        </div>
      </section>

      <!-- 操作按钮 -->
      <section class="flex flex-wrap gap-2 px-4 py-4">
        <button
          v-for="action in item.actions || []"
          :key="`${item.id}-${action}`"
          type="button"
          class="group inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-[10px] border px-3.5 text-[12.5px] font-medium shadow-[0_1px_3px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.03] active:translate-y-0 active:scale-95"
          :class="actionToneClass(action)"
          @click="$emit('action', item, action)"
        >
          <component :is="actionIcon(action)" :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:rotate-12 group-hover:scale-110" />
          {{ getActionLabel(action) }}
        </button>
      </section>
    </template>

    <div v-else class="flex flex-1 items-center justify-center px-6 py-12">
      <AppEmptyState description="选择左侧任务查看详情" size="lg" />
    </div>
  </div>
</template>

<script setup>
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  XCircle,
  Activity,
} from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatusPill from '../dashboard/StatusPill.vue'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'

defineProps({
  item: { type: Object, default: null },
  detailLoading: { type: Boolean, default: false },
  fileTreeSections: { type: Array, default: () => [] },
  circleMeta: { type: Array, default: () => [] },
  circleLog: { type: Array, default: () => [] },
  treeFilterMode: { type: String, default: 'all' },
  formatRJCode: { type: Function, required: true },
  formatDateTime: { type: Function, required: true },
  showProgress: { type: Function, required: true },
  getRecoveredNotice: { type: Function, required: true },
  getDLsiteFailureReason: { type: Function, required: true },
  getOutputPath: { type: Function, required: true },
})

defineEmits(['open-route', 'action', 'update:treeFilterMode', 'expand-section', 'toggle-node'])

function domainMeta(domain) {
  return getTaskDomainMeta(domain)
}

const ACTION_ICON_MAP = {
  pause: PauseCircle,
  resume: PlayCircle,
  cancel: XCircle,
  retry_waiting: RotateCcw,
  delete_waiting_retry: XCircle,
  open_subtitle_import: ArrowRight,
  open_circle_completion: ArrowRight,
  reindex_circle: RotateCcw,
}

const ACTION_LABEL_MAP = {
  pause: '暂停',
  resume: '恢复',
  cancel: '取消',
  retry_waiting: '立即重试',
  delete_waiting_retry: '移除等待重试',
  open_subtitle_import: '前往字幕补配',
  open_circle_completion: '前往社团补全',
  reindex_circle: '重新索引',
}

function actionIcon(action) {
  return ACTION_ICON_MAP[action] || Activity
}

function getActionLabel(action) {
  return ACTION_LABEL_MAP[action] || action
}

function actionToneClass(action) {
  if (action === 'cancel' || action === 'delete_waiting_retry') {
    return 'border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-300 hover:bg-rose-100 hover:shadow-[0_8px_18px_-8px_rgba(225,29,72,0.3)]'
  }
  if (action === 'pause') {
    return 'border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 hover:shadow-[0_8px_18px_-8px_rgba(217,119,6,0.3)]'
  }
  if (action === 'resume') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100 hover:shadow-[0_8px_18px_-8px_rgba(16,185,129,0.3)]'
  }
  if (action === 'retry_waiting' || action === 'reindex_circle') {
    return 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-100 hover:shadow-[0_8px_18px_-8px_rgba(79,70,229,0.3)]'
  }
  if (action === 'open_subtitle_import' || action === 'open_circle_completion') {
    return 'border-violet-200 bg-violet-50 text-violet-700 hover:border-violet-300 hover:bg-violet-100 hover:shadow-[0_8px_18px_-8px_rgba(124,58,237,0.3)]'
  }
  return 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
}
</script>

<style scoped>
.detail-fade-up {
  animation: detail-fade-up 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
@keyframes detail-fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.detail-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.detail-scroll::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 999px;
}
.detail-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.55);
}
</style>
