import { Database, Loader2, RefreshCw } from 'lucide-react'
import { statusLabel } from './libraryUtils'

export function LibraryIndexBadge({ status, currentLibrary, onRebuild, disabled }) {
  const name = status?.status || 'idle'
  const total = Number(status?.total_entries || 0)
  const totalText = total > 0 ? (total >= 10000 ? `${(total / 10000).toFixed(1)}w 项` : `${total.toLocaleString()} 项`) : ''
  const titleParts = [statusLabel(name)]
  if (totalText) titleParts.push(totalText)
  if (status?.error) titleParts.push(status.error)

  return (
    <div className={`library-index-badge is-${name}`} title={titleParts.join('\n')}>
      <span className="library-index-chip-main">
        {name === 'syncing' ? <Loader2 size={13} className="km-spin" /> : <Database size={13} />}
        <span>{statusLabel(name)}</span>
        {totalText ? <em>{totalText}</em> : null}
      </span>
      <button
        type="button"
        disabled={disabled || name === 'syncing'}
        onClick={onRebuild}
        title={disabled ? '请选择库存后再重建索引' : `重建 ${currentLibrary?.name || '当前库存'} 的搜索索引`}
      >
        <RefreshCw size={12} />
        <span>重建索引</span>
      </button>
    </div>
  )
}
