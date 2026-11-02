import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openVerificationPopup, reserveVerificationPopup } from './browserVerificationPopup'
import { browserVerificationApi } from '../api'
vi.mock('../api', () => ({ browserVerificationApi: { open: vi.fn(), handoff: vi.fn() } }))
beforeEach(() => browserVerificationApi.handoff.mockResolvedValue({ success: true }))
afterEach(() => { vi.restoreAllMocks(); vi.resetAllMocks() })
function popupWindow() {
  const popup = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() }
  vi.spyOn(window, 'open').mockReturnValue(popup)
  return popup
}
describe('当前浏览器弹窗下载', () => {
  it('点击时同步开窗，获取地址后跳转并清理对应系统任务', async () => {
    const popup = popupWindow()
    let resolve
    browserVerificationApi.open.mockImplementation(() => new Promise(done => { resolve = done }))
    const pending = openVerificationPopup('task')
    expect(window.open).toHaveBeenCalledWith('about:blank', '_blank', 'popup,width=960,height=760')
    expect(popup.opener).toBe(null)
    expect(browserVerificationApi.open).toHaveBeenCalledWith('task')
    expect(browserVerificationApi.handoff).not.toHaveBeenCalled()
    resolve({ presentation: 'current_browser', verification_url: 'https://cdn.imoutoheaven.org/file' })
    await pending
    expect(popup.location.replace).toHaveBeenCalledWith('https://cdn.imoutoheaven.org/file')
    expect(browserVerificationApi.handoff).toHaveBeenCalledWith('task')
    expect(popup.close).not.toHaveBeenCalled()
  })
  it('弹窗被拦截时明确报错，不假装已经打开', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    await expect(openVerificationPopup('task')).rejects.toThrow('拦截')
    expect(browserVerificationApi.open).not.toHaveBeenCalled()
    expect(browserVerificationApi.handoff).not.toHaveBeenCalled()
  })
  it.each(['http://cdn.imoutoheaven.org/file', 'https://evil.example/file', 'https://a.imoutoheaven.org.evil.example/file'])('拒绝异常地址 %s，保留任务', async url => {
    const popup = popupWindow()
    browserVerificationApi.open.mockResolvedValue({ verification_url: url })
    await expect(openVerificationPopup('task')).rejects.toThrow('非预期')
    expect(popup.close).toHaveBeenCalledOnce()
    expect(browserVerificationApi.handoff).not.toHaveBeenCalled()
  })
  it('接口失败关闭空白窗口', async () => {
    const popup = popupWindow()
    browserVerificationApi.open.mockRejectedValue(new Error('任务不存在'))
    await expect(openVerificationPopup('task')).rejects.toThrow('任务不存在')
    expect(popup.close).toHaveBeenCalledOnce()
    expect(browserVerificationApi.handoff).not.toHaveBeenCalled()
  })
  it('加载中手动关闭弹窗时不清理任务', async () => {
    const popup = popupWindow()
    popup.closed = true
    browserVerificationApi.open.mockResolvedValue({ verification_url: 'https://cdn.imoutoheaven.org/file' })
    await expect(openVerificationPopup('task')).rejects.toThrow('已关闭')
    expect(browserVerificationApi.handoff).not.toHaveBeenCalled()
  })
  it('复用点击创建时预开的窗口，不在异步任务就绪后重复开窗', async () => {
    const popup = popupWindow()
    reserveVerificationPopup()
    vi.mocked(window.open).mockClear()
    browserVerificationApi.open.mockResolvedValue({ verification_url: 'https://cdn.imoutoheaven.org/file' })
    await openVerificationPopup('created-task', popup)
    expect(window.open).not.toHaveBeenCalled()
    expect(popup.location.replace).toHaveBeenCalledWith('https://cdn.imoutoheaven.org/file')
    expect(browserVerificationApi.handoff).toHaveBeenCalledWith('created-task')
  })
  it('任务清理失败不关闭正在验证下载的浏览器', async () => {
    const popup = popupWindow()
    browserVerificationApi.open.mockResolvedValue({ verification_url: 'https://cdn.imoutoheaven.org/file' })
    browserVerificationApi.handoff.mockRejectedValue(new Error('network'))
    await expect(openVerificationPopup('task')).rejects.toThrow('清理失败')
    expect(popup.close).not.toHaveBeenCalled()
  })
})
