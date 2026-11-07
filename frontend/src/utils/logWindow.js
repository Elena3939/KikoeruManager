// 文件字节位置是记录身份；同一记录补写 traceback 时原位更新。
export function mergeLogWindow(current, incoming, { limit, following, prepend = false, anchorKey, endKey } = {}) {
  const rows = current.slice()
  const positions = new Map(rows.map((row, index) => [row.key, index]))
  const added = []
  for (const row of incoming) {
    const index = positions.get(row.key)
    if (index === undefined) {
      positions.set(row.key, rows.length + added.length)
      added.push(row)
    } else if (index < rows.length) {
      if (rows[index].rawLine !== row.rawLine) rows[index] = row
    } else added[index - rows.length] = row
  }
  const merged = prepend ? [...added, ...rows] : [...rows, ...added]
  const cap = following ? limit : Math.floor(limit * 1.5)
  const removed = Math.max(0, merged.length - cap)
  let start = following ? removed : 0
  if (!following && removed && anchorKey !== undefined) {
    const anchor = merged.findIndex((row) => row.key === anchorKey)
    const end = merged.findIndex((row) => row.key === endKey)
    // 连续窗口围绕可见区域裁剪，始终保住当前首尾可见记录。
    if (anchor >= 0) {
      const middle = (anchor + Math.max(anchor, end)) / 2
      start = Math.min(removed, Math.max(0, Math.round(middle - cap / 2)))
      start = Math.min(start, anchor)
      if (end >= 0) start = Math.max(start, end - cap + 1)
    }
  }
  return {
    rows: merged.slice(start, start + cap),
    added: added.length,
    tailGap: !following && start + cap < merged.length,
  }
}

// 只有筛选条件或记录对象变化才重新判断；计时器不参与日志依赖。
export function createLogFilter() {
  let signature = ''
  let matches = new WeakMap()
  return (rows, options) => {
    const next = JSON.stringify(options)
    if (next !== signature) {
      signature = next
      matches = new WeakMap()
    }
    const levels = new Set(options.levels)
    const modules = new Set(options.modules)
    return rows.filter((row) => {
      if (!matches.has(row)) matches.set(row,
        levels.has(row.level) && (!modules.size || modules.has(row.module)) &&
        options.terms.every((term) => row.searchText.includes(term)))
      return matches.get(row)
    })
  }
}
