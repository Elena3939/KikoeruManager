import { describe, expect, it } from 'vitest'

import { applyLibraryFrontendFilter } from './_libraryFileKind'

describe('applyLibraryFrontendFilter', () => {
  it('保留同语言翻译关联命中，即使文件夹名不含搜索 RJ', () => {
    const items = applyLibraryFrontendFilter([
      {
        entry_type: 'dir',
        name: '[RJ01700003] 另一译者版本',
        rjcode: 'RJ01700003',
        search_match_type: 'related_translation',
      },
    ], {
      keyword: 'RJ01700002',
      matchedRjcode: 'RJ01700002',
    })

    expect(items).toHaveLength(1)
    expect(items[0].rjcode).toBe('RJ01700003')
  })
})
