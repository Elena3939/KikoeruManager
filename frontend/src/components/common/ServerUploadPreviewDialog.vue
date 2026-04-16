<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal"
    align-center
    modal-class="custom-preview-overlay"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="previewLoading" class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden dialog-loading-overlay">
      <el-icon class="is-loading loader-icon"><Loading /></el-icon>
      <div class="loading-text">正在生成上传预览树...</div>
    </div>

    <div v-else class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
      <div class="window-header flex items-center justify-between px-8 py-6">
        <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">{{ title }}</h1>
        <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="emit('update:visible', false)">
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div class="tabs-row px-8 pt-1 pb-3 flex items-center justify-between gap-4">
        <div class="flex items-center gap-1.5 overflow-x-auto no-scrollbar flex-1 mask-edge-right">
          <button
            type="button"
            class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border"
            :class="allPreviewSelectionState === 'all' ? 'tab-chip-active' : (allPreviewSelectionState === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            @click="toggleAllPreviewSelection"
          >
            <span>全部</span>
          </button>
          <button
            v-for="chip in previewFileTypeChips"
            :key="chip.key"
            type="button"
            class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border"
            :class="chip.state === 'all' ? 'tab-chip-active' : (chip.state === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            @click="togglePreviewFileType(chip)"
          >
            <span>{{ chip.label }}</span>
          </button>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button type="button" class="tab-chip tab-chip-idle px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] border" @click="toggleExpandAll">{{ isAllExpanded ? '全部收起' : '全部展开' }}</button>
        </div>
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
                      <Folder :size="20" class="tree-icon icon-folder" />
                      <span class="tree-name node-rjcode text-sm text-slate-800 truncate font-medium">
                        {{ group.name }}
                        <span class="node-title-muted">{{ group.path }}</span>
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
                      <component :is="resolveTreeIcon(row, group)" :size="20" class="tree-icon" :class="row.type === 'dir' ? 'icon-folder' : getTreeRowIconClass(row)" />
                      <span class="tree-name text-sm text-slate-800 truncate font-medium">{{ row.name }}</span>
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
            <span v-if="starting"><el-icon class="is-loading" style="margin-right:6px"><Loading /></el-icon>处理中</span>
            <span v-else>开始上传</span>
          </button>
          <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="emit('update:visible', false)">取消</button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { Check, ChevronDown, ChevronRight, File as FileIcon, FileText, Folder, Music, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { libraryApi } from '../../api'

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
  if (!visible) return
  settings.targetLibraryId = props.initialTargetLibraryId || settings.targetLibraryId || targetLibraries.value[0]?.id || ''
  settings.targetSubdir = ''
  await loadStorageInfo()
  await loadPreviewGroups()
}, { immediate: true })

watch(() => props.libraries, () => {
  if (!settings.targetLibraryId) {
    settings.targetLibraryId = props.initialTargetLibraryId || targetLibraries.value[0]?.id || ''
  }
}, { deep: true, immediate: true })

watch(() => settings.targetLibraryId, async () => {
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
  if (!props.sourceLibraryId || !sourceItems.length) {
    previewGroups.value = []
    return
  }
  previewLoading.value = true
  try {
    const groups = await Promise.all(sourceItems.map(async (item, index) => {
      const path = String(item.path || '').trim()
      const name = String(item.name || getFileName(path) || `目录 ${index + 1}`).trim()
      const data = await libraryApi.browserFolderContents(props.sourceLibraryId, path)
      const items = Array.isArray(data?.items) ? data.items : []
      const resources = items.map(item => ({ ...item, selected: true }))
      const groupId = `group:${index}:${path}`
      const tree = buildTree(resources, path, groupId)
      const expandedIds = new Set(collectDirectoryIds(tree))
      const group = {
        id: groupId,
        name,
        path,
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
  } finally {
    previewLoading.value = false
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
    .filter(group => isGroupAllSelected(group) || isGroupPartiallySelected(group))
    .map(group => group.path)
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
  const targetPaths = new Set(collectLeafResources(row).map(item => item.relative_path || item.name))
  group.selectable_resources.forEach(item => {
    if (targetPaths.has(item.relative_path || item.name)) item.selected = nextSelected
  })
  refreshPlanTree(group)
}

function toggleTreeRow(group, row) {
  const nextSelected = row.indeterminate ? true : !row.checked
  updateResourceSelection(group, row, nextSelected)
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

function joinFolderPath(basePath, relativePath) {
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const relative = String(relativePath || '').replace(/^\/+|^\\+/, '')
  if (!base) return relative
  if (!relative) return base
  const separator = base.includes('\\') ? '\\' : '/'
  return `${base}${separator}${relative.replace(/\//g, separator)}`
}

function resolveTreeIcon(row, group) {
  if (row?.type === 'dir') {
    return group.expandedIds.has(row.id) ? Folder : Folder
  }
  const name = String(row?.name || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)) return Music
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return FileText
  return FileIcon
}

function getTreeRowIconClass(row) {
  if (row?.type === 'dir') return 'icon-folder'
  const resource = row?.resource || {}
  const ext = getPreviewFileTypeKey(resource)
  if (['.wav', '.flac'].includes(ext)) return 'icon-audio-blue'
  if (['.mp3', '.m4a', '.ogg', '.aac', '.wma'].includes(ext)) return 'icon-audio-purple'
  return 'icon-file'
}
</script>

<style scoped>
.custom-preview-modal :deep(.el-dialog__header) { display: none; }
.loader-icon { font-size: 28px; color: #64748b; }
.loading-text { margin-top: 12px; color: #334155; font-weight: 600; letter-spacing: .2px; }
.glass-shell { background: rgba(255,255,255,.7); backdrop-filter: blur(8px); border: 1px solid rgba(15,23,42,.06); }
.dropdown-menu { backdrop-filter: blur(8px); }
.tab-chip { transition: all .15s ease; color: #475569; }

.mask-edge-right {
  -webkit-mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
  mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
}

.tab-chip-active { background: #1e293b; border-color: #1e293b; color: #f8fafc; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16); }
.tab-chip-partial { background: #e2e8f0; border-color: #cbd5e1; color: #0f172a; }
.tab-chip-idle { background: rgba(255,255,255,.92); border-color: #cbd5e1; color: #475569; }
.tree-row-selected { background: rgba(15,23,42,.04); }
.primary-cta { background: #111827; transition: background-color .18s ease, box-shadow .18s ease, transform .18s ease; box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16); }
.primary-cta:hover:not(:disabled) { background: #0f172a; box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22); transform: translateY(-1px); }
.primary-cta:active:not(:disabled) { transform: translateY(0); }
.primary-cta:disabled { cursor: not-allowed; opacity: .55; box-shadow: none; }
.secondary-cta { background: rgba(17,24,39,.06); color: #334155; transition: background-color .18s ease, color .18s ease, transform .18s ease; }
.secondary-cta:hover { background: rgba(15,23,42,.1); color: #0f172a; transform: translateY(-1px); }
.field-input { transition: border-color .15s ease; }
.field-input:focus { border-color: rgba(17,24,39,.45); }
.tree-icon { color: #64748b; }
.node-title-muted { color: #94a3b8; font-weight: 500; margin-left: 8px; }
.icon-folder { color: #64748b; }
.preview-empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b; font-size: 14px; }
.tree-checkbox-on { background: #111827; color: #fff; border-color: #111827; }
.tree-checkbox-off { background: rgba(255,255,255,.7); border-color: rgba(15,23,42,.12); color: transparent; }
.expander-spacer { width: 21px; flex: 0 0 21px; }
</style>
