<template>
  <section class="min-h-0">
    <div
      class="grid items-start gap-3.5"
      :class="gridClass"
    >
      <aside
        class="relative min-w-0 self-start rounded-[20px] border border-slate-100 bg-white shadow-[0_4px_16px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        :class="leftRailCollapsed ? 'grid gap-3 px-2.5 py-3.5' : 'grid gap-3.5 px-4 py-4'"
      >
        <button
          type="button"
          class="group absolute right-[-9px] top-1/2 z-10 inline-flex h-16 w-[18px] -translate-y-1/2 items-center justify-center rounded-r-[12px] border border-l-0 border-slate-100 bg-white text-slate-400 shadow-[0_2px_8px_rgba(15,23,42,0.05)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.02] hover:border-slate-300 hover:text-slate-900 hover:shadow-[0_4px_12px_rgba(15,23,42,0.08)] active:scale-[0.96]"
          :aria-label="leftRailCollapsed ? '展开左侧栏' : '收起左侧栏'"
          @click="leftRailCollapsed = !leftRailCollapsed"
        >
          <PanelLeftOpen
            v-if="leftRailCollapsed"
            class="h-3.5 w-3.5 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110"
            :stroke-width="2.2"
          />
          <PanelLeftClose
            v-else
            class="h-3.5 w-3.5 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110"
            :stroke-width="2.2"
          />
        </button>

        <template v-if="leftRailCollapsed">
          <div class="grid content-start gap-2">
            <button
              v-for="item in ctx.railModes"
              :key="item.key"
              type="button"
              class="inline-flex min-h-11 w-full items-center justify-center rounded-[12px] border border-slate-100 bg-white text-slate-900 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50"
              :class="ctx.railMode === item.key ? 'border-slate-900 bg-slate-900 text-white shadow-[0_6px_16px_rgba(15,23,42,0.18)]' : ''"
              :title="item.label"
              @click="ctx.setRailMode(item.key)"
            >
              <component :is="getRailTabIcon(item.key)" class="h-3.5 w-3.5 transition-transform duration-300 group-hover:scale-110" :stroke-width="2.2" />
            </button>
          </div>
        </template>

        <template v-else>
          <div class="flex gap-1 rounded-[12px] border border-slate-100 bg-slate-50/60 p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
            <button
              v-for="item in ctx.railModes"
              :key="item.key"
              type="button"
              class="group flex flex-1 items-center justify-center gap-1.5 rounded-[8px] px-3 py-1.5 text-[12px] font-medium transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
              :class="ctx.railMode === item.key
                ? 'bg-white text-slate-900 shadow-[0_2px_6px_rgba(15,23,42,0.08)]'
                : 'text-slate-900 hover:bg-white/60'"
              @click="ctx.setRailMode(item.key)"
            >
              <component :is="getRailTabIcon(item.key)" class="h-[13px] w-[13px] transition-transform duration-300 group-hover:scale-110" :stroke-width="2.2" />
              <span>{{ item.label }}</span>
            </button>
          </div>

          <div class="min-h-0">
            <SubtitleScanRail v-if="ctx.railMode === 'scan'" :ctx="ctx.scanCtx" embedded />
            <SubtitleTaskNavigator v-else :ctx="ctx.taskNavigatorCtx" />
          </div>
        </template>
      </aside>

      <div class="grid min-w-0 gap-3.5" style="isolation: isolate;">
        <div class="flex gap-1 rounded-[12px] border border-slate-100 bg-slate-50/60 p-1" style="position: relative; z-index: 60; pointer-events: auto; isolation: isolate;">
          <button
            v-for="item in ctx.stageTabs"
            :key="item.key"
            type="button"
            class="group flex flex-1 items-center justify-center gap-1.5 rounded-[8px] px-4 py-2 text-[12.5px] font-semibold transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
            :class="ctx.activeStage === item.key
              ? 'bg-white text-slate-900 shadow-[0_2px_8px_rgba(15,23,42,0.08)]'
              : 'text-slate-900 hover:bg-white/60'"
            @click="ctx.setActiveStage(item.key)"
          >
            <component :is="getStageTabIcon(item.key)" class="h-3.5 w-3.5 transition-transform duration-300 group-hover:scale-110" :stroke-width="2.2" />
            <span>{{ item.label }}</span>
          </button>
        </div>

        <div class="min-w-0">
          <Transition name="sub-stage-fade" mode="out-in">
            <SubtitleTaskStage
              v-if="ctx.taskOverviewCtx?.subtitleQueueTasks?.length"
              key="queue-rail"
              :ctx="ctx.taskOverviewCtx"
              mode="queue"
              immersive
            />
            <div
              v-else
              key="queue-empty"
              class="grid min-h-20 content-center gap-1.5 rounded-[14px] border border-dashed border-slate-200 bg-slate-50/40 px-3 py-2.5"
            >
              <div class="text-[13px] font-semibold text-slate-800">当前没有可展示任务</div>
              <div class="text-[12px] leading-6 text-slate-500">先在左侧“扫描命中”里选目录入队，任务卡会在这里实时出现。</div>
            </div>
          </Transition>
        </div>

        <div class="min-h-0 min-w-0">
          <Transition name="sub-stage-fade" mode="out-in">
            <SubtitleTaskStage
              v-if="ctx.activeStage === 'overview'"
              key="stage-overview"
              :ctx="ctx.taskOverviewCtx"
              mode="overview"
              immersive
            />
            <SubtitleInspectorWorkbench
              v-else-if="ctx.activeStage === 'pairing'"
              key="stage-pairing"
              :ctx="ctx.workbenchCtx"
              stage-mode="pairing"
              :show-delete-precheck="false"
              immersive
            />
            <SubtitleInspectorWorkbench
              v-else
              key="stage-tree"
              :ctx="ctx.workbenchCtx"
              stage-mode="tree"
              immersive
            />
          </Transition>
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
import { FolderTree, Link2, ListChecks, ListTodo, PanelLeftClose, PanelLeftOpen, Search } from 'lucide-vue-next'

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
  if (leftRailCollapsed.value && isRightCollapsed.value) return 'grid-cols-[64px_minmax(0,1fr)_72px]'
  if (leftRailCollapsed.value) return 'grid-cols-[64px_minmax(0,2.82fr)_minmax(284px,0.82fr)]'
  if (isRightCollapsed.value) return 'grid-cols-[minmax(236px,0.74fr)_minmax(0,2.82fr)_72px]'
  return 'grid-cols-[minmax(236px,0.74fr)_minmax(0,2.34fr)_minmax(284px,0.82fr)]'
})
</script>

<style scoped>
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
</style>
