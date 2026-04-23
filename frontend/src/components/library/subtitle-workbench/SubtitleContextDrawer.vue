<template>
  <aside
    class="relative grid min-h-0 self-start rounded-[20px] border border-slate-100 bg-white shadow-[0_4px_16px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
    :class="ctx.drawerCollapsed ? 'gap-2 px-2 py-2.5' : 'gap-3.5 px-4 py-4'"
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
          class="group relative inline-flex h-10 w-10 items-center justify-center self-center rounded-[10px] border text-slate-500 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.06] active:scale-[0.94]"
          :class="ctx.contextMode === item.key
            ? 'border-slate-900 bg-slate-900 text-white shadow-[0_6px_14px_rgba(15,23,42,0.2)]'
            : 'border-slate-100 bg-white hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 hover:shadow-[0_4px_12px_rgba(15,23,42,0.06)]'"
          :title="item.label"
          @click="ctx.setContextMode(item.key)"
        >
          <component
            :is="iconMap[item.icon]"
            class="h-4 w-4 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
            :class="ctx.contextMode === item.key ? '' : 'group-hover:rotate-[8deg] group-hover:scale-110'"
            :stroke-width="2.2"
          />
          <span
            v-if="ctx.contextMode === item.key"
            class="absolute left-[-4px] top-1/2 h-5 w-1 -translate-y-1/2 rounded-full bg-slate-900"
          ></span>
        </button>
      </div>
    </template>

    <!-- 展开态 -->
    <template v-else>
      <div class="min-w-0">
        <div class="text-[13px] font-semibold tracking-[-0.01em] text-slate-900">{{ ctx.modeTitle }}</div>
        <div class="mt-1 text-[12px] leading-6 text-slate-500">{{ ctx.modeTip }}</div>
      </div>

      <div class="flex gap-1 rounded-[12px] border border-slate-200 bg-slate-100/80 p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
        <button
          v-for="item in ctx.modeOptions"
          :key="item.key"
          type="button"
          class="group flex flex-1 items-center justify-center gap-1.5 rounded-[8px] px-3 py-1.5 text-[12px] font-semibold transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
          :class="ctx.contextMode === item.key
            ? 'bg-slate-900 text-white shadow-[0_4px_12px_rgba(15,23,42,0.22)] scale-[1.02]'
            : 'text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-[0_2px_6px_rgba(15,23,42,0.06)]'"
          @click="ctx.setContextMode(item.key)"
        >
          <component :is="iconMap[item.icon]" class="h-[13px] w-[13px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:rotate-[12deg] group-hover:scale-[1.18]" :stroke-width="2.4" />
          <span>{{ item.label }}</span>
        </button>
      </div>

      <div class="min-h-0 overflow-auto pt-0.5">
        <slot />
      </div>
    </template>
  </aside>
</template>

<script setup>
import { ChevronsLeft, ChevronsRight, Sliders, Link2, FolderTree } from 'lucide-vue-next'

const iconMap = { Sliders, Link2, FolderTree }

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
</style>
