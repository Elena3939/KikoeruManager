import { describe, expect, it, vi } from 'vitest'
import { createApiRenameQueue } from './apiRenameQueue'

const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

describe('API 重命名追加队列', () => {
  it('运行中可追加、跨批次去重，并保留入队时的库和路径', async () => {
    const first = deferred()
    const states = []
    const execute = vi.fn().mockImplementationOnce(() => first.promise).mockResolvedValue('第二批')
    const queue = createApiRenameQueue({
      keyOf: row => `${row.library_id}:${row.path}`,
      execute,
      onState: state => states.push(state),
    })
    const a = { library_id: 'a', path: '/RJ1' }
    const one = queue.enqueue([a, a])
    a.path = '/改动后的选择'
    const two = queue.enqueue([{ library_id: 'a', path: '/RJ1' }, { library_id: 'b', path: '/RJ1' }])
    expect(one.count).toBe(1)
    expect(two.count).toBe(1)
    expect(execute).toHaveBeenCalledTimes(1)
    expect(states.at(-1).runningKeys).toEqual(new Set(['a:/RJ1']))
    expect(states.at(-1).targetKeys).toEqual(new Set(['a:/RJ1', 'b:/RJ1']))
    first.resolve('第一批')
    await expect(one.completion).resolves.toBe('第一批')
    await expect(two.completion).resolves.toBe('第二批')
    expect(execute.mock.calls[0][0][0].path).toBe('/RJ1')
    expect(states.at(-1).busy).toBe(false)
  })

  it('前批失败后继续后批，完成后允许失败作品重新入队', async () => {
    const first = deferred()
    const execute = vi.fn().mockImplementationOnce(async () => {
      await first.promise
      throw new Error('查询失败')
    }).mockResolvedValue('完成')
    const queue = createApiRenameQueue({ keyOf: row => row.path, execute })
    const one = queue.enqueue([{ path: 'a' }])
    const rejected = expect(one.completion).rejects.toThrow('查询失败')
    const two = queue.enqueue([{ path: 'b' }])
    first.resolve()
    await rejected
    await expect(two.completion).resolves.toBe('完成')
    const retry = queue.enqueue([{ path: 'a' }])
    expect(retry.count).toBe(1)
    await retry.completion
  })
})
