/**
 * 异步批处理工具：受控并发执行。
 *
 * 用途
 * ----
 * 字幕工作台应用配对、批量重命名、批量删除等场景之前都是 `for ... await`
 * 纯串行：N 次配对 = 2N+ 次 HTTP 请求逐个等，本地也要十几秒，远程 NAS 直接
 * 几十秒不动。改成 Promise.all 又会一次性把后端打爆（数据库锁竞争 / 文件
 * 锁竞争），所以折中走"受控并发"。
 *
 * 使用
 * ----
 * ```
 * import { runWithConcurrency } from '@/composables/useAsyncBatch'
 *
 * const results = await runWithConcurrency(
 *   pairs,
 *   8,                                // 同时最多 8 个 in-flight
 *   async (pair) => {
 *     return libraryApi.browserRename(...)
 *   }
 * )
 * ```
 *
 * 行为
 * ----
 * - 保证返回结果数组与输入 items 顺序一致（`results[i]` 对应 `items[i]`）。
 * - 任一 item 抛错时，立刻 reject，但已发出的请求会跑完（不会主动 abort，
 *   因为 axios 没有提供这个 helper 通用 cancel 入口；调用方需要自己做回滚）。
 * - 限制为 1 时退化为串行，等价于原 for-await。
 */
export async function runWithConcurrency(items, limit, fn) {
  const list = Array.from(items || [])
  if (!list.length) return []
  const safeLimit = Math.max(1, Math.min(limit | 0 || 1, list.length))

  const results = new Array(list.length)
  let nextIndex = 0
  let firstError = null

  async function worker() {
    while (true) {
      if (firstError) return
      const i = nextIndex++
      if (i >= list.length) return
      try {
        results[i] = await fn(list[i], i)
      } catch (err) {
        if (!firstError) firstError = err
        return
      }
    }
  }

  const workers = []
  for (let i = 0; i < safeLimit; i += 1) {
    workers.push(worker())
  }
  await Promise.all(workers)

  if (firstError) throw firstError
  return results
}
