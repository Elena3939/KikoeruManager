// LightGallery 的 destroy 内部包含异步关闭，必须完成后再创建新实例。
export function createLibraryMediaGallery (createGallery) {
  let active = null
  let pending = Promise.resolve()
  let version = 0

  function dispose () {
    const session = active
    if (!session) return pending
    active = null
    const destroy = () => {
      const duration = session.gallery.destroy()
      return new Promise(resolve => {
        setTimeout(() => {
          session.host.removeEventListener('lgBeforeClose', session.beforeClose)
          session.host.removeEventListener('lgBeforeSlide', session.beforeSlide)
          session.host.removeEventListener('lgAfterClose', session.afterClose)
          session.host.remove()
          resolve()
        }, duration)
      })
    }
    pending = session.closing ? session.closed.then(destroy) : destroy()
    return pending
  }

  return {
    async open (options, index) {
      const requested = ++version
      await dispose()
      if (requested !== version) return
      const host = document.createElement('div')
      host.className = 'kikoeru-lightgallery-host'
      document.body.appendChild(host)
      const gallery = createGallery(host, options)
      // 官方将未预载目标的加载延后 speed + 50ms，改为切图开始即加载。
      const beforeSlide = event => {
        const index = event.detail.index
        const item = gallery.galleryItems[index]
        if (!gallery.lGalleryOn) {
          gallery.getSlideItem(index).addClass('km-gallery-first')
          return
        }
        if (item?.video || item?.iframe || item?.__slideVideoInfo) return
        gallery.outer.find('.km-gallery-first').removeClass('km-gallery-first')
        queueMicrotask(() => {
          if (active?.gallery === gallery && !active.closing) gallery.loadContent(index, false)
        })
      }
      host.addEventListener('lgBeforeSlide', beforeSlide)
      let resolveClosed
      const session = {
        host, gallery, beforeSlide, closing: false, afterClose: null,
        beforeClose: () => { session.closing = true },
        closed: new Promise(resolve => { resolveClosed = resolve }),
      }
      // 官方事件触发时 lgOpened 尚未清零，延后到本次关闭回调结束后销毁。
      session.afterClose = () => queueMicrotask(() => {
        session.closing = false
        resolveClosed()
        if (active === session) dispose()
      })
      host.addEventListener('lgBeforeClose', session.beforeClose)
      host.addEventListener('lgAfterClose', session.afterClose)
      active = session
      gallery.openGallery(index)
    },
    close () {
      ++version
      return dispose()
    },
  }
}
