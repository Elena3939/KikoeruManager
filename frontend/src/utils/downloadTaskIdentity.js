export function getAsmrDownloadSessionId(task) {
  const metadata = task?.task_metadata || {}
  // 引擎会给 HTTP 任务填 session_id，但它不对应 ASMR 下载会话。
  if (metadata.resource_source === 'imoutoheaven' || String(task?.type || metadata.task_kind || '') === 'http_download') return ''
  return String(metadata.session_id || task?.session_id || '').trim()
}

export function getDownloadEngineTaskId(task) {
  return String(task?.active_task_id || task?.id || '').trim()
}
