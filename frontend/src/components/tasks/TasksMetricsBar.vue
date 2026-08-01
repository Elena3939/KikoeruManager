<template>
  <section class="flex flex-shrink-0 flex-wrap gap-1.5 px-5 pt-3">
    <button
      v-for="(metric, index) in metrics"
      :key="metric.key"
      type="button"
      class="tasks-metric-pill"
      :style="{ animationDelay: `${index * 40}ms` }"
      @click="metric.click?.()"
    >
      <span class="tasks-metric-dot" :class="dotClass(metric.key)" />
      <span class="tasks-metric-label">{{ metric.label }}</span>
      <span class="tasks-metric-count">{{ metric.value }}</span>
    </button>
  </section>
</template>

<script setup>
defineProps({
  metrics: { type: Array, default: () => [] },
})

function dotClass(key) {
  if (key === 'processing') return 'bg-amber-500'
  if (key === 'waiting_manual') return 'bg-indigo-500'
  if (key === 'waiting_retry') return 'bg-orange-500'
  if (key === 'failed') return 'bg-rose-500'
  return 'bg-slate-400'
}
</script>

<style scoped>
/* 极简 pill：火底圆角 + 彩色 dot + 签名 + count */
.tasks-metric-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 28px;
  padding: 0 12px;
  border: 0;
  border-radius: 999px;
  background: rgb(241 245 249);
  color: rgb(71 85 105);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
  animation: tasks-fade-up 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.tasks-metric-pill:hover {
  background: rgb(226 232 240);
  color: rgb(15 23 42);
}
.tasks-metric-pill:active {
  transform: scale(0.97);
}

.tasks-metric-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex-shrink: 0;
}

.tasks-metric-label {
  font-weight: 500;
  letter-spacing: 0.01em;
}

.tasks-metric-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.22);
  color: rgb(71 85 105);
  font-size: 10.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: color 0.2s ease, background-color 0.2s ease;
}
.tasks-metric-pill:hover .tasks-metric-count {
  background: rgba(15, 23, 42, 0.9);
  color: #fff;
}

@keyframes tasks-fade-up {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
