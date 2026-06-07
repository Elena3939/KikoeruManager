<template>
  <el-dialog
    :model-value="modelValue"
    title="补全文件夹"
    width="860px"
    custom-class="mobile-full-dialog folder-completion-dialog"
    :close-on-click-modal="!submitting"
    :close-on-press-escape="!submitting"
    @update:model-value="emit('update:modelValue', $event)"
    @open="loadPreview"
    @closed="resetState"
  >
    <div class="folder-completion-root">
      <div v-if="loading" class="folder-completion-loading app-loading-mask">
        <div class="folder-completion-loading-box">
          <span class="folder-completion-spinner"></span>
          <span>{{ loadingText }}</span>
        </div>
      </div>

      <div class="folder-completion-summary">
        <div class="folder-completion-metric">
          <span>可补全</span>
          <strong>{{ summary.downloadable_count || 0 }}</strong>
        </div>
        <div class="folder-completion-metric">
          <span>缺失文件</span>
          <strong>{{ summary.missing_file_count || 0 }}</strong>
        </div>
        <div class="folder-completion-metric">
          <span>预计下载</span>
          <strong>{{ formatSize(summary.estimated_bytes || 0) }}</strong>
        </div>
        <div class="folder-completion-metric">
          <span>跳过</span>
          <strong>{{ summary.skipped_count || 0 }}</strong>
        </div>
      </div>

      <div v-if="errorMessage" class="folder-completion-error">{{ errorMessage }}</div>

      <div v-if="items.length" class="folder-completion-list">
        <label
          v-for="item in items"
          :key="item.key"
          class="folder-completion-row"
          :class="{ 'is-selected': selectedKeys.has(item.key) }"
        >
          <input
            type="checkbox"
            :checked="selectedKeys.has(item.key)"
            @change="toggleItem(item.key, $event.target.checked)"
          >
          <span class="folder-completion-row-main">
            <span class="folder-completion-row-title">
              <b>{{ item.rjcode }}</b>
              <span v-if="item.actual_rjcode && item.actual_rjcode !== item.rjcode">下载 {{ item.actual_rjcode }}</span>
              <em>{{ item.mode === 'full_download' ? '空目录全量补全' : '只补缺失' }}</em>
            </span>
            <span class="folder-completion-row-sub" :title="item.folder_path">{{ item.folder_name || item.folder_path }}</span>
            <span class="folder-completion-row-work" :title="item.work_title">{{ item.work_title || '-' }}</span>
          </span>
          <span class="folder-completion-row-stats">
            <span>缺失 {{ item.missing_total || 0 }}</span>
            <span>已匹配 {{ item.matched_total || 0 }}</span>
            <span>过滤 {{ item.filtered_out_count || 0 }}</span>
            <strong>{{ formatSize(item.estimated_bytes || 0) }}</strong>
          </span>
        </label>
      </div>

      <div v-else-if="!loading && !errorMessage" class="folder-completion-empty">没有需要补全的文件夹</div>

      <div v-if="skipped.length" class="folder-completion-skipped">
        <button type="button" class="folder-completion-skipped-toggle" @click="skippedOpen = !skippedOpen">
          <span>跳过 {{ skipped.length }} 项</span>
          <ChevronDown :size="14" :stroke-width="2.4" :class="{ 'is-open': skippedOpen }" />
        </button>
        <div v-if="skippedOpen" class="folder-completion-skipped-list">
          <div v-for="(row, index) in skipped.slice(0, 80)" :key="`${row.path || row.rjcode || index}`" class="folder-completion-skipped-row">
            <span>{{ row.rjcode || row.name || row.path || '-' }}</span>
            <em>{{ row.reason || '已跳过' }}</em>
          </div>
          <div v-if="skipped.length > 80" class="folder-completion-skipped-more">还有 {{ skipped.length - 80 }} 项未展示</div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="folder-completion-footer">
        <button type="button" class="folder-completion-cancel" :disabled="submitting" @click="emit('update:modelValue', false)">取消</button>
        <StatefulButton
          tone="sky"
          size="default"
          :disabled="submitting || loading || !selectedItems.length"
          @click="submitSelected"
        >
          创建补全任务
        </StatefulButton>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { libraryApi } from '../../api'
import StatefulButton from '../ui/stateful-button.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  libraryId: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
  initialJobId: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'completed', 'preview-started', 'preview-updated'])

const loading = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const items = ref([])
const skipped = ref([])
const summary = ref({})
const selectedKeys = ref(new Set())
const skippedOpen = ref(false)
const previewJobId = ref('')
const currentStep = ref('')
let previewPollTimer = null

const selectedItems = computed(() => items.value.filter(item => selectedKeys.value.has(item.key)))
const loadingText = computed(() => currentStep.value || '正在检查 ASMR.one 与本地文件...')

function resetState () {
  loading.value = false
  submitting.value = false
  errorMessage.value = ''
  items.value = []
  skipped.value = []
  summary.value = {}
  selectedKeys.value = new Set()
  skippedOpen.value = false
  previewJobId.value = ''
  currentStep.value = ''
  stopPreviewPolling()
}

function selectedPaths () {
  return (Array.isArray(props.rows) ? props.rows : [])
    .map(row => String(row?.path || '').trim())
    .filter(Boolean)
}

async function loadPreview () {
  if (!props.modelValue || loading.value) return
  const existingJobId = String(props.initialJobId || '').trim()
  if (existingJobId) {
    previewJobId.value = existingJobId
    loading.value = true
    errorMessage.value = ''
    startPreviewPolling()
    await refreshPreviewJob()
    return
  }
  const paths = selectedPaths()
  if (!props.libraryId || !paths.length) {
    errorMessage.value = '没有选中可补全的目录'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const job = await libraryApi.startFolderCompletionPreview({
      library_id: props.libraryId,
      selected_paths: paths,
    })
    previewJobId.value = job?.job_id || ''
    currentStep.value = job?.current_step || '预览任务已加入后台队列'
    emit('preview-started', job)
    if (!previewJobId.value) throw new Error('后端未返回预览任务 ID')
    startPreviewPolling()
    await refreshPreviewJob()
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '预览失败'
    loading.value = false
  }
}

function startPreviewPolling () {
  stopPreviewPolling()
  previewPollTimer = window.setInterval(refreshPreviewJob, 1200)
}

function stopPreviewPolling () {
  if (!previewPollTimer) return
  window.clearInterval(previewPollTimer)
  previewPollTimer = null
}

async function refreshPreviewJob () {
  if (!previewJobId.value) return
  try {
    const job = await libraryApi.getFolderCompletionPreviewJob(previewJobId.value)
    emit('preview-updated', job)
    const status = String(job?.status || '')
    currentStep.value = job?.current_step || ''
    if (['completed', 'failed', 'cancelled'].includes(status)) {
      stopPreviewPolling()
      loading.value = false
    }
    if (status === 'failed') {
      errorMessage.value = job?.error_message || '预览任务失败'
      return
    }
    if (status === 'cancelled') {
      errorMessage.value = '预览任务已取消'
      return
    }
    const result = job?.result || {}
    if (status !== 'completed' || !result) return
    items.value = Array.isArray(result?.items) ? result.items : []
    skipped.value = Array.isArray(result?.skipped) ? result.skipped : []
    summary.value = result?.summary || {}
    selectedKeys.value = new Set(items.value.filter(item => Number(item?.missing_total || 0) > 0).map(item => item.key))
    skippedOpen.value = !items.value.length && skipped.value.length > 0
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '预览失败'
    stopPreviewPolling()
    loading.value = false
  }
}

onBeforeUnmount(() => {
  stopPreviewPolling()
})

function toggleItem (key, checked) {
  const next = new Set(selectedKeys.value)
  if (checked) next.add(key)
  else next.delete(key)
  selectedKeys.value = next
}

async function submitSelected () {
  if (!selectedItems.value.length || submitting.value) return false
  submitting.value = true
  try {
    const result = await libraryApi.startFolderCompletion({
      library_id: props.libraryId,
      items: selectedItems.value,
    })
    ElMessage.success(result?.message || `已创建 ${result?.created_count || selectedItems.value.length} 个补全任务`)
    emit('completed', result)
    emit('update:modelValue', false)
    return result
  } catch (error) {
    ElMessage.error('创建补全任务失败：' + (error?.response?.data?.detail || error?.message || '未知错误'))
    return false
  } finally {
    submitting.value = false
  }
}

function formatSize (bytes) {
  const value = Number(bytes || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}
</script>

<style scoped>
.folder-completion-root {
  position: relative;
  min-height: 240px;
}

.folder-completion-loading {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  border-radius: 12px;
}

.folder-completion-loading-box {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240);
  background: rgba(255, 255, 255, 0.94);
  padding: 12px 14px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.folder-completion-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgb(186 230 253);
  border-top-color: rgb(2 132 199);
  border-radius: 999px;
  animation: folder-completion-spin 0.8s linear infinite;
}

.folder-completion-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.folder-completion-metric {
  min-width: 0;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: rgb(248 250 252);
  padding: 10px 12px;
}

.folder-completion-metric span {
  display: block;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.folder-completion-metric strong {
  display: block;
  margin-top: 2px;
  color: #0f172a;
  font-size: 17px;
  font-weight: 800;
}

.folder-completion-error,
.folder-completion-empty {
  border-radius: 8px;
  border: 1px solid rgb(254 202 202);
  background: rgb(254 242 242);
  padding: 12px;
  color: #991b1b;
  font-size: 13px;
  font-weight: 700;
}

.folder-completion-empty {
  border-color: rgb(226 232 240);
  background: rgb(248 250 252);
  color: #64748b;
  text-align: center;
}

.folder-completion-list {
  display: grid;
  gap: 8px;
  max-height: min(460px, calc(100vh - 360px));
  overflow: auto;
  padding-right: 2px;
}

.folder-completion-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.folder-completion-row:hover {
  transform: translateY(-2px) scale(1.01);
  border-color: rgb(125 211 252);
}

.folder-completion-row.is-selected {
  border-color: rgb(14 165 233);
  background: rgb(240 249 255);
}

.folder-completion-row input {
  width: 16px;
  height: 16px;
  accent-color: #0284c7;
}

.folder-completion-row-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.folder-completion-row-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.folder-completion-row-title span,
.folder-completion-row-title em {
  border-radius: 999px;
  background: rgb(224 242 254);
  padding: 2px 7px;
  color: #0369a1;
  font-size: 11px;
  font-style: normal;
}

.folder-completion-row-title em {
  background: rgb(220 252 231);
  color: #047857;
}

.folder-completion-row-sub,
.folder-completion-row-work {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  font-size: 12px;
}

.folder-completion-row-work {
  color: #475569;
}

.folder-completion-row-stats {
  display: grid;
  justify-items: end;
  gap: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.folder-completion-row-stats strong {
  color: #0f172a;
  font-size: 12px;
}

.folder-completion-skipped {
  margin-top: 12px;
  border-top: 1px solid rgb(226 232 240);
  padding-top: 10px;
}

.folder-completion-skipped-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.folder-completion-skipped-toggle svg {
  transition: transform 0.25s ease;
}

.folder-completion-skipped-toggle svg.is-open {
  transform: rotate(180deg);
}

.folder-completion-skipped-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
  max-height: 180px;
  overflow: auto;
}

.folder-completion-skipped-row {
  display: grid;
  grid-template-columns: minmax(0, 180px) minmax(0, 1fr);
  gap: 8px;
  border-radius: 8px;
  background: rgb(248 250 252);
  padding: 7px 9px;
  font-size: 12px;
}

.folder-completion-skipped-row span,
.folder-completion-skipped-row em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-completion-skipped-row span {
  color: #334155;
  font-weight: 800;
}

.folder-completion-skipped-row em {
  color: #64748b;
  font-style: normal;
}

.folder-completion-skipped-more {
  color: #64748b;
  font-size: 12px;
  text-align: center;
}

.folder-completion-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
}

.folder-completion-cancel {
  min-height: 36px;
  border: 1px solid rgb(226 232 240);
  border-radius: 999px;
  background: #fff;
  padding: 0 15px;
  color: #334155;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.folder-completion-cancel:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgb(248 250 252);
}

.folder-completion-cancel:active:not(:disabled) {
  transform: scale(0.96);
}

@keyframes folder-completion-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .folder-completion-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .folder-completion-row {
    grid-template-columns: 18px minmax(0, 1fr);
  }

  .folder-completion-row-stats {
    grid-column: 2;
    justify-items: start;
    grid-template-columns: repeat(2, max-content);
    gap: 5px 10px;
  }

  .folder-completion-skipped-row {
    grid-template-columns: minmax(0, 1fr);
  }
}

:global(html.kikoerumanager-dark) .folder-completion-loading-box {
  border-color: rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.94);
  color: #e5e7eb;
}

:global(html.kikoerumanager-dark) .folder-completion-metric,
:global(html.kikoerumanager-dark) .folder-completion-empty,
:global(html.kikoerumanager-dark) .folder-completion-skipped-row {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.06);
}

:global(html.kikoerumanager-dark) .folder-completion-metric span,
:global(html.kikoerumanager-dark) .folder-completion-row-sub,
:global(html.kikoerumanager-dark) .folder-completion-row-stats,
:global(html.kikoerumanager-dark) .folder-completion-skipped-toggle,
:global(html.kikoerumanager-dark) .folder-completion-skipped-row em {
  color: #9ca3af;
}

:global(html.kikoerumanager-dark) .folder-completion-metric strong,
:global(html.kikoerumanager-dark) .folder-completion-row-title,
:global(html.kikoerumanager-dark) .folder-completion-row-stats strong,
:global(html.kikoerumanager-dark) .folder-completion-skipped-row span {
  color: #f8fafc;
}

:global(html.kikoerumanager-dark) .folder-completion-row {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.05);
}

:global(html.kikoerumanager-dark) .folder-completion-row.is-selected {
  border-color: rgba(56, 189, 248, 0.65);
  background: rgba(14, 165, 233, 0.14);
}

:global(html.kikoerumanager-dark) .folder-completion-row-work {
  color: #cbd5e1;
}

:global(html.kikoerumanager-dark) .folder-completion-cancel {
  border-color: rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
}
</style>
