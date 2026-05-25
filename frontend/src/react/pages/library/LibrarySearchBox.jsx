import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Archive,
  Check,
  File,
  FileText,
  Folder,
  Image,
  Loader2,
  Maximize2,
  Music,
  Search,
  Video,
  X
} from 'lucide-react'
import { libraryApi } from '../../../api'
import {
  applyLibraryFrontendFilter,
  isIndexEntryDirectory,
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

export function LibrarySearchBox({
  value,
  libraryIds,
  kindFilter = 'all',
  onChange,
  onKindFilterChange,
  onLocate,
  onOpenOverlay,
  placeholder = '搜索文件名或 RJ 号 · 默认跨库索引'
}) {
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const abortRef = useRef(null)
  const debounceRef = useRef(null)
  const requestRef = useRef(0)
  const [open, setOpen] = useState(false)
  const [filterOpen, setFilterOpen] = useState(false)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [softError, setSoftError] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [elapsedMs, setElapsedMs] = useState(null)

  const keyword = String(value || '')
  const currentFilter = useMemo(
    () => libraryFilterOptions.find(option => option.value === kindFilter) || libraryFilterOptions[0],
    [kindFilter]
  )
  const FilterIcon = filterIconMap[currentFilter.value] || Search

  useEffect(() => {
    function handleOutside(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false)
        setFilterOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutside, true)
    return () => document.removeEventListener('mousedown', handleOutside, true)
  }, [])

  useEffect(() => () => {
    abortRef.current?.abort?.()
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
  }, [])

  function resetSuggest() {
    abortRef.current?.abort?.()
    abortRef.current = null
    setItems([])
    setTotal(0)
    setLoading(false)
    setError('')
    setSoftError(false)
    setActiveIndex(-1)
    setElapsedMs(null)
  }

  function scheduleSearch(nextKeyword = keyword, immediate = false) {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    const trimmed = String(nextKeyword || '').trim()
    if (!trimmed) {
      resetSuggest()
      setOpen(false)
      return
    }
    const rjLike = /^[Rr][Jj]?\d{4,}$/.test(trimmed) || /^\d{4,}$/.test(trimmed)
    if (!rjLike && trimmed.length < 2) {
      setOpen(true)
      setItems([])
      setError('至少输入 2 个字符或一个完整 RJ 号')
      setSoftError(true)
      return
    }
    setOpen(true)
    const runner = () => fetchSuggest(trimmed)
    if (immediate) runner()
    else debounceRef.current = window.setTimeout(runner, 220)
  }

  async function fetchSuggest(nextKeyword) {
    abortRef.current?.abort?.()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = requestRef.current + 1
    requestRef.current = requestId
    setLoading(true)
    setError('')
    setSoftError(false)
    try {
      const data = await libraryApi.searchIndexGlobal({
        keyword: nextKeyword,
        libraryIds: Array.isArray(libraryIds) && libraryIds.length ? libraryIds : null,
        entryType: libraryFilterToEntryType(kindFilter),
        mode: 'suggest',
        limit: 8,
        signal: controller.signal
      })
      if (requestId !== requestRef.current) return
      const rawItems = Array.isArray(data?.items) ? data.items : []
      const filtered = applyLibraryFrontendFilter(rawItems, {
        filter: kindFilter,
        keyword: nextKeyword,
        matchedRjcode: data?.matched_rjcode
      })
      setItems(filtered)
      setTotal(Number(data?.total_count || data?.total || filtered.length))
      setElapsedMs(Number.isFinite(Number(data?.elapsed_ms)) ? Number(data.elapsed_ms) : null)
      setActiveIndex(-1)
      if (data?.error?.message) {
        setError(`索引暂不可用：${data.error.message}`)
        setSoftError(true)
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

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (!open) {
        setOpen(true)
        scheduleSearch(keyword, true)
        return
      }
      if (items.length) setActiveIndex(index => (index + 1 + items.length) % items.length)
      return
    }
    if (event.key === 'ArrowUp') {
      if (!open || !items.length) return
      event.preventDefault()
      setActiveIndex(index => (index <= 0 ? items.length - 1 : index - 1))
      return
    }
    if (event.key === 'Enter') {
      if (event.shiftKey) {
        event.preventDefault()
        setOpen(false)
        onOpenOverlay?.({ keyword: keyword.trim(), kindFilter })
        return
      }
      if (open && activeIndex >= 0 && items[activeIndex]) {
        event.preventDefault()
        selectItem(items[activeIndex])
      }
      return
    }
    if (event.key === 'Escape') {
      setOpen(false)
      setFilterOpen(false)
    }
  }

  function selectItem(item) {
    setOpen(false)
    onLocate?.(item)
  }

  return (
    <div ref={rootRef} className={`lib-search-box ${open ? 'is-open' : ''} ${filterOpen ? 'is-filter-open' : ''}`}>
      <div className="lib-search">
        <button
          type="button"
          className={`lib-search-filter ${kindFilter !== 'all' ? 'is-active' : ''} ${filterOpen ? 'is-open' : ''}`}
          title={`按文件类型筛选：${currentFilter.label}`}
          onMouseDown={event => event.preventDefault()}
          onClick={() => {
            setFilterOpen(value => !value)
            setOpen(false)
          }}
        >
          <FilterIcon size={14} strokeWidth={2.25} />
          {kindFilter !== 'all' ? <span className="lib-search-filter-dot" /> : null}
        </button>
        <input
          ref={inputRef}
          className="lib-search-input"
          value={keyword}
          spellCheck={false}
          autoComplete="off"
          placeholder={placeholder}
          onFocus={() => keyword.trim() && scheduleSearch(keyword, true)}
          onChange={event => {
            onChange?.(event.target.value)
            scheduleSearch(event.target.value)
          }}
          onKeyDown={handleKeyDown}
        />
        {keyword ? (
          <button
            type="button"
            className="lib-search-clear"
            title="清除"
            onMouseDown={event => event.preventDefault()}
            onClick={() => {
              onChange?.('')
              resetSuggest()
              inputRef.current?.focus?.()
            }}
          >
            <X size={13} strokeWidth={2.4} />
          </button>
        ) : null}
        <button
          type="button"
          className="lib-search-expand"
          title="打开跨库搜索面板"
          onMouseDown={event => event.preventDefault()}
          onClick={() => {
            setOpen(false)
            onOpenOverlay?.({ keyword: keyword.trim(), kindFilter })
          }}
        >
          <Maximize2 size={14} strokeWidth={2.25} />
        </button>
      </div>

      {filterOpen ? (
        <div className="lib-filter-menu" onMouseDown={event => event.preventDefault()}>
          <header className="lib-filter-menu-head">按文件类型筛选</header>
          <ul className="lib-filter-menu-list">
            {libraryFilterOptions.map(option => {
              const Icon = filterIconMap[option.value] || File
              return (
                <li
                  key={option.value}
                  className={`lib-filter-menu-row ${kindFilter === option.value ? 'is-active' : ''}`}
                  onClick={() => {
                    onKindFilterChange?.(option.value)
                    setFilterOpen(false)
                    inputRef.current?.focus?.()
                    if (keyword.trim()) window.setTimeout(() => scheduleSearch(keyword, true), 0)
                  }}
                >
                  <Icon size={14} strokeWidth={2.2} />
                  <span>{option.label}</span>
                  {kindFilter === option.value ? <Check size={13} strokeWidth={2.5} /> : null}
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}

      {open ? (
        <div className="lib-suggest-pop" onMouseDown={event => event.preventDefault()}>
          <header className="lib-suggest-head">
            <span>跨库索引建议</span>
            {loading ? <em><Loader2 size={11} className="km-spin" />查询中</em> : elapsedMs !== null ? <em>{elapsedMs} ms</em> : null}
          </header>
          {error ? (
            <div className={`lib-suggest-banner ${softError ? 'is-warning' : 'is-error'}`}>
              <AlertCircle size={13} />
              <span>{error}</span>
            </div>
          ) : null}
          {items.length ? (
            <ul className="lib-suggest-list">
              {items.map((item, index) => (
                <li
                  key={`${item.library_id || ''}|${item.relative_path || item.path || index}`}
                  className={`lib-suggest-row ${index === activeIndex ? 'is-active' : ''}`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectItem(item)}
                >
                  <FolderOrFileIcon item={item} />
                  <div className="lib-suggest-row-main">
                    <div className="lib-suggest-row-title">
                      <span className="lib-suggest-row-name">{item.name || itemName(item)}</span>
                      {item.rjcode ? <span className="lib-suggest-row-rj">{item.rjcode}</span> : null}
                    </div>
                    <div className="lib-suggest-row-sub">
                      <span className={`lib-suggest-lib-chip ${item.library_type === 'synology_filestation' ? 'is-remote' : 'is-local'}`}>
                        {item.library_name || item.library_id || '库存'}
                      </span>
                      <span className="lib-suggest-row-path">{item.parent_path || item.relative_path || item.path || ''}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : !loading && keyword.trim() && !error ? (
            <div className="lib-suggest-state">没有找到 “{keyword.trim()}”</div>
          ) : loading ? (
            <div className="lib-suggest-state"><Loader2 size={14} className="km-spin" />正在查询索引...</div>
          ) : null}
          <footer className="lib-suggest-foot">
            <span>↑↓ 选中 · Enter 跳转 · Shift+Enter 展开</span>
            <button type="button" onClick={() => onOpenOverlay?.({ keyword: keyword.trim(), kindFilter })}>
              查看全部{total > items.length ? ` ${total}` : ''}
            </button>
          </footer>
        </div>
      ) : null}
    </div>
  )
}

function FolderOrFileIcon({ item }) {
  const directory = isIndexEntryDirectory(item)
  const Icon = directory ? Folder : File
  return (
    <span className="lib-suggest-row-icon">
      <Icon size={15} strokeWidth={2.2} />
    </span>
  )
}
