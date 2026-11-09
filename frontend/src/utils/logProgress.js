export const TASK_PROGRESS_PREFIX = '__KIKOERUMANAGER_TASK_PROGRESS__'

const phaseLabels = {
  extract: '解压', move: '移动', filter: '过滤', metadata: '元数据', rename: '重命名',
  asmr_sync_download: '下载', http_download: '下载', baidu_netdisk_download: '下载',
  baidu_netdisk_upload: '上传', local_library_upload: '上传', browser_upload: '上传',
  rj_subtitle_fetch: '字幕', rj_subtitle_extract: '字幕', auto_process: '处理',
  process_existing_folder: '处理', library_folder_completion_preview: '库存补全',
  circle_completion_index: '社团补全', circle_completion_refresh_selected: '社团补全',
  circle_completion_download_batch: '下载', circle_completion_bonus_probe: '特典探测',
  bonus_probe: '特典探测', download: '下载', upload: '上传', library_upload: '入库上传',
  downloaded: '下载完成', download_reused: '复用下载', ready_for_upload: '等待上传',
  waiting_upload_turn: '等待上传', refresh_download_link: '刷新下载链接',
  download_failed: '下载失败', upload_failed: '上传失败', verify: '校验',
  pending: '等待', queued: '排队', receiving: '接收', completed: '完成',
}

export function resolveLogTaskPhase(phase, taskType = '') {
  const value = String(phase || taskType || '处理').trim()
  return phaseLabels[value] || value.replaceAll('_', ' ')
}

const statusTones = {
  pending: 'waiting',
  processing: 'processing',
  paused: 'paused',
  waiting_manual: 'waiting',
  waiting_retry: 'waiting',
  completed: 'success',
  failed: 'error',
  partial_failed: 'error',
  cancelled: 'paused',
}

export function parseTaskProgressPayload(message) {
  message = String(message || '').replace(/^\[task=[^\]]+\]\s*/, '')
  if (!String(message || '').startsWith(TASK_PROGRESS_PREFIX)) return null
  try {
    const payload = JSON.parse(message.slice(TASK_PROGRESS_PREFIX.length))
    if (![1, 2].includes(payload?.version) || !payload.task_id || !Object.hasOwn(statusTones, payload.status)) return null
    if (typeof payload.progress !== 'number' || !Number.isFinite(payload.progress)) return null
    return payload
  } catch {
    return null
  }
}

export function buildTaskProgress(log, order = 0) {
  const payload = log?.taskProgressPayload
  if (!payload) return null
  const phase = resolveLogTaskPhase(payload.phase, payload.task_type)
  return {
    id: payload.task_id,
    taskId: payload.task_id,
    shortId: payload.task_id.slice(0, 8),
    status: payload.status,
    rjcode: payload.rjcode || '',
    archiveLabel: payload.source_label || '',
    title: [phase, payload.rjcode || payload.source_label].filter(Boolean).join(' '),
    phase,
    detail: payload.step || '',
    progress: Math.max(0, Math.min(100, payload.progress)),
    tone: statusTones[payload.status],
    active: payload.status === 'processing',
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
    speedBytesPerSec: Number(payload.speed_bytes_per_sec || 0),
    downloadedBytes: Number(payload.downloaded_bytes || 0),
    totalBytes: Number(payload.total_bytes || 0),
    fileIndex: Number(payload.file_index || 0),
    fileCount: Number(payload.file_count || 0),
    retryCount: Number(payload.retry_count || 0),
    failureReason: payload.failure_reason || '',
    elapsedSeconds: Number(payload.elapsed_seconds || 0),
    order,
  }
}
