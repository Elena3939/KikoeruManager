<template>
  <section class="db-shrink">
    <header class="db-shrink-head">
      <div class="card-title">数据库瘦身</div>
      <p class="db-shrink-subtitle">
        压缩 {{ olderThanDays }} 天前操作历史的逐项明细、合并 WAL 草稿、VACUUM 回收主库碎片页。
        操作历史本身一条都不会少。
      </p>
    </header>

    <div class="db-size-grid">
      <div v-for="item in sizeChips" :key="item.label" class="db-size-chip">
        <span class="db-size-label">{{ item.label }}</span>
        <span class="db-size-value">{{ item.value }}</span>
      </div>
    </div>

    <div v-if="estimate" class="db-estimate-line">
      <Sparkles :size="13" class="db-estimate-icon" />
      <span class="db-estimate-text">
        预估可释放 <strong>{{ estimate.estimated_freed_human || '—' }}</strong>
        · 瘦身后约 {{ estimate.estimated_after_total_human || '—' }}
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
        瘦身完成，释放
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
      <span>瘦身失败：{{ status.error || '未知错误' }}</span>
    </div>

    <p class="db-shrink-tip">
      VACUUM 阶段会独占数据库写锁。SSD 通常 30 秒 ~ 1 分钟，HDD / 群晖 Docker 预计 3 ~ 10 分钟。
      建议在没有任务运行时点击。
    </p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Sparkles, RefreshCw, Loader2, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { databaseMaintenanceApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'

const olderThanDays = 30
const minDetailBytes = 8 * 1024

const estimate = ref(null)
const estimateError = ref('')
const status = ref(null)
const isLoading = ref(false)
let pollTimer = null

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
  if (isRunning.value) return '正在瘦身…'
  return '立即瘦身'
})

const sizeChips = computed(() => [
  { label: '主库 cache.db', value: formatHuman(sizes.value?.main_size_bytes) },
  { label: 'WAL 草稿', value: formatHuman(sizes.value?.wal_size_bytes) },
  { label: '共享内存', value: formatHuman(sizes.value?.shm_size_bytes) },
  { label: '总计', value: formatHuman(sizes.value?.total_size_bytes) }
])

const stageDisplayName = computed(() => {
  const stage = status.value?.stage
  if (stage === 'compact') return '阶段 1/3 · 压缩操作记录'
  if (stage === 'checkpoint') return '阶段 2/3 · 合并 WAL'
  if (stage === 'vacuum') return '阶段 3/3 · VACUUM 重写主库'
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
    console.warn('[数据库瘦身] 状态轮询失败', e)
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pullStatus, 1500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function onClickShrink() {
  if (isRunning.value) return
  const freedHuman = estimate.value?.estimated_freed_human || '若干 MB'
  const totalHuman = estimate.value?.total_human || '当前体积'
  try {
    await showSystemConfirm({
      title: '确认要立即瘦身数据库吗？',
      tone: 'warning',
      message: '瘦身过程不会删除任何操作记录，只压缩 30 天前的逐项明细 + 合并 WAL + VACUUM。',
      details: [
        { label: '当前体积', value: totalHuman },
        { label: '预估释放', value: freedHuman },
        { label: '裁剪窗口', value: `${olderThanDays} 天前` }
      ],
      description: 'VACUUM 阶段会独占数据库写锁，其它写请求会被排队最长 30 秒。建议在没有任务运行时点击。',
      confirmText: '立即瘦身',
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
      ElMessage.info('瘦身任务已经在运行')
    }
    status.value = result?.status || null
    startPolling()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(`启动数据库瘦身失败：${detail}`)
  }
}

async function dismissResult() {
  try {
    const data = await databaseMaintenanceApi.shrinkReset()
    status.value = data
  } catch (e) {
    console.warn('[数据库瘦身] 关闭结果失败', e)
    status.value = null
  }
}

onMounted(async () => {
  // 先看后端有没有"正在跑"的任务（比如刚刷新页面）
  try {
    const pending = await databaseMaintenanceApi.shrinkStatus()
    status.value = pending
    if (pending?.state === 'running') {
      startPolling()
    }
  } catch (e) {
    console.warn('[数据库瘦身] 初始状态读取失败', e)
  }
  await refresh()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
/* 整体容器：透明，与维护与清理面板里其他卡片（密码库清理 / 压缩包清理）保持同一种语言 */
.db-shrink {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
}

@media (max-width: 1100px) {
  .db-size-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.db-size-chip {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  font-size: 15px;
  font-weight: 600;
  color: var(--set-text-strong);
  letter-spacing: -0.1px;
  font-variant-numeric: tabular-nums;
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
