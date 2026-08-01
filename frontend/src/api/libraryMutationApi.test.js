import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiClient = {
  get: vi.fn(),
  post: vi.fn(),
  interceptors: { response: { use: vi.fn() } },
}

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiClient),
    post: vi.fn(),
  },
}))

const { libraryApi } = await import('./index')

describe('库存确认型 API 幂等协议', () => {
  beforeEach(() => {
    apiClient.post.mockReset()
    apiClient.post.mockResolvedValue({ data: { ok: true } })
  })

  it('批删预览不创建 Idempotency-Key', async () => {
    await libraryApi.browserBatchDeleteTargets([
      { library_id: 'A', path: 'preview.txt' },
    ], false)

    const config = apiClient.post.mock.calls[0][2]
    expect(config?.headers?.['Idempotency-Key']).toBeUndefined()
  })

  it('确认型跨库批删使用调用方稳定 key', async () => {
    await libraryApi.browserBatchDeleteTargets([
      { library_id: 'A', path: 'one.txt' },
      { library_id: 'B', path: 'two.txt' },
    ], true, { idempotencyKey: 'delete-retry-key' })

    const config = apiClient.post.mock.calls[0][2]
    expect(config.headers['Idempotency-Key']).toBe('delete-retry-key')
  })

  it('批量重命名与 API 重命名都透传稳定 key', async () => {
    await libraryApi.browserBatchRename('A', [
      { path: 'old.txt', new_name: 'new.txt' },
    ], { idempotencyKey: 'batch-rename-key' })
    await libraryApi.apiRename('old-rj', 'A', {
      idempotencyKey: 'api-rename-key',
    })

    expect(apiClient.post.mock.calls[0][2].headers['Idempotency-Key']).toBe('batch-rename-key')
    expect(apiClient.post.mock.calls[1][2].headers['Idempotency-Key']).toBe('api-rename-key')
  })

  it('最终索引移动通知也使用稳定 key', async () => {
    await libraryApi.browserNotifyIndexMoves('A', [
      { source: 'temp.txt', destination: 'final.txt' },
    ], { idempotencyKey: 'index-move-key' })

    expect(apiClient.post.mock.calls[0][2].headers['Idempotency-Key']).toBe('index-move-key')
  })
})
