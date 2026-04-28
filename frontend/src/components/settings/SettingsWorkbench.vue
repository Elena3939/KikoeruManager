<template>
  <div class="settings-workbench">
    <aside class="settings-sidebar">
      <div class="sidebar-shell">
        <div class="sidebar-head">
          <p class="sidebar-kicker">Prekikoeru</p>
          <h1 class="sidebar-title">设置工作台</h1>
          <p class="sidebar-desc">把连接、目录、规则和外部服务放到统一的可读工作台里管理。</p>
        </div>

        <label class="settings-search">
          <Search :size="16" :stroke-width="2.4" />
          <input :value="searchQuery" type="text" placeholder="搜索设置分组..." @input="$emit('update:searchQuery', $event.target.value)">
        </label>

        <div class="sidebar-summary">
          <div class="summary-chip">
            <span class="summary-label">配置文件</span>
            <span class="summary-value">{{ configPath || '本地配置' }}</span>
          </div>
          <div class="summary-chip" :class="{ changed: hasChanges }">
            <span class="summary-label">草稿状态</span>
            <span class="summary-value">{{ hasChanges ? '有未保存改动' : '已同步' }}</span>
          </div>
          <div class="summary-chip">
            <span class="summary-label">最近保存</span>
            <span class="summary-value">{{ lastSavedLabel }}</span>
          </div>
        </div>

        <nav class="settings-nav">
          <button
            v-for="section in filteredSections"
            :key="section.id"
            type="button"
            class="nav-item"
            :class="{ active: activeSection === section.id }"
            @click="$emit('navigate', section.id)"
          >
            <div class="nav-item-main">
              <span class="nav-item-icon">
                <component :is="section.icon" :size="16" :stroke-width="2.3" />
              </span>
              <div>
                <div class="nav-item-title">{{ section.title }}</div>
                <div class="nav-item-desc">{{ section.short }}</div>
              </div>
            </div>
            <span v-if="dirtyMap?.[section.id]" class="nav-badge is-dirty">已改</span>
          </button>
        </nav>

        <div class="sidebar-footer">
          <button type="button" class="ghost-btn" :disabled="reloading" @click="$emit('reload')">
            <RefreshCw :size="15" :stroke-width="2.5" :class="{ spinning: reloading }" />
            从文件刷新
          </button>
        </div>
      </div>
    </aside>

    <main class="settings-main">
      <div class="main-slot">
        <slot />
      </div>
    </main>

    <transition name="save-bar">
      <div v-if="hasChanges" class="save-bar">
        <div>
          <div class="save-bar-title">有未保存改动</div>
          <div class="save-bar-desc">修改会先保留在当前草稿里，确认后统一写回配置文件。</div>
        </div>
        <div class="save-bar-actions">
          <button type="button" class="ghost-btn" :disabled="saving" @click="$emit('reset-all')">放弃变更</button>
          <button type="button" class="primary-btn" :disabled="saving" @click="$emit('save')">
            <LoaderCircle v-if="saving" :size="15" :stroke-width="2.5" class="spinning" />
            <Save v-else :size="15" :stroke-width="2.5" />
            保存配置
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { LoaderCircle, RefreshCw, Save, Search } from 'lucide-vue-next'

const props = defineProps({
  sections: { type: Array, required: true },
  activeSection: { type: String, required: true },
  searchQuery: { type: String, default: '' },
  hasChanges: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  reloading: { type: Boolean, default: false },
  dirtyMap: { type: Object, default: () => ({}) },
  configPath: { type: String, default: '' },
  lastSavedLabel: { type: String, default: '尚未保存' }
})

defineEmits(['navigate', 'save', 'reload', 'reset-all', 'update:searchQuery'])

const filteredSections = computed(() => {
  const query = String(props.searchQuery || '').trim().toLowerCase()
  if (!query) return props.sections
  return props.sections.filter(section => {
    const haystack = [section.title, section.short, ...(section.keywords || [])].join(' ').toLowerCase()
    return haystack.includes(query)
  })
})
</script>

<style scoped>
.settings-workbench {
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
  gap: 18px;
  min-height: calc(100vh - 88px);
}

.settings-sidebar {
  position: sticky;
  top: 18px;
  align-self: start;
}

.sidebar-shell {
  padding: 18px 16px 16px;
  border-radius: 24px;
  background: #fff;
  border: 1px solid rgba(226, 232, 240, 0.92);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(10px);
}

.sidebar-kicker {
  margin: 0 0 6px;
  color: #94a3b8;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.sidebar-title {
  margin: 0;
  color: #0f172a;
  font-size: 28px;
  line-height: 1;
  font-weight: 900;
  letter-spacing: -0.06em;
}

.sidebar-desc {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  margin-top: 14px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.95);
  color: #94a3b8;
}

.settings-search input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: #0f172a;
  font-size: 13px;
}

.sidebar-summary {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.summary-chip {
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(255, 255, 255, 0.8);
}

.summary-chip.changed {
  border-color: rgba(96, 165, 250, 0.45);
  background: rgba(239, 246, 255, 0.88);
}

.summary-label {
  display: block;
  color: #94a3b8;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.summary-value {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
}

.settings-nav {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 11px 12px;
  border-radius: 16px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(255, 255, 255, 0.86);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.nav-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.nav-item.active {
  border-color: rgba(96, 165, 250, 0.55);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.95), rgba(255, 255, 255, 0.98));
  box-shadow: 0 16px 36px rgba(59, 130, 246, 0.12);
}

.nav-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
}

.nav-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 11px;
  background: rgba(241, 245, 249, 0.95);
  color: #475569;
}

.nav-item-title {
  color: #0f172a;
  font-size: 13px;
  font-weight: 800;
}

.nav-item-desc {
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.nav-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
}

.nav-badge.is-dirty {
  background: rgba(239, 246, 255, 0.9);
  color: #2563eb;
  border: 1px solid rgba(191, 219, 254, 0.95);
}

.sidebar-footer {
  margin-top: 14px;
}

.settings-main {
  min-width: 0;
}

.main-slot {
  min-width: 0;
}

.save-bar {
  position: fixed;
  right: 24px;
  bottom: 22px;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  width: min(760px, calc(100vw - 340px));
  padding: 16px 18px;
  border-radius: 22px;
  border: 1px solid rgba(147, 197, 253, 0.85);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 26px 50px rgba(37, 99, 235, 0.16);
  backdrop-filter: blur(12px);
  pointer-events: none;
}

.save-bar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.save-bar-desc {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
}

.save-bar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  pointer-events: auto;
}

.primary-btn,
.ghost-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 42px;
  padding: 0 16px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  border: 1px solid transparent;
}

.primary-btn {
  background: #0f172a;
  color: #f8fafc;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
}

.ghost-btn {
  background: rgba(248, 250, 252, 0.95);
  border-color: rgba(226, 232, 240, 0.95);
  color: #334155;
}

.spinning {
  animation: spin 1s linear infinite;
}

.settings-fade-leave-active,
.save-bar-enter-active,
.save-bar-leave-active {
  transition: all 0.24s ease;
}

.save-bar-enter-from,
.save-bar-leave-to {
  opacity: 0;
  transform: translateY(18px);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1200px) {
  .settings-workbench {
    grid-template-columns: 1fr;
  }

  .settings-sidebar {
    position: static;
  }

  .save-bar {
    left: 18px;
    right: 18px;
    width: auto;
  }
}

@media (max-width: 768px) {
  .save-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .save-bar-actions {
    width: 100%;
    justify-content: stretch;
  }

  .save-bar-actions button {
    flex: 1;
  }
}
</style>
