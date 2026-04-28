<template>
  <div class="rte-wrap" :class="[`rte-wrap--${size}`, { 'rte-wrap--focused': isFocused }]">
    <div class="rte-toolbar">
      <!-- 标题级别 -->
      <button
        v-if="size === 'large'"
        type="button"
        class="rte-tb-btn rte-tb-btn--text"
        :class="{ 'is-active': editor?.isActive('heading', { level: 1 }) }"
        title="一级标题"
        @mousedown.prevent="editor?.chain().focus().toggleHeading({ level: 1 }).run()"
      >H1</button>
      <button
        v-if="size === 'large'"
        type="button"
        class="rte-tb-btn rte-tb-btn--text"
        :class="{ 'is-active': editor?.isActive('heading', { level: 2 }) }"
        title="二级标题"
        @mousedown.prevent="editor?.chain().focus().toggleHeading({ level: 2 }).run()"
      >H2</button>
      <button
        v-if="size === 'large'"
        type="button"
        class="rte-tb-btn rte-tb-btn--text"
        :class="{ 'is-active': editor?.isActive('heading', { level: 3 }) }"
        title="三级标题"
        @mousedown.prevent="editor?.chain().focus().toggleHeading({ level: 3 }).run()"
      >H3</button>
      <div v-if="size === 'large'" class="rte-tb-sep" />

      <!-- 文本格式 -->
      <button
        v-for="btn in toolbarBtns"
        :key="btn.cmd"
        type="button"
        class="rte-tb-btn"
        :class="{ 'is-active': btn.active?.() }"
        :title="btn.title"
        @mousedown.prevent="btn.action()"
      >
        <component :is="btn.icon" :size="13" :stroke-width="2.4" />
      </button>

      <!-- 大号才显示的扩展按钮 -->
      <template v-if="size === 'large'">
        <div class="rte-tb-sep" />
        <button
          type="button"
          class="rte-tb-btn"
          :class="{ 'is-active': editor?.isActive('blockquote') }"
          title="引用"
          @mousedown.prevent="editor?.chain().focus().toggleBlockquote().run()"
        ><Quote :size="13" :stroke-width="2.4" /></button>
        <button
          type="button"
          class="rte-tb-btn"
          :class="{ 'is-active': editor?.isActive('codeBlock') }"
          title="代码块"
          @mousedown.prevent="editor?.chain().focus().toggleCodeBlock().run()"
        ><Code :size="13" :stroke-width="2.4" /></button>
        <button
          type="button"
          class="rte-tb-btn"
          title="水平分割线"
          @mousedown.prevent="editor?.chain().focus().setHorizontalRule().run()"
        ><Minus :size="13" :stroke-width="2.4" /></button>
        <button
          type="button"
          class="rte-tb-btn"
          title="撤销"
          :disabled="!editor?.can().undo()"
          @mousedown.prevent="editor?.chain().focus().undo().run()"
        ><Undo2 :size="13" :stroke-width="2.4" /></button>
        <button
          type="button"
          class="rte-tb-btn"
          title="重做"
          :disabled="!editor?.can().redo()"
          @mousedown.prevent="editor?.chain().focus().redo().run()"
        ><Redo2 :size="13" :stroke-width="2.4" /></button>
      </template>

      <div class="rte-tb-sep" />
      <span class="rte-tb-var-label">变量</span>
      <button
        v-for="v in VARIABLES"
        :key="v.key"
        type="button"
        class="rte-var-pill rte-var-pill--btn"
        :title="`点击插入：${v.key} — 例如：${v.example}`"
        @mousedown.prevent="insertVariable(v.key)"
      >
        <Hash :size="10" :stroke-width="2.6" class="rte-var-pill-icon" />
        <span>{{ v.key }}</span>
      </button>
    </div>
    <SlashMenu
      v-if="slashMenu.open && filteredSlashCommands.length"
      :items="filteredSlashCommands"
      :x="slashMenu.x"
      :y="slashMenu.y"
      :active-index="slashMenu.activeIndex"
      @active="slashMenu.activeIndex = $event"
      @select="runSlashCommand"
    />
    <editor-content class="rte-body" :editor="editor" @focus="isFocused = true" @blur="isFocused = false" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableHeader } from '@tiptap/extension-table-header'
import { TableCell } from '@tiptap/extension-table-cell'
import { Bold, Code, Hash, Heading1, Heading2, Heading3, Italic, Link2, Link2Off, List, ListOrdered, Minus, Quote, Redo2, Table2, Strikethrough, Undo2 } from 'lucide-vue-next'
import { VARIABLES } from './blockTypes.js'
import { EmailImage } from './emailImageExtension.js'
import { PreserveEmailAttributes } from './preserveEmailAttributes.js'
import SlashMenu from './SlashMenu.vue'

const props = defineProps({
  modelValue: { type: [Object, String], default: null },  // Tiptap JSON doc 或 HTML 字符串
  htmlCache:  { type: String,  default: '' },
  /** 'normal'（默认，内嵌富文本块用）| 'large'（HTML 模式整页用） */
  size:       { type: String,  default: 'normal' },
})
const emit = defineEmits(['update:modelValue', 'update:htmlCache'])

const isFocused = ref(false)
const slashMenu = reactive({
  open: false,
  x: 12,
  y: 48,
  activeIndex: 0,
  from: 0,
  query: '',
})

// 初始内容：modelValue 优先 JSON，无则用 htmlCache 作为 HTML 字符串
const initialContent = props.modelValue || props.htmlCache || ''

// 大号模式额外加载 table 扩展，能保留邮件 HTML 中的 <table> 布局
const largeModeExtensions = props.size === 'large'
  ? [
      Table.configure({ resizable: false, HTMLAttributes: { class: 'rte-table' } }),
      TableRow,
      TableHeader,
      TableCell,
    ]
  : []

const editor = useEditor({
  content: initialContent,
  extensions: [
    PreserveEmailAttributes,
    EmailImage,
    StarterKit.configure({
      link: false,
      codeBlock: props.size === 'large' ? {} : false,
    }),
    Link.configure({
      openOnClick:  false,
      autolink:     true,
      linkOnPaste:  true,
      protocols:    ['mailto', 'tel'],
    }),
    ...largeModeExtensions,
  ],
  editorProps: {
    handleKeyDown(view, event) {
      if (event.key === '/') {
        window.setTimeout(() => openSlashMenu(view), 0)
        return false
      }
      if (!slashMenu.open) return false
      if (event.key === 'Escape') {
        closeSlashMenu()
        return true
      }
      if (event.key === 'ArrowDown') {
        if (!filteredSlashCommands.value.length) return true
        slashMenu.activeIndex = (slashMenu.activeIndex + 1) % filteredSlashCommands.value.length
        return true
      }
      if (event.key === 'ArrowUp') {
        if (!filteredSlashCommands.value.length) return true
        slashMenu.activeIndex = (slashMenu.activeIndex - 1 + filteredSlashCommands.value.length) % filteredSlashCommands.value.length
        return true
      }
      if (event.key === 'Enter') {
        const item = filteredSlashCommands.value[slashMenu.activeIndex]
        if (item) runSlashCommand(item)
        return true
      }
      window.setTimeout(() => refreshSlashQuery(view), 0)
      return false
    },
  },
  onUpdate({ editor }) {
    emit('update:modelValue', editor.getJSON())
    emit('update:htmlCache',  editor.getHTML())
  },
})

// 注意：父组件在切换块时通过 :key="block.id" 强制重建 Inspector，
// RichTextEditor 也会随之重新挂载并用新的 modelValue 初始化。
// 因此编辑期间不需要再 watch props.modelValue，避免 onUpdate emit 后
// 外部回写引发的 setContent 抖动 / 光标跳动。

onBeforeUnmount(() => editor.value?.destroy())

function insertVariable(key) {
  if (props.size === 'large') {
    editor.value?.commands.insertContent(`{${key}}`)
    return
  }
  // 以 pill 形式插入：data-var 标记变量 key，正文显示中文 label
  // 后端 sanitize 后会把 <span data-var="..."> 整个还原为 {key} 再做替换
  // 末尾 \u200B 零宽空格 = 让光标可以从 pill 后面跳出来
  const safeKey = String(key).replace(/"/g, '&quot;')
  const html = `<span class="rte-var-pill" data-var="${safeKey}">${safeKey}</span>\u200B`
  editor.value?.commands.insertContent(html)
}

function commandChain() {
  const instance = editor.value
  if (!instance) return null
  return instance.chain().focus().deleteRange({ from: slashMenu.from, to: instance.state.selection.from })
}

const slashCommands = computed(() => {
  const base = [
    { key: 'h1', label: '一级标题', hint: '大标题', icon: Heading1, action: () => commandChain()?.setHeading({ level: 1 }).run() },
    { key: 'h2', label: '二级标题', hint: '章节标题', icon: Heading2, action: () => commandChain()?.setHeading({ level: 2 }).run() },
    { key: 'h3', label: '三级标题', hint: '小标题', icon: Heading3, action: () => commandChain()?.setHeading({ level: 3 }).run() },
    { key: 'bullet', label: '项目列表', hint: '无序列表', icon: List, action: () => commandChain()?.toggleBulletList().run() },
    { key: 'ordered', label: '编号列表', hint: '有序列表', icon: ListOrdered, action: () => commandChain()?.toggleOrderedList().run() },
    { key: 'quote', label: '引用', hint: '强调一段说明', icon: Quote, action: () => commandChain()?.toggleBlockquote().run() },
    { key: 'code', label: '代码块', hint: '等宽日志 / 错误内容', icon: Code, action: () => commandChain()?.toggleCodeBlock().run() },
    { key: 'hr', label: '分割线', hint: '水平线', icon: Minus, action: () => commandChain()?.setHorizontalRule().run() },
  ]
  if (props.size === 'large') {
    base.push({
      key: 'table',
      label: '表格',
      hint: '插入 3 x 3 表格',
      icon: Table2,
      action: () => commandChain()?.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
    })
  }
  return [
    ...base,
    ...VARIABLES.map((v) => ({
      key: `var-${v.key}`,
      label: `变量：${v.key}`,
      hint: `插入 {${v.key}}`,
      icon: Hash,
      action: () => {
        commandChain()?.run()
        insertVariable(v.key)
      },
    })),
  ]
})

const filteredSlashCommands = computed(() => {
  const q = slashMenu.query.trim().toLowerCase()
  if (!q) return slashCommands.value
  return slashCommands.value.filter((item) => `${item.label} ${item.hint} ${item.key}`.toLowerCase().includes(q))
})

function openSlashMenu(view) {
  const instance = editor.value
  if (!instance) return
  const pos = instance.state.selection.from
  slashMenu.from = Math.max(1, pos - 1)
  slashMenu.query = ''
  slashMenu.activeIndex = 0
  positionSlashMenu(view, pos)
  slashMenu.open = true
}

function refreshSlashQuery(view) {
  const instance = editor.value
  if (!instance || !slashMenu.open) return
  const pos = instance.state.selection.from
  const query = instance.state.doc.textBetween(slashMenu.from + 1, pos, '\n', '\n')
  if (query.includes(' ') || query.includes('\n')) {
    closeSlashMenu()
    return
  }
  slashMenu.query = query
  slashMenu.activeIndex = Math.min(slashMenu.activeIndex, Math.max(0, filteredSlashCommands.value.length - 1))
  positionSlashMenu(view, pos)
}

function positionSlashMenu(view, pos) {
  const caret = getCaretRect(view, pos)
  const menuHeight = 320
  const menuWidth = 260
  const below = caret.bottom + 8
  const above = caret.top - menuHeight - 8
  slashMenu.x = Math.max(8, Math.min(caret.left, window.innerWidth - menuWidth - 8))
  slashMenu.y = below + menuHeight > window.innerHeight && above > 8 ? above : below
}

function getCaretRect(view, pos) {
  const selection = window.getSelection()
  if (selection?.rangeCount) {
    const range = selection.getRangeAt(0).cloneRange()
    range.collapse(false)
    const rect = range.getBoundingClientRect()
    if (rect && (rect.width || rect.height) && rect.top >= 0) return rect

    const marker = document.createElement('span')
    marker.textContent = '\u200b'
    marker.style.display = 'inline-block'
    marker.style.width = '1px'
    marker.style.height = '1em'
    range.insertNode(marker)
    const markerRect = marker.getBoundingClientRect()
    marker.parentNode?.removeChild(marker)
    view.focus()
    if (markerRect && markerRect.top >= 0) return markerRect
  }
  return view.coordsAtPos(pos)
}

function closeSlashMenu() {
  slashMenu.open = false
  slashMenu.query = ''
  slashMenu.activeIndex = 0
}

function runSlashCommand(item) {
  if (!item) return
  item.action()
  closeSlashMenu()
}

const toolbarBtns = [
  {
    cmd: 'bold', title: '粗体',
    icon: Bold,
    active: () => editor.value?.isActive('bold'),
    action: () => editor.value?.chain().focus().toggleBold().run(),
  },
  {
    cmd: 'italic', title: '斜体',
    icon: Italic,
    active: () => editor.value?.isActive('italic'),
    action: () => editor.value?.chain().focus().toggleItalic().run(),
  },
  {
    cmd: 'strike', title: '删除线',
    icon: Strikethrough,
    active: () => editor.value?.isActive('strike'),
    action: () => editor.value?.chain().focus().toggleStrike().run(),
  },
  {
    cmd: 'ul', title: '无序列表',
    icon: List,
    active: () => editor.value?.isActive('bulletList'),
    action: () => editor.value?.chain().focus().toggleBulletList().run(),
  },
  {
    cmd: 'ol', title: '有序列表',
    icon: ListOrdered,
    active: () => editor.value?.isActive('orderedList'),
    action: () => editor.value?.chain().focus().toggleOrderedList().run(),
  },
  {
    cmd: 'link', title: '插入链接',
    icon: Link2,
    active: () => editor.value?.isActive('link'),
    action: () => {
      const url = window.prompt('链接地址', 'https://')
      if (url) editor.value?.chain().focus().setLink({ href: url }).run()
    },
  },
  {
    cmd: 'unlink', title: '移除链接',
    icon: Link2Off,
    active: () => false,
    action: () => editor.value?.chain().focus().unsetLink().run(),
  },
]
</script>

<style scoped>
.rte-wrap {
  position: relative;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
  transition: border-color 0.2s, box-shadow 0.2s;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
/* 大号变体：占满父级高度，编辑区可伸缩，工具栏 sticky */
.rte-wrap--large {
  flex: 1;
  border-radius: 12px;
}
.rte-wrap--large .rte-toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 8px 12px;
}
.rte-wrap--large .rte-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  font-size: 14px;
  line-height: 1.7;
}
.rte-wrap--focused {
  border-color: rgba(0, 113, 227, 0.5);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.12);
}
.rte-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  padding: 6px 8px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.07);
  background: #fafafa;
}
.rte-tb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(29, 29, 31, 0.6);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.rte-tb-btn:hover, .rte-tb-btn.is-active {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}
.rte-tb-btn.is-active {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
}
.rte-tb-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.rte-tb-btn--text {
  width: auto;
  padding: 0 7px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.rte-tb-sep {
  width: 1px;
  height: 16px;
  background: rgba(29, 29, 31, 0.1);
  margin: 0 4px;
}
.rte-tb-var-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.4);
  padding: 0 2px;
}
/* BlockNote 风格变量 pill：深色底 + 蓝菱形图标 + 白字 */
.rte-var-pill,
.rte-var-pill--btn {
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
  line-height: 1.4;
  white-space: nowrap;
  vertical-align: baseline;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
}
.rte-var-pill--btn {
  cursor: pointer;
  transition: all 0.15s ease;
}
.rte-var-pill--btn:hover {
  background: #1d1d1f;
  border-color: #4a4d55;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.18);
}
.rte-var-pill--btn:active { transform: translateY(0); }
.rte-var-pill-icon {
  color: #6ea8fe;
  flex-shrink: 0;
}
.rte-body {
  min-height: 120px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: #1d1d1f;
  outline: none;
}
</style>

<style>
/* Tiptap 编辑器全局样式（非 scoped） */
.rte-body .tiptap {
  outline: none;
  min-height: 100px;
}
.rte-body .tiptap p { margin: 0 0 10px; }
.rte-body .tiptap p:last-child { margin-bottom: 0; }
.rte-body .tiptap ul,
.rte-body .tiptap ol { padding-left: 22px; margin: 6px 0 10px; }
.rte-body .tiptap ul li,
.rte-body .tiptap ol li { margin: 2px 0; }
.rte-body .tiptap a { color: #0071e3; text-decoration: underline; text-underline-offset: 2px; }
.rte-body .tiptap h1 { font-size: 22px; font-weight: 600; line-height: 1.35; margin: 18px 0 10px; letter-spacing: -0.01em; }
.rte-body .tiptap h2 { font-size: 18px; font-weight: 600; line-height: 1.4;  margin: 16px 0 8px; }
.rte-body .tiptap h3 { font-size: 15px; font-weight: 600; line-height: 1.4;  margin: 14px 0 6px; }
.rte-body .tiptap blockquote {
  border-left: 3px solid rgba(0, 113, 227, 0.4);
  padding: 4px 12px;
  margin: 8px 0;
  color: rgba(29, 29, 31, 0.7);
  background: rgba(0, 113, 227, 0.04);
  border-radius: 0 6px 6px 0;
}
.rte-body .tiptap code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.92em;
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(29, 29, 31, 0.07);
  padding: 1px 5px;
  border-radius: 4px;
  color: #1d1d1f;
}
.rte-body .tiptap pre {
  background: #1d1d1f;
  color: #f5f5f7;
  padding: 12px 14px;
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  margin: 10px 0;
  overflow-x: auto;
}
.rte-body .tiptap pre code {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
}
.rte-body .tiptap hr {
  border: none;
  border-top: 1px solid rgba(29, 29, 31, 0.1);
  margin: 18px 0;
}

/* 表格在编辑器内的视觉（提示用户这是 table） */
.rte-body .tiptap table {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
  table-layout: fixed;
  position: relative;
}
.rte-body .tiptap table td,
.rte-body .tiptap table th {
  border: 1px dashed rgba(0, 113, 227, 0.18);
  padding: 6px 8px;
  vertical-align: top;
  position: relative;
  background: transparent;
}
.rte-body .tiptap table th {
  background: rgba(0, 113, 227, 0.04);
  font-weight: 600;
}
/* 编辑时选中态 */
.rte-body .tiptap .selectedCell { background: rgba(0, 113, 227, 0.08) !important; }
/* 占位提示 */
.rte-body .tiptap p.is-editor-empty:first-child::before {
  content: attr(data-placeholder);
  color: rgba(29, 29, 31, 0.3);
  pointer-events: none;
  float: left;
  height: 0;
}

/* BlockNote 风格变量 pill —— 在富文本编辑区内的 inline 样式 */
.rte-body .tiptap .rte-var-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 9px 1px 7px;
  font-size: 12px;
  font-weight: 500;
  color: #f5f5f7;
  background: #2a2d34;
  border: 1px solid #3a3d45;
  border-radius: 99px;
  line-height: 1.5;
  vertical-align: baseline;
  white-space: nowrap;
  user-select: all;
  cursor: default;
  /* 模拟 hash 图标：用伪元素画蓝色菱形点 */
  position: relative;
}
.rte-body .tiptap .rte-var-pill::before {
  content: "";
  width: 6px;
  height: 6px;
  background: #6ea8fe;
  border-radius: 1px;
  transform: rotate(45deg);
  flex-shrink: 0;
  display: inline-block;
}
</style>
