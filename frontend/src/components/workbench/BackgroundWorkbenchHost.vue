<template>
  <Teleport to="body">
    <transition-group v-if="backgroundCards.length || persistentCards.length" name="workbench-host-list" tag="div" class="workbench-host-stack">
      <BackgroundFloatingCard
        v-for="card in persistentCards"
        :key="card.id"
        v-bind="card.props"
        hosted
        persistent-replica
        @action="handlePersistentAction(card.id, $event)"
      />
      <WorkbenchBackgroundCard
        v-for="workbench in backgroundCards"
        :key="workbench.id"
        :workbench="workbench"
        @action="handleAction(workbench.id, $event)"
      />
    </transition-group>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BackgroundFloatingCard from '../common/BackgroundFloatingCard.vue'
import { persistentTaskCards, mountedTaskCards, openTaskWorkbenches, verifiedTaskCards, taskCardBelongsToPage, openPersistentTaskCard, refreshPersistentTaskCards, dismissPersistentTaskCard } from '../../composables/usePersistentTaskCards'
import WorkbenchBackgroundCard from './WorkbenchBackgroundCard.vue'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'
import { applyPersistentTransferEvent } from '../../composables/usePersistentTaskCards'
import { useRealtimeEvents } from '../../composables/useRealtimeEvents'

const manager = useBackgroundWorkbenchManager()
const route = useRoute()
const router = useRouter()
const realtime = useRealtimeEvents()
const handleTransferEvent = event => applyPersistentTransferEvent(event.detail)

const persistentCards = computed(() => Object.values(persistentTaskCards).filter(card => !card.dismissed && taskCardBelongsToPage(card, route.path) && verifiedTaskCards.has(card.id) && !mountedTaskCards.has(card.id) && !openTaskWorkbenches.has(`${card.route}:${card.props.taskSource}`)))
async function handlePersistentAction(id, action) {
  if (['close', 'dismiss'].includes(action)) dismissPersistentTaskCard(id)
  else {
    const card = persistentTaskCards[id]
    if (!card) return
    if (card.route && card.route !== route.path) {
      await router.push(card.route)
      await nextTick()
    }
    await openPersistentTaskCard(id)
  }
}
let refreshTimer
let refreshing = false
let refreshQueued = false
async function refreshCards(includeTransfers = true) {
  if (refreshing) { refreshQueued ||= includeTransfers; return }
  refreshing = true
  try { await refreshPersistentTaskCards({ includeTransfers }) } finally {
    refreshing = false
    if (refreshQueued) { refreshQueued = false; void refreshCards() }
  }
}
watch(realtime.connected, connected => { if (connected) void refreshCards() })
onMounted(() => {
  window.addEventListener('kikoerumanager:events:message', handleTransferEvent)
  refreshCards()
  refreshTimer = setInterval(() => refreshCards(false), 5000)
})
onBeforeUnmount(() => {
  clearInterval(refreshTimer)
  window.removeEventListener('kikoerumanager:events:message', handleTransferEvent)
})
const backgroundCards = computed(() => manager.backgroundCards.value.filter((workbench) => {
  if (workbench.id === 'subtitle-import-workbench') {
    return route.path === '/subtitle-import'
  }
  return true
}))

function handleAction(id, action) {
  manager.invokeWorkbenchAction(id, action)
}
</script>

<style scoped>
.workbench-host-stack {
  position: fixed;
  right: 20px;
  bottom: 88px;
  z-index: 2600;
  display: grid;
  gap: 10px;
  width: min(480px, calc(100vw - 24px));
  pointer-events: none;
}

.workbench-host-stack :deep(.floating-card) {
  pointer-events: auto;
}

.workbench-host-list-enter-active,
.workbench-host-list-leave-active {
  transition:
    opacity 0.4s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.workbench-host-list-enter-from,
.workbench-host-list-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}
</style>
