import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import DownloadTaskWorkbenchDialog from './DownloadTaskWorkbenchDialog.vue'

vi.mock('../../assets/anime/Uploading to cloud.lottie', () => ({ default: 'upload.lottie' }))
vi.mock('../../assets/anime/success confetti.lottie', () => ({ default: 'success.lottie' }))
vi.mock('../common/AppLottieProgressBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))

describe('HTTP 下载失败任务取消', () => {
  it.each(['failed', 'partial_failed'])('%s 状态即使没有文件明细也能取消', async (status) => {
    const task = { id: 'http-failed', status, task_domain: 'http_download', task_metadata: {} }
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [task], enableFailedCancel: true, mergeTasks: false },
      global: { stubs: { Teleport: true } },
    })
    await wrapper.get('button[aria-label="取消任务"]').trigger('click')
    expect(wrapper.emitted('cancel-task')[0][0].id).toBe(task.id)
    await wrapper.setProps({ tasks: [{ ...task, status: 'cancelled' }] })
    expect(wrapper.find('button[aria-label="取消任务"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('其它下载工作台默认不增加失败取消入口', () => {
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [{ id: 'failed', status: 'failed' }], mergeTasks: false },
      global: { stubs: { Teleport: true } },
    })
    expect(wrapper.find('button[aria-label="取消任务"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
