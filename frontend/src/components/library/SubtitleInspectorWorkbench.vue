<template>
  <div :class="immersive ? 'subtitle-inspector-workbench-root flex h-full min-h-0 flex-col overflow-hidden' : 'flex flex-col min-h-0 rounded-[18px] border border-slate-200 bg-white'">
    <div v-if="!immersive" class="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-slate-100">
      <div class="flex flex-col gap-0.5 min-w-0">
        <div class="flex items-center gap-2">
          <span class="inline-flex items-center justify-center w-7 h-7 rounded-[10px] border border-slate-200 bg-white text-blue-600"><Sparkles :size="15" :stroke-width="2" /></span>
          <span class="text-[14.5px] font-semibold text-slate-900 tracking-tight">字幕筛选与配对</span>
        </div>
        <p class="text-[11.5px] text-slate-500 leading-relaxed pl-9">上半区先清理不要的原始字幕，下半区预览配对结果，最后一次性把音频和字幕处理成同名。</p>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <button class="inline-flex items-center justify-center w-8 h-8 rounded-xl border border-slate-200 bg-white text-slate-500 transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-slate-300 hover:text-slate-900 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="!view.subtitleInspectorInfo.subtitleDir || view.subtitleInspectorBusy" title="刷新当前页" @click="view.reloadSubtitleInspector?.()">
          <RefreshCw :size="13" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleInspectorLoading }" />
        </button>
        <button class="inline-flex items-center justify-center w-8 h-8 rounded-xl border border-slate-200 bg-white text-slate-500 transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-slate-300 hover:text-slate-900 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" title="展开所有子目录" @click="view.expandSubtitleInspectorTree?.()">
          <ChevronsDown :size="13" :stroke-width="2.2" />
        </button>
        <button class="inline-flex items-center justify-center w-8 h-8 rounded-xl border border-slate-200 bg-white text-slate-500 transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-slate-300 hover:text-slate-900 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" title="折叠所有子目录" @click="view.collapseSubtitleInspectorTree?.()">
          <ChevronsUp :size="13" :stroke-width="2.2" />
        </button>
      </div>
    </div>

    <div
      v-if="!view.subtitleInspectorInfo.subtitleDir && activeTaskMissingSubtitleDir"
      class="grid min-h-[320px] place-items-center px-6 py-10"
    >
      <div class="max-w-[520px] rounded-[14px] border border-amber-200 bg-amber-50 px-4 py-3 text-center">
        <AlertTriangle class="mx-auto mb-2 h-6 w-6 text-amber-500" :stroke-width="2.2" />
        <div class="text-[13px] font-semibold text-amber-800">当前待配对任务缺少工作台字幕目录</div>
        <div class="mt-1 text-[11.5px] leading-relaxed text-amber-700">
          中间区暂时无法读取原始字幕文件。任务队列会保留，刷新后如果目录恢复会自动加载。
        </div>
      </div>
    </div>
    <div
      v-else-if="!view.subtitleInspectorInfo.subtitleDir && pendingInProgressTask"
      class="relative min-h-[320px]"
      v-app-loading="{ loading: true, text: pendingLoadingText, size: 124 }"
    ></div>
    <div v-else-if="!view.subtitleInspectorInfo.subtitleDir" class="py-10 px-4">
      <AppEmptyState description="从左侧任务里选择一个已生成字幕目录的任务进行检查" size="default">
        <div class="text-center text-[11.5px] text-slate-400 mt-1">任务完成后会进入上方任务队列，点击对应卡片再进入这里做筛选和配对。</div>
      </AppEmptyState>
    </div>

    <div
      v-else
      class="subtitle-inspector-workbench-scroll flex min-h-0 flex-col gap-3 overflow-auto p-3"
      :class="{ 'is-pairing-mode': showPairing && !showTree }"
      v-app-loading="{ loading: view.subtitleInspectorLoading || view.subtitleInspectorDeleting || view.subtitlePairApplying, text: '正在处理字幕目录...', size: 124 }"
    >
      <div class="flex items-center justify-between gap-3 flex-wrap px-4 py-3 rounded-[12px] border border-slate-200 bg-white">

        <div class="flex items-center gap-2.5 min-w-0">
          <span class="subtitle-folder-mark flex-shrink-0 inline-flex items-center justify-center w-8 h-8"><FolderOpen :size="18" :stroke-width="2.35" /></span>

          <span class="text-[14px] font-semibold text-slate-900 truncate">{{ getDisplayFolderTitle() }}</span>
        </div>
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="inline-flex items-center gap-1 px-2 py-1 rounded-[7px] text-[11px] font-semibold bg-slate-900 text-white">{{ view.getTaskDisplayRJCode(view.activeSubtitleInspectTask) }}</span>
          <span v-if="view.getTaskSourceRJCode(view.activeSubtitleInspectTask)" class="inline-flex items-center gap-1 px-2 py-1 rounded-[7px] text-[11px] font-medium bg-white border border-slate-200 text-slate-600"><Link :size="11" :stroke-width="2.4" />来源 {{ view.getTaskSourceRJCode(view.activeSubtitleInspectTask) }}</span>
          <span class="inline-flex items-center gap-1 px-2 py-1 rounded-[7px] text-[11px] font-medium bg-slate-50 border border-slate-200 text-slate-600"><Music :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorAudioFiles.length }} 个音频</span>
          <span class="inline-flex items-center gap-1 px-2 py-1 rounded-[7px] text-[11px] font-medium bg-slate-50 border border-slate-200 text-slate-600"><FileText :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorInfo.totalFiles }} 个字幕</span>
          <span class="inline-flex items-center gap-1 px-2 py-1 rounded-[7px] text-[11px] font-medium bg-slate-50 border border-slate-200 text-slate-600"><Database :size="11" :stroke-width="2.4" />{{ view.formatFileSize(view.subtitleInspectorInfo.totalSize) }}</span>

        </div>
        <div v-if="view.activeSubtitleInspectTask" class="flex items-center gap-1.5 flex-wrap">
          <button class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium border border-rose-200 bg-rose-50 text-rose-700 transition-all duration-200 hover:bg-rose-100 hover:border-rose-300 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed" :disabled="!view.canCancelRJSubtitleTask?.(view.activeSubtitleInspectTask)" @click="view.cancelRJSubtitleTask(view.activeSubtitleInspectTask)">
            <CircleX :size="12" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleCancelingId === view.activeSubtitleInspectTask.id }" />取消任务
          </button>
          <button class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-700 transition-all duration-200 hover:border-slate-300 hover:bg-slate-50 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed" :disabled="!view.canClearCurrentSubtitleTask?.(view.activeSubtitleInspectTask)" @click="view.clearCurrentSubtitleTask(view.activeSubtitleInspectTask)">
            <Trash2 :size="12" :stroke-width="2.2" class="text-sky-500" />清空当前任务
          </button>
          <button class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium border border-amber-200 bg-amber-50 text-amber-700 transition-all duration-200 hover:bg-amber-100 hover:border-amber-300 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed" :disabled="!view.canRerunSubtitleTask?.(view.activeSubtitleInspectTask)" @click="view.rerunSubtitleTask(view.activeSubtitleInspectTask)">
            <RotateCcw :size="12" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleTaskRerunId === view.activeSubtitleInspectTask.id }" />重新执行爬取字幕
          </button>
        </div>
      </div>

      <div v-if="showPairing" class="subtitle-pairing-stage flex min-h-0 flex-col gap-3">
        <div class="grid gap-3 px-4 py-3.5 rounded-[12px] border border-slate-200 bg-white">

          <div class="flex flex-col gap-1.5 min-w-0">
            <div class="flex items-center gap-2">
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-[8px] border border-slate-200 bg-white text-blue-600"><Link2 :size="13" :stroke-width="2.2" /></span>
              <span class="text-[13px] font-semibold text-slate-900">配对结果预览</span>
            </div>
            <p class="text-[11.5px] leading-relaxed text-slate-500 pl-8">先在这里筛掉不需要的原始字幕，再生成预匹配结果，确认后再一键应用同名。</p>
            <div v-if="view.subtitleSequenceMode" class="ml-8 inline-flex items-start gap-2 px-3 py-2 rounded-[11px] border border-blue-200 bg-gradient-to-r from-blue-50 via-white to-violet-50 text-[11.5px] leading-relaxed text-blue-700 shadow-[0_8px_24px_rgba(37,99,235,0.12)]">

              <Wand2 :size="12" :stroke-width="2.2" class="text-blue-600 mt-0.5 flex-shrink-0 is-sequence-pulse" />
              <span>顺序点选进行中：左侧蓝色序号是音频顺序，右侧紫色序号是字幕顺序。当前已点选 音频 {{ view.subtitleSequenceSelection.audioPaths.length }} 项 / 字幕 {{ view.subtitleSequenceSelection.subtitlePaths.length }} 项。</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 flex-wrap justify-end">
            <button class="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-semibold border border-cyan-200 bg-cyan-50 text-cyan-700 transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:border-cyan-300 hover:bg-cyan-100 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="view.subtitleInspectorBusy || !view.subtitleInspectorAudioFiles.length || !view.subtitleInspectorSubtitleFiles.length" title="让 AI 直接生成配对草稿；确认后再点击导入。" @click="view.buildAISubtitlePairs">
              <Bot :size="12" :stroke-width="2.2" :class="{ 'is-spinning': view.subtitleAutoPairing }" />{{ view.subtitleAutoPairing ? 'AI 配对中' : 'AI 配对' }}
            </button>
            <button class="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium border transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="view.subtitleInspectorBusy || !view.subtitleInspectorAudioFiles.length || !view.subtitleInspectorSubtitleFiles.length" title="不用 AI，按文件名、轨道号和规范化标题生成规则草稿。" @click="view.buildRuleSubtitlePairs">
              <Wand2 :size="12" class="text-emerald-500" />规则预配对
            </button>
            <button :class="['inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium border transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] active:scale-95', view.subtitleSequenceMode ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300']" @click="view.setSubtitleSequenceMode(!view.subtitleSequenceMode)">
              <MousePointerClick :size="12" :class="view.subtitleSequenceMode ? 'text-slate-300' : 'text-blue-500'" />{{ view.subtitleSequenceMode ? '退出顺序点选' : '顺序点选配对' }}
            </button>
            <button class="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-700 transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="view.subtitleSequenceMode ? !view.canBuildSequenceSubtitlePairs : !view.filteredSubtitleInspectorAudioFiles.length || !view.filteredSubtitleInspectorSubtitleFiles.length" @click="view.buildSequenceOrOrderedSubtitlePairs">
              <ListOrdered :size="12" class="text-amber-500" />{{ view.subtitleSequenceMode ? '生成顺序预配对' : '按当前列表预配对' }}
            </button>
            <button class="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-semibold border border-slate-900 bg-slate-900 text-white transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:bg-slate-800 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:scale-100" :disabled="!view.subtitleManualPairs.length" :title="!view.subtitleManualPairs.length ? '请先在中间区域生成或添加至少一组配对，再执行应用。' : ''" @click="view.applySubtitleManualPairs">
              <CheckCircle2 :size="12" :class="{ 'is-spinning': view.subtitlePairApplying }" />{{ view.subtitleManualApplyLabel || '一键应用同名' }}
            </button>
          </div>
        </div>

        <div v-if="view.activeSubtitleInspectTask?.manual_match_completed || view.subtitleInspectorInfo.manualMatchCompleted" class="flex items-center gap-2 px-4 py-2.5 rounded-[10px] border border-slate-200 bg-slate-50 text-[12.5px] text-slate-700">

          <CheckCircle2 :size="14" :stroke-width="2.2" class="text-emerald-500 flex-shrink-0" />
          <span>已匹配完成，已应用 {{ view.activeSubtitleInspectTask?.manual_match_applied_pairs || view.subtitleInspectorInfo.manualMatchAppliedPairs || 0 }} 组配对。若还要调整，可以继续重新筛选后再次应用。</span>
        </div>

        <div v-if="view.subtitleInspectorInfo.subtitleLoadError" class="flex items-start gap-2 px-4 py-2.5 rounded-[10px] border border-rose-200 bg-rose-50 text-[12.5px] text-rose-800">
          <AlertTriangle :size="14" :stroke-width="2.2" class="mt-0.5 flex-shrink-0 text-rose-500" />
          <span>字幕工作台目录读取失败：{{ view.subtitleInspectorInfo.subtitleLoadError }}</span>
        </div>

        <div v-if="view.subtitleInspectorInfo.audioLoadError" class="flex items-start gap-2 px-4 py-2.5 rounded-[10px] border border-amber-200 bg-amber-50 text-[12.5px] text-amber-800">
          <AlertTriangle :size="14" :stroke-width="2.2" class="mt-0.5 flex-shrink-0 text-amber-500" />
          <span>原音频目录读取失败：{{ view.subtitleInspectorInfo.audioLoadError }}。字幕目录已保留，可先检查任务写入目录或重新选择目标目录。</span>
        </div>

        <div class="subtitle-pairing-grid-wrap flex min-h-0 flex-1 pb-1">
          <div class="subtitle-pairing-grid">
            <div class="flex flex-col rounded-[13px] border border-slate-200 bg-white overflow-hidden">
            <div class="flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-100 bg-slate-50/60">
              <div class="flex items-center gap-1.5 text-[12px] font-semibold text-slate-700"><Music :size="12" :stroke-width="2.2" class="text-sky-500" />原音频目录<span class="text-[11px] font-normal text-slate-400">{{ view.filteredSubtitleInspectorAudioFiles.length }} 项</span></div>
              <div class="inline-flex gap-0.5 p-0.5 rounded-lg bg-slate-100">
                <button v-for="mode in ['all','paired','unpaired']" :key="mode" type="button" class="px-1.5 py-0.5 rounded-md text-[10.5px] font-medium transition-all duration-150" :class="view.subtitleAudioFilterMode === mode ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'" @click="view.setSubtitleAudioFilterMode(mode)">{{ {all:'全部',paired:'已配对',unpaired:'未配对'}[mode] }}</button>
              </div>
            </div>
            <div class="px-2 pt-2"><input :value="view.subtitleInspectorAudioSearch" class="w-full h-7 px-2 rounded-lg bg-slate-50 border border-slate-200 text-[11.5px] placeholder-slate-400 outline-none focus:bg-white focus:border-slate-400 transition-all duration-150" placeholder="搜索音频名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorAudioSearch($event.target.value)" /></div>
            <div class="flex-1 overflow-y-auto p-2 flex flex-col gap-0.5 min-h-[200px] max-h-[340px]">
              <button v-for="audio in view.filteredSubtitleInspectorAudioFiles" :key="audio.path" type="button" class="subtitle-pairing-row subtitle-pairing-audio-row group/sequence-row w-full flex flex-col gap-0.5 px-2.5 py-2 rounded-[10px] border text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01] active:scale-[0.97]" :class="[view.getSubtitleSequenceIndex('audio', audio.path) ? 'subtitle-pairing-row-sequence' : view.subtitleMatchSelection.audioPath === audio.path ? 'subtitle-pairing-row-selected' : view.isAudioPaired(audio.path) ? 'subtitle-pairing-row-paired' : 'subtitle-pairing-row-idle', view.isAudioSuspicious(audio.path) ? 'subtitle-pairing-row-suspicious' : '']" @click="view.selectSubtitleAudio(audio)">

                <div class="flex items-center gap-1 flex-wrap">
                  <span v-if="view.isAudioPaired(audio.path)" class="subtitle-pairing-row-chip subtitle-pairing-row-chip-paired text-[9.5px] font-semibold">已配对</span>
                  <span v-if="view.isAudioSuspicious(audio.path)" class="subtitle-pairing-row-chip subtitle-pairing-row-chip-warning text-[9.5px] font-semibold">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('audio', audio.path)" class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-blue-600 px-1.5 text-[10px] font-black text-white shadow-[0_4px_12px_rgba(37,99,235,0.35)] ring-2 ring-white">#{{ view.getSubtitleSequenceIndex('audio', audio.path) }}</span>

                </div>
                <div class="subtitle-pairing-row-name text-[11.5px] font-semibold truncate transition-colors duration-300">{{ formatSubtitleItemName(audio) }}</div>
                <div class="subtitle-pairing-row-path text-[10px] truncate">{{ audio.relative_path || audio.name }}</div>
              </button>
            </div>
          </div>

          <div class="subtitle-pair-results-panel flex flex-col rounded-[13px] border border-slate-200 bg-white overflow-hidden">
            <div class="subtitle-pair-results-header flex items-center justify-between gap-1 px-3 py-2 border-b border-slate-100 bg-slate-50/60">
              <div class="subtitle-pair-results-title flex items-center gap-1.5 text-[12px] font-semibold text-slate-700"><Link2 :size="12" :stroke-width="2.2" class="text-blue-500" />配对结果</div>
              <div class="flex items-center gap-0.5">
                <button type="button" class="subtitle-pair-clear-action px-1.5 py-1 rounded-lg text-[10.5px] font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed" :disabled="view.subtitleInspectorBusy || (!view.subtitleSequenceSelection.audioPaths.length && !view.subtitleSequenceSelection.subtitlePaths.length)" @click="view.clearSubtitleSequenceSelection">清空顺序</button>
                <button type="button" class="subtitle-pair-clear-action px-1.5 py-1 rounded-lg text-[10.5px] font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed" :disabled="view.subtitleInspectorBusy || !view.subtitleManualPairs.length" @click="view.clearSubtitleManualPairs">清空配对</button>
              </div>
            </div>
            <div class="px-2 pt-2">
              <button type="button" class="subtitle-pair-add-button w-full h-7 inline-flex items-center justify-center gap-1 rounded-lg text-[11.5px] font-semibold border transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed" :class="view.canAddSubtitleManualPair && !view.subtitleInspectorBusy ? 'is-ready' : 'is-disabled'" :disabled="!view.canAddSubtitleManualPair || view.subtitleInspectorBusy" :title="!view.canAddSubtitleManualPair ? '请先在左侧选一条音频，再在右侧选一条字幕，然后点此加入配对。' : ''" @click="view.addSubtitleManualPair?.()">加入手动配对</button>
            </div>
            <div class="flex-1 overflow-y-auto p-2 flex flex-col gap-1.5 min-h-[200px] max-h-[340px]">
              <div v-if="!view.subtitleManualPairs.length" class="subtitle-pair-empty flex flex-col items-center justify-center py-6 gap-1 text-center"><div class="text-[11.5px] font-medium text-slate-500">还没有生成配对结果</div><div class="text-[10.5px] text-slate-400">可以先点"AI 配对"或"规则预配对"</div></div>
              <button v-for="(pair, index) in view.subtitleManualPairs" :key="pair.id" type="button" class="subtitle-pair-card w-full flex flex-col gap-1.5 p-2 rounded-[9px] border text-left transition-all duration-150" :class="[view.subtitleSelectedManualPairId === pair.id ? 'subtitle-pair-card-selected' : '', pair.confidenceLevel === 'low' ? 'subtitle-pair-card-low-confidence' : '']" @click="view.setSubtitleSelectedManualPairId(pair.id)">

                <div class="flex items-center justify-between gap-1">
                  <div class="flex items-center gap-1">
                    <span class="subtitle-pair-confidence text-[9.5px] font-semibold" :class="pair.confidenceLevel === 'low' ? 'subtitle-pair-confidence-low' : ''">{{ view.getSubtitlePairConfidenceLabel(pair.confidenceLevel) }}</span>

                    <span class="subtitle-pair-index text-[9.5px] text-slate-400">配对 {{ index + 1 }}</span>
                  </div>
                  <button type="button" class="subtitle-pair-remove text-[10px] font-semibold px-1" :disabled="view.subtitleInspectorBusy" @click.stop="view.removeSubtitleManualPair(pair.id)">移除</button>
                </div>
                <div class="subtitle-pair-reason text-[10px] text-slate-400 truncate">{{ pair.matchReason || '手动配对' }}</div>
                <div class="flex items-center gap-1 min-w-0">
                  <div class="flex-1 min-w-0"><div class="flex items-center gap-1 min-w-0"><Music v-if="getSubtitlePairRenamePreview(pair).kind === 'audio'" :size="9" class="subtitle-pair-audio-icon text-sky-500 flex-shrink-0" /><FileText v-else :size="9" class="subtitle-pair-subtitle-icon text-violet-500 flex-shrink-0" /><span class="subtitle-pair-before text-[10px] font-medium text-slate-600 truncate" :title="getSubtitlePairRenamePreview(pair).before">{{ getSubtitlePairRenamePreview(pair).before }}</span></div></div>
                  <ArrowRight :size="10" class="subtitle-pair-arrow text-slate-400 flex-shrink-0" />
                  <div class="flex-1 min-w-0"><div class="flex items-center gap-1 min-w-0"><Music v-if="getSubtitlePairRenamePreview(pair).kind === 'audio'" :size="9" class="subtitle-pair-audio-icon text-sky-500 flex-shrink-0" /><FileText v-else :size="9" class="subtitle-pair-subtitle-icon text-violet-500 flex-shrink-0" /><span class="subtitle-pair-after text-[10px] font-medium text-emerald-700 truncate" :title="getSubtitlePairRenamePreview(pair).after">{{ getSubtitlePairRenamePreview(pair).after }}</span></div></div>
                </div>
              </button>
            </div>
          </div>

          <div class="flex flex-col rounded-[13px] border border-slate-200 bg-white overflow-hidden">
            <div class="flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-100 bg-slate-50/60">
              <div class="flex items-center gap-1.5 text-[12px] font-semibold text-slate-700"><FileText :size="12" :stroke-width="2.2" class="text-violet-500" />字幕目录<span class="text-[11px] font-normal text-slate-400">{{ view.filteredSubtitleInspectorSubtitleFiles.length }} 项</span></div>
              <div class="inline-flex gap-0.5 p-0.5 rounded-lg bg-slate-100">
                <button v-for="mode in ['all','paired','unpaired']" :key="mode" type="button" class="px-1.5 py-0.5 rounded-md text-[10.5px] font-medium transition-all duration-150" :class="view.subtitleSubtitleFilterMode === mode ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'" @click="view.setSubtitleSubtitleFilterMode(mode)">{{ {all:'全部',paired:'已配对',unpaired:'未配对'}[mode] }}</button>
              </div>
            </div>
            <div class="px-2 pt-2"><input :value="view.subtitleInspectorSubtitleSearch" class="w-full h-7 px-2 rounded-lg bg-slate-50 border border-slate-200 text-[11.5px] placeholder-slate-400 outline-none focus:bg-white focus:border-slate-400 transition-all duration-150" placeholder="搜索字幕名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorSubtitleSearch($event.target.value)" /></div>
            <div class="flex-1 overflow-y-auto p-2 flex flex-col gap-0.5 min-h-[200px] max-h-[340px]">
              <button v-for="subtitle in view.filteredSubtitleInspectorSubtitleFiles" :key="subtitle.path" type="button" class="subtitle-pairing-row subtitle-pairing-subtitle-row group/sequence-row w-full flex flex-col gap-0.5 px-2.5 py-2 rounded-[10px] border text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.01] active:scale-[0.97]" :class="[view.getSubtitleSequenceIndex('subtitle', subtitle.path) ? 'subtitle-pairing-row-sequence' : view.subtitleMatchSelection.subtitlePath === subtitle.path ? 'subtitle-pairing-row-selected' : view.isSubtitlePaired(subtitle.path) ? 'subtitle-pairing-row-paired' : 'subtitle-pairing-row-idle', view.isSubtitleSuspicious(subtitle.path) ? 'subtitle-pairing-row-suspicious' : '']" @click="view.selectSubtitleFile(subtitle)">

                <div class="flex items-center gap-1 flex-wrap">
                  <span v-if="view.isSubtitlePaired(subtitle.path)" class="subtitle-pairing-row-chip subtitle-pairing-row-chip-paired text-[9.5px] font-semibold">已配对</span>
                  <span v-if="view.isSubtitleSuspicious(subtitle.path)" class="subtitle-pairing-row-chip subtitle-pairing-row-chip-warning text-[9.5px] font-semibold">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('subtitle', subtitle.path)" class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-violet-600 px-1.5 text-[10px] font-black text-white shadow-[0_4px_12px_rgba(124,58,237,0.35)] ring-2 ring-white">#{{ view.getSubtitleSequenceIndex('subtitle', subtitle.path) }}</span>

                </div>
                <div class="subtitle-pairing-row-name text-[11.5px] font-semibold truncate transition-colors duration-300">{{ formatSubtitleItemName(subtitle) }}</div>
                <div class="subtitle-pairing-row-path text-[10px] truncate">{{ subtitle.relative_path || subtitle.name }}</div>
              </button>
            </div>
          </div>
        </div>
      </div>
      </div>

      <div v-if="showPairing && view.activeSubtitleTaskProgressLogs?.length" class="flex flex-col gap-2 p-3 rounded-[13px] bg-slate-50 border border-slate-200">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">过程日志</span>
          <span class="text-[11px] text-slate-400">{{ view.activeSubtitleTaskProgressLogs.length }} 条</span>
        </div>
        <div class="flex flex-col gap-px">
          <div v-for="(entry, idx) in view.activeSubtitleTaskProgressLogs" :key="`pair-log-${idx}`" class="flex items-start gap-2 py-1 border-b border-slate-100 last:border-b-0">
            <span class="flex-shrink-0 text-[10px] text-slate-400 tabular-nums mt-0.5">{{ view.formatProgressLogTime(entry.time) }}</span>
            <span class="flex-shrink-0 inline-flex items-center px-1.5 py-px rounded text-[10px] font-semibold" :class="{ 'bg-emerald-100 text-emerald-700': entry.level === 'success', 'bg-rose-100 text-rose-700': entry.level === 'error', 'bg-amber-100 text-amber-700': entry.level === 'warning', 'bg-slate-100 text-slate-600': !entry.level || entry.level === 'info' }">{{ view.getProgressLogLevelLabel(entry.level) }}</span>
            <span class="text-[11.5px] text-slate-700 leading-relaxed">{{ entry.message }}</span>
          </div>
        </div>
      </div>

      <div v-if="showTree" class="grid gap-3">
        <div class="subtitle-tree-search-shell group/search flex items-center gap-2 rounded-[12px] border border-slate-200 bg-slate-50/60 px-3 py-2 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] focus-within:border-sky-400 focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(56,189,248,0.15)] hover:border-slate-300">
          <Search :size="14" :stroke-width="2.2" class="shrink-0 text-slate-400 transition-all duration-300 group-focus-within/search:rotate-[-8deg] group-focus-within/search:scale-110 group-focus-within/search:text-sky-600" />
          <input
            :value="view.subtitleInspectorSearch"
            type="text"
            placeholder="搜索字幕文件名或路径..."
            :disabled="view.subtitleInspectorBusy"
            class="subtitle-tree-search-input min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] font-medium text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0 disabled:cursor-not-allowed disabled:opacity-60"
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
          <div v-if="view.subtitleInspectorSelectedRows.length" class="subtitle-tree-selection-bar flex items-center justify-between gap-3 rounded-[12px] border border-indigo-200 bg-gradient-to-br from-indigo-50/70 via-white to-white px-3.5 py-2.5 shadow-[0_2px_8px_rgba(79,70,229,0.05)]">
            <div class="flex items-center gap-2">
              <span class="subtitle-tree-selection-icon inline-flex h-6 w-6 items-center justify-center rounded-[7px] bg-indigo-500 text-white">
                <CheckSquare :size="12" :stroke-width="2.4" />
              </span>
              <span class="subtitle-tree-selection-count text-[12.5px] font-semibold text-indigo-700">已选 {{ view.subtitleInspectorSelectedRows.length }} 项</span>
              <span class="subtitle-tree-selection-help hidden text-[11px] text-indigo-600/70 md:inline">支持 Ctrl+A · Ctrl/Cmd 点击 · Shift 范围</span>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                type="button"
                class="subtitle-tree-selection-danger group/btn inline-flex items-center gap-1 rounded-[8px] border border-rose-300 bg-white px-3 py-1.5 text-[12px] font-medium text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-rose-500 hover:bg-rose-500 hover:text-white hover:shadow-[0_4px_12px_rgba(244,63,94,0.25)] active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
                :disabled="view.subtitleInspectorBusy && !view.subtitleInspectorDeleting"
                @click="view.batchDeleteSubtitleTreeEntries"
              >
                <Trash2 :size="12" :stroke-width="2.2" :class="['transition-transform duration-300 group-hover/btn:rotate-[-8deg] group-hover/btn:scale-110', view.subtitleInspectorDeleting ? 'is-spinning' : '']" />
                <span>删除选中</span>
              </button>
              <button
                type="button"
                class="subtitle-tree-selection-secondary group/btn inline-flex items-center gap-1 rounded-[8px] border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40"
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
              class="subtitle-tree-row group/row grid cursor-pointer grid-cols-[40px_minmax(0,1fr)_96px_156px_112px] items-center gap-2 border-b border-slate-50 px-3 py-2 transition-all duration-200 ease-out last:border-b-0"
              :class="[
                row.type === 'dir' ? 'subtitle-tree-row-dir' : '',
                view.subtitleInspectorSelectedIds.has(row.id) ? 'subtitle-tree-row-selected' : ''
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
                    class="subtitle-tree-row-icon inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/row:rotate-[6deg] group-hover/row:scale-110"
                    :class="row.type === 'dir' ? 'bg-amber-50 text-amber-600 ring-1 ring-inset ring-amber-100' : ''"
                    :style="row.type === 'file' ? subtitleRowChipStyle(row) : null"
                  >
                    <FolderClosed v-if="row.type === 'dir' && !view.subtitleInspectorExpandedIds.has(row.id)" :size="12" :stroke-width="2.2" />
                    <FolderOpen v-else-if="row.type === 'dir'" :size="12" :stroke-width="2.2" />
                    <component v-else :is="libraryEntryIconFor(row)" :size="12" :stroke-width="2.2" />
                  </span>
                  <span class="subtitle-tree-row-name truncate text-[13px] font-medium text-slate-900" :title="row.name">{{ row.name }}</span>
                </div>
              </div>
              <div class="subtitle-tree-row-size text-[12px] font-medium tabular-nums text-slate-600">{{ view.formatFileSize(row.size) }}</div>
              <div class="subtitle-tree-row-time text-[12px] tabular-nums text-slate-500">{{ view.formatDate(row.modified_time) }}</div>
              <div class="flex w-[60px] items-center justify-center gap-1 justify-self-end" @click.stop>
                <button
                  v-if="row.type === 'file'"
                  type="button"
                  class="group/act inline-flex h-7 w-7 items-center justify-center rounded-[7px] border border-sky-100 bg-white text-sky-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.08] hover:border-sky-300 hover:bg-white active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-40"
                  :disabled="view.subtitleInspectorBusy"
                  title="重命名"
                  @click="view.openSubtitleRenameDialog(row)"
                >
                  <Pencil :size="12" :stroke-width="2.2" class="transition-transform duration-300 group-hover/act:rotate-[-12deg]" />
                </button>
                <button
                  type="button"
                  class="group/act inline-flex h-7 w-7 items-center justify-center rounded-[7px] border border-rose-100 bg-white text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.08] hover:border-rose-300 hover:bg-white active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-40"
                  :disabled="view.subtitleInspectorBusy"
                  title="删除"
                  @click="view.deleteSubtitleTreeEntry(row)"
                >
                  <Trash2 :size="12" :stroke-width="2.2" class="transition-transform duration-300 group-hover/act:rotate-[-8deg] group-hover/act:scale-110" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
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
  AlertTriangle,
  Music,
  FileText,
  FileSearch,
  Database,
  CircleX,
  Bot,
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
import { libraryEntryIconFor, libraryEntryMetaFor } from './_libraryFileKind'

// chip 颜色：拿 helper meta 的 color，凑出“文字原色 + 10% 深度底 + 22% 深度 inset ring”。
// hex 说明是 #rrggbb 三节映射，其他格式充当备选。
function hexToRgba (hex, alpha) {
  const value = String(hex || '').replace('#', '')
  if (value.length !== 6) return `rgba(15,23,42,${alpha})`
  const r = parseInt(value.substring(0, 2), 16)
  const g = parseInt(value.substring(2, 4), 16)
  const b = parseInt(value.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function subtitleRowChipStyle (row) {
  const meta = libraryEntryMetaFor(row)
  const color = meta.color
  return {
    color,
    backgroundColor: hexToRgba(color, 0.10),
    boxShadow: `inset 0 0 0 1px ${hexToRgba(color, 0.22)}`,
  }
}

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

const emptySet = new Set()
const noop = () => {}

function arrayOrEmpty(value) {
  return Array.isArray(value) ? value : []
}

function setOrEmpty(value) {
  return value instanceof Set ? value : emptySet
}

function objectOrEmpty(value) {
  return value && typeof value === 'object' ? value : {}
}

function normalizeSequenceSelection(value) {
  const selection = objectOrEmpty(value)
  return {
    audioPaths: arrayOrEmpty(selection.audioPaths),
    subtitlePaths: arrayOrEmpty(selection.subtitlePaths)
  }
}

function normalizeMatchSelection(value) {
  const selection = objectOrEmpty(value)
  return {
    audioPath: selection.audioPath || '',
    subtitlePath: selection.subtitlePath || ''
  }
}

const viewDefaults = {
  subtitleInspectorInfo: {},
  subtitleInspectorBusy: false,
  subtitleInspectorLoading: false,
  subtitleInspectorDeleting: false,
  subtitleInspectorHasDirectories: false,
  subtitleInspectorAudioFiles: [],
  subtitleInspectorSubtitleFiles: [],
  subtitleInspectorFlatTree: [],
  subtitleInspectorSelectedRows: [],
  subtitleInspectorSelectedIds: emptySet,
  subtitleInspectorExpandedIds: emptySet,
  subtitleInspectorSearch: '',
  subtitleInspectorAudioSearch: '',
  subtitleInspectorSubtitleSearch: '',
  subtitleInspectorAllSelected: false,
  subtitleInspectorSomeSelected: false,
  inspectableSubtitleTasks: [],
  activeSubtitleTask: null,
  subtitleBackgroundActiveTask: null,
  activeSubtitleInspectTask: null,
  subtitleSequenceMode: false,
  subtitleSequenceSelection: { audioPaths: [], subtitlePaths: [] },
  subtitleManualPairs: [],
  subtitleSelectedManualPairId: '',
  subtitlePairApplying: false,
  subtitleAutoPairing: false,
  subtitleManualApplyLabel: '',
  subtitleAudioFilterMode: 'all',
  subtitleSubtitleFilterMode: 'all',
  subtitleMatchSelection: { audioPath: '', subtitlePath: '' },
  filteredSubtitleInspectorAudioFiles: [],
  filteredSubtitleInspectorSubtitleFiles: [],
  canBuildSequenceSubtitlePairs: false,
  canAddSubtitleManualPair: false,
  activeSubtitleTaskProgressLogs: [],
  subtitleCancelingId: '',
  subtitleTaskRerunId: '',
  subtitleNamingStrategy: 'audio',
  reloadSubtitleInspector: noop,
  expandSubtitleInspectorTree: noop,
  collapseSubtitleInspectorTree: noop,
  getTaskDisplayRJCode: () => '未知RJ',
  getTaskSourceRJCode: () => '',
  getFileName: value => String(value || '').split(/[\\/]/).pop(),
  formatFileSize: value => value || '0 B',
  formatDate: value => value || '-',
  canCancelRJSubtitleTask: () => false,
  cancelRJSubtitleTask: noop,
  canClearCurrentSubtitleTask: () => false,
  clearCurrentSubtitleTask: noop,
  canRerunSubtitleTask: () => false,
  rerunSubtitleTask: noop,
  buildAutoSubtitlePairs: noop,
  buildAISubtitlePairs: noop,
  buildRuleSubtitlePairs: noop,
  buildSequenceOrOrderedSubtitlePairs: noop,
  applySubtitleManualPairs: noop,
  setSubtitleSequenceMode: noop,
  setSubtitleAudioFilterMode: noop,
  setSubtitleSubtitleFilterMode: noop,
  setSubtitleInspectorAudioSearch: noop,
  setSubtitleInspectorSubtitleSearch: noop,
  setSubtitleInspectorSearch: noop,
  setSubtitleSelectedManualPairId: noop,
  isAudioPaired: () => false,
  isAudioSuspicious: () => false,
  getSubtitleSequenceIndex: () => 0,
  selectSubtitleAudio: noop,
  addSubtitleManualPair: noop,
  clearSubtitleSequenceSelection: noop,
  clearSubtitleManualPairs: noop,
  getSubtitlePairConfidenceLabel: value => value || '中',
  removeSubtitleManualPair: noop,
  isSubtitlePaired: () => false,
  isSubtitleSuspicious: () => false,
  selectSubtitleFile: noop,
  batchDeleteSubtitleTreeEntries: noop,
  clearSubtitleInspectorSelection: noop,
  toggleAllSubtitleInspectorRows: noop,
  handleSubtitleInspectorRowClick: noop,
  toggleSubtitleInspectorSelect: noop,
  toggleSubtitleInspectorExpand: noop,
  openSubtitleRenameDialog: noop,
  deleteSubtitleTreeEntry: noop,
}

const view = computed(() => {
  const merged = {
    ...viewDefaults,
    ...(props.ctx || {})
  }
  return {
    ...merged,
    subtitleInspectorInfo: objectOrEmpty(merged.subtitleInspectorInfo),
    subtitleInspectorAudioFiles: arrayOrEmpty(merged.subtitleInspectorAudioFiles),
    subtitleInspectorSubtitleFiles: arrayOrEmpty(merged.subtitleInspectorSubtitleFiles),
    subtitleInspectorFlatTree: arrayOrEmpty(merged.subtitleInspectorFlatTree),
    subtitleInspectorSelectedRows: arrayOrEmpty(merged.subtitleInspectorSelectedRows),
    inspectableSubtitleTasks: arrayOrEmpty(merged.inspectableSubtitleTasks),
    subtitleSequenceSelection: normalizeSequenceSelection(merged.subtitleSequenceSelection),
    subtitleManualPairs: arrayOrEmpty(merged.subtitleManualPairs),
    filteredSubtitleInspectorAudioFiles: arrayOrEmpty(merged.filteredSubtitleInspectorAudioFiles),
    filteredSubtitleInspectorSubtitleFiles: arrayOrEmpty(merged.filteredSubtitleInspectorSubtitleFiles),
    activeSubtitleTaskProgressLogs: arrayOrEmpty(merged.activeSubtitleTaskProgressLogs),
    subtitleInspectorSelectedIds: setOrEmpty(merged.subtitleInspectorSelectedIds),
    subtitleInspectorExpandedIds: setOrEmpty(merged.subtitleInspectorExpandedIds),
    subtitleMatchSelection: normalizeMatchSelection(merged.subtitleMatchSelection)
  }
})
const showPairing = computed(() => ['all', 'pairing'].includes(props.stageMode))
const showTree = computed(() => ['all', 'tree'].includes(props.stageMode))

function isAwaitingManualTask(task) {
  const status = String(task?.status || '').toLowerCase()
  return Boolean(
    task?.awaiting_manual_match ||
    ['waiting_manual', 'awaiting_manual_match', 'awaiting'].includes(status)
  )
}

function isRuntimePendingTask(task) {
  const status = String(task?.status || '').toLowerCase()
  if (!['pending', 'processing'].includes(status)) return false
  return !task?.manual_match_completed && !isAwaitingManualTask(task)
}

const activeTaskMissingSubtitleDir = computed(() => {
  const task = view.value.activeSubtitleInspectTask || view.value.activeSubtitleTask
  return Boolean(task && isAwaitingManualTask(task) && !view.value.subtitleInspectorInfo?.subtitleDir)
})

const pendingInProgressTask = computed(() => {
  const candidates = [view.value.activeSubtitleTask, view.value.subtitleBackgroundActiveTask]
  for (const task of candidates) {
    if (!task) continue
    if (isRuntimePendingTask(task)) return task
  }
  const tasks = Array.isArray(view.value.inspectableSubtitleTasks) ? view.value.inspectableSubtitleTasks : []
  return tasks.find(task => isRuntimePendingTask(task)) || null
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
.subtitle-inspector-workbench-root :is(button, [role="button"], input[type="checkbox"]):not(:disabled) {
  cursor: pointer;
}

.subtitle-inspector-workbench-root :is(button, input):disabled {
  cursor: not-allowed;
}

.subtitle-inspector-workbench-root :is(button, input):focus,
.subtitle-inspector-workbench-root :is(button, input):focus-visible,
.subtitle-inspector-workbench-root :focus-within {
  outline: none !important;
  box-shadow: none !important;
}

.subtitle-tree-row-selected {
  background-color: rgba(238, 242, 255, 0.78);
  border-color: #c7d2fe;
  box-shadow: inset 0 0 0 1px rgba(199, 210, 254, 0.72);
}

.subtitle-tree-row:hover {
  background-color: rgba(248, 250, 252, 0.62);
}

.subtitle-tree-row-dir {
  background-color: rgba(248, 250, 252, 0.36);
}

.subtitle-pair-results-panel {
  background: #ffffff;
}

.subtitle-pairing-row {
  position: relative;
  overflow: hidden;
  background: rgba(248, 250, 252, 0.72);
  border-color: rgba(226, 232, 240, 0.92);
  color: #0f172a;
}

.subtitle-pairing-row-idle:hover {
  background: #f8fbff;
  border-color: #93c5fd;
}

.subtitle-pairing-subtitle-row.subtitle-pairing-row-idle:hover {
  background: #fbf7ff;
  border-color: #c4b5fd;
}

.subtitle-pairing-row-paired {
  background: #f8fafc;
  border-color: #cbd5e1;
  box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.42);
}

.subtitle-pairing-row-selected {
  background: #eff6ff;
  border-color: #60a5fa;
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.38),
    0 8px 24px rgba(37, 99, 235, 0.16);
}

.subtitle-pairing-subtitle-row.subtitle-pairing-row-selected {
  background: #f5f3ff;
  border-color: #a78bfa;
  box-shadow:
    inset 0 0 0 1px rgba(167, 139, 250, 0.38),
    0 8px 24px rgba(124, 58, 237, 0.16);
}

.subtitle-pairing-row-sequence {
  background: #eef6ff;
  border-color: #38bdf8;
  box-shadow:
    inset 0 0 0 1px rgba(14, 165, 233, 0.32),
    0 8px 24px rgba(14, 165, 233, 0.18);
}

.subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence {
  background: #f6f1ff;
  border-color: #a78bfa;
  box-shadow:
    inset 0 0 0 1px rgba(139, 92, 246, 0.32),
    0 8px 24px rgba(139, 92, 246, 0.18);
}

.subtitle-pairing-row-suspicious {
  border-color: #f59e0b;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.18);
}

.subtitle-pairing-row-name {
  color: #1e293b;
}

.subtitle-pairing-audio-row:hover .subtitle-pairing-row-name,
.subtitle-pairing-audio-row.subtitle-pairing-row-selected .subtitle-pairing-row-name,
.subtitle-pairing-audio-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name {
  color: #1d4ed8;
}

.subtitle-pairing-subtitle-row:hover .subtitle-pairing-row-name,
.subtitle-pairing-subtitle-row.subtitle-pairing-row-selected .subtitle-pairing-row-name,
.subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name {
  color: #6d28d9;
}

.subtitle-pairing-row-path {
  color: #64748b;
}

.subtitle-pairing-row-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 5px;
  padding: 1px 4px;
}

.subtitle-pairing-row-chip-paired {
  background: rgba(226, 232, 240, 0.82);
  color: #475569;
}

.subtitle-pairing-row-chip-warning {
  background: rgba(254, 243, 199, 0.9);
  color: #b45309;
}

.subtitle-pair-add-button.is-ready {
  background: #f8fafc;
  border-color: #38bdf8;
  color: #0369a1;
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.16);
}

.subtitle-pair-add-button.is-ready:hover:not(:disabled) {
  background: #ecfeff;
  border-color: #0ea5e9;
  color: #075985;
}

.subtitle-pair-add-button.is-disabled {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #94a3b8;
}

.subtitle-pair-card {
  background: rgba(248, 250, 252, 0.72);
  border-color: #e2e8f0;
}

.subtitle-pair-card:hover {
  background: #f8fbff;
  border-color: #93c5fd;
  transform: translateY(-1px);
}

.subtitle-pair-card-selected {
  background: #eff6ff;
  border-color: #93c5fd;
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.42);
}

.subtitle-pair-card-low-confidence {
  background: #fffbeb;
  border-color: #fcd34d;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.18);
}

.subtitle-pair-card-selected.subtitle-pair-card-low-confidence {
  background: #fff7ed;
  border-color: #f59e0b;
}

.subtitle-pair-confidence {
  color: #64748b;
}

.subtitle-pair-confidence-low {
  color: #d97706;
}

.subtitle-pair-remove {
  border-radius: 6px;
  background: transparent;
  color: #e11d48;
}

.subtitle-pair-remove:hover:not(:disabled) {
  background: #fff1f2;
  color: #be123c;
}

.subtitle-inspector-workbench-root :deep(.bg-slate-50),
.subtitle-inspector-workbench-root :deep(.bg-slate-50\/30),
.subtitle-inspector-workbench-root :deep(.bg-slate-50\/40),
.subtitle-inspector-workbench-root :deep(.bg-slate-50\/60),
.subtitle-inspector-workbench-root :deep(.bg-slate-100),
.subtitle-inspector-workbench-root :deep(.bg-white\/80) {
  background-color: #ffffff !important;
  background-image: none !important;
}

.subtitle-inspector-workbench-root :deep(.bg-slate-900) {
  background-color: #ffffff !important;
  color: #0f172a !important;
  border: 1px solid #e2e8f0 !important;
}

.subtitle-inspector-workbench-root :deep(.bg-gradient-to-r),
.subtitle-inspector-workbench-root :deep(.bg-gradient-to-br),
.subtitle-inspector-workbench-root :deep(.bg-gradient-to-b) {
  background-image: none !important;
  background-color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep([class*="bg-white"]),
:global(html.dark) .subtitle-inspector-workbench-root :deep([class*="bg-white"]) {
  background-color: #242529 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(246, 246, 248, 0.88) !important;
}

:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/30),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/40),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/60),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-100),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/30),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/40),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-50\/60),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-100) {
  background-color: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(218, 218, 224, 0.72) !important;
}

:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-slate-900),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-slate-900) {
  background-color: #020617 !important;
  color: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-search-input),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-search-input) {
  background: transparent !important;
  background-color: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
  outline: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-search-input:focus),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-search-input:focus) {
  background: transparent !important;
  background-color: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-bar),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-bar) {
  background: #202127 !important;
  background-image: none !important;
  border-color: rgba(139, 92, 246, 0.34) !important;
  color: rgba(244, 244, 245, 0.92) !important;
  box-shadow: inset 3px 0 0 rgba(139, 92, 246, 0.82) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-icon),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-icon) {
  background: #7c3aed !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-count),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-count) {
  color: #c4b5fd !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-help),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-help) {
  color: rgba(196, 181, 253, 0.68) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root :is(.subtitle-tree-selection-secondary, .subtitle-tree-selection-danger)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root :is(.subtitle-tree-selection-secondary, .subtitle-tree-selection-danger)) {
  background: #28292f !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-danger),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-danger) {
  color: #fecdd3 !important;
  border-color: rgba(244, 63, 94, 0.32) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-danger:hover:not(:disabled)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-danger:hover:not(:disabled)) {
  background: #9f2537 !important;
  border-color: rgba(254, 205, 211, 0.42) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-secondary:hover:not(:disabled)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-selection-secondary:hover:not(:disabled)) {
  background: #32333a !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row) {
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-dir),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-dir) {
  background: #242529 !important;
  background-color: #242529 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row:hover),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row:hover) {
  background: #303136 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected:hover),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected:hover) {
  background: #252333 !important;
  background-color: #252333 !important;
  background-image: none !important;
  border-color: rgba(167, 139, 250, 0.28) !important;
  color: #f8fafc !important;
  box-shadow:
    inset 3px 0 0 rgba(139, 92, 246, 0.92),
    inset 0 0 0 1px rgba(167, 139, 250, 0.18) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected .subtitle-tree-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected .subtitle-tree-row-name) {
  color: #f8fafc !important;
  font-weight: 650 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected :is(.subtitle-tree-row-size, .subtitle-tree-row-time)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected :is(.subtitle-tree-row-size, .subtitle-tree-row-time)) {
  color: rgba(226, 232, 240, 0.68) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected .subtitle-tree-row-icon),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row-selected .subtitle-tree-row-icon) {
  background: rgba(139, 92, 246, 0.22) !important;
  color: #c4b5fd !important;
  box-shadow: inset 0 0 0 1px rgba(167, 139, 250, 0.28) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row input[type="checkbox"]),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-tree-row input[type="checkbox"]) {
  accent-color: #8b5cf6;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row) {
  background: #23252b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  color: rgba(226, 232, 240, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row:hover),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row:hover) {
  background: #282c34 !important;
  border-color: rgba(56, 189, 248, 0.3) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row:hover),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row:hover) {
  border-color: rgba(167, 139, 250, 0.36) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-paired),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-paired) {
  background: #26282e !important;
  border-color: rgba(148, 163, 184, 0.34) !important;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.12) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-selected),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-selected) {
  background: #172a3d !important;
  border-color: rgba(56, 189, 248, 0.72) !important;
  box-shadow:
    inset 0 0 0 1px rgba(125, 211, 252, 0.18),
    0 0 0 2px rgba(56, 189, 248, 0.1) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-selected),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-selected) {
  background: #27213a !important;
  border-color: rgba(167, 139, 250, 0.78) !important;
  box-shadow:
    inset 0 0 0 1px rgba(196, 181, 253, 0.18),
    0 0 0 2px rgba(167, 139, 250, 0.1) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-sequence),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-sequence) {
  background: #112c3a !important;
  border-color: rgba(14, 165, 233, 0.82) !important;
  box-shadow:
    inset 0 0 0 1px rgba(56, 189, 248, 0.2),
    0 0 0 2px rgba(14, 165, 233, 0.11) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence) {
  background: #2a213d !important;
  border-color: rgba(139, 92, 246, 0.82) !important;
  box-shadow:
    inset 0 0 0 1px rgba(167, 139, 250, 0.2),
    0 0 0 2px rgba(139, 92, 246, 0.11) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-suspicious),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-suspicious) {
  background: #2b271f !important;
  border-color: rgba(245, 158, 11, 0.56) !important;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.16) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-name) {
  color: rgba(244, 244, 245, 0.94) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row:hover .subtitle-pairing-row-name),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-selected .subtitle-pairing-row-name),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row:hover .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-selected .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-audio-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name) {
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row:hover .subtitle-pairing-row-name),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-selected .subtitle-pairing-row-name),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row:hover .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-selected .subtitle-pairing-row-name),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-subtitle-row.subtitle-pairing-row-sequence .subtitle-pairing-row-name) {
  color: #c4b5fd !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-path),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-path) {
  color: rgba(203, 213, 225, 0.62) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-chip-paired),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-chip-paired) {
  background: rgba(71, 85, 105, 0.42) !important;
  color: rgba(226, 232, 240, 0.86) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-chip-warning),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pairing-row-chip-warning) {
  background: rgba(245, 158, 11, 0.2) !important;
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-panel),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-panel) {
  background: #202127 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.92) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-header),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-header) {
  background: #1b1c22 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-title),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-results-title) {
  color: #f8fafc !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-clear-action),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-clear-action) {
  background: transparent !important;
  color: rgba(203, 213, 225, 0.7) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-clear-action:hover:not(:disabled)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-clear-action:hover:not(:disabled)) {
  background: #2d2f36 !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-ready),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-ready) {
  background: #242832 !important;
  background-image: none !important;
  border-color: rgba(56, 189, 248, 0.42) !important;
  color: #7dd3fc !important;
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.1) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-ready:hover:not(:disabled)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-ready:hover:not(:disabled)) {
  background: #26313c !important;
  border-color: rgba(125, 211, 252, 0.58) !important;
  color: #bae6fd !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-disabled),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-add-button.is-disabled) {
  background: #242529 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  color: rgba(203, 213, 225, 0.48) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-empty > div:first-child),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-empty > div:first-child) {
  color: rgba(226, 232, 240, 0.78) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-empty > div:last-child),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-empty > div:last-child) {
  color: rgba(148, 163, 184, 0.82) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card) {
  background: #23252b !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  color: rgba(226, 232, 240, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card:hover),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card:hover) {
  background: #282c34 !important;
  border-color: rgba(56, 189, 248, 0.3) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-low-confidence),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-low-confidence) {
  background: #2b271f !important;
  background-image: none !important;
  border-color: rgba(245, 158, 11, 0.42) !important;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.14) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-selected),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-selected) {
  background: #202a3b !important;
  background-image: none !important;
  border-color: rgba(96, 165, 250, 0.5) !important;
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.18) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-selected.subtitle-pair-card-low-confidence),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-card-selected.subtitle-pair-card-low-confidence) {
  background: #2a2926 !important;
  border-color: rgba(251, 191, 36, 0.56) !important;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.18) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-confidence),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-confidence) {
  color: rgba(203, 213, 225, 0.82) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-confidence-low),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-confidence-low) {
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-index),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-index),
:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-reason),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-reason) {
  color: rgba(148, 163, 184, 0.82) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-before),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-before) {
  color: rgba(226, 232, 240, 0.78) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-after),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-after) {
  color: #5eead4 !important;
  font-weight: 650 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-arrow),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-arrow) {
  color: rgba(148, 163, 184, 0.68) !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-audio-icon),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-audio-icon) {
  color: #38bdf8 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-subtitle-icon),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-subtitle-icon) {
  color: #a78bfa !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-remove),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-remove) {
  border-radius: 6px !important;
  background: rgba(127, 29, 29, 0.18) !important;
  color: #fecdd3 !important;
}

:global(html.kikoerumanager-dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-remove:hover:not(:disabled)),
:global(html.dark :is(.subtitle-workbench-dialog, .subtitle-import-workbench-dialog) .subtitle-inspector-workbench-root .subtitle-pair-remove:hover:not(:disabled)) {
  background: #9f1239 !important;
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-r),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-br),
:global(html.kikoerumanager-dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-b),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-r),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-br),
:global(html.dark) .subtitle-inspector-workbench-root :deep(.bg-gradient-to-b) {
  background-color: #242529 !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-inspector-workbench-root :deep(.shadow-sm),
.subtitle-inspector-workbench-root :deep(.shadow),
.subtitle-inspector-workbench-root :deep(.shadow-md),
.subtitle-inspector-workbench-root :deep(.shadow-lg),
.subtitle-inspector-workbench-root :deep(.shadow-xl),
.subtitle-inspector-workbench-root :deep([class*="shadow-"]) {
  box-shadow: none !important;
}

.subtitle-inspector-workbench-root :deep(.ring-1),
.subtitle-inspector-workbench-root :deep(.ring-2),
.subtitle-inspector-workbench-root :deep([class*="ring-"]) {
  --tw-ring-offset-shadow: 0 0 #0000 !important;
  --tw-ring-shadow: 0 0 #0000 !important;
  box-shadow: none !important;
}

.subtitle-folder-mark {
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #0284c7;
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-folder-mark:hover {
  background: transparent;
  color: #0369a1;
  transform: translateY(-2px) scale(1.04);
}

.subtitle-folder-mark :deep(svg) {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-folder-mark:hover :deep(svg) {
  transform: rotate(-8deg) scale(1.12);
}

:global(html.kikoerumanager-dark) .subtitle-folder-mark,
:global(html.dark) .subtitle-folder-mark {
  background: transparent;
  color: #38bdf8;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .subtitle-folder-mark:hover,
:global(html.dark) .subtitle-folder-mark:hover {
  background: transparent;
  color: #7dd3fc;
}

.subtitle-pairing-grid-wrap {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 360px;
  overflow-x: hidden;
}

.subtitle-pairing-grid {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  width: 100%;
  min-height: 0;
  grid-template-columns:
    minmax(210px, 1fr)
    minmax(260px, 0.88fr)
    minmax(210px, 1fr);
  gap: 12px;
}

.subtitle-pairing-grid > * {
  min-width: 0;
  min-height: 360px;
}

.subtitle-inspector-workbench-scroll.is-pairing-mode {
  overflow: auto;
}

.subtitle-pairing-stage {
  flex: 1 1 auto;
  min-height: 0;
}

.is-spinning { animation: subtitle-spin 1s linear infinite; }
.is-sequence-pulse { animation: subtitle-sequence-pulse 1.4s ease-in-out infinite; }
@keyframes subtitle-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes subtitle-sequence-pulse {
  0%, 100% { transform: scale(1) rotate(0deg); filter: drop-shadow(0 0 0 rgba(37, 99, 235, 0)); }
  50% { transform: scale(1.18) rotate(-8deg); filter: drop-shadow(0 0 8px rgba(37, 99, 235, 0.35)); }
}
.sub-stage-fade-enter-active, .sub-stage-fade-leave-active { transition: all 0.25s ease; }
.sub-stage-fade-enter-from, .sub-stage-fade-leave-to { opacity: 0; transform: translateY(-4px); }
.subtitle-inspector-workbench-scroll { scrollbar-gutter: stable; }
.subtitle-inspector-workbench-scroll::-webkit-scrollbar { width: 6px; }
.subtitle-inspector-workbench-scroll::-webkit-scrollbar-thumb { border-radius: 999px; background: rgba(148, 163, 184, 0.36); }

@media (max-width: 1180px) {
  .subtitle-pairing-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
