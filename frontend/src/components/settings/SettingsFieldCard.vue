<template>
  <label class="sfc" :class="{ 'is-inline': inline }">
    <span v-if="label || $slots.label" class="sfc-label">
      <slot name="label">{{ label }}</slot>
    </span>
    <div class="sfc-control">
      <slot />
    </div>
    <small v-if="hint || $slots.hint" class="sfc-hint">
      <slot name="hint">{{ hint }}</slot>
    </small>
  </label>
</template>

<script setup>
/* 设置页字段原子：label + 单行控件 slot + 可选 hint。
 * 父侧直接把 input / el-input-number / el-slider / AppDropdown / AnimatedPasswordInput 丢到默认 slot 即可。
 * 开启 inline 时左右排布（label | 控件），常用于 chip 风 slider 行。
 */
defineProps({
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  inline: { type: Boolean, default: false },
})
</script>

<style scoped>
.sfc {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 0;
  border-bottom: none;
  min-width: 0;
}

.sfc.is-inline {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.sfc.is-inline .sfc-label {
  flex: 0 0 auto;
  margin: 0;
}

.sfc.is-inline .sfc-control {
  flex: 1 1 auto;
  min-width: 0;
}

.sfc-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.05px;
}

.sfc-control {
  display: contents;
}

.sfc.is-inline .sfc-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sfc-hint {
  color: rgba(29, 29, 31, 0.5);
  font-size: 11.5px;
  line-height: 1.55;
  letter-spacing: -0.05px;
}
</style>
