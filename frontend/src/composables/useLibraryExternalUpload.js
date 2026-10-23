import { ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { captureUploadSources } from '../utils/browserUploadEntries'
import { startBrowserUpload } from './useBrowserUploads'

export function useLibraryExternalUpload(resolveTarget) {
  const uploadDropHint = ref('')
  let frame = 0, highlight, lastEvent, hideTimer, valid = false
  const external = event => Array.from(event.dataTransfer?.types || []).includes('Files')
  function clear() {
    cancelAnimationFrame(frame)
    frame = 0
    highlight?.classList.remove('library-external-upload-target')
    highlight = null
    uploadDropHint.value = ''
    valid = false
  }
  function display(event) {
    highlight?.classList.remove('library-external-upload-target')
    const target = resolveTarget(event.target)
    valid = Boolean(target?.libraryId)
    uploadDropHint.value = target?.libraryId ? `上传到：${target.libraryName} / ${target.path || '根目录'}` : (target?.reason || '请选择实际可写目录')
    highlight = target?.libraryId ? target.element : null
    highlight?.classList.add('library-external-upload-target')
    return target
  }
  function onExternalUploadOver(event) {
    if (!external(event)) return
    event.preventDefault()
    event.stopPropagation()
    clearTimeout(hideTimer)
    // 浏览器要求同步设置 dropEffect；命中与高亮合并到每帧一次。
    event.dataTransfer.dropEffect = valid ? 'copy' : 'none'
    lastEvent = { target: event.target }
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
    if (!target?.libraryId) { ElMessage.warning(target?.reason || '请选择实际可写目录'); return }
    if (!sources.length) { ElMessage.warning('未读取到拖入文件'); return }
    // 固定真实库及路径，后续导航不能改变任务目标。
    void startBrowserUpload({ ...target }, sources).catch(error => ElMessage.error(error.message))
  }
  onBeforeUnmount(() => { clearTimeout(hideTimer); clear() })
  return { uploadDropHint, onExternalUploadOver, onExternalUploadLeave, onExternalUploadDrop }
}
