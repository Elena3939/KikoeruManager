import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiClient = {
  get: vi.fn(), post: vi.fn(),
  interceptors: { response: { use: vi.fn() } },
}
vi.mock('axios', () => ({ default: { create: vi.fn(() => apiClient) } }))
const { scanApi } = await import('./index')

describe('持久扫描短请求', () => {
  beforeEach(() => {
    apiClient.get.mockReset()
    apiClient.post.mockReset()
  })

  it('启动后立即返回批次，重试携带同一幂等键', async () => {
    const job = { scan_id: 'one', status: 'running', revision: 1 }
    apiClient.post.mockResolvedValue({ data: job })
    expect(await scanApi.scan('retry-key')).toEqual(job)
    expect(apiClient.post).toHaveBeenCalledWith('/scan', null, {
      params: { background: true, request_key: 'retry-key' },
    })
    expect(apiClient.get).not.toHaveBeenCalled()
  })

  it('状态与取消均定位同一持久批次', async () => {
    apiClient.get.mockResolvedValue({ data: { status: 'running' } })
    apiClient.post.mockResolvedValue({ data: { status: 'cancelling' } })
    expect(await scanApi.status('one/two')).toEqual({ status: 'running' })
    expect(apiClient.get).toHaveBeenCalledWith('/scan/status/one%2Ftwo')
    expect(await scanApi.cancel('one')).toEqual({ status: 'cancelling' })
    expect(apiClient.post).toHaveBeenCalledWith('/scan/one/cancel')
    await scanApi.latest()
    expect(apiClient.get).toHaveBeenLastCalledWith('/scan/latest')
  })
})
