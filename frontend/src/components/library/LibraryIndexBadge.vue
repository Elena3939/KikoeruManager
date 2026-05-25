<template>
  <div class="lib-index-badge inline-flex items-center gap-1.5">
    <Badge
      variant="outline"
      class="lib-index-chip"
      :class="chipColorClass"
      :title="tooltip"
    >
      <svg
        v-if="statusName === 'syncing'"
        class="lib-index-spinner"
        viewBox="0 0 16 16"
        aria-hidden="true"
      >
        <circle class="lib-index-spinner-track" cx="8" cy="8" r="6" />
        <circle class="lib-index-spinner-arc" cx="8" cy="8" r="6" />
      </svg>
      <IconDatabase v-else :size="11" :stroke-width="2.4" />
      <span class="font-medium">{{ statusLabel }}</span>
      <span v-if="totalEntriesText" class="lib-index-chip-meta">{{ totalEntriesText }}</span>
    </Badge>
    <Badge
      as="button"
      type="button"
      variant="outline"
      class="lib-index-rebuild-btn"
      :class="{ 'is-busy': busy }"
      :disabled="busy || !libraryId"
      :title="rebuildTooltip"
      @click="onRebuild"
    >
      <IconRefreshCw
        :size="12"
        :stroke-width="2.4"
        :class="['lib-index-rebuild-icon', { 'animate-spin': busy }]"
      />
      <span>{{ busy ? '同步中' : '重建索引' }}</span>
    </Badge>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Database as IconDatabase, RefreshCw as IconRefreshCw } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { libraryApi } from '../../api'
import { showSystemAlert, showSystemConfirm } from '../../composables/useSystemPrompt'

const props = defineProps({
  library: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['status-change'])

const status = ref(null)
const rebuilding = ref(false)
let pollTimer = null
let lastFetchedFor = null

const libraryId = computed(() => (props.library?.id ? String(props.library.id) : ''))
const libraryName = computed(() => props.library?.name || libraryId.value || '当前库存')

const STATUS_LABELS = {
  idle: '索引未建',
  syncing: '正在同步',
  ready: '索引就绪',
  error: '索引出错',
}

const STATUS_CLASSES = {
  idle: 'lib-index-chip-idle',
  syncing: 'lib-index-chip-syncing',
  ready: 'lib-index-chip-ready',
  error: 'lib-index-chip-error',
}

const statusName = computed(() => {
  const raw = status.value?.status || 'idle'
  return STATUS_LABELS[raw] ? raw : 'idle'
})

const statusLabel = computed(() => STATUS_LABELS[statusName.value])
const chipColorClass = computed(() => STATUS_CLASSES[statusName.value])

const busy = computed(() => rebuilding.value || statusName.value === 'syncing')

// syncing 期间 total_entries 表示已扫描数，ready 后表示总数
const totalEntriesText = computed(() => {
  const total = Number(status.value?.total_entries || 0)
  const name = statusName.value
  if (name === 'ready' && total > 0) {
    if (total >= 10000) return `· ${(total / 10000).toFixed(1)}w 项`
    return `· ${total.toLocaleString()} 项`
  }
  if (name === 'syncing' && total > 0) {
    if (total >= 10000) return `· ${(total / 10000).toFixed(1)}w 项`
    return `· ${total.toLocaleString()} 项`
  }
  return ''
})

const tooltip = computed(() => {
  const raw = status.value
  if (!raw) return '索引尚未建立，建议手动触发重建以获得 ms 级 RJ 搜索'
  const parts = []
  parts.push(`状态：${STATUS_LABELS[statusName.value]}`)
  if (raw.total_entries) parts.push(`已索引 ${raw.total_entries} 项`)
  if (raw.last_full_scan_at) {
    const scanned = new Date(Number(raw.last_full_scan_at))
    if (!Number.isNaN(scanned.getTime())) {
      parts.push(`上次重建：${scanned.toLocaleString()}`)
    }
  }
  if (raw.error) parts.push(`错误：${raw.error}`)
  return parts.join('\n')
})

const rebuildTooltip = computed(() => {
  if (!libraryId.value) return '请选择库存后再触发重建'
  if (busy.value) return `${libraryName.value} 正在同步中，请稍候`
  return `重建 ${libraryName.value} 的搜索索引（远程库可能耗时数分钟）`
})

watch(libraryId, (id) => {
  if (!id) {
    status.value = null
    stopPolling()
    return
  }
  if (id === lastFetchedFor) return
  lastFetchedFor = id
  fetchStatus()
}, { immediate: true })

onBeforeUnmount(() => {
  stopPolling()
})

async function fetchStatus() {
  const id = libraryId.value
  if (!id) return
  try {
    const data = await libraryApi.getIndexStatus(id)
    status.value = data
    emit('status-change', data)
    if (data?.status === 'syncing') {
      startPolling()
    } else {
      stopPolling()
    }
  } catch (error) {
    // 静默：状态查询失败不应该影响页面其他功能
    status.value = { status: 'idle', error: error?.message || String(error) }
  }
}

function startPolling() {
  stopPolling()
  // syncing 期间 1.2s 一次轮询，让圆环还能看到数字补跳增长。
  // 后端每 0.5s 上报一次，前后端一起构成“近似实时”进度。
  pollTimer = setInterval(fetchStatus, 1200)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function onRebuild() {
  const id = libraryId.value
  if (!id) return
  if (busy.value) return

  const libraryType = props.library?.type || 'local'
  const isRemote = libraryType === 'synology_filestation'

  try {
    await showSystemConfirm({
      title: '重建搜索索引',
      message: isRemote
        ? `即将对群晖远程库存「${libraryName.value}」做一次全量扫描，可能耗时数分钟到数十分钟（取决于库存大小）。\n后台 task 跑，可以关闭对话框继续操作；通过状态徽章观察进度。`
        : `即将对本地库存「${libraryName.value}」做一次全量扫描，几秒到几分钟。\n本地 thread 跑，扫描期间页面可正常使用。`,
      confirmText: '开始重建',
      cancelText: '取消',
    })
  } catch {
    return // 用户取消
  }

  rebuilding.value = true
  try {
    const data = await libraryApi.rebuildIndex(id)
    status.value = data
    emit('status-change', data)
    startPolling()
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || String(error)
    showSystemAlert({
      title: '触发重建失败',
      message: detail,
    })
  } finally {
    rebuilding.value = false
  }
}

defineExpose({ refresh: fetchStatus })
</script>

<style scoped>
.lib-index-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  line-height: 16px;
  letter-spacing: 0;
  white-space: nowrap;
  border: 1px solid transparent;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-index-chip-meta {
  opacity: 0.72;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}

.lib-index-chip-idle {
  background: #f8fafc;
  color: #475569;
  border-color: rgba(148, 163, 184, 0.45);
  box-shadow: none;
}

.lib-index-chip-syncing {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: rgba(96, 165, 250, 0.5);
  box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.24);
  animation: lib-index-pulse 1.8s ease-in-out infinite;
}

.lib-index-chip-ready {
  background: #ecfdf5;
  color: #047857;
  border-color: rgba(110, 231, 183, 0.6);
  box-shadow: none;
}

.lib-index-chip-error {
  background: #fef2f2;
  color: #b91c1c;
  border-color: rgba(248, 113, 113, 0.55);
  box-shadow: none;
}

@keyframes lib-index-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.24);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0);
  }
}

/* 圆环 spinner：双层 SVG（背景轨道 + 旋转弧） */
.lib-index-spinner {
  width: 11px;
  height: 11px;
  flex-shrink: 0;
  animation: lib-index-spinner-rotate 1.4s linear infinite;
}

.lib-index-spinner-track {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  opacity: 0.22;
}

.lib-index-spinner-arc {
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-dasharray: 14 28;
  stroke-dashoffset: 0;
  animation: lib-index-spinner-dash 1.4s ease-in-out infinite;
}

@keyframes lib-index-spinner-rotate {
  to { transform: rotate(360deg); }
}

@keyframes lib-index-spinner-dash {
  0% {
    stroke-dasharray: 4 36;
    stroke-dashoffset: 0;
  }
  50% {
    stroke-dasharray: 24 16;
    stroke-dashoffset: -8;
  }
  100% {
    stroke-dasharray: 4 36;
    stroke-dashoffset: -36;
  }
}

.lib-index-rebuild-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  line-height: 16px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid rgba(96, 165, 250, 0.5);
  box-shadow: none;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  user-select: none;
}

.lib-index-rebuild-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(59, 130, 246, 0.7);
  background: #dbeafe;
  box-shadow: none;
}

.lib-index-rebuild-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.lib-index-rebuild-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.lib-index-rebuild-btn.is-busy {
  border-color: rgba(96, 165, 250, 0.5);
  background: #eff6ff;
  color: #1d4ed8;
}

.lib-index-rebuild-icon {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-index-rebuild-btn:hover:not(:disabled) .lib-index-rebuild-icon {
  transform: rotate(90deg);
}
</style>
