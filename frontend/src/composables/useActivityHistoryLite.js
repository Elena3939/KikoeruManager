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
 *
 * Phase 6 卡死修复：
 * - 维护 listAbortController，每次发起新搜索前先 abort 上一次未完成请求，
 *   配合后端取消 LIKE 全表炸弹 fallback，搜索绝不再卡死前端。
 * - listReqSeq 串号：只让最后一次发起的请求结果落到 state，避免老响应
 *   覆盖新响应造成 UI 闪烁。
 * - 暴露 searchBackend / searchStatus，给搜索框旁的状态指示灯 / 设置面板用。
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
  // 后端返回的搜索后端标记，用于前端区分「真 0 行」/「索引未就绪」/「输入清洗后为空」
  // 取值示例：'fts5_trigram' / 'fts5_unicode61' / 'unavailable' / 'fts5_trigram_error'
  // / 'sanitized_empty' / 'none'（未搜索）
  const searchBackend = shallowRef('none')

  // 搜索引擎状态（FTS5 启用 / tokenizer / 重建进度）
  const searchStatus = shallowRef({
    fts_enabled: false,
    tokenizer: '',
    trigram_supported: false,
    needs_upgrade: false,
    row_count: 0,
    fts_row_count: 0,
    rebuild: { running: false, copied: 0, total: 0, ok: null, reason: '' }
  })

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

  // 列表请求的取消 + 串号保护：保证「最后发起的请求」才能写 state
  let listAbortController = null
  let listReqSeq = 0

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
    // 取消上一次未完成的请求；axios 收到 abort 会以 CanceledError 拒绝 promise
    if (listAbortController) {
      try { listAbortController.abort() } catch {}
    }
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    listAbortController = controller
    const seq = ++listReqSeq

    loading.value = true
    try {
      const data = await api.activityLog.list(
        {
          page: page.value,
          limit: limit.value,
          category: filters.category || undefined,
          status: filters.status || undefined,
          q: filters.q.trim() || undefined,
          lite: true
        },
        controller ? { signal: controller.signal } : {}
      )
      // 串号保护：只让最后一次发起的请求结果落地
      if (seq !== listReqSeq) return
      items.value = data.items || []
      total.value = data.total || 0
      const window = data?.window || {}
      searchBackend.value = String(window.search_backend || 'none')
    } catch (err) {
      // axios 在 abort 时会抛 CanceledError，名字 'CanceledError' 或 code 'ERR_CANCELED'
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
        return
      }
      // 当前请求是否仍是「最后一次」，不是就静默忽略错误
      if (seq !== listReqSeq) return
      console.warn('[活动记录] 加载列表失败', err)
      items.value = []
      total.value = 0
      searchBackend.value = 'error'
    } finally {
      // 仅在自己仍是当前活跃 controller 时清掉 loading；否则交给后续请求的 finally 处理
      if (seq === listReqSeq) {
        loading.value = false
      }
    }
  }

  async function loadAll() {
    await Promise.all([loadStats(), loadList()])
    lastLoadedAt.value = Date.now()
  }

  /**
   * 拉取后端搜索引擎状态（FTS5 是否启用 / tokenizer / 重建进度）。
   * 设置页 + 搜索框旁状态徽章共用。失败时不抛，仅打 warning。
   */
  async function loadSearchStatus() {
    try {
      const data = await api.activityLog.searchStatus()
      searchStatus.value = {
        fts_enabled: !!data.fts_enabled,
        tokenizer: String(data.tokenizer || ''),
        trigram_supported: !!data.trigram_supported,
        needs_upgrade: !!data.needs_upgrade,
        row_count: Number(data.row_count || 0),
        fts_row_count: Number(data.fts_row_count || 0),
        rebuild: {
          running: !!(data.rebuild && data.rebuild.running),
          copied: Number(data?.rebuild?.copied || 0),
          total: Number(data?.rebuild?.total || 0),
          ok: data?.rebuild?.ok ?? null,
          reason: String(data?.rebuild?.reason || ''),
          target_tokenizer: String(data?.rebuild?.target_tokenizer || ''),
          started_at: Number(data?.rebuild?.started_at || 0),
          finished_at: Number(data?.rebuild?.finished_at || 0)
        }
      }
    } catch (err) {
      console.warn('[活动记录] 加载搜索引擎状态失败', err)
    }
  }

  /**
   * 触发后台重建 FTS5 索引。本函数只发起请求，进度靠 loadSearchStatus 轮询。
   */
  async function rebuildFts(targetTokenizer = 'trigram') {
    return api.activityLog.rebuildFts(targetTokenizer)
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
    searchBackend,
    searchStatus,
    loadStats,
    loadList,
    loadAll,
    loadDetail,
    invalidateDetail,
    loadSearchStatus,
    rebuildFts,
    applyFilters,
    onPageSizeChange,
    shouldSoftRefresh,
    handleVisibilityRefresh
  }
}
