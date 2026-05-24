import axios from 'axios'
import { ref } from 'vue'

const DEFAULT_DEV_BACKEND_PORT = '5555'

function resolveApiBase() {
  const configured = String(import.meta.env.VITE_API_BASE || '').trim()
  if (configured) return configured.replace(/\/$/, '')

  if (import.meta.env.DEV && typeof window !== 'undefined' && window.location.port === '5556') {
    const backendPort = String(import.meta.env.VITE_BACKEND_PORT || DEFAULT_DEV_BACKEND_PORT).trim()
    return `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`
  }

  return '/api'
}

export const API_BASE = resolveApiBase()

export function apiUrl(path = '') {
  const suffix = String(path || '')
  if (!suffix) return API_BASE
  return `${API_BASE}${suffix.startsWith('/') ? suffix : `/${suffix}`}`
}

export function apiFetchOptions(options = {}) {
  const next = { ...options }
  if (!next.credentials) {
    next.credentials = 'include'
  }
  return next
}

const FILTER_DELETE_PREVIEW_TIMEOUT = 30 * 60 * 1000
const CONFLICT_MERGE_TIMEOUT = 30 * 60 * 1000
const RJ_SUBTITLE_SCAN_TIMEOUT = 0

/** 群晖 OTP 二步验证过期标志。任意库存接口返回含 OTP 的错误时置 true，提示用户刷新 Device Token。 */
export const synologyOtpRequired = ref(false)

const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json; charset=utf-8'
  }
})

apiClient.interceptors.response.use(
  response => response,
  error => {
    const detail = error.response?.data?.detail || error.message || '未知错误'
    console.error('[API Error]', error.config?.url, detail)
    if (typeof detail === 'string' && detail.includes('OTP')) {
      synologyOtpRequired.value = true
    }
    if (error.response?.data?.gate_required && window.location.pathname !== '/verify') {
      const next = encodeURIComponent(window.location.pathname + window.location.search)
      window.location.assign(`/verify?next=${next}`)
    } else if (error.response?.data?.blocked && window.location.pathname !== '/blocked') {
      window.location.assign('/blocked')
    }
    return Promise.reject(error)
  }
)

export const taskApi = {
  // 兼容层：
  // 这组接口只保留给少数历史链路使用，对应后端旧 /api/tasks/*。
  // 新页面、新组件、新任务交互统一使用 taskCenterApi，不要再新增对 taskApi 的依赖。
  list: async (status = null) => {
    const params = status ? { status } : {}
    const response = await apiClient.get('/tasks', { params })
    return response.data
  },

  get: async (taskId) => {
    const response = await apiClient.get(`/tasks/${taskId}`)
    return response.data
  },

  create: async (sourcePath, taskType = 'auto_process', autoClassify = true, targetLibraryId = null) => {
    const response = await apiClient.post('/tasks', {
      source_path: sourcePath,
      task_type: taskType,
      auto_classify: autoClassify,
      target_library_id: targetLibraryId
    })
    return response.data
  },

  pause: async (taskId) => {
    const response = await apiClient.post(`/tasks/${taskId}/pause`)
    return response.data
  },

  resume: async (taskId) => {
    const response = await apiClient.post(`/tasks/${taskId}/resume`)
    return response.data
  },

  cancel: async (taskId) => {
    const response = await apiClient.post(`/tasks/${taskId}/cancel`)
    return response.data
  },

  batchCancelCleanup: async (taskIds) => {
    const response = await apiClient.post('/tasks/batch-cancel-cleanup', { task_ids: taskIds })
    return response.data
  }
}

export const taskCenterApi = {
  overview: async (params = {}) => {
    const response = await apiClient.get('/task-center/overview', { params })
    return response.data
  },

  list: async (params = {}) => {
    const response = await apiClient.get('/task-center/list', { params })
    return response.data
  },

  getItem: async (params = {}) => {
    const response = await apiClient.get('/task-center/item', { params })
    return response.data
  },

  action: async (itemId, action) => {
    const response = await apiClient.post(`/task-center/${encodeURIComponent(itemId)}/action`, { action })
    return response.data
  }
}

export const configApi = {
  get: async () => {
    const response = await apiClient.get('/config')
    return response.data
  },

  save: async (configData) => {
    const response = await apiClient.post('/config', configData)
    return response.data
  },

  reload: async () => {
    const response = await apiClient.post('/config/reload')
    return response.data
  },

  state: async () => {
    const response = await apiClient.get('/config/state')
    return response.data
  }
}

export const securityGateApi = {
  status: async () => {
    const response = await apiClient.get('/security-gate/status')
    return response.data
  },

  verify: async ({ code, remember = false }) => {
    const response = await apiClient.post('/security-gate/verify', { code, remember })
    return response.data
  },

  logout: async () => {
    const response = await apiClient.post('/security-gate/logout')
    return response.data
  },

  createSetup: async () => {
    const response = await apiClient.post('/security-gate/setup')
    return response.data
  },

  confirmSetup: async (code) => {
    const response = await apiClient.post('/security-gate/setup/confirm', { code })
    return response.data
  },

  resetSetup: async () => {
    const response = await apiClient.post('/security-gate/setup/reset')
    return response.data
  },

  logs: async (params = {}) => {
    const response = await apiClient.get('/security-gate/logs', { params })
    return response.data
  },

  blacklist: async (params = {}) => {
    const response = await apiClient.get('/security-gate/blacklist', { params })
    return response.data
  },

  unblock: async (id, reason = '') => {
    const response = await apiClient.post(`/security-gate/blacklist/${id}/unblock`, { reason })
    return response.data
  }
}

export const systemApi = {
  /**
   * 探测 temp_path / library_path / input_path 所在盘的存储类型。
   * 返回形如：
   * {
   *   primary_type: 'ssd' | 'hdd' | 'unknown',
   *   probes: [{ label, attr, path, type }],
   *   resolved_limit: 3,                // auto 模式下实际会生效的并发数
   *   resolved_reason: 'auto: 检测到 SSD ...',
   *   configured: 0,                     // 0 表示 auto
   *   max_workers: 6,
   * }
   */
  storageInfo: async () => {
    const response = await apiClient.get('/system/storage-info')
    return response.data
  }
}

export const activityLogApi = {
  // 第二参数支持 { signal } 透传给 axios，配合 AbortController 取消未完成的搜索请求
  list: async (params = {}, options = {}) => {
    const config = { params }
    if (options.signal) config.signal = options.signal
    const response = await apiClient.get('/activity-logs', config)
    return response.data
  },

  stats: async (params = {}) => {
    const response = await apiClient.get('/activity-logs/stats', { params })
    return response.data
  },

  children: async (logId, params = {}) => {
    const response = await apiClient.get(`/activity-logs/${logId}/children`, { params })
    return response.data
  },

  detail: async (logId) => {
    const response = await apiClient.get(`/activity-logs/${logId}/detail`)
    return response.data
  },

  compactEstimate: async (params = {}) => {
    const response = await apiClient.get('/activity-logs/compact/estimate', { params })
    return response.data
  },

  compact: async (params = {}) => {
    const response = await apiClient.post('/activity-logs/compact', null, { params })
    return response.data
  },

  logFilterDelete: async (payload = {}) => {
    const response = await apiClient.post('/activity-logs/filter-delete', payload)
    return response.data
  },

  // 搜索引擎状态：FTS5 是否启用、tokenizer、是否需要升级、后台重建进度
  searchStatus: async () => {
    const response = await apiClient.get('/activity-logs/search-status')
    return response.data
  },

  // 触发后台重建 FTS5 索引（默认目标 trigram）
  rebuildFts: async (targetTokenizer = 'trigram') => {
    const response = await apiClient.post('/activity-logs/rebuild-fts', null, {
      params: { target_tokenizer: targetTokenizer }
    })
    return response.data
  }
}

export const databaseMaintenanceApi = {
  // 估算一键瘦身能释放多少空间 + 返回当前 db/-wal/-shm 文件大小快照
  estimate: async (params = {}) => {
    const response = await apiClient.get('/database/maintenance/estimate', { params })
    return response.data
  },

  // 启动一次瘦身。幂等：已在跑时返回 already_running=true
  startShrink: async (params = {}) => {
    // VACUUM 可能跑几分钟，给一个长一点的请求超时（启动接口本身只是丢线程，会立刻返回，
    // 但万一进程慢，留 120s 余量）
    const response = await apiClient.post('/database/maintenance/shrink', null, { params, timeout: 120000 })
    return response.data
  },

  // 轮询瘦身状态
  shrinkStatus: async () => {
    const response = await apiClient.get('/database/maintenance/shrink/status')
    return response.data
  },

  // 把 done / error 状态清回 idle（运行中调用无效）
  shrinkReset: async () => {
    const response = await apiClient.post('/database/maintenance/shrink/reset')
    return response.data
  },

  // 读取库存索引 FTS5 状态和后台重建进度
  libraryIndexFtsStatus: async () => {
    const response = await apiClient.get('/database/maintenance/library-index-fts/status')
    return response.data
  },

  // 后台重建库存索引 FTS5 表（默认目标 trigram）
  rebuildLibraryIndexFts: async (targetTokenizer = 'trigram') => {
    const response = await apiClient.post('/database/maintenance/library-index-fts/rebuild', null, {
      params: { target_tokenizer: targetTokenizer }
    })
    return response.data
  }
}

export const backupApi = {
  status: async () => {
    const response = await apiClient.get('/library-backup/status')
    return response.data
  },

  start: async () => {
    const response = await apiClient.post('/library-backup/start')
    return response.data
  },

  cancel: async () => {
    const response = await apiClient.post('/library-backup/cancel')
    return response.data
  },

  resume: async () => {
    const response = await apiClient.post('/library-backup/resume')
    return response.data
  },

  checkpoint: async () => {
    const response = await apiClient.get('/library-backup/checkpoint')
    return response.data
  },

  history: async () => {
    const response = await apiClient.get('/backup/history')
    return response.data
  }
}

export const watcherApi = {
  status: async () => {
    const response = await apiClient.get('/watcher/status')
    return response.data
  },

  start: async () => {
    const response = await apiClient.post('/watcher/start')
    return response.data
  },

  stop: async () => {
    const response = await apiClient.post('/watcher/stop')
    return response.data
  }
}

export const scanApi = {
  scan: async () => {
    const response = await apiClient.post('/scan')
    return response.data
  }
}

export const passwordApi = {
  list: async (params = {}) => {
    const response = await apiClient.get('/passwords', { params })
    return response.data
  },

  create: async (data) => {
    const response = await apiClient.post('/passwords', {
      rjcode: data.rjcode || null,
      filename: data.filename || null,
      password: data.password,
      description: data.description || null,
      source: data.source || 'manual'
    })
    return response.data
  },

  update: async (id, data) => {
    const response = await apiClient.put(`/passwords/${id}`, data)
    return response.data
  },

  delete: async (id) => {
    const response = await apiClient.delete(`/passwords/${id}`)
    return response.data
  },

  batchCreate: async (entries) => {
    const response = await apiClient.post('/passwords/batch', entries)
    return response.data
  },

  importFromText: async (text) => {
    const response = await apiClient.post('/passwords/import-from-text', { text })
    return response.data
  },

  findForArchive: async (archivePath) => {
    const response = await apiClient.get('/passwords/find-for-archive', {
      params: { archive_path: archivePath }
    })
    return response.data
  }
}

export const logApi = {
  get: async (lines = 100, sinceOffset = -1) => {
    const params = { lines }
    if (sinceOffset >= 0) params.since_offset = sinceOffset
    const response = await apiClient.get('/logs', { params })
    return response.data
  },
  search: async (q = '', levels = [], limit = 500, cursor = 0, options = {}) => {
    const params = { limit, cursor }
    if (q) params.q = q
    if (levels.length) params.levels = levels.join(',')
    if (options.maxScanMb) params.max_scan_mb = options.maxScanMb
    if (options.includeBackups === false) params.include_backups = false
    const response = await apiClient.get('/logs/search', {
      params,
      signal: options.signal,
    })
    return response.data
  },
  info: async () => {
    const response = await apiClient.get('/logs/info')
    return response.data
  },
  cleanup: async ({ purgeBackups = false, truncateMain = false, keepTailMb = 2, rotate = false } = {}) => {
    const response = await apiClient.post('/logs/cleanup', {
      purge_backups: purgeBackups,
      truncate_main: truncateMain,
      keep_tail_mb: keepTailMb,
      rotate,
    })
    return response.data
  },
}

export const conflictApi = {
  // includeStats=false 时跳过远程 stat（目录大小、文件数、创建时间），列表秒回；
  // includeStats=true 时算完整统计，群晖 Docker / 网络挂载下可能比较慢，前端给 120s 兜底，
  // 避免 axios 默认 60s 在慢盘上误杀。前端通常先发 false 拿列表，再后台异步发 true 补齐 stats。
  // 接受 signal 让调用方能 abort 旧请求（用户连续刷新时，避免后端跑多次 + 占用网络）。
  list: async ({ includeStats = true, signal } = {}) => {
    const response = await apiClient.get('/conflicts', {
      params: { include_stats: includeStats },
      timeout: 120 * 1000,
      signal
    })
    return response.data
  },

  count: async () => {
    const response = await apiClient.get('/conflicts/count')
    return response.data
  },

  retry: async (conflictId, payload = {}) => {
    const response = await apiClient.post(`/conflicts/${conflictId}/retry`, payload)
    return response.data
  },

  // 伪装多卷压缩包 conflict 的"手动重命名分卷"提交。
  // payload = { renames: [{old, new}, ...], auto_retry: bool }
  // 后端会做原子两阶段重命名 + 可选自动起 RETRY 任务，返回 { renamed, first_volume, task_id, ... }。
  renameVolumes: async (conflictId, payload = {}) => {
    const response = await apiClient.post(`/conflicts/${conflictId}/rename-volumes`, payload, {
      timeout: 60 * 1000,
    })
    return response.data
  },

  filenamePreview: async (conflictId, payload = {}) => {
    const response = await apiClient.post(`/conflicts/${conflictId}/filename-preview`, payload, {
      timeout: 60000,
    })
    return response.data
  },

  preview: async (conflictId, action) => {
    // 合并预览改成异步 job 模式后，后端立即返回 {async: true, job_id, status: 'running', ...}，
    // HTTP 不再阻塞。KEEP_NEW 仍是同步返回 preview。前端轮询 mergePreviewJob 拿真实进度。
    const response = await apiClient.post(`/conflicts/${conflictId}/preview`, { action }, {
      timeout: 60000,
    })
    return response.data
  },

  mergePreviewJob: async (conflictId, jobId) => {
    // 合并预览异步 job 轮询接口：状态 running 时由前端按节奏继续 poll，
    // completed 时取 result（含 session_id / items / 默认 decisions），failed 时抛错。
    const response = await apiClient.get(`/conflicts/${conflictId}/preview-job/${jobId}`, {
      timeout: 30000,
    })
    return response.data
  },

  resolve: async (conflictId, payload) => {
    const requestPayload = typeof payload === 'string' ? { action: payload } : payload
    const response = await apiClient.post(`/conflicts/${conflictId}/resolve`, requestPayload, {
      // 本地合并会重建目录；远程合并还会上传差异文件。这里给用户一次完整等待窗口。
      timeout: requestPayload?.action === 'MERGE' ? CONFLICT_MERGE_TIMEOUT : 60000,
    })
    return response.data
  },

  enhancedCheck: async (rjcode, options = {}) => {
    const response = await apiClient.post('/conflicts/enhanced-check', {
      rjcode,
      check_linked_works: options.checkLinkedWorks ?? true,
      cue_languages: options.cueLanguages ?? ['CHI_HANS', 'CHI_HANT', 'ENG']
    })
    return response.data
  }
}

export const processedArchiveApi = {
  list: async (params = {}) => {
    const response = await apiClient.get('/processed-archives', { params })
    return response.data
  },

  scan: async () => {
    const response = await apiClient.post('/processed-archives/scan')
    return response.data
  },

  reprocess: async (archiveId) => {
    const response = await apiClient.post(`/processed-archives/${archiveId}/reprocess`)
    return response.data
  }
}

export const libraryApi = {
  listLibraries: async () => {
    const response = await apiClient.get('/library/libraries')
    return response.data
  },

  testConnection: async (library) => {
    const response = await apiClient.post('/library/test-connection', { library })
    return response.data
  },

  getStorageInfo: async (libraryId) => {
    const response = await apiClient.get('/library/storage-info', {
      params: { library_id: libraryId }
    })
    return response.data
  },

  // ===== 库存搜索索引（批次 5）=====
  // 在 SQLite 里常驻"库存→条目"快照，让 RJ 定位 / 名字搜索从分钟级降到毫秒级。
  // rebuild 是异步的，立即返回 syncing 状态；用 getIndexStatus 轮询 ready / error。
  rebuildIndex: async (libraryId) => {
    const response = await apiClient.post('/library/index/rebuild', {
      library_id: libraryId,
    })
    return response.data
  },

  getIndexStatus: async (libraryId = null) => {
    const response = await apiClient.get('/library/index/status', {
      params: libraryId ? { library_id: libraryId } : {},
    })
    return response.data
  },

  searchIndex: async ({
    libraryId = null,
    rjcode = null,
    name = null,
    entryType = null,
    limit = 100,
  } = {}) => {
    const response = await apiClient.get('/library/index/search', {
      params: {
        library_id: libraryId || undefined,
        rjcode: rjcode || undefined,
        name: name || undefined,
        entry_type: entryType || undefined,
        limit,
      },
    })
    return response.data
  },

  // 跨库存索引搜索：默认对所有启用库存生效，可通过 libraryIds 收窄。
  // - mode='suggest' → 仅取前 N 条（搜索框下拉）
  // - mode='full'    → 全屏面板用，limit 上限 500
  // 调用方负责传 AbortController.signal 来取消上一次飞行的请求。
  searchIndexGlobal: async ({
    keyword = '',
    libraryIds = null,
    entryType = 'all',
    mode = 'full',
    limit = 50,
    signal = undefined,
  } = {}) => {
    const csv = Array.isArray(libraryIds)
      ? libraryIds.filter(Boolean).join(',')
      : (libraryIds || '')
    const response = await apiClient.get('/library/index/global-search', {
      params: {
        keyword,
        library_ids: csv || undefined,
        entry_type: entryType || 'all',
        mode: mode || 'full',
        limit,
      },
      signal,
    })
    return response.data
  },

  // 流式跨库搜索：先推索引结果，未就绪库的兜底扫描按完成顺序逐库推送。
  // 用法：
  //   for await (const evt of libraryApi.searchIndexGlobalStream({ keyword, signal })) {
  //     if (evt.type === 'initial') ...
  //     if (evt.type === 'library') ...
  //     if (evt.type === 'done') ...
  //   }
  // 协议：NDJSON（一行一 JSON），客户端断开会触发后端 cancel。
  searchIndexGlobalStream: async function* ({
    keyword = '',
    libraryIds = null,
    entryType = 'all',
    mode = 'full',
    limit = 50,
    signal = undefined,
  } = {}) {
    const csv = Array.isArray(libraryIds)
      ? libraryIds.filter(Boolean).join(',')
      : (libraryIds || '')
    const params = new URLSearchParams()
    params.set('keyword', keyword || '')
    if (csv) params.set('library_ids', csv)
    if (entryType) params.set('entry_type', entryType)
    if (mode) params.set('mode', mode)
    if (limit != null) params.set('limit', String(limit))

    // apiClient 是 axios 实例，但 axios 不支持读 ReadableStream。这里直接走 fetch。
    // 用 apiClient.defaults.baseURL 拼出绝对 URL，与其它接口同源。
    const baseURL = (apiClient?.defaults?.baseURL || '').replace(/\/$/, '')
    const url = `${baseURL}/library/index/global-search/stream?${params.toString()}`

    const response = await fetch(url, apiFetchOptions({
      method: 'GET',
      headers: { Accept: 'application/x-ndjson' },
      signal,
    }))
    if (!response.ok) {
      const text = await response.text().catch(() => '')
      const err = new Error(`HTTP ${response.status}: ${text || response.statusText}`)
      err.status = response.status
      throw err
    }
    if (!response.body) {
      throw new Error('Streaming response missing body')
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let nlIdx
        // 一次循环把缓冲里所有完整行都吐出去
        while ((nlIdx = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, nlIdx).trim()
          buffer = buffer.slice(nlIdx + 1)
          if (!line) continue
          try {
            yield JSON.parse(line)
          } catch (parseErr) {
            // 单行解析失败不打断整流，记录后跳过
            console.warn('[streamSearch] 跳过无法解析的行', parseErr, line)
          }
        }
      }
      const tail = buffer.trim()
      if (tail) {
        try { yield JSON.parse(tail) } catch (_) { /* ignore */ }
      }
    } finally {
      try { reader.cancel() } catch (_e) { /* ignore */ }
    }
  },

  browseFiles: async ({
    libraryId = null,
    page = 1,
    pageSize = 200,
    search = '',
    currentPath = '',
    sortBy = 'size',
    sortOrder = 'desc',
    forceRefresh = false,
    searchExact = false,
    searchResultKind = 'all',
    scope = 'global'
  } = {}) => {
    const response = await apiClient.get('/library/browser/files', {
      params: {
        library_id: libraryId,
        page,
        page_size: pageSize,
        search,
        current_path: currentPath || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        force_refresh: forceRefresh || undefined,
        search_exact: searchExact || undefined,
        search_result_kind: searchResultKind || undefined,
        scope: scope && scope !== 'global' ? scope : undefined
      }
    })
    return response.data
  },

  getStats: async (forceRefresh = false, libraryId = null) => {
    const response = await apiClient.get('/library/browser/stats', {
      params: {
        force_refresh: forceRefresh,
        library_id: libraryId || undefined
      }
    })
    return response.data
  },

  cancelStats: async (libraryId) => {
    const response = await apiClient.post('/library/browser/stats/cancel', {
      library_id: libraryId
    })
    return response.data
  },

  computeFolderSize: async (path) => {
    const response = await apiClient.post('/library/browser/compute-folder-size', { path })
    return response.data
  },

  getStatsLogs: async ({ libraryId = null, lines = 200 } = {}) => {
    const response = await apiClient.get('/library/browser/stats/logs', {
      params: {
        library_id: libraryId || undefined,
        lines
      }
    })
    return response.data
  },

  listFiles: async () => {
    const response = await apiClient.get('/library/files')
    return response.data
  },

  browserFolderContents: async (libraryId, path) => {
    const response = await apiClient.post('/library/browser/folder-contents', {
      library_id: libraryId,
      path
    })
    return response.data
  },

  listSubdirectories: async (libraryId, path = '') => {
    const response = await apiClient.post('/library/list-subdirectories', {
      library_id: libraryId,
      path: path || ''
    })
    return response.data
  },

  browserMojibakePreview: async (libraryId, path, options = {}) => {
    const response = await apiClient.post('/library/browser/mojibake-preview', {
      library_id: libraryId,
      path,
      selected_paths: options.selectedPaths || undefined
    })
    return response.data
  },

  browserFilterDeletePreview: async (libraryId, path, options = {}) => {
    const response = await apiClient.post('/library/browser/filter-delete-preview', {
      library_id: libraryId,
      path,
      request_id: options.requestId || undefined,
      rules: options.rules || undefined
    }, {
      timeout: options.timeout || FILTER_DELETE_PREVIEW_TIMEOUT,
      signal: options.signal
    })
    return response.data
  },

  startFilterDeletePreviewJob: async (libraryId, path, options = {}) => {
    const response = await apiClient.post('/library/browser/filter-delete-preview/start', {
      library_id: libraryId,
      path,
      rules: options.rules || undefined
    }, {
      timeout: FILTER_DELETE_PREVIEW_TIMEOUT
    })
    return response.data
  },

  getFilterDeletePreviewStatus: async (jobId) => {
    const response = await apiClient.get('/library/browser/filter-delete-preview/status', {
      params: { job_id: jobId },
      timeout: FILTER_DELETE_PREVIEW_TIMEOUT
    })
    return response.data
  },

  cancelFilterDeletePreview: async ({ requestId = null, jobId = null } = {}) => {
      const response = await apiClient.post('/library/browser/filter-delete-preview/cancel', {
      request_id: requestId || undefined,
      job_id: jobId || undefined
    })
    return response.data
  },

  folderContents: async (path) => {
    const shouldTreatAsMissingEndpoint = (error) => {
      if (error?.response?.status !== 404) return false
      const detail = String(error?.response?.data?.detail || error?.response?.data?.message || '').trim().toLowerCase()
      if (!detail) return true
      return detail === 'not found'
    }

    const localCandidates = [
      '/library/folder-contents',
      '/library/folder-content'
    ]
    for (const endpoint of localCandidates) {
      try {
        const response = await apiClient.post(endpoint, { path })
        return response.data
      } catch (error) {
        if (!shouldTreatAsMissingEndpoint(error)) {
          throw error
        }
      }
    }

    const absoluteCandidates = [
      '/api/library/folder-contents',
      '/api/library/folder-content'
    ]
    for (const endpoint of absoluteCandidates) {
      try {
        const response = await axios.post(endpoint, { path }, {
          timeout: 60000,
          headers: {
            'Content-Type': 'application/json; charset=utf-8'
          }
        })
        return response.data
      } catch (error) {
        if (!shouldTreatAsMissingEndpoint(error)) {
          throw error
        }
      }
    }
    const unsupportedError = new Error('当前后端版本不支持文件夹内容接口')
    unsupportedError.code = 'FOLDER_CONTENTS_UNSUPPORTED'
    throw unsupportedError
  },

  rename: async (path, newName) => {
    const response = await apiClient.post('/library/rename', { path, new_name: newName })
    return response.data
  },

  browserRename: async (libraryId, path, newName, options = {}) => {
    const response = await apiClient.post('/library/browser/rename', {
      library_id: libraryId,
      path,
      new_name: newName,
      skip_activity_log: options.skipActivityLog ?? false,
      batch_id: options.batchId || '',
      rename_context: options.renameContext || ''
    })
    return response.data
  },

  browserBatchRename: async (libraryId, items, options = {}) => {
    const response = await apiClient.post('/library/browser/batch-rename', {
      library_id: libraryId,
      items,
      skip_activity_log: options.skipActivityLog ?? false,
      batch_id: options.batchId || '',
      rename_context: options.renameContext || ''
    }, {
      // 批量重命名场景下默认 axios 60s 不一定够，给到 5 分钟
      timeout: options.timeout || 5 * 60 * 1000,
      signal: options.signal
    })
    return response.data
  },

  apiRename: async (path, libraryId = null) => {
    const payload = { path }
    if (libraryId) payload.library_id = libraryId
    const response = await apiClient.post('/library/api-rename', payload)
    return response.data
  },

  delete: async (path, confirmed = false) => {
    const response = await apiClient.post('/library/delete', { path, confirmed })
    return response.data
  },

  browserDelete: async (libraryId, path, confirmed = false, options = {}) => {
    const response = await apiClient.post('/library/browser/delete', {
      library_id: libraryId,
      path,
      confirmed,
      skip_activity_log: options.skipActivityLog ?? false,
      batch_id: options.batchId || ''
    })
    return response.data
  },

  batchDelete: async (paths, confirmed = false) => {
    const response = await apiClient.post('/library/batch-delete', { paths, confirmed })
    return response.data
  },

  browserBatchDelete: async (libraryId, paths, confirmed = false) => {
    const response = await apiClient.post('/library/browser/batch-delete', {
      library_id: libraryId,
      paths,
      confirmed
    })
    return response.data
  },

  batchApiRename: async (paths) => {
    const response = await apiClient.post('/library/batch-api-rename', { paths })
    return response.data
  },

  openFolder: async (path, forceLocal = false) => {
    const response = await apiClient.post('/library/open-folder', { path, force_local: forceLocal })
    return response.data
  },

  browserOpenFolder: async (libraryId, path, forceLocal = false) => {
    const response = await apiClient.post('/library/browser/open-folder', {
      library_id: libraryId,
      path,
      force_local: forceLocal
    })
    return response.data
  },

  browserPreviewUrl: (libraryId, path) => {
    const params = new URLSearchParams()
    params.set('library_id', libraryId || '')
    params.set('path', path || '')
    return apiUrl(`/library/browser/preview?${params.toString()}`)
  },

  browserListFolders: async (libraryId, path = '', options = {}) => {
    const payload = {
      library_id: libraryId,
      path: path || ''
    }
    if (options && typeof options === 'object') {
      if (options.computeSize !== undefined) payload.compute_size = !!options.computeSize
      if (options.computeSizeCap !== undefined && options.computeSizeCap !== null) {
        const cap = Number(options.computeSizeCap)
        if (Number.isFinite(cap) && cap > 0) payload.compute_size_cap = Math.floor(cap)
      }
      if (options.includeFiles !== undefined) payload.include_files = !!options.includeFiles
    }
    const response = await apiClient.post('/library/browser/list-folders', payload)
    return response.data
  },

  browserMove: async (sourceLibraryId, paths, targetLibraryId, targetPath = '', options = {}) => {
    const response = await apiClient.post('/library/browser/move', {
      source_library_id: sourceLibraryId,
      target_library_id: targetLibraryId,
      paths,
      target_path: targetPath || '',
      conflict_strategy: options.conflictStrategy || 'suffix',
      overwrite: !!options.overwrite
    })
    return response.data
  },

  autoCircleGroup: async (libraryId, rowPath, { preview = false } = {}) => {
    const response = await apiClient.post('/library/auto-circle-group', {
      library_id: libraryId,
      row_path: rowPath,
      preview
    })
    return response.data
  }
}

export const existingFolderApi = {
  list: async () => {
    const response = await apiClient.get('/existing-folders')
    return response.data
  },

  scan: async (checkDuplicates = true, forceRefresh = false) => {
    const response = await apiClient.post('/existing-folders/scan', null, {
      params: { check_duplicates: checkDuplicates, force_refresh: forceRefresh }
    })
    return response
  },

  checkDuplicates: async (folders, options = {}) => {
    const response = await apiClient.post('/existing-folders/check-duplicates', {
      folders,
      check_linked_works: options.checkLinkedWorks ?? true,
      cue_languages: options.cueLanguages ?? ['CHI_HANS', 'CHI_HANT', 'ENG']
    })
    return response.data
  },

  process: async (folders, autoClassify = true) => {
    const response = await apiClient.post('/existing-folders/process', {
      folders,
      auto_classify: autoClassify
    })
    return response.data
  },

  delete: async (path) => {
    const response = await apiClient.post('/existing-folders/delete', { path })
    return response.data
  },

  processWithResolution: async (folderPath, resolution, autoClassify = true) => {
    const response = await apiClient.post('/existing-folders/process-with-resolution', {
      folder_path: folderPath,
      resolution,
      auto_classify: autoClassify
    })
    return response.data
  },

  refreshCache: async () => {
    const response = await apiClient.post('/existing-folders/refresh-cache')
    return response.data
  },

  clearCache: async () => {
    const response = await apiClient.post('/existing-folders/clear-cache')
    return response.data
  }
}

export const cleanupApi = {
  password: {
    status: async () => {
      const response = await apiClient.get('/password-cleanup/status')
      return response.data
    },

    preview: async () => {
      const response = await apiClient.get('/password-cleanup/preview')
      return response.data
    },

    run: async () => {
      const response = await apiClient.post('/password-cleanup/run')
      return response.data
    },

    history: async (limit = 50) => {
      const response = await apiClient.get('/password-cleanup/history', { params: { limit } })
      return response.data
    },

    restart: async () => {
      const response = await apiClient.post('/password-cleanup/restart')
      return response.data
    }
  },

  archive: {
    status: async () => {
      const response = await apiClient.get('/processed-archive-cleanup/status')
      return response.data
    },

    preview: async () => {
      const response = await apiClient.get('/processed-archive-cleanup/preview')
      return response.data
    },

    run: async () => {
      const response = await apiClient.post('/processed-archive-cleanup/run')
      return response.data
    },

    history: async (limit = 50) => {
      const response = await apiClient.get('/processed-archive-cleanup/history', { params: { limit } })
      return response.data
    },

    restart: async () => {
      const response = await apiClient.post('/processed-archive-cleanup/restart')
      return response.data
    }
  }
}

export const pathMappingApi = {
  config: async () => {
    const response = await apiClient.get('/path-mapping/config')
    return response.data
  },

  save: async (data) => {
    const response = await apiClient.post('/path-mapping/config', data)
    return response.data
  },

  test: async (path) => {
    const response = await apiClient.post('/path-mapping/test', { path })
    return response.data
  }
}

export const kikoeruApi = {
  config: async () => {
    const response = await apiClient.get('/kikoeru-server/config')
    return response.data
  },

  saveConfig: async (config) => {
    const response = await apiClient.post('/kikoeru-server/config', config)
    return response.data
  },

  getToken: async () => {
    const response = await apiClient.post('/kikoeru-server/get-token')
    return response.data
  },

  testConnection: async () => {
    const response = await apiClient.post('/kikoeru-server/test')
    return response.data
  },

  check: async (rjcode, checkLinkages = true, cueLanguages = 'CHI_HANS CHI_HANT ENG JPN') => {
    const response = await apiClient.post('/kikoeru-server/check', null, {
      params: { rjcode, check_linkages: checkLinkages, cue_languages: cueLanguages }
    })
    return response.data
  },

  clearCache: async () => {
    const response = await apiClient.post('/kikoeru-server/clear-cache')
    return response.data
  },

  linkedWorks: async (rjcode, options = {}) => {
    const response = await apiClient.get(`/linked-works/${rjcode}`, {
      params: {
        include_full_linkage: options.includeFullLinkage ?? true,
        cue_languages: options.cueLanguages ?? 'CHI_HANS,CHI_HANT,ENG'
      }
    })
    return response.data
  },

  checkLibrary: async (rjcode, cueLanguages = 'CHI_HANS,CHI_HANT,ENG') => {
    const response = await apiClient.get(`/linked-works/${rjcode}/check-library`, {
      params: { cue_languages: cueLanguages }
    })
    return response.data
  },

  searchConfigs: async () => {
    const response = await apiClient.get('/kikoeru-configs')
    return response.data
  },

  createSearchConfig: async (data) => {
    const response = await apiClient.post('/kikoeru-configs', data)
    return response.data
  },

  updateSearchConfig: async (configId, data) => {
    const response = await apiClient.put(`/kikoeru-configs/${configId}`, data)
    return response.data
  },

  deleteSearchConfig: async (configId) => {
    const response = await apiClient.delete(`/kikoeru-configs/${configId}`)
    return response.data
  }
}

export const healthApi = {
  check: async () => {
    const response = await apiClient.get('/health')
    return response.data
  }
}

export const asmrSyncApi = {
  scan: async (folderPath) => {
    const response = await apiClient.post('/asmr-sync/scan', { folder_path: folderPath })
    return response.data
  },

  planEnhanced: async (payload) => {
    const response = await apiClient.post('/asmr-sync/enhanced/plan', payload)
    return response.data
  },

  startEnhanced: async (items, autoClassify = false) => {
    const response = await apiClient.post('/asmr-sync/enhanced/start', {
      items,
      auto_classify: autoClassify
    })
    return response.data
  },

  locateRJ: async (rjcodes, libraryIds = null) => {
    const response = await apiClient.post('/asmr-sync/enhanced/locate-rj', {
      rjcodes,
      library_ids: libraryIds || undefined
    })
    return response.data
  },

  dashboardEnhanced: async () => {
    const response = await apiClient.get('/asmr-sync/enhanced/dashboard')
    return response.data
  },

  sessionsEnhanced: async (limit = 50) => {
    const response = await apiClient.get('/asmr-sync/enhanced/sessions', { params: { limit } })
    return response.data
  },

  sessionEnhanced: async (sessionId) => {
    const response = await apiClient.get(`/asmr-sync/enhanced/sessions/${sessionId}`)
    return response.data
  },

  updateSessionPriority: async (sessionId, queuePriority) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/priority`, {
      queue_priority: queuePriority
    })
    return response.data
  },

  pauseSession: async (sessionId) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/pause`)
    return response.data
  },

  resumeSession: async (sessionId) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/resume`)
    return response.data
  },

  cancelSession: async (sessionId, { cleanup = true } = {}) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/cancel`, { cleanup })
    return response.data
  },

  retryFailedSession: async (sessionId) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/retry-failed`)
    return response.data
  },

  retrySessionFiles: async (sessionId, relativePaths = []) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/retry-files`, {
      relative_paths: relativePaths
    })
    return response.data
  },

  reimportDownloadedSession: async (sessionId, payload = {}) => {
    const response = await apiClient.post(`/asmr-sync/enhanced/sessions/${sessionId}/reimport-downloaded`, {
      target_library_id: payload.targetLibraryId || '',
      target_subdir: payload.targetSubdir || ''
    })
    return response.data
  },

  reimportLocalDownload: async (payload = {}) => {
    const response = await apiClient.post('/asmr-sync/enhanced/reimport-local-download', {
      download_root: payload.downloadRoot || '',
      rjcode: payload.rjcode || '',
      circle_name: payload.circleName || '',
      target_library_id: payload.targetLibraryId || '',
      target_subdir: payload.targetSubdir || ''
    })
    return response.data
  },

  preview: async (rjcode) => {
    const response = await apiClient.post('/asmr-sync/preview', { rjcode })
    return response.data
  },

  start: async (items, autoClassify = true) => {
    const response = await apiClient.post('/asmr-sync/start', {
      items,
      auto_classify: autoClassify
    })
    return response.data
  },

  status: async () => {
    const response = await apiClient.get('/asmr-sync/status')
    return response.data
  },

  getWaitingRetry: async () => {
    const response = await apiClient.get('/asmr-sync/waiting-retry')
    return response.data
  },

  pause: async (taskId) => {
    const response = await apiClient.post(`/asmr-sync/task/${taskId}/pause`)
    return response.data
  },

  resume: async (taskId) => {
    const response = await apiClient.post(`/asmr-sync/task/${taskId}/resume`)
    return response.data
  },

  retry: async (taskId) => {
    const response = await apiClient.post(`/asmr-sync/task/${taskId}/retry`)
    return response.data
  },

  retryWaiting: async (taskId) => {
    const response = await apiClient.post(`/asmr-sync/task/${taskId}/retry-waiting`)
    return response.data
  },

  deleteWaitingRetry: async (taskId) => {
    const response = await apiClient.delete(`/asmr-sync/task/${taskId}/waiting-retry`)
    return response.data
  }
}

export const rjSubtitleApi = {
  scan: async (folderPath, options = {}) => {
    const response = await apiClient.post('/rj-subtitle/scan', {
      folder_path: folderPath,
      library_id: options.libraryId || undefined,
      scan_depth: options.scanDepth ?? 3
    }, {
      timeout: options.timeout ?? RJ_SUBTITLE_SCAN_TIMEOUT
    })
    return response.data
  },

  scanStream: async (folderPath, options = {}) => {
    const response = await fetch(apiUrl('/rj-subtitle/scan-stream'), apiFetchOptions({
      method: 'POST',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'application/x-ndjson'
      },
      body: JSON.stringify({
        folder_path: folderPath,
        library_id: options.libraryId || undefined,
        scan_depth: options.scanDepth ?? 3
      }),
      signal: options.signal,
    }))

    if (!response.ok) {
      let detail = response.statusText || '扫描失败'
      try {
        const data = await response.json()
        detail = data?.detail || detail
      } catch (_) {
      }
      throw new Error(detail)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('当前浏览器不支持流式读取')
    }

    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.trim()) continue
        const payload = JSON.parse(line)
        await Promise.resolve(options.onEvent?.(payload))
      }
    }

    if (buffer.trim()) {
      const payload = JSON.parse(buffer)
      await Promise.resolve(options.onEvent?.(payload))
    }
  },

  start: async (items, options = {}) => {
    const response = await apiClient.post('/rj-subtitle/start', {
      items,
      overwrite_existing: options.overwriteExisting ?? false,
      enable_metadata_match: options.enableMetadataMatch ?? true,
      skip_if_existing_subtitles: options.skipIfExistingSubtitles ?? false,
      force_rerun: options.forceRerun ?? false,
      naming_strategy: options.namingStrategy ?? 'audio',
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || [],
      batch_context: options.batchContext || null
    })
    return response.data
  },

  status: async () => {
    const response = await apiClient.get('/rj-subtitle/status')
    return response.data
  },

  cancel: async (taskId) => {
    const response = await apiClient.post(`/tasks/${taskId}/cancel`)
    return response.data
  },

  completeManual: async (taskId, payload = {}) => {
    const response = await apiClient.post(`/rj-subtitle/task/${taskId}/manual-complete`, {
      applied_pairs: payload.appliedPairs ?? 0,
      deleted_subtitles: payload.deletedSubtitles ?? 0,
      naming_strategy: payload.namingStrategy || 'audio',
      pair_changes: payload.pairChanges || [],
      folder_path: payload.folderPath || '',
      library_id: payload.libraryId || '',
      rjcode: payload.rjcode || ''
    }, {
      timeout: 10 * 60 * 1000
    })
    return response.data
  },

  clearTask: async (taskId) => {
    const response = await apiClient.post(`/rj-subtitle/task/${taskId}/clear`)
    return response.data
  },

  rerunTask: async (taskId, options = {}) => {
    const response = await apiClient.post(`/rj-subtitle/task/${taskId}/rerun`, {
      overwrite_existing: options.overwriteExisting ?? false,
      enable_metadata_match: options.enableMetadataMatch ?? true,
      naming_strategy: options.namingStrategy ?? 'audio',
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    })
    return response.data
  },

  checkSubtitleAvailability: async (rjcode) => {
    const response = await apiClient.post('/rj-subtitle/subtitle-availability', {
      rjcode
    })
    return response.data
  },

  checkFolderSubtitleState: async (folderPath, options = {}) => {
    const response = await apiClient.post('/rj-subtitle/folder-subtitle-state', {
      folder_path: folderPath,
      library_id: options.libraryId || undefined
    })
    return response.data
  }
}

export const subtitleImportApi = {
  listPending: async () => {
    const response = await apiClient.get('/subtitle-import/pending')
    return response.data
  },

  cleanupTask: async (taskId) => {
    const response = await apiClient.post(`/subtitle-import/task/${taskId}/cleanup`)
    return response.data
  },

  clearPending: async (options = {}) => {
    const response = await apiClient.post('/subtitle-import/pending/clear', {
      record_ids: options.recordIds || [],
      clear_all: options.clearAll ?? false
    })
    return response.data
  },

  executePending: async (recordId, options = {}) => {
    // 字幕补配会同步走完整个解压 + 字幕分析 + 写入工作台流程，
    // 嵌套小包 + 群晖 NAS 慢盘场景下 60s 默认 timeout 经常误杀，
    // 给到 10 分钟兜底，足够覆盖正常的预检 / 解包 / stage IO。
    const response = await apiClient.post(`/subtitle-import/pending/${recordId}/execute`, {
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    }, {
      timeout: 10 * 60 * 1000,
      signal: options.signal
    })
    return response.data
  },

  previewArchive: async (archivePath, options = {}) => {
    const response = await apiClient.post('/subtitle-import/archive/preview', {
      archive_path: archivePath,
      preferred_library_id: options.preferredLibraryId || undefined
    })
    return response.data
  },

  importArchive: async (archivePath, options = {}) => {
    // 同 executePending，慢盘 / 嵌套小包场景需要更长 timeout 兜底
    const response = await apiClient.post('/subtitle-import/archive/import', {
      archive_path: archivePath,
      preferred_library_id: options.preferredLibraryId || undefined,
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    }, {
      timeout: 10 * 60 * 1000,
      signal: options.signal
    })
    return response.data
  },

  previewFolder: async (folderPath, options = {}) => {
    const response = await apiClient.post('/subtitle-import/folder/preview', {
      folder_path: folderPath,
      preferred_library_id: options.preferredLibraryId || undefined,
      source_rjcode_hint: options.sourceRJCodeHint || undefined
    })
    return response.data
  },

  importFolder: async (folderPath, options = {}) => {
    // 同 executePending，整目录扫描 + stage 复制可能耗时较长
    const response = await apiClient.post('/subtitle-import/folder/import', {
      folder_path: folderPath,
      preferred_library_id: options.preferredLibraryId || undefined,
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      source_rjcode_hint: options.sourceRJCodeHint || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    }, {
      timeout: 10 * 60 * 1000,
      signal: options.signal
    })
    return response.data
  }
}

export const circleCompletionApi = {
  searchCircles: async (keyword = '', limit = 30) => {
    const response = await apiClient.get('/circle-completion/circles', { params: { keyword, limit } })
    return response.data
  },

  listRecentIndexes: async (limit = 20) => {
    const response = await apiClient.get('/circle-completion/recent', { params: { limit } })
    return response.data
  },

  indexCircle: async (payload) => {
    const response = await apiClient.post('/circle-completion/index', payload)
    return response.data
  },

  startIndexCircle: async (payload) => {
    const response = await apiClient.post('/circle-completion/index/start', payload)
    return response.data
  },

  getIndexJobStatus: async (jobId) => {
    const response = await apiClient.get(`/circle-completion/index/jobs/${jobId}`)
    return response.data
  },

  getCircleDetail: async (circleId, options = {}) => {
    const response = await apiClient.get(`/circle-completion/circles/${circleId}`, {
      params: {
        only_missing: options.onlyMissing ?? false,
        only_downloadable: options.onlyDownloadable ?? false,
        include_dl_only: options.includeDlOnly ?? true
      },
      signal: options.signal
    })
    return response.data
  },

  previewBatchDownload: async (payload) => {
    const response = await apiClient.post('/circle-completion/download/preview', payload)
    return response.data
  },

  refreshSelectedWorks: async (payload) => {
    const response = await apiClient.post('/circle-completion/refresh-selected', payload)
    return response.data
  },

  startRefreshSelectedWorks: async (payload) => {
    const response = await apiClient.post('/circle-completion/refresh-selected/start', payload)
    return response.data
  },

  getRefreshSelectedJobStatus: async (jobId) => {
    const response = await apiClient.get(`/circle-completion/refresh-selected/jobs/${jobId}`)
    return response.data
  },

  listAllCircleNames: async () => {
    const response = await apiClient.get('/circle-completion/circles/names')
    return response.data
  },

  startBatchDownload: async (payload) => {
    const response = await apiClient.post('/circle-completion/download/start', payload)
    return response.data
  }
}

export const localUploadApi = {
  start: async (payload) => {
    const response = await apiClient.post('/local-upload/start', payload)
    return response.data
  },

  status: async (params = {}) => {
    const response = await apiClient.get('/local-upload/status', { params })
    return response.data
  }
}

export const emailWatcherApi = {
  status: async () => {
    const response = await apiClient.get('/email-watcher/status')
    return response.data
  },
  test: async (config) => {
    const response = await apiClient.post('/email-watcher/test', config)
    return response.data
  },
  pollNow: async () => {
    const response = await apiClient.post('/email-watcher/poll-now')
    return response.data
  }
}

export const notificationApi = {
  unreadCount: async () => {
    const response = await apiClient.get('/notifications/unread-count')
    return response.data
  },

  list: async (params = {}) => {
    const response = await apiClient.get('/notifications', { params })
    return response.data
  },

  markRead: async (ids) => {
    const response = await apiClient.post('/notifications/read', { ids })
    return response.data
  },

  markAllRead: async () => {
    const response = await apiClient.post('/notifications/read-all')
    return response.data
  },

  delete: async (id) => {
    const response = await apiClient.delete(`/notifications/${id}`)
    return response.data
  },

  testEmail: async (config = null) => {
    const response = await apiClient.post('/notifications/test-email', { config })
    return response.data
  },

  listTemplates: async () => {
    const response = await apiClient.get('/notifications/templates')
    return response.data
  },

  createTemplate: async (data) => {
    const response = await apiClient.post('/notifications/templates', data)
    return response.data
  },

  updateTemplate: async (id, data) => {
    const response = await apiClient.put(`/notifications/templates/${id}`, data)
    return response.data
  },

  deleteTemplate: async (id) => {
    const response = await apiClient.delete(`/notifications/templates/${id}`)
    return response.data
  },

  previewTemplate: async (templateId, payload) => {
    const response = await apiClient.post('/notifications/templates/preview', { template_id: templateId, payload })
    return response.data
  },
  previewBlocks: async (blocks, eventType = 'completed', domain = 'import', subjectTemplate = '') => {
    const response = await apiClient.post('/notifications/templates/preview-blocks', {
      requestId: Date.now().toString(),
      blocks,
      event_type: eventType,
      domain,
      subject_template: subjectTemplate,
    })
    return response.data
  }
}

export default {
  task: taskApi,
  config: configApi,
  securityGate: securityGateApi,
  system: systemApi,
  watcher: watcherApi,
  scan: scanApi,
  password: passwordApi,
  log: logApi,
  conflict: conflictApi,
  processedArchive: processedArchiveApi,
  library: libraryApi,
  existingFolder: existingFolderApi,
  cleanup: cleanupApi,
  pathMapping: pathMappingApi,
  kikoeru: kikoeruApi,
  health: healthApi,
  asmrSync: asmrSyncApi,
  rjSubtitle: rjSubtitleApi,
  subtitleImport: subtitleImportApi,
  circleCompletion: circleCompletionApi,
  localUpload: localUploadApi,
  backup: backupApi,
  activityLog: activityLogApi,
  emailWatcher: emailWatcherApi,
  notification: notificationApi
}
