import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, ref } from 'vue'
import { circleCompletionApi } from '../api'
import { ElMessage } from 'element-plus'
import { useCircleSubtitleRepair } from './useCircleSubtitleRepair'
import { openVerificationPopup, reserveVerificationPopup } from '../utils/browserVerificationPopup'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('../api', () => ({ circleCompletionApi: {
  subtitleRepairTargets: vi.fn(), subtitleRepairStart: vi.fn(), subtitleRepairTasks: vi.fn(),
} }))
vi.mock('element-plus', () => ({ ElMessage: Object.assign(vi.fn(), { error: vi.fn(), warning: vi.fn() }) }))
vi.mock('./useRealtimeEvents', () => ({ useRealtimeEvents: () => ({
  start: vi.fn(), stop: vi.fn(), subscribe: () => vi.fn(),
}) }))
vi.mock('../utils/browserVerificationPopup', () => ({ reserveVerificationPopup: vi.fn(), openVerificationPopup: vi.fn() }))

const item = { canonical_rjcode: 'RJ01168542', subtitle_repair_sources: [{ provider: 'yaas' }] }
const target = { library_id: 'local', folder_path: '/RJ01168542', eligible: true }
const task = { task_id: 'created-task', status: 'processing', browser_verification_required: false }
let apps = []
let model, popup, rows, circle
const settle = async () => { for (let i = 0; i < 15; i++) await Promise.resolve() }
function mountRepair(works = [item]) {
  circle = ref('RG38133')
  const app = createApp({ setup() {
    model = useCircleSubtitleRepair(circle, ref(works))
    return () => h('div')
  } })
  app.mount(document.createElement('div'))
  apps.push(app)
  return model
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  rows = [{ ...task }]
  popup = { closed: false, close: vi.fn() }
  reserveVerificationPopup.mockReturnValue(popup)
  openVerificationPopup.mockResolvedValue({})
  circleCompletionApi.subtitleRepairTargets.mockResolvedValue({ items: [{ canonical_rjcode: item.canonical_rjcode, targets: [target] }] })
  circleCompletionApi.subtitleRepairStart.mockResolvedValue({ created_count: 1, items: [{ ...task, state: 'created' }] })
  circleCompletionApi.subtitleRepairTasks.mockImplementation(async () => ({ items: { RJ01168542: rows } }))
})
afterEach(() => {
  apps.forEach(app => app.unmount())
  apps = []
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('社团爬取字幕到浏览器下载', () => {
  it('先开窗再请求目录，任务等待验证后复用原窗口，忽略其它任务', async () => {
    mountRepair()
    let resolve
    circleCompletionApi.subtitleRepairTargets.mockImplementation(() => new Promise(done => { resolve = done }))
    const pending = model.create(item)
    expect(reserveVerificationPopup).toHaveBeenCalledOnce()
    expect(circleCompletionApi.subtitleRepairStart).not.toHaveBeenCalled()
    resolve({ items: [{ canonical_rjcode: item.canonical_rjcode, targets: [target] }] })
    await pending
    rows = [...rows, { task_id: 'unrelated', status: 'waiting_manual', browser_verification_required: true }]
    await vi.advanceTimersByTimeAsync(1000)
    expect(openVerificationPopup).not.toHaveBeenCalled()
    rows = [{ ...task, status: 'waiting_manual', browser_verification_required: true }]
    await vi.advanceTimersByTimeAsync(1000)
    expect(openVerificationPopup).toHaveBeenCalledOnce()
    expect(openVerificationPopup).toHaveBeenCalledWith('created-task', popup)
    apps[0].unmount()
    apps = []
    expect(popup.close).not.toHaveBeenCalled()
  })
  it('已有等待验证任务直接打开浏览器，不跳库存工作台', async () => {
    mountRepair()
    rows = [{ ...task, status: 'waiting_manual', browser_verification_required: true }]
    await model.refresh()
    expect(model.statusLabel(rows[0])).toBe('浏览器下载')
    await model.view(item)
    expect(openVerificationPopup).toHaveBeenCalledWith('created-task')
    expect(push).not.toHaveBeenCalled()
  })
  it('弹窗被拦截时明确提示，不创建没有窗口的任务', async () => {
    mountRepair()
    reserveVerificationPopup.mockImplementationOnce(() => { throw new Error('浏览器拦截了下载弹窗') })
    await model.create(item)
    expect(ElMessage.error).toHaveBeenCalledWith('浏览器拦截了下载弹窗')
    expect(circleCompletionApi.subtitleRepairTargets).not.toHaveBeenCalled()
    expect(circleCompletionApi.subtitleRepairStart).not.toHaveBeenCalled()
  })
  it('多位置选择时关闭占位窗，确认点击重新开窗', async () => {
    mountRepair()
    circleCompletionApi.subtitleRepairTargets.mockResolvedValue({ items: [{ canonical_rjcode: item.canonical_rjcode, targets: [target, { ...target, library_id: 'other' }] }] })
    await model.create(item)
    expect(model.visible.value).toBe(true)
    expect(popup.close).toHaveBeenCalledOnce()
    expect(circleCompletionApi.subtitleRepairStart).not.toHaveBeenCalled()
    model.selected.value = [`RJ01168542:${model.keyOf(target)}`]
    await model.confirm()
    expect(reserveVerificationPopup).toHaveBeenCalledTimes(2)
    expect(circleCompletionApi.subtitleRepairStart).toHaveBeenCalledWith(expect.objectContaining({ selections: { RJ01168542: [target] } }))
  })
  it.each(['failed', 'completed', 'cancelled'])('%s 任务关闭占位窗口，不启动验证或清理任务', async status => {
    mountRepair()
    rows = [{ ...task, status }]
    await model.create(item)
    await settle()
    expect(popup.close).toHaveBeenCalledOnce()
    expect(openVerificationPopup).not.toHaveBeenCalled()
    if (status === 'failed') expect(ElMessage.error).toHaveBeenCalled()
  })
  it('用户关闭等待窗口后停止轮询，保留系统任务', async () => {
    mountRepair()
    await model.create(item)
    popup.closed = true
    await vi.advanceTimersByTimeAsync(1000)
    const count = circleCompletionApi.subtitleRepairTasks.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(circleCompletionApi.subtitleRepairTasks).toHaveBeenCalledTimes(count)
    expect(openVerificationPopup).not.toHaveBeenCalled()
  })
  it('切换社团时只关闭占位窗，迟到的结果不会接管其它任务', async () => {
    mountRepair()
    await model.create(item)
    circle.value = 'other-circle'
    await settle()
    rows = [{ ...task, status: 'waiting_manual', browser_verification_required: true }]
    await vi.advanceTimersByTimeAsync(1000)
    expect(popup.close).toHaveBeenCalledOnce()
    expect(openVerificationPopup).not.toHaveBeenCalled()
  })
  it('asmr.one 来源维持原爬取流程，不打开无关浏览器', async () => {
    const direct = { ...item, subtitle_repair_sources: [{ provider: 'asmr.one' }] }
    mountRepair([direct])
    await model.create(direct)
    expect(reserveVerificationPopup).not.toHaveBeenCalled()
    expect(circleCompletionApi.subtitleRepairStart).toHaveBeenCalledOnce()
  })
})
