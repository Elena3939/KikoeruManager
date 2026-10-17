import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, watch } from 'vue'
import ConflictMergeWorkbench from './ConflictMergeWorkbench.vue'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'

let wrapper
it('多个库存目标不默认选中，点击后传回完整目标', async () => {
  const targets = [
    { library_id: 'one', library_name: '库存一', path: '/library-one/RJ01731933' },
    { library_id: 'two', library_name: '库存二', path: '/library-two/RJ01731933' }
  ]
  const view = createWorkbench({ targetCandidates: targets })
  expect(view.findAll('.cmw-target-option')).toHaveLength(2)
  expect(view.emitted('select-target')).toBeUndefined()
  expect(view.text()).toContain('/library-two/RJ01731933')
  await view.findAll('.cmw-target-option')[1].trigger('click')
  expect(view.emitted('select-target')).toEqual([[targets[1]]])
})

afterEach(() => wrapper?.unmount())

function createWorkbench(props = {}) {
  wrapper = mount(ConflictMergeWorkbench, {
    props: { modelValue: true, ...props },
    global: {
      stubs: {
        Teleport: true,
        AppDropdown: true,
        AppLoadingAnimation: true,
        StatefulButton: { template: '<button :disabled="$attrs.disabled"><slot /></button>' },
      },
    },
  })
  return wrapper
}

describe('合并工作台任务与窗口分离', () => {
  it('点击背景不会关闭或终止，缩小也不会终止任务', async () => {
    const cancelAction = vi.fn()
    const view = createWorkbench({ loading: true, cancelAction })
    await view.get('.merge-dialog-overlay').trigger('click')
    expect(view.emitted('close')).toBeUndefined()
    expect(view.emitted('update:modelValue')).toBeUndefined()
    await view.get('[title="缩小，保留合并进度"]').trigger('click')
    expect(view.emitted('minimize')).toHaveLength(1)
    expect(cancelAction).not.toHaveBeenCalled()
    const cancel = view.findAll('button').find(button => button.text().includes('终止生成'))
    await cancel.trigger('click')
    expect(cancelAction).toHaveBeenCalledTimes(1)
  })

  it('失败原因常驻且可重试，不再显示加载动画或允许提交', async () => {
    const message = '解压新包失败：文件名过长\nRJ01731933/长文件.mp3'
    const view = createWorkbench({ loadingProgress: { status: 'failed', message } })
    expect(view.get('[role="alert"]').text()).toContain(message)
    expect(view.find('app-loading-animation-stub').exists()).toBe(false)
    expect(view.get('.cmw-submit-btn').attributes('disabled')).toBeDefined()
    await view.findAll('button').find(button => button.text() === '重新生成预览').trigger('click')
    expect(view.emitted('refresh')).toHaveLength(1)
  })

  it('通过统一后台小窗缩小和恢复后仍保留搜索与选择', async () => {
    const manager = useBackgroundWorkbenchManager()
    const id = 'merge-workbench-regression-test'
    manager.registerWorkbench({ id, actions: ['resume'] })
    manager.openWorkbench(id)
    const view = createWorkbench({ decisions: { 'track.mp3': 'new' } })
    const state = manager.getWorkbenchState(id)
    const stop = watch(() => state.value.visible, visible => view.setProps({ modelValue: visible }))
    try {
      await view.get('input').setValue('track')
      manager.backgroundWorkbench(id)
      await nextTick()
      await nextTick()
      expect(view.find('.cmw-shell').exists()).toBe(false)
      manager.resumeWorkbench(id)
      await nextTick()
      await nextTick()
      expect(view.get('input').element.value).toBe('track')
      expect(view.props('decisions')).toEqual({ 'track.mp3': 'new' })
    } finally {
      stop()
      manager.removeWorkbench(id)
    }
  })

  it('提交失败保留预览，并在工作台显示完整错误', () => {
    const preview = { items: [], session_id: 'session' }
    const view = createWorkbench({ preview, submitError: '目标目录写入失败：文件名过长' })
    expect(view.get('[role="alert"]').text()).toBe('目标目录写入失败：文件名过长')
    expect(view.props('preview')).toEqual(preview)
    expect(view.get('.cmw-submit-btn').attributes('disabled')).toBeUndefined()
  })
})
