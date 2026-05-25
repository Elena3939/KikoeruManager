import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { IconButton } from '../../components/Primitives'
import { libraryApi } from '../../../api'
import { classifyLibraryEntryKind, itemName } from './libraryUtils'

const textEncodingOptions = [
  { value: 'auto', label: '自动识别' },
  { value: 'utf-8', label: 'UTF-8' },
  { value: 'utf-8-sig', label: 'UTF-8 BOM' },
  { value: 'shift_jis', label: 'Shift-JIS' },
  { value: 'cp932', label: 'CP932' },
  { value: 'gb18030', label: 'GB18030' },
  { value: 'big5', label: 'Big5' },
  { value: 'utf-16', label: 'UTF-16' }
]

export function LibraryMediaPreview({ state, libraryId, imageRows, onSwitchImage, onClose }) {
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [encoding, setEncoding] = useState('auto')
  const [dragging, setDragging] = useState(false)
  const [animating, setAnimating] = useState(false)
  const dragRef = useRef({ active: false, x: 0, y: 0, startX: 0, startY: 0 })
  const animationTimerRef = useRef(0)
  const item = state?.item || null
  const visible = Boolean(state?.visible && item)
  const kind = classifyLibraryEntryKind(item)
  const imageIndex = useMemo(() => imageRows.findIndex(row => row?.path === item?.path), [imageRows, item?.path])
  const canPrev = kind === 'image' && imageIndex > 0
  const canNext = kind === 'image' && imageIndex >= 0 && imageIndex < imageRows.length - 1

  useEffect(() => {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    flashTransformAnimation()
  }, [item?.path])

  useEffect(() => () => window.clearTimeout(animationTimerRef.current), [])

  useEffect(() => {
    if (!visible) return undefined
    function onKeyDown(event) {
      if (event.key === 'Escape') onClose?.()
      if (kind !== 'image') return
      if (event.key === '0') resetImageTransform()
      if (event.key === '+' || event.key === '=') setImageZoom(value => value * 1.18)
      if (event.key === '-') setImageZoom(value => value / 1.18)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [visible, kind, onClose])

  if (!visible) return null

  const url = buildPreviewUrl(libraryId, item.path, {
    encoding: kind === 'text' ? encoding : '',
    cacheBust: kind === 'text'
  })

  function switchImage(direction) {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    flashTransformAnimation()
    onSwitchImage(imageRows[imageIndex + direction])
  }

  function resetImageTransform() {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    flashTransformAnimation()
  }

  function setImageZoom(updater) {
    setZoom(value => {
      const raw = typeof updater === 'function' ? updater(value) : updater
      const next = Math.max(0.25, Math.min(6, Number(raw || 1)))
      if (next <= 1) setOffset({ x: 0, y: 0 })
      flashTransformAnimation()
      return next
    })
  }

  function flashTransformAnimation() {
    setAnimating(true)
    window.clearTimeout(animationTimerRef.current)
    animationTimerRef.current = window.setTimeout(() => setAnimating(false), 260)
  }

  function handleWheel(event) {
    if (kind !== 'image') return
    event.preventDefault()
    const direction = event.deltaY > 0 ? 1 / 1.16 : 1.16
    setImageZoom(value => value * direction)
  }

  function handleDoubleClick() {
    if (kind !== 'image') return
    if (zoom > 1.05) resetImageTransform()
    else setImageZoom(2)
  }

  function handlePointerDown(event) {
    if (kind !== 'image' || zoom <= 1) return
    dragRef.current = { active: true, x: event.clientX, y: event.clientY, startX: offset.x, startY: offset.y }
    setDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function handlePointerMove(event) {
    const drag = dragRef.current
    if (!drag.active) return
    setOffset({
      x: drag.startX + event.clientX - drag.x,
      y: drag.startY + event.clientY - drag.y
    })
  }

  function handlePointerUp(event) {
    dragRef.current.active = false
    setDragging(false)
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }

  return (
    <section className="library-media-preview">
      <div className="library-media-dialog">
        <header className="library-media-head">
          <strong>{itemName(item)}</strong>
          <div className="library-media-actions">
            {kind === 'image' ? (
              <>
                <IconButton title="上一张" disabled={!canPrev} onClick={() => switchImage(-1)}><ChevronLeft size={16} /></IconButton>
                <span>{imageIndex >= 0 ? `${imageIndex + 1} / ${imageRows.length}` : '- / -'}</span>
                <IconButton title="下一张" disabled={!canNext} onClick={() => switchImage(1)}><ChevronRight size={16} /></IconButton>
                <IconButton title="缩小" onClick={() => setImageZoom(value => value / 1.18)}><ZoomOut size={16} /></IconButton>
                <span>{Math.round(zoom * 100)}%</span>
                <IconButton title="放大" onClick={() => setImageZoom(value => value * 1.18)}><ZoomIn size={16} /></IconButton>
                <IconButton title="重置" onClick={resetImageTransform}><RotateCcw size={16} /></IconButton>
              </>
            ) : null}
            {kind === 'text' ? <AppDropdown value={encoding} onChange={setEncoding} options={textEncodingOptions} width={150} /> : null}
            <IconButton title="关闭" onClick={onClose}><X size={16} /></IconButton>
          </div>
        </header>
        <div
          className={`library-media-body ${kind === 'image' && zoom > 1 ? 'is-pannable' : ''} ${dragging ? 'is-dragging' : ''} ${animating ? 'is-transforming' : ''}`}
          onWheel={handleWheel}
          onDoubleClick={handleDoubleClick}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {kind === 'image' ? (
            <img
              src={url}
              alt={itemName(item)}
              draggable={false}
              style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }}
            />
          ) : kind === 'video' ? (
            <video src={url} controls autoPlay playsInline />
          ) : (
            <iframe src={url} title={itemName(item)} />
          )}
        </div>
      </div>
    </section>
  )
}

function buildPreviewUrl(libraryId, path, options = {}) {
  const base = libraryApi.browserPreviewUrl(libraryId, path)
  const params = []
  if (options.encoding && options.encoding !== 'auto') params.push(`encoding=${encodeURIComponent(options.encoding)}`)
  if (options.cacheBust) params.push(`_preview=${Date.now()}`)
  if (!params.length) return base
  return `${base}${base.includes('?') ? '&' : '?'}${params.join('&')}`
}
