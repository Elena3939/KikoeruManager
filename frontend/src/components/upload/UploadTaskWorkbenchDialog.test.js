import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import UploadTaskWorkbenchDialog from './UploadTaskWorkbenchDialog.vue'

vi.mock('../../assets/anime/Uploading to cloud.lottie', () => ({ default: 'upload.lottie' }))
vi.mock('../../assets/anime/success confetti.lottie', () => ({ default: 'success.lottie' }))
vi.mock('../common/AppLottieProgressBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))

describe('上传工作台共享任务详情', () => {
  it('取消任务在折叠态显示已取消，停止进度动画，并转发单条关闭', async () => {
    const wrapper = mount(UploadTaskWorkbenchDialog, {
      props: { visible: true, dismissible: true, tasks: [{ id: 'cancelled-upload', status: 'cancelled', source_path: '/来源' }] },
      global: { stubs: { Teleport: true, DotLottieVue: true } },
    })
    expect(wrapper.get('.v1-status-line').text()).toBe('已取消')
    expect(wrapper.find('.v1-summary-progress').exists()).toBe(false)
    expect(wrapper.find('.v1-task-icon-lottie').exists()).toBe(false)
    await wrapper.get('button[aria-label="关闭任务"]').trigger('click')
    expect(wrapper.emitted('dismiss-task')[0][0].id).toBe('cancelled-upload')
    wrapper.unmount()
  })
  it('自定义文件详情仍参与搜索、筛选和折叠', async () => {
    const wrapper = mount(UploadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [
        { id: 'active', status: 'processing', source_path: '/来源甲', task_metadata: { source_label: '来源甲' } },
        { id: 'done', status: 'completed', source_path: '/来源乙', task_metadata: { source_label: '来源乙' } },
      ] },
      slots: { 'task-detail': ({ task }) => `文件明细 ${task.id}` },
      global: { stubs: { Teleport: true, DotLottieVue: true } },
    })
    expect(wrapper.findAll('.v1-task-card')).toHaveLength(2)
    await wrapper.get('.v1-task-card').trigger('click')
    expect(wrapper.text()).toContain('文件明细 active')
    await wrapper.get('.v1-task-card').trigger('click')
    expect(wrapper.text()).not.toContain('文件明细 active')
    await wrapper.get('input[placeholder="搜索任务..."]').setValue('来源乙')
    expect(wrapper.findAll('.v1-task-card')).toHaveLength(1)
    expect(wrapper.get('.v1-task-card').text()).toContain('来源乙')
    await wrapper.get('input[placeholder="搜索任务..."]').setValue('')
    const completedTab = wrapper.findAll('button').find(button => button.text().startsWith('已完成'))
    await completedTab.trigger('click')
    expect(wrapper.findAll('.v1-task-card')).toHaveLength(1)
    expect(wrapper.get('.v1-task-card').text()).toContain('来源乙')
    wrapper.unmount()
  })
})
