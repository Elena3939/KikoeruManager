import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Archive, FilterX, Loader2, RefreshCcw, Search, X, Zap } from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { activityLogApi } from '../../api'
import { AppDropdown } from '../components/AppDropdown'
import { Button, IconButton, PageHeader } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm } from '../stores/systemPromptStore'
import { ActivityDetailDrawer } from './activity/ActivityDetailDrawer'
import { ActivityTimeline } from './activity/ActivityTimeline'
import {
  activityCategoryOptions,
  activityPageSizeOptions,
  activityStatusOptions,
  buildSparkline,
  categoryRows,
  formatFullDateTime,
  formatNumber,
  formatShortDate,
  groupTimeline,
  metricCards,
  splitMetric,
  statsDaysOptions
} from './activity/activityUtils'

const defaultStats = {
  days: 14,
  total_in_range: 0,
  by_day: [],
  by_category: [],
  by_status: {},
  metrics: {},
  db_path: ''
}

export function ActivityHistoryPage() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(50)
  const [statsDays, setStatsDays] = useState(14)
  const [stats, setStats] = useState(defaultStats)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [status, setStatus] = useState('all')
  const [searchBackend, setSearchBackend] = useState('none')
  const [searchStatus, setSearchStatus] = useState(null)
  const [compactEstimate, setCompactEstimate] = useState(null)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [selectedLiteRow, setSelectedLiteRow] = useState(null)
  const [selectedRow, setSelectedRow] = useState(null)
  const [lastLoadedAt, setLastLoadedAt] = useState(0)
  const [compactRunning, setCompactRunning] = useState(false)
  const searchTimer = useRef(null)
  const listAbortRef = useRef(null)
  const requestSeqRef = useRef(0)
  const detailCacheRef = useRef(new Map())

  const loadStats = useCallback(async () => {
    try {
      const data = await activityLogApi.stats({ days: statsDays })
      setStats({ ...defaultStats, ...data })
    } catch (error) {
      console.warn('[操作记录] 加载统计失败', error)
    }
  }, [statsDays])

  const loadSearchStatus = useCallback(async () => {
    try {
      setSearchStatus(await activityLogApi.searchStatus())
    } catch (error) {
      console.warn('[操作记录] 加载搜索引擎状态失败', error)
    }
  }, [])

  const loadCompactEstimate = useCallback(async () => {
    try {
      setCompactEstimate(await activityLogApi.compactEstimate({ older_than_days: 30 }))
    } catch (error) {
      console.warn('[操作记录] 归档估算失败', error)
    }
  }, [])

  const loadList = useCallback(async (nextPage = page, options = {}) => {
    if (listAbortRef.current) {
      try { listAbortRef.current.abort() } catch {}
    }
    const controller = new AbortController()
    listAbortRef.current = controller
    const seq = ++requestSeqRef.current
    setLoading(true)
    try {
      const data = await activityLogApi.list({
        page: nextPage,
        limit,
        category: category === 'all' ? undefined : category,
        status: status === 'all' ? undefined : status,
        q: query.trim() || undefined,
        lite: true
      }, { signal: controller.signal })
      if (seq !== requestSeqRef.current) return
      setRows(Array.isArray(data?.items) ? data.items : [])
      setTotal(Number(data?.total || 0))
      setSearchBackend(String(data?.window?.search_backend || 'none'))
      setLastLoadedAt(Date.now())
      if (options.keepPage !== true) setPage(nextPage)
    } catch (error) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      if (seq !== requestSeqRef.current) return
      console.warn('[操作记录] 加载列表失败', error)
      setRows([])
      setTotal(0)
      setSearchBackend('error')
    } finally {
      if (seq === requestSeqRef.current) setLoading(false)
    }
  }, [category, limit, page, query, status])

  const loadAll = useCallback(async () => {
    await Promise.all([loadStats(), loadList(page, { keepPage: true }), loadSearchStatus(), loadCompactEstimate()])
  }, [loadCompactEstimate, loadList, loadSearchStatus, loadStats, page])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    loadList(1)
  }, [category, limit, status])

  useEffect(() => {
    loadSearchStatus()
    loadCompactEstimate()
  }, [loadCompactEstimate, loadSearchStatus])

  useEffect(() => {
    return () => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current)
      if (listAbortRef.current) listAbortRef.current.abort()
    }
  }, [])

  useEffect(() => {
    const handler = () => {
      if (document.visibilityState !== 'visible') return
      if (!lastLoadedAt || Date.now() - lastLoadedAt > 3 * 60 * 1000) loadAll()
    }
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [lastLoadedAt, loadAll])

  function scheduleSearch(value) {
    setQuery(value)
    if (searchTimer.current) window.clearTimeout(searchTimer.current)
    searchTimer.current = window.setTimeout(() => {
      searchTimer.current = null
      setPage(1)
      loadList(1)
    }, 350)
  }

  function runSearchNow() {
    if (searchTimer.current) {
      window.clearTimeout(searchTimer.current)
      searchTimer.current = null
    }
    setPage(1)
    loadList(1)
  }

  function resetFilters() {
    setQuery('')
    setCategory('all')
    setStatus('all')
    setPage(1)
    window.setTimeout(() => loadList(1), 0)
  }

  async function openDetail(rowOrId) {
    const liteRow = typeof rowOrId === 'object' ? rowOrId : rows.find(item => String(item.id) === String(rowOrId))
    const id = typeof rowOrId === 'object' ? rowOrId?.id : rowOrId
    if (!id) return
    setSelectedLiteRow(liteRow || { id, __isLite: true })
    setSelectedRow(liteRow || { id, __isLite: true })
    const cacheKey = String(id)
    if (detailCacheRef.current.has(cacheKey)) {
      setSelectedRow(detailCacheRef.current.get(cacheKey))
      return
    }
    setDetailLoading(true)
    try {
      const data = await activityLogApi.detail(id)
      const next = data?.row || liteRow || { id }
      detailCacheRef.current.set(cacheKey, next)
      setSelectedRow(next)
    } catch (error) {
      console.warn('[操作记录] 加载详情失败', error)
      await showSystemAlert({ title: '详情加载失败', message: error?.message || '请稍后再试', tone: 'danger' })
    } finally {
      setDetailLoading(false)
    }
  }

  async function compactOldDetails() {
    if (compactRunning) return
    const count = Number(compactEstimate?.estimated_compactable_total || 0)
    const savedMb = Number(compactEstimate?.estimated_saved_bytes || 0) / 1024 / 1024
    const ok = await showSystemConfirm({
      title: '归档 30 天前的大型详情',
      message: count ? `预计可压缩 ${count} 条，释放约 ${savedMb.toFixed(1)} MB。记录本身不会删除。` : '当前可能没有可归档的大型详情，仍要执行一次检查吗？',
      tone: 'warning',
      confirmText: '开始归档'
    })
    if (!ok) return
    setCompactRunning(true)
    try {
      let totalUpdated = 0
      let totalSaved = 0
      let safety = 10
      while (safety-- > 0) {
        const result = await activityLogApi.compact({ older_than_days: 30, time_budget_seconds: 5 })
        totalUpdated += Number(result.updated || 0)
        totalSaved += Number(result.saved_bytes || 0)
        if (result.done) break
      }
      detailCacheRef.current.clear()
      await showSystemAlert({
        title: totalUpdated ? '归档完成' : '无需归档',
        message: totalUpdated ? `已归档 ${totalUpdated} 条旧记录，释放 ${(totalSaved / 1024 / 1024).toFixed(2)} MB。` : '当前没有需要归档的旧记录。',
        tone: totalUpdated ? 'success' : 'info'
      })
      await loadAll()
    } finally {
      setCompactRunning(false)
    }
  }

  async function rebuildFts() {
    const ok = await showSystemConfirm({
      title: '重建操作记录搜索索引',
      message: '后台会把操作记录同步到 trigram FTS 索引，搜索会更稳。执行期间列表仍可使用。',
      tone: 'info',
      confirmText: '重建索引'
    })
    if (!ok) return
    await activityLogApi.rebuildFts('trigram')
    await loadSearchStatus()
  }

  const metrics = useMemo(() => metricCards(stats), [stats])
  const timelineGroups = useMemo(() => groupTimeline(rows), [rows])
  const spark = useMemo(() => buildSparkline(stats.by_day, 420, 96), [stats.by_day])
  const categories = useMemo(() => categoryRows(stats), [stats])
  const lastLoadedText = lastLoadedAt ? `上次刷新 ${formatFullDateTime(lastLoadedAt).slice(-8)}` : ''
  const pageCount = Math.max(1, Math.ceil(total / limit))
  const activeFilters = category !== 'all' || status !== 'all' || Boolean(query.trim())
  const searchHint = getSearchHint(searchStatus, searchBackend)
  const compactSavings = Number(compactEstimate?.estimated_saved_bytes || 0) / 1024 / 1024

  return (
    <div className="km-page activity-page">
      <PageHeader
        eyebrow="操作审计"
        title="操作记录"
        description="按任务链路聚合字幕、解压、入库、删除、ASMR 同步、上传和问题处理记录。"
        actions={(
          <>
            <Button onClick={compactOldDetails} loading={compactRunning}>
              <Archive size={15} />
              归档老记录
              {compactSavings >= 0.5 ? <span className="activity-button-hint">{compactSavings.toFixed(1)} MB</span> : null}
            </Button>
            <Button variant="primary" onClick={loadAll} loading={loading}>
              <RefreshCcw size={16} />
              刷新
            </Button>
          </>
        )}
      />

      <section className="activity-search-row glass-panel">
        <div className="activity-search-box">
          <Search size={15} strokeWidth={2.4} />
          <input
            value={query}
            placeholder={searchStatus?.rebuild?.running ? '索引重建中...' : '搜索 RJ、摘要、路径、任务 ID...'}
            onChange={event => scheduleSearch(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') runSearchNow() }}
          />
          {loading && query ? <Loader2 size={14} className="km-spin" /> : null}
          {query ? (
            <IconButton title="清空搜索" onClick={() => { setQuery(''); setPage(1); window.setTimeout(() => loadList(1), 0) }}>
              <X size={13} />
            </IconButton>
          ) : null}
        </div>
        {searchHint ? (
          <button type="button" className={`activity-search-hint tone-${searchHint.tone}`} onClick={searchHint.actionable ? rebuildFts : undefined}>
            {searchHint.icon ? <searchHint.icon size={13} strokeWidth={2.5} className={searchStatus?.rebuild?.running ? 'km-spin' : ''} /> : null}
            <span>{searchHint.text}</span>
            {searchHint.actionable ? <b>升级</b> : null}
          </button>
        ) : null}
      </section>

      <section className="activity-metric-strip glass-panel">
        <div className="activity-strip-head">
          <span>关键指标</span>
          <AppDropdown value={String(statsDays)} onChange={value => setStatsDays(Number(value || 14))} options={statsDaysOptions} width={140} />
        </div>
        <div className="activity-metric-row">
          {metrics.map(item => {
            const metric = splitMetric(item.value)
            return (
              <div key={item.key} className="activity-metric-cell" title={item.hint}>
                <span>{item.label}</span>
                <strong>{metric.num}</strong>
                {metric.unit ? <em>{metric.unit}</em> : null}
              </div>
            )
          })}
        </div>
      </section>

      <section className="activity-overview-grid">
        <article className="activity-overview-card glass-panel">
          <header>
            <span>每日操作量</span>
            <em>{formatNumber(stats.total_in_range)} 条</em>
          </header>
          {spark ? (
            <div className="activity-spark-wrap">
              <svg viewBox={`0 0 ${spark.width} ${spark.height}`} preserveAspectRatio="none">
                <defs>
                  <linearGradient id="activitySparkGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.28" />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d={spark.area} fill="url(#activitySparkGradient)" />
                <path d={spark.line} fill="none" stroke="#38bdf8" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx={spark.last.x} cy={spark.last.y} r="3.5" fill="#67e8f9" />
              </svg>
              <footer>
                <span>{formatShortDate(spark.points[0]?.date)}</span>
                <span>{formatShortDate(spark.points.at(-1)?.date)}</span>
              </footer>
            </div>
          ) : <div className="activity-empty-mini">暂无趋势</div>}
        </article>

        <article className="activity-overview-card glass-panel">
          <header>
            <span>分类分布</span>
            <em>{categories.length} 项</em>
          </header>
          <div className="activity-category-bars">
            {categories.length ? categories.map(item => (
              <div key={item.key} className={`activity-category-bar tone-${item.tone}`}>
                <i />
                <span>{item.label}</span>
                <b><em style={{ width: `${item.pct}%` }} /></b>
                <strong>{formatNumber(item.count)}</strong>
              </div>
            )) : <div className="activity-empty-mini">暂无分类</div>}
          </div>
        </article>
      </section>

      <section className="activity-filter-bar glass-panel">
        <AppDropdown value={category} onChange={value => { setCategory(value); setPage(1) }} options={activityCategoryOptions} width={210} />
        <AppDropdown value={status} onChange={value => { setStatus(value); setPage(1) }} options={activityStatusOptions} width={160} />
        <AppDropdown value={String(limit)} onChange={value => { setLimit(Number(value || 50)); setPage(1) }} options={activityPageSizeOptions} width={130} />
        {activeFilters ? (
          <Button onClick={resetFilters}>
            <FilterX size={14} />
            重置筛选
          </Button>
        ) : null}
      </section>

      <ActivityTimeline
        groups={timelineGroups}
        selectedId={selectedLiteRow?.id}
        loading={loading}
        onOpen={openDetail}
      />

      <footer className="activity-footer glass-panel">
        <div>
          <span>共 {formatNumber(total)} 条</span>
          {lastLoadedText ? <em>{lastLoadedText}</em> : null}
        </div>
        <div className="activity-pager">
          <Button disabled={page <= 1 || loading} onClick={() => { const next = Math.max(1, page - 1); setPage(next); loadList(next) }}>上一页</Button>
          <span>{page} / {pageCount}</span>
          <Button disabled={page >= pageCount || loading} onClick={() => { const next = Math.min(pageCount, page + 1); setPage(next); loadList(next) }}>下一页</Button>
        </div>
      </footer>

      <AnimatePresence>
        {selectedLiteRow ? (
          <ActivityDetailDrawer
            key={selectedLiteRow.id}
            row={selectedRow || selectedLiteRow}
            loading={detailLoading}
            onClose={() => { setSelectedLiteRow(null); setSelectedRow(null) }}
            onOpenRow={openDetail}
          />
        ) : null}
      </AnimatePresence>
    </div>
  )
}

function getSearchHint(status, backend) {
  const rebuild = status?.rebuild || {}
  if (rebuild.running) {
    const total = Number(rebuild.total || 0)
    const copied = Number(rebuild.copied || 0)
    const pct = total > 0 ? Math.round((copied / total) * 100) : 0
    return { tone: 'info', icon: Loader2, text: `搜索索引重建中 ${copied}/${total || '?'} ${pct ? `${pct}%` : ''}` }
  }
  if (status?.needs_upgrade) return { tone: 'warn', icon: Zap, text: '搜索索引可升级到 trigram', actionable: true }
  if (backend && backend !== 'none' && backend !== 'fts5_trigram') {
    if (backend.includes('unicode61')) return { tone: 'warn', icon: Zap, text: '当前搜索为 unicode61，建议升级', actionable: true }
    if (backend.includes('unavailable') || backend === 'error') return { tone: 'danger', icon: Zap, text: '搜索索引不可用，点此重建', actionable: true }
  }
  return null
}
