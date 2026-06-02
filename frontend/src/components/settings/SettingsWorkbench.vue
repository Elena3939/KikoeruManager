<template>
  <div class="settings-workbench">
    <aside class="settings-sidebar">
      <div class="settings-sidebar-shell">
        <label class="settings-search">
          <Search :size="15" :stroke-width="2.4" />
          <input :value="searchQuery" type="text" placeholder="搜索设置分组..." @input="$emit('update:searchQuery', $event.target.value)">
        </label>

        <nav class="settings-nav">
          <button
            v-for="section in filteredSections"
            :key="section.id"
            type="button"
            class="settings-nav-item"
            :class="[`settings-nav-item-${section.id}`, { active: activeSection === section.id }]"
            @click="$emit('navigate', section.id)"
          >
            <span class="settings-nav-item-icon">
              <component :is="section.icon" :size="15" :stroke-width="2.2" />
            </span>
            <div class="settings-nav-item-body">
              <div class="settings-nav-item-title">{{ section.title }}</div>
              <div class="settings-nav-item-desc">{{ section.short }}</div>
            </div>
            <span v-if="dirtyMap?.[section.id]" class="settings-nav-badge is-dirty">已改</span>
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
  .settings-sidebar-shell {
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
  /* 每个导航项改成 chip：图标 + 短标题，描述隐藏 */
  .settings-nav-item {
    flex: 0 0 auto;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 80px;
    padding: 8px 12px;
    text-align: center;
    position: relative;
  }
  .settings-nav-item-body {
    flex: 0 0 auto;
    text-align: center;
  }
  .settings-nav-item-title {
    font-size: 11.5px;
    line-height: 1.15;
    white-space: nowrap;
  }
  .settings-nav-item-desc {
    display: none;
  }
  .settings-nav-badge {
    position: absolute;
    top: 2px;
    right: 4px;
    height: 14px;
    padding: 0 5px;
    font-size: 9px;
  }
  /* 导航图标在 chip 中略放大 */
  .settings-nav-item-icon {
    width: 28px;
    height: 28px;
  }
}

@media (max-width: 640px) {
  .settings-nav-item {
    min-width: 72px;
    padding: 6px 10px;
  }
  .settings-nav-item-title {
    font-size: 10.5px;
  }
}

.settings-sidebar-shell {
  box-sizing: border-box;
  width: 100%;
  padding: 14px 12px 12px;
  border-radius: 18px;
  background: var(--set-surface, rgba(255, 255, 255, 0.94));
  border: 1px solid var(--set-border-soft, transparent);
  box-shadow: var(--set-shadow, 0 12px 30px rgba(0, 0, 0, 0.05));
  overflow: hidden;
}

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid var(--set-border, rgba(226, 232, 240, 0.85));
  background: var(--set-field-bg, #ffffff);
  color: var(--set-text-subtle, #94a3b8);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.settings-search:focus-within {
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.85));
  box-shadow: 0 0 0 3px var(--set-accent-soft, rgba(15, 23, 42, 0.05));
}

.settings-search input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--set-text-strong, #0f172a);
  font-size: 13px;
}

.settings-search input::placeholder { color: var(--set-text-subtle, #94a3b8); }

.settings-nav {
  display: grid;
  gap: 4px;
  margin-top: 12px;
}

/* 设置导航：图标直接按模块语义染色，不再套灰色底块 */
.settings-nav-item {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  max-width: 100%;
  padding: 9px 10px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--set-text, #334155);
  cursor: pointer;
  text-align: left;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  overflow: hidden;
}

.settings-nav-item:hover {
  transform: translateY(-1px);
  background: var(--set-surface-hover, rgba(248, 250, 252, 0.85));
  border-color: var(--set-border, rgba(226, 232, 240, 0.85));
}

.settings-nav-item:hover .settings-nav-item-icon { transform: scale(1.08); }

.settings-nav-item.active {
  background: var(--set-surface-muted, rgba(241, 245, 249, 0.95));
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.36));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    var(--set-shadow, 0 4px 12px -4px rgba(15, 23, 42, 0.12));
}

.settings-nav-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 0;
  background: transparent;
  border: none;
  color: var(--settings-nav-icon, var(--set-text-muted, #64748b));
  transition: transform 0.25s ease, color 0.25s ease;
}

.settings-nav-item-storage { --settings-nav-icon: var(--set-nav-storage-icon, #0f766e); }
.settings-nav-item-processing { --settings-nav-icon: var(--set-nav-processing-icon, #b45309); }
.settings-nav-item-rules { --settings-nav-icon: var(--set-nav-rules-icon, #7c3aed); }
.settings-nav-item-services { --settings-nav-icon: var(--set-nav-services-icon, #0891b2); }
.settings-nav-item-aiSubtitle { --settings-nav-icon: var(--set-nav-ai-subtitle-icon, #0d9488); }
.settings-nav-item-httpDownload { --settings-nav-icon: var(--set-nav-http-download-icon, #0284c7); }
.settings-nav-item-maintenance { --settings-nav-icon: var(--set-nav-maintenance-icon, #c2410c); }
.settings-nav-item-fts { --settings-nav-icon: var(--set-nav-fts-icon, #4f46e5); }
.settings-nav-item-security { --settings-nav-icon: var(--set-nav-security-icon, #15803d); }
.settings-nav-item-notification { --settings-nav-icon: var(--set-nav-notification-icon, #be185d); }

.settings-nav-item-body {
  flex: 1 1 auto;
  min-width: 0;
}

.settings-nav-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--set-text-strong, #1d1d1f);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  line-height: 1.3;
}

.settings-nav-item-desc {
  margin-top: 2px;
  color: var(--set-text-muted, rgba(29, 29, 31, 0.55));
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-nav-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  max-width: 36px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: color-mix(in srgb, #f59e0b 13%, var(--set-surface));
  color: #b45309;
  border: 1px solid rgba(251, 191, 36, 0.5);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(245, 158, 11, 0.1);
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item) {
  border-color: transparent;
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item:hover) {
  background: rgba(255, 255, 255, 0.035);
  border-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item.active) {
  background: rgba(255, 255, 255, 0.055);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item-icon) {
  opacity: 0.82;
  filter: saturate(0.72) brightness(0.94);
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item:hover .settings-nav-item-icon),
:global(html.kikoerumanager-dark .settings-page .settings-nav-item.active .settings-nav-item-icon) {
  opacity: 0.96;
  filter: saturate(0.82) brightness(1);
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-item-httpDownload) {
  --settings-nav-icon: var(--set-nav-http-download-icon, #8aaebe);
}

:global(html.kikoerumanager-dark .settings-page .settings-nav-badge.is-dirty) {
  background: rgba(173, 136, 82, 0.12);
  color: #d7ba7d;
  border-color: rgba(202, 164, 101, 0.3);
  box-shadow: none;
}

.sidebar-footer {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--set-border, rgba(226, 232, 240, 0.85));
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
  color: var(--set-text-subtle, #94a3b8);
}

.sidebar-footer-value {
  font-size: 11.5px;
  color: var(--set-text-muted, rgba(29, 29, 31, 0.65));
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
  border: 1px solid var(--set-border, rgba(226, 232, 240, 0.85));
  background: var(--set-surface, #ffffff);
  color: var(--set-text, #334155);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sidebar-ghost-btn:not(:disabled):hover {
  transform: translateY(-1px);
  background: var(--set-surface-hover, rgba(248, 250, 252, 0.85));
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.75));
  color: var(--set-text-strong, #111827);
}

.sidebar-ghost-btn:hover:not(:disabled) svg:not(.spinning) {
  transform: rotate(-360deg);
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
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
  background: color-mix(in srgb, var(--set-surface, #ffffff) 96%, transparent);
  border: 1px solid var(--set-border, rgba(226, 232, 240, 0.9));
  box-shadow: var(--set-shadow-hover, 0 18px 40px -12px rgba(15, 23, 42, 0.18));
  backdrop-filter: blur(8px);
  pointer-events: auto;
}

.save-bar-info { min-width: 0; }

.save-bar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--set-text-strong, #1d1d1f);
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
  color: var(--set-text-muted, rgba(29, 29, 31, 0.55));
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
  background: linear-gradient(180deg, var(--set-accent-hover, #1f2937) 0%, var(--set-accent, #111827) 100%);
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
  background: var(--set-surface, #ffffff);
  border-color: var(--set-border, rgba(226, 232, 240, 0.9));
  color: var(--set-text, #475569);
}

.save-bar-btn-ghost:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong, rgba(148, 163, 184, 0.85));
  background: var(--set-surface-hover, rgba(248, 250, 252, 0.85));
  color: var(--set-text-strong, #1d1d1f);
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
  .settings-sidebar-shell {
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
  .settings-nav-item {
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
  .settings-nav-item-body {
    flex: 0 0 auto !important;
    width: 100%;
    min-width: 0;
    text-align: center !important;
  }
  .settings-nav-item-title {
    font-size: 11.5px !important;
    line-height: 1.18;
    white-space: nowrap;
  }
  .settings-nav-item-desc {
    display: none !important;
  }
  .settings-nav-item-icon {
    width: 30px !important;
    height: 30px !important;
    border-radius: 10px;
  }
  .settings-nav-badge {
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
  .settings-sidebar-shell {
    margin: 0 -2px;
    padding: 7px !important;
    border-radius: 14px;
  }
  .settings-nav-item {
    min-width: 78px;
    padding: 8px 9px !important;
    border-radius: 12px;
  }
  .settings-nav-item-title {
    font-size: 11px !important;
  }
  .settings-nav-item-icon {
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

