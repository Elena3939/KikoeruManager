import { useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  FolderInput,
  FolderOpen,
  HardDrive,
  MoreVertical,
  Trash2,
  Wand2
} from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, Card, IconButton, LoadingState } from '../../components/Primitives'
import { formatBytes, formatDateTime } from '../../utils/format'
import { LibraryFileIcon } from './LibraryFileIcon'
import { LibraryMobileCard } from './LibraryMobileCard'
import {
  PAGE_SIZES,
  canApiRenameRow,
  formatLibraryRowSize,
  isDirectory,
  itemName,
  libraryEntryLabel,
  rowKey,
  sortOptions
} from './libraryUtils'

export function LibraryFileTable({
  rows,
  total,
  page,
  pageCount,
  pageSize,
  sortBy,
  sortOrder,
  selectedKeys,
  allPageSelected,
  dragState,
  locatedPath,
  loading,
  busy,
  onToggleRow,
  onTogglePage,
  onOpen,
  onRowSelect,
  onView,
  onRename,
  onOpenFolder,
  onApiRename,
  onManage,
  onMove,
  onRemove,
  onOpenContextMenu,
  onDragStart,
  onDragOverRow,
  onDropOnRow,
  onDragEnd,
  onMarqueeSelect,
  onSortByChange,
  onSortOrderToggle,
  onPageChange,
  onPageSizeChange
}) {
  const tableWrapRef = useRef(null)
  const marqueeRef = useRef(null)
  const suppressClickRef = useRef(false)
  const [marqueeBox, setMarqueeBox] = useState(null)

  function startMarquee(event) {
    if (event.button !== 0 || event.target.closest('button,input,a')) return
    const rowElement = event.target.closest('[data-library-row-key]')
    const pressedSelectedRow = rowElement && selectedKeys.has(rowElement.getAttribute('data-library-row-key'))
    if (pressedSelectedRow) return
    const wrap = tableWrapRef.current
    if (!wrap) return
    marqueeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      currentX: event.clientX,
      currentY: event.clientY,
      additive: event.ctrlKey || event.metaKey,
      active: false
    }
    wrap.setPointerCapture?.(event.pointerId)
  }

  function moveMarquee(event) {
    const state = marqueeRef.current
    if (!state || state.pointerId !== event.pointerId) return
    state.currentX = event.clientX
    state.currentY = event.clientY
    const moved = Math.abs(state.currentX - state.startX) + Math.abs(state.currentY - state.startY)
    if (moved < 8 && !state.active) return
    state.active = true
    suppressClickRef.current = true
    event.preventDefault()
    setMarqueeBox(rectFromPoints(state.startX, state.startY, state.currentX, state.currentY))
  }

  function finishMarquee(event) {
    const state = marqueeRef.current
    if (!state || state.pointerId !== event.pointerId) return
    const wrap = tableWrapRef.current
    wrap?.releasePointerCapture?.(event.pointerId)
    marqueeRef.current = null
    setMarqueeBox(null)
    if (!state.active || !wrap) return
    const box = rectFromPoints(state.startX, state.startY, state.currentX, state.currentY)
    const keys = [...wrap.querySelectorAll('[data-library-row-key]')]
      .filter(element => intersects(box, element.getBoundingClientRect()))
      .map(element => element.getAttribute('data-library-row-key'))
      .filter(Boolean)
    onMarqueeSelect(keys, state.additive)
    window.setTimeout(() => { suppressClickRef.current = false }, 0)
  }

  return (
    <Card className="library-table-card">
      <div className="library-table-toolbar">
        <div className="km-row-actions">
          <span className="km-tag">本页 {rows.length} / 共 {total}</span>
          <AppDropdown value={sortBy} onChange={onSortByChange} options={sortOptions} width={116} />
          <Button size="sm" onClick={onSortOrderToggle}>
            {sortOrder === 'desc' ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
            {sortOrder === 'desc' ? '倒序' : '正序'}
          </Button>
        </div>
        <LibraryPagination
          page={page}
          pageCount={pageCount}
          pageSize={pageSize}
          onPageChange={onPageChange}
          onPageSizeChange={onPageSizeChange}
        />
      </div>

      {loading ? <LoadingState label="正在读取库存..." /> : null}
      {!loading && !rows.length ? <div className="km-empty"><FolderOpen size={32} /><strong>当前目录为空</strong></div> : null}
      {!loading && rows.length ? (
        <>
          <div
            ref={tableWrapRef}
            className={`lib-file-table-wrap ${marqueeBox ? 'is-marquee-selecting' : ''}`}
            onPointerDown={startMarquee}
            onPointerMove={moveMarquee}
            onPointerUp={finishMarquee}
            onPointerCancel={finishMarquee}
            onClickCapture={event => {
              if (!suppressClickRef.current) return
              event.preventDefault()
              event.stopPropagation()
            }}
          >
            <div className="lib-file-table" role="table" aria-label="库存文件列表">
              <div className="lib-file-table-head" role="rowgroup">
                <div className="lib-file-table-header-row" role="row">
                  <div className="lib-file-th lib-file-check-cell" role="columnheader">
                    <input type="checkbox" checked={allPageSelected} onChange={event => onTogglePage(event.target.checked)} aria-label="选择本页" />
                  </div>
                  <div className="lib-file-th" role="columnheader">名称</div>
                  <div className="lib-file-th" role="columnheader">大小</div>
                  <div className="lib-file-th" role="columnheader">修改时间</div>
                  <div className="lib-file-th" role="columnheader">路径</div>
                  <div className="lib-file-th" role="columnheader">操作</div>
                </div>
              </div>
              <div className="lib-file-table-body" role="rowgroup">
                {rows.map(item => {
                  const key = rowKey(item)
                  const selected = selectedKeys.has(key)
                  return (
                    <LibraryFileRow
                      key={key}
                      item={item}
                      selected={selected}
                      dragState={dragState}
                      locatedPath={locatedPath}
                      busy={busy}
                      onToggleRow={onToggleRow}
                      onOpen={onOpen}
                      onRowSelect={onRowSelect}
                      onView={onView}
                      onRename={onRename}
                      onOpenFolder={onOpenFolder}
                      onApiRename={onApiRename}
                      onManage={onManage}
                      onMove={onMove}
                      onRemove={onRemove}
                      onOpenContextMenu={onOpenContextMenu}
                      onDragStart={onDragStart}
                      onDragOverRow={onDragOverRow}
                      onDropOnRow={onDropOnRow}
                      onDragEnd={onDragEnd}
                    />
                  )
                })}
              </div>
            </div>
            {marqueeBox ? <div className="lib-table-marquee-box" style={marqueeBox} /> : null}
          </div>

          <div className="lib-mobile-list">
            {rows.map(item => {
              const key = rowKey(item)
              return (
                <LibraryMobileCard
                  key={key}
                  item={item}
                  selected={selectedKeys.has(key)}
                  sizeText={formatLibraryRowSize(item, formatBytes)}
                  timeText={formatDateTime(item.modified || item.mtime || item.updated_at)}
                  onToggle={onToggleRow}
                  onOpen={row => isDirectory(row) ? onOpen(row) : onView(row)}
                  onMenu={onOpenContextMenu}
                />
              )
            })}
          </div>
        </>
      ) : null}
    </Card>
  )
}

function rectFromPoints(startX, startY, endX, endY) {
  return {
    left: Math.min(startX, endX),
    top: Math.min(startY, endY),
    width: Math.abs(endX - startX),
    height: Math.abs(endY - startY)
  }
}

function intersects(a, b) {
  return a.left <= b.right && a.left + a.width >= b.left && a.top <= b.bottom && a.top + a.height >= b.top
}

function LibraryFileRow({
  item,
  selected,
  dragState,
  locatedPath,
  busy,
  onToggleRow,
  onOpen,
  onRowSelect,
  onView,
  onRename,
  onOpenFolder,
  onApiRename,
  onManage,
  onMove,
  onRemove,
  onOpenContextMenu,
  onDragStart,
  onDragOverRow,
  onDropOnRow,
  onDragEnd
}) {
  const name = itemName(item)
  const key = rowKey(item)
  const isDropTarget = dragState?.targetKey === key
  const located = locatedPath && normalizeComparePath(item.path) === normalizeComparePath(locatedPath)

  return (
    <div
      className={`lib-file-table-row ${selected ? 'library-row-marquee-selected' : ''} ${isDropTarget ? 'library-row-drop-target' : ''} ${located ? 'library-row-located' : ''}`}
      role="row"
      data-library-row-path={item.path || ''}
      data-library-row-key={key}
      draggable
      onClick={event => {
        if (event.target.closest('button,input,a')) return
        onRowSelect(item, event)
      }}
      onDoubleClick={event => {
        if (event.target.closest('button,input,a')) return
        if (isDirectory(item)) onOpen(item)
        else onView(item)
      }}
      onContextMenu={event => onOpenContextMenu(item, event)}
      onDragStart={event => onDragStart(item, event)}
      onDragOver={event => onDragOverRow(item, event)}
      onDrop={event => onDropOnRow(item, event)}
      onDragEnd={onDragEnd}
    >
      <div className="lib-file-cell lib-file-check-cell" role="cell">
        <input type="checkbox" checked={selected} onChange={event => onToggleRow(item, event.target.checked)} aria-label={`选择 ${name}`} />
      </div>
      <div className="lib-file-cell lib-file-name-cell" role="cell">
        <div className="file-cell" title={name}>
          <div className="file-main-line">
            <LibraryFileIcon item={item} />
            <button
              type="button"
              className="file-link-btn"
              onClick={event => {
                event.stopPropagation()
                if (isDirectory(item)) onOpen(item)
                else onView(item)
              }}
            >
              {name}
            </button>
            {item?.rjcode ? <span className="lib-file-rj">{item.rjcode}</span> : null}
          </div>
          <div className="file-sub-line">
            <span>{libraryEntryLabel(item)}</span>
            {item?.library_name || item?.library_label ? <span>来源库：{item.library_name || item.library_label}</span> : null}
          </div>
        </div>
      </div>
      <div className="lib-file-cell lib-file-size-cell" role="cell">{formatLibraryRowSize(item, formatBytes)}</div>
      <div className="lib-file-cell" role="cell">{formatDateTime(item.modified || item.mtime || item.updated_at)}</div>
      <div className="lib-file-cell library-path-cell" role="cell">{item.path || '-'}</div>
      <div className="lib-file-cell" role="cell">
        <div className="km-row-actions library-row-actions">
          <Button size="xs" onClick={() => onRename(item)}>重命名</Button>
          <Button size="xs" onClick={() => onOpenFolder(item)}><HardDrive size={13} />打开</Button>
          {canApiRenameRow(item) ? (
            <Button size="xs" disabled={busy} onClick={() => onApiRename(item)}><Wand2 size={13} />API命名</Button>
          ) : null}
          {isDirectory(item) ? <Button size="xs" onClick={() => onManage(item)}>管理</Button> : null}
          <Button size="xs" onClick={() => onMove([item])}><FolderInput size={13} />移动</Button>
          <IconButton title="删除" className="is-danger" onClick={() => onRemove(item)}><Trash2 size={14} /></IconButton>
          <IconButton title="更多" onClick={event => onOpenContextMenu(item, event)}><MoreVertical size={14} /></IconButton>
        </div>
      </div>
    </div>
  )
}

function normalizeComparePath(value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+$/g, '')
}

function LibraryPagination({ page, pageCount, pageSize, onPageChange, onPageSizeChange }) {
  return (
    <div className="km-row-actions library-pagination">
      <Button size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</Button>
      <span className="km-muted">第 <b>{page}</b> / {pageCount} 页</span>
      <Button size="sm" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>下一页</Button>
      <AppDropdown
        value={String(pageSize)}
        onChange={value => onPageSizeChange(Number(value))}
        options={PAGE_SIZES.map(size => ({ value: String(size), label: `${size} / 页` }))}
        width={112}
      />
    </div>
  )
}
