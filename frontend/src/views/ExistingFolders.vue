<template>
  <div class="existing-page">
    <section class="existing-hero">
      <div class="hero-title-block">
        <div class="hero-icon-box">
          <FolderInput :size="15" :stroke-width="2.1" />
        </div>
        <div class="hero-text">
          <h1>已有文件夹</h1>
          <p class="hero-desc">把已解压的 RJ 文件夹放入已有目录，自动识别 RJ、抓取元数据、重命名并按分类规则入库</p>
        </div>
      </div>
      <div class="hero-actions">
        <div class="hero-search-wrap">
          <Search :size="13" class="hero-search-icon" />
          <input v-model="searchQuery" class="hero-search-input" type="text" placeholder="搜索文件夹名或 RJ 号" />
        </div>
        <button type="button" class="hero-btn hero-btn-primary" :disabled="loading" @click="refreshWithCache">
          <RefreshCw :size="13" :class="{ 'animate-spin': loading }" />
          刷新列表
        </button>
        <button type="button" class="hero-btn hero-btn-secondary" :disabled="loading" @click="refreshForce">
          <RotateCcw :size="13" />
          重新抓取
        </button>
      </div>
    </section>

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
        <section class="toolbar-card">
          <div class="toolbar-main">
            <div class="toolbar-copy">
              <div class="toolbar-title">待处理目录</div>
              <div class="toolbar-subtitle">{{ loading ? '正在扫描已有目录' : `已发现 ${folders.length} 个文件夹，${conflictCount} 个可能冲突` }}</div>
            </div>
            <div class="toolbar-actions">
              <span class="metric-pill total"><Folder :size="12" /> 总数 {{ folders.length }}</span>
              <span class="metric-pill owned"><CheckCircle2 :size="12" /> 可处理 {{ readyCount }}</span>
              <span class="metric-pill warn"><AlertTriangle :size="12" /> 冲突 {{ conflictCount }}</span>
              <span class="metric-pill muted"><Hash :size="12" /> 已选 {{ selectedFolders.length }}</span>
            </div>
          </div>
        </section>

        <section class="folders-card">
          <div v-if="loading" class="scan-banner">
            <AppLoadingAnimation variant="inline" :size="34" />
            <div>
              <div class="scan-title">正在扫描文件夹</div>
              <div class="scan-desc">已发现 {{ folders.length }} 个目录，查重结果会分批更新</div>
            </div>
          </div>

          <div v-if="filteredFolders.length" class="folder-grid">
            <article v-for="folder in filteredFolders" :key="folder.path" class="folder-card" :class="{ selected: isSelected(folder), conflict: isConflict(folder) }">
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
                  <RefreshCw v-else-if="getFolderState(folder).icon === 'refresh'" :size="11" />
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

              <div v-if="isConflict(folder)" class="conflict-box">
                <AlertTriangle :size="14" />
                <div>
                  <div class="conflict-title">{{ getConflictTypeLabel(folder.duplicate_info?.conflict_type) }}</div>
                  <div class="conflict-desc">库中已有相同或关联作品，请查看冲突后选择处理方案</div>
                </div>
              </div>

              <div class="folder-actions">
                <button v-if="isConflict(folder)" type="button" class="card-action warning" @click="showDuplicateDetail(folder)">
                  <Eye :size="13" /> 查看冲突
                </button>
                <button v-else type="button" class="card-action primary" :disabled="processing" @click="handleProcessSingle(folder)">
                  <Play :size="13" /> 重命名并入库
                </button>
                <button type="button" class="card-action" :disabled="checkingDuplicates" @click="handleRefreshFolder(folder)">
                  <RefreshCw :size="13" /> 查重
                </button>
                <button type="button" class="card-action danger" @click="handleDeleteFolder(folder)">
                  <Trash2 :size="13" /> 删除
                </button>
              </div>
            </article>
          </div>

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
import { existingFolderApi } from '../api'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
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
    const url = `/api/existing-folders/scan?check_duplicates=${checkDuplicates.value}&force_refresh=${forceRefresh}`
    const response = await fetch(url, { method: 'POST', headers: { Accept: 'application/x-ndjson' } })
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
.existing-hero { display: flex; justify-content: space-between; gap: 18px; align-items: center; padding: 18px; border: 1px solid #e5e7eb; border-radius: 20px; background: #fff; box-shadow: 0 10px 26px rgba(15,23,42,.05); }
.hero-title-block { display: flex; align-items: center; gap: 13px; }
.hero-icon-box { width: 38px; height: 38px; border-radius: 16px; display: grid; place-items: center; background: #111827; color: white; box-shadow: 0 12px 28px rgba(15,23,42,.22); }
.hero-text h1 { margin: 0; font-size: 24px; line-height: 1.1; font-weight: 900; letter-spacing: -.04em; }
.hero-desc { margin: 5px 0 0; color: #64748b; font-size: 13px; }
.hero-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.hero-search-wrap { position: relative; width: min(360px, 42vw); }
.hero-search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #94a3b8; }
.hero-search-input { width: 100%; height: 38px; padding: 0 14px 0 34px; border: 1px solid #e2e8f0; border-radius: 14px; outline: none; background: rgba(255,255,255,.88); font-size: 13px; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.hero-search-input:focus { border-color: #94a3b8; box-shadow: 0 0 0 3px rgba(148,163,184,.16); }
.hero-btn, .side-ep-action, .card-action, .dialog-btn, .dialog-close, .dialog-ep-btn, .select-toggle, .resolution-option { cursor: pointer; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.hero-btn { height: 38px; border: 1px solid #e2e8f0; border-radius: 14px; padding: 0 14px; display: inline-flex; align-items: center; gap: 7px; background: white; color: #334155; font-weight: 800; font-size: 12px; }
.hero-btn:hover, .side-ep-action:hover, .card-action:hover, .dialog-btn:hover, .dialog-close:hover, .dialog-ep-btn:hover, .resolution-option:hover { transform: translateY(-2px) scale(1.02); }
.hero-btn:active, .side-ep-action:active, .card-action:active, .dialog-btn:active, .dialog-close:active, .dialog-ep-btn:active, .resolution-option:active { transform: scale(.96); }
.hero-btn-primary { background: #111827; color: white; border-color: #111827; box-shadow: 0 12px 24px rgba(15,23,42,.18); }
.hero-btn-secondary { background: #f8fafc; }
.hero-btn:disabled, .side-ep-action.is-disabled, .card-action:disabled { opacity: .55; cursor: not-allowed; transform: none; }
.existing-shell { display: grid; grid-template-columns: 310px minmax(0,1fr); gap: 18px; margin-top: 18px; }
.sidebar-card, .toolbar-card, .folders-card { border: 1px solid #e5e7eb; border-radius: 20px; background: #fff; box-shadow: 0 10px 26px rgba(15,23,42,.04); }
.sidebar-card { padding: 16px; position: sticky; top: 18px; }
.sidebar-head, .toolbar-main, .folder-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.sidebar-overline { color: #94a3b8; font-size: 11px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; }
.sidebar-title, .toolbar-title { font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.sidebar-count { min-width: 30px; height: 24px; border-radius: 999px; display: grid; place-items: center; background: #f1f5f9; color: #334155; font-size: 12px; font-weight: 900; }
.pipeline-list { margin-top: 16px; display: grid; gap: 12px; }
.pipeline-item { display: flex; gap: 10px; align-items: flex-start; padding: 10px; border-radius: 14px; background: #fff; border: 1px solid #e5e7eb; }
.pipeline-dot { width: 26px; height: 26px; flex: 0 0 auto; border-radius: 11px; display: grid; place-items: center; }
.pipeline-dot.info { background: #eff6ff; color: #2563eb; } .pipeline-dot.ok { background: #ecfdf5; color: #059669; } .pipeline-dot.warn { background: #fffbeb; color: #d97706; } .pipeline-dot.done { background: #f1f5f9; color: #0f172a; }
.pipeline-title { font-size: 13px; font-weight: 900; } .pipeline-desc { margin-top: 2px; font-size: 11px; color: #64748b; line-height: 1.45; }
.option-stack { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 16px; }
.option-row { min-height: 58px; border: 1px solid #e5e7eb; border-radius: 14px; background: #fff; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; }
.option-row-main { min-width: 0; display: flex; align-items: center; gap: 10px; color: #475569; }
.option-row-title { color: #0f172a; font-size: 13px; font-weight: 900; line-height: 1.2; }
.option-row-desc { margin-top: 3px; color: #94a3b8; font-size: 11px; line-height: 1.35; }
.sidebar-actions { margin-top: 16px; display: grid; gap: 9px; }
.side-ep-action { width: 100%; height: 38px; margin-left: 0 !important; border-radius: 14px; font-weight: 900; }
.side-ep-action.primary { --el-button-bg-color: #111827; --el-button-border-color: #111827; --el-button-text-color: #fff; --el-button-hover-bg-color: #1f2937; --el-button-hover-border-color: #1f2937; --el-button-hover-text-color: #fff; }
.side-button-icon { margin-right: 4px; }
.toolbar-card { padding: 16px; }
.toolbar-subtitle { margin-top: 4px; color: #64748b; font-size: 12px; }
.toolbar-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.metric-pill { height: 28px; border-radius: 999px; padding: 0 10px; display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 900; border: 1px solid #e5e7eb; background: #fff; color: #475569; }
.metric-pill.owned { background: #ecfdf5; color: #047857; border-color: #bbf7d0; } .metric-pill.warn { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.folders-card { margin-top: 14px; padding: 16px; min-height: 420px; }
.scan-banner { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; padding: 12px; border-radius: 16px; background: #fff; border: 1px dashed #cbd5e1; }
.scan-title { font-weight: 900; font-size: 13px; } .scan-desc { color: #64748b; font-size: 12px; margin-top: 2px; }
.folder-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 13px; }
.folder-card { border: 1px solid #dbe3ef; border-radius: 18px; padding: 14px; background: #fff; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.folder-card:hover { transform: translateY(-2px); box-shadow: 0 16px 30px rgba(15,23,42,.08); }
.folder-card.selected { border-color: #111827; box-shadow: inset 0 0 0 1px #111827; }
.folder-card.conflict { background: #fff; border-color: #fed7aa; }
.select-toggle { width: 26px; height: 26px; border-radius: 10px; border: 1px solid #cbd5e1; background: #fff; color: #cbd5e1; display: grid; place-items: center; flex: 0 0 auto; }
.select-toggle:hover { border-color: #111827; color: #111827; background: #f8fafc; }
.select-toggle.active { background: #111827; color: white; border-color: #111827; }
.folder-main-info { min-width: 0; flex: 1; }
.folder-name { font-weight: 900; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folder-path { margin-top: 3px; color: #94a3b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status-pill { height: 24px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; padding: 0 8px; font-size: 11px; font-weight: 900; white-space: nowrap; }
.status-pill.success { background: #ecfdf5; color: #047857; } .status-pill.warning { background: #fffbeb; color: #b45309; } .status-pill.danger { background: #fef2f2; color: #dc2626; } .status-pill.info { background: #eff6ff; color: #2563eb; } .status-pill.muted { background: #f1f5f9; color: #64748b; }
.folder-meta-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.folder-meta { display: inline-flex; align-items: center; gap: 4px; height: 24px; border-radius: 999px; background: #fff; border: 1px solid #e5e7eb; padding: 0 8px; color: #64748b; font-size: 11px; font-weight: 800; }
.folder-meta.rj { color: #0f172a; background: #fff; }
.conflict-box { margin-top: 12px; display: flex; gap: 9px; padding: 10px; border-radius: 16px; background: #fff7ed; border: 1px solid #fed7aa; color: #9a3412; }
.conflict-box.large { margin-top: 0; }
.conflict-title { font-size: 13px; font-weight: 900; } .conflict-desc { margin-top: 2px; font-size: 12px; color: #b45309; }
.folder-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.card-action { height: 32px; border: 1px solid #e2e8f0; border-radius: 12px; background: white; display: inline-flex; align-items: center; gap: 6px; padding: 0 10px; color: #475569; font-size: 12px; font-weight: 900; }
.card-action.primary { background: #111827; color: white; border-color: #111827; } .card-action.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; } .card-action.danger { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
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
.dialog-close { width: 32px; height: 32px; border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; color: #94a3b8; display: grid; place-items: center; }
.dialog-close:hover { color: #0f172a; border-color: #cbd5e1; background: #f8fafc; }
.result-panel { padding: 14px; border-radius: 16px; margin-bottom: 12px; border: 1px solid; }
.result-panel.success { background: #f0fdf4; color: #047857; border-color: #bbf7d0; } .result-panel.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.result-title { font-weight: 900; } .result-message { font-size: 13px; margin-top: 4px; line-height: 1.6; }
.task-list, .duplicate-panel { display: grid; gap: 10px; }
.task-list-title { color: #0f172a; font-size: 12px; font-weight: 900; }
.task-row, .linked-row { display: grid; grid-template-columns: 92px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 14px; background: #fff; border: 1px solid #e5e7eb; color: #475569; font-size: 12px; }
.task-id { font-weight: 900; color: #0f172a; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.task-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-status { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; padding: 0 8px; background: #eff6ff; color: #2563eb; font-size: 11px; font-weight: 900; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 9px; }
.dialog-ep-btn { height: 34px; border-radius: 12px; font-weight: 900; }
.dialog-ep-btn.primary { --el-button-bg-color: #111827; --el-button-border-color: #111827; --el-button-text-color: #fff; --el-button-hover-bg-color: #1f2937; --el-button-hover-border-color: #1f2937; --el-button-hover-text-color: #fff; }
.detail-card { border: 1px solid #e2e8f0; border-radius: 16px; padding: 12px; background: #fff; }
.detail-title { font-weight: 900; margin-bottom: 8px; } .detail-line { font-size: 12px; color: #475569; line-height: 1.7; word-break: break-all; }
.resolution-list { display: grid; gap: 9px; }
.resolution-option { text-align: left; border: 1px solid #e2e8f0; border-radius: 16px; padding: 12px; background: #fff; display: grid; gap: 4px; }
.resolution-option.active { border-color: #111827; box-shadow: inset 0 0 0 1px #111827; } .resolution-option.recommend { background: #f0fdf4; }
.resolution-title { font-weight: 900; color: #0f172a; } .resolution-desc { color: #64748b; font-size: 12px; }
.dialog-btn { height: 34px; border: 1px solid #e2e8f0; border-radius: 12px; background: white; padding: 0 14px; font-weight: 900; color: #475569; }
.dialog-btn.primary { background: #111827; color: white; border-color: #111827; }
.animate-spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) { .existing-shell { grid-template-columns: 1fr; } .sidebar-card { position: static; } .existing-hero { align-items: stretch; flex-direction: column; } .hero-search-wrap { width: 100%; } }
</style>
