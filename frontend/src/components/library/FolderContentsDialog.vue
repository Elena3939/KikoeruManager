<template>
  <el-dialog
    v-model="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal folder-dialog"
    align-center
    modal-class="custom-preview-overlay"
  >
    <div
      class="window panel-enter glass-shell relative flex w-full max-w-[1280px] aspect-[16/10] flex-col overflow-hidden rounded-3xl"
    >
      <div class="window-header flex items-center justify-between px-6 py-4">
        <div class="fm-header-main min-w-0">
          <div class="fm-title-row">
            <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">
              {{ getDialogFolderName() }}
            </h1>
            <span class="fm-badge">{{ folderContentsInfo.recursive === false && !folderContentsInfo.viaIndex ? `当前层 ${formatFileSize(folderContentsInfo.totalSize)}` : formatFileSize(folderContentsInfo.totalSize) }}</span>
          </div>
          <p class="mt-1 truncate text-sm text-slate-500">
            {{ getDialogFolderPath() }}
          </p>
        </div>
        <div class="fm-count-pill">
          {{ visibleFileCount }} / {{ totalFileCount }} 个文件
        </div>
        <button
          type="button"
          class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
          @click="visible = false"
        >
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <!-- 加载遮罩仅覆盖 body 区，避免遮住 window-header 里的关闭按钮 -->
      <div
        class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5"
        v-app-loading="{ loading: folderLoading, text: '正在读取目录内容...', size: 120 }"
      >
        <div class="toolbar-row flex items-center justify-between gap-3 border-b border-slate-200/70 py-3">
          <div class="toolbar-actions flex items-center gap-2">
            <button
              type="button"
              class="action-card action-card-danger"
              :disabled="!folderSelectedDeletePaths.length || folderDeleting"
              @click="batchDeleteSubFiles"
            >
              <Trash2 :size="15" />
              <span>批量删除</span>
            </button>
            <button
              type="button"
              class="action-card"
              :disabled="folderLoading || folderDeleting"
              @click="reload"
            >
              <RefreshCw :size="15" class="action-icon action-icon-refresh" :class="{ 'is-spinning': folderLoading }" />
              <span>刷新</span>
            </button>
            <button
              type="button"
              class="action-card"
              :disabled="folderLoading"
              @click="toggleExpandAll"
            >
              <ChevronDown :size="15" class="toolbar-toggle-icon" :class="{ 'is-collapsed': !isAllExpanded }" />
              <span>{{ isAllExpanded ? '全部收起' : '展开全部' }}</span>
            </button>
          </div>

          <div class="toolbar-search-group flex min-w-0 items-center gap-2">
            <label class="search-shell flex w-[320px] min-w-0 items-center gap-2 rounded-xl border px-3 py-2">
              <Search :size="16" class="text-slate-400" />
              <input
                v-model="folderSearch"
                class="search-input"
                placeholder="搜索文件名或路径..."
                :disabled="folderLoading || folderDeleting"
                @input="onSearchInput"
              >
            </label>
            <button
              type="button"
              class="action-card action-card-ghost shrink-0"
              :disabled="folderLoading || folderDeleting || !folderItems.length"
              @click="openMojibakeRepairPreview"
            >
              <DotLottieVue
                class="fm-repair-lottie"
                :src="translateAnimation"
                autoplay
                loop
                background="transparent"
                style="width: 22px; height: 22px; flex-shrink: 0;"
              />
              <span>修复乱码文件名</span>
            </button>
          </div>
        </div>

        <div v-if="folderSelectedDeleteRoots.length" class="selection-card selection-inline mt-3 flex items-center gap-5 text-sm text-slate-600">
          <span>已选 <span class="text-slate-900 font-semibold">{{ folderSelectedDeleteRoots.length }}</span> 项待删</span>
          <span>预计释放 <span class="text-slate-900 font-semibold">{{ formatFileSize(folderSelectedDeleteSize) }}</span></span>
        </div>

        <section ref="treePanelRef" class="glass-panel glass-card tree-panel mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
          <div class="tree-head tree-grid items-center gap-3 border-b border-slate-200/70 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400" :style="{ paddingRight: `calc(16px + ${treeScrollbarWidth}px)` }">
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                :class="selectionState === 'all' ? 'tree-checkbox-on' : (selectionState === 'partial' ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                :disabled="folderLoading || folderDeleting"
                @click="toggleAllFiles"
              >
                <Check v-if="selectionState === 'all'" :size="13" />
                <span v-else-if="selectionState === 'partial'" class="checkbox-minus" />
              </button>
              <span>文件名</span>
            </div>
            <span class="tree-col-size">大小</span>
            <span class="tree-col-time">修改时间</span>
            <span class="tree-col-action">操作</span>
          </div>

          <div ref="treeScrollRef" class="tree-scroll flex-1 overflow-auto px-4 py-2 no-scrollbar">
            <div v-if="!folderLoading && flatTree.length === 0" class="preview-empty">
              {{ folderSearch ? '没有匹配项' : '当前目录为空' }}
            </div>

            <div v-else class="tree-list tree-virtual-canvas" :style="treeVirtualCanvasStyle">
              <div
                v-for="{ virtualRow, row } in virtualTreeRows"
                :key="row.id"
                class="tree-node tree-virtual-row"
                :style="{
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }"
              >
                <div
                  class="tree-row tree-grid items-center gap-3 rounded-md px-3 py-1"
                  :class="isRowChecked(row) || isRowIndeterminate(row) ? 'tree-row-selected' : ''"
                  @click="handleFolderRowClick(row, $event)"
                >
                  <div class="tree-main flex min-w-0 items-center gap-2" :style="{ paddingLeft: `${row.depth * 16}px` }">
                    <button
                      v-if="row.type === 'dir'"
                      type="button"
                      class="tree-expander rounded p-0.5"
                      :disabled="isDirectoryLoading(row)"
                      @click.stop="toggleExpand(row)"
                    >
                      <RefreshCw v-if="isDirectoryLoading(row)" :size="15" class="text-slate-400 action-icon-refresh is-spinning" />
                      <ChevronDown v-else-if="expandedIds.has(row.id)" :size="17" class="text-slate-400" />
                      <ChevronRight v-else :size="17" class="text-slate-400" />
                    </button>
                    <span v-else class="expander-spacer" />

                    <button
                      type="button"
                      class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                      :class="isRowChecked(row) ? 'tree-checkbox-on' : (isRowIndeterminate(row) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                      :disabled="folderDeleting"
                      @click.stop="toggleFileSelect(row, $event)"
                    >
                      <Check v-if="isRowChecked(row)" :size="13" />
                      <span v-else-if="isRowIndeterminate(row)" class="checkbox-minus" />
                    </button>

                    <component :is="resolveTreeIcon(row)" :size="17" class="tree-icon" :style="resolveTreeIconStyle(row)" />

                    <div class="min-w-0 flex-1">
                      <div class="tree-name truncate text-[13px] font-medium text-slate-800">{{ getRowDisplayName(row) }}</div>
                      <div class="tree-sub truncate text-[11px] text-slate-400">{{ getRowSubtitle(row) }}</div>
                    </div>
                  </div>

                  <span class="tree-size text-[12px] tabular-nums text-slate-400">{{ formatFileSize(row.size) }}</span>
                  <span class="tree-time text-[12px] text-slate-400">{{ formatDate(row.modified_time) }}</span>

                  <div class="tree-action-wrap" @click.stop>
                    <button
                      type="button"
                      class="row-action inline-flex size-[22px] items-center justify-center rounded-full"
                      :disabled="folderDeleting"
                      @click="deleteEntry(row)"
                    >
                      <Trash2 :size="12" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </el-dialog>

  <el-dialog
    v-model="repairPreviewVisible"
    :show-close="false"
    width="min(1120px, calc(100vw - 32px))"
    modal-class="custom-preview-overlay"
    append-to-body
    destroy-on-close
    class="custom-preview-modal mojibake-preview-dialog"
  >
    <div class="window panel-enter glass-shell relative flex w-full max-w-[1120px] flex-col overflow-hidden rounded-3xl">
      <div class="window-header flex items-center justify-between px-6 py-4">
        <div class="fm-header-main min-w-0">
          <div class="fm-title-row">
            <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">
              乱码文件名修复预览
            </h1>
            <span class="fm-badge">{{ repairPreviewRows.length }} 项候选</span>
          </div>
          <p class="mt-1 truncate text-sm text-slate-500">
            {{ getDialogFolderPath() }}
          </p>
        </div>
        <div class="fm-count-pill">
          已选 {{ selectedRepairRows.length }} / {{ repairPreviewRows.length }} 项
        </div>
        <button
          type="button"
          class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
          @click="repairPreviewVisible = false"
        >
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5">
        <div class="toolbar-row flex items-center justify-between gap-3 border-b border-slate-200/70 py-3">
          <div class="toolbar-actions flex items-center gap-2">
            <button
              v-if="repairPreviewRows.length"
              type="button"
              class="action-card action-card-ghost group"
              @click="toggleAllRepairRows"
            >
              <Check :size="15" class="action-icon" />
              <span>{{ isAllRepairRowsSelected ? '取消全选' : '全选候选' }}</span>
            </button>
          </div>
          <el-tooltip
            content="预览确认后才会真正重命名，目录和文件都支持勾选"
            placement="top"
            effect="dark"
          >
            <div class="flex items-center justify-center size-7 rounded-full bg-slate-100/60 text-slate-400 hover:bg-slate-200/80 hover:text-slate-600 transition-colors cursor-help">
              <Info :size="14" />
            </div>
          </el-tooltip>
        </div>

      <div class="repair-preview-body">
        <div v-if="!repairPreviewRows.length" class="repair-preview-empty">
          <Search :size="32" class="text-slate-300 mb-3" />
          <span>没找到可安全修复的乱码文件名</span>
        </div>

        <div v-else class="repair-preview-list">
          <div v-for="row in repairPreviewRows" :key="row.path" class="repair-preview-card">
            <button
              type="button"
              class="tree-checkbox relative mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
              :class="row.selected ? 'tree-checkbox-on' : 'tree-checkbox-off'"
              @click="toggleRepairRow(row)"
            >
              <Check v-if="row.selected" :size="13" />
            </button>
            <div class="repair-preview-type" :class="row.itemType === 'dir' ? 'is-dir' : 'is-file'">
              {{ row.itemType === 'dir' ? '目录' : '文件' }}
            </div>
            <div class="repair-preview-label">原名</div>
            <div class="repair-preview-value">{{ row.currentName }}</div>
            <div class="repair-preview-arrow">→</div>
            <div class="repair-preview-label">修复后</div>
            <div v-if="!row.needsManualInput" class="repair-preview-value is-next">{{ row.nextName }}</div>
            <input
              v-else
              v-model="row.nextName"
              class="repair-preview-input"
              placeholder="手动输入修复后的文件名"
            >
            <div class="repair-preview-path">{{ row.relativePath }}</div>
            <div v-if="row.forcedInclude" class="repair-preview-encoding is-manual">已按勾选强制带入预览</div>
            <div v-else-if="row.encodingPair" class="repair-preview-encoding">{{ row.encodingPair }}</div>
            <div v-else-if="row.needsManualInput" class="repair-preview-encoding is-manual">未能自动推断，需手动填写</div>
          </div>
        </div>
      </div>

      <div class="repair-preview-footer border-t border-slate-200/70 pt-4">
        <button
          type="button"
          class="action-card"
          :disabled="repairApplying"
          @click="repairPreviewVisible = false"
        >
          取消
        </button>
        <button
          type="button"
          class="action-card action-card-primary"
          :disabled="repairApplying || !selectedRepairRows.length"
          @click="applyMojibakeRepair"
        >
          <RefreshCw :size="15" class="action-icon action-icon-refresh" :class="{ 'is-spinning': repairApplying }" />
          <span>{{ repairApplying ? '正在修复...' : `确认修复 ${selectedRepairRows.length} 项` }}</span>
        </button>
      </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import translateAnimation from '../../assets/anime/Translate.lottie'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../../composables/useSystemPrompt'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Info,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-vue-next'
import { libraryApi } from '../../api'
import { libraryEntryIconFor, libraryEntryMetaFor } from './_libraryFileKind'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  libraryId: { type: String, default: '' },
  folderPath: { type: String, default: '' },
  folderName: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'mutated'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})

const folderLoading = ref(false)
const folderDeleting = ref(false)
const folderSearch = ref('')
const repairPreviewVisible = ref(false)
const repairApplying = ref(false)
const repairPreviewRows = ref([])
const folderContentsInfo = ref({
  folderName: '',
  folderPath: '',
  totalFiles: 0,
  totalSize: 0,
  totalFolderCount: 0,
  recursive: false,
  viaIndex: false,
})
const folderItems = ref([])
const selectedFileIds = ref(new Set())
const expandedIds = ref(new Set())
const loadingDirectoryIds = ref(new Set())
const folderLastSelectedId = ref('')
const treePanelRef = ref(null)
const treeScrollRef = ref(null)
const treeScrollbarWidth = ref(0)

const TREE_ROW_HEIGHT = 46
const TREE_ROW_OVERSCAN = 16

const treeRoot = computed(() => buildTree(folderItems.value, folderContentsInfo.value.folderPath, folderContentsInfo.value.recursive))
const treeIndex = computed(() => buildTreeIndex(treeRoot.value))
const folderNodeById = computed(() => treeIndex.value.nodeById)
const filteredRoot = computed(() => {
  const keyword = folderSearch.value.trim().toLowerCase()
  return keyword ? filterTree(treeRoot.value, keyword) : treeRoot.value
})
const flatTree = computed(() => flattenTree(filteredRoot.value, 0, expandedIds.value))
const visibleFileCount = computed(() => visibleFileIds.value.length)
const loadedFileCount = computed(() => countLoadedFiles(treeRoot.value))
const totalFileCount = computed(() => Math.max(Number(folderContentsInfo.value.totalFiles || 0), loadedFileCount.value))
const allSelectableIds = computed(() => collectNodeIds(filteredRoot.value))
const visibleFileIds = computed(() => {
  const ids = []
  for (const row of flatTree.value) {
    if (row?.type === 'file' && row.id) ids.push(row.id)
  }
  return ids
})
const allFilesSelected = computed(() => allSelectableIds.value.length > 0 && allSelectableIds.value.every(id => selectedFileIds.value.has(id)))
const someFilesSelected = computed(() => !allFilesSelected.value && allSelectableIds.value.some(id => selectedFileIds.value.has(id)))
const selectionState = computed(() => {
  if (allFilesSelected.value) return 'all'
  if (someFilesSelected.value) return 'partial'
  return 'none'
})
const allDirectoryIds = computed(() => collectDirectoryIds(filteredRoot.value))
const isAllExpanded = computed(() => {
  if (!allDirectoryIds.value.length) return false
  return allDirectoryIds.value.every(id => expandedIds.value.has(id))
})
const folderSelectedRows = computed(() => [...selectedFileIds.value].map(id => folderNodeById.value.get(id)).filter(Boolean))
const folderSelectedDeleteRoots = computed(() => {
  const rows = [...folderSelectedRows.value].sort((left, right) => String(left.relative_path || '').length - String(right.relative_path || '').length)
  const roots = []
  for (const row of rows) {
    const rowPath = normalizeAnyPath(resolveNodePath(row))
    if (!rowPath) continue
    if (roots.some(existing => isDescendantPath(rowPath, normalizeAnyPath(resolveNodePath(existing))))) continue
    roots.push(row)
  }
  return roots
})
const folderSelectedDeletePaths = computed(() => folderSelectedDeleteRoots.value.map(row => resolveNodePath(row)).filter(Boolean))
const folderSelectedDeleteSize = computed(() => folderSelectedDeleteRoots.value.reduce((sum, row) => sum + Number(row?.size || 0), 0))
const selectedRepairRows = computed(() => repairPreviewRows.value.filter(row => row.selected))
const isAllRepairRowsSelected = computed(() => repairPreviewRows.value.length > 0 && repairPreviewRows.value.every(row => row.selected))

const treeRowSelectionState = computed(() => {
  const selected = selectedFileIds.value
  const state = new Map()

  const walk = node => {
    if (!node?.id) return { checkedCount: 0, total: 0 }
    if (node.type === 'file') {
      const checked = selected.has(node.id)
      state.set(node.id, { checked, indeterminate: false })
      return { checkedCount: checked ? 1 : 0, total: 1 }
    }

    let checkedCount = 0
    let total = 1
    if (selected.has(node.id)) checkedCount += 1
    for (const child of node.children || []) {
      const childState = walk(child)
      checkedCount += childState.checkedCount
      total += childState.total
    }
    state.set(node.id, {
      checked: checkedCount === total,
      indeterminate: checkedCount > 0 && checkedCount < total,
    })
    return { checkedCount, total }
  }

  for (const row of treeRoot.value) {
    walk(row)
  }
  return state
})

const treeRowVirtualizer = useVirtualizer(computed(() => ({
  count: flatTree.value.length,
  getScrollElement: () => treeScrollRef.value,
  estimateSize: () => TREE_ROW_HEIGHT,
  overscan: TREE_ROW_OVERSCAN,
})))

const virtualTreeRows = computed(() => treeRowVirtualizer.value.getVirtualItems()
  .map(virtualRow => ({
    virtualRow,
    row: flatTree.value[virtualRow.index],
  }))
  .filter(item => item.row))

const treeVirtualCanvasStyle = computed(() => ({
  height: `${treeRowVirtualizer.value.getTotalSize()}px`,
}))

watch(visible, async value => {
  if (value) {
    window.addEventListener('keydown', handleDialogKeydown)
    window.addEventListener('resize', syncTreeScrollbarWidth)
    await reload()
    return
  }
  window.removeEventListener('keydown', handleDialogKeydown)
  window.removeEventListener('resize', syncTreeScrollbarWidth)
})

watch(() => props.folderPath, async (nextPath, prevPath) => {
  if (!visible.value || !nextPath || nextPath === prevPath) return
  await reload()
})

watch(
  () => [flatTree.value.length, folderSearch.value, expandedIds.value.size].join(':'),
  () => {
    nextTick(() => treeRowVirtualizer.value.measure())
  },
)

function handleDialogKeydown (event) {
  if (!visible.value || folderLoading.value || folderDeleting.value || isTextInputElement(event.target)) return
  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'a') {
    event.preventDefault()
    selectedFileIds.value = new Set(getFolderSelectableIds())
    folderLastSelectedId.value = allSelectableIds.value.at(-1) || ''
  }
}

async function reload () {
  if (!props.folderPath || !props.libraryId) return
  folderLoading.value = true
  try {
    const previousExpanded = new Set([...expandedIds.value].map(id => String(id).replace(/^dir:/, '')))
    const previousSelected = new Set(selectedFileIds.value)
    const data = await libraryApi.browserFolderContents(props.libraryId, props.folderPath, { recursive: false })
    const items = Array.isArray(data.items) ? data.items : []
    folderItems.value = items.map(item => normalizeShallowItem(item, data.folder_path || props.folderPath || ''))
    folderContentsInfo.value = {
      folderName: data.folder_name || props.folderName || '',
      folderPath: data.folder_path || props.folderPath || '',
      totalFiles: pickNonNegativeNumber(data.total_files, items.filter(item => !(item?.is_directory || item?.type === 'dir')).length),
      totalSize: pickNonNegativeNumber(data.total_size, data.total_size_bytes, items.reduce((sum, item) => sum + Number(item?.size || 0), 0)),
      totalFolderCount: pickNonNegativeNumber(data.total_folder_count, 0),
      recursive: data.recursive !== false,
      viaIndex: Boolean(data.browse_via_index),
    }

    const directories = []
    const walk = nodes => nodes.forEach(node => {
      if (node.type === 'dir') {
        directories.push(node)
        walk(node.children || [])
      }
    })
    walk(treeRoot.value)

    if (previousExpanded.size) {
      expandedIds.value = new Set(directories.filter(node => previousExpanded.has(node.relative_path)).map(node => node.id))
    } else {
      expandedIds.value = new Set()
    }

    const validIds = new Set(folderNodeById.value.keys())
    selectedFileIds.value = new Set([...previousSelected].filter(id => validIds.has(id)))
    if (folderLastSelectedId.value && !validIds.has(folderLastSelectedId.value)) {
      folderLastSelectedId.value = ''
    }
    await nextTick()
    treeRowVirtualizer.value.scrollToOffset(0)
    treeRowVirtualizer.value.measure()
    syncTreeScrollbarWidth()
  } catch (error) {
    visible.value = false
    ElMessage.error('加载文件夹内容失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderLoading.value = false
  }
}

async function openMojibakeRepairPreview () {
  try {
    const forcedRows = folderSelectedRows.value.filter(row => row?.type === 'file')
    const forcedPaths = [...new Set(forcedRows.map(row => resolveNodePath(row)).filter(Boolean))]
    const preview = await libraryApi.browserMojibakePreview(props.libraryId, props.folderPath, {
      selectedPaths: forcedPaths
    })
    repairPreviewRows.value = Array.isArray(preview?.items)
      ? preview.items.map(item => ({
        path: item.path,
        currentName: item.current_name,
        nextName: item.suggested_name,
        relativePath: item.relative_path,
        encodingPair: item.encoding_pair || '',
        itemType: item.item_type || 'file',
        selected: item.forced_include ? true : !Boolean(item.needs_manual_input),
        needsManualInput: Boolean(item.needs_manual_input),
        forcedInclude: Boolean(item.forced_include),
      }))
      : []
    repairPreviewVisible.value = true
  } catch (error) {
    ElMessage.error('生成乱码修复预览失败: ' + (error.response?.data?.detail || error.message))
  }
}

function syncTreeScrollbarWidth () {
  const el = treeScrollRef.value
  if (!el) {
    treeScrollbarWidth.value = 0
    return
  }
  treeScrollbarWidth.value = Math.max(0, el.offsetWidth - el.clientWidth)
}

async function deleteEntry (row) {
  const path = resolveNodePath(row)
  if (!path) return
  await deletePaths([path], { previewRow: row })
}

async function batchDeleteSubFiles () {
  if (!folderSelectedDeletePaths.value.length) return
  await deletePaths(folderSelectedDeletePaths.value, { previewRows: folderSelectedDeleteRoots.value })
}

async function deletePaths (paths, options = {}) {
  const { previewRow = null, previewRows = [] } = options
  const effectivePreviewRow = previewRow || (paths.length === 1 && previewRows.length === 1 ? previewRows[0] : null)
  folderDeleting.value = true
  try {
    if (paths.length === 1) {
      const preview = await libraryApi.browserDelete(props.libraryId, paths[0], false)
      await showSystemConfirm({
        title: '删除确认',
        message: buildDeletePreviewMessage(preview, effectivePreviewRow),
        confirmText: '确定删除',
        cancelText: '取消',
        tone: 'danger'
      })
      await libraryApi.browserDelete(props.libraryId, paths[0], true)
      ElMessage.success('删除成功')
      const previewCounts = getRowDeleteCounts(effectivePreviewRow)
      emit('mutated', {
        deletedBytes: resolveDeletePreviewSize(preview?.size, effectivePreviewRow?.size),
        deletedFolderCount: Number(preview?.folder_count ?? previewCounts.folderCount)
      })
    } else {
      const preview = await libraryApi.browserBatchDelete(props.libraryId, paths, false)
      await showSystemConfirm({
        title: '批量删除确认',
        message: buildBatchDeletePreviewMessage(preview, previewRows),
        confirmText: '确定删除',
        cancelText: '取消',
        tone: 'danger'
      })
      const result = await libraryApi.browserBatchDelete(props.libraryId, paths, true)
      const failedCount = Number(result?.failed_paths?.length || 0)
      if (failedCount) {
        ElMessage.warning(`批量删除完成：成功 ${result.success_count || 0} 项，失败 ${failedCount} 项`)
      } else {
        ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 项`)
      }
      const previewCounts = getRowsDeleteCounts(previewRows)
      emit('mutated', {
        deletedBytes: resolveDeletePreviewSize(preview?.total_size, previewRows.reduce((sum, row) => sum + Number(row?.size || 0), 0)),
        deletedFolderCount: Number(preview?.total_folder_count ?? previewCounts.folderCount)
      })
    }
    selectedFileIds.value = new Set()
    folderLastSelectedId.value = ''
    await reload()
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderDeleting.value = false
  }
}

function buildTree (items, basePath, recursive = true) {
  if (!recursive && Array.isArray(items) && items.some(item => item?.id && item?.type)) {
    return items
  }
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => String(a.relative_path || '').localeCompare(String(b.relative_path || '')))

  for (const item of sorted) {
    const itemType = item.type || (item.is_directory ? 'dir' : 'file')
    if (!recursive) {
      const node = {
        ...item,
        id: buildNodeId(itemType, item.path || item.relative_path || item.name),
        type: itemType,
        relative_path: item.relative_path || item.name || '',
        resolved_path: item.path || joinFolderPath(basePath, item.relative_path || item.name || ''),
        children: itemType === 'dir' ? (Array.isArray(item.children) ? item.children : []) : undefined,
        childrenLoaded: itemType !== 'dir' || Boolean(item.children_loaded),
        hasChildren: itemType === 'dir' ? item.has_children !== false : false,
      }
      root.push(node)
      continue
    }
    const parts = String(item.relative_path || item.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let path = ''

    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = {
          id: key,
          name: parts[index],
          type: 'dir',
          relative_path: path,
          resolved_path: joinFolderPath(basePath, path),
          size: 0,
          modified_time: null,
          children: [],
          childrenLoaded: true,
          hasChildren: true,
        }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }

    children.push({
      ...item,
      id: `file:${item.path}`,
      type: 'file',
      resolved_path: item.path,
      childrenLoaded: true,
      hasChildren: false,
    })
  }

  const walk = node => {
    let total = 0
    let latest = null
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += Number(child.size || 0)
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }

  root.forEach(node => {
    if (node.type === 'dir') walk(node)
  })
  return root
}

function normalizeShallowItem (item, basePath) {
  const itemType = item?.type || (item?.is_directory ? 'dir' : 'file')
  const relativePath = item?.relative_path || item?.name || ''
  const resolvedPath = item?.path || joinFolderPath(basePath, relativePath)
  const fileCount = pickOptionalNonNegativeNumber(item?.file_count)
  const folderCount = pickOptionalNonNegativeNumber(item?.folder_count)
  const hasIndexedCounts = fileCount !== null || folderCount !== null
  const hasChildren = itemType === 'dir'
    ? (item?.has_children !== undefined
        ? Boolean(item.has_children)
        : (hasIndexedCounts ? Number(fileCount || 0) > 0 || Number(folderCount || 0) > 0 : true))
    : false
  return {
    ...item,
    id: buildNodeId(itemType, resolvedPath || relativePath),
    type: itemType,
    relative_path: relativePath,
    resolved_path: resolvedPath,
    children: itemType === 'dir' ? (Array.isArray(item?.children) ? item.children : []) : undefined,
    childrenLoaded: itemType !== 'dir' || Boolean(item?.children_loaded),
    hasChildren,
    file_count: fileCount ?? item?.file_count,
    folder_count: folderCount ?? item?.folder_count,
  }
}

function buildNodeId (type, path) {
  return `${type === 'dir' ? 'dir' : 'file'}:${normalizeAnyPath(path)}`
}

function buildTreeIndex (nodes = []) {
  const nodeById = new Map()
  const deleteCountsById = new Map()

  const walk = node => {
    if (!node?.id) return { folderCount: 0, fileCount: 0 }
    nodeById.set(node.id, node)

    if (node.type === 'file') {
      deleteCountsById.set(node.id, { folderCount: 0, fileCount: 1 })
      return { folderCount: 0, fileCount: 1 }
    }

    let childFolderCount = 0
    let childFileCount = 0

    for (const child of node.children || []) {
      const childMeta = walk(child)
      childFolderCount += childMeta.folderCount
      childFileCount += childMeta.fileCount
    }

    const indexedFolderCount = pickOptionalNonNegativeNumber(node.folder_count)
    const indexedFileCount = pickOptionalNonNegativeNumber(node.file_count)
    const folderCount = 1 + (indexedFolderCount ?? childFolderCount)
    const fileCount = indexedFileCount ?? childFileCount

    deleteCountsById.set(node.id, { folderCount, fileCount })
    return { folderCount, fileCount }
  }

  for (const node of nodes || []) {
    walk(node)
  }

  return {
    nodeById,
    deleteCountsById,
  }
}

function filterTree (nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const searchFields = [node.name, node.relative_path]
      .map(value => String(value || '').toLowerCase())
      .filter(Boolean)
    const matched = searchFields.some(value => value.includes(keyword))
    if (node.type === 'file') {
      if (matched) result.push(node)
      continue
    }
    const children = filterTree(node.children || [], keyword)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree (nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

async function toggleExpand (node) {
  if (node?.type !== 'dir') return
  if (!expandedIds.value.has(node.id) && node.hasChildren && !node.childrenLoaded) {
    const loaded = await loadDirectoryChildren(node)
    if (!loaded) return
  }
  const next = new Set(expandedIds.value)
  if (next.has(node.id)) next.delete(node.id)
  else next.add(node.id)
  expandedIds.value = next
}

async function loadDirectoryChildren (node) {
  const path = resolveNodePath(node)
  if (!path || loadingDirectoryIds.value.has(node.id)) return false
  loadingDirectoryIds.value = new Set([...loadingDirectoryIds.value, node.id])
  try {
    const data = await libraryApi.browserFolderContents(props.libraryId, path, { recursive: false })
    const items = Array.isArray(data.items) ? data.items : []
    replaceTreeNodeChildren(node.id, items.map(item => normalizeShallowItem(item, path)), data)
    await nextTick()
    treeRowVirtualizer.value.measure()
    return true
  } catch (error) {
    ElMessage.error('加载子目录失败: ' + (error.response?.data?.detail || error.message))
    return false
  } finally {
    const next = new Set(loadingDirectoryIds.value)
    next.delete(node.id)
    loadingDirectoryIds.value = next
  }
}

function replaceTreeNodeChildren (targetId, children, summary = {}) {
  const visit = nodes => {
    for (const node of nodes || []) {
      if (node.id === targetId) {
        node.children = children
        node.childrenLoaded = true
        node.hasChildren = children.length > 0
        const childSize = children.reduce((sum, child) => sum + Number(child?.size || 0), 0)
        const hasReadySize = Boolean(summary?.browse_via_index || node.size_status === 'ready')
        node.size = hasReadySize ? pickNonNegativeNumber(summary?.total_size, summary?.total_size_bytes, node.size, childSize) : node.size
        node.file_count = pickNonNegativeNumber(
          summary?.total_files,
          node.file_count,
          children.reduce((sum, child) => sum + (child?.type === 'dir' ? Number(child?.file_count || 0) : 1), 0)
        )
        node.folder_count = pickNonNegativeNumber(
          summary?.total_folder_count,
          node.folder_count,
          children.reduce((sum, child) => sum + (child?.type === 'dir' ? 1 + Number(child?.folder_count || 0) : 0), 0)
        )
        node.modified_time = children.reduce((latest, child) => {
          if (!child?.modified_time) return latest
          return !latest || child.modified_time > latest ? child.modified_time : latest
        }, null)
        node.size_status = hasReadySize ? 'ready' : node.size_status
        return true
      }
      if (node.children?.length && visit(node.children)) {
        return true
      }
    }
    return false
  }

  if (visit(folderItems.value)) {
    folderItems.value = folderItems.value.slice()
  }
}

function expandAll () {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => {
    if (node.type === 'dir') {
      if (node.childrenLoaded || node.children?.length) {
        next.add(node.id)
        walk(node.children || [])
      }
    }
  })
  walk(filteredRoot.value)
  expandedIds.value = next
}

function collapseAll () {
  expandedIds.value = new Set()
}

function toggleExpandAll () {
  if (isAllExpanded.value) {
    collapseAll()
    return
  }
  expandAll()
}

function onSearchInput () {
  if (folderSearch.value.trim()) expandAll()
}

function getFolderSelectableIds () {
  return allSelectableIds.value
}

function collectNodeIds (nodes = []) {
  const ids = []
  const walk = list => {
    for (const node of list || []) {
      ids.push(node.id)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(nodes)
  return ids
}

function collectDirectoryIds (nodes = []) {
  const ids = []
  const walk = list => {
    for (const node of list || []) {
      if (node?.type !== 'dir') continue
      ids.push(node.id)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(nodes)
  return ids
}

function getSelectableSubtreeIds (row) {
  if (!row?.id) return []
  const sourceNode = folderNodeById.value.get(row.id) || row
  return collectNodeIds([sourceNode])
}

function countLoadedFiles (nodes = []) {
  let count = 0
  const walk = list => {
    for (const node of list || []) {
      if (node?.type === 'file') {
        count += 1
        continue
      }
      if (node?.children?.length) walk(node.children)
    }
  }
  walk(nodes)
  return count
}

function selectFolderRange (targetId, preserveExisting = true) {
  const rowIds = getFolderSelectableIds()
  const targetIndex = rowIds.indexOf(targetId)
  if (targetIndex === -1) return
  const anchorId = folderLastSelectedId.value && rowIds.includes(folderLastSelectedId.value) ? folderLastSelectedId.value : rowIds[0]
  const anchorIndex = rowIds.indexOf(anchorId)
  const [start, end] = [anchorIndex, targetIndex].sort((left, right) => left - right)
  const next = preserveExisting ? new Set(selectedFileIds.value) : new Set()
  rowIds.slice(start, end + 1).forEach(id => next.add(id))
  selectedFileIds.value = next
  folderLastSelectedId.value = targetId
}

function toggleFileSelect (row, event = null) {
  if (!row?.id) return
  if (event?.shiftKey) {
    selectFolderRange(row.id, true)
    return
  }
  const next = new Set(selectedFileIds.value)
  const subtreeIds = getSelectableSubtreeIds(row)
  const isChecked = subtreeIds.every(id => next.has(id))
  if (isChecked) {
    subtreeIds.forEach(id => next.delete(id))
  } else {
    subtreeIds.forEach(id => next.add(id))
  }
  selectedFileIds.value = next
  folderLastSelectedId.value = row.id
}

function toggleAllFiles () {
  const checked = !allFilesSelected.value
  selectedFileIds.value = checked ? new Set(allSelectableIds.value) : new Set()
  folderLastSelectedId.value = checked ? allSelectableIds.value.at(-1) || '' : ''
}

function handleFolderRowClick (row, event) {
  if (!row?.id) return
  if (event?.shiftKey) {
    selectFolderRange(row.id, true)
    return
  }
  toggleFileSelect(row, event)
}

function resolveNodePath (row) {
  return row?.resolved_path || row?.path || ''
}

function isDirectoryLoading (row) {
  return Boolean(row?.id && loadingDirectoryIds.value.has(row.id))
}

function isRowChecked (row) {
  if (!row?.id) return false
  const state = treeRowSelectionState.value.get(row.id)
  return Boolean(state?.checked)
}

function isRowIndeterminate (row) {
  if (!row?.id || row.type !== 'dir') return false
  const state = treeRowSelectionState.value.get(row.id)
  return Boolean(state?.indeterminate)
}

function normalizeAnyPath (value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+$/, '')
}

function isDescendantPath (candidate, parent) {
  if (!candidate || !parent) return false
  return candidate === parent || candidate.startsWith(`${parent}/`)
}

function resolveTreeIcon (row) {
  if (row?.type === 'dir') return expandedIds.value.has(row.id) ? FolderOpen : Folder
  return libraryEntryIconFor(row)
}

function resolveTreeIconStyle (row) {
  const meta = libraryEntryMetaFor(row)
  return {
    color: meta.color,
    fill: meta.fillIcon ? 'currentColor' : 'none',
  }
}

function getRowSubtitle (row) {
  if (!row) return '-'
  if (row.type === 'dir') {
    const counts = getRowDeleteCounts(row)
    if (!counts.folderCount && !counts.fileCount) return '空目录'
    const parts = []
    if (counts.folderCount > 1) parts.push(`${counts.folderCount - 1} 个子目录`)
    parts.push(`${counts.fileCount} 个文件`)
    return parts.join(' · ')
  }
  return row.relative_path || row.name || '-'
}

function getRowDisplayName (row) {
  return row?.name || '-'
}

function getRowDisplayRelativePath (row) {
  return row?.relative_path || row?.name || '-'
}

function getDialogFolderName () {
  return folderContentsInfo.value.folderName || props.folderName || '文件管理'
}

function getDialogFolderPath () {
  return folderContentsInfo.value.folderPath || props.folderPath || '当前目录'
}

async function applyMojibakeRepair () {
  if (!selectedRepairRows.value.length) return
  repairApplying.value = true
  try {
    let successCount = 0
    const failed = []
    const operations = [...selectedRepairRows.value].sort(compareRepairRowsForApply)
    const renameItems = []
    const rowByIndex = new Map()
    operations.forEach((row) => {
      const nextName = String(row.nextName || '').trim()
      if (!nextName || nextName === row.currentName) {
        failed.push({
          name: `${row.itemType === 'dir' ? '目录' : '文件'} ${row.currentName}`,
          reason: row.needsManualInput ? '未填写新的名称' : '目标名称无变化'
        })
        return
      }
      const index = renameItems.length
      renameItems.push({
        path: row.path,
        new_name: nextName,
        current_name: row.currentName
      })
      rowByIndex.set(index, row)
    })

    if (renameItems.length) {
      const result = await libraryApi.browserBatchRename(props.libraryId, renameItems, {
        renameContext: 'folder_contents_mojibake_repair'
      })
      successCount += Number(result?.success_count || 0)
      const failedItems = [
        ...(Array.isArray(result?.failed) ? result.failed : []),
        ...(Array.isArray(result?.failed_items) ? result.failed_items : [])
      ]
      const seen = new Set()
      failedItems.forEach((item) => {
        const index = Number(item?.index)
        const row = rowByIndex.get(Number.isInteger(index) ? index : -1)
        const key = `${index}::${item?.path || item?.source_path || ''}::${item?.error || ''}`
        if (seen.has(key)) return
        seen.add(key)
        failed.push({
          name: row
            ? `${row.itemType === 'dir' ? '目录' : '文件'} ${row.currentName}`
            : (item?.path || item?.source_path || '未知项'),
          reason: item?.error || '重命名失败'
        })
      })
    }

    repairPreviewVisible.value = false
    await reload()

    if (!failed.length) {
      ElMessage.success(`已修复 ${successCount} 个文件名`)
      return
    }

    ElMessage.warning(`已修复 ${successCount} 个文件名，失败 ${failed.length} 个`)
  } finally {
    repairApplying.value = false
  }
}

function toggleRepairRow (row) {
  row.selected = !row.selected
}

function toggleAllRepairRows () {
  const next = !isAllRepairRowsSelected.value
  repairPreviewRows.value.forEach(row => {
    row.selected = next
  })
}

function compareRepairRowsForApply (left, right) {
  const leftTypeOrder = left?.itemType === 'dir' ? 0 : 1
  const rightTypeOrder = right?.itemType === 'dir' ? 0 : 1
  if (leftTypeOrder !== rightTypeOrder) return leftTypeOrder - rightTypeOrder
  const leftDepth = String(left?.path || '').replace(/\\/g, '/').split('/').filter(Boolean).length
  const rightDepth = String(right?.path || '').replace(/\\/g, '/').split('/').filter(Boolean).length
  if (leftDepth !== rightDepth) return leftDepth - rightDepth
  return String(left?.relativePath || '').localeCompare(String(right?.relativePath || ''))
}

function remapRepairPath (sourcePath, replacements = []) {
  const normalizedSource = normalizeAnyPath(sourcePath)
  let current = normalizedSource
  for (const replacement of replacements) {
    const oldPath = normalizeAnyPath(replacement.oldPath)
    const newPath = normalizeAnyPath(replacement.newPath)
    if (!oldPath || !newPath) continue
    if (current === oldPath) {
      current = newPath
      continue
    }
    if (current.startsWith(`${oldPath}/`)) {
      current = `${newPath}${current.slice(oldPath.length)}`
    }
  }
  return current
}

function scoreDecodedText (text) {
  if (!text) return -999
  let score = 0
  if (/\uFFFD/.test(text)) score -= 12
  if (/[ÃÂÐæçéèêïîöôåäüë鈥鐩鍙彇瀛侀濂彂鍥犺诲悕浜嬩负澶ф湰]/.test(text)) score -= 8
  if (/[一-龥]{6,}/.test(text) && !/[\u3040-\u30ff]/.test(text)) score -= 6
  if (/[\u3040-\u30ff]/.test(text)) score += 10
  if (/[\u4e00-\u9fff]/.test(text)) score += 8
  if (/[\uac00-\ud7af]/.test(text)) score += 6
  if (/[\x20-\x7e]/.test(text)) score += 2
  if (/[^\x09\x0a\x0d\x20-\x7e\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff01-\uff60]/.test(text)) score -= 3
  return score
}

function joinFolderPath (basePath, relativePath) {
  if (!relativePath) return basePath
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const relative = String(relativePath || '').replace(/^[/\\]+/, '')
  return `${base}/${relative}`
}

function pickOptionalNonNegativeNumber (value) {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric < 0) return null
  return numeric
}

function pickNonNegativeNumber (...values) {
  for (const value of values) {
    const numeric = pickOptionalNonNegativeNumber(value)
    if (numeric !== null) return numeric
  }
  return 0
}

function formatFileSize (bytes) {
  if (bytes === null || bytes === undefined) return '-'
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function formatDate (value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function getRowDeleteCounts (row) {
  if (!row) return { folderCount: 0, fileCount: 0 }
  return treeIndex.value.deleteCountsById.get(row.id) || { folderCount: 0, fileCount: 0 }
}

function getRowsDeleteCounts (rows = []) {
  return rows.reduce((result, row) => {
    const counts = getRowDeleteCounts(row)
    result.folderCount += counts.folderCount
    result.fileCount += counts.fileCount
    return result
  }, { folderCount: 0, fileCount: 0 })
}

function resolveDeletePreviewSize (previewSize, fallbackSize = 0) {
  const normalizedPreviewSize = Number(previewSize)
  const normalizedFallbackSize = Number(fallbackSize || 0)
  if (Number.isFinite(normalizedPreviewSize) && normalizedPreviewSize > 0) return normalizedPreviewSize
  if (Number.isFinite(normalizedFallbackSize) && normalizedFallbackSize > 0) return normalizedFallbackSize
  return 0
}

function buildDeletePreviewMessage (preview, row = null) {
  const itemType = preview?.type || (row?.type === 'dir' ? 'folder' : 'file')
  const rowCounts = getRowDeleteCounts(row)
  const fileCount = Number(preview?.file_count ?? rowCounts.fileCount ?? (itemType === 'file' ? 1 : 0))
  const folderCount = Number(preview?.folder_count ?? rowCounts.folderCount ?? (itemType === 'folder' || itemType === 'dir' ? 1 : 0))
  const size = resolveDeletePreviewSize(preview?.size, row?.size)
  const lines = ['删除后将移除以下内容：']
  if (itemType === 'folder' || itemType === 'dir') {
    lines.push(`文件夹：${Math.max(folderCount, 1)} 个`)
    if (fileCount) lines.push(`文件：${fileCount} 个`)
  } else {
    lines.push(`文件：${Math.max(fileCount, 1)} 个`)
  }
  lines.push(`大小：${formatFileSize(size)}`)
  lines.push('')
  lines.push('此操作不可恢复，是否继续？')
  return lines.join('\n')
}

function buildBatchDeletePreviewMessage (preview, rows = []) {
  const totalCount = rows.length
  const rowCounts = getRowsDeleteCounts(rows)
  const folderCount = Number(preview?.total_folder_count ?? rowCounts.folderCount)
  const fileCount = Number(preview?.total_file_count ?? rowCounts.fileCount)
  const size = resolveDeletePreviewSize(preview?.total_size, rows.reduce((sum, row) => sum + Number(row?.size || 0), 0))
  return [
    `已选择 ${totalCount} 项待删除`,
    `文件夹：${folderCount} 个`,
    `文件：${fileCount} 个`,
    `大小：${formatFileSize(size)}`,
    '',
    '此操作不可恢复，是否继续？'
  ].join('\n')
}

function isTextInputElement (target) {
  if (!target) return false
  const tagName = String(target.tagName || '').toUpperCase()
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || Boolean(target.isContentEditable)
}

defineExpose({ reload })

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleDialogKeydown)
  window.removeEventListener('resize', syncTreeScrollbarWidth)
})

onMounted(() => {
  if (visible.value) {
    syncTreeScrollbarWidth()
    window.addEventListener('resize', syncTreeScrollbarWidth)
  }
})
</script>

<style scoped>
.custom-preview-modal :deep(.el-dialog__header) {
  display: none;
}

.custom-preview-modal :deep(.el-dialog) {
  background: transparent;
  box-shadow: none;
  width: min(1280px, calc(100vw - 32px));
  max-width: calc(100vw - 32px);
  margin: 0 auto;
}

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
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.22), transparent 30%, rgba(255, 255, 255, 0.08) 65%, transparent 100%);
  opacity: 0.9;
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
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.fm-count-pill {
  flex: 0 0 auto;
  margin-right: 10px;
  border-radius: 999px;
  border: 1px solid rgba(147, 197, 253, 0.56);
  background: rgba(239, 246, 255, 0.4);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.44),
    0 10px 28px rgba(59, 130, 246, 0.12);
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
}

.selection-card {
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.52);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0.24));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.4),
    0 12px 32px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(18px) saturate(135%);
  padding: 12px 14px;
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

.action-card:disabled,
.row-action:disabled,
.tree-expander:disabled,
.close-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.toolbar-toggle-icon {
  transition: transform 0.18s ease;
}

.toolbar-toggle-icon.is-collapsed {
  transform: rotate(-90deg);
}

.action-icon-refresh.is-spinning {
  animation: fm-spin 0.9s linear infinite;
}

.action-card:hover:not(:disabled) .action-icon-refresh:not(.is-spinning) {
  transform: rotate(180deg) scale(1.06);
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

.toolbar-search-group {
  justify-content: flex-end;
  flex: 0 1 auto;
}

.repair-preview-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 14px;
}

.repair-preview-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 56vh;
  overflow: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(15, 23, 42, 0.32) rgba(255, 255, 255, 0.14);
}

.repair-preview-list::-webkit-scrollbar {
  width: 10px;
}

.repair-preview-list::-webkit-scrollbar-track {
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.repair-preview-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(148, 163, 184, 0.9), rgba(100, 116, 139, 0.88));
  border: 2px solid rgba(255, 255, 255, 0.18);
}

.repair-preview-list::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(100, 116, 139, 0.95), rgba(71, 85, 105, 0.92));
}

.repair-preview-list::-webkit-scrollbar-corner {
  background: transparent;
}

.repair-preview-card {
  display: grid;
  grid-template-columns: 18px 44px 52px minmax(0, 1fr) 24px 52px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.52);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0.24));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.4),
    0 12px 32px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(18px) saturate(135%);
  padding: 14px 16px;
}

.repair-preview-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 24px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.repair-preview-type.is-dir {
  background: rgba(219, 234, 254, 0.8);
  color: #1d4ed8;
}

.repair-preview-type.is-file {
  background: rgba(241, 245, 249, 0.96);
  color: #475569;
}

.repair-preview-label {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
}

.repair-preview-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #475569;
}

.repair-preview-value.is-next {
  color: #0f172a;
  font-weight: 600;
}

.repair-preview-input {
  width: 100%;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: rgba(255, 255, 255, 0.78);
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
  border-radius: 10px;
  padding: 8px 10px;
  outline: none;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.46);
}

.repair-preview-input:focus {
  border-color: rgba(96, 165, 250, 0.56);
  box-shadow:
    0 0 0 3px rgba(191, 219, 254, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.56);
}

.repair-preview-arrow {
  text-align: center;
  color: #94a3b8;
  font-weight: 700;
}

.repair-preview-path {
  grid-column: 4 / 8;
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repair-preview-encoding {
  grid-column: 4 / 8;
  font-size: 11px;
  color: #3b82f6;
}

.repair-preview-encoding.is-manual {
  color: #f59e0b;
}

.repair-preview-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
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

.selection-inline {
  padding: 10px 14px;
  border-radius: 12px;
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

.tree-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px 156px 44px;
  column-gap: 6px;
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
  align-items: center;
  justify-content: flex-start;
  min-width: 156px;
  height: 100%;
  justify-self: start;
  width: 100%;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tree-col-action {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  justify-self: start;
  width: 44px;
}

.tree-row {
  cursor: pointer;
  min-height: 44px;
  height: 44px;
  transition: background-color 0.15s ease, transform 0.15s ease;
}

.tree-row:hover {
  background: rgba(255, 255, 255, 0.24);
}

.tree-row-selected {
  background: rgba(191, 219, 254, 0.16);
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.2);
}

.tree-main {
  min-width: 0;
  line-height: 1.15;
}

.tree-action-wrap {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  min-height: 100%;
  width: 44px;
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

.row-action {
  cursor: pointer;
  color: #ef4444;
  background: rgba(254, 242, 242, 0.36);
  justify-self: end;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 6px 16px rgba(239, 68, 68, 0.08);
  transition: transform 0.15s ease, background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.row-action:hover {
  color: #fff;
  background: rgba(239, 68, 68, 0.88);
  box-shadow: 0 10px 20px rgba(239, 68, 68, 0.18);
  transform: translateY(-1px);
}

.row-action:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 3px 8px rgba(239, 68, 68, 0.14);
}

.tree-checkbox,
.close-button {
  cursor: pointer;
}

.tree-scroll {
  scrollbar-gutter: stable;
}

.tree-virtual-canvas {
  position: relative;
  width: 100%;
}

.tree-virtual-row {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
}

/* 颜色现在由 _libraryFileKind helper 通过 inline :style 接管，这里只保留兜底色 */
.tree-icon {
  color: #64748b;
  flex-shrink: 0;
  transition: color 0.18s ease;
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
  background: rgba(255, 255, 255, 0.72);
  color: transparent;
  border-color: rgba(15, 23, 42, 0.12);
}

.preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #475569;
  font-size: 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0.06));
}

.repair-preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
  color: #94a3b8;
  font-size: 14px;
  font-weight: 500;
}

.no-scrollbar::-webkit-scrollbar {
  display: none;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) .glass-shell),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) .glass-shell) {
  background: #121212 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) .glass-shell::before),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) .glass-shell::before) {
  display: none !important;
  content: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.window-header, .fm-body, .toolbar-row, .tree-head)),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.window-header, .fm-body, .toolbar-row, .tree-head)) {
  background: #181818 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.glass-card, .tree-panel, .selection-card, .search-shell, .fm-badge, .fm-count-pill)),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.glass-card, .tree-panel, .selection-card, .search-shell, .fm-badge, .fm-count-pill)) {
  background: #202020 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) .tree-row),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) .tree-row) {
  background: transparent !important;
  background-image: none !important;
  color: rgba(226, 226, 232, 0.84) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.tree-row:hover, .tree-row-selected)),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.tree-row:hover, .tree-row-selected)) {
  background: #2c2c2c !important;
  background-image: none !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.action-card, .close-button)),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.action-card, .close-button)) {
  background: #2c2c2c !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.action-card:hover:not(:disabled), .close-button:hover)),
:global(html.dark :is(.folder-dialog, .mojibake-preview-dialog) :is(.action-card:hover:not(:disabled), .close-button:hover)) {
  background: #343434 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

@keyframes fm-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1180px) {
  .toolbar-row {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-actions {
    flex-wrap: wrap;
  }

  .toolbar-search-group {
    width: 100%;
  }

  .search-shell {
    width: 100%;
  }
}

@media (max-width: 860px) {
  .window-header,
  .fm-body {
    padding-left: 20px;
    padding-right: 20px;
  }

  .tree-head,
  .tree-row {
    grid-template-columns: minmax(0, 1fr) 88px 132px 64px;
  }

  .window-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .fm-count-pill {
    margin-right: 0;
  }

  .repair-preview-card {
    grid-template-columns: 1fr;
  }

  .repair-preview-path {
    grid-column: auto;
  }

  .repair-preview-encoding {
    grid-column: auto;
  }
}

@media (max-width: 640px) {
  .window {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    aspect-ratio: auto !important;
    border-radius: 0 !important;
  }
  .window-header {
    padding: 12px 14px !important;
    gap: 8px;
  }
  .fm-title-row {
    width: 100%;
    min-width: 0;
    flex-wrap: wrap;
  }
  .fm-header-main,
  .fm-header-main p {
    width: 100%;
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .fm-count-pill {
    max-width: 100%;
  }
  .fm-body {
    padding: 0 12px 12px !important;
  }
  .toolbar-row {
    gap: 8px;
    padding: 10px 0;
  }
  .toolbar-actions,
  .toolbar-search-group {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 8px;
  }
  .toolbar-actions .action-card,
  .toolbar-search-group .action-card {
    width: 100%;
    min-width: 0;
    justify-content: center;
    padding-left: 8px;
    padding-right: 8px;
  }
  .toolbar-search-group .search-shell {
    grid-column: 1 / -1;
    width: 100% !important;
  }
  .selection-card {
    flex-direction: column;
    align-items: flex-start !important;
    gap: 4px !important;
  }
  .tree-panel {
    border-radius: 14px !important;
  }
  .tree-head {
    display: none !important;
  }
  .tree-grid,
  .tree-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto !important;
  }
  .tree-size,
  .tree-time {
    display: none !important;
  }
  .tree-action-wrap {
    width: auto;
  }
  .tree-scroll {
    padding: 8px !important;
  }
  .tree-row {
    min-height: 42px;
    padding: 7px 8px !important;
  }
  .tree-name,
  .tree-sub {
    white-space: normal !important;
    overflow-wrap: anywhere;
  }
}

/* 文件管理弹窗暗色最终兜底：去掉 toolbar / 表头残留的蓝灰底色。 */
:global(:is(html.kikoerumanager-dark, html.dark, body.kikoerumanager-dark, body.dark) :is(
  .el-dialog.custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(.window, .glass-shell)) {
  background: #121212 !important;
  background-color: #121212 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  box-shadow: none !important;
  filter: none !important;
}

:global(:is(html.kikoerumanager-dark, html.dark, body.kikoerumanager-dark, body.dark) :is(
  .el-dialog.custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(
  .window-header,
  .fm-body,
  .toolbar-row,
  .tree-head,
  .repair-preview-footer
)) {
  background: #181818 !important;
  background-color: #181818 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.095) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  filter: none !important;
}

:global(:is(html.kikoerumanager-dark, html.dark, body.kikoerumanager-dark, body.dark) :is(
  .el-dialog.custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(
  .glass-panel,
  .glass-card,
  .tree-panel,
  .selection-card,
  .search-shell,
  .fm-badge,
  .fm-count-pill,
  .repair-preview-card,
  .repair-preview-empty
)) {
  background: #202020 !important;
  background-color: #202020 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  outline: 0 !important;
  box-shadow: none !important;
  text-shadow: none !important;
  filter: none !important;
}

:global(:is(html.kikoerumanager-dark, html.dark, body.kikoerumanager-dark, body.dark) :is(
  .el-dialog.custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) .tree-scroll) {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

:global(:is(html.kikoerumanager-dark, html.dark, body.kikoerumanager-dark, body.dark) :is(
  .el-dialog.custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .custom-preview-modal.folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(.tree-row:hover, .tree-row-selected)) {
  background: #2c2c2c !important;
  background-color: #2c2c2c !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

/* 直接命中文件管理弹窗的蓝色残留区，避免基础 slate 样式透出。 */
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .window),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .window),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .window),
:global(html.dark .mojibake-preview-dialog .window) {
  background: #121212 !important;
  background-color: #121212 !important;
  background-image: none !important;
  box-shadow: none !important;
  filter: none !important;
}

:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-body),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .fm-body),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .toolbar-row),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .toolbar-row),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-head),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .tree-head),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .fm-body),
:global(html.dark .mojibake-preview-dialog .fm-body),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .toolbar-row),
:global(html.dark .mojibake-preview-dialog .toolbar-row) {
  background: #181818 !important;
  background-color: #181818 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  filter: none !important;
}

:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-panel),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .tree-panel),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .search-shell),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .search-shell),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-badge),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .fm-badge),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-count-pill),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .fm-count-pill),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-body),
:global(html.dark .mojibake-preview-dialog .repair-preview-body),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-card),
:global(html.dark .mojibake-preview-dialog .repair-preview-card) {
  background: #202020 !important;
  background-color: #202020 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  outline: 0 !important;
  box-shadow: none !important;
  text-shadow: none !important;
  filter: none !important;
}

:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-on),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-on),
:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-partial),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-partial),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .tree-checkbox-on),
:global(html.dark .mojibake-preview-dialog .tree-checkbox-on) {
  background: #565656 !important;
  background-color: #565656 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-off),
:global(html.dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-off),
:global(html.kikoerumanager-dark .mojibake-preview-dialog .tree-checkbox-off),
:global(html.dark .mojibake-preview-dialog .tree-checkbox-off) {
  background: #242424 !important;
  background-color: #242424 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: transparent !important;
  box-shadow: none !important;
}
</style>
