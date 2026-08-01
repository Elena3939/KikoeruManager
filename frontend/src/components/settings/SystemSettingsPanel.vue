<template>
  <div class="system-stack">
    <section class="system-card system-hero-card">
      <div class="system-hero-copy">
        <div class="card-title">
          <IconServerCog :size="15" class="system-title-icon" />
          <span>PostgreSQL 运行配置</span>
        </div>
        <p class="system-desc">
          这里控制 PostgreSQL 连接地址、连接池、语句超时和启动健康检查。保存后需要重启后端进程才会应用到当前 engine；DATABASE_URL 会覆盖这些字段。
        </p>
      </div>
      <div class="system-runtime-strip">
        <span class="runtime-pill">{{ db.host }}:{{ db.port }} / {{ db.database }}</span>
        <span class="runtime-pill">连接池 {{ db.pool_size }} + {{ db.max_overflow }}</span>
        <span class="runtime-pill">SQL {{ formatMs(db.statement_timeout_ms) }}</span>
      </div>
    </section>

    <div class="settings-grid two">
      <section class="system-card">
        <div class="card-title">连接信息</div>
        <div class="field-stack">
          <div class="mini-grid two">
            <SettingsFieldCard label="Host" hint="本地默认 127.0.0.1；Docker compose 使用服务名 postgres。">
              <input v-model="db.host" class="settings-inline-input" autocomplete="off" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Port" hint="PostgreSQL 默认端口。">
              <SettingsNumberStepper v-model="db.port" :min="1" :max="65535" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid two">
            <SettingsFieldCard label="Database" hint="应用业务库名，默认 kikoerumanager。">
              <input v-model="db.database" class="settings-inline-input" autocomplete="off" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Username" hint="应用角色名，默认 kikoerumanager。">
              <input v-model="db.username" class="settings-inline-input" autocomplete="off" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid two">
            <SettingsFieldCard label="Password" hint="API 返回时会脱敏；保存 ******** 会保留磁盘真实密码。">
              <AnimatedPasswordInput
                v-model="db.password"
                :reveal-value="databaseRevealedPassword"
                autocomplete="new-password"
                @visibility-change="handleDatabasePasswordVisibility"
              />
            </SettingsFieldCard>
            <SettingsFieldCard label="SSL Mode" hint="本地通常 prefer；Docker 内网可由 DATABASE_URL 使用 disable。">
              <input v-model="db.sslmode" class="settings-inline-input" autocomplete="off" />
            </SettingsFieldCard>
          </div>
        </div>
      </section>

      <section class="system-card">
        <div class="card-title">连接池与启动自检</div>
        <div class="field-stack">
          <div class="mini-grid three">
            <SettingsFieldCard label="Pool Size" hint="常驻连接数。数据库写入单写者，别盲目拉满。">
              <SettingsNumberStepper v-model="db.pool_size" :min="1" :max="20" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Max Overflow" hint="突发额外连接数。之前硬编码 10，现在可控。">
              <SettingsNumberStepper v-model="db.max_overflow" :min="0" :max="30" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Pool Recycle" hint="连接回收秒数，避免长时间挂起的旧连接。">
              <SettingsNumberStepper v-model="db.pool_recycle_seconds" :min="60" :max="86400" :step="60" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid three">
            <SettingsFieldCard label="Connect Timeout" hint="建立连接的超时秒数。">
              <SettingsNumberStepper v-model="db.connect_timeout_seconds" :min="1" :max="120" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Pool Timeout" hint="等待连接池可用连接的超时秒数。">
              <SettingsNumberStepper v-model="db.pool_timeout_seconds" :min="1" :max="300" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Statement Timeout" hint="单条 SQL 最大执行时间，单位 ms。">
              <SettingsNumberStepper v-model="db.statement_timeout_ms" :min="1000" :max="600000" :step="1000" />
            </SettingsFieldCard>
          </div>

          <SettingsToggleRow
            v-model="db.startup_health_check"
            title="启动时 PostgreSQL 健康检查"
            subtitle="后端启动时先执行 SELECT 1 并读取服务版本；失败会阻止继续启动。"
          />
        </div>
      </section>
    </div>

    <section class="system-card redis-card">
      <div class="health-head">
        <div>
          <div class="card-title">
            <IconDatabase :size="15" class="system-title-icon" />
            <span>Redis 运行态配置</span>
          </div>
          <p class="system-desc">
            Redis 只承载任务运行态、实时事件和高频短缓存；PostgreSQL 仍是事实源。保存 URL、开关或 namespace 后需要重启后端进程才会完全应用。
          </p>
        </div>
        <div class="health-actions" aria-label="Redis 运行态操作">
          <StatefulButton
            class="health-stateful-btn health-stateful-btn--quick"
            tone="neutral"
            size="sm"
            aria-label="刷新 Redis 运行态"
            :success-hold="1200"
            @click="refreshRedisStatus"
          >
            <template #prefix="{ state }">
              <IconLoader2 v-if="state === 'loading'" :size="15" class="health-spin" />
              <IconCheckCircle2 v-else-if="state === 'success'" :size="15" class="health-action-icon" />
              <IconRefreshCw v-else :size="15" class="health-action-icon" />
            </template>
            <span class="health-btn-label">刷新 Redis</span>
            <span class="health-btn-code">PING</span>
          </StatefulButton>
        </div>
      </div>

      <div class="redis-status-strip">
        <span class="health-chip" :class="redis.enabled ? 'is-ok' : ''">
          <component :is="redis.enabled ? IconCheckCircle2 : IconAlertCircle" :size="13" :stroke-width="2.5" />
          {{ redis.enabled ? '已启用' : '已禁用' }}
        </span>
        <span class="runtime-pill">{{ redis.required ? '启动强依赖' : '允许降级' }}</span>
        <span class="runtime-pill">{{ redis.namespace || 'kikoerumanager' }} / {{ redis.environment || 'prod' }}</span>
        <span v-if="redisStatus" class="health-chip" :class="redisStatus.available ? 'is-ok' : 'is-error'">
          <component :is="redisStatus.available ? IconCheckCircle2 : IconAlertCircle" :size="13" :stroke-width="2.5" />
          {{ redisStatus.available ? '连接正常' : '连接不可用' }}
        </span>
      </div>

      <div class="field-stack redis-form-stack">
        <div class="redis-toggle-grid">
          <SettingsToggleRow
            v-model="redis.enabled"
            title="启用 Redis"
            subtitle="禁用后任务运行态和事件流回退到内存 / 数据库路径。"
          />
          <SettingsToggleRow
            v-model="redis.required"
            :disabled="!redis.enabled"
            title="启动时必须可用"
            subtitle="启用后 Redis ping 失败会阻断后端启动；不稳定环境可关闭。"
          />
        </div>

        <SettingsFieldCard label="Redis URL" hint="接口默认仍脱敏返回；点击显示原始 URL 后从运行环境或配置文件读取真实连接串，随后可在左侧明文编辑并保存。">
          <div class="redis-url-row">
            <input v-model="redis.url" class="settings-inline-input redis-url-input" autocomplete="off" />
            <StatefulButton
              class="health-stateful-btn redis-reveal-btn"
              tone="neutral"
              size="sm"
              aria-label="显示原始 Redis URL"
              :success-hold="1200"
              @click="fetchOriginalRedisUrl"
            >
              <template #prefix="{ state }">
                <IconLoader2 v-if="state === 'loading'" :size="15" class="health-spin" />
                <IconCheckCircle2 v-else-if="state === 'success'" :size="15" class="health-action-icon" />
                <IconEye v-else :size="15" class="health-action-icon" />
              </template>
              <span class="health-btn-label">显示原始</span>
            </StatefulButton>
          </div>
        </SettingsFieldCard>

        <div class="mini-grid two">
          <SettingsFieldCard label="Namespace" hint="同一个 Redis 中隔离不同产品或实例，默认 kikoerumanager。">
            <input v-model="redis.namespace" class="settings-inline-input" autocomplete="off" />
          </SettingsFieldCard>
          <SettingsFieldCard label="Environment" hint="同一个 namespace 下隔离 prod、dev 等运行环境。">
            <input v-model="redis.environment" class="settings-inline-input" autocomplete="off" />
          </SettingsFieldCard>
        </div>

        <div class="mini-grid three">
          <SettingsFieldCard label="Socket Timeout" hint="读写 Redis 的 socket 超时秒数。">
            <SettingsNumberStepper v-model="redis.socket_timeout_seconds" :min="0.1" :max="60" :step="0.1" />
          </SettingsFieldCard>
          <SettingsFieldCard label="Connect Timeout" hint="建立 Redis 连接的超时秒数。">
            <SettingsNumberStepper v-model="redis.connect_timeout_seconds" :min="0.1" :max="60" :step="0.1" />
          </SettingsFieldCard>
          <SettingsFieldCard label="Runtime TTL" hint="任务运行态和短期 overlay 的保留秒数。">
            <SettingsNumberStepper v-model="redis.runtime_ttl_seconds" :min="60" :max="2592000" :step="60" />
          </SettingsFieldCard>
        </div>

        <div class="mini-grid three">
          <SettingsFieldCard label="Short Cache TTL" hint="短缓存默认保留秒数。">
            <SettingsNumberStepper v-model="redis.short_cache_ttl_seconds" :min="1" :max="3600" />
          </SettingsFieldCard>
          <SettingsFieldCard label="Event Stream MaxLen" hint="实时事件 Redis Stream 近似最大长度。">
            <SettingsNumberStepper v-model="redis.event_stream_maxlen" :min="100" :max="1000000" :step="1000" />
          </SettingsFieldCard>
          <SettingsFieldCard label="Dirty Stream MaxLen" hint="DLsite 特典缓存 dirty buffer 近似最大长度。">
            <SettingsNumberStepper v-model="redis.dirty_stream_maxlen" :min="100" :max="2000000" :step="1000" />
          </SettingsFieldCard>
        </div>
      </div>

      <div v-if="redisStatus" class="health-result redis-status-result" :class="redisStatus.available ? 'is-ok' : 'is-error'">
        <div class="health-status">
          <span class="health-chip" :class="redisStatus.available ? 'is-ok' : 'is-error'">
            <component :is="redisStatus.available ? IconCheckCircle2 : IconAlertCircle" :size="13" :stroke-width="2.5" />
            {{ redisStatus.available ? 'Redis 可用' : 'Redis 不可用' }}
          </span>
          <span class="health-meta">{{ redisStatus.url_masked || redis.url || '未配置 URL' }}</span>
        </div>

        <div class="health-stat-grid redis-stat-grid">
          <div v-for="item in redisStats" :key="item.label" class="health-stat-cell">
            <span>{{ item.label }}</span>
            <strong :title="String(item.value)">{{ item.value }}</strong>
          </div>
        </div>

        <div v-if="redisStatus.last_error" class="health-error-line">
          <IconAlertCircle :size="13" />
          <span>{{ redisStatus.last_error }}</span>
        </div>
      </div>

      <div v-else class="health-empty redis-empty">
        <IconDatabase :size="16" />
        <span>还没有 Redis 现场状态。点击“刷新 Redis”会读取当前后端运行态，不会保存配置。</span>
      </div>
    </section>

    <section class="system-card">
      <div class="card-title">
        <IconGauge :size="15" class="system-title-icon" />
        <span>全局资源预算</span>
      </div>
      <p class="system-desc">
        这些令牌会被真实业务链路消耗：数据库写入、远程库存、HTTP / 百度下载、本地磁盘复制、解压和压缩包探测。
        值为 0 表示该资源不限制；数据库写入在启用预算时最低会收敛为 1。
      </p>

      <div class="resource-head">
        <SettingsToggleRow
          v-model="budget.enabled"
          title="启用资源预算"
          subtitle="用轻量背压避免下载、解压、远程库扫描和 数据库写入互相打满。"
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
            基础检查执行 SELECT 1；完整检查会额外 ANALYZE 热点表，用于更新 planner 统计信息。
          </p>
        </div>
        <div class="health-actions" aria-label="数据库健康检查操作">
          <StatefulButton
            class="health-stateful-btn health-stateful-btn--quick"
            tone="neutral"
            size="sm"
            aria-label="运行 SELECT 1 基础检查"
            :success-hold="1200"
            @click="runHealth(false)"
          >
            <template #prefix="{ state }">
              <IconLoader2 v-if="state === 'loading'" :size="15" class="health-spin" />
              <IconCheckCircle2 v-else-if="state === 'success'" :size="15" class="health-action-icon" />
              <IconRefreshCw v-else :size="15" class="health-action-icon" />
            </template>
            <span class="health-btn-label">快速检查</span>
            <span class="health-btn-code">SELECT 1</span>
          </StatefulButton>
          <StatefulButton
            class="health-stateful-btn health-stateful-btn--full"
            tone="neutral"
            size="sm"
            aria-label="运行 ANALYZE 完整检查"
            :success-hold="1200"
            @click="runHealth(true)"
          >
            <template #prefix="{ state }">
              <IconLoader2 v-if="state === 'loading'" :size="15" class="health-spin" />
              <IconCheckCircle2 v-else-if="state === 'success'" :size="15" class="health-action-icon" />
              <IconShieldCheck v-else :size="15" class="health-action-icon" />
            </template>
            <span class="health-btn-label">完整检查</span>
            <span class="health-btn-code">ANALYZE</span>
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
        <span>还没有现场检查结果。保存运行参数后，建议先重启服务，再回来跑一次 SELECT 1。</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertCircle as IconAlertCircle,
  CheckCircle2 as IconCheckCircle2,
  Database as IconDatabase,
  DatabaseZap as IconDatabaseZap,
  Eye as IconEye,
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
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { configApi, databaseMaintenanceApi, systemRuntimeApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const defaultDatabaseConfig = {
  host: '127.0.0.1',
  port: 5432,
  database: 'kikoerumanager',
  username: 'kikoerumanager',
  password: '',
  sslmode: 'prefer',
  connect_timeout_seconds: 10,
  pool_size: 10,
  max_overflow: 20,
  pool_recycle_seconds: 1800,
  pool_timeout_seconds: 30,
  statement_timeout_ms: 120000,
  startup_health_check: true,
}

const defaultResourceBudget = {
  enabled: true,
  disk_io_local: 2,
  archive_cpu: 0,
  archive_inspect: 0,
  remote_fs: 4,
  network_download: 5,
  database_write: 1,
  library_index_write: 1,
  bonus_probe_database_write: 1,
}

const defaultRedisConfig = {
  enabled: true,
  required: true,
  url: 'redis://localhost:6379/0',
  namespace: 'kikoerumanager',
  environment: 'prod',
  socket_timeout_seconds: 2.0,
  connect_timeout_seconds: 2.0,
  runtime_ttl_seconds: 259200,
  short_cache_ttl_seconds: 60,
  event_stream_maxlen: 50000,
  dirty_stream_maxlen: 200000,
}

const budgetItems = [
  { key: 'database_write', label: '业务数据库写入', hint: '任务中心、操作历史、配置保存等业务写入队列；启用时最低实际为 1。', min: 0, max: 8 },
  { key: 'library_index_write', label: '库存索引写入', hint: '库存索引后台追赶写入队列，和业务数据库写入分离。', min: 0, max: 4 },
  { key: 'disk_io_local', label: '本地磁盘 IO', hint: '本地复制、上传入库、打包扫描、临时视图复制等慢盘操作。', min: 0, max: 16 },
  { key: 'remote_fs', label: '远程库存 / 群晖', hint: 'FileStation 列表、搜索、下载、上传等群晖接口操作。', min: 0, max: 20 },
  { key: 'network_download', label: '网络下载', hint: 'HTTP、Google Drive、Transfer.it、百度 PCSGo、ASMR 下载等。', min: 0, max: 50 },
  { key: 'archive_cpu', label: '解压 CPU', hint: '7zz / unar 实际解压子进程，建议按 CPU 和磁盘吞吐一起调。', min: 0, max: 16 },
  { key: 'archive_inspect', label: '压缩包探测', hint: '7zz l / 密码探测 / 伪装压缩包识别等轻量但高频操作。', min: 0, max: 32 },
]

const healthResult = ref(null)
const redisStatus = ref(null)
const databasePasswordRevealing = ref(false)
const databaseRevealedPassword = ref('')
const redisUrlRevealing = ref(false)

const db = computed(() => props.config.database)
const budget = computed(() => props.config.resource_budget)
const redis = computed(() => props.config.redis)

const healthMessages = computed(() => {
  const messages = healthResult.value?.messages
  return Array.isArray(messages) ? messages : []
})

const healthStats = computed(() => {
  const result = healthResult.value || {}
  const sizeText = (value) => value === undefined || value === null ? '完整检查采集' : formatBytes(value)
  return [
    { label: '数据库大小', value: sizeText(result.database_size_bytes) },
    { label: '操作历史表', value: sizeText(result.activity_logs_size_bytes) },
    { label: '库存索引表', value: sizeText(result.library_index_size_bytes) },
    { label: 'pg_trgm', value: result.pg_trgm_enabled ? '已启用' : '未启用' },
    { label: '连接池', value: `${result.pool_size ?? '—'} + ${result.max_overflow ?? '—'}` },
    { label: 'SQL 超时', value: formatMs(result.statement_timeout_ms) },
  ]
})

const redisStats = computed(() => {
  const status = redisStatus.value || {}
  const streams = status.streams || {}
  const keys = status.keys || {}
  const memory = status.memory || {}
  return [
    { label: '启用状态', value: status.enabled ? '已启用' : '已禁用' },
    { label: '强依赖', value: status.required ? '是' : '否' },
    { label: '延迟', value: status.latency_ms === null || status.latency_ms === undefined ? '—' : `${status.latency_ms}ms` },
    { label: '事件 Stream', value: formatRedisStreamInfo(streams.events) },
    { label: '任务中心 Stream', value: formatRedisStreamInfo(streams.task_center) },
    { label: '特典 Dirty Stream', value: formatRedisStreamInfo(streams.bonus_probe_cache) },
    { label: '任务运行态 Key', value: formatRedisStatValue(keys.task_runtime ?? keys.tasks) },
    { label: '缓存 Key', value: formatRedisStatValue(keys.bonus_probe_cache ?? keys.cache) },
    { label: '内存', value: memory.used_memory_human || memory.used_memory || '—' },
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
  if (!props.config.redis) {
    props.config.redis = { ...defaultRedisConfig }
  } else {
    Object.assign(props.config.redis, { ...defaultRedisConfig, ...props.config.redis })
  }
}

async function refreshRedisStatus() {
  try {
    const result = await systemRuntimeApi.redisStatus()
    redisStatus.value = result
    if (result?.available || !result?.enabled) {
      ElMessage.success(result?.enabled ? 'Redis 连接正常' : 'Redis 已禁用')
    } else {
      ElMessage.error(result?.last_error || 'Redis 连接不可用')
      return false
    }
    return true
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || 'Redis 状态读取失败'
    redisStatus.value = {
      enabled: redis.value?.enabled ?? true,
      required: redis.value?.required ?? true,
      available: false,
      url_masked: redis.value?.url || '',
      namespace: redis.value?.namespace || '',
      environment: redis.value?.environment || '',
      latency_ms: null,
      last_error: String(detail),
      streams: {},
      keys: {},
      memory: {},
    }
    ElMessage.error(String(detail))
    return false
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
      check: full ? 'vacuum_analyze_probe' : 'select_1',
      error: String(detail),
      messages: [],
      duration_ms: 0,
    }
    ElMessage.error(String(detail))
    return false
  }
}

async function handleDatabasePasswordVisibility(visible) {
  if (!visible) return
  if (db.value?.password !== '********' || databaseRevealedPassword.value || databasePasswordRevealing.value) return
  if (databasePasswordRevealing.value) return
  databasePasswordRevealing.value = true
  try {
    const result = await configApi.revealDatabaseSecret({ key: 'password' })
    databaseRevealedPassword.value = result?.value || ''
    if (!result?.value) {
      ElMessage.warning('配置文件里没有可显示的原始数据库密码')
    }
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '读取数据库密码失败'
    ElMessage.error(String(detail))
  } finally {
    databasePasswordRevealing.value = false
  }
}

async function fetchOriginalRedisUrl() {
  if (redisUrlRevealing.value) return false
  redisUrlRevealing.value = true
  try {
    const result = await configApi.revealRedisSecret({ key: 'url' })
    if (result?.value) {
      redis.value.url = result.value
      ElMessage.success('已显示原始 Redis URL')
      return true
    } else {
      ElMessage.warning('配置文件里没有可显示的原始 Redis URL')
      return false
    }
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '读取 Redis URL 失败'
    ElMessage.error(String(detail))
    return false
  } finally {
    redisUrlRevealing.value = false
  }
}

function formatRedisStreamInfo(value) {
  if (!value) return '—'
  if (typeof value !== 'object') return String(value)
  const length = value.length ?? value.len ?? '—'
  const pending = value.pending
  return pending === undefined || pending === null ? String(length) : `${length} / ${pending} pending`
}

function formatRedisStatValue(value) {
  return value === undefined || value === null || value === '' ? '—' : String(value)
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
})

watch(() => props.config, ensureSystemConfig, { immediate: true })
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

.redis-card {
  display: grid;
  gap: 16px;
}

.redis-status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.redis-form-stack {
  margin-top: 2px;
}

.redis-url-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.redis-url-input {
  font-family: "SF Mono", "Cascadia Code", Consolas, monospace;
  font-size: 12.5px;
}

.redis-reveal-btn {
  min-width: 118px;
}

.redis-toggle-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
}

.redis-status-result,
.redis-empty {
  margin-top: 0;
}

.redis-stat-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px 18px;
}

.settings-inline-input {
  display: block;
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  color: var(--set-text-strong);
  font-size: 13.5px;
  outline: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.settings-inline-input:hover {
  border-color: var(--set-border-strong);
}

.settings-inline-input:focus,
.settings-inline-input:focus-visible {
  border-color: var(--set-border-strong);
  box-shadow: none;
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
  --stateful-button-icon-size: 15px;
  min-width: 132px;
  min-height: 38px;
  height: 38px;
  padding: 0 13px;
  border: 1px solid var(--set-border);
  border-radius: 999px;
  background: var(--set-surface);
  color: var(--set-text-strong);
  box-shadow: none;
  white-space: nowrap;
}

.health-stateful-btn--full {
  border-color: var(--set-warning-border);
  background: color-mix(in srgb, var(--set-warning-bg) 58%, var(--set-surface));
  color: var(--set-warning-text);
}

.health-stateful-btn:not(:disabled):hover {
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  box-shadow: none;
}

.health-stateful-btn--full:not(:disabled):hover {
  border-color: var(--set-warning-border);
  background: var(--set-warning-bg);
}

.health-stateful-btn :deep(.stateful-button__content) {
  gap: 7px;
}

.health-stateful-btn :deep(.stateful-button__state) {
  width: 16px;
  height: 16px;
}

.health-stateful-btn :deep(.stateful-button__label) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.health-btn-label {
  color: currentColor;
  font-size: 12.5px;
  font-weight: 700;
}

.health-btn-code {
  color: var(--set-text-muted);
  font-family: "SF Mono", "Cascadia Code", Consolas, monospace;
  font-size: 10px;
  font-weight: 700;
}

.health-stateful-btn--full .health-btn-code {
  color: color-mix(in srgb, var(--set-warning-text) 72%, var(--set-text-muted));
}

.health-action-icon {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.health-stateful-btn--quick:not(:disabled):hover .health-action-icon {
  transform: rotate(-28deg) scale(1.08);
}

.health-stateful-btn--full:not(:disabled):hover .health-action-icon {
  transform: rotate(10deg) scale(1.08);
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

:global(html.kikoerumanager-dark .settings-page .health-stateful-btn),
:global(body.kikoerumanager-dark .settings-page .health-stateful-btn) {
  background: rgba(255, 255, 255, 0.055);
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(245, 245, 245, 0.92);
}

:global(html.kikoerumanager-dark .settings-page .health-stateful-btn:not(:disabled):hover),
:global(body.kikoerumanager-dark .settings-page .health-stateful-btn:not(:disabled):hover) {
  background: rgba(255, 255, 255, 0.085);
  border-color: rgba(255, 255, 255, 0.2);
}

:global(html.kikoerumanager-dark .settings-page .health-stateful-btn--full),
:global(body.kikoerumanager-dark .settings-page .health-stateful-btn--full) {
  background: rgba(251, 191, 36, 0.11);
  border-color: rgba(251, 191, 36, 0.28);
  color: #fcd34d;
}

:global(html.kikoerumanager-dark .settings-page .health-stateful-btn--full:not(:disabled):hover),
:global(body.kikoerumanager-dark .settings-page .health-stateful-btn--full:not(:disabled):hover) {
  background: rgba(251, 191, 36, 0.16);
  border-color: rgba(251, 191, 36, 0.38);
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
  .redis-toggle-grid,
  .redis-url-row,
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

  .health-actions {
    min-width: 0;
  }
}

@media (max-width: 520px) {
  .health-stateful-btn {
    min-width: min(100%, 160px);
  }
}
</style>
