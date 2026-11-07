import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkbenchBackgroundCard from './WorkbenchBackgroundCard.vue'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'
import { browserUploads, initializeBrowserUploads, UPLOAD_WORKBENCH } from '../../composables/useBrowserUploads'

const realtime = vi.hoisted(() => ({ handlers: new Map() }))
vi.mock('../../composables/useRealtimeEvents', () => ({
  useRealtimeEvents: () => ({
    connected: ref(false),
    subscribe: (type, handler) => realtime.handlers.set(type, handler),
  }),
}))
vi.mock('../../composables/useSystemPrompt', () => ({
  showSystemAlert: vi.fn(),
  showSystemConfirm: vi.fn(),
}))
vi.mock('../../api', () => ({
  apiUrl: path => path,
  redirectIfSecurityGateExpired: vi.fn(),
}))
vi.mock('@lottiefiles/dotlottie-vue', () => ({ DotLottieVue: { template: '<span />' } }))

let wrapper
afterEach(() => {
  wrapper?.unmount()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

it('浏览器上传经真实工作台状态渲染字节进度和预计时间，SSE 更新大小窗一致且不轮询', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  localStorage.clear()
  localStorage.setItem('kikoerumanager.browserUploads', JSON.stringify([{ id: 'progress-integration', token: 'test-token' }]))
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({
      id: 'progress-integration', status: 'receiving', enumerated: true,
      total_bytes: 100 * 1024 * 1024, received_bytes: 36 * 1024 * 1024, written_bytes: 11 * 1024 * 1024,
      files: [], total_entries: 0, cursor: 1, has_more: false,
      counts: { completed: 0, failed: 0 },
    }),
  })))
  const manager = useBackgroundWorkbenchManager()
  initializeBrowserUploads()
  await flushPromises()
  await vi.advanceTimersByTimeAsync(250)
  manager.backgroundWorkbench(UPLOAD_WORKBENCH)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  await router.isReady()
  wrapper = mount(defineComponent({
    components: { WorkbenchBackgroundCard },
    setup: () => ({ workbench: manager.getWorkbenchState(UPLOAD_WORKBENCH) }),
    template: '<WorkbenchBackgroundCard :workbench="workbench" />',
  }), { global: { plugins: [router] } })

  expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('36')
  expect(wrapper.get('.task-toast-meta').text()).toContain('上传 36.00 MB / 100.00 MB')
  expect(wrapper.get('.task-toast-meta').text()).toContain('剩余 64.00 MB')
  expect(wrapper.get('.task-toast-meta').text()).toContain('已写入 11.0 MiB')

  fetch.mockClear()
  realtime.handlers.get('library.browser-upload.changed')({ payload: {
    id: 'progress-integration', status: 'receiving', enumerated: true,
    total_bytes: 100 * 1024 * 1024, received_bytes: 56 * 1024 * 1024, written_bytes: 31 * 1024 * 1024,
    from_cursor: 1, cursor: 2, has_more: false, files: [],
  } })
  await vi.advanceTimersByTimeAsync(250)
  await nextTick()
  const session = browserUploads.value[0]
  expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe(String(Math.floor(session.liveReceived / session.total_bytes * 100)))
  expect(wrapper.get('.task-toast-meta').text()).toContain('上传 56.00 MB / 100.00 MB')
  expect(wrapper.get('.task-toast-meta').text()).toContain('已写入 31.0 MiB')
  expect(wrapper.get('.task-toast-timing').text()).toContain('预计剩余：')
  expect(wrapper.get('.task-toast-timing').text()).toContain('预计完成：')
  expect(wrapper.get('.task-toast-timing').text()).not.toContain('--')
  await vi.advanceTimersByTimeAsync(5000)
  expect(fetch).not.toHaveBeenCalled()
})
