import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useInputScan } from './useInputScan'

const mocks = vi.hoisted(() => ({
  latest: vi.fn(), status: vi.fn(), scan: vi.fn(), cancel: vi.fn(),
  start: vi.fn(), stop: vi.fn(), subscribe: vi.fn(),
}))
vi.mock('../api', () => ({ scanApi: mocks }))
vi.mock('./useRealtimeEvents', () => ({
  useRealtimeEvents: () => ({
    connected: ref(false), start: mocks.start, stop: mocks.stop, subscribe: mocks.subscribe,
  }),
}))

let wrapper
let state
const job = revision => ({
  scan_id: 'one', status: 'running', revision, created_at: '2026-10-25T10:00:00',
})
const Panel = defineComponent({
  setup() {
    state = useInputScan()
    return () => h('div')
  },
})

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  mocks.latest.mockResolvedValue(job(1))
  mocks.subscribe.mockReturnValue(vi.fn())
})
afterEach(() => {
  wrapper?.unmount()
  vi.useRealTimers()
})

describe('扫描状态接回', () => {
  it('扫描结束 60 秒后隐藏，重复事件和重连不会让过期结果重新出现', async () => {
    const finished = Date.now()
    const completed = {
      ...job(2), status: 'completed', execution_status: 'waiting',
      display_expires_at: new Date(finished + 60000).toISOString(),
    }
    mocks.latest.mockResolvedValue(completed)
    wrapper = mount(Panel)
    await flushPromises()
    expect(state.visibleSnapshot.value).toEqual(completed)
    await vi.advanceTimersByTimeAsync(60000)
    expect(state.visibleSnapshot.value).toBeNull()
    const handler = mocks.subscribe.mock.calls[0][1]
    handler({ payload: { ...completed, revision: 3, execution_status: 'success' } })
    await state.reconnect()
    expect(state.visibleSnapshot.value).toBeNull()
    expect(state.snapshot.value.revision).toBe(3)
    expect(mocks.status).not.toHaveBeenCalled()
    expect(mocks.latest).toHaveBeenCalledTimes(2)
  })

  it('重新打开页面直接隐藏旧扫描，新扫描仍正常显示', async () => {
    mocks.latest.mockResolvedValue({
      ...job(1), status: 'cancelled', display_expires_at: new Date(Date.now() - 1).toISOString(),
    })
    wrapper = mount(Panel)
    await flushPromises()
    expect(state.visibleSnapshot.value).toBeNull()
    const fresh = { ...job(1), scan_id: 'two', created_at: '2026-11-03T20:00:00' }
    mocks.scan.mockResolvedValue(fresh)
    await state.start()
    await vi.advanceTimersByTimeAsync(60000)
    expect(state.visibleSnapshot.value).toEqual(fresh)
    expect(state.scanning.value).toBe(true)
  })

  it('首次查询失败后轮询重新接回，旧事件不覆盖新状态', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    mocks.latest.mockRejectedValueOnce(new Error('断线'))
    wrapper = mount(Panel)
    await flushPromises()
    expect(state.snapshot.value).toBeNull()
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(state.snapshot.value.revision).toBe(1)
    mocks.status.mockResolvedValue(job(3))
    await vi.advanceTimersByTimeAsync(3000)
    const handler = mocks.subscribe.mock.calls[0][1]
    handler({ payload: job(2) })
    expect(state.snapshot.value.revision).toBe(3)
    vi.restoreAllMocks()
  })

  it('返回缓存页面会重新接回且不会重复订阅或启动定时器', async () => {
    const shown = ref(true)
    wrapper = mount(defineComponent({
      setup: () => () => h(KeepAlive, null, {
        default: () => shown.value ? h(Panel) : null,
      }),
    }))
    await flushPromises()
    expect(mocks.latest).toHaveBeenCalledTimes(1)
    shown.value = false
    await nextTick()
    mocks.latest.mockResolvedValue(job(5))
    shown.value = true
    await nextTick()
    await flushPromises()
    expect(state.snapshot.value.revision).toBe(5)
    expect(mocks.subscribe).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)
  })
})
