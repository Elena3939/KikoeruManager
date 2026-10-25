import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { useSubtitleImportWorkbench } from './useSubtitleImportWorkbench'
import { useBackgroundWorkbenchManager } from './useBackgroundWorkbenchManager'

vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))

describe('字幕工作台小窗显示条件', () => {
  it.each([
    [{ total: 2, completed: 1, awaiting: 1 }, 'awaiting', ''],
    [{ total: 2, completed: 1, failed: 1 }, 'failed', 'warning'],
    [{ total: 2, completed: 2 }, 'completed', 'success'],
  ])('字幕汇总保留业务状态，不把待配对或失败当完成', (summary, key, progressStatus) => {
    const manager = useBackgroundWorkbenchManager()
    const id = 'subtitle-status-test'
    let state
    const wrapper = mount({ setup() {
      state = useSubtitleImportWorkbench({ route: { query: {} }, workbenchManager: manager, SUBTITLE_IMPORT_WORKBENCH_ID: id })
      return () => null
    } })
    state.handleWorkbenchStateChange(summary)
    expect(manager.getWorkbenchState(id).value.status.key).toBe(key)
    expect(manager.getWorkbenchState(id).value.progress.status).toBe(progressStatus)
    wrapper.unmount()
    manager.removeWorkbench(id)
  })
  it('空队列最小化不显示，有任务时显示，清空后消失', () => {
    const manager = useBackgroundWorkbenchManager()
    const id = 'subtitle-empty-queue-test'
    let state
    const wrapper = mount({
      setup() {
        state = useSubtitleImportWorkbench({ route: { query: {} }, workbenchManager: manager, SUBTITLE_IMPORT_WORKBENCH_ID: id })
        return () => null
      }
    })
    state.hideImportWorkbenchToBackground()
    expect(manager.backgroundCards.value.some(card => card.id === id)).toBe(false)
    state.handleWorkbenchStateChange({ total: 2, processing: 1 })
    expect(manager.backgroundCards.value.some(card => card.id === id)).toBe(true)
    state.handleWorkbenchStateChange({ total: 0 })
    expect(manager.backgroundCards.value.some(card => card.id === id)).toBe(false)
    wrapper.unmount()
    manager.removeWorkbench(id)
  })
})
