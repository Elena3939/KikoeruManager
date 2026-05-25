import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  File,
  Folder,
  FolderOpen,
  HardDrive,
  Loader2,
  UploadCloud,
  X
} from 'lucide-react'
import { libraryApi } from '../../../api'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { formatBytes, normalizeListPayload } from '../../utils/format'
import { buildBreadcrumb, classifyLibraryEntryKind, isDirectory, itemName, normalizePath, parentPath } from './libraryUtils'

const rowHeight = 40
const virtualThreshold = 180

export function LibraryLocalUploadDialog({
  libraries,
  sourceRows,
  sourceLibraryId,
  sourceLibraryName,
  initialTargetLibraryId,
  initialTargetSubdir = '',
  submitting,
  onClose,
  onSubmit
}) {
  const remoteLibraries = useMemo(
    () => (libraries || []).filter(item => item?.type === 'synology_filestation' && item?.enabled !== false),
    [libraries]
  )
  const [targetLibraryId, setTargetLibraryId] = useState(initialTargetLibraryId || remoteLibraries[0]?.id || '')
  const [targetSubdir, setTargetSubdir] = useState(initialTargetSubdir || '')
  const [previewGroups, setPreviewGroups] = useState([])
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [storageInfo, setStorageInfo] = useState(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [version, setVersion] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(420)
  const chipRailRef = useRef(null)
  const chipDragRef = useRef({ active: false, pointerId: null, startX: 0, startScrollLeft: 0, moved: false })
  const uploadRows = useMemo(() => (sourceRows || []).filter(row => row?.path), [sourceRows])
  const selectedTargetLibrary = remoteLibraries.find(item => String(item.id) === String(targetLibraryId)) || null

  const flatRows = useMemo(() => {
    version
    const rows = []
    previewGroups.forEach(group => {
      rows.push({ id: `${group.id}:header`, kind: 'group', group })
      if (group.rootExpanded !== false) {
        group.flatRows.forEach(row => rows.push({ id: row.id, kind: 'row', group, row }))
      }
    })
    return rows
  }, [previewGroups, version])
  const useVirtual = flatRows.length > virtualThreshold
  const virtualRange = useMemo(() => {
    if (!useVirtual) return { start: 0, end: flatRows.length }
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 12)
    const count = Math.ceil(Math.max(viewportHeight, 180) / rowHeight) + 24
    return { start, end: Math.min(flatRows.length, start + count) }
  }, [flatRows.length, scrollTop, viewportHeight, useVirtual])
  const visibleRows = flatRows.slice(virtualRange.start, virtualRange.end)
  const topPadding = useVirtual ? virtualRange.start * rowHeight : 0
  const bottomPadding = useVirtual ? Math.max(0, (flatRows.length - virtualRange.end) * rowHeight) : 0

  const typeChips = useMemo(() => {
    version
    const map = new Map()
    previewGroups.forEach(group => {
      Object.values(group.typeStats || {}).forEach(stat => {
        const current = map.get(stat.key) || { key: stat.key, label: stat.label, total: 0, selected: 0 }
        current.total += stat.total
        current.selected += stat.selected
        map.set(stat.key, current)
      })
    })
    return [...map.values()]
      .map(item => ({ ...item, state: item.selected === 0 ? 'none' : item.selected === item.total ? 'all' : 'partial' }))
      .sort((left, right) => fileTypeOrder(left.key) - fileTypeOrder(right.key) || left.label.localeCompare(right.label, 'zh-CN'))
  }, [previewGroups, version])

  const selectedSummary = useMemo(() => {
    version
    return previewGroups.reduce((acc, group) => {
      acc.groupCount += isGroupAllSelected(group) || isGroupPartiallySelected(group) ? 1 : 0
      acc.fileCount += Number(group.selectedResourceCount || 0)
      acc.totalFileCount += Number(group.totalResourceCount || 0)
      acc.bytes += Number(group.selectedSizeBytes || 0)
      acc.totalBytes += Number(group.totalSizeBytes || 0)
      return acc
    }, { groupCount: 0, fileCount: 0, totalFileCount: 0, bytes: 0, totalBytes: 0 })
  }, [previewGroups, version])
  const groupSummary = useMemo(() => {
    version
    const partial = previewGroups.filter(isGroupPartiallySelected).length
    const all = previewGroups.filter(isGroupAllSelected).length
    return {
      all,
      partial,
      none: Math.max(0, previewGroups.length - all - partial)
    }
  }, [previewGroups, version])

  const allSelectionState = selectedSummary.fileCount === 0
    ? 'none'
    : selectedSummary.fileCount === selectedSummary.totalFileCount ? 'all' : 'partial'
  const allExpanded = previewGroups.length > 0 && previewGroups.every(group => group.rootExpanded !== false)
  const selectedPaths = useMemo(() => {
    version
    return normalizeSelectedPaths(previewGroups.flatMap(group => collectSubmitPaths(group)))
  }, [previewGroups, version])
  const targetRoot = useMemo(() => {
    const base = String(selectedTargetLibrary?.root_path || selectedTargetLibrary?.path || selectedTargetLibrary?.synology?.root_path || '').replace(/\\/g, '/').replace(/\/+$/, '')
    const subdir = normalizePath(targetSubdir).replace(/^\/+/, '')
    if (!base) return subdir
    return subdir ? `${base}/${subdir}`.replace(/\/+/g, '/') : base
  }, [selectedTargetLibrary, targetSubdir])
  const finalPathPreview = useMemo(() => {
    if (!targetRoot) return ''
    const groups = previewGroups.filter(group => isGroupAllSelected(group) || isGroupPartiallySelected(group))
    if (groups.length === 1) return `${targetRoot}/${groups[0].name}`.replace(/\/+/g, '/')
    if (groups.length > 1) return `${targetRoot}/{所选目录名}`.replace(/\/+/g, '/')
    return targetRoot
  }, [targetRoot, previewGroups, version])
  const freeBytes = Number(storageInfo?.free_size_bytes || 0) || Number(selectedTargetLibrary?.health?.free_space_gb || 0) * 1024 ** 3

  useEffect(() => {
    setTargetLibraryId(initialTargetLibraryId || remoteLibraries[0]?.id || '')
  }, [initialTargetLibraryId, remoteLibraries[0]?.id])

  useEffect(() => {
    setTargetSubdir(initialTargetSubdir || '')
  }, [initialTargetSubdir])

  useEffect(() => {
    loadPreviewGroups()
  }, [uploadRows.map(row => row.path).join('|'), sourceLibraryId])

  useEffect(() => {
    loadStorageInfo()
  }, [targetLibraryId])

  async function loadStorageInfo() {
    setStorageInfo(null)
    if (!targetLibraryId) return
    const data = await libraryApi.getStorageInfo(targetLibraryId).catch(() => null)
    setStorageInfo(data)
  }

  async function loadPreviewGroups() {
    if (!uploadRows.length) {
      setPreviewGroups([])
      bump()
      return
    }
    setLoadingPreview(true)
    try {
      const groups = await Promise.all(uploadRows.map(async (row, index) => {
        const path = normalizePath(row.path)
        const name = itemName(row)
        const groupId = `group:${index}:${path}`
        if (!isDirectory(row)) {
          return createPreviewGroupFromResources({
            id: groupId,
            name,
            path,
            isFile: true,
            resources: [{
              ...row,
              name,
              path,
              relative_path: name,
              selected: true,
              type_key: getPreviewFileTypeKey(row),
              type_label: getPreviewFileTypeLabel(row)
            }]
          })
        }
        const data = sourceLibraryId
          ? await libraryApi.browserFolderContents(sourceLibraryId, path)
          : await libraryApi.folderContents(path)
        const resources = normalizeListPayload(data).map(item => ({
          ...item,
          selected: true,
          type_key: getPreviewFileTypeKey(item),
          type_label: getPreviewFileTypeLabel(item)
        }))
        return createPreviewGroupFromResources({ id: groupId, name, path, isFile: false, resources })
      }))
      setPreviewGroups(groups)
      setScrollTop(0)
      bump()
    } finally {
      setLoadingPreview(false)
    }
  }

  function bump() {
    setVersion(value => value + 1)
  }

  function updateGroup(groupId, updater) {
    setPreviewGroups(current => current.map(group => {
      if (group.id !== groupId) return group
      updater(group)
      return { ...group }
    }))
    bump()
  }

  function toggleGroupExpand(group) {
    updateGroup(group.id, draft => {
      draft.rootExpanded = draft.rootExpanded === false
    })
  }

  function toggleNodeExpand(group, row) {
    if (row?.type !== 'dir') return
    updateGroup(group.id, draft => {
      const next = new Set(draft.expandedIds)
      next.has(row.id) ? next.delete(row.id) : next.add(row.id)
      draft.expandedIds = next
      refreshGroupFlatRows(draft)
    })
  }

  function toggleGroupSelection(group) {
    updateGroup(group.id, draft => {
      const nextSelected = !isGroupAllSelected(draft)
      draft.resources.forEach(item => { item.selected = nextSelected })
      Object.values(draft.typeStats || {}).forEach(stat => { stat.selected = nextSelected ? stat.total : 0 })
      refreshPlanTree(draft)
    })
  }

  function toggleNodeSelection(group, row) {
    updateGroup(group.id, draft => {
      const draftRow = draft.nodeById.get(row.id)
      updateResourceSelection(draft, draftRow, isTreeNodePartiallySelected(draftRow) ? true : !isTreeNodeChecked(draftRow))
    })
  }

  function toggleAllSelection() {
    const nextSelected = allSelectionState !== 'all'
    setPreviewGroups(current => current.map(group => {
      group.resources.forEach(item => { item.selected = nextSelected })
      Object.values(group.typeStats || {}).forEach(stat => { stat.selected = nextSelected ? stat.total : 0 })
      refreshPlanTree(group)
      return { ...group }
    }))
    bump()
  }

  function toggleFileType(chip) {
    const key = String(chip?.key || '')
    if (!key) return
    const nextSelected = chip.state !== 'all'
    setPreviewGroups(current => current.map(group => {
      let changed = false
      group.resources.forEach(item => {
        if ((item.type_key || getPreviewFileTypeKey(item)) === key) {
          item.selected = nextSelected
          changed = true
        }
      })
      if (group.typeStats?.[key]) group.typeStats[key].selected = nextSelected ? group.typeStats[key].total : 0
      if (changed) refreshPlanTree(group)
      return { ...group }
    }))
    bump()
  }

  function toggleExpandAll() {
    const nextState = !allExpanded
    setPreviewGroups(current => current.map(group => {
      group.rootExpanded = nextState
      group.expandedIds = nextState ? new Set(collectAllDirIds(group.tree)) : new Set()
      refreshGroupFlatRows(group)
      return { ...group }
    }))
    bump()
  }

  function handleTreeScroll(event) {
    setScrollTop(Number(event.currentTarget.scrollTop || 0))
    setViewportHeight(Math.max(Number(event.currentTarget.clientHeight || 0), 180))
  }

  function handleChipPointerDown(event) {
    const target = chipRailRef.current
    if (!target) return
    chipDragRef.current = {
      active: true,
      pointerId: event.pointerId,
      startX: event.clientX,
      startScrollLeft: target.scrollLeft,
      moved: false
    }
    target.setPointerCapture?.(event.pointerId)
  }

  function handleChipPointerMove(event) {
    const state = chipDragRef.current
    const target = chipRailRef.current
    if (!state.active || !target) return
    const delta = event.clientX - state.startX
    if (Math.abs(delta) > 3) state.moved = true
    target.scrollLeft = state.startScrollLeft - delta
  }

  function handleChipPointerUp(event) {
    chipRailRef.current?.releasePointerCapture?.(event.pointerId)
    window.setTimeout(() => { chipDragRef.current.moved = false }, 0)
    chipDragRef.current.active = false
  }

  function submit() {
    if (!targetLibraryId || !selectedPaths.length) return
    onSubmit({
      selectedPaths,
      targetLibraryId,
      targetSubdir
    })
  }

  return (
    <Modal
      title="上传到服务器"
      width={1180}
      onClose={onClose}
      footer={
        <>
          <span className="library-upload-footer-summary">
            已选 {selectedSummary.groupCount} 组 / {selectedSummary.fileCount} 文件，共 {formatBytes(selectedSummary.bytes)}
          </span>
          <Button onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={!targetLibraryId || !selectedPaths.length || loadingPreview}
            onClick={submit}
          >
            <UploadCloud size={15} />开始上传
          </Button>
        </>
      }
    >
      <div className="library-upload-dialog library-upload-preview-dialog">
        {!remoteLibraries.length ? <div className="km-empty"><strong>没有可用的服务器库存</strong></div> : null}
        <section className="library-upload-preview-settings">
          <div>
            <label>
              <span>目标库存</span>
              <AppDropdown
                value={targetLibraryId}
                onChange={setTargetLibraryId}
                options={remoteLibraries.map(item => ({ value: String(item.id), label: item.name || String(item.id) }))}
                width={260}
              />
            </label>
            <label>
              <span>指定目录</span>
              <button type="button" className="library-upload-picker-button" disabled={!targetLibraryId} onClick={() => setPickerOpen(true)}>
                <FolderOpen size={15} />
                <b>{targetSubdir || '库存根目录'}</b>
                <ChevronRight size={15} />
              </button>
              {targetSubdir ? <button type="button" className="library-upload-clear-dir" onClick={() => setTargetSubdir('')}><X size={13} />清空</button> : null}
            </label>
          </div>
          <div className="library-upload-preview-paths">
            <span><HardDrive size={13} />来源：{sourceLibraryName || sourceLibraryId || '本地库存'}</span>
            <span>目标目录：<b>{targetRoot || '-'}</b></span>
            <span>最终位置：<b>{finalPathPreview || '-'}</b></span>
            <span>剩余空间：<b>{freeBytes > 0 ? formatBytes(freeBytes) : '暂不可用'}</b>{freeBytes > 0 ? ` / 上传后约 ${formatBytes(Math.max(0, freeBytes - selectedSummary.bytes))}` : ''}</span>
          </div>
        </section>

        <section className="library-upload-preview-summary-grid">
          <div><span>已选分组</span><b>{selectedSummary.groupCount}</b><small>全选 {groupSummary.all} / 部分 {groupSummary.partial}</small></div>
          <div><span>已选文件</span><b>{selectedSummary.fileCount}</b><small>共 {selectedSummary.totalFileCount} 个文件</small></div>
          <div><span>上传体积</span><b>{formatBytes(selectedSummary.bytes)}</b><small>总量 {formatBytes(selectedSummary.totalBytes)}</small></div>
          <div><span>目标剩余</span><b>{freeBytes > 0 ? formatBytes(Math.max(0, freeBytes - selectedSummary.bytes)) : '暂不可用'}</b><small>{freeBytes > 0 ? `当前 ${formatBytes(freeBytes)}` : '等待库存上报'}</small></div>
        </section>

        <div className="library-upload-chip-row">
          <div
            ref={chipRailRef}
            className="library-upload-chip-rail"
            onPointerDown={handleChipPointerDown}
            onPointerMove={handleChipPointerMove}
            onPointerUp={handleChipPointerUp}
            onPointerCancel={handleChipPointerUp}
            onWheel={event => { event.currentTarget.scrollLeft += event.deltaY || event.deltaX }}
            onClickCapture={event => { if (chipDragRef.current.moved) event.stopPropagation() }}
          >
            <button type="button" className={selectionChipClass(allSelectionState)} onClick={toggleAllSelection}>
              全部 {selectedSummary.fileCount}/{selectedSummary.totalFileCount}
            </button>
            {typeChips.map(chip => (
              <button type="button" key={chip.key} className={selectionChipClass(chip.state)} onClick={() => toggleFileType(chip)}>
                {chip.label} {chip.selected}/{chip.total}
              </button>
            ))}
          </div>
          <Button size="sm" onClick={toggleExpandAll}>
            {allExpanded ? <ChevronsUp size={14} /> : <ChevronsDown size={14} />}
            {allExpanded ? '全部收起' : '全部展开'}
          </Button>
        </div>

        <section className="library-upload-preview-tree" onScroll={handleTreeScroll}>
          {loadingPreview ? <LoadingState label="正在生成上传预览树..." /> : null}
          {!loadingPreview && !previewGroups.length ? <div className="km-empty"><strong>当前没有可上传的目录</strong></div> : null}
          {!loadingPreview && topPadding ? <div style={{ height: topPadding }} /> : null}
          {!loadingPreview && visibleRows.map(item => item.kind === 'group' ? (
            <UploadGroupRow key={item.id} group={item.group} onToggleExpand={toggleGroupExpand} onToggleSelection={toggleGroupSelection} />
          ) : (
            <UploadTreeRow key={item.id} group={item.group} row={item.row} onToggleExpand={toggleNodeExpand} onToggleSelection={toggleNodeSelection} />
          ))}
          {!loadingPreview && bottomPadding ? <div style={{ height: bottomPadding }} /> : null}
        </section>

        {pickerOpen ? (
          <TargetDirectoryPicker
            library={selectedTargetLibrary}
            initialPath={targetSubdir}
            onSelect={path => { setTargetSubdir(path); setPickerOpen(false) }}
            onClose={() => setPickerOpen(false)}
          />
        ) : null}
      </div>
    </Modal>
  )
}

function UploadGroupRow({ group, onToggleExpand, onToggleSelection }) {
  const selectedState = isGroupAllSelected(group) ? 'all' : isGroupPartiallySelected(group) ? 'partial' : 'none'
  return (
    <div className={`library-upload-tree-row is-group ${selectedState !== 'none' ? 'is-selected' : ''}`}>
      <button type="button" className="library-upload-tree-expander" onClick={() => onToggleExpand(group)}>
        <ChevronRight size={16} className={group.rootExpanded !== false ? 'is-open' : ''} />
      </button>
      <button type="button" className={`library-upload-tree-check is-${selectedState}`} onClick={() => onToggleSelection(group)}>
        {selectedState === 'all' ? <Check size={13} /> : selectedState === 'partial' ? <span /> : null}
      </button>
      {group.isFile ? <File size={17} /> : <Folder size={17} />}
      <strong>{group.name}</strong>
      <small>{group.path}</small>
      <em>{formatBytes(group.selectedSizeBytes)} / {formatBytes(group.totalSizeBytes)}</em>
    </div>
  )
}

function UploadTreeRow({ group, row, onToggleExpand, onToggleSelection }) {
  const selectedState = isTreeNodeChecked(row) ? 'all' : isTreeNodePartiallySelected(row) ? 'partial' : 'none'
  return (
    <div className={`library-upload-tree-row ${selectedState !== 'none' ? 'is-selected' : ''}`} style={{ paddingLeft: 18 + row.depth * 18 }}>
      {row.type === 'dir' ? (
        <button type="button" className="library-upload-tree-expander" onClick={() => onToggleExpand(group, row)}>
          <ChevronRight size={16} className={group.expandedIds.has(row.id) ? 'is-open' : ''} />
        </button>
      ) : <i className="library-upload-tree-spacer" />}
      <button type="button" className={`library-upload-tree-check is-${selectedState}`} onClick={() => onToggleSelection(group, row)}>
        {selectedState === 'all' ? <Check size={13} /> : selectedState === 'partial' ? <span /> : null}
      </button>
      {row.type === 'dir' ? <Folder size={16} /> : <File size={16} />}
      <strong>{row.name}</strong>
      <small>{row.relative_path || row.resolved_path || ''}</small>
      <em>{formatBytes(row.selected_size_bytes || 0)} / {formatBytes(row.size_bytes || 0)}</em>
    </div>
  )
}

function TargetDirectoryPicker({ library, initialPath, onSelect, onClose }) {
  const [path, setPath] = useState(normalizePath(initialPath || ''))
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(false)
  const breadcrumbs = useMemo(() => buildBreadcrumb(path), [path])

  useEffect(() => {
    loadFolders(path)
  }, [library?.id, path])

  async function loadFolders(nextPath = path) {
    if (!library?.id) return
    setLoading(true)
    try {
      const data = await libraryApi.browserListFolders(library.id, nextPath || '', { includeFiles: false })
      setFolders(normalizeListPayload(data).filter(isDirectory))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="library-upload-picker-overlay">
      <section className="library-upload-picker-panel">
        <header>
          <strong>指定上传目录</strong>
          <button type="button" onClick={onClose}><X size={15} /></button>
        </header>
        <div className="library-upload-picker-breadcrumb">
          {breadcrumbs.map((crumb, index) => (
            <span key={crumb.path || 'root'}>
              {index > 0 ? <ChevronRight size={13} /> : null}
              <button type="button" className={index === breadcrumbs.length - 1 ? 'is-current' : ''} onClick={() => setPath(crumb.path)}>{crumb.label}</button>
            </span>
          ))}
        </div>
        <div className="library-upload-picker-tools">
          <Button size="xs" disabled={!path} onClick={() => setPath(parentPath(path))}>上级</Button>
          <Button size="xs" onClick={() => loadFolders(path)}>刷新</Button>
          <Button size="xs" variant="primary" onClick={() => onSelect(path)}>选择此目录</Button>
        </div>
        <div className="library-upload-picker-list">
          {loading ? <LoadingState label="正在读取目录..." /> : null}
          {!loading && !folders.length ? <div className="km-empty"><strong>没有子目录</strong></div> : null}
          {!loading && folders.map(folder => (
            <button type="button" key={folder.path || folder.name} onClick={() => setPath(normalizePath(folder.path || folder.name))}>
              <FolderOpen size={15} />
              <span>{itemName(folder)}</span>
              <small>{folder.path}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}

function createPreviewGroupFromResources({ id, name, path, isFile, resources }) {
  const tree = isFile
    ? [{
      id: `${id}:file:${path}`,
      name,
      type: 'file',
      resource: resources[0],
      size_bytes: Number(resources[0]?.size || 0),
      selected_size_bytes: Number(resources[0]?.size || 0),
      leaf_count: 1,
      selected_count: 1,
      resolved_path: path
    }]
    : buildPreviewTree(resources, path, id)
  const group = {
    id,
    name,
    path,
    isFile,
    resources,
    rootExpanded: !isFile,
    tree,
    expandedIds: new Set(collectAllDirIds(tree)),
    nodeById: new Map(),
    typeStats: {},
    flatRows: []
  }
  initializeGroupTree(group)
  return group
}

function buildPreviewTree(resources, basePath, groupId) {
  const root = []
  const dirMap = new Map()
  for (const item of resources) {
    const parts = String(item.relative_path || item.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let relative = ''
    for (let index = 0; index < parts.length - 1; index += 1) {
      relative = relative ? `${relative}/${parts[index]}` : parts[index]
      const key = `${groupId}:dir:${relative}`
      if (!dirMap.has(key)) {
        const node = {
          id: key,
          name: parts[index],
          type: 'dir',
          relative_path: relative,
          resolved_path: joinPath(basePath, relative),
          parentId: index === 0 ? '' : `${groupId}:dir:${parts.slice(0, index).join('/')}`,
          children: [],
          size_bytes: 0,
          selected_size_bytes: 0,
          leaf_count: 0,
          selected_count: 0
        }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({
      id: `${groupId}:file:${item.path || item.relative_path || item.name}`,
      name: parts.at(-1),
      type: 'file',
      resource: item,
      relative_path: item.relative_path || item.name,
      resolved_path: item.path,
      parentId: parts.length > 1 ? `${groupId}:dir:${parts.slice(0, -1).join('/')}` : '',
      size_bytes: Number(item.size || 0),
      selected_size_bytes: item.selected ? Number(item.size || 0) : 0,
      leaf_count: 1,
      selected_count: item.selected ? 1 : 0
    })
  }
  return root
}

function initializeGroupTree(group) {
  group.nodeById = new Map()
  group.typeStats = {}
  group.resources.forEach(resource => {
    const key = resource.type_key || getPreviewFileTypeKey(resource)
    const label = resource.type_label || getPreviewFileTypeLabel(resource)
    resource.type_key = key
    resource.type_label = label
    const stat = group.typeStats[key] || { key, label, total: 0, selected: 0 }
    stat.total += 1
    if (resource.selected) stat.selected += 1
    group.typeStats[key] = stat
  })
  recomputeTreeSelection(group)
  refreshGroupFlatRows(group)
}

function recomputeTreeSelection(group) {
  const walk = node => {
    group.nodeById.set(node.id, node)
    if (node.type === 'file') {
      const size = Number(node.resource?.size || node.size_bytes || 0)
      node.size_bytes = size
      node.leaf_count = 1
      node.selected_count = node.resource?.selected ? 1 : 0
      node.selected_size_bytes = node.resource?.selected ? size : 0
      if (node.resource) node.resource.node_id = node.id
      return { total: 1, selected: node.selected_count, size, selectedSize: node.selected_size_bytes }
    }
    const totals = (node.children || []).reduce((acc, child) => {
      const current = walk(child)
      acc.total += current.total
      acc.selected += current.selected
      acc.size += current.size
      acc.selectedSize += current.selectedSize
      return acc
    }, { total: 0, selected: 0, size: 0, selectedSize: 0 })
    node.leaf_count = totals.total
    node.selected_count = totals.selected
    node.size_bytes = totals.size
    node.selected_size_bytes = totals.selectedSize
    return totals
  }
  group.nodeById = new Map()
  const totals = (group.tree || []).reduce((acc, node) => {
    const current = walk(node)
    acc.total += current.total
    acc.selected += current.selected
    acc.size += current.size
    acc.selectedSize += current.selectedSize
    return acc
  }, { total: 0, selected: 0, size: 0, selectedSize: 0 })
  group.totalResourceCount = totals.total
  group.selectedResourceCount = totals.selected
  group.totalSizeBytes = totals.size
  group.selectedSizeBytes = totals.selectedSize
}

function refreshGroupFlatRows(group) {
  group.flatRows = flattenTree(group.tree || [], 0, group.expandedIds || new Set())
}

function refreshPlanTree(group) {
  recomputeTreeSelection(group)
  refreshGroupFlatRows(group)
}

function flattenTree(nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    node.depth = depth
    result.push(node)
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

function setSubtreeSelection(group, node, nextSelected) {
  if (!node) return { count: 0, size: 0 }
  if (node.type === 'file') {
    const wasSelected = Boolean(node.resource?.selected)
    if (wasSelected === nextSelected) return { count: 0, size: 0 }
    const size = Number(node.size_bytes || node.resource?.size || 0)
    node.resource.selected = nextSelected
    node.selected_count = nextSelected ? 1 : 0
    node.selected_size_bytes = nextSelected ? size : 0
    const stat = group.typeStats[node.resource.type_key]
    if (stat) stat.selected += nextSelected ? 1 : -1
    return { count: nextSelected ? 1 : -1, size: nextSelected ? size : -size }
  }
  const beforeCount = Number(node.selected_count || 0)
  const beforeSize = Number(node.selected_size_bytes || 0)
  ;(node.children || []).forEach(child => setSubtreeSelection(group, child, nextSelected))
  node.selected_count = nextSelected ? Number(node.leaf_count || 0) : 0
  node.selected_size_bytes = nextSelected ? Number(node.size_bytes || 0) : 0
  return { count: node.selected_count - beforeCount, size: node.selected_size_bytes - beforeSize }
}

function applySelectionDeltaToAncestors(group, node, delta) {
  let parentId = node?.parentId || ''
  while (parentId) {
    const parent = group.nodeById.get(parentId)
    if (!parent) break
    parent.selected_count = Math.max(0, Math.min(Number(parent.leaf_count || 0), Number(parent.selected_count || 0) + delta.count))
    parent.selected_size_bytes = Math.max(0, Math.min(Number(parent.size_bytes || 0), Number(parent.selected_size_bytes || 0) + delta.size))
    parentId = parent.parentId || ''
  }
}

function updateResourceSelection(group, node, nextSelected) {
  const delta = setSubtreeSelection(group, node, nextSelected)
  if (!delta.count && !delta.size) return
  applySelectionDeltaToAncestors(group, node, delta)
  group.selectedResourceCount = Math.max(0, Math.min(Number(group.totalResourceCount || 0), Number(group.selectedResourceCount || 0) + delta.count))
  group.selectedSizeBytes = Math.max(0, Math.min(Number(group.totalSizeBytes || 0), Number(group.selectedSizeBytes || 0) + delta.size))
}

function isGroupAllSelected(group) {
  return Number(group?.totalResourceCount || 0) > 0 && Number(group?.selectedResourceCount || 0) === Number(group?.totalResourceCount || 0)
}

function isGroupPartiallySelected(group) {
  const selected = Number(group?.selectedResourceCount || 0)
  return selected > 0 && selected < Number(group?.totalResourceCount || 0)
}

function isTreeNodeChecked(row) {
  return Number(row?.leaf_count || 0) > 0 && Number(row?.selected_count || 0) === Number(row?.leaf_count || 0)
}

function isTreeNodePartiallySelected(row) {
  const selected = Number(row?.selected_count || 0)
  return selected > 0 && selected < Number(row?.leaf_count || 0)
}

function collectSubmitPaths(group) {
  if (!group) return []
  if (isGroupAllSelected(group)) return group.path ? [group.path] : []
  if (!isGroupPartiallySelected(group)) return []
  return collectCheckedUploadPaths(group.tree || [])
}

function collectCheckedUploadPaths(nodes = [], ancestorChecked = false) {
  const paths = []
  for (const node of nodes) {
    const checked = isTreeNodeChecked(node)
    const currentPath = String(node.resolved_path || '').trim()
    if (!ancestorChecked && checked && currentPath) {
      paths.push(currentPath)
      continue
    }
    if (node.type === 'dir') paths.push(...collectCheckedUploadPaths(node.children || [], ancestorChecked || checked))
  }
  return paths
}

function normalizeSelectedPaths(paths = []) {
  const sorted = [...new Set(paths.map(path => normalizePath(path)).filter(Boolean))].sort((left, right) => left.length - right.length)
  const normalized = []
  for (const current of sorted) {
    if (!normalized.some(existing => current === existing || current.startsWith(`${existing.replace(/\/+$/, '')}/`))) {
      normalized.push(current)
    }
  }
  return normalized
}

function collectAllDirIds(nodes = []) {
  const ids = []
  for (const node of nodes) {
    if (node.type === 'dir') {
      ids.push(node.id)
      ids.push(...collectAllDirIds(node.children || []))
    }
  }
  return ids
}

function getPreviewFileTypeKey(item) {
  const explicit = String(item?.file_ext || '').trim().toLowerCase()
  if (explicit) return explicit.startsWith('.') ? explicit : `.${explicit}`
  const match = String(item?.relative_path || item?.name || '').toLowerCase().match(/\.([^.\\/]+)$/)
  return match?.[1] ? `.${match[1]}` : '__no_ext__'
}

function getPreviewFileTypeLabel(item) {
  const key = getPreviewFileTypeKey(item)
  return key === '__no_ext__' ? '无后缀' : key.replace(/^\./, '')
}

function fileTypeOrder(key) {
  const order = {
    '.wav': 0,
    '.flac': 1,
    '.mp3': 2,
    '.m4a': 3,
    '.pdf': 20,
    '.txt': 21,
    '.cue': 22,
    '.jpg': 30,
    '.png': 31,
    '.srt': 40,
    '.ass': 41,
    '.vtt': 42,
    '__no_ext__': 99
  }
  return order[key] ?? 80
}

function selectionChipClass(state) {
  if (state === 'all') return 'library-upload-chip is-all'
  if (state === 'partial') return 'library-upload-chip is-partial'
  return 'library-upload-chip'
}

function joinPath(basePath, childPath) {
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const child = String(childPath || '').replace(/^[/\\]+/, '')
  if (!base) return child
  if (!child) return base
  return `${base}/${child}`.replace(/\/+/g, '/')
}
