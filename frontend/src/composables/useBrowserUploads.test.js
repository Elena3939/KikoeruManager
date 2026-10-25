import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { alert, patchWorkbenchState } = vi.hoisted(() => ({ alert: vi.fn().mockResolvedValue(null), patchWorkbenchState: vi.fn() }))
vi.mock('./useSystemPrompt', () => ({ showSystemConfirm: vi.fn(), showSystemAlert: alert }))
vi.mock('../api', () => ({ apiUrl: path => path, redirectIfSecurityGateExpired: vi.fn() }))
vi.mock('./useBackgroundWorkbenchManager', () => ({ useBackgroundWorkbenchManager: () => ({
  registerWorkbench: vi.fn(), patchWorkbenchState, openWorkbench: vi.fn(),
  backgroundWorkbench: vi.fn(),
}) }))

describe('上传完成提醒', () => {
  let status
  beforeEach(() => {
    vi.resetModules()
    vi.useFakeTimers()
    alert.mockClear()
    patchWorkbenchState.mockClear()
    localStorage.clear()
    status = 'completed'
    localStorage.setItem('kikoerumanager.browserUploads', JSON.stringify([{ id: 'history', token: 'token' }]))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      id: 'history', status, source_label: '文件.txt', target_path: '/目标',
      files: [], total_entries: 0, revision: 1, cursor: 1, has_more: false,
      counts: { completed: status === 'completed' ? 1 : 0, failed: 0 },
    }) })))
  })
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it.each(['completed', 'failed', 'cancelled', 'paused', 'receiving'])('零字节 %s 上传的小窗同步真实状态，稳定后不重复持久化', async current => {
    status = current
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    const patch = patchWorkbenchState.mock.calls.filter(([, value]) => value.status).at(-1)[1]
    expect(patch.status.key).toBe(current === 'receiving' ? 'processing' : current)
    expect(patch.progress.percentage).toBe(current === 'completed' ? 100 : 0)
    patchWorkbenchState.mockClear()
    await vi.advanceTimersByTimeAsync(2000)
    expect(patchWorkbenchState).not.toHaveBeenCalled()
  })

  it('按服务端写入字节计算进度，传完后仍等服务端确认完成', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    fetch.mockResolvedValue({ ok: true, json: async () => ({ status, files: [], total_bytes: 100, written_bytes: 67, cursor: 2 }) })
    await uploads.refreshBrowserUploads()
    expect(patchWorkbenchState.mock.calls.at(-1)[1].progress.percentage).toBe(67)
    fetch.mockResolvedValue({ ok: true, json: async () => ({ status, files: [], total_bytes: 100, written_bytes: 100, cursor: 3 }) })
    await uploads.refreshBrowserUploads()
    expect(patchWorkbenchState.mock.calls.at(-1)[1].progress.percentage).toBe(99)
    status = 'completed'
    await uploads.refreshBrowserUploads()
    expect(patchWorkbenchState.mock.calls.at(-1)[1].progress.percentage).toBe(100)
  })

  it.each(['completed', 'failed', 'cancelled'])('恢复历史 %s 任务保持静默', async terminal => {
    status = terminal
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    await uploads.refreshBrowserUploads()
    expect(alert).not.toHaveBeenCalled()
  })

  it.each(['completed', 'failed', 'cancelled'])('手动关闭 %s 任务移除缓存，刷新不再出现', async terminal => {
    status = terminal
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    uploads.dismissBrowserUpload('history')
    await uploads.refreshBrowserUploads()
    expect(uploads.browserUploads.value).toEqual([])
    expect(JSON.parse(localStorage.getItem('kikoerumanager.browserUploads'))).toEqual([])
  })

  it.each(['completed', 'cancelled'])('%s 缓存到期自动移除', async terminal => {
    status = terminal
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    expect(uploads.browserUploads.value).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(uploads.UPLOAD_RETENTION_MS)
    expect(uploads.browserUploads.value).toEqual([])
  })

  it('失败任务不会随缓存时间自动消失，关闭窗口才移除', async () => {
    status = 'failed'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(uploads.UPLOAD_RETENTION_MS + 1600)
    expect(uploads.browserUploads.value).toHaveLength(1)
    uploads.closeBrowserUploadWorkbench()
    expect(uploads.browserUploads.value).toEqual([])
  })

  it('刷新恢复沿用原到期时间，不重新开始缓存计时', async () => {
    localStorage.setItem('kikoerumanager.browserUploads', JSON.stringify([{ id: 'history', token: 'token', terminalAt: Date.now() - 59_000 }]))
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    expect(uploads.browserUploads.value).toEqual([])
  })

  it('关闭窗口保留活动上传，单条关闭也不能移除活动任务', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    uploads.dismissBrowserUpload('history')
    uploads.closeBrowserUploadWorkbench()
    expect(uploads.browserUploads.value).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem('kikoerumanager.browserUploads'))).toHaveLength(1)
  })

  it.each(['completed', 'cancelled'])('活动任务变为 %s 后不弹窗，仍发送库存刷新事件且不重复发送', async terminal => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    const finished = vi.fn()
    window.addEventListener('library-browser-upload-finished', finished)
    status = terminal
    await uploads.refreshBrowserUploads()
    await uploads.refreshBrowserUploads()
    expect(alert).not.toHaveBeenCalled()
    expect(finished).toHaveBeenCalledTimes(1)
    window.removeEventListener('library-browser-upload-finished', finished)
  })
})
