<template>
  <BackgroundFloatingCard
    hosted
    :kind="cardKind"
    :tone="cardTone"
    :title="cardTitle"
    :subtitle="cardSubtitle"
    :meta-text="cardMetaText"
    :detail-text="cardDetailText"
    :badge-text="cardBadgeText"
    :percentage="progressPercent"
    :completed="cardCompleted"
    :metrics="cardMetrics"
    :actions="cardActions"
    :progress-key="`${workbench.id}-${cardCompleted ? 'done' : 'run'}`"
    @action="emit('action', $event)"
  />
</template>

<script setup>
import { computed } from 'vue'
import BackgroundFloatingCard from '../common/BackgroundFloatingCard.vue'

const props = defineProps({
  workbench: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['action'])

const progressPercent = computed(() => Math.max(0, Math.min(100, Number(props.workbench?.progress?.percentage || 0))))
const statusTone = computed(() => String(props.workbench?.status?.tone || 'neutral').trim().toLowerCase())
const statusKey = computed(() => String(props.workbench?.status?.key || '').trim().toLowerCase())

const cardKind = computed(() => {
  const type = String(props.workbench?.type || '').toLowerCase()
  if (type.includes('subtitle')) return 'subtitle'
  if (type.includes('upload')) return 'upload'
  if (type.includes('download')) return 'download'
  if (type.includes('delete')) return 'delete'
  return 'generic'
})

const cardTone = computed(() => {
  const type = String(props.workbench?.type || '').toLowerCase()
  if (type.includes('subtitle')) return 'emerald'
  if (type.includes('asmr')) return 'violet'
  if (statusTone.value === 'success') return 'emerald'
  if (statusTone.value === 'warning') return 'amber'
  if (statusTone.value === 'danger') return 'rose'
  return cardKind.value === 'upload' ? 'emerald' : 'primary'
})

const cardCompleted = computed(() => (
  progressPercent.value >= 100
  || statusTone.value === 'success'
  || statusKey.value === 'success'
  || statusKey.value === 'completed'
))

const baseTitle = computed(() => String(props.workbench?.title || '后台工作台').trim())

const cardTitle = computed(() => {
  if (cardCompleted.value) return `${baseTitle.value}已完成`
  if (statusTone.value === 'danger' || statusKey.value === 'failed') return `${baseTitle.value}需要处理`
  return `${baseTitle.value}正在后台运行`
})

const cardSubtitle = computed(() => (
  String(props.workbench?.summary?.subtitle || '').trim()
  || '保留当前队列与工作台上下文'
))

const cardMetaText = computed(() => {
  const label = String(props.workbench?.status?.label || '').trim()
  return label ? `状态: ${label}` : ''
})

const cardDetailText = computed(() => (
  String(props.workbench?.summary?.text || props.workbench?.progress?.label || props.workbench?.status?.label || '').trim()
  || '隐藏后继续保留任务队列、轮询和当前焦点。'
))

const cardBadgeText = computed(() => {
  const label = String(props.workbench?.status?.label || '').trim()
  if (label) return label
  if (progressPercent.value > 0) return `${progressPercent.value}%`
  return ''
})

const cardMetrics = computed(() => (
  Array.isArray(props.workbench?.metrics)
    ? props.workbench.metrics.map(metric => ({
      key: metric.key || metric.label,
      label: metric.label,
      value: metric.value,
      tone: metric.tone || metric.key
    }))
    : []
))

const cardActions = computed(() => (
  normalizedActions.value.map(action => ({
    key: action,
    label: getActionLabel(action),
    variant: action === 'resume' ? cardTone.value : action === 'cancel' || action === 'stop' ? 'rose' : 'ghost'
  }))
))

const normalizedActions = computed(() => (
  Array.isArray(props.workbench?.actions) ? props.workbench.actions.filter(Boolean).map(item => String(item)) : []
))

function getActionLabel(action) {
  if (action === 'resume') return '恢复工作台'
  if (action === 'close') return '关闭'
  if (action === 'cancel') return '取消'
  if (action === 'stop') return '停止'
  if (action === 'dismiss') return '收起'
  return action
}
</script>
