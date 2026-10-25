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
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import BackgroundFloatingCard from '../common/BackgroundFloatingCard.vue'
import { persistentTaskCards, mountedTaskCards, openTaskWorkbenches, verifiedTaskCards, taskCardBelongsToPage, openPersistentTaskCard, refreshPersistentTaskCards, dismissPersistentTaskCard } from '../../composables/usePersistentTaskCards'
import WorkbenchBackgroundCard from './WorkbenchBackgroundCard.vue'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'

const manager = useBackgroundWorkbenchManager()
const route = useRoute()

const persistentCards = computed(() => Object.values(persistentTaskCards).filter(card => !card.dismissed && taskCardBelongsToPage(card, route.path) && verifiedTaskCards.has(card.id) && !mountedTaskCards.has(card.id) && !openTaskWorkbenches.has(`${card.route}:${card.props.taskSource}`)))
function handlePersistentAction(id, action) {
  if (['close', 'dismiss'].includes(action)) dismissPersistentTaskCard(id)
  else openPersistentTaskCard(id)
}
let refreshTimer
let refreshing = false
async function refreshCards() {
  if (refreshing) return
  refreshing = true
  try { await refreshPersistentTaskCards() } finally { refreshing = false }
}
onMounted(() => { refreshCards(); refreshTimer = setInterval(refreshCards, 5000) })
onBeforeUnmount(() => clearInterval(refreshTimer))
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
