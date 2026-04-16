<template>
  <article class="workbench-card">
    <div class="workbench-card-head">
      <div class="workbench-card-copy">
        <div class="workbench-card-title">{{ workbench.title || '后台工作台' }}</div>
        <div v-if="workbench.summary?.subtitle" class="workbench-card-subtitle">{{ workbench.summary.subtitle }}</div>
      </div>
      <div class="workbench-card-status" :class="statusToneClass">
        <span v-if="progressLabel">{{ progressLabel }}</span>
        <span v-else>{{ workbench.status?.label || '运行中' }}</span>
      </div>
    </div>

    <el-progress
      v-if="showProgress"
      :percentage="Number(workbench.progress?.percentage || 0)"
      :status="progressStatus || undefined"
      :stroke-width="8"
      :show-text="false"
      class="workbench-card-progress"
    />

    <div v-if="workbench.metrics?.length" class="workbench-card-metrics">
      <span
        v-for="metric in workbench.metrics"
        :key="metric.key || metric.label"
        class="workbench-card-chip"
        :class="metricToneClass(metric)"
      >
        {{ metric.label }} {{ metric.value }}
      </span>
    </div>

    <div class="workbench-card-text">
      {{ workbench.summary?.text || workbench.progress?.label || workbench.status?.label || '后台任务正在运行。' }}
    </div>

    <div class="workbench-card-actions">
      <el-button
        v-for="action in normalizedActions"
        :key="action"
        size="small"
        :type="action === 'resume' ? 'primary' : 'default'"
        @click="emit('action', action)"
      >
        {{ getActionLabel(action) }}
      </el-button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  workbench: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['action'])

const normalizedActions = computed(() => (
  Array.isArray(props.workbench?.actions) ? props.workbench.actions.filter(Boolean) : []
))

const showProgress = computed(() => Number(props.workbench?.progress?.percentage || 0) > 0)
const progressStatus = computed(() => String(props.workbench?.progress?.status || '').trim())
const progressLabel = computed(() => String(props.workbench?.progress?.label || '').trim())
const statusToneClass = computed(() => `tone-${String(props.workbench?.status?.tone || 'neutral')}`)

function getActionLabel(action) {
  if (action === 'resume') return '恢复'
  if (action === 'close') return '关闭'
  if (action === 'cancel') return '取消'
  if (action === 'stop') return '停止'
  if (action === 'dismiss') return '收起'
  return action
}

function metricToneClass(metric = {}) {
  return `tone-${String(metric.tone || 'neutral')}`
}
</script>

<style scoped>
.workbench-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid rgba(211, 220, 232, 0.92);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(246, 249, 253, 0.98) 100%);
  box-shadow: 0 18px 46px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(20px);
}

.workbench-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.workbench-card-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.workbench-card-title {
  font-size: 15px;
  font-weight: 700;
  color: #152033;
}

.workbench-card-subtitle {
  font-size: 12px;
  color: #607086;
  line-height: 1.45;
}

.workbench-card-status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid transparent;
}

.workbench-card-progress {
  margin-top: -2px;
}

.workbench-card-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.workbench-card-chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
}

.workbench-card-text {
  font-size: 13px;
  line-height: 1.6;
  color: #314053;
}

.workbench-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tone-neutral {
  color: #556476;
  background: #f4f7fb;
  border-color: #e3e9f1;
}

.tone-info {
  color: #245da8;
  background: #edf4ff;
  border-color: #d6e6ff;
}

.tone-success {
  color: #24704a;
  background: #edf9f1;
  border-color: #d4eddc;
}

.tone-warning {
  color: #9c651b;
  background: #fff6e8;
  border-color: #f6ddb3;
}

.tone-danger {
  color: #b53a36;
  background: #fff1ef;
  border-color: #ffd7d2;
}
</style>
