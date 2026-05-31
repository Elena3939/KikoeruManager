<template>
  <aside
    class="subtitle-context-drawer relative grid h-full min-h-0 overflow-hidden rounded-[18px] border border-slate-100 bg-white transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
    :class="ctx.drawerCollapsed ? 'content-start gap-2 px-2 py-2.5' : 'grid-rows-[auto_auto_minmax(0,1fr)] gap-2 px-2 py-2'"
  >
    <!-- 浮动收纳手柄 -->
    <button
      type="button"
      class="rail-handle rail-handle-left group/handle"
      :class="{ 'rail-handle-collapsed': ctx.drawerCollapsed }"
      :aria-expanded="!ctx.drawerCollapsed"
      :aria-label="ctx.drawerCollapsed ? '展开配置面板' : '收起配置面板'"
      :title="ctx.drawerCollapsed ? '展开配置面板' : '收起配置面板'"
      @click="ctx.toggleDrawer()"
    >
      <component
        :is="ctx.drawerCollapsed ? ChevronsLeft : ChevronsRight"
        class="rail-handle-icon"
        :stroke-width="2.6"
      />
      <span class="rail-handle-label">{{ ctx.drawerCollapsed ? '展开' : '收起' }}</span>
      <span class="rail-handle-grip"></span>
    </button>

    <!-- 折叠态：窄导航条 -->
    <template v-if="ctx.drawerCollapsed">
      <div class="grid content-start gap-1.5">
        <button
          v-for="item in ctx.modeOptions"
          :key="item.key"
          type="button"
          class="subtitle-context-tab subtitle-context-tab-collapsed group relative inline-flex h-10 w-10 items-center justify-center self-center rounded-[10px] border text-slate-500 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.06] active:scale-[0.94]"
          :class="[getModeToneClass(item), ctx.contextMode === item.key ? 'is-active' : 'is-idle']"
          :title="item.label"
          :aria-pressed="ctx.contextMode === item.key"
          @click="ctx.setContextMode(item.key)"
        >
          <component
            :is="iconMap[item.icon]"
            class="subtitle-context-tab-icon h-4 w-4 shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
            :class="ctx.contextMode === item.key
              ? 'opacity-100 group-hover:-translate-y-0.5 group-hover:scale-[1.14] group-hover:rotate-[10deg]'
              : 'opacity-85 group-hover:opacity-100 group-hover:-translate-y-0.5 group-hover:rotate-[8deg] group-hover:scale-110'"
            :stroke-width="2.2"
          />
          <span
            v-if="ctx.contextMode === item.key"
            class="subtitle-context-tab-mark absolute left-[-4px] top-1/2 h-5 w-1 -translate-y-1/2 rounded-full"
          ></span>
        </button>
      </div>
    </template>

    <!-- 展开态 -->
    <template v-else>
      <div class="min-w-0">
        <div class="text-[13px] font-semibold tracking-[-0.01em] text-slate-900">{{ ctx.modeTitle }}</div>
        <div class="mt-0.5 line-clamp-1 text-[11px] leading-4 text-slate-500">{{ ctx.modeTip }}</div>
      </div>

      <div class="subtitle-context-tabs flex gap-1 rounded-[11px] border border-slate-200 bg-slate-100/80 p-0.5" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
        <button
          v-for="item in ctx.modeOptions"
          :key="item.key"
          type="button"
          class="subtitle-context-tab subtitle-context-tab-wide group flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-[8px] px-2 py-1 text-[11.5px] font-semibold transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
          :class="[getModeToneClass(item), ctx.contextMode === item.key ? 'is-active' : 'is-idle']"
          :aria-pressed="ctx.contextMode === item.key"
          @click="ctx.setContextMode(item.key)"
        >
          <component
            :is="iconMap[item.icon]"
            class="subtitle-context-tab-icon h-[13px] w-[13px] shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] opacity-90 group-hover:opacity-100 group-hover:-translate-y-0.5 group-hover:rotate-[12deg] group-hover:scale-[1.18]"
            :stroke-width="2.4"
          />
          <span>{{ item.label }}</span>
        </button>
      </div>

      <div class="min-h-0 overflow-hidden pt-0.5">
        <slot />
      </div>
    </template>
  </aside>
</template>

<script setup>
import { ChevronsLeft, ChevronsRight, Sliders, Link2, FolderTree } from 'lucide-vue-next'

const iconMap = { Sliders, Link2, FolderTree }
const modeToneClass = {
  settings: 'tone-settings',
  pairing: 'tone-pairing',
  tree: 'tone-tree'
}

function getModeToneClass(item) {
  return modeToneClass[item?.key] || 'tone-settings'
}

defineProps({
  ctx: {
    type: Object,
    required: true
  }
})
</script>

<style scoped>
@keyframes rail-handle-attn {
  0%, 100% { box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12), 0 0 0 0 rgba(15, 23, 42, 0.18); }
  50% { box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12), 0 0 0 6px rgba(15, 23, 42, 0); }
}

.rail-handle {
  position: absolute;
  top: 50%;
  z-index: 30;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 64px;
  width: 22px;
  padding: 0 4px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid #e2e8f0;
  color: #475569;
  cursor: pointer;
  overflow: hidden;
  transform: translateY(-50%);
  transition: width 0.32s cubic-bezier(0.34, 1.56, 0.64, 1),
              background 0.3s ease,
              color 0.3s ease,
              border-color 0.3s ease,
              box-shadow 0.3s ease;
  animation: rail-handle-attn 3.2s ease-in-out infinite;
}

.rail-handle-left {
  left: -11px;
  border-radius: 14px 6px 6px 14px;
  border-right: none;
}

.rail-handle:hover {
  width: 60px;
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
  animation: none;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.28);
}

.rail-handle:active {
  transform: translateY(-50%) scale(0.96);
}

.rail-handle-grip {
  width: 2px;
  height: 22px;
  border-radius: 2px;
  background: currentColor;
  opacity: 0.35;
  flex-shrink: 0;
  transition: opacity 0.3s ease;
}

.rail-handle:hover .rail-handle-grip {
  opacity: 0.65;
}

.rail-handle-icon {
  height: 14px;
  width: 14px;
  flex-shrink: 0;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.rail-handle-left:hover .rail-handle-icon {
  transform: translateX(2px);
}

.rail-handle-left.rail-handle-collapsed:hover .rail-handle-icon {
  transform: translateX(-2px);
}

.rail-handle-label {
  max-width: 0;
  overflow: hidden;
  white-space: nowrap;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0;
  transition: max-width 0.32s cubic-bezier(0.34, 1.56, 0.64, 1),
              opacity 0.2s ease 0.08s;
}

.rail-handle:hover .rail-handle-label {
  max-width: 40px;
  opacity: 1;
}

.subtitle-context-tabs {
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.02);
}

.subtitle-context-tab {
  --tab-accent: #64748b;
  --tab-accent-soft: rgba(100, 116, 139, 0.12);
  --tab-accent-border: rgba(100, 116, 139, 0.26);
  border-color: #e2e8f0;
  background: #ffffff;
  color: #64748b;
  box-shadow: none;
}

.subtitle-context-tab.tone-settings {
  --tab-accent: #d97706;
  --tab-accent-soft: rgba(245, 158, 11, 0.16);
  --tab-accent-border: rgba(217, 119, 6, 0.34);
}

.subtitle-context-tab.tone-pairing {
  --tab-accent: #059669;
  --tab-accent-soft: rgba(16, 185, 129, 0.16);
  --tab-accent-border: rgba(5, 150, 105, 0.34);
}

.subtitle-context-tab.tone-tree {
  --tab-accent: #7c3aed;
  --tab-accent-soft: rgba(124, 58, 237, 0.15);
  --tab-accent-border: rgba(124, 58, 237, 0.34);
}

.subtitle-context-tab.is-idle {
  background: transparent;
  border-color: transparent;
}

.subtitle-context-tab.is-idle .subtitle-context-tab-icon {
  color: var(--tab-accent);
}

.subtitle-context-tab.is-idle:hover {
  background: #ffffff;
  border-color: var(--tab-accent-border);
  color: #0f172a;
  box-shadow: none;
}

.subtitle-context-tab.is-active {
  background: var(--tab-accent-soft);
  border-color: var(--tab-accent-border);
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.72);
  transform: scale(1.02);
}

.subtitle-context-tab.is-active .subtitle-context-tab-icon {
  color: var(--tab-accent);
}

.subtitle-context-tab-mark {
  background: var(--tab-accent);
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer {
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
  text-shadow: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .text-slate-900 {
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .text-slate-500 {
  color: rgba(214, 214, 220, 0.66) !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tabs {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tab {
  color: rgba(214, 214, 220, 0.76) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tab.is-idle {
  background: transparent !important;
  border-color: transparent !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tab.is-idle:hover {
  background: #303136 !important;
  border-color: var(--tab-accent-border) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tab.is-active {
  background: color-mix(in srgb, var(--tab-accent) 28%, #24252a) !important;
  border-color: var(--tab-accent-border) !important;
  color: #ffffff !important;
  outline: 1px solid rgba(255, 255, 255, 0.22) !important;
  outline-offset: -1px !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .subtitle-context-tab-icon {
  color: var(--tab-accent) !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .rail-handle {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.78) !important;
  box-shadow: none !important;
  animation: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-context-drawer .rail-handle:hover {
  background: #3a3b40 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
</style>
