const PIKPAK_HOSTS = new Set(['mypikpak.com', 'www.mypikpak.com', 'drive.mypikpak.com'])
const PIKPAK_URL_PATTERN = /https?:\/\/(?:www\.|drive\.)?mypikpak\.com\/[^\s<>'"）)]+/i
const PASS_CODE_QUERY_KEYS = ['pwd', 'pass_code', 'passcode', 'password', 'code']

export function pikPakPassCodeFromText(value) {
  const match = String(value || '').trim().match(
    /(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})\s*$/i,
  )
  return match ? match[1].trim() : ''
}

export function normalizePikPakShareText(value) {
  const text = String(value || '').trim()
  const match = text.match(PIKPAK_URL_PATTERN)
  if (!match) return ''
  const shareUrl = match[0].replace(/[.,，。;；]+$/g, '')
  const suffix = text.slice((match.index || 0) + match[0].length)
  return appendPikPakPassCode(shareUrl, pikPakPassCodeFromText(suffix))
}

export function pikPakShareIdentity(value) {
  const shareUrl = normalizePikPakShareText(value)
  if (!shareUrl) return ''
  try {
    const parsed = new URL(shareUrl)
    if (!PIKPAK_HOSTS.has(parsed.hostname.toLowerCase())) return ''
    return `${parsed.hostname.toLowerCase()}${parsed.pathname.replace(/\/+$/g, '')}`
  } catch {
    return ''
  }
}

export function isPikPakPassCodeLine(value) {
  const text = String(value || '').trim()
  return Boolean(text && !normalizePikPakShareText(text) && pikPakPassCodeFromText(text))
}

export function normalizeHttpDownloadInputRows(rows) {
  const result = []
  let lastPikPakIndex = null
  for (const row of rows || []) {
    const value = String(row || '').trim()
    if (!value) continue
    const pikPakShare = normalizePikPakShareText(value)
    if (pikPakShare) {
      result.push(pikPakShare)
      lastPikPakIndex = result.length - 1
      continue
    }
    const passCode = lastPikPakIndex === null ? '' : pikPakPassCodeFromText(value)
    if (passCode) {
      result[lastPikPakIndex] = appendPikPakPassCode(result[lastPikPakIndex], passCode)
      continue
    }
    result.push(value)
    lastPikPakIndex = null
  }
  return [...new Set(result)]
}

function pikPakShareHasCode(value) {
  try {
    const parsed = new URL(String(value || '').trim())
    if (PASS_CODE_QUERY_KEYS.some(key => parsed.searchParams.has(key))) return true
    return /(?:pwd|pass_code|passcode|password|code)[=:：]|(?:提取码|访问码|密[码碼])[:：\s]/i.test(
      decodeURIComponent(parsed.hash || ''),
    )
  } catch {
    return false
  }
}

function appendPikPakPassCode(shareUrl, code) {
  const normalizedUrl = String(shareUrl || '').trim()
  const normalizedCode = String(code || '').trim()
  if (!normalizedUrl || !normalizedCode || pikPakShareHasCode(normalizedUrl)) return normalizedUrl
  try {
    const parsed = new URL(normalizedUrl)
    parsed.searchParams.set('pwd', normalizedCode)
    return parsed.toString()
  } catch {
    return normalizedUrl
  }
}
