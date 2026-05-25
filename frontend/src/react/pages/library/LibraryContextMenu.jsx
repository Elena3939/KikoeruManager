import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import {
  Copy,
  Captions,
  Eye,
  FilterX,
  FolderCog,
  FolderInput,
  FolderOpen,
  HardDrive,
  Pencil,
  Sparkles,
  Tags,
  Trash2,
  UploadCloud
} from 'lucide-react'
import { canApiRenameRow, canViewLibraryRow, isDirectory, itemName } from './libraryUtils'

export function LibraryContextMenu({
  state,
  selectedCount,
  selectedRows,
  busy,
  canAutoCircleGroup,
  autoCircleGroupRunning,
  canUpload,
  selectedUploadCount,
  canSubtitle,
  selectedSubtitleCount,
  selectedFilterDeleteCount,
  onClose,
  onAction
}) {
  const ref = useRef(null)
  const visible = state?.visible
  const row = state?.row || null
  const batchMode = Boolean(state?.batchMode)
  const apiRenameEnabled = batchMode ? selectedRows.some(canApiRenameRow) : canApiRenameRow(row)
  const manageEnabled = !batchMode && isDirectory(row)
  const viewEnabled = !batchMode && canViewLibraryRow(row)
  const deleteEnabled = batchMode ? selectedCount > 0 : Boolean(row)
  const autoCircleEnabled = !batchMode && Boolean(canAutoCircleGroup?.(row))
  const uploadEnabled = batchMode ? selectedUploadCount > 0 : Boolean(canUpload?.(row))
  const subtitleEnabled = batchMode ? selectedSubtitleCount > 0 : Boolean(canSubtitle?.(row))

  useEffect(() => {
    if (!visible) return undefined
    function closeIfOutside(event) {
      if (ref.current && !ref.current.contains(event.target)) onClose()
    }
    function closeOnScroll() {
      onClose()
    }
    document.addEventListener('mousedown', closeIfOutside, true)
    document.addEventListener('contextmenu', closeIfOutside, true)
    window.addEventListener('scroll', closeOnScroll, true)
    return () => {
      document.removeEventListener('mousedown', closeIfOutside, true)
      document.removeEventListener('contextmenu', closeIfOutside, true)
      window.removeEventListener('scroll', closeOnScroll, true)
    }
  }, [visible, onClose])

  if (!visible) return null

  const title = batchMode ? `批量操作 · ${selectedCount} 项` : itemName(row)
  const style = {
    left: Math.max(8, Math.min(Number(state.x || 0), window.innerWidth - 220)),
    top: Math.max(8, Math.min(Number(state.y || 0), window.innerHeight - 360))
  }

  const item = (action, label, Icon, options = {}) => (
    <button
      type="button"
      className={`library-context-item ${options.danger ? 'is-danger' : ''}`}
      disabled={options.disabled}
      onClick={() => onAction(action)}
    >
      <Icon size={14} strokeWidth={2.25} />
      <span>{label}</span>
      {options.badge ? <em>{options.badge}</em> : null}
    </button>
  )

  return createPortal(
    <div ref={ref} className="library-context-menu" style={style} onClick={event => event.stopPropagation()} onContextMenu={event => event.stopPropagation()}>
      <div className="library-context-title" title={title}>{title}</div>
      {!batchMode ? item('view', '观看 / 预览', Eye, { disabled: !viewEnabled }) : null}
      {!batchMode ? item('open', isDirectory(row) ? '进入目录' : '打开所在位置', FolderOpen) : null}
      {!batchMode ? item('copy_name', '复制文件名', Copy) : null}
      <div className="library-context-separator" />
      {!batchMode ? item('rename', '重命名', Pencil, { disabled: busy }) : null}
      {item('move', batchMode ? '批量移动到...' : '移动到...', FolderInput, { disabled: busy || !deleteEnabled })}
      {item('upload', batchMode ? '批量上传到服务器' : '上传到服务器', UploadCloud, {
        disabled: busy || !uploadEnabled,
        badge: batchMode ? selectedUploadCount || '' : ''
      })}
      {item('api_rename', batchMode ? '批量 API 重命名' : 'API 重命名', Sparkles, {
        disabled: busy || !apiRenameEnabled,
        badge: batchMode ? selectedRows.filter(canApiRenameRow).length || '' : ''
      })}
      {!batchMode ? item('auto_circle_group', '按社团分类', Tags, {
        disabled: busy || !autoCircleEnabled || autoCircleGroupRunning,
        badge: autoCircleGroupRunning ? '运行中' : ''
      }) : null}
      {item('subtitle', batchMode ? '批量抓字幕' : '识别抓字幕', Captions, {
        disabled: busy || !subtitleEnabled,
        badge: batchMode ? selectedSubtitleCount || '' : ''
      })}
      {!batchMode ? item('manage', '文件管理', FolderCog, { disabled: !manageEnabled }) : null}
      {item('compute_size', batchMode ? '批量计算大小' : '计算文件夹大小', HardDrive, {
        disabled: busy || (batchMode ? !selectedRows.some(isDirectory) : !isDirectory(row))
      })}
      {batchMode ? item('filter_delete', '批量删除过滤文件', FilterX, {
        disabled: busy || !selectedFilterDeleteCount,
        badge: selectedFilterDeleteCount || ''
      }) : null}
      <div className="library-context-separator" />
      {item('delete', batchMode ? '批量删除' : '删除', Trash2, { danger: true, disabled: busy || !deleteEnabled })}
    </div>,
    document.body
  )
}
