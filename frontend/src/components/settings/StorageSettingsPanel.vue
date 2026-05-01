<template>
  <div class="storage-stack">
    <div class="paths-grid">
      <label v-for="item in pathCards" :key="item.key" class="path-card">
        <span class="path-label">{{ item.label }}</span>
        <input v-model="modelValue.storage[item.key]" class="path-input" type="text" :placeholder="item.placeholder">
        <span class="path-tip">{{ item.tip }}</span>
      </label>
    </div>

    <div class="defaults-grid">
      <label class="field-card">
        <span class="field-label">默认浏览库存</span>
        <el-select v-model="modelValue.storage.default_library_id" class="field-select">
          <el-option v-for="library in enabledLibraries" :key="library.id" :label="`${library.name} (${library.id})`" :value="library.id" />
        </el-select>
      </label>
      <label class="field-card">
        <span class="field-label">默认解压目标库存</span>
        <el-select v-model="modelValue.storage.default_extract_library_id" class="field-select">
          <el-option v-for="library in enabledLibraries" :key="`extract-${library.id}`" :label="`${library.name} (${library.id})`" :value="library.id" />
        </el-select>
      </label>
      <label class="field-card">
        <span class="field-label">剩余空间预警（GB）</span>
        <el-input-number v-model="modelValue.storage.health_warning_free_gb" :min="0" :step="10" class="field-number" />
      </label>
      <label class="field-card">
        <span class="field-label">统计缓存秒数</span>
        <el-input-number v-model="modelValue.storage.stats_cache_ttl_seconds" :min="30" :step="30" class="field-number" />
      </label>
    </div>

    <div class="sub-panels">
      <div class="sub-panel">
        <div class="sub-panel-head">
          <div>
            <div class="sub-panel-title">群晖连接中心</div>
            <div class="sub-panel-desc">一台 NAS 只维护一份连接参数，多个共享目录库存统一复用。</div>
          </div>
        </div>
        <SynologyProfileCenter
          :profile="resolvedPrimaryProfile"
          :profile-summary="primaryProfileSummary"
          :testing-profile-id="testingProfileId"
          @test-profile="$emit('test-profile', $event)"
          @update-profile-flag="$emit('update-profile-flag', $event)"
        />
      </div>

      <div class="sub-panel">
        <div class="sub-panel-head">
          <div>
            <div class="sub-panel-title">库存工作台</div>
            <div class="sub-panel-desc">本地库存和群晖共享目录都在这里管理。远程库存只描述目录用途，不再重复维护连接参数。</div>
          </div>
        </div>
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
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import LibraryInventoryPanel from './LibraryInventoryPanel.vue'
import SynologyProfileCenter from './SynologyProfileCenter.vue'

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
  { key: 'input_path', label: '待处理目录', placeholder: '例如 D:\\Prekikoeru\\Input', tip: '自动扫描和手动导入默认从这里开始。' },
  { key: 'temp_path', label: '临时目录', placeholder: '例如 D:\\Prekikoeru\\Temp', tip: '解压、下载和中转文件优先写到这里。' },
  { key: 'library_path', label: '主库存目录（旧版兼容）', placeholder: '例如 D:\\Prekikoeru\\Library', tip: '⚠ 仅在"库存工作台"中没有本地库存条目时才会生效。若已在下方库存工作台配置了本地库存，请直接在那里修改路径，此字段不会覆盖它。' },
  { key: 'processed_archives_path', label: '已处理压缩包目录', placeholder: '例如 D:\\Prekikoeru\\Processed', tip: '处理完成后的压缩包归档目录。' },
  { key: 'existing_folders_path', label: '已有文件夹目录', placeholder: '例如 D:\\Prekikoeru\\Existing', tip: '处理非软件解压来源的目录时优先使用。' },
  { key: 'asmr_subtitle_path', label: 'ASMR 字幕目录', placeholder: '例如 D:\\Prekikoeru\\Subtitles', tip: 'ASMR 同步链路默认使用的字幕目录。' }
]

const enabledLibraries = computed(() => (props.modelValue.storage?.libraries || []).filter(item => item.enabled))
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
.storage-stack,
.sub-panels {
  display: grid;
  gap: 22px;
}

.paths-grid,
.defaults-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.path-card,
.field-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.9);
}

.path-label,
.field-label {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.path-input {
  width: 100%;
  min-height: 46px;
  padding: 0 14px;
  border: none;
  outline: none;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  color: #0f172a;
  font-size: 14px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.92);
}

.path-tip {
  color: #64748b;
  font-size: 12px;
  line-height: 1.65;
}

.field-select :deep(.el-select__wrapper),
.field-number :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 14px;
}

.sub-panel {
  padding: 20px;
  border-radius: 26px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(255, 255, 255, 0.95));
}

.sub-panel-head {
  margin-bottom: 16px;
}

.sub-panel-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 800;
}

.sub-panel-desc {
  margin-top: 8px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 960px) {
  .paths-grid,
  .defaults-grid {
    grid-template-columns: 1fr;
  }
}
</style>
