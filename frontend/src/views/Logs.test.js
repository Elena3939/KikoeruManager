import { afterEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import Logs from './Logs.vue'
import { TASK_PROGRESS_PREFIX } from '../utils/logProgress'

vi.mock('../api', () => ({
  logApi: { streamUrl: vi.fn(() => '/api/logs/stream'), get: vi.fn() },
  redirectIfSecurityGateExpired: vi.fn(),
}))
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
    expect(cards()).toHaveLength(1)
    expect(cards()[0].progress).toBe(100)
    expect(cards()[0].taskProgress.tone).toBe('processing')

    stream.emit('log', [line('completed', 100, '下载完成，成功 1 个，失败 0 个')], 300)
    await vi.advanceTimersByTimeAsync(160)
    expect(cards()).toHaveLength(1)
    expect(cards()[0].taskProgress.tone).toBe('success')
    expect(cards()[0].taskProgress.active).toBe(false)
  })
})
