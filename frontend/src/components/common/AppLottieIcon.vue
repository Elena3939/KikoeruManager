<template>
  <span
    ref="wrapperRef"
    class="app-lottie-icon"
    :class="[isInteractive ? 'is-interactive' : '', disabled ? 'is-disabled' : '', tone ? `is-${tone}` : '']"
    :style="wrapperStyle"
  >
    <DotLottieVue
      ref="playerRef"
      class="app-lottie-icon__player"
      :src="src"
      :autoplay="false"
      :loop="false"
      :speed="speed"
      :render-config="{ autoResize: true }"
    />
  </span>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'

const props = defineProps({
  src: {
    type: String,
    required: true,
  },
  size: {
    type: Number,
    default: 32,
  },
  speed: {
    type: Number,
    default: 1,
  },
  interactive: {
    type: Boolean,
    default: true,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  tone: {
    type: String,
    default: '',
  },
  initialFrame: {
    type: Number,
    default: 0,
  },
})

const playerRef = ref(null)
const wrapperRef = ref(null)
const interactionTarget = ref(null)
const ready = ref(false)
const playing = ref(false)
const isInteractive = computed(() => props.interactive && !props.disabled)

const wrapperStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}))

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
  if (!isInteractive.value || !ready.value || playing.value) return
  const instance = getInstance()
  if (!instance) return
  playing.value = true
  await instance.unfreeze()
  await instance.stop()
  await instance.setFrame(props.initialFrame)
  await instance.play()
}

onMounted(() => {
  const bindInteraction = () => {
    const target = wrapperRef.value?.parentElement || wrapperRef.value
    if (!target) return
    target.addEventListener('mouseenter', playOnce)
    target.addEventListener('focusin', playOnce)
    interactionTarget.value = target
  }

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

  bindInteraction()
})

onBeforeUnmount(() => {
  if (interactionTarget.value) {
    interactionTarget.value.removeEventListener('mouseenter', playOnce)
    interactionTarget.value.removeEventListener('focusin', playOnce)
  }
  const instance = getInstance()
  if (!instance) return
  instance.removeEventListener('ready', handleReady)
  instance.removeEventListener('load', handleReady)
  instance.removeEventListener('complete', handleComplete)
})
</script>

<style scoped>
.app-lottie-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  pointer-events: none;
}

.app-lottie-icon.is-interactive {
  cursor: pointer;
  transition: transform 0.18s ease, filter 0.18s ease, opacity 0.18s ease;
}

.app-lottie-icon.is-interactive:hover,
.app-lottie-icon.is-interactive:focus-within {
  transform: scale(1.06);
}

.app-lottie-icon__player {
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.app-lottie-icon.is-disabled {
  cursor: default;
  opacity: 0.52;
}

.app-lottie-icon.is-danger .app-lottie-icon__player {
  filter: drop-shadow(0 4px 10px rgba(239, 68, 68, 0.14));
}

.app-lottie-icon.is-primary .app-lottie-icon__player {
  filter: drop-shadow(0 4px 10px rgba(59, 130, 246, 0.14));
}
</style>
