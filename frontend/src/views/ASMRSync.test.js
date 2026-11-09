import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ASMRSync from './ASMRSync.vue'
import { asmrSyncApi, taskCenterApi } from '../api'

vi.mock('lottie-web', () => ({ default: { loadAnimation: vi.fn() } }))
vi.mock('../components/download/DownloadTaskWorkbenchDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/circle/CircleDownloadPreviewDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/asmr/AsmrEnhancedDownloadPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/asmr/HttpDownloadPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/asmr/BaiduNetdiskPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/asmr/AsmrSubtitleScanPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/common/AppLottieProgressBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/common/AppLoadingAnimation.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../api', () => ({
  asmrSyncApi: {
    status: vi.fn(async () => ({ tasks: [] })),
    getWaitingRetry: vi.fn(async () => ({ tasks: [] })),
  },
  configApi: { get: vi.fn(async () => ({})) },
  baiduNetdiskApi: {},
  httpDownloadApi: {},
  libraryApi: {},
  taskApi: {},
  taskCenterApi: { action: vi.fn(async () => ({ success: true })) },
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/asmr-sync', query: {} }),
  useRouter: () => ({ replace: vi.fn(async () => {}) }),
}))
vi.mock('../composables/usePersistentTaskCards', () => ({
  usePersistentTaskWorkbench: vi.fn(),
  dismissPersistentTaskCard: vi.fn(),
  dismissWorkbenchTask: vi.fn(),
}))
vi.mock('../composables/useRealtimeEvents', async () => {
  const { ref } = await import('vue')
  return { useRealtimeEvents: () => ({ connected: ref(false) }) }
})
vi.mock('../composables/useViewport', () => ({
  useViewport: () => ({ isMobile: false }),
}))

describe('ASMR 页面下载任务生命周期', () => {
  let wrapper
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    asmrSyncApi.status.mockResolvedValue({ tasks: [] })
    taskCenterApi.action.mockReset().mockResolvedValue({ success: true })
  })
  afterEach(() => wrapper?.unmount())

  const mountPage = async tasks => {
    asmrSyncApi.status.mockResolvedValue({ tasks })
    wrapper = shallowMount(ASMRSync, {
      global: {
        stubs: {
          ElDialog: true, ElDrawer: true, ElTable: true, ElTableColumn: true,
          ElRadioGroup: true, ElRadioButton: true,
        },
        directives: { 'app-loading': {} },
      },
    })
    await flushPromises()
    return wrapper.vm.$.setupState
  }
  const rows = () => wrapper.findAll('.asmr-task').map(row => row.text())

  it('默认仅展示未结束任务，已完成、失败和取消任务进入历史列表', async () => {
    const state = await mountPage([
      { id: 'running', rjcode: 'RJ1', status: 'processing' },
      { id: 'done', rjcode: 'RJ2', status: 'completed' },
      { id: 'failed', rjcode: 'RJ3', status: 'failed' },
      { id: 'cancelled', rjcode: 'RJ4', status: 'cancelled' },
      { id: 'retry', rjcode: 'RJ5', status: 'waiting_retry' },
      { id: 'manual', rjcode: 'RJ6', status: 'waiting_manual' },
      { id: 'partial', rjcode: 'RJ7', status: 'completed', display_status: 'partial_failed' },
    ])
    expect(state.activeTasks.map(task => task.id)).toEqual(['running', 'manual'])
    expect(rows()).toHaveLength(2)
    expect(rows().join(' ')).toContain('等待处理')
    expect(rows().join(' ')).not.toContain('waiting_manual')
    wrapper.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 'history')
    await nextTick()
    expect(rows()).toHaveLength(4)
    expect(rows().join(' ')).toContain('部分失败')
  })

  it('状态更新后自动移入历史，原任务重试后重新出现在当前列表', async () => {
    const state = await mountPage([{ id: 'task', rjcode: 'RJ1', status: 'processing' }])
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'task', rjcode: 'RJ1', status: 'failed' }] })
    await state.refreshStatus()
    await nextTick()
    expect(rows()).toEqual([])
    expect(wrapper.text()).toContain('暂无未结束的下载任务')
    expect(state.historyTasks).toHaveLength(1)
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'task', rjcode: 'RJ1', status: 'processing' }] })
    await state.refreshStatus()
    await nextTick()
    expect(rows()).toHaveLength(1)
    expect(state.historyTasks).toHaveLength(0)
  })

  it('任务按钮取消等待处理任务并刷新当前列表', async () => {
    const task = { id: 'manual', rjcode: 'RJ6', status: 'waiting_manual' }
    const state = await mountPage([task])
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ ...task, status: 'cancelled' }] })
    await wrapper.findComponent({ name: 'StatefulButton' }).vm.$emit('click')
    await flushPromises()
    expect(taskCenterApi.action).toHaveBeenCalledWith('engine:manual', 'cancel')
    expect(rows()).toHaveLength(0)
    expect(state.historyTasks.map(row => row.id)).toEqual(['manual'])
    expect(state.enhancedDownloadWorkbenchVisible).toBe(false)
  })

  it('历史任务按钮删除真实记录并刷新列表', async () => {
    await mountPage([{ id: 'done', rjcode: 'RJ6', status: 'completed' }])
    wrapper.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 'history')
    await nextTick()
    asmrSyncApi.status.mockResolvedValue({ tasks: [] })
    await wrapper.findComponent({ name: 'StatefulButton' }).vm.$emit('click')
    await flushPromises()
    expect(taskCenterApi.action).toHaveBeenCalledWith('engine:done', 'delete')
    expect(rows()).toHaveLength(0)
  })
})
