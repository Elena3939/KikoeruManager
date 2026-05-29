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
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, #fbfcfe 0%, #f8fafc 100%);
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
  color: #0f172a;
}
.asmr-card-head-icon {
  color: #2563eb;
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
