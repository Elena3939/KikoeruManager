<template>
  <el-dialog v-model="visible" width="1240px" class="fm-dialog filter-delete-dialog" :show-close="false">
    <template #header>
      <div class="fm-header">
        <div class="fm-title">
          <span>{{ text.title }}</span>
          <span class="fm-badge">{{ scopeLabel || getFileName(currentPath) || filterDeletePreviewInfo.folderName || text.currentFolder }}</span>
        </div>
        <div class="fd-header-actions">
          <button v-if="filterDeleteBusy" type="button" class="fm-btn fm-btn-primary" @click="hideFilterDeleteToBackground">{{ text.hideBackground }}</button>
          <div class="fm-count">{{ filterDeleteSelectedRoots.length }} / {{ filterDeleteSelectableCount }} {{ text.pendingDeleteSuffix }}</div>
          <button type="button" class="fd-close-btn" :aria-label="text.close" @click="closeFilterDeleteDialog">×</button>
        </div>
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
        <span v-if="filterDeletePreviewInfo.currentPath"> | {{ displayFilterDeletePath(filterDeletePreviewInfo.currentPath) }}</span>
        <span v-if="filterDeletePreviewInfo.deleteTotal">
          | {{ text.deleteProgress }} {{ filterDeletePreviewInfo.deleteDone }} / {{ filterDeletePreviewInfo.deleteTotal }} / {{ text.failedLabel }} {{ filterDeletePreviewInfo.deleteFailed || 0 }}
        </span>
      </div>
      <div v-if="showFilterDeleteProgressBar" class="fd-progress-bar">
        <el-progress :percentage="filterDeleteProgressPercent" :status="filterDeleteProgressStatus" :stroke-width="8" :show-text="false" />
      </div>
      <div v-if="filterDeleteBusy" class="fd-background-tip">
        {{ text.backgroundHint }}
      </div>

      <div class="fm-toolbar">
        <div class="fm-toolbar-left">
          <button class="fm-btn fm-btn-danger" :disabled="!canConfirmFilterDelete" @click="confirmFilterDeleteSelection">{{ text.confirmDelete }}</button>
          <button v-if="filterDeleteLoading" class="fm-btn fm-btn-ghost" @click="cancelFilterDeletePreview()">{{ text.cancelPreview }}</button>
          <button v-if="filterDeleteDeleting" class="fm-btn fm-btn-ghost" @click="requestCancelFilterDeleteDeletion()">{{ text.stopDelete }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="expandFilterDeleteTree">{{ text.expandAll }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="collapseFilterDeleteTree">{{ text.collapseAll }}</button>
          <button class="fm-btn fm-btn-ghost" :disabled="filterDeleteBusy || !filterDeleteSelectedRoots.length" @click="clearFilterDeleteSelection">{{ text.clearSelection }}</button>
        </div>
        <div v-if="filterDeleteTypeOptions.length" class="fd-type-filter-bar">
          <span class="fd-type-filter-label">{{ text.fileTypeLabel }}</span>
          <button
            v-for="option in filterDeleteTypeOptions"
            :key="option.key"
            type="button"
            class="fd-type-chip"
            :class="{ active: isFilterDeleteTypeFullySelected(option.key), partial: isFilterDeleteTypePartiallySelected(option.key) }"
            :disabled="filterDeleteBusy"
            @click="toggleFilterDeleteType(option.key)"
          >
            <span v-if="isFilterDeleteTypePartiallySelected(option.key)" class="fd-type-chip-indicator" aria-hidden="true">-</span>
            <span>{{ option.label }}</span>
            <span class="fd-type-chip-count">{{ option.count }}</span>
          </button>
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
        <div class="fm-col-name">
          <button type="button" class="fd-sort-btn" :class="{ active: filterDeleteSortBy === 'name' }" @click="toggleFilterDeleteSort('name')">
            <span>{{ text.fileName }}</span>
            <span class="fd-sort-mark">{{ getFilterDeleteSortMark('name') }}</span>
          </button>
        </div>
        <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-size">
          <button type="button" class="fd-sort-btn fd-sort-btn-end" :class="{ active: filterDeleteSortBy === 'size' }" @click="toggleFilterDeleteSort('size')">
            <span>{{ text.size }}</span>
            <span class="fd-sort-mark">{{ getFilterDeleteSortMark('size') }}</span>
          </button>
        </div>
        <div v-if="!filterDeleteBasicTreeOnly" class="fm-col-time">
          <button type="button" class="fd-sort-btn" :class="{ active: filterDeleteSortBy === 'modified_time' }" @click="toggleFilterDeleteSort('modified_time')">
            <span>{{ text.timeAndRule }}</span>
            <span class="fd-sort-mark">{{ getFilterDeleteSortMark('modified_time') }}</span>
          </button>
        </div>
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
            'fm-row-disabled': !canFilterDeleteSelectRow(row),
            'fd-row-basic': filterDeleteBasicTreeOnly
          }"
          @click="handleFilterDeleteRowClick(row, $event)"
        >
          <div class="fm-col-check" :style="getFilterDeleteCheckCellStyle(row)" @click.stop>
            <input
              v-if="canFilterDeleteSelectRow(row)"
              type="checkbox"
              class="fm-check"
              :checked="isFilterDeleteRowFullySelected(row)"
              :indeterminate.prop="isFilterDeleteRowPartiallySelected(row)"
              :disabled="filterDeleteBusy"
              @click.stop="toggleFilterDeleteSelect(row, $event)"
            />
          </div>
          <div class="fm-col-name">
            <div class="fm-name-cell" :style="getFilterDeleteNameCellStyle(row)">
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
            <span v-if="hasFilterDeleteSelectedAncestor(row)" class="fd-status delete-covered">{{ text.coveredBySelected }}</span>
            <span v-else-if="isFilterDeleteRowFullySelected(row)" class="fd-status delete-root">{{ text.waitConfirm }}</span>
            <span v-else class="fd-status delete-optional">{{ text.individualSelectable }}</span>
          </div>
        </div>
        <div v-if="filterDeleteVirtualBottomPadding" class="fm-virtual-spacer" :style="{ height: `${filterDeleteVirtualBottomPadding}px` }"></div>
      </div>
    </div>

    <template #footer>
      <el-button v-if="filterDeleteLoading" @click="cancelFilterDeletePreview()">{{ text.cancelPreview }}</el-button>
      <el-button v-if="filterDeleteDeleting" @click="requestCancelFilterDeleteDeletion()">{{ text.stopDelete }}</el-button>
      <el-button v-if="filterDeleteBusy" type="primary" plain @click="hideFilterDeleteToBackground">{{ text.hideBackground }}</el-button>
      <el-button v-else @click="closeFilterDeleteDialog">{{ text.close }}</el-button>
      <el-button type="danger" :disabled="!canConfirmFilterDelete" :loading="filterDeleteDeleting" @click="confirmFilterDeleteSelection">{{ text.confirmDelete }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch, watchEffect } from 'vue'
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
  backgroundHint: '\u53ef\u4ee5\u5148\u5173\u95ed\u8fd9\u4e2a\u7a97\u53e3\uff0c\u9884\u5ba1\u6216\u5220\u9664\u4f1a\u5728\u5f53\u524d\u9875\u9762\u540e\u53f0\u7ee7\u7eed\u6267\u884c\u3002',
  confirmDelete: '\u786e\u8ba4\u5220\u9664\u9009\u4e2d',
  cancelPreview: '\u53d6\u6d88\u9884\u5ba1',
  stopDelete: '\u505c\u6b62\u5220\u9664',
  expandAll: '\u5c55\u5f00\u5168\u90e8',
  collapseAll: '\u6298\u53e0\u5168\u90e8',
  clearSelection: '\u53d6\u6d88\u9009\u62e9',
  fileTypeLabel: '\u6587\u4ef6\u7c7b\u578b',
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
  coveredBySelected: '\u968f\u76ee\u5f55\u5220\u9664',
  waitConfirm: '\u5f85\u786e\u8ba4',
  coveredItem: '\u76ee\u5f55\u5185\u9879',
  individualSelectable: '\u53ef\u5355\u72ec\u9009',
  noExtension: '\u65e0\u540e\u7f00',
  hideBackground: '\u9690\u85cf\u5230\u540e\u53f0',
  close: '\u5173\u95ed'
}

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  libraryId: { type: String, default: '' },
  currentPath: { type: String, default: '' },
  targetPaths: { type: Array, default: () => [] },
  rules: { type: Array, default: () => [] },
  scopeLabel: { type: String, default: '' },
  isRemote: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'deleted', 'state-change', 'dismiss-background'])

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
const filterDeleteLoadedSessionKey = ref('')
const filterDeleteStartedAt = ref(0)
const filterDeletePreviewTargetIndex = ref(0)
const filterDeletePreviewTargetTotal = ref(0)

const FILTER_DELETE_ROW_HEIGHT = 36
const FILTER_DELETE_OVERSCAN = 12
const FILTER_DELETE_VIRTUAL_THRESHOLD = 180
const FILTER_DELETE_DEFAULT_SORT_BY = 'name'
const FILTER_DELETE_DEFAULT_SORT_ORDER = 'asc'
const FILTER_DELETE_NO_EXTENSION_KEY = '__NO_EXTENSION__'

const filterDeleteSortBy = ref(FILTER_DELETE_DEFAULT_SORT_BY)
const filterDeleteSortOrder = ref(FILTER_DELETE_DEFAULT_SORT_ORDER)
const filterDeleteTreeRoot = computed(() => buildExplicitTree(filterDeleteItems.value))
const filterDeleteNodeById = computed(() => {
  const map = new Map()
  const walk = nodes => {
    for (const node of nodes || []) {
      map.set(node.id, node)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(filterDeleteTreeRoot.value)
  return map
})
const filterDeleteTypeOptions = computed(() => {
  const counts = new Map()
  for (const item of filterDeleteItems.value || []) {
    if (!item || item.type === 'dir') continue
    const extension = getFilterDeleteFileType(item)
    counts.set(extension, (counts.get(extension) || 0) + 1)
  }
  return [...counts.entries()]
    .sort((left, right) => {
      if (right[1] !== left[1]) return right[1] - left[1]
      return String(left[0]).localeCompare(String(right[0]), 'zh-Hans-CN-u-kn-true')
    })
    .map(([key, count]) => ({
      key,
      label: key === FILTER_DELETE_NO_EXTENSION_KEY ? text.noExtension : key.toUpperCase(),
      count
    }))
})
const filterDeleteTypeRowIds = computed(() => {
  const map = new Map()
  for (const item of filterDeleteItems.value || []) {
    if (!canFilterDeleteSelectRow(item) || item.type === 'dir') continue
    const typeKey = getFilterDeleteFileType(item)
    if (!map.has(typeKey)) map.set(typeKey, [])
    map.get(typeKey).push(item.id)
  }
  return map
})
const filterDeleteFilteredRoot = computed(() => {
  const keyword = filterDeleteSearch.value.trim().toLowerCase()
  return filterExplicitTree(filterDeleteTreeRoot.value, { keyword })
})
const filterDeleteSortedRoot = computed(() => sortFilterDeleteTree(filterDeleteFilteredRoot.value, filterDeleteSortBy.value, filterDeleteSortOrder.value))
const filterDeleteFlatTree = computed(() => flattenTree(filterDeleteSortedRoot.value, 0, filterDeleteExpandedIds.value))
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
const filterDeleteSelectableRows = computed(() => filterDeleteFlatTree.value.filter(row => canFilterDeleteSelectRow(row)))
const filterDeleteBulkSelectableRows = computed(() => buildFilterDeleteBulkRows(filterDeleteSelectableRows.value))
const filterDeleteAllSelected = computed(() => filterDeleteBulkSelectableRows.value.length > 0 && filterDeleteBulkSelectableRows.value.every(row => isFilterDeleteRowFullySelected(row)))
const filterDeleteSomeSelected = computed(() => !filterDeleteAllSelected.value && filterDeleteBulkSelectableRows.value.some(row => isFilterDeleteRowFullySelected(row) || isFilterDeleteRowPartiallySelected(row)))
const filterDeleteSelectableCount = computed(() => filterDeleteBulkSelectableRows.value.length)
const filterDeleteSelectedRows = computed(() => [...filterDeleteSelectedIds.value].map(id => filterDeleteNodeById.value.get(id)).filter(Boolean))
const filterDeleteSelectedRoots = computed(() => collectFilterDeleteSelectedRoots(filterDeleteTreeRoot.value))
const filterDeleteSelectedSize = computed(() => filterDeleteSelectedRoots.value.reduce((sum, item) => sum + Number(item?.size || 0), 0))
const filterDeleteBasicTreeOnly = computed(() => props.isRemote && filterDeletePreviewInfo.value.sizeDisabled)
const filterDeleteBusy = computed(() => filterDeleteLoading.value || filterDeleteDeleting.value)
const canConfirmFilterDelete = computed(() => filterDeletePreviewInfo.value.status === 'completed' && filterDeleteSelectedRoots.value.length > 0 && !filterDeleteBusy.value)
const filterDeleteSessionKey = computed(() => JSON.stringify({
  libraryId: props.libraryId || '',
  currentPath: props.currentPath || '',
  targetPaths: effectivePreviewTargetPaths.value,
  rules: props.rules || [],
  isRemote: !!props.isRemote
}))
const showFilterDeleteProgressBar = computed(() => {
  if (filterDeleteDeleting.value) return Number(filterDeletePreviewInfo.value.deleteTotal || 0) > 0
  return ['pending', 'running', 'completed', 'canceled', 'error'].includes(filterDeletePreviewInfo.value.status || 'idle')
})
const filterDeleteProgressPercent = computed(() => {
  if (filterDeleteDeleting.value) {
    const total = Math.max(0, Number(filterDeletePreviewInfo.value.deleteTotal || 0))
    const done = Math.max(0, Number(filterDeletePreviewInfo.value.deleteDone || 0) + Number(filterDeletePreviewInfo.value.deleteFailed || 0))
    if (!total) return 0
    return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
  }
  const status = String(filterDeletePreviewInfo.value.status || 'idle')
  if (status === 'completed') return 100
  const scanned = Math.max(0, Number(filterDeletePreviewInfo.value.scannedEntries || 0))
  const discovered = Math.max(0, Number(filterDeletePreviewInfo.value.discoveredEntries || 0))
  const pendingDirectories = Math.max(0, Number(filterDeletePreviewInfo.value.pendingDirectories || 0))
  if (status === 'running' || status === 'pending') {
    const estimatedTotal = Math.max(
      discovered,
      scanned + pendingDirectories,
      scanned > 0 ? scanned + 1 : 0,
      1
    )
    const percent = Math.round((scanned / estimatedTotal) * 100)
    return Math.min(95, Math.max(scanned > 0 ? 3 : 1, percent))
  }
  if (discovered > 0) {
    const percent = Math.round((scanned / Math.max(discovered, 1)) * 100)
    return Math.max(0, Math.min(100, percent))
  }
  if (status === 'canceled' || status === 'error') return 100
  return 0
})
const filterDeleteProgressStatus = computed(() => {
  if (filterDeletePreviewInfo.value.status === 'error') return 'exception'
  if (filterDeletePreviewInfo.value.status === 'canceled') return 'warning'
  if (!filterDeleteBusy.value && filterDeletePreviewInfo.value.status === 'completed') return 'success'
  return undefined
})
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
    const hasReviewState = ['completed', 'canceled', 'error'].includes(filterDeletePreviewInfo.value.status || 'idle')
    const shouldResumeExisting = (
      filterDeleteLoadedSessionKey.value === filterDeleteSessionKey.value
      && (filterDeleteBusy.value || hasReviewState)
    )
    if (!shouldResumeExisting) await loadFilterDeletePreview()
    return
  }
  window.removeEventListener('keydown', handleDialogKeydown)
  teardownFilterDeleteScrollObserver()
})

watchEffect(() => {
  emit('state-change', {
    active: filterDeleteBusy.value,
    mode: filterDeleteDeleting.value ? 'delete' : 'preview',
    status: filterDeletePreviewInfo.value.status || 'idle',
    scopeLabel: props.scopeLabel || getFileName(props.currentPath) || filterDeletePreviewInfo.value.folderName || text.currentFolder,
    progressMessage: filterDeletePreviewInfo.value.progressMessage || '',
    currentPath: displayFilterDeletePath(filterDeletePreviewInfo.value.currentPath || props.currentPath || ''),
    percentage: filterDeleteProgressPercent.value,
    progressStatus: filterDeleteProgressStatus.value || '',
    startedAt: Number(filterDeleteStartedAt.value || 0),
    previewTargetIndex: Number(filterDeletePreviewTargetIndex.value || 0),
    previewTargetTotal: Number(filterDeletePreviewTargetTotal.value || 0),
    selectedCount: Number(filterDeletePreviewInfo.value.selectedCount || 0),
    selectedSize: Number(filterDeletePreviewInfo.value.selectedSize || 0),
    scannedEntries: Number(filterDeletePreviewInfo.value.scannedEntries || 0),
    discoveredEntries: Number(filterDeletePreviewInfo.value.discoveredEntries || 0),
    pendingDirectories: Number(filterDeletePreviewInfo.value.pendingDirectories || 0),
    ruleCount: Number(filterDeletePreviewInfo.value.ruleCount || 0),
    reviewable: filterDeletePreviewInfo.value.status === 'completed',
    deleteDone: Number(filterDeletePreviewInfo.value.deleteDone || 0),
    deleteTotal: Number(filterDeletePreviewInfo.value.deleteTotal || 0),
    deleteFailed: Number(filterDeletePreviewInfo.value.deleteFailed || 0),
    canCancelPreview: filterDeleteLoading.value,
    canStopDelete: filterDeleteDeleting.value
  })
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
    filterDeleteSelectedIds.value = new Set(filterDeleteBulkSelectableRows.value.map(row => row.id))
    filterDeleteLastSelectedId.value = filterDeleteBulkSelectableRows.value.at(-1)?.id || ''
  }
}

function hideFilterDeleteToBackground () {
  visible.value = false
}

function closeFilterDeleteDialog () {
  emit('dismiss-background')
  visible.value = false
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
    const nextSelected = new Set([...filterDeleteSelectedIds.value].filter(id => allItemIds.has(id)))
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
    folderName: props.scopeLabel || getFileName(props.currentPath) || data?.folder_name || filterDeletePreviewInfo.value.folderName || text.currentFolder,
    folderPath: props.currentPath || data?.folder_path || filterDeletePreviewInfo.value.folderPath || '',
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
    currentPath: displayFilterDeletePath(data?.current_path || ''),
    progressMessage: data?.progress_message || '',
    warning: data?.warning || '',
    error: data?.error || '',
    deleteDone: Number(data?.delete_done || filterDeletePreviewInfo.value.deleteDone || 0),
    deleteTotal: Number(data?.delete_total || filterDeletePreviewInfo.value.deleteTotal || 0),
    deleteFailed: Number(data?.delete_failed || filterDeletePreviewInfo.value.deleteFailed || 0)
  }
}

async function pollFilterDeletePreviewStatus (jobId) {
  if (!jobId) return
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
    if (filterDeleteJobId.value !== jobId) return
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
  filterDeleteLoadedSessionKey.value = filterDeleteSessionKey.value
  filterDeleteStartedAt.value = Date.now()
  filterDeletePreviewTargetIndex.value = effectivePreviewTargetPaths.value.length ? 1 : 0
  filterDeletePreviewTargetTotal.value = effectivePreviewTargetPaths.value.length
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
    currentPath: props.currentPath || effectivePreviewTargetPaths.value[0] || '',
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
      const data = await libraryApi.startFilterDeletePreviewJob(props.libraryId, effectivePreviewTargetPaths.value[0], {
        rules: props.rules
      })
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
      filterDeletePreviewTargetIndex.value = index + 1
      filterDeletePreviewTargetTotal.value = effectivePreviewTargetPaths.value.length
      filterDeletePreviewInfo.value = {
        ...filterDeletePreviewInfo.value,
        currentPath: displayFilterDeletePath(targetPath),
        pendingDirectories: Math.max(0, effectivePreviewTargetPaths.value.length - index),
        progressMessage: `正在预审 ${index + 1} / ${effectivePreviewTargetPaths.value.length}: ${getFileName(targetPath) || targetPath}`
      }
      const data = await libraryApi.startFilterDeletePreviewJob(props.libraryId, targetPath, {
        rules: props.rules
      })
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
  while (jobId) {
    const data = await libraryApi.getFilterDeletePreviewStatus(jobId)
    filterDeleteJobId.value = jobId
    filterDeletePreviewInfo.value = {
      ...filterDeletePreviewInfo.value,
      currentPath: displayFilterDeletePath(data?.current_path || targetPath),
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

function displayFilterDeletePath (rawPath = '') {
  const current = String(props.currentPath || '').trim()
  const candidate = String(rawPath || '').trim()
  if (!current) return candidate
  if (!candidate) return current

  const normalizedCurrent = current.replace(/\\/g, '/').replace(/\/+$/, '')
  const normalizedCandidate = candidate.replace(/\\/g, '/').replace(/\/+$/, '')
  const targetPaths = effectivePreviewTargetPaths.value
    .map(item => String(item || '').trim().replace(/\\/g, '/').replace(/\/+$/, ''))
    .filter(Boolean)

  if (normalizedCandidate === normalizedCurrent) {
    return current
  }
  if (targetPaths.some(target => normalizedCandidate === target || normalizedCandidate.startsWith(`${target}/`))) {
    return current
  }
  return candidate
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
  rowIds.slice(start, end + 1).forEach(id => {
    const row = filterDeleteNodeById.value.get(id)
    if (!row) return
    getFilterDeleteSelectableSubtreeIds(row).forEach(childId => next.add(childId))
  })
  filterDeleteSelectedIds.value = next
  filterDeleteLastSelectedId.value = targetId
}

function toggleFilterDeleteSelect (row, event = null) {
  if (filterDeleteBusy.value || !canFilterDeleteSelectRow(row)) return
  if (event?.shiftKey) {
    selectFilterDeleteRange(row.id, true)
    return
  }
  const next = new Set(filterDeleteSelectedIds.value)
  const subtreeIds = getFilterDeleteSelectableSubtreeIds(row)
  if (next.has(row.id)) {
    subtreeIds.forEach(id => next.delete(id))
  } else {
    subtreeIds.forEach(id => next.add(id))
  }
  filterDeleteSelectedIds.value = next
  filterDeleteLastSelectedId.value = row.id
}

function toggleAllFilterDeleteRows () {
  if (filterDeleteBusy.value) return
  if (filterDeleteAllSelected.value) {
    filterDeleteSelectedIds.value = new Set()
  } else {
    const next = new Set()
    filterDeleteBulkSelectableRows.value.forEach(row => {
      getFilterDeleteSelectableSubtreeIds(row).forEach(id => next.add(id))
    })
    filterDeleteSelectedIds.value = next
  }
  filterDeleteLastSelectedId.value = filterDeleteBulkSelectableRows.value.at(-1)?.id || ''
}

function handleFilterDeleteRowClick (row, event) {
  if (filterDeleteBusy.value || !row?.id) return
  if (canFilterDeleteSelectRow(row)) {
    toggleFilterDeleteSelect(row, event)
    return
  }
  if (row.type === 'dir') toggleFilterDeleteExpand(row)
}

function onFilterDeleteSearchInput () {
  resetFilterDeleteScroll()
  if (filterDeleteSearch.value.trim()) expandFilterDeleteTree()
}

function getFilterDeleteFileType(row) {
  const sourceName = String(row?.name || row?.relative_path || row?.path || '')
  const extension = sourceName.match(/\.([^.\\/]+)$/)?.[1] || ''
  return extension ? `.${extension.toLowerCase()}` : FILTER_DELETE_NO_EXTENSION_KEY
}

async function toggleFilterDeleteType(typeKey) {
  if (!typeKey || filterDeleteBusy.value) return
  const ids = filterDeleteTypeRowIds.value.get(typeKey) || []
  if (!ids.length) return
  const next = new Set(filterDeleteSelectedIds.value)
  const shouldSelect = !ids.every(id => next.has(id))
  ids.forEach(id => {
    if (shouldSelect) next.add(id)
    else next.delete(id)
  })
  filterDeleteSelectedIds.value = next
  filterDeleteLastSelectedId.value = ids.at(-1) || ''
}

function isFilterDeleteTypeFullySelected(typeKey) {
  const ids = filterDeleteTypeRowIds.value.get(typeKey) || []
  return ids.length > 0 && ids.every(id => filterDeleteSelectedIds.value.has(id))
}

function isFilterDeleteTypePartiallySelected(typeKey) {
  const ids = filterDeleteTypeRowIds.value.get(typeKey) || []
  if (!ids.length) return false
  const selectedCount = ids.filter(id => filterDeleteSelectedIds.value.has(id)).length
  return selectedCount > 0 && selectedCount < ids.length
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

  const nextItems = filterDeleteItems.value.filter(item => !isFilterDeletePathRemoved(resolveFilterDeleteDeleteTarget(item), normalizedDeletedPaths))
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
  filterDeleteLoadedSessionKey.value = filterDeleteSessionKey.value
  filterDeleteDeleteCancelRequested.value = false
  try {
    const paths = filterDeleteSelectedRoots.value.map(item => resolveFilterDeleteDeleteTarget(item))
    const sizeByPath = new Map(filterDeleteSelectedRoots.value.map(item => [resolveFilterDeleteDeleteTarget(item), Number(item.size || 0)]))
    const normalizedItemMeta = filterDeleteItems.value.map(item => ({
      path: normalizeFilterDeleteComparePath(item.path || item.delete_path),
      type: item.type
    }))
    const folderCountByPath = new Map(filterDeleteSelectedRoots.value.map(item => {
      const rawPath = resolveFilterDeleteDeleteTarget(item)
      const normalizedPath = normalizeFilterDeleteComparePath(rawPath)
      if (item.type !== 'dir') return [rawPath, 0]
      const folderCount = normalizedItemMeta.filter(candidate => (
        candidate.type === 'dir'
        && (candidate.path === normalizedPath || candidate.path.startsWith(`${normalizedPath}/`))
      )).length
      return [rawPath, folderCount]
    }))
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
        deletedFolderCount += Number(folderCountByPath.get(path) || 0)
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

function canFilterDeleteSelectRow (row) {
  return Boolean(row?.id && (row?.path || row?.delete_path))
}

function resolveFilterDeleteDeleteTarget (row) {
  if (!row) return ''
  if (row.selectable === false && row.path) return row.path
  return row.delete_path || row.path || ''
}

function getFilterDeleteRowPath (row) {
  return normalizeFilterDeleteComparePath(row?.path || row?.delete_path || '')
}

function isFilterDeleteAncestorPath(candidatePath, parentPath) {
  if (!candidatePath || !parentPath) return false
  return candidatePath === parentPath || candidatePath.startsWith(`${parentPath}/`)
}

function isFilterDeleteRowConflict(left, right) {
  const leftPath = getFilterDeleteRowPath(left)
  const rightPath = getFilterDeleteRowPath(right)
  if (!leftPath || !rightPath) return false
  return isFilterDeleteAncestorPath(leftPath, rightPath) || isFilterDeleteAncestorPath(rightPath, leftPath)
}

function getFilterDeleteRowDepth(row) {
  return getFilterDeleteRowPath(row).split('/').filter(Boolean).length
}

function compareFilterDeleteText(left, right) {
  return String(left || '').localeCompare(String(right || ''), 'zh-Hans-CN-u-kn-true', { sensitivity: 'base', numeric: true })
}

function reduceFilterDeleteRows(rows) {
  const sorted = [...rows].sort((left, right) => {
    const depthDiff = getFilterDeleteRowDepth(left) - getFilterDeleteRowDepth(right)
    if (depthDiff !== 0) return depthDiff
    return compareFilterDeleteText(left?.relative_path || left?.name || '', right?.relative_path || right?.name || '')
  })
  const result = []
  for (const row of sorted) {
    const rowPath = getFilterDeleteRowPath(row)
    if (!rowPath) continue
    if (result.some(existing => isFilterDeleteAncestorPath(rowPath, getFilterDeleteRowPath(existing)))) continue
    result.push(row)
  }
  return result
}

function mergeFilterDeleteSelectionRows(rows, row) {
  const nextRows = rows.filter(candidate => !isFilterDeleteRowConflict(candidate, row))
  nextRows.push(row)
  return reduceFilterDeleteRows(nextRows)
}

function buildFilterDeleteBulkRows(rows) {
  const result = []
  for (const row of rows) {
    if (!result.some(existing => isFilterDeleteAncestorPath(getFilterDeleteRowPath(row), getFilterDeleteRowPath(existing)))) {
      result.push(row)
    }
  }
  return result
}

function hasFilterDeleteSelectedAncestor(row) {
  const rowPath = getFilterDeleteRowPath(row)
  if (!rowPath) return false
  return filterDeleteSelectedRoots.value.some(selectedRow => {
    if (selectedRow.id === row.id) return false
    return isFilterDeleteAncestorPath(rowPath, getFilterDeleteRowPath(selectedRow))
  })
}

function getFilterDeleteTimeValue(value) {
  if (!value) return 0
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 0 : date.getTime()
}

function compareFilterDeleteRows(left, right, sortBy, sortOrder) {
  if (left?.type !== right?.type) return left?.type === 'dir' ? -1 : 1

  let diff = 0
  if (sortBy === 'size') {
    diff = Number(left?.size || 0) - Number(right?.size || 0)
  } else if (sortBy === 'modified_time') {
    diff = getFilterDeleteTimeValue(left?.modified_time) - getFilterDeleteTimeValue(right?.modified_time)
  } else {
    diff = compareFilterDeleteText(left?.name || left?.relative_path || '', right?.name || right?.relative_path || '')
  }

  if (diff === 0) {
    diff = compareFilterDeleteText(left?.name || left?.relative_path || '', right?.name || right?.relative_path || '')
  }
  return sortOrder === 'desc' ? -diff : diff
}

function sortFilterDeleteTree(nodes, sortBy, sortOrder) {
  return [...(nodes || [])]
    .map(node => ({
      ...node,
      children: node.children?.length ? sortFilterDeleteTree(node.children, sortBy, sortOrder) : []
    }))
    .sort((left, right) => compareFilterDeleteRows(left, right, sortBy, sortOrder))
}

function toggleFilterDeleteSort(sortBy) {
  if (!sortBy) return
  if (filterDeleteSortBy.value === sortBy) {
    filterDeleteSortOrder.value = filterDeleteSortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    filterDeleteSortBy.value = sortBy
    filterDeleteSortOrder.value = sortBy === 'name' ? 'asc' : 'desc'
  }
  resetFilterDeleteScroll()
}

function getFilterDeleteSortMark(sortBy) {
  if (filterDeleteSortBy.value !== sortBy) return '↕'
  return filterDeleteSortOrder.value === 'asc' ? '↑' : '↓'
}

function getFilterDeleteSelectableSubtreeIds (row) {
  const ids = []
  const walk = node => {
    if (!node) return
    if (canFilterDeleteSelectRow(node)) ids.push(node.id)
    for (const child of node.children || []) {
      walk(child)
    }
  }
  walk(row)
  return ids
}

function isFilterDeleteRowFullySelected (row) {
  const ids = getFilterDeleteSelectableSubtreeIds(row)
  return ids.length > 0 && ids.every(id => filterDeleteSelectedIds.value.has(id))
}

function isFilterDeleteRowPartiallySelected (row) {
  const ids = getFilterDeleteSelectableSubtreeIds(row)
  if (!ids.length) return false
  const selectedCount = ids.filter(id => filterDeleteSelectedIds.value.has(id)).length
  return selectedCount > 0 && selectedCount < ids.length
}

function collectFilterDeleteSelectedRoots (nodes = []) {
  const roots = []
  const walk = node => {
    if (!node || !canFilterDeleteSelectRow(node)) return
    if (isFilterDeleteRowFullySelected(node)) {
      roots.push(node)
      return
    }
    if (!isFilterDeleteRowPartiallySelected(node)) return
    for (const child of node.children || []) {
      walk(child)
    }
  }
  for (const node of nodes || []) {
    walk(node)
  }
  return roots
}

function getFilterDeleteCheckCellStyle (row) {
  const depth = Math.max(0, Number(row?.depth || 0))
  const indent = Math.min(depth * 18, 72)
  return {
    paddingLeft: `${indent}px`
  }
}

function getFilterDeleteNameCellStyle (row) {
  const depth = Math.max(0, Number(row?.depth || 0))
  const indent = depth * 8 + 2
  return {
    paddingLeft: `${indent}px`
  }
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

function filterExplicitTree (nodes, options = {}) {
  const keyword = String(options?.keyword || '').trim().toLowerCase()
  const result = []
  for (const node of nodes) {
    const children = filterExplicitTree(node.children || [], options)
    const textMatched = !keyword || [node.name, node.relative_path, ...(node.matched_rules || [])].some(value => String(value || '').toLowerCase().includes(keyword))
    if (node.type === 'dir') {
      if (textMatched || children.length) {
        result.push({ ...node, children })
      }
      continue
    }
    if (textMatched) result.push({ ...node, children: [] })
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

defineExpose({
  reload: loadFilterDeletePreview,
  cancelPreviewTask: cancelFilterDeletePreview,
  requestStopDeletion: requestCancelFilterDeleteDeletion
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleDialogKeydown)
  if (filterDeleteLoading.value && filterDeleteJobId.value) {
    libraryApi.cancelFilterDeletePreview({ jobId: filterDeleteJobId.value }).catch(() => {})
  }
  if (filterDeleteDeleting.value) requestCancelFilterDeleteDeletion(true)
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
.fd-header-actions { display: flex; align-items: center; gap: 10px; }
.fd-close-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  font-size: 18px;
  line-height: 1;
  color: #7c8ba1;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.fd-close-btn:hover {
  background: #f4f6f9;
  color: #2f3d4f;
}
.fd-progress-bar { margin: 0 16px 12px; }
.fd-background-tip { margin: 0 16px 12px; padding: 9px 12px; border: 1px dashed #cfe0ff; border-radius: 10px; background: #f5f9ff; font-size: 12px; color: #4c6791; }
.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-top: 1px solid #f3f4f6; border-bottom: 1px solid #e4e7ed; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fd-type-filter-bar { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; padding: 0 12px; flex-wrap: nowrap; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; -ms-overflow-style: none; }
.fd-type-filter-bar::-webkit-scrollbar { display: none; }
.fd-type-filter-label { flex: 0 0 auto; font-size: 12px; font-weight: 600; color: rgba(29, 29, 31, 0.62); letter-spacing: -0.12px; }
.fd-type-chip { display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; padding: 4px 10px; border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 999px; background: #fafafc; color: #1d1d1f; font-size: 11px; font-weight: 600; letter-spacing: -0.12px; line-height: 1; cursor: pointer; transition: border-color .16s ease, background-color .16s ease, color .16s ease, box-shadow .16s ease; }
.fd-type-chip:hover:not(:disabled) { border-color: rgba(0, 113, 227, 0.28); color: #0066cc; }
.fd-type-chip.active { background: #0071e3; border-color: #0071e3; color: #fff; box-shadow: 0 8px 20px rgba(0, 113, 227, 0.18); }
.fd-type-chip.partial { border-color: rgba(0, 113, 227, 0.34); background: #eef5ff; color: #0a5fc2; }
.fd-type-chip:disabled { opacity: 0.56; cursor: not-allowed; }
.fd-type-chip-indicator { display: inline-flex; align-items: center; justify-content: center; width: 10px; color: currentColor; font-size: 11px; font-weight: 900; line-height: 1; }
.fd-type-chip-count { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: rgba(29, 29, 31, 0.08); font-size: 10px; font-weight: 700; line-height: 1; }
.fd-type-chip.active .fd-type-chip-count { background: rgba(255, 255, 255, 0.22); }
.fd-type-chip.partial .fd-type-chip-count { background: rgba(0, 113, 227, 0.12); }
.fm-btn { padding: 4px 11px; border: 1px solid #dcdfe6; border-radius: 5px; background: #fff; font-size: 12px; cursor: pointer; }
.fm-btn:disabled { cursor: not-allowed; opacity: 0.6; }
.fm-btn-primary { color: #2458a6; border-color: #bcd3fb; background: #eef5ff; }
.fm-btn-primary:hover:not(:disabled) { color: #17478f; border-color: #8ab4f8; background: #e0ecff; }
.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn-ghost:hover:not(:disabled) { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.fm-search-input { width: 260px; height: 30px; padding: 0 10px; border: 1px solid #dcdfe6; border-radius: 5px; font-size: 12px; outline: none; }
.fd-selection-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #f2d6d2; border-radius: 12px; background: #fff8f7; }
.fd-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.fd-selection-tip { font-size: 12px; color: #8a97aa; }
.fm-head, .fm-row { display: grid; grid-template-columns: 52px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }
.fm-head { height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }
.fd-sort-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.fd-sort-btn-end { margin-left: auto; }
.fd-sort-btn.active { color: #1f5fa9; }
.fd-sort-mark { font-size: 11px; color: #95a1b3; }
.fd-sort-btn.active .fd-sort-mark { color: #1f5fa9; }
.fd-head-basic, .fd-row-basic { grid-template-columns: 52px minmax(0, 1fr); }
.fm-scroll { flex: 1; overflow: auto; contain: strict; }
.fm-virtual-spacer { width: 100%; pointer-events: none; }
.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; contain: layout paint style; }
.fm-row-dir { background: #fafbfc; cursor: pointer; }
.fm-row-selected { background: #ecf5ff !important; }
.fm-row-disabled { background: #fbfbfc; color: #a5afbc; }
.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }
.fm-name-cell { display: flex; align-items: center; gap: 4px; min-width: 0; }
.fm-col-check { display: flex; align-items: center; justify-content: center; min-width: 0; transition: padding-left 0.16s ease; }
.fm-arrow { width: 14px; display: inline-flex; align-items: center; justify-content: center; color: #909399; white-space: nowrap; transition: transform 0.16s; }
.fm-arrow.open { transform: rotate(90deg); color: #409eff; }
.fm-arrow-toggle { padding: 0; border: 0; background: transparent; cursor: pointer; }
.fm-arrow-placeholder { width: 14px; flex: 0 0 14px; }
.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
.fd-name-block, .fd-meta-block { display: flex; flex-direction: column; min-width: 0; }
.fd-subtext, .fd-rules { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; line-height: 1.45; color: #8b96a8; }
.fd-status { display: inline-flex; align-items: center; justify-content: center; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; line-height: 1.2; }
.fd-status.delete-root { border: 1px solid #ffd9b8; background: #fff2e8; color: #b86a12; }
.fd-status.delete-covered { padding: 0; border: 0; background: transparent; color: #8d99ab; font-weight: 500; }
.fd-status.delete-optional { border: 1px solid #d7e5fb; background: #f7fbff; color: #5b789f; }
@media (max-width: 1280px) {
  .filter-delete-summary, .fd-selection-bar { flex-direction: column; align-items: flex-start; }
  .fm-toolbar { flex-direction: column; align-items: flex-start; gap: 10px; }
  .fm-search { width: 100%; }
  .fm-search-input { width: 100%; }
}
</style>

