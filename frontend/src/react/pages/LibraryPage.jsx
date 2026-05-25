import { useEffect, useMemo, useState } from 'react'
import { RefreshCcw } from 'lucide-react'
import { libraryApi, localUploadApi, rjSubtitleApi, taskApi } from '../../api'
import { Button, PageHeader } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../stores/systemPromptStore'
import { normalizeListPayload } from '../utils/format'
import { LibraryActionScopeBar } from './library/LibraryActionScopeBar'
import { LibraryBatchBar } from './library/LibraryBatchBar'
import { LibraryBreadcrumbBar } from './library/LibraryBreadcrumbBar'
import { LibraryContextMenu } from './library/LibraryContextMenu'
import { LibraryFileTable } from './library/LibraryFileTable'
import { LibraryFilterDeleteDialog } from './library/LibraryFilterDeleteDialog'
import { LibraryFolderContentsDialog } from './library/LibraryFolderContentsDialog'
import { LibraryIndexBadge } from './library/LibraryIndexBadge'
import { LibraryLocalUploadDialog } from './library/LibraryLocalUploadDialog'
import { LibraryMediaPreview } from './library/LibraryMediaPreview'
import { LibraryMoveDialog } from './library/LibraryMoveDialog'
import { LibrarySearchOverlay } from './library/LibrarySearchOverlay'
import { LibraryStatsStrip } from './library/LibraryStatsStrip'
import { LibrarySubtitleTaskPanel } from './library/LibrarySubtitleTaskPanel'
import { LibraryToolbar } from './library/LibraryToolbar'
import { LibraryUploadBackgroundCard, LibraryUploadTaskWorkbenchDialog } from './library/LibraryUploadTaskWorkbenchDialog'
import {
  buildBreadcrumb,
  canApiRenameRow,
  canViewLibraryRow,
  classifyLibraryEntryKind,
  extractRJCode,
  isDirectory,
  itemName,
  normalizePath,
  normalizeIndexEntryPath,
  isIndexEntryDirectory,
  parentPath,
  rowKey
} from './library/libraryUtils'

const LIBRARY_ACTION_SCOPE_KEY = 'kikoeru.ui.library.toolbarActionScope.react'
const UPLOAD_WORKBENCH_KEY = 'kikoerumanager.library.uploadWorkbench.react'

export function LibraryPage() {
  const [libraries, setLibraries] = useState([])
  const [libraryId, setLibraryId] = useState('')
  const [currentPath, setCurrentPath] = useState('')
  const [search, setSearch] = useState('')
  const [searchKind, setSearchKind] = useState('all')
  const [toolbarActionScope, setToolbarActionScope] = useState(() => {
    try {
      return window.localStorage.getItem(LIBRARY_ACTION_SCOPE_KEY) === 'all' ? 'all' : 'page'
    } catch (_) {
      return 'page'
    }
  })
  const [sortBy, setSortBy] = useState('size')
  const [sortOrder, setSortOrder] = useState('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [indexStatus, setIndexStatus] = useState(null)
  const [selectedKeys, setSelectedKeys] = useState(new Set())
  const [lastSelectedKey, setLastSelectedKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [autoCircleGroupRunningId, setAutoCircleGroupRunningId] = useState('')
  const [moveOpen, setMoveOpen] = useState(false)
  const [moveItems, setMoveItems] = useState([])
  const [contextMenu, setContextMenu] = useState({ visible: false, row: null, x: 0, y: 0, batchMode: false })
  const [previewState, setPreviewState] = useState({ visible: false, item: null })
  const [folderDialogState, setFolderDialogState] = useState({ visible: false, path: '', name: '' })
  const [filterDeleteState, setFilterDeleteState] = useState({ visible: false, currentPath: '', targetPaths: [], scopeLabel: '' })
  const [dragState, setDragState] = useState({ items: [], targetKey: '', targetPath: '' })
  const [locatedPath, setLocatedPath] = useState('')
  const [searchOverlay, setSearchOverlay] = useState({ visible: false, keyword: '', kindFilter: 'all' })
  const [localUploadState, setLocalUploadState] = useState({ visible: false, rows: [] })
  const [localUploadSubmitting, setLocalUploadSubmitting] = useState(false)
  const [trackedUploadTaskIds, setTrackedUploadTaskIds] = useState(() => {
    try {
      const raw = JSON.parse(window.localStorage.getItem(UPLOAD_WORKBENCH_KEY) || '{}')
      return Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    } catch (_) {
      return []
    }
  })
  const [uploadTasks, setUploadTasks] = useState([])
  const [uploadWorkbenchVisible, setUploadWorkbenchVisible] = useState(() => {
    try {
      const raw = JSON.parse(window.localStorage.getItem(UPLOAD_WORKBENCH_KEY) || '{}')
      return Boolean(raw.visible && Array.isArray(raw.taskIds) && raw.taskIds.length)
    } catch (_) {
      return false
    }
  })
  const [uploadBackgroundActive, setUploadBackgroundActive] = useState(() => {
    try {
      const raw = JSON.parse(window.localStorage.getItem(UPLOAD_WORKBENCH_KEY) || '{}')
      return Boolean(raw.background && Array.isArray(raw.taskIds) && raw.taskIds.length)
    } catch (_) {
      return false
    }
  })
  const [uploadRefreshing, setUploadRefreshing] = useState(false)
  const [subtitlePanelVisible, setSubtitlePanelVisible] = useState(false)
  const [subtitleStatus, setSubtitleStatus] = useState(null)
  const [subtitleRefreshing, setSubtitleRefreshing] = useState(false)

  const currentLibrary = useMemo(
    () => libraries.find(item => String(item.id) === String(libraryId)) || null,
    [libraries, libraryId]
  )
  const isRemoteCurrentLibrary = currentLibrary?.type === 'synology_filestation'
  const isWritableCurrentLibrary = currentLibrary ? currentLibrary.writable !== false : true
  const remoteUploadLibraries = useMemo(
    () => libraries.filter(item => item?.type === 'synology_filestation' && item?.enabled !== false),
    [libraries]
  )
  const currentStats = useMemo(() => resolveCurrentStats(stats, libraryId), [stats, libraryId])
  const aggregateStats = stats?.all_libraries || null
  const selectedRows = useMemo(() => rows.filter(row => selectedKeys.has(rowKey(row))), [rows, selectedKeys])
  const selectedSubtitleRows = useMemo(() => selectedRows.filter(canSubtitleRow), [selectedRows, isWritableCurrentLibrary])
  const selectedUploadRows = useMemo(() => selectedRows.filter(row => row?.path), [selectedRows])
  const currentPageDirectoryRows = useMemo(() => rows.filter(isDirectory), [rows])
  const toolbarSubtitleRows = useMemo(() => {
    if (toolbarActionScope === 'page') {
      if (currentPageDirectoryRows.length) return currentPageDirectoryRows
      return currentPath ? [{ path: currentPath, name: itemName({ path: currentPath }), is_directory: true }] : []
    }
    return currentPath ? [{ path: currentPath, name: itemName({ path: currentPath }), is_directory: true }] : []
  }, [toolbarActionScope, currentPageDirectoryRows, currentPath])
  const toolbarFilterDeletePaths = useMemo(() => {
    if (toolbarActionScope === 'page') {
      const pagePaths = currentPageDirectoryRows.map(row => row.path).filter(Boolean)
      return pagePaths.length ? [...new Set(pagePaths)] : (currentPath ? [currentPath] : [])
    }
    return currentPath ? [currentPath] : []
  }, [toolbarActionScope, currentPageDirectoryRows, currentPath])
  const allPageSelected = rows.length > 0 && rows.every(row => selectedKeys.has(rowKey(row)))
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const breadcrumbs = useMemo(() => buildBreadcrumb(currentPath), [currentPath])
  const imageRows = useMemo(() => rows.filter(row => classifyLibraryEntryKind(row) === 'image'), [rows])
  const canCancelStats = currentStats?.status === 'pending'

  async function loadLibraries() {
    const data = await libraryApi.listLibraries()
    const list = Array.isArray(data?.libraries) ? data.libraries : normalizeListPayload(data)
    setLibraries(list)
    if (!libraryId && list[0]?.id) setLibraryId(list[0].id)
  }

  async function loadIndexStatus(id = libraryId) {
    if (!id) {
      setIndexStatus(null)
      return
    }
    const data = await libraryApi.getIndexStatus(id).catch(() => null)
    setIndexStatus(data)
  }

  async function loadStats(forceRefresh = false, id = libraryId) {
    setStatsLoading(true)
    try {
      const data = await libraryApi.getStats(forceRefresh, id || null)
      setStats(data)
      return data
    } finally {
      setStatsLoading(false)
    }
  }

  async function refresh(options = {}) {
    const nextPage = options.page ?? page
    setLoading(true)
    try {
      const data = await libraryApi.browseFiles({
        libraryId: libraryId || undefined,
        currentPath,
        search: '',
        page: nextPage,
        pageSize,
        forceRefresh: options.forceRefresh ?? false,
        sortBy,
        sortOrder,
        searchExact: false,
        searchResultKind: 'all',
        scope: 'global'
      })
      const list = normalizeListPayload(data)
      setRows(list)
      setTotal(Number(data?.total ?? data?.total_files ?? list.length))
      setPage(Number(data?.page ?? nextPage))
      setSelectedKeys(prev => {
        const visible = new Set(list.map(rowKey))
        return new Set([...prev].filter(key => visible.has(key)))
      })
      setLastSelectedKey(key => list.some(row => rowKey(row) === key) ? key : '')
      const statData = await libraryApi.getStats(false, libraryId || null).catch(() => null)
      if (statData) setStats(statData)
      await loadIndexStatus()
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLibraries()
  }, [])

  useEffect(() => {
    if (libraryId || libraries.length === 0) refresh({ page: 1 })
  }, [libraryId, currentPath, sortBy, sortOrder, pageSize])

  useEffect(() => {
    if (indexStatus?.status !== 'syncing') return undefined
    const timer = window.setInterval(() => loadIndexStatus(), 1200)
    return () => window.clearInterval(timer)
  }, [indexStatus?.status, libraryId])

  useEffect(() => {
    try {
      window.localStorage.setItem(LIBRARY_ACTION_SCOPE_KEY, toolbarActionScope)
    } catch (_) {}
  }, [toolbarActionScope])

  useEffect(() => {
    try {
      window.localStorage.setItem(UPLOAD_WORKBENCH_KEY, JSON.stringify({
        taskIds: trackedUploadTaskIds,
        visible: uploadWorkbenchVisible,
        background: uploadBackgroundActive
      }))
    } catch (_) {}
  }, [trackedUploadTaskIds, uploadWorkbenchVisible, uploadBackgroundActive])

  useEffect(() => {
    if (!trackedUploadTaskIds.length) {
      setUploadTasks([])
      return undefined
    }
    refreshUploadWorkbench({ silent: true })
    const timer = window.setInterval(() => refreshUploadWorkbench({ silent: true }), 2200)
    return () => window.clearInterval(timer)
  }, [trackedUploadTaskIds.join(',')])

  useEffect(() => {
    if (!subtitlePanelVisible) return undefined
    refreshSubtitleStatus({ silent: true })
    const timer = window.setInterval(() => refreshSubtitleStatus({ silent: true }), 2500)
    return () => window.clearInterval(timer)
  }, [subtitlePanelVisible])

  function changeLibrary(value) {
    setLibraryId(value === 'default' ? '' : value)
    setCurrentPath('')
    setPage(1)
    setSelectedKeys(new Set())
    setLastSelectedKey('')
    setLocatedPath('')
  }

  function openRow(item) {
    if (!isDirectory(item)) return
    setCurrentPath(normalizePath(item.path || ''))
    setPage(1)
    setSelectedKeys(new Set())
    setLastSelectedKey('')
    setLocatedPath('')
  }

  function goUp() {
    setCurrentPath(parentPath(currentPath))
    setPage(1)
    setSelectedKeys(new Set())
    setLastSelectedKey('')
    setLocatedPath('')
  }

  async function locateSearchResult(entry) {
    const absolutePath = normalizeIndexEntryPath(entry)
    if (!absolutePath) return
    const targetLibraryId = entry?.library_id || libraryId
    const directory = isIndexEntryDirectory(entry)
    const targetPath = directory ? absolutePath : parentPath(absolutePath)
    setSearch('')
    setSearchOverlay({ visible: false, keyword: '', kindFilter: searchKind })
    setSelectedKeys(new Set())
    setLastSelectedKey('')
    setLocatedPath(absolutePath)
    if (targetLibraryId && String(targetLibraryId) !== String(libraryId)) {
      setLibraryId(targetLibraryId)
    }
    setCurrentPath(targetPath)
    setPage(1)
  }

  function toggleSelected(item, checked) {
    const key = rowKey(item)
    setLastSelectedKey(key)
    setSelectedKeys(prev => {
      const next = new Set(prev)
      if (checked) next.add(key)
      else next.delete(key)
      return next
    })
  }

  function togglePageSelected(checked) {
    setSelectedKeys(prev => {
      const next = new Set(prev)
      for (const row of rows) {
        const key = rowKey(row)
        if (checked) next.add(key)
        else next.delete(key)
      }
      return next
    })
    setLastSelectedKey(checked ? rowKey(rows.at(-1)) : '')
  }

  function selectRowByEvent(item, event) {
    const key = rowKey(item)
    const rowIndex = rows.findIndex(row => rowKey(row) === key)
    const anchorIndex = rows.findIndex(row => rowKey(row) === lastSelectedKey)

    setSelectedKeys(prev => {
      if (event?.shiftKey && rowIndex >= 0 && anchorIndex >= 0) {
        const [start, end] = rowIndex > anchorIndex ? [anchorIndex, rowIndex] : [rowIndex, anchorIndex]
        const next = new Set(prev)
        rows.slice(start, end + 1).forEach(row => next.add(rowKey(row)))
        return next
      }

      if (event?.ctrlKey || event?.metaKey) {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      }

      return new Set([key])
    })
    setLastSelectedKey(key)
  }

  function selectRowsByMarquee(keys, additive = false) {
    const nextKeys = keys.filter(Boolean)
    setSelectedKeys(prev => {
      const next = additive ? new Set(prev) : new Set()
      nextKeys.forEach(key => next.add(key))
      return next
    })
    setLastSelectedKey(nextKeys.at(-1) || '')
  }

  async function rename(item) {
    const next = await showSystemPrompt({
      title: '重命名',
      currentValue: item.path,
      modelValue: itemName(item),
      placeholder: '新名称'
    })
    if (!next) return
    await libraryApi.browserRename(libraryId, item.path, next)
    await refresh()
  }

  async function apiRename(item) {
    if (!canApiRenameRow(item)) return
    setBusy(true)
    try {
      await libraryApi.apiRename(item.path, libraryId || null)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function remove(item) {
    await showSystemConfirm({
      title: '确认删除',
      message: '删除会作用到库存路径，请确认。',
      currentValue: item.path,
      confirmText: '删除',
      tone: 'danger'
    })
    await libraryApi.browserDelete(libraryId, item.path, true)
    await refresh()
  }

  async function removeRows(targetRows) {
    const targets = targetRows.filter(Boolean)
    if (!targets.length) return
    if (targets.length === 1) {
      await remove(targets[0])
      return
    }
    await showSystemConfirm({
      title: '批量删除',
      message: `将删除 ${targets.length} 个库存条目。`,
      currentValue: targets.map(row => row.path).join('\n'),
      confirmText: '批量删除',
      tone: 'danger',
      width: 560,
      inputType: 'textarea'
    })
    setBusy(true)
    try {
      await libraryApi.browserBatchDelete(libraryId, targets.map(row => row.path), true)
      setSelectedKeys(new Set())
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function batchDelete() {
    if (!selectedRows.length) return
    await showSystemConfirm({
      title: '批量删除',
      message: `将删除 ${selectedRows.length} 个库存条目。`,
      currentValue: selectedRows.map(row => row.path).join('\n'),
      confirmText: '批量删除',
      tone: 'danger',
      width: 560,
      inputType: 'textarea'
    })
    setBusy(true)
    try {
      await libraryApi.browserBatchDelete(libraryId, selectedRows.map(row => row.path), true)
      setSelectedKeys(new Set())
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function batchApiRename() {
    const targets = selectedRows.filter(canApiRenameRow)
    if (!targets.length) return
    await showSystemConfirm({
      title: '批量 API 命名',
      message: `将对 ${targets.length} 个 RJ 目录执行 API 命名。`,
      currentValue: targets.map(row => row.path).join('\n'),
      confirmText: '开始命名',
      tone: 'warning',
      width: 560,
      inputType: 'textarea'
    })
    setBusy(true)
    try {
      const results = await runLimited(targets, 4, row => libraryApi.apiRename(row.path, libraryId || null))
      const failed = results.filter(item => item.status === 'rejected')
      setSelectedKeys(new Set())
      await refresh()
      if (failed.length) {
        await showSystemAlert({
          title: '部分 API 命名失败',
          message: `失败 ${failed.length} / ${targets.length} 项，首个错误：${failed[0]?.reason?.response?.data?.detail || failed[0]?.reason?.message || failed[0]?.reason}`,
          tone: 'warning'
        })
      }
    } finally {
      setBusy(false)
    }
  }

  function canSubtitleRow(row) {
    return Boolean(isDirectory(row) && row?.path && isWritableCurrentLibrary)
  }

  function toRJSubtitleItem(row) {
    if (!row) return null
    return {
      rjcode: row.rjcode || extractRJCode(row.path || row.name),
      folder_name: row.name || itemName(row),
      folder_path: row.path,
      library_id: row.library_id || libraryId || ''
    }
  }

  async function startRJSubtitle(rowsForSubtitle) {
    const targets = rowsForSubtitle.filter(canSubtitleRow).map(toRJSubtitleItem).filter(Boolean)
    if (!targets.length) return
    await showSystemConfirm({
      title: targets.length === 1 ? '识别抓字幕' : '批量抓字幕',
      message: `将提交 ${targets.length} 个 RJ 目录进入字幕工作台任务链。`,
      currentValue: targets.map(item => `${item.rjcode || '-'}  ${item.folder_path}`).join('\n'),
      confirmText: '开始抓字幕',
      tone: 'warning',
      width: 600,
      inputType: 'textarea'
    })
    setBusy(true)
    try {
      const batchId = `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      await rjSubtitleApi.start(targets, {
        batchContext: {
          batch_id: batchId,
          source_page: 'library',
          source_action: targets.length === 1 ? 'row_subtitle' : 'batch_subtitle',
          source_directories: targets.map(item => ({
            rjcode: item.rjcode,
            folder_path: item.folder_path,
            library_id: item.library_id
          }))
        }
      })
      await showSystemAlert({ title: '字幕任务已提交', message: '可在任务队列或字幕补配页继续查看处理结果。', tone: 'success' })
    } finally {
      setBusy(false)
    }
  }

  async function startToolbarRJSubtitle() {
    if (!toolbarSubtitleRows.length || !isWritableCurrentLibrary) return
    if (toolbarActionScope === 'all' && currentPath) {
      setBusy(true)
      try {
        const scan = await rjSubtitleApi.scan(currentPath, { libraryId, scanDepth: 3 })
        const targets = normalizeListPayload(scan)
          .filter(item => item?.status === 'ready' || item?.rjcode || item?.folder_path)
          .map(item => ({
            rjcode: item.rjcode || extractRJCode(item.folder_path || item.path || item.folder_name),
            folder_name: item.folder_name || item.name || itemName({ path: item.folder_path || item.path }),
            folder_path: item.folder_path || item.path,
            library_id: item.library_id || libraryId || ''
          }))
          .filter(item => item.folder_path)
        if (!targets.length) {
          await showSystemAlert({ title: '未识别到可抓字幕的 RJ 目录', tone: 'warning' })
          return
        }
        await showSystemConfirm({
          title: '当前目录抓字幕',
          message: `扫描到 ${targets.length} 个 RJ 目录，将提交到字幕任务链。`,
          currentValue: targets.map(item => `${item.rjcode || '-'}  ${item.folder_path}`).join('\n'),
          confirmText: '开始抓字幕',
          tone: 'warning',
          width: 620,
          inputType: 'textarea'
        })
        const batchId = `subtitle-scope-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        await rjSubtitleApi.start(targets, {
          batchContext: {
            batch_id: batchId,
            source_page: 'library',
            source_action: 'current_folder_subtitle',
            source_directories: targets.map(item => ({
              rjcode: item.rjcode,
              folder_path: item.folder_path,
              library_id: item.library_id
            }))
          }
        })
        await showSystemAlert({ title: '字幕任务已提交', tone: 'success' })
      } finally {
        setBusy(false)
      }
      return
    }
    await startRJSubtitle(toolbarSubtitleRows)
  }

  function openToolbarFilterDeleteDialog() {
    if (!toolbarFilterDeletePaths.length || !isWritableCurrentLibrary) return
    setFilterDeleteState({
      visible: true,
      currentPath: currentPath || toolbarFilterDeletePaths[0],
      targetPaths: toolbarFilterDeletePaths,
      scopeLabel: toolbarActionScope === 'page' ? `当前页目录（${toolbarFilterDeletePaths.length} 项）` : itemName({ path: currentPath })
    })
  }

  async function computeSelectedFolderSize() {
    const dirs = selectedRows.filter(isDirectory)
    if (!dirs.length) return
    setBusy(true)
    try {
      for (const row of dirs) {
        await libraryApi.computeFolderSize(row.path)
      }
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function computeFolderSize(row) {
    if (!isDirectory(row)) return
    setBusy(true)
    try {
      await libraryApi.computeFolderSize(row.path)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function openFolderInSystem(item) {
    await libraryApi.browserOpenFolder(libraryId, item.path, false)
  }

  async function viewRow(item) {
    if (!item) return
    if (isDirectory(item)) {
      openRow(item)
      return
    }
    if (canViewLibraryRow(item)) {
      setPreviewState({ visible: true, item })
      return
    }
    await openFolderInSystem(item)
  }

  function openFolderContents(item) {
    if (!isDirectory(item)) return
    setFolderDialogState({
      visible: true,
      path: item.path || '',
      name: itemName(item)
    })
  }

  function openFilterDeleteDialog(targetRows = [], options = {}) {
    const paths = targetRows.filter(isDirectory).map(row => row.path).filter(Boolean)
    const targetPathList = paths.length ? [...new Set(paths)] : (options.currentPath ? [options.currentPath] : [])
    if (!targetPathList.length || !isWritableCurrentLibrary) return
    setFilterDeleteState({
      visible: true,
      currentPath: options.currentPath || currentPath || targetPathList[0],
      targetPaths: targetPathList,
      scopeLabel: options.scopeLabel || (paths.length ? `已选目录（${targetPathList.length} 项）` : itemName({ path: options.currentPath || currentPath }))
    })
  }

  async function handleFilterDeleteDeleted() {
    setSelectedKeys(new Set())
    await refresh()
  }

  async function copyRowName(item) {
    const name = itemName(item)
    try {
      await window.navigator?.clipboard?.writeText(name)
      await showSystemAlert({ title: '已复制文件名', message: name, tone: 'success' })
    } catch (_error) {
      await showSystemAlert({ title: '复制失败', message: name, tone: 'warning' })
    }
  }

  function canAutoCircleGroupRow(row) {
    return Boolean(row?.path && canApiRenameRow(row) && !isRemoteCurrentLibrary && isWritableCurrentLibrary)
  }

  async function autoCircleGroup(row) {
    if (!canAutoCircleGroupRow(row)) {
      await showSystemAlert({ title: '当前行无法按社团分类', tone: 'warning' })
      return
    }
    if (autoCircleGroupRunningId) return
    const runningId = rowKey(row)
    setAutoCircleGroupRunningId(runningId)
    setBusy(true)
    try {
      let workingPath = row.path
      let data = await libraryApi.autoCircleGroup(libraryId || null, workingPath)
      if (data?.need_api_rename) {
        await showSystemAlert({ title: '先执行 API 重命名', message: '未识别到社团前缀，已自动进入 API 重命名后重试。', tone: 'info' })
        const renameData = await libraryApi.apiRename(workingPath, libraryId || null)
        const nextPath = String(renameData?.path || '').trim()
        if (!nextPath) throw new Error('API 重命名后未拿到新路径')
        workingPath = nextPath
        data = await libraryApi.autoCircleGroup(libraryId || null, workingPath)
        if (data?.need_api_rename) throw new Error('API 重命名后仍未识别到社团前缀，请检查重命名模板')
      }

      await refresh()
      await showSystemAlert({
        title: data?.skipped ? '无需移动' : '社团分类完成',
        message: data?.message || (data?.safe_circle_name ? `已移动到社团：${data.safe_circle_name}` : ''),
        tone: data?.skipped ? 'info' : 'success'
      })
    } finally {
      setAutoCircleGroupRunningId('')
      setBusy(false)
    }
  }

  function canUploadRow(row) {
    return Boolean(row?.path && !isRemoteCurrentLibrary && remoteUploadLibraries.length)
  }

  function openLocalUploadDialog(rowsForUpload = selectedUploadRows) {
    const uploadRows = (Array.isArray(rowsForUpload) ? rowsForUpload : [rowsForUpload]).filter(row => row?.path)
    if (isRemoteCurrentLibrary) {
      showSystemAlert({ title: '请先切换到本地库存', message: '远程库存不能作为本地上传源。', tone: 'warning' })
      return
    }
    if (!remoteUploadLibraries.length) {
      showSystemAlert({ title: '没有可用的服务器库存', message: '请先在设置里配置群晖库存。', tone: 'warning' })
      return
    }
    if (!uploadRows.length) {
      showSystemAlert({ title: '请选择要上传的条目', tone: 'warning' })
      return
    }
    setLocalUploadState({ visible: true, rows: uploadRows })
  }

  async function submitLocalUpload({ selectedPaths, targetLibraryId, targetSubdir }) {
    const paths = (selectedPaths || []).filter(Boolean)
    if (!paths.length || !targetLibraryId) return
    setLocalUploadSubmitting(true)
    try {
      const createdTaskIds = []
      const sourceBasePath = currentPath || currentLibrary?.path || currentLibrary?.root_path || ''
      for (const selectedPath of paths) {
        const result = await localUploadApi.start({
          source_library_id: libraryId,
          source_base_path: sourceBasePath,
          selected_paths: [selectedPath],
          target_library_id: targetLibraryId,
          target_subdir: targetSubdir || '',
          circle_name: ''
        })
        if (result?.task_id) createdTaskIds.push(result.task_id)
      }
      if (createdTaskIds.length) {
        setTrackedUploadTaskIds(prev => [...new Set([...prev, ...createdTaskIds])])
      }
      setUploadWorkbenchVisible(true)
      setUploadBackgroundActive(false)
      setLocalUploadState({ visible: false, rows: [] })
      setSelectedKeys(new Set())
      await refreshUploadWorkbench({ taskIds: createdTaskIds, silent: true })
      await showSystemAlert({ title: '上传任务已创建', message: `已创建 ${createdTaskIds.length || paths.length} 个上传任务。`, tone: 'success' })
    } finally {
      setLocalUploadSubmitting(false)
    }
  }

  async function refreshUploadWorkbench(options = {}) {
    const taskIds = options.taskIds || trackedUploadTaskIds
    if (!taskIds.length) return
    if (!options.silent) setUploadRefreshing(true)
    try {
      const data = await localUploadApi.status({
        task_ids: taskIds.join(','),
        include_hidden: true
      })
      setUploadTasks(normalizeListPayload(data))
    } finally {
      if (!options.silent) setUploadRefreshing(false)
    }
  }

  async function handleUploadTaskAction(action, taskId) {
    if (!taskId) return
    if (action === 'pause') await taskApi.pause(taskId)
    if (action === 'resume') await taskApi.resume(taskId)
    if (action === 'cancel') await taskApi.cancel(taskId)
    await refreshUploadWorkbench()
  }

  async function refreshSubtitleStatus(options = {}) {
    if (!options.silent) setSubtitleRefreshing(true)
    try {
      const data = await rjSubtitleApi.status()
      setSubtitleStatus(data)
      return data
    } finally {
      if (!options.silent) setSubtitleRefreshing(false)
    }
  }

  async function openSubtitleTaskPanel() {
    setSubtitlePanelVisible(true)
    await refreshSubtitleStatus({ silent: true })
  }

  async function handleSubtitleTaskAction(action, taskId) {
    if (!taskId) return
    if (action === 'rerun') await rjSubtitleApi.rerunTask(taskId)
    if (action === 'cancel') await rjSubtitleApi.cancel(taskId)
    if (action === 'clear') await rjSubtitleApi.clearTask(taskId)
    await refreshSubtitleStatus()
  }

  function openContextMenu(item, event) {
    event?.preventDefault?.()
    event?.stopPropagation?.()
    if (!item) return

    const key = rowKey(item)
    const rowIsSelected = selectedKeys.has(key)
    const batchMode = rowIsSelected && selectedKeys.size > 1
    if (!rowIsSelected) {
      setSelectedKeys(new Set([key]))
      setLastSelectedKey(key)
    }

    setContextMenu({
      visible: true,
      row: item,
      x: event?.clientX || 0,
      y: event?.clientY || 0,
      batchMode
    })
  }

  async function handleContextAction(action) {
    const row = contextMenu.row
    const batchMode = contextMenu.batchMode
    const actionRows = batchMode ? selectedRows : [row].filter(Boolean)
    setContextMenu(current => ({ ...current, visible: false }))

    if (action === 'view') return viewRow(row)
    if (action === 'open') return isDirectory(row) ? openRow(row) : openFolderInSystem(row)
    if (action === 'copy_name') return copyRowName(row)
    if (action === 'rename') return rename(row)
    if (action === 'move') return openMoveDialog(actionRows)
    if (action === 'upload') return openLocalUploadDialog(actionRows)
    if (action === 'api_rename') return batchMode ? batchApiRename() : apiRename(row)
    if (action === 'auto_circle_group') return autoCircleGroup(row)
    if (action === 'subtitle') return startRJSubtitle(batchMode ? selectedSubtitleRows : [row])
    if (action === 'manage') return openFolderContents(row)
    if (action === 'compute_size') return batchMode ? computeSelectedFolderSize() : computeFolderSize(row)
    if (action === 'filter_delete') return openFilterDeleteDialog(selectedRows)
    if (action === 'delete') return removeRows(actionRows)
  }

  async function rebuildIndex() {
    if (!libraryId) return
    await showSystemConfirm({
      title: '重建搜索索引',
      message: `即将重建「${currentLibrary?.name || libraryId}」的库存搜索索引。远程库可能耗时较久。`,
      confirmText: '开始重建',
      tone: 'warning'
    })
    const data = await libraryApi.rebuildIndex(libraryId)
    setIndexStatus(data)
    await showSystemAlert({ title: '索引重建已启动', tone: 'success' })
  }

  async function handleStatsAction() {
    if (!libraryId) return
    if (canCancelStats) {
      setStatsLoading(true)
      try {
        const data = await libraryApi.cancelStats(libraryId)
        await showSystemAlert({ title: '统计任务已取消', message: data?.message || '', tone: 'success' })
        await loadStats(false, libraryId)
      } finally {
        setStatsLoading(false)
      }
      return
    }
    await loadStats(true, libraryId)
  }

  function openMoveDialog(items) {
    const nextItems = items.filter(Boolean)
    if (!nextItems.length) return
    setMoveItems(nextItems)
    setMoveOpen(true)
  }

  function canDropMove(target, sourceItems = dragState.items) {
    if (!isDirectory(target) || !sourceItems.length) return false
    return canDropMoveToPath(target.path || '', sourceItems)
  }

  function canDropMoveToPath(targetPathValue, sourceItems = dragState.items) {
    if (!sourceItems.length) return false
    const targetPath = normalizePath(targetPathValue || '')
    return sourceItems.every(item => {
      const sourcePath = normalizePath(item.path || '')
      return sourcePath && sourcePath !== targetPath && (!targetPath || !targetPath.startsWith(`${sourcePath}/`))
    })
  }

  function handleDragStart(item, event) {
    const key = rowKey(item)
    const sourceItems = selectedKeys.has(key) && selectedRows.length > 1 ? selectedRows : [item]
    setDragState({ items: sourceItems, targetKey: '', targetPath: '' })
    if (!selectedKeys.has(key)) {
      setSelectedKeys(new Set([key]))
      setLastSelectedKey(key)
    }
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', sourceItems.map(row => row.path).join('\n'))
  }

  function handleDragOverRow(target, event) {
    if (!canDropMove(target)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setDragState(state => state.targetKey === rowKey(target)
      ? state
      : { ...state, targetKey: rowKey(target), targetPath: target.path || '' })
  }

  async function handleDropOnRow(target, event) {
    event.preventDefault()
    const sourceItems = dragState.items
    setDragState({ items: [], targetKey: '', targetPath: '' })
    if (!canDropMove(target, sourceItems)) return
    await showSystemConfirm({
      title: '拖拽移动',
      message: `将 ${sourceItems.length} 项移动到目标目录。`,
      currentValue: `${sourceItems.map(row => row.path).join('\n')}\n\n=> ${target.path}`,
      inputType: 'textarea',
      confirmText: '确认移动',
      tone: 'warning',
      width: 620
    })
    setBusy(true)
    try {
      await libraryApi.browserMove(libraryId, sourceItems.map(row => row.path), libraryId, target.path, { conflictStrategy: 'suffix' })
      setSelectedKeys(new Set())
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  function handleDragOverCrumb(crumb, event) {
    if (!canDropMoveToPath(crumb.path || '')) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setDragState(state => state.targetKey === `crumb:${crumb.path || ''}`
      ? state
      : { ...state, targetKey: `crumb:${crumb.path || ''}`, targetPath: crumb.path || '' })
  }

  async function handleDropOnCrumb(crumb, event) {
    event.preventDefault()
    const sourceItems = dragState.items
    const targetPath = crumb.path || ''
    setDragState({ items: [], targetKey: '', targetPath: '' })
    if (!canDropMoveToPath(targetPath, sourceItems)) return
    await showSystemConfirm({
      title: '拖拽移动',
      message: `将 ${sourceItems.length} 项移动到「${crumb.label}」。`,
      currentValue: `${sourceItems.map(row => row.path).join('\n')}\n\n=> ${targetPath || '根目录'}`,
      inputType: 'textarea',
      confirmText: '确认移动',
      tone: 'warning',
      width: 620
    })
    setBusy(true)
    try {
      await libraryApi.browserMove(libraryId, sourceItems.map(row => row.path), libraryId, targetPath, { conflictStrategy: 'suffix' })
      setSelectedKeys(new Set())
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  function handleDragEnd() {
    setDragState({ items: [], targetKey: '', targetPath: '' })
  }

  async function submitMove({ targetLibraryId, targetPath, conflictStrategy = 'suffix' }) {
    setBusy(true)
    try {
      await libraryApi.browserMove(libraryId, moveItems.map(row => row.path), targetLibraryId, targetPath, { conflictStrategy })
      setMoveOpen(false)
      setMoveItems([])
      setSelectedKeys(new Set())
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  function handlePageChange(nextPage) {
    const safe = Math.min(Math.max(nextPage, 1), pageCount)
    refresh({ page: safe })
  }

  useEffect(() => {
    function handleKeydown(event) {
      const tagName = String(event.target?.tagName || '').toUpperCase()
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || event.target?.isContentEditable) return
      if ((event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 'a') {
        event.preventDefault()
        togglePageSelected(true)
      }
      if (event.key === 'Escape') {
        setContextMenu(current => ({ ...current, visible: false }))
        setPreviewState(current => ({ ...current, visible: false }))
      }
    }
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [rows])

  return (
    <div className="km-page library-workbench-page">
      <PageHeader
        eyebrow="库存主工作台"
        title="库存管理"
        description="浏览库存、搜索作品、批量选择、移动、删除、命名和维护索引。"
        actions={
          <>
            <LibraryIndexBadge status={indexStatus} currentLibrary={currentLibrary} onRebuild={rebuildIndex} disabled={!libraryId} />
            <Button variant="primary" onClick={() => refresh({ forceRefresh: true })}><RefreshCcw size={16} />刷新</Button>
          </>
        }
      />

      <LibraryStatsStrip
        currentLibrary={currentLibrary}
        currentStats={currentStats}
        aggregateStats={aggregateStats}
        statsLoading={statsLoading}
        canCancelStats={canCancelStats}
        onStatsAction={handleStatsAction}
      />

      <LibraryToolbar
        libraries={libraries}
        libraryId={libraryId}
        search={search}
        searchKind={searchKind}
        currentPath={currentPath}
        searchLibraryIds={[]}
        onLibraryChange={changeLibrary}
        onSearchChange={setSearch}
        onSearchKindChange={setSearchKind}
        onLocateSearchResult={locateSearchResult}
        onOpenSearchOverlay={payload => setSearchOverlay({
          visible: true,
          keyword: payload?.keyword || search,
          kindFilter: payload?.kindFilter || searchKind
        })}
        onFilterDelete={openToolbarFilterDeleteDialog}
        onGoUp={goUp}
      />

      <LibraryBreadcrumbBar
        breadcrumbs={breadcrumbs}
        stats={currentStats}
        dragState={dragState}
        onNavigate={path => { setCurrentPath(path); setPage(1); setLocatedPath('') }}
        onDragOverCrumb={handleDragOverCrumb}
        onDropOnCrumb={handleDropOnCrumb}
        onDragEnd={handleDragEnd}
      />

      <LibraryActionScopeBar
        scope={toolbarActionScope}
        selectedCount={selectedRows.length}
        subtitleCount={toolbarSubtitleRows.length}
        filterDeleteCount={toolbarFilterDeletePaths.length}
        uploadCount={selectedUploadRows.length}
        canSubtitle={isWritableCurrentLibrary && toolbarSubtitleRows.length > 0}
        canFilterDelete={isWritableCurrentLibrary && toolbarFilterDeletePaths.length > 0}
        canUpload={!isRemoteCurrentLibrary && remoteUploadLibraries.length > 0}
        onScopeChange={setToolbarActionScope}
        onSubtitle={startToolbarRJSubtitle}
        onFilterDelete={openToolbarFilterDeleteDialog}
        onOpenSubtitleTasks={openSubtitleTaskPanel}
        onUpload={() => openLocalUploadDialog(selectedUploadRows)}
      />

      <LibraryBatchBar
        selectedRows={selectedRows}
        busy={busy}
        onMove={() => openMoveDialog(selectedRows)}
        onBatchSubtitle={() => startRJSubtitle(selectedSubtitleRows)}
        onBatchApiRename={batchApiRename}
        onFilterDelete={() => openFilterDeleteDialog(selectedRows)}
        onComputeFolderSize={computeSelectedFolderSize}
        onUpload={() => openLocalUploadDialog(selectedRows)}
        onBatchDelete={batchDelete}
        onClear={() => setSelectedKeys(new Set())}
      />

      <LibraryFileTable
        rows={rows}
        total={total}
        page={page}
        pageCount={pageCount}
        pageSize={pageSize}
        sortBy={sortBy}
        sortOrder={sortOrder}
        selectedKeys={selectedKeys}
        allPageSelected={allPageSelected}
        dragState={dragState}
        locatedPath={locatedPath}
        loading={loading}
        busy={busy}
        onToggleRow={toggleSelected}
        onTogglePage={togglePageSelected}
        onOpen={openRow}
        onRowSelect={selectRowByEvent}
        onView={viewRow}
        onRename={rename}
        onOpenFolder={openFolderInSystem}
        onApiRename={apiRename}
        onManage={openFolderContents}
        onMove={openMoveDialog}
        onRemove={remove}
        onOpenContextMenu={openContextMenu}
        onDragStart={handleDragStart}
        onDragOverRow={handleDragOverRow}
        onDropOnRow={handleDropOnRow}
        onDragEnd={handleDragEnd}
        onMarqueeSelect={selectRowsByMarquee}
        onSortByChange={setSortBy}
        onSortOrderToggle={() => setSortOrder(value => value === 'desc' ? 'asc' : 'desc')}
        onPageChange={handlePageChange}
        onPageSizeChange={setPageSize}
      />

      <LibraryContextMenu
        state={contextMenu}
        selectedCount={selectedRows.length}
        selectedRows={selectedRows}
        busy={busy}
        canAutoCircleGroup={canAutoCircleGroupRow}
        autoCircleGroupRunning={Boolean(autoCircleGroupRunningId)}
        canUpload={canUploadRow}
        selectedUploadCount={selectedUploadRows.length}
        canSubtitle={canSubtitleRow}
        selectedSubtitleCount={selectedSubtitleRows.length}
        selectedFilterDeleteCount={selectedRows.filter(isDirectory).length}
        onClose={() => setContextMenu(current => ({ ...current, visible: false }))}
        onAction={handleContextAction}
      />

      <LibraryMediaPreview
        state={previewState}
        libraryId={libraryId}
        imageRows={imageRows}
        onSwitchImage={item => setPreviewState({ visible: true, item })}
        onClose={() => setPreviewState({ visible: false, item: null })}
      />

      {folderDialogState.visible ? (
        <LibraryFolderContentsDialog
          libraryId={libraryId}
          folderPath={folderDialogState.path}
          folderName={folderDialogState.name}
          onClose={() => setFolderDialogState({ visible: false, path: '', name: '' })}
          onMutated={async () => refresh()}
        />
      ) : null}

      {filterDeleteState.visible ? (
        <LibraryFilterDeleteDialog
          libraryId={libraryId}
          currentPath={filterDeleteState.currentPath}
          targetPaths={filterDeleteState.targetPaths}
          scopeLabel={filterDeleteState.scopeLabel}
          onClose={() => setFilterDeleteState({ visible: false, currentPath: '', targetPaths: [], scopeLabel: '' })}
          onDeleted={handleFilterDeleteDeleted}
        />
      ) : null}

      {moveOpen ? (
        <LibraryMoveDialog
          libraries={libraries}
          sourceLibraryId={libraryId}
          initialPath={currentPath}
          items={moveItems}
          submitting={busy}
          onClose={() => setMoveOpen(false)}
          onSubmit={submitMove}
        />
      ) : null}

      <LibrarySearchOverlay
        visible={searchOverlay.visible}
        initialKeyword={searchOverlay.keyword}
        initialKindFilter={searchOverlay.kindFilter}
        libraries={libraries}
        onLocate={locateSearchResult}
        onClose={() => setSearchOverlay(current => ({ ...current, visible: false }))}
      />

      {localUploadState.visible ? (
        <LibraryLocalUploadDialog
          libraries={libraries}
          sourceRows={localUploadState.rows}
          sourceLibraryId={libraryId}
          sourceLibraryName={currentLibrary?.name || ''}
          initialTargetLibraryId={remoteUploadLibraries[0]?.id || ''}
          submitting={localUploadSubmitting}
          onClose={() => setLocalUploadState({ visible: false, rows: [] })}
          onSubmit={submitLocalUpload}
        />
      ) : null}

      <LibraryUploadTaskWorkbenchDialog
        visible={uploadWorkbenchVisible}
        tasks={uploadTasks}
        refreshing={uploadRefreshing}
        onClose={() => setUploadWorkbenchVisible(false)}
        onBackground={() => {
          setUploadWorkbenchVisible(false)
          setUploadBackgroundActive(true)
        }}
        onRefresh={() => refreshUploadWorkbench()}
        onPause={taskId => handleUploadTaskAction('pause', taskId)}
        onResume={taskId => handleUploadTaskAction('resume', taskId)}
        onCancel={taskId => handleUploadTaskAction('cancel', taskId)}
      />

      {uploadBackgroundActive ? (
        <LibraryUploadBackgroundCard
          tasks={uploadTasks}
          onOpen={() => {
            setUploadBackgroundActive(false)
            setUploadWorkbenchVisible(true)
          }}
          onDismiss={() => setUploadBackgroundActive(false)}
        />
      ) : null}

      <LibrarySubtitleTaskPanel
        visible={subtitlePanelVisible}
        status={subtitleStatus}
        refreshing={subtitleRefreshing}
        fallbackLibraryId={libraryId}
        onClose={() => setSubtitlePanelVisible(false)}
        onRefresh={() => refreshSubtitleStatus()}
        onRerun={taskId => handleSubtitleTaskAction('rerun', taskId)}
        onCancel={taskId => handleSubtitleTaskAction('cancel', taskId)}
        onClear={taskId => handleSubtitleTaskAction('clear', taskId)}
      />
    </div>
  )
}

async function runLimited(items, limit, worker) {
  const results = new Array(items.length)
  let cursor = 0
  async function next() {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      try {
        results[index] = { status: 'fulfilled', value: await worker(items[index], index) }
      } catch (error) {
        results[index] = { status: 'rejected', reason: error }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, next))
  return results
}

function resolveCurrentStats(stats, libraryId) {
  if (!stats) return null
  if (Array.isArray(stats.libraries)) {
    return stats.libraries.find(item => String(item.library_id || item.id || '') === String(libraryId || '')) || null
  }
  if (stats.library_id || stats.total_size || stats.total_size_bytes || stats.folder_count) return stats
  return null
}
