import { useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  Download,
  ExternalLink,
  FileText,
  Gift,
  Info,
  Languages,
  Layers,
  LibraryBig,
  MessageSquareText,
  PackageCheck,
  Search,
  Server,
  X,
  XCircle
} from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, TextInput } from '../../components/Primitives'
import { cx, formatDateTime } from '../../utils/format'
import {
  COMPARE_PAGE_SIZES,
  WORK_PAGE_SIZES,
  buildDlsiteCoverUrl,
  getDisplayCode,
  getOwnedVariantGroupKey,
  getOwnedVariantGroupLabel,
  getWorkCode,
  isWorkUnreleased,
  normalizeKikoeruTags,
  releaseLabel
} from './circleUtils'

export function MetricPill({ tone, icon, label }) {
  return <span className={cx('circle-metric-pill', tone)}>{icon}{label}</span>
}

export function StatusFilterMenu({ options, value, onChange }) {
  const [open, setOpen] = useState(false)
  const selected = Array.isArray(value) ? value : []
  const selectedOptions = options.filter(option => selected.includes(option.value))
  const title = selectedOptions.length ? selectedOptions.map(option => option.label).join('、') : '状态筛选'

  function toggle(nextValue) {
    const next = selected.includes(nextValue)
      ? selected.filter(item => item !== nextValue)
      : [...selected, nextValue]
    onChange(next)
  }

  return (
    <div className="circle-status-filter">
      <button type="button" className={cx('status-filter-trigger', open && 'is-open', !selectedOptions.length && 'is-placeholder')} title={title} onClick={() => setOpen(value => !value)}>
        <span>{selectedOptions.length ? selectedOptions.slice(0, 2).map(option => option.label).join('、') : '状态筛选'}</span>
        {selectedOptions.length > 2 ? <em>+{selectedOptions.length - 2}</em> : null}
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="circle-status-menu">
          {options.map(option => {
            const active = selected.includes(option.value)
            return (
              <button key={option.value} type="button" className={cx(active && 'is-active')} onClick={() => toggle(option.value)}>
                <span>{option.label}</span>
                <em>{option.suffix ?? 0}</em>
                {active ? <Check size={13} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export function WorksTab({
  items,
  currentPage,
  pageSize,
  pageSizes = WORK_PAGE_SIZES,
  onPageChange,
  onPageSizeChange,
  mode,
  selectedCodes,
  flashedCodes,
  selectedActiveCanonicalRJCodes,
  selectedActiveDownloadableRJCodes,
  activeSelectableCount,
  onSelectAll,
  onClearSelection,
  onRefreshSelected,
  onPreview,
  onToggle,
  onPreviewOne,
  onReimport,
  emptyText
}) {
  return (
    <section className="circle-tab-panel">
      {items.length > 0 && selectedActiveCanonicalRJCodes.length > 0 ? (
        <SelectionBar
          selectedCount={selectedActiveCanonicalRJCodes.length}
          selectableCount={activeSelectableCount}
          downloadableCount={selectedActiveDownloadableRJCodes.length}
          onSelectAll={onSelectAll}
          onClear={onClearSelection}
          onRefresh={onRefreshSelected}
          onPreview={onPreview}
        />
      ) : null}
      <CircleWorksViewport
        items={items}
        mode={mode}
        currentPage={currentPage}
        pageSize={pageSize}
        pageSizes={pageSizes}
        selectedCodes={selectedCodes}
        flashedCodes={flashedCodes}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
        onToggle={onToggle}
        onPreview={onPreviewOne}
        onReimport={onReimport}
        emptyText={emptyText}
      />
    </section>
  )
}

export function OwnedTab({
  items,
  stats,
  searchQuery,
  filterType,
  currentPage,
  pageSize,
  viewMode,
  selectedCodes,
  flashedCodes,
  onSearchChange,
  onFilterChange,
  onPageChange,
  onPageSizeChange,
  onToggle,
  onPreviewOne,
  onReimport
}) {
  return (
    <section className="circle-tab-panel owned-panel">
      <div className="owned-stats-strip">
        {[
          ['all', '全部', stats.total],
          ['original', '原作', stats.original],
          ['simplified', '简中', stats.simplified],
          ['traditional', '繁中', stats.traditional],
          ['subtitle', '字幕', stats.subtitle],
          ['bonus', '特典', stats.bonus]
        ].map(([key, label, value]) => (
          <button key={key} type="button" className={cx(filterType === key && 'is-active')} onClick={() => onFilterChange(key)}>
            <span>{label}</span><strong>{value || 0}</strong>
          </button>
        ))}
      </div>
      <div className="owned-filter-row">
        <div className="circle-search-box owned-search-wrap">
          <Search size={14} />
          <TextInput value={searchQuery} placeholder="搜索已满足作品名或 RJ 号" onChange={event => onSearchChange(event.target.value)} />
          {searchQuery ? <button type="button" onClick={() => onSearchChange('')}><X size={13} /></button> : null}
        </div>
      </div>
      <CircleWorksViewport
        items={items}
        mode={viewMode}
        currentPage={currentPage}
        pageSize={pageSize}
        pageSizes={WORK_PAGE_SIZES}
        selectedCodes={selectedCodes}
        flashedCodes={flashedCodes}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
        onToggle={onToggle}
        onPreview={onPreviewOne}
        onReimport={onReimport}
        emptyText="没有找到符合条件的已满足作品"
      />
    </section>
  )
}

function SelectionBar({ selectedCount, selectableCount, downloadableCount, onSelectAll, onClear, onRefresh, onPreview }) {
  return (
    <div className="circle-selection-bar">
      <span>已选 {selectedCount} / {selectableCount}</span>
      <div>
        <Button size="xs" onClick={onSelectAll}>全选</Button>
        <Button size="xs" onClick={onClear}>清空</Button>
        <Button size="xs" onClick={onRefresh}>刷新状态</Button>
        <Button size="xs" variant="primary" disabled={!downloadableCount} onClick={onPreview}><Download size={13} />下载选中 {downloadableCount}</Button>
      </div>
    </div>
  )
}

export function CircleWorksViewport({
  items,
  mode,
  currentPage,
  pageSize,
  pageSizes,
  selectedCodes,
  flashedCodes,
  onPageChange,
  onPageSizeChange,
  onToggle,
  onPreview,
  onReimport,
  emptyText
}) {
  const parentRef = useRef(null)
  const safeItems = Array.isArray(items) ? items : []
  const total = safeItems.length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const normalizedPage = Math.min(Math.max(1, currentPage || 1), pageCount)
  const pagedItems = useMemo(() => {
    const start = (normalizedPage - 1) * pageSize
    return safeItems.slice(start, start + pageSize)
  }, [safeItems, normalizedPage, pageSize])
  const isCard = mode === 'card'
  const rowVirtualizer = useVirtualizer({
    count: pagedItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => isCard ? 312 : 66,
    overscan: isCard ? 4 : 12
  })

  if (!total) {
    return <div className="circle-work-empty"><span>{emptyText || '没有找到符合条件的作品'}</span></div>
  }

  return (
    <section className={cx('circle-work-viewport', `is-${mode}`)}>
      <div ref={parentRef} className={cx('circle-work-scroll', `is-${mode}`)}>
        <div className={cx('circle-work-virtual-canvas', `is-${mode}`)} style={{ height: isCard ? undefined : rowVirtualizer.getTotalSize() }}>
          {isCard ? (
            <div className="circle-work-grid">
              {pagedItems.map((item, index) => (
                <WorkCard
                  key={item.canonical_rjcode || item.rjcode || index}
                  item={item}
                  selected={Boolean(item?.canonical_rjcode && selectedCodes?.has?.(item.canonical_rjcode))}
                  statusFlash={Boolean(item?.canonical_rjcode && flashedCodes?.has?.(item.canonical_rjcode))}
                  onSelect={onToggle}
                  onPreview={onPreview}
                  onReimport={onReimport}
                />
              ))}
            </div>
          ) : (
            rowVirtualizer.getVirtualItems().map(virtualItem => {
              const item = pagedItems[virtualItem.index]
              return (
                <div key={item.canonical_rjcode || item.rjcode || virtualItem.key} className="circle-work-virtual-row is-list" style={{ height: virtualItem.size, transform: `translateY(${virtualItem.start}px)` }}>
                  <WorkListRow
                    item={item}
                    selected={Boolean(item?.canonical_rjcode && selectedCodes?.has?.(item.canonical_rjcode))}
                    statusFlash={Boolean(item?.canonical_rjcode && flashedCodes?.has?.(item.canonical_rjcode))}
                    onSelect={onToggle}
                    onPreview={onPreview}
                    onReimport={onReimport}
                  />
                </div>
              )
            })
          )}
        </div>
      </div>
      <Pager
        total={total}
        page={normalizedPage}
        pageSize={pageSize}
        pageSizes={pageSizes}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </section>
  )
}

export function WorkCard({ item, selected, statusFlash, onSelect, onPreview, onReimport }) {
  const displayCode = getDisplayCode(item)
  const unreleased = isWorkUnreleased(item)
  const coverUrl = resolveCoverUrl(item, unreleased)
  const isNewWork = Boolean(item?.is_new_work)
  const isBonusWork = Boolean(item?.is_bonus_work)
  const variantLabel = isBonusWork ? '' : item?.owned ? (item.owned_variant?.group_short_label || '原作') : (item.preferred_variant?.group_short_label || '原作')
  const variantRjcode = item?.owned
    ? (item.owned_variant?.rjcode || item.server_match_primary_rjcode || item.display_rjcode || item.canonical_rjcode)
    : (item.download_plan?.rjcode || item.display_rjcode || item.canonical_rjcode)
  const canRepairSubtitle = Boolean(item?.subtitle_repairable)
  const showSubtitleState = Boolean(item?.owned) && (item?.owned_variant?.group_key || 'original') === 'original'

  return (
    <article className={cx('work-card', selected && 'selected', item.local_download_ready && 'is-downloaded', unreleased && 'is-unreleased', isNewWork && 'is-new-work', statusFlash && 'status-flash')} onClick={() => onSelect(item)}>
      <div className="work-card-select-ring" />
      <div className="work-cover-wrapper">
        {coverUrl ? <img src={coverUrl} className="work-cover" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={handleCoverError(item, unreleased)} /> : <div className="work-cover-placeholder"><LibraryBig size={22} /></div>}
        {item.local_download_ready ? <div className="work-corner-flag">已下载</div> : null}
        {unreleased ? <div className="work-unreleased-flag"><Calendar size={12} /><span>未发售</span></div> : null}
        {isNewWork ? <div className={cx('work-new-flag', unreleased && 'work-new-flag--below')}><span>新作</span></div> : null}
        {isBonusWork ? <div className="work-bonus-flag"><Gift size={12} /><span>特典</span></div> : null}
      </div>
      <div className="work-card-body">
        <div className="work-rj">{displayCode}</div>
        <div className="work-title" title={item.title}>{item.title || '未命名作品'}</div>
        <div className="work-linked">
          <span>{variantLabel ? `${variantLabel} · ${variantRjcode}` : variantRjcode}</span>
          {!unreleased && releaseLabel(item) ? <span className="work-release-inline"><Calendar size={11} />{releaseLabel(item)}</span> : null}
        </div>
        <div className={cx('work-cv', !item?.cvs?.length && 'is-empty')}>{Array.isArray(item?.cvs) ? item.cvs.join(' / ') : ''}</div>
        <div className="work-tags">
          {unreleased ? (
            <span className="work-release-chip"><Calendar size={13} />发售 {releaseLabel(item)}</span>
          ) : (
            <>
              <span className={cx('tag-chip', item.server_owned ? 'is-primary' : 'is-danger')}>{item.server_owned ? '已收录' : '未收录'}</span>
              {showSubtitleState ? <span className={cx('tag-chip', canRepairSubtitle ? 'is-repair' : item.subtitle_present ? 'is-subtitle' : 'is-subtitle-none')}>{canRepairSubtitle ? '可补配' : item.subtitle_present ? '有字幕' : '无字幕'}</span> : null}
              <span className={cx('tag-chip', item.has_asmr_one ? 'is-success' : 'is-disabled')}>{item.has_asmr_one ? '可下载' : '无源'}</span>
            </>
          )}
        </div>
        <div className="work-actions">
          {item.local_download_ready ? <button type="button" className="work-action-btn upload" onClick={event => { event.stopPropagation(); onReimport(item) }}>入库</button> : null}
          {item.has_asmr_one || item.local_download_ready ? <button type="button" className="work-action-btn" onClick={event => { event.stopPropagation(); onPreview(item.canonical_rjcode) }}>预览</button> : null}
        </div>
      </div>
    </article>
  )
}

export function WorkListRow({ item, selected, statusFlash, onSelect, onPreview, onReimport }) {
  const displayCode = getDisplayCode(item)
  const unreleased = isWorkUnreleased(item)
  const isNewWork = Boolean(item?.is_new_work)
  const isBonusWork = Boolean(item?.is_bonus_work)
  const coverUrl = resolveCoverUrl(item, unreleased)
  const variantLabel = isBonusWork ? '' : item?.owned ? (item.owned_variant?.group_short_label || '原作') : (item.preferred_variant?.group_short_label || '原作')
  const downloadRjcode = item?.owned
    ? (item.owned_variant?.rjcode || item.server_match_primary_rjcode || item.display_rjcode || item.canonical_rjcode || '')
    : (item.download_plan?.rjcode || item.display_rjcode || item.canonical_rjcode || '')

  return (
    <article className={cx('work-list-row', selected && 'is-selected', item.local_download_ready && 'is-downloaded', isNewWork && 'is-new-work', unreleased && 'is-unreleased', statusFlash && 'status-flash')} onClick={() => onSelect(item)}>
      <div className="wlr-thumb">
        {coverUrl ? <img src={coverUrl} className="wlr-thumb-img" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={handleCoverError(item, unreleased)} /> : <div className="wlr-thumb-placeholder"><LibraryBig size={16} /></div>}
      </div>
      <div className="wlr-main">
        <div className="wlr-title" title={item.title}>
          <span className="wlr-title-text">{item.title || '未命名作品'}</span>
          {isNewWork ? <span className="wlr-new-badge">新作</span> : null}
          {unreleased ? <span className="wlr-unreleased-badge"><Calendar size={10} />未发售</span> : null}
          {isBonusWork ? <span className="wlr-bonus-badge"><Gift size={10} />特典</span> : null}
        </div>
        <div className="wlr-subtitle">
          <span className="wlr-code">{displayCode}</span>
          {Array.isArray(item?.cvs) && item.cvs.length ? <><span className="wlr-sep">/</span><span className="wlr-cv">{item.cvs.join(' / ')}</span></> : null}
          {releaseLabel(item) ? <><span className="wlr-sep">/</span><span className="wlr-release"><Calendar size={10} />{releaseLabel(item)}</span></> : null}
        </div>
      </div>
      <div className="wlr-meta">
        {variantLabel ? <span className="wlr-variant"><Layers size={11} />{variantLabel}</span> : null}
        {downloadRjcode !== displayCode ? <span className="wlr-linked-code">{downloadRjcode}</span> : null}
      </div>
      <div className="wlr-status">
        <span className={cx('wlr-pill', item.server_owned ? 'pill-owned' : 'pill-missing')}><Server size={10} />{item.server_owned ? '已收录' : '未收录'}</span>
        <span className={cx('wlr-pill', item.has_asmr_one ? 'pill-ok' : 'pill-none')}><LibraryBig size={10} />{item.has_asmr_one ? '可下载' : '无源'}</span>
      </div>
      <div className="wlr-actions" onClick={event => event.stopPropagation()}>
        {item.local_download_ready ? <button type="button" className="wlr-btn wlr-btn--import" onClick={() => onReimport(item)}><PackageCheck size={13} />入库</button> : null}
        {item.has_asmr_one || item.local_download_ready ? <button type="button" className="wlr-btn" onClick={() => onPreview(item.canonical_rjcode)}><ExternalLink size={13} />下载</button> : null}
      </div>
    </article>
  )
}

export function CompareTab({
  items,
  stats,
  searchQuery,
  sourceFilter,
  currentPage,
  pageSize,
  onSearchChange,
  onSourceFilterChange,
  onPageChange,
  onPageSizeChange
}) {
  const start = (currentPage - 1) * pageSize
  const paged = items.slice(start, start + pageSize)
  return (
    <section className="circle-tab-panel compare-panel">
      <div className="compare-stats-list">
        <CompareStat icon={<CheckCircle2 size={14} />} label="Kikoeru" value={stats.kikoeru} tone="emerald" />
        <CompareStat icon={<CheckCircle2 size={14} />} label="DLsite" value={stats.dlsite} tone="blue" />
        <CompareStat icon={<CheckCircle2 size={14} />} label="ASMR.ONE" value={stats.asmr_one} tone="violet" />
        <CompareStat icon={<XCircle size={14} />} label="暂无来源" value={stats.missing} tone="rose" />
      </div>
      <div className="compare-filter-row">
        <div className="compare-filter-tabs">
          {[
            ['all', '全部'],
            ['kikoeru', '已拥有(Kikoeru)'],
            ['asmr_one', '可下载(ASMR.ONE)'],
            ['dlsite', 'DLsite'],
            ['missing', '暂无来源']
          ].map(([key, label]) => (
            <button key={key} type="button" className={cx(sourceFilter === key && 'is-active')} onClick={() => onSourceFilterChange(key)}>{label}</button>
          ))}
        </div>
        <div className="circle-search-box compare-search-wrap">
          <Search size={14} />
          <TextInput value={searchQuery} placeholder="搜索作品名或 RJ 号" onChange={event => onSearchChange(event.target.value)} />
          {searchQuery ? <button type="button" onClick={() => onSearchChange('')}><X size={13} /></button> : null}
        </div>
      </div>
      <div className="compare-head">
        <div>资源信息</div>
        <span>Kikoeru</span>
        <span>DLsite</span>
        <span>ASMR.ONE</span>
      </div>
      <div className="compare-works-list">
        {paged.map(item => <CompareWorkRow key={item.workRjcode || item.title} item={item} />)}
        {!paged.length ? <div className="circle-work-empty"><span>没有符合条件的来源记录</span></div> : null}
      </div>
      <Pager total={items.length} page={currentPage} pageSize={pageSize} pageSizes={COMPARE_PAGE_SIZES} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />
    </section>
  )
}

function CompareStat({ icon, label, value, tone }) {
  return (
    <div className={cx('compare-stat-card', tone)}>
      <span>{icon}</span>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  )
}

function CompareWorkRow({ item }) {
  const tags = normalizeKikoeruTags(item.sourceCompare.kikoeru.tags)
  return (
    <article className="compare-work-item">
      <div className="compare-work-main">
        <h4>{item.title || item.workRjcode || '未命名作品'}</h4>
        <div className="compare-work-tags">
          <span className={cx('compare-status-pill', `is-${item.statusKey}`)}>{item.statusLabel}</span>
          <span className="compare-chip">{item.workRjcode || '-'}</span>
          {item.preferredVariantLabel ? <span className="compare-chip">{item.preferredVariantLabel}</span> : null}
          {tags.includes('字幕') ? <span className="compare-chip is-kikoeru-tag"><MessageSquareText size={12} />字幕</span> : null}
        </div>
      </div>
      <div className="compare-source-cols">
        <SourceColumn primary={item.sourceCompare.kikoeru.primary_rjcode} badges={item.sourceCompare.kikoeru.variantBadges} />
        <SourceColumn list={item.sourceCompare.dlsite.all_rjcodes} />
        <SourceColumn primary={item.sourceCompare.asmr_one.primary_rjcode} badges={item.sourceCompare.asmr_one.primaryBadge ? [item.sourceCompare.asmr_one.primaryBadge] : []} />
      </div>
    </article>
  )
}

function SourceColumn({ primary, list = [], badges = [] }) {
  const values = list.length ? list : (primary ? [primary] : [])
  return (
    <div className="compare-source-col">
      {values.length ? values.map(value => <span key={value} className="compare-source-code">{value}</span>) : <span className="compare-empty">-</span>}
      {badges.length ? <div>{badges.map(badge => <em key={badge}>{badge}</em>)}</div> : null}
    </div>
  )
}

export function InfoTab({ detail }) {
  return (
    <section className="info-grid">
      <InfoCard label="社团ID" value={detail.circle_id || '-'} />
      <InfoCard label="最近索引" value={formatDateTime(detail.last_indexed_at)} />
      <InfoCard label="来源标记" value={detail.source_mask || '-'} />
      <InfoCard label="可见作品" value={detail.works?.length || 0} />
    </section>
  )
}

function InfoCard({ label, value }) {
  return (
    <div className="info-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function Pager({ total, page, pageSize, pageSizes, onPageChange, onPageSizeChange }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="works-pager">
      <span>共 {total} 项</span>
      <AppDropdown value={String(pageSize)} onChange={value => onPageSizeChange(Number(value))} options={pageSizes.map(size => ({ value: String(size), label: `${size} / 页` }))} width={110} />
      <Button size="xs" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</Button>
      <span>{page} / {pageCount}</span>
      <Button size="xs" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>下一页</Button>
    </div>
  )
}

function resolveCoverUrl(item, unreleased) {
  const raw = String(item?.image_url || item?.cover_url || '').trim()
  const rjcode = item?.display_rjcode || getWorkCode(item)
  if (unreleased && raw.includes('/modpub/images2/work/doujin/')) return buildDlsiteCoverUrl(rjcode, true, 'sam')
  if (raw.includes('/modpub/images2/') && raw.endsWith('_img_main.jpg')) {
    return raw.replace('https://img.dlsite.jp/modpub/images2/', 'https://img.dlsite.jp/resize/images2/').replace('_img_main.jpg', '_img_main_240x240.jpg')
  }
  return raw || buildDlsiteCoverUrl(rjcode, unreleased, 'sam')
}

function handleCoverError(item, unreleased) {
  return event => {
    const rjcode = item?.display_rjcode || getWorkCode(item)
    const fallbacks = unreleased
      ? [
          buildDlsiteCoverUrl(rjcode, true, 'sam'),
          buildDlsiteCoverUrl(rjcode, true, 'resized'),
          buildDlsiteCoverUrl(rjcode, true, 'main'),
          buildDlsiteCoverUrl(rjcode, false, 'sam'),
          buildDlsiteCoverUrl(rjcode, false, 'resized'),
          buildDlsiteCoverUrl(rjcode, false, 'main')
        ]
      : [
          buildDlsiteCoverUrl(rjcode, false, 'resized'),
          buildDlsiteCoverUrl(rjcode, false, 'main')
        ]
    const tried = Number(event.currentTarget.dataset.fallbackIndex || 0)
    const fallback = fallbacks[tried]
    if (!fallback) return
    event.currentTarget.dataset.fallbackIndex = String(tried + 1)
    event.currentTarget.src = fallback
  }
}
