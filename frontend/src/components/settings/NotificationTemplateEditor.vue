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

          <!-- 大号富文本编辑器 + 原始 HTML 源码 -->
          <div class="tpl-rte-wrap tpl-rte-wrap--split">
            <div class="tpl-html-pane tpl-html-pane--visual">
              <div class="tpl-html-pane-head">
                <span class="tpl-html-pane-title">实时预览</span>
                <span class="tpl-html-pane-hint">含示例数据</span>
              </div>
              <div class="tpl-html-pane-body tpl-html-pane-body--preview">
                <iframe
                  class="tpl-html-preview-frame"
                  :srcdoc="visualRenderedHtml"
                  sandbox="allow-scripts"
                  title="邮件预览"
                />
              </div>
            </div>
            <div class="tpl-html-pane tpl-html-pane--raw">
              <div class="tpl-html-pane-head">
                <span class="tpl-html-pane-title">原始 HTML</span>
                <div class="tpl-html-pane-head-right">
                  <span v-if="componentEditContext.active" class="tpl-component-edit-tag">正在编辑：{{ componentEditContext.key }}</span>

                  <button v-if="componentEditContext.active" type="button" class="tpl-html-pane-btn" @click="cancelComponentEdit">取消片段编辑</button>
                  <button v-if="componentEditContext.active" type="button" class="tpl-html-pane-btn tpl-html-pane-btn--primary" @click="applyComponentEditToTemplate">替换占位符并返回模板</button>
                  <button v-else type="button" class="tpl-html-pane-btn" @click="formatHtmlTemplate">一键整理</button>
                  <button v-if="!componentEditContext.active" type="button" class="tpl-html-pane-btn" @click="openRawHtmlModal">
                    <Maximize2 :size="11" :stroke-width="2.4" />
                    放大
                  </button>

                </div>
              </div>
              <div class="tpl-html-pane-body">
                <div
                  class="tpl-html-code-wrap"
                  :class="{ 'is-editing': rawHtmlFocused }"
                  @click="onCodeWrapClick($event, 'main')"
                  @mouseover="onOverlayMouseover"
                  @mouseleave="onOverlayMouseleave"
                >
                  <pre
                    ref="rawHtmlOverlayRef"
                    class="tpl-html-code-overlay tpl-html-code-overlay--clickable"
                    v-html="highlightedHtml"
                  />
                  <textarea
                    ref="rawHtmlTextareaRef"
                    class="tpl-textarea tpl-textarea--code tpl-html-raw-view"
                    v-model="form.html_template"
                    spellcheck="false"
                    @input="onRawHtmlInput"
                    @focus="rawHtmlFocused = true"
                    @blur="onRawHtmlBlur"
                    @scroll="syncRawHtmlOverlayScroll($event, 'main')"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 组件文档浮层（JetBrains Quick Doc 风格） -->
        <teleport to="body">
          <transition name="tpl-doc-fade">
            <div
              v-if="componentDocPanel.open"
              ref="componentDocPanelRef"
              class="tpl-component-doc-panel"
              :style="{ left: componentDocPanel.x + 'px', top: componentDocPanel.y + 'px' }"
              @mouseenter="onDocPanelMouseenter"
              @mouseleave="onDocPanelMouseleave"
            >
              <div class="tpl-component-doc-header">
                <span class="tpl-component-doc-label">组件占位符</span>
                <span class="tpl-component-doc-key">{{ componentDocPanel.key }}</span>
                <button class="tpl-component-doc-close" type="button" @click="closeComponentDocPanel">×</button>
              </div>
              <div class="tpl-component-doc-body">
                <template v-if="isComponentHtmlEditable(componentDocPanel.key)">
                  <div class="tpl-component-doc-section-title">编辑组件 HTML（会替换对应占位符）</div>
                  <div class="tpl-component-doc-edit-wrap" @click="focusComponentDocEditor">
                    <pre
                      ref="componentDocEditorOverlayRef"
                      class="tpl-component-doc-editor-overlay"
                      v-html="buildHighlightedHtml(componentDocDraftHtml)"
                    />
                    <textarea
                      ref="componentDocEditorRef"
                      v-model="componentDocDraftHtml"
                      class="tpl-component-doc-editor-input"
                      spellcheck="false"
                      @scroll="syncComponentDocEditorScroll"
                    />
                  </div>
                  <div class="tpl-component-doc-editor-actions">
                    <button
                      type="button"
                      class="tpl-html-pane-btn tpl-html-pane-btn--primary"
                      @click="applyComponentDraftHtml"
                    >
                      应用到模板（替换 {{ componentDocPanel.key }}）
                    </button>
                  </div>
                </template>
                <template v-else>
                  <div class="tpl-component-doc-section-title">示例 HTML 输出</div>
                  <pre
                    class="tpl-component-doc-code"
                    v-html="buildHighlightedHtml(componentPreviewMap[componentDocPanel.key] || '')"
                  />
                </template>
              </div>
            </div>
          </transition>
        </teleport>

        <!-- 全屏源码编辑 dialog -->
        <transition name="tpl-prev-fade">
          <div v-if="rawHtmlModalOpen" class="tpl-html-modal-mask" @click.self="rawHtmlModalOpen = false">
            <div class="tpl-html-modal-panel">
              <header class="tpl-html-modal-head">
                <div class="tpl-html-modal-title">原始 HTML 放大编辑</div>
                <div class="tpl-html-modal-actions">
                  <button type="button" class="tpl-html-pane-btn" @click="formatHtmlTemplate">一键整理</button>

                  <button class="tpl-prev-close" type="button" @click="rawHtmlModalOpen = false" title="关闭">
                    <X :size="18" :stroke-width="2.4" />
                  </button>
                </div>
              </header>
              <div class="tpl-html-modal-body">
                <div
                  class="tpl-html-code-wrap"
                  :class="{ 'is-editing': rawHtmlFocused }"
                  @click="onCodeWrapClick($event, 'modal')"
                  @mouseover="onOverlayMouseover"
                  @mouseleave="onOverlayMouseleave"
                >
                  <pre ref="rawHtmlModalOverlayRef" class="tpl-html-code-overlay" v-html="highlightedHtml" />
                  <textarea
                    ref="rawHtmlModalTextareaRef"
                    class="tpl-textarea tpl-textarea--code tpl-html-raw-view"
                    v-model="form.html_template"
                    spellcheck="false"
                    @input="onRawHtmlInput"
                    @focus="rawHtmlFocused = true"
                    @blur="onRawHtmlBlur"
                    @scroll="syncRawHtmlOverlayScroll($event, 'modal')"
                  />
                </div>
              </div>
            </div>
          </div>
        </transition>

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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Check, Code2, Eye, LayoutTemplate, Maximize2, RefreshCw, X } from 'lucide-vue-next'
import { notificationApi } from '../../api'
import NotificationBlockEditor from './block-editor/NotificationBlockEditor.vue'
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
const htmlEditorVersion = ref(0)
const rawHtmlFocused = ref(false)
const rawHtmlOverlayRef = ref(null)
const rawHtmlModalOverlayRef = ref(null)
const rawHtmlTextareaRef = ref(null)
const rawHtmlModalTextareaRef = ref(null)
const rawHtmlModalOpen = ref(false)
const rawHtmlSyncProfile = ref('medium')

// 组件文档浮层状态
const componentDocPanel = reactive({ open: false, key: '', x: 0, y: 0 })
const componentDocPanelRef = ref(null)
const componentDocEditorRef = ref(null)
const componentDocEditorOverlayRef = ref(null)
const componentDocDraftHtml = ref('')
const componentDocPinned = ref(false)
const componentEditContext = reactive({ active: false, key: '', originalHtml: '' })
let componentDocHideTimer = null

function openComponentDocPanel(options) {
  const { key, rect = null, mouseX = 0, mouseY = 0, pin = false } = options || {}
  if (!key) return

  if (componentDocHideTimer) {
    clearTimeout(componentDocHideTimer)
    componentDocHideTimer = null
  }

  const panelW = 680
  const panelH = 320 // 估算高度
  let x = rect ? rect.left : mouseX
  let y = rect ? (rect.bottom + 6) : (mouseY + 8)

  if (x + panelW + 16 > window.innerWidth) {
    x = Math.max(8, window.innerWidth - panelW - 16)
  }
  if (y + panelH + 16 > window.innerHeight) {
    y = rect
      ? Math.max(8, rect.top - panelH - 6)
      : Math.max(8, window.innerHeight - panelH - 16)
  }

  componentDocPanel.key = key
  componentDocPanel.x = x
  componentDocPanel.y = y
  componentDocDraftHtml.value = componentPreviewMap.value[key] || ''
  componentDocPanel.open = true
  componentDocPinned.value = !!pin
}

function onOverlayMouseover(event) {
  if (componentDocPinned.value || componentEditContext.active) return
  const span = event.target.closest
    ? event.target.closest('[data-component-key]')
    : null
  if (!span) return
  const key = span.dataset.componentKey
  if (!key) return
  openComponentDocPanel({ key, rect: span.getBoundingClientRect(), pin: false })
}

function onOverlayMouseleave(event) {
  if (componentDocPinned.value) return
  // 延迟关闭，给鼠标移入浮层本身的时间
  componentDocHideTimer = setTimeout(() => {
    if (!componentDocPinned.value) {
      componentDocPanel.open = false
    }
    componentDocHideTimer = null
  }, 180)
}

function onDocPanelMouseenter() {
  if (componentDocHideTimer) {
    clearTimeout(componentDocHideTimer)
    componentDocHideTimer = null
  }
}

function onDocPanelMouseleave() {
  if (componentDocPinned.value) return
  componentDocHideTimer = setTimeout(() => {
    if (!componentDocPinned.value) {
      componentDocPanel.open = false
    }
    componentDocHideTimer = null
  }, 120)
}

function getComponentPlaceholderTokens(componentKey) {
  if (componentKey === '业务数据块') return ['业务数据块', 'payload_sections']
  if (componentKey === '统计网格') return ['统计网格', 'stats_grid_section']
  if (componentKey === '文件树') return ['文件树', 'file_tree_section']
  if (componentKey === '差异对比') return ['差异对比', 'diff_section']
  if (componentKey === '执行日志') return ['执行日志', 'task_log_section']
  return []
}

function isComponentHtmlEditable(componentKey) {
  return getComponentPlaceholderTokens(componentKey).length > 0
}

function applyComponentDraftHtml() {
  const key = componentDocPanel.key
  const draft = String(componentDocDraftHtml.value || '').trim()
  if (!key || !draft) return
  const tokens = getComponentPlaceholderTokens(key)
  if (!tokens.length) return

  let nextHtml = String(form.html_template || '')
  for (const token of tokens) {
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = new RegExp(`\\{${escaped}\\}`, 'g')
    nextHtml = nextHtml.replace(re, draft)
  }
  form.html_template = nextHtml
  applyRawHtmlToVisual()
}

const saving = ref(false)
const previewing = ref(false)
const errorMsg = ref('')
const preview = reactive({ subject: '', html: '', text: '' })
const blockEditorRef = ref(null)
const fullPreviewOpen = ref(false)
let rawHtmlSyncTimer = null

const highlightedHtml = computed(() => buildHighlightedHtml(form.html_template))
const rawHtmlSyncDelay = computed(() => {
  if (rawHtmlSyncProfile.value === 'fast') return 220
  if (rawHtmlSyncProfile.value === 'slow') return 760
  return 420
})
const componentPreviewMap = computed(() => {
  const eventType = form.event_types[0] || 'completed'
  return {
    '业务数据块': beautifyHtml(renderPayloadSections(eventType)),
    '统计网格': beautifyHtml(renderPayloadSection(eventType, 'stats_grid')),
    '文件树': beautifyHtml(renderPayloadSection(eventType, 'file_tree')),
    '差异对比': beautifyHtml(renderPayloadSection(eventType, 'diff')),
    '执行日志': beautifyHtml(renderPayloadSection(eventType, 'task_log')),
  }
})

// ---- 实时预览 (iframe) ----
const visualRenderedHtml = ref('')
let _visualPreviewTimer = null

function buildVisualPreviewSrcdoc() {
  const event_type = form.event_types[0] || 'completed'
  const samplePayload = buildSamplePayload(event_type)
  const en = {
    title: samplePayload.title || '',
    domain_label: samplePayload.domain_label || '',
    summary: samplePayload.summary || '',
    rjcode: samplePayload.rjcode || '',
    event_label: EVENT_LABELS[samplePayload.event_type] || '',
    event_icon: EVENT_ICONS[samplePayload.event_type] || '',
    created_at: new Date().toLocaleString('zh-CN', { hour12: false })
  }
  const sectionStats = renderPayloadSection(event_type, 'stats_grid')
  const sectionTree = renderPayloadSection(event_type, 'file_tree')
  const sectionDiff = renderPayloadSection(event_type, 'diff')
  const sectionLog = renderPayloadSection(event_type, 'task_log')
  const bizBlocks = {
    '统计网格': sectionStats,
    '文件树': sectionTree,
    '差异对比': sectionDiff,
    '执行日志': sectionLog,
  }
  const aliasMap = {
    payload_sections: '业务数据块',
    stats_grid_section: '统计网格',
    file_tree_section: '文件树',
    diff_section: '差异对比',
    task_log_section: '执行日志',
  }
  const plainVars = {
    ...en,
    '任务标题': en.title,
    '摘要': en.summary,
    '任务类型': en.domain_label,
    'RJ号': en.rjcode,
    '事件名称': en.event_label,
    '事件图标': en.event_icon,
    '时间': en.created_at,
    '严重程度': samplePayload.severity || '',
  }
  const phStyle = 'cursor:pointer;outline:2px dashed transparent;transition:outline-color 0.15s'
  const phOver = "this.style.outlineColor='rgba(0,113,227,0.4)'"
  const phOut = "this.style.outlineColor='transparent'"
  const renderPreviewPlaceholder = (key, innerHtml) => `<div data-ph="${key}" style="${phStyle}" onmouseover="${phOver}" onmouseout="${phOut}" title="点击跳转到占位符 {${key}}">${innerHtml}</div>`
  const businessSectionsHtml = [
    renderPreviewPlaceholder('统计网格', sectionStats),
    renderPreviewPlaceholder('文件树', sectionTree),
    renderPreviewPlaceholder('差异对比', sectionDiff),
    renderPreviewPlaceholder('执行日志', sectionLog),
  ].join('')
  const businessBlockHtml = renderPreviewPlaceholder('业务数据块', businessSectionsHtml)

  let sourceHtml = String(form.html_template || '')
  if (componentEditContext.active && componentEditContext.key === '业务数据块') {
    const sectionPairs = [
      ['统计网格', sectionStats],
      ['文件树', sectionTree],
      ['差异对比', sectionDiff],
      ['执行日志', sectionLog],
    ]
    for (const [secKey, secHtml] of sectionPairs) {
      if (sourceHtml.includes(secHtml)) {
        sourceHtml = sourceHtml.replace(secHtml, renderPreviewPlaceholder(secKey, secHtml))
      }
    }
  }

  const html = sourceHtml.replace(/\{([^{}\s]+)\}/g, (raw, k) => {
    const chKey = aliasMap[k]
    if (k === '业务数据块' || k === 'payload_sections') return businessBlockHtml
    if (chKey && bizBlocks[chKey] !== undefined) return renderPreviewPlaceholder(chKey, bizBlocks[chKey])
    if (bizBlocks[k] !== undefined) return renderPreviewPlaceholder(k, bizBlocks[k])
    if (plainVars[k] !== undefined) return escapeHtml(String(plainVars[k]))
    return raw
  })
  const clickScript = `<script>(function(){
    function inferKeyByText(txt){
      var s=String(txt||'');
      if(/文件清单|track0\d|cover\.jpg|sample\.mp3/i.test(s)) return '文件树';
      if(/总文件数|总大小|耗时/.test(s)) return '统计网格';
      if(/数据差异|社团名|RJ\s*编号/.test(s)) return '差异对比';
      if(/执行日志|开始处理任务|任务完成/.test(s)) return '执行日志';
      return '';
    }
    document.addEventListener('click', function(e){
      var el=e.target;
      while(el&&el!==document.body){
        if(el.hasAttribute&&el.hasAttribute('data-ph')){
          window.parent.postMessage({type:'preview-placeholder-click',key:el.getAttribute('data-ph')},'*');
          return;
        }
        var key=inferKeyByText(el.innerText||el.textContent||'');
        if(key){
          window.parent.postMessage({type:'preview-placeholder-click',key:key},'*');
          return;
        }
        el=el.parentElement;
      }
    }, true);
  })();<\/script>`
  return html + clickScript
}

function refreshVisualPreview(immediate) {
  if (_visualPreviewTimer) { clearTimeout(_visualPreviewTimer); _visualPreviewTimer = null }
  if (immediate) {
    visualRenderedHtml.value = buildVisualPreviewSrcdoc()
  } else {
    _visualPreviewTimer = setTimeout(() => {
      visualRenderedHtml.value = buildVisualPreviewSrcdoc()
      _visualPreviewTimer = null
    }, 380)
  }
}

function jumpToPlaceholderInEditor(key) {
  const textarea = rawHtmlTextareaRef.value
  if (!textarea) return
  const text = String(form.html_template || '')

  const selectRange = (range) => {
    textarea.focus()
    textarea.selectionStart = range.start
    textarea.selectionEnd = range.end
    const linesBefore = text.slice(0, range.start).split('\n').length - 1
    const lh = parseFloat(getComputedStyle(textarea).lineHeight) || 21
    const top = Math.max(0, linesBefore * lh - textarea.clientHeight / 3)
    textarea.scrollTop = top
    if (rawHtmlOverlayRef.value) rawHtmlOverlayRef.value.scrollTop = top
  }

  const findTokenRange = (tokens) => {
    for (const token of tokens) {
      const escaped = String(token || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const re = new RegExp(`\\{\\s*${escaped}\\s*\\}`)
      const m = re.exec(text)
      if (m && typeof m.index === 'number') {
        return { start: m.index, end: m.index + m[0].length }
      }
    }
    return null
  }

  const findBusinessSectionRange = (sectionKey) => {
    const anchors = {
      '统计网格': ['总文件数', '总大小', '耗时'],
      '文件树': ['文件清单', 'track01.flac', 'cover.jpg', 'sample.mp3'],
      '差异对比': ['数据差异', '社团名', 'RJ 编号'],
      '执行日志': ['执行日志', '开始处理任务', '任务完成'],
    }
    const list = anchors[sectionKey] || []
    for (const anchor of list) {
      const idx = text.indexOf(anchor)
      if (idx >= 0) return { start: idx, end: idx + anchor.length }
    }
    return null
  }

  // 片段编辑模式：优先在当前业务块源码中定位子组件语句
  if (componentEditContext.active && componentEditContext.key === '业务数据块') {
    const sectionRange = findBusinessSectionRange(key)
    if (sectionRange) {
      selectRange(sectionRange)
      return
    }
  }

  let range = findTokenRange(getComponentPlaceholderTokens(key))
  if (!range && key !== '业务数据块') {
    range = findTokenRange(getComponentPlaceholderTokens('业务数据块'))
  }
  if (!range) return

  selectRange(range)
}

function _onPreviewMessage(event) {
  if (event.data?.type !== 'preview-placeholder-click') return
  const key = String(event.data.key || '')
  if (key) jumpToPlaceholderInEditor(key)
}

onMounted(() => { window.addEventListener('message', _onPreviewMessage); refreshVisualPreview(true) })
onUnmounted(() => {
  window.removeEventListener('message', _onPreviewMessage)
  if (_visualPreviewTimer) { clearTimeout(_visualPreviewTimer); _visualPreviewTimer = null }
})

watch(() => form.html_template, () => refreshVisualPreview(false))
watch(() => form.event_types, () => refreshVisualPreview(true), { deep: true })
// ---- end 实时预览 ----

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
  form.html_template = beautifyHtml(form.html_template)
  onHtmlTemplateChange(form.html_template)
  preview.subject = ''
  preview.html = ''
  preview.text = ''
  if (rawHtmlSyncTimer) {
    clearTimeout(rawHtmlSyncTimer)
    rawHtmlSyncTimer = null
  }
  componentEditContext.active = false
  componentEditContext.key = ''
  componentEditContext.originalHtml = ''
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

function onRawHtmlInput() {
  onHtmlTemplateChange(form.html_template)
  scheduleRawHtmlSync()
}

function onRawHtmlBlur() {
  rawHtmlFocused.value = false
  if (rawHtmlSyncTimer) {
    clearTimeout(rawHtmlSyncTimer)
    rawHtmlSyncTimer = null
  }
  applyRawHtmlToVisual()
}

function scheduleRawHtmlSync() {
  if (!rawHtmlFocused.value) return
  if (rawHtmlSyncTimer) clearTimeout(rawHtmlSyncTimer)
  rawHtmlSyncTimer = setTimeout(() => {
    applyRawHtmlToVisual()
    rawHtmlSyncTimer = null
  }, rawHtmlSyncDelay.value)
}

function syncRawHtmlOverlayScroll(event, target = 'main') {
  const overlay = target === 'modal' ? rawHtmlModalOverlayRef.value : rawHtmlOverlayRef.value
  if (!overlay) return
  overlay.scrollTop = event.target.scrollTop
  overlay.scrollLeft = event.target.scrollLeft
}

function openRawHtmlModal() {
  rawHtmlModalOpen.value = true
}

function focusRawHtmlEditor(target = 'main') {
  const textarea = target === 'modal' ? rawHtmlModalTextareaRef.value : rawHtmlTextareaRef.value
  textarea?.focus()
}

function applyRawHtmlToVisual() {
  if (rawHtmlSyncTimer) {
    clearTimeout(rawHtmlSyncTimer)
    rawHtmlSyncTimer = null
  }
  htmlEditorVersion.value += 1
  onHtmlTemplateChange(form.html_template)
}

function formatHtmlTemplate() {
  form.html_template = beautifyHtml(form.html_template)
  applyRawHtmlToVisual()
}

function beautifyHtml(html) {
  const source = String(html || '').replace(/\r\n/g, '\n').trim()
  if (!source) return ''

  const tokens = source.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || []
  const voidTagRe = /^<\s*(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)\b/i
  const closeTagRe = /^<\s*\//
  const openTagRe = /^<\s*[a-zA-Z]/
  const selfCloseRe = /\/\s*>$/
  let depth = 0
  let inRawTag = ''

  const lines = []
  for (const tokenRaw of tokens) {
    const token = tokenRaw.trim()
    if (!token) continue

    if (inRawTag) {
      lines.push(`${'  '.repeat(depth)}${token}`)
      if (new RegExp(`^<\\s*\\/${inRawTag}\\s*>$`, 'i').test(token)) {
        depth = Math.max(depth - 1, 0)
        inRawTag = ''
      }
      continue
    }

    const isClose = closeTagRe.test(token)
    const isOpen = openTagRe.test(token)
    const isVoid = voidTagRe.test(token)
    const isSelfClose = selfCloseRe.test(token)
    const isComment = /^<!--/.test(token)

    if (isClose) depth = Math.max(depth - 1, 0)
    if (isOpen && !isClose && !isComment) {
      const prettyTag = formatTagToken(token, depth)
      if (prettyTag) {
        lines.push(...prettyTag)
      } else {
        lines.push(`${'  '.repeat(depth)}${token}`)
      }
    } else {
      lines.push(`${'  '.repeat(depth)}${token}`)
    }

    if (isComment) continue
    if (isOpen && !isClose && !isVoid && !isSelfClose && !token.includes('</')) {
      const rawTag = token.match(/^<\s*([a-zA-Z][\w:-]*)/)
      if (rawTag && /^(script|style|pre|textarea)$/i.test(rawTag[1])) {
        inRawTag = rawTag[1]
      }
      depth += 1
    }
  }

  return lines.join('\n')
}

function formatTagToken(token, depth) {
  const match = token.match(/^<\s*([a-zA-Z][\w:-]*)([\s\S]*?)(\/?)>$/)
  if (!match) return null
  const [, tagName, attrsRaw = '', selfSlash = ''] = match
  const attrs = parseTagAttributes(attrsRaw)
  if (!attrs.length) return null
  const shouldWrap = token.length > 96 || attrs.length >= 3
  if (!shouldWrap) return null

  const baseIndent = '  '.repeat(depth)
  const attrIndent = '  '.repeat(depth + 1)
  const wrapped = [`${baseIndent}<${tagName}`]
  for (const attr of attrs) {
    wrapped.push(`${attrIndent}${attr}`)
  }
  wrapped.push(`${baseIndent}${selfSlash ? '/>' : '>'}`)
  return wrapped
}

function parseTagAttributes(attrsRaw) {
  const cleaned = String(attrsRaw || '').trim()
  if (!cleaned) return []
  const attrRe = /([\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)/g
  const attrs = []
  let match
  while ((match = attrRe.exec(cleaned)) !== null) {
    const text = (match[1] || '').trim()
    if (text) attrs.push(text)
  }
  return attrs
}

function buildHighlightedHtml(html) {
  const input = String(html || '')
  if (!input) return '<span class="tpl-code-token-text"></span>'
  const tokens = input.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || []
  return tokens.map((token) => {
    if (token.startsWith('<!--')) {
      return `<span class="tpl-code-token-comment">${escapeCodeToken(token)}</span>`
    }
    if (!token.startsWith('<')) {
      return colorizeTextToken(token)
    }
    return colorizeTagToken(token)
  }).join('')
}

function colorizeTextToken(token) {
  const parts = String(token).split(/(\{[^{}\n]+\})/g)
  return parts.map((part) => {
    if (!part) return ''
    if (!part.startsWith('{') || !part.endsWith('}')) {
      return `<span class="tpl-code-token-text">${escapeCodeToken(part)}</span>`
    }

    const rawKey = part.slice(1, -1).trim()
    const componentKey = normalizeComponentPlaceholderKey(rawKey)
    if (componentKey) {
      const ctrlHint = isComponentHtmlEditable(componentKey) ? ' Ctrl+点击编辑HTML' : ''
      return `<span class="tpl-code-token-component" data-component-key="${escapeCodeToken(componentKey)}" style="pointer-events:auto" title="${escapeCodeToken(componentKey)}${ctrlHint}">${escapeCodeToken(part)}</span>`
    }

    return `<span class="tpl-code-token-variable">${escapeCodeToken(part)}</span>`
  }).join('')
}

function closeComponentDocPanel() {
  componentDocPinned.value = false
  componentDocPanel.open = false
}

function focusComponentDocEditor() {
  nextTick(() => {
    componentDocEditorRef.value?.focus()
  })
}

function syncComponentDocEditorScroll(event) {
  const overlay = componentDocEditorOverlayRef.value
  if (!overlay) return
  overlay.scrollTop = event.target.scrollTop
  overlay.scrollLeft = event.target.scrollLeft
}

function findComponentKeyAtCursor(text, cursorPos) {
  const source = String(text || '')
  const pos = Number.isFinite(cursorPos) ? cursorPos : -1
  if (pos < 0) return ''
  const tokenRe = /\{[^{}\n]+\}/g
  let match
  while ((match = tokenRe.exec(source)) !== null) {
    const start = match.index
    const end = start + match[0].length
    if (pos >= start && pos <= end) {
      const rawKey = match[0].slice(1, -1).trim()
      return normalizeComponentPlaceholderKey(rawKey)
    }
  }
  return ''
}

function enterComponentEditMode(componentKey, which) {
  if (!isComponentHtmlEditable(componentKey)) return
  componentDocPinned.value = false
  componentDocPanel.open = false
  componentEditContext.active = true
  componentEditContext.key = componentKey
  componentEditContext.originalHtml = String(form.html_template || '')
  form.html_template = componentPreviewMap.value[componentKey] || ''
  applyRawHtmlToVisual()
  nextTick(() => focusRawHtmlEditor(which))
}

function applyComponentEditToTemplate() {
  const key = componentEditContext.key
  if (!componentEditContext.active || !key) return
  const draft = String(form.html_template || '').trim()
  const tokens = getComponentPlaceholderTokens(key)
  let nextHtml = String(componentEditContext.originalHtml || '')
  for (const token of tokens) {
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = new RegExp(`\\{${escaped}\\}`, 'g')
    nextHtml = nextHtml.replace(re, draft)
  }
  componentEditContext.active = false
  componentEditContext.key = ''
  componentEditContext.originalHtml = ''
  form.html_template = nextHtml
  applyRawHtmlToVisual()
}

function cancelComponentEdit() {
  if (!componentEditContext.active) return
  form.html_template = componentEditContext.originalHtml || ''
  componentEditContext.active = false
  componentEditContext.key = ''
  componentEditContext.originalHtml = ''
  applyRawHtmlToVisual()
}

function onCodeWrapClick(event, which) {
  if (event.ctrlKey) {
    const span = event.target.closest?.('[data-component-key]')
    if (span?.dataset.componentKey) {
      event.preventDefault()
      event.stopPropagation()
      enterComponentEditMode(span.dataset.componentKey, which)
      return
    }

    const textarea = event.target?.closest?.('textarea.tpl-html-raw-view')
    if (textarea) {
      const keyAtCursor = findComponentKeyAtCursor(textarea.value, textarea.selectionStart)
      if (keyAtCursor) {
        event.preventDefault()
        event.stopPropagation()
        enterComponentEditMode(keyAtCursor, which)
        return
      }
    }
  }
  focusRawHtmlEditor(which)
}

function normalizeComponentPlaceholderKey(rawKey) {
  const aliases = {
    '业务数据块': '业务数据块',
    '统计网格': '统计网格',
    '文件树': '文件树',
    '差异对比': '差异对比',
    '执行日志': '执行日志',
    'payload_sections': '业务数据块',
    'stats_grid_section': '统计网格',
    'file_tree_section': '文件树',
    'diff_section': '差异对比',
    'task_log_section': '执行日志',
  }
  return aliases[rawKey] || ''
}

function colorizeTagToken(token) {
  const tagMatch = token.match(/^<(\/)?\s*([\w:-]+)([\s\S]*?)(\/?)>$/)
  if (!tagMatch) return `<span class="tpl-code-token-bracket">${escapeCodeToken(token)}</span>`

  const [, closeSlash = '', tagName = '', attrsRaw = '', selfSlash = ''] = tagMatch
  let attrsColored = ''
  let cursor = 0
  const attrRe = /([\w:-]+)(\s*=\s*)("[^"]*"|'[^']*'|[^\s"'=<>`]+)/g
  let match
  while ((match = attrRe.exec(attrsRaw)) !== null) {
    attrsColored += escapeCodeToken(attrsRaw.slice(cursor, match.index))
    attrsColored += `<span class="tpl-code-token-attr">${escapeCodeToken(match[1])}</span>`
    attrsColored += `<span class="tpl-code-token-operator">${escapeCodeToken(match[2])}</span>`
    attrsColored += `<span class="tpl-code-token-value">${escapeCodeToken(match[3])}</span>`
    cursor = match.index + match[0].length
  }
  attrsColored += escapeCodeToken(attrsRaw.slice(cursor))

  return [
    `<span class="tpl-code-token-bracket">&lt;${closeSlash || ''}</span>`,
    `<span class="tpl-code-token-tag">${escapeCodeToken(tagName)}</span>`,
    attrsColored,
    `<span class="tpl-code-token-bracket">${selfSlash || ''}&gt;</span>`
  ].join('')
}

function escapeCodeToken(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
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
.tpl-rte-wrap--split {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(340px, 1fr);
  gap: 12px;
}
.tpl-html-pane {
  min-height: 0;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.tpl-html-pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.08);
  background: rgba(248, 250, 252, 0.88);
}
.tpl-html-pane-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.6);
}
.tpl-html-pane-hint {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.45);
}
.tpl-html-pane-head-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tpl-html-sync-speed {
  display: inline-flex;
  align-items: center;
  background: rgba(15, 23, 42, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.34);
  border-radius: 7px;
  padding: 1px;
}
.tpl-html-sync-btn {
  min-width: 24px;
  height: 20px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: rgba(241, 245, 249, 0.7);
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
}
.tpl-html-sync-btn.is-active {
  background: rgba(59, 130, 246, 0.25);
  color: #e0f2fe;
}
.tpl-html-pane-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid rgba(29, 29, 31, 0.16);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.9);
  color: rgba(29, 29, 31, 0.7);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tpl-html-pane-btn:hover {
  transform: translateY(-1px) scale(1.02);
  border-color: rgba(0, 113, 227, 0.45);
  color: #0071e3;
}
.tpl-html-pane-btn:active {
  transform: scale(0.96);
}
.tpl-html-pane-btn--primary {
  border-color: rgba(37, 99, 235, 0.45);
  color: #1d4ed8;
}
.tpl-html-pane-body {
  flex: 1;
  min-height: 0;
}
.tpl-html-code-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.tpl-html-code-wrap:not(.is-editing) { cursor: text; }
.tpl-html-code-overlay,
.tpl-html-raw-view {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
  font-size: 12.5px !important;
  line-height: 1.62 !important;
  white-space: pre;
  word-break: normal;
  tab-size: 2;
}
.tpl-html-code-overlay {
  position: absolute;
  inset: 0;
  margin: 0;
  padding: 12px;
  overflow: auto;
  pointer-events: none;
  color: #e2e8f0;
  z-index: 2;
}
.tpl-html-pane--visual .tpl-html-pane-body {
  display: flex;
  min-height: 0;
}
.tpl-html-pane-body--preview {
  padding: 0;
  overflow: hidden;
}
.tpl-html-preview-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #fff;
  display: block;
}
.tpl-html-pane--raw {
  background: #14161a;
  border-color: rgba(15, 23, 42, 0.32);
}
.tpl-html-pane--raw .tpl-html-pane-head {
  background: rgba(255, 255, 255, 0.04);
  border-bottom-color: rgba(255, 255, 255, 0.12);
}
.tpl-html-pane--raw .tpl-html-pane-title {
  color: rgba(241, 245, 249, 0.88);
}
.tpl-html-pane--raw .tpl-html-pane-hint {
  color: rgba(203, 213, 225, 0.72);
}
.tpl-html-raw-view {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  min-height: 420px;
  resize: none;
  padding: 12px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: transparent;
  caret-color: #93c5fd;
  overflow: auto;
  z-index: 1;
}
.tpl-html-code-wrap.is-editing .tpl-html-raw-view {
  z-index: 3;
}
.tpl-html-raw-view:focus {
  box-shadow: none;
}
.tpl-html-raw-view::selection {
  background: rgba(59, 130, 246, 0.32);
}
.tpl-html-raw-view::-webkit-scrollbar,
.tpl-html-code-overlay::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.tpl-html-raw-view::-webkit-scrollbar-thumb,
.tpl-html-code-overlay::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.45);
  border-radius: 999px;
}
.tpl-html-raw-view::-webkit-scrollbar-track,
.tpl-html-code-overlay::-webkit-scrollbar-track {
  background: rgba(15, 23, 42, 0.2);
}

:deep(.tpl-code-token-text) { color: #d4d4d4; }
:deep(.tpl-code-token-comment) { color: #6a9955; font-style: italic; }
:deep(.tpl-code-token-bracket) { color: #808080; }
:deep(.tpl-code-token-tag) { color: #4ec9b0; }
:deep(.tpl-code-token-attr) { color: #9cdcfe; }
:deep(.tpl-code-token-operator) { color: #d4d4d4; }
:deep(.tpl-code-token-value) { color: #ce9178; }
:deep(.tpl-code-token-variable) { color: #dcdcaa; }
:deep(.tpl-code-token-component) {
  color: #c586c0;
  background: rgba(197, 134, 192, 0.14);
  border-radius: 6px;
  padding: 0 2px;
  cursor: pointer;
}
:deep(.tpl-code-token-component:hover) {
  background: rgba(197, 134, 192, 0.26);
}

/* === 组件文档浮层（JetBrains Quick Doc 风格） === */
.tpl-component-doc-panel {
  position: fixed;
  z-index: 99999;
  width: 680px;
  max-width: calc(100vw - 32px);
  border-radius: 10px;
  background: #1e2330;
  border: 1px solid rgba(148, 163, 184, 0.22);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5), 0 2px 8px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  pointer-events: auto;
}
.tpl-component-doc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}
.tpl-component-doc-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #64748b;
  font-family: system-ui, sans-serif;
}
.tpl-component-doc-key {
  font-size: 13px;
  font-weight: 600;
  color: #c586c0;
  flex: 1;
  font-family: system-ui, sans-serif;
}
.tpl-component-doc-close {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
}
.tpl-component-doc-close:hover {
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.08);
}
.tpl-component-doc-body {
  padding: 10px 14px 12px;
}
.tpl-component-doc-edit-wrap {
  position: relative;
  width: 100%;
  min-height: 180px;
  max-height: 260px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(0, 0, 0, 0.24);
  overflow: hidden;
}
.tpl-component-doc-editor-overlay,
.tpl-component-doc-editor-input {
  position: absolute;
  inset: 0;
  margin: 0;
  width: 100%;
  height: 100%;
  padding: 10px 12px;
  overflow: auto;
  white-space: pre;
  tab-size: 2;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.6;
}
.tpl-component-doc-editor-overlay {
  pointer-events: none;
  color: #cbd5e1;
  z-index: 1;
}
.tpl-component-doc-editor-input {
  resize: none;
  border: 0;
  background: transparent;
  color: transparent;
  caret-color: #93c5fd;
  z-index: 2;
  outline: none;
}
.tpl-component-doc-editor-input::-webkit-scrollbar,
.tpl-component-doc-editor-overlay::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.tpl-component-doc-editor-input::-webkit-scrollbar-thumb,
.tpl-component-doc-editor-overlay::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.28);
  border-radius: 999px;
}
.tpl-component-doc-editor-input::-webkit-scrollbar-track,
.tpl-component-doc-editor-overlay::-webkit-scrollbar-track {
  background: rgba(15, 23, 42, 0.14);
}
.tpl-component-doc-edit-wrap:focus-within {
  border-color: rgba(59, 130, 246, 0.55);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.16);
}
.tpl-component-doc-editor-actions {
  margin: 8px 0 10px;
  display: flex;
  justify-content: flex-end;
}
.tpl-component-edit-tag {
  font-size: 11px;
  font-weight: 600;
  color: #60a5fa;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.24);
}
.tpl-component-doc-section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: #475569;
  margin-bottom: 8px;
  font-family: system-ui, sans-serif;
}
.tpl-component-doc-code {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: #94a3b8;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 6px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
}
.tpl-component-doc-code::-webkit-scrollbar {
  width: 8px;
}
.tpl-component-doc-code::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.35);
  border-radius: 999px;
}
.tpl-component-doc-code::-webkit-scrollbar-track {
  background: rgba(15, 23, 42, 0.2);
}
/* 面板内代码语法高亮 token 颜色（与主编辑区保持一致） */
:deep(.tpl-component-doc-code .tpl-code-token-text) { color: #d4d4d4; }
:deep(.tpl-component-doc-code .tpl-code-token-comment) { color: #6a9955; font-style: italic; }
:deep(.tpl-component-doc-code .tpl-code-token-bracket) { color: #808080; }
:deep(.tpl-component-doc-code .tpl-code-token-tag) { color: #4ec9b0; }
:deep(.tpl-component-doc-code .tpl-code-token-attr) { color: #9cdcfe; }
:deep(.tpl-component-doc-code .tpl-code-token-operator) { color: #d4d4d4; }
:deep(.tpl-component-doc-code .tpl-code-token-value) { color: #ce9178; }
:deep(.tpl-component-doc-code .tpl-code-token-variable) { color: #dcdcaa; }
:deep(.tpl-component-doc-code .tpl-code-token-component) { color: #c586c0; }
.tpl-doc-fade-enter-active,
.tpl-doc-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.tpl-doc-fade-enter-from,
.tpl-doc-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.tpl-html-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 99996;
  background: rgba(15, 17, 21, 0.72);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.tpl-html-modal-panel {
  width: min(1300px, 100%);
  height: calc(100vh - 48px);
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #101317;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.42);
}
.tpl-html-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.03);
}
.tpl-html-modal-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}
.tpl-html-modal-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.tpl-html-modal-body {
  flex: 1;
  min-height: 0;
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

  .tpl-rte-wrap--split {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(240px, 1fr);
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
// 组件占位符显示名 → 积木块 type 的映射（业务数据块是聚合，无单一类型）
const COMPONENT_KEY_TO_BLOCK_TYPE = {
  '统计网格': 'stats_grid',
  '文件树': 'file_tree',
  '差异对比': 'diff_view',
  '执行日志': 'task_log',
}

function jumpToBlockByComponentKey(componentKey) {
  const blockType = COMPONENT_KEY_TO_BLOCK_TYPE[componentKey]
  if (!blockType) return
  if (form.editor_mode !== 'blocks') {
    setEditorMode('blocks')
  }
  nextTick(() => {
    blockEditorRef.value?.selectBlockByType(blockType)
  })
}

function onCodeWrapClick(event, which) {
  if (event.ctrlKey) {
    const span = event.target.closest?.('[data-component-key]')
    if (span?.dataset.componentKey) {
      event.preventDefault()
      event.stopPropagation()
      jumpToBlockByComponentKey(span.dataset.componentKey)
      return
    }
  }
  focusRawHtmlEditor(which)
}

function normalizeComponentPlaceholderKey(rawKey) {
  const aliases = {
    '业务数据块': '业务数据块',
    '统计网格': '统计网格',
    '文件树': '文件树',
    '差异对比': '差异对比',
    '执行日志': '执行日志',
    'payload_sections': '业务数据块',
    'stats_grid_section': '统计网格',
    'file_tree_section': '文件树',
    'diff_section': '差异对比',
    'task_log_section': '执行日志',
  }
  return aliases[rawKey] || ''
}
