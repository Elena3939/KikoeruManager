<template>
  <div class="app-empty-state" :class="`size-${size}`">
    <DotLottieVue
      class="app-empty-lottie"
      :src="noDataAnimation"
      autoplay
      loop
      :speed="0.7"
      mode="forward"
      :use-frame-interpolation="true"
      :render-config="{ autoResize: true }"
    />
    <div v-if="description" class="app-empty-description">{{ description }}</div>
    <div v-if="$slots.default" class="app-empty-extra">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import noDataAnimation from '../../assets/anime/No-Data.lottie'

defineProps({
  description: { type: String, default: '' },
  size: {
    type: String,
    default: 'default',
    validator: (v) => ['sm', 'default', 'lg'].includes(v),
  },
})
</script>

<style scoped>
.app-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 16px;
  color: #94a3b8;
}

.app-empty-lottie {
  display: block;
  flex-shrink: 0;
}

/* --- 尺寸 --- */
.app-empty-state.size-sm .app-empty-lottie {
  width: 80px;
  height: 80px;
}
.app-empty-state.size-default .app-empty-lottie {
  width: 120px;
  height: 120px;
}
.app-empty-state.size-lg .app-empty-lottie {
  width: 180px;
  height: 180px;
}

.app-empty-description {
  font-size: 13px;
  color: #64748b;
  text-align: center;
  line-height: 1.5;
}

.app-empty-state.size-sm .app-empty-description {
  font-size: 12px;
}

.app-empty-state.size-lg .app-empty-description {
  font-size: 14px;
}

.app-empty-extra {
  margin-top: 4px;
}
</style>
