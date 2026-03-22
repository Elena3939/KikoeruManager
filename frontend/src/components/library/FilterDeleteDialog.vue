<template>
  <el-dialog v-model="visible" width="1240px" class="fm-dialog filter-delete-dialog" destroy-on-close>
    <template #header>
      <div class="fm-header">
        <div class="fm-title">
          <span>{{ text.title }}</span>
          <span class="fm-badge">{{ filterDeletePreviewInfo.folderName || scopeLabel || getFileName(currentPath) || text.currentFolder }}</span>
        </div>
        <div class="fm-count">{{ filterDeleteSelectedRoots.length }} / {{ filterDeletePreviewInfo.selectedCount }} {{ text.pendingDeleteSuffix }}</div>
      </div>
    </template>

    <div class="fm-body" v-loading="filterDeleteBusy" :element-loading-text="filterDeleteLoadingText">
      <el-alert type="warning" :closable="false" show-icon class="filter-delete-alert" :title="text.tipReview" />
      <el-alert
        v-if="filterDeletePreviewInfo.truncated"
        type="warning"
        :closable="false"
        show-icon
        class="filter-delete-alert"
        :title="filterDeletePreviewInfo.truncatedReason || text.tipTruncated"
      />
      <el-alert v-if="filterDeletePreviewInfo.warning" type="warning" :closable="false" show-icon class="filter-delete-alert" :title="filterDeletePreviewInfo.warning" />
      <el-alert v-if="filterDeletePreviewInfo.error" type="error" :closable="false" show-icon class="filter-delete-alert" :title="filterDeletePreviewInfo.error" />

      <div class="filter-delete-summary">
        <span class="fd-chip">{{ text.statusLabel }} {{ filterDeletePreviewInfo.status || 'idle' }}</span>
        <span class="fd-chip">{{ text.hitLabel }} {{ filterDeletePreviewInfo.selectedCount }} {{ text.itemSuffix }}</span>
        <span class="fd-chip">{{ filterDeleteScanText }}</span>
        <span v-if="filterDeletePreviewInfo.pendingDirectories" class="fd-chip">{{ text.pendingDirectoryLabel }} {{ filterDeletePreviewInfo.pendingDirectories }}</span>
        <span v-if="filterDeleteBasicTreeOnly" class="fd-chip">{{ text.basicTreeOnly }}</span>
        <template v-else>
          <span class="fd-chip">{{ text.estimatedDelete }} {{ formatFileSize(filterDeleteSelectedSize) }}</span>
          <span class="fd-chip">{{ filterDeletePreviewInfo.selectedSizeExact ? text.sizeExact : text.sizePartial }}</span>
          <span class="fd-chip">{{ text.ruleCount }} {{ filterDeletePreviewInfo.ruleCount }}</span>
        </template>
      </div>

      <div v-if="filterDeletePreviewInfo.progressMessage || filterDeletePreviewInfo.currentPath" class="fd-progress">
        {{ filterDeletePreviewInfo.progressMessage || text.loadingPreview }}
        <span v-if="filterDeletePreviewInfo.discoveredEntries"> | {{ filterDeleteScanText }}</span>
        <span v-if="filterDeletePreviewInfo.currentPath"> | {{ filterDeletePreviewInfo.currentPath }}</span>
        <span v-if="filterDeletePreviewInfo.deleteTotal">
          | {{ text.deleteProgress }} {{ filterDeletePreviewInfo.deleteDone }} / {{ filterDeletePreviewInfo.deleteTotal }} / {{ text.failedLabel }} {{ filterDeletePreviewInfo.deleteFailed || 0 }}
        </span>
      </div>

      <div class="fm-toolbar">
        <div class="fm-toolbar-left">
          <button class="fm-btn fm-btn-danger" :disabled="!canConfirmFilterDelete" @click="confirmFilterDeleteSelection">{{ text.confirmDelete }}</button>
          <button v-if="filterDeleteLoading" class="fm-btn fm-btn-ghost" @click="cancelFilterDeletePreview()">{{ text.cancelPreview }}</button>
          <button v-if="filterDeleteDeleting && isRemote" class="fm-btn fm-btn-ghost" @click="requestCancelFilterDeleteDeletion()">{{ text.stopDelete }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="expandFilterDeleteTree">{{ text.expandAll }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="collapseFilterDeleteTree">{{ text.collapseAll }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="filterDeleteBusy || !filterDeleteSelectedRoots.length" @click="clearFilterDeleteSelection">{{ text.clearSelection }}</button>
        </div>
        <div class="fm-search">
          <input
            v-model="filterDeleteSearch"
            class="fm-search-input"
            :placeholder="filterDeleteBasicTreeOnly ? text.searchBasic : text.searchFull"
            :disabled="filterDeleteBusy"
            @input="onFilterDeleteSearchInput"
          />
        </div>
      </div>

      <div v-if="filterDeleteSelectedRoots.length" class="fd-selection-bar">
        <span class="fd-selection-count">{{ text.selectedLabel }} {{ filterDeleteSelectedRoots.length }} {{ text.pendingDeleteSuffix }}</span>
        <span class="fd-selection-tip">{{ text.selectionTip }}</span>
      </div>

      <div class="fm-head" :class="{ 'fd-head-basic': filterDeleteBasicTreeOnly }">
        <div class="fm-col-check">
          <input type="checkbox" class="fm-check" :checked="filterDeleteAllSelected" :indeterminate.prop="filterDeleteSomeSelected" :disabled="filterDeleteBusy" @click="toggleAllFilterDeleteRows" />
        </div>
        <div class="fm-col-name">{{ text.fileName }}</div>
        <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-size">{{ text.size }}</div>
        <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-time">{{ text.timeAndRule }}</div>
        <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-action">{{ text.state }}</div>
      </div>

      <div ref="filterDeleteScrollRef" class="fm-scroll" @scroll="onFilterDeleteScroll">
        <div v-if="!filterDeleteLoading && filterDeleteFlatTree.length === 0" class="fm-empty">
          {{ filterDeleteSearch ? text.noMatchedItems : text.noFilterHits }}
        </div>
        <div v-else-if="filterDeleteVirtualTopPadding" class="fm-virtual-spacer" :style="{ height: `${filterDeleteVirtualTopPadding}px` }"></div>
        <div
          v-for="row in filterDeleteVisibleRows"
          :key="row.id"
          v-memo="[row.id, filterDeleteSelectedIds.has(row.id), filterDeleteExpandedIds.has(row.id), row.selectable]"
          class="fm-row"
          :class="{
            'fm-row-dir': row.type === 'dir',
            'fm-row-selected': filterDeleteSelectedIds.has(row.id),
            'fm-row-disabled': !row.selectable,
            'fd-row-basic': filterDeleteBasicTreeOnly
          }"
          @click="handleFilterDeleteRowClick(row, $event)"
        >
          <div class="fm-col-check" @click.stop>
            <input
              v-if="row.selectable"
              type="checkbox"
              class="fm-check"
              :checked="filterDeleteSelectedIds.has(row.id)"
              :disabled="filterDeleteBusy"
              @click.stop="toggleFilterDeleteSelect(row, $event)"
            />
          </div>
          <div class="fm-col-name">
            <div class="fm-name-cell" :style="{ paddingLeft: `${row.depth * 18 + 4}px` }">
              <button
                v-if="row.type === 'dir'"
                type="button"
                class="fm-arrow fm-arrow-toggle"
                :class="{ open: filterDeleteExpandedIds.has(row.id) }"
                @click.stop="toggleFilterDeleteExpand(row)"
              >
                &gt;
              </button>
              <span v-else class="fm-arrow-placeholder"></span>
              <span class="fm-file-icon">
                <el-icon><component :is="resolveFilterDeleteTreeIcon(row)" /></el-icon>
              </span>
              <div class="fd-name-block">
                <span class="fm-name-text">{{ row.name }}</span>
                <span class="fd-subtext">{{ row.relative_path }}</span>
              </div>
            </div>
          </div>
          <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-size">{{ formatFileSize(row.size) }}</div>
          <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-time">
            <div class="fd-meta-block">
              <span>{{ formatDate(row.modified_time) }}</span>
              <span class="fd-rules">
                {{ row.selectable ? (row.matched_rules || []).join(' / ') : `${text.coveredByPrefix}${getFileName(row.covered_by)}` }}
              </span>
            </div>
          </div>
          <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-action">
            <span v-if="row.selectable" class="fd-status delete-root">{{ text.waitConfirm }}</span>
            <span v-else class="fd-status delete-covered">{{ text.coveredItem }}</span>
          </div>
        </div>
        <div v-if="filterDeleteVirtualBottomPadding" class="fm-virtual-spacer" :style="{ height: `${filterDeleteVirtualBottomPadding}px` }"></div>
      </div>
    </div>

    <template #footer>
      <el-button v-if="filterDeleteLoading" @click="cancelFilterDeletePreview()">{{ text.cancelPreview }}</el-button>
      <el-button v-if="filterDeleteDeleting && isRemote" @click="requestCancelFilterDeleteDeletion()">{{ text.stopDelete }}</el-button>
      <el-button :disabled="filterDeleteDeleting" @click="visible = false">{{ text.close }}</el-button>
      <el-button type="danger" :disabled="!canConfirmFilterDelete" :loading="filterDeleteDeleting" @click="confirmFilterDeleteSelection">{{ text.confirmDelete }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Folder, FolderOpened, Headset, Picture, Tickets, VideoPlay } from '@element-plus/icons-vue'
import { libraryApi } from '../../api'

const text = {
  title: '\u5220\u9664\u8fc7\u6ee4\u6587\u4ef6\u9884\u5ba1',
  currentFolder: '\u5f53\u524d\u76ee\u5f55',
  pendingDeleteSuffix: '\u9879\u5f85\u5220',
  itemSuffix: '\u9879',
  statusLabel: '\u72b6\u6001',
  hitLabel: '\u547d\u4e2d',
  scannedLabel: '\u5df2\u626b\u63cf',
  discoveredLabel: '\u5df2\u53d1\u73b0',
  pendingDirectoryLabel: '\u5f85\u626b\u76ee\u5f55',
  discoveredSuffix: '\uff08\u5f53\u524d\u5df2\u53d1\u73b0\uff09',
  basicTreeOnly: '\u8fdc\u7a0b\u9884\u5ba1\u4ec5\u663e\u793a\u57fa\u7840\u6811',
  estimatedDelete: '\u9884\u8ba1\u5220\u9664',
  sizeExact: '\u5927\u5c0f\u5df2\u5b8c\u6574\u7edf\u8ba1',
  sizePartial: '\u5927\u5c0f\u4e3a\u5df2\u626b\u63cf\u90e8\u5206\u4f30\u7b97',
  ruleCount: '\u542f\u7528\u89c4\u5219',
  loadingPreview: '\u6b63\u5728\u5904\u7406\u5220\u9664\u9884\u5ba1\u2026',
  deleteProgress: '\u5220\u9664\u8fdb\u5ea6',
  failedLabel: '\u5931\u8d25',
  tipReview: '\u5148\u5ba1\u9605\u547d\u4e2d\u8fc7\u6ee4\u89c4\u5219\u7684\u6587\u4ef6\u548c\u76ee\u5f55\uff0c\u53d6\u6d88\u52fe\u9009\u53ef\u4fdd\u7559\u8bef\u5224\u9879\u3002\u6587\u4ef6\u5939\u9879\u4f1a\u8fde\u540c\u5176\u5185\u90e8\u5185\u5bb9\u4e00\u8d77\u5220\u9664\u3002',
  tipTruncated: '\u8fdc\u7a0b\u76ee\u5f55\u8fc7\u5927\uff0c\u5f53\u524d\u4ec5\u5c55\u793a\u90e8\u5206\u9884\u5ba1\u7ed3\u679c\u3002',
  confirmDelete: '\u786e\u8ba4\u5220\u9664\u9009\u4e2d',
  cancelPreview: '\u53d6\u6d88\u9884\u5ba1',
  stopDelete: '\u505c\u6b62\u5220\u9664',
  expandAll: '\u5c55\u5f00\u5168\u90e8',
  collapseAll: '\u6298\u53e0\u5168\u90e8',
  clearSelection: '\u53d6\u6d88\u9009\u62e9',
  searchBasic: '\u641c\u7d22\u5f85\u5220\u9664\u6587\u4ef6\u540d\u6216\u8def\u5f84\u2026',
  searchFull: '\u641c\u7d22\u5f85\u5220\u9664\u6587\u4ef6\u540d\u3001\u8def\u5f84\u6216\u89c4\u5219\u2026',
  selectedLabel: '\u5df2\u9009',
  selectionTip: 'Ctrl+A / Ctrl(Command)+\u70b9\u51fb / Shift+\u70b9\u51fb\u8303\u56f4\u9009\u62e9',
  fileName: '\u6587\u4ef6\u540d',
  size: '\u5927\u5c0f',
  timeAndRule: '\u4fee\u6539\u65f6\u95f4 / \u89c4\u5219',
  state: '\u72b6\u6001',
  noMatchedItems: '\u65e0\u5339\u914d\u5f85\u5220\u9664\u9879',
  noFilterHits: '\u5f53\u524d\u76ee\u5f55\u672a\u547d\u4e2d\u8fc7\u6ee4\u89c4\u5219',
  coveredByPrefix: '\u968f\u7236\u76ee\u5f55\u5220\u9664\uff1a',
  waitConfirm: '\u5f85\u786e\u8ba4',
  coveredItem: '\u76ee\u5f55\u5185\u9879',
  close: '\u5173\u95ed'
}

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  libraryId: { type: String, default: '' },
  currentPath: { type: String, default: '' },
  targetPaths: { type: Array, default: () => [] },
  scopeLabel: { type: String, default: '' },
  isRemote: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'deleted'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})

let filterDeletePollTimer = null
let filterDeleteScrollRafId = 0
let filterDeleteResizeObserver = null

const filterDeleteLoading = ref(false)
const filterDeleteDeleting = ref(false)
const filterDeleteSearch = ref('')
const filterDeleteItems = ref([])
const filterDeleteScrollRef = ref(null)
const filterDeleteScrollTop = ref(0)
const filterDeleteViewportHeight = ref(420)
const filterDeleteExpandedIds = ref(new Set())
const filterDeleteSelectedIds = ref(new Set())
const filterDeleteLastSelectedId = ref('')
const filterDeletePreviewInfo = ref({
  folderName: '',
  folderPath: '',
  selectedCount: 0,
  selectedSize: 0,
  ruleCount: 0,
  selectedSizeExact: true,
  truncated: false,
  truncatedReason: '',
  sizeDisabled: false,
  status: 'idle',
  scannedEntries: 0,
  discoveredEntries: 0,
  pendingDirectories: 0,
  currentPath: '',
  progressMessage: '',
  warning: '',
  error: '',
  deleteDone: 0,
  deleteTotal: 0,
  deleteFailed: 0
})
const filterDeleteJobId = ref('')
const filterDeleteDeleteCancelRequested = ref(false)

const FILTER_DELETE_ROW_HEIGHT = 36
const FILTER_DELETE_OVERSCAN = 12
const FILTER_DELETE_VIRTUAL_THRESHOLD = 180

const filterDeleteTreeRoot = computed(() => buildExplicitTree(filterDeleteItems.value))
const filterDeleteFilteredRoot = computed(() => {
  const keyword = filterDeleteSearch.value.trim().toLowerCase()
  return keyword ? filterExplicitTree(filterDeleteTreeRoot.value, keyword) : filterDeleteTreeRoot.value
})
const filterDeleteFlatTree = computed(() => flattenTree(filterDeleteFilteredRoot.value, 0, filterDeleteExpandedIds.value))
const filterDeleteUseVirtual = computed(() => filterDeleteFlatTree.value.length > FILTER_DELETE_VIRTUAL_THRESHOLD)
const filterDeleteVirtualRange = computed(() => {
  const total = filterDeleteFlatTree.value.length
  if (!filterDeleteUseVirtual.value) return { start: 0, end: total }
  if (!total) return { start: 0, end: 0 }
  const viewport = Math.max(filterDeleteViewportHeight.value || 420, FILTER_DELETE_ROW_HEIGHT)
  const start = Math.max(0, Math.floor(filterDeleteScrollTop.value / FILTER_DELETE_ROW_HEIGHT) - FILTER_DELETE_OVERSCAN)
  const visibleCount = Math.ceil(viewport / FILTER_DELETE_ROW_HEIGHT) + FILTER_DELETE_OVERSCAN * 2
  return { start, end: Math.min(total, start + visibleCount) }
})
const filterDeleteVisibleRows = computed(() => {
  const { start, end } = filterDeleteVirtualRange.value
  return filterDeleteFlatTree.value.slice(start, end)
})
const filterDeleteVirtualTopPadding = computed(() => filterDeleteUseVirtual.value ? filterDeleteVirtualRange.value.start * FILTER_DELETE_ROW_HEIGHT : 0)
const filterDeleteVirtualBottomPadding = computed(() => filterDeleteUseVirtual.value ? Math.max(0, (filterDeleteFlatTree.value.length - filterDeleteVirtualRange.value.end) * FILTER_DELETE_ROW_HEIGHT) : 0)
const filterDeleteTreeHasDirectories = computed(() => filterDeleteItems.value.some(item => item?.type === 'dir'))
const filterDeleteSelectableRows = computed(() => filterDeleteFlatTree.value.filter(row => row?.selectable))
const filterDeleteAllSelected = computed(() => filterDeleteSelectableRows.value.length > 0 && filterDeleteSelectableRows.value.every(row => filterDeleteSelectedIds.value.has(row.id)))
const filterDeleteSomeSelected = computed(() => !filterDeleteAllSelected.value && filterDeleteSelectableRows.value.some(row => row.id && filterDeleteSelectedIds.value.has(row.id)))
const filterDeleteSelectedRoots = computed(() => filterDeleteItems.value.filter(item => item?.selectable && filterDeleteSelectedIds.value.has(item.id)))
const filterDeleteSelectedSize = computed(() => filterDeleteSelectedRoots.value.reduce((sum, item) => sum + Number(item?.size || 0), 0))
const filterDeleteBasicTreeOnly = computed(() => props.isRemote && filterDeletePreviewInfo.value.sizeDisabled)
const filterDeleteBusy = computed(() => filterDeleteLoading.value || filterDeleteDeleting.value)
const canConfirmFilterDelete = computed(() => filterDeletePreviewInfo.value.status === 'completed' && filterDeleteSelectedRoots.value.length > 0 && !filterDeleteBusy.value)
const filterDeleteScanText = computed(() => {
  const scanned = Number(filterDeletePreviewInfo.value.scannedEntries || 0)
  const discovered = Number(filterDeletePreviewInfo.value.discoveredEntries || 0)
  if (discovered > 0) {
    const suffix = filterDeletePreviewInfo.value.status === 'completed' ? '' : text.discoveredSuffix
    return `${text.scannedLabel} ${scanned} / ${discovered} ${text.itemSuffix}${suffix}`
  }
  return `${text.scannedLabel} ${scanned} ${text.itemSuffix}`
})
const filterDeleteLoadingText = computed(() => filterDeleteDeleting.value ? (filterDeletePreviewInfo.value.progressMessage || '\u6b63\u5728\u5220\u9664\u8fc7\u6ee4\u547d\u4e2d\u9879\u2026') : (filterDeletePreviewInfo.value.progressMessage || text.loadingPreview))
const effectivePreviewTargetPaths = computed(() => {
  const normalized = [...new Set((props.targetPaths || []).map(item => String(item || '').trim()).filter(Boolean))]
  if (normalized.length) return normalized
  return props.currentPath ? [props.currentPath] : []
})

watch(visible, async open => {
  if (open) {
    window.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    setupFilterDeleteScrollObserver()
    await loadFilterDeletePreview()
    return
  }
  window.removeEventListener('keydown', handleDialogKeydown)
  clearFilterDeletePoll()
  teardownFilterDeleteScrollObserver()
  if (filterDeleteLoading.value) await cancelFilterDeletePreview({ silent: true })
  if (filterDeleteDeleting.value) requestCancelFilterDeleteDeletion(true)
})

watch(() => filterDeleteFlatTree.value.length, () => {
  nextTick(() => {
    syncFilterDeleteViewport()
  })
})

function handleDialogKeydown (event) {
  if (!visible.value || filterDeleteBusy.value || isTextInputElement(event.target)) return
  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'a') {
    event.preventDefault()
    filterDeleteSelectedIds.value = new Set(getFilterDeleteSelectableIds())
    filterDeleteLastSelectedId.value = filterDeleteSelectableRows.value.at(-1)?.id || ''
  }
}

function clearFilterDeletePoll () {
  if (filterDeletePollTimer) {
    clearTimeout(filterDeletePollTimer)
    filterDeletePollTimer = null
  }
}

function teardownFilterDeleteScrollObserver () {
  if (filterDeleteScrollRafId) {
    cancelAnimationFrame(filterDeleteScrollRafId)
    filterDeleteScrollRafId = 0
  }
  if (filterDeleteResizeObserver) {
    filterDeleteResizeObserver.disconnect()
    filterDeleteResizeObserver = null
  }
}

function syncFilterDeleteViewport () {
  const element = filterDeleteScrollRef.value
  if (!element) return
  filterDeleteViewportHeight.value = Math.max(Number(element.clientHeight || 0), 180)
}

function setupFilterDeleteScrollObserver () {
  teardownFilterDeleteScrollObserver()
  const element = filterDeleteScrollRef.value
  if (!element || typeof ResizeObserver === 'undefined') {
    syncFilterDeleteViewport()
    return
  }
  filterDeleteResizeObserver = new ResizeObserver(() => {
    syncFilterDeleteViewport()
  })
  filterDeleteResizeObserver.observe(element)
  syncFilterDeleteViewport()
}

function resetFilterDeleteScroll () {
  filterDeleteScrollTop.value = 0
  nextTick(() => {
    const element = filterDeleteScrollRef.value
    if (!element) return
    element.scrollTop = 0
    syncFilterDeleteViewport()
  })
}

function onFilterDeleteScroll (event) {
  const target = event?.target
  if (!target) return
  const nextScrollTop = Number(target.scrollTop || 0)
  const nextViewportHeight = Math.max(Number(target.clientHeight || 0), 180)
  if (filterDeleteScrollRafId) cancelAnimationFrame(filterDeleteScrollRafId)
  filterDeleteScrollRafId = requestAnimationFrame(() => {
    filterDeleteScrollTop.value = nextScrollTop
    filterDeleteViewportHeight.value = nextViewportHeight
    filterDeleteScrollRafId = 0
  })
}

function restoreFilterDeleteSelectionState (items, options = {}) {
  const { preserveSelection = false } = options
  const nextItems = Array.isArray(items) ? items : []
  const selectableIds = new Set(nextItems.filter(item => item?.selectable).map(item => item.id))
  const allItemIds = new Set(nextItems.map(item => item.id))
  filterDeleteExpandedIds.value = preserveSelection ? new Set([...filterDeleteExpandedIds.value].filter(id => allItemIds.has(id))) : new Set()
  if (preserveSelection) {
    const nextSelected = new Set([...filterDeleteSelectedIds.value].filter(id => selectableIds.has(id)))
    filterDeleteSelectedIds.value = nextSelected.size ? nextSelected : new Set(selectableIds)
  } else {
    filterDeleteSelectedIds.value = new Set(selectableIds)
  }
  filterDeleteLastSelectedId.value = [...filterDeleteSelectedIds.value][0] || ''
}

function applyFilterDeletePreviewData (data, options = {}) {
  const { preserveSelection = false } = options
  const nextItems = Array.isArray(data?.items) ? data.items : []
  const prevLastId = filterDeleteItems.value.at(-1)?.id || ''
  const nextLastId = nextItems.at(-1)?.id || ''
  const shouldRefreshItems = !preserveSelection || nextItems.length !== filterDeleteItems.value.length || nextLastId !== prevLastId
  if (shouldRefreshItems) {
    filterDeleteItems.value = nextItems
    restoreFilterDeleteSelectionState(nextItems, { preserveSelection })
  }
  filterDeletePreviewInfo.value = {
    ...filterDeletePreviewInfo.value,
    folderName: data?.folder_name || filterDeletePreviewInfo.value.folderName || getFileName(props.currentPath),
    folderPath: data?.folder_path || filterDeletePreviewInfo.value.folderPath || props.currentPath,
    selectedCount: Number(data?.selected_count || 0),
    selectedSize: Number(data?.selected_size || 0),
    ruleCount: Array.isArray(data?.rules)
      ? data.rules.length
      : Number(data?.rule_count || filterDeletePreviewInfo.value.ruleCount || 0),
    selectedSizeExact: data?.selected_size_exact !== false,
    sizeDisabled: data?.size_disabled === true,
    truncated: !!data?.truncated,
    truncatedReason: data?.truncated_reason || '',
    status: data?.status || filterDeletePreviewInfo.value.status || 'idle',
    scannedEntries: Number(data?.scanned_entries || 0),
    discoveredEntries: Number(data?.discovered_entries || 0),
    pendingDirectories: Number(data?.pending_directories || 0),
    currentPath: data?.current_path || '',
    progressMessage: data?.progress_message || '',
    warning: data?.warning || '',
    error: data?.error || '',
    deleteDone: Number(data?.delete_done || filterDeletePreviewInfo.value.deleteDone || 0),
    deleteTotal: Number(data?.delete_total || filterDeletePreviewInfo.value.deleteTotal || 0),
    deleteFailed: Number(data?.delete_failed || filterDeletePreviewInfo.value.deleteFailed || 0)
  }
}

async function pollFilterDeletePreviewStatus (jobId) {
  if (!jobId || !visible.value) return
  try {
    const data = await libraryApi.getFilterDeletePreviewStatus(jobId)
    if (filterDeleteJobId.value !== jobId) return
    applyFilterDeletePreviewData(data, { preserveSelection: true })
    if (['pending', 'running'].includes(data?.status || 'pending')) {
      filterDeleteLoading.value = true
      clearFilterDeletePoll()
      filterDeletePollTimer = setTimeout(() => {
        pollFilterDeletePreviewStatus(jobId)
      }, 1200)
      return
    }
    filterDeleteLoading.value = false
    clearFilterDeletePoll()
  } catch (error) {
    if (!visible.value || filterDeleteJobId.value !== jobId) return
    filterDeleteLoading.value = false
    clearFilterDeletePoll()
    filterDeletePreviewInfo.value = {
      ...filterDeletePreviewInfo.value,
      status: 'error',
      error: error.response?.data?.detail || error.message || '\u83b7\u53d6\u9884\u5ba1\u8fdb\u5ea6\u5931\u8d25',
      warning: '\u9884\u5ba1\u672a\u5b8c\u6574\u5b8c\u6210\uff0c\u5f53\u524d\u7ed3\u679c\u4e0d\u53ef\u76f4\u63a5\u7528\u4e8e\u5220\u9664'
    }
  }
}

async function cancelFilterDeletePreview (options = {}) {
  const { silent = false } = options
  clearFilterDeletePoll()
  const jobId = filterDeleteJobId.value
  if (!jobId) return
  filterDeleteLoading.value = false
  filterDeleteJobId.value = ''
  try {
    await libraryApi.cancelFilterDeletePreview({ jobId })
    filterDeletePreviewInfo.value = {
      ...filterDeletePreviewInfo.value,
      status: 'canceled',
      progressMessage: '\u5220\u9664\u8fc7\u6ee4\u9884\u5ba1\u5df2\u53d6\u6d88',
      warning: '\u5220\u9664\u8fc7\u6ee4\u9884\u5ba1\u5df2\u53d6\u6d88\uff0c\u8bf7\u91cd\u65b0\u626b\u63cf\u540e\u518d\u6267\u884c\u5220\u9664'
    }
    if (!silent) ElMessage.success('\u5df2\u53d6\u6d88\u5220\u9664\u8fc7\u6ee4\u9884\u5ba1')
  } catch (_) {
    if (!silent) ElMessage.warning('\u53d6\u6d88\u9884\u5ba1\u8bf7\u6c42\u5df2\u53d1\u9001\uff0c\u540e\u53f0\u53ef\u80fd\u8fd8\u5728\u7ed3\u675f\u5f53\u524d\u76ee\u5f55\u626b\u63cf')
  }
}

async function loadFilterDeletePreview () {
  if (!effectivePreviewTargetPaths.value.length || !props.libraryId) return
  clearFilterDeletePoll()
  resetFilterDeleteScroll()
  filterDeleteJobId.value = ''
  filterDeleteDeleteCancelRequested.value = false
  filterDeleteLoading.value = true
  filterDeleteItems.value = []
  filterDeleteSelectedIds.value = new Set()
  filterDeleteExpandedIds.value = new Set()
  filterDeleteSearch.value = ''
  filterDeletePreviewInfo.value = {
    ...filterDeletePreviewInfo.value,
    folderName: props.scopeLabel || getFileName(props.currentPath) || text.currentFolder,
    folderPath: props.currentPath,
    selectedCount: 0,
    selectedSize: 0,
    selectedSizeExact: true,
    truncated: false,
    truncatedReason: '',
    status: 'pending',
    scannedEntries: 0,
    discoveredEntries: 0,
    pendingDirectories: effectivePreviewTargetPaths.value.length,
    currentPath: effectivePreviewTargetPaths.value[0] || props.currentPath,
    progressMessage: effectivePreviewTargetPaths.value.length > 1
      ? `正在创建当前页删除过滤预审任务（1 / ${effectivePreviewTargetPaths.value.length}）…`
      : '\u6b63\u5728\u521b\u5efa\u5220\u9664\u8fc7\u6ee4\u9884\u5ba1\u4efb\u52a1\u2026',
    warning: '',
    error: '',
    deleteDone: 0,
    deleteTotal: 0,
    deleteFailed: 0
  }
  try {
    if (effectivePreviewTargetPaths.value.length === 1) {
      const data = await libraryApi.startFilterDeletePreviewJob(props.libraryId, effectivePreviewTargetPaths.value[0])
      filterDeleteJobId.value = data?.job_id || ''
      applyFilterDeletePreviewData(data)
      if (['pending', 'running'].includes(data?.status || 'pending')) await pollFilterDeletePreviewStatus(filterDeleteJobId.value)
      else filterDeleteLoading.value = false
      return
    }

    const mergedItems = []
    let mergedSelectedCount = 0
    let mergedSelectedSize = 0
    let mergedScannedEntries = 0
    let mergedDiscoveredEntries = 0
    let mergedRuleCount = 0
    let hasPartialSize = false
    let hasBasicTreeOnly = false
    let hasTruncated = false
    const warnings = []

    for (let index = 0; index < effectivePreviewTargetPaths.value.length; index += 1) {
      const targetPath = effectivePreviewTargetPaths.value[index]
      filterDeletePreviewInfo.value = {
        ...filterDeletePreviewInfo.value,
        currentPath: targetPath,
        pendingDirectories: Math.max(0, effectivePreviewTargetPaths.value.length - index),
        progressMessage: `正在预审 ${index + 1} / ${effectivePreviewTargetPaths.value.length}: ${getFileName(targetPath) || targetPath}`
      }
      const data = await libraryApi.startFilterDeletePreviewJob(props.libraryId, targetPath)
      let finalData = data
      if (['pending', 'running'].includes(data?.status || 'pending') && data?.job_id) {
        finalData = await waitForFilterDeletePreviewJob(data.job_id, targetPath, index, effectivePreviewTargetPaths.value.length)
      }
      mergedItems.push(...(Array.isArray(finalData?.items) ? finalData.items : []))
      mergedSelectedCount += Number(finalData?.selected_count || 0)
      mergedSelectedSize += Number(finalData?.selected_size || 0)
      mergedScannedEntries += Number(finalData?.scanned_entries || 0)
      mergedDiscoveredEntries += Number(finalData?.discovered_entries || 0)
      mergedRuleCount = Math.max(mergedRuleCount, Array.isArray(finalData?.rules) ? finalData.rules.length : Number(finalData?.rule_count || 0))
      hasPartialSize = hasPartialSize || finalData?.selected_size_exact === false
      hasBasicTreeOnly = hasBasicTreeOnly || finalData?.size_disabled === true
      hasTruncated = hasTruncated || !!finalData?.truncated
      if (finalData?.warning) warnings.push(finalData.warning)
    }

    applyFilterDeletePreviewData({
      folder_name: props.scopeLabel || text.currentFolder,
      folder_path: props.currentPath,
      items: mergedItems,
      selected_count: mergedSelectedCount,
      selected_size: mergedSelectedSize,
      selected_size_exact: !hasPartialSize,
      size_disabled: hasBasicTreeOnly,
      truncated: hasTruncated,
      rule_count: mergedRuleCount,
      scanned_entries: mergedScannedEntries,
      discovered_entries: mergedDiscoveredEntries,
      pending_directories: 0,
      current_path: '',
      progress_message: `预审完成，共处理 ${effectivePreviewTargetPaths.value.length} 个目录`,
      warning: warnings.filter(Boolean).join('；'),
      status: 'completed'
    })
    filterDeleteLoading.value = false
  } catch (error) {
    visible.value = false
    ElMessage.error('\u52a0\u8f7d\u8fc7\u6ee4\u5220\u9664\u9884\u89c8\u5931\u8d25: ' + (error.response?.data?.detail || error.message))
  }
}

async function waitForFilterDeletePreviewJob (jobId, targetPath, index, total) {
  while (visible.value && jobId) {
    const data = await libraryApi.getFilterDeletePreviewStatus(jobId)
    filterDeleteJobId.value = jobId
    filterDeletePreviewInfo.value = {
      ...filterDeletePreviewInfo.value,
      currentPath: data?.current_path || targetPath,
      progressMessage: data?.progress_message || `正在预审 ${index + 1} / ${total}: ${getFileName(targetPath) || targetPath}`,
      scannedEntries: Number(data?.scanned_entries || 0),
      discoveredEntries: Number(data?.discovered_entries || 0),
      pendingDirectories: Math.max(0, total - index - 1) + Number(data?.pending_directories || 0)
    }
    if (!['pending', 'running'].includes(data?.status || 'pending')) {
      return data
    }
    await new Promise(resolve => {
      filterDeletePollTimer = setTimeout(resolve, 1200)
    })
  }
  throw new Error('删除过滤预审已中断')
}

function requestCancelFilterDeleteDeletion (silent = false) {
  if (!filterDeleteDeleting.value) return
  filterDeleteDeleteCancelRequested.value = true
  filterDeletePreviewInfo.value = {
    ...filterDeletePreviewInfo.value,
    progressMessage: '\u5df2\u8bf7\u6c42\u505c\u6b62\u5220\u9664\uff0c\u6b63\u5728\u7b49\u5f85\u5f53\u524d\u9879\u5b8c\u6210\u2026'
  }
  if (!silent) ElMessage.warning('\u5df2\u8bf7\u6c42\u505c\u6b62\u5220\u9664\uff0c\u5c06\u5728\u5f53\u524d\u9879\u5220\u9664\u5b8c\u6210\u540e\u505c\u6b62')
}

function toggleFilterDeleteExpand (row) {
  const next = new Set(filterDeleteExpandedIds.value)
  next.has(row.id) ? next.delete(row.id) : next.add(row.id)
  filterDeleteExpandedIds.value = next
}

function expandFilterDeleteTree () {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => {
    if (node.type === 'dir') {
      next.add(node.id)
      walk(node.children || [])
    }
  })
  walk(filterDeleteFilteredRoot.value)
  filterDeleteExpandedIds.value = next
  nextTick(syncFilterDeleteViewport)
}

function collapseFilterDeleteTree () {
  filterDeleteExpandedIds.value = new Set()
  resetFilterDeleteScroll()
}

function clearFilterDeleteSelection () {
  if (filterDeleteBusy.value) return
  filterDeleteSelectedIds.value = new Set()
  filterDeleteLastSelectedId.value = ''
}

function getFilterDeleteSelectableIds () {
  return filterDeleteSelectableRows.value.map(row => row.id)
}

function selectFilterDeleteRange (targetId, preserveExisting = true) {
  const rowIds = getFilterDeleteSelectableIds()
  const targetIndex = rowIds.indexOf(targetId)
  if (targetIndex === -1) return
  const anchorId = filterDeleteLastSelectedId.value && rowIds.includes(filterDeleteLastSelectedId.value) ? filterDeleteLastSelectedId.value : rowIds[0]
  const anchorIndex = rowIds.indexOf(anchorId)
  const [start, end] = [anchorIndex, targetIndex].sort((left, right) => left - right)
  const next = preserveExisting ? new Set(filterDeleteSelectedIds.value) : new Set()
  rowIds.slice(start, end + 1).forEach(id => next.add(id))
  filterDeleteSelectedIds.value = next
  filterDeleteLastSelectedId.value = targetId
}

function toggleFilterDeleteSelect (row, event = null) {
  if (filterDeleteBusy.value || !row?.selectable) return
  if (event?.shiftKey) {
    selectFilterDeleteRange(row.id, true)
    return
  }
  const next = new Set(filterDeleteSelectedIds.value)
  next.has(row.id) ? next.delete(row.id) : next.add(row.id)
  filterDeleteSelectedIds.value = next
  filterDeleteLastSelectedId.value = row.id
}

function toggleAllFilterDeleteRows () {
  if (filterDeleteBusy.value) return
  filterDeleteSelectedIds.value = filterDeleteAllSelected.value ? new Set() : new Set(filterDeleteSelectableRows.value.map(row => row.id))
  filterDeleteLastSelectedId.value = filterDeleteSelectableRows.value.at(-1)?.id || ''
}

function handleFilterDeleteRowClick (row, event) {
  if (filterDeleteBusy.value || !row?.id) return
  if (row.selectable) {
    toggleFilterDeleteSelect(row, event)
    return
  }
  if (row.type === 'dir') toggleFilterDeleteExpand(row)
}

function onFilterDeleteSearchInput () {
  resetFilterDeleteScroll()
  if (filterDeleteSearch.value.trim()) expandFilterDeleteTree()
}

function resolveFilterDeleteTreeIcon (row) {
  if (row?.type === 'dir') return filterDeleteExpandedIds.value.has(row.id) ? FolderOpened : Folder
  return fileIcon(row?.name || '')
}

function normalizeFilterDeleteComparePath (path) {
  const normalized = String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')
  return normalized || '/'
}

function isFilterDeletePathRemoved (candidatePath, removedPaths) {
  const normalizedCandidate = normalizeFilterDeleteComparePath(candidatePath)
  return removedPaths.some(basePath => (
    normalizedCandidate === basePath
    || normalizedCandidate.startsWith(`${basePath}/`)
  ))
}

function applyFilterDeletePostDelete (deletedPaths, options = {}) {
  const {
    deletedBytes = 0,
    deletedFolderCount = 0,
    successCount = 0,
    failedCount = 0,
    progressMessage = ''
  } = options
  const normalizedDeletedPaths = [...new Set((deletedPaths || []).map(normalizeFilterDeleteComparePath).filter(Boolean))]
  if (!normalizedDeletedPaths.length) return

  const nextItems = filterDeleteItems.value.filter(item => !isFilterDeletePathRemoved(item.delete_path || item.path, normalizedDeletedPaths))
  const nextItemIds = new Set(nextItems.map(item => item.id))
  filterDeleteItems.value = nextItems
  filterDeleteSelectedIds.value = new Set()
  filterDeleteLastSelectedId.value = ''
  filterDeleteExpandedIds.value = new Set([...filterDeleteExpandedIds.value].filter(id => nextItemIds.has(id)))

  const remainingSelectableItems = nextItems.filter(item => item?.selectable)
  const remainingSelectedSize = remainingSelectableItems.reduce((sum, item) => sum + Number(item?.size || 0), 0)
  filterDeletePreviewInfo.value = {
    ...filterDeletePreviewInfo.value,
    selectedCount: remainingSelectableItems.length,
    selectedSize: remainingSelectedSize,
    deleteDone: successCount,
    deleteTotal: successCount + failedCount,
    deleteFailed: failedCount,
    progressMessage: progressMessage || (
      remainingSelectableItems.length
        ? `\u5220\u9664\u5b8c\u6210\uff0c\u5269\u4f59 ${remainingSelectableItems.length} \u9879\u5f85\u5904\u7406`
        : '\u5220\u9664\u5b8c\u6210\uff0c\u5f53\u524d\u76ee\u5f55\u6ca1\u6709\u5269\u4f59\u547d\u4e2d\u8fc7\u6ee4\u89c4\u5219\u7684\u9879'
    ),
    currentPath: '',
    status: 'completed',
    error: ''
  }

  emit('deleted', { deletedBytes, deletedFolderCount })
}

async function confirmFilterDeleteSelection () {
  if (filterDeletePreviewInfo.value.status !== 'completed') {
    ElMessage.warning('\u5220\u9664\u8fc7\u6ee4\u9884\u5ba1\u5c1a\u672a\u5b8c\u6574\u5b8c\u6210\uff0c\u8bf7\u7b49\u5f85\u626b\u63cf\u7ed3\u675f\u540e\u518d\u5220\u9664')
    return
  }
  if (!filterDeleteSelectedRoots.value.length) {
    ElMessage.warning('\u8bf7\u5148\u52fe\u9009\u8981\u5220\u9664\u7684\u8fc7\u6ee4\u5019\u9009\u9879')
    return
  }
  try {
    await ElMessageBox.confirm(
      filterDeleteBasicTreeOnly.value
        ? `\u786e\u5b9a\u5220\u9664\u5df2\u9009 ${filterDeleteSelectedRoots.value.length} \u9879\u5417\uff1f\n\n\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\uff0c\u8bf7\u786e\u8ba4\u5df2\u7ecf\u5ba1\u9605\u65e0\u8bef\u3002`
        : `\u786e\u5b9a\u5220\u9664\u5df2\u9009 ${filterDeleteSelectedRoots.value.length} \u9879\u5417\uff1f\u9884\u8ba1\u5220\u9664 ${formatFileSize(filterDeleteSelectedSize.value)}\u3002\n\n\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\uff0c\u8bf7\u786e\u8ba4\u5df2\u7ecf\u5ba1\u9605\u65e0\u8bef\u3002`,
      '\u786e\u8ba4\u5220\u9664\u8fc7\u6ee4\u6587\u4ef6',
      { confirmButtonText: '\u786e\u5b9a\u5220\u9664', cancelButtonText: '\u53d6\u6d88', type: 'warning', confirmButtonClass: 'el-button--danger' }
    )
  } catch (_) {
    return
  }

  filterDeleteDeleting.value = true
  filterDeleteDeleteCancelRequested.value = false
  try {
    const paths = filterDeleteSelectedRoots.value.map(item => item.delete_path || item.path)
    if (props.isRemote) {
      const sizeByPath = new Map(filterDeleteSelectedRoots.value.map(item => [item.delete_path || item.path, Number(item.size || 0)]))
      const directoryPaths = new Set(filterDeleteSelectedRoots.value.filter(item => item.type === 'dir').map(item => item.delete_path || item.path))
      let successCount = 0
      let failedCount = 0
      let deletedBytes = 0
      let deletedFolderCount = 0
      const succeededPaths = []
      for (let index = 0; index < paths.length; index += 1) {
        if (filterDeleteDeleteCancelRequested.value) break
        const path = paths[index]
        filterDeletePreviewInfo.value = {
          ...filterDeletePreviewInfo.value,
          deleteDone: successCount,
          deleteTotal: paths.length,
          deleteFailed: failedCount,
          progressMessage: `\u6b63\u5728\u5220\u9664 ${index + 1} / ${paths.length}: ${getFileName(path) || path}`
        }
        try {
          await libraryApi.browserDelete(props.libraryId, path, true)
          successCount += 1
          succeededPaths.push(path)
          deletedBytes += Number(sizeByPath.get(path) || 0)
          if (directoryPaths.has(path)) deletedFolderCount += 1
        } catch (_) {
          failedCount += 1
        }
      }
      filterDeletePreviewInfo.value = {
        ...filterDeletePreviewInfo.value,
        deleteDone: successCount,
        deleteTotal: paths.length,
        deleteFailed: failedCount,
          progressMessage: filterDeleteDeleteCancelRequested.value
          ? `\u5220\u9664\u5df2\u505c\u6b62\uff0c\u5df2\u5b8c\u6210 ${successCount} / ${paths.length}`
          : `\u5220\u9664\u5b8c\u6210\uff0c\u6210\u529f ${successCount} / ${paths.length}`
      }
      if (successCount > 0) {
        applyFilterDeletePostDelete(succeededPaths, {
          deletedBytes,
          deletedFolderCount,
          successCount,
          failedCount,
          progressMessage: filterDeleteDeleteCancelRequested.value
            ? `\u5220\u9664\u5df2\u505c\u6b62\uff0c\u5df2\u5b8c\u6210 ${successCount} / ${paths.length}`
            : `\u5220\u9664\u5b8c\u6210\uff0c\u6210\u529f ${successCount} / ${paths.length}`
        })
      }
      if (filterDeleteDeleteCancelRequested.value) ElMessage.warning(`\u8fc7\u6ee4\u5220\u9664\u5df2\u505c\u6b62\uff1a\u6210\u529f ${successCount} \u9879\uff0c\u5931\u8d25 ${failedCount} \u9879`)
      else if (failedCount > 0) ElMessage.warning(`\u8fc7\u6ee4\u5220\u9664\u5b8c\u6210\uff1a\u6210\u529f ${successCount} \u9879\uff0c\u5931\u8d25 ${failedCount} \u9879`)
      else ElMessage.success(`\u8fc7\u6ee4\u5220\u9664\u5b8c\u6210\uff1a\u6210\u529f ${successCount} \u9879`)
      return
    }

    const preview = await libraryApi.browserBatchDelete(props.libraryId, paths, false)
    const result = await libraryApi.browserBatchDelete(props.libraryId, paths, true)
    const failedPathSet = new Set((result?.failed_paths || []).map(item => item?.path).filter(Boolean))
    const succeededPaths = paths.filter(path => !failedPathSet.has(path))
    if (succeededPaths.length) {
      applyFilterDeletePostDelete(succeededPaths, {
        deletedBytes: Number(preview?.total_size || 0),
        deletedFolderCount: Number(preview?.total_folder_count || 0),
        successCount: Number(result?.success_count || 0),
        failedCount: failedPathSet.size,
        progressMessage: `\u5220\u9664\u5b8c\u6210\uff0c\u6210\u529f ${result?.success_count || 0} / ${paths.length}`
      })
    } else {
      filterDeletePreviewInfo.value = {
        ...filterDeletePreviewInfo.value,
        deleteDone: Number(result?.success_count || 0),
        deleteTotal: paths.length,
        deleteFailed: failedPathSet.size,
        progressMessage: `\u5220\u9664\u5b8c\u6210\uff0c\u6210\u529f ${result?.success_count || 0} / ${paths.length}`
      }
    }
    ElMessage.success(`\u8fc7\u6ee4\u5220\u9664\u5b8c\u6210\uff1a\u6210\u529f ${result.success_count || 0} \u9879`)
  } catch (error) {
    ElMessage.error('\u8fc7\u6ee4\u5220\u9664\u5931\u8d25: ' + (error.response?.data?.detail || error.message))
  } finally {
    filterDeleteDeleting.value = false
    filterDeleteDeleteCancelRequested.value = false
  }
}

function getFileName (path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

function buildExplicitTree (items) {
  const root = []
  const nodeMap = new Map()
  const sorted = [...items].sort((left, right) => {
    const leftDepth = String(left.relative_path || '').split('/').filter(Boolean).length
    const rightDepth = String(right.relative_path || '').split('/').filter(Boolean).length
    if (leftDepth !== rightDepth) return leftDepth - rightDepth
    return String(left.relative_path || '').localeCompare(String(right.relative_path || ''), 'zh-Hans-CN-u-kn-true')
  })
  for (const item of sorted) {
    const node = { ...item, children: [] }
    nodeMap.set(item.id, node)
    const relativePath = String(item.relative_path || '')
    const parentRelativePath = relativePath.includes('/') ? relativePath.slice(0, relativePath.lastIndexOf('/')) : ''
    if (!parentRelativePath) {
      root.push(node)
      continue
    }
    const parentEntry = sorted.find(entry => entry.type === 'dir' && entry.relative_path === parentRelativePath)
    const parentNode = parentEntry ? nodeMap.get(parentEntry.id) : null
    if (parentNode) parentNode.children.push(node)
    else root.push(node)
  }
  return root
}

function filterExplicitTree (nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = [node.name, node.relative_path, ...(node.matched_rules || [])].some(value => String(value || '').toLowerCase().includes(keyword))
    if (matched) {
      result.push(node)
      continue
    }
    const children = filterExplicitTree(node.children || [], keyword)
    if (children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree (nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) result.push(...flattenTree(node.children, depth + 1, openIds))
  }
  return result
}

function fileIcon (name = '') {
  const lower = name.toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture
  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay
  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets
  return Document
}

function formatFileSize (bytes) {
  if (bytes === null || bytes === undefined) return '-'
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function formatDate (value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function isTextInputElement (target) {
  if (!target) return false
  const tagName = String(target.tagName || '').toUpperCase()
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || Boolean(target.isContentEditable)
}

defineExpose({ reload: loadFilterDeletePreview })

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleDialogKeydown)
  clearFilterDeletePoll()
  teardownFilterDeleteScrollObserver()
})
</script>

<style scoped>
.filter-delete-dialog :deep(.el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0, 0, 0, 0.18); }
.filter-delete-dialog :deep(.el-dialog__header) { padding: 0; margin: 0; }
.filter-delete-dialog :deep(.el-dialog__body) { padding: 0; }
.fm-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 12px 20px; border-bottom: 1px solid #e4e7ed; }
.fm-title { display: flex; align-items: center; gap: 10px; min-width: 0; font-size: 13px; font-weight: 600; color: #303133; }
.fm-badge { padding: 2px 8px; border: 1px solid #e4e7ed; border-radius: 10px; background: #f5f7fa; font-size: 12px; color: #909399; }
.fm-count { padding: 2px 10px; border: 1px solid #c6e2ff; border-radius: 12px; background: #f0f7ff; font-size: 12px; color: #606266; }
.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }
.filter-delete-alert, .filter-delete-summary, .fd-selection-bar { margin: 0 16px 12px; }
.filter-delete-alert:first-child { margin-top: 14px; }
.filter-delete-summary { display: flex; gap: 8px; flex-wrap: wrap; }
.fd-chip { display: inline-flex; align-items: center; padding: 7px 11px; border-radius: 999px; border: 1px solid #e6ebf2; background: #f4f6f9; font-size: 12px; font-weight: 600; color: #59697f; }
.fd-progress { margin: 0 16px 12px; font-size: 12px; line-height: 1.5; color: #7c8ba1; }
.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-top: 1px solid #f3f4f6; border-bottom: 1px solid #e4e7ed; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fm-btn { padding: 4px 11px; border: 1px solid #dcdfe6; border-radius: 5px; background: #fff; font-size: 12px; cursor: pointer; }
.fm-btn:disabled { cursor: not-allowed; opacity: 0.6; }
.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn-ghost:hover:not(:disabled) { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.fm-search-input { width: 260px; height: 30px; padding: 0 10px; border: 1px solid #dcdfe6; border-radius: 5px; font-size: 12px; outline: none; }
.fd-selection-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #f2d6d2; border-radius: 12px; background: #fff8f7; }
.fd-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.fd-selection-tip { font-size: 12px; color: #8a97aa; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }
.fm-head { height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }
.fd-head-basic, .fd-row-basic { grid-template-columns: 42px minmax(0, 1fr); }
.fm-scroll { flex: 1; overflow: auto; contain: strict; }
.fm-virtual-spacer { width: 100%; pointer-events: none; }
.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; contain: layout paint style; }
.fm-row-dir { background: #fafbfc; cursor: pointer; }
.fm-row-selected { background: #ecf5ff !important; }
.fm-row-disabled { background: #fbfbfc; color: #a5afbc; }
.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow { width: 14px; display: inline-flex; align-items: center; justify-content: center; color: #909399; white-space: nowrap; transition: transform 0.16s; }
.fm-arrow.open { transform: rotate(90deg); color: #409eff; }
.fm-arrow-toggle { padding: 0; border: 0; background: transparent; cursor: pointer; }
.fm-arrow-placeholder { width: 14px; flex: 0 0 14px; }
.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
.fd-name-block, .fd-meta-block { display: flex; flex-direction: column; min-width: 0; }
.fd-subtext, .fd-rules { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; line-height: 1.45; color: #8b96a8; }
.fd-status { display: inline-flex; align-items: center; justify-content: center; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.fd-status.delete-root { border: 1px solid #ffd9b8; background: #fff2e8; color: #b86a12; }
.fd-status.delete-covered { border: 1px solid #e3e8ef; background: #f4f6f9; color: #79869a; }
@media (max-width: 1280px) {
  .filter-delete-summary, .fd-selection-bar { flex-direction: column; align-items: flex-start; }
  .fm-toolbar { flex-direction: column; align-items: flex-start; gap: 10px; }
  .fm-search { width: 100%; }
  .fm-search-input { width: 100%; }
}
</style>

