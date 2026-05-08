/**
 * useActivityHistoryLite
 * -----------------------
 * 新版操作记录页面（时间线视图）的轻量数据层。
 *
 * 设计要点：
 * - 列表接口默认走后端 ``?lite=true`` 路径：每条记录只带 chips + 摘要 + 关联键，
 *   不再回传整段 detail JSON。响应体从 ~5MB 压到 ~150KB，TTFB 量级下降。
 * - 详情走 ``/api/activity-logs/{id}/detail``，按需懒拉单条完整 detail，
 *   并由后端就近跑合并算法把同链路子行 / 子状态嵌好——前端 UI 渲染逻辑
 *   保持兼容旧版抽屉。
 * - 不再做"5000 行整窗口合并"这一步，所以把树形展开逻辑从 composable 搬到详情接口。
 */
import { reactive, shallowRef } from 'vue'
import api from '../api'

const AUTO_REFRESH_STALE_MS = 3 * 60 * 1000

export function useActivityHistoryLite() {
  const loading = shallowRef(true)
  const items = shallowRef([])
  const total = shallowRef(0)
  const page = shallowRef(1)
  const limit = shallowRef(50)
  const lastLoadedAt = shallowRef(0)
  const detailLoading = shallowRef(false)

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

  // 单行详情按 id 缓存，关闭抽屉再打开同一行不重复请求
  const detailCache = new Map()
  const detailInflight = new Map()

  async function loadStats() {
    try {
      const data = await api.activityLog.stats({ days: statsDays.value })
      stats.days = data.days
      stats.total_in_range = data.total_in_range || 0
      stats.by_day = data.by_day || []
      stats.by_category = data.by_category || []
      stats.by_status = data.by_status || {}
      stats.metrics = data.metrics || {}
      stats.db_path = data.db_path || ''
    } catch (err) {
      console.warn('[活动记录] 加载统计失败', err)
    }
  }

  async function loadList() {
    loading.value = true
    try {
      const data = await api.activityLog.list({
        page: page.value,
        limit: limit.value,
        category: filters.category || undefined,
        status: filters.status || undefined,
        q: filters.q.trim() || undefined,
        lite: true
      })
      items.value = data.items || []
      total.value = data.total || 0
    } catch (err) {
      console.warn('[活动记录] 加载列表失败', err)
      items.value = []
      total.value = 0
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
   * 拉单行完整详情（合并算法已在后端就近跑过）。
   * 返回的 row 结构和旧版 selectedRow 完全兼容，可以直接喂给现有详情组件。
   */
  async function loadDetail(logId, { force = false } = {}) {
    if (!logId) return null
    const key = String(logId)
    if (!force && detailCache.has(key)) {
      return detailCache.get(key)
    }
    if (detailInflight.has(key)) return detailInflight.get(key)
    const promise = (async () => {
      detailLoading.value = true
      try {
        const data = await api.activityLog.detail(key)
        const row = data?.row || null
        if (row) detailCache.set(key, row)
        return row
      } finally {
        detailLoading.value = false
        detailInflight.delete(key)
      }
    })()
    detailInflight.set(key, promise)
    return promise
  }

  function invalidateDetail(logId) {
    if (logId == null) {
      detailCache.clear()
    } else {
      detailCache.delete(String(logId))
    }
  }

  return {
    loading,
    detailLoading,
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
    loadDetail,
    invalidateDetail,
    applyFilters,
    onPageSizeChange,
    shouldSoftRefresh,
    handleVisibilityRefresh
  }
}
