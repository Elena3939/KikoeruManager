import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CircleWorksViewport from './CircleWorksViewport.vue'

const originalResizeObserver = globalThis.ResizeObserver
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
let mockClientWidth = 600
let mockClientHeight = 600

describe('CircleWorksViewport', () => {
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      constructor(callback) {
        this.callback = callback
      }
      observe(target) {
        this.callback([{
          target,
          contentRect: { width: mockClientWidth, height: mockClientHeight },
          borderBoxSize: [{ inlineSize: mockClientWidth, blockSize: mockClientHeight }],
        }])
      }
      unobserve() {}
      disconnect() {}
    }
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => mockClientWidth,
    })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get: () => mockClientHeight,
    })
  })

  afterAll(() => {
    globalThis.ResizeObserver = originalResizeObserver
    if (originalClientWidth) {
      Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth)
    } else {
      delete HTMLElement.prototype.clientWidth
    }
    if (originalClientHeight) {
      Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight)
    } else {
      delete HTMLElement.prototype.clientHeight
    }
  })

  it('附属小图失败时回退主图，主图也失败后显示占位', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mount(CircleWorksViewport, {
      props: {
        imageField: 'thumb_image_url',
        items: [
          {
            canonical_rjcode: 'RJ01666799',
            display_rjcode: 'RJ01666799',
            title: '原作',
          },
          {
            canonical_rjcode: 'RJ01667699',
            display_rjcode: 'RJ01667699',
            linked_rjcodes: ['RJ01666799', 'RJ01667699'],
            title: '早期购入特典',
            is_bonus_work: true,
            thumb_image_url: '/api/circle-completion/cover/RJ01667699_sam.jpg',
            image_url: '/api/circle-completion/cover/RJ01667699.jpg',
          },
        ],
      },
      global: {
        stubs: {
          WorkCard: { template: '<div />' },
          WorkListRow: { template: '<div />' },
          ElPagination: { template: '<div />' },
        },
      },
    })

    await flushPromises()

    const smallCover = wrapper.get('.circle-bonus-gift-cover img')
    expect(smallCover.attributes('src')).toBe('/api/circle-completion/cover/RJ01667699_sam.jpg')

    await smallCover.trigger('error')
    expect(smallCover.element.src).toContain('/api/circle-completion/cover/RJ01667699.jpg')

    await smallCover.trigger('error')
    await flushPromises()
    expect(wrapper.find('.circle-bonus-gift-cover img').exists()).toBe(false)

    wrapper.unmount()
  })

  it('点击特典小图直接展示本地主图且不重复请求封面', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mount(CircleWorksViewport, {
      props: {
        imageField: 'thumb_image_url',
        items: [
          {
            canonical_rjcode: 'RJ01673453',
            display_rjcode: 'RJ01673453',
            title: '原作',
          },
          {
            canonical_rjcode: 'RJ01678200',
            display_rjcode: 'RJ01678200',
            linked_rjcodes: ['RJ01673453', 'RJ01678200'],
            bonus_parent_rjcode: 'RJ01673453',
            title: '特典',
            is_bonus_work: true,
            thumb_image_url: '/api/circle-completion/cover/RJ01678200_sam.jpg',
            image_url: '/api/circle-completion/cover/RJ01678200.jpg',
          },
        ],
      },
      global: {
        stubs: {
          WorkCard: { template: '<div />' },
          WorkListRow: { template: '<div />' },
          ElPagination: { template: '<div />' },
        },
      },
    })

    await flushPromises()
    await wrapper.get('.circle-bonus-gift').trigger('click')
    await flushPromises()

    expect(wrapper.get('.circle-bonus-detail-cover img').attributes('src')).toBe('/api/circle-completion/cover/RJ01678200.jpg')
    expect(wrapper.emitted('ensure-cover')).toBeUndefined()

    wrapper.unmount()
  })

  it('宽屏大页只挂载可见行和一行预渲染卡片', async () => {
    mockClientWidth = 1600
    mockClientHeight = 600
    const items = Array.from({ length: 100 }, (_, index) => ({
      canonical_rjcode: `RJ${String(index + 1).padStart(8, '0')}`,
      display_rjcode: `RJ${String(index + 1).padStart(8, '0')}`,
      title: `作品 ${index + 1}`,
    }))
    const wrapper = mount(CircleWorksViewport, {
      props: {
        items,
        totalItems: items.length,
        pageSize: 100,
        serverPaging: true,
      },
      global: {
        stubs: {
          WorkCard: { template: '<div class="work-card-stub" />' },
          WorkListRow: { template: '<div />' },
          ElPagination: { template: '<div />' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.find('.circle-work-plain').exists()).toBe(false)
    expect(wrapper.findAll('.circle-work-virtual-row').length).toBeGreaterThan(0)
    expect(wrapper.findAll('.work-card-stub').length).toBeLessThan(50)

    const scroll = wrapper.get('.circle-work-scroll')
    await scroll.trigger('scroll')
    expect(scroll.classes()).toContain('is-scrolling')

    wrapper.unmount()
  })

  it('选中光环按作品顺序错峰，避免全选时同帧脉冲', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mount(CircleWorksViewport, {
      props: {
        items: [
          { canonical_rjcode: 'RJ01000001', display_rjcode: 'RJ01000001', title: '作品 1' },
          { canonical_rjcode: 'RJ01000002', display_rjcode: 'RJ01000002', title: '作品 2' },
        ],
        totalItems: 2,
        selectedCodes: new Set(['RJ01000001', 'RJ01000002']),
      },
      global: {
        stubs: {
          WorkCard: {
            props: ['selectionPulseIndex'],
            template: '<div class="work-card-stub" :data-pulse-index="selectionPulseIndex" />',
          },
          WorkListRow: { template: '<div />' },
          ElPagination: { template: '<div />' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.findAll('.work-card-stub').map(card => card.attributes('data-pulse-index'))).toEqual(['0', '1'])

    wrapper.unmount()
  })
})
