<template>
  <Teleport to="body">
    <Transition name="cmw-fade">
      <div
        v-if="visible"
        class="pointer-events-none fixed inset-0 z-[2450] flex items-center justify-center p-6 max-[900px]:p-3"
      >
        <!-- 玻璃遮罩；非 loading / submitting 时点击关闭 -->
        <div
          class="pointer-events-auto absolute inset-0 bg-slate-900/35 backdrop-blur-[3px]"
          @click="close"
        />
        <!-- 玻璃面板 shell：对齐 Library.mediaPreviewDialog 的视觉范式 -->
        <div class="cmw-shell pointer-events-auto" @mousedown.stop>
          <!-- Header：纯玻璃，无 amber radial gradient -->
          <header class="cmw-header">
            <div class="flex min-w-0 items-center gap-3">
              <span class="cmw-icon">
                <GitMerge class="h-[18px] w-[18px]" :stroke-width="2.2" />
              </span>
              <div class="min-w-0">
                <div class="mb-0.5 flex items-center gap-2">
                  <h3 class="cmw-title">目录差异工作台</h3>
                  <span v-if="isRemoteTarget" class="cmw-tag is-amber">
                    <Upload class="h-3 w-3" :stroke-width="2.4" />
                    远程合并
                  </span>
                </div>
                <p class="cmw-subtitle" :title="conflictTitle">{{ conflictTitle }}</p>
              </div>
            </div>
            <div class="flex flex-shrink-0 items-center gap-2">
              <div v-if="preview" class="hidden flex-wrap items-center justify-end gap-2 md:flex">
                <button
                  type="button"
                  class="cmw-count-chip"
                  :class="{ 'is-active is-amber': statusFilter === 'changed' }"
                  @click="setStatusFilter('changed')"
                >
                  <span>差异</span><strong>{{ displaySummary.changed }}</strong>
                </button>
                <button
                  type="button"
                  class="cmw-count-chip"
                  :class="{ 'is-active is-emerald': statusFilter === 'new_only' }"
                  @click="setStatusFilter('new_only')"
                >
                  <span>新包独有</span><strong>{{ displaySummary.newOnly }}</strong>
                </button>
                <button
                  type="button"
                  class="cmw-count-chip"
                  :class="{ 'is-active is-slate': statusFilter === 'old_only' }"
                  @click="setStatusFilter('old_only')"
                >
                  <span>库存独有</span><strong>{{ displaySummary.oldOnly }}</strong>
                </button>
                <button
                  type="button"
                  class="cmw-count-chip"
                  :class="{ 'is-active is-slate': statusFilter === 'unchanged' }"
                  @click="setStatusFilter('unchanged')"
                >
                  <span>一致</span><strong>{{ displaySummary.unchanged }}</strong>
                </button>
              </div>
              <button
                type="button"
                class="cmw-close-btn"
                :disabled="loading || submitting"
                title="关闭"
                @click="close"
              >
                <X class="h-[15px] w-[15px]" :stroke-width="2.4" />
              </button>
            </div>
          </header>

          <!-- Toolbar -->
          <div class="cmw-toolbar">
            <div class="relative min-w-[180px] flex-1">
              <Search class="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" :stroke-width="2.2" />
              <input
                v-model="searchText"
                type="text"
                placeholder="搜索文件名或路径"
                class="cmw-search-input"
              />
            </div>
            <AppDropdown
              v-model="statusFilter"
              :options="statusDropdownOptions"
              label="范围"
              :width="176"
              :menu-min-width="190"
            />
            <div class="flex gap-2">
              <button type="button" class="cmw-toolbar-btn" @click="resetDecisions">
                <RotateCcw class="h-3.5 w-3.5" :stroke-width="2.2" />恢复默认
              </button>
              <button
                type="button"
                class="cmw-toolbar-btn"
                :disabled="submitting || loading"
                @click="$emit('refresh')"
              >
                <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" :stroke-width="2.2" />重新生成
              </button>
            </div>
          </div>

          <!-- Filter Pills -->
          <div v-if="preview" class="cmw-pill-bar">
            <button
              v-for="pill in filterPills"
              :key="pill.value"
              type="button"
              class="cmw-pill"
              :class="{ 'is-active': isFilterActive(pill.value) }"
              @click="setStatusFilter(pill.value)"
            >
              {{ pill.label }}<span class="cmw-pill-count">{{ pill.count }}</span>
            </button>
          </div>

          <!-- Loading panel：阶段 / 进度由父组件 loadingProgress 实时驱动，
               不再靠前端计时器估算。stage 映射到 6 个用户可读的步骤卡。 -->
          <div v-if="loading || progressStatus === 'failed'" class="cmw-loading-panel">
            <div class="cmw-loading-card">
              <div class="cmw-loading-orb" :class="{ 'is-error': progressStatus === 'failed' }">
                <Loader2 v-if="progressStatus !== 'failed'" class="h-6 w-6 animate-spin" :stroke-width="2.4" />
                <AlertTriangle v-else class="h-6 w-6" :stroke-width="2.4" />
              </div>
              <p class="cmw-loading-stage">{{ progressStageLabel }}</p>
              <p class="cmw-loading-message" :title="progressMessage">{{ progressMessage || '准备中…' }}</p>
              <!-- 真实 percent 进度条（来自 extract_task.progress 的 22~62 区间映射） -->
              <div class="cmw-loading-bar-track">
                <div
                  class="cmw-loading-bar"
                  :class="{ 'is-error': progressStatus === 'failed' }"
                  :style="{ width: `${progressPercent}%` }"
                />
                <span class="cmw-loading-bar-text">{{ progressPercent }}%</span>
              </div>
              <!-- 6 步骤卡：state = pending / active / done -->
              <div class="cmw-loading-steps">
                <div
                  v-for="step in displayLoadingSteps"
                  :key="step.key"
                  class="cmw-loading-step"
                  :class="{
                    'is-active': step.state === 'active',
                    'is-done': step.state === 'done',
                    'is-pending': step.state === 'pending',
                  }"
                >
                  <span class="cmw-loading-step-dot">
                    <CheckCircle2 v-if="step.state === 'done'" class="h-3 w-3" :stroke-width="2.6" />
                    <Loader2 v-else-if="step.state === 'active'" class="h-3 w-3 animate-spin" :stroke-width="2.4" />
                  </span>
                  <span class="cmw-loading-step-title">{{ step.title }}</span>
                </div>
              </div>
              <p v-if="progressStatus === 'failed'" class="cmw-loading-error">
                <AlertTriangle class="mr-1 inline-block h-3.5 w-3.5 text-rose-500" />
                {{ progressMessage }}
              </p>
              <p v-else class="cmw-loading-footnote">
                后端实际处理阶段会反映在上方步骤上；大压缩包 / 嵌套包 / 远程库存会更久，窗口会保持到完成。
              </p>
            </div>
          </div>

          <!-- 默认空态：进度 idle 且没有 preview（罕见路径，比如刚 mount 就没数据） -->
          <div v-else-if="!preview" class="cmw-empty-state">
            <GitMerge class="h-14 w-14 opacity-25" :stroke-width="1.6" />
            <p class="mt-3 text-[13px] text-slate-400">暂无合并预览数据</p>
          </div>

          <!-- Main content -->
          <div v-else class="flex-1 min-h-0 flex overflow-hidden">
            <!-- Left summary panel -->
            <div class="w-64 flex-shrink-0 border-r border-slate-100 overflow-y-auto bg-slate-50/40 p-4 space-y-4">
              <div>
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">来源路径</p>
                <p class="text-[11px] text-slate-600 font-mono break-all leading-relaxed bg-white border border-slate-100 rounded-xl p-2.5">{{ resolvedSourcePath }}</p>
              </div>
              <div>
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">{{ existingPaneLabel }}路径</p>
                <p class="text-[11px] text-slate-600 font-mono break-all leading-relaxed bg-white border border-slate-100 rounded-xl p-2.5">{{ resolvedExistingPath }}</p>
              </div>
              <div class="pt-2 border-t border-slate-200">
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-3">当前决策</p>
                <div class="space-y-2">
                  <div class="flex items-center justify-between text-xs">
                    <span class="text-emerald-700 font-medium flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500 inline-block" />取新包</span>
                    <strong class="text-emerald-800">{{ decisionSummary.useNew }}</strong>
                  </div>
                  <div class="flex items-center justify-between text-xs">
                    <span class="text-indigo-700 font-medium flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-indigo-500 inline-block" />取库存</span>
                    <strong class="text-indigo-800">{{ decisionSummary.useOld }}</strong>
                  </div>
                  <div class="flex items-center justify-between text-xs">
                    <span class="text-rose-700 font-medium flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-rose-500 inline-block" />删除</span>
                    <strong class="text-rose-800">{{ decisionSummary.delete }}</strong>
                  </div>
                </div>
              </div>
              <div v-if="isRemoteTarget" class="pt-2 border-t border-slate-200">
                <div class="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-3">
                  <Upload class="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div class="min-w-0">
                    <p class="text-[11px] font-semibold text-amber-800">远程上传合并</p>
                    <p class="text-[10px] text-amber-600 mt-0.5 leading-relaxed">差异文件将上传至远程库存，耗时取决于网速与文件量。</p>
                    <p class="text-[10px] font-bold text-amber-800 mt-1">{{ props.conflict?.context?.existing?.library_name || '远程库存' }}</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- Right diff table -->
            <div class="flex-1 min-w-0 overflow-auto">
              <table class="w-full text-sm border-collapse" style="min-width: 860px;">
                <thead class="sticky top-0 z-10 bg-slate-100/95 backdrop-blur-sm">
                  <tr>
                    <th class="px-4 py-3 text-left text-xs font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200 min-w-[260px]">差异树</th>
                    <th class="px-3 py-3 text-left text-xs font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200 w-52">{{ existingPaneLabel }}</th>
                    <th class="px-3 py-3 text-left text-xs font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200 w-52">新包内容</th>
                    <th class="px-3 py-3 text-left text-xs font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200 w-40">合并决策</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in displayRows" :key="row.node_key" class="group border-b border-slate-100 transition-colors duration-100" :class="rowBgClass(row)">
                    <td class="px-4 py-2.5">
                      <div class="flex items-center gap-2" :style="{ paddingLeft: `${row._depth * 18}px` }">
                        <button v-if="row.type === 'dir' && row._hasChildren" type="button" class="w-4 h-4 flex items-center justify-center flex-shrink-0 text-slate-400 hover:text-slate-700 transition-colors" @click="toggleCollapse(row)">
                          <ChevronRight v-if="row._collapsed" class="w-3.5 h-3.5" />
                          <ChevronDown v-else class="w-3.5 h-3.5" />
                        </button>
                        <span v-else class="w-4 flex-shrink-0" />
                        <span class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-lg" :class="statusIconBg(row)">
                          <FolderIcon v-if="row.type === 'dir'" class="w-3.5 h-3.5" />
                          <FileIcon v-else class="w-3.5 h-3.5" />
                        </span>
                        <div class="min-w-0 flex-1">
                          <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-slate-800 font-medium text-xs truncate max-w-[200px]" :title="row.name">{{ row.name }}</span>
                            <span class="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded-md" :class="statusBadgeClass(row)">{{ displayStatusInfo(row).label }}</span>
                          </div>
                          <p v-if="displayStatusInfo(row).note" class="text-[10px] text-slate-500 italic mt-0.5 truncate" :title="displayStatusInfo(row).note">{{ displayStatusInfo(row).note }}</p>
                        </div>
                      </div>
                    </td>
                    <td class="px-3 py-2.5 w-52">
                      <template v-if="hasSide(row, 'old')">
                        <p class="text-xs font-medium" :class="row.type === 'dir' ? 'text-slate-500' : 'text-slate-700'">{{ formatSidePrimary(row, 'old') }}</p>
                        <p class="text-[10px] text-slate-400 truncate">{{ formatSideTime(row, 'old') }}</p>
                      </template>
                      <span v-else class="text-[11px] text-slate-300 italic">无此项目</span>
                    </td>
                    <td class="px-3 py-2.5 w-52">
                      <template v-if="hasSide(row, 'new')">
                        <p class="text-xs font-medium" :class="row.type === 'dir' ? 'text-slate-500' : 'text-indigo-700'">{{ formatSidePrimary(row, 'new') }}</p>
                        <p class="text-[10px] text-slate-400 truncate">{{ formatSideTime(row, 'new') }}</p>
                      </template>
                      <span v-else class="text-[11px] text-slate-300 italic">无此项目</span>
                    </td>
                    <td class="px-3 py-2.5 w-40">
                      <template v-if="row.type === 'file'">
                        <select :value="decisionFor(row)" :disabled="submitting" class="w-full text-xs font-semibold bg-white border rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50 cursor-pointer" :class="decisionSelectClass(row)" @change="e => updateDecision(row, e.target.value)">
                          <option v-for="opt in decisionOptions(row)" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                        </select>
                      </template>
                      <span v-else class="text-[10px] text-slate-400">自动对齐</span>
                    </td>
                  </tr>
                  <tr v-if="!displayRows.length">
                    <td colspan="4" class="px-6 py-10 text-center text-sm text-slate-400">
                      <Search class="w-10 h-10 mx-auto mb-2 opacity-20" />
                      无匹配项目
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Footer：主操作走系统 emerald 渐变；ghost 关闭键 -->
          <footer class="cmw-footer">
            <div v-if="isRemoteTarget && preview" class="flex min-w-0 items-center gap-2 text-[12.5px] text-amber-700">
              <Upload class="h-4 w-4 flex-shrink-0 text-amber-500" :stroke-width="2.2" />
              <span class="truncate">合并结果将上传至 <strong class="font-semibold">{{ props.conflict?.context?.existing?.library_name || '远程库存' }}</strong></span>
            </div>
            <div v-else class="flex-1" />
            <div class="flex flex-shrink-0 items-center gap-3">
              <button
                type="button"
                class="cmw-action-btn is-slate"
                :disabled="loading || submitting"
                @click="close"
              >关闭</button>
              <button
                type="button"
                class="cmw-action-btn is-emerald"
                :disabled="!preview || submitting || loading"
                @click="$emit('submit')"
              >
                <Loader2 v-if="submitting" class="h-4 w-4 animate-spin" :stroke-width="2.4" />
                <GitMerge v-else class="h-4 w-4" :stroke-width="2.4" />
                <span>{{ submitLabel }}</span>
              </button>
            </div>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref } from 'vue'
import {
  GitMerge, Search, RotateCcw, RefreshCw, X, Upload,
  ChevronRight, ChevronDown,
  File as FileIcon, Folder as FolderIcon,
  CheckCircle2, Loader2, AlertTriangle
} from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  conflict: {
    type: Object,
    default: null
  },
  preview: {
    type: Object,
    default: null
  },
  decisions: {
    type: Object,
    default: () => ({})
  },
  loading: {
    type: Boolean,
    default: false
  },
  // 父组件通过 conflictApi.mergePreviewJob 轮询拿到的后端真实进度。
  // 字段：{ status: 'idle'|'running'|'completed'|'failed', stage, stage_label, message, percent }
  // 不传或全默认值时按 idle 处理，loading 面板会显示"准备中…"。
  loadingProgress: {
    type: Object,
    default: () => ({ status: 'idle', stage: '', stage_label: '', message: '', percent: 0 })
  },
  submitting: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue', 'update:decisions', 'refresh', 'submit', 'close'])

const searchText = ref('')
const statusFilter = ref('all')

const statusDropdownOptions = [
  { value: 'all', label: '全部项目' },
  { value: 'changed', label: '仅差异项' },
  { value: 'new_only', label: '仅新包独有' },
  { value: 'old_only', label: '仅库存独有' },
  { value: 'size_changed', label: '仅大小不同' },
  { value: 'other_changed', label: '仅其他差异' },
  { value: 'unchanged', label: '仅一致' },
]

// ============================================================
// 合并预览 loading panel：真实进度驱动
// ============================================================
// 后端 stage 序列（来自 ConflictResolutionService._run_merge_preview_worker）：
//   init / resolve_path / copy_archive / scan_source / extract / nested_extract /
//   filter / scan_existing / compare / done / failed
// 前端归并成 6 个用户可读步骤：
//   prep / stage / extract / filter / scan / diff
// 让 chip 跟随真实 stage 切，不再靠前端计时器估算时间阈值。
const STAGE_TO_STEP_INDEX = {
  init: 0,
  resolve_path: 0,
  copy_archive: 1,
  scan_source: 1,
  extract: 2,
  nested_extract: 2,
  filter: 3,
  scan_existing: 4,
  compare: 5,
  done: 6,           // 全部完成
  failed: -1,        // 失败：无 active 步骤
}

const progressStatus = computed(() => props.loadingProgress?.status || 'idle')
const progressStage = computed(() => props.loadingProgress?.stage || '')
const progressStageLabel = computed(() => {
  const label = props.loadingProgress?.stage_label
  if (label && String(label).trim()) return label
  if (progressStatus.value === 'failed') return '合并预览失败'
  if (progressStatus.value === 'completed') return '已完成'
  return '初始化'
})
const progressMessage = computed(() => props.loadingProgress?.message || '')
const progressPercent = computed(() => {
  const raw = Number(props.loadingProgress?.percent)
  if (!Number.isFinite(raw)) return 0
  return Math.max(0, Math.min(100, Math.round(raw)))
})

const displayLoadingSteps = computed(() => {
  const isArchive = props.conflict?.context?.new_path_kind === 'archive'
  const remoteScan = isRemoteTarget.value
  const steps = [
    { key: 'prep', title: '准备工作区' },
    { key: 'stage', title: isArchive ? '复制压缩包' : '读取目录' },
    { key: 'extract', title: isArchive ? '解压新包' : '整理新目录' },
    { key: 'filter', title: '过滤临时文件' },
    { key: 'scan', title: remoteScan ? '读取远程库存' : '扫描库存目录' },
    { key: 'diff', title: '生成差异树' },
  ]
  const currentIdx = STAGE_TO_STEP_INDEX[progressStage.value]
  // failed：当前 step 不高亮，已 done 的步骤保留 done 视觉
  if (progressStatus.value === 'failed') {
    return steps.map(step => ({ ...step, state: 'pending' }))
  }
  // completed / done：全部 done
  if (progressStatus.value === 'completed' || currentIdx === 6) {
    return steps.map(step => ({ ...step, state: 'done' }))
  }
  const idx = (typeof currentIdx === 'number' && currentIdx >= 0) ? currentIdx : 0
  return steps.map((step, i) => ({
    ...step,
    state: i < idx ? 'done' : (i === idx ? 'active' : 'pending'),
  }))
})

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})

const compareItems = computed(() => props.preview?.items || [])

const conflictTitle = computed(() => {
  if (!props.conflict) {
    return '请选择一个问题项'
  }
  return `${props.conflict.rjcode || '未识别 RJ'} · 按相对路径自动配对`
})

const existingPaneLabel = computed(() => {
  if (props.conflict?.context?.existing?.is_remote) {
    return '远程仓库'
  }
  return '现有目录'
})

const resolvedSourcePath = computed(() => {
  return props.conflict?.context?.source?.resolved_path || props.conflict?.context?.source?.path || props.conflict?.new_path || '-'
})

const resolvedExistingPath = computed(() => {
  return props.conflict?.context?.existing?.path || props.preview?.existing_path || props.conflict?.existing_path || '-'
})

const treeData = computed(() => buildTree(compareItems.value))

const filteredTreeData = computed(() => {
  return filterNodes(treeData.value, {
    searchText: searchText.value,
    status: statusFilter.value
  })
})

const displaySummary = computed(() => {
  const summary = {
    changed: 0,
    changedBoth: 0,
    newOnly: 0,
    oldOnly: 0,
    unchanged: 0
  }

  compareItems.value
    .filter(item => item.type === 'file')
    .forEach(item => {
      const key = displayStatusInfo(item).key
      if (key === 'new_only') {
        summary.newOnly += 1
        summary.changed += 1
      } else if (key === 'old_only') {
        summary.oldOnly += 1
        summary.changed += 1
      } else if (key === 'unchanged') {
        summary.unchanged += 1
      } else {
        summary.changedBoth += 1
        summary.changed += 1
      }
    })

  return summary
})

const decisionSummary = computed(() => {
  const summary = {
    useNew: 0,
    useOld: 0,
    delete: 0
  }

  compareItems.value
    .filter(item => item.type === 'file')
    .forEach(item => {
      const decision = decisionFor(item)
      if (decision === 'use_new') summary.useNew += 1
      else if (decision === 'use_old') summary.useOld += 1
      else if (decision === 'delete') summary.delete += 1
    })

  return summary
})

const filterPills = computed(() => ([
  { value: 'all', label: '全部', count: compareItems.value.filter(item => item.type === 'file').length, tone: 'all' },
  { value: 'changed', label: '差异', count: displaySummary.value.changed, tone: 'changed' },
  { value: 'new_only', label: '新包独有', count: displaySummary.value.newOnly, tone: 'new-only' },
  { value: 'old_only', label: '库存独有', count: displaySummary.value.oldOnly, tone: 'old-only' },
  { value: 'unchanged', label: '一致', count: displaySummary.value.unchanged, tone: 'unchanged' }
]))

function buildTree(items) {
  const nodeMap = new Map()

  function ensureNode(relativePath, fallbackType = 'dir') {
    const normalized = normalizePath(relativePath)
    if (!nodeMap.has(normalized)) {
      nodeMap.set(normalized, {
        node_key: `${fallbackType}:${normalized || '/'}`,
        relative_path: normalized,
        name: normalized ? normalized.split('/').pop() : '/',
        type: fallbackType,
        source: 'both',
        status: 'unchanged',
        children: []
      })
    }
    return nodeMap.get(normalized)
  }

  items.forEach(item => {
    const relativePath = normalizePath(item.relative_path)
    const node = ensureNode(relativePath, item.type || 'file')
    Object.assign(node, {
      ...item,
      node_key: `${item.type}:${relativePath || '/'}`,
      relative_path: relativePath,
      name: item.name || (relativePath ? relativePath.split('/').pop() : '/'),
      children: []
    })

    const parts = relativePath ? relativePath.split('/') : []
    for (let index = 0; index < parts.length - 1; index += 1) {
      ensureNode(parts.slice(0, index + 1).join('/'), 'dir')
    }
  })

  const roots = []
  Array.from(nodeMap.values()).forEach(node => {
    const parentPath = getParentPath(node.relative_path)
    if (!parentPath) {
      roots.push(node)
      return
    }
    const parentNode = ensureNode(parentPath, 'dir')
    if (!parentNode.children.some(child => child.node_key === node.node_key)) {
      parentNode.children.push(node)
    }
  })

  return sortNodes(roots)
}

function filterNodes(nodes, filters) {
  const query = (filters.searchText || '').trim().toLowerCase()
  const status = filters.status || 'changed'

  return nodes
    .map(node => {
      const children = filterNodes(node.children || [], filters)
      const statusInfo = displayStatusInfo(node)
      const matchesQuery =
        !query ||
        String(node.name || '').toLowerCase().includes(query) ||
        String(node.relative_path || '').toLowerCase().includes(query)
      const matchesStatus = matchStatusFilter(statusInfo.key, status)
      const includeSelf = matchesQuery && (node.type === 'dir' || matchesStatus)
      if (!includeSelf && children.length === 0) {
        return null
      }
      return {
        ...node,
        children
      }
    })
    .filter(Boolean)
}

function matchStatusFilter(key, filter) {
  if (filter === 'all') return true
  if (filter === 'changed') return key !== 'unchanged'
  if (filter === 'other_changed') return key === 'content_changed' || key === 'time_changed'
  return key === filter
}

function sortNodes(nodes) {
  const sorted = [...nodes].sort((left, right) => {
    if (left.type !== right.type) {
      return left.type === 'dir' ? -1 : 1
    }
    return String(left.relative_path || '').localeCompare(String(right.relative_path || ''), 'zh-CN')
  })

  return sorted.map(node => ({
    ...node,
    children: sortNodes(node.children || [])
  }))
}

function normalizePath(path) {
  return String(path || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

function getParentPath(path) {
  const normalized = normalizePath(path)
  if (!normalized || !normalized.includes('/')) {
    return ''
  }
  return normalized.split('/').slice(0, -1).join('/')
}

function hasSide(row, side) {
  if (side === 'new') return Boolean(row.new_path)
  return Boolean(row.old_path)
}

function isFiniteSize(value) {
  return Number.isFinite(Number(value))
}

function displayStatusInfo(row) {
  const itemType = String(row?.type || 'file')
  const status = String(row?.status || '')

  if (itemType === 'dir') {
    if (status === 'new_only') {
      return { key: 'new_only', label: '新包目录', tagType: 'success', note: '目录仅存在于新包侧' }
    }
    if (status === 'old_only') {
      return { key: 'old_only', label: '库存目录', tagType: 'info', note: '目录仅存在于库存侧' }
    }
    return { key: 'unchanged', label: '目录已对齐', tagType: 'primary', note: '' }
  }

  if (status === 'new_only') {
    return { key: 'new_only', label: '新包独有', tagType: 'success', note: '库存侧没有对应文件' }
  }
  if (status === 'old_only') {
    return { key: 'old_only', label: '库存独有', tagType: 'info', note: '新包侧没有对应文件' }
  }

  if (row?.matched_by === 'name_size') {
    return { key: 'unchanged', label: '已配对', tagType: 'primary', note: '已按文件名和大小配对，路径不同不再单独算差异' }
  }

  const newSize = Number(row?.new_size)
  const oldSize = Number(row?.old_size)
  if (isFiniteSize(newSize) && isFiniteSize(oldSize) && newSize !== oldSize) {
    return {
      key: 'size_changed',
      label: '大小不同',
      tagType: 'warning',
      note: `库存 ${formatFileSize(oldSize)} / 新包 ${formatFileSize(newSize)}`
    }
  }

  if (status === 'modified') {
    if (row?.compare_basis === 'content') {
      return { key: 'content_changed', label: '内容不同', tagType: 'danger', note: '名称与大小一致，但内容校验不同' }
    }
    return { key: 'time_changed', label: '时间不同', tagType: 'warning', note: '名称与大小一致，但修改时间不同' }
  }

  return { key: 'unchanged', label: '一致', tagType: 'primary', note: '同名且无需额外处理' }
}

function formatSidePrimary(row, side) {
  if (row.type === 'dir') return '目录'
  const value = side === 'new' ? row.new_size : row.old_size
  return formatFileSize(value)
}

function formatSideRelativePath(row, side) {
  const value = side === 'new' ? row.new_relative_path : row.old_relative_path
  return value || '/'
}

function formatSideTime(row, side) {
  const value = side === 'new' ? row.new_mtime : row.old_mtime
  return formatDate(value)
}

function decisionFor(row) {
  return props.decisions?.[row.relative_path] || props.preview?.default_decisions?.[row.relative_path] || defaultDecision(row)
}

function defaultDecision(row) {
  if (row.status === 'old_only') return 'use_old'
  return 'use_new'
}

function updateDecision(row, value) {
  const next = {
    ...(props.decisions || {}),
    [row.relative_path]: value
  }
  emit('update:decisions', next)
}

function resetDecisions() {
  emit('update:decisions', { ...(props.preview?.default_decisions || {}) })
}

function decisionOptions(row) {
  const options = []
  if (row.new_path) {
    options.push({ label: '取新包', value: 'use_new' })
  }
  if (row.old_path) {
    options.push({ label: '取库存', value: 'use_old' })
  }
  options.push({ label: '删除', value: 'delete' })
  return options
}

function resolveRowClassName({ row }) {
  const key = displayStatusInfo(row).key
  if (key === 'new_only') {
    return 'row-new-only'
  }
  if (key === 'old_only') {
    return 'row-old-only'
  }
  if (key === 'size_changed') {
    return 'row-size-changed'
  }
  if (key === 'size_changed' || key === 'time_changed' || key === 'content_changed') {
    return 'row-modified'
  }
  return 'row-unchanged'
}

function statusToneClass(row) {
  const key = displayStatusInfo(row).key
  return `tone-${key.replace(/_/g, '-')}`
}

function nodeDepth(row) {
  const relativePath = String(row?.relative_path || '').trim()
  if (!relativePath) {
    return 0
  }
  return Math.max(0, relativePath.split('/').length - 1)
}

function nodeIndentStyle(row) {
  const depth = nodeDepth(row)
  return {
    '--node-depth': String(depth),
    '--node-indent': `${depth * 18}px`
  }
}

function sidePaneToneClass(row, side) {
  const key = displayStatusInfo(row).key
  if (key === 'unchanged') {
    return 'tone-pane-neutral'
  }
  if (key === 'new_only' && side === 'new') {
    return 'tone-pane-incoming'
  }
  if (key === 'old_only' && side === 'old') {
    return 'tone-pane-existing'
  }
  if ((key === 'size_changed' || key === 'time_changed' || key === 'content_changed') && hasSide(row, side)) {
    return side === 'new' ? 'tone-pane-incoming-soft' : 'tone-pane-existing-soft'
  }
  return side === 'new' ? 'tone-pane-incoming' : 'tone-pane-existing'
}

function setStatusFilter(value) {
  statusFilter.value = value
}

function isFilterActive(value) {
  return statusFilter.value === value
}

const isRemoteTarget = computed(() => Boolean(props.conflict?.context?.existing?.is_remote))

const submitLabel = computed(() => {
  if (props.submitting) {
    return isRemoteTarget.value ? '正在上传至服务器...' : '提交中...'
  }
  return isRemoteTarget.value ? '上传并提交合并结果' : '生成并提交合并结果'
})

const collapsedPaths = ref(new Set())

function toggleCollapse(node) {
  const path = node.relative_path
  const newSet = new Set(collapsedPaths.value)
  if (newSet.has(path)) {
    newSet.delete(path)
  } else {
    newSet.add(path)
  }
  collapsedPaths.value = newSet
}

function flattenTree(nodes, depth = 0) {
  const result = []
  for (const node of nodes) {
    const isCollapsed = collapsedPaths.value.has(node.relative_path)
    result.push({
      ...node,
      _depth: depth,
      _collapsed: isCollapsed,
      _hasChildren: (node.children || []).length > 0
    })
    if (!isCollapsed && node.children && node.children.length > 0) {
      result.push(...flattenTree(node.children, depth + 1))
    }
  }
  return result
}

const displayRows = computed(() => flattenTree(filteredTreeData.value))

function close() {
  // submitting 期间不允许关闭；loading 期间允许（用户想取消正在跑的 7z），
  // 父组件监听 @close 取消 polling，后端 worker 自身的 cleanup 会兜底回收。
  if (props.submitting) return
  visible.value = false
  emit('close')
}

function rowBgClass(row) {
  const key = displayStatusInfo(row).key
  if (key === 'new_only') return 'bg-emerald-50/60 hover:bg-emerald-50'
  if (key === 'old_only') return 'bg-slate-100/60 hover:bg-slate-100'
  if (key === 'size_changed' || key === 'content_changed') return 'bg-amber-50/60 hover:bg-amber-50'
  if (key === 'time_changed') return 'bg-sky-50/40 hover:bg-sky-50/60'
  return 'hover:bg-slate-50/60'
}

function statusIconBg(row) {
  const key = displayStatusInfo(row).key
  if (row.type === 'dir') return 'bg-slate-100 text-slate-500'
  if (key === 'new_only') return 'bg-emerald-100 text-emerald-600'
  if (key === 'old_only') return 'bg-slate-200 text-slate-500'
  if (key === 'size_changed' || key === 'content_changed') return 'bg-amber-100 text-amber-600'
  if (key === 'time_changed') return 'bg-sky-100 text-sky-600'
  return 'bg-slate-100 text-slate-400'
}

function statusBadgeClass(row) {
  const key = displayStatusInfo(row).key
  if (key === 'new_only') return 'bg-emerald-100 text-emerald-700'
  if (key === 'old_only') return 'bg-slate-200 text-slate-600'
  if (key === 'size_changed') return 'bg-amber-100 text-amber-700'
  if (key === 'content_changed') return 'bg-rose-100 text-rose-700'
  if (key === 'time_changed') return 'bg-sky-100 text-sky-700'
  return 'bg-slate-100 text-slate-500'
}

function decisionSelectClass(row) {
  const decision = decisionFor(row)
  if (decision === 'use_new') return 'border-emerald-200 text-emerald-800 bg-emerald-50'
  if (decision === 'use_old') return 'border-indigo-200 text-indigo-800 bg-indigo-50'
  if (decision === 'delete') return 'border-rose-200 text-rose-800 bg-rose-50'
  return 'border-slate-200 text-slate-700'
}

function formatFileSize(size) {
  if (size === null || size === undefined) return '-'
  const value = Number(size)
  if (!Number.isFinite(value) || value < 0) return '-'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = value / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(current >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

function formatDate(value) {
  if (!value && value !== 0) return '-'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
/* ============================================================
   ConflictMergeWorkbench 视觉风格
   ============================================================
   全部对齐 Library.mediaPreviewDialog 的玻璃面板范式：
   - 白玻璃 shell（rounded-22 + backdrop-blur-2xl 由父级 div 提供）
   - 主操作 emerald 渐变；状态色用 indigo / amber / emerald
   - 不再使用 amber radial gradient / amber 主色
*/

/* Transition：fade + 轻位移 */
.cmw-fade-enter-active,
.cmw-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
.cmw-fade-enter-from,
.cmw-fade-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}

/* Shell：白底玻璃面板 */
.cmw-shell {
  position: relative;
  display: flex;
  width: min(94vw, 1480px);
  height: 88vh;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 22px;
  background: #fff;
  box-shadow:
    0 24px 80px rgba(15, 23, 42, 0.2),
    0 1px 0 rgba(255, 255, 255, 0.9) inset;
}

/* Header：纯玻璃 */
.cmw-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.85);
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  padding: 16px 22px;
}

.cmw-icon {
  display: inline-flex;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: #4f46e5;
  background: linear-gradient(180deg, #eef2ff 0%, #e0e7ff 100%);
  box-shadow:
    0 10px 24px rgba(79, 70, 229, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.cmw-title {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.cmw-subtitle {
  max-width: 640px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  color: #64748b;
}

.cmw-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 999px;
  padding: 2px 8px;
  background: #fff;
  color: #475569;
  font-size: 11.5px;
  font-weight: 700;
}

.cmw-tag.is-amber {
  border-color: rgba(245, 158, 11, 0.32);
  color: #b45309;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
}

.cmw-count-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 999px;
  padding: 6px 11px;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-count-chip:hover {
  transform: translateY(-1px) scale(1.03);
  border-color: rgba(148, 163, 184, 0.65);
}

.cmw-count-chip.is-active {
  color: #fff;
}

.cmw-count-chip.is-active.is-amber {
  border-color: #f59e0b;
  background: linear-gradient(180deg, #fbbf24 0%, #f59e0b 52%, #d97706 100%);
  box-shadow: 0 10px 22px rgba(245, 158, 11, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.cmw-count-chip.is-active.is-emerald {
  border-color: #10b981;
  background: linear-gradient(180deg, #34d399 0%, #10b981 54%, #059669 100%);
  box-shadow: 0 10px 22px rgba(16, 185, 129, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.cmw-count-chip.is-active.is-slate {
  border-color: #475569;
  background: linear-gradient(180deg, #64748b 0%, #475569 52%, #334155 100%);
  box-shadow: 0 10px 22px rgba(71, 85, 105, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.3);
}

/* Close 按钮：玻璃 + hover rotate */
.cmw-close-btn {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-close-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.04);
  border-color: rgba(148, 163, 184, 0.55);
  background: #fff;
  color: #0f172a;
}

.cmw-close-btn:hover:not(:disabled) svg {
  transform: rotate(90deg);
}

.cmw-close-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Toolbar */
.cmw-toolbar {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(241, 245, 249, 0.95);
  background: rgba(255, 255, 255, 0.86);
  padding: 12px 22px;
}

.cmw-search-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  padding: 9px 12px 9px 36px;
  font-size: 13px;
  color: #334155;
  outline: none;
  transition: all 0.2s ease;
}

.cmw-search-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.16);
}

.cmw-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 10px;
  background: #fff;
  color: #475569;
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-toolbar-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.34);
  color: #4338ca;
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.cmw-toolbar-btn:hover:not(:disabled) svg {
  transform: rotate(-8deg) scale(1.08);
}

.cmw-toolbar-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Pill bar */
.cmw-pill-bar {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(241, 245, 249, 0.95);
  padding: 10px 22px;
}

.cmw-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 999px;
  background: #fff;
  color: #475569;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-pill:hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.42);
  color: #4338ca;
}

.cmw-pill.is-active {
  border-color: #6366f1;
  background: linear-gradient(180deg, #818cf8 0%, #6366f1 52%, #4f46e5 100%);
  color: #fff;
  box-shadow: 0 10px 22px rgba(99, 102, 241, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.32);
}

.cmw-pill-count {
  display: inline-flex;
  min-width: 22px;
  justify-content: center;
  font-weight: 800;
}

/* Loading panel */
.cmw-loading-panel {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.94) 0%, rgba(255, 255, 255, 0.98) 100%);
  padding: 24px;
}

.cmw-loading-card {
  width: min(640px, 100%);
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  padding: 28px;
  text-align: center;
  box-shadow:
    0 22px 56px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.cmw-loading-orb {
  position: relative;
  display: inline-flex;
  width: 64px;
  height: 64px;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  color: #4f46e5;
  background: linear-gradient(180deg, #eef2ff 0%, #e0e7ff 100%);
  box-shadow:
    0 18px 38px rgba(79, 70, 229, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.cmw-loading-orb::after {
  position: absolute;
  inset: -7px;
  border: 2px solid rgba(99, 102, 241, 0.22);
  border-top-color: #6366f1;
  border-radius: 22px;
  animation: cmw-spin 1.1s linear infinite;
  content: '';
}

.cmw-loading-orb.is-error {
  color: #dc2626;
  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);
  box-shadow:
    0 18px 38px rgba(220, 38, 38, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.cmw-loading-orb.is-error::after {
  border-color: rgba(220, 38, 38, 0.22);
  border-top-color: #dc2626;
  animation: none;
}

.cmw-loading-stage {
  margin-top: 18px;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.cmw-loading-message {
  margin-top: 6px;
  font-size: 12.5px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-loading-bar-track {
  position: relative;
  height: 10px;
  margin-top: 18px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.cmw-loading-bar {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #6366f1 0%, #10b981 56%, #2563eb 100%);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.22);
  transition: width 0.45s ease;
}

.cmw-loading-bar.is-error {
  background: linear-gradient(90deg, #ef4444 0%, #dc2626 100%);
  box-shadow: 0 8px 18px rgba(220, 38, 38, 0.22);
}

.cmw-loading-bar-text {
  position: absolute;
  top: -22px;
  right: 0;
  font-size: 11px;
  font-weight: 800;
  color: #475569;
}

.cmw-loading-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
  text-align: left;
}

.cmw-loading-step {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  padding: 9px 11px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  transition: all 0.3s ease;
}

.cmw-loading-step.is-active {
  border-color: rgba(99, 102, 241, 0.42);
  color: #4338ca;
  background: #eef2ff;
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.14);
}

.cmw-loading-step.is-done {
  border-color: rgba(16, 185, 129, 0.3);
  color: #047857;
  background: #ecfdf5;
}

.cmw-loading-step-dot {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
}

.cmw-loading-step.is-active .cmw-loading-step-dot {
  background: rgba(99, 102, 241, 0.18);
  color: #4338ca;
}

.cmw-loading-step.is-done .cmw-loading-step-dot {
  background: rgba(16, 185, 129, 0.18);
  color: #047857;
}

.cmw-loading-step-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-loading-footnote,
.cmw-loading-error {
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.cmw-loading-error {
  color: #b91c1c;
  font-weight: 700;
}

/* 空态：仅在 idle 且无 preview 时显示（罕见路径） */
.cmw-empty-state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #94a3b8;
}

/* Footer */
.cmw-footer {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid rgba(226, 232, 240, 0.85);
  background: rgba(255, 255, 255, 0.92);
  padding: 14px 22px;
}

/* Action 按钮：emerald 主 / slate ghost */
.cmw-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 10px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-action-btn.is-slate {
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #fff;
  color: #475569;
}

.cmw-action-btn.is-slate:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(148, 163, 184, 0.5);
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.cmw-action-btn.is-emerald {
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #fff;
  background: linear-gradient(180deg, #34d399 0%, #10b981 52%, #059669 100%);
  box-shadow:
    0 14px 28px rgba(16, 185, 129, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.cmw-action-btn.is-emerald:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow:
    0 18px 34px rgba(16, 185, 129, 0.36),
    inset 0 1px 0 rgba(255, 255, 255, 0.4);
}

.cmw-action-btn:hover:not(:disabled) svg {
  transform: rotate(-8deg) scale(1.08);
}

.cmw-action-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-action-btn:active:not(:disabled),
.cmw-toolbar-btn:active:not(:disabled),
.cmw-close-btn:active:not(:disabled),
.cmw-pill:active:not(:disabled),
.cmw-count-chip:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
}

button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.55; }

@keyframes cmw-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .cmw-shell {
    width: 96vw;
    height: 92vh;
  }

  .cmw-loading-steps {
    grid-template-columns: 1fr;
  }
}
</style>

