import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Hourglass, Loader2, RefreshCw, RotateCcw } from 'lucide-react'
import { conflictApi, taskCenterApi } from '../../api'
import { Button, PageHeader } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../stores/systemPromptStore'
import { BatchRetryPasswordDialog } from './conflicts/BatchRetryPasswordDialog'
import { ConflictDetailPane } from './conflicts/ConflictDetailPane'
import { ConflictMergeWorkbench } from './conflicts/ConflictMergeWorkbench'
import { ConflictsListPane } from './conflicts/ConflictsListPane'
import { FilenamePreviewDialog } from './conflicts/FilenamePreviewDialog'
import { RetryPasswordsDialog } from './conflicts/RetryPasswordsDialog'
import { VolumeRenameDialog } from './conflicts/VolumeRenameDialog'
import {
  activeConflictStorageKey,
  buildPathPreview,
  canPreviewFilenames,
  conflictCanUseAction,
  filenameEncodingOptions,
  formatConflictLabel,
  getConflictId,
  getConflictSourcePath,
  getGarbledMeta,
  isConflictProcessing,
  isConflictRetrying,
  resolveErrorMessage,
  shouldKeepLocalRetrying
} from './conflicts/conflictUtils'
import { formatBytes } from '../utils/format'

const mergeIdleProgress = { status: 'idle', stage: '', stage_label: '', message: '', percent: 0 }

function delay(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function readActiveConflictId() {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(activeConflictStorageKey) || ''
}

export function ConflictsPage() {
  const [conflicts, setConflicts] = useState([])
  const [loading, setLoading] = useState(false)
  const [statsBackfilling, setStatsBackfilling] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [activeConflictId, setActiveConflictId] = useState(readActiveConflictId)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [selectionAnchorId, setSelectionAnchorId] = useState('')
  const [conflictFilter, setConflictFilter] = useState('all')
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchActionLabel, setBatchActionLabel] = useState('')
  const [actionState, setActionState] = useState({})
  const [localRetryingIds, setLocalRetryingIds] = useState({})
  const [filenamePreviewState, setFilenamePreviewState] = useState({})
  const [retryDialog, setRetryDialog] = useState({ open: false, conflict: null, title: '', description: '', confirmText: '开始重试' })
  const [batchRetryDialog, setBatchRetryDialog] = useState({ open: false, targets: [] })
  const [volumeRenameDialog, setVolumeRenameDialog] = useState({ open: false, conflict: null })
  const [filenameDialog, setFilenameDialog] = useState({ open: false, preview: null, confirmText: '关闭', cancelText: '' })
  const [mergeState, setMergeState] = useState({
    open: false,
    conflictId: '',
    loading: false,
    submitting: false,
    preview: null,
    decisions: {},
    progress: mergeIdleProgress
  })

  const conflictsRef = useRef([])
  const localRetryingIdsRef = useRef({})
  const retryPollersRef = useRef(new Map())
  const pendingFetchPromiseRef = useRef(null)
  const backfillAbortRef = useRef(null)
  const backfillRequestIdRef = useRef(0)
  const retryDialogResolverRef = useRef(null)
  const filenameDialogResolverRef = useRef(null)
  const mergePreviewCacheRef = useRef({})
  const mergeDecisionCacheRef = useRef({})
  const mergePreviewPollingAbortRef = useRef(null)

  useEffect(() => {
    conflictsRef.current = conflicts
  }, [conflicts])

  useEffect(() => {
    localRetryingIdsRef.current = localRetryingIds
  }, [localRetryingIds])

  useEffect(() => {
    if (activeConflictId) window.localStorage.setItem(activeConflictStorageKey, activeConflictId)
    else window.localStorage.removeItem(activeConflictStorageKey)
  }, [activeConflictId])

  const retryingConflicts = useMemo(() => conflicts.filter(conflict => isConflictRetrying(conflict, localRetryingIds)), [conflicts, localRetryingIds])
  const processingConflicts = useMemo(() => conflicts.filter(conflict => isConflictProcessing(conflict) && !isConflictRetrying(conflict, localRetryingIds)), [conflicts, localRetryingIds])
  const pendingConflicts = useMemo(() => conflicts.filter(conflict => !isConflictProcessing(conflict)), [conflicts])
  const filterOptions = useMemo(() => ([
    { value: 'all', label: `全部 ${conflicts.length}` },
    { value: 'pending', label: `待处理 ${pendingConflicts.length}` },
    { value: 'processing', label: `处理中 ${processingConflicts.length}` },
    { value: 'retrying', label: `重试中 ${retryingConflicts.length}` }
  ]), [conflicts.length, pendingConflicts.length, processingConflicts.length, retryingConflicts.length])
  const filteredConflicts = useMemo(() => {
    if (conflictFilter === 'pending') return pendingConflicts
    if (conflictFilter === 'processing') return processingConflicts
    if (conflictFilter === 'retrying') return retryingConflicts
    return conflicts
  }, [conflictFilter, conflicts, pendingConflicts, processingConflicts, retryingConflicts])
  const selectedConflicts = useMemo(() => filteredConflicts.filter(conflict => selectedIds.has(getConflictId(conflict))), [filteredConflicts, selectedIds])
  const activeConflict = useMemo(() => conflicts.find(conflict => getConflictId(conflict) === activeConflictId) || null, [activeConflictId, conflicts])
  const mergeConflict = useMemo(() => conflicts.find(conflict => getConflictId(conflict) === mergeState.conflictId) || null, [conflicts, mergeState.conflictId])

  useEffect(() => {
    setSelectedIds(previous => {
      const available = new Set(filteredConflicts.filter(conflict => !isConflictRetrying(conflict, localRetryingIds)).map(getConflictId))
      const next = new Set([...previous].filter(id => available.has(id)))
      return next.size === previous.size ? previous : next
    })
    if (!filteredConflicts.length) {
      setActiveConflictId('')
      return
    }
    if (!filteredConflicts.some(conflict => getConflictId(conflict) === activeConflictId)) {
      setActiveConflictId(getConflictId(filteredConflicts[0]))
    }
  }, [activeConflictId, filteredConflicts, localRetryingIds])

  function markAction(conflictId, action, value) {
    const key = `${conflictId}:${action}`
    setActionState(previous => {
      const next = { ...previous }
      if (value) next[key] = true
      else delete next[key]
      return next
    })
  }

  function markConflictRetrying(conflictId, value) {
    if (!conflictId) return
    setLocalRetryingIds(previous => {
      const next = { ...previous }
      if (value) next[conflictId] = true
      else delete next[conflictId]
      return next
    })
  }

  function reconcileLocalRetrying(nextConflicts) {
    setLocalRetryingIds(previous => {
      const next = { ...previous }
      for (const id of Object.keys(next)) {
        const conflict = nextConflicts.find(item => getConflictId(item) === id)
        if (!shouldKeepLocalRetrying(conflict)) delete next[id]
      }
      return next
    })
  }

  const fetchConflicts = useCallback(async () => {
    if (pendingFetchPromiseRef.current) return pendingFetchPromiseRef.current
    pendingFetchPromiseRef.current = (async () => {
      setLoading(true)
      setErrorMessage('')
      let nextConflicts = []
      try {
        const data = await conflictApi.list({ includeStats: false })
        const incoming = data?.conflicts || []
        const previousMap = new Map(conflictsRef.current.map(item => [getConflictId(item), item]))
        nextConflicts = incoming.map(next => {
          const previous = previousMap.get(getConflictId(next))
          if (!previous) return next
          return {
            ...next,
            context: {
              ...(next.context || {}),
              source: { ...(next.context?.source || {}), stats: next.context?.source?.stats ?? previous.context?.source?.stats ?? null },
              existing: { ...(next.context?.existing || {}), stats: next.context?.existing?.stats ?? previous.context?.existing?.stats ?? null }
            }
          }
        })
        setConflicts(nextConflicts)
        reconcileLocalRetrying(nextConflicts)
      } catch (error) {
        console.error('获取问题作品失败:', error)
        setErrorMessage(resolveErrorMessage(error, '获取问题作品失败'))
        return
      } finally {
        setLoading(false)
      }
      void backfillConflictStats(nextConflicts)
    })()
    try {
      return await pendingFetchPromiseRef.current
    } finally {
      pendingFetchPromiseRef.current = null
    }
  }, [])

  async function backfillConflictStats(baseConflicts = conflictsRef.current) {
    if (!baseConflicts.length) return
    const needsStats = baseConflicts.some(item => {
      const srcStats = item.context?.source?.stats
      if (!srcStats || srcStats.size == null) return true
      const existing = item.context?.existing
      if (existing && (!existing.stats || existing.stats.size == null)) return true
      return false
    })
    if (!needsStats) return
    if (backfillAbortRef.current) backfillAbortRef.current.abort()
    const controller = new AbortController()
    backfillAbortRef.current = controller
    const requestId = ++backfillRequestIdRef.current
    setStatsBackfilling(true)
    try {
      const data = await conflictApi.list({ includeStats: true, signal: controller.signal })
      if (requestId !== backfillRequestIdRef.current) return
      const incomingMap = new Map((data?.conflicts || []).map(item => [getConflictId(item), item]))
      setConflicts(previous => previous.map(item => {
        const incoming = incomingMap.get(getConflictId(item))
        return incoming ? { ...item, context: incoming.context } : item
      }))
    } catch (error) {
      if (error?.name !== 'CanceledError' && error?.code !== 'ERR_CANCELED') console.warn('后台补齐问题作品 stats 失败:', error)
    } finally {
      if (requestId === backfillRequestIdRef.current) {
        setStatsBackfilling(false)
        backfillAbortRef.current = null
      }
    }
  }

  useEffect(() => {
    fetchConflicts()
    return () => {
      for (const timerId of retryPollersRef.current.values()) window.clearTimeout(timerId)
      retryPollersRef.current.clear()
      if (backfillAbortRef.current) backfillAbortRef.current.abort()
      if (mergePreviewPollingAbortRef.current) mergePreviewPollingAbortRef.current()
    }
  }, [fetchConflicts])

  function handleConflictCardClick(conflict, event) {
    if (!getConflictId(conflict) || batchRunning || isConflictRetrying(conflict, localRetryingIds)) return
    const conflictId = getConflictId(conflict)
    const ids = filteredConflicts.map(getConflictId)
    const useRange = Boolean(event?.shiftKey) && selectionAnchorId
    const toggleMode = Boolean(event?.ctrlKey || event?.metaKey)
    if (useRange) {
      const startIndex = ids.indexOf(selectionAnchorId)
      const endIndex = ids.indexOf(conflictId)
      if (startIndex !== -1 && endIndex !== -1) {
        const [from, to] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
        setSelectedIds(new Set(ids.slice(from, to + 1)))
      } else {
        setSelectedIds(new Set([conflictId]))
      }
    } else if (toggleMode) {
      setSelectedIds(previous => {
        const next = new Set(previous)
        if (next.has(conflictId)) next.delete(conflictId)
        else next.add(conflictId)
        return next
      })
    } else {
      setSelectedIds(new Set([conflictId]))
    }
    setActiveConflictId(conflictId)
    setSelectionAnchorId(conflictId)
  }

  function toggleSelectAll() {
    const selectableIds = filteredConflicts.filter(conflict => !isConflictRetrying(conflict, localRetryingIds)).map(getConflictId)
    const allSelected = selectableIds.length > 0 && selectableIds.every(id => selectedIds.has(id))
    setSelectedIds(allSelected ? new Set() : new Set(selectableIds))
    setSelectionAnchorId(allSelected ? '' : selectableIds[selectableIds.length - 1] || '')
  }

  function selectedActionCount(action) {
    return selectedConflicts.filter(conflict => !isConflictRetrying(conflict, localRetryingIds) && conflictCanUseAction(conflict, action)).length
  }

  function getSelectedConflictsForAction(action) {
    return selectedConflicts.filter(conflict => !isConflictRetrying(conflict, localRetryingIds) && conflictCanUseAction(conflict, action))
  }

  function isBatchableActive(conflict, action) {
    const id = getConflictId(conflict)
    if (!id || selectedConflicts.length <= 1 || !selectedIds.has(id)) return false
    return selectedActionCount(action) > 1
  }

  function labelForAction(action, conflict) {
    const id = getConflictId(conflict)
    if (actionState[`${id}:${action}`]) {
      if (action === 'KEEP_NEW') return '保留新版中'
      if (action === 'SKIP') return '跳过中'
      if (action === 'RETRY') return '重试中'
    }
    if (action === 'KEEP_NEW' && isBatchableActive(conflict, action)) return `批量保留新版 (${selectedActionCount(action)})`
    if (action === 'SKIP' && isBatchableActive(conflict, action)) return `批量跳过 (${selectedActionCount(action)})`
    if (action === 'RETRY' && isBatchableActive(conflict, action)) return `批量重试 (${selectedActionCount(action)})`
    if (action === 'KEEP_NEW') return '保留新版'
    if (action === 'SKIP') return '跳过'
    if (action === 'RETRY') return isConflictRetrying(conflict, localRetryingIds) ? '重试中' : '重试'
    return action
  }

  function setBatchState(label, value) {
    setBatchRunning(value)
    setBatchActionLabel(value ? label : '')
  }

  async function presentBatchResult(actionLabel, successes, failures, extraMessage = '') {
    const title = `${actionLabel}完成：成功 ${successes.length} 项${failures.length ? `，失败 ${failures.length} 项` : ''}`
    await showSystemAlert({ title, tone: failures.length ? 'warning' : 'success' })
    if (!failures.length) return
    const detailLines = failures.slice(0, 8).map(item => `${formatConflictLabel(item.conflict)}：${item.message}`)
    if (failures.length > detailLines.length) detailLines.push(`另有 ${failures.length - detailLines.length} 项失败`)
    if (extraMessage) detailLines.unshift(extraMessage)
    await showSystemAlert({ title: `${actionLabel}详情`, message: detailLines.join('\n'), tone: 'warning' })
  }

  function removeConflict(conflictId) {
    setConflicts(previous => previous.filter(conflict => getConflictId(conflict) !== conflictId))
    setSelectedIds(previous => {
      const next = new Set(previous)
      next.delete(conflictId)
      return next
    })
    delete mergePreviewCacheRef.current[conflictId]
    delete mergeDecisionCacheRef.current[conflictId]
    if (mergeState.conflictId === conflictId) {
      setMergeState(previous => ({ ...previous, conflictId: '', preview: null, decisions: {} }))
    }
  }

  function buildKeepNewSummary(conflict, preview) {
    return [
      `将删除目标目录：${preview.path || conflict.existing_path || '-'}`,
      `文件夹数：${preview.folder_count ?? 0}`,
      `文件数：${preview.file_count ?? 0}`,
      `大小：${formatBytes(preview.size)}`
    ].join('\n')
  }

  async function loadKeepNewPreview(conflict) {
    const response = await conflictApi.preview(getConflictId(conflict), 'KEEP_NEW')
    return response?.preview || {}
  }

  async function resolveKeepNew(conflict, preview = null) {
    const effectivePreview = preview || await loadKeepNewPreview(conflict)
    const result = await conflictApi.resolve(getConflictId(conflict), { action: 'KEEP_NEW', confirmed: true })
    return { ...effectivePreview, ...result }
  }

  async function resolveSkip(conflict) {
    await conflictApi.resolve(getConflictId(conflict), { action: 'SKIP' })
    removeConflict(getConflictId(conflict))
  }

  async function startRetry(conflict, payload = {}) {
    return conflictApi.retry(getConflictId(conflict), payload)
  }

  function promptMultiPasswords({ conflict, title, description, confirmText }) {
    return new Promise((resolve, reject) => {
      retryDialogResolverRef.current = { resolve, reject }
      setRetryDialog({ open: true, conflict, title, description, confirmText })
    })
  }

  function openFilenamePreviewDialog(preview, options = {}) {
    return new Promise((resolve, reject) => {
      filenameDialogResolverRef.current = { resolve, reject }
      setFilenameDialog({
        open: true,
        preview,
        confirmText: options.confirmText || '关闭',
        cancelText: options.cancelText || ''
      })
    })
  }

  async function previewArchiveFilenames(conflict, { filenameEncoding = '', password = '' } = {}) {
    const normalizedEncoding = String(filenameEncoding || '').trim()
    const response = await conflictApi.filenamePreview(getConflictId(conflict), {
      filename_encoding: normalizedEncoding === 'auto' ? '' : normalizedEncoding,
      password: String(password || '').trim(),
      limit: 80
    })
    return response?.preview || {}
  }

  function ensureFilenameState(conflict) {
    const id = getConflictId(conflict)
    return filenamePreviewState[id] || { encoding: 'auto', preview: null }
  }

  function setFilenameEncoding(conflict, value) {
    const id = getConflictId(conflict)
    setFilenamePreviewState(previous => ({ ...previous, [id]: { ...(previous[id] || { encoding: 'auto', preview: null }), encoding: value || 'auto', preview: null } }))
  }

  async function askRetryPassword(conflict, batchCount = 1) {
    const isBatch = batchCount > 1
    const isGarbledConflict = !isBatch && Boolean(getGarbledMeta(conflict))
    if (isBatch) {
      try {
        const passwordValue = await showSystemPrompt({
          title: `批量重试 ${batchCount} 个问题项`,
          message: `可选：指定一个密码用于全部 ${batchCount} 项重试。留空则各项按原逻辑走密码库、RJ 推导和默认密码。`,
          confirmText: `开始批量重试 (${batchCount} 项)`,
          inputType: 'text',
          placeholder: '直接输入明文密码；留空表示正常重试',
          closeOnClickModal: false
        })
        const trimmed = String(passwordValue || '').trim()
        return { cancelled: false, passwords: trimmed ? [trimmed] : [], filenameEncoding: '', ignoreGarbled: false }
      } catch (error) {
        if (error === 'cancel' || error === 'close') return { cancelled: true, passwords: [], filenameEncoding: '', ignoreGarbled: false }
        throw error
      }
    }

    try {
      const state = ensureFilenameState(conflict)
      const passwords = await promptMultiPasswords({
        conflict,
        title: `重试 ${conflict.rjcode || '当前问题项'}`,
        description: isGarbledConflict
          ? `可填多个密码（按顺序依次尝试）。当前编码：${filenameEncodingOptions.find(item => item.value === state.encoding)?.label || '自动识别'}，下一步会预览压缩包目录确认是否仍然乱码。`
          : '可填多个密码，按顺序依次尝试，任一命中即成功。当前问题项不是文件名乱码错误，无需指定 ZIP 文件名编码。',
        confirmText: isGarbledConflict ? '下一步：编码预览' : '开始重试'
      })
      const result = { cancelled: false, passwords: Array.isArray(passwords) ? passwords.filter(Boolean) : [], filenameEncoding: '', ignoreGarbled: false }
      if (!isGarbledConflict) return result
      result.filenameEncoding = state.encoding || 'auto'
      const preview = await previewArchiveFilenames(conflict, { filenameEncoding: result.filenameEncoding, password: result.passwords[0] || '' })
      preview.requested_encoding = result.filenameEncoding
      setFilenamePreviewState(previous => ({ ...previous, [getConflictId(conflict)]: { encoding: result.filenameEncoding, preview } }))
      await openFilenamePreviewDialog(preview, {
        confirmText: preview.garbled_sample ? '仍然重试并忽略乱码' : '按该编码重试',
        cancelText: '取消'
      })
      result.ignoreGarbled = Boolean(preview.garbled_sample)
      return result
    } catch (error) {
      if (error === 'cancel' || error === 'close') return { cancelled: true, passwords: [], filenameEncoding: '', ignoreGarbled: false }
      throw error
    }
  }

  function startRetryPoller(taskId, conflictId) {
    if (!taskId || retryPollersRef.current.has(taskId)) return
    let attempts = 0
    const maxAttempts = 120
    const poll = async () => {
      attempts += 1
      try {
        const task = await taskCenterApi.getItem({ engine_task_id: taskId })
        if (task) {
          const status = String(task.status || '').trim().toLowerCase()
          if (status === 'completed') {
            retryPollersRef.current.delete(taskId)
            markConflictRetrying(conflictId, false)
            await fetchConflicts()
            if (!conflictsRef.current.some(item => getConflictId(item) === conflictId)) {
              await showSystemAlert({ title: '重试成功，已移出问题作品', tone: 'success' })
            } else {
              await showSystemAlert({ title: '重试任务已完成，但问题项仍在列表，请手动刷新确认', tone: 'warning' })
            }
            return
          }
          if (status === 'failed') {
            retryPollersRef.current.delete(taskId)
            markConflictRetrying(conflictId, false)
            await fetchConflicts()
            await showSystemAlert({ title: task.error_message ? `重试失败：${task.error_message}` : '重试失败，请查看任务详情', tone: 'warning' })
            return
          }
        }
        if (attempts % 4 === 0) await fetchConflicts()
      } catch {
      }
      if (attempts < maxAttempts && retryPollersRef.current.has(taskId)) {
        retryPollersRef.current.set(taskId, window.setTimeout(poll, attempts < 10 ? 1500 : 5000))
      } else {
        retryPollersRef.current.delete(taskId)
        markConflictRetrying(conflictId, false)
        await fetchConflicts()
      }
    }
    retryPollersRef.current.set(taskId, window.setTimeout(poll, 1000))
  }

  async function handleRetry(conflict) {
    if (isBatchableActive(conflict, 'RETRY')) return handleBatchRetry()
    const id = getConflictId(conflict)
    markAction(id, 'RETRY', true)
    try {
      const retryInput = await askRetryPassword(conflict)
      if (retryInput.cancelled) return
      const passwords = Array.isArray(retryInput.passwords) ? retryInput.passwords.filter(Boolean) : []
      const payload = {}
      if (passwords.length) {
        payload.passwords = passwords
        payload.password = passwords[0]
      }
      if (retryInput.filenameEncoding) payload.filename_encoding = retryInput.filenameEncoding
      if (retryInput.ignoreGarbled) payload.ignore_garbled = true
      const result = await startRetry(conflict, payload)
      markConflictRetrying(id, true)
      await showSystemAlert({ title: result?.already_running ? '已更新现有重试任务，后台持续跟踪结果' : '已开始重试，后台轮询中', tone: 'success' })
      await fetchConflicts()
      startRetryPoller(result?.task_id, id)
    } catch (error) {
      console.error('重试问题作品失败:', error)
      await showSystemAlert({ title: '重试失败', message: resolveErrorMessage(error, '重试失败'), tone: 'danger' })
    } finally {
      markAction(id, 'RETRY', false)
    }
  }

  async function handleKeepNew(conflict) {
    if (isBatchableActive(conflict, 'KEEP_NEW')) return handleBatchKeepNew()
    const id = getConflictId(conflict)
    markAction(id, 'KEEP_NEW', true)
    try {
      const preview = await loadKeepNewPreview(conflict)
      await showSystemConfirm({
        title: '删除审查确认',
        message: buildKeepNewSummary(conflict, preview),
        tone: 'danger',
        confirmText: '确认删除并写入新内容'
      })
      const result = await resolveKeepNew(conflict, preview)
      await fetchConflicts()
      await showSystemAlert({ title: result?.message || '已提交保留新版后台任务', tone: 'success' })
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        console.error('保留新版失败:', error)
        await showSystemAlert({ title: '保留新版失败', message: resolveErrorMessage(error, '保留新版失败'), tone: 'danger' })
      }
    } finally {
      markAction(id, 'KEEP_NEW', false)
    }
  }

  async function handleSkip(conflict) {
    if (isBatchableActive(conflict, 'SKIP')) return handleBatchSkip()
    const id = getConflictId(conflict)
    markAction(id, 'SKIP', true)
    try {
      await showSystemConfirm({
        title: '跳过当前压缩包',
        message: `将直接删除待处理来源：${getConflictSourcePath(conflict)}`,
        tone: 'warning',
        confirmText: '确认跳过'
      })
      await resolveSkip(conflict)
      await showSystemAlert({ title: '已跳过当前包', tone: 'success' })
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        console.error('跳过失败:', error)
        await showSystemAlert({ title: '跳过失败', message: resolveErrorMessage(error, '跳过失败'), tone: 'danger' })
      }
    } finally {
      markAction(id, 'SKIP', false)
    }
  }

  async function handleFilenamePreview(conflict) {
    const id = getConflictId(conflict)
    markAction(id, 'PREVIEW_FILENAME', true)
    try {
      const state = ensureFilenameState(conflict)
      const preview = await previewArchiveFilenames(conflict, { filenameEncoding: state.encoding })
      preview.requested_encoding = state.encoding
      setFilenamePreviewState(previous => ({ ...previous, [id]: { encoding: state.encoding, preview } }))
      await showSystemAlert({ title: '文件名预览已刷新', tone: 'success' })
    } catch (error) {
      console.error('预览压缩包文件名失败:', error)
      await showSystemAlert({ title: '预览文件名失败', message: resolveErrorMessage(error, '预览文件名失败'), tone: 'danger' })
    } finally {
      markAction(id, 'PREVIEW_FILENAME', false)
    }
  }

  async function handleVolumeRenameConfirm({ renames, autoRetry }) {
    const conflict = volumeRenameDialog.conflict
    setVolumeRenameDialog({ open: false, conflict: null })
    if (!conflict || !renames?.length) return
    const id = getConflictId(conflict)
    markAction(id, 'RENAME_VOLUMES', true)
    try {
      const result = await conflictApi.renameVolumes(id, { renames, auto_retry: Boolean(autoRetry) })
      await showSystemAlert({ title: result?.message || `已重命名 ${result?.renamed?.length || renames.length} 个分卷`, tone: 'success' })
      if (autoRetry && result?.task_id) {
        markConflictRetrying(id, true)
        startRetryPoller(result.task_id, id)
      }
      await fetchConflicts()
    } catch (error) {
      console.error('手动重命名分卷失败:', error)
      await showSystemAlert({ title: '重命名分卷失败', message: resolveErrorMessage(error, '重命名分卷失败'), tone: 'danger' })
    } finally {
      markAction(id, 'RENAME_VOLUMES', false)
    }
  }

  async function handleBatchKeepNew() {
    const targets = getSelectedConflictsForAction('KEEP_NEW')
    if (!targets.length) return showSystemAlert({ title: '请先勾选可执行保留新版的问题项', tone: 'warning' })
    setBatchState('保留新版', true)
    try {
      const previewEntries = []
      const failures = []
      for (const conflict of targets) {
        try {
          previewEntries.push({ conflict, preview: await loadKeepNewPreview(conflict) })
        } catch (error) {
          failures.push({ conflict, message: resolveErrorMessage(error, '生成删除审查失败') })
        }
      }
      if (!previewEntries.length) {
        await presentBatchResult('批量保留新版', [], failures)
        return
      }
      const totalFiles = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.file_count || 0), 0)
      const totalFolders = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.folder_count || 0), 0)
      const totalSize = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.size || 0), 0)
      await showSystemConfirm({
        title: '批量删除审查确认',
        message: [`将批量保留新版 ${previewEntries.length} 项`, `待删除文件夹数：${totalFolders}`, `待删除文件数：${totalFiles}`, `待删除总大小：${formatBytes(totalSize)}`, '', buildPathPreview(previewEntries.map(entry => entry.preview.path || entry.conflict.existing_path || '-'))].join('\n'),
        tone: 'danger',
        confirmText: '确认批量执行'
      })
      const successes = []
      for (const entry of previewEntries) {
        try {
          await resolveKeepNew(entry.conflict, entry.preview)
          successes.push(entry.conflict)
        } catch (error) {
          failures.push({ conflict: entry.conflict, message: resolveErrorMessage(error, '保留新版失败') })
        }
      }
      await fetchConflicts()
      await presentBatchResult('批量保留新版', successes, failures)
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') await showSystemAlert({ title: '批量保留新版失败', message: resolveErrorMessage(error, '批量保留新版失败'), tone: 'danger' })
    } finally {
      setBatchState('', false)
    }
  }

  async function handleBatchSkip() {
    const targets = getSelectedConflictsForAction('SKIP')
    if (!targets.length) return showSystemAlert({ title: '请先勾选可执行跳过的问题项', tone: 'warning' })
    setBatchState('跳过', true)
    try {
      await showSystemConfirm({
        title: '批量跳过确认',
        message: [`将批量跳过 ${targets.length} 项，并删除它们的待处理来源。`, '', buildPathPreview(targets.map(getConflictSourcePath))].join('\n'),
        tone: 'warning',
        confirmText: '确认批量跳过'
      })
      const successes = []
      const failures = []
      for (const conflict of targets) {
        try {
          await resolveSkip(conflict)
          successes.push(conflict)
        } catch (error) {
          failures.push({ conflict, message: resolveErrorMessage(error, '跳过失败') })
        }
      }
      await presentBatchResult('批量跳过', successes, failures)
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') await showSystemAlert({ title: '批量跳过失败', message: resolveErrorMessage(error, '批量跳过失败'), tone: 'danger' })
    } finally {
      setBatchState('', false)
    }
  }

  function handleBatchRetry() {
    const targets = getSelectedConflictsForAction('RETRY')
    if (!targets.length) {
      showSystemAlert({ title: '请先勾选可执行重试的问题项', tone: 'warning' })
      return
    }
    setBatchRetryDialog({ open: true, targets })
  }

  async function handleBatchRetryConfirm(entries) {
    const targets = batchRetryDialog.targets
    setBatchRetryDialog({ open: false, targets: [] })
    if (!targets.length) return
    setBatchState('重试', true)
    const inputMap = Object.fromEntries(entries.map(entry => [entry.conflictId, entry]))
    const successes = []
    const failures = []
    try {
      for (const conflict of targets) {
        try {
          const input = inputMap[getConflictId(conflict)] || {}
          const password = String(input.password || '').trim()
          const encoding = String(input.filenameEncoding || '').trim()
          const payload = {}
          if (password) {
            payload.passwords = [password]
            payload.password = password
          }
          if (encoding && encoding !== 'auto') payload.filename_encoding = encoding
          const result = await startRetry(conflict, payload)
          markConflictRetrying(getConflictId(conflict), true)
          successes.push(conflict)
          startRetryPoller(result?.task_id, getConflictId(conflict))
        } catch (error) {
          failures.push({ conflict, message: resolveErrorMessage(error, '提交重试失败') })
        }
      }
      await fetchConflicts()
      await presentBatchResult('批量重试', successes, failures, `${successes.length} 项重试已提交，后台轮询结果中，可到任务列表跟踪进度。`)
    } finally {
      setBatchState('', false)
    }
  }

  function cancelMergePreviewPolling() {
    if (mergePreviewPollingAbortRef.current) {
      mergePreviewPollingAbortRef.current()
      mergePreviewPollingAbortRef.current = null
    }
  }

  async function getMergePreview(conflict, forceRefresh = false, onProgress = null) {
    const id = getConflictId(conflict)
    let preview = mergePreviewCacheRef.current[id]
    if (preview && !forceRefresh) return preview
    const initial = await conflictApi.preview(id, 'MERGE')
    if (!initial?.async || !initial?.job_id) {
      preview = initial
      mergePreviewCacheRef.current[id] = preview
      return preview
    }
    onProgress?.({
      status: initial.status || 'running',
      stage: initial.stage || 'init',
      stage_label: initial.stage_label || '初始化',
      message: initial.message || '启动合并预览任务',
      percent: Math.max(0, Math.min(100, Number(initial.percent) || 0))
    })
    cancelMergePreviewPolling()
    let cancelled = false
    mergePreviewPollingAbortRef.current = () => { cancelled = true }
    const startedAt = Date.now()
    while (true) {
      if (cancelled) {
        const error = new Error('合并预览已取消')
        error.code = 'MERGE_PREVIEW_CANCELLED'
        throw error
      }
      if (Date.now() - startedAt > 15 * 60 * 1000) throw new Error('合并预览超时（已等待 15 分钟）')
      await delay(Date.now() - startedAt < 6000 ? 600 : 1200)
      if (cancelled) continue
      let snapshot
      try {
        snapshot = await conflictApi.mergePreviewJob(id, initial.job_id)
      } catch (error) {
        if (error?.response?.status === 404) throw new Error('合并预览任务已过期，请重新发起合并')
        continue
      }
      onProgress?.({
        status: snapshot.status || 'running',
        stage: snapshot.stage || '',
        stage_label: snapshot.stage_label || '',
        message: snapshot.message || '',
        percent: Math.max(0, Math.min(100, Number(snapshot.percent) || 0))
      })
      if (snapshot.status === 'completed' && snapshot.result) {
        mergePreviewPollingAbortRef.current = null
        mergePreviewCacheRef.current[id] = snapshot.result
        return snapshot.result
      }
      if (snapshot.status === 'failed') {
        mergePreviewPollingAbortRef.current = null
        const error = new Error(snapshot.error || snapshot.message || '合并预览失败')
        error.code = 'MERGE_PREVIEW_FAILED'
        throw error
      }
    }
  }

  async function openMergeWorkbench(conflict, forceRefresh = false) {
    const id = getConflictId(conflict)
    markAction(id, 'MERGE', true)
    setMergeState({ open: true, conflictId: id, loading: true, submitting: false, preview: null, decisions: {}, progress: { status: 'running', stage: 'init', stage_label: '初始化', message: '准备生成合并预览', percent: 1 } })
    try {
      const preview = await getMergePreview(conflict, forceRefresh, snapshot => {
        setMergeState(previous => ({ ...previous, progress: snapshot }))
      })
      setMergeState(previous => ({
        ...previous,
        loading: false,
        preview,
        decisions: { ...(mergeDecisionCacheRef.current[id] || preview.default_decisions || {}) },
        progress: { status: 'completed', stage: 'done', stage_label: '完成', message: `已生成 ${preview.items?.length || 0} 项差异`, percent: 100 }
      }))
    } catch (error) {
      if (error?.code !== 'MERGE_PREVIEW_CANCELLED') {
        console.error('生成合并预览失败:', error)
        await showSystemAlert({ title: '生成合并预览失败', message: resolveErrorMessage(error, '生成合并预览失败'), tone: 'danger' })
      }
      setMergeState(previous => ({ ...previous, open: false, loading: false }))
    } finally {
      markAction(id, 'MERGE', false)
    }
  }

  async function resolveMerge(conflict, preview = null, decisions = null) {
    const id = getConflictId(conflict)
    const effectivePreview = preview || await getMergePreview(conflict)
    const effectiveDecisions = decisions || mergeDecisionCacheRef.current[id] || effectivePreview.default_decisions || {}
    await conflictApi.resolve(id, {
      action: 'MERGE',
      merge_session_id: effectivePreview.session_id,
      merge_decisions: effectiveDecisions
    })
    removeConflict(id)
    return effectivePreview
  }

  async function submitMerge() {
    if (!mergeConflict || !mergeState.preview) return
    setMergeState(previous => ({ ...previous, submitting: true }))
    try {
      await resolveMerge(mergeConflict, mergeState.preview, mergeState.decisions)
      await showSystemAlert({ title: '合并结果已提交', tone: 'success' })
      setMergeState({ open: false, conflictId: '', loading: false, submitting: false, preview: null, decisions: {}, progress: mergeIdleProgress })
    } catch (error) {
      console.error('提交合并失败:', error)
      await showSystemAlert({ title: '提交合并失败', message: resolveErrorMessage(error, '提交合并失败'), tone: 'danger' })
      setMergeState(previous => ({ ...previous, submitting: false }))
    }
  }

  return (
    <div className="km-page conflicts-page">
      <PageHeader
        eyebrow="重复作品、解压失败、处理失败的集中处理站"
        title="问题作品"
        description="这里保留 KEEP_NEW、SKIP、MERGE、RETRY、乱码预览和分卷修复的完整工作台。"
        actions={(
          <>
            {batchRunning ? <span className="conflicts-running-pill"><Loader2 size={14} className="km-spin" />{batchActionLabel || '批量处理中'}</span> : null}
            <Button variant="primary" disabled={loading || batchRunning} onClick={fetchConflicts}>
              <RefreshCw size={16} className={loading ? 'km-spin' : ''} />
              刷新
            </Button>
          </>
        )}
      />

      <section className="conflicts-info-strip">
        <div><Hourglass size={16} /><span>待处理</span><b>{pendingConflicts.length}</b><em>/ 共 {conflicts.length}</em></div>
        <div><RotateCcw size={16} /><span>重试中</span><b>{retryingConflicts.length}</b></div>
        <div><Loader2 size={16} /><span>处理中</span><b>{processingConflicts.length}</b></div>
      </section>

      {errorMessage ? (
        <div className="conflicts-error-alert">
          <AlertCircle size={20} />
          <div><strong>获取问题作品失败</strong><p>{errorMessage}</p></div>
        </div>
      ) : null}

      {!loading || conflicts.length ? (
        <main className="conflicts-main">
          {!conflicts.length ? (
            <div className="conflicts-empty">
              <CheckCircle2 size={54} />
              <strong>当前没有待处理的问题作品</strong>
              <span>所有作品都在正常导入或库中已处于良好状态</span>
            </div>
          ) : (
            <>
              <ConflictsListPane
                conflicts={conflicts}
                filteredConflicts={filteredConflicts}
                filterOptions={filterOptions}
                conflictFilter={conflictFilter}
                selectedIds={selectedIds}
                activeId={activeConflictId}
                batchRunning={batchRunning}
                localRetryingIds={localRetryingIds}
                onFilterChange={value => {
                  setConflictFilter(value)
                  setSelectedIds(new Set())
                }}
                onCardClick={handleConflictCardClick}
                onToggleSelectAll={toggleSelectAll}
                onClearSelection={() => {
                  setSelectedIds(new Set())
                  setSelectionAnchorId('')
                }}
                isAllSelected={filteredConflicts.length > 0 && filteredConflicts.every(conflict => selectedIds.has(getConflictId(conflict)) || isConflictRetrying(conflict, localRetryingIds))}
                selectedActionCount={selectedActionCount}
                onBatchRetry={handleBatchRetry}
                onBatchSkip={handleBatchSkip}
              />
              <ConflictDetailPane
                conflict={activeConflict}
                selected={activeConflict ? selectedIds.has(getConflictId(activeConflict)) : false}
                statsBackfilling={statsBackfilling}
                batchRunning={batchRunning}
                localRetryingIds={localRetryingIds}
                actionState={actionState}
                filenameState={activeConflict ? ensureFilenameState(activeConflict) : { encoding: 'auto', preview: null }}
                onFilenameEncodingChange={setFilenameEncoding}
                onFilenamePreview={handleFilenamePreview}
                onKeepNew={handleKeepNew}
                onRetry={handleRetry}
                onSkip={handleSkip}
                onMerge={openMergeWorkbench}
                onRenameVolumes={conflict => {
                  if (!conflict?.new_metadata?.disguised_volume_set?.suspect_files?.length) {
                    showSystemAlert({ title: '该问题项缺少分卷探测信息，无法手动重命名', tone: 'warning' })
                    return
                  }
                  setVolumeRenameDialog({ open: true, conflict })
                }}
                labelForAction={labelForAction}
              />
            </>
          )}
        </main>
      ) : null}

      <RetryPasswordsDialog
        open={retryDialog.open}
        title={retryDialog.title}
        description={retryDialog.description}
        confirmText={retryDialog.confirmText}
        onConfirm={({ passwords }) => {
          const resolver = retryDialogResolverRef.current
          retryDialogResolverRef.current = null
          setRetryDialog({ open: false, conflict: null, title: '', description: '', confirmText: '开始重试' })
          resolver?.resolve(passwords)
        }}
        onClose={() => {
          const resolver = retryDialogResolverRef.current
          retryDialogResolverRef.current = null
          setRetryDialog({ open: false, conflict: null, title: '', description: '', confirmText: '开始重试' })
          resolver?.reject('cancel')
        }}
      />
      <BatchRetryPasswordDialog
        open={batchRetryDialog.open}
        targets={batchRetryDialog.targets}
        onConfirm={handleBatchRetryConfirm}
        onClose={() => setBatchRetryDialog({ open: false, targets: [] })}
      />
      <VolumeRenameDialog
        open={volumeRenameDialog.open}
        conflict={volumeRenameDialog.conflict}
        onConfirm={handleVolumeRenameConfirm}
        onClose={() => setVolumeRenameDialog({ open: false, conflict: null })}
      />
      <FilenamePreviewDialog
        open={filenameDialog.open}
        preview={filenameDialog.preview}
        confirmText={filenameDialog.confirmText}
        cancelText={filenameDialog.cancelText}
        onConfirm={() => {
          const resolver = filenameDialogResolverRef.current
          filenameDialogResolverRef.current = null
          setFilenameDialog({ open: false, preview: null, confirmText: '关闭', cancelText: '' })
          resolver?.resolve(true)
        }}
        onClose={() => {
          const resolver = filenameDialogResolverRef.current
          filenameDialogResolverRef.current = null
          setFilenameDialog({ open: false, preview: null, confirmText: '关闭', cancelText: '' })
          resolver?.reject('cancel')
        }}
      />
      <ConflictMergeWorkbench
        open={mergeState.open}
        conflict={mergeConflict}
        preview={mergeState.preview}
        decisions={mergeState.decisions}
        loading={mergeState.loading}
        progress={mergeState.progress}
        submitting={mergeState.submitting}
        onClose={() => {
          if (mergeState.submitting) return
          cancelMergePreviewPolling()
          setMergeState({ open: false, conflictId: '', loading: false, submitting: false, preview: null, decisions: {}, progress: mergeIdleProgress })
        }}
        onRefresh={() => mergeConflict && openMergeWorkbench(mergeConflict, true)}
        onDecisionChange={value => {
          if (mergeState.conflictId) mergeDecisionCacheRef.current[mergeState.conflictId] = { ...value }
          setMergeState(previous => ({ ...previous, decisions: value }))
        }}
        onSubmit={submitMerge}
      />
    </div>
  )
}
