<template>
  <div class="settings-number-stepper" :class="{ 'is-disabled': disabled }">
    <button type="button" class="stepper-btn" :disabled="disabled || numericValue <= min" @click="stepBy(-step)" aria-label="减少">
      <Minus :size="14" :stroke-width="2.2" />
    </button>
    <input
      class="stepper-input"
      :value="displayValue"
      :min="min"
      :max="max"
      :step="step"
      :disabled="disabled"
      inputmode="numeric"
      type="number"
      @input="onInput"
      @blur="commit($event.target.value)"
      @keydown.enter.prevent="commit($event.target.value)"
    >
    <button type="button" class="stepper-btn" :disabled="disabled || numericValue >= max" @click="stepBy(step)" aria-label="增加">
      <Plus :size="14" :stroke-width="2.2" />
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Minus, Plus } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: [Number, String], default: 0 },
  min: { type: Number, default: Number.NEGATIVE_INFINITY },
  max: { type: Number, default: Number.POSITIVE_INFINITY },
  step: { type: Number, default: 1 },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const numericValue = computed(() => normalize(props.modelValue))
const displayValue = computed(() => Number.isFinite(numericValue.value) ? String(numericValue.value) : '')

function normalize(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return clamp(0)
  return clamp(number)
}

function clamp(value) {
  return Math.min(props.max, Math.max(props.min, value))
}

function commit(value) {
  emit('update:modelValue', clamp(Number(value) || 0))
}

function onInput(event) {
  const value = event.target.value
  if (value === '' || value === '-' || value === '+') return
  commit(value)
}

function stepBy(delta) {
  emit('update:modelValue', clamp(numericValue.value + delta))
}
</script>

<style scoped>
.settings-number-stepper {
  display: inline-grid;
  grid-template-columns: 40px minmax(74px, 1fr) 40px;
  width: 100%;
  max-width: 188px;
  height: 38px;
  overflow: hidden;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.settings-number-stepper:focus-within {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.stepper-btn,
.stepper-input {
  min-width: 0;
  height: 100%;
  border: 0;
  background: transparent;
  color: inherit;
}

.stepper-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--set-text-muted);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.stepper-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.04);
  background: var(--set-surface-muted);
  color: var(--set-text-strong);
}

.stepper-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.stepper-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.stepper-input {
  border-right: 1px solid var(--set-border);
  border-left: 1px solid var(--set-border);
  text-align: center;
  font-size: 14px;
  font-weight: 650;
  outline: none;
  -moz-appearance: textfield;
}

.stepper-input::-webkit-inner-spin-button,
.stepper-input::-webkit-outer-spin-button {
  margin: 0;
  -webkit-appearance: none;
}

.settings-number-stepper.is-disabled {
  opacity: 0.58;
}
</style>
