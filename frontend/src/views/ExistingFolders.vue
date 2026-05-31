<template>
  <div class="existing-page">
    <AppPageHeader
      :icon="FolderInput"
      icon-color="var(--km-nav-folders-icon)"
      title="已有文件夹"
      subtitle="把已解压的 RJ 文件夹放入已有目录，支持社团分层识别、抓取元数据、重命名并按分类规则入库"
    >
      <div class="hero-search-wrap">
        <Search :size="13" class="hero-search-icon" />
        <input v-model="searchQuery" class="hero-search-input" type="text" placeholder="搜索文件夹名、路径或 RJ 号" />
      </div>
      <button type="button" class="ef-head-btn primary btn-refresh" :disabled="loading" @click="refreshWithCache">
        <span class="page-head-btn-icon-swap-container">
          <Loader2 :size="13" :stroke-width="2.6" class="page-head-btn-icon-slot animate-spin" :class="{ 'is-visible': loading }" />
          <RefreshCw :size="13" :stroke-width="2.6" class="page-head-btn-icon-slot ef-head-btn-icon" :class="{ 'is-visible': !loading }" />
        </span>
        <span class="ef-head-btn-label">{{ loading ? '刷新中…' : '刷新列表' }}</span>
      </button>
      <button type="button" class="ef-head-btn ghost btn-rescan" :disabled="loading" @click="refreshForce">
        <span class="ef-head-btn-icon-wrap">
          <RotateCcw :size="13" :stroke-width="2.6" class="ef-head-btn-icon" />
        </span>
        <span class="ef-head-btn-label">重新抓取</span>
      </button>
    </AppPageHeader>

    <section class="existing-shell">
      <aside class="existing-sidebar">
        <div class="sidebar-card">
          <div class="sidebar-head">
            <div>
              <div class="sidebar-overline">处理策略</div>
              <div class="sidebar-title">入库流水线</div>
            </div>
            <span class="sidebar-count">{{ folders.length }}</span>
          </div>

          <div class="pipeline-list">
            <div v-for="step in pipelineSteps" :key="step.label" class="pipeline-item">
              <div class="pipeline-dot" :class="step.tone"><component :is="step.icon" :size="12" /></div>
              <div>
                <div class="pipeline-title">{{ step.label }}</div>
                <div class="pipeline-desc">{{ step.desc }}</div>
              </div>
            </div>
          </div>

          <div class="option-stack">
            <div class="option-row">
              <div class="option-row-main">
                <MoveRight :size="14" />
                <div>
                  <div class="option-row-title">自动分类入库</div>
                  <div class="option-row-desc">处理完成后移动到库存分类目录</div>
                </div>
              </div>
              <button
                type="button"
                class="ef-switch"
                :class="{ checked: autoClassify }"
                role="switch"
                :aria-checked="autoClassify"
                aria-label="自动分类入库"
                @click="autoClassify = !autoClassify"
              >
                <span class="ef-switch-thumb"></span>
              </button>
            </div>
            <div class="option-row">
              <div class="option-row-main">
                <ShieldCheck :size="14" />
                <div>
                  <div class="option-row-title">扫描时查重</div>
                  <div class="option-row-desc">刷新列表时检查重复与关联作品</div>
                </div>
              </div>
              <button
                type="button"
                class="ef-switch"
                :class="{ checked: checkDuplicates }"
                role="switch"
                :aria-checked="checkDuplicates"
                aria-label="扫描时查重"
                @click="checkDuplicates = !checkDuplicates"
              >
                <span class="ef-switch-thumb"></span>
              </button>
            </div>
          </div>

          <div class="sidebar-actions">
            <button
              type="button"
              class="side-ep-action primary"
              :disabled="selectedProcessableFolders.length === 0 || processing"
              :aria-busy="processing"
              @click="handleProcess"
            >
              <span class="side-button-icon-wrap">
                <Loader2 v-if="processing" :size="13" :stroke-width="2.5" class="side-button-icon animate-spin" />
                <Play v-else :size="13" :stroke-width="2.5" class="side-button-icon" />
              </span>
              <span class="side-action-label">处理选中</span>
              <span v-if="selectedProcessableFolders.length" class="side-action-count">{{ selectedProcessableFolders.length }}</span>
            </button>
            <button
              type="button"
              class="side-ep-action"
              :disabled="selectedCheckableFolders.length === 0 || checkingDuplicates"
              :aria-busy="checkingDuplicates"
              @click="checkSelectedDuplicates"
            >
              <span class="side-button-icon-wrap">
                <Loader2 v-if="checkingDuplicates" :size="13" :stroke-width="2.5" class="side-button-icon animate-spin" />
                <SearchCheck v-else :size="13" :stroke-width="2.5" class="side-button-icon" />
              </span>
              <span class="side-action-label">检查选中项</span>
              <span v-if="selectedCheckableFolders.length" class="side-action-count">{{ selectedCheckableFolders.length }}</span>
            </button>
          </div>
        </div>
      </aside>

      <main class="existing-main">
        <!-- 顶部状态条：4 列指标（lib-info-strip 风格，对齐其他页面） -->
        <section class="ef-info-strip">
          <div class="ef-info-item">
            <Folder :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-blue" />
            <div class="ef-info-body">
              <div class="ef-info-label">总数</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(folders.length)">{{ folders.length }}</b>
                </Transition>
                <span class="ef-info-meta">个文件夹</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <CheckCircle2 :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-emerald" />
            <div class="ef-info-body">
              <div class="ef-info-label">可处理</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(readyCount)">{{ readyCount }}</b>
                </Transition>
                <span class="ef-info-meta">个就绪</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <AlertTriangle :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-amber" />
            <div class="ef-info-body">
              <div class="ef-info-label">冲突</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(conflictCount)">{{ conflictCount }}</b>
                </Transition>
                <span class="ef-info-meta">个待解决</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <Hash :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-slate" />
            <div class="ef-info-body">
              <div class="ef-info-label">已选</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(selectedFolders.length)">{{ selectedFolders.length }}</b>
                </Transition>
                <span class="ef-info-meta">个已选项</span>
              </div>
            </div>
          </div>
        </section>

        <section class="folders-card">
          <Transition name="ef-section">
            <div v-if="loading" class="scan-banner">
              <AppLoadingAnimation variant="inline" :size="34" />
              <div>
                <div class="scan-title">正在扫描文件夹</div>
                <div class="scan-desc">已发现 {{ folders.length }} 个目录，查重结果会分批更新</div>
              </div>
            </div>
          </Transition>

          <TransitionGroup
            v-if="filteredFolders.length"
            tag="div"
            name="ef-grid"
            class="folder-grid"
          >
            <article
              v-for="(folder, idx) in filteredFolders"
              :key="folder.path"
              class="folder-card"
              :class="{ selected: isSelected(folder), conflict: isConflict(folder), unrecognized: isUnrecognized(folder) }"
              :style="{ '--ef-grid-delay': `${Math.min(idx, 14) * 30}ms` }"
            >
              <div class="folder-card-head">
                <button
                  type="button"
                  class="select-toggle"
                  :class="{ active: isSelected(folder) }"
                  :disabled="!canSelectFolder(folder)"
                  :aria-label="isSelected(folder) ? '取消选择' : '选择文件夹'"
                  @click="toggleFolderSelection(folder)"
                >
                  <Check :size="13" />
                </button>
                <div class="folder-main-info">
                  <div class="folder-name-row">
                    <div class="folder-name" :title="folder.name">{{ folder.name }}</div>
                    <span v-if="folder.is_nested" class="folder-depth-chip">社团分层</span>
                  </div>
                  <div class="folder-path" :title="folder.path">{{ getFolderDisplayPath(folder) }}</div>
                  <div v-if="folder.is_nested" class="folder-root" :title="folder.path">
                    源目录：{{ folder.source_root_name || '上级目录' }}
                  </div>
                </div>
                <span class="status-pill" :class="getFolderState(folder).tone">
                  <AlertTriangle v-if="getFolderState(folder).icon === 'alert'" :size="11" />
                  <RefreshCw v-else-if="getFolderState(folder).icon === 'refresh'" :size="11" class="animate-spin" />
                  <Clock3 v-else-if="getFolderState(folder).icon === 'clock'" :size="11" />
                  <XCircle v-else-if="getFolderState(folder).icon === 'x'" :size="11" />
                  <ShieldCheck v-else-if="getFolderState(folder).icon === 'shield'" :size="11" />
                  <CheckCircle2 v-else :size="11" />
                  {{ getFolderState(folder).label }}
                </span>
              </div>

              <div class="folder-meta-row">
                <span class="folder-meta rj" :class="{ missing: isUnrecognized(folder) }"><Hash :size="11" /> {{ folder.rjcode || '未识别 RJ' }}</span>
                <span v-if="folder.is_nested" class="folder-meta route"><FolderTree :size="11" /> {{ folder.relative_path }}</span>
                <span class="folder-meta"><HardDrive :size="11" /> 大小 {{ formatFileSize(folder.folder_size || folder.size) }}</span>
                <span class="folder-meta"><Clock3 :size="11" /> 修改 {{ formatDate(folder.modified_time) }}</span>
              </div>

              <Transition name="ef-section">
                <div v-if="isConflict(folder)" class="conflict-box">
                  <AlertTriangle :size="14" />
                  <div>
                    <div class="conflict-title">{{ getConflictTypeLabel(folder.duplicate_info?.conflict_type) }}</div>
                    <div class="conflict-desc">库中已有相同或关联作品，请查看冲突后选择处理方案</div>
                  </div>
                </div>
              </Transition>

              <div class="folder-actions">
                <button v-if="isConflict(folder)" type="button" class="card-action warning" @click="showDuplicateDetail(folder)">
                  <Eye :size="13" /> 查看冲突
                </button>
                <button v-else type="button" class="card-action primary" :disabled="processing || !isProcessable(folder)" @click="handleProcessSingle(folder)">
                  <Play :size="13" /> {{ isUnrecognized(folder) ? '等待识别' : '重命名并入库' }}
                </button>
                <button type="button" class="card-action" :disabled="checkingDuplicates || !isCheckable(folder)" @click="handleRefreshFolder(folder)">
                  <RefreshCw :size="13" :class="{ 'animate-spin': folder.status === 'checking' }" /> 查重
                </button>
                <button type="button" class="card-action danger" @click="handleDeleteFolder(folder)">
                  <Trash2 :size="13" /> 删除
                </button>
              </div>
            </article>
          </TransitionGroup>

          <AppEmptyState v-else :description="loading ? '正在读取已有文件夹目录' : '暂无可处理文件夹，请把 RJ 文件夹放入已存在文件夹目录后刷新'" />
        </section>
      </main>
    </section>

    <el-dialog v-model="resultDialogVisible" width="560px" class="existing-dialog result-dialog" :show-close="false">
      <template #header>
        <div class="dialog-header">
          <div class="dialog-title-wrap">
            <div class="dialog-icon" :class="resultData.success ? 'success' : 'warning'">
              <CheckCircle2 v-if="resultData.success" :size="18" />
              <AlertTriangle v-else :size="18" />
            </div>
            <div>
              <div class="dialog-title">任务创建结果</div>
              <div class="dialog-subtitle">{{ resultData.success ? '任务已进入队列，可在任务中心查看进度' : '请检查错误信息后重试' }}</div>
            </div>
          </div>
          <button type="button" class="dialog-close" @click="resultDialogVisible = false">
            <XCircle :size="18" />
          </button>
        </div>
      </template>

      <div class="result-panel" :class="resultData.success ? 'success' : 'warning'">
        <div class="result-title">{{ resultData.success ? '已创建处理任务' : '创建失败' }}</div>
        <div class="result-message">{{ resultData.message }}</div>
      </div>

      <div v-if="resultData.tasks?.length" class="task-list">
        <div class="task-list-title">任务明细</div>
        <div v-for="task in resultData.tasks" :key="task.task_id" class="task-row">
          <span class="task-id">{{ task.task_id.substring(0, 8) }}</span>
          <span class="task-path">{{ getFolderName(task.folder_path) }}</span>
          <span class="task-status">已排队</span>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button class="dialog-ep-btn" @click="resultDialogVisible = false">关闭</el-button>
          <el-button class="dialog-ep-btn primary" @click="goToTasks">查看任务队列</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="duplicateDetailVisible" title="冲突详情" width="720px" class="existing-dialog">
      <div v-if="duplicateDetailData" class="duplicate-panel">
        <div class="conflict-box large">
          <AlertTriangle :size="16" />
          <div>
            <div class="conflict-title">{{ getConflictTypeLabel(duplicateDetailData.conflict_type) }}</div>
            <div class="conflict-desc">{{ duplicateDetailData.analysis_info?.current_work ? `当前作品类型：${duplicateDetailData.analysis_info.current_work.work_type} / ${duplicateDetailData.analysis_info.current_work.lang}` : '请选择处理方案后继续' }}</div>
          </div>
        </div>

        <div v-if="duplicateDetailData.direct_duplicate" class="detail-card">
          <div class="detail-title">直接重复</div>
          <div class="detail-line">RJ：{{ duplicateDetailData.direct_duplicate.rjcode }}</div>
          <div class="detail-line">路径：{{ duplicateDetailData.direct_duplicate.path }}</div>
        </div>

        <div v-if="duplicateDetailData.linked_works_found?.length" class="detail-card">
          <div class="detail-title">关联作品</div>
          <div v-for="work in duplicateDetailData.linked_works_found" :key="work.rjcode" class="linked-row">
            <span>{{ work.rjcode }}</span>
            <span>{{ work.work_name }}</span>
            <span>{{ work.lang || '-' }}</span>
          </div>
        </div>

        <div v-if="duplicateDetailData.resolution_options?.length" class="resolution-list">
          <button
            v-for="option in duplicateDetailData.resolution_options"
            :key="option.action"
            type="button"
            class="resolution-option"
            :class="{ active: selectedResolution === option.action, recommend: option.recommend }"
            @click="selectedResolution = option.action"
          >
            <span class="resolution-title">{{ option.label }}</span>
            <span class="resolution-desc">{{ option.description }}</span>
          </button>
        </div>
      </div>
      <template #footer>
        <button type="button" class="dialog-btn" @click="duplicateDetailVisible = false">关闭</button>
        <button type="button" class="dialog-btn primary" @click="handleProcessWithResolution">确认处理</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock3,
  Eye,
  FileSearch,
  Folder,
  FolderInput,
  FolderTree,
  HardDrive,
  Hash,
  Loader2,
  MoveRight,
  PencilLine,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  SearchCheck,
  ShieldCheck,
  Tags,
  Trash2,
  XCircle
} from 'lucide-vue-next'
import { apiFetchOptions, apiUrl, existingFolderApi } from '../api'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import { showSystemConfirm } from '../composables/useSystemPrompt'

const router = useRouter()

const loading = ref(false)
const processing = ref(false)
const checkingDuplicates = ref(false)
const folders = ref([])
const selectedFolders = ref([])
const searchQuery = ref('')
const autoClassify = ref(true)
const checkDuplicates = ref(true)
const conflictCount = ref(0)
const resultDialogVisible = ref(false)
const resultData = ref({ success: true, message: '', tasks: [] })
const duplicateDetailVisible = ref(false)
const duplicateDetailData = ref(null)
const selectedResolution = ref('')
const currentConflictFolder = ref(null)

const pipelineSteps = [
  { label: '识别 RJ', desc: '从文件夹名提取作品编号', icon: Tags, tone: 'info' },
  { label: '抓取元数据', desc: '补齐标题、社团与发售日', icon: FileSearch, tone: 'ok' },
  { label: '重命名', desc: '按模板规范化目录名', icon: PencilLine, tone: 'warn' },
  { label: '分类入库', desc: '移动到库存分类目录', icon: MoveRight, tone: 'done' }
]

const filteredFolders = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return folders.value
  return folders.value.filter((folder) =>
    String(folder.name || '').toLowerCase().includes(query) ||
    String(folder.rjcode || '').toLowerCase().includes(query) ||
    String(folder.relative_path || '').toLowerCase().includes(query) ||
    String(folder.source_root_name || '').toLowerCase().includes(query) ||
    String(folder.path || '').toLowerCase().includes(query)
  )
})

const selectedProcessableFolders = computed(() => selectedFolders.value.filter(isProcessable))
const selectedCheckableFolders = computed(() => selectedFolders.value.filter(isCheckable))
const readyCount = computed(() => folders.value.filter(isProcessable).length)

onMounted(() => {
  refreshWithCache()
})

async function consumeNdjsonResponse(response, { forceRefresh = false } = {}) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const data = JSON.parse(line)
      if (data.type === 'folder') {
        folders.value = [...folders.value, data.folder]
      } else if (data.type === 'folder_update') {
        const index = folders.value.findIndex((folder) => folder.path === data.folder.path)
        if (index !== -1) {
          folders.value[index] = { ...folders.value[index], ...data.folder }
          folders.value = [...folders.value]
        }
      } else if (data.type === 'complete') {
        conflictCount.value = folders.value.filter(isConflict).length
        let msg = data.message || `扫描完成，找到 ${folders.value.length} 个文件夹`
        if (forceRefresh) msg += '，已重新抓取'
        ElMessage.success(msg)
      } else if (data.type === 'error') {
        ElMessage.error(data.error || '扫描失败')
      }
    }
  }
}

async function refreshFoldersWithOptions(forceRefresh = false) {
  loading.value = true
  folders.value = []
  selectedFolders.value = []
  conflictCount.value = 0
  try {
    const url = apiUrl(`/existing-folders/scan?check_duplicates=${checkDuplicates.value}&force_refresh=${forceRefresh}`)
    const response = await fetch(url, apiFetchOptions({ method: 'POST', headers: { Accept: 'application/x-ndjson' } }))
    await consumeNdjsonResponse(response, { forceRefresh })
  } catch (error) {
    console.error('获取文件夹列表失败:', error)
    ElMessage.error('获取失败: ' + (error.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function refreshWithCache() {
  return refreshFoldersWithOptions(false)
}

async function refreshForce() {
  try {
    await showSystemConfirm({
      title: '重新抓取已有文件夹',
      message: '将清除已有文件夹缓存并重新查询查重信息，目录较多时会更慢。',
      tone: 'warning',
      confirmText: '重新抓取'
    })
    await existingFolderApi.refreshCache()
    await refreshFoldersWithOptions(true)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('刷新失败: ' + (error.message || '未知错误'))
  }
}

function isConflict(folder) {
  return Boolean(folder?.duplicate_info?.is_duplicate)
}

function isUnrecognized(folder) {
  return !folder?.rjcode || folder.status === 'unrecognized'
}

function isCheckable(folder) {
  return Boolean(folder?.rjcode) && folder.status !== 'checking'
}

function isProcessable(folder) {
  return Boolean(folder?.rjcode) && !isConflict(folder) && folder.status !== 'unrecognized'
}

function canSelectFolder(folder) {
  return isCheckable(folder)
}

function isSelected(folder) {
  return selectedFolders.value.some((item) => item.path === folder.path)
}

function toggleFolderSelection(folder) {
  if (!canSelectFolder(folder)) {
    ElMessage.warning('这个目录还没有识别到 RJ 号，不能加入处理队列')
    return
  }
  if (isSelected(folder)) {
    selectedFolders.value = selectedFolders.value.filter((item) => item.path !== folder.path)
  } else {
    selectedFolders.value = [...selectedFolders.value, folder]
  }
}

function getFolderState(folder) {
  if (isConflict(folder)) return { label: getConflictTypeLabel(folder.duplicate_info?.conflict_type), tone: 'danger', icon: 'alert' }
  if (isUnrecognized(folder)) return { label: '未识别 RJ', tone: 'muted', icon: 'x' }
  if (folder.status === 'checking') return { label: '检查中', tone: 'warning', icon: 'refresh' }
  if (folder.status === 'pending') return { label: '待检查', tone: 'muted', icon: 'clock' }
  if (folder.status === 'error') return { label: '检查失败', tone: 'danger', icon: 'x' }
  if (folder.status === 'cached') return { label: '已检查', tone: 'info', icon: 'shield' }
  return { label: '可处理', tone: 'success', icon: 'check' }
}

async function handleProcess() {
  if (!selectedProcessableFolders.value.length) {
    ElMessage.warning('没有可处理的选中目录')
    return
  }
  processing.value = true
  try {
    const data = await existingFolderApi.process(selectedProcessableFolders.value.map((folder) => folder.path), autoClassify.value)
    resultData.value = { success: true, message: data.message, tasks: data.tasks || [] }
    resultDialogVisible.value = true
    selectedFolders.value = []
  } catch (error) {
    resultData.value = { success: false, message: error.response?.data?.detail || error.message, tasks: [] }
    resultDialogVisible.value = true
  } finally {
    processing.value = false
  }
}

async function checkSelectedDuplicates() {
  if (!selectedCheckableFolders.value.length) {
    ElMessage.warning('没有可查重的选中目录')
    return
  }
  checkingDuplicates.value = true
  try {
    const data = await existingFolderApi.checkDuplicates(selectedCheckableFolders.value.map((folder) => folder.path), { checkLinkedWorks: true })
    applyDuplicateResults(data.results || [])
    ElMessage[data.duplicate_count > 0 ? 'warning' : 'success'](data.message || '查重完成')
  } catch (error) {
    ElMessage.error('查重检查失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    checkingDuplicates.value = false
  }
}

function applyDuplicateResults(results) {
  results.forEach((result) => {
    const index = folders.value.findIndex((folder) => folder.path === result.folder_path)
    if (index === -1) return
    folders.value[index] = {
      ...folders.value[index],
      status: result.error && !result.rjcode ? 'unrecognized' : (result.error ? 'error' : 'checked'),
      duplicate_info: result.error ? { error: result.error } : {
        is_duplicate: result.is_duplicate,
        conflict_type: result.conflict_type,
        direct_duplicate: result.direct_duplicate,
        linked_works_found: result.linked_works_found,
        related_rjcodes: result.related_rjcodes,
        analysis_info: result.analysis_info,
        resolution_options: result.resolution_options
      }
    }
  })
  folders.value = [...folders.value]
  conflictCount.value = folders.value.filter(isConflict).length
}

function showDuplicateDetail(row) {
  currentConflictFolder.value = row
  duplicateDetailData.value = row.duplicate_info
  const options = row.duplicate_info?.resolution_options || []
  selectedResolution.value = options.find((option) => option.recommend)?.action || options[0]?.action || ''
  duplicateDetailVisible.value = true
}

async function handleProcessWithResolution() {
  if (!selectedResolution.value) {
    ElMessage.warning('请先选择一个处理方案')
    return
  }
  const selectedOption = duplicateDetailData.value?.resolution_options?.find((option) => option.action === selectedResolution.value)
  try {
    await showSystemConfirm({
      title: '确认处理冲突',
      message: `确定要执行「${selectedOption?.label || selectedResolution.value}」吗？`,
      tone: selectedResolution.value === 'SKIP' ? 'danger' : 'info',
      confirmText: '确认处理'
    })
    const data = await existingFolderApi.processWithResolution(currentConflictFolder.value?.path, selectedResolution.value, autoClassify.value)
    ElMessage.success(data.message || '操作成功')
    duplicateDetailVisible.value = false
    await refreshWithCache()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('处理失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleDeleteFolder(row) {
  try {
    await showSystemConfirm({
      title: '删除已有文件夹',
      message: `确定要删除「${row.name}」吗？此操作不可恢复。`,
      tone: 'danger',
      confirmText: '确认删除'
    })
    await existingFolderApi.delete(row.path)
    ElMessage.success('文件夹已删除')
    await refreshWithCache()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleRefreshFolder(row) {
  if (!isCheckable(row)) {
    ElMessage.warning('这个目录还没有识别到 RJ 号，不能查重')
    return
  }
  checkingDuplicates.value = true
  try {
    const index = folders.value.findIndex((folder) => folder.path === row.path)
    if (index !== -1) folders.value[index] = { ...folders.value[index], status: 'checking' }
    folders.value = [...folders.value]
    const data = await existingFolderApi.checkDuplicates([row.path], { checkLinkedWorks: true })
    applyDuplicateResults(data.results || [])
    ElMessage[data.duplicate_count > 0 ? 'warning' : 'success'](data.duplicate_count > 0 ? '发现冲突' : '查重完成，无冲突')
  } catch (error) {
    ElMessage.error('刷新失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    checkingDuplicates.value = false
  }
}

async function handleProcessSingle(row) {
  if (!isProcessable(row)) {
    ElMessage.warning(isConflict(row) ? '这个目录有冲突，请先查看冲突详情' : '这个目录还没有识别到 RJ 号')
    return
  }
  try {
    await showSystemConfirm({
      title: '处理已有文件夹',
      message: `将对「${row.name}」执行元数据抓取、重命名、过滤和分类入库。`,
      tone: 'info',
      confirmText: '开始处理'
    })
    processing.value = true
    const data = await existingFolderApi.process([row.path], autoClassify.value)
    resultData.value = { success: true, message: data.message, tasks: data.tasks || [] }
    resultDialogVisible.value = true
    setTimeout(() => refreshWithCache(), 1000)
  } catch (error) {
    if (error !== 'cancel') {
      resultData.value = { success: false, message: error.response?.data?.detail || error.message, tasks: [] }
      resultDialogVisible.value = true
    }
  } finally {
    processing.value = false
  }
}

function getFolderName(path) {
  if (!path) return ''
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1]
}

function getFolderDisplayPath(folder) {
  if (folder?.relative_path) return folder.relative_path
  return folder?.path || ''
}

function goToTasks() {
  resultDialogVisible.value = false
  router.push('/tasks')
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '未知'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(value) / Math.log(1024))
  return `${parseFloat((value / Math.pow(1024, i)).toFixed(2))} ${sizes[i]}`
}

function formatDate(dateStr) {
  if (!dateStr) return '时间未知'
  const date = new Date(String(dateStr).trim().replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function getConflictTypeLabel(conflictType) {
  const labels = {
    DUPLICATE: '直接重复',
    LINKED_WORK_ORIGINAL: '原作已存在',
    LINKED_WORK_TRANSLATION: '翻译版已存在',
    LINKED_WORK_CHILD: '子版本已存在',
    LINKED_WORK: '关联作品',
    LANGUAGE_VARIANT: '语言变体',
    MULTIPLE_VERSIONS: '多版本'
  }
  return labels[conflictType] || '冲突'
}
</script>

<style scoped>
.existing-page,
:global(.existing-dialog) {
  --ef-page-bg: transparent;
  --ef-surface: #ffffff;
  --ef-surface-soft: #f8fafc;
  --ef-surface-muted: #f1f5f9;
  --ef-surface-hover: #fafbfc;
  --ef-text: #0f172a;
  --ef-text-soft: #334155;
  --ef-muted: #64748b;
  --ef-faint: #94a3b8;
  --ef-border: #e2e8f0;
  --ef-border-soft: rgba(15, 23, 42, 0.08);
  --ef-border-strong: rgba(15, 23, 42, 0.18);
  --ef-primary: #111827;
  --ef-primary-hover: #1f2937;
  --ef-primary-soft: rgba(15, 23, 42, 0.06);
  --ef-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
  --ef-shadow-hover: 0 18px 36px rgba(15, 23, 42, 0.1);
  --ef-conflict-bg: #fff7ed;
  --ef-conflict-border: #fed7aa;
  --ef-conflict-text: #9a3412;
  --ef-conflict-muted: #b45309;
  color: var(--ef-text);
  background: var(--ef-page-bg);
}

:global(html.kikoerumanager-dark .existing-page),
:global(html.kikoerumanager-dark .existing-dialog) {
  --ef-page-bg: transparent;
  --ef-surface: #151515;
  --ef-surface-soft: #1b1b1d;
  --ef-surface-muted: #242427;
  --ef-surface-hover: #202023;
  --ef-text: #f5f5f5;
  --ef-text-soft: #d4d4d8;
  --ef-muted: #a1a1aa;
  --ef-faint: #71717a;
  --ef-border: rgba(255, 255, 255, 0.11);
  --ef-border-soft: rgba(255, 255, 255, 0.08);
  --ef-border-strong: rgba(255, 255, 255, 0.18);
  --ef-primary: #e5e7eb;
  --ef-primary-hover: #ffffff;
  --ef-primary-soft: rgba(255, 255, 255, 0.08);
  --ef-shadow: 0 14px 36px rgba(0, 0, 0, 0.24);
  --ef-shadow-hover: 0 20px 42px rgba(0, 0, 0, 0.32);
  --ef-conflict-bg: rgba(127, 29, 29, 0.16);
  --ef-conflict-border: rgba(248, 113, 113, 0.28);
  --ef-conflict-text: #fca5a5;
  --ef-conflict-muted: #f87171;
}

.existing-page {
  max-width: 1480px;
  margin: 0 auto;
  padding: 22px;
}

/* ============================================================
 * 页头搜索框 + page-head-btn 规范按钮（对齐 ASMR 同步页 / 操作记录页）
 * ============================================================ */
.hero-search-wrap { position: relative; width: min(360px, 42vw); }
.hero-search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--ef-faint); pointer-events: none; transition: color 0.2s ease; }
.hero-search-input { width: 100%; height: 36px; padding: 0 14px 0 34px; border: 1px solid var(--ef-border-soft); border-radius: 10px; outline: none; background: var(--ef-surface); font-size: 13px; color: var(--ef-text); transition: border-color 0.25s ease, box-shadow 0.25s ease, background-color 0.25s ease; }
.hero-search-input::placeholder { color: var(--ef-faint); }
.hero-search-input:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-soft); }
.hero-search-input:focus { border-color: var(--ef-primary); background: var(--ef-surface); box-shadow: 0 0 0 3px var(--ef-primary-soft); }
.hero-search-wrap:focus-within .hero-search-icon { color: var(--ef-primary); }

.ef-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--ef-border-soft);
  background: var(--ef-surface);
  color: var(--ef-text-soft);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  overflow: hidden;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
  will-change: transform, opacity;
}
.ef-head-btn :deep(.ef-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.ef-head-btn :deep(svg) { flex-shrink: 0; }
.ef-head-btn-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  position: relative;
}
.ef-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.ef-head-btn:active:not(:disabled) {
  transform: scale(0.96);
  transition:
    transform 0.12s ease,
    box-shadow 0.18s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    opacity 0.2s ease;
}
.ef-head-btn:active:not(:disabled) :deep(.ef-head-btn-icon) {
  transform: scale(0.82);
  transition: transform 0.12s ease;
}
/* disabled：仅改 opacity / cursor，不重置 transform / shadow，避免点击瞬间塌回闪烁 */
.ef-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* primary：黑灰渐变 + shimmer 高光（对齐 ASMR 同步页 page-head-btn.primary） */
.ef-head-btn.primary {
  background: linear-gradient(135deg, var(--ef-primary), var(--ef-primary-hover));
  color: var(--ef-surface);
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.ef-head-btn.primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -120%;
  width: 60%;
  height: 100%;
  background: linear-gradient(100deg, transparent 0%, rgba(255,255,255,0.05) 30%, rgba(255,255,255,0.28) 50%, rgba(255,255,255,0.05) 70%, transparent 100%);
  transform: skewX(-18deg);
  transition: left 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
.ef-head-btn.primary:hover {
  background: linear-gradient(135deg, var(--ef-primary-hover), var(--ef-primary));
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.28), 0 0 0 4px rgba(15, 23, 42, 0.05);
}
.ef-head-btn.primary:hover::before { left: 130%; }

/* ghost：白底纯色 transition（gradient 不能 transition 会瞬切） */
.ef-head-btn.ghost { background-color: var(--ef-surface); }
.ef-head-btn.ghost:hover { background-color: var(--ef-surface-soft); border-color: var(--ef-border-strong); }

/* 各按钮专属图标动效 */
.ef-head-btn.btn-refresh:hover :deep(.ef-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.7s cubic-bezier(0.4, 0, 0.2, 1);
}
.ef-head-btn.btn-rescan:hover :deep(.ef-head-btn-icon) {
  transform: rotate(-180deg) scale(1.12);
}

.ef-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.ef-head-btn.primary .ef-head-btn-label { min-width: 56px; }
.ef-head-btn.ghost .ef-head-btn-label { min-width: 56px; }
.ef-head-btn:hover .ef-head-btn-label { letter-spacing: 0.04em; }

/* 图标 swap Transition */
.ef-head-btn :deep(.ef-head-icon-swap-enter-active) {
  transition:
    opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.ef-head-btn :deep(.ef-head-icon-swap-leave-active) {
  transition: opacity 0.14s ease, transform 0.18s ease;
  position: absolute;
}
.ef-head-btn :deep(.ef-head-icon-swap-enter-from) {
  opacity: 0;
  transform: scale(0.4) rotate(-90deg);
}
.ef-head-btn :deep(.ef-head-icon-swap-leave-to) {
  opacity: 0;
  transform: scale(0.4) rotate(90deg);
}

/* ============================================================
 * 顶部状态条 ef-info-strip（对齐 lib-info-strip 风格）
 * ============================================================ */
.ef-info-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  margin-bottom: 14px;
  padding: 16px 20px;
  border-radius: 14px;
  background: var(--ef-surface);
  border: 1px solid var(--ef-border-soft);
  box-shadow: var(--ef-shadow);
}
.ef-info-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  padding: 0 18px;
}
.ef-info-item:first-child { padding-left: 0; }
.ef-info-item:last-child { padding-right: 0; }
.ef-info-icon { flex-shrink: 0; margin-top: 3px; }
.ef-info-icon-blue { color: #3b82f6; }
.ef-info-icon-emerald { color: #10b981; }
.ef-info-icon-amber { color: #f59e0b; }
.ef-info-icon-slate { color: var(--ef-muted); }
.ef-info-body { min-width: 0; flex: 1 1 auto; }
.ef-info-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ef-faint);
  margin-bottom: 4px;
}
.ef-info-value {
  font-size: 13.5px;
  color: var(--ef-muted);
  line-height: 1.3;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 1.5em;
  position: relative;
}
.ef-info-value > b {
  font-weight: 700;
  font-size: 20px;
  letter-spacing: -0.4px;
  color: var(--ef-text);
  font-variant-numeric: tabular-nums;
  display: inline-block;
  transform-origin: center;
}
.ef-info-meta { color: var(--ef-faint); font-size: 12px; }
.ef-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--ef-border-strong), transparent);
  align-self: stretch;
}
@media (max-width: 980px) {
  .ef-info-strip { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); padding: 12px 14px; gap: 12px 0; }
  .ef-info-divider { display: none; }
  .ef-info-item { padding: 0 8px; }
}

/* 数字 fade flip（mode="out-in"） */
.ef-num-flip-enter-active {
  transition:
    opacity 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.ef-num-flip-leave-active {
  transition: opacity 0.18s ease, transform 0.2s ease;
}
.ef-num-flip-enter-from { opacity: 0; transform: translateY(-8px) scale(0.85); }
.ef-num-flip-leave-to   { opacity: 0; transform: translateY(8px) scale(0.85); }

/* ============================================================
 * 主体布局：左侧栏 + 右侧主区
 * ============================================================ */
.existing-shell { display: grid; grid-template-columns: 310px minmax(0,1fr); gap: 18px; margin-top: 18px; }
.sidebar-card, .folders-card { border: 1px solid var(--ef-border); border-radius: 20px; background: var(--ef-surface); box-shadow: var(--ef-shadow); }
.sidebar-card { padding: 16px; position: sticky; top: 18px; }
.sidebar-head, .folder-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.sidebar-overline { color: var(--ef-faint); font-size: 11px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
.sidebar-title { font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.sidebar-count { min-width: 30px; height: 24px; border-radius: 999px; display: grid; place-items: center; background: var(--ef-surface-muted); color: var(--ef-text-soft); font-size: 12px; font-weight: 900; transition: background-color 0.25s ease, color 0.25s ease; }
.pipeline-list { margin-top: 16px; display: grid; gap: 12px; }
.pipeline-item { display: flex; gap: 10px; align-items: flex-start; padding: 10px; border-radius: 14px; background: var(--ef-surface-soft); border: 1px solid var(--ef-border); transition: border-color 0.25s ease, background-color 0.25s ease; }
.pipeline-item:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-hover); }
.pipeline-dot { width: 26px; height: 26px; flex: 0 0 auto; border-radius: 11px; display: grid; place-items: center; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.pipeline-item:hover .pipeline-dot { transform: scale(1.1); }
.pipeline-dot.info { background: rgba(59, 130, 246, 0.12); color: #3b82f6; } .pipeline-dot.ok { background: rgba(16, 185, 129, 0.12); color: #10b981; } .pipeline-dot.warn { background: rgba(245, 158, 11, 0.12); color: #f59e0b; } .pipeline-dot.done { background: var(--ef-surface-muted); color: var(--ef-text); }
.pipeline-title { font-size: 13px; font-weight: 900; }
.pipeline-desc { margin-top: 2px; font-size: 11px; color: var(--ef-muted); line-height: 1.45; }
.option-stack { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 16px; }
.option-row { min-height: 58px; border: 1px solid var(--ef-border); border-radius: 14px; background: var(--ef-surface-soft); display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; transition: border-color 0.25s ease; }
.option-row:hover { border-color: var(--ef-border-strong); }
.option-row-main { min-width: 0; display: flex; align-items: center; gap: 10px; color: var(--ef-muted); }
.option-row-title { color: var(--ef-text); font-size: 13px; font-weight: 900; line-height: 1.2; }
.option-row-desc { margin-top: 3px; color: var(--ef-faint); font-size: 11px; line-height: 1.35; }
.ef-switch {
  width: 30px;
  height: 18px;
  flex: 0 0 auto;
  border: 1px solid var(--ef-border-strong);
  border-radius: 999px;
  background: var(--ef-surface-muted);
  padding: 2px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  cursor: pointer;
  box-shadow: inset 0 1px 1px rgba(0, 0, 0, 0.08);
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    box-shadow 0.25s ease;
}
.ef-switch:hover {
  transform: translateY(-1px) scale(1.03);
  border-color: var(--ef-border-strong);
  background: var(--ef-surface-hover);
}
.ef-switch:active { transform: scale(0.94); transition: transform 0.12s ease; }
.ef-switch.checked {
  justify-content: flex-end;
  background: var(--ef-text-soft);
  border-color: var(--ef-text-soft);
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.1);
}
.ef-switch-thumb {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: var(--ef-surface);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.18);
  transition:
    background-color 0.25s ease,
    box-shadow 0.25s ease,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.ef-switch:hover .ef-switch-thumb { transform: scale(1.04); }
.ef-switch.checked .ef-switch-thumb { background: var(--ef-surface); }

/* ============================================================
 * 侧边栏按钮（应用防闪烁规则）
 * ============================================================ */
.sidebar-actions { margin-top: 16px; display: grid; gap: 9px; }
.side-ep-action {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--ef-border);
  border-radius: 10px;
  background: var(--ef-surface-soft);
  color: var(--ef-text-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 11px;
  font-weight: 800;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
}
.side-ep-action:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--ef-border-strong);
  background: var(--ef-surface-hover);
  box-shadow: var(--ef-shadow-hover);
}
.side-ep-action:active:not(:disabled) {
  transform: scale(0.96);
  transition: transform 0.12s ease;
}
.side-ep-action:disabled {
  background: var(--ef-surface-soft);
  border-color: var(--ef-border);
  color: var(--ef-faint);
  cursor: not-allowed;
  opacity: 1;
  box-shadow: none;
}
.side-ep-action.primary {
  background: var(--ef-primary);
  border-color: var(--ef-primary);
  color: var(--ef-surface);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
}
.side-ep-action.primary:hover:not(:disabled) {
  background: var(--ef-primary-hover);
  border-color: var(--ef-primary-hover);
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.22);
}
.side-ep-action.primary:disabled {
  background: color-mix(in srgb, var(--ef-surface-muted) 72%, transparent);
  border-color: var(--ef-border);
  color: var(--ef-faint);
  box-shadow: none;
}
.side-button-icon-wrap {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
}
.side-button-icon {
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease;
}
.side-ep-action:hover:not(:disabled) .side-button-icon { transform: rotate(-8deg) scale(1.08); }
.side-action-label { min-width: 0; white-space: nowrap; }
.side-action-count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  display: inline-grid;
  place-items: center;
  background: color-mix(in srgb, currentColor 12%, transparent);
  color: currentColor;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

/* ============================================================
 * 主区：扫描横幅 + 文件夹网格
 * ============================================================ */
.folders-card { padding: 16px; min-height: 420px; }
.scan-banner { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; padding: 12px; border-radius: 14px; background: var(--ef-surface-soft); border: 1px dashed var(--ef-border-strong); }
.scan-title { font-weight: 900; font-size: 13px; }
.scan-desc { color: var(--ef-muted); font-size: 12px; margin-top: 2px; }
.folder-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 13px; }
.folder-card { border: 1px solid var(--ef-border); border-radius: 16px; padding: 14px; background: var(--ef-surface); transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.25s ease, background-color 0.25s ease; }
.folder-card:hover { transform: translateY(-3px); box-shadow: var(--ef-shadow-hover); border-color: var(--ef-border-strong); }
.folder-card.selected { border-color: var(--ef-primary); box-shadow: inset 0 0 0 1px var(--ef-primary), var(--ef-shadow); }
.folder-card.conflict { background: var(--ef-conflict-bg); border-color: var(--ef-conflict-border); }
.folder-card.conflict.selected { border-color: var(--ef-conflict-text); box-shadow: inset 0 0 0 1px var(--ef-conflict-text), var(--ef-shadow); }
.folder-card.unrecognized { background: var(--ef-surface-soft); border-style: dashed; }

/* select-toggle 选择按钮：防闪烁 + 平滑 */
.select-toggle { width: 26px; height: 26px; border-radius: 8px; border: 1px solid var(--ef-border-strong); background: var(--ef-surface); color: var(--ef-faint); display: grid; place-items: center; flex: 0 0 auto; cursor: pointer; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, box-shadow 0.25s ease; }
.select-toggle:hover { border-color: var(--ef-primary); color: var(--ef-primary); background: var(--ef-surface-soft); transform: scale(1.06); }
.select-toggle:active { transform: scale(0.92); transition: transform 0.1s ease; }
.select-toggle.active { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: 0 4px 10px rgba(15,23,42,0.2); }
.select-toggle.active:hover { background: var(--ef-primary-hover); }
.select-toggle:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

.folder-main-info { min-width: 0; flex: 1; }
.folder-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.folder-name { min-width: 0; color: var(--ef-text); font-weight: 900; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folder-depth-chip { flex: 0 0 auto; height: 20px; display: inline-flex; align-items: center; padding: 0 7px; border-radius: 999px; border: 1px solid var(--ef-border); background: var(--ef-surface-muted); color: var(--ef-muted); font-size: 10.5px; font-weight: 700; }
.folder-path { margin-top: 3px; color: var(--ef-faint); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.folder-root { margin-top: 4px; color: var(--ef-muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* status-pill：和 lib-chip 一致的视觉规范 */
.status-pill { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; padding: 0 9px; font-size: 11px; font-weight: 600; white-space: nowrap; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.folder-card:hover .status-pill { transform: scale(1.04); }
.status-pill.success { background: rgba(16, 185, 129, 0.12); color: #059669; border: 1px solid rgba(16, 185, 129, 0.24); }
.status-pill.warning { background: rgba(254, 243, 199, 0.8); color: #b45309; border: 1px solid rgba(253, 224, 71, 0.5); }
.status-pill.danger { background: rgba(254, 226, 226, 0.8); color: #b91c1c; border: 1px solid rgba(252, 165, 165, 0.5); }
.status-pill.info { background: rgba(100, 116, 139, 0.12); color: var(--ef-text-soft); border: 1px solid rgba(100, 116, 139, 0.24); }
.status-pill.muted { background: var(--ef-surface-muted); color: var(--ef-muted); border: 1px solid var(--ef-border); }

.folder-meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.folder-meta { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; height: 22px; border-radius: 999px; background: var(--ef-surface-soft); border: 1px solid var(--ef-border-soft); padding: 0 8px; color: var(--ef-muted); font-size: 11px; font-weight: 500; transition: background-color 0.25s ease, border-color 0.25s ease; }
.folder-meta:hover { background: var(--ef-surface-muted); border-color: var(--ef-border-strong); }
.folder-meta.rj { color: var(--ef-text); font-weight: 700; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.folder-meta.rj.missing { color: var(--ef-faint); }
.folder-meta.route { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-radius: 8px; }

.conflict-box { margin-top: 12px; display: flex; gap: 9px; padding: 10px; border-radius: 12px; background: var(--ef-conflict-bg); border: 1px solid var(--ef-conflict-border); color: var(--ef-conflict-text); }
.conflict-box.large { margin-top: 0; }
.conflict-title { font-size: 13px; font-weight: 900; }
.conflict-desc { margin-top: 2px; font-size: 12px; color: var(--ef-conflict-muted); }

/* ============================================================
 * 卡片操作按钮（防闪烁 + 微动效）
 * ============================================================ */
.folder-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.card-action {
  height: 28px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 8px;
  background: var(--ef-surface);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  color: var(--ef-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.2s ease;
  will-change: transform;
}
.card-action:hover { transform: translateY(-1px) scale(1.03); background: var(--ef-surface-soft); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.card-action:active:not(:disabled) { transform: scale(0.96); transition: transform 0.12s ease; }
.card-action:disabled { opacity: 0.65; cursor: not-allowed; }
.card-action.primary { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: var(--ef-shadow); }
.card-action.primary:hover { background: var(--ef-primary-hover); box-shadow: var(--ef-shadow-hover); }
.card-action.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.card-action.warning:hover { background: #fef3c7; border-color: #fcd34d; }
.card-action.danger { background: var(--ef-surface); color: #dc2626; border-color: rgba(220,38,38,0.25); }
.card-action.danger:hover { background: #fef2f2; border-color: #fca5a5; box-shadow: 0 4px 10px rgba(220,38,38,0.12); }

/* ============================================================
 * 进出过渡：section / 网格 / 卡片
 * ============================================================ */
.ef-section-enter-active {
  transition:
    opacity 0.4s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1),
    max-height 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}
.ef-section-leave-active {
  transition: opacity 0.22s ease, transform 0.28s ease, max-height 0.3s cubic-bezier(0.4, 0, 0.6, 1);
  overflow: hidden;
}
.ef-section-enter-from { opacity: 0; transform: translateY(-10px) scale(0.99); }
.ef-section-leave-to   { opacity: 0; transform: translateY(-6px) scale(0.99); }

.ef-grid-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.55s cubic-bezier(0.34, 1.56, 0.64, 1);
  transition-delay: var(--ef-grid-delay, 0ms);
}
.ef-grid-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
  position: absolute;
}
.ef-grid-enter-from { opacity: 0; transform: translateY(20px) scale(0.94); }
.ef-grid-leave-to   { opacity: 0; transform: translateY(-10px) scale(0.96); }
.ef-grid-move { transition: transform 0.45s cubic-bezier(0.22, 1, 0.36, 1); }
.result-dialog :deep(.el-dialog) { border-radius: 22px; overflow: hidden; background: var(--ef-surface); border: 1px solid var(--ef-border); box-shadow: 0 24px 70px rgba(15,23,42,.2); }
.result-dialog :deep(.el-dialog__header) { margin: 0; padding: 18px 18px 0; }
.result-dialog :deep(.el-dialog__body) { padding: 16px 18px; }
.result-dialog :deep(.el-dialog__footer) { padding: 0 18px 18px; }
.dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.dialog-title-wrap { display: flex; align-items: center; gap: 12px; }
.dialog-icon { width: 38px; height: 38px; border-radius: 14px; display: grid; place-items: center; }
.dialog-icon.success { background: #ecfdf5; color: #059669; } .dialog-icon.warning { background: #fffbeb; color: #d97706; }
.dialog-title { color: var(--ef-text); font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.dialog-subtitle { margin-top: 3px; color: var(--ef-muted); font-size: 12px; }
/* ============================================================
 * 对话框：标题 / 关闭按钮 / 结果面板 / 任务列表 / 解决方案选项
 *  - 所有交互元素加防闪烁规则（hover 不依赖 :not(:disabled)）
 * ============================================================ */
.dialog-close {
  width: 32px; height: 32px;
  border: 1px solid var(--ef-border);
  border-radius: 10px;
  background: var(--ef-surface);
  color: var(--ef-faint);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.25s ease, border-color 0.25s ease, background-color 0.25s ease, box-shadow 0.25s ease;
}
.dialog-close:hover { color: var(--ef-text); border-color: var(--ef-border-strong); background: var(--ef-surface-soft); transform: scale(1.06) rotate(90deg); }
.dialog-close:active { transform: scale(0.92) rotate(90deg); transition: transform 0.1s ease; }

.result-panel { padding: 14px; border-radius: 14px; margin-bottom: 12px; border: 1px solid; }
.result-panel.success { background: #f0fdf4; color: #047857; border-color: #bbf7d0; }
.result-panel.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.result-title { font-weight: 900; }
.result-message { font-size: 13px; margin-top: 4px; line-height: 1.6; }
.task-list, .duplicate-panel { display: grid; gap: 10px; }
.task-list-title { color: var(--ef-text); font-size: 12px; font-weight: 900; }
.task-row, .linked-row { display: grid; grid-template-columns: 92px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 12px; background: var(--ef-surface-soft); border: 1px solid var(--ef-border); color: var(--ef-muted); font-size: 12px; transition: border-color 0.25s ease, background-color 0.25s ease; }
.task-row:hover, .linked-row:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-hover); }
.task-id { font-weight: 900; color: var(--ef-text); font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.task-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-status { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; padding: 0 9px; background: var(--ef-surface-muted); color: var(--ef-text-soft); border: 1px solid var(--ef-border); font-size: 11px; font-weight: 600; }

.dialog-footer { display: flex; justify-content: flex-end; gap: 9px; }
.dialog-ep-btn { height: 34px; border-radius: 10px; font-weight: 700; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, opacity 0.25s ease; }
.dialog-ep-btn:hover { transform: translateY(-2px) scale(1.02); }
.dialog-ep-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-ep-btn.primary { --el-button-bg-color: #111827; --el-button-border-color: #111827; --el-button-text-color: #fff; --el-button-hover-bg-color: #1f2937; --el-button-hover-border-color: #1f2937; --el-button-hover-text-color: #fff; box-shadow: 0 6px 14px rgba(15,23,42,0.18); }
.dialog-ep-btn.primary:hover { box-shadow: 0 10px 22px rgba(15,23,42,0.26); }

.detail-card { border: 1px solid var(--ef-border); border-radius: 14px; padding: 12px; background: var(--ef-surface-soft); transition: border-color 0.25s ease, background-color 0.25s ease; }
.detail-card:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-hover); }
.detail-title { font-weight: 900; margin-bottom: 8px; }
.detail-line { font-size: 12px; color: var(--ef-muted); line-height: 1.7; word-break: break-all; }

/* 解决方案选项卡：选中状态加 ring + 推荐项 emerald 高亮 */
.resolution-list { display: grid; gap: 9px; }
.resolution-option {
  text-align: left;
  border: 1px solid var(--ef-border);
  border-radius: 14px;
  padding: 12px;
  background: var(--ef-surface-soft);
  display: grid;
  gap: 4px;
  cursor: pointer;
  transition:
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.25s ease,
    border-color 0.25s ease,
    background-color 0.25s ease;
}
.resolution-option:hover { transform: translateY(-1px); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.resolution-option:active { transform: scale(0.99); transition: transform 0.1s ease; }
.resolution-option.active {
  border-color: var(--ef-primary);
  box-shadow: inset 0 0 0 1px var(--ef-primary), var(--ef-shadow);
  background: var(--ef-surface);
}
.resolution-option.recommend { background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%); border-color: #bbf7d0; }
.resolution-option.recommend.active { border-color: #047857; box-shadow: inset 0 0 0 1px #047857, 0 6px 14px rgba(5,150,105,0.12); }
.resolution-title { font-weight: 900; color: var(--ef-text); }
.resolution-desc { color: var(--ef-muted); font-size: 12px; }

/* 冲突详情对话框页脚按钮 */
.dialog-btn {
  height: 34px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 10px;
  background: var(--ef-surface);
  padding: 0 14px;
  font-weight: 700;
  color: var(--ef-muted);
  font-size: 13px;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.25s ease;
}
.dialog-btn:hover { transform: translateY(-2px) scale(1.02); background: var(--ef-surface-soft); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.dialog-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-btn:disabled { opacity: 0.65; cursor: not-allowed; }
.dialog-btn.primary { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: var(--ef-shadow); }
.dialog-btn.primary:hover { background: var(--ef-primary-hover); border-color: var(--ef-primary-hover); box-shadow: var(--ef-shadow-hover); }

/* lucide animate-spin 全局已存在（Tailwind utility），此处保留兼容 */
.animate-spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 980px) {
  .existing-shell { grid-template-columns: 1fr; }
  .sidebar-card { position: static; }
  .hero-search-wrap { width: 100%; }
}

/* 手机 ≤640 紧凑边距 + 内部按钮收紧 */
@media (max-width: 640px) {
  .existing-page { padding-left: 10px; padding-right: 10px; }
  .existing-shell { gap: 12px; margin-top: 12px; }
  .sidebar-card { padding: 12px; border-radius: 14px; }
  .ef-head-btn { height: 32px; padding: 0 10px; }
  .ef-head-btn-label { font-size: 12px; }
  /* sidebar 内的 actions row 改为 2 列等分 */
  .sidebar-actions {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
}
</style>
