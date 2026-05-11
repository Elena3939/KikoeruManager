/**
 * useViewport
 * ============================================================
 * 响应式视口断点 composable（单例 + matchMedia 监听）。
 *
 * 与 `index.css` 中 "Mobile Adaptation Foundation" 区块的断点一致：
 *   · mobile  : max-width 640px
 *   · tablet  : 641px ~ 1024px
 *   · desktop : min-width 1025px
 *
 * 使用：
 *   import { useViewport } from '@/composables/useViewport'
 *   const { isMobile, isTablet, isDesktop, isTouch, width } = useViewport()
 *
 *   // 模板中：
 *   <ElDialog :fullscreen="isMobile" ...>
 *   <div v-if="isDesktop">桌面端独有功能</div>
 *
 * 设计要点：
 *   - 模块级单例，避免每个组件都创建一份 matchMedia 监听
 *   - 只用 matchMedia 不用 resize 事件，浏览器原生节流
 *   - 返回 readonly refs，组件不能反向写入
 *   - SSR / 老浏览器兜底：window 不存在时返回桌面态默认值
 */

import { computed, ref, readonly } from 'vue'

const MOBILE_MAX = 640
const TABLET_MAX = 1024

const hasWindow = typeof window !== 'undefined'

// ---------------- 状态：模块级单例 ----------------
const widthRef = ref(hasWindow ? window.innerWidth : 1440)
const isTouchRef = ref(false)
let initialized = false

// ---------------- matchMedia 监听 ----------------
function initListeners() {
  if (initialized || !hasWindow || typeof window.matchMedia !== 'function') return
  initialized = true

  const mobileMQ = window.matchMedia(`(max-width: ${MOBILE_MAX}px)`)
  const tabletMQ = window.matchMedia(
    `(min-width: ${MOBILE_MAX + 1}px) and (max-width: ${TABLET_MAX}px)`
  )
  const touchMQ = window.matchMedia('(hover: none) and (pointer: coarse)')

  function syncWidth() {
    widthRef.value = window.innerWidth
  }

  // matchMedia 的 change 比 resize 更高效，浏览器只在跨断点时触发
  const handleBreakpointChange = () => {
    syncWidth()
  }
  // 仍然挂一个 resize（passive）来同步 width 数值，给少量需要精确宽度的场景用
  const resizeHandler = () => syncWidth()

  // 兼容旧 Safari：addListener / removeListener
  function addMQ(mq, handler) {
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', handler)
    } else if (typeof mq.addListener === 'function') {
      mq.addListener(handler)
    }
  }

  addMQ(mobileMQ, handleBreakpointChange)
  addMQ(tabletMQ, handleBreakpointChange)
  addMQ(touchMQ, () => {
    isTouchRef.value = touchMQ.matches
  })

  // 首屏同步
  isTouchRef.value = touchMQ.matches
  syncWidth()

  window.addEventListener('resize', resizeHandler, { passive: true })
  window.addEventListener('orientationchange', resizeHandler, { passive: true })
}

if (hasWindow) {
  initListeners()
}

// ---------------- 派生 computed ----------------
const isMobile = computed(() => widthRef.value <= MOBILE_MAX)
const isTablet = computed(
  () => widthRef.value > MOBILE_MAX && widthRef.value <= TABLET_MAX
)
const isDesktop = computed(() => widthRef.value > TABLET_MAX)
const isTabletOrBelow = computed(() => widthRef.value <= TABLET_MAX)
const isTabletUp = computed(() => widthRef.value > MOBILE_MAX)

// ---------------- 导出 ----------------
export function useViewport() {
  return {
    width: readonly(widthRef),
    isMobile,
    isTablet,
    isDesktop,
    isTabletOrBelow,
    isTabletUp,
    isTouch: readonly(isTouchRef),
    // 断点常量便于其他模块对齐
    MOBILE_MAX,
    TABLET_MAX
  }
}

export default useViewport
