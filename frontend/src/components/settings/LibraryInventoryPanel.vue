<template>
  <div class="inventory-panel">
    <div class="inventory-list">
      <button
        v-for="library in libraryCards"
        :key="library.id"
        type="button"
        class="library-card"
        :class="{ active: selectedLibraryId === library.id, remote: library.isRemote }"
        @click="$emit('select-library', library.id)"
      >
        <div class="library-head">
          <div>
            <div class="library-title">{{ library.name || library.id }}</div>
            <div class="library-sub">{{ library.isRemote ? '群晖共享目录实例' : '本地库存目录' }}</div>
          </div>
          <span class="library-type-pill">{{ library.isRemote ? '远程' : '本地' }}</span>
        </div>
        <div class="library-meta">
          <span>{{ library.id }}</span>
          <span>{{ library.enabled ? '启用中' : '已停用' }}</span>
          <span v-if="library.isRemote">{{ library.profileName || '未绑定模板' }}</span>
        </div>
      </button>

      <div class="create-row">
        <button type="button" class="create-btn" @click="$emit('create-library', 'local')">
          <FolderPlus :size="16" :stroke-width="2.4" />
          添加本地库存
        </button>
        <button type="button" class="create-btn warn" @click="$emit('create-library', 'synology_filestation')">
          <HardDriveDownload :size="16" :stroke-width="2.4" />
          添加群晖库存
        </button>
      </div>
    </div>

    <div class="inventory-editor">
      <template v-if="selectedLibrary">
        <div class="editor-header">
          <div>
            <div class="editor-title">{{ selectedLibrary.name || '未命名库存' }}</div>
            <div class="editor-desc">
              {{ selectedLibrary.type === 'synology_filestation' ? '远程库存只描述共享目录用途，NAS 连接信息统一复用模板。' : '本地库存只维护本机目录路径和浏览入口。' }}
            </div>
          </div>
          <div class="editor-actions">
            <button type="button" class="ghost-btn danger" @click="$emit('remove-library', selectedLibraryIndex)">删除库存</button>
          </div>
        </div>

        <div class="field-grid three">
          <SettingsFieldCard label="库存 ID">
            <input v-model="selectedLibrary.id" class="lib-input" type="text" placeholder="例如 local-main">
          </SettingsFieldCard>
          <SettingsFieldCard label="库存名称">
            <input v-model="selectedLibrary.name" class="lib-input" type="text" placeholder="显示名称">
          </SettingsFieldCard>
          <SettingsFieldCard label="浏览起始路径">
            <input v-model="selectedLibrary.browse_path" class="lib-input" type="text" placeholder="留空则从库存路径开始">
          </SettingsFieldCard>
        </div>

        <SettingsFieldCard label="说明">
          <input v-model="selectedLibrary.description" class="lib-input" type="text" placeholder="可选说明">
        </SettingsFieldCard>

        <template v-if="selectedLibrary.type !== 'synology_filestation'">
          <SettingsFieldCard label="本地库存路径">
            <input v-model="selectedLibrary.path" class="lib-input" type="text" placeholder="例如 D:\Prekikoeru\Library">
          </SettingsFieldCard>
        </template>

        <template v-else>
          <div class="field-grid two">
            <SettingsFieldCard label="连接模板" hint="同一台 NAS 只维护一次连接参数。">
              <AppDropdown
                v-model="selectedLibrary.synology_profile_id"
                :options="profileDropdownOptions"
                placeholder="先选择群晖连接模板"
                class="settings-field-dd"
                @update:model-value="$emit('profile-change', selectedLibrary)"
              />
            </SettingsFieldCard>
            <SettingsFieldCard label="远程根目录">
              <input v-model="selectedLibrary.synology.root_path" class="lib-input" type="text" placeholder="/ASMR" @input="$emit('sync-path', selectedLibrary)">
            </SettingsFieldCard>
          </div>

          <div v-if="selectedLibrary.type === 'synology_filestation' && !selectedLibrary.synology_profile_id" class="inline-tip warn">当前远程库存还没绑定连接模板，先选模板再做目录访问测试。</div>

          <div class="library-summary">
            <span class="summary-pill">{{ selectedLibraryView?.profileName || '未绑定模板' }}</span>
            <span class="summary-pill">{{ selectedLibraryView?.effectiveSynology?.base_url || '未填群晖地址' }}</span>
            <span class="summary-pill">{{ selectedLibraryView?.effectiveSynology?.device_id ? '设备令牌已存在' : '可能需要 OTP' }}</span>
          </div>

          <div class="editor-actions bottom">
            <button type="button" class="ghost-btn" @click="$emit('extract-profile', selectedLibrary)">提取为模板</button>
            <a v-if="buildSynologyWebUrl(selectedLibrary)" class="ghost-btn link-btn" :href="buildSynologyWebUrl(selectedLibrary)" target="_blank">打开群晖目录</a>
            <button
              type="button"
              class="primary-btn"
              :disabled="testingLibraryId === selectedLibrary.id || (selectedLibrary.type === 'synology_filestation' && !selectedLibrary.synology_profile_id)"
              @click="$emit('test-library', selectedLibrary)"
            >
              <LoaderCircle v-if="testingLibraryId === selectedLibrary.id" :size="15" :stroke-width="2.5" class="spinning" />
              <PlugZap v-else :size="15" :stroke-width="2.5" />
              测试目录访问
            </button>
          </div>
        </template>

        <div class="toggle-row">
          <SettingsToggleRow
            :model-value="selectedLibrary.enabled"
            title="启用库存"
            subtitle="关闭后不会出现在主工作台选择里。"
            @update:model-value="emitLibraryFlag(selectedLibrary.id, 'enabled', $event)"
          />
          <SettingsToggleRow
            :model-value="selectedLibrary.writable"
            title="允许写入"
            subtitle="远程上传、落盘和分类会使用这个权限。"
            @update:model-value="emitLibraryFlag(selectedLibrary.id, 'writable', $event)"
          />
        </div>
      </template>

      <AppEmptyState v-else description="先选一个库存" size="default">
        <p class="text-xs text-slate-400 mt-1">本地库存和群晖共享目录都在这里统一管理。</p>
      </AppEmptyState>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FolderPlus, HardDriveDownload, LoaderCircle, PlugZap } from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import AppDropdown from '../common/AppDropdown.vue'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'

const props = defineProps({
  libraries: { type: Array, default: () => [] },
  profiles: { type: Array, default: () => [] },
  selectedLibraryId: { type: String, default: '' },
  testingLibraryId: { type: String, default: '' },
  buildSynologyWebUrl: { type: Function, required: true },
  getLibraryViewModel: { type: Function, required: true }
})

const emit = defineEmits([
  'select-library',
  'create-library',
  'remove-library',
  'test-library',
  'extract-profile',
  'update-library-flag',
  'profile-change',
  'sync-path'
])

const libraryCards = computed(() => props.libraries.map((library, index) => props.getLibraryViewModel(library, index + 1)))
const selectedLibraryIndex = computed(() => props.libraries.findIndex(item => item.id === props.selectedLibraryId))
const selectedLibrary = computed(() => props.libraries[selectedLibraryIndex.value] || null)
const profileDropdownOptions = computed(() => props.profiles.map(profile => ({
  value: profile.id,
  label: `${profile.name || profile.id} (${profile.id})`
})))
const selectedLibraryView = computed(() => {
  if (!selectedLibrary.value) return null
  return props.getLibraryViewModel(selectedLibrary.value, selectedLibraryIndex.value + 1)
})

function emitLibraryFlag(libraryId, key, value) {
  emit('update-library-flag', { libraryId, key, value })
}
</script>

<style scoped>
.inventory-panel {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.inventory-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-content: start;
}

/* 库存列表项保留卡感（列表项需要明确可点击边界），但圆角从 22 降到 12，背景白底 + hairline 边 */
.library-card,
.create-btn {
  width: 100%;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.library-card:hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.75);
  box-shadow: 0 4px 12px -4px rgba(15, 23, 42, 0.08);
}

.library-card.active {
  border-color: rgba(99, 102, 241, 0.55);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.85) 0%, rgba(255, 255, 255, 0.96) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 12px -4px rgba(79, 70, 229, 0.18);
}

.library-card.remote {
  background: linear-gradient(135deg, rgba(240, 253, 244, 0.6) 0%, rgba(255, 255, 255, 0.96) 100%);
}

.library-card.remote.active {
  background: linear-gradient(135deg, rgba(220, 252, 231, 0.85) 0%, rgba(255, 255, 255, 0.96) 100%);
  border-color: rgba(110, 231, 183, 0.55);
}

.library-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.library-title {
  color: #1d1d1f;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.05px;
}

.editor-title {
  color: #1d1d1f;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.2px;
}

.library-sub {
  margin-top: 2px;
  color: rgba(29, 29, 31, 0.55);
  font-size: 11.5px;
  line-height: 1.5;
}

.editor-desc,
.empty-desc {
  color: rgba(29, 29, 31, 0.55);
  font-size: 12.5px;
  line-height: 1.6;
}

.editor-desc { margin-top: 4px; }

/* type-pill / summary-pill 对齐 lib-chip 风：180deg 渐变 + inset 顶高光 + 微 glow */
.library-type-pill,
.summary-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  color: #475569;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.01em;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(15, 23, 42, 0.04);
}

.library-meta,
.library-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  color: rgba(29, 29, 31, 0.55);
  font-size: 11.5px;
}

.create-row {
  display: grid;
  gap: 8px;
  margin-top: 4px;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 14px;
  color: #4f46e5;
  font-weight: 500;
  font-size: 12.5px;
}

.create-btn:hover {
  border-color: rgba(99, 102, 241, 0.55);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.85) 0%, #ffffff 100%);
}

.create-btn.warn { color: #d97706; }

.create-btn.warn:hover {
  border-color: rgba(251, 191, 36, 0.55);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.85) 0%, #ffffff 100%);
}

/* 右侧编辑区去火火灰底大卡，内容直接铺在外层白底上 */
.inventory-editor {
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  border-radius: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 字段网格：二列 / 三列 grid，SettingsFieldCard 负责控件槽、label、hint排版 */
.field-grid {
  display: grid;
  gap: 14px 18px;
  align-items: start;
  margin-top: 0;
}

.field-grid.two   { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }

/* SettingsFieldCard 默认 slot 里裸 input 的统一外观 */
.lib-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  outline: none;
  border-radius: 10px;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13.5px;
  box-shadow: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.lib-input:hover { border-color: rgba(148, 163, 184, 0.75); }

.lib-input:focus {
  border-color: rgba(79, 70, 229, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.lib-input::placeholder { color: #94a3b8; }

/* AppDropdown 收敛：撑满 SettingsFieldCard 控件槽 + 38px 高 / 10px 圆角 */
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

.inline-tip {
  color: rgba(29, 29, 31, 0.5);
  font-size: 11.5px;
  line-height: 1.55;
}

.inline-tip.warn {
  padding: 10px 12px;
  border-radius: 10px;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  border: 1px solid rgba(251, 191, 36, 0.55);
  color: #b45309;
  font-size: 12px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(245, 158, 11, 0.1);
}

/* toggle 行外层 grid：SettingsToggleRow 负责行内颜值，外层只负责二列排列 */
.toggle-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  align-items: start;
  margin-top: 4px;
}

.bottom { margin-top: 0; justify-content: flex-end; }

/* 主按钮：AGENTS.md 三段黑色渐变 + inset 顶高光 + 双层 glow */
.primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: 10px;
  color: #ffffff;
  background: linear-gradient(180deg, #1f2937 0%, #0f172a 60%, #020617 100%);
  border: 1px solid #0f172a;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 6px 16px -6px rgba(2, 6, 23, 0.55),
    0 2px 4px rgba(15, 23, 42, 0.25);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.primary-btn:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 14px 28px -10px rgba(2, 6, 23, 0.6),
    0 4px 8px rgba(15, 23, 42, 0.3);
}

.primary-btn:not(:disabled):active {
  transform: translateY(0) scale(0.97);
}

.primary-btn:disabled { opacity: 0.55; cursor: not-allowed; }

/* ghost / link 按钮：白底 + hairline 边 + hover 微上抬 */
.ghost-btn,
.link-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ghost-btn:not(:disabled):hover,
.link-btn:hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.75);
  background: rgba(248, 250, 252, 0.85);
  color: #1d1d1f;
}

.ghost-btn.danger { color: #e11d48; border-color: rgba(244, 63, 94, 0.4); }

.ghost-btn.danger:hover {
  background: linear-gradient(135deg, rgba(254, 226, 226, 0.6) 0%, #ffffff 100%);
  border-color: rgba(244, 63, 94, 0.7);
  color: #be123c;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 240px;
  text-align: center;
  color: rgba(29, 29, 31, 0.55);
}

.empty-title {
  margin-top: 12px;
  color: #1d1d1f;
  font-size: 14px;
  font-weight: 600;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1200px) {
  .inventory-panel {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .field-grid.two,
  .field-grid.three,
  .toggle-row { grid-template-columns: 1fr; }
  .editor-header { flex-direction: column; }
}
</style>
