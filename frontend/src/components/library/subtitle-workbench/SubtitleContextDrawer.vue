<template>
  <aside
    class="relative grid min-h-0 self-start rounded-[20px] bg-[#f5f5f7] shadow-[inset_0_0_0_1px_rgba(29,29,31,0.06)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
    :class="ctx.drawerCollapsed ? 'gap-3 px-2.5 py-3.5' : 'gap-3 px-4 py-4'"
  >
    <button
      type="button"
      class="group absolute left-[-9px] top-1/2 z-10 inline-flex h-16 w-[18px] -translate-y-1/2 items-center justify-center rounded-l-[12px] border border-r-0 border-black/8 bg-gradient-to-b from-[#fbfbfd] to-[#f0f0f2] text-black/55 shadow-[0_4px_12px_rgba(0,0,0,0.08)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.02] hover:border-[#bfd7ff] hover:text-[#0071e3] hover:shadow-[0_8px_16px_rgba(0,113,227,0.12)] active:scale-[0.96]"
      :aria-label="ctx.drawerCollapsed ? '展开右侧栏' : '收起右侧栏'"
      @click="ctx.toggleDrawer()"
    >
      <component
        :is="ctx.drawerCollapsed ? PanelRightOpen : PanelRightClose"
        class="h-3.5 w-3.5 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110"
      />
    </button>

    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="text-[13px] font-semibold tracking-[-0.01em] text-[#1d1d1f]">{{ ctx.modeTitle }}</div>
        <div v-if="!ctx.drawerCollapsed" class="mt-1 text-[12px] leading-6 text-black/45">{{ ctx.modeTip }}</div>
      </div>
    </div>

    <div
      v-if="ctx.drawerCollapsed"
      class="flex flex-col gap-2"
    >
      <button
        v-for="item in ctx.modeOptions"
        :key="item.key"
        type="button"
        class="inline-flex min-h-8 items-center justify-center rounded-[10px] border border-black/6 bg-white px-1.5 py-1.5 text-[11px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02]"
        :class="ctx.contextMode === item.key
          ? 'bg-[#1d1d1f] text-white shadow-[0_10px_18px_rgba(29,29,31,0.18)]'
          : 'text-[#3c3c43] hover:bg-[#fbfbfd] hover:text-[#1d1d1f]'"
        :title="item.label"
        @click="ctx.setContextMode(item.key)"
      >
        {{ item.shortLabel }}
      </button>
    </div>

    <template v-else>
      <div class="flex gap-1 rounded-[14px] border border-slate-200 bg-white p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
        <button
          v-for="item in ctx.modeOptions"
          :key="item.key"
          type="button"
          class="flex-1 rounded-[10px] px-3 py-2 text-[12px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02]"
          :class="ctx.contextMode === item.key
            ? 'bg-[#1d1d1f] text-white shadow-[0_10px_18px_rgba(29,29,31,0.18)]'
            : 'text-[#3c3c43] hover:bg-[#fbfbfd] hover:text-[#1d1d1f]'"
          @click="ctx.setContextMode(item.key)"
        >
          {{ item.label }}
        </button>
      </div>

      <div class="min-h-0 overflow-auto pt-0.5">
        <slot />
      </div>
    </template>
  </aside>
</template>

<script setup>
import { PanelRightClose, PanelRightOpen } from 'lucide-vue-next'

defineProps({
  ctx: {
    type: Object,
    required: true
  }
})
</script>
