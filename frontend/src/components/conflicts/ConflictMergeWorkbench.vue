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
          class="relative bg-white rounded-3xl shadow-2xl flex flex-col overflow-hidden"
          style="width: 94vw; height: 88vh;"
          @mousedown.stop
        >
          <!-- Header -->
          <div class="flex-none px-6 py-4 border-b border-slate-200 bg-gradient-to-br from-slate-50 to-white">
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2.5 mb-1">
                  <GitMerge class="w-5 h-5 text-amber-500 flex-shrink-0" />
                  <h3 class="text-lg font-bold text-slate-900">目录差异工作台</h3>
                  <span v-if="isRemoteTarget" class="flex items-center gap-1 px-2.5 py-0.5 bg-amber-50 text-amber-700 text-xs font-semibold border border-amber-200 rounded-full">
                    <Upload class="w-3 h-3" />
                    远程合并
                  </span>
                </div>
                <p class="text-sm text-slate-500 truncate">{{ conflictTitle }}</p>
              </div>
              <div v-if="preview" class="flex flex-wrap gap-2 justify-end flex-shrink-0">
                <button type="button" class="flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-semibold cursor-pointer transition-all duration-200 hover:-translate-y-0.5" :class="statusFilter === 'changed' ? 'bg-amber-500 text-white border-amber-500' : 'bg-white border-amber-200 text-amber-700 hover:border-amber-400'" @click="setStatusFilter('changed')">
                  <span>差异</span><strong>{{ displaySummary.changed }}</strong>
                </button>
                <button type="button" class="flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-semibold cursor-pointer transition-all duration-200 hover:-translate-y-0.5" :class="statusFilter === 'new_only' ? 'bg-emerald-500 text-white border-emerald-500' : 'bg-white border-emerald-200 text-emerald-700 hover:border-emerald-400'" @click="setStatusFilter('new_only')">
                  <span>新包独有</span><strong>{{ displaySummary.newOnly }}</strong>
                </button>
                <button type="button" class="flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-semibold cursor-pointer transition-all duration-200 hover:-translate-y-0.5" :class="statusFilter === 'old_only' ? 'bg-slate-600 text-white border-slate-600' : 'bg-white border-slate-200 text-slate-600 hover:border-slate-400'" @click="setStatusFilter('old_only')">
                  <span>库存独有</span><strong>{{ displaySummary.oldOnly }}</strong>
                </button>
                <button type="button" class="flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-semibold cursor-pointer transition-all duration-200 hover:-translate-y-0.5" :class="statusFilter === 'unchanged' ? 'bg-slate-200 text-slate-700 border-slate-300' : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'" @click="setStatusFilter('unchanged')">
                  <span>一致</span><strong>{{ displaySummary.unchanged }}</strong>
                </button>
              </div>
              <button type="button" class="flex-shrink-0 w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition-all duration-200" @click="close">
                <X class="w-5 h-5" />
              </button>
            </div>
          </div>

          <!-- Toolbar -->
          <div class="flex-none px-6 py-3 border-b border-slate-100 flex items-center gap-3 flex-wrap bg-white/80">
            <div class="relative flex-1 min-w-[180px]">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
              <input v-model="searchText" type="text" placeholder="搜索文件名或路径" class="w-full pl-9 pr-3 py-2 text-sm bg-white border border-slate-200 rounded-xl text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400" />
            </div>
            <select v-model="statusFilter" class="px-3 py-2 text-sm bg-white border border-slate-200 rounded-xl text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 cursor-pointer">
              <option value="all">全部项目</option>
              <option value="changed">仅差异项</option>
              <option value="new_only">仅新包独有</option>
              <option value="old_only">仅库存独有</option>
              <option value="size_changed">仅大小不同</option>
              <option value="other_changed">仅其他差异</option>
              <option value="unchanged">仅一致</option>
            </select>
            <div class="flex gap-2">
              <button type="button" class="px-3 py-2 text-sm font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400 rounded-xl transition-all duration-200 flex items-center gap-1.5" @click="resetDecisions">
                <RotateCcw class="w-3.5 h-3.5" />恢复默认
              </button>
              <button type="button" class="px-3 py-2 text-sm font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400 rounded-xl transition-all duration-200 flex items-center gap-1.5 disabled:opacity-50" :disabled="submitting || loading" @click="$emit('refresh')">
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
          <div v-if="loading" class="flex-1 flex items-center justify-center bg-slate-50/50">
            <div class="text-center">
              <div class="w-10 h-10 border-[3px] border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p class="text-sm font-medium text-slate-700">正在生成合并预览...</p>
              <p class="text-xs text-slate-400 mt-1">比对新旧文件并同步决策面板</p>
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
              <button type="button" class="px-5 py-2.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400 rounded-2xl transition-all duration-200 disabled:opacity-50" :disabled="submitting" @click="close">关闭</button>
              <button type="button" class="px-6 py-2.5 text-sm font-bold text-white rounded-2xl transition-all duration-200 disabled:opacity-50 flex items-center gap-2" :class="submitting ? 'bg-amber-400 cursor-not-allowed' : 'bg-gradient-to-br from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 hover:-translate-y-0.5 shadow-lg shadow-amber-500/30 active:scale-95'" :disabled="!preview || submitting" @click="$emit('submit')">
                <span v-if="submitting" class="w-4 h-4 border-2 border-white/60 border-t-white rounded-full animate-spin" />
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
import { computed, ref } from 'vue'
import {
  GitMerge, Search, RotateCcw, RefreshCw, X, Upload,
  ChevronRight, ChevronDown,
  File as FileIcon, Folder as FolderIcon
} from 'lucide-vue-next'

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
  if (!props.submitting) {
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
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }
</style>

