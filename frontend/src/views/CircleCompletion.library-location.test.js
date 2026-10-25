import { describe, expect, it, vi } from 'vitest'
import source from './CircleCompletion.vue?raw'
import librarySource from './Library.vue?raw'
import { circleWorkVersionRjcode } from '../utils/circleWorkVersion'

function functions(text, names, bindings) {
  const bodies = names.map(name => {
    const start = text.search(new RegExp(`(?:async )?function ${name}\\s*\\(`))
    if (start < 0) throw new Error(`找不到函数 ${name}`)
    return text.slice(start, text.indexOf('\n}', start) + 2)
  })
  return new Function(...Object.keys(bindings), `${bodies.join('\n')}\nreturn { ${names.join(',')} }`)(...Object.values(bindings))
}

const item = {
  owned: true,
  canonical_rjcode: 'RJ10000',
  display_rjcode: 'RJ10001',
  owned_variant: { rjcode: 'RJ10002', group_short_label: '简中' },
  owned_paths: ['/旧缓存/原作'],
}
const location = (path = '/库存/简中') => ({ rjcode: 'RJ10002', library_id: 'local', library_name: '本地库', path })

function locator(getLibraryLocations) {
  const bindings = {
    circleWorkVersionRjcode, normalizeRjcode: value => String(value).toUpperCase(),
    circleCompletionApi: { getLibraryLocations },
    locatingLibraryWork: { value: false },
    libraryLocations: { value: [] }, libraryLocationsVisible: { value: false },
    closeWorkContextMenu: vi.fn(), goToLibraryLocation: vi.fn(),
    ElMessage: { warning: vi.fn(), error: vi.fn() },
  }
  return { ...bindings, ...functions(source, ['locateWorkInLibrary'], bindings) }
}

describe('社团作品库存定位', () => {
  it('未拥有作品置灰且不查询库存', async () => {
    const api = vi.fn()
    const state = locator(api)
    await state.locateWorkInLibrary({ ...item, owned: false })
    await state.locateWorkInLibrary({ rjcode: 'RJ10002' })
    expect(api).not.toHaveBeenCalled()
    expect(state.goToLibraryLocation).not.toHaveBeenCalled()
    expect(source).toContain(':disabled="!workContextMenu.item.owned || locatingLibraryWork"')
    expect(source).toContain('<span>前往库存</span>')
  })

  it('卡片、列表和定位统一使用实际展示的语言版本', () => {
    expect(circleWorkVersionRjcode(item)).toBe('RJ10002')
    expect(circleWorkVersionRjcode({ ...item, owned: false, download_plan: { rjcode: 'RJ10003' } })).toBe('RJ10003')
    expect(circleWorkVersionRjcode({ rjcode: 'RJ10004', is_bonus_work: true })).toBe('RJ10004')
  })

  it('单位置直接进入，重复点击重新查索引并使用更新后的路径', async () => {
    const api = vi.fn().mockResolvedValueOnce({ locations: [location()] })
      .mockResolvedValueOnce({ locations: [location('/库存/移动后的简中')] })
    const state = locator(api)
    await state.locateWorkInLibrary(item)
    await state.locateWorkInLibrary(item)
    expect(api.mock.calls).toEqual([['RJ10002'], ['RJ10002']])
    expect(state.goToLibraryLocation.mock.calls.map(([hit]) => hit.path)).toEqual(['/库存/简中', '/库存/移动后的简中'])
    expect(state.libraryLocationsVisible.value).toBe(false)
  })

  it('只有同版本多目录才显示选择，过滤其它语言', async () => {
    const state = locator(vi.fn().mockResolvedValue({ locations: [
      location(), location('/另一个库/简中'), { ...location('/库存/原作'), rjcode: 'RJ10000' },
    ] }))
    await state.locateWorkInLibrary(item)
    expect(state.goToLibraryLocation).not.toHaveBeenCalled()
    expect(state.libraryLocationsVisible.value).toBe(true)
    expect(state.libraryLocations.value).toHaveLength(2)
  })

  it('当前语言未命中时不使用跨语言路径或页面旧缓存', async () => {
    const state = locator(vi.fn().mockResolvedValue({ locations: [] }))
    await state.locateWorkInLibrary(item)
    expect(state.goToLibraryLocation).not.toHaveBeenCalled()
    expect(state.libraryLocationsVisible.value).toBe(false)
    expect(state.ElMessage.warning).toHaveBeenCalled()
  })

  it('查询期间拦截重复点击，失败后恢复', async () => {
    let reject
    const api = vi.fn(() => new Promise((_, no) => { reject = no }))
    const state = locator(api)
    const pending = state.locateWorkInLibrary(item)
    await state.locateWorkInLibrary(item)
    expect(api).toHaveBeenCalledTimes(1)
    reject(new Error('索引失败'))
    await pending
    expect(state.locatingLibraryWork.value).toBe(false)
    expect(state.ElMessage.error).toHaveBeenCalled()
  })
})

describe('库存路由定位', () => {
  function consumer(overrides = {}) {
    const bindings = {
      route: { name: 'Library', path: '/library', query: { locateLibraryId: 'local', locatePath: '/库存/简中', keep: '1' }, hash: '' },
      router: { replace: vi.fn().mockResolvedValue() },
      libraries: { value: [{ id: 'local', root_path: '/库存' }] },
      isPathWithinLibraryRoot: vi.fn().mockReturnValue(true),
      locateCircleLocation: vi.fn(),
      ElMessage: { warning: vi.fn() },
      ...overrides,
    }
    return { ...bindings, ...functions(librarySource, ['consumeLibraryLocationRoute'], bindings) }
  }

  it('清理一次性参数，复用库存现有的跨库和目录定位流程', async () => {
    const state = consumer()
    await state.consumeLibraryLocationRoute()
    expect(state.router.replace).toHaveBeenCalledWith({ path: '/library', query: { keep: '1' }, hash: '' })
    expect(state.locateCircleLocation).toHaveBeenCalledWith({ library_id: 'local', path: '/库存/简中' }, { forceRefresh: false })
    expect(librarySource.match(/await consumeLibraryLocationRoute\(\)/g)).toHaveLength(3)
    expect(librarySource).toContain('if (!libraryInitialized || libraryViewActive) return')
  })

  it('拒绝已删除的库存或库存根目录以外路径', async () => {
    const state = consumer({ isPathWithinLibraryRoot: () => false })
    await state.consumeLibraryLocationRoute()
    expect(state.locateCircleLocation).not.toHaveBeenCalled()
    expect(state.ElMessage.warning).toHaveBeenCalled()
  })
})
