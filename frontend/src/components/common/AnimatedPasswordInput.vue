<template>
  <div
    class="animated-password-input"
    :class="[
      isVisible ? 'is-visible' : 'is-hidden',
      disabled ? 'is-disabled' : '',
    ]"
  >
    <input
      :value="modelValue"
      class="animated-password-input__field"
      :type="isVisible ? 'text' : 'password'"
      :placeholder="placeholder"
      :disabled="disabled"
      :autocomplete="autocomplete"
      @input="handleInput"
    >
    <button
      ref="toggleRef"
      type="button"
      class="animated-password-input__toggle"
      :class="isVisible ? 'is-visible' : 'is-hidden'"
      :disabled="disabled"
      :aria-label="isVisible ? '隐藏密码' : '显示密码'"
      :aria-pressed="isVisible ? 'true' : 'false'"
      @click="toggleVisibility"
    >
      <DotLottieVue
        ref="playerRef"
        class="animated-password-input__player"
        :src="visibilityAnimation"
        :autoplay="false"
        :loop="false"
        :speed="1"
        :render-config="{ autoResize: true }"
      />
    </button>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import visibilityAnimation from '../../assets/anime/Visibility.lottie'

const VISIBLE_FRAME = 0
const HIDDEN_FRAME = 25
const HOVER_START_FRAME = 0
const HOVER_END_FRAME = 42

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  autocomplete: {
    type: String,
    default: 'current-password',
  },
  visibleByDefault: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'visibility-change'])

const playerRef = ref(null)
const toggleRef = ref(null)
const ready = ref(false)
const playingHoverAnimation = ref(false)
const isVisible = ref(props.visibleByDefault)
let interactionTarget = null

function handlePointerEnter() {
  playHoverAnimation()
}

function handlePointerLeave() {
  stopHoverAnimation()
}

function getInstance() {
  return playerRef.value?.getDotLottieInstance?.() || null
}

async function setStaticFrame(visible) {
  const instance = getInstance()
  if (!instance) return
  await instance.pause()
  await instance.setFrame(visible ? VISIBLE_FRAME : HIDDEN_FRAME)
  await instance.freeze()
}

async function playHoverAnimation() {
  if (!ready.value || props.disabled || playingHoverAnimation.value) return
  const instance = getInstance()
  if (!instance) return

  playingHoverAnimation.value = true
  await instance.unfreeze()
  await instance.stop()
  await instance.setLoop(false)
  await instance.setMode('forward')
  await instance.setSegment(HOVER_START_FRAME, HOVER_END_FRAME)
  await instance.setFrame(HOVER_START_FRAME)
  await instance.play()
}

async function stopHoverAnimation({ preserveHover = false } = {}) {
  const instance = getInstance()
  if (!instance) return
  playingHoverAnimation.value = false
  await instance.setLoop(false)
  await instance.stop()
  await setStaticFrame(isVisible.value)
}

function handleInput(event) {
  emit('update:modelValue', event.target.value)
}

function toggleVisibility() {
  if (props.disabled) return
  isVisible.value = !isVisible.value
  emit('visibility-change', isVisible.value)
  toggleRef.value?.blur?.()
  setStaticFrame(isVisible.value)
}

function handleReady() {
  ready.value = true
  setStaticFrame(isVisible.value)
}

function handleComplete() {
  playingHoverAnimation.value = false
  setStaticFrame(isVisible.value)
}

onMounted(() => {
  const bindInteraction = () => {
    const target = toggleRef.value
    if (!target) return
    target.addEventListener('mouseenter', handlePointerEnter)
    target.addEventListener('mouseleave', handlePointerLeave)
    interactionTarget = target
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
  if (interactionTarget) {
    interactionTarget.removeEventListener('mouseenter', handlePointerEnter)
    interactionTarget.removeEventListener('mouseleave', handlePointerLeave)
    interactionTarget = null
  }

  const instance = getInstance()
  if (!instance) return
  instance.removeEventListener('ready', handleReady)
  instance.removeEventListener('load', handleReady)
  instance.removeEventListener('complete', handleComplete)
})
</script>

<style scoped>
.animated-password-input {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

.animated-password-input__field {
  width: 100%;
  min-height: 42px;
  padding: 0 58px 0 12px;
  border: none;
  outline: none;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.95);
  color: #0f172a;
  font-size: 14px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.92);
  transition: box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.animated-password-input__field:focus {
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.95), 0 0 0 4px rgba(191, 219, 254, 0.42);
}

.animated-password-input__field:disabled {
  cursor: not-allowed;
  opacity: 0.72;
}

.animated-password-input__toggle {
  position: absolute;
  top: 50%;
  right: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  transform: translateY(-50%);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  cursor: pointer;
}

.animated-password-input__toggle:hover {
  transform: translateY(calc(-50% - 2px)) scale(1.06);
}

.animated-password-input__toggle:active:not(:disabled) {
  transform: translateY(-50%) scale(0.96);
}

.animated-password-input__toggle:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.animated-password-input__player {
  width: 34px;
  height: 34px;
  pointer-events: none;
}
</style>
