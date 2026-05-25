import { useMemo, useState } from 'react'
import {
  Archive,
  ArrowDownToLine,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  Folder,
  GitMerge,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Upload,
  X
} from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button } from '../../components/Primitives'
import { formatBytes, formatDateTime } from '../../utils/format'
import { formatConflictLabel, getConflictSourcePath, getExistingConflictPath } from './conflictUtils'

const filterOptions = [
  { value: 'all', label: '全部项目' },
  { value: 'changed', label: '仅差异项' },
  { value: 'new_only', label: '仅新包独有' },
  { value: 'old_only', label: '仅库存独有' },
  { value: 'size_changed', label: '仅大小不同' },
  { value: 'other_changed', label: '仅其他差异' },
  { value: 'unchanged', label: '仅一致' }
]

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
  done: 6,
  failed: -1
}

function normalizePath(path) {
  return String(path || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

function getParentPath(path) {
  const normalized = normalizePath(path)
  if (!normalized || !normalized.includes('/')) return ''
  return normalized.split('/').slice(0, -1).join('/')
}

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
      node_key: `${item.type || 'file'}:${relativePath || '/'}`,
      relative_path: relativePath,
      name: item.name || (relativePath ? relativePath.split('/').pop() : '/'),
      children: []
    })
    const parts = relativePath ? relativePath.split('/') : []
    for (let index = 0; index < parts.length - 1; index += 1) ensureNode(parts.slice(0, index + 1).join('/'), 'dir')
  })
  const roots = []
  Array.from(nodeMap.values()).forEach(node => {
    const parentPath = getParentPath(node.relative_path)
    if (!parentPath) {
      roots.push(node)
      return
    }
    const parentNode = ensureNode(parentPath, 'dir')
    if (!parentNode.children.some(child => child.node_key === node.node_key)) parentNode.children.push(node)
  })
  return sortNodes(roots)
}

function sortNodes(nodes) {
  return [...nodes]
    .sort((left, right) => {
      if (left.type !== right.type) return left.type === 'dir' ? -1 : 1
      return String(left.relative_path || '').localeCompare(String(right.relative_path || ''), 'zh-CN')
    })
    .map(node => ({ ...node, children: sortNodes(node.children || []) }))
}

function displayStatusInfo(row) {
  const itemType = String(row?.type || 'file')
  const status = String(row?.status || '')
  if (itemType === 'dir') {
    if (status === 'new_only') return { key: 'new_only', label: '新包目录', note: '目录仅存在于新包侧' }
    if (status === 'old_only') return { key: 'old_only', label: '库存目录', note: '目录仅存在于库存侧' }
    return { key: 'unchanged', label: '目录已对齐', note: '' }
  }
  if (status === 'new_only') return { key: 'new_only', label: '新包独有', note: '库存侧没有对应文件' }
  if (status === 'old_only') return { key: 'old_only', label: '库存独有', note: '新包侧没有对应文件' }
  if (row?.matched_by === 'name_size') return { key: 'unchanged', label: '已配对', note: '已按文件名和大小配对' }
  const newSize = Number(row?.new_size)
  const oldSize = Number(row?.old_size)
  if (Number.isFinite(newSize) && Number.isFinite(oldSize) && newSize !== oldSize) {
    return { key: 'size_changed', label: '大小不同', note: `库存 ${formatBytes(oldSize)} / 新包 ${formatBytes(newSize)}` }
  }
  if (status === 'modified') {
    if (row?.compare_basis === 'content') return { key: 'content_changed', label: '内容不同', note: '名称与大小一致，但内容校验不同' }
    return { key: 'time_changed', label: '时间不同', note: '名称与大小一致，但修改时间不同' }
  }
  return { key: 'unchanged', label: '一致', note: '同名且无需额外处理' }
}

function matchStatusFilter(key, filter) {
  if (filter === 'all') return true
  if (filter === 'changed') return key !== 'unchanged'
  if (filter === 'other_changed') return key === 'content_changed' || key === 'time_changed'
  return key === filter
}

function filterNodes(nodes, filters) {
  const query = String(filters.searchText || '').trim().toLowerCase()
  const status = filters.status || 'changed'
  return nodes.map(node => {
    const children = filterNodes(node.children || [], filters)
    const statusInfo = displayStatusInfo(node)
    const matchesQuery = !query || String(node.name || '').toLowerCase().includes(query) || String(node.relative_path || '').toLowerCase().includes(query)
    const matchesStatus = matchStatusFilter(statusInfo.key, status)
    const includeSelf = matchesQuery && (node.type === 'dir' || matchesStatus)
    if (!includeSelf && children.length === 0) return null
    return { ...node, children }
  }).filter(Boolean)
}

function flattenTree(nodes, collapsed, depth = 0) {
  const result = []
  for (const node of nodes) {
    const isCollapsed = collapsed.has(node.relative_path)
    result.push({ ...node, _depth: depth, _collapsed: isCollapsed, _hasChildren: (node.children || []).length > 0 })
    if (!isCollapsed && node.children?.length) result.push(...flattenTree(node.children, collapsed, depth + 1))
  }
  return result
}

function statusGlyph(row) {
  const key = displayStatusInfo(row).key
  if (key === 'new_only') return '+'
  if (key === 'old_only') return '-'
  if (key === 'size_changed' || key === 'content_changed') return '≠'
  if (key === 'time_changed') return '∆'
  return '='
}

function pathTail(relativePath) {
  const parts = String(relativePath || '').split('/').filter(Boolean)
  if (parts.length <= 1) return ''
  const parent = parts.slice(0, -1).join('/')
  return parent.length > 64 ? `...${parent.slice(-60)}` : parent
}

function sidePrimary(row, side) {
  if (row.type === 'dir') return '目录'
  const value = side === 'new' ? row.new_size : row.old_size
  return value == null ? '-' : formatBytes(value)
}

function sideTime(row, side) {
  const value = side === 'new' ? row.new_mtime : row.old_mtime
  if (!value && value !== 0) return '-'
  return typeof value === 'number' ? formatDateTime(new Date(value * 1000).toISOString()) : formatDateTime(value)
}

function decisionFor(row, decisions, preview) {
  return decisions?.[row.relative_path] || preview?.default_decisions?.[row.relative_path] || (row.status === 'old_only' ? 'use_old' : 'use_new')
}

function decisionOptions(row) {
  const options = []
  if (row.new_path) options.push({ label: '取新包', short: '新', value: 'use_new' })
  if (row.old_path) options.push({ label: '取库存', short: '库', value: 'use_old' })
  options.push({ label: '删除', short: '删', value: 'delete' })
  return options
}

export function ConflictMergeWorkbench({
  open,
  conflict,
  preview,
  decisions,
  loading,
  progress,
  submitting,
  onClose,
  onRefresh,
  onDecisionChange,
  onSubmit
}) {
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState('changed')
  const [collapsed, setCollapsed] = useState(() => new Set())

  const compareItems = preview?.items || []
  const tree = useMemo(() => buildTree(compareItems), [compareItems])
  const rows = useMemo(() => flattenTree(filterNodes(tree, { searchText, status: statusFilter }), collapsed), [collapsed, searchText, statusFilter, tree])
  const isRemoteTarget = Boolean(conflict?.context?.existing?.is_remote)
  const fileItems = compareItems.filter(item => item.type === 'file')
  const summary = useMemo(() => {
    const next = { changed: 0, newOnly: 0, oldOnly: 0, unchanged: 0 }
    for (const item of fileItems) {
      const key = displayStatusInfo(item).key
      if (key === 'new_only') { next.newOnly += 1; next.changed += 1 }
      else if (key === 'old_only') { next.oldOnly += 1; next.changed += 1 }
      else if (key === 'unchanged') next.unchanged += 1
      else next.changed += 1
    }
    return next
  }, [fileItems])
  const decisionSummary = useMemo(() => {
    const next = { useNew: 0, useOld: 0, delete: 0 }
    for (const item of fileItems) {
      const decision = decisionFor(item, decisions, preview)
      if (decision === 'use_new') next.useNew += 1
      else if (decision === 'use_old') next.useOld += 1
      else if (decision === 'delete') next.delete += 1
    }
    return next
  }, [decisions, fileItems, preview])

  if (!open) return null

  function updateDecision(row, value) {
    onDecisionChange({ ...(decisions || {}), [row.relative_path]: value })
  }

  function batchSetDecision(decision) {
    const next = { ...(decisions || {}) }
    for (const item of fileItems) {
      if (decision === 'use_new' && !item.new_path) continue
      if (decision === 'use_old' && !item.old_path) continue
      next[item.relative_path] = decision
    }
    onDecisionChange(next)
  }

  const steps = ['准备工作区', conflict?.context?.new_path_kind === 'archive' ? '复制压缩包' : '读取目录', '解压新包', '过滤临时文件', isRemoteTarget ? '读取远程库存' : '扫描库存目录', '生成差异树']
  const currentStep = STAGE_TO_STEP_INDEX[progress?.stage] ?? 0

  return (
    <div className="merge-workbench-overlay">
      <div className="merge-workbench-backdrop" onClick={submitting ? undefined : onClose} />
      <section className="merge-workbench">
        <header className="merge-workbench-head">
          <div>
            <span><GitMerge size={18} /></span>
            <div>
              <h2>目录差异工作台</h2>
              <p>{formatConflictLabel(conflict)} · 按相对路径自动配对</p>
            </div>
            {isRemoteTarget ? <em><Upload size={12} />远程合并</em> : null}
          </div>
          <button type="button" disabled={submitting} onClick={onClose}><X size={16} /></button>
        </header>

        <div className="merge-toolbar">
          <label>
            <Search size={14} />
            <input value={searchText} onChange={event => setSearchText(event.target.value)} placeholder="搜索文件名或路径" />
          </label>
          <AppDropdown value={statusFilter} onChange={setStatusFilter} options={filterOptions} width={176} />
          <button type="button" disabled={submitting || loading} onClick={() => batchSetDecision('use_new')}><ArrowDownToLine size={13} />全取新包</button>
          <button type="button" disabled={submitting || loading} onClick={() => batchSetDecision('use_old')}><Archive size={13} />全取库存</button>
          <button type="button" disabled={submitting || loading} onClick={() => onDecisionChange({ ...(preview?.default_decisions || {}) })}><RotateCcw size={14} />智能默认</button>
          <button type="button" disabled={submitting || loading} onClick={onRefresh}><RefreshCw size={14} className={loading ? 'km-spin' : ''} />重新生成</button>
        </div>

        {preview ? (
          <div className="merge-pill-bar">
            {[
              ['all', '全部', fileItems.length],
              ['changed', '差异', summary.changed],
              ['new_only', '新包独有', summary.newOnly],
              ['old_only', '库存独有', summary.oldOnly],
              ['unchanged', '一致', summary.unchanged]
            ].map(([value, label, count]) => (
              <button type="button" key={value} className={statusFilter === value ? 'is-active' : ''} onClick={() => setStatusFilter(value)}>
                {label}<span>{count}</span>
              </button>
            ))}
          </div>
        ) : null}

        {loading || progress?.status === 'failed' ? (
          <div className="merge-loading-panel">
            <div>
              {progress?.status === 'failed' ? <X size={26} /> : <Loader2 size={26} className="km-spin" />}
              <h3>{progress?.stage_label || (progress?.status === 'failed' ? '合并预览失败' : '初始化')}</h3>
              <p>{progress?.message || '准备中...'}</p>
              <span className="merge-loading-bar"><i style={{ width: `${Math.max(0, Math.min(100, Number(progress?.percent || 0)))}%` }} /></span>
              <div className="merge-loading-steps">
                {steps.map((step, index) => (
                  <span key={step} className={index < currentStep ? 'is-done' : index === currentStep ? 'is-active' : ''}>
                    {index < currentStep ? <CheckCircle2 size={12} /> : index === currentStep ? <Loader2 size={12} className="km-spin" /> : null}
                    {step}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ) : !preview ? (
          <div className="merge-empty"><GitMerge size={54} /><span>暂无合并预览数据</span></div>
        ) : (
          <div className="merge-content">
            <aside className="merge-summary">
              <section><span>来源路径</span><p>{getConflictSourcePath(conflict)}</p></section>
              <section><span>{isRemoteTarget ? '远程仓库' : '现有目录'}路径</span><p>{getExistingConflictPath(conflict)}</p></section>
              <section>
                <span>当前决策</span>
                <b>取新包 {decisionSummary.useNew}</b>
                <b>取库存 {decisionSummary.useOld}</b>
                <b>删除 {decisionSummary.delete}</b>
              </section>
            </aside>
            <div className="merge-table-wrap">
              <table className="merge-table">
                <thead><tr><th></th><th>文件 / 路径</th><th>{isRemoteTarget ? '远程仓库' : '现有目录'}</th><th>新包</th><th>决策</th></tr></thead>
                <tbody>
                  {rows.map(row => {
                    const status = displayStatusInfo(row)
                    const Icon = row.type === 'dir' ? Folder : FileIcon
                    return (
                      <tr key={row.node_key} data-tone={status.key.replace(/_/g, '-')}>
                        <td><i>{statusGlyph(row)}</i></td>
                        <td>
                          <div className="merge-file-cell" style={{ paddingLeft: row._depth * 16 }}>
                            {row.type === 'dir' && row._hasChildren ? (
                              <button type="button" onClick={() => setCollapsed(value => {
                                const next = new Set(value)
                                if (next.has(row.relative_path)) next.delete(row.relative_path)
                                else next.add(row.relative_path)
                                return next
                              })}>{row._collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}</button>
                            ) : <span />}
                            <Icon size={14} />
                            <strong>{row.name}</strong>
                            {pathTail(row.relative_path) ? <em>{pathTail(row.relative_path)}</em> : null}
                            <b>{status.label}</b>
                          </div>
                          {status.note ? <p>{status.note}</p> : null}
                        </td>
                        <td>{row.old_path ? <><strong>{sidePrimary(row, 'old')}</strong><span>{sideTime(row, 'old')}</span></> : <em>-</em>}</td>
                        <td>{row.new_path ? <><strong>{sidePrimary(row, 'new')}</strong><span>{sideTime(row, 'new')}</span></> : <em>-</em>}</td>
                        <td>
                          {row.type === 'file' ? (
                            <div className="merge-decision-seg">
                              {decisionOptions(row).map(option => (
                                <button
                                  type="button"
                                  key={option.value}
                                  title={option.label}
                                  className={decisionFor(row, decisions, preview) === option.value ? 'is-active' : ''}
                                  data-decision={option.value}
                                  disabled={submitting}
                                  onClick={() => updateDecision(row, option.value)}
                                >{option.short}</button>
                              ))}
                            </div>
                          ) : <em>自动</em>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <footer className="merge-workbench-foot">
          <span>{isRemoteTarget ? `合并结果将上传至 ${conflict?.context?.existing?.library_name || '远程库存'}` : ''}</span>
          <Button onClick={onClose} disabled={submitting}>关闭</Button>
          <Button variant="primary" disabled={!preview || loading} loading={submitting} onClick={onSubmit}>
            {submitting ? null : <GitMerge size={15} />}
            {isRemoteTarget ? '上传并提交合并结果' : '生成并提交合并结果'}
          </Button>
        </footer>
      </section>
    </div>
  )
}
