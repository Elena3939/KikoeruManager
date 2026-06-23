<template>
  <section class="db-shrink">
    <header class="db-shrink-head">
      <div class="card-title">PostgreSQL 维护</div>
      <p class="db-shrink-subtitle">
        压缩 {{ olderThanDays }} 天前操作历史的逐项明细，执行 VACUUM ANALYZE 并重建 pg_trgm 搜索索引。
        操作历史本身一条都不会少。
      </p>
    </header>

    <div class="db-size-grid">
      <div v-for="item in sizeChips" :key="item.label" class="db-size-chip">
        <span class="db-size-label">{{ item.label }}</span>
        <span class="db-size-value">{{ item.value }}</span>
      </div>
    </div>

    <div class="db-performance">
      <div class="db-performance-head">
        <div class="db-performance-title">
          <Gauge :size="14" />
          <span>性能诊断</span>
        </div>
        <div class="db-performance-actions">
          <button
            type="button"
            class="db-btn-ghost"
            :disabled="isPerformanceLoading"
            @click="refreshPerformance"
          >
            <RefreshCw :size="13" :class="{ 'db-spin': isPerformanceLoading }" />
            <span>刷新诊断</span>
          </button>
          <button
            type="button"
            class="db-btn-ghost"
            :disabled="isPerformanceLoading || !pgStatQueryable"
            @click="resetPerformanceStats"
          >
            <RotateCcw :size="13" />
            <span>重置统计</span>
          </button>
        </div>
      </div>

      <div class="db-perf-status" :class="{ 'is-warn': !pgStatQueryable }">
        <CheckCircle2 v-if="pgStatQueryable" :size="13" />
        <AlertCircle v-else :size="13" />
        <span>{{ pgStatLabel }}</span>
      </div>

      <div v-if="performanceError" class="db-status is-error">
        <AlertCircle :size="13" />
        <span>{{ performanceError }}</span>
      </div>

      <div class="db-perf-settings">
        <div v-for="item in performanceSettingChips" :key="item.label" class="db-perf-chip">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <div v-if="slowQueries.length" class="db-perf-list">
        <div class="db-perf-list-title">Top SQL</div>
        <div v-for="item in slowQueries" :key="item.queryid || item.query" class="db-sql-row">
          <div class="db-sql-meta">
            <span>{{ formatDuration(item.total_exec_time_ms) }}</span>
            <span>均值 {{ formatDuration(item.mean_exec_time_ms) }}</span>
            <span>{{ formatNumber(item.calls) }} 次</span>
            <span>命中 {{ Number(item.shared_hit_percent || 0).toFixed(1) }}%</span>
          </div>
          <code>{{ item.query }}</code>
        </div>
      </div>

      <div v-else-if="performance && pgStatQueryable" class="db-perf-empty">
        暂无慢查询统计，重置后跑一轮业务会更准确。
      </div>

      <div v-if="hotTables.length" class="db-perf-tables">
        <div v-for="item in hotTables" :key="item.table" class="db-table-stat">
          <span class="db-table-name">{{ item.table }}</span>
          <span>顺扫 {{ Number(item.seq_scan_percent || 0).toFixed(1) }}%</span>
          <span>死元组 {{ Number(item.dead_tuple_percent || 0).toFixed(1) }}%</span>
          <span>{{ item.total_size_human }}</span>
        </div>
      </div>
    </div>

    <div v-if="estimate" class="db-estimate-line">
      <Sparkles :size="13" class="db-estimate-icon" />
      <span class="db-estimate-text">
        预估可释放 <strong>{{ estimate.estimated_freed_human || '—' }}</strong>
        · 维护后约 {{ estimate.estimated_after_total_human || '—' }}
      </span>
      <span v-if="estimate.compact" class="db-estimate-meta">
        其中 30 天前操作记录可压缩约 {{ estimate.compact.estimated_compactable_total ?? 0 }} 行 / 候选 {{ estimate.compact.candidate_total ?? 0 }} 行
      </span>
    </div>
    <div v-else-if="estimateError" class="db-estimate-line is-error">
      <AlertCircle :size="13" />
      <span>{{ estimateError }}</span>
    </div>

    <div class="db-actions">
      <button
        type="button"
        class="db-btn-primary"
        :disabled="isRunning || isLoading"
        @click="onClickShrink"
      >
        <Loader2 v-if="isRunning" :size="14" class="db-spin" />
        <Sparkles v-else :size="14" />
        <span>{{ primaryLabel }}</span>
      </button>
      <button
        type="button"
        class="db-btn-ghost"
        :disabled="isRunning || isLoading"
        @click="refresh"
      >
        <RefreshCw :size="13" :class="{ 'db-spin': isLoading }" />
        <span>重新估算</span>
      </button>
      <button
        v-if="status?.state === 'done' || status?.state === 'error'"
        type="button"
        class="db-btn-ghost"
        :disabled="isRunning"
        @click="dismissResult"
      >
        <span>关闭结果</span>
      </button>
    </div>

    <div v-if="isRunning" class="db-status is-running">
      <Loader2 :size="13" class="db-spin" />
      <span class="db-status-stage">{{ stageDisplayName }}</span>
      <span class="db-status-detail">{{ status?.stage_label || '正在执行…' }}</span>
    </div>

    <div v-else-if="status?.state === 'done'" class="db-status is-done">
      <CheckCircle2 :size="13" />
      <span>
        维护完成，释放
        <strong>{{ status.freed_human }}</strong>
        · {{ status.before?.total_human || '—' }} → {{ status.after?.total_human || '—' }}
        · 耗时 {{ formatDuration(status.duration_ms) }}
        <template v-if="status.compact_result?.updated">
          · 压缩 {{ status.compact_result.updated }} 行
        </template>
      </span>
    </div>

    <div v-else-if="status?.state === 'error'" class="db-status is-error">
      <AlertCircle :size="13" />
      <span>维护失败：{{ status.error || '未知错误' }}</span>
    </div>

    <p class="db-shrink-tip">
      VACUUM ANALYZE 会刷新 PostgreSQL 统计信息；REINDEX 会短暂占用搜索索引。建议在没有重任务运行时点击。
    </p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Sparkles, RefreshCw, Loader2, CheckCircle2, AlertCircle, Gauge, RotateCcw } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { databaseMaintenanceApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'
import { useRealtimeEvents } from '../../composables/useRealtimeEvents'

const olderThanDays = 30
const minDetailBytes = 8 * 1024
const SHRINK_FALLBACK_POLL_MS = 30000

const realtimeEvents = useRealtimeEvents()
const estimate = ref(null)
const estimateError = ref('')
const status = ref(null)
const performance = ref(null)
const performanceError = ref('')
const isLoading = ref(false)
const isPerformanceLoading = ref(false)
let pollTimer = null
let visibilityBound = false

const sizes = computed(() => {
  // running / done / error 阶段优先显示状态机里的现场尺寸；idle 阶段用 estimate 接口的快照
  const fromStatus = status.value
  if (fromStatus?.state === 'running' || fromStatus?.state === 'done' || fromStatus?.state === 'error') {
    return fromStatus.after || fromStatus.before || estimate.value
  }
  return estimate.value
})

const isRunning = computed(() => status.value?.state === 'running')

const primaryLabel = computed(() => {
  if (isRunning.value) return '维护中...'
  return '立即维护'
})

const sizeChips = computed(() => [
  { label: '数据库', value: formatHuman(sizes.value?.database_size_bytes ?? sizes.value?.total_size_bytes) },
  { label: '操作历史', value: formatHuman(sizes.value?.activity_logs?.total_size_bytes) },
  { label: '库存索引', value: formatHuman(sizes.value?.library_index_entries?.total_size_bytes) },
  { label: 'trigram 索引', value: formatHuman(sizes.value?.index_size_bytes) }
])

const pgStatStatus = computed(() => performance.value?.pg_stat_statements || {})
const pgStatQueryable = computed(() => Boolean(pgStatStatus.value?.queryable))
const pgStatLabel = computed(() => {
  const status = pgStatStatus.value
  if (status?.queryable) return 'pg_stat_statements 已启用，正在记录 Top SQL'
  if (status?.installed && !status?.preloaded) return 'pg_stat_statements 已安装但未预加载，重启 PostgreSQL 后生效'
  if (status?.installed) return `pg_stat_statements 暂不可查询：${status.error || '需要检查权限或重启'}`
  return 'pg_stat_statements 未启用，无法展示真实 Top SQL'
})

const performanceSettingChips = computed(() => {
  const settings = performance.value?.settings_by_name || {}
  const getSetting = (name) => {
    const item = settings[name]
    if (!item) return '—'
    if (item.pretty_value) return item.pretty_value
    return item.unit ? `${item.setting}${item.unit}` : item.setting
  }
  return [
    { label: 'shared_buffers', value: getSetting('shared_buffers') },
    { label: 'effective_cache_size', value: getSetting('effective_cache_size') },
    { label: 'work_mem', value: getSetting('work_mem') },
    { label: 'max_wal_size', value: getSetting('max_wal_size') },
    { label: 'checkpoint', value: getSetting('checkpoint_timeout') },
    { label: 'statement_timeout', value: getSetting('statement_timeout') }
  ]
})

const slowQueries = computed(() => (performance.value?.slow_queries || []).slice(0, 5))
const hotTables = computed(() => {
  const rows = performance.value?.table_stats || []
  return rows
    .filter((item) => Number(item.total_size_bytes || 0) > 0 || Number(item.seq_scan || 0) > 0 || Number(item.n_dead_tup || 0) > 0)
    .slice(0, 6)
})

const stageDisplayName = computed(() => {
  const stage = status.value?.stage
  if (stage === 'compact') return '阶段 1/3 · 压缩操作记录'
  if (stage === 'vacuum_analyze') return '阶段 2/3 · VACUUM ANALYZE'
  if (stage === 'reindex') return '阶段 3/3 · REINDEX pg_trgm'
  if (stage === 'finalize') return '收尾 · 采集结果'
  return '准备中…'
})

function formatHuman(bytes) {
  const n = Number(bytes ?? 0)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return idx === 0 ? `${Math.round(value)} ${units[idx]}` : `${value.toFixed(2)} ${units[idx]}`
}

function formatDuration(ms) {
  const n = Number(ms ?? 0)
  if (!Number.isFinite(n) || n <= 0) return '0ms'
  if (n < 1000) return `${Math.round(n)}ms`
  const s = n / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s - m * 60)
  return `${m}m ${rest}s`
}

function formatNumber(value) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return '0'
  return new Intl.NumberFormat('zh-CN').format(Math.round(n))
}

async function refresh() {
  if (isLoading.value) return
  isLoading.value = true
  estimateError.value = ''
  try {
    const data = await databaseMaintenanceApi.estimate({
      older_than_days: olderThanDays,
      min_detail_bytes: minDetailBytes
    })
    estimate.value = data
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '估算失败'
    estimateError.value = String(detail)
  } finally {
    isLoading.value = false
  }
}

async function refreshPerformance() {
  if (isPerformanceLoading.value) return
  isPerformanceLoading.value = true
  performanceError.value = ''
  try {
    performance.value = await databaseMaintenanceApi.performance({ limit: 10 })
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '性能诊断读取失败'
    performanceError.value = String(detail)
  } finally {
    isPerformanceLoading.value = false
  }
}

async function resetPerformanceStats() {
  if (isPerformanceLoading.value) return
  try {
    const result = await databaseMaintenanceApi.resetPgStatStatements()
    if (result?.ok) {
      ElMessage.success('pg_stat_statements 统计已重置')
      await refreshPerformance()
      return
    }
    ElMessage.warning(result?.error || 'pg_stat_statements 当前不可重置')
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '重置失败'
    ElMessage.error(`重置 pg_stat_statements 失败：${detail}`)
  }
}

async function pullStatus() {
  try {
    const data = await databaseMaintenanceApi.shrinkStatus()
    status.value = data
    if (data?.state !== 'running' && pollTimer) {
      stopPolling()
      // 任务结束：刷新 estimate 让卡片回到最新尺寸
      if (data?.state === 'done' || data?.state === 'error') {
        refresh()
      }
    }
  } catch (e) {
    // 轮询失败不打扰，下一轮再试
    console.warn('[数据库维护] 状态轮询失败', e)
  }
}

function startPolling() {
  if (typeof document !== 'undefined' && document.hidden) return
  stopPolling()
  pollTimer = setTimeout(() => {
    pollTimer = null
    if (typeof document !== 'undefined' && document.hidden) {
      stopPolling()
      return
    }
    if (!isRunning.value) return
    if (!realtimeEvents.connected.value) {
      pullStatus()
      return
    }
    startPolling()
  }, SHRINK_FALLBACK_POLL_MS)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function onClickShrink() {
  if (isRunning.value) return
  const freedHuman = estimate.value?.estimated_freed_human || '若干 MB'
  const totalHuman = estimate.value?.total_human || '当前体积'
  try {
    await showSystemConfirm({
      title: '确认要立即执行 PostgreSQL 维护吗？',
      tone: 'warning',
      message: '维护过程不会删除任何操作记录，只压缩旧明细、执行 VACUUM ANALYZE 并重建 pg_trgm 索引。',
      details: [
        { label: '当前体积', value: totalHuman },
        { label: '预估释放', value: freedHuman },
        { label: '裁剪窗口', value: `${olderThanDays} 天前` }
      ],
      description: '建议在没有任务运行时点击；大库 REINDEX 期间搜索索引会有短暂维护窗口。',
      confirmText: '立即维护',
      cancelText: '再等等'
    })
  } catch {
    return
  }

  try {
    const result = await databaseMaintenanceApi.startShrink({
      older_than_days: olderThanDays,
      min_detail_bytes: minDetailBytes
    })
    if (result?.already_running) {
      ElMessage.info('数据库维护任务已经在运行')
    }
    status.value = result?.status || null
    startPolling()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(`启动数据库维护失败：${detail}`)
  }
}

async function dismissResult() {
  try {
    const data = await databaseMaintenanceApi.shrinkReset()
    status.value = data
  } catch (e) {
    console.warn('[数据库维护] 关闭结果失败', e)
    status.value = null
  }
}

async function handleVisibilityChange() {
  if (typeof document === 'undefined' || document.hidden) return
  await pullStatus()
  if (isRunning.value) startPolling()
}

function bindVisibilityChange() {
  if (visibilityBound || typeof document === 'undefined') return
  visibilityBound = true
  document.addEventListener('visibilitychange', handleVisibilityChange)
}

function unbindVisibilityChange() {
  if (!visibilityBound || typeof document === 'undefined') return
  visibilityBound = false
  document.removeEventListener('visibilitychange', handleVisibilityChange)
}

function handleDatabaseShrinkRealtimeEvent(event) {
  const detail = event?.detail || {}
  if (detail.type !== 'maintenance.database_shrink.changed') return
  const payload = detail.payload || {}
  status.value = payload
  if (payload.state === 'running') {
    startPolling()
    return
  }
  stopPolling()
  if (payload.state === 'done' || payload.state === 'error') {
    refresh()
    refreshPerformance()
  }
}

onMounted(async () => {
  bindVisibilityChange()
  window.addEventListener('kikoerumanager:events:message', handleDatabaseShrinkRealtimeEvent)
  // 先看后端有没有"正在跑"的任务（比如刚刷新页面）
  try {
    const pending = await databaseMaintenanceApi.shrinkStatus()
    status.value = pending
    if (pending?.state === 'running') {
      startPolling()
    }
  } catch (e) {
    console.warn('[数据库维护] 初始状态读取失败', e)
  }
  await refresh()
  await refreshPerformance()
})

onBeforeUnmount(() => {
  window.removeEventListener('kikoerumanager:events:message', handleDatabaseShrinkRealtimeEvent)
  unbindVisibilityChange()
  stopPolling()
})
</script>

<style scoped>
/* 整体容器：透明，与维护与清理面板里其他卡片（密码库清理 / 压缩包清理）保持同一种语言 */
.db-shrink {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.db-shrink-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 标题对齐其他设置卡片的 .card-title 样式 */
.db-shrink-head .card-title {
  margin: 0;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.db-shrink-subtitle {
  margin: 0;
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.6;
}

.db-size-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  min-width: 0;
}

@media (max-width: 1100px) {
  .db-size-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.db-size-chip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 11px 14px;
  border-radius: 10px;
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  transition: border-color 0.18s ease;
}

.db-size-chip:hover {
  border-color: var(--set-border-strong);
}

.db-size-label {
  font-size: 11.5px;
  color: var(--set-text-muted);
}

.db-size-value {
  min-width: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--set-text-strong);
  letter-spacing: -0.1px;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.db-performance {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
  padding: 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-surface);
}

.db-performance-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.db-performance-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 600;
}

.db-performance-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.db-perf-status {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--set-success-text);
  font-size: 12px;
  line-height: 1.55;
}

.db-perf-status.is-warn {
  color: var(--set-warning-text, #a16207);
}

.db-perf-settings {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

@media (max-width: 1100px) {
  .db-perf-settings { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.db-perf-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
  color: var(--set-text-muted);
  font-size: 11.5px;
}

.db-perf-chip strong {
  min-width: 0;
  color: var(--set-text-strong);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.db-perf-list,
.db-perf-tables {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.db-perf-list-title {
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-weight: 600;
}

.db-sql-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
}

.db-sql-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.db-sql-row code {
  display: block;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  color: var(--set-text);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.db-perf-empty {
  color: var(--set-text-muted);
  font-size: 12px;
}

.db-table-stat {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) repeat(3, auto);
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 7px 0;
  border-top: 1px dashed var(--set-border);
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.db-table-name {
  min-width: 0;
  color: var(--set-text-strong);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .db-perf-settings { grid-template-columns: 1fr; }
  .db-size-grid { grid-template-columns: 1fr; }
  .db-table-stat { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
}

/* 预估行：单行小字 + Sparkles，不再用大块渐变背景 */
.db-estimate-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12.5px;
  color: var(--set-text);
  line-height: 1.55;
}

.db-estimate-icon {
  color: var(--set-success-text);
  flex-shrink: 0;
}

.db-estimate-text strong {
  color: var(--set-success-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.db-estimate-meta {
  color: var(--set-text-muted);
  font-size: 11.5px;
}

.db-estimate-line.is-error {
  color: var(--set-danger-text);
}

.db-estimate-line.is-error svg {
  color: var(--set-danger-text);
}

/* 操作按钮区 */
.db-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.db-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: 10px;
  border: 1px solid var(--set-primary-border);
  cursor: pointer;
  background: var(--set-primary-bg);
  color: var(--set-primary-text);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.1px;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.db-btn-primary :deep(svg) {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.db-btn-primary:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: var(--set-primary-bg-hover);
  box-shadow: none;
}

.db-btn-primary:hover:not(:disabled) :deep(svg) {
  transform: scale(1.1) rotate(-6deg);
}

.db-btn-primary:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
}

.db-btn-primary:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.db-btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 9px;
  background: var(--set-surface);
  color: var(--set-text);
  border: 1px solid var(--set-border);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.db-btn-ghost:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.db-btn-ghost:hover:not(:disabled) svg:not(.db-spin) {
  transform: rotate(-360deg);
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.db-btn-ghost:active:not(:disabled) {
  transform: scale(0.97);
}

.db-btn-ghost:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.db-spin {
  animation: db-spin 0.8s linear infinite;
}

@keyframes db-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 状态行：单行小字 + 图标，不要框 */
.db-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  line-height: 1.55;
}

.db-status svg {
  flex-shrink: 0;
}

.db-status.is-running {
  color: var(--set-text-strong);
}

.db-status.is-running svg {
  color: var(--set-text-muted);
}

.db-status .db-status-stage {
  font-weight: 600;
}

.db-status .db-status-detail {
  color: var(--set-text-muted);
}

.db-status.is-done {
  color: var(--set-success-text);
}

.db-status.is-done svg {
  color: #10b981;
}

.db-status.is-done strong {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.db-status.is-error {
  color: var(--set-danger-text);
}

.db-status.is-error svg {
  color: #dc2626;
}

/* 底部提示：仅小灰字 */
.db-shrink-tip {
  margin: 0;
  color: var(--set-text-subtle);
  font-size: 11.5px;
  line-height: 1.6;
}
</style>
