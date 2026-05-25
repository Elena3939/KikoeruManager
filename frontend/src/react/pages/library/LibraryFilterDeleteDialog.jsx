import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, FilterX, RefreshCcw, Search, Trash2, XCircle } from 'lucide-react'
import { libraryApi } from '../../../api'
import { Button, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { showSystemConfirm } from '../../stores/systemPromptStore'
import { formatBytes, formatDateTime } from '../../utils/format'
import { LibraryFileIcon } from './LibraryFileIcon'
import { itemName, normalizePath } from './libraryUtils'

export function LibraryFilterDeleteDialog({
  libraryId,
  currentPath,
  targetPaths,
  scopeLabel,
  rules,
  onClose,
  onDeleted
}) {
  const [rows, setRows] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [statusText, setStatusText] = useState('等待预审')
  const [minimized, setMinimized] = useState(false)
  const [jobMeta, setJobMeta] = useState({ jobId: '', path: '', status: '', progressMessage: '', currentPath: '', discoveredEntries: 0, percentage: 0 })
  const [startedAt, setStartedAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const cancelRequestedRef = useRef(false)

  const filteredRows = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    if (!query) return rows
    return rows.filter(row => `${row.name} ${row.relative_path} ${row.path} ${row.matched_rules?.join(' ') || ''}`.toLowerCase().includes(query))
  }, [rows, keyword])
  const selectableRows = useMemo(() => rows.filter(row => row.selectable !== false), [rows])
  const selectedRows = useMemo(() => selectableRows.filter(row => selected.has(row.id)), [selectableRows, selected])
  const selectedSize = useMemo(() => selectedRows.reduce((sum, row) => sum + Number(row.size || 0), 0), [selectedRows])
  const allFilteredSelectable = filteredRows.filter(row => row.selectable !== false)
  const allVisibleSelected = allFilteredSelectable.length > 0 && allFilteredSelectable.every(row => selected.has(row.id))
  const progressPercent = Math.max(0, Math.min(100, Number(jobMeta.percentage || (loading ? 12 : rows.length ? 100 : 0))))
  const elapsedText = startedAt ? formatElapsedSeconds((now - startedAt) / 1000) : '0 秒'

  useEffect(() => {
    if (!loading && !minimized) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [loading, minimized])

  async function reload() {
    if (!libraryId) return
    const paths = [...new Set((targetPaths?.length ? targetPaths : [currentPath]).map(path => String(path || '').trim()).filter(Boolean))]
    if (!paths.length) return
    setLoading(true)
    setMinimized(false)
    setStartedAt(Date.now())
    setNow(Date.now())
    cancelRequestedRef.current = false
    setStatusText('正在生成删除预审...')
    try {
      const collected = []
      for (const path of paths) {
        if (cancelRequestedRef.current) break
        const preview = await runPreviewJob(libraryId, path, rules, {
          onProgress: setStatusText,
          onJob: meta => setJobMeta(current => ({ ...current, ...meta })),
          onStatus: meta => setJobMeta(current => ({ ...current, ...meta })),
          shouldCancel: () => cancelRequestedRef.current
        })
        const items = Array.isArray(preview?.items) ? preview.items : []
        items.forEach((item, index) => {
          const normalizedPath = normalizePath(item.path || `${path}/${item.relative_path || item.name || index}`)
          collected.push({
            ...item,
            id: `${normalizedPath}:${index}`,
            path: normalizedPath,
            name: item.name || itemName({ path: item.relative_path || normalizedPath }),
            relative_path: item.relative_path || relativeFromBase(preview?.folder_path || path, normalizedPath),
            preview_root: preview?.folder_path || path,
            preview_folder_name: preview?.folder_name || itemName({ path }),
            type: item.type || item.item_type || 'file',
            selectable: item.selectable !== false && !item.covered_by
          })
        })
      }
      setRows(collected)
      setSelected(new Set(collected.filter(row => row.selectable !== false).map(row => row.id)))
      if (!cancelRequestedRef.current) {
        setStatusText(collected.length ? `预审完成，命中 ${collected.length} 项` : '预审完成，没有命中过滤规则')
      }
    } catch (error) {
      if (cancelRequestedRef.current || /已取消/.test(String(error?.message || ''))) {
        setStatusText('删除过滤预审已取消')
      } else {
        setStatusText(error?.response?.data?.detail || error?.message || '删除过滤预审失败')
      }
    } finally {
      setLoading(false)
      setJobMeta(current => ({ ...current, jobId: '', status: cancelRequestedRef.current ? 'canceled' : current.status }))
    }
  }

  useEffect(() => {
    reload()
  }, [libraryId, currentPath, JSON.stringify(targetPaths || []), JSON.stringify(rules || [])])

  function toggleRow(row, checked) {
    if (row.selectable === false) return
    setSelected(prev => {
      const next = new Set(prev)
      if (checked) next.add(row.id)
      else next.delete(row.id)
      return next
    })
  }

  function toggleVisible() {
    const shouldSelect = !allVisibleSelected
    setSelected(prev => {
      const next = new Set(prev)
      allFilteredSelectable.forEach(row => {
        if (shouldSelect) next.add(row.id)
        else next.delete(row.id)
      })
      return next
    })
  }

  async function deleteSelected() {
    const paths = selectedRows.map(row => row.path).filter(Boolean)
    if (!paths.length) return
    await showSystemConfirm({
      title: '确认删除过滤文件',
      message: [`将删除 ${paths.length} 个过滤命中项`, `预计释放：${formatBytes(selectedSize)}`, '此操作会直接作用到库存路径。'].join('\n'),
      currentValue: paths.join('\n'),
      inputType: 'textarea',
      confirmText: '确认删除',
      tone: 'danger',
      width: 620
    })
    setDeleting(true)
    try {
      await libraryApi.browserBatchDelete(libraryId, paths, true)
      const deletedIds = new Set(selectedRows.map(row => row.id))
      setRows(current => current.filter(row => !deletedIds.has(row.id)))
      setSelected(prev => {
        const next = new Set(prev)
        deletedIds.forEach(id => next.delete(id))
        return next
      })
      setStatusText(`已删除 ${paths.length} 个过滤命中项`)
      await onDeleted?.({ deletedBytes: selectedSize, deletedFolderCount: selectedRows.filter(row => row.type === 'dir').length })
    } finally {
      setDeleting(false)
    }
  }

  async function cancelPreview() {
    cancelRequestedRef.current = true
    if (jobMeta.jobId) {
      await libraryApi.cancelFilterDeletePreview({ jobId: jobMeta.jobId }).catch(() => null)
    }
    setLoading(false)
    setMinimized(false)
    setStatusText('删除过滤预审已取消')
  }

  if (minimized) {
    return (
      <div className="library-filter-background-card">
        <div>
          <FilterX size={18} />
          <span>
            <b>删除过滤预审</b>
            <small>{statusText} · {elapsedText}</small>
          </span>
          <i style={{ '--filter-delete-percent': `${progressPercent}%` }} />
        </div>
        <button type="button" onClick={() => setMinimized(false)}>恢复审阅</button>
        <button type="button" onClick={cancelPreview}><XCircle size={15} /></button>
      </div>
    )
  }

  return (
    <Modal
      title={`删除过滤预审 · ${scopeLabel || itemName({ path: currentPath })}`}
      width={1120}
      onClose={() => { if (loading) setMinimized(true); else onClose?.() }}
      footer={
        <>
          <Button onClick={reload} disabled={loading}><RefreshCcw size={15} />重新预审</Button>
          {loading ? <Button onClick={() => setMinimized(true)}><FilterX size={15} />后台扫描</Button> : null}
          {loading ? <Button variant="danger" onClick={cancelPreview}><XCircle size={15} />取消扫描</Button> : null}
          <Button variant="danger" loading={deleting} disabled={!selectedRows.length || loading} onClick={deleteSelected}><Trash2 size={15} />删除选中</Button>
          <Button onClick={() => { if (loading) setMinimized(true); else onClose?.() }}>关闭</Button>
        </>
      }
    >
      <div className="library-filter-dialog">
        <div className="library-filter-alert">
          <FilterX size={16} />
          <span>这里是预审结果，取消勾选后不会删除；确认删除前不会改动库存文件。</span>
        </div>
        <div className="library-filter-summary">
          <span>{statusText}</span>
          <em>已选 {selectedRows.length} / 可选 {selectableRows.length} · {formatBytes(selectedSize)} · 已运行 {elapsedText}</em>
        </div>
        {(loading || jobMeta.currentPath || jobMeta.discoveredEntries) ? (
          <div className="library-filter-progress">
            <span><i style={{ width: `${progressPercent}%` }} /></span>
            <em>{Math.round(progressPercent)}%</em>
            <small>{jobMeta.currentPath || jobMeta.path || ''}{jobMeta.discoveredEntries ? ` · 已发现 ${jobMeta.discoveredEntries} 项` : ''}</small>
          </div>
        ) : null}
        <div className="library-folder-toolbar">
          <label className="library-folder-search">
            <Search size={15} />
            <TextInput value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="搜索命中项 / 规则 / 路径..." />
          </label>
          <Button size="sm" disabled={!allFilteredSelectable.length || loading} onClick={toggleVisible}>
            <Check size={15} />
            {allVisibleSelected ? '取消可见' : '选择可见'}
          </Button>
        </div>
        <div className="library-filter-list">
          <div className="library-filter-head">
            <span />
            <span>命中项</span>
            <span>规则</span>
            <span>大小</span>
            <span>修改时间</span>
          </div>
          {loading ? <LoadingState label="正在生成删除预审..." /> : null}
          {!loading && !filteredRows.length ? <div className="km-empty"><strong>{keyword ? '没有匹配项' : '没有命中过滤规则'}</strong></div> : null}
          {!loading && filteredRows.map(row => (
            <label key={row.id} className={`library-filter-row ${row.selectable === false ? 'is-covered' : ''}`}>
              <input
                type="checkbox"
                checked={selected.has(row.id)}
                disabled={row.selectable === false}
                onChange={event => toggleRow(row, event.target.checked)}
              />
              <span className="library-filter-name-cell" title={row.path}>
                <LibraryFileIcon item={{ ...row, is_directory: row.type === 'dir' }} />
                <b>{row.name}</b>
                <small>{row.preview_folder_name} / {row.relative_path}</small>
              </span>
              <em>{Array.isArray(row.matched_rules) && row.matched_rules.length ? row.matched_rules.join('、') : row.covered_by ? '由上级目录覆盖' : '-'}</em>
              <em>{formatBytes(row.size)}</em>
              <time>{formatDateTime(row.modified_time || row.modified)}</time>
            </label>
          ))}
        </div>
      </div>
    </Modal>
  )
}

async function runPreviewJob(libraryId, path, rules, options = {}) {
  const initial = await libraryApi.startFilterDeletePreviewJob(libraryId, path, { rules })
  options.onJob?.({
    jobId: initial?.job_id || '',
    path,
    status: initial?.status || '',
    progressMessage: initial?.progress_message || '',
    currentPath: initial?.current_path || '',
    discoveredEntries: Number(initial?.discovered_entries || initial?.total_items || 0),
    percentage: resolvePreviewProgressPercent(initial)
  })
  if (!initial?.job_id || ['completed', 'error', 'failed', 'canceled'].includes(initial.status)) {
    if (initial?.status === 'error' || initial?.status === 'failed') throw new Error(initial.error || initial.warning || '删除过滤预审失败')
    return initial
  }

  let current = initial
  for (;;) {
    if (options.shouldCancel?.()) {
      await libraryApi.cancelFilterDeletePreview({ jobId: initial.job_id }).catch(() => null)
      throw new Error('删除过滤预审已取消')
    }
    options.onProgress?.(current.progress_message || `正在扫描 ${itemName({ path })}...`)
    options.onStatus?.({
      status: current.status || '',
      progressMessage: current.progress_message || '',
      currentPath: current.current_path || current.path || '',
      discoveredEntries: Number(current.discovered_entries || current.total_items || 0),
      percentage: resolvePreviewProgressPercent(current)
    })
    await delay(900)
    current = await libraryApi.getFilterDeletePreviewStatus(initial.job_id)
    if (['completed', 'error', 'failed', 'canceled'].includes(current.status)) break
  }
  options.onStatus?.({
    status: current.status || '',
    progressMessage: current.progress_message || '',
    currentPath: current.current_path || current.path || '',
    discoveredEntries: Number(current.discovered_entries || current.total_items || 0),
    percentage: resolvePreviewProgressPercent(current)
  })
  if (current.status === 'error' || current.status === 'failed') throw new Error(current.error || current.warning || '删除过滤预审失败')
  if (current.status === 'canceled') throw new Error('删除过滤预审已取消')
  return current
}

function relativeFromBase(base, path) {
  const normalizedBase = normalizePath(base)
  const normalizedPath = normalizePath(path)
  if (normalizedBase && normalizedPath.startsWith(`${normalizedBase}/`)) return normalizedPath.slice(normalizedBase.length + 1)
  return normalizedPath
}

function delay(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function resolvePreviewProgressPercent(payload = {}) {
  const direct = Number(payload.progress_percent ?? payload.percentage ?? payload.percent)
  if (Number.isFinite(direct) && direct > 0) return Math.max(0, Math.min(100, direct))
  const done = Number(payload.scanned_entries ?? payload.processed_entries ?? (payload.processed || 0))
  const total = Number(payload.total_entries ?? (payload.total || 0))
  if (total > 0) return Math.max(3, Math.min(98, (done / total) * 100))
  if (payload.status === 'completed') return 100
  return payload.status === 'running' || payload.status === 'processing' ? 24 : 0
}

function formatElapsedSeconds(value) {
  const seconds = Math.max(0, Math.floor(Number(value || 0)))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes < 60) return `${minutes} 分 ${rest} 秒`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}
