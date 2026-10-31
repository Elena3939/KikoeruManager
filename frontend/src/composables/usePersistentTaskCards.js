import { reactive, watch, onBeforeUnmount, onActivated, onDeactivated } from 'vue'
import { asmrSyncApi, httpDownloadApi, baiduNetdiskApi, localUploadApi, rjSubtitleApi } from '../api'
import { getMatchingDownloadSummary, formatDownloadSummary, getDownloadBatchPercent } from '../utils/downloadProgress.js'

const STORAGE = 'kikoerumanager.ui.persistentTaskCards'
function read() {
  try { return JSON.parse(localStorage.getItem(STORAGE) || '{}') } catch (_) { return {} }
}
export const persistentTaskCards = reactive(read())
export const mountedTaskCards = reactive(new Set())
export const openTaskWorkbenches = reactive(new Set())
export const verifiedTaskCards = reactive(new Set())
const workbenchOpeners = new Map()
export const TASK_CARD_RETENTION_MS = 60_000
const autoDismissStatuses = new Set(['completed', 'success', 'succeeded', 'cancelled', 'canceled', 'superseded'])
const failedStatuses = new Set(['failed', 'partial_failed'])
export function taskStatus(task) { return String(task?.display_status || task?.status || '').trim().toLowerCase() }
function isTaskCompleted(task) {
  const status = taskStatus(task)
  return status === 'completed' || status === 'success' || status === 'succeeded'
}
function sameTasks(left, right) { return [...left].map(String).sort().join('|') === [...right].map(String).sort().join('|') }
export function dismissPersistentTaskCard(id) {
  const card = persistentTaskCards[id]
  if (!card) return
  card.dismissed = true
  verifiedTaskCards.delete(id)
  saveTaskCards()
}
// 关闭工作台中的单条任务，仅移除追踪；后端任务及文件保持可查询。
export function dismissWorkbenchTask(task, ids, tasks, cardId, invalidate = () => {}) {
  invalidate()
  const removed = new Set((task.source_task_ids?.length ? task.source_task_ids : [task.active_task_id || task.id]).map(String))
  ids.value = ids.value.filter(id => !removed.has(String(id)))
  tasks.value = tasks.value.filter(row => !removed.has(String(row.id)))
  if (!ids.value.length) dismissPersistentTaskCard(cardId)
}
export function expirePersistentTaskCards() {
  for (const card of Object.values(persistentTaskCards)) {
    if (!card.dismissed && card.expiresAt && Date.now() >= card.expiresAt) dismissPersistentTaskCard(card.id)
  }
}
function updateTaskCardState(card, tasks, complete = true) {
  const finished = complete && tasks.every(task => autoDismissStatuses.has(taskStatus(task)))
  const failed = tasks.some(task => failedStatuses.has(taskStatus(task)))
  if (finished) card.expiresAt ||= Date.now() + TASK_CARD_RETENTION_MS
  else {
    // 已结束任务被重试后重新展示；普通轮询不能复活手动关闭的任务。
    if (card.expiresAt || (card.failed && !failed)) card.dismissed = false
    delete card.expiresAt
  }
  card.failed = failed
  card.props.completed = complete && tasks.every(isTaskCompleted)
  if (card.props.completed) card.props.percentage = 100
  const active = tasks.filter(task => !autoDismissStatuses.has(taskStatus(task)) && !failedStatuses.has(taskStatus(task)))
  const stateLabel = card.props.completed ? '已完成'
    : active.length ? (active.every(task => taskStatus(task) === 'paused') ? '已暂停' : '正在后台运行')
      : failed ? '需要处理' : finished ? '已取消' : '等待处理'
  // 恢复快照和页面实时数据使用相同的业务状态，不能沿用旧的“运行中”标题。
  if (card.props.title) card.props.title = card.props.title.replace(/(?:正在后台运行|已完成|已取消|已暂停|需要处理|等待处理)$/, '') + stateLabel
  if (failed) card.props.tone = 'rose'
}
export function taskCardBelongsToPage(card, path) { return card.route === path }
export async function openPersistentTaskCard(id) {
  const card = persistentTaskCards[id]
  if (!card) return
  const open = workbenchOpeners.get(`${card.route}:${card.props.taskSource}`)
  if (open) await open(id)
}

// 从全局小窗回到页面时恢复同一批任务，而不是仅打开页面。
export function usePersistentTaskWorkbench(route, source, ids, visible, background, refresh, options = {}) {
  const routePath = route.path
  const owner = `${routePath}:${source}`
  const open = async id => {
    const card = persistentTaskCards[id]
    if (!card || route.path !== routePath) return
    ids.value = [...card.props.taskIds]
    if (options.batchTaskIds) options.batchTaskIds.value = [...(card.props.batchTaskIds || card.props.taskIds.slice(0, 1))]
    if (options.batchStartedAt) options.batchStartedAt.value = card.props.batchStartedAt || ''
    await refresh({ silent: false })
    if (options.tasks && !options.tasks.value?.length) {
      delete persistentTaskCards[id]
      verifiedTaskCards.delete(id)
      saveTaskCards()
      return
    }
    background.value = false
    visible.value = true
    sync()
  }
  workbenchOpeners.set(owner, open)
  let active = true
  const sync = () => {
    if (active && visible.value) openTaskWorkbenches.add(owner)
    else openTaskWorkbenches.delete(owner)
  }
  watch(visible, sync, { immediate: true })
  if (options.tasks) watch(() => [ids.value, options.tasks.value, options.cardProps?.value], () => {
    const tasks = options.tasks.value || []
    const kind = source === 'upload' ? 'upload' : source === 'subtitle' ? 'subtitle' : source === 'asmr' && routePath === '/asmr-sync' ? 'asmr' : 'download'
    const id = options.id || `${routePath}:${source}:${kind}`
    // 页面初始化时任务 ID 尚未恢复，不能提前删除待校验的快照。
    if (!ids.value.length) return
    if (!tasks.length) return
    rememberTaskCard(id, { kind, title: options.title || (kind === 'upload' ? '上传任务' : kind === 'subtitle' ? '字幕任务' : '下载任务'), percentage: tasks.reduce((n, task) => n + (Number(task.progress) || 0), 0) / tasks.length, ...options.cardProps?.value, taskSource: source, taskIds: ids.value.map(String), positionKey: id }, routePath)
    updateTaskCardState(persistentTaskCards[id], tasks)
    expirePersistentTaskCards()
    saveTaskCards()
  }, { deep: true, immediate: true })
  onActivated(() => { active = true; sync() })
  onDeactivated(() => { active = false; openTaskWorkbenches.delete(owner) })
  onBeforeUnmount(() => { openTaskWorkbenches.delete(owner); if (workbenchOpeners.get(owner) === open) workbenchOpeners.delete(owner) })
}
export function saveTaskCards() {
  try { localStorage.setItem(STORAGE, JSON.stringify(persistentTaskCards)) } catch (_) {}
}
export function rememberTaskCard(id, props, route) {
  if (!props.taskIds?.length) return
  // 只保存数据字段，图标组件和运行时回调不进入持久化 JSON。
  const { title, subtitle, detailText, badgeText, metaText, timingText, sampledAt, batchTaskIds, batchStartedAt, kind, tone, percentage, completed, positionKey, taskSource, taskIds, metrics } = props
  const previous = persistentTaskCards[id]
  const sameBatch = previous && sameTasks(previous.props.taskIds, taskIds)
  if (sameBatch && sampledAt && Date.parse(sampledAt) < Date.parse(previous.props.sampledAt)) return
  persistentTaskCards[id] = { ...(sameBatch ? previous : {}), id, route, props: { title, subtitle, detailText, badgeText, metaText, timingText, sampledAt, batchTaskIds, batchStartedAt, kind, tone, percentage, completed, positionKey, taskSource, taskIds: taskIds.map(String), metrics: (metrics || []).map(({ key, label, value, tone }) => ({ key, label, value, tone })), actions: [{ key: 'resume', label: '打开工作台' }, { key: 'close', label: '关闭' }] } }
  if (!persistentTaskCards[id].dismissed) verifiedTaskCards.add(id)
  saveTaskCards()
}
export async function refreshPersistentTaskCards() {
  expirePersistentTaskCards()
  const groups = new Map()
  for (const card of Object.values(persistentTaskCards)) {
    if (mountedTaskCards.has(card.id)) continue
    const source = card.props.taskSource
    // 下载统计按批次返回，多个小窗不能共用合并后的一份总计。
    const groupKey = ['http', 'baidu'].includes(source)
      ? JSON.stringify([source, [...card.props.taskIds].sort(), [...(card.props.batchTaskIds || card.props.taskIds.slice(0, 1))].sort(), card.props.batchStartedAt || ''])
      : source
    if (!groups.has(groupKey)) groups.set(groupKey, [])
    groups.get(groupKey).push(card)
  }
  await Promise.allSettled([...groups.values()].map(async cards => {
    const source = cards[0].props.taskSource
    const ids = [...new Set(cards.flatMap(card => card.props.taskIds))]
    const api = { asmr: asmrSyncApi, http: httpDownloadApi, baidu: baiduNetdiskApi, upload: localUploadApi, subtitle: rjSubtitleApi }[source]
    if (!api) return
    const batchOptions = ['http', 'baidu'].includes(source) ? {
      batch_task_ids: (cards[0].props.batchTaskIds || cards[0].props.taskIds.slice(0, 1)).join(','),
      batch_started_at: cards[0].props.batchStartedAt || '',
    } : {}
    const result = source === 'asmr' ? await api.status(ids, { compact: true }) : await api.status({ task_ids: ids.join(','), include_hidden: true, compact: true, ...batchOptions })
    if (!Array.isArray(result.tasks)) return
    for (const card of cards) {
      // 页面或另一轮刷新已更新卡片时，丢弃迟到响应。
      if (persistentTaskCards[card.id] !== card) continue
      const summary = getMatchingDownloadSummary(result.download_summary, result.tasks)
      if (summary && Date.parse(summary.sampled_at) < Date.parse(card.props.sampledAt)) continue
      if (summary && result.batch_started_at) {
        card.props.taskIds = [...summary.task_ids]
        card.props.batchStartedAt = result.batch_started_at
      }
      const tasks = result.tasks.filter(task => card.props.taskIds.includes(String(task.id)))
      const completeSnapshot = ['asmr', 'upload', 'subtitle'].includes(source) || Number(result.total_tasks) <= result.tasks.length
      if (!tasks.length) {
        if (completeSnapshot) { delete persistentTaskCards[card.id]; verifiedTaskCards.delete(card.id) }
        continue
      }
      updateTaskCardState(card, tasks, completeSnapshot || tasks.length === card.props.taskIds.length)
      expirePersistentTaskCards()
      if (!card.dismissed) verifiedTaskCards.add(card.id)
      const active = tasks.find(task => failedStatuses.has(taskStatus(task))) || tasks.find(task => !autoDismissStatuses.has(taskStatus(task))) || tasks[0]
      card.props.percentage = card.props.completed
        ? 100
        : summary?.progress_percent ?? (['http', 'baidu'].includes(source) ? getDownloadBatchPercent(tasks)
          : tasks.reduce((sum, task) => sum + Math.max(0, Math.min(100, Number(task.progress) || 0)), 0) / tasks.length)
      if (summary) {
        Object.assign(card.props, formatDownloadSummary(summary), { sampledAt: summary.sampled_at })
      }
      card.props.subtitle = active.work_title || active.folder_name || active.rjcode || card.props.subtitle
      card.props.detailText = active.failure_reason || active.error_message || active.current_step || active.status_label || ''
      card.props.metrics = ['processing', 'pending', 'paused', 'completed', 'failed', 'partial_failed', 'cancelled'].map(key => ({ key, label: { processing: '进行中', pending: '等待', paused: '暂停', completed: '完成', failed: '失败', partial_failed: '部分失败', cancelled: '已取消' }[key], tone: failedStatuses.has(key) ? 'danger' : key, value: tasks.filter(task => taskStatus(task) === key || (key === 'cancelled' && taskStatus(task) === 'canceled')).length }))
    }
    saveTaskCards()
  }))
}
