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
          <label class="field-card">
            <span class="field-label">库存 ID</span>
            <input v-model="selectedLibrary.id" class="field-input" type="text" placeholder="例如 local-main">
          </label>
          <label class="field-card">
            <span class="field-label">库存名称</span>
            <input v-model="selectedLibrary.name" class="field-input" type="text" placeholder="显示名称">
          </label>
          <label class="field-card">
            <span class="field-label">浏览起始路径</span>
            <input v-model="selectedLibrary.browse_path" class="field-input" type="text" placeholder="留空则从库存路径开始">
          </label>
        </div>

        <label class="field-card block">
          <span class="field-label">说明</span>
          <input v-model="selectedLibrary.description" class="field-input" type="text" placeholder="可选说明">
        </label>

        <template v-if="selectedLibrary.type !== 'synology_filestation'">
          <label class="field-card block">
            <span class="field-label">本地库存路径</span>
            <input v-model="selectedLibrary.path" class="field-input" type="text" placeholder="例如 D:\Prekikoeru\Library">
          </label>
        </template>

        <template v-else>
          <div class="field-grid two">
            <label class="field-card">
              <span class="field-label">连接模板</span>
              <el-select v-model="selectedLibrary.synology_profile_id" placeholder="先选择群晖连接模板" class="field-select" @change="$emit('profile-change', selectedLibrary)">
                <el-option v-for="profile in profiles" :key="profile.id" :label="`${profile.name || profile.id} (${profile.id})`" :value="profile.id" />
              </el-select>
              <span class="field-tip">同一台 NAS 只维护一次连接参数。</span>
            </label>
            <label class="field-card">
              <span class="field-label">远程根目录</span>
              <input v-model="selectedLibrary.synology.root_path" class="field-input" type="text" placeholder="/ASMR" @input="$emit('sync-path', selectedLibrary)">
            </label>
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
          <div class="toggle-card" @click="emitLibraryFlag(selectedLibrary.id, 'enabled', !selectedLibrary.enabled)">
            <span>
              <strong>启用库存</strong>
              <small>关闭后不会出现在主工作台选择里。</small>
            </span>
            <div class="toggle-control" @click.stop>
              <el-switch :model-value="selectedLibrary.enabled" @update:model-value="emitLibraryFlag(selectedLibrary.id, 'enabled', $event)" />
            </div>
          </div>
          <div class="toggle-card" @click="emitLibraryFlag(selectedLibrary.id, 'writable', !selectedLibrary.writable)">
            <span>
              <strong>允许写入</strong>
              <small>远程上传、落盘和分类会使用这个权限。</small>
            </span>
            <div class="toggle-control" @click.stop>
              <el-switch :model-value="selectedLibrary.writable" @update:model-value="emitLibraryFlag(selectedLibrary.id, 'writable', $event)" />
            </div>
          </div>
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
import { Box, FolderPlus, HardDriveDownload, LoaderCircle, PlugZap } from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'

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
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
}

.inventory-list {
  display: grid;
  gap: 12px;
  align-content: start;
}

.library-card,
.create-btn {
  width: 100%;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.88);
  text-align: left;
  cursor: pointer;
}

.library-card.active {
  border-color: rgba(96, 165, 250, 0.55);
  background: rgba(239, 246, 255, 0.92);
}

.library-card.remote {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(240, 253, 244, 0.88));
}

.library-head,
.editor-header,
.editor-actions,
.toggle-row,
.field-grid {
  display: flex;
  gap: 12px;
}

.library-head {
  justify-content: space-between;
  align-items: flex-start;
}

.library-title,
.editor-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.editor-title {
  font-size: 20px;
}

.library-sub,
.editor-desc,
.empty-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.65;
}

.editor-desc {
  margin-top: 8px;
  font-size: 13px;
}

.library-type-pill,
.summary-pill {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.88);
  color: #475569;
  font-size: 11px;
  font-weight: 800;
}

.library-meta,
.library-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  color: #64748b;
  font-size: 12px;
}

.create-row {
  display: grid;
  gap: 10px;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #2563eb;
  font-weight: 800;
}

.create-btn.warn {
  color: #b45309;
}

.inventory-editor {
  min-width: 0;
  padding: 18px;
  border-radius: 24px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.62);
}

.field-grid {
  margin-top: 14px;
}

.field-grid.two > * {
  flex: 1;
}

.field-grid.three > * {
  flex: 1;
}

.field-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.92);
}

.field-card.block {
  margin-top: 14px;
}

.field-label {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.field-input {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: none;
  outline: none;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.95);
  color: #0f172a;
  font-size: 14px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.92);
}

.field-select :deep(.el-select__wrapper) {
  min-height: 42px;
  border-radius: 12px;
}

.field-tip,
.inline-tip {
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.inline-tip.warn {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255, 251, 235, 0.95);
  border: 1px solid rgba(253, 230, 138, 0.9);
  color: #b45309;
}

.toggle-row {
  margin-top: 14px;
}

.toggle-card {
  flex: 1;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.92);
}

.toggle-control {
  position: relative;
  z-index: 2;
  flex-shrink: 0;
  pointer-events: auto;
}

.toggle-control :deep(.el-switch) {
  pointer-events: auto;
}

.toggle-card strong {
  display: block;
  color: #0f172a;
  font-size: 14px;
}

.toggle-card small {
  display: block;
  margin-top: 5px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.bottom {
  margin-top: 14px;
  justify-content: flex-end;
}

.primary-btn,
.ghost-btn,
.link-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.92);
  color: #334155;
  font-size: 13px;
  font-weight: 800;
  text-decoration: none;
  cursor: pointer;
}

.primary-btn {
  background: #0f172a;
  color: #f8fafc;
  border-color: #0f172a;
}

.ghost-btn.danger {
  color: #be123c;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 320px;
  text-align: center;
  color: #64748b;
}

.empty-title {
  margin-top: 14px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
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
  .field-grid,
  .toggle-row,
  .editor-header {
    flex-direction: column;
  }
}
</style>
