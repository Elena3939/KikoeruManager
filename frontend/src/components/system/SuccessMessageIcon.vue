<template>
  <DotLottieVue
    class="success-message-icon"
    :src="successConfettiAnimation"
    :autoplay="true"
    :loop="false"
    :speed="1"
    :render-config="{ autoResize: true }"
  />
</template>

<script setup>
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'
</script>

<style scoped>
.success-message-icon {
  width: 18px;
  height: 18px;
  display: block;
  pointer-events: none;
  transform: translateX(4px) scale(3);
  transform-origin: center center;
}
</style>
