<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal server-upload-preview-modal"
    align-center
    modal-class="custom-preview-overlay"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="previewLoading" class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden dialog-loading-overlay">
      <AppLoadingAnimation label="正在生成上传预览树..." description="同步目录结构、目标库存和上传计划" :size="168" :min-height="260" />
    </div>

    <div v-else class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
      <div class="window-header flex items-center justify-between px-8 py-6">
        <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">{{ title }}</h1>
        <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="emit('update:visible', false)">
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div class="tabs-row px-8 pt-1 pb-3 flex items-center gap-2 overflow-hidden">
        <div class="preview-chip-rail min-w-0 flex-1">
          <div
            ref="previewChipScrollRef"
            class="preview-chip-scroll flex min-w-0 items-center gap-1.5 overflow-x-auto no-scrollbar py-0"
            :class="{ 'is-dragging': previewChipDragState.active }"
            @pointerdown="onPreviewChipPointerDown"
            @pointermove="onPreviewChipPointerMove"
            @pointerup="onPreviewChipPointerUp"
            @pointercancel="onPreviewChipPointerCancel"
            @wheel="onPreviewChipWheel"
            @click.capture="onPreviewChipClickCapture"
          >
          <button
            type="button"
            class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
            :class="allPreviewSelectionState === 'all' ? 'tab-chip-active' : (allPreviewSelectionState === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            @click="toggleAllPreviewSelection"
          >
            <span>全部</span>
          </button>
          <button
            v-for="chip in previewFileTypeChips"
            :key="chip.key"
            type="button"
            class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
            :class="chip.state === 'all' ? 'tab-chip-active' : (chip.state === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            @click="togglePreviewFileType(chip)"
          >
            <span>{{ chip.label }}</span>
          </button>
          </div>
        </div>
        <button type="button" class="tab-chip tab-chip-idle restore-button shrink-0 px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] border" @click="toggleExpandAll">{{ isAllExpanded ? '全部收起' : '全部展开' }}</button>
      </div>

      <div class="content-grid flex-1 flex gap-6 px-8 py-2 min-h-0">
        <div class="left-column w-[380px] flex flex-col gap-6">
          <section ref="selectRoot" class="glass-panel glass-card settings-card flex-1 rounded-2xl p-6 overflow-y-auto no-scrollbar">
            <div class="space-y-6">
              <section class="space-y-4">
                <div class="section-head space-y-1">
                  <h2>上传设置</h2>
                  <p>延用下载预览的布局，在这里确认目标服务器库存，按选中目录原样上传。</p>
                </div>

                <div class="select-grid grid grid-cols-2 gap-4">
                  <div class="field-group space-y-2">
                    <label>目标库存</label>
                    <div class="select-wrap relative">
                      <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" @click.stop="toggleSelectMenu('inventory')">
                        <span class="line-clamp-1 text-left">{{ inventoryLabel }}</span>
                        <ChevronDown :size="18" class="select-arrow size-4 text-slate-400" />
                      </button>

                      <div v-if="openSelect === 'inventory'" class="dropdown-panel dropdown-menu absolute z-50 mt-1 w-full min-w-36 origin-top rounded-lg bg-white/88 border border-white/80 text-slate-800 shadow-lg ring-1 ring-slate-200/80 p-1">
                        <button
                          v-for="option in targetLibraries"
                          :key="option.id"
                          type="button"
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-1.5 text-sm transition-colors hover:bg-slate-100/80"
                          @click.stop="chooseOption('inventory', option.id)"
                        >
                          <span class="truncate">{{ option.name }}</span>
                          <span v-if="settings.targetLibraryId === option.id" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                            <Check :size="16" />
                          </span>
                        </button>
                      </div>
                    </div>
                  </div>

                  <div class="field-group space-y-2">
                    <label>指定目录</label>
                    <div class="picker-wrap relative">
                      <button
                        type="button"
                        class="interactive-field field-input picker-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800"
                        :disabled="!settings.targetLibraryId"
                        :title="targetSubdirHint"
                        @click="openTargetDirectoryPicker"
                      >
                        <span class="picker-label flex items-center gap-1.5 min-w-0">
                          <FolderOpen :size="14" class="text-slate-400 shrink-0" />
                          <span class="line-clamp-1 text-left">{{ targetSubdirLabel }}</span>
                        </span>
                        <span class="flex items-center gap-1 shrink-0">
                          <button
                            v-if="settings.targetSubdir"
                            type="button"
                            class="picker-clear inline-flex items-center justify-center size-5 rounded-md text-slate-400 hover:text-slate-700"
                            title="恢复到库存根目录"
                            @click.stop="clearTargetSubdir"
                          >
                            <X :size="13" />
                          </button>
                          <ChevronRight :size="16" class="text-slate-400" />
                        </span>
                      </button>
                    </div>
                  </div>
                </div>

                <div class="space-y-1.5">
                  <p class="target-path text-xs text-slate-500 leading-relaxed">
                    目标目录: <span class="text-slate-700 break-all">{{ targetDirectoryPreview || '-' }}</span>
                  </p>
                  <p class="target-path text-xs text-slate-500 leading-relaxed">
                    所选目录: <span class="text-slate-700 break-all">{{ selectedFolderPreview || '-' }}</span>
                  </p>
                  <p class="target-path text-xs text-slate-500 leading-relaxed">
                    最终上传位置: <span class="text-slate-700 break-all">{{ finalPathPreview || '-' }}</span>
                  </p>
                </div>
              </section>

              <section class="space-y-4">
                <div class="section-head compact-head">
                  <h2>上传摘要</h2>
                </div>
                <div class="summary-stack space-y-2 text-sm text-slate-600">
                  <div>目标库存剩余空间 {{ remainingSpaceText }}</div>
                  <div v-if="estimatedRemainingSpaceText">上传后预计剩余 {{ estimatedRemainingSpaceText }}</div>
                </div>
              </section>
            </div>
          </section>
        </div>

        <section class="glass-panel glass-card tree-panel flex-1 rounded-2xl flex flex-col overflow-hidden">
          <div ref="treeScrollRef" class="tree-scroll flex-1 p-4 overflow-auto no-scrollbar" @scroll="onPreviewTreeScroll">
            <div v-if="!previewGroups.length" class="preview-empty">当前没有可上传的目录</div>
            <template v-else>
              <div v-if="previewVirtualTopPadding" class="preview-virtual-spacer" :style="{ height: `${previewVirtualTopPadding}px` }" />
              <div class="tree-list space-y-1">
                <div v-for="item in previewVisibleRows" :key="item.id" class="tree-node">
                  <template v-if="item.kind === 'group'">
                  <div
                    class="tree-row plan-node-header flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="isGroupAllSelected(item.group) || isGroupPartiallySelected(item.group) ? 'tree-row-selected' : ''"
                    @click="toggleGroupExpand(item.group)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="toggleGroupExpand(item.group)"
                      >
                        <ChevronDown v-if="item.group.rootExpanded !== false" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="isGroupAllSelected(item.group) ? 'tree-checkbox-on' : (isGroupPartiallySelected(item.group) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="toggleGroupAll(item.group)"
                      >
                        <Check v-if="isGroupAllSelected(item.group)" :size="14" />
                        <span v-else-if="isGroupPartiallySelected(item.group)" class="checkbox-minus" />
                      </button>
                      <component
                        :is="iconMetaForGroup(item.group).icon"
                        :size="20"
                        :stroke-width="2.2"
                        class="tree-icon"
                        :class="[`tree-icon-kind-${classifyGroupKind(item.group)}`, { 'tree-icon-fill': iconMetaForGroup(item.group).fillIcon }]"
                        :style="{ color: iconMetaForGroup(item.group).color }"
                      />
                      <span class="tree-name node-rjcode text-sm text-slate-800 truncate font-medium">
                        {{ getDisplayText(item.group.name) }}
                        <span class="node-title-muted">{{ getDisplayText(item.group.path) }}</span>
                      </span>
                    </div>
                    <span class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(item.group.total_size_bytes) }}</span>
                  </div>
                  </template>

                  <template v-else>
                  <div
                    class="tree-row flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="isTreeNodeChecked(item.row) || isTreeNodePartiallySelected(item.row) ? 'tree-row-selected' : ''"
                    :style="{ paddingLeft: `${(item.row.depth + 1) * 16 + 16}px` }"
                    @click="handleTreeRowClick(item.group, item.row)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        v-if="item.row.type === 'dir'"
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="toggleExpand(item.group, item.row)"
                      >
                        <ChevronDown v-if="item.group.expandedIds.has(item.row.id)" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <span v-else class="expander-spacer" />
                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="isTreeNodeChecked(item.row) ? 'tree-checkbox-on' : (isTreeNodePartiallySelected(item.row) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="toggleTreeRow(item.group, item.row)"
                      >
                        <Check v-if="isTreeNodeChecked(item.row)" :size="14" />
                        <span v-else-if="isTreeNodePartiallySelected(item.row)" class="checkbox-minus" />
                      </button>
                      <component
                        :is="iconMetaForRow(item.row).icon"
                        :size="20"
                        :stroke-width="2.2"
                        class="tree-icon"
                        :class="[`tree-icon-kind-${classifyRowKind(item.row)}`, { 'tree-icon-fill': iconMetaForRow(item.row).fillIcon }]"
                        :style="{ color: iconMetaForRow(item.row).color }"
                      />
                      <span
                        class="tree-name text-sm truncate font-medium"
                        :class="isTreeNodePartiallySelected(item.row) ? 'tree-name-partial' : 'text-slate-800'"
                      >{{ getDisplayText(item.row.name) }}</span>
                    </div>
                    <span v-if="item.row.size_bytes" class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(item.row.size_bytes) }}</span>
                  </div>
                  </template>
                </div>
              </div>
              <div v-if="previewVirtualBottomPadding" class="preview-virtual-spacer" :style="{ height: `${previewVirtualBottomPadding}px` }" />
            </template>
          </div>
        </section>
      </div>

      <div class="footer-row px-8 py-6 flex items-center justify-between">
        <div class="summary text-sm text-slate-500 font-medium"><span class="summary-strong text-slate-900">{{ selectedGroupCount }}</span> 个目录待上传，共 <span class="summary-strong text-slate-900">{{ formatSize(selectedTotalBytes) }}</span></div>

        <div class="footer-actions flex items-center gap-3">
          <button type="button" class="primary-cta px-10 h-11 rounded-xl font-bold text-white" :disabled="selectedGroupCount === 0 || starting || !settings.targetLibraryId" @click="emitSubmit">
            <span v-if="starting" class="inline-flex items-center"><AppLoadingAnimation variant="inline" :size="30" class="mr-1" />处理中</span>
            <span v-else>开始上传</span>
          </button>
          <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="emit('update:visible', false)">取消</button>
        </div>
      </div>
    </div>
  </el-dialog>

  <RemoteFolderPickerDialog
    v-model:visible="targetDirectoryDialogVisible"
    :library="selectedTargetLibrary"
    :initial-relative-path="settings.targetSubdir"
    title="指定上传目录"
    @submit="handleTargetDirectorySubmit"
  />
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { Check, ChevronDown, ChevronRight, FolderOpen, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { libraryApi } from '../../api'
import AppLoadingAnimation from './AppLoadingAnimation.vue'
import RemoteFolderPickerDialog from './RemoteFolderPickerDialog.vue'
import { classifyLibraryEntryKind, libraryEntryMetaFor } from '../library/_libraryFileKind.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  starting: { type: Boolean, default: false },
  title: { type: String, default: '上传到服务器' },
  sourceLibraryId: { type: String, default: '' },
  sourceLibraryName: { type: String, default: '' },
  circleName: { type: String, default: '' },
  sourceItems: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  initialTargetLibraryId: { type: String, default: '' },
  initialTargetSubdir: { type: String, default: '' },
})

const emit = defineEmits(['update:visible', 'submit'])

const PREVIEW_ROW_HEIGHT = 41
const PREVIEW_OVERSCAN = 12
const PREVIEW_VIRTUAL_THRESHOLD = 180

const previewLoading = ref(false)
const previewGroups = shallowRef([])
const previewTreeVersion = ref(0)
const openSelect = ref(null)
const selectRoot = ref(null)
const previewChipScrollRef = ref(null)
const treeScrollRef = ref(null)
const previewScrollTop = ref(0)
const previewViewportHeight = ref(420)
const storageInfo = ref(null)
const targetDirectoryDialogVisible = ref(false)
const settings = reactive({
  targetLibraryId: '',
  targetSubdir: '',
})
const previewChipDragState = reactive({
  active: false,
  pointerId: null,
  startX: 0,
  startScrollLeft: 0,
  moved: false,
  suppressClick: false,
})
let previewScrollRafId = 0
let previewResizeObserver = null

const targetLibraries = computed(() => (Array.isArray(props.libraries) ? props.libraries : []).filter(item => item?.type === 'synology_filestation' && item?.enabled !== false))
const selectedTargetLibrary = computed(() => targetLibraries.value.find(item => item.id === settings.targetLibraryId) || null)
const inventoryLabel = computed(() => selectedTargetLibrary.value?.name || '选择目标库存')
const resolvedTargetRoot = computed(() => {
  const library = selectedTargetLibrary.value
  const base = String(library?.root_path || library?.path || library?.synology?.root_path || '').replace(/\\/g, '/')
  const prefix = String(settings.targetSubdir || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  if (!base) return ''
  return prefix ? `${base}/${prefix}`.replace(/\/+/g, '/') : base
})
const uploadCircleName = computed(() => String(props.circleName || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, ''))
const resolvedUploadRoot = computed(() => {
  const root = resolvedTargetRoot.value
  if (!root) return ''
  return uploadCircleName.value ? `${root}/${uploadCircleName.value}`.replace(/\/+/g, '/') : root
})
const selectedGroupCount = computed(() => {
  previewTreeVersion.value
  return previewGroups.value.filter(g => isGroupAllSelected(g) || isGroupPartiallySelected(g)).length
})
const selectedTotalBytes = computed(() => {
  previewTreeVersion.value
  return previewGroups.value.reduce((sum, group) => sum + Number(group.selected_size_bytes || 0), 0)
})
const selectedFileCount = computed(() => {
  previewTreeVersion.value
  return previewGroups.value.reduce((sum, group) => sum + Number(group.selected_resource_count || 0), 0)
})
const previewResourceCount = computed(() => {
  previewTreeVersion.value
  return previewGroups.value.reduce((sum, group) => sum + Number(group.total_resource_count || group.selectable_resources?.length || 0), 0)
})

const previewFileTypeChips = computed(() => {
  previewTreeVersion.value
  const typeOrder = new Map([
    ['.wav', 0], ['.flac', 1], ['.mp3', 2], ['.m4a', 3], ['.ogg', 4], ['.aac', 5], ['.wma', 6],
    ['.pdf', 20], ['.txt', 21], ['.cue', 22], ['.json', 23],
    ['.jpg', 30], ['.jpeg', 31], ['.png', 32], ['.webp', 33], ['.gif', 34], ['.bmp', 35],
    ['.srt', 40], ['.ass', 41], ['.ssa', 42], ['.vtt', 43], ['.lrc', 44], ['__no_ext__', 99],
  ])
  const groups = new Map()
  previewGroups.value.forEach((group) => {
    Object.values(group?.type_stats || {}).forEach((stat) => {
      const current = groups.get(stat.key) || { key: stat.key, label: stat.label, total: 0, selected: 0 }
      current.total += Number(stat.total || 0)
      current.selected += Number(stat.selected || 0)
      groups.set(stat.key, current)
    })
  })
  return [...groups.values()]
    .map((item) => ({ ...item, state: item.selected === 0 ? 'none' : (item.selected === item.total ? 'all' : 'partial') }))
    .sort((left, right) => {
      const leftOrder = typeOrder.has(left.key) ? typeOrder.get(left.key) : 80
      const rightOrder = typeOrder.has(right.key) ? typeOrder.get(right.key) : 80
      if (leftOrder !== rightOrder) return leftOrder - rightOrder
      return left.label.localeCompare(right.label, 'zh-CN')
    })
})

const allPreviewSelectionState = computed(() => {
  previewTreeVersion.value
  const total = previewResourceCount.value
  if (!total) return 'none'
  const selected = selectedFileCount.value
  if (selected === 0) return 'none'
  if (selected === total) return 'all'
  return 'partial'
})

const isAllExpanded = computed(() => {
  previewTreeVersion.value
  if (!previewGroups.value.length) return false
  return previewGroups.value.every(group => group.rootExpanded !== false)
})

const previewFlatRows = computed(() => {
  previewTreeVersion.value
  const rows = []
  previewGroups.value.forEach((group) => {
    rows.push({ id: `${group.id}::header`, kind: 'group', group })
    if (group.rootExpanded !== false) {
      group.flatRows.forEach(row => {
        rows.push({ id: row.id, kind: 'row', group, row })
      })
    }
  })
  return rows
})
const previewUseVirtual = computed(() => previewFlatRows.value.length > PREVIEW_VIRTUAL_THRESHOLD)
const previewVirtualRange = computed(() => {
  const total = previewFlatRows.value.length
  if (!previewUseVirtual.value) return { start: 0, end: total }
  const viewport = Math.max(previewViewportHeight.value || 420, PREVIEW_ROW_HEIGHT)
  const start = Math.max(0, Math.floor(previewScrollTop.value / PREVIEW_ROW_HEIGHT) - PREVIEW_OVERSCAN)
  const visibleCount = Math.ceil(viewport / PREVIEW_ROW_HEIGHT) + PREVIEW_OVERSCAN * 2
  return { start, end: Math.min(total, start + visibleCount) }
})
const previewVisibleRows = computed(() => {
  const { start, end } = previewVirtualRange.value
  return previewFlatRows.value.slice(start, end)
})
const previewVirtualTopPadding = computed(() => previewUseVirtual.value ? previewVirtualRange.value.start * PREVIEW_ROW_HEIGHT : 0)
const previewVirtualBottomPadding = computed(() => previewUseVirtual.value ? Math.max(0, (previewFlatRows.value.length - previewVirtualRange.value.end) * PREVIEW_ROW_HEIGHT) : 0)

function collectAllDirIds(nodes) {
  const ids = []
  for (const node of nodes || []) {
    if (node.type === 'dir') {
      ids.push(node.id)
      ids.push(...collectAllDirIds(node.children))
    }
  }
  return ids
}

function toggleExpandAll() {
  const nextState = !isAllExpanded.value
  previewGroups.value.forEach(group => {
    group.rootExpanded = nextState
    if (nextState) {
      group.expandedIds = new Set(collectAllDirIds(group.tree))
    } else {
      group.expandedIds = new Set()
    }
    refreshGroupFlatRows(group)
  })
  bumpPreviewTreeVersion()
}
const targetFreeSpaceBytes = computed(() => {
  const explicitBytes = Number(storageInfo.value?.free_size_bytes || 0)
  if (Number.isFinite(explicitBytes) && explicitBytes > 0) return explicitBytes
  const freeSpaceGb = Number(selectedTargetLibrary.value?.health?.free_space_gb)
  return Number.isFinite(freeSpaceGb) && freeSpaceGb > 0 ? freeSpaceGb * (1024 ** 3) : 0
})
const remainingSpaceText = computed(() => targetFreeSpaceBytes.value > 0 ? formatSize(targetFreeSpaceBytes.value) : '暂不可用')
const estimatedRemainingSpaceText = computed(() => {
  if (targetFreeSpaceBytes.value <= 0) return ''
  return formatSize(Math.max(0, targetFreeSpaceBytes.value - selectedTotalBytes.value))
})
const selectedUploadGroups = computed(() => {
  previewTreeVersion.value
  return previewGroups.value.filter(group => isGroupAllSelected(group) || isGroupPartiallySelected(group))
})
const targetDirectoryPreview = computed(() => resolvedUploadRoot.value || '')
const targetSubdirLabel = computed(() => {
  if (!settings.targetLibraryId) return '请先选择目标库存'
  const value = String(settings.targetSubdir || '').trim()
  return value || '库存根目录'
})
const targetSubdirHint = computed(() => {
  if (!settings.targetLibraryId) return '请先选择目标库存'
  const subdir = String(settings.targetSubdir || '').trim()
  if (!subdir) return '点击选择库存内子目录，默认上传到库存根目录'
  return `当前指定子目录：${subdir}`
})
const selectedFolderPreview = computed(() => {
  const groups = selectedUploadGroups.value
  if (!groups.length) return ''
  if (groups.length === 1) return groups[0].name || '-'
  return `${groups.length} 个已选目录，各自保留原目录名`
})
const finalPathPreview = computed(() => {
  const root = resolvedUploadRoot.value
  if (!root) return ''
  const selectedGroups = selectedUploadGroups.value
  if (selectedGroups.length === 1) return `${root}/${selectedGroups[0].name}`.replace(/\/+/g, '/')
  if (selectedGroups.length > 1) return `${root}/{所选目录名}`.replace(/\/+/g, '/')
  return root
})

watch(() => props.visible, async (visible) => {
  if (!visible) {
    previewLoading.value = false
    teardownPreviewTreeScrollObserver()
    return
  }
  settings.targetLibraryId = props.initialTargetLibraryId || settings.targetLibraryId || targetLibraries.value[0]?.id || ''
  settings.targetSubdir = props.initialTargetSubdir || ''
  previewGroups.value = []
  bumpPreviewTreeVersion()
  resetPreviewTreeScroll()
  previewLoading.value = true
  try {
    await Promise.all([
      loadStorageInfo(),
      loadPreviewGroups(),
    ])
  } finally {
    previewLoading.value = false
    await nextTick()
    setupPreviewTreeScrollObserver()
    resetPreviewTreeScroll()
  }
}, { immediate: true })

watch(() => props.libraries, () => {
  if (!settings.targetLibraryId) {
    settings.targetLibraryId = props.initialTargetLibraryId || targetLibraries.value[0]?.id || ''
  }
}, { deep: true, immediate: true })

watch(() => settings.targetLibraryId, async (next, prev) => {
  // 切换目标库存时清空已选子目录，避免把旧库下的相对路径残留到新库
  if (prev && next && next !== prev) {
    settings.targetSubdir = ''
  }
  await loadStorageInfo()
})

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function toggleSelectMenu(menu) {
  openSelect.value = openSelect.value === menu ? null : menu
}

function chooseOption(menu, value) {
  if (menu === 'inventory') settings.targetLibraryId = value
  else settings.targetSubdir = value
  openSelect.value = null
}

function openTargetDirectoryPicker() {
  if (!settings.targetLibraryId) {
    ElMessage.warning('请先选择目标库存')
    return
  }
  openSelect.value = null
  targetDirectoryDialogVisible.value = true
}

function clearTargetSubdir() {
  settings.targetSubdir = ''
}

function handleTargetDirectorySubmit(payload) {
  if (!payload) return
  const rel = String(payload.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  settings.targetSubdir = rel
  targetDirectoryDialogVisible.value = false
}

function handleDocumentClick(event) {
  if (!selectRoot.value?.contains(event.target)) {
    openSelect.value = null
  }
}

function onPreviewChipPointerDown(event) {
  if (event?.button !== undefined && event.button !== 0) return
  const element = previewChipScrollRef.value
  if (!element) return
  const startedOnButton = Boolean(event.target?.closest?.('button'))
  previewChipDragState.active = true
  previewChipDragState.pointerId = event.pointerId
  previewChipDragState.startX = event.clientX
  previewChipDragState.startScrollLeft = element.scrollLeft
  previewChipDragState.moved = false
  previewChipDragState.suppressClick = false
  if (!startedOnButton) element.setPointerCapture?.(event.pointerId)
}

function onPreviewChipPointerMove(event) {
  if (!previewChipDragState.active) return
  const element = previewChipScrollRef.value
  if (!element) return
  const deltaX = Number(event.clientX || 0) - Number(previewChipDragState.startX || 0)
  if (Math.abs(deltaX) > 4) {
    previewChipDragState.moved = true
    previewChipDragState.suppressClick = true
    event.preventDefault?.()
  }
  element.scrollLeft = Number(previewChipDragState.startScrollLeft || 0) - deltaX
}

function finishPreviewChipDrag(event) {
  const element = previewChipScrollRef.value
  if (element && previewChipDragState.pointerId !== null && element.hasPointerCapture?.(previewChipDragState.pointerId)) {
    element.releasePointerCapture?.(previewChipDragState.pointerId)
  }
  const moved = previewChipDragState.moved
  previewChipDragState.active = false
  previewChipDragState.pointerId = null
  previewChipDragState.moved = false
  if (moved) {
    previewChipDragState.suppressClick = true
    setTimeout(() => {
      previewChipDragState.suppressClick = false
    }, 120)
    event?.preventDefault?.()
  }
}

function onPreviewChipPointerUp(event) {
  finishPreviewChipDrag(event)
}

function onPreviewChipPointerCancel(event) {
  finishPreviewChipDrag(event)
}

function onPreviewChipWheel(event) {
  const element = previewChipScrollRef.value
  if (!element) return
  const delta = Math.abs(event.deltaX || 0) > Math.abs(event.deltaY || 0) ? event.deltaX : event.deltaY
  if (!delta) return
  element.scrollLeft += delta
  event.preventDefault?.()
}

function onPreviewChipClickCapture(event) {
  if (!previewChipDragState.suppressClick) return
  previewChipDragState.suppressClick = false
  event.preventDefault?.()
  event.stopPropagation?.()
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  teardownPreviewTreeScrollObserver()
})

function bumpPreviewTreeVersion() {
  previewTreeVersion.value += 1
}

function syncPreviewTreeViewport() {
  const element = treeScrollRef.value
  previewViewportHeight.value = element ? Math.max(Number(element.clientHeight || 0), 180) : 420
}

function setupPreviewTreeScrollObserver() {
  teardownPreviewTreeScrollObserver()
  const element = treeScrollRef.value
  if (!element || typeof ResizeObserver === 'undefined') {
    syncPreviewTreeViewport()
    return
  }
  previewResizeObserver = new ResizeObserver(syncPreviewTreeViewport)
  previewResizeObserver.observe(element)
  syncPreviewTreeViewport()
}

function teardownPreviewTreeScrollObserver() {
  if (previewScrollRafId) {
    cancelAnimationFrame(previewScrollRafId)
    previewScrollRafId = 0
  }
  if (previewResizeObserver) {
    previewResizeObserver.disconnect()
    previewResizeObserver = null
  }
}

function resetPreviewTreeScroll() {
  previewScrollTop.value = 0
  nextTick(() => {
    const element = treeScrollRef.value
    if (!element) return
    element.scrollTop = 0
    syncPreviewTreeViewport()
  })
}

function onPreviewTreeScroll(event) {
  const target = event?.target
  if (!target) return
  const nextScrollTop = Number(target.scrollTop || 0)
  const nextViewportHeight = Math.max(Number(target.clientHeight || 0), 180)
  if (previewScrollRafId) cancelAnimationFrame(previewScrollRafId)
  previewScrollRafId = requestAnimationFrame(() => {
    previewScrollTop.value = nextScrollTop
    previewViewportHeight.value = nextViewportHeight
    previewScrollRafId = 0
  })
}

async function loadPreviewGroups() {
  const sourceItems = (Array.isArray(props.sourceItems) ? props.sourceItems : []).filter(item => item?.path)
  if (!sourceItems.length) {
    previewGroups.value = []
    bumpPreviewTreeVersion()
    return
  }
  try {
    const groups = await Promise.all(sourceItems.map(async (item, index) => {
      const path = String(item.path || '').trim()
      const name = String(item.name || getFileName(path) || `项目 ${index + 1}`).trim()
      const isDirectory = item.is_directory !== false
      const groupId = `group:${index}:${path}`

      // 单文件场景：不调子项 list 接口，直接构造一个“只含自身”的 group
      if (!isDirectory) {
        const fileResource = {
          name,
          path,
          relative_path: name,
          size: Number(item.size || 0),
          type_key: getPreviewFileTypeKey(item),
          type_label: getPreviewFileTypeLabel(item),
          selected: true,
        }
        const tree = [{
          id: `${groupId}::file:${path}`,
          name,
          type: 'file',
          resource: fileResource,
          size_bytes: Number(item.size || 0),
          resolved_path: path,
        }]
        const group = {
          id: groupId,
          name,
          path,
          is_file: true,
          selectable_resources: [fileResource],
          rootExpanded: false,
          tree,
          nodeById: new Map(),
          type_stats: {},
          total_resource_count: 1,
          expandedIds: new Set(),
          flatRows: [],
        }
        initializeGroupTree(group)
        return group
      }

      const data = props.sourceLibraryId
        ? await libraryApi.browserFolderContents(props.sourceLibraryId, path)
        : await libraryApi.folderContents(path)
      const items = Array.isArray(data?.items) ? data.items : []
      const resources = items.map(item => ({
        ...item,
        type_key: getPreviewFileTypeKey(item),
        type_label: getPreviewFileTypeLabel(item),
        selected: true,
      }))
      const tree = buildTree(resources, path, groupId)
      const group = {
        id: groupId,
        name,
        path,
        is_file: false,
        selectable_resources: resources,
        rootExpanded: true,
        tree,
        nodeById: new Map(),
        type_stats: {},
        total_resource_count: resources.length,
        expandedIds: new Set(),
        flatRows: [],
      }
      initializeGroupTree(group)
      return group
    }))
    previewGroups.value = groups
    bumpPreviewTreeVersion()
  } catch (error) {
    previewGroups.value = []
    bumpPreviewTreeVersion()
    ElMessage.error(error?.response?.data?.detail || error?.message || '生成上传预览失败')
  }
}

async function loadStorageInfo() {
  storageInfo.value = null
  const libraryId = String(settings.targetLibraryId || '').trim()
  if (!libraryId) return
  try {
    storageInfo.value = await libraryApi.getStorageInfo(libraryId)
  } catch (_) {
    storageInfo.value = null
  }
}

function toggleGroupExpand(group) {
  group.rootExpanded = group.rootExpanded === false
  bumpPreviewTreeVersion()
}

function toggleExpand(group, row) {
  if (row?.type !== 'dir') return
  const next = new Set(group.expandedIds)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  group.expandedIds = next
  refreshGroupFlatRows(group)
  bumpPreviewTreeVersion()
}

function emitSubmit() {
  const selectedPaths = previewGroups.value
    .flatMap(group => collectSubmitPaths(group))
    .filter(Boolean)
  if (!selectedPaths.length) {
    ElMessage.warning('请选择要上传的目录')
    return
  }
  if (!settings.targetLibraryId) {
    ElMessage.warning('请选择目标库存')
    return
  }
  emit('submit', {
    source_library_id: props.sourceLibraryId,
    source_base_path: '',
    selected_paths: selectedPaths,
    target_library_id: settings.targetLibraryId,
    target_subdir: settings.targetSubdir || '',
  })
}

function buildTree(resources, basePath, groupId) {
  const root = []
  const dirMap = new Map()

  for (const item of resources) {
    const parts = String(item.relative_path || item.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let path = ''

    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `${groupId}::dir:${path}`
      if (!dirMap.has(key)) {
        const node = {
          id: key,
          name: parts[index],
          type: 'dir',
          relative_path: path,
          resolved_path: joinFolderPath(basePath, path),
          size_bytes: 0,
          selected_size_bytes: 0,
          leaf_count: 0,
          selected_count: 0,
          parentId: index === 0 ? '' : `${groupId}::dir:${parts.slice(0, index).join('/')}`,
          children: [],
        }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }

    children.push({
      id: `${groupId}::file:${item.path || item.relative_path || item.name}`,
      name: parts[parts.length - 1],
      type: 'file',
      resource: item,
      size_bytes: Number(item.size || 0),
      selected_size_bytes: item.selected ? Number(item.size || 0) : 0,
      leaf_count: 1,
      selected_count: item.selected ? 1 : 0,
      parentId: parts.length > 1 ? `${groupId}::dir:${parts.slice(0, -1).join('/')}` : '',
      resolved_path: item.path,
    })
  }

  return root
}

function flattenTree(nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    node.depth = depth
    result.push(node)
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

function initializeGroupTree(group) {
  group.nodeById = new Map()
  group.type_stats = {}
  group.selectable_resources.forEach((item) => {
    const key = item.type_key || getPreviewFileTypeKey(item)
    const label = item.type_label || getPreviewFileTypeLabel(item)
    item.type_key = key
    item.type_label = label
    const stat = group.type_stats[key] || { key, label, total: 0, selected: 0 }
    stat.total += 1
    if (item.selected) stat.selected += 1
    group.type_stats[key] = stat
  })
  recomputeTreeSelection(group)
  group.flatRows = flattenTree(group.tree || [], 0, group.expandedIds || new Set())
}

function recomputeTreeSelection(group) {
  const walk = (node) => {
    group.nodeById.set(node.id, node)
    if (node.type === 'file') {
      const size = Number(node.resource?.size || node.size_bytes || 0)
      node.size_bytes = size
      node.leaf_count = 1
      node.selected_count = node.resource?.selected ? 1 : 0
      node.selected_size_bytes = node.resource?.selected ? size : 0
      if (node.resource) node.resource.node_id = node.id
      return {
        total: 1,
        selected: node.selected_count,
        size,
        selectedSize: node.selected_size_bytes,
      }
    }
    const totals = (node.children || []).reduce((acc, child) => {
      const current = walk(child)
      acc.total += current.total
      acc.selected += current.selected
      acc.size += current.size
      acc.selectedSize += current.selectedSize
      return acc
    }, { total: 0, selected: 0, size: 0, selectedSize: 0 })
    node.leaf_count = totals.total
    node.selected_count = totals.selected
    node.size_bytes = totals.size
    node.selected_size_bytes = totals.selectedSize
    return totals
  }
  group.nodeById = new Map()
  const totals = (group.tree || []).reduce((acc, node) => {
    const current = walk(node)
    acc.total += current.total
    acc.selected += current.selected
    acc.size += current.size
    acc.selectedSize += current.selectedSize
    return acc
  }, { total: 0, selected: 0, size: 0, selectedSize: 0 })
  group.total_resource_count = totals.total
  group.total_size_bytes = totals.size
  group.selected_resource_count = totals.selected
  group.selected_size_bytes = totals.selectedSize
}

function setSubtreeSelection(group, node, nextSelected) {
  if (!node) return { count: 0, size: 0 }
  if (node.type === 'file') {
    const wasSelected = Boolean(node.resource?.selected)
    if (wasSelected === nextSelected) return { count: 0, size: 0 }
    const size = Number(node.size_bytes || node.resource?.size || 0)
    node.resource.selected = nextSelected
    node.selected_count = nextSelected ? 1 : 0
    node.selected_size_bytes = nextSelected ? size : 0
    const stat = group.type_stats[node.resource.type_key]
    if (stat) stat.selected += nextSelected ? 1 : -1
    return { count: nextSelected ? 1 : -1, size: nextSelected ? size : -size }
  }
  const beforeCount = Number(node.selected_count || 0)
  const beforeSize = Number(node.selected_size_bytes || 0)
  ;(node.children || []).forEach(child => setSubtreeSelection(group, child, nextSelected))
  node.selected_count = nextSelected ? Number(node.leaf_count || 0) : 0
  node.selected_size_bytes = nextSelected ? Number(node.size_bytes || 0) : 0
  return {
    count: node.selected_count - beforeCount,
    size: node.selected_size_bytes - beforeSize,
  }
}

function applySelectionDeltaToAncestors(group, node, delta) {
  let parentId = node?.parentId || ''
  while (parentId) {
    const parent = group.nodeById.get(parentId)
    if (!parent) break
    parent.selected_count = Math.max(0, Math.min(Number(parent.leaf_count || 0), Number(parent.selected_count || 0) + delta.count))
    parent.selected_size_bytes = Math.max(0, Math.min(Number(parent.size_bytes || 0), Number(parent.selected_size_bytes || 0) + delta.size))
    parentId = parent.parentId || ''
  }
}

function updateGroupStatsByDelta(group, delta) {
  group.selected_resource_count = Math.max(0, Math.min(Number(group.total_resource_count || 0), Number(group.selected_resource_count || 0) + delta.count))
  group.selected_size_bytes = Math.max(0, Math.min(Number(group.total_size_bytes || 0), Number(group.selected_size_bytes || 0) + delta.size))
}

function refreshGroupFlatRows(group) {
  group.flatRows = flattenTree(group.tree || [], 0, group.expandedIds || new Set())
}

function refreshPlanTree(group) {
  recomputeTreeSelection(group)
  refreshGroupFlatRows(group)
}

function isGroupAllSelected(group) {
  const total = Number(group?.total_resource_count || group?.selectable_resources?.length || 0)
  return total > 0 && Number(group?.selected_resource_count || 0) === total
}

function isGroupPartiallySelected(group) {
  const total = Number(group?.total_resource_count || group?.selectable_resources?.length || 0)
  const checkedCount = Number(group?.selected_resource_count || 0)
  return checkedCount > 0 && checkedCount < total
}

function isTreeNodeChecked(row) {
  const total = Number(row?.leaf_count || 0)
  return total > 0 && Number(row?.selected_count || 0) === total
}

function isTreeNodePartiallySelected(row) {
  const total = Number(row?.leaf_count || 0)
  const checkedCount = Number(row?.selected_count || 0)
  return checkedCount > 0 && checkedCount < total
}

function toggleGroupAll(group) {
  const next = !isGroupAllSelected(group)
  group.selectable_resources.forEach(item => {
    item.selected = next
  })
  Object.values(group.type_stats || {}).forEach(stat => {
    stat.selected = next ? Number(stat.total || 0) : 0
  })
  refreshPlanTree(group)
  bumpPreviewTreeVersion()
}

function updateResourceSelection(group, row, nextSelected) {
  const delta = setSubtreeSelection(group, row, nextSelected)
  if (!delta.count && !delta.size) return
  applySelectionDeltaToAncestors(group, row, delta)
  updateGroupStatsByDelta(group, delta)
  bumpPreviewTreeVersion()
}

function toggleTreeRow(group, row) {
  const nextSelected = isTreeNodePartiallySelected(row) ? true : !isTreeNodeChecked(row)
  updateResourceSelection(group, row, nextSelected)
}

function collectCheckedUploadPaths(nodes = [], ancestorChecked = false) {
  const paths = []
  for (const node of nodes || []) {
    const currentPath = String(node.resolved_path || '').trim()
    const checked = isTreeNodeChecked(node)
    if (!ancestorChecked && checked && currentPath) {
      paths.push(currentPath)
      continue
    }
    if (node.type === 'dir') {
      paths.push(...collectCheckedUploadPaths(node.children || [], ancestorChecked || checked))
    }
  }
  return paths
}

function normalizeSelectedPaths(paths = []) {
  const sorted = [...new Set(paths.map(item => String(item || '').trim()).filter(Boolean))]
    .sort((left, right) => left.length - right.length)
  const normalized = []
  for (const current of sorted) {
    const covered = normalized.some(existing => current === existing || current.startsWith(`${existing.replace(/\/+$/g, '')}/`))
    if (!covered) normalized.push(current)
  }
  return normalized
}

function collectSubmitPaths(group) {
  if (!group) return []
  if (isGroupAllSelected(group)) return group.path ? [group.path] : []
  if (!isGroupPartiallySelected(group)) return []
  return normalizeSelectedPaths(collectCheckedUploadPaths(group.tree || []))
}

function handleTreeRowClick(group, row) {
  if (!row) return
  if (row.type === 'dir') {
    toggleExpand(group, row)
    return
  }
  toggleTreeRow(group, row)
}

function getPreviewFileTypeKey(item) {
  const explicitExt = String(item?.file_ext || '').trim().toLowerCase()
  if (explicitExt) return explicitExt.startsWith('.') ? explicitExt : `.${explicitExt}`
  const sourceName = String(item?.relative_path || item?.name || '').trim().toLowerCase()
  const match = sourceName.match(/\.([^.\\/]+)$/)
  if (match?.[1]) return `.${match[1]}`
  return '__no_ext__'
}

function getPreviewFileTypeLabel(item) {
  const key = getPreviewFileTypeKey(item)
  return key === '__no_ext__' ? '无后缀' : key.replace(/^\./, '')
}

function toggleAllPreviewSelection() {
  const nextSelected = allPreviewSelectionState.value !== 'all'
  previewGroups.value.forEach(group => {
    group.selectable_resources.forEach(item => {
      item.selected = nextSelected
    })
    Object.values(group.type_stats || {}).forEach(stat => {
      stat.selected = nextSelected ? Number(stat.total || 0) : 0
    })
    refreshPlanTree(group)
  })
  bumpPreviewTreeVersion()
}

function togglePreviewFileType(chip) {
  const key = String(chip?.key || '').trim()
  if (!key) return
  const nextSelected = String(chip?.state || '') !== 'all'
  previewGroups.value.forEach(group => {
    let changed = false
    group.selectable_resources.forEach(item => {
      if ((item.type_key || getPreviewFileTypeKey(item)) === key && item.selected !== nextSelected) {
        item.selected = nextSelected
        changed = true
      }
    })
    const stat = group.type_stats?.[key]
    if (stat) stat.selected = nextSelected ? Number(stat.total || 0) : 0
    if (changed) refreshPlanTree(group)
  })
  bumpPreviewTreeVersion()
}

function getFileName(path) {
  return String(path || '').split(/[\\/]/).pop()
}

function getDisplayText(value) {
  const text = String(value || '')
  return text
    .replace(/\u0000/g, '')
    .replace(/\r/g, '')
    .trim()
}

function joinFolderPath(basePath, relativePath) {
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const relative = String(relativePath || '').replace(/^\/+|^\\+/, '')
  if (!base) return relative
  if (!relative) return base
  const separator = base.includes('\\') ? '\\' : '/'
  return `${base}${separator}${relative.replace(/\//g, separator)}`
}

// 全部走库存页共享 helper（8 类色盘 + dir 9 类），避免这里重复手写表决定。
// 详见 frontend/src/components/library/_libraryFileKind.js，与 Library.vue / LibrarySearchOverlay
// / ActivityRichBlock 使用同一套 kind 划分。
function normalizeGroupItem (group) {
  return { is_directory: !group?.is_file, name: group?.name || '' }
}

function normalizeRowItem (row) {
  return { is_directory: row?.type === 'dir', name: row?.name || '' }
}

function iconMetaForGroup (group) {
  return libraryEntryMetaFor(normalizeGroupItem(group))
}

function iconMetaForRow (row) {
  return libraryEntryMetaFor(normalizeRowItem(row))
}

function classifyGroupKind (group) {
  return classifyLibraryEntryKind(normalizeGroupItem(group))
}

function classifyRowKind (row) {
  return classifyLibraryEntryKind(normalizeRowItem(row))
}
</script>

<style scoped>
.dropdown-menu { backdrop-filter: blur(8px); }

.tabs-row {
  overflow: hidden;
}

.preview-chip-rail {
  position: relative;
  flex: 0 1 760px;
  width: min(760px, calc(100% - 112px));
  max-width: calc(100% - 112px);
  overflow: hidden;
}

.preview-chip-scroll {
  width: 100%;
  overflow-y: visible;
  padding: 2px 0 0;
  scrollbar-width: none;
  -ms-overflow-style: none;
  cursor: grab;
  scroll-behavior: smooth;
  touch-action: pan-y;
  user-select: none;
  overscroll-behavior-inline: contain;
}

.preview-chip-scroll.is-dragging {
  cursor: grabbing;
  scroll-behavior: auto;
}

.preview-chip-scroll .tab-chip {
  flex: 0 0 auto;
}

.restore-button {
  margin-left: auto;
}

.preview-chip-scroll::-webkit-scrollbar {
  display: none;
}
.preview-virtual-spacer {
  flex: 0 0 auto;
  pointer-events: none;
}
.tree-row-selected { background: rgba(15,23,42,.04); }
.field-input { transition: border-color .15s ease; }
.field-input:focus { border-color: rgba(17,24,39,.45); }
.picker-button { cursor: pointer; }
.picker-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: rgba(248,250,252,0.6);
}
.picker-button:not(:disabled):hover { border-color: rgba(17,24,39,0.32); }
.picker-clear { transition: background-color .15s ease, color .15s ease; }
.picker-clear:hover { background: rgba(15,23,42,0.08); }
.tree-checkbox { cursor: pointer; transition: border-color .15s ease, background-color .15s ease, transform .15s ease; }
.tree-checkbox:hover { transform: scale(1.04); }
/* 顶层颜色交给 inline :style（由 helper meta.color 赋值），这里只保留过渡动画。 */
.tree-icon { transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
/* lucide 默认 fill="none"，dir / archive 这些需要填充色的 kind 走 helper meta.fillIcon -> tree-icon-fill。 */
.tree-icon-fill { fill: currentColor; }
.tree-name,
.node-title-muted {
  font-family:
    "SF Pro Text",
    "SF Pro Rounded",
    "PingFang SC",
    "Hiragino Sans GB",
    "Hiragino Kaku Gothic ProN",
    "Yu Gothic UI",
    "Meiryo",
    "Microsoft YaHei",
    sans-serif;
}
.tree-name-partial { color: #111827; }
.node-title-muted {
  color: #94a3b8;
  font-weight: 500;
  margin-left: 8px;
}
/* .icon-folder 已废弃：颜色现在由 helper inline style 控制。 */
.preview-empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b; font-size: 14px; }
.tree-checkbox-on { background: #111827; color: #fff; border-color: #111827; }
.tree-checkbox-partial { background: #111827; color: #fff; border-color: #111827; }
.tree-checkbox-off { background: rgba(255,255,255,.7); border-color: rgba(15,23,42,.12); color: transparent; }
.tree-row:hover .tree-checkbox-off { border-color: rgba(15,23,42,.3); background: rgba(255,255,255,.92); }
.checkbox-minus { width: 10px; height: 2px; background: #fff; display: inline-block; border-radius: 999px; }
.expander-spacer { width: 21px; flex: 0 0 21px; }

@media (max-width: 640px) {
  .window {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    height: 100% !important;
    max-height: 100% !important;
    aspect-ratio: auto !important;
    border-radius: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
  }
  .window-header {
    position: relative;
    flex: 0 0 auto;
    min-width: 0;
    padding: 14px 52px 10px 16px !important;
    align-items: flex-start !important;
  }
  .close-button {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 34px !important;
    height: 34px !important;
  }
  .window-header .title {
    font-size: 18px !important;
    line-height: 1.25;
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .tabs-row {
    flex: 0 0 auto;
    width: 100%;
    min-width: 0;
    padding: 4px 12px 8px !important;
    align-items: flex-start;
    overflow: hidden;
  }
  .preview-chip-rail {
    flex: 1 1 auto;
    width: auto;
    max-width: none;
  }
  .preview-chip-scroll {
    min-width: 0;
    flex: 1 1 auto;
  }
  .restore-button {
    margin-left: 0 !important;
    flex: 0 0 auto;
  }
  .content-grid {
    flex-direction: column !important;
    gap: 10px !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
    width: 100%;
    min-width: 0;
    padding: 0 12px 10px !important;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
  }
  .left-column {
    width: 100% !important;
    flex: 0 0 auto;
    min-width: 0;
    gap: 10px !important;
  }
  .settings-card {
    flex: 0 0 auto !important;
    max-height: none;
    padding: 12px !important;
    overflow: visible;
  }
  .section-head h2 {
    font-size: 17px;
    line-height: 1.25;
  }
  .section-head p {
    font-size: 12px;
    line-height: 1.45;
  }
  .select-grid {
    grid-template-columns: 1fr !important;
    gap: 10px !important;
  }
  .target-path,
  .summary-stack {
    overflow-wrap: anywhere;
  }
  .tree-panel {
    flex: 1 0 260px;
    min-height: 220px;
    max-height: 42dvh;
    border-radius: 14px !important;
  }
  .tree-scroll {
    padding: 10px !important;
  }
  .tree-row {
    align-items: flex-start;
    gap: 8px;
  }
  .tree-size {
    display: none !important;
  }
  .node-rjcode,
  .node-title-muted {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .footer-row {
    flex: 0 0 auto;
    flex-direction: column;
    align-items: stretch !important;
    gap: 10px;
    padding: 10px 12px calc(12px + env(safe-area-inset-bottom)) !important;
    border-top: 1px solid rgba(226, 232, 240, 0.82);
    background: rgba(255, 255, 255, 0.94);
  }
  .summary {
    font-size: 12px !important;
    line-height: 1.45;
    overflow-wrap: anywhere;
  }
  .footer-actions {
    display: grid !important;
    grid-template-columns: 1fr;
    width: 100%;
    gap: 8px !important;
  }
  .primary-cta,
  .secondary-cta {
    width: 100%;
    height: 42px !important;
  }
}
</style>
