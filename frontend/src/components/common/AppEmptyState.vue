<template>
  <div
    class="flex flex-col items-center justify-center gap-2 px-4 text-neutral-400"
    :class="sizeClass.container"
  >
    <DotLottieVue
      class="block flex-shrink-0"
      :class="sizeClass.lottie"
      :src="noDataAnimation"
      autoplay
      loop
      :speed="0.7"
      mode="forward"
      :use-frame-interpolation="true"
      :render-config="{ autoResize: true }"
    />
    <div
      v-if="description"
      class="text-center leading-snug text-neutral-500"
      :class="sizeClass.description"
    >
      {{ description }}
    </div>
    <div v-if="$slots.default" class="mt-1">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import noDataAnimation from '../../assets/anime/No-Data.lottie'

const props = defineProps({
  description: { type: String, default: '' },
  size: {
    type: String,
    default: 'default',
    validator: (v) => ['sm', 'default', 'lg'].includes(v),
  },
})

const sizeClass = computed(() => {
  if (props.size === 'sm') {
    return {
      container: 'py-6',
      lottie: 'w-20 h-20',
      description: 'text-[12px]',
    }
  }
  if (props.size === 'lg') {
    return {
      container: 'py-10',
      lottie: 'w-44 h-44',
      description: 'text-[14px]',
    }
  }
  return {
    container: 'py-8',
    lottie: 'w-28 h-28',
    description: 'text-[13px]',
  }
})
</script>
