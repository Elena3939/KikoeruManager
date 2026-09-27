const METRIC_UNIT_PATTERN = /^[A-Za-z%]+(?:\/[A-Za-z%]+)?$/

export function splitActivityMetric(value) {
  const text = String(value ?? '').trim()
  if (!text) return { num: '—', unit: '' }

  const parts = text.split(/\s+/, 2)
  if (parts.length === 2 && METRIC_UNIT_PATTERN.test(parts[1])) {
    return { num: parts[0], unit: parts[1] }
  }

  return { num: text, unit: '' }
}
