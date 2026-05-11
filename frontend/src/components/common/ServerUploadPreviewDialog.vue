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

      <div class="tabs-row px-8 pt-1 pb-3 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
        <div class="preview-chip-scroll flex min-w-0 items-center gap-1.5 overflow-x-auto no-scrollbar py-0">
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
        <button type="button" class="tab-chip tab-chip-idle restore-button ml-auto px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] border" @click="toggleExpandAll">{{ isAllExpanded ? '全部收起' : '全部展开' }}</button>
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
          <div class="tree-scroll flex-1 p-4 overflow-auto no-scrollbar">
            <div v-if="!previewGroups.length" class="preview-empty">当前没有可上传的目录</div>
            <div v-else class="tree-list space-y-1">
              <template v-for="group in previewGroups" :key="group.id">
                <div class="tree-node">
                  <div
                    class="tree-row plan-node-header flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="isGroupAllSelected(group) || isGroupPartiallySelected(group) ? 'tree-row-selected' : ''"
                    @click="toggleGroupExpand(group)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="toggleGroupExpand(group)"
                      >
                        <ChevronDown v-if="group.rootExpanded !== false" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="isGroupAllSelected(group) ? 'tree-checkbox-on' : (isGroupPartiallySelected(group) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="toggleGroupAll(group)"
                      >
                        <Check v-if="isGroupAllSelected(group)" :size="14" />
                        <span v-else-if="isGroupPartiallySelected(group)" class="checkbox-minus" />
                      </button>
                      <component
                        :is="iconMetaForGroup(group).icon"
                        :size="20"
                        :stroke-width="2.2"
                        class="tree-icon"
                        :class="[`tree-icon-kind-${classifyGroupKind(group)}`, { 'tree-icon-fill': iconMetaForGroup(group).fillIcon }]"
                        :style="{ color: iconMetaForGroup(group).color }"
                      />
                      <span class="tree-name node-rjcode text-sm text-slate-800 truncate font-medium">
                        {{ getDisplayText(group.name) }}
                        <span class="node-title-muted">{{ getDisplayText(group.path) }}</span>
                      </span>
                    </div>
                    <span class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(group.total_size_bytes) }}</span>
                  </div>
                </div>

                <div v-for="row in (group.rootExpanded === false ? [] : group.flatRows)" :key="row.id" class="tree-node">
                  <div
                    class="tree-row flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="row.checked || row.indeterminate ? 'tree-row-selected' : ''"
                    :style="{ paddingLeft: `${(row.depth + 1) * 16 + 16}px` }"
                    @click="handleTreeRowClick(group, row)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        v-if="row.type === 'dir'"
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="toggleExpand(group, row)"
                      >
                        <ChevronDown v-if="group.expandedIds.has(row.id)" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <span v-else class="expander-spacer" />
                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="row.checked ? 'tree-checkbox-on' : (row.indeterminate ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="toggleTreeRow(group, row)"
                      >
                        <Check v-if="row.checked" :size="14" />
                        <span v-else-if="row.indeterminate" class="checkbox-minus" />
                      </button>
                      <component
                        :is="iconMetaForRow(row).icon"
                        :size="20"
                        :stroke-width="2.2"
                        class="tree-icon"
                        :class="[`tree-icon-kind-${classifyRowKind(row)}`, { 'tree-icon-fill': iconMetaForRow(row).fillIcon }]"
                        :style="{ color: iconMetaForRow(row).color }"
                      />
                      <span
                        class="tree-name text-sm truncate font-medium"
                        :class="row.indeterminate ? 'tree-name-partial' : 'text-slate-800'"
                      >{{ getDisplayText(row.name) }}</span>
                    </div>
                    <span v-if="row.size_bytes" class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(row.size_bytes) }}</span>
                  </div>
                </div>
              </template>
            </div>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, toRaw, watch } from 'vue'
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
  sourceItems: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  initialTargetLibraryId: { type: String, default: '' },
  initialTargetSubdir: { type: String, default: '' },
})

const emit = defineEmits(['update:visible', 'submit'])

const previewLoading = ref(false)
const previewGroups = ref([])
const openSelect = ref(null)
const selectRoot = ref(null)
const storageInfo = ref(null)
const targetDirectoryDialogVisible = ref(false)
const settings = reactive({
  targetLibraryId: '',
  targetSubdir: '',
})

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
const selectedGroupCount = computed(() => previewGroups.value.filter(g => isGroupAllSelected(g) || isGroupPartiallySelected(g)).length)
const selectedTotalBytes = computed(() => previewGroups.value.reduce((sum, group) => sum + Number(group.selected_size_bytes || 0), 0))
const selectedFileCount = computed(() => previewGroups.value.reduce((sum, group) => sum + Number(group.selected_resource_count || 0), 0))
const previewSelectableResources = computed(() => previewGroups.value.flatMap(group => Array.isArray(group?.selectable_resources) ? group.selectable_resources : []))

const previewFileTypeChips = computed(() => {
  const typeOrder = new Map([
    ['.wav', 0], ['.flac', 1], ['.mp3', 2], ['.m4a', 3], ['.ogg', 4], ['.aac', 5], ['.wma', 6],
    ['.pdf', 20], ['.txt', 21], ['.cue', 22], ['.json', 23],
    ['.jpg', 30], ['.jpeg', 31], ['.png', 32], ['.webp', 33], ['.gif', 34], ['.bmp', 35],
    ['.srt', 40], ['.ass', 41], ['.ssa', 42], ['.vtt', 43], ['.lrc', 44], ['__no_ext__', 99],
  ])
  const groups = new Map()
  previewSelectableResources.value.forEach((item) => {
    const key = getPreviewFileTypeKey(item)
    const label = getPreviewFileTypeLabel(item)
    const current = groups.get(key) || { key, label, total: 0, selected: 0 }
    current.total += 1
    if (item?.selected) current.selected += 1
    groups.set(key, current)
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
  const total = previewSelectableResources.value.length
  if (!total) return 'none'
  const selected = previewSelectableResources.value.filter(item => item?.selected).length
  if (selected === 0) return 'none'
  if (selected === total) return 'all'
  return 'partial'
})

const isAllExpanded = computed(() => {
  if (!previewGroups.value.length) return false
  return previewGroups.value.every(group => group.rootExpanded !== false)
})

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
    refreshPlanTree(group)
  })
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
const selectedUploadGroups = computed(() => previewGroups.value.filter(group => isGroupAllSelected(group) || isGroupPartiallySelected(group)))
const targetDirectoryPreview = computed(() => resolvedTargetRoot.value || '')
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
  const root = resolvedTargetRoot.value
  if (!root) return ''
  const selectedGroups = selectedUploadGroups.value
  if (selectedGroups.length === 1) return `${root}/${selectedGroups[0].name}`.replace(/\/+/g, '/')
  if (selectedGroups.length > 1) return `${root}/{所选目录名}`.replace(/\/+/g, '/')
  return root
})

watch(() => props.visible, async (visible) => {
  if (!visible) {
    previewLoading.value = false
    return
  }
  settings.targetLibraryId = props.initialTargetLibraryId || settings.targetLibraryId || targetLibraries.value[0]?.id || ''
  settings.targetSubdir = props.initialTargetSubdir || ''
  previewGroups.value = []
  previewLoading.value = true
  try {
    await Promise.all([
      loadStorageInfo(),
      loadPreviewGroups(),
    ])
  } finally {
    previewLoading.value = false
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

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
})

async function loadPreviewGroups() {
  const sourceItems = (Array.isArray(props.sourceItems) ? props.sourceItems : []).filter(item => item?.path)
  if (!sourceItems.length) {
    previewGroups.value = []
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
          expandedIds: new Set(),
          flatRows: [],
        }
        refreshPlanTree(group)
        return group
      }

      const data = props.sourceLibraryId
        ? await libraryApi.browserFolderContents(props.sourceLibraryId, path)
        : await libraryApi.folderContents(path)
      const items = Array.isArray(data?.items) ? data.items : []
      const resources = items.map(item => ({ ...item, selected: true }))
      const tree = buildTree(resources, path, groupId)
      const expandedIds = new Set(collectDirectoryIds(tree))
      const group = {
        id: groupId,
        name,
        path,
        is_file: false,
        selectable_resources: resources,
        rootExpanded: true,
        tree,
        expandedIds,
        flatRows: [],
      }
      refreshPlanTree(group)
      return group
    }))
    previewGroups.value = groups
  } catch (error) {
    previewGroups.value = []
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
}

function toggleExpand(group, row) {
  if (row?.type !== 'dir') return
  const next = new Set(group.expandedIds)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  group.expandedIds = next
  group.flatRows = flattenTree(group.tree, 0, next)
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
  const sorted = [...resources].sort((a, b) => String(a.relative_path || '').localeCompare(String(b.relative_path || '')))

  for (const item of sorted) {
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
      resolved_path: item.path,
    })
  }

  return root
}

function flattenTree(nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

function collectLeafResources(node) {
  if (!node) return []
  if (node.type === 'file') return [node.resource]
  return (node.children || []).flatMap(child => collectLeafResources(child))
}

function annotateSelection(node) {
  if (node.type === 'file') {
    return { ...node, checked: Boolean(node.resource.selected), indeterminate: false }
  }
  const children = (node.children || []).map(annotateSelection)
  const leafResources = children.flatMap(child => child.type === 'file' ? [child.resource] : collectLeafResources(child))
  const checkedCount = leafResources.filter(item => item.selected).length
  return {
    ...node,
    children,
    size_bytes: children.reduce((sum, child) => sum + Number(child.size_bytes || 0), 0),
    checked: checkedCount > 0 && checkedCount === leafResources.length,
    indeterminate: checkedCount > 0 && checkedCount < leafResources.length
  }
}

function refreshPlanTree(group) {
  group.tree = (group.tree || []).map(annotateSelection)
  group.flatRows = flattenTree(group.tree, 0, group.expandedIds)
  group.total_size_bytes = group.selectable_resources.reduce((sum, item) => sum + Number(item.size || 0), 0)
  group.selected_resource_count = group.selectable_resources.filter(item => item.selected).length
  group.selected_size_bytes = group.selectable_resources.filter(item => item.selected).reduce((sum, item) => sum + Number(item.size || 0), 0)
}

function isGroupAllSelected(group) {
  return group.selectable_resources.length > 0 && group.selectable_resources.every(item => item.selected)
}

function isGroupPartiallySelected(group) {
  const checkedCount = group.selectable_resources.filter(item => item.selected).length
  return checkedCount > 0 && checkedCount < group.selectable_resources.length
}

function toggleGroupAll(group) {
  const next = !isGroupAllSelected(group)
  group.selectable_resources.forEach(item => {
    item.selected = next
  })
  refreshPlanTree(group)
}

function updateResourceSelection(group, row, nextSelected) {
  const leafResources = new Set(collectLeafResources(row).map(item => toRaw(item)))
  group.selectable_resources.forEach(item => {
    if (leafResources.has(toRaw(item))) item.selected = nextSelected
  })
  refreshPlanTree(group)
}

function toggleTreeRow(group, row) {
  const nextSelected = row.indeterminate ? true : !row.checked
  updateResourceSelection(group, row, nextSelected)
}

function collectCheckedDirectoryPaths(nodes = [], ancestorChecked = false) {
  const paths = []
  for (const node of nodes || []) {
    if (node.type !== 'dir') continue
    const currentPath = String(node.resolved_path || '').trim()
    if (!ancestorChecked && node.checked && currentPath) {
      paths.push(currentPath)
      continue
    }
    paths.push(...collectCheckedDirectoryPaths(node.children || [], ancestorChecked || Boolean(node.checked)))
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
  return normalizeSelectedPaths(collectCheckedDirectoryPaths(group.tree || []))
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
    refreshPlanTree(group)
  })
}

function togglePreviewFileType(chip) {
  const key = String(chip?.key || '').trim()
  if (!key) return
  const nextSelected = String(chip?.state || '') !== 'all'
  previewGroups.value.forEach(group => {
    group.selectable_resources.forEach(item => {
      if (getPreviewFileTypeKey(item) === key) item.selected = nextSelected
    })
    refreshPlanTree(group)
  })
}

function collectDirectoryIds(nodes = []) {
  const ids = []
  const walk = list => {
    for (const node of list || []) {
      if (node.type === 'dir') {
        ids.push(node.id)
        walk(node.children || [])
      }
    }
  }
  walk(nodes)
  return ids
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

.preview-chip-scroll {
  flex: 0 1 auto;
  max-width: 100%;
  overflow-y: visible;
  padding-top: 2px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.preview-chip-scroll::-webkit-scrollbar {
  display: none;
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
    overflow-x: auto;
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
