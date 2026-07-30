<template>
  <Transition name="progress-fade">
    <div v-if="!dismissed" class="app-lottie-progress" :class="[`size-${size}`]">
      <div class="app-lottie-progress-track" :class="{ 'is-complete': isComplete }">
        <!-- 已完成填充 -->
        <div class="app-lottie-progress-fill" :style="{ width: displayPct + '%' }" />
        <!-- 蠕虫角色 (lottie-web SVG 渲染，不裁切 viewport 外内容) -->
        <div
          class="app-lottie-progress-worm"
          :class="{ 'is-arriving': isComplete }"
          :style="{ left: displayPct + '%' }"
        >
          <div ref="wormContainer" class="app-lottie-progress-worm-player" />
        </div>
        <!-- 终点旗子 -->
        <div class="app-lottie-progress-flag" :class="{ 'is-waving': isComplete }">
          <div class="app-lottie-progress-flag-pole" />
          <div class="app-lottie-progress-flag-banner" />
        </div>
      </div>
      <span v-if="showText" class="app-lottie-progress-text">{{ displayPctRound }}%</span>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import lottie from 'lottie-web'
import wormAnimationData from '../../assets/anime/worm_crawl.json'

const props = defineProps({
  percentage: { type: Number, default: 0 },
  showText: { type: Boolean, default: true },
  size: { type: String, default: 'default', validator: v => ['sm', 'default'].includes(v) },
})

const wormContainer = ref(null)
let lottieInstance = null

onMounted(() => {
  if (wormContainer.value) {
    lottieInstance = lottie.loadAnimation({
      container: wormContainer.value,
      renderer: 'svg',
      loop: true,
      autoplay: true,
      animationData: wormAnimationData,
      rendererSettings: {
        viewBoxOnly: true,
        preserveAspectRatio: 'xMidYMid meet',
        progressiveLoad: true,
      },
    })
    lottieInstance.setSpeed(0.8)
  }
})

/* ---- 归一化，不取整以支持小数进度 ---- */
const normalizedPercentage = computed(() => {
  const value = Number(props.percentage ?? 0)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
})

/* ---- 平滑插值 (lerp 系数更小 → 更丝滑) ---- */
const displayPct = ref(0)
const displayPctRound = computed(() => Math.round(displayPct.value))
const isComplete = computed(() => displayPctRound.value >= 100)
const dismissed = ref(false)
let rafId = null
let completeTimer = null

function tick() {
  const target = normalizedPercentage.value
  const cur = displayPct.value
  const diff = target - cur
  if (Math.abs(diff) < 0.15) {
    displayPct.value = target
    rafId = null
    return
  }
  // 更平滑：每帧只走剩余距离的 4%，最小步长 0.15
  const step = Math.max(0.15, Math.abs(diff) * 0.04)
  displayPct.value = cur + (diff > 0 ? step : -step)
  rafId = requestAnimationFrame(tick)
}

watch(normalizedPercentage, () => {
  if (!rafId) rafId = requestAnimationFrame(tick)
}, { immediate: true })

/* ---- 完成后延迟消失 ---- */
watch(isComplete, (v) => {
  if (v) {
    // 到达 100% 后停留 2.5s 再淡出
    completeTimer = setTimeout(() => {
      dismissed.value = true
    }, 3000)
  } else {
    // 进度回退（重新开始新任务）
    dismissed.value = false
    if (completeTimer) { clearTimeout(completeTimer); completeTimer = null }
  }
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (completeTimer) clearTimeout(completeTimer)
  if (lottieInstance) { lottieInstance.destroy(); lottieInstance = null }
})
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
  height: 8px;
  border-radius: 4px;
  background: rgba(148, 163, 184, 0.34);
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
  border-radius: 4px;
  background: #7bbbd5;
  transition: width 0.3s ease-out;
}

.app-lottie-progress-worm {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 76px;
  height: 58px;
  overflow: visible;
  pointer-events: none;
  transition: left 0.3s ease-out;
  transform: translateX(-50%);
}

/* 虫子到达终点时的轻微弹跳 */
.app-lottie-progress-worm.is-arriving {
  animation: worm-bounce 0.6s ease-out 1;
}

@keyframes worm-bounce {
  0% { transform: translateX(-50%) scale(1); }
  40% { transform: translateX(-50%) scale(1.15); }
  70% { transform: translateX(-50%) scale(0.95); }
  100% { transform: translateX(-50%) scale(1); }
}

.app-lottie-progress-worm-player {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.app-lottie-progress-worm-player :deep(svg) {
  overflow: visible !important;
  display: block;
}

/* ---- sm 尺寸 ---- */
.app-lottie-progress.size-sm .app-lottie-progress-track {
  height: 6px;
  border-radius: 3px;
}
.app-lottie-progress.size-sm .app-lottie-progress-fill {
  border-radius: 3px;
}
.app-lottie-progress.size-sm .app-lottie-progress-worm {
  width: 52px;
  height: 40px;
}
.app-lottie-progress.size-sm .app-lottie-progress-flag {
  width: 14px;
  height: 22px;
  bottom: 2px;
}
.app-lottie-progress.size-sm .app-lottie-progress-flag-pole {
  width: 2px;
}
.app-lottie-progress.size-sm .app-lottie-progress-flag-banner {
  width: 10px;
  height: 8px;
}
.app-lottie-progress.size-sm .app-lottie-progress-text {
  font-size: 11px;
}

/* 终点旗子：旗杆底部插在进度条右端 */
.app-lottie-progress-flag {
  position: absolute;
  right: -2px;
  bottom: 4px;
  width: 20px;
  height: 32px;
  pointer-events: none;
  transform-origin: bottom center;
}

/* 虫子到达后旗帜摇摆 */
.app-lottie-progress-flag.is-waving {
  animation: flag-wave 0.5s ease-in-out 3;
}

@keyframes flag-wave {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(8deg); }
  75% { transform: rotate(-8deg); }
}

.app-lottie-progress-flag-pole {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 3px;
  height: 100%;
  background: #a9b5c6;
  border-radius: 1px;
}

.app-lottie-progress-flag-banner {
  position: absolute;
  top: 0;
  left: 50%;
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

/* ---- 完成后整体淡出 ---- */
.progress-fade-leave-active {
  transition: opacity 2s ease-out;
}
.progress-fade-leave-to {
  opacity: 0;
}
</style>
