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

    <el-aside
      v-if="!isGateRoute"
      width="248px"
      class="sidebar"
      :class="{ 'is-mobile-open': mobileNavOpen, 'is-sidebar-pinned': sidebarPinned }"
    >
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

        <button
          type="button"
          class="sidebar-pin-button"
          :class="{ 'is-pinned': sidebarPinned }"
          :aria-pressed="sidebarPinned"
          :aria-label="sidebarPinned ? '取消常驻展开侧边栏' : '常驻展开侧边栏'"
          :title="sidebarPinned ? '取消常驻展开侧边栏' : '常驻展开侧边栏'"
          @click="toggleSidebarPinned"
        >
          <ChevronsLeft v-if="sidebarPinned" :size="17" :stroke-width="2.2" />
          <ChevronsRight v-else :size="17" :stroke-width="2.2" />
          <span>{{ sidebarPinned ? '收回侧栏' : '常驻展开' }}</span>
        </button>

        <div class="sidebar-section-label">导航</div>

        <el-menu
          :default-active="route.path"
          router
          class="sidebar-menu"
        >
          <el-menu-item index="/" title="概览" class="sidebar-nav-item sidebar-nav-overview">
            <House :size="18" :stroke-width="2.2" />
            <span>概览</span>
          </el-menu-item>

          <el-menu-item index="/tasks" title="任务队列" class="sidebar-nav-item sidebar-nav-tasks">
            <ListTodo :size="18" :stroke-width="2.2" />
            <span>任务队列</span>
          </el-menu-item>

          <el-menu-item index="/conflicts" title="问题作品" class="sidebar-nav-item sidebar-nav-conflicts">
            <TriangleAlert :size="18" :stroke-width="2.2" />
            <span>问题作品</span>
            <el-badge v-if="conflictCount > 0" :value="conflictCount" class="conflict-badge" />
          </el-menu-item>

          <el-menu-item index="/library" title="库存管理" class="sidebar-nav-item sidebar-nav-library">
            <Boxes :size="18" :stroke-width="2.2" />
            <span>库存管理</span>
          </el-menu-item>

          <el-menu-item index="/subtitle-import" title="字幕补配" class="sidebar-nav-item sidebar-nav-subtitle">
            <Captions :size="18" :stroke-width="2.2" />
            <span>字幕补配</span>
          </el-menu-item>

          <el-menu-item index="/passwords" title="密码库" class="sidebar-nav-item sidebar-nav-passwords">
            <KeyRound :size="18" :stroke-width="2.2" />
            <span>密码库</span>
          </el-menu-item>

          <el-menu-item index="/existing-folders" title="已有文件夹" class="sidebar-nav-item sidebar-nav-folders">
            <FolderTree :size="18" :stroke-width="2.2" />
            <span>已有文件夹</span>
          </el-menu-item>

          <el-menu-item index="/asmr-sync" title="ASMR 同步下载" class="sidebar-nav-item sidebar-nav-asmr">
            <Download :size="18" :stroke-width="2.2" />
            <span>ASMR 同步下载</span>
          </el-menu-item>

          <el-menu-item index="/circle-completion" title="社团补全" class="sidebar-nav-item sidebar-nav-circle">
            <Tags :size="18" :stroke-width="2.2" />
            <span>社团补全</span>
          </el-menu-item>

          <el-menu-item index="/library-backup" title="库存打包" class="sidebar-nav-item sidebar-nav-backup">
            <Archive :size="18" :stroke-width="2.2" />
            <span>库存打包</span>
          </el-menu-item>

          <el-menu-item index="/settings" title="设置" class="sidebar-nav-item sidebar-nav-settings">
            <Settings2 :size="18" :stroke-width="2.2" />
            <span>设置</span>
          </el-menu-item>

          <el-menu-item index="/logs" title="日志" class="sidebar-nav-item sidebar-nav-logs">
            <ScrollText :size="18" :stroke-width="2.2" />
            <span>日志</span>
          </el-menu-item>

          <el-menu-item index="/activity-history" title="操作记录" class="sidebar-nav-item sidebar-nav-history">
            <History :size="18" :stroke-width="2.2" />
            <span>操作记录</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-footer">
          <NotificationBell class="sidebar-rail-bell" />
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
              :class="{ 'is-running': watcherStatus.is_running }"
              size="small"
              :aria-label="watcherStatus.is_running ? '停止监视器' : '启动监视器'"
              :title="watcherStatus.is_running ? '停止监视器' : '启动监视器'"
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
  ChevronsLeft,
  ChevronsRight,
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

const appVersion = '1.5.45'
const route = useRoute()
const watcherStore = useWatcherStore()
const conflictCount = ref(0)
const watcherStatus = ref({ is_running: false, watch_path: '', pending_files: [] })
const mobileNavOpen = ref(false)
const themeStorageKey = 'kikoerumanager.theme'
const sidebarPinnedStorageKey = 'kikoerumanager.sidebarPinned'
const themeTransitionClass = 'kikoerumanager-theme-transition'
const themeTransitionDuration = 460
const isDarkTheme = ref(false)
const sidebarPinned = ref(false)
let themeTransitionTimer = null

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
  sidebarPinned.value = readInitialSidebarPinned()
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
  clearThemeTransitionClass()
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

function readInitialSidebarPinned() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(sidebarPinnedStorageKey) === 'true'
}

function applyTheme() {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('kikoerumanager-dark', isDarkTheme.value)
  document.body.classList.toggle('kikoerumanager-dark', isDarkTheme.value)
  const themeColorMeta = document.querySelector('meta[name="theme-color"]')
  if (themeColorMeta) {
    themeColorMeta.setAttribute('content', isDarkTheme.value ? '#08090d' : '#ffffff')
  }
}

function persistTheme() {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(themeStorageKey, isDarkTheme.value ? 'dark' : 'light')
  }
}

function commitThemeToggle() {
  isDarkTheme.value = !isDarkTheme.value
  applyTheme()
  persistTheme()
}

function getThemeTransitionOrigin(event) {
  if (typeof window === 'undefined') {
    return { x: 0, y: 0, radius: 0 }
  }
  const target = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null
  const rect = target?.getBoundingClientRect()
  const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2
  const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
  return { x, y, radius }
}

function clearThemeTransitionClass() {
  if (typeof document === 'undefined') return
  if (themeTransitionTimer) {
    clearTimeout(themeTransitionTimer)
    themeTransitionTimer = null
  }
  document.documentElement.classList.remove(themeTransitionClass)
  document.body.classList.remove(themeTransitionClass)
}

function markThemeTransitioning(event) {
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const { x, y, radius } = getThemeTransitionOrigin(event)
  document.documentElement.style.setProperty('--theme-transition-x', `${x}px`)
  document.documentElement.style.setProperty('--theme-transition-y', `${y}px`)
  document.documentElement.style.setProperty('--theme-transition-radius', `${Math.ceil(radius)}px`)
  document.documentElement.style.setProperty(
    '--theme-transition-color',
    isDarkTheme.value ? 'rgba(255, 255, 255, 0.5)' : 'rgba(8, 9, 13, 0.36)'
  )
  document.documentElement.classList.add(themeTransitionClass)
  document.body.classList.add(themeTransitionClass)
  if (themeTransitionTimer) clearTimeout(themeTransitionTimer)
  themeTransitionTimer = setTimeout(clearThemeTransitionClass, themeTransitionDuration + 80)
}

function toggleTheme(event) {
  markThemeTransitioning(event)
  commitThemeToggle()
}

function toggleSidebarPinned() {
  sidebarPinned.value = !sidebarPinned.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(sidebarPinnedStorageKey, sidebarPinned.value ? 'true' : 'false')
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
  color: var(--sidebar-nav-icon, rgba(203, 213, 225, 0.58));
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover {
  background: transparent;
  color: #f8fafc;
  box-shadow: none;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover > svg {
  color: var(--sidebar-nav-icon, #f8fafc);
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active {
  background: transparent;
  color: #f8fafc;
  box-shadow: none;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active > svg {
  color: var(--sidebar-nav-icon, #f8fafc);
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

body.kikoerumanager-theme-transition::before {
  position: fixed;
  left: var(--theme-transition-x, 50vw);
  top: var(--theme-transition-y, 50vh);
  z-index: 2147483647;
  width: 1px;
  height: 1px;
  pointer-events: none;
  content: "";
  border-radius: 999px;
  background: var(--theme-transition-color, rgba(15, 23, 42, 0.32));
  opacity: 0;
  transform: translate3d(-50%, -50%, 0) scale(0);
  animation: theme-lightweight-ripple 0.46s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform, opacity;
}

html.kikoerumanager-theme-transition body,
html.kikoerumanager-theme-transition #app,
html.kikoerumanager-theme-transition .app-container,
html.kikoerumanager-theme-transition .sidebar-shell,
html.kikoerumanager-theme-transition .content-shell,
html.kikoerumanager-theme-transition .main-shell {
  transition:
    background-color 0.28s ease,
    background 0.28s ease,
    border-color 0.28s ease,
    color 0.24s ease,
    box-shadow 0.28s ease !important;
}

@keyframes theme-lightweight-ripple {
  0% {
    opacity: 0.28;
    transform: translate3d(-50%, -50%, 0) scale(0);
  }
  55% {
    opacity: 0.18;
  }
  100% {
    opacity: 0;
    transform: translate3d(-50%, -50%, 0) scale(var(--theme-transition-radius, 1400));
  }
}

@media (prefers-reduced-motion: reduce) {
  body.kikoerumanager-theme-transition::before {
    animation-duration: 0.01ms;
  }
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
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 22px 58px rgba(0, 0, 0, 0.52), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-100,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .bg-slate-100,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-slate-50,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-slate-100 {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-command"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .hover\:bg-slate-50\/50:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .hover\:bg-slate-50\/50:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .hover\:bg-slate-50:hover,
html.kikoerumanager-dark .task-card:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
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
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .dash-icon-btn:hover,
html.kikoerumanager-dark .dash-cmd-btn:not(:first-child):hover,
html.kikoerumanager-dark .dash-archive-refresh-btn:hover,
html.kikoerumanager-dark .dash-archive-pager-btn:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] button:not(.theme-toggle-button):hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] button:not(.theme-toggle-button):hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .dash-kpi {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .dash-kpi:hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .dash-status-chip {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .dash-status-chip:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .dash-icon-hover:not([class*="text-"]),
html.kikoerumanager-dark .dash-icon-default:not([class*="text-"]),
html.kikoerumanager-dark .el-button svg:not([class*="text-"]) {
  color: currentColor;
}

html.kikoerumanager-dark .dash-kpi .group-hover\:bg-slate-900,
html.kikoerumanager-dark .dash-kpi:hover .group-hover\:bg-slate-900 {
  background: var(--km-dark-surface-hover) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark [data-section="dashboard-tasks"] .border-dashed {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .border-dashed,
html.kikoerumanager-dark [data-section="dashboard-hero"] .border-neutral-200,
html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-50:hover {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] select,
html.kikoerumanager-dark [data-section="dashboard-hero"] option {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-slate-900 {
  background: #020617 !important;
  color: #ffffff !important;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .hover\:bg-slate-800:hover {
  background: #111116 !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .bg-amber-50,
html.kikoerumanager-dark [data-section="dashboard-archive"] .bg-amber-50 {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(245, 158, 11, 0.26) !important;
}

html.kikoerumanager-dark [data-section="dashboard-command"] .bg-blue-600 {
  background: #020617 !important;
  color: #ffffff !important;
  border-color: var(--km-dark-border-strong) !important;
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.44), inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .el-input__wrapper,
html.kikoerumanager-dark .el-radio-button__inner {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .el-radio-button__original-radio:checked + .el-radio-button__inner {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
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
html.kikoerumanager-dark .page-head-btn:not(.is-primary),
html.kikoerumanager-dark .lib-action-btn:not(.is-primary),
html.kikoerumanager-dark .conflicts-action-btn.is-slate {
  background: var(--km-dark-button-bg) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success):hover,
html.kikoerumanager-dark .app-dd-trigger:hover,
html.kikoerumanager-dark .app-dd-trigger.is-open,
html.kikoerumanager-dark .tasks-toolbar-btn:hover,
html.kikoerumanager-dark .tasks-toolbar-btn.is-on,
html.kikoerumanager-dark .subtitle-refresh-btn:hover,
html.kikoerumanager-dark .subtitle-action-btn:not(.is-primary):hover,
html.kikoerumanager-dark .subtitle-mini-btn:hover,
html.kikoerumanager-dark .page-head-btn:not(.is-primary):hover,
html.kikoerumanager-dark .lib-action-btn:not(.is-primary):hover,
html.kikoerumanager-dark .conflicts-action-btn.is-slate:hover {
  background: var(--km-dark-button-bg-hover) !important;
  background-image: none !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .el-button--primary,
html.kikoerumanager-dark .subtitle-action-btn.is-primary,
html.kikoerumanager-dark .page-head-btn.is-primary,
html.kikoerumanager-dark .lib-action-btn.is-primary,
html.kikoerumanager-dark .conflicts-action-btn.is-primary {
  background: var(--km-dark-primary-button-bg) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-primary-button-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .el-button--danger,
html.kikoerumanager-dark button.is-danger,
html.kikoerumanager-dark .el-button.is-danger,
html.kikoerumanager-dark .conflicts-action-btn.is-danger {
  background: linear-gradient(180deg, rgba(244, 63, 94, 0.34) 0%, rgba(127, 29, 29, 0.9) 100%) !important;
  border-color: rgba(253, 164, 175, 0.36) !important;
  color: #ffe4e6 !important;
  box-shadow: 0 12px 26px rgba(244, 63, 94, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .el-button,
html.kikoerumanager-dark [data-section="dashboard-command"] .el-button,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .el-button,
html.kikoerumanager-dark [data-section="dashboard-archive"] .el-button,
html.kikoerumanager-dark [data-section="dashboard-hero"] .dash-cmd-btn,
html.kikoerumanager-dark [data-section="dashboard-command"] .dash-cmd-btn,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .dash-cmd-btn,
html.kikoerumanager-dark [data-section="dashboard-archive"] .dash-cmd-btn {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark [data-section="dashboard-hero"] .el-button:hover,
html.kikoerumanager-dark [data-section="dashboard-command"] .el-button:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .el-button:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .el-button:hover,
html.kikoerumanager-dark [data-section="dashboard-hero"] .dash-cmd-btn:hover,
html.kikoerumanager-dark [data-section="dashboard-command"] .dash-cmd-btn:hover,
html.kikoerumanager-dark [data-section="dashboard-tasks"] .dash-cmd-btn:hover,
html.kikoerumanager-dark [data-section="dashboard-archive"] .dash-cmd-btn:hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .app-dd-menu {
  background: var(--km-dark-selected, #17181d) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: 0 24px 54px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .app-dd-item {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .app-dd-item:hover,
html.kikoerumanager-dark .app-dd-item.is-active,
html.kikoerumanager-dark .app-dd-item.is-active:hover {
  background: var(--km-dark-selected-hover, #24252a) !important;
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
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .tasks-toolbar,
html.kikoerumanager-dark .tasks-toolbar-row,
html.kikoerumanager-dark .tasks-toolbar-search,
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
html.kikoerumanager-dark .library-card,
html.kikoerumanager-dark .conflicts-card,
html.kikoerumanager-dark .activity-card {
  background: var(--km-dark-surface) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-detail-header,
html.kikoerumanager-dark .subtitle-info-card-header,
html.kikoerumanager-dark .import-task-list-head,
html.kikoerumanager-dark .workbench-card-head,
html.kikoerumanager-dark .el-table th.el-table__cell {
  background: var(--km-dark-surface-soft) !important;
  background-image: none !important;
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
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04) !important;
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
html.kikoerumanager-dark .app-dd-badge {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.9) 100%) !important;
  border-color: var(--km-dark-border) !important;
  color: #cbd5e1 !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .lib-chip-success,
html.kikoerumanager-dark .tone-success,
html.kikoerumanager-dark .tone-emerald,
html.kikoerumanager-dark .app-dd-badge.tone-emerald {
  background: linear-gradient(180deg, rgba(16, 185, 129, 0.2) 0%, rgba(6, 78, 59, 0.72) 100%) !important;
  border-color: rgba(110, 231, 183, 0.32) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark .lib-chip-warning,
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
html.kikoerumanager-dark .asmr-sync-page section,
html.kikoerumanager-dark .sync-card,
html.kikoerumanager-dark .sync-panel,
html.kikoerumanager-dark .download-card,
html.kikoerumanager-dark .task-detail-pane,
html.kikoerumanager-dark .task-list-pane {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .metric-strip-head,
html.kikoerumanager-dark .metric-strip-row,
html.kikoerumanager-dark .sync-stat-row,
html.kikoerumanager-dark .task-detail-header,
html.kikoerumanager-dark .task-list-header {
  background: var(--km-dark-surface-2) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .metric-cell:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .tasks-page .task-list-pane,
html.kikoerumanager-dark .tasks-page .task-detail-pane,
html.kikoerumanager-dark .tasks-page .detail-scroll,
html.kikoerumanager-dark .tasks-page .bg-white,
html.kikoerumanager-dark .tasks-page .bg-white\/95 {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .tasks-page .task-card,
html.kikoerumanager-dark .tasks-page .bg-slate-50,
html.kikoerumanager-dark .tasks-page .bg-slate-100 {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .tasks-page .task-card:hover,
html.kikoerumanager-dark .tasks-page .task-card.is-active,
html.kikoerumanager-dark .tasks-page .hover\:bg-slate-50:hover,
html.kikoerumanager-dark .tasks-page .hover\:bg-slate-100:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .tasks-page .border-slate-100,
html.kikoerumanager-dark .tasks-page .border-slate-200,
html.kikoerumanager-dark .tasks-page .border-slate-200\/90 {
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll,
html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll > header,
html.kikoerumanager-dark .tasks-page .task-file-tree-card,
html.kikoerumanager-dark .tasks-page .task-file-tree,
html.kikoerumanager-dark .tasks-page .tree-row {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll section,
html.kikoerumanager-dark .tasks-page .tasks-main > .detail-scroll .mx-4,
html.kikoerumanager-dark .tasks-page .task-file-tree-row {
  background: transparent !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .tasks-page .task-file-tree-card::before {
  background: linear-gradient(180deg, var(--km-dark-sidebar) 0%, rgba(10, 11, 16, 0)) !important;
}

html.kikoerumanager-dark .tasks-page .task-file-tree-card::after {
  background: linear-gradient(0deg, var(--km-dark-sidebar) 0%, rgba(10, 11, 16, 0)) !important;
}

html.kikoerumanager-dark .tasks-page .tree-row:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .tasks-page .rounded-\[8px\],
html.kikoerumanager-dark .tasks-page .rounded-\[10px\],
html.kikoerumanager-dark .tasks-page .rounded-\[12px\] {
  border-color: var(--km-dark-border) !important;
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
  background: var(--km-dark-panel) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .conflicts-empty {
  border-style: dashed !important;
  border-color: rgba(147, 197, 253, 0.28) !important;
}

html.kikoerumanager-dark .conflicts-list-header,
html.kikoerumanager-dark .conflicts-detail-header,
html.kikoerumanager-dark .conflicts-segmented {
  background: transparent !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
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
  background: var(--km-dark-matte) !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .conflicts-segmented-item:hover,
html.kikoerumanager-dark .conflicts-segmented-item.is-active,
html.kikoerumanager-dark .conflicts-mini-btn:hover,
html.kikoerumanager-dark .conflicts-mini-btn.is-active,
html.kikoerumanager-dark .conflicts-refresh-btn:hover {
  background: var(--km-dark-selected) !important;
  background-image: none !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .conflicts-list-card {
  background: rgba(15, 23, 42, 0.42) !important;
  border-color: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .conflicts-list-card:hover,
html.kikoerumanager-dark .conflicts-list-card.is-selected,
html.kikoerumanager-dark .conflicts-list-card.is-active {
  background: var(--km-dark-selected) !important;
  background-image: none !important;
  border-color: var(--km-dark-selected-border) !important;
  box-shadow: none !important;
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
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 22px 58px rgba(0, 0, 0, 0.52), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .library .lib-card-header,
html.kikoerumanager-dark .library .lib-toolbar,
html.kikoerumanager-dark .library .path-toolbar,
html.kikoerumanager-dark .library .pagination-wrap {
  background: var(--km-dark-field) !important;
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
html.kikoerumanager-dark .library .lib-btn-icon-tinted,
html.kikoerumanager-dark .library .lib-action-btn {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .library .lib-btn:hover,
html.kikoerumanager-dark .library .lib-btn-ghost:hover,
html.kikoerumanager-dark .library .lib-btn-icon-tinted:hover,
html.kikoerumanager-dark .library .lib-action-btn:hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .library .lib-btn-icon-tinted {
  background: rgba(27, 28, 33, 0.82) !important;
  border-color: rgba(255, 255, 255, 0.075) !important;
  color: rgba(236, 236, 241, 0.86) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-btn-icon-tinted:hover:not(:disabled) {
  background: rgba(34, 35, 41, 0.9) !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  color: rgba(250, 250, 252, 0.94) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .el-table th.el-table__cell {
  background: var(--km-dark-surface-2) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .el-table td.el-table__cell {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .el-table__row:nth-child(odd),
html.kikoerumanager-dark .library .el-table__row:nth-child(odd) td.el-table__cell {
  background: var(--km-dark-field) !important;
}

html.kikoerumanager-dark .library .el-table__row:nth-child(even),
html.kikoerumanager-dark .library .el-table__row:nth-child(even) td.el-table__cell {
  background: var(--km-dark-surface) !important;
}

html.kikoerumanager-dark .library .lib-file-table {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .library .lib-file-table-head,
html.kikoerumanager-dark .library .lib-file-table-header-row {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .library .lib-file-table-body,
html.kikoerumanager-dark .library .lib-file-table-row {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .lib-file-table-row:hover,
html.kikoerumanager-dark .library .lib-file-table-row.is-hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
}

html.kikoerumanager-dark .library .lib-file-table-row.library-row-marquee-selected {
  background: rgba(255, 255, 255, 0.16) !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-file-table-row.library-row-marquee-selected:hover {
  background: rgba(255, 255, 255, 0.22) !important;
  border-color: rgba(255, 255, 255, 0.32) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-file-table-row.library-row-context-active {
  background: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-file-table-row.library-row-drag-source {
  background: rgba(255, 255, 255, 0.1) !important;
  opacity: 0.78;
}

html.kikoerumanager-dark .library .lib-table-marquee-box {
  border: 1px solid rgba(255, 255, 255, 0.88) !important;
  background: rgba(255, 255, 255, 0.16) !important;
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.22),
    0 0 0 1px rgba(255, 255, 255, 0.18),
    0 10px 28px rgba(0, 0, 0, 0.36) !important;
}

html.kikoerumanager-dark .library .lib-batch-bar {
  background: rgba(24, 24, 28, 0.98) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .library .lib-batch-count-pill {
  background: rgba(255, 255, 255, 0.16) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .library .lib-batch-count-pill b {
  color: #ffffff !important;
}

html.kikoerumanager-dark .library .lib-file-th {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .file-icon.icon-dir,
html.kikoerumanager-dark .library .file-icon.icon-folder {
  color: #f6b73c !important;
  fill: currentColor;
  stroke: currentColor;
}

html.kikoerumanager-dark .library .file-icon.icon-audio-lossless { color: #2563eb !important; }
html.kikoerumanager-dark .library .file-icon.icon-audio { color: #7c3aed !important; }
html.kikoerumanager-dark .library .file-icon.icon-image { color: #f97316 !important; }
html.kikoerumanager-dark .library .file-icon.icon-video { color: #6366f1 !important; }
html.kikoerumanager-dark .library .file-icon.icon-pdf { color: #dc2626 !important; }
html.kikoerumanager-dark .library .file-icon.icon-archive { color: #d97706 !important; }
html.kikoerumanager-dark .library .file-icon.icon-text { color: #64748b !important; }
html.kikoerumanager-dark .library .file-icon.icon-file { color: #94a3b8 !important; }

html.kikoerumanager-dark .library .library-search-mark {
  background: rgba(245, 158, 11, 0.28) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .library .el-pagination button,
html.kikoerumanager-dark .library .el-pagination .el-pager li,
html.kikoerumanager-dark .library .el-pagination .el-input__wrapper {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .library .el-pagination .el-pager li.is-active {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar,
html.kikoerumanager-dark .library .lib-batch-bar {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-btn,
html.kikoerumanager-dark .library .lib-path-toolbar .lib-btn-ghost {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-btn-icon-tinted {
  background: rgba(27, 28, 33, 0.78) !important;
  border-color: rgba(255, 255, 255, 0.07) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-btn-icon-tinted:hover:not(:disabled) {
  background: rgba(34, 35, 41, 0.88) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-label,
html.kikoerumanager-dark .library .lib-batch-info {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .lib-path-code,
html.kikoerumanager-dark .library .lib-batch-count-pill {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .library .lib-batch-bar {
  background: rgba(24, 24, 28, 0.98) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.48),
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 0 0 1px rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .library .lib-batch-count-pill {
  background: rgba(255, 255, 255, 0.16) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .library .lib-batch-count-pill b {
  color: #ffffff !important;
}

html.kikoerumanager-dark .library .lib-scope-switch {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .library .lib-scope-option {
  background: transparent !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .library .lib-scope-option:hover,
html.kikoerumanager-dark .library .lib-scope-option.is-active {
  background: var(--km-dark-surface-hover) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-scope-switch {
  background: #202126 !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-scope-option {
  background: transparent !important;
  color: rgba(205, 205, 211, 0.62) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-scope-option:hover:not(.is-active) {
  background: #3334 !important;
  color: rgba(238, 238, 242, 0.84) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-scope-option.is-active {
  background: #5556 !important;
  color: rgba(255, 255, 255, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .library .lib-path-toolbar .lib-scope-option.is-active::after {
  display: none !important;
  content: none !important;
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
  background: var(--km-dark-field) !important;
  border: 1px solid var(--km-dark-border) !important;
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
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 24px 54px rgba(0, 0, 0, 0.52), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-header span {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item {
  background: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark [data-library-row-menu="1"] .menu-item:hover:not(:disabled) {
  background: var(--km-dark-surface-hover) !important;
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

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .window,
html.kikoerumanager-dark .server-upload-preview-modal .window,
html.kikoerumanager-dark .lib-move-modal .window,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .glass-shell,
html.kikoerumanager-dark .server-upload-preview-modal .glass-shell,
html.kikoerumanager-dark .lib-move-modal .glass-shell {
  background: var(--km-dark-sidebar) !important;
  border: 1px solid var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 70px rgba(0, 0, 0, 0.56), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .window-header,
html.kikoerumanager-dark .server-upload-preview-modal .window-header,
html.kikoerumanager-dark .lib-move-modal .window-header,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .footer-row,
html.kikoerumanager-dark .server-upload-preview-modal .footer-row,
html.kikoerumanager-dark .lib-move-modal .footer-row,
html.kikoerumanager-dark .lib-move-modal .explorer-toolbar {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .title,
html.kikoerumanager-dark .server-upload-preview-modal .title,
html.kikoerumanager-dark .lib-move-modal .title,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) h1,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) h2,
html.kikoerumanager-dark .server-upload-preview-modal h1,
html.kikoerumanager-dark .server-upload-preview-modal h2,
html.kikoerumanager-dark .lib-move-modal h1,
html.kikoerumanager-dark .lib-move-modal h2 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) p,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) label,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .summary,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .target-path,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tree-size,
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

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .glass-panel,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .glass-card,
html.kikoerumanager-dark .server-upload-preview-modal .glass-panel,
html.kikoerumanager-dark .server-upload-preview-modal .glass-card,
html.kikoerumanager-dark .lib-move-modal .glass-panel,
html.kikoerumanager-dark .lib-move-modal .glass-card,
html.kikoerumanager-dark .lib-move-modal .path-bar,
html.kikoerumanager-dark .lib-move-modal .nav-pane,
html.kikoerumanager-dark .lib-move-modal .file-list,
html.kikoerumanager-dark .lib-move-modal .content-pane {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .field-input,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .select-button,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .picker-button,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .dropdown-panel,
html.kikoerumanager-dark .server-upload-preview-modal .field-input,
html.kikoerumanager-dark .server-upload-preview-modal .select-button,
html.kikoerumanager-dark .server-upload-preview-modal .picker-button,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-panel,
html.kikoerumanager-dark .lib-move-modal .search-input,
html.kikoerumanager-dark .lib-move-modal .crumb-btn,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .dropdown-item,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .dropdown-item:hover,
html.kikoerumanager-dark .server-upload-preview-modal .dropdown-item:hover,
html.kikoerumanager-dark .lib-move-modal .crumb-btn:hover,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn:hover:not(:disabled) {
  background: var(--km-dark-surface-hover) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tree-row,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row,
html.kikoerumanager-dark .lib-move-modal .tree-row,
html.kikoerumanager-dark .lib-move-modal .file-row {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tree-row:hover,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row:hover,
html.kikoerumanager-dark .lib-move-modal .tree-row:hover,
html.kikoerumanager-dark .lib-move-modal .file-row:hover {
  background: var(--km-dark-surface-hover) !important;
}

html.kikoerumanager-dark .lib-move-modal .nav-item,
html.kikoerumanager-dark .lib-move-modal .nav-item:hover {
  background: transparent !important;
  color: inherit !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tree-row-selected,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected,
html.kikoerumanager-dark .lib-move-modal .tree-row-selected {
  background: rgba(255, 255, 255, 0.16) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tab-chip,
html.kikoerumanager-dark .server-upload-preview-modal .tab-chip {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tab-chip-active,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tab-chip-partial,
html.kikoerumanager-dark .server-upload-preview-modal .tab-chip-active,
html.kikoerumanager-dark .server-upload-preview-modal .tab-chip-partial {
  background: rgba(255, 255, 255, 0.16) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .tree-name,
html.kikoerumanager-dark .server-upload-preview-modal .tree-name,
html.kikoerumanager-dark .lib-move-modal .tree-name,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .summary-strong,
html.kikoerumanager-dark .server-upload-preview-modal .summary-strong {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .secondary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .secondary-cta,
html.kikoerumanager-dark .lib-move-modal .secondary-cta,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .interactive-chip,
html.kikoerumanager-dark .server-upload-preview-modal .interactive-chip,
html.kikoerumanager-dark .lib-move-modal .interactive-chip {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-shell {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-header {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-body {
  --tw-gradient-from: var(--km-dark-bg) var(--tw-gradient-from-position) !important;
  --tw-gradient-via: var(--km-dark-bg) var(--tw-gradient-via-position) !important;
  --tw-gradient-to: var(--km-dark-bg) var(--tw-gradient-to-position) !important;
  background-color: var(--km-dark-bg) !important;
  background-image: none !important;
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
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog :is(
  aside,
  .rounded-\[20px\],
  .rounded-\[18px\],
  .rounded-\[16px\],
  .rounded-\[14px\],
  .rounded-\[12px\],
  .settings-card,
  .config-section,
  .subtitle-info-card,
  .subtitle-candidate-card,
  .import-task-list-card,
  .import-task-detail,
  .import-task-row
) {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog :is(
  .rounded-\[10px\],
  .rounded-\[8px\],
  .app-dd-badge,
  .lib-chip,
  .set-chip,
  .task-status-pill,
  .toolbar-pill
) {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-100,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200\/70,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-200\/80,
html.kikoerumanager-dark .subtitle-workbench-dialog .border-slate-300 {
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog button:not(.primary-cta),
html.kikoerumanager-dark .subtitle-workbench-btn {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog button:not(.primary-cta):hover,
html.kikoerumanager-dark .subtitle-workbench-btn:hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog :is(button, input, textarea, [tabindex]):focus,
html.kikoerumanager-dark .subtitle-workbench-dialog :is(button, input, textarea, [tabindex]):focus-visible {
  outline: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-overview {
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-filter {
  height: 32px !important;
  min-height: 0 !important;
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(244, 244, 245, 0.86) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-filter:hover {
  background: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-filter.is-active {
  background: #34353a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.26) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-filter:focus,
html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-queue-filter:focus-visible {
  outline: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .bg-slate-900,
html.kikoerumanager-dark .subtitle-workbench-dialog .stage-tab-active,
html.kikoerumanager-dark .subtitle-workbench-dialog .is-active {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-filter-row.active,
  .subtitle-naming-option.active,
  .subtitle-toggle-pill.active
) {
  background: #56575e !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.42) !important;
  color: #ffffff !important;
  outline: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-filter-add-btn,
  .subtitle-filter-delete-btn,
  .subtitle-filter-editor-toggle,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn
) {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-filter-add-btn,
  .subtitle-filter-delete-btn,
  .subtitle-filter-editor-toggle,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn
):hover {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog :is(
  .bg-blue-50,
  .bg-sky-50,
  .bg-indigo-50,
  .bg-violet-50,
  .bg-blue-100,
  .bg-sky-100,
  .bg-indigo-100,
  .bg-violet-100,
  [class*="from-blue-"],
  [class*="to-blue-"],
  [class*="from-sky-"],
  [class*="to-sky-"],
  [class*="from-indigo-"],
  [class*="to-indigo-"]
) {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog :is(
  button:not(.primary-cta).is-active,
  button:not(.primary-cta)[class*="bg-slate-900"],
  button:not(.primary-cta)[class*="bg-blue-"],
  button:not(.primary-cta)[class*="bg-indigo-"]
) {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card button.subtitle-filter-row.active,
html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card button.subtitle-naming-option.active,
html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card button.subtitle-toggle-pill.active {
  background: #56575e !important;
  background-color: #56575e !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.42) !important;
  color: #ffffff !important;
  outline: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-naming-option,
html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-naming-option span {
  white-space: nowrap !important;
}

html.kikoerumanager-dark .subtitle-workbench-dialog input,
html.kikoerumanager-dark .subtitle-workbench-dialog textarea {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .floating-card,
html.kikoerumanager-dark .filter-delete-floating-card {
  background:
    linear-gradient(180deg, rgba(45, 46, 51, 0.72), rgba(13, 14, 18, 0.88)),
    rgba(18, 19, 23, 0.86) !important;
  background-image:
    linear-gradient(180deg, rgba(45, 46, 51, 0.72), rgba(13, 14, 18, 0.88)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(14px) saturate(106%) !important;
  -webkit-backdrop-filter: blur(14px) saturate(106%) !important;
}

html.kikoerumanager-dark .floating-card .text-slate-900,
html.kikoerumanager-dark .floating-card .upload-floating-title,
html.kikoerumanager-dark .floating-chip b,
html.kikoerumanager-dark .floating-card .floating-chip b,
html.kikoerumanager-dark .floating-card .floating-progress-percent,
html.kikoerumanager-dark .filter-delete-floating-title,
html.kikoerumanager-dark .filter-delete-floating-percent {
  color: #ffffff !important;
}

html.kikoerumanager-dark .floating-card .floating-hero-lottie,
html.kikoerumanager-dark .floating-card .floating-hero-static-icon {
  color: #ffffff !important;
  filter: brightness(0) invert(1) !important;
}

html.kikoerumanager-dark .floating-card .floating-progress-lottie-progress {
  opacity: 0 !important;
}

html.kikoerumanager-dark .floating-card .floating-progress-percent {
  background:
    radial-gradient(circle, rgba(18, 19, 23, 0.94) 0 46%, transparent 47%),
    conic-gradient(#ffffff var(--floating-progress, 0%), rgba(255, 255, 255, 0.22) 0);
  color: #ffffff !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
}

html.kikoerumanager-dark .floating-card .text-slate-500,
html.kikoerumanager-dark .floating-card .text-slate-400,
html.kikoerumanager-dark .floating-card .floating-detail-box,
html.kikoerumanager-dark .filter-delete-floating-mode {
  color: rgba(214, 214, 220, 0.68) !important;
}

html.kikoerumanager-dark .floating-card .bg-slate-50,
html.kikoerumanager-dark .floating-chip,
html.kikoerumanager-dark .floating-chip-title,
html.kikoerumanager-dark .floating-detail-box,
html.kikoerumanager-dark .floating-percent-badge,
html.kikoerumanager-dark .filter-delete-floating-path,
html.kikoerumanager-dark .filter-delete-floating-card [class*="bg-slate-50"] {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.84) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .floating-action-btn {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .floating-action-btn:hover {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .floating-card .floating-action-btn-primary,
html.kikoerumanager-dark .floating-card .floating-action-btn-emerald,
html.kikoerumanager-dark .floating-card .floating-action-btn-violet,
html.kikoerumanager-dark .floating-card .floating-action-btn-amber,
html.kikoerumanager-dark .floating-card .floating-action-btn-rose {
  background: #3a3b40 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .floating-card .floating-action-btn-primary:hover,
html.kikoerumanager-dark .floating-card .floating-action-btn-emerald:hover,
html.kikoerumanager-dark .floating-card .floating-action-btn-violet:hover,
html.kikoerumanager-dark .floating-card .floating-action-btn-amber:hover,
html.kikoerumanager-dark .floating-card .floating-action-btn-rose:hover {
  background: #45464b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .sp-shell > div {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 24px 58px rgba(0, 0, 0, 0.56), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .sp-shell > div > div {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .sp-shell h3,
html.kikoerumanager-dark .sp-shell .text-slate-900,
html.kikoerumanager-dark .sp-shell .text-slate-800 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .sp-shell .text-slate-600,
html.kikoerumanager-dark .sp-shell .text-slate-500,
html.kikoerumanager-dark .sp-shell .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .sp-shell .bg-slate-50,
html.kikoerumanager-dark .sp-shell .bg-slate-100 {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .sp-shell input,
html.kikoerumanager-dark .sp-shell textarea {
  background: var(--km-dark-field) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-text) !important;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    0 0 0 3px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .sp-shell input:focus,
html.kikoerumanager-dark .sp-shell textarea:focus {
  background: #090a0f !important;
  border-color: rgba(255, 255, 255, 0.42) !important;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.12),
    0 0 0 3px rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .sp-shell button:not([class*="bg-rose"]):not([class*="bg-red"]):not([class*="bg-emerald"]) {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .sp-shell button:not([class*="bg-rose"]):not([class*="bg-red"]):not([class*="bg-emerald"]):hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .sp-shell button[class*="bg-slate-900"],
html.kikoerumanager-dark .sp-shell button[class*="bg-blue-"],
html.kikoerumanager-dark .sp-shell button[class*="bg-indigo-"] {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 26px rgba(0, 0, 0, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.16) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog).el-dialog,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .window,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .glass-shell,
html.kikoerumanager-dark .mojibake-preview-dialog.el-dialog,
html.kikoerumanager-dark .mojibake-preview-dialog .window,
html.kikoerumanager-dark .mojibake-preview-dialog .glass-shell {
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .window-header,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-body,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .toolbar-row,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-head,
html.kikoerumanager-dark .mojibake-preview-dialog .window-header,
html.kikoerumanager-dark .mojibake-preview-dialog .fm-body,
html.kikoerumanager-dark .mojibake-preview-dialog .toolbar-row,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-footer {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .glass-panel,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .glass-card,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-panel,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-scroll,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .selection-card,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .search-shell,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-badge,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-count-pill,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-body,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-card,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-empty,
html.kikoerumanager-dark .mojibake-preview-dialog .fm-badge,
html.kikoerumanager-dark .mojibake-preview-dialog .fm-count-pill {
  background: #1d1e23 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row:hover,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row-selected,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-card:hover {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .action-card,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .close-button,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .row-action,
html.kikoerumanager-dark .mojibake-preview-dialog .action-card,
html.kikoerumanager-dark .mojibake-preview-dialog .close-button {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .action-card:hover:not(:disabled),
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .close-button:hover,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .row-action:hover:not(:disabled),
html.kikoerumanager-dark .mojibake-preview-dialog .action-card:hover:not(:disabled),
html.kikoerumanager-dark .mojibake-preview-dialog .close-button:hover {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .title,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-900,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-800,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-700,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-name,
html.kikoerumanager-dark .mojibake-preview-dialog .title,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-value {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-600,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-500,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .text-slate-400,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-sub,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-size,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-time,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .preview-empty,
html.kikoerumanager-dark .mojibake-preview-dialog .text-slate-600,
html.kikoerumanager-dark .mojibake-preview-dialog .text-slate-500,
html.kikoerumanager-dark .mojibake-preview-dialog .text-slate-400,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-label,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-path,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-encoding {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .search-input,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-input {
  background: transparent !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox {
  background: #24252a !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-on,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-partial,
html.kikoerumanager-dark .mojibake-preview-dialog .tree-checkbox-on {
  background: #56575e !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog.el-dialog,
html.kikoerumanager-dark .filter-delete-dialog .window,
html.kikoerumanager-dark .filter-delete-dialog .glass-shell {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 70px rgba(0, 0, 0, 0.56), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .window-header,
html.kikoerumanager-dark .filter-delete-dialog .fm-body,
html.kikoerumanager-dark .filter-delete-dialog .toolbar-row,
html.kikoerumanager-dark .filter-delete-dialog .tree-head,
html.kikoerumanager-dark .filter-delete-dialog .window > .flex.items-center.justify-end {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .glass-panel,
html.kikoerumanager-dark .filter-delete-dialog .glass-card,
html.kikoerumanager-dark .filter-delete-dialog .tree-panel,
html.kikoerumanager-dark .filter-delete-dialog .tree-scroll,
html.kikoerumanager-dark .filter-delete-dialog .tree-row,
html.kikoerumanager-dark .filter-delete-dialog .selection-card,
html.kikoerumanager-dark .filter-delete-dialog .search-shell,
html.kikoerumanager-dark .filter-delete-dialog .fd-chip,
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row:hover,
html.kikoerumanager-dark .filter-delete-dialog .tree-row-selected,
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag-active,
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag-partial {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"],
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-slate-50"] {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: var(--km-dark-shadow-soft) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"]:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-slate-50"]:hover:not(:disabled) {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .title,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-900,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-800,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-700,
html.kikoerumanager-dark .filter-delete-dialog .tree-name {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .text-slate-600,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-500,
html.kikoerumanager-dark .filter-delete-dialog .text-slate-400,
html.kikoerumanager-dark .filter-delete-dialog .tree-sub,
html.kikoerumanager-dark .filter-delete-dialog .tree-size,
html.kikoerumanager-dark .filter-delete-dialog .tree-time,
html.kikoerumanager-dark .filter-delete-dialog .fd-progress,
html.kikoerumanager-dark .filter-delete-dialog .preview-empty {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .search-input {
  background: transparent !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .floating-action-btn-emerald,
html.kikoerumanager-dark .floating-action-btn-primary,
html.kikoerumanager-dark .floating-action-btn-violet,
html.kikoerumanager-dark .floating-action-btn-amber,
html.kikoerumanager-dark .floating-action-btn-rose {
  background: #3a3b40 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .custom-preview-overlay:has(.filter-delete-dialog) {
  background: transparent !important;
  background-image: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .window,
html.kikoerumanager-dark .filter-delete-dialog .glass-shell {
  background:
    linear-gradient(180deg, rgba(45, 46, 51, 0.76), rgba(13, 14, 18, 0.9)),
    rgba(18, 19, 23, 0.86) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .glass-shell::before {
  display: none !important;
  content: none !important;
  background: none !important;
  opacity: 0 !important;
}

html.kikoerumanager-dark .filter-delete-dialog .window-header,
html.kikoerumanager-dark .filter-delete-dialog .fm-body,
html.kikoerumanager-dark .filter-delete-dialog .toolbar-row,
html.kikoerumanager-dark .filter-delete-dialog .tree-head,
html.kikoerumanager-dark .filter-delete-dialog .footer-row,
html.kikoerumanager-dark .filter-delete-dialog [class*="border-t"][class*="bg-slate-50"] {
  background: rgba(20, 21, 25, 0.66) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .fm-body {
  background: rgba(20, 21, 25, 0.48) !important;
  background-image: none !important;
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
  background: #3a3b40 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: rgba(250, 250, 252, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-alert--error {
  background: rgba(70, 42, 46, 0.72) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: rgba(255, 228, 230, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-alert__title,
html.kikoerumanager-dark .filter-delete-dialog .el-alert__description {
  color: inherit !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-alert__icon {
  color: currentColor !important;
  filter: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .fd-chip,
html.kikoerumanager-dark .filter-delete-dialog .fm-badge,
html.kikoerumanager-dark .filter-delete-dialog .selection-card {
  background:
    linear-gradient(180deg, rgba(52, 53, 58, 0.28), rgba(18, 19, 23, 0.42)),
    rgba(20, 21, 25, 0.74) !important;
  background-image:
    linear-gradient(180deg, rgba(52, 53, 58, 0.28), rgba(18, 19, 23, 0.42)) !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(10px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(112%) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card,
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag,
html.kikoerumanager-dark .filter-delete-dialog .close-button,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"] {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog .fd-type-tag:hover:not(:disabled),
html.kikoerumanager-dark .filter-delete-dialog .close-button:hover,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-white"]:hover:not(:disabled) {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card-danger,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-rose-600"] {
  background: #3a3b40 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: rgba(250, 250, 252, 0.72) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .action-card-primary,
html.kikoerumanager-dark .filter-delete-dialog button[class*="bg-indigo-600"] {
  background: #3a3b40 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .search-shell,
html.kikoerumanager-dark .filter-delete-dialog .search-input {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .search-input::placeholder {
  color: rgba(214, 214, 220, 0.5) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-panel,
html.kikoerumanager-dark .filter-delete-dialog .glass-panel,
html.kikoerumanager-dark .filter-delete-dialog .glass-card,
html.kikoerumanager-dark .filter-delete-dialog .tree-scroll {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.36), rgba(18, 19, 23, 0.52)),
    rgba(22, 23, 27, 0.72) !important;
  background-image:
    linear-gradient(180deg, rgba(48, 49, 54, 0.36), rgba(18, 19, 23, 0.52)) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(12px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(12px) saturate(108%) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(226, 232, 240, 0.82) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row:hover {
  background: transparent !important;
  border-color: transparent !important;
  color: rgba(250, 250, 252, 0.94) !important;
  transform: translate3d(0, -2px, 0) !important;
  box-shadow:
    0 8px 18px rgba(0, 0, 0, 0.22),
    inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-row-selected {
  background: #3a3b40 !important;
  background-image: none !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.12) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox {
  background: #2b2c30 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
}

html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox-on,
html.kikoerumanager-dark .filter-delete-dialog .tree-checkbox-partial {
  background: #3a3b40 !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-progress-bar__outer {
  background: #2b2c30 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-progress-bar__inner {
  background: #5a5b60 !important;
  background-image: none !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .filter-delete-dialog .el-progress-bar__inner::after {
  display: none !important;
  content: none !important;
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
html.kikoerumanager-dark .server-upload-preview-modal .window {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)),
    rgba(20, 21, 25, 0.88) !important;
  background-image:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .lib-move-modal .window {
  background:
    linear-gradient(180deg, rgba(29, 30, 35, 0.96), rgba(14, 15, 18, 0.98)),
    #111216 !important;
  background-image:
    linear-gradient(180deg, rgba(29, 30, 35, 0.96), rgba(14, 15, 18, 0.98)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .window-header,
html.kikoerumanager-dark .remote-folder-picker-modal .explorer-toolbar,
html.kikoerumanager-dark .remote-folder-picker-modal .footer-row,
html.kikoerumanager-dark .server-upload-preview-modal .window-header,
html.kikoerumanager-dark .server-upload-preview-modal .footer-row {
  background: rgba(24, 25, 29, 0.58) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .window-header,
html.kikoerumanager-dark .lib-move-modal .explorer-toolbar,
html.kikoerumanager-dark .lib-move-modal .footer-row {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
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
html.kikoerumanager-dark .server-upload-preview-modal .tree-scroll {
  background: transparent !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .explorer-list,
html.kikoerumanager-dark .lib-move-modal .fm-body {
  background: #15161a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .explorer-main,
html.kikoerumanager-dark .lib-move-modal .explorer-nav {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .explorer-nav {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-head,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-section-title,
html.kikoerumanager-dark .server-upload-preview-modal .section-head {
  background: rgba(20, 21, 25, 0.46) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text-muted) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .fm-head,
html.kikoerumanager-dark .lib-move-modal .nav-section-title {
  background: transparent !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(214, 214, 220, 0.68) !important;
  box-shadow: none !important;
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
html.kikoerumanager-dark .server-upload-preview-modal .target-path {
  background: rgba(43, 44, 48, 0.84) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .path-bar,
html.kikoerumanager-dark .lib-move-modal .search-input,
html.kikoerumanager-dark .lib-move-modal .crumb-btn,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn,
html.kikoerumanager-dark .lib-move-modal .target-chip,
html.kikoerumanager-dark .lib-move-modal .rel-chip {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .search-input::placeholder,
html.kikoerumanager-dark .lib-move-modal .search-input::placeholder {
  color: rgba(214, 214, 220, 0.5) !important;
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
html.kikoerumanager-dark .lib-move-modal .crumb-btn:hover,
html.kikoerumanager-dark .lib-move-modal .fm-icon-btn:hover:not(:disabled) {
  background: #2b2c30 !important;
  background-image: none !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .nav-row:hover {
  background: #2b2c30 !important;
  background-image: none !important;
  color: var(--km-dark-text-strong) !important;
  transform: none !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-row-selected,
html.kikoerumanager-dark .remote-folder-picker-modal .nav-row-active,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected {
  background: rgba(255, 255, 255, 0.16) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow:
    inset 3px 0 0 rgba(255, 255, 255, 0.78),
    inset 0 0 0 1px rgba(255, 255, 255, 0.14) !important;
}

html.kikoerumanager-dark .lib-move-modal .fm-row-selected,
html.kikoerumanager-dark .lib-move-modal .fm-row-selected:hover,
html.kikoerumanager-dark .lib-move-modal .nav-row-active,
html.kikoerumanager-dark .lib-move-modal .nav-row-active:hover,
html.kikoerumanager-dark .lib-move-modal .fm-row-selected.fm-row-self {
  background: #333438 !important;
  background-image: none !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
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
  background: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .secondary-cta,
html.kikoerumanager-dark .remote-folder-picker-modal .interactive-chip,
html.kikoerumanager-dark .server-upload-preview-modal .secondary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .interactive-chip,
html.kikoerumanager-dark .lib-move-modal .secondary-cta,
html.kikoerumanager-dark .lib-move-modal .interactive-chip {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .primary-cta,
html.kikoerumanager-dark .server-upload-preview-modal .primary-cta {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: #111116 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-move-modal .primary-cta {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: #111116 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-info-strip,
html.kikoerumanager-dark .subtitle-page .subtitle-shell,
html.kikoerumanager-dark .subtitle-page .subtitle-list-pane,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-pane {
  background: #15161b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-info-strip {
  background: #18191f !important;
  background-image: none !important;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented,
html.kikoerumanager-dark .subtitle-page .subtitle-list-header,
html.kikoerumanager-dark .subtitle-page .subtitle-detail-header,
html.kikoerumanager-dark .subtitle-page .subtitle-info-card,
html.kikoerumanager-dark .subtitle-page .subtitle-candidate-card,
html.kikoerumanager-dark .subtitle-page .subtitle-list-card {
  background: #1c1d22 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented-item,
html.kikoerumanager-dark .subtitle-page .subtitle-action-btn,
html.kikoerumanager-dark .subtitle-page .subtitle-mini-btn {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #e7e7eb !important;
}

html.kikoerumanager-dark .subtitle-page .subtitle-segmented-item.is-active,
html.kikoerumanager-dark .subtitle-page .subtitle-action-btn.is-primary {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: #111116 !important;
  box-shadow: none !important;
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
  background: rgba(245, 158, 11, 0.16) !important;
  background-image: none !important;
  border-color: rgba(245, 158, 11, 0.42) !important;
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
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-header {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .subtitle-workbench-body {
  --tw-gradient-from: var(--km-dark-bg) var(--tw-gradient-from-position) !important;
  --tw-gradient-via: var(--km-dark-bg) var(--tw-gradient-via-position) !important;
  --tw-gradient-to: var(--km-dark-bg) var(--tw-gradient-to-position) !important;
  background-color: var(--km-dark-bg) !important;
  background-image: none !important;
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
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-100,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200\/70,
html.kikoerumanager-dark .subtitle-import-workbench-dialog .border-slate-200\/80 {
  border-color: var(--km-dark-border) !important;
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
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
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
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .import-workbench-modal {
  background: var(--km-dark-surface) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-workbench-body,
html.kikoerumanager-dark .import-workbench-modal .bg-gradient-to-b {
  background: var(--km-dark-bg) !important;
  background-image: none !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal section,
html.kikoerumanager-dark .import-workbench-modal aside,
html.kikoerumanager-dark .import-workbench-modal article,
html.kikoerumanager-dark .import-workbench-modal .grid,
html.kikoerumanager-dark .import-workbench-modal .min-w-0,
html.kikoerumanager-dark .import-workbench-modal .min-h-0 {
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .import-workbench-modal .rounded-\[20px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[18px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[14px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-\[12px\],
html.kikoerumanager-dark .import-workbench-modal .rounded-xl {
  border-color: var(--km-dark-border) !important;
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
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .bg-slate-900,
html.kikoerumanager-dark .import-workbench-modal .is-active {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
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
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .import-workbench-modal .shadow-\[0_4px_16px_rgba\(15\,23\,42\,0\.04\)\],
html.kikoerumanager-dark .import-workbench-modal .shadow-\[0_20px_60px_rgba\(15\,23\,42\,0\.1\)\] {
  box-shadow: none !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-config-card,
html.kikoerumanager-dark .import-workbench-modal .subtitle-option-stack,
html.kikoerumanager-dark .import-workbench-modal .subtitle-settings-block,
html.kikoerumanager-dark .import-workbench-modal .subtitle-setting-item,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-editor,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-detail,
html.kikoerumanager-dark .import-workbench-modal .search-row {
  background: var(--km-dark-surface) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-help-card-danger {
  background: linear-gradient(180deg, rgba(127, 29, 29, 0.42) 0%, rgba(30, 41, 59, 0.86) 100%) !important;
  border-color: rgba(253, 164, 175, 0.28) !important;
}

html.kikoerumanager-dark .import-workbench-modal .header-badge {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
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
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-switch {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-target-badge,
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-white"],
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-slate-50"] {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option:hover,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill:hover,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row:hover,
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-white"]:hover:not(:disabled),
html.kikoerumanager-dark .import-workbench-modal button[class*="bg-slate-50"]:hover:not(:disabled) {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .import-workbench-modal .subtitle-naming-option.active,
html.kikoerumanager-dark .import-workbench-modal .subtitle-toggle-pill.active,
html.kikoerumanager-dark .import-workbench-modal .subtitle-filter-row.active {
  background: #020617 !important;
  border-color: var(--km-dark-border-strong) !important;
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


html.kikoerumanager-dark body:has(.existing-page),
html.kikoerumanager-dark .main-content:has(.existing-page),
html.kikoerumanager-dark .page-content:has(.existing-page),
html.kikoerumanager-dark .content-area:has(.existing-page) {
  background: var(--km-dark-bg) !important;
}

html.kikoerumanager-dark .existing-page {
  color: var(--ef-text, var(--km-dark-text)) !important;
  background: transparent !important;
}

html.kikoerumanager-dark .existing-page .app-page-header,
html.kikoerumanager-dark .existing-page .app-page-header-inner,
html.kikoerumanager-dark .existing-page .app-page-header-actions {
  background: transparent !important;
  border-color: transparent !important;
  color: var(--ef-text, var(--km-dark-text)) !important;
}

html.kikoerumanager-dark .existing-page .existing-shell {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .existing-page .existing-sidebar,
html.kikoerumanager-dark .existing-page .existing-main {
  background: transparent !important;
}

html.kikoerumanager-dark .existing-page .app-empty-state,
html.kikoerumanager-dark .existing-page .empty-state,
html.kikoerumanager-dark .existing-page [class*="empty"] {
  background: transparent !important;
  color: var(--ef-muted, var(--km-dark-text-muted)) !important;
}

html.kikoerumanager-dark .existing-page .side-ep-action.is-disabled,
html.kikoerumanager-dark .existing-page .card-action:disabled {
  opacity: 0.58 !important;
}

html.kikoerumanager-dark .custom-preview-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .window,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .glass-shell {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 23, 42, 0.94) 100%) !important;
  border: 1px solid rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .window-header,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .tabs-row,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .footer-row {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .glass-card,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .mode-switch,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .content-grid,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .left-column,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .dropdown-panel,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .resource-row,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .preview-card {
  background: rgba(30, 41, 59, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .title,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) h1,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) h2,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) label,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .text-slate-900,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .text-slate-800 {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) p,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .text-slate-600,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .text-slate-500,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.folder-dialog) .text-slate-400 {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .field-input,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) .select-button,
html.kikoerumanager-dark .custom-preview-modal:not(.circle-download-preview-modal):not(.lib-move-modal):not(.filter-delete-dialog):not(.folder-dialog):not(.server-upload-preview-modal):not(.remote-folder-picker-modal) input {
  background: rgba(15, 23, 42, 0.9) !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: var(--km-dark-text-strong) !important;
}

/* 旧设置页暗黑覆盖保留作历史参考，但禁用。设置页现在由 Settings.vue / settings 组件变量接管。 */
@media not all {
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
  background: var(--set-success-bg) !important;
  border-color: var(--set-success-border) !important;
  color: var(--set-success-text) !important;
}

html.kikoerumanager-dark .settings-page .set-chip-warning {
  background: var(--set-warning-bg) !important;
  border-color: var(--set-warning-border) !important;
  color: var(--set-warning-text) !important;
}

html.kikoerumanager-dark .settings-page .set-chip-info,
html.kikoerumanager-dark .settings-page .settings-nav-badge:not(.is-dirty) {
  background: var(--set-tag-info-bg) !important;
  border-color: var(--set-tag-info-border) !important;
  color: var(--set-tag-info-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .settings-nav-badge.is-dirty {
  background: rgba(173, 136, 82, 0.12) !important;
  border-color: rgba(202, 164, 101, 0.3) !important;
  color: #d7ba7d !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page .sidebar-ghost-btn,
html.kikoerumanager-dark .settings-page button:not(.el-switch__core):not(.settings-nav-item):not(.pikpak-account-tab) {
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

}

html.kikoerumanager-dark .settings-page {
  color: var(--set-text, #d4d4d8) !important;
}

html.kikoerumanager-dark .settings-page :is(.settings-workbench, .settings-main, .main-slot) {
  color: var(--set-text, #d4d4d8) !important;
}

html.kikoerumanager-dark .settings-page :is(input, textarea, select, .el-input__wrapper, .el-input__inner, .el-textarea__inner, .el-select__wrapper) {
  --el-input-bg-color: var(--set-field-bg, #1b1b1d) !important;
  --el-input-border-color: var(--set-border, rgba(255, 255, 255, 0.11)) !important;
  --el-input-text-color: var(--set-text-strong, #f5f5f5) !important;
  --el-input-placeholder-color: var(--set-text-subtle, #71717a) !important;
  background-color: var(--set-field-bg, #1b1b1d) !important;
  border-color: var(--set-border, rgba(255, 255, 255, 0.11)) !important;
  color: var(--set-text-strong, #f5f5f5) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .settings-page :is(input, textarea)::placeholder {
  color: var(--set-text-subtle, #71717a) !important;
  -webkit-text-fill-color: var(--set-text-subtle, #71717a) !important;
}

html.kikoerumanager-dark .settings-page :is(input:focus, textarea:focus, .el-input__wrapper.is-focus, .el-select__wrapper.is-focused) {
  border-color: var(--set-border-strong, rgba(255, 255, 255, 0.18)) !important;
  box-shadow: 0 0 0 3px var(--set-accent-soft, rgba(255, 255, 255, 0.08)) !important;
}

html.kikoerumanager-dark .settings-page .el-switch__core {
  background-color: var(--set-surface-muted, #242427) !important;
  border-color: var(--set-border-strong, rgba(255, 255, 255, 0.18)) !important;
}

html.kikoerumanager-dark .settings-page .el-switch.is-checked .el-switch__core {
  background-color: var(--set-accent, #e5e7eb) !important;
  border-color: var(--set-accent, #e5e7eb) !important;
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
html.kikoerumanager-dark .activity-page .page-head-search {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .activity-page .page-head-search-input {
  background: transparent !important;
  background-image: none !important;
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
  background: #0b0c10 !important;
  background-image: none !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-head,
html.kikoerumanager-dark .detail-foot {
  background: #0b0c10 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-close,
html.kikoerumanager-dark .copy-btn,
html.kikoerumanager-dark .panel-toggle,
html.kikoerumanager-dark .foot-btn {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #d7dde7 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .detail-icon {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #d7dde7 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .detail-close:hover,
html.kikoerumanager-dark .copy-btn:hover,
html.kikoerumanager-dark .panel-toggle:hover,
html.kikoerumanager-dark .foot-btn:hover {
  background: #202126 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .foot-btn.primary {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.26) !important;
  color: #111116 !important;
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
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .detail-body .rounded-xl,
html.kikoerumanager-dark .detail-body .inline-flex {
  background-color: #17181d !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .detail-body .child-item {
  background: #17181d !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .detail-body .child-item:hover,
html.kikoerumanager-dark .detail-body .child-item.is-expanded {
  background: #202126 !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
}

html.kikoerumanager-dark .detail-body .raw-json-wrap {
  background: #08090c !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .detail-body .raw-json {
  color: #d7dde7 !important;
}

html.kikoerumanager-dark .detail-body [class*="text-slate-900"],
html.kikoerumanager-dark .detail-body [class*="text-slate-800"],
html.kikoerumanager-dark .detail-body [class*="text-slate-700"],
html.kikoerumanager-dark .detail-body [class*="text-sky-"],
html.kikoerumanager-dark .detail-body [class*="text-blue-"],
html.kikoerumanager-dark .detail-body [class*="text-indigo-"],
html.kikoerumanager-dark .detail-body [class*="text-violet-"],
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
html.kikoerumanager-dark .detail-body [class*="bg-sky-50"],
html.kikoerumanager-dark .detail-body [class*="bg-blue-50"],
html.kikoerumanager-dark .detail-body [class*="bg-indigo-50"],
html.kikoerumanager-dark .detail-body [class*="bg-violet-50"],
html.kikoerumanager-dark .detail-body [class*="from-sky-50"],
html.kikoerumanager-dark .detail-body [class*="from-blue-50"],
html.kikoerumanager-dark .detail-body [class*="from-indigo-50"],
html.kikoerumanager-dark .detail-body [class*="from-violet-50"],
html.kikoerumanager-dark .detail-body [class*="to-white"],
html.kikoerumanager-dark .detail-body .highlight-row,
html.kikoerumanager-dark .detail-body .metric-cell,
html.kikoerumanager-dark .detail-body .metric-tail-row,
html.kikoerumanager-dark .detail-body .entry-row,
html.kikoerumanager-dark .detail-body .entry-item,
html.kikoerumanager-dark .detail-body .entry-section-toggle {
  background-color: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-body [class*="ring-sky-"],
html.kikoerumanager-dark .detail-body [class*="ring-blue-"],
html.kikoerumanager-dark .detail-body [class*="ring-indigo-"],
html.kikoerumanager-dark .detail-body [class*="ring-violet-"],
html.kikoerumanager-dark .detail-body [class*="border-sky-"],
html.kikoerumanager-dark .detail-body [class*="border-blue-"],
html.kikoerumanager-dark .detail-body [class*="border-indigo-"],
html.kikoerumanager-dark .detail-body [class*="border-violet-"] {
  --tw-ring-color: rgba(255, 255, 255, 0.14) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .detail-body .metric-strip {
  background: #17181d !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .detail-body .highlight-grid,
html.kikoerumanager-dark .detail-body .metric-tail {
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .detail-body .entry-section-toggle:hover,
html.kikoerumanager-dark .detail-body .entry-row:hover,
html.kikoerumanager-dark .detail-body .entry-item:hover {
  background: #202126 !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
}

html.kikoerumanager-dark .detail-body code,
html.kikoerumanager-dark .detail-body .mono,
html.kikoerumanager-dark .detail-body .path {
  color: #d7dde7 !important;
}
</style>

<style scoped>
.app-container {
  height: 100vh;
  padding: 8px;
  gap: 10px;
  overflow: hidden;
  background: #ffffff;
}

.sidebar {
  --sidebar-collapsed-width: 64px;
  --sidebar-expanded-width: 248px;
  --sidebar-ease: cubic-bezier(0.22, 1, 0.36, 1);
  position: relative;
  z-index: 40;
  width: var(--sidebar-collapsed-width) !important;
  flex: 0 0 var(--sidebar-collapsed-width) !important;
  border-radius: 22px;
  overflow: visible;
  background: transparent;
  border: 0;
  box-shadow: none;
  contain: layout style;
  isolation: isolate;
  will-change: width;
  transform: translateZ(0);
  backface-visibility: hidden;
  transition:
    width 0.24s var(--sidebar-ease),
    flex-basis 0.24s var(--sidebar-ease);
}

.sidebar.is-sidebar-pinned {
  width: var(--sidebar-expanded-width) !important;
  flex-basis: var(--sidebar-expanded-width) !important;
}

.sidebar.is-sidebar-pinned {
  flex-basis: var(--sidebar-expanded-width) !important;
}

.sidebar-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  height: 100%;
  width: var(--sidebar-collapsed-width);
  padding: 8px 0;
  overflow: hidden;
  box-sizing: border-box;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow:
    0 18px 42px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
  contain: layout paint style;
  transform: translateZ(0);
  will-change: width;
  transition:
    width 0.24s var(--sidebar-ease),
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}

.sidebar:hover .sidebar-shell,
.sidebar.is-sidebar-pinned .sidebar-shell {
  width: var(--sidebar-expanded-width);
}

.logo {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  width: 100%;
  min-height: 44px;
  gap: 10px;
  padding: 6px 0 8px 12px;
  overflow: hidden;
}

.logo-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
  transform: translate3d(-8px, 0, 0);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease);
}

.sidebar:hover .logo-copy,
.sidebar.is-sidebar-pinned .logo-copy {
  opacity: 1;
  pointer-events: auto;
  transform: translate3d(0, 0, 0);
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
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  color: #111827;
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.08),
    inset 0 0 0 1px rgba(15, 23, 42, 0.08);
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
  display: block;
  height: 0;
  margin: 0 10px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(29, 29, 31, 0.42);
  text-transform: uppercase;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
  transform: translate3d(-8px, 0, 0);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease);
}

.sidebar:hover .sidebar-section-label,
.sidebar.is-sidebar-pinned .sidebar-section-label {
  height: 20px;
  margin: 0 10px 8px;
  opacity: 1;
  pointer-events: auto;
  transform: translate3d(0, 0, 0);
}

.sidebar-pin-button {
  position: absolute;
  top: 102px;
  right: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  min-height: 24px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
  color: rgba(29, 29, 31, 0.55);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transform: translate3d(0, -4px, 0) scale(0.86);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease),
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.sidebar-pin-button > svg {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.sidebar-pin-button span {
  display: none;
}

.sidebar:hover .sidebar-pin-button,
.sidebar.is-sidebar-pinned .sidebar-pin-button {
  opacity: 1;
  pointer-events: auto;
  transform: translate3d(0, 0, 0) scale(1);
}

.sidebar-pin-button:hover {
  background: #ffffff;
  border-color: rgba(15, 23, 42, 0.14);
  color: #1d1d1f;
}

.sidebar-pin-button:active {
  transform: scale(0.92);
}

.sidebar-pin-button.is-pinned {
  background: rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.12);
  color: rgba(15, 23, 42, 0.85);
}

.sidebar-menu {
  flex: 1;
  width: 100%;
  padding: 4px 0;
  overflow: hidden;
  scrollbar-width: none;
  border-right: none;
  background: transparent;
}

.sidebar-menu::-webkit-scrollbar {
  display: none;
}

.sidebar-footer {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  width: 100%;
  padding: 12px 0 0;
}

.sidebar:hover .sidebar-rail-bell,
.sidebar.is-sidebar-pinned .sidebar-rail-bell {
  opacity: 0;
  pointer-events: none;
  height: 0;
  margin: 0 12px;
  transform: translate3d(0, 6px, 0) scale(0.92);
}

.sidebar-rail-bell {
  flex-shrink: 0;
  margin: 0 12px;
  align-self: flex-start;
  height: 40px;
  overflow: hidden;
  transform: translate3d(0, 0, 0) scale(1);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease);
}

.sidebar-rail-bell :deep(.notif-bell-btn) {
  width: 40px;
  height: 40px;
  border-radius: 14px;
}

.sidebar-rail-bell :deep(.notif-bell-player) {
  width: 30px;
  height: 30px;
}

.sidebar-status-card {
  width: calc(var(--sidebar-expanded-width) - 16px);
  height: 0;
  margin: 0 8px;
  padding: 0 14px;
  box-sizing: border-box;
  border-radius: 16px;
  background: #f7f7fa;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
  opacity: 0;
  pointer-events: none;
  overflow: hidden;
  transform: translate3d(0, 10px, 0) scale(0.98);
  transition:
    opacity 0.18s ease,
    transform 0.22s var(--sidebar-ease);
}

.sidebar:hover .sidebar-status-card,
.sidebar.is-sidebar-pinned .sidebar-status-card {
  height: 132px;
  padding: 14px;
  opacity: 1;
  pointer-events: auto;
  transform: translate3d(0, 0, 0) scale(1);
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
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease;
}

.sidebar:hover .conflict-badge,
.sidebar.is-sidebar-pinned .conflict-badge {
  opacity: 1;
  pointer-events: auto;
}

.version-info {
  position: static;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-direction: row;
  gap: 8px;
  width: 100%;
  min-height: 40px;
  padding: 0;
}

.sidebar:not(:hover):not(.is-sidebar-pinned) .version-info {
  gap: 0;
}

.version-text {
  display: inline-block;
  width: 0;
  margin-left: calc(var(--sidebar-collapsed-width) + 8px);
  opacity: 0;
  overflow: hidden;
  white-space: nowrap;
  font-size: 12px;
  padding: 4px 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #1d1d1f;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
  transform: translate3d(-8px, 0, 0);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease);
}

.sidebar:hover .version-text,
.sidebar.is-sidebar-pinned .version-text {
  width: 128px;
  opacity: 1;
  padding: 4px 10px;
  transform: translate3d(0, 0, 0);
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
  overflow-x: hidden;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

:deep(.sidebar-menu .el-menu) {
  border-right: none;
}

:deep(.sidebar-menu .el-menu-item) {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  width: calc(100% - 16px);
  height: 40px;
  min-width: 0;
  margin: 4px 8px;
  padding: 0 14px !important;
  gap: 12px;
  border-radius: 12px;
  color: rgba(29, 29, 31, 0.72);
  font-size: 14px;
  overflow: hidden;
  white-space: nowrap;
  transition:
    background 0.22s ease,
    color 0.22s ease,
    box-shadow 0.24s ease,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

:deep(.sidebar-menu .sidebar-nav-overview) { --sidebar-nav-icon: var(--km-nav-overview-icon); }
:deep(.sidebar-menu .sidebar-nav-tasks) { --sidebar-nav-icon: var(--km-nav-tasks-icon); }
:deep(.sidebar-menu .sidebar-nav-conflicts) { --sidebar-nav-icon: var(--km-nav-conflicts-icon); }
:deep(.sidebar-menu .sidebar-nav-library) { --sidebar-nav-icon: var(--km-nav-library-icon); }
:deep(.sidebar-menu .sidebar-nav-subtitle) { --sidebar-nav-icon: var(--km-nav-subtitle-icon); }
:deep(.sidebar-menu .sidebar-nav-passwords) { --sidebar-nav-icon: var(--km-nav-passwords-icon); }
:deep(.sidebar-menu .sidebar-nav-folders) { --sidebar-nav-icon: var(--km-nav-folders-icon); }
:deep(.sidebar-menu .sidebar-nav-asmr) { --sidebar-nav-icon: var(--km-nav-asmr-icon); }
:deep(.sidebar-menu .sidebar-nav-circle) { --sidebar-nav-icon: var(--km-nav-circle-icon); }
:deep(.sidebar-menu .sidebar-nav-backup) { --sidebar-nav-icon: var(--km-nav-backup-icon); }
:deep(.sidebar-menu .sidebar-nav-settings) { --sidebar-nav-icon: var(--km-nav-settings-icon); }
:deep(.sidebar-menu .sidebar-nav-logs) { --sidebar-nav-icon: var(--km-nav-logs-icon); }
:deep(.sidebar-menu .sidebar-nav-history) { --sidebar-nav-icon: var(--km-nav-history-icon); }

:deep(.sidebar-menu .el-menu-item span) {
  display: inline-block;
  width: 140px;
  opacity: 0;
  overflow: hidden;
  white-space: nowrap;
  transform: translate3d(-8px, 0, 0);
  transition:
    opacity 0.16s ease,
    transform 0.2s var(--sidebar-ease);
}

:deep(.sidebar-menu .el-menu-item > svg) {
  flex: 0 0 auto;
  width: 19px;
  height: 19px;
  color: var(--sidebar-nav-icon, rgba(29, 29, 31, 0.56));
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.24s ease;
}

.sidebar:hover :deep(.sidebar-menu .el-menu-item span),
.sidebar.is-sidebar-pinned :deep(.sidebar-menu .el-menu-item span) {
  opacity: 1;
  transform: translate3d(0, 0, 0);
}

:deep(.sidebar-menu .el-menu-item:hover) {
  transform: translateY(-2px) scale(1.02);
  background: transparent;
  color: #1d1d1f;
  box-shadow: none;
}

:deep(.sidebar-menu .el-menu-item:hover > svg) {
  transform: rotate(-8deg);
  color: var(--sidebar-nav-icon, #1d1d1f);
}

:deep(.sidebar-menu .el-menu-item.is-active) {
  background: transparent;
  color: #1d1d1f;
  font-weight: 600;
  box-shadow: none;
}

:deep(.sidebar-menu .el-menu-item.is-active > svg) {
  color: var(--sidebar-nav-icon, #1d1d1f);
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
  position: absolute;
  left: calc(var(--sidebar-collapsed-width) / 2 - 1px);
  bottom: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  width: 40px !important;
  height: 40px !important;
  min-width: 0;
  padding: 0 !important;
  overflow: hidden;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.68);
  color: rgba(29, 29, 31, 0.72);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.62);
  cursor: pointer;
  z-index: 2;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0;
  transform: translate3d(-50%, 0, 0);
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.28s ease,
    border-color 0.24s ease,
    color 0.24s ease,
    box-shadow 0.24s ease;
}

.theme-toggle-button:hover {
  border-color: rgba(29, 29, 31, 0.16);
  color: #1d1d1f;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08), inset 0 0 0 1px rgba(255, 255, 255, 0.72);
  transform: translate3d(-50%, -1px, 0) scale(1.03);
}

.theme-toggle-button:active {
  transform: translate3d(-50%, 0, 0) scale(0.96);
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
  display: none;
}

.theme-toggle-icon {
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
  margin: 0;
  position: relative;
  z-index: 1;
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
  transition: opacity 0.28s ease, transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.28s ease;
}

.theme-icon-enter-from {
  opacity: 0;
  transform: rotate(-110deg) scale(0.25);
  filter: blur(5px);
}

.theme-icon-leave-to {
  opacity: 0;
  transform: rotate(110deg) scale(0.25);
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
  color: var(--sidebar-nav-icon, rgba(203, 213, 225, 0.58));
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item:hover) {
  background: transparent;
  color: #f8fafc;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item:hover > svg) {
  color: var(--sidebar-nav-icon, #f8fafc);
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item.is-active) {
  background: transparent;
  color: #f8fafc;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) :deep(.sidebar-menu .el-menu-item.is-active > svg) {
  color: var(--sidebar-nav-icon, #f8fafc);
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

  .sidebar.is-sidebar-pinned {
    width: min(82vw, 320px) !important;
    flex: none !important;
    flex-basis: auto !important;
  }

  /* 抽屉打开态 */
  .sidebar.is-mobile-open {
    transform: translateX(0);
  }

  /* sidebar-shell 在抽屉态调整 */
  .sidebar-shell {
    height: 100%;
    width: 100%;
    padding: 16px 14px 16px;
    border-radius: 0 22px 22px 0;
    align-items: stretch;
    contain: none;
    will-change: auto;
  }

  .logo {
    justify-content: flex-start;
    gap: 10px;
    padding: 6px 8px 18px;
  }

  .logo-copy {
    display: flex;
    opacity: 1;
    pointer-events: auto;
    transform: none;
  }

  .logo-bell {
    display: block;
  }

  .logo-mark {
    width: 40px;
    height: 40px;
    border-radius: 13px;
    background: #f3f7ff;
    color: #0071e3;
    box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.08);
  }

  .sidebar-section-label {
    display: block;
    height: auto;
    margin: 0 10px 10px;
    opacity: 1;
    pointer-events: auto;
    transform: none;
  }

  .sidebar-pin-button {
    display: none;
  }

  .sidebar-menu {
    padding: 0;
    overflow-y: auto;
  }

  :deep(.sidebar-menu .el-menu-item) {
    justify-content: flex-start;
    width: auto;
    height: 46px;
    min-width: 0;
    margin: 4px 0;
    padding: 0 18px !important;
    gap: 10px;
    border-radius: 16px;
  }

  :deep(.sidebar-menu .el-menu-item span) {
    display: inline;
    width: auto;
    opacity: 1;
    transform: none;
  }

  :deep(.sidebar-menu .el-menu-item > svg) {
    width: 18px;
    height: 18px;
  }

  .sidebar-footer {
    align-items: stretch;
    gap: 12px;
    padding: 16px 8px 0;
  }

  .sidebar-rail-bell {
    display: none;
  }

  .sidebar-status-card {
    display: block;
    height: auto;
    padding: 14px;
    opacity: 1;
    pointer-events: auto;
    transform: none;
  }

  .version-info {
    flex-direction: row;
    justify-content: space-between;
    margin-top: 14px;
    padding: 0 6px;
  }

  .version-text {
    display: inline-flex;
    width: auto;
    margin-left: 0;
    opacity: 1;
    padding: 4px 10px;
    transform: none;
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
    position: static;
    width: 40px !important;
    height: 40px !important;
    gap: 6px;
    padding: 0 !important;
    border-radius: 14px;
    transform: none;
  }

  .theme-toggle-button:hover {
    transform: translateY(-1px) scale(1.03);
  }

  .theme-toggle-button:active {
    transform: scale(0.96);
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

.app-container {
  background: #ffffff !important;
}

html.kikoerumanager-dark .app-container {
  background: #08090c !important;
}

html.kikoerumanager-dark,
body.kikoerumanager-dark,
html.kikoerumanager-dark body,
html.kikoerumanager-dark #app {
  background: #08090c !important;
}

.sidebar-shell {
  background: rgba(255, 255, 255, 0.98) !important;
  border-color: rgba(15, 23, 42, 0.08) !important;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.8) !important;
}

html.kikoerumanager-dark .sidebar-shell {
  background: rgba(12, 13, 17, 0.96) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  box-shadow: 0 22px 60px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

html.kikoerumanager-dark .logo-mark {
  background: rgba(255, 255, 255, 0.06) !important;
  color: rgba(241, 245, 249, 0.92) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item {
  color: rgba(226, 232, 240, 0.78) !important;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item > svg {
  color: var(--sidebar-nav-icon, rgba(226, 232, 240, 0.68)) !important;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover {
  background: transparent !important;
  color: #f8fafc !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active {
  background: transparent !important;
  color: #f8fafc !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .sidebar-menu .el-menu-item:hover > svg,
html.kikoerumanager-dark .sidebar-menu .el-menu-item.is-active > svg {
  color: var(--sidebar-nav-icon, #f8fafc) !important;
}

/* 弹窗内统一取消浏览器 / Element Plus / Tailwind 聚焦态。 */
.el-dialog :is(
  button,
  input,
  textarea,
  select,
  [tabindex],
  [role="button"],
  [contenteditable="true"],
  .interactive-chip,
  .action-card,
  .row-action,
  .tree-row,
  .tree-checkbox,
  .fm-body,
  .fm-row,
  .nav-row,
  .crumb-btn,
  .fm-icon-btn,
  .search-input,
  .primary-cta,
  .secondary-cta,
  .close-button,
  .el-input__wrapper,
  .el-select__wrapper
):focus,
.el-dialog :is(
  button,
  input,
  textarea,
  select,
  [tabindex],
  [role="button"],
  [contenteditable="true"],
  .interactive-chip,
  .action-card,
  .row-action,
  .tree-row,
  .tree-checkbox,
  .fm-body,
  .fm-row,
  .nav-row,
  .crumb-btn,
  .fm-icon-btn,
  .search-input,
  .primary-cta,
  .secondary-cta,
  .close-button,
  .el-input__wrapper,
  .el-select__wrapper
):focus-visible,
.el-dialog :is(
  .el-input__wrapper.is-focus,
  .el-select__wrapper.is-focused,
  .search-shell:focus-within
) {
  --tw-ring-color: transparent !important;
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
  outline: 0 !important;
  outline-offset: 0 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark :is(
  .folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(
  button,
  input,
  textarea,
  select,
  [tabindex],
  [role="button"],
  [contenteditable="true"],
  .interactive-chip,
  .action-card,
  .row-action,
  .tree-row,
  .tree-checkbox,
  .close-button,
  .el-input__wrapper,
  .el-select__wrapper
):focus,
html.kikoerumanager-dark :is(
  .folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(
  button,
  input,
  textarea,
  select,
  [tabindex],
  [role="button"],
  [contenteditable="true"],
  .interactive-chip,
  .action-card,
  .row-action,
  .tree-row,
  .tree-checkbox,
  .close-button,
  .el-input__wrapper,
  .el-select__wrapper
):focus-visible,
html.kikoerumanager-dark :is(
  .folder-dialog:not(.filter-delete-dialog),
  .mojibake-preview-dialog
) :is(
  .el-input__wrapper.is-focus,
  .el-select__wrapper.is-focused,
  .search-shell:focus-within,
  .repair-preview-input:focus
) {
  --tw-ring-color: transparent !important;
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
  outline: 0 !important;
  outline-offset: 0 !important;
  box-shadow: none !important;
}

/* 文件管理弹窗最终暗色兜底：改为中性黑灰，去掉蓝灰泛光和聚焦投影。 */
html.kikoerumanager-dark .custom-preview-overlay:has(.folder-dialog:not(.filter-delete-dialog)),
html.kikoerumanager-dark .custom-preview-overlay:has(.mojibake-preview-dialog) {
  background: rgba(8, 8, 10, 0.42) !important;
  background-image: none !important;
  backdrop-filter: blur(12px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(12px) saturate(108%) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog).el-dialog,
html.kikoerumanager-dark .mojibake-preview-dialog.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .window,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .glass-shell,
html.kikoerumanager-dark .mojibake-preview-dialog .window,
html.kikoerumanager-dark .mojibake-preview-dialog .glass-shell {
  background:
    linear-gradient(180deg, rgba(29, 30, 35, 0.96), rgba(14, 15, 18, 0.98)),
    #111216 !important;
  background-image:
    linear-gradient(180deg, rgba(29, 30, 35, 0.96), rgba(14, 15, 18, 0.98)) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  outline: 1px solid rgba(255, 255, 255, 0.04) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .glass-shell::before,
html.kikoerumanager-dark .mojibake-preview-dialog .glass-shell::before {
  display: none !important;
  content: none !important;
  background: none !important;
  opacity: 0 !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .window-header,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-body,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .toolbar-row,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-head,
html.kikoerumanager-dark .mojibake-preview-dialog .window-header,
html.kikoerumanager-dark .mojibake-preview-dialog .fm-body,
html.kikoerumanager-dark .mojibake-preview-dialog .toolbar-row,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-footer {
  background: #17181d !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) :is(
  .glass-panel,
  .glass-card,
  .tree-panel,
  .selection-card,
  .info-card,
  .search-shell,
  .fm-badge,
  .fm-count-pill
),
html.kikoerumanager-dark .mojibake-preview-dialog :is(
  .repair-preview-body,
  .repair-preview-card,
  .repair-preview-empty,
  .repair-preview-input,
  .fm-badge,
  .fm-count-pill
) {
  background: #1d1e23 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  outline: 1px solid rgba(255, 255, 255, 0.035) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(12px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(12px) saturate(108%) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-scroll {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(226, 232, 240, 0.82) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row:hover {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(250, 250, 252, 0.94) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-row-selected {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) :is(
  .action-card,
  .close-button
),
html.kikoerumanager-dark .mojibake-preview-dialog :is(
  .action-card,
  .close-button
) {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) :is(
  .action-card:hover:not(:disabled),
  .close-button:hover
),
html.kikoerumanager-dark .mojibake-preview-dialog :is(
  .action-card:hover:not(:disabled),
  .close-button:hover
) {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .action-card-danger {
  background: rgba(244, 63, 94, 0.12) !important;
  border-color: rgba(251, 113, 133, 0.28) !important;
  color: #fb7185 !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .action-card-danger:hover:not(:disabled) {
  background: rgba(244, 63, 94, 0.2) !important;
  border-color: rgba(251, 113, 133, 0.38) !important;
  color: #fecdd3 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .fm-repair-lottie {
  filter: grayscale(1) brightness(0) invert(1) !important;
  opacity: 0.92 !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .row-action {
  background: rgba(244, 63, 94, 0.1) !important;
  background-image: none !important;
  border-color: rgba(251, 113, 133, 0.24) !important;
  color: #fb7185 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .row-action:hover:not(:disabled) {
  background: rgba(244, 63, 94, 0.2) !important;
  border-color: rgba(251, 113, 133, 0.38) !important;
  color: #fecdd3 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) :is(
  .title,
  .tree-name,
  .text-slate-900,
  .text-slate-800,
  .text-slate-700
),
html.kikoerumanager-dark .mojibake-preview-dialog :is(
  .title,
  .repair-preview-value,
  .text-slate-900,
  .text-slate-800,
  .text-slate-700
) {
  color: rgba(250, 250, 252, 0.96) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) :is(
  .tree-sub,
  .tree-size,
  .tree-time,
  .preview-empty,
  .text-slate-600,
  .text-slate-500,
  .text-slate-400
),
html.kikoerumanager-dark .mojibake-preview-dialog :is(
  .repair-preview-label,
  .repair-preview-path,
  .repair-preview-encoding,
  .text-slate-600,
  .text-slate-500,
  .text-slate-400
) {
  color: rgba(214, 214, 220, 0.68) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .search-input {
  background: transparent !important;
  color: rgba(250, 250, 252, 0.94) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .search-shell:focus-within,
html.kikoerumanager-dark .mojibake-preview-dialog .repair-preview-input:focus {
  border-color: rgba(255, 255, 255, 0.16) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .app-loading-mask {
  background: rgba(5, 6, 10, 0.52) !important;
  color: rgba(250, 250, 252, 0.94) !important;
  box-shadow: none !important;
  backdrop-filter: blur(5px) saturate(104%) !important;
  -webkit-backdrop-filter: blur(5px) saturate(104%) !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .app-loading-animation__player {
  filter: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .app-loading-animation__label {
  color: rgba(250, 250, 252, 0.96) !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .app-loading-animation__description {
  color: rgba(214, 214, 220, 0.72) !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox {
  background: #24252a !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-on,
html.kikoerumanager-dark .folder-dialog:not(.filter-delete-dialog) .tree-checkbox-partial {
  background: #56575e !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

/* 上传到服务器预览：单独兜底，避免被通用 custom-preview 深蓝规则再次覆盖。 */
html.kikoerumanager-dark .custom-preview-overlay:has(.server-upload-preview-modal) {
  background: rgba(4, 5, 8, 0.22) !important;
  background-image: none !important;
  backdrop-filter: blur(10px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(108%) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .window,
html.kikoerumanager-dark .server-upload-preview-modal .glass-shell {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)),
    rgba(20, 21, 25, 0.88) !important;
  background-image:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .glass-shell::before {
  display: none !important;
  content: none !important;
  background: none !important;
  opacity: 0 !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .window-header,
  .tabs-row,
  .footer-row
) {
  background: rgba(24, 25, 29, 0.58) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .content-grid,
html.kikoerumanager-dark .server-upload-preview-modal .left-column {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .glass-panel,
  .glass-card,
  .tree-panel
) {
  background:
    linear-gradient(180deg, rgba(50, 51, 56, 0.38), rgba(20, 21, 25, 0.56)),
    rgba(24, 25, 29, 0.72) !important;
  background-image:
    linear-gradient(180deg, rgba(50, 51, 56, 0.38), rgba(20, 21, 25, 0.56)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(14px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(14px) saturate(108%) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .upload-settings-card {
  background-color: rgba(24, 25, 29, 0.72) !important;
  background-image: linear-gradient(180deg, rgba(56, 57, 62, 0.44), rgba(16, 17, 21, 0.62)) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-scroll {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .section-head {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(214, 214, 220, 0.72) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .field-input,
  .select-button,
  .picker-button,
  .dropdown-panel,
  .target-path
) {
  background: rgba(35, 36, 40, 0.72) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(10px) saturate(106%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(106%) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .target-path {
  background: rgba(255, 255, 255, 0.045) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  border-radius: 8px !important;
  padding: 5px 8px !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .field-input:hover,
html.kikoerumanager-dark .server-upload-preview-modal .picker-button:not(:disabled):hover,
html.kikoerumanager-dark .server-upload-preview-modal .select-button:hover {
  background: rgba(48, 49, 54, 0.78) !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-row {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(226, 232, 240, 0.84) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-row:hover {
  background: rgba(255, 255, 255, 0.055) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  transform: translate3d(0, -1px, 0) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected,
html.kikoerumanager-dark .server-upload-preview-modal .tree-row-selected:hover {
  background: rgba(255, 255, 255, 0.13) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: rgba(250, 250, 252, 0.98) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .tab-chip,
  .secondary-cta,
  .interactive-chip,
  .close-button
) {
  background: rgba(43, 44, 48, 0.84) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .tab-chip:hover,
  .secondary-cta:hover,
  .interactive-chip:hover,
  .close-button:hover
) {
  background: rgba(56, 57, 62, 0.9) !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .tab-chip-active,
  .tab-chip-partial
) {
  background: rgba(86, 87, 94, 0.86) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .primary-cta {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: #111116 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .primary-cta:hover:not(:disabled) {
  background: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.42) !important;
  color: #0f1014 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .primary-cta:disabled {
  background: rgba(86, 87, 94, 0.52) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: rgba(214, 214, 220, 0.48) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .tree-checkbox-on,
  .tree-checkbox-partial
) {
  background: #4a4b51 !important;
  border-color: rgba(255, 255, 255, 0.34) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-checkbox-off {
  background: rgba(30, 31, 35, 0.74) !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  color: transparent !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-row:hover .tree-checkbox-off {
  background: rgba(48, 49, 54, 0.88) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  .title,
  h1,
  h2,
  label,
  .tree-name,
  .summary-strong,
  .text-slate-900,
  .text-slate-800,
  .text-slate-700
) {
  color: rgba(250, 250, 252, 0.96) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal :is(
  p,
  .summary,
  .summary-stack,
  .tree-size,
  .node-title-muted,
  .preview-empty,
  .text-slate-600,
  .text-slate-500,
  .text-slate-400
) {
  color: rgba(214, 214, 220, 0.68) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .tree-icon {
  filter: none !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .app-loading-animation {
  color: rgba(250, 250, 252, 0.94) !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .app-loading-animation__label {
  color: rgba(250, 250, 252, 0.96) !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .server-upload-preview-modal .app-loading-animation__description {
  color: rgba(214, 214, 220, 0.72) !important;
  text-shadow: none !important;
}

/* 上传目录选择器：跟上传到服务器弹窗统一为中性厚玻璃，移除蓝灰底和竖条选中线。 */
html.kikoerumanager-dark .custom-preview-overlay:has(.remote-folder-picker-modal) {
  background: rgba(4, 5, 8, 0.22) !important;
  background-image: none !important;
  backdrop-filter: blur(10px) saturate(108%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(108%) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal.el-dialog {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .window,
html.kikoerumanager-dark .remote-folder-picker-modal .glass-shell {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)),
    rgba(20, 21, 25, 0.88) !important;
  background-image:
    linear-gradient(180deg, rgba(48, 49, 54, 0.74), rgba(16, 17, 21, 0.9)) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline: 1px solid rgba(255, 255, 255, 0.045) !important;
  outline-offset: -2px !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: blur(18px) saturate(112%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(112%) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .glass-shell::before {
  display: none !important;
  content: none !important;
  background: none !important;
  opacity: 0 !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .window-header,
  .explorer-toolbar,
  .footer-row
) {
  background: rgba(24, 25, 29, 0.58) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .explorer-main,
  .explorer-nav,
  .explorer-list,
  .fm-body
) {
  background: transparent !important;
  background-image: none !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .explorer-nav {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-head,
  .nav-section-title
) {
  background: rgba(20, 21, 25, 0.46) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: rgba(214, 214, 220, 0.68) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-head-cell,
  .fm-head .fm-cell-time
) {
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(214, 214, 220, 0.68) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .path-bar,
  .search-input,
  .crumb-btn,
  .fm-icon-btn,
  .target-chip,
  .rel-chip,
  .interactive-chip,
  .secondary-cta
) {
  background: rgba(43, 44, 48, 0.84) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .crumb-btn:hover,
  .fm-icon-btn:hover:not(:disabled),
  .interactive-chip:hover,
  .secondary-cta:hover
) {
  background: rgba(56, 57, 62, 0.9) !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-row,
  .nav-row
) {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  color: rgba(226, 232, 240, 0.84) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-row:hover,
  .nav-row:hover
) {
  background: rgba(255, 255, 255, 0.055) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  transform: translate3d(0, -1px, 0) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-row-selected,
  .fm-row-selected:hover,
  .nav-row-active,
  .nav-row-active:hover
) {
  background: rgba(255, 255, 255, 0.13) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: rgba(250, 250, 252, 0.98) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .primary-cta {
  background: #e7e7eb !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: #111116 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .primary-cta:hover:not(:disabled) {
  background: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.42) !important;
  color: #0f1014 !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .primary-cta:disabled {
  background: rgba(86, 87, 94, 0.52) !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: rgba(250, 250, 252, 0.72) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .title,
  .fm-name,
  .target-chip-path,
  .rel-chip-value,
  .text-slate-900,
  .text-slate-800,
  .text-slate-700
) {
  color: rgba(250, 250, 252, 0.96) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-cell-time,
  .rel-chip-label,
  .fm-name-rel,
  .fm-loading-desc,
  .text-slate-600,
  .text-slate-500,
  .text-slate-400
) {
  color: rgba(214, 214, 220, 0.68) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .search-input::placeholder {
  color: rgba(214, 214, 220, 0.5) !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .fm-loading-icon,
  .fm-loading-title,
  .nav-disk-icon
) {
  color: rgba(250, 250, 252, 0.92) !important;
  filter: none !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal .fm-kind-icon {
  filter: none !important;
  opacity: 1 !important;
}

html.kikoerumanager-dark .remote-folder-picker-modal :is(
  .nav-splitter,
  .nav-splitter-line
) {
  background: rgba(255, 255, 255, 0.1) !important;
}

</style>
