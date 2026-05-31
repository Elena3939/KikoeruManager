<template>
  <label class="stc" :class="{ 'is-disabled': disabled, 'is-active': modelValue }">
    <span class="stc-label">
      <slot>{{ label }}</slot>
    </span>
    <SettingsSwitch
      :model-value="modelValue"
      :disabled="disabled"
      @update:model-value="(v) => emit('update:modelValue', v)"
      @change="(v) => emit('change', v)"
    />
  </label>
</template>

<script setup>
import SettingsSwitch from './SettingsSwitch.vue'

/* 设置页 pill 开关原子：用于 pill-switch-grid 里的小 chip（左 label，右 switch，整行一个 pill）。
 */
defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])
</script>

<style scoped>
.stc {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--set-surface, #ffffff);
  border: 1px solid var(--set-border, rgba(226, 232, 240, 0.85));
  color: var(--set-text-strong, #1d1d1f);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: -0.05px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.stc:not(.is-disabled):hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.75));
  background: var(--set-surface-hover, rgba(248, 250, 252, 0.85));
  box-shadow: var(--set-shadow, 0 4px 12px -4px rgba(15, 23, 42, 0.08));
}

.stc.is-active {
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.36));
  background: var(--set-surface-muted, rgba(241, 245, 249, 0.9));
}

.stc.is-disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.stc-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
