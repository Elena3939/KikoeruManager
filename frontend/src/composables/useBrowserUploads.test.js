import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { alert } = vi.hoisted(() => ({ alert: vi.fn().mockResolvedValue(null) }))
vi.mock('./useSystemPrompt', () => ({ showSystemConfirm: vi.fn(), showSystemAlert: alert }))
vi.mock('../api', () => ({ apiUrl: path => path, redirectIfSecurityGateExpired: vi.fn() }))
vi.mock('./useBackgroundWorkbenchManager', () => ({ useBackgroundWorkbenchManager: () => ({
  registerWorkbench: vi.fn(), patchWorkbenchState: vi.fn(), openWorkbench: vi.fn(),
}) }))

describe('上传完成提醒', () => {
  let status
  beforeEach(() => {
    vi.resetModules()
    vi.useFakeTimers()
    alert.mockClear()
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

  it.each(['completed', 'failed', 'cancelled'])('恢复历史 %s 任务保持静默', async terminal => {
    status = terminal
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    await uploads.refreshBrowserUploads()
    expect(alert).not.toHaveBeenCalled()
  })

  it('恢复中的活动任务真正完成后使用系统弹窗，重复刷新不重放', async () => {
    status = 'receiving'
    const uploads = await import('./useBrowserUploads')
    uploads.initializeBrowserUploads()
    await vi.advanceTimersByTimeAsync(1600)
    status = 'completed'
    await uploads.refreshBrowserUploads()
    await uploads.refreshBrowserUploads()
    expect(alert).toHaveBeenCalledTimes(1)
    expect(alert).toHaveBeenCalledWith(expect.objectContaining({ title: '上传完成', tone: 'success',
      details: [{ label: '目标目录', value: '/目标' }],
    }))
  })
})
