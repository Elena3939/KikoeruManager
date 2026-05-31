<template>
  <div class="blk-lib">
    <div class="blk-lib-head">
      <span class="blk-lib-title">积木块库</span>
    </div>
    <div v-for="group in BLOCK_GROUPS" :key="group.key" class="blk-lib-group">
      <p class="blk-lib-group-label">{{ group.label }}</p>
      <button
        v-for="(meta, type) in groupedBlocks[group.key]"
        :key="type"
        type="button"
        class="blk-lib-item"
        :title="meta.description"
        @click="$emit('add-block', type)"
      >
        <span class="blk-lib-item-dot" :style="{ background: meta.color }" />
        <span class="blk-lib-item-label">{{ meta.label }}</span>
        <Plus :size="13" :stroke-width="2.6" class="blk-lib-item-add" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Plus } from 'lucide-vue-next'
import { BLOCK_TYPES, BLOCK_GROUPS } from './blockTypes.js'

defineEmits(['add-block'])

const groupedBlocks = computed(() => {
  const result = {}
  for (const g of BLOCK_GROUPS) result[g.key] = {}
  for (const [type, meta] of Object.entries(BLOCK_TYPES)) {
    if (result[meta.group]) result[meta.group][type] = meta
  }
  return result
})
</script>

<style scoped>
.blk-lib {
  width: 176px;
  flex-shrink: 0;
  border-right: 1px solid var(--set-border-soft, rgba(29, 29, 31, 0.07));
  background: var(--set-surface-soft, #fafafa);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.blk-lib-head {
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--set-border-soft, rgba(29, 29, 31, 0.07));
}
.blk-lib-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--set-text-muted, rgba(29, 29, 31, 0.5));
}
.blk-lib-group {
  padding: 10px 8px 4px;
}
.blk-lib-group-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--set-text-subtle, rgba(29, 29, 31, 0.4));
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 0 6px;
  margin-bottom: 4px;
}
.blk-lib-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  color: var(--set-text-strong, #1d1d1f);
  text-align: left;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.blk-lib-item:hover {
  background: var(--set-surface-hover, rgba(0, 0, 0, 0.05));
}
.blk-lib-item:hover .blk-lib-item-add {
  opacity: 1;
}
.blk-lib-item-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.blk-lib-item-label {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
}
.blk-lib-item-add {
  opacity: 0;
  color: var(--set-text-muted, #64748b);
  transition: opacity 0.15s;
}
</style>
