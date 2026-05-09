<template>
  <div class="rules-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">过滤规则</div>
        <div class="toggle-stack compact">
          <SettingsToggleRow v-model="config.filter.filter_dir" title="过滤文件夹" subtitle="把规则同时应用到目录名。" />
        </div>
        <div class="rule-stack">
          <div v-for="(rule, index) in config.filter.rules" :key="`filter-${index}`" class="rule-row">
            <AppDropdown
              v-model="rule.target"
              :options="filterRuleTargetOptions"
              class="rule-target"
              :width="110"
              :menu-min-width="130"
              :show-trigger-badge="false"
            />
            <input v-model="rule.name" class="field-input" type="text" placeholder="规则名称">
            <input v-model="rule.pattern" class="field-input" type="text" placeholder="正则表达式">
            <el-switch v-model="rule.enabled" />
            <button type="button" class="icon-btn danger" @click="config.filter.rules.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
          </div>
          <button type="button" class="ghost-inline-btn" @click="addFilterRule"><Plus :size="14" :stroke-width="2.4" /> 添加过滤规则</button>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">重命名与落盘</div>
        <div class="field-stack">
          <SettingsFieldCard label="重命名模板">
            <input v-model="config.rename.template" class="field-input" type="text" placeholder="{rjcode} {work_name}">
          </SettingsFieldCard>
          <SettingsFieldCard label="日期格式">
            <input v-model="config.rename.date_format" class="field-input" type="text" placeholder="%y%m%d">
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.rename.api_rename_follow_template" title="API 重命名遵循模板" subtitle="库存里的 API 重命名也统一走模板。" />
          <SettingsToggleRow v-model="config.rename.use_japanese_metadata" title="使用日语元数据" subtitle="让 maker、CV、tags 等优先取日语元数据。" />
          <SettingsToggleRow v-model="config.rename.exclude_square_brackets" title="移除方括号内容" subtitle="重命名前先剔除方括号片段。" />
          <SettingsToggleRow v-model="config.rename.illegal_char_to_full_width" title="非法字符转全角" subtitle="降低 Windows 文件名报错概率。" />
          <SettingsToggleRow v-model="config.rename.flatten_single_subfolder" title="自动扁平化单层文件夹" subtitle="过滤之后顺手把单层嵌套压平。" />
          <SettingsFieldCard v-if="config.rename.flatten_single_subfolder" label="扁平化深度">
            <el-input-number v-model="config.rename.flatten_depth" :min="1" :max="10" class="field-number" />
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.rename.remove_empty_folders" title="自动移除空文件夹" subtitle="过滤和扁平化后清理空目录。" />
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">分类规则</div>
        <div class="rule-stack">
          <div v-for="(rule, index) in config.classification" :key="rule.id || index" class="classification-row">
            <AppDropdown
              v-model="rule.type"
              :options="classificationTypeOptions"
              class="rule-target"
              :width="120"
              :menu-min-width="140"
              :show-trigger-badge="false"
            />
            <input v-model="rule.path_template" class="field-input" type="text" placeholder="路径模板">
            <input v-model="rule.custom_name" class="field-input" type="text" placeholder="自定义目录名">
            <input v-model="rule.rjcode_range" class="field-input" type="text" placeholder="RJ 段，例如 RJ01000000-RJ01999999">
            <el-switch v-model="rule.enabled" />
            <button type="button" class="icon-btn danger" @click="config.classification.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
          </div>
          <button type="button" class="ghost-inline-btn" @click="addRule"><Plus :size="14" :stroke-width="2.4" /> 添加分类规则</button>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">路径映射</div>
        <SettingsToggleRow v-model="config.path_mapping_enabled" title="启用路径映射" subtitle="跨设备打开路径时自动换算。" />
        <div class="rule-stack">
          <div v-for="(mapping, index) in config.path_mappings" :key="`mapping-${index}`" class="rule-row">
            <input v-model="mapping.original" class="field-input" type="text" placeholder="原始路径">
            <input v-model="mapping.mapped" class="field-input" type="text" placeholder="映射路径">
            <button type="button" class="icon-btn danger" @click="config.path_mappings.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
          </div>
          <button type="button" class="ghost-inline-btn" @click="addPathMapping"><Plus :size="14" :stroke-width="2.4" /> 添加映射规则</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Plus, Trash2 } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'

// 「过滤规则」作用范围选项
const filterRuleTargetOptions = [
  { value: 'file', label: '文件' },
  { value: 'folder', label: '文件夹' },
  { value: 'all', label: '全部' },
]

// 「分类规则」类型选项
const classificationTypeOptions = [
  { value: 'none', label: '不分类' },
  { value: 'maker', label: '按社团' },
  { value: 'series', label: '按系列' },
  { value: 'rjcode', label: '按 RJ 段' },
]

const props = defineProps({
  config: { type: Object, required: true }
})

function addFilterRule() {
  props.config.filter.rules.push({
    name: '新规则',
    pattern: '',
    target: 'file',
    action: 'exclude',
    enabled: true
  })
}

function addRule() {
  props.config.classification.push({
    id: Date.now(),
    type: 'none',
    path_template: '',
    custom_name: '',
    rjcode_range: '',
    enabled: true
  })
}

function addPathMapping() {
  props.config.path_mappings.push({
    original: '',
    mapped: ''
  })
}
</script>

<style scoped>
.rules-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.field-stack,
.toggle-stack,
.rule-stack {
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
.toggle-stack,
.rule-stack {
  display: grid;
  gap: 12px;
}

.toggle-stack.compact {
  margin-bottom: 12px;
  gap: 8px;
}

/* SettingsFieldCard slot 里裸 input 的统一外观 */
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

/* el-input-number 与 input 视觉对齐 */
.field-number :deep(.el-input__wrapper) {
  min-height: 38px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: none;
  border: 1px solid rgba(226, 232, 240, 0.85) !important;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-number :deep(.el-input__wrapper:hover) {
  border-color: rgba(148, 163, 184, 0.75) !important;
  box-shadow: none;
}

.field-number :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(79, 70, 229, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
}

/* 规则行 grid 结构 */
.rule-row,
.classification-row {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) minmax(0, 1.1fr) auto auto;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.rule-row:hover,
.classification-row:hover {
  border-color: rgba(148, 163, 184, 0.75);
  background: rgba(248, 250, 252, 0.5);
}

.classification-row {
  grid-template-columns: 130px minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.2fr) auto auto;
}

.rule-target :deep(.el-select__wrapper) {
  min-height: 36px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0 !important;
  box-shadow: none;
}

/* ghost 内联按钮 / icon 按钮 */
.ghost-inline-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ghost-inline-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.55);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.85) 0%, #ffffff 100%);
  color: #4f46e5;
}

.ghost-inline-btn:not(:disabled):active { transform: scale(0.97); }
.ghost-inline-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.icon-btn:hover { transform: translateY(-1px); border-color: rgba(148, 163, 184, 0.75); }
.icon-btn:active { transform: scale(0.94); }

.icon-btn.danger { color: #e11d48; border-color: rgba(244, 63, 94, 0.4); }

.icon-btn.danger:hover {
  background: linear-gradient(135deg, rgba(254, 226, 226, 0.6) 0%, #ffffff 100%);
  border-color: rgba(244, 63, 94, 0.7);
  color: #be123c;
}

@media (max-width: 1200px) {
  .settings-grid.two { grid-template-columns: 1fr; }
  .rule-row,
  .classification-row { grid-template-columns: 1fr; }
}
</style>
