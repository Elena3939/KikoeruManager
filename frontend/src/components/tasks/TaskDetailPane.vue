<template>
  <div class="flex min-h-0 flex-col overflow-auto rounded-[14px] border border-slate-200/90 bg-white shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] detail-scroll">
    <header class="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-100 bg-white/95 px-4 py-3 backdrop-blur">
      <span class="text-[13px] font-bold tracking-tight text-slate-900">任务详情</span>
      <button
        v-if="item?.route_hint"
        type="button"
        class="group inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-[10px] border border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 transition-all duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-400 hover:bg-slate-50 hover:text-slate-900 active:scale-95"
        @click="$emit('open-route', item)"
      >
        <ArrowRight :size="13" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-0.5" />
        <span>打开关联页面</span>
      </button>
    </header>

    <template v-if="item">
      <div v-if="detailLoading" class="flex items-center gap-2 px-4 pt-3 text-[12px] text-slate-500">
        <RefreshCw :size="13" :stroke-width="2.3" class="animate-spin" />
        <span>正在读取完整任务详情...</span>
      </div>

      <!-- Hero：纯色图标无背景框，和任务列表卡片呼应 -->
      <div class="flex items-start gap-3 px-5 pt-4 pb-3">
        <component
          :is="taskIcon(item)"
          :size="22"
          :stroke-width="2"
          class="mt-[3px] flex-shrink-0 transition-transform duration-300 hover:scale-110 hover:rotate-[-4deg]"
          :class="taskIconClass(item)"
        />
        <div class="flex-1 min-w-0">
          <div class="flex items-start justify-between gap-2.5">
            <h2 class="m-0 text-[17px] font-bold tracking-tight text-slate-900 leading-tight">{{ item.title }}</h2>
            <StatusPill :status="statusForPill(item)" :label="statusLabelForPill(item)" />
          </div>
          <p v-if="item.subtitle" class="m-0 mt-1 text-[12.5px] leading-snug text-slate-500">{{ item.subtitle }}</p>
          <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
            <span
              class="task-domain-chip inline-flex h-[20px] items-center rounded-full px-2 text-[11px] font-semibold"
              :class="[domainMeta(item.domain).chipBg, domainMeta(item.domain).chipText]"
            >{{ taskDomainLabel(item) }}</span>
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
          v-if="item.error_message && !isCancelledTask(item)"
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

        <div
          v-if="getGarbledDiagnostic(item)"
          class="mt-3 rounded-[12px] border border-amber-200 bg-white p-3 shadow-[0_8px_18px_-12px_rgba(217,119,6,0.28)]"
        >
          <div class="flex items-start gap-2">
            <AlertTriangle :size="15" :stroke-width="2.4" class="mt-0.5 flex-shrink-0 text-amber-600" />
            <div class="min-w-0 flex-1">
              <div class="text-[12px] font-bold text-slate-900">文件名乱码诊断</div>
              <p class="mt-1 text-[11.5px] leading-relaxed text-slate-600">
                {{ buildGarbledSummary(getGarbledDiagnostic(item)) }}
              </p>
              <div class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div class="rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-2">
                  <span class="block text-slate-400">样本</span>
                  <b class="mt-0.5 block break-all text-slate-800">{{ getGarbledDiagnostic(item).sample || '—' }}</b>
                </div>
                <div class="rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-2">
                  <span class="block text-slate-400">评分</span>
                  <b class="mt-0.5 block text-slate-800">
                    {{ getGarbledDiagnostic(item).scoreBefore }} → {{ getGarbledDiagnostic(item).scoreAfter }}
                  </b>
                </div>
                <div class="rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-2">
                  <span class="block text-slate-400">修复 / 编码尝试</span>
                  <b class="mt-0.5 block text-slate-800">
                    {{ getGarbledDiagnostic(item).repairedCount }} / {{ getGarbledDiagnostic(item).codecPairsTried }}
                  </b>
                </div>
                <div class="rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-2">
                  <span class="block text-slate-400">触发位置</span>
                  <b class="mt-0.5 block text-slate-800">{{ getGarbledDiagnostic(item).origin || '—' }}</b>
                </div>
              </div>
              <div v-if="getGarbledDiagnostic(item).topSamples.length" class="mt-2 max-h-[142px] overflow-y-auto rounded-[10px] border border-slate-100 detail-scroll">
                <div
                  v-for="entry in getGarbledDiagnostic(item).topSamples"
                  :key="`${entry.name}-${entry.score}`"
                  class="grid grid-cols-[1fr_48px] gap-2 border-b border-slate-100 px-2.5 py-2 text-[11px] last:border-b-0"
                >
                  <div class="min-w-0">
                    <div class="break-all font-semibold text-slate-700">{{ entry.name }}</div>
                    <div v-if="entry.markers?.length" class="mt-1 flex flex-wrap gap-1">
                      <span
                        v-for="marker in entry.markers"
                        :key="`${entry.name}-${marker}`"
                        class="rounded bg-amber-50 px-1.5 py-0.5 font-mono text-[10px] font-bold text-amber-700"
                      >{{ marker }}</span>
                    </div>
                  </div>
                  <b class="text-right tabular-nums text-amber-700">{{ entry.score }}</b>
                </div>
              </div>
            </div>
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
        <div class="mb-2.5 flex flex-col gap-2.5">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <span class="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[0.06em] text-slate-500">
              <span class="h-1 w-1 rounded-full bg-emerald-500" />
              {{ section.label }}
            </span>
            <div v-if="section.removedCount > 0" class="task-tree-actions">
              <button
                v-for="option in treeFilterOptions"
                :key="option.value"
                type="button"
                class="task-tree-filter-button"
                :class="{ 'task-tree-filter-button--active': treeFilterMode === option.value }"
                @click="$emit('update:treeFilterMode', option.value)"
              >
                <component :is="option.icon" :size="12" :stroke-width="2.4" class="task-tree-filter-button__icon" />
                <span>{{ option.label }}</span>
              </button>
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap gap-1.5">
              <span v-if="section.totalCount" class="inline-flex h-6 items-center rounded-md border border-slate-200 bg-white px-2 text-[10.5px] font-bold tabular-nums text-slate-700">文件 {{ section.totalCount }}</span>
              <span v-if="section.removedCount" class="inline-flex h-6 items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 text-[10.5px] font-bold tabular-nums text-rose-700">
                <span class="h-1.5 w-1.5 rounded-full bg-rose-500" />
                已删除 {{ section.directRemovedCount || section.removedCount }}
                <span v-if="section.removedCount > (section.directRemovedCount || section.removedCount)" class="text-rose-500/75">影响 {{ section.removedCount }}</span>
              </span>
            </div>
            <button type="button" class="task-tree-toggle" @click="$emit('expand-section', section, !section.allExpanded)">
              <component
                :is="section.allExpanded ? ChevronRight : ChevronDown"
                :size="12"
                :stroke-width="2.4"
                class="task-tree-toggle__icon"
              />
              <span>{{ section.allExpanded ? '收起文件树' : '展开文件树' }}</span>
            </button>
          </div>
        </div>

        <div class="task-file-tree-card">
          <div class="task-file-tree detail-scroll">
            <div
              v-for="entry in section.rows"
              :key="`${item.id}-${section.key}-${entry.key}`"
              class="task-file-tree-row tree-row"
              :class="{ 'tree-row-filtered': entry.status === 'removed' }"
              :style="{ paddingLeft: `${entry.depth * 16 + 8}px` }"
            >
              <div class="tree-main">
                <button
                  v-if="entry.hasChildren"
                  type="button"
                  class="tree-expander"
                  @click="$emit('toggle-node', entry.key, entry.defaultExpanded)"
                >
                  <component :is="entry.expanded ? ChevronDown : ChevronRight" :size="17" :stroke-width="2.3" />
                </button>
                <span v-else class="expander-spacer" />

                <span class="tree-main-target" :class="{ 'tree-main-target-filtered': entry.status === 'removed' }">
                  <component :is="getTreeRowIconComponent(entry)" :size="20" class="tree-icon" :class="getTreeRowIconClass(entry)" />

                  <span class="tree-name">
                    <span class="tree-label-text">{{ entry.label }}</span>
                    <span v-if="entry.status === 'removed'" class="tree-removed-badge">
                      {{ entry.removedByDirectory ? '随目录删除' : '已删除' }}
                    </span>
                  </span>
                </span>
              </div>
              <span v-if="entry.sizeText" class="tree-size">{{ entry.sizeText }}</span>
            </div>
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

    <!-- 空态：移动端 wrapper padding 收紧（平板/桌面保留宽松 padding） -->
    <div v-else class="flex flex-1 items-center justify-center px-3 py-4 md:px-6 md:py-12">
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
  FolderOpen,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Trash2,
  XCircle,
  Activity,
  ListFilter,
} from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatusPill from '../dashboard/StatusPill.vue'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'
import { getHttpDownloadDisplayMeta } from '../common/httpDownloadPlatformMeta.js'
import { classifyLibraryEntryKind, libraryEntryIconFor } from '../library/_libraryFileKind.js'

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

function getTreeRowIconComponent(entry) {
  if (isTreeDirectory(entry) && entry?.expanded) return FolderOpen
  return libraryEntryIconFor(normalizeTreeRowForFileKind(entry))
}

function getTreeRowIconClass(entry) {
  const kind = classifyLibraryEntryKind(normalizeTreeRowForFileKind(entry))
  return kind === 'dir' ? 'icon-folder' : `icon-${kind}`
}

function normalizeTreeRowForFileKind(entry) {
  const name = entry?.label || entry?.name || entry?.relative_path || entry?.path || ''
  if (isTreeDirectory(entry)) {
    return {
      type: 'dir',
      name,
    }
  }
  return {
    type: entry?.type,
    name,
  }
}

function isTreeDirectory(entry) {
  if (!entry) return false
  const type = String(entry.type || entry.entry_type || '').toLowerCase()
  if (type === 'dir' || type === 'directory') return true
  if (entry.is_directory === true) return true
  return Boolean(entry.hasChildren)
}

function getGarbledDiagnostic(item) {
  const metadata = item?.details?.metadata || item?.metadata || {}
  const sample = metadata.garbled_filename_sample || ''
  const topSamples = Array.isArray(metadata.garbled_filename_top_samples)
    ? metadata.garbled_filename_top_samples
    : []
  if (!sample && !topSamples.length) return null
  return {
    sample,
    scoreBefore: Number(metadata.garbled_filename_score_before ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    scoreAfter: Number(metadata.garbled_filename_score_after ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    repairedCount: Number(metadata.garbled_filename_repaired_count || 0),
    codecPairsTried: Number(metadata.garbled_filename_codec_pairs_tried || 0),
    origin: metadata.garbled_filename_guard_origin || '',
    totalNames: Number(metadata.garbled_filename_total_names || 0),
    garbledCount: Number(metadata.garbled_filename_garbled_count || 0),
    // surrogate 修复指标：repaired = 已经反解为合法 UTF-8（强信号）；
    // escaped = 反解失败、用 \udcXX 字面量保命，需要在编码下拉里手动确认。
    surrogateRepairedCount: Number(metadata.garbled_filename_surrogate_repaired_count || 0),
    surrogateEscapedCount: Number(metadata.garbled_filename_surrogate_escaped_count || 0),
    topSamples,
  }
}

function buildGarbledSummary(info) {
  const total = info.totalNames ? `，扫描 ${info.totalNames} 个文件名` : ''
  const count = info.garbledCount ? `，命中 ${info.garbledCount} 个高风险名称` : ''
  const surrogateBits = []
  if (info.surrogateRepairedCount) surrogateBits.push(`自动反解 ${info.surrogateRepairedCount} 个非 UTF-8 文件名`)
  if (info.surrogateEscapedCount) surrogateBits.push(`字面转义 ${info.surrogateEscapedCount} 个`)
  const surrogateText = surrogateBits.length ? `；本次${surrogateBits.join('、')}。` : ''
  return `7zz 已完成解压，但文件名评分达到 ${info.scoreAfter}（阈值 >= 30）${total}${count}。系统已尝试常见编码反解，仍认为存在乱码风险${surrogateText}`
}

const treeFilterOptions = [
  { value: 'all', label: '显示全部', icon: ListFilter },
  { value: 'removed', label: '只看已删除', icon: XCircle },
]

const ACTION_ICON_MAP = {
  pause: PauseCircle,
  resume: PlayCircle,
  cancel: XCircle,
  retry: RotateCcw,
  retry_waiting: RotateCcw,
  delete: Trash2,
  delete_waiting_retry: Trash2,
  open_subtitle_import: ArrowRight,
  open_circle_completion: ArrowRight,
  reindex_circle: RotateCcw,
}

const ACTION_LABEL_MAP = {
  pause: '暂停',
  resume: '恢复',
  cancel: '取消',
  delete: '删除',
  retry: '重试',
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
  if (action === 'cancel' || action === 'delete' || action === 'delete_waiting_retry') {
    return 'border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-300 hover:bg-rose-100 hover:shadow-[0_8px_18px_-8px_rgba(225,29,72,0.3)]'
  }
  if (action === 'pause') {
    return 'border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 hover:shadow-[0_8px_18px_-8px_rgba(217,119,6,0.3)]'
  }
  if (action === 'resume') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100 hover:shadow-[0_8px_18px_-8px_rgba(16,185,129,0.3)]'
  }
  if (action === 'retry' || action === 'retry_waiting' || action === 'reindex_circle') {
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

.task-tree-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.task-tree-filter-button {
  display: inline-flex;
  height: 30px;
  cursor: pointer;
  align-items: center;
  gap: 5px;
  border: 1px solid #dbe3ee;
  border-radius: 9px;
  background: #ffffff;
  padding: 0 11px;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-filter-button:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  box-shadow: 0 5px 12px -10px rgba(15, 23, 42, 0.22);
}

.task-tree-filter-button:active {
  transform: scale(0.96);
}

.task-tree-filter-button--active {
  border-color: #94a3b8;
  background: #f1f5f9;
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.04);
}

.task-tree-filter-button--active:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.task-tree-filter-button__icon {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-filter-button:hover .task-tree-filter-button__icon {
  transform: rotate(-10deg) scale(1.12);
}

.task-tree-toggle {
  display: inline-flex;
  height: 32px;
  cursor: pointer;
  align-items: center;
  gap: 6px;
  padding: 0 13px;
  border: 1px solid #dbe3ee;
  border-radius: 9px;
  background: #ffffff;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-tree-toggle:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  box-shadow: 0 5px 12px -10px rgba(15, 23, 42, 0.22);
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

.task-file-tree-card {
  position: relative;
  overflow: visible;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  box-shadow:
    0 10px 28px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
}

.task-file-tree-card::before,
.task-file-tree-card::after {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 2;
  height: 18px;
  pointer-events: none;
  content: '';
}

.task-file-tree-card::before {
  top: 0;
  background: linear-gradient(180deg, #ffffff 0%, rgba(255, 255, 255, 0));
}

.task-file-tree-card::after {
  bottom: 0;
  background: linear-gradient(0deg, #ffffff 0%, rgba(255, 255, 255, 0));
}

.task-file-tree {
  overflow: visible;
  padding: 10px 12px;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.65) transparent;
}

.tree-row {
  position: relative;
  display: flex;
  min-height: 32px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 7px;
  padding: 6px 10px 6px 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: rgb(30, 41, 59);
  cursor: default;
  transition: background-color 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}

.tree-row:last-child {
  margin-bottom: 0;
}

.tree-row:hover {
  background: rgba(248, 250, 252, 0.72);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.84);
}

.tree-row-filtered {
  border-color: transparent;
  background: transparent;
  color: #64748b;
  opacity: 0.74;
  box-shadow: none;
}

.tree-row-filtered:hover {
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}

.tree-main {
  position: relative;
  z-index: 1;
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 8px;
}

.tree-main-target {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.tree-main-target-filtered::after {
  content: none;
}

.tree-expander,
.expander-spacer {
  width: 20px;
  flex: 0 0 20px;
}

.tree-expander {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #38bdf8;
  cursor: pointer;
  padding: 2px;
  transition: background-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.tree-expander:hover {
  transform: scale(1.08);
  background: rgba(224, 242, 254, 0.76);
  color: #0284c7;
}

.tree-icon {
  flex: 0 0 auto;
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
  width: 22px;
  height: 22px;
  object-fit: contain;
  border-radius: 4px;
  filter: none;
  opacity: 1;
}

.icon-folder {
  color: #f6b73c;
  fill: rgba(251, 191, 36, 0.22);
}

.icon-audio-lossless {
  color: #2563eb;
}

.icon-audio {
  color: #7c3aed;
}

.icon-image {
  color: #f97316;
}

.icon-video {
  color: #6366f1;
}

.icon-pdf {
  color: #dc2626;
}

.icon-archive {
  color: #d97706;
}

.icon-text {
  color: #64748b;
}

.icon-file {
  color: #94a3b8;
}

.tree-row-filtered .tree-icon {
  color: #94a3b8;
  fill: rgba(148, 163, 184, 0.14);
  stroke: #94a3b8;
  opacity: 0.72;
  filter: grayscale(1);
}

.tree-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  color: currentColor;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-label-text {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tree-row-filtered .tree-name {
  color: #64748b;
}

.tree-row-filtered .tree-label-text {
  text-decoration: line-through;
  text-decoration-color: rgba(148, 163, 184, 0.86);
  text-decoration-thickness: 1.5px;
}

.tree-removed-badge {
  display: inline-flex;
  flex: 0 0 auto;
  height: 18px;
  align-items: center;
  padding: 0 6px;
  border: 1px solid rgba(148, 163, 184, 0.34);
  border-radius: 5px;
  background: rgba(226, 232, 240, 0.66);
  color: #64748b;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  vertical-align: 1px;
}

.tree-size {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  min-width: 72px;
  margin-left: 16px;
  color: rgb(148, 163, 184);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.tree-row-filtered .tree-size {
  color: #94a3b8;
  opacity: 0.78;
  text-decoration: line-through;
  text-decoration-color: rgba(148, 163, 184, 0.72);
  text-decoration-thickness: 1.2px;
}

@keyframes detail-fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.detail-scroll::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.detail-scroll::-webkit-scrollbar-thumb {
  border: 2px solid rgba(255, 255, 255, 0.9);
  background: rgba(148, 163, 184, 0.52);
  border-radius: 999px;
}
.detail-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.68);
}
.detail-scroll::-webkit-scrollbar-track {
  background: transparent;
}

:global(html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll) {
  background: #08090c !important;
  background-color: #08090c !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .tasks-main > .detail-scroll > header) {
  background: #101012 !important;
  background-color: #101012 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll section),
:global(html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll .mx-4) {
  background: transparent !important;
  background-color: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .tasks-main > .detail-scroll > section),
:global(html.kikoerumanager-dark body #app .tasks-page .tasks-main > .detail-scroll > .mx-4) {
  background: transparent !important;
  background-color: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .tasks-main > .detail-scroll :is(.bg-white, .bg-white\/95, .bg-slate-50, .bg-slate-100)) {
  background: #101012 !important;
  background-color: #101012 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll code),
:global(html.kikoerumanager-dark .tasks-page .task-file-tree-card),
:global(html.kikoerumanager-dark .tasks-page .task-file-tree) {
  background: #05060a !important;
  background-color: #05060a !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-folder) {
  color: #fbbf24 !important;
  fill: rgba(251, 191, 36, 0.22) !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-audio-lossless) {
  color: #60a5fa !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-audio) {
  color: #a78bfa !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-image) {
  color: #fb923c !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-video) {
  color: #818cf8 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-pdf) {
  color: #f87171 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-archive) {
  color: #f59e0b !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-text) {
  color: #94a3b8 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-icon.icon-file) {
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered) {
  border-color: transparent !important;
  background: transparent !important;
  color: #94a3b8 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered:hover) {
  border-color: transparent !important;
  background: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered .tree-icon) {
  color: #94a3b8 !important;
  fill: rgba(148, 163, 184, 0.12) !important;
  stroke: #94a3b8 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered .tree-name),
:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered .tree-size) {
  color: #94a3b8 !important;
}

:global(html.kikoerumanager-dark body #app .tasks-page .task-file-tree .tree-row-filtered .tree-removed-badge) {
  border-color: rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.72);
  color: #cbd5e1;
}
</style>
