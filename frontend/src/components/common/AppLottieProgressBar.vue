<template>
  <div class="app-lottie-progress">
    <div class="app-lottie-progress-track" :class="{ 'is-complete': isComplete }">
      <!-- 已完成填充 -->
      <div class="app-lottie-progress-fill" :style="{ width: displayPct + '%' }" />
      <!-- 蠕虫角色 -->
      <div class="app-lottie-progress-worm" :style="{ left: displayPct + '%' }">
        <DotLottieVue
          ref="playerRef"
          class="app-lottie-progress-worm-player"
          :src="wormAnimation"
          autoplay
          loop
          :speed="0.8"
          :render-config="{ autoResize: true }"
        />
      </div>
      <!-- 终点旗子 -->
      <div class="app-lottie-progress-flag">
        <div class="app-lottie-progress-flag-pole" />
        <div class="app-lottie-progress-flag-banner" />
      </div>
    </div>
    <span v-if="showText" class="app-lottie-progress-text">{{ displayPctRound }}%</span>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import wormAnimation from '../../assets/anime/worm_crawl.lottie'

const props = defineProps({
  percentage: { type: Number, default: 0 },
  showText: { type: Boolean, default: true },
})

const normalizedPercentage = computed(() => {
  const value = Number(props.percentage ?? 0)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0
})

/* ---- 平滑插值 ---- */
const displayPct = ref(0)
const displayPctRound = computed(() => Math.round(displayPct.value))
const isComplete = computed(() => displayPctRound.value >= 100)
let rafId = null

function tick() {
  const target = normalizedPercentage.value
  const cur = displayPct.value
  const diff = target - cur
  if (Math.abs(diff) < 0.3) {
    displayPct.value = target
    rafId = null
    return
  }
  // 恒速 ~60%/s (at 60fps ≈ 1%/frame), 最小步长 0.3
  const step = Math.max(0.3, Math.abs(diff) * 0.08)
  displayPct.value = cur + (diff > 0 ? step : -step)
  rafId = requestAnimationFrame(tick)
}

watch(normalizedPercentage, () => {
  if (!rafId) rafId = requestAnimationFrame(tick)
}, { immediate: true })

onBeforeUnmount(() => { if (rafId) cancelAnimationFrame(rafId) })
</script>

<style scoped>
.app-lottie-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}

.app-lottie-progress-track {
  position: relative;
  flex: 1;
  height: 10px;
  border-radius: 5px;
  background: #fffc00;
  overflow: visible;
}

/* 100% 完成闪光效果 */
.app-lottie-progress-track.is-complete .app-lottie-progress-fill {
  background: linear-gradient(90deg, #7bbbd5, #5de0b8, #7bbbd5);
  background-size: 200% 100%;
  animation: shimmer 1.2s ease-in-out 1;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.app-lottie-progress-fill {
  height: 100%;
  border-radius: 5px;
  background: #7bbbd5;
  will-change: width;
}

.app-lottie-progress-worm {
  position: absolute;
  bottom: 4px;
  left: 0;
  width: 76px;
  height: 52px;
  pointer-events: none;
  will-change: left;
  transform: translateX(-50%);
}

.app-lottie-progress-worm-player {
  width: 100%;
  height: 100%;
}

.app-lottie-progress-worm-player :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}

/* 终点旗子 */
.app-lottie-progress-flag {
  position: absolute;
  right: -4px;
  bottom: 0;
  width: 20px;
  height: 32px;
  pointer-events: none;
}

.app-lottie-progress-flag-pole {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 3px;
  height: 100%;
  background: #a9b5c6;
  border-radius: 1px;
}

.app-lottie-progress-flag-banner {
  position: absolute;
  top: 0;
  left: 3px;
  width: 14px;
  height: 10px;
  background: #ff001e;
  border-radius: 1px 3px 3px 0;
}

.app-lottie-progress-text {
  flex: 0 0 auto;
  min-width: 36px;
  text-align: right;
  font-size: 12px;
  font-weight: 800;
  color: #36577f;
  font-variant-numeric: tabular-nums;
}
</style>
