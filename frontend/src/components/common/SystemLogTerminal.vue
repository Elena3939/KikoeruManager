<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import StatefulButton from '../ui/stateful-button.vue'
import { ElMessage } from 'element-plus'
import { copyText } from '../../utils/clipboard'
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  CirclePause,
  CirclePlay,
  Copy,
  FileText,
  Files,
  Info,
  RotateCcw,
  Terminal,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from 'lucide-vue-next'

const props = defineProps({
  copyTask: { type: Function, default: null },
  title: { type: String, default: 'system.log' },
  subtitle: { type: String, default: 'kikoerumanager - system stream' },
  lines: { type: Array, default: () => [] },
  highlightTerms: { type: Array, default: () => [] },
  status: { type: String, default: 'idle' },
  errorMessage: { type: String, default: '' },
  taskStatus: { type: String, default: '' },
  maxHeight: { type: Number, default: 380 },
  autoScrollDefault: { type: Boolean, default: true },
  autoScrollEnabled: { type: Boolean, default: null },
})

const emit = defineEmits(['clear', 'reconnect', 'update:autoScrollEnabled', 'follow-change', 'load-before', 'copy-task', 'line-expand', 'noise-expand'])

const scrollRef = ref(null)
const localAutoScroll = ref(props.autoScrollDefault)
const autoScroll = computed(() => props.autoScrollEnabled ?? localAutoScroll.value)
const userPinnedHistory = ref(false)
const expandedLineKeys = ref(new Set())
const selectedKeys = ref(new Set())
const timelines = ref(new Map())
const measuredHeights = new Map()
const highlightedKey = ref('')
let selectionAnchor = null
let highlightTimer = null

let autoScrollRaf = 0
let resizeObserver = null
let lastScrollTop = 0
let touchY = null
let scrollbarDragging = false
let historyLoadPending = false

const safeLines = computed(() => Array.isArray(props.lines) ? props.lines : [])
const lineCount = computed(() => safeLines.value.length)
const terminalHeight = computed(() => `${Math.max(260, Number(props.maxHeight || 380))}px`)
const connectionStatus = computed(() => String(props.status || 'idle').trim().toLowerCase())
const isFinished = computed(() => ['completed', 'failed', 'cancelled', 'canceled'].includes(String(props.taskStatus || '').trim().toLowerCase()))
const normalizedHighlightTerms = computed(() => Array.from(new Set(
  (Array.isArray(props.highlightTerms) ? props.highlightTerms : [])
    .map((term) => String(term || '').trim().toLowerCase())
    .filter(Boolean),
)).sort((left, right) => right.length - left.length))
const highlightPattern = computed(() => {
  if (!normalizedHighlightTerms.value.length) return null
  const escaped = normalizedHighlightTerms.value.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  return new RegExp(`(${escaped.join('|')})`, 'giu')
})

const statusMeta = computed(() => {
  const status = connectionStatus.value
  if (status === 'connected') return { label: '已连接', className: 'is-connected', icon: Wifi }
  if (status === 'connecting') return { label: '连接中', className: 'is-connecting', icon: RotateCcw }
  if (status === 'error') return { label: '错误', className: 'is-error', icon: WifiOff }
  if (status === 'disconnected') return { label: '已断开', className: 'is-disconnected', icon: WifiOff }
  return { label: '未连接', className: 'is-idle', icon: WifiOff }
})

const rowVirtualizer = useVirtualizer(computed(() => {
  // 滑动窗口条数不变时，记录身份仍会变化，必须使虚拟列表刷新 key 缓存。
  const lines = safeLines.value
  const keys = lines.map(lineKey)
  const expanded = expandedLineKeys.value
  return {
    count: lines.length,
    getItemKey: (index) => keys[index],
    getScrollElement: () => scrollRef.value,
    // 批量估高时直接读当前快照，避免每行重复访问响应式数组和计算属性。
    estimateSize: (index) => measuredHeights.get(keys[index])
      ?? (expanded.has(keys[index]) ? estimateExpandedLineSize(lines[index]) : 32),
    measureElement: (element, entry) => {
      // 使用观察器已计算的尺寸，避免逐行 ref 回调交错读写触发同步布局。
      const height = entry?.borderBoxSize?.[0]?.blockSize
        || measuredHeights.get(element?.dataset.lineKey) || 32
      if (element?.dataset.lineKey) measuredHeights.set(element.dataset.lineKey, height)
      return height
    },
    overscan: 12,
  }
}))

// 只补偿视口上方的行；下方测高不会抢走用户正在阅读的位置。
rowVirtualizer.value.shouldAdjustScrollPositionOnItemSizeChange = (item) => {
  const element = scrollRef.value
  return Boolean(element && item?.start < element.scrollTop)
}

const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())

function clampProgress(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

function normalizeProgressTone(value) {
  const tone = String(value || 'processing').trim().toLowerCase()
  if (['success', 'error', 'waiting', 'paused'].includes(tone)) return tone
  return 'processing'
}

function progressToneLabel(value) {
  const tone = normalizeProgressTone(value)
  if (tone === 'success') return '完成'
  if (tone === 'error') return '异常'
  if (tone === 'waiting') return '等待'
  if (tone === 'paused') return '暂停'
  return '进行中'
}

function isTaskProgressLine(line) {
  return String(line?.kind || '') === 'task-progress' && hasProgress(line)
}

const timeFormatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

function formatTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    const text = String(value)
    return text.length > 8 ? text.slice(11, 19) || text.slice(0, 8) : text
  }
  return timeFormatter.format(date)
}

function normalizeLevel(value) {
  const level = String(value || 'info').trim().toLowerCase()
  if (level === 'warn') return 'warning'
  if (level === 'err' || level === 'fatal') return 'error'
  if (level === 'ok') return 'success'
  return level || 'info'
}

function levelIcon(level) {
  const normalized = normalizeLevel(level)
  if (normalized === 'success') return CheckCircle2
  if (normalized === 'warning') return AlertTriangle
  if (normalized === 'error') return AlertTriangle
  if (normalized === 'debug') return Bug
  return Info
}

function levelLabel(level) {
  const normalized = normalizeLevel(level)
  if (normalized === 'warning') return 'warn'
  return normalized
}

function hasProgress(line) {
  return line?.progress !== null && line?.progress !== undefined && Number.isFinite(Number(line.progress))
}

function shellTokens(text) {
  const value = String(text || '')
  const parts = value.split(/(\s+)/)
  let expectCommand = true
  return parts.map((part) => {
    if (/^\s+$/.test(part)) return { type: 'default', value: part }
    if (part.startsWith('#')) return { type: 'comment', value: part }
    if (part.startsWith('$')) return { type: 'variable', value: part }
    if (part.startsWith('--') || part.startsWith('-')) return { type: 'flag', value: part }
    if (/^["'].*["']$/.test(part)) return { type: 'string', value: part }
    if (/^\d+%?$/.test(part)) return { type: 'number', value: part }
    if (/^[|>&<]+$/.test(part)) {
      expectCommand = true
      return { type: 'operator', value: part }
    }
    if (part.includes('/') || part.includes('\\') || part.startsWith('.') || part.startsWith('~')) return { type: 'path', value: part }
    if (expectCommand) {
      expectCommand = false
      return { type: 'command', value: part }
    }
    return { type: 'default', value: part }
  })
}

function logMessage(line, preferFull = false) {
  if (!line) return ''
  if (preferFull) {
    return String(line.fullMessage || line.rawLine || line.message || '')
  }
  return String(line.message || line.fullMessage || line.rawLine || '')
}

function originalLogMessage(line) {
  if (!line) return ''
  const message = String(line.message || '')
  const fullMessage = String(line.fullMessage || '')
  const rawLine = String(line.rawLine || '')
  if (fullMessage && fullMessage !== message) return fullMessage
  return rawLine || fullMessage || message
}

function hasHiddenOriginalDetail(line) {
  if (!line) return false
  return originalLogMessage(line) !== logMessage(line)
}

function isLineTruncated(line) {
  return Boolean(line?.isTruncated)
}

function lineKey(line, index) {
  if (line?.id !== null && line?.id !== undefined) return String(line.id)
  return `${index}:${formatTime(line?.time)}:${levelLabel(line?.level)}:${logMessage(line, true).slice(0, 80)}`
}

function isLineExpanded(line, index) {
  return expandedLineKeys.value.has(lineKey(line, index))
}

function estimateExpandedLineSize(line) {
  const text = originalLogMessage(line)
  const width = Number(scrollRef.value?.clientWidth || 920)
  const detailWidth = width <= 720 ? Math.max(280, width - 28) : Math.max(360, width - 332)
  const charsPerRow = Math.max(44, Math.floor(detailWidth / 7.4))
  const visualLineCount = String(text || '')
    .split(/\r\n|\n|\r/)
    .reduce((sum, segment) => sum + Math.max(1, Math.ceil(segment.length / charsPerRow)), 0)
  return Math.max(54, 18 + visualLineCount * 18)
}

function lineText(line, preferFull = false) {
  const time = formatTime(line?.time)
  const level = levelLabel(line?.level).toUpperCase()
  const source = String(line?.source || 'system')
  const progress = line?.progress !== null && line?.progress !== undefined && Number.isFinite(Number(line.progress))
    ? ` ${Number(line.progress)}%`
    : ''
  return `[${time}] ${level} ${source}${progress} ${logMessage(line, preferFull)}`
}

function allText() {
  return safeLines.value.map((line) => lineText(line, true)).join('\n')
}

async function copyLogs() {
  const text = allText()
  if (!text) {
    ElMessage.info('当前没有可复制的日志')
    return
  }
  try {
    if (await copyText(text)) ElMessage.success(`已复制 ${safeLines.value.length} 行日志`)
    else throw new Error('clipboard unavailable')
  } catch {
    ElMessage.error('复制失败，浏览器未授权剪贴板')
  }
}

async function copyLine(line) {
  const text = line.rawLine || lineText(line, true)
  if (!text) return
  try {
    if (await copyText(text)) ElMessage.success('已复制完整日志')
    else throw new Error('clipboard unavailable')
  } catch {
    ElMessage.error('复制失败，浏览器未授权剪贴板')
  }
}

function handleLineCopy(event, line) {
  if (!isLineTruncated(line) && !hasHiddenOriginalDetail(line)) return
  event.clipboardData?.setData('text/plain', lineText(line, true))
  event.preventDefault()
}

function toggleLineDetail(line, index, event) {
  if (!line) return
  if (line.kind === 'noise-group') { emit('noise-expand', line); return }
  const key = lineKey(line, index)
  const selected = event?.ctrlKey || event?.metaKey || event?.shiftKey ? new Set(selectedKeys.value) : new Set()
  if (event?.shiftKey && selectionAnchor !== null) {
    const anchor = safeLines.value.findIndex((row, i) => lineKey(row, i) === selectionAnchor)
    for (let i = anchor < 0 ? index : Math.min(anchor, index); i <= Math.max(anchor, index); i++) selected.add(lineKey(safeLines.value[i], i))
  } else if (selected.has(key)) selected.delete(key)
  else selected.add(key)
  selectedKeys.value = selected
  selectionAnchor = key
  if (event?.shiftKey || event?.ctrlKey || event?.metaKey) return
  const expanded = new Set(expandedLineKeys.value)
  if (expanded.has(key)) expanded.delete(key)
  else { expanded.add(key); emit('line-expand', line) }
  measuredHeights.delete(key)
  expandedLineKeys.value = expanded
}

function collapseAll() {
  expandedLineKeys.value = new Set()
  measuredHeights.clear()
}

async function copySelected(withTime = true) {
  const rows = safeLines.value.filter((row, index) => selectedKeys.value.has(lineKey(row, index)))
  try {
    const copied = await copyText(rows.map((row) => withTime ? (row.rawLine || lineText(row, true)) : plainLogMessage(row)).join('\n'))
    if (!copied) throw new Error('clipboard unavailable')
    ElMessage.success(`已复制 ${rows.length} 条日志`)
  } catch { ElMessage.error('复制失败，浏览器未授权剪贴板') }
}

function plainLogMessage(row) {
  if (!row.rawLine) return logMessage(row, true)
  return row.rawLine.replace(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?\s+(?:\[\w+\]\s+\S+\s+-\s*|-\s+\S+\s+-\s+\w+\s+-\s*)/, '')
}

const selectedTaskId = computed(() => {
  const row = safeLines.value.find((row, index) => selectedKeys.value.has(lineKey(row, index)))
  return row?.taskId || row?.taskProgress?.taskId || ''
})

function setTimeline(key, text) {
  timelines.value = new Map(timelines.value).set(key, text)
  measuredHeights.delete(key)
  nextTick(() => rowVirtualizer.value.measure())
}

function visibleLineMessage(line, index) {
  if (isLineExpanded(line, index)) return timelines.value.get(lineKey(line, index)) || originalLogMessage(line)
  const message = logMessage(line)
  return message
}

function measureTerminalLine(element) {
  if (element) rowVirtualizer.value.measureElement(element)
}

function isTerminalRowClipped(row) {
  if (!row || typeof row.querySelector !== 'function' || typeof document === 'undefined') return false
  const message = row.querySelector('.terminal-message')
  const messageText = row.querySelector('.terminal-message-text')
  if (!message || !messageText) return false

  const availableWidth = message.getBoundingClientRect().width
  if (!availableWidth) return false

  const sourceStyle = window.getComputedStyle(messageText)
  const probe = document.createElement('span')
  probe.textContent = messageText.textContent || ''
  probe.style.position = 'fixed'
  probe.style.left = '-9999px'
  probe.style.bottom = '-9999px'
  probe.style.visibility = 'hidden'
  probe.style.pointerEvents = 'none'
  probe.style.whiteSpace = 'pre'
  probe.style.font = sourceStyle.font
  probe.style.letterSpacing = sourceStyle.letterSpacing
  document.body.appendChild(probe)
  const naturalWidth = probe.getBoundingClientRect().width
  probe.remove()

  return naturalWidth > availableWidth + 1
}

function clearLogs() {
  emit('clear')
}

function toggleAutoScroll() {
  const enabled = !autoScroll.value
  localAutoScroll.value = enabled
  emit('update:autoScrollEnabled', enabled)
}

function handleScroll() {
  const el = scrollRef.value
  if (!el) return
  const movedUp = el.scrollTop < lastScrollTop
  lastScrollTop = el.scrollTop
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  const followThreshold = 64 // 普通日志约 32px/行，底部两行以内才跟随
  if (movedUp || (!autoScrollRaf && !scrollbarDragging)) {
    userPinnedHistory.value = distance > followThreshold
  }
  if (el.scrollTop <= 200 && !historyLoadPending && lineCount.value) {
    const first = safeLines.value[0]
    historyLoadPending = true
    emit('load-before', {
      file: first?.file || 'app.log',
      anchorOffset: Number(first?.offset || 0),
      done: () => { historyLoadPending = false },
    })
  }
}

function captureScrollState() {
  const el = scrollRef.value
  if (!el) return null
  const item = rowVirtualizer.value.getVirtualItems().find((row) => row.end > el.scrollTop)
  const end = rowVirtualizer.value.getVirtualItems().find((row) => row.end >= el.scrollTop + el.clientHeight)
  return { key: item?.key, endKey: end?.key, offset: item ? el.scrollTop - item.start : 0, scrollTop: el.scrollTop }
}

function restoreScrollState(state) {
  const el = scrollRef.value
  if (!el || !state) return
  const index = safeLines.value.findIndex((row, i) => lineKey(row, i) === state.key)
  if (index >= 0) {
    const position = rowVirtualizer.value.getOffsetForIndex(index, 'start')
    el.scrollTop = Math.max(0, (position?.[0] || 0) + state.offset)
  } else el.scrollTop = state.scrollTop
  lastScrollTop = el.scrollTop
  historyLoadPending = false
}

function followBottom() {
  userPinnedHistory.value = false
  scrollToBottom()
}

function jumpToKey(key) {
  userPinnedHistory.value = true
  const index = safeLines.value.findIndex((row, i) => lineKey(row, i) === key)
  if (index >= 0) rowVirtualizer.value.scrollToIndex(index, { align: 'center' })
  highlightedKey.value = key
  clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => { highlightedKey.value = '' }, 4000)
}

defineExpose({ captureScrollState, restoreScrollState, followBottom, jumpToKey, setTimeline })

function pinHistory() {
  const el = scrollRef.value
  if (!el || el.scrollHeight <= el.clientHeight + 2) return
  userPinnedHistory.value = true
  cancelAutoScroll()
}

function handleTouchStart(event) {
  touchY = event.touches[0]?.clientY ?? null
}

function handleTouchMove(event) {
  const y = event.touches[0]?.clientY ?? null
  if (y !== null && touchY !== null && y > touchY) pinHistory()
  touchY = y
}

function handlePointerDown(event) {
  const el = scrollRef.value
  if (!el || event.clientX < el.getBoundingClientRect().left + el.clientLeft + el.clientWidth) return
  scrollbarDragging = true
  pinHistory()
}

function handlePointerUp() {
  if (!scrollbarDragging) return
  scrollbarDragging = false
  handleScroll()
}

function highlightedTextParts(value) {
  const text = String(value || '')
  const pattern = highlightPattern.value
  if (!text || !pattern) return [{ value: text, highlighted: false }]
  const terms = normalizedHighlightTerms.value
  return text
    .split(pattern)
    .filter((part) => part !== '')
    .map((part) => ({
      value: part,
      highlighted: terms.includes(part.toLowerCase()),
    }))
}

function cancelAutoScroll() {
  if (autoScrollRaf) {
    window.cancelAnimationFrame(autoScrollRaf)
    autoScrollRaf = 0
  }
}

function scrollToBottom() {
  if (typeof window === 'undefined' || !autoScroll.value || userPinnedHistory.value) return
  if (autoScrollRaf) return
  autoScrollRaf = window.requestAnimationFrame(() => {
    autoScrollRaf = 0
    if (!autoScroll.value || userPinnedHistory.value || !lineCount.value) return
    const el = scrollRef.value
    if (!el) return
    // 直接定位，避免虚拟列表 scrollToIndex 的重试在用户上滚后继续抢位置。
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight)
    lastScrollTop = el.scrollTop
  })
}

watch(userPinnedHistory, (pinned) => {
  if (pinned) cancelAutoScroll()
  emit('follow-change', !pinned)
}, { flush: 'sync' })

watch(autoScroll, (enabled) => {
  if (!enabled) cancelAutoScroll()
  else scrollToBottom()
}, { flush: 'sync' })

watch(() => props.lines, () => {
  const keys = new Set(safeLines.value.map((line, index) => lineKey(line, index)))
  for (const key of measuredHeights.keys()) if (!keys.has(key)) measuredHeights.delete(key)
  for (const key of timelines.value.keys()) if (!keys.has(key)) timelines.value.delete(key)
  selectedKeys.value = new Set([...selectedKeys.value].filter((key) => keys.has(key)))
  const expanded = [...expandedLineKeys.value].filter((key) => keys.has(key))
  if (expanded.length !== expandedLineKeys.value.size) expandedLineKeys.value = new Set(expanded)
  scrollToBottom()
}, { flush: 'post' })

watch(totalSize, scrollToBottom, { flush: 'post' })

watch(expandedLineKeys, () => {
  nextTick(() => {
    rowVirtualizer.value.measure()
  })
})

onMounted(() => {
  window.addEventListener('pointerup', handlePointerUp)
  window.addEventListener('pointercancel', handlePointerUp)
  scrollToBottom()
  if (typeof ResizeObserver === 'undefined' || !scrollRef.value) return
  resizeObserver = new ResizeObserver(() => {
    nextTick(() => {
      rowVirtualizer.value.measure()
      if (!userPinnedHistory.value) scrollToBottom()
    })
  })
  resizeObserver.observe(scrollRef.value)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerup', handlePointerUp)
  window.removeEventListener('pointercancel', handlePointerUp)
  if (autoScrollRaf) {
    window.cancelAnimationFrame(autoScrollRaf)
    autoScrollRaf = 0
  }
  clearTimeout(highlightTimer)
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div class="system-log-terminal" :style="{ '--terminal-height': terminalHeight }">
    <div class="terminal-window">
      <div class="terminal-titlebar">
        <div class="terminal-lights" aria-hidden="true">
          <span class="is-red" />
          <span class="is-yellow" />
          <span class="is-green" />
        </div>
        <div class="terminal-title">
          <Terminal :size="13" :stroke-width="2.3" />
          <span class="terminal-title-text">{{ title }}</span>
          <span v-if="isFinished" class="terminal-finished">finished</span>
        </div>
        <div class="terminal-actions">
          <button v-if="expandedLineKeys.size" class="terminal-icon-button" title="全部折叠" @click="collapseAll"><RotateCcw :size="14" /></button>
          <button
            type="button"
            class="terminal-icon-button"
            :title="autoScrollEnabled === null ? (autoScroll ? '暂停自动滚动' : '恢复自动滚动') : (autoScroll ? '暂停自动刷新' : '开启自动刷新')"
            @click="toggleAutoScroll"
          >
            <component :is="autoScroll ? CirclePause : CirclePlay" :size="14" :stroke-width="2.35" />
          </button>
          <StatefulButton unstyled class="terminal-icon-button" title="复制日志" @click="copyLogs">
            <Copy :size="14" :stroke-width="2.35" />
          </StatefulButton>
          <button type="button" class="terminal-icon-button" title="清空当前显示" @click="clearLogs">
            <Trash2 :size="14" :stroke-width="2.35" />
          </button>
          <button type="button" class="terminal-icon-button" title="重新连接" @click="$emit('reconnect')">
            <RotateCcw :size="14" :stroke-width="2.35" />
          </button>
        </div>
      </div>

      <div class="terminal-meta">
        <span class="terminal-summary">{{ lineCount }} lines · {{ autoScroll && !userPinnedHistory ? 'auto-scroll' : 'history pinned' }}</span>
        <span class="terminal-status" :class="statusMeta.className">
          <component :is="statusMeta.icon" :size="12" :stroke-width="2.4" />
          {{ statusMeta.label }}
        </span>
      </div>

      <div class="terminal-body">
      <slot name="body-overlay" />
      <div
        ref="scrollRef"
        class="terminal-scroll"
        tabindex="0"
        @scroll.passive="handleScroll"
        @wheel.passive="($event.deltaY < 0) && pinHistory()"
        @touchstart.passive="handleTouchStart"
        @touchmove.passive="handleTouchMove"
        @pointerdown="handlePointerDown"
        @keydown="['ArrowUp', 'PageUp', 'Home'].includes($event.key) && pinHistory()"
      >
        <div v-if="!lineCount" class="terminal-empty">
          <span class="terminal-empty-text">暂无日志输出</span>
          <span class="terminal-cursor" />
        </div>

        <div v-else class="terminal-virtual-canvas" :style="{ height: `${totalSize}px` }">
          <div
            v-for="virtualRow in virtualRows"
            :key="virtualRow.key"
            :ref="measureTerminalLine"
            :data-index="virtualRow.index"
            :data-line-key="lineKey(safeLines[virtualRow.index], virtualRow.index)"
            class="terminal-line"
            :class="[
              `is-${normalizeLevel(safeLines[virtualRow.index]?.level)}`,
              `is-progress-${normalizeProgressTone(safeLines[virtualRow.index]?.taskProgress?.tone)}`,
              {
                'has-progress': hasProgress(safeLines[virtualRow.index]),
                'has-inline-progress': hasProgress(safeLines[virtualRow.index]) && !isTaskProgressLine(safeLines[virtualRow.index]),
                'is-task-progress': isTaskProgressLine(safeLines[virtualRow.index]),
                'is-truncated': isLineTruncated(safeLines[virtualRow.index]),
                'can-toggle-detail': true,
                'is-selected': selectedKeys.has(String(virtualRow.key)),
                'is-search-target': highlightedKey === String(virtualRow.key),
                'is-expanded': isLineExpanded(safeLines[virtualRow.index], virtualRow.index),
              },
            ]"
            :style="{
              minHeight: '32px',
              transform: `translate3d(0, ${virtualRow.start}px, 0)`,
            }"
            @contextmenu.prevent="safeLines[virtualRow.index]?.taskId && $emit('copy-task', safeLines[virtualRow.index].taskId)"
            @click="toggleLineDetail(safeLines[virtualRow.index], virtualRow.index, $event)"
          >
            <span class="terminal-time">{{ formatTime(safeLines[virtualRow.index]?.time) }}</span>
            <span class="terminal-level">
              <component :is="levelIcon(safeLines[virtualRow.index]?.level)" :size="12" :stroke-width="2.5" />
              {{ levelLabel(safeLines[virtualRow.index]?.level) }}
            </span>
            <span class="terminal-source">{{ safeLines[virtualRow.index]?.source || 'system' }}</span>
            <span v-if="hasProgress(safeLines[virtualRow.index]) && !isTaskProgressLine(safeLines[virtualRow.index])" class="terminal-progress">{{ safeLines[virtualRow.index]?.progress }}%</span>
            <span
              class="terminal-message"
              :title="isLineTruncated(safeLines[virtualRow.index]) ? '点击展开完整日志' : isLineExpanded(safeLines[virtualRow.index], virtualRow.index) ? '点击收起原始日志' : '点击查看原始日志'"
              @copy="handleLineCopy($event, safeLines[virtualRow.index])"
            >
              <span class="terminal-message-text">
                <template v-if="isLineExpanded(safeLines[virtualRow.index], virtualRow.index)">
                  <template v-for="(token, tokenIndex) in shellTokens(visibleLineMessage(safeLines[virtualRow.index], virtualRow.index))" :key="`${virtualRow.key}-${tokenIndex}`">
                    <span :class="`terminal-token is-${token.type}`">
                      <template v-for="(part, partIndex) in highlightedTextParts(token.value)" :key="`${virtualRow.key}-${tokenIndex}-${partIndex}`">
                        <mark v-if="part.highlighted" class="terminal-search-highlight">{{ part.value }}</mark>
                        <template v-else>{{ part.value }}</template>
                      </template>
                    </span>
                  </template>
                </template>
                <template v-else>
                  <template v-for="(part, partIndex) in highlightedTextParts(visibleLineMessage(safeLines[virtualRow.index], virtualRow.index))" :key="`${virtualRow.key}-${partIndex}`">
                    <mark v-if="part.highlighted" class="terminal-search-highlight">{{ part.value }}</mark>
                    <template v-else>{{ part.value }}</template>
                  </template>
                </template>
              </span>
            </span>
            <StatefulButton unstyled class="terminal-row-copy terminal-icon-button" title="复制完整日志" @click.stop="() => copyLine(safeLines[virtualRow.index])"><Copy :size="13" /></StatefulButton>
          </div>
        </div>
      </div>
      </div>
      <div v-if="selectedKeys.size" class="terminal-selection-bar" role="toolbar" aria-label="日志选择操作">
        <span class="terminal-selection-count">已选 {{ selectedKeys.size }} 条</span>
        <StatefulButton unstyled class="terminal-selection-action" title="复制选中日志（带时间）" aria-label="复制选中日志（带时间）" @click="() => copySelected(true)"><Copy :size="13" />复制</StatefulButton>
        <StatefulButton unstyled class="terminal-selection-action" title="复制选中日志为纯文本" aria-label="复制选中日志为纯文本" @click="() => copySelected(false)"><FileText :size="13" />纯文本</StatefulButton>
        <StatefulButton unstyled v-if="selectedTaskId" class="terminal-selection-action is-icon" title="复制本任务全部日志" aria-label="复制本任务全部日志" @click="() => copyTask ? copyTask(selectedTaskId) : $emit('copy-task', selectedTaskId)"><Files :size="13" /></StatefulButton>
        <button type="button" class="terminal-selection-action is-icon terminal-selection-clear" title="清除选择" aria-label="清除选择" @click="selectedKeys = new Set()"><X :size="14" /></button>
      </div>
      <div class="terminal-footer">
        <span>{{ subtitle }}</span>
        <span v-if="errorMessage" class="terminal-error">{{ errorMessage }}</span>
        <span v-else>{{ autoScroll ? '自动滚动' : '查看历史' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.system-log-terminal {
  width: 100%;
  min-width: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.terminal-body { position: relative; min-width: 0; }

.terminal-window {
  overflow: hidden;
  border: 1px solid rgba(39, 39, 42, 0.96);
  border-radius: 14px;
  background: #09090b;
  box-shadow:
    0 24px 55px -28px rgba(15, 23, 42, 0.85),
    0 12px 26px -18px rgba(0, 0, 0, 0.88);
}

.terminal-titlebar {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(63, 63, 70, 0.85);
  background: #18181b;
}

.terminal-lights {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.terminal-lights span {
  width: 12px;
  height: 12px;
  border-radius: 999px;
}

.terminal-lights .is-red { background: #ff5f56; }
.terminal-lights .is-yellow { background: #ffbd2e; }
.terminal-lights .is-green { background: #27c93f; }

.terminal-title {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: #a1a1aa;
  font-size: 12px;
  font-weight: 700;
}

.terminal-title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-finished {
  flex-shrink: 0;
  border: 1px solid rgba(52, 211, 153, 0.22);
  border-radius: 999px;
  padding: 1px 6px;
  color: #86efac;
  font-size: 10px;
}

.terminal-actions {
  display: inline-flex;
  justify-content: flex-end;
  gap: 4px;
}

.terminal-icon-button {
  display: inline-flex;
  width: 28px;
  height: 28px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(82, 82, 91, 0.7);
  border-radius: 8px;
  background: rgba(24, 24, 27, 0.72);
  color: #d4d4d8;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.terminal-icon-button:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(161, 161, 170, 0.8);
  background: rgba(39, 39, 42, 0.9);
  color: #fff;
}

.terminal-icon-button:active {
  transform: scale(0.96);
}

.terminal-icon-button:hover :deep(svg) {
  transform: rotate(-8deg);
}

.terminal-icon-button :deep(svg) {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.terminal-meta,
.terminal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 14px;
  color: #71717a;
  font-size: 11px;
}

.terminal-meta {
  border-bottom: 1px solid rgba(39, 39, 42, 0.76);
}

.terminal-footer {
  border-top: 1px solid rgba(39, 39, 42, 0.76);
  background: #09090b;
}

.terminal-status {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 5px;
  border: 1px solid rgba(82, 82, 91, 0.8);
  border-radius: 999px;
  padding: 3px 8px;
  color: #a1a1aa;
}

.terminal-status.is-connected {
  border-color: rgba(16, 185, 129, 0.35);
  color: #6ee7b7;
}

.terminal-status.is-connecting {
  border-color: rgba(56, 189, 248, 0.35);
  color: #7dd3fc;
}

.terminal-status.is-error {
  border-color: rgba(251, 113, 133, 0.35);
  color: #fda4af;
}

.terminal-scroll {
  position: relative;
  height: var(--terminal-height);
  overflow: auto;
  padding: 10px 0;
  background: #09090b;
  contain: strict;
  scrollbar-color: rgba(113, 113, 122, 0.7) transparent;
}

.terminal-empty {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 14px;
  color: #d4d4d8;
  font-size: 12px;
}

.terminal-cursor {
  width: 8px;
  height: 16px;
  background: #d4d4d8;
  animation: terminal-cursor 1.05s steps(2, start) infinite;
}

.terminal-virtual-canvas {
  position: relative;
  width: 100%;
  contain: layout style paint;
}

.terminal-line {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  display: grid;
  grid-template-columns: 72px 76px 92px 46px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 5px 14px;
  box-sizing: border-box;
  border-left: none;
  color: #d4d4d8;
  font-size: 11.5px;
  line-height: 1.35;
  contain: layout style paint;
  transform: translateZ(0);
  will-change: transform;
}

.terminal-line:hover {
  background: rgba(39, 39, 42, 0.58);
}

.terminal-line.is-expanded {
  align-items: flex-start;
  padding-top: 7px;
  padding-bottom: 9px;
}

.terminal-line.can-toggle-detail {
  cursor: pointer;
}

.terminal-line.is-expanded .terminal-time,
.terminal-line.is-expanded .terminal-level,
.terminal-line.is-expanded .terminal-source,
.terminal-line.is-expanded .terminal-progress {
  padding-top: 2px;
}

.terminal-time {
  color: #71717a;
  font-variant-numeric: tabular-nums;
}

.terminal-level,
.terminal-source,
.terminal-progress {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-level {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 900;
  text-transform: uppercase;
}

.terminal-source {
  color: #a1a1aa;
}

.terminal-progress {
  color: #38bdf8;
  font-weight: 900;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.terminal-message {
  display: flex;
  align-items: center;
  grid-column: 4 / -1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-line.is-expanded .terminal-message {
  display: block;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}

.terminal-message-text {
  display: block;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-line.is-expanded .terminal-message-text {
  display: block;
  overflow: visible;
  text-overflow: clip;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.terminal-line.is-expanded .terminal-token {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}

.terminal-search-highlight {
  margin: 0 1px;
  padding: 0 2px;
  border: 0;
  border-radius: 3px;
  background: #fde047;
  color: #111827;
  font: inherit;
  font-weight: 900;
  box-shadow: 0 0 0 1px rgba(250, 204, 21, 0.28);
}

.terminal-line.has-inline-progress .terminal-message {
  grid-column: auto;
}

.terminal-line.is-info .terminal-level { color: #93c5fd; }
.terminal-line.is-success .terminal-level { color: #86efac; }
.terminal-line.is-warning {
  background: rgba(245, 158, 11, 0.18);
}
.terminal-line.is-warning .terminal-level {
  color: #fbbf24;
}
.terminal-line.is-warning .terminal-time,
.terminal-line.is-warning .terminal-source {
  color: #d97706;
}
.terminal-line.is-warning .terminal-token.is-default,
.terminal-line.is-warning .terminal-message {
  color: #fde68a;
}
.terminal-line.is-error {
  background: rgba(239, 68, 68, 0.16);
}
.terminal-line.is-error .terminal-level { color: #fb7185; }
.terminal-line.is-error .terminal-time,
.terminal-line.is-error .terminal-source {
  color: #f87171;
}
.terminal-line.is-error .terminal-token.is-default,
.terminal-line.is-error .terminal-message {
  color: #fecdd3;
}
.terminal-line.is-debug .terminal-level { color: #c084fc; }

.terminal-token.is-command { color: #34d399; }
.terminal-token.is-flag { color: #38bdf8; }
.terminal-token.is-string { color: #fbbf24; }
.terminal-token.is-number { color: #c084fc; }
.terminal-token.is-operator { color: #fb7185; }
.terminal-token.is-path { color: #67e8f9; }
.terminal-token.is-variable { color: #f472b6; }
.terminal-token.is-comment { color: #71717a; }
.terminal-token.is-default { color: #d4d4d8; }

.terminal-error {
  min-width: 0;
  overflow: hidden;
  color: #fda4af;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes terminal-cursor {
  0%, 46% { opacity: 1; }
  47%, 100% { opacity: 0; }
}

@keyframes terminal-progress-sheen {
  from { transform: translateX(-100%); }
  to { transform: translateX(100%); }
}

@media (max-width: 720px) {
  .terminal-titlebar {
    grid-template-columns: 62px minmax(0, 1fr) auto;
    padding: 0 9px;
  }

  .terminal-actions {
    gap: 2px;
  }

  .terminal-icon-button {
    width: 26px;
    height: 26px;
  }

  .terminal-meta,
  .terminal-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .terminal-line {
    grid-template-columns: 62px 68px minmax(0, 1fr);
    gap: 6px;
    padding: 7px 10px;
  }

  .terminal-source,
  .terminal-progress {
    display: none;
  }

  .terminal-message {
    grid-column: 1 / -1;
  }

  .terminal-inline-progress {
    grid-template-columns: minmax(0, 1fr);
    gap: 5px;
  }

  .terminal-inline-progress-head {
    gap: 8px;
  }

  .terminal-inline-progress-detail {
    display: block;
  }
}

.terminal-window { position: relative; }
.terminal-line { padding-right: 42px; }
.terminal-line.is-task-progress { min-height: 32px; }
.terminal-line.is-task-progress .terminal-message-text::first-letter { color: #38bdf8; }
.terminal-line.is-progress-success .terminal-message-text::first-letter { color: #86efac; }
.terminal-line.is-progress-error .terminal-message-text::first-letter { color: #fda4af; }
.terminal-line.is-selected { background: rgba(56, 189, 248, 0.14); }
.terminal-line.is-search-target { background: rgba(250, 204, 21, 0.2); box-shadow: inset 3px 0 #facc15; }
.terminal-row-copy { position: absolute; right: 6px; top: 2px; opacity: 0; min-width: 28px; padding: 0; }
.terminal-line:hover .terminal-row-copy, .terminal-row-copy:focus-visible { opacity: 1; }
.terminal-selection-bar {
  position: absolute;
  z-index: 4;
  bottom: 38px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 2px;
  max-width: calc(100% - 24px);
  padding: 2px 4px;
  border: 1px solid rgba(82, 82, 91, 0.7);
  border-radius: 6px;
  background: #18181b;
  color: #d4d4d8;
  font-family: inherit;
  font-size: 11px;
  line-height: 16px;
  box-shadow: 0 3px 12px #0004;
}
.terminal-selection-count { flex-shrink: 0; padding: 0 8px 0 5px; color: #a1a1aa; white-space: nowrap; font-variant-numeric: tabular-nums; }
.terminal-selection-action {
  --stateful-button-icon-size: 13px;
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  height: 28px;
  box-sizing: border-box;
  padding: 0 6px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.terminal-selection-action :deep(.stateful-button__content) { gap: 0; }
.terminal-selection-action :deep(.stateful-button__content),
.terminal-selection-action :deep(.stateful-button__label),
.terminal-selection-action :deep(.stateful-button__state) {
  height: 100%;
  line-height: 1;
}
.terminal-selection-action :deep(.stateful-button__label) { gap: 5px; }
.terminal-selection-action :deep(.stateful-button__state:not(.is-idle)) { margin-right: 5px; }
.terminal-selection-action.is-icon { width: 28px; padding: 0; }
.terminal-selection-clear { color: #a1a1aa; }
.terminal-selection-action:hover { transform: translateY(-2px) scale(1.02); background: #ffffff0a; color: #fff; }
.terminal-selection-action:active { transform: scale(0.96); }
.terminal-selection-action :deep(svg) { flex-shrink: 0; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.terminal-selection-action:hover :deep(.stateful-button__label > svg), .terminal-selection-clear:hover > svg { transform: rotate(-8deg); }
.terminal-selection-action:disabled { cursor: default; opacity: 0.65; }
.terminal-selection-bar button:focus, .terminal-selection-bar button:focus-visible, .terminal-row-copy:focus { outline: none; box-shadow: none; }
@media (max-width: 640px) {
  .terminal-selection-bar { max-width: calc(100% - 16px); }
  .terminal-row-copy { opacity: 1; }
}

</style>
