<template>
  <el-container class="app-container" :class="{ 'is-mobile-nav-open': mobileNavOpen }">
    <!-- 移动端顶栏：仅 ≤1024 显示（桌面端 display:none，零改动） -->
    <header class="app-mobile-topbar safe-area-top">
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
        v-if="mobileNavOpen"
        class="app-drawer-mask"
        @click="mobileNavOpen = false"
      />
    </Transition>

    <el-aside width="248px" class="sidebar" :class="{ 'is-mobile-open': mobileNavOpen }">
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
    <BackgroundWorkbenchHost />
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
  Package2,
  ScrollText,
  Settings2,
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
import BackgroundWorkbenchHost from './components/workbench/BackgroundWorkbenchHost.vue'
import SystemPromptHost from './components/system/SystemPromptHost.vue'
import NotificationBell from './components/system/NotificationBell.vue'
import router from './router'

const appVersion = '1.4.0'
const route = useRoute()
const watcherStore = useWatcherStore()
const conflictCount = ref(0)
const watcherStatus = ref({ is_running: false, watch_path: '', pending_files: [] })
const mobileNavOpen = ref(false)

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
  ActivityHistory
}
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
  await refreshStatus()
  intervalId = setInterval(refreshStatus, 3000)
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
