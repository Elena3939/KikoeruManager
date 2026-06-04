import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Tasks from '../views/Tasks.vue'
import Conflicts from '../views/Conflicts.vue'
import Settings from '../views/Settings.vue'
import Logs from '../views/Logs.vue'
import Library from '../views/Library.vue'
import PasswordVault from '../views/PasswordVault.vue'
import ExistingFolders from '../views/ExistingFolders.vue'
import ASMRSync from '../views/ASMRSync.vue'
import LibraryBackup from '../views/LibraryBackup.vue'
import SubtitleImport from '../views/SubtitleImport.vue'
import ActivityHistory from '../views/ActivityHistory.vue'
import CircleCompletion from '../views/CircleCompletion.vue'
import VerifyGate from '../views/VerifyGate.vue'
import BlockedGate from '../views/BlockedGate.vue'
import { securityGateApi } from '../api'

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

function buildVerifyRedirect(to) {
  const next = encodeURIComponent(to.fullPath || '/')
  return `/verify?next=${next}`
}

router.beforeEach(async (to) => {
  if (to.meta?.gatePage) {
    return true
  }

  try {
    const state = await securityGateApi.status()
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

export default router
