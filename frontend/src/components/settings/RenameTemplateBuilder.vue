<template>
  <div class="rename-template-builder">
    <div
      ref="templateCanvas"
      class="template-canvas"
      :class="{ 'is-empty': !blocks.length }"
    >
      <div v-if="!blocks.length" class="empty-template">模板为空</div>

      <div
        v-for="(block, index) in blocks"
        :key="block.id"
        :data-block-id="block.id"
        class="template-block"
        :class="`is-${block.type}`"
      >
        <button
          type="button"
          class="block-grip"
          title="拖动调整顺序"
        >
          <GripVertical :size="14" :stroke-width="2.4" />
        </button>

        <template v-if="block.type === 'variable'">
          <Braces :size="14" :stroke-width="2.4" class="block-kind-icon" />
          <span class="variable-label">{{ variableLabel(block.value) }}</span>
          <code>{{ variableToken(block.value) }}</code>
        </template>
        <input
          v-else
          v-model="block.value"
          class="text-block-input"
          type="text"
          aria-label="自定义模板文本"
          :style="{ width: textBlockWidth(block.value) }"
          @input="commit"
          @blur="removeEmptyTextBlock(index)"
        >

        <button
          type="button"
          class="block-action is-remove"
          title="删除"
          @click="removeBlock(index)"
        >
          <X :size="12" :stroke-width="2.7" />
        </button>
      </div>
    </div>

    <div class="template-toolbar">
      <div class="template-add-control">
        <AppDropdown
          v-model="selectedVariables"
          :options="variableOptions"
          multiple
          placeholder="选择字段"
          :menu-min-width="240"
          :show-trigger-badge="false"
          class="variable-picker"
          @change="applyVariableSelection"
        />
        <span class="control-divider" />
        <input
          v-model="customText"
          type="text"
          placeholder="输入符号或文字后添加"
          @keydown.enter.prevent="addTextBlock"
        >
        <button
          type="button"
          class="builder-icon-btn"
          title="添加自定义文本"
          :disabled="!customText"
          @click="addTextBlock"
        >
          <Plus :size="15" :stroke-width="2.5" />
        </button>
      </div>

      <div class="wrapper-control">
        <div class="wrapper-toggle">
          <span>字段括号</span>
          <SettingsSwitch
            v-model="wrapperEnabled"
            @change="commitWrapperSettings"
          />
        </div>
        <div class="wrapper-inputs" :class="{ 'is-disabled': !wrapperEnabled }">
          <label>
            <span>左</span>
            <input
              v-model="wrapperLeft"
              type="text"
              maxlength="8"
              :disabled="!wrapperEnabled"
              aria-label="字段左括号"
              @input="commitWrapperSettings"
            >
          </label>
          <label>
            <span>右</span>
            <input
              v-model="wrapperRight"
              type="text"
              maxlength="8"
              :disabled="!wrapperEnabled"
              aria-label="字段右括号"
              @input="commitWrapperSettings"
            >
          </label>
        </div>
      </div>
    </div>

    <div class="template-result">
      <span>模板值</span>
      <code>{{ serializedTemplate || '空模板' }}</code>
    </div>
    <div class="template-result is-preview">
      <span>参考重命名</span>
      <strong>{{ previewName || '空模板' }}</strong>
    </div>
  </div>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import Sortable from 'sortablejs'
import {
  Braces,
  GripVertical,
  Plus,
  X,
} from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import SettingsSwitch from './SettingsSwitch.vue'
import {
  getRenameTemplateVariable,
  parseRenameTemplateForBuilder,
  RENAME_TEMPLATE_VARIABLES,
  serializeRenameTemplate,
} from './renameTemplate'

const props = defineProps({
  modelValue: { type: String, default: '' },
  wrapperEnabled: { type: Boolean, default: true },
  wrapperLeft: { type: String, default: '[' },
  wrapperRight: { type: String, default: ']' },
})

const emit = defineEmits([
  'update:modelValue',
  'update:wrapperEnabled',
  'update:wrapperLeft',
  'update:wrapperRight',
])

let blockSequence = 0
const blocks = ref([])
const templateCanvas = ref(null)
const selectedVariables = ref([])
const customText = ref('')
const wrapperEnabled = ref(props.wrapperEnabled)
const wrapperLeft = ref(props.wrapperLeft)
const wrapperRight = ref(props.wrapperRight)
let sortable = null

const variableOptions = RENAME_TEMPLATE_VARIABLES.map((variable) => ({
  value: variable.value,
  label: variable.label,
  suffix: variable.token,
}))

const wrapperOptions = computed(() => ({
  wrapperEnabled: wrapperEnabled.value,
  wrapperLeft: wrapperLeft.value,
  wrapperRight: wrapperRight.value,
}))

const serializedTemplate = computed(() => serializeRenameTemplate(
  blocks.value,
  wrapperOptions.value,
))

const previewName = computed(() => {
  const sampleValues = {
    rjcode: 'RJ01670873',
    work_name: '怪異快楽',
    maker_id: 'RG64225',
    maker_name: '生ハメ堕ち部★LACK',
    original_maker_name: '生ハメ堕ち部★LACK',
    translator_name: 'みんなで翻訳',
    release_date: '260725',
    cvs: '(CV 示例声优)',
    tags: '标签',
  }
  return RENAME_TEMPLATE_VARIABLES.reduce(
    (result, variable) => result.replaceAll(
      variable.token,
      sampleValues[variable.value] || '',
    ),
    serializedTemplate.value,
  )
})

function createBlock(block) {
  blockSequence += 1
  return {
    ...block,
    id: `rename-template-block-${blockSequence}`,
  }
}

function syncVariableSelection() {
  selectedVariables.value = [
    ...new Set(
      blocks.value
        .filter((block) => block.type === 'variable')
        .map((block) => block.value),
    ),
  ]
}

function hydrate(template) {
  blocks.value = parseRenameTemplateForBuilder(
    template,
    wrapperOptions.value,
  ).map(createBlock)
  syncVariableSelection()
  commit()
}

function commit() {
  const nextTemplate = serializeRenameTemplate(
    blocks.value,
    wrapperOptions.value,
  )
  if (nextTemplate !== props.modelValue) {
    emit('update:modelValue', nextTemplate)
  }
}

function applyVariableSelection(values) {
  const selected = new Set(Array.isArray(values) ? values : [])
  blocks.value = blocks.value.filter(
    (block) => block.type !== 'variable' || selected.has(block.value),
  )

  const existing = new Set(
    blocks.value
      .filter((block) => block.type === 'variable')
      .map((block) => block.value),
  )
  for (const value of selected) {
    if (!existing.has(value) && getRenameTemplateVariable(value)) {
      blocks.value.push(createBlock({ type: 'variable', value }))
    }
  }
  commit()
}

function addTextBlock() {
  if (!customText.value) return
  blocks.value.push(createBlock({ type: 'text', value: customText.value }))
  customText.value = ''
  commit()
}

function commitWrapperSettings() {
  emit('update:wrapperEnabled', wrapperEnabled.value)
  emit('update:wrapperLeft', wrapperLeft.value)
  emit('update:wrapperRight', wrapperRight.value)
  commit()
}

function removeBlock(index) {
  blocks.value.splice(index, 1)
  syncVariableSelection()
  commit()
}

function removeEmptyTextBlock(index) {
  if (blocks.value[index]?.type === 'text' && blocks.value[index].value === '') {
    removeBlock(index)
  }
}

function moveBlock(fromIndex, toIndex) {
  if (
    fromIndex < 0
    || toIndex < 0
    || fromIndex >= blocks.value.length
    || toIndex >= blocks.value.length
    || fromIndex === toIndex
  ) return

  const [block] = blocks.value.splice(fromIndex, 1)
  blocks.value.splice(toIndex, 0, block)
  commit()
}

function variableLabel(value) {
  return getRenameTemplateVariable(value)?.label || value
}

function variableToken(value) {
  return getRenameTemplateVariable(value)?.token || ''
}

function textBlockWidth(value) {
  const length = Array.from(String(value || '')).length
  return `${Math.min(240, Math.max(42, length * 9 + 24))}px`
}

watch(
  () => props.modelValue,
  (value) => {
    if (String(value ?? '') !== serializedTemplate.value) hydrate(value)
  },
  { immediate: true },
)

watch(
  () => props.wrapperEnabled,
  (value) => {
    if (value === wrapperEnabled.value) return
    wrapperEnabled.value = value
    commit()
  },
)

watch(
  () => props.wrapperLeft,
  (value) => {
    if (value === wrapperLeft.value) return
    wrapperLeft.value = String(value ?? '')
    commit()
  },
)

watch(
  () => props.wrapperRight,
  (value) => {
    if (value === wrapperRight.value) return
    wrapperRight.value = String(value ?? '')
    commit()
  },
)

onMounted(() => {
  sortable = Sortable.create(templateCanvas.value, {
    animation: 180,
    chosenClass: 'is-sortable-chosen',
    dragClass: 'is-sortable-drag',
    draggable: '.template-block',
    fallbackClass: 'is-sortable-fallback',
    fallbackOnBody: true,
    fallbackTolerance: 4,
    forceFallback: true,
    ghostClass: 'is-sortable-ghost',
    handle: '.block-grip',
    swapThreshold: 0.65,
    touchStartThreshold: 4,
    onEnd(event) {
      const { oldIndex, newIndex } = event
      if (!Number.isInteger(oldIndex) || !Number.isInteger(newIndex)) return
      moveBlock(oldIndex, newIndex)
      nextTick(() => sortable?.sort(blocks.value.map((block) => block.id)))
    },
    dataIdAttr: 'data-block-id',
  })
})

onBeforeUnmount(() => {
  sortable?.destroy()
  sortable = null
})
</script>

<style scoped>
.rename-template-builder {
  display: grid;
  gap: 9px;
  min-width: 0;
}

.template-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.template-add-control {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(145px, auto) 1px minmax(150px, 1fr) 36px;
  align-items: center;
  min-height: 40px;
  overflow: hidden;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  background: var(--set-field-bg);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.template-add-control:focus-within,
.template-add-control:hover {
  border-color: var(--set-border-strong);
}

.template-add-control .variable-picker {
  min-width: 0;
}

.variable-picker :deep(.app-dd-trigger) {
  min-height: 38px;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.control-divider {
  width: 1px;
  height: 22px;
  background: var(--set-border);
}

.template-add-control > input {
  width: 100%;
  min-width: 0;
  height: 38px;
  padding: 0 12px;
  border: 0;
  border-radius: 0;
  outline: none;
  background: transparent;
  color: var(--set-text-strong);
  font-size: 13px;
}

.template-add-control > input::placeholder {
  color: var(--set-text-subtle);
}

.wrapper-control {
  display: flex;
  width: fit-content;
  max-width: 100%;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 7px 0 10px;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  background: var(--set-field-bg);
}

.wrapper-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  color: var(--set-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.wrapper-inputs {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: opacity 0.2s ease;
}

.wrapper-inputs.is-disabled {
  opacity: 0.4;
}

.wrapper-inputs label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--set-text-subtle);
  font-size: 11px;
}

.wrapper-inputs input {
  width: 34px;
  height: 28px;
  padding: 0 5px;
  border: 1px solid var(--set-border);
  border-radius: 6px;
  outline: none;
  background: var(--set-surface);
  color: var(--set-text-strong);
  text-align: center;
  font: 600 13px/1 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.wrapper-inputs input:focus {
  border-color: var(--set-border-strong);
}

.builder-icon-btn,
.block-grip,
.block-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  background: var(--set-surface);
  color: var(--set-text-muted);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.builder-icon-btn {
  width: 36px;
  height: 38px;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.builder-icon-btn:not(:disabled):hover,
.block-grip:hover,
.block-action:not(:disabled):hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.builder-icon-btn:not(:disabled):active,
.block-grip:active,
.block-action:not(:disabled):active {
  transform: scale(0.96);
}

.builder-icon-btn:disabled,
.block-action:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}

.template-canvas {
  display: flex;
  min-height: 48px;
  align-items: center;
  align-content: flex-start;
  flex-wrap: wrap;
  gap: 7px;
  padding: 8px;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  background: var(--set-field-bg);
}

.template-canvas.is-empty {
  justify-content: center;
}

.empty-template {
  color: var(--set-text-subtle);
  font-size: 12px;
}

.template-block {
  display: inline-flex;
  height: 32px;
  max-width: 100%;
  align-items: center;
  gap: 5px;
  padding: 0 4px 0 2px;
  border: 1px solid var(--set-border);
  border-radius: 7px;
  background: var(--set-surface);
  color: var(--set-text);
  transition: all 0.18s ease;
}

.template-block.is-variable {
  border-color: rgba(14, 165, 233, 0.35);
  background: rgba(14, 165, 233, 0.08);
  color: #0369a1;
}

.template-block.is-sortable-ghost {
  opacity: 0.28;
}

.template-block.is-sortable-chosen {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.16);
}

.template-block.is-sortable-drag,
.template-block.is-sortable-fallback {
  opacity: 0.92;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.22);
}

.block-grip {
  display: inline-flex;
  width: 22px;
  height: 24px;
  flex: 0 0 22px;
  align-items: center;
  justify-content: center;
  border: 0;
  background: transparent;
  cursor: grab;
  touch-action: none;
}

.template-block.is-sortable-chosen .block-grip {
  cursor: grabbing;
}

.block-kind-icon {
  flex: 0 0 auto;
}

.variable-label {
  white-space: nowrap;
  font-size: 12px;
  font-weight: 650;
}

.template-block code {
  color: inherit;
  opacity: 0.7;
  font-size: 10px;
}

.text-block-input {
  min-width: 42px;
  max-width: 240px;
  height: 24px;
  padding: 0 5px;
  border: 0;
  border-radius: 5px;
  outline: none;
  background: transparent;
  color: var(--set-text-strong);
  font: 600 12px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.text-block-input:focus {
  background: var(--set-surface-hover);
}

.block-action {
  width: 21px;
  height: 22px;
  border: 0;
  background: transparent;
}

.block-action.is-remove:hover {
  color: #e11d48;
}

.template-result {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  color: var(--set-text-muted);
  font-size: 11.5px;
}

.template-result code,
.template-result strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--set-text-strong);
  font-size: 11.5px;
  font-weight: 600;
}

.template-result.is-preview strong {
  font-family: inherit;
}

@media (max-width: 640px) {
  .template-add-control {
    grid-template-columns: minmax(125px, auto) 1px minmax(90px, 1fr) 36px;
  }

  .wrapper-control {
    justify-content: space-between;
  }

  .template-result {
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .template-block code {
    display: none;
  }
}
</style>
