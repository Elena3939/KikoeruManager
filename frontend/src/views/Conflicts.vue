<template>
  <div class="conflicts-page">
    <div class="page-header">
      <div>
        <h1>问题作品</h1>
        <p>重复作品以及解压失败作品处理</p>
      </div>
      <div class="header-actions">
        <span v-if="batchRunning" class="batch-status">批量处理中: {{ batchActionLabel }}</span>
        <el-button :loading="loading" :disabled="batchRunning" @click="fetchConflicts">刷新列表</el-button>
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
      <aside class="conflict-list-shell">
        <div class="list-toolbar">
          <div>
            <h3>待处理列表</h3>
            <p>已选 {{ selectedCount }} / {{ conflicts.length }}</p>
            <span class="list-hint">单击聚焦，`Ctrl/Command` 多选，`Shift` 连续选择</span>
          </div>
        </div>

        <div class="conflict-list">
          <article
            v-for="conflict in conflicts"
            :key="conflict.id"
            class="conflict-card"
            :class="{
              active: conflict.id === activeConflictId,
              selected: isConflictSelected(conflict.id),
            }"
            @click="handleConflictCardClick(conflict, $event)"
          >
            <div class="card-head">
              <div class="card-title">
                <strong>{{ conflict.rjcode || '未识别 RJ' }}</strong>
              </div>
              <el-tag :type="conflict.context?.existing?.is_remote ? 'warning' : 'primary'" effect="plain">
                {{ conflict.context?.existing?.is_remote ? '远程库存' : '本地库存' }}
              </el-tag>
            </div>
            <div class="card-body">
              <p>{{ getConflictTypeLabel(conflict.conflict_type) }}</p>
              <span>{{ formatDate(conflict.created_at) }}</span>
            </div>
          </article>
        </div>
      </aside>

      <section class="conflict-detail" v-if="activeConflict">
        <div class="detail-head">
          <div>
            <div class="detail-title-row">
              <h2>{{ activeConflict.rjcode || '未识别 RJ' }}</h2>
              <el-tag v-if="isConflictSelected(activeConflict.id)" type="primary" effect="plain">已加入批量</el-tag>
            </div>
            <p>{{ getConflictTypeLabel(activeConflict.conflict_type) }}</p>
          </div>
          <div class="action-row">
            <el-button
              v-if="canUseAction(activeConflict, 'KEEP_NEW')"
              type="primary"
              :loading="isActionLoading(activeConflict.id, 'KEEP_NEW')"
              :disabled="batchRunning || isConflictBusy(activeConflict.id)"
              @click="handleKeepNew(activeConflict)"
            >
              保留新版
            </el-button>
            <el-button
              v-if="canUseAction(activeConflict, 'RETRY')"
              type="success"
              :loading="isActionLoading(activeConflict.id, 'RETRY')"
              :disabled="batchRunning || isConflictBusy(activeConflict.id)"
              @click="handleRetry(activeConflict)"
            >
              重试
            </el-button>
            <el-button
              v-if="canUseAction(activeConflict, 'SKIP')"
              type="info"
              :loading="isActionLoading(activeConflict.id, 'SKIP')"
              :disabled="batchRunning || isConflictBusy(activeConflict.id)"
              @click="handleSkip(activeConflict)"
            >
              跳过
            </el-button>
            <el-button
              v-if="canUseAction(activeConflict, 'MERGE')"
              type="warning"
              :loading="mergeLoading && mergeConflictId === activeConflict.id"
              :disabled="batchRunning || isConflictBusy(activeConflict.id)"
              @click="openMergeWorkbench(activeConflict)"
            >
              合并
            </el-button>
          </div>
        </div>

        <el-alert
          v-if="isFailureConflict(activeConflict)"
          :title="isExtractFailed(activeConflict) ? '这是一条解压失败问题项，不是重复作品冲突' : '这是一条处理失败问题项，不是重复作品冲突'"
          type="error"
          show-icon
          :closable="false"
          class="detail-alert"
        >
          <template #default>
            <span>{{ activeConflict.new_metadata?.error_message || (isExtractFailed(activeConflict) ? '解压阶段失败，请检查密码、分卷完整性或压缩包本身是否损坏。' : '导入流程处理中途失败，请按失败原因修复后重试。') }}</span>
          </template>
        </el-alert>

        <div class="detail-grid">
          <el-card shadow="never">
            <template #header>{{ isFailureConflict(activeConflict) ? '失败来源' : '当前新内容' }}</template>
            <div class="meta-block">
              <label>来源路径</label>
              <pre>{{ getConflictSourcePath(activeConflict) }}</pre>
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
              <label>{{ isFailureConflict(activeConflict) ? '附带信息' : '作品信息' }}</label>
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
            <template #header>{{ isFailureConflict(activeConflict) ? '处理建议' : '已存在目录' }}</template>
            <div class="meta-block">
              <label>{{ isFailureConflict(activeConflict) ? '建议动作' : '目标路径' }}</label>
              <pre v-if="!isFailureConflict(activeConflict)">{{ getExistingConflictPath(activeConflict) }}</pre>
              <span v-else>{{ isExtractFailed(activeConflict) ? '可直接跳过并删除当前失败来源；如果你已经补充了正确密码或完整分卷，建议回到任务列表重新处理。' : '可先根据失败原因修复来源内容后重试；如果确认不再处理，也可以直接跳过删除当前失败来源。' }}</span>
            </div>
            <div class="meta-block" v-if="!isFailureConflict(activeConflict)">
              <label>落地位置</label>
              <span>{{ activeConflict.context?.existing?.library_name || '默认库存' }}</span>
              <span>{{ activeConflict.context?.existing?.is_remote ? '群晖远程目录' : '本地目录' }}</span>
            </div>
            <div class="meta-block" v-if="!isFailureConflict(activeConflict)">
              <label>文件大小</label>
              <span>{{ formatFileSize(activeConflict.context?.existing?.stats?.size) }}</span>
            </div>
            <div class="meta-block" v-if="!isFailureConflict(activeConflict)">
              <label>创建时间</label>
              <span>{{ formatTimestamp(activeConflict.context?.existing?.stats?.created_at) }}</span>
            </div>
            <div class="meta-block">
              <label>{{ isFailureConflict(activeConflict) ? '记录时间' : '检测时间' }}</label>
              <span>{{ formatDate(activeConflict.created_at) }}</span>
            </div>
          </el-card>
        </div>

        <el-card shadow="never" class="action-help">
          <template #header>{{ isFailureConflict(activeConflict) ? '失败说明' : '动作说明' }}</template>
          <ul v-if="!isFailureConflict(activeConflict)" class="help-list">
            <li>保留新版：先经过删除审查，再安全替换已有目录，失败时走最小化破坏路径。</li>
            <li>跳过：不解压，直接删除当前压缩包或待处理目录，原有目录保持不变。</li>
            <li>合并：进入组件文件夹对比视图，逐文件决定保留新文件、旧文件或删除。</li>
          </ul>
          <ul v-else class="help-list">
            <li>{{ isExtractFailed(activeConflict) ? '当前问题发生在解压阶段，不代表库存中已经有重复作品。' : '当前问题发生在导入处理链路中，不代表库存中已经有重复作品。' }}</li>
            <li>{{ isExtractFailed(activeConflict) ? '如果错误是密码不正确、分卷缺失或压缩包损坏，修复后重新处理通常更合适。' : '如果错误发生在元数据、重命名、过滤或分类阶段，优先按当前失败原因排查对应链路。' }}</li>
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
import { conflictApi, taskCenterApi } from '../api'

const ACTIVE_CONFLICT_STORAGE_KEY = 'prekikoeru-conflicts-active-id'

const conflicts = ref([])
const loading = ref(false)
const errorMessage = ref('')
const activeConflictId = ref(localStorage.getItem(ACTIVE_CONFLICT_STORAGE_KEY) || '')
const selectedConflictIds = ref([])
const selectionAnchorId = ref('')
const actionState = reactive({})

const batchRunning = ref(false)
const batchActionLabel = ref('')

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
const selectedConflicts = computed(() => conflicts.value.filter(conflict => selectedConflictIds.value.includes(conflict.id)))
const selectedCount = computed(() => selectedConflicts.value.length)
const hasSelection = computed(() => selectedCount.value > 0)
const isAllSelected = computed(() => conflicts.value.length > 0 && selectedCount.value === conflicts.value.length)

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
    syncSelectedConflicts()
    syncActiveConflict()
  } catch (error) {
    console.error('获取问题作品失败:', error)
    errorMessage.value = resolveErrorMessage(error, '获取问题作品失败')
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

function syncSelectedConflicts() {
  const existingIds = new Set(conflicts.value.map(conflict => conflict.id))
  selectedConflictIds.value = selectedConflictIds.value.filter(id => existingIds.has(id))
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

function isFailureConflict(conflict) {
  return ['EXTRACT_FAILED', 'PROCESS_FAILED'].includes(conflict?.conflict_type)
}

function isConflictSelected(conflictId) {
  return selectedConflictIds.value.includes(conflictId)
}

function setConflictSelected(conflictId, selected) {
  if (selected && !selectedConflictIds.value.includes(conflictId)) {
    selectedConflictIds.value = [...selectedConflictIds.value, conflictId]
    selectionAnchorId.value = conflictId
    return
  }
  if (!selected) {
    selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
  }
}

function handleConflictCardClick(conflict, event) {
  if (!conflict?.id || batchRunning.value) {
    return
  }

  const conflictId = conflict.id
  const useRange = Boolean(event?.shiftKey) && selectionAnchorId.value
  const toggleMode = Boolean(event?.ctrlKey || event?.metaKey)

  if (useRange) {
    const ids = conflicts.value.map(item => item.id)
    const startIndex = ids.indexOf(selectionAnchorId.value)
    const endIndex = ids.indexOf(conflictId)
    if (startIndex !== -1 && endIndex !== -1) {
      const [from, to] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
      selectedConflictIds.value = ids.slice(from, to + 1)
    } else {
      selectedConflictIds.value = [conflictId]
    }
  } else if (toggleMode) {
    if (isConflictSelected(conflictId)) {
      selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
    } else {
      selectedConflictIds.value = [...selectedConflictIds.value, conflictId]
    }
  } else {
    selectedConflictIds.value = [conflictId]
  }

  activeConflictId.value = conflictId
  selectionAnchorId.value = conflictId
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    clearSelection()
    return
  }
  selectedConflictIds.value = conflicts.value.map(conflict => conflict.id)
  selectionAnchorId.value = selectedConflictIds.value[selectedConflictIds.value.length - 1] || ''
}

function clearSelection() {
  selectedConflictIds.value = []
  selectionAnchorId.value = ''
}

function selectedActionCount(action) {
  return selectedConflicts.value.filter(conflict => canUseAction(conflict, action)).length
}

function getSelectedConflictsForAction(action) {
  return selectedConflicts.value.filter(conflict => canUseAction(conflict, action))
}

function batchButtonLabel(action, label) {
  const count = selectedActionCount(action)
  return count ? `${label} (${count})` : label
}

function resolveErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function formatConflictLabel(conflict) {
  return conflict?.rjcode || conflict?.new_metadata?.work_name || conflict?.new_path || '未识别问题项'
}

function getConflictSourcePath(conflict) {
  return conflict?.context?.source?.resolved_path || conflict?.context?.source?.path || conflict?.new_path || '-'
}

function getExistingConflictPath(conflict) {
  return conflict?.context?.existing?.path || conflict?.existing_path || '-'
}

function setBatchState(label, value) {
  batchRunning.value = value
  batchActionLabel.value = value ? label : ''
}

function buildPathPreview(paths) {
  const lines = paths.slice(0, 5)
  if (paths.length > lines.length) {
    lines.push(`以及另外 ${paths.length - lines.length} 项`)
  }
  return lines.join('\n')
}

async function waitForRetryTask(taskId) {
  const deadline = Date.now() + 10 * 60 * 1000

  while (Date.now() < deadline) {
    await new Promise(resolve => window.setTimeout(resolve, 1500))
    const task = await taskCenterApi.getItem({ engine_task_id: taskId })
    if (!task) {
      continue
    }
    if (task.status === 'completed') {
      return task
    }
    if (task.status === 'failed') {
      throw new Error(task.error_message || '重试失败')
    }
  }

  throw new Error('重试超时，请到任务列表查看进度')
}

async function loadKeepNewPreview(conflict) {
  const response = await conflictApi.preview(conflict.id, 'KEEP_NEW')
  return response.preview || {}
}

function buildKeepNewSummary(conflict, preview) {
  return [
    `将删除目标目录：${preview.path || conflict.existing_path || '-'}`,
    `文件夹数：${preview.folder_count ?? 0}`,
    `文件数：${preview.file_count ?? 0}`,
    `大小：${formatFileSize(preview.size)}`
  ].join('\n')
}

async function resolveKeepNew(conflict, preview = null) {
  const effectivePreview = preview || await loadKeepNewPreview(conflict)
  await conflictApi.resolve(conflict.id, {
    action: 'KEEP_NEW',
    confirmed: true
  })
  removeConflict(conflict.id)
  return effectivePreview
}

async function resolveSkip(conflict) {
  await conflictApi.resolve(conflict.id, {
    action: 'SKIP'
  })
  removeConflict(conflict.id)
}

async function startRetry(conflict) {
  return conflictApi.retry(conflict.id)
}

async function getMergePreview(conflict, forceRefresh = false) {
  let preview = mergePreviewCache[conflict.id]
  if (!preview || forceRefresh) {
    preview = await conflictApi.preview(conflict.id, 'MERGE')
    mergePreviewCache[conflict.id] = preview
  }
  return preview
}

async function resolveMerge(conflict, preview = null, decisions = null) {
  const effectivePreview = preview || await getMergePreview(conflict)
  const effectiveDecisions = decisions || mergeDecisionCache[conflict.id] || effectivePreview.default_decisions || {}
  await conflictApi.resolve(conflict.id, {
    action: 'MERGE',
    merge_session_id: effectivePreview.session_id,
    merge_decisions: effectiveDecisions
  })
  removeConflict(conflict.id)
  return effectivePreview
}

async function presentBatchResult(actionLabel, successes, failures, extraMessage = '') {
  const summary = `${actionLabel}完成：成功 ${successes.length} 项${failures.length ? `，失败 ${failures.length} 项` : ''}`

  if (!successes.length && failures.length) {
    ElMessage.error(summary)
  } else if (failures.length) {
    ElMessage.warning(summary)
  } else {
    ElMessage.success(summary)
  }

  if (!failures.length) {
    return
  }

  const detailLines = failures.slice(0, 8).map(item => `${formatConflictLabel(item.conflict)}：${item.message}`)
  if (failures.length > detailLines.length) {
    detailLines.push(`另有 ${failures.length - detailLines.length} 项失败`)
  }
  if (extraMessage) {
    detailLines.unshift(extraMessage)
  }

  await ElMessageBox.alert(detailLines.join('\n'), `${actionLabel}详情`, {
    type: 'warning',
    confirmButtonText: '知道了'
  })
}

async function handleRetry(conflict) {
  markAction(conflict.id, 'RETRY', true)
  try {
    const result = await startRetry(conflict)
    ElMessage.success(result.already_running ? '已存在重试任务，正在继续跟踪结果' : '已开始重试')
    await waitForRetryTask(result.task_id)
    await fetchConflicts()
    if (conflicts.value.some(item => item.id === conflict.id)) {
      ElMessage.warning('重试任务已完成，但问题项仍在列表里，请刷新后再确认')
      return
    }
    ElMessage.success('重试成功，已移出问题作品')
  } catch (error) {
    console.error('重试问题作品失败:', error)
    await fetchConflicts()
    ElMessage.error(resolveErrorMessage(error, '重试失败'))
  } finally {
    markAction(conflict.id, 'RETRY', false)
  }
}

async function handleKeepNew(conflict) {
  markAction(conflict.id, 'KEEP_NEW', true)
  try {
    const preview = await loadKeepNewPreview(conflict)
    await ElMessageBox.confirm(buildKeepNewSummary(conflict, preview), '删除审查确认', {
      confirmButtonText: '确认删除并写入新内容',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await resolveKeepNew(conflict, preview)
    ElMessage.success('已完成保留新版')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('保留新版失败:', error)
      ElMessage.error(resolveErrorMessage(error, '保留新版失败'))
    }
  } finally {
    markAction(conflict.id, 'KEEP_NEW', false)
  }
}

async function handleSkip(conflict) {
  markAction(conflict.id, 'SKIP', true)
  try {
    await ElMessageBox.confirm(
      `将直接删除待处理来源：${getConflictSourcePath(conflict)}`,
      '跳过当前压缩包',
      {
        confirmButtonText: '确认跳过',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await resolveSkip(conflict)
    ElMessage.success('已跳过当前包')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('跳过失败:', error)
      ElMessage.error(resolveErrorMessage(error, '跳过失败'))
    }
  } finally {
    markAction(conflict.id, 'SKIP', false)
  }
}

async function handleBatchKeepNew() {
  const targets = getSelectedConflictsForAction('KEEP_NEW')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行“保留新版”的问题项')
    return
  }

  setBatchState('保留新版', true)
  try {
    const previewEntries = []
    const failures = []

    for (const conflict of targets) {
      try {
        const preview = await loadKeepNewPreview(conflict)
        previewEntries.push({ conflict, preview })
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '生成删除审查失败') })
      }
    }

    if (!previewEntries.length) {
      await presentBatchResult('批量保留新版', [], failures)
      return
    }

    const totalFiles = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.file_count || 0), 0)
    const totalFolders = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.folder_count || 0), 0)
    const totalSize = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.size || 0), 0)
    const previewPaths = previewEntries.map(entry => entry.preview.path || entry.conflict.existing_path || '-')

    await ElMessageBox.confirm(
      [
        `将批量保留新版 ${previewEntries.length} 项`,
        `待删除文件夹数：${totalFolders}`,
        `待删除文件数：${totalFiles}`,
        `待删除总大小：${formatFileSize(totalSize)}`,
        '',
        buildPathPreview(previewPaths)
      ].join('\n'),
      '批量删除审查确认',
      {
        confirmButtonText: '确认批量执行',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const successes = []
    for (const entry of previewEntries) {
      try {
        await resolveKeepNew(entry.conflict, entry.preview)
        successes.push(entry.conflict)
      } catch (error) {
        failures.push({ conflict: entry.conflict, message: resolveErrorMessage(error, '保留新版失败') })
      }
    }

    await presentBatchResult('批量保留新版', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量保留新版失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量保留新版失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

async function handleBatchSkip() {
  const targets = getSelectedConflictsForAction('SKIP')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行“跳过”的问题项')
    return
  }

  setBatchState('跳过', true)
  try {
    await ElMessageBox.confirm(
      [
        `将批量跳过 ${targets.length} 项，并删除它们的待处理来源。`,
        '',
        buildPathPreview(targets.map(conflict => getConflictSourcePath(conflict)))
      ].join('\n'),
      '批量跳过确认',
      {
        confirmButtonText: '确认批量跳过',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const successes = []
    const failures = []
    for (const conflict of targets) {
      try {
        await resolveSkip(conflict)
        successes.push(conflict)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '跳过失败') })
      }
    }

    await presentBatchResult('批量跳过', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量跳过失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量跳过失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

async function handleBatchMerge() {
  const targets = getSelectedConflictsForAction('MERGE')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行“合并”的问题项')
    return
  }

  setBatchState('合并', true)
  try {
    await ElMessageBox.confirm(
      [
        `将批量合并 ${targets.length} 项。`,
        '未单独打开工作台的项目会按默认合并决策直接执行。',
        '如果某项已经在工作台调整过决策，将优先沿用已保存的决策。'
      ].join('\n'),
      '批量合并确认',
      {
        confirmButtonText: '确认批量合并',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const successes = []
    const failures = []
    for (const conflict of targets) {
      try {
        const preview = await getMergePreview(conflict)
        const decisions = mergeDecisionCache[conflict.id] || preview.default_decisions || {}
        await resolveMerge(conflict, preview, decisions)
        successes.push(conflict)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '合并失败') })
      }
    }

    await presentBatchResult('批量合并', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量合并失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量合并失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

async function handleBatchRetry() {
  const targets = getSelectedConflictsForAction('RETRY')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行“重试”的问题项')
    return
  }

  setBatchState('重试', true)
  try {
    const successes = []
    const failures = []

    for (const conflict of targets) {
      try {
        await startRetry(conflict)
        successes.push(conflict)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '提交重试失败') })
      }
    }

    await fetchConflicts()
    await presentBatchResult('批量重试', successes, failures, '重试任务已提交，请到任务列表跟踪执行结果。')
  } catch (error) {
    console.error('批量重试失败:', error)
    ElMessage.error(resolveErrorMessage(error, '批量重试失败'))
  } finally {
    setBatchState('', false)
  }
}

async function openMergeWorkbench(conflict, forceRefresh = false) {
  mergeConflictId.value = conflict.id
  mergeDialogVisible.value = true
  mergeLoading.value = true
  try {
    const preview = await getMergePreview(conflict, forceRefresh)
    mergePreview.value = preview
    mergeDecisions.value = {
      ...(mergeDecisionCache[conflict.id] || preview.default_decisions || {})
    }
  } catch (error) {
    console.error('生成合并预览失败:', error)
    ElMessage.error(resolveErrorMessage(error, '生成合并预览失败'))
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
    await resolveMerge(mergeConflict.value, mergePreview.value, mergeDecisions.value)
    ElMessage.success('合并结果已提交')
    mergeDialogVisible.value = false
    mergePreview.value = null
    mergeConflictId.value = ''
    mergeDecisions.value = {}
  } catch (error) {
    console.error('提交合并失败:', error)
    ElMessage.error(resolveErrorMessage(error, '提交合并失败'))
  } finally {
    mergeSubmitting.value = false
  }
}

function removeConflict(conflictId) {
  conflicts.value = conflicts.value.filter(conflict => conflict.id !== conflictId)
  selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
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
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败'
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
  align-items: center;
  gap: 12px;
}

.batch-status {
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
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
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  min-height: 620px;
}

.conflict-list-shell {
  display: grid;
  gap: 14px;
  align-content: start;
}

.list-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.list-toolbar h3 {
  margin: 0 0 6px;
  color: #0f172a;
  font-size: 16px;
}

.list-toolbar p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.list-hint {
  display: inline-block;
  margin-top: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.list-toolbar-actions,
.batch-toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.batch-toolbar {
  padding: 14px;
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  background: #f8fbff;
}

.conflict-list {
  display: grid;
  gap: 12px;
  align-content: start;
}

.conflict-card {
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.98)),
    radial-gradient(circle at top right, rgba(37, 99, 235, 0.08), transparent 42%);
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

.conflict-card.selected {
  border-color: #3b82f6;
  box-shadow:
    0 14px 34px rgba(37, 99, 235, 0.18),
    inset 0 0 0 1px rgba(59, 130, 246, 0.35);
}

.card-head,
.card-body {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.card-head strong {
  color: #0f172a;
  font-size: 16px;
  word-break: break-all;
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

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.detail-head h2 {
  margin: 0;
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

@media (max-width: 1180px) {
  .page-body,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .page-header,
  .detail-head,
  .list-toolbar {
    flex-direction: column;
  }

  .action-row,
  .header-actions,
  .list-toolbar-actions,
  .batch-toolbar {
    width: 100%;
  }

  .action-row :deep(.el-button),
  .header-actions :deep(.el-button),
  .list-toolbar-actions :deep(.el-button),
  .batch-toolbar :deep(.el-button) {
    flex: 1;
  }
}
</style>
