import { useEffect, useMemo, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, Modal } from '../../components/Primitives'
import { filenameEncodingOptions, formatConflictLabel, getConflictId, getGarbledMeta } from './conflictUtils'

export function BatchRetryPasswordDialog({ open, targets = [], onConfirm, onClose }) {
  const [rows, setRows] = useState([])

  useEffect(() => {
    if (!open) return
    setRows(targets.map(conflict => ({
      conflictId: getConflictId(conflict),
      label: formatConflictLabel(conflict),
      password: '',
      filenameEncoding: getGarbledMeta(conflict) ? 'auto' : ''
    })))
  }, [open, targets])

  const passwordCount = useMemo(() => rows.filter(row => row.password.trim()).length, [rows])

  if (!open) return null

  return (
    <Modal title={`批量重试 ${targets.length} 个问题项`} width={760} onClose={onClose} footer={(
      <>
        <span className="conflict-dialog-footnote">指定密码 {passwordCount} / {rows.length}</span>
        <Button onClick={onClose}>取消</Button>
        <Button variant="primary" onClick={() => onConfirm(rows)}><RotateCcw size={14} />提交批量重试</Button>
      </>
    )}>
      <div className="batch-retry-dialog">
        {rows.map(row => (
          <div key={row.conflictId} className="batch-retry-row">
            <strong title={row.label}>{row.label}</strong>
            <input
              value={row.password}
              placeholder="密码，可留空"
              onChange={event => setRows(value => value.map(item => item.conflictId === row.conflictId ? { ...item, password: event.target.value } : item))}
            />
            <AppDropdown
              value={row.filenameEncoding || 'auto'}
              onChange={value => setRows(list => list.map(item => item.conflictId === row.conflictId ? { ...item, filenameEncoding: value } : item))}
              options={filenameEncodingOptions}
              width={190}
              disabled={!row.filenameEncoding}
            />
          </div>
        ))}
      </div>
    </Modal>
  )
}
