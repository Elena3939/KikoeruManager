<template>
  <div class="settings-page">
    <AppPageHeader
      :icon="IconSettings"
      icon-color="var(--km-nav-settings-icon)"
      title="设置工作台"
      subtitle="集中管理连接、目录、规则、外部服务和通知模板"
    >
      <span class="set-chip" :class="hasChanges ? 'set-chip-warning' : 'set-chip-success'">
        <component :is="hasChanges ? IconAlertCircle : IconCheckCircle2" :size="12" :stroke-width="2.4" />
        {{ hasChanges ? '有未保存改动' : '已同步' }}
      </span>
      <span class="set-chip set-chip-info">
        <IconClock :size="12" :stroke-width="2.4" />
        {{ lastSavedLabel }}
      </span>
    </AppPageHeader>

    <SettingsWorkbench
      :sections="sections"
      :active-section="activeSection"
      :search-query="searchQuery"
      :has-changes="hasChanges"
      :saving="saving"
      :reloading="reloading"
      :dirty-map="dirtyMap"
      :config-path="configPathDisplay"
      @navigate="activeSection = $event"
      @save="saveConfig"
      @reload="reloadConfigFromServer"
      @reset-all="resetAllConfig"
      @update:searchQuery="searchQuery = $event"
    >
      <SettingsSectionPanel
        v-if="activeSection === 'storage'"
        kicker="Storage & Inventory"
        title="存储与库存"
        description="把本地路径、多库存和群晖模板都收进一个工作台。连接信息只维护一次，共享目录库存直接复用。"
      >
        <StorageSettingsPanel
          :model-value="config"
          :profiles="profiles"
          :libraries="libraries"
          :primary-profile="primaryProfile"
          :profile-summaries="profileSummaries"
          :library-view-models="libraryViewModels"
          :get-profile-summary="getProfileSummary"
          :get-library-view-model="getLibraryViewModel"
          :selected-library-id="selectedLibraryId"
          :testing-profile-id="testingProfileId"
          :testing-library-id="testingLibraryId"
          :build-synology-web-url="buildSynologyWebUrl"
          @select-library="selectedLibraryId = $event"
          @test-profile="testProfileConnection"
          @create-library="handleCreateLibrary"
          @remove-library="removeStorageLibrary"
          @test-library="testStorageLibrary"
          @extract-profile="extractSynologyProfileFromLibrary"
          @update-profile-flag="updateProfileFlag"
          @update-library-flag="updateLibraryFlag"
          @profile-change="handleLibraryProfileChange"
          @sync-path="syncRemoteLibraryPath"
        />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'processing'"
        kicker="Pipeline"
        title="处理流程"
        description="把扫描、解压、自动处理和已有文件夹链路放在一组里看，避免到处来回找开关。"
      >
        <ProcessingSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'rules'"
        kicker="Rules"
        title="内容规则"
        description="把过滤、重命名、分类和路径映射放到一组里，专注控制最终落盘形态。"
      >
        <RulesSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'services'"
        kicker="External Services"
        title="外部服务"
        description="集中维护 Kikoeru、ASMR 下载、RJ 字幕抓取和邮件监听等远程链路。"
      >
        <ServicesSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'aiSubtitle'"
        kicker="AI Subtitle Matching"
        title="AI 配对"
        description="单独维护字幕配对模型、Key、代理、提示词和测试连接，任务执行仍由当前参数面板约束。"
      >
        <AISubtitleSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'httpDownload'"
        kicker="HTTP Downloader"
        title="HTTP 下载"
        description="配置 HTTP/HTTPS 外链、Gofile 分享和 PikPak 下载。"
      >
        <HttpDownloadSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'baiduNetdisk'"
        kicker="Baidu Netdisk"
        title="百度网盘"
        description="配置官方账号绑定、分享直下和百度网盘下载落盘规则。"
      >
        <BaiduNetdiskSettingsPanel :config="config" @persisted="handleBaiduNetdiskPersisted" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'maintenance'"
        kicker="Maintenance"
        title="维护与清理"
        description="自动清理、备份打包等维护项集中放在一起，避免日常配置区被危险操作打断。"
      >
        <MaintenanceSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'fts'"
        kicker="Full-Text Search"
        title="全文搜索索引"
        description="管理 SQLite FTS5 全文搜索索引。trigram tokenizer 支持中文任意片段搜索，unicode61 仅支持英文前缀。重建期间搜索自动降级，功能不中断。"
      >
        <FtsSettingsPanel />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'security'"
        kicker="Security Gate"
        title="安全门禁"
        description="用 Google Authenticator 给系统入口加一层轻量保护，覆盖访问验证、黑名单和安全提醒。"
      >
        <SecurityGateSettingsPanel :config="config" />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else
        kicker="Notifications"
        title="通知中心"
        description="任务完成、失败或需要人工处理时，站内铃铛实时提醒；配置 SMTP 还可收到邮件推送。"
      >
        <NotificationSettingsPanel :config="config" />
      </SettingsSectionPanel>
    </SettingsWorkbench>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Bell, Bot, Boxes, DownloadCloud, HardDrive, LifeBuoy, ScanSearch, ShieldCheck, TextSearch, Workflow, Settings2 as IconSettings, AlertCircle as IconAlertCircle, CheckCircle2 as IconCheckCircle2, Clock as IconClock } from 'lucide-vue-next'
import SettingsSectionPanel from '../components/settings/SettingsSectionPanel.vue'
import SettingsWorkbench from '../components/settings/SettingsWorkbench.vue'
import BaiduNetdiskNavIcon from '../components/settings/BaiduNetdiskNavIcon.vue'
import StorageSettingsPanel from '../components/settings/StorageSettingsPanel.vue'
import ProcessingSettingsPanel from '../components/settings/ProcessingSettingsPanel.vue'
import RulesSettingsPanel from '../components/settings/RulesSettingsPanel.vue'
import ServicesSettingsPanel from '../components/settings/ServicesSettingsPanel.vue'
import AISubtitleSettingsPanel from '../components/settings/AISubtitleSettingsPanel.vue'
import HttpDownloadSettingsPanel from '../components/settings/HttpDownloadSettingsPanel.vue'
import BaiduNetdiskSettingsPanel from '../components/settings/BaiduNetdiskSettingsPanel.vue'
import MaintenanceSettingsPanel from '../components/settings/MaintenanceSettingsPanel.vue'
import FtsSettingsPanel from '../components/settings/FtsSettingsPanel.vue'
import NotificationSettingsPanel from '../components/settings/NotificationSettingsPanel.vue'
import SecurityGateSettingsPanel from '../components/settings/SecurityGateSettingsPanel.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import { useSettingsDraft } from '../composables/useSettingsDraft'
import { useSynologyProfiles } from '../composables/useSynologyProfiles'
import { configApi } from '../api'

const sectionKeyMap = {
  storage: ['storage'],
  processing: ['watcher', 'processing', 'extract', 'auto_process', 'process_existing'],
  rules: ['filter', 'rename', 'classification', 'path_mappings', 'path_mapping_enabled'],
  services: ['kikoeru_server', 'asmr_sync', 'asmr_sync_step', 'rj_subtitle', 'email_watcher'],
  aiSubtitle: ['ai_subtitle_matching'],
  httpDownload: ['http_downloader'],
  baiduNetdisk: ['baidu_netdisk'],
  maintenance: ['password_cleanup', 'archive_cleanup', 'backup_zip'],
  fts: [],
  security: ['security_gate'],
  notification: ['notification_email', 'notification_center']
}

const {
  config,
  saving,
  reloading,
  lastSavedAt,
  hasChanges,
  dirtyMap,
  loadConfig,
  saveConfig,
  reloadConfigFromServer,
  resetAllConfig,
  markFieldsPersisted
} = useSettingsDraft({ sectionKeyMap })

const BAIDU_NETDISK_PERSISTED_FIELDS = [
  'enabled',
  'cookie',
  'account_name',
  'account_netdisk_name',
  'account_avatar_url',
  'account_uk',
  'share_code_separator',
  'vip_type',
  'vip_label',
  'vip_level',
  'vip_expire_at',
  'quota_bytes',
  'used_bytes',
  'account_cached_at'
]

const {
  profiles,
  libraries,
  primaryProfile,
  profileSummaries,
  libraryViewModels,
  testingProfileId,
  testingLibraryId,
  extractSynologyProfileFromLibrary,
  handleLibraryProfileChange,
  addStorageLibrary,
  removeStorageLibrary,
  buildSynologyWebUrl,
  testProfileConnection,
  testStorageLibrary,
  getProfileSummary,
  getLibraryViewModel,
  updateProfileFlag,
  updateLibraryFlag,
  syncRemoteLibraryPath
} = useSynologyProfiles(config)

const activeSection = ref('storage')
const searchQuery = ref('')
const selectedLibraryId = ref('')

const sections = [
  { id: 'storage', title: '存储与库存', short: '路径、本地库存、群晖模板', icon: HardDrive, keywords: ['storage', 'library', 'synology', '群晖', '库存'] },
  { id: 'processing', title: '处理流程', short: '监视、解压、自动处理', icon: Workflow, keywords: ['watcher', 'processing', 'extract', '自动处理'] },
  { id: 'rules', title: '内容规则', short: '过滤、重命名、分类、路径映射', icon: Boxes, keywords: ['filter', 'rename', 'classification', 'path'] },
  { id: 'services', title: '外部服务', short: 'Kikoeru、ASMR、RJ 字幕', icon: ScanSearch, keywords: ['kikoeru', 'asmr', 'subtitle', 'email', '外部服务'] },
  { id: 'aiSubtitle', title: 'AI 配对', short: '模型、Key、提示词、阈值', icon: Bot, keywords: ['ai', 'subtitle', 'match', 'model', 'prompt', '字幕配对', '模型', '提示词'] },
  { id: 'httpDownload', title: 'HTTP 下载', short: 'HTTP、Gofile、PikPak', icon: DownloadCloud, keywords: ['http', 'download', 'aria2', 'gofile', 'pikpak', '外链下载'] },
  { id: 'baiduNetdisk', title: '百度网盘', short: '官方登录、分享直下、SVIP', icon: BaiduNetdiskNavIcon, keywords: ['baidu', '百度网盘', '分享直下', 'SVIP', '百度'] },
  { id: 'maintenance', title: '维护与清理', short: '清理、备份、压缩包', icon: LifeBuoy, keywords: ['cleanup', 'backup', 'archive', '维护'] },
  { id: 'fts', title: '全文搜索索引', short: 'FTS5 trigram 加速', icon: TextSearch, keywords: ['fts', 'search', 'trigram', '索引', '全文搜索', 'sqlite'] },
  { id: 'security', title: '安全门禁', short: '验证器、黑名单', icon: ShieldCheck, keywords: ['security', 'google authenticator', '门禁', '黑名单'] },
  { id: 'notification', title: '通知中心', short: 'SMTP 邮件、站内铃铛', icon: Bell, keywords: ['notification', 'smtp', 'email', '通知', '邮件', '铃铛'] }
]

const lastSavedLabel = computed(() => {
  if (!lastSavedAt.value) return '尚未保存'
  const date = new Date(lastSavedAt.value)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
})

// 运行配置文件的真实路径，由 /api/config/state 返回。配置面板侧栏底部 + 顶栏 chip 都基于它显示。
const configPathRuntime = ref('')
const configPathDisplay = computed(() => configPathRuntime.value || '本地配置')

async function refreshConfigRuntimeState() {
  try {
    const state = await configApi.state()
    configPathRuntime.value = state?.path || ''
  } catch (error) {
    console.warn('[Settings] 获取配置运行态失败:', error)
  }
}

function handleCreateLibrary(type) {
  const created = addStorageLibrary(type)
  selectedLibraryId.value = created.id
}

function handleBaiduNetdiskPersisted() {
  markFieldsPersisted('baidu_netdisk', BAIDU_NETDISK_PERSISTED_FIELDS)
  lastSavedAt.value = Date.now()
}

watch(libraryViewModels, (list) => {
  if (!selectedLibraryId.value && list.length) selectedLibraryId.value = list[0].id
  if (selectedLibraryId.value && !list.some(item => item.id === selectedLibraryId.value)) {
    selectedLibraryId.value = list[0]?.id || ''
  }
}, { immediate: true, deep: true })

onMounted(() => {
  loadConfig()
  refreshConfigRuntimeState()
})
</script>

<style scoped>
/* =============================================
   Settings.vue — 仅保留 page 壳 + 顶栏 chip
   各 section 的字段 / 开关 / 业务样式都迁移到对应 panel scoped 里。
   ============================================= */

.settings-page {
  --set-page-bg: transparent;
  --set-surface: #ffffff;
  --set-surface-soft: #f8fafc;
  --set-surface-muted: #f1f5f9;
  --set-surface-hover: #f8fafc;
  --set-field-bg: #ffffff;
  --set-text: #334155;
  --set-text-strong: #111827;
  --set-text-muted: #64748b;
  --set-text-subtle: #94a3b8;
  --set-border: rgba(15, 23, 42, 0.12);
  --set-border-soft: rgba(15, 23, 42, 0.08);
  --set-border-strong: rgba(15, 23, 42, 0.2);
  --set-accent: #111827;
  --set-accent-hover: #1f2937;
  --set-accent-soft: rgba(15, 23, 42, 0.06);
  --set-primary-bg: #1f2937;
  --set-primary-bg-hover: #111827;
  --set-primary-border: rgba(15, 23, 42, 0.92);
  --set-primary-text: #ffffff;
  --set-chip-bg: #f8fafc;
  --set-chip-bg-active: #e5e7eb;
  --set-chip-text: #475569;
  --set-chip-text-strong: #0f172a;
  --set-focus-ring: rgba(15, 23, 42, 0.08);
  --set-success-bg: #ecfdf5;
  --set-success-border: rgba(110, 231, 183, 0.55);
  --set-success-text: #047857;
  --set-warning-bg: #fffbeb;
  --set-warning-border: rgba(251, 191, 36, 0.55);
  --set-warning-text: #b45309;
  --set-danger-bg: #fff1f2;
  --set-danger-border: rgba(252, 165, 165, 0.55);
  --set-danger-text: #b91c1c;
  --set-tag-local-bg: #fff7ed;
  --set-tag-local-border: rgba(194, 120, 3, 0.24);
  --set-tag-local-text: #9a3412;
  --set-tag-remote-bg: #ecfeff;
  --set-tag-remote-border: rgba(14, 116, 144, 0.24);
  --set-tag-remote-text: #0e7490;
  --set-tag-info-bg: #eef2ff;
  --set-tag-info-border: rgba(79, 70, 229, 0.18);
  --set-tag-info-text: #4338ca;
  --set-nav-storage-icon: #0f766e;
  --set-nav-processing-icon: #b45309;
  --set-nav-rules-icon: #7c3aed;
  --set-nav-services-icon: #0891b2;
  --set-nav-ai-subtitle-icon: #0d9488;
  --set-nav-http-download-icon: #0284c7;
  --set-nav-baidu-netdisk-icon: #2563eb;
  --set-nav-maintenance-icon: #c2410c;
  --set-nav-fts-icon: #4f46e5;
  --set-nav-security-icon: #15803d;
  --set-nav-notification-icon: #be185d;
  --set-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
  --set-shadow-hover: 0 18px 36px rgba(15, 23, 42, 0.1);
  max-width: 1480px;
  margin: 0 auto;
  padding: 16px;
  color: var(--set-text);
  background: var(--set-page-bg);
  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}

:global(html.kikoerumanager-dark .settings-page),
:global(body.kikoerumanager-dark .settings-page) {
  --set-page-bg: transparent;
  --set-surface: #151515;
  --set-surface-soft: #1b1b1d;
  --set-surface-muted: #242427;
  --set-surface-hover: #202023;
  --set-field-bg: #1b1b1d;
  --set-text: #d4d4d8;
  --set-text-strong: #f5f5f5;
  --set-text-muted: #a1a1aa;
  --set-text-subtle: #71717a;
  --set-border: rgba(255, 255, 255, 0.11);
  --set-border-soft: rgba(255, 255, 255, 0.08);
  --set-border-strong: rgba(255, 255, 255, 0.18);
  --set-accent: #e5e7eb;
  --set-accent-hover: #ffffff;
  --set-accent-soft: rgba(255, 255, 255, 0.08);
  --set-primary-bg: #2b2c30;
  --set-primary-bg-hover: #333438;
  --set-primary-border: rgba(255, 255, 255, 0.14);
  --set-primary-text: #f5f5f5;
  --set-chip-bg: #202023;
  --set-chip-bg-active: #2a2a2d;
  --set-chip-text: #d4d4d8;
  --set-chip-text-strong: #f5f5f5;
  --set-focus-ring: rgba(255, 255, 255, 0.08);
  --set-success-bg: rgba(52, 211, 153, 0.13);
  --set-success-border: rgba(52, 211, 153, 0.28);
  --set-success-text: #86efac;
  --set-warning-bg: rgba(251, 191, 36, 0.13);
  --set-warning-border: rgba(251, 191, 36, 0.28);
  --set-warning-text: #fbbf24;
  --set-danger-bg: rgba(251, 113, 133, 0.13);
  --set-danger-border: rgba(251, 113, 133, 0.3);
  --set-danger-text: #fda4af;
  --set-tag-local-bg: rgba(251, 191, 36, 0.13);
  --set-tag-local-border: rgba(251, 191, 36, 0.28);
  --set-tag-local-text: #facc15;
  --set-tag-remote-bg: rgba(45, 212, 191, 0.13);
  --set-tag-remote-border: rgba(94, 234, 212, 0.26);
  --set-tag-remote-text: #5eead4;
  --set-tag-info-bg: rgba(129, 140, 248, 0.14);
  --set-tag-info-border: rgba(165, 180, 252, 0.22);
  --set-tag-info-text: #c7d2fe;
  --set-nav-storage-icon: #5eead4;
  --set-nav-processing-icon: #fbbf24;
  --set-nav-rules-icon: #c4b5fd;
  --set-nav-services-icon: #67e8f9;
  --set-nav-ai-subtitle-icon: #5eead4;
  --set-nav-http-download-icon: #8aaebe;
  --set-nav-baidu-netdisk-icon: #93c5fd;
  --set-nav-maintenance-icon: #fdba74;
  --set-nav-fts-icon: #a5b4fc;
  --set-nav-security-icon: #86efac;
  --set-nav-notification-icon: #f9a8d4;
  --set-shadow: 0 14px 36px rgba(0, 0, 0, 0.24);
  --set-shadow-hover: 0 20px 42px rgba(0, 0, 0, 0.32);
}

/* 移动端紧凑边距 */
@media (max-width: 640px) {
  .settings-page {
    width: 100%;
    max-width: 100vw;
    min-width: 0;
    padding: 8px 10px 16px;
    overflow-x: hidden;
  }
  .set-chip {
    height: 22px;
    padding: 0 8px;
    font-size: 11px;
  }
}

/* ---- 顶栏 chip（AppPageHeader 右侧槽位） ----
   180deg 双段渐变 + inset 1px 顶高光 + 同色微 glow，跟库存页 lib-chip 同源 */
.set-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.set-chip:hover { transform: translateY(-1px) scale(1.04); }

.set-chip-success {
  background: var(--set-success-bg);
  color: var(--set-success-text);
  border-color: var(--set-success-border);
  box-shadow: none;
}

.set-chip-success:hover {
  box-shadow: none;
}

.set-chip-warning {
  background: var(--set-warning-bg);
  color: var(--set-warning-text);
  border-color: var(--set-warning-border);
  box-shadow: none;
}

.set-chip-warning:hover {
  box-shadow: none;
}

.set-chip-info {
  background: var(--set-tag-info-bg);
  color: var(--set-tag-info-text);
  border-color: var(--set-tag-info-border);
  box-shadow: none;
}

.set-chip-info:hover {
  box-shadow: none;
}

@media (max-width: 640px) {
  .set-chip {
    height: 22px;
    padding: 0 8px;
    font-size: 11px;
  }
}
</style>




