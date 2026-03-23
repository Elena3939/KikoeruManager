<template>
  <el-dialog
    v-model="visible"
    class="conflict-merge-dialog"
    width="92%"
    top="4vh"
    :close-on-click-modal="false"
    :destroy-on-close="false"
  >
    <template #header>
      <div class="dialog-header">
        <div>
          <h3>组件文件夹对比</h3>
          <p>{{ conflictTitle }}</p>
        </div>
        <div class="header-tags" v-if="preview">
          <el-tag type="primary">文件 {{ preview.summary?.total_files || 0 }}</el-tag>
          <el-tag>目录 {{ preview.summary?.total_dirs || 0 }}</el-tag>
          <el-tag type="success">新增 {{ preview.summary?.new_only || 0 }}</el-tag>
          <el-tag type="warning">修改 {{ preview.summary?.modified || 0 }}</el-tag>
          <el-tag type="info">旧版独有 {{ preview.summary?.old_only || 0 }}</el-tag>
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
              <el-option label="全部状态" value="all" />
              <el-option label="仅新增" value="new_only" />
              <el-option label="仅删除" value="old_only" />
              <el-option label="仅修改" value="modified" />
              <el-option label="仅未变化" value="unchanged" />
            </el-select>
          </div>
          <div class="toolbar-right">
            <el-button @click="resetDecisions">恢复默认决策</el-button>
            <el-button @click="$emit('refresh')" :disabled="submitting">重新生成预览</el-button>
          </div>
        </div>

        <div class="panels">
          <section class="panel summary-panel">
            <div class="panel-title">最终结果预览</div>
            <div class="summary-grid">
              <div class="summary-card">
                <strong>{{ decisionSummary.useNew }}</strong>
                <span>保留新文件</span>
              </div>
              <div class="summary-card">
                <strong>{{ decisionSummary.useOld }}</strong>
                <span>保留旧文件</span>
              </div>
              <div class="summary-card danger">
                <strong>{{ decisionSummary.delete }}</strong>
                <span>删除文件</span>
              </div>
              <div class="summary-card neutral">
                <strong>{{ conflictSourceLabel }}</strong>
                <span>目标落地</span>
              </div>
            </div>
            <div class="path-grid">
              <div>
                <label>新内容来源</label>
                <span>{{ conflict?.new_path || '-' }}</span>
              </div>
              <div>
                <label>已存在目录</label>
                <span>{{ preview.existing_path || '-' }}</span>
              </div>
            </div>
          </section>

          <section class="panel table-panel">
            <div class="panel-title">文件级差异与决策</div>
            <el-table
              :data="filteredTreeData"
              row-key="node_key"
              border
              height="58vh"
              default-expand-all
              :tree-props="{ children: 'children' }"
            >
              <el-table-column label="名称" min-width="220">
                <template #default="{ row }">
                  <div class="name-cell">
                    <el-icon>
                      <Folder v-if="row.type === 'dir'" />
                      <Document v-else />
                    </el-icon>
                    <span class="file-name" :title="row.name">{{ row.name }}</span>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="相对路径" min-width="260">
                <template #default="{ row }">
                  <span class="path-text" :title="row.relative_path">{{ row.relative_path || '/' }}</span>
                </template>
              </el-table-column>

              <el-table-column label="来源" width="110">
                <template #default="{ row }">
                  <el-tag :type="sourceTagType(row.source)" effect="plain">{{ sourceLabel(row.source) }}</el-tag>
                </template>
              </el-table-column>

              <el-table-column label="差异状态" width="120">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>

              <el-table-column label="新版信息" min-width="180">
                <template #default="{ row }">
                  <div class="meta-cell">
                    <span>{{ formatFileSize(row.new_size) }}</span>
                    <span>{{ formatDate(row.new_mtime) }}</span>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="旧版信息" min-width="180">
                <template #default="{ row }">
                  <div class="meta-cell">
                    <span>{{ formatFileSize(row.old_size) }}</span>
                    <span>{{ formatDate(row.old_mtime) }}</span>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="文件决策" width="170">
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
                  <span v-else class="dir-note">目录自动纳入</span>
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
  const contextLabel = props.conflict?.context?.existing?.is_remote ? '远程目录' : '本地目录'
  return `${props.conflict.rjcode || '未识别 RJ'} · ${contextLabel}`
})

const conflictSourceLabel = computed(() => {
  if (props.conflict?.context?.existing?.is_remote) {
    return '群晖上传'
  }
  return '本地落盘'
})

const filteredTreeData = computed(() => {
  return filterNodes(buildTree(compareItems.value), {
    searchText: searchText.value,
    status: statusFilter.value
  })
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
  const status = filters.status || 'all'

  return nodes
    .map(node => {
      const children = filterNodes(node.children || [], filters)
      const matchesQuery =
        !query ||
        String(node.name || '').toLowerCase().includes(query) ||
        String(node.relative_path || '').toLowerCase().includes(query)
      const matchesStatus = status === 'all' || node.status === status
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
    options.push({ label: '保留新文件', value: 'use_new' })
  }
  if (row.old_path) {
    options.push({ label: '保留旧文件', value: 'use_old' })
  }
  options.push({ label: '删除文件', value: 'delete' })
  return options
}

function statusLabel(status) {
  return {
    new_only: '新增',
    old_only: '删除',
    modified: '修改',
    unchanged: '未变化'
  }[status] || status
}

function sourceLabel(source) {
  return {
    new: '仅新',
    old: '仅旧',
    both: '双方'
  }[source] || source
}

function statusTagType(status) {
  return {
    new_only: 'success',
    old_only: 'info',
    modified: 'warning',
    unchanged: ''
  }[status] || ''
}

function sourceTagType(source) {
  return {
    new: 'success',
    old: 'info',
    both: 'primary'
  }[source] || ''
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
  gap: 16px;
}

.dialog-header h3 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #172554;
}

.dialog-header p {
  margin: 0;
  color: #64748b;
}

.header-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.merge-workbench {
  min-height: 320px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
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
  width: 160px;
}

.panels {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.panel {
  border: 1px solid #dbe4f0;
  border-radius: 14px;
  background: #fff;
  overflow: hidden;
}

.panel-title {
  padding: 14px 16px;
  font-weight: 600;
  color: #1e293b;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fb 100%);
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
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border-radius: 12px;
  background: #eff6ff;
  color: #1d4ed8;
}

.summary-card.danger {
  background: #fef2f2;
  color: #b91c1c;
}

.summary-card.neutral {
  background: #f8fafc;
  color: #334155;
}

.summary-card strong {
  font-size: 24px;
}

.path-grid {
  display: grid;
  gap: 12px;
  padding: 0 16px 16px;
}

.path-grid div {
  display: grid;
  gap: 6px;
  padding: 12px;
  border-radius: 12px;
  background: #f8fafc;
}

.path-grid label {
  font-size: 12px;
  color: #64748b;
}

.path-grid span {
  font-family: Consolas, Monaco, monospace;
  word-break: break-all;
  color: #1e293b;
}

.table-panel {
  min-width: 0;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.file-name,
.path-text {
  display: inline-block;
  min-width: 0;
  word-break: break-all;
}

.path-text {
  font-family: Consolas, Monaco, monospace;
  color: #475569;
}

.meta-cell {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: #475569;
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

@media (max-width: 1200px) {
  .panels {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
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
}
</style>
