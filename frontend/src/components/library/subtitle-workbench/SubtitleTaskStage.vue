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
          <div class="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
            <div class="flex items-center gap-1.5 text-[12px] font-semibold text-slate-900">
              <Activity class="h-3.5 w-3.5 text-emerald-500" :stroke-width="2.2" />
              <span>执行日志</span>
            </div>
            <span class="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10.5px] font-medium text-slate-900">
              {{ ctx.activeSubtitleTask.progress_log?.length || 0 }} 条
            </span>
          </div>
          <div v-if="ctx.activeSubtitleTaskProgressLogs.length" class="max-h-[260px] overflow-auto px-3 py-2">
            <TransitionGroup tag="div" name="sub-log-item" class="grid gap-1.5">
              <div
                v-for="(entry, idx) in ctx.activeSubtitleTaskProgressLogs"
                :key="`${ctx.activeSubtitleTask.id}-progress-log-${idx}`"
                class="grid grid-cols-[110px_80px_minmax(0,1fr)] items-start gap-2 text-[12px] leading-relaxed"
              >
                <span class="font-mono text-[11px] text-slate-400">{{ ctx.formatProgressLogTime(entry.time) }}</span>
                <span
                  class="inline-flex items-center justify-center rounded-md px-1.5 py-0.5 text-[10.5px] font-medium"
                  :class="logLevelClass(entry.level)"
                >{{ ctx.getProgressLogLevelLabel(entry.level) }}</span>
                <span class="font-medium text-slate-800 break-words">{{ entry.message }}</span>
              </div>
            </TransitionGroup>
          </div>
          <div v-else class="px-3 py-6 text-center text-[12px] text-slate-400">当前任务还没有日志</div>
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
          type="button"
          class="group grid min-w-0 content-start gap-2 rounded-[14px] border bg-white p-3 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01] hover:shadow-[0_8px_20px_rgba(15,23,42,0.08)] active:translate-y-0 active:scale-[0.98]"
          :class="[
            ctx.isSubtitleTaskSelected(task)
              ? 'border-slate-900 bg-white shadow-[0_6px_20px_rgba(15,23,42,0.1)] ring-1 ring-slate-900/15'
              : task.manual_match_completed
                ? 'border-emerald-200/70 hover:border-emerald-300'
                : task.status === 'processing'
                  ? 'border-sky-200/70 hover:border-sky-300'
                  : 'border-slate-100 hover:border-slate-300'
          ]"
          @click="ctx.selectSubtitleTask(task)"
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
            <span class="break-words line-clamp-2">{{ task.folder_name || ctx.getFileName(task.folder_path) }}</span>
          </div>

          <div v-if="ctx.getTaskSourceRJCode(task)" class="flex items-center gap-1 text-[11px] text-slate-900">
            <Link2 class="h-3 w-3 text-sky-500" :stroke-width="2.2" />
            <span>来源 {{ ctx.getTaskSourceRJCode(task) }}</span>
          </div>

          <div class="rounded-lg bg-slate-50/60 px-2 py-1.5 text-[11.5px] leading-relaxed text-slate-500 line-clamp-2">
            {{ task.current_step || task.error_message || '等待中' }}
          </div>

          <div class="flex flex-wrap gap-1">
            <template v-if="ctx.isHistoryRestoredSubtitleTask(task)">
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <History class="h-2.5 w-2.5 text-violet-500" :stroke-width="2.4" />历史恢复
              </span>
              <span v-if="task.manual_match_completed" class="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-medium text-emerald-700">
                <CheckCheck class="h-2.5 w-2.5" :stroke-width="2.4" />已匹配 {{ task.manual_match_applied_pairs || 0 }}
              </span>
              <span v-else-if="task.awaiting_manual_match" class="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-700">
                <Hand class="h-2.5 w-2.5" :stroke-width="2.4" />待配对
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
                <Link2 class="h-2.5 w-2.5 text-indigo-500" :stroke-width="2.4" />匹配 {{ task.match_result?.matched_group_count || 0 }}
              </span>
              <span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <FileCheck class="h-2.5 w-2.5 text-emerald-500" :stroke-width="2.4" />写入 {{ task.written_files?.length || 0 }}
              </span>
              <span v-if="task.manual_match_completed" class="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-medium text-emerald-700">
                <CheckCheck class="h-2.5 w-2.5" :stroke-width="2.4" />完成 {{ task.manual_match_applied_pairs || 0 }}
              </span>
              <span v-else class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-900">
                <CircleSlash class="h-2.5 w-2.5 text-rose-400" :stroke-width="2.4" />未配 {{ task.match_result?.unmatched_audio?.length || 0 }}
              </span>
            </template>
          </div>

          <div class="flex justify-end pt-0.5">
            <span
              class="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
              :class="task.subtitle_dir
                ? 'border-slate-200 bg-white text-slate-900 hover:border-slate-900 hover:bg-slate-900 hover:text-white hover:shadow-[0_4px_12px_rgba(15,23,42,0.2)] cursor-pointer'
                : 'border-slate-100 bg-slate-50/60 text-slate-300 cursor-not-allowed'"
              @click.stop="task.subtitle_dir && ctx.inspectSubtitleTask(task)"
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
import { computed } from 'vue'
import {
  Activity, CheckCheck, CheckCircle2, ChevronDown, CircleDot, CircleSlash,
  Clock, Download, Eye, FileCheck, Folder, FolderOpen, Hand, History,
  Layers, Link2, ListTodo, Loader2, ScrollText, Sparkles, Trash2, XCircle
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

function statusPillClass(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return 'border border-emerald-200 bg-emerald-50 text-emerald-700'
  if (k === 'failed') return 'border border-rose-200 bg-rose-50 text-rose-700'
  if (['processing', 'awaiting_manual_match'].includes(k)) return 'border border-sky-200 bg-sky-50 text-sky-700'
  return 'border border-slate-200 bg-slate-50 text-slate-600'
}

function statusIcon(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return CheckCircle2
  if (k === 'failed') return XCircle
  if (k === 'processing') return Loader2
  if (k === 'awaiting_manual_match') return Hand
  return Clock
}

function statusIconColor(key) {
  const k = String(key || '').toLowerCase()
  if (['completed', 'manual_match_completed'].includes(k)) return 'text-emerald-500'
  if (k === 'failed') return 'text-rose-500'
  if (['processing', 'awaiting_manual_match'].includes(k)) return 'text-sky-500'
  return 'text-slate-400'
}

function logLevelClass(level) {
  const k = String(level || 'info').toLowerCase()
  if (k === 'error') return 'bg-rose-50 text-rose-700 border border-rose-200'
  if (k === 'warning' || k === 'warn') return 'bg-amber-50 text-amber-700 border border-amber-200'
  if (k === 'success') return 'bg-emerald-50 text-emerald-700 border border-emerald-200'
  return 'bg-slate-100 text-slate-600 border border-slate-200'
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
</style>
