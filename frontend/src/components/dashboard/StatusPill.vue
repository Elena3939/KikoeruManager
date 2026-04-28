<template>
  <span
    class="inline-flex h-[18px] flex-shrink-0 items-center gap-1 rounded-full border px-1.5 text-[10px] font-medium tracking-tight transition-all duration-300"
    :class="pillClass"
  >
    <span class="h-1.5 w-1.5 flex-shrink-0 rounded-full" :class="dotClass" />
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
  label: { type: String, default: '' },
})

const pillClass = computed(() => {
  const label = String(props.label || '').trim()
  if (label === '重试中') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (label === '已解决') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
})

const dotClass = computed(() => {
  const s = String(props.status || '').toLowerCase()
  const label = String(props.label || '').trim()
  if (label === '重试中') return 'bg-emerald-500 animate-pulse'
  if (label === '已解决') return 'bg-emerald-500'
  if (['completed', 'success', 'finished'].includes(s)) return 'bg-emerald-500'
  if (['failed', 'error', 'cancelled', 'canceled'].includes(s)) return 'bg-rose-500'
  if (['processing', 'running'].includes(s)) return 'bg-amber-500 animate-pulse'
  if (['waiting_manual', 'waiting_retry', 'pending'].includes(s)) return 'bg-indigo-500'
  if (s === 'paused') return 'bg-slate-400'
  return 'bg-slate-400'
})
</script>
