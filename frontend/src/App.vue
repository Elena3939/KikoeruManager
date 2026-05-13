<template>
  <el-container class="app-container" :class="{ 'is-mobile-nav-open': mobileNavOpen, 'is-gate-route': isGateRoute }">
    <!-- 移动端顶栏：仅 ≤1024 显示（桌面端 display:none，零改动） -->
    <header v-if="!isGateRoute" class="app-mobile-topbar safe-area-top">
      <button
        type="button"
        class="app-mobile-trigger safe-touch-target"
        :aria-expanded="mobileNavOpen"
        aria-label="打开导航菜单"
        @click="mobileNavOpen = true"
      >
        <Menu :size="22" :stroke-width="2.2" />
      </button>
      <div class="app-mobile-brand">
        <div class="app-mobile-brand-mark">
          <Package2 :size="16" :stroke-width="2.2" />
        </div>
        <div class="app-mobile-brand-copy">
          <span class="app-mobile-brand-text">KikoeruManager</span>
          <span class="app-mobile-brand-version">v{{ appVersion }}</span>
        </div>
      </div>
      <NotificationBell class="app-mobile-bell" />
    </header>

    <!-- 移动端抽屉遮罩：点击关闭 -->
    <Transition name="app-drawer-mask">
      <div
        v-if="mobileNavOpen && !isGateRoute"
        class="app-drawer-mask"
        @click="mobileNavOpen = false"
      />
    </Transition>

    <el-aside v-if="!isGateRoute" width="248px" class="sidebar" :class="{ 'is-mobile-open': mobileNavOpen }">
      <div class="sidebar-shell">
        <div class="logo">
          <div class="logo-mark">
            <Package2 :size="22" :stroke-width="2.2" />
          </div>
          <div class="logo-copy">
            <span class="logo-text">KikoeruManager</span>
            <div class="logo-meta-row">
              <span class="logo-subtitle">v{{ appVersion }}</span>
              <NotificationBell class="logo-bell" />
            </div>
          </div>
        </div>

        <div class="sidebar-section-label">导航</div>

        <el-menu
          :default-active="route.path"
          router
          class="sidebar-menu"
        >
          <el-menu-item index="/">
            <House :size="18" :stroke-width="2.2" />
            <span>概览</span>
          </el-menu-item>

          <el-menu-item index="/tasks">
            <ListTodo :size="18" :stroke-width="2.2" />
            <span>任务队列</span>
          </el-menu-item>

          <el-menu-item index="/conflicts">
            <TriangleAlert :size="18" :stroke-width="2.2" />
            <span>问题作品</span>
            <el-badge v-if="conflictCount > 0" :value="conflictCount" class="conflict-badge" />
          </el-menu-item>

          <el-menu-item index="/library">
            <Boxes :size="18" :stroke-width="2.2" />
            <span>库存管理</span>
          </el-menu-item>

          <el-menu-item index="/subtitle-import">
            <Captions :size="18" :stroke-width="2.2" />
            <span>字幕补配</span>
          </el-menu-item>

          <el-menu-item index="/passwords">
            <KeyRound :size="18" :stroke-width="2.2" />
            <span>密码库</span>
          </el-menu-item>

          <el-menu-item index="/existing-folders">
            <FolderTree :size="18" :stroke-width="2.2" />
            <span>已有文件夹</span>
          </el-menu-item>

          <el-menu-item index="/asmr-sync">
            <Download :size="18" :stroke-width="2.2" />
            <span>ASMR 同步下载</span>
          </el-menu-item>

          <el-menu-item index="/circle-completion">
            <Tags :size="18" :stroke-width="2.2" />
            <span>社团补全</span>
          </el-menu-item>

          <el-menu-item index="/library-backup">
            <Archive :size="18" :stroke-width="2.2" />
            <span>库存打包</span>
          </el-menu-item>

          <el-menu-item index="/settings">
            <Settings2 :size="18" :stroke-width="2.2" />
            <span>设置</span>
          </el-menu-item>

          <el-menu-item index="/logs">
            <ScrollText :size="18" :stroke-width="2.2" />
            <span>日志</span>
          </el-menu-item>

          <el-menu-item index="/activity-history">
            <History :size="18" :stroke-width="2.2" />
            <span>操作记录</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-footer">
          <div class="sidebar-status-card">
            <div class="sidebar-status-header">
              <span class="sidebar-status-title">监视器</span>
              <el-tag :type="watcherStatus.is_running ? 'success' : 'info'" size="small" effect="plain">
                {{ watcherStatus.is_running ? '运行中' : '已停止' }}
              </el-tag>
            </div>
            <div class="sidebar-status-text">
              {{ watcherStatus.is_running ? '正在监听新文件进入队列。' : '当前没有自动监听任务。' }}
            </div>
            <el-button
              class="watcher-button"
              size="small"
              @click="toggleWatcher"
            >
              {{ watcherStatus.is_running ? '停止监视器' : '启动监视器' }}
            </el-button>
          </div>

          <div class="version-info">
            <span class="version-text">KikoeruManager</span>
            <button
              v-if="!isGateRoute"
              type="button"
              class="theme-toggle-button"
              :class="{ 'is-dark': isDarkTheme }"
              :aria-label="isDarkTheme ? '当前深色模式，点击切换到浅色模式' : '当前浅色模式，点击切换到深色模式'"
              :title="isDarkTheme ? '当前深色模式，点击切换到浅色模式' : '当前浅色模式，点击切换到深色模式'"
              @click="toggleTheme"
            >
              <Transition name="theme-icon" mode="out-in">
                <Moon
                  v-if="isDarkTheme"
                  key="moon"
                  class="theme-toggle-icon theme-toggle-icon-moon"
                  :size="15"
                  :stroke-width="2.5"
                />
                <Sun
                  v-else
                  key="sun"
                  class="theme-toggle-icon theme-toggle-icon-sun"
                  :size="15"
                  :stroke-width="2.5"
                />
              </Transition>
              <span class="theme-toggle-text">{{ isDarkTheme ? '深色' : '浅色' }}</span>
            </button>
          </div>
        </div>
      </div>
    </el-aside>

    <el-container class="main-frame">
      <el-main class="main-content main-shell">
        <div class="content-shell">
          <keep-alive :include="cachedViews">
            <component
              :is="currentViewComponent"
              :key="currentViewKey"
            />
          </keep-alive>
        </div>
      </el-main>
    </el-container>
    <BackgroundWorkbenchHost v-if="!isGateRoute" />
    <SystemPromptHost />
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Archive,
  Boxes,
  Captions,
  Download,
  FolderTree,
  History,
  House,
  KeyRound,
  ListTodo,
  Menu,
  Moon,
  Package2,
  ScrollText,
  Settings2,
  Sun,
  Tags,
  TriangleAlert
} from 'lucide-vue-next'
import { useWatcherStore } from './stores'
import Dashboard from './views/Dashboard.vue'
import Tasks from './views/Tasks.vue'
import Conflicts from './views/Conflicts.vue'
import Settings from './views/Settings.vue'
import Logs from './views/Logs.vue'
import Library from './views/Library.vue'
import PasswordVault from './views/PasswordVault.vue'
import ExistingFolders from './views/ExistingFolders.vue'
import ASMRSync from './views/ASMRSync.vue'
import LibraryBackup from './views/LibraryBackup.vue'
import SubtitleImport from './views/SubtitleImport.vue'
import ActivityHistory from './views/ActivityHistory.vue'
import CircleCompletion from './views/CircleCompletion.vue'
import VerifyGate from './views/VerifyGate.vue'
import BlockedGate from './views/BlockedGate.vue'
import BackgroundWorkbenchHost from './components/workbench/BackgroundWorkbenchHost.vue'
import SystemPromptHost from './components/system/SystemPromptHost.vue'
import NotificationBell from './components/system/NotificationBell.vue'
import router from './router'

const appVersion = '1.5.1'
const route = useRoute()
const watcherStore = useWatcherStore()
const conflictCount = ref(0)
const watcherStatus = ref({ is_running: false, watch_path: '', pending_files: [] })
const mobileNavOpen = ref(false)
const themeStorageKey = 'kikoerumanager.theme'
const isDarkTheme = ref(false)

// 路由切换时自动关闭移动端抽屉（点击菜单项后即关闭）
watch(() => route.fullPath, () => {
  if (mobileNavOpen.value) mobileNavOpen.value = false
})

// 抽屉打开时锁定 body 滚动；关闭时恢复
watch(mobileNavOpen, (open) => {
  if (typeof document === 'undefined') return
  if (open) {
    document.body.classList.add('app-mobile-nav-locked')
  } else {
    document.body.classList.remove('app-mobile-nav-locked')
  }
})
const routeComponentMap = {
  Dashboard,
  Tasks,
  Conflicts,
  Settings,
  Logs,
  Library,
  PasswordVault,
  ExistingFolders,
  ASMRSync,
  CircleCompletion,
  LibraryBackup,
  SubtitleImport,
  ActivityHistory,
  VerifyGate,
  BlockedGate
}
const isGateRoute = computed(() => Boolean(route.meta?.gatePage))
const currentViewComponent = computed(() => routeComponentMap[route.name] || Dashboard)
const cachedViews = computed(() =>
  router
    .getRoutes()
    .filter((item) => item.meta?.cache && item.name)
    .map((item) => String(item.name))
)
const currentViewKey = computed(() => {
  const routeName = String(route.name || '')
  if (cachedViews.value.includes(routeName)) {
    return routeName || String(route.path || '')
  }
  return String(route.fullPath || route.path || '')
})
let intervalId = null

onMounted(async () => {
  isDarkTheme.value = readInitialTheme()
  applyTheme()
  if (isGateRoute.value) return
  await refreshStatus()
  intervalId = setInterval(refreshStatus, 3000)
})

watch(isGateRoute, async (gateRoute) => {
  if (gateRoute) {
    if (intervalId) {
      clearInterval(intervalId)
      intervalId = null
    }
    return
  }
  await refreshStatus()
  if (!intervalId) {
    intervalId = setInterval(refreshStatus, 3000)
  }
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
    intervalId = null
  }
})

async function refreshStatus() {
  await watcherStore.fetchStatus()
  watcherStatus.value = watcherStore.status
}

async function toggleWatcher() {
  if (watcherStatus.value.is_running) {
    await watcherStore.stop()
  } else {
    await watcherStore.start()
  }
  await refreshStatus()
}

function readInitialTheme() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(themeStorageKey) === 'dark'
}

function applyTheme() {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('kikoerumanager-dark', isDarkTheme.value)
  document.body.classList.toggle('kikoerumanager-dark', isDarkTheme.value)
}

function toggleTheme() {
  isDarkTheme.value = !isDarkTheme.value
  applyTheme()
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(themeStorageKey, isDarkTheme.value ? 'dark' : 'light')
  }
}
</script>

<style>
body {
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    sans-serif;
}

html.kikoerumanager-dark,
body.kikoerumanager-dark {
  color-scheme: dark;
  background: #070b12;
}

html.kikoerumanager-dark body,
body.kikoerumanager-dark,
html.kikoerumanager-dark #app {
  background: #070b12;
}

html.kikoerumanager-dark .app-container {
  background: #070b12;
}

html.kikoerumanager-dark .sidebar-shell {
  background: rgba(15, 23, 42, 0.86);
  border-color: rgba(148, 163, 184, 0.14);
  box-shadow: 0 22px 56px rgba(0, 0, 0, 0.38);
}

html.kikoerumanager-dark .logo-text,
html.kikoerumanager-dark .sidebar-status-title,
html.kikoerumanager-dark .watcher-button,
html.kikoerumanager-dark .version-text,
html.kikoerumanager-dark .app-mobile-trigger,
html.kikoerumanager-dark .app-mobile-brand-text {
  color: #f8fafc;
}

html.kikoerumanager-dark .logo-subtitle,
html.kikoerumanager-dark .sidebar-section-label,
html.kikoerumanager-dark .sidebar-status-text,
html.kikoerumanager-dark .app-mobile-brand-version {
  color: rgba(226, 232, 240, 0.62);
}

html.kikoerumanager-dark .logo-mark,
html.kikoerumanager-dark .app-mobile-brand-mark {
  background: rgba(59, 130, 246, 0.16);
  color: #93c5fd;
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.16);
}

html.kikoerumanager-dark .sidebar-status-card {
  background: rgba(30, 41, 59, 0.76);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.12);
}

html.kikoerumanager-dark .watcher-button,
html.kikoerumanager-dark .version-text {
  background: rgba(15, 23, 42, 0.86);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.1);
}

html.kikoerumanager-dark .watcher-button:hover,
html.kikoerumanager-dark .watcher-button:focus {
  background: rgba(30, 41, 59, 0.92);
  border-color: rgba(148, 163, 184, 0.24);
  color: #f8fafc;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item {
  color: rgba(226, 232, 240, 0.74);
}

.app-container.is-gate-route {
  min-height: 100vh;
  background: #020617;
}

.app-container.is-gate-route .main-frame,
.app-container.is-gate-route .main-content,
.app-container.is-gate-route .content-shell {
  width: 100%;
  min-height: 100vh;
  padding: 0;
  margin: 0;
  max-width: none;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item > svg {
  color: rgba(203, 213, 225, 0.58);
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover {
  background: rgba(51, 65, 85, 0.72);
  color: #f8fafc;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover > svg {
  color: #f8fafc;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active {
  background: rgba(37, 99, 235, 0.18);
  color: #93c5fd;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active > svg {
  color: #60a5fa;
}

html.kikoerumanager-dark .theme-toggle-button {
  background: rgba(15, 23, 42, 0.36);
  border-color: rgba(147, 197, 253, 0.18);
  color: #dbeafe;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

html.kikoerumanager-dark .theme-toggle-button:hover {
  border-color: rgba(147, 197, 253, 0.34);
  color: #f8fafc;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12), inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

html.kikoerumanager-dark .el-card,
html.kikoerumanager-dark .el-dialog,
html.kikoerumanager-dark .el-drawer,
html.kikoerumanager-dark .el-message-box,
html.kikoerumanager-dark .el-popover,
html.kikoerumanager-dark .el-popper,
html.kikoerumanager-dark .el-dropdown__popper .el-dropdown-menu,
html.kikoerumanager-dark .el-picker-panel,
html.kikoerumanager-dark .el-select-dropdown {
  background: rgba(15, 23, 42, 0.96);
  border-color: rgba(148, 163, 184, 0.16);
  color: #e2e8f0;
}

html.kikoerumanager-dark .el-input__wrapper,
html.kikoerumanager-dark .el-textarea__inner {
  background: rgba(15, 23, 42, 0.88);
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.16) inset;
}

html.kikoerumanager-dark .el-input__inner,
html.kikoerumanager-dark .el-textarea__inner,
html.kikoerumanager-dark .el-form-item__label,
html.kikoerumanager-dark .el-dialog__title,
html.kikoerumanager-dark .el-message-box__title,
html.kikoerumanager-dark .el-message-box__message {
  color: #e2e8f0;
}

html.kikoerumanager-dark .el-table,
html.kikoerumanager-dark .el-table tr,
html.kikoerumanager-dark .el-table th.el-table__cell,
html.kikoerumanager-dark .el-table td.el-table__cell {
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  border-color: rgba(148, 163, 184, 0.14);
}

html.kikoerumanager-dark .content-shell {
  color: #e2e8f0;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-white,
html.kikoerumanager-dark [data-section="dashboard-command"] .bg-white,
html.kikoerumanager-dark [data-section="dashboard-tasks"],
html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-white,
html.kikoerumanager-dark [data-section="dashboard-archive"],
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-white,
html.kikoerumanager-dark .task-list-pane,
html.kikoerumanager-dark .task-card,
html.kikoerumanager-dark .el-card {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: #e2e8f0 !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-100,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-100,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-slate-100 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-command"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .hover\:bg-slate-50\/50:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .hover\:bg-slate-50\/50:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark .task-card:hover {
  background: rgba(30, 41, 59, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.24) !important;
}

html.kikoerumanager-dark .text-slate-900,
html.kikoerumanager-dark .text-slate-800,
html.kikoerumanager-dark .hover\:text-slate-900:hover {
  color: #f8fafc !important;
}

html.kikoerumanager-dark .text-slate-700,
html.kikoerumanager-dark .text-slate-600,
html.kikoerumanager-dark .hover\:text-slate-700:hover {
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .text-slate-500,
html.kikoerumanager-dark .text-slate-400 {
  color: #94a3b8 !important;
}

html.kikoerumanager-dark .border-slate-100,
html.kikoerumanager-dark .border-slate-200,
html.kikoerumanager-dark .border-slate-200\/80,
html.kikoerumanager-dark .hover\:border-slate-200:hover,
html.kikoerumanager-dark .hover\:border-slate-300:hover {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .dash-icon-btn,
html.kikoerumanager-dark .dash-cmd-btn:not(:first-child),
html.kikoerumanager-dark .dash-archive-refresh-btn,
html.kikoerumanager-dark .dash-archive-pager-btn,
html.kikoerumanager-dark [data-section="dashboard-tasks"] button:not(.theme-toggle-button),
html.kikoerumanager-dark [data-section="dashboard-archive"] button:not(.theme-toggle-button) {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.2) 0%, rgba(30, 41, 59, 0.86) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .dash-icon-btn:hover,
html.kikoerumanager-dark .dash-cmd-btn:not(:first-child):hover,
html.kikoerumanager-dark .dash-archive-refresh-btn:hover,
html.kikoerumanager-dark .dash-archive-pager-btn:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] button:not(.theme-toggle-button):hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] button:not(.theme-toggle-button):hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #f8fafc !important;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .dash-kpi {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.86) 0%, rgba(30, 41, 59, 0.92) 100%) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: #e2e8f0 !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .dash-kpi:hover {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.96) 0%, rgba(51, 65, 85, 0.9) 100%) !important;
  border-color: rgba(147, 197, 253, 0.3) !important;
}

html.kikoerumanager-dark .dash-status-chip {
  background: linear-gradient(180deg, rgba(20, 83, 45, 0.22) 0%, rgba(15, 23, 42, 0.84) 100%) !important;
  border-color: rgba(52, 211, 153, 0.22) !important;
  color: #d1fae5 !important;
  box-shadow: 0 8px 18px rgba(6, 78, 59, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.07) !important;
}

html.kikoerumanager-dark .dash-status-chip:hover {
  background: linear-gradient(180deg, rgba(5, 150, 105, 0.28) 0%, rgba(20, 83, 45, 0.84) 100%) !important;
  border-color: rgba(110, 231, 183, 0.34) !important;
}

html.kikoerumanager-dark .dash-icon-hover,
html.kikoerumanager-dark .dash-icon-default,
html.kikoerumanager-dark .el-button svg,
html.kikoerumanager-dark button svg {
  color: currentColor;
}

html.kikoerumanager-dark .dash-kpi .group-hover\:bg-slate-900,
html.kikoerumanager-dark .dash-kpi:hover .group-hover\:bg-slate-900 {
  background: rgba(96, 165, 250, 0.18) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark [data-section="dashboard-tasks"] .border-dashed {
  background: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .border-dashed,
html.kikoerumanager-dark [data-section="dashboard-hero"] .border-neutral-200,
html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-50:hover {
  background: rgba(30, 41, 59, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] select,
html.kikoerumanager-dark [data-section="dashboard-hero"] option {
  background: #0f172a !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: #e2e8f0 !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-900 {
  background: linear-gradient(180deg, #3b82f6 0%, #2563eb 52%, #1d4ed8 100%) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-800:hover {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 54%, #1e40af 100%) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-blue-600 {
  color: #93c5fd !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-amber-700,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-amber-700 {
  color: #fcd34d !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-amber-50,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-amber-50 {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(245, 158, 11, 0.26) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-emerald-600,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .text-emerald-600,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-emerald-600 {
  color: #6ee7b7 !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-sky-600,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .text-sky-600,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-sky-600 {
  color: #7dd3fc !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-violet-600,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .text-violet-600,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-violet-600 {
  color: #c4b5fd !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .text-rose-600,
html.kikoerumanager-dark [data-section="dashboard-hero"] .text-rose-500,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .text-rose-600,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .text-rose-500,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-rose-600,
html.kikoerumanager-dark [data-section="dashboard-archive"] .text-rose-500 {
  color: #fda4af !important;
}

html.kikoerumanager-dark [data-section="dashboard-command"] .bg-blue-600 {
  background: linear-gradient(180deg, #3b82f6 0%, #2563eb 52%, #1d4ed8 100%) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark .el-input__wrapper,
html.kikoerumanager-dark .el-radio-button__inner {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: #e2e8f0 !important;
}

html.kikoerumanager-dark .el-radio-button__original-radio:checked + .el-radio-button__inner {
  background: rgba(96, 165, 250, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark {
  --km-dark-bg: #070b12;
  --km-dark-surface: rgba(15, 23, 42, 0.92);
  --km-dark-surface-2: rgba(30, 41, 59, 0.9);
  --km-dark-surface-3: rgba(51, 65, 85, 0.82);
  --km-dark-border: rgba(148, 163, 184, 0.18);
  --km-dark-border-strong: rgba(147, 197, 253, 0.34);
  --km-dark-text: #e2e8f0;
  --km-dark-text-strong: #f8fafc;
  --km-dark-text-muted: #94a3b8;
  --km-dark-blue: #93c5fd;
  --km-dark-blue-bg: rgba(37, 99, 235, 0.2);
  --km-dark-blue-bg-strong: rgba(37, 99, 235, 0.34);
  --km-dark-green: #6ee7b7;
  --km-dark-green-bg: rgba(16, 185, 129, 0.16);
  --km-dark-amber: #fcd34d;
  --km-dark-amber-bg: rgba(245, 158, 11, 0.16);
  --km-dark-red: #fda4af;
  --km-dark-red-bg: rgba(244, 63, 94, 0.16);
  --km-dark-purple: #c4b5fd;
  --km-dark-purple-bg: rgba(139, 92, 246, 0.16);
}

html.kikoerumanager-dark .bg-white,
html.kikoerumanager-dark .bg-slate-50,
html.kikoerumanager-dark .bg-neutral-50,
html.kikoerumanager-dark .bg-gray-50 {
  background: var(--km-dark-surface) !important;
}

html.kikoerumanager-dark .bg-slate-100,
html.kikoerumanager-dark .bg-neutral-100,
html.kikoerumanager-dark .bg-gray-100 {
  background: var(--km-dark-surface-2) !important;
}

html.kikoerumanager-dark .page-shell,
html.kikoerumanager-dark .tasks-page,
html.kikoerumanager-dark .subtitle-page,
html.kikoerumanager-dark .settings-page,
html.kikoerumanager-dark .password-vault,
html.kikoerumanager-dark .library-page,
html.kikoerumanager-dark .conflicts-page,
html.kikoerumanager-dark .activity-page,
html.kikoerumanager-dark .asmr-sync-page,
html.kikoerumanager-dark .circle-completion-page,
html.kikoerumanager-dark .logs-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success),
html.kikoerumanager-dark .app-dd-trigger,
html.kikoerumanager-dark .tasks-toolbar-btn,
html.kikoerumanager-dark .subtitle-refresh-btn,
html.kikoerumanager-dark .subtitle-action-btn:not(.is-primary),
html.kikoerumanager-dark .subtitle-mini-btn,
html.kikoerumanager-dark .vault-btn,
html.kikoerumanager-dark .vault-toolbar-btn,
html.kikoerumanager-dark .vault-icon-btn,
html.kikoerumanager-dark .page-head-btn:not(.is-primary),
html.kikoerumanager-dark .lib-action-btn:not(.is-primary),
html.kikoerumanager-dark .conflicts-action-btn.is-slate {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success):hover,
html.kikoerumanager-dark .app-dd-trigger:hover,
html.kikoerumanager-dark .app-dd-trigger.is-open,
html.kikoerumanager-dark .tasks-toolbar-btn:hover,
html.kikoerumanager-dark .tasks-toolbar-btn.is-on,
html.kikoerumanager-dark .subtitle-refresh-btn:hover,
html.kikoerumanager-dark .subtitle-action-btn:not(.is-primary):hover,
html.kikoerumanager-dark .subtitle-mini-btn:hover,
html.kikoerumanager-dark .vault-btn:hover,
html.kikoerumanager-dark .vault-toolbar-btn:hover,
html.kikoerumanager-dark .vault-icon-btn:hover,
html.kikoerumanager-dark .page-head-btn:not(.is-primary):hover,
html.kikoerumanager-dark .lib-action-btn:not(.is-primary):hover,
html.kikoerumanager-dark .conflicts-action-btn.is-slate:hover {
  background: linear-gradient(180deg, var(--km-dark-blue-bg-strong) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .el-button--primary,
html.kikoerumanager-dark .subtitle-action-btn.is-primary,
html.kikoerumanager-dark .page-head-btn.is-primary,
html.kikoerumanager-dark .lib-action-btn.is-primary,
html.kikoerumanager-dark .vault-btn.is-primary,
html.kikoerumanager-dark .conflicts-action-btn.is-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 52%, #1d4ed8 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
}

html.kikoerumanager-dark .el-button--danger,
html.kikoerumanager-dark .is-danger,
html.kikoerumanager-dark .conflicts-action-btn.is-danger {
  background: linear-gradient(180deg, rgba(244, 63, 94, 0.34) 0%, rgba(127, 29, 29, 0.9) 100%) !important;
  border-color: rgba(253, 164, 175, 0.36) !important;
  color: #ffe4e6 !important;
  box-shadow: 0 12px 26px rgba(244, 63, 94, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .app-dd-menu {
  background: rgba(15, 23, 42, 0.98) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: 0 24px 54px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .app-dd-item {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .app-dd-item:hover,
html.kikoerumanager-dark .app-dd-item.is-active,
html.kikoerumanager-dark .app-dd-item.is-active:hover {
  background: var(--km-dark-blue-bg) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .app-dd-trigger-label,
html.kikoerumanager-dark .app-dd-trigger-icon,
html.kikoerumanager-dark .app-dd-trigger-caret,
html.kikoerumanager-dark .app-dd-item-icon,
html.kikoerumanager-dark .app-dd-item-description,
html.kikoerumanager-dark .app-dd-item-suffix {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .app-dd-item-check {
  color: #60a5fa !important;
}

html.kikoerumanager-dark .tasks-toolbar,
html.kikoerumanager-dark .tasks-toolbar-row,
html.kikoerumanager-dark .tasks-toolbar-search,
html.kikoerumanager-dark .vault-toolbar-panel,
html.kikoerumanager-dark .vault-toolbar-shell,
html.kikoerumanager-dark .subtitle-shell,
html.kikoerumanager-dark .subtitle-list-pane,
html.kikoerumanager-dark .subtitle-detail-pane,
html.kikoerumanager-dark .subtitle-info-card,
html.kikoerumanager-dark .subtitle-candidate-card,
html.kikoerumanager-dark .import-task-list-card,
html.kikoerumanager-dark .import-task-detail,
html.kikoerumanager-dark .import-task-row,
html.kikoerumanager-dark .workbench-card,
html.kikoerumanager-dark .notification-card,
html.kikoerumanager-dark .settings-card,
html.kikoerumanager-dark .settings-panel,
html.kikoerumanager-dark .config-section,
html.kikoerumanager-dark .template-card,
html.kikoerumanager-dark .vault-card,
html.kikoerumanager-dark .vault-list-card,
html.kikoerumanager-dark .library-card,
html.kikoerumanager-dark .conflicts-card,
html.kikoerumanager-dark .activity-card {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(15, 23, 42, 0.88) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .subtitle-detail-header,
html.kikoerumanager-dark .subtitle-info-card-header,
html.kikoerumanager-dark .import-task-list-head,
html.kikoerumanager-dark .workbench-card-head,
html.kikoerumanager-dark .el-table th.el-table__cell {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.96) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .subtitle-meta-item,
html.kikoerumanager-dark .subtitle-tree,
html.kikoerumanager-dark .subtitle-detail-alert,
html.kikoerumanager-dark .workbench-card-chip,
html.kikoerumanager-dark .task-card,
html.kikoerumanager-dark .import-task-row {
  background: var(--km-dark-surface-2) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-list-card:hover,
html.kikoerumanager-dark .subtitle-candidate-card:hover,
html.kikoerumanager-dark .import-task-row:hover,
html.kikoerumanager-dark .task-card:hover {
  background: var(--km-dark-surface-3) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .subtitle-list-card.is-active,
html.kikoerumanager-dark .subtitle-candidate-card.is-selected,
html.kikoerumanager-dark .task-card.is-active {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.24) 0%, rgba(30, 41, 59, 0.92) 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .tasks-toolbar-search-input,
html.kikoerumanager-dark input,
html.kikoerumanager-dark textarea,
html.kikoerumanager-dark select {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark input::placeholder,
html.kikoerumanager-dark textarea::placeholder {
  color: rgba(148, 163, 184, 0.72) !important;
}

html.kikoerumanager-dark .tasks-toolbar-search-icon,
html.kikoerumanager-dark .tasks-toolbar-search-clear,
html.kikoerumanager-dark .subtitle-list-card-source,
html.kikoerumanager-dark .subtitle-list-card-meta,
html.kikoerumanager-dark .subtitle-list-card-arrow,
html.kikoerumanager-dark .subtitle-detail-subtitle,
html.kikoerumanager-dark .subtitle-meta-label,
html.kikoerumanager-dark .subtitle-meta-value-muted,
html.kikoerumanager-dark .subtitle-tree-bullet,
html.kikoerumanager-dark .subtitle-tree-name.is-file,
html.kikoerumanager-dark .workbench-card-subtitle,
html.kikoerumanager-dark .workbench-card-text,
html.kikoerumanager-dark .import-section-tip {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .subtitle-list-card-title,
html.kikoerumanager-dark .subtitle-detail-title,
html.kikoerumanager-dark .subtitle-info-card-header h3,
html.kikoerumanager-dark .subtitle-meta-value,
html.kikoerumanager-dark .subtitle-tree-name.is-dir,
html.kikoerumanager-dark .subtitle-candidate-name,
html.kikoerumanager-dark .import-section-title,
html.kikoerumanager-dark .workbench-card-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-chip,
html.kikoerumanager-dark .set-chip,
html.kikoerumanager-dark .app-dd-badge {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.9) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: #cbd5e1 !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .lib-chip-success,
html.kikoerumanager-dark .set-chip-success,
html.kikoerumanager-dark .tone-success,
html.kikoerumanager-dark .tone-emerald,
html.kikoerumanager-dark .app-dd-badge.tone-emerald {
  background: linear-gradient(180deg, rgba(16, 185, 129, 0.2) 0%, rgba(6, 78, 59, 0.72) 100%) !important;
  border-color: rgba(110, 231, 183, 0.32) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark .lib-chip-warning,
html.kikoerumanager-dark .set-chip-warning,
html.kikoerumanager-dark .tone-warning,
html.kikoerumanager-dark .tone-amber,
html.kikoerumanager-dark .app-dd-badge.tone-amber {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.22) 0%, rgba(120, 53, 15, 0.72) 100%) !important;
  border-color: rgba(252, 211, 77, 0.34) !important;
  color: #fef3c7 !important;
}

html.kikoerumanager-dark .lib-chip-danger,
html.kikoerumanager-dark .tone-danger,
html.kikoerumanager-dark .tone-rose,
html.kikoerumanager-dark .app-dd-badge.tone-rose {
  background: linear-gradient(180deg, rgba(244, 63, 94, 0.22) 0%, rgba(127, 29, 29, 0.72) 100%) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #ffe4e6 !important;
}

html.kikoerumanager-dark .lib-chip-info,
html.kikoerumanager-dark .set-chip-info,
html.kikoerumanager-dark .tone-info,
html.kikoerumanager-dark .tone-sky,
html.kikoerumanager-dark .app-dd-badge.tone-sky,
html.kikoerumanager-dark .app-dd-badge.tone-violet {
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.2) 0%, rgba(30, 64, 175, 0.72) 100%) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: #dbeafe !important;
}

html.kikoerumanager-dark [class*="bg-white"],
html.kikoerumanager-dark [class*="bg-slate-50"],
html.kikoerumanager-dark [class*="from-white"],
html.kikoerumanager-dark [class*="to-slate-50"],
html.kikoerumanager-dark [class*="via-white"],
html.kikoerumanager-dark [class*="border-slate-100"],
html.kikoerumanager-dark [class*="border-slate-200"] {
  --tw-gradient-from: rgba(15, 23, 42, 0.94) var(--tw-gradient-from-position) !important;
  --tw-gradient-via: rgba(30, 41, 59, 0.9) var(--tw-gradient-via-position) !important;
  --tw-gradient-to: rgba(15, 23, 42, 0.88) var(--tw-gradient-to-position) !important;
  background-color: rgba(15, 23, 42, 0.92) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark [class*="text-slate-900"],
html.kikoerumanager-dark [class*="text-slate-800"],
html.kikoerumanager-dark [class*="text-slate-700"],
html.kikoerumanager-dark [class*="text-gray-900"],
html.kikoerumanager-dark [class*="text-gray-800"] {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark [class*="text-slate-600"],
html.kikoerumanager-dark [class*="text-slate-500"],
html.kikoerumanager-dark [class*="text-slate-400"],
html.kikoerumanager-dark [class*="text-gray-600"],
html.kikoerumanager-dark [class*="text-gray-500"] {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark [class*="bg-emerald-50"],
html.kikoerumanager-dark [class*="border-emerald-200"] {
  background: var(--km-dark-green-bg) !important;
  border-color: rgba(110, 231, 183, 0.32) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark [class*="bg-amber-50"],
html.kikoerumanager-dark [class*="border-amber-200"] {
  background: var(--km-dark-amber-bg) !important;
  border-color: rgba(252, 211, 77, 0.34) !important;
  color: #fef3c7 !important;
}

html.kikoerumanager-dark [class*="bg-red-50"],
html.kikoerumanager-dark [class*="bg-rose-50"],
html.kikoerumanager-dark [class*="border-red-"],
html.kikoerumanager-dark [class*="border-rose-"] {
  background: var(--km-dark-red-bg) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #ffe4e6 !important;
}

html.kikoerumanager-dark [class*="bg-violet-50"],
html.kikoerumanager-dark [class*="bg-blue-50"],
html.kikoerumanager-dark [class*="border-violet-200"],
html.kikoerumanager-dark [class*="border-blue-200"] {
  background: var(--km-dark-blue-bg) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: #dbeafe !important;
}

html.kikoerumanager-dark .metric-strip,
html.kikoerumanager-dark .overview-strip,
html.kikoerumanager-dark .timeline-shell,
html.kikoerumanager-dark .timeline-card,
html.kikoerumanager-dark .metric-cell,
html.kikoerumanager-dark .chart-card,
html.kikoerumanager-dark .distribution-card,
html.kikoerumanager-dark .log-toolbar,
html.kikoerumanager-dark .log-viewer,
html.kikoerumanager-dark .log-table,
html.kikoerumanager-dark .backup-page section,
html.kikoerumanager-dark .circle-layout,
html.kikoerumanager-dark .circle-sidebar,
html.kikoerumanager-dark .circle-main,
html.kikoerumanager-dark .circle-list-panel,
html.kikoerumanager-dark .circle-list-card,
html.kikoerumanager-dark .toolbar-card,
html.kikoerumanager-dark .work-grid,
html.kikoerumanager-dark .work-card,
html.kikoerumanager-dark .asmr-sync-page section,
html.kikoerumanager-dark .sync-card,
html.kikoerumanager-dark .sync-panel,
html.kikoerumanager-dark .download-card,
html.kikoerumanager-dark .task-detail-pane,
html.kikoerumanager-dark .task-list-pane {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(15, 23, 42, 0.88) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .metric-strip-head,
html.kikoerumanager-dark .metric-strip-row,
html.kikoerumanager-dark .toolbar-main,
html.kikoerumanager-dark .toolbar-stats-row,
html.kikoerumanager-dark .circle-search-box,
html.kikoerumanager-dark .circle-filter-bar,
html.kikoerumanager-dark .sync-stat-row,
html.kikoerumanager-dark .task-detail-header,
html.kikoerumanager-dark .task-list-header {
  background: rgba(30, 41, 59, 0.86) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .circle-list-card:hover,
html.kikoerumanager-dark .circle-list-card.is-active,
html.kikoerumanager-dark .work-card:hover,
html.kikoerumanager-dark .metric-cell:hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.24) 0%, rgba(30, 41, 59, 0.92) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .el-table,
html.kikoerumanager-dark .el-table__inner-wrapper,
html.kikoerumanager-dark .el-table__body-wrapper,
html.kikoerumanager-dark .el-table__header-wrapper,
html.kikoerumanager-dark .el-table tr,
html.kikoerumanager-dark .el-table th.el-table__cell,
html.kikoerumanager-dark .el-table td.el-table__cell,
html.kikoerumanager-dark .el-table__row,
html.kikoerumanager-dark .el-table__empty-block {
  background: rgba(15, 23, 42, 0.94) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .el-table__row:nth-child(even),
html.kikoerumanager-dark .el-table__row:nth-child(even) td.el-table__cell {
  background: rgba(30, 41, 59, 0.78) !important;
}

html.kikoerumanager-dark .el-table__row:hover,
html.kikoerumanager-dark .el-table__row:hover > td.el-table__cell {
  background: rgba(37, 99, 235, 0.2) !important;
}

html.kikoerumanager-dark .el-input-number,
html.kikoerumanager-dark .el-input-number__decrease,
html.kikoerumanager-dark .el-input-number__increase,
html.kikoerumanager-dark .el-slider__runway {
  background: rgba(30, 41, 59, 0.9) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .el-switch__core {
  border-color: rgba(96, 165, 250, 0.3) !important;
  background: rgba(30, 41, 59, 0.9) !important;
}

html.kikoerumanager-dark .el-switch.is-checked .el-switch__core {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
}

html.kikoerumanager-dark .page-head-search,
html.kikoerumanager-dark .page-head-search-input,
html.kikoerumanager-dark .search-engine-hint,
html.kikoerumanager-dark .log-action-btn,
html.kikoerumanager-dark .batch-action-button {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .AppEmptyState,
html.kikoerumanager-dark .empty-state,
html.kikoerumanager-dark .app-empty-state {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .conflicts-info-strip,
html.kikoerumanager-dark .conflicts-empty,
html.kikoerumanager-dark .conflicts-list-pane,
html.kikoerumanager-dark .conflicts-detail-pane {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(15, 23, 42, 0.88) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .conflicts-empty {
  border-style: dashed !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
}

html.kikoerumanager-dark .conflicts-list-header,
html.kikoerumanager-dark .conflicts-detail-header,
html.kikoerumanager-dark .conflicts-segmented {
  background: rgba(30, 41, 59, 0.88) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .conflicts-list-title,
html.kikoerumanager-dark .conflicts-list-card-title,
html.kikoerumanager-dark .conflicts-detail-title,
html.kikoerumanager-dark .conflicts-empty .text-slate-700,
html.kikoerumanager-dark .lib-info-value b {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-info-label,
html.kikoerumanager-dark .lib-info-meta,
html.kikoerumanager-dark .lib-info-sub,
html.kikoerumanager-dark .conflicts-list-hint,
html.kikoerumanager-dark .conflicts-list-card-type,
html.kikoerumanager-dark .conflicts-list-card-date,
html.kikoerumanager-dark .conflicts-detail-subtitle,
html.kikoerumanager-dark .conflicts-empty .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .lib-info-divider {
  background: linear-gradient(180deg, transparent, rgba(148, 163, 184, 0.22), transparent) !important;
}

html.kikoerumanager-dark .conflicts-segmented-item,
html.kikoerumanager-dark .conflicts-mini-btn,
html.kikoerumanager-dark .conflicts-refresh-btn {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .conflicts-segmented-item:hover,
html.kikoerumanager-dark .conflicts-segmented-item.is-active,
html.kikoerumanager-dark .conflicts-mini-btn:hover,
html.kikoerumanager-dark .conflicts-mini-btn.is-active,
html.kikoerumanager-dark .conflicts-refresh-btn:hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .conflicts-list-card {
  background: rgba(15, 23, 42, 0.42) !important;
  border-color: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .conflicts-list-card:hover,
html.kikoerumanager-dark .conflicts-list-card.is-selected,
html.kikoerumanager-dark .conflicts-list-card.is-active {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.24) 0%, rgba(30, 41, 59, 0.92) 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
}

html.kikoerumanager-dark .app-page-title,
html.kikoerumanager-dark h1.app-page-title {
  color: #ffffff !important;
  opacity: 1 !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .app-page-subtitle,
html.kikoerumanager-dark p.app-page-subtitle {
  color: #d1d5db !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .library .lib-info-strip,
html.kikoerumanager-dark .library .main-card,
html.kikoerumanager-dark .library .el-card.main-card,
html.kikoerumanager-dark .library .el-card__header,
html.kikoerumanager-dark .library .el-card__body {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(15, 23, 42, 0.88) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .library .lib-card-header,
html.kikoerumanager-dark .library .lib-toolbar,
html.kikoerumanager-dark .library .path-toolbar,
html.kikoerumanager-dark .library .pagination-wrap {
  background: rgba(30, 41, 59, 0.86) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .lib-card-title,
html.kikoerumanager-dark .library .file-name,
html.kikoerumanager-dark .library .file-link-btn,
html.kikoerumanager-dark .library .lib-info-value b {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .library .file-link-btn:hover {
  color: #93c5fd !important;
}

html.kikoerumanager-dark .library .search-result-library,
html.kikoerumanager-dark .library .empty-text,
html.kikoerumanager-dark .library .lib-info-label,
html.kikoerumanager-dark .library .lib-info-meta,
html.kikoerumanager-dark .library .lib-info-sub {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .lib-info-divider {
  background: linear-gradient(180deg, transparent, rgba(148, 163, 184, 0.22), transparent) !important;
}

html.kikoerumanager-dark .library .lib-btn,
html.kikoerumanager-dark .library .lib-btn-ghost,
html.kikoerumanager-dark .library .lib-btn-icon-tinted {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .library .lib-btn:hover,
html.kikoerumanager-dark .library .lib-btn-ghost:hover,
html.kikoerumanager-dark .library .lib-btn-icon-tinted:hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .library .el-table th.el-table__cell {
  background: rgba(30, 41, 59, 0.96) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .el-table td.el-table__cell {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .el-table__row:nth-child(odd),
html.kikoerumanager-dark .library .el-table__row:nth-child(odd) td.el-table__cell {
  background: rgba(15, 23, 42, 0.94) !important;
}

html.kikoerumanager-dark .library .el-table__row:nth-child(even),
html.kikoerumanager-dark .library .el-table__row:nth-child(even) td.el-table__cell {
  background: rgba(30, 41, 59, 0.78) !important;
}

html.kikoerumanager-dark .library .library-search-mark {
  background: rgba(245, 158, 11, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .library .el-pagination button,
html.kikoerumanager-dark .library .el-pagination .el-pager li,
html.kikoerumanager-dark .library .el-pagination .el-input__wrapper {
  background: rgba(30, 41, 59, 0.9) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .el-pagination .el-pager li.is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar,
html.kikoerumanager-dark .library .lib-batch-bar {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.94) 0%, rgba(15, 23, 42, 0.92) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .library .lib-path-label,
html.kikoerumanager-dark .library .lib-batch-info {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .lib-path-code,
html.kikoerumanager-dark .library .lib-batch-count-pill {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .library .lib-scope-switch {
  background: rgba(15, 23, 42, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .library .lib-scope-option {
  background: transparent !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .lib-scope-option:hover,
html.kikoerumanager-dark .library .lib-scope-option.is-active {
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.34) 0%, rgba(30, 64, 175, 0.8) 100%) !important;
  color: #ffffff !important;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .library .el-alert {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(252, 211, 77, 0.34) !important;
  color: #fef3c7 !important;
}

html.kikoerumanager-dark .library .el-alert .el-alert__title,
html.kikoerumanager-dark .library .el-alert .el-alert__description {
  color: #fef3c7 !important;
}

html.kikoerumanager-dark .library .el-checkbox__inner {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.36) !important;
}

html.kikoerumanager-dark .library .el-checkbox__input.is-checked .el-checkbox__inner,
html.kikoerumanager-dark .library .el-checkbox__input.is-indeterminate .el-checkbox__inner {
  background: #3b82f6 !important;
  border-color: #60a5fa !important;
}

html.kikoerumanager-dark .library .el-select__wrapper,
html.kikoerumanager-dark .library .el-pagination .el-select__wrapper,
html.kikoerumanager-dark .library .el-pagination .el-input__wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  box-shadow: none !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .el-pagination__total,
html.kikoerumanager-dark .library .el-pagination__jump,
html.kikoerumanager-dark .library .el-pagination__goto,
html.kikoerumanager-dark .library .el-pagination__classifier {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .el-pagination button.is-disabled,
html.kikoerumanager-dark .library .lib-btn:disabled,
html.kikoerumanager-dark .library .lib-btn-icon-tinted:disabled {
  background: rgba(30, 41, 59, 0.48) !important;
  border-color: rgba(148, 163, 184, 0.12) !important;
  color: rgba(148, 163, 184, 0.48) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .el-table::before,
html.kikoerumanager-dark .library .el-table__inner-wrapper::before,
html.kikoerumanager-dark .library .el-table__border-left-patch {
  background: rgba(148, 163, 184, 0.16) !important;
}

html.kikoerumanager-dark .library .el-table th.el-table__cell,
html.kikoerumanager-dark .library .el-table td.el-table__cell {
  border-bottom-color: rgba(148, 163, 184, 0.12) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"],
html.kikoerumanager-dark .menu-panel[data-library-row-menu="1"] {
  background: rgba(15, 23, 42, 0.98) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 24px 54px rgba(0, 0, 0, 0.44), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-header span {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item {
  background: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item:hover:not(:disabled) {
  background: rgba(37, 99, 235, 0.2) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item:disabled {
  color: rgba(148, 163, 184, 0.45) !important;
  opacity: 0.58 !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .border-slate-200 {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item-danger {
  color: #fecdd3 !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item-danger:hover:not(:disabled) {
  background: rgba(244, 63, 94, 0.18) !important;
  color: #ffe4e6 !important;
}

html.kikoerumanager-dark .custom-preview-modal.el-dialog,
html.kikoerumanager-dark .server-upload-preview-modal.el-dialog,
html.kikoerumanager-dark .lib-move-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .custom-preview-modal .window,
html.kikoerumanager-dark .server-upload-preview-modal .window,
html.kikoerumanager-dark .lib-move-modal .window,
html.kikoerumanager-dark .custom-preview-modal .glass-shell,
html.kikoerumanager-dark .server-upload-preview-modal .glass-shell,
html.kikoerumanager-dark .lib-move-modal .glass-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 70px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .custom-preview-modal .window-header,
html.kikoerumanager-dark .server-upload-preview-modal .window-header,
html.kikoerumanager-dark .lib-move-modal .window-header,
html.kikoerumanager-dark .custom-preview-modal .footer-row,
html.kikoerumanager-dark .server-upload-preview-modal .footer-row,
html.kikoerumanager-dark .lib-move-modal .footer-row,
html.kikoerumanager-dark .lib-move-modal .explorer-toolbar {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .title,
html.kikoerumanager-dark .server-upload-preview-modal .title,
html.kikoerumanager-dark .lib-move-modal .title,
html.kikoerumanager-dark .custom-preview-modal h1,
html.kikoerumanager-dark .custom-preview-modal h2,
html.kikoerumanager-dark .server-upload-preview-modal h1,
html.kikoerumanager-dark .server-upload-preview-modal h2,
html.kikoerumanager-dark .lib-move-modal h1,
html.kikoerumanager-dark .lib-move-modal h2 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal p,
html.kikoerumanager-dark .custom-preview-modal label,
html.kikoerumanager-dark .custom-preview-modal .summary,
html.kikoerumanager-dark .custom-preview-modal .target-path,
html.kikoerumanager-dark .custom-preview-modal .tree-size,
html.kikoerumanager-dark .server-upload-preview-modal p,
html.kikoerumanager-dark .server-upload-preview-modal label,
html.kikoerumanager-dark .server-upload-preview-modal .summary,
html.kikoerumanager-dark .server-upload-preview-modal .target-path,
html.kikoerumanager-dark .server-upload-preview-modal .tree-size,
html.kikoerumanager-dark .lib-move-modal p,
html.kikoerumanager-dark .lib-move-modal label,
html.kikoerumanager-dark .lib-move-modal .path-empty {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .custom-preview-modal .glass-panel,
html.kikoerumanager-dark .custom-preview-modal .glass-card,
html.kikoerumanager-dark .server-upload-preview-modal .glass-panel,
html.kikoerumanager-dark .server-upload-preview-modal .glass-card,
html.kikoerumanager-dark .lib-move-modal .glass-panel,
html.kikoerumanager-dark .lib-move-modal .glass-card,
html.kikoerumanager-dark .lib-move-modal .path-bar,
html.kikoerumanager-dark .lib-move-modal .nav-pane,
html.kikoerumanager-dark .lib-move-modal .file-list,
html.kikoerumanager-dark .lib-move-modal .content-pane {
  background: rgba(30, 41, 59, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .field-input,
html.kikoerumanager-dark .custom-preview-modal .select-button,
html.kikoerumanager-dark .custom-preview-modal .picker-button,
html.kikoerumanager-dark .custom-preview-modal .dropdown-panel,
html.kikoerumanager-dark .server-upload-preview-modal .field-input,
html.kikoerumanager-dark .server-upload-preview-modal .select-button,
html.kikoerumanager-dark .server-upload-preview-modal .picker-button,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-panel,
html.kikoerumanager-dark .lib-move-modal .search-input,
html.kikoerumanager-dark .lib-move-modal .crumb-btn,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .dropdown-item,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .dropdown-item:hover,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item:hover,
html.kikoerumanager-dark .lib-move-modal .crumb-btn:hover,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn:hover:not(:disabled) {
  background: rgba(37, 99, 235, 0.2) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal .tree-row,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row,
html.kikoerumanager-dark .lib-move-modal .tree-row,
html.kikoerumanager-dark .lib-move-modal .file-row,
html.kikoerumanager-dark .lib-move-modal .nav-item {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .tree-row:hover,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row:hover,
html.kikoerumanager-dark .lib-move-modal .tree-row:hover,
html.kikoerumanager-dark .lib-move-modal .file-row:hover,
html.kikoerumanager-dark .lib-move-modal .nav-item:hover {
  background: rgba(37, 99, 235, 0.16) !important;
}

html.kikoerumanager-dark .custom-preview-modal .tree-row-selected,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected,
html.kikoerumanager-dark .lib-move-modal .tree-row-selected,
html.kikoerumanager-dark .lib-move-modal .is-active {
  background: rgba(37, 99, 235, 0.24) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal .tree-name,
html.kikoerumanager-dark .server-upload-preview-modal .tree-name,
html.kikoerumanager-dark .lib-move-modal .tree-name,
html.kikoerumanager-dark .custom-preview-modal .summary-strong,
html.kikoerumanager-dark .server-upload-preview-modal .summary-strong {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal .secondary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .secondary-cta,
html.kikoerumanager-dark .lib-move-modal .secondary-cta,
html.kikoerumanager-dark .custom-preview-modal .interactive-chip,
html.kikoerumanager-dark .server-upload-preview-modal .interactive-chip,
html.kikoerumanager-dark .lib-move-modal .interactive-chip {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .el-dialog__header,
html.kikoerumanager-dark .subtitle-workbench-dialog .el-dialog__body {
  background: transparent !important;
}

html.kikoerumanager-dark .subtitle-workbench-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .subtitle-workbench-header {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-body {
  --tw-gradient-from: rgba(15, 23, 42, 0.96) var(--tw-gradient-from-position) !important;
  --tw-gradient-via: rgba(15, 23, 42, 0.94) var(--tw-gradient-via-position) !important;
  --tw-gradient-to: rgba(15, 23, 42, 0.92) var(--tw-gradient-to-position) !important;
  background-color: rgba(15, 23, 42, 0.94) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog h1,
html.kikoerumanager-dark .subtitle-workbench-dialog h2,
html.kikoerumanager-dark .subtitle-workbench-dialog h3,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-900,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-800,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog p,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-600,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-500,
html.kikoerumanager-dark .subtitle-workbench-dialog .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .bg-white,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-white\/80,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-white\/70,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-white\/60,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-white\/50,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50\/80,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50\/70,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50\/60,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50\/50,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-50\/40,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-100,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-100\/80,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-100\/90,
html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-100\/95 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-100,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200\/70,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200\/80,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-300 {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog button:not(.primary-cta):not(.el-button--primary),
html.kikoerumanager-dark .subtitle-workbench-btn {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog button:not(.primary-cta):not(.el-button--primary):hover,
html.kikoerumanager-dark .subtitle-workbench-btn:hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-900,
html.kikoerumanager-dark .subtitle-workbench-dialog .stage-tab-active,
html.kikoerumanager-dark .subtitle-workbench-dialog .is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog input,
html.kikoerumanager-dark .subtitle-workbench-dialog textarea,
html.kikoerumanager-dark .subtitle-workbench-dialog .el-input__wrapper,
html.kikoerumanager-dark .subtitle-workbench-dialog .el-textarea__inner {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .floating-card,
html.kikoerumanager-dark .filter-delete-floating-card {
  background: rgba(15, 23, 42, 0.96) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 22px 52px rgba(0, 0, 0, 0.46), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .floating-card .text-slate-900,
html.kikoerumanager-dark .filter-delete-floating-title,
html.kikoerumanager-dark .filter-delete-floating-percent {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .floating-card .text-slate-500,
html.kikoerumanager-dark .filter-delete-floating-mode {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .floating-card .bg-slate-50,
html.kikoerumanager-dark .floating-chip,
html.kikoerumanager-dark .filter-delete-floating-card [class*="bg-slate-50"] {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .floating-action-btn {
  background: rgba(30, 41, 59, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .floating-action-btn-emerald {
  background: linear-gradient(180deg, rgba(52, 211, 153, 0.94) 0%, rgba(5, 150, 105, 0.94) 100%) !important;
  border-color: rgba(110, 231, 183, 0.42) !important;
  color: #ecfdf5 !important;
}

html.kikoerumanager-dark .filter-delete-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .window,
html.kikoerumanager-dark .filter-delete-dialog .glass-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .window-header,
html.kikoerumanager-dark .filter-delete-dialog .fm-body,
html.kikoerumanager-dark .filter-delete-dialog .toolbar-row,
html.kikoerumanager-dark .filter-delete-dialog .tree-head,
html.kikoerumanager-dark .filter-delete-dialog .footer-row,
html.kikoerumanager-dark .filter-delete-dialog [class*="border-t"][class*="bg-slate-50"] {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .fm-body {
  background: rgba(15, 23, 42, 0.92) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .title,
html.kikoerumanager-dark .filter-delete-dialog .tree-name,
html.kikoerumanager-dark .filter-delete-dialog .selection-card .text-slate-900,
html.kikoerumanager-dark .filter-delete-dialog .fm-title-row {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog p,
html.kikoerumanager-dark .filter-delete-dialog .fd-progress,
html.kikoerumanager-dark .filter-delete-dialog .fd-background-tip,
html.kikoerumanager-dark .filter-delete-dialog .tree-sub,
html.kikoerumanager-dark .filter-delete-dialog .tree-size,
html.kikoerumanager-dark .filter-delete-dialog .tree-time,
html.kikoerumanager-dark .filter-delete-dialog .tree-time-date,
html.kikoerumanager-dark .filter-delete-dialog .tree-time-rule,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-500,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .filter-delete-alert.el-alert,
html.kikoerumanager-dark .filter-delete-dialog .el-alert--warning {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(252, 211, 77, 0.34) !important;
  color: #fef3c7 !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-alert--error {
  background: rgba(244, 63, 94, 0.14) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #ffe4e6 !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-alert__title,
html.kikoerumanager-dark .filter-delete-dialog .el-alert__description {
  color: inherit !important;
}

html.kikoerumanager-dark .filter-delete-dialog .fd-chip,
html.kikoerumanager-dark .filter-delete-dialog .fm-badge,
html.kikoerumanager-dark .filter-delete-dialog .selection-card {
  background: rgba(30, 41, 59, 0.84) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card,
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag,
html.kikoerumanager-dark .filter-delete-dialog .close-button,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"] {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog .close-button:hover,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"]:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 64, 175, 0.9) 100%) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card-danger,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-rose-600"] {
  background: linear-gradient(180deg, rgba(251, 113, 133, 0.94) 0%, rgba(190, 18, 60, 0.96) 100%) !important;
  border-color: rgba(253, 164, 175, 0.42) !important;
  color: #fff1f2 !important;
  box-shadow: 0 12px 26px rgba(244, 63, 94, 0.24) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card-primary,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-indigo-600"] {
  background: linear-gradient(180deg, #818cf8 0%, #4f46e5 100%) !important;
  border-color: rgba(165, 180, 252, 0.42) !important;
  color: #eef2ff !important;
}

html.kikoerumanager-dark .filter-delete-dialog .search-shell,
html.kikoerumanager-dark .filter-delete-dialog .search-input {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .search-input::placeholder {
  color: rgba(148, 163, 184, 0.62) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-panel,
html.kikoerumanager-dark .filter-delete-dialog .glass-panel,
html.kikoerumanager-dark .filter-delete-dialog .glass-card,
html.kikoerumanager-dark .filter-delete-dialog .tree-scroll {
  background: rgba(15, 23, 42, 0.88) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row:hover {
  background: rgba(37, 99, 235, 0.16) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row-selected {
  background: rgba(37, 99, 235, 0.24) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.36) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox-on,
html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox-partial {
  background: #3b82f6 !important;
  border-color: #60a5fa !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .filter-delete-dialog .preview-empty {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal.el-dialog,
html.kikoerumanager-dark .server-upload-preview-modal.el-dialog,
html.kikoerumanager-dark .lib-move-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .window,
html.kikoerumanager-dark .server-upload-preview-modal .window,
html.kikoerumanager-dark .lib-move-modal .window {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .window-header,
html.kikoerumanager-dark .remote-folder-picker-modal .explorer-toolbar,
html.kikoerumanager-dark .remote-folder-picker-modal .footer-row,
html.kikoerumanager-dark .server-upload-preview-modal .window-header,
html.kikoerumanager-dark .server-upload-preview-modal .footer-row,
html.kikoerumanager-dark .lib-move-modal .window-header,
html.kikoerumanager-dark .lib-move-modal .explorer-toolbar,
html.kikoerumanager-dark .lib-move-modal .footer-row {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .title,
html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-900,
html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-800,
html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-700,
html.kikoerumanager-dark .server-upload-preview-modal .title,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-900,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-800,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-700,
html.kikoerumanager-dark .lib-move-modal .title,
html.kikoerumanager-dark .lib-move-modal .text-slate-900,
html.kikoerumanager-dark .lib-move-modal .text-slate-800,
html.kikoerumanager-dark .lib-move-modal .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-600,
html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-500,
html.kikoerumanager-dark .remote-folder-picker-modal .text-slate-400,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-600,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-500,
html.kikoerumanager-dark .server-upload-preview-modal .text-slate-400,
html.kikoerumanager-dark .lib-move-modal .text-slate-600,
html.kikoerumanager-dark .lib-move-modal .text-slate-500,
html.kikoerumanager-dark .lib-move-modal .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .explorer-main,
html.kikoerumanager-dark .remote-folder-picker-modal .explorer-nav,
html.kikoerumanager-dark .remote-folder-picker-modal .explorer-list,
html.kikoerumanager-dark .remote-folder-picker-modal .fm-body,
html.kikoerumanager-dark .server-upload-preview-modal .content-grid,
html.kikoerumanager-dark .server-upload-preview-modal .left-column,
html.kikoerumanager-dark .server-upload-preview-modal .tree-panel,
html.kikoerumanager-dark .server-upload-preview-modal .tree-scroll,
html.kikoerumanager-dark .lib-move-modal .explorer-main,
html.kikoerumanager-dark .lib-move-modal .explorer-nav,
html.kikoerumanager-dark .lib-move-modal .explorer-list,
html.kikoerumanager-dark .lib-move-modal .fm-body {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-head,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-section-title,
html.kikoerumanager-dark .server-upload-preview-modal .section-head,
html.kikoerumanager-dark .lib-move-modal .fm-head,
html.kikoerumanager-dark .lib-move-modal .nav-section-title {
  background: rgba(30, 41, 59, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .path-bar,
html.kikoerumanager-dark .remote-folder-picker-modal .search-input,
html.kikoerumanager-dark .remote-folder-picker-modal .crumb-btn,
html.kikoerumanager-dark .remote-folder-picker-modal .fm-icon-btn,
html.kikoerumanager-dark .remote-folder-picker-modal .target-chip,
html.kikoerumanager-dark .remote-folder-picker-modal .rel-chip,
html.kikoerumanager-dark .server-upload-preview-modal .field-input,
html.kikoerumanager-dark .server-upload-preview-modal .select-button,
html.kikoerumanager-dark .server-upload-preview-modal .picker-button,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-panel,
html.kikoerumanager-dark .server-upload-preview-modal .target-path,
html.kikoerumanager-dark .lib-move-modal .path-bar,
html.kikoerumanager-dark .lib-move-modal .search-input,
html.kikoerumanager-dark .lib-move-modal .crumb-btn,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn,
html.kikoerumanager-dark .lib-move-modal .target-chip,
html.kikoerumanager-dark .lib-move-modal .rel-chip {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .search-input::placeholder,
html.kikoerumanager-dark .lib-move-modal .search-input::placeholder {
  color: rgba(148, 163, 184, 0.62) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-row,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-row,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item,
html.kikoerumanager-dark .lib-move-modal .fm-row,
html.kikoerumanager-dark .lib-move-modal .nav-row {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-row:hover,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-row:hover,
html.kikoerumanager-dark .remote-folder-picker-modal .crumb-btn:hover,
html.kikoerumanager-dark .remote-folder-picker-modal .fm-icon-btn:hover:not(:disabled),
html.kikoerumanager-dark .server-upload-preview-modal .tree-row:hover,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item:hover,
html.kikoerumanager-dark .lib-move-modal .fm-row:hover,
html.kikoerumanager-dark .lib-move-modal .nav-row:hover,
html.kikoerumanager-dark .lib-move-modal .crumb-btn:hover,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn:hover:not(:disabled) {
  background: rgba(37, 99, 235, 0.18) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-row-selected,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-row-active,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected,
html.kikoerumanager-dark .lib-move-modal .fm-row-selected,
html.kikoerumanager-dark .lib-move-modal .nav-row-active {
  background: rgba(37, 99, 235, 0.28) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.26) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-name,
html.kikoerumanager-dark .remote-folder-picker-modal .target-chip-path,
html.kikoerumanager-dark .remote-folder-picker-modal .rel-chip-value,
html.kikoerumanager-dark .server-upload-preview-modal .tree-name,
html.kikoerumanager-dark .server-upload-preview-modal .summary-strong,
html.kikoerumanager-dark .lib-move-modal .fm-name,
html.kikoerumanager-dark .lib-move-modal .target-chip-path,
html.kikoerumanager-dark .lib-move-modal .rel-chip-value {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-cell-time,
html.kikoerumanager-dark .remote-folder-picker-modal .rel-chip-label,
html.kikoerumanager-dark .server-upload-preview-modal .tree-size,
html.kikoerumanager-dark .server-upload-preview-modal .node-title-muted,
html.kikoerumanager-dark .lib-move-modal .fm-cell-time,
html.kikoerumanager-dark .lib-move-modal .rel-chip-label {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .nav-splitter,
html.kikoerumanager-dark .lib-move-modal .nav-splitter {
  background: rgba(148, 163, 184, 0.12) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .nav-splitter-line,
html.kikoerumanager-dark .lib-move-modal .nav-splitter-line {
  background: rgba(147, 197, 253, 0.36) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .secondary-cta,
html.kikoerumanager-dark .remote-folder-picker-modal .interactive-chip,
html.kikoerumanager-dark .server-upload-preview-modal .secondary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .interactive-chip,
html.kikoerumanager-dark .lib-move-modal .secondary-cta,
html.kikoerumanager-dark .lib-move-modal .interactive-chip {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .primary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .primary-cta,
html.kikoerumanager-dark .lib-move-modal .primary-cta {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-info-strip,
html.kikoerumanager-dark .subtitle-page .subtitle-shell,
html.kikoerumanager-dark .subtitle-page .subtitle-list-pane,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-pane {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-info-strip {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.92) 0%, rgba(15, 23, 42, 0.9) 100%) !important;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented,
html.kikoerumanager-dark .subtitle-page .subtitle-list-header,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-header,
html.kikoerumanager-dark .subtitle-page .subtitle-info-card,
html.kikoerumanager-dark .subtitle-page .subtitle-candidate-card,
html.kikoerumanager-dark .subtitle-page .subtitle-list-card {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented-item,
html.kikoerumanager-dark .subtitle-page .subtitle-action-btn,
html.kikoerumanager-dark .subtitle-page .subtitle-mini-btn {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented-item.is-active,
html.kikoerumanager-dark .subtitle-page .subtitle-action-btn.is-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-list-title,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-title,
html.kikoerumanager-dark .subtitle-page .subtitle-info-card h3,
html.kikoerumanager-dark .subtitle-page .subtitle-list-card-title,
html.kikoerumanager-dark .subtitle-page .subtitle-meta-value,
html.kikoerumanager-dark .subtitle-page .lib-info-value {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-list-tip,
html.kikoerumanager-dark .subtitle-page .subtitle-list-card-source,
html.kikoerumanager-dark .subtitle-page .subtitle-list-card-meta,
html.kikoerumanager-dark .subtitle-page .subtitle-meta-label,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-subtitle,
html.kikoerumanager-dark .subtitle-page .lib-info-label,
html.kikoerumanager-dark .subtitle-page .lib-info-sub {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-list-card.is-active,
html.kikoerumanager-dark .subtitle-page .subtitle-candidate-card.is-selected {
  background: rgba(37, 99, 235, 0.24) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .el-dialog__body {
  background: transparent !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .import-workbench-modal,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-header {
  background: rgba(30, 41, 59, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-body {
  --tw-gradient-from: rgba(15, 23, 42, 0.96) var(--tw-gradient-from-position) !important;
  --tw-gradient-via: rgba(15, 23, 42, 0.94) var(--tw-gradient-via-position) !important;
  --tw-gradient-to: rgba(15, 23, 42, 0.92) var(--tw-gradient-to-position) !important;
  background-color: rgba(15, 23, 42, 0.94) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-white,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-white\/80,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-white\/70,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-white\/60,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50\/80,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50\/70,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50\/60,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50\/50,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-50\/40,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-100,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .bg-slate-100\/80 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-100,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200\/70,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200\/80 {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-900,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-800,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-700,
html.kikoerumanager-dark .subtitle-import-workbench-dialog h1,
html.kikoerumanager-dark .subtitle-import-workbench-dialog h2,
html.kikoerumanager-dark .subtitle-import-workbench-dialog h3 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-600,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-500,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .text-slate-400,
html.kikoerumanager-dark .subtitle-import-workbench-dialog p {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-btn,
html.kikoerumanager-dark .subtitle-import-workbench-dialog button:not(.primary-cta):not(.el-button--primary) {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-btn-close {
  background: linear-gradient(180deg, rgba(251, 113, 133, 0.24) 0%, rgba(127, 29, 29, 0.72) 100%) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog input,
html.kikoerumanager-dark .subtitle-import-workbench-dialog textarea,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .el-input__wrapper,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .el-textarea__inner {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .import-workbench-modal {
  background: rgba(15, 23, 42, 0.96) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-workbench-body,
html.kikoerumanager-dark .import-workbench-modal .bg-gradient-to-b {
  background: rgba(15, 23, 42, 0.94) !important;
  background-image: linear-gradient(180deg, rgba(15, 23, 42, 0.96) 0%, rgba(15, 23, 42, 0.94) 48%, rgba(15, 23, 42, 0.92) 100%) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal section,
html.kikoerumanager-dark .import-workbench-modal aside,
html.kikoerumanager-dark .import-workbench-modal article,
html.kikoerumanager-dark .import-workbench-modal .grid,
html.kikoerumanager-dark .import-workbench-modal .min-w-0,
html.kikoerumanager-dark .import-workbench-modal .min-h-0 {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .import-workbench-modal .rounded-\[20px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[18px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[14px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[12px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-xl {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .import-workbench-modal .bg-white,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/95,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/90,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/80,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/70,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/60,
html.kikoerumanager-dark .import-workbench-modal .bg-white\/50,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/90,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/80,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/70,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/60,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/50,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-50\/40,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-100,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-100\/90,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-100\/80,
html.kikoerumanager-dark .import-workbench-modal .bg-slate-100\/70 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .bg-slate-900,
html.kikoerumanager-dark .import-workbench-modal .is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .import-workbench-modal .text-slate-900,
html.kikoerumanager-dark .import-workbench-modal .text-slate-800,
html.kikoerumanager-dark .import-workbench-modal .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .import-workbench-modal .text-slate-600,
html.kikoerumanager-dark .import-workbench-modal .text-slate-500,
html.kikoerumanager-dark .import-workbench-modal .text-slate-400,
html.kikoerumanager-dark .import-workbench-modal .preview-empty,
html.kikoerumanager-dark .import-workbench-modal .empty-description {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .import-workbench-modal .border-slate-100,
html.kikoerumanager-dark .import-workbench-modal .border-slate-200,
html.kikoerumanager-dark .import-workbench-modal .border-slate-200\/70,
html.kikoerumanager-dark .import-workbench-modal .border-slate-200\/80,
html.kikoerumanager-dark .import-workbench-modal .border-slate-300 {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .import-workbench-modal .shadow-\[0_4px_16px_rgba\(15\,23\,42\,0\.04\)\],
html.kikoerumanager-dark .import-workbench-modal .shadow-\[0_20px_60px_rgba\(15\,23\,42\,0\.1\)\] {
  box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-config-card,
html.kikoerumanager-dark .import-workbench-modal .subtitle-option-stack,
html.kikoerumanager-dark .import-workbench-modal .subtitle-settings-block,
html.kikoerumanager-dark .import-workbench-modal .subtitle-setting-item,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-editor,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-detail,
html.kikoerumanager-dark .import-workbench-modal .search-row {
  background: rgba(30, 41, 59, 0.84) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 12px 26px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-help-card-danger {
  background: linear-gradient(180deg, rgba(127, 29, 29, 0.42) 0%, rgba(30, 41, 59, 0.86) 100%) !important;
  border-color: rgba(253, 164, 175, 0.28) !important;
}

html.kikoerumanager-dark .import-workbench-modal .header-badge {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .import-workbench-modal .header-badge-danger {
  background: rgba(127, 29, 29, 0.72) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-block-title,
html.kikoerumanager-dark .import-workbench-modal .subtitle-option-title,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-detail-title,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-summary-title,
html.kikoerumanager-dark .import-workbench-modal .stat-cell .text-slate-900 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-block-tip,
html.kikoerumanager-dark .import-workbench-modal .subtitle-card-tip,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-summary-pattern,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-empty,
html.kikoerumanager-dark .import-workbench-modal .search-chip,
html.kikoerumanager-dark .import-workbench-modal .stat-cell .text-slate-500 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .import-workbench-modal .stat-trio,
html.kikoerumanager-dark .import-workbench-modal .stat-cell {
  background: rgba(15, 23, 42, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-switch {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-target-badge,
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-white"],
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-slate-50"] {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option:hover,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill:hover,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row:hover,
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-white"]:hover:not(:disabled),
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-slate-50"]:hover:not(:disabled) {
  background: rgba(37, 99, 235, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option.active,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill.active,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row.active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-state {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.24) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-state.off {
  background: rgba(148, 163, 184, 0.12) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .password-vault {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .password-vault .vault-toolbar-panel,
html.kikoerumanager-dark .password-vault > section,
html.kikoerumanager-dark .password-vault .vault-mobile-card {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .password-vault h2,
html.kikoerumanager-dark .password-vault .text-slate-900,
html.kikoerumanager-dark .password-vault .text-slate-800,
html.kikoerumanager-dark .password-vault .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .password-vault p,
html.kikoerumanager-dark .password-vault .text-slate-600,
html.kikoerumanager-dark .password-vault .text-slate-500,
html.kikoerumanager-dark .password-vault .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .password-vault .bg-white,
html.kikoerumanager-dark .password-vault .bg-white\/90,
html.kikoerumanager-dark .password-vault .bg-white\/80,
html.kikoerumanager-dark .password-vault .bg-slate-50,
html.kikoerumanager-dark .password-vault .bg-slate-50\/70,
html.kikoerumanager-dark .password-vault .bg-slate-50\/50,
html.kikoerumanager-dark .password-vault .bg-slate-100 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .password-vault input,
html.kikoerumanager-dark .password-vault .el-input__wrapper,
html.kikoerumanager-dark .password-vault .el-textarea__inner {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .password-vault input::placeholder,
html.kikoerumanager-dark .password-vault textarea::placeholder {
  color: rgba(148, 163, 184, 0.62) !important;
}

html.kikoerumanager-dark .password-vault .vault-btn {
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .password-vault .vault-btn-ghost {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
}

html.kikoerumanager-dark .password-vault .vault-btn-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark .password-vault .vault-btn-danger {
  background: linear-gradient(180deg, rgba(251, 113, 133, 0.92) 0%, rgba(190, 18, 60, 0.96) 100%) !important;
  border-color: rgba(253, 164, 175, 0.42) !important;
  color: #fff1f2 !important;
}

html.kikoerumanager-dark .password-vault .vault-toolbar-divider {
  background: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .password-vault .password-table.el-table,
html.kikoerumanager-dark .password-vault .password-table .el-table__inner-wrapper,
html.kikoerumanager-dark .password-vault .password-table .el-table__body-wrapper,
html.kikoerumanager-dark .password-vault .password-table .el-table__header-wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .password-vault .password-table th.el-table__cell {
  background: rgba(15, 23, 42, 0.96) !important;
  border-bottom-color: rgba(148, 163, 184, 0.16) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .password-vault .password-table tr,
html.kikoerumanager-dark .password-vault .password-table td.el-table__cell {
  background: rgba(15, 23, 42, 0.88) !important;
  border-bottom-color: rgba(148, 163, 184, 0.12) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .password-vault .password-table .el-table__row--striped td.el-table__cell {
  background: rgba(30, 41, 59, 0.72) !important;
}

html.kikoerumanager-dark .password-vault .password-table .el-table__row:hover td.el-table__cell,
html.kikoerumanager-dark .password-vault .password-table .el-table__row.current-row td.el-table__cell {
  background: rgba(37, 99, 235, 0.22) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .password-vault .password-pill,
html.kikoerumanager-dark .password-vault .vault-mobile-password {
  background: rgba(226, 232, 240, 0.92) !important;
  color: #0f172a !important;
  border-color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .password-vault .el-tag {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .password-vault .el-checkbox__inner {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.36) !important;
}

html.kikoerumanager-dark .password-vault .el-checkbox__input.is-checked .el-checkbox__inner,
html.kikoerumanager-dark .password-vault .el-checkbox__input.is-indeterminate .el-checkbox__inner {
  background: #3b82f6 !important;
  border-color: #60a5fa !important;
}

html.kikoerumanager-dark .password-vault .el-pagination button,
html.kikoerumanager-dark .password-vault .el-pagination .el-pager li,
html.kikoerumanager-dark .password-vault .el-pagination .el-input__wrapper,
html.kikoerumanager-dark .password-vault .el-pagination .el-select__wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .password-vault .el-pagination .el-pager li.is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .vault-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .vault-dialog .el-dialog__header,
html.kikoerumanager-dark .vault-dialog .el-dialog__body {
  background: transparent !important;
}

html.kikoerumanager-dark .vault-dialog .vault-dialog-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 26px 66px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-dialog-header,
html.kikoerumanager-dark .vault-dialog .vault-dialog-footer {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-dialog-body {
  background: rgba(15, 23, 42, 0.92) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-dialog-note,
html.kikoerumanager-dark .vault-dialog .vault-cleanup-summary,
html.kikoerumanager-dark .vault-dialog .vault-cleanup-meta {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-cleanup-value,
html.kikoerumanager-dark .vault-dialog b,
html.kikoerumanager-dark .vault-dialog .text-slate-900,
html.kikoerumanager-dark .vault-dialog .text-slate-800,
html.kikoerumanager-dark .vault-dialog .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .vault-dialog .text-slate-600,
html.kikoerumanager-dark .vault-dialog .text-slate-500,
html.kikoerumanager-dark .vault-dialog .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .vault-dialog .el-form-item__label {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .vault-dialog .el-input__wrapper,
html.kikoerumanager-dark .vault-dialog .el-textarea__inner,
html.kikoerumanager-dark .vault-dialog input,
html.kikoerumanager-dark .vault-dialog textarea {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .vault-dialog .vault-icon-btn {
  background: rgba(15, 23, 42, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .password-vault .password-table .el-table__row.current-row td.el-table__cell,
html.kikoerumanager-dark .password-vault .password-table .el-table__row.is-selected td.el-table__cell,
html.kikoerumanager-dark .password-vault .password-table tr:hover > td.el-table__cell {
  background: rgba(30, 64, 175, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .password-vault .password-table .el-table__row--striped.current-row td.el-table__cell,
html.kikoerumanager-dark .password-vault .password-table .el-table__row--striped:hover td.el-table__cell {
  background: rgba(30, 64, 175, 0.34) !important;
}

html.kikoerumanager-dark .password-vault .password-pill,
html.kikoerumanager-dark .password-vault .vault-mobile-password {
  background: rgba(15, 23, 42, 0.78) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: #dbeafe !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .password-vault .password-pill:hover,
html.kikoerumanager-dark .password-vault .vault-mobile-password:hover {
  background: rgba(30, 41, 59, 0.92) !important;
  color: #eff6ff !important;
}

html.kikoerumanager-dark .password-vault .el-table__fixed-right,
html.kikoerumanager-dark .password-vault .el-table__fixed-right-patch,
html.kikoerumanager-dark .password-vault .el-table__fixed-right::before {
  background: rgba(15, 23, 42, 0.96) !important;
  box-shadow: -10px 0 22px rgba(0, 0, 0, 0.24) !important;
}

html.kikoerumanager-dark .password-vault .password-table button[title="编辑"] {
  background: rgba(37, 99, 235, 0.16) !important;
  border: 1px solid rgba(147, 197, 253, 0.22) !important;
  color: #93c5fd !important;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.16) !important;
}

html.kikoerumanager-dark .password-vault .password-table button[title="编辑"]:hover {
  background: rgba(37, 99, 235, 0.28) !important;
  border-color: rgba(147, 197, 253, 0.36) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .password-vault .password-table button[title="删除"] {
  background: rgba(190, 18, 60, 0.22) !important;
  border: 1px solid rgba(253, 164, 175, 0.24) !important;
  color: #fda4af !important;
  box-shadow: 0 8px 18px rgba(244, 63, 94, 0.16) !important;
}

html.kikoerumanager-dark .password-vault .password-table button[title="删除"]:hover {
  background: rgba(190, 18, 60, 0.36) !important;
  border-color: rgba(253, 164, 175, 0.4) !important;
  color: #ffe4e6 !important;
}

html.kikoerumanager-dark .vault-dialog .el-input,
html.kikoerumanager-dark .vault-dialog .el-textarea,
html.kikoerumanager-dark .vault-dialog .animated-password-input,
html.kikoerumanager-dark .vault-dialog .password-input-wrapper {
  background: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .vault-dialog .el-input__wrapper,
html.kikoerumanager-dark .vault-dialog .el-textarea__inner,
html.kikoerumanager-dark .vault-dialog input,
html.kikoerumanager-dark .vault-dialog textarea,
html.kikoerumanager-dark .vault-dialog .animated-password-input input {
  background: rgba(30, 41, 59, 0.92) !important;
  border: 1px solid rgba(148, 163, 184, 0.24) !important;
  color: var(--km-dark-text-strong) !important;
  caret-color: #93c5fd !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .vault-dialog .el-input__wrapper.is-focus,
html.kikoerumanager-dark .vault-dialog .el-textarea__inner:focus,
html.kikoerumanager-dark .vault-dialog input:focus,
html.kikoerumanager-dark .vault-dialog textarea:focus {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(147, 197, 253, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .vault-dialog input::placeholder,
html.kikoerumanager-dark .vault-dialog textarea::placeholder {
  color: rgba(148, 163, 184, 0.64) !important;
}

html.kikoerumanager-dark .vault-dialog .el-input__suffix,
html.kikoerumanager-dark .vault-dialog .el-input__suffix-inner,
html.kikoerumanager-dark .vault-dialog .el-icon {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .vault-dialog .grid.size-10,
html.kikoerumanager-dark .vault-dialog .grid.size-11 {
  background: rgba(37, 99, 235, 0.18) !important;
  border: 1px solid rgba(147, 197, 253, 0.24) !important;
  color: #93c5fd !important;
}

html.kikoerumanager-dark .vault-dialog .vault-dialog-note b {
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .password-vault .inline-flex.h-8,
html.kikoerumanager-dark .password-vault .inline-flex.h-7 {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input,
html.kikoerumanager-dark .vault-dialog .vault-form .el-input__wrapper,
html.kikoerumanager-dark .vault-dialog .vault-form .el-input__inner,
html.kikoerumanager-dark .vault-dialog .vault-form .el-textarea,
html.kikoerumanager-dark .vault-dialog .vault-form .el-textarea__inner {
  --el-input-bg-color: rgba(30, 41, 59, 0.94) !important;
  --el-input-border-color: rgba(148, 163, 184, 0.26) !important;
  --el-input-text-color: var(--km-dark-text-strong) !important;
  --el-input-placeholder-color: rgba(148, 163, 184, 0.64) !important;
  --el-input-hover-border-color: rgba(147, 197, 253, 0.38) !important;
  --el-input-focus-border-color: rgba(147, 197, 253, 0.55) !important;
  background-color: rgba(30, 41, 59, 0.94) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.26) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input__wrapper {
  border: 1px solid rgba(148, 163, 184, 0.26) !important;
  border-radius: 10px !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input__wrapper.is-focus {
  background-color: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(147, 197, 253, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input__inner {
  -webkit-text-fill-color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input__inner::placeholder,
html.kikoerumanager-dark .vault-dialog .vault-form .el-textarea__inner::placeholder {
  color: rgba(148, 163, 184, 0.64) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.64) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .animated-password-input,
html.kikoerumanager-dark .vault-dialog .vault-form .animated-password-input .el-input,
html.kikoerumanager-dark .vault-dialog .vault-form .animated-password-input .el-input__wrapper,
html.kikoerumanager-dark .vault-dialog .vault-form .animated-password-input .el-input__inner {
  background-color: rgba(30, 41, 59, 0.94) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .vault-dialog .vault-form .el-input__clear,
html.kikoerumanager-dark .vault-dialog .vault-form .el-input__password,
html.kikoerumanager-dark .vault-dialog .vault-form .el-input__suffix-inner svg {
  color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .existing-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-page .hero-search-wrap,
html.kikoerumanager-dark .existing-page .hero-search-input,
html.kikoerumanager-dark .existing-page .existing-shell,
html.kikoerumanager-dark .existing-page .sidebar-card,
html.kikoerumanager-dark .existing-page .ef-info-strip,
html.kikoerumanager-dark .existing-page .folders-card {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .existing-page .hero-search-input::placeholder {
  color: rgba(148, 163, 184, 0.62) !important;
}

html.kikoerumanager-dark .existing-page .sidebar-title,
html.kikoerumanager-dark .existing-page .pipeline-title,
html.kikoerumanager-dark .existing-page .option-row-title,
html.kikoerumanager-dark .existing-page .ef-info-value,
html.kikoerumanager-dark .existing-page .folder-name,
html.kikoerumanager-dark .existing-page .scan-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .existing-page .sidebar-overline,
html.kikoerumanager-dark .existing-page .pipeline-desc,
html.kikoerumanager-dark .existing-page .option-row-desc,
html.kikoerumanager-dark .existing-page .ef-info-label,
html.kikoerumanager-dark .existing-page .ef-info-meta,
html.kikoerumanager-dark .existing-page .folder-path,
html.kikoerumanager-dark .existing-page .folder-meta,
html.kikoerumanager-dark .existing-page .scan-desc {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .existing-page .pipeline-item,
html.kikoerumanager-dark .existing-page .option-row,
html.kikoerumanager-dark .existing-page .folder-card,
html.kikoerumanager-dark .existing-page .scan-banner {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-page .pipeline-item:hover,
html.kikoerumanager-dark .existing-page .option-row:hover,
html.kikoerumanager-dark .existing-page .folder-card:hover {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
}

html.kikoerumanager-dark .existing-page .folder-card.selected {
  background: rgba(37, 99, 235, 0.24) !important;
  border-color: rgba(147, 197, 253, 0.36) !important;
}

html.kikoerumanager-dark .existing-page .folder-card.conflict,
html.kikoerumanager-dark .existing-page .conflict-box {
  background: rgba(120, 53, 15, 0.32) !important;
  border-color: rgba(251, 191, 36, 0.26) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .existing-page .conflict-title {
  color: #fef3c7 !important;
}

html.kikoerumanager-dark .existing-page .conflict-desc {
  color: rgba(253, 230, 138, 0.72) !important;
}

html.kikoerumanager-dark .existing-page .sidebar-count,
html.kikoerumanager-dark .existing-page .folder-meta,
html.kikoerumanager-dark .existing-page .status-pill,
html.kikoerumanager-dark .existing-page .select-toggle {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-page .select-toggle.active {
  background: #3b82f6 !important;
  border-color: #60a5fa !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .existing-page .pipeline-dot.info,
html.kikoerumanager-dark .existing-page .ef-info-icon-blue {
  background: rgba(37, 99, 235, 0.18) !important;
  color: #93c5fd !important;
}

html.kikoerumanager-dark .existing-page .pipeline-dot.ok,
html.kikoerumanager-dark .existing-page .ef-info-icon-emerald {
  background: rgba(16, 185, 129, 0.16) !important;
  color: #6ee7b7 !important;
}

html.kikoerumanager-dark .existing-page .pipeline-dot.warn,
html.kikoerumanager-dark .existing-page .ef-info-icon-amber {
  background: rgba(245, 158, 11, 0.16) !important;
  color: #fcd34d !important;
}

html.kikoerumanager-dark .existing-page .pipeline-dot.done,
html.kikoerumanager-dark .existing-page .ef-info-icon-slate {
  background: rgba(148, 163, 184, 0.14) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .existing-page .ef-info-divider {
  background: rgba(148, 163, 184, 0.14) !important;
}

html.kikoerumanager-dark .existing-page .ef-head-btn,
html.kikoerumanager-dark .existing-page .side-ep-action,
html.kikoerumanager-dark .existing-page .card-action {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .existing-page .ef-head-btn.primary,
html.kikoerumanager-dark .existing-page .side-ep-action.primary,
html.kikoerumanager-dark .existing-page .card-action.primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .existing-page .card-action.warning {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.28) 0%, rgba(120, 53, 15, 0.72) 100%) !important;
  border-color: rgba(251, 191, 36, 0.3) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .existing-page .card-action.danger {
  background: linear-gradient(180deg, rgba(251, 113, 133, 0.28) 0%, rgba(127, 29, 29, 0.76) 100%) !important;
  border-color: rgba(253, 164, 175, 0.34) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .existing-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .existing-dialog .el-dialog__header,
html.kikoerumanager-dark .existing-dialog .el-dialog__body,
html.kikoerumanager-dark .existing-dialog .el-dialog__footer {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-dialog .dialog-header,
html.kikoerumanager-dark .existing-dialog .dialog-footer,
html.kikoerumanager-dark .existing-dialog .duplicate-panel,
html.kikoerumanager-dark .existing-dialog .detail-card,
html.kikoerumanager-dark .existing-dialog .task-row,
html.kikoerumanager-dark .existing-dialog .resolution-option {
  background: rgba(30, 41, 59, 0.84) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-dialog .dialog-title,
html.kikoerumanager-dark .existing-dialog .result-title,
html.kikoerumanager-dark .existing-dialog .task-list-title,
html.kikoerumanager-dark .existing-dialog .detail-title,
html.kikoerumanager-dark .existing-dialog .resolution-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .existing-dialog .dialog-subtitle,
html.kikoerumanager-dark .existing-dialog .result-message,
html.kikoerumanager-dark .existing-dialog .detail-line,
html.kikoerumanager-dark .existing-dialog .resolution-desc,
html.kikoerumanager-dark .existing-dialog .task-path {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .existing-dialog .resolution-option.active {
  background: rgba(37, 99, 235, 0.26) !important;
  border-color: rgba(147, 197, 253, 0.36) !important;
}

html.kikoerumanager-dark body:has(.existing-page),
html.kikoerumanager-dark .main-content:has(.existing-page),
html.kikoerumanager-dark .page-content:has(.existing-page),
html.kikoerumanager-dark .content-area:has(.existing-page) {
  background: var(--km-dark-bg) !important;
}

html.kikoerumanager-dark .existing-page {
  min-height: calc(100vh - 32px) !important;
  background: linear-gradient(180deg, rgba(7, 11, 18, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-radius: 18px !important;
  padding: 14px !important;
}

html.kikoerumanager-dark .existing-page .app-page-header,
html.kikoerumanager-dark .existing-page .app-page-header-inner,
html.kikoerumanager-dark .existing-page .app-page-header-actions {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .existing-page .hero-search-wrap {
  background: rgba(15, 23, 42, 0.96) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .existing-page .hero-search-input {
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .existing-page .existing-shell {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .existing-page .existing-sidebar,
html.kikoerumanager-dark .existing-page .existing-main {
  background: transparent !important;
}

html.kikoerumanager-dark .existing-page .sidebar-card,
html.kikoerumanager-dark .existing-page .folders-card,
html.kikoerumanager-dark .existing-page .ef-info-strip {
  background: rgba(15, 23, 42, 0.96) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
}

html.kikoerumanager-dark .existing-page .folders-card {
  min-height: 420px !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 18px 38px rgba(0, 0, 0, 0.28) !important;
}

html.kikoerumanager-dark .existing-page .app-empty-state,
html.kikoerumanager-dark .existing-page .empty-state,
html.kikoerumanager-dark .existing-page [class*="empty"] {
  background: transparent !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .existing-page .status-pill.success {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .existing-page .status-pill.warning {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .existing-page .status-pill.danger {
  background: rgba(190, 18, 60, 0.18) !important;
  border-color: rgba(253, 164, 175, 0.3) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .existing-page .status-pill.info {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .existing-page .status-pill.muted {
  background: rgba(148, 163, 184, 0.12) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .existing-page .side-ep-action.is-disabled,
html.kikoerumanager-dark .existing-page .card-action:disabled {
  background: rgba(30, 41, 59, 0.62) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.54) !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .asmr-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-info-strip,
html.kikoerumanager-dark .asmr-page .asmr-card,
html.kikoerumanager-dark .asmr-page .asmr-batch-toolbar,
html.kikoerumanager-dark .asmr-page .asmr-table-wrap {
  background: rgba(15, 23, 42, 0.94) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head,
html.kikoerumanager-dark .asmr-page .asmr-card-head-amber {
  background: rgba(30, 41, 59, 0.84) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-body {
  background: rgba(15, 23, 42, 0.92) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head-title h2,
html.kikoerumanager-dark .asmr-page .asmr-batch-toolbar-title,
html.kikoerumanager-dark .asmr-page .lib-info-value,
html.kikoerumanager-dark .asmr-page .text-slate-900,
html.kikoerumanager-dark .asmr-page .text-slate-800,
html.kikoerumanager-dark .asmr-page .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head-subtitle,
html.kikoerumanager-dark .asmr-page .asmr-card-head-count,
html.kikoerumanager-dark .asmr-page .lib-info-label,
html.kikoerumanager-dark .asmr-page .text-slate-600,
html.kikoerumanager-dark .asmr-page .text-slate-500,
html.kikoerumanager-dark .asmr-page .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head-icon,
html.kikoerumanager-dark .asmr-page .lib-info-icon {
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head-icon-amber {
  color: #fcd34d !important;
}

html.kikoerumanager-dark .asmr-page .lib-info-divider {
  background: rgba(148, 163, 184, 0.14) !important;
}

html.kikoerumanager-dark .asmr-page .page-head-btn,
html.kikoerumanager-dark .asmr-page .asmr-mini-btn,
html.kikoerumanager-dark .asmr-page .asmr-link-btn {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.18) 0%, rgba(30, 41, 59, 0.88) 100%) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .asmr-page .page-head-btn.primary,
html.kikoerumanager-dark .asmr-page .asmr-mini-btn.is-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-mini-btn.is-warning {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.28) 0%, rgba(120, 53, 15, 0.72) 100%) !important;
  border-color: rgba(251, 191, 36, 0.3) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .asmr-page .page-head-btn:disabled,
html.kikoerumanager-dark .asmr-page .asmr-mini-btn:disabled {
  background: rgba(30, 41, 59, 0.62) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.54) !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .asmr-page .el-input,
html.kikoerumanager-dark .asmr-page .el-input__wrapper,
html.kikoerumanager-dark .asmr-page .el-input__inner,
html.kikoerumanager-dark .asmr-page .el-textarea,
html.kikoerumanager-dark .asmr-page .el-textarea__inner {
  --el-input-bg-color: rgba(30, 41, 59, 0.94) !important;
  --el-input-border-color: rgba(148, 163, 184, 0.26) !important;
  --el-input-text-color: var(--km-dark-text-strong) !important;
  --el-input-placeholder-color: rgba(148, 163, 184, 0.64) !important;
  background-color: rgba(30, 41, 59, 0.94) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.26) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .asmr-page .el-input__wrapper,
html.kikoerumanager-dark .asmr-page .el-textarea__inner {
  border: 1px solid rgba(148, 163, 184, 0.26) !important;
}

html.kikoerumanager-dark .asmr-page .el-input__inner::placeholder,
html.kikoerumanager-dark .asmr-page .el-textarea__inner::placeholder {
  color: rgba(148, 163, 184, 0.64) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.64) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-amber {
  background: rgba(120, 53, 15, 0.22) !important;
  border-color: rgba(251, 191, 36, 0.24) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-list-row,
html.kikoerumanager-dark .asmr-page .asmr-task-card,
html.kikoerumanager-dark .asmr-page .enhanced-plan-card {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-rjcode,
html.kikoerumanager-dark .asmr-page .enhanced-plan-meta-pill,
html.kikoerumanager-dark .asmr-page .enhanced-plan-tag {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .asmr-page .asmr-table-wrap .el-table,
html.kikoerumanager-dark .asmr-page .asmr-table-wrap .el-table__inner-wrapper,
html.kikoerumanager-dark .asmr-page .asmr-table-wrap .el-table__body-wrapper,
html.kikoerumanager-dark .asmr-page .asmr-table-wrap .el-table__header-wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-table-wrap th.el-table__cell {
  background: rgba(15, 23, 42, 0.96) !important;
  border-bottom-color: rgba(148, 163, 184, 0.16) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-table-wrap td.el-table__cell {
  background: rgba(15, 23, 42, 0.88) !important;
  border-bottom-color: rgba(148, 163, 184, 0.12) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-table-wrap .el-table__row:hover td.el-table__cell {
  background: rgba(37, 99, 235, 0.2) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .asmr-page .asmr-card-head-checkbox {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .circle-page .hero-search-wrap,
html.kikoerumanager-dark .circle-page .hero-search-input,
html.kikoerumanager-dark .circle-page .circle-shell,
html.kikoerumanager-dark .circle-page .sidebar-card,
html.kikoerumanager-dark .circle-page .toolbar-card,
html.kikoerumanager-dark .circle-page .works-card,
html.kikoerumanager-dark .circle-page .circle-tabs-wrapper,
html.kikoerumanager-dark .circle-page .owned-stats-strip,
html.kikoerumanager-dark .circle-page .owned-filter-tabs {
  background: rgba(15, 23, 42, 0.94) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .circle-page .circle-shell {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-page .circle-sidebar,
html.kikoerumanager-dark .circle-page .circle-main {
  background: transparent !important;
}

html.kikoerumanager-dark .circle-page .sidebar-title,
html.kikoerumanager-dark .circle-page .toolbar-title,
html.kikoerumanager-dark .circle-page .circle-list-name,
html.kikoerumanager-dark .circle-page .text-slate-900,
html.kikoerumanager-dark .circle-page .text-slate-800,
html.kikoerumanager-dark .circle-page .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .circle-page .sidebar-overline,
html.kikoerumanager-dark .circle-page .toolbar-subtitle,
html.kikoerumanager-dark .circle-page .toolbar-subtext,
html.kikoerumanager-dark .circle-page .circle-list-id,
html.kikoerumanager-dark .circle-page .sidebar-sort-label,
html.kikoerumanager-dark .circle-page .text-slate-600,
html.kikoerumanager-dark .circle-page .text-slate-500,
html.kikoerumanager-dark .circle-page .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page .el-input,
html.kikoerumanager-dark .circle-page .el-input__wrapper,
html.kikoerumanager-dark .circle-page .el-input__inner,
html.kikoerumanager-dark .circle-page .owned-search-wrap input {
  --el-input-bg-color: rgba(30, 41, 59, 0.94) !important;
  --el-input-border-color: rgba(148, 163, 184, 0.26) !important;
  --el-input-text-color: var(--km-dark-text-strong) !important;
  --el-input-placeholder-color: rgba(148, 163, 184, 0.64) !important;
  background-color: rgba(30, 41, 59, 0.94) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.26) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-page .hero-search-input {
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-page .circle-list-item,
html.kikoerumanager-dark .circle-page .sidebar-filter-chip,
html.kikoerumanager-dark .circle-page .owned-filter-tabs button,
html.kikoerumanager-dark .circle-page .release-sort-button,
html.kikoerumanager-dark .circle-page .view-toggle-btn,
html.kikoerumanager-dark .circle-page .batch-action-button,
html.kikoerumanager-dark .circle-page .toolbar-right-actions button {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .circle-page .circle-list-item:hover,
html.kikoerumanager-dark .circle-page .sidebar-filter-chip:hover,
html.kikoerumanager-dark .circle-page .owned-filter-tabs button:hover,
html.kikoerumanager-dark .circle-page .release-sort-button:hover,
html.kikoerumanager-dark .circle-page .view-toggle-btn:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.3) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .circle-page .circle-list-item.active,
html.kikoerumanager-dark .circle-page .sidebar-filter-chip.active,
html.kikoerumanager-dark .circle-page .view-toggle-btn.active,
html.kikoerumanager-dark .circle-page .owned-filter-tabs button[class*="text-white"] {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.36) 0%, rgba(30, 41, 59, 0.96) 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-page .circle-list-item.active {
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .circle-page .circle-list-progress-track {
  background: rgba(15, 23, 42, 0.86) !important;
}

html.kikoerumanager-dark .circle-page .circle-list-progress-fill {
  background: linear-gradient(90deg, #60a5fa 0%, #34d399 100%) !important;
}

html.kikoerumanager-dark .circle-page .circle-stat-item,
html.kikoerumanager-dark .circle-page .circle-list-status-pill,
html.kikoerumanager-dark .circle-page .circle-list-tag,
html.kikoerumanager-dark .circle-page .metric-pill,
html.kikoerumanager-dark .circle-page .circle-inline-new-badge,
html.kikoerumanager-dark .circle-page .circle-tab-badge {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .circle-page .metric-pill.warn,
html.kikoerumanager-dark .circle-page .circle-stat-item.missing {
  background: rgba(190, 18, 60, 0.18) !important;
  border-color: rgba(253, 164, 175, 0.3) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .circle-page .metric-pill.ok,
html.kikoerumanager-dark .circle-page .circle-stat-item.owned,
html.kikoerumanager-dark .circle-page .circle-list-status-pill.completed {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .circle-page .metric-pill.unreleased,
html.kikoerumanager-dark .circle-page .circle-list-tag.unreleased {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .circle-page .el-tabs__nav-wrap::after,
html.kikoerumanager-dark .circle-page .el-tabs__active-bar {
  background: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .circle-page .el-tabs__item {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page .el-tabs__item.is-active {
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .circle-page .work-card,
html.kikoerumanager-dark .circle-page .work-list-row,
html.kikoerumanager-dark .circle-page .owned-panel,
html.kikoerumanager-dark .circle-page .compare-panel,
html.kikoerumanager-dark .circle-page .index-progress-card,
html.kikoerumanager-dark .circle-page .bg-white,
html.kikoerumanager-dark .circle-page .bg-white\/50,
html.kikoerumanager-dark .circle-page .bg-slate-50,
html.kikoerumanager-dark .circle-page .bg-slate-100 {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .circle-page .work-card:hover,
html.kikoerumanager-dark .circle-page .work-list-row:hover,
html.kikoerumanager-dark .circle-page .work-card.is-selected,
html.kikoerumanager-dark .circle-page .work-list-row.is-selected {
  background: rgba(37, 99, 235, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .circle-page .wlr-title,
html.kikoerumanager-dark .circle-page .wlr-title-text,
html.kikoerumanager-dark .circle-page .work-title,
html.kikoerumanager-dark .circle-page .card-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .circle-page .wlr-subtitle,
html.kikoerumanager-dark .circle-page .wlr-cv,
html.kikoerumanager-dark .circle-page .work-subtitle,
html.kikoerumanager-dark .circle-page .card-subtitle {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page .wlr-code,
html.kikoerumanager-dark .circle-page .wlr-variant,
html.kikoerumanager-dark .circle-page .wlr-linked-code,
html.kikoerumanager-dark .circle-page .wlr-pill,
html.kikoerumanager-dark .circle-page .wlr-btn {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .circle-page .works-pager .el-pagination button,
html.kikoerumanager-dark .circle-page .works-pager .el-pagination .el-pager li,
html.kikoerumanager-dark .circle-page .works-pager .el-pagination .el-input__wrapper,
html.kikoerumanager-dark .circle-page .works-pager .el-pagination .el-select__wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-page .works-pager .el-pagination .el-pager li.is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .custom-preview-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .custom-preview-modal .window,
html.kikoerumanager-dark .custom-preview-modal .glass-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .custom-preview-modal .window-header,
html.kikoerumanager-dark .custom-preview-modal .tabs-row,
html.kikoerumanager-dark .custom-preview-modal .footer-row {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .custom-preview-modal .glass-card,
html.kikoerumanager-dark .custom-preview-modal .mode-switch,
html.kikoerumanager-dark .custom-preview-modal .content-grid,
html.kikoerumanager-dark .custom-preview-modal .left-column,
html.kikoerumanager-dark .custom-preview-modal .dropdown-panel,
html.kikoerumanager-dark .custom-preview-modal .resource-row,
html.kikoerumanager-dark .custom-preview-modal .preview-card {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal .title,
html.kikoerumanager-dark .custom-preview-modal h1,
html.kikoerumanager-dark .custom-preview-modal h2,
html.kikoerumanager-dark .custom-preview-modal label,
html.kikoerumanager-dark .custom-preview-modal .text-slate-900,
html.kikoerumanager-dark .custom-preview-modal .text-slate-800 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal p,
html.kikoerumanager-dark .custom-preview-modal .text-slate-600,
html.kikoerumanager-dark .custom-preview-modal .text-slate-500,
html.kikoerumanager-dark .custom-preview-modal .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .custom-preview-modal .field-input,
html.kikoerumanager-dark .custom-preview-modal .select-button,
html.kikoerumanager-dark .custom-preview-modal input {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark body:has(.circle-page),
html.kikoerumanager-dark .main-content:has(.circle-page),
html.kikoerumanager-dark .page-content:has(.circle-page),
html.kikoerumanager-dark .content-area:has(.circle-page) {
  background: var(--km-dark-bg) !important;
}

html.kikoerumanager-dark .circle-page {
  min-height: calc(100vh - 32px) !important;
  background: linear-gradient(180deg, rgba(7, 11, 18, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-radius: 18px !important;
  padding: 14px !important;
}

html.kikoerumanager-dark .circle-page .circle-page-header,
html.kikoerumanager-dark .circle-page .app-page-header,
html.kikoerumanager-dark .circle-page .app-page-header-inner,
html.kikoerumanager-dark .circle-page .app-page-header-actions {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .circle-page .work-card,
html.kikoerumanager-dark .circle-page .work-card.is-downloaded,
html.kikoerumanager-dark .circle-page .work-card.is-unreleased,
html.kikoerumanager-dark .circle-page .work-card.disabled {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.92) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .circle-page .work-card:hover,
html.kikoerumanager-dark .circle-page .work-card.is-downloaded:hover,
html.kikoerumanager-dark .circle-page .work-card.is-unreleased:hover {
  background: linear-gradient(180deg, rgba(30, 64, 175, 0.24) 0%, rgba(15, 23, 42, 0.96) 100%) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28), 0 0 0 1px rgba(147, 197, 253, 0.12) !important;
}

html.kikoerumanager-dark .circle-page .work-card.selected,
html.kikoerumanager-dark .circle-page .work-card.selected:hover {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(15, 23, 42, 0.96) 100%) !important;
  border-color: rgba(147, 197, 253, 0.48) !important;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2), 0 18px 36px rgba(0, 0, 0, 0.32) !important;
}

html.kikoerumanager-dark .circle-page .work-card.status-flash {
  background: linear-gradient(180deg, rgba(16, 185, 129, 0.22) 0%, rgba(15, 23, 42, 0.96) 100%) !important;
  border-color: rgba(110, 231, 183, 0.4) !important;
}

html.kikoerumanager-dark .circle-page .work-cover-wrapper,
html.kikoerumanager-dark .circle-page .work-cover-placeholder,
html.kikoerumanager-dark .circle-page .wlr-thumb-placeholder {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page .work-cover-shine {
  background: linear-gradient(115deg, transparent 40%, rgba(147, 197, 253, 0.16) 50%, transparent 60%) !important;
}

html.kikoerumanager-dark .circle-page .work-rj,
html.kikoerumanager-dark .circle-page .work-card:hover .work-rj {
  color: #93c5fd !important;
}

html.kikoerumanager-dark .circle-page .work-title,
html.kikoerumanager-dark .circle-page .work-card:hover .work-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .circle-page .work-linked,
html.kikoerumanager-dark .circle-page .work-card.disabled .work-rj,
html.kikoerumanager-dark .circle-page .work-card.disabled .work-title,
html.kikoerumanager-dark .circle-page .work-card.disabled .work-linked {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .circle-page .work-cv {
  color: #7dd3fc !important;
}

html.kikoerumanager-dark .circle-page .tag-chip.is-primary,
html.kikoerumanager-dark .circle-page .work-release-chip,
html.kikoerumanager-dark .circle-page .work-unreleased-flag {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .circle-page .tag-chip.is-success {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .circle-page .tag-chip.is-danger {
  background: rgba(190, 18, 60, 0.18) !important;
  border-color: rgba(253, 164, 175, 0.3) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .circle-page .tag-chip.is-warning,
html.kikoerumanager-dark .circle-page .work-new-flag,
html.kikoerumanager-dark .circle-page .work-new-badge {
  background: rgba(245, 158, 11, 0.2) !important;
  border-color: rgba(251, 191, 36, 0.3) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .circle-page .tag-chip.is-info,
html.kikoerumanager-dark .circle-page .tag-chip.is-disabled {
  background: rgba(148, 163, 184, 0.12) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .circle-page .work-action-btn {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .circle-page .work-action-btn:hover {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-page .work-action-btn.upload {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .circle-page .work-action-btn.upload:hover {
  background: linear-gradient(180deg, #34d399 0%, #059669 100%) !important;
  border-color: rgba(110, 231, 183, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .circle-page .work-list-row {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
}

html.kikoerumanager-dark .circle-page .work-list-row:hover,
html.kikoerumanager-dark .circle-page .work-list-row.is-selected {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .circle-page .owned-search-wrap input::placeholder,
html.kikoerumanager-dark .circle-page .hero-search-input::placeholder,
html.kikoerumanager-dark .circle-page .el-input__inner::placeholder {
  color: rgba(148, 163, 184, 0.64) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.64) !important;
}

html.kikoerumanager-dark .circle-page .el-pagination .el-select .el-input,
html.kikoerumanager-dark .circle-page .el-pagination .el-select__wrapper,
html.kikoerumanager-dark .circle-page .el-pagination__jump .el-input__wrapper {
  background: rgba(15, 23, 42, 0.94) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .settings-workbench,
html.kikoerumanager-dark .settings-page .settings-main,
html.kikoerumanager-dark .settings-page .main-slot {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .sidebar-shell,
html.kikoerumanager-dark .settings-page .settings-section-panel,
html.kikoerumanager-dark .settings-page .settings-card,
html.kikoerumanager-dark .settings-page .setting-card,
html.kikoerumanager-dark .settings-page .config-card,
html.kikoerumanager-dark .settings-page .panel-card,
html.kikoerumanager-dark .settings-page .library-card,
html.kikoerumanager-dark .settings-page .profile-card {
  background: rgba(15, 23, 42, 0.94) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .settings-page .settings-search,
html.kikoerumanager-dark .settings-page .sidebar-footer,
html.kikoerumanager-dark .settings-page .sidebar-footer-meta {
  background: rgba(30, 41, 59, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .settings-search input {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .settings-search input::placeholder {
  color: rgba(148, 163, 184, 0.68) !important;
}

html.kikoerumanager-dark .settings-page .nav-item {
  background: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.12) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .nav-item:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
}

html.kikoerumanager-dark .settings-page .nav-item.active {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 41, 59, 0.92) 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .settings-page .nav-item-title,
html.kikoerumanager-dark .settings-page .panel-title,
html.kikoerumanager-dark .settings-page h1,
html.kikoerumanager-dark .settings-page h2,
html.kikoerumanager-dark .settings-page h3,
html.kikoerumanager-dark .settings-page h4,
html.kikoerumanager-dark .settings-page .section-title,
html.kikoerumanager-dark .settings-page .setting-title,
html.kikoerumanager-dark .settings-page .field-title,
html.kikoerumanager-dark .settings-page .card-title,
html.kikoerumanager-dark .settings-page .text-slate-900,
html.kikoerumanager-dark .settings-page .text-slate-800,
html.kikoerumanager-dark .settings-page .text-slate-700 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .nav-item-desc,
html.kikoerumanager-dark .settings-page .panel-kicker,
html.kikoerumanager-dark .settings-page .panel-desc,
html.kikoerumanager-dark .settings-page .sidebar-footer-label,
html.kikoerumanager-dark .settings-page .sidebar-footer-value,
html.kikoerumanager-dark .settings-page .section-desc,
html.kikoerumanager-dark .settings-page .setting-desc,
html.kikoerumanager-dark .settings-page .field-desc,
html.kikoerumanager-dark .settings-page .help-text,
html.kikoerumanager-dark .settings-page .hint-text,
html.kikoerumanager-dark .settings-page .text-slate-600,
html.kikoerumanager-dark .settings-page .text-slate-500,
html.kikoerumanager-dark .settings-page .text-slate-400,
html.kikoerumanager-dark .settings-page p,
html.kikoerumanager-dark .settings-page small {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .settings-page .nav-item-icon {
  background: rgba(15, 23, 42, 0.86) !important;
  border: 1px solid rgba(147, 197, 253, 0.18) !important;
  color: #93c5fd !important;
}

html.kikoerumanager-dark .settings-page .nav-item-storage .nav-item-icon,
html.kikoerumanager-dark .settings-page .nav-item-notification .nav-item-icon {
  color: #93c5fd !important;
}

html.kikoerumanager-dark .settings-page .nav-item-processing .nav-item-icon {
  color: #c4b5fd !important;
}

html.kikoerumanager-dark .settings-page .nav-item-rules .nav-item-icon {
  color: #fcd34d !important;
}

html.kikoerumanager-dark .settings-page .nav-item-services .nav-item-icon {
  color: #6ee7b7 !important;
}

html.kikoerumanager-dark .settings-page .nav-item-maintenance .nav-item-icon {
  color: #fda4af !important;
}

html.kikoerumanager-dark .settings-page svg {
  color: currentColor;
}

html.kikoerumanager-dark .settings-page label,
html.kikoerumanager-dark .settings-page .el-form-item__label,
html.kikoerumanager-dark .settings-page .form-label,
html.kikoerumanager-dark .settings-page .field-label {
  color: rgba(226, 232, 240, 0.86) !important;
}

html.kikoerumanager-dark .settings-page input,
html.kikoerumanager-dark .settings-page textarea,
html.kikoerumanager-dark .settings-page select,
html.kikoerumanager-dark .settings-page .el-input__wrapper,
html.kikoerumanager-dark .settings-page .el-input__inner,
html.kikoerumanager-dark .settings-page .el-textarea__inner,
html.kikoerumanager-dark .settings-page .el-select__wrapper,
html.kikoerumanager-dark .settings-page .el-input-number,
html.kikoerumanager-dark .settings-page .el-input-number__decrease,
html.kikoerumanager-dark .settings-page .el-input-number__increase {
  --el-input-bg-color: rgba(30, 41, 59, 0.94) !important;
  --el-input-border-color: rgba(148, 163, 184, 0.26) !important;
  --el-input-text-color: var(--km-dark-text-strong) !important;
  --el-input-placeholder-color: rgba(148, 163, 184, 0.66) !important;
  background-color: rgba(30, 41, 59, 0.94) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.26) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page input::placeholder,
html.kikoerumanager-dark .settings-page textarea::placeholder {
  color: rgba(148, 163, 184, 0.66) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.66) !important;
}

html.kikoerumanager-dark .settings-page .el-input__wrapper.is-focus,
html.kikoerumanager-dark .settings-page .el-select__wrapper.is-focused,
html.kikoerumanager-dark .settings-page input:focus,
html.kikoerumanager-dark .settings-page textarea:focus {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(147, 197, 253, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
}

html.kikoerumanager-dark .settings-page .set-chip-success {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.28) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .settings-page .set-chip-warning {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .settings-page .set-chip-info,
html.kikoerumanager-dark .settings-page .nav-badge {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .sidebar-ghost-btn,
html.kikoerumanager-dark .settings-page button:not(.el-switch__core) {
  border-color: rgba(96, 165, 250, 0.24) !important;
}

html.kikoerumanager-dark .settings-page .sidebar-ghost-btn,
html.kikoerumanager-dark .settings-page .save-bar-btn-ghost {
  background: rgba(15, 23, 42, 0.82) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .save-bar {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.42) !important;
}

html.kikoerumanager-dark .settings-page .save-bar-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .save-bar-desc {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .settings-page .save-bar-btn-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .settings-page .storage-stack,
html.kikoerumanager-dark .settings-page .storage-card,
html.kikoerumanager-dark .settings-page .storage-card-head,
html.kikoerumanager-dark .settings-page .inventory-panel,
html.kikoerumanager-dark .settings-page .inventory-list,
html.kikoerumanager-dark .settings-page .inventory-editor {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .storage-card-title,
html.kikoerumanager-dark .settings-page .library-title,
html.kikoerumanager-dark .settings-page .editor-title {
  color: var(--km-dark-text-strong) !important;
  text-shadow: 0 1px 16px rgba(147, 197, 253, 0.12) !important;
}

html.kikoerumanager-dark .settings-page .storage-card-desc,
html.kikoerumanager-dark .settings-page .library-sub,
html.kikoerumanager-dark .settings-page .library-meta,
html.kikoerumanager-dark .settings-page .editor-desc {
  color: rgba(203, 213, 225, 0.78) !important;
}

html.kikoerumanager-dark .settings-page .library-card,
html.kikoerumanager-dark .settings-page .library-card.remote,
html.kikoerumanager-dark .settings-page .create-btn,
html.kikoerumanager-dark .settings-page .field-card,
html.kikoerumanager-dark .settings-page .settings-field-card,
html.kikoerumanager-dark .settings-page .toggle-row,
html.kikoerumanager-dark .settings-page .library-summary {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .library-card:hover,
html.kikoerumanager-dark .settings-page .create-btn:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.32) !important;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .settings-page .library-card.active,
html.kikoerumanager-dark .settings-page .library-card.remote.active {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.34) 0%, rgba(30, 41, 59, 0.94) 100%) !important;
  border-color: rgba(147, 197, 253, 0.44) !important;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .settings-page .library-type-pill,
html.kikoerumanager-dark .settings-page .summary-pill {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .library-card.remote .library-type-pill {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .settings-page .storage-field-input,
html.kikoerumanager-dark .settings-page .lib-input,
html.kikoerumanager-dark .settings-page .settings-field-dd .app-dd-trigger {
  background: rgba(30, 41, 59, 0.94) !important;
  border-color: rgba(148, 163, 184, 0.26) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .storage-field-input:hover,
html.kikoerumanager-dark .settings-page .lib-input:hover,
html.kikoerumanager-dark .settings-page .settings-field-dd .app-dd-trigger:hover {
  border-color: rgba(147, 197, 253, 0.38) !important;
}

html.kikoerumanager-dark .settings-page .storage-field-input:focus,
html.kikoerumanager-dark .settings-page .lib-input:focus {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(147, 197, 253, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
}

html.kikoerumanager-dark .settings-page .storage-field-input::placeholder,
html.kikoerumanager-dark .settings-page .lib-input::placeholder {
  color: rgba(148, 163, 184, 0.66) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.66) !important;
}

html.kikoerumanager-dark .settings-page .create-btn {
  text-align: center !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .create-btn.warn {
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .settings-page .ghost-btn,
html.kikoerumanager-dark .settings-page .primary-btn,
html.kikoerumanager-dark .settings-page .link-btn {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: var(--km-dark-blue) !important;
}

html.kikoerumanager-dark .settings-page .primary-btn {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .settings-page .ghost-btn.danger {
  background: rgba(190, 18, 60, 0.18) !important;
  border-color: rgba(253, 164, 175, 0.3) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .settings-page .inline-tip.warn {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .settings-page .bg-white,
html.kikoerumanager-dark .settings-page .bg-white\/50,
html.kikoerumanager-dark .settings-page .bg-white\/55,
html.kikoerumanager-dark .settings-page .bg-white\/60,
html.kikoerumanager-dark .settings-page .bg-white\/70,
html.kikoerumanager-dark .settings-page .bg-white\/80,
html.kikoerumanager-dark .settings-page .bg-slate-50,
html.kikoerumanager-dark .settings-page .bg-slate-100,
html.kikoerumanager-dark .settings-page [class*="bg-white"],
html.kikoerumanager-dark .settings-page [class*="from-white"],
html.kikoerumanager-dark .settings-page [class*="to-white"],
html.kikoerumanager-dark .settings-page [class*="from-slate-50"],
html.kikoerumanager-dark .settings-page [class*="to-slate-50"] {
  background-color: rgba(30, 41, 59, 0.84) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page [class*="border-slate"],
html.kikoerumanager-dark .settings-page [class*="divide-slate"] > :not([hidden]) ~ :not([hidden]) {
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .settings-page [class*="text-slate-900"],
html.kikoerumanager-dark .settings-page [class*="text-slate-800"],
html.kikoerumanager-dark .settings-page [class*="text-slate-700"] {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page [class*="text-slate-600"],
html.kikoerumanager-dark .settings-page [class*="text-slate-500"],
html.kikoerumanager-dark .settings-page [class*="text-slate-400"] {
  color: rgba(203, 213, 225, 0.76) !important;
}

html.kikoerumanager-dark .settings-page .settings-grid,
html.kikoerumanager-dark .settings-page .mini-grid,
html.kikoerumanager-dark .settings-page .field-stack,
html.kikoerumanager-dark .settings-page .field-grid,
html.kikoerumanager-dark .settings-page .form-grid {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .settings-card,
html.kikoerumanager-dark .settings-page .notification-card,
html.kikoerumanager-dark .settings-page .template-card,
html.kikoerumanager-dark .settings-page .rule-card,
html.kikoerumanager-dark .settings-page .rule-row,
html.kikoerumanager-dark .settings-page .filter-rule-row,
html.kikoerumanager-dark .settings-page .mapping-row,
html.kikoerumanager-dark .settings-page .step-card,
html.kikoerumanager-dark .settings-page .cleanup-card,
html.kikoerumanager-dark .settings-page .stat-card,
html.kikoerumanager-dark .settings-page .profile-panel,
html.kikoerumanager-dark .settings-page .profile-header,
html.kikoerumanager-dark .settings-page .profile-status-strip,
html.kikoerumanager-dark .settings-page .toggle-card,
html.kikoerumanager-dark .settings-page .toggle-row,
html.kikoerumanager-dark .settings-page .settings-toggle-row {
  background: rgba(30, 41, 59, 0.84) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 10px 24px rgba(0, 0, 0, 0.18) !important;
}

html.kikoerumanager-dark .settings-page .settings-card:hover,
html.kikoerumanager-dark .settings-page .template-card:hover,
html.kikoerumanager-dark .settings-page .rule-row:hover,
html.kikoerumanager-dark .settings-page .mapping-row:hover,
html.kikoerumanager-dark .settings-page .toggle-card:hover,
html.kikoerumanager-dark .settings-page .settings-toggle-row:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.3) !important;
}

html.kikoerumanager-dark .settings-page .card-title,
html.kikoerumanager-dark .settings-page .profile-title,
html.kikoerumanager-dark .settings-page .template-title,
html.kikoerumanager-dark .settings-page .rule-title,
html.kikoerumanager-dark .settings-page .toggle-title,
html.kikoerumanager-dark .settings-page .stat-title,
html.kikoerumanager-dark .settings-page .section-head h2 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .card-desc,
html.kikoerumanager-dark .settings-page .profile-desc,
html.kikoerumanager-dark .settings-page .template-desc,
html.kikoerumanager-dark .settings-page .rule-desc,
html.kikoerumanager-dark .settings-page .toggle-subtitle,
html.kikoerumanager-dark .settings-page .stat-desc,
html.kikoerumanager-dark .settings-page .section-head p {
  color: rgba(203, 213, 225, 0.76) !important;
}

html.kikoerumanager-dark .settings-page .status-chip,
html.kikoerumanager-dark .settings-page .template-chip,
html.kikoerumanager-dark .settings-page .type-chip,
html.kikoerumanager-dark .settings-page .rule-chip,
html.kikoerumanager-dark .settings-page .preset-chip,
html.kikoerumanager-dark .settings-page .pill,
html.kikoerumanager-dark .settings-page .badge {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .status-chip.is-good,
html.kikoerumanager-dark .settings-page .pill-success,
html.kikoerumanager-dark .settings-page .badge-success {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.26) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .settings-page .status-chip.is-warn,
html.kikoerumanager-dark .settings-page .pill-warning,
html.kikoerumanager-dark .settings-page .badge-warning {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .settings-page .preset-button,
html.kikoerumanager-dark .settings-page .provider-button,
html.kikoerumanager-dark .settings-page .add-rule-btn,
html.kikoerumanager-dark .settings-page .add-button,
html.kikoerumanager-dark .settings-page .icon-btn,
html.kikoerumanager-dark .settings-page .mini-btn,
html.kikoerumanager-dark .settings-page .action-btn,
html.kikoerumanager-dark .settings-page .test-btn {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .preset-button:hover,
html.kikoerumanager-dark .settings-page .provider-button:hover,
html.kikoerumanager-dark .settings-page .add-rule-btn:hover,
html.kikoerumanager-dark .settings-page .add-button:hover,
html.kikoerumanager-dark .settings-page .icon-btn:hover,
html.kikoerumanager-dark .settings-page .mini-btn:hover,
html.kikoerumanager-dark .settings-page .action-btn:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .delete-btn,
html.kikoerumanager-dark .settings-page .remove-btn,
html.kikoerumanager-dark .settings-page .danger-btn,
html.kikoerumanager-dark .settings-page button[aria-label*="删除"],
html.kikoerumanager-dark .settings-page button[title*="删除"] {
  background: rgba(190, 18, 60, 0.16) !important;
  border-color: rgba(253, 164, 175, 0.28) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .settings-page .el-switch__core {
  border-color: rgba(148, 163, 184, 0.28) !important;
}

html.kikoerumanager-dark .settings-page .el-slider__runway {
  background: rgba(30, 41, 59, 0.96) !important;
}

html.kikoerumanager-dark .settings-page .el-slider__bar {
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%) !important;
}

html.kikoerumanager-dark .settings-page .el-slider__button {
  border-color: #93c5fd !important;
  background: #f8fafc !important;
}

html.kikoerumanager-dark .settings-page .str,
html.kikoerumanager-dark .settings-page .rule-row,
html.kikoerumanager-dark .settings-page .classification-row {
  background: rgba(30, 41, 59, 0.86) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  border-radius: 12px !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .str {
  padding: 12px 14px !important;
}

html.kikoerumanager-dark .settings-page .str:hover,
html.kikoerumanager-dark .settings-page .rule-row:hover,
html.kikoerumanager-dark .settings-page .classification-row:hover {
  background: rgba(37, 99, 235, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .settings-page .str-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .str-subtitle {
  color: rgba(203, 213, 225, 0.76) !important;
}

html.kikoerumanager-dark .settings-page .field-input,
html.kikoerumanager-dark .settings-page .profile-input {
  background: rgba(15, 23, 42, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.24) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .field-input:hover,
html.kikoerumanager-dark .settings-page .profile-input:hover {
  border-color: rgba(147, 197, 253, 0.38) !important;
}

html.kikoerumanager-dark .settings-page .field-input:focus,
html.kikoerumanager-dark .settings-page .profile-input:focus {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(147, 197, 253, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18) !important;
}

html.kikoerumanager-dark .settings-page .field-input::placeholder,
html.kikoerumanager-dark .settings-page .profile-input::placeholder {
  color: rgba(148, 163, 184, 0.66) !important;
  -webkit-text-fill-color: rgba(148, 163, 184, 0.66) !important;
}

html.kikoerumanager-dark .settings-page .ghost-inline-btn {
  width: 100% !important;
  min-height: 38px !important;
  border-radius: 10px !important;
  background: rgba(37, 99, 235, 0.16) !important;
  border: 1px solid rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .ghost-inline-btn:hover {
  background: rgba(37, 99, 235, 0.26) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #eff6ff !important;
}

html.kikoerumanager-dark .settings-page .rule-target .app-dd-trigger,
html.kikoerumanager-dark .settings-page .app-dd-trigger {
  background: rgba(37, 99, 235, 0.14) !important;
  background-image: none !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .rule-target .app-dd-trigger:hover,
html.kikoerumanager-dark .settings-page .app-dd-trigger:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.38) !important;
}

html.kikoerumanager-dark .settings-page .icon-btn.danger,
html.kikoerumanager-dark .settings-page .icon-btn.danger:hover {
  background: rgba(190, 18, 60, 0.16) !important;
  border-color: rgba(253, 164, 175, 0.3) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .settings-page .service-action-row {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  flex-wrap: wrap !important;
}

html.kikoerumanager-dark .settings-page .service-action-row .ghost-inline-btn {
  width: auto !important;
  min-width: 96px !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  border-radius: 10px !important;
  justify-content: center !important;
}

html.kikoerumanager-dark .settings-page .service-inline-row {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
}

html.kikoerumanager-dark .settings-page .service-inline-row .field-input {
  flex: 1 1 auto !important;
}

html.kikoerumanager-dark .settings-page .service-lottie-trigger,
html.kikoerumanager-dark .settings-page .email-watcher-action-btn {
  width: auto !important;
  min-width: 104px !important;
  min-height: 38px !important;
  padding: 0 14px !important;
  border-radius: 10px !important;
  background: rgba(15, 23, 42, 0.82) !important;
  border: 1px solid rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .service-lottie-trigger:hover,
html.kikoerumanager-dark .settings-page .email-watcher-action-btn:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .pill-switch-grid {
  display: grid !important;
  gap: 10px !important;
}

html.kikoerumanager-dark .settings-page .pill-switch-grid label,
html.kikoerumanager-dark .settings-page .pill-switch-grid button,
html.kikoerumanager-dark .settings-page .pill-switch-grid > * {
  background: rgba(30, 41, 59, 0.86) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .pill-switch-grid label:hover,
html.kikoerumanager-dark .settings-page .pill-switch-grid button:hover {
  background: rgba(37, 99, 235, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-item {
  background: rgba(30, 41, 59, 0.86) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-item:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  background-image: none !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-label {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-item p,
html.kikoerumanager-dark .settings-page .email-watcher-guide-extra {
  color: rgba(203, 213, 225, 0.78) !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-item strong {
  color: #dbeafe !important;
}

html.kikoerumanager-dark .settings-page .email-watcher-guide-item code {
  background: rgba(37, 99, 235, 0.18) !important;
  border: 1px solid rgba(147, 197, 253, 0.24) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .db-shrink,
html.kikoerumanager-dark .settings-page .db-shrink-head {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .settings-page .db-shrink-head .card-title {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .db-shrink-subtitle,
html.kikoerumanager-dark .settings-page .db-estimate-line,
html.kikoerumanager-dark .settings-page .db-estimate-meta,
html.kikoerumanager-dark .settings-page .db-shrink-tip {
  color: rgba(203, 213, 225, 0.78) !important;
}

html.kikoerumanager-dark .settings-page .db-size-chip {
  background: rgba(30, 41, 59, 0.86) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .db-size-chip:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  background-image: none !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .settings-page .db-size-label {
  color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .settings-page .db-size-value {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .db-estimate-text strong {
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .settings-page .db-btn-primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}

html.kikoerumanager-dark .settings-page .db-btn-ghost {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .db-btn-ghost:hover:not(:disabled) {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-block {
  background: rgba(30, 41, 59, 0.86) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-head strong {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-hint {
  color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-chip {
  background: rgba(15, 23, 42, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: rgba(226, 232, 240, 0.86) !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-chip.is-active {
  background: rgba(37, 99, 235, 0.2) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .notif-domain-link {
  color: #93c5fd !important;
}

html.kikoerumanager-dark .settings-page .smtp-preset-btn {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .tpl-panel-desc,
html.kikoerumanager-dark .settings-page .tpl-panel-loading,
html.kikoerumanager-dark .settings-page .tpl-panel-empty {
  color: rgba(203, 213, 225, 0.78) !important;
}

html.kikoerumanager-dark .settings-page .tpl-card {
  background: rgba(30, 41, 59, 0.86) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .settings-page .tpl-card:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  background-image: none !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .settings-page .tpl-card-name {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .tpl-card-desc,
html.kikoerumanager-dark .settings-page .tpl-meta-label {
  color: rgba(203, 213, 225, 0.72) !important;
}

html.kikoerumanager-dark .settings-page .tpl-meta-chip,
html.kikoerumanager-dark .settings-page .tpl-badge,
html.kikoerumanager-dark .settings-page .tpl-panel-count {
  background: rgba(37, 99, 235, 0.16) !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .tpl-meta-chip--muted,
html.kikoerumanager-dark .settings-page .tpl-badge--off {
  background: rgba(148, 163, 184, 0.12) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .settings-page .tpl-action,
html.kikoerumanager-dark .settings-page .tpl-panel-action,
html.kikoerumanager-dark .settings-page .tpl-create-item {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .settings-page .tpl-panel-action--primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .settings-page .tpl-action:hover,
html.kikoerumanager-dark .settings-page .tpl-panel-action:hover,
html.kikoerumanager-dark .settings-page .tpl-create-item:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .settings-page .tpl-action--danger,
html.kikoerumanager-dark .settings-page .tpl-action--danger:hover {
  background: rgba(190, 18, 60, 0.16) !important;
  border-color: rgba(253, 164, 175, 0.28) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .activity-page {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .activity-page .metric-strip,
html.kikoerumanager-dark .activity-page .overview-card,
html.kikoerumanager-dark .activity-page .filter-bar,
html.kikoerumanager-dark .activity-page .event-card,
html.kikoerumanager-dark .activity-page .footer-bar {
  background: rgba(15, 23, 42, 0.94) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.86) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .activity-page .overview-label,
html.kikoerumanager-dark .activity-page .metric-strip-label,
html.kikoerumanager-dark .activity-page .metric-cell-label,
html.kikoerumanager-dark .activity-page .event-summary,
html.kikoerumanager-dark .activity-page .cat-label,
html.kikoerumanager-dark .activity-page .day-label {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .activity-page .overview-meta,
html.kikoerumanager-dark .activity-page .metric-cell-unit,
html.kikoerumanager-dark .activity-page .event-meta,
html.kikoerumanager-dark .activity-page .event-time,
html.kikoerumanager-dark .activity-page .footer-meta,
html.kikoerumanager-dark .activity-page .cat-num,
html.kikoerumanager-dark .activity-page .sparkline-foot,
html.kikoerumanager-dark .activity-page .day-meta {
  color: rgba(203, 213, 225, 0.74) !important;
}

html.kikoerumanager-dark .activity-page .filter-reset,
html.kikoerumanager-dark .activity-page .page-head-search,
html.kikoerumanager-dark .activity-page .page-head-search-input {
  background: rgba(15, 23, 42, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .activity-page .filter-reset:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .activity-page .event-row:hover .event-card,
html.kikoerumanager-dark .activity-page .event-row.is-active .event-card {
  background: rgba(37, 99, 235, 0.18) !important;
  background-image: none !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .activity-page .day-events,
html.kikoerumanager-dark .activity-page .event-row,
html.kikoerumanager-dark .activity-page .event-row.tone-success,
html.kikoerumanager-dark .activity-page .event-row.tone-info,
html.kikoerumanager-dark .activity-page .event-row.tone-warn,
html.kikoerumanager-dark .activity-page .event-row.tone-danger,
html.kikoerumanager-dark .activity-page .event-row.tone-neutral {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .activity-page .event-row::before,
html.kikoerumanager-dark .activity-page .event-row::after {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .activity-page .event-row:hover {
  background: transparent !important;
  background-image: none !important;
}

html.kikoerumanager-dark .activity-page .event-rail {
  background: transparent !important;
}

html.kikoerumanager-dark .activity-page .event-rail::before {
  background: rgba(148, 163, 184, 0.16) !important;
}

html.kikoerumanager-dark .activity-page .event-dot {
  background: rgba(15, 23, 42, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.28) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .activity-page .event-dot.tone-success {
  background: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.38) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .activity-page .event-dot.tone-info {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.38) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .activity-page .event-dot.tone-warn {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.38) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .activity-page .event-dot.tone-danger {
  background: rgba(190, 18, 60, 0.16) !important;
  border-color: rgba(253, 164, 175, 0.38) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .activity-page .event-path,
html.kikoerumanager-dark .activity-page .inline-flex {
  background-color: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
}

html.kikoerumanager-dark .activity-page .cat-track {
  background: rgba(15, 23, 42, 0.86) !important;
}

html.kikoerumanager-dark .activity-page .footer-pager .el-pagination button,
html.kikoerumanager-dark .activity-page .footer-pager .el-pagination .el-pager li,
html.kikoerumanager-dark .activity-page .footer-pager .el-pagination .el-input__wrapper,
html.kikoerumanager-dark .activity-page .footer-pager .el-pagination .el-select__wrapper {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .activity-page .footer-pager .el-pagination .el-pager li.is-active {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .activity-page .event-card-head .inline-flex,
html.kikoerumanager-dark .activity-page .event-meta .inline-flex {
  background-color: rgba(15, 23, 42, 0.78) !important;
  border-color: rgba(148, 163, 184, 0.28) !important;
  color: rgba(226, 232, 240, 0.92) !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .activity-page .event-card-head .inline-flex svg,
html.kikoerumanager-dark .activity-page .event-meta .inline-flex svg {
  color: currentColor !important;
}

html.kikoerumanager-dark .activity-page .event-card-head [class*="text-emerald"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-emerald"] {
  background-color: rgba(16, 185, 129, 0.16) !important;
  border-color: rgba(110, 231, 183, 0.32) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .activity-page .event-card-head [class*="text-sky"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-sky"],
html.kikoerumanager-dark .activity-page .event-card-head [class*="text-blue"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-blue"] {
  background-color: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .activity-page .event-card-head [class*="text-violet"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-violet"],
html.kikoerumanager-dark .activity-page .event-card-head [class*="text-purple"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-purple"] {
  background-color: rgba(124, 58, 237, 0.18) !important;
  border-color: rgba(196, 181, 253, 0.32) !important;
  color: #ddd6fe !important;
}

html.kikoerumanager-dark .activity-page .event-card-head [class*="text-amber"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-amber"],
html.kikoerumanager-dark .activity-page .event-card-head [class*="text-orange"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-orange"] {
  background-color: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.32) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .activity-page .event-card-head [class*="text-rose"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-rose"],
html.kikoerumanager-dark .activity-page .event-card-head [class*="text-red"],
html.kikoerumanager-dark .activity-page .event-meta [class*="text-red"] {
  background-color: rgba(190, 18, 60, 0.16) !important;
  border-color: rgba(253, 164, 175, 0.32) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .activity-page .event-summary {
  color: rgba(241, 245, 249, 0.96) !important;
  font-weight: 600 !important;
}

html.kikoerumanager-dark .activity-page .event-path {
  color: rgba(203, 213, 225, 0.86) !important;
}

html.kikoerumanager-dark .activity-page .event-path-text {
  color: rgba(203, 213, 225, 0.9) !important;
}

html.kikoerumanager-dark .activity-page .rename-old {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(251, 191, 36, 0.32) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .activity-page .rename-arrow {
  background: rgba(37, 99, 235, 0.18) !important;
  color: #bfdbfe !important;
}

html.kikoerumanager-dark .activity-page .rename-new {
  background: rgba(16, 185, 129, 0.18) !important;
  border-color: rgba(110, 231, 183, 0.32) !important;
  color: #a7f3d0 !important;
}

html.kikoerumanager-dark .activity-page .rename-reason-inline {
  color: rgba(203, 213, 225, 0.76) !important;
}

html.kikoerumanager-dark .activity-drawer,
html.kikoerumanager-dark .activity-drawer .el-drawer__body,
html.kikoerumanager-dark .detail-body {
  background: linear-gradient(180deg, rgba(7, 11, 18, 0.98) 0%, rgba(15, 23, 42, 0.96) 100%) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-head,
html.kikoerumanager-dark .detail-foot {
  background: rgba(15, 23, 42, 0.92) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-close,
html.kikoerumanager-dark .copy-btn,
html.kikoerumanager-dark .panel-toggle,
html.kikoerumanager-dark .foot-btn {
  background: rgba(15, 23, 42, 0.82) !important;
  border-color: rgba(96, 165, 250, 0.24) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .detail-close:hover,
html.kikoerumanager-dark .copy-btn:hover,
html.kikoerumanager-dark .panel-toggle:hover,
html.kikoerumanager-dark .foot-btn:hover {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .foot-btn.primary {
  background: linear-gradient(180deg, #60a5fa 0%, #2563eb 100%) !important;
  border-color: rgba(147, 197, 253, 0.42) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .detail-title,
html.kikoerumanager-dark .panel-head,
html.kikoerumanager-dark .summary-text,
html.kikoerumanager-dark .meta-row dd,
html.kikoerumanager-dark .child-rel,
html.kikoerumanager-dark .child-summary {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .detail-subtitle,
html.kikoerumanager-dark .subtitle-time,
html.kikoerumanager-dark .meta-row dt,
html.kikoerumanager-dark .child-time {
  color: rgba(203, 213, 225, 0.74) !important;
}

html.kikoerumanager-dark .detail-body .panel {
  background: rgba(15, 23, 42, 0.94) !important;
  background-image: linear-gradient(180deg, rgba(30, 41, 59, 0.86) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .detail-body .rounded-xl,
html.kikoerumanager-dark .detail-body .inline-flex {
  background-color: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
}

html.kikoerumanager-dark .detail-body .child-item {
  background: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
}

html.kikoerumanager-dark .detail-body .child-item:hover,
html.kikoerumanager-dark .detail-body .child-item.is-expanded {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .detail-body .raw-json-wrap {
  background: rgba(2, 6, 23, 0.96) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .detail-body .raw-json {
  color: #dbeafe !important;
}

html.kikoerumanager-dark .detail-body [class*="text-slate-900"],
html.kikoerumanager-dark .detail-body [class*="text-slate-800"],
html.kikoerumanager-dark .detail-body [class*="text-slate-700"],
html.kikoerumanager-dark .detail-body .entry-section-title,
html.kikoerumanager-dark .detail-body .highlight-value,
html.kikoerumanager-dark .detail-body .highlight-num,
html.kikoerumanager-dark .detail-body .metric-num,
html.kikoerumanager-dark .detail-body .metric-cell-value,
html.kikoerumanager-dark .detail-body .metric-tail-v,
html.kikoerumanager-dark .detail-body .entry-name {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .detail-body [class*="text-slate-600"],
html.kikoerumanager-dark .detail-body [class*="text-slate-500"],
html.kikoerumanager-dark .detail-body [class*="text-slate-400"],
html.kikoerumanager-dark .detail-body .entry-eyebrow,
html.kikoerumanager-dark .detail-body .entry-section-desc,
html.kikoerumanager-dark .detail-body .highlight-label,
html.kikoerumanager-dark .detail-body .highlight-unit,
html.kikoerumanager-dark .detail-body .metric-cell-label,
html.kikoerumanager-dark .detail-body .metric-unit,
html.kikoerumanager-dark .detail-body .metric-tail-k,
html.kikoerumanager-dark .detail-body .entry-meta,
html.kikoerumanager-dark .detail-body .entry-subtitle {
  color: rgba(203, 213, 225, 0.76) !important;
}

html.kikoerumanager-dark .detail-body [class*="bg-slate-50"],
html.kikoerumanager-dark .detail-body [class*="bg-slate-100"],
html.kikoerumanager-dark .detail-body [class*="bg-white"],
html.kikoerumanager-dark .detail-body .highlight-row,
html.kikoerumanager-dark .detail-body .metric-cell,
html.kikoerumanager-dark .detail-body .metric-tail-row,
html.kikoerumanager-dark .detail-body .entry-row,
html.kikoerumanager-dark .detail-body .entry-item,
html.kikoerumanager-dark .detail-body .entry-section-toggle {
  background-color: rgba(15, 23, 42, 0.74) !important;
  background-image: none !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-body .metric-strip {
  background: rgba(15, 23, 42, 0.74) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .detail-body .highlight-grid,
html.kikoerumanager-dark .detail-body .metric-tail {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-body .entry-section-toggle:hover,
html.kikoerumanager-dark .detail-body .entry-row:hover,
html.kikoerumanager-dark .detail-body .entry-item:hover {
  background: rgba(37, 99, 235, 0.18) !important;
  border-color: rgba(147, 197, 253, 0.34) !important;
}

html.kikoerumanager-dark .detail-body code,
html.kikoerumanager-dark .detail-body .mono,
html.kikoerumanager-dark .detail-body .path {
  color: #dbeafe !important;
}
</style>

<style scoped>
.app-container {
  height: 100vh;
  padding: 16px;
  gap: 16px;
  background: #ffffff;
}

.sidebar {
  width: 248px !important;
  border-radius: 30px;
  overflow: hidden;
}

.sidebar-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 20px 16px 16px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(29, 29, 31, 0.06);
  box-shadow: 0 22px 48px rgba(0, 0, 0, 0.08);
  backdrop-filter: blur(20px);
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 18px;
}

.logo-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.logo-bell {
  flex-shrink: 0;
}

/* 铃铛放在副标题行右侧，跟 v1.x.x 字号匹配的紧凑尺寸 */
.logo-bell :deep(.notif-bell-btn) {
  width: 44px;
  height: 44px;
}
.logo-bell :deep(.notif-bell-player) {
  width: 36px;
  height: 36px;
}

.logo-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 13px;
  background: #f3f7ff;
  color: #0071e3;
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.08);
  flex-shrink: 0;
}

.logo-mark > svg {
  flex-shrink: 0;
}

.logo-text {
  font-size: 17px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.18px;
  color: #1d1d1f;
  white-space: nowrap;
}

.logo-subtitle {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.54);
  white-space: nowrap;
}

.sidebar-section-label {
  margin: 0 10px 10px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(29, 29, 31, 0.42);
  text-transform: uppercase;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  background: transparent;
}

.sidebar-footer {
  padding: 16px 8px 0;
}

.sidebar-status-card {
  padding: 14px;
  border-radius: 22px;
  background: #f7f7fa;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
}

.sidebar-status-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.sidebar-status-title {
  font-size: 15px;
  font-weight: 600;
  color: #1d1d1f;
}

.sidebar-status-text {
  margin-bottom: 12px;
  font-size: 13px;
  line-height: 1.45;
  color: rgba(29, 29, 31, 0.62);
}

.watcher-button {
  width: 100%;
  height: 38px;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 999px;
  background: #ffffff;
  color: #1d1d1f;
}

.watcher-button:hover,
.watcher-button:focus {
  color: #1d1d1f;
  border-color: rgba(29, 29, 31, 0.14);
  background: #f1f1f4;
}

.conflict-badge {
  margin-left: auto;
}

.version-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 14px;
  padding: 0 6px;
}

.version-text {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.46);
}

.version-text {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #1d1d1f;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.main-frame {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.main-content {
  min-width: 0;
  padding: 0;
  overflow: hidden;
}

.main-shell {
  background: transparent;
}

.content-shell {
  height: 100%;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

:deep(.sidebar-menu .el-menu) {
  border-right: none;
}

:deep(.sidebar-menu .el-menu-item) {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 46px;
  margin: 4px 0;
  border-radius: 16px;
  color: rgba(29, 29, 31, 0.72);
  font-size: 14px;
}

:deep(.sidebar-menu .el-menu-item > svg) {
  flex: 0 0 auto;
  color: rgba(29, 29, 31, 0.56);
}

:deep(.sidebar-menu .el-menu-item:hover) {
  background: #f3f3f6;
  color: #1d1d1f;
}

:deep(.sidebar-menu .el-menu-item:hover > svg) {
  color: #1d1d1f;
}

:deep(.sidebar-menu .el-menu-item.is-active) {
  background: #f0f6ff;
  color: #0066cc;
  font-weight: 600;
}

:deep(.sidebar-menu .el-menu-item.is-active > svg) {
  color: #0071e3;
}

:deep(.el-card) {
  overflow: visible;
}

:deep(.el-tag.el-tag--info.el-tag--plain) {
  color: rgba(29, 29, 31, 0.72);
  border-color: rgba(29, 29, 31, 0.08);
  background: rgba(255, 255, 255, 0.85);
}

:deep(.el-tag.el-tag--success.el-tag--plain) {
  color: #1f8f4e;
  border-color: rgba(31, 143, 78, 0.14);
  background: rgba(238, 248, 240, 0.9);
}

.theme-toggle-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 26px;
  min-width: 0;
  padding: 0 8px;
  overflow: hidden;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.68);
  color: rgba(29, 29, 31, 0.72);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.62);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: -0.01em;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.24s ease, color 0.24s ease, box-shadow 0.24s ease;
}

.theme-toggle-button:hover {
  transform: translateY(-1px) scale(1.03);
  border-color: rgba(29, 29, 31, 0.16);
  color: #1d1d1f;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08), inset 0 0 0 1px rgba(255, 255, 255, 0.72);
}

.theme-toggle-button:active {
  transform: scale(0.96);
}

.theme-toggle-button.is-dark {
  background: rgba(15, 23, 42, 0.36);
  border-color: rgba(147, 197, 253, 0.18);
  color: #dbeafe;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

.theme-toggle-button.is-dark:hover {
  border-color: rgba(147, 197, 253, 0.34);
  color: #f8fafc;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12), inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.theme-toggle-text {
  position: relative;
  z-index: 1;
}

.theme-toggle-icon {
  flex: 0 0 auto;
  transition: color 0.3s ease, filter 0.3s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.theme-toggle-button:hover .theme-toggle-icon {
  transform: rotate(-12deg) scale(1.1);
}

.theme-toggle-icon-sun {
  color: #f59e0b;
  filter: drop-shadow(0 0 5px rgba(245, 158, 11, 0.26));
}

.theme-toggle-icon-moon {
  color: #2563eb;
  filter: drop-shadow(0 0 5px rgba(37, 99, 235, 0.24));
}

.theme-icon-enter-active,
.theme-icon-leave-active {
  transition: opacity 0.24s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.24s ease;
}

.theme-icon-enter-from {
  opacity: 0;
  transform: rotate(-80deg) scale(0.35);
  filter: blur(5px);
}

.theme-icon-leave-to {
  opacity: 0;
  transform: rotate(80deg) scale(0.35);
  filter: blur(5px);
}

:global(html.kikoerumanager-dark) {
  color-scheme: dark;
}

:global(html.kikoerumanager-dark body) {
  background: #070b12;
}

:global(html.kikoerumanager-dark) .app-container {
  background: #070b12;
}

:global(html.kikoerumanager-dark) .sidebar-shell {
  background: rgba(15, 23, 42, 0.86);
  border-color: rgba(148, 163, 184, 0.14);
  box-shadow: 0 22px 56px rgba(0, 0, 0, 0.38);
}

:global(html.kikoerumanager-dark) .logo-text,
:global(html.kikoerumanager-dark) .sidebar-status-title,
:global(html.kikoerumanager-dark) .watcher-button,
:global(html.kikoerumanager-dark) .version-text {
  color: #f8fafc;
}

:global(html.kikoerumanager-dark) .logo-subtitle,
:global(html.kikoerumanager-dark) .sidebar-section-label,
:global(html.kikoerumanager-dark) .sidebar-status-text {
  color: rgba(226, 232, 240, 0.62);
}

:global(html.kikoerumanager-dark) .logo-mark,
:global(html.kikoerumanager-dark) .app-mobile-brand-mark {
  background: rgba(59, 130, 246, 0.16);
  color: #93c5fd;
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.16);
}

:global(html.kikoerumanager-dark) .sidebar-status-card {
  background: rgba(30, 41, 59, 0.76);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.12);
}

:global(html.kikoerumanager-dark) .watcher-button,
:global(html.kikoerumanager-dark) .version-text {
  background: rgba(15, 23, 42, 0.86);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.1);
}

:global(html.kikoerumanager-dark) .watcher-button:hover,
:global(html.kikoerumanager-dark) .watcher-button:focus {
  background: rgba(30, 41, 59, 0.92);
  border-color: rgba(148, 163, 184, 0.24);
  color: #f8fafc;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item) {
  color: rgba(226, 232, 240, 0.74);
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item > svg) {
  color: rgba(203, 213, 225, 0.58);
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item:hover) {
  background: rgba(51, 65, 85, 0.72);
  color: #f8fafc;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item:hover > svg) {
  color: #f8fafc;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item.is-active) {
  background: rgba(37, 99, 235, 0.18);
  color: #93c5fd;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item.is-active > svg) {
  color: #60a5fa;
}

:global(html.kikoerumanager-dark) :deep(.el-card),
:global(html.kikoerumanager-dark) :deep(.el-dialog),
:global(html.kikoerumanager-dark) :deep(.el-drawer),
:global(html.kikoerumanager-dark) :deep(.el-message-box),
:global(html.kikoerumanager-dark) :deep(.el-popover),
:global(html.kikoerumanager-dark) :deep(.el-popper),
:global(html.kikoerumanager-dark) :deep(.el-dropdown__popper .el-dropdown-menu),
:global(html.kikoerumanager-dark) :deep(.el-picker-panel),
:global(html.kikoerumanager-dark) :deep(.el-select-dropdown) {
  background: rgba(15, 23, 42, 0.96);
  border-color: rgba(148, 163, 184, 0.16);
  color: #e2e8f0;
}

:global(html.kikoerumanager-dark) :deep(.el-input__wrapper),
:global(html.kikoerumanager-dark) :deep(.el-textarea__inner) {
  background: rgba(15, 23, 42, 0.88);
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.16) inset;
}

:global(html.kikoerumanager-dark) :deep(.el-input__inner),
:global(html.kikoerumanager-dark) :deep(.el-textarea__inner),
:global(html.kikoerumanager-dark) :deep(.el-form-item__label),
:global(html.kikoerumanager-dark) :deep(.el-dialog__title),
:global(html.kikoerumanager-dark) :deep(.el-message-box__title),
:global(html.kikoerumanager-dark) :deep(.el-message-box__message) {
  color: #e2e8f0;
}

:global(html.kikoerumanager-dark) :deep(.el-table),
:global(html.kikoerumanager-dark) :deep(.el-table tr),
:global(html.kikoerumanager-dark) :deep(.el-table th.el-table__cell),
:global(html.kikoerumanager-dark) :deep(.el-table td.el-table__cell) {
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  border-color: rgba(148, 163, 184, 0.14);
}

:global(html.kikoerumanager-dark) .theme-toggle-button {
  background: rgba(15, 23, 42, 0.36);
  border-color: rgba(147, 197, 253, 0.18);
  color: #dbeafe;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

:global(html.kikoerumanager-dark) .theme-toggle-button:hover {
  border-color: rgba(147, 197, 253, 0.34);
  color: #f8fafc;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12), inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

/* ============================================================
 * 移动端顶栏 + 抽屉式侧栏（Phase 1）
 * 桌面端 (≥1025px) 零改动：
 *  - .app-mobile-topbar 默认 display:none
 *  - .app-drawer-mask 用 v-if 渲染，桌面态永远 false
 *  - .is-mobile-nav-open / .is-mobile-open class 桌面态永远不挂
 * ============================================================ */

/* 顶栏默认隐藏（桌面态） */
.app-mobile-topbar {
  display: none;
}

/* 抽屉遮罩默认 z-index 但无视觉（仅在 v-if 渲染时出现） */
.app-drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

/* 遮罩过渡 */
.app-drawer-mask-enter-active,
.app-drawer-mask-leave-active {
  transition: opacity 0.22s ease;
}
.app-drawer-mask-enter-from,
.app-drawer-mask-leave-to {
  opacity: 0;
}

/* ----------------- 平板及以下 (≤1024) ----------------- */
@media (max-width: 1024px) {
  /* 顶栏出现 */
  .app-mobile-topbar {
    position: sticky;
    top: 0;
    z-index: 80;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    background: rgba(255, 255, 255, 0.92);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(15, 23, 42, 0.06);
    min-height: 52px;
  }

  /* app-container 改为顶栏 + 主区垂直布局 */
  .app-container {
    flex-direction: column;
    padding: 0;
    gap: 0;
    height: 100vh;
    height: 100dvh;
  }

  /* 汉堡按钮 */
  .app-mobile-trigger {
    flex-shrink: 0;
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: transparent;
    border: 1px solid transparent;
    color: #0f172a;
    cursor: pointer;
    transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  .app-mobile-trigger:hover {
    background: rgba(15, 23, 42, 0.06);
    border-color: rgba(15, 23, 42, 0.08);
  }
  .app-mobile-trigger:active {
    transform: scale(0.94);
  }

  /* 顶栏中间品牌区 */
  .app-mobile-brand {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .app-mobile-brand-mark {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 9px;
    background: #f3f7ff;
    color: #0071e3;
  }
  .app-mobile-brand-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
    line-height: 1.1;
  }
  .app-mobile-brand-text {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
    letter-spacing: -0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .app-mobile-brand-version {
    font-size: 10px;
    color: rgba(15, 23, 42, 0.48);
  }
  .app-mobile-bell {
    flex-shrink: 0;
  }
  .app-mobile-bell :deep(.notif-bell-btn) {
    width: 40px;
    height: 40px;
  }
  .app-mobile-bell :deep(.notif-bell-player) {
    width: 32px;
    height: 32px;
  }
  :global(html.kikoerumanager-dark) .app-mobile-topbar {
    background: rgba(15, 23, 42, 0.92);
    border-bottom-color: rgba(148, 163, 184, 0.12);
  }
  :global(html.kikoerumanager-dark) .app-mobile-trigger,
  :global(html.kikoerumanager-dark) .app-mobile-brand-text {
    color: #f8fafc;
  }
  :global(html.kikoerumanager-dark) .app-mobile-brand-version {
    color: rgba(226, 232, 240, 0.58);
  }
  :global(html.kikoerumanager-dark) .app-mobile-trigger:hover {
    background: rgba(148, 163, 184, 0.12);
    border-color: rgba(148, 163, 184, 0.16);
  }

  /* 侧栏切到抽屉态：默认 translateX(-100%) 隐藏 */
  .sidebar {
    position: fixed !important;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    width: min(82vw, 320px) !important;
    height: 100vh;
    height: 100dvh;
    border-radius: 0 22px 22px 0;
    transform: translateX(-100%);
    transition: transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
    will-change: transform;
    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.24);
  }

  /* 抽屉打开态 */
  .sidebar.is-mobile-open {
    transform: translateX(0);
  }

  /* sidebar-shell 在抽屉态调整 */
  .sidebar-shell {
    height: 100%;
    padding: 16px 14px 16px;
    border-radius: 0 22px 22px 0;
  }

  /* 主内容区铺满 */
  .main-frame {
    flex: 1;
    min-height: 0;
  }
  .main-content {
    padding: 0;
    height: 100%;
  }
  .content-shell {
    height: 100%;
    padding-right: 0;
  }
  .theme-toggle-button {
    height: 26px;
  }
}

/* ----------------- 手机 (≤640) 微调 ----------------- */
@media (max-width: 640px) {
  .app-mobile-topbar {
    padding: 6px 10px;
    min-height: 48px;
  }
  .sidebar {
    border-radius: 0 18px 18px 0;
  }
  .sidebar-shell {
    border-radius: 0 18px 18px 0;
    padding: 14px 12px 12px;
  }
}
</style>

<style>
html,
body {
  height: 100%;
  margin: 0;
  padding: 0;
  overflow: hidden;
}

#app {
  height: 100vh;
  height: 100dvh;
}

/* 抽屉打开时锁定 body 滚动（非 scoped 才能覆盖到 body） */
body.app-mobile-nav-locked {
  overflow: hidden !important;
  touch-action: none;
}
</style>
