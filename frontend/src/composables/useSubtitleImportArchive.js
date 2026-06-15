import { ref, computed, watch, reactive, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from './useSystemPrompt'
import { subtitleImportApi } from '../api'

const PENDING_REFRESH_INTERVAL_MS = 4000
const AUTO_IMPORT_POLL_INTERVAL_MS = 2500

export function useSubtitleImportArchive({ 
  workbenchDialogVisible, 
  workbenchBackgroundActive, 
  getSubtitleWorkbenchFilterOptions,
  openImportedTask,
  route
}) {
  const pendingLoading = ref(false)
  const pendingRefreshing = ref(false)
  const pendingLoadedOnce = ref(false)
  const pendingItems = ref([])
  const activePendingId = ref('')
  const executingPendingId = ref('')
  const retryingPendingId = ref('')
  const pendingClearLoading = ref(false)
  const pendingClearMode = ref('')
  const archiveCandidateSelection = reactive({})
  
  const autoImportingPendingId = ref('')
  const autoImportBlockedIds = ref(new Set())
  let autoImportTimer = null
  let pendingRefreshTimer = null

  const activePendingItem = computed(() => {
    return pendingItems.value.find(item => item.id === activePendingId.value) || null
  })

  function isClearablePendingItem(item) {
    return ['PENDING', 'IMPORTED'].includes(String(item?.status || '').trim().toUpperCase())
  }

  function isImportedPendingItem(item) {
    return String(item?.status || '').trim().toUpperCase() === 'IMPORTED'
  }

  function getPendingItemWorkbenchTaskId(item) {
    const preview = item?.preview || {}
    return String(
      preview?.import_result_summary?.task_id ||
      preview?.linked_workbench_task_id ||
      ''
    ).trim()
  }

  const clearablePendingItems = computed(() => {
    return (pendingItems.value || []).filter(item => isClearablePendingItem(item))
  })

  const clearablePendingCount = computed(() => clearablePendingItems.value.length)

  const canClearActivePending = computed(() => {
    return Boolean(activePendingItem.value && isClearablePendingItem(activePendingItem.value))
  })

  const selectedArchiveCandidate = computed(() => {
    const item = activePendingItem.value
    if (!item) return null
    const key = archiveCandidateSelection[item.id]
    return (item.preview?.candidates || []).find(candidate => candidateKey(candidate) === key) || null
  })

  const canRetryActivePendingPreview = computed(() => {
    const item = activePendingItem.value
    if (!item || retryingPendingId.value) return false
    return !item.can_execute || Number(item.preview?.candidate_count || 0) <= 0
  })

  watch(activePendingItem, (item) => {
    if (!item) return
    const selected = item.preview?.selected_candidate
    if (selected) {
      archiveCandidateSelection[item.id] = candidateKey(selected)
      return
    }
    const readyCandidates = (item.preview?.candidates || []).filter(candidate => candidate?.ready_for_import)
    if (!archiveCandidateSelection[item.id] && readyCandidates.length === 1) {
      archiveCandidateSelection[item.id] = candidateKey(readyCandidates[0])
    }
  }, { immediate: true })

  watch(pendingItems, () => {
    pruneAutoImportBlockedIds()
    if (workbenchDialogVisible.value || workbenchBackgroundActive.value) {
      queueAutoImportProcessing()
    }
  }, { deep: false })

  watch(() => route.path, (path) => {
    if (path === '/subtitle-import') {
      startPendingRefreshPolling()
      queuePendingRefresh({ silent: true })
      return
    }
    stopPendingRefreshPolling()
  }, { immediate: true })

  watch(() => [workbenchDialogVisible.value, workbenchBackgroundActive.value], ([visible, backgroundActive]) => {
    if (!visible && !backgroundActive) {
      stopAutoImportPolling()
      return
    }
    startAutoImportPolling()
    queuePendingRefresh({ silent: true })
    queueAutoImportProcessing()
  })

  onMounted(() => {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handlePendingRefreshVisibilityChange)
    }
    startPendingRefreshPolling()
  })

  onActivated(() => {
    startPendingRefreshPolling()
  })

  onDeactivated(() => {
    stopPendingRefreshPolling()
  })

  onUnmounted(() => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handlePendingRefreshVisibilityChange)
    }
    stopAutoImportPolling()
    stopPendingRefreshPolling()
  })

  async function loadPendingImports(options = {}) {
    const { silent = false } = options
    if (pendingLoading.value || pendingRefreshing.value) return
    if (silent) pendingRefreshing.value = true
    else pendingLoading.value = true
    try {
      const data = await subtitleImportApi.listPending()
      pendingItems.value = data.items || []
      pendingLoadedOnce.value = true
      if (!pendingItems.value.some(item => item.id === activePendingId.value)) {
        activePendingId.value = pendingItems.value[0]?.id || ''
      }
    } catch (error) {
      if (!silent) {
        ElMessage.error('加载字幕补配预检单失败: ' + (error.response?.data?.detail || error.message))
      }
    } finally {
      if (silent) pendingRefreshing.value = false
      else pendingLoading.value = false
    }
  }

  async function clearPendingImports(clearAll = false) {
    const targetItem = activePendingItem.value
    const targetIds = clearAll
      ? clearablePendingItems.value.map(item => String(item.id || '')).filter(Boolean)
      : (isClearablePendingItem(targetItem) ? [String(targetItem?.id || '')].filter(Boolean) : [])
    if (!targetIds.length) {
      ElMessage.warning(
        clearAll
          ? '当前没有可清除的待处理预检单'
          : isImportedPendingItem(targetItem)
            ? '这条来源已导入工作台，清除会废弃对应补配上下文'
            : '请先选择一条可清理的预检单'
      )
      return
    }

    try {
      const hasImportedTargets = clearAll
        ? clearablePendingItems.value.some(item => isImportedPendingItem(item))
        : isImportedPendingItem(targetItem)
      await showSystemConfirm({
        title: clearAll ? '清空补配记录' : '清除当前补配记录',
        message: clearAll
          ? `确定清空当前 ${targetIds.length} 条字幕补配记录吗？${hasImportedTargets ? '已导入工作台的记录会同时废弃对应补配上下文；' : ''}不会删除原始压缩包。`
          : `确定清除当前这条字幕补配记录吗？${hasImportedTargets ? '它已导入工作台，会同时废弃对应补配上下文；' : ''}不会删除原始压缩包。`,
        confirmText: clearAll ? '清空' : '清除',
        cancelText: '取消',
        tone: 'warning'
      })
    } catch (_) {
      return
    }

    pendingClearLoading.value = true
    pendingClearMode.value = clearAll ? 'all' : 'single'
    try {
      const result = await subtitleImportApi.clearPending({
        recordIds: targetIds,
        clearAll
      })
      await loadPendingImports()
      ElMessage.success(
        clearAll
          ? `已清空 ${Number(result.cleared_count || 0)} 条补配记录`
          : '当前补配记录已清除'
      )
    } catch (error) {
      await loadPendingImports({ silent: true })
      ElMessage.error('清除字幕补配预检单失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      pendingClearLoading.value = false
      pendingClearMode.value = ''
    }
  }

  function openPendingItemWorkbench(item = activePendingItem.value) {
    const taskId = getPendingItemWorkbenchTaskId(item)
    if (!taskId) {
      ElMessage.warning('这条记录没有可恢复的字幕补配工作台')
      return
    }
    openImportedTask(taskId)
  }

  function getSelectedArchiveCandidateForItem(item) {
    if (!item) return null
    const key = archiveCandidateSelection[item.id]
    if (key) {
      const matched = (item.preview?.candidates || []).find(candidate => candidateKey(candidate) === key)
      if (matched) return matched
    }
    const selected = item.preview?.selected_candidate
    if (selected) return selected
    const readyCandidates = (item.preview?.candidates || []).filter(candidate => candidate?.ready_for_import)
    return readyCandidates.length === 1 ? readyCandidates[0] : null
  }

  function pruneAutoImportBlockedIds() {
    const currentIds = new Set((pendingItems.value || []).map(item => String(item.id || '')))
    autoImportBlockedIds.value = new Set(
      [...autoImportBlockedIds.value].filter(id => currentIds.has(String(id || '')))
    )
  }

  function findNextAutoImportItem() {
    return (pendingItems.value || []).find(item => (
      item?.can_execute &&
      getSelectedArchiveCandidateForItem(item) &&
      !autoImportBlockedIds.value.has(String(item.id || ''))
    )) || null
  }

  function stopAutoImportPolling() {
    if (autoImportTimer) {
      clearInterval(autoImportTimer)
      autoImportTimer = null
    }
  }

  function stopPendingRefreshPolling() {
    if (pendingRefreshTimer) {
      clearTimeout(pendingRefreshTimer)
      pendingRefreshTimer = null
    }
  }

  function startPendingRefreshPolling() {
    if (pendingRefreshTimer) return
    if (route.path !== '/subtitle-import') return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    pendingRefreshTimer = setTimeout(() => {
      pendingRefreshTimer = null
      queuePendingRefresh({ silent: true })
      startPendingRefreshPolling()
    }, PENDING_REFRESH_INTERVAL_MS)
  }

  function handlePendingRefreshVisibilityChange() {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      stopPendingRefreshPolling()
      return
    }
    if (route.path !== '/subtitle-import') return
    queuePendingRefresh({ silent: true })
    startPendingRefreshPolling()
  }

  function queuePendingRefresh(options = {}) {
    if (route.path !== '/subtitle-import') return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    if (pendingLoading.value || pendingRefreshing.value || executingPendingId.value || pendingClearLoading.value) return
    void loadPendingImports(options)
  }

  function startAutoImportPolling() {
    if (autoImportTimer) return
    autoImportTimer = setInterval(() => {
      queueAutoImportProcessing()
    }, AUTO_IMPORT_POLL_INTERVAL_MS)
  }

  function queueAutoImportProcessing() {
    if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) return
    void processAutoImportQueue()
  }

  async function processAutoImportQueue() {
    if (!workbenchDialogVisible.value && !workbenchBackgroundActive.value) return
    if (pendingLoading.value || pendingRefreshing.value || executingPendingId.value || autoImportingPendingId.value) return
    const item = findNextAutoImportItem()
    if (!item) return
    const candidate = getSelectedArchiveCandidateForItem(item)
    if (!candidate) return

    autoImportingPendingId.value = String(item.id || '')
    try {
      await executePendingImportRecord(item, candidate, { autoTriggered: true })
    } catch (error) {
      autoImportBlockedIds.value = new Set([
        ...autoImportBlockedIds.value,
        String(item.id || '')
      ])
      ElMessage.error(`自动导入 ${item.preview?.source_label || getFileName(item.source_path)} 失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      autoImportingPendingId.value = ''
    }
  }

  async function retryActivePendingPreview() {
    const item = activePendingItem.value
    if (!item?.id) return

    retryingPendingId.value = item.id
    try {
      await loadPendingImports()
      ElMessage.success('已重新检查当前预检单的目标目录候选')
    } catch (error) {
      ElMessage.error('重试候选检查失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      retryingPendingId.value = ''
    }
  }

  async function executePendingImportRecord(item, candidate, options = {}) {
    if (!item || !candidate) return null
    const { autoTriggered = false } = options
    executingPendingId.value = item.id
    // 双重保险兜底：极端情况下（浏览器 tab 被休眠 + axios 不抛 timeout）
    // promise 可能在某些环境下挂起。15 分钟还没结束时强制清空"导入中"状态，
    // 让用户能再次点击重试，避免按钮永远卡在 loading。
    const fallbackClearTimer = window.setTimeout(() => {
      if (executingPendingId.value === item.id) {
        console.warn('[subtitle-import] 导入操作超过 15 分钟未返回，强制清空 loading 状态')
        executingPendingId.value = ''
      }
    }, 15 * 60 * 1000)
    try {
      const filterOptions = getSubtitleWorkbenchFilterOptions()
      const data = await subtitleImportApi.executePending(item.id, {
        targetLibraryId: candidate.library_id,
        targetFolderPath: candidate.folder_path,
        useFilterRules: filterOptions.useFilterRules,
        subtitleFilterRules: filterOptions.subtitleFilterRules
      })
      if (!autoTriggered) {
        ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕补配导入成功，已自动加入工作台' : '字幕补配导入成功')
      }
      await loadPendingImports()
      if (data.task?.id) {
        openImportedTask(data.task.id)
      }
      return data
    } finally {
      window.clearTimeout(fallbackClearTimer)
      executingPendingId.value = ''
    }
  }

  async function executePendingImport() {
    const item = activePendingItem.value
    const candidate = selectedArchiveCandidate.value
    if (!item || !candidate) return false

    try {
      await executePendingImportRecord(item, candidate, { autoTriggered: false })
      return true
    } catch (error) {
      // ★ 容错兜底：用户痛点"实际后端已经导入成功，但前端 axios 60s timeout 抛错"。
      //   axios timeout 触发后 backend 仍可能在跑；轮询等几秒再查 pending 列表，
      //   如果该记录已经 status=IMPORTED，证明导入已成功，自动打开工作台并提示
      //   用户"已成功 + 后台归档中"，避免用户以为"卡死"重复点导入。
      const isTimeout = (error?.code === 'ECONNABORTED') ||
        /timeout of \d+ms exceeded/i.test(String(error?.message || ''))

      if (isTimeout && item?.id) {
        try {
          // 后端归档可能还在跑，但 IMPORTED 状态在 db.commit() 之后立刻可见。
          // 给后端一点缓冲时间，重试 3 次（间隔 2/4/6 秒）。
          for (let attempt = 1; attempt <= 3; attempt++) {
            await new Promise(resolve => setTimeout(resolve, attempt * 2000))
            await loadPendingImports({ silent: true })
            const refreshed = pendingItems.value.find(it => it.id === item.id)
            // 该记录消失了（被搬到已完成）或者状态非 PENDING 都说明导入成功
            const importedSuccess = !refreshed || (refreshed.status && refreshed.status !== 'PENDING')
            const importedTaskId = refreshed?.preview?.import_result_summary?.task_id ||
              refreshed?.preview?.linked_workbench_task_id ||
              ''
            if (importedSuccess) {
              ElMessage.success('字幕补配实际已导入成功（后端归档仍在后台进行）')
              if (importedTaskId) {
                openImportedTask(importedTaskId)
              }
              return true
            }
          }
        } catch (probeError) {
          console.warn('[subtitle-import] timeout 后兜底查询失败', probeError)
        }
      }

      ElMessage.error('执行字幕补配失败: ' + (error.response?.data?.detail || error.message))
      return false
    }
  }

  function candidateKey(candidate) {
    return `${candidate.library_id || ''}::${candidate.folder_path || ''}`
  }

  function getFileName(path) {
    if (!path) return ''
    return String(path).split(/[\\/]/).pop()
  }

  return {
    pendingLoading,
    pendingLoadedOnce,
    pendingItems,
    activePendingId,
    executingPendingId,
    retryingPendingId,
    pendingClearLoading,
    clearablePendingCount,
    canClearActivePending,
    archiveCandidateSelection,
    activePendingItem,
    selectedArchiveCandidate,
    canRetryActivePendingPreview,

    isImportedPendingItem,
    getPendingItemWorkbenchTaskId,
    loadPendingImports,
    clearPendingImports,
    openPendingItemWorkbench,
    retryActivePendingPreview,
    executePendingImport,
    candidateKey,
    getFileName
  }
}
