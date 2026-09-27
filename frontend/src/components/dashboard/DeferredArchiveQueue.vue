<template>
  <section class="deferred-archive-queue flex min-h-0 flex-col rounded-[14px] border border-slate-200 bg-white p-3.5" data-section="deferred-archive-queue">
    <header class="flex shrink-0 items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2.5">
        <Archive :size="20" :stroke-width="2" class="queue-muted shrink-0 text-slate-700" />
        <div class="min-w-0 leading-tight">
          <h2 class="m-0 text-sm font-bold">延后归档队列</h2>
          <p class="queue-muted m-0 mt-0.5 text-[11.5px] text-slate-500">{{ data.pending_count }} 项待归档 · {{ data.counts_by_status?.waiting_retry || 0 }} 项等待重试</p>
        </div>
      </div>
      <StatefulButton unstyled class="queue-control queue-icon-control" :show-default-icons="false" :disabled="loading" aria-label="刷新归档队列" title="刷新归档队列" @click="refresh">
        <template #prefix="{ state }"><component :is="state === 'success' ? Check : state === 'error' ? CircleAlert : RefreshCw" :size="14" :class="{ 'animate-spin': state === 'loading' || loading }" /></template>
      </StatefulButton>
    </header>
    <div class="my-2 shrink-0">
      <AppDropdown :model-value="status" :options="statusOptions" @update:model-value="changeStatus" />
    </div>
    <div class="relative min-h-0 flex-1 overflow-auto" :aria-busy="loading">
      <p v-if="error" role="alert" class="mb-2 break-words text-xs text-rose-600">{{ error }}</p>
      <p v-if="actionError" role="alert" class="mb-2 break-words text-xs text-rose-600">{{ actionError }}</p>
      <p v-if="!data.items.length" class="queue-muted py-5 text-center text-xs text-slate-500">{{ loading ? '正在读取归档队列…' : error ? '队列读取失败，请刷新重试' : '当前筛选下没有归档作业' }}</p>
      <article v-for="job in data.items" :key="job.job_id" class="queue-item deferred-archive-item mb-2 border border-slate-100 bg-white p-2.5">
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 flex-1 items-start gap-2.5">
            <FileArchive :size="18" :stroke-width="2" class="mt-0.5 shrink-0 text-amber-600" aria-hidden="true" />
            <p class="min-w-0 break-all text-xs font-semibold" :title="job.source_summary.source_path">{{ job.source_summary.filename || job.rjcode || '源压缩包' }}</p>
          </div>
          <span class="queue-status queue-muted shrink-0 text-[11px] text-slate-500">{{ labels[job.status] || job.status }}</span>
        </div>
        <p class="mt-2 text-xs">{{ job.starvation_protected && !job.cancel_requested ? '超时保护执行中' : job.wait_reason }}</p>
        <p v-if="job.last_error" class="mt-1 whitespace-pre-wrap break-all text-xs text-rose-600">{{ job.last_error }}</p>
        <dl class="queue-muted mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px] text-slate-500">
          <dt>源文件</dt><dd>{{ job.source_summary.volume_count }} 卷 · {{ formatSize(job.source_summary.total_bytes) }}</dd>
          <dt>入队时间</dt><dd>{{ formatTime(job.created_at) }}</dd>
          <dt>可执行时间</dt><dd>{{ formatTime(job.available_at) }}</dd>
          <dt>尝试次数</dt><dd>{{ job.attempt_count }}</dd>
        </dl>
        <p v-if="job.starvation_reached && job.status === 'pending'" class="queue-muted mt-2 text-[11px] text-slate-500">已达到超时保护阈值，等待调度</p>
        <div v-if="job.can_cancel || job.can_retry" class="mt-2 flex flex-wrap justify-end gap-2">
          <StatefulButton v-if="job.can_retry" unstyled class="queue-control queue-action-control" @click="() => runAction(job, 'retry')">重新归档</StatefulButton>
          <StatefulButton v-if="job.can_cancel" unstyled class="queue-control queue-action-control" @click="() => runAction(job, 'cancel')">取消归档</StatefulButton>
        </div>
      </article>
    </div>
    <footer class="queue-pager mt-2.5 flex shrink-0 items-center justify-between gap-2 pt-2.5 text-[11px]">
      <span class="queue-muted text-slate-500">共 {{ data.total }} 项</span>
      <div class="flex items-center gap-1">
        <StatefulButton unstyled class="queue-control queue-page-control" :show-default-icons="false" :disabled="loading || page <= 1" aria-label="上一页" title="上一页" @click="() => changePage(page - 1)">
          <template #prefix="{ state }"><component :is="state === 'loading' ? RefreshCw : state === 'success' ? Check : state === 'error' ? CircleAlert : ChevronLeft" :size="12" :class="{ 'animate-spin': state === 'loading' }" /></template>
        </StatefulButton>
        <span class="queue-page-indicator tabular-nums">{{ page }} / {{ pages }}</span>
        <StatefulButton unstyled class="queue-control queue-page-control" :show-default-icons="false" :disabled="loading || page >= pages" aria-label="下一页" title="下一页" @click="() => changePage(page + 1)">
          <template #prefix="{ state }"><component :is="state === 'loading' ? RefreshCw : state === 'success' ? Check : state === 'error' ? CircleAlert : ChevronRight" :size="12" :class="{ 'animate-spin': state === 'loading' }" /></template>
        </StatefulButton>
      </div>
    </footer>
  </section>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { Archive, Check, ChevronLeft, ChevronRight, CircleAlert, FileArchive, RefreshCw } from 'lucide-vue-next'
import { deferredArchiveApi } from '../../api'
import AppDropdown from '../common/AppDropdown.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { useRealtimeEvents } from '../../composables/useRealtimeEvents'
import { showSystemConfirm } from '../../composables/useSystemPrompt'

const labels = { pending: '待归档', processing: '归档中', waiting_retry: '等待重试', failed: '失败', completed: '已完成', cancelled: '已取消' }
const statusOptions = [{ value: '', label: '全部状态' }, ...Object.entries(labels).map(([value, label]) => ({ value, label }))]
const status = ref('')
const page = ref(1)
const pageSize = 5
const data = ref({ items: [], total: 0, pending_count: 0, counts_by_status: {} })
const pages = computed(() => Math.max(1, Math.ceil(data.value.total / pageSize)))
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const realtime = useRealtimeEvents()
let active = false
let timer = null
let unsubscribe = null
let controller = null
let requestId = 0

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}
function formatSize(value) {
  const size = Number(value || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`
  return `${(size / 1024 ** 3).toFixed(2)} GB`
}
async function refresh() {
  const id = ++requestId
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  try {
    const result = await deferredArchiveApi.list({ status: status.value, page: page.value, page_size: pageSize }, { signal: controller.signal })
    if (id !== requestId) return
    data.value = result
    error.value = ''
    if (page.value > pages.value) {
      page.value = pages.value
      return await refresh()
    }
  } catch (cause) {
    if (id !== requestId || cause?.code === 'ERR_CANCELED') return
    error.value = cause?.response?.data?.detail || cause.message || '归档队列读取失败'
    throw cause
  } finally {
    if (id === requestId) loading.value = false
  }
}
function scheduleRefresh() {
  if (!active) return
  clearTimeout(timer)
  timer = setTimeout(() => refresh().catch(() => {}), 350)
}
function changeStatus(value) {
  status.value = value
  page.value = 1
  return refresh().catch(() => {})
}
function changePage(value) {
  page.value = value
  return refresh()
}
async function runAction(job, action) {
  if (action === 'cancel') {
    try {
      await showSystemConfirm({ title: '取消归档', message: `取消 ${job.source_summary.filename} 的归档？源文件将保留在原位置。`, confirmText: '取消归档' })
    } catch { return }
  }
  actionError.value = ''
  try {
    await deferredArchiveApi[action](job.job_id)
  } catch (cause) {
    actionError.value = cause?.response?.data?.detail || cause.message || '归档操作失败'
    scheduleRefresh()
    throw cause
  }
  if (active) await refresh()
}
function activate() {
  if (active) return
  active = true
  realtime.start()
  unsubscribe = realtime.subscribe('archive.queue.changed', scheduleRefresh)
  scheduleRefresh()
}
function deactivate() {
  if (!active) return
  active = false
  clearTimeout(timer)
  unsubscribe?.()
  controller?.abort()
  requestId += 1
  loading.value = false
  realtime.stop()
}
watch(realtime.connected, (connected) => { if (connected) scheduleRefresh() })
onMounted(activate)
onActivated(activate)
onDeactivated(deactivate)
onUnmounted(deactivate)
</script>

<style scoped>
.deferred-archive-queue {
  min-width: 0;
  color: #0f172a;
}
.deferred-archive-queue .deferred-archive-item {
  border-radius: 8px;
}
.deferred-archive-item dd {
  min-width: 0;
  overflow-wrap: anywhere;
}
.queue-pager {
  border-top: 1px solid #f1f5f9;
  background: transparent;
}
.queue-control {
  --stateful-button-icon-size: 14px;
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.queue-icon-control {
  width: 28px;
  height: 28px;
}
.queue-page-control {
  width: 24px;
  height: 24px;
}
.queue-action-control {
  min-height: 28px;
  padding: 4px 8px;
  font-size: 11px;
}
.queue-control:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: #f8fafc;
  border-color: #94a3b8;
}
.queue-control:active:not(:disabled) {
  transform: scale(0.96);
}
.queue-control:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.queue-control :deep(svg) {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.queue-control:hover:not(:disabled) :deep(svg:not(.animate-spin)) {
  transform: rotate(-6deg);
}
.queue-control :deep(.stateful-button__content) {
  gap: 4px;
}
.queue-control :deep(.stateful-button__label:empty) {
  display: none;
}
.queue-page-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid #f1f5f9;
  border-radius: 7px;
  background: #f8fafc;
}
.queue-status {
  padding: 1px 5px;
  border-radius: 5px;
  background: #f1f5f9;
}
</style>
