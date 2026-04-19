<template>
  <div
    class="app-loading-animation"
    :class="[
      `app-loading-animation--${variant}`,
      centered ? 'app-loading-animation--centered' : '',
    ]"
    :style="containerStyle"
  >
    <div class="app-loading-animation__player" :style="playerStyle">
      <DotLottieVue
        class="app-loading-animation__dotlottie"
        :src="loadingCatAnimation"
        autoplay
        loop
        :speed="0.9"
        mode="forward"
        :use-frame-interpolation="true"
        :render-config="renderConfig"
      />
    </div>
    <div v-if="label || description" class="app-loading-animation__copy">
      <div v-if="label" class="app-loading-animation__label">{{ label }}</div>
      <div v-if="description" class="app-loading-animation__description">{{ description }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import loadingCatAnimation from '../../assets/anime/Loading Cat.lottie'

const props = defineProps({
  label: {
    type: String,
    default: '',
  },
  description: {
    type: String,
    default: '',
  },
  size: {
    type: Number,
    default: 120,
  },
  minHeight: {
    type: Number,
    default: 0,
  },
  variant: {
    type: String,
    default: 'block',
  },
  centered: {
    type: Boolean,
    default: true,
  },
})

const playerStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}))

const containerStyle = computed(() => ({
  minHeight: props.minHeight > 0 ? `${props.minHeight}px` : undefined,
}))

const renderConfig = computed(() => ({
  autoResize: true,
  devicePixelRatio: typeof window !== 'undefined'
    ? Math.min(window.devicePixelRatio || 1, 1.5)
    : 1,
}))
</script>
