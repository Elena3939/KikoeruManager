<template>
  <div class="processing-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">文件夹监视器</div>
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.watcher.enabled" title="启用监视器" subtitle="后台定期扫描待处理目录。" />
          <SettingsToggleRow v-model="config.watcher.auto_start" title="自动开始处理" subtitle="发现新项目后直接进入处理链路。" />
          <SettingsToggleRow v-model="config.watcher.auto_classify" title="自动分类" subtitle="监视链路里跟随分类规则落盘。" />
          <SettingsToggleRow v-model="config.watcher.delete_after_process" title="处理后删除原文件" subtitle="谨慎开启，适合完全托管的目录。" />
        </div>
        <SettingsFieldCard label="扫描间隔（秒）">
          <el-slider v-model="config.watcher.scan_interval" :min="10" :max="300" :step="10" show-input />
        </SettingsFieldCard>
      </div>

      <div class="settings-card">
        <div class="card-title">处理与解压</div>
        <div class="field-stack">
          <SettingsFieldCard label="最大并发数">
            <el-slider v-model="config.processing.max_workers" :min="1" :max="10" show-input />
          </SettingsFieldCard>
          <SettingsFieldCard label="7-Zip 路径">
            <input v-model="config.extract.seven_zip_path" class="field-input" type="text" placeholder="例如 C:\Program Files\7-Zip\7z.exe">
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.extract.auto_repair_extension" title="自动修复后缀名" subtitle="针对异常扩展名做兼容修复。" />
          <SettingsToggleRow v-model="config.extract.verify_after_extract" title="解压后验证" subtitle="解压后再做结果校验，降低脏目录风险。" />
          <SettingsToggleRow v-model="config.extract.extract_nested_archives" title="自动解压嵌套压缩包" subtitle="适合复杂包结构，但会增加处理时长。" />
          <SettingsFieldCard v-if="config.extract.extract_nested_archives" label="最大嵌套深度">
            <el-slider v-model="config.extract.max_nested_depth" :min="1" :max="10" show-input />
          </SettingsFieldCard>
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">正常解压流程</div>
        <div class="pill-switch-grid">
          <SettingsToggleChip v-for="item in autoProcessItems" :key="item.key" v-model="config.auto_process[item.key]" :label="item.label" />
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">已有文件夹流程</div>
        <div class="pill-switch-grid">
          <SettingsToggleChip v-for="item in processExistingItems" :key="item.key" v-model="config.process_existing[item.key]" :label="item.label" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsToggleChip from './SettingsToggleChip.vue'

defineProps({
  config: { type: Object, required: true }
})

const autoProcessItems = [
  { key: 'check_duplicate', label: '预检重复' },
  { key: 'import_linked_translation_subtitles', label: '字幕补配预检' },
  { key: 'extract', label: '解压文件' },
  { key: 'fetch_metadata', label: '获取元数据' },
  { key: 'rename', label: '重命名' },
  { key: 'filter', label: '文件过滤' },
  { key: 'classify', label: '智能分类' },
  { key: 'archive', label: '归档压缩包' }
]

const processExistingItems = [
  { key: 'check_duplicate', label: '预检重复' },
  { key: 'fetch_metadata', label: '获取元数据' },
  { key: 'rename', label: '重命名' },
  { key: 'filter', label: '文件过滤' },
  { key: 'import_lrc', label: '导入 LRC' },
  { key: 'classify', label: '智能分类' }
]
</script>

<style scoped>
.processing-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.pill-switch-grid,
.field-stack,
.toggle-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  color: #1d1d1f;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.field-stack,
.toggle-stack {
  display: grid;
  gap: 12px;
}

.pill-switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

/* SettingsFieldCard 默认 slot 里裸 input 的统一外观 */
.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 10px;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: rgba(148, 163, 184, 0.75); }

.field-input:focus {
  border-color: rgba(79, 70, 229, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.field-input::placeholder { color: #94a3b8; }

@media (max-width: 1200px) {
  .settings-grid.two,
  .pill-switch-grid {
    grid-template-columns: 1fr;
  }
}
</style>
