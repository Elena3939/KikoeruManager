<template>
  <component
    :is="immersive ? 'div' : 'el-card'"
    :shadow="immersive ? undefined : 'never'"
    :class="immersive ? 'grid min-w-0 gap-3' : 'subtitle-task-card'"
  >
    <template v-if="!immersive" #header>
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-2 text-[14px] font-semibold text-slate-900">
            <ListTodo class="h-4 w-4 text-indigo-500" :stroke-width="2.1" />
            <span>最近字幕任务</span>
          </div>
          <p class="mt-1 text-[12px] leading-relaxed text-slate-500">上面展示当前选中任务的详情，下面保留完整任务队列。运行中任务也会留在队列里，当前查看项会高亮。</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
            <CircleDot class="h-3 w-3 text-sky-500" :stroke-width="2.2" />总任务 {{ ctx.subtitleQueueTasks.length }}
          </span>
          <span class="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
            <Sparkles class="h-3 w-3 text-amber-500" :stroke-width="2.2" />可清理 {{ ctx.subtitleClearableTaskCounts.finished }}
          </span>
          <el-dropdown
            trigger="click"
            :disabled="!ctx.subtitleClearableTaskCounts.finished || Boolean(ctx.subtitleBulkClearingScope)"
            @command="ctx.clearSubtitleTasksByScope"
          >
            <button
              type="button"
              class="group inline-flex items-center gap-1.5 whitespace-nowrap rounded-[10px] border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-900 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:shadow-[0_4px_12px_rgba(15,23,42,0.08)] active:translate-y-0 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:scale-100"
              :disabled="!ctx.subtitleClearableTaskCounts.finished || Boolean(ctx.subtitleBulkClearingScope)"
            >
              <Trash2 class="h-3.5 w-3.5 text-rose-500 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]" :stroke-width="2.1" />
              <span>一键清空任务</span>
              <ChevronDown class="h-3 w-3 transition-transform duration-300 group-hover:translate-y-0.5" :stroke-width="2.2" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="completed" :disabled="!ctx.subtitleClearableTaskCounts.completed">清空成功 {{ ctx.subtitleClearableTaskCounts.completed }}</el-dropdown-item>
                <el-dropdown-item command="failed" :disabled="!ctx.subtitleClearableTaskCounts.failed">清空失败 {{ ctx.subtitleClearableTaskCounts.failed }}</el-dropdown-item>
                <el-dropdown-item command="finished" :disabled="!ctx.subtitleClearableTaskCounts.finished">清空全部已结束 {{ ctx.subtitleClearableTaskCounts.finished }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </template>

    <AppEmptyState v-if="showOverview && !ctx.visibleSubtitleTasks.length" description="暂无字幕任务" size="sm" />
    <div v-else class="grid min-w-0 gap-3">
      <!-- Active task log panel -->
      <div
        v-if="showOverview && ctx.activeSubtitleTask"
        :key="ctx.activeSubtitleTask.id"
        class="rounded-[16px] border border-slate-200/80 bg-white p-4 shadow-[0_2px_12px_rgba(15,23,42,0.04)]"
      >
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2.5 min-w-0">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[10px] border border-slate-200 bg-slate-900 text-white">
              <ScrollText class="h-4 w-4" :stroke-width="2.1" />
            </div>
            <div class="min-w-0">
              <div class="text-[13px] font-semibold text-slate-900">当前任务执行日志</div>
              <div class="mt-0.5 text-[11.5px] font-medium text-slate-500 truncate">{{ ctx.getTaskDisplayRJCode(ctx.activeSubtitleTask) }}</div>
            </div>
          </div>
          <span
            class="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium"
            :class="statusPillClass(ctx.getRJSubtitleTaskStatusClass(ctx.activeSubtitleTask))"
          >
            {{ ctx.getRJSubtitleTaskStatusLabel(ctx.activeSubtitleTask) }}
          </span>
        </div>

        <div class="mt-3 rounded-[12px] border border-slate-100 bg-gradient-to-b from-[#fafcff] to-white">
          <div
            v-if="shouldShowMetaPanel(ctx.activeSubtitleTask)"
            class="border-b border-slate-100 px-3 py-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-1.5 text-[12px] font-semibold text-slate-900">
                <History class="h-3.5 w-3.5 text-violet-500" :stroke-width="2.2" />
                <span>{{ getMetaPanelTitle(ctx.activeSubtitleTask) }}</span>
              </div>
              <div class="flex flex-wrap items-center justify-end gap-1">
                <span
                  v-for="chip in getTaskMetaChips(ctx.activeSubtitleTask)"
                  :key="`${ctx.activeSubtitleTask.id}-${chip.key}`"
                  class="inline-flex items-center gap-1 rounded-[8px] border px-2 py-0.5 text-[10.5px] font-medium"
                  :class="chip.class"
                >
                  <component :is="chip.icon" class="h-2.5 w-2.5" :stroke-width="2.3" />
                  <span>{{ chip.label }}</span>
                </span>
              </div>
            </div>

            <div class="mt-3 grid gap-2 md:grid-cols-2">
              <div
                v-for="item in getTaskMetaItems(ctx.activeSubtitleTask)"
                :key="`${ctx.activeSubtitleTask.id}-${item.key}`"
                class="rounded-[10px] border border-slate-200/80 bg-white/80 px-2.5 py-2 shadow-[0_1px_4px_rgba(15,23,42,0.03)]"
                :class="item.layout === 'full' ? 'md:col-span-2' : ''"
              >
                <div class="flex items-start gap-2">
                  <div class="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50">
                    <component :is="item.icon" class="h-3 w-3" :class="item.iconClass" :stroke-width="2.2" />
                  </div>
                  <div class="min-w-0">
                    <div class="text-[10.5px] font-medium uppercase tracking-[0.08em] text-slate-400">{{ item.label }}</div>
                    <div class="mt-0.5 break-words text-[11.5px] font-medium leading-relaxed text-slate-800">{{ item.value }}</div>
                    <div v-if="item.tip" class="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">{{ item.tip }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
            <div class="flex items-center gap-1.5 text-[12px] font-semibold text-slate-900">
              <Activity class="h-3.5 w-3.5 text-emerald-500" :stroke-width="2.2" />
              <span>执行日志</span>
            </div>
            <span class="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10.5px] font-medium text-slate-900">
              {{ ctx.activeSubtitleTask.progress_log?.length || 0 }} 条
            </span>
          </div>
          <div v-if="ctx.activeSubtitleTaskProgressLogs.length" class="subtitle-workbench-scrollbar max-h-[300px] overflow-auto px-3 py-3">
            <TransitionGroup tag="div" name="sub-log-item" class="task-log-stream">
              <div
                v-for="(entry, idx) in ctx.activeSubtitleTaskProgressLogs"
                :key="`${ctx.activeSubtitleTask.id}-progress-log-${idx}`"
                class="task-log-row"
              >
                <div class="task-log-time-wrap">
                  <span class="task-log-time">{{ ctx.formatProgressLogTime(entry.time) }}</span>
                  <span class="task-log-dot" :class="getTaskLogTone(entry).dot"></span>
                </div>
                <span
                  class="task-log-level"
                  :class="getTaskLogTone(entry).label"
                >
                  <component :is="getTaskLogBusinessIcon(entry)" class="h-3 w-3" :class="getTaskLogTone(entry).icon" :stroke-width="2.2" />
                  {{ getTaskLogBusinessLabel(entry) }}
                </span>
                <span class="task-log-message">{{ entry.message }}</span>
              </div>
            </TransitionGroup>
          </div>
          <div v-else class="px-3 py-2">
            <AppEmptyState :description="getTaskLogEmptyTitle(ctx.activeSubtitleTask)" size="sm">
              <template #default>
                <div class="mt-1 text-center text-[11px] leading-relaxed text-slate-500">
                  {{ getTaskLogEmptyDescription(ctx.activeSubtitleTask) }}
                </div>
              </template>
            </AppEmptyState>
          </div>
        </div>
      </div>

      <!-- Queue head (non-immersive) -->
      <div v-if="showQueue && !immersive" class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-900">
            <Layers class="h-3.5 w-3.5 text-indigo-500" :stroke-width="2.2" />
            <span>任务队列</span>
          </div>
          <p class="mt-1 text-[11.5px] leading-relaxed text-slate-500">包含正在处理中的任务和历史任务，当前查看项会高亮。</p>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <button
            v-for="item in ctx.subtitleTaskManualOverview"
            :key="`manual-${item.key}`"
            type="button"
            class="group inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] active:translate-y-0 active:scale-[0.96]"
            :class="ctx.subtitleTaskManualFilter === item.key
              ? 'border-slate-900 bg-slate-900 text-white shadow-[0_4px_12px_rgba(15,23,42,0.2)]'
              : 'border-slate-100 bg-white text-slate-900 hover:border-slate-300 hover:bg-slate-50'"
            @click="ctx.setSubtitleTaskManualFilter(item.key)"
          >
            <span>{{ item.label }}</span>
            <span
              class="inline-flex min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-semibold"
              :class="ctx.subtitleTaskManualFilter === item.key ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-900'"
            >{{ item.value }}</span>
          </button>
        </div>
      </div>

      <!-- Task rail -->
      <TransitionGroup
        v-if="showQueue && ctx.subtitleQueueTasks.length"
        tag="div"
        name="sub-rail-item"
        class="subtitle-task-rail grid auto-cols-[minmax(244px,288px)] grid-flow-col gap-2.5 overflow-x-auto px-1 pb-2 pt-1 -mx-1"
      >
        <button
          v-for="task in ctx.subtitleQueueTasks"
          :key="`queue-${task.id}`"
          :ref="el => registerRailRef(task.id, el)"
          type="button"
          class="group grid min-w-0 content-start gap-2 rounded-[14px] border bg-white p-3 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
          :class="[
            isTaskInteractionLocked(task)
              ? (ctx.isSubtitleTaskSelected(task)
                  ? 'cursor-not-allowed border-slate-300 bg-slate-100/95 opacity-75 shadow-[0_4px_14px_rgba(15,23,42,0.06)] ring-1 ring-slate-300/70'
                  : 'cursor-not-allowed border-slate-200 bg-slate-100/90 opacity-70 shadow-none')
              : ctx.isSubtitleTaskSelected(task)
              ? 'border-slate-900 bg-white shadow-[0_6px_20px_rgba(15,23,42,0.1)] ring-1 ring-slate-900/15'
              : task.manual_match_completed
                ? 'border-emerald-200/70 hover:border-emerald-300'
                : task.status === 'processing'
                  ? 'border-sky-200/70 hover:border-sky-300'
                  : 'border-slate-100 hover:border-slate-300'
          ]"
          :disabled="isTaskInteractionLocked(task)"
          @click="handleTaskClick(task)"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-1.5 min-w-0">
              <component
                :is="statusIcon(ctx.getRJSubtitleTaskStatusClass(task))"
                class="h-4 w-4 flex-shrink-0 transition-transform duration-300 group-hover:scale-110"
                :class="[statusIconColor(ctx.getRJSubtitleTaskStatusClass(task)), task.status === 'processing' ? 'animate-spin' : '']"
                :stroke-width="2.1"
              />
              <span class="text-[15px] font-semibold tracking-tight text-slate-900 truncate">{{ ctx.getTaskDisplayRJCode(task) }}</span>
            </div>
            <span
              class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium flex-shrink-0"
              :class="statusPillClass(ctx.getRJSubtitleTaskStatusClass(task))"
            >{{ ctx.getRJSubtitleTaskStatusLabel(task) }}</span>
          </div>

          <div class="flex items-start gap-1.5 text-[12px] text-slate-900 leading-relaxed">
            <Folder class="h-3 w-3 mt-0.5 flex-shrink-0 text-amber-500" :stroke-width="2.2" />
            <span class="break-words line-clamp-2">{{ getDisplayFolderName(task) }}</span>
          </div>

          <div class="rounded-lg bg-slate-50/60 px-2 py-1.5 text-[11.5px] leading-relaxed text-slate-500 line-clamp-2">
            {{ formatTaskStep(task.current_step || task.error_message || '等待中') }}
          </div>

          <div class="flex flex-wrap gap-1">
            <template v-if="ctx.isHistoryRestoredSubtitleTask(task) || ctx.isSelectionBackfillSubtitleTask(task)">
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <History class="h-2.5 w-2.5 text-violet-500" :stroke-width="2.4" />{{ ctx.isHistoryRestoredSubtitleTask(task) ? '历史恢复' : '结果回填' }}
              </span>
              <span v-if="task.manual_match_completed" class="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-medium text-emerald-700">
                <CheckCheck class="h-2.5 w-2.5" :stroke-width="2.4" />已匹配 {{ ctx.getSubtitleMatchedPairCount(task) || 0 }}
              </span>
              <span v-else-if="task.awaiting_manual_match" class="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-700">
                <Hand class="h-2.5 w-2.5" :stroke-width="2.4" />待配对
              </span>
              <span v-else class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-700">
                <ScrollText class="h-2.5 w-2.5 text-slate-500" :stroke-width="2.4" />结果回看
              </span>
              <span v-if="task.subtitle_dir" class="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10.5px] font-medium text-sky-700">
                <FolderOpen class="h-2.5 w-2.5" :stroke-width="2.4" />字幕树
              </span>
            </template>
            <template v-else>
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <Download class="h-2.5 w-2.5 text-sky-500" :stroke-width="2.4" />下载 {{ task.downloaded_count || ctx.getSubtitleDownloadFiles(task).length }}
              </span>
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <Link2 class="h-2.5 w-2.5 text-indigo-500" :stroke-width="2.4" />匹配 {{ ctx.getSubtitleMatchedPairCount(task) || 0 }}
              </span>
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <FileCheck class="h-2.5 w-2.5 text-emerald-500" :stroke-width="2.4" />写入 {{ ctx.getSubtitleAppliedWrittenFiles(task).length || 0 }}
              </span>
              <span v-if="isTaskInteractionLocked(task)" class="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-500">
                <Clock class="h-2.5 w-2.5" :stroke-width="2.4" />运行锁定
              </span>
              <span v-if="task.manual_match_completed" class="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-medium text-emerald-700">
                <CheckCheck class="h-2.5 w-2.5" :stroke-width="2.4" />完成 {{ ctx.getSubtitleMatchedPairCount(task) || 0 }}
              </span>
              <span v-else class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <CircleSlash class="h-2.5 w-2.5 text-rose-400" :stroke-width="2.4" />未配 {{ ctx.getSubtitleUnmatchedAudioCount(task) || 0 }}
              </span>
            </template>
          </div>

          <div class="flex min-h-[28px] items-center justify-between gap-2 pt-0.5">
            <div class="flex min-w-0 items-center gap-1 text-[11px] text-slate-900">
              <template v-if="ctx.getTaskSourceRJCode(task)">
                <Link2 class="h-3 w-3 flex-shrink-0 text-sky-500" :stroke-width="2.2" />
                <span class="truncate">来源 {{ ctx.getTaskSourceRJCode(task) }}</span>
              </template>
            </div>
            <span
              class="inline-flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
              :class="isTaskInteractionLocked(task)
                ? 'border-slate-200 bg-slate-100 text-slate-400 cursor-not-allowed'
                : task.subtitle_dir
                ? 'border-slate-200 bg-white text-slate-900 hover:border-slate-900 hover:bg-slate-900 hover:text-white hover:shadow-[0_4px_12px_rgba(15,23,42,0.2)] cursor-pointer'
                : 'border-slate-100 bg-slate-50/60 text-slate-300 cursor-not-allowed'"
              @click.stop="!isTaskInteractionLocked(task) && task.subtitle_dir && ctx.inspectSubtitleTask(task)"
            >
              <Eye class="h-3 w-3" :stroke-width="2.2" />
              <span>{{ ctx.getSubtitleTaskInspectLabel(task) }}</span>
            </span>
          </div>
        </button>
      </TransitionGroup>
    </div>
  </component>
</template>

<script setup>
import { computed, nextTick, watch } from 'vue'
import {
  Activity, CheckCheck, CheckCircle2, ChevronDown, CircleDot, CircleSlash,
  Clock, Download, Eye, FileCheck, FileDown, FileUp, Filter, Folder, FolderOpen, Hand, History,
  Layers, Link2, ListTodo, Loader2, Search, ScrollText, Sparkles, Trash2, Wand2, XCircle
} from 'lucide-vue-next'
import AppEmptyState from '../../common/AppEmptyState.vue'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: 'full'
  },
  immersive: {
    type: Boolean,
    default: false
  }
})

const showOverview = computed(() => ['full', 'overview'].includes(props.mode))
const showQueue = computed(() => ['full', 'queue'].includes(props.mode))
const subtitleTaskDetailPanels = computed(() => (
  Array.isArray(props.ctx?.subtitleTaskDetailPanels) ? props.ctx.subtitleTaskDetailPanels : []
))

const railRefs = new Map()
function registerRailRef(id, el) {
  if (el) railRefs.set(id, el)
  else railRefs.delete(id)
}

let scrollRafId = 0
function scrollRailToTask(id) {
  if (!id) return
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  scrollRafId = requestAnimationFrame(() => {
    scrollRafId = 0
    const el = railRefs.get(id)
    if (!el || !el.isConnected) return
    const container = el.closest('.subtitle-task-rail')
    if (!container) return
    const cRect = container.getBoundingClientRect()
    const eRect = el.getBoundingClientRect()
    const target = container.scrollLeft + (eRect.left - cRect.left) - (cRect.width - eRect.width) / 2
    container.scrollTo({ left: Math.max(0, target), behavior: 'smooth' })
  })
}

watch(
  () => props.ctx?.selectedSubtitleTaskId || props.ctx?.activeSubtitleTask?.id || '',
  (id) => {
    if (!id) return
    nextTick(() => scrollRailToTask(id))
  }
)

function statusPillClass(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return 'border border-emerald-200 bg-emerald-50 text-emerald-700'
  if (k === 'failed') return 'border border-rose-200 bg-rose-50 text-rose-700'
  if (['processing', 'awaiting_manual_match'].includes(k)) return 'border border-sky-200 bg-sky-50 text-sky-700'
  if (k === 'view_restored') return 'border border-violet-200 bg-violet-50 text-violet-700'
  if (k === 'view_backfilled') return 'border border-slate-200 bg-slate-50 text-slate-700'
  return 'border border-slate-200 bg-slate-50 text-slate-600'
}

function statusIcon(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return CheckCircle2
  if (k === 'failed') return XCircle
  if (k === 'processing') return Loader2
  if (k === 'awaiting_manual_match') return Hand
  if (k === 'view_restored') return History
  if (k === 'view_backfilled') return Layers
  return Clock
}

function statusIconColor(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return 'text-emerald-500'
  if (k === 'failed') return 'text-rose-500'
  if (['processing', 'awaiting_manual_match'].includes(k)) return 'text-sky-500'
  if (k === 'view_restored') return 'text-violet-500'
  if (k === 'view_backfilled') return 'text-slate-500'
  return 'text-slate-400'
}

function logLevelClass(level) {
  const k = String(level || 'info').toLowerCase()
  if (k === 'error') return 'border-rose-200 text-rose-700'
  if (k === 'warning' || k === 'warn') return 'border-amber-200 text-amber-700'
  if (k === 'success') return 'border-emerald-200 text-emerald-700'
  return 'border-slate-200 text-slate-600'
}

function isTaskInteractionLocked(task) {
  return Boolean(props.ctx?.isSubtitleTaskRerunLocked?.(task))
}

function handleTaskClick(task) {
  if (isTaskInteractionLocked(task)) return
  if (task.subtitle_dir) {
    props.ctx?.inspectSubtitleTask?.(task)
    return
  }
  props.ctx?.selectSubtitleTask?.(task)
}

function logLevelDotClass(level) {
  const k = String(level || 'info').toLowerCase()
  if (k === 'error') return 'bg-rose-500'
  if (k === 'warning' || k === 'warn') return 'bg-amber-500'
  if (k === 'success') return 'bg-emerald-500'
  return 'bg-sky-500'
}

function getTaskLogKind(entry = {}) {
  const message = String(entry?.message || '').trim()
  const level = String(entry?.level || 'info').toLowerCase()
  if (/下载字幕/.test(message)) return 'download'
  if (/上传字幕/.test(message)) return 'upload'
  if (/写入完成|原始字幕写入完成|确认导入目标目录/.test(message)) return 'write'
  if (/后处理|已应用\s*\d+\s*组配对|匹配完成/.test(message)) return 'postprocess'
  if (/发现字幕来源|来源/.test(message)) return 'source'
  if (/搜索|检索/.test(message)) return 'search'
  if (/整理字幕|准备匹配/.test(message)) return 'match'
  if (/过滤|跳过/.test(message)) return 'filter'
  if (level === 'success') return 'success'
  if (level === 'warning' || level === 'warn') return 'warning'
  if (level === 'error') return 'error'
  return 'progress'
}

function getTaskLogTone(entry = {}) {
  const kind = getTaskLogKind(entry)
  const tones = {
    download: { dot: 'bg-sky-500', icon: 'text-sky-600', label: 'border-sky-200 text-sky-700' },
    upload: { dot: 'bg-indigo-500', icon: 'text-indigo-600', label: 'border-indigo-200 text-indigo-700' },
    write: { dot: 'bg-emerald-500', icon: 'text-emerald-600', label: 'border-emerald-200 text-emerald-700' },
    postprocess: { dot: 'bg-teal-500', icon: 'text-teal-600', label: 'border-teal-200 text-teal-700' },
    source: { dot: 'bg-violet-500', icon: 'text-violet-600', label: 'border-violet-200 text-violet-700' },
    search: { dot: 'bg-blue-500', icon: 'text-blue-600', label: 'border-blue-200 text-blue-700' },
    match: { dot: 'bg-cyan-500', icon: 'text-cyan-600', label: 'border-cyan-200 text-cyan-700' },
    filter: { dot: 'bg-amber-500', icon: 'text-amber-600', label: 'border-amber-200 text-amber-700' },
    success: { dot: 'bg-emerald-500', icon: 'text-emerald-600', label: 'border-emerald-200 text-emerald-700' },
    warning: { dot: 'bg-amber-500', icon: 'text-amber-600', label: 'border-amber-200 text-amber-700' },
    error: { dot: 'bg-rose-500', icon: 'text-rose-600', label: 'border-rose-200 text-rose-700' },
    progress: { dot: 'bg-slate-400', icon: 'text-slate-500', label: 'border-slate-200 text-slate-600' }
  }
  return tones[kind] || tones.progress
}

function getTaskLogBusinessIcon(entry = {}) {
  const kind = getTaskLogKind(entry)
  if (kind === 'download') return FileDown
  if (kind === 'upload') return FileUp
  if (kind === 'write') return FileCheck
  if (kind === 'postprocess') return Wand2
  if (kind === 'source') return Link2
  if (kind === 'search') return Search
  if (kind === 'match') return Link2
  if (kind === 'filter') return Filter
  if (kind === 'success') return CheckCircle2
  if (kind === 'warning') return CircleSlash
  if (kind === 'error') return XCircle
  return Activity
}

function getTaskLogBusinessLabel(entry = {}) {
  const labels = {
    download: '下载字幕',
    upload: '上传字幕',
    write: '写入完成',
    postprocess: '后处理',
    source: '来源确认',
    search: '来源搜索',
    match: '整理匹配',
    filter: '筛选过滤',
    success: '完成',
    warning: '注意',
    error: '错误',
    progress: '任务进度'
  }
  return labels[getTaskLogKind(entry)] || labels.progress
}

function getDisplayFolderName(task) {
  const folderName = String(task?.folder_name || '').trim().replace(/[\\/]+$/, '')
  if (folderName) {
    const parts = folderName.split(/[\\/]/).filter(Boolean)
    return parts[parts.length - 1] || folderName
  }
  return props.ctx?.getFileName?.(task?.folder_path) || '-'
}

function getSourceModeLabel(mode) {
  const normalized = String(mode || '').trim().toLowerCase()
  const labels = {
    linked_translation_archive_import: '关联字幕压缩包导入',
    subtitle_folder_import: '字幕目录导入',
    activity_history_restore: '操作记录恢复',
    subtitle_workbench_scan: '字幕工作台扫描'
  }
  if (labels[normalized]) return labels[normalized]
  return normalized ? normalized.replace(/[_-]+/g, ' / ') : ''
}

function getQueueStateLabel(queueState) {
  switch (String(queueState || '').trim()) {
    case 'awaiting_manual_match':
      return '待继续配对'
    case 'manual_match_completed':
      return '已匹配完成'
    case 'existing_task':
      return '任务已存在'
    case 'queued':
      return '已入任务'
    case 'create_failed':
      return '加入失败'
    default:
      return ''
  }
}

function formatMetaTime(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const date = new Date(text)
  if (Number.isNaN(date.getTime())) return text
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatTaskDuration(task) {
  if (!task) return ''
  const parseTime = (value) => {
    const ts = Date.parse(String(value || '').trim())
    return Number.isFinite(ts) ? ts : 0
  }
  const start = parseTime(task.started_at || task.activity_context?.started_at || task.created_at || task.restored_at || task.activity_context?.created_at)
  const end = parseTime(task.completed_at || task.activity_context?.completed_at)
  if (!start) return ''
  const diff = Math.max(0, (end || Date.now()) - start)
  const totalSeconds = Math.floor(diff / 1000)
  if (!totalSeconds) return end ? '0秒' : ''
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}时${minutes}分${seconds}秒`
  if (minutes > 0) return `${minutes}分${seconds}秒`
  return `${seconds}秒`
}

function getTaskMetaSourceLabel(task) {
  return String(
    task?.source_label
    || task?.task_metadata?.source_label
    || task?.activity_context?.source_label
    || task?.restore_payload?.source_label
    || task?.snapshot?.source_label
    || ''
  ).trim()
}

function formatTaskStep(value) {
  return String(value || '').replace(/^后处理完成，?/, '') || '等待中'
}

function getTaskMetaPrimaryMessage(task) {
  return String(
    task?.snapshot?.queue_message
    || task?.activity_context?.summary
    || task?.activity_context?.message
    || task?.restore_payload?.message
    || task?.current_step
    || ''
  ).trim()
}

function getTaskLogEmptyTitle(task) {
  if (props.ctx?.isHistoryRestoredSubtitleTask?.(task)) return '这是一份恢复快照'
  if (props.ctx?.isSelectionBackfillSubtitleTask?.(task)) return '这是一份回填快照'
  return '当前任务还没有日志'
}

function getTaskLogEmptyDescription(task) {
  if (props.ctx?.isHistoryRestoredSubtitleTask?.(task)) {
    return '当前展示的是从操作记录恢复出来的历史上下文，没有实时进度日志并不代表这条任务从未执行过。'
  }
  if (props.ctx?.isSelectionBackfillSubtitleTask?.(task)) {
    return '当前展示的是扫描命中回填结果，日志要等实时任务状态同步回来后才会继续补齐。'
  }
  return '当前任务还没有产生可展示的执行日志。'
}

function shouldShowMetaPanel(task) {
  return Boolean(
    task &&
    subtitleTaskDetailPanels.value.includes('meta') &&
    (props.ctx?.isHistoryRestoredSubtitleTask?.(task) || props.ctx?.isSelectionBackfillSubtitleTask?.(task))
  )
}

function getMetaPanelTitle(task) {
  if (props.ctx?.isHistoryRestoredSubtitleTask?.(task)) return '恢复任务上下文'
  if (props.ctx?.isSelectionBackfillSubtitleTask?.(task)) return '回填任务上下文'
  return '任务上下文'
}

function getTaskMetaChips(task) {
  const chips = []
  if (props.ctx?.isHistoryRestoredSubtitleTask?.(task)) {
    chips.push({
      key: 'mode',
      label: '操作记录恢复',
      icon: History,
      class: 'border-violet-200 bg-violet-50 text-violet-700'
    })
  } else if (props.ctx?.isSelectionBackfillSubtitleTask?.(task)) {
    chips.push({
      key: 'mode',
      label: '扫描命中回填',
      icon: Layers,
      class: 'border-slate-200 bg-slate-50 text-slate-700'
    })
  }
  if (task?.manual_match_completed) {
    chips.push({
      key: 'manual-done',
      label: `已匹配 ${props.ctx?.getSubtitleMatchedPairCount?.(task) || 0}`,
      icon: CheckCircle2,
      class: 'border-emerald-200 bg-emerald-50 text-emerald-700'
    })
  } else if (task?.awaiting_manual_match) {
    chips.push({
      key: 'manual-wait',
      label: '待继续配对',
      icon: Hand,
      class: 'border-amber-200 bg-amber-50 text-amber-700'
    })
  }
  if (task?.subtitle_dir) {
    chips.push({
      key: 'tree',
      label: '可查看字幕树',
      icon: FolderOpen,
      class: 'border-sky-200 bg-sky-50 text-sky-700'
    })
  }
  return chips
}

function getTaskMetaItems(task) {
  if (!task) return []
  const items = []
  const queueState = String(task?.snapshot?.queue_state || '').trim()
  const queueLabel = getQueueStateLabel(queueState)
  const sourceLabel = getTaskMetaSourceLabel(task)
  const sourceModeLabel = getSourceModeLabel(task?.source_mode)
  const libraryLabel = props.ctx?.getLibraryLabelById?.(task?.library_id || task?.subtitle_library_id || '')
  const createdAt = formatMetaTime(task?.restored_at || task?.activity_context?.restored_at || task?.activity_context?.created_at || task?.restore_payload?.restored_at || task?.created_at)
  const durationText = formatTaskDuration(task)
  const currentMessage = getTaskMetaPrimaryMessage(task)

  if (sourceLabel) {
    items.push({
      key: 'source-label',
      label: '来源动作',
      value: sourceLabel,
      tip: '优先使用任务快照或恢复记录里自带的来源标签。',
      icon: Link2,
      iconClass: 'text-sky-500'
    })
  }

  if (sourceModeLabel) {
    items.push({
      key: 'source-mode',
      label: '来源模式',
      value: sourceModeLabel,
      icon: Layers,
      iconClass: 'text-indigo-500'
    })
  }

  if (libraryLabel) {
    items.push({
      key: 'library',
      label: '来源库',
      value: libraryLabel,
      icon: CircleDot,
      iconClass: 'text-slate-500'
    })
  }

  if (queueLabel || currentMessage) {
    items.push({
      key: 'snapshot-state',
      label: '快照状态',
      value: queueLabel || currentMessage,
      tip: queueLabel && currentMessage && queueLabel !== currentMessage ? currentMessage : '',
      icon: ScrollText,
      iconClass: 'text-violet-500'
    })
  }

  if (createdAt) {
    items.push({
      key: 'created-at',
      label: '记录时间',
      value: createdAt,
      icon: Clock,
      iconClass: 'text-amber-500'
    })
  }

  if (durationText) {
    items.push({
      key: 'duration',
      label: '处理时间',
      value: durationText,
      icon: Activity,
      iconClass: 'text-emerald-500'
    })
  }

  if (task?.folder_path) {
    items.push({
      key: 'folder-path',
      label: '作品目录',
      value: String(task.folder_path),
      icon: Folder,
      iconClass: 'text-amber-500',
      layout: 'full'
    })
  }

  if (task?.subtitle_dir) {
    items.push({
      key: 'subtitle-dir',
      label: '字幕目录',
      value: String(task.subtitle_dir),
      icon: FolderOpen,
      iconClass: 'text-sky-500',
      layout: 'full'
    })
  }

  return items
}
</script>

<style scoped>
.subtitle-task-card {
  display: grid;
  gap: 12px;
  min-width: 0;
  border-radius: 14px;
  border: 1px solid rgb(226 232 240 / 0.8);
  background: #fff;
}

.subtitle-task-card :deep(.el-card__header) {
  padding: 14px 16px;
  border-bottom: 1px solid rgb(226 232 240 / 0.8);
}

.subtitle-task-card :deep(.el-card__body) {
  display: grid;
  gap: 12px;
  padding: 14px 16px;
}

/* Horizontal rail item transitions */
.sub-rail-item-enter-active,
.sub-rail-item-leave-active {
  transition: all 0.38s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.sub-rail-item-enter-from {
  opacity: 0;
  transform: translateY(12px) scale(0.95);
}
.sub-rail-item-leave-to {
  opacity: 0;
  transform: translateX(-12px) scale(0.95);
}
.sub-rail-item-move {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Log item transitions */
.task-log-stream {
  position: relative;
  display: grid;
  gap: 0;
}

.task-log-stream::before {
  content: '';
  position: absolute;
  left: 76px;
  top: 10px;
  bottom: 10px;
  width: 1px;
  background: #e2e8f0;
}

.task-log-row {
  position: relative;
  display: grid;
  grid-template-columns: 96px 74px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 7px 0;
  font-size: 12px;
  line-height: 1.55;
}

.task-log-time-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding-right: 14px;
}

.task-log-time {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.task-log-dot {
  position: relative;
  z-index: 1;
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
  box-shadow: 0 0 0 3px #ffffff;
}

.task-log-level {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border-radius: 7px;
  border: 1px solid;
  background: #ffffff;
  padding: 0 8px;
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
}

.task-log-level svg {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.task-log-row:hover .task-log-level svg {
  transform: rotate(-8deg) scale(1.12);
}

.task-log-message {
  min-width: 0;
  border-radius: 9px;
  background: #ffffff;
  color: #1e293b;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.55;
  word-break: break-word;
}

.sub-log-item-enter-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.sub-log-item-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.sub-log-item-move {
  transition: transform 0.3s ease;
}

.subtitle-task-rail::-webkit-scrollbar {
  height: 6px;
}

.subtitle-task-rail::-webkit-scrollbar-track {
  background: transparent;
}

.subtitle-task-rail::-webkit-scrollbar-thumb {
  background: rgb(203 213 225);
  border-radius: 9999px;
}

.subtitle-task-rail::-webkit-scrollbar-thumb:hover {
  background: rgb(148 163 184);
}

.subtitle-task-rail > button {
  cursor: pointer;
}
</style>
