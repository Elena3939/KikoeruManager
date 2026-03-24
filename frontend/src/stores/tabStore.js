import { defineStore } from 'pinia'
import router from '../router'

const STORAGE_KEY = 'prekikoeru.ui.tabs'

const DEFAULT_TAB = {
  path: '/',
  name: 'Dashboard',
  title: '概览',
  icon: 'HomeFilled',
  closable: false,
  cache: false
}

function getValidRoutePaths() {
  return new Set(
    router
      .getRoutes()
      .filter(route => route.path && route.name)
      .map(route => route.path)
  )
}

function normalizeStoredTab(tab = {}) {
  if (!tab?.path || !tab?.name) return null

  return {
    path: String(tab.path),
    name: String(tab.name),
    title: String(tab.title || tab.name),
    icon: tab.icon ? String(tab.icon) : null,
    closable: tab.closable !== false,
    cache: tab.cache !== false
  }
}

function buildTabFromRoute(route) {
  return {
    path: route.path,
    name: route.name,
    title: route.meta?.title || route.name,
    icon: route.meta?.icon || null,
    closable: route.meta?.closable !== false && route.path !== '/',
    cache: route.meta?.cache !== false
  }
}

function loadStoredState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return {
        tabs: [DEFAULT_TAB],
        activeTab: DEFAULT_TAB.path,
        refreshKeys: { [DEFAULT_TAB.path]: 0 }
      }
    }

    const parsed = JSON.parse(raw)
    const validPaths = getValidRoutePaths()
    const storedTabs = Array.isArray(parsed?.tabs)
      ? parsed.tabs
          .map(normalizeStoredTab)
          .filter(tab => tab && validPaths.has(tab.path))
      : []

    const tabs = storedTabs.length
      ? [DEFAULT_TAB, ...storedTabs.filter(tab => tab.path !== DEFAULT_TAB.path)]
      : [DEFAULT_TAB]

    const refreshKeys = { [DEFAULT_TAB.path]: 0 }
    tabs.forEach((tab) => {
      refreshKeys[tab.path] = Number(parsed?.refreshKeys?.[tab.path] || 0)
    })

    return {
      tabs,
      activeTab: validPaths.has(parsed?.activeTab) ? parsed.activeTab : DEFAULT_TAB.path,
      refreshKeys
    }
  } catch (_) {
    return {
      tabs: [DEFAULT_TAB],
      activeTab: DEFAULT_TAB.path,
      refreshKeys: { [DEFAULT_TAB.path]: 0 }
    }
  }
}

export const useTabStore = defineStore('tabs', {
  state: () => loadStoredState(),

  getters: {
    cachedViewNames: state => state.tabs.filter(tab => tab.cache).map(tab => tab.name),
    activeTabItem: state => state.tabs.find(tab => tab.path === state.activeTab) || state.tabs[0] || DEFAULT_TAB,
    orderedClosableTabs: state => state.tabs.filter(tab => tab.closable),
    viewKey: state => (path, fallback = '') => `${path || fallback}::${Number(state.refreshKeys[path] || 0)}`
  },

  actions: {
    persist() {
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            tabs: this.tabs,
            activeTab: this.activeTab,
            refreshKeys: this.refreshKeys
          })
        )
      } catch (_) {}
    },

    ensureRefreshKey(path) {
      if (typeof this.refreshKeys[path] !== 'number') {
        this.refreshKeys[path] = 0
      }
    },

    dropRefreshKey(path) {
      if (path === DEFAULT_TAB.path) {
        this.refreshKeys[path] = 0
        return
      }
      delete this.refreshKeys[path]
    },

    openTab(route) {
      if (!route?.path || !route?.name) return

      const nextTab = buildTabFromRoute(route)
      const existingIndex = this.tabs.findIndex(tab => tab.path === route.path)

      if (existingIndex === -1) {
        this.tabs.push(nextTab)
      } else {
        this.tabs[existingIndex] = {
          ...this.tabs[existingIndex],
          ...nextTab
        }
      }

      this.ensureRefreshKey(route.path)
      this.activeTab = route.path
      this.persist()
    },

    async switchTab(path) {
      if (!path) return
      this.activeTab = path
      this.persist()

      if (router.currentRoute.value.path !== path) {
        await router.push(path)
      }
    },

    refreshTab(path = this.activeTab) {
      if (!path) return
      this.ensureRefreshKey(path)
      this.refreshKeys[path] += 1
      this.persist()
    },

    async closeTab(path) {
      const index = this.tabs.findIndex(tab => tab.path === path)
      if (index === -1 || !this.tabs[index].closable) return

      const isActive = this.activeTab === path
      this.tabs.splice(index, 1)
      this.dropRefreshKey(path)

      if (!this.tabs.length) {
        this.tabs = [DEFAULT_TAB]
      }

      if (isActive) {
        const fallback = this.tabs[index] || this.tabs[index - 1] || this.tabs[0] || DEFAULT_TAB
        this.activeTab = fallback.path
        this.persist()
        if (router.currentRoute.value.path !== fallback.path) {
          await router.push(fallback.path)
        }
        return
      }

      this.persist()
    },

    async closeOthers(path) {
      const keep = new Set([DEFAULT_TAB.path, path])
      this.tabs = this.tabs.filter(tab => !tab.closable || keep.has(tab.path))
      Object.keys(this.refreshKeys).forEach((key) => {
        if (!keep.has(key)) this.dropRefreshKey(key)
      })
      if (!this.tabs.some(tab => tab.path === path)) {
        this.tabs.unshift(DEFAULT_TAB)
      }
      await this.switchTab(path)
    },

    async closeRight(path) {
      const currentIndex = this.tabs.findIndex(tab => tab.path === path)
      if (currentIndex === -1) return

      const removedTabs = this.tabs.slice(currentIndex + 1).filter(tab => tab.closable)
      const removedActiveTab = removedTabs.some(tab => tab.path === this.activeTab)

      removedTabs.forEach(tab => this.dropRefreshKey(tab.path))
      this.tabs = this.tabs.filter((tab, index) => !tab.closable || index <= currentIndex)

      if (removedActiveTab) {
        await this.switchTab(path)
        return
      }

      this.persist()
    },

    async closeAll() {
      this.tabs = this.tabs.filter(tab => !tab.closable)
      this.refreshKeys = { [DEFAULT_TAB.path]: Number(this.refreshKeys[DEFAULT_TAB.path] || 0) }
      if (!this.tabs.length) {
        this.tabs = [DEFAULT_TAB]
      }
      await this.switchTab(this.tabs[0].path)
    }
  }
})
