<template>
  <section class="scan-status" :class="{ 'has-open-details': expanded }" aria-label="输入扫描结果">
    <div class="scan-status-line" role="status">
      <span class="scan-status-heading"><component :is="scanning ? ScanLine : CheckCheck" :size="14" />{{ snapshot.message }}</span>
      <span>发现 <b>{{ snapshot.discovered_groups || 0 }}</b> 组</span>
      <span>已交接 <b>{{ snapshot.found_count || 0 }}</b></span>
      <span v-if="snapshot.pending_count">待处理 <b>{{ snapshot.pending_count }}</b></span>
      <span v-if="snapshot.counts?.routed">转入其他流程 <b>{{ snapshot.counts.routed }}</b></span>
      <span v-if="snapshot.counts?.skipped">已跳过 <b>{{ snapshot.counts.skipped }}</b></span>
      <span v-if="snapshot.counts?.failed" class="scan-error">失败 <b>{{ snapshot.counts.failed }}</b></span>
      <button type="button" class="scan-action" :aria-expanded="expanded" aria-controls="scan-details-panel" @click="toggleDetails">
        <ListFilter :size="13" /><span>扫描明细</span><ChevronDown :size="12" :class="{ expanded }" />
      </button>
      <StatefulButton v-if="scanning && !snapshot.cancel_requested" unstyled :show-default-icons="false" class="scan-action" @click="onCancel">
        <Square :size="12" />取消扫描
      </StatefulButton>
    </div>
    <div v-if="skipSummary.length" class="scan-skip-summary">
      <span v-for="item in skipSummary" :key="item.key">{{ item.label }} {{ item.count }} 组</span>
    </div>
    <div id="scan-details-panel" class="scan-details-collapse" :class="{ 'is-open': expanded }" :aria-hidden="!expanded">
      <div class="scan-details">
        <div v-if="error" class="scan-error">{{ error }}</div>
        <div v-if="loading && !candidates.length" class="scan-details-loading" role="status">
          <LoaderCircle :size="16" class="scan-spinner" />正在加载扫描明细
        </div>
        <template v-else>
          <div v-for="item in candidates" :key="item.id" class="scan-detail-row">
            <span class="scan-file" :title="item.source_path">{{ item.source_path }}</span>
            <span class="scan-detail-state" :class="candidateTone(item)">{{ describeCandidate(item) }}</span>
          </div>
          <div v-if="!candidates.length && !error" class="scan-details-empty">暂无候选记录</div>
          <StatefulButton v-if="hasMore" unstyled :show-default-icons="false" class="scan-action scan-more" :disabled="loading" @click="loadMore">
            <LoaderCircle v-if="loading" :size="14" class="scan-spinner" />{{ loading ? '加载中' : '加载更多' }}
          </StatefulButton>
        </template>
        <div v-for="(item, index) in snapshot.coverage?.errors || []" :key="index" class="scan-error">{{ item.path }} {{ item.reason }}</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { CheckCheck, ChevronDown, ListFilter, LoaderCircle, ScanLine, Square } from 'lucide-vue-next'
import StatefulButton from '../ui/stateful-button.vue'
import { scanApi } from '../../api'
import { describeCandidate, skipReasonLabel } from './inputScanPresentation'

const props = defineProps({
  snapshot: { type: Object, required: true },
  scanning: { type: Boolean, default: false },
  onCancel: { type: Function, required: true },
})
const expanded = ref(false)
const candidates = ref([])
const loading = ref(false)
const error = ref('')
const hasMore = ref(false)
let generation = 0
onUnmounted(() => { generation += 1 })
const skipSummary = computed(() => Object.entries(props.snapshot.skip_counts || {}).map(([key, count]) => ({
  key, count, label: skipReasonLabel(key),
})))

function candidateTone(item) {
  if (item.state === 'submitted') return 'is-submitted'
  if (['waiting_stable', 'ready', 'preflight', 'discovered'].includes(item.state)) return 'is-waiting'
  if (item.state === 'failed') return 'is-failed'
  return ''
}

async function loadMore() {
  if (loading.value) return
  const current = generation
  loading.value = true
  error.value = ''
  try {
    const rows = await scanApi.candidates(props.snapshot.scan_id, candidates.value.at(-1)?.id)
    if (current !== generation) return
    candidates.value.push(...rows)
    hasMore.value = rows.length === 100
  } catch (cause) {
    if (current === generation) error.value = cause.response?.data?.detail || '扫描明细加载失败'
  } finally {
    if (current === generation) loading.value = false
  }
}
function toggleDetails() {
  expanded.value = !expanded.value
  if (expanded.value && !candidates.value.length) loadMore()
}
watch(() => [props.snapshot.scan_id, props.snapshot.revision], () => {
  generation += 1
  candidates.value = []
  loading.value = false
  hasMore.value = false
  error.value = ''
  if (expanded.value) loadMore()
})
</script>

<style scoped>
.scan-status { position: relative; z-index: 1; margin-bottom: 10px; color: #64748b; font-size: 12px; min-width: 0; }
.scan-status.has-open-details { z-index: 20; }
.scan-status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; min-height: 28px; }
.scan-status-heading { display: inline-flex; align-items: center; gap: 6px; color: #334155; font-weight: 600; }
.scan-status b { font-weight: 600; font-variant-numeric: tabular-nums; }
.scan-action { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-height: 28px; padding: 3px 9px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #475569; font: inherit; cursor: pointer; transition: background-color .2s, border-color .2s, color .2s; }
.scan-action:hover { border-color: #cbd5e1; background: #f8fafc; color: #0f172a; }
.scan-action:disabled { cursor: wait; opacity: .7; }
.scan-action .lucide-chevron-down { transition: transform .2s ease; }
.scan-action .expanded { transform: rotate(180deg); }
.scan-skip-summary { display: flex; flex-wrap: wrap; gap: 4px 16px; padding: 2px 0 2px 20px; }
.scan-details-collapse { position: absolute; top: calc(100% - 2px); left: 0; z-index: 30; width: min(720px, calc(100vw - 32px)); visibility: hidden; opacity: 0; pointer-events: none; transform: translateY(-6px) scale(.99); transform-origin: top left; transition: opacity .18s ease, transform .22s ease, visibility .22s; }
.scan-details-collapse.is-open { visibility: visible; opacity: 1; pointer-events: auto; transform: translateY(0) scale(1); transition-delay: 0s; }
.scan-details { max-height: min(320px, 55vh); overflow: auto; border: 1px solid rgba(203, 213, 225, .8); border-radius: 8px; background: rgba(255, 255, 255, .88); box-shadow: 0 12px 32px rgba(15, 23, 42, .16); backdrop-filter: blur(16px) saturate(1.25); -webkit-backdrop-filter: blur(16px) saturate(1.25); }
.scan-detail-row { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 7px 4px; border-bottom: 1px solid #f1f5f9; }
.scan-file { min-width: 0; overflow-wrap: anywhere; color: #334155; }
.scan-detail-state { flex-shrink: 0; max-width: 50%; overflow-wrap: anywhere; font-weight: 500; }
.scan-detail-state.is-submitted { color: #15803d; }
.scan-detail-state.is-waiting { color: #a16207; }
.scan-detail-state.is-failed { color: #be123c; }
.scan-details-empty { padding: 8px 4px; }
.scan-details-loading { display: flex; align-items: center; gap: 8px; min-height: 64px; padding: 8px 4px; }
.scan-spinner { flex: none; animation: scan-spin 1s linear infinite; }
.scan-more { margin: 8px 4px; }
@keyframes scan-spin { to { transform: rotate(360deg); } }
.scan-error { color: #e11d48; overflow-wrap: anywhere; }
:global(html.kikoerumanager-dark .scan-status) { color: var(--km-dark-text-secondary, #a1a1aa); }
:global(html.kikoerumanager-dark .scan-status-heading),
:global(html.kikoerumanager-dark .scan-file) { color: var(--km-dark-text-primary, #e4e4e7); }
:global(html.kikoerumanager-dark .scan-action) { color: #d4d4d8; background: #27272a; border-color: #52525b; }
:global(html.kikoerumanager-dark .scan-action:hover) { color: #fafafa; background: #3f3f46; }
:global(html.kikoerumanager-dark .scan-detail-state.is-submitted) { color: #4ade80; }
:global(html.kikoerumanager-dark .scan-detail-state.is-waiting) { color: #fbbf24; }
:global(html.kikoerumanager-dark .scan-detail-state.is-failed) { color: #fb7185; }
:global(html.kikoerumanager-dark .scan-details) { border-color: rgba(255,255,255,.14); background: rgba(24, 24, 27, .88); box-shadow: 0 12px 32px rgba(0, 0, 0, .38); }
:global(html.kikoerumanager-dark .scan-detail-row) { border-color: rgba(255,255,255,0.1); }
@media (prefers-reduced-motion: reduce) { .scan-details-collapse { transition: none; } }
@media (max-width: 640px) { .scan-details-collapse { width: min(520px, calc(100vw - 24px)); } .scan-detail-row { flex-direction: column; gap: 3px; } .scan-detail-state { max-width: 100%; } .scan-status-line { gap: 6px 12px; } }
</style>
