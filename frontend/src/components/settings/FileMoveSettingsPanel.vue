<template>
  <div class="move-stack">
    <section class="move-card">
      <div class="move-heading">
        <div>
          <h3><HardDrive :size="17" /> 文件移动加速</h3>
          <p>优先重命名；遇到跨挂载时，同文件系统使用宿主快速克隆，跨文件系统流式复制。</p>
        </div>
        <StatefulButton class="move-action" size="sm" tone="neutral" :disabled="refreshing" @click="refresh">
          <template #prefix="{ state }">
            <LoaderCircle v-if="state === 'loading'" :size="15" class="move-spin" />
            <CircleCheck v-else-if="state === 'success'" :size="15" />
            <RefreshCw v-else :size="15" />
          </template>
          刷新状态
        </StatefulButton>
      </div>
      <div class="move-badges" aria-live="polite">
        <span class="move-badge" :class="{ good: status?.enabled }">
          当前配置：{{ status ? (status.enabled ? '已启用' : '未启用') : '读取中' }}
        </span>
        <span class="move-badge" :class="{ good: status?.online }">
          执行器：{{ status ? (status.online ? '在线' : '不可用') : '待检查' }}
        </span>
        <span class="move-badge" :class="{ good: status?.ready }">
          白名单：{{ status ? (status.ready ? '业务目录就绪' : '尚未就绪') : '待检查' }}
        </span>
      </div>
      <p v-if="error || status?.error" class="move-error" role="alert">{{ error || status.error }}</p>
      <p v-if="draftChanged" class="move-note">参数有未保存变更。下方状态和诊断使用服务器当前配置，保存后自动刷新。</p>
      <p v-if="status?.online && !status?.enabled" class="move-note">服务已在线，但应用尚未启用宿主加速。</p>
      <p v-if="status?.service" class="move-meta">
        启动于 {{ formatTime(status.service.started_at) }} · 协议 {{ status.service.protocol_version }}
        · 最大连接 {{ status.service.max_connections }} · 容器 {{ status.service.container_id?.slice(0, 12) }}
        <br />映射版本：{{ status.service.mapping_version }}
      </p>
      <p class="move-meta">状态检查时间：{{ status ? formatTime(status.checked_at) : '尚未完成' }} · 每 15 秒刷新</p>
    </section>

    <section class="move-card">
      <h3><Settings2 :size="17" /> 搬运参数</h3>
      <SettingsToggleRow
        v-model="settings.host_enabled"
        title="启用宿主快速克隆"
        subtitle="保存时验证执行器及业务目录。启用后执行器故障会明确报错并保留来源。"
      />
      <SettingsToggleRow
        v-model="settings.filter_verify_hashes"
        title="过滤文件搬运 SHA-256 校验"
        subtitle="流式复制和快速克隆共用此开关，默认关闭。适用于过滤保存、迁移、复原和回滚；开启会重读源文件与副本。关闭仍校验来源变化、目录成员和目标大小。"
      />
      <div class="move-grid">
        <SettingsFieldCard label="Unix socket 路径" hint="应用容器内路径；必须与已安装执行器的通信位置一致。">
          <input v-model="settings.socket_path" class="settings-inline-input" spellcheck="false" />
        </SettingsFieldCard>
        <SettingsFieldCard label="请求超时（秒）" hint="等待宿主单次操作的上限；超时不能视为操作已经停止。">
          <SettingsNumberStepper v-model="settings.request_timeout_seconds" :min="0.1" :max="3600" :step="1" />
        </SettingsFieldCard>
        <SettingsFieldCard label="恢复记录目录" hint="留空使用默认目录。存在未完成记录时禁止更改，避免丢失恢复入口。">
          <input v-model="settings.journal_path" class="settings-inline-input" placeholder="使用默认目录" spellcheck="false" />
        </SettingsFieldCard>
      </div>
      <p class="move-note">通过设置页顶部“保存”应用参数。开关影响后续搬运，不会把已经开始的复制转换为克隆。</p>
    </section>

    <section class="move-card">
      <h3><Activity :size="17" /> 路径与能力诊断</h3>
      <p>只读取文件系统身份，不创建文件。同文件系统仍需实际 FICLONE 验收才能确认克隆可用。</p>
      <div class="move-grid">
        <SettingsFieldCard label="来源目录">
          <AppDropdown v-model="source" class="move-directory-dropdown" :options="directoryOptions"
            placeholder="选择业务根目录" :disabled="!directoryOptions.length" />
        </SettingsFieldCard>
        <SettingsFieldCard label="目标目录">
          <AppDropdown v-model="destination" class="move-directory-dropdown" :options="directoryOptions"
            placeholder="选择业务根目录" :disabled="!directoryOptions.length" />
        </SettingsFieldCard>
      </div>
      <StatefulButton class="move-action" size="sm" tone="neutral" :disabled="!status?.online || !source || !destination" @click="probe">
        <template #prefix="{ state }">
          <LoaderCircle v-if="state === 'loading'" :size="15" class="move-spin" />
          <CircleCheck v-else-if="state === 'success'" :size="15" />
          <Activity v-else :size="15" />
        </template>
        检查文件系统
      </StatefulButton>
      <div v-if="probeResult" class="move-result" aria-live="polite">
        <strong>跨挂载时预计使用：{{ probeResult.method }}</strong>
        <p>{{ probeResult.source }} → {{ probeResult.destination }}</p>
        <p>来源：{{ probeResult.source_filesystem }}<br />目标：{{ probeResult.target_filesystem }}</p>
        <p>{{ probeResult.note }}</p>
      </div>
      <p v-if="probeError" class="move-error" role="alert">{{ probeError }}</p>
      <div class="move-paths">
        <div v-for="row in status?.roots || []" :key="row.path" class="move-path">
          <code>{{ row.path }}</code>
          <span :class="row.mapped && row.available && row.exists ? 'move-ok' : 'move-error'">
            {{ !row.exists ? '应用目录不存在' : row.mapped == null ? '映射状态未知（执行器未连接）' : !row.mapped ? '未映射' : !row.available ? '宿主目录不可访问' : '可访问' }}
          </span>
          <small>{{ row.filesystem || '文件系统身份未知' }}</small>
        </div>
      </div>
      <p class="move-note">目录映射由宿主安装工具根据真实 Docker 挂载生成，没有逐目录开关。使用上方“启用宿主快速克隆”统一控制；修改挂载或重建容器时须同步执行器绑定。</p>
    </section>

    <section class="move-card">
      <h3><Files :size="17" /> 搬运与恢复记录</h3>
      <p class="move-meta">{{ status?.journal?.path || '尚未读取' }}</p>
      <p v-if="status?.journal?.error" class="move-error">{{ status.journal.error }}</p>
      <div class="move-badges">
        <span v-for="(count, state) in status?.journal?.states || {}" :key="state" class="move-badge">
          {{ phaseLabels[state] || state }} {{ count }}
        </span>
      </div>
      <p v-if="status?.journal && !status.journal.sampled && !status.journal.error">当前没有未完成搬运记录。</p>
      <p v-if="status?.journal?.truncated">统计达到条数、读取量或耗时上限，结果不代表全部记录。</p>
      <p v-if="status?.journal?.invalid" class="move-error">有 {{ status.journal.invalid }} 条记录不可读取或过大，需要人工核对。</p>
      <p class="move-note">记录可能属于正在执行的任务，不能据此判定失败。此处只读，不触发重试或清理来源。</p>
      <p>快速克隆共享数据块，后续修改相互隔离；哈希校验仍会读取完整文件。克隆进度表示逻辑完成量，不代表真实磁盘写入速度。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, CircleCheck, Files, HardDrive, LoaderCircle, RefreshCw, Settings2 } from 'lucide-vue-next'
import { fileMoveApi } from '../../api'
import AppDropdown from '../common/AppDropdown.vue'
import StatefulButton from '../ui/stateful-button.vue'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'

const props = defineProps({ config: { type: Object, required: true } })
const settings = computed(() => props.config.file_move)
const status = ref(null)
const directoryOptions = computed(() => (status.value?.roots || []).map(row => ({ value: row.path, label: row.path })))
const error = ref('')
const refreshing = ref(false)
const source = ref('')
const destination = ref('')
const probeResult = ref(null)
const probeError = ref('')
const draftChanged = computed(() => status.value && JSON.stringify(settings.value) !== JSON.stringify(status.value.settings))
const phaseLabels = { preparing: '准备中', staged: '已暂存', backed_up: '旧目标已备份', published: '已发布', cleaning: '待清源' }
let timer
let disposed = false

function formatTime(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString() : '未知'
}

async function refresh() {
  if (refreshing.value) return false
  refreshing.value = true
  try {
    const result = await fileMoveApi.status()
    if (disposed) return
    status.value = result
    error.value = ''
    const roots = result.roots.map(row => row.path)
    if (!roots.includes(source.value)) source.value = roots[0] || ''
    if (!roots.includes(destination.value)) destination.value = roots.find(path => path !== source.value) || roots[0] || ''
    if (probeResult.value && probeResult.value.mapping_version !== result.service?.mapping_version) probeResult.value = null
  } catch (exc) {
    if (!disposed) {
      status.value = null
      probeResult.value = null
      error.value = exc.response?.data?.detail || exc.message
    }
    return false
  } finally {
    refreshing.value = false
  }
}

async function probe() {
  const selectedSource = source.value
  const selectedDestination = destination.value
  probeError.value = ''
  probeResult.value = null
  try {
    const result = await fileMoveApi.probe(selectedSource, selectedDestination)
    if (!disposed && source.value === selectedSource && destination.value === selectedDestination) probeResult.value = result
  } catch (exc) {
    if (!disposed) probeError.value = exc.response?.data?.detail || exc.message
    return false
  }
}

watch([source, destination], () => { probeResult.value = null; probeError.value = '' })
onMounted(() => {
  refresh()
  timer = setInterval(() => { if (!document.hidden) refresh() }, 15000)
})
onUnmounted(() => { disposed = true; clearInterval(timer) })
</script>

<style scoped>
.move-stack { display: grid; gap: 24px; min-width: 0; }
.move-card { display: grid; gap: 14px; padding: 0; border: none; background: transparent; min-width: 0; }
h3 { display: flex; align-items: center; gap: 8px; margin: 0; color: var(--set-text-strong); font-size: 13.5px; font-weight: 600; letter-spacing: -0.1px; }
h3 svg { flex-shrink: 0; }
p { margin: 0; color: var(--set-text-muted); font-size: 12.5px; line-height: 1.65; overflow-wrap: anywhere; }
.move-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.move-heading > div { min-width: 0; }
.move-heading p { margin-top: 8px; }
.move-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.move-badges { display: flex; flex-wrap: wrap; gap: 8px; }
.move-badge { border: 1px solid var(--set-border-soft); border-radius: 8px; padding: 5px 9px; background: var(--set-surface-soft); color: var(--set-text-muted); font-size: 12px; }
.move-badge.good { background: var(--set-success-bg); border-color: var(--set-success-border); color: var(--set-success-text); }
.move-ok { color: var(--set-success-text); }
.move-error { color: var(--set-warning-text); }
.move-note { padding: 10px 12px; background: var(--set-surface-soft); border-radius: 10px; }
.move-meta { font-size: 11px; overflow-wrap: anywhere; }
.move-paths { display: grid; gap: 8px; }
.move-path { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 5px 12px; padding: 10px 0; border-bottom: 1px solid var(--set-border-soft); font-size: 12px; }
.move-path code { overflow-wrap: anywhere; color: var(--set-text-strong); }
.move-path small { grid-column: 1 / -1; color: var(--set-text-muted); overflow-wrap: anywhere; }
.move-result { display: grid; gap: 6px; padding: 12px; border: 1px solid var(--set-border); background: var(--set-surface-soft); border-radius: 10px; font-size: 13px; color: var(--set-text-strong); overflow-wrap: anywhere; }
.settings-inline-input { display: block; width: 100%; min-width: 0; height: 38px; padding: 0 12px; border: 1px solid var(--set-border); border-radius: 10px; background: var(--set-field-bg); color: var(--set-text-strong); font-size: 13.5px; outline: none; transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.settings-inline-input:hover,
.settings-inline-input:focus { border-color: var(--set-border-strong); box-shadow: none; }
.settings-inline-input::placeholder { color: var(--set-text-subtle); }
.move-directory-dropdown { width: 100%; min-width: 0; }
.move-directory-dropdown :deep(.app-dd-trigger-anchor),
.move-directory-dropdown :deep(.app-dd-trigger) { width: 100%; min-width: 0; }
.move-directory-dropdown :deep(.app-dd-trigger) { height: 38px; }
.move-action { --stateful-button-icon-size: 15px; justify-self: start; flex-shrink: 0; width: auto; min-width: 132px; height: 38px; min-height: 38px; padding: 0 13px; border: 1px solid var(--set-border); border-radius: 999px; background: var(--set-surface); color: var(--set-text-strong); box-shadow: none; white-space: nowrap; transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.move-action:not(:disabled):hover { background: var(--set-surface-hover); border-color: var(--set-border-strong); box-shadow: none; transform: translateY(-2px) scale(1.02); }
.move-action:not(:disabled):active { transform: scale(0.96); }
.move-action :deep(.stateful-button__content) { gap: 7px; }
.move-action :deep(.stateful-button__state) { width: 16px; height: 16px; }
.move-spin { animation: move-spin 1s linear infinite; }
@keyframes move-spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  .move-grid { grid-template-columns: minmax(0, 1fr); }
  .move-heading { flex-direction: column; }
}
</style>
