<template>
  <div class="system-stack">
    <section class="system-card system-hero-card">
      <div class="system-hero-copy">
        <div class="card-title">
          <IconServerCog :size="15" class="system-title-icon" />
          <span>SQLite 运行配置</span>
        </div>
        <p class="system-desc">
          这里控制数据库 journal、同步策略、busy timeout 和 SQLAlchemy 连接池。保存后需要重启后端进程才会应用到当前 engine。
        </p>
      </div>
      <div class="system-runtime-strip">
        <span class="runtime-pill">当前草稿：{{ db.journal_mode }} / {{ db.synchronous }}</span>
        <span class="runtime-pill">连接池 {{ db.pool_size }} + {{ db.max_overflow }}</span>
        <span class="runtime-pill">busy {{ formatMs(db.busy_timeout_ms) }}</span>
      </div>
    </section>

    <div class="settings-grid two">
      <section class="system-card">
        <div class="card-title">SQLite 安全与吞吐</div>
        <div class="field-stack">
          <div class="mini-grid two">
            <SettingsFieldCard label="Journal Mode" hint="WAL 适合读写并发；DELETE 更保守但写入时读写互斥。">
              <AppDropdown v-model="db.journal_mode" :options="journalModeOptions" class="settings-field-dd" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Synchronous" hint="FULL 更耐断电/掉盘；NORMAL 吞吐更高但 WAL checkpoint 风险更大。">
              <AppDropdown v-model="db.synchronous" :options="synchronousOptions" class="settings-field-dd" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid two">
            <SettingsFieldCard label="Busy Timeout" hint="写锁等待上限。群晖 / HDD / Docker 卷建议 60000ms 起。">
              <SettingsNumberStepper v-model="db.busy_timeout_ms" :min="1000" :max="300000" :step="1000" />
            </SettingsFieldCard>
            <SettingsFieldCard label="WAL Auto Checkpoint" hint="WAL 累积到指定页数后自动 checkpoint；过大可能让 -wal 文件膨胀。">
              <SettingsNumberStepper v-model="db.wal_autocheckpoint" :min="100" :max="10000" :step="100" />
            </SettingsFieldCard>
          </div>

          <SettingsFieldCard label="SQLite Cache Size" hint="单位 KB。负数 PRAGMA cache_size 的绝对值，当前后端按 KB 写入。">
            <SettingsNumberStepper v-model="db.cache_size_kb" :min="1024" :max="262144" :step="1024" />
          </SettingsFieldCard>
        </div>
      </section>

      <section class="system-card">
        <div class="card-title">连接池与启动自检</div>
        <div class="field-stack">
          <div class="mini-grid three">
            <SettingsFieldCard label="Pool Size" hint="常驻连接数。SQLite 写入单写者，别盲目拉满。">
              <SettingsNumberStepper v-model="db.pool_size" :min="1" :max="20" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Max Overflow" hint="突发额外连接数。之前硬编码 10，现在可控。">
              <SettingsNumberStepper v-model="db.max_overflow" :min="0" :max="30" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Pool Recycle" hint="连接回收秒数，避免长时间挂起的旧连接。">
              <SettingsNumberStepper v-model="db.pool_recycle_seconds" :min="60" :max="86400" :step="60" />
            </SettingsFieldCard>
          </div>

          <SettingsToggleRow
            v-model="db.startup_quick_check"
            title="启动时 quick_check"
            subtitle="后端启动时先做 SQLite 快速一致性检查；失败会阻止继续启动，避免继续写坏库。"
          />
          <SettingsToggleRow
            v-model="db.startup_integrity_check"
            title="启动时完整 integrity_check"
            subtitle="比 quick_check 慢很多，大库不建议常开；适合修复后短期开启确认。"
            :disabled="!db.startup_quick_check"
          />
        </div>
      </section>
    </div>

    <section class="system-card">
      <div class="card-title">
        <IconGauge :size="15" class="system-title-icon" />
        <span>全局资源预算</span>
      </div>
      <p class="system-desc">
        这些令牌会被真实业务链路消耗：SQLite 写入、远程库存、HTTP / 百度下载、本地磁盘复制、解压和压缩包探测。
        值为 0 表示该资源不限制；SQLite 写入在启用预算时最低会收敛为 1。
      </p>

      <div class="resource-head">
        <SettingsToggleRow
          v-model="budget.enabled"
          title="启用资源预算"
          subtitle="用轻量背压避免下载、解压、远程库扫描和 SQLite 写入互相打满。"
        />
      </div>

      <div class="budget-grid">
        <SettingsFieldCard
          v-for="item in budgetItems"
          :key="item.key"
          :label="item.label"
          :hint="item.hint"
        >
          <SettingsNumberStepper
            v-model="budget[item.key]"
            :min="item.min"
            :max="item.max"
            :step="item.step || 1"
            :disabled="!budget.enabled"
          />
        </SettingsFieldCard>
      </div>
    </section>

    <section class="system-card health-card">
      <div class="health-head">
        <div>
          <div class="card-title">
            <IconDatabaseZap :size="15" class="system-title-icon" />
            <span>数据库健康检查</span>
          </div>
          <p class="system-desc">
            quick_check 日常够用；integrity_check 会完整扫描数据库，大库或 NAS 上会明显更慢。
          </p>
        </div>
        <div class="health-actions">
          <StatefulButton
            class="health-stateful-btn"
            tone="neutral"
            size="sm"
            :success-hold="1200"
            @click="runHealth(false)"
          >
            <template #prefix="{ state }">
              <IconLoader2 v-if="state === 'loading'" :size="14" class="health-spin" />
              <IconCheckCircle2 v-else-if="state === 'success'" :size="14" />
              <IconRefreshCw v-else :size="14" />
            </template>
            quick_check
          </StatefulButton>
          <StatefulButton
            class="health-stateful-btn"
            tone="warning"
            size="sm"
            :success-hold="1200"
            @click="runHealth(true)"
          >
            <template #prefix="{ state }">
              <IconLoader2 v-if="state === 'loading'" :size="14" class="health-spin" />
              <IconCheckCircle2 v-else-if="state === 'success'" :size="14" />
              <IconShieldCheck v-else :size="14" />
            </template>
            integrity_check
          </StatefulButton>
        </div>
      </div>

      <div v-if="healthResult" class="health-result" :class="healthResult.ok ? 'is-ok' : 'is-error'">
        <div class="health-status">
          <span class="health-chip" :class="healthResult.ok ? 'is-ok' : 'is-error'">
            <component :is="healthResult.ok ? IconCheckCircle2 : IconAlertCircle" :size="13" :stroke-width="2.5" />
            {{ healthResult.ok ? '检查通过' : '检查失败' }}
          </span>
          <span class="health-meta">{{ healthResult.check || 'unknown' }} · {{ formatDuration(healthResult.duration_ms) }}</span>
        </div>

        <div class="health-stat-grid">
          <div v-for="item in healthStats" :key="item.label" class="health-stat-cell">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>

        <div v-if="healthMessages.length" class="health-messages">
          <span class="health-message-label">返回信息</span>
          <code v-for="message in healthMessages" :key="message" class="health-message">{{ message }}</code>
        </div>
        <div v-if="healthResult.error" class="health-error-line">
          <IconAlertCircle :size="13" />
          <span>{{ healthResult.error }}</span>
        </div>
      </div>

      <div v-else class="health-empty">
        <IconDatabaseZap :size="16" />
        <span>还没有现场检查结果。保存运行参数后，建议先重启服务，再回来跑一次 quick_check。</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertCircle as IconAlertCircle,
  CheckCircle2 as IconCheckCircle2,
  DatabaseZap as IconDatabaseZap,
  Gauge as IconGauge,
  Loader2 as IconLoader2,
  RefreshCw as IconRefreshCw,
  ServerCog as IconServerCog,
  ShieldCheck as IconShieldCheck,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { databaseMaintenanceApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const defaultDatabaseConfig = {
  journal_mode: 'WAL',
  synchronous: 'FULL',
  busy_timeout_ms: 60000,
  wal_autocheckpoint: 500,
  cache_size_kb: 20000,
  pool_size: 2,
  max_overflow: 2,
  pool_recycle_seconds: 1800,
  startup_quick_check: true,
  startup_integrity_check: false,
}

const defaultResourceBudget = {
  enabled: true,
  disk_io_local: 2,
  archive_cpu: 0,
  archive_inspect: 0,
  remote_fs: 4,
  network_download: 5,
  sqlite_write: 1,
}

const journalModeOptions = [
  { value: 'WAL', label: 'WAL', description: '推荐：读写并发更好，配合 checkpoint 管理 -wal' },
  { value: 'DELETE', label: 'DELETE', description: '传统 rollback journal，写入期间读写互斥更明显' },
  { value: 'TRUNCATE', label: 'TRUNCATE', description: '提交后截断 rollback journal，适合少数兼容场景' },
  { value: 'PERSIST', label: 'PERSIST', description: '保留 journal 文件并清头，减少文件创建开销' },
  { value: 'MEMORY', label: 'MEMORY', description: 'journal 放内存，断电/崩溃风险更高' },
  { value: 'OFF', label: 'OFF', description: '关闭 journal，只建议临时压测或一次性导入前明确承担风险' },
]

const synchronousOptions = [
  { value: 'FULL', label: 'FULL', description: '推荐 NAS / Docker 卷：更强掉电保护' },
  { value: 'NORMAL', label: 'NORMAL', description: '吞吐更高；断电或底层 I/O 异常时风险更大' },
  { value: 'EXTRA', label: 'EXTRA', description: '最保守，通常只用于极端安全场景' },
  { value: 'OFF', label: 'OFF', description: '不等待同步刷盘，只建议临时压测，不建议长期运行' },
]

const budgetItems = [
  { key: 'sqlite_write', label: 'SQLite 写入', hint: '操作历史、库存索引等同步写入队列；启用时最低实际为 1。', min: 0, max: 8 },
  { key: 'disk_io_local', label: '本地磁盘 IO', hint: '本地复制、上传入库、打包扫描、临时视图复制等慢盘操作。', min: 0, max: 16 },
  { key: 'remote_fs', label: '远程库存 / 群晖', hint: 'FileStation 列表、下载、上传、远程库存索引重建。', min: 0, max: 20 },
  { key: 'network_download', label: '网络下载', hint: 'HTTP、Google Drive、Transfer.it、百度 PCSGo、ASMR 下载等。', min: 0, max: 50 },
  { key: 'archive_cpu', label: '解压 CPU', hint: '7zz / unar 实际解压子进程，建议按 CPU 和磁盘吞吐一起调。', min: 0, max: 16 },
  { key: 'archive_inspect', label: '压缩包探测', hint: '7zz l / 密码探测 / 伪装压缩包识别等轻量但高频操作。', min: 0, max: 32 },
]

const healthResult = ref(null)

const db = computed(() => props.config.database)
const budget = computed(() => props.config.resource_budget)

const healthMessages = computed(() => {
  const messages = healthResult.value?.messages
  return Array.isArray(messages) ? messages : []
})

const healthStats = computed(() => {
  const result = healthResult.value || {}
  return [
    { label: '主库', value: formatBytes(result.main_size_bytes) },
    { label: 'WAL', value: formatBytes(result.wal_size_bytes) },
    { label: 'SHM', value: formatBytes(result.shm_size_bytes) },
    { label: '运行参数', value: `${result.journal_mode || '—'} / ${result.synchronous || '—'}` },
    { label: '连接池', value: `${result.pool_size ?? '—'} + ${result.max_overflow ?? '—'}` },
    { label: 'Checkpoint', value: result.wal_autocheckpoint ?? '—' },
  ]
})

function ensureSystemConfig() {
  if (!props.config.database) {
    props.config.database = { ...defaultDatabaseConfig }
  } else {
    Object.assign(props.config.database, { ...defaultDatabaseConfig, ...props.config.database })
  }
  if (!props.config.resource_budget) {
    props.config.resource_budget = { ...defaultResourceBudget }
  } else {
    Object.assign(props.config.resource_budget, { ...defaultResourceBudget, ...props.config.resource_budget })
  }
}

function normalizeToggleDependencies() {
  if (!db.value.startup_quick_check) {
    db.value.startup_integrity_check = false
  }
}

async function runHealth(full) {
  try {
    const result = await databaseMaintenanceApi.health(Boolean(full))
    healthResult.value = result
    if (result?.ok) {
      ElMessage.success(`${result.check || '数据库检查'} 通过`)
    } else {
      ElMessage.error(`${result?.check || '数据库检查'} 失败`)
      return false
    }
    return true
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '数据库健康检查失败'
    healthResult.value = {
      ok: false,
      check: full ? 'integrity_check' : 'quick_check',
      error: String(detail),
      messages: [],
      duration_ms: 0,
    }
    ElMessage.error(String(detail))
    return false
  }
}

function formatBytes(bytes) {
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
  const seconds = n / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds - minutes * 60)
  return `${minutes}m ${rest}s`
}

function formatMs(ms) {
  const n = Number(ms ?? 0)
  if (!Number.isFinite(n) || n <= 0) return '0ms'
  if (n < 1000) return `${Math.round(n)}ms`
  return `${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}s`
}

onMounted(() => {
  ensureSystemConfig()
  normalizeToggleDependencies()
})

watch(() => props.config, ensureSystemConfig, { immediate: true })
watch(() => db.value?.startup_quick_check, normalizeToggleDependencies)
</script>

<style scoped>
.system-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.mini-grid {
  display: grid;
  gap: 10px;
}

.mini-grid.two {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
}

.mini-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.field-stack {
  display: grid;
  gap: 12px;
}

.system-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  min-height: 0;
  overflow: visible;
}

.system-hero-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.system-hero-copy {
  min-width: 0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 10px;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.system-title-icon {
  color: var(--set-nav-system-icon, #0f766e);
}

.system-desc {
  max-width: 860px;
  margin: 0;
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.65;
}

.system-runtime-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: min(100%, 360px);
}

.runtime-pill,
.health-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid var(--set-border);
  border-radius: 999px;
  background: var(--set-chip-bg);
  color: var(--set-chip-text-strong);
  font-size: 12px;
  font-weight: 600;
}

.resource-head {
  margin: 16px 0 14px;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px 18px;
}

.settings-field-dd {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-root),
.settings-field-dd :deep(.app-dd-trigger-anchor) {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) {
  border-color: var(--set-border-strong);
}

.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.health-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
}

.health-actions {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.health-stateful-btn {
  --stateful-button-icon-size: 14px;
}

.health-stateful-btn :deep(.stateful-button__content) {
  gap: 7px;
}

.health-stateful-btn :deep(.stateful-button__state) {
  width: 14px;
  height: 14px;
}

.health-spin {
  animation: system-spin 0.65s linear infinite;
}

.health-result,
.health-empty {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--set-border);
  border-radius: 18px;
  background: var(--set-surface-soft);
}

.health-result.is-ok {
  border-color: var(--set-success-border);
  background: var(--set-success-bg);
}

.health-result.is-error {
  border-color: var(--set-danger-border);
  background: var(--set-danger-bg);
}

.health-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.health-chip.is-ok {
  border-color: var(--set-success-border);
  background: rgba(255, 255, 255, 0.32);
  color: var(--set-success-text);
}

.health-chip.is-error {
  border-color: var(--set-danger-border);
  background: rgba(255, 255, 255, 0.32);
  color: var(--set-danger-text);
}

.health-meta {
  color: var(--set-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.health-stat-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.health-stat-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--set-border-soft);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.42);
}

.health-stat-cell span {
  color: var(--set-text-muted);
  font-size: 11.5px;
}

.health-stat-cell strong {
  overflow: hidden;
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.health-messages {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.health-message-label {
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-weight: 600;
}

.health-message {
  display: block;
  overflow: auto;
  padding: 8px 10px;
  border: 1px solid var(--set-border-soft);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.05);
  color: var(--set-text-strong);
  font-size: 12px;
  white-space: pre-wrap;
}

.health-error-line,
.health-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.55;
}

.health-error-line {
  margin-top: 12px;
  color: var(--set-danger-text);
}

:global(html.kikoerumanager-dark .settings-page .health-stat-cell),
:global(body.kikoerumanager-dark .settings-page .health-stat-cell) {
  background: rgba(255, 255, 255, 0.05);
}

:global(html.kikoerumanager-dark .settings-page .health-message),
:global(body.kikoerumanager-dark .settings-page .health-message) {
  background: rgba(255, 255, 255, 0.06);
}

@keyframes system-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.three,
  .budget-grid,
  .health-stat-grid {
    grid-template-columns: 1fr;
  }

  .system-hero-card,
  .health-head {
    flex-direction: column;
  }

  .system-runtime-strip,
  .health-actions {
    justify-content: flex-start;
    width: 100%;
  }
}
</style>
