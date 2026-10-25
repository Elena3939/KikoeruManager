import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted } from 'vue'

// 拖动实际浮层容器，分页器与同组任务卡片一起移动。
export function useFloatingCardDrag(card, identity, stackIndex = () => 0) {
  let target, observer, drag
  let storageKey
  const margin = 12
  const key = () => storageKey
  const viewport = () => {
    const view = window.visualViewport
    return { left: view?.offsetLeft || 0, top: view?.offsetTop || 0, width: view?.width || window.innerWidth, height: view?.height || window.innerHeight }
  }
  function place(x, y) {
    if (!target) return
    const view = viewport()
    const rect = target.getBoundingClientRect()
    const left = Math.max(view.left + margin, Math.min(x, view.left + view.width - (target.offsetWidth || rect.width) - margin))
    const top = Math.max(view.top + margin, Math.min(y, view.top + view.height - (target.offsetHeight || rect.height) - margin))
    Object.assign(target.style, { left: `${left}px`, top: `${top}px`, right: 'auto', bottom: 'auto' })
  }
  function constrain() {
    if (!target) return
    const rect = target.getBoundingClientRect()
    // 缓存页面移出文档时尺寸为零，不能把该位置写回；进出场动画的偏移也不应累积。
    if (!rect.width || !rect.height) return
    const left = parseFloat(target.style.left)
    const top = parseFloat(target.style.top)
    place(Number.isFinite(left) ? left : rect.left, Number.isFinite(top) ? top : rect.top)
  }
  function move(event) {
    if (!drag || event.pointerId !== drag.id) return
    place(drag.x + event.clientX - drag.startX, drag.y + event.clientY - drag.startY)
  }
  function finish(event) {
    if (!drag || (event && event.pointerId !== drag.id)) return
    drag.handle.releasePointerCapture?.(drag.id)
    drag = null
    target?.classList.remove('is-dragging')
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', finish)
    if (target) {
      try { localStorage.setItem(key(), JSON.stringify({ x: parseFloat(target.style.left), y: parseFloat(target.style.top) })) } catch (_) {}
    }
  }
  function startDrag(event) {
    if (event.button !== 0 || event.target.closest('button, a, input, [role=button]')) return
    if (!target) return
    constrain()
    const rect = target.getBoundingClientRect()
    event.preventDefault()
    drag = { id: event.pointerId, x: parseFloat(target.style.left) || rect.left, y: parseFloat(target.style.top) || rect.top, startX: event.clientX, startY: event.clientY, handle: event.currentTarget }
    drag.handle.setPointerCapture?.(event.pointerId)
    target.classList.add('is-dragging')
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }
  onMounted(() => {
    target = card.value?.closest('.workbench-host-stack') || card.value
    if (!target) return
    storageKey = `kikoerumanager.ui.floatingPosition.${target.matches('.workbench-host-stack') ? 'workbench-stack' : identity()}`
    const view = viewport()
    target.style.maxHeight = 'calc(100dvh - 24px)'
    // 单卡本身已裁切内容；只有多卡容器需要纵向滚动。
    // 显式限制横向，避免进出场缩放动画扩大滚动范围。
    target.style.overflowX = 'hidden'
    target.style.overflowY = target === card.value ? 'hidden' : 'auto'
    try {
      const saved = JSON.parse(localStorage.getItem(key()) || 'null')
      if (target.dataset.floatingPositioned) constrain()
      else if (Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) place(saved.x, saved.y)
      else place(view.left + view.width - target.offsetWidth - 24, view.top + view.height - target.offsetHeight - 88 - Math.max(0, Number(stackIndex()) || 0) * (target.offsetHeight + 12))
    } catch (_) { constrain() }
    target.dataset.floatingPositioned = 'true'
    observer = new ResizeObserver(constrain)
    observer.observe(target)
    window.addEventListener('resize', constrain)
    window.visualViewport?.addEventListener('resize', constrain)
    window.visualViewport?.addEventListener('scroll', constrain)
  })
  onActivated(() => { nextTick(constrain) })
  onDeactivated(finish)
  onBeforeUnmount(() => {
    finish()
    observer?.disconnect()
    window.removeEventListener('resize', constrain)
    window.visualViewport?.removeEventListener('resize', constrain)
    window.visualViewport?.removeEventListener('scroll', constrain)
  })
  return { startDrag }
}
