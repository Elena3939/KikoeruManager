export function cx(...parts) {
  return parts.flat().filter(Boolean).join(' ')
}

export function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let next = bytes
  let index = 0
  while (next >= 1024 && index < units.length - 1) {
    next /= 1024
    index += 1
  }
  return `${next.toFixed(next >= 10 || index === 0 ? 0 : 1)} ${units[index]}`
}

export function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export function normalizeListPayload(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.tasks)) return payload.tasks
  if (Array.isArray(payload?.data)) return payload.data
  if (Array.isArray(payload?.results)) return payload.results
  return []
}
