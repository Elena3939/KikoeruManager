import {
  AlertCircle,
  Archive,
  CheckCircle2,
  Clock,
  Database,
  File,
  FileArchive,
  FileText,
  Film,
  Folder,
  History,
  Image,
  Link,
  Mail,
  MinusCircle,
  Music,
  Package,
  RefreshCw,
  Scissors,
  Search,
  ShieldAlert,
  Tag,
  Upload,
  Users,
  XCircle
} from 'lucide-react'
import { formatBytes } from '../../utils/format'

export const activityCategoryOptions = [
  { value: 'all', label: '全部分类' },
  { value: 'subtitle_crawl', label: '字幕爬取' },
  { value: 'subtitle_pair', label: '字幕配对' },
  { value: 'subtitle_import', label: '字幕补配' },
  { value: 'extract', label: '解压' },
  { value: 'auto_import', label: '解压入库' },
  { value: 'process_existing', label: '已有目录处理' },
  { value: 'pipeline_filter', label: '筛选' },
  { value: 'pipeline_metadata', label: '元数据' },
  { value: 'pipeline_rename', label: '重命名' },
  { value: 'pipeline_delete', label: '删除' },
  { value: 'asmr_sync', label: 'ASMR 同步' },
  { value: 'upload', label: '库存上传' },
  { value: 'circle_completion', label: '社团补全' },
  { value: 'email_watcher', label: '邮件监听' },
  { value: 'conflict_resolution', label: '问题作品处理' }
]

export const activityStatusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'partial_success', label: '部分成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'waiting', label: '等待中' },
  { value: 'incomplete', label: '未完成' }
]

export const activityPageSizeOptions = [
  { value: '30', label: '30 条' },
  { value: '50', label: '50 条' },
  { value: '100', label: '100 条' },
  { value: '200', label: '200 条' }
]

export const statsDaysOptions = [
  { value: '0', label: '所有时间' },
  { value: '7', label: '近 7 天' },
  { value: '14', label: '近 14 天' },
  { value: '30', label: '近 30 天' }
]

export const categoryConfigs = {
  subtitle_crawl: { icon: Search, label: '字幕爬取', tone: 'indigo' },
  subtitle_pair: { icon: Link, label: '字幕配对', tone: 'violet' },
  subtitle_import: { icon: FileText, label: '字幕补配', tone: 'fuchsia' },
  extract: { icon: Package, label: '解压', tone: 'teal' },
  auto_import: { icon: Database, label: '解压入库', tone: 'emerald' },
  process_existing: { icon: Folder, label: '已有目录处理', tone: 'lime' },
  pipeline_filter: { icon: Archive, label: '筛选', tone: 'amber' },
  pipeline_metadata: { icon: Tag, label: '元数据', tone: 'slate' },
  pipeline_rename: { icon: Tag, label: '重命名', tone: 'orange' },
  pipeline_delete: { icon: Scissors, label: '删除', tone: 'rose' },
  asmr_sync: { icon: RefreshCw, label: 'ASMR 同步', tone: 'cyan' },
  upload: { icon: Upload, label: '库存上传', tone: 'sky' },
  circle_completion: { icon: Users, label: '社团补全', tone: 'blue' },
  email_watcher: { icon: Mail, label: '邮件监听', tone: 'purple' },
  conflict_resolution: { icon: ShieldAlert, label: '问题作品处理', tone: 'blue' },
  default: { icon: Tag, label: '其他', tone: 'slate' }
}

export const statusConfigs = {
  success: { icon: CheckCircle2, label: '成功', tone: 'success' },
  completed: { icon: CheckCircle2, label: '完成', tone: 'success' },
  partial_success: { icon: AlertCircle, label: '部分成功', tone: 'warn' },
  failed: { icon: XCircle, label: '失败', tone: 'danger' },
  error: { icon: XCircle, label: '错误', tone: 'danger' },
  cancelled: { icon: MinusCircle, label: '已取消', tone: 'neutral' },
  waiting: { icon: Clock, label: '等待中', tone: 'info' },
  incomplete: { icon: Clock, label: '未完成', tone: 'info' },
  info: { icon: History, label: '信息', tone: 'info' },
  default: { icon: MinusCircle, label: '-', tone: 'neutral' }
}

const partialKeywords = [
  '加入问题作品列表',
  '已转入问题作品',
  '问题作品',
  '字幕冲突',
  '已有字幕'
]

export function getCategoryConfig(category) {
  return categoryConfigs[category] || categoryConfigs.default
}

export function getStatusConfig(status) {
  return statusConfigs[status] || statusConfigs.default
}

export function safeDetail(row) {
  return row?.detail && typeof row.detail === 'object' ? row.detail : {}
}

export function effectiveStatus(row) {
  if (!row) return ''
  const raw = String(row.status || '')
  if (['success', 'completed', 'partial_success'].includes(raw)) {
    const failedChildren = Number(row.child_failed_count || 0)
    const partialChildren = Number(row.child_partial_count || 0)
    const successChildren = Number(row.child_success_count || 0)
    if (failedChildren > 0) return successChildren + partialChildren > 0 ? 'partial_success' : 'failed'
    if (partialChildren > 0) return 'partial_success'
  }
  if (raw !== 'success') return raw
  const detail = safeDetail(row)
  const summary = String(row.summary || '')
  if (partialKeywords.some(keyword => summary.includes(keyword))) return 'partial_success'
  if (detail.linked_subtitle_problem || detail.existing_subtitle_problem) return 'partial_success'
  if (String(detail.source_mode || '').endsWith('_existing_subtitle_conflict')) return 'partial_success'
  return raw
}

export function isPureProblemPartial(row) {
  if (!row) return false
  if (Number(row.child_failed_count || 0) > 0) return false
  const detail = safeDetail(row)
  if (partialKeywords.some(keyword => String(row.summary || '').includes(keyword))) return true
  if (detail.linked_subtitle_problem || detail.existing_subtitle_problem) return true
  if (String(detail.source_mode || '').endsWith('_existing_subtitle_conflict')) return true
  return Number(row.child_partial_count || 0) > 0
}

export function displayRjcode(row) {
  const detail = safeDetail(row)
  const candidates = [
    row?.rjcode,
    detail.rjcode,
    detail.source_rjcode,
    detail.preview_source_rjcode,
    detail.target_rjcode,
    row?.source_path,
    row?.summary,
    row?.task_id
  ]
  for (const value of candidates) {
    const match = String(value || '').match(/RJ\d{4,}/i)
    if (match) return match[0].toUpperCase()
  }
  return ''
}

export function humanAction(row) {
  if (!row) return ''
  const detail = safeDetail(row)
  const cat = String(row.category || '')
  const action = String(row.action || '')
  const status = effectiveStatus(row)
  const conflictAction = String(detail.conflict_resolution_action || '').trim().toUpperCase()

  if (conflictAction && ['task_finished', 'task_finished_incomplete'].includes(action)) {
    if (conflictAction === 'SKIP') return '已跳过'
    if (conflictAction === 'KEEP_NEW') return '已保留新版'
    if (conflictAction === 'MERGE') return '已合并'
  }
  if (row.is_tree_child) {
    if (row.relation === 'rerun') return status === 'success' ? '重试完成' : status === 'failed' ? '重试失败' : '重试'
    if (row.relation === 'subtitle_import') return status === 'success' ? '字幕补配完成' : status === 'failed' ? '字幕补配失败' : '字幕补配'
    if (row.relation === 'pair') return status === 'success' ? '字幕手动配对完成' : '字幕手动配对'
    if (row.relation === 'delete_apply') return status === 'partial_success' ? '删除执行部分成功' : status === 'failed' ? '删除执行失败' : '删除执行'
    if (row.relation === 'asmr_resource') return status === 'success' ? '文件下载完成' : '文件下载'
    if (row.relation === 'asmr_upload') return status === 'success' ? '文件上传完成' : '文件上传'
  }
  if (cat === 'subtitle_crawl') {
    if (action === 'batch_start') return getStatusConfig(status).label
    if (status === 'success') return '抓取完成'
    if (status === 'failed') return '抓取失败'
    if (status === 'waiting') return '等待中'
  }
  if (cat === 'subtitle_pair') return status === 'success' ? '配对完成' : '手动配对'
  if (cat === 'subtitle_import') return status === 'success' ? '补配完成' : '补配失败'
  if (cat === 'extract') return status === 'success' ? '解压完成' : '解压失败'
  if (cat === 'auto_import') {
    if (status === 'success') return '入库完成'
    if (status === 'partial_success') return isPureProblemPartial(row) ? '转入问题作品' : '部分入库'
    if (status === 'failed') return '入库失败'
    if (status === 'incomplete') return '未正常结束'
  }
  if (cat === 'process_existing') {
    if (status === 'success') return '处理完成'
    if (status === 'partial_success') return '部分处理'
    if (status === 'failed') return '处理失败'
  }
  if (cat === 'asmr_sync') {
    if (action === 'session_completed' || status === 'success') return 'ASMR 下载完成'
    if (action === 'session_partial_failed' || status === 'partial_success') return 'ASMR 部分失败'
    if (status === 'failed') return 'ASMR 下载失败'
  }
  if (cat === 'upload') {
    if (status === 'success') return '上传完成'
    if (status === 'failed') return '上传失败'
    if (status === 'cancelled') return '上传取消'
  }
  if (cat === 'pipeline_filter') {
    if (action === 'filter_delete_preview') return '删除预审'
    if (action === 'filter_delete_apply') return '删除执行'
    if (action === 'filter_delete_preview_retry') return '失败项重试'
  }
  if (cat === 'pipeline_rename' || cat === 'pipeline_delete') {
    if (status === 'success') return '完成'
    if (status === 'partial_success') return '部分成功'
    if (status === 'failed') return '失败'
  }
  if (cat === 'circle_completion') {
    if (action === 'index_completed') return '索引完成'
    if (action === 'refresh_selected_works') return '刷新作品'
    if (action === 'download_batch_start') return '创建下载任务'
  }
  if (cat === 'email_watcher') {
    if (action === 'fetch_check') return '监视邮件'
    if (action === 'circle_index_triggered') return '触发索引'
  }
  return getStatusConfig(status).label
}

export function displaySummary(row) {
  const text = String(row?.summary || '').trim()
  if (!text) return '-'
  const rj = displayRjcode(row)
  if (row?.category === 'pipeline_filter' && rj && text.includes('未知RJ')) {
    return text.replace(/未知RJ号?|未知RJ/gi, rj)
  }
  return text
}

export function compactPath(value, head = 24, tail = 42) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.length <= head + tail + 3) return text
  return `${text.slice(0, head)}...${text.slice(-tail)}`
}

export function formatFullDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

export function formatClock(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function formatShortDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function formatNumber(value) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '0'
}

export function formatGb(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '0.00 GB'
  const gb = bytes / (1024 ** 3)
  if (gb > 0 && gb < 0.01) return '<0.01 GB'
  return `${gb.toFixed(2)} GB`
}

export function splitMetric(value) {
  const text = String(value ?? '').trim()
  if (!text) return { num: '-', unit: '' }
  const match = text.match(/^([+\-]?[\d.,<>= ]+)\s*([^\s].*?)$/)
  if (!match) return { num: text, unit: '' }
  return { num: match[1].trim(), unit: match[2].trim() }
}

export function metricCards(stats) {
  const metrics = stats?.metrics || {}
  const days = Number(stats?.days || 0)
  const suffix = days ? `${days} 天内` : '所有时间'
  return [
    { key: 'subtitle_download_count', label: '字幕下载', value: formatNumber(metrics.subtitle_download_count), hint: `${suffix}成功抓取到的字幕文件数` },
    { key: 'subtitle_match_count', label: '手动配对', value: formatNumber(metrics.subtitle_match_count), hint: `${suffix}手动配对实际应用的组数` },
    { key: 'subtitle_crawl_count', label: '匹配 RJ', value: formatNumber(metrics.subtitle_crawl_count), hint: `${suffix}成功匹配并创建抓取任务的 RJ 目录数` },
    { key: 'subtitle_import_count', label: '补配个数', value: formatNumber(metrics.subtitle_import_count), hint: `${suffix}成功补配写入的文件数` },
    { key: 'extract_count', label: '解压个数', value: formatNumber(metrics.extract_count), hint: `${suffix}成功完成的解压任务数` },
    { key: 'delete_count', label: '删除个数', value: formatNumber(metrics.delete_count), hint: `${suffix}删除过滤实际删除的项数` },
    { key: 'delete_bytes', label: '删除大小', value: formatGb(metrics.delete_bytes), hint: `${suffix}按删除成功项累计` },
    { key: 'extract_bytes', label: '解压大小', value: formatGb(metrics.extract_bytes), hint: `${suffix}解压后产物大小累计` }
  ]
}

export function groupTimeline(rows) {
  const today = startOfDay(new Date())
  const yesterday = addDays(today, -1)
  const groups = []
  const map = new Map()

  for (const row of rows || []) {
    const date = row?.created_at ? new Date(row.created_at) : null
    let key = '__unknown'
    let label = '未知时间'
    if (date && !Number.isNaN(date.getTime())) {
      const day = startOfDay(date)
      key = day.toISOString().slice(0, 10)
      if (day.getTime() === today.getTime()) label = '今天'
      else if (day.getTime() === yesterday.getTime()) label = '昨天'
      else if (day > addDays(today, -7)) label = `${day.getMonth() + 1}月${day.getDate()}日（${weekDayName(day)}）`
      else if (day > addDays(today, -30)) label = `${day.getMonth() + 1}月${day.getDate()}日`
      else label = `${day.getFullYear()}年${day.getMonth() + 1}月${day.getDate()}日`
    }
    if (!map.has(key)) {
      const group = { key, label, items: [] }
      map.set(key, group)
      groups.push(group)
    }
    map.get(key).items.push(row)
  }
  return groups
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function addDays(date, days) {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function weekDayName(date) {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()]
}

export function buildSparkline(days = [], width = 420, height = 96) {
  const rows = Array.isArray(days) ? days : []
  if (!rows.length) return null
  const max = Math.max(1, ...rows.map(item => Number(item.count || 0)))
  const step = rows.length > 1 ? width / (rows.length - 1) : width
  const points = rows.map((item, index) => ({
    date: item.date,
    count: Number(item.count || 0),
    x: rows.length > 1 ? index * step : width / 2,
    y: height - (Number(item.count || 0) / max) * (height - 16) - 8
  }))
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
  const area = `${line} L ${points[points.length - 1].x.toFixed(2)} ${height} L ${points[0].x.toFixed(2)} ${height} Z`
  return { points, line, area, last: points[points.length - 1], width, height }
}

export function categoryRows(stats) {
  const rows = Array.isArray(stats?.by_category) ? stats.by_category : []
  const total = rows.reduce((sum, item) => sum + Number(item.count || 0), 0) || 1
  return rows.map((item, index) => ({
    key: item.category || `cat-${index}`,
    label: item.label || getCategoryConfig(item.category).label,
    count: Number(item.count || 0),
    pct: Math.max(2, Math.round((Number(item.count || 0) / total) * 100)),
    tone: getCategoryConfig(item.category).tone
  }))
}

const highlightLabels = {
  rjcode: 'RJ',
  source_rjcode: '来源 RJ',
  target_rjcode: '目标 RJ',
  downloaded_count: '抓取字幕数',
  written_files_count: '写入字幕数',
  awaiting_manual_match: '待手动配对',
  output_path: '输出目录',
  source_basename: '压缩包文件',
  archive_size_bytes: '压缩包大小',
  extract_output_bytes: '解压产物大小',
  filtered_count: '过滤文件数',
  filtered_size: '过滤体积',
  final_file_count: '最终文件数',
  record_id: '记录 ID',
  import_final_file_count: '导入文件数',
  recovered_failure_count: '修复失败数',
  duration_ms: '耗时',
  selected_count: '命中数量',
  selected_size: '命中体积',
  success_count: '成功数量',
  failed_count: '失败数量',
  deleted_bytes: '删除体积',
  retry_target_count: '重试目标数',
  retry_success_count: '重试成功数',
  retry_failed_count: '重试失败数',
  batch_task_count: '下载任务数',
  downloaded_bytes: '下载大小',
  uploaded_bytes: '上传大小',
  average_upload_speed_bytes: '平均上传速度',
  download_root: '下载目录',
  final_output_path: '最终入库路径',
  target_path: '上传目标',
  target_library_id: '目标库存',
  target_subdir: '库存前缀目录',
  source_base_path: '来源根目录',
  upload_mode: '上传模式',
  uploaded_count: '上传文件数',
  selected_dir_count: '上传目录数',
  circle_name: '社团名',
  local_owned_count: '本地已有',
  owned_count: '服务器已有',
  missing_count: '缺失数量',
  downloadable_count: '可下载数量',
  works_count: '作品总数',
  scan_directory_count: '扫描目录数',
  recognized_rj_count: '识别 RJ 数',
  created_count: '创建任务数',
  skipped_total: '跳过数量'
}

const byteKeys = new Set([
  'selected_size',
  'deleted_bytes',
  'archive_size_bytes',
  'extract_output_bytes',
  'filtered_size',
  'uploaded_bytes',
  'downloaded_bytes',
  'size_bytes'
])

export function detailHighlights(row) {
  const detail = safeDetail(row)
  const out = []
  for (const key of Object.keys(highlightLabels)) {
    if (detail[key] === undefined || detail[key] === null) continue
    let value = detail[key]
    if (key === 'duration_ms') value = formatDurationMs(value)
    else if (key === 'awaiting_manual_match') value = value ? '是' : '否'
    else if (byteKeys.has(key)) value = formatBytes(value)
    else if (key === 'average_upload_speed_bytes') value = `${formatBytes(value)}/s`
    const text = String(value ?? '').trim()
    if (!text) continue
    out.push({ key, label: highlightLabels[key], value: text })
    if (out.length >= 14) break
  }
  return out
}

export function formatDurationMs(value) {
  const ms = Math.max(0, Number(value || 0))
  if (ms < 1000) return `${Math.round(ms)} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round(seconds % 60)
  return `${minutes} 分 ${remain} 秒`
}

export function childRows(row) {
  const out = []
  const seen = new Set()
  const walk = (rows, depth = 0) => {
    for (const item of Array.isArray(rows) ? rows : []) {
      if (!item || typeof item !== 'object') continue
      const key = String(item.id || `${item.relation || ''}-${item.created_at || ''}-${item.action || ''}`)
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ ...item, __depth: depth })
      walk(item.child_rows, depth + 1)
      walk(item.detail?.child_rows, depth + 1)
    }
  }
  walk(row?.child_rows, 0)
  walk(row?.detail?.child_rows, 0)
  return out
}

export function fileSections(row) {
  const detail = safeDetail(row)
  const sections = []
  const candidates = [
    ['download_files', '下载文件'],
    ['upload_files', '上传文件'],
    ['uploaded_files', '已上传文件'],
    ['entries', '文件清单'],
    ['files', '文件清单'],
    ['filtered_items', '过滤命中'],
    ['deleted_items', '已删除项目'],
    ['failed_items', '失败项目'],
    ['success_items', '成功项目'],
    ['items', '业务项目']
  ]
  for (const [key, title] of candidates) {
    const value = detail[key]
    if (!Array.isArray(value) || !value.length) continue
    sections.push({ key, title, rows: value.slice(0, 600) })
  }
  return sections
}

export function entryLabel(item) {
  if (item == null) return '-'
  if (typeof item !== 'object') return String(item)
  return String(item.name || item.filename || item.relative_path || item.path || item.resource_path || item.title || item.rjcode || item.id || '-')
}

export function entryMeta(item) {
  if (!item || typeof item !== 'object') return ''
  const parts = []
  if (item.status) parts.push(item.status)
  if (item.size || item.size_bytes) parts.push(formatBytes(item.size || item.size_bytes))
  if (item.error || item.reason) parts.push(item.error || item.reason)
  return parts.filter(Boolean).join(' · ')
}

export function entryIcon(item) {
  const name = entryLabel(item).toLowerCase()
  if (item?.type === 'dir' || item?.is_dir) return Folder
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)) return Music
  if (/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(name)) return Image
  if (/\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i.test(name)) return Film
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/i.test(name)) return FileArchive
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return FileText
  return File
}

export function stringifyDetail(detail) {
  const seen = new WeakSet()
  const compact = (value, depth = 0) => {
    if (value === null || typeof value !== 'object') {
      if (typeof value === 'string' && value.length > 1200) return `${value.slice(0, 1200)}...（已截断 ${value.length - 1200} 字符）`
      return value
    }
    if (seen.has(value)) return '[Circular]'
    if (depth >= 4) return Array.isArray(value) ? `[Array(${value.length})]` : `[Object(${Object.keys(value).length})]`
    seen.add(value)
    if (Array.isArray(value)) {
      const out = value.slice(0, 80).map(item => compact(item, depth + 1))
      if (value.length > 80) out.push(`...（已省略 ${value.length - 80} 项）`)
      return out
    }
    const entries = Object.entries(value)
    const out = {}
    for (const [key, item] of entries.slice(0, 80)) out[key] = compact(item, depth + 1)
    if (entries.length > 80) out.__truncated_keys__ = `已省略 ${entries.length - 80} 个字段`
    return out
  }
  try {
    const text = JSON.stringify(compact(detail), null, 2)
    return text.length > 60000 ? `${text.slice(0, 60000)}\n...（原始 JSON 过大，已截断 ${text.length - 60000} 字符）` : text
  } catch {
    return ''
  }
}
