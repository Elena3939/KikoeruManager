import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TaskDetailPane from './TaskDetailPane.vue'

vi.mock('../common/AppEmptyState.vue', () => ({
  default: { template: '<div />' },
}))
import {
  countRemovedFilterEntries,
  getFilterRestoreAvailability,
  isRestoredFilterEntry,
} from './_filterRecovery.js'

const completedTask = {
  status: 'completed',
  details: { metadata: { filter_recovery: { target_ready: true } } },
}

describe('任务过滤项恢复状态', () => {
  it('允许完成任务还原有恢复数据的直接删除项', () => {
    const result = getFilterRestoreAvailability({
      status: 'removed',
      recoveryId: 'recovery-1',
    }, completedTask)
    expect(result).toEqual({
      enabled: true,
      reason: '',
      recoveryId: 'recovery-1',
      recoveryRelativePath: '',
    })
  })

  it('阻止单独还原随目录删除的子项', () => {
    const result = getFilterRestoreAvailability({
      status: 'removed',
      recoveryId: 'recovery-1',
      removedByDirectory: 'folder',
    }, completedTask)
    expect(result.enabled).toBe(false)
    expect(result.reason).toContain('上级目录')
  })

  it('允许按目录恢复数据还原其中一个文件', () => {
    const result = getFilterRestoreAvailability({
      type: 'file',
      status: 'removed',
      recoveryId: 'directory-recovery-1',
      recoveryRelativePath: 'nested/remove.txt',
      removedByDirectory: 'folder',
    }, completedTask)
    expect(result).toEqual({
      enabled: true,
      reason: '',
      recoveryId: 'directory-recovery-1',
      recoveryRelativePath: 'nested/remove.txt',
    })
  })

  it('旧任务没有恢复数据时保持不可用', () => {
    const result = getFilterRestoreAvailability({ status: 'removed' }, completedTask)
    expect(result).toEqual({ enabled: false, reason: '旧任务没有恢复数据' })
  })

  it('已还原项目不再计入删除数量', () => {
    const entries = [
      { status: 'removed', recoveryStatus: 'available' },
      { status: 'restored', recoveryStatus: 'restored' },
    ]
    expect(isRestoredFilterEntry(entries[1])).toBe(true)
    expect(countRemovedFilterEntries(entries)).toBe(1)
  })

  it('右键菜单点击后提交还原事件', async () => {
    const wrapper = mount(TaskDetailPane, {
      attachTo: document.body,
      props: {
        item: { ...completedTask, id: 'engine:task-1', title: '任务', actions: [] },
        fileTreeSections: [{
          key: 'files',
          label: '文件列表',
          rows: [{
            key: 'remove.txt',
            label: 'remove.txt',
            type: 'file',
            status: 'removed',
            recoveryId: 'recovery-1',
            depth: 0,
            hasChildren: false,
          }],
        }],
        formatRJCode: () => '',
        formatDateTime: () => '-',
        showProgress: () => false,
        getRecoveredNotice: () => '',
        getDLsiteFailureReason: () => '',
        getOutputPath: () => '',
      },
    })

    await wrapper.get('.task-file-tree-row').trigger('contextmenu', { clientX: 50, clientY: 50 })
    await nextTick()
    const button = document.body.querySelector('.task-filter-restore-menu__action')
    expect(button).not.toBeNull()
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(wrapper.emitted('restore-filtered')?.[0]?.[0]?.entry?.recoveryId).toBe('recovery-1')
    wrapper.unmount()
  })
})
