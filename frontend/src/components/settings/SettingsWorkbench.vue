<template>
  <div class="settings-workbench">
    <aside class="settings-sidebar">
      <div class="sidebar-shell">
        <label class="settings-search">
          <Search :size="15" :stroke-width="2.4" />
          <input :value="searchQuery" type="text" placeholder="搜索设置分组..." @input="$emit('update:searchQuery', $event.target.value)">
        </label>

        <nav class="settings-nav">
          <button
            v-for="section in filteredSections"
            :key="section.id"
            type="button"
            class="nav-item"
            :class="[`nav-item-${section.id}`, { active: activeSection === section.id }]"
            @click="$emit('navigate', section.id)"
          >
            <span class="nav-item-icon">
              <component :is="section.icon" :size="15" :stroke-width="2.2" />
            </span>
            <div class="nav-item-body">
              <div class="nav-item-title">{{ section.title }}</div>
              <div class="nav-item-desc">{{ section.short }}</div>
            </div>
            <span v-if="dirtyMap?.[section.id]" class="nav-badge is-dirty">已改</span>
          </button>
        </nav>

        <div class="sidebar-footer">
          <div v-if="configPath" class="sidebar-footer-meta" :title="configPath">
            <span class="sidebar-footer-label">配置文件</span>
            <span class="sidebar-footer-value">{{ configPath }}</span>
          </div>
          <button type="button" class="sidebar-ghost-btn" :disabled="reloading" @click="$emit('reload')">
            <RefreshCw :size="14" :stroke-width="2.4" :class="{ spinning: reloading }" />
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
        <div class="save-bar-info">
          <div class="save-bar-title">
            <span class="save-bar-dot" aria-hidden="true"></span>
            有未保存改动
          </div>
          <div class="save-bar-desc">改动会先保留在草稿里，确认后统一写回配置文件。</div>
        </div>
        <div class="save-bar-actions">
          <button type="button" class="save-bar-btn save-bar-btn-ghost" :disabled="saving" @click="$emit('reset-all')">放弃变更</button>
          <button type="button" class="save-bar-btn save-bar-btn-primary" :disabled="saving" @click="$emit('save')">
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
  configPath: { type: String, default: '' }
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
/* 视觉基线参考库存页：白底 + 18px 圆角 + 极淡阴影，不再走大圆角胖侧栏 */
.settings-workbench {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
}

.settings-sidebar {
  position: sticky;
  top: 16px;
  align-self: start;
}

/* ============================================================
 * 移动端 (≤1024)：双栏 → stack
 * sidebar 切到顶部横向滚动 chip 导航，footer/search 隐藏
 * ============================================================ */
@media (max-width: 1024px) {
  .settings-workbench {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .settings-sidebar {
    position: relative;
    top: auto;
  }
  .sidebar-shell {
    padding: 8px;
    border-radius: 14px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
  }
  /* 搜索 & footer 隐藏（移动端 6 个分组够直接横向 chip 切） */
  .settings-search,
  .sidebar-footer {
    display: none !important;
  }
  /* nav 改成横向滚动 chip row */
  .settings-nav {
    display: flex;
    flex-direction: row;
    gap: 6px;
    margin-top: 0;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    padding-bottom: 2px;
  }
  .settings-nav::-webkit-scrollbar { height: 4px; }
  .settings-nav::-webkit-scrollbar-thumb {
    background: rgba(148, 163, 184, 0.4);
    border-radius: 999px;
  }
  /* 每个 nav-item 改成 chip：图标 + 短标题，描述隐藏 */
  .nav-item {
    flex: 0 0 auto;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 80px;
    padding: 8px 12px;
    text-align: center;
    position: relative;
  }
  .nav-item-body {
    flex: 0 0 auto;
    text-align: center;
  }
  .nav-item-title {
    font-size: 11.5px;
    line-height: 1.15;
    white-space: nowrap;
  }
  .nav-item-desc {
    display: none;
  }
  .nav-badge {
    position: absolute;
    top: 2px;
    right: 4px;
    height: 14px;
    padding: 0 5px;
    font-size: 9px;
  }
  /* nav-item-icon 在 chip 中略放大 */
  .nav-item-icon {
    width: 28px;
    height: 28px;
  }
}

@media (max-width: 640px) {
  .nav-item {
    min-width: 72px;
    padding: 6px 10px;
  }
  .nav-item-title {
    font-size: 10.5px;
  }
}

.sidebar-shell {
  padding: 14px 12px 12px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.05);
}

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #94a3b8;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.settings-search:focus-within {
  border-color: rgba(148, 163, 184, 0.85);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.05);
}

.settings-search input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: #0f172a;
  font-size: 13px;
}

.settings-search input::placeholder { color: #94a3b8; }

.settings-nav {
  display: grid;
  gap: 4px;
  margin-top: 12px;
}

/* nav-item 对齐库存页 lib-btn-icon-tinted 风：白底 + 图标按 section 染色 + hover 微上抬 */
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: transparent;
  color: #334155;
  cursor: pointer;
  text-align: left;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.nav-item:hover {
  transform: translateY(-1px);
  background: rgba(248, 250, 252, 0.85);
  border-color: rgba(226, 232, 240, 0.85);
}

.nav-item:hover .nav-item-icon { transform: scale(1.08); }

.nav-item.active {
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.95) 0%, rgba(255, 255, 255, 0.96) 100%);
  border-color: rgba(199, 210, 254, 0.7);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 4px 12px -4px rgba(79, 70, 229, 0.18);
}

.nav-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 8px;
  color: #4f46e5;
  transition: transform 0.25s ease, color 0.25s ease;
}

/* 每个 section 一个颜色，跟库存页 lib-btn-icon-tinted 同一思路 */
.nav-item-storage     .nav-item-icon { color: #2563eb; }
.nav-item-processing  .nav-item-icon { color: #7c3aed; }
.nav-item-rules       .nav-item-icon { color: #d97706; }
.nav-item-services    .nav-item-icon { color: #059669; }
.nav-item-maintenance .nav-item-icon { color: #e11d48; }
.nav-item-notification .nav-item-icon { color: #4f46e5; }

.nav-item-body {
  flex: 1 1 auto;
  min-width: 0;
}

.nav-item-title {
  color: #1d1d1f;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  line-height: 1.3;
}

.nav-item-desc {
  margin-top: 2px;
  color: rgba(29, 29, 31, 0.55);
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  color: #b45309;
  border: 1px solid rgba(251, 191, 36, 0.5);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(245, 158, 11, 0.1);
}

.sidebar-footer {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed rgba(226, 232, 240, 0.85);
  display: grid;
  gap: 8px;
}

.sidebar-footer-meta {
  display: grid;
  gap: 2px;
  padding: 0 4px;
}

.sidebar-footer-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #94a3b8;
}

.sidebar-footer-value {
  font-size: 11.5px;
  color: rgba(29, 29, 31, 0.65);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all;
  line-height: 1.4;
}

.sidebar-ghost-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #334155;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sidebar-ghost-btn:not(:disabled):hover {
  transform: translateY(-1px);
  background: linear-gradient(135deg, #eff6ff 0%, #fff 100%);
  border-color: rgba(59, 130, 246, 0.55);
  color: #1d4ed8;
}

.sidebar-ghost-btn:disabled { opacity: 0.55; cursor: not-allowed; }

.settings-main,
.main-slot {
  min-width: 0;
}

.main-slot {
  display: grid;
  gap: 16px;
}

/* 保存栏：白底 + 主按钮走 AGENTS.md 三段渐变 + 双层 glow */
.save-bar {
  position: fixed;
  right: 24px;
  bottom: 22px;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  width: min(720px, calc(100vw - 280px));
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 18px 40px -12px rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(8px);
  pointer-events: auto;
}

.save-bar-info { min-width: 0; }

.save-bar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #1d1d1f;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.save-bar-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(180deg, #fbbf24 0%, #f59e0b 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.6),
    0 0 0 3px rgba(251, 191, 36, 0.18);
  animation: save-bar-dot-pulse 1.8s ease-in-out infinite;
}

@keyframes save-bar-dot-pulse {
  0%, 100% { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 0 0 3px rgba(251, 191, 36, 0.18); }
  50%      { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 0 0 5px rgba(251, 191, 36, 0.06); }
}

.save-bar-desc {
  margin-top: 3px;
  color: rgba(29, 29, 31, 0.55);
  font-size: 12px;
  line-height: 1.5;
}

.save-bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.save-bar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* 主按钮：180deg 三段渐变 + inset 顶部高光 + 双层 glow shadow */
.save-bar-btn-primary {
  color: #ffffff;
  background: linear-gradient(180deg, #1f2937 0%, #0f172a 60%, #020617 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 6px 16px -6px rgba(2, 6, 23, 0.55),
    0 2px 4px rgba(15, 23, 42, 0.25);
}

.save-bar-btn-primary:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 14px 28px -10px rgba(2, 6, 23, 0.6),
    0 4px 8px rgba(15, 23, 42, 0.3);
}

.save-bar-btn-primary:not(:disabled):active {
  transform: translateY(0) scale(0.97);
}

/* 次按钮：白底 ghost */
.save-bar-btn-ghost {
  background: #ffffff;
  border-color: rgba(226, 232, 240, 0.9);
  color: #475569;
}

.save-bar-btn-ghost:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.85);
  background: rgba(248, 250, 252, 0.85);
  color: #1d1d1f;
}

.save-bar-btn-ghost:not(:disabled):active {
  transform: scale(0.96);
}

.save-bar-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.spinning { animation: spin 1s linear infinite; }

.save-bar-enter-active,
.save-bar-leave-active { transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1); }

.save-bar-enter-from,
.save-bar-leave-to {
  opacity: 0;
  transform: translateY(18px);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1200px) {
  .settings-workbench { grid-template-columns: 1fr; }
  .settings-sidebar { position: static; }
  .save-bar { left: 18px; right: 18px; width: auto; }
}

@media (max-width: 768px) {
  .save-bar { flex-direction: column; align-items: stretch; }
  .save-bar-actions { width: 100%; }
  .save-bar-actions button { flex: 1; }
}

@media (max-width: 1024px) {
  .settings-workbench {
    display: flex !important;
    flex-direction: column !important;
    gap: 12px;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }
  .settings-sidebar {
    position: static !important;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }
  .sidebar-shell {
    padding: 8px !important;
    border-radius: 16px;
    overflow: hidden;
  }
  .settings-search,
  .sidebar-footer {
    display: none !important;
  }
  .settings-nav {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    gap: 8px !important;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    margin-top: 0 !important;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 2px 2px 6px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .settings-nav::-webkit-scrollbar {
    display: none;
  }
  .nav-item {
    width: auto !important;
    flex: 0 0 auto !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 5px !important;
    min-width: 86px;
    padding: 9px 10px !important;
    text-align: center !important;
    position: relative;
  }
  .nav-item-body {
    flex: 0 0 auto !important;
    width: 100%;
    min-width: 0;
    text-align: center !important;
  }
  .nav-item-title {
    font-size: 11.5px !important;
    line-height: 1.18;
    white-space: nowrap;
  }
  .nav-item-desc {
    display: none !important;
  }
  .nav-item-icon {
    width: 30px !important;
    height: 30px !important;
    border-radius: 10px;
  }
  .nav-badge {
    position: absolute;
    top: 3px;
    right: 4px;
    height: 14px;
    padding: 0 5px;
    font-size: 9px;
  }
  .main-slot {
    gap: 12px;
  }
}

@media (max-width: 640px) {
  .settings-workbench {
    gap: 10px;
  }
  .sidebar-shell {
    margin: 0 -2px;
    padding: 7px !important;
    border-radius: 14px;
  }
  .nav-item {
    min-width: 78px;
    padding: 8px 9px !important;
    border-radius: 12px;
  }
  .nav-item-title {
    font-size: 11px !important;
  }
  .nav-item-icon {
    width: 28px !important;
    height: 28px !important;
  }
  .save-bar {
    left: 10px;
    right: 10px;
    bottom: calc(10px + env(safe-area-inset-bottom));
    padding: 12px;
    border-radius: 16px;
  }
  .save-bar-desc {
    display: none;
  }
}
</style>

