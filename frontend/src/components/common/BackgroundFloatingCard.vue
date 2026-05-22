<template>
  <article
    class="floating-card floating-card-upload background-floating-card"
    :class="[toneClass, { 'is-hosted': hosted }]"
    :style="cardStyle"
  >
    <div class="upload-floating-head">
      <div class="flex min-w-0 items-center gap-2.5 pr-2">
        <div class="floating-hero-icon">
          <DotLottieVue
            v-if="resolvedHeroAnimation"
            :src="resolvedHeroAnimation"
            autoplay
            loop
            background="transparent"
            class="floating-hero-lottie"
          />
          <component
            :is="resolvedHeroIcon"
            v-else
            class="floating-hero-static-icon"
            :stroke-width="2.25"
          />
        </div>

        <div class="min-w-0">
          <div class="flex items-center gap-1.5 text-[13px] font-semibold leading-tight text-slate-900">
            <span class="upload-floating-title">{{ title }}</span>
            <span v-if="badgeText" class="floating-chip floating-chip-title">{{ badgeText }}</span>
          </div>

          <div v-if="subtitle" class="mt-0.5 break-all text-[11px] leading-snug text-slate-500">
            {{ subtitle }}
          </div>

          <div v-if="metaText" class="mt-1 text-[11px] font-medium leading-none text-slate-400">
            {{ metaText }}
          </div>
        </div>
      </div>
    </div>

    <DotLottieVue
      v-if="completed"
      :src="successAnimationSrc"
      autoplay
      loop
      :render-config="{ autoResize: true, devicePixelRatio: 2 }"
      background="transparent"
      class="floating-progress-lottie floating-progress-lottie-success"
    />

    <DotLottieVue
      v-else
      ref="progressLottieRef"
      :key="progressLottieKey"
      :src="progressAnimationSrc"
      :autoplay="false"
      :loop="false"
      :render-config="{ autoResize: true, devicePixelRatio: 2 }"
      background="transparent"
      class="floating-progress-lottie floating-progress-lottie-progress"
    />

    <div v-if="normalizedMetrics.length" class="floating-chip-row-compact">
      <span
        v-for="metric in normalizedMetrics"
        :key="metric.key"
        class="floating-chip"
        :class="{ 'floating-chip-danger': metric.tone === 'danger' }"
      >
        <component
          :is="metric.icon"
          v-if="metric.icon"
          class="floating-chip-icon"
          :class="metric.iconClass"
          :stroke-width="2.2"
        />
        <span>{{ metric.label }}</span>
        <b v-if="metric.value !== ''">{{ metric.value }}</b>
      </span>
    </div>

    <div v-if="detailText" class="floating-detail-box">
      {{ detailText }}
    </div>

    <div v-if="normalizedActions.length" class="floating-actions-row">
      <button
        v-for="action in normalizedActions"
        :key="action.key"
        type="button"
        class="floating-action-btn group"
        :class="action.className"
        @click="emit('action', action.key)"
      >
        <component
          :is="action.icon"
          v-if="action.icon"
          class="h-3 w-3 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:rotate-[-6deg]"
          :stroke-width="2.3"
        />
        {{ action.label }}
      </button>
    </div>
  </article>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import {
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
import uploadToCloudAnimation from '../../assets/anime/Uploading to cloud.lottie'
import downloadAnimation from '../../assets/anime/download icon.lottie'
import progressAnimation from '../../assets/anime/Loading Bar  Progress Bar.lottie'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'
import translateAnimation from '../../assets/anime/Translate.lottie'
import deleteAnimation from '../../assets/anime/Delete icon animation.lottie'

const props = defineProps({
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

const emit = defineEmits(['action'])

const toneClass = computed(() => `floating-card-tone-${normalizeTone(props.tone)}`)

const cardStyle = computed(() => {
  const index = Math.max(0, Number(props.stackIndex || 0))
  if (props.hosted || index <= 0) return undefined
  return {
    bottom: `calc(20px + ${index} * 176px)`
  }
})

const heroAnimationMap = {
  upload: uploadToCloudAnimation,
  download: downloadAnimation,
  asmr: downloadAnimation,
  subtitle: translateAnimation,
  delete: deleteAnimation,
  generic: uploadToCloudAnimation
}

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
  return heroAnimationMap[kind] ? kind : 'generic'
})

const resolvedHeroAnimation = computed(() => props.heroAnimation || heroAnimationMap[resolvedKind.value] || '')
const resolvedHeroIcon = computed(() => props.heroIcon || heroIconMap[resolvedKind.value] || Upload)
const progressAnimationSrc = computed(() => props.progressAnimation || progressAnimation)
const successAnimationSrc = computed(() => props.successAnimation || successConfettiAnimation)
const safePercentage = computed(() => Math.max(0, Math.min(100, Number(props.percentage || 0))))
const progressLottieKey = computed(() => props.progressKey || `${resolvedKind.value}-${props.completed ? 'done' : 'run'}`)

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

const progressLottieRef = ref(null)
const progressLottieInstance = ref(null)
const animatedFrame = ref(0)
const targetFrame = ref(0)
let frameRaf = null

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

function cancelFrameAnimation() {
  if (!frameRaf) return
  window.cancelAnimationFrame(frameRaf)
  frameRaf = null
}

function getProgressLottieInstance() {
  return progressLottieRef.value?.getDotLottieInstance?.() || null
}

function unbindProgressLottieListeners() {
  cancelFrameAnimation()
  const instance = progressLottieInstance.value
  if (!instance) return
  instance.removeEventListener?.('ready', syncProgressLottieFrame)
  instance.removeEventListener?.('load', syncProgressLottieFrame)
  progressLottieInstance.value = null
}

function bindProgressLottieListeners() {
  const instance = getProgressLottieInstance()
  if (!instance || progressLottieInstance.value === instance) return
  unbindProgressLottieListeners()
  progressLottieInstance.value = instance
  instance.addEventListener?.('ready', syncProgressLottieFrame)
  instance.addEventListener?.('load', syncProgressLottieFrame)
}

async function syncProgressLottieFrame() {
  if (props.completed) return
  const instance = getProgressLottieInstance()
  if (!instance) return

  const totalFrames = Number(instance.totalFrames || instance.total_frames || 0)
  if (!Number.isFinite(totalFrames) || totalFrames <= 1) return

  const frame = Math.floor((Math.min(safePercentage.value, 99) / 100) * (totalFrames - 1))
  targetFrame.value = frame

  try {
    await instance.setLoop?.(false)
    await instance.pause?.()
    if (!Number.isFinite(animatedFrame.value)) animatedFrame.value = frame
    if (Math.abs(animatedFrame.value - frame) < 0.5) {
      animatedFrame.value = frame
      await instance.setFrame?.(frame)
      return
    }
    cancelFrameAnimation()
    const animate = async () => {
      const nextFrame = animatedFrame.value + ((targetFrame.value - animatedFrame.value) * 0.18)
      if (Math.abs(targetFrame.value - nextFrame) < 0.35) {
        animatedFrame.value = targetFrame.value
        frameRaf = null
        try {
          await instance.setFrame?.(Math.round(animatedFrame.value))
        } catch {
          // 动画实例切换时可能还没就绪，忽略这类瞬时错误。
        }
        return
      }
      animatedFrame.value = nextFrame
      try {
        await instance.setFrame?.(Math.round(animatedFrame.value))
      } catch {
        frameRaf = null
        return
      }
      frameRaf = window.requestAnimationFrame(() => {
        animate()
      })
    }
    frameRaf = window.requestAnimationFrame(() => {
      animate()
    })
  } catch {
    // 动画实例切换时可能还没就绪，忽略这类瞬时错误。
  }
}

watch([safePercentage, () => props.completed, progressLottieRef], () => {
  if (props.completed) {
    cancelFrameAnimation()
    return
  }
  nextTick(() => {
    bindProgressLottieListeners()
    syncProgressLottieFrame()
  })
}, { immediate: true })

watch(progressAnimationSrc, () => {
  animatedFrame.value = 0
  targetFrame.value = 0
  nextTick(() => {
    bindProgressLottieListeners()
    syncProgressLottieFrame()
  })
})

onBeforeUnmount(() => {
  unbindProgressLottieListeners()
})
</script>

<style scoped>
.background-floating-card.is-hosted {
  position: relative;
  right: auto;
  bottom: auto;
  width: 100%;
  z-index: auto;
}

.floating-hero-static-icon {
  width: 18px;
  height: 18px;
}

.background-floating-card.floating-card-tone-emerald .floating-chip-title {
  color: #0369a1;
  border-color: #bae6fd;
  background: #f0f9ff;
}

.background-floating-card.floating-card-tone-violet .floating-chip-title {
  color: #6d28d9;
  border-color: #ddd6fe;
  background: #f5f3ff;
}

.background-floating-card.floating-card-tone-amber .floating-chip-title {
  color: #b45309;
  border-color: #fde68a;
  background: #fffbeb;
}

.background-floating-card.floating-card-tone-rose .floating-chip-title {
  color: #be123c;
  border-color: #fecdd3;
  background: #fff1f2;
}

.floating-action-btn-violet {
  border-color: transparent;
  color: #fff;
  background: linear-gradient(180deg, #a78bfa 0%, #7c3aed 52%, #5b21b6 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.34), 0 4px 10px rgba(124, 58, 237, 0.20), 0 0 0 1px rgba(124, 58, 237, 0.10);
}

.floating-action-btn-violet:hover {
  color: #fff;
  background: linear-gradient(180deg, #c4b5fd 0%, #7c3aed 48%, #4c1d95 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38), 0 6px 14px rgba(124, 58, 237, 0.24), 0 0 0 1px rgba(124, 58, 237, 0.12);
}

.floating-action-btn-amber {
  border-color: transparent;
  color: #fff;
  background: linear-gradient(180deg, #fbbf24 0%, #d97706 52%, #b45309 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.34), 0 4px 10px rgba(217, 119, 6, 0.20), 0 0 0 1px rgba(217, 119, 6, 0.10);
}

.floating-action-btn-amber:hover {
  color: #fff;
  background: linear-gradient(180deg, #fcd34d 0%, #d97706 48%, #92400e 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38), 0 6px 14px rgba(217, 119, 6, 0.24), 0 0 0 1px rgba(217, 119, 6, 0.12);
}

.floating-action-btn-rose {
  border-color: transparent;
  color: #fff;
  background: linear-gradient(180deg, #fb7185 0%, #e11d48 52%, #be123c 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.34), 0 4px 10px rgba(225, 29, 72, 0.20), 0 0 0 1px rgba(225, 29, 72, 0.10);
}

.floating-action-btn-rose:hover {
  color: #fff;
  background: linear-gradient(180deg, #fda4af 0%, #e11d48 48%, #9f1239 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38), 0 6px 14px rgba(225, 29, 72, 0.24), 0 0 0 1px rgba(225, 29, 72, 0.12);
}
</style>
