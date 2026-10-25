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
    <div class="window circle-download-preview-window panel-enter glass-shell relative w-full aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
      <div class="window-header flex items-center justify-between px-8 py-6">
        <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">创建下载任务</h1>
        <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="emit('update:visible', false)">
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div v-if="previewLoading" class="flex-1 min-h-0 flex items-center justify-center">
        <AppLoadingAnimation :label="loading ? loadingLabel : '正在查询下载来源…'" :description="loading ? loadingDescription : '正在获取作品资料与文件列表'" :size="168" :min-height="260" />
      </div>


      <div v-if="!previewLoading" class="content-grid flex-1 flex gap-6 px-8 py-2 min-h-0">
        <aside class="download-settings-panel left-column">
          <div v-show="settingsSite === 'asmr.one'" class="source-settings-body flex flex-col gap-4 min-h-0 flex-1">
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
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-1.5 text-sm transition-colors"
                          :class="{ 'is-selected': settings.targetLibraryId === option.id }"
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

              <div class="action-buttons">
                <div class="path-option-row">
                  <span class="option-label">按社团归类</span>
                  <button type="button" class="path-option-toggle" role="switch" aria-label="按社团归类"
                    :class="{ active: settings.classifyMode === 'circle' && !settings.flattenFiles }"
                    :aria-checked="settings.classifyMode === 'circle' && !settings.flattenFiles"
                    :disabled="settings.flattenFiles" @click="toggleClassifyMode">
                    <span class="path-toggle-thumb" aria-hidden="true" />
                  </button>
                </div>
                <div class="path-option-row">
                  <span class="option-label">API 命名作品目录</span>
                  <button type="button" class="path-option-toggle" role="switch" aria-label="API 命名作品目录"
                    :class="{ active: settings.namingMode === 'api' && !settings.flattenFiles }"
                    :aria-checked="settings.namingMode === 'api' && !settings.flattenFiles"
                    :disabled="settings.flattenFiles" @click="toggleNamingMode">
                    <span class="path-toggle-thumb" aria-hidden="true" />
                  </button>
                </div>
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
                            class="dropdown-item flex w-full items-center rounded-md py-1.5 pr-8 pl-2 text-sm transition-colors relative"
                            :class="{ 'is-selected': isDirectPathSelected(option) }"
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
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-2 text-sm transition-colors"
                          :class="{ 'is-selected': !settings.directSubPath }"
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
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-2 text-sm transition-colors"
                          :class="{ 'is-selected': settings.directSubPath === sub.name }"
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

          <section v-show="settingsSite === 'imoutoheaven'" class="glass-panel circle-preview-settings-card source-settings-body rounded-2xl p-5 space-y-4">
            <div class="section-head space-y-1"><h2>YAAS 保存设置</h2><p>本批次的压缩包保存位置</p></div>
            <div class="field-group space-y-2">
              <label>压缩包保存目录</label>
              <input v-model="settings.yaasDownloadBasePath" :placeholder="yaasDownloadRoots[0] || '使用 HTTP 下载默认目录'" class="field-input h-9 w-full rounded-lg px-2.5 text-sm" />
            </div>
            <p class="source-preview-description break-all">保存到：{{ settings.yaasDownloadBasePath?.trim() || yaasDownloadRoots[0] || 'HTTP 下载默认目录' }}</p>
            <p class="source-preview-description">保留原压缩包，密码按系统模板写入文件名。下载完成后不自动解压。</p>
          </section>
        </aside>

        <section class="glass-panel glass-card tree-panel flex-1 rounded-2xl flex flex-col overflow-hidden">
          <div class="tree-scroll flex-1 p-4 overflow-auto no-scrollbar">
            <div class="tree-list space-y-1">
              <div v-if="!sourceComparisonMode && fileTreePlans.length" class="selected-site-columns">
                <section v-for="site in selectedSiteGroups" :key="site.id" class="selected-site-group">
                  <header class="selected-site-heading"><strong>{{ site.label }}</strong><span>{{ site.plans.length }} 部作品</span></header>
                  <div class="unified-file-scroll">
                    <DownloadResourceTree :plans="site.plans"
                      @toggle-root="togglePlanExpand" @toggle-all="togglePlanAll"
                      @toggle-expand="toggleExpand($event.plan, $event.row)"
                      @toggle-row="toggleTreeRow($event.plan, $event.row)"
                      @change-source="reselectSource" />
                  </div>
                </section>
              </div>
              <DownloadSourceComparison v-if="sourceComparisonMode" v-model="settingsSite" :plans="activePlans" @select-site="selectSite"
                @choose-source="chooseSource" @choose-row="chooseSourceRow" @toggle-root="togglePlanExpand" @toggle-expand="toggleExpand"
                @toggle-all="togglePlanAll" @toggle-row="toggleTreeRow">
                <template #toolbar>
      <div v-if="!previewLoading && settingsSite === 'asmr.one' && previewSelectableResources.length" class="file-type-toolbar flex flex-wrap items-center gap-1.5">
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
      </div>
                </template>
              </DownloadSourceComparison>
            </div>
          </div>
        </section>
      </div>

      <div v-if="!previewLoading" class="footer-row flex items-center justify-between">
        <div v-if="!selectedFileCount && pendingSourcePlans.length" class="summary">请选择要下载的语言版本和来源</div>
        <div v-else class="summary"><span class="summary-strong">{{ selectedFileCount }}</span> 已选，共 <span class="summary-strong">{{ formatSize(selectedTotalBytes) }}</span></div>

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
  FolderOpen,
  X,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
import RemoteFolderPickerDialog from '../common/RemoteFolderPickerDialog.vue'
import { libraryApi } from '../../api'
import DownloadResourceTree from './DownloadResourceTree.vue'
import DownloadSourceComparison from './DownloadSourceComparison.vue'

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

const emit = defineEmits(['submit', 'update:visible', 'versions-updated'])

const planStates = ref([])
const activePlans = computed(() => planStates.value.filter(plan => plan.selected_version !== false))
const selectedDownloadPlans = computed(() => activePlans.value.filter(plan =>
  !plan.source_selection_required && plan.selected_resource_count > 0))
const settingsSite = ref('asmr.one')
const availableSettingsSites = computed(() => {
  const providers = new Set(activePlans.value.flatMap(plan =>
    (plan.source_options?.length ? plan.source_options : [plan]).map(option => option.source_provider || 'asmr.one')))
  return [{ id: 'asmr.one', label: 'asmr.one 路径' }, { id: 'imoutoheaven', label: 'YAAS 路径' }]
    .filter(site => providers.has(site.id))
})
watch(availableSettingsSites, sites => {
  if (!sites.some(site => site.id === settingsSite.value)) settingsSite.value = sites[0]?.id || 'asmr.one'
}, { immediate: true })
const sourceComparisonMode = computed(() => activePlans.value.length > 0)
const fileTreePlans = computed(() => planStates.value.filter(plan =>
  !plan.source_selection_required && !plan.discovery_only && !plan.preview_error && plan.selectable_resources?.length))
const selectedSiteGroups = computed(() => [
  { id: 'asmr.one', label: 'asmr.one' }, { id: 'imoutoheaven', label: 'YAAS' },
].map(site => ({ ...site, plans: fileTreePlans.value.filter(plan =>
  (plan.source_provider || 'asmr.one') === site.id) })).filter(site => site.plans.length))
const previewLoading = computed(() => props.loading || (
  activePlans.value.some(plan => plan.version_loading)
  && activePlans.value.every(plan => plan.discovery_only && !plan.preview_error)
))

const targetLibraries = computed(() => (props.libraries || []).filter(item => item?.enabled !== false))
const selectedTargetLibrary = computed(() => targetLibraries.value.find(item => item.id === props.settings.targetLibraryId) || null)
const selectedFileCount = computed(() => activePlans.value.reduce((sum, plan) => sum + Number(plan.selected_resource_count || 0), 0))
const selectedTotalBytes = computed(() => activePlans.value.reduce((sum, plan) => sum + Number(plan.selected_size_bytes || 0), 0))
const asmrSelectionEntries = computed(() => activePlans.value.flatMap(plan => {
  const selected = !plan.source_selection_required && (plan.source_provider || 'asmr.one') === 'asmr.one'
  const option = selected ? plan : plan.sourcePreviews?.find(item => item.source_provider === 'asmr.one')
  return option ? [{ plan, option, selected }] : []
}))
const previewSelectableResources = computed(() => asmrSelectionEntries.value.flatMap(({ option, selected }) =>
  option.selectable_resources.map(item => selected ? item : { ...item, selected: false })))

function activateAsmrSelection(entry) {
  if (!entry.selected) {
    chooseSource(entry.plan, entry.option)
    entry.plan.selectable_resources.forEach(item => { item.selected = false })
  }
  return entry.plan
}

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

const isDirectMode = computed(() => props.enableDirectMode && props.settings?.mode === 'direct')
const hasAsmrPlans = computed(() => selectedDownloadPlans.value.some(plan => plan.source_provider !== 'imoutoheaven'))
const hasYaasPlans = computed(() => selectedDownloadPlans.value.some(plan => plan.source_provider === 'imoutoheaven'))
const yaasDownloadRoots = computed(() => [...new Set(activePlans.value.flatMap(plan => plan.source_options?.length ? plan.source_options : [plan]).filter(plan => plan.source_provider === 'imoutoheaven').map(plan => plan.download_root).filter(Boolean))])
const pendingSourcePlans = computed(() => activePlans.value.filter(plan => plan.source_selection_required))
const requiresTargetLibrary = computed(() => activePlans.value.some(plan =>
  plan.source_provider !== 'imoutoheaven' && !plan.source_selection_required && plan.selected_resource_count > 0) && !isDirectMode.value)
const primaryActionLabel = computed(() => {
  if (!activePlans.value.length) return '请选择下载版本'
  if (!selectedDownloadPlans.value.length) return '请选择下载内容'
  if (hasYaasPlans.value && !hasAsmrPlans.value) return '下载原压缩包'
  if (props.actionMode === 'reimport') return '跳过下载直接入库'
  if (isDirectMode.value) return '直接下载到选中的库存路径'
  return '下载'
})
const primaryActionDisabled = computed(() => {
  if (previewLoading.value || props.starting || activePlans.value.some(plan => plan.version_loading || plan.preview_error || plan.discovery_only)) return true
  if (!selectedDownloadPlans.value.length) return true
  if (selectedFileCount.value === 0) return true
  if (requiresTargetLibrary.value && !String(props.settings?.targetLibraryId || '').trim()) return true
  if (isDirectMode.value && hasAsmrPlans.value) {
    return !props.settings?.directLibraryId || !props.settings?.directBasePath
  }
  return false
})

const openSelect = ref(null)
watch(settingsSite, () => { openSelect.value = null })
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
  planStates.value = Array.isArray(plans)
    ? plans.filter(plan => !plan.discovery_only && !plan.preview_error
      && (plan.selectable_resources?.length || plan.source_selection_required))
      .map(plan => buildPlanState({ ...plan, selected_version: true,
        selectable_resources: (plan.selectable_resources || []).map(resource => ({ ...resource,
          selected: plan.selected_version !== false && resource.selected })) }))
    : []

}, { immediate: true })

function emitSubmit() {
  if (primaryActionDisabled.value) return
  if (requiresTargetLibrary.value && !String(props.settings?.targetLibraryId || '').trim()) {
    ElMessage.warning('请先选择目标库存')
    return
  }
  const action = props.actionMode === 'reimport' ? 'reimport' : 'download'
  const subdir = String(props.settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  const flattenFiles = !isDirectMode.value && Boolean(props.settings.flattenFiles)
  // flatten 直放模式下：强制 preserve / none，避免后端再创建作品目录 / 社团目录层。
  const namingMode = flattenFiles ? 'preserve' : (props.settings.namingMode === 'api' ? 'api' : 'preserve')
  const classifyMode = flattenFiles ? 'none' : (props.settings.classifyMode === 'circle' ? 'circle' : 'none')

  const items = selectedDownloadPlans.value
    .map(plan => buildSubmitItem(plan, isDirectMode.value))
    .filter(item => item && item.selected_resources.length > 0)

  emit('submit', {
    action,
    mode: isDirectMode.value ? 'direct' : 'classify',
    items,
    batchOptions: {
      download_base_path: props.settings.downloadBasePath || '',
      target_library_id: props.settings.targetLibraryId || '',
      target_subdir: subdir,
      naming_mode: namingMode,
      classify_mode: classifyMode,
      flatten_files: flattenFiles,
      mode: isDirectMode.value ? 'direct' : 'classify'
    }
  })
}

function buildSubmitItem(plan, isDirectMode) {
  if (plan.source_provider === 'imoutoheaven') {
    return { source_provider: plan.source_provider, rjcode: plan.rjcode,
      download_base_path: String(props.settings.yaasDownloadBasePath || '').trim(),
      canonical_rjcode: plan.canonical_rjcode,
      selected_resources: plan.selectable_resources.filter(item => item.selected).map(item => ({ id: item.id })) }
  }
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
  if (plan.source_selection_required) {
    plan = { ...plan, source_provider: '', selectable_resources: [] }
  }
  const resources = (plan?.selectable_resources || []).map(item => ({
    ...item,
    relative_path: plan.source_provider === 'imoutoheaven' ? (item.download_name || item.name) : item.relative_path,
    selected: Boolean(item.selected),
    recommended: Boolean(item.selected),
    recommended_skip_reasons: item.recommended_skip_reasons || []
  }))
  const tree = buildTree(resources)
  const expandedIds = new Set(tree.map(node => node.id))
  const state = { ...plan, selectable_resources: resources, tree, expandedIds, rootExpanded: true, flatRows: [] }
  if (plan.source_selection_required) state.sourcePreviews = (plan.source_options || []).map(option =>
    buildPlanState({ ...option, language_label: plan.language_label, source_selection_required: false, source_options: [] }))
  refreshPlanTree(state)
  return state
}

function chooseSource(plan, option, resource = null) {
  const previews = plan.sourcePreviews
  const states = plan.sourceStates || {}
  if (plan.source_provider) {
    // 缓存文件选择和展开状态，避免把来源缓存自身递归存进去。
    const { sourceStates, sourcePreviews, ...currentState } = plan
    states[plan.source_provider] = currentState
  }
  const state = states[option.source_provider] || buildPlanState({ ...plan, ...option,
    language_label: plan.language_label,
    source_options: plan.source_options, source_errors: plan.source_errors, source_selection_required: false })
  Object.assign(plan, state, { sourcePreviews: previews, sourceStates: states, source_selection_required: false })
  if (plan.source_provider === 'imoutoheaven') {
    const selected = resource || plan.selectable_resources.find(item => item.selected && item.complete)
      || plan.selectable_resources.find(item => item.complete)
    plan.selectable_resources.forEach(item => { item.selected = Boolean(selected && item.id === selected.id && item.complete) })
  } else if (!plan.selectable_resources.some(item => item.selected)) {
    plan.selectable_resources.forEach(item => { item.selected = item.complete !== false })
  }
  refreshPlanTree(plan)
}

function chooseSourceRow(plan, option, row) {
  const selected = !plan.source_selection_required && (plan.source_provider || 'asmr.one') === (option.source_provider || 'asmr.one')
  if (!selected) {
    const expandedIds = new Set(option.expandedIds)
    chooseSource(plan, option)
    plan.expandedIds = expandedIds
    plan.selectable_resources.forEach(item => { item.selected = false })
    refreshPlanTree(plan)
  }
  const currentRow = plan.flatRows.find(item => item.id === row.id)
  if (currentRow) toggleTreeRow(plan, currentRow)
}

function selectSite(entries, selected) {
  for (const { plan, option } of entries) {
    if (!selected) {
      plan.selectable_resources.forEach(item => { item.selected = false })
    } else {
      chooseSource(plan, option)
      if (plan.source_provider !== 'imoutoheaven') {
        plan.selectable_resources.forEach(item => { item.selected = item.complete !== false })
      }
    }
    refreshPlanTree(plan)
  }
}

function reselectSource(plan) {
  const states = { ...plan.sourceStates, [plan.source_provider]: { ...plan } }
  Object.assign(plan, buildPlanState({ ...plan, source_selection_required: true }), { sourceStates: states })
}

function choosePackage(plan, resource) {
  const selected = !resource.selected
  plan.selectable_resources.forEach(item => { item.selected = selected && item.id === resource.id && item.complete })
  refreshPlanTree(plan)
}

function buildTree(resources) {
  const roots = []
  const dirMap = new Map()
  for (const resource of resources) {
    const path = String(resource.relative_path || resource.file_name || '')
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
    let children = roots
    let parentPath = ''
    for (let i = 0; i < parts.length; i += 1) {
      const name = parts[i]
      const currentPath = parentPath ? `${parentPath}/${name}` : name
      const isFile = i === parts.length - 1
      if (isFile) {
        // 同名压缩包可能对应不同下载资源，行标识必须包含资源 ID。
        const id = JSON.stringify(['file', resource.id, currentPath])
        children.push({ id, name, path: currentPath, type: 'file', resource, size_bytes: Number(resource.size_bytes || 0), children: [] })
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
  if (plan.source_provider === 'imoutoheaven') {
    if (row.resource?.complete) choosePackage(plan, row.resource)
    return
  }
  const nextSelected = row.indeterminate ? true : !row.checked
  updateResourceSelection(plan, row, nextSelected)
}

function isPlanAllSelected(plan) {
  return plan.selectable_resources.length > 0 && plan.selectable_resources.every(item => item.selected)
}

function togglePlanAll(plan) {
  if (plan.source_provider === 'imoutoheaven') return
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

function togglePreviewFileType(chip) {
  const key = String(chip?.key || '').trim()
  if (!key) return
  const nextSelected = String(chip?.state || '') !== 'all'
  asmrSelectionEntries.value.forEach(entry => {
    const plan = activateAsmrSelection(entry)
    plan.selectable_resources.forEach(item => {
      if (getPreviewFileTypeKey(item) === key) item.selected = nextSelected
    })
    refreshPlanTree(plan)
  })
}

function resetRecommended() {
  asmrSelectionEntries.value.forEach(entry => {
    const plan = activateAsmrSelection(entry)
    plan.selectable_resources.forEach(item => {
      item.selected = Boolean(item.recommended)
    })
    refreshPlanTree(plan)
  })
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
.circle-download-preview-modal .circle-download-preview-window {
  height: min(780px, calc(100dvh - 48px));
  max-height: calc(100dvh - 48px);
  aspect-ratio: auto;
}
.circle-download-preview-modal .window-header,
.circle-download-preview-modal .tabs-row,
.circle-download-preview-modal .footer-row { flex-shrink: 0; }
.circle-download-preview-modal .tree-panel,
.circle-download-preview-modal .tree-scroll { min-height: 0; }
.circle-download-preview-modal .tree-list,
.circle-download-preview-modal .version-heading { min-width: 0; max-width: 100%; }
.circle-download-preview-modal .version-heading-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.circle-download-preview-modal .version-work-title { margin: 0; font-size: 14px; font-weight: 600; line-height: 1.65; overflow-wrap: anywhere; white-space: normal; }
.circle-download-preview-modal .download-source-comparison {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  padding: 0 12px 12px;
  gap: 12px;
  flex-shrink: 0;
}
.circle-download-preview-modal .source-comparison-intro {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 14px;
}
.circle-download-preview-modal .source-comparison-intro span {
  font-size: 12px;
  opacity: 0.6;
}
.circle-download-preview-modal .source-comparison-works {
  min-height: 0;
}
.circle-download-preview-modal .source-comparison-works::-webkit-scrollbar,
.circle-download-preview-modal .source-preview-tree::-webkit-scrollbar { display: none; }
.circle-download-preview-modal .source-comparison-work {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding-bottom: 8px;
  box-sizing: border-box;
}
.circle-download-preview-modal .source-comparison-work-heading {
  display: flex;
  gap: 12px;
  min-width: 0;
  margin-bottom: 12px;
  font-size: 12px;
  font-weight: 600;
}
.circle-download-preview-modal .source-comparison-work-heading span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.6;
  font-weight: 400;
}
.circle-download-preview-modal .source-comparison-grid {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-rows: minmax(0, 1fr);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.circle-download-preview-modal .source-preview-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}
.circle-download-preview-modal .source-preview-pane:hover {
  border-color: rgba(59, 130, 246, 0.65);
  background-color: rgba(59, 130, 246, 0.05);
}
.circle-download-preview-modal .source-preview-pane:active { background-color: rgba(59, 130, 246, 0.1); }
.circle-download-preview-modal .source-preview-pane:focus,
.circle-download-preview-modal .source-preview-pane:focus-visible { outline: none; box-shadow: none; }
.circle-download-preview-modal .source-preview-header {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}
.circle-download-preview-modal .source-preview-header p,
.circle-download-preview-modal .source-preview-description {
  font-size: 12px;
  line-height: 1.7;
  opacity: 0.7;
}
.circle-download-preview-modal .source-preview-pane > .source-preview-description { flex-shrink: 0; padding: 10px 12px; }
.circle-download-preview-modal .source-preview-tree {
  flex: 1;
  min-height: 0;
  padding: 0 12px 16px;
}
.circle-download-preview-modal .download-resource-tree { display: flex; flex-direction: column; gap: 6px; }
.circle-download-preview-modal .resource-file-row { cursor: pointer; transition: background-color 140ms ease; }
.circle-download-preview-modal .resource-file-row.is-unavailable { opacity: 0.45; cursor: not-allowed; }
.circle-download-preview-modal .resource-file-meta { display: block; margin-top: 4px; font-size: 11px; opacity: 0.8; }
@media (max-width: 640px) {
  .circle-download-preview-modal .download-source-comparison { padding: 0 18px 10px; gap: 12px; }
  .circle-download-preview-modal .source-comparison-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
}
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

.circle-download-preview-modal .tab-count {
  padding: 2px 5px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1;
  font-weight: 500;
  letter-spacing: normal;
  background: rgba(248, 250, 252, 0.4);
  color: rgb(156, 163, 175);
}

.circle-download-preview-modal .tab-chip-active .tab-count {
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
}

.circle-download-preview-modal .tab-chip-partial .tab-count {
  background: rgba(59, 130, 246, 0.15);
  color: #2563eb;
}

.circle-download-preview-modal .content-grid {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 24px;
  padding: 8px 32px;
}

.circle-download-preview-modal .left-column {
  width: 380px;
  flex: 0 0 380px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
}

.circle-download-preview-modal .glass-card {
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
.circle-download-preview-modal .no-scrollbar { scrollbar-width: none; -ms-overflow-style: none; }
.circle-download-preview-modal .no-scrollbar::-webkit-scrollbar { display: none; }

.circle-download-preview-modal .circle-preview-settings-card {
  padding: 24px;
  flex: 1 1 auto;
  overflow-y: auto;
}

.circle-download-preview-modal .mode-switch {
  flex: 0 0 auto;
}

.circle-download-preview-modal .mode-tab {
  border: 0;
  cursor: pointer;
  color: rgb(100, 116, 139);
  background: transparent;
  transition: all 0.18s ease;
}

.circle-download-preview-modal .mode-tab-active {
  background: rgba(255, 255, 255, 0.95);
  color: rgb(30, 41, 59);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.circle-download-preview-modal .mode-tab-idle:hover {
  background: rgba(248, 250, 252, 0.65);
  color: rgb(30, 41, 59);
}

.circle-download-preview-modal .section-head {
  margin-bottom: 16px;
}

.circle-download-preview-modal .section-head h2 {
  margin: 0 0 4px;
  font-size: 16px;
  line-height: 1;
  font-weight: 800;
  color: rgb(15, 23, 42);
}

.circle-download-preview-modal .section-head p {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: rgb(100, 116, 139);
}

.circle-download-preview-modal .field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.circle-download-preview-modal .field-group label {
  font-size: 12px;
  font-weight: 500;
  color: rgb(100, 116, 139);
}

.circle-download-preview-modal .field-input {
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

.circle-download-preview-modal .field-input:focus,
.circle-download-preview-modal .field-input:hover {
  border-color: rgba(96, 165, 250, 0.6);
  box-shadow:
    0 0 0 3px rgba(59, 130, 246, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.circle-download-preview-modal .select-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}

.circle-download-preview-modal .select-wrap {
  position: relative;
}

.circle-download-preview-modal .select-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  text-align: left;
}

.circle-download-preview-modal .picker-wrap {
  position: relative;
}

.circle-download-preview-modal .picker-button {
  cursor: pointer;
  text-align: left;
}

.circle-download-preview-modal .picker-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: rgba(248, 250, 252, 0.6);
}

.circle-download-preview-modal .picker-button:not(:disabled):hover {
  border-color: rgba(17, 24, 39, 0.32);
}

.circle-download-preview-modal .picker-clear {
  transition: background-color 0.15s ease, color 0.15s ease;
}

.circle-download-preview-modal .picker-clear:hover {
  background: rgba(15, 23, 42, 0.08);
}

.circle-download-preview-modal .select-arrow {
  color: #7f8792;
  flex: 0 0 auto;
}

.circle-download-preview-modal .placeholder {
  color: #a2a8b0;
}

.circle-download-preview-modal .dropdown-menu {
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

.circle-download-preview-modal .dropdown-item {
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

.circle-download-preview-modal .dropdown-item:hover {
  background: rgba(241, 245, 249, 0.8);
}

.circle-download-preview-modal .dropdown-item.is-selected {
  background: rgba(226, 232, 240, 0.86);
  color: rgb(15, 23, 42);
  font-weight: 600;
}

.circle-download-preview-modal .dropdown-item.is-selected:hover {
  background: rgba(203, 213, 225, 0.9);
}

.circle-download-preview-modal .action-buttons {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.circle-download-preview-modal .soft-button {
  border: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(255, 255, 255, 0.55);
  box-shadow:
    0 2px 8px rgba(31, 45, 61, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
  color: rgb(71, 85, 105);
}

.circle-download-preview-modal .soft-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 40px;
  height: auto;
  border-radius: 8px;
  font-size: 11px !important;
  padding: 6px 4px;
  box-sizing: border-box;
  white-space: nowrap;
  line-height: 1.15;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
  letter-spacing: -0.01em;
}

/* 选中态对齐顶部 mode-tab-active 的「浅白浮起」语言，
   不再用突兀的彩色渐变，保持整体玻璃浅色风格统一。 */
.circle-download-preview-modal .soft-button.active {
  background: rgba(255, 255, 255, 0.95);
  color: rgb(15, 23, 42);
  font-weight: 600;
  border-color: rgba(148, 163, 184, 0.5);
  box-shadow:
    0 4px 12px rgba(15, 23, 42, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 0 0 1px rgba(15, 23, 42, 0.04);
}

.circle-download-preview-modal .soft-button.active:hover {
  transform: translateY(-1px);
  box-shadow:
    0 6px 16px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98),
    inset 0 0 0 1px rgba(15, 23, 42, 0.05);
}

.circle-download-preview-modal .soft-button[disabled],
.circle-download-preview-modal .soft-button.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.circle-download-preview-modal .soft-button[disabled]:hover,
.circle-download-preview-modal .soft-button.is-disabled:hover {
  transform: none;
  box-shadow:
    0 2px 8px rgba(31, 45, 61, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.circle-download-preview-modal .soft-button:hover {
  transform: translateY(-1px);
  box-shadow:
    0 8px 16px rgba(148, 163, 184, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.circle-download-preview-modal .target-path {
  margin: 12px 0 0;
  font-size: 12px;
  color: rgb(100, 116, 139);
}

.circle-download-preview-modal .tree-panel {
  min-width: 0;
  overflow: hidden;
  flex: 1 1 auto;
}

.circle-download-preview-modal .tree-scroll {
  display: flex;
  flex-direction: column;
  overflow-y: hidden;
  overflow-x: hidden;
  padding: 16px;
  scrollbar-width: none;
  scrollbar-color: rgba(119, 129, 141, 0.58) transparent;
}

.circle-download-preview-modal .tree-scroll::-webkit-scrollbar {
  display: none;
}

.circle-download-preview-modal .tree-scroll::-webkit-scrollbar-thumb {
  background: rgba(119, 129, 141, 0.48);
  border-radius: 999px;
}

.circle-download-preview-modal .tree-list {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
}

.circle-download-preview-modal .tree-row {
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

.circle-download-preview-modal .plan-node-header {
  padding-left: 8px;
}

.circle-download-preview-modal .tree-row:hover {
  background: rgba(248, 250, 252, 0.72);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.84);
}

.circle-download-preview-modal .tree-row-selected {
  background: rgba(239, 246, 255, 0.7);
  box-shadow: inset 0 0 0 1px rgba(219, 234, 254, 0.8);
}

.circle-download-preview-modal .tree-main {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.circle-download-preview-modal .tree-expander,
.circle-download-preview-modal .expander-spacer {
  width: 20px;
  flex: 0 0 20px;
}

.circle-download-preview-modal .tree-expander {
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

.circle-download-preview-modal .tree-expander:hover {
  background: rgba(255, 255, 255, 0.55);
  color: rgb(100, 116, 139);
}

.circle-download-preview-modal .tree-checkbox {
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

.circle-download-preview-modal .tree-checkbox svg {
  stroke-width: 1.9;
}

.circle-download-preview-modal .checkbox-minus {
  width: 8px;
  height: 1.5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.95;
}

.circle-download-preview-modal .tree-checkbox-on {
  border-color: rgb(59, 130, 246);
  background: rgb(59, 130, 246);
  color: #ffffff;
}

.circle-download-preview-modal .tree-checkbox-partial {
  border-color: rgb(59, 130, 246);
  background: rgb(59, 130, 246);
  color: #ffffff;
}

.circle-download-preview-modal .tree-checkbox-off {
  border-color: rgb(203, 213, 225);
  background: rgba(255, 255, 255, 0.95);
}

.circle-download-preview-modal .tree-row:hover .tree-checkbox-off {
  border-color: rgba(148, 163, 184, 0.48);
  background: rgba(255, 255, 255, 0.98);
}

.circle-download-preview-modal .tree-icon {
  flex: 0 0 auto;
}

.circle-download-preview-modal .icon-folder {
  color: rgb(96, 165, 250);
  fill: rgba(96, 165, 250, 0.2);
}

.circle-download-preview-modal .icon-audio-blue {
  color: rgb(129, 140, 248);
}

.circle-download-preview-modal .icon-audio-purple {
  color: rgb(196, 181, 253);
}

.circle-download-preview-modal .icon-file {
  color: rgb(156, 163, 175);
}

.circle-download-preview-modal .tree-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  line-height: 1.25;
  font-weight: 500;
  color: rgb(30, 41, 59);
}

.circle-download-preview-modal .node-rjcode {
  font-size: 14px;
  font-weight: 600;
  color: rgb(30, 41, 59);
  margin-right: 4px;
}

.circle-download-preview-modal .node-title-muted {
  margin-left: 4px;
  font-weight: 400;
  color: rgb(148, 163, 184);
}

.circle-download-preview-modal .tree-size {
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

.circle-download-preview-modal .soft-button:active {
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

.circle-download-preview-modal .soft-button.mode-classify.active {
  background: rgba(219, 234, 254, 0.82);
  border-color: rgba(59, 130, 246, 0.42);
  color: #1d4ed8;
}

.circle-download-preview-modal .soft-button.mode-api.active {
  background: rgba(237, 233, 254, 0.84);
  border-color: rgba(139, 92, 246, 0.42);
  color: #6d28d9;
}

.circle-download-preview-modal .soft-button.mode-direct.active {
  background: rgba(204, 251, 241, 0.84);
  border-color: rgba(13, 148, 136, 0.42);
  color: #0f766e;
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

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item:not(.is-selected) {
  background: transparent !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item:not(.is-selected):hover {
  background: rgba(255, 255, 255, 0.07) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item.is-selected {
  background: #3a3b40 !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: #ffffff !important;
  font-weight: 650;
}

html.kikoerumanager-dark .circle-download-preview-modal .dropdown-item.is-selected:hover {
  background: #45474d !important;
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

html.kikoerumanager-dark .circle-download-preview-modal .soft-button.mode-classify.active {
  background: rgba(37, 99, 235, 0.28) !important;
  border-color: rgba(96, 165, 250, 0.62) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .soft-button.mode-api.active {
  background: rgba(124, 58, 237, 0.28) !important;
  border-color: rgba(167, 139, 250, 0.62) !important;
  color: #ddd6fe !important;
}

html.kikoerumanager-dark .circle-download-preview-modal .soft-button.mode-direct.active {
  background: rgba(13, 148, 136, 0.28) !important;
  border-color: rgba(45, 212, 191, 0.62) !important;
  color: #99f6e4 !important;
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
  .circle-download-preview-modal.el-dialog {
    width: min(calc(100vw - 24px), calc((100vh - 24px) * 16 / 9)) !important;
    max-width: min(calc(100vw - 24px), calc((100vh - 24px) * 16 / 9)) !important;
  }
}

@media (max-width: 1120px) {
  .circle-download-preview-modal .action-buttons {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .circle-download-preview-modal .action-buttons,
  .circle-download-preview-modal .select-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 960px) {
  .circle-download-preview-modal.el-dialog {
    width: calc(100vw - 24px) !important;
    max-width: calc(100vw - 24px) !important;
  }

  .circle-download-preview-modal .window {
    aspect-ratio: auto;
    height: calc(100vh - 24px);
    max-height: calc(100vh - 24px);
    border-radius: 20px;
  }

  .circle-download-preview-modal .window-header {
    padding: 20px 18px;
  }

  .circle-download-preview-modal .tabs-row {
    padding: 0 18px 14px;
  }

  .circle-download-preview-modal .content-grid {
    flex-direction: column;
    gap: 16px;
    padding: 6px 18px;
  }

  .circle-download-preview-modal .left-column {
    width: auto;
    flex-basis: auto;
    gap: 16px;
  }

  .circle-download-preview-modal .footer-row {
    flex-direction: column;
    align-items: stretch;
    padding: 18px;
  }

  .circle-download-preview-modal .summary {
    margin-left: 0;
  }

  .circle-download-preview-modal .footer-actions {
    justify-content: stretch;
  }

  .circle-download-preview-modal .primary-cta,
  .circle-download-preview-modal .secondary-cta {
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

.circle-download-preview-modal .archive-package-card {
  background: rgba(148, 163, 184, 0.06);
  border-color: rgba(148, 163, 184, 0.25);
  border-radius: 10px;
  color: inherit;
  position: relative;
  overflow: hidden;
  transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}
.circle-download-preview-modal .archive-package-card:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.11);
  border-color: rgba(96, 165, 250, 0.48);
}
.circle-download-preview-modal .archive-package-card:active:not(:disabled) {
  background: rgba(59, 130, 246, 0.12);
}
.circle-download-preview-modal .archive-package-icon { opacity: 0.88; }
.circle-download-preview-modal .archive-package-card.is-selected {
  border-color: rgba(59, 130, 246, 0.72);
  background: rgba(59, 130, 246, 0.09);
  box-shadow: inset 3px 0 0 #3b82f6;
}
.circle-download-preview-modal .archive-package-card.is-selected .archive-package-check {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
html.kikoerumanager-dark .circle-download-preview-modal .archive-package-card.is-selected {
  border-color: rgba(96, 165, 250, 0.72);
  background: rgba(96, 165, 250, 0.13);
  box-shadow: inset 3px 0 0 #60a5fa;
}
.circle-download-preview-modal .archive-package-card:disabled { opacity: 0.45; cursor: not-allowed; }
.circle-download-preview-modal .archive-package-check {
  border-radius: 6px;
  border-color: rgba(148, 163, 184, 0.55);
  background: rgba(15, 23, 42, 0.04);
}
.circle-download-preview-modal .version-tag {
  display: inline-flex; align-items: center; border: 1px solid rgba(59,130,246,.35);
  border-radius: 6px; padding: 3px 8px; font-size: 12px; color: #2563eb;
  background: rgba(59,130,246,.08);
}
.circle-download-preview-modal .version-language-card {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 10px;
  border: 0;
  border-radius: 0;
  padding: 14px 16px;
  font-size: 12px;
  text-align: left;
  color: inherit;
  background: transparent;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease;
}
.circle-download-preview-modal .version-language-card:hover {
  background: rgba(148, 163, 184, 0.12);
  transform: none;
}
.circle-download-preview-modal .version-language-card:active { background: rgba(148, 163, 184, 0.2); transform: none; }
.circle-download-preview-modal .version-language-card.is-selected { background: rgba(96, 165, 250, 0.06); }
.circle-download-preview-modal .version-language-card:disabled { opacity: 0.5; cursor: wait; }
.circle-download-preview-modal .version-language-card > :not(.version-language-title) { flex-shrink: 0; }
.circle-download-preview-modal .version-language-title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.circle-download-preview-modal .version-section {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
}
.circle-download-preview-modal .version-section.is-expanded { border-color: rgba(96, 165, 250, 0.4); flex: 1 1 0; min-height: 0; }
.circle-download-preview-modal .version-heading { flex-shrink: 0; }
.circle-download-preview-modal .version-file-scroll,
.circle-download-preview-modal .source-preview-tree { min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; scrollbar-width: thin; }
.circle-download-preview-modal .version-file-scroll { flex: 1; padding: 0 12px 12px; }
.circle-download-preview-modal .unified-file-scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; scrollbar-width: thin; }
.circle-download-preview-modal .selected-site-columns { display: flex; gap: 16px; flex: 1; min-height: 0; overflow: hidden; }
.circle-download-preview-modal .selected-site-group { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; }
.circle-download-preview-modal .selected-site-heading { display: flex; align-items: center; gap: 10px; padding: 8px 8px 14px; font-size: 14px; flex-shrink: 0; }
.circle-download-preview-modal .selected-site-heading span { font-size: 12px; opacity: .6; }
.circle-download-preview-modal .resource-tree-entry + .resource-tree-entry { margin-top: 4px; }
.circle-download-preview-modal .download-source-comparison { flex: 1 1 0; overflow: hidden; }
.circle-download-preview-modal .source-comparison-intro { flex-shrink: 0; }
.circle-download-preview-modal .source-comparison-works { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.circle-download-preview-modal .source-comparison-work { flex: 1; overflow: hidden; }
.circle-download-preview-modal .source-switch-link { align-self: flex-start; padding: 0; border: 0; background: none; color: #60a5fa; font-size: 12px; cursor: pointer; }
.circle-download-preview-modal .source-switch-link:hover { color: #3b82f6; text-decoration: underline; }
.circle-download-preview-modal .version-heading-toolbar { padding: 14px 16px 8px; }
.circle-download-preview-modal .version-work-title { padding: 0 16px 12px; }
.circle-download-preview-modal .version-details { display: flex; flex-direction: column; gap: 10px; padding: 10px 16px 14px; }
.circle-download-preview-modal .version-status { display: flex; flex-wrap: wrap; gap: 8px; font-size: 11px; opacity: 0.7; }
.circle-download-preview-modal .version-status span + span::before { content: '·'; margin-right: 8px; }
.circle-download-preview-modal .version-error { padding: 12px; border-radius: 8px; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2); }
.circle-download-preview-modal .version-error p { margin: 0 0 10px; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.circle-download-preview-modal .version-error .stateful-button { align-self: flex-start; }
@media (max-width: 640px) {
  .circle-download-preview-modal .version-language-card { flex-wrap: wrap; }
  .circle-download-preview-modal .version-language-title { flex-basis: 100%; order: 1; }
}
html.kikoerumanager-dark .circle-download-preview-modal .version-tag { color: #bfdbfe; border-color: rgba(147,197,253,.4); background: rgba(96,165,250,.12); }

/* 两站并排预览，路径设置保持固定宽度，外缘柔化只作用于弹窗本身。 */
.custom-preview-modal.circle-download-preview-modal.el-dialog {
  width: min(1680px, calc(100vw - 64px)) !important;
  max-width: calc(100vw - 64px) !important;
  padding: 0;
  overflow: visible;
}
.circle-download-preview-modal .circle-download-preview-window {
  width: 100%;
  max-width: none;
  height: min(760px, calc(100dvh - 96px));
  max-height: calc(100dvh - 64px);
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  box-shadow: 0 30px 90px #0f172a40, 0 0 24px #64748b26, 0 0 2px #ffffffb3 !important;
}
.circle-download-preview-modal .content-grid { gap: 20px; padding: 12px 24px; }
.circle-download-preview-modal .download-settings-panel {
  width: 300px;
  flex: 0 0 300px;
  gap: 12px;
  min-height: 0;
}
.circle-download-preview-modal .source-settings-body { overflow-y: auto; scrollbar-width: none; }
.circle-download-preview-modal .source-settings-body::-webkit-scrollbar { display: none; }
.circle-download-preview-modal .select-grid { grid-template-columns: minmax(0, 1fr); }
.circle-download-preview-modal .tree-panel { min-width: 0; }
@media (max-width: 1200px) {
  .circle-download-preview-modal .download-settings-panel { width: 250px; flex-basis: 250px; }
  .circle-download-preview-modal .content-grid { padding: 8px 16px; gap: 12px; }
}
@media (max-width: 960px) {
  .circle-download-preview-modal .content-grid { flex-direction: row; }
  .circle-download-preview-modal .download-settings-panel { width: 220px; flex-basis: 220px; }
}
@media (max-width: 640px) {
  .custom-preview-modal.circle-download-preview-modal.el-dialog { width: calc(100vw - 16px) !important; max-width: calc(100vw - 16px) !important; }
  .circle-download-preview-modal .circle-download-preview-window { height: calc(100dvh - 24px); max-height: calc(100dvh - 24px); }
  .circle-download-preview-modal .content-grid { flex-direction: column; }
  .circle-download-preview-modal .download-settings-panel { width: 100%; flex: 0 0 auto; max-height: 32dvh; }
  .circle-download-preview-modal .footer-row { padding: 12px 16px; }
}

/* 交互与状态使用系统灰阶，文件类型图标继续保留各自的辨识色。 */
.circle-download-preview-modal {
  --preview-control-text: #3f3f46;
  --preview-control-bg: #71717a12;
  --preview-control-border: #71717a40;
  --preview-selected-bg: #52525b;
  --preview-selected-text: #fafafa;
}
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal {
  --preview-control-text: #e4e4e7;
  --preview-control-bg: #ffffff12;
  --preview-control-border: #ffffff33;
  --preview-selected-bg: #d4d4d8;
  --preview-selected-text: #18181b;
}
html .custom-preview-modal.circle-download-preview-modal :is(.version-tag, .soft-button.active, .mode-tab-active, .tab-chip-active, .tab-chip-partial),
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal :is(.version-tag, .soft-button.active, .mode-tab-active, .tab-chip-active, .tab-chip-partial) {
  color: var(--language-tag-text, var(--preview-control-text)) !important;
  background: var(--language-tag-bg, var(--preview-control-bg)) !important;
  border-color: var(--language-tag-border, var(--preview-control-border)) !important;
  box-shadow: none !important;
}
html .custom-preview-modal.circle-download-preview-modal :is(.tree-checkbox-on, .tree-checkbox-partial),
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal :is(.tree-checkbox-on, .tree-checkbox-partial) {
  background: var(--preview-selected-bg) !important;
  color: var(--preview-selected-text) !important;
  border-color: var(--preview-control-border) !important;
}
html .custom-preview-modal.circle-download-preview-modal .tree-row-selected,
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal .tree-row-selected {
  background: var(--preview-control-bg) !important;
  box-shadow: inset 0 0 0 1px var(--preview-control-border) !important;
}
html .custom-preview-modal.circle-download-preview-modal :is(.primary-cta:not(:disabled), .secondary-cta, .summary-strong, .source-switch-link),
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal :is(.primary-cta:not(:disabled), .secondary-cta, .summary-strong, .source-switch-link) {
  color: var(--preview-control-text) !important;
}
html .custom-preview-modal.circle-download-preview-modal .primary-cta:not(:disabled),
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal .primary-cta:not(:disabled) {
  background: var(--preview-control-bg) !important;
  border-color: var(--preview-control-border) !important;
}
.circle-download-preview-modal .tree-row > .text-blue-400 { color: var(--preview-control-text); }
html .custom-preview-modal.circle-download-preview-modal .tab-count,
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal .tab-count {
  color: var(--preview-control-text) !important;
  background: var(--preview-control-bg) !important;
}
.circle-download-preview-modal .source-settings-body { animation: path-panel-enter 180ms ease; }
@keyframes path-panel-enter { from { opacity: .4; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>

<style>
.circle-download-preview-modal .file-type-toolbar { padding: 0 8px 12px; flex-shrink: 0; }
/* 说明文字不承担切换操作，交互仅限右侧开关。 */
.circle-download-preview-modal .action-buttons { grid-template-columns: minmax(0, 1fr); gap: 0; }
.circle-download-preview-modal .path-option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 38px;
  padding: 4px 0;
  color: var(--preview-control-text);
  font-size: 12px;
  line-height: 1.5;
}
.circle-download-preview-modal .path-option-row .option-label { min-width: 0; overflow-wrap: anywhere; cursor: default; }
html .custom-preview-modal.circle-download-preview-modal .path-option-toggle {
  position: relative;
  box-sizing: border-box;
  flex: 0 0 32px;
  width: 32px;
  height: 18px;
  padding: 0;
  border: 1px solid #a1a1aa;
  border-radius: 999px;
  background: transparent !important;
  box-shadow: none !important;
  cursor: pointer;
  transform: none !important;
  transition: background-color 120ms ease-out, border-color 120ms ease-out;
}
.circle-download-preview-modal .path-toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #a1a1aa;
  transition: transform 120ms ease-out, background-color 120ms ease-out;
}
html .custom-preview-modal.circle-download-preview-modal .path-option-toggle.active { background: #52525b !important; border-color: #52525b; }
.circle-download-preview-modal .path-option-toggle.active .path-toggle-thumb { transform: translateX(14px); background: #fafafa; }
html.kikoerumanager-dark .custom-preview-modal.circle-download-preview-modal .path-option-toggle.active { background: #27272a !important; border-color: #71717a; }
html.kikoerumanager-dark .circle-download-preview-modal .path-option-toggle.active .path-toggle-thumb { background: #fafafa; }
html .custom-preview-modal.circle-download-preview-modal .path-option-toggle:hover:not(:disabled) { border-color: var(--preview-control-text); }
.circle-download-preview-modal .path-option-toggle:disabled { opacity: .4; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) {
  .circle-download-preview-modal :is(.path-option-toggle, .path-toggle-thumb) { transition: none; }
}
</style>
