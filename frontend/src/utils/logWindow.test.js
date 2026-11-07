import { describe, expect, it } from 'vitest'
import { createLogFilter, mergeLogWindow } from './logWindow'

const rows = (start, count) => Array.from({ length: count }, (_, index) => ({
  key: `app.log:${start + index}`, rawLine: `line ${start + index}`,
  level: 'INFO', module: 'worker', searchText: `line ${start + index}`,
}))

describe('逻辑日志窗口', () => {
  it('跟随时从头裁剪，续写记录按字节位置原位更新', () => {
    const current = rows(0, 5)
    const merged = mergeLogWindow(current, [...rows(4, 3), { ...current[4], rawLine: '续写 traceback' }], { limit: 5, following: true })
    expect(merged.rows.map(row => row.key)).toEqual(rows(2, 5).map(row => row.key))
    expect(merged.rows[2].rawLine).toBe('续写 traceback')
    expect(merged.rows[0]).toBe(current[2])
    expect(merged.tailGap).toBe(false)
  })

  it('阅读窗口保住可见首尾，丢掉远端新日志并记下缺口', () => {
    const merged = mergeLogWindow(rows(0, 2000), rows(2000, 2000), {
      limit: 2000, following: false, anchorKey: 'app.log:1200', endKey: 'app.log:1230',
    })
    expect(merged.rows).toHaveLength(3000)
    expect(merged.rows.some(row => row.key === 'app.log:1200')).toBe(true)
    expect(merged.rows.some(row => row.key === 'app.log:1230')).toBe(true)
    expect(merged.tailGap).toBe(true)
  })

  it('插入历史时保留当前底部可见行', () => {
    const merged = mergeLogWindow(rows(1000, 3000), rows(500, 500), {
      limit: 2000, following: false, prepend: true, anchorKey: 'app.log:3900', endKey: 'app.log:3930',
    })
    expect(merged.rows).toHaveLength(3000)
    expect(merged.rows.some(row => row.key === 'app.log:3930')).toBe(true)
    expect(merged.tailGap).toBe(false)
  })

  it('筛选只对新记录计算，条件变化后重新判断', () => {
    const filter = createLogFilter()
    const current = rows(0, 2)
    let reads = 0
    Object.defineProperty(current[0], 'searchText', { get() { reads++; return 'line 0' } })
    const options = { levels: ['INFO'], modules: [], terms: ['line'] }
    expect(filter(current, options)).toHaveLength(2)
    expect(filter([...current, ...rows(2, 1)], options)).toHaveLength(3)
    expect(reads).toBe(1)
    expect(filter(current, { ...options, terms: ['absent'] })).toHaveLength(0)
    expect(reads).toBe(2)
  })
})
