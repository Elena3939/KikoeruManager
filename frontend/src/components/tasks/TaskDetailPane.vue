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

      <!-- 本次处理：轻量业务摘要 -->
      <section v-if="item.metrics?.length" class="border-b border-slate-200 px-4 pt-3.5 pb-3.5">
        <span class="mb-2.5 flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
          <span class="h-1 w-1 rounded-full bg-amber-500" />
          本次处理
        </span>
        <div class="task-metrics-strip">
          <div
            v-for="(metric, mIndex) in item.metrics"
            :key="`${item.id}-${metric.label}`"
            class="detail-fade-up task-metric-item"
            :class="getMetricItemClass(metric)"
            :style="{ animationDelay: `${mIndex * 30}ms` }"
          >
            <span class="task-metric-label">{{ getMetricLabel(metric.label) }}</span>
            <span
              class="task-metric-value"
              :class="isCompactMetric(metric) ? 'tabular-nums' : ''"
              :title="String(metric.value || '')"
            >
              {{ getMetricValue(metric) }}
            </span>
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
        <div class="mb-2.5 flex flex-col gap-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
              <span class="h-1 w-1 rounded-full bg-emerald-500" />
              {{ section.label }}
            </span>
            <el-radio-group
              :model-value="treeFilterMode"
              size="small"
              class="task-tree-filter"
              @change="$emit('update:treeFilterMode', $event)"
            >
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="added">新增</el-radio-button>
              <el-radio-button label="removed">移除</el-radio-button>
            </el-radio-group>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap gap-1.5">
              <span v-if="section.totalCount" class="inline-flex h-6 items-center rounded-md border border-slate-200 bg-white px-2 text-[10.5px] font-bold tabular-nums text-slate-700">文件 {{ section.totalCount }}</span>
              <span v-if="section.addedCount" class="inline-flex h-6 items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 text-[10.5px] font-bold tabular-nums text-emerald-700">
                <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" /> 新增 {{ section.addedCount }}
              </span>
              <span v-if="section.removedCount" class="inline-flex h-6 items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 text-[10.5px] font-bold tabular-nums text-rose-700">
                <span class="h-1.5 w-1.5 rounded-full bg-rose-500" /> 移除 {{ section.removedCount }}
              </span>
            </div>
            <el-button class="task-tree-toggle" size="small" @click="$emit('expand-section', section, !section.allExpanded)">
              <component
                :is="section.allExpanded ? ChevronRight : ChevronDown"
                :size="12"
                :stroke-width="2.4"
                class="task-tree-toggle__icon"
              />
              <span>{{ section.allExpanded ? '收起全部' : '展开全部' }}</span>
            </el-button>
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

const METRIC_LABEL_MAP = {
  RJ: 'RJ 号',
  输出: '作品目录',
  此前失败: '失败次数',
  问题作品: '问题记录',
  目标库: '目标库存',
  下载: '下载字幕',
  写入: '写入字幕',
  来源字幕: '候选字幕',
  可执行候选: '可配对目录',
  候选目录: '候选目录',
  下载文件: '下载文件',
  失败文件: '失败文件',
  已上传: '已上传',
  上传大小: '上传大小',
  平均上传: '平均速度',
  耗时: '耗时',
  DLsite: 'DLsite 作品',
  可下载: '可下载',
  本地: '本地已有',
  缺失: '服务器缺失',
}

function getMetricLabel(label) {
  const raw = String(label || '').trim()
  return METRIC_LABEL_MAP[raw] || raw || '指标'
}

function getMetricValue(metric) {
  const label = String(metric?.label || '').trim()
  const value = String(metric?.value ?? '').trim()
  if (!value) return '—'
  if (label === '此前失败' && !value.includes('次')) return `${value} 次`
  if (label === '问题作品' && /^\d+$/.test(value)) return `${value} 条`
  return value
}

function isCompactMetric(metric) {
  const label = String(metric?.label || '').trim()
  const value = String(metric?.value ?? '').trim()
  return label === 'RJ' || /^[\d.]+\s*[\w%次条]*$/i.test(value) || value.length <= 12
}

function getMetricItemClass(metric) {
  return isCompactMetric(metric) ? 'task-metric-item--compact' : 'task-metric-item--wide'
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

.task-metrics-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  background: #fff;
}

.task-metric-item {
  position: relative;
  min-width: 0;
  padding: 9px 12px 9px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
  background: linear-gradient(90deg, rgba(248, 250, 252, 0.9), #fff);
}

.task-metric-item::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: #f59e0b;
  content: '';
}

.task-metric-item:last-child {
  border-bottom: 0;
}

.task-metric-label {
  display: block;
  color: #64748b;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1.2;
}

.task-metric-value {
  display: block;
  min-width: 0;
  margin-top: 3px;
  overflow: hidden;
  color: #0f172a;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-tree-filter,
.task-tree-toggle {
  font-family: inherit;
}

.task-tree-filter {
  overflow: hidden;
  padding: 3px;
  border: 1px solid #dbe3ee;
  border-radius: 11px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(248, 250, 252, 0.95));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 6px 16px rgba(15, 23, 42, 0.04);
}

.task-tree-filter :deep(.el-radio-button__inner) {
  height: 28px;
  padding: 0 12px;
  border: 0;
  border-radius: 8px !important;
  background: transparent;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  line-height: 28px;
  box-shadow: none !important;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-filter :deep(.el-radio-button__inner:hover) {
  transform: translateY(-1px) scale(1.02);
  background: rgba(255, 255, 255, 0.92);
  color: #0f172a;
}

.task-tree-filter :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #0f172a;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.22) !important;
  color: #fff;
}

.task-tree-filter :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner:hover) {
  transform: translateY(-1px) scale(1.02);
  background: #0f172a;
  color: #fff;
}

.task-tree-toggle {
  height: 32px;
  padding: 0 13px !important;
  border-color: #bbf7d0 !important;
  border-radius: 11px !important;
  background:
    radial-gradient(circle at top left, rgba(220, 252, 231, 0.95), rgba(255, 255, 255, 0.98) 68%) !important;
  color: #047857 !important;
  font-size: 11px;
  font-weight: 800;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 8px 18px rgba(16, 185, 129, 0.1);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-toggle :deep(span) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.task-tree-toggle:hover {
  transform: translateY(-2px) scale(1.03);
  border-color: #34d399 !important;
  background: linear-gradient(180deg, #ecfdf5, #fff) !important;
  box-shadow: 0 12px 22px rgba(16, 185, 129, 0.16);
}

.task-tree-toggle:active {
  transform: scale(0.96);
}

.task-tree-toggle__icon {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-toggle:hover .task-tree-toggle__icon {
  transform: rotate(-12deg) scale(1.12);
}

@media (min-width: 640px) {
  .task-metrics-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-metric-item {
    border-right: 1px solid rgba(226, 232, 240, 0.8);
  }

  .task-metric-item:nth-child(2n) {
    border-right: 0;
  }

  .task-metric-item--wide {
    grid-column: span 2;
  }
}

@media (min-width: 1280px) {
  .task-metrics-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .task-metric-item:nth-child(2n) {
    border-right: 1px solid rgba(226, 232, 240, 0.8);
  }

  .task-metric-item:nth-child(3n) {
    border-right: 0;
  }

  .task-metric-item--wide {
    grid-column: span 2;
  }
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
