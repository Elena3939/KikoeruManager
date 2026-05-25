import { Calendar, Clock, LibraryBig, Mail, RefreshCw, Server, Tags, X, XCircle } from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, Card, TextInput } from '../../components/Primitives'
import { cx, formatDateTime } from '../../utils/format'
import {
  getCircleCompletionState,
  getCircleMissingCount,
  getCircleOwnedPercent,
  getCircleWorksCount
} from './circleUtils'

export function CircleSidebar({
  circles,
  allCount,
  activeCircleId,
  search,
  sortKey,
  filter,
  sortOptions,
  onSearchChange,
  onSearchSubmit,
  onSearchClear,
  onSortChange,
  onFilterChange,
  onRefresh,
  onSelect
}) {
  return (
    <aside className="circle-sidebar">
      <Card className="circle-sidebar-card">
        <header className="circle-sidebar-head">
          <div>
            <div className="circle-overline">社团目录</div>
            <h2>最近索引</h2>
          </div>
          <Button size="xs" onClick={onRefresh}><RefreshCw size={13} />刷新</Button>
        </header>

        <div className="circle-search-box">
          <Tags size={14} />
          <TextInput
            value={search}
            placeholder="筛选已缓存社团"
            onChange={event => onSearchChange(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') onSearchSubmit() }}
          />
          {search ? <button type="button" onClick={onSearchClear}><X size={13} /></button> : null}
        </div>

        <div className="circle-filter-stack">
          <div className="circle-filter-chips">
            {[
              ['all', '全部'],
              ['completed', '已补全'],
              ['incomplete', '未补全'],
              ['new_works', '新作']
            ].map(([value, label]) => (
              <button key={value} type="button" className={cx('circle-chip-button', filter === value && 'is-active', value === 'new_works' && 'is-new')} onClick={() => onFilterChange(value)}>
                {label}
              </button>
            ))}
          </div>
          <div className="circle-sort-row">
            <span>排序</span>
            <AppDropdown value={sortKey} onChange={onSortChange} options={sortOptions} width={150} />
          </div>
        </div>

        <div className="circle-list">
          {circles.map(circle => (
            <CircleListItem
              key={circle.circle_id || circle.circle_name}
              circle={circle}
              active={activeCircleId === circle.circle_id}
              onClick={() => onSelect(circle.circle_id)}
            />
          ))}
          {!circles.length ? (
            <div className="km-empty circle-sidebar-empty">
              <Tags size={24} />
              <strong>{allCount ? '当前筛选条件下没有社团' : '还没有社团索引'}</strong>
            </div>
          ) : null}
        </div>
      </Card>
    </aside>
  )
}

export function CircleListItem({ circle, active, onClick }) {
  const state = getCircleCompletionState(circle)
  const percent = getCircleOwnedPercent(circle)
  return (
    <button type="button" className={cx('circle-list-item', active && 'active')} onClick={onClick}>
      <div className="circle-list-header">
        <div className="circle-list-name">
          <span>{circle.circle_name || circle.circle_id}</span>
          {Number(circle.new_works_48h_count || 0) > 0 ? <span className="circle-inline-new-badge">NEW</span> : null}
        </div>
        <div className="circle-list-id">{circle.circle_id}</div>
      </div>
      <div className="circle-list-stats-row">
        <div className="circle-list-counts">
          <span className="circle-stat-item total" title="DLsite作品数"><LibraryBig size={10} /> {getCircleWorksCount(circle)}</span>
          <span className="circle-stat-item owned" title="服务器已拥有"><Server size={10} /> {circle.server_owned || 0}</span>
          {getCircleMissingCount(circle) > 0 ? <span className="circle-stat-item missing" title="缺失"><XCircle size={10} /> {getCircleMissingCount(circle)}</span> : null}
        </div>
        <span className={cx('circle-list-status-pill', state)}>{state === 'completed' ? '已补全' : '未补全'}</span>
      </div>
      <div className="circle-list-progress-container">
        <div className="circle-list-progress"><div style={{ width: `${percent}%` }} /></div>
        <span className="circle-list-percent">{percent}%</span>
      </div>
      {Number(circle.unreleased_count || 0) > 0 || Number(circle.new_works_48h_count || 0) > 0 ? (
        <div className="circle-list-tag-row">
          {Number(circle.unreleased_count || 0) > 0 ? <span className="circle-list-tag unreleased"><Calendar size={9} /> {circle.unreleased_count} 未发售</span> : null}
          {Number(circle.new_works_48h_count || 0) > 0 ? <span className="circle-list-tag new-work"><Mail size={9} /> {circle.new_works_48h_count} 新作</span> : null}
        </div>
      ) : null}
      {circle.last_indexed_at ? <div className="circle-list-refresh-row"><Clock size={9} /> {formatDateTime(circle.last_indexed_at)}</div> : null}
    </button>
  )
}
