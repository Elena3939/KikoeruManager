import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLibraryIndexStateStore } from '../stores/libraryIndexState'
import { apiRenameDeletedPaths } from './apiRenameResults'

describe('API 重命名结果的库存可见性', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('名称未变时目录和子文件仍然可见', () => {
    const store = useLibraryIndexStateStore()
    const path = '/library/[テグラユウキ][RJ01036995]'
    const response = { results: [{ success: true, path, new_path: path }] }
    store.registerMutationResponse(response, {
      libraryId: 'a',
      deletedPaths: apiRenameDeletedPaths(response.results)
        .map(path => ({ libraryId: 'a', path, scope: 'subtree' })),
    })
    const rows = [{ path }, { path: `${path}/本編/audio.wav` }]
    expect(store.filterRows('a', rows)).toEqual(rows)
  })

  it('混合结果只删除真实改名的旧路径', () => {
    expect(apiRenameDeletedPaths([
      { success: true, path: '/旧名', new_path: '/新名' },
      { success: true, path: '/同名', new_path: '/同名/' },
      { success: true, path: 'C:\\库\\同名', new_path: 'C:/库/同名' },
      { success: true, path: '/无变化', new_path: '/其它', no_change: true },
      { success: false, path: '/失败', new_path: '/其它' },
      { success: true, path: '/缺少目标' },
    ])).toEqual(['/旧名'])
  })
})
