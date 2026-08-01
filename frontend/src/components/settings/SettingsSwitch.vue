<template>
  <button
    type="button"
    class="settings-switch"
    :class="{ 'is-on': modelValue, 'is-disabled': disabled }"
    :aria-checked="String(Boolean(modelValue))"
    :disabled="disabled"
    role="switch"
    @click="toggle"
  >
    <span class="settings-switch__track">
      <span class="settings-switch__thumb" />
    </span>
  </button>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

function toggle() {
  if (props.disabled) return
  const next = !props.modelValue
  emit('update:modelValue', next)
  emit('change', next)
}
</script>

<style scoped>
.settings-switch {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 26px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.settings-switch:not(.is-disabled):hover {
  transform: translateY(-1px) scale(1.03);
}

.settings-switch:not(.is-disabled):active {
  transform: scale(0.96);
}

.settings-switch__track {
  position: relative;
  width: 42px;
  height: 24px;
  border-radius: 999px;
  border: 1px solid var(--set-border-strong);
  background: var(--set-surface-muted);
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.settings-switch__thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--set-text-muted);
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.settings-switch.is-on .settings-switch__track {
  background: var(--set-primary-bg);
  border-color: var(--set-primary-border);
  box-shadow: none;
}

.settings-switch.is-on .settings-switch__thumb {
  left: 21px;
  background: var(--set-primary-text);
}

.settings-switch.is-disabled {
  opacity: 0.52;
  cursor: not-allowed;
}
</style>
