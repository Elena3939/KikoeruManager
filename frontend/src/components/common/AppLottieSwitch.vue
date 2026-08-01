<template>
  <button
    type="button"
    class="app-lottie-switch"
    :class="[
      modelValue ? 'is-on' : 'is-off',
      disabled ? 'is-disabled' : '',
      compact ? 'is-compact' : '',
    ]"
    role="switch"
    :aria-checked="String(modelValue)"
    :aria-disabled="disabled ? 'true' : 'false'"
    :disabled="disabled"
    @click="handleToggle"
  >
    <span class="app-lottie-switch__track">
      <DotLottieVue
        ref="playerRef"
        class="app-lottie-switch__player"
        :src="toggleAnimation"
        :autoplay="false"
        :loop="false"
        :speed="1.05"
        :render-config="{ autoResize: true }"
      />
    </span>
    <span v-if="showText" class="app-lottie-switch__text">
      {{ modelValue ? activeText : inactiveText }}
    </span>
  </button>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import toggleAnimation from '../../assets/anime/Toggle switch buttons on and off.lottie'

const OFF_FRAME = 0
const ON_FRAME = 192
const OFF_TRANSITION_START_FRAME = 192
const OFF_TRANSITION_END_FRAME = 216
const FRAME_RATE = 30
const TRANSITION_SETTLE_MS =
  Math.round((Math.max(ON_FRAME - OFF_FRAME, OFF_TRANSITION_END_FRAME - OFF_TRANSITION_START_FRAME) / FRAME_RATE) * 1000) + 80

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
  showText: {
    type: Boolean,
    default: false,
  },
  activeText: {
    type: String,
    default: '开',
  },
  inactiveText: {
    type: String,
    default: '关',
  },
})

const emit = defineEmits(['update:modelValue', 'change'])

const playerRef = ref(null)
const ready = ref(false)
const animating = ref(false)
const renderedValue = ref(null)
let settleTimer = null

function getInstance() {
  return playerRef.value?.getDotLottieInstance?.() || null
}

async function setStaticFrame(value) {
  const instance = getInstance()
  if (!instance) return
  await instance.pause()
  await instance.setFrame(value ? ON_FRAME : OFF_FRAME)
  await instance.freeze()
  renderedValue.value = value
}

async function playTransition(nextValue) {
  const instance = getInstance()
  if (!instance) return

  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }

  animating.value = true
  await instance.unfreeze()
  await instance.stop()
  await instance.setLoop(false)
  await instance.setMode('forward')
  const startFrame = nextValue ? OFF_FRAME : OFF_TRANSITION_START_FRAME
  const endFrame = nextValue ? ON_FRAME : OFF_TRANSITION_END_FRAME
  await instance.setSegment(startFrame, endFrame)
  await instance.setFrame(startFrame)
  await instance.play()

  settleTimer = window.setTimeout(() => {
    animating.value = false
    setStaticFrame(nextValue)
    settleTimer = null
  }, TRANSITION_SETTLE_MS)
}

function handleComplete() {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  animating.value = false
  setStaticFrame(props.modelValue)
}

function handleReady() {
  ready.value = true
  setStaticFrame(props.modelValue)
}

function handleToggle() {
  if (props.disabled || animating.value) return
  const nextValue = !props.modelValue
  emit('update:modelValue', nextValue)
  emit('change', nextValue)
}

watch(
  () => props.modelValue,
  async value => {
    if (!ready.value) return
    if (renderedValue.value === value) {
      setStaticFrame(value)
      return
    }
    if (animating.value) {
      await nextTick()
      return
    }
    playTransition(value)
  }
)

onMounted(() => {
  const bind = () => {
    const instance = getInstance()
    if (!instance) return false
    instance.addEventListener('ready', handleReady)
    instance.addEventListener('load', handleReady)
    instance.addEventListener('complete', handleComplete)
    return true
  }

  if (!bind()) {
    window.setTimeout(bind, 60)
  }
})

onBeforeUnmount(() => {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  const instance = getInstance()
  if (!instance) return
  instance.removeEventListener('ready', handleReady)
  instance.removeEventListener('load', handleReady)
  instance.removeEventListener('complete', handleComplete)
})
</script>

<style scoped>
.app-lottie-switch {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.app-lottie-switch:hover:not(.is-disabled) {
  transform: translateY(-1px);
}

.app-lottie-switch.is-disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.app-lottie-switch__track {
  display: inline-flex;
  width: 84px;
  height: 52px;
  overflow: visible;
  flex-shrink: 0;
}

.app-lottie-switch.is-compact .app-lottie-switch__track {
  width: 68px;
  height: 42px;
}

.app-lottie-switch__player {
  width: 100%;
  height: 100%;
  transform: scale(1.4);
  transform-origin: center;
  filter: drop-shadow(0 6px 14px rgba(249, 115, 22, 0.16));
  pointer-events: none;
}

.app-lottie-switch__text {
  min-width: 28px;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  color: #64748b;
  letter-spacing: 0.02em;
}

.app-lottie-switch.is-on .app-lottie-switch__text {
  color: #ea580c;
}
</style>
