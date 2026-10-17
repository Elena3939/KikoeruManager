import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { shallowMount } from '@vue/test-utils'
import CircleWorksViewport from './CircleWorksViewport.vue'
import WorkCard from './WorkCard.vue'
import WorkListRow from './WorkListRow.vue'

vi.mock('@tanstack/vue-virtual', async () => {
  const { computed } = await import('vue')
  return {
    useVirtualizer: options => computed(() => ({
      getVirtualItems: () => Array.from({ length: Math.min(options.value.count, 2) }, (_, index) => ({
        index, key: index, start: index * options.value.estimateSize(),
      })),
      getTotalSize: () => options.value.count * options.value.estimateSize(),
      scrollToOffset: vi.fn(), measure: vi.fn(),
    })),
  }
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('社团封面结果在两种渲染布局复用', () => {
  it.each([
    ['移动端卡片', 480, 'card', WorkCard],
    ['桌面虚拟卡片', 1200, 'card', WorkCard],
    ['移动端列表', 480, 'list', WorkListRow],
    ['桌面虚拟列表', 1200, 'list', WorkListRow],
  ])('%s 离开视口再返回直接使用成功的实际图片 URL', async (_, width, mode, child) => {
    vi.useFakeTimers()
    let frames = []
    vi.stubGlobal('requestAnimationFrame', callback => { frames.push(callback); return frames.length })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback) { this.callback = callback }
      observe(target) {
        Object.defineProperty(target, 'clientWidth', { value: width, configurable: true })
        this.callback()
      }
      disconnect() {}
    })
    const flushFrames = async () => {
      await nextTick()
      for (let n = 0; frames.length && n < 10; n++) {
        const current = frames
        frames = []
        current.forEach(callback => callback())
        await nextTick()
      }
    }
    const item = { canonical_rjcode: 'RJ123456', title: '测试作品', image_url: '/cover.jpg' }
    const wrapper = shallowMount(CircleWorksViewport, {
      props: { items: [item], mode, serverPaging: true, totalItems: 1 },
      global: { stubs: { ElPagination: true, ElDialog: true } },
    })
    await flushFrames()
    const first = wrapper.findComponent(child)
    expect(first.exists()).toBe(true)
    expect(first.props('imageActive')).toBe(true)
    first.vm.$emit('image-settled', { url: '/successful-fallback.jpg' })
    await flushFrames()
    await wrapper.setProps({ items: [] })
    await flushFrames()
    await wrapper.setProps({ items: [item] })
    await flushFrames()
    const returned = wrapper.findComponent(child)
    expect(returned.props('resolvedCoverUrl')).toBe('/successful-fallback.jpg')
    expect(returned.props('imageActive')).toBe(true)
    wrapper.unmount()
  })
})
