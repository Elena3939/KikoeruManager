<template>
  <div class="settings-range-stepper" :class="{ 'is-disabled': disabled }">
    <div class="range-shell">
      <input
        class="range-input"
        type="range"
        :value="numericValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        :style="{ '--range-progress': `${progress}%` }"
        @input="updateValue($event.target.value)"
      >
    </div>
    <SettingsNumberStepper
      :model-value="numericValue"
      :min="min"
      :max="max"
      :step="step"
      :disabled="disabled"
      @update:model-value="updateValue"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'

const props = defineProps({
  modelValue: { type: [Number, String], default: 0 },
  min: { type: Number, default: 0 },
  max: { type: Number, default: 100 },
  step: { type: Number, default: 1 },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const numericValue = computed(() => normalize(props.modelValue))
const progress = computed(() => {
  const span = props.max - props.min
  if (!Number.isFinite(span) || span <= 0) return 0
  return Math.min(100, Math.max(0, ((numericValue.value - props.min) / span) * 100))
})

function normalize(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return props.min
  return Math.min(props.max, Math.max(props.min, number))
}

function updateValue(value) {
  emit('update:modelValue', normalize(value))
}
</script>

<style scoped>
.settings-range-stepper {
  display: grid;
  grid-template-columns: minmax(72px, 1fr) minmax(128px, auto);
  gap: 12px;
  align-items: center;
  width: 100%;
  max-width: min(100%, 360px);
  min-width: 0;
}

.range-shell {
  display: flex;
  align-items: center;
  min-width: 0;
  height: 38px;
}

.range-input {
  width: 100%;
  height: 6px;
  border: 0;
  border-radius: 999px;
  outline: none;
  cursor: pointer;
  appearance: none;
  background:
    linear-gradient(
      90deg,
      var(--set-range-fill, var(--set-text-muted)) 0%,
      var(--set-range-fill, var(--set-text-muted)) var(--range-progress),
      var(--set-range-track, var(--set-surface-muted)) var(--range-progress),
      var(--set-range-track, var(--set-surface-muted)) 100%
    );
}

.range-input::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background: transparent;
}

.range-input::-webkit-slider-thumb {
  width: 18px;
  height: 18px;
  margin-top: -6px;
  border: 1px solid var(--set-range-thumb-border, var(--set-border-strong));
  border-radius: 999px;
  appearance: none;
  background: var(--set-range-thumb, var(--set-text-strong));
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.16);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease;
}

.range-input::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: var(--set-range-track, var(--set-surface-muted));
}

.range-input::-moz-range-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--set-range-fill, var(--set-text-muted));
}

.range-input::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border: 1px solid var(--set-range-thumb-border, var(--set-border-strong));
  border-radius: 999px;
  background: var(--set-range-thumb, var(--set-text-strong));
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.16);
}

.range-input:hover::-webkit-slider-thumb {
  transform: scale(1.08);
}

.range-input:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 4px var(--set-focus-ring);
}

.settings-range-stepper.is-disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.settings-range-stepper.is-disabled .range-input {
  cursor: not-allowed;
}

@media (max-width: 700px) {
  .settings-range-stepper {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
</style>
