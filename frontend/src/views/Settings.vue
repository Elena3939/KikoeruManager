<template>
  <div class="settings-page">
    <AppPageHeader
      :icon="IconSettings"
      icon-color="#4f46e5"
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
        description="集中维护 Kikoeru、ASMR 下载和 RJ 字幕抓取等远程链路。"
      >
        <ServicesSettingsPanel :config="config" />
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
import { Bell, Boxes, HardDrive, LifeBuoy, ScanSearch, ShieldCheck, TextSearch, Workflow, Settings2 as IconSettings, AlertCircle as IconAlertCircle, CheckCircle2 as IconCheckCircle2, Clock as IconClock } from 'lucide-vue-next'
import SettingsSectionPanel from '../components/settings/SettingsSectionPanel.vue'
import SettingsWorkbench from '../components/settings/SettingsWorkbench.vue'
import StorageSettingsPanel from '../components/settings/StorageSettingsPanel.vue'
import ProcessingSettingsPanel from '../components/settings/ProcessingSettingsPanel.vue'
import RulesSettingsPanel from '../components/settings/RulesSettingsPanel.vue'
import ServicesSettingsPanel from '../components/settings/ServicesSettingsPanel.vue'
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
  resetAllConfig
} = useSettingsDraft({ sectionKeyMap })

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
  { id: 'services', title: '外部服务', short: 'Kikoeru、ASMR、RJ 字幕', icon: ScanSearch, keywords: ['kikoeru', 'asmr', 'subtitle', '外部服务'] },
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
  max-width: 1480px;
  margin: 0 auto;
  padding: 16px;
  color: #1d1d1f;
  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
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
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
  border-color: rgba(110, 231, 183, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.set-chip-success:hover {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 10px -2px rgba(16, 185, 129, 0.28);
}

.set-chip-warning {
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  color: #b45309;
  border-color: rgba(251, 191, 36, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(245, 158, 11, 0.12);
}

.set-chip-warning:hover {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 10px -2px rgba(245, 158, 11, 0.3);
}

.set-chip-info {
  background: linear-gradient(180deg, #eef2ff 0%, #e0e7ff 100%);
  color: #4338ca;
  border-color: rgba(165, 180, 252, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(99, 102, 241, 0.12);
}

.set-chip-info:hover {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 10px -2px rgba(99, 102, 241, 0.3);
}

@media (max-width: 640px) {
  .set-chip {
    height: 22px;
    padding: 0 8px;
    font-size: 11px;
  }
}
</style>
