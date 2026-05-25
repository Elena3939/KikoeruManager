import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ListTodo, RefreshCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { taskCenterApi } from '../../api'
import { Button, PageHeader } from '../components/Primitives'
import { showSystemAlert } from '../stores/systemPromptStore'
import { TaskDetailPane } from './tasks/TaskDetailPane'
import { TaskListPane } from './tasks/TaskListPane'
import { TasksFilters } from './tasks/TasksFilters'
import { TasksMetricsBar } from './tasks/TasksMetricsBar'
import {
  ACTIVE_STATUSES,
  buildFileTreeSections,
  domainOptions,
  getCircleIndexMetaEntries,
  getCircleIndexProgressLog,
  getTaskId,
  sortTasks,
  statusOptions
} from './tasks/taskUtils'

const DETAIL_REFRESH_INTERVAL_MS = 15000

function buildSummarySyncSignature(summary) {
  if (!summary) return ''
  return [
    String(getTaskId(summary) || ''),
    String(summary.status || ''),
    String(summary.progress ?? ''),
    String(summary.current_step || ''),
    String(summary.error_message || ''),
    String(summary.started_at || ''),
    String(summary.completed_at || ''),
    String(summary.updated_at || '')
  ].join('|')
}

function normalizeListPayload(payload) {
  if (Array.isArray(payload)) return { items: payload, total: payload.length }
  const items = Array.isArray(payload?.items) ? payload.items : []
  return { items, total: Number(payload?.total ?? items.length) }
}

export function TasksPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [items, setItems] = useState([])
  const [totalItems, setTotalItems] = useState(0)
  const [pageSize] = useState(80)
  const [currentOffset, setCurrentOffset] = useState(0)
  const [selectedItemId, setSelectedItemId] = useState('')
  const [selectedItemDetail, setSelectedItemDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [currentDomain, setCurrentDomain] = useState('all')
  const [currentStatus, setCurrentStatus] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  const [overviewHighlightCounts, setOverviewHighlightCounts] = useState({})
  const [overviewDomainCounts, setOverviewDomainCounts] = useState({})
  const [sortKey, setSortKey] = useState('updated_desc')
  const [activeOnly, setActiveOnly] = useState(false)
  const [treeExpandedState, setTreeExpandedState] = useState({})
  const [treeFilterMode, setTreeFilterMode] = useState('all')

  const refreshingRef = useRef(false)
  const queuedRefreshRef = useRef(false)
  const selectedItemIdRef = useRef('')
  const itemsRef = useRef([])
  const detailLoadingRef = useRef(false)
  const lastDetailFetchedAtRef = useRef(0)
  const lastDetailSyncSignatureRef = useRef('')

  useEffect(() => {
    selectedItemIdRef.current = selectedItemId
  }, [selectedItemId])

  useEffect(() => {
    itemsRef.current = items
  }, [items])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchQuery(String(searchQuery || '').trim())
      setCurrentOffset(0)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [searchQuery])

  const filteredItems = useMemo(() => {
    const base = activeOnly
      ? items.filter(item => ACTIVE_STATUSES.has(String(item?.status || '').trim()))
      : items
    return sortTasks(base, sortKey)
  }, [activeOnly, items, sortKey])

  const selectedItem = useMemo(() => {
    if (!filteredItems.length) return null
    const summary = filteredItems.find(item => getTaskId(item) === selectedItemId) || filteredItems[0]
    if (selectedItemDetail && getTaskId(selectedItemDetail) === getTaskId(summary)) {
      return { ...summary, ...selectedItemDetail }
    }
    return summary
  }, [filteredItems, selectedItemDetail, selectedItemId])

  const selectedItemFileTreeSections = useMemo(
    () => buildFileTreeSections(selectedItem, treeExpandedState, treeFilterMode),
    [selectedItem, treeExpandedState, treeFilterMode]
  )

  const metrics = useMemo(() => ([
    { key: 'processing', label: '处理中', value: Number(overviewHighlightCounts.processing || 0), status: 'processing', tone: 'processing' },
    { key: 'waiting_manual', label: '等待人工', value: Number(overviewHighlightCounts.waiting_manual || 0), status: 'waiting_manual', tone: 'waiting_manual' },
    { key: 'waiting_retry', label: '等待重试', value: Number(overviewHighlightCounts.waiting_retry || 0), status: 'waiting_retry', tone: 'waiting_retry' },
    { key: 'failed', label: '失败', value: Number(overviewHighlightCounts.failed || 0), status: 'failed', tone: 'failed' }
  ]), [overviewHighlightCounts])

  const fetchSelectedItemDetail = useCallback(async (itemId, options = {}) => {
    if (!itemId) return
    const { force = false, silent = false } = options
    if (!force && detailLoadingRef.current) return
    detailLoadingRef.current = true
    if (!silent) setDetailLoading(true)
    try {
      const detail = await taskCenterApi.getItem({ item_id: itemId, _t: Date.now() })
      if (selectedItemIdRef.current === itemId) {
        setSelectedItemDetail(detail || null)
        const currentSummary = itemsRef.current.find(item => getTaskId(item) === itemId)
        lastDetailSyncSignatureRef.current = buildSummarySyncSignature(currentSummary || detail || {})
        lastDetailFetchedAtRef.current = Date.now()
      }
    } catch (error) {
      console.error('获取任务详情失败:', error)
    } finally {
      detailLoadingRef.current = false
      if (!silent) setDetailLoading(false)
    }
  }, [])

  const refreshTaskCenter = useCallback(async (options = {}) => {
    const { silent = false, showMessage = false } = options
    if (refreshingRef.current) {
      queuedRefreshRef.current = true
      return
    }
    refreshingRef.current = true
    setRefreshing(true)
    if (!silent) setLoading(true)
    try {
      const params = {
        mode: 'summary',
        limit: pageSize,
        offset: currentOffset,
        _t: Date.now()
      }
      if (currentDomain !== 'all') params.domain = currentDomain
      if (currentStatus !== 'all') params.status = currentStatus
      if (debouncedSearchQuery) params.search = debouncedSearchQuery

      const [overviewData, listData] = await Promise.all([
        taskCenterApi.overview({ _t: Date.now() }),
        taskCenterApi.list(params)
      ])
      const next = normalizeListPayload(listData)
      setOverviewHighlightCounts(overviewData?.highlight_counts || {})
      setOverviewDomainCounts(overviewData?.counts_by_domain || {})
      setItems(next.items)
      setTotalItems(next.total)

      if (next.total > 0 && currentOffset >= next.total) {
        setCurrentOffset(Math.max(0, Math.floor((next.total - 1) / pageSize) * pageSize))
      }

      const selectedId = selectedItemIdRef.current
      const selectedSummary = next.items.find(item => getTaskId(item) === selectedId)
      if (selectedSummary) {
        const signature = buildSummarySyncSignature(selectedSummary)
        const shouldRefreshBySignature = signature !== lastDetailSyncSignatureRef.current
        const shouldRefreshByInterval = Date.now() - lastDetailFetchedAtRef.current >= DETAIL_REFRESH_INTERVAL_MS
        if (shouldRefreshBySignature || shouldRefreshByInterval) {
          fetchSelectedItemDetail(selectedId, { silent: true }).catch(error => {
            console.error('任务详情同步刷新失败:', error)
          })
        }
      }

      if (showMessage) {
        await showSystemAlert({ title: '任务中心已刷新', tone: 'success' })
      }
    } catch (error) {
      console.error('获取任务中心失败:', error)
      if (!silent) {
        await showSystemAlert({
          title: '获取任务中心失败',
          message: error.response?.data?.detail || error.message,
          tone: 'danger'
        })
      }
    } finally {
      refreshingRef.current = false
      setRefreshing(false)
      if (!silent) setLoading(false)
      if (queuedRefreshRef.current) {
        queuedRefreshRef.current = false
        refreshTaskCenter({ silent: true }).catch(error => {
          console.error('任务中心补偿刷新失败:', error)
        })
      }
    }
  }, [currentDomain, currentOffset, currentStatus, debouncedSearchQuery, fetchSelectedItemDetail, pageSize])

  useEffect(() => {
    refreshTaskCenter({ silent: false }).catch(error => {
      console.error('任务中心初始化失败:', error)
    })
  }, [refreshTaskCenter])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      refreshTaskCenter({ silent: true }).catch(error => {
        console.error('任务中心轮询失败:', error)
      })
    }, 5000)
    return () => window.clearInterval(intervalId)
  }, [refreshTaskCenter])

  useEffect(() => {
    if (!filteredItems.length) {
      setSelectedItemId('')
      return
    }
    if (!filteredItems.some(item => getTaskId(item) === selectedItemId)) {
      setSelectedItemId(getTaskId(filteredItems[0]))
    }
  }, [filteredItems, selectedItemId])

  useEffect(() => {
    if (!selectedItemId) {
      setSelectedItemDetail(null)
      setTreeExpandedState({})
      setTreeFilterMode('all')
      lastDetailFetchedAtRef.current = 0
      lastDetailSyncSignatureRef.current = ''
      return
    }
    setSelectedItemDetail(null)
    setTreeExpandedState({})
    setTreeFilterMode('all')
    fetchSelectedItemDetail(selectedItemId, { force: true }).catch(error => {
      console.error('任务详情刷新失败:', error)
    })
  }, [fetchSelectedItemDetail, selectedItemId])

  function resetFilters() {
    setCurrentDomain('all')
    setCurrentStatus('all')
    setActiveOnly(false)
    setSearchQuery('')
    setDebouncedSearchQuery('')
    setCurrentOffset(0)
  }

  function applyQuickFilter(domain, status) {
    setCurrentDomain(domain || 'all')
    setCurrentStatus(status || 'all')
    setCurrentOffset(0)
  }

  async function handleTaskAction(item, action) {
    const id = getTaskId(item)
    if (!id) return
    try {
      const result = await taskCenterApi.action(id, action)
      if (result?.route_hint) navigate(result.route_hint)
      await showSystemAlert({ title: result?.message || '操作成功', tone: 'success' })
      await refreshTaskCenter({ silent: true })
    } catch (error) {
      console.error('执行任务动作失败:', error)
      await showSystemAlert({
        title: '操作失败',
        message: error.response?.data?.detail || error.message,
        tone: 'danger'
      })
    }
  }

  function openTaskRoute(item) {
    if (item?.route_hint) navigate(item.route_hint)
  }

  function setTreeSectionExpanded(section, expanded) {
    setTreeExpandedState(previous => {
      const next = { ...previous }
      for (const key of section?.directoryKeys || []) {
        next[key] = expanded
      }
      return next
    })
  }

  function toggleTreeNode(key) {
    setTreeExpandedState(previous => ({ ...previous, [key]: !(previous[key] ?? true) }))
  }

  return (
    <div className="km-page tasks-page">
      <PageHeader
        eyebrow="Task Center"
        title="任务中心"
        description="导入处理、RJ 字幕、字幕补配、ASMR 同步与系统任务的统一视图。"
        actions={(
          <>
            <span className="tasks-sync-pill">
              <span />
              实时同步
            </span>
            <Button variant="ghost" onClick={() => refreshTaskCenter({ showMessage: true })} loading={refreshing}>
              <RefreshCw size={15} strokeWidth={2.4} />
              刷新
            </Button>
          </>
        )}
      />

      <TasksMetricsBar metrics={metrics} onFilter={applyQuickFilter} />

      <TasksFilters
        domainOptions={domainOptions}
        statusOptions={statusOptions}
        currentDomain={currentDomain}
        currentStatus={currentStatus}
        searchQuery={searchQuery}
        sortKey={sortKey}
        activeOnly={activeOnly}
        getDomainCount={domain => overviewDomainCounts[domain]}
        onDomainChange={value => { setCurrentDomain(value); setCurrentOffset(0) }}
        onStatusChange={value => { setCurrentStatus(value); setCurrentOffset(0) }}
        onSearchChange={setSearchQuery}
        onSortChange={setSortKey}
        onActiveOnlyChange={setActiveOnly}
        onReset={resetFilters}
      />

      <section className="tasks-main">
        <TaskListPane
          items={filteredItems}
          totalItems={totalItems}
          currentOffset={currentOffset}
          pageSize={pageSize}
          selectedId={selectedItem ? getTaskId(selectedItem) : ''}
          loading={loading}
          onSelect={setSelectedItemId}
          onPrevPage={() => setCurrentOffset(value => Math.max(0, value - pageSize))}
          onNextPage={() => setCurrentOffset(value => value + pageSize)}
        />
        <TaskDetailPane
          item={selectedItem}
          detailLoading={detailLoading}
          fileTreeSections={selectedItemFileTreeSections}
          circleMeta={getCircleIndexMetaEntries(selectedItem)}
          circleLog={getCircleIndexProgressLog(selectedItem)}
          treeFilterMode={treeFilterMode}
          onOpenRoute={openTaskRoute}
          onAction={handleTaskAction}
          onTreeFilterModeChange={setTreeFilterMode}
          onExpandSection={setTreeSectionExpanded}
          onToggleNode={toggleTreeNode}
        />
      </section>
    </div>
  )
}
