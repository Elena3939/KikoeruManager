<template>
  <div class="notif-bell-wrap" ref="bellRef">
    <button
      class="notif-bell-btn"
      :class="{ 'notif-bell-btn--active': panelOpen, 'notif-bell-btn--has-unread': unreadCount > 0 }"
      @click="onBellClick"
      title="通知"
    >
      <Bell :size="18" :stroke-width="2.2" />
      <span v-if="unreadCount > 0" class="notif-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Bell } from 'lucide-vue-next'
import NotificationPanel from './NotificationPanel.vue'
import { useNotifications } from '../../composables/useNotifications'

const bellRef = ref(null)
const panelRect = ref(null)
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

function updateRect() {
  if (bellRef.value) {
    panelRect.value = bellRef.value.getBoundingClientRect()
  }
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
  width: 38px;
  height: 38px;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  color: rgba(29, 29, 31, 0.6);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.notif-bell-btn:hover {
  background: rgba(255, 255, 255, 0.95);
  color: #1d1d1f;
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.notif-bell-btn:active {
  transform: scale(0.96);
}

.notif-bell-btn--active {
  background: #f0f6ff;
  color: #0071e3;
  border-color: rgba(0, 113, 227, 0.2);
}

.notif-bell-btn--has-unread {
  color: #0071e3;
  border-color: rgba(0, 113, 227, 0.15);
}

.notif-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  font-size: 10px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
  border-radius: 99px;
  background: #d93025;
  color: #fff;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(217, 48, 37, 0.4);
  animation: badge-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes badge-pop {
  from { transform: scale(0); }
  to { transform: scale(1); }
}

.notif-overlay {
  position: fixed;
  inset: 0;
  z-index: 99998;
  background: transparent;
}
</style>
