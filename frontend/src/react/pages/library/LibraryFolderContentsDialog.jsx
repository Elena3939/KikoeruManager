import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, ChevronRight, RefreshCcw, Search, Trash2 } from 'lucide-react'
import { libraryApi } from '../../../api'
import { Button, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { showSystemConfirm } from '../../stores/systemPromptStore'
import { formatBytes, formatDateTime } from '../../utils/format'
import { LibraryFileIcon } from './LibraryFileIcon'
import { isDirectory, itemName, normalizePath } from './libraryUtils'

export function LibraryFolderContentsDialog({ libraryId, folderPath, folderName, onClose, onMutated }) {
  const [items, setItems] = useState([])
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [expanded, setExpanded] = useState(new Set())

  const tree = useMemo(() => buildFolderTree(items, folderPath), [items, folderPath])
  const nodeMap = useMemo(() => {
    const map = new Map()
    walkTree(tree, node => map.set(node.id, node))
    return map
  }, [tree])
  const filteredTree = useMemo(() => filterFolderTree(tree, keyword), [tree, keyword])
  const visibleRows = useMemo(() => flattenFolderTree(filteredTree, expanded), [filteredTree, expanded])
  const selectedRows = useMemo(() => [...selected].map(id => nodeMap.get(id)).filter(Boolean), [selected, nodeMap])
  const selectedDeleteRoots = useMemo(() => reduceDeleteRoots(selectedRows), [selectedRows])
  const selectedSize = useMemo(() => selectedDeleteRoots.reduce((sum, row) => sum + Number(row?.size || 0), 0), [selectedDeleteRoots])
  const allVisibleIds = useMemo(() => {
    const ids = []
    walkTree(filteredTree, node => ids.push(node.id))
    return ids
  }, [filteredTree])
  const selectionState = getSelectionState(filteredTree, selected)
  const allDirectoryIds = useMemo(() => {
    const ids = []
    walkTree(filteredTree, node => {
      if (node.type === 'dir') ids.push(node.id)
    })
    return ids
  }, [filteredTree])
  const allExpanded = allDirectoryIds.length > 0 && allDirectoryIds.every(id => expanded.has(id))

  async function reload() {
    if (!folderPath || !libraryId) return
    setLoading(true)
    try {
      const data = await libraryApi.browserFolderContents(libraryId, folderPath)
      const nextItems = Array.isArray(data?.items) ? data.items : []
      setItems(nextItems)
      setInfo({
        folderName: data?.folder_name || folderName || itemName({ path: folderPath }),
        folderPath: data?.folder_path || folderPath,
        totalFiles: Number(data?.total_files || nextItems.length || 0),
        totalSize: nextItems.reduce((sum, item) => sum + Number(item?.size || 0), 0)
      })
      const nextTree = buildFolderTree(nextItems, folderPath)
      const nextIds = new Set()
      const nextDirs = new Set()
      walkTree(nextTree, node => {
        nextIds.add(node.id)
        if (node.type === 'dir') nextDirs.add(node.id)
      })
      setSelected(prev => new Set([...prev].filter(id => nextIds.has(id))))
      setExpanded(prev => prev.size ? new Set([...prev].filter(id => nextDirs.has(id))) : nextDirs)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [libraryId, folderPath])

  function toggleNode(node, checked) {
    const targetIds = collectNodeIds(node)
    setSelected(prev => {
      const next = new Set(prev)
      targetIds.forEach(id => {
        if (checked) next.add(id)
        else next.delete(id)
      })
      return next
    })
  }

  function toggleAllVisible() {
    const shouldSelect = selectionState !== 'all'
    setSelected(prev => {
      const next = new Set(prev)
      allVisibleIds.forEach(id => {
        if (shouldSelect) next.add(id)
        else next.delete(id)
      })
      return next
    })
  }

  function toggleExpand(node) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(node.id)) next.delete(node.id)
      else next.add(node.id)
      return next
    })
  }

  function toggleExpandAll() {
    setExpanded(allExpanded ? new Set() : new Set(allDirectoryIds))
  }

  async function deleteSelected() {
    const paths = selectedDeleteRoots.map(row => row.path).filter(Boolean)
    if (!paths.length) return
    setDeleting(true)
    try {
      const preview = paths.length === 1
        ? await libraryApi.browserDelete(libraryId, paths[0], false)
        : await libraryApi.browserBatchDelete(libraryId, paths, false)
      const size = Number(preview?.total_size ?? preview?.size ?? selectedSize)
      const counts = countDeleteRows(selectedDeleteRoots)
      const fileCount = Number(preview?.total_file_count ?? preview?.file_count ?? counts.files)
      const folderCount = Number(preview?.total_folder_count ?? preview?.folder_count ?? counts.dirs)
      await showSystemConfirm({
        title: paths.length === 1 ? '删除确认' : '批量删除确认',
        message: [`已选择 ${paths.length} 项待删除`, `文件：${fileCount} 个`, `文件夹：${folderCount} 个`, `预计释放：${formatBytes(size)}`].join('\n'),
        currentValue: paths.join('\n'),
        inputType: 'textarea',
        confirmText: '确定删除',
        tone: 'danger',
        width: 560
      })
      if (paths.length === 1) await libraryApi.browserDelete(libraryId, paths[0], true)
      else await libraryApi.browserBatchDelete(libraryId, paths, true)
      setSelected(new Set())
      await reload()
      await onMutated?.({ deletedBytes: size, deletedFolderCount: folderCount })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Modal
      title={`文件管理 · ${info?.folderName || folderName || itemName({ path: folderPath })}`}
      width={1080}
      onClose={onClose}
      footer={
        <>
          <Button onClick={reload} disabled={loading}><RefreshCcw size={15} />刷新</Button>
          <Button variant="danger" loading={deleting} disabled={!selectedDeleteRoots.length} onClick={deleteSelected}><Trash2 size={15} />删除选中</Button>
          <Button onClick={onClose}>关闭</Button>
        </>
      }
    >
      <div className="library-folder-dialog">
        <div className="library-folder-summary">
          <span>{info?.folderPath || folderPath}</span>
          <em>{info?.totalFiles || items.length} 项 · {formatBytes(info?.totalSize || 0)}</em>
        </div>

        <div className="library-folder-toolbar">
          <label className="library-folder-search">
            <Search size={15} />
            <TextInput value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="搜索文件名或路径..." />
          </label>
          <Button size="sm" disabled={loading || !tree.length} onClick={toggleExpandAll}>
            {allExpanded ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
            {allExpanded ? '全部收起' : '展开全部'}
          </Button>
          <Button size="sm" disabled={loading || !allVisibleIds.length} onClick={toggleAllVisible}>
            <Check size={15} />
            {selectionState === 'all' ? '取消全选' : '全选可见'}
          </Button>
        </div>

        {selectedDeleteRoots.length ? (
          <div className="library-folder-selection">
            已选 <b>{selectedDeleteRoots.length}</b> 个删除根，预计释放 <b>{formatBytes(selectedSize)}</b>
          </div>
        ) : null}

        <div className="library-folder-list">
          <div className="library-folder-tree-head">
            <span>文件名</span>
            <span>大小</span>
            <span>修改时间</span>
          </div>
          {loading ? <LoadingState label="正在读取目录..." /> : null}
          {!loading && !visibleRows.length ? <div className="km-empty"><strong>{keyword ? '没有匹配项' : '目录为空'}</strong></div> : null}
          {!loading && visibleRows.map(row => (
            <FolderTreeRow
              key={row.id}
              row={row}
              selected={selected}
              expanded={expanded}
              onToggleNode={toggleNode}
              onToggleExpand={toggleExpand}
            />
          ))}
        </div>
      </div>
    </Modal>
  )
}

function FolderTreeRow({ row, selected, expanded, onToggleNode, onToggleExpand }) {
  const checked = isNodeFullySelected(row, selected)
  const partial = !checked && isNodePartiallySelected(row, selected)
  const open = expanded.has(row.id)

  return (
    <div className={`library-folder-row ${checked || partial ? 'is-selected' : ''}`} style={{ '--folder-depth': row.depth }}>
      <div className="library-folder-name-cell">
        {row.type === 'dir' ? (
          <button type="button" className="library-folder-expander" onClick={() => onToggleExpand(row)}>
            {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        ) : <span className="library-folder-expander-spacer" />}
        <button
          type="button"
          className={`library-folder-check ${checked ? 'is-checked' : partial ? 'is-partial' : ''}`}
          onClick={() => onToggleNode(row, !(checked || partial))}
          aria-label={`选择 ${row.name}`}
        >
          {checked ? <Check size={12} /> : partial ? <span /> : null}
        </button>
        <LibraryFileIcon item={{ ...row, is_directory: row.type === 'dir' }} />
        <span title={row.relativePath || row.name}>{row.name}</span>
      </div>
      <em>{formatBytes(row.size)}</em>
      <time>{formatDateTime(row.modified)}</time>
    </div>
  )
}

function buildFolderTree(items, folderPath) {
  const rootPath = normalizePath(folderPath)
  const roots = []
  const dirMap = new Map()

  function ensureDir(parts, absolutePath) {
    let siblings = roots
    let parentPath = rootPath
    let node = null
    parts.forEach((part, index) => {
      parentPath = normalizePath(parentPath ? `${parentPath}/${part}` : part)
      const id = `dir:${parentPath}`
      node = dirMap.get(id)
      if (!node) {
        node = {
          id,
          type: 'dir',
          name: part,
          path: parentPath || absolutePath,
          relativePath: parts.slice(0, index + 1).join('/'),
          size: 0,
          modified: '',
          children: [],
          depth: index
        }
        dirMap.set(id, node)
        siblings.push(node)
      }
      siblings = node.children
    })
    return node
  }

  for (const item of items || []) {
    const path = resolveItemPath(folderPath, item)
    const relativePath = normalizeRelativePath(item?.relative_path || relativeFromBase(rootPath, path) || item?.name || itemName({ path }))
    const parts = relativePath.split('/').filter(Boolean)
    if (!parts.length) continue
    const parentParts = parts.slice(0, -1)
    const siblings = parentParts.length ? ensureDir(parentParts).children : roots
    const type = isDirectory(item) ? 'dir' : 'file'
    const id = `${type}:${path}`
    const existing = type === 'dir' ? dirMap.get(id) : null
    const node = existing || {
      id,
      type,
      name: parts.at(-1),
      path,
      relativePath,
      size: Number(item?.size || 0),
      modified: item?.modified || item?.mtime || item?.modified_time || item?.updated_at || '',
      children: [],
      depth: parentParts.length
    }
    if (existing) {
      existing.size = Number(item?.size || existing.size || 0)
      existing.modified = item?.modified || item?.mtime || item?.modified_time || item?.updated_at || existing.modified || ''
    } else {
      if (type === 'dir') dirMap.set(id, node)
      siblings.push(node)
    }
  }

  sortFolderNodes(roots)
  return roots
}

function sortFolderNodes(nodes) {
  nodes.sort((left, right) => {
    if (left.type !== right.type) return left.type === 'dir' ? -1 : 1
    return left.name.localeCompare(right.name, 'zh-CN', { numeric: true, sensitivity: 'base' })
  })
  nodes.forEach(node => sortFolderNodes(node.children || []))
}

function filterFolderTree(nodes, keyword) {
  const query = String(keyword || '').trim().toLowerCase()
  if (!query) return nodes
  const result = []
  for (const node of nodes) {
    const children = filterFolderTree(node.children || [], query)
    const matched = `${node.name} ${node.relativePath}`.toLowerCase().includes(query)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenFolderTree(nodes, expanded, depth = 0) {
  const rows = []
  for (const node of nodes) {
    const next = { ...node, depth }
    rows.push(next)
    if (node.type === 'dir' && expanded.has(node.id)) rows.push(...flattenFolderTree(node.children || [], expanded, depth + 1))
  }
  return rows
}

function walkTree(nodes, visitor) {
  for (const node of nodes || []) {
    visitor(node)
    walkTree(node.children || [], visitor)
  }
}

function collectNodeIds(node) {
  const ids = []
  walkTree([node], item => ids.push(item.id))
  return ids
}

function isNodeFullySelected(node, selected) {
  const ids = collectNodeIds(node)
  return ids.length > 0 && ids.every(id => selected.has(id))
}

function isNodePartiallySelected(node, selected) {
  return collectNodeIds(node).some(id => selected.has(id))
}

function getSelectionState(nodes, selected) {
  const ids = []
  walkTree(nodes, node => ids.push(node.id))
  if (!ids.length) return 'none'
  if (ids.every(id => selected.has(id))) return 'all'
  if (ids.some(id => selected.has(id))) return 'partial'
  return 'none'
}

function reduceDeleteRoots(rows) {
  const sorted = rows.slice().sort((left, right) => left.path.length - right.path.length)
  const roots = []
  for (const row of sorted) {
    const normalized = normalizePath(row.path)
    if (!normalized) continue
    if (roots.some(root => isDescendantPath(normalized, normalizePath(root.path)))) continue
    roots.push(row)
  }
  return roots
}

function countDeleteRows(rows) {
  const result = { dirs: 0, files: 0 }
  rows.forEach(row => {
    walkTree([row], node => {
      if (node.type === 'dir') result.dirs += 1
      else result.files += 1
    })
  })
  return result
}

function isDescendantPath(path, parent) {
  return path !== parent && path.startsWith(`${parent}/`)
}

function resolveItemPath(folderPath, item) {
  const direct = String(item?.path || '').trim()
  if (direct) return normalizePath(direct)
  const relative = String(item?.relative_path || item?.name || '').replace(/^[/\\]+/, '')
  return normalizePath(`${folderPath}/${relative}`)
}

function relativeFromBase(base, path) {
  const normalizedBase = normalizePath(base)
  const normalizedPath = normalizePath(path)
  if (normalizedBase && normalizedPath.startsWith(`${normalizedBase}/`)) return normalizedPath.slice(normalizedBase.length + 1)
  return normalizedPath
}

function normalizeRelativePath(value) {
  return normalizePath(String(value || '').replace(/^[/\\]+/, ''))
}
