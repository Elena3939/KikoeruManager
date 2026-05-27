import { createApp, isVNode } from 'vue'
import { createPinia } from 'pinia'
import { autoAnimatePlugin } from '@formkit/auto-animate/vue'
import ElementPlus, { ElMessage } from 'element-plus'
import 'element-plus/dist/index.css'
import './index.css'
import './style.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import './dark-mode.css'
import router from './router'
import { appLoadingDirective } from './directives/appLoading'
import SuccessMessageIcon from './components/system/SuccessMessageIcon.vue'
import ErrorMessageIcon from './components/system/ErrorMessageIcon.vue'

function normalizeMessageOptions(options) {
  if (typeof options === 'string' || isVNode(options) || typeof options === 'function') {
    return { message: options }
  }
  if (options && typeof options === 'object') {
    return { ...options }
  }
  return { message: '' }
}

const originalSuccessMessage = ElMessage.success.bind(ElMessage)
ElMessage.success = (options = {}) => {
  const normalized = normalizeMessageOptions(options)
  return originalSuccessMessage({
    ...normalized,
    icon: normalized.icon || SuccessMessageIcon,
  })
}

const originalErrorMessage = ElMessage.error.bind(ElMessage)
ElMessage.error = (options = {}) => {
  const normalized = normalizeMessageOptions(options)
  return originalErrorMessage({
    ...normalized,
    icon: normalized.icon || ErrorMessageIcon,
  })
}

const app = createApp(App)
const pinia = createPinia()

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.directive('app-loading', appLoadingDirective)

app.use(pinia)
app.use(router)
app.use(autoAnimatePlugin)
app.use(ElementPlus)

router.isReady().finally(() => {
  app.mount('#app')
})
