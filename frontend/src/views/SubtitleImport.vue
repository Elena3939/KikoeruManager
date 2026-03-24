<template>
  <div class="subtitle-import-page">
    <el-card shadow="never" class="hero-card">
      <div class="hero-head">
        <div>
          <h1 class="page-title">字幕补配</h1>
          <div class="hero-desc">
            正常解压检测到的“关联字幕补配”来源会先出现在这里作为预检单；手头如果只有字幕文件夹，也可以直接在这里补进库存并进入现有 RJ 字幕工作台。
          </div>
        </div>
        <div class="hero-actions">
          <el-button :loading="pendingLoading" @click="loadPendingImports">刷新预检单</el-button>
        </div>
      </div>
    </el-card>

    <el-tabs v-model="activeTab" class="page-tabs">
      <el-tab-pane label="压缩包补配" name="archive">
        <el-row :gutter="18">
          <el-col :xs="24" :lg="9">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="panel-header">
                  <span>自动检测来源</span>
                  <el-tag size="small" type="info">来自正常解压主链路</el-tag>
                </div>
              </template>

              <el-empty v-if="!pendingItems.length && !pendingLoading" description="当前没有待处理的字幕补配预检单" />

              <div v-else class="pending-list">
                <button
                  v-for="item in pendingItems"
                  :key="item.id"
                  type="button"
                  class="pending-item"
                  :class="{ active: item.id === activePendingId }"
                  @click="activePendingId = item.id"
                >
                  <div class="pending-item-head">
                    <strong>{{ item.preview?.target_rjcode || item.preview?.source_rjcode || '未识别 RJ' }}</strong>
                    <el-tag size="small" :type="item.can_execute ? 'success' : 'info'">
                      {{ item.can_execute ? '可执行' : '仅查看' }}
                    </el-tag>
                  </div>
                  <div class="pending-item-title">{{ item.preview?.source_label || getFileName(item.source_path) }}</div>
                  <div class="pending-item-meta">
                    <span>来源 {{ item.preview?.source_rjcode || '-' }}</span>
                    <span>目标 {{ item.preview?.target_rjcode || '-' }}</span>
                    <span>字幕 {{ item.preview?.subtitle_count ?? 0 }}</span>
                  </div>
                  <div class="pending-item-path">{{ item.source_path }}</div>
                </button>
              </div>
            </el-card>
          </el-col>

          <el-col :xs="24" :lg="15">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="panel-header">
                  <span>预检结果</span>
                  <el-tag v-if="activePendingItem" size="small" :type="activePendingItem.can_execute ? 'success' : 'warning'">
                    {{ activePendingItem.can_execute ? '可以补配' : '当前不可执行' }}
                  </el-tag>
                </div>
              </template>

              <el-empty v-if="!activePendingItem" description="先从左侧选择一条自动检测到的预检单" />

              <div v-else class="detail-shell">
                <el-alert
                  :title="activePendingItem.can_execute ? '这条来源可以进入字幕补配' : '这条来源目前只能查看预检结果'"
                  :type="activePendingItem.can_execute ? 'success' : 'warning'"
                  :closable="false"
                  show-icon
                >
                  <template #default>
                    {{ activePendingItem.preview?.reason || '目标原作已定位，可以继续导入并进入库存字幕工作台。' }}
                  </template>
                </el-alert>

                <el-descriptions :column="2" border>
                  <el-descriptions-item label="来源压缩包">{{ activePendingItem.preview?.source_label || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="来源 RJ">{{ activePendingItem.preview?.source_rjcode || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="目标原作 RJ">{{ activePendingItem.preview?.target_rjcode || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="字幕候选数">{{ activePendingItem.preview?.subtitle_count ?? 0 }}</el-descriptions-item>
                  <el-descriptions-item label="Kikoeru 原作命中">
                    <el-tag :type="activePendingItem.preview?.kikoeru_has_subtitle ? 'success' : 'info'">
                      {{ activePendingItem.preview?.kikoeru_has_subtitle ? '已命中原作' : '未命中原作' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="预检时间">{{ formatDate(activePendingItem.created_at) }}</el-descriptions-item>
                </el-descriptions>

                <div v-if="activePendingItem.preview?.subtitle_entries?.length" class="block-box">
                  <div class="section-title">压缩包内检测到的字幕</div>
                  <div class="chip-list">
                    <span
                      v-for="entry in activePendingItem.preview.subtitle_entries.slice(0, 24)"
                      :key="entry"
                      class="entry-chip"
                    >
                      {{ entry }}
                    </span>
                  </div>
                </div>

                <div class="block-box">
                  <div class="section-head">
                    <div>
                      <div class="section-title">目标目录候选</div>
                      <div class="section-tip">单命中会默认选中，多命中时请手动选择；已有字幕的目录不会允许执行。</div>
                    </div>
                    <el-tag size="small" type="info">候选 {{ activePendingItem.preview?.candidate_count ?? 0 }}</el-tag>
                  </div>

                  <el-empty v-if="!activePendingItem.preview?.candidates?.length" description="没有可用的目标目录候选" />

                  <el-radio-group v-else v-model="archiveCandidateSelection[activePendingItem.id]" class="candidate-list">
                    <label
                      v-for="candidate in activePendingItem.preview.candidates"
                      :key="candidateKey(candidate)"
                      class="candidate-item"
                      :class="{ disabled: candidate.has_existing_subtitles }"
                    >
                      <el-radio
                        :label="candidateKey(candidate)"
                        :disabled="candidate.has_existing_subtitles"
                      >
                        <span class="candidate-title">{{ candidate.folder_name || candidate.folder_path }}</span>
                      </el-radio>
                      <div class="candidate-meta">
                        <span>{{ candidate.library_name }}</span>
                        <span>{{ candidate.library_type === 'synology_filestation' ? '远程库' : '本地库' }}</span>
                        <span>音频 {{ candidate.audio_count ?? 0 }}</span>
                        <span>现有字幕 {{ candidate.existing_subtitle_count ?? 0 }}</span>
                        <span>{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="candidate-path">{{ candidate.folder_path }}</div>
                    </label>
                  </el-radio-group>
                </div>

                <div class="action-row">
                  <el-button
                    type="primary"
                    :disabled="!activePendingItem.can_execute || !selectedArchiveCandidate"
                    :loading="executingPendingId === activePendingItem.id"
                    @click="executePendingImport()"
                  >
                    导入并打开字幕工作台
                  </el-button>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="字幕文件夹补配" name="folder">
        <el-row :gutter="18">
          <el-col :xs="24" :lg="10">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="panel-header">
                  <span>手动字幕来源</span>
                  <el-tag size="small" type="warning">保留手动补配入口</el-tag>
                </div>
              </template>

              <el-form label-position="top">
                <el-form-item label="字幕文件夹路径">
                  <el-input
                    v-model="folderPath"
                    clearable
                    placeholder="例如 D:\\Temp\\RJ123456 或其中带 subtitles 子目录"
                    @keyup.enter="previewFolderImport"
                  />
                </el-form-item>
              </el-form>

              <div class="action-row">
                <el-button :loading="folderPreviewLoading" @click="previewFolderImport">预检目标</el-button>
                <el-button
                  type="primary"
                  :loading="folderImporting"
                  :disabled="!canExecuteFolderImport"
                  @click="executeFolderImport"
                >
                  导入并打开字幕工作台
                </el-button>
              </div>

              <el-alert
                title="适用场景"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  手头单独拿到了字幕目录时，可以直接在这里补进原作目录，再进入库存页做筛选、删除和手动配对。
                </template>
              </el-alert>
            </el-card>
          </el-col>

          <el-col :xs="24" :lg="14">
            <el-card shadow="never" class="panel-card">
              <template #header>
                <div class="panel-header">
                  <span>文件夹预检结果</span>
                  <el-tag v-if="folderPreview" size="small" :type="canExecuteFolderImport ? 'success' : 'warning'">
                    {{ canExecuteFolderImport ? '可以补配' : '当前不可执行' }}
                  </el-tag>
                </div>
              </template>

              <el-empty v-if="!folderPreview && !folderPreviewLoading" description="输入字幕文件夹路径后做一次预检" />

              <div v-else-if="folderPreview" class="detail-shell">
                <el-alert
                  :title="canExecuteFolderImport ? '可以执行字幕文件夹补配' : '这份字幕文件夹当前还不能直接补配'"
                  :type="canExecuteFolderImport ? 'success' : 'warning'"
                  :closable="false"
                  show-icon
                >
                  <template #default>
                    {{ folderPreview.reason || '目标原作已定位，可以继续导入并进入库存字幕工作台。' }}
                  </template>
                </el-alert>

                <el-descriptions :column="2" border>
                  <el-descriptions-item label="来源 RJ">{{ folderPreview.source_rjcode || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="目标原作 RJ">{{ folderPreview.target_rjcode || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="来源目录">{{ folderPreview.source_label || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="字幕候选数">{{ folderPreview.subtitle_count ?? 0 }}</el-descriptions-item>
                </el-descriptions>

                <div v-if="folderPreview.subtitle_entries?.length" class="block-box">
                  <div class="section-title">检测到的字幕文件</div>
                  <div class="chip-list">
                    <span
                      v-for="entry in folderPreview.subtitle_entries.slice(0, 24)"
                      :key="entry"
                      class="entry-chip"
                    >
                      {{ entry }}
                    </span>
                  </div>
                </div>

                <div class="block-box">
                  <div class="section-head">
                    <div>
                      <div class="section-title">目标目录候选</div>
                      <div class="section-tip">多命中时请选择正确的原作目录。</div>
                    </div>
                    <el-tag size="small" type="info">候选 {{ folderPreview.candidate_count ?? 0 }}</el-tag>
                  </div>

                  <el-empty v-if="!folderPreview.candidates?.length" description="没有找到目标目录候选" />

                  <el-radio-group v-else v-model="folderCandidateSelection" class="candidate-list">
                    <label
                      v-for="candidate in folderPreview.candidates"
                      :key="candidateKey(candidate)"
                      class="candidate-item"
                      :class="{ disabled: candidate.has_existing_subtitles }"
                    >
                      <el-radio
                        :label="candidateKey(candidate)"
                        :disabled="candidate.has_existing_subtitles"
                      >
                        <span class="candidate-title">{{ candidate.folder_name || candidate.folder_path }}</span>
                      </el-radio>
                      <div class="candidate-meta">
                        <span>{{ candidate.library_name }}</span>
                        <span>{{ candidate.library_type === 'synology_filestation' ? '远程库' : '本地库' }}</span>
                        <span>音频 {{ candidate.audio_count ?? 0 }}</span>
                        <span>现有字幕 {{ candidate.existing_subtitle_count ?? 0 }}</span>
                        <span>{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="candidate-path">{{ candidate.folder_path }}</div>
                    </label>
                  </el-radio-group>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { subtitleImportApi } from '../api'

const router = useRouter()
const SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch (_) {
    return fallback
  }
}

function normalizeSubtitleFilterRule(rule = {}) {
  return {
    target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',
    name: String(rule.name || ''),
    pattern: String(rule.pattern || ''),
    enabled: rule.enabled !== false
  }
}

function sanitizeSubtitleFilterRules(rules = []) {
  return (rules || [])
    .map(rule => normalizeSubtitleFilterRule(rule))
    .filter(rule => rule.pattern.trim())
    .map(rule => ({
      target: rule.target,
      name: rule.name.trim(),
      pattern: rule.pattern.trim(),
      enabled: rule.enabled !== false
    }))
}

function getSubtitleWorkbenchFilterOptions() {
  const saved = loadJson(SUBTITLE_OPTIONS_KEY, {})
  return {
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: sanitizeSubtitleFilterRules(saved?.subtitleFilterRules || [])
  }
}

const activeTab = ref('archive')
const pendingLoading = ref(false)
const pendingItems = ref([])
const activePendingId = ref('')
const executingPendingId = ref('')
const archiveCandidateSelection = reactive({})

const folderPath = ref('')
const folderPreviewLoading = ref(false)
const folderImporting = ref(false)
const folderPreview = ref(null)
const folderCandidateSelection = ref('')

const activePendingItem = computed(() => {
  return pendingItems.value.find(item => item.id === activePendingId.value) || null
})

const selectedArchiveCandidate = computed(() => {
  const item = activePendingItem.value
  if (!item) return null
  const key = archiveCandidateSelection[item.id]
  return (item.preview?.candidates || []).find(candidate => candidateKey(candidate) === key) || null
})

const selectedFolderCandidate = computed(() => {
  return (folderPreview.value?.candidates || []).find(candidate => candidateKey(candidate) === folderCandidateSelection.value) || null
})

const canExecuteFolderImport = computed(() => {
  if (!folderPreview.value) return false
  const readyCount = Number(folderPreview.value.ready_candidate_count || 0)
  if (readyCount <= 0) return false
  return Boolean(selectedFolderCandidate.value)
})

watch(activePendingItem, (item) => {
  if (!item) return
  if (!archiveCandidateSelection[item.id]) {
    const selected = item.preview?.selected_candidate
    if (selected && !selected.has_existing_subtitles) {
      archiveCandidateSelection[item.id] = candidateKey(selected)
      return
    }
    const firstReady = (item.preview?.candidates || []).find(candidate => !candidate.has_existing_subtitles)
    if (firstReady) archiveCandidateSelection[item.id] = candidateKey(firstReady)
  }
}, { immediate: true })

watch(folderPreview, (preview) => {
  if (!preview) {
    folderCandidateSelection.value = ''
    return
  }
  const selected = preview.selected_candidate
  if (selected && !selected.has_existing_subtitles) {
    folderCandidateSelection.value = candidateKey(selected)
    return
  }
  const firstReady = (preview.candidates || []).find(candidate => !candidate.has_existing_subtitles)
  folderCandidateSelection.value = firstReady ? candidateKey(firstReady) : ''
}, { immediate: true })

onMounted(async () => {
  await loadPendingImports()
})

async function loadPendingImports() {
  pendingLoading.value = true
  try {
    const data = await subtitleImportApi.listPending()
    pendingItems.value = data.items || []
    if (!pendingItems.value.some(item => item.id === activePendingId.value)) {
      activePendingId.value = pendingItems.value[0]?.id || ''
    }
  } catch (error) {
    ElMessage.error('加载字幕补配预检单失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    pendingLoading.value = false
  }
}

async function executePendingImport() {
  const item = activePendingItem.value
  const candidate = selectedArchiveCandidate.value
  if (!item || !candidate) return

  executingPendingId.value = item.id
  try {
    const filterOptions = getSubtitleWorkbenchFilterOptions()
    const data = await subtitleImportApi.executePending(item.id, {
      targetLibraryId: candidate.library_id,
      targetFolderPath: candidate.folder_path,
      useFilterRules: filterOptions.useFilterRules,
      subtitleFilterRules: filterOptions.subtitleFilterRules
    })
    ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕补配导入成功，正在进入工作台' : '字幕补配导入成功')
    await loadPendingImports()
    if (data.task?.id) {
      openImportedTask(data.task.id)
    }
  } catch (error) {
    ElMessage.error('执行字幕补配失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    executingPendingId.value = ''
  }
}

async function previewFolderImport() {
  const path = folderPath.value.trim()
  if (!path) {
    ElMessage.warning('请先输入字幕文件夹路径')
    return
  }

  folderPreviewLoading.value = true
  try {
    const data = await subtitleImportApi.previewFolder(path)
    folderPreview.value = data.preview || data
    ElMessage.success('字幕文件夹预检完成')
  } catch (error) {
    folderPreview.value = null
    ElMessage.error('字幕文件夹预检失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderPreviewLoading.value = false
  }
}

async function executeFolderImport() {
  const path = folderPath.value.trim()
  const candidate = selectedFolderCandidate.value
  if (!path || !candidate) return

  folderImporting.value = true
  try {
    const filterOptions = getSubtitleWorkbenchFilterOptions()
    const data = await subtitleImportApi.importFolder(path, {
      targetLibraryId: candidate.library_id,
      targetFolderPath: candidate.folder_path,
      useFilterRules: filterOptions.useFilterRules,
      subtitleFilterRules: filterOptions.subtitleFilterRules
    })
    ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕文件夹补配成功，正在进入工作台' : '字幕文件夹补配成功')
    if (data.task?.id) {
      openImportedTask(data.task.id)
    }
  } catch (error) {
    ElMessage.error('执行字幕文件夹补配失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderImporting.value = false
  }
}

function openImportedTask(taskId) {
  router.push({
    path: '/library',
    query: {
      subtitleDialog: '1',
      subtitleImport: '1',
      subtitleTaskId: taskId
    }
  })
}

function candidateKey(candidate) {
  return `${candidate.library_id || ''}::${candidate.folder_path || ''}`
}

function getFileName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatSize(size) {
  const value = Number(size || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const result = value / (1024 ** exponent)
  return `${result >= 100 || exponent === 0 ? result.toFixed(0) : result.toFixed(1)} ${units[exponent]}`
}
</script>

<style scoped>
.subtitle-import-page {
  display: grid;
  gap: 18px;
}

.hero-card,
.panel-card {
  border: none;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.97) 0%, #ffffff 100%);
  box-shadow: 0 16px 36px rgba(31, 46, 67, 0.08);
}

.hero-head,
.panel-header,
.section-head,
.action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.page-title {
  margin: 0;
  font-size: 32px;
  line-height: 1.2;
  color: #20344d;
}

.hero-desc {
  margin-top: 10px;
  max-width: 900px;
  font-size: 14px;
  line-height: 1.75;
  color: #5d718a;
}

.pending-list,
.detail-shell,
.candidate-list {
  display: grid;
  gap: 12px;
}

.pending-item,
.candidate-item {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border: 1px solid #e6edf6;
  border-radius: 16px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.pending-item:hover,
.candidate-item:hover {
  border-color: #bfd4f6;
  box-shadow: 0 10px 24px rgba(59, 88, 135, 0.08);
  transform: translateY(-1px);
}

.pending-item.active {
  border-color: #9fc4ff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.08);
}

.pending-item-head,
.pending-item-meta,
.candidate-meta,
.chip-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pending-item-title,
.candidate-title,
.section-title {
  font-weight: 700;
  color: #24364f;
}

.pending-item-meta,
.pending-item-path,
.candidate-meta,
.candidate-path,
.section-tip {
  font-size: 12px;
  line-height: 1.6;
  color: #71839b;
}

.block-box {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid #e8eef6;
  background: #fbfcfe;
}

.entry-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: #eef4ff;
  color: #31599b;
  font-size: 12px;
}

.candidate-item.disabled {
  cursor: not-allowed;
  background: #f7f8fa;
  opacity: 0.72;
}

@media (max-width: 992px) {
  .page-title {
    font-size: 28px;
  }
}
</style>
