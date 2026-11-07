import { afterEach, describe, expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'

describe('上传分块摘要线程', () => {
  afterEach(() => vi.unstubAllGlobals())

  it.each([true, false])('WebCrypto 可用=%s 时保持相同摘要和可转移数据', async available => {
    vi.resetModules()
    const worker = { crypto: available ? webcrypto : undefined, postMessage: vi.fn() }
    vi.stubGlobal('self', worker)
    await import('./browserUploadHash.worker')
    const buffer = new Uint8Array([97, 98, 99]).buffer
    await worker.onmessage({ data: { id: 1, buffer } })
    expect(worker.postMessage).toHaveBeenCalledWith({ id: 1, buffer,
      digest: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' }, [buffer])
  })
})
