import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  Folder,
  FolderOpen,
  HardDrive,
  Loader2,
  Plus,
  RefreshCcw,
  Search,
  SkipForward,
  X
} from 'lucide-react'
import { libraryApi } from '../../../api'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { formatBytes, formatDateTime, normalizeListPayload } from '../../utils/format'
import { buildBreadcrumb, isDirectory, itemName, normalizePath, parentPath } from './libraryUtils'

const navMinWidth = 220
const navMaxWidth = 520
const conflictPreviewMax = 8

export function LibraryMoveDialog({ libraries, sourceLibraryId, initialPath, items, submitting, onClose, onSubmit }) {
  const targetLibraries = useMemo(
    () => (libraries || []).filter(item => item?.id && item?.enabled !== false && item?.writable !== false),
    [libraries]
  )
  const [targetLibraryId, setTargetLibraryId] = useState(sourceLibraryId || targetLibraries[0]?.id || '')
  const [currentPath, setCurrentPath] = useState(normalizePath(initialPath || ''))
  const [selectedFolderPath, setSelectedFolderPath] = useState('')
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [sortBy, setSortBy] = useState('name')
  const [sortOrder, setSortOrder] = useState('asc')
  const [navWidth, setNavWidth] = useState(300)
  const [navTree, setNavTree] = useState({})
  const [indexReady, setIndexReady] = useState(false)
  const [indexResults, setIndexResults] = useState([])
  const [indexLoading, setIndexLoading] = useState(false)
  const [indexError, setIndexError] = useState('')
  const [activeEntryIndex, setActiveEntryIndex] = useState(-1)
  const [targetPreviewEntries, setTargetPreviewEntries] = useState([])
  const [targetPreviewLoading, setTargetPreviewLoading] = useState(false)
  const [conflictOpen, setConflictOpen] = useState(false)
  const [pendingTarget, setPendingTarget] = useState(null)
  const resizeRef = useRef({ active: false, x: 0, width: 300 })
  const indexSearchRef = useRef(0)
  const fileBodyRef = useRef(null)

  const targetLibrary = targetLibraries.find(item => String(item.id) === String(targetLibraryId)) || null
  const breadcrumbs = useMemo(() => buildBreadcrumb(currentPath), [currentPath])
  const sourceNames = useMemo(() => new Set((items || []).map(item => itemName(item).trim().toLowerCase()).filter(Boolean)), [items])
  const sourcePaths = useMemo(() => new Set((items || []).map(item => normalizePath(item.path)).filter(Boolean)), [items])
  const effectiveTargetPath = selectedFolderPath || currentPath || ''
  const conflictNames = useMemo(() => {
    const set = new Set()
    const candidates = selectedFolderPath ? targetPreviewEntries : entries
    for (const entry of candidates) {
      const name = itemName(entry).trim().toLowerCase()
      if (name && sourceNames.has(name)) set.add(itemName(entry))
    }
    return [...set]
  }, [entries, sourceNames, selectedFolderPath, targetPreviewEntries])
  const conflictNamesPreview = conflictNames.slice(0, conflictPreviewMax)
  const inIndexSearchMode = indexReady && searchKeyword.trim().length > 0
  const filteredEntries = useMemo(() => {
    if (inIndexSearchMode) return sortMoveEntries(indexResults, sortBy, sortOrder)
    const query = searchKeyword.trim().toLowerCase()
    const base = query ? entries.filter(entry => `${itemName(entry)} ${entry.path || ''}`.toLowerCase().includes(query)) : entries
    return sortMoveEntries(base, sortBy, sortOrder)
  }, [entries, indexResults, inIndexSearchMode, searchKeyword, sortBy, sortOrder])
  const canGoUp = Boolean(currentPath)
  const targetEqualsSourceParent = (items || []).every(item => normalizePath(parentPath(item.path)) === normalizePath(effectiveTargetPath))
  const targetIsSourceOrChild = (items || []).some(item => {
    const sourcePath = normalizePath(item.path)
    const target = normalizePath(effectiveTargetPath)
    return sourcePath && target && (target === sourcePath || target.startsWith(`${sourcePath}/`))
  })
  const canSubmit = Boolean(targetLibraryId && !targetEqualsSourceParent && !targetIsSourceOrChild)

  useEffect(() => {
    if (!targetLibraryId && targetLibraries[0]?.id) setTargetLibraryId(targetLibraries[0].id)
  }, [targetLibraries[0]?.id, targetLibraryId])

  useEffect(() => {
    loadEntries(currentPath, targetLibraryId)
  }, [targetLibraryId, currentPath])

  useEffect(() => {
    if (!targetLibraryId) return
    ensureLibraryNavLoaded(targetLibraryId)
    loadIndexStatus(targetLibraryId)
  }, [targetLibraryId])

  useEffect(() => {
    if (!targetLibraryId || !currentPath) return
    expandNavToPath(targetLibraryId, currentPath)
  }, [targetLibraryId, currentPath])

  useEffect(() => {
    loadTargetConflictPreview()
  }, [targetLibraryId, selectedFolderPath])

  useEffect(() => {
    setActiveEntryIndex(filteredEntries.length ? 0 : -1)
  }, [filteredEntries.map(entry => entry.path || entry.name).join('|')])

  useEffect(() => {
    if (!inIndexSearchMode || !targetLibraryId) {
      setIndexResults([])
      setIndexLoading(false)
      setIndexError('')
      return undefined
    }
    const keyword = searchKeyword.trim()
    const token = indexSearchRef.current + 1
    indexSearchRef.current = token
    const timer = window.setTimeout(async () => {
      setIndexLoading(true)
      setIndexError('')
      try {
        const data = await libraryApi.searchIndex({
          libraryId: targetLibraryId,
          name: keyword,
          entryType: 'dir',
          limit: 120
        })
        if (token !== indexSearchRef.current) return
        const list = normalizeListPayload(data)
          .filter(isDirectory)
          .map(item => ({
            ...item,
            is_directory: true,
            entry_type: 'dir',
            path: normalizePath(item.absolute_path || item.path || item.relative_path || ''),
            name: item.name || itemName(item)
          }))
        setIndexResults(list)
      } catch (err) {
        if (token !== indexSearchRef.current) return
        setIndexError(err?.response?.data?.detail || err?.message || '索引搜索失败')
        setIndexResults([])
      } finally {
        if (token === indexSearchRef.current) setIndexLoading(false)
      }
    }, 260)
    return () => window.clearTimeout(timer)
  }, [inIndexSearchMode, targetLibraryId, searchKeyword])

  useEffect(() => {
    function move(event) {
      if (!resizeRef.current.active) return
      const delta = event.clientX - resizeRef.current.x
      setNavWidth(Math.max(navMinWidth, Math.min(navMaxWidth, resizeRef.current.width + delta)))
    }
    function up() {
      resizeRef.current.active = false
      document.body?.removeAttribute('data-lib-move-resizing')
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
      document.body?.removeAttribute('data-lib-move-resizing')
    }
  }, [])

  async function loadEntries(path = currentPath, libraryId = targetLibraryId) {
    if (!libraryId) {
      setEntries([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await libraryApi.browserListFolders(libraryId, path || '', {
        includeFiles: true,
        computeSize: true,
        computeSizeCap: 256
      })
      setEntries(normalizeListPayload(data))
      setSelectedFolderPath('')
    } catch (err) {
      setEntries([])
      setError(err?.response?.data?.detail || err?.message || '读取目录失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadIndexStatus(libraryId) {
    setIndexReady(false)
    if (!libraryId) return
    const data = await libraryApi.getIndexStatus(libraryId).catch(() => null)
    const status = Array.isArray(data?.libraries)
      ? data.libraries.find(item => String(item.library_id || item.id || '') === String(libraryId))
      : data
    setIndexReady(String(status?.status || status?.index_status || '') === 'ready')
  }

  async function loadTargetConflictPreview() {
    setTargetPreviewEntries([])
    if (!targetLibraryId || !selectedFolderPath) return
    setTargetPreviewLoading(true)
    try {
      const data = await libraryApi.browserListFolders(targetLibraryId, selectedFolderPath, {
        includeFiles: true,
        computeSize: false
      })
      setTargetPreviewEntries(normalizeListPayload(data))
    } finally {
      setTargetPreviewLoading(false)
    }
  }

  async function ensureLibraryNavLoaded(libraryId) {
    setNavTree(current => ({
      ...current,
      [libraryId]: current[libraryId] || { rootExpanded: true, rootChildren: [], rootLoading: false, nodes: {} }
    }))
    const state = navTree[libraryId]
    if (state?.rootChildren?.length || state?.rootLoading) return
    await loadNavChildren(libraryId, '')
  }

  async function loadNavChildren(libraryId, path) {
    setNavTree(current => {
      const lib = current[libraryId] || { rootExpanded: true, rootChildren: [], rootLoading: false, nodes: {} }
      if (!path) return { ...current, [libraryId]: { ...lib, rootLoading: true } }
      return {
        ...current,
        [libraryId]: {
          ...lib,
          nodes: { ...lib.nodes, [path]: { ...(lib.nodes[path] || {}), loading: true, expanded: true } }
        }
      }
    })
    try {
      const data = await libraryApi.browserListFolders(libraryId, path || '', { includeFiles: false })
      const children = normalizeListPayload(data).filter(isDirectory)
      setNavTree(current => {
        const lib = current[libraryId] || { rootExpanded: true, rootChildren: [], nodes: {} }
        if (!path) return { ...current, [libraryId]: { ...lib, rootChildren: children, rootLoading: false, rootExpanded: true } }
        return {
          ...current,
          [libraryId]: {
            ...lib,
            nodes: {
              ...lib.nodes,
              [path]: { ...(lib.nodes[path] || {}), children, loading: false, expanded: true }
            }
          }
        }
      })
    } catch (error) {
      setNavTree(current => {
        const lib = current[libraryId] || { rootExpanded: true, rootChildren: [], nodes: {} }
        if (!path) return { ...current, [libraryId]: { ...lib, rootLoading: false, rootError: error.message } }
        return {
          ...current,
          [libraryId]: {
            ...lib,
            nodes: { ...lib.nodes, [path]: { ...(lib.nodes[path] || {}), loading: false, error: error.message } }
          }
        }
      })
    }
  }

  async function expandNavToPath(libraryId, path) {
    const target = normalizePath(path)
    if (!libraryId || !target) return
    const ancestors = []
    let cursor = parentPath(target)
    while (cursor) {
      ancestors.unshift(cursor)
      cursor = parentPath(cursor)
    }
    for (const ancestor of ancestors) {
      await loadNavChildren(libraryId, ancestor).catch(() => null)
    }
    setNavTree(current => {
      const lib = current[libraryId] || { rootExpanded: true, rootChildren: [], rootLoading: false, nodes: {} }
      const nodes = { ...lib.nodes }
      ancestors.forEach(ancestor => {
        nodes[ancestor] = { ...(nodes[ancestor] || {}), expanded: true }
      })
      return { ...current, [libraryId]: { ...lib, rootExpanded: true, nodes } }
    })
  }

  function toggleNavNode(libraryId, path) {
    const normalized = normalizePath(path)
    const nodeState = navTree[libraryId]?.nodes?.[normalized]
    if (!nodeState?.children?.length && !nodeState?.loading) {
      loadNavChildren(libraryId, normalized)
      return
    }
    setNavTree(current => {
      const lib = current[libraryId] || { rootExpanded: true, rootChildren: [], nodes: {} }
      return {
        ...current,
        [libraryId]: {
          ...lib,
          nodes: {
            ...lib.nodes,
            [normalized]: { ...(lib.nodes[normalized] || {}), expanded: !lib.nodes[normalized]?.expanded }
          }
        }
      }
    })
  }

  function navigateTo(path, libraryId = targetLibraryId) {
    if (!libraryId) return
    setTargetLibraryId(libraryId)
    setCurrentPath(normalizePath(path || ''))
    setSelectedFolderPath('')
  }

  function selectEntry(entry) {
    if (!isDirectory(entry)) return
    const path = normalizePath(entry.path)
    setSelectedFolderPath(path === selectedFolderPath ? '' : path)
  }

  function handleSort(nextSortBy) {
    if (sortBy === nextSortBy) {
      setSortOrder(value => value === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(nextSortBy)
      setSortOrder(nextSortBy === 'name' ? 'asc' : 'desc')
    }
  }

  function handleSubmit() {
    if (!canSubmit) return
    const snapshot = { targetLibraryId, targetPath: effectiveTargetPath }
    if (conflictNames.length) {
      setPendingTarget(snapshot)
      setConflictOpen(true)
      return
    }
    onSubmit({ ...snapshot, conflictStrategy: 'suffix' })
  }

  function confirmConflict(conflictStrategy) {
    const snapshot = pendingTarget
    setConflictOpen(false)
    setPendingTarget(null)
    if (!snapshot) return
    onSubmit({ ...snapshot, conflictStrategy })
  }

  function startResize(event) {
    resizeRef.current = { active: true, x: event.clientX, width: navWidth }
    document.body?.setAttribute('data-lib-move-resizing', '1')
  }

  function handleListKeyDown(event) {
    if (!filteredEntries.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveEntryIndex(index => Math.min(filteredEntries.length - 1, Math.max(0, index) + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveEntryIndex(index => Math.max(0, index <= 0 ? 0 : index - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const entry = filteredEntries[Math.max(0, activeEntryIndex)]
      if (!entry || !isDirectory(entry)) return
      if (event.ctrlKey || event.metaKey) selectEntry(entry)
      else navigateTo(normalizePath(entry.path || entry.name))
    }
  }

  return (
    <Modal
      title="移动到..."
      width={1180}
      onClose={onClose}
      footer={
        <div className="library-move-explorer-footer">
          <div className="library-move-source-chips">
            {(items || []).slice(0, 5).map(item => (
              <span key={item.path || item.name} title={item.path}>
                {isDirectory(item) ? <Folder size={12} /> : <FileIcon size={12} />}
                {itemName(item)}
              </span>
            ))}
            {items.length > 5 ? <span>+{items.length - 5} 项</span> : null}
          </div>
          <div className="library-move-target-chip" title={effectiveTargetPath}>
            <ArrowRight size={13} />
            <span>移动到</span>
            <b>{effectiveTargetPath || '根目录'}</b>
            {conflictNames.length ? <em><AlertCircle size={12} />{conflictNames.length} 同名</em> : null}
          </div>
          <div className="library-move-footer-actions">
            <Button onClick={onClose} disabled={submitting}>取消</Button>
            <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={handleSubmit}>
              移动 {items.length} 项
            </Button>
          </div>
        </div>
      }
    >
      <div className="library-move-explorer">
        <header className="library-move-explorer-toolbar">
          <AppDropdown
            value={targetLibraryId || 'default'}
            onChange={value => navigateTo('', value === 'default' ? '' : value)}
            options={targetLibraries.map(item => ({ value: String(item.id), label: item.name || String(item.id) }))}
            width={230}
          />
          <Button size="sm" disabled={!canGoUp || loading} onClick={() => navigateTo(parentPath(currentPath))}><ArrowUp size={14} />上级</Button>
          <Button size="sm" disabled={loading || !targetLibraryId} onClick={() => loadEntries()}><RefreshCcw size={14} />刷新</Button>
          <div className="library-move-crumbs">
            <button type="button" onClick={() => navigateTo('')}><HardDrive size={13} />{targetLibrary?.name || targetLibraryId || '目标库存'}</button>
            {breadcrumbs.slice(1).map(crumb => (
              <span key={crumb.path}>
                <ChevronRight size={13} />
                <button type="button" className={crumb.path === currentPath ? 'is-current' : ''} onClick={() => navigateTo(crumb.path)}>{crumb.label}</button>
              </span>
            ))}
          </div>
          <label className="library-move-search">
            <Search size={14} />
            <TextInput
              value={searchKeyword}
              onChange={event => setSearchKeyword(event.target.value)}
              placeholder={indexReady ? `在「${targetLibrary?.name || '目标库存'}」中全库搜索目录...` : '搜索当前目录...'}
            />
          </label>
        </header>

        <div className="library-move-explorer-main">
          <aside className="library-move-nav" style={{ width: navWidth }}>
            <div className="library-move-nav-scroll">
              {targetLibraries.map(library => (
                <LibraryMoveNavLibrary
                  key={library.id}
                  library={library}
                  state={navTree[library.id]}
                  activeLibraryId={targetLibraryId}
                  currentPath={currentPath}
                  sourceLibraryId={sourceLibraryId}
                  onNavigate={navigateTo}
                  onLoadChildren={loadNavChildren}
                  onToggleNode={toggleNavNode}
                  onPatchState={patch => setNavTree(current => ({ ...current, [library.id]: { ...(current[library.id] || {}), ...patch } }))}
                />
              ))}
            </div>
          </aside>
          <button type="button" className="library-move-nav-splitter" onPointerDown={startResize} aria-label="调整目录树宽度" />
          <section className="library-move-file-list">
            <div className="library-move-file-head">
              <button type="button" className={sortBy === 'name' ? 'is-active' : ''} onClick={() => handleSort('name')}>名称</button>
              <button type="button" className={sortBy === 'size' ? 'is-active' : ''} onClick={() => handleSort('size')}>大小</button>
              <button type="button" className={sortBy === 'mtime' ? 'is-active' : ''} onClick={() => handleSort('mtime')}>修改时间</button>
            </div>
            <div
              ref={fileBodyRef}
              className="library-move-file-body"
              tabIndex={0}
              onKeyDown={handleListKeyDown}
            >
              {inIndexSearchMode && indexLoading ? <LoadingState label="正在全库搜索目录..." /> : null}
              {inIndexSearchMode && indexError ? <div className="km-empty"><AlertCircle size={18} /><strong>{indexError}</strong></div> : null}
              {!inIndexSearchMode && loading ? <LoadingState label="正在读取目录..." /> : null}
              {!inIndexSearchMode && error ? <div className="km-empty"><AlertCircle size={18} /><strong>{error}</strong></div> : null}
              {!loading && !indexLoading && !indexError && !error && !filteredEntries.length ? <div className="km-empty"><strong>{searchKeyword ? '没有匹配项' : '此目录为空'}</strong></div> : null}
              {!loading && !indexLoading && !indexError && !error && filteredEntries.map((entry, index) => {
                const path = normalizePath(entry.path)
                const folder = isDirectory(entry)
                const conflict = sourceNames.has(itemName(entry).trim().toLowerCase())
                const sourceSelf = sourcePaths.has(path)
                return (
                  <button
                    type="button"
                    key={entry.path || entry.name}
                    className={`library-move-file-row ${selectedFolderPath === path ? 'is-selected' : ''} ${index === activeEntryIndex ? 'is-active' : ''} ${conflict ? 'is-conflict' : ''} ${sourceSelf ? 'is-source' : ''} ${!folder ? 'is-file' : ''}`}
                    title={entry.path}
                    onMouseEnter={() => setActiveEntryIndex(index)}
                    onClick={() => selectEntry(entry)}
                    onDoubleClick={() => folder && navigateTo(path)}
                  >
                    <span>
                      {folder ? <FolderOpen size={16} /> : <FileIcon size={16} />}
                      <b>{itemName(entry)}</b>
                      {conflict ? <em>同名</em> : null}
                    </span>
                    <span>{entry.size !== null && entry.size !== undefined ? formatBytes(entry.size) : '-'}</span>
                    <time>{formatDateTime(entry.modified_time || entry.modified)}</time>
                  </button>
                )
              })}
            </div>
          </section>
        </div>

        {conflictNames.length || targetEqualsSourceParent || targetIsSourceOrChild ? (
          <section className="library-move-conflict-preview">
            {targetEqualsSourceParent ? <span><AlertCircle size={13} />目标目录就是源目录，无法移动。</span> : null}
            {targetIsSourceOrChild ? <span><AlertCircle size={13} />不能把目录移动到自己或子目录内。</span> : null}
            {conflictNames.length ? (
              <>
                <strong><AlertCircle size={13} />同名预览：{targetPreviewLoading ? '读取中' : `${conflictNames.length} 项`}</strong>
                <div>
                  {conflictNamesPreview.map(name => <em key={name}>{name}</em>)}
                  {conflictNames.length > conflictNamesPreview.length ? <em>+{conflictNames.length - conflictNamesPreview.length}</em> : null}
                </div>
              </>
            ) : null}
          </section>
        ) : null}

        {conflictOpen ? (
          <div className="library-move-conflict-overlay" onClick={() => { setConflictOpen(false); setPendingTarget(null) }}>
            <section className="library-move-conflict-panel" onClick={event => event.stopPropagation()}>
              <header>
                <span><AlertCircle size={16} /></span>
                <div>
                  <strong>目标目录已存在 {conflictNames.length} 个同名项</strong>
                  <small>请选择处理方式</small>
                </div>
                <button type="button" onClick={() => { setConflictOpen(false); setPendingTarget(null) }}><X size={15} /></button>
              </header>
              <ul>
                {conflictNamesPreview.map(name => <li key={name}><Folder size={12} />{name}</li>)}
                {conflictNames.length > conflictNamesPreview.length ? <li>+{conflictNames.length - conflictNamesPreview.length} 项</li> : null}
              </ul>
              <div>
                <button type="button" onClick={() => confirmConflict('suffix')}><Plus size={13} />追加序号</button>
                <button type="button" onClick={() => confirmConflict('overwrite')}><RefreshCcw size={13} />覆盖现有</button>
                <button type="button" onClick={() => confirmConflict('skip')}><SkipForward size={13} />跳过同名</button>
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

function LibraryMoveNavLibrary({
  library,
  state,
  activeLibraryId,
  currentPath,
  sourceLibraryId,
  onNavigate,
  onLoadChildren,
  onToggleNode,
  onPatchState
}) {
  const expanded = state?.rootExpanded !== false
  const children = state?.rootChildren || []
  return (
    <div className="library-move-nav-library">
      <button
        type="button"
        className={`library-move-nav-row ${String(activeLibraryId) === String(library.id) && !currentPath ? 'is-active' : ''} ${String(sourceLibraryId) === String(library.id) ? 'is-source' : ''}`}
        onClick={() => onNavigate('', library.id)}
      >
        <span
          onClick={event => {
            event.stopPropagation()
            onPatchState({ rootExpanded: !expanded })
            if (!children.length) onLoadChildren(library.id, '')
          }}
        >
          <ChevronRight size={13} className={expanded ? 'is-open' : ''} />
        </span>
        <HardDrive size={14} />
        <b>{library.name || library.id}</b>
      </button>
      {expanded ? (
        <div className="library-move-nav-children">
          {state?.rootLoading ? <div className="library-move-nav-loading"><RefreshCcw size={13} className="km-spin" />读取中</div> : null}
          {children.map(child => (
            <LibraryMoveNavNode
              key={child.path || child.name}
              libraryId={library.id}
              node={child}
              depth={1}
              state={state}
              activeLibraryId={activeLibraryId}
              currentPath={currentPath}
              onNavigate={onNavigate}
              onLoadChildren={onLoadChildren}
              onToggleNode={onToggleNode}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function LibraryMoveNavNode({ libraryId, node, depth, state, activeLibraryId, currentPath, onNavigate, onLoadChildren, onToggleNode }) {
  const path = normalizePath(node.path || node.name)
  const nodeState = state?.nodes?.[path] || {}
  const expanded = Boolean(nodeState.expanded)
  const active = String(activeLibraryId) === String(libraryId) && normalizePath(currentPath) === path
  return (
    <div className="library-move-nav-node">
      <button
        type="button"
        className={`library-move-nav-row ${active ? 'is-active' : ''}`}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => onNavigate(path, libraryId)}
      >
        <span
          onClick={event => {
            event.stopPropagation()
            onToggleNode(libraryId, path)
          }}
        >
          <ChevronRight size={13} className={expanded ? 'is-open' : ''} />
        </span>
        <Folder size={14} />
        <b>{itemName(node)}</b>
      </button>
      {expanded ? (
        <div className="library-move-nav-children">
          {nodeState.loading ? <div className="library-move-nav-loading"><RefreshCcw size={13} className="km-spin" />读取中</div> : null}
          {(nodeState.children || []).map(child => (
            <LibraryMoveNavNode
              key={child.path || child.name}
              libraryId={libraryId}
              node={child}
              depth={depth + 1}
              state={state}
              activeLibraryId={activeLibraryId}
              currentPath={currentPath}
              onNavigate={onNavigate}
              onLoadChildren={onLoadChildren}
              onToggleNode={onToggleNode}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function sortMoveEntries(entries, sortBy, sortOrder) {
  const direction = sortOrder === 'desc' ? -1 : 1
  return [...(entries || [])].sort((left, right) => {
    if (isDirectory(left) !== isDirectory(right)) return isDirectory(left) ? -1 : 1
    if (sortBy === 'size') return (Number(left.size || left.size_bytes || 0) - Number(right.size || right.size_bytes || 0)) * direction
    if (sortBy === 'mtime') return String(left.modified_time || left.modified || '').localeCompare(String(right.modified_time || right.modified || '')) * direction
    return itemName(left).localeCompare(itemName(right), 'zh-CN', { numeric: true }) * direction
  })
}
