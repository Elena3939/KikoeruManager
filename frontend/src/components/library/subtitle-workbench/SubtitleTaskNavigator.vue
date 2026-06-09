<template>
  <div
    ref="rootRef"
    class="subtitle-task-navigator grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-2.5"
  >
    <div class="subtitle-queue-header flex items-center justify-between gap-2">
      <div class="min-w-0">
        <div class="flex min-w-0 items-center gap-1.5 text-[14px] font-semibold tracking-[-0.015em] text-slate-900">
          <ListTodo class="h-3.5 w-3.5 text-violet-500" :stroke-width="2.2" />
          <span class="truncate">执行队列</span>
        </div>
      </div>

      <div class="subtitle-clear-menu-wrap">
        <button
          type="button"
          class="subtitle-clear-trigger group"
          :aria-expanded="clearMenuOpen"
          aria-haspopup="menu"
          title="批量清理任务"
          @click="clearMenuOpen = !clearMenuOpen"
        >
          <Trash2 class="subtitle-clear-trigger-icon" :stroke-width="2.2" />
          <span>清理</span>
          <ChevronDown class="subtitle-clear-trigger-chev" :class="{ 'rotate-180': clearMenuOpen }" :stroke-width="2.2" />
        </button>

        <div
          v-if="clearMenuOpen"
          class="subtitle-clear-menu-panel"
          role="menu"
        >
          <button
            v-for="item in clearActions"
            :key="item.key"
            type="button"
            class="subtitle-clear-menu-item"
            :disabled="!item.count"
            role="menuitem"
            @click="handleClear(item.key)"
          >
            <span>{{ item.label }}</span>
            <span class="subtitle-clear-menu-count">{{ item.count }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="subtitle-queue-overview">
      <button
        v-for="(item, idx) in ctx.subtitleTaskManualOverview"
        :key="item.key"
        type="button"
        class="subtitle-queue-filter group"
        :class="{ 'is-active': ctx.subtitleTaskManualFilter === item.key }"
        :aria-pressed="ctx.subtitleTaskManualFilter === item.key"
        @click="ctx.setSubtitleTaskManualFilter(item.key)"
      >
        <span
          class="subtitle-queue-active-mark"
          :class="{ 'is-active': ctx.subtitleTaskManualFilter === item.key }"
        ></span>
        <span
          class="subtitle-queue-dot"
          :class="statDotClass(item.key)"
        ></span>
        <span
          class="subtitle-queue-label"
        >{{ item.label }}</span>
        <span
          class="subtitle-queue-count"
          :class="{ 'is-active': ctx.subtitleTaskManualFilter === item.key, 'has-value': item.value > 0 }"
        >{{ item.value }}</span>
      </button>
    </div>

    <div class="subtitle-queue-body">
      <AppLoadingAnimation
        v-if="ctx.subtitleQueueLoading"
        label="加载任务队列"
        description="正在同步字幕补配状态"
        :size="82"
        :min-height="260"
        class="subtitle-queue-loading"
      />

      <AppEmptyState v-else-if="!visibleTasks.length" :description="ctx.subtitleQueueTasks.length ? '当前筛选暂无任务' : '暂无字幕任务'" size="sm" />

      <TransitionGroup v-else tag="div" name="sub-task-item" class="grid min-h-0 content-start gap-2 overflow-hidden">
        <button
          v-for="task in pagedTasks"
          :key="task.id"
          :ref="el => registerTaskRef(task.id, el)"
          type="button"
          class="group grid w-full gap-1.5 rounded-[12px] border bg-white px-2.5 py-2 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
          :class="getCardClass(task)"
          :disabled="isTaskInteractionLocked(task)"
          @click="handleTaskClick(task)"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="subtitle-task-title text-[12.5px] font-semibold tracking-[-0.02em] text-slate-900">{{ ctx.getTaskDisplayRJCode(task) }}</span>

            <Transition name="subtitle-status-flip" mode="out-in">
              <span
                :key="`${task.id}-${getTaskStatusKey(task)}`"
                class="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] font-medium whitespace-nowrap transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
                :class="getStatusClass(task)"
              >
                <component :is="getStatusIcon(task)" class="h-2.5 w-2.5" :class="{ 'animate-spin': getTaskStatusKey(task) === 'processing' }" :stroke-width="2.4" />
                {{ getStatusLabel(task) }}
              </span>
            </Transition>
          </div>

          <div class="flex items-start gap-1 text-[10.5px] font-medium leading-tight text-slate-900">
            <Folder class="mt-px h-2.5 w-2.5 flex-shrink-0 text-amber-500" :stroke-width="2.4" />
            <span class="subtitle-task-folder-name min-w-0 flex-1">{{ getDisplayFolderName(task) }}</span>
          </div>

          <div class="subtitle-task-step rounded-md bg-slate-50/80 px-1.5 py-1 text-[10px] leading-snug text-slate-500">
            {{ getCurrentStep(task) }}
          </div>

          <div class="flex flex-wrap gap-1 text-[9px]">
            <template v-if="ctx.isHistoryRestoredSubtitleTask?.(task) || ctx.isSelectionBackfillSubtitleTask?.(task)">
              <span class="inline-flex items-center gap-0.5 rounded border border-slate-200 bg-slate-50 px-1 py-0.5 font-medium text-slate-700">
                <Clock class="h-2 w-2 text-violet-500" :stroke-width="2.4" />
                {{ ctx.isHistoryRestoredSubtitleTask?.(task) ? '历史恢复' : '结果回填' }}
              </span>
              <span
                v-if="task.manual_match_completed"
                class="inline-flex items-center gap-0.5 rounded border border-emerald-200 bg-emerald-50 px-1 py-0.5 font-medium text-emerald-700"
              >
                <CheckCheck class="h-2 w-2" :stroke-width="2.4" />
                已匹配 {{ ctx.getSubtitleMatchedPairCount?.(task) || 0 }}
              </span>
              <span
                v-else-if="task.awaiting_manual_match || task.status === 'awaiting_manual_match' || task.status === 'waiting_manual'"
                class="inline-flex items-center gap-0.5 rounded border border-amber-200 bg-amber-50 px-1 py-0.5 font-medium text-amber-700"
              >
                <Link2 class="h-2 w-2" :stroke-width="2.4" />
                待配对
              </span>
              <span
                v-else
                class="inline-flex items-center gap-0.5 rounded border border-slate-200 bg-slate-50 px-1 py-0.5 font-medium text-slate-700"
              >
                <Folder class="h-2 w-2 text-sky-500" :stroke-width="2.4" />
                结果回看
              </span>
            </template>
            <template v-else>
            <span class="inline-flex items-center gap-0.5 rounded border border-slate-200 bg-slate-50 px-1 py-0.5 font-medium text-slate-900">
              <Download class="h-2 w-2 text-sky-500" :stroke-width="2.4" />
              下载 {{ task.downloaded_count || ctx.getSubtitleDownloadFiles(task).length }}
            </span>
            <span class="inline-flex items-center gap-0.5 rounded border border-slate-200 bg-slate-50 px-1 py-0.5 font-medium text-slate-900">
              <FilePenLine class="h-2 w-2 text-emerald-500" :stroke-width="2.4" />
              写入 {{ ctx.getSubtitleAppliedWrittenFiles?.(task).length || 0 }}
            </span>
            <span
              v-if="task.manual_match_completed"
              class="inline-flex items-center gap-0.5 rounded border border-emerald-200 bg-emerald-50 px-1 py-0.5 font-medium text-emerald-700"
            >
              <CheckCheck class="h-2 w-2" :stroke-width="2.4" />
              已匹配 {{ ctx.getSubtitleMatchedPairCount?.(task) || 0 }}
            </span>
            <span
              v-if="isTaskInteractionLocked(task)"
              class="inline-flex items-center gap-0.5 rounded border border-slate-300 bg-slate-100 px-1 py-0.5 font-medium text-slate-500"
            >
              <Clock class="h-2 w-2" :stroke-width="2.4" />
              运行锁定
            </span>
            <span
              v-else-if="task.awaiting_manual_match || task.status === 'awaiting_manual_match' || task.status === 'waiting_manual'"
              class="inline-flex items-center gap-0.5 rounded border border-amber-200 bg-amber-50 px-1 py-0.5 font-medium text-amber-700"
            >
              <Link2 class="h-2 w-2" :stroke-width="2.4" />
              待配对
            </span>
            </template>
          </div>
        </button>
      </TransitionGroup>
    </div>

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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CheckCheck, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  Clock, Download, FilePenLine, Folder, Link2, ListTodo,
  Loader2, Trash2, XCircle
} from 'lucide-vue-next'
import AppEmptyState from '../../common/AppEmptyState.vue'
import AppLoadingAnimation from '../../common/AppLoadingAnimation.vue'

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
  { key: 'all', label: '清理全部任务', count: props.ctx?.subtitleClearableTaskCounts?.all || 0 },
  { key: 'completed', label: '清理成功', count: props.ctx?.subtitleClearableTaskCounts?.completed || 0 },
  { key: 'failed', label: '清理失败', count: props.ctx?.subtitleClearableTaskCounts?.failed || 0 },
  { key: 'finished', label: '清理全部已结束', count: props.ctx?.subtitleClearableTaskCounts?.finished || 0 }
])

const visibleTasks = computed(() => props.ctx?.visibleSubtitleTasks || props.ctx?.subtitleQueueTasks || [])
const totalPages = computed(() => Math.max(1, Math.ceil(visibleTasks.value.length / PAGE_SIZE)))
const pagedTasks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return visibleTasks.value.slice(start, start + PAGE_SIZE)
})

watch(() => props.ctx?.subtitleTaskManualFilter, () => {
  currentPage.value = 1
})

watch(() => visibleTasks.value.length, () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
})

const taskRefs = new Map()
function registerTaskRef(id, el) {
  if (el) taskRefs.set(id, el)
  else taskRefs.delete(id)
}

let scrollRafId = 0
function scrollToActiveTask(id) {
  if (!id) return
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  scrollRafId = requestAnimationFrame(() => {
    scrollRafId = 0
    const el = taskRefs.get(id)
    if (!el || !el.isConnected) return
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

watch(
  () => props.ctx?.selectedSubtitleTaskId || props.ctx?.activeSubtitleTask?.id || props.ctx?.subtitleActiveTaskId || '',
  (id) => {
    if (!id) return
    const tasks = visibleTasks.value
    const idx = tasks.findIndex(t => t.id === id)
    if (idx < 0) return
    const targetPage = Math.floor(idx / PAGE_SIZE) + 1
    if (targetPage !== currentPage.value) currentPage.value = targetPage
    nextTick(() => scrollToActiveTask(id))
  }
)

function handleClear(scope) {
  clearMenuOpen.value = false
  props.ctx?.clearSubtitleTasksByScope?.(scope)
}

function handleDocumentClick(event) {
  if (!clearMenuOpen.value || !rootRef.value) return
  if (!rootRef.value.contains(event.target)) clearMenuOpen.value = false
}

function handleEscape(event) {
  if (event.key === 'Escape') {
    clearMenuOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  window.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  window.removeEventListener('keydown', handleEscape)
})

function getTaskStatusKey(task) {
  return props.ctx?.getRJSubtitleTaskStatusClass?.(task) || task?.status || 'pending'
}

function getStatusLabel(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || status === 'manual_match_completed') return '已匹配完成'
  if (status === 'completed') return '已完成'
  if (['processing'].includes(status)) return '执行中'
  if (['awaiting', 'awaiting_manual_match', 'waiting_manual'].includes(status)) return '待手动配对'
  if (status === 'view_restored') return '恢复查看'
  if (status === 'view_backfilled') return '已回填'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return '待处理'
}

function getStatusClass(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || status === 'manual_match_completed') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (status === 'view_restored') return 'border-violet-200 bg-violet-50 text-violet-700'
  if (status === 'view_backfilled') return 'border-slate-200 bg-slate-50 text-slate-700'
  if (['processing', 'awaiting', 'awaiting_manual_match', 'waiting_manual'].includes(status)) {
    return 'border-sky-200 bg-sky-50 text-sky-700'
  }
  if (status === 'failed') return 'border-rose-200 bg-rose-50 text-rose-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function getStatusIcon(task) {
  const status = getTaskStatusKey(task)
  if (task?.manual_match_completed || status === 'manual_match_completed') return CheckCircle2
  if (status === 'processing') return Loader2
  if (['awaiting', 'awaiting_manual_match', 'waiting_manual'].includes(status)) return Link2
  if (status === 'failed') return XCircle
  if (status === 'view_backfilled') return ListTodo
  return Clock
}

function getCardClass(task) {
  const status = getTaskStatusKey(task)
  if (isTaskInteractionLocked(task)) {
    return props.ctx?.isSubtitleTaskSelected?.(task)
      ? 'cursor-not-allowed border-slate-300 bg-white opacity-75'
      : 'cursor-not-allowed border-slate-200 bg-white opacity-70'
  }
  if (props.ctx?.isSubtitleTaskSelected?.(task)) {
    return 'border-slate-400 bg-white hover:-translate-y-0.5 hover:scale-[1.01] active:translate-y-0 active:scale-[0.98]'
  }
  if (task?.manual_match_completed || status === 'manual_match_completed') {
    return 'border-emerald-200/70 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-emerald-300 active:translate-y-0 active:scale-[0.98]'
  }
  if (status === 'view_restored') {
    return 'border-violet-200/70 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-violet-300 active:translate-y-0 active:scale-[0.98]'
  }
  if (status === 'view_backfilled') {
    return 'border-slate-200/80 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-slate-300 active:translate-y-0 active:scale-[0.98]'
  }
  if (status === 'processing') {
    return 'border-sky-200/70 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-sky-300 active:translate-y-0 active:scale-[0.98]'
  }
  if (status === 'failed') {
    return 'border-rose-200/70 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-rose-300 active:translate-y-0 active:scale-[0.98]'
  }
  return 'border-slate-100 hover:-translate-y-0.5 hover:scale-[1.01] hover:border-slate-300 active:translate-y-0 active:scale-[0.98]'
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

function statDotClass(key) {
  const k = String(key || '').toLowerCase()
  if (k === 'all' || k === 'total') return 'bg-slate-700'
  if (k === 'pending' || k === 'waiting' || k === 'awaiting' || k === 'waiting_manual' || k === 'awaiting_manual_match') return 'bg-amber-400'
  if (k === 'processing') return 'bg-sky-500'
  if (k === 'clearable') return 'bg-slate-400'
  if (k === 'completed' || k === 'matched' || k === 'manual_match_completed') return 'bg-emerald-500'
  if (k === 'failed') return 'bg-rose-500'
  return 'bg-slate-300'
}

function getCurrentStep(task) {
  return task?.current_step || task?.error_message || '等待中'
}

function getDisplayFolderName(task) {
  const folderName = String(task?.folder_name || '').trim().replace(/[\\/]+$/, '')
  if (folderName) {
    const parts = folderName.split(/[\\/]/).filter(Boolean)
    return parts[parts.length - 1] || folderName
  }
  return props.ctx?.getFileName?.(task?.folder_path) || '-'
}
</script>

<style scoped>
.subtitle-task-navigator button:not(:disabled) {
  cursor: pointer !important;
}

.subtitle-task-navigator button:disabled {
  cursor: not-allowed !important;
}

.subtitle-task-navigator :deep(.bg-slate-50),
.subtitle-task-navigator :deep(.bg-slate-50\/80),
.subtitle-task-navigator :deep(.bg-slate-100) {
  background-color: #ffffff !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-white"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-white"]) {
  background-color: #242529 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(246, 246, 248, 0.88) !important;
}

:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep(.bg-slate-50),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep(.bg-slate-50\/80),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep(.bg-slate-100),
:global(html.dark) .subtitle-task-navigator :deep(.bg-slate-50),
:global(html.dark) .subtitle-task-navigator :deep(.bg-slate-50\/80),
:global(html.dark) .subtitle-task-navigator :deep(.bg-slate-100) {
  background-color: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(218, 218, 224, 0.72) !important;
}

:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-emerald-"]),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-sky-"]),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-violet-"]),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-amber-"]),
:global(html.kikoerumanager-dark) .subtitle-task-navigator :deep([class*="bg-rose-"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-emerald-"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-sky-"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-violet-"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-amber-"]),
:global(html.dark) .subtitle-task-navigator :deep([class*="bg-rose-"]) {
  background-color: #242529 !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-task-navigator :deep(.shadow-sm),
.subtitle-task-navigator :deep(.shadow),
.subtitle-task-navigator :deep(.shadow-md),
.subtitle-task-navigator :deep(.shadow-lg),
.subtitle-task-navigator :deep(.shadow-xl),
.subtitle-task-navigator :deep([class*="shadow-"]) {
  box-shadow: none !important;
}

.subtitle-task-navigator :deep(.ring-1),
.subtitle-task-navigator :deep(.ring-2),
.subtitle-task-navigator :deep([class*="ring-"]) {
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
  box-shadow: none !important;
}

.subtitle-clear-menu-wrap {
  position: relative;
  flex: 0 0 auto;
  min-width: 0;
}

.subtitle-task-navigator {
  min-width: 0;
  overflow: hidden;
}

.subtitle-queue-header {
  min-width: 0;
  overflow: visible;
}

.subtitle-queue-body {
  min-height: 0;
  overflow: hidden;
}

.subtitle-task-title,
.subtitle-task-folder-name,
.subtitle-task-step {
  min-width: 0;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
  display: -webkit-box;
  -webkit-box-orient: vertical;
}

.subtitle-task-title {
  flex: 1 1 auto;
  -webkit-line-clamp: 2;
}

.subtitle-task-folder-name,
.subtitle-task-step {
  -webkit-line-clamp: 2;
}

.subtitle-clear-trigger {
  display: inline-flex;
  max-width: 84px;
  min-height: 30px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  overflow: hidden;
  white-space: nowrap;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 0 8px;
  color: #0f172a;
  font-size: 11.5px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-clear-trigger span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.subtitle-clear-trigger:hover:not(:disabled) {
  transform: scale(1.02);
  border-color: #cbd5e1;
  background: #ffffff;
}

.subtitle-clear-trigger:active:not(:disabled) {
  transform: scale(0.96);
}

.subtitle-clear-trigger-icon {
  width: 13px;
  height: 13px;
  color: #e11d48;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-clear-trigger:hover .subtitle-clear-trigger-icon {
  transform: rotate(-8deg) scale(1.1);
}

.subtitle-clear-trigger-chev {
  width: 12px;
  height: 12px;
  transition: transform 0.2s ease;
}

.subtitle-clear-menu-panel {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  z-index: 120;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 196px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  padding: 5px;
  box-shadow: none;
}

.subtitle-clear-menu-item {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 28px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 0;
  border-radius: 9px;
  background: #ffffff;
  padding: 6px 8px;
  color: #0f172a;
  text-align: left;
  font-size: 11.5px;
  font-weight: 650;
  transition: all 0.2s ease;
}

.subtitle-clear-menu-item span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-clear-menu-item:hover:not(:disabled) {
  transform: none;
  background: #ffffff;
  color: #0f172a;
}

.subtitle-clear-menu-item:disabled {
  opacity: 0.45;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-trigger),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-trigger) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #24252a !important;
  background-image: none !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-trigger:hover:not(:disabled)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-trigger:hover:not(:disabled)) {
  border-color: rgba(255, 255, 255, 0.24) !important;
  background: #303136 !important;
  background-image: none !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #111216 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel .subtitle-clear-menu-item),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel .subtitle-clear-menu-item) {
  border-color: transparent !important;
  background: transparent !important;
  background-image: none !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel .subtitle-clear-menu-item:hover:not(:disabled)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-panel .subtitle-clear-menu-item:hover:not(:disabled)) {
  background: #24252a !important;
  background-image: none !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-count),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-clear-menu-count) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #2b2c30 !important;
  background-image: none !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

.subtitle-clear-menu-count {
  display: inline-flex;
  min-width: 20px;
  justify-content: center;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #ffffff;
  padding: 1px 6px;
  color: #0f172a;
  font-size: 10px;
  font-weight: 800;
}

.subtitle-queue-overview {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: 32px;
  gap: 6px;
  align-content: start;
  padding: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  min-width: 0;
  overflow: hidden;
}

.subtitle-queue-filter {
  position: relative;
  display: flex;
  min-width: 0;
  width: 100%;
  min-height: 0;
  height: 32px;
  align-items: center;
  gap: 7px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 9px;
  background: #ffffff;
  padding: 0 8px 0 10px;
  color: #334155;
  text-align: left;
  transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1),
              background 0.2s ease,
              border-color 0.2s ease,
              color 0.2s ease;
}

.subtitle-queue-filter:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: #cbd5e1;
  background: #ffffff;
  color: #0f172a;
}

.subtitle-queue-filter:active {
  transform: scale(0.96);
}

.subtitle-task-navigator button:focus,
.subtitle-task-navigator button:focus-visible {
  outline: none;
  box-shadow: none;
}

.subtitle-queue-filter.is-active {
  border-color: #94a3b8;
  background: #ffffff;
  color: #0f172a;
}

.subtitle-queue-active-mark {
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 16px;
  border-radius: 0 999px 999px 0;
  background: #0f172a;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.24s ease;
}

.subtitle-queue-filter:hover .subtitle-queue-active-mark {
  opacity: 0.28;
}

.subtitle-queue-active-mark.is-active {
  opacity: 1;
}

.subtitle-queue-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 999px;
}

.subtitle-queue-label {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  color: currentColor;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-queue-count {
  flex: 0 0 auto;
  color: #94a3b8;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1;
}

.subtitle-queue-count.is-active,
.subtitle-queue-count.has-value {
  color: #0f172a;
  font-weight: 800;
}

:global(html.kikoerumanager-dark .subtitle-queue-overview) {
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-filter) {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(244, 244, 245, 0.86) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-filter:hover) {
  background: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-filter.is-active) {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: rgba(244, 244, 245, 0.9) !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-active-mark),
:global(html.dark .subtitle-queue-active-mark) {
  background: #8f96a3 !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-count) {
  color: rgba(214, 214, 220, 0.48) !important;
}

:global(html.kikoerumanager-dark .subtitle-queue-count.is-active),
:global(html.kikoerumanager-dark .subtitle-queue-count.has-value) {
  color: rgba(250, 250, 252, 0.94) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-violet-500, .text-violet-600, .text-violet-700)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-violet-500, .text-violet-600, .text-violet-700)) {
  color: #a78bfa !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-amber-500, .text-amber-600, .text-amber-700)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-amber-500, .text-amber-600, .text-amber-700)) {
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-sky-500, .text-sky-600, .text-sky-700)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-sky-500, .text-sky-600, .text-sky-700)) {
  color: #38bdf8 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-emerald-500, .text-emerald-600, .text-emerald-700)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-emerald-500, .text-emerald-600, .text-emerald-700)) {
  color: #34d399 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-rose-500, .text-rose-600, .text-rose-700)),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator :is(.text-rose-500, .text-rose-600, .text-rose-700)) {
  color: #fb7185 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-amber-400),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-amber-400) {
  background: #fbbf24 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-sky-500),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-sky-500) {
  background: #38bdf8 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-emerald-500),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-emerald-500) {
  background: #34d399 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-rose-500),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-rose-500) {
  background: #fb7185 !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-slate-700),
:global(html.dark .subtitle-workbench-dialog .subtitle-task-navigator .subtitle-queue-dot.bg-slate-700) {
  background: #8f96a3 !important;
}

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
