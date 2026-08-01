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

          <!-- Loading panel：阶段 / 进度由父组件 loadingProgress 实时驱动。 -->
          <div v-if="loading || progressStatus === 'failed'" class="cmw-loading-panel">
            <AppLoadingAnimation
              :label="loadingLabel"
              :description="loadingDescription"
              :size="168"
              :min-height="360"
            />
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
              <StatefulButton
                type="button"
                class="cmw-action-btn is-emerald cmw-submit-btn"
                unstyled
                :show-default-icons="false"
                :success-hold="900"
                :disabled="!preview || loading"
                @click="handleSubmitClick"
              >
                <template #prefix="{ state }">
                  <span class="cmw-submit-state-icon" :class="`is-${state}`" aria-hidden="true">
                    <Loader2 v-if="state === 'loading' || submitting" class="h-4 w-4 animate-spin" :stroke-width="2.4" />
                    <CheckCircle2 v-else-if="state === 'success'" class="h-4 w-4" :stroke-width="2.6" />
                    <AlertCircle v-else-if="state === 'error'" class="h-4 w-4" :stroke-width="2.5" />
                    <GitMerge v-else class="h-4 w-4" :stroke-width="2.4" />
                  </span>
                </template>
                <span>{{ submitLabel }}</span>
              </StatefulButton>
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
  CheckCircle2,
  ArrowDownToLine, Archive, Loader2, AlertCircle
} from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
import StatefulButton from '../ui/stateful-button.vue'
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
  },
  submitAction: {
    type: Function,
    default: null
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
const loadingLabel = computed(() => {
  if (progressStatus.value === 'failed') return progressStageLabel.value || '合并预览生成失败'
  const label = progressStageLabel.value && progressStageLabel.value !== '初始化'
    ? progressStageLabel.value
    : '正在生成目录差异...'
  return label
})
const loadingDescription = computed(() => {
  if (progressStatus.value === 'failed') return progressMessage.value || '请关闭后重新生成，或检查任务日志。'
  if (progressMessage.value) return progressMessage.value
  const stage = progressStage.value
  if (stage === 'resolve_path') return '正在定位现有目录和新包来源'
  if (stage === 'copy_archive') return '正在准备临时工作区'
  if (stage === 'scan_source') return '正在读取新包目录结构'
  if (stage === 'extract' || stage === 'nested_extract') return '正在展开压缩包并整理文件'
  if (stage === 'filter') return '正在过滤临时文件和系统文件'
  if (stage === 'scan_existing') return '正在读取库存目录'
  if (stage === 'compare') return '正在按相对路径生成差异'
  return '正在分析目录结构，请稍候'
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

async function handleSubmitClick() {
  if (props.submitting) return false
  if (typeof props.submitAction === 'function') {
    return props.submitAction()
  }
  emit('submit')
  return true
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
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow:
    0 30px 80px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
  font-family: Inter, "HarmonyOS Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
  text-rendering: geometricPrecision;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Header：纯玻璃 */
.cmw-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.58);
  background: transparent;
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
  margin: 0;
  font-size: 17px;
  font-weight: 850;
  line-height: 1.15;
  color: #0f172a;
  letter-spacing: -0.015em;
}

.cmw-subtitle {
  max-width: 640px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.35;
  color: #52647c;
  font-weight: 520;
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
  border-bottom: 1px solid rgba(226, 232, 240, 0.58);
  background: transparent;
  padding: 7px 16px;
}

.cmw-search-input {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  padding: 7px 10px 7px 32px;
  font-size: 12px;
  font-weight: 560;
  color: #243247;
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
  font-size: 12px;
  font-weight: 720;
  letter-spacing: 0.005em;
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
  font-weight: 680;
  letter-spacing: 0.005em;
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
  border-bottom: 1px solid rgba(226, 232, 240, 0.5);
  background: transparent;
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
  background: transparent;
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
  font-weight: 720;
  letter-spacing: 0.005em;
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
  background: transparent;
  padding: 28px;
}

.cmw-loading-panel :deep(.app-loading-animation) {
  width: min(520px, 100%);
}

.cmw-loading-panel :deep(.app-loading-animation__label) {
  color: #111827;
  font-size: 15px;
  font-weight: 820;
  letter-spacing: -0.01em;
}

.cmw-loading-panel :deep(.app-loading-animation__description) {
  color: #52647c;
  font-size: 12px;
  font-weight: 540;
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
  font-size: 11.5px;
  color: #475569;
  font-weight: 720;
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
  background: transparent;
}

.cmw-split-head {
  display: grid;
  flex: none;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.6);
  background: transparent;
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
  color: #64748b;
  font-size: 11px;
  font-weight: 820;
  letter-spacing: 0.02em;
}

.cmw-split-title code {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #52647c;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0;
}

.cmw-split-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 12px 12px;
  background: transparent;
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
  color: #7f8fa6;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 10.5px;
  font-weight: 520;
  letter-spacing: 0;
}

.cmw-side-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 164px;
  color: #52647c;
  font-size: 11.5px;
  font-weight: 720;
  font-variant-numeric: tabular-nums;
}

.cmw-side-meta span:last-child {
  min-width: 108px;
  text-align: right;
  color: #667993;
  font-weight: 620;
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
  font-size: 13px;
  font-weight: 720;
  color: #111827;
  line-height: 1.22;
  letter-spacing: 0;
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
  font-weight: 780;
  letter-spacing: 0.005em;
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

.cmw-submit-btn {
  min-width: 146px;
  min-height: 44px;
}

.cmw-submit-btn[data-state="loading"] {
  opacity: 1;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}

.cmw-submit-btn :deep(.stateful-button__content),
.cmw-submit-btn :deep(.stateful-button__label) {
  gap: 7px;
}

.cmw-submit-state-icon {
  display: inline-flex;
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  align-items: center;
  justify-content: center;
}

.cmw-submit-state-icon.is-success svg,
.cmw-submit-state-icon.is-error svg {
  animation: cmw-submit-icon-pop 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes cmw-submit-icon-pop {
  0% {
    transform: scale(0.55) rotate(-10deg);
  }
  70% {
    transform: scale(1.12) rotate(4deg);
  }
  100% {
    transform: scale(1) rotate(0deg);
  }
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
  font-weight: 560;
  color: #64748b;
}

.cmw-footer-remote-hint strong {
  color: #334155;
  font-weight: 600;
}

/* 暗色态：目录差异工作台 */
:global(html.kikoerumanager-dark) .cmw-shell {
  border-color: var(--km-dark-border);
  background: rgba(13, 14, 18, 0.96);
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.38),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

:global(html.kikoerumanager-dark) .cmw-header,
:global(html.kikoerumanager-dark) .cmw-toolbar,
:global(html.kikoerumanager-dark) .cmw-pill-bar,
:global(html.kikoerumanager-dark) .cmw-split-head {
  border-color: var(--km-dark-border-soft);
}

:global(html.kikoerumanager-dark) .cmw-icon,
:global(html.kikoerumanager-dark) .cmw-tag,
:global(html.kikoerumanager-dark) .cmw-close-btn,
:global(html.kikoerumanager-dark) .cmw-pill,
:global(html.kikoerumanager-dark) .cmw-bulk-group,
:global(html.kikoerumanager-dark) .cmw-summary-remote {
  border-color: var(--km-dark-border);
  background: var(--km-dark-accent-bg);
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .cmw-icon {
  color: #a5b4fc;
}

:global(html.kikoerumanager-dark) .cmw-title,
:global(html.kikoerumanager-dark) .cmw-diff-name,
:global(html.kikoerumanager-dark) .cmw-loading-panel :deep(.app-loading-animation__label),
:global(html.kikoerumanager-dark) .cmw-summary-stat b,
:global(html.kikoerumanager-dark) .cmw-footer-remote-hint strong {
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark) .cmw-subtitle,
:global(html.kikoerumanager-dark) .cmw-tag,
:global(html.kikoerumanager-dark) .cmw-search-input,
:global(html.kikoerumanager-dark) .cmw-toolbar-btn,
:global(html.kikoerumanager-dark) .cmw-bulk-btn,
:global(html.kikoerumanager-dark) .cmw-pill,
:global(html.kikoerumanager-dark) .cmw-summary-stat,
:global(html.kikoerumanager-dark) .cmw-summary-remote,
:global(html.kikoerumanager-dark) .cmw-side-meta,
:global(html.kikoerumanager-dark) .cmw-diff-side-primary,
:global(html.kikoerumanager-dark) .cmw-footer-remote-hint {
  color: var(--km-dark-text);
}

:global(html.kikoerumanager-dark) .cmw-split-title span,
:global(html.kikoerumanager-dark) .cmw-split-title code,
:global(html.kikoerumanager-dark) .cmw-side-path,
:global(html.kikoerumanager-dark) .cmw-side-meta span:last-child,
:global(html.kikoerumanager-dark) .cmw-loading-panel :deep(.app-loading-animation__description),
:global(html.kikoerumanager-dark) .cmw-summary-label,
:global(html.kikoerumanager-dark) .cmw-diff-pathtail,
:global(html.kikoerumanager-dark) .cmw-diff-note,
:global(html.kikoerumanager-dark) .cmw-diff-side-secondary,
:global(html.kikoerumanager-dark) .cmw-diff-empty,
:global(html.kikoerumanager-dark) .cmw-empty-state {
  color: var(--km-dark-text-muted);
}

:global(html.kikoerumanager-dark) .cmw-search-input::placeholder {
  color: var(--km-dark-text-subtle);
}

:global(html.kikoerumanager-dark) .cmw-search-input:focus {
  border-color: var(--km-dark-border-strong);
  background: var(--km-dark-field);
}

:global(html.kikoerumanager-dark) .cmw-close-btn:hover:not(:disabled),
:global(html.kikoerumanager-dark) .cmw-toolbar-btn:hover:not(:disabled),
:global(html.kikoerumanager-dark) .cmw-bulk-btn:hover:not(:disabled),
:global(html.kikoerumanager-dark) .cmw-pill:hover {
  border-color: var(--km-dark-border-strong);
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark) .cmw-bulk-btn + .cmw-bulk-btn {
  border-left-color: var(--km-dark-border-soft);
}

:global(html.kikoerumanager-dark) .cmw-pill.is-active {
  border-color: rgba(129, 140, 248, 0.46);
  background: rgba(99, 102, 241, 0.18);
  color: #c7d2fe;
}

:global(html.kikoerumanager-dark) .cmw-pill-count {
  background: rgba(255, 255, 255, 0.12);
}

:global(html.kikoerumanager-dark) .cmw-pill.is-active .cmw-pill-count {
  background: rgba(129, 140, 248, 0.22);
  color: #ddd6fe;
}

:global(html.kikoerumanager-dark) .cmw-split-list,
:global(html.kikoerumanager-dark) .cmw-table-pane {
  background: var(--km-dark-surface);
}

:global(html.kikoerumanager-dark) .cmw-split-row {
  border-bottom-color: var(--km-dark-border-soft);
}

:global(html.kikoerumanager-dark) .cmw-split-row:hover {
  background: var(--km-dark-surface-hover);
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-pickable:hover {
  background: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-picked {
  border-left-color: #60a5fa;
  background: rgba(96, 165, 250, 0.18);
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-added {
  border-left-color: #34d399;
  background: rgba(16, 185, 129, 0.13);
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-removed {
  border-left-color: #fb7185;
  background: rgba(244, 63, 94, 0.13);
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-changed {
  border-left-color: #fbbf24;
}

:global(html.kikoerumanager-dark) .cmw-side-line.is-missing {
  color: var(--km-dark-text-subtle);
  opacity: 0.8;
}

:global(html.kikoerumanager-dark) .cmw-side-meta .is-size-diff {
  color: var(--km-dark-amber);
}

:global(html.kikoerumanager-dark) .cmw-pick-mark {
  background: #60a5fa;
  color: #07111f;
}

:global(html.kikoerumanager-dark) .cmw-diff-table thead {
  background: rgba(16, 17, 22, 0.92);
}

:global(html.kikoerumanager-dark) .cmw-diff-th,
:global(html.kikoerumanager-dark) .cmw-diff-row {
  border-color: var(--km-dark-border-soft);
}

:global(html.kikoerumanager-dark) .cmw-diff-th {
  color: var(--km-dark-text-muted);
}

:global(html.kikoerumanager-dark) .cmw-diff-row:hover {
  background: var(--km-dark-surface-hover);
}

:global(html.kikoerumanager-dark) .cmw-diff-toggle:hover {
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark) .cmw-diff-glyph,
:global(html.kikoerumanager-dark) .cmw-diff-badge {
  background: var(--km-dark-accent-bg);
  color: var(--km-dark-text-muted);
  border-color: var(--km-dark-border-soft);
}

:global(html.kikoerumanager-dark) .cmw-diff-glyph.is-new,
:global(html.kikoerumanager-dark) .cmw-diff-badge.is-new {
  background: rgba(16, 185, 129, 0.16);
  color: #a7f3d0;
  border-color: rgba(52, 211, 153, 0.22);
}

:global(html.kikoerumanager-dark) .cmw-diff-glyph.is-old,
:global(html.kikoerumanager-dark) .cmw-diff-badge.is-old {
  background: rgba(99, 102, 241, 0.18);
  color: #c7d2fe;
  border-color: rgba(129, 140, 248, 0.24);
}

:global(html.kikoerumanager-dark) .cmw-diff-glyph.is-size,
:global(html.kikoerumanager-dark) .cmw-diff-glyph.is-time,
:global(html.kikoerumanager-dark) .cmw-diff-badge.is-size,
:global(html.kikoerumanager-dark) .cmw-diff-badge.is-time {
  background: rgba(245, 158, 11, 0.16);
  color: #fde68a;
  border-color: rgba(251, 191, 36, 0.24);
}

:global(html.kikoerumanager-dark) .cmw-diff-glyph.is-content,
:global(html.kikoerumanager-dark) .cmw-diff-badge.is-content {
  background: rgba(244, 63, 94, 0.16);
  color: #fecdd3;
  border-color: rgba(251, 113, 133, 0.24);
}

:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-audio-lossless { color: #93c5fd; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-audio { color: #c4b5fd; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-image { color: #fdba74; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-video { color: #a5b4fc; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-pdf { color: #fca5a5; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-archive { color: #fcd34d; }
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-text,
:global(html.kikoerumanager-dark) .cmw-diff-fileicon.icon-file { color: var(--km-dark-text-muted); }

:global(html.kikoerumanager-dark) .cmw-footer {
  border-top-color: var(--km-dark-border-soft);
  background: rgba(36, 37, 41, 0.92);
}

:global(html.kikoerumanager-dark) .cmw-action-btn.is-slate {
  border-color: var(--km-dark-border);
  background: var(--km-dark-accent-bg);
  color: var(--km-dark-text);
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .cmw-action-btn.is-slate:hover:not(:disabled) {
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .cmw-action-btn.is-emerald {
  background: #111827;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .cmw-action-btn.is-emerald:hover:not(:disabled) {
  background: #172033;
  box-shadow: none;
}

button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.55; }

@media (max-width: 768px) {
  .cmw-shell {
    width: 96vw;
    height: 92vh;
  }
}
</style>

