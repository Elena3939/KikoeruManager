import { Activity, ChevronLeft, ChevronRight, PauseCircle, RefreshCw, RotateCcw, Search, Sparkles, XCircle } from 'lucide-react'
import { useMemo } from 'react'
import { Button, EmptyState } from '../../components/Primitives'
import { filterArchives, formatArchiveDate, formatArchiveSize, getArchiveStatusMeta, getArchiveTaskMeta } from './dashboardUtils'

const statusIconMap = {
  completed: Sparkles,
  failed: XCircle,
  processing: Activity,
  pending: PauseCircle,
  unknown: Activity
}

export function DashboardArchive({
  items,
  tabs,
  searchQuery,
  domainFilter,
  loading,
  reprocessingId,
  page,
  pageSize,
  onRefresh,
  onReprocess,
  onChangePage,
  onSearchChange,
  onDomainChange
}) {
  const filtered = useMemo(() => filterArchives(items, searchQuery, domainFilter), [domainFilter, items, searchQuery])
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(Math.max(1, page), totalPages)
  const paged = filtered.slice((safePage - 1) * pageSize, safePage * pageSize)

  return (
    <section className="dashboard-archive-panel" data-section="dashboard-archive">
      <header className="dashboard-panel-head">
        <div>
          <h2>最近归档</h2>
          <p>{items.length ? `共 ${items.length} 条记录` : '暂无归档记录'}</p>
        </div>
        <Button size="xs" disabled={loading} onClick={onRefresh}>
          <RefreshCw size={14} className={loading ? 'km-spin' : ''} />
          刷新
        </Button>
      </header>

      <label className="dashboard-archive-search">
        <Search size={14} />
        <input value={searchQuery} onChange={event => onSearchChange(event.target.value)} placeholder="搜索 RJ / 文件名" />
      </label>

      <div className="dashboard-archive-tabs">
        {tabs.map(tab => (
          <button
            type="button"
            key={tab.key}
            className={domainFilter === tab.key ? 'is-active' : ''}
            onClick={() => onDomainChange(tab.key)}
          >
            {tab.label}
            {tab.count ? <span>{tab.count}</span> : null}
          </button>
        ))}
      </div>

      {paged.length ? (
        <div className="dashboard-archive-list">
          {paged.map((archive, index) => {
            const meta = getArchiveTaskMeta(archive)
            const status = getArchiveStatusMeta(archive.status)
            const Icon = meta.icon
            const StatusIcon = statusIconMap[status.key] || Activity
            return (
              <article className="dashboard-archive-card" key={archive.id} data-tone={meta.tone} style={{ animationDelay: `${index * 32}ms` }}>
                <Icon size={18} className="dashboard-archive-icon" />
                <div>
                  <div className="dashboard-archive-title-row">
                    <strong title={archive.filename}>{archive.filename}</strong>
                    {archive.rjcode ? <b>{archive.rjcode}</b> : null}
                    <time>{formatArchiveDate(archive.processed_at)}</time>
                  </div>
                  <div className="dashboard-archive-meta">
                    <span>{meta.label}</span>
                    <span data-tone={status.tone}><StatusIcon size={11} />{status.label}</span>
                    {archive.isVolumeGroup ? <span>{archive.volumes?.length || 0} 分卷</span> : null}
                    <em>{formatArchiveSize(archive.file_size)}</em>
                  </div>
                </div>
                {archive.source === 'processed_archive' && status.key === 'failed' ? (
                  <button
                    type="button"
                    className="dashboard-archive-reprocess"
                    disabled={reprocessingId === archive.id}
                    title="重新解压"
                    onClick={() => onReprocess(archive.id)}
                  >
                    <RotateCcw size={14} className={reprocessingId === archive.id ? 'km-spin' : ''} />
                  </button>
                ) : null}
              </article>
            )
          })}
        </div>
      ) : (
        <EmptyState title="暂无归档记录" description="扫描、导入或任务完成后会出现在这里。" />
      )}

      {filtered.length > pageSize ? (
        <footer className="dashboard-archive-pager">
          <span>共 <b>{filtered.length}</b> 条</span>
          <div>
            <button type="button" disabled={safePage <= 1} onClick={() => onChangePage(safePage - 1)}><ChevronLeft size={13} /></button>
            <em>{safePage} / {totalPages}</em>
            <button type="button" disabled={safePage >= totalPages} onClick={() => onChangePage(safePage + 1)}><ChevronRight size={13} /></button>
          </div>
        </footer>
      ) : null}
    </section>
  )
}
