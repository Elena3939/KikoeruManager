<template>
  <div class="subtitle-config-card">
    <template v-if="mode === 'settings'">
      <div class="subtitle-settings-compact">
        <section class="subtitle-settings-block subtitle-fetch-block group/card">
          <div class="subtitle-compact-head">
            <span class="header-badge header-badge-fetch">
              <SlidersHorizontal class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">抓取行为</div>
            </div>
          </div>

          <div class="subtitle-quick-grid">
            <div class="subtitle-depth-control">
              <span class="subtitle-quick-label">扫描深度</span>
              <div class="subtitle-stepper" role="group" aria-label="扫描深度">
                <input
                  class="subtitle-stepper-input"
                  type="number"
                  :value="ctx.subtitleOptions.scanDepth"
                  min="1"
                  max="10"
                  step="1"
                  @input="setScanDepth($event.target.value)"
                  @blur="setScanDepth($event.target.value)"
                />
                <div class="subtitle-stepper-actions">
                  <button type="button" class="subtitle-stepper-btn" aria-label="增加扫描深度" @click="adjustScanDepth(1)">
                    <ChevronUp class="h-[11px] w-[11px]" :stroke-width="2.4" />
                  </button>
                  <button type="button" class="subtitle-stepper-btn" aria-label="减少扫描深度" @click="adjustScanDepth(-1)">
                    <ChevronDown class="h-[11px] w-[11px]" :stroke-width="2.4" />
                  </button>
                </div>
              </div>
            </div>
            <div class="subtitle-quick-toggle">
              <span class="subtitle-quick-label">覆盖已有</span>
              <button
                type="button"
                class="subtitle-switch tone-overwrite"
                :class="{ checked: ctx.subtitleOptions.overwriteExisting }"
                role="switch"
                :aria-checked="ctx.subtitleOptions.overwriteExisting"
                @click="ctx.setSubtitleOption('overwriteExisting', !ctx.subtitleOptions.overwriteExisting)"
              >
                <span class="subtitle-switch-knob"></span>
              </button>
            </div>

            <div class="subtitle-quick-toggle">
              <span class="subtitle-quick-label">Metadata</span>
              <button
                type="button"
                class="subtitle-switch tone-metadata"
                :class="{ checked: ctx.subtitleOptions.enableMetadataMatch }"
                role="switch"
                :aria-checked="ctx.subtitleOptions.enableMetadataMatch"
                @click="ctx.setSubtitleOption('enableMetadataMatch', !ctx.subtitleOptions.enableMetadataMatch)"
              >
                <span class="subtitle-switch-knob"></span>
              </button>
            </div>

            <div class="subtitle-quick-toggle">
              <span class="subtitle-quick-label">已有字幕跳过</span>
              <button
                type="button"
                class="subtitle-switch tone-skip"
                :class="{ checked: ctx.subtitleOptions.skipIfExistingSubtitles }"
                role="switch"
                :aria-checked="ctx.subtitleOptions.skipIfExistingSubtitles"
                @click="ctx.setSubtitleOption('skipIfExistingSubtitles', !ctx.subtitleOptions.skipIfExistingSubtitles)"
              >
                <span class="subtitle-switch-knob"></span>
              </button>
            </div>
          </div>
        </section>

        <section class="subtitle-settings-block subtitle-filter-settings-block group/card">
          <div class="subtitle-compact-head">
            <span class="header-badge header-badge-filter">
              <Filter class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[-8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">命名与筛选</div>
            </div>
          </div>

          <div class="subtitle-filter-compact-panel">
            <div class="subtitle-filter-compact-row">
              <div class="subtitle-setting-main min-w-0">
                <div class="subtitle-option-title">同名依据</div>
              </div>
              <div class="subtitle-naming-switch" role="radiogroup" aria-label="同名依据">
                <button
                  v-for="option in namingOptions"
                  :key="option.value"
                  type="button"
                  class="group/naming subtitle-naming-option"
                  :class="[option.tone, { active: ctx.subtitleOptions.namingStrategy === option.value }]"
                  role="radio"
                  :aria-checked="ctx.subtitleOptions.namingStrategy === option.value"
                  @click="ctx.setSubtitleOption('namingStrategy', option.value)"
                >
                  <component
                    :is="option.icon"
                    :class="['h-[13px] w-[13px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/naming:scale-110 group-hover/naming:rotate-[8deg]', option.color]"
                    :stroke-width="2.4"
                  />
                  <span>{{ option.label }}</span>
                </button>
              </div>
            </div>

            <div class="subtitle-filter-compact-row subtitle-filter-toggle-row subtitle-filter-toggle-card">
              <div class="subtitle-setting-main min-w-0">
                <div class="subtitle-option-title">启用字幕过滤</div>
                <div class="subtitle-card-tip">规则 {{ enabledSubtitleFilterRuleCount }} / {{ subtitleFilterRuleCount }}</div>
              </div>
              <button
                type="button"
                class="subtitle-switch tone-filter"
                :class="{ checked: ctx.subtitleOptions.useFilterRules }"
                role="switch"
                :aria-checked="ctx.subtitleOptions.useFilterRules"
                @click="ctx.setSubtitleOption('useFilterRules', !ctx.subtitleOptions.useFilterRules)"
              >
                <span class="subtitle-switch-knob"></span>
              </button>
            </div>
          </div>

          <div v-if="ctx.subtitleOptions.useFilterRules" class="subtitle-filter-editor">
            <div v-if="!ctx.subtitleOptions.subtitleFilterRules.length" class="subtitle-filter-empty">
              <Inbox class="h-[14px] w-[14px] text-slate-400" :stroke-width="2.2" />
              <span>还没有规则</span>
              <button
                type="button"
                class="group/btn subtitle-filter-add-btn subtitle-filter-empty-add"
                @click="handleAddSubtitleFilterRule"
              >
                <Plus class="h-[13px] w-[13px] text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:rotate-[90deg] group-hover/btn:scale-110" :stroke-width="2.4" />
                <span>新增</span>
              </button>
            </div>

            <div v-else class="subtitle-filter-rule-strip">
              <button
                type="button"
                class="subtitle-filter-nav-btn"
                :disabled="subtitleFilterRuleCount <= 1"
                title="上一条规则"
                @click="selectAdjacentSubtitleFilterRule(-1)"
              >
                <ChevronUp class="h-[12px] w-[12px]" :stroke-width="2.4" />
              </button>
              <button
                type="button"
                class="subtitle-filter-current-card"
                @click="filterRuleEditorExpanded = !filterRuleEditorExpanded"
              >
                <span class="subtitle-filter-index">{{ activeSubtitleFilterRuleIndex + 1 }}</span>
                <span class="subtitle-filter-summary min-w-0 flex-1">
                  <span class="subtitle-filter-row-topline">
                    <span class="subtitle-filter-summary-title">{{ String(activeSubtitleFilterRule?.name || '').trim() || `规则 ${activeSubtitleFilterRuleIndex + 1}` }}</span>
                    <span class="subtitle-filter-target-mini">{{ getFilterRuleTargetLabel(activeSubtitleFilterRule?.target) }}</span>
                  </span>
                  <span
                    class="subtitle-filter-summary-pattern"
                    :title="String(activeSubtitleFilterRule?.pattern || '').trim() || '尚未填写正则'"
                  >{{ String(activeSubtitleFilterRule?.pattern || '').trim() || '尚未填写正则' }}</span>
                </span>
                <span class="subtitle-filter-state" :class="{ off: activeSubtitleFilterRule?.enabled === false }">{{ activeSubtitleFilterRule?.enabled === false ? '停用' : '启用' }}</span>
              </button>
              <button
                type="button"
                class="subtitle-filter-nav-btn"
                :disabled="subtitleFilterRuleCount <= 1"
                title="下一条规则"
                @click="selectAdjacentSubtitleFilterRule(1)"
              >
                <ChevronDown class="h-[12px] w-[12px]" :stroke-width="2.4" />
              </button>
              <button
                type="button"
                class="group/btn subtitle-filter-add-btn subtitle-filter-add-icon-btn"
                title="新增过滤规则"
                @click="handleAddSubtitleFilterRule"
              >
                <Plus class="h-[13px] w-[13px] text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:rotate-[90deg] group-hover/btn:scale-110" :stroke-width="2.4" />
              </button>
            </div>

            <div
              v-if="activeSubtitleFilterRule && filterRuleEditorExpanded"
              class="subtitle-filter-detail"
              :class="{ 'is-expanded': filterRuleEditorExpanded }"
            >
              <div class="subtitle-filter-detail-head">
                <div>
                  <div class="subtitle-filter-detail-title">规则 {{ activeSubtitleFilterRuleIndex + 1 }}</div>
                </div>
                <div class="subtitle-filter-detail-actions">
                  <button
                    type="button"
                    class="subtitle-switch subtitle-switch-compact"
                    :class="{ checked: activeSubtitleFilterRule.enabled !== false }"
                    role="switch"
                    :aria-checked="activeSubtitleFilterRule.enabled !== false"
                    @click="activeSubtitleFilterRule.enabled = activeSubtitleFilterRule.enabled === false"
                  >
                    <span class="subtitle-switch-knob"></span>
                  </button>
                  <button
                    type="button"
                    class="subtitle-filter-editor-toggle"
                    @click="filterRuleEditorExpanded = !filterRuleEditorExpanded"
                  >
                    <component
                      :is="filterRuleEditorExpanded ? ChevronUp : ChevronDown"
                      class="h-[12px] w-[12px]"
                      :stroke-width="2.4"
                    />
                    <span>{{ filterRuleEditorExpanded ? '收起' : '编辑' }}</span>
                  </button>
                </div>
              </div>
              <div v-if="!filterRuleEditorExpanded" class="subtitle-filter-current-summary">
                <span class="subtitle-filter-target-badge">{{ getFilterRuleTargetLabel(activeSubtitleFilterRule.target) }}</span>
                <span class="subtitle-filter-current-name">{{ String(activeSubtitleFilterRule.name || '').trim() || `规则 ${activeSubtitleFilterRuleIndex + 1}` }}</span>
                <span class="subtitle-filter-current-pattern">{{ String(activeSubtitleFilterRule.pattern || '').trim() || '尚未填写正则' }}</span>
              </div>
              <template v-else>
                <div class="subtitle-filter-form-grid">
                  <label class="subtitle-filter-field">
                    <span>匹配范围</span>
                    <AppDropdown
                      v-model="activeSubtitleFilterRule.target"
                      :options="subtitleFilterTargetOptions"
                      class="subtitle-filter-target"
                      :width="110"
                      :menu-min-width="130"
                      :show-trigger-badge="false"
                    />
                  </label>
                  <label class="subtitle-filter-field">
                    <span>规则名称</span>
                    <input
                      v-model="activeSubtitleFilterRule.name"
                      class="subtitle-native-input"
                      type="text"
                      placeholder="例如：反转版"
                    />
                  </label>
                  <label class="subtitle-filter-field subtitle-filter-field-full">
                    <span>正则表达式</span>
                    <textarea
                      v-model="activeSubtitleFilterRule.pattern"
                      class="subtitle-native-input subtitle-native-textarea"
                      placeholder="例如 (反转|reverse|無SE)"
                    ></textarea>
                  </label>
                </div>
                <div class="subtitle-filter-row-actions">
                  <span class="subtitle-filter-target-badge">{{ getFilterRuleTargetLabel(activeSubtitleFilterRule.target) }}</span>
                  <button
                    type="button"
                    class="group/btn subtitle-filter-delete-btn inline-flex items-center gap-1 rounded-[8px] border border-rose-200 bg-white px-2.5 py-1 text-[11.5px] font-semibold text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-rose-300 active:scale-[0.96]"
                    @click="removeActiveSubtitleFilterRule"
                  >
                    <Trash2 class="h-[12px] w-[12px] text-rose-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:rotate-[-12deg] group-hover/btn:scale-110" :stroke-width="2.4" />
                    <span>删除</span>
                  </button>
                </div>
              </template>
            </div>
          </div>
        </section>

        <section class="subtitle-settings-block subtitle-display-block group/card">
          <div class="subtitle-inline-section-head">
            <div class="inline-flex min-w-0 items-center gap-2">
            <span class="header-badge header-badge-display">
              <LayoutPanelLeft class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
              <div class="subtitle-block-title">任务展示</div>
            </div>
            <span class="subtitle-inline-section-tip">仅显示</span>
          </div>

          <div class="subtitle-pill-grid">
            <button
              v-for="pill in displayPills"
              :key="pill.key"
              type="button"
              class="group/pill subtitle-toggle-pill"
              :class="[pill.tone, { active: ctx.subtitleOptions[pill.key] }]"
              :title="pill.label"
              :aria-pressed="Boolean(ctx.subtitleOptions[pill.key])"
              @click="ctx.setSubtitleOption(pill.key, !ctx.subtitleOptions[pill.key])"
            >
              <component
                :is="pill.icon"
                :class="['h-[13px] w-[13px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/pill:scale-110 group-hover/pill:rotate-[8deg]', pill.color]"
                :stroke-width="2.4"
              />
              <span>{{ pill.label }}</span>
            </button>
          </div>
        </section>

        <section class="subtitle-settings-block subtitle-tool-block group/card">
          <div class="subtitle-tool-row">
            <div class="min-w-0">
              <div class="subtitle-block-title">字幕清理</div>
              <div class="subtitle-block-tip">{{ ctx.subtitleCleanupSummary || '清理字幕正文里的多余标记。' }}</div>
            </div>
            <button
              type="button"
              class="subtitle-tool-btn tone-cleanup"
              :disabled="ctx.subtitleCleanupLoading || !ctx.activeTask"
              @click="ctx.applySubtitleCleanup"
            >
              <component :is="ctx.subtitleCleanupLoading ? Loader2 : WandSparkles" class="h-[13px] w-[13px]" :class="{ 'animate-spin': ctx.subtitleCleanupLoading }" :stroke-width="2.4" />
              <span>{{ ctx.subtitleCleanupLoading ? '清理中' : '执行' }}</span>
            </button>
          </div>
        </section>

        <section class="subtitle-settings-block subtitle-tool-block group/card">
          <div class="subtitle-tool-row">
            <div class="min-w-0">
              <div class="subtitle-block-title">目标目录</div>
              <div class="subtitle-block-tip">{{ retargetSummary }}</div>
            </div>
            <button
              type="button"
              class="subtitle-tool-btn tone-refresh"
              :disabled="!ctx.activeTaskSupportsRetarget || ctx.retargetPreviewLoading"
              @click="ctx.loadRetargetPreview?.(ctx.activeTask, { force: true, showMessage: true })"
            >
              <component :is="ctx.retargetPreviewLoading ? Loader2 : RefreshCw" class="h-[13px] w-[13px]" :class="{ 'animate-spin': ctx.retargetPreviewLoading }" :stroke-width="2.4" />
              <span>刷新</span>
            </button>
          </div>

          <div v-if="ctx.activeTaskSupportsRetarget && ctx.retargetCandidates?.length" class="subtitle-retarget-list">
            <button
              v-for="candidate in ctx.retargetCandidates.slice(0, 3)"
              :key="ctx.candidateKey?.(candidate) || candidate.folder_path"
              type="button"
              class="subtitle-retarget-option"
              :class="{ active: ctx.retargetCandidateSelection === (ctx.candidateKey?.(candidate) || '') }"
              @click="ctx.setRetargetCandidateSelection?.(ctx.candidateKey?.(candidate) || '')"
            >
              <span class="subtitle-retarget-main">{{ candidate.library_id || '默认库' }}</span>
              <span class="subtitle-retarget-path">{{ candidate.folder_path || '-' }}</span>
            </button>
          </div>

          <button
            v-if="ctx.activeTaskSupportsRetarget"
            type="button"
            class="subtitle-tool-btn subtitle-tool-btn-wide tone-retarget"
            :disabled="!ctx.canRetargetActiveTask || Boolean(ctx.retargetingTaskId)"
            @click="ctx.retargetActiveTask"
          >
            <component :is="ctx.retargetingTaskId ? Loader2 : ArrowRightLeft" class="h-[13px] w-[13px]" :class="{ 'animate-spin': ctx.retargetingTaskId }" :stroke-width="2.4" />
            <span>{{ ctx.retargetingTaskId ? '切换中' : '切换目标并重建' }}</span>
          </button>
        </section>
      </div>
    </template>

    <template v-else-if="mode === 'pairing'">
      <div class="subtitle-option-stack">
        <!-- 选中快照 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Gauge class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">选中快照</div>
              <div class="subtitle-block-tip">顺序点选、配对数量，一目了然。</div>
            </div>
          </div>
          <div class="stat-trio">
            <div
              v-for="row in pairingRows"
              :key="row.key"
              class="stat-cell group/stat"
            >
              <div class="flex items-center gap-1.5 text-slate-500">
                <component
                  :is="row.icon"
                  :class="['h-[14px] w-[14px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:scale-110 group-hover/stat:rotate-[12deg]', row.color]"
                  :stroke-width="2.2"
                />
                <span class="text-[11.5px] font-semibold tracking-[-0.005em] truncate">{{ row.label }}</span>
              </div>
              <div class="mt-1 text-[30px] font-black leading-none text-slate-900 tabular-nums tracking-[-0.04em] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:-translate-y-0.5">{{ row.value }}</div>
            </div>
          </div>
        </section>

        <!-- AI 配对策略 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Bot class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">AI 配对策略</div>
              <div class="subtitle-block-tip">只生成配对草稿，确认后再导入。</div>
            </div>
          </div>

          <div class="subtitle-filter-compact-panel">
            <div class="subtitle-filter-compact-row subtitle-ai-mode-row">
              <div class="subtitle-setting-main min-w-0">
                <div class="subtitle-option-title">配对模式</div>
              </div>
              <div class="subtitle-ai-mode-switch" role="radiogroup" aria-label="AI 配对模式">
                <button
                  v-for="option in aiModeOptions"
                  :key="option.value"
                  type="button"
                  class="group/ai subtitle-ai-mode-option"
                  :class="[option.tone, { active: resolvedAiMatchMode === option.value }]"
                  role="radio"
                  :aria-checked="resolvedAiMatchMode === option.value"
                  @click="ctx.setSubtitleOption('aiMatchMode', option.value)"
                >
                  <component
                    :is="option.icon"
                    :class="['h-[12px] w-[12px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/ai:scale-110 group-hover/ai:rotate-[8deg]', option.color]"
                    :stroke-width="2.4"
                  />
                  <span>{{ option.label }}</span>
                </button>
              </div>
            </div>

            <div v-if="resolvedAiMatchMode !== 'rule'" class="subtitle-filter-compact-row subtitle-ai-threshold-row">
              <div class="subtitle-setting-main min-w-0">
                <div class="subtitle-option-title">自动阈值</div>
                <div class="subtitle-card-tip">{{ normalizedAiThreshold }} 分以上高置信</div>
              </div>
              <div class="subtitle-stepper subtitle-threshold-stepper" role="group" aria-label="AI 自动阈值">
                <input
                  class="subtitle-stepper-input"
                  type="number"
                  :value="normalizedAiThreshold"
                  min="0"
                  max="100"
                  step="1"
                  @input="setAiConfidenceThreshold($event.target.value)"
                  @blur="setAiConfidenceThreshold($event.target.value)"
                />
                <div class="subtitle-stepper-actions">
                  <button type="button" class="subtitle-stepper-btn" aria-label="增加 AI 阈值" @click="adjustAiConfidenceThreshold(1)">
                    <ChevronUp class="h-[11px] w-[11px]" :stroke-width="2.4" />
                  </button>
                  <button type="button" class="subtitle-stepper-btn" aria-label="减少 AI 阈值" @click="adjustAiConfidenceThreshold(-1)">
                    <ChevronDown class="h-[11px] w-[11px]" :stroke-width="2.4" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 快捷动作 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Zap class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[-12deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">快捷动作</div>
              <div class="subtitle-block-tip">先点音频，再点字幕，生成顺序预配对。</div>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="group/btn flex items-center justify-center gap-1.5 rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-[12px] font-semibold text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-slate-300 enabled:hover:bg-slate-50 enabled:hover:shadow-[0_8px_16px_rgba(15,23,42,0.08)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-slate-50/40"
              :disabled="!ctx.canClearSequenceSelection"
              @click="ctx.clearSubtitleSequenceSelection"
            >
              <Eraser class="h-[14px] w-[14px] text-slate-500 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[-12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.2" />
              <span>清空顺序</span>
            </button>
            <button
              type="button"
              class="group/btn flex items-center justify-center gap-1.5 rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-[12px] font-semibold text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-slate-300 enabled:hover:bg-slate-50 enabled:hover:shadow-[0_8px_16px_rgba(15,23,42,0.08)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-slate-50/40"
              :disabled="!ctx.canClearManualPairs"
              @click="ctx.clearSubtitleManualPairs"
            >
              <Unlink class="h-[14px] w-[14px] text-slate-500 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.2" />
              <span>清空配对</span>
            </button>
          </div>
        </section>

        <!-- 删除预审 -->
        <section class="subtitle-settings-block subtitle-help-card-danger group/card">
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-3 min-w-0">
              <span class="header-badge header-badge-danger">
                <ShieldAlert class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
              </span>
              <div class="min-w-0">
                <div class="subtitle-block-title">删除预审</div>
                <div class="subtitle-block-tip">已移出主流程，避免和配对动作混用。</div>
              </div>
            </div>
            <button
              type="button"
              class="group/btn inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-rose-200 bg-white px-3 py-2 text-[12px] font-bold text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-rose-500 enabled:hover:bg-rose-500 enabled:hover:text-white enabled:hover:shadow-[0_10px_18px_rgba(244,63,94,0.28)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="!ctx.canOpenSubtitleInspectorFilterDeleteDialog"
              @click="ctx.openSubtitleInspectorFilterDeleteDialog"
            >
              <Trash2 class="h-[13px] w-[13px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[-12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.4" />
              <span>执行</span>
            </button>
          </div>
        </section>
      </div>
    </template>

    <template v-else>
      <div class="subtitle-option-stack">
        <!-- 文件快照 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <FolderTree class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">文件快照</div>
              <div class="subtitle-block-tip">搜索范围与选中规模一览。</div>
            </div>
          </div>
          <div class="stat-trio stat-trio-2">
            <div
              v-for="row in treeRows"
              :key="row.key"
              class="stat-cell group/stat"
            >
              <div class="flex items-center gap-1.5 text-slate-500">
                <component
                  :is="row.icon"
                  :class="['h-[14px] w-[14px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:scale-110 group-hover/stat:rotate-[12deg]', row.color]"
                  :stroke-width="2.2"
                />
                <span class="text-[11.5px] font-semibold tracking-[-0.005em] truncate">{{ row.label }}</span>
              </div>
              <div class="mt-1 text-[30px] font-black leading-none text-slate-900 tabular-nums tracking-[-0.04em] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:-translate-y-0.5">{{ row.value }}</div>
            </div>
          </div>
          <div class="search-row group/search">
            <span class="search-chip">
              <Search class="h-[11px] w-[11px] shrink-0 text-slate-400 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/search:rotate-[-10deg] group-hover/search:scale-[1.18] group-hover/search:text-slate-700" :stroke-width="2.6" />
              <span>搜索词</span>
            </span>
            <span
              class="min-w-0 flex-1 truncate text-[12px] font-semibold"
              :class="ctx.treeSearchText ? 'text-slate-900' : 'text-slate-400'"
              :title="ctx.treeSearchText || ''"
            >{{ ctx.treeSearchText || '未搜索' }}</span>
          </div>
        </section>

        <!-- 删除风险 -->
        <section class="subtitle-settings-block subtitle-help-card-danger group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge header-badge-danger">
              <AlertTriangle class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">删除风险</div>
              <div class="subtitle-block-tip">操作直接作用于字幕目录，批量前先确认范围。</div>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import {
  Gauge,
  Zap,
  Eraser,
  Unlink,
  Trash2,
  ShieldAlert,
  AlertTriangle,
  FolderTree,
  Search,
  Music,
  FileText,
  Link2,
  CheckSquare,
  Eye,
  SlidersHorizontal,
  Filter,
  LayoutPanelLeft,
  Plus,
  Inbox,
  Globe,
  PenLine,
  Download,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  WandSparkles,
  RefreshCw,
  ArrowRightLeft,
  Bot,
  ClipboardList,
  Sparkles
} from 'lucide-vue-next'
import AppDropdown from '../../common/AppDropdown.vue'

// 字幕过滤规则匹配范围选项
const subtitleFilterTargetOptions = [
  { value: 'name', label: '文件名' },
  { value: 'path', label: '路径' },
  { value: 'all', label: '全部' },
]

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: 'settings'
  }
})

const activeFilterRuleKey = ref('')
const filterRuleEditorExpanded = ref(false)

const pairingRows = computed(() => [
  { key: 'audio', label: '音频轨', icon: Music, color: 'text-sky-600', value: props.ctx?.pairingAudioSelectedCount || 0 },
  { key: 'subtitle', label: '字幕轨', icon: FileText, color: 'text-violet-600', value: props.ctx?.pairingSubtitleSelectedCount || 0 },
  { key: 'pairs', label: '配对组', icon: Link2, color: 'text-emerald-600', value: props.ctx?.pairingPairCount || 0 }
])

const treeRows = computed(() => [
  { key: 'selected', label: '已选', icon: CheckSquare, color: 'text-emerald-600', value: props.ctx?.treeSelectedCount || 0 },
  { key: 'visible', label: '可见', icon: Eye, color: 'text-sky-600', value: props.ctx?.treeVisibleCount || 0 }
])

const displayPills = [
  { key: 'showSourceSearch', label: '来源搜索', icon: Globe, color: 'text-sky-600', tone: 'tone-source' },
  { key: 'showWrittenFiles', label: '写入结果', icon: PenLine, color: 'text-emerald-600', tone: 'tone-written' },
  { key: 'showDownloadedFiles', label: '下载进度', icon: Download, color: 'text-violet-600', tone: 'tone-download' },
  { key: 'showIssues', label: '问题项', icon: AlertCircle, color: 'text-amber-600', tone: 'tone-issue' }
]

const namingOptions = [
  { value: 'audio', label: '音频名', icon: Music, color: 'text-sky-600', tone: 'tone-audio' },
  { value: 'subtitle', label: '字幕名', icon: FileText, color: 'text-violet-600', tone: 'tone-subtitle' }
]

const aiModeOptions = [
  { value: 'rule', label: '规则', icon: ClipboardList, color: 'text-slate-600', tone: 'tone-rule' },
  { value: 'ai_auto', label: 'AI 自动', icon: Bot, color: 'text-cyan-600', tone: 'tone-ai-auto' },
  { value: 'rule_ai_auto', label: '规则+AI', icon: Sparkles, color: 'text-emerald-600', tone: 'tone-rule-ai' },
  { value: 'ai_assist', label: 'AI 草稿', icon: WandSparkles, color: 'text-violet-600', tone: 'tone-ai-assist' }
]

const resolvedAiMatchMode = computed(() => {
  const mode = String(props.ctx?.subtitleOptions?.aiMatchMode || '').trim().toLowerCase()
  return aiModeOptions.some(option => option.value === mode) ? mode : 'rule_ai_auto'
})

const normalizedAiThreshold = computed(() => normalizeAiConfidenceThreshold(props.ctx?.subtitleOptions?.aiConfidenceThreshold))

const subtitleFilterRuleCount = computed(() => props.ctx?.subtitleOptions?.subtitleFilterRules?.length || 0)

const enabledSubtitleFilterRuleCount = computed(() => (
  props.ctx?.subtitleOptions?.subtitleFilterRules || []
).filter(rule => rule.enabled !== false).length)

const retargetSummary = computed(() => {
  if (!props.ctx?.activeTask) return '先选择一个任务。'
  if (!props.ctx?.activeTaskSupportsRetarget) return '当前任务不支持切换。'
  if (props.ctx?.retargetPreviewLoading) return '正在刷新候选目录。'
  const count = props.ctx?.retargetCandidates?.length || 0
  return count ? `候选 ${count} 个` : '暂无候选目录'
})

function normalizeScanDepth(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 3
  return Math.max(1, Math.min(10, Math.round(numeric)))
}

function normalizeAiConfidenceThreshold(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 85
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

function setScanDepth(value) {
  props.ctx?.setSubtitleOption?.('scanDepth', normalizeScanDepth(value))
}

function adjustScanDepth(delta) {
  setScanDepth(Number(props.ctx?.subtitleOptions?.scanDepth || 3) + delta)
}

function setAiConfidenceThreshold(value) {
  props.ctx?.setSubtitleOption?.('aiConfidenceThreshold', normalizeAiConfidenceThreshold(value))
}

function adjustAiConfidenceThreshold(delta) {
  setAiConfidenceThreshold(normalizedAiThreshold.value + delta)
}

const activeSubtitleFilterRuleIndex = computed(() => {
  const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
  if (!rules.length) return -1
  const index = rules.findIndex((rule, idx) => getFilterRuleKey(rule, idx) === activeFilterRuleKey.value)
  return index >= 0 ? index : 0
})

const activeSubtitleFilterRule = computed(() => {
  const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
  return activeSubtitleFilterRuleIndex.value >= 0 ? rules[activeSubtitleFilterRuleIndex.value] : null
})

function getFilterRuleKey(rule, index) {
  return rule?.id || `rule-${index}`
}

function getFilterRuleTargetLabel(target) {
  if (target === 'path') return '路径'
  if (target === 'all') return '全部'
  return '文件名'
}

function selectSubtitleFilterRule(rule, index) {
  activeFilterRuleKey.value = getFilterRuleKey(rule, index)
  filterRuleEditorExpanded.value = false
}

function selectAdjacentSubtitleFilterRule(delta) {
  const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
  if (!rules.length) return
  const currentIndex = activeSubtitleFilterRuleIndex.value >= 0 ? activeSubtitleFilterRuleIndex.value : 0
  const nextIndex = (currentIndex + delta + rules.length) % rules.length
  selectSubtitleFilterRule(rules[nextIndex], nextIndex)
}

function handleAddSubtitleFilterRule() {
  props.ctx?.addSubtitleFilterRule?.()
  nextTick(() => {
    const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
    const lastIndex = rules.length - 1
    if (lastIndex >= 0) activeFilterRuleKey.value = getFilterRuleKey(rules[lastIndex], lastIndex)
    filterRuleEditorExpanded.value = false
  })
}

function removeActiveSubtitleFilterRule() {
  const rule = activeSubtitleFilterRule.value
  if (!rule?.id) return
  props.ctx?.removeSubtitleFilterRule?.(rule.id)
  nextTick(() => {
    const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
    const nextIndex = Math.min(activeSubtitleFilterRuleIndex.value, rules.length - 1)
    activeFilterRuleKey.value = nextIndex >= 0 ? getFilterRuleKey(rules[nextIndex], nextIndex) : ''
  })
}
</script>

<style scoped>
.subtitle-config-card {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  min-height: 0;
  overflow: hidden;
}

.subtitle-switch {
  --switch-accent: #64748b;
  --switch-accent-dark: #475569;
  position: relative;
  width: 34px;
  height: 20px;
  flex-shrink: 0;
  padding: 0;
  border: 1px solid #d8e1ec;
  border-radius: 999px;
  background: #e2e8f0;
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-switch:hover {
  transform: translateY(-1px) scale(1.02);
  border-color: #c3d4e5;
}

.subtitle-switch:active {
  transform: scale(0.96);
}

.subtitle-switch.checked {
  background: var(--switch-accent);
  border-color: var(--switch-accent-dark);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.28);
}

.subtitle-switch.tone-overwrite {
  --switch-accent: #e11d48;
  --switch-accent-dark: #be123c;
}

.subtitle-switch.tone-metadata {
  --switch-accent: #0ea5e9;
  --switch-accent-dark: #0284c7;
}

.subtitle-switch.tone-skip {
  --switch-accent: #059669;
  --switch-accent-dark: #047857;
}

.subtitle-switch.tone-filter {
  --switch-accent: #d97706;
  --switch-accent-dark: #b45309;
}

.subtitle-switch-knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14);
  transition: transform 0.3s var(--ease-spring), background-color 0.3s ease;
}

.subtitle-switch.checked .subtitle-switch-knob {
  transform: translateX(14px);
}

.subtitle-switch-compact {
  width: 32px;
  height: 18px;
}

.subtitle-switch-compact .subtitle-switch-knob {
  width: 12px;
  height: 12px;
}

.subtitle-switch-compact.checked .subtitle-switch-knob {
  transform: translateX(12px);
}

.subtitle-stepper {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 30px;
  width: 88px;
  height: 28px;
  overflow: hidden;
  border: 1px solid #d8e1ec;
  border-radius: 12px;
  background: #ffffff;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-stepper:hover,
.subtitle-stepper:focus-within {
  border-color: #c3d4e5;
  box-shadow: 0 0 0 3px rgba(114, 157, 208, 0.12);
}

.subtitle-stepper-input {
  min-width: 0;
  width: 100%;
  border: 0;
  background: transparent;
  color: #0f172a;
  font-size: 12px;
  font-weight: 800;
  text-align: center;
  outline: none;
}

.subtitle-stepper-input::-webkit-outer-spin-button,
.subtitle-stepper-input::-webkit-inner-spin-button {
  margin: 0;
  appearance: none;
}

.subtitle-stepper-actions {
  display: grid;
  border-left: 1px solid #e2e8f0;
}

.subtitle-stepper-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-stepper-btn:first-child {
  border-bottom: 1px solid #e2e8f0;
}

.subtitle-stepper-btn:hover {
  background: #eef2f7;
  color: #0f172a;
}

.subtitle-naming-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  width: 168px;
  padding: 3px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #f8fafc;
  box-shadow: none;
}

.subtitle-naming-option {
  --option-accent: #64748b;
  --option-accent-soft: rgba(100, 116, 139, 0.12);
  --option-accent-border: rgba(100, 116, 139, 0.24);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  height: 26px;
  min-height: 24px;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-naming-option:hover {
  transform: translateY(-1px) scale(1.01);
  color: #0f172a;
  background: var(--option-accent-soft);
  border-color: var(--option-accent-border);
}

.subtitle-naming-option:active {
  transform: scale(0.96);
}

.subtitle-naming-option.active {
  border-color: var(--option-accent-border);
  background: var(--option-accent-soft);
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.76);
}

.subtitle-naming-option.tone-audio {
  --option-accent: #0284c7;
  --option-accent-soft: rgba(14, 165, 233, 0.16);
  --option-accent-border: rgba(2, 132, 199, 0.36);
}

.subtitle-naming-option.tone-subtitle {
  --option-accent: #7c3aed;
  --option-accent-soft: rgba(139, 92, 246, 0.16);
  --option-accent-border: rgba(124, 58, 237, 0.34);
}

.subtitle-ai-mode-row {
  align-items: stretch;
}

.subtitle-ai-mode-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  width: 188px;
  padding: 3px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #f8fafc;
}

.subtitle-ai-mode-option {
  --ai-option-soft: rgba(100, 116, 139, 0.12);
  --ai-option-border: rgba(100, 116, 139, 0.24);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  height: 25px;
  min-height: 24px;
  padding: 4px 5px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  font-size: 10.8px;
  font-weight: 850;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-ai-mode-option:hover {
  transform: translateY(-1px) scale(1.01);
  color: #0f172a;
  background: var(--ai-option-soft);
  border-color: var(--ai-option-border);
}

.subtitle-ai-mode-option:active {
  transform: scale(0.96);
}

.subtitle-ai-mode-option.active {
  border-color: var(--ai-option-border);
  background: var(--ai-option-soft);
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.76);
}

.subtitle-ai-mode-option.tone-rule {
  --ai-option-soft: rgba(100, 116, 139, 0.14);
  --ai-option-border: rgba(100, 116, 139, 0.28);
}

.subtitle-ai-mode-option.tone-ai-auto {
  --ai-option-soft: rgba(6, 182, 212, 0.16);
  --ai-option-border: rgba(8, 145, 178, 0.34);
}

.subtitle-ai-mode-option.tone-rule-ai {
  --ai-option-soft: rgba(16, 185, 129, 0.16);
  --ai-option-border: rgba(5, 150, 105, 0.34);
}

.subtitle-ai-mode-option.tone-ai-assist {
  --ai-option-soft: rgba(139, 92, 246, 0.16);
  --ai-option-border: rgba(124, 58, 237, 0.34);
}

:global(html.kikoerumanager-dark) .subtitle-config-card :is(.subtitle-naming-switch, .subtitle-ai-mode-switch, .subtitle-stepper),
:global(html.dark) .subtitle-config-card :is(.subtitle-naming-switch, .subtitle-ai-mode-switch, .subtitle-stepper) {
  background: #111216 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card :is(.subtitle-naming-option, .subtitle-ai-mode-option),
:global(html.dark) .subtitle-config-card :is(.subtitle-naming-option, .subtitle-ai-mode-option) {
  color: rgba(214, 214, 220, 0.72) !important;
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card :is(.subtitle-naming-option, .subtitle-ai-mode-option):hover,
:global(html.dark) .subtitle-config-card :is(.subtitle-naming-option, .subtitle-ai-mode-option):hover {
  color: rgba(250, 250, 252, 0.96) !important;
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card :is(.subtitle-naming-option.active, .subtitle-ai-mode-option.active),
:global(html.dark) .subtitle-config-card :is(.subtitle-naming-option.active, .subtitle-ai-mode-option.active) {
  color: #ffffff !important;
  background: var(--option-accent-soft, var(--ai-option-soft, rgba(86, 87, 94, 0.8))) !important;
  background-image: none !important;
  border-color: var(--option-accent-border, var(--ai-option-border, rgba(255, 255, 255, 0.32))) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card :is(.subtitle-stepper-input, .subtitle-stepper-btn),
:global(html.dark) .subtitle-config-card :is(.subtitle-stepper-input, .subtitle-stepper-btn) {
  background: transparent !important;
  color: rgba(246, 246, 248, 0.9) !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card .subtitle-stepper-actions,
:global(html.kikoerumanager-dark) .subtitle-config-card .subtitle-stepper-btn:first-child,
:global(html.dark) .subtitle-config-card .subtitle-stepper-actions,
:global(html.dark) .subtitle-config-card .subtitle-stepper-btn:first-child {
  border-color: rgba(255, 255, 255, 0.14) !important;
}

.subtitle-ai-threshold-row {
  align-items: center;
}

.subtitle-threshold-stepper {
  width: 84px;
}

.subtitle-option-stack,
.subtitle-settings-compact {
  display: grid;
  gap: 4px;
  min-height: 0;
}

.subtitle-settings-block {
  display: grid;
  gap: 5px;
  padding: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 13px;
  background: #ffffff;
  box-shadow: none;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-settings-block {
  gap: 5px;
}

.subtitle-tool-block {
  gap: 6px;
  padding: 7px;
}

.subtitle-tool-row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subtitle-tool-btn {
  --tool-accent: #64748b;
  --tool-accent-soft: rgba(100, 116, 139, 0.12);
  --tool-accent-border: rgba(100, 116, 139, 0.24);
  display: inline-flex;
  min-height: 28px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid #d8e1ec;
  border-radius: 10px;
  background: #ffffff;
  padding: 0 9px;
  color: var(--tool-accent);
  font-size: 11.5px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-tool-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--tool-accent-border);
  background: var(--tool-accent-soft);
  color: var(--tool-accent);
}

.subtitle-tool-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.subtitle-tool-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.subtitle-tool-btn-wide {
  width: 100%;
  min-height: 30px;
}

.subtitle-tool-btn.tone-cleanup {
  --tool-accent: #059669;
  --tool-accent-soft: rgba(16, 185, 129, 0.14);
  --tool-accent-border: rgba(5, 150, 105, 0.32);
}

.subtitle-tool-btn.tone-refresh {
  --tool-accent: #0284c7;
  --tool-accent-soft: rgba(14, 165, 233, 0.14);
  --tool-accent-border: rgba(2, 132, 199, 0.32);
}

.subtitle-tool-btn.tone-retarget {
  --tool-accent: #7c3aed;
  --tool-accent-soft: rgba(139, 92, 246, 0.14);
  --tool-accent-border: rgba(124, 58, 237, 0.32);
}

.subtitle-retarget-list {
  display: grid;
  gap: 4px;
}

.subtitle-retarget-option {
  --option-accent-soft: #303136;
  --option-accent-border: rgba(255, 255, 255, 0.22);
  display: grid;
  min-width: 0;
  gap: 2px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 6px 8px;
  text-align: left;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-retarget-option:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.subtitle-retarget-option.active {
  border-color: rgba(124, 58, 237, 0.34);
  background: rgba(139, 92, 246, 0.14);
  color: #111827;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.76);
}

.subtitle-retarget-main {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 11.5px;
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-retarget-path {
  min-width: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-compact-head,
.subtitle-inline-section-head {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subtitle-fetch-block .subtitle-compact-head {
  justify-content: flex-start;
}

.subtitle-inline-section-tip {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 10.5px;
  font-weight: 800;
}

.subtitle-display-block {
  grid-template-columns: minmax(0, 1fr);
  align-items: stretch;
}

.subtitle-display-block .subtitle-inline-section-head {
  justify-content: flex-start;
  gap: 6px;
}

.subtitle-display-block .subtitle-inline-section-tip {
  display: none;
}

.subtitle-quick-grid {
  display: grid;
  grid-template-columns: minmax(112px, 1.1fr) minmax(0, 1fr);
  gap: 4px;
}

.subtitle-depth-control,
.subtitle-quick-toggle {
  display: flex;
  min-width: 0;
  min-height: 28px;
  align-items: center;
  justify-content: space-between;
  gap: 7px;
  border: 1px solid #eef2f7;
  border-radius: 10px;
  background: #f8fafc;
  padding: 3px 6px;
}

.subtitle-quick-label {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-size: 11.5px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-settings-block:hover {
  border-color: #cbd5e1;
  box-shadow: none;
}

.subtitle-help-card-danger {
  background: #fffafa;
  border-color: #fecaca;
}

.subtitle-help-card-danger:hover {
  border-color: #fca5a5;
  box-shadow: 0 8px 20px rgba(244, 63, 94, 0.08);
}


.stat-trio {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: end;
}

.stat-trio-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.stat-cell {
  position: relative;
  min-width: 0;
  padding: 0 10px;
}

.stat-cell:first-child {
  padding-left: 0;
}

.stat-cell:last-child {
  padding-right: 0;
}

.stat-cell + .stat-cell::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12%;
  bottom: 12%;
  width: 1px;
  background: linear-gradient(180deg, transparent 0%, #e2e8f0 28%, #e2e8f0 72%, transparent 100%);
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: all 0.28s var(--ease-spring);
}

.search-row:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.search-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  font-size: 10.5px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.01em;
  flex-shrink: 0;
  transition: all 0.28s var(--ease-spring);
}

.search-row:hover .search-chip {
  border-color: #cbd5e1;
  color: #0f172a;
}

.subtitle-block-title {
  font-size: 12.5px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: #1f2d3d;
}

.subtitle-block-tip {
  font-size: 11px;
  line-height: 1.35;
  color: #74869d;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.subtitle-filter-compact-panel {
  display: grid;
  gap: 5px;
}

.subtitle-filter-compact-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.subtitle-filter-toggle-row {
  padding-top: 5px;
  border-top: 1px solid #f1f5f9;
}

.subtitle-filter-toggle-card {
  min-height: 34px;
}

.subtitle-setting-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.subtitle-option-title {
  font-size: 11.8px;
  font-weight: 800;
  color: #1f2d3d;
  letter-spacing: -0.01em;
}

.subtitle-card-tip {
  font-size: 10.5px;
  line-height: 1.35;
  color: #64748b;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.subtitle-filter-editor {
  display: grid;
  gap: 4px;
  margin-top: 0;
  padding: 5px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #fbfcfd;
}

.subtitle-filter-current-card {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 30px;
  padding: 4px 6px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
  box-shadow: none;
}

.subtitle-filter-rule-strip {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 24px 24px;
  align-items: stretch;
  gap: 4px;
}

.subtitle-filter-current-card {
  min-height: 30px;
  padding-block: 3px;
}

.subtitle-filter-current-card:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
  transform: translateY(-1px) scale(1.005);
}

.subtitle-filter-nav-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-add-icon-btn,
.subtitle-filter-empty-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-add-icon-btn:hover,
.subtitle-filter-empty-add:hover {
  transform: translateY(-1px) scale(1.03);
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.subtitle-filter-nav-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.03);
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #0f172a;
}

.subtitle-filter-nav-btn:active:not(:disabled) {
  transform: scale(0.96);
}

.subtitle-filter-nav-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.subtitle-filter-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 10.5px;
  font-weight: 800;
  color: #475569;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-summary {
  display: grid;
  gap: 1px;
}

.subtitle-filter-row-topline {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.subtitle-filter-summary-title,
.subtitle-filter-summary-pattern {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-filter-summary-title {
  min-width: 0;
  font-size: 11px;
  font-weight: 800;
  color: #1e293b;
  letter-spacing: -0.01em;
}

.subtitle-filter-summary-pattern {
  max-width: 100%;
  margin-top: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 10px;
  line-height: 1.1;
  color: #64748b;
}

.subtitle-filter-target-mini {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  max-width: 46px;
  height: 17px;
  padding: 0 6px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 10px;
  font-weight: 800;
}

.subtitle-filter-target-badge,
.subtitle-filter-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 34px;
  height: 19px;
  border-radius: 999px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  padding: 0 8px;
  font-size: 10.5px;
  font-weight: 800;
  color: #7c3aed;
}

.subtitle-filter-state {
  min-width: 32px;
  height: 18px;
  border-color: #dbe4ee;
  background: #ffffff;
  color: #475569;
  font-size: 10px;
}

.subtitle-filter-state.off {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #94a3b8;
}

.subtitle-filter-detail {
  display: grid;
  gap: 4px;
  padding: 5px;
  border: 1px solid #dbe4ee;
  border-radius: 11px;
  background: #fbfcfd;
  box-shadow: none;
}

.subtitle-filter-detail.is-expanded {
  gap: 4px;
}

.subtitle-filter-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-filter-detail-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.subtitle-filter-detail-title {
  font-size: 11.5px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.subtitle-filter-editor-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 22px;
  padding: 0 7px;
  border-radius: 8px;
  border: 1px solid #dbe4ee;
  background: #ffffff;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-editor-toggle:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #0f172a;
}

.subtitle-filter-current-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 0.68fr) minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 3px 6px;
  border-radius: 9px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}

.subtitle-filter-current-name,
.subtitle-filter-current-pattern {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-filter-current-name {
  font-size: 11.5px;
  font-weight: 800;
  color: #1e293b;
}

.subtitle-filter-current-pattern {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 10.5px;
  color: #64748b;
}

.subtitle-filter-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 5px 6px;
}

.subtitle-filter-field {
  display: grid;
  gap: 4px;
}

.subtitle-filter-field-full {
  grid-column: 1 / -1;
}

.subtitle-filter-field > span {
  font-size: 10.5px;
  font-weight: 800;
  color: #64748b;
}

.subtitle-native-input {
  width: 100%;
  min-width: 0;
  height: 27px;
  border: 0;
  border-radius: 10px;
  background: #ffffff;
  padding: 0 10px;
  color: #0f172a;
  font-size: 11.5px;
  font-weight: 700;
  box-shadow: 0 0 0 1px #dbe4ee inset;
  outline: none;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-native-input:hover,
.subtitle-native-input:focus {
  box-shadow: 0 0 0 1px #cbd5e1 inset, 0 0 0 3px rgba(114, 157, 208, 0.12);
}

.subtitle-native-input::placeholder {
  color: #94a3b8;
}

.subtitle-native-textarea {
  height: 28px;
  min-height: 28px;
  max-height: 28px;
  padding: 4px 10px;
  resize: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  line-height: 1.35;
  overflow: hidden;
}

.subtitle-filter-row-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subtitle-filter-target {
  min-width: 0;
  max-width: 112px;
}

.subtitle-filter-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  background: #ffffff;
  font-size: 11.5px;
  font-weight: 600;
  color: #64748b;
}

.subtitle-naming-option span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-pill-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
}

.subtitle-toggle-pill {
  --pill-accent: #64748b;
  --pill-accent-soft: rgba(100, 116, 139, 0.12);
  --pill-accent-border: rgba(100, 116, 139, 0.24);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  min-height: 28px;
  padding: 4px 9px;
  border-radius: 9px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-toggle-pill span {
  min-width: max-content;
  white-space: nowrap;
}

.subtitle-toggle-pill:hover {
  transform: translateY(-1px) scale(1.01);
  border-color: var(--pill-accent-border);
  color: var(--pill-accent);
  background: var(--pill-accent-soft);
  box-shadow: none;
}

.subtitle-toggle-pill:active {
  transform: scale(0.96);
}

.subtitle-toggle-pill.active {
  border-color: var(--pill-accent-border);
  background: var(--pill-accent-soft);
  color: #111827;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.76);
}

.header-badge {
  --badge-accent: #64748b;
  --badge-accent-soft: rgba(100, 116, 139, 0.12);
  --badge-accent-border: rgba(100, 116, 139, 0.24);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 9px;
  flex-shrink: 0;
  color: var(--badge-accent);
  background: var(--badge-accent-soft);
  border: 1px solid var(--badge-accent-border);
  box-shadow: none;
  transition: all 0.3s var(--ease-spring);
}

.header-badge-danger {
  background: #fff1f2;
  border-color: #fecdd3;
  color: #e11d48;
  box-shadow: none;
}

.header-badge-fetch {
  --badge-accent: #0284c7;
  --badge-accent-soft: rgba(14, 165, 233, 0.14);
  --badge-accent-border: rgba(2, 132, 199, 0.32);
}

.header-badge-filter {
  --badge-accent: #d97706;
  --badge-accent-soft: rgba(245, 158, 11, 0.16);
  --badge-accent-border: rgba(217, 119, 6, 0.34);
}

.header-badge-display {
  --badge-accent: #7c3aed;
  --badge-accent-soft: rgba(139, 92, 246, 0.15);
  --badge-accent-border: rgba(124, 58, 237, 0.32);
}

.subtitle-toggle-pill.tone-source {
  --pill-accent: #0284c7;
  --pill-accent-soft: rgba(14, 165, 233, 0.14);
  --pill-accent-border: rgba(2, 132, 199, 0.32);
}

.subtitle-toggle-pill.tone-written {
  --pill-accent: #059669;
  --pill-accent-soft: rgba(16, 185, 129, 0.14);
  --pill-accent-border: rgba(5, 150, 105, 0.32);
}

.subtitle-toggle-pill.tone-download {
  --pill-accent: #7c3aed;
  --pill-accent-soft: rgba(99, 102, 241, 0.14);
  --pill-accent-border: rgba(124, 58, 237, 0.34);
}

.subtitle-toggle-pill.tone-issue {
  --pill-accent: #d97706;
  --pill-accent-soft: rgba(245, 158, 11, 0.16);
  --pill-accent-border: rgba(217, 119, 6, 0.34);
}

.group\/card:hover .header-badge {
  transform: scale(1.06);
  box-shadow: none;
}

.group\/card:hover .header-badge-danger {
  box-shadow: 0 10px 20px rgba(244, 63, 94, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.subtitle-config-card :is(button, input):focus,
.subtitle-config-card :is(button, input):focus-visible,
.subtitle-config-card :focus-within {
  outline: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :is(
  .subtitle-stepper:hover,
  .subtitle-stepper:focus,
  .subtitle-stepper:focus-within,
  .subtitle-native-input:hover,
  .subtitle-native-input:focus,
  .subtitle-native-input:focus-visible
) {
  border-color: #cbd5e1 !important;
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :is(
  .header-badge,
  .search-chip,
  .subtitle-filter-index,
  .subtitle-filter-target-mini,
  .subtitle-filter-target-badge,
  .subtitle-filter-state
) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-naming-switch,
  .subtitle-filter-editor,
  .subtitle-filter-detail,
  .subtitle-filter-current-summary,
  .subtitle-retarget-option,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .search-row,
  .subtitle-stepper,
  .subtitle-stepper-btn,
  .subtitle-toggle-pill
) {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-naming-switch,
  .subtitle-filter-editor,
  .subtitle-filter-detail,
  .subtitle-filter-current-summary,
  .subtitle-retarget-option,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .search-row,
  .subtitle-stepper,
  .subtitle-stepper-btn,
  .subtitle-toggle-pill
):hover {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :deep(.app-dd-root),
.subtitle-config-card :deep(.app-dd-menu) {
  --app-dd-trigger-bg: #ffffff;
  --app-dd-trigger-bg-hover: #ffffff;
  --app-dd-trigger-bg-open: #ffffff;
  --app-dd-item-hover-bg: #ffffff;
  --app-dd-item-active-bg: #ffffff;
  --app-dd-item-active-hover-bg: #ffffff;
  --app-dd-focus-ring: transparent;
}

.subtitle-config-card :deep(.app-dd-trigger),
.subtitle-config-card :deep(.app-dd-trigger:hover),
.subtitle-config-card :deep(.app-dd-trigger.is-open) {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
  transform: none !important;
  outline: none !important;
}

.subtitle-config-card :is(
  .subtitle-naming-option.active,
  .subtitle-toggle-pill.active,
  .subtitle-retarget-option.active
) {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

.subtitle-config-card :is(
  .subtitle-tool-btn:hover:not(:disabled),
  .subtitle-retarget-option:hover,
  .subtitle-filter-current-card:hover,
  .subtitle-filter-nav-btn:hover:not(:disabled),
  .subtitle-filter-add-icon-btn:hover,
  .subtitle-filter-empty-add:hover,
  .subtitle-filter-editor-toggle:hover,
  .search-row:hover,
  .subtitle-toggle-pill:hover
) {
  background: #ffffff !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-config-card {
  color: rgba(244, 244, 245, 0.9);
}

:global(html.kikoerumanager-dark) .subtitle-switch {
  background: #34353a !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

.subtitle-toggle-pill span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(html.kikoerumanager-dark) .subtitle-switch.checked {
  background: var(--switch-accent) !important;
  border-color: var(--switch-accent-dark) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark) .subtitle-switch-knob {
  background: #f4f4f5 !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.22) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper,
:global(html.kikoerumanager-dark) .subtitle-native-input,
:global(html.kikoerumanager-dark) .subtitle-filter-target :deep(.app-dd-trigger) {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper-input,
:global(html.kikoerumanager-dark) .subtitle-native-input,
:global(html.kikoerumanager-dark) .subtitle-filter-target :deep(.app-dd-trigger-value) {
  color: rgba(244, 244, 245, 0.92) !important;
}

:global(html.kikoerumanager-dark) .subtitle-native-input::placeholder {
  color: rgba(214, 214, 220, 0.44) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper:hover,
:global(html.kikoerumanager-dark) .subtitle-stepper:focus-within,
:global(html.kikoerumanager-dark) .subtitle-native-input:hover,
:global(html.kikoerumanager-dark) .subtitle-native-input:focus,
:global(html.kikoerumanager-dark) .subtitle-filter-target :deep(.app-dd-trigger:hover) {
  border-color: rgba(255, 255, 255, 0.22) !important;
  background: #2d2e33 !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper-actions {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper-btn {
  background: #2b2c30 !important;
  color: rgba(214, 214, 220, 0.72) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper-btn:first-child {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

:global(html.kikoerumanager-dark) .subtitle-stepper-btn:hover {
  background: #333438 !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark) .subtitle-naming-switch,
:global(html.kikoerumanager-dark) .subtitle-ai-mode-switch,
:global(html.kikoerumanager-dark) .subtitle-settings-block,
:global(html.kikoerumanager-dark) .subtitle-filter-editor,
:global(html.kikoerumanager-dark) .subtitle-filter-detail,
:global(html.kikoerumanager-dark) .subtitle-filter-empty,
:global(html.kikoerumanager-dark) .subtitle-toggle-pill,
:global(html.kikoerumanager-dark) .search-row {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.32), rgba(18, 19, 23, 0.46)),
    rgba(22, 23, 27, 0.72) !important;
  background-image: linear-gradient(180deg, rgba(48, 49, 54, 0.32), rgba(18, 19, 23, 0.46)) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-help-card-danger {
  background:
    linear-gradient(180deg, rgba(70, 42, 46, 0.34), rgba(18, 19, 23, 0.48)),
    rgba(22, 23, 27, 0.72) !important;
  border-color: rgba(251, 113, 133, 0.22) !important;
}

:global(html.kikoerumanager-dark) .subtitle-settings-block:hover,
:global(html.kikoerumanager-dark) .subtitle-toggle-pill:hover,
:global(html.kikoerumanager-dark) .search-row:hover {
  background: #2d2e33 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-naming-option.active,
:global(html.kikoerumanager-dark) .subtitle-ai-mode-option.active,
:global(html.kikoerumanager-dark) .subtitle-toggle-pill.active {
  background: var(--option-accent-soft, var(--ai-option-soft, var(--pill-accent-soft, #45464b))) !important;
  background-image: none !important;
  border-color: var(--option-accent-border, var(--ai-option-border, var(--pill-accent-border, rgba(255, 255, 255, 0.34)))) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16) !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-current-card,
:global(html.kikoerumanager-dark) .subtitle-filter-nav-btn {
  background: #24252a !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-current-card:hover,
:global(html.kikoerumanager-dark) .subtitle-filter-nav-btn:hover:not(:disabled) {
  background: #303136 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark) .subtitle-naming-option {
  color: rgba(214, 214, 220, 0.72);
}

:global(html.kikoerumanager-dark) .subtitle-ai-mode-option {
  color: rgba(214, 214, 220, 0.72) !important;
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-naming-option:hover {
  background: var(--option-accent-soft);
  border-color: var(--option-accent-border);
  color: rgba(250, 250, 252, 0.96);
}

:global(html.kikoerumanager-dark) .subtitle-ai-mode-option:hover {
  background: var(--ai-option-soft) !important;
  background-image: none !important;
  border-color: var(--ai-option-border) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-tool-btn {
  background: #24252a !important;
  background-image: none !important;
  border-color: var(--tool-accent-border) !important;
  color: var(--tool-accent) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-tool-btn:hover:not(:disabled) {
  background: var(--tool-accent-soft) !important;
  background-image: none !important;
  border-color: var(--tool-accent-border) !important;
  color: var(--tool-accent) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-retarget-option {
  background: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-retarget-option.active,
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-retarget-option.active),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-retarget-option.active) {
  background: #303136 !important;
  background-color: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
  outline: 1px solid rgba(255, 255, 255, 0.14) !important;
  outline-offset: -1px !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-retarget-main {
  color: rgba(250, 250, 252, 0.94) !important;
}

:global(html.kikoerumanager-dark) .subtitle-retarget-path {
  color: rgba(214, 214, 220, 0.66) !important;
}

:global(html.kikoerumanager-dark) .subtitle-retarget-option.active .subtitle-retarget-main,
:global(html.kikoerumanager-dark) .subtitle-retarget-option.active .subtitle-retarget-path,
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-retarget-option.active .subtitle-retarget-main),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-retarget-option.active .subtitle-retarget-path),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-retarget-option.active .subtitle-retarget-main),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-retarget-option.active .subtitle-retarget-path) {
  color: #ffffff !important;
}

:global(html.kikoerumanager-dark) .subtitle-block-title,
:global(html.kikoerumanager-dark) .subtitle-option-title,
:global(html.kikoerumanager-dark) .subtitle-filter-detail-title,
:global(html.kikoerumanager-dark) .subtitle-filter-summary-title {
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark) .subtitle-block-tip,
:global(html.kikoerumanager-dark) .subtitle-card-tip,
:global(html.kikoerumanager-dark) .subtitle-filter-summary-pattern,
:global(html.kikoerumanager-dark) .subtitle-filter-field > span {
  color: rgba(214, 214, 220, 0.66) !important;
}

:global(html.kikoerumanager-dark) .subtitle-depth-control,
:global(html.kikoerumanager-dark) .subtitle-quick-toggle {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #24252a !important;
}

:global(html.kikoerumanager-dark) .subtitle-quick-label,
:global(html.kikoerumanager-dark) .subtitle-inline-section-tip {
  color: rgba(214, 214, 220, 0.72) !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-toggle-row {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-index,
:global(html.kikoerumanager-dark) .subtitle-filter-target-mini,
:global(html.kikoerumanager-dark) .subtitle-filter-target-badge,
:global(html.kikoerumanager-dark) .subtitle-filter-state,
:global(html.kikoerumanager-dark) .search-chip {
  background: #303136 !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-state.off {
  background: #24252a !important;
  color: rgba(214, 214, 220, 0.5) !important;
}

:global(html.kikoerumanager-dark) .stat-cell + .stat-cell::before {
  background: linear-gradient(180deg, transparent 0%, rgba(255, 255, 255, 0.12) 28%, rgba(255, 255, 255, 0.12) 72%, transparent 100%);
}

:global(html.kikoerumanager-dark) .header-badge {
  background: var(--badge-accent-soft) !important;
  border-color: var(--badge-accent-border) !important;
  color: var(--badge-accent) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .header-badge-danger {
  background: rgba(244, 63, 94, 0.16) !important;
  border-color: rgba(251, 113, 133, 0.26) !important;
  color: #fb7185 !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-add-btn,
:global(html.kikoerumanager-dark) .subtitle-filter-delete-btn,
:global(html.kikoerumanager-dark) .subtitle-config-card button[class*="bg-white"] {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-filter-add-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-filter-delete-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-config-card button[class*="bg-white"]:hover {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card) {
  color: rgba(244, 244, 245, 0.9) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-settings-block),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-naming-switch),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-ai-mode-switch),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-editor),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-detail),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-empty),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-toggle-pill),
:global(html.kikoerumanager-dark .subtitle-config-card .search-row) {
  background:
    linear-gradient(180deg, rgba(48, 49, 54, 0.32), rgba(18, 19, 23, 0.46)),
    rgba(22, 23, 27, 0.72) !important;
  background-image: linear-gradient(180deg, rgba(48, 49, 54, 0.32), rgba(18, 19, 23, 0.46)) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-editor),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-detail),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-current-summary) {
  background: #24252a !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-help-card-danger) {
  background:
    linear-gradient(180deg, rgba(70, 42, 46, 0.34), rgba(18, 19, 23, 0.48)),
    rgba(22, 23, 27, 0.72) !important;
  border-color: rgba(251, 113, 133, 0.22) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-naming-option.active),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-ai-mode-option.active),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-toggle-pill.active),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-retarget-option.active) {
  background: var(--option-accent-soft, var(--ai-option-soft, var(--pill-accent-soft, #56575e))) !important;
  background-image: none !important;
  border-color: var(--option-accent-border, var(--ai-option-border, var(--pill-accent-border, rgba(255, 255, 255, 0.42)))) !important;
  color: #ffffff !important;
  outline: 1px solid rgba(255, 255, 255, 0.2) !important;
  outline-offset: -1px !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-sky-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-sky-500) {
  color: #38bdf8 !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-violet-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-violet-500) {
  color: #a78bfa !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-emerald-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-emerald-500) {
  color: #34d399 !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-indigo-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-indigo-500) {
  color: #a78bfa !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-amber-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-amber-500) {
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .text-rose-600),
:global(html.kikoerumanager-dark .subtitle-config-card .text-rose-500) {
  color: #fb7185 !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-sky-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-sky-500) {
  color: #38bdf8 !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-violet-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-violet-500) {
  color: #a78bfa !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-emerald-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-emerald-500) {
  color: #34d399 !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-indigo-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-indigo-500) {
  color: #a78bfa !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-amber-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-amber-500) {
  color: #fbbf24 !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-rose-600),
:global(html.kikoerumanager-dark body #app .library .subtitle-config-card .text-rose-500) {
  color: #fb7185 !important;
  stroke: currentColor !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card button:not(.primary-cta, .subtitle-switch, .subtitle-naming-option, .subtitle-ai-mode-option, .subtitle-toggle-pill, .subtitle-tool-btn, .subtitle-retarget-option)) {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card button:not(.primary-cta, .subtitle-switch, .subtitle-naming-option, .subtitle-ai-mode-option, .subtitle-toggle-pill, .subtitle-tool-btn, .subtitle-retarget-option):hover) {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-naming-option.active),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-ai-mode-option.active),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-toggle-pill.active),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-retarget-option.active) {
  background: var(--option-accent-soft, var(--ai-option-soft, var(--pill-accent-soft, #56575e))) !important;
  background-color: var(--option-accent-soft, var(--ai-option-soft, var(--pill-accent-soft, #56575e))) !important;
  background-image: none !important;
  border-color: var(--option-accent-border, var(--ai-option-border, var(--pill-accent-border, rgba(255, 255, 255, 0.42)))) !important;
  color: #ffffff !important;
  outline: 1px solid rgba(255, 255, 255, 0.2) !important;
  outline-offset: -1px !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-stepper,
  .subtitle-stepper-input,
  .subtitle-stepper-btn,
  .subtitle-naming-switch,
  .subtitle-ai-mode-switch,
  .subtitle-toggle-pill,
  .subtitle-retarget-option,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .search-row
)) {
  background: #24252a !important;
  background-color: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-stepper,
  .subtitle-stepper-btn,
  .subtitle-toggle-pill,
  .subtitle-retarget-option,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .search-row
):hover),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper:focus-within) {
  background: #303136 !important;
  background-color: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-input) {
  background: transparent !important;
  background-color: transparent !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-actions),
:global(html.kikoerumanager-dark body #app .library .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn:first-child) {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-block-title),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-option-title),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-detail-title),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-summary-title) {
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-block-tip),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-card-tip),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-summary-pattern),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-current-pattern),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-field > span) {
  color: rgba(214, 214, 220, 0.66) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-current-name) {
  color: rgba(250, 250, 252, 0.92) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-depth-control),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-quick-toggle),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-editor),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-rule-strip),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-current-card),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-nav-btn),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-add-icon-btn),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-depth-control),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-quick-toggle),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-editor),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-rule-strip),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-current-card),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-nav-btn),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-add-icon-btn) {
  background: #24252a !important;
  background-color: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-depth-control:hover),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-quick-toggle:hover),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper:hover),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper:focus-within),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn:hover),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-current-card:hover),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-nav-btn:hover:not(:disabled)),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-add-icon-btn:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-depth-control:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-quick-toggle:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper:focus-within),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-current-card:hover),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-nav-btn:hover:not(:disabled)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-filter-add-icon-btn:hover) {
  background: #303136 !important;
  background-color: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-input),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-input) {
  background: transparent !important;
  background-color: transparent !important;
  background-image: none !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-actions),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn:first-child),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-actions),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-stepper-btn:first-child) {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-index),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-target-mini),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-target-badge),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-state),
:global(html.kikoerumanager-dark .subtitle-config-card .search-chip) {
  background: #303136 !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-current-card),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-nav-btn) {
  background: #24252a !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-current-card:hover),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-nav-btn:hover:not(:disabled)) {
  background: #303136 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-depth-control),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-quick-toggle) {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #24252a !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-quick-label),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-inline-section-tip) {
  color: rgba(214, 214, 220, 0.72) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-toggle-row) {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-stepper),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-native-input),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-target .app-dd-trigger) {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-stepper-input),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-native-input),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-target .app-dd-trigger-value) {
  color: rgba(244, 244, 245, 0.92) !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-add-btn),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-delete-btn),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-editor-toggle),
:global(html.kikoerumanager-dark .subtitle-config-card button[class*="bg-white"]) {
  background: #2b2c30 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-add-btn:hover),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-delete-btn:hover),
:global(html.kikoerumanager-dark .subtitle-config-card .subtitle-filter-editor-toggle:hover),
:global(html.kikoerumanager-dark .subtitle-config-card button[class*="bg-white"]:hover) {
  background: #333438 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-stepper,
  .subtitle-stepper-btn,
  .subtitle-naming-switch,
  .subtitle-ai-mode-switch,
  .subtitle-filter-editor,
  .subtitle-filter-detail,
  .subtitle-filter-current-summary,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .subtitle-filter-empty,
  .subtitle-retarget-option,
  .subtitle-toggle-pill,
  .search-row,
  .subtitle-native-input
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-depth-control,
  .subtitle-quick-toggle,
  .subtitle-stepper,
  .subtitle-stepper-btn,
  .subtitle-naming-switch,
  .subtitle-ai-mode-switch,
  .subtitle-filter-editor,
  .subtitle-filter-detail,
  .subtitle-filter-current-summary,
  .subtitle-filter-current-card,
  .subtitle-filter-nav-btn,
  .subtitle-filter-add-icon-btn,
  .subtitle-filter-empty-add,
  .subtitle-filter-empty,
  .subtitle-retarget-option,
  .subtitle-toggle-pill,
  .search-row,
  .subtitle-native-input
)) {
  background: #24252a !important;
  background-color: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-naming-option.active,
  .subtitle-ai-mode-option.active,
  .subtitle-toggle-pill.active,
  .subtitle-retarget-option.active
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-naming-option.active,
  .subtitle-ai-mode-option.active,
  .subtitle-toggle-pill.active,
  .subtitle-retarget-option.active
)) {
  background: rgba(59, 60, 66, 0.96) !important;
  background-color: rgba(59, 60, 66, 0.96) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  outline: none !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-naming-option:hover,
  .subtitle-ai-mode-option:hover,
  .subtitle-toggle-pill:hover,
  .subtitle-retarget-option:hover,
  .subtitle-stepper-btn:hover,
  .subtitle-filter-current-card:hover,
  .subtitle-filter-nav-btn:hover:not(:disabled),
  .subtitle-filter-add-icon-btn:hover,
  .subtitle-filter-empty-add:hover,
  .subtitle-filter-editor-toggle:hover,
  .search-row:hover
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-naming-option:hover,
  .subtitle-ai-mode-option:hover,
  .subtitle-toggle-pill:hover,
  .subtitle-retarget-option:hover,
  .subtitle-stepper-btn:hover,
  .subtitle-filter-current-card:hover,
  .subtitle-filter-nav-btn:hover:not(:disabled),
  .subtitle-filter-add-icon-btn:hover,
  .subtitle-filter-empty-add:hover,
  .subtitle-filter-editor-toggle:hover,
  .search-row:hover
)) {
  background: #303136 !important;
  background-color: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: rgba(250, 250, 252, 0.96) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch) {
  background: #34353a !important;
  background-color: #34353a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.18) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch.checked),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch.checked) {
  background: var(--switch-accent) !important;
  background-color: var(--switch-accent) !important;
  border-color: var(--switch-accent-dark) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch-knob),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card .subtitle-switch-knob) {
  background: #a7abb5 !important;
  background-color: #a7abb5 !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.28) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-block-title,
  .subtitle-option-title,
  .subtitle-filter-detail-title,
  .subtitle-filter-summary-title,
  .subtitle-filter-current-name,
  .subtitle-stepper-input,
  .subtitle-native-input
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-block-title,
  .subtitle-option-title,
  .subtitle-filter-detail-title,
  .subtitle-filter-summary-title,
  .subtitle-filter-current-name,
  .subtitle-stepper-input,
  .subtitle-native-input
)) {
  color: rgba(250, 250, 252, 0.96) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-block-tip,
  .subtitle-card-tip,
  .subtitle-quick-label,
  .subtitle-inline-section-tip,
  .subtitle-filter-summary-pattern,
  .subtitle-filter-current-pattern,
  .subtitle-filter-field > span
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-block-tip,
  .subtitle-card-tip,
  .subtitle-quick-label,
  .subtitle-inline-section-tip,
  .subtitle-filter-summary-pattern,
  .subtitle-filter-current-pattern,
  .subtitle-filter-field > span
)) {
  color: rgba(214, 214, 220, 0.66) !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-filter-index,
  .subtitle-filter-target-mini,
  .subtitle-filter-target-badge,
  .subtitle-filter-state,
  .search-chip
)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :is(
  .subtitle-filter-index,
  .subtitle-filter-target-mini,
  .subtitle-filter-target-badge,
  .subtitle-filter-state,
  .search-chip
)) {
  background: #303136 !important;
  background-color: #303136 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.82) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-root)),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-menu)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-root)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-menu)) {
  --app-dd-trigger-bg: #24252a;
  --app-dd-trigger-bg-hover: #303136;
  --app-dd-trigger-bg-open: #303136;
  --app-dd-item-hover-bg: #303136;
  --app-dd-item-active-bg: #3b3c42;
  --app-dd-item-active-hover-bg: #3b3c42;
  --app-dd-focus-ring: transparent;
}

:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger)),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger:hover)),
:global(html.kikoerumanager-dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger.is-open)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger:hover)),
:global(html.dark .subtitle-workbench-dialog .subtitle-config-card :deep(.app-dd-trigger.is-open)) {
  background: #24252a !important;
  background-color: #24252a !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: rgba(244, 244, 245, 0.9) !important;
  box-shadow: none !important;
}

@keyframes danger-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.08); }
}

@media (max-width: 960px) {
  .subtitle-pill-grid {
    grid-template-columns: 1fr;
  }

  .subtitle-filter-target {
    min-width: 0;
    max-width: none;
  }
}
</style>
