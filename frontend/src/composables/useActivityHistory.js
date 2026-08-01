/**
 * useActivityHistory
 * -------------------
 * Phase 4C 拆分：把 ActivityHistory.vue 的数据层（列表 / 统计 / 过滤 / 懒拉子行）
 * 抽成一个 composable，页面本身只负责 UI 展示与装饰性交互。
 *
 * 设计要点：
 * - `items` 用 `shallowRef`：合并后的操作记录是 2~5 级深嵌套的大对象，deep reactive
 *   会让每次 loadList 都对 5000+ 行创建代理，页面滚动/切换时 CPU 占用明显。
 *   shallowRef 只跟踪 .value 指针变化；列表刷新直接整体替换、子行懒加载时用
 *   triggerRef 强制触发。
 * - `loadChildren(row)` 走新加的 `/api/activity-logs/:id/children` 索引接口：
 *   后端直接按 batch_id / parent_id / session_key 索引单次 SQL 拉子行，
 *   不再需要合并算法在 5000 行窗口里现扫；前端把返回的 items 直接塞进
 *   `row.detail.child_rows`，兼容现有 UI 的树形读取路径。
 */
import { reactive, shallowRef, triggerRef } from 'vue'
import api from '../api'

const AUTO_REFRESH_STALE_MS = 3 * 60 * 1000
const DEFAULT_CHILDREN_LIMIT = 500

export function useActivityHistory() {
  const loading = shallowRef(true)
  const items = shallowRef([])
  const total = shallowRef(0)
  const page = shallowRef(1)
  const limit = shallowRef(30)
  const lastLoadedAt = shallowRef(0)

  const stats = reactive({
    days: 14,
    total_in_range: 0,
    by_day: [],
    by_category: [],
    by_status: {},
    metrics: {},
    db_path: ''
  })
  const statsDays = shallowRef(14)

  const filters = reactive({
    q: '',
    category: '',
    status: ''
  })

  // 懒拉子行的并发控制：同一 row 正在拉时返回同一个 promise，完成后 30 秒内再点展开不再重复打网络
  const childrenInflight = new Map()
  const childrenLoadedAt = new WeakMap()

  async function loadStats() {
    const data = await api.activityLog.stats({ days: statsDays.value })
    stats.days = data.days
    stats.total_in_range = data.total_in_range || 0
    stats.by_day = data.by_day || []
    stats.by_category = data.by_category || []
    stats.by_status = data.by_status || {}
    stats.metrics = data.metrics || {}
    stats.db_path = data.db_path || ''
  }

  async function loadList() {
    loading.value = true
    try {
      const data = await api.activityLog.list({
        page: page.value,
        limit: limit.value,
        category: filters.category || undefined,
        status: filters.status || undefined,
        q: filters.q.trim() || undefined
      })
      items.value = data.items || []
      total.value = data.total || 0
    } finally {
      loading.value = false
    }
  }

  async function loadAll() {
    await Promise.all([loadStats(), loadList()])
    lastLoadedAt.value = Date.now()
  }

  function shouldSoftRefresh() {
    const lastLoaded = Number(lastLoadedAt.value || 0)
    if (!lastLoaded) return true
    return Date.now() - lastLoaded >= AUTO_REFRESH_STALE_MS
  }

  function handleVisibilityRefresh() {
    if (typeof document === 'undefined') return
    if (document.visibilityState !== 'visible') return
    if (!shouldSoftRefresh()) return
    loadAll()
  }

  function applyFilters() {
    page.value = 1
    loadList()
  }

  function onPageSizeChange() {
    page.value = 1
    loadList()
  }

  /**
   * 懒拉某条记录的子行并原地合入 `row.detail.child_rows`。
   *
   * 幂等：已加载过且未 force 时直接 resolve；并发调用共享同一 promise。
   *
   * @param {object} row  ActivityLog 合并后的父行；需要含 `id`
   * @param {object} [options]
   * @param {number} [options.limit]  后端返回子行上限，默认 500
   * @param {boolean} [options.force] 强制刷新，忽略已加载缓存
   * @returns {Promise<object[]>}  子行数组（来自后端 /children items）
   */
  async function loadChildren(row, { limit: childLimit = DEFAULT_CHILDREN_LIMIT, force = false } = {}) {
    if (!row || !row.id) return []
    const key = String(row.id)
    if (childrenInflight.has(key)) return childrenInflight.get(key)
    if (!force && childrenLoadedAt.has(row)) {
      return Array.isArray(row?.detail?.child_rows) ? row.detail.child_rows : []
    }

    const promise = (async () => {
      try {
        const data = await api.activityLog.children(key, { limit: childLimit })
        const childItems = Array.isArray(data?.items) ? data.items : []
        const nextDetail = {
          ...(row.detail && typeof row.detail === 'object' ? row.detail : {}),
          child_rows: childItems,
          child_row_count: childItems.length
        }
        row.detail = nextDetail
        row.has_child_rows = childItems.length > 0
        childrenLoadedAt.set(row, Date.now())
        // shallowRef 不跟踪深层变更，手动触发一次才能让依赖 items 的 template / watch 刷新
        triggerRef(items)
        return childItems
      } finally {
        childrenInflight.delete(key)
      }
    })()

    childrenInflight.set(key, promise)
    return promise
  }

  return {
    loading,
    items,
    total,
    page,
    limit,
    lastLoadedAt,
    stats,
    statsDays,
    filters,
    loadStats,
    loadList,
    loadAll,
    loadChildren,
    applyFilters,
    onPageSizeChange,
    shouldSoftRefresh,
    handleVisibilityRefresh
  }
}
