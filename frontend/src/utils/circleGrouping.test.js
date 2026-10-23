import { describe, expect, it, vi } from 'vitest'
import { classifyCircleFolder } from './circleGrouping'

describe('纯社团分类', () => {
  it('未识别社团时报告错误，禁止调用重命名接口或再次分类', async () => {
    const api = {
      autoCircleGroup: vi.fn().mockResolvedValue({ success: false, error: '未识别社团，未操作' }),
      apiRename: vi.fn()
    }
    await expect(classifyCircleFolder(api, 'local', '/library/RJ123456')).rejects.toThrow('未识别社团，未操作')
    expect(api.autoCircleGroup).toHaveBeenCalledTimes(1)
    expect(api.autoCircleGroup).toHaveBeenCalledWith('local', '/library/RJ123456')
    expect(api.apiRename).not.toHaveBeenCalled()
  })

  it('服务端报错直接交给调用者，不启动重命名', async () => {
    const error = new Error('未识别社团')
    const api = { autoCircleGroup: vi.fn().mockRejectedValue(error), apiRename: vi.fn() }
    await expect(classifyCircleFolder(api, 'local', '/folder')).rejects.toBe(error)
    expect(api.apiRename).not.toHaveBeenCalled()
  })

  it('保留移动结果和索引围栏', async () => {
    const result = { success: true, result: { index_fences: [{ seq: 7 }] } }
    const api = { autoCircleGroup: vi.fn().mockResolvedValue(result) }
    await expect(classifyCircleFolder(api, 'local', '/folder')).resolves.toBe(result)
  })
})
