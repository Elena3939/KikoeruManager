import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import Logs from './Logs.vue'
import { TASK_PROGRESS_PREFIX } from '../utils/logProgress'
import { getTaskDomainMeta } from '../components/common/taskDomainMeta'
import { getHttpDownloadDisplayMeta, HTTP_DOWNLOAD_PLATFORM_META } from '../components/common/httpDownloadPlatformMeta'

vi.mock('../api', () => ({
  logApi: { streamUrl: vi.fn(() => '/api/logs/stream'), get: vi.fn() },
  taskCenterApi: { overview: vi.fn(async () => ({ active_items: [] })) },
  redirectIfSecurityGateExpired: vi.fn(),
}))
vi.mock('../composables/useRealtimeEvents', () => ({ useRealtimeEvents: () => ({ start: vi.fn(), stop: vi.fn(), subscribe: vi.fn() }) }))
vi.mock('../components/common/AppLottieIcon.vue', () => ({ default: { template: '<span />' } }))
vi.mock('../assets/anime/Delete icon animation.lottie', () => ({ default: '' }))

describe('日志 SSE 到进度卡片的完整解析链路', () => {
  let wrapper
  afterEach(() => {
    wrapper?.unmount()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('重试显示本轮阶段和公共图标，按动作展示 MB/s，两个分栏独立收起', async () => {
    vi.stubGlobal('EventSource', class {
      addEventListener() {}
      close() {}
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({
      engine_task_id: 'extract', domain: 'import', task_type: 'auto_process',
      status: 'processing', kind_label: '解压失败', current_step: '准备解压',
      retry_from_conflicts: true,
    })
    expect(state.activeTasks[0]).toMatchObject({ phase: '准备', retrying: true, hasSpeed: false, hasBytes: false })
    expect(state.activeTasks[0].icon).toBe(getTaskDomainMeta('import').icon)
    await nextTick()
    expect(wrapper.find('[data-task-id="extract"] .logs-active-details').exists()).toBe(false)
    expect(wrapper.find('[data-task-id="extract"]').text()).not.toContain('解压失败')
    expect(wrapper.find('.logs-active-retry').text()).toBe('重试')
    state.updateActiveTask({
      engine_task_id: 'extract', current_step: '解压中',
      io_runtime: { phase: 'extract', speed_kind: 'read', io_active: true, speed_bytes_per_sec: 2 * 1024 ** 2, completed_bytes: 8 * 1024 ** 2 },
    })
    state.updateActiveTask({
      engine_task_id: 'download', task_type: 'http_download', status: 'processing',
      runtime: { speed_bytes_per_sec: 1024 ** 2, transferred_bytes: 1024 ** 3, total_bytes: 2 * 1024 ** 3 },
    })
    await nextTick()
    expect(wrapper.find('[data-task-id="extract"] .logs-active-speed').text()).toBe('解压 2.00 MB/s')
    expect(wrapper.find('[data-task-id="download"]').text()).toContain('1.00 GB')
    await wrapper.find('.is-transfer .logs-active-toggle').trigger('click')
    expect(wrapper.find('.is-transfer .logs-active-list').isVisible()).toBe(false)
    expect(wrapper.find('.is-system .logs-active-list').isVisible()).toBe(true)
    state.updateActiveTask({
      engine_task_id: 'extract', current_step: '读取元数据',
      io_runtime: { io_active: false, speed_bytes_per_sec: null },
    })
    await nextTick()
    expect(wrapper.find('[data-task-id="extract"] .logs-active-details').exists()).toBe(false)
    state.updateActiveTask({
      engine_task_id: 'extract', current_step: '移动文件',
      io_runtime: { phase: 'move', speed_kind: 'move', io_active: true, speed_bytes_per_sec: 3 * 1024 ** 2 },
    })
    await nextTick()
    expect(wrapper.find('[data-task-id="extract"] .logs-active-speed').text()).toBe('移动 3.00 MB/s')
    state.updateActiveTask({
      engine_task_id: 'extract', current_step: '上传文件',
      io_runtime: { io_active: false, speed_bytes_per_sec: null },
      upload_runtime: { speed_bytes_per_sec: 4 * 1024 ** 2, eta_seconds: 12 },
    })
    await nextTick()
    expect(wrapper.find('[data-task-id="extract"] .logs-active-speed').text()).toBe('上传 4.00 MB/s')
    state.updateActiveTask({ engine_task_id: 'extract', current_step: '校验文件', runtime: { eta_seconds: 12 } })
    expect(state.activeTasks.find(task => task.id === 'extract').eta).toBeNull()
    expect(state.activeTasks.find(task => task.id === 'extract').hasSpeed).toBe(false)
  })

  it('明确的新一轮开始时间允许同 ID 重试，迟到的旧快照仍被阻止', async () => {
    vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
    wrapper = shallowMount(Logs, { global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } } })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({ id: 'retry', status: 'processing', started_at: '2026-11-09T10:00:00' })
    state.updateActiveTask({ id: 'retry', status: 'failed' })
    state.updateActiveTask({ id: 'retry', status: 'processing', started_at: '2026-11-09T10:00:00' })
    expect(state.activeTasks[0].finished).toBe(true)
    state.updateActiveTask({ id: 'retry', status: 'processing', started_at: '2026-11-09T10:01:00', retry_count: 1 })
    expect(state.activeTasks[0]).toMatchObject({ finished: false, retrying: true })
  })

  it('所有下载平台复用任务中心图标，进度增量保留来源', async () => {
    vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
    wrapper = shallowMount(Logs, { global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } } })
    const state = wrapper.vm.$.setupState
    for (const platform of Object.values(HTTP_DOWNLOAD_PLATFORM_META)) {
      const event = {
        id: platform.key, domain: 'http_download', task_type: 'http_download',
        status: 'processing', source_modes: [platform.key],
      }
      state.updateActiveTask(event)
      state.updateActiveTask({ id: platform.key, progress: 30 })
      const task = state.activeTasks.find(item => item.id === platform.key)
      const shared = getHttpDownloadDisplayMeta(event)
      expect(task).toMatchObject({
        sourceKey: shared.key, sourceIcon: shared.iconSrc, sourceName: shared.iconLabel,
      })
      expect(task.icon).toBe(getTaskDomainMeta('http_download').icon)
    }
    await nextTick()
    const megaIcon = wrapper.find('[data-task-id="mega"] .logs-active-source-icon')
    expect(megaIcon.attributes('src')).toContain('mega.ico')
    expect(megaIcon.attributes('alt')).toBe('Mega')
    expect(wrapper.find('[data-task-id="http"] .logs-active-source-icon').exists()).toBe(false)
    state.updateActiveTask({
      id: 'extract-platform-name', domain: 'import', task_type: 'auto_process',
      status: 'processing', title: 'Mega 下载文件.zip',
    })
    expect(state.activeTasks.find(task => task.id === 'extract-platform-name').sourceIcon).toBe('')
  })

  it('任务详情中的下载模式及混合平台使用公共解析结果', () => {
    vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
    wrapper = shallowMount(Logs, { global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } } })
    const state = wrapper.vm.$.setupState
    const events = [
      {
        id: 'metadata-platform', domain: 'http_download', status: 'processing',
        details: { metadata: { download_mode: 'mega.nz' } },
      },
      {
        id: 'mixed-platform', domain: 'http_download', status: 'processing',
        source_modes: ['gofile', 'mega'],
      },
    ]
    for (const event of events) {
      state.updateActiveTask(event)
      state.updateActiveTask({ id: event.id, progress: 50 })
      const shared = getHttpDownloadDisplayMeta(event)
      expect(state.activeTasks.find(task => task.id === event.id)).toMatchObject({
        sourceIcon: shared.iconSrc, sourceName: shared.iconLabel, sourcePlatforms: shared.platforms,
      })
    }
  })

  it('首次历史和增量事件均使用后端状态，100% 处理态不会提前完成', async () => {
    vi.useFakeTimers()
    let stream
    vi.stubGlobal('EventSource', class {
      handlers = {}
      constructor() { stream = this }
      addEventListener(name, handler) { this.handlers[name] = handler }
      close() {}
      emit(name, logs, offset) {
        this.handlers[name]({ data: JSON.stringify({ logs, next_offset: offset }) })
      }
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const line = (status, progress, step) => '2026-10-22 16:00:00 [INFO] app.core.task_engine - '
      + TASK_PROGRESS_PREFIX + JSON.stringify({
        version: 1, task_id: 'task-1234', status, progress, step, phase: '下载',
      })
    const padding = Array.from({ length: 50 }, (_, index) => `普通日志 ${index}`)
    stream.emit('connected', [...padding, line('processing', 37, '文字进度 100%')], 100)
    await nextTick()
    const cards = () => wrapper.findComponent({ name: 'SystemLogTerminal' })
      .props('lines').filter(row => row.taskProgress)
    expect(cards()).toHaveLength(1)
    expect(cards()[0].progress).toBe(37)
    expect(cards()[0].taskProgress.tone).toBe('processing')

    stream.emit('log', [line('processing', 100, '下载完成，失败 0 个，等待后处理')], 200)
    await vi.advanceTimersByTimeAsync(160)
    expect(cards()).toHaveLength(2)
    expect(cards()[1].progress).toBe(100)
    expect(cards()[1].taskProgress.tone).toBe('processing')

    stream.emit('log', [line('completed', 100, '下载完成，成功 1 个，失败 0 个')], 300)
    await vi.advanceTimersByTimeAsync(160)
    expect(cards()).toHaveLength(3)
    expect(cards()[2].taskProgress.tone).toBe('success')
    expect(cards()[2].taskProgress.active).toBe(false)
  })

  it('交替更新保持顺序和来源，缺少 ETA 时按真实字节计算，零速度显示未知', async () => {
    vi.stubGlobal('EventSource', class {
      addEventListener() {}
      close() {}
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({
      engine_task_id: 'baidu', task_type: 'baidu_netdisk_download', status: 'processing',
      progress: 40, runtime: { transferred_bytes: 4000, total_bytes: 10000, speed_bytes_per_sec: 2000 },
    })
    state.updateActiveTask({ engine_task_id: 'second', status: 'processing', progress: 10 })
    state.updateActiveTask({ engine_task_id: 'baidu', status: 'processing', progress: 50 })
    expect(state.activeTasks.map(task => task.id)).toEqual(['baidu', 'second'])
    expect(state.activeTasks[0]).toMatchObject({ eta: 3, sourceName: '百度网盘' })
    expect(state.activeTasks[0].sourceIcon).toContain('baidu-netdisk.ico')
    state.updateActiveTask({ engine_task_id: 'baidu', runtime: { speed_bytes_per_sec: 0 } })
    expect(state.activeTasks[0].eta).toBeNull()
    state.updateActiveTask({
      engine_task_id: 'second', task_type: 'http_download', source_modes: ['pikpak'],
      runtime: { speed_bytes_per_sec: 100, eta_seconds: 9 },
    })
    expect(state.activeTasks[1]).toMatchObject({ sourceName: 'PikPak', eta: 9 })
    state.updateActiveTask({
      engine_task_id: 'second', runtime: { total_bytes: 20000, transferred_bytes: 10000, speed_bytes_per_sec: 1000 },
    })
    expect(state.activeTasks[1].eta).toBe(10)
  })

  it('从上传元信息显示 ETA，并阻止完成任务被迟到的活动快照复活', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', class {
      addEventListener() {}
      close() {}
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({
      engine_task_id: 'upload-metadata', task_type: 'browser_upload', status: 'processing',
      details: { metadata: { upload_runtime: { eta_seconds: 42 } } },
    })
    expect(state.activeTasks[0].eta).toBe(42)
    state.updateActiveTask({
      engine_task_id: 'upload-performance', task_type: 'browser_upload', status: 'processing',
      performance_metrics: { upload_runtime: { eta_seconds: 24 } },
    })
    expect(state.activeTasks[1].eta).toBe(24)

    state.updateActiveTask({ engine_task_id: 'upload-metadata', status: 'completed', progress: 100 })
    expect(state.activeTasks[0]).toMatchObject({ finished: true, eta: null })
    await vi.advanceTimersByTimeAsync(5000)
    expect(state.activeTasks.map(task => task.id)).not.toContain('upload-metadata')

    state.updateActiveTask({
      engine_task_id: 'upload-metadata', status: 'processing', progress: 12,
      runtime: { speed_bytes_per_sec: 100, eta_seconds: 90 },
    })
    expect(state.activeTasks.map(task => task.id)).not.toContain('upload-metadata')
  })

  it('失败不会显示完成，重复结束事件不延长五秒保留期', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', class {
      addEventListener() {}
      close() {}
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({ engine_task_id: 'failed', status: 'processing', progress: 40 })
    state.updateActiveTask({ engine_task_id: 'failed', status: 'failed' })
    expect(state.activeTasks[0]).toMatchObject({ finished: true, failed: true, speed: 0 })
    await vi.advanceTimersByTimeAsync(4000)
    state.updateActiveTask({ engine_task_id: 'failed', status: 'failed' })
    await vi.advanceTimersByTimeAsync(1000)
    expect(state.activeTasks).toHaveLength(0)
  })

  it('把传输任务与系统任务分到左右两栏', () => {
    vi.stubGlobal('EventSource', class {
      addEventListener() {}
      close() {}
    })
    wrapper = shallowMount(Logs, {
      global: { stubs: { ElSelect: true, ElOption: true, ElDialog: true } },
    })
    const state = wrapper.vm.$.setupState
    state.updateActiveTask({ engine_task_id: 'download', task_type: 'http_download', status: 'processing', progress: 20 })
    state.updateActiveTask({ engine_task_id: 'upload', task_type: 'browser_upload', status: 'processing', progress: 30 })
    state.updateActiveTask({ engine_task_id: 'extract', task_type: 'extract', status: 'processing', progress: 40 })
    state.updateActiveTask({ engine_task_id: 'move', task_type: 'library_move_archive', status: 'processing', progress: 50 })
    state.updateActiveTask({
      engine_task_id: 'circle-download', domain: 'circle_completion', kind: 'asmr_sync_download',
      status: 'processing', progress: 60,
    })
    expect(state.taskLanes[0].tasks.map(task => task.id)).toEqual(['download', 'upload', 'circle-download'])
    expect(state.taskLanes[1].tasks.map(task => task.id)).toEqual(['extract', 'move'])
  })
})
