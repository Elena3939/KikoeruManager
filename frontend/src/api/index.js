import axios from 'axios'

const API_BASE = '/api'
const FILTER_DELETE_PREVIEW_TIMEOUT = 30 * 60 * 1000
const RJ_SUBTITLE_SCAN_TIMEOUT = 0

const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json; charset=utf-8'
  }
})

apiClient.interceptors.response.use(
  response => response,
  error => {
    const detail = error.response?.data?.detail || error.message || '未知错误'
    console.error('[API Error]', error.config?.url, detail)
    return Promise.reject(error)
  }
)

export const taskApi = {
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
  get: async (lines = 100) => {
    const response = await apiClient.get('/logs', { params: { lines } })
    return response.data
  }
}

export const conflictApi = {
  list: async () => {
    const response = await apiClient.get('/conflicts')
    return response.data
  },

  retry: async (conflictId) => {
    const response = await apiClient.post(`/conflicts/${conflictId}/retry`)
    return response.data
  },

  preview: async (conflictId, action) => {
    const response = await apiClient.post(`/conflicts/${conflictId}/preview`, { action })
    return response.data
  },

  resolve: async (conflictId, payload) => {
    const requestPayload = typeof payload === 'string' ? { action: payload } : payload
    const response = await apiClient.post(`/conflicts/${conflictId}/resolve`, requestPayload)
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

  browseFiles: async ({ libraryId = null, page = 1, pageSize = 200, search = '', currentPath = '', sortBy = 'size', sortOrder = 'desc', forceRefresh = false } = {}) => {
    const response = await apiClient.get('/library/browser/files', {
      params: {
        library_id: libraryId,
        page,
        page_size: pageSize,
        search,
        current_path: currentPath || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        force_refresh: forceRefresh || undefined
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

  browserFilterDeletePreview: async (libraryId, path, options = {}) => {
    const response = await apiClient.post('/library/browser/filter-delete-preview', {
      library_id: libraryId,
      path,
      request_id: options.requestId || undefined
    }, {
      timeout: options.timeout || FILTER_DELETE_PREVIEW_TIMEOUT,
      signal: options.signal
    })
    return response.data
  },

  startFilterDeletePreviewJob: async (libraryId, path) => {
    const response = await apiClient.post('/library/browser/filter-delete-preview/start', {
      library_id: libraryId,
      path
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
    const localCandidates = [
      '/library/folder-contents',
      '/library/folder-content'
    ]
    for (const endpoint of localCandidates) {
      try {
        const response = await apiClient.post(endpoint, { path })
        return response.data
      } catch (error) {
        if (error?.response?.status !== 404) {
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
        if (error?.response?.status !== 404) {
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

  browserRename: async (libraryId, path, newName) => {
    const response = await apiClient.post('/library/browser/rename', {
      library_id: libraryId,
      path,
      new_name: newName
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

  browserDelete: async (libraryId, path, confirmed = false) => {
    const response = await apiClient.post('/library/browser/delete', {
      library_id: libraryId,
      path,
      confirmed
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
    const response = await fetch(`${API_BASE}/rj-subtitle/scan-stream`, {
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
      signal: options.signal
    })

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
      naming_strategy: options.namingStrategy ?? 'audio',
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
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
      naming_strategy: payload.namingStrategy || 'audio'
    })
    return response.data
  },

  clearTask: async (taskId) => {
    const response = await apiClient.post(`/rj-subtitle/task/${taskId}/clear`)
    return response.data
  },

  checkSubtitleAvailability: async (rjcode) => {
    const response = await apiClient.post('/rj-subtitle/subtitle-availability', {
      rjcode
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
    const response = await apiClient.post(`/subtitle-import/pending/${recordId}/execute`, {
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
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
    const response = await apiClient.post('/subtitle-import/archive/import', {
      archive_path: archivePath,
      preferred_library_id: options.preferredLibraryId || undefined,
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    })
    return response.data
  },

  previewFolder: async (folderPath, options = {}) => {
    const response = await apiClient.post('/subtitle-import/folder/preview', {
      folder_path: folderPath,
      preferred_library_id: options.preferredLibraryId || undefined
    })
    return response.data
  },

  importFolder: async (folderPath, options = {}) => {
    const response = await apiClient.post('/subtitle-import/folder/import', {
      folder_path: folderPath,
      preferred_library_id: options.preferredLibraryId || undefined,
      target_library_id: options.targetLibraryId || undefined,
      target_folder_path: options.targetFolderPath || undefined,
      use_filter_rules: options.useFilterRules ?? false,
      subtitle_filter_rules: options.subtitleFilterRules || []
    })
    return response.data
  }
}

export default {
  task: taskApi,
  config: configApi,
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
  backup: backupApi
}
