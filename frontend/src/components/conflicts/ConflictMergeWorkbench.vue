<template>
  <Teleport to="body">
    <Transition name="cmw-fade">
      <div
        v-if="visible"
        class="pointer-events-none fixed inset-0 z-[2450] flex items-center justify-center p-6 max-[900px]:p-3"
      >
        <!-- 透明点击层；弹窗打开时不虚化、不压暗背景 -->
        <div
          class="merge-dialog-overlay pointer-events-auto absolute inset-0 bg-transparent"
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
            <div class="cmw-pill-group">
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
            <div class="cmw-summary-stats" aria-label="当前决策统计">
              <span class="cmw-summary-stat is-new"><i class="cmw-dot is-new" />取新包<b>{{ decisionSummary.useNew }}</b></span>
              <span class="cmw-summary-stat is-old"><i class="cmw-dot is-old" />取库存<b>{{ decisionSummary.useOld }}</b></span>
              <span class="cmw-summary-stat is-del"><i class="cmw-dot is-del" />不要<b>{{ decisionSummary.delete }}</b></span>
            </div>
          </div>

          <!-- Loading panel：阶段 / 进度由父组件 loadingProgress 实时驱动，
               不再靠前端计时器估算。stage 映射到 6 个用户可读的步骤卡。 -->
          <div v-if="loading || progressStatus === 'failed'" class="cmw-loading-panel">
            <div class="cmw-loading-card">
              <div class="cmw-loading-main">
                <div class="cmw-loading-orb" :class="{ 'is-error': progressStatus === 'failed' }">
                  <Loader2 v-if="progressStatus !== 'failed'" class="h-6 w-6 animate-spin" :stroke-width="2.4" />
                  <AlertTriangle v-else class="h-6 w-6" :stroke-width="2.4" />
                </div>
                <div class="min-w-0">
                  <p class="cmw-loading-kicker">合并预览任务</p>
                  <p class="cmw-loading-stage">{{ progressStageLabel }}</p>
                  <p class="cmw-loading-message" :title="progressMessage">{{ progressMessage || '准备中…' }}</p>
                </div>
              </div>

              <div class="cmw-loading-progress">
                <!-- 真实 percent 进度条（来自 extract_task.progress 的 22~62 区间映射） -->
                <div class="cmw-loading-bar-head">
                  <span>处理进度</span>
                  <b>{{ progressPercent }}%</b>
                </div>
                <div class="cmw-loading-bar-track">
                  <div
                    class="cmw-loading-bar"
                    :class="{ 'is-error': progressStatus === 'failed' }"
                    :style="{ width: `${progressPercent}%` }"
                  />
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
          </div>

          <!-- 默认空态：进度 idle 且没有 preview（罕见路径，比如刚 mount 就没数据） -->
          <div v-else-if="!preview" class="cmw-empty-state">
            <GitMerge class="h-14 w-14 opacity-25" :stroke-width="1.6" />
            <p class="mt-3 text-[13px] text-slate-400">暂无合并预览数据</p>
          </div>

          <!-- Main content -->
          <div v-else class="cmw-main">
            <!-- Split diff：左右并排比对，点击任一侧文件即可选择 / 取消 -->
            <div class="cmw-split-pane">
              <div class="cmw-split-head">
                <div class="cmw-split-title">
                  <span>{{ existingPaneLabel }}</span>
                  <code :title="resolvedExistingPath">{{ resolvedExistingPath }}</code>
                </div>
                <div class="cmw-split-title">
                  <span>新包</span>
                  <code :title="resolvedSourcePath">{{ resolvedSourcePath }}</code>
                </div>
              </div>

              <div class="cmw-split-list">
                <article
                  v-for="row in displayRows"
                  :key="row.node_key"
                  class="cmw-split-row"
                  :class="rowToneClass(row)"
                >
                  <section
                    class="cmw-side-line is-old"
                    :class="sideLineClass(row, 'old')"
                    role="button"
                    :tabindex="canPickSide(row, 'old') ? 0 : -1"
                    :title="canPickSide(row, 'old') ? '选择库存侧这个文件' : ''"
                    @click="pickSide(row, 'old')"
                    @keydown.enter.prevent="pickSide(row, 'old')"
                    @keydown.space.prevent="pickSide(row, 'old')"
                  >
                    <div v-if="hasSide(row, 'old')" class="cmw-side-file">
                      <span
                        v-if="row.type === 'file'"
                        class="cmw-pick-mark"
                        :class="{ 'is-hidden': !isSidePicked(row, 'old') }"
                        :title="isSidePicked(row, 'old') ? '已选择库存侧；再点取消' : ''"
                        :aria-hidden="!isSidePicked(row, 'old')"
                      >
                        <CheckCircle2 class="h-3.5 w-3.5" :stroke-width="2.6" />
                      </span>
                      <span class="cmw-file-icon-shell">
                        <component :is="fileIconForRow(row)" class="cmw-diff-fileicon file-icon" :class="fileIconClassForRow(row)" :size="18" :stroke-width="2.2" />
                      </span>
                      <div class="cmw-side-name-stack">
                        <span class="cmw-diff-name" :title="row.relative_path || row.name">{{ row.name }}</span>
                        <span class="cmw-side-path" :title="row.relative_path || row.name">{{ row.relative_path || row.name }}</span>
                      </div>
                    </div>
                    <div v-else class="cmw-side-missing">此侧不存在</div>
                    <div class="cmw-side-meta" :class="{ 'is-empty': !hasSide(row, 'old') }">
                      <template v-if="hasSide(row, 'old')">
                        <span :class="{ 'is-size-diff': isSizeDifferent(row) }">{{ formatSidePrimary(row, 'old') }}</span>
                        <span>{{ formatSideTime(row, 'old') }}</span>
                      </template>
                    </div>
                  </section>

                  <section
                    class="cmw-side-line is-new"
                    :class="sideLineClass(row, 'new')"
                    role="button"
                    :tabindex="canPickSide(row, 'new') ? 0 : -1"
                    :title="canPickSide(row, 'new') ? '选择新包侧这个文件' : ''"
                    @click="pickSide(row, 'new')"
                    @keydown.enter.prevent="pickSide(row, 'new')"
                    @keydown.space.prevent="pickSide(row, 'new')"
                  >
                    <div v-if="hasSide(row, 'new')" class="cmw-side-file">
                      <span
                        v-if="row.type === 'file'"
                        class="cmw-pick-mark"
                        :class="{ 'is-hidden': !isSidePicked(row, 'new') }"
                        :title="isSidePicked(row, 'new') ? '已选择新包侧；再点取消' : ''"
                        :aria-hidden="!isSidePicked(row, 'new')"
                      >
                        <CheckCircle2 class="h-3.5 w-3.5" :stroke-width="2.6" />
                      </span>
                      <span class="cmw-file-icon-shell">
                        <component :is="fileIconForRow(row)" class="cmw-diff-fileicon file-icon" :class="fileIconClassForRow(row)" :size="18" :stroke-width="2.2" />
                      </span>
                      <div class="cmw-side-name-stack">
                        <span class="cmw-diff-name" :title="row.relative_path || row.name">{{ row.name }}</span>
                        <span class="cmw-side-path" :title="row.relative_path || row.name">{{ row.relative_path || row.name }}</span>
                      </div>
                    </div>
                    <div v-else class="cmw-side-missing">此侧不存在</div>
                    <div class="cmw-side-meta" :class="{ 'is-empty': !hasSide(row, 'new') }">
                      <template v-if="hasSide(row, 'new')">
                        <span :class="{ 'is-size-diff': isSizeDifferent(row) }">{{ formatSidePrimary(row, 'new') }}</span>
                        <span>{{ formatSideTime(row, 'new') }}</span>
                      </template>
                    </div>
                  </section>
                </article>

                <div v-if="!displayRows.length" class="cmw-diff-empty">
                  <Search class="h-10 w-10 mx-auto mb-2 opacity-20" />
                  无匹配项目
                </div>
              </div>
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
  CheckCircle2, Loader2, AlertTriangle,
  ArrowDownToLine, Archive
} from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import { classifyLibraryEntryKind, libraryEntryIconFor } from '../library/_libraryFileKind'

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
const statusFilter = ref('changed')

const statusDropdownOptions = [
  { value: 'all', label: '全部项目' },
  { value: 'changed', label: '只看差异' },
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
  { value: 'changed', label: '只看差异', count: displaySummary.value.changed, tone: 'changed' },
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
      return { key: 'content_changed', label: '内容不同', tagType: 'danger', note: '同名同大小，但文件内容不同' }
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

function isSizeDifferent(row) {
  return displayStatusInfo(row).key === 'size_changed'
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

function decisionValueForSide(side) {
  return side === 'new' ? 'use_new' : 'use_old'
}

function canPickSide(row, side) {
  return row?.type === 'file' && hasSide(row, side) && !props.submitting
}

function isSidePicked(row, side) {
  return row?.type === 'file' && decisionFor(row) === decisionValueForSide(side)
}

function pickSide(row, side) {
  if (!canPickSide(row, side)) return
  const sideDecision = decisionValueForSide(side)
  if (decisionFor(row) === sideDecision) {
    updateDecision(row, 'delete')
    return
  }
  updateDecision(row, sideDecision)
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

function sideLineClass(row, side) {
  const key = displayStatusInfo(row).key
  return {
    'is-missing': !hasSide(row, side),
    'is-added': side === 'new' && key === 'new_only',
    'is-removed': side === 'old' && key === 'old_only',
    'is-pickable': canPickSide(row, side),
    'is-picked': isSidePicked(row, side),
  }
}

function fileIconForRow(row) {
  return libraryEntryIconFor({
    ...row,
    is_directory: row?.type === 'dir',
    entry_type: row?.type === 'dir' ? 'dir' : 'file',
  })
}

function fileIconClassForRow(row) {
  const kind = classifyLibraryEntryKind({
    ...row,
    is_directory: row?.type === 'dir',
    entry_type: row?.type === 'dir' ? 'dir' : 'file',
  })
  return `icon-${kind}`
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
  transition: opacity 0.18s ease;
}
.cmw-fade-enter-from,
.cmw-fade-leave-to {
  opacity: 0;
}

/* Shell：对齐社团补全预览的白色毛玻璃壳 */
.cmw-shell {
  position: relative;
  display: flex;
  width: min(94vw, 1360px);
  height: min(88vh, 820px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.42);
  border-radius: 22px;
  background: #fff;
  backdrop-filter: blur(34px) saturate(150%);
  -webkit-backdrop-filter: blur(34px) saturate(150%);
  box-shadow:
    0 28px 70px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

/* Header：纯玻璃 */
.cmw-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  padding: 12px 18px;
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
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
  background: rgba(255, 255, 255, 0.34);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
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
  border: 1px solid rgba(255, 255, 255, 0.62);
  border-radius: 999px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.56);
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.72),
    0 6px 14px rgba(15, 23, 42, 0.055);
  backdrop-filter: blur(10px) saturate(130%);
  -webkit-backdrop-filter: blur(10px) saturate(130%);
}

/* Close 按钮：玻璃 + hover rotate */
.cmw-close-btn {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.38);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.24);
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-close-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(148, 163, 184, 0.55);
  background: rgba(255, 255, 255, 0.48);
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
  gap: 8px;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  padding: 7px 16px;
}

.cmw-search-input {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  padding: 7px 10px 7px 32px;
  font-size: 12.5px;
  color: #334155;
  outline: none;
  transition: all 0.2s ease;
}

.cmw-search-input:focus {
  border-color: rgba(203, 213, 225, 0.9);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: none;
}

.cmw-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #475569;
  padding: 7px 9px;
  font-size: 12.5px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-toolbar-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(203, 213, 225, 0.82);
  background: rgba(255, 255, 255, 0.74);
  color: #0f172a;
  box-shadow: none;
}

/* Bulk decision 控件组：全取新包 / 全取库存 -- segmented 风格 */
.cmw-bulk-group {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(226, 232, 240, 0.82);
  border-radius: 8px;
  background: transparent;
  overflow: hidden;
}

.cmw-bulk-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 9px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  background: transparent;
  border: 0;
  transition: background-color 0.18s ease, color 0.18s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-bulk-btn + .cmw-bulk-btn {
  border-left: 1px solid rgba(15, 23, 42, 0.06);
}

.cmw-bulk-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.78);
  color: #0f172a;
  transform: translateY(-2px) scale(1.02);
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
  justify-content: space-between;
  gap: 8px 12px;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  padding: 6px 16px;
}

.cmw-pill-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.cmw-main {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}

/* Pill：segmented 灰阶，active 单色 indigo（去渐变、去阴影） */
.cmw-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.74);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.48);
  color: #64748b;
  padding: 4px 10px;
  font-size: 11.5px;
  font-weight: 700;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.cmw-pill:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(203, 213, 225, 0.9);
  color: #334155;
  background: rgba(255, 255, 255, 0.78);
}

.cmw-pill.is-active {
  border-color: rgba(165, 180, 252, 0.48);
  background: rgba(238, 242, 255, 0.72);
  color: #3730a3;
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
  background: rgba(255, 255, 255, 0.56);
  padding: 28px;
}

.cmw-loading-card {
  display: grid;
  width: min(860px, 100%);
  grid-template-columns: minmax(210px, 0.38fr) minmax(0, 1fr);
  gap: 26px;
  align-items: center;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.72);
  padding: 26px;
  text-align: left;
  backdrop-filter: blur(20px) saturate(130%);
  -webkit-backdrop-filter: blur(20px) saturate(130%);
  box-shadow:
    0 18px 46px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.cmw-loading-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 18px;
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
    0 16px 32px rgba(79, 70, 229, 0.14),
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

.cmw-loading-kicker {
  margin: 0 0 5px;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.cmw-loading-stage {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.35px;
}

.cmw-loading-message {
  margin: 7px 0 0;
  font-size: 12.5px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-loading-progress {
  min-width: 0;
}

.cmw-loading-bar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
}

.cmw-loading-bar-head b {
  color: #334155;
  font-variant-numeric: tabular-nums;
}

.cmw-loading-bar-track {
  position: relative;
  height: 8px;
  margin-top: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.78);
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

.cmw-loading-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
  text-align: left;
}

.cmw-loading-step {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.62);
  padding: 8px 10px;
  color: #94a3b8;
  font-size: 11.5px;
  font-weight: 700;
  transition: all 0.3s ease;
}

.cmw-loading-step.is-active {
  border-color: rgba(99, 102, 241, 0.42);
  color: #4338ca;
  background: rgba(238, 242, 255, 0.82);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.1);
}

.cmw-loading-step.is-done {
  border-color: rgba(14, 165, 233, 0.28);
  color: #0369a1;
  background: rgba(240, 249, 255, 0.82);
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
  border: 1px solid rgba(255, 255, 255, 0.36);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.28);
  padding: 6px 9px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmw-summary-stats {
  display: flex;
  align-items: center;
  flex: none;
  gap: 6px;
}

.cmw-summary-stat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 64px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  padding: 4px 7px;
  font-size: 11px;
  color: #475569;
  font-weight: 700;
}

.cmw-summary-stat b {
  margin-left: 2px;
  color: #0f172a;
  font-size: 12px;
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
  flex: none;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(226, 232, 240, 0.76);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  padding: 6px 10px;
  max-width: 220px;
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
}

.cmw-table-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  background: rgba(255, 255, 255, 0.1);
}

/* ============================================================
   Split diff：左右并排文件级对比
   ============================================================ */
.cmw-split-pane {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}

.cmw-split-head {
  display: grid;
  flex: none;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px;
  border-bottom: 1px solid #e5edf6;
  background: #fff;
  padding: 7px 12px 6px;
}

.cmw-split-head .cmw-split-title:last-child {
  grid-column: 2;
}

.cmw-split-title {
  min-width: 0;
}

.cmw-split-title span {
  display: block;
  color: #7d91ad;
  font-size: 10.5px;
  font-weight: 800;
}

.cmw-split-title code {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #6f86a5;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10.5px;
  font-weight: 700;
}

.cmw-split-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 12px 12px;
  background: #fff;
}

.cmw-split-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px;
  align-items: stretch;
  min-height: 38px;
  border-bottom: 1px solid rgba(219, 226, 235, 0.62);
}

.cmw-split-row:hover {
  background: rgba(246, 249, 252, 0.62);
}

.cmw-side-line {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  border-left: 2px solid transparent;
  padding: 5px 8px 5px 7px;
  transition: background-color 0.16s ease, border-color 0.16s ease;
}

.cmw-side-line.is-pickable {
  cursor: pointer;
}

.cmw-side-line.is-pickable:hover {
  background: rgba(239, 246, 255, 0.46);
}

.cmw-side-line.is-picked {
  border-left-color: #2563eb;
  background: rgba(239, 246, 255, 0.7);
}

.cmw-side-line.is-missing {
  opacity: 0.74;
  color: #94a3b8;
}

.cmw-side-line.is-added {
  border-left-color: #22c55e;
  background: rgba(236, 253, 245, 0.44);
}

.cmw-side-line.is-removed {
  border-left-color: #ef4444;
  background: rgba(254, 242, 242, 0.44);
}

.cmw-side-line.is-changed {
  border-left-color: #f59e0b;
}

.cmw-side-file {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.cmw-side-name-stack {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}

.cmw-side-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}

.cmw-side-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 164px;
  color: #7890ad;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.cmw-side-meta span:last-child {
  min-width: 108px;
  text-align: right;
  color: #7890ad;
  font-weight: 600;
}

.cmw-side-meta .is-size-diff {
  color: #b45309;
  font-weight: 850;
}

.cmw-side-meta.is-empty {
  display: none;
}

/* 旧表格样式保留给潜在回退结构，主界面已切到 split diff */
.cmw-diff-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
}

.cmw-diff-table thead {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(255, 255, 255, 0.32);
  backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
}

.cmw-diff-th {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
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
  border-bottom: 1px solid rgba(241, 245, 249, 0.82);
  transition: background-color 0.12s ease;
  position: relative;
}

.cmw-diff-row:hover {
  background: rgba(255, 255, 255, 0.24);
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
  padding: 8px 12px;
  vertical-align: top;
}

.cmw-diff-td-side {
  padding: 8px 10px;
}

.cmw-diff-td-decision {
  padding: 8px 10px;
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
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
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

.cmw-file-icon-shell {
  display: inline-flex;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  align-items: center;
  justify-content: center;
}

.cmw-diff-fileicon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.cmw-diff-fileicon.icon-dir,
.cmw-diff-fileicon.icon-folder {
  color: #f6b73c;
  fill: currentColor;
  stroke: currentColor;
}

.cmw-diff-fileicon.icon-audio-lossless { color: #2563eb; }

.cmw-diff-fileicon.icon-audio { color: #7c3aed; }

.cmw-diff-fileicon.icon-image { color: #f97316; }

.cmw-diff-fileicon.icon-video { color: #6366f1; }

.cmw-diff-fileicon.icon-pdf { color: #dc2626; }

.cmw-diff-fileicon.icon-archive { color: #d97706; }

.cmw-diff-fileicon.icon-text { color: #64748b; }

.cmw-diff-fileicon.icon-file { color: #94a3b8; }

.cmw-pick-mark {
  display: inline-flex;
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #2563eb;
  color: #fff;
}

.cmw-pick-mark.is-hidden {
  opacity: 0;
}

.cmw-diff-name {
  flex-shrink: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: #1e293b;
  max-width: 340px;
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

/* Footer */
.cmw-footer {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.24);
  background: rgba(255, 255, 255, 0.16);
  padding: 12px 20px;
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
}

/* Action 按钮：深色主按钮 / 白色磨砂 ghost，去掉绿色发光。 */
.cmw-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 14px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 800;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Cancel：与社团预览 secondary-cta 同款（半透灰 ghost） */
.cmw-action-btn.is-slate {
  border: 1px solid rgba(255, 255, 255, 0.66);
  background: rgba(255, 255, 255, 0.58);
  color: #334155;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(10px) saturate(130%);
  -webkit-backdrop-filter: blur(10px) saturate(130%);
}

.cmw-action-btn.is-slate:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: rgba(255, 255, 255, 0.86);
  color: #0f172a;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.84),
    0 14px 28px rgba(15, 23, 42, 0.12);
}

/* Submit：与社团预览 primary-cta 同款（深色实心 #111827） */
.cmw-action-btn.is-emerald {
  border: 0;
  color: #fff;
  background: #111827;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
}

.cmw-action-btn.is-emerald:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: #0f172a;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}

.cmw-action-btn.is-emerald:disabled {
  cursor: not-allowed;
  opacity: 0.55;
  box-shadow: none;
  transform: none;
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
.cmw-bulk-btn:active:not(:disabled),
.cmw-pill:active:not(:disabled) {
  transform: scale(0.96);
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

