<template>
  <div class="http-settings-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">HTTP 外链下载</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.http_downloader.enabled" title="启用 HTTP 外链下载" subtitle="ASMR 同步页可把 HTTP/HTTPS 直链交给 aria2 下载。" />
          <SettingsFieldCard label="下载根目录" hint="留空时使用 storage.input_path，也就是待处理 input 目录。">
            <input v-model="config.http_downloader.download_root" class="field-input" type="text" placeholder="留空使用待处理 input 目录">
          </SettingsFieldCard>

          <div class="mini-grid three">
            <SettingsFieldCard label="下载引擎" hint="首版仅支持 aria2。">
              <AppDropdown v-model="config.http_downloader.engine" :options="httpEngineOptions" class="settings-field-dd" />
            </SettingsFieldCard>
            <SettingsFieldCard label="aria2 路径" hint="Docker 内默认 aria2c；Windows 可填 aria2c.exe 绝对路径。">
              <input v-model="config.http_downloader.aria2_path" class="field-input" type="text" placeholder="aria2c">
            </SettingsFieldCard>
            <SettingsFieldCard label="HTTP 代理" hint="代理地址本身，和 asmr.one 代理分离。">
              <input v-model="config.http_downloader.proxy_url" class="field-input" type="text" placeholder="http://127.0.0.1:7890">
            </SettingsFieldCard>
          </div>

          <SettingsFieldCard label="代理适用范围" hint="只让选中的 HTTP 下载来源走上面的代理；不选则全部直连。">
            <AppDropdown
              v-model="config.http_downloader.proxy_platforms"
              :options="httpProxyPlatformOptions"
              multiple
              class="settings-field-dd http-proxy-platform-dd"
              menu-class="http-proxy-platform-menu"
              placeholder="全部直连"
              :menu-min-width="260"
            >
              <template #trigger="{ open, toggle, hasSelection }">
                <button
                  type="button"
                  class="http-proxy-trigger"
                  :class="{ 'is-open': open, 'is-placeholder': !hasSelection }"
                  @click="toggle"
                >
                  <span v-if="selectedHttpProxyPlatformOptions.length" class="http-proxy-trigger-icons">
                    <span
                      v-for="option in selectedHttpProxyPlatformOptions"
                      :key="option.value"
                      class="http-proxy-icon-chip"
                      :title="option.label"
                    >
                      <component :is="option.icon" :size="15" :stroke-width="2.3" />
                    </span>
                  </span>
                  <span v-else class="http-proxy-trigger-placeholder">全部直连</span>
                  <ChevronDown :size="14" :stroke-width="2.4" class="http-proxy-trigger-caret" :class="{ 'is-open': open }" />
                </button>
              </template>
              <template #option="{ option, isActive }">
                <span class="http-proxy-option-icon">
                  <component :is="option.icon" :size="16" :stroke-width="2.3" />
                </span>
                <span class="http-proxy-option-main">
                  <span class="http-proxy-option-label">{{ option.label }}</span>
                  <span class="http-proxy-option-desc">{{ option.description }}</span>
                </span>
                <Check v-if="isActive" :size="14" :stroke-width="2.7" class="http-proxy-option-check" />
              </template>
            </AppDropdown>
          </SettingsFieldCard>

          <div class="mini-grid three">
            <SettingsFieldCard label="并发下载">
              <SettingsNumberStepper v-model="config.http_downloader.max_concurrent_downloads" :min="1" :max="16" />
            </SettingsFieldCard>
            <SettingsFieldCard label="分片数">
              <SettingsNumberStepper v-model="config.http_downloader.split" :min="1" :max="32" />
            </SettingsFieldCard>
            <SettingsFieldCard label="单站连接">
              <SettingsNumberStepper v-model="config.http_downloader.max_connection_per_server" :min="1" :max="32" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid three">
            <SettingsFieldCard label="最小分片">
              <input v-model="config.http_downloader.min_split_size" class="field-input" type="text" placeholder="1M">
            </SettingsFieldCard>
            <SettingsFieldCard label="重试次数">
              <SettingsNumberStepper v-model="config.http_downloader.retry_count" :min="1" :max="50" />
            </SettingsFieldCard>
            <SettingsFieldCard label="重试等待秒">
              <SettingsNumberStepper v-model="config.http_downloader.retry_wait_seconds" :min="0" :max="300" />
            </SettingsFieldCard>
          </div>

          <div class="mini-grid three">
            <SettingsFieldCard label="连接超时秒">
              <SettingsNumberStepper v-model="config.http_downloader.connect_timeout_seconds" :min="1" :max="120" />
            </SettingsFieldCard>
            <SettingsFieldCard label="传输超时秒">
              <SettingsNumberStepper v-model="config.http_downloader.timeout_seconds" :min="1" :max="600" />
            </SettingsFieldCard>
            <SettingsFieldCard label="冲突策略">
              <AppDropdown v-model="config.http_downloader.conflict_policy" :options="httpConflictPolicyOptions" class="settings-field-dd" />
            </SettingsFieldCard>
          </div>

          <SettingsToggleRow v-model="config.http_downloader.allow_private_network" title="允许内网 URL" subtitle="默认阻止 localhost、内网、link-local 和 metadata 地址，避免误把系统内部服务当下载源。" />
          <SettingsFieldCard label="Gofile API Token" hint="可选；未填写时会使用临时网页账号解析分享目录，遇到权限或限流问题再填写账号 token。">
            <AnimatedPasswordInput v-model="config.http_downloader.gofile_token" placeholder="可选账号 token，用于提升 Gofile 解析稳定性" autocomplete="off" />
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="Gofile 并发文件">
              <SettingsNumberStepper v-model="config.http_downloader.gofile_max_concurrent_downloads" :min="1" :max="16" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Gofile 分片数">
              <SettingsNumberStepper v-model="config.http_downloader.gofile_split" :min="1" :max="32" />
            </SettingsFieldCard>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">Google Drive OAuth</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.http_downloader.google_drive_oauth_enabled" title="启用 Drive API 下载" subtitle="开启后 Google Drive 分享优先走 OAuth Drive API 下载；失败时回退现有公开直链解析。" />
          <div class="google-drive-oauth-actions">
            <div class="google-drive-oauth-status" :class="{ 'is-ready': googleDriveOAuthConfigured, 'is-expired': googleDriveOAuthExpired }">
              <CheckCircle2 :size="15" :stroke-width="2.4" />
              <span>{{ googleDriveOAuthStatusText }}</span>
            </div>
            <button type="button" class="ghost-inline-btn" :disabled="googleDriveOAuthBusy" @click="startGoogleDriveOAuth">
              <LoaderCircle v-if="googleDriveOAuthBusy" :size="14" class="spin-icon" />
              <LogIn v-else :size="14" :stroke-width="2.4" />
              {{ googleDriveOAuthExpired ? '重新登录' : 'Google 登录' }}
            </button>
          </div>
          <div v-if="googleDriveAccountVisible" class="google-drive-account-card">
            <img v-if="googleDriveAccountAvatar" :src="googleDriveAccountAvatar" alt="" class="google-drive-account-avatar" referrerpolicy="no-referrer">
            <div v-else class="google-drive-account-avatar is-placeholder">{{ googleDriveAccountInitial }}</div>
            <div class="google-drive-account-main">
              <strong>{{ googleDriveAccountName }}</strong>
              <span>{{ googleDriveAccountEmail }}</span>
            </div>
            <small>{{ googleDriveAccountCachedText }}</small>
          </div>
          <div class="google-drive-oauth-advanced">
            <div class="google-drive-oauth-advanced-head">
              <div>
                <span>OAuth 应用</span>
                <small>{{ googleDriveOAuthClientModeLabel }}</small>
              </div>
              <AppDropdown v-model="googleDriveOAuthClientMode" :options="googleDriveOAuthClientModeOptions" class="settings-field-dd google-drive-oauth-mode-dd" />
            </div>
            <div v-if="googleDriveUseCustomClient" class="google-drive-oauth-custom-grid">
              <SettingsFieldCard label="Client ID" hint="Google Cloud OAuth 客户端 ID。">
                <input v-model="config.http_downloader.google_drive_client_id" class="field-input" type="text" placeholder="xxxx.apps.googleusercontent.com" autocomplete="off">
              </SettingsFieldCard>
              <SettingsFieldCard label="Client Secret" hint="Web 类型客户端需要；桌面/PKCE 客户端可留空。">
                <AnimatedPasswordInput
                  v-model="config.http_downloader.google_drive_client_secret"
                  :reveal-value="getRevealedGoogleDriveSecret('google_drive_client_secret')"
                  placeholder="可选"
                  autocomplete="off"
                  @visibility-change="visible => handleGoogleDriveSecretVisibility('google_drive_client_secret', visible)"
                />
              </SettingsFieldCard>
            </div>
          </div>
          <div v-if="googleDriveOAuthMessage" class="pikpak-message" :class="googleDriveOAuthMessage.startsWith('✓') ? 'is-success' : googleDriveOAuthMessage.startsWith('✗') ? 'is-error' : 'is-info'">{{ googleDriveOAuthMessage }}</div>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">PikPak 分享解析</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.http_downloader.pikpak_enabled" title="启用 PikPak 链接解析" subtitle="分享链接先解析为临时直链，再交给 aria2 下载；不处理验证码绕过。" />
          <SettingsToggleRow v-if="config.http_downloader.pikpak_enabled" v-model="config.http_downloader.pikpak_auto_save_share" title="自动转存分享文件" subtitle="开启后预览/开始下载 PikPak 分享时自动保存到转存目录。" />
        </div>
      </div>
    </div>

    <div v-if="config.http_downloader.pikpak_enabled" class="settings-grid">
      <div class="settings-card">
        <div class="pikpak-accounts-card">
          <div class="pikpak-accounts-head">
            <div>
              <div class="pikpak-status-title">PikPak 账号列表</div>
              <div class="pikpak-status-subtitle">所有账号都在这里维护。手机号账号按所属地区填写，必要时在号码前加国家码；多文件转存会按各账号剩余空间自动分配，单个文件不会拆分。</div>
            </div>
            <button type="button" class="ghost-inline-btn" @click="addPikPakAccount">
              <Plus :size="14" :stroke-width="2.4" />
              添加账号
            </button>
          </div>

          <div class="pikpak-account-list">
            <div v-for="(row, index) in editablePikPakAccountRows" :key="row.id" class="pikpak-account-row" :class="pikpakAccountStateClass(getPikPakAccountStatus(row.id))">
              <div class="pikpak-account-index">
                <input v-if="row.legacy" v-model="config.http_downloader.pikpak_default_enabled" type="checkbox">
                <input v-else v-model="row.account.enabled" type="checkbox">
                <span>{{ index + 1 }}</span>
              </div>
              <div class="pikpak-account-fields">
                <input v-if="row.legacy" :value="defaultPikPakAccountLabel" class="field-input" type="text" placeholder="备注名" @input="updateDefaultPikPakLabel($event.target.value)">
                <input v-else v-model="row.account.label" class="field-input" type="text" placeholder="备注名">
                <input v-if="row.legacy" v-model="config.http_downloader.pikpak_username" class="field-input" type="text" placeholder="邮箱或手机号（可带国家码）" @blur="normalizePikPakAccountUsername(row)">
                <input v-else v-model="row.account.username" class="field-input" type="text" placeholder="邮箱或手机号（可带国家码）" @blur="normalizePikPakAccountUsername(row)">
                <AnimatedPasswordInput v-if="row.legacy" v-model="config.http_downloader.pikpak_password" compact :reveal-value="getRevealedPikPakPassword(row.id)" placeholder="密码" autocomplete="new-password" @visibility-change="visible => handlePikPakPasswordVisibility(row, visible)" />
                <AnimatedPasswordInput v-else v-model="row.account.password" compact :reveal-value="getRevealedPikPakPassword(row.id)" placeholder="密码" autocomplete="new-password" @visibility-change="visible => handlePikPakPasswordVisibility(row, visible)" />
                <input v-if="row.legacy" v-model="config.http_downloader.pikpak_transfer_dir" class="field-input" type="text" placeholder="/KikoeruManager">
                <input v-else v-model="row.account.transfer_dir" class="field-input" type="text" placeholder="/KikoeruManager">
                <span v-if="getPikPakUsernameHint(row.legacy ? config.http_downloader.pikpak_username : row.account?.username)" class="pikpak-account-note">
                  {{ getPikPakUsernameHint(row.legacy ? config.http_downloader.pikpak_username : row.account?.username) }}
                </span>
              </div>
              <div class="pikpak-account-side">
                <button type="button" class="ghost-inline-btn compact" :disabled="isPikPakTesting(row.id)" @click="testPikPakAccount(row.id, row.account)">
                  <LoaderCircle v-if="isPikPakTesting(row.id)" :size="13" class="spin-icon" />
                  <CheckCircle2 v-else :size="13" :stroke-width="2.4" />
                  检测
                </button>
                <button type="button" class="icon-btn danger" @click="removePikPakAccountRow(row)">
                  <Trash2 :size="15" :stroke-width="2.4" />
                </button>
              </div>
              <div class="pikpak-account-status" :class="pikpakAccountStateClass(getPikPakAccountStatus(row.id))">
                <span>{{ pikpakAccountStatusLabel(row.id) }}</span>
                <small>{{ pikpakAccountStatusDetail(row.id) }}</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="pikpak-status-card">
          <div class="pikpak-status-head">
            <div>
              <div class="pikpak-status-title">PikPak 转存空间</div>
              <div class="pikpak-status-subtitle">{{ pikpakStatusText }}</div>
            </div>
            <div class="pikpak-status-actions">
              <StatefulButton
                class="ghost-inline-btn pikpak-stateful-btn"
                unstyled
                :show-default-icons="false"
                :success-hold="1400"
                @click="refreshPikPakStatus"
              >
                <template #prefix="{ state }">
                  <PikPakStateIcon :state="state" />
                </template>
                检测全部
              </StatefulButton>
              <button type="button" class="ghost-inline-btn danger" :disabled="pikpakBusy || !visiblePikPakAccountRows.length" @click="clearAllPikPakTransfers">
                <Trash2 :size="14" :stroke-width="2.4" />
                清空全部
              </button>
              <button type="button" class="ghost-inline-btn" :disabled="pikpakBusy" @click="openPikPakManager">
                <FolderOpen :size="14" :stroke-width="2.4" />
                管理转存
              </button>
            </div>
          </div>
          <div class="pikpak-quota-summary">
            <div>
              <span>总容量</span>
              <strong>{{ formatBytes(pikpakTotalQuota.limit) }}</strong>
            </div>
            <div>
              <span>已使用</span>
              <strong>{{ formatBytes(pikpakTotalQuota.usage) }}</strong>
            </div>
            <div>
              <span>剩余</span>
              <strong>{{ formatBytes(pikpakTotalQuota.remaining) }}</strong>
            </div>
            <div>
              <span>可用账号</span>
              <strong>{{ pikpakHealthyAccountCount }} / {{ pikpakAccountStatuses.length || visiblePikPakAccountRows.length }}</strong>
            </div>
          </div>
          <div v-if="pikpakTotalQuota.usage > 0" class="pikpak-quota-bar">
            <div class="pikpak-quota-fill" :style="{ width: `${pikpakTotalUsedPercent}%` }"></div>
          </div>
          <div v-if="pikpakAccountUsageRows.length" class="pikpak-account-usage-list">
            <div v-for="row in pikpakAccountUsageRows" :key="row.id" class="pikpak-account-usage-row" :class="row.success ? 'is-ok' : 'is-error'">
              <div class="pikpak-usage-main">
                <strong>{{ row.label }}</strong>
                <span>{{ row.success ? `${formatBytes(row.usage)} / ${formatBytes(row.limit)}，剩余 ${formatBytes(row.remaining)}` : row.message }}</span>
              </div>
              <div class="pikpak-usage-meter">
                <i :style="{ width: `${row.percent}%` }"></i>
              </div>
              <small>{{ row.success ? `${row.percent}%` : '异常' }}</small>
            </div>
          </div>
          <div v-if="pikpakMessage" class="pikpak-message" :class="pikpakMessage.startsWith('✓') ? 'is-success' : pikpakMessage.startsWith('✗') ? 'is-error' : 'is-info'">{{ pikpakMessage }}</div>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <Transition name="fade-up">
        <div v-if="pikpakManagerVisible" class="pikpak-manager-overlay" @click.self="closePikPakManager">
          <div class="pikpak-manager-modal">
            <div class="pikpak-manager-head">
              <div>
                <div class="pikpak-manager-title">PikPak 转存目录</div>
                <div class="pikpak-manager-subtitle">{{ selectedPikPakAccountLabel }} · {{ pikpakListRoot ? '根目录' : selectedPikPakTransferDir }}</div>
              </div>
              <button type="button" class="pikpak-icon-btn" @click="closePikPakManager">×</button>
            </div>

            <div v-if="pikpakAccountStatuses.length > 1" class="pikpak-account-tabs">
              <button
                v-for="status in pikpakAccountStatuses"
                :key="status.account_id || status.account?.id"
                type="button"
                class="pikpak-account-tab"
                :class="{
                  active: selectedPikPakAccountId === accountStatusId(status),
                  'is-ok': status.success,
                  'is-error': !status.success
                }"
                :disabled="pikpakBusy"
                @click="selectPikPakManagerAccount(status.account_id || status.account?.id)"
              >
                <span class="pikpak-account-tab-title">
                  <CheckCircle2 v-if="selectedPikPakAccountId === accountStatusId(status)" :size="13" :stroke-width="2.5" />
                  {{ status.account_label || status.account?.label || status.account_id }}
                </span>
                <small>{{ status.success ? formatBytes(status.quota?.remaining_bytes) : '异常' }}</small>
              </button>
            </div>

            <div class="pikpak-manager-quota">
              <div>
                <span>已用</span>
                <strong>{{ formatBytes(pikpakQuota.usage_bytes) }} / {{ formatBytes(pikpakQuota.limit_bytes) }}</strong>
              </div>
              <div>
                <span>剩余</span>
                <strong>{{ formatBytes(pikpakQuota.remaining_bytes) }}</strong>
              </div>
              <div>
                <span>回收站</span>
                <strong>{{ formatBytes(pikpakQuota.usage_in_trash_bytes) }}</strong>
              </div>
            </div>

            <div class="pikpak-manager-actions">
              <button type="button" class="ghost-inline-btn" :class="{ active: !pikpakListRoot }" :disabled="pikpakBusy" @click="switchPikPakListRoot(false)">转存目录</button>
              <button type="button" class="ghost-inline-btn" :class="{ active: pikpakListRoot }" :disabled="pikpakBusy" @click="switchPikPakListRoot(true)">根目录</button>
              <button type="button" class="ghost-inline-btn" :disabled="pikpakBusy" @click="refreshPikPakManager(true)">刷新</button>
              <button type="button" class="ghost-inline-btn danger" :disabled="pikpakBusy || !selectedPikPakFileIds.length" @click="deleteSelectedPikPak(false)">移入回收站</button>
              <button type="button" class="ghost-inline-btn danger" :disabled="pikpakBusy || !selectedPikPakFileIds.length" @click="deleteSelectedPikPak(true)">永久删除</button>
            </div>

            <div v-if="pikpakMessage" class="pikpak-message" :class="pikpakMessage.startsWith('✓') ? 'is-success' : pikpakMessage.startsWith('✗') ? 'is-error' : 'is-info'">{{ pikpakMessage }}</div>
            <div class="pikpak-file-tree">
              <div v-if="pikpakTreeRows.length" class="pikpak-tree-scroll">
                <div
                  v-for="row in pikpakTreeRows"
                  :key="row.key"
                  class="pikpak-tree-row"
                  :class="{
                    'is-folder': row.isFolder,
                    'is-file': !row.isFolder && !row.placeholder,
                    'is-selected': row.selected,
                    'is-placeholder': row.placeholder
                  }"
                  :style="{ paddingLeft: `${row.depth * 18 + 10}px` }"
                  @click="handlePikPakTreeRowClick(row)"
                >
                  <div class="pikpak-tree-main">
                    <button
                      v-if="row.isFolder"
                      type="button"
                      class="pikpak-tree-expander"
                      :disabled="row.loading"
                      @click.stop="togglePikPakFolder(row.item)"
                    >
                      <LoaderCircle v-if="row.loading" :size="14" class="spin-icon" />
                      <component v-else :is="row.expanded ? ChevronDown : ChevronRight" :size="16" :stroke-width="2.4" />
                    </button>
                    <span v-else class="pikpak-tree-expander-spacer"></span>

                    <input
                      v-if="!row.placeholder"
                      type="checkbox"
                      class="pikpak-tree-checkbox"
                      :checked="row.selected"
                      @click.stop
                      @change="togglePikPakFile(row.id)"
                    >
                    <span v-else class="pikpak-tree-checkbox-spacer"></span>

                    <component :is="getPikPakTreeIcon(row)" class="pikpak-tree-icon" :class="getPikPakTreeIconClass(row)" :size="17" :stroke-width="2.35" />
                    <span class="pikpak-tree-text">
                      <span class="pikpak-tree-name">{{ row.name }}</span>
                      <span class="pikpak-tree-meta">{{ row.meta }}</span>
                    </span>
                  </div>
                  <span v-if="row.sizeText" class="pikpak-tree-size">{{ row.sizeText }}</span>
                </div>
              </div>
              <div v-else class="pikpak-empty">
                <LoaderCircle v-if="pikpakBusy" :size="16" class="spin-icon" />
                <span>{{ pikpakBusy ? '正在读取...' : '转存目录为空' }}</span>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, CheckCircle2, ChevronDown, ChevronRight, File, FileArchive, FileAudio, FileVideo, Folder, FolderOpen, Link, LoaderCircle, LogIn, Plus, Trash2 } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import StatefulButton from '../ui/stateful-button.vue'
import PikPakStateIcon from './PikPakStateIcon.vue'
import AppDropdown from '../common/AppDropdown.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import { HTTP_DOWNLOAD_PLATFORM_META } from '../common/httpDownloadPlatformMeta'
import { API_BASE, configApi, httpDownloadApi } from '../../api'
import { showSystemConfirm } from '../../composables/useSystemPrompt'

const props = defineProps({
  config: { type: Object, required: true }
})

const httpConflictPolicyOptions = [
  { value: 'resume', label: '断点续传' },
  { value: 'rename', label: '自动改名' },
  { value: 'skip', label: '已存在跳过' }
]
const httpEngineOptions = [
  { value: 'aria2', label: 'aria2' }
]
const httpProxyPlatformOptions = [
  { value: 'http', label: 'HTTP 直链', description: '普通 HTTP/HTTPS 文件直链与未知来源。' },
  { value: 'gofile', label: 'Gofile', description: 'Gofile 分享解析和文件下载。' },
  { value: 'transferit', label: 'Transfer.it', description: 'Transfer.it 分享解析和专用下载。' },
  { value: 'onedrive', label: 'OneDrive', description: 'OneDrive 分享直链解析。' },
  { value: 'google_drive', label: 'Google Drive', description: 'Drive OAuth、API、确认页和文件下载。' },
  { value: 'pikpak', label: 'PikPak', description: 'PikPak 登录、转存、解析和文件下载。' }
].map(option => ({
  ...option,
  icon: HTTP_DOWNLOAD_PLATFORM_META[option.value]?.icon || Link
}))
const googleDriveOAuthClientModeOptions = [
  { value: 'builtin', label: '内置应用' },
  { value: 'custom', label: '自定义' }
]

const pikpakBusy = ref(false)
const pikpakManagerVisible = ref(false)
const pikpakMessage = ref('')
const pikpakStatus = ref(null)
const pikpakFiles = ref([])
const selectedPikPakFileIds = ref([])
const pikpakListRoot = ref(true)
const selectedPikPakAccountId = ref('')
const pikpakTestingIds = ref([])
const pikpakTreeVersion = ref(0)
const pikpakTreeExpandedIds = ref(new Set())
const pikpakTreeLoadingIds = ref(new Set())
const pikpakTreeErrors = ref({})
const pikpakTreeCache = ref({})
const pikpakRevealedPasswords = ref({})
const pikpakRevealLoadingIds = ref(new Set())
const googleDriveRevealedSecrets = ref({})
const googleDriveSecretLoadingKeys = ref(new Set())
const googleDriveOAuthBusy = ref(false)
const googleDriveOAuthMessage = ref('')
const googleDriveOAuthPopup = ref(null)
const googleDriveOAuthPopupTimer = ref(null)
const googleDriveExpiredNotified = ref(false)

const config = computed(() => props.config)
const selectedHttpProxyPlatformOptions = computed(() => {
  const selected = Array.isArray(props.config.http_downloader.proxy_platforms)
    ? props.config.http_downloader.proxy_platforms
    : []
  const selectedSet = new Set(selected)
  return httpProxyPlatformOptions.filter(option => selectedSet.has(option.value))
})
const googleDriveOAuthClientMode = computed({
  get: () => props.config.http_downloader.google_drive_oauth_client_mode || 'builtin',
  set: (value) => {
    props.config.http_downloader.google_drive_oauth_client_mode = value === 'custom' ? 'custom' : 'builtin'
  }
})
const googleDriveUseCustomClient = computed(() => googleDriveOAuthClientMode.value === 'custom')
const googleDriveOAuthClientModeLabel = computed(() => (
  googleDriveUseCustomClient.value ? '使用自己创建的 Google OAuth Client' : '使用项目维护的 OAuth 应用'
))
const pikpakAccounts = computed(() => {
  if (!Array.isArray(props.config.http_downloader.pikpak_accounts)) {
    props.config.http_downloader.pikpak_accounts = []
  }
  return props.config.http_downloader.pikpak_accounts
})
const defaultPikPakAccountLabel = computed(() => props.config.http_downloader.pikpak_label || props.config.http_downloader.pikpak_username || '')
const editablePikPakAccountRows = computed(() => [
  {
    id: 'default',
    legacy: true,
    account: null,
    accountIndex: -1
  },
  ...pikpakAccounts.value.map((account, index) => ({
    id: String(account.id || `account-${index + 1}`),
    legacy: false,
    account,
    accountIndex: index
  }))
])
const pikpakAccountStatuses = computed(() => Array.isArray(pikpakStatus.value?.accounts) ? pikpakStatus.value.accounts : (pikpakStatus.value ? [pikpakStatus.value] : []))
const selectedPikPakStatus = computed(() => {
  const wanted = String(selectedPikPakAccountId.value || '')
  return pikpakAccountStatuses.value.find(item => accountStatusId(item) === wanted) || pikpakAccountStatuses.value[0] || pikpakStatus.value || {}
})
const pikpakQuota = computed(() => selectedPikPakStatus.value?.quota || {})
const pikpakQuotaPercent = computed(() => {
  const used = Number(pikpakQuota.value.usage_bytes || 0)
  const limit = Number(pikpakQuota.value.limit_bytes || 0)
  if (!limit) return 0
  return Math.min(100, Math.max(0, Math.round((used / limit) * 100)))
})
const visiblePikPakAccountRows = computed(() => {
  const rows = []
  const legacyConfigured = Boolean(
    props.config.http_downloader.pikpak_username
      || props.config.http_downloader.pikpak_password
      || props.config.http_downloader.pikpak_encoded_token
  )
  if (legacyConfigured) {
    rows.push({
      id: 'default',
      label: defaultPikPakAccountLabel.value || props.config.http_downloader.pikpak_username || 'PikPak 账号',
      enabled: props.config.http_downloader.pikpak_default_enabled !== false,
      legacy: true
    })
  }
  pikpakAccounts.value.forEach((account, index) => {
    rows.push({
      id: String(account.id || `account-${index + 1}`),
      label: account.label || account.username || `账号 ${index + 2}`,
      enabled: account.enabled !== false,
      legacy: false
    })
  })
  return rows
})
const pikpakTotalQuota = computed(() => {
  const rows = pikpakAccountStatuses.value.filter(item => item?.success)
  return rows.reduce((acc, item) => {
    const quota = item.quota || {}
    acc.limit += Number(quota.limit_bytes || 0)
    acc.usage += Number(quota.usage_bytes || 0)
    acc.remaining += Number(quota.remaining_bytes || 0)
    acc.trash += Number(quota.usage_in_trash_bytes || 0)
    return acc
  }, { limit: 0, usage: 0, remaining: 0, trash: 0 })
})
const pikpakTotalUsedPercent = computed(() => {
  if (!pikpakTotalQuota.value.limit) return 0
  return Math.min(100, Math.max(0, Math.round((pikpakTotalQuota.value.usage / pikpakTotalQuota.value.limit) * 100)))
})
const pikpakHealthyAccountCount = computed(() => pikpakAccountStatuses.value.filter(item => item?.success).length)
const pikpakAccountUsageRows = computed(() => pikpakAccountStatuses.value.map((item) => {
  const quota = item.quota || {}
  const limit = Number(quota.limit_bytes || 0)
  const usage = Number(quota.usage_bytes || 0)
  const remaining = Number(quota.remaining_bytes || 0)
  return {
    id: item.account_id || item.account?.id || item.account_label || item.account?.label || '',
    label: item.account_label || item.account?.label || item.account?.username || 'PikPak 账号',
    success: Boolean(item.success),
    limit,
    usage,
    remaining,
    percent: limit ? Math.min(100, Math.max(0, Math.round((usage / limit) * 100))) : 0,
    message: item.message || '账号异常'
  }
}))
const pikpakStatusText = computed(() => {
  if (!props.config.http_downloader.pikpak_enabled) return '未启用'
  if (!pikpakStatus.value) return '点击“检测全部”读取登录状态、总容量、已用空间和剩余空间。'
  const count = pikpakAccountStatuses.value.length || visiblePikPakAccountRows.value.length
  const suffix = pikpakStatus.value?.cache_updated_at ? `，上次同步 ${formatDateTime(pikpakStatus.value.cache_updated_at)}` : ''
  return `${pikpakHealthyAccountCount.value}/${count || 0} 个账号可用，总容量 ${formatBytes(pikpakTotalQuota.value.limit)}，已用 ${pikpakTotalUsedPercent.value}%${suffix}`
})
const googleDriveOAuthConfigured = computed(() => Boolean(
  !props.config.http_downloader.google_drive_oauth_expired && (
    props.config.http_downloader.google_drive_refresh_token
    || googleDriveRevealedSecrets.value.google_drive_refresh_token
  )
))
const googleDriveOAuthExpired = computed(() => Boolean(props.config.http_downloader.google_drive_oauth_expired))
const googleDriveOAuthStatusText = computed(() => {
  if (googleDriveOAuthBusy.value) return '正在等待 Google 授权'
  if (googleDriveOAuthExpired.value) return 'Google Drive 授权已过期'
  if (googleDriveOAuthConfigured.value) return '已授权 Drive 只读访问'
  return '未授权 Drive 只读访问'
})
const googleDriveAccountName = computed(() => String(props.config.http_downloader.google_drive_account_name || '').trim())
const googleDriveAccountEmail = computed(() => String(props.config.http_downloader.google_drive_account_email || '').trim())
const googleDriveAccountAvatar = computed(() => String(props.config.http_downloader.google_drive_account_avatar_url || '').trim())
const googleDriveAccountVisible = computed(() => Boolean(
  googleDriveAccountName.value || googleDriveAccountEmail.value
))
const googleDriveAccountInitial = computed(() => {
  const text = googleDriveAccountName.value || googleDriveAccountEmail.value || 'G'
  return String(text).trim().slice(0, 1).toUpperCase() || 'G'
})
const googleDriveAccountCachedText = computed(() => {
  const cachedAt = Number(props.config.http_downloader.google_drive_account_cached_at || 0)
  const timeText = cachedAt ? formatDateTime(cachedAt) : ''
  if (googleDriveOAuthExpired.value) return timeText ? `授权已过期 · ${timeText}` : '授权已过期'
  return timeText ? `缓存于 ${timeText}` : '本地缓存'
})
const googleDriveAllowedMessageOrigins = computed(() => {
  const origins = new Set()
  if (typeof window !== 'undefined') {
    origins.add(window.location.origin)
    try {
      origins.add(new URL(API_BASE, window.location.origin).origin)
    } catch (_) {
    }
  }
  return origins
})
const selectedPikPakAccountLabel = computed(() => selectedPikPakStatus.value?.account_label || selectedPikPakStatus.value?.account?.label || '默认账号')
const selectedPikPakTransferDir = computed(() => selectedPikPakStatus.value?.transfer_dir || selectedPikPakStatus.value?.account?.transfer_dir || props.config.http_downloader.pikpak_transfer_dir || '/KikoeruManager')
const pikpakTreeRootKey = computed(() => buildPikPakCacheKey({ parentId: '' }))
const pikpakTreeRootRows = computed(() => {
  pikpakTreeVersion.value
  return pikpakTreeCache.value[pikpakTreeRootKey.value]?.files || []
})
const pikpakTreeRows = computed(() => {
  pikpakTreeVersion.value
  const rows = []
  const walk = (items, depth) => {
    for (const item of items || []) {
      const id = String(item.id || '').trim()
      if (!id) continue
      const isFolder = Boolean(item.is_folder)
      const expanded = isFolder && pikpakTreeExpandedIds.value.has(id)
      const loading = isFolder && pikpakTreeLoadingIds.value.has(id)
      const cacheKey = buildPikPakCacheKey({ parentId: id })
      const cached = pikpakTreeCache.value[cacheKey]
      const error = pikpakTreeErrors.value[id] || ''
      rows.push({
        key: id,
        id,
        item,
        depth,
        isFolder,
        expanded,
        loading,
        selected: selectedPikPakFileIds.value.includes(id),
        name: item.name || id,
        meta: pikpakFileMeta(item, { cached, error, loading }),
        sizeText: isFolder ? '' : formatBytes(item.size_bytes)
      })
      if (isFolder && expanded) {
        if (cached?.files?.length) {
          walk(cached.files, depth + 1)
        } else if (loading) {
          rows.push(pikpakPlaceholderRow(id, depth + 1, '正在读取目录...'))
        } else if (error) {
          rows.push(pikpakPlaceholderRow(id, depth + 1, error))
        } else if (cached) {
          rows.push(pikpakPlaceholderRow(id, depth + 1, '空目录'))
        }
      }
    }
  }
  walk(pikpakTreeRootRows.value, 0)
  return rows
})

function newPikPakAccount() {
  const id = `account-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
  return {
    id,
    label: '',
    enabled: true,
    username: '',
    password: '',
    encoded_token: '',
    device_id: '',
    transfer_dir: props.config.http_downloader.pikpak_transfer_dir || '/KikoeruManager'
  }
}

function normalizePikPakUsername(value) {
  return String(value || '').trim()
}

function normalizePikPakAccountUsername(row) {
  if (!row) return
  if (row.legacy) {
    props.config.http_downloader.pikpak_username = normalizePikPakUsername(props.config.http_downloader.pikpak_username)
    return
  }
  if (row.account) {
    row.account.username = normalizePikPakUsername(row.account.username)
  }
}

function getPikPakUsernameHint(value) {
  const text = normalizePikPakUsername(value)
  if (!text || text.includes('@')) return ''
  const raw = text.startsWith('+') ? text.slice(1) : text
  if (!/^\d{6,18}$/.test(raw)) return ''
  if (text.startsWith('+')) {
    return '手机号账号已经带国家码。若检测仍失败，可以再试试账号原始格式。'
  }
  if (raw.length === 11 && raw.startsWith('1')) {
    return '如果这是中国手机号，可以试试在号码前补 +86。'
  }
  return '如果这是手机号，可按所属地区补国家码。'
}

function addPikPakAccount() {
  props.config.http_downloader.pikpak_accounts = [...pikpakAccounts.value, newPikPakAccount()]
}

function removePikPakAccount(index) {
  props.config.http_downloader.pikpak_accounts = pikpakAccounts.value.filter((_item, itemIndex) => itemIndex !== index)
}

function clearDefaultPikPakAccount() {
  props.config.http_downloader.pikpak_default_enabled = true
  props.config.http_downloader.pikpak_label = ''
  props.config.http_downloader.pikpak_username = ''
  props.config.http_downloader.pikpak_password = ''
  props.config.http_downloader.pikpak_encoded_token = ''
  props.config.http_downloader.pikpak_device_id = ''
  props.config.http_downloader.pikpak_transfer_dir = '/KikoeruManager'
}

function removePikPakAccountRow(row) {
  if (row?.legacy) {
    clearDefaultPikPakAccount()
    return
  }
  removePikPakAccount(row.accountIndex)
}

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

function formatDateTime(value) {
  const numberValue = Number(value || 0)
  const date = new Date(numberValue > 0 && numberValue < 1000000000000 ? numberValue * 1000 : value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function normalizePikPakAccountId(accountId = '') {
  return String(accountId || selectedPikPakAccountId.value || selectedPikPakStatus.value?.account_id || selectedPikPakStatus.value?.account?.id || '').trim()
}

function buildPikPakCacheKey({ accountId = '', root = null, parentId = '' } = {}) {
  const account = normalizePikPakAccountId(accountId) || 'default'
  const scope = (root ?? pikpakListRoot.value) ? 'root' : 'transfer'
  return `${account}::${scope}::${String(parentId || 'root')}`
}

function bumpPikPakTreeVersion() {
  pikpakTreeVersion.value += 1
}

function setPikPakTreeCache(key, payload) {
  pikpakTreeCache.value = {
    ...pikpakTreeCache.value,
    [key]: {
      files: Array.isArray(payload.files) ? payload.files : [],
      folder_id: payload.folder_id || '',
      loaded_at: Date.now()
    }
  }
  bumpPikPakTreeVersion()
}

function clearPikPakTreeCache({ accountId = '', root = null } = {}) {
  const account = normalizePikPakAccountId(accountId) || 'default'
  const scope = (root ?? pikpakListRoot.value) ? 'root' : 'transfer'
  const prefix = `${account}::${scope}::`
  pikpakTreeCache.value = Object.fromEntries(Object.entries(pikpakTreeCache.value).filter(([key]) => !key.startsWith(prefix)))
  resetPikPakTreeViewState()
}

function resetPikPakTreeViewState() {
  pikpakTreeErrors.value = {}
  pikpakTreeExpandedIds.value = new Set()
  pikpakTreeLoadingIds.value = new Set()
  bumpPikPakTreeVersion()
}

function pikpakPlaceholderRow(parentId, depth, message) {
  return {
    key: `${parentId || 'root'}::placeholder::${message}`,
    id: '',
    depth,
    isFolder: false,
    placeholder: true,
    selected: false,
    name: message,
    meta: '',
    sizeText: ''
  }
}

function pikpakFileMeta(item, { cached = null, error = '', loading = false } = {}) {
  if (item?.is_folder) {
    if (loading) return '文件夹 · 正在读取'
    if (error) return `文件夹 · ${error}`
    if (cached) return `文件夹 · ${cached.files?.length || 0} 项`
    return '文件夹 · 点击展开'
  }
  return `${formatBytes(item?.size_bytes)} · ${item?.phase || 'complete'}`
}

function getPikPakTreeIcon(row) {
  if (row.placeholder) return File
  if (row.isFolder) return row.expanded ? FolderOpen : Folder
  const name = String(row.name || '').toLowerCase()
  if (/\.(zip|rar|7z|tar|gz|bz2|xz)$/i.test(name)) return FileArchive
  if (/\.(mp3|flac|wav|m4a|aac|ogg|opus)$/i.test(name)) return FileAudio
  if (/\.(mp4|mkv|avi|mov|webm)$/i.test(name)) return FileVideo
  return File
}

function getPikPakTreeIconClass(row) {
  if (row.placeholder) return 'is-muted'
  if (row.isFolder) return 'is-folder'
  const name = String(row.name || '').toLowerCase()
  if (/\.(mp3|flac|wav|m4a|aac|ogg|opus)$/i.test(name)) return 'is-audio'
  if (/\.(mp4|mkv|avi|mov|webm)$/i.test(name)) return 'is-video'
  if (/\.(zip|rar|7z|tar|gz|bz2|xz)$/i.test(name)) return 'is-archive'
  return 'is-file'
}

async function loadPikPakTreeNode({ parentId = '', force = false } = {}) {
  const id = String(parentId || '').trim()
  const key = buildPikPakCacheKey({ parentId: id })
  if (!force && pikpakTreeCache.value[key]) {
    return pikpakTreeCache.value[key]
  }
  if (id) {
    pikpakTreeLoadingIds.value = new Set([...pikpakTreeLoadingIds.value, id])
  }
  if (id && pikpakTreeErrors.value[id]) {
    const nextErrors = { ...pikpakTreeErrors.value }
    delete nextErrors[id]
    pikpakTreeErrors.value = nextErrors
  }
  bumpPikPakTreeVersion()
  try {
    const listing = await httpDownloadApi.pikpakFiles({
      limit: 300,
      root: pikpakListRoot.value,
      parentId: id || undefined,
      accountId: selectedPikPakAccountId.value
    })
    setPikPakTreeCache(key, listing)
    if (!id) {
      pikpakFiles.value = Array.isArray(listing.files) ? listing.files : []
    }
    return listing
  } catch (error) {
    if (id) {
      pikpakTreeErrors.value = { ...pikpakTreeErrors.value, [id]: getPikPakErrorDetail(error, '目录读取失败') }
    }
    throw error
  } finally {
    if (id) {
      pikpakTreeLoadingIds.value = new Set([...pikpakTreeLoadingIds.value].filter(item => item !== id))
      bumpPikPakTreeVersion()
    }
  }
}

function getPikPakErrorDetail(error, fallback = 'PikPak 请求失败') {
  const status = Number(error?.response?.status || 0)
  const url = String(error?.config?.url || '')
  if (status === 404 && url.includes('/http-download/pikpak/test-account')) {
    return '当前运行中的后端还没加载 PikPak 账号检测接口，请重启后端后再检测；这不是 PikPak 账号不存在。'
  }
  if (status === 404 && url.includes('/http-download/pikpak/')) {
    return '当前运行中的后端还没加载 PikPak 管理接口，请重启后端后再试。'
  }
  return error?.response?.data?.detail || error?.message || fallback
}

function setPikPakError(error, fallback = 'PikPak 请求失败') {
  const detail = getPikPakErrorDetail(error, fallback)
  pikpakMessage.value = `✗ ${detail}`
  ElMessage.error(detail)
}

function accountStatusId(status) {
  return String(status?.account_id || status?.account?.id || '')
}

function ensureSelectedPikPakAccount(statusPayload = pikpakStatus.value) {
  const rows = Array.isArray(statusPayload?.accounts) ? statusPayload.accounts : (statusPayload ? [statusPayload] : [])
  const current = String(selectedPikPakAccountId.value || '')
  if (current && rows.some(item => accountStatusId(item) === current)) return
  selectedPikPakAccountId.value = rows.map(item => accountStatusId(item)).find(Boolean) || ''
}

function getPikPakAccountStatus(accountId) {
  const wanted = String(accountId || '')
  return pikpakAccountStatuses.value.find(item => accountStatusId(item) === wanted) || null
}

function pikpakAccountStateClass(status) {
  if (!status) return 'is-unknown'
  return status.success ? 'is-ok' : 'is-error'
}

function pikpakAccountStatusLabel(accountId) {
  if (isPikPakTesting(accountId)) return '检测中'
  const status = getPikPakAccountStatus(accountId)
  if (!status) return '未检测'
  return status.success ? '可用' : '异常'
}

function pikpakAccountStatusDetail(accountId) {
  const status = getPikPakAccountStatus(accountId)
  if (!status) return '点击检测登录和容量'
  if (!status.success) return status.message || '账号不可用'
  const quota = status.quota || {}
  return `剩余 ${formatBytes(quota.remaining_bytes)} / 总 ${formatBytes(quota.limit_bytes)}`
}

function isPikPakTesting(accountId) {
  return pikpakTestingIds.value.includes(String(accountId || ''))
}

function getRevealedPikPakPassword(accountId) {
  return pikpakRevealedPasswords.value[String(accountId || '')] || ''
}

function getRevealedGoogleDriveSecret(key) {
  return googleDriveRevealedSecrets.value[String(key || '')] || ''
}

async function handleGoogleDriveSecretVisibility(key, visible) {
  const secretKey = String(key || '')
  if (!visible || !secretKey || getRevealedGoogleDriveSecret(secretKey) || googleDriveSecretLoadingKeys.value.has(secretKey)) return
  const currentValue = props.config.http_downloader?.[secretKey]
  if (currentValue !== '********') return
  const nextLoading = new Set(googleDriveSecretLoadingKeys.value)
  nextLoading.add(secretKey)
  googleDriveSecretLoadingKeys.value = nextLoading
  try {
    const result = await configApi.revealHttpSecret({ key: secretKey })
    googleDriveRevealedSecrets.value = {
      ...googleDriveRevealedSecrets.value,
      [secretKey]: result?.value || ''
    }
    if (!result?.value) {
      ElMessage.warning('配置文件里没有可显示的 Google Drive OAuth 值')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '读取 Google Drive OAuth 配置失败')
  } finally {
    const doneLoading = new Set(googleDriveSecretLoadingKeys.value)
    doneLoading.delete(secretKey)
    googleDriveSecretLoadingKeys.value = doneLoading
  }
}

function googleDriveClientSecretForOAuth() {
  const configuredClientSecret = String(props.config.http_downloader.google_drive_client_secret || '').trim()
  if (configuredClientSecret === '********') {
    return String(getRevealedGoogleDriveSecret('google_drive_client_secret') || configuredClientSecret).trim()
  }
  return configuredClientSecret
}

function handleGoogleDriveOAuthMessage(event) {
  if (googleDriveOAuthPopup.value && event?.source !== googleDriveOAuthPopup.value) return
  if (event?.origin && !googleDriveAllowedMessageOrigins.value.has(event.origin)) return
  const data = event?.data || {}
  if (data.type !== 'kikoerumanager:google-drive-oauth') return
  const payload = data.payload || {}
  if (googleDriveOAuthPopupTimer.value) {
    window.clearInterval(googleDriveOAuthPopupTimer.value)
    googleDriveOAuthPopupTimer.value = null
  }
  googleDriveOAuthBusy.value = false
  googleDriveOAuthPopup.value = null
  if (!payload.success) {
    const detail = payload.message || 'Google Drive OAuth 授权失败'
    googleDriveOAuthMessage.value = `✗ ${detail}`
    ElMessage.error(detail)
    return
  }
  const refreshToken = String(payload.refresh_token || '').trim()
  if (!refreshToken) {
    googleDriveOAuthMessage.value = '✗ Google OAuth 未返回 Refresh Token'
    ElMessage.error('Google OAuth 未返回 Refresh Token')
    return
  }
  props.config.http_downloader.google_drive_oauth_enabled = true
  props.config.http_downloader.google_drive_oauth_expired = false
  props.config.http_downloader.google_drive_refresh_token = refreshToken
  const account = payload.account || {}
  props.config.http_downloader.google_drive_account_name = String(account.name || '').trim()
  props.config.http_downloader.google_drive_account_email = String(account.email || '').trim()
  props.config.http_downloader.google_drive_account_avatar_url = String(account.avatar_url || '').trim()
  props.config.http_downloader.google_drive_account_permission_id = String(account.permission_id || '').trim()
  props.config.http_downloader.google_drive_account_cached_at = Number(account.cached_at || Date.now() / 1000)
  googleDriveRevealedSecrets.value = {
    ...googleDriveRevealedSecrets.value,
    google_drive_refresh_token: refreshToken
  }
  const accountLabel = props.config.http_downloader.google_drive_account_email || props.config.http_downloader.google_drive_account_name
  googleDriveOAuthMessage.value = accountLabel
    ? `✓ Google Drive 已授权并保存：${accountLabel}`
    : '✓ Google Drive 已授权并保存'
  ElMessage.success(accountLabel ? `Google Drive 已授权并保存：${accountLabel}` : 'Google Drive 已授权并保存')
}

function notifyGoogleDriveExpired() {
  if (!googleDriveOAuthExpired.value || googleDriveExpiredNotified.value) return
  googleDriveExpiredNotified.value = true
  const label = googleDriveAccountEmail.value || googleDriveAccountName.value || '当前账号'
  const detail = `Google Drive 授权已过期，请重新登录：${label}`
  googleDriveOAuthMessage.value = `✗ ${detail}`
  ElMessage.warning(detail)
}

async function startGoogleDriveOAuth() {
  if (googleDriveOAuthBusy.value) return
  const clientMode = googleDriveOAuthClientMode.value
  const clientId = googleDriveUseCustomClient.value ? String(props.config.http_downloader.google_drive_client_id || '').trim() : ''
  const clientSecret = googleDriveUseCustomClient.value ? googleDriveClientSecretForOAuth() : ''
  if (googleDriveUseCustomClient.value && !clientId) {
    ElMessage.warning('自定义 OAuth Client 需要填写 Client ID')
    return
  }
  const popup = window.open('about:blank', 'kikoerumanager-google-drive-oauth', 'width=520,height=720,menubar=no,toolbar=no,location=yes,status=no')
  if (!popup) {
    ElMessage.warning('浏览器阻止了 Google 登录弹窗，请允许弹窗后重试')
    return
  }
  googleDriveOAuthPopup.value = popup
  googleDriveOAuthBusy.value = true
  googleDriveOAuthMessage.value = '正在打开 Google 登录弹窗...'
  try {
    popup.document.write('<!doctype html><title>Google Drive OAuth</title><body style="font-family: system-ui, sans-serif; padding: 24px;">正在打开 Google 登录...</body>')
  } catch (_) {
  }
  try {
    const result = await httpDownloadApi.googleDriveOAuthBegin({
      clientMode,
      clientId,
      clientSecret,
      openerOrigin: window.location.origin
    })
    if (!result?.auth_url) {
      throw new Error('后端未返回 Google 授权地址')
    }
    googleDriveOAuthMessage.value = '请在 Google 弹窗里完成登录授权'
    popup.location.href = result.auth_url
    if (googleDriveOAuthPopupTimer.value) {
      window.clearInterval(googleDriveOAuthPopupTimer.value)
    }
    googleDriveOAuthPopupTimer.value = window.setInterval(() => {
      if (!googleDriveOAuthPopup.value?.closed) return
      window.clearInterval(googleDriveOAuthPopupTimer.value)
      googleDriveOAuthPopupTimer.value = null
      googleDriveOAuthPopup.value = null
      if (googleDriveOAuthBusy.value) {
        googleDriveOAuthBusy.value = false
        googleDriveOAuthMessage.value = 'Google 登录弹窗已关闭'
      }
    }, 700)
  } catch (error) {
    try {
      popup.close()
    } catch (_) {
    }
    googleDriveOAuthPopup.value = null
    const detail = error?.response?.data?.detail || error?.message || 'Google Drive OAuth 授权失败'
    googleDriveOAuthMessage.value = `✗ ${detail}`
    ElMessage.error(detail)
    googleDriveOAuthBusy.value = false
  }
}

async function handlePikPakPasswordVisibility(row, visible) {
  if (!visible) return
  const id = String(row?.id || '')
  if (!id || getRevealedPikPakPassword(id) || pikpakRevealLoadingIds.value.has(id)) return
  const currentPassword = row?.legacy ? props.config.http_downloader.pikpak_password : row?.account?.password
  if (currentPassword !== '********') return
  const nextLoading = new Set(pikpakRevealLoadingIds.value)
  nextLoading.add(id)
  pikpakRevealLoadingIds.value = nextLoading
  try {
    const payload = row?.legacy
      ? { key: 'pikpak_password' }
      : { key: 'password', account_id: row?.account?.id || id }
    const result = await configApi.revealHttpSecret(payload)
    pikpakRevealedPasswords.value = {
      ...pikpakRevealedPasswords.value,
      [id]: result?.value || ''
    }
    if (!result?.value) {
      ElMessage.warning('配置文件里没有可显示的原始密码')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '读取已保存密码失败')
  } finally {
    const doneLoading = new Set(pikpakRevealLoadingIds.value)
    doneLoading.delete(id)
    pikpakRevealLoadingIds.value = doneLoading
  }
}

function updateDefaultPikPakLabel(value) {
  props.config.http_downloader.pikpak_label = value
}

function buildPikPakAccountPayload(accountId, account = null) {
  if (accountId === 'default') {
    return {
      id: 'default',
      label: defaultPikPakAccountLabel.value || props.config.http_downloader.pikpak_username || 'PikPak 账号',
      enabled: props.config.http_downloader.pikpak_default_enabled !== false,
      username: props.config.http_downloader.pikpak_username || '',
      password: props.config.http_downloader.pikpak_password || '',
      transfer_dir: props.config.http_downloader.pikpak_transfer_dir || '/KikoeruManager',
      legacy: true
    }
  }
  return {
    id: account?.id || accountId,
    label: account?.label || account?.username || '',
    enabled: account?.enabled !== false,
    username: account?.username || '',
    password: account?.password || '',
    transfer_dir: account?.transfer_dir || props.config.http_downloader.pikpak_transfer_dir || '/KikoeruManager'
  }
}

function mergePikPakAccountStatus(status) {
  const id = accountStatusId(status)
  if (!id) return
  const current = pikpakAccountStatuses.value
  const nextAccounts = current.some(item => accountStatusId(item) === id)
    ? current.map(item => (accountStatusId(item) === id ? status : item))
    : [...current, status]
  pikpakStatus.value = { ...(pikpakStatus.value || {}), accounts: nextAccounts, ready: nextAccounts.some(item => item.success), success: nextAccounts.some(item => item.success) }
}

async function testPikPakAccount(accountId, account = null) {
  const id = String(accountId || '')
  if (!id || isPikPakTesting(id)) return
  pikpakTestingIds.value = [...pikpakTestingIds.value, id]
  try {
    const result = await httpDownloadApi.pikpakTestAccount({
      accountId: id,
      account: buildPikPakAccountPayload(id, account)
    })
    mergePikPakAccountStatus(result)
    pikpakMessage.value = `✓ ${result.account_label || result.account?.label || 'PikPak 账号'} 可用，剩余 ${formatBytes(result.quota?.remaining_bytes)}`
    ElMessage.success(pikpakMessage.value.slice(2))
  } catch (error) {
    const detail = getPikPakErrorDetail(error, 'PikPak 账号检测失败')
    mergePikPakAccountStatus({
      success: false,
      ready: false,
      account_id: id,
      account_label: account?.label || account?.username || (id === 'default' ? (defaultPikPakAccountLabel.value || props.config.http_downloader.pikpak_username || 'PikPak 账号') : id),
      account: { id, label: account?.label || account?.username || id },
      quota: {},
      message: detail
    })
    pikpakMessage.value = `✗ ${detail}`
    ElMessage.error(detail)
  } finally {
    pikpakTestingIds.value = pikpakTestingIds.value.filter(item => item !== id)
  }
}

async function refreshPikPakStatus() {
  if (pikpakBusy.value) return
  pikpakBusy.value = true
  pikpakMessage.value = '正在检测 PikPak 账号...'
  try {
    const result = await httpDownloadApi.pikpakStatus({ includeFiles: false, limit: 1, forceRefresh: true })
    pikpakStatus.value = result
    ensureSelectedPikPakAccount(result)
    pikpakMessage.value = `✓ 已检测 ${pikpakHealthyAccountCount.value}/${pikpakAccountStatuses.value.length || 0} 个账号`
    return true
  } catch (error) {
    setPikPakError(error)
    return false
  } finally {
    pikpakBusy.value = false
  }
}

async function refreshPikPakManager(force = false) {
  if (pikpakBusy.value && !force) return
  pikpakBusy.value = true
  pikpakMessage.value = '正在读取 PikPak 容量和转存目录...'
  try {
    if (force || !pikpakStatus.value) {
      pikpakStatus.value = await httpDownloadApi.pikpakStatus({ includeFiles: false, limit: 200, forceRefresh: force })
    }
    const result = pikpakStatus.value || {}
    ensureSelectedPikPakAccount(result)
    const listing = await loadPikPakTreeNode({ force })
    pikpakFiles.value = Array.isArray(listing.files) ? listing.files : []
    const activeId = listing.account_id || selectedPikPakAccountId.value
    const nextStatuses = pikpakAccountStatuses.value.map(item => {
      const itemId = item.account_id || item.account?.id
      if (itemId !== activeId) return item
      return { ...item, files: pikpakFiles.value, folder_id: listing.folder_id || item.folder_id }
    })
    if (nextStatuses.length) {
      pikpakStatus.value = { ...(pikpakStatus.value || {}), accounts: nextStatuses }
    } else {
      pikpakStatus.value = { ...(pikpakStatus.value || {}), files: pikpakFiles.value, folder_id: listing.folder_id || '' }
    }
    const visibleIds = new Set(pikpakTreeRows.value.map(row => row.id).filter(Boolean))
    selectedPikPakFileIds.value = selectedPikPakFileIds.value.filter(id => visibleIds.has(id))
    pikpakMessage.value = `✓ 已读取 ${pikpakFiles.value.length} 个转存项`
  } catch (error) {
    setPikPakError(error)
  } finally {
    pikpakBusy.value = false
  }
}

async function loadPikPakCachedStatus() {
  if (!props.config.http_downloader.pikpak_enabled || pikpakStatus.value) return
  try {
    const result = await httpDownloadApi.pikpakStatus({ includeFiles: false, limit: 1, forceRefresh: false })
    pikpakStatus.value = result
    ensureSelectedPikPakAccount(result)
  } catch (error) {
    console.debug('读取 PikPak 缓存状态失败:', error)
  }
}

async function openPikPakManager() {
  pikpakManagerVisible.value = true
  pikpakListRoot.value = true
  selectedPikPakFileIds.value = []
  resetPikPakTreeViewState()
  await refreshPikPakManager()
}

function closePikPakManager() {
  pikpakManagerVisible.value = false
}

async function switchPikPakListRoot(nextRoot) {
  pikpakListRoot.value = Boolean(nextRoot)
  selectedPikPakFileIds.value = []
  resetPikPakTreeViewState()
  await refreshPikPakManager(false)
}

async function selectPikPakManagerAccount(accountId) {
  const nextId = String(accountId || '')
  if (selectedPikPakAccountId.value === nextId) return
  selectedPikPakAccountId.value = nextId
  selectedPikPakFileIds.value = []
  resetPikPakTreeViewState()
  await refreshPikPakManager(false)
}

async function togglePikPakFolder(item) {
  const id = String(item?.id || '').trim()
  if (!id) return
  const next = new Set(pikpakTreeExpandedIds.value)
  if (next.has(id)) {
    next.delete(id)
    pikpakTreeExpandedIds.value = next
    bumpPikPakTreeVersion()
    return
  }
  next.add(id)
  pikpakTreeExpandedIds.value = next
  bumpPikPakTreeVersion()
  try {
    await loadPikPakTreeNode({ parentId: id })
  } catch (error) {
    setPikPakError(error, '读取 PikPak 子目录失败')
  }
}

function handlePikPakTreeRowClick(row) {
  if (row.placeholder) return
  if (row.isFolder) {
    togglePikPakFolder(row.item)
    return
  }
  togglePikPakFile(row.id)
}

function togglePikPakFile(id) {
  const value = String(id || '').trim()
  if (!value) return
  if (selectedPikPakFileIds.value.includes(value)) {
    selectedPikPakFileIds.value = selectedPikPakFileIds.value.filter(item => item !== value)
  } else {
    selectedPikPakFileIds.value = [...selectedPikPakFileIds.value, value]
  }
}

async function deleteSelectedPikPak(permanent = false) {
  if (!selectedPikPakFileIds.value.length || pikpakBusy.value) return
  pikpakBusy.value = true
  try {
    const count = selectedPikPakFileIds.value.length
    const result = await httpDownloadApi.pikpakDelete({ ids: selectedPikPakFileIds.value, permanent, accountId: selectedPikPakAccountId.value })
    if (result.quota) {
      pikpakStatus.value = { ...(pikpakStatus.value || {}), quota: result.quota }
    }
    pikpakMessage.value = `✓ 已${permanent ? '永久删除' : '移入回收站'} ${count} 项`
    ElMessage.success(pikpakMessage.value.slice(2))
    selectedPikPakFileIds.value = []
    clearPikPakTreeCache()
    await refreshPikPakManager(true)
  } catch (error) {
    setPikPakError(error, '删除 PikPak 转存文件失败')
  } finally {
    pikpakBusy.value = false
  }
}

async function clearAllPikPakTransfers() {
  if (pikpakBusy.value) return
  try {
    await showSystemConfirm({
      title: '清空所有 PikPak 转存空间',
      message: '会永久删除所有已启用 PikPak 账号网盘里的文件，并继续清空回收站。',
      description: '删除后无法从本工具恢复。正在执行的 PikPak 下载仍可能再次产生转存文件。',
      details: [
        { label: '账号数量', value: `${pikpakHealthyAccountCount.value}/${pikpakAccountStatuses.value.length || visiblePikPakAccountRows.value.length || 0}` },
        { label: '当前已用', value: formatBytes(pikpakTotalQuota.value.usage) },
        { label: '回收站', value: formatBytes(pikpakTotalQuota.value.trash) }
      ],
      confirmText: '永久清空',
      cancelText: '取消',
      tone: 'danger'
    })
  } catch {
    return
  }

  pikpakBusy.value = true
  pikpakMessage.value = '正在清空所有 PikPak 账号的转存文件...'
  try {
    const result = await httpDownloadApi.pikpakClear({ timeout: 180000 })
    const deletedCount = Number(result?.deleted_count || 0)
    const failedCount = Number(result?.failed_account_count || 0)
    selectedPikPakFileIds.value = []
    pikpakFiles.value = []
    clearPikPakTreeCache()
    const suffix = failedCount ? `，${failedCount} 个账号失败` : ''
    pikpakMessage.value = `✓ 已清空 ${deletedCount} 项${suffix}`
    if (failedCount) {
      ElMessage.warning(pikpakMessage.value.slice(2))
    } else {
      ElMessage.success(pikpakMessage.value.slice(2))
    }
    try {
      pikpakStatus.value = await httpDownloadApi.pikpakStatus({ includeFiles: false, limit: 1, forceRefresh: false })
      ensureSelectedPikPakAccount(pikpakStatus.value)
    } catch (refreshError) {
      console.debug('清空完成后读取 PikPak 缓存状态失败:', refreshError)
    }
  } catch (error) {
    setPikPakError(error, '清空 PikPak 转存空间失败')
  } finally {
    pikpakBusy.value = false
  }
}

onMounted(() => {
  window.addEventListener('message', handleGoogleDriveOAuthMessage)
  loadPikPakCachedStatus()
  notifyGoogleDriveExpired()
})

watch(googleDriveOAuthExpired, (expired) => {
  if (!expired) {
    googleDriveExpiredNotified.value = false
    return
  }
  notifyGoogleDriveExpired()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', handleGoogleDriveOAuthMessage)
  if (googleDriveOAuthPopupTimer.value) {
    window.clearInterval(googleDriveOAuthPopupTimer.value)
    googleDriveOAuthPopupTimer.value = null
  }
  googleDriveOAuthPopup.value = null
})
</script>

<style scoped>
.http-settings-stack {
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

.google-drive-oauth-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.google-drive-oauth-status {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  min-height: 34px;
  gap: 7px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.3;
}

.google-drive-oauth-status span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.google-drive-oauth-status.is-ready {
  border-color: var(--set-success-border);
  background: var(--set-success-bg);
  color: var(--set-success-text);
}

.google-drive-oauth-status.is-expired {
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(127, 29, 29, 0.2);
  color: #fecaca;
}

.google-drive-account-card {
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

.google-drive-account-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.45);
  background: var(--set-surface);
}

.google-drive-account-avatar.is-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--set-success-text);
  font-size: 13px;
  font-weight: 800;
}

.google-drive-account-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.google-drive-account-main strong,
.google-drive-account-main span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.google-drive-account-main strong {
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 700;
}

.google-drive-account-main span {
  color: var(--set-success-text);
  font-size: 12px;
}

.google-drive-account-card small {
  color: var(--set-text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.google-drive-oauth-advanced {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}

.google-drive-oauth-advanced-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(150px, 190px);
  gap: 10px;
  align-items: center;
}

.google-drive-oauth-advanced-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.google-drive-oauth-advanced-head span {
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 700;
}

.google-drive-oauth-advanced-head small {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-muted);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.google-drive-oauth-custom-grid {
  display: grid;
  gap: 10px;
}

.google-drive-oauth-mode-dd {
  width: 100%;
}

.settings-card {
  min-height: 0;
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
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

.field-input {
  width: 100%;
  min-height: 36px;
  padding: 0 11px;
  border: 1px solid var(--set-border);
  border-radius: 9px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: var(--set-border-strong); }

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.field-input::placeholder { color: var(--set-text-subtle); }

.settings-field-dd { display: block; width: 100%; }

.settings-field-dd :deep(.app-dd-root),
.settings-field-dd :deep(.app-dd-trigger-anchor) {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 36px;
  height: 36px;
  padding: 0 11px;
  border-radius: 9px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  font-size: 13px;
  justify-content: space-between;
  box-shadow: none;
}

.settings-field-dd :deep(.app-dd-trigger:hover) { border-color: var(--set-border-strong); }

.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: var(--set-border-strong);
  box-shadow: none;
}

.http-proxy-platform-dd :deep(.app-dd-trigger-anchor) {
  width: 100%;
}

.http-proxy-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-height: 36px;
  padding: 4px 10px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  cursor: pointer;
  outline: none;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.http-proxy-trigger:hover,
.http-proxy-trigger.is-open {
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
}

.http-proxy-trigger:focus,
.http-proxy-trigger:focus-visible {
  outline: none;
  box-shadow: none;
}

.http-proxy-trigger-icons {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  gap: 8px;
  align-items: center;
  overflow: hidden;
}

.http-proxy-icon-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--set-text);
}

.http-proxy-icon-chip :deep(.http-platform-icon),
.http-proxy-option-icon :deep(.http-platform-icon) {
  width: 18px;
  height: 18px;
  object-fit: contain;
  border-radius: 0;
}

.http-proxy-trigger-placeholder {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--set-text-muted);
  font-size: 13px;
  text-align: left;
}

.http-proxy-trigger-caret {
  flex: 0 0 auto;
  color: var(--set-text-muted);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.http-proxy-trigger-caret.is-open {
  transform: rotate(180deg);
}

.http-proxy-option-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  background: transparent;
  color: var(--set-text);
}

.http-proxy-option-main {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  gap: 1px;
}

.http-proxy-option-label {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.http-proxy-option-desc {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.http-proxy-option-check {
  flex: 0 0 auto;
  color: var(--set-text-strong);
}

:global(.http-proxy-platform-menu) {
  display: grid;
  gap: 2px;
  padding: 6px;
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.96));
  border: 1px solid rgba(203, 213, 225, 0.82);
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.14);
}

:global(.http-proxy-platform-menu .app-dd-item) {
  min-height: 48px;
  padding: 6px 10px;
  border-radius: 10px;
  background: transparent;
  gap: 9px;
  transform-origin: center;
}

:global(.http-proxy-platform-menu .app-dd-item:hover) {
  background: rgba(226, 232, 240, 0.6);
}

:global(.http-proxy-platform-menu .app-dd-item.is-active) {
  background: linear-gradient(135deg, rgba(226, 232, 240, 0.9), rgba(241, 245, 249, 0.96));
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.22);
}

:global(html.kikoerumanager-dark .http-proxy-platform-menu) {
  background:
    linear-gradient(180deg, rgba(24, 31, 42, 0.98), rgba(15, 23, 42, 0.98));
  border-color: rgba(71, 85, 105, 0.72);
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.35);
}

:global(html.kikoerumanager-dark .http-proxy-platform-menu .app-dd-item:hover) {
  background: rgba(51, 65, 85, 0.64);
}

:global(html.kikoerumanager-dark .http-proxy-platform-menu .app-dd-item.is-active) {
  background: linear-gradient(135deg, rgba(51, 65, 85, 0.92), rgba(30, 41, 59, 0.96));
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18);
}

.ghost-inline-btn,
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  border-radius: 9px;
  border: 1px solid var(--pikpak-control-border, var(--set-border));
  background: var(--set-surface);
  color: var(--set-text);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ghost-inline-btn { padding: 0 14px; }

.ghost-inline-btn.compact {
  height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 12px;
}

.pikpak-stateful-btn {
  min-width: 0;
}

.pikpak-stateful-btn :deep(.stateful-button__content) {
  gap: 6px;
}

@keyframes pikpak-spin {
  to {
    transform: rotate(360deg);
  }
}

.spin-icon {
  display: inline-block;
  animation: pikpak-spin 0.9s linear infinite;
  transform-origin: center;
  will-change: transform;
}

.ghost-inline-btn:not(:disabled):hover,
.icon-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.ghost-inline-btn:disabled,
.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn { width: 36px; padding: 0; }
.icon-btn.danger { color: #e11d48; border-color: rgba(244, 63, 94, 0.4); }
.icon-btn.danger:hover {
  background: linear-gradient(135deg, rgba(254, 226, 226, 0.6) 0%, #ffffff 100%);
  border-color: rgba(244, 63, 94, 0.7);
  color: #be123c;
}

.pikpak-status-card,
.pikpak-accounts-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--pikpak-panel-border, var(--set-border));
  background: var(--pikpak-panel-bg, var(--set-surface));
}

.pikpak-accounts-card { padding: 12px; }

.pikpak-accounts-head,
.pikpak-status-head,
.pikpak-manager-head,
.pikpak-manager-actions,
.pikpak-manager-quota {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pikpak-account-list {
  display: grid;
  gap: 4px;
}

.pikpak-account-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 7px;
  align-items: center;
  padding: 7px 0 0;
  border-radius: 0;
  border: 0;
  border-top: 1px solid var(--pikpak-row-divider, var(--set-border-soft, var(--set-border)));
  background: transparent;
}

.pikpak-account-row:first-child {
  padding-top: 0;
  border-top: 0;
}

.pikpak-account-row.is-ok {
  border-color: var(--set-success-border);
}

.pikpak-account-row.is-error {
  border-color: var(--set-danger-border);
}

.pikpak-account-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 32px;
  height: 30px;
  color: var(--set-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.pikpak-account-index input {
  width: 16px;
  height: 16px;
  accent-color: var(--set-primary-bg);
}

.pikpak-account-side {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.pikpak-account-fields {
  display: grid;
  grid-template-columns: minmax(150px, 0.9fr) minmax(170px, 1fr) minmax(160px, 1fr) minmax(170px, 1fr);
  gap: 7px;
}

.pikpak-account-note {
  grid-column: 1 / -1;
  min-width: 0;
  color: var(--set-text-muted);
  font-size: 11px;
  line-height: 1.35;
  white-space: normal;
}

.pikpak-account-status {
  grid-column: 2 / -1;
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
  padding: 2px 0 0;
  border-radius: 0;
  border: 0;
  background: transparent;
  color: var(--set-text-muted);
  font-size: 12px;
}

.pikpak-account-status span {
  flex: 0 0 auto;
  font-weight: 700;
}

.pikpak-account-status small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-account-status.is-ok {
  color: var(--set-success-text);
}

.pikpak-account-status.is-error {
  color: var(--set-danger-text);
}

.pikpak-status-title,
.pikpak-manager-title {
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 700;
}

.pikpak-status-subtitle,
.pikpak-manager-subtitle {
  margin-top: 2px;
  color: var(--set-text-muted);
  font-size: 12px;
}

.pikpak-status-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.pikpak-quota-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.pikpak-quota-summary > div {
  padding: 10px;
  border-radius: 9px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}

.pikpak-quota-summary span {
  display: block;
  color: var(--set-text-muted);
  font-size: 11px;
}

.pikpak-quota-summary strong {
  display: block;
  margin-top: 4px;
  color: var(--set-text-strong);
  font-size: 14px;
}

.pikpak-quota-bar {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}

.pikpak-quota-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--set-text-muted) 0%, var(--set-text-strong) 100%);
  transition: width 0.24s ease;
}

.pikpak-account-usage-list {
  display: grid;
  gap: 7px;
}

.pikpak-account-usage-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, 180px) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 9px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
}

.pikpak-usage-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.pikpak-usage-main strong {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-strong);
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-usage-main span {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-muted);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-usage-meter {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
}

.pikpak-usage-meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--set-text-strong);
}

.pikpak-account-usage-row small {
  color: var(--set-text-muted);
  font-size: 11px;
  font-weight: 700;
}

.pikpak-account-usage-row.is-error {
  border-color: var(--set-danger-border);
}

.pikpak-message {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--set-border);
  color: var(--set-text);
  font-size: 12px;
  line-height: 1.5;
}

.pikpak-message.is-success { border-color: var(--set-success-border); color: var(--set-success-text); background: var(--set-success-bg); }
.pikpak-message.is-error { border-color: var(--set-danger-border); color: var(--set-danger-text); background: var(--set-danger-bg); }
.pikpak-message.is-info { background: var(--set-surface); }

.pikpak-manager-overlay {
  --set-surface: rgba(255, 255, 255, 0.14);
  --set-surface-soft: rgba(255, 255, 255, 0.05);
  --set-surface-muted: rgba(255, 255, 255, 0.08);
  --set-surface-hover: rgba(255, 255, 255, 0.18);
  --set-field-bg: rgba(255, 255, 255, 0.08);
  --set-text: #334155;
  --set-text-strong: #111827;
  --set-text-muted: #64748b;
  --set-text-subtle: #94a3b8;
  --set-border: rgba(148, 163, 184, 0.32);
  --set-border-strong: rgba(51, 65, 85, 0.24);
  --set-accent: #111827;
  --set-primary-bg: #1f2937;
  --set-success-bg: #ecfdf5;
  --set-success-border: rgba(110, 231, 183, 0.55);
  --set-success-text: #047857;
  --set-danger-bg: #fff1f2;
  --set-danger-border: rgba(252, 165, 165, 0.55);
  --set-danger-text: #b91c1c;
  --pikpak-modal-bg:
    linear-gradient(135deg, rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.015) 46%, rgba(255, 255, 255, 0.09)),
    rgba(255, 255, 255, 0.02);
  --pikpak-glass-panel: rgba(255, 255, 255, 0.012);
  --pikpak-glass-card: rgba(255, 255, 255, 0.03);
  --pikpak-glass-card-hover: rgba(255, 255, 255, 0.11);
  --pikpak-glass-border: rgba(255, 255, 255, 0.82);
  --pikpak-glass-inset: rgba(255, 255, 255, 0.72);
  --pikpak-modal-border: rgba(255, 255, 255, 0.78);
  --pikpak-modal-highlight:
    linear-gradient(180deg, rgba(255, 255, 255, 0.24), transparent 34%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.22), transparent 26%, rgba(255, 255, 255, 0.06) 58%, transparent 82%);
  --pikpak-modal-highlight-opacity: 0.28;
  --pikpak-modal-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    inset 0 -1px 0 rgba(15, 23, 42, 0.03),
    0 32px 72px -24px rgba(15, 23, 42, 0.28),
    0 14px 36px -18px rgba(15, 23, 42, 0.18),
    0 2px 8px rgba(15, 23, 42, 0.06);
  --pikpak-soft-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
  --pikpak-selected-shadow: 0 8px 18px rgba(59, 130, 246, 0.08);
  --pikpak-tree-selected-bg: rgba(219, 234, 254, 0.16);
  --pikpak-tree-selected-border: rgba(59, 130, 246, 0.28);
  --pikpak-tree-selected-rail: #3b82f6;
  position: fixed;
  inset: 0;
  z-index: 5000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: transparent;
}

:global(html.kikoerumanager-dark .pikpak-manager-overlay),
:global(body.kikoerumanager-dark .pikpak-manager-overlay) {
  --set-surface: rgba(21, 21, 21, 0.34);
  --set-surface-soft: rgba(27, 27, 29, 0.14);
  --set-surface-muted: rgba(36, 36, 39, 0.18);
  --set-surface-hover: rgba(32, 32, 35, 0.28);
  --set-field-bg: rgba(27, 27, 29, 0.2);
  --set-text: #d4d4d8;
  --set-text-strong: #f5f5f5;
  --set-text-muted: #a1a1aa;
  --set-text-subtle: #71717a;
  --set-border: rgba(255, 255, 255, 0.11);
  --set-border-strong: rgba(255, 255, 255, 0.18);
  --set-accent: #e5e7eb;
  --set-primary-bg: #2b2c30;
  --set-primary-bg-hover: #333438;
  --set-primary-border: rgba(255, 255, 255, 0.14);
  --set-primary-text: #f5f5f5;
  --set-success-bg: rgba(52, 211, 153, 0.13);
  --set-success-border: rgba(52, 211, 153, 0.28);
  --set-success-text: #86efac;
  --set-danger-bg: rgba(251, 113, 133, 0.13);
  --set-danger-border: rgba(251, 113, 133, 0.3);
  --set-danger-text: #fda4af;
  --pikpak-modal-bg:
    linear-gradient(135deg, rgba(48, 49, 54, 0.28), rgba(18, 19, 22, 0.1) 48%, rgba(38, 39, 44, 0.2)),
    rgba(18, 19, 22, 0.24);
  --pikpak-glass-panel: rgba(38, 39, 44, 0.1);
  --pikpak-glass-card: rgba(38, 39, 44, 0.13);
  --pikpak-glass-card-hover: rgba(48, 50, 56, 0.24);
  --pikpak-glass-border: rgba(255, 255, 255, 0.16);
  --pikpak-glass-inset: rgba(255, 255, 255, 0.1);
  --pikpak-modal-border: rgba(255, 255, 255, 0.13);
  --pikpak-modal-highlight: linear-gradient(180deg, rgba(255, 255, 255, 0.07), transparent 30%);
  --pikpak-modal-highlight-opacity: 0.18;
  --pikpak-modal-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    inset 0 -1px 0 rgba(255, 255, 255, 0.035),
    0 28px 66px -26px rgba(0, 0, 0, 0.74),
    0 10px 28px -22px rgba(0, 0, 0, 0.68);
  --pikpak-soft-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
  --pikpak-selected-shadow: 0 8px 18px rgba(0, 0, 0, 0.22);
  --pikpak-tree-selected-bg: linear-gradient(90deg, rgba(96, 165, 250, 0.16), rgba(32, 32, 35, 0.68));
  --pikpak-tree-selected-border: rgba(96, 165, 250, 0.28);
  --pikpak-tree-selected-rail: #60a5fa;
  background: transparent;
}

.pikpak-manager-modal {
  position: relative;
  isolation: isolate;
  display: grid;
  gap: 12px;
  width: min(820px, 96vw);
  max-height: min(760px, 92vh);
  overflow: hidden;
  padding: 18px;
  border-radius: 22px;
  border: 1px solid var(--pikpak-modal-border);
  background: var(--pikpak-modal-bg);
  color: var(--set-text);
  box-shadow: var(--pikpak-modal-shadow);
  backdrop-filter: blur(16px) saturate(180%) contrast(108%);
  -webkit-backdrop-filter: blur(16px) saturate(180%) contrast(108%);
}

.pikpak-manager-modal::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: inherit;
  background: var(--pikpak-modal-highlight);
  opacity: var(--pikpak-modal-highlight-opacity);
  pointer-events: none;
}

.pikpak-manager-modal > * {
  position: relative;
  z-index: 1;
}

.pikpak-manager-modal .ghost-inline-btn {
  background: var(--pikpak-glass-card);
  border-color: var(--pikpak-glass-border);
  color: var(--set-text);
  box-shadow:
    inset 0 1px 0 var(--pikpak-glass-inset),
    var(--pikpak-soft-shadow);
  backdrop-filter: blur(12px) saturate(155%);
  -webkit-backdrop-filter: blur(12px) saturate(155%);
}

.pikpak-manager-modal .ghost-inline-btn:hover:not(:disabled),
.pikpak-manager-modal .ghost-inline-btn.active {
  background: var(--pikpak-glass-card-hover);
  border-color: var(--set-border-strong);
  color: var(--set-text-strong);
}

.pikpak-icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid var(--pikpak-glass-border);
  background: var(--pikpak-glass-card);
  color: var(--set-text-strong);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  backdrop-filter: blur(12px) saturate(155%);
  -webkit-backdrop-filter: blur(12px) saturate(155%);
}

.pikpak-account-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 2px 4px;
  scrollbar-width: thin;
  scrollbar-color: var(--set-border-strong) transparent;
}

.pikpak-account-tab {
  position: relative;
  display: grid;
  gap: 4px;
  min-width: 140px;
  padding: 10px 12px;
  border-radius: 9px;
  border: 1px solid var(--pikpak-glass-border);
  background: var(--pikpak-glass-card);
  color: var(--set-text);
  text-align: left;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 var(--pikpak-glass-inset),
    var(--pikpak-soft-shadow);
  backdrop-filter: blur(12px) saturate(155%);
  -webkit-backdrop-filter: blur(12px) saturate(155%);
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pikpak-account-tab.active {
  border-color: rgba(52, 211, 153, 0.42);
  background: var(--pikpak-glass-card-hover);
  color: var(--set-text-strong);
  box-shadow:
    inset 0 0 0 1px rgba(52, 211, 153, 0.14),
    inset 0 1px 0 var(--pikpak-glass-inset),
    var(--pikpak-soft-shadow);
}

.pikpak-account-tab.is-ok.active {
  border-color: var(--set-success-border);
}

.pikpak-account-tab.is-error {
  border-color: var(--set-danger-border);
}

.pikpak-account-tab-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.pikpak-account-tab span {
  min-width: 0;
  overflow: hidden;
  font-size: 12.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-account-tab small {
  color: var(--set-text-muted);
  font-size: 11px;
}

.pikpak-manager-quota {
  align-items: stretch;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.pikpak-manager-quota > div {
  padding: 10px;
  border-radius: 12px;
  border: 1px solid var(--pikpak-glass-border);
  background: var(--pikpak-glass-card);
  box-shadow:
    inset 0 1px 0 var(--pikpak-glass-inset),
    var(--pikpak-soft-shadow);
  backdrop-filter: blur(12px) saturate(155%);
  -webkit-backdrop-filter: blur(12px) saturate(155%);
}

.pikpak-manager-quota span {
  display: block;
  color: var(--set-text-muted);
  font-size: 11px;
}

.pikpak-manager-quota strong {
  display: block;
  margin-top: 4px;
  color: var(--set-text-strong);
  font-size: 13px;
}

.pikpak-manager-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.ghost-inline-btn.danger {
  border-color: rgba(244, 63, 94, 0.42);
  color: #fb7185;
}

.pikpak-file-tree {
  min-height: 190px;
  overflow: hidden;
  border-radius: 14px;
  border: 1px solid var(--pikpak-glass-border);
  background: var(--pikpak-glass-panel);
  box-shadow:
    inset 0 1px 0 var(--pikpak-glass-inset),
    inset 0 -1px 0 rgba(15, 23, 42, 0.03);
  backdrop-filter: blur(14px) saturate(160%);
  -webkit-backdrop-filter: blur(14px) saturate(160%);
}

.pikpak-tree-scroll {
  min-height: 160px;
  max-height: 420px;
  overflow: auto;
  padding: 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--set-border-strong) transparent;
}

.pikpak-tree-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 36px;
  margin-bottom: 4px;
  padding: 6px 10px;
  border-radius: 7px;
  border: 1px solid transparent;
  color: var(--set-text);
  cursor: pointer;
  transition: background-color 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.pikpak-tree-row:last-child {
  margin-bottom: 0;
}

.pikpak-tree-row:hover {
  border-color: var(--pikpak-glass-border);
  background: var(--pikpak-glass-card-hover);
}

.pikpak-tree-row.is-selected {
  border-color: var(--pikpak-tree-selected-border);
  background: var(--pikpak-tree-selected-bg);
  box-shadow:
    inset 3px 0 0 var(--pikpak-tree-selected-rail),
    var(--pikpak-selected-shadow);
  transform: none;
}

.pikpak-tree-row.is-placeholder {
  color: var(--set-text-muted);
  cursor: default;
}

.pikpak-tree-main {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  gap: 8px;
}

.pikpak-tree-expander,
.pikpak-tree-expander-spacer {
  width: 22px;
  flex: 0 0 22px;
}

.pikpak-tree-expander {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--set-text-muted);
  cursor: pointer;
  transition: all 0.18s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pikpak-tree-expander:hover:not(:disabled) {
  background: var(--set-surface-muted);
  color: var(--set-text-strong);
  transform: scale(1.08);
}

.pikpak-tree-expander:disabled {
  cursor: wait;
  opacity: 0.72;
}

.pikpak-tree-checkbox,
.pikpak-tree-checkbox-spacer {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
}

.pikpak-tree-checkbox {
  accent-color: var(--set-primary-bg);
  cursor: pointer;
}

.pikpak-tree-icon {
  flex: 0 0 auto;
  color: var(--set-text-muted);
}

.pikpak-tree-icon.is-folder {
  color: #d97706;
  fill: rgba(245, 158, 11, 0.16);
}

.pikpak-tree-icon.is-audio {
  color: #0f766e;
}

.pikpak-tree-icon.is-video {
  color: #7c3aed;
}

.pikpak-tree-icon.is-archive {
  color: #be123c;
}

.pikpak-tree-icon.is-muted {
  color: var(--set-text-subtle);
}

.pikpak-tree-text {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.pikpak-tree-name {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-strong);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-tree-meta {
  min-width: 0;
  overflow: hidden;
  color: var(--set-text-muted);
  font-size: 11px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pikpak-tree-size {
  flex: 0 0 auto;
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.pikpak-empty {
  display: grid;
  gap: 8px;
  place-items: center;
  min-height: 160px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.18);
  color: var(--set-text-muted);
  font-size: 12px;
}

.pikpak-empty.small {
  min-height: 64px;
}

.fade-up-enter-active,
.fade-up-leave-active { transition: all 0.24s ease; }
.fade-up-enter-from,
.fade-up-leave-to { opacity: 0; transform: translateY(5px); }

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two,
  .mini-grid.three,
  .google-drive-oauth-actions,
  .google-drive-oauth-advanced-head {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .google-drive-account-card {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .google-drive-account-card small {
    grid-column: 2;
  }

  .pikpak-account-fields,
  .pikpak-manager-quota {
    grid-template-columns: 1fr;
  }

  .pikpak-account-row {
    grid-template-columns: 1fr;
  }

  .pikpak-account-index {
    justify-content: flex-start;
  }
}
</style>
