<template>
  <section
    class="flex h-full flex-col rounded-[12px] border border-slate-200/80 bg-white p-3 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]"
    data-section="dashboard-tasks"
  >
    <header class="mb-3 flex flex-shrink-0 items-center justify-between gap-2">
      <div class="min-w-0">
        <h2 class="m-0 text-[12.5px] font-bold tracking-tight text-slate-900">任务流</h2>
        <p class="m-0 mt-px text-[10px] text-slate-500">活跃任务优先，空闲时显示最近完成/失败</p>
      </div>
      <button
        type="button"
        class="group inline-flex items-center gap-1 rounded-[6px] border border-transparent px-2 py-1 text-[11.5px] font-medium text-slate-500 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:border-slate-200 hover:bg-slate-50 hover:text-slate-900 active:scale-95"
        @click="$emit('go', '/tasks')"
      >
        查看全部
        <ArrowRight :size="12" :stroke-width="2.4" class="transition-transform duration-300 group-hover:translate-x-1" />
      </button>
    </header>

    <div v-if="tasks.length" class="flex flex-1 flex-col gap-1.5 overflow-auto">
      <article
        v-for="(task, index) in tasks"
        :key="task.id"
        class="dash-fade-up group grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-x-2.5 gap-y-0 rounded-[8px] border border-slate-100 bg-white p-2.5 transition-colors duration-300 hover:border-slate-200 hover:bg-slate-50/50"
        :style="{ animationDelay: `${index * 40}ms` }"
      >
        <!-- 域图标 -->
        <span
          class="mt-0.5 inline-flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[8px] border border-slate-200 bg-white transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
        >
          <component :is="domainMeta(task.domain).icon" :size="13" :stroke-width="1.7" :class="domainMeta(task.domain).chipIcon" />
        </span>

        <!-- 主内容 -->
        <div class="min-w-0">
          <h3 class="m-0 truncate text-[12.5px] font-bold leading-tight text-slate-900">{{ task.title }}</h3>
          <p v-if="task.subtitle" class="m-0 mt-0.5 truncate text-[11px] text-slate-400">{{ task.subtitle }}</p>

          <div class="mt-1.5 flex flex-wrap items-center gap-1">
            <span class="inline-flex h-[18px] items-center gap-1 rounded-[4px] border border-slate-200 bg-white px-1.5 text-[10px] font-medium text-slate-600">
              <component :is="domainMeta(task.domain).icon" :size="10" :stroke-width="1.7" :class="domainMeta(task.domain).chipIcon" />
              {{ task.domain_label }}
            </span>
            <span v-if="formatRJ(task.rjcode)" class="inline-flex h-[18px] items-center gap-1 rounded-[4px] bg-slate-50 px-1.5 text-[10px] tabular-nums text-slate-500">
              {{ formatRJ(task.rjcode) }}
            </span>
            <span
              v-if="task.current_step && !isTerminalStatus(task)"
              class="inline-flex h-[18px] max-w-[160px] items-center truncate rounded-[4px] px-1.5 text-[10px]"
              :class="stepChipClass(task)"
            >
              {{ task.current_step }}
            </span>
          </div>

          <div v-if="showProgress(task)" class="mt-2 flex items-center gap-2">
            <div class="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div class="h-full rounded-full transition-all duration-700 ease-out" :class="domainMeta(task.domain).bar" :style="{ width: `${task.progress}%` }" />
            </div>
            <span class="text-[10px] tabular-nums text-slate-400">{{ task.progress }}%</span>
          </div>
        </div>

        <!-- 右列：状态 pill + 操作按钮 -->
        <div class="flex flex-shrink-0 items-center gap-1 pt-0.5">
          <StatusPill :status="statusClass(task)" :label="statusLabel(task)" />
          <button
            type="button"
            class="inline-flex h-5 w-5 items-center justify-center rounded-[4px] text-slate-400 transition-all duration-200 hover:bg-slate-100 hover:text-slate-700"
            :class="!task.actions?.length ? 'pointer-events-none opacity-30' : ''"
            :title="task.actions?.length ? getActionLabel(task.actions[0]) : ''"
            @click="task.actions?.length && $emit('action', task, task.actions[0])"
          >
            <MoreVertical :size="12" :stroke-width="2" />
          </button>
        </div>
      </article>
    </div>

    <div v-else class="flex flex-1 items-center justify-center rounded-[10px] border border-dashed border-slate-200 bg-slate-50/40">
      <AppEmptyState description="当前没有需要关注的任务" size="default" />
    </div>
  </section>
</template>

<script setup>
import { ArrowRight, MoreVertical, PauseCircle, PlayCircle, RotateCcw, XCircle } from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatusPill from './StatusPill.vue'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'

defineProps({
  tasks: { type: Array, default: () => [] },
})

defineEmits(['go', 'action'])

const ACTION_ICON_MAP = {
  pause: PauseCircle,
  resume: PlayCircle,
  cancel: XCircle,
  retry: RotateCcw,
  retry_waiting: RotateCcw,
  delete_waiting_retry: XCircle,
  open_subtitle_import: ArrowRight,
}

const ACTION_LABEL_MAP = {
  pause: '暂停',
  resume: '恢复',
  cancel: '取消',
  retry: '重试',
  retry_waiting: '立即重试',
  delete_waiting_retry: '移除',
  open_subtitle_import: '前往字幕补配',
}

function domainMeta(domain) {
  return getTaskDomainMeta(domain)
}

function actionIcon(action) {
  return ACTION_ICON_MAP[action] || ArrowRight
}

function getActionLabel(action) {
  return ACTION_LABEL_MAP[action] || action
}

function showProgress(task) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(task?.status)
}

function statusClass(task) {
  if (task?.error_message === '用户取消') return 'cancelled'
  return String(task?.status || 'default')
}

function statusLabel(task) {
  if (task?.error_message === '用户取消') return '已取消'
  return task?.status_label || task?.status || '-'
}

function isTerminalStatus(task) {
  const s = String(task?.status || '').toLowerCase()
  return ['completed', 'success', 'finished', 'failed', 'error', 'cancelled', 'canceled'].includes(s)
}

function stepChipClass(task) {
  const s = String(task?.status || '').toLowerCase()
  if (['completed', 'success', 'finished'].includes(s)) return 'bg-emerald-50 text-emerald-700'
  if (['failed', 'error', 'cancelled', 'canceled'].includes(s)) return 'bg-rose-50 text-rose-700'
  if (['processing', 'running'].includes(s)) return 'bg-amber-50 text-amber-700'
  if (['waiting_manual', 'waiting_retry', 'pending', 'paused'].includes(s)) return 'bg-slate-100 text-slate-500'
  return 'bg-slate-50 text-slate-500'
}

function formatRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const match = text.match(/[RVB]J\s*(\d{4,})/i)
  return match ? `RJ${match[1]}` : text
}
</script>

<style scoped>
.dash-fade-up {
  animation: dash-fade-up 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) both;
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
