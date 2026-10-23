// 兼容已有 PROCESS_FAILED 记录，以业务来源区分 API 重命名与导入失败。
export function isApiRenameConflict(conflict) {
  return conflict?.new_metadata?.source_operation === 'api_rename'
}

export function passwordRetryTargets(conflicts) {
  return conflicts.filter(conflict => !isApiRenameConflict(conflict))
}

export async function requestRetryInput(conflict, askPassword) {
  return isApiRenameConflict(conflict) ? {} : askPassword(conflict)
}

export function buildConflictRetryPayload(conflict, input = {}) {
  if (isApiRenameConflict(conflict)) return {}
  const payload = {}
  const passwords = Array.isArray(input.passwords)
    ? input.passwords.filter(Boolean)
    : [String(input.password || '').trim()].filter(Boolean)
  if (passwords.length) {
    payload.passwords = passwords
    payload.password = passwords[0]
  }
  const encoding = String(input.filenameEncoding || '').trim()
  if (encoding && encoding !== 'auto') payload.filename_encoding = encoding
  if (input.ignoreGarbled) payload.ignore_garbled = true
  return payload
}
