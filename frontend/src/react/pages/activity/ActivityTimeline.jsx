import { ChevronRight, FolderOpen } from 'lucide-react'
import {
  compactPath,
  displayRjcode,
  displaySummary,
  effectiveStatus,
  formatClock,
  getCategoryConfig,
  getStatusConfig,
  humanAction
} from './activityUtils'

export function ActivityTimeline({ groups, selectedId, loading, onOpen }) {
  if (!groups.length && !loading) {
    return (
      <section className="activity-empty-panel glass-panel">
        <strong>没有匹配的操作记录</strong>
        <span>换个关键词、状态或分类再查。</span>
      </section>
    )
  }

  return (
    <section className="activity-timeline-shell">
      <div className="activity-timeline">
        {groups.map(group => (
          <section className="activity-day-group" key={group.key}>
            <header className="activity-day-marker">
              <span>{group.label}</span>
              <em>{group.items.length} 条</em>
              <i />
            </header>
            <div className="activity-day-events">
              {group.items.map(row => (
                <ActivityEventRow
                  key={row.id}
                  row={row}
                  active={String(selectedId || '') === String(row.id || '')}
                  onOpen={() => onOpen?.(row)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </section>
  )
}

function ActivityEventRow({ row, active, onOpen }) {
  const status = effectiveStatus(row)
  const category = getCategoryConfig(row.category)
  const statusConfig = getStatusConfig(status)
  const CategoryIcon = category.icon
  const StatusIcon = statusConfig.icon
  const rj = displayRjcode(row)
  const sourcePath = row.source_path || row.detail?.source_path || row.detail?.archive_path || row.detail?.folder_path || ''

  return (
    <article
      className={`activity-event-row tone-${statusConfig.tone} ${active ? 'is-active' : ''}`}
      onClick={onOpen}
    >
      <div className="activity-event-rail">
        <time>{formatClock(row.created_at)}</time>
        <span className={`activity-event-dot tone-${statusConfig.tone}`}>
          <StatusIcon size={10} strokeWidth={3} />
        </span>
      </div>
      <div className="activity-event-card glass-panel">
        <div className="activity-event-card-head">
          <span className={`activity-category-chip tone-${category.tone}`}>
            <CategoryIcon size={11} strokeWidth={2.6} />
            {row.category_label || category.label}
          </span>
          {rj ? <span className="activity-rj-chip">{rj}</span> : null}
          <strong className={`activity-action tone-${statusConfig.tone}`}>{humanAction(row)}</strong>
          {row.compacted ? <em>已归档</em> : null}
          {row.rerun ? <em>已重试</em> : null}
          {row.has_children || row.has_child_rows ? <em>有子任务</em> : null}
          {Number(row.child_failed_count || 0) > 0 ? <em className="is-danger">失败 {row.child_failed_count}</em> : null}
          {Number(row.child_partial_count || 0) > 0 ? <em className="is-warn">部分 {row.child_partial_count}</em> : null}
        </div>
        <p>{displaySummary(row)}</p>
        <div className="activity-event-meta">
          {(row.chips || []).slice(0, 7).map(chip => (
            <span key={`${row.id}-${chip.label}-${chip.value}`} className={`activity-small-chip tone-${chip.tone || 'neutral'}`}>
              <b>{chip.label}</b>
              <i>{chip.value}</i>
            </span>
          ))}
          {sourcePath ? (
            <span className="activity-event-path" title={sourcePath}>
              <FolderOpen size={11} strokeWidth={2.4} />
              {compactPath(sourcePath, 18, 44)}
            </span>
          ) : null}
        </div>
      </div>
      <div className="activity-event-tail">
        <ChevronRight size={15} strokeWidth={2.4} />
      </div>
    </article>
  )
}
