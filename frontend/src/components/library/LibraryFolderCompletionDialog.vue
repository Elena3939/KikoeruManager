<template>
  <Teleport to="body">
    <Transition name="folder-completion-fade">
      <div
        v-if="modelValue"
        class="custom-preview-overlay folder-completion-overlay"
        @click.self="handleBackdropClick"
      >
        <section
          class="custom-preview-modal folder-completion-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="folder-completion-title"
        >
          <div class="window panel-enter glass-shell folder-completion-window">
            <div class="window-header folder-completion-header">
              <div class="folder-completion-heading">
                <h1 id="folder-completion-title" class="title">补全文件夹</h1>
                <p>检查已选目录缺失文件，并按 ASMR.one 可用资源创建补全任务</p>
              </div>
              <button
                type="button"
                class="interactive-chip close-button folder-completion-close"
                :disabled="submitting"
                aria-label="关闭"
                @click="closeDialog"
              >
                <X :size="20" :stroke-width="2" />
              </button>
            </div>

            <div class="folder-completion-body">
              <div v-if="loading" class="folder-completion-loading app-loading-mask">
                <div class="folder-completion-loading-box">
                  <AppLoadingAnimation variant="block" :size="96" :centered="false" />
                  <span>{{ loadingText }}</span>
                </div>
              </div>

              <div v-if="!loading || items.length || skipped.length || errorMessage" class="folder-completion-summary">
                <div class="folder-completion-metric is-ready">
                  <span class="folder-completion-metric-icon">
                    <CheckCircle2 :size="15" :stroke-width="2.4" />
                  </span>
                  <span class="folder-completion-metric-copy">
                    <strong>{{ summary.downloadable_count || 0 }}</strong>
                    <em>可补全</em>
                  </span>
                </div>
                <div class="folder-completion-metric is-missing">
                  <span class="folder-completion-metric-icon">
                    <FileSearch :size="15" :stroke-width="2.4" />
                  </span>
                  <span class="folder-completion-metric-copy">
                    <strong>{{ summary.missing_file_count || 0 }}</strong>
                    <em>缺失文件</em>
                  </span>
                </div>
                <div class="folder-completion-metric is-size">
                  <span class="folder-completion-metric-icon">
                    <Download :size="15" :stroke-width="2.4" />
                  </span>
                  <span class="folder-completion-metric-copy">
                    <strong>{{ formatSize(summary.estimated_bytes || 0) }}</strong>
                    <em>预计下载</em>
                  </span>
                </div>
                <div class="folder-completion-metric is-skipped">
                  <span class="folder-completion-metric-icon">
                    <Ban :size="15" :stroke-width="2.4" />
                  </span>
                  <span class="folder-completion-metric-copy">
                    <strong>{{ summary.skipped_count || 0 }}</strong>
                    <em>跳过</em>
                  </span>
                </div>
              </div>

              <div v-if="errorMessage" class="folder-completion-error">{{ errorMessage }}</div>

              <div v-if="items.length" class="folder-completion-list">
                <div
                  v-for="item in items"
                  :key="item.key"
                  class="folder-completion-item"
                >
                  <label
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
                      <button
                        v-if="downloadResourcesForItem(item).length"
                        type="button"
                        class="folder-completion-files-toggle"
                        @click.stop.prevent="toggleResourceDetails(item.key)"
                      >
                        <span>待下载文件</span>
                        <ChevronDown :size="13" :stroke-width="2.4" :class="{ 'is-open': expandedResourceKeys.has(item.key) }" />
                      </button>
                    </span>
                  </label>
                  <Transition name="folder-completion-files">
                    <div v-if="expandedResourceKeys.has(item.key)" class="folder-completion-files">
                      <div
                        v-for="(resource, resourceIndex) in downloadResourcesForItem(item).slice(0, 100)"
                        :key="`${item.key}-${resource.relative_path || resource.file_name || resourceIndex}`"
                        class="folder-completion-file-row"
                      >
                        <span class="folder-completion-file-icon" :class="resourceIconClass(resource)" aria-hidden="true">
                          <component :is="resourceIcon(resource)" :size="15" :stroke-width="2.2" />
                        </span>
                        <span class="folder-completion-file-name" :title="resource.relative_path || resource.file_name">
                          {{ displayResourceName(resource) }}
                        </span>
                        <span class="folder-completion-file-type">{{ formatResourceType(resource) }}</span>
                        <strong>{{ formatSize(resource.size_bytes || resource.size || 0) }}</strong>
                      </div>
                      <div v-if="downloadResourcesForItem(item).length > 100" class="folder-completion-files-more">
                        还有 {{ downloadResourcesForItem(item).length - 100 }} 个文件未展示
                      </div>
                    </div>
                  </Transition>
                </div>
              </div>

              <AppEmptyState
                v-else-if="!loading && !errorMessage"
                class="folder-completion-empty-state"
                size="sm"
                :description="emptyStateDescription"
              />

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

            <div class="folder-completion-footer">
              <p class="summary">
                已选 <span class="summary-strong">{{ selectedItems.length }}</span> / {{ items.length }} 项
              </p>
              <div class="footer-actions">
                <button type="button" class="secondary-cta folder-completion-cancel" :disabled="submitting" @click="closeDialog">取消</button>
                <StatefulButton
                  unstyled
                  class="folder-completion-submit"
                  :disabled="submitting || loading || !selectedItems.length"
                  @click="submitSelected"
                >
                  创建补全下载任务
                </StatefulButton>
              </div>
            </div>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Ban, CheckCircle2, ChevronDown, Download, File, FileArchive, FileAudio, FileImage, FileSearch, FileText, FileVideo, Subtitles, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { libraryApi } from '../../api'
import AppEmptyState from '../common/AppEmptyState.vue'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
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
const expandedResourceKeys = ref(new Set())
const skippedOpen = ref(false)
const previewJobId = ref('')
const currentStep = ref('')
let previewPollTimer = null

const selectedItems = computed(() => items.value.filter(item => selectedKeys.value.has(item.key)))
const loadingText = computed(() => currentStep.value || '正在检查 ASMR.one 与本地文件...')
const emptyStateDescription = computed(() => {
  if (skipped.value.length) {
    const upToDateCount = skipped.value.filter(isUpToDateSkipped).length
    if (upToDateCount === skipped.value.length) return '已检查，当前没有缺失文件'
    if (upToDateCount > 0) return `没有可创建的补全任务，其中 ${upToDateCount} 项已是完整状态`
    return '没有可创建的补全任务'
  }
  return '没有需要补全的文件夹'
})

function isUpToDateSkipped (row) {
  const status = String(row?.status || '').trim().toLowerCase()
  const reason = String(row?.reason || '').trim()
  return status === 'up_to_date' || reason === '没有缺失文件'
}

watch(() => props.modelValue, (visible) => {
  if (visible) {
    window.addEventListener('keydown', handleKeydown)
    loadPreview()
    return
  }
  window.removeEventListener('keydown', handleKeydown)
  resetState()
}, { immediate: true })

function closeDialog () {
  if (submitting.value) return
  emit('update:modelValue', false)
}

function handleBackdropClick () {
  closeDialog()
}

function handleKeydown (event) {
  if (event.key !== 'Escape') return
  closeDialog()
}

function resetState () {
  loading.value = false
  submitting.value = false
  errorMessage.value = ''
  items.value = []
  skipped.value = []
  summary.value = {}
  selectedKeys.value = new Set()
  expandedResourceKeys.value = new Set()
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
    currentStep.value = job?.current_step || '检查任务已加入后台队列'
    emit('preview-started', job)
    if (!previewJobId.value) throw new Error('后端未返回检查任务 ID')
    startPreviewPolling()
    await refreshPreviewJob()
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '检查失败'
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
      errorMessage.value = job?.error_message || '检查任务失败'
      return
    }
    if (status === 'cancelled') {
      errorMessage.value = '检查任务已取消'
      return
    }
    const result = job?.result || {}
    if (status !== 'completed' || !result) return
    items.value = Array.isArray(result?.items) ? result.items : []
    skipped.value = Array.isArray(result?.skipped) ? result.skipped : []
    summary.value = result?.summary || {}
    selectedKeys.value = new Set(items.value.filter(item => Number(item?.missing_total || 0) > 0).map(item => item.key))
    expandedResourceKeys.value = new Set(items.value.length === 1 ? [items.value[0].key] : [])
    skippedOpen.value = !items.value.length && skipped.value.length > 0
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '检查失败'
    stopPreviewPolling()
    loading.value = false
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  stopPreviewPolling()
})

function toggleItem (key, checked) {
  const next = new Set(selectedKeys.value)
  if (checked) next.add(key)
  else next.delete(key)
  selectedKeys.value = next
}

function toggleResourceDetails (key) {
  const next = new Set(expandedResourceKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedResourceKeys.value = next
}

function downloadResourcesForItem (item) {
  const resources = Array.isArray(item?.selected_resources)
    ? item.selected_resources
    : Array.isArray(item?.missing_resources)
      ? item.missing_resources
      : []
  return resources.filter(resource => resource && typeof resource === 'object')
}

function displayResourceName (resource) {
  const path = String(resource?.relative_path || resource?.file_name || '').replace(/\\/g, '/')
  return path || '-'
}

function formatResourceType (resource) {
  const type = String(resource?.resource_type || '').trim()
  if (!type) return '文件'
  const labels = {
    audio: '音频',
    image: '图片',
    text: '文本',
    subtitle: '字幕',
    archive: '压缩包',
    video: '视频',
    other: '其他',
  }
  return labels[type] || type
}

function resourceIcon (resource) {
  const type = String(resource?.resource_type || '').trim()
  if (type === 'audio') return FileAudio
  if (type === 'image') return FileImage
  if (type === 'text') return FileText
  if (type === 'subtitle') return Subtitles
  if (type === 'archive') return FileArchive
  if (type === 'video') return FileVideo
  return File
}

function resourceIconClass (resource) {
  const type = String(resource?.resource_type || 'other').trim() || 'other'
  return `is-${type}`
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
.folder-completion-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.28);
}

.folder-completion-modal {
  width: min(920px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
}

.folder-completion-window {
  width: 100%;
  max-height: calc(100vh - 48px);
  border-radius: 24px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(15, 23, 42, 0.07);
  box-shadow: 0 24px 72px rgba(15, 23, 42, 0.2);
  backdrop-filter: blur(18px) saturate(128%);
  -webkit-backdrop-filter: blur(18px) saturate(128%);
}

.folder-completion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 20px 24px 14px;
  background: transparent;
}

.folder-completion-heading {
  min-width: 0;
}

.folder-completion-heading .title {
  font-size: 22px;
  line-height: 1.1;
  letter-spacing: 0;
}

.folder-completion-heading p {
  margin: 6px 0 0;
  overflow: hidden;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-completion-close {
  display: inline-flex;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  color: #64748b;
}

.folder-completion-close:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
}

.folder-completion-close:active:not(:disabled) {
  transform: scale(0.96);
}

.folder-completion-body {
  position: relative;
  min-height: 260px;
  overflow: hidden auto;
  padding: 4px 24px 16px;
  background: transparent;
}

.folder-completion-loading {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
}

.folder-completion-loading-box {
  display: grid;
  justify-items: center;
  align-items: center;
  gap: 6px;
  max-width: min(320px, calc(100vw - 80px));
  border: 0;
  background: transparent;
  padding: 0;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
}

.folder-completion-loading-box :deep(.app-loading-animation) {
  min-height: 0;
}

.folder-completion-loading-box :deep(.app-loading-animation__copy) {
  display: none;
}

.folder-completion-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 0 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.36));
  padding: 7px 8px;
}

.folder-completion-metric {
  display: inline-flex;
  min-width: 0;
  flex: 1 1 150px;
  align-items: center;
  gap: 9px;
  border: 0;
  border-radius: 11px;
  background: transparent;
  padding: 7px 12px;
  box-shadow: none;
}

.folder-completion-metric + .folder-completion-metric {
  border-left: 1px solid rgba(148, 163, 184, 0.2);
}

.folder-completion-metric-icon {
  display: inline-flex;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
}

.folder-completion-metric-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.folder-completion-metric strong {
  display: block;
  color: #0f172a;
  font-size: 16px;
  font-weight: 900;
  line-height: 1.05;
}

.folder-completion-metric em {
  display: block;
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-completion-metric.is-ready .folder-completion-metric-icon {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.folder-completion-metric.is-missing .folder-completion-metric-icon {
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
}

.folder-completion-metric.is-size .folder-completion-metric-icon {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
}

.folder-completion-metric.is-skipped .folder-completion-metric-icon {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
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
  background: rgba(255, 255, 255, 0.52);
  color: #64748b;
  text-align: center;
}

.folder-completion-empty-state {
  min-height: 132px;
  margin-bottom: 10px;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
}

.folder-completion-empty-state :deep(.block) {
  filter: drop-shadow(0 10px 24px rgba(15, 23, 42, 0.08));
}

.folder-completion-list {
  display: grid;
  gap: 8px;
  max-height: min(460px, calc(100vh - 360px));
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 2px;
}

.folder-completion-item {
  min-width: 0;
}

.folder-completion-row {
  display: grid;
  min-width: 0;
  grid-template-columns: 18px minmax(0, 1fr) minmax(118px, max-content);
  align-items: center;
  gap: 10px;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.64);
  padding: 10px;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}

.folder-completion-row:hover {
  border-color: rgb(125 211 252);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 0 0 1px rgba(125, 211, 252, 0.18);
}

.folder-completion-row.is-selected {
  border-color: rgb(14 165 233);
  background: rgb(240 249 255);
}

.folder-completion-row input {
  width: 16px;
  height: 16px;
  accent-color: #0284c7;
  cursor: pointer;
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

.folder-completion-row-title b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.folder-completion-row-title span,
.folder-completion-row-title em {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  min-width: 0;
  justify-items: end;
  gap: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.folder-completion-files-toggle {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
  border: 0;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.1);
  padding: 4px 8px;
  color: #0369a1;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  transition:
    background 0.18s ease,
    color 0.18s ease;
}

.folder-completion-files-toggle:hover {
  background: rgba(14, 165, 233, 0.16);
}

.folder-completion-files-toggle:active {
  background: rgba(14, 165, 233, 0.22);
}

.folder-completion-files-toggle svg {
  flex: 0 0 auto;
  transition: transform 0.25s ease;
}

.folder-completion-files-toggle svg.is-open {
  transform: rotate(180deg);
}

.folder-completion-files {
  display: grid;
  min-width: 0;
  gap: 6px;
  margin-top: 6px;
  overflow-x: hidden;
  border: 1px solid rgba(125, 211, 252, 0.28);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.46);
  padding: 8px;
}

.folder-completion-files-enter-active,
.folder-completion-files-leave-active {
  max-height: 520px;
  overflow: hidden;
  transition:
    max-height 0.24s ease,
    opacity 0.18s ease,
    margin-top 0.24s ease,
    padding-block 0.24s ease;
}

.folder-completion-files-enter-from,
.folder-completion-files-leave-to {
  max-height: 0;
  margin-top: 0;
  padding-top: 0;
  padding-bottom: 0;
  opacity: 0;
}

.folder-completion-file-row {
  display: grid;
  min-width: 0;
  grid-template-columns: 24px minmax(0, 1fr) minmax(42px, max-content) minmax(54px, max-content);
  align-items: center;
  gap: 8px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.72);
  padding: 7px 9px;
  color: #334155;
  font-size: 12px;
}

.folder-completion-file-icon {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: rgba(100, 116, 139, 0.1);
  color: #64748b;
}

.folder-completion-file-icon.is-audio {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
}

.folder-completion-file-icon.is-image {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.folder-completion-file-icon.is-text,
.folder-completion-file-icon.is-subtitle {
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
}

.folder-completion-file-icon.is-archive {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.folder-completion-file-icon.is-video {
  background: rgba(244, 63, 94, 0.12);
  color: #e11d48;
}

.folder-completion-file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 800;
}

.folder-completion-file-type {
  min-width: 0;
  color: #64748b;
  font-weight: 700;
}

.folder-completion-file-row strong {
  color: #0f172a;
  font-size: 12px;
}

.folder-completion-files-more {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
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
  background: rgba(255, 255, 255, 0.5);
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
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.72);
  padding: 14px 24px 18px;
  background: transparent;
}

.folder-completion-cancel {
  min-height: 36px;
  border: 0;
  border-radius: 999px;
  padding: 0 18px;
  font-size: 13px;
  font-weight: 800;
}

.folder-completion-submit {
  min-height: 38px;
  min-width: 132px;
  border: 0;
  border-radius: 999px;
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  padding: 0 18px;
  color: #fff;
  font-size: 13px;
  font-weight: 800;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.24);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.folder-completion-submit:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3);
}

.folder-completion-submit:active:not(:disabled) {
  transform: scale(0.96);
}

.folder-completion-submit:disabled {
  background: rgba(15, 23, 42, 0.08);
  color: rgba(100, 116, 139, 0.62);
  box-shadow: none;
  cursor: not-allowed;
  opacity: 1;
}

.folder-completion-cancel:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgb(248 250 252);
}

.folder-completion-cancel:active:not(:disabled) {
  transform: scale(0.96);
}

@media (max-width: 640px) {
  .folder-completion-overlay {
    padding: 0;
  }

  .folder-completion-modal,
  .folder-completion-window {
    width: 100vw;
    max-height: 100vh;
    min-height: 100vh;
    border-radius: 0;
  }

  .folder-completion-heading p {
    white-space: normal;
  }

  .folder-completion-body {
    max-height: calc(100vh - 166px);
    padding-inline: 16px;
  }

  .folder-completion-summary {
    gap: 6px;
    padding: 6px;
  }

  .folder-completion-metric {
    flex-basis: calc(50% - 3px);
    gap: 7px;
    padding: 7px 8px;
  }

  .folder-completion-metric-icon {
    width: 26px;
    height: 26px;
  }

  .folder-completion-row {
    grid-template-columns: 18px minmax(0, 1fr);
  }

  .folder-completion-row-stats {
    grid-column: 2;
    justify-items: start;
    grid-template-columns: repeat(2, minmax(0, max-content));
    gap: 5px 10px;
  }

  .folder-completion-files {
    margin-left: 28px;
  }

  .folder-completion-file-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 3px;
  }

  .folder-completion-file-icon {
    display: none;
  }

  .folder-completion-skipped-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .folder-completion-footer {
    flex-direction: column;
    align-items: stretch;
    padding-inline: 16px;
  }

  .folder-completion-footer .footer-actions {
    justify-content: flex-end;
  }
}

.folder-completion-fade-enter-active,
.folder-completion-fade-leave-active {
  transition: opacity 0.18s ease;
}

.folder-completion-fade-enter-from,
.folder-completion-fade-leave-to {
  opacity: 0;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-loading-box),
:global(html.dark .folder-completion-modal .folder-completion-loading-box) {
  background: transparent !important;
  color: rgba(248, 250, 252, 0.92);
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .folder-completion-overlay),
:global(html.dark .folder-completion-overlay) {
  background: rgba(0, 0, 0, 0.52) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-window),
:global(html.dark .folder-completion-modal .folder-completion-window) {
  background:
    linear-gradient(180deg, rgba(18, 20, 27, 0.86), rgba(6, 7, 11, 0.92)),
    rgba(8, 10, 14, 0.9) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: 0 34px 92px rgba(0, 0, 0, 0.36) !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-header),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-body),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-footer),
:global(html.dark .folder-completion-modal .folder-completion-header),
:global(html.dark .folder-completion-modal .folder-completion-body),
:global(html.dark .folder-completion-modal .folder-completion-footer) {
  background: transparent !important;
  color: rgba(244, 244, 245, 0.9) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-header),
:global(html.dark .folder-completion-modal .folder-completion-header) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-footer),
:global(html.dark .folder-completion-modal .folder-completion-footer) {
  background: rgba(4, 6, 10, 0.18) !important;
  border-top-color: rgba(255, 255, 255, 0.08) !important;
  border-bottom: 0 !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .footer-row.folder-completion-footer),
:global(html.dark .folder-completion-modal .footer-row.folder-completion-footer) {
  background: rgba(4, 6, 10, 0.18) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-heading .title),
:global(html.dark .folder-completion-modal .folder-completion-heading .title) {
  color: rgba(250, 250, 252, 0.96);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-heading p),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-footer .summary),
:global(html.dark .folder-completion-modal .folder-completion-heading p),
:global(html.dark .folder-completion-modal .folder-completion-footer .summary) {
  color: rgba(212, 212, 216, 0.72);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-close),
:global(html.dark .folder-completion-modal .folder-completion-close) {
  color: rgba(229, 231, 235, 0.72);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-close:hover:not(:disabled)),
:global(html.dark .folder-completion-modal .folder-completion-close:hover:not(:disabled)) {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(250, 250, 252, 0.94);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-loading),
:global(html.dark .folder-completion-modal .folder-completion-loading) {
  background: rgba(9, 10, 14, 0.58) !important;
  color: rgba(248, 250, 252, 0.92) !important;
  backdrop-filter: blur(3px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(3px) saturate(112%) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-empty),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-empty-state),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-files),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-skipped-row),
:global(html.dark .folder-completion-modal .folder-completion-empty),
:global(html.dark .folder-completion-modal .folder-completion-empty-state),
:global(html.dark .folder-completion-modal .folder-completion-files),
:global(html.dark .folder-completion-modal .folder-completion-skipped-row) {
  border-color: rgba(255, 255, 255, 0.075) !important;
  background: rgba(4, 6, 10, 0.28) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-summary),
:global(html.dark .folder-completion-modal .folder-completion-summary) {
  border-color: rgba(255, 255, 255, 0.075) !important;
  background: linear-gradient(135deg, rgba(8, 11, 18, 0.42), rgba(3, 5, 9, 0.18)) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric),
:global(html.dark .folder-completion-modal .folder-completion-metric) {
  background: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric + .folder-completion-metric),
:global(html.dark .folder-completion-modal .folder-completion-metric + .folder-completion-metric) {
  border-left-color: rgba(255, 255, 255, 0.07) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-empty-state .text-neutral-500),
:global(html.dark .folder-completion-modal .folder-completion-empty-state .text-neutral-500) {
  color: rgba(212, 212, 216, 0.72) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric em),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-sub),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-stats),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-type),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-files-more),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-skipped-toggle),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-skipped-row em),
:global(html.dark .folder-completion-modal .folder-completion-metric em),
:global(html.dark .folder-completion-modal .folder-completion-row-sub),
:global(html.dark .folder-completion-modal .folder-completion-row-stats),
:global(html.dark .folder-completion-modal .folder-completion-file-type),
:global(html.dark .folder-completion-modal .folder-completion-files-more),
:global(html.dark .folder-completion-modal .folder-completion-skipped-toggle),
:global(html.dark .folder-completion-modal .folder-completion-skipped-row em) {
  color: rgba(212, 212, 216, 0.72) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric.is-ready .folder-completion-metric-icon),
:global(html.dark .folder-completion-modal .folder-completion-metric.is-ready .folder-completion-metric-icon) {
  background: rgba(16, 185, 129, 0.16) !important;
  color: #86efac !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric.is-missing .folder-completion-metric-icon),
:global(html.dark .folder-completion-modal .folder-completion-metric.is-missing .folder-completion-metric-icon) {
  background: rgba(129, 140, 248, 0.16) !important;
  color: #c4b5fd !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric.is-size .folder-completion-metric-icon),
:global(html.dark .folder-completion-modal .folder-completion-metric.is-size .folder-completion-metric-icon) {
  background: rgba(14, 165, 233, 0.16) !important;
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric.is-skipped .folder-completion-metric-icon),
:global(html.dark .folder-completion-modal .folder-completion-metric.is-skipped .folder-completion-metric-icon) {
  background: rgba(245, 158, 11, 0.16) !important;
  color: #fcd34d !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-metric strong),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-title),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-stats strong),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-name),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-row strong),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-skipped-row span),
:global(html.dark .folder-completion-modal .folder-completion-metric strong),
:global(html.dark .folder-completion-modal .folder-completion-row-title),
:global(html.dark .folder-completion-modal .folder-completion-row-stats strong),
:global(html.dark .folder-completion-modal .folder-completion-file-name),
:global(html.dark .folder-completion-modal .folder-completion-file-row strong),
:global(html.dark .folder-completion-modal .folder-completion-skipped-row span) {
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-row),
:global(html.dark .folder-completion-modal .folder-completion-row) {
  border-color: rgba(255, 255, 255, 0.075) !important;
  background: rgba(4, 6, 10, 0.24) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025) !important;
}

:global(html.dark .folder-completion-modal .folder-completion-file-row) {
  border-color: rgba(255, 255, 255, 0.075) !important;
  background: rgba(4, 6, 10, 0.24) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row:hover),
:global(html.dark .folder-completion-modal .folder-completion-row:hover) {
  border-color: rgba(125, 211, 252, 0.46) !important;
  background: rgba(7, 12, 20, 0.44) !important;
  box-shadow: 0 0 0 1px rgba(125, 211, 252, 0.14) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row.is-selected),
:global(html.dark .folder-completion-modal .folder-completion-row.is-selected) {
  border-color: rgba(56, 189, 248, 0.58) !important;
  background: rgba(14, 165, 233, 0.13) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row input),
:global(html.dark .folder-completion-modal .folder-completion-row input) {
  accent-color: #38bdf8;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-title span),
:global(html.dark .folder-completion-modal .folder-completion-row-title span) {
  background: rgba(14, 165, 233, 0.16) !important;
  color: #bae6fd !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-title em),
:global(html.dark .folder-completion-modal .folder-completion-row-title em) {
  background: rgba(16, 185, 129, 0.15) !important;
  color: #bbf7d0 !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-files-toggle),
:global(html.dark .folder-completion-modal .folder-completion-files-toggle) {
  background: rgba(14, 165, 233, 0.16) !important;
  color: #bae6fd !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-files-toggle:hover),
:global(html.dark .folder-completion-modal .folder-completion-files-toggle:hover) {
  background: rgba(14, 165, 233, 0.24) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon),
:global(html.dark .folder-completion-modal .folder-completion-file-icon) {
  background: rgba(255, 255, 255, 0.06) !important;
  color: rgba(212, 212, 216, 0.78) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-audio),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-audio) {
  background: rgba(14, 165, 233, 0.16) !important;
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-image),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-image) {
  background: rgba(16, 185, 129, 0.16) !important;
  color: #86efac !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-text),
:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-subtitle),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-text),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-subtitle) {
  background: rgba(129, 140, 248, 0.16) !important;
  color: #c4b5fd !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-archive),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-archive) {
  background: rgba(245, 158, 11, 0.16) !important;
  color: #fcd34d !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-file-icon.is-video),
:global(html.dark .folder-completion-modal .folder-completion-file-icon.is-video) {
  background: rgba(244, 63, 94, 0.16) !important;
  color: #fda4af !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-row-work),
:global(html.dark .folder-completion-modal .folder-completion-row-work) {
  color: rgba(228, 228, 231, 0.84) !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-skipped),
:global(html.dark .folder-completion-modal .folder-completion-skipped) {
  border-top-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-cancel),
:global(html.dark .folder-completion-modal .folder-completion-cancel) {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(4, 6, 10, 0.2);
  color: #f8fafc;
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-cancel:hover:not(:disabled)),
:global(html.dark .folder-completion-modal .folder-completion-cancel:hover:not(:disabled)) {
  border-color: rgba(125, 211, 252, 0.24);
  background: rgba(7, 12, 20, 0.42);
}

:global(html.kikoerumanager-dark .folder-completion-modal .folder-completion-submit:disabled),
:global(html.dark .folder-completion-modal .folder-completion-submit:disabled) {
  background: rgba(4, 6, 10, 0.3) !important;
  color: rgba(244, 244, 245, 0.42) !important;
  box-shadow: none !important;
  opacity: 1 !important;
}

:global(html.kikoerumanager-dark .folder-completion-modal .primary-cta.folder-completion-submit:disabled),
:global(html.dark .folder-completion-modal .primary-cta.folder-completion-submit:disabled) {
  background: rgba(4, 6, 10, 0.3) !important;
  color: rgba(244, 244, 245, 0.42) !important;
  box-shadow: none !important;
}
</style>
