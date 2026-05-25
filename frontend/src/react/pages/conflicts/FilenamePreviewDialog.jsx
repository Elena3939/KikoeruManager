import { File, Folder, Music, XCircle } from 'lucide-react'
import { Button, Modal } from '../../components/Primitives'
import { formatBytes } from '../../utils/format'
import { formatPreviewName, getFilenamePreviewRows } from './conflictUtils'

function rowIcon(row) {
  const name = String(row.name || '')
  if (row.type === 'dir') return Folder
  if (/\.(flac|wav|ape|tta|wv|alac|aif|aiff|mp3|aac|m4a|m4b|ogg|opus|wma)$/i.test(name)) return Music
  return File
}

export function FilenamePreviewDialog({ open, preview, confirmText = '关闭', cancelText = '', onConfirm, onClose }) {
  if (!open || !preview) return null
  const encoding = preview.requested_encoding || preview.encoding || 'auto'
  const rows = getFilenamePreviewRows(preview, encoding)
  const garbledCount = rows.filter(row => row.garbled).length

  return (
    <Modal title="压缩包文件名预览" width={860} onClose={onClose} footer={(
      <>
        {cancelText ? <Button onClick={onClose}>{cancelText}</Button> : null}
        <Button variant="primary" onClick={onConfirm}>{confirmText}</Button>
      </>
    )}>
      <div className="filename-preview-dialog">
        <div className="filename-preview-meta">
          <span>编码 <b>{preview.encoding || 'auto'}</b></span>
          <span>codepage <b>{preview.codepage || 'auto'}</b></span>
          <span>密码来源 <b>{preview.password_source || '未指定'}</b></span>
          <span>文件 <b>{preview.file_count || rows.length}</b></span>
          {garbledCount ? <span data-tone="danger">疑似乱码 <b>{garbledCount}</b></span> : null}
        </div>
        <div className="filename-preview-tree">
          {rows.length ? rows.map((row, index) => {
            const Icon = rowIcon(row)
            return (
              <div key={`${row.name}-${index}`} className={row.garbled ? 'is-garbled' : ''}>
                <Icon size={14} />
                <span title={row.name}>{formatPreviewName(row.name, encoding)}</span>
                {row.garbled ? <em>乱码</em> : null}
                {row.score != null ? <b>{row.score}</b> : null}
                {row.size != null ? <small>{formatBytes(row.size)}</small> : null}
              </div>
            )
          }) : (
            <p><XCircle size={18} />暂无可展示文件</p>
          )}
        </div>
      </div>
    </Modal>
  )
}
