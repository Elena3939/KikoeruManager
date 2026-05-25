import { formatBytes, formatDateTime } from '../../utils/format'

export const activeConflictStorageKey = 'kikoerumanager.conflicts.active'

export const filenameEncodingOptions = [
  { value: 'auto', label: '自动识别' },
  { value: 'shift_jis', label: 'Shift_JIS / CP932' },
  { value: 'gbk', label: 'GBK / CP936' },
  { value: 'big5', label: 'Big5 / CP950' },
  { value: 'euc_kr', label: 'EUC-KR / CP949' },
  { value: 'utf-8', label: 'UTF-8' }
]

export function resolveErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

export function getConflictId(conflict) {
  return conflict?.id || conflict?.conflict_id || ''
}

export function formatConflictLabel(conflict) {
  return conflict?.rjcode || conflict?.new_metadata?.work_name || conflict?.new_path || conflict?.source_path || '未识别问题项'
}

export function getConflictSourcePath(conflict) {
  return conflict?.context?.source?.resolved_path || conflict?.context?.source?.path || conflict?.new_path || conflict?.source_path || '-'
}

export function getExistingConflictPath(conflict) {
  return conflict?.context?.existing?.path || conflict?.existing_path || '-'
}

export function getConflictTypeLabel(type) {
  return {
    DUPLICATE: '完全重复',
    LANGUAGE_VARIANT: '多语言版本',
    MULTIPLE_VERSIONS: '多版本冲突',
    LINKED_WORK_ORIGINAL: '原作已入库',
    LINKED_WORK_TRANSLATION: '翻译版已入库',
    LINKED_WORK_CHILD: '子版本已入库',
    LINKED_WORK: '关联作品',
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败'
  }[String(type || '').toUpperCase()] || type || '未知冲突'
}

export function getConflictTypeDetail(conflict) {
  const type = String(conflict?.conflict_type || '').toUpperCase()
  const analysis = conflict?.analysis_info || {}
  const linked = Array.isArray(conflict?.linked_works_info) ? conflict.linked_works_info : []
  if (type === 'LINKED_WORK_ORIGINAL') return linked[0]?.rjcode ? `原作已入库（${linked[0].rjcode}）` : '原作已入库'
  if (type === 'LINKED_WORK_TRANSLATION') return linked[0]?.rjcode ? `翻译版已入库（${linked[0].rjcode}）` : '翻译版已入库'
  if (type === 'LINKED_WORK_CHILD') return linked[0]?.rjcode ? `子版本已入库（${linked[0].rjcode}）` : '子版本已入库'
  if (type === 'LINKED_WORK') {
    const sourceMode = String(analysis?.source_mode || '').toLowerCase()
    if (sourceMode.includes('existing_subtitle')) return '原作已含字幕，翻译版无需补配'
    if (linked.length === 1) {
      const work = linked[0]
      const wtype = String(work?.work_type || '').toLowerCase()
      const rj = work?.rjcode || ''
      if (wtype === 'original') return rj ? `原作已入库（${rj}）` : '原作已入库'
      if (wtype === 'translation' || wtype === 'child_translation') return rj ? `翻译版已入库（${rj}）` : '翻译版已入库'
      return rj ? `关联作品已入库（${rj}）` : '关联作品已入库'
    }
    if (linked.length > 1) return `已入库 ${linked.length} 个关联作品`
    return '关联作品已入库'
  }
  return getConflictTypeLabel(type)
}

export function isExtractFailed(conflict) {
  return conflict?.conflict_type === 'EXTRACT_FAILED'
}

export function isFailureConflict(conflict) {
  return ['EXTRACT_FAILED', 'PROCESS_FAILED'].includes(conflict?.conflict_type)
}

export function isPasswordFailureConflict(conflict) {
  const metadata = conflict?.new_metadata || {}
  const reason = String(metadata.extract_failure_reason || '').trim()
  const message = [metadata.error_message, metadata.resolution_error, conflict?.error_message].map(value => String(value || '')).join(' ')
  if (reason === 'wrong_password' || reason === 'missing_password') return true
  return /无正确密码|密码错误|密码不正确|wrong password|incorrect password|password required|missing password/i.test(message)
}

export function getGarbledMeta(conflict) {
  const metadata = conflict?.new_metadata || {}
  const sample = metadata.garbled_filename_sample || ''
  const topSamples = Array.isArray(metadata.garbled_filename_top_samples) ? metadata.garbled_filename_top_samples : []
  const reason = String(metadata.extract_failure_reason || '').trim()
  if (isPasswordFailureConflict(conflict)) return null
  if (reason !== 'garbled_filename') return null
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

export function canPreviewFilenames(conflict) {
  return isFailureConflict(conflict) && Boolean(getConflictId(conflict)) && Boolean(getGarbledMeta(conflict))
}

export function getConflictResolutionAction(conflict) {
  const metadata = conflict?.new_metadata || {}
  return String(metadata.resolution_action || metadata.conflict_resolution_action || '').trim().toUpperCase()
}

export function isConflictProcessing(conflict) {
  return String(conflict?.status || '').trim().toUpperCase() === 'PROCESSING'
}

export function isRetryConflict(conflict) {
  const metadata = conflict?.new_metadata || {}
  return getConflictResolutionAction(conflict) === 'RETRY' || Boolean(metadata.retry_from_conflicts || metadata.retry_conflict_id || metadata.retry_task_id)
}

export function isActiveRetryLinkedTask(conflict) {
  if (!isRetryConflict(conflict)) return false
  const status = String(conflict?.linked_task?.status || '').trim().toLowerCase()
  return ['pending', 'processing', 'paused', 'waiting_retry'].includes(status)
}

export function isKeepNewProcessing(conflict) {
  return isConflictProcessing(conflict) && getConflictResolutionAction(conflict) === 'KEEP_NEW'
}

export function isConflictRetrying(conflict, localRetryingIds = {}) {
  const id = getConflictId(conflict)
  if (!id) return false
  return Boolean(localRetryingIds[id] || (isConflictProcessing(conflict) && isRetryConflict(conflict)) || isActiveRetryLinkedTask(conflict))
}

export function shouldKeepLocalRetrying(conflict) {
  if (!conflict) return false
  const status = String(conflict.status || '').trim().toUpperCase()
  const linkedStatus = String(conflict.linked_task?.status || '').trim().toLowerCase()
  if (['completed', 'failed', 'cancelled', 'canceled'].includes(linkedStatus)) return false
  if (['pending', 'processing', 'paused', 'waiting_retry'].includes(linkedStatus)) return true
  return status === 'PROCESSING' && isRetryConflict(conflict)
}

export function getConflictRetryProgress(conflict) {
  const value = Number(conflict?.linked_task?.progress ?? conflict?.new_metadata?.resolution_progress ?? 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

export function getConflictStatusLabel(conflict, localRetryingIds = {}) {
  if (isConflictRetrying(conflict, localRetryingIds)) return '重试中'
  if (isKeepNewProcessing(conflict)) return '保留新版中'
  if (isConflictProcessing(conflict)) return '处理中'
  return '待处理'
}

export function conflictCanUseAction(conflict, action) {
  const actions = Array.isArray(conflict?.available_actions) ? conflict.available_actions : []
  if (actions.length) return actions.includes(action)
  if (action === 'SKIP') return true
  if (action === 'RETRY') return isFailureConflict(conflict)
  if (action === 'RENAME_VOLUMES') return Boolean(conflict?.new_metadata?.disguised_volume_set?.suspect_files?.length)
  if (action === 'KEEP_NEW' || action === 'MERGE') return !isFailureConflict(conflict)
  return false
}

export function formatConflictDate(value) {
  return formatDateTime(value)
}

export function formatConflictSize(value, statsBackfilling = false) {
  if (value != null) return formatBytes(value)
  return statsBackfilling ? '统计中...' : '-'
}

export function formatConflictTimestamp(value, statsBackfilling = false) {
  if (value != null) return formatDateTime(new Date(Number(value) * 1000).toISOString())
  return statsBackfilling ? '统计中...' : '-'
}

export function textDecoderEncoding(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (['932', 'cp932', 'shift_jis', 'shift-jis', 'sjis'].includes(normalized)) return 'shift_jis'
  if (['936', 'cp936', 'gbk', 'gb2312'].includes(normalized)) return 'gbk'
  if (['950', 'cp950', 'big5'].includes(normalized)) return 'big5'
  if (['949', 'cp949', 'euc_kr', 'euc-kr'].includes(normalized)) return 'euc-kr'
  if (['utf8', 'utf-8'].includes(normalized)) return 'utf-8'
  return 'shift_jis'
}

export function escapedSurrogateBytes(value) {
  const text = String(value || '')
  const bytes = []
  let matched = false
  for (let index = 0; index < text.length;) {
    const literal = text.slice(index, index + 6)
    const literalMatch = /^\\udc([0-9a-fA-F]{2})$/.exec(literal)
    if (literalMatch) {
      bytes.push(parseInt(literalMatch[1], 16))
      matched = true
      index += 6
      continue
    }
    const code = text.charCodeAt(index)
    if (code >= 0xdc80 && code <= 0xdcff) {
      bytes.push(code - 0xdc00)
      matched = true
      index += 1
      continue
    }
    if (code <= 0xff) {
      bytes.push(code)
      index += 1
      continue
    }
    const encoded = new TextEncoder().encode(text[index])
    bytes.push(...encoded)
    index += 1
  }
  return matched ? new Uint8Array(bytes) : null
}

export function formatPreviewName(value, encoding) {
  const raw = String(value || '')
  const bytes = escapedSurrogateBytes(raw)
  if (!bytes) return raw
  try {
    return new TextDecoder(textDecoderEncoding(encoding), { fatal: false }).decode(bytes) || raw
  } catch {
    return raw
  }
}

export function getFilenamePreviewRows(preview, encoding) {
  const diagList = Array.isArray(preview?.diagnostics) ? preview.diagnostics : []
  if (diagList.length) {
    return diagList.slice(0, 80).map(item => ({ ...item, displayName: formatPreviewName(item.name, encoding) }))
  }
  return (preview?.items || []).slice(0, 80).map(item => ({
    name: item.name || '',
    displayName: formatPreviewName(item.name || '', encoding),
    score: 0,
    garbled: false
  }))
}

export function buildPathPreview(paths) {
  const lines = paths.slice(0, 5)
  if (paths.length > lines.length) lines.push(`以及另外 ${paths.length - lines.length} 项`)
  return lines.join('\n')
}
