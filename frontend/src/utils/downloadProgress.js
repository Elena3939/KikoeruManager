function nonNegativeNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : 0
}

function getDownloadProgress(task) {
  const runtime = task?.download_runtime
    || task?.performance_metrics?.download_runtime
    || task?.task_metadata?.performance_metrics?.download_runtime
    || {}
  const files = Array.isArray(task?.download_files) ? task.download_files : []
  const fileTotal = files.reduce((sum, file) => (
    sum + nonNegativeNumber(file?.size_bytes || file?.size || file?.total)
  ), 0)
  const total = nonNegativeNumber(runtime.total_bytes) || fileTotal
  const fileTransferred = files.reduce((sum, file) => {
    const size = nonNegativeNumber(file?.size_bytes || file?.size || file?.total)
    return sum + (file?.status === 'completed' ? size : nonNegativeNumber(file?.downloaded))
  }, 0)
  const completed = String(task?.display_status || task?.status || '') === 'completed'
  const transferred = completed ? total : nonNegativeNumber(runtime.transferred_bytes ?? fileTransferred)
  const fraction = completed ? 1 : total > 0
    ? Math.min(1, transferred / total)
    : Math.min(1, nonNegativeNumber(task?.progress) / 100)
  return { total, fraction, completed }
}

export function getDownloadBatchPercent(tasks = []) {
  if (!tasks.length) return 0
  const progress = tasks.map(getDownloadProgress)
  if (progress.every(item => item.completed)) return 100
  const total = progress.reduce((sum, item) => sum + item.total, 0)
  // 总大小尚未解析时，每项都参与计算，避免未知大小的等待任务被当作已完成。
  const fraction = total > 0 && progress.every(item => item.total > 0)
    ? progress.reduce((sum, item) => sum + item.total * item.fraction, 0) / total
    : progress.reduce((sum, item) => sum + item.fraction, 0) / progress.length
  return Math.max(0, Math.min(99, Math.floor(fraction * 100)))
}

export function getMatchingDownloadSummary(summary, tasks = []) {
  if (!summary || !Array.isArray(summary.task_ids)) return null
  const ids = new Set(tasks.map(task => String(task.id)))
  return ids.size === summary.task_ids.length && summary.task_ids.every(id => ids.has(String(id)))
    ? summary : null
}

export function formatDownloadEta(seconds) {
  if (!(Number(seconds) > 0)) return '计算中'
  const value = Math.ceil(Number(seconds))
  if (value < 60) return `${value} 秒`
  if (value < 3600) return `${Math.floor(value / 60)} 分 ${value % 60} 秒`
  if (value < 86400) return `${Math.floor(value / 3600)} 小时 ${Math.floor(value % 3600 / 60)} 分`
  return `${Math.floor(value / 86400)} 天 ${Math.floor(value % 86400 / 3600)} 小时`
}

export function formatDownloadCompletion(value) {
  const date = value ? new Date(value) : null
  return date && Number.isFinite(date.getTime())
    ? date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '计算中'
}

export function formatDownloadSummary(summary) {
  if (!summary) return { metaText: '', timingText: '' }
  const speed = nonNegativeNumber(summary.speed_bytes_per_sec)
  const unit = speed > 0 ? Math.min(3, Math.max(0, Math.floor(Math.log(speed) / Math.log(1024)))) : 0
  const speedText = `${(speed / 1024 ** unit).toFixed(2)} ${['B', 'KB', 'MB', 'GB'][unit]}/s`
  const state = { completed: '已完成', paused: '已暂停，恢复后估算时间', needs_attention: '需要处理，处理后估算时间', cancelled: '已取消' }[summary.eta_status]
  return {
    metaText: `总进度: ${summary.progress_percent}% · 当前速度: ${speedText}`,
    timingText: state || `预计剩余：${formatDownloadEta(summary.eta_seconds)} · 预计完成：${formatDownloadCompletion(summary.estimated_completion_at)}`,
  }
}
