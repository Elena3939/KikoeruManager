<template>
  <section class="subtitle-workbench-stage relative h-full min-h-0 flex-1 overflow-hidden">
    <div
      class="absolute inset-0 grid min-h-0 grid-rows-[minmax(0,1fr)] items-stretch gap-3 overflow-hidden"
      :class="gridClass"
    >
      <aside
        class="relative min-w-0 overflow-hidden rounded-[18px] border border-slate-100 bg-white transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        :class="leftRailCollapsed ? 'grid content-start gap-2 px-2 py-2.5' : 'grid grid-rows-[auto_minmax(0,1fr)] gap-3 px-3 py-3'"
      >
        <!-- 浮动收纳手柄 -->
        <button
          type="button"
          class="rail-handle rail-handle-right group/handle"
          :class="{ 'rail-handle-collapsed': leftRailCollapsed }"
          :aria-expanded="!leftRailCollapsed"
          :aria-label="leftRailCollapsed ? '展开任务栏' : '收起任务栏'"
          :title="leftRailCollapsed ? '展开任务栏' : '收起任务栏'"
          @click="leftRailCollapsed = !leftRailCollapsed"
        >
          <span class="rail-handle-grip"></span>
          <component
            :is="leftRailCollapsed ? ChevronsRight : ChevronsLeft"
            class="rail-handle-icon"
            :stroke-width="2.6"
          />
          <span class="rail-handle-label">{{ leftRailCollapsed ? '展开' : '收起' }}</span>
        </button>

        <!-- 折叠态：窄导航条 -->
        <template v-if="leftRailCollapsed">
          <div v-if="ctx.railModes.length > 1" class="grid content-start gap-1.5">
            <button
              v-for="item in ctx.railModes"
              :key="item.key"
              type="button"
              class="group relative inline-flex h-10 w-10 items-center justify-center self-center rounded-[10px] border text-slate-500 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.06] active:scale-[0.94]"
              :class="ctx.railMode === item.key
                ? 'border-slate-900 bg-slate-900 text-white shadow-[0_6px_14px_rgba(15,23,42,0.2)]'
                : 'border-slate-100 bg-white hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 hover:shadow-[0_4px_12px_rgba(15,23,42,0.06)]'"
              :title="item.label"
              @click="ctx.setRailMode(item.key)"
            >
              <component
                :is="getRailTabIcon(item.key)"
                class="h-4 w-4 shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
                :class="ctx.railMode === item.key
                  ? 'opacity-100 group-hover:-translate-y-0.5 group-hover:scale-[1.14] group-hover:rotate-[10deg]'
                  : 'opacity-85 group-hover:opacity-100 group-hover:-translate-y-0.5 group-hover:scale-110 group-hover:rotate-[8deg]'"
                :stroke-width="2.2"
              />
              <span
                v-if="ctx.railMode === item.key"
                class="absolute right-[-4px] top-1/2 h-5 w-1 -translate-y-1/2 rounded-full bg-slate-900"
              ></span>
            </button>
          </div>
          <div v-else class="grid h-10 w-10 place-items-center self-center rounded-[10px] border border-slate-100 bg-white text-slate-500">
            <component
              :is="getRailTabIcon(ctx.railMode)"
              class="h-4 w-4"
              :stroke-width="2.2"
            />
          </div>
        </template>

        <!-- 展开态 -->
        <template v-else>
          <div v-if="ctx.railModes.length > 1" class="flex gap-1 rounded-[12px] border border-slate-200 bg-slate-100/80 p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
            <button
              v-for="item in ctx.railModes"
              :key="item.key"
              type="button"
              class="group flex flex-1 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-[8px] px-2 py-1.5 text-[12px] font-semibold transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
              :class="ctx.railMode === item.key
                ? 'bg-slate-900 text-white shadow-[0_4px_12px_rgba(15,23,42,0.22)] scale-[1.02]'
                : 'text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-[0_2px_6px_rgba(15,23,42,0.06)]'"
              @click="ctx.setRailMode(item.key)"
            >
              <component
                :is="getRailTabIcon(item.key)"
                class="h-[13px] w-[13px] shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] opacity-90 group-hover:opacity-100 group-hover:-translate-y-0.5 group-hover:rotate-[12deg] group-hover:scale-[1.18]"
                :stroke-width="2.4"
              />
              <span>{{ item.label }}</span>
            </button>
          </div>

          <div class="subtitle-left-rail-content min-h-0 overflow-hidden">
            <SubtitleScanRail v-if="ctx.railMode === 'scan'" :ctx="ctx.scanCtx" embedded />
            <SubtitleTaskNavigator v-else :ctx="ctx.taskNavigatorCtx" />
          </div>
        </template>
      </aside>

      <div class="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden" style="isolation: isolate;">
        <div class="flex gap-1 rounded-[12px] border border-slate-200 bg-slate-100/80 p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
          <button
            v-for="item in ctx.stageTabs"
            :key="item.key"
            type="button"
            class="group flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-[8px] px-4 py-2 text-[12.5px] font-semibold transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
            :class="ctx.activeStage === item.key
              ? 'bg-slate-900 text-white shadow-[0_6px_16px_rgba(15,23,42,0.25)] scale-[1.02]'
              : 'text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-[0_2px_6px_rgba(15,23,42,0.06)]'"
            @click="ctx.setActiveStage(item.key)"
          >
            <component
              :is="getStageTabIcon(item.key)"
              class="h-3.5 w-3.5 shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] opacity-90 group-hover:opacity-100 group-hover:-translate-y-0.5 group-hover:rotate-[12deg] group-hover:scale-[1.18]"
              :stroke-width="2.4"
            />
            <span>{{ item.label }}</span>
          </button>
        </div>

        <div class="min-h-0 min-w-0 overflow-hidden">
          <SubtitleTaskStage
            v-if="ctx.activeStage === 'overview'"
            :ctx="ctx.taskOverviewCtx"
            mode="overview"
            immersive
          />
          <SubtitleInspectorWorkbench
            v-else
            :ctx="ctx.workbenchCtx"
            :stage-mode="ctx.activeStage === 'pairing' ? 'pairing' : 'tree'"
            :show-delete-precheck="ctx.activeStage !== 'pairing'"
            immersive
          />
        </div>
      </div>

      <SubtitleContextDrawer :ctx="ctx.contextDrawerCtx">
        <SubtitleConfigRail
          v-if="ctx.contextMode === 'settings'"
          :ctx="ctx.configCtx"
          mode="settings"
        />
        <SubtitleConfigRail
          v-else-if="ctx.contextMode === 'pairing'"
          :ctx="ctx.configCtx"
          mode="pairing"
        />
        <SubtitleConfigRail
          v-else
          :ctx="ctx.configCtx"
          mode="tree"
        />
      </SubtitleContextDrawer>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import SubtitleInspectorWorkbench from '../SubtitleInspectorWorkbench.vue'
import SubtitleConfigRail from './SubtitleConfigRail.vue'
import SubtitleScanRail from './SubtitleScanRail.vue'
import SubtitleTaskNavigator from './SubtitleTaskNavigator.vue'
import SubtitleTaskStage from './SubtitleTaskStage.vue'
import SubtitleContextDrawer from './SubtitleContextDrawer.vue'
import { ChevronsLeft, ChevronsRight, FolderTree, Link2, ListChecks, ListTodo, Search } from 'lucide-vue-next'

function getRailTabIcon(key) {
  return { scan: Search, tasks: ListTodo }[key] || Search
}

function getStageTabIcon(key) {
  return { overview: ListChecks, pairing: Link2, tree: FolderTree }[key] || ListChecks
}

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  }
})

const leftRailCollapsed = ref(false)
const isRightCollapsed = computed(() => Boolean(props.ctx?.contextDrawerCtx?.drawerCollapsed))
const gridClass = computed(() => {
  if (leftRailCollapsed.value && isRightCollapsed.value) return 'grid-cols-[56px_minmax(0,1fr)_56px]'
  if (leftRailCollapsed.value) return 'grid-cols-[56px_minmax(0,2.64fr)_minmax(312px,0.86fr)]'
  if (isRightCollapsed.value) return 'grid-cols-[minmax(236px,0.74fr)_minmax(0,2.82fr)_56px]'
  return 'grid-cols-[minmax(224px,0.7fr)_minmax(0,2.28fr)_minmax(312px,0.86fr)]'
})
</script>

<style scoped>
@keyframes nudge-r {
  0%, 70%, 100% { transform: translateX(0); }
  85% { transform: translateX(3px); }
}
@keyframes nudge-l {
  0%, 70%, 100% { transform: translateX(0); }
  85% { transform: translateX(-3px); }
}
@keyframes rail-handle-attn {
  0%, 100% { box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12), 0 0 0 0 rgba(15, 23, 42, 0.18); }
  50% { box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12), 0 0 0 6px rgba(15, 23, 42, 0); }
}

/* 浮动手柄：竖向胶囊，悬挂在 aside 内侧边缘 */
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

.rail-handle-right {
  right: -11px;
  border-radius: 6px 14px 14px 6px;
  border-left: none;
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

.rail-handle-right:hover .rail-handle-icon {
  transform: translateX(-2px);
}

.rail-handle-right.rail-handle-collapsed:hover .rail-handle-icon {
  transform: translateX(2px);
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

.subtitle-left-rail-content :deep(> *) {
  height: 100%;
  min-height: 0;
}

.subtitle-left-rail-content :deep(.grid.content-start),
.subtitle-left-rail-content :deep(.grid[style*="content-start"]) {
  overflow: hidden;
}

:deep(.subtitle-task-stage-root),
:deep(.subtitle-inspector-workbench-root) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.sub-stage-fade-enter-active,
.sub-stage-fade-leave-active {
  transition: opacity 0.28s cubic-bezier(0.4, 0, 0.2, 1), transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.sub-stage-fade-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
.sub-stage-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.99);
}

@media (max-width: 640px) {
  section {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }
  section > div {
    display: flex !important;
    flex-direction: column !important;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 10px !important;
  }
  aside {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    padding: 12px !important;
    border-radius: 16px !important;
    overflow: hidden;
  }
  aside > .min-h-0 {
    max-height: 300px;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
  }
  .rail-handle {
    display: none !important;
  }
  section > div > div {
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }
  section > div > div > div:first-child {
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  section > div > div > div:first-child::-webkit-scrollbar {
    display: none;
  }
  section > div > div > div:first-child button {
    min-width: 78px;
    flex: 0 0 auto;
    padding-left: 10px !important;
    padding-right: 10px !important;
    font-size: 11.5px !important;
    white-space: nowrap;
  }
  section > div > div > div:first-child button span {
    white-space: nowrap;
  }
  section > div > div > div:nth-child(2) {
    padding: 12px !important;
    border-radius: 16px !important;
  }
  section > div > div > div:nth-child(2) > div:first-child {
    flex-direction: column;
  }
  :deep(.subtitle-context-drawer),
  :deep(.subtitle-context-drawer *) {
    max-width: 100%;
    min-width: 0;
  }
}
</style>
