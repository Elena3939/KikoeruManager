import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'

const mocks = vi.hoisted(() => ({ list: vi.fn(), cancel: vi.fn(), retry: vi.fn(), confirm: vi.fn(), start: vi.fn(), stop: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn() }))
vi.mock('../../api', () => ({ deferredArchiveApi: mocks }))
vi.mock('../../composables/useSystemPrompt', () => ({ showSystemConfirm: mocks.confirm }))
vi.mock('../../composables/useRealtimeEvents', () => ({ useRealtimeEvents: () => ({ ...mocks, connected: ref(false) }) }))
import DeferredArchiveQueue from './DeferredArchiveQueue.vue'

const Button = defineComponent({
  inheritAttrs: false,
  props: ['onClick', 'disabled'],
  template: '<button v-bind="$attrs" :disabled="disabled" @click="run"><slot /></button>',
  methods: { async run() { try { await this.onClick?.() } catch {} } },
})
const global = { stubs: { StatefulButton: Button, AppDropdown: true } }
const job = (values = {}) => ({ job_id: 'one', status: 'pending', wait_reason: '等待系统空闲', source_summary: { filename: 'RJ123456.zip', source_path: '/input/RJ123456.zip', volume_count: 1, total_bytes: 7 }, can_cancel: true, ...values })
const payload = (items = []) => ({ items, total: items.length, pending_count: items.length, counts_by_status: {} })
let wrapper
let event
async function open(items = []) {
  mocks.list.mockResolvedValue(payload(items))
  wrapper = mount(DeferredArchiveQueue, { global })
  await vi.advanceTimersByTimeAsync(350)
  await flushPromises()
}
const button = (label) => wrapper.findAll('button').find((item) => item.text() === label)

describe('延后归档队列', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
    mocks.subscribe.mockImplementation((name, callback) => { event = callback; return mocks.unsubscribe })
    mocks.confirm.mockResolvedValue()
    mocks.cancel.mockResolvedValue({ status: 'cancelled' })
  })
  afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

  it('默认显示全部状态，连续队列事件只刷新一次', async () => {
    await open()
    expect(mocks.list.mock.calls[0][0].status).toBe('')
    event(); event(); event()
    await vi.advanceTimersByTimeAsync(349)
    expect(mocks.list).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.list).toHaveBeenCalledTimes(2)
  })

  it('切换筛选后，较晚返回的旧请求不能覆盖新结果', async () => {
    await open()
    let resolveOld
    mocks.list.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    event()
    await vi.advanceTimersByTimeAsync(350)
    const signal = mocks.list.mock.calls[1][1].signal
    mocks.list.mockResolvedValue(payload([job({ status: 'failed', last_error: '新的失败记录' })]))
    wrapper.findComponent({ name: 'AppDropdown' }).vm.$emit('update:modelValue', 'failed')
    await flushPromises()
    expect(signal.aborted).toBe(true)
    resolveOld(payload([job({ source_summary: { filename: '旧文件.zip' } })]))
    await flushPromises()
    expect(wrapper.text()).toContain('新的失败记录')
    expect(wrapper.text()).not.toContain('旧文件.zip')
  })

  it('KeepAlive 停用时取消请求和订阅，重新激活才继续刷新', async () => {
    const visible = ref(true)
    mocks.list.mockImplementation(() => new Promise(() => {}))
    wrapper = mount(defineComponent({ components: { DeferredArchiveQueue }, setup: () => ({ visible }), template: '<KeepAlive><DeferredArchiveQueue v-if="visible" /></KeepAlive>' }), { global })
    await vi.advanceTimersByTimeAsync(350)
    const signal = mocks.list.mock.calls[0][1].signal
    visible.value = false
    await nextTick()
    expect(signal.aborted).toBe(true)
    expect(mocks.unsubscribe).toHaveBeenCalledOnce()
    expect(mocks.stop).toHaveBeenCalledOnce()
    event()
    await vi.advanceTimersByTimeAsync(350)
    expect(mocks.list).toHaveBeenCalledOnce()
    visible.value = true
    await nextTick()
    await vi.advanceTimersByTimeAsync(350)
    expect(mocks.list).toHaveBeenCalledTimes(2)
  })

  it('取消操作失败原因不会被自动刷新清掉', async () => {
    await open([job()])
    mocks.cancel.mockRejectedValue({ response: { data: { detail: '已有分卷发布，不能取消归档' } } })
    await button('取消归档').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenCalledOnce()
    expect(mocks.cancel).toHaveBeenCalledWith('one')
    await vi.advanceTimersByTimeAsync(350)
    expect(wrapper.get('[role="alert"]').text()).toBe('已有分卷发布，不能取消归档')
  })

  it('拒绝确认不调用取消 API', async () => {
    await open([job()])
    mocks.confirm.mockRejectedValue('cancel')
    await button('取消归档').trigger('click')
    await flushPromises()
    expect(mocks.cancel).not.toHaveBeenCalled()
  })

  it('超时保护中仍优先显示取消请求，并隐藏不可用操作', async () => {
    await open([job({ status: 'processing', starvation_protected: true, cancel_requested: true, wait_reason: '取消已请求，等待安全停止', can_cancel: false })])
    expect(wrapper.text()).toContain('取消已请求，等待安全停止')
    expect(wrapper.text()).not.toContain('超时保护执行中')
    expect(button('取消归档')).toBeUndefined()
    expect(button('重新归档')).toBeUndefined()
  })

  it('读取失败显示原因，成功刷新后恢复', async () => {
    await open()
    mocks.list.mockRejectedValueOnce(new Error('读取超时'))
    event()
    await vi.advanceTimersByTimeAsync(350)
    expect(wrapper.get('[role="alert"]').text()).toBe('读取超时')
    await wrapper.get('button[aria-label="刷新归档队列"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('文件行复用压缩包图标，分页不命中全局蓝色背景规则', async () => {
    await open([job()])
    expect(wrapper.get('.deferred-archive-item .lucide-file-archive').classes()).toContain('text-amber-600')
    expect(wrapper.get('.queue-pager').classes()).not.toContain('border-slate-100')
    expect(wrapper.get('.queue-pager').classes()).not.toContain('border-slate-200')
  })

  it('图标分页保留页码、总数及首尾禁用状态', async () => {
    await open([job()])
    mocks.list.mockResolvedValue({ ...payload([job()]), total: 6 })
    await wrapper.get('button[aria-label="刷新归档队列"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('button[aria-label="上一页"]').element.disabled).toBe(true)
    expect(wrapper.get('.queue-page-indicator').text()).toBe('1 / 2')
    expect(wrapper.get('.queue-pager').text()).toContain('共 6 项')
    await wrapper.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(mocks.list.mock.lastCall[0].page).toBe(2)
    expect(wrapper.get('.queue-page-indicator').text()).toBe('2 / 2')
    expect(wrapper.get('button[aria-label="下一页"]').element.disabled).toBe(true)
    await wrapper.get('button[aria-label="上一页"]').trigger('click')
    await flushPromises()
    expect(mocks.list.mock.lastCall[0].page).toBe(1)
  })
})
