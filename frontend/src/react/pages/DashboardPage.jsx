import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Captions, Database, FileArchive, ShieldAlert, Sparkles, Upload, UploadCloud } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { conflictApi, processedArchiveApi, scanApi, taskCenterApi, watcherApi } from '../../api'
import { showSystemAlert } from '../stores/systemPromptStore'
import { DashboardActiveTasks } from './dashboard/DashboardActiveTasks'
import { DashboardArchive } from './dashboard/DashboardArchive'
import { DashboardCommandStrip } from './dashboard/DashboardCommandStrip'
import { DashboardHero } from './dashboard/DashboardHero'
import { buildArchiveTabs, buildDisplayedArchives } from './dashboard/dashboardUtils'

const CONFLICT_REFRESH_INTERVAL = 30000

export function DashboardPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [watcherRunning, setWatcherRunning] = useState(false)
  const [overview, setOverview] = useState({
    recent_items: [],
    active_items: [],
    counts_by_domain: {},
    counts_by_status: {},
    highlight_counts: {},
    total: 0
  })
  const [stats, setStats] = useState({ pending: 0, processing: 0, completed: 0, conflicts: 0 })
  const [archives, setArchives] = useState([])
  const [archivesLoading, setArchivesLoading] = useState(false)
  const [reprocessingId, setReprocessingId] = useState(null)
  const [archivePage, setArchivePage] = useState(1)
  const [archiveSearchQuery, setArchiveSearchQuery] = useState('')
  const [archiveDomainFilter, setArchiveDomainFilter] = useState('all')

  const refreshRunningRef = useRef(false)
  const refreshPendingRef = useRef(false)
  const lastConflictRefreshTimeRef = useRef(0)
  const cachedConflictCountRef = useRef(0)
  const searchTimerRef = useRef(null)

  const domainCounts = useMemo(() => ({
    import: Number(overview?.counts_by_domain?.import || 0),
    rj_subtitle: Number(overview?.counts_by_domain?.rj_subtitle || 0),
    subtitle_import: Number(overview?.counts_by_domain?.subtitle_import || 0),
    asmr_sync: Number(overview?.counts_by_domain?.asmr_sync || 0),
    upload: Number(overview?.counts_by_domain?.upload || 0),
    circle_completion: Number(overview?.counts_by_domain?.circle_completion || 0)
  }), [overview])

  const recentTasks = useMemo(() => {
    const active = Array.isArray(overview?.active_items) ? overview.active_items : []
    const recent = Array.isArray(overview?.recent_items) ? overview.recent_items : []
    return active.length ? active : recent.slice(0, 10)
  }, [overview])

  const kpiCards = useMemo(() => ([
    { key: 'import', label: '导入处理', value: domainCounts.import, icon: FileArchive, route: '/library' },
    { key: 'rj', label: 'RJ 字幕', value: domainCounts.rj_subtitle, icon: Captions, route: '/library' },
    { key: 'subtitle', label: '字幕补配', value: domainCounts.subtitle_import, icon: Sparkles, route: '/subtitle-import' },
    { key: 'asmr', label: 'ASMR 同步', value: domainCounts.asmr_sync, icon: UploadCloud, route: '/asmr-sync' },
    { key: 'upload', label: '库存上传', value: domainCounts.upload, icon: Upload, route: '/library' },
    { key: 'conflicts', label: '问题作品', value: stats.conflicts, icon: ShieldAlert, route: '/conflicts' }
  ]), [domainCounts, stats.conflicts])

  const statusCards = useMemo(() => ([
    { key: 'processing', label: '处理中', value: Number(overview?.highlight_counts?.processing || 0) },
    { key: 'waiting', label: '等待人工', value: Number(overview?.highlight_counts?.waiting_manual || 0) },
    { key: 'retry', label: '等待重试', value: Number(overview?.highlight_counts?.waiting_retry || 0) },
    { key: 'failed', label: '失败', value: Number(overview?.highlight_counts?.failed || 0) }
  ]), [overview])

  const displayedArchives = useMemo(() => buildDisplayedArchives(archives, overview), [archives, overview])
  const archiveTabs = useMemo(() => buildArchiveTabs(displayedArchives), [displayedArchives])

  useEffect(() => {
    if (!archiveTabs.some(tab => tab.key === archiveDomainFilter)) setArchiveDomainFilter('all')
  }, [archiveDomainFilter, archiveTabs])

  const fetchWatcherStatus = useCallback(async () => {
    try {
      const data = await watcherApi.status()
      setWatcherRunning(Boolean(data?.is_running))
    } catch (error) {
      console.error('获取监视器状态失败:', error)
    }
  }, [])

  const fetchProcessedArchives = useCallback(async (options = {}) => {
    const { silent = false, scan = false, search = archiveSearchQuery } = options
    setArchivesLoading(true)
    try {
      if (scan) await processedArchiveApi.scan()
      const params = { sort_by: 'processed_at', sort_order: 'desc', limit: 500, offset: 0 }
      if (search) params.search = search
      const data = await processedArchiveApi.list(params)
      setArchives(data?.archives || [])
      if (!silent) await showSystemAlert({ title: '归档记录已刷新', tone: 'success' })
    } catch (error) {
      console.error('获取已处理压缩包列表失败:', error)
      if (!silent) await showSystemAlert({ title: '获取归档记录失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setArchivesLoading(false)
    }
  }, [archiveSearchQuery])

  const refreshData = useCallback(async (options = {}) => {
    const { silent = false, forceConflictRefresh = false } = options
    if (refreshRunningRef.current) {
      refreshPendingRef.current = true
      return
    }
    refreshRunningRef.current = true
    if (!silent) setLoading(true)
    try {
      const nextOverview = await taskCenterApi.overview({ _t: Date.now() })
      setOverview(nextOverview || {})

      const now = Date.now()
      const shouldRefreshConflicts =
        forceConflictRefresh ||
        !lastConflictRefreshTimeRef.current ||
        now - lastConflictRefreshTimeRef.current >= CONFLICT_REFRESH_INTERVAL
      if (shouldRefreshConflicts) {
        try {
          const data = await conflictApi.count()
          cachedConflictCountRef.current = Number(data?.count || 0)
          lastConflictRefreshTimeRef.current = now
        } catch (error) {
          console.error('获取问题作品数量失败:', error)
        }
      }

      setStats({
        pending: Number(nextOverview?.counts_by_status?.pending || 0),
        processing: Number(nextOverview?.counts_by_status?.processing || 0),
        completed: Number(nextOverview?.counts_by_status?.completed || 0),
        conflicts: cachedConflictCountRef.current
      })
    } catch (error) {
      console.error('获取概览失败:', error)
      if (!silent) await showSystemAlert({ title: '获取概览失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      refreshRunningRef.current = false
      if (!silent) setLoading(false)
      if (refreshPendingRef.current) {
        refreshPendingRef.current = false
        refreshData({ silent: true }).catch(error => console.error('概览补偿刷新失败:', error))
      }
    }
  }, [])

  const refreshDashboardOnResume = useCallback(async (silent = true) => {
    await refreshData({ silent, forceConflictRefresh: true })
    await fetchWatcherStatus()
    await fetchProcessedArchives({ silent: true })
  }, [fetchProcessedArchives, fetchWatcherStatus, refreshData])

  useEffect(() => {
    refreshDashboardOnResume(false).catch(error => console.error('初始化概览失败:', error))
  }, [refreshDashboardOnResume])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      refreshData({ silent: true }).catch(error => console.error('概览轮询失败:', error))
    }, 3000)
    return () => window.clearInterval(intervalId)
  }, [refreshData])

  useEffect(() => {
    function handleFocus() {
      if (document.visibilityState === 'hidden') return
      refreshData({ silent: true }).catch(error => console.error('概览焦点刷新失败:', error))
    }
    window.addEventListener('focus', handleFocus)
    document.addEventListener('visibilitychange', handleFocus)
    return () => {
      window.removeEventListener('focus', handleFocus)
      document.removeEventListener('visibilitychange', handleFocus)
    }
  }, [refreshData])

  useEffect(() => () => {
    if (searchTimerRef.current) window.clearTimeout(searchTimerRef.current)
  }, [])

  async function handleManualScan() {
    setScanning(true)
    try {
      const data = await scanApi.scan()
      await showSystemAlert({ title: data?.message || '扫描处理已启动', tone: 'success' })
      await refreshData({ forceConflictRefresh: true })
    } catch (error) {
      console.error('扫描失败:', error)
      await showSystemAlert({ title: '扫描失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setScanning(false)
    }
  }

  async function handleWatcherToggle() {
    try {
      if (watcherRunning) {
        await watcherApi.stop()
        setWatcherRunning(false)
        await showSystemAlert({ title: '监视器已停止', tone: 'success' })
      } else {
        await watcherApi.start()
        setWatcherRunning(true)
        await showSystemAlert({ title: '监视器已启动', tone: 'success' })
      }
    } catch (error) {
      console.error('操作监视器失败:', error)
      await showSystemAlert({ title: '操作监视器失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    }
  }

  async function refreshArchivePanel() {
    await refreshData({ silent: true })
    await fetchProcessedArchives({ scan: true })
  }

  function handleArchiveSearch(value) {
    const next = String(value || '')
    setArchiveSearchQuery(next)
    setArchivePage(1)
    if (searchTimerRef.current) window.clearTimeout(searchTimerRef.current)
    searchTimerRef.current = window.setTimeout(() => {
      fetchProcessedArchives({ silent: true, search: next }).catch(error => console.error('归档搜索刷新失败:', error))
    }, 400)
  }

  async function reprocessArchive(archiveId) {
    setReprocessingId(archiveId)
    try {
      const data = await processedArchiveApi.reprocess(archiveId)
      await showSystemAlert({ title: data?.message || '已提交重新处理', tone: 'success' })
      await refreshData({ forceConflictRefresh: true })
      await fetchProcessedArchives({ silent: true })
    } catch (error) {
      console.error('重新处理失败:', error)
      await showSystemAlert({ title: '重新处理失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setReprocessingId(null)
    }
  }

  async function handleTaskCenterAction(task, action) {
    try {
      const result = await taskCenterApi.action(task.id, action)
      if (result?.route_hint) navigate(result.route_hint)
      await showSystemAlert({ title: result?.message || '操作成功', tone: 'success' })
      await refreshData({ forceConflictRefresh: true })
    } catch (error) {
      console.error('执行任务中心动作失败:', error)
      await showSystemAlert({ title: '任务操作失败', message: error.response?.data?.detail || error.message, tone: 'danger' })
    }
  }

  return (
    <div className="km-page dashboard-page">
      <DashboardHero
        watcherRunning={watcherRunning}
        loading={loading}
        kpiCards={kpiCards}
        onRefresh={() => refreshDashboardOnResume(false)}
        onKpiClick={item => item.route && navigate(item.route)}
        onUploadSuccess={() => {
          refreshData({ forceConflictRefresh: true }).catch(error => console.error('上传后概览刷新失败:', error))
          fetchProcessedArchives({ silent: true }).catch(error => console.error('上传后归档刷新失败:', error))
        }}
      />
      <DashboardCommandStrip
        scanning={scanning}
        watcherRunning={watcherRunning}
        onScan={handleManualScan}
        onToggleWatcher={handleWatcherToggle}
        onGo={path => navigate(path)}
      />
      <main className="dashboard-main">
        <DashboardActiveTasks
          tasks={recentTasks}
          statusCards={statusCards}
          onGo={path => navigate(path)}
          onAction={handleTaskCenterAction}
        />
        <DashboardArchive
          items={displayedArchives}
          tabs={archiveTabs}
          searchQuery={archiveSearchQuery}
          domainFilter={archiveDomainFilter}
          loading={archivesLoading}
          reprocessingId={reprocessingId}
          page={archivePage}
          pageSize={10}
          onRefresh={refreshArchivePanel}
          onReprocess={reprocessArchive}
          onChangePage={setArchivePage}
          onSearchChange={handleArchiveSearch}
          onDomainChange={value => {
            setArchiveDomainFilter(value)
            setArchivePage(1)
          }}
        />
      </main>
    </div>
  )
}
