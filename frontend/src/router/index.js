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

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: {
      title: '概览',
      icon: 'HomeFilled',
      closable: false,
      cache: false
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
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
