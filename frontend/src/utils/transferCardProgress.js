import { formatDownloadEta, formatDownloadCompletion } from './downloadProgress.js'

const number = value => Math.max(0, Number(value) || 0)
const status = task => String(task?.display_status || task?.status || '')
const size = bytes => {
  const value = number(bytes)
  const unit = value > 0 ? Math.min(3, Math.floor(Math.log(value) / Math.log(1024))) : 0
  return `${(value / 1024 ** unit).toFixed(2)} ${['B', 'KB', 'MB', 'GB'][unit]}`
}

export function getTransferRuntime(task, mode) {
  return task?.[`${mode}_runtime`] || task?.performance_metrics?.[`${mode}_runtime`]
    || task?.task_metadata?.performance_metrics?.[`${mode}_runtime`] || {}
}

export function getTransferCardProgress(tasks = [], mode = 'download', now = Date.now()) {
  const rows = tasks.map(task => {
    const runtime = getTransferRuntime(task, mode)
    const files = task?.[`${mode}_files`] || []
    const total = number(runtime.total_bytes) || files.reduce((sum, file) => sum + number(file.size_bytes || file.size || file.total), 0)
      || number(task?.task_metadata?.total_bytes || task?.total_bytes)
    const completed = status(task) === 'completed'
    const transferred = completed ? total : number(runtime.transferred_bytes ?? files.reduce((sum, file) => sum
      + (file.status === 'completed' ? number(file.size_bytes || file.size || file.total) : number(mode === 'upload' ? file.uploaded : file.downloaded)), 0))
    const active = status(task) === 'processing' && !['verifying', 'completed', 'paused'].includes(runtime.phase)
    return { total, transferred: total ? Math.min(total, transferred) : transferred, completed,
      fraction: completed ? 1 : total ? Math.min(1, transferred / total) : Math.min(1, number(task.progress) / 100),
      speed: active ? number(runtime.speed_bytes_per_sec) : 0 }
  })
  const total = rows.reduce((sum, row) => sum + row.total, 0)
  const transferred = rows.reduce((sum, row) => sum + row.transferred, 0)
  const speed = rows.reduce((sum, row) => sum + row.speed, 0)
  const completed = rows.length > 0 && rows.every(row => row.completed)
  const known = rows.length > 0 && rows.every(row => row.total > 0)
  const fraction = known ? transferred / total : rows.reduce((sum, row) => sum + row.fraction, 0) / (rows.length || 1)
  const percentage = completed ? 100 : Math.min(99, Math.floor(fraction * 100))
  const remaining = Math.max(0, total - transferred)
  const eta = known && speed > 0 && remaining > 0 ? Math.ceil(remaining / speed) : null
  const states = tasks.map(status)
  const stateText = completed ? '已完成' : states.every(state => state === 'paused') && states.length ? '已暂停，恢复后估算时间'
    : !states.includes('processing') && states.some(state => ['failed', 'partial_failed'].includes(state)) ? '需要处理，处理后估算时间'
      : states.length && states.every(state => ['cancelled', 'canceled'].includes(state)) ? '已取消'
        : tasks.some(task => getTransferRuntime(task, mode).phase === 'verifying') && speed === 0 ? '正在确认远端文件' : ''
  return {
    percentage, completed,
    metaText: `${mode === 'upload' ? '上传' : '下载'} ${size(transferred)} / ${known ? size(total) : '统计中'} · 速度 ${size(speed)}/s · 剩余 ${known ? size(remaining) : '统计中'}`,
    timingText: stateText || `预计剩余：${formatDownloadEta(eta)} · 预计完成：${formatDownloadCompletion(eta ? now + eta * 1000 : null)}`
  }
}
