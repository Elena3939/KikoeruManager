import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { Archive } from 'lucide-vue-next'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  subscribe: vi.fn(),
  refreshArchives: vi.fn(),
}))
vi.mock('../../api', () => ({ deferredArchiveApi: mocks }))
vi.mock('../../composables/useRealtimeEvents', () => ({
  useRealtimeEvents: () => ({ ...mocks, connected: ref(false) }),
}))
vi.mock('../common/AppEmptyState.vue', () => ({
  default: { template: '<div>暂无归档记录</div>' },
}))
import DashboardArchive from './DashboardArchive.vue'

const Button = defineComponent({
  inheritAttrs: false,
  props: ['onClick', 'disabled'],
  template: '<button v-bind="$attrs" :disabled="disabled" @click="onClick"><slot name="prefix" state="idle" /><slot /></button>',
})
let wrapper

async function open() {
  wrapper = mount(DashboardArchive, {
    attachTo: document.body,
    props: {
      archives: [{ id: 1, filename: '任务归档记录' }],
      filteredArchives: [{ id: 1, filename: '任务归档记录' }],
      getMeta: () => ({ key: 'import', label: '解压入库', icon: Archive }),
      getStatusMeta: () => ({ key: 'completed', label: '已完成' }),
      formatDate: () => '',
      formatFileSize: () => '',
      refreshArchives: mocks.refreshArchives,
    },
    global: { stubs: { StatefulButton: Button, AppDropdown: true } },
  })
  await vi.advanceTimersByTimeAsync(350)
  await flushPromises()
}

const selectType = (index) => wrapper.findAll('.dash-archive-list-type')[index].trigger('click')

describe('首页归档中心', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
    mocks.subscribe.mockReturnValue(vi.fn())
    mocks.list.mockResolvedValue({
      items: [],
      total: 6,
      pending_count: 2,
      counts_by_status: { waiting_retry: 1 },
    })
  })
  afterEach(() => {
    wrapper?.unmount()
    vi.useRealTimers()
  })

  it('共享标题和刷新按钮，按列表类型显示对应内容', async () => {
    await open()
    expect(wrapper.findAll('header')).toHaveLength(1)
    expect(wrapper.get('h2').text()).toBe('归档中心')
    expect(wrapper.get('header').text()).toContain('2 项待归档 · 1 项等待重试')
    expect(wrapper.get('[data-section="deferred-archive-queue"]').isVisible()).toBe(true)
    expect(wrapper.get('.dash-archive-row').isVisible()).toBe(false)

    await selectType(1)
    expect(wrapper.get('[data-section="deferred-archive-queue"]').element.style.display).toBe('none')
    expect(wrapper.get('.dash-archive-row').isVisible()).toBe(true)
    expect(wrapper.get('header').text()).toContain('共 1 条记录')
    expect(wrapper.findAll('.dash-archive-list-type')[1].attributes('aria-pressed')).toBe('true')
  })

  it('切换列表保留压缩包队列的状态筛选和页码', async () => {
    await open()
    const queue = wrapper.getComponent({ name: 'DeferredArchiveQueue' })
    queue.getComponent({ name: 'AppDropdown' }).vm.$emit('update:modelValue', 'failed')
    await flushPromises()
    await queue.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(mocks.list.mock.lastCall[0]).toMatchObject({ status: 'failed', page: 2 })

    await selectType(1)
    await selectType(0)
    expect(queue.get('.queue-page-indicator').text()).toBe('2 / 2')
    expect(mocks.list).toHaveBeenCalledTimes(3)
    expect(queue.getComponent({ name: 'AppDropdown' }).props('modelValue')).toBe('failed')
  })

  it('顶部刷新只请求当前列表，并保留任务归档搜索事件', async () => {
    await open()
    await wrapper.get('button[aria-label="刷新压缩包队列"]').trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledTimes(2)
    expect(mocks.refreshArchives).not.toHaveBeenCalled()

    await selectType(1)
    await wrapper.get('button[aria-label="刷新任务归档"]').trigger('click')
    await flushPromises()
    expect(mocks.refreshArchives).toHaveBeenCalledOnce()
    expect(mocks.list).toHaveBeenCalledTimes(2)
    await wrapper.get('input[type="search"]').setValue('RJ123456')
    expect(wrapper.emitted('update:searchQuery')[0]).toEqual(['RJ123456'])
  })
})
