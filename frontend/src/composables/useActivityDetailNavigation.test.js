import { describe, expect, it, vi } from 'vitest'
import { useActivityDetailNavigation } from './useActivityDetailNavigation.js'

function setup(loadDetail = vi.fn(async id => ({ id, detail: { child_rows: [] } }))) {
  const captureView = vi.fn(() => ({ scrollTop: 480, childExpanded: true }))
  const restoreView = vi.fn()
  const onError = vi.fn()
  const nav = useActivityDetailNavigation({ loadDetail, captureView, restoreView, onError })
  return { ...nav, loadDetail, captureView, restoreView, onError }
}

describe('操作历史详情逐级导航', () => {
  it('多层返回保留父级详情引用和视图位置，不重新请求', async () => {
    const nav = setup()
    await nav.open({ id: 'batch' })
    const batch = nav.row.value
    await nav.openChild('package')
    const archive = nav.row.value
    await nav.openChild('directory')
    nav.back()
    expect(nav.row.value).toBe(archive)
    expect(nav.canGoBack.value).toBe(true)
    nav.back()
    expect(nav.row.value).toBe(batch)
    expect(nav.canGoBack.value).toBe(false)
    expect(nav.restoreView).toHaveBeenLastCalledWith({ scrollTop: 480, childExpanded: true })
    expect(nav.loadDetail).toHaveBeenCalledTimes(3)
  })

  it('子任务加载期间返回，迟到响应不能覆盖父级', async () => {
    let finish
    const nav = setup(vi.fn(id => id === 'batch' ? Promise.resolve({ id })
      : new Promise(resolve => { finish = resolve })))
    await nav.open({ id: 'batch' })
    const pending = nav.openChild('package')
    expect(nav.loading.value).toBe(true)
    nav.back()
    finish({ id: 'package' })
    await pending
    expect(nav.row.value.id).toBe('batch')
    expect(nav.loading.value).toBe(false)
  })

  it('子任务请求失败恢复父级和展开状态', async () => {
    const nav = setup(vi.fn(async id => {
      if (id === 'package') throw new Error('加载失败')
      return { id }
    }))
    await nav.open({ id: 'batch' })
    await nav.openChild('package')
    expect(nav.row.value.id).toBe('batch')
    expect(nav.canGoBack.value).toBe(false)
    expect(nav.onError).toHaveBeenCalledOnce()
    expect(nav.restoreView).toHaveBeenLastCalledWith({ scrollTop: 480, childExpanded: true })
  })

  it('关闭后不接收迟到详情，重新打开主记录清空旧导航', async () => {
    let finish
    const nav = setup(vi.fn(id => id === 'slow' ? new Promise(resolve => { finish = resolve })
      : Promise.resolve({ id })))
    await nav.open({ id: 'batch' })
    const pending = nav.openChild('slow')
    nav.reset()
    finish({ id: 'slow' })
    await pending
    expect(nav.row.value).toBeNull()
    await nav.open({ id: 'other-batch' })
    expect(nav.canGoBack.value).toBe(false)
    expect(nav.row.value.id).toBe('other-batch')
  })
})
