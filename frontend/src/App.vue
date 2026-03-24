<template>
  <el-container class="app-container">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <el-icon :size="32"><Box /></el-icon>
        <span class="logo-text">Prekikoeru</span>
      </div>

      <el-menu
        :default-active="route.path"
        router
        class="sidebar-menu"
        background-color="#1e293b"
        text-color="#94a3b8"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon>
          <span>概览</span>
        </el-menu-item>

        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <span>任务队列</span>
        </el-menu-item>

        <el-menu-item index="/conflicts">
          <el-icon><WarningFilled /></el-icon>
          <span>问题作品</span>
          <el-badge v-if="conflictCount > 0" :value="conflictCount" class="conflict-badge" />
        </el-menu-item>

        <el-menu-item index="/library">
          <el-icon><Box /></el-icon>
          <span>库存管理</span>
        </el-menu-item>

        <el-menu-item index="/subtitle-import">
          <el-icon><Tickets /></el-icon>
          <span>字幕补配</span>
        </el-menu-item>

        <el-menu-item index="/passwords">
          <el-icon><Lock /></el-icon>
          <span>密码库</span>
        </el-menu-item>

        <el-menu-item index="/existing-folders">
          <el-icon><Folder /></el-icon>
          <span>已有文件夹</span>
        </el-menu-item>

        <el-menu-item index="/asmr-sync">
          <el-icon><Download /></el-icon>
          <span>ASMR 同步下载</span>
        </el-menu-item>

        <el-menu-item index="/library-backup">
          <el-icon><FolderOpened /></el-icon>
          <span>库存打包</span>
        </el-menu-item>

        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>

        <el-menu-item index="/logs">
          <el-icon><Document /></el-icon>
          <span>日志</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="watcher-status">
          <el-tag :type="watcherStatus.is_running ? 'success' : 'info'" size="small">
            {{ watcherStatus.is_running ? '监视中' : '已停止' }}
          </el-tag>
          <el-button
            :type="watcherStatus.is_running ? 'danger' : 'primary'"
            size="small"
            @click="toggleWatcher"
          >
            {{ watcherStatus.is_running ? '停止' : '启动' }}
          </el-button>
        </div>
        <div class="version-info">
          <span class="version-text">版本: v{{ appVersion }}</span>
        </div>
      </div>
    </el-aside>

    <el-main class="main-content main-shell">
      <router-view v-slot="{ Component, route: viewRoute }">
        <keep-alive :include="cachedViews">
          <component
            :is="Component"
            v-if="viewRoute.meta?.cache"
            :key="viewRoute.name || viewRoute.path"
          />
        </keep-alive>
        <component
          :is="Component"
          v-if="!viewRoute.meta?.cache"
          :key="viewRoute.fullPath"
        />
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  Box,
  Document,
  Download,
  Folder,
  FolderOpened,
  HomeFilled,
  List,
  Lock,
  Setting,
  Tickets,
  WarningFilled
} from '@element-plus/icons-vue'
import router from './router'
import { useWatcherStore } from './stores'

const appVersion = '1.0.2'
const route = useRoute()
const watcherStore = useWatcherStore()
const conflictCount = ref(0)
const watcherStatus = ref({ is_running: false, watch_path: '', pending_files: [] })
const cachedViews = computed(() =>
  router
    .getRoutes()
    .filter((item) => item.meta?.cache && item.name)
    .map((item) => item.name)
)

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

<style scoped>
.app-container {
  height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  background:
    linear-gradient(180deg, #1e293b 0%, #182433 100%);
  box-shadow: 10px 0 30px rgba(15, 23, 42, 0.16);
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 64px;
  padding: 0 20px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  color: #ffffff;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.18) 0%, rgba(30, 41, 59, 0) 100%);
}

.logo-text {
  margin-left: 12px;
  font-size: 20px;
  font-weight: 600;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.22);
}

.watcher-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.conflict-badge {
  margin-left: auto;
}

.version-info {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.16);
  text-align: center;
}

.version-text {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background-color: #0f172a;
  color: #94a3b8;
  font-size: 12px;
}

.main-content {
  min-width: 0;
  padding: 20px;
  overflow-y: auto;
}

.main-shell {
  background:
    radial-gradient(circle at top right, rgba(96, 165, 250, 0.12) 0%, rgba(241, 245, 249, 0) 28%),
    linear-gradient(180deg, #f6f9fc 0%, #eef4f9 100%);
}

@media screen and (max-width: 768px) {
  .app-container {
    flex-direction: column;
  }

  .sidebar {
    width: 100% !important;
    height: auto;
    max-height: 60px;
    overflow: hidden;
  }

  .main-content {
    padding: 10px;
  }
}

:deep(.el-card) {
  overflow: visible;
}

:deep(.el-card__body) {
  overflow-x: auto;
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
