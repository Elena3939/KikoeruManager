<template>
  <button
    v-bind="buttonAttrs"
    :type="buttonType"
    :class="buttonClasses"
    :disabled="disabled"
    :aria-busy="running ? 'true' : undefined"
    :data-state="buttonState"
    @click="handleClick"
  >
    <span class="stateful-button__content">
      <span
        v-if="showDefaultIcons || $slots.prefix || $slots.loading || $slots.success || $slots.error"
        class="stateful-button__state"
        :class="`is-${buttonState}`"
        :data-state="buttonState"
        aria-hidden="true"
      >
        <slot name="prefix" :state="buttonState" :loading="loaderVisible" :success="checkVisible" :error="errorVisible">
          <span
            v-if="showDefaultIcons || $slots.loading"
            class="stateful-button__icon stateful-button__icon--loader"
            :class="{ 'is-visible': loaderVisible }"
          >
            <slot name="loading">
              <Loader2 :size="20" :stroke-width="2.25" />
            </slot>
          </span>
          <span
            v-if="showDefaultIcons || $slots.success"
            class="stateful-button__icon stateful-button__icon--check"
            :class="{ 'is-visible': checkVisible }"
          >
            <slot name="success">
              <Check :size="20" :stroke-width="2.5" />
            </slot>
          </span>
        </slot>
      </span>
      <span class="stateful-button__label">
        <slot />
      </span>
    </span>
  </button>
</template>

<script setup>
import { computed, ref, useAttrs } from 'vue'
import { Check, Loader2 } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

defineOptions({
  inheritAttrs: false,
})

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
  tone: {
    type: String,
    default: 'primary',
    validator: (value) => ['primary', 'neutral', 'success', 'warning', 'danger', 'violet', 'sky'].includes(value),
  },
  size: {
    type: String,
    default: 'default',
    validator: (value) => ['sm', 'default', 'lg'].includes(value),
  },
  successHold: {
    type: Number,
    default: 2000,
  },
  showDefaultIcons: {
    type: Boolean,
    default: true,
  },
  unstyled: {
    type: Boolean,
    default: false,
  },
})

const attrs = useAttrs()
const running = ref(false)
const loaderVisible = ref(false)
const checkVisible = ref(false)
const errorVisible = ref(false)
let sequenceId = 0

const toneClasses = {
  primary:
    'bg-slate-900 text-white ring-slate-900/20 shadow-[0_10px_22px_rgba(15,23,42,0.18)] hover:ring-slate-900/25 dark:bg-zinc-100 dark:text-zinc-950 dark:ring-white/20 dark:shadow-none',
  neutral:
    'border border-slate-200 bg-white text-slate-800 ring-slate-200 shadow-[0_8px_18px_rgba(15,23,42,0.08)] hover:border-slate-300 hover:bg-slate-50 hover:ring-slate-200 dark:border-white/12 dark:bg-white/10 dark:text-zinc-100 dark:ring-white/15 dark:hover:bg-white/15',
  success:
    'bg-emerald-600 text-white ring-emerald-500/25 shadow-[0_10px_22px_rgba(5,150,105,0.2)] hover:bg-emerald-500 hover:ring-emerald-400/30',
  warning:
    'bg-amber-500 text-white ring-amber-400/25 shadow-[0_10px_22px_rgba(217,119,6,0.2)] hover:bg-amber-400 hover:ring-amber-300/30',
  danger:
    'bg-rose-600 text-white ring-rose-500/25 shadow-[0_10px_22px_rgba(225,29,72,0.2)] hover:bg-rose-500 hover:ring-rose-400/30',
  violet:
    'bg-violet-600 text-white ring-violet-500/25 shadow-[0_10px_22px_rgba(124,58,237,0.2)] hover:bg-violet-500 hover:ring-violet-400/30',
  sky:
    'bg-sky-600 text-white ring-sky-500/25 shadow-[0_10px_22px_rgba(2,132,199,0.2)] hover:bg-sky-500 hover:ring-sky-400/30',
}

const sizeClasses = {
  sm: 'min-h-8 min-w-[104px] px-3 py-1.5 text-xs',
  default: 'min-h-9 min-w-[120px] px-4 py-2 text-sm',
  lg: 'min-h-10 min-w-[136px] px-5 py-2.5 text-sm',
}

const buttonAttrs = computed(() => {
  const passthrough = {}
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === 'class' || key === 'onClick' || key === 'type') return
    passthrough[key] = value
  })
  return passthrough
})

const buttonType = computed(() => (typeof attrs.type === 'string' ? attrs.type : 'button'))
const buttonState = computed(() => {
  if (checkVisible.value) return 'success'
  if (errorVisible.value) return 'error'
  if (loaderVisible.value) return 'loading'
  return 'idle'
})

const buttonClasses = computed(() =>
  props.unstyled
    ? cn('stateful-button', attrs.class)
    : cn(
      'stateful-button group inline-flex shrink-0 cursor-pointer select-none items-center justify-center whitespace-nowrap rounded-full font-semibold tracking-normal outline-none ring-offset-2 transition-[transform,background-color,border-color,color,box-shadow,opacity,filter] duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:ring-2 active:translate-y-0 active:scale-[0.96] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
      sizeClasses[props.size],
      toneClasses[props.tone],
      attrs.class,
    )
)

function wait(ms) {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    return Promise.resolve()
  }
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function nextFrame() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(resolve)
    })
  })
}

function normalizeHandlers(value) {
  if (!value) return []
  return Array.isArray(value) ? value.filter(Boolean) : [value]
}

async function runClickHandlers(event) {
  const handlers = normalizeHandlers(attrs.onClick)
  const results = []

  handlers.forEach((handler) => {
    if (typeof handler === 'function') {
      results.push(handler(event))
    }
  })

  return Promise.all(results)
}

async function hideActivity() {
  loaderVisible.value = false
  checkVisible.value = false
  errorVisible.value = false
  await nextFrame()
}

async function handleClick(event) {
  if (props.disabled || running.value) return

  const currentSequence = ++sequenceId
  running.value = true
  loaderVisible.value = true
  checkVisible.value = false
  errorVisible.value = false

  try {
    await nextFrame()
    const results = await runClickHandlers(event)
    if (currentSequence !== sequenceId) return
    const hasFailureResult = results.some((result) => result === false || result?.success === false)
    loaderVisible.value = false
    await nextFrame()
    if (currentSequence !== sequenceId) return
    if (hasFailureResult) {
      errorVisible.value = true
    } else {
      checkVisible.value = true
    }
    await nextFrame()
    await wait(props.successHold)
    if (currentSequence !== sequenceId) return
    checkVisible.value = false
    errorVisible.value = false
  } catch (error) {
    if (currentSequence !== sequenceId) throw error
    loaderVisible.value = false
    await nextFrame()
    errorVisible.value = true
    await nextFrame()
    await wait(props.successHold)
    await hideActivity()
    throw error
  } finally {
    if (currentSequence === sequenceId) {
      running.value = false
    }
  }
}
</script>

<style scoped>
.stateful-button {
  transform: translateZ(0);
  will-change: transform;
}

.stateful-button__content {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 0;
}

.stateful-button__state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  min-width: 0;
  transform: translateZ(0);
  will-change: transform, opacity;
}

.stateful-button__icon {
  display: inline-flex;
  width: 0;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  opacity: 0;
  transform: scale(0);
  transition:
    width 0.22s ease,
    opacity 0.18s ease,
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.stateful-button__icon.is-visible {
  width: var(--stateful-button-icon-size, 20px);
  opacity: 1;
  transform: scale(1);
}

.stateful-button__icon :deep(svg) {
  width: var(--stateful-button-icon-size, 20px);
  height: var(--stateful-button-icon-size, 20px);
  flex: 0 0 auto;
}

.stateful-button__icon--loader :deep(svg) {
  animation: stateful-button-spin 0.3s linear infinite;
}

.stateful-button__icon--check.is-visible :deep(svg) {
  animation: stateful-button-check-pop 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.stateful-button__label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: inherit;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stateful-button__icon--loader :deep(svg) {
  transform: none;
}

@keyframes stateful-button-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes stateful-button-check-pop {
  0% {
    transform: scale(0.4) rotate(-16deg);
  }
  70% {
    transform: scale(1.15) rotate(6deg);
  }
  100% {
    transform: scale(1) rotate(0deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .stateful-button,
  .stateful-button__icon {
    transition-duration: 0.01ms !important;
  }

  .stateful-button__icon--loader :deep(svg),
  .stateful-button__icon--check.is-visible :deep(svg) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
