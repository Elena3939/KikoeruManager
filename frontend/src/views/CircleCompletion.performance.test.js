import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, shallowReactive, toRaw, watchEffect } from 'vue'
import { shallowMount } from '@vue/test-utils'
import source from './CircleCompletion.vue?raw'
import viewportSource from '../components/circle/CircleWorksViewport.vue?raw'
import WorkCard from '../components/circle/WorkCard.vue'

function loadFunctions(text, names, bindings, declarations = '') {
  const bodies = names.map(name => {
    const start = text.search(new RegExp(`(?:async )?function ${name}\\(`))
    if (start < 0) throw new Error(`找不到函数 ${name}`)
    return text.slice(start, text.indexOf('\n}', start) + 2)
  })
  return new Function(...Object.keys(bindings), `${declarations}\n${bodies.join('\n')}\nreturn { ${names.join(',')} }`)(...Object.values(bindings))
}

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

afterEach(() => vi.useRealTimers())

describe('社团首屏请求优先级', () => {
  it('recent 未返回时已发起路由社团加载，首屏不等待库存列表', async () => {
    const recent = deferred()
    const applyRouteCircleTarget = vi.fn().mockResolvedValue(true)
    const loadRecentCircles = vi.fn(() => recent.promise)
    const { initializeCircleView } = loadFunctions(source, ['initializeCircleView'], {
      getRouteCircleTarget: () => ({ circleId: '42' }),
      getRouteCircleTargetKey: () => '42', loadRecentCircles, applyRouteCircleTarget,
    })
    await initializeCircleView()
    expect(loadRecentCircles).toHaveBeenCalledWith({ selectDefault: false })
    expect(applyRouteCircleTarget).toHaveBeenCalledTimes(1)
    const mounted = source.slice(source.indexOf('onMounted(async'), source.indexOf('watch(() => route.fullPath'))
    expect(mounted).toContain('void loadLibraries()')
    expect(mounted).not.toContain('await Promise.all([loadRecentCircles(), loadLibraries()])')
  })

  it('recent 后到时保留直达社团，且不加载默认社团', async () => {
    const target = { circle_id: '42', circle_name: '直达社团' }
    const circleList = { value: [target] }
    const syncActiveCircleWithList = vi.fn()
    const { loadRecentCircles } = loadFunctions(source, ['loadRecentCircles'], {
      circleCompletionApi: { listRecentIndexes: async () => ({ circles: [{ circle_id: '1' }] }) },
      circleList, activeCircleId: { value: '42' }, syncActiveCircleWithList,
      getRouteCircleTargetKey: () => '42', getRouteCircleTarget: () => ({}),
    })
    await loadRecentCircles({ selectDefault: false })
    expect(circleList.value[0]).toBe(target)
    expect(syncActiveCircleWithList).not.toHaveBeenCalled()
  })

  it('circle_id 直达不查名称索引，并隔离 keep-alive 首次重复激活', async () => {
    const select = deferred()
    const selectCircle = vi.fn(() => select.promise)
    const resolveRouteCircleCandidate = vi.fn()
    const circleList = { value: [] }
    const { applyRouteCircleTarget } = loadFunctions(source, ['applyRouteCircleTarget'], {
      getRouteCircleTarget: () => ({ circleId: '42', circleName: '', rjcode: '' }),
      getRouteCircleTargetKey: () => '42', findRouteCircleCandidate: () => null,
      resolveRouteCircleCandidate, circleList,
      buildHeroSearchCircleListItem: item => item,
      ensureHeroSearchCircleVisible: vi.fn(), selectCircle,
    }, "let lastAppliedRouteCircleKey = ''; let applyingRouteCircleKey = ''")
    const first = applyRouteCircleTarget()
    await nextTick()
    await applyRouteCircleTarget({ force: true })
    expect(resolveRouteCircleCandidate).not.toHaveBeenCalled()
    expect(selectCircle).toHaveBeenCalledTimes(1)
    expect(circleList.value[0].circle_id).toBe('42')
    select.resolve()
    await first
  })
})

describe('外搜更新与作品实体隔离', () => {
  it('单行结果变化只通知对应 key，重复状态不触发订阅，作品对象不变', async () => {
    const externalSearchResults = shallowReactive(new Map())
    const detail = { works: [{ canonical_rjcode: 'RJ123456' }, { canonical_rjcode: 'RJ234567' }] }
    const entities = detail.works.slice()
    const calls = [vi.fn(), vi.fn()]
    const stops = entities.map((item, index) => watchEffect(() => calls[index](externalSearchResults.get(item.canonical_rjcode))))
    const { mergeExternalSearchResults } = loadFunctions(source, ['mergeExternalSearchResults'], {
      externalSearchResults, activeCircleId: { value: '42' },
      externalSearchWorkKey: (_, code) => code, EXTERNAL_SEARCH_RESULT_CACHE_MAX: 240,
    })
    mergeExternalSearchResults({ RJ123456: { anime_share: { status: 'hit' } } })
    await nextTick()
    mergeExternalSearchResults({ RJ123456: { anime_share: { status: 'hit' } } })
    await nextTick()
    expect(calls[0]).toHaveBeenCalledTimes(2)
    expect(calls[1]).toHaveBeenCalledTimes(1)
    expect(detail.works[0]).toBe(entities[0])
    stops.forEach(stop => stop())
  })

  it('缓存页或空页切换会中止上一页，晚到响应和失败不会串页', async () => {
    for (const rejectOld of [false, true]) {
      const old = deferred()
      const detail = { works: [{ canonical_rjcode: 'RJ123456' }] }
      const activeCircleId = { value: '42' }
      let signal
      const mergeExternalSearchResults = vi.fn()
      const searchExternalSources = vi.fn((_, options) => { signal = options.signal; return old.promise })
      const { refreshExternalSearchForPage } = loadFunctions(source, ['refreshExternalSearchForPage'], {
        detail, activeCircleId, normalizeRjcode: value => value, isBonusDisplayWork: () => false,
        getExternalSearchWorkCache: () => null, mergeExternalSearchResults,
        circleCompletionApi: { searchExternalSources }, AbortController,
        EXTERNAL_SEARCH_BATCH_SIZE: 20, setExternalSearchWorkCache: vi.fn(),
        buildExternalSearchFailure: () => ({ status: 'error' }),
      }, 'let externalSearchRequestSeq = 0; let externalSearchAbortController = null')
      const first = refreshExternalSearchForPage()
      detail.works = []
      await refreshExternalSearchForPage()
      expect(signal.aborted).toBe(true)
      if (rejectOld) old.reject(new Error('旧请求失败'))
      else old.resolve({ items: { RJ123456: { status: 'hit' } } })
      await first
      expect(mergeExternalSearchResults).toHaveBeenCalledTimes(1)
    }
  })

  it('卡片只给外搜标签投影状态，封面和作品属性保持原对象', async () => {
    const item = { canonical_rjcode: 'RJ123456', title: '原作品' }
    const states = shallowReactive(new Map())
    const wrapper = shallowMount(WorkCard, {
      props: { item }, global: { provide: { circleExternalSearchResult: code => states.get(code) } },
    })
    states.set('RJ123456', { anime_share: { status: 'hit' } })
    await nextTick()
    const chips = wrapper.findComponent({ name: 'ExternalSearchSourceChips' })
    expect(chips.props('item').external_search.anime_share.status).toBe('hit')
    expect(toRaw(wrapper.props('item'))).toBe(item)
    expect(item.external_search).toBeUndefined()
    wrapper.unmount()
  })
})

describe('封面队列帧批处理与复用', () => {
  it('可见列表每帧合并一次，最多 8 个并发，返回已加载图片不再占槽', () => {
    vi.useFakeTimers()
    const visibleImageKeys = { value: Array.from({ length: 12 }, (_, i) => `work${i}`) }
    const imageSignatures = { value: new Map(visibleImageKeys.value.map(key => [key, key])) }
    const activeImageKeys = { value: new Set() }
    const loadingImageKeys = new Set(), queuedImageKeys = new Set(), settledImages = new Map(), imageLoadTimers = new Map()
    const frames = []
    const requestAnimationFrame = vi.fn(callback => { frames.push(callback); return frames.length })
    const functions = loadFunctions(viewportSource, [
      'resolvedImageUrl', 'releaseImageSlot', 'markImageSettled', 'scheduleImagePump', 'pumpImageQueue', 'enqueueVisibleImages',
    ], {
      visibleImageKeys, imageSignatures, activeImageKeys, loadingImageKeys, queuedImageKeys, settledImages,
      imageLoadTimers, activeImageSignatures: new Map(), requestAnimationFrame, MAX_ACTIVE_IMAGES: 8, window,
    }, 'let imagePumpFrame = null')
    functions.enqueueVisibleImages()
    functions.enqueueVisibleImages()
    expect(frames).toHaveLength(1)
    frames.shift()()
    expect(loadingImageKeys.size).toBe(8)
    functions.markImageSettled('work0', { url: '/actual-cover.jpg' })
    functions.markImageSettled('work1', { url: '/second.jpg' })
    expect(frames).toHaveLength(1)
    frames.shift()()
    expect(loadingImageKeys.size).toBe(8)
    visibleImageKeys.value = []
    functions.pumpImageQueue()
    expect(loadingImageKeys.size).toBe(0)
    expect(imageLoadTimers.size).toBe(0)
    visibleImageKeys.value = ['work0']
    functions.pumpImageQueue()
    expect(activeImageKeys.value.has('work0')).toBe(true)
    expect(loadingImageKeys.size).toBe(0)
    expect(functions.resolvedImageUrl('work0')).toBe('/actual-cover.jpg')
    imageSignatures.value.set('work0', '刷新封面')
    expect(functions.resolvedImageUrl('work0')).toBe('')
    functions.pumpImageQueue()
    expect(loadingImageKeys.has('work0')).toBe(true)
  })
})
