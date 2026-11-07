import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
const realtime = vi.hoisted(() => ({ handlers: new Map(), connected: null }))
vi.mock('./useRealtimeEvents', () => ({ useRealtimeEvents: () => ({
  connected: (realtime.connected = ref(false)), subscribe: (type, handler) => realtime.handlers.set(type, handler),
}) }))

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
    realtime.handlers.clear()
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

  it.each(['failed', 'paused', 'receiving'])('零字节 %s 上传的小窗同步真实状态，稳定后不重复持久化', async current => {
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

  it('SSE 直接更新 36% 发送和 11% 写入，定时采样不请求状态', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    fetch.mockClear()
    realtime.handlers.get('library.browser-upload.changed')({ payload: {
      id: 'history', status, enumerated: true, total_bytes: 100, received_bytes: 36, written_bytes: 11,
      from_cursor: 1, cursor: 2, has_more: false, files: [],
    } })
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).not.toHaveBeenCalled()
    expect(uploads.browserUploads.value[0].liveReceived).toBe(36)
    const patch = patchWorkbenchState.mock.calls.filter(([, value]) => value.status).at(-1)[1]
    expect(patch.progress.percentage).toBe(36)
    expect(patch.summary.metaText).toContain('已写入 11 B')
    expect(patch.summary.timingText).toContain('预计剩余')
  })

  it('SSE 增量缺口按需补拉，重连重新取快照', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    fetch.mockClear()
    realtime.handlers.get('library.browser-upload.changed')({ payload: { id: 'history', from_cursor: 8, cursor: 9 } })
    await vi.advanceTimersByTimeAsync(250)
    expect(fetch.mock.calls[0][0]).toContain('/changes?cursor=1')
    fetch.mockClear()
    realtime.connected.value = true
    await vi.advanceTimersByTimeAsync(250)
    expect(fetch.mock.calls[0][0]).toContain('?offset=0&limit=200')
  })

  it('按主窗口发送字节计算进度，写入进度单列，传完仍等服务端确认', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    fetch.mockResolvedValue({ ok: true, json: async () => ({ status, enumerated: true, files: [], total_bytes: 100, received_bytes: 67, written_bytes: 11, cursor: 2 }) })
    await uploads.refreshBrowserUploads()
    expect(patchWorkbenchState.mock.calls.at(-1)[1].progress.percentage).toBe(67)
    expect(patchWorkbenchState.mock.calls.at(-1)[1].summary.metaText).toContain('已写入 11 B')
    fetch.mockResolvedValue({ ok: true, json: async () => ({ status, files: [], total_bytes: 100, received_bytes: 100, written_bytes: 100, cursor: 3 }) })
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

  it.each(['completed', 'cancelled'])('恢复历史 %s 会话立即移除，不重新出现在工作台', async terminal => {
    status = terminal
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    expect(uploads.browserUploads.value).toEqual([])
    expect(JSON.parse(localStorage.getItem('kikoerumanager.browserUploads'))).toEqual([])
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('恢复不存在的会话只请求一次并移除缓存', async () => {
    fetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: '上传会话不存在' }) })
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(uploads.browserUploads.value).toEqual([])
    expect(JSON.parse(localStorage.getItem('kikoerumanager.browserUploads'))).toEqual([])
  })

  it('清单空页不能在一次恢复中无限请求', async () => {
    status = 'receiving'
    fetch.mockResolvedValue({ ok: true, json: async () => ({ status, files: [], total_entries: 10, revision: 1 }) })
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(uploads.browserUploads.value[0].connectionError).toContain('分页未前进')
  })

  it('畸形缓存不阻断应用启动', async () => {
    localStorage.setItem('kikoerumanager.browserUploads', '{"id":"history"}')
    const uploads = await import('./useBrowserUploads')
    expect(() => uploads.initializeBrowserUploads()).not.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('恢复来源按清单批量重试，使用服务端校验状态', async () => {
    status = 'failed'
    const files = Array.from({ length: 33 }, (_, i) => ({ id: `f${i}`, relative_path: `f${i}.bin`,
      size: 1, last_modified: 42, status: 'failed', received: 1, written: 0 }))
    fetch.mockImplementation(async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : {}
      let result = { status, files: [], total_entries: files.length, revision: 1, cursor: 1, counts: { failed: 33 } }
      if (url.includes('/manifest')) result = { files: body.entries.map(entry => files.find(file => file.relative_path === entry.relative_path)) }
      else if (url.includes('/actions')) result = { status: 'receiving', changed_files: body.file_ids.map(id => ({ ...files.find(file => file.id === id), status: 'verifying' })) }
      else if (!url.includes('/changes')) result.files = files
      return { ok: true, json: async () => result }
    })
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    const sources = files.map(file => ({ name: file.relative_path, size: 1, lastModified: 42 }))
    const restoring = uploads.restoreBrowserUploadSource('history', sources)
    await vi.advanceTimersByTimeAsync(250)
    await restoring
    const actions = fetch.mock.calls.filter(([url]) => url.includes('/actions')).map(([, options]) => JSON.parse(options.body))
    expect(actions.map(action => action.file_ids.length)).toEqual([32, 1])
    expect(actions.every(action => action.action === 'retry' && !action.file_id)).toBe(true)
    expect([...uploads.browserUploads.value[0].files.values()].every(file => file.status === 'verifying')).toBe(true)
    expect(fetch.mock.calls.some(([url]) => url.includes('/checkpoint'))).toBe(false)
  })

  it('视图定时刷新不扫描全部文件', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    const files = uploads.browserUploads.value[0].files
    const scan = vi.spyOn(files, 'values').mockImplementation(() => { throw new Error('不应扫描全清单') })
    await vi.advanceTimersByTimeAsync(500)
    expect(scan).not.toHaveBeenCalled()
  })

  it('补报接收失败时采用服务端已进入校验的真实状态', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(250)
    const session = uploads.browserUploads.value[0]
    session.files.set('f1', { id: 'f1', size: 5, received: 5, status: 'failed', clientFailed: true, reason: '超时' })
    session.failedReports.add('f1')
    fetch.mockImplementation(async url => ({ ok: true, json: async () => url.includes('/actions')
      ? { status, changed_files: [{ id: 'f1', size: 5, received: 5, status: 'verifying' }] }
      : { status, files: [], cursor: 2 } }))
    await uploads.refreshBrowserUploads()
    expect(session.files.get('f1')).toMatchObject({ status: 'verifying', clientFailed: false })
    expect(session.failedReports.size).toBe(0)
  })

  it('分块超时重试四次后上报失败，不误判为用户取消', async () => {
    localStorage.clear()
    const file = { id: 'f1', relative_path: 'file.bin', size: 1, last_modified: 42, status: 'receiving', received: 0, written: 0 }
    const response = () => ({ id: 'active', token: 'token', status: 'receiving', source_label: 'file.bin', files: [], cursor: 0 })
    fetch.mockImplementation(async (url, options = {}) => {
      let result = response()
      if (url.includes('/manifest')) result = { files: JSON.parse(options.body).entries.length ? [file] : [] }
      else if (url.includes('/checkpoint')) result = { offset: 0, chunks: [] }
      else if (url.includes('/actions')) result = { status: 'failed', counts: { failed: 1 }, changed_files: [{ ...file, status: 'failed' }] }
      return { ok: true, json: async () => result }
    })
    vi.stubGlobal('Worker', class {
      postMessage({ id, buffer }) { queueMicrotask(() => this.onmessage({ data: { id, digest: 'digest', buffer } })) }
    })
    const sent = vi.fn(), aborted = vi.fn()
    vi.stubGlobal('XMLHttpRequest', class {
      upload = {}
      open() {}
      setRequestHeader() {}
      send() { sent(); setTimeout(() => { this.ontimeout(); this.onloadend() }, this.timeout) }
      abort() { aborted(); this.onabort(); this.onloadend() }
    })
    const uploads = await import('./useBrowserUploads')
    const session = await uploads.startBrowserUpload({ libraryId: 'test', path: '' }, [{ name: 'file.bin', size: 1, lastModified: 42,
      slice: () => ({ arrayBuffer: async () => new ArrayBuffer(1) }) }])
    await vi.advanceTimersByTimeAsync(485000)
    expect(sent).toHaveBeenCalledTimes(4)
    expect(aborted).not.toHaveBeenCalled()
    expect(session.files.get('f1').status).toBe('failed')
    const actions = fetch.mock.calls.filter(([url]) => url.includes('/actions')).map(([, options]) => JSON.parse(options.body))
    expect(actions).toHaveLength(1)
    expect(actions[0]).toMatchObject({ action: 'receive_failed', file_id: 'f1' })
    expect(actions[0].reason).toContain('上传超时')
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
