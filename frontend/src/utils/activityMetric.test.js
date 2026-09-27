import { describe, expect, it } from 'vitest'
import { splitActivityMetric } from './activityMetric.js'

describe('操作历史指标显示', () => {
  it('完整显示纯数字计数，不把末位误当单位', () => {
    expect(splitActivityMetric('4387')).toEqual({ num: '4387', unit: '' })
    expect(splitActivityMetric(1089)).toEqual({ num: '1089', unit: '' })
  })

  it('只拆分真实的文本单位', () => {
    expect(splitActivityMetric('1918.08 GB')).toEqual({ num: '1918.08', unit: 'GB' })
    expect(splitActivityMetric('<0.01 GB')).toEqual({ num: '<0.01', unit: 'GB' })
  })
})
