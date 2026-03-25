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

                <div v-if="canRetryActivePendingPreview" class="alert-actions">
                  <el-button
                    size="small"
                    text
                    :loading="retryingPendingId === activePendingItem.id"
                    @click="retryActivePendingPreview"
                  >
                    重试远程搜索
                  </el-button>
                </div>

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
                      {{ formatSubtitleEntryDisplay(entry) }}
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
                    >
                      <el-radio
                        :label="candidateKey(candidate)"
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

                <div v-if="canRetryFolderPreview" class="alert-actions">
                  <el-button
                    size="small"
                    text
                    :loading="folderPreviewLoading"
                    @click="previewFolderImport"
                  >
                    重新检查目标目录
                  </el-button>
                </div>

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
                      {{ formatSubtitleEntryDisplay(entry) }}
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
                    >
                      <el-radio
                        :label="candidateKey(candidate)"
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

    <SubtitleImportWorkbench
      v-if="activeWorkbenchTaskId"
      :task-id="activeWorkbenchTaskId"
      @clear-task="clearImportWorkbench"
      @task-finished="handleWorkbenchTaskFinished"
      @select-task="openImportedTask"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { rjSubtitleApi, subtitleImportApi } from '../api'
import SubtitleImportWorkbench from '../components/subtitle-import/SubtitleImportWorkbench.vue'

const route = useRoute()
const router = useRouter()
const SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'
const SUBTITLE_IMPORT_WORKBENCH_TASK_KEY = 'kikoeru.ui.subtitleImport.activeTaskId'

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

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function formatSubtitleEntryDisplay(entry = '') {
  const normalized = String(entry || '').replace(/\\/g, '/')
  if (!normalized) return ''
  const parts = normalized.split('/')
  const fileName = parts.pop() || ''
  const extMatch = fileName.match(/\.[^.]+$/)
  const subtitleExt = extMatch?.[0] || ''
  const baseName = subtitleExt ? fileName.slice(0, -subtitleExt.length) : fileName
  const cleanedFileName = `${stripTrailingAudioExtension(baseName)}${subtitleExt}`
  return [...parts, cleanedFileName].filter(Boolean).join('/')
}

function getSubtitleWorkbenchFilterOptions() {
  const saved = loadJson(SUBTITLE_OPTIONS_KEY, {})
  return {
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: sanitizeSubtitleFilterRules(saved?.subtitleFilterRules || [])
  }
}

function persistWorkbenchTaskId(taskId = '') {
  try {
    if (taskId) localStorage.setItem(SUBTITLE_IMPORT_WORKBENCH_TASK_KEY, String(taskId))
    else localStorage.removeItem(SUBTITLE_IMPORT_WORKBENCH_TASK_KEY)
  } catch (_) {}
}

function readPersistedWorkbenchTaskId() {
  try {
    return String(localStorage.getItem(SUBTITLE_IMPORT_WORKBENCH_TASK_KEY) || '')
  } catch (_) {
    return ''
  }
}

function isPendingLinkedSubtitleWorkbenchTask(task = {}) {
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  return (
    ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode) &&
    task?.awaiting_manual_match &&
    !task?.manual_match_completed
  )
}

const activeTab = ref('archive')
const pendingLoading = ref(false)
const pendingItems = ref([])
const activePendingId = ref('')
const executingPendingId = ref('')
const retryingPendingId = ref('')
const archiveCandidateSelection = reactive({})

const folderPath = ref('')
const folderPreviewLoading = ref(false)
const folderImporting = ref(false)
const folderPreview = ref(null)
const folderCandidateSelection = ref('')
const activeWorkbenchTaskId = ref(String(route.query.taskId || ''))

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

const canRetryActivePendingPreview = computed(() => {
  const item = activePendingItem.value
  if (!item || retryingPendingId.value) return false
  return !item.can_execute || Number(item.preview?.candidate_count || 0) <= 0
})

const canRetryFolderPreview = computed(() => {
  if (!folderPreview.value || folderPreviewLoading.value) return false
  return !canExecuteFolderImport.value || Number(folderPreview.value?.candidate_count || 0) <= 0
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
    if (selected) {
      archiveCandidateSelection[item.id] = candidateKey(selected)
      return
    }
    const firstReady = (item.preview?.candidates || [])[0]
    if (firstReady) archiveCandidateSelection[item.id] = candidateKey(firstReady)
  }
}, { immediate: true })

watch(folderPreview, (preview) => {
  if (!preview) {
    folderCandidateSelection.value = ''
    return
  }
  const selected = preview.selected_candidate
  if (selected) {
    folderCandidateSelection.value = candidateKey(selected)
    return
  }
  const firstReady = (preview.candidates || [])[0]
  folderCandidateSelection.value = firstReady ? candidateKey(firstReady) : ''
}, { immediate: true })

onMounted(async () => {
  await loadPendingImports()
  await restoreActiveWorkbenchTask()
})

watch(() => route.query.taskId, (value) => {
  activeWorkbenchTaskId.value = String(value || '')
  if (value) persistWorkbenchTaskId(activeWorkbenchTaskId.value)
}, { immediate: true })

async function restoreActiveWorkbenchTask() {
  try {
    const requestedId = String(route.query.taskId || activeWorkbenchTaskId.value || readPersistedWorkbenchTaskId() || '')
    const data = await rjSubtitleApi.status()
    const candidates = (data.tasks || []).filter(task => isPendingLinkedSubtitleWorkbenchTask(task))
    const matchedTask = (requestedId && candidates.find(task => task.id === requestedId)) || candidates.at(-1) || null
    if (!matchedTask) {
      persistWorkbenchTaskId('')
      activeWorkbenchTaskId.value = ''
      if (route.query.taskId) {
        const nextQuery = { ...route.query }
        delete nextQuery.taskId
        router.replace({
          path: '/subtitle-import',
          query: nextQuery
        })
      }
      return
    }
    activeWorkbenchTaskId.value = String(matchedTask.id || '')
    persistWorkbenchTaskId(activeWorkbenchTaskId.value)
    if (route.query.taskId !== activeWorkbenchTaskId.value) {
      router.replace({
        path: '/subtitle-import',
        query: {
          ...route.query,
          taskId: activeWorkbenchTaskId.value
        }
      })
    }
  } catch (error) {
    ElMessage.error('恢复字幕补配工作台失败: ' + (error.response?.data?.detail || error.message))
  }
}

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

async function retryActivePendingPreview() {
  const item = activePendingItem.value
  if (!item?.id) return

  retryingPendingId.value = item.id
  try {
    await loadPendingImports()
    ElMessage.success('已重新检查当前预检单的目标目录候选')
  } catch (error) {
    ElMessage.error('重试候选检查失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    retryingPendingId.value = ''
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
  const nextTaskId = String(taskId || '')
  if (!nextTaskId) return
  if (activeWorkbenchTaskId.value === nextTaskId && route.query.taskId === nextTaskId) return
  activeWorkbenchTaskId.value = nextTaskId
  persistWorkbenchTaskId(activeWorkbenchTaskId.value)
  router.replace({
    path: '/subtitle-import',
    query: {
      ...route.query,
      taskId: activeWorkbenchTaskId.value
    }
  })
}

function clearImportWorkbench() {
  activeWorkbenchTaskId.value = ''
  persistWorkbenchTaskId('')
  const nextQuery = { ...route.query }
  delete nextQuery.taskId
  router.replace({
    path: '/subtitle-import',
    query: nextQuery
  })
}

function handleWorkbenchTaskFinished(taskId) {
  if (String(taskId || '') === readPersistedWorkbenchTaskId()) {
    persistWorkbenchTaskId('')
  }
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
  gap: 14px;
}

.hero-card,
.panel-card {
  border: 1px solid #e6edf7;
  border-radius: 22px;
  background:
    radial-gradient(circle at top right, rgba(116, 164, 255, 0.10), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, #ffffff 100%);
  box-shadow: 0 12px 30px rgba(31, 46, 67, 0.07);
  overflow: hidden;
}

.hero-card :deep(.el-card__body) {
  padding: 18px 20px;
}

.panel-card :deep(.el-card__header) {
  padding: 14px 18px 12px;
  border-bottom-color: #edf2f8;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.92) 0%, rgba(255, 255, 255, 0.96) 100%);
}

.panel-card :deep(.el-card__body) {
  padding: 16px 18px 18px;
}

.panel-card :deep(.el-empty) {
  padding: 22px 0 8px;
}

.panel-card :deep(.el-empty__image) {
  width: 86px;
  height: 86px;
  margin-bottom: 10px;
}

.panel-card :deep(.el-empty__description) {
  margin-top: 0;
}

.page-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.page-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.page-tabs :deep(.el-tabs__nav) {
  gap: 8px;
  padding: 5px;
  border-radius: 16px;
  border: 1px solid #e6edf7;
  background: linear-gradient(180deg, #f7faff 0%, #fdfefe 100%);
}

.page-tabs :deep(.el-tabs__item) {
  height: 38px;
  padding: 0 16px;
  border-radius: 12px;
  color: #647791;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.page-tabs :deep(.el-tabs__item.is-active) {
  color: #204d8f;
  background: linear-gradient(180deg, #edf4ff 0%, #e4efff 100%);
  box-shadow: inset 0 0 0 1px #d8e6ff, 0 8px 18px rgba(64, 158, 255, 0.12);
}

.page-tabs :deep(.el-tabs__content) {
  padding-top: 12px;
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
  font-size: 28px;
  line-height: 1.2;
  color: #20344d;
}

.hero-desc {
  margin-top: 8px;
  max-width: 760px;
  font-size: 13px;
  line-height: 1.65;
  color: #5d718a;
}

.pending-list,
.detail-shell,
.candidate-list {
  display: grid;
  gap: 10px;
}

.pending-list {
  max-height: 560px;
  overflow: auto;
  padding-right: 4px;
}

.pending-item,
.candidate-item {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #e6edf6;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  position: relative;
}

.pending-item:hover,
.candidate-item:hover {
  border-color: #bfd4f6;
  box-shadow: 0 8px 20px rgba(59, 88, 135, 0.08);
  transform: translateY(-1px);
}

.pending-item.active {
  border-color: #8fb8ff;
  background: linear-gradient(180deg, #f6faff 0%, #edf5ff 100%);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.11);
}

.pending-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 4px;
  border-radius: 999px;
  background: linear-gradient(180deg, #409eff 0%, #7db4ff 100%);
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
  gap: 8px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid #e8eef6;
  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 100%);
}

.alert-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: -2px;
}

.entry-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  background: #eef4ff;
  color: #31599b;
  font-size: 12px;
}

.detail-shell :deep(.el-alert) {
  border-radius: 14px;
}

.detail-shell :deep(.el-descriptions__cell) {
  padding-top: 10px;
  padding-bottom: 10px;
}

.candidate-item :deep(.el-radio) {
  align-items: flex-start;
  white-space: normal;
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

  .pending-list {
    max-height: none;
    padding-right: 0;
  }
}
</style>
