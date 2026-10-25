import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BackgroundFloatingCard from './BackgroundFloatingCard.vue'
vi.mock('@lottiefiles/dotlottie-vue', () => ({ DotLottieVue: { props: ['src', 'autoplay', 'loop'], template: '<div class="completion-player" />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/library', query: {} }) }))

let wrapper
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('PointerEvent', class extends MouseEvent { constructor(type, options = {}) { super(type, options); this.pointerId = options.pointerId } })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

describe('后台任务小窗', () => {
  it('展示真实进度与统计，关闭和恢复沿用原事件', async () => {
    wrapper = mount(BackgroundFloatingCard, { props: { title: '下载任务', percentage: 39, metrics: [{ key: 'processing', label: '进行中', value: 3 }], actions: [{ key: 'close', label: '关闭' }, { key: 'resume', label: '恢复工作台' }] } })
    expect(wrapper.get('[role=progressbar]').attributes('aria-valuenow')).toBe('39')
    expect(wrapper.text()).toContain('进行中 3')
    await wrapper.get('.task-toast-dismiss').trigger('click')
    await wrapper.get('.task-toast-action').trigger('click')
    expect(wrapper.emitted('action')).toEqual([['close'], ['resume']])
  })

  it('折叠后只留进度条，持续更新且展开不会关闭任务', async () => {
    wrapper = mount(BackgroundFloatingCard, { props: { percentage: 39, title: '下载任务', metrics: [{ key: 'failed', label: '失败', value: 0 }], actions: [{ key: 'resume', label: '恢复工作台' }] } })
    expect(wrapper.find('.task-toast-metrics').exists()).toBe(false)
    await wrapper.get('.task-toast-collapse').trigger('click')
    expect(wrapper.classes()).toContain('is-collapsed')
    expect(wrapper.get('.task-toast-mini-name').text()).toBe('下载任务')
    expect(wrapper.find('.task-toast-mini-logo svg').exists()).toBe(true)
    expect(wrapper.get('.task-toast-mini-percent').text()).toBe('39%')
    expect(wrapper.find('.task-toast-head').exists()).toBe(false)
    expect(wrapper.find('.task-toast-actions').exists()).toBe(false)
    expect(wrapper.emitted('action')).toBeUndefined()
    await wrapper.setProps({ percentage: 72 })
    expect(wrapper.get('[role=progressbar]').attributes('aria-valuenow')).toBe('72')
    expect(wrapper.get('.task-toast-mini-percent').text()).toBe('72%')
    await wrapper.get('.task-toast-mini-expand').trigger('click')
    expect(wrapper.find('.task-toast-head').exists()).toBe(true)
    await wrapper.get('.task-toast-action').trigger('click')
    expect(wrapper.emitted('action')).toEqual([['resume']])
  })

  it('完成态收起进度条，保留统计和工作台入口', () => {
    wrapper = mount(BackgroundFloatingCard, { props: { completed: true, actions: [{ key: 'resume', label: '查看结果' }] } })
    expect(wrapper.find('[role=progressbar]').exists()).toBe(false)
    expect(wrapper.find('.task-toast-icon.is-success').exists()).toBe(true)
    expect(wrapper.find('.task-toast-success-animation').exists()).toBe(true)
    expect(wrapper.text()).toContain('查看结果')
  })

  it('统计与后端速度元信息同时显示，折叠只隐藏元信息', async () => {
    wrapper = mount(BackgroundFloatingCard, { props: { title: '下载任务', metaText: '总进度: 39% · 当前速度: 12 MB/s', metrics: [{ key: 'processing', label: '进行中', value: 2 }] } })
    expect(wrapper.text()).toContain('进行中 2')
    expect(wrapper.get('.task-toast-meta').text()).toContain('12 MB/s')
    await wrapper.get('.task-toast-collapse').trigger('click')
    expect(wrapper.find('.task-toast-meta').exists()).toBe(false)
    expect(wrapper.find('.task-toast-mini-logo').exists()).toBe(true)
    await wrapper.setProps({ completed: true, percentage: 100 })
    expect(wrapper.find('.task-toast-mini-logo .completion-player').exists()).toBe(true)
    expect(wrapper.get('.task-toast-mini-percent').text()).toBe('100%')
  })

  it('拖动限制边界并记住位置，按钮不会触发拖动', async () => {
    wrapper = mount(BackgroundFloatingCard, { props: { positionKey: 'drag-test', actions: [{ key: 'close', label: '关闭' }] } })
    const card = wrapper.element
    expect(card.style.overflowX).toBe('hidden')
    expect(card.style.overflowY).toBe('hidden')
    vi.spyOn(card, 'getBoundingClientRect').mockImplementation(() => ({ left: parseFloat(card.style.left) || 0, top: parseFloat(card.style.top) || 0, width: 440, height: 230 }))
    const header = wrapper.get('.task-toast-head')
    wrapper.get('.task-toast-dismiss').element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, pointerId: 1, clientX: 5, clientY: 5 }))
    expect(card.classList.contains('is-dragging')).toBe(false)
    header.element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, pointerId: 1, clientX: 50, clientY: 50 }))
    window.dispatchEvent(new PointerEvent('pointermove', { pointerId: 1, clientX: -2000, clientY: -2000 }))
    expect(card.style.left).toBe('12px')
    expect(card.style.top).toBe('12px')
    window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 }))
    expect(JSON.parse(localStorage.getItem('kikoerumanager.ui.floatingPosition.drag-test'))).toEqual({ x: 12, y: 12 })
    card.style.left = '5000px'
    card.style.top = '5000px'
    window.dispatchEvent(new Event('resize'))
    expect(parseFloat(card.style.left) + 440).toBeLessThanOrEqual(window.innerWidth - 12)
    expect(parseFloat(card.style.top) + 230).toBeLessThanOrEqual(window.innerHeight - 12)
  })
})
