<template>
  <div class="notif-bell-wrap" ref="bellRef">
    <button
      class="notif-bell-btn"
      :class="{ 'notif-bell-btn--active': panelOpen, 'notif-bell-btn--has-unread': unreadCount > 0 }"
      @click="onBellClick"
      @mouseenter="onBellHover"
      @mouseleave="onBellLeave"
      title="通知"
    >
      <DotLottieVue
        ref="playerRef"
        class="notif-bell-player"
        :src="notificationLottie"
        :autoplay="false"
        :loop="false"
        :speed="1"
        :render-config="{ autoResize: true }"
      />

    </button>

    <teleport to="body">
      <NotificationPanel
        :visible="panelOpen"
        :panel-style="panelStyle"
        @close="closePanel"
      />
      <div v-if="panelOpen" class="notif-overlay" @click="closePanel" />
    </teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import NotificationPanel from './NotificationPanel.vue'
import { useNotifications } from '../../composables/useNotifications'
import notificationLottie from '../../assets/anime/Notification.lottie'

// ── 未读循环帧段 ── 调整这两个值到动画内黄点出现的帧范围 ──
const UNREAD_LOOP_START = 15  // 循环起始帧（黄点出现之后）
const UNREAD_LOOP_END = 60    // 循环结束帧

const bellRef = ref(null)
const panelRect = ref(null)
const playerRef = ref(null)
const lottieReady = ref(false)
const { unreadCount, panelOpen, openPanel, closePanel, startSSE, stopSSE } = useNotifications()

const PANEL_WIDTH = 360

const panelStyle = computed(() => {
  if (!panelRect.value) return {}
  const r = panelRect.value
  const viewW = window.innerWidth
  // 优先让面板左边缘对齐铃铛左边缘，不够则右对齐
  let left = r.left
  if (left + PANEL_WIDTH > viewW - 8) {
    left = viewW - PANEL_WIDTH - 8
  }
  if (left < 8) left = 8
  return {
    top: `${r.bottom + 8}px`,
    left: `${left}px`,
  }
})

function getInstance() {
  return playerRef.value?.getDotLottieInstance?.() || null
}

async function setStaticFrame() {
  const instance = getInstance()
  if (!instance) return
  await instance.pause()
  await instance.setLoop(false)
  await instance.setFrame(0)
  await instance.freeze()
}

async function syncPlayback(force = false) {
  const instance = getInstance()
  if (!instance || !lottieReady.value) return
  if (unreadCount.value > 0) {
    await instance.unfreeze()
    await instance.setLoop(true)
    // 锁定在含黄点的帧段内循环
    if (typeof instance.setSegment === 'function') {
      instance.setSegment(UNREAD_LOOP_START, UNREAD_LOOP_END)
    }
    if (force) {
      await instance.stop()
      await instance.setFrame(UNREAD_LOOP_START)
    }
    await instance.play()
    return
  }
  // 恢复全段
  if (typeof instance.setSegment === 'function') {
    instance.setSegment(0, Infinity)
  }
  await setStaticFrame()
}

async function handleReady() {
  lottieReady.value = true
  await nextTick()
  await syncPlayback(true)
}

async function handleComplete() {
  await nextTick()
  await syncPlayback(true)
}

function updateRect() {
  if (bellRef.value) {
    panelRect.value = bellRef.value.getBoundingClientRect()
  }
}

const HOVER_SHAKE_MAX_FRAME = 10
let hoverFrameHandler = null

async function onBellHover() {
  if (unreadCount.value > 0) return
  const instance = getInstance()
  if (!instance || !lottieReady.value) return
  // 卸掉旧监听，避免重复
  if (hoverFrameHandler) {
    instance.removeEventListener('frame', hoverFrameHandler)
    hoverFrameHandler = null
  }
  hoverFrameHandler = async (event) => {
    const frame = event?.currentFrame ?? 0
    if (frame >= HOVER_SHAKE_MAX_FRAME) {
      instance.removeEventListener('frame', hoverFrameHandler)
      hoverFrameHandler = null
      // 定格在摄晃末端的帧，不返回静止帧
      await instance.pause()
      await instance.setFrame(HOVER_SHAKE_MAX_FRAME)
    }
  }
  instance.addEventListener('frame', hoverFrameHandler)
  await instance.unfreeze()
  await instance.setLoop(false)
  await instance.stop()
  await instance.setFrame(0)
  await instance.play()
}

async function onBellLeave() {
  if (unreadCount.value > 0) return
  const instance = getInstance()
  if (!instance || !lottieReady.value) return
  if (hoverFrameHandler) {
    instance.removeEventListener('frame', hoverFrameHandler)
    hoverFrameHandler = null
  }
  await setStaticFrame()
}

function onBellClick() {
  updateRect()
  if (panelOpen.value) {
    closePanel()
  } else {
    openPanel()
  }
}

onMounted(() => {
  startSSE()
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
})

watch(unreadCount, async (count, prev) => {
  if (!lottieReady.value) return
  await syncPlayback(count > 0 && prev <= 0)
})

onBeforeUnmount(() => {
  const instance = getInstance()
  if (instance) {
    instance.removeEventListener('ready', handleReady)
    instance.removeEventListener('load', handleReady)
    instance.removeEventListener('complete', handleComplete)
  }
})

onUnmounted(() => {
  stopSSE()
})
</script>

<style scoped>
.notif-bell-wrap {
  position: relative;
}

.notif-bell-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: rgba(29, 29, 31, 0.6);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: none;
}

.notif-bell-btn:hover {
  background: transparent;
  color: #1d1d1f;
  transform: translateY(-2px) scale(1.08);
  box-shadow: none;
}

.notif-bell-btn:active {
  transform: scale(0.96);
}

.notif-bell-btn--active {
  background: transparent;
  color: #0071e3;
  box-shadow: none;
}

.notif-bell-btn--has-unread {
  color: #8a5a00;
  background: transparent;
  box-shadow: none;
}

.notif-bell-player {
  width: 38px;
  height: 38px;
  pointer-events: none;
  filter: drop-shadow(0 6px 12px rgba(245, 158, 11, 0.22));
}



.notif-overlay {
  position: fixed;
  inset: 0;
  z-index: 99998;
  background: transparent;
}
</style>
