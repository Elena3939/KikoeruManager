<template>
  <section
    class="flex h-full flex-col rounded-[14px] border border-slate-200/80 bg-white p-4 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]"
    data-section="dashboard-tasks"
  >
    <!-- 顶部：标题 + 查看全部 -->
    <header class="flex flex-shrink-0 items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="m-0 text-[14px] font-bold tracking-tight text-slate-900">任务流</h2>
        <p class="m-0 mt-0.5 text-[11.5px] leading-snug text-slate-500">活跃任务优先，空闲时展示最近完成 / 失败</p>
      </div>
      <button
        type="button"
        class="group inline-flex items-center gap-1 rounded-[8px] border border-transparent px-2.5 py-1 text-[12px] font-medium text-slate-500 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:border-slate-200 hover:bg-slate-50 hover:text-slate-900 active:scale-95"
        @click="$emit('go', '/tasks')"
      >
        查看全部
        <ArrowRight :size="13" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-0.5" />
      </button>
    </header>

    <!-- 状态 summary chips（合并自 DashboardStatusPanel） -->
    <div
      v-if="statusCards.length"
      class="mt-2.5 grid flex-shrink-0 grid-cols-2 gap-1.5 sm:grid-cols-3 xl:grid-cols-6"
    >
      <div
        v-for="item in statusCards"
        :key="item.key"
        class="dash-status-chip group flex items-center justify-between gap-1.5 rounded-[9px] border border-slate-200/80 bg-white px-2.5 py-1.5 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_4px_10px_-6px_rgba(15,23,42,0.18)]"
      >
        <span class="inline-flex items-center gap-1.5 min-w-0">
          <component
            :is="statusIconFor(item.key)"
            :size="13"
            :stroke-width="2.2"
            :class="statusIconColor(item.key)"
          />
          <span class="truncate text-[11.5px] font-medium text-slate-600">{{ item.label }}</span>
        </span>
        <b
          class="text-[14px] font-bold tabular-nums leading-none"
          :class="statusValueColor(item.key, item.value)"
        >{{ item.value }}</b>
      </div>
    </div>

    <!-- 任务列表 -->
    <div v-if="tasks.length" class="dash-task-list mt-3 flex flex-1 flex-col gap-2 overflow-hidden">
      <article
        v-for="(task, index) in pagedTasks"
        :key="task.id"
        class="dash-fade-up group grid grid-cols-[40px_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-0 rounded-[10px] border border-slate-100 bg-white p-3 transition-colors duration-300 hover:border-slate-200 hover:bg-slate-50/50"
        :style="{ animationDelay: `${index * 40}ms` }"
      >
        <!-- 域图标 -->
        <span
          class="dash-task-icon-box mt-0.5 inline-flex h-10 w-10 flex-shrink-0 items-center justify-center transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
        >
          <component :is="taskIcon(task)" :size="20" :stroke-width="1.9" :class="taskIconClass(task)" />
        </span>

        <!-- 主内容 -->
        <div class="min-w-0">
          <h3 class="m-0 truncate text-[13.5px] font-bold leading-tight text-slate-900">{{ task.title }}</h3>
          <p v-if="displaySubtitle(task)" class="m-0 mt-0.5 truncate text-[12px] text-slate-500">{{ displaySubtitle(task) }}</p>

          <div class="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
            <span class="inline-flex h-[22px] items-center gap-1 rounded-[6px] border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-600">
              <component :is="taskIcon(task)" :size="11" :stroke-width="1.8" :class="taskChipIconClass(task)" />
              {{ taskDomainLabel(task) }}
            </span>
            <span
              v-if="taskBadgeLabel(task)"
              class="dash-task-badge-chip inline-flex min-h-[22px] items-center rounded-[6px] bg-slate-50 px-2 py-0.5 text-[11px] tabular-nums text-slate-500"
              :title="taskBadgeLabel(task)"
            >
              <span class="min-w-0 truncate">{{ taskBadgeLabel(task) }}</span>
            </span>
            <span
              v-if="task.current_step && !isTerminalStatus(task)"
              class="inline-flex min-h-[22px] items-center rounded-[6px] px-2 py-0.5 text-[11px] leading-snug whitespace-normal break-all"
              :class="stepChipClass(task)"
            >
              {{ task.current_step }}
            </span>
          </div>

          <div v-if="showProgress(task)" class="dash-task-progress mt-2.5 flex items-center gap-2">
            <div class="dash-task-progress-track h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div class="dash-task-progress-fill h-full rounded-full transition-all duration-700 ease-out" :class="domainMeta(task.domain).bar" :style="{ width: `${task.progress}%` }" />
            </div>
            <span class="dash-task-progress-percent text-[11px] tabular-nums text-slate-500">{{ task.progress }}%</span>
          </div>
        </div>

        <!-- 右列：状态 pill + 操作按钮 -->
        <div class="flex flex-shrink-0 items-center gap-1.5 pt-0.5">
          <StatusPill :status="statusClass(task)" :label="statusLabel(task)" />
          <button
            type="button"
            data-dashboard-task-action-trigger="1"
            class="dash-task-menu-trigger group inline-flex h-8 w-8 items-center justify-center rounded-[8px] border border-transparent text-slate-400 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.06] hover:border-slate-200 hover:bg-slate-50 hover:text-slate-800 active:translate-y-0 active:scale-95"
            aria-haspopup="menu"
            :aria-expanded="taskActionMenu.visible && taskActionMenu.task?.id === task.id"
            title="任务操作"
            @click="openTaskActionMenu(task, $event)"
          >
            <MoreVertical :size="14" :stroke-width="2" class="transition-transform duration-300 group-hover:rotate-90 group-hover:scale-110" />
          </button>
        </div>
      </article>
    </div>

    <div v-else class="mt-3 flex flex-1 items-center justify-center rounded-[12px] border border-dashed border-slate-200">
      <AppEmptyState description="当前没有需要关注的任务" size="default" />
    </div>

    <div
      v-if="tasks.length && totalPages > 1"
      class="dash-task-pager mt-2.5 flex flex-shrink-0 items-center justify-between gap-2 border-t border-slate-100 pt-2.5"
    >
      <span class="text-[11px] font-medium tracking-wide text-slate-400">
        共 <b class="text-slate-700 tabular-nums">{{ tasks.length }}</b> 条任务
      </span>

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="dash-task-pager-btn group"
          :disabled="internalPage <= 1"
          aria-label="上一页任务"
          @click="goPrevPage"
        >
          <ChevronLeft :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:-translate-x-0.5" />
        </button>

        <div class="dash-task-pager-indicator">
          <span class="dash-task-pager-current">{{ internalPage }}</span>
          <span class="dash-task-pager-divider">/</span>
          <span class="dash-task-pager-total">{{ totalPages }}</span>
        </div>

        <button
          type="button"
          class="dash-task-pager-btn group"
          :disabled="internalPage >= totalPages"
          aria-label="下一页任务"
          @click="goNextPage"
        >
          <ChevronRight :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-0.5" />
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="taskActionMenu.visible"
        ref="taskActionMenuPanel"
        class="dash-task-action-menu fixed z-[2400] w-[200px] overflow-hidden rounded-[10px] border border-slate-200 p-1.5"
        :style="{ left: `${taskActionMenu.x}px`, top: `${taskActionMenu.y}px` }"
        role="menu"
        @click.stop
        @contextmenu.stop
      >
        <div class="dash-task-action-menu-header flex items-center px-2 py-1.5">
          <span class="min-w-0 truncate text-[11px] font-semibold tracking-tight text-slate-700" :title="taskActionMenu.task?.title || ''">
            {{ taskActionMenu.task?.title || '任务操作' }}
          </span>
        </div>

        <button
          v-for="action in taskMenuActions(taskActionMenu.task)"
          :key="`${taskActionMenu.task?.id}-${action}`"
          type="button"
          class="dash-task-action-menu-item"
          :class="actionToneClass(action)"
          role="menuitem"
          @click="runTaskAction(action)"
        >
          <component
            :is="actionIcon(action)"
            :size="14"
            :stroke-width="2.2"
            class="dash-task-action-menu-icon"
            :class="actionIconClass(action)"
          />
          <span>{{ getActionLabel(action, taskActionMenu.task) }}</span>
        </button>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Activity, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight, Clock3, MoreVertical, PauseCircle, PlayCircle, RotateCcw, RotateCw, Trash2, XCircle } from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatusPill from './StatusPill.vue'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'
import { getHttpDownloadDisplayMeta } from '../common/httpDownloadPlatformMeta.js'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  statusCards: { type: Array, default: () => [] },
})

const emit = defineEmits(['go', 'action'])

const MENU_WIDTH = 200
const MENU_PADDING = 12
const PAGE_SIZE = 6

const taskActionMenuPanel = ref(null)
const internalPage = ref(1)
const taskActionMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  task: null,
})

const STATUS_ICON_MAP = {
  processing: Activity,
  waiting_total: Clock3,
  completed: CheckCircle2,
  waiting: PauseCircle,
  retry: RotateCw,
  failed: XCircle,
}

const ACTION_ICON_MAP = {
  pause: PauseCircle,
  resume: PlayCircle,
  cancel: XCircle,
  retry: RotateCcw,
  retry_waiting: RotateCcw,
  delete: Trash2,
  delete_waiting_retry: Trash2,
  open_route: ArrowRight,
  open_tasks: ArrowRight,
  open_subtitle_import: ArrowRight,
}

const ACTION_LABEL_MAP = {
  pause: '暂停',
  resume: '恢复',
  cancel: '取消',
  delete: '删除',
  retry: '重试',
  retry_waiting: '立即重试',
  delete_waiting_retry: '移除',
  open_route: '查看处理',
  open_tasks: '查看任务详情',
  open_subtitle_import: '前往字幕补配',
}

const totalPages = computed(() => {
  const total = Array.isArray(props.tasks) ? props.tasks.length : 0
  return Math.max(1, Math.ceil(total / PAGE_SIZE))
})

const pagedTasks = computed(() => {
  const list = Array.isArray(props.tasks) ? props.tasks : []
  const safePage = Math.min(Math.max(1, internalPage.value), totalPages.value)
  const start = (safePage - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})

watch(
  () => props.tasks.map((task) => task?.id || '').join('|'),
  () => {
    if (internalPage.value > totalPages.value) internalPage.value = totalPages.value
    if (internalPage.value < 1) internalPage.value = 1
  }
)

watch(totalPages, (max) => {
  if (internalPage.value > max) internalPage.value = max
  if (internalPage.value < 1) internalPage.value = 1
})

function goPrevPage() {
  if (internalPage.value <= 1) return
  closeTaskActionMenu()
  internalPage.value -= 1
}

function goNextPage() {
  if (internalPage.value >= totalPages.value) return
  closeTaskActionMenu()
  internalPage.value += 1
}

function taskHasActions(task) {
  return taskMenuActions(task).length > 0
}

function taskMenuActions(task) {
  const explicitActions = Array.isArray(task?.actions)
    ? task.actions.map(action => String(action || '').trim()).filter(Boolean)
    : []
  if (explicitActions.length) return explicitActions

  const status = String(task?.status || '').trim().toLowerCase()
  const isEngineTask = String(task?.id || '').startsWith('engine:')
  if (isEngineTask && ['pending', 'processing', 'running'].includes(status)) return ['pause', 'cancel']
  if (isEngineTask && status === 'paused') return ['resume', 'cancel']
  if (isEngineTask && ['completed', 'success', 'finished', 'failed', 'error', 'cancelled', 'canceled'].includes(status)) {
    return ['delete']
  }
  if (task?.route_hint) return ['open_route']
  return ['open_tasks']
}

function clampMenuPosition(x, y) {
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || MENU_WIDTH
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 320
  const safeX = Math.min(
    Math.max(MENU_PADDING, Number(x || 0)),
    Math.max(MENU_PADDING, viewportWidth - MENU_WIDTH - MENU_PADDING)
  )
  const panelHeight = taskActionMenuPanel.value?.offsetHeight || 44 + Math.max(1, taskMenuActions(taskActionMenu.value.task).length) * 33
  const safeY = Math.min(
    Math.max(MENU_PADDING, Number(y || 0)),
    Math.max(MENU_PADDING, viewportHeight - panelHeight - MENU_PADDING)
  )
  return { x: safeX, y: safeY }
}

function openTaskActionMenu(task, event) {
  event?.stopPropagation?.()
  const rect = event?.currentTarget?.getBoundingClientRect?.()
  const x = rect ? rect.right - MENU_WIDTH : MENU_PADDING
  const y = rect ? rect.bottom + 6 : MENU_PADDING
  const nextPosition = clampMenuPosition(x, y)
  taskActionMenu.value = {
    visible: true,
    x: nextPosition.x,
    y: nextPosition.y,
    task,
  }
  bindTaskActionMenuDismiss()
  nextTick(() => {
    const adjusted = clampMenuPosition(taskActionMenu.value.x, taskActionMenu.value.y)
    taskActionMenu.value = { ...taskActionMenu.value, ...adjusted }
  })
}

function closeTaskActionMenu() {
  if (!taskActionMenu.value.visible) return
  taskActionMenu.value = {
    visible: false,
    x: 0,
    y: 0,
    task: null,
  }
  unbindTaskActionMenuDismiss()
}

function handleTaskActionMenuDismiss(event) {
  if (!taskActionMenu.value.visible) return
  const target = event?.target
  if (taskActionMenuPanel.value && taskActionMenuPanel.value.contains(target)) return
  if (target instanceof Element && target.closest('[data-dashboard-task-action-trigger="1"]')) return
  closeTaskActionMenu()
}

function handleTaskActionMenuScroll() {
  closeTaskActionMenu()
}

function bindTaskActionMenuDismiss() {
  document.removeEventListener('mousedown', handleTaskActionMenuDismiss, true)
  document.removeEventListener('click', handleTaskActionMenuDismiss, true)
  document.removeEventListener('contextmenu', handleTaskActionMenuDismiss, true)
  window.removeEventListener('scroll', handleTaskActionMenuScroll, true)
  document.addEventListener('mousedown', handleTaskActionMenuDismiss, true)
  document.addEventListener('click', handleTaskActionMenuDismiss, true)
  document.addEventListener('contextmenu', handleTaskActionMenuDismiss, true)
  window.addEventListener('scroll', handleTaskActionMenuScroll, true)
}

function unbindTaskActionMenuDismiss() {
  document.removeEventListener('mousedown', handleTaskActionMenuDismiss, true)
  document.removeEventListener('click', handleTaskActionMenuDismiss, true)
  document.removeEventListener('contextmenu', handleTaskActionMenuDismiss, true)
  window.removeEventListener('scroll', handleTaskActionMenuScroll, true)
}

function runTaskAction(action) {
  const task = taskActionMenu.value.task
  closeTaskActionMenu()
  if (!task || !action) return
  if (action === 'open_route' || action === 'open_tasks') {
    emit('go', action === 'open_route' ? (task.route_hint || '/tasks') : '/tasks')
    return
  }
  emit('action', task, action)
}

onBeforeUnmount(() => {
  unbindTaskActionMenuDismiss()
})

function domainMeta(domain) {
  return getTaskDomainMeta(domain)
}

function isDownloadProviderTask(task) {
  return ['http_download', 'baidu_netdisk'].includes(String(task?.domain || '').trim())
}

function httpDisplayMeta(task) {
  return getHttpDownloadDisplayMeta(task)
}

function taskIcon(task) {
  if (isDownloadProviderTask(task)) return httpDisplayMeta(task).icon || domainMeta(task.domain).icon
  return domainMeta(task.domain).icon
}

function taskIconClass(task) {
  return isDownloadProviderTask(task) && httpDisplayMeta(task).icon
    ? 'dash-platform-icon'
    : domainMeta(task.domain).chipIcon
}

function taskChipIconClass(task) {
  return isDownloadProviderTask(task) && httpDisplayMeta(task).icon
    ? 'dash-platform-chip-icon'
    : domainMeta(task.domain).chipIcon
}

function taskDomainLabel(task) {
  if (isDownloadProviderTask(task)) return httpDisplayMeta(task).label || task.domain_label || domainMeta(task.domain).label
  return task.domain_label
}

function displaySubtitle(task) {
  if (String(task?.domain || '').trim() === 'import') return ''
  return String(task?.subtitle || '').trim()
}

function taskBadgeLabel(task) {
  if (String(task?.domain || '').trim() === 'import') return getImportRenamedLabel(task)
  return formatRJ(task?.rjcode)
}

function getImportRenamedLabel(task) {
  const metadata = task?.details?.metadata || {}
  const candidates = [
    task?.target_path,
    metadata.final_output_path,
    metadata.renamed_output_path,
    metadata.target_path,
    metadata.folder_path,
  ]
  for (const candidate of candidates) {
    const label = getPathLeaf(candidate)
    if (label) return label
  }
  return ''
}

function getPathLeaf(value) {
  const text = String(value || '').trim().replace(/[\\/]+$/g, '')
  if (!text) return ''
  const parts = text.split(/[\\/]/).filter(Boolean)
  return parts.length ? parts[parts.length - 1] : ''
}

function actionIcon(action) {
  return ACTION_ICON_MAP[action] || ArrowRight
}

function getActionLabel(action, task = null) {
  if (action === 'open_route' && String(task?.route_hint || '').includes('subtitle')) return '前往字幕补配'
  if (action === 'open_route' && String(task?.route_hint || '').includes('conflicts')) return '前往问题作品'
  return ACTION_LABEL_MAP[action] || action
}

function actionToneClass(action) {
  if (action === 'cancel' || action === 'delete' || action === 'delete_waiting_retry') return 'dash-task-action-menu-item--danger'
  if (action === 'pause') return 'dash-task-action-menu-item--warning'
  if (action === 'resume') return 'dash-task-action-menu-item--success'
  return ''
}

function actionIconClass(action) {
  if (action === 'cancel' || action === 'delete' || action === 'delete_waiting_retry') return 'text-rose-600'
  if (action === 'pause') return 'text-amber-600'
  if (action === 'resume') return 'text-emerald-600'
  if (action === 'retry' || action === 'retry_waiting') return 'text-amber-600'
  return 'text-slate-500'
}

function showProgress(task) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(effectiveStatus(task))
}

function statusClass(task) {
  return effectiveStatus(task) || 'default'
}

function statusLabel(task) {
  const status = effectiveStatus(task)
  if (status === 'cancelled' || task?.error_message === '用户取消') return '已取消'
  if (status === 'completed') return '已完成'
  return task?.status_label || task?.status || '-'
}

function isTerminalStatus(task) {
  const s = effectiveStatus(task)
  return ['completed', 'success', 'finished', 'failed', 'error', 'cancelled', 'canceled'].includes(s)
}

function stepChipClass(task) {
  const s = effectiveStatus(task)
  if (['completed', 'success', 'finished'].includes(s)) return 'bg-emerald-50 text-emerald-700'
  if (['failed', 'error'].includes(s)) return 'bg-rose-50 text-rose-700'
  if (['cancelled', 'canceled'].includes(s)) return 'bg-slate-100 text-slate-500'
  if (['processing', 'running'].includes(s)) return 'bg-amber-50 text-amber-700'
  if (['waiting_manual', 'waiting_retry', 'pending', 'paused'].includes(s)) return 'bg-slate-100 text-slate-500'
  return 'bg-slate-50 text-slate-500'
}

function effectiveStatus(task) {
  const status = String(task?.status || '').toLowerCase()
  const progress = Number(task?.progress || 0)
  if (['processing', 'running'].includes(status) && progress >= 100) return 'completed'
  return status
}

function statusIconFor(key) {
  return STATUS_ICON_MAP[key] || Activity
}

function statusIconColor(key) {
  if (key === 'processing') return 'text-amber-500'
  if (key === 'waiting_total') return 'text-indigo-500'
  if (key === 'completed') return 'text-emerald-500'
  if (key === 'waiting') return 'text-slate-400'
  if (key === 'retry') return 'text-orange-500'
  if (key === 'failed') return 'text-rose-500'
  if (key === 'cancelled') return 'text-slate-400'
  return 'text-slate-400'
}

function statusValueColor(key, value) {
  const n = Number(value || 0)
  if (n <= 0) return 'text-slate-400'
  if (key === 'failed') return 'text-rose-600'
  if (key === 'cancelled') return 'text-slate-500'
  if (key === 'processing') return 'text-amber-600'
  if (key === 'waiting_total') return 'text-indigo-600'
  if (key === 'completed') return 'text-emerald-600'
  if (key === 'waiting') return 'text-slate-600'
  if (key === 'retry') return 'text-orange-600'
  return 'text-slate-800'
}

function formatRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const match = text.match(/[RVB]J\s*(\d{4,})/i)
  return match ? `RJ${match[1]}` : text
}
</script>

<style scoped>
.dash-task-list {
  scrollbar-width: none;
}

.dash-task-list::-webkit-scrollbar {
  display: none;
}

@media (max-width: 1024px) {
  .dash-task-list {
    flex: 0 0 auto !important;
    max-height: none !important;
    overflow: visible !important;
  }
}

:global(html.kikoerumanager-dark [data-section="dashboard-tasks"]) {
  background: #101012 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #f8fafc !important;
  box-shadow: 0 22px 58px rgba(0, 0, 0, 0.46), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"]) {
  background: #101012 !important;
  background-color: #101012 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #f8fafc !important;
}

:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] .border-dashed),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-white),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-50),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-100),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] [class*="bg-blue-50"]),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] [class*="bg-sky-50"]),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] [class*="bg-indigo-50"]),
:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] [class*="bg-violet-50"]) {
  background: #17181b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] :is(.border-dashed, .bg-white, .bg-slate-50, .bg-slate-100, [class*="bg-blue-50"], [class*="bg-sky-50"], [class*="bg-indigo-50"], [class*="bg-violet-50"])) {
  background: #17181b !important;
  background-color: #17181b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark [data-section="dashboard-tasks"] .border-dashed) {
  background: #101012 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .border-dashed) {
  background: #101012 !important;
  background-color: #101012 !important;
  background-image: none !important;
}
</style>

<style scoped>
.dash-fade-up {
  animation: dash-fade-up 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.dash-platform-icon,
.dash-platform-chip-icon {
  object-fit: contain;
  border-radius: 3px;
}

.dash-platform-icon {
  width: 20px;
  height: 20px;
}

.dash-platform-chip-icon {
  width: 12px;
  height: 12px;
}

.dash-task-icon-box {
  background: transparent;
  border: 0;
  box-shadow: none;
  color: inherit;
}

.dash-task-badge-chip {
  min-width: 0;
  max-width: 100%;
  flex: 1 1 280px;
}

.dash-task-pager-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid rgb(226 232 240);
  border-radius: 7px;
  background: #ffffff;
  color: rgb(71 85 105);
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.dash-task-pager-btn:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgb(15 23 42);
  background: rgb(15 23 42);
  color: #ffffff;
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.4);
}

.dash-task-pager-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.dash-task-pager-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
}

.dash-task-pager-indicator {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  height: 24px;
  padding: 0 9px;
  border-radius: 7px;
  background: rgb(248 250 252);
  border: 1px solid rgb(241 245 249);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}

.dash-task-pager-current {
  font-size: 12px;
  font-weight: 700;
  color: rgb(15 23 42);
  line-height: 1;
}

.dash-task-pager-divider {
  font-size: 10px;
  color: rgb(203 213 225);
  margin: 0 1px;
}

.dash-task-pager-total {
  font-size: 10.5px;
  font-weight: 600;
  color: rgb(100 116 139);
  line-height: 1;
}

.dash-task-action-menu {
  background: #ffffff;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px -10px rgba(15, 23, 42, 0.18),
    0 6px 16px -12px rgba(15, 23, 42, 0.12);
  animation: dash-task-menu-enter 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top right;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dash-task-action-menu-item {
  position: relative;
  display: inline-flex;
  min-height: 32px;
  width: 100%;
  cursor: pointer;
  align-items: center;
  gap: 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 0 9px;
  color: #334155;
  font-size: 12.5px;
  font-weight: 500;
  text-align: left;
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.2s ease;
}

.dash-task-action-menu-item:hover {
  background: rgb(248 250 252);
  color: #0f172a;
  transform: translateX(2px);
  box-shadow: inset 0 0 0 1px rgb(226 232 240);
}

.dash-task-action-menu-item:active {
  transform: translateX(2px) scale(0.98);
}

.dash-task-action-menu-icon {
  flex-shrink: 0;
  transition:
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.2s ease;
}

.dash-task-action-menu-item:hover .dash-task-action-menu-icon {
  transform: translateY(-1px) scale(1.12) rotate(-4deg);
}

.dash-task-action-menu-item--danger {
  color: #be123c;
}

.dash-task-action-menu-item--danger:hover {
  background: rgb(255 241 242);
  color: #9f1239;
  box-shadow: inset 0 0 0 1px rgb(254 205 211);
}

.dash-task-action-menu-item--warning:hover {
  background: rgb(255 251 235);
  box-shadow: inset 0 0 0 1px rgb(253 230 138);
}

.dash-task-action-menu-item--success:hover {
  background: rgb(240 253 244);
  box-shadow: inset 0 0 0 1px rgb(187 247 208);
}

@keyframes dash-task-menu-enter {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

:global(html.kikoerumanager-dark) .dash-task-icon-box {
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .dash-task-menu-trigger {
  background: rgba(255, 255, 255, 0.04) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .dash-task-menu-trigger:hover {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager {
  position: relative;
  z-index: 1;
  margin-bottom: 0 !important;
  background: #101012 !important;
  background-color: #101012 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(226, 232, 240, 0.72) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager b {
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-indicator {
  align-items: center;
  background: var(--km-dark-surface-soft) !important;
  background-color: var(--km-dark-surface-soft) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-current,
:global(html.kikoerumanager-dark) .dash-task-pager-total {
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-divider {
  color: rgba(255, 255, 255, 0.48) !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-btn {
  background: var(--km-dark-surface-soft) !important;
  background-color: var(--km-dark-surface-soft) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-btn:hover {
  background: var(--km-dark-surface-hover) !important;
  background-color: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .dash-task-pager-btn:disabled {
  background: rgba(255, 255, 255, 0.04) !important;
  background-color: rgba(255, 255, 255, 0.04) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.42) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  box-shadow: 0 22px 58px rgba(0, 0, 0, 0.56) !important;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu-header span {
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu-item {
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu-item:hover {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #ffffff !important;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.14) !important;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu-item--danger {
  color: #fda4af;
}

:global(html.kikoerumanager-dark) .dash-task-action-menu-item--danger:hover {
  background: rgba(244, 63, 94, 0.16);
  color: #fecdd3;
  box-shadow: inset 0 0 0 1px rgba(253, 164, 175, 0.28);
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .dash-task-progress-track.dash-task-progress-track) {
  background: rgba(255, 255, 255, 0.16) !important;
  background-color: rgba(255, 255, 255, 0.16) !important;
  background-image: none !important;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    inset 0 1px 1px rgba(0, 0, 0, 0.28) !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .dash-task-progress-fill.dash-task-progress-fill) {
  background-image: linear-gradient(90deg, rgba(251, 191, 36, 0.98), rgba(245, 158, 11, 0.94)) !important;
  background-color: #f59e0b !important;
  box-shadow:
    0 0 0 1px rgba(254, 243, 199, 0.24),
    0 0 14px rgba(245, 158, 11, 0.42) !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .dash-task-progress-percent.dash-task-progress-percent) {
  color: #f8fafc !important;
  -webkit-text-fill-color: #f8fafc !important;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.36) !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill.status-pill) {
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--failed),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--error) {
  background: rgba(244, 63, 94, 0.17) !important;
  border-color: rgba(251, 113, 133, 0.4) !important;
  color: #fecdd3 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--waiting_manual),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--waiting_retry),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--pending) {
  background: rgba(99, 102, 241, 0.18) !important;
  border-color: rgba(129, 140, 248, 0.42) !important;
  color: #e0e7ff !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--processing),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--running),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--partial_failed) {
  background: rgba(245, 158, 11, 0.18) !important;
  border-color: rgba(251, 191, 36, 0.42) !important;
  color: #fef3c7 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--completed),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--success),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--finished) {
  background: rgba(34, 197, 94, 0.17) !important;
  border-color: rgba(74, 222, 128, 0.38) !important;
  color: #dcfce7 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--cancelled),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--canceled),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--paused) {
  background: rgba(148, 163, 184, 0.16) !important;
  border-color: rgba(203, 213, 225, 0.28) !important;
  color: #e2e8f0 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill .status-pill-dot.status-pill-dot) {
  background-image: none !important;
  box-shadow: 0 0 0 2px rgba(8, 9, 12, 0.95), 0 0 10px currentColor !important;
  opacity: 1 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--failed .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--error .status-pill-dot) {
  background: #fb7185 !important;
  background-color: #fb7185 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--waiting_manual .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--waiting_retry .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--pending .status-pill-dot) {
  background: #a5b4fc !important;
  background-color: #a5b4fc !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--processing .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--running .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--partial_failed .status-pill-dot) {
  background: #fbbf24 !important;
  background-color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--completed .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--success .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--finished .status-pill-dot) {
  background: #4ade80 !important;
  background-color: #4ade80 !important;
}

:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--cancelled .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--canceled .status-pill-dot),
:global(html.kikoerumanager-dark body #app [data-section="dashboard-tasks"] .status-pill--paused .status-pill-dot) {
  background: #cbd5e1 !important;
  background-color: #cbd5e1 !important;
}

@keyframes dash-fade-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
