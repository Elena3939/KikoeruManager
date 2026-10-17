import { describe, expect, it, vi } from 'vitest'
import { createLatestRequestGate } from '../utils/libraryRequestGuard'
import source from './Library.vue?raw'

function loadFunctions (names, bindings, declarations = '') {
  const bodies = names.map(name => {
    const start = source.indexOf(`function ${name} (`)
    if (start < 0) throw new Error(`找不到函数 ${name}`)
    const end = source.indexOf('\n}', start) + 2
    return source.slice(start, end)
  })
  return new Function(...Object.keys(bindings), `${declarations}\n${bodies.join('\n')}\nreturn { ${names.join(',')} }`)(...Object.values(bindings))
}

describe('库存索引完成后的目录刷新', () => {
  it('索引版本变化后清除已中止请求，允许同一目录重新请求', () => {
    const gate = createLatestRequestGate()
    const request = gate.begin()
    const inFlight = new Map([['directory|library|folder', Promise.resolve()]])
    const state = {
      directoryRequestGate: gate,
      directoryRefreshInFlight: inFlight,
      suppressSelectionChange: { value: true },
      listPolling: { value: true },
      loading: { value: true },
    }
    const { invalidateDirectoryViewRequests } = loadFunctions(['invalidateDirectoryViewRequests'], state)
    invalidateDirectoryViewRequests()

    expect(request.controller.signal.aborted).toBe(true)
    expect(inFlight.size).toBe(0)
    expect(gate.isCurrent(gate.begin())).toBe(true)
  })

  it('刷新尚未返回时第二个完成事件保留待刷新项，结束后再次校正', async () => {
    let complete
    const refreshLibrary = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
      .mockResolvedValue(undefined)
    const pending = new Map([['library:1', { index_fences: [{ library_id: 'library' }] }]])
    const bindings = {
      pendingIndexFenceRefreshes: pending,
      selectedLibraryId: { value: 'library' },
      indexFencesMaterialized: () => true,
      pendingFenceAffectsCurrentDirectory: () => true,
      clearPendingIndexFence: vi.fn(),
      refreshLibrary,
      folderDialogVisible: { value: false },
      folderDialogRef: { value: null },
      ElMessage: { warning: vi.fn() },
    }
    const functions = loadFunctions(
      ['refreshMaterializedLibraryViews', 'flushPendingIndexFenceRefreshes'],
      bindings,
      'let pendingFenceRefreshInFlight = false; let pendingFenceRefreshNeedsFlush = false',
    )
    functions.flushPendingIndexFenceRefreshes()
    expect(refreshLibrary).toHaveBeenCalledTimes(1)

    pending.set('library:2', { index_fences: [{ library_id: 'library' }] })
    functions.flushPendingIndexFenceRefreshes()
    expect(pending.has('library:2')).toBe(true)
    complete()
    await vi.waitFor(() => expect(refreshLibrary).toHaveBeenCalledTimes(2))
    expect(pending.size).toBe(0)
  })
})
