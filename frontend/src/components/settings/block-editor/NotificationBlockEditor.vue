<template>
  <div class="blk-editor">
    <!-- ── 顶部工具栏 ── -->
    <div class="blk-toolbar">
      <button
        ref="addBtnRef"
        type="button"
        class="blk-add-main-btn"
        @click="openAddPicker"
      >
        <Plus :size="14" :stroke-width="2.6" />
        添加积木
      </button>
      <span class="blk-toolbar-hint">{{ blocks.length ? `共 ${blocks.length} 个积木块` : '从这里开始搭建邮件' }}</span>
      <div class="blk-toolbar-gap" />
      <!-- 全屏预览触发 -->
      <button
        type="button"
        class="blk-fullscreen-btn"
        :disabled="!blocks.length"
        :title="blocks.length ? '在全屏窗口中预览邮件' : '请先添加积木块'"
        @click="openFullPreview"
      >
        <Eye :size="13" :stroke-width="2.2" />
        预览邮件
      </button>
    </div>

    <!-- 顶部 + 按钮的 picker -->
    <BlockTypePicker
      :visible="addPickerVisible"
      :anchor="addPickerAnchor"
      placement="bottom"
      @select="onAddPickerSelect"
      @close="addPickerVisible = false"
    />

    <!-- ── 主体区 ── -->
    <div class="blk-body">
      <!-- 左：画布（所见即所得） -->
      <TemplateBlockCanvas
        v-model:blocks="blocks"
        :selected-id="selectedId"
        :event-type="eventType"
        @select="onSelect"
        @delete="deleteBlock"
        @duplicate="duplicateBlock"
        @insert="onInsertBlock"
      />

      <!-- 右：属性面板（一直显示，不再切换） -->
      <div class="blk-right">
        <TemplateBlockInspector
          v-if="selectedBlock"
          :key="selectedBlock.id"
          :block="selectedBlock"
          @update="onBlockUpdate"
        />
        <div v-else class="blk-empty-hint">
          <div class="blk-empty-hint-illu">
            <Layers :size="22" :stroke-width="1.4" />
          </div>
          <p class="blk-empty-hint-title">点击左侧任意积木</p>
          <p class="blk-empty-hint-sub">即可在这里编辑属性</p>
        </div>
      </div>
    </div>

    <!-- ── 全屏预览 dialog ── -->
    <transition name="blk-prev-fade">
      <div v-if="fullPreviewOpen" class="blk-prev-mask" @click.self="closeFullPreview">
        <div class="blk-prev-panel">
          <header class="blk-prev-head">
            <div class="blk-prev-head-title">
              <Eye :size="14" :stroke-width="2.2" />
              <span>邮件预览</span>
              <span class="blk-prev-head-hint">数据为示例值，实际邮件按任务真实数据渲染</span>
            </div>
            <button class="blk-prev-close" type="button" @click="closeFullPreview" title="关闭">
              <X :size="18" :stroke-width="2.4" />
            </button>
          </header>
          <TemplateBlockPreview
            ref="previewRef"
            class="blk-prev-body"
            :blocks="blocks"
            :event-type="eventType"
            :domain="domain"
            :subject-template="subjectTemplate"
          />
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Eye, Layers, Plus, X } from 'lucide-vue-next'
import { createBlock, cloneBlock } from './blockTypes.js'
import TemplateBlockCanvas    from './TemplateBlockCanvas.vue'
import TemplateBlockInspector from './TemplateBlockInspector.vue'
import TemplateBlockPreview   from './TemplateBlockPreview.vue'
import BlockTypePicker        from './BlockTypePicker.vue'

const props = defineProps({
  initialBlocks:   { type: Array,  default: () => [] },
  eventType:       { type: String, default: 'completed' },
  domain:          { type: String, default: 'import' },
  subjectTemplate: { type: String, default: '' },
})
const emit = defineEmits(['update:blocks'])

const blocks            = ref(props.initialBlocks.map(b => ({ ...b })))
const selectedId        = ref(null)
const previewRef        = ref(null)
const fullPreviewOpen   = ref(false)

// 顶部 + 添加积木 picker
const addBtnRef         = ref(null)
const addPickerVisible  = ref(false)
const addPickerAnchor   = ref(null)

function openAddPicker() {
  addPickerAnchor.value = addBtnRef.value?.getBoundingClientRect?.() || null
  addPickerVisible.value = true
}
function onAddPickerSelect(type) {
  addBlock(type)
  addPickerVisible.value = false
}

const selectedBlock = computed(() =>
  selectedId.value ? blocks.value.find(b => b.id === selectedId.value) ?? null : null
)

function openFullPreview() {
  if (!blocks.value.length) return
  fullPreviewOpen.value = true
  // 等 dialog 内部 ref 就绪后再触发首次预览
  Promise.resolve().then(() => previewRef.value?.fetchPreview?.())
}
function closeFullPreview() {
  fullPreviewOpen.value = false
}

// 防循环标志
let _emitting = false

watch(blocks, (val) => {
  _emitting = true
  emit('update:blocks', val)
  Promise.resolve().then(() => { _emitting = false })
}, { deep: true })

watch(() => props.initialBlocks, (val) => {
  if (_emitting) return
  blocks.value = val.map(b => ({ ...b }))
  selectedId.value = null
})

// ---- 操作 ----
function addBlock(type) {
  const block = createBlock(type)
  blocks.value = [...blocks.value, block]
  selectedId.value = block.id
}

/** 在指定位置后插入；afterIndex = -1 表示插到最前 */
function onInsertBlock({ type, afterIndex }) {
  const block = createBlock(type)
  const insertAt = Math.max(0, Math.min(blocks.value.length, afterIndex + 1))
  blocks.value = [
    ...blocks.value.slice(0, insertAt),
    block,
    ...blocks.value.slice(insertAt),
  ]
  selectedId.value = block.id
}

function onSelect(id) {
  selectedId.value = id
}

function deleteBlock(id) {
  blocks.value = blocks.value.filter(b => b.id !== id)
  if (selectedId.value === id) selectedId.value = null
}

function duplicateBlock(id) {
  const idx = blocks.value.findIndex(b => b.id === id)
  if (idx < 0) return
  const clone = cloneBlock(blocks.value[idx])
  blocks.value = [
    ...blocks.value.slice(0, idx + 1),
    clone,
    ...blocks.value.slice(idx + 1),
  ]
  selectedId.value = clone.id
}

function onBlockUpdate(updatedBlock) {
  blocks.value = blocks.value.map(b => b.id === updatedBlock.id ? updatedBlock : b)
}

defineExpose({
  getBlocks: () => blocks.value,
  triggerPreview: () => {
    fullPreviewOpen.value = true
    Promise.resolve().then(() => previewRef.value?.fetchPreview?.())
  },
  selectBlockByType: (blockType) => {
    const block = blocks.value.find(b => b.type === blockType)
    if (!block) return false
    selectedId.value = block.id
    nextTick(() => {
      const el = document.querySelector(`[data-block-id="${block.id}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return true
  },
})
</script>

<style scoped>
.blk-editor {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── 工具栏 ── */
.blk-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  flex-shrink: 0;
}
/* 顶部主按钮：添加积木 */
.blk-add-main-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--set-primary-text, #fff);
  background: var(--set-primary-bg, #1d1d1f);
  border: 1px solid var(--set-primary-border, #1d1d1f);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  flex-shrink: 0;
  box-shadow: none;
}
.blk-add-main-btn:hover {
  background: var(--set-primary-bg-hover);
  border-color: var(--set-primary-border);
  transform: translateY(-1px) scale(1.02);
  box-shadow: none;
}
.blk-add-main-btn:active { transform: scale(0.96); }

.blk-toolbar-hint {
  font-size: 11.5px;
  color: var(--set-text-muted);
  font-weight: 500;
  flex-shrink: 0;
}

.blk-toolbar-gap { flex: 1; }

/* 全屏预览按钮 */
.blk-fullscreen-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--set-primary-text);
  background: var(--set-primary-bg);
  border: 1px solid var(--set-primary-border);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  flex-shrink: 0;
}
.blk-fullscreen-btn:hover {
  background: var(--set-primary-bg-hover);
  transform: translateY(-1px) scale(1.02);
  box-shadow: none;
}
.blk-fullscreen-btn:active:not(:disabled) { transform: scale(0.96); }
.blk-fullscreen-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ── 主体 ── */
.blk-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── 右面板 ── */
.blk-right {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--set-border);
  background: var(--set-surface);
}

.blk-empty-hint {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.6;
  text-align: center;
  padding: 32px 20px;
}
.blk-empty-hint-illu {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--set-surface-soft, rgba(0, 0, 0, 0.03));
  color: var(--set-text-muted, rgba(29, 29, 31, 0.55));
  margin-bottom: 6px;
}
.blk-empty-hint-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--set-text);
}
.blk-empty-hint-sub {
  margin: 0;
  font-size: 11.5px;
  color: var(--set-text-muted);
}

/* ── 全屏预览 dialog ── */
.blk-prev-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 21, 0.6);
  backdrop-filter: blur(8px);
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}
.blk-prev-panel {
  width: min(880px, 100%);
  max-height: calc(100vh - 64px);
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  border-radius: 16px;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.blk-prev-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--set-border);
  background: var(--set-surface-soft);
}
.blk-prev-head-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--set-text-strong);
}
.blk-prev-head-hint {
  font-size: 11px;
  color: var(--set-text-muted);
  font-weight: 400;
  margin-left: 6px;
}
.blk-prev-close {
  width: 30px;
  height: 30px;
  border: 1px solid var(--set-border);
  border-radius: 8px;
  background: var(--set-surface);
  color: var(--set-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
}
.blk-prev-close:hover {
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}
.blk-prev-body {
  flex: 1;
  min-height: 0;
}

/* dialog 过渡 */
.blk-prev-fade-enter-active,
.blk-prev-fade-leave-active {
  transition: opacity 0.18s ease;
}
.blk-prev-fade-enter-from,
.blk-prev-fade-leave-to { opacity: 0; }
.blk-prev-fade-enter-from .blk-prev-panel,
.blk-prev-fade-leave-to .blk-prev-panel {
  transform: translateY(8px) scale(0.98);
}
</style>
