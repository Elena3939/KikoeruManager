<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal circle-download-preview-modal"
    align-center
    modal-class="custom-preview-overlay circle-download-preview-overlay"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="loading" class="window circle-download-preview-window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden dialog-loading-overlay is-loading">
      <AppLoadingAnimation :label="loadingLabel" :description="loadingDescription" :size="168" :min-height="260" />
    </div>
    
    <div v-else class="window circle-download-preview-window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
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
        <button
          type="button"
          class="tab-chip tab-chip-idle ml-auto px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] border cursor-pointer relative z-10 transition-all duration-200"
          @click.stop="toggleFilterSelection"
        >
          <span>{{ filterApplied ? '过滤文件' : '全部' }}</span>
        </button>
      </div>

      <div class="content-grid flex-1 flex gap-6 px-8 py-2 min-h-0">
        <div class="left-column w-[380px] flex flex-col gap-6">
          <div v-if="enableDirectMode" class="mode-switch flex items-center gap-1 p-1 rounded-xl bg-white/55 border border-slate-200/70">
            <button
              type="button"
              class="mode-tab flex-1 h-8 px-3 rounded-lg text-sm font-medium transition-all"
              :class="settings.mode === 'classify' ? 'mode-tab-active' : 'mode-tab-idle'"
              @click="setMode('classify')"
            >入库归类</button>
            <button
              type="button"
              class="mode-tab flex-1 h-8 px-3 rounded-lg text-sm font-medium transition-all"
              :class="settings.mode === 'direct' ? 'mode-tab-active' : 'mode-tab-idle'"
              @click="setMode('direct')"
            >直放已有路径</button>
          </div>

          <section ref="selectRoot" class="glass-panel glass-card circle-preview-settings-card flex-1 rounded-2xl p-6 overflow-y-auto no-scrollbar">
            <div v-if="!enableDirectMode || settings.mode === 'classify'" class="space-y-6">
              <section class="space-y-4">
                <div class="section-head space-y-1">
                  <h2>落地设置</h2>
                  <p>先下载到临时目录，下载完成后入库到目标库存内。</p>
                </div>

                <div class="field-group space-y-2">
                  <label>下载临时目录</label>
                  <input v-model="settings.downloadBasePath" type="text" class="field-input h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-sm text-slate-800 outline-none" placeholder="留空使用默认临时路径" />
                </div>

                <div class="select-grid grid grid-cols-2 gap-4">
                  <div class="field-group space-y-2">
                    <label>目标库存</label>
                    <div class="select-wrap relative">
                      <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" @click.stop="toggleSelectMenu('inventory')">
                        <span class="line-clamp-1 text-left" :class="settings.targetLibraryId ? 'text-slate-800' : 'text-slate-400'">{{ inventoryLabel }}</span>
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
                          <span class="line-clamp-1 text-left" :class="settings.targetSubdir ? 'text-slate-800' : 'text-slate-400'">{{ targetSubdirLabel }}</span>
                        </span>
                        <span class="flex items-center gap-1 shrink-0">
                          <button
                            v-if="settings.targetSubdir"
                            type="button"
                            class="picker-clear inline-flex items-center justify-center size-5 rounded-md text-slate-400 hover:text-slate-700"
                            title="恢复到按社团名自动归类"
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
              </section>

              <div class="action-buttons grid grid-cols-3 gap-3">
                <button
                  type="button"
                  class="soft-button interactive-button h-10 rounded-lg border border-slate-200/70 bg-white/55 text-sm font-medium text-slate-700"
                  :class="{ active: settings.classifyMode === 'circle', 'is-disabled': settings.flattenFiles }"
                  :disabled="settings.flattenFiles"
                  :title="settings.flattenFiles ? '直放指定目录模式下不再按社团归类' : ''"
                  @click="toggleClassifyMode"
                >
                  按社团归类
                </button>
                <button
                  type="button"
                  class="soft-button interactive-button h-10 rounded-lg border border-slate-200/70 bg-white/55 text-sm font-medium text-slate-700"
                  :class="{ active: settings.namingMode === 'api', 'is-disabled': settings.flattenFiles }"
                  :disabled="settings.flattenFiles"
                  :title="settings.flattenFiles ? '直放指定目录模式下不创建作品目录' : ''"
                  @click="toggleNamingMode"
                >
                  API 命名作品目录
                </button>
                <button
                  type="button"
                  class="soft-button interactive-button h-10 rounded-lg border border-slate-200/70 bg-white/55 text-sm font-medium text-slate-700"
                  :class="{ active: settings.flattenFiles }"
                  title="开启后所有选中的文件直接落到「指定目录」下，不再创建社团目录 / 作品目录，也不保留作品内子目录"
                  @click="toggleFlattenFiles"
                >
                  直放指定目录
                </button>
              </div>

              <div class="space-y-1.5">
                <p class="target-path text-xs text-slate-500 leading-relaxed">
                  最终路径: <span class="text-slate-700 break-all">{{ finalPathPreview || '-' }}</span>
                </p>
                <p class="text-[11px] leading-relaxed text-slate-400">{{ finalPathDescription }}</p>
              </div>
            </div>

            <div v-else class="space-y-6">
              <section class="space-y-3">
                <div class="section-head space-y-1">
                  <h2>直放已有路径</h2>
                  <p>从已有库存定位本作品目录，直接把所选文件放进去。</p>
                </div>

                <div v-if="directLoading" class="text-xs text-slate-500">正在跨库存定位 RJ 路径…</div>

                <div v-else-if="directRJOptions.length === 0" class="rounded-xl border border-amber-200 bg-amber-50/80 p-3 text-xs text-amber-700 leading-relaxed">
                  没有从已有库存里找到匹配的 RJ 文件夹。请使用「入库归类」模式，或先在库存里建立目录。
                </div>

                <template v-else>
                  <div class="field-group space-y-2">
                    <label>选择 RJ 路径</label>
                    <div class="select-wrap relative">
                      <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" @click.stop="toggleSelectMenu('directPath')">
                        <span class="line-clamp-1 text-left" :class="selectedDirectPathLabel === '请选择' ? 'text-slate-400' : 'text-slate-800'">{{ selectedDirectPathLabel }}</span>
                        <ChevronDown :size="18" class="select-arrow size-4 text-slate-400" />
                      </button>

                      <div v-if="openSelect === 'directPath'" class="dropdown-panel dropdown-menu absolute z-50 mt-1 w-full origin-top rounded-lg bg-white/88 border border-white/80 text-slate-800 shadow-lg ring-1 ring-slate-200/80 p-1 max-h-64 overflow-y-auto">
                        <template v-for="option in directRJOptions" :key="option.key">
                          <button
                            type="button"
                            class="dropdown-item flex w-full items-center rounded-md py-1.5 pr-8 pl-2 text-sm transition-colors hover:bg-slate-100/80 relative"
                            @click.stop="chooseDirectPath(option)"
                          >
                            <div class="flex flex-col items-start min-w-0 w-full text-left">
                              <span class="truncate font-medium text-slate-800">{{ option.rjcode }} · {{ option.libraryName }}</span>
                              <span class="truncate text-[11px] text-slate-500">{{ option.path }}</span>
                            </div>
                            <span v-if="isDirectPathSelected(option)" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                              <Check :size="16" />
                            </span>
                          </button>
                        </template>
                      </div>
                    </div>
                  </div>

                  <div class="field-group space-y-2">
                    <label>目标子目录（可空 = RJ 根目录）</label>
                    <div class="select-wrap relative">
                      <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" :disabled="!hasDirectSelection" @click.stop="hasDirectSelection && toggleSelectMenu('directSub')">
                        <span class="line-clamp-1 text-left" :class="settings.directSubPath ? 'text-slate-800' : 'text-slate-400'">{{ settings.directSubPath || (hasDirectSelection ? '放在 RJ 根目录' : '先选 RJ 路径') }}</span>
                        <ChevronDown :size="18" class="select-arrow size-4 text-slate-400" />
                      </button>

                      <div v-if="openSelect === 'directSub'" class="dropdown-panel dropdown-menu absolute z-50 mt-1 w-full origin-top rounded-lg bg-white/88 border border-white/80 text-slate-800 shadow-lg ring-1 ring-slate-200/80 p-1 max-h-64 overflow-y-auto">
                        <button
                          type="button"
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-2 text-sm transition-colors hover:bg-slate-100/80"
                          @click.stop="chooseDirectSubdir('')"
                        >
                          <span class="truncate">放在 RJ 根目录</span>
                          <span v-if="!settings.directSubPath" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                            <Check :size="16" />
                          </span>
                        </button>
                        <button
                          v-for="sub in directSubdirOptions"
                          :key="sub.path || sub.name"
                          type="button"
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-2 text-sm transition-colors hover:bg-slate-100/80"
                          @click.stop="chooseDirectSubdir(sub.name)"
                        >
                          <span class="truncate">{{ sub.name }}</span>
                          <span v-if="settings.directSubPath === sub.name" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                            <Check :size="16" />
                          </span>
                        </button>
                        <div v-if="directSubdirLoading" class="px-2 py-1.5 text-[11px] text-slate-500">加载子目录…</div>
                        <div v-else-if="!directSubdirOptions.length" class="px-2 py-1.5 text-[11px] text-slate-400">RJ 路径下无子目录</div>
                      </div>
                    </div>
                    <input v-model="settings.directSubPath" type="text" class="field-input h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-sm text-slate-800 outline-none" placeholder="或手动输入相对路径" />
                  </div>

                  <div class="space-y-1">
                    <p class="target-path text-xs text-slate-500 leading-relaxed">
                      最终路径: <span class="text-slate-700 break-all">{{ resolvedDirectFinalPath || '-' }}</span>
                    </p>
                  </div>
                </template>
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
                        <ChevronDown v-if="plan.rootExpanded !== false" :size="17" class="text-blue-400" />
                        <ChevronRight v-else :size="17" class="text-blue-400" />
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
                        <ChevronDown v-if="plan.expandedIds.has(row.id)" :size="17" class="text-blue-400" />
                        <ChevronRight v-else :size="17" class="text-blue-400" />
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

      <div class="footer-row flex items-center justify-between">
        <div class="summary"><span class="summary-strong">{{ selectedFileCount }}</span> 已选，共 <span class="summary-strong">{{ formatSize(selectedTotalBytes) }}</span></div>

        <div class="footer-actions flex items-center gap-3">
          <button type="button" class="primary-cta" :disabled="primaryActionDisabled" @click="emitSubmit">
            <span v-if="starting" class="inline-flex items-center"><AppLoadingAnimation variant="inline" :size="24" class="mr-1" />处理中</span>
            <span v-else>{{ primaryActionLabel }}</span>
          </button>
          <button type="button" class="secondary-cta" @click="emit('update:visible', false)">取消</button>
        </div>
      </div>
    </div>
  </el-dialog>

  <RemoteFolderPickerDialog
    v-model:visible="targetDirectoryDialogVisible"
    :library="selectedTargetLibrary"
    :initial-relative-path="settings.targetSubdir"
    title="指定入库目录"
    @submit="handleTargetDirectorySubmit"
  />
</template>

<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount, toRaw } from 'vue'
import {
  Check,
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  FileText,
  Folder,
  FolderOpen,
  Music,
  X,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
import RemoteFolderPickerDialog from '../common/RemoteFolderPickerDialog.vue'
import { configApi, libraryApi } from '../../api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  loadingLabel: { type: String, default: '正在分析资源结构并生成下载计划...' },
  loadingDescription: { type: String, default: '聚合资源分组、语言版本和推荐项' },
  starting: { type: Boolean, default: false },
  actionMode: { type: String, default: 'download' },
  plans: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  targetSubdirOptions: { type: Array, default: () => [] },
  settings: { type: Object, required: true },
  circleName: { type: String, default: '' },
  enableDirectMode: { type: Boolean, default: false },
  existingPaths: { type: Object, default: () => ({}) },
  directLoading: { type: Boolean, default: false }
})

const emit = defineEmits(['submit', 'update:visible'])

const planStates = ref([])
const filterApplied = ref(false)
const cachedFilterRules = ref(null)

const targetLibraries = computed(() => (props.libraries || []).filter(item => item?.enabled !== false))
const selectedTargetLibrary = computed(() => targetLibraries.value.find(item => item.id === props.settings.targetLibraryId) || null)
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

const targetSubdirLabel = computed(() => {
  if (!props.settings.targetLibraryId) return '请先选择目标库存'
  const value = String(props.settings.targetSubdir || '').trim()
  return value || '按社团名自动归类'
})

const targetSubdirHint = computed(() => {
  if (!props.settings.targetLibraryId) return '请先选择目标库存'
  const subdir = String(props.settings.targetSubdir || '').trim()
  if (!subdir) return '点击选择库存内子目录，默认按社团名自动归类'
  return `当前指定子目录：${subdir}`
})

const finalPathPreview = computed(() => {
  const library = selectedTargetLibrary.value
  const base = String(library?.root_path || '').trim()
  if (!base) return ''
  const sep = base.includes('/') ? '/' : '\\'
  const subdir = String(props.settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')

  const parts = [base]
  if (subdir) parts.push(subdir.replace(/[\\/]+/g, sep))
  // 直放指定目录：不再拼社团 / 作品目录，所有文件直接落到 base/subdir 下。
  if (props.settings.flattenFiles) {
    return parts.join(sep)
  }
  if (props.settings.classifyMode === 'circle') {
    const circle = String(props.circleName || '').trim() || '{社团名}'
    parts.push(circle)
  }
  const workDir = props.settings.namingMode === 'api' ? '{API命名作品目录}' : '{作品目录}'
  parts.push(workDir)

  return parts.join(sep)
})

const finalPathDescription = computed(() => {
  const subdir = String(props.settings.targetSubdir || '').trim()
  if (props.settings.flattenFiles) {
    const where = subdir ? '指定子目录' : '库存根目录'
    return `所有选中文件直接落到${where}下，不创建社团 / 作品目录，也不保留作品内子目录。`
  }
  const hints = []
  hints.push(subdir ? '落到指定子目录下' : '落到库存根目录')
  if (props.settings.classifyMode === 'circle') {
    hints.push('按社团名再归类一层')
  } else {
    hints.push('不再按社团归类')
  }
  if (props.settings.namingMode === 'api') {
    hints.push('作品目录使用 API 命名')
  } else {
    hints.push('保留原作品目录名')
  }
  return hints.join('，') + '。'
})

function toggleClassifyMode() {
  if (props.settings.flattenFiles) return
  props.settings.classifyMode = props.settings.classifyMode === 'circle' ? 'none' : 'circle'
}

function toggleNamingMode() {
  if (props.settings.flattenFiles) return
  props.settings.namingMode = props.settings.namingMode === 'api' ? 'preserve' : 'api'
}

function toggleFlattenFiles() {
  props.settings.flattenFiles = !props.settings.flattenFiles
}
const requiresTargetLibrary = computed(() => props.actionMode === 'reimport')
const primaryActionLabel = computed(() => {
  if (props.actionMode === 'reimport') return '跳过下载直接入库'
  if (props.enableDirectMode && props.settings?.mode === 'direct') return '直接下载到选中的库存路径'
  return '下载'
})
const primaryActionDisabled = computed(() => {
  if (props.starting) return true
  if (selectedFileCount.value === 0) return true
  if (requiresTargetLibrary.value && !props.settings?.targetLibraryId) return true
  if (props.enableDirectMode && props.settings?.mode === 'direct') {
    return !props.settings?.directLibraryId || !props.settings?.directBasePath
  }
  return false
})

const openSelect = ref(null)
const selectRoot = ref(null)
const targetDirectoryDialogVisible = ref(false)

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

function setMode(mode) {
  props.settings.mode = mode
  openSelect.value = null
}

function openTargetDirectoryPicker() {
  if (!props.settings.targetLibraryId) {
    ElMessage.warning('请先选择目标库存')
    return
  }
  openSelect.value = null
  targetDirectoryDialogVisible.value = true
}

function clearTargetSubdir() {
  props.settings.targetSubdir = ''
}

function handleTargetDirectorySubmit(payload) {
  if (!payload) return
  const rel = String(payload.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  props.settings.targetSubdir = rel
  targetDirectoryDialogVisible.value = false
}

watch(() => props.settings?.targetLibraryId, (next, prev) => {
  if (prev && next && next !== prev) {
    props.settings.targetSubdir = ''
  }
})

// targetSubdir 在「有 → 无」或「无 → 有」之间切换时，把两个 toggle 重置为该模式的合理默认：
//  - 有子目录：默认不归类、保留原目录名（直接落到指定目录）
//  - 无子目录：默认按社团归类 + API 命名（与原行为一致）
// 用户随后可以手动覆盖任一 toggle。
watch(() => Boolean(String(props.settings?.targetSubdir || '').trim()), (hasNow, hadBefore) => {
  if (hadBefore === undefined) return
  if (hasNow === hadBefore) return
  if (hasNow) {
    props.settings.classifyMode = 'none'
    props.settings.namingMode = 'preserve'
  } else {
    props.settings.classifyMode = 'circle'
    props.settings.namingMode = 'api'
  }
})

function ensureToggleDefaults() {
  // 根据当前 targetSubdir 同步一次 toggle 默认值（不覆盖已被用户改过的值）。
  const hasSubdir = Boolean(String(props.settings?.targetSubdir || '').trim())
  if (!props.settings.classifyMode) {
    props.settings.classifyMode = hasSubdir ? 'none' : 'circle'
  }
  if (!props.settings.namingMode) {
    props.settings.namingMode = hasSubdir ? 'preserve' : 'api'
  }
}

const directSubdirOptions = ref([])
const directSubdirLoading = ref(false)
const directSubdirCache = new Map()

const directRJOptions = computed(() => {
  if (!props.enableDirectMode) return []
  const planRjset = new Set((props.plans || []).map(plan => String(plan?.rjcode || '').toUpperCase()).filter(Boolean))
  const options = []
  Object.entries(props.existingPaths || {}).forEach(([rjcode, info]) => {
    const upperRj = String(rjcode || '').toUpperCase()
    if (!upperRj || (planRjset.size > 0 && !planRjset.has(upperRj))) return
    const matches = (info && Array.isArray(info.matches)) ? info.matches : []
    matches.forEach(match => {
      const path = String(match?.path || '').trim()
      if (!path) return
      options.push({
        key: `${upperRj}::${match.library_id}::${path}`,
        rjcode: upperRj,
        libraryId: String(match.library_id || ''),
        libraryName: String(match.library_name || match.library_id || ''),
        libraryType: String(match.library_type || 'local'),
        libraryRootPath: String(match.library_root_path || ''),
        path,
        name: String(match.name || ''),
        size: match.size
      })
    })
  })
  return options
})

const directSelectionMap = computed(() => {
  const map = new Map()
  const selected = directRJOptions.value.find(opt => opt.libraryId === props.settings.directLibraryId && opt.path === props.settings.directBasePath)
  // 单一 RJ 场景下默认应用同一个 selection 给所有 plan
  if (selected) {
    directRJOptions.value
      .filter(opt => opt.rjcode === selected.rjcode && opt.libraryId === selected.libraryId && opt.path === selected.path)
      .forEach(opt => map.set(opt.rjcode, opt))
  }
  // 多 RJ 场景下，对每个 RJ 取首选项；如果与 settings 一致则覆盖
  const grouped = new Map()
  directRJOptions.value.forEach(opt => {
    if (!grouped.has(opt.rjcode)) grouped.set(opt.rjcode, opt)
  })
  grouped.forEach((opt, rjcode) => {
    if (!map.has(rjcode)) map.set(rjcode, opt)
  })
  return map
})

const selectedDirectPathLabel = computed(() => {
  const rjset = new Set([...directSelectionMap.value.keys()])
  if (rjset.size === 0) return '请选择'
  const samples = []
  rjset.forEach(rj => {
    const opt = directSelectionMap.value.get(rj)
    if (opt) samples.push(`${rj} · ${opt.libraryName}`)
  })
  if (samples.length === 1) return samples[0]
  return `${samples.length} 个 RJ 已匹配`
})

const hasDirectSelection = computed(() => directSelectionMap.value.size > 0)

const resolvedDirectFinalPath = computed(() => {
  if (!hasDirectSelection.value) return ''
  const selection = directSelectionMap.value.values().next().value
  if (!selection) return ''
  return joinDirectFinalPath(selection.path, props.settings.directSubPath, selection.libraryType)
})

function isDirectPathSelected(option) {
  return option.libraryId === props.settings.directLibraryId && option.path === props.settings.directBasePath
}

function chooseDirectPath(option) {
  props.settings.directLibraryId = option.libraryId
  props.settings.directBasePath = option.path
  props.settings.directLibraryType = option.libraryType
  openSelect.value = null
  loadDirectSubdirectories(option.libraryId, option.path)
}

function chooseDirectSubdir(name) {
  props.settings.directSubPath = String(name || '')
  openSelect.value = null
}

async function loadDirectSubdirectories(libraryId, path) {
  if (!libraryId || !path) {
    directSubdirOptions.value = []
    return
  }
  const cacheKey = `${libraryId}::${path}`
  if (directSubdirCache.has(cacheKey)) {
    directSubdirOptions.value = directSubdirCache.get(cacheKey) || []
    return
  }
  directSubdirLoading.value = true
  try {
    const data = await libraryApi.listSubdirectories(libraryId, path)
    const dirs = Array.isArray(data?.directories) ? data.directories : []
    directSubdirCache.set(cacheKey, dirs)
    directSubdirOptions.value = dirs
  } catch (error) {
    directSubdirOptions.value = []
  } finally {
    directSubdirLoading.value = false
  }
}

watch(
  () => [props.settings?.mode, props.enableDirectMode, props.settings?.directLibraryId, props.settings?.directBasePath],
  () => {
    if (props.enableDirectMode && props.settings?.mode === 'direct' && props.settings?.directLibraryId && props.settings?.directBasePath) {
      loadDirectSubdirectories(props.settings.directLibraryId, props.settings.directBasePath)
    }
  },
  { immediate: true }
)

function handleDocumentClick(event) {
  if (!selectRoot.value?.contains(event.target)) {
    openSelect.value = null
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  if (props.enableDirectMode && props.settings) {
    if (typeof props.settings.mode !== 'string' || !props.settings.mode) props.settings.mode = 'classify'
    if (typeof props.settings.directLibraryId !== 'string') props.settings.directLibraryId = ''
    if (typeof props.settings.directBasePath !== 'string') props.settings.directBasePath = ''
    if (typeof props.settings.directSubPath !== 'string') props.settings.directSubPath = ''
    if (typeof props.settings.directLibraryType !== 'string') props.settings.directLibraryType = ''
  }
  ensureToggleDefaults()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
})

watch(() => props.plans, (plans) => {
  filterApplied.value = false
  planStates.value = Array.isArray(plans) ? plans.map(buildPlanState) : []
  // Preload filter rules
  if (!cachedFilterRules.value) {
    configApi.get().then(config => {
      const rules = config?.filter?.rules
      if (Array.isArray(rules)) cachedFilterRules.value = rules.filter(r => r.enabled !== false && r.action === 'exclude')
    }).catch(() => {})
  }
}, { deep: true, immediate: true })

function emitSubmit() {
  const action = props.actionMode === 'reimport' ? 'reimport' : 'download'
  const isDirectMode = props.enableDirectMode && props.settings.mode === 'direct'
  const subdir = String(props.settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  const flattenFiles = !isDirectMode && Boolean(props.settings.flattenFiles)
  // flatten 直放模式下：强制 preserve / none，避免后端再创建作品目录 / 社团目录层。
  const namingMode = flattenFiles ? 'preserve' : (props.settings.namingMode === 'api' ? 'api' : 'preserve')
  const classifyMode = flattenFiles ? 'none' : (props.settings.classifyMode === 'circle' ? 'circle' : 'none')

  const items = planStates.value
    .map(plan => buildSubmitItem(plan, isDirectMode))
    .filter(item => item && item.selected_resources.length > 0)

  emit('submit', {
    action,
    mode: isDirectMode ? 'direct' : 'classify',
    items,
    batchOptions: {
      download_base_path: props.settings.downloadBasePath || '',
      target_library_id: props.settings.targetLibraryId || '',
      target_subdir: subdir,
      naming_mode: namingMode,
      classify_mode: classifyMode,
      flatten_files: flattenFiles,
      mode: isDirectMode ? 'direct' : 'classify'
    }
  })
}

function buildSubmitItem(plan, isDirectMode) {
  const flattenFiles = !isDirectMode && Boolean(props.settings.flattenFiles)
  // 直放指定目录：扁平化作品内子目录——把 selected_resources 的 relative_path 替换为 file_name，
  // 这样下载时文件直接落在 download_root 根下，后端 archive 不需要再处理嵌套层级。
  const rawSelected = plan.selectable_resources.filter(item => item.selected)
  const selectedResources = flattenFiles
    ? rawSelected.map(item => ({
        ...item,
        relative_path: String(item.file_name || item.relative_path || '').split('/').pop().split('\\').pop()
      }))
    : rawSelected

  const baseItem = {
    session_id: plan.session_id,
    rjcode: plan.rjcode,
    canonical_rjcode: plan.canonical_rjcode,
    display_rjcodes: plan.display_rjcodes || [],
    work_title: plan.title,
    cover_url: plan.cover_url || plan.image_url || '',
    image_url: plan.image_url || plan.cover_url || '',
    folder_path: plan.folder_path || '',
    selected_resources: selectedResources,
    resource_filter_snapshot: {},
    verify_md5_after_download: true,
    download_base_path: props.settings.downloadBasePath || ''
  }

  if (!isDirectMode) {
    const useImmediateSynologyUpload = selectedTargetLibrary.value?.type === 'synology_filestation' && String(props.settings.targetLibraryId || '').trim()
    const subdir = String(props.settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
    const namingMode = flattenFiles ? 'preserve' : (props.settings.namingMode === 'api' ? 'api' : 'preserve')
    const classifyMode = flattenFiles ? 'none' : (props.settings.classifyMode === 'circle' ? 'circle' : 'none')
    return {
      ...baseItem,
      upload_options: {
        enabled: useImmediateSynologyUpload,
        mode: useImmediateSynologyUpload ? 'synology' : 'disabled',
        target_path: '',
        library_id: useImmediateSynologyUpload ? String(props.settings.targetLibraryId || '').trim() : ''
      },
      postprocess_options: {
        enabled: true,
        target_library_id: props.settings.targetLibraryId || '',
        target_subdir: subdir,
        naming_mode: namingMode,
        classify_mode: classifyMode,
        flatten_files: flattenFiles,
        circle_name: props.circleName || ''
      }
    }
  }

  // direct 模式：用每个 RJ 自己的 selected match
  const selection = directSelectionMap.value.get(plan.rjcode) || directSelectionMap.value.get((plan.canonical_rjcode || '').toUpperCase())
  if (!selection) {
    return null
  }
  const finalPath = joinDirectFinalPath(selection.path, props.settings.directSubPath, selection.libraryType)
  const uploadMode = selection.libraryType === 'synology_filestation' ? 'synology' : 'local'
  return {
    ...baseItem,
    upload_options: {
      enabled: true,
      mode: uploadMode,
      target_path: finalPath,
      library_id: selection.libraryId
    },
    postprocess_options: {
      enabled: false,
      target_library_id: '',
      target_subdir: '',
      naming_mode: '',
      classify_mode: 'direct_target',
      circle_name: props.circleName || '',
      direct_target: {
        library_id: selection.libraryId,
        library_type: selection.libraryType,
        rj_root_path: selection.path,
        sub_path: props.settings.directSubPath || '',
        final_path: finalPath
      }
    }
  }
}

function joinDirectFinalPath(rjRootPath, subPath, libraryType) {
  const rj = String(rjRootPath || '').trim()
  const sub = String(subPath || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  if (!rj) return ''
  if (!sub) return rj
  const sep = libraryType === 'synology_filestation' ? '/' : (rj.includes('/') ? '/' : (rj.includes('\\') ? '\\' : '/'))
  const trimmed = rj.replace(/[\\/]+$/, '')
  return `${trimmed}${sep}${sub}`
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

function updateResourceSelection(plan, row, nextSelected) {
  const leafResources = new Set(collectLeafResources(row).map(item => toRaw(item)))
  plan.selectable_resources.forEach(item => {
    if (leafResources.has(toRaw(item))) item.selected = nextSelected
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

function toggleFilterSelection() {
  filterApplied.value = !filterApplied.value
  const applyFilter = filterApplied.value
  let compiledRules = null
  if (applyFilter) {
    compiledRules = (cachedFilterRules.value || []).map(rule => {
      try { return { regex: new RegExp(rule.pattern, 'i'), target: rule.target || 'all' } }
      catch { return null }
    }).filter(Boolean)
  }
  requestAnimationFrame(() => {
    planStates.value.forEach(plan => {
      let changed = false
      plan.selectable_resources.forEach(item => {
        let newVal
        if (!applyFilter) {
          newVal = Boolean(item.recommended)
        } else {
          newVal = Boolean(item.recommended)
          if (newVal && compiledRules.length > 0) {
            const fileName = String(item.file_name || '')
            const relativePath = String(item.relative_path || '')
            const folderPath = relativePath.includes('/') ? relativePath.substring(0, relativePath.lastIndexOf('/')) : ''
            for (const { regex, target } of compiledRules) {
              if (target === 'file' && regex.test(fileName)) { newVal = false; break }
              if (target === 'folder' && folderPath && regex.test(folderPath)) { newVal = false; break }
              if (target === 'all' && (regex.test(fileName) || regex.test(relativePath))) { newVal = false; break }
            }
          }
        }
        if (item.selected !== newVal) { item.selected = newVal; changed = true }
      })
      if (changed) refreshPlanTree(plan)
    })
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
.circle-download-preview-overlay {
  background: transparent !important;
  background-image: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

html.kikoerumanager-dark .circle-download-preview-overlay,
body.kikoerumanager-dark .circle-download-preview-overlay {
  background: transparent !important;
  background-image: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

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

/* 隐藏滚动条但保留滚轮滚动能力；
   scoped 样式无法继承其他组件定义，必须在本组件里复刻一份。 */
.no-scrollbar { scrollbar-width: none; -ms-overflow-style: none; }
.no-scrollbar::-webkit-scrollbar { display: none; }

.circle-preview-settings-card {
  padding: 24px;
  flex: 1 1 auto;
  overflow-y: auto;
}

.mode-switch {
  flex: 0 0 auto;
}

.mode-tab {
  border: 0;
  cursor: pointer;
  color: rgb(100, 116, 139);
  background: transparent;
  transition: all 0.18s ease;
}

.mode-tab-active {
  background: rgba(255, 255, 255, 0.95);
  color: rgb(30, 41, 59);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.mode-tab-idle:hover {
  background: rgba(248, 250, 252, 0.65);
  color: rgb(30, 41, 59);
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

.picker-wrap {
  position: relative;
}

.picker-button {
  cursor: pointer;
  text-align: left;
}

.picker-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: rgba(248, 250, 252, 0.6);
}

.picker-button:not(:disabled):hover {
  border-color: rgba(17, 24, 39, 0.32);
}

.picker-clear {
  transition: background-color 0.15s ease, color 0.15s ease;
}

.picker-clear:hover {
  background: rgba(15, 23, 42, 0.08);
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
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
  height: 34px;
  border-radius: 8px;
  font-size: 11.5px;
  padding: 0 4px;
  white-space: nowrap;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
  letter-spacing: -0.01em;
}

/* 选中态对齐顶部 mode-tab-active 的「浅白浮起」语言，
   不再用突兀的彩色渐变，保持整体玻璃浅色风格统一。 */
.soft-button.active {
  background: rgba(255, 255, 255, 0.95);
  color: rgb(15, 23, 42);
  font-weight: 600;
  border-color: rgba(148, 163, 184, 0.5);
  box-shadow:
    0 4px 12px rgba(15, 23, 42, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 0 0 1px rgba(15, 23, 42, 0.04);
}

.soft-button.active:hover {
  transform: translateY(-1px);
  box-shadow:
    0 6px 16px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98),
    inset 0 0 0 1px rgba(15, 23, 42, 0.05);
}

.soft-button[disabled],
.soft-button.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.soft-button[disabled]:hover,
.soft-button.is-disabled:hover {
  transform: none;
  box-shadow:
    0 2px 8px rgba(31, 45, 61, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
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

.circle-download-preview-modal .footer-row {
  flex: 0 0 auto;
  min-height: 58px;
  padding: 10px 30px 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.56);
  backdrop-filter: blur(18px) saturate(1.08);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
}

.circle-download-preview-modal .summary {
  margin: 0;
  color: rgb(100, 116, 139);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}

.circle-download-preview-modal .summary-strong {
  color: rgb(15, 23, 42);
  font-size: 12px;
  font-weight: 800;
}

.circle-download-preview-modal .footer-actions {
  gap: 10px;
}

.circle-download-preview-modal .primary-cta,
.circle-download-preview-modal .secondary-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 96px;
  height: 36px;
  padding: 0 22px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.circle-download-preview-modal .primary-cta {
  background: rgba(24, 24, 27, 0.08);
  color: rgb(24, 24, 27);
  border-color: rgba(24, 24, 27, 0.18);
  box-shadow:
    0 5px 14px rgba(24, 24, 27, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.circle-download-preview-modal .primary-cta:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgba(24, 24, 27, 0.12);
  border-color: rgba(24, 24, 27, 0.26);
  box-shadow:
    0 10px 20px rgba(24, 24, 27, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.74);
}

.circle-download-preview-modal .primary-cta:focus,
.circle-download-preview-modal .primary-cta:focus-visible,
.circle-download-preview-modal .secondary-cta:focus,
.circle-download-preview-modal .secondary-cta:focus-visible,
.circle-download-preview-modal .tab-chip:focus,
.circle-download-preview-modal .tab-chip:focus-visible,
.circle-download-preview-modal .soft-button:focus,
.circle-download-preview-modal .soft-button:focus-visible,
.circle-download-preview-modal .mode-tab:focus,
.circle-download-preview-modal .mode-tab:focus-visible,
.circle-download-preview-modal .close-button:focus,
.circle-download-preview-modal .close-button:focus-visible,
.circle-download-preview-modal .tree-row:focus,
.circle-download-preview-modal .tree-row:focus-visible,
.circle-download-preview-modal .tree-checkbox:focus,
.circle-download-preview-modal .tree-checkbox:focus-visible,
.circle-download-preview-modal .tree-expander:focus,
.circle-download-preview-modal .tree-expander:focus-visible,
.circle-download-preview-modal .field-input:focus,
.circle-download-preview-modal .field-input:focus-visible,
.circle-download-preview-modal .select-button:focus,
.circle-download-preview-modal .select-button:focus-visible,
.circle-download-preview-modal .picker-button:focus,
.circle-download-preview-modal .picker-button:focus-visible,
.circle-download-preview-modal .dropdown-item:focus,
.circle-download-preview-modal .dropdown-item:focus-visible,
.circle-download-preview-modal .el-input__wrapper.is-focus,
.circle-download-preview-modal .el-select__wrapper.is-focused {
  outline: none !important;
  outline-offset: 0 !important;
  --tw-ring-color: transparent !important;
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
}

.circle-download-preview-modal .field-input:focus,
.circle-download-preview-modal .field-input:focus-visible,
.circle-download-preview-modal .select-button:focus,
.circle-download-preview-modal .select-button:focus-visible,
.circle-download-preview-modal .picker-button:focus,
.circle-download-preview-modal .picker-button:focus-visible,
.circle-download-preview-modal .dropdown-item:focus,
.circle-download-preview-modal .dropdown-item:focus-visible,
.circle-download-preview-modal .el-input__wrapper.is-focus,
.circle-download-preview-modal .el-select__wrapper.is-focused {
  box-shadow: none !important;
}

.circle-download-preview-modal .primary-cta:active:not(:disabled),
.circle-download-preview-modal .secondary-cta:active {
  transform: translateY(0) scale(0.96);
}

.circle-download-preview-modal .primary-cta:disabled {
  cursor: not-allowed;
  background: rgba(226, 232, 240, 0.68);
  color: rgba(100, 116, 139, 0.7);
  border-color: rgba(203, 213, 225, 0.7);
  box-shadow: none;
}

.circle-download-preview-modal .secondary-cta {
  background: rgba(255, 255, 255, 0.58);
  color: rgb(51, 65, 85);
  box-shadow:
    0 4px 12px rgba(15, 23, 42, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
}

.circle-download-preview-modal .secondary-cta:hover {
  transform: translateY(-2px) scale(1.02);
  background: rgba(248, 250, 252, 0.92);
  border-color: rgba(15, 23, 42, 0.2);
  color: rgb(15, 23, 42);
  box-shadow:
    0 10px 20px rgba(15, 23, 42, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.92);
}

html.kikoerumanager-dark .circle-download-preview-overlay {
  background: transparent !important;
  background-image: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-window {
  background: #121316 !important;
  border: 1px solid rgba(255, 255, 255, 0.10) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow:
    0 28px 72px rgba(0, 0, 0, 0.54),
    inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .circle-download-preview-window.is-loading {
  align-items: center;
  justify-content: center;
  background: #121316 !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .window-header,
html.kikoerumanager-dark .circle-download-preview-modal .tabs-row,
html.kikoerumanager-dark .circle-download-preview-modal .footer-row {
  background: #17191d !important;
  border-color: rgba(255, 255, 255, 0.10) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .window-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

html.kikoerumanager-dark .circle-download-preview-modal .tabs-row {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

html.kikoerumanager-dark .circle-download-preview-modal .footer-row {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

html.kikoerumanager-dark .circle-download-preview-modal .title,
html.kikoerumanager-dark .circle-download-preview-modal h1,
html.kikoerumanager-dark .circle-download-preview-modal h2,
html.kikoerumanager-dark .circle-download-preview-modal .summary-strong,
html.kikoerumanager-dark .circle-download-preview-modal .tree-name,
html.kikoerumanager-dark .circle-download-preview-modal .node-rjcode,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-900,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-800,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-700 {
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal p,
html.kikoerumanager-dark .circle-download-preview-modal label,
html.kikoerumanager-dark .circle-download-preview-modal .summary,
html.kikoerumanager-dark .circle-download-preview-modal .target-path,
html.kikoerumanager-dark .circle-download-preview-modal .tree-size,
html.kikoerumanager-dark .circle-download-preview-modal .node-title-muted,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-600,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-500,
html.kikoerumanager-dark .circle-download-preview-modal .text-slate-400 {
  color: rgba(212, 212, 216, 0.68) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .glass-panel,
html.kikoerumanager-dark .circle-download-preview-modal .glass-card,
html.kikoerumanager-dark .circle-download-preview-modal .mode-switch {
  background: #17191d !important;
  border-color: rgba(255, 255, 255, 0.10) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .content-grid {
  background: #121316 !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tab-chip {
  min-height: 28px;
  border-radius: 7px !important;
  background: rgba(255, 255, 255, 0.045) !important;
  border-color: rgba(255, 255, 255, 0.10) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tab-chip:hover {
  transform: translateY(-1px);
  background: rgba(255, 255, 255, 0.075) !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tab-chip-active,
html.kikoerumanager-dark .circle-download-preview-modal .tab-chip-partial {
  background: rgba(255, 255, 255, 0.12) !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tab-count {
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06) !important;
  color: rgba(212, 212, 216, 0.72) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tab-chip-active .tab-count,
html.kikoerumanager-dark .circle-download-preview-modal .tab-chip-partial .tab-count {
  background: rgba(255, 255, 255, 0.16) !important;
  color: rgba(244, 244, 245, 0.92) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .mode-tab {
  color: rgba(212, 212, 216, 0.70) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .mode-tab-active {
  background: rgba(255, 255, 255, 0.12) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .mode-tab-idle:hover {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .field-input,
html.kikoerumanager-dark .circle-download-preview-modal .select-button,
html.kikoerumanager-dark .circle-download-preview-modal .picker-button {
  background: #101114 !important;
  border-color: rgba(255, 255, 255, 0.11) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .field-input::placeholder {
  color: rgba(161, 161, 170, 0.62) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .field-input:hover,
html.kikoerumanager-dark .circle-download-preview-modal .field-input:focus,
html.kikoerumanager-dark .circle-download-preview-modal .select-button:hover,
html.kikoerumanager-dark .circle-download-preview-modal .picker-button:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.22) !important;
  background: #14161a !important;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .picker-button:disabled {
  background: rgba(255, 255, 255, 0.035) !important;
  color: rgba(161, 161, 170, 0.62) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-menu,
html.kikoerumanager-dark .circle-download-preview-modal .dropdown-panel {
  background: #202226 !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: 0 18px 38px rgba(0, 0, 0, 0.38) !important;
  backdrop-filter: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item {
  color: rgba(244, 244, 245, 0.86) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item:hover {
  background: rgba(255, 255, 255, 0.07) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .soft-button,
html.kikoerumanager-dark .circle-download-preview-modal .secondary-cta,
html.kikoerumanager-dark .circle-download-preview-modal .interactive-chip {
  background: rgba(255, 255, 255, 0.045) !important;
  border-color: rgba(255, 255, 255, 0.10) !important;
  color: rgba(244, 244, 245, 0.84) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .soft-button:hover,
html.kikoerumanager-dark .circle-download-preview-modal .secondary-cta:hover,
html.kikoerumanager-dark .circle-download-preview-modal .interactive-chip:hover {
  background: rgba(255, 255, 255, 0.075) !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .soft-button.active {
  background: rgba(255, 255, 255, 0.12) !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-row {
  color: rgba(244, 244, 245, 0.86) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-row:hover {
  background: rgba(255, 255, 255, 0.055) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-row-selected {
  background: rgba(255, 255, 255, 0.11) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-checkbox {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #101114 !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-checkbox-on,
html.kikoerumanager-dark .circle-download-preview-modal .tree-checkbox-partial {
  border-color: rgba(255, 255, 255, 0.40) !important;
  background: #d4d4d8 !important;
  color: #18181b !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .tree-row:hover .tree-checkbox-off {
  border-color: rgba(255, 255, 255, 0.26) !important;
  background: #14161a !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .icon-folder {
  color: rgba(244, 244, 245, 0.82) !important;
  fill: rgba(244, 244, 245, 0.10) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .icon-audio-blue,
html.kikoerumanager-dark .circle-download-preview-modal .icon-audio-purple {
  color: #a5b4fc !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .icon-file {
  color: rgba(212, 212, 216, 0.60) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .primary-cta {
  background: rgba(255, 255, 255, 0.08) !important;
  color: rgba(244, 244, 245, 0.92) !important;
  border: 1px solid rgba(255, 255, 255, 0.16) !important;
  box-shadow:
    0 6px 16px rgba(0, 0, 0, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .primary-cta:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgba(255, 255, 255, 0.12) !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  box-shadow:
    0 10px 22px rgba(0, 0, 0, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .primary-cta:disabled {
  background: rgba(255, 255, 255, 0.06) !important;
  color: rgba(161, 161, 170, 0.62) !important;
  border-color: rgba(255, 255, 255, 0.10) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-download-preview-window .app-loading-animation {
  color: #ffffff;
}

html.kikoerumanager-dark .circle-download-preview-window .app-loading-animation__player {
  filter: brightness(1.12) contrast(1.04);
}

html.kikoerumanager-dark .circle-download-preview-window .app-loading-animation__label {
  color: #ffffff !important;
  font-weight: 700;
}

html.kikoerumanager-dark .circle-download-preview-window .app-loading-animation__description {
  color: rgba(212, 212, 216, 0.72) !important;
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
