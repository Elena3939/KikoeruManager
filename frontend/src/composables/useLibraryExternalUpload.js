import { ref, onBeforeUnmount } from 'vue'
import { showSystemAlert } from './useSystemPrompt'
import { captureUploadSources } from '../utils/browserUploadEntries'
import { startBrowserUpload } from './useBrowserUploads'

export function useLibraryExternalUpload(resolveTarget) {
  const uploadDropHint = ref('')
  const uploadDragState = ref(null)
  let frame = 0, highlight, lastEvent, hideTimer, valid = false
  const external = event => Array.from(event.dataTransfer?.types || []).includes('Files')
  const warn = message => { void showSystemAlert({ title: '无法上传', message, tone: 'warning' }).catch(() => {}) }
  function clear() {
    cancelAnimationFrame(frame)
    frame = 0
    highlight?.classList.remove('library-external-upload-target')
    highlight = null
    uploadDropHint.value = ''
    uploadDragState.value = null
    valid = false
  }
  function display(event) {
    highlight?.classList.remove('library-external-upload-target')
    const target = resolveTarget(event.target)
    valid = Boolean(target?.libraryId)
    uploadDropHint.value = target?.libraryId ? `上传到：${target.libraryName} / ${target.path || '根目录'}` : (target?.reason || '请选择实际可写目录')
    highlight = target?.libraryId ? target.element : null
    highlight?.classList.add('library-external-upload-target')
    const items = event.items || []
    uploadDragState.value = {
      x: Math.max(8, Math.min(event.clientX + 18, window.innerWidth - 310)),
      y: Math.max(8, Math.min(event.clientY + 22, window.innerHeight - 80)),
      count: event.count || 1,
      // 外部拖动的 protected 模式只读取类型，不读取内容或递归目录。
      items: items.slice(0, 3),
      valid,
    }
    return target
  }
  function onExternalUploadOver(event) {
    if (!external(event)) return
    event.preventDefault()
    event.stopPropagation()
    clearTimeout(hideTimer)
    // 浏览器要求同步设置 dropEffect；命中与高亮合并到每帧一次。
    event.dataTransfer.dropEffect = valid ? 'copy' : 'none'
    // 同步快照元数据，避免 RAF 执行时 DataTransfer 的保护区已失效。
    const items = []
    let count = 0
    for (const item of event.dataTransfer.items || []) {
      if (item.kind !== 'file') continue
      count++
      if (items.length < 3) items.push({ type: item.type })
    }
    lastEvent = { target: event.target, clientX: event.clientX, clientY: event.clientY, items, count }
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; display(lastEvent) })
    hideTimer = setTimeout(clear, 500)
  }
  function onExternalUploadLeave(event) {
    if (!event.currentTarget.contains(event.relatedTarget)) clear()
  }
  function onExternalUploadDrop(event) {
    if (!external(event)) return
    event.preventDefault()
    event.stopPropagation()
    const target = resolveTarget(event.target)
    const sources = captureUploadSources(event.dataTransfer)
    clear()
    if (!target?.libraryId) { warn(target?.reason || '请选择实际可写目录'); return }
    if (!sources.length) { warn('未读取到拖入文件'); return }
    // 固定真实库及路径，后续导航不能改变任务目标。
    void startBrowserUpload({ ...target }, sources).catch(error => warn(error.message))
  }
  onBeforeUnmount(() => { clearTimeout(hideTimer); clear() })
  return { uploadDropHint, uploadDragState, onExternalUploadOver, onExternalUploadLeave, onExternalUploadDrop }
}
