import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertCircle,
  Archive,
  Check,
  Cloud,
  CornerDownLeft,
  File,
  FileText,
  Filter,
  Folder,
  HardDrive,
  Image,
  Loader2,
  Music,
  RefreshCcw,
  Search,
  SearchX,
  Video,
  X
} from 'lucide-react'
import { libraryApi } from '../../../api'
import { formatBytes } from '../../utils/format'
import {
  applyLibraryFrontendFilter,
  classifyLibraryEntryKind,
  itemName,
  libraryFilterOptions,
  libraryFilterToEntryType
} from './libraryUtils'

const filterIconMap = {
  all: Search,
  dir: Folder,
  folder: Folder,
  file: File,
  audio: Music,
  image: Image,
  video: Video,
  archive: Archive,
  text: FileText
}

export function LibrarySearchOverlay({
  visible,
  initialKeyword = '',
  initialKindFilter = 'all',
  libraries = [],
  onLocate,
  onClose
}) {
  const inputRef = useRef(null)
  const filterButtonRef = useRef(null)
  const abortRef = useRef(null)
  const debounceRef = useRef(null)
  const requestRef = useRef(0)
  const [keyword, setKeyword] = useState(initialKeyword)
  const [kindFilter, setKindFilter] = useState(initialKindFilter || 'all')
  const [filterOpen, setFilterOpen] = useState(false)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [softError, setSoftError] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [elapsedMs, setElapsedMs] = useState(null)
  const [totalCount, setTotalCount] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [matchedRjcode, setMatchedRjcode] = useState('')
  const [libraryStatusMap, setLibraryStatusMap] = useState({})
  const [filterMenuStyle, setFilterMenuStyle] = useState({})

  const currentFilter = useMemo(
    () => libraryFilterOptions.find(option => option.value === kindFilter) || libraryFilterOptions[0],
    [kindFilter]
  )
  const FilterIcon = filterIconMap[currentFilter.value] || Search

  useEffect(() => {
    if (!visible) return undefined
    setKeyword(initialKeyword || '')
    setKindFilter(initialKindFilter || 'all')
    setFilterOpen(false)
    setItems([])
    setError('')
    setSoftError(false)
    setActiveIndex(-1)
    setElapsedMs(null)
    setTotalCount(0)
    setTruncated(false)
    setMatchedRjcode('')
    setLibraryStatusMap({})
    window.setTimeout(() => inputRef.current?.focus?.(), 0)
    if (String(initialKeyword || '').trim()) scheduleSearch(initialKeyword, true)
    return () => cleanup()
  }, [visible, initialKeyword, initialKindFilter])

  useEffect(() => {
    if (!visible) return undefined
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose?.()
      } else if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex(index => items.length ? (index + 1 + items.length) % items.length : -1)
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex(index => items.length ? (index <= 0 ? items.length - 1 : index - 1) : -1)
      } else if (event.key === 'Enter' && activeIndex >= 0 && items[activeIndex]) {
        event.preventDefault()
        selectItem(items[activeIndex])
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [visible, items, activeIndex])

  useEffect(() => {
    if (visible && keyword.trim()) scheduleSearch(keyword, true)
  }, [kindFilter])

  useEffect(() => {
    if (!visible || !filterOpen) return undefined
    updateFilterMenuPosition()
    function closeOnOutside(event) {
      const target = event.target
      if (!target?.closest) return
      if (target.closest('.lib-panel-filter') || target.closest('.lib-panel-filter-menu')) return
      setFilterOpen(false)
    }
    function reflow() {
      updateFilterMenuPosition()
    }
    document.addEventListener('mousedown', closeOnOutside, true)
    window.addEventListener('scroll', reflow, true)
    window.addEventListener('resize', reflow)
    return () => {
      document.removeEventListener('mousedown', closeOnOutside, true)
      window.removeEventListener('scroll', reflow, true)
      window.removeEventListener('resize', reflow)
    }
  }, [visible, filterOpen])

  function cleanup() {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    abortRef.current?.abort?.()
    abortRef.current = null
  }

  function scheduleSearch(nextKeyword = keyword, immediate = false) {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    const trimmed = String(nextKeyword || '').trim()
    if (!trimmed) {
      cleanup()
      setItems([])
      setError('')
      setTotalCount(0)
      setTruncated(false)
      setMatchedRjcode('')
      setLibraryStatusMap({})
      setLoading(false)
      return
    }
    const run = () => streamSearch(trimmed)
    if (immediate) run()
    else debounceRef.current = window.setTimeout(run, 280)
  }

  async function streamSearch(nextKeyword) {
    cleanup()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = requestRef.current + 1
    requestRef.current = requestId
    setLoading(true)
    setError('')
    setSoftError(false)
    setActiveIndex(-1)
    setTotalCount(0)
    setTruncated(false)
    setMatchedRjcode('')
    setLibraryStatusMap({})
    const nextItems = []
    const failedLibraries = new Set()
    const localStatusMap = {}

    try {
      for await (const event of libraryApi.searchIndexGlobalStream({
        keyword: nextKeyword,
        libraryIds: null,
        entryType: libraryFilterToEntryType(kindFilter),
        mode: 'full',
        limit: 240,
        signal: controller.signal
      })) {
        if (requestId !== requestRef.current) return
        if (event.type === 'initial' || event.type === 'library') {
          if (event.matched_rjcode) setMatchedRjcode(String(event.matched_rjcode || '').toUpperCase())
          const filtered = applyLibraryFrontendFilter(Array.isArray(event.items) ? event.items : [], {
            filter: kindFilter,
            keyword: nextKeyword,
            matchedRjcode: event.matched_rjcode
          })
          if (filtered.length) {
            nextItems.push(...filtered)
            const deduped = dedupeSearchItems(nextItems)
            setItems(deduped)
            setTotalCount(Number(event.total_count ?? event.total ?? deduped.length))
          }
          if (event.truncated !== undefined) setTruncated(Boolean(event.truncated))
          if (Array.isArray(event.library_status)) {
            for (const status of event.library_status) {
              if (status?.library_id) localStatusMap[status.library_id] = status
            }
            setLibraryStatusMap({ ...localStatusMap })
          }
          if (event.library_id && event.library_status) {
            localStatusMap[event.library_id] = event.library_status
            setLibraryStatusMap({ ...localStatusMap })
          }
          if (event.error && event.library_id) failedLibraries.add(event.library_name || event.library_id)
          if (event.error && !event.library_id) {
            setError(event.error.message ? `索引暂不可用：${event.error.message}` : '索引暂不可用')
            setSoftError(true)
          }
          if (Number.isFinite(Number(event.elapsed_ms))) setElapsedMs(Number(event.elapsed_ms))
        } else if (event.type === 'done') {
          if (Number.isFinite(Number(event.elapsed_ms))) setElapsedMs(Number(event.elapsed_ms))
          if (event.total_count !== undefined || event.total !== undefined) setTotalCount(Number(event.total_count ?? event.total ?? nextItems.length))
          if (event.truncated !== undefined) setTruncated(Boolean(event.truncated))
          if (event.matched_rjcode) setMatchedRjcode(String(event.matched_rjcode || '').toUpperCase())
          if (Array.isArray(event.library_status)) {
            const finalMap = {}
            for (const status of event.library_status) {
              if (status?.library_id) finalMap[status.library_id] = status
            }
            setLibraryStatusMap(finalMap)
          }
          if (failedLibraries.size && !error) {
            const sample = [...failedLibraries].slice(0, 2).join('、')
            setError(`部分库未能搜索：${sample}${failedLibraries.size > 2 ? ' 等' : ''}`)
            setSoftError(true)
          }
        }
      }
    } catch (err) {
      if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return
      if (requestId !== requestRef.current) return
      setError(err?.response?.data?.detail || err?.message || '跨库索引暂时连不上')
      setSoftError(false)
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }

  function selectItem(item) {
    if (!item) return
    onLocate?.(item)
  }

  function updateFilterMenuPosition() {
    const button = filterButtonRef.current
    if (!button) return
    const rect = button.getBoundingClientRect()
    const minWidth = 240
    const padding = 8
    let left = rect.left
    if (left + minWidth > window.innerWidth - padding) left = window.innerWidth - padding - minWidth
    if (left < padding) left = padding
    setFilterMenuStyle({
      left,
      top: rect.bottom + 8,
      minWidth
    })
  }

  function toggleFilterMenu() {
    setFilterOpen(value => {
      const next = !value
      if (!value) window.requestAnimationFrame(updateFilterMenuPosition)
      return next
    })
  }

  if (!visible) return null

  return (
    <>
      {createPortal(
        <div className="lib-search-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose?.() }}>
          <section className="lib-search-panel" onMouseDown={event => event.stopPropagation()}>
            <div className="lib-panel-input-row">
              <button
                ref={filterButtonRef}
                type="button"
                className={`lib-panel-filter ${kindFilter !== 'all' ? 'is-active' : ''} ${filterOpen ? 'is-open' : ''}`}
                title={`按文件类型筛选：${currentFilter.label}`}
                onClick={toggleFilterMenu}
              >
                <FilterIcon size={18} strokeWidth={2.4} />
                {kindFilter !== 'all' ? <span className="lib-panel-filter-dot" /> : null}
              </button>
          <input
            ref={inputRef}
            className="lib-panel-input"
            value={keyword}
            placeholder="跨库索引搜索 · 输入文件名或 RJ 号"
            spellCheck={false}
            onChange={event => {
              setKeyword(event.target.value)
              scheduleSearch(event.target.value)
            }}
          />
          {loading ? <Loader2 size={15} className="km-spin lib-panel-input-loader" /> : null}
          <button type="button" className="lib-panel-input-close" onClick={onClose} aria-label="关闭">
            <X size={15} />
          </button>
        </div>

        {keyword.trim() || error || loading ? (
          <div className="lib-panel-results">
            {error ? (
              <div className={`lib-panel-banner ${softError ? 'is-warning' : 'is-error'}`}>
                <AlertCircle size={14} />
                <span>{error}</span>
                <button type="button" onClick={() => scheduleSearch(keyword, true)}><RefreshCcw size={12} />重试</button>
              </div>
            ) : null}

            {items.length ? (
              <ul className="lib-panel-list">
                {items.map((item, index) => (
                  <li
                    key={`${item.library_id || ''}|${item.relative_path || item.path || index}`}
                    className={`lib-panel-row ${index === activeIndex ? 'is-active' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => selectItem(item)}
                    >
                      <span className="lib-panel-row-icon"><FolderOrFile item={item} /></span>
                      <div className="lib-panel-row-main">
                        <div className="lib-panel-row-title">
                          <span
                            className="lib-panel-row-name"
                            dangerouslySetInnerHTML={{ __html: renderHighlightedName(item, keyword) }}
                          />
                          {item.rjcode ? <span className="lib-panel-row-rj">{item.rjcode}</span> : null}
                        </div>
                      <div className="lib-panel-row-sub">
                        <span className={`lib-panel-row-lib ${item.library_type === 'synology_filestation' ? 'is-remote' : 'is-local'}`}>
                          {item.library_type === 'synology_filestation' ? <Cloud size={10} /> : <HardDrive size={10} />}
                          {item.library_name || item.library_id || '库存'}
                        </span>
                        <span className="lib-panel-row-path">{item.parent_path || item.relative_path || item.path || ''}</span>
                      </div>
                    </div>
                    <div className="lib-panel-row-meta">
                      {Number(item.size || 0) > 0 ? <span>{formatBytes(item.size)}</span> : null}
                      {index === activeIndex ? <CornerDownLeft size={12} /> : null}
                    </div>
                  </li>
                ))}
              </ul>
            ) : loading ? (
              <div className="lib-panel-state"><Loader2 size={16} className="km-spin" />查询索引中...</div>
            ) : keyword.trim() && !error ? (
              <div className="lib-panel-state"><SearchX size={16} />没找到 “{keyword.trim()}”</div>
            ) : null}
            {Object.keys(libraryStatusMap).length ? (
              <div className="lib-panel-status-row">
                {Object.values(libraryStatusMap).slice(0, 6).map(status => (
                  <span key={status.library_id || status.library_name} className={`is-${status.search_mode || status.index_status || 'unknown'}`}>
                    {status.library_name || status.library_id}
                    <em>{summarizeIndexStatus(status)}</em>
                  </span>
                ))}
                {Object.keys(libraryStatusMap).length > 6 ? <span>+{Object.keys(libraryStatusMap).length - 6} 库</span> : null}
              </div>
            ) : null}
            <div className="lib-panel-foot">
              <span>{items.length ? `已显示 ${items.length} / ${totalCount || items.length} 项` : '输入后开始搜索'}</span>
              {matchedRjcode ? <span>RJ 命中 {matchedRjcode}</span> : null}
              {truncated ? <span>结果已截断</span> : null}
              {elapsedMs !== null ? <span>{elapsedMs} ms</span> : null}
            </div>
          </div>
        ) : null}
      </section>
    </div>,
        document.body
      )}
      {filterOpen ? createPortal(
        <div
          className="lib-panel-filter-menu"
          style={{
            left: filterMenuStyle.left,
            top: filterMenuStyle.top,
            minWidth: filterMenuStyle.minWidth
          }}
          onMouseDown={event => event.preventDefault()}
        >
          <header className="lib-panel-filter-menu-head"><Filter size={12} />按文件类型筛选</header>
          <ul className="lib-panel-filter-menu-list">
            {libraryFilterOptions.map(option => {
              const Icon = filterIconMap[option.value] || File
              return (
                <li
                  key={option.value}
                  className={`lib-panel-filter-menu-row ${kindFilter === option.value ? 'is-active' : ''}`}
                  onClick={() => {
                    setKindFilter(option.value)
                    setFilterOpen(false)
                    inputRef.current?.focus?.()
                  }}
                >
                  <Icon size={15} />
                  <span>{option.label}</span>
                  {kindFilter === option.value ? <Check size={14} /> : null}
                </li>
              )
            })}
          </ul>
        </div>,
        document.body
      ) : null}
    </>
  )
}

function FolderOrFile({ item }) {
  const kind = classifyLibraryEntryKind({
    ...item,
    is_directory: item?.is_directory ?? item?.entry_type === 'dir'
  })
  const Icon = filterIconMap[kind] || (String(item?.entry_type || '').toLowerCase() === 'file' ? File : Folder)
  return <Icon size={16} strokeWidth={2.2} />
}

function dedupeSearchItems(items) {
  const seen = new Set()
  const result = []
  for (const item of items) {
    const key = `${item.library_id || ''}|${item.absolute_path || item.path || item.relative_path || item.name || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(item)
  }
  return result
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderHighlightedName(item, keyword) {
  const safe = escapeHtml(item?.name || itemName(item))
  const query = String(keyword || '').trim()
  if (!query) return safe
  const pattern = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  try {
    return safe.replace(new RegExp(pattern, 'ig'), match => `<mark>${match}</mark>`)
  } catch (_) {
    return safe
  }
}

function summarizeIndexStatus(status) {
  const mode = String(status?.search_mode || '').trim()
  const index = String(status?.index_status || '').trim()
  if (mode === 'fallback_failed') return '兜底失败'
  if (mode === 'fallback') return '兜底'
  if (mode === 'index') return '索引'
  if (index === 'ready') return '索引就绪'
  if (index === 'syncing') return '同步中'
  if (index === 'error') return '索引异常'
  return index || mode || '未知'
}
