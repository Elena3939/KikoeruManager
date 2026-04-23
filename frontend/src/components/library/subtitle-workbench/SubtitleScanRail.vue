<template>
  <div :class="embedded ? 'grid min-w-0 gap-3' : 'grid min-w-0 gap-3 rounded-[20px] border border-slate-100 bg-white p-4 shadow-[0_4px_16px_rgba(15,23,42,0.04)]'">
    <template v-if="!embedded">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="grid gap-1">
          <div class="inline-flex items-center gap-2">
            <span class="text-[14px] font-semibold text-slate-900">扫描命中目录</span>
            <span class="inline-flex min-w-10 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
              {{ ctx.subtitleDialogSelection.length }}
            </span>
          </div>
          <span v-if="ctx.subtitleSelectionLoading && ctx.subtitleSelectionProgressText" class="text-[11px] leading-5 text-slate-500">
            {{ ctx.subtitleSelectionProgressText }}
          </span>
        </div>

        <div v-if="ctx.subtitleSelectionTotalPages > 1" class="flex items-center gap-2 text-[11px] text-slate-500">
          <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="ctx.subtitleSelectionPage <= 1" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage - 1)">上一页</button>
          <span>{{ ctx.subtitleSelectionPage }} / {{ ctx.subtitleSelectionTotalPages }}</span>
          <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="ctx.subtitleSelectionPage >= ctx.subtitleSelectionTotalPages" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage + 1)">下一页</button>
        </div>
      </div>
    </template>

    <div class="grid gap-3">
      <div v-if="ctx.subtitleScanSessionSummary.length" class="flex flex-wrap gap-2">
        <span v-for="item in ctx.subtitleScanSessionSummary" :key="item.key" class="scan-rail-chip">
          {{ item.label }} {{ item.value }}
        </span>
      </div>

      <div v-if="ctx.subtitleSelectionLoading && !ctx.subtitleDialogSelection.length" class="inline-flex min-h-14 items-center gap-2.5">
        <AppLoadingAnimation variant="inline" :size="36" />
        <span class="text-[12px] text-slate-500">{{ ctx.subtitleSelectionProgressText || '正在扫描目录…' }}</span>
      </div>

      <AppEmptyState v-else-if="!ctx.subtitleDialogSelection.length" description="没有识别到 RJ 文件夹" size="sm" />

      <template v-else>
        <section class="grid gap-3">
          <div class="flex flex-wrap items-center justify-between gap-2.5">
            <div class="flex flex-wrap items-center gap-2">
              <div class="text-[13px] font-semibold text-slate-900">可执行与已入任务</div>
              <span class="inline-flex min-w-10 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
                {{ ctx.subtitleExecutableSelectionItems.length }}
              </span>
              <button type="button" class="scan-rail-toggle" @click="ctx.setSubtitleExecutableCollapsed(!ctx.subtitleExecutableCollapsed)">
                <span>{{ ctx.subtitleExecutableCollapsed ? '展开' : '收起' }}</span>
                <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleExecutableCollapsed }" />
              </button>
            </div>

            <div class="flex flex-wrap items-center justify-end gap-2">
              <div v-if="ctx.subtitleSelectionFilterOptions.length" class="grid grid-cols-2 gap-1.5 max-[1280px]:grid-cols-1">
                <button
                  v-for="item in ctx.subtitleSelectionFilterOptions"
                  :key="item.key"
                  type="button"
                  class="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-[8px] border border-slate-200 bg-white px-3 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
                  :class="{ active: ctx.subtitleSelectionFilter === item.key }"
                  @click="ctx.setSubtitleSelectionFilter(item.key)"
                >
                  {{ item.label }} {{ item.value }}
                </button>
              </div>
            </div>
          </div>

          <AppEmptyState v-if="!ctx.subtitleExecutableCollapsed && !ctx.subtitleExecutableDisplayItems.length" description="当前没有可执行或已入任务的 RJ 目录" size="sm" />

          <transition-group v-else-if="!ctx.subtitleExecutableCollapsed" name="subtitle-card-fade" tag="div" class="grid gap-2.5">
            <button
              v-for="item in ctx.pagedSubtitleSelectionItems"
              :key="ctx.buildSubtitleSelectionKey(item)"
              type="button"
              class="scan-rail-card group relative w-full overflow-hidden rounded-[16px] border px-3 py-2.5 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01]"
              :class="ctx.isSubtitleSelectionActive(item)
                ? 'border-slate-900 bg-white shadow-[0_6px_20px_rgba(15,23,42,0.1)] ring-1 ring-slate-900/15'
                : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 hover:shadow-[0_4px_12px_rgba(15,23,42,0.06)]'"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="absolute inset-y-3 left-0 w-[3px] rounded-r-full bg-transparent transition-all duration-300 group-hover:bg-slate-300" :class="{ '!bg-slate-900': ctx.isSubtitleSelectionActive(item) }"></div>

              <div class="ml-1.5 grid gap-1.5">
                <div class="line-clamp-2 text-[12px] font-semibold leading-[1.3] tracking-[-0.01em] text-slate-900">
                  {{ getDisplayFolderName(item) }}
                </div>

                <div class="text-[10px] leading-4 text-slate-500">
                  <span v-if="ctx.getLibraryLabelById(item.library_id)">来源库：{{ ctx.getLibraryLabelById(item.library_id) }}</span>
                </div>

                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="inline-flex min-h-[22px] items-center gap-1 rounded-[8px] border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                    <ListTodo class="h-3 w-3 text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:rotate-[10deg] group-hover:scale-110" :stroke-width="2.2" />
                    <span>{{ ctx.getSubtitleSelectionQueueLabel(item) }}</span>
                  </span>
                  <span
                    v-for="chip in ctx.getSubtitleSelectionExistingChips(item)"
                    :key="`${ctx.buildSubtitleSelectionKey(item)}-${chip.key}`"
                    :class="getExistingChipClass(chip)"
                  >
                    <component
                      :is="getExistingChipIcon(chip)"
                      class="h-3 w-3 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:-rotate-[10deg] group-hover:scale-110"
                      :class="getExistingChipIconClass(chip)"
                      :stroke-width="2.2"
                    />
                    <span>{{ chip.label }}</span>
                  </span>
                </div>

                <div v-if="item.queue_message" class="text-[9.5px] leading-[1.35] text-slate-500">{{ item.queue_message }}</div>

                <div v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item) || ctx.canRetryCreateSubtitleTaskForSelection(item) || ctx.canForceCreateSubtitleTaskForSelection(item)" class="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <button
                    v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item)"
                    type="button"
                    class="group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:scale-[0.96]"
                    @click.stop="ctx.focusSubtitleSelectionItem(item)"
                  >
                    <Eye class="h-3.5 w-3.5 text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:scale-110 group-hover/btn:rotate-[8deg]" :stroke-width="2.2" />
                    <span>{{ item.queue_state === 'existing_task' ? '打开现有任务' : '检查字幕稿' }}</span>
                  </button>
                  <button
                    v-if="ctx.canRetryCreateSubtitleTaskForSelection(item)"
                    type="button"
                    class="group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    <RotateCcw class="h-3.5 w-3.5 text-amber-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:scale-110 group-hover/btn:-rotate-[10deg]" :stroke-width="2.2" />
                    <span>重试加入</span>
                  </button>
                  <button
                    v-if="ctx.canForceCreateSubtitleTaskForSelection(item)"
                    type="button"
                    class="group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    <Plus class="h-3.5 w-3.5 text-emerald-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:scale-110 group-hover/btn:rotate-[12deg]" :stroke-width="2.2" />
                    <span>创建一次任务</span>
                  </button>
                </div>
              </div>
            </button>
          </transition-group>

          <div v-if="ctx.subtitleSelectionTotalPages > 1 && !ctx.subtitleExecutableCollapsed" class="flex flex-wrap items-center justify-center gap-2 pt-0.5 text-[11px] text-slate-500">
            <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="ctx.subtitleSelectionPage <= 1" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage - 1)">上一页</button>
            <span class="inline-flex min-h-[26px] min-w-[52px] items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 font-medium text-slate-600">{{ ctx.subtitleSelectionPage }} / {{ ctx.subtitleSelectionTotalPages }}</span>
            <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="ctx.subtitleSelectionPage >= ctx.subtitleSelectionTotalPages" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage + 1)">下一页</button>
          </div>
        </section>

        <section v-if="ctx.subtitleSkippedSelectionItems.length" class="grid gap-3 border-t border-slate-100 pt-3">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="inline-flex items-center gap-2">
              <div class="text-[13px] font-semibold text-slate-900">被跳过</div>
              <span class="inline-flex min-w-10 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
                {{ ctx.filteredSubtitleSkippedSelectionItems.length }}
              </span>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <div v-if="ctx.subtitleSkippedSelectionFilterOptions.length" class="flex flex-wrap gap-1.5">
                <button
                  v-for="item in ctx.subtitleSkippedSelectionFilterOptions"
                  :key="item.key"
                  type="button"
                  class="scan-rail-filter-pill"
                  :class="{ active: ctx.isSubtitleSkippedSelectionFilterActive(item.key) }"
                  @click="ctx.toggleSubtitleSkippedSelectionFilter(item.key)"
                >
                  {{ item.label }} {{ item.value }}
                </button>
              </div>
              <button type="button" class="scan-rail-toggle" @click="ctx.setSubtitleSkippedCollapsed(!ctx.subtitleSkippedCollapsed)">
                <span>{{ ctx.subtitleSkippedCollapsed ? '展开' : '收起' }}</span>
                <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleSkippedCollapsed }" />
              </button>
            </div>
          </div>

          <transition-group v-if="!ctx.subtitleSkippedCollapsed" name="subtitle-card-fade" tag="div" class="grid gap-2.5">
            <button
              v-for="item in ctx.filteredSubtitleSkippedSelectionItems"
              :key="`${ctx.buildSubtitleSelectionKey(item)}-skipped`"
              type="button"
              class="scan-rail-card w-full rounded-[16px] border border-slate-100 bg-slate-50/60 px-4 py-3 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01] hover:border-slate-200 hover:bg-white hover:shadow-[0_4px_12px_rgba(15,23,42,0.06)]"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="grid gap-2">
                <div class="text-[13px] font-semibold leading-[1.4] text-slate-900">{{ getDisplayFolderName(item) }}</div>
                <div class="text-[10px] text-slate-500">
                  <span v-if="ctx.getLibraryLabelById(item.library_id)">来源库：{{ ctx.getLibraryLabelById(item.library_id) }}</span>
                </div>
                <div class="flex flex-wrap gap-2">
                  <span class="scan-rail-chip" :class="ctx.getSubtitleSelectionQueueClass(item)">{{ ctx.getSubtitleSelectionQueueLabel(item) }}</span>
                  <span
                    v-for="chip in ctx.getSubtitleSelectionExistingChips(item)"
                    :key="`${ctx.buildSubtitleSelectionKey(item)}-${chip.key}`"
                    class="scan-rail-chip"
                  >
                    {{ chip.label }}
                  </span>
                </div>
                <div v-if="item.queue_message" class="text-[10px] leading-[1.45] text-slate-500">{{ item.queue_message }}</div>
                <div class="flex flex-wrap items-center gap-2">
                  <button v-if="ctx.canInspectSubtitleSelectionFolder(item)" type="button" class="scan-rail-btn scan-rail-btn-primary" @click.stop="ctx.inspectSubtitleSelectionFolder(item)">检查字幕稿</button>
                  <button v-if="ctx.canForceCreateSubtitleTaskForSelection(item)" type="button" class="scan-rail-btn scan-rail-btn-success" :disabled="Boolean(ctx.subtitleForceQueueKey)" @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)">创建一次任务</button>
                </div>
              </div>
            </button>
          </transition-group>
        </section>
      </template>
    </div>

    <section v-if="ctx.subtitleScanTargetResults.length" class="grid gap-3 border-t border-slate-100 pt-3">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="inline-flex items-center gap-2">
          <div class="text-[13px] font-semibold text-slate-900">扫描目标</div>
          <span class="inline-flex min-w-10 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
            {{ ctx.subtitleScanTargetResults.length }}
          </span>
        </div>
        <button type="button" class="scan-rail-toggle" @click="ctx.setSubtitleScanTargetsCollapsed(!ctx.subtitleScanTargetsCollapsed)">
          <span>{{ ctx.subtitleScanTargetsCollapsed ? '展开' : '收起' }}</span>
          <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleScanTargetsCollapsed }" />
        </button>
      </div>

      <div class="flex flex-wrap gap-2">
        <span v-if="ctx.subtitleScanSummary.pending" class="scan-rail-chip">扫描中 {{ ctx.subtitleScanSummary.pending }}</span>
        <span class="scan-rail-chip">成功 {{ ctx.subtitleScanSummary.success }}</span>
        <span v-if="ctx.subtitleScanSummary.noAudio" class="scan-rail-chip">无音频 {{ ctx.subtitleScanSummary.noAudio }}</span>
        <span v-if="ctx.subtitleScanSummary.noMatch" class="scan-rail-chip">未识别 {{ ctx.subtitleScanSummary.noMatch }}</span>
        <span v-if="ctx.subtitleScanSummary.failed" class="scan-rail-chip">失败 {{ ctx.subtitleScanSummary.failed }}</span>
      </div>

      <transition-group v-if="!ctx.subtitleScanTargetsCollapsed" name="subtitle-card-fade" tag="div" class="grid gap-2.5">
        <div v-for="item in ctx.subtitleScanTargetResults" :key="ctx.buildSubtitleScanTargetResultKey(item)" class="grid gap-3 rounded-[14px] border border-slate-200 bg-white px-3 py-3 shadow-[0_2px_8px_rgba(15,23,42,0.04)] md:grid-cols-[minmax(0,1fr)_auto]">
          <div class="grid min-w-0 gap-1.5" :title="item.path">
            <span class="text-[13px] font-semibold leading-[1.4] text-slate-900">{{ item.name }}</span>
            <div class="grid gap-1 text-[10px] text-slate-500">
              <span v-if="ctx.getLibraryLabelById(item.library_id)">{{ ctx.getLibraryLabelById(item.library_id) }}</span>
              <span>{{ item.path }}</span>
            </div>
          </div>
          <div class="grid gap-1.5 md:justify-items-end">
            <span class="scan-rail-status-pill" :class="`status-${item.status}`">{{ ctx.getSubtitleScanResultLabel(item.status) }}</span>
            <span class="text-[11px] leading-5 text-slate-500">{{ item.message }}</span>
            <button v-if="ctx.canRetrySubtitleScanResult(item)" type="button" class="scan-rail-btn scan-rail-btn-primary" :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)" @click="ctx.rescanSubtitleSelectionTarget(item)">重新扫描此项</button>
          </div>
        </div>
      </transition-group>
    </section>

    <section v-if="ctx.subtitleSkippedScanResults.length" class="grid gap-3 border-t border-slate-100 pt-3">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="inline-flex items-center gap-2">
          <div class="text-[13px] font-semibold text-slate-900">跳过结果</div>
          <span class="inline-flex min-w-10 items-center justify-center rounded-[8px] border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-900">
            {{ ctx.filteredSubtitleSkippedScanResults.length }}
          </span>
        </div>

        <div v-if="ctx.subtitleSkippedScanFilterOptions.length" class="flex flex-wrap gap-1.5">
          <button
            v-for="item in ctx.subtitleSkippedScanFilterOptions"
            :key="item.key"
            type="button"
            class="scan-rail-filter-pill"
            :class="{ active: ctx.subtitleScanSkipFilter === item.key }"
            @click="ctx.setSubtitleScanSkipFilter(item.key)"
          >
            {{ item.label }} {{ item.value }}
          </button>
        </div>
      </div>

      <transition-group name="subtitle-card-fade" tag="div" class="grid gap-2.5">
        <div v-for="item in ctx.filteredSubtitleSkippedScanResults" :key="`${ctx.buildSubtitleScanTargetResultKey(item)}-skipped`" class="grid gap-3 rounded-[14px] border border-slate-100 bg-slate-50/60 px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <div class="grid min-w-0 gap-1.5">
            <span class="text-[13px] font-semibold leading-[1.4] text-slate-900">{{ item.name }}</span>
            <div class="grid gap-1 text-[10px] text-slate-500">
              <span v-if="ctx.getLibraryLabelById(item.library_id)">{{ ctx.getLibraryLabelById(item.library_id) }}</span>
              <span>{{ item.path }}</span>
            </div>
          </div>
          <div class="grid gap-1.5 md:justify-items-end">
            <span class="scan-rail-status-pill" :class="`status-${item.status}`">{{ ctx.getSubtitleScanResultLabel(item.status) }}</span>
            <span class="text-[11px] leading-5 text-slate-500">{{ item.message }}</span>
            <button v-if="ctx.canRetrySubtitleScanResult(item)" type="button" class="scan-rail-btn scan-rail-btn-primary" :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)" @click="ctx.rescanSubtitleSelectionTarget(item)">重新扫描此项</button>
          </div>
        </div>
      </transition-group>
    </section>
  </div>
</template>

<script setup>
import { ChevronDown, Eye, FolderSearch, FileAudio2, ListTodo, Plus, RotateCcw } from 'lucide-vue-next'
import AppLoadingAnimation from '../../common/AppLoadingAnimation.vue'
import AppEmptyState from '../../common/AppEmptyState.vue'

defineProps({
  ctx: {
    type: Object,
    required: true
  },
  embedded: {
    type: Boolean,
    default: false
  }
})

function getDisplayFolderName(item) {
  const folderName = String(item?.folder_name || '').trim()
  if (folderName && !/[\\/]/.test(folderName)) return folderName

  const folderPath = String(item?.folder_path || item?.path || '').trim().replace(/[\\/]+$/, '')
  if (!folderPath) return folderName || '-'

  const parts = folderPath.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || folderName || folderPath
}

function getExistingChipClass(chip) {
  return 'inline-flex min-h-[22px] items-center gap-1 rounded-[8px] border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-700'
}

function getExistingChipIcon(chip) {
  const label = String(chip?.label || '')
  if (label.includes('本地字幕')) return FileAudio2
  return FolderSearch
}

function getExistingChipIconClass(chip) {
  const label = String(chip?.label || '')
  if (label.includes('本地字幕')) return 'text-amber-600'
  if (label.includes('已入任务')) return 'text-sky-600'
  return 'text-slate-500'
}
</script>

<style scoped>
.scan-rail-chip,
.scan-rail-filter-pill,
.scan-rail-btn,
.scan-rail-toggle {
  font: inherit;
}

.scan-rail-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 4px 9px;
  border-radius: 8px;
  background: #ffffff;
  color: #0f172a;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: -0.005em;
  border: 1px solid #e2e8f0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-filter-pill,
.scan-rail-btn,
.scan-rail-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #0f172a;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-toggle {
  min-height: 26px;
  padding: 0 8px;
  border-color: #e2e8f0;
  background: #f8fafc;
  color: #475569;
}

.scan-rail-filter-pill:hover,
.scan-rail-btn:hover,
.scan-rail-toggle:hover {
  transform: translateY(-1px) scale(1.02);
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.scan-rail-chip:hover {
  border-color: #cbd5e1;
}

.scan-rail-filter-pill:active,
.scan-rail-btn:active,
.scan-rail-toggle:active,
.scan-rail-chip:active {
  transform: scale(0.96);
}

.scan-rail-filter-pill.active {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
}

.scan-rail-btn:disabled,
.scan-rail-filter-pill:disabled,
.scan-rail-toggle:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.scan-rail-btn-ghost {
  background: #f8fafc;
  color: #475569;
}

.scan-rail-btn-primary {
  color: #334155;
  border-color: #cbd5e1;
}

.scan-rail-btn-primary:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.scan-rail-btn-success {
  color: #334155;
  border-color: #cbd5e1;
}

.scan-rail-btn-success:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.scan-rail-btn-danger {
  color: #7f1d1d;
  border-color: #e5c9c9;
}

.scan-rail-btn-danger:hover {
  background: #faf4f4;
  border-color: #d6b0b0;
}

.scan-rail-meta-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #334155;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.01em;
}

.scan-rail-status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 3px 9px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 500;
  box-shadow: 0 0 0 1px transparent;
}

.scan-rail-status-pill.status-pending { background: #f5f5f7; box-shadow: 0 0 0 1px #e2e2e8; color: #70707a; }
.scan-rail-status-pill.status-success { background: #f0f5f1; box-shadow: 0 0 0 1px #b8d0c0; color: #1a6b3a; }
.scan-rail-status-pill.status-no_audio,
.scan-rail-status-pill.status-no_match { background: #f5f5f7; box-shadow: 0 0 0 1px #d8d8e0; color: #505058; }
.scan-rail-status-pill.status-failed { background: #f5f0f0; box-shadow: 0 0 0 1px #d8c0c0; color: #8a2020; }

.subtitle-card-fade-enter-active,
.subtitle-card-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.subtitle-card-fade-enter-from,
.subtitle-card-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

.scan-rail-card {
  cursor: pointer;
}
</style>
