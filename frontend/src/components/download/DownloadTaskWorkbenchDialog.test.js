import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import DownloadTaskWorkbenchDialog from './DownloadTaskWorkbenchDialog.vue'

vi.mock('../../assets/anime/Uploading to cloud.lottie', () => ({ default: 'upload.lottie' }))
vi.mock('../../assets/anime/success confetti.lottie', () => ({ default: 'success.lottie' }))
vi.mock('../common/AppLottieProgressBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))

describe('下载任务 RJ 展示', () => {
  it.each([
    ['标题已是 RJ', { work_title: 'RJ01715445', rjcode: 'RJ01715445' }, ''],
    ['标题含 RJ 但字段为空', { work_title: 'RJ01715445' }, ''],
    ['压缩包文件名含 RJ', { download_files: [{ name: 'RJ01715445(south-plus).rar' }] }, 'RJ01715445'],
    ['分卷和小写编号', { task_metadata: { selected_resources: [{ file_name: '[rj123456].part1.rar' }, { relative_path: '[rj123456].part2.rar' }] } }, 'RJ123456'],
    ['多个不同 RJ 的合集', { download_files: [{ name: 'RJ01715445.rar' }, { name: 'RJ01434247.rar' }] }, ''],
    ['显式编号优先', { rjcode: 'RJ01715445', download_files: [{ name: 'RJ01434247.rar' }] }, 'RJ01715445'],
    ['没有编号', {}, ''],
    ['超长数字不截断为 RJ', { download_files: [{ name: 'RJ123456789.rar' }] }, ''],
  ])('%s', (_, fields, expected) => {
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [{ id: 'download', status: 'processing', work_title: '下载作品', ...fields }], mergeTasks: false },
      global: { stubs: { Teleport: true } },
    })
    expect(wrapper.find('.v1-task-rj').exists()).toBe(Boolean(expected))
    if (expected) expect(wrapper.get('.v1-task-rj').text()).toBe(expected)
    expect(wrapper.text()).not.toContain('未知 RJ')
    wrapper.unmount()
  })
})

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
describe('下载失败操作', () => {
  it.each(['failed', 'partial_failed'])('%s 没有会话和文件明细也能重试和关闭', async status => {
    const task = { id: 'download-one', status, error_message: '资源解析失败', progress: 0 }
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [task], mergeTasks: false },
      global: { stubs: { Teleport: true, DotLottieVue: true, AppLottieProgressBar: true } },
    })
    const retry = wrapper.findAll('button').find(button => button.text().includes('重试失败项'))
    expect(retry).toBeDefined()
    await retry.trigger('click')
    await wrapper.get('[aria-label=关闭任务]').trigger('click')
    expect(wrapper.emitted('retry-task')[0][0].id).toBe(task.id)
    expect(wrapper.emitted('dismiss-task')[0][0].id).toBe(task.id)
    expect(wrapper.emitted('cancel-task')).toBeUndefined()
    wrapper.unmount()
  })
})
