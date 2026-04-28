<template>
  <div class="blk-canvas">
    <!-- 空态 -->
    <div v-if="!localBlocks.length" class="blk-canvas-empty">
      <div class="blk-canvas-empty-illu">
        <LayoutTemplate :size="36" :stroke-width="1.2" />
      </div>
      <p class="blk-canvas-empty-title">从顶部添加你的第一个积木</p>
      <p class="blk-canvas-empty-sub">每个积木对应一段邮件内容，可以拖拽排序、点击编辑</p>
    </div>

    <!-- 邮件画布（模拟邮件版面） -->
    <div v-else class="blk-canvas-scroller">
      <div class="blk-canvas-paper">
        <!-- 起始位置插入条（块前） -->
        <div class="blk-insert-zone" @click="onInsertClick($event, -1)">
          <div class="blk-insert-line" />
          <button type="button" class="blk-insert-btn" title="在此插入积木">
            <Plus :size="12" :stroke-width="2.6" />
          </button>
        </div>

        <template v-for="(block, index) in localBlocks" :key="block.id">
        <div
          class="blk-row"
          :class="{
            'is-selected': block.id === selectedId,
            'is-disabled': !block.enabled,
            'is-dragging': dragging === block.id,
            'is-drag-over': dragOver === block.id,
          }"
          :style="{ '--accent': BLOCK_TYPES[block.type]?.color ?? '#8e8e93' }"
          @click="emit('select', block.id)"
          @dragenter.prevent="onDragEnter(block.id)"
          @dragover.prevent
          @dragleave="onDragLeave(block.id)"
          @drop.prevent="onDrop(block.id)"
        >
          <!-- 左侧浮动把手（hover 出现） -->
          <div
            class="blk-row-grip"
            draggable="true"
            title="拖拽调整顺序"
            @click.stop
            @dragstart="onDragStart(block.id, $event)"
            @dragend="onDragEnd"
          >
            <GripVertical :size="14" :stroke-width="2" />
          </div>

          <!-- 块编号小角标 -->
          <span class="blk-row-index" :title="`第 ${index + 1} 个块`">{{ index + 1 }}</span>

          <!-- 真实渲染（mini-renderer） -->
          <div class="blk-row-content" v-html="renderMini(block)" />

          <!-- 类型徽标（左下） -->
          <span class="blk-row-type-badge">
            {{ BLOCK_TYPES[block.type]?.label ?? block.type }}
            <span v-if="!block.enabled" class="blk-row-off-pill">已停用</span>
          </span>

          <!-- 右侧浮动操作按钮（hover 出现） -->
          <div class="blk-row-actions" @click.stop>
            <button
              class="blk-row-btn"
              :title="block.enabled ? '停用此块' : '启用此块'"
              @click="toggleEnabled(block.id)"
            >
              <EyeOff v-if="block.enabled" :size="13" :stroke-width="2" />
              <Eye v-else :size="13" :stroke-width="2" />
            </button>
            <button class="blk-row-btn" title="复制此块" @click="emit('duplicate', block.id)">
              <Copy :size="13" :stroke-width="2" />
            </button>
            <button class="blk-row-btn blk-row-btn--danger" title="删除此块" @click="emit('delete', block.id)">
              <Trash2 :size="13" :stroke-width="2" />
            </button>
          </div>
        </div>

        <!-- 块后插入条 -->
        <div class="blk-insert-zone" @click="onInsertClick($event, index)">
          <div class="blk-insert-line" />
          <button type="button" class="blk-insert-btn" title="在此插入积木">
            <Plus :size="12" :stroke-width="2.6" />
          </button>
        </div>
        </template>
      </div>
    </div>

    <!-- 插入位置选择器 -->
    <BlockTypePicker
      :visible="pickerVisible"
      :anchor="pickerAnchor"
      placement="bottom"
      @select="onPickerSelect"
      @close="closePicker"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Copy, Eye, EyeOff, GripVertical, LayoutTemplate, Plus, Trash2 } from 'lucide-vue-next'
import { BLOCK_TYPES } from './blockTypes.js'
import { buildSamplePayload, renderBlockMini } from './blockMiniRenderers.js'
import BlockTypePicker from './BlockTypePicker.vue'

const props = defineProps({
  blocks:     { type: Array,  default: () => [] },
  selectedId: { type: String, default: null },
  eventType:  { type: String, default: 'completed' },
})
const emit = defineEmits(['update:blocks', 'select', 'delete', 'duplicate', 'insert'])

// ---- 插入位置 picker ----
const pickerVisible = ref(false)
const pickerAnchor  = ref(null)
const insertAfter   = ref(-1)  // -1 表示插到最前；index 表示插在该位置之后

function onInsertClick(evt, afterIndex) {
  insertAfter.value = afterIndex
  // 取被点中的"+"按钮 rect 作为定位锚点；若整条 zone 被点也用该按钮
  const btn = evt.currentTarget?.querySelector('.blk-insert-btn') || evt.currentTarget
  pickerAnchor.value = btn?.getBoundingClientRect?.() || null
  pickerVisible.value = true
}

function closePicker() {
  pickerVisible.value = false
}

function onPickerSelect(type) {
  emit('insert', { type, afterIndex: insertAfter.value })
  pickerVisible.value = false
}

const localBlocks = ref([])
const dragging    = ref(null)
const dragOver    = ref(null)

const samplePayload = computed(() => buildSamplePayload(props.eventType))

function renderMini(block) {
  return renderBlockMini(block, samplePayload.value)
}

// 同步 props -> localBlocks
let _lastJson = ''
watch(
  () => props.blocks,
  (val) => {
    const json = JSON.stringify(val)
    if (json === _lastJson) return
    _lastJson = json
    localBlocks.value = val.map(b => ({ ...b }))
  },
  { immediate: true, deep: true },
)

// ---- 拖拽排序 ----
function onDragStart(id, evt) {
  dragging.value = id
  evt.dataTransfer.effectAllowed = 'move'
  // Firefox 必须 setData 才会进入 drop 事件流
  try { evt.dataTransfer.setData('text/plain', id) } catch (e) { /* 老浏览器忽略 */ }
}
function onDragEnter(id) {
  if (id !== dragging.value) dragOver.value = id
}
function onDragLeave(id) {
  if (dragOver.value === id) dragOver.value = null
}
function onDrop(targetId) {
  if (!dragging.value || dragging.value === targetId) return
  const list = [...localBlocks.value]
  const fromIdx = list.findIndex(b => b.id === dragging.value)
  const toIdx   = list.findIndex(b => b.id === targetId)
  if (fromIdx < 0 || toIdx < 0) return
  const [item] = list.splice(fromIdx, 1)
  list.splice(toIdx, 0, item)
  _lastJson = JSON.stringify(list)
  localBlocks.value = list
  emit('update:blocks', list)
}
function onDragEnd() {
  dragging.value = null
  dragOver.value = null
}

// ---- 切换启用 ----
function toggleEnabled(id) {
  const updated = localBlocks.value.map(b => b.id === id ? { ...b, enabled: !b.enabled } : b)
  _lastJson = JSON.stringify(updated)
  localBlocks.value = updated
  emit('update:blocks', updated)
}
</script>

<style scoped>
.blk-canvas {
  flex: 1;
  min-width: 0;
  border-right: 1px solid rgba(29, 29, 31, 0.07);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f5f7;
}

/* ── 空态 ── */
.blk-canvas-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: rgba(29, 29, 31, 0.3);
  padding: 32px;
}
.blk-canvas-empty-illu {
  width: 72px;
  height: 72px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 113, 227, 0.06);
  color: rgba(0, 113, 227, 0.55);
  margin-bottom: 4px;
}
.blk-canvas-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.65);
  margin: 0;
}
.blk-canvas-empty-sub {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.4);
  margin: 0;
  text-align: center;
  line-height: 1.6;
  max-width: 320px;
}

/* ── 滚动容器 + 邮件纸 ── */
.blk-canvas-scroller {
  flex: 1;
  overflow-y: auto;
  padding: 24px 24px 60px;
}
.blk-canvas-paper {
  max-width: 600px;
  margin: 0 auto;
  background: #fff;
  border-radius: 16px;
  padding: 28px 32px;
  box-shadow: 0 2px 20px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* ── 块行：默认无边框，hover/选中再显形 ── */
.blk-row {
  position: relative;
  padding: 4px 4px 4px 4px;
  margin: 0 -4px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
  user-select: none;
}

.blk-row:hover {
  background: rgba(0, 113, 227, 0.04);
}

.blk-row.is-selected {
  background: rgba(0, 113, 227, 0.06);
  box-shadow: 0 0 0 2px rgba(0, 113, 227, 0.32) inset;
}

.blk-row.is-disabled { opacity: 0.4; }
.blk-row.is-dragging { opacity: 0.4; }
.blk-row.is-drag-over {
  box-shadow: 0 -2px 0 0 #0071e3 inset;
  background: rgba(0, 113, 227, 0.05);
}

/* 真实渲染区域（v-html 内容用 inline style） */
.blk-row-content {
  position: relative;
  z-index: 1;
}

/* 把手 — 浮动到行外侧左边 */
.blk-row-grip {
  position: absolute;
  left: -28px;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: rgba(29, 29, 31, 0.35);
  cursor: grab;
  opacity: 0;
  transition: opacity 0.12s, background 0.12s;
  z-index: 5;
}
.blk-row-grip:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}
.blk-row-grip:active { cursor: grabbing; }
.blk-row:hover .blk-row-grip,
.blk-row.is-selected .blk-row-grip {
  opacity: 1;
}

/* 编号小角标 */
.blk-row-index {
  position: absolute;
  left: -50px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.32);
  font-family: ui-monospace, SFMono-Regular, monospace;
  opacity: 0;
  transition: opacity 0.12s;
}
.blk-row:hover .blk-row-index,
.blk-row.is-selected .blk-row-index {
  opacity: 1;
}

/* 类型徽标（hover/选中时浮在右上） */
.blk-row-type-badge {
  position: absolute;
  top: -10px;
  right: 4px;
  font-size: 10px;
  font-weight: 600;
  color: var(--accent);
  background: #fff;
  padding: 2px 8px;
  border-radius: 99px;
  border: 1px solid color-mix(in srgb, var(--accent) 30%, #fff);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.15s, transform 0.15s;
  pointer-events: none;
  z-index: 4;
  letter-spacing: 0.02em;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.blk-row:hover .blk-row-type-badge,
.blk-row.is-selected .blk-row-type-badge {
  opacity: 1;
  transform: translateY(0);
}
.blk-row-off-pill {
  font-size: 9px;
  color: rgba(29, 29, 31, 0.5);
  background: rgba(29, 29, 31, 0.07);
  padding: 1px 5px;
  border-radius: 99px;
  font-weight: 500;
}

/* 操作按钮 — 浮在右侧外面 */
.blk-row-actions {
  position: absolute;
  top: 50%;
  right: -88px;
  transform: translateY(-50%);
  display: flex;
  gap: 2px;
  padding: 3px;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 6;
}
.blk-row:hover .blk-row-actions,
.blk-row.is-selected .blk-row-actions {
  opacity: 1;
}

.blk-row-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(29, 29, 31, 0.55);
  cursor: pointer;
  transition: all 0.15s;
}
.blk-row-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}
.blk-row-btn--danger:hover {
  background: rgba(220, 50, 50, 0.08);
  color: #dc3232;
}

/* ── 块间插入条 ── */
.blk-insert-zone {
  position: relative;
  height: 12px;
  margin: 0 -4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.blk-insert-zone:first-child { height: 8px; }
.blk-insert-zone:last-child  { height: 18px; }

.blk-insert-line {
  width: 100%;
  height: 1px;
  background: rgba(0, 113, 227, 0.55);
  opacity: 0;
  transition: opacity 0.12s;
}

.blk-insert-btn {
  position: absolute;
  width: 22px;
  height: 22px;
  border: 1px solid rgba(0, 113, 227, 0.4);
  background: #fff;
  color: #0071e3;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transform: scale(0.85);
  transition: opacity 0.15s, transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.15s;
  z-index: 7;
  box-shadow: 0 2px 8px rgba(0, 113, 227, 0.18);
}
.blk-insert-btn:hover {
  background: #0071e3;
  color: #fff;
}

.blk-insert-zone:hover .blk-insert-line { opacity: 1; }
.blk-insert-zone:hover .blk-insert-btn {
  opacity: 1;
  transform: scale(1);
}

/* 容器若太窄，actions 收回到行内右上 */
@media (max-width: 720px) {
  .blk-row-actions {
    right: 4px;
    top: 4px;
    transform: none;
  }
  .blk-row-grip,
  .blk-row-index { display: none; }
}
</style>
