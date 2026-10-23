// 单个和批量操作共用队列，正在处理和等待中的路径都只接受一次。
export function createApiRenameQueue ({ keyOf, execute, onState = () => {} }) {
  const pending = []
  const activeKeys = new Set()
  let running = null
  let draining = false

  function publish () {
    onState({
      targetKeys: new Set(activeKeys),
      runningKeys: new Set((running?.rows || []).map(keyOf)),
      busy: activeKeys.size > 0,
    })
  }

  async function drain () {
    if (draining) return
    draining = true
    try {
      while (pending.length) {
        running = pending.shift()
        publish()
        try {
          running.resolve(await execute(running.rows, running.id))
        } catch (error) {
          running.reject(error)
        } finally {
          running.rows.forEach(row => activeKeys.delete(keyOf(row)))
          running = null
          publish()
        }
      }
    } finally {
      draining = false
    }
  }

  function enqueue (rows) {
    const accepted = []
    for (const row of rows) {
      const key = keyOf(row)
      if (!key || activeKeys.has(key)) continue
      activeKeys.add(key)
      accepted.push({ ...row })
    }
    if (!accepted.length) return { count: 0, completion: Promise.resolve(null) }
    const id = `api-rename-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    const completion = new Promise((resolve, reject) => {
      pending.push({ rows: accepted, id, resolve, reject })
    })
    publish()
    void drain()
    return { count: accepted.length, completion }
  }

  return { enqueue }
}
