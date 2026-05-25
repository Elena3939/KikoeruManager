import { ChevronRight, Folder } from 'lucide-react'
import { Card } from '../../components/Primitives'
import { formatBytes } from '../../utils/format'

export function LibraryBreadcrumbBar({ breadcrumbs, stats, dragState, onNavigate, onDragOverCrumb, onDropOnCrumb, onDragEnd }) {
  return (
    <Card className="library-path-card">
      <Folder size={16} />
      <nav>
        {breadcrumbs.map((crumb, index) => (
          <span key={crumb.path || 'root'} className="library-crumb-wrap">
            {index > 0 ? <ChevronRight size={13} /> : null}
            <button
              type="button"
              className={`${index === breadcrumbs.length - 1 ? 'is-current' : ''} ${dragState?.targetKey === `crumb:${crumb.path || ''}` ? 'is-drag-hover' : ''}`}
              onClick={() => onNavigate(crumb.path)}
              onDragOver={event => onDragOverCrumb?.(crumb, event)}
              onDrop={event => onDropOnCrumb?.(crumb, event)}
              onDragEnd={onDragEnd}
            >
              {crumb.label}
            </button>
          </span>
        ))}
      </nav>
      <em>{stats?.total_size ? formatBytes(stats.total_size) : ''}</em>
    </Card>
  )
}
