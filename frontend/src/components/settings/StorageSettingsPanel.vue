<template>
  <div class="storage-stack">
    <!-- 分组卡片 1：默认目录 —— 6 个路径字段合到一张大卡里，二列 grid + 行内字段块 -->
    <section class="storage-card">
      <header class="storage-card-head">
        <h3 class="storage-card-title">默认目录</h3>
        <p class="storage-card-desc">扫描、解压、下载、归档链路的默认落盘位置。</p>
      </header>
      <div class="storage-fields-grid">
        <SettingsFieldCard v-for="item in pathCards" :key="item.key" :label="item.label" :hint="item.tip">
          <input v-model="modelValue.storage[item.key]" class="storage-field-input" type="text" :placeholder="item.placeholder">
        </SettingsFieldCard>
      </div>
    </section>

    <!-- 分组卡片 2：默认库存与容量 -->
    <section class="storage-card">
      <header class="storage-card-head">
        <h3 class="storage-card-title">默认库存与容量</h3>
        <p class="storage-card-desc">默认浏览 / 解压落盘库存、空间预警阈值和统计缓存时间。</p>
      </header>
      <div class="storage-fields-grid">
        <SettingsFieldCard label="默认浏览库存">
          <AppDropdown
            v-model="modelValue.storage.default_library_id"
            :options="libraryDropdownOptions"
            placeholder="选择默认浏览库存"
            class="settings-field-dd"
          />
        </SettingsFieldCard>
        <SettingsFieldCard label="默认解压目标库存">
          <AppDropdown
            v-model="modelValue.storage.default_extract_library_id"
            :options="libraryDropdownOptions"
            placeholder="选择默认解压库存"
            class="settings-field-dd"
          />
        </SettingsFieldCard>
        <SettingsFieldCard label="剩余空间预警（GB）">
          <el-input-number v-model="modelValue.storage.health_warning_free_gb" :min="0" :step="10" class="storage-field-number" />
        </SettingsFieldCard>
        <SettingsFieldCard label="统计缓存秒数">
          <el-input-number v-model="modelValue.storage.stats_cache_ttl_seconds" :min="30" :step="30" class="storage-field-number" />
        </SettingsFieldCard>
      </div>
    </section>

    <!-- 分组卡片 3：群晖连接中心 -->
    <section class="storage-card">
      <header class="storage-card-head">
        <h3 class="storage-card-title">群晖连接中心</h3>
        <p class="storage-card-desc">一台 NAS 只维护一份连接参数，多个共享目录库存统一复用。</p>
      </header>
      <SynologyProfileCenter
        :profile="resolvedPrimaryProfile"
        :profile-summary="primaryProfileSummary"
        :testing-profile-id="testingProfileId"
        @test-profile="$emit('test-profile', $event)"
        @update-profile-flag="$emit('update-profile-flag', $event)"
      />
    </section>

    <!-- 分组卡片 4：库存工作台 -->
    <section class="storage-card">
      <header class="storage-card-head">
        <h3 class="storage-card-title">库存工作台</h3>
        <p class="storage-card-desc">本地库存和群晖共享目录都在这里管理。远程库存只描述目录用途，不再重复维护连接参数。</p>
      </header>
      <LibraryInventoryPanel
        :libraries="libraries"
        :profiles="profiles"
        :selected-library-id="selectedLibraryId"
        :testing-library-id="testingLibraryId"
        :build-synology-web-url="buildSynologyWebUrl"
        :get-library-view-model="getLibraryViewModel"
        @select-library="$emit('select-library', $event)"
        @create-library="$emit('create-library', $event)"
        @remove-library="$emit('remove-library', $event)"
        @test-library="$emit('test-library', $event)"
        @extract-profile="$emit('extract-profile', $event)"
        @update-library-flag="$emit('update-library-flag', $event)"
        @profile-change="$emit('profile-change', $event)"
        @sync-path="$emit('sync-path', $event)"
      />
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import LibraryInventoryPanel from './LibraryInventoryPanel.vue'
import SynologyProfileCenter from './SynologyProfileCenter.vue'
import SettingsFieldCard from './SettingsFieldCard.vue'
import AppDropdown from '../common/AppDropdown.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  profiles: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  primaryProfile: { type: Object, default: null },
  profileSummaries: { type: Array, default: () => [] },
  libraryViewModels: { type: Array, default: () => [] },
  getProfileSummary: { type: Function, required: true },
  getLibraryViewModel: { type: Function, required: true },
  selectedLibraryId: { type: String, default: '' },
  testingProfileId: { type: String, default: '' },
  testingLibraryId: { type: String, default: '' },
  buildSynologyWebUrl: { type: Function, required: true }
})

defineEmits([
  'select-library',
  'test-profile',
  'create-library',
  'remove-library',
  'test-library',
  'extract-profile',
  'update-profile-flag',
  'update-library-flag',
  'profile-change',
  'sync-path'
])

const pathCards = [
  { key: 'input_path', label: '待处理目录', placeholder: '例如 D:\\KikoeruManager\\Input', tip: '自动扫描和手动导入默认从这里开始。' },
  { key: 'temp_path', label: '临时目录', placeholder: '例如 D:\\KikoeruManager\\Temp', tip: '解压、下载和中转文件优先写到这里。' },
  { key: 'library_path', label: '主库存目录（旧版兼容）', placeholder: '例如 D:\\KikoeruManager\\Library', tip: '⚠ 仅在"库存工作台"中没有本地库存条目时才会生效。若已在下方库存工作台配置了本地库存，请直接在那里修改路径，此字段不会覆盖它。' },
  { key: 'processed_archives_path', label: '已处理压缩包目录', placeholder: '例如 D:\\KikoeruManager\\Processed', tip: '处理完成后的压缩包归档目录。' },
  { key: 'existing_folders_path', label: '已有文件夹目录', placeholder: '例如 D:\\KikoeruManager\\Existing', tip: '处理非软件解压来源的目录时优先使用。' },
  { key: 'asmr_subtitle_path', label: 'ASMR 字幕目录', placeholder: '例如 D:\\KikoeruManager\\Subtitles', tip: 'ASMR 同步链路默认使用的字幕目录。' }
]

const enabledLibraries = computed(() => (props.modelValue.storage?.libraries || []).filter(item => item.enabled))
const libraryDropdownOptions = computed(() => enabledLibraries.value.map(library => ({
  value: library.id,
  label: `${library.name || library.id} (${library.id})`
})))
const resolvedPrimaryProfile = computed(() => props.primaryProfile || props.profiles[0] || {
  id: 'synology-main',
  name: '主群晖连接',
  base_url: '',
  username: '',
  password: '',
  otp_code: '',
  device_name: '',
  device_id: '',
  enable_device_token: true,
  session_name: 'FileStation',
  timeout: 30,
  verify_ssl: true,
  linkedCount: 0,
  hasDeviceToken: false
})
const primaryProfileSummary = computed(() => props.getProfileSummary(resolvedPrimaryProfile.value, 1))
</script>

<style scoped>
/* 去 hairline 边、去卡边，分组与字段全靠空间节奏划分 */
.storage-stack {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.storage-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
}

.storage-card-head {
  margin-bottom: 14px;
  padding-bottom: 0;
  border-bottom: none;
}

.storage-card-title {
  margin: 0;
  color: #1d1d1f;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.storage-card-desc {
  margin: 4px 0 0;
  color: rgba(29, 29, 31, 0.55);
  font-size: 12px;
  line-height: 1.6;
}

/* 二列 grid 字段块；SettingsFieldCard 已提供 label + hint 排版，外层 grid 只负责行列。
 *  align-items: start 避免 stretch 拉伸导致 EP 控件内部出滚动条。 */
.storage-fields-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  align-items: start;
}

.storage-field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  outline: none;
  border-radius: 10px;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13.5px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.storage-field-input:hover { border-color: rgba(148, 163, 184, 0.75); }

.storage-field-input:focus {
  border-color: rgba(79, 70, 229, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.storage-field-input::placeholder { color: #94a3b8; }

/* el-input-number 与 input 视觉对齐：38px 高 / 10px 圆角 / 同色边 / 同色 focus ring */
.storage-field-number :deep(.el-input__wrapper) {
  min-height: 38px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: none;
  border: 1px solid rgba(226, 232, 240, 0.85) !important;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.storage-field-number :deep(.el-input__wrapper:hover) {
  border-color: rgba(148, 163, 184, 0.75) !important;
}

.storage-field-number :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(79, 70, 229, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
}

/* AppDropdown 收敛：撑满 SettingsFieldCard 控件槽 + 38px 高 / 10px 圆角，与 input 视觉对齐 */
.settings-field-dd {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-root) {
  display: block;
  width: 100%;
}

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) {
  border-color: rgba(148, 163, 184, 0.75);
}

.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: rgba(79, 70, 229, 0.55);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

@media (max-width: 960px) {
  .storage-fields-grid {
    grid-template-columns: 1fr;
  }
}
</style>
