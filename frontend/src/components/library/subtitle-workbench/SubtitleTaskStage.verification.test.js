import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Stage from './SubtitleTaskStage.vue'
import { openVerificationPopup } from '../../../utils/browserVerificationPopup'
vi.mock('../../../utils/browserVerificationPopup', () => ({ openVerificationPopup: vi.fn().mockResolvedValue({}) }))
vi.mock('../../common/AppLoadingAnimation.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))
describe('库存字幕工作台验证入口', () => {
  it('等待验证的当前任务显示按钮并传递真实任务 ID', async () => {
    const task = { id: 'real-task', status: 'waiting_manual', task_metadata: { browser_verification_required: true } }
    const refresh = vi.fn()
    const wrapper = mount(Stage, { props: { mode: 'overview', immersive: true, ctx: { activeSubtitleTask: task, visibleSubtitleTasks: [task], refreshBrowserDownloadTasks: refresh } }, global: { stubs: { StatefulButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' } } } })
    const button = wrapper.findAll('button').find(button => button.text().includes('浏览器下载'))
    expect(button).toBeTruthy()
    expect(openVerificationPopup).not.toHaveBeenCalled()
    expect(wrapper.find('.el-dialog, browser-verification-dialog-stub').exists()).toBe(false)
    await button.trigger('click')
    await flushPromises()
    expect(openVerificationPopup).toHaveBeenCalledWith('real-task')
    expect(refresh).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
  it('普通任务不显示验证按钮', () => {
    const task = { id: 'normal', status: 'processing' }
    const wrapper = mount(Stage, { props: { mode: 'overview', immersive: true, ctx: { activeSubtitleTask: task, visibleSubtitleTasks: [task] } } })
    expect(wrapper.text()).not.toContain('浏览器下载')
    wrapper.unmount()
  })
})
