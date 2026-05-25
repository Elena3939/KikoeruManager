import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  Gift,
  Globe,
  HardDrive,
  Hash,
  Headphones,
  Info,
  LayoutGrid,
  List,
  Mail,
  MinusCircle,
  RefreshCcw,
  RefreshCw,
  Search,
  Shuffle,
  Sparkles,
  Tags,
  XCircle
} from 'lucide-react'
import {
  asmrSyncApi,
  circleCompletionApi,
  emailWatcherApi,
  libraryApi,
  localUploadApi,
  taskApi
} from '../../api'
import { Button, Card, LoadingState, PageHeader, TextInput } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../stores/systemPromptStore'
import { cx, formatDateTime } from '../utils/format'
import { DownloadPreviewDialog, LocalUploadDialog } from './circle/CircleDialogs'
import { JobProgressCard } from './circle/CircleProgress'
import { CircleSidebar } from './circle/CircleSidebar'
import { BackgroundTaskCard, TaskWorkbenchDialog } from './circle/CircleTasks'
import {
  commonAncestorPath,
  extractError,
  formatElapsed,
  formatLogTime,
  formatServerOwnedLabel,
  getCircleCompletionState,
  getCircleMissingCount,
  getCircleOwnedCount,
  getCircleOwnedPercent,
  getCircleRefreshTimestamp,
  getCircleWorksCount,
  getLocalUploadCircleNameForPath,
  getOwnedVariantGroupKey,
  getWorkCode,
  getWorkReleaseTimestamp,
  isPreferredMissingWorkVisible,
  isWorkUnreleased,
  itemMatchesStatusFilter,
  jobStatusText,
  normalizeRjcode,
  normalizeStatusFilters,
  prioritizeChangedWorks,
  safeJsonParse,
  sortCompareWorksByRelease,
  sortWorksByRelease
} from './circle/circleUtils'
import {
  CompareTab,
  InfoTab,
  MetricPill,
  OwnedTab,
  StatusFilterMenu,
  WorksTab
} from './circle/CircleWorks'

const TARGET_SUBDIRS_KEY = 'kikoerumanager.circleCompletion.targetSubdirs'
const DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.downloadWorkbench'
const UPLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.uploadWorkbench'
const REFRESH_JOB_KEY = 'kikoerumanager.circleCompletion.refreshJob'
const INDEX_JOB_KEY = 'kikoerumanager.circleCompletion.indexJob'

const EMPTY_DETAIL = {
  circle_id: '',
  circle_name: '',
  source_mask: '',
  last_indexed_at: '',
  owned_count: 0,
  missing_count: 0,
  downloadable_count: 0,
  dl_only_count: 0,
  works: []
}

const STATUS_OPTIONS = [
  { value: 'repairable', label: '可补配' },
  { value: 'downloadable', label: '可下载' },
  { value: 'missing', label: '未收录' },
  { value: 'no_source', label: '无源' }
]

const CIRCLE_SORT_OPTIONS = [
  { value: 'refreshed_at', label: '刷新时间' },
  { value: 'completion', label: '收集程度' },
  { value: 'works', label: '作品数量' },
  { value: 'missing', label: '缺失数量' },
  { value: 'owned', label: '拥有数量' }
]

const WORK_PAGE_SIZES = [12, 24, 48, 96]

function listFromPayload(payload, key) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.[key])) return payload[key]
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.data)) return payload.data
  if (Array.isArray(payload?.results)) return payload.results
  return []
}

export function CircleCompletionPage() {
  const [circleQuery, setCircleQuery] = useState('')
  const [circleSearch, setCircleSearch] = useState('')
  const [circleCompletionFilter, setCircleCompletionFilter] = useState('all')
  const [circleSortKey, setCircleSortKey] = useState('refreshed_at')
  const [circleList, setCircleList] = useState([])
  const [activeCircleId, setActiveCircleId] = useState('')
  const [detail, setDetail] = useState(EMPTY_DETAIL)
  const [circleDetailLoading, setCircleDetailLoading] = useState(false)
  const [circleDetailLoaded, setCircleDetailLoaded] = useState(false)

  const [indexing, setIndexing] = useState(false)
  const [emailCheckLoading, setEmailCheckLoading] = useState(false)
  const [refreshingCurrentCircle, setRefreshingCurrentCircle] = useState(false)
  const [cancellingIndexJob, setCancellingIndexJob] = useState(false)
  const [cancellingRefreshJob, setCancellingRefreshJob] = useState(false)
  const [indexJob, setIndexJob] = useState(() => hydrateStoredIndexJob())
  const [refreshJob, setRefreshJob] = useState(() => hydrateStoredRefreshJob())

  const [activeTab, setActiveTab] = useState('missing')
  const [statusFilters, setStatusFilters] = useState([])
  const [selectedCanonicals, setSelectedCanonicals] = useState(() => new Set())
  const [flashedWorkCodes, setFlashedWorkCodes] = useState(() => new Set())
  const [viewMode, setViewMode] = useState('card')
  const [worksReleaseSort, setWorksReleaseSort] = useState('desc')
  const [worksPageSize, setWorksPageSize] = useState(24)
  const [missingPage, setMissingPage] = useState(1)
  const [ownedPage, setOwnedPage] = useState(1)
  const [comparePage, setComparePage] = useState(1)
  const [comparePageSize, setComparePageSize] = useState(10)
  const [ownedWorksSearchQuery, setOwnedWorksSearchQuery] = useState('')
  const [ownedWorksFilterType, setOwnedWorksFilterType] = useState('all')
  const [compareSearchQuery, setCompareSearchQuery] = useState('')
  const [compareSourceFilter, setCompareSourceFilter] = useState('all')

  const [libraries, setLibraries] = useState([])
  const [cachedTargetSubdirs, setCachedTargetSubdirs] = useState(() => {
    const parsed = safeJsonParse(localStorage.getItem(TARGET_SUBDIRS_KEY), [])
    return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 20) : []
  })
  const [downloadSettings, setDownloadSettings] = useState({
    downloadBasePath: '',
    targetLibraryId: '',
    targetSubdir: '',
    namingMode: 'api',
    classifyMode: 'circle',
    flattenFiles: false
  })

  const [previewDialogVisible, setPreviewDialogVisible] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [startingDownload, setStartingDownload] = useState(false)
  const [previewPlans, setPreviewPlans] = useState([])

  const [trackedDownloadTaskIds, setTrackedDownloadTaskIds] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(DOWNLOAD_WORKBENCH_KEY), {})
    return Array.isArray(raw?.taskIds) ? raw.taskIds.filter(Boolean) : []
  })
  const [trackedDownloadTasks, setTrackedDownloadTasks] = useState([])
  const [downloadWorkbenchVisible, setDownloadWorkbenchVisible] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(DOWNLOAD_WORKBENCH_KEY), {})
    return Boolean(raw?.visible && raw?.taskIds?.length)
  })
  const [downloadWorkbenchBackgroundActive, setDownloadWorkbenchBackgroundActive] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(DOWNLOAD_WORKBENCH_KEY), {})
    return Boolean(raw?.background && raw?.taskIds?.length)
  })
  const [downloadWorkbenchRefreshing, setDownloadWorkbenchRefreshing] = useState(false)
  const [retryingTaskIds, setRetryingTaskIds] = useState(() => new Set())

  const [trackedUploadTaskIds, setTrackedUploadTaskIds] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(UPLOAD_WORKBENCH_KEY), {})
    return Array.isArray(raw?.taskIds) ? raw.taskIds.filter(Boolean) : []
  })
  const [trackedUploadTasks, setTrackedUploadTasks] = useState([])
  const [uploadWorkbenchVisible, setUploadWorkbenchVisible] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(UPLOAD_WORKBENCH_KEY), {})
    return Boolean(raw?.visible && raw?.taskIds?.length)
  })
  const [uploadWorkbenchBackgroundActive, setUploadWorkbenchBackgroundActive] = useState(() => {
    const raw = safeJsonParse(localStorage.getItem(UPLOAD_WORKBENCH_KEY), {})
    return Boolean(raw?.background && raw?.taskIds?.length)
  })
  const [uploadWorkbenchRefreshing, setUploadWorkbenchRefreshing] = useState(false)
  const [localUploadDialogVisible, setLocalUploadDialogVisible] = useState(false)
  const [localUploadSubmitting, setLocalUploadSubmitting] = useState(false)
  const [localUploadSourceItems, setLocalUploadSourceItems] = useState([])
  const [localUploadForm, setLocalUploadForm] = useState({ targetLibraryId: '', targetSubdir: '' })

  const indexJobTimerRef = useRef(null)
  const refreshJobTimerRef = useRef(null)
  const refreshJobAutoHideTimerRef = useRef(null)
  const downloadWorkbenchTimerRef = useRef(null)
  const uploadWorkbenchTimerRef = useRef(null)
  const flashedWorkTimerRef = useRef(null)
  const circleOwnedSyncedTimerRef = useRef(null)
  const circleOwnedSyncedHitsRef = useRef(new Set())
  const activeCircleIdRef = useRef(activeCircleId)
  const detailRef = useRef(detail)
  const selectedCanonicalsRef = useRef(selectedCanonicals)
  const trackedDownloadTaskIdsRef = useRef(trackedDownloadTaskIds)
  const trackedUploadTaskIdsRef = useRef(trackedUploadTaskIds)
  const downloadWorkbenchVisibleRef = useRef(downloadWorkbenchVisible)
  const downloadWorkbenchBackgroundRef = useRef(downloadWorkbenchBackgroundActive)
  const uploadWorkbenchVisibleRef = useRef(uploadWorkbenchVisible)
  const uploadWorkbenchBackgroundRef = useRef(uploadWorkbenchBackgroundActive)

  useEffect(() => { activeCircleIdRef.current = activeCircleId }, [activeCircleId])
  useEffect(() => { detailRef.current = detail }, [detail])
  useEffect(() => { selectedCanonicalsRef.current = selectedCanonicals }, [selectedCanonicals])
  useEffect(() => { trackedDownloadTaskIdsRef.current = trackedDownloadTaskIds }, [trackedDownloadTaskIds])
  useEffect(() => { trackedUploadTaskIdsRef.current = trackedUploadTaskIds }, [trackedUploadTaskIds])
  useEffect(() => { downloadWorkbenchVisibleRef.current = downloadWorkbenchVisible }, [downloadWorkbenchVisible])
  useEffect(() => { downloadWorkbenchBackgroundRef.current = downloadWorkbenchBackgroundActive }, [downloadWorkbenchBackgroundActive])
  useEffect(() => { uploadWorkbenchVisibleRef.current = uploadWorkbenchVisible }, [uploadWorkbenchVisible])
  useEffect(() => { uploadWorkbenchBackgroundRef.current = uploadWorkbenchBackgroundActive }, [uploadWorkbenchBackgroundActive])

  const works = useMemo(() => Array.isArray(detail.works) ? detail.works : [], [detail.works])

  const statusScopeWorks = useMemo(() => {
    if (activeTab === 'missing') return works.filter(isPreferredMissingWorkVisible)
    if (activeTab === 'owned') return works.filter(item => item?.owned)
    return works
  }, [activeTab, works])

  const statusFilterOptions = useMemo(() => STATUS_OPTIONS.map(option => ({
    ...option,
    suffix: statusScopeWorks.filter(item => itemMatchesStatusFilter(item, option.value)).length
  })), [statusScopeWorks])

  const applyStatusFilters = (list) => {
    if (!statusFilters.length) return list
    return list.filter(item => statusFilters.some(key => itemMatchesStatusFilter(item, key)))
  }

  const missingWorks = useMemo(() => {
    const list = applyStatusFilters(works.filter(isPreferredMissingWorkVisible))
    return sortWorksByRelease(list, worksReleaseSort)
  }, [works, statusFilters, worksReleaseSort])

  const ownedWorks = useMemo(() => {
    let list = applyStatusFilters(works.filter(item => item?.owned))
    if (ownedWorksFilterType !== 'all') {
      list = list.filter(item => {
        const groupKey = getOwnedVariantGroupKey(item)
        const hasSubtitle = groupKey === 'original' && item.subtitle_present
        if (ownedWorksFilterType === 'original') return groupKey === 'original' && !hasSubtitle
        if (ownedWorksFilterType === 'simplified') return groupKey === 'simplified'
        if (ownedWorksFilterType === 'traditional') return groupKey === 'traditional'
        if (ownedWorksFilterType === 'subtitle') return hasSubtitle
        if (ownedWorksFilterType === 'bonus') return Boolean(item?.is_bonus_work)
        return true
      })
    }
    const query = ownedWorksSearchQuery.trim().toLowerCase()
    if (query) {
      list = list.filter(item => {
        const rjcode = getWorkCode(item).toLowerCase()
        const title = String(item?.title || '').toLowerCase()
        return rjcode.includes(query) || title.includes(query)
      })
    }
    return sortWorksByRelease(list, worksReleaseSort)
  }, [works, statusFilters, ownedWorksFilterType, ownedWorksSearchQuery, worksReleaseSort])

  const ownedWorksStats = useMemo(() => {
    const all = works.filter(item => item?.owned)
    return {
      total: all.length,
      original: all.filter(item => getOwnedVariantGroupKey(item) === 'original' && !item.subtitle_present).length,
      simplified: all.filter(item => getOwnedVariantGroupKey(item) === 'simplified').length,
      traditional: all.filter(item => getOwnedVariantGroupKey(item) === 'traditional').length,
      subtitle: all.filter(item => getOwnedVariantGroupKey(item) === 'original' && item.subtitle_present).length,
      bonus: all.filter(item => Boolean(item?.is_bonus_work)).length
    }
  }, [works])

  const compareWorks = useMemo(() => works.map(item => ({
    workRjcode: getWorkCode(item),
    title: String(item?.title || '').trim(),
    preferredVariantLabel: String(item?.preferred_variant?.group_short_label || item?.preferred_variant?.label || '').trim(),
    statusLabel: item?.server_owned ? formatServerOwnedLabel(item) : (item?.has_asmr_one ? '可下载' : '暂无来源'),
    statusKey: item?.server_owned ? 'owned' : (item?.has_asmr_one ? 'downloadable' : 'dl_only'),
    releaseTimestamp: getWorkReleaseTimestamp(item),
    sourceCompare: {
      kikoeru: {
        primary_rjcode: String(item?.source_compare?.kikoeru?.primary_rjcode || '').trim(),
        primaryBadge: String(item?.source_compare?.kikoeru?.primary_badge || '').trim(),
        variantBadges: Array.isArray(item?.source_compare?.kikoeru?.variant_badges) && item.source_compare.kikoeru.variant_badges.length
          ? item.source_compare.kikoeru.variant_badges.filter(Boolean)
          : (String(item?.source_compare?.kikoeru?.primary_badge || '').trim() ? [String(item.source_compare.kikoeru.primary_badge).trim()] : []),
        all_rjcodes: Array.isArray(item?.source_compare?.kikoeru?.all_rjcodes) ? item.source_compare.kikoeru.all_rjcodes.filter(Boolean) : [],
        tags: Array.isArray(item?.source_compare?.kikoeru?.tags) ? item.source_compare.kikoeru.tags.filter(Boolean) : []
      },
      dlsite: {
        all_rjcodes: Array.isArray(item?.source_compare?.dlsite?.all_rjcodes) ? item.source_compare.dlsite.all_rjcodes.filter(Boolean) : []
      },
      asmr_one: {
        primary_rjcode: String(item?.source_compare?.asmr_one?.primary_rjcode || '').trim(),
        primaryBadge: String(item?.source_compare?.asmr_one?.primary_badge || '').trim(),
        all_rjcodes: Array.isArray(item?.source_compare?.asmr_one?.all_rjcodes) ? item.source_compare.asmr_one.all_rjcodes.filter(Boolean) : []
      }
    }
  })), [works])

  const filteredCompareWorks = useMemo(() => {
    let list = compareWorks
    if (compareSourceFilter !== 'all') {
      list = list.filter(item => {
        if (compareSourceFilter === 'kikoeru') return item.statusKey === 'owned'
        if (compareSourceFilter === 'dlsite') return Boolean(item.sourceCompare.dlsite.all_rjcodes.length)
        if (compareSourceFilter === 'asmr_one') return Boolean(item.sourceCompare.asmr_one.primary_rjcode)
        if (compareSourceFilter === 'missing') return !item.sourceCompare.kikoeru.primary_rjcode && !item.sourceCompare.dlsite.all_rjcodes.length && !item.sourceCompare.asmr_one.primary_rjcode
        return true
      })
    }
    const query = compareSearchQuery.trim().toLowerCase()
    if (query) {
      list = list.filter(item => item.workRjcode.toLowerCase().includes(query) || item.title.toLowerCase().includes(query))
    }
    return sortCompareWorksByRelease(list, worksReleaseSort)
  }, [compareWorks, compareSourceFilter, compareSearchQuery, worksReleaseSort])

  const compareWorksStats = useMemo(() => ({
    total: compareWorks.length,
    kikoeru: compareWorks.filter(item => item.statusKey === 'owned').length,
    dlsite: compareWorks.filter(item => Boolean(item.sourceCompare.dlsite.all_rjcodes.length)).length,
    asmr_one: compareWorks.filter(item => Boolean(item.sourceCompare.asmr_one.primary_rjcode)).length,
    missing: compareWorks.filter(item => !item.sourceCompare.kikoeru.primary_rjcode && !item.sourceCompare.dlsite.all_rjcodes.length && !item.sourceCompare.asmr_one.primary_rjcode).length
  }), [compareWorks])

  const displayCircleList = useMemo(() => {
    let list = Array.isArray(circleList) ? [...circleList] : []
    if (circleCompletionFilter === 'completed') list = list.filter(circle => getCircleCompletionState(circle) === 'completed')
    else if (circleCompletionFilter === 'incomplete') list = list.filter(circle => getCircleCompletionState(circle) === 'incomplete')
    else if (circleCompletionFilter === 'new_works') list = list.filter(circle => Number(circle?.new_works_48h_count || 0) > 0)

    list.sort((left, right) => {
      if (circleSortKey === 'completion') {
        const diff = getCircleOwnedPercent(right) - getCircleOwnedPercent(left)
        if (diff !== 0) return diff
      } else if (circleSortKey === 'works') {
        const diff = getCircleWorksCount(right) - getCircleWorksCount(left)
        if (diff !== 0) return diff
      } else if (circleSortKey === 'missing') {
        const diff = getCircleMissingCount(right) - getCircleMissingCount(left)
        if (diff !== 0) return diff
      } else if (circleSortKey === 'owned') {
        const diff = getCircleOwnedCount(right) - getCircleOwnedCount(left)
        if (diff !== 0) return diff
      } else {
        const diff = getCircleRefreshTimestamp(right) - getCircleRefreshTimestamp(left)
        if (diff !== 0) return diff
      }
      return String(left?.circle_name || left?.circle_id || '').localeCompare(String(right?.circle_name || right?.circle_id || ''), 'zh-CN')
    })
    return list
  }, [circleList, circleCompletionFilter, circleSortKey])

  const activeSelectableWorks = activeTab === 'owned' ? ownedWorks : activeTab === 'missing' ? missingWorks : []
  const selectedCanonicalRJCodes = useMemo(() => [...selectedCanonicals], [selectedCanonicals])
  const selectedActiveCanonicalRJCodes = useMemo(() => (
    activeSelectableWorks.map(item => item?.canonical_rjcode).filter(code => code && selectedCanonicals.has(code))
  ), [activeSelectableWorks, selectedCanonicals])
  const selectedActiveDownloadableRJCodes = useMemo(() => selectedActiveCanonicalRJCodes.filter(code => {
    const item = activeSelectableWorks.find(work => work.canonical_rjcode === code)
    return Boolean(item?.has_asmr_one)
  }), [selectedActiveCanonicalRJCodes, activeSelectableWorks])

  const targetLibraries = useMemo(() => (libraries || []).filter(item => item?.enabled !== false), [libraries])
  const targetSubdirOptions = useMemo(() => [...new Set(cachedTargetSubdirs.filter(Boolean))], [cachedTargetSubdirs])

  const counts = useMemo(() => ({
    unreleased: works.filter(item => !item?.owned && isWorkUnreleased(item)).length,
    newWorks: works.filter(item => Boolean(item?.is_new_work)).length,
    bonus: works.filter(item => Boolean(item?.is_bonus_work)).length
  }), [works])

  const refreshForceRefreshHint = refreshJob.meta?.force_refresh
    ? refreshJob.meta.force_refresh_reason === 'auto_threshold'
      ? '1 分钟内连续刷新达到 3 次，当前已自动切换为强制刷新。'
      : '当前已启用强制刷新，不走缓存。'
    : ''

  const indexJobStatusText = jobStatusText(indexJob)
  const refreshJobStatusText = jobStatusText(refreshJob)
  const isRefreshJobActive = Boolean(refreshJob.job_id && ['pending', 'processing'].includes(String(refreshJob.status || '')))
  const canCancelIndexJob = Boolean(indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || '')))
  const canCancelRefreshJob = isRefreshJobActive

  const completedDownloadTasks = trackedDownloadTasks.filter(task => String(task?.status || '') === 'completed')
  const failedDownloadTasks = trackedDownloadTasks.filter(task => String(task?.status || '') === 'failed')
  const completedUploadTasks = trackedUploadTasks.filter(task => String(task?.status || '') === 'completed')
  const failedUploadTasks = trackedUploadTasks.filter(task => String(task?.status || '') === 'failed')

  const showDownloadBackgroundCard = downloadWorkbenchBackgroundActive && !downloadWorkbenchVisible && trackedDownloadTaskIds.length > 0
  const showUploadBackgroundCard = uploadWorkbenchBackgroundActive && !uploadWorkbenchVisible && trackedUploadTaskIds.length > 0

  useEffect(() => {
    loadCachedTargetSubdirs()
    loadLibraries()
    loadRecentCircles()
    if (indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || ''))) {
      setIndexing(true)
      pollIndexJob(indexJob.job_id)
    }
    if (refreshJob.job_id && ['pending', 'processing'].includes(String(refreshJob.status || ''))) {
      setRefreshingCurrentCircle(true)
      pollRefreshJob(refreshJob.job_id, { silentFinish: true })
    }
    if (trackedDownloadTaskIdsRef.current.length) refreshDownloadWorkbench({ silent: true })
    if (trackedUploadTaskIdsRef.current.length) refreshUploadWorkbench({ silent: true })

    function handleNewReleaseNotification(event) {
      const item = event?.detail || {}
      if (String(item.event_type || '') !== 'email_watcher_new_release') return
      loadRecentCircles().catch(() => {})
      const circleId = String(item.route_query?.circle_id || '').trim()
      if (circleId) selectCircle(circleId).catch(() => {})
    }

    function handleCircleOwnedSynced(event) {
      const payload = event?.detail || {}
      const circleIds = Array.isArray(payload.circle_ids) ? payload.circle_ids : []
      for (const cid of circleIds) {
        const normalized = String(cid || '').trim()
        if (normalized) circleOwnedSyncedHitsRef.current.add(normalized)
      }
      if (circleOwnedSyncedTimerRef.current) window.clearTimeout(circleOwnedSyncedTimerRef.current)
      circleOwnedSyncedTimerRef.current = window.setTimeout(async () => {
        circleOwnedSyncedTimerRef.current = null
        const hits = new Set(circleOwnedSyncedHitsRef.current)
        circleOwnedSyncedHitsRef.current.clear()
        try {
          await loadRecentCircles()
          if (activeCircleIdRef.current && hits.has(activeCircleIdRef.current)) await refreshActiveCircle(activeCircleIdRef.current)
        } catch (_) {}
      }, 300)
    }

    window.addEventListener('kikoerumanager:notification:new', handleNewReleaseNotification)
    window.addEventListener('kikoerumanager:circle:owned-synced', handleCircleOwnedSynced)

    return () => {
      window.removeEventListener('kikoerumanager:notification:new', handleNewReleaseNotification)
      window.removeEventListener('kikoerumanager:circle:owned-synced', handleCircleOwnedSynced)
      stopIndexJobPolling()
      stopRefreshJobPolling()
      stopRefreshJobAutoHide()
      stopDownloadWorkbenchPolling()
      stopUploadWorkbenchPolling()
      if (flashedWorkTimerRef.current) window.clearTimeout(flashedWorkTimerRef.current)
      if (circleOwnedSyncedTimerRef.current) window.clearTimeout(circleOwnedSyncedTimerRef.current)
    }
  }, [])

  useEffect(() => {
    setMissingPage(1)
    setOwnedPage(1)
    setComparePage(1)
  }, [worksReleaseSort, detail.works])

  useEffect(() => {
    try {
      if (!indexJob.job_id) localStorage.removeItem(INDEX_JOB_KEY)
      else localStorage.setItem(INDEX_JOB_KEY, JSON.stringify(indexJob))
    } catch (_) {}
  }, [indexJob])

  useEffect(() => {
    try {
      if (!refreshJob.job_id) localStorage.removeItem(REFRESH_JOB_KEY)
      else localStorage.setItem(REFRESH_JOB_KEY, JSON.stringify({
        job_id: refreshJob.job_id,
        status: refreshJob.status,
        circle_id: refreshJob.circle_id,
        circle_name: refreshJob.circle_name,
        selected_count: refreshJob.selected_count,
        auto_hide_at: refreshJob.auto_hide_at,
        changed_codes: Array.isArray(refreshJob.changed_codes) ? refreshJob.changed_codes : []
      }))
    } catch (_) {}
  }, [refreshJob])

  useEffect(() => {
    persistDownloadWorkbenchState()
    if ((downloadWorkbenchVisible || downloadWorkbenchBackgroundActive) && trackedDownloadTaskIds.length) startDownloadWorkbenchPolling()
    else stopDownloadWorkbenchPolling()
  }, [downloadWorkbenchVisible, downloadWorkbenchBackgroundActive, trackedDownloadTaskIds])

  useEffect(() => {
    persistUploadWorkbenchState()
    if ((uploadWorkbenchVisible || uploadWorkbenchBackgroundActive) && trackedUploadTaskIds.length) startUploadWorkbenchPolling()
    else stopUploadWorkbenchPolling()
  }, [uploadWorkbenchVisible, uploadWorkbenchBackgroundActive, trackedUploadTaskIds])

  async function loadRecentCircles(options = {}) {
    const result = await circleCompletionApi.listRecentIndexes(24)
    const list = listFromPayload(result, 'circles')
    setCircleList(list)
    if (!activeCircleIdRef.current && list.length && !options.skipAutoSelect) {
      await selectCircle(String(list[0]?.circle_id || ''))
    }
    return list
  }

  async function searchCachedCircles() {
    const keyword = circleSearch.trim()
    const result = await circleCompletionApi.searchCircles(keyword, 24)
    const list = listFromPayload(result, 'circles')
    setCircleList(list)
    if (!activeCircleIdRef.current && list.length && !keyword) {
      await selectCircle(String(list[0]?.circle_id || ''))
    }
  }

  async function loadLibraries() {
    try {
      const result = await libraryApi.listLibraries()
      const list = listFromPayload(result, 'libraries')
      setLibraries(list)
      setDownloadSettings(prev => {
        if (prev.targetLibraryId) return prev
        const preferred = list.find(item => item?.is_default) || list[0]
        return { ...prev, targetLibraryId: preferred?.id || '' }
      })
    } catch (error) {
      showToastError(error, '加载库存列表失败')
    }
  }

  async function selectCircle(circleId) {
    const normalized = String(circleId || '').trim()
    if (!normalized) return
    activeCircleIdRef.current = normalized
    setActiveCircleId(normalized)
    setCircleDetailLoaded(false)
    setSelectedCanonicals(new Set())
    await refreshActiveCircle(normalized)
  }

  async function refreshActiveCircle(circleId = activeCircleIdRef.current) {
    const normalized = String(circleId || '').trim()
    if (!normalized) return
    setCircleDetailLoading(true)
    try {
      const result = await circleCompletionApi.getCircleDetail(normalized, { includeDlOnly: true })
      const nextDetail = {
        circle_id: result.circle_id || '',
        circle_name: result.circle_name || '',
        source_mask: result.source_mask || '',
        last_indexed_at: result.last_indexed_at || '',
        owned_count: result.owned_count || 0,
        missing_count: result.missing_count || 0,
        downloadable_count: result.downloadable_count || 0,
        dl_only_count: result.dl_only_count || 0,
        works: Array.isArray(result.works) ? result.works : []
      }
      setDetail(nextDetail)
      setCircleDetailLoaded(true)
      setSelectedCanonicals(prev => new Set([...prev].filter(code => nextDetail.works.some(item => item.canonical_rjcode === code))))
    } catch (error) {
      showToastError(error, '加载社团详情失败')
    } finally {
      setCircleDetailLoading(false)
    }
  }

  async function startIndexCircleJob({ circleQuery: targetQuery, circleQueries = [], onlyNewWorks = false } = {}) {
    const normalizedQueries = Array.isArray(circleQueries) ? circleQueries.map(item => String(item || '').trim()).filter(Boolean) : []
    if (!normalizedQueries.length && !String(targetQuery || '').trim()) {
      await showSystemAlert({ title: '先输入社团名', tone: 'warning' })
      return
    }
    const finalQueries = normalizedQueries.length ? normalizedQueries : [String(targetQuery || '').trim()]
    setIndexing(true)
    try {
      const result = await circleCompletionApi.startIndexCircle({
        circle_query: finalQueries[0],
        circle_queries: finalQueries,
        force_refresh: !onlyNewWorks,
        include_dlsite: true,
        include_kikoeru: true,
        only_new_works: Boolean(onlyNewWorks)
      })
      applyIndexJob(result)
      await pollIndexJob(result.job_id)
    } catch (error) {
      setIndexing(false)
      showToastError(error, '启动社团索引失败')
    }
  }

  async function handleIndexCircle() {
    await startIndexCircleJob({ circleQuery: circleQuery.trim(), onlyNewWorks: false })
  }

  async function handleIndexOnlyNewWorks() {
    await startIndexCircleJob({ circleQuery: detail.circle_name || circleQuery, onlyNewWorks: true })
  }

  async function handleBatchIndexPrompt() {
    try {
      const value = await showSystemPrompt({
        title: '批量创建社团补全',
        description: '一行一个社团名，提交后按顺序执行。',
        badge: '社团补全',
        inputType: 'textarea',
        width: 680,
        closeOnClickModal: false,
        placeholder: '例如：\nリリムワークス/兎月りりむ。\n耳かき屋\nしろくまだんご',
        confirmText: '开始批量补全',
        validator: text => {
          const queries = normalizeBatchCircleQueries(text)
          if (!queries.length) return '至少输入一个社团名'
          if (queries.length > 100) return '一次最多提交 100 个社团'
          return true
        }
      })
      await startIndexCircleJob({ circleQueries: normalizeBatchCircleQueries(value), onlyNewWorks: false })
    } catch (_) {}
  }

  async function handleEmailCheck() {
    if (emailCheckLoading) return
    setEmailCheckLoading(true)
    try {
      const result = await emailWatcherApi.pollNow()
      await showSystemAlert({
        title: result.success ? (result.count > 0 ? '邮件检查完成' : '没有新邮件命中') : '邮件检查失败',
        message: result.message || '',
        tone: result.success ? 'success' : 'warning'
      })
      await loadRecentCircles()
    } catch (error) {
      await showSystemAlert({ title: '邮件检查请求失败', message: extractError(error, '请确认后端已启动且邮件监听已配置'), tone: 'danger' })
    } finally {
      setEmailCheckLoading(false)
    }
  }

  function applyIndexJob(payload = {}) {
    setIndexJob({
      visible: true,
      job_id: payload.job_id || '',
      status: payload.status || '',
      progress: Number(payload.progress || 0),
      current_step: payload.current_step || '',
      circle_query: payload.circle_query || '',
      elapsed_seconds: Number(payload.elapsed_seconds || 0),
      error_message: payload.error_message || '',
      meta: payload.meta || {},
      result: payload.result || {}
    })
  }

  function applyRefreshJob(payload = {}) {
    setRefreshJob(prev => ({
      visible: true,
      job_id: payload.job_id || prev.job_id || '',
      status: payload.status || '',
      progress: Number(payload.progress || 0),
      current_step: payload.current_step || '',
      circle_id: payload.circle_id || '',
      circle_name: payload.circle_name || '',
      selected_count: Number(payload.selected_count || 0),
      elapsed_seconds: Number(payload.elapsed_seconds || 0),
      auto_hide_at: payload.auto_hide_at || prev.auto_hide_at || '',
      changed_codes: Array.isArray(payload.changed_codes) ? payload.changed_codes.filter(Boolean) : (Array.isArray(prev.changed_codes) ? prev.changed_codes : []),
      error_message: payload.error_message || '',
      meta: payload.meta || {},
      result: payload.result || {},
      progress_log: Array.isArray(payload.progress_log) ? payload.progress_log : []
    }))
  }

  async function pollIndexJob(jobId) {
    stopIndexJobPolling()
    try {
      const result = await circleCompletionApi.getIndexJobStatus(jobId)
      applyIndexJob(result)
      if (result.status === 'completed') {
        clearIndexJobState()
        const nextCircleId = result.circle_id || result.result?.circle_id || activeCircleIdRef.current
        await loadRecentCircles({ skipAutoSelect: true })
        if (nextCircleId) await selectCircle(nextCircleId)
        const onlyNewWorks = Boolean(result.meta?.only_new_works)
        const newlyIndexedCount = Number(result.result?.incremental?.newly_indexed_count || result.meta?.newly_indexed_count || 0)
        await showSystemAlert({
          title: result.meta?.is_batch ? '批量社团补全完成' : (onlyNewWorks ? '新作索引完成' : '社团索引已刷新'),
          message: result.meta?.is_batch
            ? `成功 ${result.meta.completed_queries || 0} 个，失败 ${result.meta.failed_queries || 0} 个`
            : (onlyNewWorks ? `新增 ${newlyIndexedCount} 个作品` : ''),
          tone: 'success'
        })
        return
      }
      if (result.status === 'failed') {
        setIndexing(false)
        if (result.error_message === '用户取消' || result.current_step === '已取消') clearIndexJobState()
        else await showSystemAlert({ title: '社团索引失败', message: result.error_message || '', tone: 'danger' })
        return
      }
      indexJobTimerRef.current = window.setTimeout(() => pollIndexJob(jobId), 800)
    } catch (error) {
      setIndexing(false)
      if (error?.response?.status === 404) {
        clearIndexJobState()
        return
      }
      showToastError(error, '查询社团索引进度失败')
    }
  }

  async function pollRefreshJob(jobId, options = {}) {
    stopRefreshJobPolling()
    const silentFinish = Boolean(options?.silentFinish)
    try {
      const result = await circleCompletionApi.getRefreshSelectedJobStatus(jobId)
      applyRefreshJob(result)
      if (result.status === 'completed') {
        setRefreshingCurrentCircle(false)
        await Promise.all([refreshActiveCircle(), loadRecentCircles({ skipAutoSelect: true })])
        const changedCodes = (Array.isArray(result.result?.items) ? result.result.items : [])
          .filter(item => item?.changed)
          .map(item => item.canonical_rjcode)
          .filter(Boolean)
        flashChangedWorks(changedCodes)
        setDetail(prev => ({ ...prev, works: prioritizeChangedWorks(prev.works, changedCodes) }))
        setRefreshJob(prev => ({
          ...prev,
          current_step: `批量刷新完成，${changedCodes.length} 个状态变更，10 秒后自动隐藏`,
          status: 'completed',
          progress: 100,
          error_message: '',
          meta: { ...(prev.meta || {}), changed_count: changedCodes.length },
          changed_codes: changedCodes
        }))
        scheduleRefreshJobAutoHide(10000)
        if (!silentFinish) {
          await showSystemAlert({ title: '批量刷新完成', message: `已刷新 ${result.result?.refreshed_count || result.meta?.processed_count || result.selected_count || 0} 个作品`, tone: 'success' })
        }
        return
      }
      if (result.status === 'failed') {
        setRefreshingCurrentCircle(false)
        if (!silentFinish && result.error_message !== '用户取消' && result.current_step !== '已取消') {
          await showSystemAlert({ title: '批量刷新失败', message: result.error_message || '', tone: 'danger' })
        }
        clearRefreshJobState()
        return
      }
      refreshJobTimerRef.current = window.setTimeout(() => pollRefreshJob(jobId, { silentFinish: true }), 1000)
    } catch (error) {
      setRefreshingCurrentCircle(false)
      if (error?.response?.status === 404) {
        clearRefreshJobState()
        return
      }
      if (!silentFinish) showToastError(error, '查询批量刷新进度失败')
      refreshJobTimerRef.current = window.setTimeout(() => pollRefreshJob(jobId, { silentFinish: true }), 2000)
    }
  }

  async function cancelIndexJob() {
    if (!indexJob.job_id || cancellingIndexJob) return
    setCancellingIndexJob(true)
    try {
      await taskApi.cancel(indexJob.job_id)
      clearIndexJobState()
      await showSystemAlert({ title: '已发送取消请求', tone: 'success' })
    } catch (error) {
      showToastError(error, '取消社团索引失败')
    } finally {
      setCancellingIndexJob(false)
    }
  }

  async function cancelRefreshJob() {
    if (!refreshJob.job_id || cancellingRefreshJob) return
    setCancellingRefreshJob(true)
    try {
      await taskApi.cancel(refreshJob.job_id)
      setRefreshingCurrentCircle(false)
      clearRefreshJobState()
      await showSystemAlert({ title: '已发送取消请求', tone: 'success' })
    } catch (error) {
      showToastError(error, '取消批量刷新失败')
    } finally {
      setCancellingRefreshJob(false)
    }
  }

  async function refreshSelectedCircleIndex(targetCodes = null) {
    const circleId = String(activeCircleIdRef.current || detail.circle_id || '').trim()
    if (!circleId) {
      await showSystemAlert({ title: '当前还没有选中社团', tone: 'warning' })
      return
    }
    const codes = (Array.isArray(targetCodes) ? targetCodes : selectedCanonicalRJCodes)
      .map(code => String(code || '').trim())
      .filter(Boolean)
    if (!codes.length) {
      await showSystemAlert({ title: '先选中要刷新的作品', tone: 'warning' })
      return
    }
    if (isRefreshJobActive) {
      await showSystemAlert({ title: '已有批量刷新任务在跑', tone: 'warning' })
      return
    }
    setRefreshingCurrentCircle(true)
    try {
      const result = await circleCompletionApi.startRefreshSelectedWorks({
        circle_id: circleId,
        circle_name: detail.circle_name || '',
        canonical_rjcodes: codes,
        force_refresh: false
      })
      applyRefreshJob(result)
      await pollRefreshJob(result.job_id)
    } catch (error) {
      showToastError(error, '批量刷新选中作品失败')
      setRefreshingCurrentCircle(false)
    }
  }

  function toggleSelection(item) {
    if (!item?.canonical_rjcode) return
    setSelectedCanonicals(prev => {
      const next = new Set(prev)
      if (next.has(item.canonical_rjcode)) next.delete(item.canonical_rjcode)
      else next.add(item.canonical_rjcode)
      return next
    })
  }

  function selectAllVisibleWorks() {
    setSelectedCanonicals(new Set(activeSelectableWorks.map(item => item.canonical_rjcode).filter(Boolean)))
  }

  function clearSelection() {
    setSelectedCanonicals(new Set())
  }

  function getPreviewRequestedRjcodes(canonicalCodes = []) {
    const mapping = {}
    canonicalCodes.forEach(code => {
      const item = works.find(work => work.canonical_rjcode === code)
      if (!item) return
      const candidates = [
        item.download_plan?.rjcode,
        item.asmr_available_rjcode,
        item.display_rjcode,
        item.canonical_rjcode,
        ...(Array.isArray(item.linked_rjcodes) ? item.linked_rjcodes : [])
      ].map(value => normalizeRjcode(value)).filter(Boolean)
      const unique = [...new Set(candidates)]
      if (unique.length) mapping[code] = unique
    })
    return mapping
  }

  async function openBatchPreview(singleCanonical = '') {
    const codes = singleCanonical ? [singleCanonical] : selectedActiveDownloadableRJCodes
    if (!codes.length) {
      await showSystemAlert({ title: singleCanonical ? '当前作品没有可下载资源' : '选中的作品里没有可下载项', tone: 'warning' })
      return
    }
    setPreviewDialogVisible(true)
    setPreviewLoading(true)
    setPreviewPlans([])
    try {
      const result = await circleCompletionApi.previewBatchDownload({
        circle_id: detail.circle_id,
        canonical_rjcodes: codes,
        requested_rjcodes: getPreviewRequestedRjcodes(codes)
      })
      setPreviewPlans(result.plans || [])
      setDownloadSettings(prev => ({
        ...prev,
        downloadBasePath: result.download_base_path || prev.downloadBasePath || '',
        targetLibraryId: prev.targetLibraryId || result.default_target_library_id || '',
        targetSubdir: prev.targetSubdir || result.default_target_subdir || ''
      }))
    } catch (error) {
      setPreviewDialogVisible(false)
      showToastError(error, '生成下载预览失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function startBatchDownload(payload = {}) {
    const items = Array.isArray(payload.items) ? payload.items : []
    if (!items.length) {
      await showSystemAlert({ title: '没有选中任何文件', tone: 'warning' })
      return
    }
    setStartingDownload(true)
    try {
      const result = await circleCompletionApi.startBatchDownload({
        circle_id: detail.circle_id,
        circle_name: detail.circle_name,
        batch_options: payload.batchOptions || {},
        items
      })
      rememberTargetSubdir(downloadSettings.targetSubdir || '')
      const taskIds = (result.tasks || []).map(item => item.task_id).filter(Boolean)
      setTrackedDownloadTaskIds(taskIds)
      setDownloadWorkbenchVisible(taskIds.length > 0)
      setDownloadWorkbenchBackgroundActive(false)
      await refreshDownloadWorkbench({ taskIds, silent: true })
      await showSystemAlert({ title: '下载任务已创建', message: result.message || '', tone: 'success' })
      setPreviewDialogVisible(false)
      await refreshActiveCircle()
    } catch (error) {
      showToastError(error, '创建下载任务失败')
    } finally {
      setStartingDownload(false)
    }
  }

  function buildReimportSourceFromWork(item) {
    const canonicalRjcode = normalizeRjcode(item?.canonical_rjcode || item?.display_rjcode)
    const downloadRoot = String(item?.local_download_root || '').trim()
    return {
      canonical_rjcode: canonicalRjcode,
      session_id: String(item?.local_download_session_id || '').trim(),
      download_root: downloadRoot,
      rjcode: normalizeRjcode(item?.display_rjcode || item?.canonical_rjcode),
      circle_name: String(item?.circle_name || detailRef.current.circle_name || '').trim(),
      name: downloadRoot ? downloadRoot.split(/[\\/]/).filter(Boolean).pop() || canonicalRjcode : canonicalRjcode
    }
  }

  function buildReimportSourceFromTask(task) {
    const metadata = task?.task_metadata || {}
    const downloadRoot = String(metadata?.local_download_root || '').trim()
    const rjcode = normalizeRjcode(task?.rjcode || metadata?.rjcode)
    return {
      canonical_rjcode: normalizeRjcode(metadata?.canonical_rjcode || rjcode),
      session_id: String(metadata?.session_id || task?.session_id || '').trim(),
      download_root: downloadRoot,
      rjcode,
      circle_name: String(task?.circle_name || metadata?.circle_name || detailRef.current.circle_name || '').trim(),
      name: downloadRoot ? downloadRoot.split(/[\\/]/).filter(Boolean).pop() || rjcode : rjcode
    }
  }

  function openLocalUploadDialogWithSources(sources = []) {
    const normalized = sources
      .filter(source => String(source?.download_root || '').trim())
      .map(source => ({
        ...source,
        path: String(source.download_root || '').trim(),
        name: String(source.name || '').trim() || String(source.rjcode || source.canonical_rjcode || '').trim()
      }))
    if (!normalized.length) {
      showSystemAlert({ title: '当前任务缺少可复用的下载目录', tone: 'warning' })
      return
    }
    setLocalUploadSourceItems(normalized.map(source => ({
      name: source.name,
      path: source.path,
      circle_name: String(source.circle_name || '').trim()
    })))
    setLocalUploadForm(prev => ({
      targetLibraryId: prev.targetLibraryId || downloadSettings.targetLibraryId || targetLibraries.find(item => item?.type === 'synology_filestation')?.id || '',
      targetSubdir: prev.targetSubdir || downloadSettings.targetSubdir || ''
    }))
    setLocalUploadDialogVisible(true)
  }

  function openReimportDialogForWork(item) {
    if (!String(item?.local_download_root || '').trim()) {
      showSystemAlert({ title: '本地下载目录不存在，无法直接入库', tone: 'warning' })
      return
    }
    openLocalUploadDialogWithSources([buildReimportSourceFromWork(item)])
  }

  function openLocalUploadDialogForTask(task) {
    openLocalUploadDialogWithSources([buildReimportSourceFromTask(task)])
  }

  async function submitLocalUpload(payload = {}) {
    const selectedPaths = Array.isArray(payload?.selected_paths) ? payload.selected_paths.filter(Boolean) : []
    const targetLibraryId = String(payload?.target_library_id || localUploadForm.targetLibraryId || '').trim()
    const targetSubdir = String(payload?.target_subdir || localUploadForm.targetSubdir || '').trim()
    const sourceBasePath = localUploadSourceItems.length === 1
      ? String(localUploadSourceItems[0]?.path || '').trim()
      : String(commonAncestorPath(selectedPaths) || '').trim()
    if (!selectedPaths.length) {
      await showSystemAlert({ title: '请先选中要上传的目录', tone: 'warning' })
      return
    }
    if (!targetLibraryId) {
      await showSystemAlert({ title: '请选择目标服务器库存', tone: 'warning' })
      return
    }
    if (!sourceBasePath) {
      await showSystemAlert({ title: '缺少来源目录', tone: 'warning' })
      return
    }
    setLocalUploadForm({ targetLibraryId, targetSubdir })
    setLocalUploadSubmitting(true)
    try {
      const createdTaskIds = []
      for (const selectedPath of selectedPaths) {
        const result = await localUploadApi.start({
          source_library_id: '',
          source_base_path: sourceBasePath,
          selected_paths: [selectedPath],
          target_library_id: targetLibraryId,
          target_subdir: targetSubdir,
          circle_name: getLocalUploadCircleNameForPath(localUploadSourceItems, selectedPath, detail.circle_name)
        })
        if (result?.task_id) createdTaskIds.push(result.task_id)
      }
      rememberTargetSubdir(targetSubdir || '')
      setTrackedUploadTaskIds(prev => [...new Set([...createdTaskIds, ...prev])])
      setDownloadSettings(prev => ({ ...prev, targetLibraryId, targetSubdir }))
      setUploadWorkbenchVisible(true)
      setUploadWorkbenchBackgroundActive(false)
      setLocalUploadDialogVisible(false)
      await refreshUploadWorkbench({ taskIds: createdTaskIds, silent: true })
      await showSystemAlert({ title: '直接入库任务已创建', message: `已创建 ${createdTaskIds.length || selectedPaths.length} 个上传任务`, tone: 'success' })
      await refreshActiveCircle()
    } catch (error) {
      showToastError(error, '直接入库上传失败')
    } finally {
      setLocalUploadSubmitting(false)
    }
  }

  async function refreshDownloadWorkbench(options = {}) {
    const taskIds = options.taskIds || trackedDownloadTaskIdsRef.current
    if (!taskIds.length) {
      setTrackedDownloadTasks([])
      stopDownloadWorkbenchPolling()
      return
    }
    if (!options.silent) setDownloadWorkbenchRefreshing(true)
    try {
      const result = await asmrSyncApi.status()
      const allTasks = Array.isArray(result.tasks) ? result.tasks : []
      const tasks = taskIds.map(id => allTasks.find(task => task.id === id)).filter(Boolean)
      setTrackedDownloadTasks(tasks)
      setTrackedDownloadTaskIds(tasks.map(task => task.id))
      const stillActive = tasks.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task.status || '')))
      if (stillActive || downloadWorkbenchVisibleRef.current || downloadWorkbenchBackgroundRef.current) startDownloadWorkbenchPolling()
      else stopDownloadWorkbenchPolling()
    } catch (error) {
      if (!options.silent) showToastError(error, '刷新下载工作台失败')
      startDownloadWorkbenchPolling()
    } finally {
      if (!options.silent) setDownloadWorkbenchRefreshing(false)
    }
  }

  async function refreshUploadWorkbench(options = {}) {
    const taskIds = options.taskIds || trackedUploadTaskIdsRef.current
    if (!taskIds.length) {
      setTrackedUploadTasks([])
      stopUploadWorkbenchPolling()
      return
    }
    if (!options.silent) setUploadWorkbenchRefreshing(true)
    try {
      const result = await localUploadApi.status({ task_ids: taskIds.join(','), include_hidden: true })
      const allTasks = Array.isArray(result.tasks) ? result.tasks : []
      const tasks = taskIds.map(id => allTasks.find(task => String(task?.id || '') === String(id || ''))).filter(Boolean)
      setTrackedUploadTasks(tasks)
      setTrackedUploadTaskIds(tasks.map(task => task.id))
      const stillActive = tasks.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))
      if (stillActive || uploadWorkbenchVisibleRef.current || uploadWorkbenchBackgroundRef.current) startUploadWorkbenchPolling()
      else stopUploadWorkbenchPolling()
      if (tasks.some(task => ['completed', 'failed'].includes(String(task?.status || ''))) && activeCircleIdRef.current) {
        await refreshActiveCircle()
      }
    } catch (error) {
      if (!options.silent) showToastError(error, '获取上传任务失败')
      if (uploadWorkbenchVisibleRef.current || uploadWorkbenchBackgroundRef.current) startUploadWorkbenchPolling()
    } finally {
      if (!options.silent) setUploadWorkbenchRefreshing(false)
    }
  }

  async function retryDownloadTask(task) {
    const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
    const taskId = String(task?.id || '').trim()
    setRetryingTaskIds(prev => new Set(prev).add(taskId))
    try {
      if (sessionId) {
        const response = await asmrSyncApi.retryFailedSession(sessionId)
        const nextTaskId = String(response?.session?.task_id || '').trim()
        if (nextTaskId) setTrackedDownloadTaskIds(prev => [nextTaskId, ...prev.filter(id => id !== taskId && id !== nextTaskId)])
      } else if (taskId) {
        await asmrSyncApi.retry(taskId)
      } else {
        throw new Error('缺少任务标识')
      }
      await refreshDownloadWorkbench({ silent: true })
      await showSystemAlert({ title: '已提交重试', tone: 'success' })
    } catch (error) {
      showToastError(error, '提交重试失败')
    } finally {
      setRetryingTaskIds(prev => {
        const next = new Set(prev)
        next.delete(taskId)
        return next
      })
    }
  }

  async function retryWaitingDownloadTask(task) {
    const taskId = String(task?.id || '').trim()
    if (!taskId) return
    try {
      await asmrSyncApi.retryWaiting(taskId)
      await refreshDownloadWorkbench({ silent: true })
      await showSystemAlert({ title: '已立即重试', tone: 'success' })
    } catch (error) {
      showToastError(error, '立即重试失败')
    }
  }

  async function handlePauseDownloadTask(task) {
    const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
    try {
      if (sessionId) await asmrSyncApi.pauseSession(sessionId)
      else {
        const taskId = String(task?.active_task_id || task?.id || '').trim()
        if (taskId) await taskApi.pause(taskId)
      }
      await refreshDownloadWorkbench({ silent: true })
    } catch (error) {
      showToastError(error, '暂停失败')
    }
  }

  async function handleResumeDownloadTask(task) {
    const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
    try {
      if (sessionId) await asmrSyncApi.resumeSession(sessionId)
      else {
        const taskId = String(task?.active_task_id || task?.id || '').trim()
        if (taskId) await taskApi.resume(taskId)
      }
      await refreshDownloadWorkbench({ silent: true })
    } catch (error) {
      showToastError(error, '恢复失败')
    }
  }

  async function handleCancelDownloadTask(task) {
    const rjcode = String(task?.rjcode || '').trim()
    const title = String(task?.work_title || task?.source_label || '').trim()
    try {
      await showSystemConfirm({
        title: '取消下载任务',
        message: `确定要取消 ${rjcode || title || '此任务'} 的下载吗？`,
        description: '取消后将停止下载并清理已下载的临时文件。',
        tone: 'danger',
        confirmText: '取消下载'
      })
    } catch (_) {
      return
    }
    const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
    try {
      if (sessionId) await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
      else {
        const taskIds = (task?.source_task_ids || [task?.active_task_id || task?.id]).filter(Boolean).map(String)
        if (taskIds.length) await taskApi.batchCancelCleanup(taskIds)
      }
      await refreshDownloadWorkbench({ silent: true })
    } catch (error) {
      showToastError(error, '取消失败')
    }
  }

  function clearIndexJobState() {
    setIndexJob({ visible: false, job_id: '', status: '', progress: 0, current_step: '', circle_query: '', elapsed_seconds: 0, error_message: '', meta: {}, result: {} })
    setIndexing(false)
    stopIndexJobPolling()
    try { localStorage.removeItem(INDEX_JOB_KEY) } catch (_) {}
  }

  function clearRefreshJobState() {
    setRefreshJob({ visible: false, job_id: '', status: '', progress: 0, current_step: '', circle_id: '', circle_name: '', selected_count: 0, elapsed_seconds: 0, auto_hide_at: '', changed_codes: [], error_message: '', meta: {}, result: {}, progress_log: [] })
    stopRefreshJobPolling()
    stopRefreshJobAutoHide()
    try { localStorage.removeItem(REFRESH_JOB_KEY) } catch (_) {}
  }

  function stopIndexJobPolling() {
    if (indexJobTimerRef.current) {
      window.clearTimeout(indexJobTimerRef.current)
      indexJobTimerRef.current = null
    }
  }

  function stopRefreshJobPolling() {
    if (refreshJobTimerRef.current) {
      window.clearTimeout(refreshJobTimerRef.current)
      refreshJobTimerRef.current = null
    }
  }

  function stopRefreshJobAutoHide() {
    if (refreshJobAutoHideTimerRef.current) {
      window.clearTimeout(refreshJobAutoHideTimerRef.current)
      refreshJobAutoHideTimerRef.current = null
    }
  }

  function scheduleRefreshJobAutoHide(delayMs = 10000) {
    stopRefreshJobAutoHide()
    const targetAt = new Date(Date.now() + Math.max(0, Number(delayMs || 0))).toISOString()
    setRefreshJob(prev => ({ ...prev, auto_hide_at: targetAt }))
    refreshJobAutoHideTimerRef.current = window.setTimeout(() => clearRefreshJobState(), Math.max(0, Number(delayMs || 0)))
  }

  function stopDownloadWorkbenchPolling() {
    if (downloadWorkbenchTimerRef.current) {
      window.clearTimeout(downloadWorkbenchTimerRef.current)
      downloadWorkbenchTimerRef.current = null
    }
  }

  function startDownloadWorkbenchPolling() {
    if (!trackedDownloadTaskIdsRef.current.length) return
    stopDownloadWorkbenchPolling()
    downloadWorkbenchTimerRef.current = window.setTimeout(() => refreshDownloadWorkbench({ silent: true }), 2000)
  }

  function stopUploadWorkbenchPolling() {
    if (uploadWorkbenchTimerRef.current) {
      window.clearTimeout(uploadWorkbenchTimerRef.current)
      uploadWorkbenchTimerRef.current = null
    }
  }

  function startUploadWorkbenchPolling() {
    if (!trackedUploadTaskIdsRef.current.length) return
    stopUploadWorkbenchPolling()
    uploadWorkbenchTimerRef.current = window.setTimeout(() => refreshUploadWorkbench({ silent: true }), 2000)
  }

  function persistDownloadWorkbenchState() {
    try {
      localStorage.setItem(DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
        taskIds: trackedDownloadTaskIdsRef.current,
        visible: downloadWorkbenchVisibleRef.current,
        background: downloadWorkbenchBackgroundRef.current
      }))
    } catch (_) {}
  }

  function persistUploadWorkbenchState() {
    try {
      localStorage.setItem(UPLOAD_WORKBENCH_KEY, JSON.stringify({
        taskIds: trackedUploadTaskIdsRef.current,
        visible: uploadWorkbenchVisibleRef.current,
        background: uploadWorkbenchBackgroundRef.current
      }))
    } catch (_) {}
  }

  function closeDownloadWorkbench() {
    setTrackedDownloadTaskIds([])
    setTrackedDownloadTasks([])
    setDownloadWorkbenchVisible(false)
    setDownloadWorkbenchBackgroundActive(false)
    stopDownloadWorkbenchPolling()
    try { localStorage.removeItem(DOWNLOAD_WORKBENCH_KEY) } catch (_) {}
  }

  function closeUploadWorkbench() {
    setTrackedUploadTaskIds([])
    setTrackedUploadTasks([])
    setUploadWorkbenchVisible(false)
    setUploadWorkbenchBackgroundActive(false)
    stopUploadWorkbenchPolling()
    try { localStorage.removeItem(UPLOAD_WORKBENCH_KEY) } catch (_) {}
  }

  function flashChangedWorks(codes = []) {
    const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
    if (!normalized.length) return
    setFlashedWorkCodes(new Set(normalized))
    if (flashedWorkTimerRef.current) window.clearTimeout(flashedWorkTimerRef.current)
    flashedWorkTimerRef.current = window.setTimeout(() => {
      setFlashedWorkCodes(new Set())
      flashedWorkTimerRef.current = null
    }, 3000)
  }

  function rememberTargetSubdir(value = '') {
    const normalized = String(value || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
    if (!normalized) return
    setCachedTargetSubdirs(prev => {
      const next = [normalized, ...prev.filter(item => item !== normalized)].slice(0, 20)
      try { localStorage.setItem(TARGET_SUBDIRS_KEY, JSON.stringify(next)) } catch (_) {}
      return next
    })
  }

  function loadCachedTargetSubdirs() {
    const parsed = safeJsonParse(localStorage.getItem(TARGET_SUBDIRS_KEY), [])
    setCachedTargetSubdirs(Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 20) : [])
  }

  async function showToastError(error, fallback) {
    await showSystemAlert({ title: fallback, message: extractError(error, fallback), tone: 'danger' }).catch(() => {})
  }

  return (
    <div className="km-page circle-page react-circle-page">
      <PageHeader
        eyebrow="社团补全"
        title="社团补全"
        description="按社团建立索引，结合 Kikoeru 收录态、DLsite 关联与 asmr.one 下载能力补全缺失作品。"
        actions={(
          <>
            <div className="circle-hero-search">
              <Search size={14} />
              <TextInput
                value={circleQuery}
                placeholder="输入社团名，例如 こぐま座 / C_Realization"
                onChange={event => setCircleQuery(event.target.value)}
                onKeyDown={event => { if (event.key === 'Enter') handleIndexCircle() }}
              />
            </div>
            <Button variant="primary" loading={indexing} onClick={handleIndexCircle}><RefreshCcw size={16} />建立 / 刷新索引</Button>
            <Button disabled={indexing} onClick={handleBatchIndexPrompt}><Tags size={15} />批量创建</Button>
            <Button loading={emailCheckLoading} onClick={handleEmailCheck}><Mail size={15} />邮件检查</Button>
          </>
        )}
      />

      {indexJob.visible ? (
        <JobProgressCard
          title="索引进度"
          job={indexJob}
          statusText={indexJobStatusText}
          onCancel={canCancelIndexJob ? cancelIndexJob : null}
          cancelling={cancellingIndexJob}
          meta={[
            ['time', <Clock size={10} />, formatElapsed(indexJob.elapsed_seconds)],
            indexJob.meta?.is_batch ? ['batch', <CheckCircle2 size={10} />, `${indexJob.meta.completed_queries || 0}/${indexJob.meta.batch_total || 0} 已完成`] : null,
            indexJob.meta?.is_batch && indexJob.meta.failed_queries ? ['warn', <AlertCircle size={10} />, indexJob.meta.failed_queries] : null,
            ['local', <HardDrive size={10} />, `元数据 ${indexJob.meta?.local_candidates_count || 0}`],
            ['kikoeru', <Headphones size={10} />, indexJob.meta?.kikoeru_candidates_count || 0],
            ['dlsite', <Globe size={10} />, indexJob.meta?.dlsite_candidates_count || 0],
            ['merged', <List size={10} />, indexJob.meta?.combined_candidates_count || indexJob.meta?.aggregated_count || 0],
            ['ok', <Download size={10} />, indexJob.meta?.asmr_available_count || 0]
          ]}
        />
      ) : null}

      <section className="circle-shell react-circle-shell">
        <CircleSidebar
          circles={displayCircleList}
          allCount={circleList.length}
          activeCircleId={activeCircleId}
          search={circleSearch}
          sortKey={circleSortKey}
          filter={circleCompletionFilter}
          sortOptions={CIRCLE_SORT_OPTIONS}
          onSearchChange={setCircleSearch}
          onSearchSubmit={searchCachedCircles}
          onSearchClear={() => { setCircleSearch(''); loadRecentCircles({ skipAutoSelect: true }) }}
          onSortChange={setCircleSortKey}
          onFilterChange={setCircleCompletionFilter}
          onRefresh={() => loadRecentCircles({ skipAutoSelect: true })}
          onSelect={selectCircle}
        />

        <main className="circle-main">
          <Card className="circle-toolbar-card">
            <div className="circle-toolbar-main">
              <div>
                <h2>{detail.circle_name || '未选择社团'}</h2>
                <p>{detail.last_indexed_at ? `上次刷新 ${formatDateTime(detail.last_indexed_at)}` : '建立索引后会显示社团作品状态。'}</p>
              </div>
              {detail.works?.length ? (
                <div className="circle-toolbar-actions">
                  <Button disabled={!activeCircleId || indexing || isRefreshJobActive} loading={indexing} onClick={handleIndexOnlyNewWorks}><Sparkles size={14} />仅索引新作</Button>
                  <Button disabled={!activeCircleId || indexing || isRefreshJobActive || !selectedCanonicalRJCodes.length} loading={refreshingCurrentCircle} onClick={() => refreshSelectedCircleIndex()}><RefreshCw size={14} />批量刷新状态</Button>
                </div>
              ) : null}
            </div>
            <div className="circle-metrics-row">
              <MetricPill tone="owned" icon={<CheckCircle2 size={12} />} label={`已满足 ${detail.owned_count || 0}`} />
              <MetricPill tone="warn" icon={<XCircle size={12} />} label={`缺失 ${detail.missing_count || 0}`} />
              <MetricPill tone="ok" icon={<Download size={12} />} label={`可下载 ${detail.downloadable_count || 0}`} />
              <MetricPill tone="muted" icon={<MinusCircle size={12} />} label={`暂不可下载 ${detail.dl_only_count || 0}`} />
              {counts.unreleased > 0 ? <MetricPill tone="unreleased" icon={<Calendar size={12} />} label={`未发售 ${counts.unreleased}`} /> : null}
              {counts.bonus > 0 ? <MetricPill tone="bonus" icon={<Gift size={12} />} label={`特典 ${counts.bonus}`} /> : null}
              {counts.newWorks > 0 ? <MetricPill tone="new" icon={<Mail size={12} />} label={`新作 ${counts.newWorks}`} /> : null}
            </div>
            {refreshForceRefreshHint ? <div className="circle-toolbar-hint">{refreshForceRefreshHint}</div> : null}
          </Card>

          {activeCircleId ? (
            <Card className="circle-works-card">
              {refreshJob.visible ? (
                <JobProgressCard
                  compact
                  title="批量刷新进度"
                  job={refreshJob}
                  statusText={refreshJobStatusText}
                  onCancel={canCancelRefreshJob ? cancelRefreshJob : null}
                  cancelling={cancellingRefreshJob}
                  meta={[
                    ['time', <Clock size={10} />, formatElapsed(refreshJob.elapsed_seconds)],
                    ['total', <Hash size={10} />, refreshJob.selected_count || refreshJob.meta?.total_count || 0],
                    ['batch', <CheckCircle2 size={10} />, refreshJob.meta?.processed_count || 0],
                    ['changed', <Shuffle size={10} />, refreshJob.meta?.changed_count || 0],
                    refreshJob.meta?.force_refresh ? ['warn', <AlertCircle size={10} />, '强制刷新'] : null,
                    ['kikoeru', <Headphones size={10} />, refreshJob.meta?.kikoeru_owned_count || 0],
                    ['ok', <Download size={10} />, refreshJob.meta?.asmr_available_count || 0],
                    refreshJob.meta?.current_rjcode ? ['current', <Hash size={10} />, `当前 ${refreshJob.meta.current_rjcode}`] : null
                  ]}
                >
                  {refreshJob.progress_log?.length ? (
                    <div className="circle-job-log">
                      {refreshJob.progress_log.slice(-2).map(entry => (
                        <div key={`${entry.time}-${entry.message}`} className={cx('circle-job-log-row', entry.level || 'info')}>
                          <span>{formatLogTime(entry.time)}</span>
                          <strong>{entry.message}</strong>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </JobProgressCard>
              ) : null}

              <div className="circle-work-controls">
                <div className="circle-tabs">
                  {[
                    ['missing', <XCircle size={13} />, '缺失作品', detail.missing_count || 0],
                    ['owned', <CheckCircle2 size={13} />, '已满足', ownedWorksStats.total],
                    ['compare', <BarChart3 size={13} />, '来源对比', compareWorks.length],
                    ['info', <Info size={13} />, '索引信息', null]
                  ].map(([value, icon, label, count]) => (
                    <button key={value} type="button" className={cx('circle-tab-btn', activeTab === value && 'is-active')} onClick={() => setActiveTab(value)}>
                      {icon}<span>{label}</span>{count !== null ? <em>{count}</em> : null}
                    </button>
                  ))}
                </div>
                <div className="circle-toolbar-right-actions">
                  <button type="button" className="circle-sort-release-btn" title={worksReleaseSort === 'asc' ? '按发售时间正序' : '按发售时间倒序'} onClick={() => setWorksReleaseSort(value => value === 'asc' ? 'desc' : 'asc')}>
                    <ArrowUpDown size={13} />
                    <span>发售时间</span>
                    {worksReleaseSort === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
                  </button>
                  <StatusFilterMenu
                    options={statusFilterOptions}
                    value={statusFilters}
                    onChange={next => setStatusFilters(prev => normalizeStatusFilters(next, prev))}
                  />
                  <div className="circle-view-toggle">
                    <button type="button" className={cx(viewMode === 'card' && 'is-active')} title="卡片视图" onClick={() => setViewMode('card')}><LayoutGrid size={14} /></button>
                    <button type="button" className={cx(viewMode === 'list' && 'is-active')} title="列表视图" onClick={() => setViewMode('list')}><List size={14} /></button>
                  </div>
                </div>
              </div>

              {circleDetailLoading ? <LoadingState label="正在加载社团作品..." /> : null}

              {!circleDetailLoading && activeTab === 'missing' ? (
                <WorksTab
                  items={missingWorks}
                  currentPage={missingPage}
                  pageSize={worksPageSize}
                  pageSizes={WORK_PAGE_SIZES}
                  onPageChange={setMissingPage}
                  onPageSizeChange={(size) => { setWorksPageSize(size); setMissingPage(1) }}
                  mode={viewMode}
                  selectedCodes={selectedCanonicals}
                  flashedCodes={flashedWorkCodes}
                  selectedActiveCanonicalRJCodes={selectedActiveCanonicalRJCodes}
                  selectedActiveDownloadableRJCodes={selectedActiveDownloadableRJCodes}
                  activeSelectableCount={activeSelectableWorks.length}
                  onSelectAll={selectAllVisibleWorks}
                  onClearSelection={clearSelection}
                  onRefreshSelected={() => refreshSelectedCircleIndex(selectedActiveCanonicalRJCodes)}
                  onPreview={() => openBatchPreview()}
                  onToggle={toggleSelection}
                  onPreviewOne={openBatchPreview}
                  onReimport={openReimportDialogForWork}
                  emptyText={circleDetailLoaded && (detail.missing_count || 0) === 0 ? '这个社团已经补全' : '没有找到符合条件的缺失作品'}
                />
              ) : null}

              {!circleDetailLoading && activeTab === 'owned' ? (
                <OwnedTab
                  items={ownedWorks}
                  stats={ownedWorksStats}
                  searchQuery={ownedWorksSearchQuery}
                  filterType={ownedWorksFilterType}
                  currentPage={ownedPage}
                  pageSize={worksPageSize}
                  viewMode={viewMode}
                  selectedCodes={selectedCanonicals}
                  flashedCodes={flashedWorkCodes}
                  onSearchChange={value => { setOwnedWorksSearchQuery(value); setOwnedPage(1) }}
                  onFilterChange={value => { setOwnedWorksFilterType(value); setOwnedPage(1) }}
                  onPageChange={setOwnedPage}
                  onPageSizeChange={(size) => { setWorksPageSize(size); setOwnedPage(1) }}
                  onToggle={toggleSelection}
                  onPreviewOne={openBatchPreview}
                  onReimport={openReimportDialogForWork}
                />
              ) : null}

              {!circleDetailLoading && activeTab === 'compare' ? (
                <CompareTab
                  items={filteredCompareWorks}
                  total={filteredCompareWorks.length}
                  stats={compareWorksStats}
                  searchQuery={compareSearchQuery}
                  sourceFilter={compareSourceFilter}
                  currentPage={comparePage}
                  pageSize={comparePageSize}
                  onSearchChange={value => { setCompareSearchQuery(value); setComparePage(1) }}
                  onSourceFilterChange={value => { setCompareSourceFilter(value); setComparePage(1) }}
                  onPageChange={setComparePage}
                  onPageSizeChange={(size) => { setComparePageSize(size); setComparePage(1) }}
                />
              ) : null}

              {!circleDetailLoading && activeTab === 'info' ? (
                <InfoTab detail={detail} />
              ) : null}
            </Card>
          ) : (
            <Card className="circle-empty-state-card">
              <div className="km-empty"><Tags size={32} /><strong>先建立一个社团索引</strong><span>输入社团名后点击建立 / 刷新索引。</span></div>
            </Card>
          )}
        </main>
      </section>

      {previewDialogVisible ? (
        <DownloadPreviewDialog
          loading={previewLoading}
          starting={startingDownload}
          plans={previewPlans}
          libraries={libraries}
          targetSubdirOptions={targetSubdirOptions}
          settings={downloadSettings}
          circleName={detail.circle_name}
          onSettingsChange={setDownloadSettings}
          onClose={() => setPreviewDialogVisible(false)}
          onSubmit={startBatchDownload}
        />
      ) : null}

      {downloadWorkbenchVisible ? (
        <TaskWorkbenchDialog
          type="download"
          title="社团补全下载工作台"
          tasks={trackedDownloadTasks}
          refreshing={downloadWorkbenchRefreshing}
          retryingKeys={retryingTaskIds}
          onRefresh={() => refreshDownloadWorkbench({ silent: false })}
          onBackground={() => { setDownloadWorkbenchVisible(false); setDownloadWorkbenchBackgroundActive(true) }}
          onClose={closeDownloadWorkbench}
          onRetry={retryDownloadTask}
          onRetryWaiting={retryWaitingDownloadTask}
          onPause={handlePauseDownloadTask}
          onResume={handleResumeDownloadTask}
          onCancel={handleCancelDownloadTask}
          onReimport={openLocalUploadDialogForTask}
        />
      ) : null}

      {uploadWorkbenchVisible ? (
        <TaskWorkbenchDialog
          type="upload"
          title="直接入库上传工作台"
          tasks={trackedUploadTasks}
          refreshing={uploadWorkbenchRefreshing}
          onRefresh={() => refreshUploadWorkbench({ silent: false })}
          onBackground={() => { setUploadWorkbenchVisible(false); setUploadWorkbenchBackgroundActive(true) }}
          onClose={closeUploadWorkbench}
        />
      ) : null}

      {localUploadDialogVisible ? (
        <LocalUploadDialog
          title="直接入库"
          sources={localUploadSourceItems}
          libraries={libraries}
          form={localUploadForm}
          starting={localUploadSubmitting}
          circleName={detail.circle_name}
          onFormChange={setLocalUploadForm}
          onClose={() => setLocalUploadDialogVisible(false)}
          onSubmit={submitLocalUpload}
        />
      ) : null}

      {showDownloadBackgroundCard ? (
        <BackgroundTaskCard
          tone={failedDownloadTasks.length ? 'amber' : 'primary'}
          title={completedDownloadTasks.length === trackedDownloadTasks.length ? '社团补全下载已完成' : failedDownloadTasks.length ? '社团补全下载需要处理' : '社团补全下载正在后台运行'}
          badge={`下载 ${trackedDownloadTasks.length} 项`}
          tasks={trackedDownloadTasks}
          type="download"
          onResume={() => { setDownloadWorkbenchVisible(true); setDownloadWorkbenchBackgroundActive(false) }}
          onClose={closeDownloadWorkbench}
        />
      ) : null}

      {showUploadBackgroundCard ? (
        <BackgroundTaskCard
          tone={failedUploadTasks.length ? 'amber' : 'emerald'}
          title={completedUploadTasks.length === trackedUploadTasks.length ? '直接入库上传已完成' : failedUploadTasks.length ? '直接入库上传需要处理' : '直接入库上传正在后台运行'}
          badge={`上传 ${trackedUploadTasks.length} 项`}
          tasks={trackedUploadTasks}
          type="upload"
          stacked={showDownloadBackgroundCard}
          onResume={() => { setUploadWorkbenchVisible(true); setUploadWorkbenchBackgroundActive(false) }}
          onClose={closeUploadWorkbench}
        />
      ) : null}
    </div>
  )
}

function hydrateStoredIndexJob() {
  const raw = safeJsonParse(localStorage.getItem(INDEX_JOB_KEY), {})
  const status = String(raw?.status || '').trim()
  if (!raw?.job_id || ['completed', 'failed'].includes(status) || raw?.error_message === '用户取消' || raw?.current_step === '已取消') {
    try { localStorage.removeItem(INDEX_JOB_KEY) } catch (_) {}
    return { visible: false, job_id: '', status: '', progress: 0, current_step: '', circle_query: '', elapsed_seconds: 0, error_message: '', meta: {}, result: {} }
  }
  return {
    visible: raw.visible !== false,
    job_id: String(raw.job_id || '').trim(),
    status,
    progress: Number(raw.progress || 0),
    current_step: String(raw.current_step || '').trim(),
    circle_query: String(raw.circle_query || '').trim(),
    elapsed_seconds: Number(raw.elapsed_seconds || 0),
    error_message: String(raw.error_message || '').trim(),
    meta: raw.meta && typeof raw.meta === 'object' ? raw.meta : {},
    result: raw.result && typeof raw.result === 'object' ? raw.result : {}
  }
}

function hydrateStoredRefreshJob() {
  const raw = safeJsonParse(localStorage.getItem(REFRESH_JOB_KEY), {})
  const status = String(raw?.status || '').trim()
  if (!raw?.job_id || ['completed', 'failed', 'cancelled'].includes(status) || raw?.error_message === '用户取消' || raw?.current_step === '已取消') {
    try { localStorage.removeItem(REFRESH_JOB_KEY) } catch (_) {}
    return { visible: false, job_id: '', status: '', progress: 0, current_step: '', circle_id: '', circle_name: '', selected_count: 0, elapsed_seconds: 0, auto_hide_at: '', changed_codes: [], error_message: '', meta: {}, result: {}, progress_log: [] }
  }
  return {
    visible: Boolean(raw.job_id),
    job_id: String(raw.job_id || '').trim(),
    status,
    progress: Number(raw.progress || 0),
    current_step: String(raw.current_step || '').trim(),
    circle_id: String(raw.circle_id || '').trim(),
    circle_name: String(raw.circle_name || '').trim(),
    selected_count: Number(raw.selected_count || 0),
    elapsed_seconds: Number(raw.elapsed_seconds || 0),
    auto_hide_at: String(raw.auto_hide_at || '').trim(),
    changed_codes: Array.isArray(raw.changed_codes) ? raw.changed_codes.filter(Boolean) : [],
    error_message: String(raw.error_message || '').trim(),
    meta: raw.meta && typeof raw.meta === 'object' ? raw.meta : {},
    result: raw.result && typeof raw.result === 'object' ? raw.result : {},
    progress_log: Array.isArray(raw.progress_log) ? raw.progress_log : []
  }
}

function normalizeBatchCircleQueries(text = '') {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(item => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}
