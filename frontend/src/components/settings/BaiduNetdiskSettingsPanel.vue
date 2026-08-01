<template>
  <div class="baidu-settings-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">百度网盘下载</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.baidu_netdisk.enabled" title="启用百度网盘下载" subtitle="通过百度官方登录态解析分享并直接下载。" />
          <div class="mini-grid three">
            <SettingsFieldCard label="下载根目录" hint="留空时使用待处理 input 目录或上层下载根目录。">
              <input v-model.trim="config.baidu_netdisk.download_root" class="field-input" type="text" placeholder="留空使用默认下载目录">
            </SettingsFieldCard>
            <SettingsFieldCard label="提取码分隔符" hint="支持“分享链接 + 分隔符 + 提取码”，例如链接----abcd。">
              <input v-model.trim="config.baidu_netdisk.share_code_separator" class="field-input" type="text" placeholder="----">
            </SettingsFieldCard>
            <SettingsFieldCard label="冲突策略">
              <AppDropdown v-model="config.baidu_netdisk.conflict_policy" :options="conflictPolicyOptions" class="settings-field-dd" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="下载线程数" hint="SVIP 建议 20，BaiduPCS-Go 支持范围 1~20。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.max_parallel" :min="1" :max="20" />
            </SettingsFieldCard>
            <SettingsFieldCard label="全局同时下载文件数" hint="所有百度下载任务共享这个上限，SVIP 建议 5，范围 1~5。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.max_download_load" :min="1" :max="5" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="转存并发数" hint="只限制分享转存请求，不影响 BaiduPCS-Go 下载并发；建议保持 1。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.transfer_max_concurrency" :min="1" :max="5" />
            </SettingsFieldCard>
            <SettingsFieldCard label="转存网络重试次数" hint="仅重试 SSL EOF、连接超时及 429/5xx，不重试分享失效等业务错误。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.transfer_retry_count" :min="0" :max="8" />
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow
            v-model="config.baidu_netdisk.low_speed_refresh_enabled"
            title="持续低速自动换链"
            subtitle="SVIP 大文件持续低于阈值时，保留 BaiduPCS-Go 断点并重新获取下载线路。"
          />
          <div v-if="config.baidu_netdisk.low_speed_refresh_enabled" class="mini-grid three">
            <SettingsFieldCard label="低速阈值" hint="窗口平均速度低于该值时开始判定，单位 MB/s。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.low_speed_threshold_mbps" :min="1" :max="20" />
            </SettingsFieldCard>
            <SettingsFieldCard label="持续时间" hint="连续低速达到该时长后换链，单位秒。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.low_speed_duration_seconds" :min="30" :max="1800" :step="30" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最多换链次数" hint="达到上限后保留当前线路继续下载，避免无限重试。">
              <SettingsNumberStepper v-model="config.baidu_netdisk.low_speed_refresh_limit" :min="0" :max="5" />
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow v-model="config.baidu_netdisk.svip_speed_enabled" title="SVIP 高速提示" subtitle="账号为 SVIP 时，工作台和任务中心显示高速模式。" />
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">账号绑定</div>
        <div class="field-stack">
          <div class="baidu-bind-card">
            <template v-if="baiduLoginEntryVisible">
              <div class="baidu-bind-head">
                <div class="baidu-bind-copy">
                  <span>百度官方登录</span>
                  <div class="baidu-official-login-main">
                    <img :src="baiduNetdiskIconUrl" alt="" class="baidu-platform-icon" draggable="false">
                    <div>
                      <strong>{{ baiduOfficialLoginTitle }}</strong>
                      <small v-if="baiduOfficialLoginSubtitle">{{ baiduOfficialLoginSubtitle }}</small>
                    </div>
                  </div>
                </div>
                <div class="baidu-official-login-actions">
                  <StatefulButton
                    class="ghost-inline-btn primary"
                    unstyled
                    :show-default-icons="false"
                    :disabled="baiduTesting && baiduAction !== 'qr-start'"
                    :success-hold="1100"
                    @click="startBaiduQrLogin"
                  >
                    <template #prefix="{ state }">
                      <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                        <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                        <QrCode v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                        <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                        <XCircle v-else :size="14" :stroke-width="2.4" />
                      </span>
                    </template>
                    {{ baiduQrLoginActive ? '重新生成二维码' : '扫码登录' }}
                  </StatefulButton>
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

              <div v-if="baiduQrLoginActive" class="baidu-qr-login-card">
                <div class="baidu-qr-preview">
                  <img :src="baiduQrLogin.image_url" alt="" referrerpolicy="no-referrer">
                </div>
                <div class="baidu-qr-info">
                  <strong>{{ baiduQrLoginStatusText || '请使用百度网盘 App 扫码登录' }}</strong>
                  <small>扫码并在手机端确认后会自动同步账号，不需要手动复制 Cookie。</small>
                  <button type="button" class="baidu-cookie-toggle" @click="closeBaiduQrLogin">关闭二维码</button>
                </div>
              </div>

              <div class="baidu-cookie-bind">
                <div class="baidu-cookie-bind-head">
                  <div>
                    <strong>账号密码登录（可选）</strong>
                    <small>百度常返回 50052 风控错误，失败时直接改用扫码</small>
                  </div>
                  <button type="button" class="baidu-cookie-toggle" @click="baiduPasswordPanelOpen = !baiduPasswordPanelOpen">
                    {{ baiduPasswordPanelOpen ? '收起' : '展开' }}
                  </button>
                </div>
                <div v-if="baiduPasswordPanelOpen" class="baidu-login-form">
                  <input
                    v-model.trim="baiduLoginUsername"
                    class="field-input"
                    type="text"
                    autocomplete="username"
                    placeholder="手机号 / 邮箱 / 用户名"
                  >
                  <AnimatedPasswordInput
                    v-model="baiduLoginPassword"
                    placeholder="百度账号密码"
                    autocomplete="current-password"
                  />
                  <StatefulButton
                    class="ghost-inline-btn"
                    unstyled
                    :show-default-icons="false"
                    :disabled="!baiduLoginUsername.trim() || !baiduLoginPassword || (baiduTesting && baiduAction !== 'password')"
                    :success-hold="1100"
                    @click="loginBaiduWithPassword"
                  >
                    <template #prefix="{ state }">
                      <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                        <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                        <KeyRound v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                        <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                        <XCircle v-else :size="14" :stroke-width="2.4" />
                      </span>
                    </template>
                    登录并同步
                  </StatefulButton>
                </div>
              </div>

              <div class="baidu-cookie-bind">
                <div class="baidu-cookie-bind-head">
                  <div>
                    <strong>手动 Cookie 绑定</strong>
                    <small>扫码或官方登录不可用时的兜底方式</small>
                  </div>
                  <button type="button" class="baidu-cookie-toggle" @click="baiduCookiePanelOpen = !baiduCookiePanelOpen">
                    {{ baiduCookiePanelOpen ? '收起' : '展开' }}
                  </button>
                </div>
                <div v-if="baiduCookiePanelOpen" class="baidu-cookie-bind-body">
                  <textarea
                    v-model="baiduManualCookie"
                    class="field-input baidu-cookie-input"
                    rows="4"
                    spellcheck="false"
                    placeholder="BDUSS=...; STOKEN=...; BAIDUID=..."
                  ></textarea>
                  <StatefulButton
                    class="ghost-inline-btn"
                    unstyled
                    :show-default-icons="false"
                    :disabled="!baiduManualCookie.trim() || (baiduTesting && baiduAction !== 'cookie')"
                    :success-hold="1100"
                    @click="bindBaiduManualCookie"
                  >
                    <template #prefix="{ state }">
                      <span class="baidu-action-icon" :class="`is-${state}`" aria-hidden="true">
                        <LoaderCircle v-if="state === 'loading'" :size="14" :stroke-width="2.4" />
                        <KeyRound v-else-if="state === 'idle'" :size="14" :stroke-width="2.4" />
                        <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                        <XCircle v-else :size="14" :stroke-width="2.4" />
                      </span>
                    </template>
                    验证并保存 Cookie
                  </StatefulButton>
                </div>
              </div>
            </template>

            <div v-if="baiduAccountStatusVisible" class="baidu-account-actions">
              <div
                class="baidu-account-status"
                :class="{
                  'is-ready': baiduAccountReady,
                  'is-active': baiduOfficialLoginActive || baiduQrLoginActive,
                  'is-loading': baiduTesting || baiduAutoSyncing,
                  'is-error': baiduStatusMessage.startsWith('✗') || (baiduAccountVisible && !baiduAccountReady)
                }"
                :aria-busy="baiduTesting || baiduAutoSyncing ? 'true' : undefined"
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
                <div class="baidu-account-title-row">
                  <strong>{{ baiduAccountDisplayName }}</strong>
                  <span class="baidu-vip-pill">{{ baiduVipStatusText }}</span>
                </div>
                <div class="baidu-account-detail-line">
                  <span v-if="baiduNetdiskNameText">{{ baiduNetdiskNameText }}</span>
                  <span v-if="baiduAccountUkText">{{ baiduAccountUkText }}</span>
                  <span>{{ baiduAccountCachedText }}</span>
                </div>
                <div class="baidu-account-detail-line">
                  <span>{{ baiduVipExpireDisplayText }}</span>
                  <span>{{ baiduQuotaSummaryText }}</span>
                </div>
              </div>
            </div>

            <div v-if="baiduAccountVisible" class="baidu-account-meta-grid">
              <div class="baidu-account-meta">
                <span>账号状态</span>
                <strong>{{ config.baidu_netdisk.enabled ? '已启用' : '未启用' }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>会员状态</span>
                <strong>{{ baiduVipStatusText }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>到期时间</span>
                <strong>{{ baiduVipExpireDisplayText }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>总空间</span>
                <strong>{{ baiduQuotaDisplayText }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>已使用</span>
                <strong>{{ baiduUsedDisplayText }}</strong>
              </div>
              <div class="baidu-account-meta">
                <span>剩余空间</span>
                <strong>{{ baiduRemainingDisplayText }}</strong>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, Crown, ExternalLink, KeyRound, LoaderCircle, QrCode, RefreshCw, ShieldCheck, Trash2, TriangleAlert, XCircle } from 'lucide-vue-next'
import baiduNetdiskIconUrl from '../../assets/platforms/baidu-netdisk.ico'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { baiduNetdiskApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})
const emit = defineEmits(['persisted'])

const conflictPolicyOptions = [
  { value: 'resume', label: '断点续传' },
  { value: 'rename', label: '自动改名' },
  { value: 'skip', label: '已存在跳过' }
]

const baiduTesting = ref(false)
const baiduAction = ref('')
const baiduStatusMessage = ref('')
const baiduAutoSyncing = ref(false)
const baiduPasswordPanelOpen = ref(false)
const baiduLoginUsername = ref('')
const baiduLoginPassword = ref('')
const baiduCookiePanelOpen = ref(false)
const baiduManualCookie = ref('')
const baiduQrLogin = ref({
  active: false,
  session_id: '',
  status: '',
  message: '',
  image_url: '',
  created_at: 0,
  expires_at: 0
})
const baiduOfficialLogin = ref({
  active: false,
  browser: '',
  browser_path: '',
  profile_dir: '',
  started_at: 0,
  login_url: ''
})
const BAIDU_OFFICIAL_LOGIN_POLL_MS = 1800
const BAIDU_QR_LOGIN_POLL_MS = 900
let baiduOfficialLoginPollTimer = 0
let baiduQrLoginPollTimer = 0
let baiduQrLoginPolling = false

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
const baiduVipExpireAt = computed(() => Number(props.config.baidu_netdisk.vip_expire_at || 0))
const baiduVipExpireText = computed(() => {
  const timestamp = baiduVipExpireAt.value
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `会员截止日 ${year}/${month}/${day}`
})
const baiduVipStatusText = computed(() => `${baiduVipLabel.value}${baiduVipLevelText.value}`)
const baiduVipExpireDisplayText = computed(() => baiduVipExpireText.value || '未返回到期时间')
const baiduNetdiskNameText = computed(() => {
  const name = String(props.config.baidu_netdisk.account_netdisk_name || '').trim()
  return name && name !== baiduAccountDisplayName.value ? `网盘名 ${name}` : ''
})
const baiduAccountUkText = computed(() => {
  const uk = String(props.config.baidu_netdisk.account_uk || '').trim()
  return uk ? `UK ${uk}` : ''
})
const baiduQuotaAvailable = computed(() => (
  Number(props.config.baidu_netdisk.quota_bytes || 0) > 0
    || Number(props.config.baidu_netdisk.used_bytes || 0) > 0
))
const remainingBytes = computed(() => Math.max(0, Number(props.config.baidu_netdisk.quota_bytes || 0) - Number(props.config.baidu_netdisk.used_bytes || 0)))
const baiduQuotaDisplayText = computed(() => baiduQuotaAvailable.value ? formatBytes(props.config.baidu_netdisk.quota_bytes) : '容量待刷新')
const baiduUsedDisplayText = computed(() => baiduQuotaAvailable.value ? formatBytes(props.config.baidu_netdisk.used_bytes) : '容量待刷新')
const baiduRemainingDisplayText = computed(() => baiduQuotaAvailable.value ? formatBytes(remainingBytes.value) : '容量待刷新')
const baiduQuotaSummaryText = computed(() => {
  if (!baiduQuotaAvailable.value) return '容量待刷新'
  return `已用 ${baiduUsedDisplayText.value} / ${baiduQuotaDisplayText.value}`
})
const baiduLoginCookieReady = computed(() => Boolean(props.config.baidu_netdisk.cookie))
const baiduAccountVisible = computed(() => Boolean(
  props.config.baidu_netdisk.account_name
    || props.config.baidu_netdisk.account_netdisk_name
    || props.config.baidu_netdisk.account_avatar_url
    || Number(props.config.baidu_netdisk.vip_type || 0) > 0
    || Number(props.config.baidu_netdisk.vip_expire_at || 0) > 0
    || Number(props.config.baidu_netdisk.quota_bytes || 0) > 0
))
const baiduAccountReady = computed(() => Boolean(props.config.baidu_netdisk.enabled && baiduLoginCookieReady.value))
const baiduAccountInitial = computed(() => (baiduAccountDisplayName.value || 'B').trim().slice(0, 1).toUpperCase() || 'B')
const baiduOfficialLoginActive = computed(() => Boolean(baiduOfficialLogin.value?.active))
const baiduOfficialLoginBrowserLabel = computed(() => String(baiduOfficialLogin.value?.browser || '').trim() || '百度官方登录')
const baiduOfficialLoginTitle = computed(() => (
  baiduOfficialLoginActive.value
    ? '百度官方登录窗口已打开'
    : '打开百度官方登录'
))
const baiduOfficialLoginSubtitle = computed(() => '通过登录状态同步获取用户信息')
const baiduQrLoginActive = computed(() => Boolean(baiduQrLogin.value?.active))
const baiduLoginEntryVisible = computed(() => Boolean(!baiduAccountReady.value || baiduOfficialLoginActive.value || baiduQrLoginActive.value))
const baiduQrLoginStatusText = computed(() => {
  const status = String(baiduQrLogin.value?.status || '').trim()
  if (baiduTesting.value && baiduAction.value === 'qr-start') return '正在生成扫码二维码...'
  if (status === 'scanned') return '已扫码，等待手机确认登录'
  if (status === 'confirmed') return '已确认登录，正在同步账号...'
  if (status === 'expired') return '二维码已过期，请重新生成'
  if (status === 'failed') return baiduQrLogin.value?.message || '扫码登录失败'
  if (status === 'cancelled') return '扫码登录已取消'
  if (baiduQrLoginActive.value) return '请使用百度网盘 App 扫码登录'
  return ''
})
const baiduAccountCachedText = computed(() => {
  const cachedAt = Number(props.config.baidu_netdisk.account_cached_at || 0)
  if (!cachedAt) return '本地缓存'
  const date = new Date(cachedAt * 1000)
  if (Number.isNaN(date.getTime())) return '本地缓存'
  return `上次刷新 ${date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
})
const baiduAccountStatusVisible = computed(() => Boolean(
  baiduAccountReady.value
    || baiduTesting.value
    || baiduAutoSyncing.value
    || baiduQrLoginActive.value
    || baiduOfficialLoginActive.value
    || baiduStatusMessage.value.startsWith('✗')
    || baiduStatusMessage.value.startsWith('✓')
    || baiduAccountVisible.value
    || baiduVipExpireText.value
))
const baiduAccountStatusText = computed(() => {
  if (baiduAutoSyncing.value) return '检测到登录，正在自动同步百度账号...'
  if (baiduTesting.value && baiduAction.value === 'start') return '正在打开百度官方登录窗口...'
  if (baiduTesting.value && baiduAction.value === 'complete') return '正在同步百度登录状态...'
  if (baiduTesting.value && baiduAction.value === 'cookie') return '正在验证并保存百度 Cookie...'
  if (baiduTesting.value && baiduAction.value === 'password') return '正在用账号密码登录百度...'
  if (baiduTesting.value && baiduAction.value === 'qr-start') return '正在生成百度扫码二维码...'
  if (baiduTesting.value && baiduAction.value === 'qr-poll') return '正在轮询百度扫码状态...'
  if (baiduTesting.value && baiduAction.value === 'refresh') return '正在刷新百度账号和容量...'
  if (baiduTesting.value && baiduAction.value === 'unbind') return '正在解绑百度账号...'
  if (baiduStatusMessage.value.startsWith('✗')) return baiduStatusMessage.value
  if (baiduStatusMessage.value.startsWith('✓')) return baiduStatusMessage.value
  if (baiduQrLoginStatusText.value) return baiduQrLoginStatusText.value
  if (baiduOfficialLoginActive.value) return `等待官方登录完成，会自动同步 · ${baiduOfficialLoginBrowserLabel.value}`
  if (baiduAccountReady.value) return `百度账号已绑定 · ${baiduVipStatusText.value}`
  if (baiduAccountVisible.value) return '百度账号资料为历史缓存，登录态缺少 BDUSS，请重新扫码或重新绑定 Cookie'
  if (baiduVipExpireText.value) return `${baiduVipLabel.value} · ${baiduVipExpireText.value}`
  return ''
})
const baiduAccountIcon = computed(() => {
  if (baiduTesting.value || baiduAutoSyncing.value) return LoaderCircle
  if (baiduQrLoginActive.value) return LoaderCircle
  if (baiduStatusMessage.value.startsWith('✗')) return TriangleAlert
  if (baiduAccountReady.value) return baiduVipLabel.value.includes('SVIP') ? Crown : CheckCircle2
  if (baiduAccountVisible.value) return TriangleAlert
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

function setQrLoginState(qrLogin = {}) {
  baiduQrLogin.value = {
    active: Boolean(qrLogin?.active),
    session_id: String(qrLogin?.session_id || '').trim(),
    status: String(qrLogin?.status || '').trim(),
    message: String(qrLogin?.message || '').trim(),
    image_url: String(qrLogin?.image_url || '').trim(),
    created_at: Number(qrLogin?.created_at || 0),
    expires_at: Number(qrLogin?.expires_at || 0)
  }
}

function mergeAccount(account = {}) {
  const hasField = key => Object.prototype.hasOwnProperty.call(account || {}, key)
  const configured = Boolean(
    account?.configured
      || account?.ready
      || account?.login_cookie_valid
  )
  props.config.baidu_netdisk.enabled = configured
  props.config.baidu_netdisk.cookie = configured ? '********' : ''
  if (hasField('name')) props.config.baidu_netdisk.account_name = String(account.name || '').trim()
  if (hasField('netdisk_name')) props.config.baidu_netdisk.account_netdisk_name = String(account.netdisk_name || '').trim()
  if (hasField('avatar_url')) props.config.baidu_netdisk.account_avatar_url = String(account.avatar_url || '').trim()
  if (hasField('uk')) props.config.baidu_netdisk.account_uk = String(account.uk || '').trim()
  if (hasField('vip_type')) props.config.baidu_netdisk.vip_type = Number(account.vip_type || 0)
  if (hasField('vip_label')) props.config.baidu_netdisk.vip_label = String(account.vip_label || '').trim()
  if (hasField('vip_level')) props.config.baidu_netdisk.vip_level = String(account.vip_level || '').trim()
  if (hasField('vip_expire_at')) props.config.baidu_netdisk.vip_expire_at = Number(account.vip_expire_at || 0)
  if (hasField('quota_bytes')) props.config.baidu_netdisk.quota_bytes = Number(account.quota_bytes || 0)
  if (hasField('used_bytes')) props.config.baidu_netdisk.used_bytes = Number(account.used_bytes || 0)
  props.config.baidu_netdisk.account_cached_at = Number(account.cached_at || Date.now() / 1000)
}

function formatBaiduError(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function formatBaiduSuccess(result, fallback) {
  const warning = String(result?.warning || '').trim()
  if (!warning) return `✓ ${fallback}`
  if (warning.includes('容量刷新失败')) {
    return `✓ ${fallback}；容量稍后重试`
  }
  return `✓ ${fallback}；${warning}`
}

function normalizeBaiduCookie(value) {
  return String(value || '')
    .trim()
    .replace(/^cookie\s*:\s*/i, '')
    .replace(/\r?\n/g, '; ')
    .replace(/;{2,}/g, ';')
    .replace(/\s*;\s*/g, '; ')
    .trim()
}

function hasBaiduLoginCookie(cookie) {
  return /(?:^|;\s*)BDUSS(?:_BFESS)?=/i.test(String(cookie || ''))
}

function isBaiduLoginPendingError(message) {
  return [
    '未检测到百度登录态',
    '请先在官方登录窗口完成登录',
    'DevTools 未返回 Cookie'
  ].some(fragment => String(message || '').includes(fragment))
}

function stopBaiduOfficialLoginPolling() {
  if (!baiduOfficialLoginPollTimer) return
  window.clearInterval(baiduOfficialLoginPollTimer)
  baiduOfficialLoginPollTimer = 0
}

function startBaiduOfficialLoginPolling() {
  stopBaiduOfficialLoginPolling()
  if (!baiduOfficialLoginActive.value) return
  baiduOfficialLoginPollTimer = window.setInterval(() => {
    void pollBaiduOfficialLogin()
  }, BAIDU_OFFICIAL_LOGIN_POLL_MS)
}

function stopBaiduQrLoginPolling() {
  if (baiduQrLoginPollTimer) {
    window.clearTimeout(baiduQrLoginPollTimer)
  }
  baiduQrLoginPollTimer = 0
  baiduQrLoginPolling = false
}

function scheduleBaiduQrLoginPoll(delay = BAIDU_QR_LOGIN_POLL_MS) {
  if (!baiduQrLoginActive.value) return
  if (baiduQrLoginPollTimer) {
    window.clearTimeout(baiduQrLoginPollTimer)
  }
  baiduQrLoginPollTimer = window.setTimeout(() => {
    baiduQrLoginPollTimer = 0
    void pollBaiduQrLogin()
  }, delay)
}

function startBaiduQrLoginPolling() {
  stopBaiduQrLoginPolling()
  scheduleBaiduQrLoginPoll(0)
}

async function autoCompleteBaiduOfficialLogin() {
  if (baiduTesting.value || baiduAutoSyncing.value || !baiduOfficialLoginActive.value) return false
  baiduAutoSyncing.value = true
  try {
    const result = await baiduNetdiskApi.completeOfficialLogin({ persist: true })
    setOfficialLoginState({ ...(result?.official_login || {}), active: false })
    mergeAccount(result?.account || {})
    emit('persisted')
    stopBaiduOfficialLoginPolling()
    baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 已自动同步`)
    return true
  } catch (error) {
    const message = formatBaiduError(error, '自动同步百度官方登录失败')
    if (isBaiduLoginPendingError(message)) {
      baiduStatusMessage.value = ''
      return false
    }
    if (String(message).includes('窗口已关闭') || String(message).includes('没有正在进行')) {
      setOfficialLoginState({ active: false })
      stopBaiduOfficialLoginPolling()
    }
    baiduStatusMessage.value = `✗ ${message}`
    return false
  } finally {
    baiduAutoSyncing.value = false
  }
}

async function pollBaiduOfficialLogin() {
  if (baiduTesting.value || baiduAutoSyncing.value) return
  try {
    const result = await baiduNetdiskApi.officialLoginStatus()
    setOfficialLoginState(result?.official_login || {})
    if (result?.account) {
      mergeAccount(result.account)
    }
    if (!baiduOfficialLoginActive.value) {
      stopBaiduOfficialLoginPolling()
      return
    }
    await autoCompleteBaiduOfficialLogin()
  } catch (error) {
    const message = formatBaiduError(error, '刷新百度官方登录状态失败')
    if (!isBaiduLoginPendingError(message)) {
      baiduStatusMessage.value = `✗ ${message}`
    }
  }
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
    if (baiduOfficialLoginActive.value) {
      startBaiduOfficialLoginPolling()
    } else {
      stopBaiduOfficialLoginPolling()
    }
    baiduStatusMessage.value = ''
  })
}

async function refreshBaiduAccountStatus() {
  return runBaiduAction('refresh', '刷新百度账号状态失败', async () => {
    const result = await baiduNetdiskApi.refreshAccount()
    setOfficialLoginState(result?.official_login || {})
    mergeAccount(result?.account || {})
    emit('persisted')
    baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 状态已刷新`)
  })
}

async function bindBaiduManualCookie() {
  return runBaiduAction('cookie', '绑定百度 Cookie 失败', async () => {
    const cookie = normalizeBaiduCookie(baiduManualCookie.value)
    if (!cookie) {
      throw new Error('百度 Cookie 不能为空')
    }
    if (!hasBaiduLoginCookie(cookie)) {
      throw new Error('百度 Cookie 缺少 BDUSS，请重新扫码或从已登录浏览器复制完整 Cookie')
    }
    const qrSessionId = baiduQrLogin.value.session_id
    const result = await baiduNetdiskApi.testAccount({ cookie, persist: true, allowQuotaFailure: true })
    setOfficialLoginState({ active: false })
    setQrLoginState({ active: false, status: 'closed' })
    mergeAccount(result?.account || {})
    emit('persisted')
    stopBaiduOfficialLoginPolling()
    stopBaiduQrLoginPolling()
    await baiduNetdiskApi.closeQrLogin({ sessionId: qrSessionId }).catch(() => {})
    baiduManualCookie.value = ''
    baiduCookiePanelOpen.value = false
    baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 已绑定`)
  })
}

async function loginBaiduWithPassword() {
  return runBaiduAction('password', '百度账号密码登录失败', async () => {
    const username = baiduLoginUsername.value.trim()
    if (!username || !baiduLoginPassword.value) {
      throw new Error('百度账号和密码不能为空')
    }
    const qrSessionId = baiduQrLogin.value.session_id
    const result = await baiduNetdiskApi.passwordLogin({
      username,
      password: baiduLoginPassword.value,
      persist: true
    })
    setOfficialLoginState({ active: false })
    setQrLoginState({ active: false, status: 'closed' })
    mergeAccount(result?.account || {})
    emit('persisted')
    stopBaiduOfficialLoginPolling()
    stopBaiduQrLoginPolling()
    await baiduNetdiskApi.closeQrLogin({ sessionId: qrSessionId }).catch(() => {})
    baiduLoginPassword.value = ''
    baiduPasswordPanelOpen.value = false
    baiduCookiePanelOpen.value = false
    baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 已账号密码同步`)
  })
}

async function startBaiduQrLogin() {
  return runBaiduAction('qr-start', '生成百度扫码二维码失败', async () => {
    stopBaiduQrLoginPolling()
    stopBaiduOfficialLoginPolling()
    setOfficialLoginState({ active: false })
    await baiduNetdiskApi.closeQrLogin({ sessionId: baiduQrLogin.value.session_id }).catch(() => {})
    const result = await baiduNetdiskApi.startQrLogin()
    setQrLoginState(result?.qr_login || {})
    baiduPasswordPanelOpen.value = false
    baiduCookiePanelOpen.value = false
    baiduStatusMessage.value = ''
    startBaiduQrLoginPolling()
  })
}

async function pollBaiduQrLogin() {
  if (baiduQrLoginPolling || !baiduQrLoginActive.value) return
  baiduQrLoginPolling = true
  try {
    const result = await baiduNetdiskApi.pollQrLogin({
      sessionId: baiduQrLogin.value.session_id,
      persist: true
    })
    setQrLoginState(result?.qr_login || {})
    if (result?.account) {
      mergeAccount(result.account)
      emit('persisted')
      stopBaiduQrLoginPolling()
      stopBaiduOfficialLoginPolling()
      baiduManualCookie.value = ''
      baiduLoginPassword.value = ''
      baiduPasswordPanelOpen.value = false
      baiduCookiePanelOpen.value = false
      baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 已扫码同步`)
      return
    }
    if (!baiduQrLoginActive.value) {
      stopBaiduQrLoginPolling()
    } else {
      scheduleBaiduQrLoginPoll()
    }
  } catch (error) {
    const message = formatBaiduError(error, '轮询百度扫码登录失败')
    baiduStatusMessage.value = `✗ ${message}`
    stopBaiduQrLoginPolling()
  } finally {
    baiduQrLoginPolling = false
  }
}

async function closeBaiduQrLogin() {
  stopBaiduQrLoginPolling()
  const sessionId = baiduQrLogin.value.session_id
  setQrLoginState({ active: false, status: 'closed' })
  await baiduNetdiskApi.closeQrLogin({ sessionId }).catch(() => {})
  baiduStatusMessage.value = '✓ 百度扫码登录已关闭'
}

async function startBaiduOfficialLogin() {
  return runBaiduAction('start', '打开百度官方登录失败', async () => {
    const result = await baiduNetdiskApi.startOfficialLogin()
    const qrSessionId = baiduQrLogin.value.session_id
    setOfficialLoginState(result?.official_login || { active: true, browser: result?.browser || '' })
    stopBaiduQrLoginPolling()
    setQrLoginState({ active: false, status: 'closed' })
    await baiduNetdiskApi.closeQrLogin({ sessionId: qrSessionId }).catch(() => {})
    baiduPasswordPanelOpen.value = false
    baiduCookiePanelOpen.value = false
    startBaiduOfficialLoginPolling()
    baiduStatusMessage.value = `✓ 已打开百度官方登录窗口${result?.browser ? ` · ${result.browser}` : ''}，登录完成后会自动同步`
  })
}

async function completeBaiduOfficialLogin() {
  return runBaiduAction('complete', '同步百度官方登录失败', async () => {
    const result = await baiduNetdiskApi.completeOfficialLogin({ persist: true })
    setOfficialLoginState({ ...(result?.official_login || {}), active: false })
    mergeAccount(result?.account || {})
    emit('persisted')
    stopBaiduOfficialLoginPolling()
    baiduLoginPassword.value = ''
    baiduPasswordPanelOpen.value = false
    baiduCookiePanelOpen.value = false
    baiduStatusMessage.value = formatBaiduSuccess(result, `${baiduAccountDisplayName.value} 已同步`)
  })
}

async function closeBaiduOfficialLogin() {
  return runBaiduAction('close', '关闭百度官方登录窗口失败', async () => {
    await baiduNetdiskApi.closeOfficialLogin()
    setOfficialLoginState({ active: false })
    stopBaiduOfficialLoginPolling()
    baiduStatusMessage.value = '✓ 百度官方登录窗口已关闭'
  })
}

async function unbindBaiduAccount() {
  return runBaiduAction('unbind', '解绑失败', async () => {
    await baiduNetdiskApi.closeOfficialLogin().catch(() => {})
    await baiduNetdiskApi.closeQrLogin({ sessionId: baiduQrLogin.value.session_id }).catch(() => {})
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
    props.config.baidu_netdisk.vip_expire_at = 0
    props.config.baidu_netdisk.quota_bytes = 0
    props.config.baidu_netdisk.used_bytes = 0
    props.config.baidu_netdisk.account_cached_at = 0
    setOfficialLoginState({ active: false })
    setQrLoginState({ active: false, status: 'closed' })
    emit('persisted')
    stopBaiduOfficialLoginPolling()
    stopBaiduQrLoginPolling()
    baiduLoginPassword.value = ''
    baiduPasswordPanelOpen.value = false
    baiduCookiePanelOpen.value = false
    baiduStatusMessage.value = '✓ 百度账号已解绑'
  })
}

onMounted(() => {
  void refreshBaiduOfficialLoginStatus()
})

onBeforeUnmount(() => {
  stopBaiduOfficialLoginPolling()
  stopBaiduQrLoginPolling()
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
.mini-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
.baidu-official-login-main :is(svg, img) {
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
}
.baidu-official-login-main svg {
  color: #2563eb;
}
.baidu-platform-icon {
  object-fit: contain;
  border-radius: 4px;
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
  grid-template-columns: repeat(4, max-content);
  gap: 8px;
  justify-content: end;
  align-items: center;
}
.baidu-account-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
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
  align-items: flex-start;
  min-width: 0;
  max-width: 100%;
  min-height: 34px;
  gap: 7px;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.3;
  transition: all 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.baidu-account-status :deep(svg) {
  flex: 0 0 auto;
  margin-top: 1px;
}
.baidu-account-status span {
  min-width: 0;
  overflow-wrap: normal;
  word-break: keep-all;
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
.baidu-qr-login-card {
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.07);
}
.baidu-qr-preview {
  display: grid;
  place-items: center;
  width: 132px;
  height: 132px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: #fff;
  overflow: hidden;
}
.baidu-qr-preview img {
  width: 120px;
  height: 120px;
  object-fit: contain;
}
.baidu-qr-info {
  display: grid;
  gap: 7px;
  min-width: 0;
}
.baidu-qr-info strong {
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 750;
  overflow-wrap: anywhere;
}
.baidu-qr-info small {
  color: var(--set-text-muted);
  font-size: 12px;
  line-height: 1.45;
}
.baidu-cookie-bind {
  display: grid;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px dashed rgba(59, 130, 246, 0.3);
  background: rgba(59, 130, 246, 0.05);
}
.baidu-cookie-bind-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}
.baidu-cookie-bind-head div {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.baidu-cookie-bind-head strong {
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 750;
}
.baidu-cookie-bind-head small {
  color: var(--set-text-muted);
  font-size: 11.5px;
  line-height: 1.4;
}
.baidu-cookie-toggle {
  height: 28px;
  padding: 0 10px;
  border: 1px solid rgba(59, 130, 246, 0.22);
  border-radius: 9px;
  background: var(--set-surface);
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.baidu-cookie-toggle:hover {
  transform: translateY(-1px);
  border-color: rgba(59, 130, 246, 0.42);
  background: rgba(59, 130, 246, 0.08);
}
.baidu-cookie-toggle:active {
  transform: translateY(0) scale(0.96);
}
.baidu-cookie-bind-body {
  display: grid;
  gap: 10px;
}
.baidu-login-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}
.baidu-cookie-input {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.5;
}
.baidu-account-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  min-height: 62px;
  padding: 10px 12px;
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
  gap: 5px;
}
.baidu-account-title-row {
  display: flex;
  min-width: 0;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.baidu-account-title-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.baidu-account-title-row strong {
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 700;
}
.baidu-vip-pill {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  border: 1px solid rgba(16, 185, 129, 0.22);
  background: rgba(16, 185, 129, 0.12);
  color: var(--set-success-text);
  font-size: 11.5px;
  font-weight: 750;
}
.baidu-account-detail-line {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 10px;
  color: var(--set-text-muted);
  font-size: 11.5px;
  line-height: 1.35;
}
.baidu-account-detail-line span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.baidu-account-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
  overflow-wrap: anywhere;
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

.ghost-inline-btn.primary {
  border-color: rgba(37, 99, 235, 0.32);
  color: #1d4ed8;
}

.ghost-inline-btn.primary:not(:disabled):hover {
  border-color: rgba(37, 99, 235, 0.52);
  background: rgba(37, 99, 235, 0.08);
  color: #1e40af;
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
  .mini-grid.two,
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
  .baidu-qr-login-card {
    grid-template-columns: 1fr;
  }
  .baidu-qr-preview {
    width: 100%;
    max-width: 180px;
    height: 180px;
    justify-self: center;
  }
  .baidu-qr-preview img {
    width: 164px;
    height: 164px;
  }
  .baidu-cookie-bind-head {
    grid-template-columns: 1fr;
  }
  .baidu-cookie-toggle {
    width: 100%;
  }
  .ghost-inline-btn { width: 100%; }
}
</style>
