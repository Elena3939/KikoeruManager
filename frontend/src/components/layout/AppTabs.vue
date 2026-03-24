<template>
  <div class="app-tabs" @click="hideContextMenu">
    <div class="app-tabs__start">
      <div class="app-tabs__workspace">
        <el-icon class="app-tabs__workspace-icon"><Menu /></el-icon>
        <span class="app-tabs__workspace-text">标签</span>
        <span class="app-tabs__workspace-count">{{ tabStore.tabs.length }}</span>
      </div>
    </div>

    <div ref="scrollRef" class="app-tabs__scroll">
      <div
        v-for="tab in tabStore.tabs"
        :key="tab.path"
        role="button"
        tabindex="0"
        class="app-tabs__item"
        :class="{ 'is-active': tabStore.activeTab === tab.path }"
        @click="tabStore.switchTab(tab.path)"
        @contextmenu.prevent="openContextMenu($event, tab)"
        @keydown.enter.prevent="tabStore.switchTab(tab.path)"
        @keydown.space.prevent="tabStore.switchTab(tab.path)"
      >
        <el-icon v-if="tab.icon" class="app-tabs__icon">
          <component :is="tab.icon" />
        </el-icon>
        <span class="app-tabs__title">{{ tab.title }}</span>
        <button
          v-if="tab.closable"
          type="button"
          class="app-tabs__close"
          @click.stop="tabStore.closeTab(tab.path)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>

    <div class="app-tabs__actions">
      <button
        type="button"
        class="app-tabs__action-btn"
        title="刷新当前页"
        @click.stop="handleRefresh"
      >
        <el-icon><RefreshRight /></el-icon>
      </button>

      <el-dropdown trigger="click" placement="bottom-end" @command="handleToolbarCommand">
        <button type="button" class="app-tabs__action-btn" title="标签操作">
          <el-icon><Operation /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu class="app-tabs__dropdown-menu">
            <el-dropdown-item command="refresh">刷新当前页</el-dropdown-item>
            <el-dropdown-item
              command="closeCurrent"
              :disabled="!tabStore.activeTabItem?.closable"
            >
              关闭当前
            </el-dropdown-item>
            <el-dropdown-item command="closeOthers">关闭其他</el-dropdown-item>
            <el-dropdown-item command="closeRight">关闭右侧</el-dropdown-item>
            <el-dropdown-item command="closeAll">关闭全部</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-dropdown trigger="click" placement="bottom-end">
        <button type="button" class="app-tabs__action-btn" title="已打开标签">
          <el-icon><Menu /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu class="app-tabs__dropdown-menu app-tabs__dropdown-menu--wide">
            <el-dropdown-item
              v-for="tab in tabStore.tabs"
              :key="tab.path"
              :class="{ 'is-active': tab.path === tabStore.activeTab }"
              @click="tabStore.switchTab(tab.path)"
            >
              <div class="app-tabs__tab-list-item">
                <span class="app-tabs__tab-list-title">{{ tab.title }}</span>
                <button
                  v-if="tab.closable"
                  type="button"
                  class="app-tabs__tab-list-close"
                  @click.stop="tabStore.closeTab(tab.path)"
                >
                  <el-icon><Close /></el-icon>
                </button>
              </div>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div
      v-if="contextMenu.visible"
      class="app-tabs__menu"
      :style="{
        left: `${contextMenu.x}px`,
        top: `${contextMenu.y}px`
      }"
    >
      <button
        type="button"
        class="app-tabs__menu-item"
        @click="handleMenuAction(() => tabStore.refreshTab(contextMenu.tab?.path))"
      >
        刷新当前页
      </button>
      <button
        type="button"
        class="app-tabs__menu-item"
        :disabled="!contextMenu.tab?.closable"
        @click="handleMenuAction(() => tabStore.closeTab(contextMenu.tab?.path))"
      >
        关闭当前
      </button>
      <button
        type="button"
        class="app-tabs__menu-item"
        @click="handleMenuAction(() => tabStore.closeOthers(contextMenu.tab?.path))"
      >
        关闭其他
      </button>
      <button
        type="button"
        class="app-tabs__menu-item"
        @click="handleMenuAction(() => tabStore.closeRight(contextMenu.tab?.path))"
      >
        关闭右侧
      </button>
      <button
        type="button"
        class="app-tabs__menu-item"
        @click="handleMenuAction(() => tabStore.closeAll())"
      >
        关闭全部
      </button>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Close, Menu, Operation, RefreshRight } from '@element-plus/icons-vue'
import { useTabStore } from '../../stores/tabStore'

const tabStore = useTabStore()
const scrollRef = ref(null)
const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  tab: null
})

function hideContextMenu() {
  contextMenu.visible = false
}

function openContextMenu(event, tab) {
  contextMenu.visible = true
  contextMenu.x = event.clientX
  contextMenu.y = event.clientY
  contextMenu.tab = tab
}

async function handleMenuAction(action) {
  hideContextMenu()
  await action()
}

function handleRefresh() {
  tabStore.refreshTab()
}

async function handleToolbarCommand(command) {
  if (command === 'refresh') {
    tabStore.refreshTab()
    return
  }
  if (command === 'closeCurrent') {
    await tabStore.closeTab(tabStore.activeTab)
    return
  }
  if (command === 'closeOthers') {
    await tabStore.closeOthers(tabStore.activeTab)
    return
  }
  if (command === 'closeRight') {
    await tabStore.closeRight(tabStore.activeTab)
    return
  }
  if (command === 'closeAll') {
    await tabStore.closeAll()
  }
}

function scrollActiveTabIntoView() {
  nextTick(() => {
    const container = scrollRef.value
    if (!container) return

    const activeEl = container.querySelector('.app-tabs__item.is-active')
    activeEl?.scrollIntoView({
      behavior: 'smooth',
      inline: 'nearest',
      block: 'nearest'
    })
  })
}

watch(
  () => [tabStore.activeTab, tabStore.tabs.length],
  () => {
    scrollActiveTabIntoView()
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('click', hideContextMenu)
  window.addEventListener('resize', hideContextMenu)
})

onBeforeUnmount(() => {
  window.removeEventListener('click', hideContextMenu)
  window.removeEventListener('resize', hideContextMenu)
})
</script>

<style scoped>
.app-tabs {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: stretch;
  min-height: 40px;
  border-bottom: 1px solid #dde5ee;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.app-tabs__start,
.app-tabs__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
}

.app-tabs__start {
  border-right: 1px solid #e7edf4;
  background: #fbfcfe;
}

.app-tabs__workspace {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 2px 4px 1px;
  border: none;
  border-radius: 0;
  background: transparent;
  color: #64748b;
}

.app-tabs__workspace-icon {
  font-size: 13px;
  color: #475569;
}

.app-tabs__workspace-text {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.app-tabs__workspace-count {
  min-width: 16px;
  padding: 0 5px;
  border-radius: 999px;
  background: #eef3f8;
  color: #3b82f6;
  font-size: 11px;
  line-height: 17px;
  text-align: center;
}

.app-tabs__scroll {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  overflow-x: auto;
  padding: 5px 10px;
  scrollbar-width: none;
}

.app-tabs__scroll::-webkit-scrollbar {
  display: none;
}

.app-tabs__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  height: 26px;
  padding: 0 9px 0 10px;
  border: 1px solid #d9e3ec;
  border-radius: 4px;
  background: #ffffff;
  color: #5f6b7a;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.app-tabs__item:hover {
  border-color: #c8d4e2;
  background: #f8fafc;
  color: #334155;
}

.app-tabs__item.is-active {
  border-color: #4b89d6;
  background: #4b89d6;
  color: #ffffff;
  box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.04);
}

.app-tabs__item.is-active::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
}

.app-tabs__icon {
  flex-shrink: 0;
  font-size: 12px;
}

.app-tabs__title {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.1;
}

.app-tabs__item.is-active .app-tabs__title {
  font-weight: 600;
}

.app-tabs__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  opacity: 0.58;
}

.app-tabs__close:hover {
  background: rgba(255, 255, 255, 0.18);
  opacity: 1;
}

.app-tabs__item:not(.is-active) .app-tabs__close:hover {
  background: rgba(100, 116, 139, 0.12);
}

.app-tabs__actions {
  border-left: 1px solid #e7edf4;
  background: #fbfcfe;
}

.app-tabs__action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  transition: border-color 0.16s ease, color 0.16s ease, background-color 0.16s ease;
}

.app-tabs__action-btn:hover {
  border-color: #cfd9e4;
  background: #f8fafc;
  color: #334155;
}

.app-tabs__menu {
  position: fixed;
  min-width: 148px;
  padding: 6px;
  border: 1px solid #dde5ee;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.1);
  backdrop-filter: blur(8px);
}

.app-tabs__menu-item {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #334155;
  text-align: left;
  font-size: 13px;
  cursor: pointer;
}

.app-tabs__menu-item:hover:not(:disabled) {
  background: #ecf5ff;
  color: #409eff;
}

.app-tabs__menu-item:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.app-tabs__tab-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.app-tabs__tab-list-title {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-tabs__tab-list-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.app-tabs__tab-list-close:hover {
  background: rgba(88, 103, 125, 0.12);
}

:deep(.app-tabs__dropdown-menu) {
  padding: 6px;
  border: 1px solid #dde5ee;
  border-radius: 8px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.1);
}

:deep(.app-tabs__dropdown-menu--wide) {
  min-width: 240px;
}

:deep(.app-tabs__dropdown-menu .el-dropdown-menu__item) {
  margin: 2px 0;
  border-radius: 8px;
  color: #334155;
}

:deep(.app-tabs__dropdown-menu .el-dropdown-menu__item:hover) {
  background: #ecf5ff;
  color: #2563eb;
}

:deep(.app-tabs__dropdown-menu .el-dropdown-menu__item.is-disabled) {
  color: #94a3b8;
}

:deep(.app-tabs__dropdown-menu .el-dropdown-menu__item.is-active) {
  background: linear-gradient(180deg, #f8fbff 0%, #edf5ff 100%);
  color: #1453b8;
  font-weight: 600;
}
</style>
