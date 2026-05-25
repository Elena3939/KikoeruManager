export const PAGE_SIZES = [20, 50, 100, 200, 500]

export const sortOptions = [
  { value: 'name', label: '名称' },
  { value: 'size', label: '大小' },
  { value: 'mtime', label: '修改时间' }
]

export const searchKindOptions = [
  { value: 'all', label: '全部' },
  { value: 'folder', label: '目录' },
  { value: 'file', label: '文件' }
]

export const scopeOptions = [
  { value: 'global', label: '全库' },
  { value: 'current', label: '当前目录' }
]

export const libraryFilterOptions = [
  { value: 'all', label: '全部' },
  { value: 'dir', label: '文件夹' },
  { value: 'file', label: '文件' },
  { value: 'audio', label: '音频' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'archive', label: '压缩包' },
  { value: 'text', label: '文档/字幕' }
]

const AUDIO_LOSSLESS_RE = /\.(wav|flac)$/i
const AUDIO_RE = /\.(mp3|m4a|ogg|aac|wma|opus|cue)$/i
const IMAGE_RE = /\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i
const VIDEO_RE = /\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i
const PDF_RE = /\.pdf$/i
const ARCHIVE_RE = /\.(zip|7z|rar|tar|gz|bz2|xz)$/i
const TEXT_RE = /\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i

export function itemName(item) {
  return item?.name || String(item?.path || '').split(/[\\/]/).filter(Boolean).pop() || item?.path || '-'
}

export function isDirectory(item) {
  if (!item) return false
  if (item.is_directory === true || item.is_dir === true) return true
  const type = String(item.type || item.entry_type || '').toLowerCase()
  return type === 'dir' || type === 'directory'
}

export function rowKey(item) {
  return item?.path || item?.id || item?.name
}

export function normalizePath(path = '') {
  return String(path || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '')
}

export function parentPath(path = '') {
  const parts = normalizePath(path).split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

export function buildBreadcrumb(path = '') {
  const parts = normalizePath(path).split('/').filter(Boolean)
  const crumbs = [{ label: '根目录', path: '' }]
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    crumbs.push({ label: part, path: acc })
  }
  return crumbs
}

export function statusLabel(status) {
  if (status === 'syncing') return '正在同步'
  if (status === 'ready') return '索引就绪'
  if (status === 'error') return '索引出错'
  return '索引未建'
}

export function extractRJCode(value) {
  const text = String(value || '').toUpperCase()
  const match = text.match(/[RVB]J\s*(\d{6,8})(?!\d)/i)
  return match ? `RJ${match[1]}` : ''
}

export function classifyLibraryEntryKind(item) {
  if (!item) return 'file'
  if (isDirectory(item)) return 'dir'
  const raw = String(item.name || item.label || item.relative_path || item.path || '').toLowerCase()
  if (AUDIO_LOSSLESS_RE.test(raw)) return 'audio-lossless'
  if (AUDIO_RE.test(raw)) return 'audio'
  if (IMAGE_RE.test(raw)) return 'image'
  if (VIDEO_RE.test(raw)) return 'video'
  if (PDF_RE.test(raw)) return 'pdf'
  if (ARCHIVE_RE.test(raw)) return 'archive'
  if (TEXT_RE.test(raw)) return 'text'
  return 'file'
}

export function libraryEntryClass(item) {
  return `icon-${classifyLibraryEntryKind(item)}`
}

export function libraryEntryLabel(item) {
  const kind = classifyLibraryEntryKind(item)
  const labels = {
    dir: '文件夹',
    'audio-lossless': '无损音频',
    audio: '音频',
    image: '图片',
    video: '视频',
    pdf: 'PDF',
    archive: '压缩包',
    text: '文档/字幕',
    file: '文件'
  }
  return labels[kind] || '文件'
}

export const VIEWABLE_LIBRARY_KINDS = new Set(['image', 'video', 'pdf', 'text'])

export function canViewLibraryRow(row) {
  return Boolean(row && !isDirectory(row) && VIEWABLE_LIBRARY_KINDS.has(classifyLibraryEntryKind(row)))
}

export function formatLibraryRowSize(row, formatBytes) {
  if (isDirectory(row) && row?.size_status !== 'ready' && (row?.size === null || row?.size === undefined)) return '-'
  if (row?.size_status === 'pending' && (row.size === null || row.size === undefined)) return '统计中'
  if (row?.size_status === 'stale' && row.size !== null && row.size !== undefined) return `${formatBytes(row.size)} *`
  return formatBytes(row?.size)
}

export function canApiRenameRow(row) {
  if (!isDirectory(row)) return false
  const detectedRJ = String(row?.rjcode || extractRJCode(row?.path || row?.name) || '').trim()
  return Boolean(detectedRJ)
}

export function libraryFilterToEntryType(filter) {
  if (filter === 'dir' || filter === 'folder') return 'dir'
  if (filter && filter !== 'all') return 'file'
  return 'all'
}

export function applyLibraryFrontendFilter(items, { filter = 'all', keyword = '', matchedRjcode = '' } = {}) {
  const normalizedFilter = String(filter || 'all')
  const normalizedKeyword = String(keyword || '').trim().toLowerCase()
  const normalizedRj = String(matchedRjcode || '').trim().toUpperCase()
  return (Array.isArray(items) ? items : []).filter(item => {
    const kind = classifyLibraryEntryKind({
      ...item,
      is_directory: item?.is_directory ?? item?.entry_type === 'dir'
    })
    if (normalizedFilter === 'dir' || normalizedFilter === 'folder') {
      if (kind !== 'dir') return false
    } else if (normalizedFilter === 'file') {
      if (kind === 'dir') return false
    } else if (normalizedFilter !== 'all') {
      if (normalizedFilter === 'audio') {
        if (kind !== 'audio' && kind !== 'audio-lossless') return false
      } else if (kind !== normalizedFilter) {
        return false
      }
    }

    if (!normalizedKeyword || String(item?.rjcode || '').toUpperCase() === normalizedRj) return true
    const name = String(item?.name || itemName(item)).toLowerCase()
    const relative = String(item?.relative_path || '').toLowerCase()
    const parent = String(item?.parent_path || '').toLowerCase()
    return name.includes(normalizedKeyword) || relative.includes(normalizedKeyword) || parent.includes(normalizedKeyword)
  })
}

export function normalizeIndexEntryPath(entry) {
  return normalizePath(entry?.absolute_path || entry?.path || entry?.relative_path || '')
}

export function isIndexEntryDirectory(entry) {
  if (!entry) return false
  if (entry.entry_type) return String(entry.entry_type) !== 'file'
  return isDirectory(entry)
}
