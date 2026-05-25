import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CloudDownload,
  Database,
  Download,
  Eye,
  File,
  FileText,
  Folder,
  FolderSearch,
  Hourglass,
  Loader2,
  Pause,
  Package,
  Play,
  RefreshCcw,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
  Upload,
  X
} from 'lucide-react'
import { asmrSyncApi, configApi, libraryApi, taskApi } from '../../api'
import { useInterval } from '../hooks/useAsync'
import { Button, Card, EmptyState, Field, IconButton, LoadingState, Modal, PageHeader, TextArea, TextInput } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm } from '../stores/systemPromptStore'
import { cx, formatBytes, normalizeListPayload } from '../utils/format'

const WORKBENCH_KEY = 'kikoerumanager.asmrSync.downloadWorkbench'

const resourceTypeOptions = [
  { key: 'audio', label: '音频' },
  { key: 'subtitle', label: '字幕' },
  { key: 'cover', label: '封面' },
  { key: 'image', label: '图片' },
  { key: 'text', label: '文本' }
]

const statusText = {
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  paused: '已暂停',
  waiting_retry: '等待重试',
  cancelled: '已取消'
}

export function ASMRSyncPage() {
  const [subtitleFolder, setSubtitleFolder] = useState('')
  const [scanResults, setScanResults] = useState([])
  const [selectedScan, setSelectedScan] = useState(new Set())
  const [previewData, setPreviewData] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [tasks, setTasks] = useState([])
  const [nextRetryTime, setNextRetryTime] = useState('')
  const [dashboard, setDashboard] = useState({})
  const [sessions, setSessions] = useState([])
  const [libraries, setLibraries] = useState([])
  const [enhancedInput, setEnhancedInput] = useState('')
  const [resourceTypes, setResourceTypes] = useState(['audio', 'subtitle', 'cover'])
  const [includeExisting, setIncludeExisting] = useState(false)
  const [enhancedPlans, setEnhancedPlans] = useState([])
  const [selectedPlans, setSelectedPlans] = useState(new Set())
  const [selectedResources, setSelectedResources] = useState({})
  const [workbenchTaskIds, setWorkbenchTaskIds] = useState([])
  const [workbenchVisible, setWorkbenchVisible] = useState(false)
  const [workbenchBackground, setWorkbenchBackground] = useState(false)
  const [workbenchTasks, setWorkbenchTasks] = useState([])
  const [sessionDetail, setSessionDetail] = useState(null)
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false)
  const [downloadBasePath, setDownloadBasePath] = useState('')
  const [targetLibraryId, setTargetLibraryId] = useState('')
  const [targetSubdir, setTargetSubdir] = useState('')
  const [loading, setLoading] = useState({
    scan: false,
    sync: false,
    refresh: false,
    planning: false,
    enhancedStart: false,
    dashboard: false,
    sessions: false,
    sessionDetail: false,
    workbench: false
  })

  const selectedScanItems = useMemo(
    () => scanResults.filter(item => selectedScan.has(item.rjcode)),
    [scanResults, selectedScan]
  )
  const waitingRetryTasks = useMemo(() => tasks.filter(task => task.status === 'waiting_retry'), [tasks])
  const activeTasks = useMemo(() => tasks.filter(task => task.status !== 'waiting_retry'), [tasks])
  const selectedPlanList = useMemo(
    () => enhancedPlans.filter(plan => selectedPlans.has(plan.rjcode)),
    [enhancedPlans, selectedPlans]
  )
  const metricCards = useMemo(() => buildMetricCards(dashboard), [dashboard])
  const workbenchStats = useMemo(() => buildWorkbenchStats(workbenchTasks), [workbenchTasks])
  const backgroundCard = workbenchBackground && !workbenchVisible && workbenchTaskIds.length > 0

  useEffect(() => {
    hydrateWorkbench()
    initialize()
  }, [])

  useInterval(refreshStatus, 3000, true)
  useInterval(() => refreshWorkbench({ silent: true }), 2200, workbenchTaskIds.length > 0 && (workbenchVisible || workbenchBackground))

  useEffect(() => {
    persistWorkbench()
  }, [workbenchTaskIds, workbenchVisible, workbenchBackground])

  async function initialize() {
    await Promise.all([
      loadSavedConfig(),
      loadLibraries(),
      refreshDashboard(),
      refreshSessions(),
      refreshStatus()
    ])
  }

  async function loadSavedConfig() {
    try {
      const config = await configApi.get()
      if (config?.storage?.asmr_subtitle_path) setSubtitleFolder(config.storage.asmr_subtitle_path)
      if (config?.storage?.temp_path) setDownloadBasePath(`${String(config.storage.temp_path).replace(/[\\/]$/, '')}/asmr_enhanced`)
      if (config?.asmr_sync?.auto_upload_library_id) setTargetLibraryId(config.asmr_sync.auto_upload_library_id)
      if (config?.asmr_sync?.auto_upload_target_path) setTargetSubdir(config.asmr_sync.auto_upload_target_path)
    } catch (error) {
      console.warn('[ASMR] 加载配置失败', error)
    }
  }

  async function loadLibraries() {
    try {
      const result = await libraryApi.listLibraries()
      const list = Array.isArray(result?.libraries) ? result.libraries : normalizeListPayload(result)
      setLibraries(list)
      if (!targetLibraryId && list[0]?.id) setTargetLibraryId(list[0].id)
    } catch (error) {
      console.warn('[ASMR] 加载库存失败', error)
    }
  }

  async function refreshDashboard() {
    setLoadingFlag('dashboard', true)
    try {
      const result = await asmrSyncApi.dashboardEnhanced()
      setDashboard(result?.dashboard || result || {})
    } finally {
      setLoadingFlag('dashboard', false)
    }
  }

  async function refreshSessions() {
    setLoadingFlag('sessions', true)
    try {
      const result = await asmrSyncApi.sessionsEnhanced(80)
      setSessions(result?.sessions || [])
    } finally {
      setLoadingFlag('sessions', false)
    }
  }

  async function refreshStatus() {
    setLoadingFlag('refresh', true)
    try {
      const [statusResult, waitingResult] = await Promise.all([
        asmrSyncApi.status().catch(() => ({ tasks: [] })),
        asmrSyncApi.getWaitingRetry().catch(() => ({ tasks: [] }))
      ])
      const baseTasks = Array.isArray(statusResult?.tasks) ? statusResult.tasks : []
      const waitingTasks = (waitingResult?.tasks || []).map(item => ({
        id: item.id,
        rjcode: item.rjcode,
        work_title: item.work_title,
        status: 'waiting_retry',
        progress: 0,
        current_step: `等待重试: ${item.retry_reason || '未找到版本'}`,
        task_metadata: {
          retry_reason: item.retry_reason,
          retry_count: item.retry_count,
          retry_after: item.retry_after,
          subtitle_folder: item.subtitle_folder
        }
      }))
      const seen = new Set(baseTasks.map(task => String(task.id)))
      setTasks([...baseTasks, ...waitingTasks.filter(task => !seen.has(String(task.id)))])
      setNextRetryTime(waitingResult?.next_retry_time || '')
      setScanResults(prev => prev.map(item => {
        const task = baseTasks.find(row => row.rjcode === item.rjcode)
        if (!task) return item
        return { ...item, status: task.status === 'processing' ? 'downloading' : task.status, taskId: task.id }
      }))
    } finally {
      setLoadingFlag('refresh', false)
    }
  }

  async function scanFolder() {
    if (!subtitleFolder.trim()) {
      await showSystemAlert({ title: '请先输入字幕文件夹路径', tone: 'warning' })
      return
    }
    setLoadingFlag('scan', true)
    setScanResults([])
    setSelectedScan(new Set())
    try {
      const result = await asmrSyncApi.scan(subtitleFolder.trim())
      const items = (result?.items || []).map(item => ({ ...item, status: 'pending', previewing: false }))
      setScanResults(items)
      setSelectedScan(new Set(items.map(item => item.rjcode).filter(Boolean)))
      await showSystemAlert({ title: `发现 ${result?.total_found ?? items.length} 个作品`, tone: 'success' })
    } catch (error) {
      await showSystemAlert({ title: '扫描失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setLoadingFlag('scan', false)
    }
  }

  async function previewDownload(row) {
    setPreviewLoading(true)
    setPreviewData({ rjcode: row.rjcode, loading: true })
    setScanResults(prev => prev.map(item => item.rjcode === row.rjcode ? { ...item, previewing: true } : item))
    try {
      const result = await asmrSyncApi.preview(row.rjcode)
      setPreviewData(result)
      if (!result?.success) {
        await showSystemAlert({ title: '未找到可用版本', message: result?.error || 'asmr.one 暂无该作品版本', tone: 'warning' })
      }
    } catch (error) {
      await showSystemAlert({ title: '获取预览失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setPreviewLoading(false)
      setScanResults(prev => prev.map(item => item.rjcode === row.rjcode ? { ...item, previewing: false } : item))
    }
  }

  async function startSync() {
    if (!selectedScanItems.length) {
      await showSystemAlert({ title: '请先选择要下载的作品', tone: 'warning' })
      return
    }
    setLoadingFlag('sync', true)
    try {
      const payload = selectedScanItems.map(item => ({
        rjcode: item.rjcode,
        subtitle_folder: item.folder_path,
        work_title: item.folder_name
      }))
      const result = await asmrSyncApi.start(payload, true)
      const ids = (result?.tasks || []).map(item => item.task_id).filter(Boolean)
      if (ids.length) mergeWorkbenchIds(ids, true)
      setScanResults(prev => prev.map(item => {
        const task = (result?.tasks || []).find(row => row.rjcode === item.rjcode)
        return task ? { ...item, status: 'downloading', taskId: task.task_id } : item
      }))
      await refreshStatus()
      await showSystemAlert({ title: result?.message || '下载任务已创建', tone: 'success' })
    } catch (error) {
      await showSystemAlert({ title: '启动下载失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setLoadingFlag('sync', false)
    }
  }

  async function buildEnhancedPlans() {
    const rjcodes = parseRJCodes(enhancedInput)
    if (!rjcodes.length) {
      await showSystemAlert({ title: '请先输入至少一个 RJ 号', tone: 'warning' })
      return
    }
    setLoadingFlag('planning', true)
    try {
      const result = await asmrSyncApi.planEnhanced({
        rjcodes,
        folder_path: '',
        resource_types: resourceTypes,
        audio_formats: [],
        subtitle_languages: [],
        include_existing: includeExisting
      })
      const plans = (result?.plans || []).map(plan => ({
        ...plan,
        selectable_resources: (plan.selectable_resources || []).map(item => ({ ...item, selected: item.selected !== false }))
      }))
      setEnhancedPlans(plans)
      setSelectedPlans(new Set(plans.map(plan => plan.rjcode)))
      setSelectedResources(Object.fromEntries(plans.map(plan => [
        plan.rjcode,
        new Set((plan.selectable_resources || []).filter(item => item.selected !== false).map(resourceKey))
      ])))
      await refreshDashboard()
      await showSystemAlert({
        title: result?.errors?.length ? '增强计划部分生成' : '增强计划已生成',
        message: result?.errors?.length ? `成功 ${result.planned_count || plans.length} 个，失败 ${result.errors.length} 个。` : `已生成 ${result?.planned_count || plans.length} 个计划。`,
        tone: result?.errors?.length ? 'warning' : 'success'
      })
    } catch (error) {
      await showSystemAlert({ title: '生成下载计划失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setLoadingFlag('planning', false)
    }
  }

  async function startEnhancedDownload() {
    const items = selectedPlanList.map(plan => {
      const selected = selectedResources[plan.rjcode] || new Set()
      const resources = (plan.selectable_resources || []).filter(resource => selected.has(resourceKey(resource)))
      return {
        rjcode: plan.rjcode,
        session_id: plan.session_id,
        work_title: plan.work_title || plan.title || plan.source_label || '',
        cover_url: plan.cover_url || plan.image_url || '',
        folder_path: plan.folder_path || '',
        download_base_path: downloadBasePath || '',
        selected_resources: resources,
        resource_filter_snapshot: { resource_types: resourceTypes, include_existing: includeExisting },
        upload_options: buildUploadOptions(),
        queue_priority: 100,
        verify_md5_after_download: true
      }
    }).filter(item => item.session_id && item.selected_resources.length)

    if (!items.length) {
      await showSystemAlert({ title: '没有可启动的增强下载任务', message: '请确认已选择计划和资源。', tone: 'warning' })
      return
    }
    setLoadingFlag('enhancedStart', true)
    try {
      const result = await asmrSyncApi.startEnhanced(items)
      const ids = (result?.tasks || []).map(task => task.task_id).filter(Boolean)
      mergeWorkbenchIds(ids, true)
      await Promise.all([refreshStatus(), refreshDashboard(), refreshSessions()])
      await showSystemAlert({ title: result?.message || '增强下载任务已创建', tone: 'success' })
    } catch (error) {
      await showSystemAlert({ title: '启动增强下载失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setLoadingFlag('enhancedStart', false)
    }
  }

  function buildUploadOptions() {
    if (!targetLibraryId) return { mode: 'disabled' }
    const library = libraries.find(item => String(item.id) === String(targetLibraryId))
    return {
      mode: library?.type === 'synology' ? 'synology' : 'local',
      library_id: targetLibraryId,
      target_subdir: targetSubdir || '',
      target_path: targetSubdir || library?.path || ''
    }
  }

  async function refreshWorkbench(options = {}) {
    if (!workbenchTaskIds.length) {
      setWorkbenchTasks([])
      return
    }
    if (!options.silent) setLoadingFlag('workbench', true)
    try {
      const result = await asmrSyncApi.status()
      const allTasks = Array.isArray(result?.tasks) ? result.tasks : []
      const nextTasks = workbenchTaskIds.map(id => allTasks.find(task => String(task.id) === String(id))).filter(Boolean)
      setWorkbenchTasks(nextTasks)
      setWorkbenchTaskIds(nextTasks.map(task => task.id))
    } finally {
      if (!options.silent) setLoadingFlag('workbench', false)
    }
  }

  function mergeWorkbenchIds(ids, show = false) {
    setWorkbenchTaskIds(prev => [...ids, ...prev.filter(id => !ids.includes(id))])
    if (show) {
      setWorkbenchVisible(true)
      setWorkbenchBackground(false)
    }
  }

  function hydrateWorkbench() {
    try {
      const raw = JSON.parse(localStorage.getItem(WORKBENCH_KEY) || '{}')
      const ids = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
      setWorkbenchTaskIds(ids)
      setWorkbenchVisible(Boolean(raw.visible && ids.length))
      setWorkbenchBackground(Boolean(raw.background && ids.length))
    } catch {
      setWorkbenchTaskIds([])
    }
  }

  function persistWorkbench() {
    try {
      localStorage.setItem(WORKBENCH_KEY, JSON.stringify({
        taskIds: workbenchTaskIds,
        visible: workbenchVisible,
        background: workbenchBackground
      }))
    } catch {}
  }

  function closeWorkbench() {
    setWorkbenchTaskIds([])
    setWorkbenchTasks([])
    setWorkbenchVisible(false)
    setWorkbenchBackground(false)
    try { localStorage.removeItem(WORKBENCH_KEY) } catch {}
  }

  async function taskAction(task, action) {
    const taskId = task?.id || task?.active_task_id
    const sessionId = task?.session_id || task?.task_metadata?.session_id
    try {
      if (action === 'pause') {
        if (sessionId) await asmrSyncApi.pauseSession(sessionId)
        else await asmrSyncApi.pause(taskId)
      } else if (action === 'resume') {
        if (sessionId) await asmrSyncApi.resumeSession(sessionId)
        else await asmrSyncApi.resume(taskId)
      } else if (action === 'retry') {
        if (sessionId) await asmrSyncApi.retryFailedSession(sessionId)
        else await asmrSyncApi.retry(taskId)
      } else if (action === 'cancel') {
        const ok = await confirmOrFalse({
          title: '取消下载任务',
          message: `确定取消 ${task.rjcode || task.work_title || taskId} 吗？`,
          tone: 'danger',
          confirmText: '取消下载'
        })
        if (!ok) return
        if (sessionId) await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
        else await taskApi.batchCancelCleanup([taskId])
      } else if (action === 'retryWaiting') {
        await asmrSyncApi.retryWaiting(taskId)
      } else if (action === 'deleteWaiting') {
        await asmrSyncApi.deleteWaitingRetry(taskId)
      }
      await Promise.all([refreshStatus(), refreshWorkbench({ silent: true }), refreshSessions(), refreshDashboard()])
    } catch (error) {
      await showSystemAlert({ title: '操作失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    }
  }

  async function openSession(session) {
    setSessionDrawerOpen(true)
    setSessionDetail(null)
    setLoadingFlag('sessionDetail', true)
    try {
      const result = await asmrSyncApi.sessionEnhanced(session.id)
      setSessionDetail(result?.session || null)
    } catch (error) {
      await showSystemAlert({ title: '加载会话详情失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    } finally {
      setLoadingFlag('sessionDetail', false)
    }
  }

  async function sessionAction(session, action) {
    try {
      if (action === 'pause') await asmrSyncApi.pauseSession(session.id)
      if (action === 'resume') await asmrSyncApi.resumeSession(session.id)
      if (action === 'retry') await asmrSyncApi.retryFailedSession(session.id)
      if (action === 'priorityUp') await asmrSyncApi.updateSessionPriority(session.id, Math.max(1, Number(session.queue_priority || 100) - 10))
      if (action === 'priorityDown') await asmrSyncApi.updateSessionPriority(session.id, Number(session.queue_priority || 100) + 10)
      await Promise.all([refreshSessions(), refreshStatus(), refreshDashboard()])
    } catch (error) {
      await showSystemAlert({ title: '会话操作失败', message: error?.response?.data?.detail || error.message, tone: 'danger' })
    }
  }

  function toggleScan(rjcode) {
    setSelectedScan(prev => {
      const next = new Set(prev)
      if (next.has(rjcode)) next.delete(rjcode)
      else next.add(rjcode)
      return next
    })
  }

  function togglePlan(rjcode) {
    setSelectedPlans(prev => {
      const next = new Set(prev)
      if (next.has(rjcode)) next.delete(rjcode)
      else next.add(rjcode)
      return next
    })
  }

  function toggleResource(plan, resource) {
    const key = resourceKey(resource)
    setSelectedResources(prev => {
      const next = { ...prev }
      const set = new Set(next[plan.rjcode] || [])
      if (set.has(key)) set.delete(key)
      else set.add(key)
      next[plan.rjcode] = set
      return next
    })
  }

  function applyPlanPreset(plan, presetKey) {
    const preset = new Set(plan?.selection_presets?.[presetKey] || [])
    setSelectedResources(prev => ({ ...prev, [plan.rjcode]: preset }))
  }

  function setLoadingFlag(key, value) {
    setLoading(prev => ({ ...prev, [key]: value }))
  }

  return (
    <div className="km-page asmr-sync-page">
      <PageHeader
        eyebrow="ASMR 下载"
        title="ASMR 同步下载"
        description="根据字幕目录创建下载任务，也可以手动构建增强下载计划并跟踪会话。"
        actions={(
          <>
            <Button disabled={loading.scan || !subtitleFolder.trim()} onClick={scanFolder} loading={loading.scan}>
              <Search size={16} />扫描
            </Button>
            <Button variant="primary" disabled={loading.sync || !selectedScanItems.length} onClick={startSync} loading={loading.sync}>
              <Download size={16} />开始同步下载
            </Button>
            <Button onClick={() => Promise.all([refreshStatus(), refreshDashboard(), refreshSessions()])} loading={loading.refresh}>
              <RefreshCcw size={16} />刷新
            </Button>
          </>
        )}
      />

      <section className="asmr-metric-strip glass-panel">
        {metricCards.map(card => {
          const Icon = card.icon
          return (
            <div key={card.label} title={card.help}>
              <Icon size={16} />
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </div>
          )
        })}
      </section>

      <section className="asmr-work-grid">
        <Card className="asmr-card glass-panel">
          <header className="asmr-card-head">
            <div>
              <FolderSearch size={16} />
              <h2>字幕文件夹扫描</h2>
            </div>
          </header>
          <Field label="字幕根目录">
            <TextInput value={subtitleFolder} onChange={event => setSubtitleFolder(event.target.value)} placeholder="输入包含字幕文件的文件夹路径" />
          </Field>
          {scanResults.length ? (
            <div className="asmr-scan-toolbar">
              <span>发现 {scanResults.length} 个作品，已选 {selectedScan.size}</span>
              <Button size="xs" onClick={() => setSelectedScan(new Set(scanResults.map(item => item.rjcode)))}>全选</Button>
              <Button size="xs" onClick={() => setSelectedScan(new Set())}>清空</Button>
            </div>
          ) : null}
          <div className="asmr-scan-list">
            {scanResults.length ? scanResults.map(item => (
              <article key={item.rjcode} className={cx('asmr-scan-row', selectedScan.has(item.rjcode) && 'is-selected')}>
                <label>
                  <input type="checkbox" checked={selectedScan.has(item.rjcode)} onChange={() => toggleScan(item.rjcode)} />
                  <span className="asmr-rj">{item.rjcode}</span>
                </label>
                <div>
                  <strong title={item.folder_name}>{item.folder_name}</strong>
                  <span>{item.subtitle_count || 0} 个字幕 · {item.folder_path}</span>
                </div>
                <StatusChip status={item.status} />
                <Button size="xs" onClick={() => previewDownload(item)} loading={item.previewing}>
                  <Eye size={13} />预览
                </Button>
              </article>
            )) : <EmptyState icon={FolderSearch} title="暂无扫描结果" description="输入字幕目录后点击扫描。" />}
          </div>
        </Card>

        <Card className="asmr-card glass-panel">
          <header className="asmr-card-head">
            <div>
              <Sparkles size={16} />
              <h2>增强下载工作台</h2>
            </div>
            {workbenchTaskIds.length ? (
              <Button size="xs" onClick={() => { setWorkbenchVisible(true); setWorkbenchBackground(false); refreshWorkbench() }}>
                <Download size={13} />下载工作台
              </Button>
            ) : null}
          </header>
          <Field label="RJ 号">
            <TextArea value={enhancedInput} rows={4} onChange={event => setEnhancedInput(event.target.value)} placeholder="支持 RJ123456、RJ234567，空格 / 换行 / 逗号分隔" />
          </Field>
          <div className="asmr-option-row">
            {resourceTypeOptions.map(option => (
              <label key={option.key} className="km-check">
                <input
                  type="checkbox"
                  checked={resourceTypes.includes(option.key)}
                  onChange={event => setResourceTypes(prev => event.target.checked ? [...new Set([...prev, option.key])] : prev.filter(item => item !== option.key))}
                />
                {option.label}
              </label>
            ))}
            <label className="km-check">
              <input type="checkbox" checked={includeExisting} onChange={event => setIncludeExisting(event.target.checked)} />
              包含已存在资源
            </label>
          </div>
          <div className="asmr-enhanced-targets">
            <Field label="下载临时目录"><TextInput value={downloadBasePath} onChange={event => setDownloadBasePath(event.target.value)} /></Field>
            <Field label="目标库存">
              <select className="km-input" value={targetLibraryId} onChange={event => setTargetLibraryId(event.target.value)}>
                <option value="">不自动上传</option>
                {libraries.map(library => <option key={library.id} value={library.id}>{library.name || library.id}</option>)}
              </select>
            </Field>
            <Field label="目标子目录"><TextInput value={targetSubdir} onChange={event => setTargetSubdir(event.target.value)} placeholder="可留空" /></Field>
          </div>
          <div className="asmr-card-actions">
            <Button onClick={buildEnhancedPlans} loading={loading.planning}><Search size={15} />查询 RJ</Button>
            <Button variant="primary" disabled={!selectedPlanList.length || loading.enhancedStart} loading={loading.enhancedStart} onClick={startEnhancedDownload}>
              <Download size={15} />下载选中 ({selectedPlanList.length})
            </Button>
          </div>
        </Card>
      </section>

      {enhancedPlans.length ? (
        <section className="asmr-plan-section glass-panel">
          <header>
            <div>
              <h2>增强下载计划</h2>
              <p>已选 {selectedPlanList.length} / {enhancedPlans.length} 个计划</p>
            </div>
            <div className="km-row-actions">
              <Button size="xs" onClick={() => setSelectedPlans(new Set(enhancedPlans.map(plan => plan.rjcode)))}>全选</Button>
              <Button size="xs" onClick={() => setSelectedPlans(new Set())}>清空</Button>
            </div>
          </header>
          <div className="asmr-plan-grid">
            {enhancedPlans.map(plan => (
              <EnhancedPlanCard
                key={plan.rjcode}
                plan={plan}
                selected={selectedPlans.has(plan.rjcode)}
                selectedResources={selectedResources[plan.rjcode] || new Set()}
                onTogglePlan={() => togglePlan(plan.rjcode)}
                onToggleResource={resource => toggleResource(plan, resource)}
                onPreset={preset => applyPlanPreset(plan, preset)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {waitingRetryTasks.length ? (
        <TaskSection
          title={`等待重试 (${waitingRetryTasks.length})`}
          subtitle={nextRetryTime ? `下次：${formatDateTime(nextRetryTime)}` : '等待手动处理或下次自动重试'}
          tasks={waitingRetryTasks}
          onAction={taskAction}
          waiting
        />
      ) : null}

      {activeTasks.length ? (
        <TaskSection title="下载任务" subtitle={`${activeTasks.length} 个进行中 / 历史任务`} tasks={activeTasks} onAction={taskAction} />
      ) : null}

      {sessions.length ? (
        <section className="asmr-session-section glass-panel">
          <header>
            <div>
              <h2>增强下载会话</h2>
              <p>{sessions.length} 个最近会话</p>
            </div>
            <Button size="xs" onClick={refreshSessions} loading={loading.sessions}><RefreshCcw size={13} />刷新</Button>
          </header>
          <div className="asmr-session-list">
            {sessions.map(session => (
              <article key={session.id} className="asmr-session-row">
                <button type="button" onClick={() => openSession(session)}>
                  <span className="asmr-rj">{session.rjcode}</span>
                  <strong>{session.source_label || session.work_title || session.rjcode}</strong>
                  <em>{session.target_path || session.download_root || '未设置目标'}</em>
                </button>
                <StatusChip status={session.status} />
                <span>优先级 {session.queue_priority || 100}</span>
                <div className="km-row-actions">
                  <Button size="xs" onClick={() => sessionAction(session, 'priorityUp')}>提前</Button>
                  <Button size="xs" onClick={() => sessionAction(session, 'priorityDown')}>延后</Button>
                  {session.status === 'paused' ? <Button size="xs" onClick={() => sessionAction(session, 'resume')}><Play size={12} />继续</Button> : <Button size="xs" onClick={() => sessionAction(session, 'pause')}><Pause size={12} />暂停</Button>}
                  <Button size="xs" onClick={() => sessionAction(session, 'retry')}><RotateCcw size={12} />重试</Button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {backgroundCard ? (
        <button type="button" className="asmr-background-card glass-panel" onClick={() => { setWorkbenchVisible(true); setWorkbenchBackground(false) }}>
          <Download size={18} />
          <div>
            <strong>{workbenchStats.failed ? 'ASMR 下载需要处理' : workbenchStats.completed === workbenchTasks.length ? 'ASMR 下载已完成' : 'ASMR 下载后台运行中'}</strong>
            <span>总进度 {workbenchStats.percent}% · {workbenchTasks.length || workbenchTaskIds.length} 项</span>
          </div>
        </button>
      ) : null}

      {previewData ? (
        <PreviewModal data={previewData} loading={previewLoading} onClose={() => setPreviewData(null)} />
      ) : null}

      {workbenchVisible ? (
        <WorkbenchModal
          tasks={workbenchTasks}
          stats={workbenchStats}
          loading={loading.workbench}
          onRefresh={() => refreshWorkbench()}
          onBackground={() => { setWorkbenchVisible(false); setWorkbenchBackground(true) }}
          onClose={closeWorkbench}
          onAction={taskAction}
        />
      ) : null}

      {sessionDrawerOpen ? (
        <SessionDrawer
          session={sessionDetail}
          loading={loading.sessionDetail}
          onClose={() => setSessionDrawerOpen(false)}
        />
      ) : null}
    </div>
  )
}

function EnhancedPlanCard({ plan, selected, selectedResources, onTogglePlan, onToggleResource, onPreset }) {
  const [open, setOpen] = useState(false)
  const resources = plan.selectable_resources || []
  const selectedCount = resources.filter(resource => selectedResources.has(resourceKey(resource))).length
  const cover = plan.cover_url || plan.image_url || plan.mainCoverUrl

  return (
    <article className={cx('asmr-plan-card glass-panel', selected && 'is-selected')}>
      <header>
        <label>
          <input type="checkbox" checked={selected} onChange={onTogglePlan} />
          <span className="asmr-rj">{plan.rjcode}</span>
        </label>
        <span>{selectedCount} / {resources.length}</span>
      </header>
      <div className="asmr-plan-main">
        <div className="asmr-plan-cover">
          {cover ? <img src={cover} alt={plan.rjcode} loading="lazy" referrerPolicy="no-referrer" /> : <Download size={24} />}
        </div>
        <div>
          <strong title={plan.work_title || plan.title}>{plan.work_title || plan.title || plan.rjcode}</strong>
          <p>{(plan.grouped_resources || []).slice(0, 3).map(group => `${resourceTypeLabel(group.resource_type)} ×${group.count}`).join(' · ') || '暂无资源分组'}</p>
        </div>
      </div>
      <div className="asmr-plan-presets">
        {Object.keys(plan.selection_presets || {}).map(key => (
          <button type="button" key={key} onClick={() => onPreset(key)}>{presetLabel(key)}</button>
        ))}
        <button type="button" onClick={() => setOpen(value => !value)}>
          资源明细 <ChevronDown size={13} className={open ? 'is-open' : ''} />
        </button>
      </div>
      {open ? (
        <div className="asmr-resource-list">
          {resources.map(resource => (
            <label key={resourceKey(resource)}>
              <input
                type="checkbox"
                checked={selectedResources.has(resourceKey(resource))}
                onChange={() => onToggleResource(resource)}
              />
              <File size={13} />
              <span title={resource.file_name || resource.relative_path}>{resource.file_name || resource.relative_path || resource.title}</span>
              <em>{resourceTypeLabel(resource.resource_type)} · {formatBytes(resource.size || resource.size_bytes)}</em>
            </label>
          ))}
        </div>
      ) : null}
    </article>
  )
}

function TaskSection({ title, subtitle, tasks, onAction, waiting = false }) {
  return (
    <section className={cx('asmr-task-section glass-panel', waiting && 'is-waiting')}>
      <header>
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </header>
      <div className="asmr-task-list">
        {tasks.map(task => <TaskCard key={task.id} task={task} onAction={onAction} waiting={waiting} />)}
      </div>
    </section>
  )
}

function TaskCard({ task, onAction, waiting }) {
  const progress = Math.max(0, Math.min(100, Number(task.progress || 0)))
  return (
    <article className={cx('asmr-task-card', `is-${task.status}`)}>
      <header>
        <div>
          <span className="asmr-rj">{task.actual_rjcode || task.rjcode}</span>
          <strong>{task.work_title || task.task_metadata?.work_title || task.source_label || task.id}</strong>
        </div>
        <div className="km-row-actions">
          <StatusChip status={task.status} />
          {task.status === 'processing' ? <Button size="xs" onClick={() => onAction(task, 'pause')}><Pause size={12} />暂停</Button> : null}
          {task.status === 'paused' ? <Button size="xs" onClick={() => onAction(task, 'resume')}><Play size={12} />继续</Button> : null}
          {task.status === 'waiting_retry' ? <Button size="xs" onClick={() => onAction(task, 'retryWaiting')}><RotateCcw size={12} />重试</Button> : null}
          {task.failed_files?.length || task.status === 'failed' ? <Button size="xs" onClick={() => onAction(task, 'retry')}><RotateCcw size={12} />重试失败</Button> : null}
          {waiting ? <Button size="xs" variant="danger" onClick={() => onAction(task, 'deleteWaiting')}><Trash2 size={12} />取消</Button> : null}
          {!waiting && ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task.status || '')) ? <Button size="xs" variant="danger" onClick={() => onAction(task, 'cancel')}><Square size={12} />取消</Button> : null}
        </div>
      </header>
      <div className="asmr-progress"><i style={{ width: `${progress}%` }} /></div>
      <p>{task.current_step || task.error_message || '等待状态更新'}</p>
      {task.error_message ? <div className="asmr-task-alert"><AlertTriangle size={14} />{task.error_message}</div> : null}
      <TaskDetails task={task} />
    </article>
  )
}

function TaskDetails({ task }) {
  return (
    <div className="asmr-task-details">
      {task.sync_result?.renamed_files?.length ? (
        <details>
          <summary><FileText size={13} />字幕同步映射 ({task.sync_result.renamed_files.length})</summary>
          <div>
            {task.sync_result.renamed_files.map((item, index) => (
              <p key={index}><span>{item.original}</span><b>{item.new}</b><em>{item.subtitle}</em></p>
            ))}
          </div>
        </details>
      ) : null}
      {task.failed_files?.length ? (
        <details>
          <summary><AlertTriangle size={13} />失败文件 ({task.failed_files.length})</summary>
          <div>
            {task.failed_files.map((file, index) => (
              <p key={index}><span>{file.title || file.path}</span><em>{file.reason}</em></p>
            ))}
          </div>
        </details>
      ) : null}
      {task.download_files?.length ? (
        <details>
          <summary><Folder size={13} />文件下载进度 ({task.download_files.length})</summary>
          <div>
            {task.download_files.map(file => (
              <p key={file.name}>
                <span>{file.name}</span>
                <b>{Math.round(Number(file.progress || 0))}%</b>
                <em>{formatBytes(file.downloaded)} / {formatBytes(file.total)}</em>
              </p>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  )
}

function WorkbenchModal({ tasks, stats, loading, onRefresh, onBackground, onClose, onAction }) {
  return (
    <Modal title="ASMR 增强下载工作台" width={1040} onClose={onBackground} footer={(
      <>
        <Button onClick={onRefresh} loading={loading}><RefreshCcw size={14} />刷新</Button>
        <Button onClick={onBackground}>后台保留</Button>
        <Button variant="danger" onClick={onClose}>关闭并清空</Button>
      </>
    )}>
      <div className="asmr-workbench">
        <div className="asmr-workbench-stats">
          <span>总进度 <b>{stats.percent}%</b></span>
          <span>进行中 <b>{stats.processing}</b></span>
          <span>等待 <b>{stats.pending}</b></span>
          <span>完成 <b>{stats.completed}</b></span>
          <span>失败 <b>{stats.failed}</b></span>
        </div>
        {tasks.length ? tasks.map(task => <TaskCard key={task.id} task={task} onAction={onAction} />) : <EmptyState title="暂无工作台任务" />}
      </div>
    </Modal>
  )
}

function PreviewModal({ data, loading, onClose }) {
  return (
    <Modal title="下载预览" width={900} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>关闭</Button>}>
      {loading ? <LoadingState label="正在获取作品信息..." /> : (
        <div className="asmr-preview">
          <div className="asmr-preview-stats">
            <span>请求 RJ <b>{data.rjcode}</b></span>
            <span>实际下载 <b>{data.actual_rjcode || '未找到'}</b></span>
            <span>预计大小 <b>{formatBytes(data.total_size)}</b></span>
            <span>文件 <b>{data.total_files || 0} {'->'} {data.filtered_files || 0}</b></span>
          </div>
          {data.error ? <div className="asmr-task-alert"><AlertTriangle size={14} />{data.error}</div> : null}
          <h3>{data.title || '可用版本'}</h3>
          <div className="asmr-version-list">
            {(data.available_versions || []).map(version => (
              <div key={version.rjcode}>
                <span className="asmr-rj">{version.rjcode}</span>
                <b>{version.lang || 'JPN'}</b>
                <em>{version.available ? '可用' : '不可用'} · {version.file_count || 0} 文件</em>
                <strong>{version.title}</strong>
              </div>
            ))}
          </div>
          <h3>下载文件</h3>
          <div className="asmr-preview-files">
            {(data.files || []).map((file, index) => (
              <div key={`${file.title}-${index}`}>
                <File size={13} />
                <span>{file.title || file.path}</span>
                <em>{file.type || '文件'} · {formatBytes(file.size)}</em>
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  )
}

function SessionDrawer({ session, loading, onClose }) {
  return (
    <div className="asmr-session-drawer-layer">
      <button type="button" className="asmr-session-backdrop" onClick={onClose} aria-label="关闭会话详情" />
      <aside className="asmr-session-drawer glass-panel">
        <header>
          <div>
            <span className="asmr-rj">{session?.rjcode || '会话详情'}</span>
            <h2>{session?.source_label || session?.work_title || session?.rjcode || '增强下载会话'}</h2>
          </div>
          <IconButton title="关闭" onClick={onClose}><X size={16} /></IconButton>
        </header>
        {loading ? <LoadingState label="正在加载增强下载详情..." /> : session ? (
          <div className="asmr-session-detail">
            <div className="asmr-preview-stats">
              <span>状态 <b>{statusText[session.status] || session.status || '-'}</b></span>
              <span>优先级 <b>{session.queue_priority || 100}</b></span>
              <span>上传模式 <b>{uploadModeLabel(session.upload_mode)}</b></span>
              <span>成功 / 失败 <b>{session.statistics?.success_count || 0} / {session.statistics?.failed_count || 0}</b></span>
            </div>
            <div className="asmr-session-path">
              <strong>目标路径</strong>
              <span>{session.target_path || '未设置'}</span>
            </div>
            <div className="asmr-resource-table">
              {(session.resources || []).map(resource => (
                <div key={resource.id || resource.relative_path || resource.file_name}>
                  <span>{resource.file_name || resource.relative_path}</span>
                  <b>{resource.resource_type || '-'}</b>
                  <em>{resource.download_status || '-'} / {resource.verify_status || '-'} / {resource.upload_status || '-'}</em>
                  <strong>{resource.last_error || resource.upload_path || '-'}</strong>
                </div>
              ))}
            </div>
          </div>
        ) : <EmptyState title="暂无会话详情" />}
      </aside>
    </div>
  )
}

function StatusChip({ status }) {
  return <span className={cx('asmr-status-chip', `is-${status}`)}>{statusText[status] || status || '-'}</span>
}

function buildMetricCards(dashboard = {}) {
  return [
    { label: '已建档 RJ', value: dashboard.total_rj || 0, help: '资源库中已记录的作品数', icon: Database },
    { label: '资源条目', value: dashboard.total_resources || 0, help: '已抓取并落库的远端资源', icon: Package },
    { label: '已下载', value: dashboard.downloaded_resources || 0, help: '已完成下载的文件数', icon: CloudDownload },
    { label: '已上传', value: dashboard.uploaded_resources || 0, help: '已进入自动上传管道的文件数', icon: Upload },
    { label: '处理中', value: dashboard.processing_tasks || 0, help: '当前运行中的增强下载任务', icon: Activity },
    { label: '待处理 / 失败', value: `${dashboard.pending_tasks || 0} / ${dashboard.failed_tasks || 0}`, help: '当前排队与失败任务概况', icon: Hourglass }
  ]
}

function buildWorkbenchStats(tasks = []) {
  const totalProgress = tasks.reduce((sum, task) => sum + Number(task.progress || 0), 0)
  return {
    percent: tasks.length ? Math.round(totalProgress / tasks.length) : 0,
    processing: tasks.filter(task => task.status === 'processing').length,
    pending: tasks.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))).length,
    completed: tasks.filter(task => task.status === 'completed').length,
    failed: tasks.filter(task => task.status === 'failed').length
  }
}

function parseRJCodes(text) {
  return Array.from(new Set(
    String(text || '')
      .split(/[\s,，;；、]+/)
      .map(item => item.trim().toUpperCase())
      .map(item => {
        const match = item.match(/RJ\d{4,}/i)
        return match ? match[0].toUpperCase() : ''
      })
      .filter(Boolean)
  ))
}

function resourceKey(resource) {
  return String(resource?.relative_path || resource?.path || resource?.file_name || resource?.title || resource?.id || '')
}

function resourceTypeLabel(type) {
  return ({
    audio: '音频',
    subtitle: '字幕',
    cover: '封面',
    image: '图片',
    text: '文本',
    other: '其他'
  })[String(type || '')] || String(type || '资源')
}

function presetLabel(key) {
  return ({
    audio: '仅音频',
    subtitle: '仅字幕',
    cover: '仅封面',
    recommended: '推荐',
    all: '全部'
  })[key] || key
}

function uploadModeLabel(value) {
  return ({ disabled: '不上传', local: '本地入库', synology: '群晖上传', classify: '分类入库' })[value] || value || '未设置'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN')
}

async function confirmOrFalse(options) {
  try {
    await showSystemConfirm(options)
    return true
  } catch {
    return false
  }
}
