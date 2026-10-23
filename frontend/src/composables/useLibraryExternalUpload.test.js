import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { useLibraryExternalUpload } from './useLibraryExternalUpload'

vi.mock('./useBrowserUploads', () => ({ startBrowserUpload: vi.fn() }))
vi.mock('element-plus', () => ({ ElMessage: { warning: vi.fn(), error: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

it('外部多项拖动逐帧更新图标与目标，离开即清除，不读取文件', () => {
  let frame, state
  vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { frame = callback; return 1 }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const resolveTarget = vi.fn(() => ({ libraryId: 1, libraryName: '库存', path: '/目录' }))
  const wrapper = mount({ template: '<div />', setup() { state = useLibraryExternalUpload(resolveTarget) } })
  const read = vi.fn()
  const event = { target: wrapper.element, clientX: 20, clientY: 30, preventDefault: vi.fn(), stopPropagation: vi.fn(),
    dataTransfer: { types: ['Files'], items: [
      { kind: 'file', type: 'image/png', getAsFile: read },
      { kind: 'file', type: 'audio/mpeg', getAsFile: read },
    ] },
  }
  state.onExternalUploadOver(event)
  state.onExternalUploadOver(event)
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1)
  expect(resolveTarget).not.toHaveBeenCalled()
  frame()
  expect(state.uploadDragState.value).toMatchObject({ count: 2, valid: true, items: [{ type: 'image/png' }, { type: 'audio/mpeg' }] })
  expect(state.uploadDropHint.value).toBe('上传到：库存 / /目录')
  expect(read).not.toHaveBeenCalled()
  state.onExternalUploadLeave({ currentTarget: wrapper.element, relatedTarget: null })
  expect(state.uploadDragState.value).toBeNull()
  wrapper.unmount()
})
