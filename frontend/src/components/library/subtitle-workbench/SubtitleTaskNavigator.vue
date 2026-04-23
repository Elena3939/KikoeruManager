<template>
  <div ref="rootRef" class="grid h-full gap-3.5">
    <div class="flex items-start justify-between gap-3 max-[1280px]:flex-col max-[1280px]:items-stretch">
      <div class="min-w-0">
        <div class="flex items-center gap-1.5 text-[14px] font-semibold tracking-[-0.015em] text-slate-900">
          <ListTodo class="h-3.5 w-3.5 text-indigo-500" :stroke-width="2.2" />
          <span>执行队列</span>
        </div>
        <div class="mt-1 max-w-[24ch] text-[11px] leading-relaxed text-slate-500">
          活跃任务会自动置顶，点击任意卡片可直达中央工位。
        </div>
      </div>

      <div class="relative">
        <button
          type="button"
          class="group inline-flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[10px] border border-slate-200 bg-white px-2.5 text-[11.5px] font-medium text-slate-900 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:shadow-[0_6px_14px_rgba(15,23,42,0.08)] active:translate-y-0 active:scale-[0.96]"
          :aria-expanded="clearMenuOpen"
          aria-haspopup="menu"
          @click="clearMenuOpen = !clearMenuOpen"
        >
          <Trash2 class="h-3 w-3 text-rose-500 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:rotate-[-6deg]" :stroke-width="2.2" />
          <span>批量清理</span>
          <ChevronDown class="h-3 w-3 transition-transform duration-200" :class="{ 'rotate-180': clearMenuOpen }" :stroke-width="2.2" />
        </button>

        <div
          v-if="clearMenuOpen"
          class="absolute right-0 top-[calc(100%+8px)] z-20 w-48 rounded-[14px] border border-slate-200 bg-white p-1.5 shadow-[0_16px_40px_rgba(15,23,42,0.14)]"
        >
          <button
            v-for="item in clearActions"
            :key="item.key"
            type="button"
            class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[11.5px] font-medium text-slate-900 transition-all duration-200 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45"
            :disabled="!item.count"
            @click="handleClear(item.key)"
          >
            <span>{{ item.label }}</span>
            <span class="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold text-slate-900">{{ item.count }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="overflow-hidden rounded-[12px] border border-slate-100 bg-white">
      <button
        v-for="(item, idx) in ctx.subtitleTaskManualOverview"
        :key="item.key"
        type="button"
        class="group relative flex w-full items-center gap-2.5 px-3 py-2 text-left transition-all duration-200 ease-out hover:bg-slate-50/80"
        :class="[
          idx > 0 ? 'border-t border-slate-100' : '',
          ctx.subtitleTaskManualFilter === item.key ? 'bg-slate-50' : ''
        ]"
        @click="ctx.setSubtitleTaskManualFilter(item.key)"
      >
        <span
          class="absolute left-0 top-1/2 h-[18px] w-[3px] -translate-y-1/2 rounded-r-full transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
          :class="ctx.subtitleTaskManualFilter === item.key ? 'bg-slate-900 opacity-100' : 'bg-slate-900 opacity-0 group-hover:opacity-30'"
        ></span>
        <span
          class="h-1.5 w-1.5 flex-shrink-0 rounded-full transition-all duration-200"
          :class="statDotClass(item.key)"
        ></span>
        <span
          class="flex-1 text-[11.5px] text-slate-900 transition-colors duration-200"
          :class="ctx.subtitleTaskManualFilter === item.key ? 'font-semibold' : 'font-medium'"
        >{{ item.label }}</span>
        <span
          class="tabular-nums text-[13px] leading-none transition-colors duration-200"
          :class="ctx.subtitleTaskManualFilter === item.key
            ? 'font-bold text-slate-900'
            : item.value > 0 ? 'font-semibold text-slate-900' : 'font-medium text-slate-300'"
        >{{ item.value }}</span>
      </button>
    </div>

    <AppEmptyState v-if="!ctx.subtitleQueueTasks.length" description="暂无字幕任务" size="sm" />

    <TransitionGroup v-else tag="div" name="sub-task-item" class="grid content-start gap-2">
      <button
        v-for="task in pagedTasks"
        :key="task.id"
        type="button"
        class="group grid w-full gap-1.5 rounded-[14px] border bg-white px-3 py-2.5 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01] hover:shadow-[0_10px_22px_rgba(79,70,229,0.12)] active:translate-y-0 active:scale-[0.98]"
        :class="getCardClass(task)"
        @click="ctx.selectSubtitleTask(task)"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="text-[13.5px] font-semibold tracking-[-0.02em] text-slate-900 truncate">{{ ctx.getTaskDisplayRJCode(task) }}</span>

          <Transition name="subtitle-status-flip" mode="out-in">
            <span
              :key="`${task.id}-${getTaskStatusKey(task)}`"
              class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
              :class="getStatusClass(task)"
            >
              <component :is="getStatusIcon(task)" class="h-2.5 w-2.5" :class="{ 'animate-spin': getTaskStatusKey(task) === 'processing' }" :stroke-width="2.4" />
              {{ getStatusLabel(task) }}
            </span>
          </Transition>
        </div>

        <div class="flex items-start gap-1 break-all text-[11px] font-medium leading-snug text-slate-900">
          <Folder class="mt-0.5 h-2.5 w-2.5 flex-shrink-0 text-amber-500" :stroke-width="2.4" />
          <span class="line-clamp-2">{{ task.folder_name || ctx.getFileName(task.folder_path) }}</span>
        </div>

        <div class="rounded-md bg-slate-50/80 px-1.5 py-1 text-[10.5px] leading-snug text-slate-500 line-clamp-2">
          {{ getCurrentStep(task) }}
        </div>

        <div class="flex flex-wrap gap-1 text-[9.5px]">
          <span class="inline-flex items-center gap-0.5 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-medium text-slate-900">
            <Download class="h-2.5 w-2.5 text-sky-500" :stroke-width="2.4" />
            下载 {{ task.downloaded_count || ctx.getSubtitleDownloadFiles(task).length }}
          </span>
          <span class="inline-flex items-center gap-0.5 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-medium text-slate-900">
            <FilePenLine class="h-2.5 w-2.5 text-emerald-500" :stroke-width="2.4" />
            写入 {{ task.written_files?.length || 0 }}
          </span>
          <span
            v-if="task.manual_match_completed"
            class="inline-flex items-center gap-0.5 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700"
          >
            <CheckCheck class="h-2.5 w-2.5" :stroke-width="2.4" />
            已匹配 {{ task.manual_match_applied_pairs || 0 }}
          </span>
          <span
            v-else-if="task.awaiting_manual_match || task.status === 'awaiting_manual_match' || task.status === 'waiting_manual'"
            class="inline-flex items-center gap-0.5 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-medium text-amber-700"
          >
            <Link2 class="h-2.5 w-2.5" :stroke-width="2.4" />
            待配对
          </span>
        </div>
      </button>
    </TransitionGroup>

    <div v-if="totalPages > 1" class="flex items-center justify-between gap-2 px-0.5 pt-1">
      <button
        type="button"
        class="group inline-flex min-h-7 items-center gap-1 rounded-[8px] border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-slate-900 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 active:translate-y-0 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
        :disabled="currentPage <= 1"
        @click="currentPage -= 1"
      >
        <ChevronLeft class="h-3 w-3 transition-transform duration-300 group-hover:-translate-x-0.5" :stroke-width="2.2" />
        上一页
      </button>
      <span class="rounded-[8px] border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-900">
        {{ currentPage }} / {{ totalPages }}
      </span>
      <button
        type="button"
        class="group inline-flex min-h-7 items-center gap-1 rounded-[8px] border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-slate-900 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 active:translate-y-0 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
        :disabled="currentPage >= totalPages"
        @click="currentPage += 1"
      >
        下一页
        <ChevronRight class="h-3 w-3 transition-transform duration-300 group-hover:translate-x-0.5" :stroke-width="2.2" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CheckCheck, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  Clock, Download, FilePenLine, Folder, Link2, ListTodo,
  Loader2, Trash2, XCircle
} from 'lucide-vue-next'
import AppEmptyState from '../../common/AppEmptyState.vue'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  }
})

const PAGE_SIZE = 6
const currentPage = ref(1)
const clearMenuOpen = ref(false)
const rootRef = ref(null)

const clearActions = computed(() => [
  { key: 'completed', label: '清理成功', count: props.ctx?.subtitleClearableTaskCounts?.completed || 0 },
  { key: 'failed', label: '清理失败', count: props.ctx?.subtitleClearableTaskCounts?.failed || 0 },
  { key: 'finished', label: '清理全部已结束', count: props.ctx?.subtitleClearableTaskCounts?.finished || 0 }
])

const totalPages = computed(() => Math.max(1, Math.ceil((props.ctx?.subtitleQueueTasks?.length || 0) / PAGE_SIZE)))
const pagedTasks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return (props.ctx?.subtitleQueueTasks || []).slice(start, start + PAGE_SIZE)
})

watch(() => props.ctx?.subtitleTaskManualFilter, () => {
  currentPage.value = 1
})

watch(() => props.ctx?.subtitleQueueTasks?.length, () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
})

function handleClear(scope) {
  clearMenuOpen.value = false
  props.ctx?.clearSubtitleTasksByScope?.(scope)
}

function handleDocumentClick(event) {
  if (!clearMenuOpen.value || !rootRef.value) return
  if (!rootRef.value.contains(event.target)) {
    clearMenuOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
})

function getTaskStatusKey(task) {
  return props.ctx?.getRJSubtitleTaskStatusClass?.(task) || task?.status || 'pending'
}

function getStatusLabel(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || ['completed', 'manual_match_completed'].includes(status)) return '已匹配完成'
  if (['processing'].includes(status)) return '执行中'
  if (['awaiting_manual_match', 'waiting_manual'].includes(status)) return '待手动配对'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return '待处理'
}

function getStatusClass(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || ['completed', 'manual_match_completed'].includes(status)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 [animation:subtitleStatusGlow_1.6s_ease-in-out_infinite]'
  }
  if (['processing', 'awaiting_manual_match', 'waiting_manual'].includes(status)) {
    return 'border-sky-200 bg-sky-50 text-sky-700 [animation:subtitleStatusPulse_1.4s_ease-in-out_infinite]'
  }
  if (status === 'failed') return 'border-rose-200 bg-rose-50 text-rose-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function getStatusIcon(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || ['completed', 'manual_match_completed'].includes(status)) return CheckCircle2
  if (status === 'processing') return Loader2
  if (['awaiting_manual_match', 'waiting_manual'].includes(status)) return Link2
  if (status === 'failed') return XCircle
  return Clock
}

function getCardClass(task) {
  const status = getTaskStatusKey(task)
  if (props.ctx?.isSubtitleTaskSelected?.(task)) {
    return 'border-slate-900 bg-white shadow-[0_6px_20px_rgba(15,23,42,0.1)] ring-1 ring-slate-900/15'
  }
  if (task?.manual_match_completed || ['completed', 'manual_match_completed'].includes(status)) {
    return 'border-emerald-200/70 hover:border-emerald-300'
  }
  if (status === 'processing') {
    return 'border-sky-200/70 hover:border-sky-300'
  }
  if (status === 'failed') {
    return 'border-rose-200/70 hover:border-rose-300'
  }
  return 'border-slate-100 hover:border-slate-300'
}

function statDotClass(key) {
  const k = String(key || '').toLowerCase()
  if (k === 'all' || k === 'total') return 'bg-slate-700'
  if (k === 'pending' || k === 'waiting' || k === 'waiting_manual' || k === 'awaiting_manual_match') return 'bg-amber-400'
  if (k === 'processing') return 'bg-sky-500'
  if (k === 'completed' || k === 'matched' || k === 'manual_match_completed') return 'bg-emerald-500'
  if (k === 'failed') return 'bg-rose-500'
  return 'bg-slate-300'
}

function getCurrentStep(task) {
  return task?.current_step || task?.error_message || '等待中'
}
</script>

<style scoped>
.subtitle-status-flip-enter-active,
.subtitle-status-flip-leave-active {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease;
}

.subtitle-status-flip-enter-from,
.subtitle-status-flip-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.92);
}

/* List item transitions */
.sub-task-item-enter-active,
.sub-task-item-leave-active {
  transition: all 0.38s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.sub-task-item-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}
.sub-task-item-leave-to {
  opacity: 0;
  transform: translateX(-16px) scale(0.96);
}
.sub-task-item-move {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes subtitleStatusPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(14, 165, 233, 0.12);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(14, 165, 233, 0);
  }
}

@keyframes subtitleStatusGlow {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.12);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(16, 185, 129, 0);
  }
}
</style>
