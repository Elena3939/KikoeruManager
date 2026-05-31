<template>
  <button
    type="button"
    class="app-lottie-text-button"
    :class="[
      active ? 'is-active' : '',
      disabled ? 'is-disabled' : '',
      compact ? 'is-compact' : '',
    ]"
    :disabled="disabled"
    @mouseenter="playOnce"
    @focus="playOnce"
    @click="$emit('click', $event)"
  >
    <span class="app-lottie-text-button__media" aria-hidden="true">
      <DotLottieVue
        ref="playerRef"
        class="app-lottie-text-button__player"
        :src="src"
        :autoplay="false"
        :loop="false"
        :speed="speed"
        :render-config="{ autoResize: true }"
      />
      <span class="app-lottie-text-button__label">{{ label }}</span>
    </span>
  </button>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'

const props = defineProps({
  src: {
    type: String,
    required: true,
  },
  label: {
    type: String,
    default: '',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  active: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
  speed: {
    type: Number,
    default: 1,
  },
  initialFrame: {
    type: Number,
    default: 0,
  },
})

defineEmits(['click'])

const playerRef = ref(null)
const ready = ref(false)
const playing = ref(false)

function getInstance() {
  return playerRef.value?.getDotLottieInstance?.() || null
}

async function setStaticFrame() {
  const instance = getInstance()
  if (!instance) return
  await instance.pause()
  await instance.setFrame(props.initialFrame)
  await instance.freeze()
}

function handleReady() {
  ready.value = true
  setStaticFrame()
}

async function handleComplete() {
  playing.value = false
  await nextTick()
  setStaticFrame()
}

async function playOnce() {
  if (props.disabled || !ready.value || playing.value) return
  const instance = getInstance()
  if (!instance) return
  playing.value = true
  await instance.unfreeze()
  await instance.stop()
  await instance.setFrame(props.initialFrame)
  await instance.play()
}

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
  const instance = getInstance()
  if (!instance) return
  instance.removeEventListener('ready', handleReady)
  instance.removeEventListener('load', handleReady)
  instance.removeEventListener('complete', handleComplete)
})
</script>

<style scoped>
.app-lottie-text-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.app-lottie-text-button:hover:not(.is-disabled),
.app-lottie-text-button:focus-visible:not(.is-disabled) {
  transform: translateY(-2px) scale(1.02);
}

.app-lottie-text-button:active:not(.is-disabled) {
  transform: scale(0.96);
}

.app-lottie-text-button.is-disabled {
  opacity: 0.52;
  cursor: not-allowed;
}

.app-lottie-text-button__media {
  position: relative;
  display: inline-flex;
  width: 148px;
  height: 58px;
  align-items: center;
  justify-content: center;
  overflow: visible;
}

.app-lottie-text-button.is-compact .app-lottie-text-button__media {
  width: 132px;
  height: 52px;
}

.app-lottie-text-button__player {
  width: 100%;
  height: 100%;
  transform: scale(1.34);
  transform-origin: center;
  filter: drop-shadow(0 10px 20px rgba(15, 23, 42, 0.12));
  pointer-events: none;
}

.app-lottie-text-button__label {
  position: absolute;
  inset: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 24px;
  color: var(--set-text-strong, #0f172a);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.02em;
  pointer-events: none;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.72);
}

.app-lottie-text-button.is-active .app-lottie-text-button__label {
  color: var(--set-text-strong, #0f172a);
}

.app-lottie-text-button.is-active .app-lottie-text-button__player {
  filter: drop-shadow(0 12px 22px rgba(15, 23, 42, 0.18));
}
</style>
