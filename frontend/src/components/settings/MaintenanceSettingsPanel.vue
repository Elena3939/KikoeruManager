<template>
  <div class="maintenance-stack">
    <DatabaseShrinkCard />

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">密码库智能清理</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.password_cleanup.enabled" title="启用自动清理" subtitle="按使用次数和保留天数自动清理密码库。" />
          <div class="mini-grid two">
            <SettingsFieldCard label="使用次数阈值">
              <SettingsRangeStepper v-model="config.password_cleanup.max_use_count" :min="0" :max="10" />
            </SettingsFieldCard>
            <SettingsFieldCard label="保留天数">
              <SettingsRangeStepper v-model="config.password_cleanup.preserve_days" :min="1" :max="90" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="Cron 表达式">
            <input v-model="config.password_cleanup.cron_expression" class="field-input" type="text" placeholder="0 0 * * 0">
          </SettingsFieldCard>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">已处理压缩包清理</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.archive_cleanup.enabled" title="启用自动清理" subtitle="按天数和保底数量控制已处理压缩包规模。" />
          <div class="mini-grid two">
            <SettingsFieldCard label="保留天数">
              <SettingsRangeStepper v-model="config.archive_cleanup.preserve_days" :min="1" :max="90" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最小保留数量">
              <SettingsNumberStepper v-model="config.archive_cleanup.min_keep_count" :min="0" :max="100" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="Cron 表达式">
            <input v-model="config.archive_cleanup.cron_expression" class="field-input" type="text" placeholder="0 0 * * 0">
          </SettingsFieldCard>
        </div>
      </div>
    </div>

    <div class="settings-card">
      <div class="card-title">库存打包</div>
      <div class="settings-grid two">
        <div class="field-stack">
          <SettingsToggleRow v-model="config.backup_zip.enabled" title="启用库存打包" subtitle="按压缩参数把指定目录输出为发布包。" />
          <SettingsFieldCard label="源目录">
            <input v-model="config.backup_zip.source_path" class="field-input" type="text" placeholder="要打包的目录">
          </SettingsFieldCard>
          <SettingsFieldCard label="输出目录">
            <input v-model="config.backup_zip.output_dir" class="field-input" type="text" placeholder="打包结果输出目录">
          </SettingsFieldCard>
        </div>
        <div class="field-stack">
          <SettingsFieldCard label="临时复制目录">
            <input v-model="config.backup_zip.path_copy_target" class="field-input" type="text" placeholder="可选中转目录">
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="压缩格式">
              <AppDropdown
                v-model="config.backup_zip.archive_format"
                :options="archiveFormatOptions"
                class="settings-field-dd"
              />
            </SettingsFieldCard>
            <SettingsFieldCard label="压缩级别">
              <SettingsNumberStepper v-model="config.backup_zip.compression_level" :min="0" :max="9" />
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow v-model="config.backup_zip.copy_structure_before_zip" title="复制结构后再压缩" subtitle="先生成中转目录再做归档，更适合复杂结构。" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsRangeStepper from './SettingsRangeStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'
import DatabaseShrinkCard from './DatabaseShrinkCard.vue'

defineProps({
  config: { type: Object, required: true }
})

const archiveFormatOptions = [
  { value: 'zip', label: 'zip' },
  { value: '7z', label: '7z' }
]
</script>

<style scoped>
.maintenance-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.mini-grid,
.field-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.mini-grid { display: grid; gap: 10px; }
.mini-grid.two { grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); }

.field-stack {
  display: grid;
  gap: 12px;
}

.settings-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  min-height: 0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 14px;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: var(--set-border-strong); }

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.field-input::placeholder { color: var(--set-text-subtle); }

/* AppDropdown 收敛 */
.settings-field-dd {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-root) {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) {
  border-color: var(--set-border-strong);
}

.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two { grid-template-columns: 1fr; }
}
</style>
