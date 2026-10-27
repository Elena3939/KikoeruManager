import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive, ref, nextTick } from 'vue'

vi.mock('../api', () => ({ asmrSyncApi: { status: vi.fn() }, httpDownloadApi: { status: vi.fn() }, baiduNetdiskApi: { status: vi.fn() }, localUploadApi: { status: vi.fn() }, rjSubtitleApi: { status: vi.fn() } }))

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => { vi.useRealTimers() })
describe('任务小窗持久恢复', () => {
  it.each([
    ['http', 'httpDownloadApi'],
    ['baidu', 'baiduNetdiskApi'],
    ['asmr', 'asmrSyncApi'],
  ])('%s 下载失败及部分失败跨刷新长期保留，重试成功后仍按原计时消失', async (source, apiName) => {
    vi.useFakeTimers()
    const api = (await import('../api'))[apiName]
    const cards = await import('./usePersistentTaskCards')
    cards.rememberTaskCard('download', {
      taskSource: source, taskIds: ['one', 'two'], title: '下载任务正在后台运行',
    }, '/asmr-sync')
    const tasks = [
      { id: 'one', status: 'failed', error_message: '没有通过校验的下载项' },
      { id: 'two', status: 'completed', display_status: 'partial_failed', progress: 100 },
    ]
    api.status.mockResolvedValue({ tasks, total_tasks: 2 })
    await cards.refreshPersistentTaskCards()
    vi.advanceTimersByTime(24 * 60 * 60 * 1000)
    cards.expirePersistentTaskCards()
    expect(cards.persistentTaskCards.download.dismissed).not.toBe(true)
    expect(cards.persistentTaskCards.download.expiresAt).toBeUndefined()
    vi.resetModules()
    const restored = await import('./usePersistentTaskCards')
    const restoredApi = (await import('../api'))[apiName]
    restoredApi.status.mockResolvedValue({ tasks, total_tasks: 2 })
    await restored.refreshPersistentTaskCards()
    expect(restored.verifiedTaskCards.has('download')).toBe(true)
    expect(restored.persistentTaskCards.download.props.completed).toBe(false)
    expect(restored.persistentTaskCards.download.props.detailText).toBe('没有通过校验的下载项')
    restoredApi.status.mockResolvedValue({
      tasks: tasks.map(task => ({ id: task.id, status: 'completed', progress: 100 })), total_tasks: 2,
    })
    await restored.refreshPersistentTaskCards()
    vi.advanceTimersByTime(restored.TASK_CARD_RETENTION_MS)
    restored.expirePersistentTaskCards()
    expect(restored.persistentTaskCards.download.dismissed).toBe(true)
  })

  it.each([['asmr', 'asmrSyncApi'], ['http', 'httpDownloadApi'], ['baidu', 'baiduNetdiskApi'], ['upload', 'localUploadApi'], ['subtitle', 'rjSubtitleApi']])('%s 恢复后标题、完成动画标记和进度随服务端状态一起更新', async (source, apiName) => {
    const api = (await import('../api'))[apiName]
    const { rememberTaskCard, persistentTaskCards, refreshPersistentTaskCards } = await import('./usePersistentTaskCards')
    rememberTaskCard('card', { taskSource: source, taskIds: ['one'], title: '任务正在后台运行' }, '/library')
    for (const [status, title] of [['completed', '任务已完成'], ['paused', '任务已暂停'], ['failed', '任务需要处理'], ['cancelled', '任务已取消'], ['processing', '任务正在后台运行']]) {
      api.status.mockResolvedValue({ tasks: [{ id: 'one', status, progress: status === 'completed' ? 0 : 42 }], total_tasks: 1 })
      await refreshPersistentTaskCards()
      expect(persistentTaskCards.card.props.title).toBe(title)
      expect(persistentTaskCards.card.props.completed).toBe(status === 'completed')
      expect(persistentTaskCards.card.props.percentage).toBe(status === 'completed' ? 100 : 42)
    }
  })
  it('关闭合并任务移除所有来源 ID，并使在途刷新失效，最后一条关闭后持久隐藏', async () => {
    const { dismissWorkbenchTask, rememberTaskCard, persistentTaskCards } = await import('./usePersistentTaskCards')
    const ids = ref(['old', 'new', 'other'])
    const tasks = ref(ids.value.map(id => ({ id, status: 'failed' })))
    const invalidate = vi.fn()
    rememberTaskCard('card', { taskSource: 'asmr', taskIds: ids.value }, '/circle-completion')
    dismissWorkbenchTask({ source_task_ids: ['old', 'new'] }, ids, tasks, 'card', invalidate)
    expect(ids.value).toEqual(['other'])
    expect(tasks.value.map(task => task.id)).toEqual(['other'])
    expect(invalidate).toHaveBeenCalledOnce()
    dismissWorkbenchTask({ id: 'other' }, ids, tasks, 'card', invalidate)
    expect(ids.value).toEqual([])
    expect(persistentTaskCards.card.dismissed).toBe(true)
  })
  it('大窗口内任务也保存，恢复入口接回原任务并隐藏重复小窗', async () => {
    const { usePersistentTaskWorkbench, persistentTaskCards, openTaskWorkbenches, openPersistentTaskCard } = await import('./usePersistentTaskCards')
    const route = reactive({ path: '/circle-completion', query: {} })
    const ids = ref(['one'])
    const tasks = ref([{ id: 'one', status: 'processing', progress: 35 }])
    const visible = ref(true)
    const background = ref(false)
    const refresh = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount({ setup() {
      usePersistentTaskWorkbench(route, 'asmr', ids, visible, background, refresh, { tasks })
      return () => null
    } })
    const id = '/circle-completion:asmr:download'
    expect(persistentTaskCards[id].props.percentage).toBe(35)
    expect(openTaskWorkbenches.has('/circle-completion:asmr')).toBe(true)
    visible.value = false
    ids.value = []
    await openPersistentTaskCard(id)
    await nextTick()
    expect(ids.value).toEqual(['one'])
    expect(visible.value).toBe(true)
    expect(refresh).toHaveBeenCalled()
    visible.value = false
    await openPersistentTaskCard(id)
    expect(visible.value).toBe(true)
    expect(refresh).toHaveBeenCalledTimes(2)
    visible.value = false
    refresh.mockImplementationOnce(async () => { tasks.value = [] })
    await openPersistentTaskCard(id)
    expect(visible.value).toBe(false)
    expect(persistentTaskCards[id]).toBeUndefined()
    wrapper.unmount()
    expect(openTaskWorkbenches.size).toBe(0)
  })
  it('所属页面之外不显示，失败保留，不存在的旧任务清理', async () => {
    const { asmrSyncApi } = await import('../api')
    const { rememberTaskCard, persistentTaskCards, verifiedTaskCards, refreshPersistentTaskCards, taskCardBelongsToPage } = await import('./usePersistentTaskCards')
    rememberTaskCard('old', { taskSource: 'asmr', taskIds: ['one'] }, '/circle-completion')
    expect(taskCardBelongsToPage(persistentTaskCards.old, '/')).toBe(false)
    expect(taskCardBelongsToPage(persistentTaskCards.old, '/circle-completion')).toBe(true)
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'failed', progress: 0 }] })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards.old).toBeDefined()
    expect(persistentTaskCards.old.expiresAt).toBeUndefined()
    expect(verifiedTaskCards.has('old')).toBe(true)
    rememberTaskCard('missing', { taskSource: 'asmr', taskIds: ['gone'] }, '/circle-completion')
    asmrSyncApi.status.mockResolvedValue({ tasks: [], total_tasks: 0 })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards.missing).toBeUndefined()
  })
  it('刷新恢复任务，暂停及断网保留，完成后限时展示且不重置计时', async () => {
    vi.useFakeTimers()
    localStorage.setItem('kikoerumanager.ui.persistentTaskCards', JSON.stringify({ download: { id: 'download', route: '/circle-completion', props: { taskSource: 'asmr', taskIds: ['one'], percentage: 10 } } }))
    const { asmrSyncApi } = await import('../api')
    const { persistentTaskCards, refreshPersistentTaskCards } = await import('./usePersistentTaskCards')
    expect(persistentTaskCards.download.props.taskIds).toEqual(['one'])
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'paused', progress: 42 }] })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards.download.props.percentage).toBe(42)
    asmrSyncApi.status.mockRejectedValueOnce(new Error('网络断开'))
    await refreshPersistentTaskCards()
    expect(persistentTaskCards.download).toBeDefined()
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'completed', progress: 100 }] })
    await refreshPersistentTaskCards()
    const expiresAt = persistentTaskCards.download.expiresAt
    expect(expiresAt).toBe(Date.now() + 60_000)
    vi.advanceTimersByTime(30_000)
    vi.resetModules()
    const restored = await import('./usePersistentTaskCards')
    const restoredApi = await import('../api')
    restoredApi.asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'completed', progress: 100 }] })
    await restored.refreshPersistentTaskCards()
    expect(restored.persistentTaskCards.download.expiresAt).toBe(expiresAt)
    expect(restored.persistentTaskCards.download.dismissed).not.toBe(true)
    vi.advanceTimersByTime(30_000)
    await restored.refreshPersistentTaskCards()
    expect(restored.persistentTaskCards.download.dismissed).toBe(true)
    expect(restored.verifiedTaskCards.has('download')).toBe(false)
  })

  it('display_status 为 completed 时小窗进入完成态并显示 100%', async () => {
    const { rememberTaskCard, refreshPersistentTaskCards, persistentTaskCards } = await import('./usePersistentTaskCards')
    const { localUploadApi } = await import('../api')
    rememberTaskCard('upload', { taskSource: 'upload', taskIds: ['one'], title: '库存上传任务' }, '/library')
    localUploadApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'processing', display_status: 'completed', progress: 0 }] })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards.upload.props.completed).toBe(true)
    expect(persistentTaskCards.upload.props.percentage).toBe(100)
  })

  it.each(['failed', 'partial_failed', 'cancelled', 'canceled'])('%s 页面与恢复状态一致，手动关闭后不复活，重试重新展示', async status => {
    vi.useFakeTimers()
    const { usePersistentTaskWorkbench, persistentTaskCards, dismissPersistentTaskCard, refreshPersistentTaskCards, mountedTaskCards } = await import('./usePersistentTaskCards')
    const { asmrSyncApi } = await import('../api')
    const tasks = ref([{ id: 'one', status, progress: 100 }])
    const background = ref(true)
    const wrapper = mount({ setup() {
      usePersistentTaskWorkbench(reactive({ path: '/circle-completion' }), 'asmr', ref(['one']), ref(false), background, vi.fn(), { tasks, cardProps: ref({ completed: true }) })
      return () => null
    } })
    const id = '/circle-completion:asmr:download'
    expect(background.value).toBe(true)
    expect(persistentTaskCards[id].props.completed).toBe(false)
    expect(Boolean(persistentTaskCards[id].expiresAt)).toBe(['cancelled', 'canceled'].includes(status))
    mountedTaskCards.add(id)
    vi.advanceTimersByTime(60_000)
    await refreshPersistentTaskCards()
    if (['failed', 'partial_failed'].includes(status)) expect(persistentTaskCards[id].dismissed).not.toBe(true)
    else expect(persistentTaskCards[id].dismissed).toBe(true)
    dismissPersistentTaskCard(id)
    tasks.value = [{ id: 'one', status, progress: 99 }]
    await nextTick()
    expect(persistentTaskCards[id].dismissed).toBe(true)
    wrapper.unmount()
    mountedTaskCards.delete(id)
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status, progress: 100, error_message: '测试失败原因' }] })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards[id].dismissed).toBe(true)
    expect(persistentTaskCards[id].props.detailText).toBe('测试失败原因')
    asmrSyncApi.status.mockResolvedValue({ tasks: [{ id: 'one', status: 'processing', progress: 5 }] })
    await refreshPersistentTaskCards()
    expect(persistentTaskCards[id].dismissed).toBe(false)
    expect(persistentTaskCards[id].expiresAt).toBeUndefined()
  })
})
