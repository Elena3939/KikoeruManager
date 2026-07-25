import { describe, expect, it } from 'vitest'
import { buildLibraryPathKey } from './libraryOperationKey'

describe('buildLibraryPathKey', () => {
  it('同一行号但不同目录生成不同操作标识', () => {
    const original = buildLibraryPathKey('library-a', 'D:/Library/RJ001')
    const siblingChild = buildLibraryPathKey('library-a', 'D:/Library/Other/RJ001')

    expect(siblingChild).not.toBe(original)
  })

  it('统一路径分隔符和末尾分隔符', () => {
    expect(buildLibraryPathKey('library-a', 'D:\\Library\\RJ001\\')).toBe('library-a::D:/Library/RJ001')
  })
})
