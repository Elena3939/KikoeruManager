import { useEffect, useMemo, useRef, useState } from 'react'
import { Plus, RotateCcw, Sparkles, X } from 'lucide-react'
import { Button, Modal } from '../../components/Primitives'

function makeRow(value = '') {
  return { key: `pwd-${Date.now()}-${Math.random().toString(16).slice(2)}`, value }
}

export function RetryPasswordsDialog({ open, title, description, confirmText = '开始重试', onConfirm, onClose }) {
  const [rows, setRows] = useState([makeRow('')])
  const firstInputRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setRows([makeRow('')])
    window.setTimeout(() => firstInputRef.current?.focus(), 30)
  }, [open])

  const effectiveCount = useMemo(() => rows.filter(row => row.value.trim()).length, [rows])

  if (!open) return null

  function confirm() {
    const seen = new Set()
    const passwords = []
    for (const row of rows) {
      const value = row.value.trim()
      if (!value || seen.has(value)) continue
      seen.add(value)
      passwords.push(value)
    }
    onConfirm({ passwords })
  }

  return (
    <Modal title={title || '重试问题项'} width={560} onClose={onClose} footer={(
      <>
        <span className="conflict-dialog-footnote">有效密码 {effectiveCount} / {rows.length}</span>
        <Button onClick={onClose}>取消</Button>
        <Button variant="primary" onClick={confirm}><RotateCcw size={14} />{confirmText}</Button>
      </>
    )}>
      <div className="conflict-password-dialog">
        <p><Sparkles size={13} />{description || '可填多个密码，按顺序依次尝试，任一命中即成功。全部留空表示走密码库 / RJ 推导 / 默认密码。'}</p>
        <div className="conflict-password-rows">
          {rows.map((row, index) => (
            <div key={row.key}>
              <span>{index + 1}</span>
              <input
                ref={index === 0 ? firstInputRef : null}
                value={row.value}
                placeholder={index === 0 ? '密码（可留空走密码库）' : `密码 ${index + 1}`}
                onChange={event => setRows(value => value.map(item => item.key === row.key ? { ...item, value: event.target.value } : item))}
                onKeyDown={event => {
                  if (event.key !== 'Enter') return
                  event.preventDefault()
                  if (index === rows.length - 1 && row.value.trim()) setRows(value => [...value, makeRow('')])
                  else confirm()
                }}
              />
              <button type="button" disabled={rows.length <= 1} onClick={() => setRows(value => value.filter(item => item.key !== row.key))}>
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
        <Button size="sm" onClick={() => setRows(value => [...value, makeRow('')])}><Plus size={14} />添加密码</Button>
      </div>
    </Modal>
  )
}
