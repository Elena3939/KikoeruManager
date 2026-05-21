<template>
  <div class="existing-page">
    <AppPageHeader
      :icon="FolderInput"
      icon-color="#16a34a"
      title="已有文件夹"
      subtitle="把已解压的 RJ 文件夹放入已有目录，自动识别 RJ、抓取元数据、重命名并按分类规则入库"
    >
      <div class="hero-search-wrap">
        <Search :size="13" class="hero-search-icon" />
        <input v-model="searchQuery" class="hero-search-input" type="text" placeholder="搜索文件夹名或 RJ 号" />
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
              <el-switch v-model="autoClassify" size="small" />
            </div>
            <div class="option-row">
              <div class="option-row-main">
                <ShieldCheck :size="14" />
                <div>
                  <div class="option-row-title">扫描时查重</div>
                  <div class="option-row-desc">刷新列表时检查重复与关联作品</div>
                </div>
              </div>
              <el-switch v-model="checkDuplicates" size="small" />
            </div>
          </div>

          <div class="sidebar-actions">
            <el-button class="side-ep-action primary" :disabled="selectedFolders.length === 0" :loading="processing" @click="handleProcess">
              <Play :size="13" class="side-button-icon" />
              处理选中 {{ selectedFolders.length ? `(${selectedFolders.length})` : '' }}
            </el-button>
            <el-button class="side-ep-action" :disabled="selectedFolders.length === 0" :loading="checkingDuplicates" @click="checkSelectedDuplicates">
              <SearchCheck :size="13" class="side-button-icon" />
              检查选中项
            </el-button>
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
                <span class="ef-info-meta">个准备处理</span>
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
              :class="{ selected: isSelected(folder), conflict: isConflict(folder) }"
              :style="{ '--ef-grid-delay': `${Math.min(idx, 14) * 30}ms` }"
            >
              <div class="folder-card-head">
                <button type="button" class="select-toggle" :class="{ active: isSelected(folder) }" :aria-label="isSelected(folder) ? '取消选择' : '选择文件夹'" @click="toggleFolderSelection(folder)">
                  <Check :size="13" />
                </button>
                <div class="folder-main-info">
                  <div class="folder-name" :title="folder.name">{{ folder.name }}</div>
                  <div class="folder-path" :title="folder.path">{{ folder.path }}</div>
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
                <span class="folder-meta rj"><Hash :size="11" /> {{ folder.rjcode || '未识别 RJ' }}</span>
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
                <button v-else type="button" class="card-action primary" :disabled="processing" @click="handleProcessSingle(folder)">
                  <Play :size="13" /> 重命名并入库
                </button>
                <button type="button" class="card-action" :disabled="checkingDuplicates" @click="handleRefreshFolder(folder)">
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
    String(folder.rjcode || '').toLowerCase().includes(query)
  )
})

const readyCount = computed(() => folders.value.filter((folder) => !isConflict(folder)).length)

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

function isSelected(folder) {
  return selectedFolders.value.some((item) => item.path === folder.path)
}

function toggleFolderSelection(folder) {
  if (isSelected(folder)) {
    selectedFolders.value = selectedFolders.value.filter((item) => item.path !== folder.path)
  } else {
    selectedFolders.value = [...selectedFolders.value, folder]
  }
}

function getFolderState(folder) {
  if (isConflict(folder)) return { label: getConflictTypeLabel(folder.duplicate_info?.conflict_type), tone: 'danger', icon: 'alert' }
  if (folder.status === 'checking') return { label: '检查中', tone: 'warning', icon: 'refresh' }
  if (folder.status === 'pending') return { label: '待检查', tone: 'muted', icon: 'clock' }
  if (folder.status === 'error') return { label: '检查失败', tone: 'danger', icon: 'x' }
  if (folder.status === 'cached') return { label: '已检查', tone: 'info', icon: 'shield' }
  return { label: '可处理', tone: 'success', icon: 'check' }
}

async function handleProcess() {
  if (!selectedFolders.value.length) return
  processing.value = true
  try {
    const data = await existingFolderApi.process(selectedFolders.value.map((folder) => folder.path), autoClassify.value)
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
  if (!selectedFolders.value.length) return
  checkingDuplicates.value = true
  try {
    const data = await existingFolderApi.checkDuplicates(selectedFolders.value.map((folder) => folder.path), { checkLinkedWorks: true })
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
      status: result.error ? 'error' : 'checked',
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
.existing-page { max-width: 1480px; margin: 0 auto; padding: 22px; color: #0f172a; background: #fff; }

/* ============================================================
 * 页头搜索框 + page-head-btn 规范按钮（对齐 ASMR 同步页 / 操作记录页）
 * ============================================================ */
.hero-search-wrap { position: relative; width: min(360px, 42vw); }
.hero-search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #94a3b8; pointer-events: none; transition: color 0.2s ease; }
.hero-search-input { width: 100%; height: 36px; padding: 0 14px 0 34px; border: 1px solid rgba(15, 23, 42, 0.12); border-radius: 10px; outline: none; background: #fff; font-size: 13px; color: #1e293b; transition: border-color 0.25s ease, box-shadow 0.25s ease, background-color 0.25s ease; }
.hero-search-input::placeholder { color: #94a3b8; }
.hero-search-input:hover { border-color: rgba(15, 23, 42, 0.2); background: #f8fafc; }
.hero-search-input:focus { border-color: #0f172a; background: #fff; box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.06); }
.hero-search-wrap:focus-within .hero-search-icon { color: #0f172a; }

.ef-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
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
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
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
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.28), 0 0 0 4px rgba(15, 23, 42, 0.05);
}
.ef-head-btn.primary:hover::before { left: 130%; }

/* ghost：白底纯色 transition（gradient 不能 transition 会瞬切） */
.ef-head-btn.ghost { background-color: #fff; }
.ef-head-btn.ghost:hover { background-color: #f8fafc; border-color: rgba(15, 23, 42, 0.2); }

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
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
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
.ef-info-icon-slate { color: #64748b; }
.ef-info-body { min-width: 0; flex: 1 1 auto; }
.ef-info-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #94a3b8;
  margin-bottom: 4px;
}
.ef-info-value {
  font-size: 13.5px;
  color: #475569;
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
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  display: inline-block;
  transform-origin: center;
}
.ef-info-meta { color: #94a3b8; font-size: 12px; }
.ef-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(15, 23, 42, 0.1), transparent);
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
.sidebar-card, .folders-card { border: 1px solid #e5e7eb; border-radius: 20px; background: #fff; box-shadow: 0 10px 26px rgba(15,23,42,.04); }
.sidebar-card { padding: 16px; position: sticky; top: 18px; }
.sidebar-head, .folder-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.sidebar-overline { color: #94a3b8; font-size: 11px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
.sidebar-title { font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.sidebar-count { min-width: 30px; height: 24px; border-radius: 999px; display: grid; place-items: center; background: #f1f5f9; color: #334155; font-size: 12px; font-weight: 900; transition: background-color 0.25s ease, color 0.25s ease; }
.pipeline-list { margin-top: 16px; display: grid; gap: 12px; }
.pipeline-item { display: flex; gap: 10px; align-items: flex-start; padding: 10px; border-radius: 14px; background: #fff; border: 1px solid #e5e7eb; transition: border-color 0.25s ease, background-color 0.25s ease; }
.pipeline-item:hover { border-color: rgba(15,23,42,0.12); background: #fafbfc; }
.pipeline-dot { width: 26px; height: 26px; flex: 0 0 auto; border-radius: 11px; display: grid; place-items: center; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.pipeline-item:hover .pipeline-dot { transform: scale(1.1); }
.pipeline-dot.info { background: #eff6ff; color: #2563eb; } .pipeline-dot.ok { background: #ecfdf5; color: #059669; } .pipeline-dot.warn { background: #fffbeb; color: #d97706; } .pipeline-dot.done { background: #f1f5f9; color: #0f172a; }
.pipeline-title { font-size: 13px; font-weight: 900; }
.pipeline-desc { margin-top: 2px; font-size: 11px; color: #64748b; line-height: 1.45; }
.option-stack { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 16px; }
.option-row { min-height: 58px; border: 1px solid #e5e7eb; border-radius: 14px; background: #fff; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; transition: border-color 0.25s ease; }
.option-row:hover { border-color: rgba(15,23,42,0.12); }
.option-row-main { min-width: 0; display: flex; align-items: center; gap: 10px; color: #475569; }
.option-row-title { color: #0f172a; font-size: 13px; font-weight: 900; line-height: 1.2; }
.option-row-desc { margin-top: 3px; color: #94a3b8; font-size: 11px; line-height: 1.35; }

/* ============================================================
 * 侧边栏按钮（应用防闪烁规则）
 * ============================================================ */
.sidebar-actions { margin-top: 16px; display: grid; gap: 9px; }
.side-ep-action { width: 100%; height: 38px; margin-left: 0 !important; border-radius: 12px; font-weight: 700; font-size: 13px; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease; }
.side-ep-action:hover { transform: translateY(-2px) scale(1.02); }
.side-ep-action:active:not(.is-disabled) { transform: scale(0.96); transition: transform 0.12s ease; }
.side-ep-action.is-disabled { opacity: 0.7; cursor: not-allowed; }
.side-ep-action.primary { --el-button-bg-color: #111827; --el-button-border-color: #111827; --el-button-text-color: #fff; --el-button-hover-bg-color: #1f2937; --el-button-hover-border-color: #1f2937; --el-button-hover-text-color: #fff; box-shadow: 0 6px 14px rgba(15,23,42,0.15); }
.side-ep-action.primary:hover { box-shadow: 0 10px 22px rgba(15,23,42,0.25); }
.side-button-icon { margin-right: 4px; }

/* ============================================================
 * 主区：扫描横幅 + 文件夹网格
 * ============================================================ */
.folders-card { padding: 16px; min-height: 420px; }
.scan-banner { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; padding: 12px; border-radius: 14px; background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%); border: 1px dashed rgba(15,23,42,0.18); }
.scan-title { font-weight: 900; font-size: 13px; }
.scan-desc { color: #64748b; font-size: 12px; margin-top: 2px; }
.folder-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 13px; }
.folder-card { border: 1px solid #dbe3ef; border-radius: 16px; padding: 14px; background: #fff; transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.25s ease, background-color 0.25s ease; }
.folder-card:hover { transform: translateY(-3px); box-shadow: 0 18px 36px rgba(15,23,42,.1); border-color: rgba(15,23,42,0.16); }
.folder-card.selected { border-color: #111827; box-shadow: inset 0 0 0 1px #111827, 0 8px 18px rgba(15,23,42,0.08); }
.folder-card.conflict { background: linear-gradient(180deg, #fff7ed 0%, #ffffff 60%); border-color: #fed7aa; }
.folder-card.conflict.selected { border-color: #c2410c; box-shadow: inset 0 0 0 1px #c2410c, 0 8px 18px rgba(194,65,12,0.1); }

/* select-toggle 选择按钮：防闪烁 + 平滑 */
.select-toggle { width: 26px; height: 26px; border-radius: 8px; border: 1px solid #cbd5e1; background: #fff; color: #cbd5e1; display: grid; place-items: center; flex: 0 0 auto; cursor: pointer; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, box-shadow 0.25s ease; }
.select-toggle:hover { border-color: #111827; color: #111827; background: #f8fafc; transform: scale(1.06); }
.select-toggle:active { transform: scale(0.92); transition: transform 0.1s ease; }
.select-toggle.active { background: #111827; color: white; border-color: #111827; box-shadow: 0 4px 10px rgba(15,23,42,0.2); }
.select-toggle.active:hover { background: #1f2937; }

.folder-main-info { min-width: 0; flex: 1; }
.folder-name { font-weight: 900; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folder-path { margin-top: 3px; color: #94a3b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }

/* status-pill：和 lib-chip 一致的视觉规范 */
.status-pill { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; padding: 0 9px; font-size: 11px; font-weight: 600; white-space: nowrap; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.folder-card:hover .status-pill { transform: scale(1.04); }
.status-pill.success { background: rgba(220, 252, 231, 0.8); color: #047857; border: 1px solid rgba(134, 239, 172, 0.5); }
.status-pill.warning { background: rgba(254, 243, 199, 0.8); color: #b45309; border: 1px solid rgba(253, 224, 71, 0.5); }
.status-pill.danger { background: rgba(254, 226, 226, 0.8); color: #b91c1c; border: 1px solid rgba(252, 165, 165, 0.5); }
.status-pill.info { background: rgba(224, 231, 255, 0.8); color: #4338ca; border: 1px solid rgba(165, 180, 252, 0.5); }
.status-pill.muted { background: rgba(241, 245, 249, 0.8); color: #475569; border: 1px solid rgba(203, 213, 225, 0.5); }

.folder-meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.folder-meta { display: inline-flex; align-items: center; gap: 4px; height: 22px; border-radius: 999px; background: #f8fafc; border: 1px solid rgba(15,23,42,0.06); padding: 0 8px; color: #64748b; font-size: 11px; font-weight: 500; transition: background-color 0.25s ease, border-color 0.25s ease; }
.folder-meta:hover { background: #f1f5f9; border-color: rgba(15,23,42,0.12); }
.folder-meta.rj { color: #0f172a; font-weight: 700; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }

.conflict-box { margin-top: 12px; display: flex; gap: 9px; padding: 10px; border-radius: 12px; background: #fff7ed; border: 1px solid #fed7aa; color: #9a3412; }
.conflict-box.large { margin-top: 0; }
.conflict-title { font-size: 13px; font-weight: 900; }
.conflict-desc { margin-top: 2px; font-size: 12px; color: #b45309; }

/* ============================================================
 * 卡片操作按钮（防闪烁 + 微动效）
 * ============================================================ */
.folder-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.card-action {
  height: 28px;
  border: 1px solid rgba(15,23,42,0.12);
  border-radius: 8px;
  background: #fff;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  color: #475569;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.2s ease;
  will-change: transform;
}
.card-action:hover { transform: translateY(-1px) scale(1.03); background: #f8fafc; border-color: rgba(15,23,42,0.18); box-shadow: 0 4px 10px rgba(15,23,42,0.06); }
.card-action:active:not(:disabled) { transform: scale(0.96); transition: transform 0.12s ease; }
.card-action:disabled { opacity: 0.65; cursor: not-allowed; }
.card-action.primary { background: #111827; color: white; border-color: #111827; box-shadow: 0 3px 8px rgba(15,23,42,0.15); }
.card-action.primary:hover { background: #1f2937; box-shadow: 0 6px 14px rgba(15,23,42,0.22); }
.card-action.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.card-action.warning:hover { background: #fef3c7; border-color: #fcd34d; }
.card-action.danger { background: #fff; color: #dc2626; border-color: rgba(220,38,38,0.25); }
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
.result-dialog :deep(.el-dialog) { border-radius: 22px; overflow: hidden; box-shadow: 0 24px 70px rgba(15,23,42,.2); }
.result-dialog :deep(.el-dialog__header) { margin: 0; padding: 18px 18px 0; }
.result-dialog :deep(.el-dialog__body) { padding: 16px 18px; }
.result-dialog :deep(.el-dialog__footer) { padding: 0 18px 18px; }
.dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.dialog-title-wrap { display: flex; align-items: center; gap: 12px; }
.dialog-icon { width: 38px; height: 38px; border-radius: 14px; display: grid; place-items: center; }
.dialog-icon.success { background: #ecfdf5; color: #059669; } .dialog-icon.warning { background: #fffbeb; color: #d97706; }
.dialog-title { color: #0f172a; font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.dialog-subtitle { margin-top: 3px; color: #64748b; font-size: 12px; }
/* ============================================================
 * 对话框：标题 / 关闭按钮 / 结果面板 / 任务列表 / 解决方案选项
 *  - 所有交互元素加防闪烁规则（hover 不依赖 :not(:disabled)）
 * ============================================================ */
.dialog-close {
  width: 32px; height: 32px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  color: #94a3b8;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.25s ease, border-color 0.25s ease, background-color 0.25s ease, box-shadow 0.25s ease;
}
.dialog-close:hover { color: #0f172a; border-color: rgba(15,23,42,0.2); background: #f8fafc; transform: scale(1.06) rotate(90deg); }
.dialog-close:active { transform: scale(0.92) rotate(90deg); transition: transform 0.1s ease; }

.result-panel { padding: 14px; border-radius: 14px; margin-bottom: 12px; border: 1px solid; }
.result-panel.success { background: #f0fdf4; color: #047857; border-color: #bbf7d0; }
.result-panel.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.result-title { font-weight: 900; }
.result-message { font-size: 13px; margin-top: 4px; line-height: 1.6; }
.task-list, .duplicate-panel { display: grid; gap: 10px; }
.task-list-title { color: #0f172a; font-size: 12px; font-weight: 900; }
.task-row, .linked-row { display: grid; grid-template-columns: 92px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 12px; background: #fff; border: 1px solid #e5e7eb; color: #475569; font-size: 12px; transition: border-color 0.25s ease, background-color 0.25s ease; }
.task-row:hover, .linked-row:hover { border-color: rgba(15,23,42,0.14); background: #fafbfc; }
.task-id { font-weight: 900; color: #0f172a; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.task-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-status { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; padding: 0 9px; background: rgba(224, 231, 255, 0.8); color: #4338ca; border: 1px solid rgba(165, 180, 252, 0.5); font-size: 11px; font-weight: 600; }

.dialog-footer { display: flex; justify-content: flex-end; gap: 9px; }
.dialog-ep-btn { height: 34px; border-radius: 10px; font-weight: 700; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, opacity 0.25s ease; }
.dialog-ep-btn:hover { transform: translateY(-2px) scale(1.02); }
.dialog-ep-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-ep-btn.primary { --el-button-bg-color: #111827; --el-button-border-color: #111827; --el-button-text-color: #fff; --el-button-hover-bg-color: #1f2937; --el-button-hover-border-color: #1f2937; --el-button-hover-text-color: #fff; box-shadow: 0 6px 14px rgba(15,23,42,0.18); }
.dialog-ep-btn.primary:hover { box-shadow: 0 10px 22px rgba(15,23,42,0.26); }

.detail-card { border: 1px solid #e2e8f0; border-radius: 14px; padding: 12px; background: #fff; transition: border-color 0.25s ease, background-color 0.25s ease; }
.detail-card:hover { border-color: rgba(15,23,42,0.14); background: #fafbfc; }
.detail-title { font-weight: 900; margin-bottom: 8px; }
.detail-line { font-size: 12px; color: #475569; line-height: 1.7; word-break: break-all; }

/* 解决方案选项卡：选中状态加 ring + 推荐项 emerald 高亮 */
.resolution-list { display: grid; gap: 9px; }
.resolution-option {
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px;
  background: #fff;
  display: grid;
  gap: 4px;
  cursor: pointer;
  transition:
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.25s ease,
    border-color 0.25s ease,
    background-color 0.25s ease;
}
.resolution-option:hover { transform: translateY(-1px); border-color: rgba(15,23,42,0.16); box-shadow: 0 4px 10px rgba(15,23,42,0.05); }
.resolution-option:active { transform: scale(0.99); transition: transform 0.1s ease; }
.resolution-option.active {
  border-color: #111827;
  box-shadow: inset 0 0 0 1px #111827, 0 6px 14px rgba(15,23,42,0.08);
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
}
.resolution-option.recommend { background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%); border-color: #bbf7d0; }
.resolution-option.recommend.active { border-color: #047857; box-shadow: inset 0 0 0 1px #047857, 0 6px 14px rgba(5,150,105,0.12); }
.resolution-title { font-weight: 900; color: #0f172a; }
.resolution-desc { color: #64748b; font-size: 12px; }

/* 冲突详情对话框页脚按钮 */
.dialog-btn {
  height: 34px;
  border: 1px solid rgba(15,23,42,0.12);
  border-radius: 10px;
  background: white;
  padding: 0 14px;
  font-weight: 700;
  color: #475569;
  font-size: 13px;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.25s ease;
}
.dialog-btn:hover { transform: translateY(-2px) scale(1.02); background: #f8fafc; border-color: rgba(15,23,42,0.2); box-shadow: 0 6px 14px rgba(15,23,42,0.06); }
.dialog-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-btn:disabled { opacity: 0.65; cursor: not-allowed; }
.dialog-btn.primary { background: #111827; color: white; border-color: #111827; box-shadow: 0 6px 14px rgba(15,23,42,0.18); }
.dialog-btn.primary:hover { background: #1f2937; border-color: #1f2937; box-shadow: 0 10px 22px rgba(15,23,42,0.26); }

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
