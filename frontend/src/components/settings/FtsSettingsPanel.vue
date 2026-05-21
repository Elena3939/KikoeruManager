<template>
  <div class="fts-stack">
    <!-- ─── 操作记录 FTS ─── -->
    <section class="fts-section">
      <div class="card-title">操作记录全文搜索</div>
      <p class="fts-desc">
        为操作历史搜索框提供 SQLite FTS5 加速。trigram tokenizer 支持中文任意片段搜索（"字幕"、"失败"等），unicode61 仅支持英文前缀匹配。
      </p>

      <!-- 状态信息格子（对齐 DatabaseShrinkCard db-size-chip 设计语言） -->
      <div class="fts-stat-grid">
        <div class="fts-stat-cell">
          <span class="fts-stat-label">状态</span>
          <span class="fts-chip" :class="activityChipClass">
            <svg v-if="activityStatusKey === 'syncing'" class="fts-spinner" viewBox="0 0 16 16" aria-hidden="true">
              <circle class="fts-spinner-track" cx="8" cy="8" r="6" />
              <circle class="fts-spinner-arc" cx="8" cy="8" r="6" />
            </svg>
            <component :is="activityStatusIcon" v-else :size="11" :stroke-width="2.4" />
            <span>{{ activityStatusLabel }}</span>
          </span>
        </div>

        <div v-if="activityInfo?.fts_enabled" class="fts-stat-cell">
          <span class="fts-stat-label">已索引 / 总行数</span>
          <span class="fts-counts">
            <span class="fts-count-num">{{ (activityInfo.fts_row_count ?? 0).toLocaleString() }}</span>
            <span class="fts-count-sep">/</span>
            <span class="fts-count-total">{{ (activityInfo.row_count ?? 0).toLocaleString() }}</span>
            <span class="fts-count-unit">条</span>
          </span>
        </div>

        <div v-if="activityInfo?.tokenizer" class="fts-stat-cell">
          <span class="fts-stat-label">Tokenizer</span>
          <span class="fts-token-chip" :class="{ 'is-trigram': activityInfo.tokenizer === 'trigram' }">
            {{ activityInfo.tokenizer === 'trigram' ? '⚡ trigram' : activityInfo.tokenizer }}
          </span>
        </div>
      </div>

      <!-- 升级提示 -->
      <div v-if="activityInfo?.needs_upgrade" class="fts-upgrade-hint">
        <IconZap :size="13" />
        <span>检测到 trigram 支持，建议重建升级以获得中文全文搜索能力</span>
      </div>

      <!-- 重建进度 -->
      <div v-if="activityStatusKey === 'syncing'" class="fts-progress-row">
        <div class="fts-progress-track">
          <div class="fts-progress-fill" :style="{ width: activityProgressPct + '%' }" />
        </div>
        <span class="fts-progress-label">
          {{ (activityInfo?.rebuild?.copied ?? 0).toLocaleString() }} / {{ (activityInfo?.rebuild?.total ?? 0).toLocaleString() }} 条
        </span>
      </div>

      <!-- 结果行 -->
      <div v-else-if="activityInfo?.rebuild?.ok === true" class="fts-result is-done">
        <IconCheckCircle2 :size="13" />
        <span>重建完成 · tokenizer: {{ activityInfo.rebuild.target_tokenizer || activityInfo.tokenizer }} · 共 {{ (activityInfo.rebuild.total ?? 0).toLocaleString() }} 条</span>
      </div>
      <div v-else-if="activityInfo?.rebuild?.ok === false" class="fts-result is-error">
        <IconAlertCircle :size="13" />
        <span>重建失败：{{ activityInfo.rebuild.reason || '未知错误' }}</span>
      </div>

      <!-- 操作按钮 -->
      <div class="fts-actions">
        <button type="button" class="fts-btn-primary" :disabled="activityBusy || !activityInfo?.fts_enabled" @click="rebuildActivity">
          <IconLoader2 v-if="activityBusy" :size="13" class="fts-spin" />
          <IconRefreshCw v-else :size="13" />
          <span>{{ activityBusy ? '重建中…' : activityInfo?.needs_upgrade ? '升级 trigram 并重建' : '重建索引' }}</span>
        </button>
        <button type="button" class="fts-btn-ghost" :disabled="activityLoading" @click="fetchActivity">
          <IconRefreshCw :size="12" :class="{ 'fts-spin': activityLoading && !activityBusy }" />
          <span>刷新状态</span>
        </button>
      </div>

      <p v-if="activityInfo && !activityInfo.fts_enabled" class="fts-warn-tip">
        当前 SQLite 不支持 FTS5（版本 &lt; 3.34），操作历史搜索降级为 LIKE 全表扫描（较慢）。
      </p>
    </section>

    <div class="fts-divider" />

    <!-- ─── 库存索引 FTS ─── -->
    <section class="fts-section">
      <div class="card-title">库存索引全文搜索</div>
      <p class="fts-desc">
        为库存搜索框、RJ 跨库查找提供 SQLite FTS5 加速。重建完成后搜索速度从秒级降至 ms 级；重建期间搜索自动 fallback，功能不中断。
      </p>

      <!-- 状态信息格子 -->
      <div class="fts-stat-grid">
        <div class="fts-stat-cell">
          <span class="fts-stat-label">状态</span>
          <span class="fts-chip" :class="libraryChipClass">
            <svg v-if="libraryStatusKey === 'syncing'" class="fts-spinner" viewBox="0 0 16 16" aria-hidden="true">
              <circle class="fts-spinner-track" cx="8" cy="8" r="6" />
              <circle class="fts-spinner-arc" cx="8" cy="8" r="6" />
            </svg>
            <component :is="libraryStatusIcon" v-else :size="11" :stroke-width="2.4" />
            <span>{{ libraryStatusLabel }}</span>
          </span>
        </div>

        <div v-if="libraryInfo?.fts_enabled" class="fts-stat-cell">
          <span class="fts-stat-label">已索引 / 总行数</span>
          <span class="fts-counts">
            <span class="fts-count-num">{{ (libraryInfo.fts_row_count ?? libraryInfo.indexed_entries ?? 0).toLocaleString() }}</span>
            <span class="fts-count-sep">/</span>
            <span class="fts-count-total">{{ (libraryInfo.row_count ?? libraryInfo.total_entries ?? 0).toLocaleString() }}</span>
            <span class="fts-count-unit">条</span>
          </span>
        </div>

        <div v-if="libraryInfo?.tokenizer" class="fts-stat-cell">
          <span class="fts-stat-label">Tokenizer</span>
          <span class="fts-token-chip" :class="{ 'is-trigram': libraryInfo.tokenizer === 'trigram' }">
            {{ libraryInfo.tokenizer === 'trigram' ? '⚡ trigram' : libraryInfo.tokenizer }}
          </span>
        </div>
      </div>

      <!-- 升级提示 -->
      <div v-if="libraryInfo?.needs_upgrade" class="fts-upgrade-hint">
        <IconZap :size="13" />
        <span>检测到 trigram 支持，建议重建升级以获得更精准的中文搜索能力</span>
      </div>

      <!-- 重建进度 -->
      <div v-if="libraryStatusKey === 'syncing'" class="fts-progress-row">
        <div class="fts-progress-track">
          <div class="fts-progress-fill" :style="{ width: libraryProgressPct + '%' }" />
        </div>
        <span class="fts-progress-label">
          {{ (libraryInfo?.indexed_entries ?? 0).toLocaleString() }} / {{ (libraryInfo?.total_entries ?? 0).toLocaleString() }} 条
        </span>
      </div>

      <!-- 结果行 -->
      <div v-else-if="libraryInfo?.rebuild?.state === 'done'" class="fts-result is-done">
        <IconCheckCircle2 :size="13" />
        <span>重建完成 · tokenizer: {{ libraryInfo.rebuild.tokenizer }} · 共 {{ (libraryInfo.rebuild.total_entries ?? 0).toLocaleString() }} 条</span>
      </div>
      <div v-else-if="libraryInfo?.rebuild?.state === 'error'" class="fts-result is-error">
        <IconAlertCircle :size="13" />
        <span>重建失败：{{ libraryInfo.rebuild.error || '未知错误' }}</span>
      </div>

      <!-- 操作按钮 -->
      <div class="fts-actions">
        <button type="button" class="fts-btn-primary" :disabled="libraryBusy || !libraryInfo?.fts_enabled" @click="rebuildLibrary">
          <IconLoader2 v-if="libraryBusy" :size="13" class="fts-spin" />
          <IconRefreshCw v-else :size="13" />
          <span>{{ libraryBusy ? '重建中…' : libraryInfo?.needs_upgrade ? '升级 trigram 并重建' : '重建索引' }}</span>
        </button>
        <button type="button" class="fts-btn-ghost" :disabled="libraryLoading" @click="fetchLibrary">
          <IconRefreshCw :size="12" :class="{ 'fts-spin': libraryLoading && !libraryBusy }" />
          <span>刷新状态</span>
        </button>
      </div>

      <p v-if="libraryInfo && !libraryInfo.fts_enabled" class="fts-warn-tip">
        当前 SQLite 不支持 FTS5（版本 &lt; 3.34），库存搜索降级为 LIKE 扫描（较慢）。
      </p>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  AlertCircle as IconAlertCircle,
  CheckCircle2 as IconCheckCircle2,
  Database as IconDatabase,
  Loader2 as IconLoader2,
  RefreshCw as IconRefreshCw,
  SearchX as IconSearchX,
  Zap as IconZap,
  ZapOff as IconZapOff,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { activityLogApi, databaseMaintenanceApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'

// ─── Activity Logs FTS ───────────────────────────────────────
const activityInfo = ref(null)
const activityLoading = ref(false)
let activityPollTimer = null

const activityStatusKey = computed(() => {
  const info = activityInfo.value
  if (!info) return 'idle'
  if (!info.fts_enabled) return 'unavailable'
  if (info.rebuild?.running) return 'syncing'
  if (info.rebuild?.ok === false) return 'error'
  if (info.needs_upgrade) return 'warning'
  const r = info.row_count ?? 0
  const f = info.fts_row_count ?? 0
  if (r > 0 && f < r) return 'degraded'
  return 'ready'
})

const activityBusy = computed(() => activityStatusKey.value === 'syncing')

const ACTIVITY_STATUS_MAP = {
  idle:        { label: '未加载', chipClass: 'fts-chip-idle',      icon: IconDatabase },
  unavailable: { label: '不支持',  chipClass: 'fts-chip-unavailable', icon: IconZapOff },
  syncing:     { label: '重建中',  chipClass: 'fts-chip-syncing',    icon: null },
  ready:       { label: '正常',   chipClass: 'fts-chip-ready',      icon: IconCheckCircle2 },
  warning:     { label: '可升级', chipClass: 'fts-chip-warning',    icon: IconZap },
  degraded:    { label: '待回填', chipClass: 'fts-chip-degraded',   icon: IconAlertCircle },
  error:       { label: '出错',   chipClass: 'fts-chip-error',      icon: IconAlertCircle },
}

const activityChipClass = computed(() => ACTIVITY_STATUS_MAP[activityStatusKey.value]?.chipClass ?? 'fts-chip-idle')
const activityStatusLabel = computed(() => ACTIVITY_STATUS_MAP[activityStatusKey.value]?.label ?? '—')
const activityStatusIcon = computed(() => ACTIVITY_STATUS_MAP[activityStatusKey.value]?.icon ?? IconDatabase)

const activityProgressPct = computed(() => {
  const rebuild = activityInfo.value?.rebuild
  if (!rebuild) return 0
  const total = Number(rebuild.total ?? 0)
  const copied = Number(rebuild.copied ?? 0)
  if (total <= 0) return 0
  return Math.min(100, Math.round((copied / total) * 100))
})

async function fetchActivity() {
  if (activityLoading.value && !activityBusy.value) return
  activityLoading.value = true
  try {
    const data = await activityLogApi.searchStatus()
    activityInfo.value = data
    if (data?.rebuild?.running) {
      startActivityPolling()
    } else {
      stopActivityPolling()
    }
  } catch (e) {
    console.warn('[FTS] 操作记录 FTS 状态获取失败', e)
  } finally {
    activityLoading.value = false
  }
}

function startActivityPolling() {
  stopActivityPolling()
  activityPollTimer = setInterval(fetchActivity, 1400)
}

function stopActivityPolling() {
  if (activityPollTimer) {
    clearInterval(activityPollTimer)
    activityPollTimer = null
  }
}

async function rebuildActivity() {
  if (activityBusy.value) return
  const info = activityInfo.value
  const isUpgrade = info?.needs_upgrade
  const targetTokenizer = info?.trigram_supported ? 'trigram' : (info?.tokenizer || 'trigram')
  try {
    await showSystemConfirm({
      title: isUpgrade ? '升级 FTS tokenizer 并重建索引' : '重建操作记录全文搜索索引',
      message: isUpgrade
        ? '将把操作记录搜索索引从 unicode61 升级为 trigram tokenizer，之后可以搜索任意中文片段。'
        : '将后台重建操作记录 FTS5 索引，期间搜索自动 fallback，功能不中断。',
      details: [
        { label: '目标 tokenizer', value: targetTokenizer },
        { label: '当前行数', value: `${(info?.row_count ?? 0).toLocaleString()} 条` },
      ],
      confirmText: isUpgrade ? '升级并重建' : '立即重建',
      cancelText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await activityLogApi.rebuildFts(targetTokenizer)
    if (result?.started === false) {
      ElMessage.info('重建任务已经在运行中')
    }
    await fetchActivity()
    startActivityPolling()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(`触发操作记录 FTS 重建失败：${detail}`)
  }
}

// ─── Library Index FTS ───────────────────────────────────────
const libraryInfo = ref(null)
const libraryLoading = ref(false)
let libraryPollTimer = null

const libraryStatusKey = computed(() => {
  const info = libraryInfo.value
  if (!info) return 'idle'
  if (!info.fts_enabled) return 'unavailable'
  const rebuildState = info.rebuild?.state || info.state
  if (rebuildState === 'running') return 'syncing'
  if (rebuildState === 'error') return 'error'
  if (info.needs_upgrade) return 'warning'
  const r = info.row_count ?? info.total_entries ?? 0
  const f = info.fts_row_count ?? info.indexed_entries ?? 0
  if (r > 0 && f < r) return 'degraded'
  return 'ready'
})

const libraryBusy = computed(() => libraryStatusKey.value === 'syncing')

const LIBRARY_STATUS_MAP = {
  idle:        { label: '未加载', chipClass: 'fts-chip-idle',      icon: IconDatabase },
  unavailable: { label: '不支持',  chipClass: 'fts-chip-unavailable', icon: IconZapOff },
  syncing:     { label: '重建中',  chipClass: 'fts-chip-syncing',    icon: null },
  ready:       { label: '正常',   chipClass: 'fts-chip-ready',      icon: IconCheckCircle2 },
  warning:     { label: '可升级', chipClass: 'fts-chip-warning',    icon: IconZap },
  degraded:    { label: '待回填', chipClass: 'fts-chip-degraded',   icon: IconAlertCircle },
  error:       { label: '出错',   chipClass: 'fts-chip-error',      icon: IconAlertCircle },
}

const libraryChipClass = computed(() => LIBRARY_STATUS_MAP[libraryStatusKey.value]?.chipClass ?? 'fts-chip-idle')
const libraryStatusLabel = computed(() => LIBRARY_STATUS_MAP[libraryStatusKey.value]?.label ?? '—')
const libraryStatusIcon = computed(() => LIBRARY_STATUS_MAP[libraryStatusKey.value]?.icon ?? IconDatabase)

const libraryProgressPct = computed(() => {
  const info = libraryInfo.value
  if (!info) return 0
  const total = Number(info.total_entries ?? info.row_count ?? 0)
  const indexed = Number(info.indexed_entries ?? info.fts_row_count ?? 0)
  if (total <= 0) return 0
  return Math.min(100, Math.round((indexed / total) * 100))
})

async function fetchLibrary() {
  if (libraryLoading.value && !libraryBusy.value) return
  libraryLoading.value = true
  try {
    const data = await databaseMaintenanceApi.libraryIndexFtsStatus()
    libraryInfo.value = data
    const rebuildState = data?.rebuild?.state || data?.state
    if (rebuildState === 'running') {
      startLibraryPolling()
    } else {
      stopLibraryPolling()
    }
  } catch (e) {
    console.warn('[FTS] 库存索引 FTS 状态获取失败', e)
  } finally {
    libraryLoading.value = false
  }
}

function startLibraryPolling() {
  stopLibraryPolling()
  libraryPollTimer = setInterval(fetchLibrary, 1400)
}

function stopLibraryPolling() {
  if (libraryPollTimer) {
    clearInterval(libraryPollTimer)
    libraryPollTimer = null
  }
}

async function rebuildLibrary() {
  if (libraryBusy.value) return
  const info = libraryInfo.value
  const isUpgrade = info?.needs_upgrade
  const targetTokenizer = info?.trigram_supported ? 'trigram' : (info?.tokenizer || 'trigram')
  try {
    await showSystemConfirm({
      title: isUpgrade ? '升级库存索引 FTS tokenizer 并重建' : '重建库存索引全文搜索',
      message: isUpgrade
        ? '将把库存搜索索引升级为 trigram tokenizer，搜索精度大幅提升。'
        : '将后台重建库存索引 FTS5 表，期间搜索自动 fallback LIKE，功能不中断。',
      details: [
        { label: '目标 tokenizer', value: targetTokenizer },
        { label: '当前行数', value: `${((info?.row_count ?? info?.total_entries) ?? 0).toLocaleString()} 条` },
      ],
      confirmText: isUpgrade ? '升级并重建' : '立即重建',
      cancelText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await databaseMaintenanceApi.rebuildLibraryIndexFts(targetTokenizer)
    if (result?.already_running) {
      ElMessage.info('重建任务已经在运行中')
    }
    await fetchLibrary()
    startLibraryPolling()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error(`触发库存索引 FTS 重建失败：${detail}`)
  }
}

// ─── 生命周期 ───────────────────────────────────────────────
onMounted(() => {
  fetchActivity()
  fetchLibrary()
})

onBeforeUnmount(() => {
  stopActivityPolling()
  stopLibraryPolling()
})
</script>

<style scoped>
.fts-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* ─── 每个 FTS 区块（对齐 DatabaseShrinkCard .db-shrink 风格） ─── */
.fts-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 0;
}

.fts-divider {
  height: 1px;
  background: rgba(226, 232, 240, 0.7);
  margin: 0;
}

.card-title {
  margin: 0;
  color: #1d1d1f;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.fts-desc {
  margin: 0;
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.6;
}

/* ─── 状态信息格子（对齐 DatabaseShrinkCard .db-size-chip 设计语言） ─── */
.fts-stat-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.fts-stat-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  min-width: 80px;
  transition: border-color 0.18s ease;
}

.fts-stat-cell:hover {
  border-color: rgba(148, 163, 184, 0.6);
}

.fts-stat-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* ─── 状态 Chip（对齐 LibraryIndexBadge 的 lib-index-chip 设计语言） ─── */
.fts-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  letter-spacing: 0.01em;
  white-space: nowrap;
  border: 1px solid transparent;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.fts-chip-idle {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  color: #64748b;
  border-color: rgba(148, 163, 184, 0.3);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(15, 23, 42, 0.04);
}

.fts-chip-unavailable {
  background: linear-gradient(180deg, #fafafa 0%, #f4f4f5 100%);
  color: #a1a1aa;
  border-color: rgba(161, 161, 170, 0.3);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 1px 2px rgba(15, 23, 42, 0.03);
}

.fts-chip-syncing {
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  color: #1d4ed8;
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(37, 99, 235, 0.12),
    0 0 0 0 rgba(59, 130, 246, 0.35);
  animation: fts-chip-pulse 1.8s ease-in-out infinite;
}

.fts-chip-ready {
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
  border-color: rgba(110, 231, 183, 0.55);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(16, 185, 129, 0.12);
}

.fts-chip-warning {
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  color: #b45309;
  border-color: rgba(251, 191, 36, 0.5);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(245, 158, 11, 0.12);
}

.fts-chip-degraded {
  background: linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%);
  color: #c2410c;
  border-color: rgba(251, 146, 60, 0.45);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), 0 1px 2px rgba(249, 115, 22, 0.12);
}

.fts-chip-error {
  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);
  color: #b91c1c;
  border-color: rgba(248, 113, 113, 0.5);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), 0 1px 2px rgba(239, 68, 68, 0.15);
}

@keyframes fts-chip-pulse {
  0%, 100% {
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.7),
      0 1px 2px rgba(37, 99, 235, 0.12),
      0 0 0 0 rgba(59, 130, 246, 0.4);
  }
  50% {
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.85),
      0 1px 2px rgba(37, 99, 235, 0.18),
      0 0 0 4px rgba(59, 130, 246, 0);
  }
}

/* ─── 圆环 Spinner ─── */
.fts-spinner {
  width: 11px;
  height: 11px;
  flex-shrink: 0;
  animation: fts-spinner-rotate 1.4s linear infinite;
}

.fts-spinner-track {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  opacity: 0.22;
}

.fts-spinner-arc {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-dasharray: 20;
  stroke-dashoffset: 15;
  stroke-linecap: round;
  transform-origin: center;
}

@keyframes fts-spinner-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* ─── 行数统计 ─── */
.fts-counts {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  font-variant-numeric: tabular-nums;
}

.fts-count-num {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.fts-count-sep {
  font-size: 12px;
  color: #94a3b8;
}

.fts-count-total {
  font-size: 12px;
  color: #475569;
}

.fts-count-unit {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 2px;
}

/* ─── Tokenizer 标签 ─── */
.fts-token-chip {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%);
  color: #475569;
  border: 1px solid rgba(148, 163, 184, 0.3);
}

.fts-token-chip.is-trigram {
  background: linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%);
  color: #15803d;
  border-color: rgba(134, 239, 172, 0.5);
}

/* ─── 升级提示 ─── */
.fts-upgrade-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 8px;
  background: linear-gradient(180deg, #fffbeb 0%, #fef9ec 100%);
  border: 1px solid rgba(251, 191, 36, 0.4);
  color: #92400e;
  font-size: 12.5px;
  font-weight: 500;
}

.fts-upgrade-hint svg {
  color: #d97706;
  flex-shrink: 0;
}

/* ─── 进度条 ─── */
.fts-progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fts-progress-track {
  flex: 1;
  height: 4px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.12);
  overflow: hidden;
}

.fts-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #3b82f6 0%, #60a5fa 100%);
  transition: width 0.5s ease;
}

.fts-progress-label {
  font-size: 11.5px;
  color: #475569;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ─── 结果行 ─── */
.fts-result {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
}

.fts-result.is-done {
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  border: 1px solid rgba(110, 231, 183, 0.4);
  color: #065f46;
}

.fts-result.is-done svg { color: #10b981; flex-shrink: 0; }

.fts-result.is-error {
  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);
  border: 1px solid rgba(248, 113, 113, 0.4);
  color: #7f1d1d;
}

.fts-result.is-error svg { color: #ef4444; flex-shrink: 0; }

/* ─── 操作按钮（对齐 DatabaseShrinkCard 的 db-btn-primary/ghost） ─── */
.fts-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.fts-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #1e293b 0%, #334155 50%, #1e293b 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 2px 6px rgba(15, 23, 42, 0.2),
    0 8px 18px rgba(15, 23, 42, 0.14);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
}

.fts-btn-primary:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 4px 10px rgba(15, 23, 42, 0.22),
    0 14px 28px rgba(15, 23, 42, 0.18),
    0 0 0 4px rgba(15, 23, 42, 0.05);
}

.fts-btn-primary:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  box-shadow:
    inset 0 2px 6px rgba(0, 0, 0, 0.3),
    0 2px 4px rgba(15, 23, 42, 0.15);
  transition: all 0.08s ease;
}

.fts-btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.fts-btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: #fff;
  color: #475569;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.25s ease;
  white-space: nowrap;
}

.fts-btn-ghost:hover:not(:disabled) {
  border-color: rgba(148, 163, 184, 0.75);
  color: #1e293b;
  background: #f8fafc;
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.06);
}

.fts-btn-ghost:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.08s ease;
}

.fts-btn-ghost:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ─── 旋转动画（Loader2 图标） ─── */
.fts-spin {
  animation: fts-icon-spin 0.85s linear infinite;
}

@keyframes fts-icon-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* ─── 不支持提示 ─── */
.fts-warn-tip {
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.6);
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .fts-actions { flex-direction: column; align-items: stretch; }
  .fts-btn-primary, .fts-btn-ghost { width: 100%; justify-content: center; }
}
</style>
