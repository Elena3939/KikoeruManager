import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ConflictDiagnostics from './ConflictDiagnostics.vue'

const { diagnostics } = vi.hoisted(() => ({ diagnostics: vi.fn() }))
vi.mock('../../api', () => ({ conflictApi: { diagnostics } }))

async function toggle(wrapper, open) {
  const toggled = new Promise(resolve => wrapper.element.addEventListener('toggle', resolve, { once: true }))
  wrapper.element.open = open
  await toggled
  await flushPromises()
}

describe('问题作品按需诊断', () => {
  let wrapper
  beforeEach(() => { diagnostics.mockReset() })
  afterEach(() => wrapper?.unmount())

  it('仅展开时读取，重新展开读取最新内容', async () => {
    diagnostics.mockResolvedValue({ metadata: { extract_timing: { elapsed: 55 } } })
    wrapper = mount(ConflictDiagnostics, { props: { conflictId: 'a' } })
    expect(diagnostics).not.toHaveBeenCalled()
    await toggle(wrapper, true)
    expect(diagnostics).toHaveBeenCalledWith('a', { signal: expect.any(AbortSignal) })
    expect(wrapper.find('pre').text()).toContain('"elapsed": 55')
    await toggle(wrapper, false)
    expect(wrapper.find('pre').exists()).toBe(false)
    await toggle(wrapper, true)
    expect(diagnostics).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('关闭与卸载中止请求，迟到的旧响应不渲染', async () => {
    let resolve
    diagnostics.mockImplementation(() => new Promise(done => { resolve = done }))
    wrapper = mount(ConflictDiagnostics, { props: { conflictId: 'a' } })
    await toggle(wrapper, true)
    const signal = diagnostics.mock.calls[0][1].signal
    await toggle(wrapper, false)
    expect(signal.aborted).toBe(true)
    resolve({ metadata: { old: true } })
    await flushPromises()
    expect(wrapper.find('pre').exists()).toBe(false)
    await toggle(wrapper, true)
    const nextSignal = diagnostics.mock.calls[1][1].signal
    wrapper.unmount()
    expect(nextSignal.aborted).toBe(true)
    resolve({ metadata: {} })
    await flushPromises()
  })

  it('读取失败保留错误提示', async () => {
    diagnostics.mockRejectedValue(new Error('读取失败'))
    wrapper = mount(ConflictDiagnostics, { props: { conflictId: 'a' } })
    await toggle(wrapper, true)
    expect(wrapper.find('[role="alert"]').text()).toBe('读取失败')
    wrapper.unmount()
  })
})
