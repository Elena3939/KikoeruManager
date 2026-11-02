import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { createLatestRequestGate } from '../utils/libraryRequestGuard'
import source from './Library.vue?raw'

function loadFunctions (names, bindings, declarations = '') {
  const bodies = names.map(name => {
    const match = source.match(new RegExp(`(?:async )?function ${name} \\([^]*?\\n\\}`))
    if (!match) throw new Error(`找不到函数 ${name}`)
    return match[0]
  })
  return new Function(...Object.keys(bindings), `${declarations}\n${bodies.join('\n')}\nreturn { ${names.join(',')} }`)(...Object.values(bindings))
}

function deferred () {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

function directoryBindings () {
  return {
    libraryViewMode: ref('directory'),
    selectedLibraryId: ref('library'),
    currentPath: ref('/library'),
    currentPage: ref(1),
    pageSize: ref(20),
    sortBy: ref('size'),
    sortOrder: ref('desc'),
    DEFAULT_PAGE_SIZE: 20,
    DEFAULT_SORT_BY: 'size',
    DEFAULT_SORT_ORDER: 'desc',
    directoryRequestGate: createLatestRequestGate(),
    selectedRowPaths: ref(new Set()),
    selectedRows: ref([]),
    suppressSelectionChange: ref(false),
    getLibraryPageCursorForRequest: () => '',
    clearListPoll: vi.fn(),
    listPolling: ref(false),
    loading: ref(true),
    libraryApi: { browseFiles: vi.fn() },
    files: ref([]),
    totalFiles: ref(0),
    libraryIndexStateStore: {
      isIndexViewResponseCurrent: () => true,
      recordIndexViews: vi.fn(),
      setLibraryRoots: vi.fn(),
    },
    filterRowsByIndexTombstones: rows => rows,
    applyRecentRenameRows: rows => rows,
    libraries: ref([]),
    browseRootPath: ref('/library'),
    parentPath: ref(''),
    rememberLibraryPageCursor: vi.fn(),
    librarySearchState: ref({}),
    createLibrarySearchState: () => ({}),
    scheduleListPoll: vi.fn(),
    applyTableSortIndicator: nextTick,
    nextTick,
    ElMessage: { error: vi.fn() },
  }
}

describe('库存内容加载生命周期', () => {
  it('静默目录请求接替前台请求时，列表提交前不能提前关闭加载态', async () => {
    const request = deferred()
    const bindings = directoryBindings()
    bindings.libraryApi.browseFiles.mockReturnValue(request.promise)
    const { refreshLibraryInternal } = loadFunctions(['refreshLibraryInternal'], bindings)
    const refresh = refreshLibraryInternal({ silent: true })
    expect(bindings.loading.value).toBe(true)
    request.resolve({ files: [{ name: 'RJ123456', path: '/library/RJ123456' }], total: 1 })
    await refresh
    expect(bindings.files.value).toHaveLength(1)
    expect(bindings.loading.value).toBe(false)
  })

  it('已有列表的后台刷新不额外打开遮罩', async () => {
    const bindings = directoryBindings()
    bindings.loading.value = false
    bindings.files.value = [{ name: '旧条目', path: '/library/old' }]
    const request = deferred()
    bindings.libraryApi.browseFiles.mockReturnValue(request.promise)
    const { refreshLibraryInternal } = loadFunctions(['refreshLibraryInternal'], bindings)
    const refresh = refreshLibraryInternal({ silent: true })
    expect(bindings.loading.value).toBe(false)
    expect(bindings.files.value[0].name).toBe('旧条目')
    request.resolve({ files: [], total: 0 })
    await refresh
    expect(bindings.files.value).toEqual([])
  })

  it('静默社团请求接替前台请求时保留加载态到列表提交', async () => {
    const request = deferred()
    const circleLoading = ref(true)
    const bindings = {
      circleLoading,
      circleErrorMessage: ref(''),
      libraryViewMode: ref('circle'),
      requestCircleLibraryViewData: () => request.promise,
      commitCircleLibraryViewResult: vi.fn(() => true),
      applyTableSortIndicator: nextTick,
      handleCircleLibraryViewError: vi.fn(),
    }
    const { refreshCircleLibraryView } = loadFunctions(
      ['refreshCircleLibraryView'], bindings, 'let circleRefreshSequence = 0; let circleAbortController = null',
    )
    const refresh = refreshCircleLibraryView({ silent: true })
    expect(circleLoading.value).toBe(true)
    request.resolve({ data: { files: [{ name: '社团' }] } })
    await refresh
    expect(bindings.commitCircleLibraryViewResult).toHaveBeenCalledTimes(1)
    expect(circleLoading.value).toBe(false)
  })

  it.each(['directory', 'circle'])('初始化 %s 视图显式等待文件列表，且不等待无关统计才结束遮罩', async mode => {
    const content = deferred()
    const stats = deferred()
    const bindings = {
      libraryInitializing: ref(true),
      libraryViewMode: ref(mode),
      selectedLibraryId: ref('library'),
      trackedUploadTaskIds: ref([]),
      restoreUploadWorkbenchState: vi.fn(),
      loadLibraryViewPreferences: vi.fn().mockResolvedValue(undefined),
      loadLibraries: vi.fn().mockResolvedValue(undefined),
      loadRJSubtitlePreferences: vi.fn().mockResolvedValue(undefined),
      restoreSubtitleScanWorkspace: vi.fn(),
      refreshLibrary: vi.fn(() => content.promise),
      refreshCircleLibraryView: vi.fn(() => content.promise),
      refreshStats: vi.fn(() => stats.promise),
      refreshUploadWorkbench: vi.fn(),
      nextTick,
    }
    const { initializeLibraryPage } = loadFunctions(
      ['initializeLibraryPage'], bindings, 'let libraryInitialized = false',
    )
    const initialized = initializeLibraryPage()
    await vi.waitFor(() => expect(bindings.refreshLibrary).toHaveBeenCalledTimes(1))
    expect(bindings.libraryInitializing.value).toBe(true)
    expect(bindings.refreshLibrary).toHaveBeenCalledWith()
    content.resolve()
    await vi.waitFor(() => expect(bindings.libraryInitializing.value).toBe(false))
    stats.resolve()
    await initialized
    expect(bindings.refreshCircleLibraryView).not.toHaveBeenCalled()
  })

  it('初始化失败也结束加载态，不留下永久遮罩', async () => {
    const bindings = {
      libraryInitializing: ref(true),
      restoreUploadWorkbenchState: vi.fn(),
      loadLibraryViewPreferences: vi.fn().mockRejectedValue(new Error('网络失败')),
    }
    const { initializeLibraryPage } = loadFunctions(
      ['initializeLibraryPage'], bindings, 'let libraryInitialized = false',
    )
    await expect(initializeLibraryPage()).rejects.toThrow('网络失败')
    expect(bindings.libraryInitializing.value).toBe(false)
  })

  it('列表不再因路径、页码或排序变化而先退场卸载', () => {
    expect(source.includes('name="lib-file-table-swap"')).toBe(false)
    expect(source.includes(':key="libraryTableKey"')).toBe(false)
  })
})
