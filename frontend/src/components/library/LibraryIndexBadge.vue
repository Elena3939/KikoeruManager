<template>
  <div class="lib-index-badge inline-flex items-center gap-1.5">
    <span
      class="lib-index-chip"
      :class="chipColorClass"
      :title="tooltip"
    >
      <IconDatabase :size="11" :stroke-width="2.4" />
      <span class="font-medium">{{ statusLabel }}</span>
      <span v-if="totalEntriesText" class="lib-index-chip-meta">{{ totalEntriesText }}</span>
    </span>
    <button
      type="button"
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
    </button>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Database as IconDatabase, RefreshCw as IconRefreshCw } from 'lucide-vue-next'
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

const totalEntriesText = computed(() => {
  const total = Number(status.value?.total_entries || 0)
  if (statusName.value !== 'ready' || total <= 0) return ''
  if (total >= 10000) return `· ${(total / 10000).toFixed(1)}w 项`
  return `· ${total} 项`
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
  pollTimer = setInterval(fetchStatus, 2500)
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
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
  border: 1px solid transparent;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-index-chip-meta {
  opacity: 0.7;
  font-weight: 400;
}

.lib-index-chip-idle {
  background: #f1f5f9;
  color: #475569;
  border-color: #e2e8f0;
}

.lib-index-chip-syncing {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
  animation: lib-index-pulse 1.6s ease-in-out infinite;
}

.lib-index-chip-ready {
  background: #ecfdf5;
  color: #047857;
  border-color: #a7f3d0;
}

.lib-index-chip-error {
  background: #fef2f2;
  color: #b91c1c;
  border-color: #fecaca;
}

@keyframes lib-index-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.lib-index-rebuild-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  user-select: none;
}

.lib-index-rebuild-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: #94a3b8;
  background: #f8fafc;
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.12);
}

.lib-index-rebuild-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.lib-index-rebuild-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.lib-index-rebuild-btn.is-busy {
  border-color: #bfdbfe;
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
