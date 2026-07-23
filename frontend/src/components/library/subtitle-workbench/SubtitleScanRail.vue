<template>
  <div :class="embedded ? 'subtitle-scan-rail-root grid min-w-0 content-start gap-3' : 'subtitle-scan-rail-root grid min-w-0 content-start gap-3 rounded-[20px] border border-slate-100 bg-white p-4 shadow-[0_4px_16px_rgba(15,23,42,0.04)]'">
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

    <div class="scan-rail-primary-stack grid content-start gap-3">
      <div v-if="ctx.subtitleScanSessionSummary.length" class="scan-session-summary">
        <div
          v-for="(item, idx) in ctx.subtitleScanSessionSummary"
          :key="item.key"
          class="scan-session-summary-row"
          :class="{ 'border-t border-slate-100': idx > 0 }"
        >
          <span class="scan-session-summary-dot" :class="getSessionSummaryDotClass(item.key)"></span>
          <span class="scan-session-summary-label">{{ item.label }}</span>
          <span class="scan-session-summary-value" :class="{ empty: !item.value }">{{ item.value }}</span>
        </div>
      </div>

      <div v-if="ctx.subtitleSelectionLoading && !ctx.subtitleDialogSelection.length" class="inline-flex min-h-14 items-center gap-2.5">
        <AppLoadingAnimation variant="inline" :size="36" />
        <span class="text-[12px] text-slate-500">{{ ctx.subtitleSelectionProgressText || '正在扫描目录…' }}</span>
      </div>

      <AppEmptyState v-else-if="!ctx.subtitleDialogSelection.length" description="没有识别到 RJ 文件夹" size="sm" />

      <template v-else>
        <section class="scan-rail-section scan-rail-executable-section grid content-start gap-3">
          <div class="scan-rail-section-head">
            <div class="scan-rail-section-title">
              <div class="scan-rail-section-label text-[13px] font-semibold text-slate-900">可执行 / 已入队</div>
              <span class="scan-rail-count-badge scan-rail-count-badge-sky">
                <ListTodo class="h-3 w-3" :stroke-width="2.2" />
                {{ ctx.subtitleExecutableSelectionItems.length }}
              </span>
              <button type="button" class="scan-rail-toggle scan-rail-toggle-subtle" @click="ctx.setSubtitleExecutableCollapsed(!ctx.subtitleExecutableCollapsed)">
                <span class="scan-rail-toggle-text">{{ ctx.subtitleExecutableCollapsed ? '展开' : '收起' }}</span>
                <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleExecutableCollapsed }" />
              </button>
            </div>

            <div class="scan-rail-filter-wrap">
              <div v-if="ctx.subtitleSelectionFilterOptions.length" class="scan-rail-segment-grid">
                <button
                  v-for="item in ctx.subtitleSelectionFilterOptions"
                  :key="item.key"
                  type="button"
                  class="scan-rail-segment group"
                  :class="[`scan-rail-segment-${item.key}`, { active: ctx.subtitleSelectionFilter === item.key }]"
                  @click="ctx.setSubtitleSelectionFilter(item.key)"
                >
                  <component
                    :is="getSelectionFilterIcon(item.key)"
                    class="h-3.5 w-3.5 shrink-0 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
                    :class="getSelectionFilterIconClass(item.key, ctx.subtitleSelectionFilter === item.key)"
                    :stroke-width="2.2"
                  />
                  <span>{{ item.label }}</span>
                  <span class="scan-rail-segment-count">{{ item.value }}</span>
                </button>
              </div>
            </div>
          </div>

          <div v-if="!ctx.subtitleExecutableCollapsed && !ctx.subtitleExecutableDisplayItems.length" class="scan-rail-inline-empty">
            <span class="scan-rail-inline-empty-icon">
              <ListTodo class="h-4 w-4" :stroke-width="2.2" />
            </span>
            <div class="scan-rail-inline-empty-copy">
              <strong>暂无可执行项目</strong>
              <span>{{ ctx.subtitleSkippedSelectionItems.length ? '命中项已归入下方“被跳过”' : '当前没有待加入或已入任务的 RJ 目录' }}</span>
            </div>
          </div>

          <transition-group v-else-if="!ctx.subtitleExecutableCollapsed" name="subtitle-card-fade" tag="div" class="scan-rail-card-list">
            <button
              v-for="item in ctx.pagedSubtitleSelectionItems"
              :key="ctx.buildSubtitleSelectionKey(item)"
              type="button"
              class="scan-rail-card group relative w-full overflow-hidden rounded-[16px] border px-3 py-2.5 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.01]"
              :class="ctx.isSubtitleSelectionActive(item)
                ? 'border-slate-950 bg-white'
                : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-white'"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="scan-rail-card-content">
                <div class="scan-rail-card-title">
                  {{ getDisplayFolderName(item) }}
                </div>

                <div class="scan-rail-card-source">
                  <span v-if="ctx.getLibraryLabelById(item.library_id)">来源库：{{ ctx.getLibraryLabelById(item.library_id) }}</span>
                </div>

                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="scan-rail-tag" :class="getQueueChipClass(item)">
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

                <div v-if="item.queue_message" class="scan-rail-card-message">{{ item.queue_message }}</div>

                <div v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item) || ctx.canRetryCreateSubtitleTaskForSelection(item) || ctx.canForceCreateSubtitleTaskForSelection(item)" class="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <button
                    v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item)"
                    type="button"
                    class="scan-rail-card-action group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.02] hover:border-slate-300 hover:bg-white hover:text-slate-900 active:scale-[0.96]"
                    @click.stop="ctx.focusSubtitleSelectionItem(item)"
                  >
                    <Eye class="h-3.5 w-3.5 text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:scale-110 group-hover/btn:rotate-[8deg]" :stroke-width="2.2" />
                    <span>{{ item.queue_state === 'existing_task' ? '打开现有任务' : '检查字幕稿' }}</span>
                  </button>
                  <button
                    v-if="ctx.canRetryCreateSubtitleTaskForSelection(item)"
                    type="button"
                    class="scan-rail-card-action group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.02] hover:border-slate-300 hover:bg-white active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    <RotateCcw class="h-3.5 w-3.5 text-amber-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:scale-110 group-hover/btn:-rotate-[10deg]" :stroke-width="2.2" />
                    <span>重试加入</span>
                  </button>
                  <button
                    v-if="ctx.canForceCreateSubtitleTaskForSelection(item)"
                    type="button"
                    class="scan-rail-card-action group/btn inline-flex min-h-[30px] items-center gap-1 rounded-[9px] border border-slate-200 bg-white px-2.5 text-[10.5px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.02] hover:border-slate-300 hover:bg-white hover:text-slate-900 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
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

        <section v-if="ctx.subtitleSkippedSelectionItems.length" class="scan-rail-section scan-rail-skipped-section grid gap-3 border-t border-slate-100 pt-3">
          <div class="scan-rail-section-head">
            <div class="scan-rail-section-title">
              <div class="scan-rail-section-label text-[13px] font-semibold text-slate-900">被跳过</div>
              <span class="scan-rail-count-badge scan-rail-count-badge-amber">
                <Ban class="h-3 w-3" :stroke-width="2.2" />
                {{ ctx.filteredSubtitleSkippedSelectionItems.length }}
              </span>
              <button type="button" class="scan-rail-toggle scan-rail-section-collapse" @click="ctx.setSubtitleSkippedCollapsed(!ctx.subtitleSkippedCollapsed)">
                <span>{{ ctx.subtitleSkippedCollapsed ? '展开' : '收起' }}</span>
                <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleSkippedCollapsed }" />
              </button>
            </div>

            <div v-if="ctx.subtitleSkippedSelectionFilterOptions.length" class="scan-rail-skipped-filter-grid">
                <button
                  v-for="item in ctx.subtitleSkippedSelectionFilterOptions"
                  :key="item.key"
                  type="button"
                  class="scan-rail-filter-pill"
                  :class="[getSkippedFilterPillClass(item.key), { active: ctx.isSubtitleSkippedSelectionFilterActive(item.key) }]"
                  @click="ctx.toggleSubtitleSkippedSelectionFilter(item.key)"
                >
                  <component :is="getSkippedFilterIcon(item.key)" class="h-3 w-3" :stroke-width="2.2" />
                  <span>{{ item.label }}</span>
                  <span class="scan-rail-filter-count">{{ item.value }}</span>
                </button>
            </div>
          </div>

          <div v-if="!ctx.subtitleSkippedCollapsed" class="scan-rail-skipped-list grid gap-2">
            <button
              v-for="item in getPagedSkippedSelectionItems(ctx.filteredSubtitleSkippedSelectionItems, subtitleSkippedSelectionPage)"
              :key="`${ctx.buildSubtitleSelectionKey(item)}-skipped`"
              type="button"
              class="scan-rail-card group w-full rounded-[14px] border border-slate-200 bg-white px-3 py-2 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-[1.01] hover:border-slate-300 hover:bg-white active:scale-[0.98]"
              :class="ctx.isSubtitleSelectionActive(item) ? 'border-slate-950' : ''"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="scan-skipped-card-content">
                <div class="scan-skipped-card-head">
                  <span class="scan-skipped-card-icon">
                    <FolderOpen class="h-3 w-3" :stroke-width="2.2" />
                  </span>
                  <div class="scan-skipped-card-title-wrap">
                    <div class="scan-rail-card-title scan-skipped-card-title">{{ getDisplayFolderName(item) }}</div>
                    <div v-if="ctx.getLibraryLabelById(item.library_id)" class="scan-rail-card-source">
                      来源 · {{ ctx.getLibraryLabelById(item.library_id) }}
                    </div>
                  </div>
                </div>
                <div class="scan-skipped-card-meta">
                  <span class="scan-rail-tag scan-rail-tag-soft">
                    <component :is="getSkippedQueueIcon(item)" class="h-3 w-3" :class="getSkippedQueueIconClass(item)" :stroke-width="2.2" />
                    {{ ctx.getSubtitleSelectionQueueLabel(item) }}
                  </span>
                  <span
                    v-for="chip in ctx.getSubtitleSelectionExistingChips(item)"
                    :key="`${ctx.buildSubtitleSelectionKey(item)}-${chip.key}`"
                    :class="getExistingChipClass(chip)"
                  >
                    <component :is="getExistingChipIcon(chip)" class="h-3 w-3" :class="getExistingChipIconClass(chip)" :stroke-width="2.2" />
                    {{ chip.label }}
                  </span>
                </div>
                <div v-if="item.queue_message" class="scan-rail-card-message scan-skipped-card-message">{{ item.queue_message }}</div>
                <div class="scan-skipped-card-actions">
                  <button v-if="ctx.canInspectSubtitleSelectionFolder(item)" type="button" class="scan-rail-btn scan-rail-btn-primary" @click.stop="ctx.inspectSubtitleSelectionFolder(item)">检查字幕稿</button>
                  <button v-if="ctx.canForceCreateSubtitleTaskForSelection(item)" type="button" class="scan-rail-btn scan-rail-btn-success" :disabled="Boolean(ctx.subtitleForceQueueKey)" @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)">创建一次任务</button>
                </div>
              </div>
            </button>
          </div>

          <div v-if="!ctx.subtitleSkippedCollapsed && getSkippedSelectionPageCount(ctx.filteredSubtitleSkippedSelectionItems) > 1" class="scan-target-pager">
            <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="subtitleSkippedSelectionPage <= 1" @click="subtitleSkippedSelectionPage -= 1">上一页</button>
            <span class="scan-target-page-indicator">{{ subtitleSkippedSelectionPage }} / {{ getSkippedSelectionPageCount(ctx.filteredSubtitleSkippedSelectionItems) }}</span>
            <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="subtitleSkippedSelectionPage >= getSkippedSelectionPageCount(ctx.filteredSubtitleSkippedSelectionItems)" @click="subtitleSkippedSelectionPage += 1">下一页</button>
          </div>
        </section>
      </template>
    </div>

    <section v-if="ctx.subtitleScanTargetResults.length" class="grid gap-3 border-t border-slate-100 pt-3">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="inline-flex items-center gap-2">
          <div class="text-[13px] font-semibold text-slate-900">扫描目标</div>
          <span class="scan-rail-count-badge scan-rail-count-badge-violet">
            <FolderOpen class="h-3 w-3" :stroke-width="2.2" />
            {{ ctx.subtitleScanTargetResults.length }}
          </span>
        </div>
        <button type="button" class="scan-rail-toggle" @click="ctx.setSubtitleScanTargetsCollapsed(!ctx.subtitleScanTargetsCollapsed)">
          <span>{{ ctx.subtitleScanTargetsCollapsed ? '展开' : '收起' }}</span>
          <ChevronDown class="h-3.5 w-3.5 transition-transform duration-200" :class="{ '-rotate-90': ctx.subtitleScanTargetsCollapsed }" />
        </button>
      </div>

      <div class="flex flex-wrap gap-2">
        <span v-if="ctx.subtitleScanSummary.pending" class="scan-rail-chip scan-rail-chip-pending">
          <Clock3 class="h-3 w-3" :stroke-width="2.2" />
          扫描中 {{ ctx.subtitleScanSummary.pending }}
        </span>
        <span class="scan-rail-chip scan-rail-chip-success">
          <CheckCircle2 class="h-3 w-3" :stroke-width="2.2" />
          成功 {{ ctx.subtitleScanSummary.success }}
        </span>
        <span v-if="ctx.subtitleScanSummary.noAudio" class="scan-rail-chip scan-rail-chip-muted">
          <Ban class="h-3 w-3" :stroke-width="2.2" />
          无音频 {{ ctx.subtitleScanSummary.noAudio }}
        </span>
        <span v-if="ctx.subtitleScanSummary.noMatch" class="scan-rail-chip scan-rail-chip-muted">
          <Search class="h-3 w-3" :stroke-width="2.2" />
          未识别 {{ ctx.subtitleScanSummary.noMatch }}
        </span>
        <span v-if="ctx.subtitleScanSummary.failed" class="scan-rail-chip scan-rail-chip-failed">
          <AlertTriangle class="h-3 w-3" :stroke-width="2.2" />
          失败 {{ ctx.subtitleScanSummary.failed }}
        </span>
      </div>

      <transition-group v-if="!ctx.subtitleScanTargetsCollapsed" name="subtitle-card-fade" tag="div" class="scan-target-list">
        <div
          v-for="item in getPagedScanTargetResults(ctx.subtitleScanTargetResults, subtitleScanTargetPage)"
          :key="ctx.buildSubtitleScanTargetResultKey(item)"
          class="scan-target-card"
          :class="`scan-target-card-${getScanResultTone(item.status)}`"
          :title="item.path"
        >
          <div class="scan-target-head">
            <span class="scan-target-icon" :class="`scan-target-icon-${getScanResultTone(item.status)}`">
              <FolderOpen class="h-4 w-4" :stroke-width="2.2" />
            </span>
            <div class="scan-target-title-wrap">
              <span class="scan-target-title">{{ item.name }}</span>
            </div>
            <span class="scan-rail-status-pill" :class="`status-${item.status}`">
              <component :is="getScanResultIcon(item.status)" class="h-3 w-3" :stroke-width="2.2" />
              {{ ctx.getSubtitleScanResultLabel(item.status) }}
            </span>
          </div>

          <div class="scan-target-path">{{ getScanTargetParentPath(item) }}</div>

          <div v-if="item.message || ctx.canRetrySubtitleScanResult(item)" class="scan-target-foot">
            <span v-if="item.message" class="scan-target-message">{{ item.message }}</span>
            <button
              v-if="ctx.canRetrySubtitleScanResult(item)"
              type="button"
              class="scan-rail-btn scan-rail-btn-primary scan-target-retry"
              :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)"
              @click="ctx.rescanSubtitleSelectionTarget(item)"
            >
              <RotateCcw class="h-3.5 w-3.5" :stroke-width="2.2" />
              <span>重新扫描此项</span>
            </button>
          </div>
        </div>
      </transition-group>

      <div v-if="!ctx.subtitleScanTargetsCollapsed && getScanTargetPageCount(ctx.subtitleScanTargetResults) > 1" class="scan-target-pager">
        <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="subtitleScanTargetPage <= 1" @click="subtitleScanTargetPage -= 1">上一页</button>
        <span class="scan-target-page-indicator">{{ subtitleScanTargetPage }} / {{ getScanTargetPageCount(ctx.subtitleScanTargetResults) }}</span>
        <button type="button" class="scan-rail-btn scan-rail-btn-ghost" :disabled="subtitleScanTargetPage >= getScanTargetPageCount(ctx.subtitleScanTargetResults)" @click="subtitleScanTargetPage += 1">下一页</button>
      </div>
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
        <div
          v-for="item in ctx.filteredSubtitleSkippedScanResults"
          :key="`${ctx.buildSubtitleScanTargetResultKey(item)}-skipped`"
          class="scan-target-card scan-target-card-muted"
          :title="item.path"
        >
          <div class="scan-target-head">
            <span class="scan-target-icon scan-target-icon-muted">
              <Ban class="h-4 w-4" :stroke-width="2.2" />
            </span>
            <div class="scan-target-title-wrap">
              <span class="scan-target-title">{{ item.name }}</span>
            </div>
            <span class="scan-rail-status-pill" :class="`status-${item.status}`">
              <component :is="getScanResultIcon(item.status)" class="h-3 w-3" :stroke-width="2.2" />
              {{ ctx.getSubtitleScanResultLabel(item.status) }}
            </span>
          </div>

          <div class="scan-target-path">{{ item.path }}</div>

          <div v-if="item.message || ctx.canRetrySubtitleScanResult(item)" class="scan-target-foot">
            <span v-if="item.message" class="scan-target-message">{{ item.message }}</span>
            <button
              v-if="ctx.canRetrySubtitleScanResult(item)"
              type="button"
              class="scan-rail-btn scan-rail-btn-primary scan-target-retry"
              :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)"
              @click="ctx.rescanSubtitleSelectionTarget(item)"
            >
              <RotateCcw class="h-3.5 w-3.5" :stroke-width="2.2" />
              <span>重新扫描此项</span>
            </button>
          </div>
        </div>
      </transition-group>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { AlertTriangle, Ban, CheckCircle2, ChevronDown, Clock3, Eye, FolderOpen, FolderSearch, FileAudio2, ListTodo, Plus, RotateCcw, Search } from 'lucide-vue-next'
import AppLoadingAnimation from '../../common/AppLoadingAnimation.vue'
import AppEmptyState from '../../common/AppEmptyState.vue'

const SCAN_TARGET_PAGE_SIZE = 6
const SKIPPED_SELECTION_PAGE_SIZE = 5
const subtitleScanTargetPage = ref(1)
const subtitleSkippedSelectionPage = ref(1)

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

function normalizePage(page, total) {
  const totalPage = Math.max(1, Math.ceil((Array.isArray(total) ? total.length : 0) / SCAN_TARGET_PAGE_SIZE))
  return Math.min(Math.max(1, Number(page) || 1), totalPage)
}

function getScanTargetPageCount(items = []) {
  return Math.max(1, Math.ceil((Array.isArray(items) ? items.length : 0) / SCAN_TARGET_PAGE_SIZE))
}

function getPagedScanTargetResults(items = [], page = 1) {
  const source = Array.isArray(items) ? items : []
  const currentPage = normalizePage(page, source)
  const start = (currentPage - 1) * SCAN_TARGET_PAGE_SIZE
  return source.slice(start, start + SCAN_TARGET_PAGE_SIZE)
}

function normalizeSkippedPage(page, items = []) {
  const totalPage = Math.max(1, Math.ceil((Array.isArray(items) ? items.length : 0) / SKIPPED_SELECTION_PAGE_SIZE))
  return Math.min(Math.max(1, Number(page) || 1), totalPage)
}

function getSkippedSelectionPageCount(items = []) {
  return Math.max(1, Math.ceil((Array.isArray(items) ? items.length : 0) / SKIPPED_SELECTION_PAGE_SIZE))
}

function getPagedSkippedSelectionItems(items = [], page = 1) {
  const source = Array.isArray(items) ? items : []
  const currentPage = normalizeSkippedPage(page, source)
  const start = (currentPage - 1) * SKIPPED_SELECTION_PAGE_SIZE
  return source.slice(start, start + SKIPPED_SELECTION_PAGE_SIZE)
}

function getDisplayFolderName(item) {
  const folderName = String(item?.folder_name || '').trim()
  if (folderName && !/[\\/]/.test(folderName)) return folderName

  const folderPath = String(item?.folder_path || item?.path || '').trim().replace(/[\\/]+$/, '')
  if (!folderPath) return folderName || '-'

  const parts = folderPath.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || folderName || folderPath
}

function getScanTargetParentPath(item) {
  const path = String(item?.path || '').trim().replace(/[\\/]+$/, '')
  if (!path) return '-'

  const name = String(item?.name || '').trim()
  if (!name) return path

  const normalizedPath = path.replace(/\\/g, '/')
  const normalizedName = name.replace(/\\/g, '/')
  if (!normalizedPath.endsWith(`/${normalizedName}`)) return path

  return normalizedPath.slice(0, -(normalizedName.length + 1)) || '/'
}

function getExistingChipClass(chip) {
  const label = String(chip?.label || '')
  if (label.includes('已匹配完成')) {
    return 'scan-rail-tag scan-rail-tag-success'
  }
  if (label.includes('本地字幕')) {
    return 'scan-rail-tag scan-rail-tag-amber'
  }
  if (label.includes('已入任务') || label.includes('任务已存在')) {
    return 'scan-rail-tag scan-rail-tag-sky'
  }
  return 'scan-rail-tag scan-rail-tag-soft'
}

function getQueueChipClass(item) {
  const label = String(item?.queue_label || '').trim() || String(item?.queue_state || '').trim()
  if (label.includes('已匹配完成') || label.includes('manual_match_completed')) return 'scan-rail-tag-success'
  if (label.includes('已入任务') || label.includes('queued') || label.includes('existing_task')) return 'scan-rail-tag-sky'
  if (label.includes('加入失败') || label.includes('create_failed')) return 'scan-rail-tag-rose'
  return 'scan-rail-tag-soft'
}

function getExistingChipIcon(chip) {
  const label = String(chip?.label || '')
  if (label.includes('本地字幕')) return FileAudio2
  return FolderSearch
}

function getExistingChipIconClass(chip) {
  const label = String(chip?.label || '')
  if (label.includes('已匹配完成')) return 'text-emerald-600'
  if (label.includes('本地字幕')) return 'text-amber-600'
  if (label.includes('已入任务')) return 'text-sky-600'
  return 'text-slate-500'
}

function getSkippedQueueIcon(item) {
  const label = String(item?.queue_label || item?.queue_state || '')
  if (label.includes('远程无字幕') || label.includes('no_subtitle')) return Ban
  if (label.includes('已有字幕') || label.includes('existing')) return CheckCircle2
  return Search
}

function getSkippedQueueIconClass(item) {
  const label = String(item?.queue_label || item?.queue_state || '')
  if (label.includes('远程无字幕') || label.includes('no_subtitle')) return 'text-sky-600'
  if (label.includes('已有字幕') || label.includes('existing')) return 'text-emerald-600'
  return 'text-slate-500'
}

function getSelectionFilterIcon(key) {
  return key === 'queued' ? ListTodo : Search
}

function getSkippedFilterIcon(key) {
  if (key === 'skipped_existing') return CheckCircle2
  if (key === 'skipped_no_subtitle') return Ban
  return Search
}

function getSkippedFilterPillClass(key) {
  if (key === 'skipped_existing') return 'scan-rail-filter-pill-success'
  if (key === 'skipped_no_subtitle') return 'scan-rail-filter-pill-sky'
  return 'scan-rail-filter-pill-soft'
}

function getSelectionFilterIconClass(key, active) {
  if (key === 'queued') {
    return active
      ? 'text-sky-200 group-hover:text-white group-hover:-translate-y-0.5 group-hover:rotate-[10deg] group-hover:scale-110'
      : 'text-sky-600 group-hover:text-sky-700 group-hover:-translate-y-0.5 group-hover:rotate-[10deg] group-hover:scale-110'
  }
  return active
    ? 'text-slate-200 group-hover:text-white group-hover:-translate-y-0.5 group-hover:rotate-[-8deg] group-hover:scale-110'
    : 'text-slate-500 group-hover:text-slate-700 group-hover:-translate-y-0.5 group-hover:rotate-[-8deg] group-hover:scale-110'
}

function getSessionSummaryDotClass(key) {
  if (key === 'created') return 'bg-emerald-500'
  if (key === 'failed') return 'bg-rose-500'
  if (key === 'existing' || key === 'exists') return 'bg-amber-500'
  if (key === 'noSubtitle') return 'bg-slate-400'
  return 'bg-sky-500'
}

function getScanResultTone(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'failed'
  if (status === 'pending') return 'pending'
  return 'muted'
}

function getScanResultIcon(status) {
  if (status === 'success') return CheckCircle2
  if (status === 'failed') return AlertTriangle
  if (status === 'pending') return Clock3
  return Ban
}
</script>

<style scoped>
.subtitle-scan-rail-root {
  align-content: start;
  grid-auto-rows: max-content;
  gap: 10px;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 3px;
  scrollbar-color: rgba(148, 163, 184, 0.42) transparent;
  scrollbar-width: thin;
}

.subtitle-scan-rail-root > * {
  min-height: 0;
}

.subtitle-scan-rail-root::-webkit-scrollbar {
  width: 5px;
}

.subtitle-scan-rail-root::-webkit-scrollbar-track {
  background: transparent;
}

.subtitle-scan-rail-root::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.34);
}

.scan-rail-primary-stack {
  min-width: 0;
  gap: 10px;
}

.scan-rail-section {
  min-width: 0;
}

.scan-rail-section-head {
  display: grid;
  align-content: start;
  gap: 7px;
}

.scan-rail-section-title {
  display: flex;
  min-width: 0;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
}

.scan-rail-section-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-rail-section-collapse,
.scan-rail-toggle-subtle {
  margin-left: auto;
  flex: 0 0 auto;
}

.scan-rail-filter-wrap {
  min-width: 0;
}

.scan-rail-skipped-filter-grid {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
  gap: 6px;
}

.scan-rail-skipped-filter-grid .scan-rail-filter-pill {
  width: 100%;
  min-width: 0;
}

.scan-rail-skipped-filter-grid .scan-rail-filter-pill > span:not(.scan-rail-filter-count) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-rail-segment-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.scan-rail-card-list {
  display: grid;
  align-content: start;
  grid-auto-rows: max-content;
  gap: 10px;
  min-height: 0;
}

.scan-rail-card-content {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 7px;
}

.scan-rail-inline-empty {
  display: grid;
  min-width: 0;
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: center;
  gap: 9px;
  border: 1px dashed #dbe3ee;
  border-radius: 11px;
  background: #f8fafc;
  padding: 9px 10px;
}

.scan-rail-inline-empty-icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border: 1px solid #dbeafe;
  border-radius: 9px;
  background: #ffffff;
  color: #64748b;
}

.scan-rail-inline-empty-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.scan-rail-inline-empty-copy strong {
  overflow: hidden;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-rail-inline-empty-copy span {
  color: #64748b;
  font-size: 9.5px;
  font-weight: 500;
  line-height: 1.35;
}

.scan-rail-skipped-list {
  align-content: start;
  grid-auto-rows: max-content;
}

.scan-skipped-card-content {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.scan-skipped-card-head {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 8px;
}

.scan-skipped-card-title-wrap {
  display: grid;
  min-width: 0;
  flex: 1 1 auto;
  gap: 1px;
}

.scan-skipped-card-meta,
.scan-skipped-card-actions {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding-left: 26px;
}

.scan-skipped-card-meta .scan-rail-tag {
  min-height: 18px;
  gap: 3px;
  padding: 0 6px;
  font-size: 9px;
}

.scan-skipped-card-meta .scan-rail-tag svg {
  width: 11px;
  height: 11px;
}

.scan-skipped-card-message {
  padding-left: 26px;
  line-height: 1.35;
}

.scan-rail-card-title {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-rail-card-title.scan-skipped-card-title {
  display: -webkit-box;
  max-height: 2.76em;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.38;
  text-overflow: ellipsis;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.scan-rail-card-source {
  min-width: 0;
  color: #64748b;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.35;
}

.scan-rail-card-message {
  min-width: 0;
  color: #64748b;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.scan-rail-card,
.scan-rail-card:hover,
.scan-rail-card:focus,
.scan-rail-card:focus-visible,
.scan-rail-card:focus-within,
.scan-rail-btn,
.scan-rail-btn:hover,
.scan-rail-btn:focus,
.scan-rail-btn:focus-visible,
.scan-rail-toggle,
.scan-rail-toggle:hover,
.scan-rail-toggle:focus,
.scan-rail-toggle:focus-visible,
.scan-rail-segment,
.scan-rail-segment:hover,
.scan-rail-segment:focus,
.scan-rail-segment:focus-visible,
.scan-rail-filter-pill,
.scan-rail-filter-pill:hover,
.scan-rail-filter-pill:focus,
.scan-rail-filter-pill:focus-visible {
  outline: none !important;
  box-shadow: none !important;
}

.scan-rail-card :is(button, input, textarea):focus,
.scan-rail-card :is(button, input, textarea):focus-visible {
  outline: none !important;
  box-shadow: none !important;
}

.scan-rail-card,
.scan-rail-card:hover,
.scan-rail-toggle-subtle,
.scan-rail-toggle-subtle:hover,
.scan-session-summary,
.scan-session-summary-row,
.scan-target-card,
.scan-target-card:hover,
.scan-target-card:focus,
.scan-target-card:focus-visible {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

.scan-rail-chip,
.scan-rail-tag,
.scan-rail-filter-pill,
.scan-rail-btn,
.scan-rail-toggle,
.scan-rail-segment,
.scan-rail-segment-count {
  font: inherit;
}

.scan-rail-tag {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  gap: 4px;
  border-radius: 7px;
  border: 1px solid #dbe3ee;
  background: #ffffff;
  padding: 1px 7px;
  font-size: 9.5px;
  font-weight: 600;
  color: #334155;
  letter-spacing: -0.01em;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-skipped-card-icon {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1px solid #fde68a;
  background: #ffffff;
  color: #f59e0b;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-card:hover .scan-skipped-card-icon {
  transform: rotate(-6deg) scale(1.08);
}

.scan-rail-tag-success {
  border-color: #cfeedd;
  background: #ffffff;
  color: #3f7a5d;
  box-shadow: none;
}

.scan-rail-tag-sky {
  border-color: #e4effb;
  background: #ffffff;
  color: #4a6a88;
}

.scan-rail-tag-amber {
  border-color: #fdf5dc;
  background: #fffef9;
  color: #8f784b;
}

.scan-rail-tag-rose {
  border-color: #fde1e5;
  background: #fff9fa;
  color: #9b5f69;
}

.scan-rail-tag-soft {
  border-color: #dbe3ee;
  background: #fdfefe;
  color: #4b5b70;
}

.scan-rail-count-badge {
  display: inline-flex;
  min-width: 30px;
  min-height: 24px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border-radius: 9px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  padding: 0 9px;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #1e293b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-count-badge svg {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-count-badge:hover svg {
  transform: rotate(-8deg) scale(1.12);
}

.scan-rail-count-badge-sky {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-count-badge-sky svg {
  color: #7c3aed;
}

.scan-rail-count-badge-amber {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-count-badge-amber svg {
  color: #d97706;
}

.scan-rail-count-badge-violet {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-count-badge-violet svg {
  color: #f59e0b;
}

.scan-rail-toggle-subtle {
  min-height: 26px;
  border-color: #e2e8f0;
  background: #ffffff;
  color: #64748b;
  padding: 0 9px;
}

.scan-rail-toggle-subtle:hover {
  border-color: #d1dbe7;
  background: #ffffff;
  color: #334155;
}

.scan-rail-toggle-text {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.scan-session-summary {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
}

.scan-session-summary-row {
  position: relative;
  display: flex;
  min-height: 34px;
  align-items: center;
  gap: 9px;
  padding: 0 11px;
  transition: background-color 0.2s ease;
}

.scan-session-summary-row:hover {
  background: #ffffff;
}

.scan-session-summary-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 999px;
}

.scan-session-summary-label {
  min-width: 0;
  flex: 1;
  color: #0f172a;
  font-size: 11.5px;
  font-weight: 500;
}

.scan-session-summary-value {
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.scan-session-summary-value.empty {
  color: #cbd5e1;
  font-weight: 600;
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

.scan-rail-chip svg {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-chip:hover svg {
  transform: rotate(-8deg) scale(1.12);
}

.scan-rail-chip-success {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #15803d;
}

.scan-rail-chip-pending {
  border-color: #fde68a;
  background: #fffbeb;
  color: #b45309;
}

.scan-rail-chip-muted {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #475569;
}

.scan-rail-chip-failed {
  border-color: #fecdd3;
  background: #fff1f2;
  color: #be123c;
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

.scan-rail-filter-pill svg,
.scan-rail-toggle svg {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.3s ease;
}

.scan-rail-filter-pill:hover svg,
.scan-rail-toggle:hover svg {
  transform: rotate(-8deg) scale(1.1);
}

.scan-rail-filter-pill {
  position: relative;
  background: #ffffff;
  overflow: hidden;
}

.scan-rail-filter-pill::before {
  display: none;
  content: none;
}

.scan-rail-filter-pill-success {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-filter-pill-success svg {
  color: #15803d;
}

.scan-rail-filter-pill-sky {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-filter-pill-sky svg {
  color: #7c3aed;
}

.scan-rail-filter-pill-soft {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #475569;
}

.scan-rail-filter-pill-soft svg {
  color: #64748b;
}

.scan-rail-filter-count {
  display: inline-flex;
  min-width: 22px;
  min-height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.82);
  padding: 0 6px;
  font-size: 10px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.scan-rail-toggle {
  min-height: 26px;
  padding: 0 8px;
  border-color: #e2e8f0;
  background: #ffffff;
  color: #334155;
}

.scan-rail-segment {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 30px;
  padding: 0 9px 0 10px;
  border-radius: 10px;
  border: 1px solid #dbe3ee;
  background: #ffffff;
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: -0.01em;
  cursor: pointer;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-segment > span:not(.scan-rail-segment-count) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-rail-segment:hover {
  transform: scale(1.02);
  border-color: #cbd5e1;
  color: #0f172a;
  box-shadow: none;
}

.scan-rail-segment:active {
  transform: scale(0.96);
}

.scan-rail-segment.active {
  border-color: #0f172a;
  background: #0f172a;
  color: #f8fafc;
  box-shadow: none;
}

.scan-rail-segment-queued {
  border-color: #bbf7d0;
  background: #ffffff;
}

.scan-rail-segment-queued .scan-rail-segment-count {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #15803d;
}

.scan-rail-segment-queued:hover {
  border-color: #86efac;
  box-shadow: none;
}

.scan-rail-segment-queued.active {
  border-color: #15803d;
  background: #15803d;
  color: #ffffff;
  box-shadow: none;
}

.scan-rail-segment-queued.active .scan-rail-segment-count {
  border-color: rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.scan-rail-segment-count {
  display: inline-flex;
  min-width: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(241, 245, 249, 0.9);
  padding: 0 6px;
  min-height: 18px;
  font-size: 10px;
  font-weight: 700;
  color: #475569;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-rail-segment:hover .scan-rail-segment-count {
  border-color: rgba(148, 163, 184, 0.34);
  background: rgba(255, 255, 255, 0.96);
}

.scan-rail-segment.active .scan-rail-segment-count {
  border-color: rgba(226, 232, 240, 0.18);
  background: rgba(255, 255, 255, 0.12);
  color: #f8fafc;
}

.scan-rail-filter-pill:hover,
.scan-rail-btn:hover,
.scan-rail-toggle:hover {
  transform: scale(1.02);
  border-color: #cbd5e1;
  box-shadow: none;
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
  background: #ffffff;
  border-color: #cbd5e1;
  color: #0f172a;
  box-shadow: none;
}

.scan-rail-filter-pill-success.active {
  background: #ffffff;
  border-color: #bbf7d0;
  color: #0f172a;
  box-shadow: none;
}

.scan-rail-filter-pill-sky.active {
  background: #ffffff;
  border-color: #ddd6fe;
  color: #0f172a;
  box-shadow: none;
}

.scan-rail-filter-pill.active::before {
  display: none;
}

.scan-rail-filter-pill-success.active::before {
  background: #22c55e;
}

.scan-rail-filter-pill-sky.active::before {
  background: #7c3aed;
}

.scan-rail-filter-pill.active svg {
  transform: scale(1.12);
}

.scan-rail-filter-pill.active .scan-rail-filter-count {
  border-color: #cbd5e1;
  background: #ffffff;
  color: #0f172a;
}

/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.scan-rail-btn:disabled,
.scan-rail-filter-pill:disabled,
.scan-rail-toggle:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.scan-rail-btn-ghost {
  background: #ffffff;
  color: #475569;
}

.scan-rail-btn-primary {
  color: #334155;
  border-color: #cbd5e1;
}

.scan-rail-btn-primary:hover {
  background: #ffffff;
  border-color: #94a3b8;
}

.scan-rail-btn-success {
  color: #334155;
  border-color: #cbd5e1;
}

.scan-rail-btn-success:hover {
  background: #ffffff;
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
  background: #ffffff;
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
  gap: 5px;
  min-height: 24px;
  padding: 3px 9px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 10px;
  font-weight: 500;
}

.scan-rail-status-pill.status-pending { background: #fffbeb; border-color: #fde68a; color: #b45309; }
.scan-rail-status-pill.status-success { background: #f0fdf4; border-color: #bbf7d0; color: #15803d; }
.scan-rail-status-pill.status-no_audio,
.scan-rail-status-pill.status-no_match { background: #ffffff; border-color: #e2e8f0; color: #475569; }
.scan-rail-status-pill.status-failed { background: #fff1f2; border-color: #fecdd3; color: #be123c; }

.scan-target-card {
  display: grid;
  gap: 10px;
  width: 100%;
  min-width: 0;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.3s ease;
}

.scan-target-list {
  display: grid;
  gap: 10px;
}

.scan-target-pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-top: 2px;
}

.scan-target-page-indicator {
  display: inline-flex;
  min-height: 28px;
  min-width: 58px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
}

.scan-target-card:hover {
  transform: scale(1.01);
  border-color: #bfdbfe;
  background: #ffffff;
}

.scan-target-card-success { border-color: #bbf7d0; }
.scan-target-card-pending { border-color: #bfdbfe; }
.scan-target-card-failed { border-color: #fecdd3; }
.scan-target-card-muted { border-color: #e2e8f0; }

.scan-target-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 8px 10px;
  min-width: 0;
}

.scan-target-head .scan-rail-status-pill {
  grid-column: 2;
  grid-row: 1;
  justify-self: end;
}

.scan-target-icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid #fde68a;
  background: #ffffff;
  color: #f59e0b;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-target-card:hover .scan-target-icon {
  transform: rotate(-6deg) scale(1.08);
}

.scan-target-icon-success {
  border-color: #fde68a;
  background: #ffffff;
  color: #f59e0b;
}

.scan-target-icon-pending {
  border-color: #fde68a;
  background: #ffffff;
  color: #f59e0b;
}

.scan-target-icon-failed {
  border-color: #fde68a;
  background: #ffffff;
  color: #f59e0b;
}

.scan-target-icon-muted {
  border-color: #fde68a;
  background: #ffffff;
  color: #f59e0b;
}

.scan-target-title-wrap {
  display: grid;
  grid-column: 1 / -1;
  grid-row: 2;
  gap: 3px;
  min-width: 0;
}

.scan-target-title {
  display: -webkit-box;
  min-width: 0;
  max-height: 2.76em;
  overflow: hidden;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.38;
  letter-spacing: 0;
  overflow-wrap: break-word;
  text-overflow: ellipsis;
  word-break: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.scan-target-path {
  display: -webkit-box;
  min-width: 0;
  max-height: 2.8em;
  overflow: hidden;
  padding-left: 0;
  color: #52657d;
  font-size: 11px;
  line-height: 1.4;
  overflow-wrap: anywhere;
  text-overflow: ellipsis;
  word-break: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.scan-target-foot {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-left: 40px;
}

.scan-target-message {
  min-width: 0;
  flex: 1 1 150px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.scan-target-retry svg {
  color: #0078d4;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.scan-target-retry:hover svg {
  transform: rotate(-12deg) scale(1.1);
}

@media (max-width: 640px) {
  .scan-target-path,
  .scan-target-foot {
    padding-left: 0;
  }
}

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
  align-self: start;
  height: auto;
  min-height: 0;
  max-height: none;
}

.subtitle-scan-rail-root :deep(.app-empty-state) {
  min-height: 96px;
}

.scan-rail-card .grid {
  align-content: start;
}

.scan-rail-card .flex {
  min-height: 0;
}

.scan-rail-card > div {
  min-height: 0;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root,
:global(html.dark) .subtitle-scan-rail-root {
  color: rgba(245, 245, 247, 0.9);
  scrollbar-color: rgba(255, 255, 255, 0.24) transparent;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-inline-empty),
:global(html.dark .subtitle-scan-rail-root .scan-rail-inline-empty) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #1b1c20 !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-inline-empty-icon),
:global(html.dark .subtitle-scan-rail-root .scan-rail-inline-empty-icon) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #2b2c30 !important;
  color: rgba(203, 213, 225, 0.74) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-inline-empty-copy strong),
:global(html.dark .subtitle-scan-rail-root .scan-rail-inline-empty-copy strong) {
  color: rgba(248, 250, 252, 0.9) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-inline-empty-copy span),
:global(html.dark .subtitle-scan-rail-root .scan-rail-inline-empty-copy span) {
  color: rgba(203, 213, 225, 0.62) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-session-summary),
:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-session-summary-row),
:global(html.dark .subtitle-scan-rail-root .scan-session-summary),
:global(html.dark .subtitle-scan-rail-root .scan-session-summary-row) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #242529 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-session-summary-row:hover),
:global(html.dark .subtitle-scan-rail-root .scan-session-summary-row:hover) {
  background: #2b2c30 !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-session-summary-label, .scan-session-summary-value)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-session-summary-label, .scan-session-summary-value)) {
  color: rgba(248, 250, 252, 0.94) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-session-summary-value.empty),
:global(html.dark .subtitle-scan-rail-root .scan-session-summary-value.empty) {
  color: rgba(203, 213, 225, 0.48) !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card,
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card:hover,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card:hover {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #333438 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card:hover,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card:hover {
  border-color: rgba(255, 255, 255, 0.24) !important;
  background: #3a3b40 !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card-title,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card-title {
  color: rgba(248, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card-source,
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root .scan-rail-card-message,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card-source,
:global(html.dark) .subtitle-scan-rail-root .scan-rail-card-message {
  color: rgba(203, 213, 225, 0.68) !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-chip),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-count-badge),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment-count),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-pill),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-count),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-toggle),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-btn),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-chip),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-count-badge),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment-count),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-pill),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-count),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-toggle),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-btn),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: rgba(255, 255, 255, 0.06) !important;
  background-image: none !important;
  color: rgba(245, 245, 247, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-success),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-success),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-success),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-success) {
  border-color: rgba(74, 222, 128, 0.22) !important;
  background: rgba(34, 197, 94, 0.13) !important;
  color: #bbf7d0 !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-sky),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-pill-sky),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-sky),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-filter-pill-sky) {
  border-color: rgba(56, 189, 248, 0.22) !important;
  background: rgba(14, 165, 233, 0.12) !important;
  color: #bae6fd !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-amber),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-pending),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-amber),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-pending) {
  border-color: rgba(251, 191, 36, 0.22) !important;
  background: rgba(245, 158, 11, 0.13) !important;
  color: #fde68a !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-rose),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-failed),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag-rose),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-chip-failed) {
  border-color: rgba(251, 113, 133, 0.24) !important;
  background: rgba(244, 63, 94, 0.13) !important;
  color: #fecdd3 !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment:hover),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-toggle:hover),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-btn:hover),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action:hover),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment:hover),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-toggle:hover),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-btn:hover),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action:hover) {
  border-color: rgba(255, 255, 255, 0.24) !important;
  background: rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment.active),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment.active) {
  border-color: rgba(255, 255, 255, 0.26) !important;
  background: #3f4046 !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment.active .scan-rail-segment-count),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment.active .scan-rail-segment-count) {
  border-color: rgba(255, 255, 255, 0.18) !important;
  background: rgba(255, 255, 255, 0.08) !important;
  color: rgba(245, 245, 247, 0.92) !important;
}

:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-tag svg),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-chip svg),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-count-badge svg),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-segment svg),
:global(html.kikoerumanager-dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action svg),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-tag svg),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-chip svg),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-count-badge svg),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-segment svg),
:global(html.dark) .subtitle-scan-rail-root :deep(.scan-rail-card-action svg) {
  color: currentColor !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root),
:global(html.dark .subtitle-scan-rail-root) {
  color: rgba(245, 245, 247, 0.9) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-card),
:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-card:hover),
:global(html.dark .subtitle-scan-rail-root .scan-rail-card),
:global(html.dark .subtitle-scan-rail-root .scan-rail-card:hover) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #333438 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-card-title),
:global(html.dark .subtitle-scan-rail-root .scan-rail-card-title) {
  color: rgba(248, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-card-source),
:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-card-message),
:global(html.dark .subtitle-scan-rail-root .scan-rail-card-source),
:global(html.dark .subtitle-scan-rail-root .scan-rail-card-message) {
  color: rgba(203, 213, 225, 0.68) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-card),
:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-card:hover),
:global(html.dark .subtitle-scan-rail-root .scan-target-card),
:global(html.dark .subtitle-scan-rail-root .scan-target-card:hover) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #242529 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-card-success),
:global(html.dark .subtitle-scan-rail-root .scan-target-card-success) {
  border-color: rgba(74, 222, 128, 0.3) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-title),
:global(html.dark .subtitle-scan-rail-root .scan-target-title) {
  color: rgba(248, 250, 252, 0.94) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-path),
:global(html.dark .subtitle-scan-rail-root .scan-target-path) {
  color: rgba(203, 213, 225, 0.68) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-target-icon),
:global(html.dark .subtitle-scan-rail-root .scan-target-icon) {
  border-color: rgba(251, 191, 36, 0.28) !important;
  background: rgba(245, 158, 11, 0.1) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-status-pill.status-success),
:global(html.dark .subtitle-scan-rail-root .scan-rail-status-pill.status-success) {
  border-color: rgba(74, 222, 128, 0.3) !important;
  background: rgba(34, 197, 94, 0.14) !important;
  color: #86efac !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag, .scan-rail-tag-soft, .scan-rail-chip, .scan-rail-count-badge, .scan-rail-segment, .scan-rail-segment-count, .scan-rail-filter-pill, .scan-rail-filter-count, .scan-rail-toggle, .scan-rail-btn, .scan-rail-card-action)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag, .scan-rail-tag-soft, .scan-rail-chip, .scan-rail-count-badge, .scan-rail-segment, .scan-rail-segment-count, .scan-rail-filter-pill, .scan-rail-filter-count, .scan-rail-toggle, .scan-rail-btn, .scan-rail-card-action)) {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: rgba(255, 255, 255, 0.06) !important;
  background-image: none !important;
  color: rgba(245, 245, 247, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag-success, .scan-rail-chip-success)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag-success, .scan-rail-chip-success)) {
  border-color: rgba(74, 222, 128, 0.22) !important;
  background: rgba(34, 197, 94, 0.13) !important;
  color: #bbf7d0 !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag-sky, .scan-rail-filter-pill-sky)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag-sky, .scan-rail-filter-pill-sky)) {
  border-color: rgba(56, 189, 248, 0.22) !important;
  background: rgba(14, 165, 233, 0.12) !important;
  color: #bae6fd !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag-amber, .scan-rail-chip-pending)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag-amber, .scan-rail-chip-pending)) {
  border-color: rgba(251, 191, 36, 0.22) !important;
  background: rgba(245, 158, 11, 0.13) !important;
  color: #fde68a !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag-rose, .scan-rail-chip-failed)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag-rose, .scan-rail-chip-failed)) {
  border-color: rgba(251, 113, 133, 0.24) !important;
  background: rgba(244, 63, 94, 0.13) !important;
  color: #fecdd3 !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-segment:hover, .scan-rail-toggle:hover, .scan-rail-btn:hover, .scan-rail-card-action:hover)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-segment:hover, .scan-rail-toggle:hover, .scan-rail-btn:hover, .scan-rail-card-action:hover)) {
  border-color: rgba(255, 255, 255, 0.24) !important;
  background: rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-segment.active),
:global(html.dark .subtitle-scan-rail-root .scan-rail-segment.active) {
  border-color: rgba(255, 255, 255, 0.26) !important;
  background: #3f4046 !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root .scan-rail-segment.active .scan-rail-segment-count),
:global(html.dark .subtitle-scan-rail-root .scan-rail-segment.active .scan-rail-segment-count) {
  border-color: rgba(255, 255, 255, 0.18) !important;
  background: rgba(255, 255, 255, 0.08) !important;
  color: rgba(245, 245, 247, 0.92) !important;
}

:global(html.kikoerumanager-dark .subtitle-scan-rail-root :is(.scan-rail-tag svg, .scan-rail-chip svg, .scan-rail-count-badge svg, .scan-rail-segment svg, .scan-rail-card-action svg)),
:global(html.dark .subtitle-scan-rail-root :is(.scan-rail-tag svg, .scan-rail-chip svg, .scan-rail-count-badge svg, .scan-rail-segment svg, .scan-rail-card-action svg)) {
  color: currentColor !important;
  stroke: currentColor !important;
}

@media (max-width: 420px) {
  .scan-rail-toggle-subtle {
    width: 30px;
    min-width: 30px;
    padding: 0;
  }

  .scan-rail-toggle-subtle .scan-rail-toggle-text {
    display: none;
  }

  .scan-rail-segment {
    min-height: 34px;
    padding: 0 8px;
    gap: 5px;
  }

  .scan-rail-segment-count {
    min-width: 20px;
    padding: 0 5px;
  }
}

@media (max-width: 360px) {
  .scan-rail-segment-grid {
    grid-template-columns: 1fr;
  }
}
</style>
