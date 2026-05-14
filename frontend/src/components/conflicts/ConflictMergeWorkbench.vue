<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        @mousedown.self="close"
      >
        <div class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" @click="close" />
        <div
          class="merge-workbench-shell"
          @mousedown.stop
        >
          <!-- Header -->
          <div class="merge-workbench-header">
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2.5 mb-1">
                  <span class="merge-workbench-icon">
                    <GitMerge class="w-5 h-5" />
                  </span>
                  <h3 class="merge-workbench-title">目录差异工作台</h3>
                  <span v-if="isRemoteTarget" class="merge-workbench-chip is-amber">
                    <Upload class="w-3 h-3" />
                    远程合并
                  </span>
                </div>
                <p class="merge-workbench-subtitle">{{ conflictTitle }}</p>
              </div>
              <div v-if="preview" class="flex flex-wrap gap-2 justify-end flex-shrink-0">
                <button type="button" class="merge-count-chip" :class="{ 'is-active is-amber': statusFilter === 'changed' }" @click="setStatusFilter('changed')">
                  <span>差异</span><strong>{{ displaySummary.changed }}</strong>
                </button>
                <button type="button" class="merge-count-chip" :class="{ 'is-active is-emerald': statusFilter === 'new_only' }" @click="setStatusFilter('new_only')">
                  <span>新包独有</span><strong>{{ displaySummary.newOnly }}</strong>
                </button>
                <button type="button" class="merge-count-chip" :class="{ 'is-active is-slate': statusFilter === 'old_only' }" @click="setStatusFilter('old_only')">
                  <span>库存独有</span><strong>{{ displaySummary.oldOnly }}</strong>
                </button>
                <button type="button" class="merge-count-chip" :class="{ 'is-active is-slate': statusFilter === 'unchanged' }" @click="setStatusFilter('unchanged')">
                  <span>一致</span><strong>{{ displaySummary.unchanged }}</strong>
                </button>
              </div>
              <button type="button" class="merge-icon-btn" :disabled="loading || submitting" @click="close">
                <X class="w-5 h-5" />
              </button>
            </div>
          </div>

          <!-- Toolbar -->
          <div class="merge-workbench-toolbar">
            <div class="relative flex-1 min-w-[180px]">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
              <input v-model="searchText" type="text" placeholder="搜索文件名或路径" class="merge-search-input" />
            </div>
            <AppDropdown
              v-model="statusFilter"
              :options="statusDropdownOptions"
              label="范围"
              :width="176"
              :menu-min-width="190"
            />
            <div class="flex gap-2">
              <button type="button" class="merge-toolbar-btn" @click="resetDecisions">
                <RotateCcw class="w-3.5 h-3.5" />恢复默认
              </button>
              <button type="button" class="merge-toolbar-btn" :disabled="submitting || loading" @click="$emit('refresh')">
                <RefreshCw class="w-3.5 h-3.5" :class="loading ? 'animate-spin' : ''" />重新生成
              </button>
            </div>
          </div>

          <!-- Filter Pills -->
          <div v-if="preview" class="flex-none px-6 py-2.5 border-b border-slate-100 flex items-center gap-2 flex-wrap">
            <button v-for="pill in filterPills" :key="pill.value" type="button" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all duration-200" :class="isFilterActive(pill.value) ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white border-slate-200 text-slate-600 hover:border-indigo-400 hover:text-indigo-600'" @click="setStatusFilter(pill.value)">
              {{ pill.label }}<span class="font-bold">{{ pill.count }}</span>
            </button>
          </div>

          <!-- Loading -->
          <div v-if="loading" class="merge-loading-panel">
            <div class="merge-loading-card">
              <div class="merge-loading-orbit">
                <GitMerge class="w-7 h-7" />
              </div>
              <p class="merge-loading-title">{{ activeLoadingStep.title }}</p>
              <p class="merge-loading-desc">{{ activeLoadingStep.description }}</p>
              <div class="merge-loading-track">
                <div class="merge-loading-bar" :style="{ width: `${loadingProgress}%` }" />
              </div>
              <div class="merge-loading-steps">
                <div
                  v-for="(step, index) in loadingSteps"
                  :key="step.key"
                  class="merge-loading-step"
                  :class="{ 'is-active': index === activeLoadingIndex, 'is-done': index < activeLoadingIndex }"
                >
                  <span class="merge-loading-dot">
                    <CheckCircle2 v-if="index < activeLoadingIndex" class="w-3 h-3" />
                    <Loader2 v-else-if="index === activeLoadingIndex" class="w-3 h-3 animate-spin" />
                  </span>
                  <span>{{ step.title }}</span>
                </div>
              </div>
              <p class="merge-loading-footnote">
                已等待 {{ loadingElapsedSeconds }} 秒。大压缩包、分卷包或远程库存会更久，窗口会保持在这里直到后端返回。
              </p>
            </div>
          </div>

          <!-- No preview -->
          <div v-else-if="!preview" class="flex-1 flex items-center justify-center bg-slate-50/50">
            <div class="text-center text-slate-400">
              <GitMerge class="w-16 h-16 mx-auto mb-3 opacity-20" />
              <p class="text-sm">暂无合并预览数据</p>
            </div>
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
                        <select :value="decisionFor(row)" :disabled="submitting" class="w-full text-xs font-semibold bg-white border rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400 disabled:opacity-50 cursor-pointer" :class="decisionSelectClass(row)" @change="e => updateDecision(row, e.target.value)">
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

          <!-- Footer -->
          <div class="flex-none px-6 py-4 border-t border-slate-100 flex items-center justify-between gap-4 bg-white/90">
            <div v-if="isRemoteTarget && preview" class="flex items-center gap-2 text-sm text-amber-700">
              <Upload class="w-4 h-4 text-amber-500 flex-shrink-0" />
              <span>合并结果将上传至 <strong>{{ props.conflict?.context?.existing?.library_name || '远程库存' }}</strong></span>
            </div>
            <div v-else class="flex-1" />
            <div class="flex items-center gap-3">
              <button type="button" class="merge-footer-btn is-ghost" :disabled="loading || submitting" @click="close">关闭</button>
              <button type="button" class="merge-footer-btn is-primary" :disabled="!preview || submitting || loading" @click="$emit('submit')">
                <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
                <GitMerge v-else class="w-4 h-4" />
                <span>{{ submitLabel }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  GitMerge, Search, RotateCcw, RefreshCw, X, Upload,
  ChevronRight, ChevronDown,
  File as FileIcon, Folder as FolderIcon,
  CheckCircle2, Loader2
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
  submitting: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue', 'update:decisions', 'refresh', 'submit'])

const searchText = ref('')
const statusFilter = ref('all')
const loadingElapsedSeconds = ref(0)
let loadingTimer = null

const statusDropdownOptions = [
  { value: 'all', label: '全部项目' },
  { value: 'changed', label: '仅差异项' },
  { value: 'new_only', label: '仅新包独有' },
  { value: 'old_only', label: '仅库存独有' },
  { value: 'size_changed', label: '仅大小不同' },
  { value: 'other_changed', label: '仅其他差异' },
  { value: 'unchanged', label: '仅一致' },
]

const loadingSteps = computed(() => {
  const isArchive = props.conflict?.context?.new_path_kind === 'archive'
  return [
    { key: 'prepare', title: '准备工作区', description: '创建临时目录并确认新旧路径' },
    { key: 'stage', title: isArchive ? '复制压缩包' : '复制目录', description: isArchive ? '把待处理压缩包放入合并工作区' : '把待处理目录放入合并工作区' },
    { key: 'extract', title: isArchive ? '解压新包' : '整理新目录', description: isArchive ? '调用解压器展开内容，分卷和大包会在这里停留更久' : '对新目录做过滤前准备' },
    { key: 'filter', title: '过滤临时目录', description: '按项目规则清理无效文件并保留可入库内容' },
    { key: 'scan', title: isRemoteTarget.value ? '读取远程库存' : '扫描库存目录', description: isRemoteTarget.value ? '从远程库存读取目录清单' : '扫描现有目录的文件树' },
    { key: 'diff', title: '生成差异树', description: '按相对路径生成逐文件合并决策' },
  ]
})

const activeLoadingIndex = computed(() => {
  if (!props.loading) return loadingSteps.value.length - 1
  const elapsed = loadingElapsedSeconds.value
  if (elapsed < 2) return 0
  if (elapsed < 6) return 1
  if (elapsed < 18) return 2
  if (elapsed < 28) return 3
  if (elapsed < 42) return 4
  return 5
})

const activeLoadingStep = computed(() => loadingSteps.value[activeLoadingIndex.value] || loadingSteps.value[0])

const loadingProgress = computed(() => {
  if (!props.loading) return 100
  const base = Math.min(92, 12 + loadingElapsedSeconds.value * 1.7)
  const stepFloor = activeLoadingIndex.value * 14
  return Math.max(stepFloor, Math.round(base))
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

watch(
  () => props.loading,
  (value) => {
    if (loadingTimer) {
      clearInterval(loadingTimer)
      loadingTimer = null
    }
    if (!value) {
      loadingElapsedSeconds.value = 0
      return
    }
    loadingElapsedSeconds.value = 0
    loadingTimer = setInterval(() => {
      loadingElapsedSeconds.value += 1
    }, 1000)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (loadingTimer) {
    clearInterval(loadingTimer)
    loadingTimer = null
  }
})

function close() {
  if (!props.submitting && !props.loading) {
    visible.value = false
  }
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
.merge-workbench-shell {
  position: relative;
  display: flex;
  width: min(94vw, 1480px);
  height: 88vh;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.2), 0 1px 0 rgba(255, 255, 255, 0.9) inset;
}

.merge-workbench-header {
  flex: none;
  border-bottom: 1px solid rgba(226, 232, 240, 0.9);
  background:
    radial-gradient(circle at 18% 0%, rgba(245, 158, 11, 0.12), transparent 34%),
    linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  padding: 18px 24px;
}

.merge-workbench-icon {
  display: inline-flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: #d97706;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  box-shadow: 0 10px 24px rgba(245, 158, 11, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.merge-workbench-title {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.merge-workbench-subtitle {
  max-width: 720px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #64748b;
}

.merge-workbench-chip,
.merge-count-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 999px;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.merge-workbench-chip {
  padding: 3px 9px;
}

.merge-workbench-chip.is-amber {
  border-color: rgba(245, 158, 11, 0.24);
  color: #b45309;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
}

.merge-count-chip {
  padding: 7px 11px;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.merge-count-chip:hover {
  transform: translateY(-1px) scale(1.03);
  border-color: rgba(148, 163, 184, 0.65);
}

.merge-count-chip.is-active {
  color: #fff;
}

.merge-count-chip.is-active.is-amber {
  border-color: #f59e0b;
  background: linear-gradient(180deg, #fbbf24 0%, #f59e0b 52%, #d97706 100%);
  box-shadow: 0 10px 22px rgba(245, 158, 11, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.merge-count-chip.is-active.is-emerald {
  border-color: #10b981;
  background: linear-gradient(180deg, #34d399 0%, #10b981 54%, #059669 100%);
  box-shadow: 0 10px 22px rgba(16, 185, 129, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.merge-count-chip.is-active.is-slate {
  border-color: #475569;
  background: linear-gradient(180deg, #64748b 0%, #475569 52%, #334155 100%);
  box-shadow: 0 10px 22px rgba(71, 85, 105, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.3);
}

.merge-icon-btn {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 10px;
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.merge-icon-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(226, 232, 240, 0.95);
  background: #f8fafc;
  color: #0f172a;
}

.merge-workbench-toolbar {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(241, 245, 249, 0.95);
  background: rgba(255, 255, 255, 0.86);
  padding: 12px 24px;
}

.merge-search-input {
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

.merge-search-input:focus {
  border-color: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.14);
}

.merge-toolbar-btn,
.merge-footer-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.merge-toolbar-btn {
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #fff;
  color: #475569;
  padding: 9px 12px;
}

.merge-toolbar-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(245, 158, 11, 0.34);
  color: #b45309;
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.merge-toolbar-btn:hover:not(:disabled) svg,
.merge-footer-btn:hover:not(:disabled) svg,
.merge-icon-btn:hover:not(:disabled) svg {
  transform: rotate(-8deg) scale(1.08);
}

.merge-toolbar-btn svg,
.merge-footer-btn svg,
.merge-icon-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.merge-loading-panel {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  background:
    linear-gradient(180deg, rgba(248, 250, 252, 0.94) 0%, rgba(255, 255, 255, 0.98) 100%),
    radial-gradient(circle at 50% 18%, rgba(245, 158, 11, 0.12), transparent 32%);
  padding: 24px;
}

.merge-loading-card {
  width: min(640px, 100%);
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.94);
  padding: 28px;
  text-align: center;
  box-shadow: 0 22px 56px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.merge-loading-orbit {
  position: relative;
  display: inline-flex;
  width: 64px;
  height: 64px;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  color: #d97706;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  box-shadow: 0 18px 38px rgba(245, 158, 11, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.merge-loading-orbit::after {
  position: absolute;
  inset: -7px;
  border: 2px solid rgba(245, 158, 11, 0.24);
  border-top-color: #f59e0b;
  border-radius: 22px;
  animation: merge-spin 1s linear infinite;
  content: '';
}

.merge-loading-title {
  margin-top: 18px;
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
}

.merge-loading-desc {
  margin-top: 6px;
  font-size: 13px;
  color: #64748b;
}

.merge-loading-track {
  height: 8px;
  margin-top: 20px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.merge-loading-bar {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #f59e0b 0%, #10b981 56%, #2563eb 100%);
  box-shadow: 0 8px 18px rgba(245, 158, 11, 0.24);
  transition: width 0.45s ease;
}

.merge-loading-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
  text-align: left;
}

.merge-loading-step {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  padding: 9px 10px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}

.merge-loading-step.is-active {
  border-color: rgba(245, 158, 11, 0.4);
  color: #b45309;
  background: #fffbeb;
}

.merge-loading-step.is-done {
  border-color: rgba(16, 185, 129, 0.25);
  color: #047857;
  background: #ecfdf5;
}

.merge-loading-dot {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
}

.merge-loading-footnote {
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.merge-footer-btn {
  padding: 10px 20px;
}

.merge-footer-btn.is-ghost {
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #fff;
  color: #475569;
}

.merge-footer-btn.is-ghost:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(148, 163, 184, 0.5);
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.merge-footer-btn.is-primary {
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: #fff;
  background: linear-gradient(180deg, #fbbf24 0%, #f59e0b 52%, #d97706 100%);
  box-shadow: 0 14px 28px rgba(245, 158, 11, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.merge-footer-btn.is-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 18px 34px rgba(245, 158, 11, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.4);
}

.merge-footer-btn:active:not(:disabled),
.merge-toolbar-btn:active:not(:disabled),
.merge-icon-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
}

button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.55; }

@keyframes merge-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .merge-workbench-shell {
    width: 96vw;
    height: 92vh;
  }

  .merge-loading-steps {
    grid-template-columns: 1fr;
  }
}
</style>

