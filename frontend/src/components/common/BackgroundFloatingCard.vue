<template>
  <article
    v-if="!persistentDismissed"
    ref="cardRef"
    class="floating-card background-floating-card task-toast"
    :class="[toneClass, { 'is-hosted': hosted, 'is-completed': completed, 'is-problem': hasProblem, 'is-collapsed': collapsed }]"
    :style="cardStyle"
    role="region"
    :aria-label="title"
  >
    <div v-if="collapsed" class="task-toast-mini" @pointerdown="startDrag">
      <button
        type="button"
        class="task-toast-mini-expand"
        :aria-label="`展开${title}，进度 ${progressPercentText}`"
        :title="`${title} · ${progressPercentText}，点击展开`"
        @click="collapsed = false"
      >
        <span class="task-toast-mini-logo" aria-hidden="true">
          <DotLottieVue v-if="completed" :src="successAnimation || defaultSuccessAnimation" :autoplay="true" :loop="false" />
          <component :is="resolvedHeroIcon" v-else :size="16" :stroke-width="2" />
        </span>
        <span class="task-toast-mini-name">{{ title }}</span>
        <span class="task-toast-mini-track" role="progressbar" :aria-valuenow="completed ? 100 : safePercentage" aria-valuemin="0" aria-valuemax="100" :aria-label="title">
          <span :style="{ width: `${completed ? 100 : safePercentage}%` }" />
        </span>
      </button>
      <strong class="task-toast-mini-percent">{{ completed ? '100%' : progressPercentText }}</strong>
      <GripHorizontal class="task-toast-mini-grip" :size="14" aria-hidden="true" />
    </div>
    <template v-else>
      <header class="task-toast-head" title="拖动以移动小窗" @pointerdown="startDrag">
        <div class="task-toast-icon" :class="{ 'is-success': completed }">
          <DotLottieVue v-if="completed" class="task-toast-success-animation" :src="successAnimation || defaultSuccessAnimation" :autoplay="true" :loop="false" />
          <component :is="resolvedHeroIcon" v-else :size="18" :stroke-width="2.1" />
        </div>
        <div class="task-toast-heading">
          <h3 :title="title">{{ title }}</h3>
          <p v-if="subtitle" :title="subtitle">{{ subtitle }}</p>
        </div>
        <button class="task-toast-collapse task-toast-close" type="button" aria-label="仅显示进度条" title="仅显示进度条" @click="collapsed = true"><Minus :size="17" /></button>
        <button v-if="dismissAction" class="task-toast-close task-toast-dismiss" type="button" :aria-label="dismissAction.label" :title="dismissAction.label" @click="emit('action', dismissAction.key)"><X :size="17" /></button>
      </header>
      <div class="task-toast-body">
        <div v-if="!completed" class="task-toast-progress-row">
          <div class="task-toast-progress" role="progressbar" aria-label="任务进度" :aria-valuenow="safePercentage" aria-valuemin="0" aria-valuemax="100">
            <span :style="{ width: `${safePercentage}%` }" />
          </div>
          <strong>{{ progressPercentText }}</strong>
        </div>
        <div class="task-toast-footer">
          <div class="task-toast-info" :title="[badgeText, metaText, detailText].filter(Boolean).join(' · ')">
            <div v-if="visibleMetrics.length" class="task-toast-metrics">
              <span v-for="metric in visibleMetrics" :key="metric.key" :class="`metric-${metric.tone}`" :title="`${metric.label} ${metric.value}`">
                <component v-if="metric.icon" :is="metric.icon" :size="12" />
                {{ metric.label }} <b>{{ metric.value }}</b>
              </span>
            </div>
            <span v-if="metaText" class="task-toast-context task-toast-meta">{{ metaText }}</span>
            <span v-else-if="!visibleMetrics.length" class="task-toast-context">{{ detailText || badgeText }}</span>
          </div>
          <div v-if="bodyActions.length" class="task-toast-actions">
            <button v-for="action in bodyActions" :key="action.key" type="button" :class="['task-toast-action', { 'is-primary': action.key === 'resume' }]" :title="action.label" @click="emit('action', action.key)">
              <component v-if="action.icon" :is="action.icon" :size="12" />{{ action.key === 'resume' && action.label === '恢复工作台' ? '打开' : action.label }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </article>
</template>

<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'
import { useRoute } from 'vue-router'
import { mountedTaskCards, persistentTaskCards, dismissPersistentTaskCard } from '../../composables/usePersistentTaskCards'
import { useFloatingCardDrag } from '../../composables/useFloatingCardDrag'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import defaultSuccessAnimation from '../../assets/anime/success confetti.lottie?url'
import {
  GripHorizontal,
  Minus,
  BarChart3,
  Captions,
  CheckSquare,
  Clock,
  CloudDownload,
  Download,
  ListTodo,
  RefreshCw,
  Timer,
  Trash2,
  Upload,
  X
} from 'lucide-vue-next'
const props = defineProps({
  taskIds: { type: Array, default: () => [] },
  taskSource: { type: String, default: '' },
  persistentReplica: { type: Boolean, default: false },
  positionKey: { type: String, default: '' },
  title: { type: String, default: '后台任务正在运行' },
  subtitle: { type: String, default: '' },
  metaText: { type: String, default: '' },
  detailText: { type: String, default: '' },
  badgeText: { type: String, default: '' },
  kind: { type: String, default: 'upload' },
  tone: { type: String, default: 'primary' },
  percentage: { type: Number, default: 0 },
  completed: { type: Boolean, default: false },
  hosted: { type: Boolean, default: false },
  stackIndex: { type: Number, default: 0 },
  heroAnimation: { type: String, default: '' },
  progressAnimation: { type: String, default: '' },
  successAnimation: { type: String, default: '' },
  progressKey: { type: String, default: '' },
  heroIcon: { type: [Object, Function, String], default: null },
  primaryActionIcon: { type: [Object, Function, String], default: null },
  metrics: { type: Array, default: () => [] },
  actions: { type: Array, default: () => [] }
})

const emitAction = defineEmits(['action'])
function emit(event, action) {
  if (['close', 'dismiss'].includes(action) && props.taskSource) dismissPersistentTaskCard(persistentId.value)
  emitAction(event, action)
}
const ownerRoute = useRoute()
const ownerPath = ownerRoute?.path || '/tasks'
const persistentId = computed(() => props.positionKey || `${ownerPath}:${props.taskSource}:${props.kind}`)
const persistentDismissed = computed(() => props.taskSource && persistentTaskCards[persistentId.value]?.dismissed)
onMounted(() => { if (!props.persistentReplica && props.taskSource) mountedTaskCards.add(persistentId.value) })
onBeforeUnmount(() => { if (!props.persistentReplica) mountedTaskCards.delete(persistentId.value) })
onActivated(() => { if (!props.persistentReplica && props.taskSource) mountedTaskCards.add(persistentId.value) })
onDeactivated(() => { if (!props.persistentReplica) mountedTaskCards.delete(persistentId.value) })

const toneClass = computed(() => `floating-card-tone-${normalizeTone(props.tone)}`)

const cardStyle = computed(() => {
  const index = Math.max(0, Number(props.stackIndex || 0))
  if (props.hosted || index <= 0) return undefined
  return {
    bottom: `calc(20px + ${index} * 176px)`
  }
})

const heroIconMap = {
  upload: Upload,
  download: Download,
  asmr: CloudDownload,
  subtitle: Captions,
  delete: Trash2,
  generic: Upload
}

const resolvedKind = computed(() => {
  const kind = String(props.kind || 'generic').trim().toLowerCase()
  return heroIconMap[kind] ? kind : 'generic'
})

const resolvedHeroIcon = computed(() => props.heroIcon || heroIconMap[resolvedKind.value] || Upload)
const safePercentage = computed(() => Math.max(0, Math.min(100, Number(props.percentage || 0))))
const progressPercentText = computed(() => `${Math.round(safePercentage.value)}%`)
const normalizedMetrics = computed(() => props.metrics
  .filter(Boolean)
  .map((metric, index) => {
    const key = String(metric.key || metric.label || index)
    const tone = normalizeMetricTone(metric.tone || key)
    return {
      key,
      label: String(metric.label ?? ''),
      value: metric.value === undefined || metric.value === null ? '' : String(metric.value),
      tone,
      icon: metric.icon || getMetricIcon(metric.iconKey || key, tone),
      iconClass: metric.iconClass || getMetricIconClass(tone, key)
    }
  })
  .filter(metric => metric.label || metric.value !== '')
)

const hasProblem = computed(() => {
  const tone = normalizeTone(props.tone)
  if (tone === 'rose') return true
  return normalizedMetrics.value.some((metric) => {
    if (metric.tone !== 'danger') return false
    const value = Number(metric.value)
    return Number.isFinite(value) ? value > 0 : Boolean(metric.value)
  })
})

const normalizedActions = computed(() => props.actions
  .filter(Boolean)
  .map((action) => {
    const key = String(action.key || action.action || action).trim()
    const variant = normalizeTone(action.variant || (key === 'resume' ? props.tone : 'ghost'))
    return {
      key,
      label: String(action.label || getActionLabel(key)),
      icon: action.icon === false ? null : (action.icon || getActionIcon(key, variant)),
      className: getActionClass(variant)
    }
  })
  .filter(action => action.key)
)

// 折叠只影响呈现，任务与原有操作状态继续保留。
const collapsed = ref(false)
watch(() => props.positionKey || props.kind, key => {
  try { collapsed.value = localStorage.getItem(`kikoerumanager.ui.floatingCollapsed.${key}`) === 'true' } catch (_) {}
}, { immediate: true })
watch(collapsed, value => {
  try { localStorage.setItem(`kikoerumanager.ui.floatingCollapsed.${props.positionKey || props.kind}`, String(value)) } catch (_) {}
})
const visibleMetrics = computed(() => normalizedMetrics.value.filter(metric => {
  const value = metric.value.trim()
  if (!value || /^[-—–]+$/.test(value)) return false
  const count = Number(value)
  return !Number.isFinite(count) || count > 0
}))
const cardRef = ref(null)
const { startDrag } = useFloatingCardDrag(cardRef, () => props.positionKey || props.kind, () => props.stackIndex)
const dismissAction = computed(() => normalizedActions.value.find(action => ['dismiss', 'close'].includes(action.key)))
const bodyActions = computed(() => normalizedActions.value.filter(action => action !== dismissAction.value))

function normalizeTone(value) {
  const tone = String(value || '').trim().toLowerCase()
  if (['primary', 'blue', 'info'].includes(tone)) return 'primary'
  if (['emerald', 'success', 'green'].includes(tone)) return 'emerald'
  if (['violet', 'purple', 'asmr'].includes(tone)) return 'violet'
  if (['amber', 'warning', 'orange'].includes(tone)) return 'amber'
  if (['rose', 'danger', 'red', 'delete'].includes(tone)) return 'rose'
  return tone || 'primary'
}

function normalizeMetricTone(value) {
  const tone = String(value || '').trim().toLowerCase()
  if (['processing', 'progress', 'info', 'blue', 'primary'].includes(tone)) return 'info'
  if (['pending', 'waiting', 'warning', 'amber', 'clock'].includes(tone)) return 'warning'
  if (['completed', 'complete', 'success', 'emerald', 'matched'].includes(tone)) return 'success'
  if (['failed', 'failure', 'danger', 'rose', 'error'].includes(tone)) return 'danger'
  if (['speed', 'rate', 'indigo'].includes(tone)) return 'indigo'
  if (['eta', 'time', 'timer', 'violet'].includes(tone)) return 'violet'
  return 'neutral'
}

function getMetricIcon(key, tone) {
  const normalized = String(key || '').trim().toLowerCase()
  if (['processing', 'progress', 'running'].includes(normalized)) return RefreshCw
  if (['pending', 'waiting', 'queued'].includes(normalized)) return ListTodo
  if (['all', 'total', 'task', 'tasks', 'status'].includes(normalized)) return ListTodo
  if (['scan', 'scanned', 'selected', 'hit', 'hits'].includes(normalized)) return CheckSquare
  if (['rules', 'rule', 'directory', 'folder', 'size'].includes(normalized)) return BarChart3
  if (['completed', 'complete', 'success', 'matched'].includes(normalized)) return CheckSquare
  if (['failed', 'failure', 'danger', 'error'].includes(normalized)) return X
  if (['speed', 'rate'].includes(normalized)) return BarChart3
  if (['eta', 'time', 'timer'].includes(normalized)) return Timer
  if (['delete', 'deleted', 'trash'].includes(normalized)) return Trash2
  if (tone === 'warning') return Clock
  if (tone === 'success') return CheckSquare
  if (tone === 'danger') return X
  if (tone === 'indigo') return BarChart3
  if (tone === 'violet') return Timer
  return null
}

function getMetricIconClass(tone, key = '') {
  const normalizedKey = String(key || '').trim().toLowerCase()
  if (['all', 'total', 'task', 'tasks', 'status'].includes(normalizedKey)) return 'chip-slate'
  if (['processing', 'progress', 'running'].includes(normalizedKey)) return 'chip-blue'
  if (['pending', 'waiting', 'queued'].includes(normalizedKey)) return 'chip-amber'
  if (['completed', 'complete', 'success', 'matched', 'scan', 'scanned'].includes(normalizedKey)) return 'chip-cyan'
  if (['failed', 'failure', 'danger', 'error'].includes(normalizedKey)) return 'chip-rose'
  if (['speed', 'rate', 'rules', 'rule'].includes(normalizedKey)) return 'chip-indigo'
  if (['eta', 'time', 'timer', 'directory', 'folder'].includes(normalizedKey)) return 'chip-violet'
  if (['delete', 'deleted', 'trash', 'selected', 'hit', 'hits', 'size'].includes(normalizedKey)) return 'chip-amber'
  if (tone === 'info') return 'chip-blue'
  if (tone === 'warning') return 'chip-amber'
  if (tone === 'success') return 'chip-cyan'
  if (tone === 'danger') return 'chip-rose'
  if (tone === 'indigo') return 'chip-indigo'
  if (tone === 'violet') return 'chip-violet'
  return 'chip-slate'
}

function getActionLabel(action) {
  if (action === 'resume') return '恢复工作台'
  if (action === 'close') return '关闭'
  if (action === 'cancel') return '取消'
  if (action === 'stop') return '停止'
  if (action === 'dismiss') return '收起'
  return action
}

function getActionIcon(action, variant) {
  if (action === 'resume') return props.primaryActionIcon || heroIconMap[resolvedKind.value] || Upload
  if (action === 'cancel' || action === 'stop' || variant === 'rose') return X
  return null
}

function getActionClass(variant) {
  if (variant === 'primary') return 'floating-action-btn-primary'
  if (variant === 'emerald') return 'floating-action-btn-emerald'
  if (variant === 'violet') return 'floating-action-btn-violet'
  if (variant === 'amber') return 'floating-action-btn-amber'
  if (variant === 'rose') return 'floating-action-btn-rose'
  return ''
}

</script>
