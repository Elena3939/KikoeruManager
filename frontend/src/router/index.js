import { createRouter, createWebHistory } from 'vue-router'
import { securityGateApi } from '../api'

const Dashboard = () => import('../views/Dashboard.vue')
const Tasks = () => import('../views/Tasks.vue')
const Conflicts = () => import('../views/Conflicts.vue')
const Settings = () => import('../views/Settings.vue')
const Logs = () => import('../views/Logs.vue')
const Library = () => import('../views/Library.vue')
const PasswordVault = () => import('../views/PasswordVault.vue')
const ExistingFolders = () => import('../views/ExistingFolders.vue')
const ASMRSync = () => import('../views/ASMRSync.vue')
const LibraryBackup = () => import('../views/LibraryBackup.vue')
const SubtitleImport = () => import('../views/SubtitleImport.vue')
const ActivityHistory = () => import('../views/ActivityHistory.vue')
const CircleCompletion = () => import('../views/CircleCompletion.vue')
const VerifyGate = () => import('../views/VerifyGate.vue')
const BlockedGate = () => import('../views/BlockedGate.vue')

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: {
      title: '概览',
      icon: 'HomeFilled',
      closable: false,
      cache: true
    }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: Tasks,
    meta: {
      title: '任务队列',
      icon: 'List',
      cache: false
    }
  },
  {
    path: '/conflicts',
    name: 'Conflicts',
    component: Conflicts,
    meta: {
      title: '问题作品',
      icon: 'WarningFilled',
      cache: true
    }
  },
  {
    path: '/library',
    name: 'Library',
    component: Library,
    meta: {
      title: '库存管理',
      icon: 'Box',
      cache: true
    }
  },
  {
    path: '/subtitle-import',
    name: 'SubtitleImport',
    component: SubtitleImport,
    meta: {
      title: '字幕补配',
      icon: 'Tickets',
      cache: true
    }
  },
  {
    path: '/passwords',
    name: 'PasswordVault',
    component: PasswordVault,
    meta: {
      title: '密码库',
      icon: 'Lock',
      cache: true
    }
  },
  {
    path: '/existing-folders',
    name: 'ExistingFolders',
    component: ExistingFolders,
    meta: {
      title: '已有文件夹',
      icon: 'Folder',
      cache: true
    }
  },
  {
    path: '/asmr-sync',
    name: 'ASMRSync',
    component: ASMRSync,
    meta: {
      title: 'ASMR 同步下载',
      icon: 'Download',
      cache: true
    }
  },
  {
    path: '/baidu-netdisk',
    redirect: { path: '/asmr-sync', query: { tab: 'baidu' } }
  },
  {
    path: '/library-backup',
    name: 'LibraryBackup',
    component: LibraryBackup,
    meta: {
      title: '库存打包',
      icon: 'FolderOpened',
      cache: true
    }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
    meta: {
      title: '设置',
      icon: 'Setting',
      cache: true
    }
  },
  {
    path: '/logs',
    name: 'Logs',
    component: Logs,
    meta: {
      title: '日志',
      icon: 'Document',
      cache: false
    }
  },
  {
    path: '/circle-completion',
    name: 'CircleCompletion',
    component: CircleCompletion,
    meta: {
      title: '社团补全',
      icon: 'CollectionTag',
      cache: true
    }
  },
  {
    path: '/activity-history',
    name: 'ActivityHistory',
    component: ActivityHistory,
    meta: {
      title: '操作记录',
      icon: 'DataLine',
      cache: false
    }
  },
  {
    path: '/verify',
    name: 'VerifyGate',
    component: VerifyGate,
    meta: {
      title: '安全验证',
      cache: false,
      gatePage: true
    }
  },
  {
    path: '/blocked',
    name: 'BlockedGate',
    component: BlockedGate,
    meta: {
      title: '访问已阻止',
      cache: false,
      gatePage: true
    }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

const CHUNK_RELOAD_KEY_PREFIX = 'kikoerumanager.routeChunkReloaded:'
const SECURITY_GATE_STATUS_TTL_MS = 8000
const SECURITY_GATE_STATUS_TIMEOUT_MS = 800
let securityGateStatusCache = {
  value: null,
  expiresAt: 0,
  pending: null
}

function buildVerifyRedirect(to) {
  const next = encodeURIComponent(to.fullPath || '/')
  return `/verify?next=${next}`
}

async function getSecurityGateStatus() {
  const now = Date.now()
  if (securityGateStatusCache.value && securityGateStatusCache.expiresAt > now) {
    return securityGateStatusCache.value
  }
  if (!securityGateStatusCache.pending) {
    securityGateStatusCache.pending = securityGateApi.status({ timeout: SECURITY_GATE_STATUS_TIMEOUT_MS })
      .then((state) => {
        const canEnter = !state?.blocked && (!state?.enforced || state?.authenticated)
        securityGateStatusCache.value = canEnter ? state : null
        securityGateStatusCache.expiresAt = canEnter ? Date.now() + SECURITY_GATE_STATUS_TTL_MS : 0
        return state
      })
      .finally(() => {
        securityGateStatusCache.pending = null
      })
  }
  return securityGateStatusCache.pending
}

router.beforeEach(async (to) => {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('kikoerumanager:route:navigation-start', {
      detail: { to: to.fullPath || to.path || '/', startedAt: Date.now() }
    }))
  }
  if (to.meta?.gatePage) {
    return true
  }

  try {
    const state = await getSecurityGateStatus()
    if (state?.blocked) {
      return '/blocked'
    }
    if (state?.enforced && !state?.authenticated) {
      return buildVerifyRedirect(to)
    }
    return true
  } catch (error) {
    const data = error.response?.data || {}
    if (data.blocked) {
      return '/blocked'
    }
    if (data.gate_required) {
      return buildVerifyRedirect(to)
    }
    return true
  }
})

router.afterEach((to) => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('kikoerumanager:route:navigation-end', {
    detail: { to: to.fullPath || to.path || '/', endedAt: Date.now() }
  }))
})

function isRouteChunkLoadError(error) {
  const text = `${error?.name || ''} ${error?.message || ''} ${error?.stack || ''}`
  return /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk|CSS_CHUNK_LOAD_FAILED|error loading dynamically imported module/i.test(text)
}

router.onError((error, to) => {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('kikoerumanager:route:navigation-end', {
      detail: { to: to?.fullPath || to?.path || '/', endedAt: Date.now(), error: true }
    }))
  }
  if (typeof window === 'undefined' || !isRouteChunkLoadError(error)) return
  const target = to?.fullPath || window.location.pathname || '/'
  const key = `${CHUNK_RELOAD_KEY_PREFIX}${target}`
  if (window.sessionStorage.getItem(key) === '1') {
    console.error('[Router] 懒加载资源刷新后仍加载失败:', error)
    return
  }
  window.sessionStorage.setItem(key, '1')
  window.location.assign(target)
})

export default router
