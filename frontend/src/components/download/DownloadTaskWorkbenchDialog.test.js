import { describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import DownloadTaskWorkbenchDialog from './DownloadTaskWorkbenchDialog.vue'

vi.mock('../../assets/anime/Uploading to cloud.lottie', () => ({ default: 'upload.lottie' }))
vi.mock('../../assets/anime/success confetti.lottie', () => ({ default: 'success.lottie' }))
vi.mock('../common/AppLottieProgressBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))

describe('下载与上传状态区分', () => {
  it.each([
    ['waiting_download_slot', '等待下载槽'],
    ['prepare_directory', '准备目录'],
    ['mkdir', '创建临时目录'],
    ['waiting_transfer_slot', '等待转存槽'],
    ['transferring', '转存中'],
    ['transfer_retry_wait', '等待转存重试'],
    ['waiting_network_budget', '等待网络预算'],
    ['starting_download', '启动下载'],
    ['transmitting', '实际传输'],
  ])('百度阶段 %s 使用真实运行态', (startup_phase, label) => {
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, mergeTasks: false, tasks: [{
        id: 'baidu', status: 'processing', task_domain: 'baidu_netdisk_download',
        task_metadata: { download_runtime: { startup_phase } },
      }] },
      global: { stubs: { Teleport: true, DotLottieVue: true } },
    })
    expect(wrapper.get('.v1-status-line').text()).toBe(label)
    wrapper.unmount()
  })

  it.each(['http_download', 'baidu_netdisk_upload'])('其它业务 %s 不采用百度启动阶段', task_domain => {
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, mergeTasks: false, tasks: [{
        id: 'other', status: 'processing', task_domain,
        task_metadata: { download_runtime: { startup_phase: 'transferring' } },
      }] },
      global: { stubs: { Teleport: true, DotLottieVue: true } },
    })
    expect(wrapper.get('.v1-status-line').text()).not.toBe('转存中')
    wrapper.unmount()
  })

  it('上传主窗口以实时字节为准，不采用缓存文件行的旧进度', async () => {
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, transferMode: 'upload', mergeTasks: false, tasks: [{
        id: 'upload', status: 'processing', progress: 11,
        upload_runtime: { total_bytes: 1000, transferred_bytes: 360, active_file_count: 1, speed_bytes_per_sec: 10 },
        upload_files: [{ relative_path: 'audio.mp3', size_bytes: 1000, uploaded: 110 }]
      }] },
      global: { stubs: { Teleport: true, DotLottieVue: true } },
    })
    await wrapper.get('.v1-task-card').trigger('click')
    expect(wrapper.get('.v1-summary-progress-text').text()).toBe('36%')
    expect(wrapper.get('.v1-task-meta').text()).toContain('上传 360 B / 1000 B')
    wrapper.unmount()
  })
  const downloadedFile = { name: '音声.zip', relative_path: '音声.zip', size_bytes: 1024, downloaded: 1024, progress: 100 }
  const completedTask = {
    id: 'download',
    status: 'completed',
    download_files: [downloadedFile],
    task_metadata: {
      download_root: '/temp/download',
      final_output_path: '/library/社团/作品',
    },
    progress_log: [{ message: '已入库到: /library/社团/作品' }],
  }
  const mountTask = (task, props = {}) => shallowMount(DownloadTaskWorkbenchDialog, {
    props: { visible: true, tasks: [task], ...props },
    global: { stubs: { Teleport: true, DotLottieVue: true } },
  })

  it.each([true, false])('本地整理入库不会被误认成上传，任务合并=%s', mergeTasks => {
    const wrapper = mountTask(completedTask, { mergeTasks })
    expect(wrapper.get('.v1-status-line').text()).toBe('已完成')
    expect(wrapper.get('.v1-task-meta').text()).toContain('下载大小 1.00 KB')
    expect(wrapper.get('.v1-task-meta').text()).not.toContain('上传')
    expect(wrapper.get('.v1-file-row').text()).not.toContain('上传')
    expect(wrapper.get('.v1-footer').text()).not.toContain('上传速度')
    wrapper.unmount()
  })

  it.each([
    { enabled: false, mode: 'local' },
    { mode: 'disabled' },
    { enabled: true, mode: 'disabled' },
  ])('明确关闭上传优先于旧上传记录和运行态：%j', uploadOptions => {
    const task = {
      ...completedTask,
      task_metadata: { ...completedTask.task_metadata, upload_options: uploadOptions },
      upload_files: [{ ...downloadedFile, uploaded: 512, progress: 50, speed_bytes_per_sec: 100 }],
      uploaded_files: [downloadedFile],
      upload_runtime: { active_file_count: 1, transferred_bytes: 512, speed_bytes_per_sec: 100 },
    }
    const wrapper = mountTask(task)
    expect(wrapper.get('.v1-task-meta').text()).not.toContain('上传')
    expect(wrapper.get('.v1-file-row').text()).not.toContain('上传')
    expect(wrapper.get('.v1-footer').text()).not.toContain('上传速度')
    wrapper.unmount()
  })

  it('关闭上传的进行中任务只计算下载进度', async () => {
    const wrapper = mountTask({
      ...completedTask,
      status: 'processing',
      download_files: [{ ...downloadedFile, progress: 50, downloaded: 512 }],
      task_metadata: { ...completedTask.task_metadata, upload_options: { enabled: false } },
      upload_runtime: { active_file_count: 1, is_waiting_turn: 1, current_relative_path: '音声.zip' },
    }, { mergeTasks: false })
    await wrapper.get('.v1-task-card').trigger('click')
    expect(wrapper.get('.v1-summary-progress-text').text()).toBe('50%')
    expect(wrapper.get('.v1-task-meta').text()).toContain('下载 512 B / 1.00 KB')
    expect(wrapper.get('.v1-task-meta').text()).not.toContain('上传')
    await wrapper.get('.v1-task-card').trigger('click')
    expect(wrapper.get('.v1-file-row').text()).not.toContain('上传')
    wrapper.unmount()
  })

  it.each([
    { task_metadata: { ...completedTask.task_metadata, upload_options: { enabled: true, mode: 'synology' } } },
    { uploaded_files: [downloadedFile] },
  ])('真实上传及有实际上传记录的旧任务保留上传文案', fields => {
    const wrapper = mountTask({ ...completedTask, ...fields })
    expect(wrapper.get('.v1-status-line').text()).toBe('已上传 / 已入库')
    expect(wrapper.get('.v1-task-meta').text()).toContain('上传 1.00 KB / 1.00 KB')
    expect(wrapper.get('.v1-file-row').text()).toContain('已上传')
    expect(wrapper.get('.v1-footer').text()).toContain('上传速度')
    wrapper.unmount()
  })

  it('独立上传工作台继续使用上传模式', () => {
    const wrapper = mountTask({
      ...completedTask,
      upload_files: [{ ...downloadedFile, uploaded: 1024 }],
    }, { transferMode: 'upload', mergeTasks: false })
    expect(wrapper.get('.v1-status-line').text()).toBe('已上传 / 已入库')
    expect(wrapper.get('.v1-task-meta').text()).toContain('上传 1.00 KB / 1.00 KB')
    wrapper.unmount()
  })
})

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
  it.each(['failed', 'partial_failed'])('%s 关闭等待清理，期间禁用重试及重复关闭', async status => {
    let finish
    const cleanupFailedTask = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [{ id: 'failed', status }], mergeTasks: false, cleanupFailedTask },
      global: { stubs: { Teleport: true, StatefulButton: { template: '<button><slot /></button>' } } },
    })
    const close = wrapper.get('[aria-label=关闭任务]')
    expect(close.attributes('title')).toBe('关闭任务并删除下载缓存')
    await close.trigger('click')
    expect(cleanupFailedTask).toHaveBeenCalledOnce()
    expect(close.attributes('disabled')).toBeDefined()
    expect(wrapper.get('button.retry').attributes('disabled')).toBeDefined()
    await close.trigger('click')
    expect(cleanupFailedTask).toHaveBeenCalledOnce()
    finish(false)
    await flushPromises()
    expect(close.attributes('disabled')).toBeUndefined()
    expect(wrapper.emitted('dismiss-task')).toBeUndefined()
    wrapper.unmount()
  })

  it('成功关闭仍保留任务和文件', async () => {
    const cleanupFailedTask = vi.fn()
    const wrapper = shallowMount(DownloadTaskWorkbenchDialog, {
      props: { visible: true, tasks: [{ id: 'completed', status: 'completed' }], mergeTasks: false, cleanupFailedTask },
      global: { stubs: { Teleport: true } },
    })
    const close = wrapper.get('[aria-label=关闭任务]')
    expect(close.attributes('title')).toBe('从当前工作台关闭，保留任务与文件')
    await close.trigger('click')
    expect(cleanupFailedTask).not.toHaveBeenCalled()
    expect(wrapper.emitted('dismiss-task')[0][0].id).toBe('completed')
    wrapper.unmount()
  })

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
