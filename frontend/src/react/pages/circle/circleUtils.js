import { formatBytes } from '../../utils/format'

export const WORK_PAGE_SIZES = [12, 24, 48, 96]
export const COMPARE_PAGE_SIZES = [10, 20, 50, 100]
export const UNRELEASED_PLACEHOLDER_TIMESTAMP = new Date(2099, 0, 1).getTime()

export function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  const match = text.match(/[RBV]J(\d{6}|\d{8})(?!\d)/i)
  return match ? match[0].toUpperCase() : text
}

export function getWorkCode(item) {
  return String(item?.source_compare?.work_rjcode || item?.canonical_rjcode || item?.display_rjcode || item?.rjcode || '').trim()
}

export function getDisplayCode(item) {
  return String(item?.source_compare?.work_rjcode || item?.canonical_rjcode || item?.rjcode || '').trim()
}

export function buildDlsiteCoverUrl(rjcode, unreleased = false, variant = 'sam') {
  const normalized = normalizeRjcode(rjcode)
  const match = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!match) return ''
  const number = Number(match[1])
  const folderUpper = (Math.floor(number / 1000) + 1) * 1000
  const folder = `RJ${String(folderUpper).padStart(match[1].length, '0')}`
  const pathType = unreleased ? 'announce' : 'work'
  if (variant === 'sam') {
    if (unreleased) return `https://img.dlsite.jp/modpub/images2/ana/doujin/${folder}/${normalized}_ana_img_main.jpg`
    return `https://img.dlsite.jp/modpub/images2/${pathType}/doujin/${folder}/${normalized}_img_sam.jpg`
  }
  if (variant === 'resized') return `https://img.dlsite.jp/resize/images2/${pathType}/doujin/${folder}/${normalized}_img_main_240x240.jpg`
  return `https://img.dlsite.jp/modpub/images2/${pathType}/doujin/${folder}/${normalized}_img_main.jpg`
}

export function isWorkUnreleased(item) {
  if (item?.is_unreleased) return true
  const value = String(item?.release_date || item?.date || item?.release_at || '').trim()
  if (!value) return false
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return false
  const year = Number(match[1])
  const month = Number(match[2]) - 1
  let day = Number(match[3] || 1)
  if (!match[3] && value.includes('下旬')) day = 28
  else if (!match[3] && value.includes('中旬')) day = 20
  else if (!match[3] && value.includes('上旬')) day = 10
  const releaseDate = new Date(year, month, day)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return releaseDate > today
}

export function releaseLabel(item) {
  const value = String(item?.release_date || item?.date || item?.release_at || '').trim()
  if (!value) return item?.is_unreleased ? '待定' : ''
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return value
  const month = String(match[2]).padStart(2, '0')
  let day = ''
  if (match[3]) day = `/${String(match[3]).padStart(2, '0')}`
  else if (value.includes('下旬')) day = ' 下旬'
  else if (value.includes('中旬')) day = ' 中旬'
  else if (value.includes('上旬')) day = ' 上旬'
  return `${match[1]}/${month}${day}`
}

export function parseReleaseDateForSort(raw) {
  const text = String(raw || '').trim()
  if (!text) return 0
  const fullDateMatch = text.match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/)
  if (fullDateMatch) {
    const year = Number(fullDateMatch[1])
    const month = Number(fullDateMatch[2])
    const day = Number(fullDateMatch[3])
    if (year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      return new Date(year, month - 1, day).getTime()
    }
  }
  const monthMatch = text.match(/(\d{4})\D+(\d{1,2})\D*(上旬|中旬|下旬)/)
  if (monthMatch) {
    const year = Number(monthMatch[1])
    const month = Number(monthMatch[2])
    const phase = monthMatch[3]
    const day = phase === '上旬' ? 9 : phase === '中旬' ? 19 : new Date(year, month, 0).getDate()
    return new Date(year, month - 1, day).getTime()
  }
  const normalized = text.replace(/[年./]/g, '-').replace(/月/g, '-').replace(/日/g, '').replace(/\s+/g, '')
  const exactTimestamp = new Date(normalized).getTime()
  if (Number.isFinite(exactTimestamp) && exactTimestamp > 0) return exactTimestamp
  const yearMonthMatch = normalized.match(/^(\d{4})-(\d{1,2})$/)
  if (yearMonthMatch) return new Date(Number(yearMonthMatch[1]), Number(yearMonthMatch[2]) - 1, 1).getTime()
  const looseYearMonthMatch = text.match(/(\d{4})\D+(\d{1,2})/)
  if (looseYearMonthMatch) return new Date(Number(looseYearMonthMatch[1]), Number(looseYearMonthMatch[2]) - 1, 1).getTime()
  return 0
}

export function getWorkReleaseTimestamp(item) {
  const raw = String(item?.release_date || item?.date || item?.release_at || '').trim()
  const timestamp = raw ? parseReleaseDateForSort(raw) : 0
  if (Number.isFinite(timestamp) && timestamp > 0) return timestamp
  return item?.is_unreleased ? UNRELEASED_PLACEHOLDER_TIMESTAMP : 0
}

export function sortWorksByRelease(list, direction = 'desc') {
  if (direction !== 'asc' && direction !== 'desc') return list
  const dir = direction === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    const diff = getWorkReleaseTimestamp(a) - getWorkReleaseTimestamp(b)
    if (diff !== 0) return diff * dir
    return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
  })
}

export function sortCompareWorksByRelease(list, direction = 'desc') {
  if (direction !== 'asc' && direction !== 'desc') return list
  const dir = direction === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    const diff = (a.releaseTimestamp || 0) - (b.releaseTimestamp || 0)
    if (diff !== 0) return diff * dir
    return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
  })
}

export function getCircleWorksCount(circle) {
  return Number(circle?.dl_works || circle?.total_works || 0)
}

export function getCircleOwnedCount(circle) {
  return Number(circle?.server_owned || 0)
}

export function getCircleMissingCount(circle) {
  return Math.max(0, Number(circle?.missing || 0))
}

export function getCircleOwnedPercent(circle) {
  const total = getCircleWorksCount(circle)
  const owned = getCircleOwnedCount(circle)
  if (!total) return 0
  return Math.min(100, Math.round((owned / total) * 100))
}

export function getCircleCompletionState(circle) {
  const works = getCircleWorksCount(circle)
  const missing = getCircleMissingCount(circle)
  return works > 0 && missing === 0 ? 'completed' : 'incomplete'
}

export function getCircleRefreshTimestamp(circle) {
  const raw = circle?.last_indexed_at || circle?.updated_at || circle?.refreshed_at || circle?.created_at || ''
  const timestamp = new Date(raw).getTime()
  return Number.isFinite(timestamp) ? timestamp : 0
}

export function isPreferredMissingWorkVisible(item) {
  if (item?.owned) return false
  const groupKey = String(item?.preferred_variant?.group_key || '').trim()
  return ['original', 'simplified', 'traditional'].includes(groupKey || 'original')
}

export function itemMatchesStatusFilter(item, key) {
  if (key === 'repairable') return Boolean(item?.subtitle_repairable)
  if (key === 'downloadable') return Boolean(item?.has_asmr_one) && !isWorkUnreleased(item)
  if (key === 'missing') return !Boolean(item?.owned)
  if (key === 'no_source') return !Boolean(item?.owned) && !Boolean(item?.has_asmr_one)
  return true
}

export function normalizeStatusFilters(next, previous = []) {
  const allowed = new Set(['repairable', 'downloadable', 'missing', 'no_source'])
  let values = [...new Set((Array.isArray(next) ? next : []).filter(value => allowed.has(value)))]
  const addedValue = values.find(value => !(previous || []).includes(value))
  const exclusiveGroups = [['downloadable', 'no_source'], ['repairable', 'missing']]
  for (const group of exclusiveGroups) {
    const selectedInGroup = values.filter(value => group.includes(value))
    if (selectedInGroup.length <= 1) continue
    const keepValue = addedValue && group.includes(addedValue) ? addedValue : selectedInGroup[selectedInGroup.length - 1]
    values = values.filter(value => !group.includes(value) || value === keepValue)
  }
  return values
}

export function getOwnedVariantGroupLabel(item) {
  return item?.owned_variant?.group_short_label || '原作'
}

export function getOwnedVariantGroupKey(item) {
  return item?.owned_variant?.group_key || 'original'
}

export function formatServerOwnedLabel(item) {
  if (!item?.server_owned) return '服务器缺失'
  const matched = String(
    item?.server_match_primary_rjcode ||
    item?.source_compare?.kikoeru?.matched_rjcode ||
    item?.source_compare?.kikoeru?.primary_rjcode ||
    ''
  ).trim()
  return matched ? `服务器已有 · ${matched}` : '服务器已有'
}

export function normalizeKikoeruTags(tags) {
  const source = Array.isArray(tags) ? tags : []
  const normalized = []
  for (const tag of source) {
    const text = String(tag || '').trim()
    if (!text) continue
    const value = text.startsWith('字幕') ? '字幕' : text
    if (!normalized.includes(value)) normalized.push(value)
  }
  return normalized
}

export function formatElapsed(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)))
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

export function formatEtaSeconds(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)))
  if (!totalSeconds) return '-'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${Math.floor((totalSeconds % 3600) / 60)}分`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

export function formatSpeed(bytesPerSec) {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatBytes(value)}/s` : '-'
}

export function formatLogTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString()
}

export function getJobProgressPercent(job) {
  const value = Number(job?.progress || 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

export function getDownloadRuntime(task) {
  const runtime = task?.download_runtime || task?.performance_metrics?.download_runtime || task?.task_metadata?.performance_metrics?.download_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

export function getUploadRuntime(task) {
  const runtime = task?.upload_runtime || task?.performance_metrics?.upload_runtime || task?.task_metadata?.performance_metrics?.upload_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

export function isTaskFinished(task) {
  return ['completed', 'failed', 'partial_failed'].includes(String(task?.display_status || task?.status || ''))
}

export function getDownloadSpeedBytes(task) {
  const runtimeSpeed = Number(getDownloadRuntime(task)?.speed_bytes_per_sec || 0)
  if (runtimeSpeed > 0) return runtimeSpeed
  if (isTaskFinished(task)) {
    const details = task?.performance_metrics || task?.task_metadata?.performance_metrics || {}
    return Number(details?.average_download_speed_bytes || 0)
  }
  return 0
}

export function getDownloadEtaSeconds(task) {
  return Number(getDownloadRuntime(task)?.eta_seconds || 0)
}

export function getUploadSpeedBytes(task) {
  const runtime = getUploadRuntime(task)
  return Number(runtime?.speed_bytes_per_sec || runtime?.last_non_zero_speed_bytes_per_sec || 0)
}

export function getTaskStatusLabel(taskOrStatus) {
  const task = typeof taskOrStatus === 'object' && taskOrStatus !== null ? taskOrStatus : null
  const status = task ? (task.display_status || task.status) : taskOrStatus
  const map = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    paused: '已暂停',
    waiting_manual: '等待处理',
    waiting_retry: '等待重试'
  }
  return map[String(status || '')] || String(status || '未知')
}

export function extractError(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

export function safeJsonParse(raw, fallback) {
  try {
    return JSON.parse(raw || '')
  } catch (_) {
    return fallback
  }
}

export function normalizePath(path) {
  return String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/g, '').toLowerCase()
}

export function commonAncestorPath(paths = []) {
  const normalized = paths.map(path => String(path || '').trim()).filter(Boolean)
  if (!normalized.length) return ''
  const splitPaths = normalized.map(path => path.replace(/\\/g, '/').split('/'))
  const first = splitPaths[0]
  const shared = []
  for (let index = 0; index < first.length; index += 1) {
    const segment = first[index]
    if (splitPaths.every(parts => parts[index] === segment)) shared.push(segment)
    else break
  }
  return shared.join('/').replace(/^([A-Za-z]:)$/, '$1/')
}

export function prioritizeChangedWorks(works, codes = []) {
  const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
  if (!normalized.length || !Array.isArray(works) || !works.length) return works
  const order = new Map(normalized.map((code, index) => [code, index]))
  return [...works].sort((left, right) => {
    const leftIndex = order.has(left?.canonical_rjcode) ? order.get(left.canonical_rjcode) : Number.POSITIVE_INFINITY
    const rightIndex = order.has(right?.canonical_rjcode) ? order.get(right.canonical_rjcode) : Number.POSITIVE_INFINITY
    return leftIndex - rightIndex
  })
}

export function jobStatusText(job) {
  if (job?.error_message === '用户取消' || job?.current_step === '已取消') return '已取消'
  if (job?.status === 'completed') return '已完成'
  if (job?.status === 'failed') return '失败'
  if (job?.status === 'processing') return '进行中'
  return '等待中'
}

export function getLocalUploadCircleNameForPath(sources, selectedPath, fallback) {
  const matchedSource = (sources || [])
    .filter(source => {
      const sourcePath = normalizePath(source?.path)
      const selected = normalizePath(selectedPath)
      return sourcePath && selected && (selected === sourcePath || selected.startsWith(`${sourcePath}/`))
    })
    .sort((left, right) => normalizePath(right?.path).length - normalizePath(left?.path).length)[0]
  return String(matchedSource?.circle_name || fallback || '').trim()
}
