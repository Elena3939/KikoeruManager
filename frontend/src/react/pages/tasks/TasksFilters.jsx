import { FilterX, Search, X } from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, IconButton } from '../../components/Primitives'
import { sortOptions } from './taskUtils'

export function TasksFilters({
  domainOptions = [],
  statusOptions = [],
  currentDomain,
  currentStatus,
  searchQuery,
  sortKey,
  activeOnly,
  getDomainCount,
  onDomainChange,
  onStatusChange,
  onSearchChange,
  onSortChange,
  onActiveOnlyChange,
  onReset
}) {
  const domainDropdownOptions = domainOptions.map(option => {
    const count = option.value === 'all' ? 0 : Number(getDomainCount?.(option.value) || 0)
    return {
      value: option.value,
      label: count > 0 ? `${option.label} · ${count}` : option.label
    }
  })

  return (
    <section className="tasks-filter-bar">
      <div className="tasks-search">
        <Search size={15} strokeWidth={2.3} />
        <input
          value={searchQuery}
          type="text"
          placeholder="搜索标题、RJ、路径、当前步骤"
          onChange={event => onSearchChange?.(event.target.value)}
        />
        {searchQuery ? (
          <IconButton title="清空搜索" className="tasks-search-clear" onClick={() => onSearchChange?.('')}>
            <X size={13} strokeWidth={2.6} />
          </IconButton>
        ) : null}
      </div>

      <AppDropdown value={currentDomain} onChange={onDomainChange} options={domainDropdownOptions} placeholder="类型" width={174} />
      <AppDropdown value={currentStatus} onChange={onStatusChange} options={statusOptions} placeholder="状态" width={150} />
      <AppDropdown value={sortKey} onChange={onSortChange} options={sortOptions} placeholder="排序" width={154} />

      <Button
        variant={activeOnly ? 'primary' : 'ghost'}
        className="tasks-active-toggle"
        onClick={() => onActiveOnlyChange?.(!activeOnly)}
      >
        <span className="tasks-live-dot" data-on={activeOnly ? 'true' : 'false'} />
        {activeOnly ? '仅活跃' : '全部'}
      </Button>

      <Button variant="ghost" onClick={onReset}>
        <FilterX size={14} strokeWidth={2.4} />
        重置
      </Button>
    </section>
  )
}
