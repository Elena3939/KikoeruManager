import { beforeEach, expect, it, vi } from 'vitest'
import api from '../api'
import { useActivityHistoryLite } from './useActivityHistoryLite'

vi.mock('../api', () => ({
  default: { activityLog: { list: vi.fn(), detail: vi.fn() } },
}))

beforeEach(() => vi.resetAllMocks())

it('刷新列表后重试过的父记录重新加载详情', async () => {
  const history = useActivityHistoryLite()
  api.activityLog.detail
    .mockResolvedValueOnce({ row: { id: 'parent', status: 'failed' } })
    .mockResolvedValueOnce({ row: { id: 'parent', status: 'success' } })
  api.activityLog.list.mockResolvedValue({
    total: 1,
    items: [{ id: 'parent', status: 'success', latest_activity_at: '2026-10-25T19:30:00' }],
  })
  expect((await history.loadDetail('parent')).status).toBe('failed')
  expect((await history.loadDetail('parent')).status).toBe('failed')
  await history.loadList()
  expect((await history.loadDetail('parent')).status).toBe('success')
  expect(api.activityLog.detail).toHaveBeenCalledTimes(2)
})

it('刷新前未完成的详情不能覆盖新详情缓存或清除新请求', async () => {
  const history = useActivityHistoryLite()
  let resolveOld
  let resolveNew
  api.activityLog.detail
    .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveNew = resolve }))
  api.activityLog.list.mockResolvedValue({ total: 1, items: [{ id: 'parent', status: 'success' }] })
  const oldRequest = history.loadDetail('parent')
  await history.loadList()
  const newRequest = history.loadDetail('parent')
  resolveOld({ row: { id: 'parent', status: 'failed' } })
  await oldRequest
  expect(history.detailLoading.value).toBe(true)
  const sharedNewRequest = history.loadDetail('parent')
  expect(api.activityLog.detail).toHaveBeenCalledTimes(2)
  resolveNew({ row: { id: 'parent', status: 'success' } })
  expect((await newRequest).status).toBe('success')
  expect((await sharedNewRequest).status).toBe('success')
  expect((await history.loadDetail('parent')).status).toBe('success')
  expect(history.detailLoading.value).toBe(false)
})
