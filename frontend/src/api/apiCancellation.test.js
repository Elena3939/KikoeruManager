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

const { isCanceledApiRequest, rjSubtitleApi } = await import('./index')

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

  it('向字幕查询接口透传取消信号', async () => {
    apiClient.post = vi.fn().mockResolvedValue({ data: { success: true } })
    const controller = new AbortController()

    await rjSubtitleApi.checkSubtitleAvailability('RJ01234567', { signal: controller.signal })
    await rjSubtitleApi.checkFolderSubtitleState('/library/RJ01234567', {
      libraryId: 'library-a',
      signal: controller.signal,
    })
    apiClient.get = vi.fn().mockResolvedValue({ data: { tasks: [] } })
    await rjSubtitleApi.status({ signal: controller.signal })
    await rjSubtitleApi.start([{ rjcode: 'RJ01234567' }], {
      signal: controller.signal,
    })

    expect(apiClient.post).toHaveBeenNthCalledWith(
      1,
      '/rj-subtitle/subtitle-availability',
      { rjcode: 'RJ01234567' },
      { signal: controller.signal },
    )
    expect(apiClient.post).toHaveBeenNthCalledWith(
      2,
      '/rj-subtitle/folder-subtitle-state',
      {
        folder_path: '/library/RJ01234567',
        library_id: 'library-a',
      },
      { signal: controller.signal },
    )
    expect(apiClient.post).toHaveBeenNthCalledWith(
      3,
      '/rj-subtitle/start',
      expect.objectContaining({
        items: [{ rjcode: 'RJ01234567' }],
      }),
      { signal: controller.signal },
    )
    expect(apiClient.get).toHaveBeenCalledWith(
      '/rj-subtitle/status',
      { signal: controller.signal },
    )
  })
})
