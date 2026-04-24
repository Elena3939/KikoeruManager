<template>
  <component
    :is="immersive ? 'div' : 'el-card'"
    :shadow="immersive ? undefined : 'never'"
    :class="immersive ? 'subtitle-tree-card subtitle-tree-card-immersive' : 'subtitle-tree-card'"
  >
    <template v-if="!immersive" #header>
      <div class="subtitle-section-header">
        <div class="subtitle-section-heading">
          <div class="subtitle-section-heading-title">
            <span class="subtitle-section-icon"><Sparkles :size="16" :stroke-width="2" /></span>
            <span class="subtitle-tree-title">字幕筛选与配对</span>
          </div>
          <div class="subtitle-section-tip">上半区先清理不要的原始字幕，下半区预览配对结果，最后一次性把音频和字幕处理成同名。</div>
        </div>
        <div class="subtitle-tree-actions">
          <el-tooltip effect="light" placement="top" content="刷新当前页">
            <span class="subtitle-btn-tooltip-wrap">
              <button class="workbench-icon-btn" :disabled="!view.subtitleInspectorInfo.subtitleDir || view.subtitleInspectorBusy" @click="view.reloadSubtitleInspector">
                <RefreshCw :size="14" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleInspectorLoading }" />
              </button>
            </span>
          </el-tooltip>
          <el-tooltip effect="light" placement="top" content="展开所有子目录">
            <span class="subtitle-btn-tooltip-wrap">
              <button class="workbench-icon-btn" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.expandSubtitleInspectorTree">
                <ChevronsDown :size="14" :stroke-width="2.2" />
              </button>
            </span>
          </el-tooltip>
          <el-tooltip effect="light" placement="top" content="折叠所有子目录">
            <span class="subtitle-btn-tooltip-wrap">
              <button class="workbench-icon-btn" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.collapseSubtitleInspectorTree">
                <ChevronsUp :size="14" :stroke-width="2.2" />
              </button>
            </span>
          </el-tooltip>
        </div>
      </div>
    </template>

    <div
      v-if="!view.subtitleInspectorInfo.subtitleDir && pendingInProgressTask"
      class="subtitle-inspector-empty subtitle-inspector-empty--loading"
      v-app-loading="{ loading: true, text: pendingLoadingText, size: 124 }"
    ></div>
    <div v-else-if="!view.subtitleInspectorInfo.subtitleDir" class="subtitle-inspector-empty">
      <AppEmptyState description="从左侧任务里选择一个已生成字幕目录的任务进行检查" size="default">
        <div class="subtitle-empty-tip">任务完成后会进入上方任务队列，点击对应卡片再进入这里做筛选和配对。</div>
      </AppEmptyState>
    </div>

    <div v-else class="subtitle-tree-shell" v-app-loading="{ loading: view.subtitleInspectorBusy, text: '正在处理字幕目录...', size: 124 }">
      <div class="subtitle-tree-info">
        <div class="subtitle-tree-info-top">
          <div class="subtitle-tree-info-head">
            <span class="subtitle-tree-info-icon"><FolderOpen :size="18" :stroke-width="2" /></span>
            <div class="subtitle-tree-info-main">
              <div class="subtitle-tree-title">{{ getDisplayFolderTitle() }}</div>
            </div>
          </div>
        </div>
        <div class="subtitle-tree-info-bottom">
          <div class="subtitle-tree-meta">
            <span class="subtitle-mini-chip subtitle-mini-chip-rj">{{ view.getTaskDisplayRJCode(view.activeSubtitleInspectTask) }}</span>
            <span v-if="view.getTaskSourceRJCode(view.activeSubtitleInspectTask)" class="subtitle-mini-chip subtitle-mini-chip-source"><Link :size="11" :stroke-width="2.4" />来源 {{ view.getTaskSourceRJCode(view.activeSubtitleInspectTask) }}</span>
            <span class="subtitle-mini-chip subtitle-mini-chip-audio"><Music :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorAudioFiles.length }} 个音频</span>
            <span class="subtitle-mini-chip subtitle-mini-chip-subtitle"><FileText :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorInfo.totalFiles }} 个字幕</span>
            <span class="subtitle-mini-chip subtitle-mini-chip-size"><Database :size="11" :stroke-width="2.4" />{{ view.formatFileSize(view.subtitleInspectorInfo.totalSize) }}</span>
          </div>
          <div v-if="view.activeSubtitleInspectTask" class="subtitle-tree-actions subtitle-tree-info-actions subtitle-tree-info-actions-bottom">
            <button
              class="workbench-pill-btn workbench-pill-danger"
              :disabled="!view.canCancelRJSubtitleTask?.(view.activeSubtitleInspectTask)"
              @click="view.cancelRJSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <CircleX :size="13" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleCancelingId === view.activeSubtitleInspectTask.id }" /><span>取消任务</span>
            </button>
            <button
              class="workbench-pill-btn"
              :disabled="!view.canClearCurrentSubtitleTask?.(view.activeSubtitleInspectTask)"
              @click="view.clearCurrentSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <Trash2 class="workbench-icon-clean" :size="13" :stroke-width="2.2" /><span>清空当前任务</span>
            </button>
            <button
              class="workbench-pill-btn workbench-pill-warn"
              :disabled="!view.canRerunSubtitleTask?.(view.activeSubtitleInspectTask)"
              @click="view.rerunSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <RotateCcw :size="13" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleTaskRerunId === view.activeSubtitleInspectTask.id }" /><span>重新执行爬取字幕</span>
            </button>
          </div>
        </div>
      </div>

      <div v-if="showPairing" class="subtitle-match-shell">
        <div class="subtitle-match-header">
          <div class="subtitle-match-header-title">
            <div class="subtitle-section-heading-title">
              <span class="subtitle-section-icon subtitle-section-icon-match"><Link2 :size="15" :stroke-width="2.2" /></span>
              <span class="subtitle-tree-title subtitle-tree-title-md">配对结果预览</span>
            </div>
            <div class="subtitle-section-tip">先在这里筛掉不需要的原始字幕，再生成预匹配结果，确认后再一键应用同名。</div>
            <div v-if="view.subtitleSequenceMode" class="subtitle-sequence-hint">
              <Wand2 :size="13" :stroke-width="2.2" />
              <span>顺序点选进行中：先在左侧依次点音频，再在右侧依次点字幕，然后生成顺序配对。当前已点选 音频 {{ view.subtitleSequenceSelection.audioPaths.length }} 项 / 字幕 {{ view.subtitleSequenceSelection.subtitlePaths.length }} 项。</span>
            </div>
          </div>
          <div class="subtitle-match-header-actions">
            <button class="workbench-pill-btn" @click="view.buildAutoSubtitlePairs">
              <Wand2 class="workbench-icon-auto" :size="13" :stroke-width="2.2" /><span>自动预配对</span>
            </button>
            <button :class="['workbench-pill-btn', view.subtitleSequenceMode ? 'workbench-pill-active' : '']" @click="view.setSubtitleSequenceMode(!view.subtitleSequenceMode)">
              <MousePointerClick class="workbench-icon-sequence" :size="13" :stroke-width="2.2" /><span>{{ view.subtitleSequenceMode ? '退出顺序点选' : '顺序点选配对' }}</span>
            </button>
            <button
              class="workbench-pill-btn"
              :disabled="view.subtitleSequenceMode ? !view.canBuildSequenceSubtitlePairs : !view.filteredSubtitleInspectorAudioFiles.length || !view.filteredSubtitleInspectorSubtitleFiles.length"
              @click="view.buildSequenceOrOrderedSubtitlePairs"
            >
              <ListOrdered class="workbench-icon-list" :size="13" :stroke-width="2.2" /><span>{{ view.subtitleSequenceMode ? '生成顺序预配对' : '按当前列表预配对' }}</span>
            </button>
            <el-tooltip
              effect="light"
              popper-class="subtitle-inspector-tooltip"
              placement="top"
              :disabled="Boolean(view.subtitleManualPairs.length)"
              content="请先在中间区域生成或添加至少一组配对，再执行应用。"
            >
              <span class="subtitle-btn-tooltip-wrap">
                <button
                  class="workbench-primary-btn"
                  :disabled="!view.subtitleManualPairs.length"
                  @click="view.applySubtitleManualPairs"
                >
                  <CheckCircle2 :size="14" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitlePairApplying }" /><span>{{ view.subtitleManualApplyLabel || '一键应用同名' }}</span>
                </button>
              </span>
            </el-tooltip>
          </div>
        </div>

        <div v-if="view.activeSubtitleInspectTask?.manual_match_completed || view.subtitleInspectorInfo.manualMatchCompleted" class="subtitle-match-done-alert">
          <CheckCircle2 :size="16" :stroke-width="2.2" />
          <span>已匹配完成，已应用 {{ view.activeSubtitleInspectTask?.manual_match_applied_pairs || view.subtitleInspectorInfo.manualMatchAppliedPairs || 0 }} 组配对。若还要调整，可以继续重新筛选后再次应用。</span>
        </div>

        <div class="subtitle-match-layout">
          <div class="subtitle-match-panel subtitle-match-panel-audio">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-audio"><Music :size="14" :stroke-width="2.2" />原音频目录</div>
              <div class="subtitle-match-panel-tools">
                <span class="subtitle-box-meta">{{ view.filteredSubtitleInspectorAudioFiles.length }} 项</span>
                <div class="subtitle-filter-segment" role="tablist" aria-label="音频筛选">
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleAudioFilterMode === 'all' }" @click="view.setSubtitleAudioFilterMode('all')">全部</button>
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleAudioFilterMode === 'paired' }" @click="view.setSubtitleAudioFilterMode('paired')">已配对</button>
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleAudioFilterMode === 'unpaired' }" @click="view.setSubtitleAudioFilterMode('unpaired')">未配对</button>
                </div>
              </div>
            </div>
            <input :value="view.subtitleInspectorAudioSearch" class="fm-search-input subtitle-match-search" placeholder="搜索音频名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorAudioSearch($event.target.value)">
            <div class="subtitle-match-list">
              <button
                v-for="audio in view.filteredSubtitleInspectorAudioFiles"
                :key="audio.path"
                type="button"
                class="subtitle-match-item"
                :class="{
                  active: view.subtitleMatchSelection.audioPath === audio.path,
                  paired: view.isAudioPaired(audio.path),
                  suspicious: view.isAudioSuspicious(audio.path),
                  queued: view.getSubtitleSequenceIndex('audio', audio.path) > 0
                }"
                @click="view.selectSubtitleAudio(audio)"
              >
                <div class="subtitle-match-name">
                  {{ formatSubtitleItemName(audio) }}
                  <span v-if="view.isAudioPaired(audio.path)" class="subtitle-match-badge badge-paired">已配对</span>
                  <span v-if="view.isAudioSuspicious(audio.path)" class="subtitle-match-badge badge-low">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('audio', audio.path)" class="subtitle-match-badge badge-seq">#{{ view.getSubtitleSequenceIndex('audio', audio.path) }}</span>
                </div>
                <div class="subtitle-match-meta">{{ audio.relative_path || audio.name }}</div>
              </button>
            </div>
          </div>

          <div class="subtitle-match-center">
            <div class="subtitle-match-panel-head subtitle-match-preview-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-center"><Link2 :size="14" :stroke-width="2.2" />配对结果预览</div>
              <div class="subtitle-match-preview-actions">
                <el-tooltip
                  effect="light"
                  popper-class="subtitle-inspector-tooltip"
                  placement="top"
                  :disabled="view.subtitleInspectorBusy || view.canAddSubtitleManualPair"
                  content="请先在左侧选一条音频，再在右侧选一条字幕，然后点此加入配对。"
                >
                  <span class="subtitle-btn-tooltip-wrap">
                    <button
                      type="button"
                      class="workbench-primary-btn workbench-primary-btn-inline"
                      :disabled="!view.canAddSubtitleManualPair || view.subtitleInspectorBusy"
                      @click="view.addSubtitleManualPair"
                    >
                      加入手动配对
                    </button>
                  </span>
                </el-tooltip>
                <button type="button" class="workbench-text-btn" :disabled="view.subtitleInspectorBusy || (!view.subtitleSequenceSelection.audioPaths.length && !view.subtitleSequenceSelection.subtitlePaths.length)" @click="view.clearSubtitleSequenceSelection">清空顺序</button>
                <button type="button" class="workbench-text-btn" :disabled="view.subtitleInspectorBusy || !view.subtitleManualPairs.length" @click="view.clearSubtitleManualPairs">清空配对</button>
              </div>
            </div>
            <div class="subtitle-match-pair-list">
              <div v-if="!view.subtitleManualPairs.length" class="subtitle-match-empty">
                <div>还没有生成配对结果</div>
                <div class="subtitle-card-tip">可以先点“自动预配对”，也可以左右各选一项后加入手动配对。</div>
              </div>
              <button
                v-for="(pair, index) in view.subtitleManualPairs"
                :key="pair.id"
                type="button"
                class="subtitle-match-pair"
                :class="{ active: view.subtitleSelectedManualPairId === pair.id, suspicious: pair.confidenceLevel === 'low' }"
                @click="view.setSubtitleSelectedManualPairId(pair.id)"
              >
                <div class="subtitle-match-pair-head">
                  <div class="subtitle-match-pair-head-left">
                    <span class="subtitle-match-pair-confidence" :class="`confidence-${pair.confidenceLevel || 'medium'}`">{{ view.getSubtitlePairConfidenceLabel(pair.confidenceLevel) }}</span>
                    <span class="subtitle-match-pair-track">配对 {{ index + 1 }}</span>
                  </div>
                  <span class="subtitle-match-pair-reason">{{ pair.matchReason || '手动配对' }}</span>
                </div>
                <div class="subtitle-match-pair-flow">
                  <div class="subtitle-match-flow-side subtitle-match-flow-source">
                    <span class="subtitle-match-flow-label">原始</span>
                    <div class="subtitle-match-flow-line" :title="getSubtitlePairRenamePreview(pair).before">
                      <Music v-if="getSubtitlePairRenamePreview(pair).kind === 'audio'" :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-audio" />
                      <FileText v-else :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-subtitle" />
                      <span class="subtitle-match-flow-text">{{ getSubtitlePairRenamePreview(pair).before }}</span>
                    </div>
                  </div>
                  <div class="subtitle-match-flow-arrow">
                    <ArrowRight :size="16" :stroke-width="2.2" />
                  </div>
                  <div class="subtitle-match-flow-side subtitle-match-flow-target">
                    <span class="subtitle-match-flow-label">应用后</span>
                    <div class="subtitle-match-flow-line" :title="getSubtitlePairRenamePreview(pair).after">
                      <Music v-if="getSubtitlePairRenamePreview(pair).kind === 'audio'" :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-audio" />
                      <FileText v-else :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-subtitle" />
                      <span class="subtitle-match-flow-text">{{ getSubtitlePairRenamePreview(pair).after }}</span>
                    </div>
                  </div>
                </div>
                <div class="subtitle-match-row-actions">
                  <button type="button" class="workbench-text-btn workbench-text-btn-danger" :disabled="view.subtitleInspectorBusy" @click.stop="view.removeSubtitleManualPair(pair.id)">移除</button>
                </div>
              </button>
            </div>
          </div>

          <div class="subtitle-match-panel subtitle-match-panel-subtitle">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-subtitle"><FileText :size="14" :stroke-width="2.2" />字幕目录</div>
              <div class="subtitle-match-panel-tools">
                <span class="subtitle-box-meta">{{ view.filteredSubtitleInspectorSubtitleFiles.length }} 项</span>
                <div class="subtitle-filter-segment" role="tablist" aria-label="字幕筛选">
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleSubtitleFilterMode === 'all' }" @click="view.setSubtitleSubtitleFilterMode('all')">全部</button>
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleSubtitleFilterMode === 'paired' }" @click="view.setSubtitleSubtitleFilterMode('paired')">已配对</button>
                  <button type="button" class="subtitle-filter-chip" :class="{ active: view.subtitleSubtitleFilterMode === 'unpaired' }" @click="view.setSubtitleSubtitleFilterMode('unpaired')">未配对</button>
                </div>
              </div>
            </div>
            <input :value="view.subtitleInspectorSubtitleSearch" class="fm-search-input subtitle-match-search" placeholder="搜索字幕名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorSubtitleSearch($event.target.value)">
            <div class="subtitle-match-list">
              <button
                v-for="subtitle in view.filteredSubtitleInspectorSubtitleFiles"
                :key="subtitle.path"
                type="button"
                class="subtitle-match-item"
                :class="{
                  active: view.subtitleMatchSelection.subtitlePath === subtitle.path,
                  paired: view.isSubtitlePaired(subtitle.path),
                  suspicious: view.isSubtitleSuspicious(subtitle.path),
                  queued: view.getSubtitleSequenceIndex('subtitle', subtitle.path) > 0
                }"
                @click="view.selectSubtitleFile(subtitle)"
              >
                <div class="subtitle-match-name">
                  {{ formatSubtitleItemName(subtitle) }}
                  <span v-if="view.isSubtitlePaired(subtitle.path)" class="subtitle-match-badge badge-paired">已配对</span>
                  <span v-if="view.isSubtitleSuspicious(subtitle.path)" class="subtitle-match-badge badge-low">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('subtitle', subtitle.path)" class="subtitle-match-badge badge-seq">#{{ view.getSubtitleSequenceIndex('subtitle', subtitle.path) }}</span>
                </div>
                <div class="subtitle-match-meta">{{ subtitle.relative_path || subtitle.name }}</div>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="showPairing && view.activeSubtitleTaskProgressLogs?.length" class="subtitle-pairing-log-shell">
        <div class="subtitle-pairing-log-head">
          <div class="subtitle-task-box-title">过程日志</div>
          <div class="subtitle-box-meta">{{ view.activeSubtitleTaskProgressLogs.length }} 条</div>
        </div>
        <div class="subtitle-log-list">
          <div v-for="(entry, idx) in view.activeSubtitleTaskProgressLogs" :key="`pair-log-${idx}`" class="subtitle-log-row">
            <span class="subtitle-log-time">{{ view.formatProgressLogTime(entry.time) }}</span>
            <span class="subtitle-log-level" :class="`level-${entry.level || 'info'}`">{{ view.getProgressLogLevelLabel(entry.level) }}</span>
            <span class="subtitle-inline-primary">{{ entry.message }}</span>
          </div>
        </div>
      </div>

      <div v-if="showTree" class="grid gap-3">
        <div class="group/search flex items-center gap-2 rounded-[12px] border border-slate-200 bg-slate-50/60 px-3 py-2 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] focus-within:border-sky-400 focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(56,189,248,0.15)] hover:border-slate-300">
          <Search :size="14" :stroke-width="2.2" class="shrink-0 text-slate-400 transition-all duration-300 group-focus-within/search:rotate-[-8deg] group-focus-within/search:scale-110 group-focus-within/search:text-sky-600" />
          <input
            :value="view.subtitleInspectorSearch"
            type="text"
            placeholder="搜索字幕文件名或路径..."
            :disabled="view.subtitleInspectorBusy"
            class="min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] font-medium text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0 disabled:cursor-not-allowed disabled:opacity-60"
            @input="view.setSubtitleInspectorSearch($event.target.value)"
          >
          <button
            v-if="view.subtitleInspectorSearch"
            type="button"
            class="group/clear inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-slate-400 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:scale-110 hover:bg-slate-200 hover:text-slate-700 active:scale-90"
            title="清空搜索"
            @click="view.setSubtitleInspectorSearch('')"
          >
            <X :size="12" :stroke-width="2.6" class="transition-transform duration-300 group-hover/clear:rotate-90" />
          </button>
        </div>

        <Transition name="sub-stage-fade">
          <div v-if="view.subtitleInspectorSelectedRows.length" class="flex items-center justify-between gap-3 rounded-[12px] border border-indigo-200 bg-gradient-to-br from-indigo-50/70 via-white to-white px-3.5 py-2.5 shadow-[0_2px_8px_rgba(79,70,229,0.05)]">
            <div class="flex items-center gap-2">
              <span class="inline-flex h-6 w-6 items-center justify-center rounded-[7px] bg-indigo-500 text-white">
                <CheckSquare :size="12" :stroke-width="2.4" />
              </span>
              <span class="text-[12.5px] font-semibold text-indigo-700">已选 {{ view.subtitleInspectorSelectedRows.length }} 项</span>
              <span class="hidden text-[11px] text-indigo-600/70 md:inline">支持 Ctrl+A · Ctrl/Cmd 点击 · Shift 范围</span>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                type="button"
                class="group/btn inline-flex items-center gap-1 rounded-[8px] border border-rose-300 bg-white px-3 py-1.5 text-[12px] font-medium text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-rose-500 hover:bg-rose-500 hover:text-white hover:shadow-[0_4px_12px_rgba(244,63,94,0.25)] active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
                :disabled="view.subtitleInspectorBusy && !view.subtitleInspectorDeleting"
                @click="view.batchDeleteSubtitleTreeEntries"
              >
                <Trash2 :size="12" :stroke-width="2.2" :class="['transition-transform duration-300 group-hover/btn:rotate-[-8deg] group-hover/btn:scale-110', view.subtitleInspectorDeleting ? 'is-spinning' : '']" />
                <span>删除选中</span>
              </button>
              <button
                type="button"
                class="group/btn inline-flex items-center gap-1 rounded-[8px] border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40"
                :disabled="view.subtitleInspectorBusy"
                @click="view.clearSubtitleInspectorSelection"
              >
                <XCircle :size="12" :stroke-width="2.2" class="transition-transform duration-300 group-hover/btn:rotate-90" />
                <span>取消选择</span>
              </button>
            </div>
          </div>
        </Transition>

        <div class="overflow-hidden rounded-[14px] border border-slate-200 bg-white shadow-[0_2px_8px_rgba(15,23,42,0.03)]">
          <div class="grid grid-cols-[40px_minmax(0,1fr)_96px_156px_112px] items-center gap-2 border-b border-slate-100 bg-slate-50/60 py-2 pl-3 pr-[29px] text-[11px] font-semibold uppercase tracking-[0.04em] text-slate-500">
            <div class="flex items-center justify-center">
              <input
                type="checkbox"
                class="h-3.5 w-3.5 cursor-pointer accent-slate-900"
                :checked="view.subtitleInspectorAllSelected"
                :indeterminate.prop="view.subtitleInspectorSomeSelected"
                :disabled="view.subtitleInspectorBusy"
                @click="view.toggleAllSubtitleInspectorRows"
              >
            </div>
            <div>文件名</div>
            <div>大小</div>
            <div>修改时间</div>
            <div class="flex w-[60px] justify-center justify-self-end">操作</div>
          </div>

          <div class="max-h-[560px] overflow-auto [scrollbar-gutter:stable]">
            <div v-if="!view.subtitleInspectorLoading && view.subtitleInspectorFlatTree.length === 0" class="flex items-center justify-center gap-2 px-4 py-10 text-[12px] text-slate-500">
              <FileSearch :size="14" :stroke-width="2.2" class="text-slate-400" />
              <span>{{ view.subtitleInspectorSearch ? '没有匹配的字幕文件' : '字幕目录为空' }}</span>
            </div>
            <div
              v-for="row in view.subtitleInspectorFlatTree"
              :key="row.id"
              class="group/row grid cursor-pointer grid-cols-[40px_minmax(0,1fr)_96px_156px_112px] items-center gap-2 border-b border-slate-50 px-3 py-2 transition-all duration-200 ease-out last:border-b-0 hover:bg-slate-50/60"
              :class="[
                row.type === 'dir' ? 'bg-slate-50/30' : '',
                view.subtitleInspectorSelectedIds.has(row.id) ? '!bg-indigo-50/70 ring-1 ring-inset ring-indigo-200' : ''
              ]"
              @click="view.handleSubtitleInspectorRowClick(row, $event)"
            >
              <div class="flex items-center justify-center" @click.stop>
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 cursor-pointer accent-slate-900"
                  :checked="view.subtitleInspectorSelectedIds.has(row.id)"
                  :disabled="view.subtitleInspectorBusy"
                  @click.stop="view.toggleSubtitleInspectorSelect(row, $event)"
                >
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-1.5" :style="{ paddingLeft: `${row.depth * 16}px` }">
                  <button
                    v-if="row.type === 'dir'"
                    type="button"
                    class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] text-slate-400 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:bg-slate-100 hover:text-slate-900 active:scale-90"
                    @click.stop="view.toggleSubtitleInspectorExpand(row)"
                  >
                    <ChevronRight
                      :size="12"
                      :stroke-width="2.4"
                      class="transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
                      :class="view.subtitleInspectorExpandedIds.has(row.id) ? 'rotate-90' : ''"
                    />
                  </button>
                  <span v-else-if="row.depth > 0" class="inline-block h-5 w-5 shrink-0"></span>
                  <span
                    class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/row:rotate-[6deg] group-hover/row:scale-110"
                    :class="row.type === 'dir'
                      ? 'bg-amber-50 text-amber-600 ring-1 ring-inset ring-amber-100'
                      : 'bg-sky-50 text-sky-600 ring-1 ring-inset ring-sky-100'"
                  >
                    <FolderClosed v-if="row.type === 'dir' && !view.subtitleInspectorExpandedIds.has(row.id)" :size="12" :stroke-width="2.2" />
                    <FolderOpen v-else-if="row.type === 'dir'" :size="12" :stroke-width="2.2" />
                    <FileText v-else :size="12" :stroke-width="2.2" />
                  </span>
                  <span class="truncate text-[13px] font-medium text-slate-900" :title="row.name">{{ row.name }}</span>
                </div>
              </div>
              <div class="text-[12px] font-medium tabular-nums text-slate-600">{{ view.formatFileSize(row.size) }}</div>
              <div class="text-[12px] tabular-nums text-slate-500">{{ view.formatDate(row.modified_time) }}</div>
              <div class="flex w-[60px] items-center justify-center gap-1 justify-self-end" @click.stop>
                <el-tooltip v-if="row.type === 'file'" effect="light" placement="top" content="重命名">
                  <button
                    type="button"
                    class="group/act inline-flex h-7 w-7 items-center justify-center rounded-[7px] border border-sky-100 bg-white text-sky-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.08] hover:border-sky-300 hover:bg-white active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-40"
                    :disabled="view.subtitleInspectorBusy"
                    @click="view.openSubtitleRenameDialog(row)"
                  >
                    <Pencil :size="12" :stroke-width="2.2" class="transition-transform duration-300 group-hover/act:rotate-[-12deg]" />
                  </button>
                </el-tooltip>
                <el-tooltip effect="light" placement="top" content="删除">
                  <button
                    type="button"
                    class="group/act inline-flex h-7 w-7 items-center justify-center rounded-[7px] border border-rose-100 bg-white text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.08] hover:border-rose-300 hover:bg-white active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-40"
                    :disabled="view.subtitleInspectorBusy"
                    @click="view.deleteSubtitleTreeEntry(row)"
                  >
                    <Trash2 :size="12" :stroke-width="2.2" class="transition-transform duration-300 group-hover/act:rotate-[-8deg] group-hover/act:scale-110" />
                  </button>
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </component>
</template>

<script setup>
import { computed } from 'vue'
import AppEmptyState from '../common/AppEmptyState.vue'
import {
  Sparkles,
  RefreshCw,
  ChevronsDown,
  ChevronsUp,
  ChevronRight,
  FolderOpen,
  FolderClosed,
  Hash,
  Link,
  Link2,
  Music,
  FileText,
  FileSearch,
  Database,
  CircleX,
  Wand2,
  MousePointerClick,
  ListOrdered,
  CheckCircle2,
  CheckSquare,
  RotateCcw,
  Trash2,
  ArrowRight,
  Search,
  X,
  XCircle,
  Pencil
} from 'lucide-vue-next'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  stageMode: {
    type: String,
    default: 'all'
  },
  showDeletePrecheck: {
    type: Boolean,
    default: true
  },
  immersive: {
    type: Boolean,
    default: false
  }
})

const view = computed(() => props.ctx || {})
const showPairing = computed(() => ['all', 'pairing'].includes(props.stageMode))
const showTree = computed(() => ['all', 'tree'].includes(props.stageMode))

const pendingInProgressTask = computed(() => {
  const candidates = [view.value.activeSubtitleTask, view.value.subtitleBackgroundActiveTask]
  for (const task of candidates) {
    if (!task) continue
    if (['pending', 'processing'].includes(task.status)) return task
  }
  const tasks = Array.isArray(view.value.inspectableSubtitleTasks) ? view.value.inspectableSubtitleTasks : []
  return tasks.find(task => ['pending', 'processing'].includes(task?.status)) || null
})

const pendingLoadingText = computed(() => {
  const task = pendingInProgressTask.value
  if (!task) return '正在执行字幕任务...'
  const step = task.current_step || '正在执行字幕任务'
  const rjcode = task.actual_rjcode || task.rjcode || ''
  return rjcode ? `${rjcode} · ${step}` : step
})

function getDisplayFolderTitle() {
  const folderName = String(view.value.activeSubtitleInspectTask?.folder_name || '').trim()
  if (folderName && !/[\\/]/.test(folderName)) return folderName
  const folderPath = String(view.value.subtitleInspectorInfo?.folderPath || view.value.subtitleInspectorInfo?.subtitleDir || '').trim()
  return view.value.getFileName?.(folderPath) || folderName || ''
}

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function formatSubtitleName(name = '') {
  const raw = String(name || '')
  const extMatch = raw.match(/\.[^.]+$/)
  const subtitleExt = extMatch?.[0] || ''
  const baseName = subtitleExt ? raw.slice(0, -subtitleExt.length) : raw
  return `${stripTrailingAudioExtension(baseName)}${subtitleExt}`
}

function formatSubtitleItemName(item = {}) {
  return formatSubtitleName(item?.display_name || item?.name || '')
}

function getSubtitlePairRenamePreview(pair = {}) {
  const strategy = String(view.value.subtitleNamingStrategy || pair.naming_strategy || 'audio')
  if (strategy === 'subtitle') {
    return {
      kind: 'audio',
      before: formatSubtitleName(pair.audio_name || ''),
      after: formatSubtitleName(pair.target_audio_name || pair.audio_name || '')
    }
  }
  return {
    kind: 'subtitle',
    before: formatSubtitleName(pair.subtitle_name || ''),
    after: formatSubtitleName(pair.target_subtitle_name || pair.subtitle_name || '')
  }
}
</script>

<style scoped>
.subtitle-tree-card {
  --apple-bg: #f8fafc;
  --apple-surface: #ffffff;
  --apple-surface-soft: #f8fafc;
  --apple-border: #e2e8f0;
  --apple-border-strong: #cbd5e1;
  --apple-text: #0f172a;
  --apple-text-soft: #334155;
  --apple-text-faint: #64748b;
  --apple-blue: #475569;
  --apple-shadow: rgba(15, 23, 42, 0.06) 0 4px 16px 0;
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --audio-accent: #0ea5e9;
  --subtitle-accent: #8b5cf6;
  --pair-accent: #10b981;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: none;
}
.subtitle-tree-card :deep(.el-card__header) {
  padding: 0;
  border-bottom: 1px solid #f1f5f9;
}
.subtitle-tree-card :deep(.el-card__body) { display: flex; flex-direction: column; min-height: 0; }
/* --- Header ------------------------------------------------- */
.subtitle-section-header { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 16px 22px; }
.subtitle-section-heading { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.subtitle-section-heading-title { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.subtitle-section-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 10px;
  background: #ffffff;
  color: #0078d4;
  border: 1px solid #e2e8f0;
  box-shadow: none;
  transition: transform .3s var(--ease-spring), box-shadow .3s var(--ease-spring);
}
.subtitle-section-icon-match {
  background: #ffffff;
  color: #0078d4;
  border-color: #e2e8f0;
  box-shadow: none;
}
.subtitle-section-heading:hover .subtitle-section-icon { transform: rotate(-4deg) scale(1.06); }
.subtitle-section-tip {
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 12px;
  color: var(--apple-text-soft);
  line-height: 1.55;
  letter-spacing: -0.12px;
}
.subtitle-tree-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.subtitle-btn-tooltip-wrap { display: inline-flex; vertical-align: middle; }
.subtitle-tree-action-tip { font-size: 12px; color: var(--apple-text-faint); }

/* --- Chips --------------------------------------------------- */
.subtitle-mini-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.1px;
  background: #ffffff;
  color: #475569;
  border: 1px solid #e2e8f0;
  transition: transform .3s var(--ease-spring), box-shadow .3s var(--ease-spring), border-color .3s var(--ease-spring), color .3s var(--ease-spring);
}
.subtitle-mini-chip :deep(svg),
.subtitle-mini-chip svg {
  opacity: .8;
  color: #94a3b8;
  transition: transform .3s var(--ease-spring), color .3s var(--ease-spring);
}
.subtitle-mini-chip:hover {
  transform: translateY(-1px) scale(1.02);
  border-color: #cbd5e1;
  color: #0f172a;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
}
.subtitle-mini-chip:hover :deep(svg),
.subtitle-mini-chip:hover svg {
  color: #475569;
  transform: scale(1.1);
}
.subtitle-mini-chip-accent {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.14);
}
.subtitle-mini-chip-accent :deep(svg),
.subtitle-mini-chip-accent svg { color: #cbd5e1; opacity: 1; }
.subtitle-mini-chip-accent:hover {
  background: #020617;
  border-color: #020617;
  color: #ffffff;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.22);
}
.subtitle-mini-chip-accent:hover :deep(svg),
.subtitle-mini-chip-accent:hover svg { color: #f1f5f9; }

.subtitle-mini-chip-rj {
  background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
  color: #ffffff;
  border-color: #0f172a;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.14);
}
.subtitle-mini-chip-source svg { color: #0078d4; opacity: 1; }
.subtitle-mini-chip-audio svg { color: #00a2ed; opacity: 1; }
.subtitle-mini-chip-subtitle svg { color: #7f56d9; opacity: 1; }
.subtitle-mini-chip-size svg { color: #107c10; opacity: 1; }
.subtitle-mini-chip-source:hover { border-color: #bae6fd; box-shadow: 0 6px 14px rgba(0, 120, 212, 0.12); }
.subtitle-mini-chip-audio:hover { border-color: #bae6fd; box-shadow: 0 6px 14px rgba(0, 162, 237, 0.12); }
.subtitle-mini-chip-subtitle:hover { border-color: #ddd6fe; box-shadow: 0 6px 14px rgba(127, 86, 217, 0.12); }
.subtitle-mini-chip-size:hover { border-color: #bbf7d0; box-shadow: 0 6px 14px rgba(16, 124, 16, 0.12); }

/* --- Icon action buttons ------------------------------------ */
.workbench-icon-btn {
  appearance: none;
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: var(--apple-text-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all .3s var(--ease-spring);
}
.workbench-icon-btn:hover:not(:disabled) {
  background: linear-gradient(180deg, #ffffff 0%, #edf2f7 100%) !important;
  border-color: #cbd5e1;
  color: #334155 !important;
  transform: translateY(-2px) scale(1.04);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.workbench-icon-btn:hover:not(:disabled) svg { transform: scale(1.15); }
.workbench-icon-btn:active:not(:disabled) { transform: scale(0.94); }
.workbench-icon-btn svg { transition: transform .3s var(--ease-spring); }

/* --- Pill action buttons ----------------------------------- */
.workbench-pill-btn,
.workbench-primary-btn,
.workbench-text-btn,
.subtitle-filter-chip {
  appearance: none;
  font: inherit;
}
.workbench-pill-btn {
  min-height: 36px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.1px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all .3s var(--ease-spring);
}
.workbench-pill-btn svg,
.workbench-primary-btn svg { transition: transform .3s var(--ease-spring), color .3s var(--ease-spring); }
.workbench-pill-btn > svg,
.workbench-pill-btn :deep(> svg) { color: #94a3b8; }
.workbench-pill-btn > .workbench-icon-clean,
.workbench-pill-btn :deep(> .workbench-icon-clean) { color: #0078d4; }
.workbench-pill-btn > .workbench-icon-auto,
.workbench-pill-btn :deep(> .workbench-icon-auto) { color: #107c10; }
.workbench-pill-btn > .workbench-icon-sequence,
.workbench-pill-btn :deep(> .workbench-icon-sequence) { color: #0078d4; }
.workbench-pill-btn > .workbench-icon-list,
.workbench-pill-btn :deep(> .workbench-icon-list) { color: #d97706; }
.workbench-pill-btn:hover:not(:disabled) {
  border-color: #cbd5e1;
  color: #0f172a;
  background: #ffffff;
  transform: translateY(-2px) scale(1.02);
  box-shadow: none;
}
.workbench-pill-btn:hover:not(:disabled) svg { transform: scale(1.15) rotate(-4deg); }
.workbench-pill-btn:active:not(:disabled) { transform: scale(0.96); }
.workbench-pill-btn.workbench-pill-active {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.workbench-pill-btn.workbench-pill-active svg { color: #cbd5e1; }
.workbench-pill-btn.workbench-pill-active:hover:not(:disabled) {
  background: #020617;
  border-color: #020617;
  color: #ffffff;
}
.workbench-pill-btn.workbench-pill-active:hover:not(:disabled) svg { color: #f1f5f9; }
.workbench-pill-btn.workbench-pill-danger {
  color: #e11d48;
  border-color: #fecdd3;
  background: #fff1f2;
}
.workbench-pill-btn.workbench-pill-danger svg { color: #fb7185; }
.workbench-pill-btn.workbench-pill-warn {
  color: #b45309;
  border-color: #fde68a;
  background: #fffbeb;
}
.workbench-pill-btn.workbench-pill-warn svg { color: #f59e0b; }
.workbench-pill-btn.workbench-pill-danger:hover:not(:disabled) {
  background: #ffe4e6;
  border-color: #fb7185;
  color: #be123c;
  box-shadow: 0 10px 22px rgba(225, 29, 72, 0.16);
}
.workbench-pill-btn.workbench-pill-danger:hover:not(:disabled) svg { color: #e11d48; }
.workbench-pill-btn.workbench-pill-warn:hover:not(:disabled) {
  background: #fef3c7;
  border-color: #f59e0b;
  color: #92400e;
  box-shadow: 0 10px 22px rgba(245, 158, 11, 0.16);
}
.workbench-pill-btn.workbench-pill-warn:hover:not(:disabled) svg { color: #d97706; }
.workbench-primary-btn {
  min-height: 36px;
  border-radius: 10px;
  padding: 0 16px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid #0f172a;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.16);
  transition: all .3s var(--ease-spring);
}
.workbench-primary-btn svg { color: #e2e8f0; }
.workbench-primary-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.03);
  background: linear-gradient(180deg, #0f172a 0%, #020617 100%);
  border-color: #020617;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.26);
}
.workbench-primary-btn:hover:not(:disabled) svg { transform: scale(1.2) rotate(-6deg); color: #ffffff; }
.workbench-primary-btn:active:not(:disabled) { transform: scale(0.96); }
.workbench-primary-btn-inline {
  min-height: 34px;
  padding: 0 14px;
  font-size: 12px;
}
.workbench-text-btn {
  border: none;
  background: transparent;
  color: #6b7f98;
  font-size: 13px;
  font-weight: 700;
  padding: 0 2px;
  cursor: pointer;
  transition: color .2s ease, transform .2s ease;
}
.workbench-text-btn:hover:not(:disabled) {
  color: #17324c;
  transform: translateY(-1px);
}
.workbench-text-btn-danger { color: #d14343; }
.workbench-text-btn-danger:hover:not(:disabled) { color: #b82b2b; }
.workbench-icon-btn:disabled,
.workbench-pill-btn:disabled,
.workbench-primary-btn:disabled,
.workbench-text-btn:disabled,
.subtitle-filter-chip:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none !important;
}
.is-spinning { animation: subtitle-spin 1s linear infinite; }
@keyframes subtitle-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.subtitle-filter-segment {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 11px;
  background: #fafafc;
  border: 3px solid rgba(0, 0, 0, 0.04);
}
.subtitle-filter-chip {
  min-height: 30px;
  padding: 0 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(0, 0, 0, 0.8);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all .25s var(--ease-spring);
}
.subtitle-filter-chip:hover:not(:disabled) {
  color: #1d1d1f;
  background: rgba(255, 255, 255, 0.82);
}
.subtitle-filter-chip.active {
  background: #ffffff;
  color: #1d1d1f;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

/* --- Shell --------------------------------------------------- */
.subtitle-tree-shell { display: flex; flex-direction: column; gap: 12px; min-height: 820px; padding: 0; }
.subtitle-inspector-empty { display: grid; gap: 10px; padding: 28px 0 18px; }
.subtitle-inspector-empty--loading { min-height: 320px; padding: 40px 0; position: relative; }
.subtitle-empty-tip { text-align: center; font-size: 12px; color: var(--apple-text-faint); }

/* --- Task info banner --------------------------------------- */
.subtitle-tree-info {
  display: grid;
  gap: 12px;
  padding: 18px 20px;
  border-radius: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: none;
}
.subtitle-tree-info-top { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
.subtitle-tree-info-bottom { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
.subtitle-tree-info-head { display: flex; gap: 12px; align-items: flex-start; min-width: 0; }
.subtitle-tree-info-icon {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: linear-gradient(135deg, #fff7ed, #ffffff);
  color: #f59e0b;
  border: 1px solid #fed7aa;
  box-shadow: none;
  transition: transform .3s var(--ease-spring);
}
.subtitle-tree-info:hover .subtitle-tree-info-icon { transform: rotate(-6deg) scale(1.05); }
.subtitle-tree-info-main { min-width: 0; display: grid; gap: 8px; }
.subtitle-tree-info-desc {
  max-width: 760px;
  font-size: 14px;
  line-height: 1.47;
  color: rgba(29, 29, 31, 0.72);
}
.subtitle-tree-info-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.subtitle-tree-title {
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 22px;
  font-weight: 600;
  color: #1d1d1f;
  line-height: 1.18;
  letter-spacing: -0.22px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: normal;
}
.subtitle-tree-title-md { font-size: 24px; font-weight: 600; line-height: 1.14; letter-spacing: -0.24px; }
.subtitle-tree-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.subtitle-tree-info-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.subtitle-stat-card {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 14px;
  border: none;
  background: #ffffff;
  box-shadow: none;
  transition: transform .25s var(--ease-spring), background-color .25s ease;
}
.subtitle-stat-card:hover {
  transform: translateY(-2px) scale(1.02);
  background: #fbfbfd;
}
.subtitle-stat-card-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.48);
}
.subtitle-stat-card-value {
  font-size: 19px;
  font-weight: 600;
  line-height: 1.19;
  letter-spacing: 0.231px;
  color: #1d1d1f;
}

/* --- Match shell -------------------------------------------- */
.subtitle-match-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
  padding: 12px 0 0;
  border-radius: 0;
  background: transparent;
  border: none;
  box-shadow: none;
}
.subtitle-pairing-log-shell {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
  border: 1px solid #e2e8f0;
  box-shadow: none;
}
.subtitle-pairing-log-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.subtitle-match-header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  flex-wrap: wrap;
  padding: 16px 18px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: none;
}
.subtitle-match-header-title { display: flex; flex-direction: column; gap: 6px; min-width: 0; flex: 1; }
.subtitle-match-header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.subtitle-sequence-hint {
  margin-top: -2px;
  padding: 12px 14px;
  display: inline-flex;
  gap: 8px;
  align-items: flex-start;
  border: 1px dashed #cbd5e1;
  border-radius: 16px;
  background: #ffffff;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}
.subtitle-sequence-hint svg { flex: 0 0 auto; margin-top: 2px; color: #0078d4; }
.subtitle-match-done-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: -2px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid #bbf7d0;
  background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%);
  color: #1d1d1f;
  font-size: 13px;
  line-height: 1.6;
  box-shadow: none;
}
.subtitle-match-done-alert svg { flex: 0 0 auto; color: #107c10; }

.subtitle-match-layout { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.5fr) minmax(0, 1.05fr); gap: 18px; align-items: stretch; }
.subtitle-match-panel, .subtitle-match-center {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  background: #ffffff;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: none;
}
.subtitle-match-panel-audio,
.subtitle-match-panel-subtitle,
.subtitle-match-center { border-top: none; }
.subtitle-match-panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}
.subtitle-match-preview-head { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; align-items: start; }
.subtitle-match-panel-tools, .subtitle-match-preview-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.subtitle-match-preview-actions { width: 100%; justify-content: flex-start; align-items: center; gap: 6px; }
.subtitle-match-panel-heading { display: grid; gap: 5px; min-width: 0; }
.subtitle-task-box-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 21px;
  font-weight: 700;
  color: #1d1d1f;
  line-height: 1.19;
  letter-spacing: 0.231px;
}
.subtitle-task-box-title-audio { color: #334155; }
.subtitle-task-box-title-audio svg { color: var(--audio-accent); }
.subtitle-task-box-title-subtitle { color: #334155; }
.subtitle-task-box-title-subtitle svg { color: var(--subtitle-accent); }
.subtitle-task-box-title-center { color: #334155; }
.subtitle-task-box-title-center svg { color: var(--pair-accent); }
.subtitle-match-panel-caption {
  font-size: 14px;
  line-height: 1.29;
  letter-spacing: -0.224px;
  color: rgba(0, 0, 0, 0.48);
}
.subtitle-box-meta { font-size: 12px; color: rgba(0, 0, 0, 0.48); font-weight: 600; }
.subtitle-match-search { width: 100%; }
.subtitle-match-list, .subtitle-match-pair-list {
  display: grid;
  gap: 10px;
  min-width: 0;
  min-height: 440px;
  max-height: 680px;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 6px;
  align-content: start;
  grid-auto-rows: max-content;
  scrollbar-gutter: stable;
}
.subtitle-match-list::-webkit-scrollbar,
.subtitle-match-pair-list::-webkit-scrollbar { width: 6px; }
.subtitle-match-list::-webkit-scrollbar-thumb,
.subtitle-match-pair-list::-webkit-scrollbar-thumb { background: #d8e2f0; border-radius: 999px; }

.subtitle-match-item, .subtitle-match-pair {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  text-align: left;
  border: 1px solid #edf2f7;
  border-radius: 16px;
  background: #ffffff;
  padding: 10px 12px;
  cursor: pointer;
  transition: all .3s var(--ease-spring);
  position: relative;
  box-shadow: none;
}
.subtitle-match-item:hover, .subtitle-match-pair:hover {
  border-color: #dbe4ee;
  background: #ffffff;
  transform: translateY(-2px) scale(1.02);
  box-shadow: none;
}
.subtitle-match-item:active, .subtitle-match-pair:active { transform: scale(0.98); }
.subtitle-match-item.active {
  border-color: #0f172a;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.24), inset 0 0 0 1px rgba(15, 23, 42, 0.14);
}
.subtitle-match-item.queued {
  border-color: #cbd5e1;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.10);
}
.subtitle-match-item.paired,
.subtitle-match-pair.active {
  border-color: #cbd5e1;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.06);
}
.subtitle-match-item.active.queued {
  border-color: #0f172a;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.24), inset 0 0 0 1px rgba(15, 23, 42, 0.14);
}
.subtitle-match-item.active.paired {
  border-color: #0f172a;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.24), inset 0 0 0 1px rgba(15, 23, 42, 0.14);
}
.subtitle-match-item.suspicious,
.subtitle-match-pair.suspicious {
  border-color: #fed7aa;
  background: #ffffff;
}
.subtitle-match-name {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.224px;
  line-height: 1.24;
}
.subtitle-match-meta {
  margin-top: 6px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 10px;
  line-height: 1.4;
  color: rgba(0, 0, 0, 0.48);
  word-break: break-all;
  letter-spacing: -0.12px;
}
.subtitle-match-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 8px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid transparent;
  line-height: 1.3;
}
.badge-paired { background: #f0fdf4; color: #15803d; border-color: #bbf7d0; }
.badge-low { background: #fff7ed; color: #c2410c; border-color: #fed7aa; }
.badge-seq { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
.subtitle-match-empty {
  min-height: 220px;
  border: 1px dashed #d5dfed;
  border-radius: 18px;
  display: grid;
  place-items: center;
  gap: 6px;
  padding: 24px 20px;
  text-align: center;
  color: #6f8198;
  line-height: 1.55;
  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 100%);
}
.subtitle-card-tip { font-size: 12px; color: #8394aa; }

/* --- Pair card internal: confidence head + source->target flow --- */
.subtitle-match-pair-head { display: flex; justify-content: space-between; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.subtitle-match-pair-head-left { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.subtitle-match-pair-confidence,
.subtitle-match-pair-track {
  font-size: 10px;
  font-weight: 700;
  border-radius: 7px;
  padding: 3px 7px;
  border: 1px solid transparent;
  line-height: 1.35;
}
.confidence-high { background: #f0fdf4; color: #15803d; border-color: #bbf7d0; }
.confidence-medium { background: #f8fafc; color: #475569; border-color: #e2e8f0; }
.confidence-low { background: #fff7ed; color: #c2410c; border-color: #fed7aa; }
.subtitle-match-pair-track { color: #166534; background: #f0fdf4; border-color: #dcfce7; }
.subtitle-match-pair-reason { font-size: 10px; color: rgba(0, 0, 0, 0.48); letter-spacing: -0.12px; }

.subtitle-match-pair-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
  align-items: stretch;
  min-width: 0;
  max-width: 100%;
  padding: 8px 9px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}
.subtitle-match-flow-side { display: grid; gap: 4px; min-width: 0; }
.subtitle-match-flow-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(0, 0, 0, 0.48);
}
.subtitle-match-flow-source .subtitle-match-flow-label { color: #8a97aa; }
.subtitle-match-flow-target .subtitle-match-flow-label { color: #64748b; }
.subtitle-match-flow-line {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 6px;
  align-items: flex-start;
  font-size: 10.5px;
  line-height: 1.35;
  color: #1d1d1f;
  min-width: 0;
}
.subtitle-match-flow-target .subtitle-match-flow-line { color: #1d1d1f; font-weight: 600; }
.subtitle-match-flow-icon { flex: 0 0 auto; margin-top: 1px; }
.subtitle-match-flow-icon-audio { color: var(--audio-accent); }
.subtitle-match-flow-icon-subtitle { color: var(--subtitle-accent); }
.subtitle-match-flow-text {
  min-width: 0;
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
  word-break: break-all;
  display: block;
}
.subtitle-match-flow-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  color: rgba(29, 29, 31, 0.72);
  background: #f8fafc;
  justify-self: center;
  align-self: center;
  transform: rotate(90deg);
}
.subtitle-match-pair:hover .subtitle-match-flow-arrow { animation: subtitle-arrow-nudge-vertical 0.9s var(--ease-spring) infinite alternate; }
@keyframes subtitle-arrow-nudge-vertical { from { transform: rotate(90deg) translateX(0); } to { transform: rotate(90deg) translateX(2px); } }
.subtitle-match-row-actions { margin-top: 2px; display: flex; justify-content: flex-end; }

/* --- Tree (bottom file list) --------------------------------- */
.subtitle-tree-toolbar { display: flex; justify-content: flex-end; }
.subtitle-tree-selection-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #f2d6d2;
  border-radius: 12px;
  background: linear-gradient(180deg, #fff8f7 0%, #ffffff 100%);
  box-shadow: 0 6px 16px rgba(212, 76, 70, 0.08);
}
.subtitle-tree-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.subtitle-tree-selection-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-tree-selection-tip { font-size: 11px; color: #8a97aa; }
.subtitle-tree-head { margin-top: 2px; border-radius: 12px 12px 0 0; overflow: hidden; }
.subtitle-tree-scroll {
  min-height: 260px;
  max-height: 520px;
  overflow: auto;
  border: 1px solid #e9eef5;
  border-radius: 0 0 12px 12px;
  background: #ffffff;
}
.subtitle-tree-row-actions { display: flex; gap: 6px; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 110px 170px 130px; align-items: center; }
.fm-head {
  min-height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid #e8edf5;
  background: #ffffff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #5f7188;
}
.fm-row {
  min-height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f6;
  font-size: 13px;
  color: var(--apple-text);
  transition: background .2s ease;
}
.fm-row:hover { background: #f7fbff; }
.fm-row:last-child { border-bottom: none; }
.fm-row-dir { background: #fafbfd; }
.fm-row-selected { background: linear-gradient(90deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.98)) !important; box-shadow: inset 3px 0 0 #0078d4; }
.fm-empty { display: flex; align-items: center; justify-content: center; min-height: 180px; color: #a2b0c2; font-size: 13px; }
.fm-col-name, .fm-col-size, .fm-col-time, .fm-col-action { min-width: 0; }
.fm-col-size, .fm-col-time { font-variant-numeric: tabular-nums; color: var(--apple-text-soft); font-size: 12px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow-toggle { width: 18px; height: 18px; border: none; background: transparent; color: #8ea0b8; cursor: pointer; padding: 0; font-weight: 700; transition: transform .3s var(--ease-spring), color .2s ease; }
.fm-arrow-toggle.open { transform: rotate(90deg); color: #64748b; }
.fm-arrow-placeholder { width: 18px; flex: 0 0 18px; }
.fm-file-icon { width: 20px; display: inline-flex; justify-content: center; color: #64748b; transition: transform .3s var(--ease-spring); }
.fm-row:hover .fm-file-icon { transform: scale(1.15); }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-edit, .fm-link-danger {
  border: 1px solid #d7dfec;
  background: #fff;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all .3s var(--ease-spring);
}
.fm-link-edit { color: #475569; }
.fm-link-danger { color: #d84b46; border-color: #efc1be; background: #fff7f7; }
.fm-link-edit:hover {
  color: #1f2937;
  border-color: #cbd5e1;
  background: #f8fafc;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
  transform: translateY(-2px) scale(1.04);
}
.fm-link-danger:hover {
  color: #c40017;
  border-color: #f3a8a8;
  background: #fff0f0;
  box-shadow: 0 6px 14px rgba(215, 0, 21, 0.14);
  transform: translateY(-2px) scale(1.04);
}
.fm-link-edit:active, .fm-link-danger:active { transform: scale(0.95); }
.fm-check { width: 14px; height: 14px; accent-color: #64748b; cursor: pointer; }
</style>
