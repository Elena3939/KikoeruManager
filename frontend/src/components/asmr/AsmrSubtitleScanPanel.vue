<template>
  <section class="asmr-card">
    <header class="asmr-card-head">
      <div class="asmr-card-head-title">
        <FolderSearch :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
        <h2>字幕文件夹扫描</h2>
      </div>
    </header>
    <div class="asmr-card-body">
      <div class="scan-input-row">
        <el-input
          :model-value="modelValue"
          placeholder="输入包含字幕文件的文件夹路径"
          clearable
          class="scan-input"
          @update:model-value="$emit('update:modelValue', $event)"
        />
      </div>
    </div>
  </section>
</template>

<script setup>
import { FolderSearch } from 'lucide-vue-next'

defineProps({
  modelValue: { type: String, default: '' }
})

defineEmits(['update:modelValue'])
</script>

<style scoped>
.asmr-card {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-border);
  box-shadow: var(--asmr-card-shadow);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
}
.asmr-card-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.asmr-card-head-title h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--asmr-text-strong);
}
.asmr-card-head-icon {
  color: var(--asmr-accent);
  flex-shrink: 0;
}
.asmr-card-body {
  padding: 16px 18px;
}
.scan-input-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.scan-input {
  flex: 1 1 auto;
  min-width: 0;
}
.scan-input :deep(.el-input__wrapper) {
  background: var(--asmr-field-bg);
  border: 1px solid var(--asmr-border);
  box-shadow: none;
}
.scan-input :deep(.el-input__wrapper:hover),
.scan-input :deep(.el-input__wrapper.is-focus) {
  background: var(--asmr-field-bg-focus);
  border-color: var(--asmr-border-strong);
  box-shadow: 0 0 0 3px var(--asmr-focus-ring);
}
.scan-input :deep(.el-input__inner) {
  color: var(--asmr-text-strong);
}
.scan-input :deep(.el-input__inner::placeholder) {
  color: var(--asmr-field-placeholder);
}
@media (max-width: 640px) {
  .asmr-card {
    border-radius: 12px;
  }
  .asmr-card-head,
  .asmr-card-body {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
