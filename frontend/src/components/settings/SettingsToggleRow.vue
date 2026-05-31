<template>
  <label class="str" :class="{ 'is-disabled': disabled }">
    <span class="str-text">
      <strong class="str-title">
        <slot name="title">{{ title }}</slot>
      </strong>
      <small v-if="subtitle || $slots.subtitle" class="str-subtitle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </small>
    </span>
    <span class="str-control">
      <slot name="control">
        <SettingsSwitch
          :model-value="modelValue"
          :disabled="disabled"
          @update:model-value="(v) => emit('update:modelValue', v)"
          @change="(v) => emit('change', v)"
        />
      </slot>
    </span>
  </label>
</template>

<script setup>
import SettingsSwitch from './SettingsSwitch.vue'

/* 设置页开关行原子：左 title + subtitle，右侧默认使用中性 SettingsSwitch。
 * 如果需要自定义控件（比如按钮 / 数字输入），可通过 control slot 覆写。
 */
defineProps({
  modelValue: { type: [Boolean, String, Number], default: false },
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])
</script>

<style scoped>
.str {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 0;
  border-bottom: none;
  min-width: 0;
}

.str.is-disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.str-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.str-title {
  display: block;
  color: var(--set-text-strong, #0f172a);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: -0.05px;
}

.str-subtitle {
  display: block;
  margin-top: 3px;
  color: var(--set-text-muted, #94a3b8);
  font-size: 12px;
  line-height: 1.5;
  letter-spacing: -0.05px;
}

.str-control {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
}
</style>
