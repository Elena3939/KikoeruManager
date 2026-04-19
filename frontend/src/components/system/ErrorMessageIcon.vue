<template>
  <DotLottieVue
    class="error-message-icon"
    :src="errorAnimation"
    :autoplay="true"
    :loop="false"
    :speed="1"
    :render-config="{ autoResize: true }"
  />
</template>

<script setup>
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import errorAnimation from '../../assets/anime/Error animation.lottie'
</script>

<style scoped>
.error-message-icon {
  width: 18px;
  height: 18px;
  display: block;
  pointer-events: none;
  transform: translateX(4px) scale(3);
  transform-origin: center center;
}
</style>
