import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('工作台关闭状态', () => {
  beforeEach(() => { vi.resetModules(); localStorage.clear() })

  it('业务关闭回调可保留未完成任务的后台卡片', async () => {
    const { useBackgroundWorkbenchManager } = await import('./useBackgroundWorkbenchManager')
    const manager = useBackgroundWorkbenchManager()
    manager.registerWorkbench({ id: 'active-upload', onClose: () => {
      manager.backgroundWorkbench('active-upload')
      return false
    } })
    manager.openWorkbench('active-upload')
    manager.invokeWorkbenchAction('active-upload', 'close')
    expect(manager.getWorkbenchState('active-upload').value).toMatchObject({ visible: false, cardVisible: true, backgroundActive: true })
  })

  it('普通工作台关闭仍重置窗口', async () => {
    const { useBackgroundWorkbenchManager } = await import('./useBackgroundWorkbenchManager')
    const manager = useBackgroundWorkbenchManager()
    manager.registerWorkbench({ id: 'ordinary' })
    manager.backgroundWorkbench('ordinary')
    manager.closeWorkbench('ordinary')
    expect(manager.getWorkbenchState('ordinary').value).toMatchObject({ visible: false, cardVisible: false, backgroundActive: false })
  })
})
