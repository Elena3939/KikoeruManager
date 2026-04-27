<template>
  <section
    class="rounded-[10px] border border-slate-200/80 bg-white p-2 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_4px_12px_-8px_rgba(15,23,42,0.14)]"
    data-section="dashboard-status"
  >
    <header class="mb-1.5 flex items-center justify-between gap-2">
      <h2 class="m-0 text-[11.5px] font-bold tracking-tight text-slate-900 leading-none">
        状态
        <span class="ml-1 text-[9.5px] font-medium text-slate-400">队列摘要</span>
      </h2>
      <Activity :size="11" :stroke-width="2.3" class="text-slate-400 animate-pulse" />
    </header>

    <div class="flex flex-col gap-1">
      <div
        v-for="(item, index) in cards"
        :key="item.key"
        class="dash-fade-up group flex items-center justify-between gap-2 rounded-[6px] border border-slate-200 bg-white px-2 py-1 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_3px_8px_-5px_rgba(15,23,42,0.16)]"
        :style="{ animationDelay: `${index * 35}ms` }"
      >
        <div class="flex items-center gap-1.5 min-w-0 text-[10.5px] font-medium text-slate-700">
          <component :is="iconFor(item.key)" :size="11" :stroke-width="2.3" :class="iconColor(item.key)" />
          <span class="truncate">{{ item.label }}</span>
        </div>
        <b class="text-[12px] font-bold tabular-nums leading-none" :class="item.value > 0 && item.key === 'failed' ? 'text-rose-600' : 'text-blue-600'">{{ item.value }}</b>
      </div>
    </div>
  </section>
</template>

<script setup>
import { Activity, PauseCircle, RotateCcw, XCircle } from 'lucide-vue-next'

defineProps({
  cards: { type: Array, default: () => [] },
})

const ICON_MAP = {
  processing: Activity,
  waiting: PauseCircle,
  retry: RotateCcw,
  failed: XCircle,
}

function iconFor(key) {
  return ICON_MAP[key] || Activity
}

function iconColor(key) {
  if (key === 'processing') return 'text-amber-600'
  if (key === 'waiting') return 'text-indigo-600'
  if (key === 'retry') return 'text-orange-600'
  if (key === 'failed') return 'text-rose-600'
  return 'text-slate-500'
}
</script>

<style scoped>
.dash-fade-up {
  animation: dash-fade-up 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
@keyframes dash-fade-up {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
