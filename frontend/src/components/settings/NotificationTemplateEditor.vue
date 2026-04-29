<template>
  <transition name="tpl-fade">
    <div v-if="visible" class="tpl-editor-mask" @click.self="onCancel">
      <div class="tpl-editor-panel">
        <header class="tpl-editor-head">
          <div class="tpl-editor-head-text">
            <span class="tpl-editor-kicker">Email Template</span>
            <h2 class="tpl-editor-title">{{ isCreate ? '新建邮件模板' : '编辑邮件模板' }}</h2>
            <p v-if="form.editor_mode === 'html'" class="tpl-editor-desc">变量插入用 <code>{任务标题}</code> / <code>{摘要}</code> / <code>{任务类型}</code> / <code>{RJ号}</code> / <code>{事件名称}</code> / <code>{事件图标}</code> / <code>{时间}</code></p>
          </div>
          <!-- 模式切换 -->
          <div class="tpl-mode-toggle">
            <button
              type="button"
              class="tpl-mode-btn"
              :class="{ 'is-active': form.editor_mode === 'html' }"
              @click="setEditorMode('html')"
            >
              <Code2 :size="13" :stroke-width="2.4" /> HTML
            </button>
            <button
              type="button"
              class="tpl-mode-btn"
              :class="{ 'is-active': form.editor_mode === 'blocks' }"
              @click="setEditorMode('blocks')"
            >
              <LayoutTemplate :size="13" :stroke-width="2.4" /> 积木编辑器
            </button>
          </div>
          <button class="tpl-icon-btn" type="button" @click="onCancel" title="关闭">
            <X :size="18" :stroke-width="2.4" />
          </button>
        </header>

        <!-- blocks 模式 -->
        <div v-if="form.editor_mode === 'blocks'" class="tpl-editor-blocks-wrap">
          <!-- 基础字段精简行 -->
          <div class="tpl-meta-bar">
            <input v-model="form.name" class="tpl-input tpl-meta-input" type="text" placeholder="模板名称（必填）">
            <input v-model="form.subject_template" class="tpl-input tpl-meta-input tpl-meta-input--subject" type="text" placeholder="邮件主题，如 [Prekikoeru] {任务类型}{事件名称} — {任务标题}">
            <div class="tpl-chips tpl-meta-chips">
              <button
                v-for="e in EVENT_OPTIONS" :key="e.value"
                type="button" class="tpl-chip" :class="{ 'is-active': form.event_types.includes(e.value) }"
                @click="toggleEvent(e.value)"
              >{{ e.label }}</button>
            </div>
            <label class="tpl-toggle">
              <el-switch v-model="form.enabled" size="small" />
              <span style="font-size:12px;">启用</span>
            </label>
            <label class="tpl-toggle">
              <el-switch v-model="form.is_default" size="small" />
              <span style="font-size:12px;">默认</span>
            </label>
            <button
              type="button"
              class="tpl-reset-btn"
              title="把当前积木重置为拆分后的默认多块布局（头图 / 事件元信息 / 标题 / 信息表 / 统计 / 文件 / 日志 / 页脚）"
              @click="resetToDefaultBlocks"
            >
              <RefreshCw :size="12" :stroke-width="2.4" />
              重置为标准积木
            </button>
          </div>
          <!-- 积木编辑器主体 -->
          <NotificationBlockEditor
            ref="blockEditorRef"
            :initial-blocks="form.blocks"
            :event-type="form.event_types[0] || 'completed'"
            :subject-template="form.subject_template"
            domain="import"
            @update:blocks="form.blocks = $event"
          />
        </div>

        <!-- html / 富文本模式：与积木模式同款布局 -->
        <div v-else class="tpl-editor-blocks-wrap">
          <!-- 顶部 meta-bar -->
          <div class="tpl-meta-bar">
            <input v-model="form.name" class="tpl-input tpl-meta-input" type="text" placeholder="模板名称（必填）">
            <input v-model="form.subject_template" class="tpl-input tpl-meta-input tpl-meta-input--subject" type="text" placeholder="邮件主题，如 [Prekikoeru] {任务类型}{事件名称} — {任务标题}">
            <div class="tpl-chips tpl-meta-chips">
              <button
                v-for="e in EVENT_OPTIONS" :key="e.value"
                type="button" class="tpl-chip" :class="{ 'is-active': form.event_types.includes(e.value) }"
                @click="toggleEvent(e.value)"
              >{{ e.label }}</button>
            </div>
            <label class="tpl-toggle">
              <el-switch v-model="form.enabled" size="small" />
              <span style="font-size:12px;">启用</span>
            </label>
            <label class="tpl-toggle">
              <el-switch v-model="form.is_default" size="small" />
              <span style="font-size:12px;">默认</span>
            </label>
          </div>

          <!-- domain 范围 chip 一行 -->
          <div class="tpl-meta-bar tpl-meta-bar--secondary">
            <span class="tpl-meta-bar-label">适用任务类型</span>
            <div class="tpl-chips tpl-meta-chips">
              <button
                v-for="d in DOMAIN_OPTIONS" :key="d.value"
                type="button" class="tpl-chip" :class="{ 'is-active': form.task_domains.includes(d.value) }"
                @click="toggleDomain(d.value)"
              >{{ d.label }}</button>
            </div>
            <span class="tpl-meta-bar-hint">不选 = 通用模板，所有任务都用</span>
            <div class="tpl-meta-bar-spacer" />
            <button
              type="button"
              class="tpl-fullscreen-btn"
              :disabled="!form.html_template?.trim()"
              :title="form.html_template?.trim() ? '在全屏窗口预览邮件' : '请先编写正文'"
              @click="openFullPreview"
            >
              <Eye :size="13" :stroke-width="2.2" />
              预览邮件
            </button>
          </div>

          <!-- 大号富文本编辑器 -->
          <div class="tpl-rte-wrap">
            <RichTextEditor
              :key="`rte-html-${form.editor_mode}`"
              :model-value="null"
              :html-cache="form.html_template"
              size="large"
              @update:html-cache="onHtmlTemplateChange"
            />
          </div>
        </div>

        <!-- 全屏预览 dialog（HTML 模式专用） -->
        <transition name="tpl-prev-fade">
          <div v-if="fullPreviewOpen" class="tpl-prev-mask" @click.self="fullPreviewOpen = false">
            <div class="tpl-prev-panel">
              <header class="tpl-prev-head">
                <div class="tpl-prev-head-title">
                  <Eye :size="14" :stroke-width="2.2" />
                  <span>邮件预览</span>
                  <span class="tpl-prev-head-hint">主题：{{ preview.subject || '—' }}</span>
                </div>
                <button class="tpl-prev-close" type="button" @click="fullPreviewOpen = false" title="关闭">
                  <X :size="18" :stroke-width="2.4" />
                </button>
              </header>
              <div class="tpl-prev-frame-wrap">
                <iframe
                  v-if="preview.html"
                  :srcdoc="preview.html"
                  class="tpl-prev-frame"
                  sandbox=""
                  title="email preview"
                />
                <div v-else class="tpl-prev-empty">点击"刷新预览"渲染</div>
              </div>
            </div>
          </div>
        </transition>

        <footer class="tpl-editor-foot">
          <span v-if="errorMsg" class="tpl-editor-err">{{ errorMsg }}</span>
          <span class="tpl-editor-spacer" />
          <button class="tpl-btn tpl-btn--ghost" type="button" :disabled="saving" @click="onCancel">取消</button>
          <button class="tpl-btn tpl-btn--primary" type="button" :disabled="saving || !canSave" @click="onSave">
            <Check :size="14" :stroke-width="2.6" />
            {{ saving ? '保存中...' : (isCreate ? '创建模板' : '保存修改') }}
          </button>
        </footer>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Check, Code2, Eye, LayoutTemplate, RefreshCw, X } from 'lucide-vue-next'
import { notificationApi } from '../../api'
import NotificationBlockEditor from './block-editor/NotificationBlockEditor.vue'
import RichTextEditor from './block-editor/RichTextEditor.vue'
import { DEFAULT_EMAIL_HTML, DEFAULT_SUBJECT, buildDefaultEmailBlocks } from './block-editor/defaultEmailTemplate.js'
import { renderBlockMini, buildSamplePayload } from './block-editor/blockMiniRenderers.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  template: { type: Object, default: null }
})
const emit = defineEmits(['close', 'saved'])

const EVENT_OPTIONS = [
  { value: 'completed', label: '任务完成' },
  { value: 'failed', label: '任务失败' },
  { value: 'waiting_manual', label: '等待人工处理' }
]

const DOMAIN_OPTIONS = [
  { value: 'import', label: '导入处理' },
  { value: 'rj_subtitle', label: 'RJ 字幕' },
  { value: 'subtitle_import', label: '字幕补配' },
  { value: 'asmr_sync', label: 'ASMR 同步' },
  { value: 'upload', label: '库存上传' },
  { value: 'circle_completion', label: '社团补全' },
  { value: 'system', label: '系统任务' }
]

const DEFAULT_FORM = () => ({
  name: '',
  description: '',
  channel: 'email',
  event_types: ['completed'],
  task_domains: [],
  editor_mode: 'html',
  blocks: [],
  subject_template: DEFAULT_SUBJECT,
  html_template: DEFAULT_EMAIL_HTML,
  text_template: '',
  enabled: true,
  is_default: false,
  sort_order: 0
})

const form = reactive(DEFAULT_FORM())
const saving = ref(false)
const previewing = ref(false)
const errorMsg = ref('')
const preview = reactive({ subject: '', html: '', text: '' })
const blockEditorRef = ref(null)
const fullPreviewOpen = ref(false)

async function openFullPreview() {
  if (!form.html_template?.trim()) return
  fullPreviewOpen.value = true
  await runPreview()
}

const isCreate = computed(() => !props.template?.id)

const canSave = computed(() => {
  if (!form.name.trim() || !form.event_types.length || !form.subject_template.trim()) return false
  if (form.editor_mode === 'blocks') return form.blocks.length > 0
  return !!form.html_template.trim()
})

watch(() => props.visible, (v) => {
  if (!v) return
  errorMsg.value = ''
  Object.assign(form, DEFAULT_FORM())
  if (props.template) {
    Object.assign(form, {
      ...DEFAULT_FORM(),
      ...props.template,
      event_types: Array.isArray(props.template.event_types) ? [...props.template.event_types] : ['completed'],
      task_domains: Array.isArray(props.template.task_domains) ? [...props.template.task_domains] : [],
      blocks: Array.isArray(props.template.blocks) ? JSON.parse(JSON.stringify(props.template.blocks)) : [],
    })
    // 历史遗留升级：旧版本创建的预设会把默认 HTML 镜像为单个 rich_text，
    // 只要仍然是「单镜像块 + html 未修改」就静默升级为拆分后的多块布局。
    if (form.editor_mode === 'blocks' && isLegacyDefaultMirror(form.blocks, form.html_template)) {
      form.blocks = buildDefaultEmailBlocks()
    }
  }
  preview.subject = ''
  preview.html = ''
  preview.text = ''
}, { immediate: true })

function toggleEvent(value) {
  const i = form.event_types.indexOf(value)
  if (i >= 0) form.event_types.splice(i, 1)
  else form.event_types.push(value)
}

function toggleDomain(value) {
  const i = form.task_domains.indexOf(value)
  if (i >= 0) form.task_domains.splice(i, 1)
  else form.task_domains.push(value)
}

async function runPreview() {
  if (previewing.value) return
  previewing.value = true
  errorMsg.value = ''
  try {
    // 后端预览需要落库的模板才能精确定位，但若是新建则只能用 payload 直接渲染。
    // 为了让"未保存就能预览"，我们组装一份本地变量做客户端简单 format。
    const event_type = form.event_types[0] || 'completed'
    const samplePayload = buildSamplePayload(event_type)
    let result
    if (props.template?.id) {
      result = await notificationApi.previewTemplate(props.template.id, samplePayload)
    } else {
      result = renderLocalPreview(samplePayload)
    }
    preview.subject = result.subject || ''
    preview.html = result.html || ''
    preview.text = result.text || ''
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message || '预览失败'
  } finally {
    previewing.value = false
  }
}

const EVENT_LABELS = { completed: '任务完成', failed: '任务失败', waiting_manual: '等待人工处理' }
const EVENT_ICONS = { completed: '✅', failed: '❌', waiting_manual: '⚠️' }

function renderLocalPreview(payload) {
  // 同时填充中文 key 和英文别名，让两种风格的模板都能正常预览
  const en = {
    title: payload.title || '',
    domain_label: payload.domain_label || '',
    summary: payload.summary || '',
    rjcode: payload.rjcode || '',
    event_label: EVENT_LABELS[payload.event_type] || '',
    event_icon: EVENT_ICONS[payload.event_type] || '',
    created_at: new Date().toLocaleString('zh-CN', { hour12: false })
  }
  const variables = {
    ...en,
    '任务标题': en.title,
    '摘要':     en.summary,
    '任务类型': en.domain_label,
    'RJ号':     en.rjcode,
    '事件名称': en.event_label,
    '事件图标': en.event_icon,
    '时间':     en.created_at,
    '严重程度': payload.severity || '',
    '业务数据块': renderPayloadSections(payload.event_type),
    '统计网格': renderPayloadSection(payload.event_type, 'stats_grid'),
    '文件树': renderPayloadSection(payload.event_type, 'file_tree'),
    '差异对比': renderPayloadSection(payload.event_type, 'diff'),
    '执行日志': renderPayloadSection(payload.event_type, 'task_log'),
  }
  // 占位符放宽：花括号内任意非空白非花括号字符（兼容中文）
  const fill = (tpl) => String(tpl || '').replace(/\{([^{}\s]+)\}/g, (raw, k) => {
    const rawHtmlKeys = {
      payload_sections: '业务数据块',
      stats_grid_section: '统计网格',
      file_tree_section: '文件树',
      diff_section: '差异对比',
      task_log_section: '执行日志',
    }
    if (variables[k] !== undefined && ['业务数据块', '统计网格', '文件树', '差异对比', '执行日志'].includes(k)) return variables[k]
    if (rawHtmlKeys[k]) return variables[rawHtmlKeys[k]]
    return variables[k] !== undefined ? escapeHtml(variables[k]) : raw
  })
  return {
    subject: fill(form.subject_template),
    html: fill(form.html_template),
    text: fill(form.text_template) || variables.summary
  }
}

function renderPayloadSections(eventType = 'completed') {
  return [
    renderPayloadSection(eventType, 'stats_grid'),
    renderPayloadSection(eventType, 'file_tree'),
    renderPayloadSection(eventType, 'diff'),
    renderPayloadSection(eventType, 'task_log'),
  ].join('')
}

function renderPayloadSection(eventType = 'completed', section = 'stats_grid') {
  const sample = buildSamplePayload(eventType)
  const blockMap = {
    stats_grid: {
      type: 'stats_grid',
      props: {
        columns: 3,
        items: [
          { key: 'total_files', label: '总文件数', icon: '' },
          { key: 'total_size', label: '总大小', icon: '' },
          { key: 'duration', label: '耗时', icon: '' },
        ],
      },
    },
    file_tree: { type: 'file_tree', props: { title: '文件清单', sourceKey: 'file_tree', maxItems: 8 } },
    diff: { type: 'diff_view', props: { title: '数据差异', sourceKey: 'diff_items' } },
    task_log: { type: 'task_log', props: { title: '执行日志', sourceKey: 'recent_logs', maxLines: 6 } },
  }
  return renderBlockMini(blockMap[section], sample)
}

function createHtmlMirrorBlock(html = form.html_template) {
  return {
    id: `blk_html_${Date.now().toString(36)}`,
    type: 'rich_text',
    enabled: true,
    schemaVersion: 1,
    props: {
      contentJson: null,
      htmlCache: html || '',
      mirrorSource: 'html',
    },
  }
}

// 判断当前 blocks 是否是「默认 HTML 镜像为单个 rich_text」的遗留状态
function isLegacyDefaultMirror(blocks, htmlTemplate) {
  if (!Array.isArray(blocks) || blocks.length !== 1) return false
  const only = blocks[0]
  if (!only || only.type !== 'rich_text') return false
  const isMirror = only.props?.mirrorSource === 'html'
  const cache = (only.props?.htmlCache || '').trim()
  const html = (htmlTemplate || '').trim()
  const def = DEFAULT_EMAIL_HTML.trim()
  // 两种判定：明确标记为 html 镜像，或者 cache/html 仍然是默认 HTML
  return isMirror || cache === def || html === def
}

function resetToDefaultBlocks() {
  form.blocks = buildDefaultEmailBlocks()
}

function syncHtmlMirrorBlock() {
  const first = form.blocks[0]
  if (!first || first.type !== 'rich_text' || first.props?.mirrorSource === 'html') {
    form.blocks = [createHtmlMirrorBlock()]
  }
}

function setEditorMode(mode) {
  if (mode === form.editor_mode) return
  if (mode === 'blocks' && !form.blocks.length) {
    // 默认 HTML 转积木：用拆分好的多个独立块；
    // 用户已自定义过 HTML 时才退回“整段 HTML 镜像为单个富文本块”。
    if ((form.html_template || '').trim() === DEFAULT_EMAIL_HTML.trim()) {
      form.blocks = buildDefaultEmailBlocks()
    } else {
      form.blocks = [createHtmlMirrorBlock()]
    }
  }
  if (mode === 'html' && blockEditorRef.value?.getBlocks) {
    form.blocks = blockEditorRef.value.getBlocks()
  }
  form.editor_mode = mode
}

function onHtmlTemplateChange(value) {
  form.html_template = value
  if (!form.blocks.length || form.blocks[0]?.props?.mirrorSource === 'html') {
    form.blocks = [createHtmlMirrorBlock(value)]
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

async function onSave() {
  if (saving.value || !canSave.value) return
  saving.value = true
  errorMsg.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      channel: 'email',
      event_types: [...form.event_types],
      task_domains: [...form.task_domains],
      editor_mode: form.editor_mode,
      blocks: form.editor_mode === 'blocks' ? (blockEditorRef.value?.getBlocks() ?? form.blocks) : (syncHtmlMirrorBlock(), form.blocks),
      subject_template: form.subject_template,
      html_template: form.html_template,
      text_template: form.text_template,
      enabled: !!form.enabled,
      is_default: !!form.is_default,
      sort_order: Number(form.sort_order) || 0
    }
    let saved
    if (isCreate.value) {
      saved = await notificationApi.createTemplate(payload)
    } else {
      saved = await notificationApi.updateTemplate(props.template.id, payload)
    }
    emit('saved', saved)
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

function onCancel() {
  if (saving.value) return
  emit('close')
}
</script>

<style scoped>
.tpl-editor-mask {
  position: fixed;
  inset: 0;
  z-index: 99990;
  background: rgba(15, 17, 21, 0.42);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.tpl-editor-panel {
  width: min(1480px, 100%);
  height: calc(100vh - 32px);
  max-height: calc(100vh - 32px);
  background: #fff;
  border-radius: 18px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tpl-editor-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 22px 26px 18px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.08);
}

.tpl-editor-head-text {
  flex: 1;
}

.tpl-editor-kicker {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(0, 113, 227, 0.85);
  padding: 2px 8px;
  background: rgba(0, 113, 227, 0.08);
  border-radius: 99px;
  margin-bottom: 8px;
}

.tpl-editor-title {
  font-size: 18px;
  font-weight: 600;
  color: #1d1d1f;
  margin-bottom: 4px;
}

.tpl-editor-desc {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.55);
  line-height: 1.5;
}

.tpl-editor-desc code {
  background: rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 5px;
  padding: 1px 5px;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #1d1d1f;
}

.tpl-icon-btn {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 10px;
  background: #fff;
  color: rgba(29, 29, 31, 0.6);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-icon-btn:hover {
  transform: translateY(-2px) scale(1.02);
  color: #1d1d1f;
  border-color: rgba(29, 29, 31, 0.16);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.tpl-icon-btn:active {
  transform: scale(0.96);
}

.tpl-editor-body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: 0;
  overflow: hidden;
}

.tpl-editor-form {
  padding: 20px 26px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-right: 1px solid rgba(29, 29, 31, 0.06);
}

.tpl-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tpl-field--row {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
}

.tpl-field--inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.tpl-field-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.7);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.tpl-field-hint {
  font-weight: 400;
  font-size: 11px;
  color: rgba(29, 29, 31, 0.45);
}

.tpl-input,
.tpl-textarea {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  color: #1d1d1f;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 10px;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.tpl-input:focus,
.tpl-textarea:focus {
  border-color: rgba(0, 113, 227, 0.5);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.12);
}

.tpl-textarea {
  resize: vertical;
  line-height: 1.55;
}

.tpl-textarea--code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.55;
}

.tpl-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tpl-chip {
  padding: 5px 11px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.7);
  background: rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tpl-chip:hover {
  transform: translateY(-2px) scale(1.02);
  background: rgba(0, 113, 227, 0.06);
  border-color: rgba(0, 113, 227, 0.2);
  color: #0071e3;
}

.tpl-chip:active {
  transform: scale(0.96);
}

.tpl-chip.is-active {
  background: #1d1d1f;
  border-color: #1d1d1f;
  color: #fff;
}

.tpl-toggle {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #1d1d1f;
}

.tpl-toggle small {
  display: block;
  font-size: 11px;
  color: rgba(29, 29, 31, 0.5);
  font-weight: 400;
}

.tpl-editor-preview {
  padding: 20px 26px;
  background: #fafafa;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tpl-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tpl-preview-kicker {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.55);
}

.tpl-preview-refresh {
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

.tpl-preview-refresh:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(0, 113, 227, 0.3);
  color: #0071e3;
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.1);
}

.tpl-preview-refresh:active:not(:disabled) {
  transform: scale(0.96);
}

.tpl-preview-refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@keyframes spin-once {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

.spin-once {
  animation: spin-once 0.8s linear;
}

.tpl-preview-subject {
  padding: 10px 12px;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tpl-preview-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.45);
}

.tpl-preview-value {
  font-size: 13px;
  color: #1d1d1f;
  word-break: break-all;
}

.tpl-preview-frame-wrap {
  flex: 1;
  min-height: 320px;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  position: relative;
}

.tpl-preview-frame {
  width: 100%;
  height: 100%;
  min-height: 320px;
  border: 0;
}

.tpl-preview-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.45);
}

.tpl-preview-text pre {
  padding: 10px 12px;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #1d1d1f;
  white-space: pre-wrap;
  word-break: break-word;
}

.tpl-editor-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 26px;
  border-top: 1px solid rgba(29, 29, 31, 0.08);
  background: #fafafa;
}

.tpl-editor-spacer {
  flex: 1;
}

.tpl-editor-err {
  font-size: 12px;
  color: #d93025;
  font-weight: 500;
}

.tpl-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  border: 1px solid transparent;
}

.tpl-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
}

.tpl-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.tpl-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tpl-btn--ghost {
  color: rgba(29, 29, 31, 0.7);
  background: #fff;
  border-color: rgba(29, 29, 31, 0.12);
}

.tpl-btn--ghost:hover:not(:disabled) {
  border-color: rgba(29, 29, 31, 0.24);
  color: #1d1d1f;
}

.tpl-btn--primary {
  color: #fff;
  background: #1d1d1f;
  border-color: #1d1d1f;
}

.tpl-btn--primary:hover:not(:disabled) {
  background: #000;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}

.tpl-fade-enter-active,
.tpl-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.tpl-fade-enter-from,
.tpl-fade-leave-to {
  opacity: 0;
}

.tpl-fade-enter-from .tpl-editor-panel,
.tpl-fade-leave-to .tpl-editor-panel {
  transform: translateY(8px) scale(0.98);
}

/* ─────────── HTML / 富文本模式：与积木模式一致的 meta-bar 布局 ─────────── */
.tpl-editor-blocks-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fafafa;
}
.tpl-rte-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px 20px;
  overflow: hidden;
}
.tpl-meta-bar--secondary {
  padding-top: 0;
}
.tpl-reset-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 7px;
  background: #fff;
  color: rgba(29, 29, 31, 0.7);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
}
.tpl-reset-btn:hover {
  border-color: rgba(0, 113, 227, 0.4);
  background: rgba(0, 113, 227, 0.04);
  color: #0071e3;
}
.tpl-reset-btn:active { transform: scale(0.96); }
.tpl-meta-bar-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.45);
  flex-shrink: 0;
}
.tpl-meta-bar-hint {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.4);
  margin-left: 4px;
}
.tpl-meta-bar-spacer { flex: 1; }
.tpl-meta-input--subject {
  flex: 1;
  min-width: 240px;
}
.tpl-fullscreen-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tpl-fullscreen-btn:hover:not(:disabled) {
  border-color: rgba(0, 113, 227, 0.4);
  color: #0071e3;
  background: rgba(0, 113, 227, 0.04);
  transform: translateY(-1px);
}
.tpl-fullscreen-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─────────── 全屏预览 dialog ─────────── */
.tpl-prev-mask {
  position: fixed;
  inset: 0;
  z-index: 99995;
  background: rgba(15, 17, 21, 0.6);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}
.tpl-prev-panel {
  width: min(960px, 100%);
  height: calc(100vh - 64px);
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.32);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tpl-prev-head {
  display: flex;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
  background: #fafafa;
}
.tpl-prev-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
}
.tpl-prev-head-hint {
  font-size: 11.5px;
  font-weight: 400;
  color: rgba(29, 29, 31, 0.5);
  margin-left: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tpl-prev-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: rgba(29, 29, 31, 0.5);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tpl-prev-close:hover {
  background: rgba(0, 0, 0, 0.05);
  color: #1d1d1f;
}
.tpl-prev-frame-wrap {
  flex: 1;
  background: #f6f7f9;
  overflow: hidden;
  display: flex;
}
.tpl-prev-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: transparent;
}
.tpl-prev-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: rgba(29, 29, 31, 0.4);
}
.tpl-prev-fade-enter-active,
.tpl-prev-fade-leave-active {
  transition: opacity 0.18s ease;
}
.tpl-prev-fade-enter-from,
.tpl-prev-fade-leave-to {
  opacity: 0;
}

@media (max-width: 960px) {
  .tpl-editor-body {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1fr) minmax(280px, 1fr);
  }

  .tpl-editor-form {
    border-right: 0;
    border-bottom: 1px solid rgba(29, 29, 31, 0.06);
  }
}

/* ---- 模式切换按钮 ---- */
.tpl-mode-toggle {
  display: flex;
  align-items: center;
  gap: 2px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 10px;
  padding: 3px;
  flex-shrink: 0;
}
.tpl-mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.6);
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
}
.tpl-mode-btn.is-active {
  background: #fff;
  color: #1d1d1f;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

/* ---- blocks 模式布局 ---- */
.tpl-editor-blocks-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.tpl-meta-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.07);
  background: #fafafa;
}
.tpl-meta-input {
  flex: 0 0 auto;
  width: 180px;
  padding: 6px 10px;
  font-size: 12px;
}
.tpl-meta-input--subject { width: 300px; }
.tpl-meta-chips { display: flex; gap: 4px; }
.tpl-meta-chips .tpl-chip { padding: 4px 10px; font-size: 11px; }

/* ───── F5：HTML 模式美化 ───── */

/* 顶部引导卡：建议切积木 */
.tpl-mode-suggest {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(0, 113, 227, 0.18);
  background: linear-gradient(135deg, rgba(0, 113, 227, 0.04), rgba(0, 113, 227, 0.08));
  border-radius: 12px;
  margin-bottom: 4px;
}
.tpl-mode-suggest-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.tpl-mode-suggest-text strong {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
}
.tpl-mode-suggest-text small {
  font-size: 11.5px;
  color: rgba(29, 29, 31, 0.6);
  line-height: 1.5;
}
.tpl-mode-suggest-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #0071e3;
  border: 1px solid #0071e3;
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  flex-shrink: 0;
  box-shadow: 0 1px 4px rgba(0, 113, 227, 0.3);
}
.tpl-mode-suggest-btn:hover {
  background: #0056b3;
  border-color: #0056b3;
  transform: translateY(-1px) scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.4);
}
.tpl-mode-suggest-btn:active { transform: scale(0.96); }

/* HTML 变量插入工具栏 */
.tpl-html-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 10px;
  background: #fafafa;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-bottom: none;
  border-radius: 10px 10px 0 0;
}
.tpl-html-toolbar-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.45);
  margin-right: 4px;
}
/* BlockNote 风格变量 pill */
.tpl-var-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px 2px 7px;
  font-size: 11.5px;
  font-weight: 500;
  color: #f5f5f7;
  background: #2a2d34;
  border: 1px solid #3a3d45;
  border-radius: 99px;
  cursor: pointer;
  line-height: 1.5;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.tpl-var-pill:hover {
  background: #1d1d1f;
  border-color: #4a4d55;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.18);
}
.tpl-var-pill:active { transform: translateY(0); }
.tpl-var-pill-dot {
  width: 6px;
  height: 6px;
  background: #6ea8fe;
  transform: rotate(45deg);
  border-radius: 1px;
  flex-shrink: 0;
}

/* 代码编辑器容器 + 角标 */
.tpl-code-editor {
  position: relative;
}
.tpl-code-editor-area {
  /* 与工具栏拼接：上方圆角去掉 */
  border-radius: 0 0 10px 10px !important;
  background: #1d1d1f !important;
  color: #f5f5f7 !important;
  border-color: rgba(29, 29, 31, 0.16) !important;
  font-family: ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, monospace !important;
  font-size: 12.5px !important;
  line-height: 1.65 !important;
  tab-size: 2;
  padding: 14px 16px !important;
  caret-color: #0a84ff;
}
.tpl-code-editor-area:focus {
  border-color: rgba(10, 132, 255, 0.6) !important;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.15) !important;
}
.tpl-code-editor-area::placeholder {
  color: rgba(245, 245, 247, 0.3);
  font-family: inherit;
}
.tpl-code-editor-area::selection {
  background: rgba(10, 132, 255, 0.3);
}
.tpl-code-editor-hint {
  position: absolute;
  top: 8px;
  right: 12px;
  font-size: 9.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: rgba(245, 245, 247, 0.35);
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  pointer-events: none;
}

/* 字段标签内 code 样式（HTML 模式提示文字） */
.tpl-field-label code {
  font-size: 10.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(29, 29, 31, 0.08);
  padding: 1px 5px;
  border-radius: 4px;
  color: #0071e3;
  margin: 0 1px;
}
</style>
