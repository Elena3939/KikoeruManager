import { describe, expect, it } from 'vitest'
import { aggregateConflictRjcodes, formatConflictLabel } from './conflictLabel'

const codes = ['RJ01511409', 'RJ01653669', 'RJ01653910', 'RJ01653911', 'RJ01696686', 'RJ01711137']
const conflict = {
  rjcode: codes[0],
  new_path: '/downloads/合集.zip',
  new_metadata: { aggregate_archive: true, aggregate_rjcodes: codes, aggregate_rj_count: 6 },
}

describe('合集问题项标题', () => {
  it('旧记录即使绑定第一个 RJ，标题也显示整个合集', () => {
    expect(formatConflictLabel(conflict)).toBe('合集.zip（6 个作品）')
    expect(aggregateConflictRjcodes(conflict)).toEqual(codes)
    expect(conflict.rjcode).toBe(codes[0])
  })

  it('兼容 Windows 路径，数量取去重后的有效清单', () => {
    expect(formatConflictLabel({ ...conflict, new_path: 'E:\\downloads\\合集.zip', new_metadata: {
      ...conflict.new_metadata, aggregate_rjcodes: [...codes, codes[0], '无效'], aggregate_rj_count: 999,
    } })).toBe('合集.zip（6 个作品）')
  })

  it('单作品和权威锁定的 RJ 保持作品标题', () => {
    expect(formatConflictLabel({ ...conflict, new_metadata: {} })).toBe(codes[0])
    expect(formatConflictLabel({ ...conflict, new_metadata: { ...conflict.new_metadata, rjcode_lock: true } })).toBe(codes[0])
    expect(aggregateConflictRjcodes({ new_metadata: { aggregate_archive: true, aggregate_rjcodes: [codes[0], codes[0]] } })).toEqual([])
  })
})
