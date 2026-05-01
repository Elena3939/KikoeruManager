<template>
  <div class="settings-card tpl-panel">
    <div class="card-title">
      <span>邮件模板</span>
      <span class="tpl-panel-count">{{ templates.length }}</span>
      <span class="tpl-panel-spacer" />
      <button class="tpl-panel-action" type="button" :disabled="loading" @click="reload">
        <RefreshCw :size="13" :stroke-width="2.4" :class="{ 'spin-once': loading }" />
        刷新
      </button>
      <div class="tpl-create-wrap">
        <button class="tpl-panel-action tpl-panel-action--primary" type="button" @click="presetMenuOpen = !presetMenuOpen">
          <Plus :size="14" :stroke-width="2.6" />
          新建模板
          <ChevronDown :size="13" :stroke-width="2.4" />
        </button>
        <div v-if="presetMenuOpen" class="tpl-create-menu">
          <button class="tpl-create-item" type="button" @click="openCreate">
            <FilePlus2 :size="15" :stroke-width="2.2" />
            <span>
              <strong>从空白创建</strong>
              <small>使用默认 HTML 模板</small>
            </span>
          </button>
          <button
            v-for="preset in PRESET_TEMPLATES"
            :key="preset.id"
            class="tpl-create-item"
            type="button"
            @click="openPreset(preset)"
          >
            <component :is="PRESET_ICONS[preset.icon] || LayoutTemplate" :size="15" :stroke-width="2.2" />
            <span>
              <strong>{{ preset.name }}</strong>
              <small>{{ preset.description }}</small>
            </span>
          </button>
        </div>
      </div>
    </div>

    <p class="tpl-panel-desc">
      未配置任何模板时使用内置样式发送。模板按"事件 + 任务类型"匹配，专用模板优先于通用模板。
    </p>

    <div v-if="loading" class="tpl-panel-loading">加载中...</div>
    <div v-else-if="!templates.length" class="tpl-panel-empty">
      <Mail :size="20" :stroke-width="2" />
      <span>暂无自定义模板，邮件将使用内置样式发送</span>
    </div>
    <div v-else class="tpl-panel-list">
      <div
        v-for="tpl in templates"
        :key="tpl.id"
        class="tpl-card"
        :class="{ 'is-disabled': !tpl.enabled }"
      >
        <div class="tpl-card-head">
          <div class="tpl-card-title-wrap">
            <span class="tpl-card-name">{{ tpl.name || '未命名模板' }}</span>
            <span v-if="tpl.is_default" class="tpl-badge tpl-badge--default">默认</span>
            <span v-if="!tpl.enabled" class="tpl-badge tpl-badge--off">已停用</span>
          </div>
          <div class="tpl-card-actions">
            <button
              v-if="isLegacyBlocksTemplate(tpl)"
              class="tpl-action tpl-action--upgrade"
              type="button"
              title="升级到最新模板布局（RJ 卡片 + 完整文件树）"
              @click="upgradeTemplate(tpl)"
            >
              <Sparkles :size="14" :stroke-width="2.2" />
              升级布局
            </button>
            <button class="tpl-action" type="button" title="启用 / 停用" @click="toggleEnabled(tpl)">
              <component :is="tpl.enabled ? ToggleRight : ToggleLeft" :size="16" :stroke-width="2.2" />
            </button>
            <button class="tpl-action" type="button" :title="tpl.is_default ? '已是默认' : '设为默认'" @click="setDefault(tpl)">
              <Star :size="15" :stroke-width="2.2" :class="{ 'is-filled': tpl.is_default }" />
            </button>
            <button class="tpl-action" type="button" title="编辑" @click="openEdit(tpl)">
              <Pencil :size="14" :stroke-width="2.4" />
            </button>
            <button class="tpl-action tpl-action--danger" type="button" title="删除" @click="onDelete(tpl)">
              <Trash2 :size="14" :stroke-width="2.4" />
            </button>
          </div>
        </div>

        <p v-if="tpl.description" class="tpl-card-desc">{{ tpl.description }}</p>

        <div class="tpl-card-meta">
          <div class="tpl-meta-row">
            <span class="tpl-meta-label">事件</span>
            <div class="tpl-meta-chips">
              <span v-for="e in (tpl.event_types || [])" :key="e" class="tpl-meta-chip">{{ EVENT_LABEL[e] || e }}</span>
              <span v-if="!(tpl.event_types || []).length" class="tpl-meta-chip tpl-meta-chip--muted">未指定</span>
            </div>
          </div>
          <div class="tpl-meta-row">
            <span class="tpl-meta-label">范围</span>
            <div class="tpl-meta-chips">
              <span v-if="!(tpl.task_domains || []).length" class="tpl-meta-chip tpl-meta-chip--muted">通用模板</span>
              <span v-for="d in (tpl.task_domains || [])" :key="d" class="tpl-meta-chip">{{ DOMAIN_LABEL[d] || d }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <NotificationTemplateEditor
      :visible="editorVisible"
      :template="editingTemplate"
      @close="closeEditor"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import {
  ChevronDown,
  FilePlus2,
  LayoutTemplate,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Star,
  ToggleLeft,
  ToggleRight,
  Trash2,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { notificationApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'
import NotificationTemplateEditor from './NotificationTemplateEditor.vue'
import { PRESET_TEMPLATES } from './block-editor/presetTemplates.js'
import { buildDefaultEmailBlocks } from './block-editor/defaultEmailTemplate.js'

const EVENT_LABEL = { completed: '完成', failed: '失败', waiting_manual: '等待人工' }
const DOMAIN_LABEL = {
  import: '导入处理',
  rj_subtitle: 'RJ 字幕',
  subtitle_import: '字幕补配',
  asmr_sync: 'ASMR 同步',
  upload: '库存上传',
  circle_completion: '社团补全',
  system: '系统任务'
}

const templates = ref([])
const loading = ref(false)
const editorVisible = ref(false)
const editingTemplate = ref(null)
const presetMenuOpen = ref(false)

const PRESET_ICONS = {
  LayoutTemplate,
  Mail,
}

async function reload() {
  loading.value = true
  try {
    const data = await notificationApi.listTemplates()
    templates.value = data.items || []
  } catch (e) {
    templates.value = []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  presetMenuOpen.value = false
  editingTemplate.value = null
  editorVisible.value = true
}

function openPreset(preset) {
  presetMenuOpen.value = false
  // 优先 buildBlocks() 现场生成（保证每次 ID 唯一）；否则回退到静态 blocks 数组
  let blocks = []
  if (typeof preset.buildBlocks === 'function') {
    blocks = preset.buildBlocks() || []
  } else if (Array.isArray(preset.blocks)) {
    blocks = JSON.parse(JSON.stringify(preset.blocks))
  }
  editingTemplate.value = {
    ...preset,
    id: undefined,
    blocks,
    enabled: true,
    is_default: false,
    sort_order: 0,
  }
  editorVisible.value = true
}

function openEdit(tpl) {
  editingTemplate.value = { ...tpl }
  editorVisible.value = true
}

function closeEditor() {
  editorVisible.value = false
  editingTemplate.value = null
}

function onSaved() {
  closeEditor()
  reload()
}

async function toggleEnabled(tpl) {
  try {
    await notificationApi.updateTemplate(tpl.id, { enabled: !tpl.enabled })
    tpl.enabled = !tpl.enabled
  } catch (e) {
    /* 静默失败，下次刷新会同步 */
  }
}

async function setDefault(tpl) {
  if (tpl.is_default) return
  try {
    // 同事件下若已有默认，后端不会自动互斥，这里前端把同事件其他模板的 is_default 置 false
    const overlapping = templates.value.filter(t =>
      t.id !== tpl.id
      && t.is_default
      && (t.event_types || []).some(e => (tpl.event_types || []).includes(e))
    )
    await Promise.all(overlapping.map(t => notificationApi.updateTemplate(t.id, { is_default: false })))
    await notificationApi.updateTemplate(tpl.id, { is_default: true })
    await reload()
  } catch (e) {
    /* 忽略 */
  }
}

function isLegacyBlocksTemplate(tpl) {
  if (tpl.editor_mode !== 'blocks') return false
  const blocks = Array.isArray(tpl.blocks) ? tpl.blocks : []
  return blocks.some(b => b && b.type === 'stats_grid')
}

async function upgradeTemplate(tpl) {
  try {
    await showSystemConfirm({
      title: '升级模板布局',
      message: `将把「${tpl.name || '未命名'}」的积木布局升级到最新版本（RJ 作品卡片 + 完整文件树），原 stats_grid 统计格会被移除。此操作会覆盖当前积木内容。`,
      confirmText: '确认升级',
      cancelText: '取消',
    })
  } catch {
    return
  }
  try {
    const newBlocks = buildDefaultEmailBlocks()
    await notificationApi.updateTemplate(tpl.id, { blocks: newBlocks, editor_mode: 'blocks' })
    ElMessage.success('布局已升级到最新版本')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '升级失败')
  }
}

async function onDelete(tpl) {
  try {
    await showSystemConfirm({
      title: '删除模板',
      message: `确认删除模板「${tpl.name || '未命名'}」？此操作无法撤销。`,
      confirmText: '删除',
      cancelText: '取消'
    })
  } catch {
    return
  }
  try {
    await notificationApi.deleteTemplate(tpl.id)
    templates.value = templates.value.filter(t => t.id !== tpl.id)
  } catch (e) {
    /* 忽略 */
  }
}

onMounted(reload)
defineExpose({ reload })
</script>

<style scoped>
.tpl-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tpl-panel .card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tpl-panel-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.6);
  background: rgba(0, 0, 0, 0.05);
  border-radius: 99px;
}

.tpl-panel-spacer {
  flex: 1;
}

.tpl-panel-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-panel-action:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(0, 113, 227, 0.3);
  color: #0071e3;
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.1);
}

.tpl-panel-action:active:not(:disabled) {
  transform: scale(0.96);
}

.tpl-panel-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tpl-panel-action--primary {
  color: #fff;
  background: #1d1d1f;
  border-color: #1d1d1f;
}

.tpl-panel-action--primary:hover:not(:disabled) {
  background: #000;
  border-color: #000;
  color: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.tpl-create-wrap {
  position: relative;
  flex-shrink: 0;
}

.tpl-create-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 20;
  width: 310px;
  padding: 7px;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.1);
  border-radius: 12px;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.14);
}

.tpl-create-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 11px;
  color: #1d1d1f;
  background: transparent;
  border: 0;
  border-radius: 9px;
  text-align: left;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-create-item:hover {
  background: rgba(0, 113, 227, 0.06);
  color: #0071e3;
  transform: translateY(-1px);
}

.tpl-create-item:active {
  transform: scale(0.98);
}

.tpl-create-item span {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tpl-create-item strong {
  font-size: 12.5px;
  font-weight: 650;
  color: inherit;
}

.tpl-create-item small {
  font-size: 11px;
  line-height: 1.45;
  color: rgba(29, 29, 31, 0.52);
}

.tpl-panel-desc {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.55);
  line-height: 1.55;
}

.tpl-panel-loading,
.tpl-panel-empty {
  padding: 22px 18px;
  text-align: center;
  font-size: 13px;
  color: rgba(29, 29, 31, 0.5);
  background: rgba(0, 0, 0, 0.02);
  border: 1px dashed rgba(29, 29, 31, 0.1);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.tpl-panel-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tpl-card {
  padding: 14px 16px;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 14px;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-card:hover {
  border-color: rgba(29, 29, 31, 0.16);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.tpl-card.is-disabled {
  opacity: 0.6;
}

.tpl-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.tpl-card-title-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tpl-card-name {
  font-size: 14px;
  font-weight: 600;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tpl-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: 99px;
  flex-shrink: 0;
}

.tpl-badge--default {
  color: #0071e3;
  background: rgba(0, 113, 227, 0.1);
  border: 1px solid rgba(0, 113, 227, 0.2);
}

.tpl-badge--off {
  color: rgba(29, 29, 31, 0.55);
  background: rgba(29, 29, 31, 0.06);
  border: 1px solid rgba(29, 29, 31, 0.12);
}

.tpl-card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.tpl-action {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  color: rgba(29, 29, 31, 0.55);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-action:hover {
  background: rgba(0, 0, 0, 0.05);
  color: #1d1d1f;
  transform: translateY(-1px);
}

.tpl-action:active {
  transform: scale(0.94);
}

.tpl-action--danger:hover {
  background: rgba(217, 48, 37, 0.08);
  color: #d93025;
}

.tpl-action--upgrade {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  color: #7c3aed;
  background: rgba(124, 58, 237, 0.07);
  border: 1px solid rgba(124, 58, 237, 0.2);
  white-space: nowrap;
}

.tpl-action--upgrade:hover {
  background: rgba(124, 58, 237, 0.14);
  color: #6d28d9;
  transform: translateY(-1px);
  border-color: rgba(109, 40, 217, 0.35);
}

.tpl-action :deep(.is-filled) {
  fill: currentColor;
}

.tpl-card-desc {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.6);
  line-height: 1.55;
  margin-bottom: 8px;
}

.tpl-card-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tpl-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.tpl-meta-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.45);
  min-width: 38px;
}

.tpl-meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tpl-meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.7);
  background: rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(29, 29, 31, 0.06);
  border-radius: 99px;
}

.tpl-meta-chip--muted {
  color: rgba(29, 29, 31, 0.45);
  font-style: italic;
}

@keyframes spin-once {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

.spin-once {
  animation: spin-once 0.8s linear;
}
</style>
