import { Database, MoreVertical } from 'lucide-react'
import { LibraryFileIcon } from './LibraryFileIcon'
import { itemName, isDirectory } from './libraryUtils'

export function LibraryMobileCard({
  item,
  selected,
  sizeText,
  timeText,
  onToggle,
  onOpen,
  onMenu
}) {
  return (
    <article className={`lib-mobile-card ${selected ? 'is-context-active' : ''} ${isDirectory(item) ? 'is-directory' : ''}`}>
      <input type="checkbox" checked={selected} onChange={event => onToggle(item, event.target.checked)} aria-label={`选择 ${itemName(item)}`} />
      <button type="button" className="lib-mobile-card-main-button" onClick={() => onOpen(item)}>
        <span className="lib-mobile-card-icon-shell">
          <LibraryFileIcon item={item} size={22} />
        </span>
        <span className="lib-mobile-card-main">
          <span className="lib-mobile-card-title-row">
            <span className="lib-mobile-card-name">{itemName(item)}</span>
            {item?.rjcode ? <span className="lib-mobile-card-rj">{item.rjcode}</span> : null}
          </span>
          <span className="lib-mobile-card-meta">
            {sizeText ? <span>{sizeText}</span> : null}
            {sizeText && timeText ? <span className="lib-mobile-card-meta-divider">·</span> : null}
            {timeText ? <span>{timeText}</span> : null}
          </span>
          {item?.library_name || item?.library_label ? (
            <span className="lib-mobile-card-source">
              <Database size={11} strokeWidth={2.4} />
              来源库：{item.library_name || item.library_label}
            </span>
          ) : null}
        </span>
      </button>
      <button type="button" className="lib-mobile-card-menu" title="更多操作" onClick={event => onMenu(item, event)}>
        <MoreVertical size={16} strokeWidth={2.2} />
      </button>
    </article>
  )
}
