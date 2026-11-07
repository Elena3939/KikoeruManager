import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import CircleWorksViewport from './CircleWorksViewport.vue'

const calls = vi.hoisted(() => ({ index: vi.fn(), offset: vi.fn(), reveal: vi.fn() }))

vi.mock('@tanstack/vue-virtual', async () => {
  const { computed, ref } = await import('vue')
  return {
    useVirtualizer: options => {
      const firstRow = ref(0)
      return computed(() => ({
        getVirtualItems: () => Array.from(
          { length: Math.min(2, Math.max(0, options.value.count - firstRow.value)) },
          (_, offset) => {
            const index = firstRow.value + offset
            return { index, key: index, start: index * options.value.estimateSize(), size: options.value.estimateSize() }
          },
        ),
        getTotalSize: () => options.value.count * options.value.estimateSize(),
        scrollToOffset: offset => { calls.offset(offset); firstRow.value = 0 },
        scrollToIndex: (index, settings) => { calls.index(index, settings); firstRow.value = index },
        measure: vi.fn(),
      }))
    },
  }
})

const work = index => ({ canonical_rjcode: `RJ${100000 + index}`, title: `作品 ${index}` })
const items = Array.from({ length: 100 }, (_, index) => work(index))
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
let wrapper
let width

beforeEach(() => {
  width = 1200
  vi.stubGlobal('requestAnimationFrame', () => 1)
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { this.callback = callback }
    observe(target) {
      Object.defineProperty(target, 'clientWidth', { configurable: true, get: () => width })
      this.callback()
    }
    unobserve() {}
    disconnect() {}
  })
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value(options) { calls.reveal(this.dataset.workIndex, options) },
  })
})

afterEach(() => {
  wrapper?.unmount()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalScrollIntoView) {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
  } else {
    delete HTMLElement.prototype.scrollIntoView
  }
})

async function mountViewport(props = {}) {
  wrapper = shallowMount(CircleWorksViewport, {
    props: { items, serverPaging: true, totalItems: 200, pageSize: 100, ...props },
    global: { stubs: { ElPagination: true, ElDialog: true } },
  })
  await flushPromises()
  return wrapper
}

describe('社团搜索结果滚动定位', () => {
  it.each(['card', 'list'])('%s 将尚未渲染的目标行滚入视口并高亮', async mode => {
    await mountViewport({ mode })
    expect(wrapper.find('[data-work-index="90"]').exists()).toBe(false)

    await wrapper.setProps({ locatedCodes: new Set(['RJ100090']) })
    await flushPromises()

    const columns = mode === 'card' ? 7 : 1
    expect(calls.index).toHaveBeenLastCalledWith(Math.floor(90 / columns), { align: 'center' })
    const cell = wrapper.get('[data-work-index="90"]')
    expect(cell.findComponent({ name: mode === 'card' ? 'WorkCard' : 'WorkListRow' }).props('locateFlash')).toBe(true)
    expect(calls.reveal).toHaveBeenLastCalledWith('90', expect.objectContaining({ block: 'nearest' }))
  })

  it('跨页异步返回作品后定位，切页置顶不会覆盖目标滚动', async () => {
    await mountViewport()
    await wrapper.setProps({ currentPage: 2, locatedCodes: new Set(['RJ200090']) })
    await flushPromises()
    expect(calls.index).not.toHaveBeenCalled()

    const secondPage = Array.from({ length: 100 }, (_, index) => ({
      ...work(index), canonical_rjcode: `RJ${200000 + index}`,
    }))
    await wrapper.setProps({ items: secondPage })
    await flushPromises()
    expect(calls.index).toHaveBeenLastCalledWith(12, { align: 'center' })
    expect(wrapper.find('[data-work-index="90"]').exists()).toBe(true)

    const indexCalls = calls.index.mock.calls.length
    await wrapper.setProps({ items: secondPage.map(item => ({ ...item, owned: true })) })
    await flushPromises()
    expect(calls.index).toHaveBeenCalledTimes(indexCalls)
    await wrapper.setProps({ locatedCodes: new Set() })
    await flushPromises()
    expect(calls.index).toHaveBeenCalledTimes(indexCalls)
  })

  it('同时更新分页、总数和定位时，最终停留目标行', async () => {
    await mountViewport({ mode: 'list' })
    await wrapper.setProps({ currentPage: 2, totalItems: 300, locatedCodes: new Set(['RJ100090']) })
    await flushPromises()
    expect(wrapper.find('[data-work-index="90"]').exists()).toBe(true)
    expect(calls.index.mock.invocationCallOrder.at(-1)).toBeGreaterThan(calls.offset.mock.invocationCallOrder.at(-1))
  })

  it.each(['card', 'list'])('移动端 %s 直接滚动到目标元素', async mode => {
    width = 480
    await mountViewport({ mode, locatedCodes: new Set(['RJ100090']) })
    expect(calls.index).not.toHaveBeenCalled()
    expect(calls.reveal).toHaveBeenLastCalledWith('90', expect.objectContaining({ block: 'nearest' }))
  })

  it.each(['card', 'list'])('%s 定位附属特典对应的卡片或列表行', async mode => {
    const bonus = { canonical_rjcode: 'RJ999999', title: '特典' }
    const page = items.map((item, index) => index === 90 ? { ...item, bonus_display_works: [bonus] } : item)
    await mountViewport({ mode, items: page, locatedCodes: new Set(['RJ999999']) })
    const index = mode === 'card' ? 90 : 91
    expect(calls.index).toHaveBeenLastCalledWith(mode === 'card' ? 12 : 91, { align: 'center' })
    expect(calls.reveal).toHaveBeenLastCalledWith(String(index), expect.any(Object))
  })

  it('快速更换定位目标时，旧定位不会覆盖新目标', async () => {
    await mountViewport({ mode: 'list' })
    const first = wrapper.setProps({ locatedCodes: new Set(['RJ100050']) })
    await nextTick()
    await wrapper.setProps({ locatedCodes: new Set(['RJ100090']) })
    await first
    await flushPromises()
    expect(calls.reveal).toHaveBeenLastCalledWith('90', expect.any(Object))
  })
})
