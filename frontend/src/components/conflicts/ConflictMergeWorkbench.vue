<template>
  <el-dialog
    v-model="visible"
    class="conflict-merge-dialog"
    width="94%"
    top="3vh"
    :close-on-click-modal="false"
    :destroy-on-close="false"
  >
    <template #header>
      <div class="dialog-header">
        <div class="header-copy">
          <h3>目录差异工作台</h3>
          <p>{{ conflictTitle }}</p>
        </div>
        <div v-if="preview" class="header-tags">
          <button class="header-chip changed" type="button" @click="setStatusFilter('changed')">
            <span>差异</span>
            <strong>{{ displaySummary.changed }}</strong>
          </button>
          <button class="header-chip new-only" type="button" @click="setStatusFilter('new_only')">
            <span>新包独有</span>
            <strong>{{ displaySummary.newOnly }}</strong>
          </button>
          <button class="header-chip old-only" type="button" @click="setStatusFilter('old_only')">
            <span>库存独有</span>
            <strong>{{ displaySummary.oldOnly }}</strong>
          </button>
          <button class="header-chip unchanged" type="button" @click="setStatusFilter('unchanged')">
            <span>一致</span>
            <strong>{{ displaySummary.unchanged }}</strong>
          </button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="merge-workbench">
      <template v-if="preview">
        <div class="toolbar">
          <div class="toolbar-left">
            <el-input
              v-model="searchText"
              placeholder="搜索文件名或相对路径"
              clearable
            />
            <el-select v-model="statusFilter" class="status-filter">
              <el-option label="全部项目" value="all" />
              <el-option label="仅差异项" value="changed" />
              <el-option label="仅新包独有" value="new_only" />
              <el-option label="仅库存独有" value="old_only" />
              <el-option label="仅大小不同" value="size_changed" />
              <el-option label="仅其他差异" value="other_changed" />
              <el-option label="仅一致" value="unchanged" />
            </el-select>
          </div>
          <div class="toolbar-right">
            <el-button @click="resetDecisions">恢复默认决策</el-button>
            <el-button @click="$emit('refresh')" :disabled="submitting">重新生成预览</el-button>
          </div>
        </div>

        <div class="filter-strip">
          <button
            v-for="pill in filterPills"
            :key="pill.value"
            class="filter-pill"
            :class="[pill.tone, { active: isFilterActive(pill.value) }]"
            type="button"
            @click="setStatusFilter(pill.value)"
          >
            <span class="filter-pill__label">{{ pill.label }}</span>
            <strong class="filter-pill__count">{{ pill.count }}</strong>
          </button>
        </div>

        <div class="panels">
          <section class="panel summary-panel">
            <div class="panel-title">差异总览</div>

            <div class="summary-grid">
              <div class="summary-card highlight">
                <strong>{{ displaySummary.changed }}</strong>
                <span>需要处理的差异</span>
              </div>
              <div class="summary-card success">
                <strong>{{ displaySummary.newOnly }}</strong>
                <span>新包独有</span>
              </div>
              <div class="summary-card neutral">
                <strong>{{ displaySummary.oldOnly }}</strong>
                <span>库存独有</span>
              </div>
              <div class="summary-card warning">
                <strong>{{ displaySummary.changedBoth }}</strong>
                <span>同名但不一致</span>
              </div>
              <div class="summary-card calm">
                <strong>{{ displaySummary.unchanged }}</strong>
                <span>一致项也会显示</span>
              </div>
              <div class="summary-card calm">
                <strong>{{ preview.summary?.total_files || 0 }}</strong>
                <span>文件总数</span>
              </div>
            </div>

            <div class="summary-section">
              <div class="section-label">路径基准</div>
              <div class="path-stack">
                <div class="path-card existing">
                  <label>{{ existingPaneLabel }}</label>
                  <span>{{ resolvedExistingPath }}</span>
                </div>
                <div class="path-card incoming">
                  <label>新包内容</label>
                  <span>{{ resolvedSourcePath }}</span>
                </div>
              </div>
            </div>

            <div class="summary-section">
              <div class="section-label">当前决策</div>
              <div class="decision-grid">
                <div class="decision-card incoming">
                  <strong>{{ decisionSummary.useNew }}</strong>
                  <span>取新包</span>
                </div>
                <div class="decision-card existing">
                  <strong>{{ decisionSummary.useOld }}</strong>
                  <span>取库存</span>
                </div>
                <div class="decision-card delete">
                  <strong>{{ decisionSummary.delete }}</strong>
                  <span>删除</span>
                </div>
              </div>
            </div>
          </section>

          <section class="panel table-panel">
            <div class="panel-title">左右对照差异树</div>
            <el-table
              :data="filteredTreeData"
              row-key="node_key"
              class="diff-table"
              border
              height="62vh"
              default-expand-all
              :row-class-name="resolveRowClassName"
              :tree-props="{ children: 'children' }"
            >
              <el-table-column label="差异树" min-width="280">
                <template #default="{ row }">
                  <div class="node-cell" :style="nodeIndentStyle(row)">
                    <span class="node-spacer" aria-hidden="true" />
                    <span class="node-icon-badge">
                      <el-icon class="node-icon">
                        <Folder v-if="row.type === 'dir'" />
                        <Document v-else />
                      </el-icon>
                      <span class="node-icon-dot" :class="statusToneClass(row)" />
                    </span>
                    <div class="node-copy">
                      <div class="node-topline">
                        <span class="node-name" :title="row.name">{{ row.name }}</span>
                        <span class="status-text" :class="statusToneClass(row)">
                          {{ displayStatusInfo(row).label }}
                        </span>
                      </div>
                      <div class="node-path" :title="row.relative_path || '/'">
                        {{ row.relative_path || '/' }}
                      </div>
                      <div
                        v-if="displayStatusInfo(row).note"
                        class="node-note"
                      >
                        {{ displayStatusInfo(row).note }}
                      </div>
                    </div>
                  </div>
                </template>
              </el-table-column>

              <el-table-column :label="existingPaneLabel" min-width="250">
                <template #default="{ row }">
                  <div class="side-pane existing" :class="[sidePaneToneClass(row, 'old'), { missing: !hasSide(row, 'old') }]">
                    <template v-if="hasSide(row, 'old')">
                      <div class="side-head">
                        <span class="side-state">{{ row.type === 'dir' ? '目录' : '已存在' }}</span>
                        <span class="side-size">{{ formatSidePrimary(row, 'old') }}</span>
                      </div>
                      <div class="side-path">{{ formatSideRelativePath(row, 'old') }}</div>
                      <div class="side-meta">{{ formatSideTime(row, 'old') }}</div>
                    </template>
                    <template v-else>
                      <div class="side-empty">无此项目</div>
                    </template>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="新包内容" min-width="250">
                <template #default="{ row }">
                  <div class="side-pane incoming" :class="[sidePaneToneClass(row, 'new'), { missing: !hasSide(row, 'new') }]">
                    <template v-if="hasSide(row, 'new')">
                      <div class="side-head">
                        <span class="side-state">{{ row.type === 'dir' ? '目录' : '新包提供' }}</span>
                        <span class="side-size">{{ formatSidePrimary(row, 'new') }}</span>
                      </div>
                      <div class="side-path">{{ formatSideRelativePath(row, 'new') }}</div>
                      <div class="side-meta">{{ formatSideTime(row, 'new') }}</div>
                    </template>
                    <template v-else>
                      <div class="side-empty">无此项目</div>
                    </template>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="合并决策" width="170">
                <template #default="{ row }">
                  <template v-if="row.type === 'file'">
                    <el-select
                      :model-value="decisionFor(row)"
                      size="small"
                      :disabled="submitting"
                      @change="value => updateDecision(row, value)"
                    >
                      <el-option
                        v-for="option in decisionOptions(row)"
                        :key="option.value"
                        :label="option.label"
                        :value="option.value"
                      />
                    </el-select>
                  </template>
                  <span v-else class="dir-note">目录自动对齐</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
      </template>

      <el-empty v-else description="暂无合并预览数据" />
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="visible = false" :disabled="submitting">关闭</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!preview"
          @click="$emit('submit')"
        >
          生成并提交合并结果
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Document, Folder } from '@element-plus/icons-vue'

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
.dialog-header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
}

.header-copy h3 {
  margin: 0 0 8px;
  font-size: 22px;
  color: #0f172a;
  letter-spacing: 0.02em;
}

.header-copy p {
  margin: 0;
  color: #64748b;
}

.header-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.header-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: #fff;
  color: #334155;
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}

.header-chip span {
  font-size: 12px;
  font-weight: 600;
}

.header-chip strong {
  font-size: 14px;
}

.header-chip:hover {
  transform: translateY(-1px);
}

.header-chip.changed {
  background: #fff7ed;
  border-color: #fdba74;
  color: #9a3412;
}

.header-chip.new-only {
  background: #effcf3;
  border-color: #86efac;
  color: #166534;
}

.header-chip.old-only {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.header-chip.unchanged {
  background: #eef4ff;
  border-color: #bfdbfe;
  color: #1e40af;
}

.merge-workbench {
  min-height: 320px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  gap: 12px;
  align-items: center;
}

.toolbar-left {
  flex: 1;
}

.status-filter {
  width: 180px;
}

.filter-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid #dbe4f0;
  background: #fff;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-pill:hover {
  border-color: #94a3b8;
}

.filter-pill.active {
  transform: translateY(-1px);
  box-shadow: 0 10px 20px rgba(148, 163, 184, 0.16);
}

.filter-pill__label {
  font-size: 12px;
  font-weight: 700;
}

.filter-pill__count {
  font-size: 14px;
}

.filter-pill.all.active {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #0f172a;
}

.filter-pill.changed.active {
  background: #fff7ed;
  border-color: #fdba74;
  color: #9a3412;
}

.filter-pill.new-only.active {
  background: #effcf3;
  border-color: #86efac;
  color: #166534;
}

.filter-pill.old-only.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.filter-pill.unchanged.active {
  background: #eef4ff;
  border-color: #bfdbfe;
  color: #1e40af;
}

.panels {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
}

.panel {
  border: 1px solid #dbe4f0;
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 251, 255, 0.98) 100%);
  overflow: hidden;
  box-shadow: 0 18px 40px rgba(148, 163, 184, 0.12);
}

.panel-title {
  padding: 14px 16px;
  font-weight: 700;
  color: #0f172a;
  background: linear-gradient(180deg, #fdfefe 0%, #f5f8fc 100%);
  border-bottom: 1px solid #dbe4f0;
}

.summary-panel {
  display: flex;
  flex-direction: column;
}

.summary-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 16px;
}

.summary-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid transparent;
}

.summary-card strong {
  font-size: 24px;
  line-height: 1;
}

.summary-card span {
  font-size: 13px;
}

.summary-card.highlight {
  background: linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%);
  border-color: #fdba74;
  color: #9a3412;
}

.summary-card.success {
  background: linear-gradient(180deg, #effcf3 0%, #dcfce7 100%);
  border-color: #86efac;
  color: #166534;
}

.summary-card.neutral,
.summary-card.calm {
  background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  border-color: #cbd5e1;
  color: #334155;
}

.summary-card.warning {
  background: linear-gradient(180deg, #fefce8 0%, #fef3c7 100%);
  border-color: #fcd34d;
  color: #92400e;
}

.summary-section {
  display: grid;
  gap: 10px;
  padding: 0 16px 16px;
}

.section-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #64748b;
  text-transform: uppercase;
}

.path-stack {
  display: grid;
  gap: 10px;
}

.path-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid #dbe4f0;
}

.path-card label {
  font-size: 12px;
  color: #64748b;
}

.path-card span {
  font-family: Consolas, Monaco, monospace;
  word-break: break-all;
  color: #0f172a;
}

.path-card.existing {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.path-card.incoming {
  background: linear-gradient(180deg, #f4fff7 0%, #e7fbe9 100%);
  border-color: #9dd8a8;
}

.decision-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}

.decision-card {
  display: grid;
  gap: 5px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid #dbe4f0;
}

.decision-card strong {
  font-size: 22px;
}

.decision-card.incoming {
  background: linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%);
  color: #166534;
  border-color: #86efac;
}

.decision-card.existing {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  color: #334155;
}

.decision-card.delete {
  background: linear-gradient(180deg, #fff5f5 0%, #fee2e2 100%);
  color: #b91c1c;
  border-color: #fca5a5;
}

.table-panel {
  min-width: 0;
}

.node-cell {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
  padding-left: 0;
}

.node-spacer {
  width: var(--node-indent, 0px);
  flex: 0 0 var(--node-indent, 0px);
  height: 1px;
}

.node-icon-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 12px;
  border: 1px solid #dbe4f0;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  flex: 0 0 auto;
  margin-left: 0;
}

.node-icon {
  font-size: 18px;
  color: #64748b;
}

.node-icon-dot {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 11px;
  height: 11px;
  border-radius: 999px;
  border: 2px solid #fff;
  background: #94a3b8;
}

.node-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.node-topline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.node-name {
  font-weight: 600;
  color: #0f172a;
  word-break: break-all;
}

.node-path {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  color: #64748b;
  word-break: break-all;
}

.node-note {
  font-size: 12px;
  color: #475569;
}

.status-text {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.tone-new-only.status-text {
  color: #166534;
}

.node-icon-dot.tone-new-only {
  background: #16a34a;
}

.tone-old-only.status-text {
  color: #1d4ed8;
}

.node-icon-dot.tone-old-only {
  background: #2563eb;
}

.tone-size-changed.status-text,
.tone-time-changed.status-text,
.tone-content-changed.status-text {
  color: #b91c1c;
}

.node-icon-dot.tone-size-changed,
.node-icon-dot.tone-time-changed,
.node-icon-dot.tone-content-changed {
  background: #dc2626;
}

.tone-unchanged.status-text {
  color: #64748b;
}

.node-icon-dot.tone-unchanged {
  background: #94a3b8;
}

.side-pane {
  display: grid;
  gap: 5px;
  min-height: auto;
  padding: 4px 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.side-pane.missing {
  color: #b91c1c;
}

.side-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: baseline;
}

.side-state {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #64748b;
}

.side-size {
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}

.side-pane.existing .side-size {
  color: #334155;
}

.side-pane.incoming .side-size {
  color: #15803d;
}

.side-meta,
.side-path,
.side-empty {
  font-size: 12px;
  color: #64748b;
}

.side-path {
  font-family: Consolas, Monaco, monospace;
  word-break: break-all;
}

.dir-note {
  font-size: 12px;
  color: #94a3b8;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

:deep(.diff-table .row-new-only) {
  background: rgba(240, 253, 244, 0.72);
}

:deep(.diff-table .row-unchanged) {
  background: transparent;
}

:deep(.diff-table .row-unchanged .node-name),
:deep(.diff-table .row-unchanged .status-text),
:deep(.diff-table .row-unchanged .node-note),
:deep(.diff-table .row-unchanged .side-state),
:deep(.diff-table .row-unchanged .side-path),
:deep(.diff-table .row-unchanged .side-meta),
:deep(.diff-table .row-unchanged .side-empty) {
  color: #64748b;
}

:deep(.diff-table .row-old-only) {
  background: rgba(239, 246, 255, 0.84);
}

:deep(.diff-table .row-old-only .node-name),
:deep(.diff-table .row-old-only .status-text),
:deep(.diff-table .row-old-only .node-note),
:deep(.diff-table .row-old-only .side-state),
:deep(.diff-table .row-old-only .side-path),
:deep(.diff-table .row-old-only .side-meta),
:deep(.diff-table .row-old-only .side-empty) {
  color: #1d4ed8;
}

:deep(.diff-table .row-size-changed) {
  background: rgba(254, 242, 242, 0.9);
}

:deep(.diff-table .row-size-changed .node-name),
:deep(.diff-table .row-size-changed .status-text),
:deep(.diff-table .row-size-changed .node-note),
:deep(.diff-table .row-size-changed .side-state),
:deep(.diff-table .row-size-changed .side-path),
:deep(.diff-table .row-size-changed .side-meta),
:deep(.diff-table .row-size-changed .side-empty) {
  color: #b91c1c;
}

:deep(.diff-table .row-new-only .node-name),
:deep(.diff-table .row-new-only .status-text),
:deep(.diff-table .row-new-only .node-note),
:deep(.diff-table .row-new-only .side-state),
:deep(.diff-table .row-new-only .side-path),
:deep(.diff-table .row-new-only .side-meta),
:deep(.diff-table .row-new-only .side-empty) {
  color: #166534;
}

:deep(.diff-table .row-modified) {
  background: rgba(254, 242, 242, 0.78);
}

:deep(.diff-table .row-modified .node-name),
:deep(.diff-table .row-modified .status-text),
:deep(.diff-table .row-modified .node-note),
:deep(.diff-table .row-modified .side-state),
:deep(.diff-table .row-modified .side-path),
:deep(.diff-table .row-modified .side-meta),
:deep(.diff-table .row-modified .side-empty) {
  color: #b91c1c;
}

:deep(.diff-table .el-table__row td:first-child .cell) {
  display: flex;
  align-items: flex-start;
}

:deep(.diff-table .el-table__indent) {
  width: 18px !important;
  flex: 0 0 18px;
}

:deep(.diff-table .el-table__placeholder) {
  width: 18px !important;
  flex: 0 0 18px;
}

:deep(.diff-table .el-table__expand-icon) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  margin-right: 6px;
  margin-top: 8px;
  color: #64748b;
  transform: none;
}

@media (max-width: 1320px) {
  .panels {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .toolbar {
    flex-direction: column;
  }

  .toolbar-left,
  .toolbar-right {
    width: 100%;
    flex-wrap: wrap;
  }

  .status-filter {
    width: 100%;
  }

  .filter-strip {
    gap: 8px;
  }

  .decision-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .dialog-header {
    flex-direction: column;
  }

  .header-tags {
    justify-content: flex-start;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
