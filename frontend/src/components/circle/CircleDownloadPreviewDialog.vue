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
    <div v-if="loading" class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden dialog-loading-overlay">
      <AppLoadingAnimation label="正在分析资源结构并生成下载计划..." description="聚合资源分组、语言版本和推荐项" :size="168" :min-height="260" />
    </div>
    
    <div v-else class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
      <div class="window-header flex items-center justify-between px-8 py-6">
        <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">创建下载任务</h1>
        <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="emit('update:visible', false)">
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div class="tabs-row px-8 pt-1 pb-3 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
        <button
          type="button"
          class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
          :class="allPreviewSelectionState === 'all' ? 'tab-chip-active' : (allPreviewSelectionState === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
          @click="toggleAllPreviewSelection"
        >
          <span>全部</span>
          <span class="tab-count">{{ selectedFileCount }}/{{ previewSelectableResources.length }}</span>
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
          <span class="tab-count">{{ chip.selected }}/{{ chip.total }}</span>
        </button>
        <button type="button" class="tab-chip tab-chip-idle restore-button ml-auto px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] border" @click="resetRecommended">恢复推荐</button>
      </div>

      <div class="content-grid flex-1 flex gap-6 px-8 py-2 min-h-0">
        <div class="left-column w-[380px] flex flex-col gap-6">
          <section ref="selectRoot" class="glass-panel glass-card settings-card flex-1 rounded-2xl p-6 overflow-y-auto no-scrollbar">
            <div class="space-y-6">
              <section class="space-y-4">
                <div class="section-head space-y-1">
              <h2>落地设置</h2>
              <p>在地的设置，请置下临时下载的文件，并根据需要调整保存位置。</p>
                </div>

            <div class="field-group space-y-2">
              <label>下载临时目录</label>
              <input v-model="settings.downloadBasePath" type="text" class="field-input h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-sm text-slate-800 outline-none" placeholder="默认临时路径" />
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
                <label>库存内前缀目录</label>
                <div class="select-wrap relative">
                  <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" @click.stop="toggleSelectMenu('prefix')">
                    <span class="line-clamp-1 text-left" :class="settings.targetSubdir ? 'text-slate-800' : 'text-slate-400'">{{ prefixLabel || '按社团名自动归类' }}</span>
                    <ChevronDown :size="18" class="select-arrow size-4 text-slate-400" />
                  </button>

                  <div v-if="openSelect === 'prefix'" class="dropdown-panel dropdown-menu absolute z-50 mt-1 w-full min-w-36 origin-top rounded-lg bg-white/88 border border-white/80 text-slate-800 shadow-lg ring-1 ring-slate-200/80 p-1">
                    <button
                      type="button"
                      class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-1.5 text-sm transition-colors hover:bg-slate-100/80"
                      @click.stop="chooseOption('prefix', '')"
                    >
                      <span class="truncate">按社团名自动归类</span>
                      <span v-if="settings.targetSubdir === ''" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                        <Check :size="16" />
                      </span>
                    </button>
                    <button
                      v-for="option in targetSubdirOptions"
                      :key="option"
                      type="button"
                      class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-1.5 text-sm transition-colors hover:bg-slate-100/80"
                      @click.stop="chooseOption('prefix', option)"
                    >
                      <span class="truncate">{{ option }}</span>
                      <span v-if="settings.targetSubdir === option" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                        <Check :size="16" />
                      </span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
              </section>

              <section class="space-y-4">
                <div class="section-head compact-head">
              <h2>最终行为</h2>
                </div>

            <div class="action-buttons grid grid-cols-2 gap-3">
              <button 
                type="button" 
                class="soft-button interactive-button h-10 rounded-lg border border-slate-200/70 bg-white/55 text-sm font-medium text-slate-700" 
                :class="{'active': settings.classifyMode === 'circle'}"
                @click="settings.classifyMode = settings.classifyMode === 'circle' ? '' : 'circle'"
              >
                直接按社团名入库
              </button>
              <button 
                type="button" 
                class="soft-button interactive-button h-10 rounded-lg border border-slate-200/70 bg-white/55 text-sm font-medium text-slate-700"
                :class="{'active': settings.namingMode === 'api'}"
                @click="settings.namingMode = settings.namingMode === 'api' ? '' : 'api'"
              >
                API 命名后的文件
              </button>
            </div>

            <div class="space-y-1">
              <p class="target-path text-xs text-slate-500 leading-relaxed">
                入库路径: <span class="text-slate-700 break-all">{{ resolvedTargetRoot || '-' }}</span>
                <span class="text-slate-400"> / {作品目录}</span>
              </p>
            </div>
              </section>
            </div>
          </section>
        </div>

        <section class="glass-panel glass-card tree-panel flex-1 rounded-2xl flex flex-col overflow-hidden">
          <div class="tree-scroll flex-1 p-4 overflow-auto no-scrollbar">
            <div class="tree-list space-y-1">
              <template v-for="plan in planStates" :key="plan.session_id">
                <div class="tree-node">
                  <div
                    class="tree-row plan-node-header flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="isPlanAllSelected(plan) || isPlanPartiallySelected(plan) ? 'tree-row-selected' : ''"
                    @click="togglePlanExpand(plan)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="togglePlanExpand(plan)"
                      >
                        <ChevronDown v-if="plan.rootExpanded !== false" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="isPlanAllSelected(plan) ? 'tree-checkbox-on' : (isPlanPartiallySelected(plan) ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="togglePlanAll(plan)"
                      >
                        <Check v-if="isPlanAllSelected(plan)" :size="14" />
                        <span v-else-if="isPlanPartiallySelected(plan)" class="checkbox-minus" />
                      </button>

                      <Folder :size="20" class="tree-icon icon-folder" />

                      <span class="tree-name node-rjcode text-sm text-slate-800 truncate font-medium">
                        {{ plan.rjcode }} <span class="node-title-muted">{{ plan.title || plan.canonical_rjcode }}</span>
                      </span>
                    </div>
                    <span class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(plan.total_size_bytes) }}</span>
                  </div>
                </div>

                <div v-for="row in (plan.rootExpanded === false ? [] : plan.flatRows)" :key="row.id" class="tree-node">
                  <div
                    class="tree-row flex items-center py-1.5 px-2 rounded-md group cursor-pointer"
                    :class="row.checked || row.indeterminate ? 'tree-row-selected' : ''"
                    :style="{ paddingLeft: `${(row.depth + 1) * 16 + 16}px` }"
                    @click="handleTreeRowClick(plan, row)"
                  >
                    <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                      <button
                        v-if="row.type === 'dir'"
                        type="button"
                        class="tree-expander p-0.5 rounded"
                        @click.stop="toggleExpand(plan, row)"
                      >
                        <ChevronDown v-if="plan.expandedIds.has(row.id)" :size="17" class="text-slate-400" />
                        <ChevronRight v-else :size="17" class="text-slate-400" />
                      </button>
                      <span v-else class="expander-spacer" />

                      <button
                        type="button"
                        class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                        :class="row.checked ? 'tree-checkbox-on' : (row.indeterminate ? 'tree-checkbox-partial' : 'tree-checkbox-off')"
                        @click.stop="toggleTreeRow(plan, row)"
                      >
                        <Check v-if="row.checked" :size="14" />
                        <span v-else-if="row.indeterminate" class="checkbox-minus" />
                      </button>

                      <component :is="getTreeRowIconComponent(row)" :size="20" class="tree-icon" :class="getTreeRowIconClass(row)" />

                      <span class="tree-name text-sm text-slate-800 truncate font-medium">
                        {{ row.name }}
                      </span>
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
        <div class="summary text-sm text-slate-500 font-medium"><span class="summary-strong text-slate-900">{{ selectedFileCount }}</span> 已选，共 <span class="summary-strong text-slate-900">{{ formatSize(selectedTotalBytes) }}</span></div>

        <div class="footer-actions flex items-center gap-3">
          <button type="button" class="primary-cta px-10 h-11 rounded-xl font-bold text-white" :disabled="selectedFileCount === 0 || starting || (requiresTargetLibrary && !props.settings.targetLibraryId)" @click="emitSubmit">
            <span v-if="starting" class="inline-flex items-center"><AppLoadingAnimation variant="inline" :size="30" class="mr-1" />处理中</span>
            <span v-else>{{ primaryActionLabel }}</span>
          </button>
          <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="emit('update:visible', false)">取消</button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  Check,
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  FileText,
  Folder,
  Music,
  X,
} from 'lucide-vue-next'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  starting: { type: Boolean, default: false },
  actionMode: { type: String, default: 'download' },
  plans: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  targetSubdirOptions: { type: Array, default: () => [] },
  settings: { type: Object, required: true },
  circleName: { type: String, default: '' }
})

const emit = defineEmits(['submit', 'update:visible'])

const planStates = ref([])

const targetLibraries = computed(() => (props.libraries || []).filter(item => item?.enabled !== false))
const selectedTargetLibrary = computed(() => targetLibraries.value.find(item => item.id === props.settings.targetLibraryId) || null)
const resolvedTargetRoot = computed(() => {
  const root = String(selectedTargetLibrary.value?.root_path || '').trim()
  const sep = root.includes('/') ? '/' : '\\'
  const prefix = String(props.settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  const circle = String(props.circleName || '').trim()
  
  const parts = [root]
  if (prefix) parts.push(prefix)
  if (circle) parts.push(circle)
  
  return parts.filter(Boolean).join(sep)
})
const selectedFileCount = computed(() => planStates.value.reduce((sum, plan) => sum + Number(plan.selected_resource_count || 0), 0))
const selectedTotalBytes = computed(() => planStates.value.reduce((sum, plan) => sum + Number(plan.selected_size_bytes || 0), 0))
const previewSelectableResources = computed(() => planStates.value.flatMap(plan => Array.isArray(plan?.selectable_resources) ? plan.selectable_resources : []))

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

const inventoryLabel = computed(() => {
  return targetLibraries.value.find(item => item.id === props.settings.targetLibraryId)?.name || '选择库存'
})

const prefixLabel = computed(() => {
  return props.settings.targetSubdir || ''
})
const requiresTargetLibrary = computed(() => props.actionMode === 'reimport')
const primaryActionLabel = computed(() => props.actionMode === 'reimport' ? '跳过下载直接入库' : '下载')

const openSelect = ref(null)
const selectRoot = ref(null)

function toggleSelectMenu(menu) {
  openSelect.value = openSelect.value === menu ? null : menu
}

function chooseOption(menu, value) {
  if (menu === 'inventory') {
    props.settings.targetLibraryId = value
  } else {
    props.settings.targetSubdir = value
  }
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

watch(() => props.plans, (plans) => {
  planStates.value = Array.isArray(plans) ? plans.map(buildPlanState) : []
}, { deep: true, immediate: true })

function emitSubmit() {
  const action = props.actionMode === 'reimport' ? 'reimport' : 'download'
  const useImmediateSynologyUpload = selectedTargetLibrary.value?.type === 'synology_filestation' && String(props.settings.targetLibraryId || '').trim()
  const items = planStates.value
    .map(plan => ({
      session_id: plan.session_id,
      rjcode: plan.rjcode,
      canonical_rjcode: plan.canonical_rjcode,
      display_rjcodes: plan.display_rjcodes || [],
      work_title: plan.title,
      folder_path: plan.folder_path || '',
      selected_resources: plan.selectable_resources.filter(item => item.selected),
      upload_options: {
        enabled: useImmediateSynologyUpload,
        mode: useImmediateSynologyUpload ? 'synology' : 'disabled',
        target_path: '',
        library_id: useImmediateSynologyUpload ? String(props.settings.targetLibraryId || '').trim() : ''
      },
      postprocess_options: {
        enabled: true,
        target_library_id: props.settings.targetLibraryId || '',
        target_subdir: props.settings.targetSubdir || '',
        naming_mode: props.settings.namingMode,
        classify_mode: props.settings.classifyMode,
        circle_name: props.circleName || ''
      },
      resource_filter_snapshot: {},
      verify_md5_after_download: true
    }))
    .filter(item => item.selected_resources.length > 0)

  emit('submit', {
    action,
    items,
    batchOptions: {
      download_base_path: props.settings.downloadBasePath || '',
      target_library_id: props.settings.targetLibraryId || '',
      target_subdir: props.settings.targetSubdir || '',
      naming_mode: props.settings.namingMode,
      classify_mode: props.settings.classifyMode
    }
  })
}

function buildPlanState(plan) {
  const resources = (plan?.selectable_resources || []).map(item => ({
    ...item,
    selected: Boolean(item.selected),
    recommended: Boolean(item.selected),
    recommended_skip_reasons: item.recommended_skip_reasons || []
  }))
  const tree = buildTree(resources)
  const expandedIds = new Set(tree.map(node => node.id))
  const state = { ...plan, selectable_resources: resources, tree, expandedIds, rootExpanded: true, flatRows: [] }
  refreshPlanTree(state)
  return state
}

function buildTree(resources) {
  const roots = []
  const dirMap = new Map()
  for (const resource of resources) {
    const path = String(resource.relative_path || resource.file_name || '')
    const parts = path.split('/').filter(Boolean)
    let children = roots
    let parentPath = ''
    for (let i = 0; i < parts.length; i += 1) {
      const name = parts[i]
      const currentPath = parentPath ? `${parentPath}/${name}` : name
      const isFile = i === parts.length - 1
      if (isFile) {
        children.push({ id: currentPath, name, path: currentPath, type: 'file', resource, size_bytes: Number(resource.size_bytes || 0), children: [] })
      } else {
        if (!dirMap.has(currentPath)) {
          const node = { id: currentPath, name, path: currentPath, type: 'dir', size_bytes: 0, children: [] }
          dirMap.set(currentPath, node)
          children.push(node)
        }
        children = dirMap.get(currentPath).children
      }
      parentPath = currentPath
    }
  }
  return roots
}

function flattenTree(nodes, expandedIds, depth = 0, out = []) {
  for (const node of nodes || []) {
    out.push({ ...node, depth })
    if (node.type === 'dir' && expandedIds.has(node.id)) flattenTree(node.children, expandedIds, depth + 1, out)
  }
  return out
}

function collectLeafResources(node) {
  if (!node) return []
  if (node.type === 'file') return [node.resource]
  return (node.children || []).flatMap(child => collectLeafResources(child))
}

function annotateSelection(node) {
  if (node.type === 'file') {
    return { ...node, checked: Boolean(node.resource.selected), indeterminate: false, recommended_skip_reasons: node.resource.recommended_skip_reasons || [] }
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

function refreshPlanTree(plan) {
  plan.tree = (plan.tree || []).map(annotateSelection)
  plan.flatRows = flattenTree(plan.tree, plan.expandedIds, 0, [])
  plan.total_size_bytes = plan.selectable_resources.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0)
  plan.selected_resource_count = plan.selectable_resources.filter(item => item.selected).length
  plan.selected_size_bytes = plan.selectable_resources.filter(item => item.selected).reduce((sum, item) => sum + Number(item.size_bytes || 0), 0)
}

function toggleExpand(plan, row) {
  const next = new Set(plan.expandedIds)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  plan.expandedIds = next
  refreshPlanTree(plan)
}

function togglePlanExpand(plan) {
  plan.rootExpanded = plan.rootExpanded === false ? true : false
}

function getPlanFinalPath(plan) {
  const base = resolvedTargetRoot.value
  if (!base) return '-'
  const sep = base.includes('/') ? '/' : '\\'
  // 优先使用后端给出的 folder_path，如果没有则拼凑一个预览名
  const workFolder = plan.folder_path || `${plan.rjcode} ${plan.title || plan.canonical_rjcode}`
  return `${base}${sep}${workFolder}`
}

function updateResourceSelection(plan, row, nextSelected) {
  const targetIds = new Set(collectLeafResources(row).map(item => item.relative_path))
  plan.selectable_resources.forEach(item => {
    if (targetIds.has(item.relative_path)) item.selected = nextSelected
  })
  refreshPlanTree(plan)
}

function toggleTreeRow(plan, row) {
  const nextSelected = row.indeterminate ? true : !row.checked
  updateResourceSelection(plan, row, nextSelected)
}

function handleTreeRowClick(plan, row) {
  if (!row) return
  if (row.type === 'dir') {
    toggleExpand(plan, row)
    return
  }
  toggleTreeRow(plan, row)
}

function isPlanAllSelected(plan) {
  return plan.selectable_resources.length > 0 && plan.selectable_resources.every(item => item.selected)
}

function isPlanPartiallySelected(plan) {
  const checkedCount = plan.selectable_resources.filter(item => item.selected).length
  return checkedCount > 0 && checkedCount < plan.selectable_resources.length
}

function togglePlanAll(plan) {
  const next = !isPlanAllSelected(plan)
  plan.selectable_resources.forEach(item => {
    item.selected = next
  })
  refreshPlanTree(plan)
}

function getPreviewFileTypeKey(item) {
  const explicitExt = String(item?.file_ext || '').trim().toLowerCase()
  if (explicitExt) return explicitExt.startsWith('.') ? explicitExt : `.${explicitExt}`
  const sourceName = String(item?.relative_path || item?.file_name || '').trim().toLowerCase()
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
  planStates.value.forEach(plan => {
    plan.selectable_resources.forEach(item => {
      item.selected = nextSelected
    })
    refreshPlanTree(plan)
  })
}

function togglePreviewFileType(chip) {
  const key = String(chip?.key || '').trim()
  if (!key) return
  const nextSelected = String(chip?.state || '') !== 'all'
  planStates.value.forEach(plan => {
    plan.selectable_resources.forEach(item => {
      if (getPreviewFileTypeKey(item) === key) item.selected = nextSelected
    })
    refreshPlanTree(plan)
  })
}

function resetRecommended() {
  planStates.value.forEach(plan => {
    plan.selectable_resources.forEach(item => {
      item.selected = Boolean(item.recommended)
    })
    refreshPlanTree(plan)
  })
}

function getTreeRowIconComponent(row) {
  if (row?.type === 'dir') return Folder
  const resource = row?.resource || {}
  const ext = getPreviewFileTypeKey(resource)
  const resourceType = String(resource.resource_type || '').toLowerCase()
  if (['.wav', '.flac', '.mp3', '.m4a', '.ogg', '.aac', '.wma'].includes(ext) || resourceType === 'audio') return Music
  if (['.txt', '.md', '.json', '.cue', '.srt', '.ass', '.vtt'].includes(ext) || resourceType === 'subtitle') return FileText
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

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}
</script>

<style>
.tab-count {
  padding: 2px 5px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1;
  font-weight: 500;
  letter-spacing: normal;
  background: rgba(248, 250, 252, 0.4);
  color: rgb(156, 163, 175);
}

.tab-chip-active .tab-count {
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
}

.tab-chip-partial .tab-count {
  background: rgba(59, 130, 246, 0.15);
  color: #2563eb;
}

.content-grid {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 24px;
  padding: 8px 32px;
}

.left-column {
  width: 380px;
  flex: 0 0 380px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
}

.glass-card {
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.25), rgba(255, 255, 255, 0.1));
  box-shadow:
    0 8px 24px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
  /* 内层卡片移除过度模糊，依赖外层 window 的高斯模糊，以保证透视感 */
}

.settings-card {
  padding: 24px;
  flex: 1 1 auto;
  overflow-y: auto;
}

.action-card {
  padding: 24px;
}

.section-head {
  margin-bottom: 16px;
}

.section-head h2 {
  margin: 0 0 4px;
  font-size: 16px;
  line-height: 1;
  font-weight: 800;
  color: rgb(15, 23, 42);
}

.section-head p {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: rgb(100, 116, 139);
}

.compact-head {
  margin-bottom: 18px;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-group label {
  font-size: 12px;
  font-weight: 500;
  color: rgb(100, 116, 139);
}

.field-input {
  width: 100%;
  height: 36px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.92);
  box-shadow:
    0 2px 8px rgba(31, 45, 61, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
  padding: 0 10px;
  font-size: 14px;
  color: rgb(30, 41, 59);
  outline: none;
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
}

.field-input:focus,
.field-input:hover {
  border-color: rgba(96, 165, 250, 0.6);
  box-shadow:
    0 0 0 3px rgba(59, 130, 246, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.select-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}

.select-wrap {
  position: relative;
}

.select-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  text-align: left;
}

.select-arrow {
  color: #7f8792;
  flex: 0 0 auto;
}

.placeholder {
  color: #a2a8b0;
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 30;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.82);
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 14px 36px rgba(28, 42, 57, 0.14);
  backdrop-filter: blur(22px) saturate(135%);
  padding: 4px;
  animation: dropdown-in 0.18s ease;
}

.dropdown-item {
  width: 100%;
  border: 0;
  background: transparent;
  border-radius: 6px;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px 0 6px;
  font-size: 14px;
  color: rgb(30, 41, 59);
  cursor: pointer;
}

.dropdown-item:hover {
  background: rgba(241, 245, 249, 0.8);
}

.action-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.soft-button {
  border: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(255, 255, 255, 0.55);
  box-shadow:
    0 2px 8px rgba(31, 45, 61, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
  color: rgb(71, 85, 105);
}

.soft-button {
  height: 40px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease;
}

.soft-button.active {
  color: rgb(30, 41, 59);
  background: rgba(255, 255, 255, 0.78);
  border-color: rgba(226, 232, 240, 0.9);
  box-shadow: 0 8px 16px rgba(148, 163, 184, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.soft-button:hover {
  transform: translateY(-1px);
  box-shadow:
    0 8px 16px rgba(148, 163, 184, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.target-path {
  margin: 12px 0 0;
  font-size: 12px;
  color: rgb(100, 116, 139);
}

.tree-panel {
  min-width: 0;
  overflow: hidden;
  flex: 1 1 auto;
}

.tree-scroll {
  height: 100%;
  overflow: auto;
  padding: 16px;
  scrollbar-width: thin;
  scrollbar-color: rgba(119, 129, 141, 0.58) transparent;
}

.tree-scroll::-webkit-scrollbar {
  width: 8px;
}

.tree-scroll::-webkit-scrollbar-thumb {
  background: rgba(119, 129, 141, 0.48);
  border-radius: 999px;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tree-row {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 6px 10px 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background-color 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}

.plan-node-header {
  padding-left: 8px;
}

.tree-row:hover {
  background: rgba(248, 250, 252, 0.72);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.84);
}

.tree-row-selected {
  background: rgba(239, 246, 255, 0.7);
  box-shadow: inset 0 0 0 1px rgba(219, 234, 254, 0.8);
}

.tree-main {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.tree-expander,
.expander-spacer {
  width: 20px;
  flex: 0 0 20px;
}

.tree-expander {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  padding: 2px;
  border-radius: 6px;
  background: transparent;
  color: rgb(148, 163, 184);
  cursor: pointer;
}

.tree-expander:hover {
  background: rgba(255, 255, 255, 0.55);
  color: rgb(100, 116, 139);
}

.tree-checkbox {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
  border: 1px solid rgb(203, 213, 225);
  background: rgba(255, 255, 255, 0.9);
  color: transparent;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.tree-checkbox svg {
  stroke-width: 1.9;
}

.checkbox-minus {
  width: 8px;
  height: 1.5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.95;
}

.tree-checkbox-on {
  border-color: rgb(59, 130, 246);
  background: rgb(59, 130, 246);
  color: #ffffff;
}

.tree-checkbox-partial {
  border-color: rgb(59, 130, 246);
  background: rgb(59, 130, 246);
  color: #ffffff;
}

.tree-checkbox-off {
  border-color: rgb(203, 213, 225);
  background: rgba(255, 255, 255, 0.95);
}

.tree-row:hover .tree-checkbox-off {
  border-color: rgba(148, 163, 184, 0.48);
  background: rgba(255, 255, 255, 0.98);
}

.tree-icon {
  flex: 0 0 auto;
}

.icon-folder {
  color: rgb(96, 165, 250);
  fill: rgba(96, 165, 250, 0.2);
}

.icon-audio-blue {
  color: rgb(129, 140, 248);
}

.icon-audio-purple {
  color: rgb(196, 181, 253);
}

.icon-file {
  color: rgb(156, 163, 175);
}

.tree-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  line-height: 1.25;
  font-weight: 500;
  color: rgb(30, 41, 59);
}

.node-rjcode {
  font-size: 14px;
  font-weight: 600;
  color: rgb(30, 41, 59);
  margin-right: 4px;
}

.node-title-muted {
  margin-left: 4px;
  font-weight: 400;
  color: rgb(148, 163, 184);
}

.tree-size {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  min-width: 72px;
  text-align: right;
  font-size: 12px;
  color: rgb(148, 163, 184);
  margin-left: 16px;
  font-variant-numeric: tabular-nums;
}

.soft-button:active {
  transform: scale(0.98);
}

@media (max-width: 1280px) {
  .custom-preview-modal.el-dialog {
    width: min(calc(100vw - 24px), calc((100vh - 24px) * 16 / 9)) !important;
    max-width: min(calc(100vw - 24px), calc((100vh - 24px) * 16 / 9)) !important;
  }
}

@media (max-width: 960px) {
  .custom-preview-modal.el-dialog {
    width: calc(100vw - 24px) !important;
    max-width: calc(100vw - 24px) !important;
  }

  .window {
    aspect-ratio: auto;
    height: calc(100vh - 24px);
    max-height: calc(100vh - 24px);
    border-radius: 20px;
  }

  .window-header {
    padding: 20px 18px;
  }

  .tabs-row {
    padding: 0 18px 14px;
  }

  .content-grid {
    flex-direction: column;
    gap: 16px;
    padding: 6px 18px;
  }

  .left-column {
    width: auto;
    flex-basis: auto;
    gap: 16px;
  }

  .footer-row {
    flex-direction: column;
    align-items: stretch;
    padding: 18px;
  }

  .summary {
    margin-left: 0;
  }

  .footer-actions {
    justify-content: stretch;
  }

  .primary-cta,
  .secondary-cta {
    flex: 1;
    width: auto;
  }
}

@keyframes dropdown-in {
  from {
    opacity: 0;
    transform: translateY(-6px) scale(0.985);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
