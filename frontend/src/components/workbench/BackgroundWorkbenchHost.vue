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
  right: 20px;
  bottom: 20px;
  z-index: 2600;
  display: grid;
  gap: 10px;
  width: min(420px, calc(100vw - 40px));
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
