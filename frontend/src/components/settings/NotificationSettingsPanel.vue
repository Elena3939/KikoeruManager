<template>
  <div class="notification-stack">
    <div class="settings-grid two">
      <!-- 站内通知 -->
      <div class="settings-card">
        <div class="card-title">站内通知</div>
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.notification_center.enabled" title="启用通知中心" subtitle="任务状态变化时写入站内铃铛。" />
          <SettingsToggleRow v-model="config.notification_center.unread_highlight_enabled" title="未读高亮提示" subtitle="铃铛图标显示未读数量徽章。" />
        </div>
        <div class="field-stack notif-center-fields">
          <div class="mini-grid two">
            <SettingsFieldCard label="通知保留天数">
              <SettingsNumberStepper v-model="config.notification_center.retain_days" :min="1" :max="365" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大保留条数">
              <SettingsNumberStepper v-model="config.notification_center.max_items" :min="20" :max="2000" />
            </SettingsFieldCard>
          </div>
        </div>
      </div>

      <!-- 邮件推送触发规则 -->
      <div class="settings-card">
        <div class="card-title">邮件推送触发规则</div>
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.notification_email.enabled" title="启用邮件推送" subtitle="通过 SMTP 发送任务通知邮件。" />
          <SettingsToggleRow v-model="config.notification_email.send_on_completed" title="任务完成时发送" :disabled="!config.notification_email.enabled" />
          <SettingsToggleRow v-model="config.notification_email.send_on_failed" title="任务失败时发送" :disabled="!config.notification_email.enabled" />
          <SettingsToggleRow v-model="config.notification_email.send_on_waiting_manual" title="等待人工处理时发送" :disabled="!config.notification_email.enabled" />
          <SettingsToggleRow v-model="config.notification_email.send_on_cancelled" title="任务取消时发送" subtitle="默认关闭，取消通知噪音较多。" :disabled="!config.notification_email.enabled" />
        </div>
        <div class="notif-domain-block" :class="{ 'is-disabled': !config.notification_email.enabled }">
          <div class="notif-domain-head">
            <strong>按任务类型推送</strong>
            <span class="notif-domain-hint">{{ notifDomainHint }}</span>
          </div>
          <div class="notif-domain-chips">
            <button
              v-for="d in NOTIF_DOMAINS"
              :key="d.value"
              type="button"
              class="notif-domain-chip"
              :class="{ 'is-active': isDomainEnabled(d.value) }"
              :disabled="!config.notification_email.enabled"
              @click="toggleDomain(d.value)"
            >
              <component :is="d.icon" :size="13" :stroke-width="2.4" />
              <span>{{ d.label }}</span>
            </button>
          </div>
          <div class="notif-domain-actions">
            <button type="button" class="notif-domain-link" :disabled="!config.notification_email.enabled" @click="setAllDomains(true)">全选</button>
            <span class="notif-domain-sep">·</span>
            <button type="button" class="notif-domain-link" :disabled="!config.notification_email.enabled" @click="setAllDomains(false)">清空（=全部发送）</button>
          </div>
        </div>
      </div>
    </div>

    <!-- SMTP 发件配置 -->
    <div class="settings-card" v-if="config.notification_email.enabled">
      <div class="card-title">SMTP 发件配置</div>
      <div class="smtp-preset-row">
        <span class="smtp-preset-label">快速填入：</span>
        <button v-for="p in smtpPresets" :key="p.name" class="smtp-preset-btn" type="button" @click="applySmtpPreset(p)">{{ p.name }}</button>
        <a class="smtp-help-link" href="https://service.mail.qq.com/detail/0/75" target="_blank" rel="noopener">QQ 如何开启 SMTP？</a>
      </div>
      <div class="settings-grid two">
        <div class="field-stack">
          <SettingsFieldCard>
            <template #label>SMTP 主机 <small class="smtp-host-tip">（填服务器地址，如 smtp.qq.com）</small></template>
            <input v-model="config.notification_email.smtp_host" class="field-input" type="text" placeholder="smtp.qq.com">
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="端口">
              <SettingsNumberStepper v-model="config.notification_email.smtp_port" :min="1" :max="65535" />
            </SettingsFieldCard>
            <SettingsFieldCard label="加密方式">
              <div class="smtp-crypt-row">
                <div class="toggle-mini">
                  <SettingsSwitch v-model="config.notification_email.smtp_ssl" @change="v => { if(v) config.notification_email.smtp_starttls = false }" />
                  <span>SSL</span>
                </div>
                <div class="toggle-mini">
                  <SettingsSwitch v-model="config.notification_email.smtp_starttls" @change="v => { if(v) config.notification_email.smtp_ssl = false }" />
                  <span>STARTTLS</span>
                </div>
              </div>
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="发件账号">
            <input v-model="config.notification_email.username" class="field-input" type="text" placeholder="your@qq.com">
          </SettingsFieldCard>
          <SettingsFieldCard label="发件密码 / 授权码">
            <AnimatedPasswordInput v-model="config.notification_email.password" placeholder="QQ 邮箱需填授权码" />
          </SettingsFieldCard>
        </div>
        <div class="field-stack">
          <SettingsFieldCard label="发件显示名">
            <input v-model="config.notification_email.from_name" class="field-input" type="text" placeholder="KikoeruManager">
          </SettingsFieldCard>
          <SettingsFieldCard label="发件地址">
            <input v-model="config.notification_email.from_email" class="field-input" type="text" placeholder="留空使用账号地址">
          </SettingsFieldCard>
          <SettingsFieldCard label="收件地址">
            <input v-model="config.notification_email.to_email" class="field-input" type="text" placeholder="接收通知的邮箱">
          </SettingsFieldCard>
          <div class="smtp-test-row">
            <button class="action-btn action-btn--secondary" :disabled="emailTestBusy" @click="doTestEmail">
              <Mail :size="14" />
              {{ emailTestBusy ? '发送中...' : '发送测试邮件' }}
            </button>
            <span v-if="emailTestResult" :class="['email-test-result', emailTestResult.ok ? 'ok' : 'err']">{{ emailTestResult.message }}</span>
          </div>
        </div>
      </div>
    </div>

    <NotificationTemplatesPanel />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Activity, Bell, Captions, Database, FileArchive, Mail, Sparkles, Upload, UploadCloud } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsSwitch from './SettingsSwitch.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import NotificationTemplatesPanel from './NotificationTemplatesPanel.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import { notificationApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

// SMTP 服务商预设
const smtpPresets = [
  { name: 'QQ 邮箱', smtp_host: 'smtp.qq.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: '163 邮箱', smtp_host: 'smtp.163.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: '126 邮箱', smtp_host: 'smtp.126.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: 'Gmail', smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_ssl: false, smtp_starttls: true },
  { name: 'Outlook', smtp_host: 'smtp.office365.com', smtp_port: 587, smtp_ssl: false, smtp_starttls: true },
]

function applySmtpPreset(preset) {
  props.config.notification_email.smtp_host = preset.smtp_host
  props.config.notification_email.smtp_port = preset.smtp_port
  props.config.notification_email.smtp_ssl = preset.smtp_ssl
  props.config.notification_email.smtp_starttls = preset.smtp_starttls
}

// 通知邮件按 domain 过滤
const NOTIF_DOMAINS = [
  { value: 'import', label: '导入处理', icon: FileArchive },
  { value: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
  { value: 'subtitle_import', label: '字幕补配', icon: Sparkles },
  { value: 'asmr_sync', label: 'ASMR 同步', icon: UploadCloud },
  { value: 'upload', label: '库存上传', icon: Upload },
  { value: 'circle_completion', label: '社团补全', icon: Database },
  { value: 'system', label: '系统任务', icon: Activity }
]

const notifDomainHint = computed(() => {
  const list = props.config?.notification_email?.enabled_domains || []
  if (!list.length) return '未选 = 全部任务类型都发邮件'
  return `仅推送 ${list.length} 类任务`
})

function isDomainEnabled(domain) {
  const list = props.config?.notification_email?.enabled_domains || []
  return list.includes(domain)
}

function toggleDomain(domain) {
  if (!props.config?.notification_email) return
  const list = Array.isArray(props.config.notification_email.enabled_domains)
    ? [...props.config.notification_email.enabled_domains]
    : []
  const idx = list.indexOf(domain)
  if (idx >= 0) list.splice(idx, 1)
  else list.push(domain)
  props.config.notification_email.enabled_domains = list
}

function setAllDomains(selectAll) {
  if (!props.config?.notification_email) return
  props.config.notification_email.enabled_domains = selectAll
    ? NOTIF_DOMAINS.map(d => d.value)
    : []
}

// 通知邮件测试
const emailTestBusy = ref(false)
const emailTestResult = ref(null)
async function doTestEmail() {
  if (emailTestBusy.value) return
  emailTestBusy.value = true
  emailTestResult.value = null
  try {
    const cfg = { ...props.config.notification_email }
    const result = await notificationApi.testEmail(cfg)
    emailTestResult.value = result
  } catch (e) {
    emailTestResult.value = { ok: false, message: e.response?.data?.detail || e.message || '发送失败' }
  } finally {
    emailTestBusy.value = false
  }
}
</script>

<style scoped>
.notification-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.mini-grid,
.field-stack,
.toggle-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.mini-grid { display: grid; gap: 10px; }
.mini-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.field-stack,
.toggle-stack {
  display: grid;
  gap: 12px;
}

.notif-center-fields { margin-top: 10px; }

.settings-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  min-height: 0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 14px;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

/* SettingsFieldCard slot 内的统一 input 视觉 */
.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: var(--set-border-strong); }

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.field-input::placeholder { color: var(--set-text-subtle); }

/* SMTP */
.smtp-preset-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.smtp-preset-label {
  font-size: 12px;
  color: var(--set-text-muted);
  letter-spacing: -0.05px;
}

.smtp-preset-btn {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text);
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.03px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.smtp-preset-btn:hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.smtp-help-link {
  font-size: 11.5px;
  color: var(--set-text-muted);
  text-decoration: none;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.55);
  padding-bottom: 1px;
  margin-left: auto;
  transition: color 0.18s, border-color 0.18s;
}

.smtp-help-link:hover {
  color: var(--set-text-strong);
  border-bottom-color: var(--set-border-strong);
}

.smtp-host-tip {
  color: #8e8e93;
  font-weight: 400;
  font-size: 11.5px;
  margin-left: 4px;
}

.smtp-crypt-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 38px;
}

.smtp-test-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.toggle-mini {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--set-text);
  letter-spacing: -0.05px;
  cursor: pointer;
}

/* 通知 domain chips */
.notif-domain-block {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--set-border);
  border-radius: 12px;
  background: var(--set-surface-soft);
  box-shadow: none;
}

.notif-domain-block.is-disabled { opacity: 0.55; pointer-events: none; }

.notif-domain-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--set-text-strong);
  letter-spacing: -0.05px;
}

.notif-domain-hint {
  font-size: 11.5px;
  color: var(--set-text-muted);
  letter-spacing: -0.05px;
}

.notif-domain-chips { display: flex; flex-wrap: wrap; gap: 6px; }

.notif-domain-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  height: 26px;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--set-chip-text);
  background: var(--set-chip-bg);
  border: 1px solid var(--set-border);
  border-radius: 999px;
  cursor: pointer;
  box-shadow: none;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.notif-domain-chip:hover {
  transform: translateY(-1px) scale(1.04);
  border-color: var(--set-border-strong);
  color: var(--set-text-strong);
  background: var(--set-surface-hover);
  box-shadow: none;
}

.notif-domain-chip.is-active {
  color: var(--set-tag-info-text);
  background: var(--set-tag-info-bg);
  border-color: var(--set-tag-info-border);
  box-shadow: none;
}

.notif-domain-chip.is-active:hover {
  color: var(--set-tag-info-text);
  background: var(--set-tag-info-bg);
  box-shadow: none;
}

.notif-domain-chip:disabled { cursor: not-allowed; opacity: 0.6; }

.notif-domain-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 11.5px;
}

.notif-domain-link {
  background: none;
  border: none;
  padding: 0;
  font-size: 11.5px;
  color: var(--set-text-strong);
  letter-spacing: -0.03px;
  cursor: pointer;
  transition: color 0.18s;
}

.notif-domain-link:hover {
  color: var(--set-text-strong);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.notif-domain-link:disabled { color: var(--set-text-subtle); cursor: not-allowed; }
.notif-domain-sep { color: var(--set-text-subtle); }

/* action 按钮 */
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.action-btn:hover { transform: translateY(-1px); }
.action-btn:active:not(:disabled) { transform: scale(0.97); }
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.action-btn--secondary {
  background: var(--set-surface);
  color: var(--set-text);
  border: 1px solid var(--set-border);
}

.action-btn--secondary:hover {
  border-color: var(--set-border-strong);
  color: var(--set-text-strong);
  background: var(--set-surface-hover);
}

.email-test-result {
  font-size: 11.5px;
  font-weight: 500;
  padding: 3px 10px;
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  letter-spacing: 0.01em;
  white-space: pre-line;
}

.email-test-result.ok {
  background: var(--set-success-bg);
  color: var(--set-success-text);
  border: 1px solid var(--set-success-border);
  box-shadow: none;
}

.email-test-result.err {
  background: var(--set-danger-bg);
  color: var(--set-danger-text);
  border: 1px solid var(--set-danger-border);
  box-shadow: none;
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two { grid-template-columns: 1fr; }
}
</style>
