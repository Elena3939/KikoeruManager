import { useEffect, useMemo, useState } from 'react'
import { FileEdit, MoveRight, Sparkles } from 'lucide-react'
import { Button, Modal } from '../../components/Primitives'
import { formatBytes } from '../../utils/format'

function basenameOf(path) {
  const normalized = String(path || '').replace(/\\/g, '/')
  const index = normalized.lastIndexOf('/')
  return index >= 0 ? normalized.slice(index + 1) : normalized
}

function buildRows(conflict) {
  const payload = conflict?.new_metadata?.disguised_volume_set
  if (!payload) return []
  const suspect = Array.isArray(payload.suspect_files) ? payload.suspect_files : []
  const suggested = Array.isArray(payload.suggested_renames) ? payload.suggested_renames : []
  const suggestedByOld = new Map()
  for (const item of suggested) {
    if (item?.old) suggestedByOld.set(String(item.old), basenameOf(item.new))
  }
  return suspect.map((item, index) => {
    const oldPath = String(item.path || '')
    return {
      key: `vol-${index}-${oldPath}`,
      oldPath,
      oldName: basenameOf(oldPath),
      newName: suggestedByOld.get(oldPath) || basenameOf(oldPath),
      size: Number(item.size || 0),
      error: ''
    }
  })
}

function validateRows(rows, applyErrors = false) {
  const seen = new Map()
  let ok = true
  const next = rows.map((row, index) => {
    let error = ''
    const value = String(row.newName || '').trim()
    if (!value) error = '新文件名不能为空'
    else if (value.includes('/') || value.includes('\\')) error = '不能含路径分隔符'
    else if (value === '.' || value === '..' || value.split(/[\\/]/).includes('..')) error = '不允许 .. 路径段'
    else {
      const lowered = value.toLowerCase()
      if (seen.has(lowered)) error = `与第 ${seen.get(lowered) + 1} 行重名`
      else seen.set(lowered, index)
    }
    if (error) ok = false
    return applyErrors ? { ...row, error } : row
  })
  return { ok, rows: next }
}

export function VolumeRenameDialog({ open, conflict, onConfirm, onClose }) {
  const [rows, setRows] = useState([])
  const [autoRetry, setAutoRetry] = useState(true)

  useEffect(() => {
    if (!open) return
    setRows(buildRows(conflict))
    setAutoRetry(true)
  }, [conflict, open])

  const payload = conflict?.new_metadata?.disguised_volume_set
  const canSubmit = useMemo(() => validateRows(rows).ok && rows.length > 0, [rows])

  if (!open) return null

  function confirm() {
    const result = validateRows(rows, true)
    setRows(result.rows)
    if (!result.ok) return
    onConfirm({
      renames: rows.map(row => ({ old: row.oldPath, new: String(row.newName || '').trim() })),
      autoRetry
    })
  }

  return (
    <Modal title="手动重命名分卷" width={720} onClose={onClose} footer={(
      <>
        <label className="conflict-checkbox"><input type="checkbox" checked={autoRetry} onChange={event => setAutoRetry(event.target.checked)} />重命名后立即重试解压</label>
        <Button onClick={onClose}>取消</Button>
        <Button variant="warning" disabled={!canSubmit} onClick={confirm}><FileEdit size={14} />确认重命名</Button>
      </>
    )}>
      <div className="volume-rename-dialog">
        <p><Sparkles size={13} />目录：<code>{payload?.directory || '-'}</code></p>
        {rows.map((row, index) => (
          <div key={row.key} className={`volume-rename-row ${row.error ? 'is-error' : ''}`}>
            <span>{index + 1}</span>
            <b title={row.oldName}>{row.oldName}</b>
            <MoveRight size={14} />
            <input
              value={row.newName}
              onChange={event => setRows(value => value.map(item => item.key === row.key ? { ...item, newName: event.target.value, error: '' } : item))}
            />
            <em>{formatBytes(row.size)}</em>
            {row.error ? <small>{row.error}</small> : null}
          </div>
        ))}
      </div>
    </Modal>
  )
}
