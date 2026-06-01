<template>
  <el-dialog
    v-model="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal folder-dialog filter-delete-dialog"
    align-center
    modal-class="custom-preview-overlay"
  >
    <div
      class="window panel-enter glass-shell relative flex w-full max-w-[1536px] aspect-[16/10] flex-col overflow-hidden rounded-3xl"
    >
      <div class="window-header flex items-center justify-between px-6 py-4">
        <div class="fm-header-main min-w-0">
          <div class="fm-title-row">
            <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">
              {{ text.title }}
            </h1>
            <span class="fm-badge">{{ scopeLabel || getFileName(currentPath) || filterDeletePreviewInfo.folderName || text.currentFolder }}</span>
          </div>
          <p class="mt-1 truncate text-sm text-slate-500">
            {{ filterDeleteSelectedRoots.length }} / {{ filterDeleteSelectableCount }} {{ text.pendingDeleteSuffix }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <button v-if="filterDeleteBusy" type="button" class="action-card action-card-primary" @click="hideFilterDeleteToBackground">
            {{ text.hideBackground }}
          </button>
          <button
            type="button"
            class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
            @click="closeFilterDeleteDialog"
          >
            <X :size="20" :stroke-width="2" />
          </button>
        </div>
      </div>

      <!-- 加载遮罩仅覆盖 body 区，避免遮住「隐藏到后台」和「关闭」按钮 -->
      <div
        class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5"
        v-app-loading="{ loading: filterDeleteBusy, text: '正在生成删除预审...', size: 120 }"
      >
        <div class="space-y-2 mb-3">
          <el-alert type="warning" :closable="false" show-icon class="filter-delete-alert !rounded-xl !border !border-amber-200/60 !bg-amber-50/50" :title="text.tipReview" />
          <el-alert
            v-if="filterDeletePreviewInfo.truncated"
            type="warning"
            :closable="false"
            show-icon
            class="filter-delete-alert !rounded-xl !border !border-amber-200/60 !bg-amber-50/50"
            :title="filterDeletePreviewInfo.truncatedReason || text.tipTruncated"
          />
          <el-alert v-if="filterDeletePreviewInfo.warning" type="warning" :closable="false" show-icon class="filter-delete-alert !rounded-xl !border !border-amber-200/60 !bg-amber-50/50" :title="filterDeletePreviewInfo.warning" />
          <el-alert v-if="filterDeletePreviewInfo.error" type="error" :closable="false" show-icon class="filter-delete-alert !rounded-xl !border !border-red-200/60 !bg-red-50/50" :title="filterDeletePreviewInfo.error" />
        </div>

        <div class="filter-delete-summary flex flex-wrap gap-2 mb-3">
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

        <div v-if="filterDeletePreviewInfo.progressMessage || filterDeletePreviewInfo.currentPath" class="fd-progress text-[12px] text-slate-500 mb-2">
          {{ filterDeletePreviewInfo.progressMessage || text.loadingPreview }}
          <span v-if="filterDeletePreviewInfo.discoveredEntries"> | {{ filterDeleteScanText }}</span>
          <span v-if="filterDeletePreviewInfo.currentPath"> | {{ displayFilterDeletePath(filterDeletePreviewInfo.currentPath) }}</span>
          <span v-if="filterDeletePreviewInfo.deleteTotal">
            | {{ text.deleteProgress }} {{ filterDeletePreviewInfo.deleteDone }} / {{ filterDeletePreviewInfo.deleteTotal }} / {{ text.failedLabel }} {{ filterDeletePreviewInfo.deleteFailed || 0 }}
          </span>
        </div>
        <div v-if="showFilterDeleteProgressBar" class="fd-progress-bar mb-3">
          <el-progress :percentage="filterDeleteProgressPercent" :status="filterDeleteProgressStatus" :stroke-width="8" :show-text="false" />
        </div>
        <div v-if="filterDeleteBusy" class="fd-background-tip text-[12px] text-slate-400 italic mb-3">
          {{ text.backgroundHint }}
        </div>

        <div class="toolbar-row flex items-center justify-between gap-3 border-b border-slate-200/70 py-3">
          <div class="toolbar-actions flex flex-wrap items-center gap-2">
            <button v-if="filterDeleteLoading" class="action-card group" @click="cancelFilterDeletePreview()">
              <XCircle :size="15" class="action-icon" />
              <span>{{ text.cancelPreview }}</span>
            </button>
            <button v-if="filterDeleteDeleting" class="action-card action-card-danger group" @click="requestCancelFilterDeleteDeletion()">
              <StopCircle :size="15" class="action-icon" />
              <span>{{ text.stopDelete }}</span>
            </button>
            <button v-if="!filterDeleteBusy && filterDeleteFailedTargets.length" class="action-card action-card-warning group" @click="retryFailedFilterDeleteTargets">
              <RotateCcw :size="15" class="action-icon" />
              <span>{{ text.retryFailedTargets }}</span>
            </button>
            <button class="action-card group" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="expandFilterDeleteTree">
              <ChevronsDown :size="15" class="action-icon" />
              <span>{{ text.expandAll }}</span>
            </button>
            <button class="action-card group" :disabled="!filterDeleteTreeHasDirectories || filterDeleteBusy" @click="collapseFilterDeleteTree">
              <ChevronsUp :size="15" class="action-icon" />
              <span>{{ text.collapseAll }}</span>
            </button>
            <button class="action-card group" :disabled="filterDeleteBusy || !filterDeleteSelectedRoots.length" @click="clearFilterDeleteSelection">
              <XSquare :size="15" class="action-icon" />
              <span>{{ text.clearSelection }}</span>
            </button>
            
            <div class="h-4 w-px bg-slate-200 mx-1"></div>
            
            <div v-if="filterDeleteTypeOptions.length" class="fd-type-filter-bar flex items-center gap-1.5">
              <span class="text-[12px] font-medium text-slate-500 mr-1">{{ text.fileTypeLabel }}</span>
              <button
                v-for="option in filterDeleteTypeOptions"
                :key="option.key"
                type="button"
                class="fd-type-tag inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-medium transition-all border group"
                :class="isFilterDeleteTypeFullySelected(option.key) ? 'fd-type-tag-active' : (isFilterDeleteTypePartiallySelected(option.key) ? 'fd-type-tag-partial' : 'fd-type-tag-inactive')"
                :disabled="filterDeleteBusy"
                @click="toggleFilterDeleteType(option.key)"
              >
                <span v-if="isFilterDeleteTypePartiallySelected(option.key)" class="font-bold">-</span>
                <span>{{ option.label }}</span>
                <span class="fd-type-count">{{ option.count }}</span>
              </button>
            </div>
          </div>

          <div class="toolbar-search-group flex min-w-0 items-center gap-2 shrink-0">
            <label class="search-shell flex w-[280px] min-w-0 items-center gap-2 rounded-xl border px-3 py-2">
              <Search :size="16" class="text-slate-400" />
              <input
                v-model="filterDeleteSearch"
                class="search-input"
                :placeholder="filterDeleteBasicTreeOnly ? text.searchBasic : text.searchFull"
                :disabled="filterDeleteBusy"
                @input="onFilterDeleteSearchInput"
              />
            </label>
          </div>
        </div>

        <div v-if="filterDeleteSelectedRoots.length" class="selection-card selection-inline mt-3 flex items-center gap-5 text-sm text-slate-600">
          <span>{{ text.selectedLabel }} <span class="text-slate-900 font-semibold">{{ filterDeleteSelectedRoots.length }}</span> {{ text.pendingDeleteSuffix }}</span>
          <span class="text-xs text-slate-400">{{ text.selectionTip }}</span>
        </div>

        <section class="glass-panel glass-card tree-panel mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
          <div class="tree-head fd-tree-grid items-center gap-3 border-b border-slate-200/70 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400" :style="{ paddingRight: `calc(16px + ${filterDeleteScrollbarWidth}px)` }">
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-all"
                :class="filterDeleteAllSelected ? 'tree-checkbox-on' : (filterDeleteSomeSelected ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                :disabled="filterDeleteBusy"
                @click="toggleAllFilterDeleteRows"
              >
                <Check v-if="filterDeleteAllSelected" :size="13" />
                <span v-else-if="filterDeleteSomeSelected" class="checkbox-minus" />
              </button>
              <button type="button" class="flex items-center gap-1 hover:text-slate-700 transition-colors cursor-pointer" @click="toggleFilterDeleteSort('name')">
                <span>{{ text.fileName }}</span>
                <span class="text-[10px]">{{ getFilterDeleteSortMark('name') }}</span>
              </button>
            </div>
            
            <button v-if="!filterDeleteBasicTreeOnly" type="button" class="tree-col-size tree-sort-button hover:text-slate-700 transition-colors cursor-pointer" @click="toggleFilterDeleteSort('size')">
              <span>{{ text.size }}</span>
              <span class="tree-sort-mark">{{ getFilterDeleteSortMark('size') }}</span>
            </button>
            
            <button v-if="!filterDeleteBasicTreeOnly" type="button" class="tree-col-time tree-col-time-button hover:text-slate-700 transition-colors cursor-pointer" @click="toggleFilterDeleteSort('modified_time')">
              <span class="tree-col-time-label">{{ text.timeAndRule }}</span>
              <span class="tree-col-time-sort">{{ getFilterDeleteSortMark('modified_time') }}</span>
            </button>
          </div>

          <div
            ref="filterDeleteScrollRef"
            v-memo="[filterDeleteFlatTree, filterDeleteSelectedIds, filterDeleteExpandedIds, filterDeleteBasicTreeOnly, filterDeleteBusy]"
            class="tree-scroll flex-1 overflow-auto px-4 py-2 no-scrollbar"
            @scroll="onFilterDeleteScroll"
          >
            <div v-if="!filterDeleteLoading && filterDeleteFlatTree.length === 0" class="preview-empty">
              {{ filterDeleteSearch ? text.noMatchedItems : text.noFilterHits }}
            </div>
            <template v-else>
              <div v-if="filterDeleteVirtualTopPadding" class="fm-virtual-spacer" :style="{ height: `${filterDeleteVirtualTopPadding}px` }"></div>

              <div class="tree-list space-y-0.5">
              <div
                v-for="row in filterDeleteVisibleRows"
                :key="row.id"
                v-memo="[row.id, filterDeleteSelectedIds.has(row.id), filterDeleteExpandedIds.has(row.id), row.selectable]"
                class="tree-node"
              >
                <div
                  class="tree-row fd-tree-grid items-center gap-3 rounded-md px-4 py-1"
                  :class="{
                    'tree-row-selected': filterDeleteSelectedIds.has(row.id),
                    'opacity-50': !canFilterDeleteSelectRow(row)
                  }"
                  @click="handleFilterDeleteRowClick(row, $event)"
                >
                  <div class="tree-main flex min-w-0 items-center gap-2" :style="{ paddingLeft: `${row.depth * 16}px` }">
                    <button
                      v-if="row.type === 'dir'"
                      type="button"
                      class="tree-expander rounded p-0.5 transition-colors cursor-pointer"
                      @click.stop="toggleFilterDeleteExpand(row)"
                    >
                      <ChevronDown v-if="filterDeleteExpandedIds.has(row.id)" :size="17" class="text-slate-400" />
                      <ChevronRight v-else :size="17" class="text-slate-400" />
                    </button>
                    <span v-else class="expander-spacer" />

                    <button
                      v-if="canFilterDeleteSelectRow(row)"
                      type="button"
                      class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-all cursor-pointer"
                      :class="isFilterDeleteRowFullySelected(row) ? 'tree-checkbox-on' : (isFilterDeleteRowPartiallySelected(row) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                      :disabled="filterDeleteBusy"
                      @click.stop="toggleFilterDeleteSelect(row, $event)"
                    >
                      <Check v-if="isFilterDeleteRowFullySelected(row)" :size="13" />
                      <span v-else-if="isFilterDeleteRowPartiallySelected(row)" class="checkbox-minus" />
                    </button>
                    <span v-else class="tree-checkbox-placeholder" />

                    <component :is="resolveFilterDeleteTreeIcon(row)" :size="17" class="tree-icon" :style="resolveFilterDeleteTreeIconStyle(row)" />

                    <div class="min-w-0 flex-1">
                      <div class="tree-name truncate text-[13px] font-medium text-slate-800">{{ row.name }}</div>
                      <div class="tree-sub truncate text-[11px] text-slate-400">{{ row.relative_path }}</div>
                    </div>
                  </div>

                  <span v-if="!filterDeleteBasicTreeOnly" class="tree-size text-[12px] tabular-nums text-slate-400 text-right">{{ formatFileSize(row.size) }}</span>
                  
                  <div v-if="!filterDeleteBasicTreeOnly" class="tree-time min-w-0" :title="row.selectable ? `${formatDate(row.modified_time)} / ${(row.matched_rules || []).join(' / ') || text.individualSelectable}` : `${formatDate(row.modified_time)} / ${text.coveredByPrefix}${getFileName(row.covered_by)}`">
                    <span class="tree-time-date">{{ formatDate(row.modified_time) }}</span>
                    <span class="tree-time-rule">{{ row.selectable ? ((row.matched_rules || []).join(' / ') || text.individualSelectable) : `${text.coveredByPrefix}${getFileName(row.covered_by)}` }}</span>
                  </div>
                </div>
              </div>
              </div>

              <div v-if="filterDeleteVirtualBottomPadding" class="fm-virtual-spacer" :style="{ height: `${filterDeleteVirtualBottomPadding}px` }"></div>
            </template>
          </div>
        </section>
      </div>
      
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/70 bg-slate-50/50">
        <button v-if="filterDeleteLoading" type="button" class="px-4 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 transition-all cursor-pointer shadow-sm active:scale-[0.98]" @click="cancelFilterDeletePreview()">
          {{ text.cancelPreview }}
        </button>
        <button v-if="filterDeleteDeleting" type="button" class="px-4 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 transition-all cursor-pointer shadow-sm active:scale-[0.98]" @click="requestCancelFilterDeleteDeletion()">
          {{ text.stopDelete }}
        </button>
        <button v-if="filterDeleteBusy" type="button" class="px-4 py-2 rounded-xl text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-all cursor-pointer shadow-md shadow-indigo-200 active:scale-[0.98]" @click="hideFilterDeleteToBackground">
          {{ text.hideBackground }}
        </button>
        <button v-else type="button" class="px-4 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 transition-all cursor-pointer shadow-sm active:scale-[0.98]" @click="closeFilterDeleteDialog">
          {{ text.close }}
        </button>
        <button 
          type="button" 
          class="px-4 py-2 rounded-xl text-sm font-medium text-white bg-rose-600 hover:bg-rose-700 transition-all cursor-pointer shadow-md shadow-rose-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none active:scale-[0.98]" 
          :disabled="!canConfirmFilterDelete || filterDeleteDeleting" 
          @click="confirmFilterDeleteSelection"
        >
          <span v-if="filterDeleteDeleting" class="flex items-center gap-2">
            <RefreshCw :size="14" class="animate-spin" />
            删除中...
          </span>
          <span v-else>{{ text.confirmDelete }}</span>
        </button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch, watchEffect } from 'vue'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../../composables/useSystemPrompt'
import { 
  Check, 
  ChevronDown, 
  ChevronRight, 
  Folder, 
  FolderOpen, 
  RefreshCw, 
  Search, 
  Trash2, 
  X,
  XCircle,
  StopCircle,
  RotateCcw,
  ChevronsDown,
  ChevronsUp,
  XSquare
} from 'lucide-vue-next'
import { activityLogApi, libraryApi } from '../../api'
import { libraryEntryIconFor, libraryEntryMetaFor } from './_libraryFileKind'

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
  retryFailedTargets: '\u91cd\u8bd5\u5931\u8d25\u9879',
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
  isRemote: { type: Boolean, default: false },
  initialJobId: { type: String, default: '' }
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
const filterDeleteScrollbarWidth = ref(0)
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
const filterDeleteFailedTargets = ref([])
const filterDeleteLoadedSessionKey = ref('')
const filterDeleteStartedAt = ref(0)
const filterDeletePreviewTargetIndex = ref(0)
const filterDeletePreviewTargetTotal = ref(0)
const filterDeletePreviewLoggedSessionKey = ref('')
const filterDeleteApplyLoggedExecutionKey = ref('')

const FILTER_DELETE_ROW_HEIGHT = 44
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
      label: key === FILTER_DELETE_NO_EXTENSION_KEY ? text.noExtension : key.replace(/^\./, '').toUpperCase(),
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
    if (!shouldResumeExisting) {
      const resumeId = String(props.initialJobId || '').trim()
      if (resumeId) {
        // 恢复已有后台 job，直接接管轮询，不重新发起
        filterDeleteJobId.value = resumeId
        filterDeleteLoadedSessionKey.value = filterDeleteSessionKey.value
        filterDeleteStartedAt.value = Date.now()
        filterDeleteLoading.value = true
        filterDeletePreviewInfo.value = { ...filterDeletePreviewInfo.value, status: 'running' }
        await pollFilterDeletePreviewStatus(resumeId)
      } else {
        await loadFilterDeletePreview()
      }
    }
    return
  }
  window.removeEventListener('keydown', handleDialogKeydown)
  teardownFilterDeleteScrollObserver()
})

watchEffect(() => {
  emit('state-change', {
    active: filterDeleteBusy.value,
    jobId: filterDeleteJobId.value || '',
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

async function resetFilterDeleteDialogState () {
  clearFilterDeletePoll()
  filterDeleteLoading.value = false
  filterDeleteDeleting.value = false
  filterDeleteJobId.value = ''
  filterDeleteDeleteCancelRequested.value = false
  filterDeleteLoadedSessionKey.value = ''
  filterDeleteStartedAt.value = 0
  filterDeletePreviewTargetIndex.value = 0
  filterDeletePreviewTargetTotal.value = 0
  filterDeletePreviewLoggedSessionKey.value = ''
  filterDeleteApplyLoggedExecutionKey.value = ''
  filterDeleteFailedTargets.value = []
  filterDeleteSearch.value = ''
  filterDeleteItems.value = []
  filterDeleteExpandedIds.value = new Set()
  filterDeleteSelectedIds.value = new Set()
  filterDeleteLastSelectedId.value = ''
  filterDeleteScrollTop.value = 0
  filterDeletePreviewInfo.value = {
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
  }
}

async function closeFilterDeleteDialog () {
  if (filterDeleteBusy.value) {
    hideFilterDeleteToBackground()
    return
  }
  emit('dismiss-background')
  await resetFilterDeleteDialogState()
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
  if (!element) {
    filterDeleteViewportHeight.value = 180
    filterDeleteScrollbarWidth.value = 0
    return
  }
  filterDeleteViewportHeight.value = Math.max(Number(element.clientHeight || 0), 180)
  filterDeleteScrollbarWidth.value = Math.max(0, Number(element.offsetWidth || 0) - Number(element.clientWidth || 0))
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
  const nextScrollbarWidth = Math.max(0, Number(target.offsetWidth || 0) - Number(target.clientWidth || 0))
  if (filterDeleteScrollRafId) cancelAnimationFrame(filterDeleteScrollRafId)
  filterDeleteScrollRafId = requestAnimationFrame(() => {
    filterDeleteScrollTop.value = nextScrollTop
    filterDeleteViewportHeight.value = nextViewportHeight
    filterDeleteScrollbarWidth.value = nextScrollbarWidth
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
    await writeFilterDeletePreviewActivityLog('error')
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
    await writeFilterDeletePreviewActivityLog('canceled')
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
  filterDeletePreviewLoggedSessionKey.value = ''
  filterDeletePreviewTargetIndex.value = effectivePreviewTargetPaths.value.length ? 1 : 0
  filterDeletePreviewTargetTotal.value = effectivePreviewTargetPaths.value.length
  resetFilterDeleteScroll()
  filterDeleteJobId.value = ''
  filterDeleteDeleteCancelRequested.value = false
  filterDeleteFailedTargets.value = []
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
      if (String(data?.status || '') === 'error') {
        filterDeleteFailedTargets.value = [{
          path: effectivePreviewTargetPaths.value[0],
          error: data?.error || '预审失败'
        }]
      }
      if (['pending', 'running'].includes(data?.status || 'pending')) await pollFilterDeletePreviewStatus(filterDeleteJobId.value)
      else filterDeleteLoading.value = false
      await writeFilterDeletePreviewActivityLog()
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
    let hasError = false
    let hasCancelled = false
    const failedTargets = []
    const warnings = []
    const errors = []

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
      hasError = hasError || finalData?.status === 'error'
      hasCancelled = hasCancelled || finalData?.status === 'canceled'
      if (finalData?.warning) warnings.push(finalData.warning)
      if (finalData?.error) errors.push(finalData.error)
      if (finalData?.status === 'error') {
        failedTargets.push({
          path: targetPath,
          error: finalData?.error || '预审失败'
        })
      }
    }

    filterDeleteFailedTargets.value = failedTargets

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
      progress_message: hasError
        ? `预审结束，但有 ${errors.length || 1} 个目录预审失败`
        : hasCancelled
          ? `预审已取消，已处理 ${effectivePreviewTargetPaths.value.length} 个目录中的一部分`
          : `预审完成，共处理 ${effectivePreviewTargetPaths.value.length} 个目录`,
      warning: warnings.filter(Boolean).join('；'),
      error: errors.filter(Boolean).join('；'),
      status: hasError ? 'error' : (hasCancelled ? 'canceled' : 'completed')
    })
    filterDeleteLoading.value = false
    await writeFilterDeletePreviewActivityLog()
  } catch (error) {
    clearFilterDeletePoll()
    filterDeleteLoading.value = false
    filterDeleteJobId.value = ''
    filterDeletePreviewInfo.value = {
      ...filterDeletePreviewInfo.value,
      status: 'error',
      pendingDirectories: 0,
      progressMessage: '',
      error: error.response?.data?.detail || error.message || '加载删除过滤预审失败'
    }
    await writeFilterDeletePreviewActivityLog('error')
    ElMessage.error('\u52a0\u8f7d\u8fc7\u6ee4\u5220\u9664\u9884\u89c8\u5931\u8d25: ' + (error.response?.data?.detail || error.message))
  }
}

async function retryFailedFilterDeleteTargets () {
  if (filterDeleteBusy.value || !filterDeleteFailedTargets.value.length || !props.libraryId) return
  const failedTargets = [...filterDeleteFailedTargets.value]
  const retryStartedAt = Date.now()
  filterDeleteLoading.value = true
  const recoveredItems = []
  let recoveredSelectedCount = 0
  let recoveredSelectedSize = 0
  let recoveredScannedEntries = 0
  let recoveredDiscoveredEntries = 0
  let recoveredRuleCount = Number(filterDeletePreviewInfo.value.ruleCount || 0)
  let recoveredHasPartialSize = filterDeletePreviewInfo.value.selectedSizeExact === false
  let recoveredHasBasicTreeOnly = filterDeletePreviewInfo.value.sizeDisabled === true
  let recoveredHasTruncated = !!filterDeletePreviewInfo.value.truncated
  const nextFailedTargets = []
  const retryWarnings = []
  const retryErrors = []

  try {
    for (let index = 0; index < failedTargets.length; index += 1) {
      const target = failedTargets[index]
      filterDeletePreviewInfo.value = {
        ...filterDeletePreviewInfo.value,
        status: 'running',
        currentPath: displayFilterDeletePath(target.path),
        progressMessage: `正在重试失败预审 ${index + 1} / ${failedTargets.length}: ${getFileName(target.path) || target.path}`
      }
      try {
        const data = await libraryApi.startFilterDeletePreviewJob(props.libraryId, target.path, {
          rules: props.rules
        })
        let finalData = data
        if (['pending', 'running'].includes(data?.status || 'pending') && data?.job_id) {
          finalData = await waitForFilterDeletePreviewJob(data.job_id, target.path, index, failedTargets.length)
        }
        if (finalData?.status === 'error') {
          nextFailedTargets.push({
            path: target.path,
            error: finalData?.error || '预审失败'
          })
          if (finalData?.error) retryErrors.push(finalData.error)
          continue
        }
        recoveredItems.push(...(Array.isArray(finalData?.items) ? finalData.items : []))
        recoveredSelectedCount += Number(finalData?.selected_count || 0)
        recoveredSelectedSize += Number(finalData?.selected_size || 0)
        recoveredScannedEntries += Number(finalData?.scanned_entries || 0)
        recoveredDiscoveredEntries += Number(finalData?.discovered_entries || 0)
        recoveredRuleCount = Math.max(
          recoveredRuleCount,
          Array.isArray(finalData?.rules) ? finalData.rules.length : Number(finalData?.rule_count || 0)
        )
        recoveredHasPartialSize = recoveredHasPartialSize || finalData?.selected_size_exact === false
        recoveredHasBasicTreeOnly = recoveredHasBasicTreeOnly || finalData?.size_disabled === true
        recoveredHasTruncated = recoveredHasTruncated || !!finalData?.truncated
        if (finalData?.warning) retryWarnings.push(finalData.warning)
      } catch (error) {
        nextFailedTargets.push({
          path: target.path,
          error: error?.response?.data?.detail || error?.message || '预审失败'
        })
        retryErrors.push(error?.response?.data?.detail || error?.message || '预审失败')
      }
    }

    const mergedItemMap = new Map(filterDeleteItems.value.map(item => [item.id, item]))
    recoveredItems.forEach(item => {
      if (item?.id) mergedItemMap.set(item.id, item)
    })
    filterDeleteFailedTargets.value = nextFailedTargets
    applyFilterDeletePreviewData({
      folder_name: filterDeletePreviewInfo.value.folderName,
      folder_path: filterDeletePreviewInfo.value.folderPath,
      items: [...mergedItemMap.values()],
      selected_count: Number(filterDeletePreviewInfo.value.selectedCount || 0) + recoveredSelectedCount,
      selected_size: Number(filterDeletePreviewInfo.value.selectedSize || 0) + recoveredSelectedSize,
      selected_size_exact: !recoveredHasPartialSize,
      size_disabled: recoveredHasBasicTreeOnly,
      truncated: recoveredHasTruncated,
      rule_count: recoveredRuleCount,
      scanned_entries: Number(filterDeletePreviewInfo.value.scannedEntries || 0) + recoveredScannedEntries,
      discovered_entries: Number(filterDeletePreviewInfo.value.discoveredEntries || 0) + recoveredDiscoveredEntries,
      pending_directories: nextFailedTargets.length,
      current_path: '',
      progress_message: nextFailedTargets.length
        ? `重试完成，仍有 ${nextFailedTargets.length} 个目录预审失败`
        : `失败项重试完成，已补回 ${recoveredItems.length} 个命中项`,
      warning: retryWarnings.filter(Boolean).join('；'),
      error: retryErrors.filter(Boolean).join('；'),
      status: nextFailedTargets.length ? 'error' : 'completed'
    }, { preserveSelection: true })
    await activityLogApi.logFilterDelete({
      mode: 'retry_preview',
      session_key: filterDeleteSessionKey.value,
      status: nextFailedTargets.length ? (recoveredItems.length ? 'partial_success' : 'failed') : 'success',
      scope_label: props.scopeLabel || getFileName(props.currentPath) || text.currentFolder,
      folder_name: filterDeletePreviewInfo.value.folderName || '',
      folder_path: props.currentPath || filterDeletePreviewInfo.value.folderPath || '',
      duration_ms: Math.max(0, Date.now() - retryStartedAt),
      retry_target_count: failedTargets.length,
      retry_success_count: failedTargets.length - nextFailedTargets.length,
      retry_failed_count: nextFailedTargets.length,
      recovered_item_count: recoveredItems.length,
      recovered_selected_size: recoveredSelectedSize,
      retry_targets: failedTargets.map(item => ({
        path: item.path,
        name: getFileName(item.path),
        type: 'dir',
        status: nextFailedTargets.some(target => target.path === item.path) ? 'failed' : 'success',
        error: item.error || ''
      })),
      recovered_items: recoveredItems,
      failed_targets: nextFailedTargets.map(item => ({
        path: item.path,
        name: getFileName(item.path),
        type: 'dir',
        status: 'failed',
        error: item.error || '预审失败'
      })),
      warning: retryWarnings.filter(Boolean).join('；'),
      error: retryErrors.filter(Boolean).join('；')
    })
    if (nextFailedTargets.length) {
      ElMessage.warning(`失败项重试完成，仍有 ${nextFailedTargets.length} 个目录失败`)
    } else {
      ElMessage.success('失败项已重试成功并补回到当前预审结果')
    }
  } finally {
    filterDeleteLoading.value = false
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
    getFilterDeleteSubtreeIds(row).forEach(childId => next.add(childId))
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
  const subtreeIds = getFilterDeleteSubtreeIds(row)
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
      getFilterDeleteSubtreeIds(row).forEach(id => next.add(id))
    })
    filterDeleteSelectedIds.value = next
  }
  filterDeleteLastSelectedId.value = filterDeleteBulkSelectableRows.value.at(-1)?.id || ''
}

function handleFilterDeleteRowClick (row, event) {
  if (filterDeleteBusy.value || !row?.id) return
  if (row.type === 'dir') {
    toggleFilterDeleteExpand(row)
    return
  }
  if (canFilterDeleteSelectRow(row)) {
    toggleFilterDeleteSelect(row, event)
  }
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
  if (row?.type === 'dir') return filterDeleteExpandedIds.value.has(row.id) ? FolderOpen : Folder
  return libraryEntryIconFor(row)
}

// dir / 领域色都交给共享 helper走 9 类色盘
function resolveFilterDeleteTreeIconStyle (row) {
  const meta = libraryEntryMetaFor(row)
  return {
    color: meta.color,
    fill: meta.fillIcon ? 'currentColor' : 'none',
  }
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
    await showSystemConfirm({
      title: '\u786e\u8ba4\u5220\u9664\u8fc7\u6ee4\u6587\u4ef6',
      message: filterDeleteBasicTreeOnly.value
        ? `\u786e\u5b9a\u5220\u9664\u5df2\u9009 ${filterDeleteSelectedRoots.value.length} \u9879\u5417\uff1f\n\n\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\uff0c\u8bf7\u786e\u8ba4\u5df2\u7ecf\u5ba1\u9605\u65e0\u8bef\u3002`
        : `\u786e\u5b9a\u5220\u9664\u5df2\u9009 ${filterDeleteSelectedRoots.value.length} \u9879\u5417\uff1f\u9884\u8ba1\u5220\u9664 ${formatFileSize(filterDeleteSelectedSize.value)}\u3002\n\n\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\uff0c\u8bf7\u786e\u8ba4\u5df2\u7ecf\u5ba1\u9605\u65e0\u8bef\u3002`,
      confirmText: '\u786e\u5b9a\u5220\u9664',
      cancelText: '\u53d6\u6d88',
      tone: 'danger'
    })
  } catch (_) {
    return
  }

  filterDeleteDeleting.value = true
  filterDeleteLoadedSessionKey.value = filterDeleteSessionKey.value
  filterDeleteDeleteCancelRequested.value = false
  filterDeleteApplyLoggedExecutionKey.value = ''
  try {
    const deleteStartedAt = Date.now()
    const paths = filterDeleteSelectedRoots.value.map(item => resolveFilterDeleteDeleteTarget(item))
    const executionKey = `${filterDeleteSessionKey.value}::${deleteStartedAt}::${paths.length}`
    const sizeByPath = new Map(filterDeleteSelectedRoots.value.map(item => [resolveFilterDeleteDeleteTarget(item), Number(item.size || 0)]))
    const normalizedItemMeta = filterDeleteItems.value.map(item => ({
      path: normalizeFilterDeleteComparePath(item.path || item.delete_path),
      type: item.type
    }))
    const attemptedItems = buildFilterDeleteLogItemsByTargets(filterDeleteItems.value, paths)
    const selectedRootItems = filterDeleteSelectedRoots.value.map(buildFilterDeleteLogItem).filter(Boolean)
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
    const batchId = `filter-delete-${filterDeleteSessionKey.value || Date.now()}`
    const succeededPaths = []
    const failedItems = []
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
        await libraryApi.browserDelete(props.libraryId, path, true, {
          skipActivityLog: true,
          batchId
        })
        successCount += 1
        succeededPaths.push(path)
        deletedBytes += Number(sizeByPath.get(path) || 0)
        deletedFolderCount += Number(folderCountByPath.get(path) || 0)
      } catch (error) {
        failedCount += 1
        failedItems.push({
          path,
          name: getFileName(path),
          type: 'dir',
          size: Number(sizeByPath.get(path) || 0),
          status: 'failed',
          error: error?.response?.data?.detail || error?.message || '删除失败'
        })
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
    const succeededItems = buildFilterDeleteLogItemsByTargets(attemptedItems, succeededPaths)
    await writeFilterDeleteApplyActivityLog({
      session_key: filterDeleteSessionKey.value,
      execution_key: executionKey,
      status: filterDeleteDeleteCancelRequested.value
        ? 'cancelled'
        : (successCount > 0 && failedCount > 0 ? 'partial_success' : (failedCount > 0 ? 'failed' : 'success')),
      scope_label: props.scopeLabel || getFileName(props.currentPath) || text.currentFolder,
      folder_name: filterDeletePreviewInfo.value.folderName || '',
      folder_path: props.currentPath || filterDeletePreviewInfo.value.folderPath || '',
      duration_ms: Math.max(0, Date.now() - deleteStartedAt),
      selected_count: selectedRootItems.length,
      success_count: successCount,
      failed_count: failedCount,
      deleted_bytes: deletedBytes,
      deleted_folder_count: deletedFolderCount,
      attempted_items: attemptedItems,
      succeeded_items: succeededItems,
      failed_items: failedItems,
      batch_id: batchId
    })
    if (filterDeleteDeleteCancelRequested.value) ElMessage.warning(`\u8fc7\u6ee4\u5220\u9664\u5df2\u505c\u6b62\uff1a\u6210\u529f ${successCount} \u9879\uff0c\u5931\u8d25 ${failedCount} \u9879`)
    else if (failedCount > 0) ElMessage.warning(`\u8fc7\u6ee4\u5220\u9664\u5b8c\u6210\uff1a\u6210\u529f ${successCount} \u9879\uff0c\u5931\u8d25 ${failedCount} \u9879`)
    else ElMessage.success(`\u8fc7\u6ee4\u5220\u9664\u5b8c\u6210\uff1a\u6210\u529f ${successCount} \u9879`)
  } catch (error) {
    await writeFilterDeleteApplyActivityLog({
      session_key: filterDeleteSessionKey.value,
      execution_key: `${filterDeleteSessionKey.value}::fatal::${Date.now()}`,
      status: 'failed',
      scope_label: props.scopeLabel || getFileName(props.currentPath) || text.currentFolder,
      folder_name: filterDeletePreviewInfo.value.folderName || '',
      folder_path: props.currentPath || filterDeletePreviewInfo.value.folderPath || '',
      duration_ms: 0,
      selected_count: filterDeleteSelectedRoots.value.length,
      success_count: 0,
      failed_count: filterDeleteSelectedRoots.value.length,
      deleted_bytes: 0,
      deleted_folder_count: 0,
      attempted_items: buildFilterDeleteLogItemsByTargets(filterDeleteItems.value, filterDeleteSelectedRoots.value.map(item => resolveFilterDeleteDeleteTarget(item))),
      failed_items: [{
        path: props.currentPath || '',
        name: getFileName(props.currentPath || ''),
        type: 'dir',
        size: 0,
        status: 'failed',
        error: error.response?.data?.detail || error.message || '过滤删除失败'
      }],
      error: error.response?.data?.detail || error.message || '过滤删除失败'
    })
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

function getFilterDeleteSubtreeIds (row) {
  const ids = []
  const walk = node => {
    if (!node) return
    if (node.id) ids.push(node.id)
    for (const child of node.children || []) {
      walk(child)
    }
  }
  walk(row)
  return ids
}

function isFilterDeleteRowFullySelected (row) {
  const ids = getFilterDeleteSubtreeIds(row)
  return ids.length > 0 && ids.every(id => filterDeleteSelectedIds.value.has(id))
}

function isFilterDeleteRowPartiallySelected (row) {
  const ids = getFilterDeleteSubtreeIds(row)
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
  const indent = Math.min(depth * 6, 18)
  return {
    paddingLeft: `${indent}px`
  }
}

function buildFilterDeleteLogItem (item) {
  if (!item) return null
  return {
    path: item.path || item.delete_path || '',
    relative_path: item.relative_path || '',
    name: item.name || getFileName(item.path || item.delete_path || ''),
    type: item.type || 'file',
    size: Number(item.size || 0),
    matched_rules: Array.isArray(item.matched_rules) ? item.matched_rules : [],
    covered_by: item.covered_by || '',
    delete_path: item.delete_path || item.path || ''
  }
}

function buildFilterDeleteLogItemsByTargets (items, targetPaths = []) {
  const normalizedTargets = [...new Set((targetPaths || []).map(normalizeFilterDeleteComparePath).filter(Boolean))]
  return (items || [])
    .filter(item => {
      if (!normalizedTargets.length) return true
      return isFilterDeletePathRemoved(resolveFilterDeleteDeleteTarget(item), normalizedTargets)
    })
    .map(buildFilterDeleteLogItem)
    .filter(Boolean)
}

async function writeFilterDeletePreviewActivityLog (statusOverride = '') {
  const sessionKey = filterDeleteSessionKey.value
  if (!sessionKey || filterDeletePreviewLoggedSessionKey.value === sessionKey) return
  const status = String(statusOverride || filterDeletePreviewInfo.value.status || 'idle')
  if (!['completed', 'canceled', 'error'].includes(status)) return
  filterDeletePreviewLoggedSessionKey.value = sessionKey
  try {
    await activityLogApi.logFilterDelete({
      mode: 'preview',
      session_key: sessionKey,
      status: status === 'completed' ? 'success' : (status === 'canceled' ? 'cancelled' : 'failed'),
      scope_label: props.scopeLabel || getFileName(props.currentPath) || text.currentFolder,
      folder_name: filterDeletePreviewInfo.value.folderName || '',
      folder_path: props.currentPath || filterDeletePreviewInfo.value.folderPath || '',
      duration_ms: Math.max(0, Date.now() - Number(filterDeleteStartedAt.value || Date.now())),
      selected_count: Number(filterDeletePreviewInfo.value.selectedCount || 0),
      selected_size: Number(filterDeletePreviewInfo.value.selectedSize || 0),
      selected_size_exact: filterDeletePreviewInfo.value.selectedSizeExact !== false,
      scanned_entries: Number(filterDeletePreviewInfo.value.scannedEntries || 0),
      discovered_entries: Number(filterDeletePreviewInfo.value.discoveredEntries || 0),
      pending_directories: Number(filterDeletePreviewInfo.value.pendingDirectories || 0),
      preview_target_total: Number(filterDeletePreviewTargetTotal.value || 0),
      rule_count: Number(filterDeletePreviewInfo.value.ruleCount || 0),
      truncated: !!filterDeletePreviewInfo.value.truncated,
      truncated_reason: filterDeletePreviewInfo.value.truncatedReason || '',
      warning: filterDeletePreviewInfo.value.warning || '',
      error: filterDeletePreviewInfo.value.error || '',
      items: buildFilterDeleteLogItemsByTargets(filterDeleteItems.value)
    })
  } catch (_) {}
}

async function writeFilterDeleteApplyActivityLog (payload = {}) {
  const executionKey = String(payload.execution_key || '')
  if (!executionKey || filterDeleteApplyLoggedExecutionKey.value === executionKey) return
  filterDeleteApplyLoggedExecutionKey.value = executionKey
  try {
    await activityLogApi.logFilterDelete({
      mode: 'apply',
      ...payload
    })
  } catch (_) {}
}

function getFilterDeleteNameCellStyle (row) {
  const depth = Math.max(0, Number(row?.depth || 0))
  const indent = Math.max(0, depth * 2 - 2)
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
.custom-preview-modal :deep(.el-dialog__body) {
  padding: 0;
}

.custom-preview-overlay {
  background: transparent !important;
  background-image: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

.glass-card {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.46), rgba(255, 255, 255, 0.26));
  border: 1px solid rgba(255, 255, 255, 0.54);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.42),
    0 22px 60px rgba(15, 23, 42, 0.09);
  backdrop-filter: blur(22px) saturate(145%);
}

.glass-shell {
  position: relative;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.58), rgba(255, 255, 255, 0.34)),
    radial-gradient(circle at top left, rgba(191, 219, 254, 0.18), transparent 34%),
    radial-gradient(circle at top right, rgba(186, 230, 253, 0.14), transparent 28%);
  backdrop-filter: blur(28px) saturate(155%);
  -webkit-backdrop-filter: blur(28px) saturate(155%);
  border: 1px solid rgba(255, 255, 255, 0.42);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.56),
    0 28px 80px rgba(15, 23, 42, 0.14);
}

.glass-shell::before {
  display: none;
  content: none;
}

.window-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.4);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.06));
}

.fm-header-main {
  flex: 1;
  min-width: 0;
}

.fm-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.fm-badge {
  flex: 0 0 auto;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.56);
  background: rgba(255, 255, 255, 0.46);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38);
  padding: 3px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.fd-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: rgba(241, 245, 249, 0.5);
  border: 1px solid rgba(226, 232, 240, 0.6);
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.02);
  transition: all 0.2s ease;
}

.fd-chip:hover {
  background: rgba(241, 245, 249, 0.8);
  border-color: rgba(203, 213, 225, 0.8);
  color: #475569;
  transform: translateY(-0.5px);
}

.fd-type-tag {
  box-shadow: 0 2px 5px rgba(15, 23, 42, 0.03);
}

.fd-type-tag-active {
  background: rgba(238, 242, 255, 0.8);
  border-color: rgba(199, 210, 254, 0.8);
  color: #4338ca;
}

.fd-type-tag-active:hover {
  background: rgba(238, 242, 255, 1);
  border-color: rgba(165, 180, 252, 1);
}

.fd-type-tag-partial {
  background: rgba(245, 243, 255, 0.6);
  border-color: rgba(221, 214, 254, 0.6);
  color: #6d28d9;
}

.fd-type-tag-inactive {
  background: rgba(255, 255, 255, 0.5);
  border-color: rgba(226, 232, 240, 0.8);
  color: #64748b;
}

.fd-type-tag-inactive:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(203, 213, 225, 1);
  color: #475569;
}

.fd-type-count {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.6);
  color: #94a3b8;
  border: 1px solid rgba(0, 0, 0, 0.03);
}

.action-card {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  height: 34px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.52);
  background: rgba(255, 255, 255, 0.42);
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 6px 18px rgba(15, 23, 42, 0.05);
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease;
}

.action-icon {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.action-card:hover {
  border-color: rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.58);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.action-card:hover .action-icon {
  transform: scale(1.08);
}

.action-card:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.06);
}

.action-card-danger {
  border-color: rgba(252, 165, 165, 0.38);
  background: rgba(254, 242, 242, 0.42);
  color: #b91c1c;
}

.action-card-danger:hover {
  border-color: rgba(248, 113, 113, 0.48);
  background: rgba(254, 226, 226, 0.56);
  box-shadow: 0 10px 24px rgba(239, 68, 68, 0.16);
}

.action-card-ghost {
  background: rgba(255, 255, 255, 0.34);
}

.action-card-primary {
  border-color: rgba(59, 130, 246, 0.26);
  background: rgba(59, 130, 246, 0.9);
  color: #fff;
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.24);
}

.action-card-primary:hover {
  border-color: rgba(37, 99, 235, 0.32);
  background: rgba(37, 99, 235, 0.94);
  box-shadow: 0 14px 34px rgba(37, 99, 235, 0.3);
}

.action-card-warning {
  background: #fffbeb;
  border-color: #fde68a;
  color: #d97706;
}

.action-card-warning:hover {
  background: #fef3c7;
  border-color: #fcd34d;
  color: #b45309;
}

.action-card:disabled,
.tree-expander:disabled,
.close-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.search-shell {
  border-color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.34);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 8px 24px rgba(15, 23, 42, 0.04);
  backdrop-filter: blur(18px) saturate(135%);
  height: 36px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.search-shell:focus-within {
  border-color: rgba(148, 163, 184, 0.34);
  box-shadow:
    0 0 0 3px rgba(255, 255, 255, 0.2),
    0 12px 28px rgba(15, 23, 42, 0.06);
}

.search-input {
  width: 100%;
  border: none;
  background: transparent;
  color: #0f172a;
  font-size: 13px;
  outline: none;
}

.tree-panel {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.34), rgba(255, 255, 255, 0.18));
  border: 1px solid rgba(255, 255, 255, 0.46);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 20px 48px rgba(15, 23, 42, 0.07);
  backdrop-filter: blur(20px) saturate(140%);
}

.tree-head {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.28), rgba(255, 255, 255, 0.12));
  border-bottom-color: rgba(255, 255, 255, 0.34) !important;
}

.fd-tree-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px minmax(220px, 280px);
  column-gap: 6px;
}

.fd-head-basic .fd-tree-grid,
.fd-row-basic .fd-tree-grid {
  grid-template-columns: minmax(0, 1fr) 72px;
}

.tree-col-size,
.tree-size {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 96px;
  height: 100%;
  justify-self: center;
  text-align: center;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tree-col-time,
.tree-time {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: flex-start;
  min-width: 220px;
  height: 100%;
  justify-self: start;
  width: 100%;
  font-variant-numeric: tabular-nums;
  text-align: left;
}

.tree-row {
  position: relative;
  cursor: pointer;
  min-height: 44px;
  transition:
    transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.24s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.18s ease;
  will-change: transform;
}

.tree-row:hover {
  z-index: 1;
  background: transparent;
  transform: translate3d(0, -2px, 0);
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.1),
    inset 0 0 0 1px rgba(15, 23, 42, 0.08);
}

.tree-row-selected {
  background: rgba(15, 23, 42, 0.07);
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.12);
}

.tree-row-selected:hover {
  background: rgba(15, 23, 42, 0.09);
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.12),
    inset 0 0 0 1px rgba(15, 23, 42, 0.14);
}

.tree-main {
  min-width: 0;
  line-height: 1.15;
}

.tree-name {
  line-height: 1.2;
}

.tree-sub {
  margin-top: 1px;
  line-height: 1.15;
}

.checkbox-minus {
  width: 9px;
  height: 2px;
  border-radius: 999px;
  background: currentColor;
}

.expander-spacer {
  width: 21px;
  flex: 0 0 21px;
}

.tree-expander {
  cursor: pointer;
  transition: background-color 0.15s ease, transform 0.15s ease;
}

.tree-expander:hover {
  background: rgba(148, 163, 184, 0.12);
}

.tree-expander:active:not(:disabled) {
  transform: scale(0.96);
}

.tree-checkbox,
.close-button {
  cursor: pointer;
}

.tree-scroll {
  scrollbar-gutter: stable;
}

/* 颜色现在由 _libraryFileKind helper 通过 inline :style 接管，这里只保留兜底色 */
.tree-icon {
  color: #64748b;
  flex-shrink: 0;
  transition: color 0.18s ease;
}

.tree-sort-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  white-space: nowrap;
}

.tree-sort-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  flex: 0 0 12px;
  font-size: 10px;
}

.tree-col-time-button {
  gap: 1px;
  align-items: flex-start;
  justify-content: flex-start;
  white-space: normal;
  text-transform: none;
}

.tree-col-time-label {
  display: block;
  width: 100%;
  line-height: 1.2;
  text-align: left;
}

.tree-col-time-sort {
  display: block;
  width: 100%;
  min-height: 12px;
  color: #94a3b8;
  font-size: 10px;
  line-height: 1;
  text-align: left;
}

.tree-time-date {
  color: #475569;
  display: block;
  font-weight: 600;
  font-size: 12px;
  line-height: 1.2;
  width: 100%;
  text-align: left;
}

.tree-time-rule {
  display: block;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #94a3b8;
  font-size: 10px;
  line-height: 1.2;
  margin-top: 2px;
}

.icon-folder {
  color: #64748b;
  fill: #eff6ff;
}

.tree-checkbox-on {
  background: #111827;
  color: #fff;
  border-color: #111827;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
}

.tree-checkbox-partial {
  background: rgba(15, 23, 42, 0.08);
  color: #111827;
  border-color: rgba(15, 23, 42, 0.14);
}

.tree-checkbox-off {
  background: white;
  border-color: #cbd5e1;
}

.tree-checkbox-off:hover {
  border-color: #94a3b8;
}

.preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 220px;
  color: #94a3b8;
  font-size: 13px;
}

.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
</style>

