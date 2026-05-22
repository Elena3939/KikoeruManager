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
                  <span v-if="isRemoteTarget" class="cmw-tag">
                    <Upload class="h-3 w-3" :stroke-width="2.4" />
                    远程合并
                  </span>
                </div>
                <p class="cmw-subtitle" :title="conflictTitle">{{ conflictTitle }}</p>
              </div>
            </div>
            <div class="flex flex-shrink-0 items-center gap-2">
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
            <div class="flex flex-wrap items-center gap-2">
              <!-- 批量决策快捷：借鉴 GitKraken / Sourcetree 顶部 stage-all 控件 -->
              <div v-if="preview" class="cmw-bulk-group">
                <button type="button" class="cmw-bulk-btn" :disabled="submitting" title="所有文件改为使用新包版本" @click="batchSetDecision('use_new')">
                  <ArrowDownToLine class="h-3 w-3" :stroke-width="2.4" />全取新包
                </button>
                <button type="button" class="cmw-bulk-btn" :disabled="submitting" title="所有文件改为保留库存版本" @click="batchSetDecision('use_old')">
                  <Archive class="h-3 w-3" :stroke-width="2.4" />全取库存
                </button>
              </div>
              <button type="button" class="cmw-toolbar-btn" @click="resetDecisions" title="按默认规则重新判断每个文件">
                <RotateCcw class="h-3.5 w-3.5" :stroke-width="2.2" />智能默认
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
            <!-- Left summary panel：克制灰阶，去三色 dot 强字 -->
            <aside class="cmw-summary-pane">
              <div class="cmw-summary-block">
                <p class="cmw-summary-label">来源路径</p>
                <p class="cmw-summary-path">{{ resolvedSourcePath }}</p>
              </div>
              <div class="cmw-summary-block">
                <p class="cmw-summary-label">{{ existingPaneLabel }}路径</p>
                <p class="cmw-summary-path">{{ resolvedExistingPath }}</p>
              </div>
              <div class="cmw-summary-block cmw-summary-decisions">
                <p class="cmw-summary-label">当前决策</p>
                <div class="cmw-summary-decision-row">
                  <span class="cmw-decision-key"><i class="cmw-dot is-new" />取新包</span>
                  <span class="cmw-decision-val">{{ decisionSummary.useNew }}</span>
                </div>
                <div class="cmw-summary-decision-row">
                  <span class="cmw-decision-key"><i class="cmw-dot is-old" />取库存</span>
                  <span class="cmw-decision-val">{{ decisionSummary.useOld }}</span>
                </div>
                <div class="cmw-summary-decision-row">
                  <span class="cmw-decision-key"><i class="cmw-dot is-del" />删除</span>
                  <span class="cmw-decision-val">{{ decisionSummary.delete }}</span>
                </div>
              </div>
              <div v-if="isRemoteTarget" class="cmw-summary-remote">
                <Upload class="h-3.5 w-3.5 flex-shrink-0" :stroke-width="2.2" />
                <div class="min-w-0">
                  <p class="cmw-summary-remote-title">远程上传合并</p>
                  <p class="cmw-summary-remote-desc">差异文件将上传至远程库存，耗时取决于网速与文件量。</p>
                  <p class="cmw-summary-remote-name">{{ props.conflict?.context?.existing?.library_name || '远程库存' }}</p>
                </div>
              </div>
            </aside>

            <!-- Right diff table：借鉴 GitHub PR review + VSCode Source Control 的 status glyph + segmented decision -->
            <div class="flex-1 min-w-0 overflow-auto">
              <table class="cmw-diff-table">
                <thead>
                  <tr>
                    <th class="cmw-diff-th cmw-diff-th-marker" aria-hidden="true"></th>
                    <th class="cmw-diff-th cmw-diff-th-tree">文件 / 路径</th>
                    <th class="cmw-diff-th cmw-diff-th-side">{{ existingPaneLabel }}</th>
                    <th class="cmw-diff-th cmw-diff-th-side">新包</th>
                    <th class="cmw-diff-th cmw-diff-th-decision">决策</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in displayRows" :key="row.node_key" class="cmw-diff-row" :class="rowToneClass(row)">
                    <td class="cmw-diff-marker" />
                    <td class="cmw-diff-td">
                      <div class="cmw-diff-name-line" :style="{ paddingLeft: `${row._depth * 16}px` }">
                        <button v-if="row.type === 'dir' && row._hasChildren" type="button" class="cmw-diff-toggle" @click="toggleCollapse(row)">
                          <ChevronRight v-if="row._collapsed" class="h-3.5 w-3.5" />
                          <ChevronDown v-else class="h-3.5 w-3.5" />
                        </button>
                        <span v-else class="w-4 flex-shrink-0" />
                        <!-- Status glyph：VSCode SCM 风格的单字符状态 -->
                        <span class="cmw-diff-glyph" :class="statusBadgeClass(row)" :title="displayStatusInfo(row).label">
                          {{ statusGlyph(row) }}
                        </span>
                        <component :is="row.type === 'dir' ? FolderIcon : FileIcon" class="cmw-diff-fileicon" :stroke-width="1.9" />
                        <span class="cmw-diff-name" :title="row.relative_path || row.name">{{ row.name }}</span>
                        <span v-if="row.relative_path && row.relative_path.includes('/')" class="cmw-diff-pathtail" :title="row.relative_path">{{ pathTail(row.relative_path) }}</span>
                        <span class="cmw-diff-badge" :class="statusBadgeClass(row)">{{ displayStatusInfo(row).label }}</span>
                      </div>
                      <p v-if="displayStatusInfo(row).note" class="cmw-diff-note" :title="displayStatusInfo(row).note">{{ displayStatusInfo(row).note }}</p>
                    </td>
                    <td class="cmw-diff-td cmw-diff-td-side">
                      <template v-if="hasSide(row, 'old')">
                        <span class="cmw-diff-side-primary">{{ formatSidePrimary(row, 'old') }}</span>
                        <span class="cmw-diff-side-secondary">{{ formatSideTime(row, 'old') }}</span>
                      </template>
                      <span v-else class="cmw-diff-side-empty">—</span>
                    </td>
                    <td class="cmw-diff-td cmw-diff-td-side">
                      <template v-if="hasSide(row, 'new')">
                        <span class="cmw-diff-side-primary">{{ formatSidePrimary(row, 'new') }}</span>
                        <span class="cmw-diff-side-secondary">{{ formatSideTime(row, 'new') }}</span>
                      </template>
                      <span v-else class="cmw-diff-side-empty">—</span>
                    </td>
                    <td class="cmw-diff-td cmw-diff-td-decision">
                      <template v-if="row.type === 'file'">
                        <!-- Segmented decision：借鉴 GitKraken stage-line 控件，单击即切 -->
                        <div class="cmw-decision-seg" role="radiogroup" :aria-label="`决策：${row.name}`">
                          <button
                            v-for="opt in decisionOptions(row)"
                            :key="opt.value"
                            type="button"
                            class="cmw-decision-seg-btn"
                            :class="[`is-${opt.value.replace('_', '-')}`, { 'is-active': decisionFor(row) === opt.value }]"
                            :disabled="submitting"
                            role="radio"
                            :aria-checked="decisionFor(row) === opt.value"
                            :title="opt.label"
                            @click="updateDecision(row, opt.value)"
                          >{{ opt.short }}</button>
                        </div>
                      </template>
                      <span v-else class="cmw-diff-side-empty">自动</span>
                    </td>
                  </tr>
                  <tr v-if="!displayRows.length">
                    <td colspan="5" class="cmw-diff-empty">
                      <Search class="h-10 w-10 mx-auto mb-2 opacity-20" />
                      无匹配项目
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Footer：主操作走轻量蓝按钮；ghost 关闭键 -->
          <footer class="cmw-footer">
            <div v-if="isRemoteTarget && preview" class="cmw-footer-remote-hint">
              <Upload class="h-4 w-4 flex-shrink-0" :stroke-width="2.2" />
              <span class="truncate">合并结果将上传至 <strong>{{ props.conflict?.context?.existing?.library_name || '远程库存' }}</strong></span>
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
  CheckCircle2, Loader2, AlertTriangle,
  ArrowDownToLine, Archive
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
  // short 用于 segmented 按钮的单字签，label 用于 tooltip / a11y
  const options = []
  if (row.new_path) {
    options.push({ label: '取新包', short: '新', value: 'use_new' })
  }
  if (row.old_path) {
    options.push({ label: '取库存', short: '库', value: 'use_old' })
  }
  options.push({ label: '删除', short: '删', value: 'delete' })
  return options
}

// VSCode SCM 风格的单字符状态指示。
//   + new_only（新增） / − old_only（库存独有） / ≠ size/content_changed / ∆ time_changed / = unchanged
function statusGlyph(row) {
  const key = displayStatusInfo(row).key
  if (key === 'new_only') return '+'
  if (key === 'old_only') return '−'
  if (key === 'size_changed' || key === 'content_changed') return '≠'
  if (key === 'time_changed') return '∆'
  return '='
}

// 为 path tail 提供上一级父目录片段，避免在長路径中丢失上下文。
function pathTail(relativePath) {
  const parts = String(relativePath || '').split('/').filter(Boolean)
  if (parts.length <= 1) return ''
  const parent = parts.slice(0, -1).join('/')
  return parent.length > 64 ? '…' + parent.slice(-60) : parent
}

// 行色条 tone：GitHub PR 风格的左侧 4px 颜色条，快速扫表定位状态
function rowToneClass(row) {
  return `tone-${displayStatusInfo(row).key.replace(/_/g, '-')}`
}

// 批量决策：对全部文件设同一决策（dir 跳过）。仅在该决策可用时应用：
//   - use_new：仅当行有 new_path
//   - use_old：仅当行有 old_path
// 其他行维持原决策，避免一键全取 “未出现在新包” 的行被默认设为 delete。
function batchSetDecision(decision) {
  if (props.submitting) return
  const next = { ...(props.decisions || {}) }
  for (const item of compareItems.value) {
    if (item.type !== 'file') continue
    if (decision === 'use_new' && !item.new_path) continue
    if (decision === 'use_old' && !item.old_path) continue
    next[item.relative_path] = decision
  }
  emit('update:decisions', next)
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

function statusBadgeClass(row) {
  // 返回语义 tone class，具体颜色在 <style> 里统一控制（低饱和度、去填底块）
  const key = displayStatusInfo(row).key
  if (key === 'new_only') return 'is-new'
  if (key === 'old_only') return 'is-old'
  if (key === 'size_changed') return 'is-size'
  if (key === 'content_changed') return 'is-content'
  if (key === 'time_changed') return 'is-time'
  return 'is-neutral'
}

function decisionSelectClass(row) {
  const decision = decisionFor(row)
  if (decision === 'use_new') return 'is-new'
  if (decision === 'use_old') return 'is-old'
  if (decision === 'delete') return 'is-del'
  return 'is-neutral'
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
   - 主操作轻量蓝按钮；状态色按语义区分
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

/* 远程合并 tag：克制 slate 轮廓，去 amber 渐变 */
.cmw-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 2px 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
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
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
}

/* Bulk decision 控件组：全取新包 / 全取库存 -- segmented 风格 */
.cmw-bulk-group {
  display: inline-flex;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.cmw-bulk-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 11px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  background: transparent;
  border: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.cmw-bulk-btn + .cmw-bulk-btn {
  border-left: 1px solid #e2e8f0;
}

.cmw-bulk-btn:hover:not(:disabled) {
  background: #f8fafc;
  color: #4338ca;
}

.cmw-bulk-btn:disabled {
  opacity: 0.5;
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

/* Pill：segmented 灰阶，active 单色 indigo（去渐变、去阴影） */
.cmw-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #fff;
  color: #64748b;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.18s ease;
}

.cmw-pill:hover {
  border-color: #cbd5e1;
  color: #334155;
  background: #f8fafc;
}

.cmw-pill.is-active {
  border-color: #6366f1;
  background: #eef2ff;
  color: #4338ca;
}

.cmw-pill-count {
  display: inline-flex;
  min-width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
  color: inherit;
  padding: 0 5px;
  font-size: 10.5px;
  font-weight: 700;
}

.cmw-pill.is-active .cmw-pill-count {
  background: rgba(99, 102, 241, 0.16);
  color: #4338ca;
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
  background: linear-gradient(90deg, #6366f1 0%, #2563eb 100%);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.14);
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
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.12);
}

.cmw-loading-step.is-done {
  border-color: rgba(14, 165, 233, 0.28);
  color: #0369a1;
  background: #f0f9ff;
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
  background: rgba(14, 165, 233, 0.16);
  color: #0369a1;
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

/* ============================================================
   Left summary panel：克制灰阶，去三色 dot 强字
   ============================================================ */
.cmw-summary-pane {
  width: 256px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid #f1f5f9;
  background: #fafbfc;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cmw-summary-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cmw-summary-label {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.cmw-summary-path {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  padding: 8px 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  color: #475569;
  word-break: break-all;
}

.cmw-summary-decisions {
  border-top: 1px solid #e2e8f0;
  padding-top: 14px;
  gap: 10px;
}

.cmw-summary-decision-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.cmw-decision-key {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #475569;
  font-weight: 500;
}

.cmw-decision-val {
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.cmw-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex-shrink: 0;
}
.cmw-dot.is-new { background: #10b981; }
.cmw-dot.is-old { background: #6366f1; }
.cmw-dot.is-del { background: #94a3b8; }

.cmw-summary-remote {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
  color: #64748b;
}

.cmw-summary-remote-title {
  font-size: 11px;
  font-weight: 700;
  color: #334155;
}

.cmw-summary-remote-desc {
  margin-top: 3px;
  font-size: 10.5px;
  line-height: 1.55;
  color: #94a3b8;
}

.cmw-summary-remote-name {
  margin-top: 5px;
  font-size: 10.5px;
  font-weight: 700;
  color: #475569;
}

/* ============================================================
   Diff table：去填色行、统一 muted
   ============================================================ */
.cmw-diff-table {
  width: 100%;
  min-width: 860px;
  border-collapse: collapse;
}

.cmw-diff-table thead {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #fafbfc;
  backdrop-filter: blur(6px);
}

.cmw-diff-th {
  padding: 11px 14px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
  font-size: 10.5px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.cmw-diff-th-marker { width: 4px; padding: 0; }
.cmw-diff-th-tree { min-width: 280px; }
.cmw-diff-th-side { width: 132px; padding-left: 12px; padding-right: 12px; }
.cmw-diff-th-decision { width: 132px; padding-left: 12px; padding-right: 12px; }

/* 行 tone：GitHub PR 风格的左侧 4px 色条。颜色仅作状态错锅使用，不填整行 bg。 */
.cmw-diff-row {
  border-bottom: 1px solid #f1f5f9;
  transition: background-color 0.12s ease;
  position: relative;
}

.cmw-diff-row:hover {
  background: #f8fafc;
}

.cmw-diff-marker {
  width: 4px;
  padding: 0;
  background: transparent;
}

.tone-new-only .cmw-diff-marker { background: #10b981; }
.tone-old-only .cmw-diff-marker { background: #94a3b8; }
.tone-size-changed .cmw-diff-marker,
.tone-time-changed .cmw-diff-marker { background: #f59e0b; }
.tone-content-changed .cmw-diff-marker { background: #ef4444; }
.tone-unchanged .cmw-diff-marker { background: transparent; }

.cmw-diff-td {
  padding: 9px 14px;
  vertical-align: top;
}

.cmw-diff-td-side {
  padding: 9px 12px;
}

.cmw-diff-td-decision {
  padding: 9px 12px;
}

/* Name line：紧凑 toggle + glyph + fileicon + name + tail + badge 一行平铺 */
.cmw-diff-name-line {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.cmw-diff-toggle {
  display: inline-flex;
  width: 16px;
  height: 16px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #94a3b8;
  transition: color 0.15s ease;
}

.cmw-diff-toggle:hover {
  color: #334155;
}

/* Status glyph：VSCode SCM 风格的单字符状态。颜色复用 cmw-diff-badge 的 tone class */
.cmw-diff-glyph {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  background: #f1f5f9;
  color: #94a3b8;
  border: none !important;
  padding: 0 !important;
}

.cmw-diff-glyph.is-new { background: #ecfdf5; color: #059669; }
.cmw-diff-glyph.is-old { background: #f1f5f9; color: #475569; }
.cmw-diff-glyph.is-size,
.cmw-diff-glyph.is-time { background: #fff7ed; color: #b45309; }
.cmw-diff-glyph.is-content { background: #fef2f2; color: #b91c1c; }
.cmw-diff-glyph.is-neutral { background: #f1f5f9; color: #94a3b8; }

.cmw-diff-fileicon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: #94a3b8;
}

.cmw-diff-name {
  flex-shrink: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: #1e293b;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-diff-pathtail {
  flex: 1;
  min-width: 0;
  font-size: 10.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.cmw-diff-note {
  margin-top: 3px;
  margin-left: 32px;
  font-size: 10.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Side cell：尺寸 + 时间合为一行主，二行辅，去除原本上下两行 <p> 的垄余 */
.cmw-diff-side-primary {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: #334155;
  font-variant-numeric: tabular-nums;
}

.cmw-diff-side-secondary {
  display: block;
  font-size: 10.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-diff-side-empty {
  font-size: 11px;
  color: #cbd5e1;
  font-style: italic;
}

.cmw-diff-empty {
  padding: 40px 24px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
}

/* Status badge：统一 dot + 弱底 muted */
.cmw-diff-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 1px 8px 1px 6px;
  font-size: 10.5px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.cmw-diff-badge-dot {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  flex-shrink: 0;
}

.cmw-diff-badge.is-new {
  background: #ecfdf5;
  color: #059669;
  border-color: rgba(16, 185, 129, 0.18);
}

.cmw-diff-badge.is-old {
  background: #eef2ff;
  color: #4f46e5;
  border-color: rgba(99, 102, 241, 0.18);
}

.cmw-diff-badge.is-size,
.cmw-diff-badge.is-time {
  background: #fff7ed;
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.2);
}

.cmw-diff-badge.is-content {
  background: #fef2f2;
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.18);
}

.cmw-diff-badge.is-neutral {
  background: #f1f5f9;
  color: #64748b;
  border-color: #e2e8f0;
}

/* Segmented decision：借鉴 GitKraken stage-line，3 个单字按钮贴在一起，active 亮色 */
.cmw-decision-seg {
  display: inline-flex;
  align-items: stretch;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.cmw-decision-seg-btn {
  flex: 1;
  min-width: 28px;
  border: 0;
  background: transparent;
  padding: 5px 0;
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.cmw-decision-seg-btn + .cmw-decision-seg-btn {
  border-left: 1px solid #e2e8f0;
}

.cmw-decision-seg-btn:hover:not(:disabled):not(.is-active) {
  background: #f8fafc;
  color: #475569;
}

.cmw-decision-seg-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.cmw-decision-seg-btn.is-active.is-use-new {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 700;
}

.cmw-decision-seg-btn.is-active.is-use-old {
  background: #eef2ff;
  color: #4338ca;
  font-weight: 700;
}

.cmw-decision-seg-btn.is-active.is-delete {
  background: #f1f5f9;
  color: #475569;
  font-weight: 700;
  text-decoration: line-through;
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

/* Action 按钮：轻量蓝主按钮 / slate ghost，去掉绿色发光。 */
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
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.08);
}

.cmw-action-btn.is-emerald {
  border: 1px solid rgba(147, 197, 253, 0.78);
  color: #1d4ed8;
  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 4px 10px rgba(37, 99, 235, 0.08);
}

.cmw-action-btn.is-emerald:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.82);
  background: linear-gradient(180deg, #f3f8ff 0%, #dfeeff 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 6px 14px rgba(37, 99, 235, 0.12);
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
.cmw-pill:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
}

/* Footer remote hint：去 amber 强字 */
.cmw-footer-remote-hint {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.cmw-footer-remote-hint strong {
  color: #334155;
  font-weight: 600;
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

