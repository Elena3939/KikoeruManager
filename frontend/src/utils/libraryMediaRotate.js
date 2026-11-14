import lgRotate from 'lightgallery/plugins/rotate'

// 官方 3.0.0 在首个 beforeSlide 之前关闭时会读取尚未建立的旋转状态。
// 尚未进入幻灯片的图片没有旋转，避免关闭流程访问不存在的状态。
export default class LibraryMediaRotate extends lgRotate {
  isImageOrientationChanged () {
    return !!this.rotateValuesList[this.core.index] && super.isImageOrientationChanged()
  }
}
