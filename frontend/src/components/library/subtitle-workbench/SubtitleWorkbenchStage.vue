<template>
  <section class="subtitle-workbench-stage-shell">
    <div class="subtitle-workbench-main-grid">
      <aside class="subtitle-workbench-rail">
        <div class="subtitle-rail-tabs">
          <button
            v-for="item in ctx.railModes"
            :key="item.key"
            type="button"
            class="subtitle-rail-tab"
            :class="{ active: ctx.railMode === item.key }"
            @click="ctx.setRailMode(item.key)"
          >
            <component :is="getRailTabIcon(item.key)" :size="13" :stroke-width="2.2" />
            <span>{{ item.label }}</span>
          </button>
        </div>

        <div class="subtitle-rail-body">
          <SubtitleScanRail v-if="ctx.railMode === 'scan'" :ctx="ctx.scanCtx" embedded />
          <SubtitleTaskNavigator v-else :ctx="ctx.taskNavigatorCtx" />
        </div>
      </aside>

      <div class="subtitle-stage-column">
        <div class="subtitle-stage-tabs">
          <button
            v-for="item in ctx.stageTabs"
            :key="item.key"
            type="button"
            class="subtitle-stage-tab"
            :class="{ active: ctx.activeStage === item.key }"
            @click="ctx.setActiveStage(item.key)"
          >
            <component :is="getStageTabIcon(item.key)" :size="14" :stroke-width="2.2" />
            <span class="subtitle-stage-tab-label">{{ item.label }}</span>
          </button>
        </div>

        <div class="subtitle-stage-queue-strip">
          <SubtitleTaskStage
            v-if="ctx.taskOverviewCtx?.subtitleQueueTasks?.length"
            :ctx="ctx.taskOverviewCtx"
            mode="queue"
            immersive
          />
          <div v-else class="subtitle-stage-queue-empty">
            <div class="subtitle-stage-queue-empty-title">当前没有可展示任务</div>
            <div class="subtitle-stage-queue-empty-tip">先在左侧“扫描命中”里选目录入队，任务卡会在这里实时出现。</div>
          </div>
        </div>

        <div class="subtitle-stage-panel">
          <SubtitleTaskStage v-if="ctx.activeStage === 'overview'" :ctx="ctx.taskOverviewCtx" mode="overview" immersive />
          <SubtitleInspectorWorkbench
            v-else-if="ctx.activeStage === 'pairing'"
            :ctx="ctx.workbenchCtx"
            stage-mode="pairing"
            :show-delete-precheck="false"
            immersive
          />
          <SubtitleInspectorWorkbench
            v-else
            :ctx="ctx.workbenchCtx"
            stage-mode="tree"
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
import SubtitleInspectorWorkbench from '../SubtitleInspectorWorkbench.vue'
import SubtitleConfigRail from './SubtitleConfigRail.vue'
import SubtitleScanRail from './SubtitleScanRail.vue'
import SubtitleTaskNavigator from './SubtitleTaskNavigator.vue'
import SubtitleTaskStage from './SubtitleTaskStage.vue'
import SubtitleContextDrawer from './SubtitleContextDrawer.vue'
import { ListChecks, Link2, FolderTree, Search, ListTodo } from 'lucide-vue-next'

function getRailTabIcon(key) {
  return { scan: Search, tasks: ListTodo }[key] || Search
}

function getStageTabIcon(key) {
  return { overview: ListChecks, pairing: Link2, tree: FolderTree }[key] || ListChecks
}

defineProps({
  ctx: {
    type: Object,
    required: true
  }
})
</script>

<style scoped>
.subtitle-workbench-stage-shell {
  min-height: 0;
}

.subtitle-workbench-main-grid {
  display: grid;
  grid-template-columns: minmax(236px, 0.74fr) minmax(0, 2.34fr) minmax(284px, 0.82fr);
  gap: 16px;
  align-items: start;
}

.subtitle-workbench-rail,
.subtitle-stage-column {
  min-width: 0;
}

.subtitle-workbench-rail {
  display: grid;
  gap: 14px;
  align-content: start;
  align-self: start;
  min-height: 0;
  padding: 16px;
  border: 1px solid rgba(220, 229, 238, 0.98);
  border-radius: 24px;
  background:
    radial-gradient(circle at top left, rgba(186, 208, 236, 0.2), transparent 38%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(245, 247, 250, 0.96));
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.05);
}

.subtitle-rail-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: rgba(226, 232, 240, 0.55);
  border-radius: 12px;
}

.subtitle-rail-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 10px;
  border-radius: 9px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.subtitle-rail-tab:hover {
  color: #0f172a;
  background: rgba(255, 255, 255, 0.72);
}

.subtitle-rail-tab:active {
  transform: scale(0.97);
}

.subtitle-rail-tab.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.1), 0 0 0 1px rgba(226, 232, 240, 0.5);
}

.subtitle-stage-tabs {
  display: flex;
  gap: 6px;
  padding: 5px;
  background: rgba(226, 232, 240, 0.62);
  border-radius: 16px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
}

.subtitle-stage-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 10px 18px;
  border-radius: 12px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  white-space: nowrap;
}

.subtitle-stage-tab:hover {
  color: #0f172a;
  background: rgba(255, 255, 255, 0.78);
  transform: translateY(-2px) scale(1.02);
}

.subtitle-stage-tab:active {
  transform: scale(0.96);
}

.subtitle-stage-tab.active {
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  color: #10233d;
  box-shadow: 0 10px 24px rgba(61, 92, 138, 0.12), 0 0 0 1px rgba(214, 225, 238, 0.85);
}

.subtitle-stage-tab-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.subtitle-rail-body,
.subtitle-stage-panel {
  min-height: 0;
}

.subtitle-stage-column {
  display: grid;
  gap: 16px;
}

.subtitle-stage-queue-strip,
.subtitle-stage-panel {
  padding: 14px;
  border: 1px solid rgba(220, 229, 238, 0.98);
  border-radius: 24px;
  background:
    radial-gradient(circle at top right, rgba(219, 232, 248, 0.18), transparent 42%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(245, 247, 250, 0.96));
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.05);
}

.subtitle-stage-queue-empty {
  min-height: 84px;
  display: grid;
  gap: 6px;
  align-content: center;
  padding: 10px 12px;
  border: 1px dashed #cfd8e3;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f8fc 100%);
}

.subtitle-stage-queue-empty-title {
  font-size: 13px;
  font-weight: 800;
  color: #1f2d3d;
}

.subtitle-stage-queue-empty-tip {
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

@media (max-width: 1360px) {
  .subtitle-workbench-main-grid {
    grid-template-columns: minmax(224px, 0.72fr) minmax(0, 2.08fr) minmax(264px, 0.76fr);
  }
}

@media (max-width: 1180px) {
  .subtitle-workbench-main-grid {
    grid-template-columns: 1fr;
  }
}
</style>
