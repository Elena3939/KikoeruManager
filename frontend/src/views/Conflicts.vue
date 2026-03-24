<template>
  <div class="conflicts-page">
    <div class="page-header">
      <div>
        <h1>问题作品</h1>
        <p>
          重复作品以及解压失败作品处理
        </p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="fetchConflicts">刷新列表</el-button>
      </div>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
      class="page-alert"
    />

    <div v-if="loading && !conflicts.length" class="loading-shell" v-loading="true" />

    <el-empty
      v-else-if="!conflicts.length"
      description="当前没有待处理的问题作品"
    />

    <div v-else class="page-body">
      <aside class="conflict-list">
        <button
          v-for="conflict in conflicts"
          :key="conflict.id"
          type="button"
          class="conflict-card"
          :class="{ active: conflict.id === activeConflictId }"
          @click="activeConflictId = conflict.id"
        >
          <div class="card-head">
            <strong>{{ conflict.rjcode || '未识别 RJ' }}</strong>
            <el-tag :type="conflict.context?.existing?.is_remote ? 'warning' : 'primary'" effect="plain">
              {{ conflict.context?.existing?.is_remote ? '远程库存' : '本地库存' }}
            </el-tag>
          </div>
          <div class="card-body">
            <p>{{ getConflictTypeLabel(conflict.conflict_type) }}</p>
            <span>{{ formatDate(conflict.created_at) }}</span>
          </div>
        </button>
      </aside>

      <section class="conflict-detail" v-if="activeConflict">
        <div class="detail-head">
          <div>
            <h2>{{ activeConflict.rjcode || '未识别 RJ' }}</h2>
            <p>{{ getConflictTypeLabel(activeConflict.conflict_type) }}</p>
          </div>
          <div class="action-row">
            <el-button
              v-if="canUseAction(activeConflict, 'KEEP_NEW')"
              type="primary"
              :loading="isActionLoading(activeConflict.id, 'KEEP_NEW')"
              :disabled="isConflictBusy(activeConflict.id)"
              @click="handleKeepNew(activeConflict)"
            >
              保留新版
            </el-button>
            <el-button
              v-if="canUseAction(activeConflict, 'SKIP')"
              type="info"
              :loading="isActionLoading(activeConflict.id, 'SKIP')"
              :disabled="isConflictBusy(activeConflict.id)"
              @click="handleSkip(activeConflict)"
            >
              跳过
            </el-button>
            <el-button
              v-if="canUseAction(activeConflict, 'MERGE')"
              type="warning"
              :loading="mergeLoading && mergeConflictId === activeConflict.id"
              :disabled="isConflictBusy(activeConflict.id)"
              @click="openMergeWorkbench(activeConflict)"
            >
              合并
            </el-button>
          </div>
        </div>

        <el-alert
          v-if="isExtractFailed(activeConflict)"
          title="这是一条解压失败问题项，不是重复作品冲突"
          type="error"
          show-icon
          :closable="false"
          class="detail-alert"
        >
          <template #default>
            <span>{{ activeConflict.new_metadata?.error_message || '解压阶段失败，请检查密码、分卷完整性或压缩包本身是否损坏。' }}</span>
          </template>
        </el-alert>

        <div class="detail-grid">
          <el-card shadow="never">
            <template #header>{{ isExtractFailed(activeConflict) ? '失败来源' : '当前新内容' }}</template>
            <div class="meta-block">
              <label>来源路径</label>
              <pre>{{ activeConflict.new_path || '-' }}</pre>
            </div>
            <div class="meta-block">
              <label>来源类型</label>
              <span>{{ activeConflict.context?.new_path_kind === 'archive' ? '压缩包' : '目录' }}</span>
            </div>
            <div class="meta-block">
              <label>文件大小</label>
              <span>{{ formatFileSize(activeConflict.context?.source?.stats?.size) }}</span>
            </div>
            <div class="meta-block">
              <label>创建时间</label>
              <span>{{ formatTimestamp(activeConflict.context?.source?.stats?.created_at) }}</span>
            </div>
            <div class="meta-block" v-if="activeConflict.new_metadata">
              <label>{{ isExtractFailed(activeConflict) ? '附带信息' : '作品信息' }}</label>
              <span>{{ activeConflict.new_metadata.work_name || '-' }}</span>
              <span>{{ activeConflict.new_metadata.maker_name || '-' }}</span>
              <span>{{ Array.isArray(activeConflict.new_metadata.cvs) ? activeConflict.new_metadata.cvs.join(' / ') : '-' }}</span>
            </div>
            <div class="meta-block" v-if="activeConflict.new_metadata?.error_message">
              <label>失败原因</label>
              <span>{{ activeConflict.new_metadata.error_message }}</span>
            </div>
          </el-card>

          <el-card shadow="never">
            <template #header>{{ isExtractFailed(activeConflict) ? '处理建议' : '已存在目录' }}</template>
            <div class="meta-block">
              <label>{{ isExtractFailed(activeConflict) ? '建议动作' : '目标路径' }}</label>
              <pre v-if="!isExtractFailed(activeConflict)">{{ activeConflict.existing_path || '-' }}</pre>
              <span v-else>可直接跳过并删除当前失败来源；如果你已经补充了正确密码或完整分卷，建议回到任务列表重新处理。</span>
            </div>
            <div class="meta-block" v-if="!isExtractFailed(activeConflict)">
              <label>落地位置</label>
              <span>{{ activeConflict.context?.existing?.library_name || '默认库存' }}</span>
              <span>{{ activeConflict.context?.existing?.is_remote ? '群晖远程目录' : '本地目录' }}</span>
            </div>
            <div class="meta-block" v-if="!isExtractFailed(activeConflict)">
              <label>文件大小</label>
              <span>{{ formatFileSize(activeConflict.context?.existing?.stats?.size) }}</span>
            </div>
            <div class="meta-block" v-if="!isExtractFailed(activeConflict)">
              <label>创建时间</label>
              <span>{{ formatTimestamp(activeConflict.context?.existing?.stats?.created_at) }}</span>
            </div>
            <div class="meta-block">
              <label>{{ isExtractFailed(activeConflict) ? '记录时间' : '检测时间' }}</label>
              <span>{{ formatDate(activeConflict.created_at) }}</span>
            </div>
          </el-card>
        </div>

        <el-card shadow="never" class="action-help">
          <template #header>{{ isExtractFailed(activeConflict) ? '失败说明' : '动作说明' }}</template>
          <ul v-if="!isExtractFailed(activeConflict)" class="help-list">
            <li>保留新版：先经过删除审查，再安全替换已有目录，失败时走最小化破坏路径。</li>
            <li>跳过：不解压，直接删除当前压缩包或待处理目录，原有目录保持不变。</li>
            <li>合并：进入组件文件夹对比视图，逐文件决定保留新文件、旧文件或删除。</li>
          </ul>
          <ul v-else class="help-list">
            <li>当前问题发生在解压阶段，不代表库存中已经有重复作品。</li>
            <li>如果错误是密码不正确、分卷缺失或压缩包损坏，修复后重新处理通常更合适。</li>
            <li>如果确认不再处理这个包，可以直接点击“跳过”删除失败来源。</li>
          </ul>
        </el-card>
      </section>
    </div>

    <ConflictMergeWorkbench
      v-model="mergeDialogVisible"
      :conflict="mergeConflict"
      :preview="mergePreview"
      :decisions="mergeDecisions"
      :loading="mergeLoading"
      :submitting="mergeSubmitting"
      @update:decisions="handleDecisionUpdate"
      @refresh="refreshMergePreview"
      @submit="submitMerge"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ConflictMergeWorkbench from '../components/conflicts/ConflictMergeWorkbench.vue'
import { conflictApi } from '../api'

const ACTIVE_CONFLICT_STORAGE_KEY = 'prekikoeru-conflicts-active-id'

const conflicts = ref([])
const loading = ref(false)
const errorMessage = ref('')
const activeConflictId = ref(localStorage.getItem(ACTIVE_CONFLICT_STORAGE_KEY) || '')
const actionState = reactive({})

const mergeDialogVisible = ref(false)
const mergeLoading = ref(false)
const mergeSubmitting = ref(false)
const mergeConflictId = ref('')
const mergePreview = ref(null)
const mergeDecisions = ref({})
const mergePreviewCache = reactive({})
const mergeDecisionCache = reactive({})

const activeConflict = computed(() => conflicts.value.find(conflict => conflict.id === activeConflictId.value) || null)
const mergeConflict = computed(() => conflicts.value.find(conflict => conflict.id === mergeConflictId.value) || null)

watch(activeConflictId, value => {
  if (value) {
    localStorage.setItem(ACTIVE_CONFLICT_STORAGE_KEY, value)
  } else {
    localStorage.removeItem(ACTIVE_CONFLICT_STORAGE_KEY)
  }
})

onMounted(() => {
  fetchConflicts()
})

async function fetchConflicts() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await conflictApi.list()
    conflicts.value = data.conflicts || []
    syncActiveConflict()
  } catch (error) {
    console.error('获取问题作品失败:', error)
    errorMessage.value = error.response?.data?.detail || error.message || '获取问题作品失败'
  } finally {
    loading.value = false
  }
}

function syncActiveConflict() {
  if (!conflicts.value.length) {
    activeConflictId.value = ''
    return
  }
  if (!conflicts.value.some(conflict => conflict.id === activeConflictId.value)) {
    activeConflictId.value = conflicts.value[0].id
  }
}

function markAction(conflictId, action, value) {
  const key = `${conflictId}:${action}`
  if (value) {
    actionState[key] = true
  } else {
    delete actionState[key]
  }
}

function isActionLoading(conflictId, action) {
  return Boolean(actionState[`${conflictId}:${action}`])
}

function isConflictBusy(conflictId) {
  return Object.keys(actionState).some(key => key.startsWith(`${conflictId}:`)) ||
    (mergeSubmitting.value && mergeConflictId.value === conflictId)
}

function canUseAction(conflict, action) {
  return Array.isArray(conflict?.available_actions) && conflict.available_actions.includes(action)
}

function isExtractFailed(conflict) {
  return conflict?.conflict_type === 'EXTRACT_FAILED'
}

async function handleKeepNew(conflict) {
  markAction(conflict.id, 'KEEP_NEW', true)
  try {
    const previewResponse = await conflictApi.preview(conflict.id, 'KEEP_NEW')
    const preview = previewResponse.preview || {}
    const summary = [
      `将删除目标目录：${preview.path || conflict.existing_path || '-'}`,
      `文件夹数：${preview.folder_count ?? 0}`,
      `文件数：${preview.file_count ?? 0}`,
      `大小：${formatFileSize(preview.size)}`
    ].join('\n')

    await ElMessageBox.confirm(summary, '删除审查确认', {
      confirmButtonText: '确认删除并写入新版',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await conflictApi.resolve(conflict.id, {
      action: 'KEEP_NEW',
      confirmed: true
    })
    ElMessage.success('已完成保留新版')
    removeConflict(conflict.id)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('保留新版失败:', error)
      ElMessage.error(error.response?.data?.detail || error.message || '保留新版失败')
    }
  } finally {
    markAction(conflict.id, 'KEEP_NEW', false)
  }
}

async function handleSkip(conflict) {
  markAction(conflict.id, 'SKIP', true)
  try {
    await ElMessageBox.confirm(
      `将直接删除待处理来源：${conflict.new_path || '-'}`,
      '跳过当前压缩包',
      {
        confirmButtonText: '确认跳过',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await conflictApi.resolve(conflict.id, {
      action: 'SKIP'
    })
    ElMessage.success('已跳过当前包')
    removeConflict(conflict.id)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('跳过失败:', error)
      ElMessage.error(error.response?.data?.detail || error.message || '跳过失败')
    }
  } finally {
    markAction(conflict.id, 'SKIP', false)
  }
}

async function openMergeWorkbench(conflict, forceRefresh = false) {
  mergeConflictId.value = conflict.id
  mergeDialogVisible.value = true
  mergeLoading.value = true
  try {
    let preview = mergePreviewCache[conflict.id]
    if (!preview || forceRefresh) {
      preview = await conflictApi.preview(conflict.id, 'MERGE')
      mergePreviewCache[conflict.id] = preview
    }
    mergePreview.value = preview
    mergeDecisions.value = {
      ...(mergeDecisionCache[conflict.id] || preview.default_decisions || {})
    }
  } catch (error) {
    console.error('生成合并预览失败:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '生成合并预览失败')
    mergeDialogVisible.value = false
  } finally {
    mergeLoading.value = false
  }
}

function handleDecisionUpdate(value) {
  mergeDecisions.value = value
  if (mergeConflictId.value) {
    mergeDecisionCache[mergeConflictId.value] = { ...value }
  }
}

function refreshMergePreview() {
  if (!mergeConflict.value) {
    return
  }
  openMergeWorkbench(mergeConflict.value, true)
}

async function submitMerge() {
  if (!mergeConflict.value || !mergePreview.value) {
    return
  }
  mergeSubmitting.value = true
  try {
    await conflictApi.resolve(mergeConflict.value.id, {
      action: 'MERGE',
      merge_session_id: mergePreview.value.session_id,
      merge_decisions: mergeDecisions.value
    })
    ElMessage.success('合并结果已提交')
    const resolvedId = mergeConflict.value.id
    mergeDialogVisible.value = false
    mergePreview.value = null
    mergeConflictId.value = ''
    removeConflict(resolvedId)
  } catch (error) {
    console.error('提交合并失败:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '提交合并失败')
  } finally {
    mergeSubmitting.value = false
  }
}

function removeConflict(conflictId) {
  conflicts.value = conflicts.value.filter(conflict => conflict.id !== conflictId)
  delete mergePreviewCache[conflictId]
  delete mergeDecisionCache[conflictId]
  if (mergeConflictId.value === conflictId) {
    mergeConflictId.value = ''
    mergePreview.value = null
    mergeDecisions.value = {}
  }
  syncActiveConflict()
}

function getConflictTypeLabel(type) {
  return {
    DUPLICATE: '完全重复',
    LANGUAGE_VARIANT: '多语言版本',
    MULTIPLE_VERSIONS: '多版本冲突',
    LINKED_WORK: '关联作品',
    EXTRACT_FAILED: '解压失败'
  }[type] || type || '未知冲突'
}

function formatDate(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

function formatTimestamp(value) {
  if (value === null || value === undefined) {
    return '-'
  }
  return formatDate(new Date(Number(value) * 1000).toISOString())
}

function formatFileSize(size) {
  if (size === null || size === undefined) return '-'
  const value = Number(size)
  if (!Number.isFinite(value) || value < 0) return '-'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = value / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(current >= 10 ? 1 : 2)} ${units[unitIndex]}`
}
</script>

<style scoped>
.conflicts-page {
  display: grid;
  gap: 20px;
  padding: 0 20px 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.page-header h1 {
  margin: 0 0 8px;
  font-size: 28px;
  color: #0f172a;
}

.page-header p {
  margin: 0;
  color: #64748b;
  line-height: 1.6;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.page-alert {
  margin-bottom: -4px;
}

.detail-alert {
  margin-bottom: 16px;
}

.loading-shell {
  min-height: 320px;
  border-radius: 18px;
  background: #fff;
}

.page-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 18px;
  min-height: 620px;
}

.conflict-list {
  display: grid;
  gap: 12px;
  align-content: start;
}

.conflict-card {
  width: 100%;
  text-align: left;
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  background: #fff;
  padding: 14px 16px;
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.conflict-card:hover,
.conflict-card.active {
  border-color: #2563eb;
  box-shadow: 0 10px 30px rgba(37, 99, 235, 0.12);
  transform: translateY(-1px);
}

.card-head,
.card-body {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-head strong {
  color: #0f172a;
  font-size: 16px;
}

.card-body {
  margin-top: 10px;
  align-items: flex-start;
}

.card-body p,
.card-body span {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.conflict-detail {
  display: grid;
  gap: 16px;
}

.detail-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 20px 22px;
  border-radius: 20px;
  background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
  border: 1px solid #dbe4f0;
}

.detail-head h2 {
  margin: 0 0 8px;
  color: #172554;
}

.detail-head p {
  margin: 0;
  color: #64748b;
}

.action-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.meta-block {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}

.meta-block:last-child {
  margin-bottom: 0;
}

.meta-block label {
  color: #64748b;
  font-size: 12px;
}

.meta-block span,
.meta-block pre {
  margin: 0;
  color: #1e293b;
  line-height: 1.6;
}

.meta-block pre {
  white-space: pre-wrap;
  word-break: break-all;
  border-radius: 12px;
  background: #f8fafc;
  padding: 12px;
  font-family: Consolas, Monaco, monospace;
}

.action-help {
  border-radius: 18px;
}

.help-list {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  line-height: 1.8;
}

@media (max-width: 1080px) {
  .page-body,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .page-header,
  .detail-head {
    flex-direction: column;
  }

  .action-row,
  .header-actions {
    width: 100%;
  }

  .action-row :deep(.el-button),
  .header-actions :deep(.el-button) {
    flex: 1;
  }
}
</style>
