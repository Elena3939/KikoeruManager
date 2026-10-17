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
