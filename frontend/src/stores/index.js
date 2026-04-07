import { defineStore } from 'pinia'
import { configApi, watcherApi } from '../api'

export const useConfigStore = defineStore('config', {
  state: () => ({
    config: null,
    loading: false
  }),

  actions: {
    async fetchConfig() {
      try {
        this.loading = true
        this.config = await configApi.get()
        console.log('[ConfigStore] 配置已获取:', this.config)
        return this.config  // 返回获取到的配置数据
      } catch (error) {
        console.error('获取配置失败:', error)
        throw error
      } finally {
        this.loading = false
      }
    },

    async saveConfig(configData) {
      try {
        this.loading = true
        const result = await configApi.save(configData)
        this.config = result.config || configData
        return result
      } catch (error) {
        console.error('保存配置失败:', error)
        throw error
      } finally {
        this.loading = false
      }
    }
  }
})

export const useWatcherStore = defineStore('watcher', {
  state: () => ({
    status: {
      is_running: false,
      watch_path: '',
      pending_files: []
    }
  }),

  actions: {
    async fetchStatus() {
      try {
        this.status = await watcherApi.status()
      } catch (error) {
        console.error('获取监视器状态失败:', error)
      }
    },

    async start() {
      try {
        await watcherApi.start()
        await this.fetchStatus()
      } catch (error) {
        console.error('启动监视器失败:', error)
        throw error
      }
    },

    async stop() {
      try {
        await watcherApi.stop()
        await this.fetchStatus()
      } catch (error) {
        console.error('停止监视器失败:', error)
        throw error
      }
    }
  }
})
