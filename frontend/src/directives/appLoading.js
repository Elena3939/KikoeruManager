import { createApp, h, reactive } from 'vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'

function normalizeBinding(value) {
  if (typeof value === 'boolean') {
    return {
      loading: value,
      text: '',
      description: '',
      size: 120,
      minHeight: 160,
      maskClass: '',
      delay: 120,
      minVisible: 360,
    }
  }

  return {
    loading: Boolean(value?.loading),
    text: value?.text || '',
    description: value?.description || '',
    size: value?.size || 120,
    minHeight: value?.minHeight || 160,
    maskClass: value?.maskClass || '',
    delay: Number(value?.delay ?? 120),
    minVisible: Number(value?.minVisible ?? 360),
  }
}

function ensureOverlay(el, options) {
  if (el.__appLoadingOverlay) {
    const overlay = el.__appLoadingOverlay
    overlay.className = 'app-loading-mask'
    if (options.maskClass) {
      overlay.classList.add(...options.maskClass.split(' ').filter(Boolean))
    }
    return el.__appLoadingOverlay
  }

  const computedStyle = window.getComputedStyle(el)
  if (computedStyle.position === 'static') {
    el.dataset.appLoadingOriginalPosition = 'static'
    el.style.position = 'relative'
  }

  const overlay = document.createElement('div')
  overlay.className = 'app-loading-mask'

  if (options.maskClass) {
    overlay.classList.add(...options.maskClass.split(' ').filter(Boolean))
  }

  const mountNode = document.createElement('div')
  mountNode.className = 'app-loading-mask__mount'
  overlay.appendChild(mountNode)
  el.appendChild(overlay)

  const state = reactive({
    label: options.text,
    description: options.description,
    size: options.size,
    minHeight: options.minHeight,
  })

  const app = createApp({
    render() {
      return h(AppLoadingAnimation, {
        label: state.label,
        description: state.description,
        size: state.size,
        minHeight: state.minHeight,
      })
    },
  })

  app.mount(mountNode)

  el.__appLoadingOverlay = overlay
  el.__appLoadingApp = app
  el.__appLoadingState = state
  return overlay
}

function renderOverlay(el, options) {
  const overlay = ensureOverlay(el, options)
  overlay.style.display = ''
  if (el.__appLoadingState) {
    el.__appLoadingState.label = options.text
    el.__appLoadingState.description = options.description
    el.__appLoadingState.size = options.size
    el.__appLoadingState.minHeight = options.minHeight
  }
}

function clearShowTimer(el) {
  if (el.__appLoadingShowTimer) {
    clearTimeout(el.__appLoadingShowTimer)
    delete el.__appLoadingShowTimer
  }
}

function clearHideTimer(el) {
  if (el.__appLoadingHideTimer) {
    clearTimeout(el.__appLoadingHideTimer)
    delete el.__appLoadingHideTimer
  }
}

function hideOverlay(el) {
  if (el.__appLoadingOverlay) {
    el.__appLoadingOverlay.style.display = 'none'
  }
  delete el.__appLoadingShownAt
}

function scheduleHide(el) {
  clearHideTimer(el)

  const shownAt = el.__appLoadingShownAt
  if (!shownAt) {
    hideOverlay(el)
    return
  }

  const minVisible = Number(el.__appLoadingOptions?.minVisible ?? 360)
  const elapsed = Date.now() - shownAt
  const remain = Math.max(0, minVisible - elapsed)

  if (remain === 0) {
    hideOverlay(el)
    return
  }

  el.__appLoadingHideTimer = setTimeout(() => {
    hideOverlay(el)
  }, remain)
}

function scheduleShow(el, options) {
  clearShowTimer(el)
  clearHideTimer(el)

  const delay = Math.max(0, Number(options.delay ?? 120))
  const show = () => {
    renderOverlay(el, options)
    el.__appLoadingShownAt = Date.now()
  }

  if (delay === 0) {
    show()
    return
  }

  el.__appLoadingShowTimer = setTimeout(show, delay)
}

function updateOverlay(el, binding) {
  const options = normalizeBinding(binding.value)
  el.__appLoadingOptions = options

  if (!options.loading) {
    clearShowTimer(el)
    scheduleHide(el)
    return
  }

  if (el.__appLoadingOverlay && el.__appLoadingOverlay.style.display !== 'none') {
    renderOverlay(el, options)
    return
  }

  scheduleShow(el, options)
}

function cleanupOverlay(el) {
  clearShowTimer(el)
  clearHideTimer(el)

  if (el.__appLoadingApp) {
    el.__appLoadingApp.unmount()
    delete el.__appLoadingApp
  }

  if (el.__appLoadingOverlay) {
    el.__appLoadingOverlay.remove()
    delete el.__appLoadingOverlay
  }

  if (el.dataset.appLoadingOriginalPosition === 'static') {
    el.style.position = ''
    delete el.dataset.appLoadingOriginalPosition
  }

  delete el.__appLoadingOptions
  delete el.__appLoadingShownAt
  delete el.__appLoadingState
}

export const appLoadingDirective = {
  mounted(el, binding) {
    updateOverlay(el, binding)
  },
  updated(el, binding) {
    updateOverlay(el, binding)
  },
  unmounted(el) {
    cleanupOverlay(el)
  },
}
