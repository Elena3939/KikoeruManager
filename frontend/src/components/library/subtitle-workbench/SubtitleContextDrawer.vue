<template>
  <aside class="subtitle-context-drawer" :class="{ collapsed: ctx.drawerCollapsed }">
    <div class="subtitle-context-drawer-head">
      <div>
        <div class="subtitle-context-drawer-title">{{ ctx.modeTitle }}</div>
        <div v-if="!ctx.drawerCollapsed" class="subtitle-context-drawer-tip">{{ ctx.modeTip }}</div>
      </div>
      <el-button class="subtitle-context-toggle" circle size="small" @click="ctx.toggleDrawer()">
        <component :is="ctx.drawerCollapsed ? PanelRightOpen : PanelRightClose" :size="14" />
      </el-button>
    </div>

    <div v-if="ctx.drawerCollapsed" class="subtitle-context-collapsed-tabs">
      <button
        v-for="item in ctx.modeOptions"
        :key="item.key"
        type="button"
        class="subtitle-context-mini-tab"
        :class="{ active: ctx.contextMode === item.key }"
        :title="item.label"
        @click="ctx.setContextMode(item.key)"
      >
        {{ item.shortLabel }}
      </button>
    </div>

    <template v-else>
      <div class="subtitle-context-tabs">
        <button
          v-for="item in ctx.modeOptions"
          :key="item.key"
          type="button"
          class="subtitle-context-tab"
          :class="{ active: ctx.contextMode === item.key }"
          @click="ctx.setContextMode(item.key)"
        >
          {{ item.label }}
        </button>
      </div>

      <div class="subtitle-context-drawer-body">
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

<style scoped>
.subtitle-context-drawer {
  display: grid;
  gap: 12px;
  min-height: 0;
  align-self: start;
  padding: 16px;
  border: 1px solid rgba(223, 231, 239, 0.96);
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 251, 253, 0.98));
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.05);
  transition: width 0.28s cubic-bezier(0.34, 1.56, 0.64, 1), padding 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-context-drawer.collapsed {
  padding: 14px 10px;
}

.subtitle-context-drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.subtitle-context-drawer-title {
  font-size: 14px;
  font-weight: 900;
  color: #132335;
}

.subtitle-context-drawer-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #73859b;
}

.subtitle-context-toggle {
  flex-shrink: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-context-toggle:hover {
  transform: translateY(-2px) scale(1.04);
}

.subtitle-context-toggle:active {
  transform: scale(0.96);
}

.subtitle-context-toggle :deep(svg) {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.3s ease;
}

.subtitle-context-toggle:hover :deep(svg) {
  transform: scale(1.16) rotate(4deg);
}

.subtitle-context-tabs {
  display: flex;
  gap: 10px;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.subtitle-context-collapsed-tabs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0;
  background: transparent;
  border-radius: 12px;
}

.subtitle-context-tab,
.subtitle-context-mini-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 8px 14px;
  border-radius: 14px;
  border: 1px solid #d8e1ec;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
  color: #41546b;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.subtitle-context-mini-tab {
  min-width: unset;
  min-height: 36px;
  padding: 8px 6px;
  font-size: 11px;
}

.subtitle-context-tab:hover,
.subtitle-context-mini-tab:hover {
  color: #12273d;
  border-color: #c4d2e0;
  background: #ffffff;
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 18px rgba(15, 23, 42, 0.08);
}

.subtitle-context-tab:active,
.subtitle-context-mini-tab:active {
  transform: scale(0.97);
}

.subtitle-context-tab.active,
.subtitle-context-mini-tab.active {
  border-color: #142238;
  background: linear-gradient(180deg, #1c2b43 0%, #101b2e 100%);
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(16, 27, 46, 0.24);
}

.subtitle-context-drawer-body {
  min-height: 0;
  overflow: auto;
  padding-top: 2px;
}
</style>
