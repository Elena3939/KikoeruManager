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
              <el-input-number v-model="config.notification_center.retain_days" :min="1" :max="365" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大保留条数">
              <el-input-number v-model="config.notification_center.max_items" :min="20" :max="2000" class="field-number" />
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
              <el-input-number v-model="config.notification_email.smtp_port" :min="1" :max="65535" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="加密方式">
              <div class="smtp-crypt-row">
                <label class="toggle-mini"><el-switch v-model="config.notification_email.smtp_ssl" @change="v => { if(v) config.notification_email.smtp_starttls = false }" /><span>SSL</span></label>
                <label class="toggle-mini"><el-switch v-model="config.notification_email.smtp_starttls" @change="v => { if(v) config.notification_email.smtp_ssl = false }" /><span>STARTTLS</span></label>
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
            <input v-model="config.notification_email.from_name" class="field-input" type="text" placeholder="Prekikoeru">
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
  color: #1d1d1f;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

/* SettingsFieldCard slot 内的统一 input 视觉 */
.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 10px;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: rgba(148, 163, 184, 0.75); }

.field-input:focus {
  border-color: rgba(79, 70, 229, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.field-input::placeholder { color: #94a3b8; }

.field-number :deep(.el-input__wrapper) {
  min-height: 38px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: none;
  border: 1px solid rgba(226, 232, 240, 0.85) !important;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-number :deep(.el-input__wrapper:hover) {
  border-color: rgba(148, 163, 184, 0.75) !important;
  box-shadow: none;
}

.field-number :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(79, 70, 229, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
}

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
  color: rgba(29, 29, 31, 0.55);
  letter-spacing: -0.05px;
}

.smtp-preset-btn {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.03px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.smtp-preset-btn:hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.55);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.85) 0%, #ffffff 100%);
  color: #4f46e5;
}

.smtp-help-link {
  font-size: 11.5px;
  color: rgba(29, 29, 31, 0.5);
  text-decoration: none;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.55);
  padding-bottom: 1px;
  margin-left: auto;
  transition: color 0.18s, border-color 0.18s;
}

.smtp-help-link:hover {
  color: #4f46e5;
  border-bottom-color: rgba(99, 102, 241, 0.85);
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
  color: rgba(29, 29, 31, 0.65);
  letter-spacing: -0.05px;
  cursor: pointer;
}

/* 通知 domain chips */
.notif-domain-block {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, rgba(248, 250, 252, 0.6) 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.notif-domain-block.is-disabled { opacity: 0.55; pointer-events: none; }

.notif-domain-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
  letter-spacing: -0.05px;
}

.notif-domain-hint {
  font-size: 11.5px;
  color: rgba(29, 29, 31, 0.5);
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
  color: #475569;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 999px;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.notif-domain-chip:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.04);
  border-color: rgba(148, 163, 184, 0.75);
  color: #1d1d1f;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 10px -2px rgba(15, 23, 42, 0.1);
}

.notif-domain-chip.is-active {
  color: #ffffff;
  background: linear-gradient(180deg, #1f2937 0%, #0f172a 60%, #020617 100%);
  border-color: #0f172a;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 4px 10px -4px rgba(2, 6, 23, 0.5);
}

.notif-domain-chip.is-active:hover:not(:disabled) {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 8px 18px -6px rgba(2, 6, 23, 0.55);
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
  color: #4f46e5;
  letter-spacing: -0.03px;
  cursor: pointer;
  transition: color 0.18s;
}

.notif-domain-link:hover:not(:disabled) {
  color: #3730a3;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.notif-domain-link:disabled { color: #cbd5e1; cursor: not-allowed; }
.notif-domain-sep { color: #cbd5e1; }

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

.action-btn:not(:disabled):hover { transform: translateY(-1px); }
.action-btn:not(:disabled):active { transform: scale(0.97); }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.action-btn--secondary {
  background: #ffffff;
  color: #475569;
  border: 1px solid rgba(226, 232, 240, 0.85);
}

.action-btn--secondary:not(:disabled):hover {
  border-color: rgba(99, 102, 241, 0.55);
  color: #4f46e5;
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.85) 0%, #ffffff 100%);
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
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
  border: 1px solid rgba(110, 231, 183, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.email-test-result.err {
  background: linear-gradient(180deg, #fff1f2 0%, #fee2e2 100%);
  color: #b91c1c;
  border: 1px solid rgba(252, 165, 165, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(239, 68, 68, 0.1);
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two { grid-template-columns: 1fr; }
}
</style>
