import {
  Activity,
  Archive,
  Captions,
  CheckCircle2,
  Clock3,
  Database,
  FileArchive,
  FolderInput,
  ListTodo,
  PauseCircle,
  RotateCcw,
  Sparkles,
  TriangleAlert,
  Upload,
  UploadCloud,
  XCircle
} from 'lucide-react'
import { formatBytes } from '../../utils/format'

export const ACTIVE_STATUSES = new Set(['processing', 'pending', 'paused', 'waiting_manual', 'waiting_retry'])

export const domainOptions = [
  { value: 'all', label: '全部', icon: ListTodo },
  { value: 'import', label: '导入处理', icon: FileArchive },
  { value: 'existing_folder', label: '已有文件夹', icon: FolderInput },
  { value: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
  { value: 'subtitle_import', label: '字幕补配', icon: Sparkles },
  { value: 'asmr_sync', label: 'ASMR 同步', icon: UploadCloud },
  { value: 'upload', label: '库存上传', icon: Upload },
  { value: 'circle_completion', label: '社团补全', icon: Database },
  { value: 'system', label: '系统任务', icon: Activity }
]

export const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'processing', label: '处理中' },
  { value: 'waiting_manual', label: '等待人工' },
  { value: 'waiting_retry', label: '等待重试' },
  { value: 'pending', label: '待处理' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
  { value: 'completed', label: '已完成' }
]

export const sortOptions = [
  { value: 'updated_desc', label: '最近更新' },
  { value: 'created_desc', label: '最近创建' },
  { value: 'progress_desc', label: '进度最高' },
  { value: 'status_priority', label: '状态优先' }
]

export const statusMetaMap = {
  processing: { label: '处理中', icon: Activity, tone: 'info' },
  pending: { label: '待处理', icon: Clock3, tone: 'muted' },
  waiting_manual: { label: '等待人工', icon: TriangleAlert, tone: 'warning' },
  waiting_retry: { label: '等待重试', icon: RotateCcw, tone: 'warning' },
  paused: { label: '已暂停', icon: PauseCircle, tone: 'muted' },
  completed: { label: '已完成', icon: CheckCircle2, tone: 'success' },
  failed: { label: '失败', icon: XCircle, tone: 'danger' },
  canceled: { label: '已取消', icon: XCircle, tone: 'muted' },
  cancelled: { label: '已取消', icon: XCircle, tone: 'muted' }
}

const domainMetaMap = {
  import: { label: '导入处理', icon: FileArchive, tone: 'blue' },
  existing_folder: { label: '已有文件夹', icon: FolderInput, tone: 'teal' },
  rj_subtitle: { label: 'RJ 字幕', icon: Captions, tone: 'green' },
  subtitle_import: { label: '字幕补配', icon: Sparkles, tone: 'violet' },
  asmr_sync: { label: 'ASMR 同步', icon: UploadCloud, tone: 'sky' },
  upload: { label: '库存上传', icon: Upload, tone: 'cyan' },
  circle_completion: { label: '社团补全', icon: Database, tone: 'amber' },
  system: { label: '系统任务', icon: Activity, tone: 'slate' },
  backup: { label: '库存打包', icon: Archive, tone: 'slate' }
}

export const actionLabels = {
  pause: '暂停',
  resume: '恢复',
  cancel: '取消',
  retry: '重试',
  retry_waiting: '立即重试',
  delete_waiting_retry: '移除等待重试',
  open_subtitle_import: '前往字幕补配',
  open_circle_completion: '前往社团补全',
  reindex_circle: '重新索引'
}

export function getTaskId(item) {
  return item?.id || item?.item_id || item?.task_id || ''
}

export function getDomainMeta(domain) {
  return domainMetaMap[String(domain || '').trim()] || { label: '其他任务', icon: Activity, tone: 'slate' }
}

export function getStatusMeta(status, label = '') {
  const meta = statusMetaMap[String(status || '').trim()] || { label: label || status || '未知', icon: Clock3, tone: 'muted' }
  return { ...meta, label: label || meta.label }
}

export function safeTimestamp(value) {
  const ts = new Date(value || 0).getTime()
  return Number.isFinite(ts) ? ts : 0
}

export function statusPriority(status) {
  const map = { processing: 0, waiting_manual: 1, waiting_retry: 2, pending: 3, paused: 4, failed: 5, completed: 6 }
  return map[String(status || '')] ?? 99
}

export function sortTasks(items, sortKey) {
  const next = Array.isArray(items) ? [...items] : []
  next.sort((left, right) => {
    if (sortKey === 'created_desc') return safeTimestamp(right.created_at) - safeTimestamp(left.created_at)
    if (sortKey === 'progress_desc') {
      const progress = Number(right.progress || 0) - Number(left.progress || 0)
      if (progress !== 0) return progress
    }
    if (sortKey === 'status_priority') {
      const status = statusPriority(left.status) - statusPriority(right.status)
      if (status !== 0) return status
    }
    return safeTimestamp(right.updated_at || right.created_at) - safeTimestamp(left.updated_at || left.created_at)
  })
  return next
}

export function formatRJCode(value) {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''
  const repeated = raw.match(/(?:RJ)+\s*(\d{6,8})/i)
  if (repeated) return `RJ${repeated[1]}`
  const fallback = raw.match(/[RVB]J\s*(\d{6,8})/i)
  if (fallback) return `RJ${fallback[1]}`
  return raw
}

export function getFileName(path) {
  if (!path) return ''
  return String(path).replace(/[\\/]+$/g, '').split(/[\\/]/).pop()
}

export function showProgress(item) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(String(item?.status || ''))
}

export function shouldShowTaskStep(item) {
  const step = String(item?.current_step || '').trim()
  const statusLabel = String(item?.status_label || '').trim()
  if (!step || step === statusLabel) return false
  return !['完成', '已完成', '处理中', '等待中', '待处理', '已暂停', '失败', '等待重试', '等待人工'].includes(step)
}

export function getTaskTitle(item) {
  return item?.title || item?.source_label || item?.name || getFileName(item?.source_path) || getTaskId(item) || '未命名任务'
}

export function getOutputPath(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  return item?.target_path || metadata.subtitle_dir || metadata.target_folder_path || metadata.folder_path || preview.selected_candidate?.folder_path || ''
}

export function getTaskActions(item) {
  if (Array.isArray(item?.actions) && item.actions.length) return item.actions
  const status = String(item?.status || '')
  const actions = []
  if (status === 'processing') actions.push('pause', 'cancel')
  if (status === 'pending') actions.push('cancel')
  if (status === 'paused') actions.push('resume', 'cancel')
  if (status === 'waiting_retry') actions.push('retry_waiting', 'delete_waiting_retry')
  if (status === 'failed') actions.push('retry')
  return actions
}

export function pickMetricValue(item, label) {
  const metrics = Array.isArray(item?.metrics) ? item.metrics : []
  const value = metrics.find(metric => metric?.label === label)?.value
  return value === undefined || value === null ? '' : value
}

export function getRecoveredNotice(item) {
  return String(item?.details?.metadata?.recovered_notice || '').trim()
}

export function getDLsiteFailureReason(item) {
  const metadata = item?.details?.metadata || {}
  const indexMeta = metadata.index_meta || {}
  return String(indexMeta.dlsite_failure_reason || metadata.dlsite_failure_reason || '').trim()
}

export function getCircleIndexMetaEntries(item) {
  if (item?.kind !== 'circle_completion_index') return []
  const metadata = item?.details?.metadata || {}
  const indexMeta = metadata.index_meta || {}
  const indexedCounts = metadata.indexed_counts || {}
  const circleQueries = Array.isArray(metadata.circle_queries)
    ? metadata.circle_queries.map(value => String(value || '').trim()).filter(Boolean)
    : []
  const isBatch = Boolean(metadata.is_batch) || circleQueries.length > 1
  const batchTotal = Number(metadata.batch_total || 0) || circleQueries.length
  const currentCircle = String(indexMeta.current_circle_query || metadata.current_circle_query || metadata.circle_query || '').trim()
  const completedQueries = Number(indexMeta.completed_queries || 0)
  const failedQueries = Number(indexMeta.failed_queries || 0)
  const circleField = isBatch
    ? `批量补全 · ${circleQueries.slice(0, 6).join('、')}${circleQueries.length > 6 ? `... 等 ${batchTotal} 个` : `（共 ${batchTotal} 个）`}`
    : metadata.circle_name || metadata.circle_query || ''
  const entries = [
    ['社团', circleField],
    ['当前进度', isBatch ? `${completedQueries + failedQueries}/${batchTotal}${currentCircle ? `（正在：${currentCircle}）` : ''}` : ''],
    ['批量结果', isBatch ? `成功 ${completedQueries} / 失败 ${failedQueries}` : ''],
    ['Maker ID', indexMeta.maker_id || ''],
    ['来源模式', indexMeta.dlsite_source_mode || ''],
    ['DLsite失败原因', getDLsiteFailureReason(item)],
    ['本地候选', indexMeta.local_candidates_count],
    ['Kikoeru', indexMeta.kikoeru_candidates_count],
    ['DLsite原作', indexMeta.dlsite_profile_total || indexMeta.dlsite_candidates_count],
    ['合并候选', indexMeta.combined_candidates_count || indexMeta.aggregated_count],
    ['已检查下载', indexMeta.asmr_checked_count],
    ['可下载', indexMeta.asmr_available_count || indexedCounts.downloadable_count],
    ['最终作品', indexedCounts.works],
    ['服务器缺失', indexedCounts.missing_count]
  ]
  return entries
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([label, value]) => ({ label, value: String(value) }))
}

export function getCircleIndexProgressLog(item) {
  if (item?.kind !== 'circle_completion_index') return []
  const metadata = item?.details?.metadata || {}
  const logs = Array.isArray(metadata.progress_log) ? metadata.progress_log : []
  return [...logs].reverse()
}

export function getGarbledDiagnostic(item) {
  const metadata = item?.details?.metadata || item?.metadata || {}
  const sample = metadata.garbled_filename_sample || ''
  const topSamples = Array.isArray(metadata.garbled_filename_top_samples) ? metadata.garbled_filename_top_samples : []
  if (!sample && !topSamples.length) return null
  return {
    sample,
    scoreBefore: Number(metadata.garbled_filename_score_before ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    scoreAfter: Number(metadata.garbled_filename_score_after ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    repairedCount: Number(metadata.garbled_filename_repaired_count || 0),
    codecPairsTried: Number(metadata.garbled_filename_codec_pairs_tried || 0),
    origin: metadata.garbled_filename_guard_origin || '',
    totalNames: Number(metadata.garbled_filename_total_names || 0),
    garbledCount: Number(metadata.garbled_filename_garbled_count || 0),
    surrogateRepairedCount: Number(metadata.garbled_filename_surrogate_repaired_count || 0),
    surrogateEscapedCount: Number(metadata.garbled_filename_surrogate_escaped_count || 0),
    topSamples
  }
}

export function buildGarbledSummary(info) {
  if (!info) return ''
  const total = info.totalNames ? `，扫描 ${info.totalNames} 个文件名` : ''
  const count = info.garbledCount ? `，命中 ${info.garbledCount} 个高风险名称` : ''
  const surrogateBits = []
  if (info.surrogateRepairedCount) surrogateBits.push(`自动反解 ${info.surrogateRepairedCount} 个非 UTF-8 文件名`)
  if (info.surrogateEscapedCount) surrogateBits.push(`字面转义 ${info.surrogateEscapedCount} 个`)
  const surrogateText = surrogateBits.length ? `；本次${surrogateBits.join('、')}。` : ''
  return `7zz 已完成解压，但文件名评分达到 ${info.scoreAfter}（阈值 >= 30）${total}${count}。系统已尝试常见编码反解，仍认为存在乱码风险${surrogateText}`
}

export function getTaskSummary(item) {
  const metrics = Array.isArray(item?.metrics) ? item.metrics : []
  const pieces = []
  const pushMetric = label => {
    const value = metrics.find(metric => metric?.label === label)?.value
    if (value !== undefined && value !== null && String(value).trim() !== '') pieces.push(`${label} ${value}`)
  }
  if (formatRJCode(item?.rjcode)) pieces.push(formatRJCode(item.rjcode))
  if (item?.domain === 'circle_completion') {
    ;['DLsite', '可下载', '本地', '缺失'].forEach(pushMetric)
  } else if (item?.domain === 'asmr_sync' || item?.domain === 'upload') {
    ;['下载文件', '已上传', '上传大小', '平均上传', '失败文件'].forEach(pushMetric)
  } else if (item?.domain === 'rj_subtitle' || item?.domain === 'subtitle_import') {
    ;['下载', '写入', '来源字幕', '候选目录', '可执行候选'].forEach(pushMetric)
  } else {
    ;['目标库', '输出', '此前失败', '问题作品'].forEach(pushMetric)
  }
  return dedupePieces(pieces).slice(0, 6)
}

export function buildFileTreeSections(item, expandedState = {}, filterMode = 'all') {
  const metadata = item?.details?.metadata || {}
  const entries = [
    ...mapFileEntries(metadata.file_tree_items, 'default'),
    ...mapFileEntries(metadata.upload_files || metadata.uploaded_files, 'added'),
    ...mapFileEntries(metadata.download_files, 'added'),
    ...mapFileEntries(metadata.filtered_items || metadata.filtered_files || metadata.filtered_dirs, 'removed')
  ]
  const normalized = new Map()
  for (const entry of entries) {
    const relativePath = String(entry.relative_path || entry.path || entry.name || '').replace(/^[/\\]+|[/\\]+$/g, '').replace(/\\/g, '/')
    if (!relativePath) continue
    const previous = normalized.get(relativePath)
    normalized.set(relativePath, { ...(previous || {}), ...entry, relative_path: relativePath })
  }
  const allItems = [...normalized.values()]
  const removedCount = allItems.filter(item => item.status === 'removed').length
  const displayItems = filterMode === 'removed' ? allItems.filter(item => item.status === 'removed') : allItems
  if (!displayItems.length) return []
  const tree = buildTreeRows(displayItems, expandedState)
  const directoryKeys = collectDirectoryKeys(allItems)
  return [{
    key: 'files',
    label: '文件列表',
    rows: tree,
    totalCount: allItems.length,
    removedCount,
    directoryKeys,
    allExpanded: directoryKeys.length ? directoryKeys.every(key => expandedState[key] ?? true) : true
  }]
}

function mapFileEntries(value, status) {
  const list = Array.isArray(value) ? value : []
  return list.map((item, index) => {
    const obj = typeof item === 'object' && item !== null ? item : { path: String(item || '') }
    const relativePath = obj.relative_path || obj.path || obj.name || `${index}`
    return {
      relative_path: relativePath,
      name: obj.name || getFileName(relativePath),
      type: obj.type === 'dir' || obj.is_dir ? 'dir' : 'file',
      size: obj.size ?? obj.size_bytes,
      status
    }
  })
}

function buildTreeRows(items, expandedState) {
  const root = []
  const map = new Map()
  for (const item of items) {
    const parts = String(item.relative_path || '').split('/').filter(Boolean)
    let parent = root
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const key = `${isLeaf ? item.type : 'dir'}:${joined}`
      let node = map.get(key)
      if (!node) {
        node = { key, pathKey: joined, label: part, type: isLeaf ? item.type : 'dir', status: 'default', size: null, children: [] }
        map.set(key, node)
        parent.push(node)
      }
      if (isLeaf) {
        node.status = item.status || node.status
        node.size = item.size
        node.type = item.type || node.type
      }
      parent = node.children
    })
  }
  const rows = []
  const walk = (nodes, depth = 0) => {
    nodes.sort((left, right) => {
      if (left.type !== right.type) return left.type === 'dir' ? -1 : 1
      return left.label.localeCompare(right.label, 'zh-CN', { numeric: true, sensitivity: 'base' })
    })
    for (const node of nodes) {
      const hasChildren = node.children.length > 0
      const expanded = hasChildren ? (expandedState[node.pathKey] ?? true) : false
      rows.push({
        ...node,
        depth,
        hasChildren,
        expanded,
        sizeText: node.size !== undefined && node.size !== null ? formatBytes(node.size) : ''
      })
      if (hasChildren && expanded) walk(node.children, depth + 1)
    }
  }
  walk(root)
  return rows
}

function collectDirectoryKeys(items) {
  const keys = new Set()
  for (const item of items) {
    const parts = String(item.relative_path || '').split('/').filter(Boolean)
    let joined = ''
    parts.slice(0, item.type === 'dir' ? parts.length : -1).forEach(part => {
      joined = joined ? `${joined}/${part}` : part
      keys.add(joined)
    })
  }
  return [...keys]
}

function dedupePieces(pieces) {
  const seen = new Set()
  const out = []
  for (const piece of pieces) {
    const key = String(piece || '').trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(key)
  }
  return out
}
