<template>
  <div ref="readerRef" class="library-pdf-reader" :style="windowStyle">
    <PDFViewer :key="src" class="library-pdf-viewer" :config="config" @init="handleInit" @ready="handleReady" />
    <button
      type="button"
      class="library-pdf-close"
      :class="{ 'is-dark': resolvedTheme === 'dark' }"
      aria-label="关闭 PDF 窗口"
      title="关闭 PDF 窗口"
      @pointerdown.stop
      @click="emit('close')"
    >
      <X :size="18" :stroke-width="2" />
    </button>
    <span
      v-for="direction in resizeDirections"
      :key="direction"
      class="library-pdf-resize"
      :class="`library-pdf-resize-${direction}`"
      :data-direction="direction"
      aria-hidden="true"
      @pointerdown="startResize($event, direction)"
      @pointermove="moveResize"
      @pointerup="finishResize"
      @pointercancel="finishResize"
      @lostpointercapture="finishResize"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeMount, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { PDFViewer } from '@embedpdf/vue-pdf-viewer'
import { X } from 'lucide-vue-next'
import { FontCharset } from '@embedpdf/models'
import wasmUrl from '@embedpdf/pdfium/pdfium.wasm?url'
import { useTheme } from '../../composables/useTheme'

const props = defineProps({ src: { type: String, required: true }, title: { type: String, default: 'PDF' } })
const emit = defineEmits(['close'])
const { resolvedTheme } = useTheme()
let container = null
let documentManager = null
let ui = null
let unsubscribeClosed = null
let disposed = false
let previousFocus = null
const readerRef = ref(null)
const windowRect = ref(null)
const resizeDirections = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
const windowStyle = computed(() => windowRect.value ? {
  top: `${windowRect.value.top}px`, left: `${windowRect.value.left}px`,
  width: `${windowRect.value.width}px`, height: `${windowRect.value.height}px`, transform: 'none',
} : {})
let resizeState = null
let resizeFrame = 0
let pendingRect = null
const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
function startDrag (event) {
  if (event.button !== 0 || !event.isPrimary || document.fullscreenElement) return
  const path = event.composedPath()
  const tabBar = container.shadowRoot.querySelector('[role="tab"]')?.parentElement?.parentElement
  if (!tabBar || !path.includes(tabBar)) return
  if (path.some(node => node instanceof Element && node.matches('button, input, select, textarea, a, [role="button"]'))) return
  event.preventDefault()
  event.stopPropagation()
  resizeState = { direction: 'move', x: event.clientX, y: event.clientY, rect: readerRef.value.getBoundingClientRect(), pointerId: event.pointerId, target: container }
  container.setPointerCapture(event.pointerId)
}
function startResize (event, direction) {
  if (event.button !== 0 || !event.isPrimary) return
  event.preventDefault()
  event.stopPropagation()
  const rect = readerRef.value.getBoundingClientRect()
  resizeState = { direction, x: event.clientX, y: event.clientY, rect, pointerId: event.pointerId, target: event.currentTarget }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function moveResize (event) {
  if (!resizeState || event.pointerId !== resizeState.pointerId) return
  const { direction, x, y, rect } = resizeState
  const dx = event.clientX - x
  const dy = event.clientY - y
  const maxWidth = Math.max(1, window.innerWidth - 24)
  const maxHeight = Math.max(1, window.innerHeight - 24)
  const minWidth = Math.min(480, maxWidth)
  const minHeight = Math.min(320, maxHeight)
  let { left, right, top, bottom } = rect
  if (direction === 'move') {
    left = clamp(rect.left + dx, 12, window.innerWidth - rect.width - 12)
    top = clamp(rect.top + dy, 12, window.innerHeight - rect.height - 12)
    right = left + rect.width
    bottom = top + rect.height
  } else {
    if (direction.includes('w')) left = clamp(rect.left + dx, 12, right - minWidth)
    if (direction.includes('e')) right = clamp(rect.right + dx, left + minWidth, window.innerWidth - 12)
    if (direction.includes('n')) top = clamp(rect.top + dy, 12, bottom - minHeight)
    if (direction.includes('s')) bottom = clamp(rect.bottom + dy, top + minHeight, window.innerHeight - 12)
  }
  pendingRect = { left, top, width: right - left, height: bottom - top }
  // 合并同一帧内的指针事件，避免重复触发 PDF 视口重排。
  if (!resizeFrame) resizeFrame = requestAnimationFrame(applyResize)
}
function applyResize () {
  resizeFrame = 0
  if (pendingRect) windowRect.value = pendingRect
  pendingRect = null
}
function finishResize () {
  if (resizeFrame) cancelAnimationFrame(resizeFrame)
  applyResize()
  const state = resizeState
  resizeState = null
  if (state?.target.hasPointerCapture(state.pointerId)) state.target.releasePointerCapture(state.pointerId)
}
function fitViewport () {
  finishResize()
  if (!windowRect.value) return
  const rect = windowRect.value
  const width = Math.min(rect.width, Math.max(1, window.innerWidth - 24))
  const height = Math.min(rect.height, Math.max(1, window.innerHeight - 24))
  windowRect.value = { width, height, left: clamp(rect.left, 12, window.innerWidth - width - 12), top: clamp(rect.top, 12, window.innerHeight - height - 12) }
}
// 字体按 PDF 实际需要加载；资源由 Vite 生成带 hash 的本地地址。
const latin = new URL('../../../node_modules/@embedpdf/fonts-latin/fonts/NotoSans-Regular.ttf', import.meta.url).href
const japanese = new URL('../../../node_modules/@embedpdf/fonts-jp/fonts/NotoSansJP-Regular.otf', import.meta.url).href
const simplified = new URL('../../../node_modules/@embedpdf/fonts-sc/fonts/NotoSansHans-Regular.otf', import.meta.url).href
const traditional = new URL('../../../node_modules/@embedpdf/fonts-tc/fonts/NotoSansHant-Regular.otf', import.meta.url).href
const config = computed(() => ({
  // 引擎运行在 Blob Worker 中，资源和文档都必须传绝对地址。
  wasmUrl: new URL(wasmUrl, window.location.href).href,
  worker: true,
  documentManager: { initialDocuments: [{ url: new URL(props.src, window.location.href).href, name: props.title, requestOptions: { credentials: 'include' } }] },
  theme: { preference: resolvedTheme.value },
  tabBar: 'always',
  i18n: { defaultLocale: 'zh-CN' },
  disabledCategories: ['annotation', 'redaction'],
  stamp: { manifests: [], defaultLibrary: false },
  fonts: { ui: { family: '"Segoe UI", "Microsoft YaHei", sans-serif', stylesheetUrl: null }, signature: null },
  fontFallback: {
    fonts: { [FontCharset.ANSI]: latin, [FontCharset.SHIFTJIS]: japanese, [FontCharset.GB2312]: simplified, [FontCharset.CHINESEBIG5]: traditional },
    defaultFont: latin,
  },
}))
function handleInit (viewer) {
  container = viewer
  viewer.shadowRoot.addEventListener('pointerdown', startDrag, true)
  viewer.addEventListener('pointermove', moveResize)
  viewer.addEventListener('pointerup', finishResize)
  viewer.addEventListener('pointercancel', finishResize)
  viewer.addEventListener('lostpointercapture', finishResize)
  viewer.tabIndex = -1
  viewer.focus({ preventScroll: true })
  // 阅读器使用 Shadow DOM，在组件内部应用项目的交互规范。
  const style = document.createElement('style')
  style.textContent = `
    :is(button, input, textarea, select, [tabindex]):is(:focus, :focus-visible) { outline: none !important; box-shadow: none !important; }
    button { transition: all .3s cubic-bezier(.34, 1.56, .64, 1) !important; }
    button:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); }
    button:active:not(:disabled) { transform: scale(.96); }
    button:hover:not(:disabled) svg { rotate: 4deg; }
    [role="tab"], div:has(> [role="tab"]), div:has(> div > [role="tab"]) { cursor: grab; touch-action: none; user-select: none; }
    [role="tab"]:active, div:has(> [role="tab"]):active, div:has(> div > [role="tab"]):active { cursor: grabbing; }
    div:has(> div > [role="tab"]) { padding-right: 52px; }
  `
  viewer.shadowRoot.appendChild(style)
}
function handleReady (registry) {
  if (disposed) return
  documentManager = registry.getPlugin('document-manager').provides()
  ui = registry.getPlugin('ui').provides()
  unsubscribeClosed = documentManager.onDocumentClosed(() => {
    if (documentManager.getDocumentCount() === 0) emit('close')
  })
}
function handleKeydown (event) {
  if (event.key !== 'Escape') return
  event.preventDefault()
  event.stopImmediatePropagation()
  const documentId = documentManager?.getActiveDocumentId()
  const scope = documentId ? ui?.forDocument(documentId) : null
  // Escape 先关闭阅读器自己的对话框和菜单，再退出阅读界面。
  if (scope?.isModalOpen()) {
    scope.closeModal()
  } else if (scope?.getOpenMenus().length) {
    scope.closeAllMenus()
  } else if (document.fullscreenElement) {
    document.exitFullscreen()
  } else {
    emit('close')
  }
}
onBeforeMount(() => {
  previousFocus = document.activeElement
})
onMounted(() => {
  document.addEventListener('keydown', handleKeydown, true)
  window.addEventListener('resize', fitViewport)
})
onBeforeUnmount(() => {
  disposed = true
  unsubscribeClosed?.()
  document.removeEventListener('keydown', handleKeydown, true)
  window.removeEventListener('resize', fitViewport)
  finishResize()
  container?.shadowRoot.removeEventListener('pointerdown', startDrag, true)
  container?.removeEventListener('pointermove', moveResize)
  container?.removeEventListener('pointerup', finishResize)
  container?.removeEventListener('pointercancel', finishResize)
  container?.removeEventListener('lostpointercapture', finishResize)
  if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
})
watch(resolvedTheme, value => container?.setTheme(value))
</script>

<style scoped>
.library-pdf-reader {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 2450;
  width: min(1120px, calc(100vw - 64px));
  height: min(820px, calc(100dvh - 80px));
  min-width: 0;
  min-height: 0;
  border-radius: 12px;
  box-shadow: 0 20px 70px rgb(0 0 0 / 28%);
  transform: translate(-50%, -50%);
  user-select: text;
}
.library-pdf-viewer { width: 100%; height: 100%; overflow: hidden; border-radius: inherit; }
.library-pdf-close {
  position: absolute; top: 7px; right: 10px; z-index: 2;
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px;
  background: transparent; color: #475569; cursor: pointer;
  transition: all .3s cubic-bezier(.34, 1.56, .64, 1);
}
.library-pdf-close.is-dark { color: #e2e8f0; }
.library-pdf-close:hover { background: rgb(100 116 139 / 16%); transform: translateY(-2px) scale(1.02); }
.library-pdf-close:active { transform: scale(.96); }
.library-pdf-close svg { transition: rotate .3s cubic-bezier(.34, 1.56, .64, 1); }
.library-pdf-close:hover svg { rotate: 90deg; }
.library-pdf-close:focus, .library-pdf-close:focus-visible { outline: none; box-shadow: none; }
.library-pdf-resize { position: absolute; z-index: 1; touch-action: none; user-select: none; }
.library-pdf-resize-n, .library-pdf-resize-s { left: 10px; right: 10px; height: 8px; cursor: ns-resize; }
.library-pdf-resize-n { top: -4px; }
.library-pdf-resize-s { bottom: -4px; }
.library-pdf-resize-e, .library-pdf-resize-w { top: 10px; bottom: 10px; width: 8px; cursor: ew-resize; }
.library-pdf-resize-e { right: -4px; }
.library-pdf-resize-w { left: -4px; }
.library-pdf-resize-ne, .library-pdf-resize-nw, .library-pdf-resize-se, .library-pdf-resize-sw { width: 16px; height: 16px; }
.library-pdf-resize-ne { top: -4px; right: -4px; cursor: nesw-resize; }
.library-pdf-resize-nw { top: -4px; left: -4px; cursor: nwse-resize; }
.library-pdf-resize-se { bottom: -4px; right: -4px; cursor: nwse-resize; }
.library-pdf-resize-sw { bottom: -4px; left: -4px; cursor: nesw-resize; }
@media (max-width: 640px) {
  .library-pdf-reader { width: calc(100vw - 24px); height: calc(100dvh - 24px); }
}
</style>
