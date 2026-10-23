import { computed, ref } from 'vue'
import { describe, it, expect } from 'vitest'
import { useUploadFileTree } from './useUploadFileTree'

describe('上传文件树', () => {
  it('纯文件平铺且保留传输项', () => {
    const file = { relative_path: 'a.txt', size: 10 }
    const { rows } = useUploadFileTree(ref([file, { relative_path: 'b.txt' }]))
    expect(rows.value.map(row => [row.name, row.depth, row.type])).toEqual([['a.txt', 0, 'file'], ['b.txt', 0, 'file']])
    expect(rows.value[0].file.relative_path).toBe('a.txt')
  })
  it('合并显式目录与隐含目录，折叠不影响其他根文件', () => {
    const { rows, toggle } = useUploadFileTree(ref([
      { relative_path: '目录/a.txt' }, { relative_path: '目录', is_directory: true },
      { relative_path: '目录/空目录', is_directory: true }, { relative_path: 'b.txt' },
    ]))
    expect(rows.value.map(row => row.id)).toEqual(['目录', '目录/a.txt', '目录/空目录', 'b.txt'])
    toggle(rows.value[0])
    expect(rows.value.map(row => row.id)).toEqual(['目录', 'b.txt'])
    toggle(rows.value[0])
    expect(rows.value).toHaveLength(4)
  })
})
