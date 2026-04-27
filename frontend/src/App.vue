<template>
  <el-container class="app-container">
    <el-aside width="248px" class="sidebar">
      <div class="sidebar-shell">
        <div class="logo">
          <div class="logo-mark">
            <Package2 :size="22" :stroke-width="2.2" />
          </div>
        <div class="logo-copy">
          <span class="logo-text">Prekikoeru</span>
          <span class="logo-subtitle">v{{ appVersion }}</span>
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
            <span class="version-text">Prekikoeru</span>
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
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
import router from './router'

const appVersion = '1.0.2'
const route = useRoute()
const watcherStore = useWatcherStore()
const conflictCount = ref(0)
const watcherStatus = ref({ is_running: false, watch_path: '', pending_files: [] })
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
  background: linear-gradient(180deg, #fbfbfd 0%, #f2f2f5 100%);
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
  gap: 12px;
  padding: 6px 8px 18px;
}

.logo-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: #f3f7ff;
  color: #0071e3;
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.08);
}

.logo-mark > svg {
  flex-shrink: 0;
}

.logo-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.logo-text {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.18px;
  color: #1d1d1f;
}

.logo-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.54);
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

@media screen and (max-width: 768px) {
  .app-container {
    flex-direction: column;
    padding: 10px;
  }

  .sidebar {
    width: 100% !important;
    height: auto;
  }

  .sidebar-shell {
    height: auto;
  }

  .main-content {
    min-height: 0;
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
}
</style>
