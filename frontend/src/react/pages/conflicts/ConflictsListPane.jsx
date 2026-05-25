import { CheckCircle2, CheckSquare, ChevronRight, Cloud, Copy, FileWarning, HardDrive, RotateCcw, SkipForward, XSquare } from 'lucide-react'
import {
  formatConflictDate,
  formatConflictLabel,
  getConflictId,
  getConflictRetryProgress,
  getConflictStatusLabel,
  getConflictTypeDetail,
  isConflictProcessing,
  isConflictRetrying,
  isFailureConflict,
  isKeepNewProcessing
} from './conflictUtils'

export function ConflictsListPane({
  conflicts,
  filteredConflicts,
  filterOptions,
  conflictFilter,
  selectedIds,
  activeId,
  batchRunning,
  localRetryingIds,
  onFilterChange,
  onCardClick,
  onToggleSelectAll,
  onClearSelection,
  isAllSelected,
  selectedActionCount,
  onBatchRetry,
  onBatchSkip
}) {
  const selectedCount = filteredConflicts.filter(item => selectedIds.has(getConflictId(item))).length

  return (
    <aside className="conflicts-list-pane">
      <header className="conflicts-list-header">
        <div className="conflicts-list-title-row">
          <h2>待处理列表</h2>
          <span className="conflicts-count-pill">已选 {selectedCount} / {filteredConflicts.length}</span>
        </div>
        <div className="conflicts-segmented">
          {filterOptions.map(option => (
            <button
              type="button"
              key={option.value}
              className={conflictFilter === option.value ? 'is-active' : ''}
              onClick={() => onFilterChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="conflicts-list-actions">
          <button type="button" className={isAllSelected ? 'is-active' : ''} disabled={batchRunning} onClick={onToggleSelectAll}>
            <CheckSquare size={14} />
            {isAllSelected ? '取消全选' : '全选'}
          </button>
          <button type="button" disabled={batchRunning || !selectedCount} onClick={onClearSelection}>
            <XSquare size={14} />
            清空选择
          </button>
        </div>
        {selectedCount > 0 ? (
          <div className="conflicts-batch-actions">
            {selectedActionCount('RETRY') > 0 ? (
              <button type="button" data-tone="success" disabled={batchRunning} onClick={onBatchRetry}>
                <RotateCcw size={14} />
                一键重试 ({selectedActionCount('RETRY')})
              </button>
            ) : null}
            {selectedActionCount('SKIP') > 0 ? (
              <button type="button" data-tone="muted" disabled={batchRunning} onClick={onBatchSkip}>
                <SkipForward size={14} />
                批量跳过 ({selectedActionCount('SKIP')})
              </button>
            ) : null}
          </div>
        ) : null}
        <p>单击聚焦，Ctrl/⌘ 多选，Shift 连选</p>
      </header>

      <div className="conflicts-list-scroll">
        {!conflicts.length ? (
          <div className="conflicts-list-empty">
            <CheckCircle2 size={34} />
            <strong>当前没有待处理的问题作品</strong>
            <span>所有作品都在正常导入或库中已处于良好状态</span>
          </div>
        ) : !filteredConflicts.length ? (
          <div className="conflicts-list-empty">
            <CheckCircle2 size={30} />
            <strong>没有匹配项</strong>
            <span>切换上方筛选查看其他分类</span>
          </div>
        ) : (
          filteredConflicts.map(conflict => {
            const id = getConflictId(conflict)
            const retrying = isConflictRetrying(conflict, localRetryingIds)
            return (
              <button
                key={id}
                type="button"
                disabled={retrying}
                className={[
                  'conflicts-list-card',
                  selectedIds.has(id) ? 'is-selected' : '',
                  id === activeId ? 'is-active' : '',
                  isConflictProcessing(conflict) ? 'is-processing' : '',
                  isKeepNewProcessing(conflict) ? 'is-keep-new' : '',
                  retrying ? 'is-retrying' : ''
                ].filter(Boolean).join(' ')}
                onClick={event => onCardClick(conflict, event)}
              >
                <div className="conflicts-list-card-row">
                  <strong>
                    {formatConflictLabel(conflict)}
                    <ChevronRight size={14} />
                  </strong>
                  <span className="conflicts-mini-chip">
                    {conflict.context?.existing?.is_remote ? <Cloud size={11} /> : <HardDrive size={11} />}
                    {conflict.context?.existing?.is_remote ? '远程' : '本地'}
                  </span>
                </div>
                <div className="conflicts-list-card-meta">
                  <span>{isFailureConflict(conflict) ? <FileWarning size={13} /> : <Copy size={13} />}{getConflictTypeDetail(conflict)}</span>
                  <em>{getConflictStatusLabel(conflict, localRetryingIds)}</em>
                  <time>{formatConflictDate(conflict.created_at).split(' ')[0]}</time>
                </div>
                {retrying ? (
                  <div className="conflicts-retry-progress">
                    <span><i style={{ width: `${getConflictRetryProgress(conflict)}%` }} /></span>
                    <b>{getConflictRetryProgress(conflict)}%</b>
                  </div>
                ) : null}
              </button>
            )
          })
        )}
      </div>
    </aside>
  )
}
