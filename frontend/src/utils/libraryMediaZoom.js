import lgZoom from 'lightgallery/plugins/zoom'

// 复用官方缩放和边界计算，滚轮事件每帧最多更新一次。
export default class LibraryMediaZoom extends lgZoom {
  init () {
    super.init()
    if (!this.settings.zoom) return
    let delta = 0
    let point
    this.wheelFrame = 0
    this.onWheel = event => {
      const slide = this.core.getSlideItem(this.core.index)
      if (!this.core.lgOpened || this.core.lgBusy || !this.isImageSlide(this.core.index) ||
        !slide.hasClass('lg-zoomable') || !event.target.closest('.lg-current .lg-img-wrap') || !event.deltaY) return
      event.preventDefault()
      event.stopPropagation()
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.core.outer.height() : 1
      delta += event.deltaY * unit
      point = { x: event.pageX, y: event.pageY }
      if (this.wheelFrame) return
      const index = this.core.index
      this.wheelFrame = requestAnimationFrame(() => {
        this.wheelFrame = 0
        const change = delta
        delta = 0
        if (!this.core.lgOpened || this.core.lgBusy || index !== this.core.index) return
        this.stopZoomSpring()
        this.setZoomEssentials()
        this.pageX = point.x
        this.pageY = point.y
        const previous = this.scale || 1
        const scale = Math.min(8, Math.max(1, previous * Math.exp(-Math.max(-240, Math.min(240, change)) * 0.002)))
        this.beginZoom(scale)
        this.zoomImage(scale, scale - previous, true, false)
      })
    }
    this.core.outer.get().addEventListener('wheel', this.onWheel, { passive: false })
  }

  destroy () {
    cancelAnimationFrame(this.wheelFrame)
    this.core.outer.get()?.removeEventListener('wheel', this.onWheel)
    super.destroy()
  }
}
