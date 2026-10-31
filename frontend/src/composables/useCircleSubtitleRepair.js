import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, provide, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { circleCompletionApi } from '../api'
import { useRealtimeEvents } from './useRealtimeEvents'

export function useCircleSubtitleRepair(circleId, items) {
  const router = useRouter()
  const busy = ref(false)
  const groups = ref([])
  const selected = ref([])
  const visible = ref(false)
  const viewOnly = ref(false)
  const states = ref({})
  const requestCircle = ref('')
  const realtimeEvents = useRealtimeEvents()
  let revision = 0
  let pendingRefresh = null
  let active = true
  let realtimeStarted = false
  let unsubscribeTasks = null
  let unsubscribeSubtitle = null
  const codeOf = item => String(item?.canonical_rjcode || '').toUpperCase()
  const keyOf = target => JSON.stringify([target.library_id, target.folder_path])
  const tasks = item => states.value[codeOf(item)] || []
  const statusLabel = task => task?.skipped_reason ? '已跳过' : task?.awaiting_manual_match ? '待配对' : ({ pending: '已加入', processing: '爬取中', waiting_manual: '待配对', completed: '已结束', failed: '失败', paused: '已暂停', cancelled: '已取消', waiting_retry: '等待重试' }[task?.status] || task?.status || '')
  const payload = codes => ({ circle_id: requestCircle.value || circleId.value, canonical_rjcodes: codes })
  async function refresh() {
    if (!active) return
    const circle = circleId.value
    const codes = [...new Set(items.value.map(codeOf).filter(Boolean))]
    const current = ++revision
    if (!circle || !codes.length) { states.value = {}; return }
    try {
      const response = await circleCompletionApi.subtitleRepairTasks({ circle_id: circle, canonical_rjcodes: codes.slice(0, 100) })
      if (current === revision && circle === circleId.value) states.value = response.items || {}
    } catch (error) { console.debug('[社团字幕] 任务状态读取失败', error) }
  }
  function scheduleRefresh() {
    if (pendingRefresh) return
    pendingRefresh = setTimeout(() => { pendingRefresh = null; void refresh() }, 700)
  }
  function taskPayloads(event) {
    if (event?.type === 'task.center.changed.batch') return event.payload?.events || []
    if (event?.type === 'task.center.changed' && event.payload) return [event.payload]
    return []
  }
  function handleTaskEvent(event) {
    if (!active) return
    const visibleCodes = new Set()
    for (const item of items.value) {
      for (const code of [
        item?.canonical_rjcode,
        item?.display_rjcode,
        item?.asmr_available_rjcode,
        ...(item?.linked_rjcodes || []),
        ...(item?.subtitle_translation_rjcodes || []),
      ]) {
        const normalized = String(code || '').toUpperCase()
        if (normalized) visibleCodes.add(normalized)
      }
    }
    const relevant = taskPayloads(event).some(payload => {
      if (payload?.type !== 'task_center_changed' || payload.domain !== 'rj_subtitle') return false
      const code = String(payload.circle_canonical_rjcode || payload.rjcode || '').toUpperCase()
      if (payload.circle_id && payload.circle_id !== circleId.value) return false
      if (code && !visibleCodes.has(code)) return false
      const reason = String(payload.reason || '')
      const status = String(payload.status || '')
      if (reason === 'submitted' && status === 'pending') return true
      if (reason === 'started' && status === 'processing') return true
      return ['completed', 'failed', 'cancelled', 'waiting_manual', 'waiting_retry'].includes(status)
    })
    if (relevant) scheduleRefresh()
  }
  function handleSubtitleSync(event) {
    if (!active) return
    const payload = event?.payload || {}
    const circles = payload.circle_ids || (payload.circle_id ? [payload.circle_id] : [])
    if (circles.includes(circleId.value)) scheduleRefresh()
  }
  function startRealtime() {
    active = true
    if (realtimeStarted) return
    realtimeStarted = true
    realtimeEvents.start()
    unsubscribeTasks = realtimeEvents.subscribe('task.center.changed', handleTaskEvent)
    unsubscribeTasksBatch = realtimeEvents.subscribe('task.center.changed.batch', handleTaskEvent)
    unsubscribeSubtitle = realtimeEvents.subscribe('circle.subtitle.synced', handleSubtitleSync)
    void refresh()
  }
  let unsubscribeTasksBatch = null
  function stopRealtime() {
    active = false
    revision++
    clearTimeout(pendingRefresh)
    pendingRefresh = null
    if (!realtimeStarted) return
    realtimeStarted = false
    unsubscribeTasks?.()
    unsubscribeTasksBatch?.()
    unsubscribeSubtitle?.()
    unsubscribeTasks = unsubscribeTasksBatch = unsubscribeSubtitle = null
    realtimeEvents.stop()
  }
  function openTask(task) {
    visible.value = false
    return router.push({ name: 'Library', query: { subtitleDialog: '1', subtitleTaskId: task.task_id, subtitleLibraryId: task.library_id, subtitleFolderPath: task.folder_path, subtitleRjcode: task.rjcode, subtitleStage: task.awaiting_manual_match ? 'pairing' : 'overview' } })
  }
  async function submit(codes, selections) {
    const response = await circleCompletionApi.subtitleRepairStart({ ...payload(codes), ...(selections ? { selections } : {}) })
    const count = response.created_count || 0
    const reused = response.reused_count || 0
    const skipped = response.skipped_count || 0
    ElMessage({ type: skipped ? 'warning' : 'success', message: `已创建 ${count}，复用 ${reused}，跳过 ${skipped} 个字幕任务` })
    const failed = (response.items || []).filter(item => item.state === 'skipped')
    if (failed.length) ElMessage.warning(failed.slice(0, 3).map(item => `${item.canonical_rjcode}：${item.reason}`).join('；'))
    const choose = (response.items || []).filter(item => item.state === 'selection_required')
    if (choose.length && requestCircle.value === circleId.value) { groups.value = choose; selected.value = []; visible.value = true; viewOnly.value = false }
    await refresh()
    return response
  }
  async function create(input) {
    if (busy.value) return
    busy.value = true
    requestCircle.value = circleId.value
    viewOnly.value = false
    try {
      const codes = Array.isArray(input) ? [...new Set(input)] : [codeOf(input)]
      if (!codes.length) return
      if (codes.length > 100) { ElMessage.warning('每次最多创建 100 个作品的字幕任务'); return }
      const response = await circleCompletionApi.subtitleRepairTargets(payload(codes))
      if (requestCircle.value !== circleId.value) return
      groups.value = response.items || []
      if (groups.value.some(group => group.targets.length > 1)) {
        selected.value = []
        visible.value = true
      } else { await submit(codes) }
    } catch (error) { ElMessage.error(error.response?.data?.detail || '创建字幕任务失败') }
    finally { busy.value = false }
  }
  async function confirm() {
    if (busy.value || !selected.value.length) return
    busy.value = true
    try {
      const selections = {}
      for (const group of groups.value) {
        selections[group.canonical_rjcode] = group.targets.filter(target => selected.value.includes(`${group.canonical_rjcode}:${keyOf(target)}`))
      }
      visible.value = false
      await submit(Object.keys(selections), selections)
    } catch (error) { ElMessage.error(error.response?.data?.detail || '创建字幕任务失败'); visible.value = true }
    finally { busy.value = false }
  }
  function view(item) {
    const list = tasks(item)
    if (list.length === 1) return openTask(list[0])
    requestCircle.value = circleId.value
    groups.value = [{ canonical_rjcode: codeOf(item), targets: list.map(task => ({ ...task, task })) }]
    viewOnly.value = true
    visible.value = true
  }
  provide('circleSubtitleRepair', { tasks, create, view, busy: () => busy.value })
  watch(() => [circleId.value, items.value.map(codeOf).join('|')], () => { states.value = {}; void refresh() })
  watch(circleId, () => { visible.value = false })
  onMounted(startRealtime)
  onActivated(startRealtime)
  onDeactivated(stopRealtime)
  onBeforeUnmount(stopRealtime)
  return { busy, groups, selected, visible, viewOnly, statusLabel, keyOf, create, confirm, openTask, view, tasks, scheduleRefresh, refresh, canConfirm: computed(() => selected.value.length > 0) }
}
