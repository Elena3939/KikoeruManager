import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, nextTick, ref } from 'vue'
import { useSubtitleImportArchive } from './useSubtitleImportArchive'
import { subtitleImportApi } from '../api'
import { ElMessage } from 'element-plus'

vi.mock('../api', () => ({
  subtitleImportApi: { listPending: vi.fn(), executePending: vi.fn() }
}))
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), warning: vi.fn(), success: vi.fn() }
}))
vi.mock('./useSystemPrompt', () => ({ showSystemConfirm: vi.fn() }))

let app
afterEach(() => {
  app?.unmount()
  vi.useRealTimers()
})

function mountArchive() {
  let archive
  const visible = ref(false)
  app = createApp(defineComponent({
    setup() {
      archive = useSubtitleImportArchive({
        workbenchDialogVisible: visible,
        workbenchBackgroundActive: ref(false),
        route: { path: '/other' },
        getSubtitleWorkbenchFilterOptions: () => ({}),
        openImportedTask: vi.fn()
      })
      return () => null
    }
  }))
  app.mount(document.createElement('div'))
  return { archive, visible }
}

const candidate = { library_id: 'local', folder_path: '/library/RJ123456', ready_for_import: true }
const item = {
  id: 'failed-import', status: 'PENDING', can_execute: true, auto_import_blocked: true,
  preview: { candidates: [candidate], selected_candidate: candidate }
}

describe('字幕补配失败后的自动和手动执行', () => {
  it('刷新后保留禁止自动执行标记，同时允许手动导入', async () => {
    vi.useFakeTimers()
    subtitleImportApi.listPending.mockResolvedValue({ items: [item] })
    subtitleImportApi.executePending.mockResolvedValue({ success: true })
    const { archive, visible } = mountArchive()
    await archive.loadPendingImports()
    visible.value = true
    await nextTick()
    await vi.advanceTimersByTimeAsync(5000)
    expect(subtitleImportApi.executePending).not.toHaveBeenCalled()
    expect(await archive.executePendingImport()).toBe(true)
    expect(subtitleImportApi.executePending).toHaveBeenCalledTimes(1)
  })

  it('超时后失败记录转走时不误报导入成功', async () => {
    vi.useFakeTimers()
    subtitleImportApi.listPending.mockResolvedValueOnce({ items: [item] }).mockResolvedValue({ items: [] })
    subtitleImportApi.executePending.mockRejectedValue({ response: { status: 504 }, message: '请求超时' })
    const { archive } = mountArchive()
    await archive.loadPendingImports()
    await nextTick()
    const result = archive.executePendingImport()
    await vi.advanceTimersByTimeAsync(3000)
    expect(await result).toBe(false)
    expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('问题作品'))
  })
})
