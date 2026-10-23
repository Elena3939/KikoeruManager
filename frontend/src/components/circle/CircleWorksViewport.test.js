import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CircleWorksViewport from './CircleWorksViewport.vue'

function mountViewport(options) {
  const items = options.props.items
  const originals = new Map(items.filter(item => !item.is_bonus_work).map(item => [item.canonical_rjcode, item]))
  for (const item of items) {
    if (!item.is_bonus_work) continue
    const parent = (item.linked_rjcodes || []).map(code => originals.get(code)).find(Boolean)
    if (parent) {
      parent.bonus_works ||= []
      parent.bonus_works.push(item)
    }
  }
  options.props.items = items.filter(item => !item.is_bonus_work || !(item.linked_rjcodes || []).some(code => originals.has(code)))
  for (const item of options.props.items) {
    item.bonus_display_works = (item.bonus_works || []).filter(bonus => bonus.dlsite_cover_available !== false && !bonus.cover_confirmed_missing)
  }
  return mount(CircleWorksViewport, options)
}

const originalResizeObserver = globalThis.ResizeObserver
const originalRequestAnimationFrame = globalThis.requestAnimationFrame
const originalCancelAnimationFrame = globalThis.cancelAnimationFrame
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
let mockClientWidth = 600
let mockClientHeight = 600

describe('CircleWorksViewport', () => {
  beforeAll(() => {
    // 确定性执行图片调度帧，避免 flushPromises 早于浏览器的下一帧。
    let frameId = 0
    const frames = new Map()
    globalThis.requestAnimationFrame = callback => {
      const id = ++frameId
      frames.set(id, callback)
      queueMicrotask(() => {
        if (!frames.has(id)) return
        frames.delete(id)
        callback(0)
      })
      return id
    }
    globalThis.cancelAnimationFrame = id => frames.delete(id)
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
    globalThis.requestAnimationFrame = originalRequestAnimationFrame
    globalThis.cancelAnimationFrame = originalCancelAnimationFrame
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
    const wrapper = mountViewport({
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
    const wrapper = mountViewport({
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

  it('展示后端已去重且有封面的特典成员', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mountViewport({
      props: {
        imageField: 'thumb_image_url',
        items: [
          {
            canonical_rjcode: 'RJ01708868',
            display_rjcode: 'RJ01708868',
            title: '原作',
            bonus_works: [
              {
                canonical_rjcode: 'RJ01708876',
                display_rjcode: 'RJ01708876',
                title: '期间限定特典',
                is_bonus_work: true,
                cover_available: true,
                thumb_image_url: '/api/circle-completion/cover/RJ01708876_sam.jpg',
                image_url: '/api/circle-completion/cover/RJ01708876.jpg',
              },
            ],
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

    expect(wrapper.find('.circle-bonus-gift').exists()).toBe(true)
    expect(wrapper.get('.circle-bonus-gift').attributes('title')).toBe('期间限定特典')

    wrapper.unmount()
  })

  it.each([true, false])('同名特典保留有图 RJ，封面已验证：%s', async (confirmed) => {
    mockClientWidth = 600
    mockClientHeight = 600
    const bonuses = ['RJ01739773', 'RJ01739750'].map(code => ({
      canonical_rjcode: code,
      display_rjcode: code,
      title: '早期購入特典',
      is_bonus_work: true,
      cover_available: true,
      cover_confirmed_available: confirmed && code === 'RJ01739750',
      image_url: `/api/circle-completion/cover/${code}.jpg`,
      thumb_image_url: `/api/circle-completion/cover/${code}_sam.jpg`,
    }))
    const wrapper = mountViewport({
      props: {
        imageField: 'thumb_image_url',
        items: [{ canonical_rjcode: 'RJ01726963', title: '原作', bonus_works: [{ ...bonuses[confirmed ? 1 : 0], _bonus_members: confirmed ? [bonuses[1]] : bonuses }] }],
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
    if (!confirmed) {
      const image = wrapper.get('.circle-bonus-gift-cover img')
      expect(image.attributes('src')).toContain('RJ01739773')
      await image.trigger('error')
      await image.trigger('error')
      await flushPromises()
    }
    expect(wrapper.get('.circle-bonus-gift-cover img').attributes('src')).toContain('RJ01739750')
    await wrapper.get('.circle-bonus-gift').trigger('click')
    await flushPromises()
    expect(wrapper.get('.circle-bonus-detail-cover img').attributes('src')).toContain('RJ01739750')
    wrapper.unmount()
  })

  it('只展示后端提供的特典标题', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mountViewport({
      props: {
        items: [{
          canonical_rjcode: 'RJ01529215',
          display_rjcode: 'RJ01529215',
          title: '原作',
          bonus_works: [
            {
              canonical_rjcode: 'RJ01549463',
              display_rjcode: 'RJ01549463',
              title: '【早期限定415大特典】',
              is_bonus_work: true,
            },
          ],
        }],
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

    const bonusRows = wrapper.findAll('.circle-bonus-gift')
    expect(bonusRows).toHaveLength(1)
    expect(bonusRows[0].attributes('title')).toBe('【早期限定415大特典】')

    wrapper.unmount()
  })

  it('无封面但不是编号脏数据的特典仍挂在本体卡片上', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mountViewport({
      props: {
        items: [
          {
            canonical_rjcode: 'RJ01647392',
            display_rjcode: 'RJ01647392',
            title: '原作',
            owned: true,
            bonus_works: [
              {
                canonical_rjcode: 'RJ01657211',
                display_rjcode: 'RJ01657211',
                title: '早期購入限定500大特典',
                is_bonus_work: true,
                cover_available: false,
              },
            ],
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

    expect(wrapper.find('.circle-bonus-gift').exists()).toBe(true)
    expect(wrapper.find('.circle-bonus-gift-cover img').exists()).toBe(false)

    wrapper.unmount()
  })

  it('DLsite 官方无封面的特典不显示', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mountViewport({
      props: {
        items: [{
          canonical_rjcode: 'RJ01647392',
          display_rjcode: 'RJ01647392',
          title: '原作',
          bonus_works: [{
            canonical_rjcode: 'RJ01715445',
            display_rjcode: 'RJ01715445',
            title: '早期限定340大特典',
            is_bonus_work: true,
            cover_available: true,
            dlsite_cover_available: false,
            image_url: '/api/circle-completion/cover/RJ01715445.jpg',
          }],
        }],
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

    expect(wrapper.find('.circle-bonus-gift').exists()).toBe(false)
    expect(wrapper.find('.circle-bonus-gift-cover img').exists()).toBe(false)
    wrapper.unmount()
  })

  it('确认不存在官方封面的特典不显示', async () => {
    const wrapper = mountViewport({
      props: {
        items: [{
          canonical_rjcode: 'RJ01647392',
          title: '原作',
          bonus_works: [{
            canonical_rjcode: 'RJ01657211',
            display_rjcode: 'RJ01657211',
            title: '早期購入限定500大特典',
            is_bonus_work: true,
            cover_confirmed_missing: true,
          }],
        }],
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
    expect(wrapper.find('.circle-bonus-gift').exists()).toBe(false)
    expect(wrapper.find('.circle-bonus-gift-cover img').exists()).toBe(false)
    wrapper.unmount()
  })

  it('本体已收录但特典未收录时将特典卡置灰', async () => {
    mockClientWidth = 600
    mockClientHeight = 600
    const wrapper = mountViewport({
      props: {
        items: [{
          canonical_rjcode: 'RJ01647392',
          display_rjcode: 'RJ01647392',
          title: '原作',
          owned: true,
          bonus_works: [{
            canonical_rjcode: 'RJ01715445',
            display_rjcode: 'RJ01715445',
            title: '早期限定340大特典',
            is_bonus_work: true,
            owned: false,
            cover_available: true,
          }],
        }],
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

    expect(wrapper.get('.circle-bonus-gift').classes()).toContain('is-dimmed')

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
    const wrapper = mountViewport({
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
    const wrapper = mountViewport({
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
