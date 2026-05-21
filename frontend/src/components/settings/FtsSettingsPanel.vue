<template>
  <div class="fts-stack">
    <div class="settings-grid two">
      <!-- ─── 操作记录 FTS ─── -->
      <div class="fts-card">
        <div class="fts-card-header">
          <div class="card-title">
            <IconDatabase :size="15" class="fts-title-icon" />
            <span>操作记录全文搜索</span>
          </div>
          <p class="fts-desc">
            为操作历史搜索框提供 SQLite FTS5 加速。trigram tokenizer 支持中文任意片段搜索（"字幕"、"失败"等），unicode61 仅支持英文前缀匹配。
          </p>
        </div>

        <!-- 状态信息格子（对齐 DatabaseShrinkCard db-size-chip 设计语言） -->
        <div class="fts-stat-grid">
          <div class="fts-stat-cell">
            <span class="fts-stat-label">当前状态</span>
            <div class="fts-stat-value">
              <span class="fts-chip" :class="activityChipClass">
                <svg v-if="activityStatusKey === 'syncing'" class="fts-spinner" viewBox="0 0 16 16" aria-hidden="true">
                  <circle class="fts-spinner-track" cx="8" cy="8" r="6" />
                  <circle class="fts-spinner-arc" cx="8" cy="8" r="6" />
                </svg>
                <component :is="activityStatusIcon" v-else :size="12" :stroke-width="2.4" />
                <span>{{ activityStatusLabel }}</span>
              </span>
            </div>
          </div>

          <div v-if="activityInfo?.fts_enabled" class="fts-stat-cell">
            <span class="fts-stat-label">已索引 / 总行数</span>
            <div class="fts-stat-value">
              <span class="fts-counts">
                <span class="fts-count-num">{{ (activityInfo.fts_row_count ?? 0).toLocaleString() }}</span>
                <span class="fts-count-sep">/</span>
                <span class="fts-count-total">{{ (activityInfo.row_count ?? 0).toLocaleString() }}</span>
                <span class="fts-count-unit">条</span>
              </span>
            </div>
          </div>

          <div v-if="activityInfo?.tokenizer" class="fts-stat-cell">
            <span class="fts-stat-label">Tokenizer</span>
            <div class="fts-stat-value">
              <span class="fts-token-chip" :class="{ 'is-trigram': activityInfo.tokenizer === 'trigram' }">
                {{ activityInfo.tokenizer === 'trigram' ? '⚡ trigram' : activityInfo.tokenizer }}
              </span>
            </div>
          </div>
        </div>

        <!-- 升级提示 / 重建进度 / 结果 -->
        <div class="fts-status-area">
          <!-- 升级提示 -->
          <div v-if="activityInfo?.needs_upgrade" class="fts-upgrade-hint">
            <IconZap :size="13" />
            <span>检测到 trigram 支持，建议重建升级以获得中文全文搜索能力</span>
          </div>

          <!-- 重建进度 -->
          <div v-if="activityStatusKey === 'syncing'" class="fts-progress-wrapper">
            <div class="fts-progress-row">
              <div class="fts-progress-track">
                <div class="fts-progress-fill" :style="{ width: activityProgressPct + '%' }" />
              </div>
              <span class="fts-progress-label">
                {{ (activityInfo?.rebuild?.copied ?? 0).toLocaleString() }} / {{ (activityInfo?.rebuild?.total ?? 0).toLocaleString() }} 条 ({{ activityProgressPct }}%)
              </span>
            </div>
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
        </div>

        <!-- 操作按钮 -->
        <div class="fts-actions">
          <button type="button" class="fts-btn-primary" :disabled="activityBusy || !activityInfo?.fts_enabled" @click="rebuildActivity">
            <IconLoader2 v-if="activityBusy" :size="13" class="fts-spin" />
            <IconRefreshCw v-else :size="13" />
            <span>{{ activityBusy ? '重建中…' : activityInfo?.needs_upgrade ? '升级 trigram 并重建' : '重建索引' }}</span>
          </button>
          <button type="button" class="fts-btn-ghost" :disabled="activityLoading" @click="fetchActivity">
            <span class="fts-icon-swap">
              <span class="fts-icon-slot" :class="{ 'is-visible': activityLoading && !activityBusy }">
                <IconLoader2 :size="12" class="fts-spin" />
              </span>
              <span class="fts-icon-slot" :class="{ 'is-visible': !(activityLoading && !activityBusy) }">
                <IconRefreshCw :size="12" />
              </span>
            </span>
            <span class="fts-ghost-label">{{ activityLoading && !activityBusy ? '刷新中…' : '刷新状态' }}</span>
          </button>
        </div>

        <p v-if="activityInfo && !activityInfo.fts_enabled" class="fts-warn-tip">
          当前 SQLite 不支持 FTS5（版本 &lt; 3.34），操作历史搜索降级为 LIKE 全表扫描（较慢）。
        </p>
      </div>

      <!-- ─── 库存索引 FTS ─── -->
      <div class="fts-card">
        <div class="fts-card-header">
          <div class="card-title">
            <IconSearchX :size="15" class="fts-title-icon" />
            <span>库存索引全文搜索</span>
          </div>
          <p class="fts-desc">
            为库存搜索框、RJ 跨库查找提供 SQLite FTS5 加速。重建完成后搜索速度从秒级降至 ms 级；重建期间搜索自动 fallback，功能不中断。
          </p>
        </div>

        <!-- 状态信息格子 -->
        <div class="fts-stat-grid">
          <div class="fts-stat-cell">
            <span class="fts-stat-label">当前状态</span>
            <div class="fts-stat-value">
              <span class="fts-chip" :class="libraryChipClass">
                <svg v-if="libraryStatusKey === 'syncing'" class="fts-spinner" viewBox="0 0 16 16" aria-hidden="true">
                  <circle class="fts-spinner-track" cx="8" cy="8" r="6" />
                  <circle class="fts-spinner-arc" cx="8" cy="8" r="6" />
                </svg>
                <component :is="libraryStatusIcon" v-else :size="12" :stroke-width="2.4" />
                <span>{{ libraryStatusLabel }}</span>
              </span>
            </div>
          </div>

          <div v-if="libraryInfo?.fts_enabled" class="fts-stat-cell">
            <span class="fts-stat-label">已索引 / 总行数</span>
            <div class="fts-stat-value">
              <span class="fts-counts">
                <span class="fts-count-num">{{ (libraryInfo.fts_row_count ?? libraryInfo.indexed_entries ?? 0).toLocaleString() }}</span>
                <span class="fts-count-sep">/</span>
                <span class="fts-count-total">{{ (libraryInfo.row_count ?? libraryInfo.total_entries ?? 0).toLocaleString() }}</span>
                <span class="fts-count-unit">条</span>
              </span>
            </div>
          </div>

          <div v-if="libraryInfo?.tokenizer" class="fts-stat-cell">
            <span class="fts-stat-label">Tokenizer</span>
            <div class="fts-stat-value">
              <span class="fts-token-chip" :class="{ 'is-trigram': libraryInfo.tokenizer === 'trigram' }">
                {{ libraryInfo.tokenizer === 'trigram' ? '⚡ trigram' : libraryInfo.tokenizer }}
              </span>
            </div>
          </div>
        </div>

        <!-- 升级提示 / 重建进度 / 结果 -->
        <div class="fts-status-area">
          <!-- 升级提示 -->
          <div v-if="libraryInfo?.needs_upgrade" class="fts-upgrade-hint">
            <IconZap :size="13" />
            <span>检测到 trigram 支持，建议重建升级以获得更精准的中文搜索能力</span>
          </div>

          <!-- 重建进度 -->
          <div v-if="libraryStatusKey === 'syncing'" class="fts-progress-wrapper">
            <div class="fts-progress-row">
              <div class="fts-progress-track">
                <div class="fts-progress-fill" :style="{ width: libraryProgressPct + '%' }" />
              </div>
              <span class="fts-progress-label">
                {{ (libraryInfo?.indexed_entries ?? 0).toLocaleString() }} / {{ (libraryInfo?.total_entries ?? 0).toLocaleString() }} 条 ({{ libraryProgressPct }}%)
              </span>
            </div>
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
        </div>

        <!-- 操作按钮 -->
        <div class="fts-actions">
          <button type="button" class="fts-btn-primary" :disabled="libraryBusy || !libraryInfo?.fts_enabled" @click="rebuildLibrary">
            <IconLoader2 v-if="libraryBusy" :size="13" class="fts-spin" />
            <IconRefreshCw v-else :size="13" />
            <span>{{ libraryBusy ? '重建中…' : libraryInfo?.needs_upgrade ? '升级 trigram 并重建' : '重建索引' }}</span>
          </button>
          <button type="button" class="fts-btn-ghost" :disabled="libraryLoading" @click="fetchLibrary">
            <span class="fts-icon-swap">
              <span class="fts-icon-slot" :class="{ 'is-visible': libraryLoading && !libraryBusy }">
                <IconLoader2 :size="12" class="fts-spin" />
              </span>
              <span class="fts-icon-slot" :class="{ 'is-visible': !(libraryLoading && !libraryBusy) }">
                <IconRefreshCw :size="12" />
              </span>
            </span>
            <span class="fts-ghost-label">{{ libraryLoading && !libraryBusy ? '刷新中…' : '刷新状态' }}</span>
          </button>
        </div>

        <p v-if="libraryInfo && !libraryInfo.fts_enabled" class="fts-warn-tip">
          当前 SQLite 不支持 FTS5（版本 &lt; 3.34），库存搜索降级为 LIKE 扫描（较慢）。
        </p>
      </div>
    </div>
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

/** 保证 loading 态最少持续 ms 毫秒，让动画有时间播完 */
function withMinDuration(promise, ms = 600) {
  return Promise.all([promise, new Promise(r => setTimeout(r, ms))]).then(([result]) => result)
}

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
    const data = await withMinDuration(activityLogApi.searchStatus())
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
    const data = await withMinDuration(databaseMaintenanceApi.libraryIndexFtsStatus())
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
  overflow: visible;
}

/* ─── 统一栅格（对齐 settings-grid two） ─── */
.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (max-width: 1200px) {
  .settings-grid.two {
    grid-template-columns: 1fr;
  }
}

/* ─── 模块卡片（fts-card） ─── */
.fts-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02), 0 8px 24px -12px rgba(15, 23, 42, 0.05);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.fts-card:hover {
  border-color: rgba(148, 163, 184, 0.45);
  box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.04), 0 12px 28px -4px rgba(15, 23, 42, 0.08);
}

.fts-card-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.fts-title-icon {
  color: #4f46e5;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #1d1d1f;
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.fts-desc {
  margin: 0;
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.6;
}

/* ─── 状态信息格子（解决嵌套白框，改用轻质对比底色） ─── */
.fts-stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 480px) {
  .fts-stat-grid {
    grid-template-columns: 1fr;
  }
}

.fts-stat-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(226, 232, 240, 0.7);
  transition: all 0.2s ease;
}

.fts-stat-cell:hover {
  background: #f1f5f9;
  border-color: rgba(203, 213, 225, 0.85);
}

.fts-stat-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.fts-stat-value {
  display: flex;
  align-items: center;
  min-height: 24px;
}

/* ─── 状态 Chip ─── */
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

.fts-chip:hover {
  transform: translateY(-1px) scale(1.04);
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
    0 1px 2px rgba(37, 99, 235, 0.12);
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
      0 0 0 4px rgba(59, 130, 246, 0.2);
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
  font-size: 13.5px;
  font-weight: 600;
  color: #0f172a;
}

.fts-count-sep {
  font-size: 11px;
  color: #cbd5e1;
}

.fts-count-total {
  font-size: 11.5px;
  color: #64748b;
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
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
  background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%);
  color: #475569;
  border: 1px solid rgba(148, 163, 184, 0.3);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.fts-token-chip:hover {
  transform: translateY(-1px) scale(1.04);
}

.fts-token-chip.is-trigram {
  background: linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%);
  color: #15803d;
  border-color: rgba(134, 239, 172, 0.5);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(34, 197, 94, 0.12);
}

/* ─── 提示与状态区域 ─── */
.fts-status-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

/* ─── 升级提示 ─── */
.fts-upgrade-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  background: linear-gradient(180deg, #fffbeb 0%, #fef9ec 100%);
  border: 1px solid rgba(251, 191, 36, 0.4);
  color: #92400e;
  font-size: 12px;
  font-weight: 500;
}

.fts-upgrade-hint svg {
  color: #d97706;
  flex-shrink: 0;
}

/* ─── 进度条 ─── */
.fts-progress-wrapper {
  padding: 4px 2px;
}

.fts-progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.fts-progress-track {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.1);
  overflow: hidden;
}

.fts-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #4f46e5 0%, #6366f1 100%);
  transition: width 0.4s ease;
}

.fts-progress-label {
  font-size: 11.5px;
  color: #64748b;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

/* ─── 结果行 ─── */
.fts-result {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
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
  gap: 10px;
  margin-top: 4px;
}

.fts-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid #0f172a;
  cursor: pointer;
  background: linear-gradient(180deg, #1f2937 0%, #0f172a 60%, #020617 100%);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.1px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 6px 16px -6px rgba(2, 6, 23, 0.55),
    0 2px 4px rgba(15, 23, 42, 0.25);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
}

.fts-btn-primary svg {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.fts-btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 10px 22px -6px rgba(2, 6, 23, 0.65),
    0 4px 8px rgba(15, 23, 42, 0.3);
}

.fts-btn-primary:hover:not(:disabled) svg {
  transform: scale(1.1) rotate(-6deg);
}

.fts-btn-primary:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.08s ease;
}

.fts-btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.fts-btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7.5px 13px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
  min-width: 88px;
}

.fts-icon-swap {
  position: relative;
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

.fts-icon-slot {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transform: scale(0.5) rotate(-45deg);
  transition: opacity 0.22s ease, transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  pointer-events: none;
}

.fts-icon-slot.is-visible {
  opacity: 1;
  transform: scale(1) rotate(0deg);
}

.fts-ghost-label {
  min-width: 42px;
}

.fts-btn-ghost:hover:not(:disabled) {
  border-color: rgba(148, 163, 184, 0.75);
  color: #0f172a;
  background: #f8fafc;
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.06);
}

.fts-btn-ghost:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.08s ease;
}

.fts-btn-ghost:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ─── 旋转动画 ─── */
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
  font-size: 11.5px;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .fts-actions { flex-direction: column; align-items: stretch; }
  .fts-btn-primary, .fts-btn-ghost { width: 100%; justify-content: center; }
}
</style>
