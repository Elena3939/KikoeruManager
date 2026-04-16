<template>
  <div class="subtitle-import-page">
    <el-card shadow="never" class="hero-card">
      <div class="hero-shell">
        <div class="hero-main">
          <div class="hero-eyebrow">Subtitle Import</div>
          <h1 class="page-title">字幕补配</h1>
          <div class="hero-desc">
            自动检测到的压缩包来源会先进入预检单，手动拿到的字幕目录也可以在这里补进库存。确认目标原作后，直接进入现有 RJ 字幕工作台继续筛选、配对和应用。
          </div>
          <div class="hero-actions">
            <el-button type="primary" @click="openImportWorkbench()">打开工作台</el-button>
            <el-button :loading="pendingLoading" @click="loadPendingImports">刷新预检单</el-button>
          </div>
        </div>
        <div class="hero-side">
          <div class="hero-side-title">当前概览</div>
          <div class="hero-metrics">
            <div class="hero-metric-card">
              <span class="hero-metric-label">待处理预检单</span>
              <strong class="hero-metric-value">{{ pendingItems.length }}</strong>
              <span class="hero-metric-note">自动检测来源</span>
            </div>
            <div class="hero-metric-card">
              <span class="hero-metric-label">后台工作台</span>
              <strong class="hero-metric-value">{{ workbenchBackgroundSummary.total || 0 }}</strong>
              <span class="hero-metric-note">累计任务</span>
            </div>
            <div class="hero-metric-card">
              <span class="hero-metric-label">进行中</span>
              <strong class="hero-metric-value">{{ workbenchBackgroundSummary.processing || 0 }}</strong>
              <span class="hero-metric-note">补配任务</span>
            </div>
            <div class="hero-metric-card">
              <span class="hero-metric-label">手动目录预检</span>
              <strong class="hero-metric-value">{{ folderPreview?.candidate_count ?? 0 }}</strong>
              <span class="hero-metric-note">目标候选</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-tabs v-show="!workbenchDialogVisible" v-model="activeTab" class="page-tabs">
      <el-tab-pane label="压缩包补配" name="archive">
        <div class="tab-intro">
          <div>
            <div class="tab-intro-title">自动检测到的字幕来源</div>
            <div class="tab-intro-desc">左侧管理待处理预检单，右侧查看命中结果并选择目标目录。确认后即可一键送入补配工作台。</div>
          </div>
        </div>
        <div class="top-panel-grid archive-panel-grid">
          <el-card shadow="never" class="panel-card source-panel-card">
              <template #header>
                <div class="panel-header">
                  <div>
                    <div class="panel-title">自动检测来源</div>
                    <div class="panel-subtitle">来自正常解压主链路</div>
                  </div>
                  <el-tag size="small" type="info">来自正常解压主链路</el-tag>
                </div>
              </template>

              <el-empty v-if="pendingLoadedOnce && !pendingItems.length" description="当前没有待处理的字幕补配预检单" />

              <div v-else>
                <div class="pending-toolbar">
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    :disabled="!activePendingItem || pendingClearLoading"
                    :loading="pendingClearLoading && pendingClearMode === 'single'"
                    @click="clearPendingImports(false)"
                  >
                    清除当前
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    :disabled="!pendingItems.length || pendingClearLoading"
                    :loading="pendingClearLoading && pendingClearMode === 'all'"
                    @click="clearPendingImports(true)"
                  >
                    清空预检单
                  </el-button>
                </div>

                <div class="pending-list">
                <button
                  v-for="item in pendingItems"
                  :key="item.id"
                  type="button"
                  class="pending-item"
                  :class="{ active: item.id === activePendingId }"
                  @click="activePendingId = item.id"
                >
                  <div class="pending-item-head">
                    <strong>{{ getDisplayRJCode(item.preview?.target_rjcode || item.preview?.source_rjcode) || '未识别 RJ' }}</strong>
                    <el-tag size="small" :type="item.can_execute ? 'success' : 'info'">
                      {{ item.can_execute ? '可执行' : '仅查看' }}
                    </el-tag>
                  </div>
                  <div class="pending-item-title">{{ item.preview?.source_label || getFileName(item.source_path) }}</div>
                  <div class="pending-item-meta">
                    <span>来源 {{ getDisplayRJCode(item.preview?.source_rjcode) || '-' }}</span>
                    <span>目标 {{ getDisplayRJCode(item.preview?.target_rjcode) || '-' }}</span>
                    <span>字幕 {{ item.preview?.subtitle_count ?? 0 }}</span>
                  </div>
                  <div class="pending-item-path">{{ item.source_path }}</div>
                </button>
              </div>
              </div>
            </el-card>

            <el-card shadow="never" class="panel-card preview-panel-card">
              <template #header>
                <div class="panel-header">
                  <div>
                    <div class="panel-title">预检结果</div>
                    <div class="panel-subtitle">查看来源、候选字幕和目标目录命中情况</div>
                  </div>
                  <el-tag v-if="activePendingItem" size="small" :type="activePendingItem.can_execute ? 'success' : 'warning'">
                    {{ activePendingItem.can_execute ? '可以补配' : '当前不可执行' }}
                  </el-tag>
                </div>
              </template>

              <el-empty v-if="!activePendingItem" description="先从左侧选择一条自动检测到的预检单" />

              <div v-else :key="activePendingItem.id" class="detail-shell">
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

                <el-descriptions :key="`archive-preview-${activePendingItem.id}`" :column="2" border>
                  <el-descriptions-item label="来源压缩包">{{ activePendingItem.preview?.source_label || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="来源 RJ"><span class="rj-code-value">{{ getDisplayRJCode(activePendingItem.preview?.source_rjcode) || '-' }}</span></el-descriptions-item>
                  <el-descriptions-item label="目标原作 RJ"><span class="rj-code-value">{{ getDisplayRJCode(activePendingItem.preview?.target_rjcode) || '-' }}</span></el-descriptions-item>
                  <el-descriptions-item label="字幕候选数">{{ activePendingItem.preview?.subtitle_count ?? 0 }}</el-descriptions-item>
                  <el-descriptions-item label="Kikoeru 原作命中">
                    <el-tag :type="activePendingItem.preview?.kikoeru_has_work ? 'success' : 'info'">
                      {{ activePendingItem.preview?.kikoeru_has_work ? '已命中原作' : '未命中原作' }}
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
                  导入并加入补配工作台
                </el-button>
                </div>
              </div>
            </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="字幕文件夹补配" name="folder">
        <div class="tab-intro">
          <div>
            <div class="tab-intro-title">手动补进字幕目录</div>
            <div class="tab-intro-desc">适合单独拿到字幕文件夹的场景。先输入路径做预检，再选择目标原作并送入工作台继续处理。</div>
          </div>
        </div>
        <div class="top-panel-grid folder-panel-grid">
          <el-card shadow="never" class="panel-card source-panel-card">
              <template #header>
                <div class="panel-header">
                  <div>
                    <div class="panel-title">手动字幕来源</div>
                    <div class="panel-subtitle">保留手动补配入口</div>
                  </div>
                  <el-tag size="small" type="warning">保留手动补配入口</el-tag>
                </div>
              </template>

              <el-form label-position="top" class="manual-source-form">
                <el-form-item label="字幕文件夹路径">
                  <el-input
                    v-model="folderPath"
                    clearable
                    placeholder="例如 D:\\Temp\\RJ123456 或其中带 subtitles 子目录"
                    @keyup.enter="previewFolderImport"
                  />
                </el-form-item>
              </el-form>

              <div class="action-row manual-action-row">
                <el-button :loading="folderPreviewLoading" @click="previewFolderImport">预检目标</el-button>
                <el-button
                  type="primary"
                  :loading="folderImporting"
                  :disabled="!canExecuteFolderImport"
                  @click="executeFolderImport"
                >
                  导入并加入补配工作台
                </el-button>
                <el-button @click="openImportWorkbench()">打开工作台</el-button>
              </div>

              <div class="scene-tip-card">
                <div class="scene-tip-title">适用场景</div>
                <div class="scene-tip-text">手头单独拿到了字幕目录时，可以直接在这里补进原作目录，再进入库存页做筛选、删除和手动配对。</div>
              </div>
            </el-card>

            <el-card shadow="never" class="panel-card preview-panel-card">
              <template #header>
                <div class="panel-header">
                  <div>
                    <div class="panel-title">文件夹预检结果</div>
                    <div class="panel-subtitle">查看来源字幕、目标目录候选和可执行状态</div>
                  </div>
                  <el-tag v-if="folderPreview" size="small" :type="canExecuteFolderImport ? 'success' : 'warning'">
                    {{ canExecuteFolderImport ? '可以补配' : '当前不可执行' }}
                  </el-tag>
                </div>
              </template>

              <el-empty v-if="!folderPreview && !folderPreviewLoading" description="输入字幕文件夹路径后做一次预检" />

              <div v-else-if="folderPreview" :key="`${folderPreview.source_path || folderPreview.source_label || 'folder-preview'}`" class="detail-shell">
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

                <el-descriptions :key="`folder-preview-${folderPreview.source_path || folderPreview.source_label || ''}`" :column="2" border>
                  <el-descriptions-item label="来源 RJ"><span class="rj-code-value">{{ getDisplayRJCode(folderPreview.source_rjcode) || '-' }}</span></el-descriptions-item>
                  <el-descriptions-item label="目标原作 RJ"><span class="rj-code-value">{{ getDisplayRJCode(folderPreview.target_rjcode) || '-' }}</span></el-descriptions-item>
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
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="workbenchDialogVisible"
      class="subtitle-import-workbench-dialog"
      append-to-body
      :destroy-on-close="false"
      :close-on-click-modal="false"
      :show-close="false"
      top="3vh"
      width="96vw"
    >
      <SubtitleImportWorkbench
        v-if="workbenchDialogInitialized"
        :task-id="activeWorkbenchTaskId"
        :visible="workbenchDialogVisible"
        :background-active="workbenchBackgroundActive"
        @close="closeImportWorkbench"
        @hide-background="hideImportWorkbenchToBackground"
        @select-task="openImportedTask"
        @state-change="handleWorkbenchStateChange"
      />
    </el-dialog>

  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { rjSubtitleApi, subtitleImportApi } from '../api'
import SubtitleImportWorkbench from '../components/subtitle-import/SubtitleImportWorkbench.vue'
import { useBackgroundWorkbenchManager } from '../composables/useBackgroundWorkbenchManager'

const route = useRoute()
const router = useRouter()
const LEGACY_SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'
const SUBTITLE_IMPORT_OPTIONS_KEY = 'kikoeru.ui.subtitleImport.workbenchOptions'
const SUBTITLE_IMPORT_QUEUE_STATE_KEY = 'kikoeru.ui.subtitleImport.workbenchQueueState'
const SUBTITLE_IMPORT_TASK_DRAFTS_KEY = 'kikoeru.ui.subtitleImport.taskDrafts'
const SUBTITLE_IMPORT_WORKBENCH_ID = 'subtitle-import-workbench'
const AUTO_IMPORT_POLL_INTERVAL_MS = 2500
const PENDING_REFRESH_INTERVAL_MS = 4000

const workbenchManager = useBackgroundWorkbenchManager()

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

function loadSubtitleImportOptions() {
  const saved = loadJson(SUBTITLE_IMPORT_OPTIONS_KEY, null)
  if (saved && typeof saved === 'object') return saved
  const legacy = loadJson(LEGACY_SUBTITLE_OPTIONS_KEY, {})
  if (legacy && typeof legacy === 'object') {
    try {
      localStorage.setItem(SUBTITLE_IMPORT_OPTIONS_KEY, JSON.stringify(legacy))
    } catch (_) {}
  }
  return legacy
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

function getDisplayRJCode(value = '') {
  const normalized = String(value || '').trim().toUpperCase()
  if (!normalized) return ''
  const match = normalized.match(/[RVB]J(?:\d{8}|\d{6})(?!\d)/)
  return match ? match[0] : normalized
}

function getSubtitleWorkbenchFilterOptions() {
  const saved = loadSubtitleImportOptions()
  return {
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: sanitizeSubtitleFilterRules(saved?.subtitleFilterRules || [])
  }
}

function clearPersistedWorkbenchSession() {
  try {
    localStorage.removeItem(SUBTITLE_IMPORT_QUEUE_STATE_KEY)
    localStorage.removeItem(SUBTITLE_IMPORT_TASK_DRAFTS_KEY)
  } catch (_) {}
}

function isLinkedSubtitleWorkbenchTask(task = {}) {
  const sourceMode = String(task?.source_mode || '').trim().toLowerCase()
  return ['linked_translation_archive_import', 'subtitle_folder_import'].includes(sourceMode)
}

const activeTab = ref('archive')
const pendingLoading = ref(false)
const pendingRefreshing = ref(false)
const pendingLoadedOnce = ref(false)
const pendingItems = ref([])
const activePendingId = ref('')
const executingPendingId = ref('')
const retryingPendingId = ref('')
const pendingClearLoading = ref(false)
const pendingClearMode = ref('')
const archiveCandidateSelection = reactive({})

const folderPath = ref('')
const folderPreviewLoading = ref(false)
const folderImporting = ref(false)
const folderPreview = ref(null)
const folderCandidateSelection = ref('')
workbenchManager.registerWorkbench({
  id: SUBTITLE_IMPORT_WORKBENCH_ID,
  type: 'subtitle-import',
  title: '字幕补配工作台',
  priority: 72,
  actions: ['resume', 'close'],
  onClose: () => {
    resetImportWorkbenchSession()
  }
})
const subtitleImportWorkbenchRuntime = workbenchManager.getWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID)
const activeWorkbenchTaskId = ref(String(
  route.query.taskId ||
  subtitleImportWorkbenchRuntime.value?.payload?.activeTaskId ||
  ''
))
const workbenchDialogVisible = computed({
  get: () => Boolean(subtitleImportWorkbenchRuntime.value?.visible),
  set: (value) => {
    workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
      visible: Boolean(value),
      restorable: Boolean(value) || Boolean(workbenchBackgroundActive.value) || Boolean(activeWorkbenchTaskId.value)
    })
  }
})
const workbenchBackgroundActive = computed({
  get: () => Boolean(subtitleImportWorkbenchRuntime.value?.backgroundActive),
  set: (value) => {
    workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
      backgroundActive: Boolean(value),
      cardVisible: Boolean(value),
      dismissed: false,
      restorable: Boolean(value) || Boolean(workbenchDialogVisible.value) || Boolean(activeWorkbenchTaskId.value)
    })
  }
})
const workbenchDialogInitialized = ref(Boolean(
  route.query.taskId ||
  activeWorkbenchTaskId.value ||
  subtitleImportWorkbenchRuntime.value?.visible ||
  subtitleImportWorkbenchRuntime.value?.backgroundActive
))
const workbenchBackgroundSummary = ref({
  total: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  clearable: 0,
  selectedTaskId: '',
  activeTask: null
})
const autoImportingPendingId = ref('')
const autoImportBlockedIds = ref(new Set())
let autoImportTimer = null
let pendingRefreshTimer = null

function syncSubtitleImportWorkbenchCardState() {
  const summary = workbenchBackgroundSummary.value || {}
  const total = Number(summary.total || 0)
  const processing = Number(summary.processing || 0)
  const completed = Number(summary.completed || 0)
  const failed = Number(summary.failed || 0)
  const activeTask = summary.activeTask || null
  const percentage = total > 0 ? Math.max(0, Math.min(100, Math.round(((completed + failed) / total) * 100))) : 0
  const tone = processing > 0 ? 'info' : failed > 0 ? 'warning' : completed > 0 ? 'success' : 'neutral'
  const label = processing > 0 ? '后台运行中' : failed > 0 ? '可回看' : completed > 0 ? '已完成' : '待处理'

  workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
    title: '字幕补配工作台',
    cardVisible: Boolean(workbenchBackgroundActive.value),
    dismissed: false,
    payload: {
      activeTaskId: String(activeWorkbenchTaskId.value || '')
    },
    status: {
      key: tone,
      label,
      tone
    },
    progress: {
      percentage,
      status: failed > 0 && processing <= 0 ? 'warning' : completed > 0 && processing <= 0 && failed <= 0 ? 'success' : '',
      label: activeTask?.progressText || activeTask?.statusLabel || ''
    },
    summary: {
      subtitle: activeTask
        ? `${activeTask.rjcode || '当前任务'} · ${activeTask.title || '-'}`
        : '保留当前队列与人工补配上下文',
      text: activeTask?.progressText || activeTask?.statusLabel || '隐藏后继续保留任务队列、自动轮询和手动补配上下文。'
    },
    metrics: [
      { key: 'total', label: '全部', value: total, tone: 'neutral' },
      { key: 'processing', label: '进行中', value: processing, tone: processing > 0 ? 'info' : 'neutral' },
      { key: 'completed', label: '完成', value: completed, tone: completed > 0 ? 'success' : 'neutral' },
      { key: 'failed', label: '失败', value: failed, tone: failed > 0 ? 'danger' : 'neutral' }
    ]
  })
}

function resetImportWorkbenchSession() {
  workbenchDialogVisible.value = false
  workbenchBackgroundActive.value = false
  workbenchDialogInitialized.value = false
  activeWorkbenchTaskId.value = ''
  workbenchBackgroundSummary.value = {
    total: 0,
    processing: 0,
    completed: 0,
    failed: 0,
    clearable: 0,
    selectedTaskId: '',
    activeTask: null
  }
  clearPersistedWorkbenchSession()
}

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
  const selected = item.preview?.selected_candidate
  if (selected) {
    archiveCandidateSelection[item.id] = candidateKey(selected)
    return
  }
  const readyCandidates = (item.preview?.candidates || []).filter(candidate => candidate?.ready_for_import)
  if (!archiveCandidateSelection[item.id] && readyCandidates.length === 1) {
    archiveCandidateSelection[item.id] = candidateKey(readyCandidates[0])
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
  const readyCandidates = (preview.candidates || []).filter(candidate => candidate?.ready_for_import)
  folderCandidateSelection.value = readyCandidates.length === 1 ? candidateKey(readyCandidates[0]) : ''
}, { immediate: true })

onMounted(async () => {
  startPendingRefreshPolling()
  await refreshSubtitleImportPage({ silent: false })
})

onActivated(async () => {
  startPendingRefreshPolling()
  await refreshSubtitleImportPage({ silent: true })
})

onDeactivated(() => {
  stopPendingRefreshPolling()
})

onUnmounted(() => {
  stopAutoImportPolling()
  stopPendingRefreshPolling()
})

watch(() => route.query.taskId, (value) => {
  if (value) {
    activeWorkbenchTaskId.value = String(value || '')
    workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
      activeTaskId: activeWorkbenchTaskId.value
    })
    workbenchDialogInitialized.value = true
    workbenchBackgroundActive.value = false
    workbenchDialogVisible.value = true
    return
  }
  if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) {
    activeWorkbenchTaskId.value = ''
  }
}, { immediate: true })

watch(() => [workbenchDialogVisible.value, workbenchBackgroundActive.value], ([visible, backgroundActive]) => {
  if (!visible && !backgroundActive) {
    stopAutoImportPolling()
    const nextQuery = { ...route.query }
    delete nextQuery.taskId
    if (route.query.taskId) {
      router.replace({
        path: '/subtitle-import',
        query: nextQuery
      })
    }
    return
  }
  workbenchDialogInitialized.value = true
  startAutoImportPolling()
  queuePendingRefresh({ silent: true })
  queueAutoImportProcessing()
  if (visible && activeWorkbenchTaskId.value && route.query.taskId !== activeWorkbenchTaskId.value) {
    router.replace({
      path: '/subtitle-import',
      query: {
        ...route.query,
        taskId: activeWorkbenchTaskId.value
      }
    })
    return
  }
  if (!visible && route.query.taskId) {
    const nextQuery = { ...route.query }
    delete nextQuery.taskId
    router.replace({
      path: '/subtitle-import',
      query: nextQuery
    })
  }
})

watch(activeWorkbenchTaskId, (taskId) => {
  const normalized = String(taskId || '')
  workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
    payload: {
      activeTaskId: normalized
    },
    restorable: Boolean(normalized) || Boolean(workbenchDialogVisible.value) || Boolean(workbenchBackgroundActive.value)
  })
  if (!workbenchDialogVisible.value) return
  if (String(route.query.taskId || '') === normalized) {
    return
  }
  const nextQuery = { ...route.query }
  if (normalized) nextQuery.taskId = normalized
  else delete nextQuery.taskId
  router.replace({
    path: '/subtitle-import',
    query: nextQuery
  })
})

watch(() => workbenchBackgroundSummary.value, () => {
  syncSubtitleImportWorkbenchCardState()
}, { deep: true, immediate: true })

watch(pendingItems, () => {
  pruneAutoImportBlockedIds()
  if (workbenchDialogVisible.value || workbenchBackgroundActive.value) {
    queueAutoImportProcessing()
  }
}, { deep: false })

watch(() => route.path, (path) => {
  if (path === '/subtitle-import') {
    startPendingRefreshPolling()
    queuePendingRefresh({ silent: true })
    return
  }
  stopPendingRefreshPolling()
}, { immediate: true })

async function refreshSubtitleImportPage(options = {}) {
  await loadPendingImports(options)
  await restoreActiveWorkbenchTask(options)
}

async function restoreActiveWorkbenchTask(options = {}) {
  const { silent = false } = options
  try {
    const requestedId = String(
      route.query.taskId ||
      activeWorkbenchTaskId.value ||
      subtitleImportWorkbenchRuntime.value?.payload?.activeTaskId ||
      ''
    )
    const data = await rjSubtitleApi.status()
    const candidates = (data.tasks || []).filter(task => isLinkedSubtitleWorkbenchTask(task))
    const matchedTask = (requestedId && candidates.find(task => task.id === requestedId)) || candidates.at(-1) || null
    if (!matchedTask) {
      activeWorkbenchTaskId.value = ''
      workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
        payload: {
          activeTaskId: ''
        }
      })
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
    workbenchManager.patchWorkbenchState(SUBTITLE_IMPORT_WORKBENCH_ID, {
      payload: {
        activeTaskId: activeWorkbenchTaskId.value
      }
    })
    if (workbenchDialogVisible.value && route.query.taskId !== activeWorkbenchTaskId.value) {
      router.replace({
        path: '/subtitle-import',
        query: {
          ...route.query,
          taskId: activeWorkbenchTaskId.value
        }
      })
    }
  } catch (error) {
    if (!silent) {
      ElMessage.error('恢复字幕补配工作台失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

async function loadPendingImports(options = {}) {
  const { silent = false } = options
  if (pendingLoading.value || pendingRefreshing.value) return
  if (silent) pendingRefreshing.value = true
  else pendingLoading.value = true
  try {
    const data = await subtitleImportApi.listPending()
    pendingItems.value = data.items || []
    pendingLoadedOnce.value = true
    if (!pendingItems.value.some(item => item.id === activePendingId.value)) {
      activePendingId.value = pendingItems.value[0]?.id || ''
    }
  } catch (error) {
    if (!silent) {
      ElMessage.error('加载字幕补配预检单失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    if (silent) pendingRefreshing.value = false
    else pendingLoading.value = false
  }
}

async function clearPendingImports(clearAll = false) {
  const targetItem = activePendingItem.value
  const targetIds = clearAll ? (pendingItems.value || []).map(item => String(item.id || '')).filter(Boolean) : [String(targetItem?.id || '')].filter(Boolean)
  if (!targetIds.length) {
    ElMessage.warning(clearAll ? '当前没有可清除的预检单' : '请先选择一条预检单')
    return
  }

  try {
    await ElMessageBox.confirm(
      clearAll
        ? `确定清空当前 ${targetIds.length} 条字幕补配预检单吗？清除后需要重新导入或重新等待自动检测。`
        : '确定清除当前这条字幕补配预检单吗？清除后需要重新导入或重新等待自动检测。',
      clearAll ? '清空预检单' : '清除当前预检单',
      {
        confirmButtonText: clearAll ? '清空' : '清除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (_) {
    return
  }

  pendingClearLoading.value = true
  pendingClearMode.value = clearAll ? 'all' : 'single'
  try {
    const result = await subtitleImportApi.clearPending({
      recordIds: targetIds,
      clearAll
    })
    await loadPendingImports()
    ElMessage.success(
      clearAll
        ? `已清空 ${Number(result.cleared_count || 0)} 条预检单`
        : '当前预检单已清除'
    )
  } catch (error) {
    ElMessage.error('清除字幕补配预检单失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    pendingClearLoading.value = false
    pendingClearMode.value = ''
  }
}

function getSelectedArchiveCandidateForItem(item) {
  if (!item) return null
  const key = archiveCandidateSelection[item.id]
  if (key) {
    const matched = (item.preview?.candidates || []).find(candidate => candidateKey(candidate) === key)
    if (matched) return matched
  }
  const selected = item.preview?.selected_candidate
  if (selected) return selected
  const readyCandidates = (item.preview?.candidates || []).filter(candidate => candidate?.ready_for_import)
  return readyCandidates.length === 1 ? readyCandidates[0] : null
}

function pruneAutoImportBlockedIds() {
  const currentIds = new Set((pendingItems.value || []).map(item => String(item.id || '')))
  autoImportBlockedIds.value = new Set(
    [...autoImportBlockedIds.value].filter(id => currentIds.has(String(id || '')))
  )
}

function findNextAutoImportItem() {
  return (pendingItems.value || []).find(item => (
    item?.can_execute &&
    getSelectedArchiveCandidateForItem(item) &&
    !autoImportBlockedIds.value.has(String(item.id || ''))
  )) || null
}

function stopAutoImportPolling() {
  if (autoImportTimer) {
    clearInterval(autoImportTimer)
    autoImportTimer = null
  }
}

function stopPendingRefreshPolling() {
  if (pendingRefreshTimer) {
    clearInterval(pendingRefreshTimer)
    pendingRefreshTimer = null
  }
}

function startPendingRefreshPolling() {
  if (pendingRefreshTimer) return
  pendingRefreshTimer = setInterval(() => {
    queuePendingRefresh({ silent: true })
  }, PENDING_REFRESH_INTERVAL_MS)
}

function queuePendingRefresh(options = {}) {
  if (route.path !== '/subtitle-import') return
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  if (pendingLoading.value || pendingRefreshing.value || executingPendingId.value || pendingClearLoading.value) return
  void loadPendingImports(options)
}

function startAutoImportPolling() {
  if (autoImportTimer) return
  autoImportTimer = setInterval(() => {
    queueAutoImportProcessing()
  }, AUTO_IMPORT_POLL_INTERVAL_MS)
}

function queueAutoImportProcessing() {
  if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) return
  void processAutoImportQueue()
}

async function processAutoImportQueue() {
  if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) return
  if (pendingLoading.value || pendingRefreshing.value || executingPendingId.value || autoImportingPendingId.value) return
  const item = findNextAutoImportItem()
  if (!item) return
  const candidate = getSelectedArchiveCandidateForItem(item)
  if (!candidate) return

  autoImportingPendingId.value = String(item.id || '')
  try {
    await executePendingImportRecord(item, candidate, { autoTriggered: true })
  } catch (error) {
    autoImportBlockedIds.value = new Set([
      ...autoImportBlockedIds.value,
      String(item.id || '')
    ])
    ElMessage.error(`自动导入 ${item.preview?.source_label || getFileName(item.source_path)} 失败: ${error.response?.data?.detail || error.message}`)
  } finally {
    autoImportingPendingId.value = ''
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

async function executePendingImportRecord(item, candidate, options = {}) {
  if (!item || !candidate) return null
  const { autoTriggered = false } = options
  executingPendingId.value = item.id
  try {
    const filterOptions = getSubtitleWorkbenchFilterOptions()
    const data = await subtitleImportApi.executePending(item.id, {
      targetLibraryId: candidate.library_id,
      targetFolderPath: candidate.folder_path,
      useFilterRules: filterOptions.useFilterRules,
      subtitleFilterRules: filterOptions.subtitleFilterRules
    })
    if (!autoTriggered) {
      ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕补配导入成功，已自动加入工作台' : '字幕补配导入成功')
    }
    await loadPendingImports()
    if (data.task?.id) {
      openImportedTask(data.task.id)
    }
    return data
  } finally {
    executingPendingId.value = ''
  }
}

async function executePendingImport() {
  const item = activePendingItem.value
  const candidate = selectedArchiveCandidate.value
  if (!item || !candidate) return

  try {
    await executePendingImportRecord(item, candidate, { autoTriggered: false })
  } catch (error) {
    ElMessage.error('执行字幕补配失败: ' + (error.response?.data?.detail || error.message))
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
    ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕文件夹补配成功，已自动加入工作台' : '字幕文件夹补配成功')
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
  workbenchDialogInitialized.value = true
  workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
    activeTaskId: nextTaskId
  })
  if (!nextTaskId) return
  if (activeWorkbenchTaskId.value === nextTaskId && route.query.taskId === nextTaskId) return
  activeWorkbenchTaskId.value = nextTaskId
}

function openImportWorkbench() {
  workbenchDialogInitialized.value = true
  workbenchManager.openWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID, {
    activeTaskId: String(activeWorkbenchTaskId.value || '')
  })
}

function restoreImportWorkbench() {
  workbenchDialogInitialized.value = true
  workbenchManager.resumeWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID)
}

function hideImportWorkbenchToBackground() {
  workbenchDialogInitialized.value = true
  workbenchManager.backgroundWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID)
}

function closeImportWorkbench() {
  workbenchManager.closeWorkbench(SUBTITLE_IMPORT_WORKBENCH_ID)
}

function handleWorkbenchStateChange(payload) {
  workbenchBackgroundSummary.value = {
    total: Number(payload?.total || 0),
    processing: Number(payload?.processing || 0),
    completed: Number(payload?.completed || 0),
    failed: Number(payload?.failed || 0),
    clearable: Number(payload?.clearable || 0),
    selectedTaskId: String(payload?.selectedTaskId || ''),
    activeTask: payload?.activeTask || null
  }
  syncSubtitleImportWorkbenchCardState()
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
  gap: 12px;
}

.hero-card,
.panel-card {
  border: 1px solid #e6edf7;
  border-radius: 18px;
  background:
    radial-gradient(circle at top right, rgba(116, 164, 255, 0.10), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, #ffffff 100%);
  box-shadow: 0 8px 24px rgba(31, 46, 67, 0.06);
  overflow: hidden;
}

.hero-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.panel-card :deep(.el-card__header) {
  padding: 12px 14px 10px;
  border-bottom-color: #edf2f8;
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.92) 0%, rgba(255, 255, 255, 0.96) 100%);
}

.panel-card :deep(.el-card__body) {
  padding: 12px 14px 14px;
}

.panel-card :deep(.el-empty) {
  padding: 12px 0 2px;
}

.panel-card :deep(.el-empty__image) {
  width: 64px;
  height: 64px;
  margin-bottom: 4px;
}

.panel-card :deep(.el-empty__description) {
  margin-top: 0;
  font-size: 12px;
}

.page-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.page-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.page-tabs :deep(.el-tabs__nav) {
  gap: 6px;
  padding: 4px;
  border-radius: 14px;
  border: 1px solid #e6edf7;
  background: linear-gradient(180deg, #f7faff 0%, #fdfefe 100%);
}

.page-tabs :deep(.el-tabs__item) {
  height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  color: #647791;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.page-tabs :deep(.el-tabs__item.is-active) {
  color: #204d8f;
  background: linear-gradient(180deg, #edf4ff 0%, #e4efff 100%);
  box-shadow: inset 0 0 0 1px #d8e6ff, 0 8px 18px rgba(64, 158, 255, 0.12);
}

.page-tabs :deep(.el-tabs__content) {
  padding-top: 10px;
}

.hero-head,
.panel-header,
.section-head,
.action-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.hero-head {
  align-items: center;
}

.page-title {
  margin: 0;
  font-size: 26px;
  line-height: 1.2;
  color: #20344d;
}

.hero-desc {
  margin-top: 6px;
  max-width: 720px;
  font-size: 12px;
  line-height: 1.55;
  color: #5d718a;
}

.hero-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.top-panel-grid {
  display: grid;
  gap: 12px;
  align-items: start;
}

.archive-panel-grid {
  grid-template-columns: minmax(320px, 0.88fr) minmax(420px, 1.38fr);
}

.folder-panel-grid {
  grid-template-columns: minmax(340px, 0.92fr) minmax(440px, 1.28fr);
}

.source-panel-card :deep(.el-card__body),
.preview-panel-card :deep(.el-card__body) {
  min-height: 172px;
}

.pending-list,
.detail-shell,
.candidate-list {
  display: grid;
  gap: 8px;
}

.pending-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.pending-list {
  max-height: 330px;
  overflow: auto;
  padding-right: 3px;
}

.pending-item,
.candidate-item {
  display: grid;
  gap: 5px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e6edf6;
  border-radius: 12px;
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
  gap: 6px;
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
  font-size: 11px;
  line-height: 1.5;
  color: #71839b;
}

.block-box {
  display: grid;
  gap: 7px;
  padding: 10px 12px;
  border-radius: 14px;
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
  padding: 4px 9px;
  border-radius: 999px;
  background: #eef4ff;
  color: #31599b;
  font-size: 11px;
}

.detail-shell :deep(.el-alert) {
  border-radius: 14px;
}

.detail-shell :deep(.el-descriptions__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.rj-code-value {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef4ff;
  color: #31599b;
  font-family: Consolas, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
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

.manual-source-form :deep(.el-form-item) {
  margin-bottom: 10px;
}

.manual-action-row {
  align-items: center;
}

.scene-tip-card {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid #e6edf7;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.scene-tip-title {
  font-size: 12px;
  font-weight: 700;
  color: #29405f;
}

.scene-tip-text {
  font-size: 11px;
  line-height: 1.55;
  color: #6c7f97;
}

@media (max-width: 992px) {
  .page-title {
    font-size: 24px;
  }

  .pending-list {
    max-height: none;
    padding-right: 0;
  }

  .top-panel-grid {
    grid-template-columns: 1fr;
  }
}

.subtitle-import-page :deep(.subtitle-import-workbench-dialog) {
  padding: 0;
}

.subtitle-import-page :deep(.subtitle-import-workbench-dialog .el-dialog) {
  width: min(96vw, 1520px);
  margin: 0 auto;
  border-radius: 24px;
  overflow: hidden;
  background: linear-gradient(180deg, #f7fbff 0%, #f4f8fe 100%);
  box-shadow: 0 26px 80px rgba(24, 42, 72, 0.24);
}

.subtitle-import-page :deep(.subtitle-import-workbench-dialog .el-dialog__header) {
  display: none;
}

.subtitle-import-page :deep(.subtitle-import-workbench-dialog .el-dialog__body) {
  padding: 0;
  max-height: calc(100vh - 18px);
  overflow: auto;
}

.workbench-background-dock {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 2200;
}

.workbench-background-card {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 360px;
  max-width: min(92vw, 560px);
  padding: 14px 16px;
  border: 1px solid rgba(121, 160, 255, 0.28);
  border-radius: 18px;
  background:
    radial-gradient(circle at top right, rgba(111, 155, 255, 0.16), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 255, 0.98) 100%);
  box-shadow: 0 18px 42px rgba(29, 47, 84, 0.18);
}

.workbench-background-main {
  display: grid;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.workbench-background-title {
  font-size: 15px;
  font-weight: 700;
  color: #203252;
}

.workbench-background-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 12px;
  color: #5c6c87;
}

.workbench-background-active {
  font-size: 12px;
  color: #30476d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workbench-background-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtitle-import-page {
  --apple-bg: #f5f5f7;
  --apple-surface: rgba(255, 255, 255, 0.96);
  --apple-surface-soft: rgba(255, 255, 255, 0.82);
  --apple-border: rgba(0, 0, 0, 0.06);
  --apple-text: #1d1d1f;
  --apple-text-soft: rgba(29, 29, 31, 0.72);
  --apple-text-muted: rgba(29, 29, 31, 0.52);
  --apple-blue: #0071e3;
  --apple-blue-soft: rgba(0, 113, 227, 0.08);
  --apple-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
  background:
    radial-gradient(circle at top left, rgba(0, 113, 227, 0.06), transparent 26%),
    linear-gradient(180deg, #fafafc 0%, #f5f5f7 100%);
}

.hero-card,
.panel-card {
  border: 1px solid var(--apple-border);
  border-radius: 24px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.9)),
    var(--apple-bg);
  box-shadow: var(--apple-shadow);
}

.hero-card :deep(.el-card__body) {
  padding: 20px 22px;
}

.panel-card :deep(.el-card__header) {
  padding: 14px 16px 12px;
  border-bottom-color: rgba(0, 0, 0, 0.04);
  background: rgba(255, 255, 255, 0.7);
}

.panel-card :deep(.el-card__body) {
  padding: 14px 16px 16px;
}

.page-tabs :deep(.el-tabs__nav) {
  gap: 8px;
  padding: 4px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.05);
  background: rgba(255, 255, 255, 0.76);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.page-tabs :deep(.el-tabs__item) {
  height: 36px;
  padding: 0 16px;
  border-radius: 999px;
  color: var(--apple-text-soft);
  font-weight: 600;
}

.page-tabs :deep(.el-tabs__item.is-active) {
  color: #ffffff;
  background: var(--apple-blue);
  box-shadow: 0 10px 20px rgba(0, 113, 227, 0.18);
}

.page-tabs :deep(.el-tabs__active-bar) {
  display: none;
}

.page-title {
  font-size: 32px;
  line-height: 1.08;
  letter-spacing: -0.4px;
  color: var(--apple-text);
}

.hero-desc {
  margin-top: 8px;
  max-width: 760px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--apple-text-soft);
}

.hero-actions :deep(.el-button),
.pending-toolbar :deep(.el-button),
.action-row :deep(.el-button),
.alert-actions :deep(.el-button) {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.12px;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.hero-actions :deep(.el-button:hover),
.pending-toolbar :deep(.el-button:hover),
.action-row :deep(.el-button:hover),
.alert-actions :deep(.el-button:hover) {
  transform: translateY(-1px);
}

.subtitle-import-page :deep(.el-button--default) {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.92);
  color: var(--apple-text);
}

.subtitle-import-page :deep(.el-button--default:hover) {
  border-color: rgba(0, 113, 227, 0.24);
  color: var(--apple-blue);
  background: #ffffff;
}

.subtitle-import-page :deep(.el-button--primary) {
  border-color: transparent;
  background: var(--apple-blue);
  box-shadow: 0 10px 20px rgba(0, 113, 227, 0.18);
}

.subtitle-import-page :deep(.el-button--primary:hover) {
  background: #0066cc;
}

.subtitle-import-page :deep(.el-button--danger) {
  box-shadow: none;
}

.panel-header,
.section-head {
  align-items: center;
}

.pending-item,
.candidate-item,
.block-box,
.scene-tip-card {
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.pending-item:hover,
.candidate-item:hover {
  border-color: rgba(0, 113, 227, 0.18);
  box-shadow: 0 18px 34px rgba(15, 23, 42, 0.08);
}

.pending-item.active {
  border-color: rgba(0, 113, 227, 0.24);
  background: linear-gradient(180deg, rgba(0, 113, 227, 0.08), rgba(255, 255, 255, 0.96));
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.1);
}

.pending-item.active::before {
  left: 8px;
  top: 12px;
  bottom: 12px;
  width: 3px;
  background: var(--apple-blue);
}

.pending-item-title,
.candidate-title,
.section-title,
.scene-tip-title {
  color: var(--apple-text);
}

.pending-item-meta,
.pending-item-path,
.candidate-meta,
.candidate-path,
.section-tip,
.scene-tip-text {
  color: var(--apple-text-soft);
}

.entry-chip,
.rj-code-value {
  background: rgba(0, 113, 227, 0.08);
  color: var(--apple-blue);
  border: 1px solid rgba(0, 113, 227, 0.1);
}

.detail-shell :deep(.el-alert) {
  border-radius: 18px;
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.detail-shell :deep(.el-descriptions) {
  overflow: hidden;
  border-radius: 18px;
}

.detail-shell :deep(.el-descriptions__table) {
  background: rgba(255, 255, 255, 0.82);
}

.detail-shell :deep(.el-descriptions__label),
.detail-shell :deep(.el-descriptions__content) {
  background: rgba(255, 255, 255, 0.82);
  border-color: rgba(0, 0, 0, 0.05);
}

.manual-source-form :deep(.el-input__wrapper),
.candidate-item :deep(.el-radio__label) {
  font-size: 13px;
}

.manual-source-form :deep(.el-input__wrapper) {
  border-radius: 16px;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06) inset;
  background: rgba(250, 250, 252, 0.94);
}

.manual-source-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.24) inset, 0 0 0 4px rgba(0, 113, 227, 0.08);
}

.candidate-item :deep(.el-radio__input.is-checked .el-radio__inner) {
  background: var(--apple-blue);
  border-color: var(--apple-blue);
}

.subtitle-import-page :deep(.subtitle-import-workbench-dialog .el-dialog) {
  background: linear-gradient(180deg, #fafafc 0%, #f5f5f7 100%);
  box-shadow: 0 32px 90px rgba(15, 23, 42, 0.24);
}

.workbench-background-card {
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.88)),
    var(--apple-bg);
  box-shadow: 0 22px 50px rgba(15, 23, 42, 0.16);
}

.workbench-background-title {
  color: var(--apple-text);
}

.workbench-background-meta,
.workbench-background-active {
  color: var(--apple-text-soft);
}

.hero-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.92fr);
  gap: 22px;
  align-items: stretch;
}

.hero-main {
  display: grid;
  align-content: center;
  gap: 12px;
  min-height: 240px;
}

.hero-eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--apple-blue);
}

.hero-side {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(250, 250, 252, 0.94));
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.hero-side-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--apple-text);
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.hero-metric-card {
  display: grid;
  gap: 4px;
  padding: 14px 14px 12px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(0, 0, 0, 0.04);
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
}

.hero-metric-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--apple-text-muted);
}

.hero-metric-value {
  font-size: 28px;
  line-height: 1.05;
  letter-spacing: -0.3px;
  color: var(--apple-text);
}

.hero-metric-note {
  font-size: 11px;
  color: var(--apple-text-soft);
}

.tab-intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px 14px;
}

.tab-intro-title {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.22px;
  color: var(--apple-text);
}

.tab-intro-desc {
  margin-top: 6px;
  max-width: 760px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--apple-text-soft);
}

.top-panel-grid {
  align-items: stretch;
}

.archive-panel-grid {
  grid-template-columns: minmax(320px, 0.82fr) minmax(520px, 1.48fr);
}

.folder-panel-grid {
  grid-template-columns: minmax(360px, 0.88fr) minmax(520px, 1.32fr);
}

.source-panel-card,
.preview-panel-card {
  min-height: 100%;
}

.panel-header {
  align-items: center;
}

.panel-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.18px;
  color: var(--apple-text);
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--apple-text-muted);
}

.source-panel-card :deep(.el-card__body),
.preview-panel-card :deep(.el-card__body) {
  min-height: 420px;
}

.pending-list {
  max-height: 540px;
}

.detail-shell {
  gap: 12px;
}

.block-box {
  padding: 14px 16px;
}

.candidate-list {
  gap: 10px;
}

.candidate-item,
.pending-item {
  padding: 12px 14px;
}

@media (max-width: 1120px) {
  .hero-shell {
    grid-template-columns: 1fr;
  }

  .hero-main {
    min-height: auto;
  }

  .hero-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .archive-panel-grid,
  .folder-panel-grid {
    grid-template-columns: 1fr;
  }

  .source-panel-card :deep(.el-card__body),
  .preview-panel-card :deep(.el-card__body) {
    min-height: auto;
  }

  .pending-list {
    max-height: none;
  }
}

@media (max-width: 720px) {
  .hero-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
