export function aggregateConflictRjcodes(conflict) {
  const metadata = conflict?.new_metadata || {}
  if (!metadata.aggregate_archive || metadata.rjcode_lock || !Array.isArray(metadata.aggregate_rjcodes)) return []
  const codes = [...new Set(metadata.aggregate_rjcodes.map(code => String(code).trim().toUpperCase()))]
    .filter(code => /^[RVB]J(?:\d{8}|\d{6})$/.test(code))
  return codes.length >= 2 ? codes : []
}

export function formatConflictLabel(conflict) {
  const codes = aggregateConflictRjcodes(conflict)
  if (codes.length) {
    const name = String(conflict?.new_path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '合集压缩包'
    return `${name}（${codes.length} 个作品）`
  }
  return conflict?.rjcode || conflict?.new_metadata?.work_name || conflict?.new_path || '未识别问题项'
}
