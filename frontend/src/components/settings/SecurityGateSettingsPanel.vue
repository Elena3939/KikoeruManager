<template>
  <div class="security-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">系统门禁</div>
        <div class="toggle-stack">
          <SettingsToggleRow
            v-model="config.security_gate.enabled"
            title="启用 Google Authenticator 门禁"
            :subtitle="gateSubtitle"
            :disabled="!config.security_gate.bound"
          />
          <SettingsToggleRow v-model="config.security_gate.allow_remember_device" title="允许记住设备" subtitle="可信浏览器可保存长期验证状态。" />
          <SettingsToggleRow v-model="config.security_gate.trust_proxy_headers" title="信任反向代理 IP 头" subtitle="仅在可信 Nginx / Cloudflare 等代理后开启。" />
        </div>
        <div class="mini-grid two">
          <SettingsFieldCard label="普通会话小时">
            <SettingsNumberStepper v-model="config.security_gate.session_hours" :min="1" :max="72" />
          </SettingsFieldCard>
          <SettingsFieldCard label="记住设备天数">
            <SettingsNumberStepper v-model="config.security_gate.remember_days" :min="1" :max="180" />
          </SettingsFieldCard>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">验证器绑定</div>
        <div class="gate-bind-status" :class="config.security_gate.bound ? 'is-bound' : 'is-empty'">
          <component :is="config.security_gate.bound ? ShieldCheck : QrCode" :size="20" />
          <div>
            <strong>{{ config.security_gate.bound ? '已绑定' : '未绑定' }}</strong>
            <span>{{ config.security_gate.bound ? '当前门禁可随时开启。' : '先生成二维码并用 Google Authenticator 扫码。' }}</span>
          </div>
        </div>
        <div v-if="setup.qr_data_uri || setup.secret" class="gate-setup-box">
          <img v-if="setup.qr_data_uri" :src="setup.qr_data_uri" alt="Google Authenticator 绑定二维码">
          <div class="setup-secret">
            <span>{{ setup.secret }}</span>
            <button type="button" @click="copySecret">
              <Copy :size="14" />
              复制
            </button>
          </div>
          <div class="confirm-row">
            <input v-model="setupCode" class="field-input" maxlength="6" inputmode="numeric" placeholder="输入 6 位验证码" @input="setupCode = setupCode.replace(/\D/g, '').slice(0, 6)">
            <button type="button" class="gate-action is-primary" :disabled="setupBusy || setupCode.length !== 6" @click="confirmSetup">
              <ShieldCheck :size="15" />
              确认绑定
            </button>
          </div>
        </div>
        <div class="action-row">
          <button type="button" class="gate-action is-primary" :disabled="setupBusy" @click="createSetup">
            <QrCode :size="15" />
            {{ config.security_gate.bound ? '重新生成绑定' : '生成绑定二维码' }}
          </button>
          <button type="button" class="gate-action is-danger" :disabled="setupBusy || !config.security_gate.bound" @click="resetSetup">
            <RotateCcw :size="15" />
            重置验证器
          </button>
        </div>
      </div>
    </div>

    <div class="settings-card">
      <div class="card-title">失败与提醒策略</div>
      <div class="settings-grid two">
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.security_gate.blacklist_enabled" title="启用黑名单" subtitle="达到失败阈值后永久拉黑来源 IP。" />
          <SettingsToggleRow v-model="config.security_gate.email_alert_enabled" title="启用安全邮件提醒" subtitle="复用通知中心 SMTP 发件配置。" />
          <SettingsToggleRow v-model="config.security_gate.email_alert_on_failure" title="验证码失败时提醒" :disabled="!config.security_gate.email_alert_enabled" />
          <SettingsToggleRow v-model="config.security_gate.email_alert_on_blacklist" title="拉黑时提醒" :disabled="!config.security_gate.email_alert_enabled" />
          <SettingsToggleRow v-model="config.security_gate.email_alert_on_blocked_visit" title="黑名单再次访问提醒" :disabled="!config.security_gate.email_alert_enabled" />
          <SettingsToggleRow v-model="config.security_gate.email_alert_on_reset" title="验证器重置提醒" :disabled="!config.security_gate.email_alert_enabled" />
        </div>
        <div class="mini-grid two">
          <SettingsFieldCard label="失败统计窗口（分钟）">
            <SettingsNumberStepper v-model="config.security_gate.failure_window_minutes" :min="1" :max="120" />
          </SettingsFieldCard>
          <SettingsFieldCard label="最大失败次数">
            <SettingsNumberStepper v-model="config.security_gate.max_failures" :min="2" :max="20" />
          </SettingsFieldCard>
          <SettingsFieldCard label="提醒最小间隔（秒）">
            <SettingsNumberStepper v-model="config.security_gate.email_alert_min_interval_seconds" :min="60" :max="86400" />
          </SettingsFieldCard>
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-head-row">
          <div class="card-title">认证记录</div>
          <button type="button" class="gate-icon-btn" :disabled="logsBusy" @click="loadLogs">
            <RefreshCw :size="15" :class="{ 'spin-once': logsBusy }" />
          </button>
        </div>
        <div class="filter-row">
          <button v-for="item in logFilters" :key="item.value" type="button" class="filter-chip" :class="{ 'is-active': logFilter === item.value }" @click="logFilter = item.value; loadLogs()">
            {{ item.label }}
          </button>
        </div>
        <div class="log-list">
          <div v-for="item in logs" :key="item.id" class="log-row">
            <div class="log-main">
              <span class="log-dot" :class="item.success ? 'is-ok' : 'is-bad'"></span>
              <div class="log-copy">
                <strong>{{ eventLabel(item.event_type) }}</strong>
                <span>{{ item.ip_address }} · {{ formatTime(item.created_at) }}</span>
              </div>
            </div>
            <em class="log-result">{{ item.failure_reason || '通过' }}</em>
          </div>
          <AppEmptyState v-if="!logs.length" title="暂无认证记录" description="门禁验证后会在这里出现记录。" />
        </div>
      </div>

      <div class="settings-card">
        <div class="card-head-row">
          <div class="card-title">黑名单</div>
          <button type="button" class="gate-icon-btn" :disabled="blacklistBusy" @click="loadBlacklist">
            <RefreshCw :size="15" :class="{ 'spin-once': blacklistBusy }" />
          </button>
        </div>
        <div class="black-list">
          <div v-for="item in blacklist" :key="item.id" class="black-row">
            <div class="black-copy">
              <strong>{{ item.ip_address }}</strong>
              <span>{{ item.reason }} · 失败 {{ item.failure_count }} 次</span>
            </div>
            <button type="button" class="gate-action is-ghost" @click="unblock(item)">
              <UnlockKeyhole :size="14" />
              解除
            </button>
          </div>
          <AppEmptyState v-if="!blacklist.length" title="暂无黑名单" description="达到失败阈值的来源会出现在这里。" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Copy, QrCode, RefreshCw, RotateCcw, ShieldCheck, UnlockKeyhole } from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import { securityGateApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'

const props = defineProps({
  config: { type: Object, required: true }
})

const setup = ref({})
const setupCode = ref('')
const setupBusy = ref(false)
const logs = ref([])
const blacklist = ref([])
const logFilter = ref('all')
const logsBusy = ref(false)
const blacklistBusy = ref(false)

const logFilters = [
  { value: 'all', label: '全部' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'blacklist', label: '拉黑相关' }
]

const gateSubtitle = computed(() => {
  if (!props.config.security_gate.bound) return '需要先绑定验证器后才能开启。'
  return props.config.security_gate.enabled ? '系统页面和业务接口已受保护。' : '关闭时不会要求访问验证。'
})

onMounted(() => {
  loadLogs()
  loadBlacklist()
})

async function createSetup() {
  if (props.config.security_gate.bound) {
    await showSystemConfirm({
      title: '重新生成验证器绑定',
      message: '确认后需要用新的二维码完成绑定，旧验证器会在确认新验证码后失效。',
      confirmText: '继续生成',
      cancelText: '取消',
      tone: 'warning'
    })
  }
  setupBusy.value = true
  try {
    setup.value = await securityGateApi.createSetup()
    setupCode.value = ''
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '生成绑定二维码失败')
  } finally {
    setupBusy.value = false
  }
}

async function confirmSetup() {
  setupBusy.value = true
  try {
    await securityGateApi.confirmSetup(setupCode.value)
    props.config.security_gate.bound = true
    props.config.security_gate.has_pending_setup = false
    props.config.security_gate.secret = '********'
    props.config.security_gate.pending_secret = ''
    setup.value = {}
    setupCode.value = ''
    ElMessage.success('验证器绑定完成')
    loadLogs()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '验证码错误')
  } finally {
    setupBusy.value = false
  }
}

async function resetSetup() {
  await showSystemConfirm({
    title: '重置验证器',
    message: '重置后旧 Google Authenticator 立即失效，安全门禁会自动关闭。',
    confirmText: '重置验证器',
    cancelText: '取消',
    tone: 'danger'
  })
  setupBusy.value = true
  try {
    await securityGateApi.resetSetup()
    props.config.security_gate.enabled = false
    props.config.security_gate.bound = false
    props.config.security_gate.secret = ''
    props.config.security_gate.pending_secret = ''
    setup.value = {}
    ElMessage.success('验证器已重置')
    loadLogs()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重置失败')
  } finally {
    setupBusy.value = false
  }
}

async function copySecret() {
  await navigator.clipboard.writeText(setup.value.secret || '')
  ElMessage.success('密钥已复制')
}

async function loadLogs() {
  if (logsBusy.value) return
  logsBusy.value = true
  try {
    const result = await securityGateApi.logs({ result: logFilter.value, limit: 80 })
    logs.value = result.items || []
  } finally {
    logsBusy.value = false
  }
}

async function loadBlacklist() {
  if (blacklistBusy.value) return
  blacklistBusy.value = true
  try {
    const result = await securityGateApi.blacklist()
    blacklist.value = result.items || []
  } finally {
    blacklistBusy.value = false
  }
}

async function unblock(item) {
  await showSystemConfirm({
    title: '解除黑名单',
    message: `确定解除 ${item.ip_address} 的门禁黑名单吗？`,
    confirmText: '解除',
    cancelText: '取消',
    tone: 'warning'
  })
  await securityGateApi.unblock(item.id, '设置页手动解除')
  ElMessage.success('已解除黑名单')
  loadBlacklist()
  loadLogs()
}

function eventLabel(value) {
  return {
    verify_success: '验证成功',
    verify_failed: '验证失败',
    setup_failed: '绑定失败',
    setup_confirmed: '绑定完成',
    blocked_visit: '黑名单访问',
    blacklist_unblocked: '解除黑名单',
    totp_reset: '重置验证器'
  }[value] || value
}

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}
</script>

<style scoped>
.security-stack {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px 26px;
  align-items: start;
}

.settings-grid.two,
.mini-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-card {
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.card-title {
  margin: 0 0 14px;
  color: var(--set-text-strong);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.card-head-row,
.action-row,
.confirm-row,
.filter-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-row {
  margin-top: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.action-row {
  margin-top: 22px;
  flex-wrap: wrap;
}

.card-head-row {
  justify-content: space-between;
  margin-bottom: 18px;
}

.card-head-row .card-title {
  margin: 0;
}

.toggle-stack,
.mini-grid,
.log-list,
.black-list {
  display: grid;
  gap: 12px;
}

.log-list,
.black-list {
  padding-top: 2px;
}

.mini-grid {
  margin-top: 16px;
}

.gate-bind-status {
  display: flex;
  align-items: center;
  gap: 14px;
  width: fit-content;
  max-width: 100%;
  min-height: 0;
  padding: 2px 0;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.gate-bind-status > svg {
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  padding: 9px;
  border-radius: 12px;
  color: var(--set-text-muted);
  background: var(--set-surface-soft);
  box-shadow:
    inset 0 0 0 1px rgba(148, 163, 184, 0.16),
    0 6px 16px rgba(15, 23, 42, 0.05);
}

.gate-bind-status.is-bound {
  border-color: transparent;
  background: transparent;
}

.gate-bind-status.is-empty {
  border-color: transparent;
  background: transparent;
}

.gate-bind-status.is-bound > svg {
  color: var(--set-success-text);
  background: var(--set-success-bg);
}

.gate-bind-status.is-empty > svg {
  color: var(--set-text-muted);
  background: var(--set-surface);
}

.gate-bind-status strong,
.gate-bind-status span {
  display: block;
}

.gate-bind-status span {
  margin-top: 5px;
  color: var(--set-text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.gate-setup-box {
  display: grid;
  gap: 14px;
  margin-top: 16px;
  padding: 16px 18px;
  border-radius: 14px;
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
}

.gate-setup-box img {
  width: 168px;
  height: 168px;
  margin: 0 auto;
  border-radius: 12px;
}

.setup-secret {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--set-text-strong);
  font-size: 12px;
  word-break: break-all;
  padding: 9px 10px;
  border-radius: 12px;
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
}

.setup-secret button,
.gate-action,
.gate-icon-btn,
.filter-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.setup-secret button,
.gate-action,
.filter-chip {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 11px;
  font-weight: 600;
  font-size: 12px;
}

.gate-action.is-primary {
  color: var(--set-primary-text);
  background: var(--set-primary-bg);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 8px 18px rgba(15, 23, 42, 0.14);
}

.gate-action.is-danger {
  color: var(--set-danger-text);
  background: var(--set-danger-bg);
  box-shadow: inset 0 0 0 1px var(--set-danger-border);
}

.gate-action.is-ghost,
.setup-secret button,
.filter-chip {
  color: var(--set-text);
  background: var(--set-surface);
  box-shadow: inset 0 0 0 1px var(--set-border);
}

.filter-chip.is-active {
  color: var(--set-text-strong);
  background: var(--set-surface-muted);
  box-shadow: inset 0 0 0 1px var(--set-border-strong);
}

.gate-icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  color: var(--set-text);
  background: var(--set-surface-soft);
  box-shadow: inset 0 0 0 1px var(--set-border);
}

.gate-icon-btn:hover svg:not(.spin-once) {
  transform: rotate(-360deg);
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes spin-once {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.spin-once {
  animation: spin-once 0.7s linear infinite;
}

.gate-action:hover:not(:disabled),
.gate-icon-btn:hover,
.filter-chip:hover,
.setup-secret button:hover {
  transform: translateY(-1px) scale(1.01);
}

.gate-action:active:not(:disabled),
.gate-icon-btn:active {
  transform: scale(0.96);
}

.gate-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  outline: none;
  color: var(--set-text-strong);
  background: var(--set-field-bg);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.confirm-row .field-input {
  flex: 1;
}

.log-row,
.black-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  min-height: 72px;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.03);
}

.log-row > div,
.black-row > div,
.log-main,
.black-copy {
  min-width: 0;
}

.log-main {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
}

.log-copy,
.black-copy {
  min-width: 0;
}

.log-row strong,
.black-row strong,
.log-row span,
.black-row span {
  display: block;
}

.log-row strong,
.black-row strong {
  color: var(--set-text-strong);
  font-size: 14px;
  line-height: 1.35;
}

.log-row span,
.black-row span {
  margin-top: 4px;
  color: var(--set-text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-result {
  min-width: 72px;
  text-align: right;
  color: var(--set-text-muted);
  font-size: 12px;
  font-weight: 600;
  font-style: normal;
}

.log-dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 999px;
}

.log-dot.is-ok {
  background: #10b981;
}

.log-dot.is-bad {
  background: #ef4444;
}

@media (max-width: 900px) {
  .settings-grid.two,
  .mini-grid.two {
    grid-template-columns: 1fr;
  }
  .action-row,
  .confirm-row {
    align-items: stretch;
    flex-direction: column;
  }
  .action-row {
    margin-top: 18px;
  }
  .log-row,
  .black-row {
    grid-template-columns: 1fr;
    align-items: start;
  }
  .log-result {
    min-width: 0;
    text-align: left;
    padding-left: 21px;
  }
}
</style>
