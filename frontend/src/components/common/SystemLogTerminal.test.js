import { afterEach, describe, expect, it } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import SystemLogTerminal from './SystemLogTerminal.vue'

describe('日志虚拟窗口记录身份', () => {
  let wrapper
  afterEach(() => wrapper?.unmount())

  it('固定条数窗口滑动后刷新测量缓存中的记录 key', async () => {
    const lines = (start) => Array.from({ length: 3 }, (_, index) => ({
      id: `app.log:${start + index}`, time: '2026-11-06 12:00:00', message: '日志',
    }))
    wrapper = shallowMount(SystemLogTerminal, { props: { lines: lines(0) } })
    const virtualizer = () => wrapper.vm.$.setupState.rowVirtualizer
    // 先读取测量数据，复现条数不变时仍命中旧缓存的情况。
    expect(virtualizer().getTotalSize()).toBe(96)
    const measuredKeys = () => [0, 32, 64].map(offset => virtualizer().getVirtualItemForOffset(offset).key)
    expect(measuredKeys()).toEqual(['app.log:0', 'app.log:1', 'app.log:2'])
    await wrapper.setProps({ lines: lines(1) })
    expect(virtualizer().getTotalSize()).toBe(96)
    expect(measuredKeys()).toEqual(['app.log:1', 'app.log:2', 'app.log:3'])
  })

  it('失败任务加载时不自动请求时间线，手动展开才请求', async () => {
    const line = {
      id: 'app.log:1', key: 'app.log:1', taskId: '12345678',
      message: '任务失败', taskProgress: { tone: 'error', status: 'failed', progress: 10 },
    }
    wrapper = shallowMount(SystemLogTerminal, { props: { lines: [line] } })
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('line-expand')).toBeUndefined()
    wrapper.vm.$.setupState.toggleLineDetail(line, 0, {})
    expect(wrapper.emitted('line-expand')).toEqual([[line]])
  })
})
