<template>
  <div class="blk-inspector">
    <div class="blk-inspector-head">
      <span class="blk-inspector-dot" :style="{ background: blockMeta.color }" />
      <span class="blk-inspector-title">{{ blockMeta.label }}</span>
      <span class="blk-inspector-type">{{ block.type }}</span>
    </div>

    <div class="blk-inspector-body">
      <!-- enabled 开关 -->
      <div class="bi-field bi-field--row">
        <span class="bi-label">启用此块</span>
        <SettingsSwitch :model-value="block.enabled" @update:model-value="setProp('__enabled', $event)" />
      </div>

      <!-- 各类型 prop 表单 -->
      <template v-for="schema in propSchema" :key="schema.key">
        <!-- hidden 字段跳过 -->
        <template v-if="schema.type !== 'hidden'">
          <!-- 富文本 -->
          <div v-if="schema.type === 'richtext'" class="bi-field">
            <span class="bi-label">{{ schema.label }}</span>
            <RichTextEditor
              :model-value="propValue('contentJson')"
              :html-cache="propValue('htmlCache') || ''"
              @update:model-value="v => setProp('contentJson', v)"
              @update:html-cache="v => setProp('htmlCache', v)"
            />
          </div>

          <!-- 变量选择：下拉 + 自定义输入 -->
          <div v-else-if="schema.type === 'variable'" class="bi-field">
            <span class="bi-label">{{ schema.label }}</span>
            <div class="bi-var-wrap">
              <!-- 下拉：直接选标签 -->
              <div class="bi-var-select-row">
                <select
                  :value="varSelectValue(schema)"
                  class="bi-select"
                  @change="onVarSelectChange(schema, $event.target.value)"
                >
                  <option
                    v-for="v in VARIABLES"
                    :key="v.key"
                    :value="v.key"
                  >{{ v.label }} — {{ v.key }}</option>
                  <option value="__custom__">⚙ 自定义变量名</option>
                </select>
              </div>
              <!-- 仅当选择"自定义"或当前值不在 registry 时展示 input -->
              <input
                v-if="isCustomVar(schema)"
                :value="propValue(schema.key, schema.default ?? '')"
                class="bi-input bi-input--mono"
                type="text"
                placeholder="自定义变量名，如 stats.duration"
                @input="setProp(schema.key, $event.target.value)"
              >
              <!-- 当前值的预览（取 sample payload 的示例值） -->
              <div class="bi-var-preview" :title="`将渲染为：${currentVarExample(schema)}`">
                <span class="bi-var-pill">
                  <span class="bi-var-pill-dot" />
                  <span>{{ propValue(schema.key, schema.default) || '?' }}</span>
                </span>
                <span class="bi-var-preview-arrow">→</span>
                <span class="bi-var-preview-val">{{ currentVarExample(schema) || '（无示例值）' }}</span>
              </div>
            </div>
          </div>

          <!-- 颜色 -->
          <div v-else-if="schema.type === 'color'" class="bi-field bi-field--row">
            <span class="bi-label">{{ schema.label }}</span>
            <div class="bi-color-wrap">
              <input
                :value="propValue(schema.key, schema.default ?? '#000000')"
                type="color"
                class="bi-color-swatch"
                @input="setProp(schema.key, $event.target.value)"
              >
              <input
                :value="propValue(schema.key, schema.default ?? '#000000')"
                type="text"
                class="bi-input bi-input--mono bi-input--sm"
                @input="setProp(schema.key, $event.target.value)"
              >
            </div>
          </div>

          <!-- 数字 -->
          <div v-else-if="schema.type === 'number'" class="bi-field bi-field--row">
            <span class="bi-label">{{ schema.label }}</span>
            <div class="bi-num-wrap">
              <input
                :value="propValue(schema.key, schema.default ?? 0)"
                type="range"
                :min="schema.min ?? 0"
                :max="schema.max ?? 100"
                class="bi-range"
                @input="setProp(schema.key, Number($event.target.value))"
              >
              <span class="bi-num-val">{{ propValue(schema.key, schema.default ?? 0) }}px</span>
            </div>
          </div>

          <!-- 数据来源选择（业务块用） -->
          <div v-else-if="schema.type === 'data_source'" class="bi-field">
            <span class="bi-label">{{ schema.label }}</span>
            <select
              :value="propValue(schema.key, schema.default ?? '')"
              class="bi-select"
              @change="setProp(schema.key, $event.target.value)"
            >
              <option
                v-for="opt in schema.options"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</option>
            </select>
            <div class="bi-data-source-hint">
              <span class="bi-var-pill"><span class="bi-var-pill-dot" /><span>{{ propValue(schema.key, schema.default ?? '') }}</span></span>
              <span class="bi-data-source-hint-text">从 payload 的此字段读取数据</span>
            </div>
          </div>

          <!-- 统计字段动态列表（stats_grid 专用） -->
          <div v-else-if="schema.type === 'stats_items'" class="bi-field">
            <span class="bi-label">{{ schema.label }}</span>
            <div class="bi-stats-list">
              <div
                v-for="(item, idx) in (propValue(schema.key, []) || [])"
                :key="idx"
                class="bi-stats-item"
              >
                <input
                  :value="item.icon || ''"
                  class="bi-input bi-input--icon"
                  type="text"
                  placeholder="🎵"
                  maxlength="2"
                  @input="updateStatsItem(schema.key, idx, 'icon', $event.target.value)"
                >
                <input
                  :value="item.label || ''"
                  class="bi-input bi-stats-input"
                  type="text"
                  placeholder="字段标签"
                  @input="updateStatsItem(schema.key, idx, 'label', $event.target.value)"
                >
                <input
                  :value="item.key || ''"
                  class="bi-input bi-input--mono bi-stats-input"
                  type="text"
                  placeholder="stats.字段名"
                  @input="updateStatsItem(schema.key, idx, 'key', $event.target.value)"
                >
                <button
                  type="button"
                  class="bi-stats-rm"
                  title="删除"
                  @click="removeStatsItem(schema.key, idx)"
                >×</button>
              </div>
              <button type="button" class="bi-stats-add" @click="addStatsItem(schema.key)">
                + 添加字段
              </button>
            </div>
          </div>

          <!-- 文本 -->
          <div v-else class="bi-field">
            <span class="bi-label">{{ schema.label }}</span>
            <input
              :value="propValue(schema.key, schema.default ?? '')"
              type="text"
              class="bi-input"
              @input="setProp(schema.key, $event.target.value)"
            >
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { BLOCK_TYPES, VARIABLES } from './blockTypes.js'
import SettingsSwitch from '../SettingsSwitch.vue'
import RichTextEditor from './RichTextEditor.vue'

const props = defineProps({
  block: { type: Object, required: true },
})
const emit = defineEmits(['update'])

const blockMeta  = computed(() => BLOCK_TYPES[props.block.type] || { label: props.block.type, color: '#8e8e93' })
const propSchema = computed(() => blockMeta.value.propSchema || [])

// 直接从 props.block.props 读取，不再用本地副本，避免切块残留旧字段。
// 父组件用 :key="block.id" 强制重建，所以不会有抖动。
function propValue(key, fallback = undefined) {
  const v = props.block.props?.[key]
  return v === undefined || v === null ? fallback : v
}

function setProp(key, value) {
  if (key === '__enabled') {
    emit('update', { ...props.block, enabled: value })
    return
  }
  const newProps = { ...(props.block.props || {}), [key]: value }
  emit('update', { ...props.block, props: newProps })
}

// ---- 变量字段助手 ----
const VAR_KEYS = new Set(VARIABLES.map(v => v.key))
// 记录"用户主动选了自定义"的字段，避免输入到一半就因 key 进入 VAR_KEYS 而切回下拉
const customVarFields = ref(new Set())

function isVarRegistered(value) {
  return VAR_KEYS.has(String(value || ''))
}

function isCustomVar(schema) {
  if (customVarFields.value.has(schema.key)) return true
  const cur = propValue(schema.key, schema.default ?? '')
  return cur !== '' && !isVarRegistered(cur)
}

function varSelectValue(schema) {
  if (isCustomVar(schema)) return '__custom__'
  return propValue(schema.key, schema.default ?? '')
}

function onVarSelectChange(schema, value) {
  if (value === '__custom__') {
    customVarFields.value.add(schema.key)
    // 若当前已是注册变量，清空给用户输入空间
    if (isVarRegistered(propValue(schema.key))) setProp(schema.key, '')
  } else {
    customVarFields.value.delete(schema.key)
    setProp(schema.key, value)
  }
}

// ─── stats_items 动态列表助手 ───
function updateStatsItem(propKey, idx, field, value) {
  const list = [...(propValue(propKey, []) || [])]
  list[idx] = { ...(list[idx] || {}), [field]: value }
  setProp(propKey, list)
}
function removeStatsItem(propKey, idx) {
  const list = [...(propValue(propKey, []) || [])]
  list.splice(idx, 1)
  setProp(propKey, list)
}
function addStatsItem(propKey) {
  const list = [...(propValue(propKey, []) || [])]
  list.push({ key: '', label: '', icon: '' })
  setProp(propKey, list)
}

function currentVarExample(schema) {
  const cur = String(propValue(schema.key, schema.default ?? '') || '')
  const v = VARIABLES.find(x => x.key === cur)
  return v?.example ?? ''
}
</script>

<style scoped>
.blk-inspector {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex: 1;
  min-height: 0;
}

.blk-inspector-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px 10px;
  border-bottom: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  flex-shrink: 0;
}

.blk-inspector-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: none;
}

.blk-inspector-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--set-text-strong);
  flex: 1;
  min-width: 0;
}

.blk-inspector-type {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--set-text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: var(--set-surface-muted);
  padding: 2px 7px;
  border-radius: 5px;
}

.blk-inspector-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.bi-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bi-field--row {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.bi-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--set-text-muted);
  text-transform: uppercase;
}

.bi-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  font-size: 12.5px;
  color: var(--set-text-strong);
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  border-radius: 8px;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.bi-input--mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
}
.bi-stats-input {
  flex: 1;
  min-width: 0;
  width: auto !important;
}
.bi-input--icon {
  width: 36px;
  text-align: center;
  font-size: 14px;
  padding: 6px 4px;
  flex: 0 0 36px;
}

/* 数据来源选择 - 提示 */
.bi-data-source-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 6px 10px;
  background: var(--set-surface-soft, rgba(0, 0, 0, 0.03));
  border-radius: 6px;
  font-size: 11px;
  color: var(--set-text);
}
.bi-data-source-hint-text {
  color: var(--set-text-muted);
  font-size: 10.5px;
}

/* stats_items 动态列表 */
.bi-stats-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bi-stats-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.bi-stats-rm {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid rgba(217, 48, 37, 0.2);
  border-radius: 5px;
  color: #d93025;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  transition: all 0.15s;
  flex-shrink: 0;
}
.bi-stats-rm:hover {
  background: rgba(217, 48, 37, 0.08);
  border-color: rgba(217, 48, 37, 0.4);
}
.bi-stats-add {
  padding: 7px 10px;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--set-text-strong, #1d1d1f);
  background: var(--set-surface-soft, rgba(0, 0, 0, 0.03));
  border: 1px dashed var(--set-border, rgba(29, 29, 31, 0.12));
  border-radius: 6px;
  cursor: pointer;
  text-align: center;
  transition: all 0.15s;
}
.bi-stats-add:hover {
  background: var(--set-surface-hover, rgba(0, 0, 0, 0.05));
  border-color: var(--set-border-strong, rgba(29, 29, 31, 0.2));
}

.bi-input--sm { width: 88px; }

.bi-input:focus {
  border-color: var(--set-border-strong, rgba(29, 29, 31, 0.2));
  box-shadow: 0 0 0 3px var(--set-focus-ring, rgba(15, 23, 42, 0.08));
}

/* 变量选择 */
.bi-var-wrap { display: flex; flex-direction: column; gap: 6px; }
.bi-var-select-row { display: flex; gap: 6px; }
.bi-select {
  flex: 1;
  width: 100%;
  padding: 7px 10px;
  font-size: 12.5px;
  color: var(--set-text-strong);
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  border-radius: 8px;
  outline: none;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.bi-select:focus {
  border-color: var(--set-border-strong, rgba(29, 29, 31, 0.2));
  box-shadow: 0 0 0 3px var(--set-focus-ring, rgba(15, 23, 42, 0.08));
}

.bi-var-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--set-surface-soft, rgba(0, 0, 0, 0.03));
  border-radius: 6px;
  font-size: 11px;
  color: var(--set-text);
}
/* BlockNote 风格变量 pill */
.bi-var-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 9px 1px 6px;
  font-size: 11px;
  font-weight: 500;
  color: #f5f5f7;
  background: #2a2d34;
  border: 1px solid #3a3d45;
  border-radius: 99px;
  white-space: nowrap;
  flex-shrink: 0;
}
.bi-var-pill-dot {
  width: 5px;
  height: 5px;
  background: var(--set-tag-info-text, #c7d2fe);
  transform: rotate(45deg);
  border-radius: 1px;
  flex-shrink: 0;
}
.bi-var-preview-arrow {
  color: var(--set-text-subtle);
  font-size: 11px;
  flex-shrink: 0;
}
.bi-var-preview-val {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--set-text-strong);
  font-weight: 500;
}

/* 颜色 */
.bi-color-wrap { display: flex; align-items: center; gap: 8px; }

.bi-color-swatch {
  width: 30px;
  height: 30px;
  padding: 2px;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  cursor: pointer;
  background: none;
  flex-shrink: 0;
}

/* 数字滑块 */
.bi-num-wrap { display: flex; align-items: center; gap: 8px; }
.bi-range { flex: 1; accent-color: var(--set-text-muted, #64748b); }
.bi-num-val {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: var(--set-text-muted);
  min-width: 32px;
  text-align: right;
}
</style>
