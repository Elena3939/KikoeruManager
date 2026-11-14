// 动态媒体没有缩略图触发元素，不走从来源图片放大的开场。默认遮罩会让首图额外等待 300ms。
export const LIGHT_GALLERY_OPEN_OPTIONS = {
  addClass: 'km-media-gallery',
  zoomFromOrigin: false,
  startClass: '',
  startAnimationDuration: 0,
  backdropDuration: 80,
  speed: 240,
}

// HTML5 视频的地址只放在 video.source 中，避免被 LightGallery 当成图片。
export function buildLightGalleryVideoItem (src, title = '') {
  return {
    title: title || '视频',
    downloadUrl: src,
    video: {
      // 由预览接口的 Content-Type 决定格式，不能把 WebM 等视频声明成 MP4。
      source: [{ src }],
      tracks: [],
      attributes: { controls: true, autoplay: true, playsinline: true, preload: 'metadata' },
    },
  }
}
