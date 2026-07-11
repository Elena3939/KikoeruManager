import { describe, expect, it, vi } from 'vitest'

const apiClient = {
  interceptors: { response: { use: vi.fn() } },
}

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiClient),
    isCancel: vi.fn(error => error?.axiosCanceled === true),
  },
}))

const { isCanceledApiRequest } = await import('./index')

describe('API 请求取消判定', () => {
  it.each([
    { axiosCanceled: true },
    { code: 'ERR_CANCELED' },
    { name: 'CanceledError' },
    { name: 'AbortError' },
  ])('识别预期取消 %#', (error) => {
    expect(isCanceledApiRequest(error)).toBe(true)
  })

  it('不吞掉普通接口错误', () => {
    expect(isCanceledApiRequest({ code: 'ERR_NETWORK', name: 'AxiosError' })).toBe(false)
  })
})
