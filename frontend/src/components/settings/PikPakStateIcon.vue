<template>
  <span class="pikpak-stateful-icon" :class="stateClass" :data-state="displayState" aria-hidden="true">
    <RefreshCw class="pikpak-stateful-icon__glyph pikpak-stateful-icon__glyph--idle" :size="14" :stroke-width="2.4" />
    <LoaderCircle class="pikpak-stateful-icon__glyph pikpak-stateful-icon__glyph--loading" :size="14" :stroke-width="2.4" />
    <CheckCircle2 class="pikpak-stateful-icon__glyph pikpak-stateful-icon__glyph--success" :size="14" :stroke-width="2.4" />
    <XCircle class="pikpak-stateful-icon__glyph pikpak-stateful-icon__glyph--error" :size="14" :stroke-width="2.4" />
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { CheckCircle2, LoaderCircle, RefreshCw, XCircle } from 'lucide-vue-next'

const props = defineProps({
  state: {
    type: String,
    default: 'idle',
    validator: (value) => ['idle', 'loading', 'success', 'error'].includes(value),
  },
})

const displayState = computed(() => normalizeState(props.state))
const stateClass = computed(() => `is-${displayState.value}`)

function normalizeState(value) {
  if (['loading', 'success', 'error', 'idle'].includes(value)) return value
  return 'idle'
}
</script>

<style scoped>
.pikpak-stateful-icon {
  display: inline-flex;
  position: relative;
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  align-items: center;
  justify-content: center;
  contain: layout paint;
  color: currentColor;
}

.pikpak-stateful-icon__glyph {
  position: absolute;
  inset: 0;
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  opacity: 0;
  transform: scale(0.68) translateY(2px) rotate(-12deg);
  transform-origin: center;
  transition:
    opacity 180ms ease,
    color 180ms ease,
    transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1);
  will-change: transform, opacity;
}

.pikpak-stateful-icon.is-idle .pikpak-stateful-icon__glyph--idle,
.pikpak-stateful-icon.is-loading .pikpak-stateful-icon__glyph--loading,
.pikpak-stateful-icon.is-success .pikpak-stateful-icon__glyph--success,
.pikpak-stateful-icon.is-error .pikpak-stateful-icon__glyph--error {
  opacity: 1;
  transform: scale(1) translateY(0) rotate(0deg);
}

.pikpak-stateful-icon.is-loading .pikpak-stateful-icon__glyph--loading {
  color: var(--set-text-strong);
  animation: pikpak-stateful-icon-spin 0.72s linear infinite;
}

.pikpak-stateful-icon.is-success .pikpak-stateful-icon__glyph--success {
  color: #16a34a;
  animation: pikpak-stateful-icon-pop 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.pikpak-stateful-icon.is-error .pikpak-stateful-icon__glyph--error {
  color: #e11d48;
  animation: pikpak-stateful-icon-pop 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.pikpak-stateful-icon.is-idle .pikpak-stateful-icon__glyph--idle {
  color: currentColor;
}

@keyframes pikpak-stateful-icon-spin {
  to {
    transform: scale(1) translateY(0) rotate(360deg);
  }
}

@keyframes pikpak-stateful-icon-pop {
  0% {
    transform: scale(0.56) translateY(2px) rotate(-16deg);
  }
  72% {
    transform: scale(1.16) translateY(0) rotate(6deg);
  }
  100% {
    transform: scale(1) translateY(0) rotate(0deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .pikpak-stateful-icon__glyph {
    transition-duration: 0.01ms !important;
  }

  .pikpak-stateful-icon.is-loading .pikpak-stateful-icon__glyph--loading,
  .pikpak-stateful-icon.is-success .pikpak-stateful-icon__glyph--success,
  .pikpak-stateful-icon.is-error .pikpak-stateful-icon__glyph--error {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
