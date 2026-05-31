<template>
  <div class="slash-menu" :style="{ left: `${x}px`, top: `${y}px` }">
    <button
      v-for="(item, index) in items"
      :key="item.key"
      type="button"
      class="slash-item"
      :class="{ 'is-active': index === activeIndex }"
      @mousedown.prevent="$emit('select', item)"
      @mouseenter="$emit('active', index)"
    >
      <component :is="item.icon" :size="15" :stroke-width="2.2" />
      <span>
        <strong>{{ item.label }}</strong>
        <small>{{ item.hint }}</small>
      </span>
    </button>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  activeIndex: { type: Number, default: 0 },
})

defineEmits(['select', 'active'])
</script>

<style scoped>
.slash-menu {
  position: fixed;
  z-index: 10;
  width: 260px;
  max-height: 320px;
  overflow-y: auto;
  padding: 6px;
  background: var(--set-surface, #fff);
  border: 1px solid var(--set-border, rgba(29, 29, 31, 0.1));
  border-radius: 12px;
  box-shadow: var(--set-shadow-hover, 0 18px 42px rgba(0, 0, 0, 0.12));
}

.slash-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--set-text-strong, #1d1d1f);
  text-align: left;
  cursor: pointer;
  transition: all 0.16s ease;
}

.slash-item:hover,
.slash-item.is-active {
  background: var(--set-surface-hover, rgba(0, 0, 0, 0.05));
  color: var(--set-text-strong, #1d1d1f);
}

.slash-item span {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.slash-item strong {
  font-size: 12.5px;
  font-weight: 650;
  color: inherit;
}

.slash-item small {
  font-size: 11px;
  line-height: 1.35;
  color: var(--set-text-muted, rgba(29, 29, 31, 0.52));
}
</style>
