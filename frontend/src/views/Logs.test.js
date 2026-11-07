import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import Logs from './Logs.vue'
import { TASK_PROGRESS_PREFIX } from '../utils/logProgress'

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
    expect(state.taskLanes[0].tasks.map(task => task.id)).toEqual(['download', 'upload'])
    expect(state.taskLanes[1].tasks.map(task => task.id)).toEqual(['extract', 'move'])
  })
})
