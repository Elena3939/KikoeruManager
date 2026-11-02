import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { appLoadingDirective } from './appLoading'

vi.mock('../components/common/AppLoadingAnimation.vue', () => ({
  default: { template: '<div class="loading-animation-stub" />' },
}))

describe('加载遮罩请求交接', () => {
  let host
  const binding = loading => ({ value: { loading, delay: 0, minVisible: 360 } })

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-01T00:00:00Z'))
    host = document.createElement('div')
    document.body.appendChild(host)
  })

  afterEach(() => {
    appLoadingDirective.unmounted(host)
    host.remove()
    vi.useRealTimers()
  })

  it('最短展示时间内重新加载，旧隐藏定时器不能关闭新请求的遮罩', () => {
    appLoadingDirective.mounted(host, binding(true))
    vi.advanceTimersByTime(100)
    appLoadingDirective.updated(host, binding(false))
    vi.advanceTimersByTime(100)
    appLoadingDirective.updated(host, binding(true))
    vi.advanceTimersByTime(1000)

    expect(host.querySelector('.app-loading-mask').style.display).not.toBe('none')
    appLoadingDirective.updated(host, binding(false))
    expect(host.querySelector('.app-loading-mask').style.display).toBe('none')
  })

  it('快速完成的请求仍遵守最短展示时间', () => {
    appLoadingDirective.mounted(host, binding(true))
    vi.advanceTimersByTime(100)
    appLoadingDirective.updated(host, binding(false))
    vi.advanceTimersByTime(259)
    expect(host.querySelector('.app-loading-mask').style.display).not.toBe('none')
    vi.advanceTimersByTime(1)
    expect(host.querySelector('.app-loading-mask').style.display).toBe('none')
  })

  it('延迟显示前已完成的请求不会再弹出遮罩', () => {
    const delayed = loading => ({ value: { loading, delay: 120, minVisible: 360 } })
    appLoadingDirective.mounted(host, delayed(true))
    vi.advanceTimersByTime(50)
    appLoadingDirective.updated(host, delayed(false))
    vi.advanceTimersByTime(1000)
    expect(host.querySelector('.app-loading-mask')).toBeNull()
  })

  it('卸载时清理尚未执行的隐藏定时器', () => {
    appLoadingDirective.mounted(host, binding(true))
    appLoadingDirective.updated(host, binding(false))
    appLoadingDirective.unmounted(host)
    expect(vi.getTimerCount()).toBe(0)
    expect(host.querySelector('.app-loading-mask')).toBeNull()
  })
})
