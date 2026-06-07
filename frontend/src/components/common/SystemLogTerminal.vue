<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { ElMessage } from 'element-plus'
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  CirclePause,
  CirclePlay,
  Copy,
  Info,
  RotateCcw,
  Terminal,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-vue-next'

const props = defineProps({
  title: { type: String, default: 'system.log' },
  subtitle: { type: String, default: 'kikoerumanager - system stream' },
  lines: { type: Array, default: () => [] },
  status: { type: String, default: 'idle' },
  errorMessage: { type: String, default: '' },
  taskStatus: { type: String, default: '' },
  maxHeight: { type: Number, default: 380 },
  autoScrollDefault: { type: Boolean, default: true },
})

const emit = defineEmits(['clear', 'reconnect'])

const scrollRef = ref(null)
const autoScroll = ref(props.autoScrollDefault)
const userPinnedHistory = ref(false)

let autoScrollRaf = 0

const safeLines = computed(() => Array.isArray(props.lines) ? props.lines : [])
const lineCount = computed(() => safeLines.value.length)
const terminalHeight = computed(() => `${Math.max(260, Number(props.maxHeight || 380))}px`)
const connectionStatus = computed(() => String(props.status || 'idle').trim().toLowerCase())
const isFinished = computed(() => ['completed', 'failed', 'cancelled', 'canceled'].includes(String(props.taskStatus || '').trim().toLowerCase()))

const statusMeta = computed(() => {
  const status = connectionStatus.value
  if (status === 'connected') return { label: '已连接', className: 'is-connected', icon: Wifi }
  if (status === 'connecting') return { label: '连接中', className: 'is-connecting', icon: RotateCcw }
  if (status === 'error') return { label: '错误', className: 'is-error', icon: WifiOff }
  if (status === 'disconnected') return { label: '已断开', className: 'is-disconnected', icon: WifiOff }
  return { label: '未连接', className: 'is-idle', icon: WifiOff }
})

const rowVirtualizer = useVirtualizer(computed(() => ({
  count: lineCount.value,
  getScrollElement: () => scrollRef.value,
  estimateSize: () => 32,
  overscan: 12,
})))

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

function formatTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    const text = String(value)
    return text.length > 8 ? text.slice(11, 19) || text.slice(0, 8) : text
  }
  return date.toLocaleTimeString('zh-CN', { hour12: false })
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

function lineText(line) {
  const time = formatTime(line?.time)
  const level = levelLabel(line?.level).toUpperCase()
  const source = String(line?.source || 'system')
  const progress = line?.progress !== null && line?.progress !== undefined && Number.isFinite(Number(line.progress))
    ? ` ${Number(line.progress)}%`
    : ''
  return `[${time}] ${level} ${source}${progress} ${String(line?.message || '')}`
}

function allText() {
  return safeLines.value.map(lineText).join('\n')
}

async function copyLogs() {
  const text = allText()
  if (!text) {
    ElMessage.info('当前没有可复制的日志')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制 ${safeLines.value.length} 行日志`)
  } catch {
    ElMessage.error('复制失败，浏览器未授权剪贴板')
  }
}

function clearLogs() {
  emit('clear')
}

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  if (autoScroll.value) {
    userPinnedHistory.value = false
    scrollToBottom()
  }
}

function handleScroll() {
  const el = scrollRef.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  userPinnedHistory.value = distance > 72
  if (userPinnedHistory.value) autoScroll.value = false
}

function scrollToBottom() {
  if (typeof window === 'undefined') return
  if (autoScrollRaf) return
  autoScrollRaf = window.requestAnimationFrame(() => {
    autoScrollRaf = 0
    if (!lineCount.value) return
    rowVirtualizer.value.scrollToIndex(lineCount.value - 1, { align: 'end' })
  })
}

watch(lineCount, () => {
  if (autoScroll.value && !userPinnedHistory.value) scrollToBottom()
})

watch(() => props.status, () => {
  if (autoScroll.value && !userPinnedHistory.value) scrollToBottom()
})

onBeforeUnmount(() => {
  if (autoScrollRaf) {
    window.cancelAnimationFrame(autoScrollRaf)
    autoScrollRaf = 0
  }
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
          <button
            type="button"
            class="terminal-icon-button"
            :title="autoScroll ? '暂停自动滚动' : '恢复自动滚动'"
            @click="toggleAutoScroll"
          >
            <component :is="autoScroll ? CirclePause : CirclePlay" :size="14" :stroke-width="2.35" />
          </button>
          <button type="button" class="terminal-icon-button" title="复制日志" @click="copyLogs">
            <Copy :size="14" :stroke-width="2.35" />
          </button>
          <button type="button" class="terminal-icon-button" title="清空当前显示" @click="clearLogs">
            <Trash2 :size="14" :stroke-width="2.35" />
          </button>
          <button type="button" class="terminal-icon-button" title="重新连接" @click="$emit('reconnect')">
            <RotateCcw :size="14" :stroke-width="2.35" />
          </button>
        </div>
      </div>

      <div class="terminal-meta">
        <span class="terminal-summary">{{ lineCount }} lines · {{ autoScroll ? 'auto-scroll' : 'history pinned' }}</span>
        <span class="terminal-status" :class="statusMeta.className">
          <component :is="statusMeta.icon" :size="12" :stroke-width="2.4" />
          {{ statusMeta.label }}
        </span>
      </div>

      <div ref="scrollRef" class="terminal-scroll" @scroll="handleScroll">
        <div v-if="!lineCount" class="terminal-empty">
          <span class="terminal-empty-text">暂无日志输出</span>
          <span class="terminal-cursor" />
        </div>

        <div v-else class="terminal-virtual-canvas" :style="{ height: `${totalSize}px` }">
          <div
            v-for="virtualRow in virtualRows"
            :key="virtualRow.key"
            :data-index="virtualRow.index"
            class="terminal-line"
            :class="[
              `is-${normalizeLevel(safeLines[virtualRow.index]?.level)}`,
              `is-progress-${normalizeProgressTone(safeLines[virtualRow.index]?.taskProgress?.tone)}`,
              {
                'has-progress': hasProgress(safeLines[virtualRow.index]),
                'is-task-progress': isTaskProgressLine(safeLines[virtualRow.index]),
              },
            ]"
            :style="{ transform: `translate3d(0, ${virtualRow.start}px, 0)` }"
          >
            <span class="terminal-time">{{ formatTime(safeLines[virtualRow.index]?.time) }}</span>
            <span class="terminal-level">
              <component :is="levelIcon(safeLines[virtualRow.index]?.level)" :size="12" :stroke-width="2.5" />
              {{ levelLabel(safeLines[virtualRow.index]?.level) }}
            </span>
            <span class="terminal-source">{{ safeLines[virtualRow.index]?.source || 'system' }}</span>
            <span v-if="hasProgress(safeLines[virtualRow.index])" class="terminal-progress">{{ safeLines[virtualRow.index]?.progress }}%</span>
            <span v-if="isTaskProgressLine(safeLines[virtualRow.index])" class="terminal-message terminal-inline-progress">
              <span class="terminal-inline-progress-title">
                任务 {{ safeLines[virtualRow.index]?.taskProgress?.shortId || '--------' }}
              </span>
              <span class="terminal-inline-progress-detail">{{ safeLines[virtualRow.index]?.message || '处理中' }}</span>
              <span class="terminal-inline-progress-bar" :style="{ '--inline-progress': `${clampProgress(safeLines[virtualRow.index]?.progress)}%` }">
                <span />
              </span>
              <span class="terminal-inline-progress-state">
                {{ progressToneLabel(safeLines[virtualRow.index]?.taskProgress?.tone) }} · {{ safeLines[virtualRow.index]?.taskProgress?.updatedLabel || '--:--:--' }}
              </span>
            </span>
            <span v-else class="terminal-message">
              <template v-for="(token, tokenIndex) in shellTokens(safeLines[virtualRow.index]?.message)" :key="`${virtualRow.key}-${tokenIndex}`">
                <span :class="`terminal-token is-${token.type}`">{{ token.value }}</span>
              </template>
            </span>
          </div>
        </div>
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
  right: 0;
  left: 0;
  display: grid;
  grid-template-columns: 72px 76px 92px 46px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 5px 14px;
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
  grid-column: 4 / -1;
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.terminal-line.has-progress .terminal-message {
  grid-column: auto;
}

.terminal-line.is-task-progress {
  min-height: 32px;
  background: rgba(14, 20, 25, 0.72);
}

.terminal-line.is-task-progress:hover {
  background: rgba(20, 29, 36, 0.82);
}

.terminal-inline-progress {
  display: grid;
  grid-template-columns: auto minmax(120px, 0.44fr) minmax(180px, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  white-space: nowrap;
}

.terminal-inline-progress-title,
.terminal-inline-progress-state,
.terminal-inline-progress-detail {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-inline-progress-title {
  color: #e5e7eb;
  font-size: 11.5px;
  font-weight: 900;
}

.terminal-inline-progress-state {
  color: #71717a;
  font-size: 10.5px;
  font-weight: 800;
}

.terminal-inline-progress-detail {
  color: #a1a1aa;
  font-size: 11px;
  line-height: 1.2;
}

.terminal-inline-progress-bar {
  position: relative;
  overflow: hidden;
  height: 7px;
  border-radius: 999px;
  background: rgba(63, 63, 70, 0.72);
}

.terminal-inline-progress-bar span {
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--inline-progress, 0%);
  min-width: 8px;
  border-radius: inherit;
  background: linear-gradient(90deg, #22d3ee, #34d399);
  box-shadow: 0 0 16px rgba(34, 211, 238, 0.22);
  transition: width 0.45s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.terminal-line.is-progress-processing .terminal-inline-progress-bar span::after,
.terminal-line.is-progress-waiting .terminal-inline-progress-bar span::after {
  position: absolute;
  inset: 0;
  content: "";
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.28), transparent);
  animation: terminal-progress-sheen 1.45s linear infinite;
}

.terminal-line.is-progress-success .terminal-progress,
.terminal-line.is-progress-success .terminal-inline-progress-title {
  color: #86efac;
}

.terminal-line.is-progress-success .terminal-inline-progress-bar span {
  background: linear-gradient(90deg, #22c55e, #86efac);
}

.terminal-line.is-progress-error .terminal-progress,
.terminal-line.is-progress-error .terminal-inline-progress-title {
  color: #fda4af;
}

.terminal-line.is-progress-error .terminal-inline-progress-bar span {
  background: linear-gradient(90deg, #fb7185, #fda4af);
}

.terminal-line.is-progress-waiting .terminal-progress,
.terminal-line.is-progress-waiting .terminal-inline-progress-title {
  color: #fde68a;
}

.terminal-line.is-progress-waiting .terminal-inline-progress-bar span {
  background: linear-gradient(90deg, #f59e0b, #fde68a);
}

.terminal-line.is-progress-paused .terminal-progress,
.terminal-line.is-progress-paused .terminal-inline-progress-title {
  color: #c4b5fd;
}

.terminal-line.is-progress-paused .terminal-inline-progress-bar span {
  background: linear-gradient(90deg, #8b5cf6, #c4b5fd);
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
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .terminal-inline-progress-bar {
    grid-column: 1 / -1;
    order: 3;
  }

  .terminal-inline-progress-detail {
    display: none;
  }
}
</style>
