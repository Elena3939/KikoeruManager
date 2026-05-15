<template>
  <Teleport to="body">
    <transition-group name="workbench-host-list" tag="div" class="workbench-host-stack">
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import WorkbenchBackgroundCard from './WorkbenchBackgroundCard.vue'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'

const manager = useBackgroundWorkbenchManager()
const route = useRoute()
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
  right: 24px;
  bottom: 24px;
  z-index: 2600;
  display: grid;
  gap: 14px;
  width: min(360px, calc(100vw - 32px));
  pointer-events: none;
}

.workbench-host-stack :deep(.workbench-card) {
  pointer-events: auto;
}

.workbench-host-list-enter-active,
.workbench-host-list-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}

.workbench-host-list-enter-from,
.workbench-host-list-leave-to {
  opacity: 0;
  transform: translateY(12px);
}
</style>
