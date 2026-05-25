import {
  Activity,
  Archive,
  Captions,
  Database,
  FileArchive,
  Sparkles,
  Upload,
  UploadCloud
} from 'lucide-react'
import { formatBytes, formatDateTime } from '../../utils/format'
import { getDomainMeta } from '../tasks/taskUtils'

export const archiveDomainOrder = ['import', 'subtitle_import', 'rj_subtitle', 'asmr_sync', 'upload', 'circle_completion', 'system']

export const archiveDomainMeta = {
  all: { key: 'all', label: '全部', icon: Archive, tone: 'slate' },
  import: { key: 'import', label: '解压入库', icon: FileArchive, tone: 'amber' },
  subtitle_import: { key: 'subtitle_import', label: '字幕补配', icon: Sparkles, tone: 'violet' },
  rj_subtitle: { key: 'rj_subtitle', label: 'RJ 字幕', icon: Captions, tone: 'sky' },
  asmr_sync: { key: 'asmr_sync', label: 'ASMR', icon: UploadCloud, tone: 'green' },
  upload: { key: 'upload', label: '库存上传', icon: Upload, tone: 'blue' },
  circle_completion: { key: 'circle_completion', label: '社团补全', icon: Database, tone: 'teal' },
  system: { key: 'system', label: '系统', icon: Activity, tone: 'slate' }
}

export function formatRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const match = text.match(/[RVB]J\s*(\d{4,})/i)
  return match ? `RJ${match[1]}` : text
}

export function formatArchiveDate(value) {
  if (!value) return '-'
  return formatDateTime(String(value).replace(' ', 'T'))
}

export function formatArchiveSize(value) {
  const size = Number(value || 0)
  return size > 0 ? formatBytes(size) : '-'
}

export function getArchiveTaskMeta(item) {
  const domain = String(item?.task_domain || item?.domain || item?.task_kind || item?.kind || 'import')
    .trim()
    .toLowerCase()
  const key = archiveDomainOrder.includes(domain) ? domain : 'import'
  const fallback = getDomainMeta(key)
  return {
    ...archiveDomainMeta[key],
    label: archiveDomainMeta[key]?.label || fallback.label,
    icon: archiveDomainMeta[key]?.icon || fallback.icon,
    tone: archiveDomainMeta[key]?.tone || fallback.tone || 'slate'
  }
}

export function getArchiveStatusMeta(status) {
  const normalized = String(status || '').trim().toLowerCase()
  if (['completed', 'success', 'finished'].includes(normalized)) return { key: 'completed', label: '已完成', tone: 'success' }
  if (['failed', 'error'].includes(normalized)) return { key: 'failed', label: '失败', tone: 'danger' }
  if (['processing', 'running'].includes(normalized)) return { key: 'processing', label: '处理中', tone: 'info' }
  if (['pending', 'waiting', 'queued'].includes(normalized)) return { key: 'pending', label: '待处理', tone: 'warning' }
  return { key: 'unknown', label: normalized || '状态未知', tone: 'muted' }
}

export function groupProcessedArchives(archives = []) {
  const groups = new Map()
  const singles = []
  for (const archive of archives) {
    const filename = String(archive.filename || '')
    const volumeMatch = filename.match(/^(.*)\.part(\d+)\.(rar|zip|7z|exe)$/i)
    if (!volumeMatch) {
      singles.push({ ...archive, source: 'processed_archive', isVolumeGroup: false })
      continue
    }

    const baseName = volumeMatch[1]
    const groupKey = `${baseName}_volume_group`
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        id: archive.id,
        rjcode: archive.rjcode,
        filename: `${baseName}（分卷组）`,
        file_size: 0,
        process_count: archive.process_count || 1,
        processed_at: archive.processed_at || new Date(0).toISOString(),
        status: archive.status,
        isVolumeGroup: true,
        volumes: [],
        source: 'processed_archive'
      })
    }
    const group = groups.get(groupKey)
    group.volumes.push(archive)
    group.file_size += Number(archive.file_size || 0)
    if (filename.toLowerCase().includes('.part1.')) group.id = archive.id
    if (new Date(archive.processed_at || 0).getTime() > new Date(group.processed_at || 0).getTime()) {
      group.processed_at = archive.processed_at
      group.status = archive.status || group.status
    }
  }
  return [...groups.values(), ...singles]
}

export function buildTaskArchiveItems(overview) {
  const recent = Array.isArray(overview?.recent_items) ? overview.recent_items : []
  const active = Array.isArray(overview?.active_items) ? overview.active_items : []
  return [...active, ...recent]
    .filter((task, index, list) => list.findIndex(item => item.id === task.id) === index)
    .map(task => {
      const domain = String(task.domain || 'system').trim()
      const title = String(task.title || task.subtitle || task.id || '未命名任务').trim()
      return {
        id: `task-${task.id}`,
        source: 'task_center',
        filename: title,
        rjcode: formatRJ(task.rjcode),
        status: task.status,
        task_domain: domain,
        domain,
        task_kind: task.kind || task.type || '',
        processed_at: task.completed_at || task.updated_at || task.started_at || task.created_at,
        file_size: 0,
        summary: task.subtitle || task.current_step || '',
        route_hint: task.route_hint
      }
    })
}

export function buildDisplayedArchives(archives, overview) {
  const processed = groupProcessedArchives(archives)
  const taskItems = buildTaskArchiveItems(overview).filter(item => item.task_domain !== 'import')
  return [...taskItems, ...processed].sort((a, b) => new Date(b.processed_at || 0).getTime() - new Date(a.processed_at || 0).getTime())
}

export function buildArchiveTabs(items) {
  const counts = new Map()
  for (const item of items) {
    const key = getArchiveTaskMeta(item).key
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  const tabs = [{ ...archiveDomainMeta.all, count: items.length }]
  for (const key of archiveDomainOrder) {
    const count = counts.get(key) || 0
    if (count > 0) tabs.push({ ...archiveDomainMeta[key], count })
  }
  return tabs
}

export function filterArchives(items, searchQuery, domainFilter) {
  const keyword = String(searchQuery || '').trim().toLowerCase()
  const searched = keyword
    ? items.filter(item => [item.filename, item.rjcode, item.summary, item.task_domain, item.domain].join(' ').toLowerCase().includes(keyword))
    : items
  if (!domainFilter || domainFilter === 'all') return searched
  return searched.filter(item => getArchiveTaskMeta(item).key === domainFilter)
}
