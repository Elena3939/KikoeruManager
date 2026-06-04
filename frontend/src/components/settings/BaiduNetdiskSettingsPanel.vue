<template>
  <div class="baidu-settings-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">百度网盘下载</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.baidu_netdisk.enabled" title="启用百度网盘下载" subtitle="独立于 HTTP 外链下载，走 BaiduPCS-Go 子进程执行。" />
          <div class="mini-grid three">
            <SettingsFieldCard label="下载根目录" hint="留空时使用待处理 input 目录或上层下载根目录。">
              <input v-model.trim="config.baidu_netdisk.download_root" class="field-input" type="text" placeholder="留空使用默认下载目录">
            </SettingsFieldCard>
            <SettingsFieldCard label="BaiduPCS-Go 路径" hint="默认使用项目 tools 目录下的 BaiduPCS-Go，可改为绝对路径。">
              <input v-model.trim="config.baidu_netdisk.baidupcs_go_path" class="field-input" type="text" placeholder="tools/baidupcs-go/BaiduPCS-Go.exe">
            </SettingsFieldCard>
            <SettingsFieldCard label="配置目录" hint="建议放在项目隔离配置下，避免污染用户全局配置。">
              <input v-model.trim="config.baidu_netdisk.config_dir" class="field-input" type="text" placeholder="留空自动生成">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid three">
            <SettingsFieldCard label="并发参数">
              <SettingsNumberStepper v-model="config.baidu_netdisk.max_parallel" :min="1" :max="500" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大下载负载">
              <input v-model.trim="config.baidu_netdisk.max_download_load" class="field-input" type="text" placeholder="0">
            </SettingsFieldCard>
            <SettingsFieldCard label="冲突策略">
              <AppDropdown v-model="config.baidu_netdisk.conflict_policy" :options="conflictPolicyOptions" class="settings-field-dd" />
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow v-model="config.baidu_netdisk.svip_speed_enabled" title="SVIP 高速提示" subtitle="账号为 SVIP 时，工作台和任务中心显示高速模式。" />
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">账号绑定</div>
        <div class="field-stack">
          <div class="baidu-bind-card">
            <div class="baidu-bind-head">
              <div class="baidu-bind-copy">
                <span>百度官方登录</span>
                <div class="baidu-official-login-main">
                  <ShieldCheck :size="18" :stroke-width="2.4" />
                  <div>
                    <strong>{{ baiduOfficialLoginTitle }}</strong>
                    <small>{{ baiduOfficialLoginSubtitle }}</small>
                  </div>
                </div>
              </div>
              <div class="baidu-official-login-actions">
                <StatefulButton
                  class="ghost-inline-btn"
                  unstyled
                  :show-default-icons="false"
                  :disabled="baiduTesting && baiduAction !== 'start'"
                  :success-hold="1100"
                  @click="startBaiduOfficialLogin"
                >
                  <template #prefix="{ state }">
                    <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                      <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                      <ExternalLink v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                      <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else :size="14" :stroke-width="2.4" />
                    </span>
                  </template>
                  {{ baiduOfficialLoginActive ? '重新打开' : '打开官方登录' }}
                </StatefulButton>
                <StatefulButton
                  class="ghost-inline-btn"
                  unstyled
                  :show-default-icons="false"
                  :disabled="!baiduOfficialLoginActive || (baiduTesting && baiduAction !== 'complete')"
                  :success-hold="1100"
                  @click="completeBaiduOfficialLogin"
                >
                  <template #prefix="{ state }">
                    <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                      <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                      <CheckCircle2 v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                      <Crown v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else :size="14" :stroke-width="2.4" />
                    </span>
                  </template>
                  同步账号
                </StatefulButton>
                <StatefulButton
                  v-if="baiduOfficialLoginActive"
                  class="ghost-inline-btn warning"
                  unstyled
                  :show-default-icons="false"
                  :disabled="baiduTesting && baiduAction !== 'close'"
                  :success-hold="900"
                  @click="closeBaiduOfficialLogin"
                >
                  <template #prefix="{ state }">
                    <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                      <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                      <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else :size="14" :stroke-width="2.4" />
                    </span>
                  </template>
                  关闭登录窗
                </StatefulButton>
              </div>
            </div>

            <div class="baidu-account-actions">
              <div
                class="baidu-account-status"
                :class="{
                  'is-ready': baiduAccountReady,
                  'is-active': baiduOfficialLoginActive,
                  'is-loading': baiduTesting,
                  'is-error': baiduStatusMessage.startsWith('✗')
                }"
                :aria-busy="baiduTesting ? 'true' : undefined"
              >
                <component :is="baiduAccountIcon" :size="15" :stroke-width="2.4" />
                <span>{{ baiduAccountStatusText }}</span>
              </div>
              <div class="baidu-account-buttons">
                <StatefulButton
                  class="ghost-inline-btn"
                  unstyled
                  :show-default-icons="false"
                  :disabled="baiduTesting && baiduAction !== 'refresh'"
                  :success-hold="1100"
                  @click="refreshBaiduAccountStatus"
                >
                  <template #prefix="{ state }">
                    <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                      <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                      <RefreshCw v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                      <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else :size="14" :stroke-width="2.4" />
                    </span>
                  </template>
                  刷新账号
                </StatefulButton>
                <StatefulButton
                  class="ghost-inline-btn danger"
                  unstyled
                  :show-default-icons="false"
                  :disabled="baiduTesting && baiduAction !== 'unbind'"
                  :success-hold="1100"
                  @click="unbindBaiduAccount"
                >
                  <template #prefix="{ state }">
                    <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                      <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                      <Trash2 v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                      <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                      <XCircle v-else :size="14" :stroke-width="2.4" />
                    </span>
                  </template>
                  解绑
                </StatefulButton>
              </div>
            </div>

            <div v-if="baiduAccountVisible" class="baidu-account-card">
              <img v-if="baiduAvatarUrl" :src="baiduAvatarUrl" alt="" class="baidu-account-avatar" referrerpolicy="no-referrer">
              <div v-else class="baidu-account-avatar is-placeholder">{{ baiduAccountInitial }}</div>
              <div class="baidu-account-main">
                <strong>{{ baiduAccountDisplayName }}</strong>
                <span>{{ baiduVipLabel }}{{ baiduVipLevelText }}</span>
              </div>
              <small>{{ baiduAccountCachedText }}</small>
            </div>

            <div v-if="baiduAccountVisible" class="baidu-account-meta-grid">
              <div class="baidu-account-meta">
                <span>总空间</span>
                <strong>{{ formatBytes(config.baidu_netdisk.quota_bytes) }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>已使用</span>
                <strong>{{ formatBytes(config.baidu_netdisk.used_bytes) }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>剩余空间</span>
                <strong>{{ formatBytes(remainingBytes) }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>账号状态</span>
                <strong>{{ config.baidu_netdisk.enabled ? '已启用' : '未启用' }}</strong>
              </div>
            </div>

            <div class="baidu-account-note">
              <span>只展示百度官方接口返回的头像 / 名称 / VIP 信息。拿不到官方头像时，不使用仿制图。</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, Crown, ExternalLink, LoaderCircle, RefreshCw, ShieldCheck, Trash2, TriangleAlert, XCircle } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { baiduNetdiskApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const conflictPolicyOptions = [
  { value: 'resume', label: '断点续传' },
  { value: 'rename', label: '自动改名' },
  { value: 'skip', label: '已存在跳过' }
]

const baiduTesting = ref(false)
const baiduAction = ref('')
const baiduStatusMessage = ref('')
const baiduOfficialLogin = ref({
  active: false,
  browser: '',
  browser_path: '',
  profile_dir: '',
  started_at: 0,
  login_url: ''
})

const baiduAvatarUrl = computed(() => String(props.config.baidu_netdisk.account_avatar_url || '').trim())
const baiduAccountDisplayName = computed(() => {
  const name = String(props.config.baidu_netdisk.account_name || '').trim()
  const netdisk = String(props.config.baidu_netdisk.account_netdisk_name || '').trim()
  return name || netdisk || '百度网盘账号'
})
const baiduVipLabel = computed(() => String(props.config.baidu_netdisk.vip_label || '').trim() || '普通账号')
const baiduVipLevelText = computed(() => {
  const level = String(props.config.baidu_netdisk.vip_level || '').trim()
  return level ? ` · 等级 ${level}` : ''
})
const remainingBytes = computed(() => Math.max(0, Number(props.config.baidu_netdisk.quota_bytes || 0) - Number(props.config.baidu_netdisk.used_bytes || 0)))
const baiduAccountVisible = computed(() => Boolean(
  props.config.baidu_netdisk.enabled && (
    props.config.baidu_netdisk.account_name
      || props.config.baidu_netdisk.account_netdisk_name
      || props.config.baidu_netdisk.account_avatar_url
      || Number(props.config.baidu_netdisk.vip_type || 0) > 0
      || Number(props.config.baidu_netdisk.quota_bytes || 0) > 0
  )
))
const baiduAccountReady = computed(() => Boolean(props.config.baidu_netdisk.enabled && baiduAccountVisible.value))
const baiduAccountInitial = computed(() => (baiduAccountDisplayName.value || 'B').trim().slice(0, 1).toUpperCase() || 'B')
const baiduOfficialLoginActive = computed(() => Boolean(baiduOfficialLogin.value?.active))
const baiduOfficialLoginBrowserLabel = computed(() => String(baiduOfficialLogin.value?.browser || '').trim() || '百度官方登录')
const baiduOfficialLoginTitle = computed(() => (
  baiduOfficialLoginActive.value
    ? '百度官方登录窗口已打开'
    : '打开百度官方登录'
))
const baiduOfficialLoginSubtitle = computed(() => (
  baiduOfficialLoginActive.value
    ? `请在百度官方页面完成登录后点击“同步账号” · ${baiduOfficialLoginBrowserLabel.value}`
    : '扫码、手机号或账号密码都在百度官方页面完成，系统只同步登录结果'
))
const baiduAccountCachedText = computed(() => {
  const cachedAt = Number(props.config.baidu_netdisk.account_cached_at || 0)
  if (!cachedAt) return '本地缓存'
  const date = new Date(cachedAt * 1000)
  if (Number.isNaN(date.getTime())) return '本地缓存'
  return `缓存于 ${date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
})
const baiduAccountStatusText = computed(() => {
  if (baiduTesting.value && baiduAction.value === 'start') return '正在打开百度官方登录窗口...'
  if (baiduTesting.value && baiduAction.value === 'complete') return '正在同步百度登录状态...'
  if (baiduTesting.value && baiduAction.value === 'refresh') return '正在刷新百度账号和容量...'
  if (baiduStatusMessage.value.startsWith('✗')) return baiduStatusMessage.value
  if (baiduOfficialLoginActive.value) return `官方登录窗口已打开 · ${baiduOfficialLoginBrowserLabel.value}`
  if (baiduAccountVisible.value) return `${baiduVipLabel.value} · ${formatBytes(remainingBytes.value)} 剩余`
  if (baiduStatusMessage.value.startsWith('✓')) return baiduStatusMessage.value
  return '未绑定百度账号'
})
const baiduAccountIcon = computed(() => {
  if (baiduTesting.value) return LoaderCircle
  if (baiduStatusMessage.value.startsWith('✗')) return TriangleAlert
  if (baiduAccountVisible.value) return baiduVipLabel.value.includes('SVIP') ? Crown : CheckCircle2
  if (baiduOfficialLoginActive.value) return ExternalLink
  return ShieldCheck
})

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`
}

function setOfficialLoginState(officialLogin = {}) {
  baiduOfficialLogin.value = {
    active: Boolean(officialLogin?.active),
    browser: String(officialLogin?.browser || '').trim(),
    browser_path: String(officialLogin?.browser_path || '').trim(),
    profile_dir: String(officialLogin?.profile_dir || '').trim(),
    started_at: Number(officialLogin?.started_at || 0),
    login_url: String(officialLogin?.login_url || '').trim()
  }
}

function mergeAccount(account = {}) {
  const accountHasIdentity = Boolean(
    String(account.name || '').trim()
      || String(account.netdisk_name || '').trim()
      || String(account.avatar_url || '').trim()
      || Number(account.vip_type || 0) > 0
      || Number(account.quota_bytes || 0) > 0
      || Number(account.used_bytes || 0) > 0
  )
  const configured = Boolean(
    account?.configured
      || account?.ready
      || (account?.enabled && accountHasIdentity)
  )
  props.config.baidu_netdisk.enabled = Boolean(account?.enabled ?? configured)
  props.config.baidu_netdisk.cookie = configured ? '********' : ''
  props.config.baidu_netdisk.account_name = String(account.name || '').trim()
  props.config.baidu_netdisk.account_netdisk_name = String(account.netdisk_name || '').trim()
  props.config.baidu_netdisk.account_avatar_url = String(account.avatar_url || '').trim()
  props.config.baidu_netdisk.account_uk = String(account.uk || '').trim()
  props.config.baidu_netdisk.vip_type = Number(account.vip_type || 0)
  props.config.baidu_netdisk.vip_label = String(account.vip_label || '').trim()
  props.config.baidu_netdisk.vip_level = String(account.vip_level || '').trim()
  props.config.baidu_netdisk.quota_bytes = Number(account.quota_bytes || 0)
  props.config.baidu_netdisk.used_bytes = Number(account.used_bytes || 0)
  props.config.baidu_netdisk.account_cached_at = configured ? Number(account.cached_at || Date.now() / 1000) : 0
}

function formatBaiduError(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

async function runBaiduAction(action, fallbackMessage, runner) {
  if (baiduTesting.value) return
  baiduAction.value = action
  baiduTesting.value = true
  try {
    await runner()
    return true
  } catch (error) {
    baiduStatusMessage.value = `✗ ${formatBaiduError(error, fallbackMessage)}`
    return false
  } finally {
    baiduTesting.value = false
    baiduAction.value = ''
  }
}

async function refreshBaiduOfficialLoginStatus() {
  return runBaiduAction('status', '刷新百度官方登录状态失败', async () => {
    const result = await baiduNetdiskApi.officialLoginStatus()
    setOfficialLoginState(result?.official_login || {})
    if (result?.account) {
      mergeAccount(result.account)
    }
    baiduStatusMessage.value = ''
  })
}

async function refreshBaiduAccountStatus() {
  return runBaiduAction('refresh', '刷新百度账号状态失败', async () => {
    const result = await baiduNetdiskApi.refreshAccount()
    setOfficialLoginState(result?.official_login || {})
    mergeAccount(result?.account || {})
    baiduStatusMessage.value = `✓ ${baiduAccountDisplayName.value} 状态已刷新`
  })
}

async function startBaiduOfficialLogin() {
  return runBaiduAction('start', '打开百度官方登录失败', async () => {
    const result = await baiduNetdiskApi.startOfficialLogin()
    setOfficialLoginState(result?.official_login || { active: true, browser: result?.browser || '' })
    baiduStatusMessage.value = `✓ 已打开百度官方登录窗口${result?.browser ? ` · ${result.browser}` : ''}`
  })
}

async function completeBaiduOfficialLogin() {
  return runBaiduAction('complete', '同步百度官方登录失败', async () => {
    const result = await baiduNetdiskApi.completeOfficialLogin({ persist: true })
    setOfficialLoginState(result?.official_login || { active: false })
    mergeAccount(result?.account || {})
    baiduStatusMessage.value = `✓ ${baiduAccountDisplayName.value} 已同步`
  })
}

async function closeBaiduOfficialLogin() {
  return runBaiduAction('close', '关闭百度官方登录窗口失败', async () => {
    await baiduNetdiskApi.closeOfficialLogin()
    setOfficialLoginState({ active: false })
    baiduStatusMessage.value = '✓ 百度官方登录窗口已关闭'
  })
}

async function unbindBaiduAccount() {
  return runBaiduAction('unbind', '解绑失败', async () => {
    await baiduNetdiskApi.closeOfficialLogin().catch(() => {})
    const result = await baiduNetdiskApi.unbindAccount()
    const next = result?.account || {}
    props.config.baidu_netdisk.cookie = ''
    props.config.baidu_netdisk.enabled = Boolean(next.enabled)
    props.config.baidu_netdisk.account_name = ''
    props.config.baidu_netdisk.account_netdisk_name = ''
    props.config.baidu_netdisk.account_avatar_url = ''
    props.config.baidu_netdisk.account_uk = ''
    props.config.baidu_netdisk.vip_type = 0
    props.config.baidu_netdisk.vip_label = ''
    props.config.baidu_netdisk.vip_level = ''
    props.config.baidu_netdisk.quota_bytes = 0
    props.config.baidu_netdisk.used_bytes = 0
    props.config.baidu_netdisk.account_cached_at = 0
    setOfficialLoginState({ active: false })
    baiduStatusMessage.value = '✓ 百度账号已解绑'
  })
}

onMounted(() => {
  void refreshBaiduOfficialLoginStatus()
})
</script>

<style scoped>
.baidu-settings-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.settings-grid,
.settings-card,
.mini-grid,
.field-stack {
  overflow: visible;
}
.settings-grid {
  display: grid;
  gap: 18px;
  align-items: start;
}
.settings-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.mini-grid { display: grid; gap: 10px; }
.mini-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.field-stack { display: grid; gap: 12px; }
.baidu-bind-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}

.baidu-bind-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.baidu-bind-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.baidu-bind-copy > span {
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 700;
}

.baidu-official-login-main {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: var(--set-text-strong);
}
.baidu-official-login-main svg {
  flex: 0 0 auto;
  color: #2563eb;
}
.baidu-official-login-main div {
  display: grid;
  min-width: 0;
  gap: 3px;
}
.baidu-official-login-main strong,
.baidu-official-login-main small {
  min-width: 0;
  overflow-wrap: anywhere;
}
.baidu-official-login-main strong {
  font-size: 13px;
  font-weight: 750;
}
.baidu-official-login-main small {
  display: block;
  color: var(--set-text-muted);
  font-size: 12px;
  line-height: 1.45;
}
.baidu-official-login-actions {
  display: grid;
  grid-template-columns: repeat(3, max-content);
  gap: 8px;
  justify-content: end;
  align-items: center;
}
.baidu-account-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}
.baidu-account-buttons {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: max-content;
  gap: 8px;
  justify-content: flex-end;
}
.baidu-account-status {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  gap: 7px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.3;
  transition: all 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.baidu-account-status.is-ready {
  border-color: var(--set-success-border);
  background: var(--set-success-bg);
  color: var(--set-success-text);
}
.baidu-account-status.is-active {
  border-color: rgba(59, 130, 246, 0.25);
  background: rgba(59, 130, 246, 0.08);
  color: #1d4ed8;
}
.baidu-account-status.is-error {
  border-color: rgba(244, 63, 94, 0.3);
  background: rgba(244, 63, 94, 0.08);
  color: #be123c;
}
.baidu-account-status.is-loading {
  border-color: rgba(16, 185, 129, 0.42);
  background: linear-gradient(90deg, rgba(16, 185, 129, 0.14), rgba(34, 197, 94, 0.2), rgba(16, 185, 129, 0.14));
  background-size: 220% 100%;
  color: #047857;
  animation: baidu-status-pulse 1.2s ease-in-out infinite;
}
.baidu-account-status.is-loading :deep(svg) {
  animation: baidu-action-spin 0.84s linear infinite;
}
.baidu-account-status:hover {
  transform: translateY(-1px);
}
.baidu-account-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 46px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--set-success-border);
  background: var(--set-success-bg);
}
.baidu-account-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.45);
  background: var(--set-surface);
}
.baidu-account-avatar.is-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--set-success-text);
  font-size: 13px;
  font-weight: 800;
}
.baidu-account-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.baidu-account-main strong,
.baidu-account-main span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.baidu-account-main strong {
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 700;
}
.baidu-account-main span {
  color: var(--set-success-text);
  font-size: 12px;
}
.baidu-account-card small {
  color: var(--set-text-muted);
  font-size: 11px;
  white-space: nowrap;
}
.baidu-account-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.baidu-account-meta {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}
.baidu-account-meta span {
  color: var(--set-text-muted);
  font-size: 11.5px;
}
.baidu-account-meta strong {
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 700;
}
.baidu-account-note {
  color: var(--set-text-muted);
  font-size: 11.5px;
  line-height: 1.55;
}

.ghost-inline-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-surface);
  color: var(--set-text);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0;
  cursor: pointer;
  outline: none;
  box-shadow: none;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform: translateZ(0);
}

.ghost-inline-btn :deep(.stateful-button__content) {
  gap: 6px;
}

.ghost-inline-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
  box-shadow: none;
}

.ghost-inline-btn:not(:disabled):active {
  transform: translateY(0) scale(0.96);
}

.ghost-inline-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.ghost-inline-btn.warning {
  border-color: rgba(180, 83, 9, 0.4);
  color: #a16207;
}

.ghost-inline-btn.warning:not(:disabled):hover {
  border-color: rgba(180, 83, 9, 0.68);
  background: rgba(180, 83, 9, 0.08);
  color: #92400e;
}

.ghost-inline-btn.danger {
  border-color: rgba(244, 63, 94, 0.4);
  color: #be123c;
}

.ghost-inline-btn.danger:not(:disabled):hover {
  border-color: rgba(244, 63, 94, 0.72);
  background: rgba(244, 63, 94, 0.08);
  color: #9f1239;
}

.baidu-action-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.baidu-action-icon.is-loading :deep(svg) {
  animation: baidu-action-spin 0.84s linear infinite;
}

.baidu-action-icon.is-success :deep(svg),
.baidu-action-icon.is-error :deep(svg) {
  animation: baidu-action-pop 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes baidu-action-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes baidu-status-pulse {
  0% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0% 50%;
  }
}

@keyframes baidu-action-pop {
  0% {
    transform: scale(0.62) rotate(-12deg);
  }
  70% {
    transform: scale(1.14) rotate(6deg);
  }
  100% {
    transform: scale(1) rotate(0deg);
  }
}

@media (max-width: 980px) {
  .settings-grid.two,
  .mini-grid.three,
  .baidu-account-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .settings-grid.two,
  .mini-grid.three,
  .baidu-account-meta-grid,
  .baidu-account-actions,
  .baidu-bind-head {
    grid-template-columns: 1fr;
  }
  .baidu-account-buttons,
  .baidu-official-login-actions {
    justify-content: flex-start;
    grid-auto-flow: row;
    grid-auto-columns: minmax(0, 1fr);
    grid-template-columns: 1fr;
  }
  .ghost-inline-btn { width: 100%; }
}
</style>
