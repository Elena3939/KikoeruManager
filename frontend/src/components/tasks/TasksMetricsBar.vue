<template>
  <section class="flex flex-shrink-0 flex-wrap gap-2 px-5 py-2">
    <el-button
      v-for="(metric, index) in metrics"
      :key="metric.key"
      class="tasks-metric-btn"
      :style="{ animationDelay: `${index * 40}ms` }"
      @click="metric.click?.()"
    >
      <component :is="metric.icon" :size="13" :stroke-width="2.2" :class="iconColor(metric.key)" />
      <span class="tasks-metric-label">{{ metric.label }}</span>
      <span class="tasks-metric-count">{{ metric.value }}</span>
    </el-button>
  </section>
</template>

<script setup>
defineProps({
  metrics: { type: Array, default: () => [] },
})

function iconColor(key) {
  if (key === 'processing') return 'text-amber-500'
  if (key === 'waiting_manual') return 'text-indigo-500'
  if (key === 'waiting_retry') return 'text-orange-500'
  if (key === 'failed') return 'text-rose-500'
  return 'text-slate-400'
}
</script>

<style scoped>
.tasks-metric-btn {
  --el-button-size: 28px;
  height: 28px;
  padding: 0 10px;
  margin: 0 !important;
  border-radius: 8px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
  color: rgb(51 65 85);
  font-size: 12px;
  font-weight: 500;
  gap: 6px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  animation: tasks-fade-up 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.tasks-metric-btn :deep(span),
.tasks-metric-btn :deep(> span) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tasks-metric-btn:hover {
  transform: translateY(-1px);
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  color: rgb(15 23 42);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}
.tasks-metric-btn:active {
  transform: translateY(0) scale(0.96);
}

.tasks-metric-label {
  font-weight: 600;
  letter-spacing: 0.01em;
}

.tasks-metric-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 16px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 4px;
  background: rgb(241 245 249);
  color: rgb(51 65 85);
  font-size: 10px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: all 0.3s ease;
}
.tasks-metric-btn:hover .tasks-metric-count {
  background: rgb(15 23 42);
  color: #fff;
}

@keyframes tasks-fade-up {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
