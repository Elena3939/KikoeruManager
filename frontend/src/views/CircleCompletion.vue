<template>
  <div class="circle-page">
    <AppPageHeader
      :icon="Tags"
      icon-color="#0f766e"
      title="社团补全"
      subtitle="按社团建立索引，结合 Kikoeru 收录态、DLsite 关联与 asmr.one 下载能力补全缺失作品"
      class="circle-page-header"
    >
      <div class="hero-search-wrap">
        <Search :size="13" class="hero-search-icon" />
        <el-input
          v-model="circleQuery"
          class="hero-search-input"
          placeholder="输入社团名，例如 こぐま座 / C_Realization"
          clearable
          @keyup.enter="handleIndexCircle"
        />
      </div>
      <el-button class="hero-btn hero-btn-primary" :loading="indexing" @click="handleIndexCircle">建立 / 刷新索引</el-button>
      <el-button class="hero-btn hero-btn-secondary" :disabled="indexing" @click="openBatchIndexPrompt">批量创建</el-button>
      <el-tooltip content="立即检查 DLsite 邮件，提取新作 RJ 号并触发社团补全索引" placement="bottom">
        <el-button
          class="hero-btn hero-btn-email"
          :loading="emailCheckLoading"
          @click="handleEmailCheck"
        >
          <Mail :size="13" style="margin-right:4px" />
          邮件检查
        </el-button>
      </el-tooltip>
    </AppPageHeader>

    <section v-if="indexJob.visible" class="index-progress-card">
      <div class="index-progress-head">
        <div>
          <div class="index-progress-title">索引进度</div>
          <div class="index-progress-subtitle">
            {{ indexJob.circle_query || circleQuery || '当前社团' }} · {{ indexJob.current_step || '处理中' }}
          </div>
        </div>
        <div class="index-progress-head-actions">
          <el-button
            v-if="canCancelIndexJob"
            size="small"
            class="index-cancel-button"
            :loading="cancellingIndexJob"
            @click="cancelIndexJob"
          >
            取消索引
          </el-button>
          <div class="index-progress-status" :class="indexJob.status">{{ indexJobStatusText }}</div>
        </div>
      </div>

      <div class="index-progress-bar-wrap">
        <AppLottieProgressBar :percentage="getJobProgressPercent(indexJob)" />
      </div>

      <div class="index-progress-meta">
        <span class="progress-meta-pill time" title="耗时"><Clock :size="10" /> {{ formatElapsed(indexJob.elapsed_seconds) }}</span>
        <span v-if="indexJob.meta?.is_batch" class="progress-meta-pill batch"><CheckCircle2 :size="10" /> {{ indexJob.meta.completed_queries || 0 }}/{{ indexJob.meta.batch_total || 0 }} 已完成</span>
        <span v-if="indexJob.meta?.is_batch && indexJob.meta.failed_queries" class="progress-meta-pill warn" title="失败数"><AlertCircle :size="10" /> {{ indexJob.meta.failed_queries }}</span>
        <span class="progress-meta-pill local" title="本地元数据缓存命中的候选作品"><HardDrive :size="10" /> 元数据 {{ indexJob.meta.local_candidates_count || 0 }}</span>
        <span class="progress-meta-pill kikoeru" title="Kikoeru候选"><Headphones :size="10" /> {{ indexJob.meta.kikoeru_candidates_count || 0 }}</span>
        <span class="progress-meta-pill dlsite" title="DLsite候选"><Globe :size="10" /> {{ indexJob.meta.dlsite_candidates_count || 0 }}</span>
        <span class="progress-meta-pill merged" title="合并候选"><List :size="10" /> {{ indexJob.meta.combined_candidates_count || indexJob.meta.aggregated_count || 0 }}</span>
        <span class="progress-meta-pill ok" title="可下载"><Download :size="10" /> {{ indexJob.meta.asmr_available_count || 0 }}</span>
      </div>

      <div v-if="indexJob.error_message" class="index-progress-error">{{ indexJob.error_message }}</div>
    </section>

    <section class="circle-shell">
      <aside class="circle-sidebar">
        <div class="sidebar-card">
          <div class="sidebar-head">
            <div>
              <div class="sidebar-overline">社团目录</div>
              <div class="sidebar-title">最近索引</div>
            </div>
            <el-button text class="sidebar-refresh-button" @click="loadRecentCircles">刷新</el-button>
          </div>
          <div class="sidebar-search">
            <el-input v-model="circleSearch" placeholder="筛选已缓存社团" clearable @input="searchCachedCircles" />
          </div>
          <div class="sidebar-filter-stack">
            <div class="sidebar-filter-group">
              <button type="button" class="sidebar-filter-chip" :class="{ active: circleCompletionFilter === 'all' }" @click="circleCompletionFilter = 'all'">全部</button>
              <button type="button" class="sidebar-filter-chip" :class="{ active: circleCompletionFilter === 'completed' }" @click="circleCompletionFilter = 'completed'">已补全</button>
              <button type="button" class="sidebar-filter-chip" :class="{ active: circleCompletionFilter === 'incomplete' }" @click="circleCompletionFilter = 'incomplete'">未补全</button>
              <button type="button" class="sidebar-filter-chip new-work" :class="{ active: circleCompletionFilter === 'new_works' }" @click="circleCompletionFilter = 'new_works'">✦ 新作</button>
            </div>
            <div class="sidebar-sort-row">
              <span class="sidebar-sort-label">排序</span>
              <AppDropdown
                v-model="circleSortKey"
                :options="circleSortKeyOptions"
                class="sidebar-sort-select"
                :width="140"
                :menu-min-width="170"
                :show-trigger-badge="false"
              />
            </div>
          </div>
          <div v-if="displayCircleList.length" class="circle-list">
            <button
              v-for="circle in displayCircleList"
              :key="circle.circle_id"
              type="button"
              class="circle-list-item"
              :class="{ active: activeCircleId === circle.circle_id }"
              @click="selectCircle(circle.circle_id)"
            >
              <div class="circle-list-header">
                <div class="circle-list-name">
                  <span>{{ circle.circle_name || circle.circle_id }}</span>
                  <span v-if="(circle.new_works_48h_count || 0) > 0" class="circle-inline-new-badge">NEW</span>
                </div>
                <div class="circle-list-id">{{ circle.circle_id }}</div>
              </div>
              <div class="circle-list-stats-row">
                <div class="circle-list-counts">
                  <span class="circle-stat-item total" title="DLsite作品数"><LibraryBig :size="10" /> {{ circle.dl_works || circle.total_works || 0 }}</span>
                  <span class="circle-stat-item owned" title="服务器已拥有"><Server :size="10" /> {{ circle.server_owned || 0 }}</span>
                  <span v-if="(circle.missing || 0) > 0" class="circle-stat-item missing" title="缺失"><XCircle :size="10" /> {{ circle.missing }}</span>
                </div>
                <span class="circle-list-status-pill" :class="getCircleCompletionState(circle)">
                  {{ getCircleCompletionState(circle) === 'completed' ? '已补全' : '未补全' }}
                </span>
              </div>
              <div class="circle-list-progress-container">
                <div class="circle-list-progress">
                  <div class="circle-list-progress-track">
                    <div class="circle-list-progress-fill" :style="{ width: `${getCircleOwnedPercent(circle)}%` }"></div>
                  </div>
                </div>
                <span class="circle-list-percent">{{ getCircleOwnedPercent(circle) }}%</span>
              </div>
              <div v-if="(circle.unreleased_count > 0) || (circle.new_works_48h_count > 0)" class="circle-list-tag-row">
                <span v-if="circle.unreleased_count > 0" class="circle-list-tag unreleased"><Calendar :size="9" /> {{ circle.unreleased_count }} 未发售</span>
                <span v-if="(circle.new_works_48h_count || 0) > 0" class="circle-list-tag new-work"><Mail :size="9" /> {{ circle.new_works_48h_count }} 新作</span>
              </div>
              <div v-if="circle.last_indexed_at" class="circle-list-refresh-row">
                <Clock :size="9" /> {{ formatDateTime(circle.last_indexed_at) }}
              </div>
            </button>
          </div>
          <AppEmptyState v-else :description="circleList.length ? '当前筛选条件下没有社团' : '还没有社团索引'" size="sm" />
        </div>
      </aside>

      <main class="circle-main">
        <section class="toolbar-card">
          <div class="toolbar-main">
            <div class="toolbar-copy">
              <div class="toolbar-title">{{ detail.circle_name || '未选择社团' }}</div>
              <div v-if="detail.last_indexed_at" class="toolbar-subtitle">上次刷新 {{ formatDateTime(detail.last_indexed_at) }}</div>
            </div>
            <div v-if="detail.works?.length" class="toolbar-actions">
              <el-button
                class="batch-action-button"
                :disabled="!activeCircleId || indexing || isRefreshJobActive"
                :loading="indexing"
                @click="handleIndexOnlyNewWorks"
              >
                仅索引新作
              </el-button>
              <el-button
                class="batch-action-button refresh"
                :disabled="!activeCircleId || indexing || isRefreshJobActive"
                :loading="refreshingCurrentCircle"
                @click="refreshSelectedCircleIndex"
              >
                批量刷新状态
              </el-button>
            </div>
          </div>

          <div class="toolbar-stats-row">
            <div class="toolbar-metrics">
              <span class="metric-pill owned"><CheckCircle2 :size="12" /> 已满足 {{ detail.owned_count || 0 }}</span>
              <span class="metric-pill warn"><XCircle :size="12" /> 缺失 {{ detail.missing_count || 0 }}</span>
              <span class="metric-pill ok"><Download :size="12" /> 可下载 {{ detail.downloadable_count || 0 }}</span>
              <span class="metric-pill muted"><MinusCircle :size="12" /> 暂不可下载 {{ detail.dl_only_count || 0 }}</span>
              <span v-if="unreleasedWorksCount > 0" class="metric-pill unreleased"><Calendar :size="12" /> 未发售 {{ unreleasedWorksCount }}</span>
              <span v-if="bonusWorksCount > 0" class="metric-pill bonus"><Gift :size="12" /> 特典 {{ bonusWorksCount }}</span>
              <span v-if="newWorksCount > 0" class="metric-pill new-work"><Mail :size="12" /> 新作 {{ newWorksCount }}</span>
            </div>
          </div>
          <div v-if="refreshForceRefreshHint" class="toolbar-subtext">{{ refreshForceRefreshHint }}</div>
        </section>

        <section v-if="activeCircleId" class="works-card">
          <section v-if="refreshJob.visible" class="index-progress-card refresh-progress-card">
            <div class="index-progress-head">
              <div>
                <div class="index-progress-title">批量刷新进度</div>
                <div class="index-progress-subtitle">
                  {{ refreshJob.circle_name || detail.circle_name || '当前社团' }} · {{ refreshJob.current_step || '处理中' }}
                </div>
              </div>
              <div class="index-progress-head-actions">
                <el-button
                  v-if="canCancelRefreshJob"
                  size="small"
                  class="index-cancel-button"
                  :loading="cancellingRefreshJob"
                  @click="cancelRefreshJob"
                >
                  取消刷新
                </el-button>
                <div class="index-progress-status" :class="refreshJob.status">{{ refreshJobStatusText }}</div>
              </div>
            </div>

            <div class="index-progress-bar-wrap">
              <AppLottieProgressBar :percentage="getJobProgressPercent(refreshJob)" size="sm" :show-text="false" />
            </div>

            <div class="index-progress-meta">
              <span class="progress-meta-pill time" title="耗时"><Clock :size="10" /> {{ formatElapsed(refreshJob.elapsed_seconds) }}</span>
              <span class="progress-meta-pill total" title="总数"><Hash :size="10" /> {{ refreshJob.selected_count || refreshJob.meta.total_count || 0 }}</span>
              <span class="progress-meta-pill batch" title="已处理"><CheckCircle2 :size="10" /> {{ refreshJob.meta.processed_count || 0 }}</span>
              <span class="progress-meta-pill changed" title="有变化"><Shuffle :size="10" /> {{ refreshJob.meta.changed_count || 0 }}</span>
              <span v-if="refreshJob.meta.force_refresh" class="progress-meta-pill warn"><AlertCircle :size="10" /> 强制刷新</span>
              <span class="progress-meta-pill kikoeru" title="Kikoeru已拥有"><Headphones :size="10" /> {{ refreshJob.meta.kikoeru_owned_count || 0 }}</span>
              <span class="progress-meta-pill ok" title="asmr.one可下载"><Download :size="10" /> {{ refreshJob.meta.asmr_available_count || 0 }}</span>
              <span v-if="refreshJob.meta.current_rjcode" class="progress-meta-pill current"><Hash :size="10" /> 当前 {{ refreshJob.meta.current_rjcode }}</span>
            </div>

            <div v-if="refreshJob.progress_log?.length" class="refresh-progress-log-list compact">
              <div
                v-for="entry in refreshJob.progress_log.slice(-2)"
                :key="`${refreshJob.job_id}-${entry.time}-${entry.message}`"
                class="refresh-progress-log-item"
                :class="entry.level || 'info'"
              >
                <span class="refresh-progress-log-time">{{ formatLogTime(entry.time) }}</span>
                <span class="refresh-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>
          </section>

          <div class="circle-tabs-wrapper">
            <div class="toolbar-right-actions">
              <button
                type="button"
                class="release-sort-button group"
                :title="worksReleaseSort === 'asc' ? '按发售时间正序' : '按发售时间倒序'"
                @click="toggleWorksReleaseSort"
              >
                <span class="release-sort-icon-stack">
                  <ArrowUpDown :size="13" class="release-sort-icon base" />
                  <ArrowUp v-if="worksReleaseSort === 'asc'" :size="13" class="release-sort-icon hover asc" />
                  <ArrowDown v-else :size="13" class="release-sort-icon hover desc" />
                </span>
                <span>发售时间</span>
                <ArrowUp v-if="worksReleaseSort === 'asc'" :size="12" class="release-sort-direction asc" />
                <ArrowDown v-else :size="12" class="release-sort-direction desc" />
              </button>
              <AppDropdown
                v-model="statusFilterModel"
                multiple
                :options="statusFilterOptions"
                placeholder="状态筛选"
                class="work-status-filter-dropdown"
                :width="148"
                :menu-min-width="216"
                :show-trigger-badge="false"
                menu-class="circle-status-filter-menu"
              >
                <template #trigger="{ open, toggle, hasSelection }">
                  <button
                    type="button"
                    class="status-filter-trigger"
                    :class="{ 'is-open': open, 'is-placeholder': !hasSelection, 'has-overflow': statusFilterOverflowCount > 0 }"
                    :title="statusFilterTriggerTitle"
                    @click="toggle"
                  >
                    <span
                      class="status-filter-trigger__content"
                      :class="{ 'has-overflow': statusFilterOverflowCount > 0 }"
                    >
                      <span v-if="selectedStatusFilterOptions.length" class="status-filter-trigger__tags">
                        <span
                          v-for="option in statusFilterVisibleOptions"
                          :key="option.value"
                          class="status-filter-token"
                        >{{ option.label }}</span>
                      </span>
                      <span v-else class="status-filter-trigger__placeholder">状态筛选</span>
                    </span>
                    <span v-if="statusFilterOverflowCount > 0" class="status-filter-overflow">+{{ statusFilterOverflowCount }}</span>
                    <ChevronDown
                      :size="13"
                      :stroke-width="2.4"
                      class="status-filter-trigger__caret"
                      :class="{ 'is-open': open }"
                    />
                  </button>
                </template>
                <template #option="{ option, isActive }">
                  <span class="status-filter-option">
                    <span class="status-filter-option__label">{{ option.label }}</span>
                    <span class="status-filter-option__meta">
                      <span class="status-filter-option__count">{{ option.suffix ?? 0 }}</span>
                      <Check
                        v-if="isActive"
                        :size="13"
                        :stroke-width="2.6"
                        class="status-filter-option__check"
                      />
                    </span>
                  </span>
                </template>
              </AppDropdown>
              <div class="view-toggle-group">
                <button type="button" class="view-toggle-btn" :class="{ active: viewMode === 'card' }" title="卡片视图" @click="viewMode = 'card'"><LayoutGrid :size="14" /></button>
                <button type="button" class="view-toggle-btn" :class="{ active: viewMode === 'list' }" title="列表视图" @click="viewMode = 'list'"><List :size="14" /></button>
              </div>
            </div>
            <el-tabs v-model="activeTab" class="circle-tabs">
            <el-tab-pane name="missing">
              <template #label>
                <span class="circle-tab-label"><XCircle :size="13" class="circle-tab-icon missing" /> 缺失作品 <em class="circle-tab-badge missing">{{ missingWorksTotal }}</em></span>
              </template>

              <div v-if="missingWorks.length > 0 && selectedActiveCanonicalRJCodes.length > 0" class="flex items-center justify-between bg-slate-50/80 border border-slate-200/80 rounded-xl px-4 py-3 mb-4 mt-2 shadow-sm backdrop-blur-sm">
                <span class="text-sm font-medium text-slate-700">已选 {{ selectedActiveCanonicalRJCodes.length }} / {{ activeSelectableWorks.length }}</span>
                <div class="flex items-center gap-2">
                  <button type="button" class="batch-action-button" @click="selectAllVisibleWorks">全选</button>
                  <button type="button" class="batch-action-button ghost" @click="clearSelection">清空</button>
                  <button
                    type="button"
                    class="batch-action-button refresh"
                    :class="{ 'is-busy': refreshingCurrentCircle }"
                    :disabled="isRefreshJobActive"
                    @click="refreshSelectedCircleIndex(selectedActiveCanonicalRJCodes)"
                  >
                    <RefreshCw v-if="refreshingCurrentCircle" :size="13" class="batch-action-spinner" />
                    刷新状态
                  </button>
                  <button
                    type="button"
                    class="batch-action-button primary ml-2"
                    :class="{ 'is-busy': previewing }"
                    :disabled="selectedActiveDownloadableRJCodes.length === 0"
                    @click="openBatchPreview()"
                  >
                    <Download v-if="!previewing" :size="13" />
                    <RefreshCw v-else :size="13" class="batch-action-spinner" />
                    下载选中项
                  </button>
                </div>
              </div>

              <div v-if="showMissingWorksCompleteState" class="circle-complete-state">
                <div class="circle-complete-visual">
                  <Transition name="complete-confetti">
                    <div v-if="showCompleteConfetti" class="circle-complete-confetti" aria-hidden="true">
                      <DotLottieVue
                        class="circle-complete-confetti-player"
                        :src="confettiAnimation"
                        autoplay
                      />
                    </div>
                  </Transition>
                  <img
                    :src="celebrateImg"
                    class="circle-complete-image"
                    :class="{ 'is-revealed': revealCompletePoster }"
                    alt="已全部收集完成"
                  />
                </div>
                <div class="circle-complete-copy">
                  <div class="circle-complete-stats">
                    <span class="circle-complete-pill owned">补全已满足 {{ detail.owned_count || 0 }}</span>
                  </div>
                </div>
              </div>
              <div v-else-if="circleDetailLoading" class="circle-works-loading-state">
                <AppLoadingAnimation
                  label="正在刷新社团作品状态"
                  description="正在同步缺失作品、服务器拥有态和可下载信息"
                  :size="176"
                  :min-height="280"
                />
              </div>
              <AppEmptyState
                v-else-if="missingWorksTotal > 0 && missingWorks.length === 0"
                description="存在缺失记录，但当前没有可展示的首选版本"
                size="lg"
                class="circle-empty-state"
              />
              <CircleWorksViewport
                v-else
                v-model:current-page="missingPage"
                v-model:page-size="worksPageSize"
                :items="missingWorks"
                :mode="viewMode"
                :page-sizes="worksPageSizes"
                :selected-codes="selectedCanonicals"
                :flashed-codes="flashedWorkCodes"
                image-field="thumb_image_url"
                pager-label="缺失作品"
                @select="toggleSelection"
                @preview="openBatchPreview"
                @reimport="openReimportDialogForWork"
              />
            </el-tab-pane>

            <el-tab-pane name="owned">
              <template #label>
                <span class="circle-tab-label"><CheckCircle2 :size="13" class="circle-tab-icon owned" /> 已满足 <em class="circle-tab-badge owned">{{ detail.owned_count || 0 }}</em></span>
              </template>
              <!-- Header Stats & Actions -->
              <div class="owned-panel mb-4 space-y-4">
                <div class="owned-stats-strip flex items-center justify-between bg-white rounded-xl border border-slate-200/60 p-1.5 shadow-sm">
                  <div class="owned-stats-list flex items-center divide-x divide-slate-200/60">
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-slate-50 border border-slate-100/50 flex items-center justify-center text-slate-500">
                        <LibraryBig :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">总收录</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.total }}</span>
                      </div>
                    </div>
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-sky-50 border border-sky-100/50 flex items-center justify-center text-sky-500">
                        <Languages :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">简中</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.simplified }}</span>
                      </div>
                    </div>
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-violet-50 border border-violet-100/50 flex items-center justify-center text-violet-500">
                        <Languages :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">繁中</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.traditional }}</span>
                      </div>
                    </div>
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-slate-100 border border-slate-200/50 flex items-center justify-center text-slate-600">
                        <PlayCircle :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">原作</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.original }}</span>
                      </div>
                    </div>
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-indigo-50 border border-indigo-100/50 flex items-center justify-center text-indigo-500">
                        <Subtitles :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">含字幕</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.subtitle }}</span>
                      </div>
                    </div>
                    <div class="px-4 py-2 flex items-center gap-2.5">
                      <div class="w-7 h-7 rounded-full bg-purple-50 border border-purple-100/50 flex items-center justify-center text-purple-600">
                        <Gift :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">特典</span>
                        <span class="text-[15px] font-bold text-slate-800 leading-none">{{ ownedWorksStats.bonus }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="owned-filter-row flex items-center justify-between gap-4">
                  <div class="owned-filter-tabs flex bg-white rounded-lg border border-slate-200/60 p-1 shadow-sm">
                    <button type="button" class="owned-filter-chip" :class="{ 'is-active': ownedWorksFilterType === 'all' }" @click="setOwnedWorksFilter('all')">
                      全部
                      <span class="owned-filter-count">{{ ownedWorksStats.total }}</span>
                    </button>
                    <button type="button" class="owned-filter-chip" :class="{ 'is-active': ownedWorksFilterType === 'original' }" @click="setOwnedWorksFilter('original')">
                      仅原作
                      <span class="owned-filter-count">{{ ownedWorksStats.original }}</span>
                    </button>
                    <button type="button" class="owned-filter-chip is-simplified" :class="{ 'is-active': ownedWorksFilterType === 'simplified' }" @click="setOwnedWorksFilter('simplified')">
                      简中
                      <span class="owned-filter-count">{{ ownedWorksStats.simplified }}</span>
                    </button>
                    <button type="button" class="owned-filter-chip is-traditional" :class="{ 'is-active': ownedWorksFilterType === 'traditional' }" @click="setOwnedWorksFilter('traditional')">
                      繁中
                      <span class="owned-filter-count">{{ ownedWorksStats.traditional }}</span>
                    </button>
                    <button type="button" class="owned-filter-chip is-subtitle" :class="{ 'is-active': ownedWorksFilterType === 'subtitle' }" @click="setOwnedWorksFilter('subtitle')">
                      <MessageSquareText :size="14" stroke-width="2.5" />
                      字幕
                      <span class="owned-filter-count">{{ ownedWorksStats.subtitle }}</span>
                    </button>
                    <button type="button" class="owned-filter-chip is-bonus" :class="{ 'is-active': ownedWorksFilterType === 'bonus' }" @click="setOwnedWorksFilter('bonus')">
                      <Gift :size="14" stroke-width="2.5" />
                      特典
                      <span class="owned-filter-count">{{ ownedWorksStats.bonus }}</span>
                    </button>
                  </div>

                  <div class="flex items-center gap-3">
                    <button
                      type="button"
                      class="release-sort-button group"
                      :title="worksReleaseSort === 'asc' ? '按发售时间正序' : '按发售时间倒序'"
                      @click="toggleWorksReleaseSort"
                    >
                      <span class="release-sort-icon-stack">
                        <ArrowUpDown :size="13" class="release-sort-icon base" />
                        <ArrowUp v-if="worksReleaseSort === 'asc'" :size="13" class="release-sort-icon hover asc" />
                        <ArrowDown v-else :size="13" class="release-sort-icon hover desc" />
                      </span>
                      <span>发售时间</span>
                      <ArrowUp v-if="worksReleaseSort === 'asc'" :size="12" class="release-sort-direction asc" />
                      <ArrowDown v-else :size="12" class="release-sort-direction desc" />
                    </button>

                    <div class="owned-search-wrap relative w-64">
                    <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Search :size="16" class="text-slate-400" />
                    </div>
                    <input 
                      v-model="ownedWorksSearchQuery" 
                      type="text" 
                      class="block w-full pl-9 pr-3 py-2 border border-slate-200/60 rounded-lg text-sm bg-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400/20 focus:border-slate-400 transition-all shadow-sm" 
                      placeholder="搜索作品名或 RJ 号..." 
                    />
                    <button 
                      v-if="ownedWorksSearchQuery" 
                      @click="ownedWorksSearchQuery = ''" 
                      class="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600"
                    >
                      <X :size="14" />
                    </button>
                  </div>
                </div>
              </div>
              </div>

              <!-- List -->
              <!-- 改成和"缺失作品" tab 一样的双模式（card / list），共用 viewMode 开关，
                   保持上面 stats / 筛选 chip / 搜索框不变。已满足作品默认走 cornerLabel
                   = "已收录" 让卡片角标和原配色（绿色）统一。 -->
              <template v-if="circleDetailLoading && !circleDetailLoaded">
                <div class="circle-works-loading-state">
                  <AppLoadingAnimation
                    label="正在切换社团作品"
                    description="先展示当前社团摘要，作品列表马上补齐"
                    :size="176"
                    :min-height="280"
                  />
                </div>
              </template>
              <template v-else-if="ownedWorks.length === 0">
                <div class="flex flex-col items-center justify-center py-12 text-slate-400 bg-white/50 rounded-xl border border-slate-200/50 border-dashed">
                  <LibraryBig :size="32" class="mb-3 opacity-40" />
                  <p class="text-sm font-medium">没有找到符合条件的作品</p>
                </div>
              </template>
              <template v-else>
                <div v-if="ownedWorks.length > 0 && selectedActiveCanonicalRJCodes.length > 0" class="flex items-center justify-between bg-slate-50/80 border border-slate-200/80 rounded-xl px-4 py-3 mb-4 mt-2 shadow-sm backdrop-blur-sm">
                  <span class="text-sm font-medium text-slate-700">已选 {{ selectedActiveCanonicalRJCodes.length }} / {{ activeSelectableWorks.length }}</span>
                  <div class="flex items-center gap-2">
                    <button type="button" class="batch-action-button" @click="selectAllVisibleWorks">全选</button>
                    <button type="button" class="batch-action-button ghost" @click="clearSelection">清空</button>
                    <button
                      type="button"
                      class="batch-action-button refresh"
                      :class="{ 'is-busy': refreshingCurrentCircle }"
                      :disabled="isRefreshJobActive"
                      @click="refreshSelectedCircleIndex(selectedActiveCanonicalRJCodes)"
                    >
                      <RefreshCw v-if="refreshingCurrentCircle" :size="13" class="batch-action-spinner" />
                      刷新状态
                    </button>
                  </div>
                </div>
                <CircleWorksViewport
                  v-model:current-page="ownedPage"
                  v-model:page-size="worksPageSize"
                  :items="ownedWorks"
                  :mode="viewMode"
                  :page-sizes="worksPageSizes"
                  :selected-codes="selectedCanonicals"
                  :flashed-codes="flashedWorkCodes"
                  image-field="thumb_image_url"
                  corner-label="已收录"
                  pager-label="已满足作品"
                  @select="toggleSelection"
                  @preview="openBatchPreview"
                  @reimport="openReimportDialogForWork"
                />
              </template>
            </el-tab-pane>

            <el-tab-pane name="compare">
              <template #label>
                <span class="circle-tab-label"><Layers :size="13" class="circle-tab-icon" /> 来源对比</span>
              </template>
              <!-- Stats Row -->
              <div class="compare-panel mb-4">
                <div class="compare-stats-list bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden flex flex-wrap divide-x divide-slate-100">
                  <div class="px-4 py-2 flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-full bg-slate-50 border border-slate-100/50 flex items-center justify-center text-slate-500">
                      <LibraryBig :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">总数</span>
                      <span class="text-[15px] font-bold text-slate-800 leading-none">{{ compareWorksStats.total }}</span>
                    </div>
                  </div>
                  <div class="px-4 py-2 flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-full bg-emerald-50 border border-emerald-100/50 flex items-center justify-center text-emerald-500">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Kikoeru</span>
                      <span class="text-[15px] font-bold text-slate-800 leading-none">{{ compareWorksStats.kikoeru }}</span>
                    </div>
                  </div>
                  <div class="px-4 py-2 flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-full bg-blue-50 border border-blue-100/50 flex items-center justify-center text-blue-500">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">DLsite</span>
                      <span class="text-[15px] font-bold text-slate-800 leading-none">{{ compareWorksStats.dlsite }}</span>
                    </div>
                  </div>
                  <div class="px-4 py-2 flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-full bg-violet-50 border border-violet-100/50 flex items-center justify-center text-violet-500">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">ASMR.ONE</span>
                      <span class="text-[15px] font-bold text-slate-800 leading-none">{{ compareWorksStats.asmr_one }}</span>
                    </div>
                  </div>
                  <div class="px-4 py-2 flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-full bg-rose-50 border border-rose-100/50 flex items-center justify-center text-rose-500">
                      <XCircle :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">暂无来源</span>
                      <span class="text-[15px] font-bold text-slate-800 leading-none">{{ compareWorksStats.missing }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Actions Toolbar -->
              <div class="compare-filter-row flex items-center justify-between mb-4">
                <div class="compare-filter-tabs flex bg-white rounded-lg border border-slate-200/60 p-1 shadow-sm">
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'all' ? 'bg-slate-800 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'all'; comparePage = 1">全部</button>
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'kikoeru' ? 'bg-emerald-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'kikoeru'; comparePage = 1">已拥有(Kikoeru)</button>
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'asmr_one' ? 'bg-indigo-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'asmr_one'; comparePage = 1">可下载(ASMR.ONE)</button>
                </div>

                <div class="flex items-center gap-3">
                  <button
                    type="button"
                    class="release-sort-button group"
                    :title="worksReleaseSort === 'asc' ? '按发售时间正序' : '按发售时间倒序'"
                    @click="toggleWorksReleaseSort"
                  >
                    <span class="release-sort-icon-stack">
                      <ArrowUpDown :size="13" class="release-sort-icon base" />
                      <ArrowUp v-if="worksReleaseSort === 'asc'" :size="13" class="release-sort-icon hover asc" />
                      <ArrowDown v-else :size="13" class="release-sort-icon hover desc" />
                    </span>
                    <span>发售时间</span>
                    <ArrowUp v-if="worksReleaseSort === 'asc'" :size="12" class="release-sort-direction asc" />
                    <ArrowDown v-else :size="12" class="release-sort-direction desc" />
                  </button>

                  <div class="compare-search-wrap relative w-64">
                  <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Search :size="16" class="text-slate-400" />
                  </div>
                  <input 
                    v-model="compareSearchQuery" 
                    type="text" 
                    @input="comparePage = 1"
                    class="block w-full pl-9 pr-3 py-2 border border-slate-200/60 rounded-lg text-sm bg-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400/20 focus:border-slate-400 transition-all shadow-sm" 
                    placeholder="搜索作品名或 RJ 号..." 
                  />
                  <button 
                    v-if="compareSearchQuery" 
                    @click="compareSearchQuery = ''; comparePage = 1" 
                    class="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600"
                  >
                    <X :size="14" />
                  </button>
                </div>
                </div>
              </div>

              <!-- Header -->
              <div class="compare-head flex items-center gap-4 px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 border border-slate-200/60 rounded-t-lg">
                <div class="flex-1">资源信息</div>
                <div class="flex items-center gap-4 shrink-0 text-center">
                  <div class="w-20">Kikoeru</div>
                  <div class="w-px h-4 bg-transparent"></div>
                  <div class="w-20">DLsite</div>
                  <div class="w-px h-4 bg-transparent"></div>
                  <div class="w-20">ASMR.ONE</div>
                </div>
              </div>

              <!-- List -->
              <div class="compare-works-list border-x border-b border-slate-200/60 rounded-b-lg mb-4 divide-y divide-slate-100/80 bg-white" v-auto-animate>
                <div v-for="item in pagedCompareWorks" :key="`compare-${item.workRjcode}`" class="compare-work-item p-4 hover:bg-slate-50/50 transition-colors">
                  <div class="compare-work-row flex items-start justify-between gap-4">
                    <!-- Title & Badges -->
                    <div class="compare-work-main flex-1 min-w-0">
                      <h4 class="compare-work-title text-[14px] font-semibold text-slate-800 truncate mb-1.5" :title="item.title || item.workRjcode || '未命名作品'">{{ item.title || item.workRjcode || '未命名作品' }}</h4>
                      <div class="compare-work-tags flex items-center gap-2">
                        <!-- Status Badge -->
                        <span v-if="item.statusKey === 'owned'" class="inline-flex items-center gap-1 text-emerald-600 text-xs font-medium" title="服务器已拥有">
                          <CheckCircle2 :size="14" stroke-width="2.5" />
                          已拥有
                        </span>
                        <span v-else-if="item.statusKey === 'missing'" class="inline-flex items-center gap-1 text-rose-500 text-xs font-medium" title="未拥有">
                          <XCircle :size="14" stroke-width="2.5" />
                          未拥有
                        </span>
                        <span v-else-if="item.statusKey === 'partial'" class="inline-flex items-center gap-1 text-amber-500 text-xs font-medium" title="部分拥有">
                          <AlertCircle :size="14" stroke-width="2.5" />
                          部分拥有
                        </span>
                        <span v-else class="inline-flex items-center gap-1 text-slate-500 text-xs font-medium">
                          <MinusCircle :size="14" stroke-width="2.5" />
                          {{ item.statusLabel }}
                        </span>

                        <span class="text-xs font-mono font-medium text-slate-600">{{ item.workRjcode || '—' }}</span>

                        <!-- Variant Tags -->
                        <span v-if="item.preferredVariantLabel && item.preferredVariantLabel !== '—'" class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold" :class="[
                          item.preferredVariantLabel === '简中' ? 'text-sky-600 bg-sky-50 border border-sky-100' :
                          item.preferredVariantLabel === '繁中' ? 'text-violet-600 bg-violet-50 border border-violet-100' :
                          item.preferredVariantLabel === '原作' ? 'text-slate-600 bg-slate-100 border border-slate-200' :
                          'text-slate-600 bg-slate-50 border border-slate-200'
                        ]">
                          {{ item.preferredVariantLabel }}
                        </span>

                        <!-- Subtitle Icon (if kikoeru tags contain 字幕) -->
                        <span v-if="normalizeKikoeruTags(item.sourceCompare.kikoeru.tags).includes('字幕')" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold text-indigo-600 bg-indigo-50 border border-indigo-100">
                          <MessageSquareText :size="12" stroke-width="2.5" />
                          字幕
                        </span>
                      </div>
                    </div>

                    <!-- Source Info -->
                    <div class="compare-source-cols flex items-center gap-4 text-xs shrink-0 mt-0.5">
                      <!-- Kikoeru -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <span v-if="item.sourceCompare.kikoeru.primary_rjcode" class="font-mono text-slate-700">{{ item.sourceCompare.kikoeru.primary_rjcode }}</span>
                        <span v-else class="text-slate-400 scale-90">—</span>
                        <div v-if="item.sourceCompare.kikoeru.variantBadges.length || normalizeKikoeruTags(item.sourceCompare.kikoeru.tags).length" class="flex flex-wrap items-center justify-center gap-1 mt-0.5">
                          <span v-for="badge in item.sourceCompare.kikoeru.variantBadges" :key="`kb-${item.workRjcode}-${badge}`" class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-bold leading-none" :class="[
                            badge === '简中' ? 'text-sky-600 bg-sky-50 border border-sky-100' :
                            badge === '繁中' ? 'text-violet-600 bg-violet-50 border border-violet-100' :
                            badge === '原作' ? 'text-slate-600 bg-slate-100 border border-slate-200' :
                            'text-slate-500 bg-slate-50 border border-slate-200'
                          ]">{{ badge }}</span>
                        </div>
                      </div>
                      
                      <div class="w-px h-6 bg-slate-200/60"></div>
                      
                      <!-- DLsite -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <div v-if="item.sourceCompare.dlsite.all_rjcodes.length" class="flex flex-col items-center gap-0.5">
                          <span v-for="code in item.sourceCompare.dlsite.all_rjcodes" :key="`d-${item.workRjcode}-${code}`" class="font-mono text-slate-700">{{ code }}</span>
                        </div>
                        <span v-else class="text-slate-400 scale-90">—</span>
                      </div>
                      
                      <div class="w-px h-6 bg-slate-200/60"></div>

                      <!-- ASMR.ONE -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <div v-if="item.sourceCompare.asmr_one.primary_rjcode" class="flex flex-col items-center">
                          <span class="font-mono text-slate-700">{{ item.sourceCompare.asmr_one.primary_rjcode }}</span>
                          <span v-if="item.sourceCompare.asmr_one.primaryBadge" class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-bold leading-none mt-0.5" :class="[
                            item.sourceCompare.asmr_one.primaryBadge === '简中' ? 'text-sky-600 bg-sky-50 border border-sky-100' :
                            item.sourceCompare.asmr_one.primaryBadge === '繁中' ? 'text-violet-600 bg-violet-50 border border-violet-100' :
                            item.sourceCompare.asmr_one.primaryBadge === '原作' ? 'text-slate-600 bg-slate-100 border border-slate-200' :
                            'text-slate-500 bg-slate-50 border border-slate-200'
                          ]">{{ item.sourceCompare.asmr_one.primaryBadge }}</span>
                        </div>
                        <span v-else class="text-slate-400 scale-90">—</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="comparePage"
                  v-model:page-size="comparePageSize"
                  :page-sizes="comparePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="compareWorksFilteredCount"
                  background
                />
              </div>
            </el-tab-pane>

            <el-tab-pane name="info">
              <template #label>
                <span class="circle-tab-label"><Info :size="13" class="circle-tab-icon" /> 索引信息</span>
              </template>
              <div class="info-grid">
                <div class="info-card">
                  <div class="info-label">社团ID</div>
                  <div class="info-value">{{ detail.circle_id || '—' }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">最近索引</div>
                  <div class="info-value">{{ formatDateTime(detail.last_indexed_at) }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">来源标记</div>
                  <div class="info-value">{{ detail.source_mask || '—' }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">可见作品</div>
                  <div class="info-value">{{ detail.works?.length || 0 }}</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
        </section>

        <AppEmptyState v-else description="先建立一个社团索引" size="lg" class="circle-empty-state" />
      </main>
    </section>

    <CircleDownloadPreviewDialog
      v-model:visible="previewDialogVisible"
      :loading="previewLoading"
      :starting="starting"
      :plans="previewPlans"
      :libraries="libraries"
      :target-subdir-options="targetSubdirOptions"
      :settings="downloadSettings"
      :circle-name="detail.circle_name"
      @submit="startBatchDownload"
    />

    <ServerUploadPreviewDialog
      :visible="localUploadDialogVisible"
      :starting="localUploadSubmitting"
      title="直接入库"
      :source-library-id="''"
      :source-library-name="detail.circle_name || ''"
      :circle-name="localUploadPreviewCircleName"
      :source-items="localUploadSourceItems"
      :libraries="libraries"
      :initial-target-library-id="localUploadForm.targetLibraryId"
      :initial-target-subdir="localUploadForm.targetSubdir"
      @update:visible="value => localUploadDialogVisible = value"
      @submit="submitLocalUpload"
    />

    <DownloadTaskWorkbenchDialog
      v-model:visible="downloadWorkbenchVisible"
      :tasks="trackedDownloadTasks"
      :refreshing="downloadWorkbenchRefreshing"
      :retrying-keys="[...retryingTaskIds]"
      @refresh="refreshDownloadWorkbench({ silent: true })"
      @background="hideDownloadWorkbenchToBackground"
      @close="closeDownloadWorkbench"
      @retry-task="retryDownloadTask"
      @retry-waiting="retryWaitingDownloadTask"
      @retry-file="handleRetrySingleFailedFile"
      @reimport-task="openLocalUploadDialogForTask"
      @pause-task="handlePauseDownloadTask"
      @resume-task="handleResumeDownloadTask"
      @cancel-task="handleCancelDownloadTask"
    />

    <UploadTaskWorkbenchDialog
      v-model:visible="uploadWorkbenchVisible"
      :tasks="trackedUploadTasks"
      :refreshing="uploadWorkbenchRefreshing"
      @refresh="refreshUploadWorkbench"
      @background="hideUploadWorkbenchToBackground"
      @close="closeUploadWorkbench"
    />

    <Transition name="floating-card">
      <BackgroundFloatingCard
        v-if="showDownloadBackgroundCard"
        v-bind="downloadBackgroundCardProps"
        @action="handleDownloadBackgroundCardAction"
      />
    </Transition>

    <Transition name="floating-card">
      <BackgroundFloatingCard
        v-if="showUploadBackgroundCard"
        v-bind="uploadBackgroundCardProps"
        :stack-index="showDownloadBackgroundCard ? 1 : 0"
        @action="handleUploadBackgroundCardAction"
      />
    </Transition>

  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import celebrateImg from '../assets/celebrate.png'
import confettiAnimation from '../assets/anime/Confetti.lottie'
import { Check, CheckCircle2, ChevronDown, Tags, MessageSquareText, Search, LibraryBig, Languages, PlayCircle, Subtitles, X, FileText, XCircle, AlertCircle, MinusCircle, Server, Clock, HardDrive, Globe, List, LayoutGrid, Download, Headphones, Hash, Shuffle, Layers, Info, ArrowUpDown, ArrowUp, ArrowDown, Mail, Calendar, Gift, RefreshCw, BarChart3, Timer, Upload } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api, { asmrSyncApi, circleCompletionApi, emailWatcherApi, libraryApi, localUploadApi, taskApi } from '../api'
import CircleDownloadPreviewDialog from '../components/circle/CircleDownloadPreviewDialog.vue'
import DownloadTaskWorkbenchDialog from '../components/download/DownloadTaskWorkbenchDialog.vue'
import ServerUploadPreviewDialog from '../components/common/ServerUploadPreviewDialog.vue'
import UploadTaskWorkbenchDialog from '../components/upload/UploadTaskWorkbenchDialog.vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import BackgroundFloatingCard from '../components/common/BackgroundFloatingCard.vue'
import CircleWorksViewport from '../components/circle/CircleWorksViewport.vue'
import { showSystemConfirm, showSystemPrompt } from '../composables/useSystemPrompt'

const CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY = 'kikoerumanager.circleCompletion.targetSubdirs'
const CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.downloadWorkbench'
const CIRCLE_COMPLETION_REFRESH_JOB_KEY = 'kikoerumanager.circleCompletion.refreshJob'
const CIRCLE_COMPLETION_INDEX_JOB_KEY = 'kikoerumanager.circleCompletion.indexJob'
const CIRCLE_COMPLETION_UPLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.uploadWorkbench'
function getJobProgressPercent(job) {
  const value = Number(job?.progress || 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

const circleQuery = ref('')
const circleSearch = ref('')
const circleSearchRequestSeq = ref(0)
const circleCompletionFilter = ref('all')
const circleSortKey = ref('refreshed_at')

// 侧边栏「排序」下拉选项
const circleSortKeyOptions = [
  { value: 'completion', label: '收集程度' },
  { value: 'refreshed_at', label: '刷新时间' },
  { value: 'works', label: '作品数量' },
  { value: 'missing', label: '缺失数量' },
  { value: 'owned', label: '服务器拥有数量' },
]
const indexing = ref(false)
const emailCheckLoading = ref(false)
const previewing = ref(false)
const previewLoading = ref(false)
const starting = ref(false)
const activeCircleId = ref('')
const circleDetailLoading = ref(false)
const circleDetailLoaded = ref(false)
const circleList = ref([])
const detail = reactive({
  circle_id: '',
  circle_name: '',
  source_mask: '',
  last_indexed_at: '',
  owned_count: 0,
  missing_count: 0,
  downloadable_count: 0,
  dl_only_count: 0,
  works: []
})
const CIRCLE_DETAIL_CACHE_TTL = 5 * 60 * 1000
const CIRCLE_DETAIL_PREFETCH_LIMIT = 2
const circleDetailCache = new Map()
let circleDetailRequestSeq = 0
let circleDetailAbortController = null
let circleDetailPrefetchTimer = null
let circleDetailPrefetchRunning = false
const filters = reactive({
  onlyMissing: false,
  onlyDownloadable: false,
  includeDlOnly: true
})
const statusFilters = ref([])
const statusFilterBaseOptions = [
  { value: 'repairable', label: '可补配' },
  { value: 'downloadable', label: '可下载' },
  { value: 'missing', label: '未收录' },
  { value: 'no_source', label: '无源' },
]
const statusFilterExclusiveGroups = [
  ['downloadable', 'no_source'],
  ['repairable', 'missing'],
]
const statusFilterOptions = computed(() => {
  const works = getStatusFilterScopeWorks()
  return statusFilterBaseOptions.map(option => ({
    ...option,
    suffix: works.filter(item => itemMatchesStatusFilter(item, option.value)).length,
  }))
})
const statusFilterModel = computed({
  get: () => statusFilters.value,
  set: (next) => {
    statusFilters.value = normalizeStatusFilters(next, statusFilters.value)
  },
})
const selectedStatusFilterOptions = computed(() => {
  const selected = Array.isArray(statusFilters.value) ? statusFilters.value : []
  return statusFilterOptions.value.filter(option => selected.includes(option.value))
})
const statusFilterVisibleOptions = computed(() => (
  selectedStatusFilterOptions.value.length <= 2
    ? selectedStatusFilterOptions.value
    : selectedStatusFilterOptions.value.slice(0, 1)
))
const statusFilterOverflowCount = computed(() => Math.max(
  0,
  selectedStatusFilterOptions.value.length - statusFilterVisibleOptions.value.length,
))
const statusFilterTriggerTitle = computed(() => (
  selectedStatusFilterOptions.value.length
    ? selectedStatusFilterOptions.value.map(option => option.label).join('、')
    : '状态筛选'
))

function normalizeStatusFilters(next, previous = []) {
  const allowed = new Set(statusFilterBaseOptions.map(option => option.value))
  let values = [...new Set((Array.isArray(next) ? next : []).filter(value => allowed.has(value)))]
  const previousValues = Array.isArray(previous) ? previous : []
  const addedValue = values.find(value => !previousValues.includes(value))

  for (const group of statusFilterExclusiveGroups) {
    const selectedInGroup = values.filter(value => group.includes(value))
    if (selectedInGroup.length <= 1) continue
    const keepValue = addedValue && group.includes(addedValue)
      ? addedValue
      : selectedInGroup[selectedInGroup.length - 1]
    values = values.filter(value => !group.includes(value) || value === keepValue)
  }

  return values
}

function resetCircleDetail() {
  circleDetailRequestSeq += 1
  if (circleDetailAbortController) {
    circleDetailAbortController.abort()
    circleDetailAbortController = null
  }
  Object.assign(detail, {
    circle_id: '',
    circle_name: '',
    source_mask: '',
    last_indexed_at: '',
    owned_count: 0,
    missing_count: 0,
    downloadable_count: 0,
    dl_only_count: 0,
    works: []
  })
  circleDetailLoaded.value = false
  circleDetailLoading.value = false
  selectedCanonicals.value = new Set()
}

function getCircleDetailCacheKey(circleId) {
  return `${String(circleId || '').trim()}::dlOnly=${filters.includeDlOnly ? 1 : 0}`
}

function cloneCircleDetailPayload(payload = {}) {
  return {
    circle_id: String(payload.circle_id || ''),
    circle_name: String(payload.circle_name || ''),
    source_mask: String(payload.source_mask || ''),
    last_indexed_at: payload.last_indexed_at || '',
    owned_count: Number(payload.owned_count || 0),
    missing_count: Number(payload.missing_count || 0),
    downloadable_count: Number(payload.downloadable_count || 0),
    dl_only_count: Number(payload.dl_only_count || 0),
    works: Array.isArray(payload.works) ? payload.works.map(item => ({ ...item })) : []
  }
}

function getCachedCircleDetail(circleId) {
  const key = getCircleDetailCacheKey(circleId)
  const cached = circleDetailCache.get(key)
  if (!cached) return null
  if (Date.now() - cached.cachedAt > CIRCLE_DETAIL_CACHE_TTL) {
    circleDetailCache.delete(key)
    return null
  }
  return cloneCircleDetailPayload(cached.payload)
}

function hasFreshCircleDetailCache(circleId) {
  const key = getCircleDetailCacheKey(circleId)
  const cached = circleDetailCache.get(key)
  if (!cached) return false
  if (Date.now() - cached.cachedAt <= CIRCLE_DETAIL_CACHE_TTL) return true
  circleDetailCache.delete(key)
  return false
}

function setCachedCircleDetail(circleId, payload) {
  const key = getCircleDetailCacheKey(circleId)
  circleDetailCache.set(key, {
    cachedAt: Date.now(),
    payload: cloneCircleDetailPayload(payload)
  })
  while (circleDetailCache.size > 12) {
    const oldestKey = circleDetailCache.keys().next().value
    if (!oldestKey) break
    circleDetailCache.delete(oldestKey)
  }
}

function invalidateCircleDetailCache(circleId = '') {
  const target = String(circleId || '').trim()
  if (!target) {
    circleDetailCache.clear()
    return
  }
  for (const key of [...circleDetailCache.keys()]) {
    if (key.startsWith(`${target}::`)) circleDetailCache.delete(key)
  }
}

function applyCircleDetailPayload(payload, { loaded = true } = {}) {
  const normalized = cloneCircleDetailPayload(payload)
  Object.assign(detail, normalized)
  circleDetailLoaded.value = loaded
  selectedCanonicals.value = new Set(
    [...selectedCanonicals.value].filter(code => normalized.works.some(item => item.canonical_rjcode === code))
  )
}

function applyCircleSummaryPlaceholder(circleId) {
  const target = String(circleId || '').trim()
  const circle = (circleList.value || []).find(item => String(item?.circle_id || '') === target)
  Object.assign(detail, {
    circle_id: target,
    circle_name: circle?.circle_name || target,
    source_mask: circle?.source_mask || '',
    last_indexed_at: circle?.last_indexed_at || '',
    owned_count: Number(circle?.owned_count ?? circle?.server_owned ?? 0),
    missing_count: Number(circle?.missing ?? 0),
    downloadable_count: Number(circle?.downloadable_count ?? 0),
    dl_only_count: Number(circle?.dl_only_count ?? 0),
    works: []
  })
  circleDetailLoaded.value = false
}

async function syncActiveCircleWithList(options = {}) {
  const { preserveActiveWhenEmpty = false } = options
  const list = Array.isArray(displayCircleList.value) ? displayCircleList.value : []
  if (!list.length) {
    if (preserveActiveWhenEmpty && activeCircleId.value) {
      return
    }
    activeCircleId.value = ''
    resetCircleDetail()
    return
  }

  const hasActiveCircle = list.some(circle => circle?.circle_id === activeCircleId.value)
  if (hasActiveCircle) return

  const nextCircleId = String(list[0]?.circle_id || '').trim()
  if (!nextCircleId) {
    activeCircleId.value = ''
    resetCircleDetail()
    return
  }

  await selectCircle(nextCircleId)
}
const activeTab = ref('missing')
const selectedCanonicals = ref(new Set())
const flashedWorkCodes = ref(new Set())
const previewDialogVisible = ref(false)
const previewPlans = ref([])
const libraries = ref([])
const trackedDownloadTaskIds = ref([])
const downloadWorkbenchVisible = ref(false)
const downloadWorkbenchBackgroundActive = ref(false)
const downloadWorkbenchRefreshing = ref(false)
const trackedDownloadTasks = ref([])
const retryingTaskIds = ref(new Set())
const localUploadDialogVisible = ref(false)
const localUploadSubmitting = ref(false)
const localUploadSourceItems = ref([])
const localUploadForm = ref({ targetLibraryId: '', targetSubdir: '' })
const trackedUploadTaskIds = ref([])
const trackedUploadTasks = ref([])
const uploadWorkbenchVisible = ref(false)
const localUploadPreviewCircleName = computed(() => {
  const names = localUploadSourceItems.value
    .map(source => String(source?.circle_name || '').trim())
    .filter(Boolean)
  const uniqueNames = [...new Set(names)]
  if (uniqueNames.length === 1) return uniqueNames[0]
  if (uniqueNames.length > 1) return ''
  return String(detail.circle_name || '').trim()
})

async function handleNewReleaseNotification(event) {
  const item = event?.detail || {}
  if (String(item.event_type || '') !== 'email_watcher_new_release') return
  const circleId = String(item.route_query?.circle_id || '').trim()
  await loadRecentCircles()
  if (!circleId) return
  const exists = circleList.value.some(circle => String(circle?.circle_id || '') === circleId)
  if (exists) {
    await selectCircle(circleId)
  } else if (activeCircleId.value === circleId) {
    await refreshActiveCircle()
  }
}

// === 入库 → 社团补全状态实时刷新 ===
// 后端 sync_owned_for_rj 在写完 LibraryOwnedWork 后会通过 SSE 广播
// circle_owned_synced 事件，useNotifications 转发为 kikoerumanager:circle:owned-synced
// 自定义事件。这里订阅后做两件事：
//   1. 永远刷新左侧目录的 missing 计数（loadRecentCircles）
//   2. 仅当事件命中当前打开的社团时刷新右侧详情（refreshActiveCircle）
//
// 用 300ms debounce + 命中集合，避免批量入库（一次几十条）触发刷新风暴；
// 命中判断推迟到 timer fire 时点，避免 300ms 内 activeCircleId 切换导致用陈旧值。
let _circleOwnedSyncedTimer = null
const _circleOwnedSyncedHits = new Set()
function handleCircleOwnedSynced(event) {
  const detail = event?.detail || {}
  const circleIds = Array.isArray(detail.circle_ids) ? detail.circle_ids : []
  for (const cid of circleIds) {
    const normalized = String(cid || '').trim()
    if (normalized) _circleOwnedSyncedHits.add(normalized)
  }
  if (_circleOwnedSyncedTimer) clearTimeout(_circleOwnedSyncedTimer)
  _circleOwnedSyncedTimer = setTimeout(async () => {
    _circleOwnedSyncedTimer = null
    const hits = new Set(_circleOwnedSyncedHits)
    _circleOwnedSyncedHits.clear()
    try {
      const tasks = [loadRecentCircles()]
      if (activeCircleId.value && hits.has(activeCircleId.value)) {
        tasks.push(refreshActiveCircle())
      }
      await Promise.all(tasks)
    } catch (_) { /* 静默：不影响其他交互 */ }
  }, 300)
}
const uploadWorkbenchBackgroundActive = ref(false)
const uploadWorkbenchRefreshing = ref(false)
const worksPageSizes = [12, 24, 48, 96]
const comparePageSizes = [10, 20, 50, 100]
const worksPageSize = ref(24)
const comparePageSize = ref(10)
const missingPage = ref(1)
const missingSort = ref('default') // 'default' | 'downloadable' | 'title'
const worksReleaseSort = ref('desc')
const viewMode = ref('card') // 'card' | 'list'
watch(missingSort, () => { missingPage.value = 1 })
watch(worksReleaseSort, () => { missingPage.value = 1; ownedPage.value = 1; comparePage.value = 1 })
watch([circleCompletionFilter, circleSortKey], () => {
  syncActiveCircleWithList({ preserveActiveWhenEmpty: true })
})
const ownedPage = ref(1)
const comparePage = ref(1)
const refreshForceRefreshHint = computed(() => {
  if (refreshJob.meta?.force_refresh) {
    return refreshJob.meta.force_refresh_reason === 'auto_threshold'
      ? '1 分钟内连续刷新达到 3 次，当前已自动切换为强制刷新。'
      : '当前已启用强制刷新，不走缓存。'
  }
  return ''
})
const indexJob = reactive({
  visible: false,
  job_id: '',
  status: '',
  progress: 0,
  current_step: '',
  circle_query: '',
  elapsed_seconds: 0,
  error_message: '',
  meta: {}
})
let indexJobTimer = null
const cancellingIndexJob = ref(false)
const refreshingCurrentCircle = ref(false)
const refreshJob = reactive({
  visible: false,
  job_id: '',
  status: '',
  progress: 0,
  current_step: '',
  circle_id: '',
  circle_name: '',
  selected_count: 0,
  elapsed_seconds: 0,
  auto_hide_at: '',
  changed_codes: [],
  error_message: '',
  meta: {},
  result: {},
  progress_log: []
})
let refreshJobTimer = null
let refreshJobAutoHideTimer = null
const cancellingRefreshJob = ref(false)
const downloadSettings = reactive({
  downloadBasePath: '',
  targetLibraryId: '',
  targetSubdir: '',
  namingMode: 'api',
  classifyMode: 'circle',
  // 直放指定目录：开启后所有下载文件直接落到 target_subdir 下，不创建社团 / 作品目录层。
  flattenFiles: false
})
const cachedTargetSubdirs = ref([])
let flashedWorkTimer = null
let completeConfettiTimer = null
const showCompleteConfetti = ref(false)
const revealCompletePoster = ref(false)

function isPreferredMissingWorkVisible(item) {
  if (item?.owned) return false
  const groupKey = String(item?.preferred_variant?.group_key || '').trim()
  return ['original', 'simplified', 'traditional'].includes(groupKey || 'original')
}

function isWorkUnreleased(item) {
  if (item?.is_unreleased) return true
  const value = String(item?.release_date || item?.date || item?.release_at || '').trim()
  if (!value) return true
  const m = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!m) return false
  const rd = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3] || 1))
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return rd > today
}

function itemMatchesStatusFilter(item, key) {
  switch (key) {
    case 'repairable':
      return Boolean(item?.subtitle_repairable)
    case 'downloadable':
      return Boolean(item?.has_asmr_one) && !isWorkUnreleased(item)
    case 'missing':
      return !Boolean(item?.owned)
    case 'no_source':
      return !Boolean(item?.owned) && !Boolean(item?.has_asmr_one)
    default:
      return true
  }
}

function getStatusFilterScopeWorks() {
  const works = Array.isArray(detail.works) ? detail.works : []
  if (activeTab.value === 'missing') return works.filter(item => isPreferredMissingWorkVisible(item))
  if (activeTab.value === 'owned') return works.filter(item => item?.owned)
  return works
}

function applyStatusFilters(list) {
  const selected = Array.isArray(statusFilters.value) ? statusFilters.value : []
  if (!selected.length) return list
  return list.filter(item => selected.some(key => itemMatchesStatusFilter(item, key)))
}

const missingWorks = computed(() => {
  const list = applyStatusFilters((detail.works || []).filter(item => isPreferredMissingWorkVisible(item)))
  if (worksReleaseSort.value === 'asc' || worksReleaseSort.value === 'desc') {
    const direction = worksReleaseSort.value === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      // 「发售日未定」（后端 is_unreleased=true 但 release_date 没有具体年月日）
      // 由 getWorkReleaseTimestamp 折算成虚构的 2099-01-01 时间戳，正常参与排序：
      // 升序时落到列表末尾、降序时落到列表最前，都符合"发售日最迟"的业务语义。
      const diff = getWorkReleaseTimestamp(a) - getWorkReleaseTimestamp(b)
      if (diff !== 0) return diff * direction
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
    })
  }
  return list
})

const missingWorksTotal = computed(() =>
  Math.max(0, Number(detail.missing_count || 0))
)

const unreleasedWorksCount = computed(() =>
  (detail.works || []).filter(item => {
    if (item?.owned) return false
    if (item?.is_unreleased) return true
    const value = String(item?.release_date || item?.date || item?.release_at || '').trim()
    if (!value) return true
    const m = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
    if (!m) return false
    const rd = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3] || 1))
    const today = new Date(); today.setHours(0, 0, 0, 0)
    return rd > today
  }).length
)

// 工具栏"新作 N"统计：直接读后端打的 item.is_new_work（与 WorkCard / WorkListRow
// 同一来源），保证左侧 search_circles 的 new_works_48h_count、右侧卡片特效、
// 以及这里的工具栏数字三方永远对齐，不会再出现"卡片闪新作但左侧没标记"。
const newWorksCount = computed(() =>
  (detail.works || []).filter(item => isStrictTrue(item?.is_new_work)).length
)
const bonusWorksCount = computed(() =>
  (detail.works || []).filter(item => isBonusDisplayWork(item)).length
)

function getCircleWorksCount(circle) {
  return Number(circle?.dl_works || circle?.total_works || 0)
}

function getCircleOwnedCount(circle) {
  return Number(circle?.server_owned || 0)
}

function getCircleMissingCount(circle) {
  return Math.max(0, Number(circle?.missing || 0))
}

// 「发售日未定」作品参与排序时使用的虚构最大时间戳：2099-01-01 00:00。
// 业务语义是"发售日最迟"——升序排到末尾、降序排到最前，都对得上
// DLsite 上预售作品"还没排日期"的真实状态。等真实日期被刷新进来后，
// parseReleaseDateForSort 能正常返回 0 < t < 2099 的时间戳，自然归位。
const UNRELEASED_PLACEHOLDER_TIMESTAMP = new Date(2099, 0, 1).getTime()

function getWorkReleaseTimestamp(item) {
  const raw = String(item?.release_date || item?.date || item?.release_at || '').trim()
  const timestamp = raw ? parseReleaseDateForSort(raw) : 0
  if (Number.isFinite(timestamp) && timestamp > 0) return timestamp
  // 后端 is_unreleased=true 但 release_date 是"未定" / "TBD" / 空 等
  // 不可解析成具体年月日的字符串：用虚构的 2099-01-01 当成"最迟发售日"。
  if (item?.is_unreleased) return UNRELEASED_PLACEHOLDER_TIMESTAMP
  return 0
}

function parseReleaseDateForSort(raw) {
  const text = String(raw || '').trim()
  if (!text) return 0

  const fullDateMatch = text.match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/)
  if (fullDateMatch) {
    const year = Number(fullDateMatch[1])
    const month = Number(fullDateMatch[2])
    const day = Number(fullDateMatch[3])
    if (
      year > 0
      && month >= 1
      && month <= 12
      && day >= 1
      && day <= 31
    ) {
      return new Date(year, month - 1, day).getTime()
    }
  }

  const normalized = text
    .replace(/[年./]/g, '-')
    .replace(/月/g, '-')
    .replace(/日/g, '')
    .replace(/\s+/g, '')

  const exactTimestamp = new Date(normalized).getTime()
  if (Number.isFinite(exactTimestamp) && exactTimestamp > 0) {
    return exactTimestamp
  }

  const monthMatch = text.match(/(\d{4})\D+(\d{1,2})\D*(上旬|中旬|下旬)/)
  if (monthMatch) {
    const year = Number(monthMatch[1])
    const month = Number(monthMatch[2])
    const phase = monthMatch[3]
    if (year > 0 && month >= 1 && month <= 12) {
      const day = phase === '上旬'
        ? 9
        : phase === '中旬'
          ? 19
          : new Date(year, month, 0).getDate()
      return new Date(year, month - 1, day).getTime()
    }
  }

  const yearMonthMatch = normalized.match(/^(\d{4})-(\d{1,2})$/)
  if (yearMonthMatch) {
    const year = Number(yearMonthMatch[1])
    const month = Number(yearMonthMatch[2])
    if (year > 0 && month >= 1 && month <= 12) {
      return new Date(year, month - 1, 1).getTime()
    }
  }

  const looseYearMonthMatch = text.match(/(\d{4})\D+(\d{1,2})/)
  if (looseYearMonthMatch) {
    const year = Number(looseYearMonthMatch[1])
    const month = Number(looseYearMonthMatch[2])
    if (year > 0 && month >= 1 && month <= 12) {
      return new Date(year, month - 1, 1).getTime()
    }
  }

  return 0
}

function toggleWorksReleaseSort() {
  worksReleaseSort.value = worksReleaseSort.value === 'asc' ? 'desc' : 'asc'
}

function getCircleCompletionState(circle) {
  const works = getCircleWorksCount(circle)
  const missing = getCircleMissingCount(circle)
  if (works > 0 && missing === 0) return 'completed'
  return 'incomplete'
}

function getCircleRefreshTimestamp(circle) {
  const raw = circle?.last_indexed_at || circle?.updated_at || circle?.refreshed_at || circle?.created_at || ''
  const timestamp = new Date(raw).getTime()
  return Number.isFinite(timestamp) ? timestamp : 0
}

const displayCircleList = computed(() => {
  let list = Array.isArray(circleList.value) ? [...circleList.value] : []

  if (circleCompletionFilter.value === 'completed') {
    list = list.filter(circle => getCircleCompletionState(circle) === 'completed')
  } else if (circleCompletionFilter.value === 'incomplete') {
    list = list.filter(circle => getCircleCompletionState(circle) === 'incomplete')
  } else if (circleCompletionFilter.value === 'new_works') {
    list = list.filter(circle => (circle.new_works_48h_count || 0) > 0)
  }

  list.sort((left, right) => {
    switch (circleSortKey.value) {
      case 'completion': {
        const diff = getCircleOwnedPercent(right) - getCircleOwnedPercent(left)
        if (diff !== 0) return diff
        break
      }
      case 'works': {
        const diff = getCircleWorksCount(right) - getCircleWorksCount(left)
        if (diff !== 0) return diff
        break
      }
      case 'missing': {
        const diff = getCircleMissingCount(right) - getCircleMissingCount(left)
        if (diff !== 0) return diff
        break
      }
      case 'owned': {
        const diff = getCircleOwnedCount(right) - getCircleOwnedCount(left)
        if (diff !== 0) return diff
        break
      }
      case 'refreshed_at':
      default: {
        const diff = getCircleRefreshTimestamp(right) - getCircleRefreshTimestamp(left)
        if (diff !== 0) return diff
      }
    }

    return String(left?.circle_name || left?.circle_id || '').localeCompare(String(right?.circle_name || right?.circle_id || ''), 'zh-CN')
  })

  return list
})
const showMissingWorksCompleteState = computed(() =>
  Boolean(activeCircleId.value)
  && circleDetailLoaded.value
  && !circleDetailLoading.value
  && missingWorksTotal.value === 0
)

watch(showMissingWorksCompleteState, value => {
  if (completeConfettiTimer) {
    clearTimeout(completeConfettiTimer)
    completeConfettiTimer = null
  }

  if (!value) {
    showCompleteConfetti.value = false
    revealCompletePoster.value = false
    return
  }

  showCompleteConfetti.value = true
  revealCompletePoster.value = false

  completeConfettiTimer = setTimeout(() => {
    showCompleteConfetti.value = false
    revealCompletePoster.value = true
    completeConfettiTimer = null
  }, 1450)
}, { immediate: true })

const ownedWorksSearchQuery = ref('')
const ownedWorksFilterType = ref('all') // 'all', 'original', 'simplified', 'traditional', 'subtitle', 'bonus'
const compareSearchQuery = ref('')
const compareSourceFilter = ref('all') // 'all', 'kikoeru', 'dlsite', 'asmr_one', 'missing'

watch(ownedWorksSearchQuery, () => { ownedPage.value = 1 })
watch(compareSearchQuery, () => { comparePage.value = 1 })

function getOwnedVariantGroupLabel(item) {
  return item?.owned_variant?.group_short_label || '原作'
}

function getOwnedVariantGroupKey(item) {
  return item?.owned_variant?.group_key || 'original'
}

function isStrictTrue(value) {
  if (value === true || value === 1 || value === '1') return true
  if (typeof value === 'string') return value.trim().toLowerCase() === 'true'
  return false
}

function isBonusDisplayWork(item) {
  return isStrictTrue(item?.is_bonus_work)
}

function setOwnedWorksFilter(type) {
  if (ownedWorksFilterType.value === type) return
  ownedWorksFilterType.value = type
  ownedPage.value = 1
}

const ownedWorks = computed(() => {
  let list = applyStatusFilters((detail.works || []).filter(item => item.owned))

  // Filter
  if (ownedWorksFilterType.value !== 'all') {
    list = list.filter(item => {
      const groupKey = getOwnedVariantGroupKey(item)
      const hasSubtitle = groupKey === 'original' && isStrictTrue(item.subtitle_present)

      switch (ownedWorksFilterType.value) {
        case 'original': return groupKey === 'original' && !hasSubtitle
        case 'simplified': return groupKey === 'simplified'
        case 'traditional': return groupKey === 'traditional'
        case 'subtitle': return hasSubtitle
        case 'bonus': return isBonusDisplayWork(item)
        default: return true
      }
    })
  }

  // Search
  const query = ownedWorksSearchQuery.value.trim().toLowerCase()
  if (query) {
    list = list.filter(item => {
      const rjcode = (item.source_compare?.work_rjcode || item.canonical_rjcode || '').toLowerCase()
      const title = (item.title || item.canonical_rjcode || '').toLowerCase()
      return rjcode.includes(query) || title.includes(query)
    })
  }

  // 发售日排序（与缺失作品共用同一排序状态）
  if (worksReleaseSort.value === 'asc' || worksReleaseSort.value === 'desc') {
    const direction = worksReleaseSort.value === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      const diff = getWorkReleaseTimestamp(a) - getWorkReleaseTimestamp(b)
      if (diff !== 0) return diff * direction
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
    })
  }

  return list
})

const ownedWorksStats = computed(() => {
  const all = (detail.works || []).filter(item => item.owned)
  return {
    total: all.length,
    original: all.filter(item => {
      const groupKey = getOwnedVariantGroupKey(item)
      const hasSubtitle = groupKey === 'original' && isStrictTrue(item.subtitle_present)
      return groupKey === 'original' && !hasSubtitle
    }).length,
    simplified: all.filter(item => getOwnedVariantGroupKey(item) === 'simplified').length,
    traditional: all.filter(item => getOwnedVariantGroupKey(item) === 'traditional').length,
    subtitle: all.filter(item => getOwnedVariantGroupKey(item) === 'original' && isStrictTrue(item.subtitle_present)).length,
    bonus: all.filter(item => isBonusDisplayWork(item)).length,
  }
})

const compareWorks = computed(() => (detail.works || []).map(item => ({
  workRjcode: String(item?.source_compare?.work_rjcode || item?.canonical_rjcode || '').trim(),
  title: String(item?.title || '').trim(),
  preferredVariantLabel: String(item?.preferred_variant?.group_short_label || item?.preferred_variant?.label || '').trim(),
  statusLabel: item?.server_owned
    ? formatServerOwnedLabel(item)
    : (item?.has_asmr_one ? '可下载' : '暂无来源'),
  statusKey: item?.server_owned
    ? 'owned'
    : (item?.has_asmr_one ? 'downloadable' : 'dl_only'),
  __releaseTimestamp: getWorkReleaseTimestamp(item),
  __releaseDate: String(item?.release_date || item?.date || item?.release_at || '').trim(),
  sourceCompare: {
    kikoeru: {
      primary_rjcode: String(item?.source_compare?.kikoeru?.primary_rjcode || '').trim(),
      primaryBadge: String(item?.source_compare?.kikoeru?.primary_badge || '').trim(),
      variantBadges: Array.isArray(item?.source_compare?.kikoeru?.variant_badges) && item.source_compare.kikoeru.variant_badges.length
        ? item.source_compare.kikoeru.variant_badges.filter(Boolean)
        : (String(item?.source_compare?.kikoeru?.primary_badge || '').trim() ? [String(item.source_compare.kikoeru.primary_badge).trim()] : []),
      all_rjcodes: Array.isArray(item?.source_compare?.kikoeru?.all_rjcodes) ? item.source_compare.kikoeru.all_rjcodes.filter(Boolean) : [],
      tags: Array.isArray(item?.source_compare?.kikoeru?.tags) ? item.source_compare.kikoeru.tags.filter(Boolean) : [],
    },
    dlsite: {
      all_rjcodes: Array.isArray(item?.source_compare?.dlsite?.all_rjcodes) ? item.source_compare.dlsite.all_rjcodes.filter(Boolean) : [],
    },
    asmr_one: {
      primary_rjcode: String(item?.source_compare?.asmr_one?.primary_rjcode || '').trim(),
      primaryBadge: String(item?.source_compare?.asmr_one?.primary_badge || '').trim(),
      all_rjcodes: Array.isArray(item?.source_compare?.asmr_one?.all_rjcodes) ? item.source_compare.asmr_one.all_rjcodes.filter(Boolean) : [],
    },
  }
})))

function formatServerOwnedLabel(item) {
  if (!item?.server_owned) return '服务器缺失'
  const matched = String(
    item?.server_match_primary_rjcode ||
    item?.source_compare?.kikoeru?.matched_rjcode ||
    item?.source_compare?.kikoeru?.primary_rjcode ||
    ''
  ).trim()
  return matched ? `服务器已有 · ${matched}` : '服务器已有'
}

function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  const match = text.match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)
  return match ? match[0].toUpperCase() : text
}

function inferCanonicalRjcodesFromUploadTask(task) {
  const metadata = task?.task_metadata || {}
  const explicit = [
    metadata?.canonical_rjcode,
    metadata?.rjcode,
    task?.rjcode
  ]
    .map(value => normalizeRjcode(value))
    .filter(Boolean)
  if (explicit.length) return [...new Set(explicit)]

  const candidates = []
  const selectedPaths = Array.isArray(metadata?.selected_paths) ? metadata.selected_paths : []
  const uploaded = Array.isArray(task?.uploaded_files) ? task.uploaded_files : []
  const selectedItems = Array.isArray(metadata?.selected_items) ? metadata.selected_items : []

  for (const value of selectedPaths) {
    const normalized = normalizeRjcode(value)
    if (normalized) candidates.push(normalized)
  }
  for (const item of selectedItems) {
    const normalized = normalizeRjcode(item?.source_path)
    if (normalized) candidates.push(normalized)
  }
  for (const item of uploaded) {
    const normalized = normalizeRjcode(item?.name || item?.relative_path || item?.upload_path)
    if (normalized) candidates.push(normalized)
  }
  return [...new Set(candidates.filter(Boolean))]
}

function applyOptimisticOwnedStateForUploadTask(task) {
  if (!task || String(task?.task_metadata?.source_action || '').trim() !== 'direct_reimport_upload') return
  if (!Array.isArray(detail.works) || !detail.works.length) return
  const targetCodes = new Set(inferCanonicalRjcodesFromUploadTask(task))
  if (!targetCodes.size) return

  let changed = false
  detail.works = detail.works.map(item => {
    const canonical = normalizeRjcode(item?.canonical_rjcode)
    const display = normalizeRjcode(item?.display_rjcode)
    const linked = Array.isArray(item?.linked_rjcodes) ? item.linked_rjcodes.map(code => normalizeRjcode(code)).filter(Boolean) : []
    const matched = targetCodes.has(canonical) || targetCodes.has(display) || linked.some(code => targetCodes.has(code))
    if (!matched) return item
    changed = true
    return {
      ...item,
      owned: true,
      completion_owned: true,
      local_download_ready: false,
      local_download_root: '',
      local_download_session_id: '',
      local_downloaded_count: 0,
      server_owned: true,
      server_match_rjcodes: item.server_match_rjcodes?.length ? item.server_match_rjcodes : [display || canonical].filter(Boolean),
      server_match_primary_rjcode: String(item.server_match_primary_rjcode || display || canonical || '').trim(),
      status_tags: [
        ...(item.local_owned ? ['库存已收录'] : []),
        '服务器已有',
        ...(item.has_asmr_one ? ['可下载'] : ['暂不可下载']),
      ]
    }
  })
  if (!changed) return
  detail.owned_count = (detail.works || []).filter(item => item?.owned).length
  detail.server_owned_count = (detail.works || []).filter(item => item?.server_owned).length
  detail.missing_count = (detail.works || []).filter(item => !item?.owned).length
  detail.downloadable_count = (detail.works || []).filter(item => !item?.owned && item?.has_asmr_one).length
  detail.dl_only_count = (detail.works || []).filter(item => !item?.owned && !item?.has_asmr_one).length
}

function normalizeKikoeruTags(tags) {
  const source = Array.isArray(tags) ? tags : []
  const normalized = []
  for (const tag of source) {
    const text = String(tag || '').trim()
    if (!text) continue
    const value = text.startsWith('字幕') ? '字幕' : text
    if (!normalized.includes(value)) normalized.push(value)
  }
  return normalized
}

function flashChangedWorks(codes = []) {
  const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
  if (!normalized.length) return
  flashedWorkCodes.value = new Set(normalized)
  if (flashedWorkTimer) {
    window.clearTimeout(flashedWorkTimer)
    flashedWorkTimer = null
  }
  flashedWorkTimer = window.setTimeout(() => {
    flashedWorkCodes.value = new Set()
    flashedWorkTimer = null
  }, 3000)
}

function prioritizeChangedWorks(codes = []) {
  const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
  if (!normalized.length || !Array.isArray(detail.works) || !detail.works.length) return
  const order = new Map(normalized.map((code, index) => [code, index]))
  detail.works = [...detail.works].sort((left, right) => {
    const leftIndex = order.has(left?.canonical_rjcode) ? order.get(left.canonical_rjcode) : Number.POSITIVE_INFINITY
    const rightIndex = order.has(right?.canonical_rjcode) ? order.get(right.canonical_rjcode) : Number.POSITIVE_INFINITY
    if (leftIndex !== rightIndex) return leftIndex - rightIndex
    return 0
  })
}

const pagedCompareWorks = computed(() => {
  let list = compareWorks.value

  if (compareSourceFilter.value !== 'all') {
    list = list.filter(item => {
      switch (compareSourceFilter.value) {
        case 'kikoeru': return item.statusKey === 'owned'
        case 'dlsite': return !!item.sourceCompare.dlsite.all_rjcodes.length
        case 'asmr_one': return !!item.sourceCompare.asmr_one.primary_rjcode
        case 'missing': return !item.sourceCompare.kikoeru.primary_rjcode && !item.sourceCompare.dlsite.all_rjcodes.length && !item.sourceCompare.asmr_one.primary_rjcode
        default: return true
      }
    })
  }

  const query = compareSearchQuery.value.trim().toLowerCase()
  if (query) {
    list = list.filter(item => {
      const rjcode = item.workRjcode.toLowerCase()
      const title = item.title.toLowerCase()
      return rjcode.includes(query) || title.includes(query)
    })
  }

  // 发售日排序
  if (worksReleaseSort.value === 'asc' || worksReleaseSort.value === 'desc') {
    const direction = worksReleaseSort.value === 'asc' ? 1 : -1
    list = [...list].sort((a, b) => {
      const diff = (a.__releaseTimestamp || 0) - (b.__releaseTimestamp || 0)
      if (diff !== 0) return diff * direction
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
    })
  }

  const size = Number(comparePageSize.value || 10)
  const start = (comparePage.value - 1) * size
  return list.slice(start, start + size)
})

const compareWorksFilteredCount = computed(() => {
  let list = compareWorks.value
  if (compareSourceFilter.value !== 'all') {
    list = list.filter(item => {
      switch (compareSourceFilter.value) {
        case 'kikoeru': return item.statusKey === 'owned'
        case 'dlsite': return !!item.sourceCompare.dlsite.all_rjcodes.length
        case 'asmr_one': return !!item.sourceCompare.asmr_one.primary_rjcode
        case 'missing': return !item.sourceCompare.kikoeru.primary_rjcode && !item.sourceCompare.dlsite.all_rjcodes.length && !item.sourceCompare.asmr_one.primary_rjcode
        default: return true
      }
    })
  }
  const query = compareSearchQuery.value.trim().toLowerCase()
  if (query) {
    list = list.filter(item => {
      const rjcode = item.workRjcode.toLowerCase()
      const title = item.title.toLowerCase()
      return rjcode.includes(query) || title.includes(query)
    })
  }
  return list.length
})

const compareWorksStats = computed(() => {
  const all = compareWorks.value

  return {
    total: all.length,
    kikoeru: all.filter(item => item.statusKey === 'owned').length,
    dlsite: all.filter(item => !!item.sourceCompare.dlsite.all_rjcodes.length).length,
    asmr_one: all.filter(item => !!item.sourceCompare.asmr_one.primary_rjcode).length,
    missing: all.filter(item => !item.sourceCompare.kikoeru.primary_rjcode && !item.sourceCompare.dlsite.all_rjcodes.length && !item.sourceCompare.asmr_one.primary_rjcode).length
  }
})
const selectedCanonicalRJCodes = computed(() => [...selectedCanonicals.value])
const selectedDownloadableRJCodes = computed(() => selectedCanonicalRJCodes.value.filter(code => {
  const item = (detail.works || []).find(work => work.canonical_rjcode === code)
  return Boolean(item?.has_asmr_one)
}))
const activeSelectableWorks = computed(() => {
  if (activeTab.value === 'owned') return ownedWorks.value
  if (activeTab.value === 'missing') return missingWorks.value
  return []
})
const selectedActiveCanonicalRJCodes = computed(() => activeSelectableWorks.value
  .map(item => item?.canonical_rjcode)
  .filter(code => code && selectedCanonicals.value.has(code)))
const selectedActiveDownloadableRJCodes = computed(() => selectedActiveCanonicalRJCodes.value.filter(code => {
  const item = activeSelectableWorks.value.find(work => work.canonical_rjcode === code)
  return Boolean(item?.has_asmr_one)
}))
function getPreviewRequestedRjcodes(canonicalCodes = []) {
  const mapping = {}
  canonicalCodes.forEach(code => {
    const item = (detail.works || []).find(work => work.canonical_rjcode === code)
    if (!item) return
    const candidates = [
      item.download_plan?.rjcode,
      item.asmr_available_rjcode,
      item.display_rjcode,
      item.canonical_rjcode,
      ...(Array.isArray(item.linked_rjcodes) ? item.linked_rjcodes : [])
    ]
      .map(value => String(value || '').trim().toUpperCase())
      .filter(Boolean)
      .filter((value, index, array) => array.indexOf(value) === index)
    if (candidates.length) {
      mapping[code] = candidates
    }
  })
  return mapping
}
const targetLibraries = computed(() => (libraries.value || []).filter(item => item?.enabled !== false))
const targetSubdirOptions = computed(() => [...new Set((cachedTargetSubdirs.value || []).filter(Boolean))])
const processingDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => ['processing'].includes(String(task.status || ''))))
const pendingDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))))
const completedDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => String(task.status || '') === 'completed'))
const failedDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => String(task.status || '') === 'failed'))
const showDownloadBackgroundCard = computed(() => downloadWorkbenchBackgroundActive.value && !downloadWorkbenchVisible.value && trackedDownloadTaskIds.value.length > 0)
const activeBackgroundDownloadTask = computed(() => processingDownloadTasks.value[0] || pendingDownloadTasks.value[0] || trackedDownloadTasks.value[0] || null)
const processingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => ['processing'].includes(String(task?.status || ''))))
const pendingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))))
const completedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'completed'))
const failedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'failed'))
const showUploadBackgroundCard = computed(() => uploadWorkbenchBackgroundActive.value && !uploadWorkbenchVisible.value && trackedUploadTaskIds.value.length > 0)
const activeBackgroundUploadTask = computed(() => processingUploadTasks.value[0] || pendingUploadTasks.value[0] || trackedUploadTasks.value[0] || null)
const uploadBackgroundPercent = computed(() => {
  if (!trackedUploadTasks.value.length) return 0
  const aggregate = trackedUploadTasks.value.reduce((sum, task) => {
    const runtime = task?.upload_runtime || {}
    sum.transferred += Number(runtime?.transferred_bytes || 0)
    sum.total += Number(runtime?.total_bytes || 0)
    return sum
  }, { transferred: 0, total: 0 })
  if (aggregate.total > 0) {
    return Math.max(0, Math.min(100, Math.round((aggregate.transferred / aggregate.total) * 100)))
  }
  const total = trackedUploadTasks.value.reduce((sum, task) => sum + Number(task?.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / trackedUploadTasks.value.length)))
})
const backgroundDownloadPercent = computed(() => {
  if (!trackedDownloadTasks.value.length) return 0
  const aggregate = trackedDownloadTasks.value.reduce((sum, task) => {
    sum.transferred += getTaskTransferredBytes(task)
    sum.total += getTaskTotalBytes(task)
    return sum
  }, { transferred: 0, total: 0 })
  if (aggregate.total > 0) {
    return Math.max(0, Math.min(100, Math.round((aggregate.transferred / aggregate.total) * 100)))
  }
  const total = trackedDownloadTasks.value.reduce((sum, task) => sum + Number(task.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / trackedDownloadTasks.value.length)))
})
const downloadBackgroundCompleted = computed(() => (
  trackedDownloadTasks.value.length > 0
  && completedDownloadTasks.value.length === trackedDownloadTasks.value.length
  && failedDownloadTasks.value.length === 0
))
const downloadBackgroundFailed = computed(() => (
  failedDownloadTasks.value.length > 0
  && processingDownloadTasks.value.length === 0
  && pendingDownloadTasks.value.length === 0
))
const uploadBackgroundCompleted = computed(() => (
  trackedUploadTasks.value.length > 0
  && completedUploadTasks.value.length === trackedUploadTasks.value.length
  && failedUploadTasks.value.length === 0
))
const uploadBackgroundFailed = computed(() => (
  failedUploadTasks.value.length > 0
  && processingUploadTasks.value.length === 0
  && pendingUploadTasks.value.length === 0
))
const downloadBackgroundCardProps = computed(() => ({
  kind: 'download',
  tone: downloadBackgroundFailed.value ? 'amber' : 'primary',
  title: downloadBackgroundCompleted.value
    ? '社团补全下载已完成'
    : downloadBackgroundFailed.value
      ? '社团补全下载需要处理'
      : '社团补全下载正在后台运行',
  badgeText: `下载 ${trackedDownloadTasks.value.length} 项`,
  subtitle: activeBackgroundDownloadTask.value
    ? `${activeBackgroundDownloadTask.value.rjcode || 'RJ'} · ${activeBackgroundDownloadTask.value.work_title || activeBackgroundDownloadTask.value.source_label || '-'}`
    : '保留当前下载队列与进度状态',
  metaText: `预计剩余: ${formatDownloadTaskEta(activeBackgroundDownloadTask.value)}`,
  percentage: backgroundDownloadPercent.value,
  completed: downloadBackgroundCompleted.value,
  metrics: [
    { key: 'processing', label: '进行中', value: processingDownloadTasks.value.length, tone: 'info' },
    { key: 'pending', label: '等待中', value: pendingDownloadTasks.value.length, tone: 'warning' },
    { key: 'completed', label: '完成', value: completedDownloadTasks.value.length, tone: 'success' },
    { key: 'failed', label: '失败', value: failedDownloadTasks.value.length, tone: failedDownloadTasks.value.length ? 'danger' : 'neutral' },
    { key: 'speed', label: formatSpeed(getDownloadSpeedBytes(activeBackgroundDownloadTask.value)), tone: 'indigo' },
    { key: 'eta', label: formatDownloadTaskEta(activeBackgroundDownloadTask.value), tone: 'violet' }
  ],
  detailText: activeBackgroundDownloadTask.value?.current_step || '隐藏后继续保留下载队列和进度。',
  actions: [
    { key: 'close', label: '关闭' },
    { key: 'resume', label: '恢复工作台', variant: 'primary' }
  ]
}))
const uploadBackgroundCardProps = computed(() => ({
  kind: 'upload',
  tone: uploadBackgroundFailed.value ? 'amber' : 'emerald',
  title: uploadBackgroundCompleted.value
    ? '直接入库上传已完成'
    : uploadBackgroundFailed.value
      ? '直接入库上传需要处理'
      : '直接入库上传正在后台运行',
  badgeText: `上传 ${trackedUploadTasks.value.length} 项`,
  subtitle: activeBackgroundUploadTask.value
    ? `${activeBackgroundUploadTask.value.work_title || activeBackgroundUploadTask.value.source_label || '-'} · ${getUploadBackgroundTargetLabel(activeBackgroundUploadTask.value)}`
    : '保留当前上传队列与进度状态',
  metaText: `预计剩余: ${formatTaskEta(activeBackgroundUploadTask.value)}`,
  percentage: uploadBackgroundPercent.value,
  completed: uploadBackgroundCompleted.value,
  metrics: [
    { key: 'processing', label: '进行中', value: processingUploadTasks.value.length, tone: 'info' },
    { key: 'pending', label: '等待中', value: pendingUploadTasks.value.length, tone: 'warning' },
    { key: 'completed', label: '完成', value: completedUploadTasks.value.length, tone: 'success' },
    { key: 'failed', label: '失败', value: failedUploadTasks.value.length, tone: failedUploadTasks.value.length ? 'danger' : 'neutral' },
    { key: 'speed', label: formatSpeed(getUploadBackgroundSpeed(activeBackgroundUploadTask.value)), tone: 'indigo' },
    { key: 'eta', label: formatTaskEta(activeBackgroundUploadTask.value), tone: 'violet' }
  ],
  detailText: activeBackgroundUploadTask.value?.current_step || '隐藏后继续保留上传队列和进度。',
  actions: [
    { key: 'close', label: '关闭' },
    { key: 'resume', label: '恢复工作台', variant: 'emerald' }
  ]
}))
const indexJobStatusText = computed(() => {
  if (indexJob.error_message === '用户取消' || indexJob.current_step === '已取消') return '已取消'
  if (indexJob.status === 'completed') return '已完成'
  if (indexJob.status === 'failed') return '失败'
  if (indexJob.status === 'processing') return '进行中'
  return '等待中'
})
const canCancelIndexJob = computed(() =>
  Boolean(indexJob.job_id) && ['pending', 'processing'].includes(String(indexJob.status || ''))
)
const refreshJobStatusText = computed(() => {
  if (refreshJob.error_message === '用户取消' || refreshJob.current_step === '已取消') return '已取消'
  if (refreshJob.status === 'completed') return '已完成'
  if (refreshJob.status === 'failed') return '失败'
  if (refreshJob.status === 'processing') return '进行中'
  return '等待中'
})
const isRefreshJobActive = computed(() =>
  Boolean(refreshJob.job_id) && ['pending', 'processing'].includes(String(refreshJob.status || ''))
)
const canCancelRefreshJob = computed(() => isRefreshJobActive.value)

onMounted(async () => {
  window.addEventListener('kikoerumanager:notification:new', handleNewReleaseNotification)
  window.addEventListener('kikoerumanager:circle:owned-synced', handleCircleOwnedSynced)
  hydrateIndexJobState()
  hydrateRefreshJobState()
  hydrateDownloadWorkbenchState()
  restoreUploadWorkbenchState()
  loadCachedTargetSubdirs()
  await Promise.all([loadRecentCircles(), loadLibraries()])
  if (trackedDownloadTaskIds.value.length) await refreshDownloadWorkbench()
  if (trackedUploadTaskIds.value.length) await refreshUploadWorkbench({ silent: true })
  if (indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || ''))) {
    await pollIndexJob(indexJob.job_id)
  }
  if (isRefreshJobActive.value) await pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length) {
      await refreshActiveCircle()
      prioritizeChangedWorks(refreshJob.changed_codes)
      flashChangedWorks(refreshJob.changed_codes)
    }
    resumeRefreshJobAutoHide()
  }
})

onActivated(() => {
  if (indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || ''))) {
    indexing.value = true
    pollIndexJob(indexJob.job_id)
  }
  if (isRefreshJobActive.value) {
    refreshingCurrentCircle.value = true
    pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  } else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length && activeCircleId.value) {
      refreshActiveCircle().then(() => {
        prioritizeChangedWorks(refreshJob.changed_codes)
        flashChangedWorks(refreshJob.changed_codes)
      }).catch(() => {})
    }
    resumeRefreshJobAutoHide()
  }
  if (trackedDownloadTaskIds.value.length) {
    refreshDownloadWorkbench()
  }
  if (trackedUploadTaskIds.value.length) {
    refreshUploadWorkbench({ silent: true })
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('kikoerumanager:notification:new', handleNewReleaseNotification)
  window.removeEventListener('kikoerumanager:circle:owned-synced', handleCircleOwnedSynced)
  if (_circleOwnedSyncedTimer) {
    clearTimeout(_circleOwnedSyncedTimer)
    _circleOwnedSyncedTimer = null
  }
  if (completeConfettiTimer) {
    clearTimeout(completeConfettiTimer)
    completeConfettiTimer = null
  }
  if (circleDetailPrefetchTimer) {
    clearTimeout(circleDetailPrefetchTimer)
    circleDetailPrefetchTimer = null
  }
  if (circleDetailAbortController) {
    circleDetailAbortController.abort()
    circleDetailAbortController = null
  }
  stopIndexJobPolling()
  stopRefreshJobPolling()
  stopRefreshJobAutoHide()
  stopDownloadWorkbenchPolling()
  stopUploadWorkbenchPolling()
})

watch(activeTab, (tab) => {
  if (tab === 'missing') missingPage.value = 1
  if (tab === 'owned') ownedPage.value = 1
  if (tab === 'compare') comparePage.value = 1
})

watch(() => detail.works, () => {
  missingPage.value = 1
  ownedPage.value = 1
  comparePage.value = 1
}, { deep: true })

watch(downloadWorkbenchVisible, (visible) => {
  persistDownloadWorkbenchState()
  if (visible || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
  else stopDownloadWorkbenchPolling()
})

watch(downloadWorkbenchBackgroundActive, () => {
  persistDownloadWorkbenchState()
  if (downloadWorkbenchVisible.value || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
  else stopDownloadWorkbenchPolling()
})

watch(trackedDownloadTaskIds, () => {
  persistDownloadWorkbenchState()
}, { deep: true })

watch(uploadWorkbenchVisible, () => {
  persistUploadWorkbenchState()
  if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  else stopUploadWorkbenchPolling()
})

watch(uploadWorkbenchBackgroundActive, () => {
  persistUploadWorkbenchState()
  if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  else stopUploadWorkbenchPolling()
})

watch(trackedUploadTaskIds, () => {
  persistUploadWorkbenchState()
}, { deep: true })

watch(
  () => [refreshJob.job_id, refreshJob.status, refreshJob.progress, refreshJob.current_step, refreshJob.elapsed_seconds].join(':'),
  () => {
    persistRefreshJobState()
  }
)

watch(() => downloadSettings.targetSubdir, (value) => {
  if (value) rememberTargetSubdir(value)
})

watch(
  () => trackedDownloadTasks.value.map(task => [task?.id, task?.status, task?.completed_at].join(':')).join('|'),
  async (value, previousValue) => {
    if (!value || value === previousValue) return
    const justFinished = trackedDownloadTasks.value.some(task => {
      if (!task || !isTaskFinished(task)) return false
      const taskId = String(task?.id || '').trim()
      const previousText = String(previousValue || '')
      if (!taskId) return false
      return !previousText.includes(taskId) || !previousText.includes(`${taskId}:${task.status}:${task.completed_at || ''}`)
    })
    if (!justFinished || !activeCircleId.value) return
    try {
      await refreshActiveCircle()
    } catch (_) {}
  }
)

watch(
  () => trackedUploadTasks.value.map(task => [task?.id, task?.status, task?.completed_at].join(':')).join('|'),
  async (value, previousValue) => {
    if (!value || value === previousValue) return
    const justCompletedTasks = trackedUploadTasks.value.filter(task => {
      if (!task || String(task?.status || '') !== 'completed') return false
      const taskId = String(task?.id || '').trim()
      const previousText = String(previousValue || '')
      if (!taskId) return false
      return !previousText.includes(taskId) || !previousText.includes(`${taskId}:${task.status}:${task.completed_at || ''}`)
    })
    if (!justCompletedTasks.length) return
    for (const task of justCompletedTasks) {
      applyOptimisticOwnedStateForUploadTask(task)
    }
    if (!activeCircleId.value) return
    try {
      await refreshActiveCircle()
    } catch (_) {}
  }
)

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function getCircleOwnedPercent(circle) {
  const total = Number(circle?.dl_works || circle?.total_works || 0)
  const owned = Number(circle?.server_owned || 0)
  if (!total) return 0
  return Math.min(100, Math.round((owned / total) * 100))
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)))
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatLogTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString()
}

function formatDurationMs(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${mins}分${secs}秒`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatEtaSeconds(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)))
  if (!totalSeconds) return '—'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${Math.floor((totalSeconds % 3600) / 60)}分`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatSpeed(bytesPerSec) {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatSize(value)}/s` : '—'
}

function isReimportTaskActive(task) {
  return ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || ''))
}

function isTaskFinished(task) {
  return ['completed', 'failed'].includes(String(task?.status || ''))
}

function formatTaskEta(task) {
  if (!task) return '—'
  if (isTaskFinished(task) || getReimportOverallPercent(task) >= 100) return '完成'
  return formatEtaSeconds(getUploadEtaSeconds(task))
}

function formatDownloadTaskEta(task) {
  if (!task) return '—'
  if (isTaskFinished(task) || backgroundDownloadPercent.value >= 100) return '完成'
  return formatEtaSeconds(getDownloadEtaSeconds(task))
}

function formatFileEta(file) {
  if (Number(file?.progress || 0) >= 100) return '等待确认'
  return formatEtaSeconds(file?.eta_seconds)
}

function getDownloadRuntime(task) {
  const runtime = task?.download_runtime || task?.performance_metrics?.download_runtime || task?.task_metadata?.performance_metrics?.download_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function getUploadRuntime(task) {
  const runtime = task?.upload_runtime || task?.performance_metrics?.upload_runtime || task?.task_metadata?.performance_metrics?.upload_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function getTaskTransferredBytes(task) {
  const downloadTransferred = Number(getDownloadRuntime(task)?.transferred_bytes || 0)
  const uploadTransferred = Number(getUploadRuntime(task)?.transferred_bytes || 0)
  if (Number(getUploadRuntime(task)?.total_bytes || 0) > 0) return downloadTransferred + uploadTransferred
  return downloadTransferred
}

function getTaskTotalBytes(task) {
  const downloadTotal = Number(getDownloadRuntime(task)?.total_bytes || 0)
  const uploadTotal = Number(getUploadRuntime(task)?.total_bytes || 0)
  if (uploadTotal > 0) return Math.max(downloadTotal, getTaskTransferBytes(task)) + uploadTotal
  return downloadTotal || getTaskTransferBytes(task)
}

function getUploadTransferredBytes(task) {
  const runtimeBytes = Number(getUploadRuntime(task)?.transferred_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  return uploadFiles.reduce((sum, item) => sum + Number(item?.uploaded || 0), 0)
}

function getUploadTotalBytes(task) {
  const runtimeBytes = Number(getUploadRuntime(task)?.total_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const totalBytes = uploadFiles.reduce((sum, item) => sum + Number(item?.total || 0), 0)
  if (totalBytes > 0) return totalBytes
  return getTaskTransferBytes(task)
}

function getUploadSpeedBytes(task) {
  const runtimeSpeed = Number(getUploadRuntime(task)?.speed_bytes_per_sec || 0)
  if (runtimeSpeed > 0) return runtimeSpeed
  if (isTaskFinished(task)) {
    const details = task?.performance_metrics || task?.task_metadata?.performance_metrics || {}
    return Number(details?.average_upload_speed_bytes || 0)
  }
  return 0
}

function getUploadEtaSeconds(task) {
  return Number(getUploadRuntime(task)?.eta_seconds || 0)
}

function getTaskElapsedMs(task) {
  const runtime = getUploadRuntime(task)
  const startValue = runtime?.started_at || task?.started_at || task?.created_at
  const endValue = runtime?.ended_at || task?.completed_at || runtime?.updated_at
  if (!startValue) return 0
  const start = new Date(startValue)
  const end = endValue ? new Date(endValue) : new Date()
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0
  return Math.max(0, end.getTime() - start.getTime())
}

function getReimportOverallPercent(task) {
  const runtimeProgress = Number(getUploadRuntime(task)?.progress || 0)
  if (runtimeProgress > 0) return Math.min(100, runtimeProgress)
  if (isTaskFinished(task) && getUploadedCount(task) > 0) return 100
  return Math.min(100, Number(task?.progress || 0))
}

function getCurrentUploadSequenceLabel(task) {
  const runtime = getUploadRuntime(task)
  const current = Number(runtime?.current_file_index || 0)
  const total = Number(runtime?.total_files || getTaskResourceCount(task) || 0)
  if (current > 0 && total > 0) return `${current} / ${total}`
  if (total > 0) return `0 / ${total}`
  return '—'
}

function getUploadStageLabel(task) {
  const runtime = getUploadRuntime(task)
  const stage = String(runtime?.stage || '').trim()
  const currentStep = String(task?.current_step || '').trim()
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const pendingConfirmation = uploadFiles.some(item => Number(item?.progress || 0) >= 100)
  if (stage === 'library_upload') return '上传到服务器目录'
  if (stage === 'upload') return '上传到服务器目录'
  if (pendingConfirmation) return '等待服务器确认'
  if (currentStep.includes('校验中')) return '校验文件'
  if (isReimportTask(task)) return '准备入库'
  return '处理中'
}

function hasTaskFailures(task) {
  if (!task) return false
  const failedFiles = Array.isArray(task.failed_files) ? task.failed_files : []
  const verificationFailures = Array.isArray(task.verification_failures) ? task.verification_failures : []
  return Boolean(failedFiles.length || verificationFailures.length || String(task.task_metadata?.failure_reason || '').trim() || String(task.error_message || '').trim())
}

function getDownloadTaskStatusLabel(taskOrStatus) {
  const task = typeof taskOrStatus === 'object' && taskOrStatus !== null ? taskOrStatus : null
  const status = task ? (task.display_status || task.status) : taskOrStatus
  if (task && String(status || '') === 'completed' && hasTaskFailures(task)) {
    return '部分失败'
  }
  const map = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    paused: '已暂停',
    waiting_retry: '等待重试'
  }
  return map[String(status || '')] || String(status || '未知')
}

function getDownloadTaskStatusClass(task) {
  const status = String(task?.display_status || task?.status || '')
  return {
    ok: status === 'completed' && !hasTaskFailures(task),
    warning: status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task)),
    danger: status === 'failed'
  }
}

function getDownloadTaskProgressStatus(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'failed') return 'exception'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return 'warning'
  if (status === 'completed') return 'success'
  return ''
}

function getTaskFailureText(task) {
  if (!task) return ''
  const fromMeta = String(task.task_metadata?.failure_reason || '').trim()
  if (fromMeta) return fromMeta
  const errorMessage = String(task.error_message || '').trim()
  if (errorMessage) return errorMessage
  const failedFiles = Array.isArray(task.failed_files) ? task.failed_files : []
  if (failedFiles.length) {
    return failedFiles
      .slice(0, 3)
      .map(item => `${item.name || '未知文件'}: ${item.reason || item.exception_type || '失败'}`)
      .join(' / ')
  }
  const verificationFailures = Array.isArray(task.verification_failures) ? task.verification_failures : []
  if (verificationFailures.length) {
    return verificationFailures
      .slice(0, 2)
      .map(item => `${item.name || item.relative_path || '文件'} MD5 校验失败`)
      .join(' / ')
  }
  return ''
}

function getUploadedCount(task) {
  const uploaded = Array.isArray(task?.uploaded_files) ? task.uploaded_files.length : 0
  if (uploaded) return uploaded
  const summaryUploaded = Number(task?.task_metadata?.upload_summary?.uploaded || task?.upload_summary?.uploaded || 0)
  if (summaryUploaded) return summaryUploaded
  const progressFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  return progressFiles.filter(item => Number(item?.progress || 0) >= 100).length
}

function isReimportTask(task) {
  const action = String(task?.task_metadata?.source_action || '').trim()
  return action === 'reimport_local_download_root' || action === 'reimport_downloaded_session'
}

function getTaskResourceCount(task) {
  const explicit = Number(task?.task_metadata?.selected_resource_count || task?.session_state?.selected_resource_count || 0)
  if (explicit > 0) return explicit
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources.length : 0
  if (selectedResources > 0) return selectedResources
  return getDownloadedCount(task)
}

function getTaskTransferBytes(task) {
  const metricBytes = Number(task?.performance_metrics?.downloaded_bytes || task?.task_metadata?.performance_metrics?.downloaded_bytes || 0)
  if (metricBytes > 0) return metricBytes
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const selectedBytes = selectedResources.reduce((sum, item) => sum + Number(item?.size_bytes || 0), 0)
  if (selectedBytes > 0) return selectedBytes
  const downloadRuntimeTotal = Number(getDownloadRuntime(task)?.total_bytes || 0)
  if (downloadRuntimeTotal > 0) return downloadRuntimeTotal
  const uploadedFiles = Array.isArray(task?.uploaded_files) ? task.uploaded_files : []
  return uploadedFiles.reduce((sum, item) => sum + Number(item?.size_bytes || 0), 0)
}

function getTaskTransferLabel(task) {
  return isReimportTask(task) ? '资源大小' : '下载大小'
}

function getFailureSummary(task) {
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files.length : 0
  const verifyFailures = Array.isArray(task?.verification_failures) ? task.verification_failures.length : 0
  if (!failedFiles && !verifyFailures) return '0'
  const parts = []
  if (failedFiles) parts.push(`下载失败 ${failedFiles}`)
  if (verifyFailures) parts.push(`校验失败 ${verifyFailures}`)
  return parts.join(' / ')
}

function getDownloadedCount(task) {
  const persistedCount = Number(task?.task_metadata?.local_downloaded_count || task?.session_state?.local_downloaded_count || 0)
  if (persistedCount > 0) return persistedCount
  const downloadedResources = Array.isArray(task?.task_metadata?.downloaded_resources) ? task.task_metadata.downloaded_resources.length : 0
  if (downloadedResources) return downloadedResources
  const downloadFiles = Array.isArray(task?.download_files) ? task.download_files : []
  return downloadFiles.filter(item => Number(item?.progress || 0) >= 100).length
}

function isTaskDownloaded(task) {
  const persistedReady = Boolean(task?.task_metadata?.local_download_ready || task?.session_state?.local_download_ready)
  const downloadRoot = String(
    task?.task_metadata?.local_download_root
    || task?.session_state?.local_download_root
    || task?.task_metadata?.download_root
    || ''
  ).trim()
  return Boolean((persistedReady || getDownloadedCount(task) > 0) && downloadRoot)
}

function getRetryableFailedFiles(task) {
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files : []
  return failedFiles
    .map(item => ({
      name: String(item?.name || '').trim(),
      relative_path: String(item?.relative_path || '').trim(),
      reason: String(item?.reason || '').trim(),
      exception_type: String(item?.exception_type || '').trim(),
      stage: String(item?.stage || '').trim(),
    }))
    .filter(item => item.relative_path || item.name)
}

function loadCachedTargetSubdirs() {
  try {
    const raw = localStorage.getItem(CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY)
    const parsed = JSON.parse(raw || '[]')
    cachedTargetSubdirs.value = Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 20) : []
  } catch (_) {
    cachedTargetSubdirs.value = []
  }
}

function rememberTargetSubdir(value = '') {
  const normalized = String(value || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  if (!normalized) return
  const next = [normalized, ...cachedTargetSubdirs.value.filter(item => item !== normalized)].slice(0, 20)
  cachedTargetSubdirs.value = next
  try {
    localStorage.setItem(CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY, JSON.stringify(next))
  } catch (_) {}
}

let downloadWorkbenchTimer = null

function persistDownloadWorkbenchState() {
  try {
    localStorage.setItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: trackedDownloadTaskIds.value,
      visible: downloadWorkbenchVisible.value,
      background: downloadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function persistIndexJobState() {
  try {
    if (!indexJob.job_id) {
      localStorage.removeItem(CIRCLE_COMPLETION_INDEX_JOB_KEY)
      return
    }
    localStorage.setItem(CIRCLE_COMPLETION_INDEX_JOB_KEY, JSON.stringify({
      job_id: indexJob.job_id,
      status: indexJob.status,
      progress: indexJob.progress,
      current_step: indexJob.current_step,
      circle_query: indexJob.circle_query,
      elapsed_seconds: indexJob.elapsed_seconds,
      error_message: indexJob.error_message,
      meta: indexJob.meta || {},
      visible: indexJob.visible,
    }))
  } catch (_) {}
}

function isCancelledJobState(raw = {}) {
  return String(raw?.error_message || '').trim() === '用户取消'
    || String(raw?.current_step || '').trim() === '已取消'
}

function hydrateIndexJobState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_INDEX_JOB_KEY) || '{}')
    const status = String(raw.status || '').trim()
    // 终态或取消态：启动时直接清除，不常驻进度卡
    if (isCancelledJobState(raw) || ['completed', 'failed'].includes(status)) {
      clearIndexJobState()
      return
    }
    indexJob.visible = Boolean(raw.job_id && raw.visible !== false)
    indexJob.job_id = String(raw.job_id || '').trim()
    indexJob.status = String(raw.status || '').trim()
    indexJob.progress = Number(raw.progress || 0)
    indexJob.current_step = String(raw.current_step || '').trim()
    indexJob.circle_query = String(raw.circle_query || '').trim()
    indexJob.elapsed_seconds = Number(raw.elapsed_seconds || 0)
    indexJob.error_message = String(raw.error_message || '').trim()
    indexJob.meta = raw.meta && typeof raw.meta === 'object' ? raw.meta : {}
    indexing.value = Boolean(indexJob.job_id && ['pending', 'processing'].includes(indexJob.status))
  } catch (_) {
    clearIndexJobState()
  }
}

function clearIndexJobState() {
  indexJob.visible = false
  indexJob.job_id = ''
  indexJob.status = ''
  indexJob.progress = 0
  indexJob.current_step = ''
  indexJob.circle_query = ''
  indexJob.elapsed_seconds = 0
  indexJob.error_message = ''
  indexJob.meta = {}
  indexing.value = false
  stopIndexJobPolling()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_INDEX_JOB_KEY)
  } catch (_) {}
}

function hydrateDownloadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY) || '{}')
    trackedDownloadTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    downloadWorkbenchVisible.value = Boolean(raw.visible && trackedDownloadTaskIds.value.length)
    downloadWorkbenchBackgroundActive.value = Boolean(raw.background && trackedDownloadTaskIds.value.length)
  } catch (_) {
    trackedDownloadTaskIds.value = []
    downloadWorkbenchVisible.value = false
    downloadWorkbenchBackgroundActive.value = false
  }
}

function clearDownloadWorkbenchState() {
  trackedDownloadTaskIds.value = []
  trackedDownloadTasks.value = []
  downloadWorkbenchVisible.value = false
  downloadWorkbenchBackgroundActive.value = false
  stopDownloadWorkbenchPolling()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY)
  } catch (_) {}
}

function persistRefreshJobState() {
  try {
    if (!refreshJob.job_id) {
      localStorage.removeItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY)
      return
    }
    localStorage.setItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY, JSON.stringify({
      job_id: refreshJob.job_id,
      status: refreshJob.status,
      circle_id: refreshJob.circle_id,
      circle_name: refreshJob.circle_name,
      selected_count: refreshJob.selected_count,
      auto_hide_at: refreshJob.auto_hide_at,
      changed_codes: Array.isArray(refreshJob.changed_codes) ? refreshJob.changed_codes : [],
    }))
  } catch (_) {}
}

function hydrateRefreshJobState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY) || '{}')
    const status = String(raw.status || '').trim()
    // 终态：启动时直接清除，不常驻进度卡
    if (['completed', 'failed', 'cancelled'].includes(status) || isCancelledJobState(raw)) {
      clearRefreshJobState()
      return
    }
    refreshJob.visible = Boolean(raw.job_id)
    refreshJob.job_id = String(raw.job_id || '').trim()
    refreshJob.status = String(raw.status || '').trim()
    refreshJob.circle_id = String(raw.circle_id || '').trim()
    refreshJob.circle_name = String(raw.circle_name || '').trim()
    refreshJob.selected_count = Number(raw.selected_count || 0)
    refreshJob.auto_hide_at = String(raw.auto_hide_at || '').trim()
    refreshJob.changed_codes = Array.isArray(raw.changed_codes) ? raw.changed_codes.filter(Boolean) : []
  } catch (_) {
    clearRefreshJobState()
  }
}

function clearRefreshJobState() {
  refreshJob.visible = false
  refreshJob.job_id = ''
  refreshJob.status = ''
  refreshJob.progress = 0
  refreshJob.current_step = ''
  refreshJob.circle_id = ''
  refreshJob.circle_name = ''
  refreshJob.selected_count = 0
  refreshJob.elapsed_seconds = 0
  refreshJob.auto_hide_at = ''
  refreshJob.changed_codes = []
  refreshJob.error_message = ''
  refreshJob.meta = {}
  refreshJob.result = {}
  refreshJob.progress_log = []
  stopRefreshJobPolling()
  stopRefreshJobAutoHide()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY)
  } catch (_) {}
}

function stopRefreshJobAutoHide() {
  if (refreshJobAutoHideTimer) {
    window.clearTimeout(refreshJobAutoHideTimer)
    refreshJobAutoHideTimer = null
  }
}

function scheduleRefreshJobAutoHide(delayMs = 10000) {
  stopRefreshJobAutoHide()
  const targetAt = new Date(Date.now() + Math.max(0, Number(delayMs || 0))).toISOString()
  refreshJob.auto_hide_at = targetAt
  persistRefreshJobState()
  refreshJobAutoHideTimer = window.setTimeout(() => {
    clearRefreshJobState()
  }, Math.max(0, Number(delayMs || 0)))
}

function resumeRefreshJobAutoHide() {
  if (!refreshJob.auto_hide_at || refreshJob.status !== 'completed') return
  const remainMs = new Date(refreshJob.auto_hide_at).getTime() - Date.now()
  if (!Number.isFinite(remainMs) || remainMs <= 0) {
    clearRefreshJobState()
    return
  }
  stopRefreshJobAutoHide()
  refreshJobAutoHideTimer = window.setTimeout(() => {
    clearRefreshJobState()
  }, remainMs)
}

function stopDownloadWorkbenchPolling() {
  if (downloadWorkbenchTimer) {
    window.clearTimeout(downloadWorkbenchTimer)
    downloadWorkbenchTimer = null
  }
}

function startDownloadWorkbenchPolling() {
  if (!trackedDownloadTaskIds.value.length) return
  stopDownloadWorkbenchPolling()
  downloadWorkbenchTimer = window.setTimeout(() => {
    refreshDownloadWorkbench()
  }, 2000)
}

async function refreshDownloadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  if (!trackedDownloadTaskIds.value.length) {
    trackedDownloadTasks.value = []
    stopDownloadWorkbenchPolling()
    return
  }
  if (!silent) downloadWorkbenchRefreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    trackedDownloadTasks.value = trackedDownloadTaskIds.value
      .map(id => allTasks.find(task => task.id === id))
      .filter(Boolean)
    trackedDownloadTaskIds.value = trackedDownloadTasks.value.map(task => task.id)
    const stillActive = trackedDownloadTasks.value.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task.status || '')))
    if (stillActive || downloadWorkbenchVisible.value || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
    else stopDownloadWorkbenchPolling()
  } catch (error) {
    console.error('刷新社团补全下载工作台失败:', error)
    startDownloadWorkbenchPolling()
  } finally {
    if (!silent) downloadWorkbenchRefreshing.value = false
  }
}

function replaceTrackedDownloadTaskForSession(sessionId, nextTaskId) {
  const normalizedTaskId = String(nextTaskId || '').trim()
  if (!normalizedTaskId) return
  const normalizedSessionId = String(sessionId || '').trim()
  const sameSessionTaskIds = normalizedSessionId
    ? trackedDownloadTasks.value
      .filter(task => String(task?.task_metadata?.session_id || task?.session_id || '').trim() === normalizedSessionId)
      .map(task => String(task?.id || '').trim())
      .filter(Boolean)
    : []
  trackedDownloadTaskIds.value = [
    normalizedTaskId,
    ...trackedDownloadTaskIds.value.filter(id => id !== normalizedTaskId && !sameSessionTaskIds.includes(String(id || '').trim()))
  ]
}

function appendTrackedDownloadTask(nextTaskId) {
  const normalizedTaskId = String(nextTaskId || '').trim()
  if (!normalizedTaskId) return
  if (trackedDownloadTaskIds.value.includes(normalizedTaskId)) return
  trackedDownloadTaskIds.value = [normalizedTaskId, ...trackedDownloadTaskIds.value]
}

function canRetryDownloadTask(task) {
  const status = String(task?.status || '')
  return ['failed', 'partial_failed', 'waiting_retry'].includes(status)
}

async function retryDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const taskId = String(task?.id || '').trim()
  const next = new Set(retryingTaskIds.value)
  next.add(taskId)
  retryingTaskIds.value = next
  try {
    let nextTaskId = ''
    if (sessionId) {
      const response = await asmrSyncApi.retryFailedSession(sessionId)
      nextTaskId = String(response?.session?.task_id || '').trim()
      replaceTrackedDownloadTaskForSession(sessionId, nextTaskId)
    }
    else if (taskId) await asmrSyncApi.retry(taskId)
    else throw new Error('缺少任务标识')
    ElMessage.success('已提交重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(taskId)
    retryingTaskIds.value = done
  }
}

async function retryWaitingDownloadTask(task) {
  const taskId = String(task?.id || '').trim()
  if (!taskId) return
  const next = new Set(retryingTaskIds.value)
  next.add(`${taskId}:waiting`)
  retryingTaskIds.value = next
  try {
    await asmrSyncApi.retryWaiting(taskId)
    ElMessage.success('已立即重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '立即重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(`${taskId}:waiting`)
    retryingTaskIds.value = done
  }
}

async function retrySingleFailedFile(task, file) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const relativePath = String(file?.relative_path || '').trim()
  const key = `${task?.id}:${relativePath || file?.name || 'file'}`
  const next = new Set(retryingTaskIds.value)
  next.add(key)
  retryingTaskIds.value = next
  try {
    if (!sessionId || !relativePath) throw new Error('缺少会话或文件路径')
    const response = await asmrSyncApi.retrySessionFiles(sessionId, [relativePath])
    const nextTaskId = String(response?.session?.task_id || '').trim()
    appendTrackedDownloadTask(nextTaskId)
    ElMessage.success('已提交该文件重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交单文件重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(key)
    retryingTaskIds.value = done
  }
}

function handleRetrySingleFailedFile(payload) {
  retrySingleFailedFile(payload?.task, payload?.file)
}

async function handlePauseDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.pauseSession(sessionId)
    } else {
      const taskId = String(task?.active_task_id || task?.id || '').trim()
      if (taskId) await taskApi.pause(taskId)
    }
    ElMessage.success('已暂停')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '暂停失败')
  }
}

async function handleResumeDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.resumeSession(sessionId)
    } else {
      const taskId = String(task?.active_task_id || task?.id || '').trim()
      if (taskId) await taskApi.resume(taskId)
    }
    ElMessage.success('已恢复')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '恢复失败')
  }
}

async function handleCancelDownloadTask(task) {
  const rjcode = String(task?.rjcode || '').trim()
  const title = String(task?.work_title || task?.source_label || '').trim()
  try {
    await showSystemConfirm({
      title: '取消下载任务',
      message: `确定要取消 ${rjcode || title || '此任务'} 的下载吗？`,
      description: '取消后将停止下载并清理已下载的临时文件，此操作不可撤销。',
      tone: 'danger',
      confirmText: '取消下载',
    })
  } catch {
    return
  }
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
    } else {
      const taskIds = (task?.source_task_ids || [task?.active_task_id || task?.id]).filter(Boolean).map(String)
      if (taskIds.length) await taskApi.batchCancelCleanup(taskIds)
    }
    ElMessage.success('已取消并清理')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消失败')
  }
}

function buildReimportSourceFromWork(item) {
  const canonicalRjcode = String(item?.canonical_rjcode || item?.display_rjcode || '').trim().toUpperCase()
  const downloadRoot = String(item?.local_download_root || '').trim()
  return {
    canonical_rjcode: canonicalRjcode,
    session_id: String(item?.local_download_session_id || '').trim(),
    download_root: downloadRoot,
    rjcode: String(item?.display_rjcode || item?.canonical_rjcode || '').trim().toUpperCase(),
    circle_name: String(item?.circle_name || detail.circle_name || '').trim(),
    name: downloadRoot ? downloadRoot.split(/[\\/]/).filter(Boolean).pop() || canonicalRjcode : canonicalRjcode,
  }
}

function getDownloadSpeedBytes(task) {
  const runtimeSpeed = Number(getDownloadRuntime(task)?.speed_bytes_per_sec || 0)
  if (runtimeSpeed > 0) return runtimeSpeed
  if (isTaskFinished(task)) {
    const details = task?.performance_metrics || task?.task_metadata?.performance_metrics || {}
    return Number(details?.average_download_speed_bytes || 0)
  }
  return 0
}

function getDownloadEtaSeconds(task) {
  return Number(getDownloadRuntime(task)?.eta_seconds || 0)
}

function buildReimportSourceFromTask(task) {
  const metadata = task?.task_metadata || {}
  const downloadRoot = String(metadata?.local_download_root || '').trim()
  return {
    canonical_rjcode: String(metadata?.canonical_rjcode || task?.rjcode || metadata?.rjcode || '').trim().toUpperCase(),
    session_id: String(metadata?.session_id || task?.session_id || '').trim(),
    download_root: downloadRoot,
    rjcode: String(task?.rjcode || metadata?.rjcode || '').trim().toUpperCase(),
    circle_name: String(task?.circle_name || metadata?.circle_name || detail.circle_name || '').trim(),
    name: downloadRoot ? downloadRoot.split(/[\\/]/).filter(Boolean).pop() || String(task?.rjcode || metadata?.rjcode || '').trim().toUpperCase() : String(task?.rjcode || metadata?.rjcode || '').trim().toUpperCase(),
  }
}

function openLocalUploadDialogWithSources(sources = []) {
  const normalized = sources
    .filter(source => String(source?.download_root || '').trim())
    .map(source => ({
      ...source,
      path: String(source.download_root || '').trim(),
      name: String(source.name || '').trim() || String(source.rjcode || source.canonical_rjcode || '').trim(),
    }))
  if (!normalized.length) {
    ElMessage.error('当前任务缺少可复用的下载目录')
    return
  }
  localUploadSourceItems.value = normalized.map(source => ({
    name: source.name,
    path: source.path,
    circle_name: String(source.circle_name || '').trim(),
  }))
  localUploadForm.value = {
    targetLibraryId: localUploadForm.value.targetLibraryId || downloadSettings.targetLibraryId || targetLibraries.value.find(item => item?.type === 'synology_filestation')?.id || '',
    targetSubdir: localUploadForm.value.targetSubdir || downloadSettings.targetSubdir || ''
  }
  localUploadDialogVisible.value = true
}

function hideDownloadWorkbenchToBackground() {
  downloadWorkbenchVisible.value = false
  downloadWorkbenchBackgroundActive.value = true
}

function resumeDownloadWorkbenchFromBackground() {
  downloadWorkbenchVisible.value = true
  downloadWorkbenchBackgroundActive.value = false
}

function closeDownloadWorkbench() {
  clearDownloadWorkbenchState()
}

function handleDownloadBackgroundCardAction(action) {
  if (action === 'resume') {
    resumeDownloadWorkbenchFromBackground()
    return
  }
  if (action === 'close') {
    closeDownloadWorkbench()
  }
}

function stopRefreshJobPolling() {
  if (refreshJobTimer) {
    window.clearTimeout(refreshJobTimer)
    refreshJobTimer = null
  }
}

function stopIndexJobPolling() {
  if (indexJobTimer) {
    window.clearTimeout(indexJobTimer)
    indexJobTimer = null
  }
}

function applyIndexJob(payload = {}) {
  indexJob.visible = true
  indexJob.job_id = payload.job_id || ''
  indexJob.status = payload.status || ''
  indexJob.progress = Number(payload.progress || 0)
  indexJob.current_step = payload.current_step || ''
  indexJob.circle_query = payload.circle_query || ''
  indexJob.elapsed_seconds = Number(payload.elapsed_seconds || 0)
  indexJob.error_message = payload.error_message || ''
  indexJob.meta = payload.meta || {}
  persistIndexJobState()
}

function applyRefreshJob(payload = {}) {
  refreshJob.visible = true
  refreshJob._retryCount = 0
  refreshJob.job_id = payload.job_id || refreshJob.job_id || ''
  refreshJob.status = payload.status || ''
  refreshJob.progress = Number(payload.progress || 0)
  refreshJob.current_step = payload.current_step || ''
  refreshJob.circle_id = payload.circle_id || ''
  refreshJob.circle_name = payload.circle_name || ''
  refreshJob.selected_count = Number(payload.selected_count || 0)
  refreshJob.elapsed_seconds = Number(payload.elapsed_seconds || 0)
  refreshJob.auto_hide_at = payload.auto_hide_at || refreshJob.auto_hide_at || ''
  refreshJob.changed_codes = Array.isArray(payload.changed_codes) ? payload.changed_codes.filter(Boolean) : (Array.isArray(refreshJob.changed_codes) ? refreshJob.changed_codes : [])
  refreshJob.error_message = payload.error_message || ''
  refreshJob.meta = payload.meta || {}
  refreshJob.result = payload.result || {}
  refreshJob.progress_log = Array.isArray(payload.progress_log) ? payload.progress_log : []
  if (refreshJob.status !== 'completed') {
    stopRefreshJobAutoHide()
    refreshJob.auto_hide_at = ''
  }
  persistRefreshJobState()
}

async function pollIndexJob(jobId) {
  stopIndexJobPolling()
  try {
    const result = await circleCompletionApi.getIndexJobStatus(jobId)
    applyIndexJob(result)
    if (result.status === 'completed') {
      clearIndexJobState()
      activeCircleId.value = result.circle_id || result.result?.circle_id || ''
      await Promise.all([loadRecentCircles(), refreshActiveCircle()])
      const onlyNewWorks = Boolean(result.meta?.only_new_works)
      const newlyIndexedCount = Number(result.result?.incremental?.newly_indexed_count || result.meta?.newly_indexed_count || 0)
      if (result.meta?.is_batch) {
        ElMessage.success(`批量社团补全完成，成功 ${result.meta.completed_queries || 0} 个，失败 ${result.meta.failed_queries || 0} 个`)
      } else {
        ElMessage.success(onlyNewWorks ? `新作索引完成，新增 ${newlyIndexedCount} 个作品` : '社团索引已刷新')
      }
      return
    }
    if (result.status === 'failed') {
      indexing.value = false
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        clearIndexJobState()
        ElMessage.info('社团索引已取消')
      } else {
        persistIndexJobState()
        ElMessage.error(result.error_message || '社团索引失败')
      }
      return
    }
    indexJobTimer = window.setTimeout(() => {
      pollIndexJob(jobId)
    }, 800)
  } catch (error) {
    indexing.value = false
    // 404 说明任务已不存在（后端重启），直接清除进度卡
    if (error?.response?.status === 404) {
      clearIndexJobState()
      return
    }
    persistIndexJobState()
    ElMessage.error(error.response?.data?.detail || '查询社团索引进度失败')
  }
}

async function pollRefreshJob(jobId, options = {}) {
  stopRefreshJobPolling()
  const silentFinish = Boolean(options?.silentFinish)
  try {
    const result = await circleCompletionApi.getRefreshSelectedJobStatus(jobId)
    applyRefreshJob(result)
    if (result.status === 'completed') {
      refreshingCurrentCircle.value = false
      await Promise.all([refreshActiveCircle(), loadRecentCircles()])
      const changedCodes = (Array.isArray(result.result?.items) ? result.result.items : [])
        .filter(item => item?.changed)
        .map(item => item.canonical_rjcode)
      prioritizeChangedWorks(changedCodes)
      flashChangedWorks(changedCodes)
      refreshJob.current_step = `批量刷新完成，${changedCodes.length} 个状态变更，10 秒后自动隐藏`
      refreshJob.status = 'completed'
      refreshJob.progress = 100
      refreshJob.error_message = ''
      refreshJob.meta = {
        ...(refreshJob.meta || {}),
        changed_count: changedCodes.length,
      }
      refreshJob.changed_codes = changedCodes
      scheduleRefreshJobAutoHide(10000)
      if (!silentFinish) {
        ElMessage.success(`已刷新 ${result.result?.refreshed_count || result.meta?.processed_count || refreshJob.selected_count || 0} 个作品`)
      }
      return
    }
    if (result.status === 'failed') {
      refreshingCurrentCircle.value = false
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        ElMessage.info('批量刷新已取消')
      } else if (!silentFinish) {
        ElMessage.error(result.error_message || '批量刷新失败')
      }
      clearRefreshJobState()
      return
    }
    refreshJobTimer = window.setTimeout(() => {
      pollRefreshJob(jobId, { silentFinish: true })
    }, 1000)
  } catch (error) {
    refreshingCurrentCircle.value = false
    // 404 说明任务已不存在（后端重启），直接清除进度卡
    if (error?.response?.status === 404) {
      clearRefreshJobState()
      return
    }
    refreshJob._retryCount = (refreshJob._retryCount || 0) + 1
    if (refreshJob._retryCount >= 10) {
      // 连续10次失败（约20秒），放弃轮询，清除进度卡
      clearRefreshJobState()
      return
    }
    if (!silentFinish) {
      ElMessage.error(error.response?.data?.detail || '查询批量刷新进度失败')
    }
    refreshJobTimer = window.setTimeout(() => {
      pollRefreshJob(jobId, { silentFinish: true })
    }, 2000)
  }
}

async function cancelIndexJob() {
  if (!indexJob.job_id || cancellingIndexJob.value) return
  cancellingIndexJob.value = true
  try {
    await api.task.cancel(indexJob.job_id)
    clearIndexJobState()
    ElMessage.success('已发送取消请求')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消社团索引失败')
  } finally {
    cancellingIndexJob.value = false
  }
}

async function cancelRefreshJob() {
  if (!refreshJob.job_id || cancellingRefreshJob.value) return
  cancellingRefreshJob.value = true
  try {
    await api.task.cancel(refreshJob.job_id)
    refreshingCurrentCircle.value = false
    clearRefreshJobState()
    ElMessage.success('已发送取消请求')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消批量刷新失败')
  } finally {
    cancellingRefreshJob.value = false
  }
}

async function loadRecentCircles() {
  const result = await circleCompletionApi.listRecentIndexes(24)
  circleList.value = result.circles || []
  await syncActiveCircleWithList()
}

async function loadLibraries() {
  try {
    const result = await libraryApi.listLibraries()
    libraries.value = result.libraries || []
    if (!downloadSettings.targetLibraryId) {
      const preferred = libraries.value.find(item => item?.is_default) || libraries.value[0]
      downloadSettings.targetLibraryId = preferred?.id || ''
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载库存列表失败')
  }
}

async function searchCachedCircles() {
  const requestSeq = ++circleSearchRequestSeq.value
  const keyword = String(circleSearch.value || '').trim()
  const result = await circleCompletionApi.searchCircles(keyword, 24)
  if (requestSeq !== circleSearchRequestSeq.value) {
    return
  }
  circleList.value = result.circles || []
  await syncActiveCircleWithList({ preserveActiveWhenEmpty: Boolean(keyword) })
}

function scheduleCircleDetailPrefetch() {
  if (circleDetailPrefetchTimer) {
    window.clearTimeout(circleDetailPrefetchTimer)
    circleDetailPrefetchTimer = null
  }
  circleDetailPrefetchTimer = window.setTimeout(() => {
    circleDetailPrefetchTimer = null
    prefetchNeighborCircleDetails().catch(() => {})
  }, 450)
}

async function prefetchNeighborCircleDetails() {
  if (circleDetailPrefetchRunning || circleDetailLoading.value) return
  const list = Array.isArray(displayCircleList.value) ? displayCircleList.value : []
  if (!list.length || !activeCircleId.value) return
  const activeIndex = list.findIndex(circle => String(circle?.circle_id || '') === activeCircleId.value)
  if (activeIndex < 0) return
  const candidates = [
    ...list.slice(activeIndex + 1, activeIndex + 1 + CIRCLE_DETAIL_PREFETCH_LIMIT),
    ...list.slice(Math.max(0, activeIndex - 1), activeIndex),
  ]
    .map(circle => String(circle?.circle_id || '').trim())
    .filter(circleId => circleId && circleId !== activeCircleId.value && !hasFreshCircleDetailCache(circleId))

  if (!candidates.length) return
  circleDetailPrefetchRunning = true
  try {
    for (const circleId of candidates.slice(0, CIRCLE_DETAIL_PREFETCH_LIMIT)) {
      if (hasFreshCircleDetailCache(circleId)) continue
      const result = await circleCompletionApi.getCircleDetail(circleId, {
        includeDlOnly: filters.includeDlOnly
      })
      setCachedCircleDetail(circleId, result)
    }
  } finally {
    circleDetailPrefetchRunning = false
  }
}

async function handleIndexCircle() {
  await startIndexCircleJob({
    circleQuery: circleQuery.value.trim(),
    onlyNewWorks: false
  })
}

async function handleEmailCheck() {
  if (emailCheckLoading.value) return
  emailCheckLoading.value = true
  try {
    const result = await emailWatcherApi.pollNow()
    if (result.success) {
      ElMessage({ type: result.count > 0 ? 'success' : 'info', message: result.message || '检查完成' })
    } else {
      ElMessage({ type: 'warning', message: result.message || '邮件检查失败，请检查设置页的邮件监听配置' })
    }
  } catch (e) {
    ElMessage({ type: 'error', message: '邮件检查请求失败，请确认后端已启动且已配置邮件监听' })
  } finally {
    emailCheckLoading.value = false
  }
}

function normalizeBatchCircleQueries(text = '') {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(item => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

async function openBatchIndexPrompt() {
  try {
    const value = await showSystemPrompt({
      title: '批量创建社团补全',
      description: '手动输入社团名，一行一个，提交后会按顺序批量执行社团补全。',
      badge: '社团补全',
      mode: 'prompt',
      inputType: 'textarea',
      width: 680,
      closeOnClickModal: false,
      placeholder: '例如：\nリリムワークス/兎月りりむ。\n耳かき屋\nしろくまだんご',
      confirmText: '开始批量补全',
      cancelText: '取消',
      validator: value => {
        const queries = normalizeBatchCircleQueries(value)
        if (!queries.length) return '至少输入一个社团名'
        if (queries.length > 100) return '一次最多提交 100 个社团'
        return true
      }
    })
    const circleQueries = normalizeBatchCircleQueries(value)
    await startIndexCircleJob({
      circleQueries,
      onlyNewWorks: false
    })
  } catch (_) {}
}

async function handleIndexOnlyNewWorks() {
  const targetQuery = String(detail.circle_name || circleQuery.value || '').trim()
  await startIndexCircleJob({
    circleQuery: targetQuery,
    onlyNewWorks: true
  })
}

async function startIndexCircleJob({ circleQuery: targetQuery, circleQueries: rawCircleQueries = [], onlyNewWorks = false } = {}) {
  const normalizedQueries = Array.isArray(rawCircleQueries)
    ? rawCircleQueries.map(item => String(item || '').trim()).filter(Boolean)
    : []
  if (!normalizedQueries.length && !String(targetQuery || '').trim()) {
    ElMessage.warning('先输入社团名')
    return
  }
  const finalCircleQueries = normalizedQueries.length ? normalizedQueries : [String(targetQuery || '').trim()]
  indexing.value = true
  try {
    const result = await circleCompletionApi.startIndexCircle({
      circle_query: finalCircleQueries[0],
      circle_queries: finalCircleQueries,
      // 只索引新作时让 metadata / canonical 缓存生效，避免每次都把整社团 DLsite 列表重爬一遍；
      // "建立 / 刷新索引"路径仍走 force_refresh，符合用户主动"刷新"的语义。
      force_refresh: !onlyNewWorks,
      include_dlsite: true,
      include_kikoeru: true,
      only_new_works: Boolean(onlyNewWorks)
    })
    applyIndexJob(result)
    await pollIndexJob(result.job_id)
  } catch (error) {
    indexing.value = false
    persistIndexJobState()
    ElMessage.error(error.response?.data?.detail || '启动社团索引失败')
  }
}

async function refreshSelectedCircleIndex(targetCodes = null) {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  const codes = (Array.isArray(targetCodes) ? targetCodes : selectedCanonicalRJCodes.value)
    .map(code => String(code || '').trim())
    .filter(Boolean)
  if (!codes.length) {
    ElMessage.warning('先选中要刷新的作品')
    return
  }
  if (isRefreshJobActive.value) {
    ElMessage.warning('已有批量刷新任务在跑')
    return
  }
  refreshingCurrentCircle.value = true
  try {
    const result = await circleCompletionApi.startRefreshSelectedWorks({
      circle_id: circleId,
      circle_name: detail.circle_name || '',
      canonical_rjcodes: codes,
      force_refresh: false
    })
    applyRefreshJob(result)
    if (result.meta?.force_refresh) {
      ElMessage.info(result.meta.force_refresh_reason === 'auto_threshold'
        ? '1 分钟内连续刷新达到 3 次，本次已自动强制刷新并跳过缓存'
        : '本次已使用强制刷新')
    }
    await pollRefreshJob(result.job_id)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量刷新选中作品失败')
  } finally {
    if (!isRefreshJobActive.value) {
      refreshingCurrentCircle.value = false
    }
  }
}

async function selectCircle(circleId) {
  const targetCircleId = String(circleId || '').trim()
  if (!targetCircleId) return
  if (activeCircleId.value === targetCircleId && circleDetailLoaded.value && !circleDetailLoading.value) {
    return
  }

  activeCircleId.value = targetCircleId
  selectedCanonicals.value = new Set()
  flashedWorkCodes.value = new Set()
  missingPage.value = 1
  ownedPage.value = 1
  comparePage.value = 1

  const cached = getCachedCircleDetail(targetCircleId)
  if (cached) {
    applyCircleDetailPayload(cached)
    circleDetailLoading.value = false
    scheduleCircleDetailPrefetch()
    return
  }

  applyCircleSummaryPlaceholder(targetCircleId)
  await refreshActiveCircle({ preferCache: true })
}

async function refreshActiveCircle(options = {}) {
  if (!activeCircleId.value) return
  const { preferCache = false } = options
  const requestCircleId = String(activeCircleId.value || '').trim()
  if (!requestCircleId) return

  if (preferCache) {
    const cached = getCachedCircleDetail(requestCircleId)
    if (cached) {
      applyCircleDetailPayload(cached)
      circleDetailLoading.value = false
      scheduleCircleDetailPrefetch()
      return
    }
  } else {
    invalidateCircleDetailCache(requestCircleId)
  }

  const requestSeq = ++circleDetailRequestSeq
  if (circleDetailAbortController) {
    circleDetailAbortController.abort()
  }
  circleDetailAbortController = new AbortController()
  circleDetailLoading.value = true
  try {
    const result = await circleCompletionApi.getCircleDetail(requestCircleId, {
      includeDlOnly: filters.includeDlOnly,
      signal: circleDetailAbortController.signal
    })
    if (requestSeq !== circleDetailRequestSeq || activeCircleId.value !== requestCircleId) return
    setCachedCircleDetail(requestCircleId, result)
    applyCircleDetailPayload(result)
    scheduleCircleDetailPrefetch()
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    ElMessage.error(error.response?.data?.detail || '加载社团详情失败')
  } finally {
    if (requestSeq === circleDetailRequestSeq) {
      circleDetailLoading.value = false
      circleDetailAbortController = null
    }
  }
}

function toggleSelection(item) {
  if (!item?.canonical_rjcode) return
  const next = new Set(selectedCanonicals.value)
  if (next.has(item.canonical_rjcode)) next.delete(item.canonical_rjcode)
  else next.add(item.canonical_rjcode)
  selectedCanonicals.value = next
}

function selectAllVisibleWorks() {
  selectedCanonicals.value = new Set(
    activeSelectableWorks.value.map(item => item.canonical_rjcode).filter(Boolean)
  )
}

function clearSelection() {
  selectedCanonicals.value = new Set()
}

function openReimportDialogForWork(item) {
  if (!String(item?.local_download_root || '').trim()) {
    ElMessage.error('本地下载目录不存在，无法直接入库')
    return
  }
  const source = buildReimportSourceFromWork(item)
  openLocalUploadDialogWithSources([source])
}

function openLocalUploadDialogForTask(task) {
  const source = buildReimportSourceFromTask(task)
  openLocalUploadDialogWithSources([source])
}

async function openBatchPreview(singleCanonical = '') {
  const codes = singleCanonical ? [singleCanonical] : selectedActiveDownloadableRJCodes.value
  if (!codes.length) {
    ElMessage.warning(singleCanonical ? '当前作品没有可下载资源' : '选中的作品里没有可下载项')
    return
  }
  previewing.value = true
  previewDialogVisible.value = true
  previewLoading.value = true
  previewPlans.value = []
  try {
    const result = await circleCompletionApi.previewBatchDownload({
      circle_id: detail.circle_id,
      canonical_rjcodes: codes,
      requested_rjcodes: getPreviewRequestedRjcodes(codes)
    })
    previewPlans.value = result.plans || []
    downloadSettings.downloadBasePath = result.download_base_path || downloadSettings.downloadBasePath || ''
    if (!downloadSettings.targetLibraryId) {
      downloadSettings.targetLibraryId = result.default_target_library_id || downloadSettings.targetLibraryId
    }
    if (!downloadSettings.targetSubdir) {
      downloadSettings.targetSubdir = result.default_target_subdir || ''
    }
  } catch (error) {
    previewDialogVisible.value = false
    ElMessage.error(error.response?.data?.detail || '生成下载预览失败')
  } finally {
    previewing.value = false
    previewLoading.value = false
  }
}
async function startBatchDownload(payload = {}) {
  const items = Array.isArray(payload.items) ? payload.items : []
  if (!items.length) {
    ElMessage.warning('没有选中任何文件')
    return
  }

  starting.value = true
  try {
    const result = await circleCompletionApi.startBatchDownload({
      circle_id: detail.circle_id,
      circle_name: detail.circle_name,
      batch_options: payload.batchOptions || {},
      items
    })
    rememberTargetSubdir(downloadSettings.targetSubdir || '')
    trackedDownloadTaskIds.value = (result.tasks || []).map(item => item.task_id).filter(Boolean)
    downloadWorkbenchVisible.value = trackedDownloadTaskIds.value.length > 0
    downloadWorkbenchBackgroundActive.value = false
    persistDownloadWorkbenchState()
    await refreshDownloadWorkbench()
    ElMessage.success(result.message || '下载任务已创建')
    previewDialogVisible.value = false
    await refreshActiveCircle()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '创建下载任务失败')
  } finally {
    starting.value = false
  }
}

async function submitLocalUpload(payload = {}) {
  const selectedPaths = Array.isArray(payload?.selected_paths) ? payload.selected_paths.filter(Boolean) : []
  const targetLibraryId = String(payload?.target_library_id || localUploadForm.value.targetLibraryId || '').trim()
  const targetSubdir = String(payload?.target_subdir || localUploadForm.value.targetSubdir || '').trim()
  const sourceBasePath = localUploadSourceItems.value.length === 1
    ? String(localUploadSourceItems.value[0]?.path || '').trim()
    : String(commonAncestorPath(selectedPaths) || '').trim()

  if (!selectedPaths.length) return ElMessage.warning('请先选中要上传的目录')
  if (!targetLibraryId) return ElMessage.warning('请选择目标服务器库存')
  if (!sourceBasePath) return ElMessage.warning('缺少来源目录')

  localUploadForm.value = { targetLibraryId, targetSubdir }
  localUploadSubmitting.value = true
  try {
    const createdTaskIds = []
    for (const selectedPath of selectedPaths) {
      const result = await localUploadApi.start({
        source_library_id: '',
        source_base_path: sourceBasePath,
        selected_paths: [selectedPath],
        target_library_id: targetLibraryId,
        target_subdir: targetSubdir,
        circle_name: getLocalUploadCircleNameForPath(selectedPath)
      })
      if (result?.task_id) rememberUploadTaskId(result.task_id)
      if (result?.task_id) createdTaskIds.push(result.task_id)
    }
    rememberTargetSubdir(targetSubdir || '')
    downloadSettings.targetLibraryId = targetLibraryId
    downloadSettings.targetSubdir = targetSubdir
    uploadWorkbenchVisible.value = true
    uploadWorkbenchBackgroundActive.value = false
    localUploadDialogVisible.value = false
    persistUploadWorkbenchState()
    await refreshUploadWorkbench({ silent: true })
    ElMessage.success(`已创建 ${createdTaskIds.length || selectedPaths.length} 个直接入库上传任务`)
    await refreshActiveCircle()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '直接入库上传失败')
  } finally {
    localUploadSubmitting.value = false
  }
}

function normalizeLocalUploadComparePath(path) {
  return String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/g, '').toLowerCase()
}

function isLocalUploadPathInside(sourcePath, selectedPath) {
  const source = normalizeLocalUploadComparePath(sourcePath)
  const selected = normalizeLocalUploadComparePath(selectedPath)
  if (!source || !selected) return false
  return selected === source || selected.startsWith(`${source}/`)
}

function getLocalUploadCircleNameForPath(selectedPath) {
  const matchedSource = localUploadSourceItems.value
    .filter(source => isLocalUploadPathInside(source?.path, selectedPath))
    .sort((left, right) => normalizeLocalUploadComparePath(right?.path).length - normalizeLocalUploadComparePath(left?.path).length)[0]
  return String(matchedSource?.circle_name || detail.circle_name || '').trim()
}

function commonAncestorPath(paths = []) {
  const normalized = paths.map(path => String(path || '').trim()).filter(Boolean)
  if (!normalized.length) return ''
  const splitPaths = normalized.map(path => path.replace(/\\/g, '/').split('/'))
  const first = splitPaths[0]
  const shared = []
  for (let index = 0; index < first.length; index += 1) {
    const segment = first[index]
    if (splitPaths.every(parts => parts[index] === segment)) shared.push(segment)
    else break
  }
  return shared.join('/').replace(/^([A-Za-z]:)$/, '$1/')
}

function persistUploadWorkbenchState() {
  try {
    localStorage.setItem(CIRCLE_COMPLETION_UPLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: trackedUploadTaskIds.value,
      visible: uploadWorkbenchVisible.value,
      background: uploadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function restoreUploadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_UPLOAD_WORKBENCH_KEY) || '{}')
    trackedUploadTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    uploadWorkbenchVisible.value = Boolean(raw.visible && trackedUploadTaskIds.value.length)
    uploadWorkbenchBackgroundActive.value = Boolean(raw.background && trackedUploadTaskIds.value.length)
  } catch (_) {
    trackedUploadTaskIds.value = []
    uploadWorkbenchVisible.value = false
    uploadWorkbenchBackgroundActive.value = false
  }
}

let uploadWorkbenchTimer = null
function stopUploadWorkbenchPolling() {
  if (uploadWorkbenchTimer) {
    window.clearTimeout(uploadWorkbenchTimer)
    uploadWorkbenchTimer = null
  }
}

function startUploadWorkbenchPolling() {
  if (!trackedUploadTaskIds.value.length) return
  stopUploadWorkbenchPolling()
  uploadWorkbenchTimer = window.setTimeout(() => {
    refreshUploadWorkbench({ silent: true })
  }, 2000)
}

function rememberUploadTaskId(nextTaskId) {
  const normalized = String(nextTaskId || '').trim()
  if (!normalized || trackedUploadTaskIds.value.includes(normalized)) return
  trackedUploadTaskIds.value = [normalized, ...trackedUploadTaskIds.value]
}

async function refreshUploadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  if (!trackedUploadTaskIds.value.length) {
    trackedUploadTasks.value = []
    stopUploadWorkbenchPolling()
    persistUploadWorkbenchState()
    return
  }
  if (!silent) uploadWorkbenchRefreshing.value = true
  try {
    const result = await localUploadApi.status({
      task_ids: trackedUploadTaskIds.value.join(','),
      include_hidden: true
    })
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    const nextTrackedTasks = trackedUploadTaskIds.value
      .map(id => allTasks.find(task => String(task?.id || '') === String(id || '')))
      .filter(Boolean)
    trackedUploadTasks.value = nextTrackedTasks
    if (nextTrackedTasks.length) {
      trackedUploadTaskIds.value = nextTrackedTasks.map(task => task.id)
    }
    const justCompleted = trackedUploadTasks.value.some(task => ['completed', 'failed'].includes(String(task?.status || '')))
    if (justCompleted && activeCircleId.value) {
      await refreshActiveCircle()
    }
    const stillActive = trackedUploadTasks.value.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))
    if (stillActive || uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
    else stopUploadWorkbenchPolling()
    persistUploadWorkbenchState()
  } catch (error) {
    if (!silent) ElMessage.error(error.response?.data?.detail || error.message || '获取上传任务失败')
    if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  } finally {
    if (!silent) uploadWorkbenchRefreshing.value = false
  }
}

function hideUploadWorkbenchToBackground() {
  uploadWorkbenchVisible.value = false
  uploadWorkbenchBackgroundActive.value = true
  persistUploadWorkbenchState()
}

function resumeUploadWorkbenchFromBackground() {
  uploadWorkbenchBackgroundActive.value = false
  uploadWorkbenchVisible.value = true
  persistUploadWorkbenchState()
}

async function closeUploadWorkbench() {
  uploadWorkbenchVisible.value = false
  uploadWorkbenchBackgroundActive.value = false
  trackedUploadTaskIds.value = []
  trackedUploadTasks.value = []
  stopUploadWorkbenchPolling()
  persistUploadWorkbenchState()
}

function handleUploadBackgroundCardAction(action) {
  if (action === 'resume') {
    resumeUploadWorkbenchFromBackground()
    return
  }
  if (action === 'close') {
    closeUploadWorkbench()
  }
}

function getUploadBackgroundSpeed(task) {
  const runtime = task?.upload_runtime || {}
  return Number(runtime?.speed_bytes_per_sec || runtime?.last_non_zero_speed_bytes_per_sec || 0)
}

function getUploadBackgroundTargetLabel(task) {
  return String(task?.task_metadata?.final_output_path || task?.task_metadata?.target_path || task?.output_path || '目标路径处理中').trim()
}
</script>

<style scoped>
.circle-page {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  background: #fafafa;
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}

.circle-works-loading-state {
  position: relative;
  display: grid;
  place-items: center;
  gap: 18px;
  min-height: 430px;
  margin-top: 8px;
  overflow: hidden;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.download-settings-card {
  display: grid;
  gap: 14px;
  padding: 20px 22px;
  border: 1px solid rgba(255, 255, 255, 0.48);
  border-radius: 26px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.64) 0%, rgba(244, 248, 255, 0.44) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.62),
    0 18px 36px rgba(78, 104, 146, 0.14);
  backdrop-filter: blur(18px);
}
.download-settings-head {
  display: grid;
  gap: 4px;
}
.download-settings-title {
  font-size: 15px;
  font-weight: 800;
  color: #1f3759;
}
.download-settings-subtitle {
  font-size: 12px;
  color: #6b7f98;
}
.download-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}
.setting-field {
  display: grid;
  gap: 6px;
}
.setting-field-wide {
  grid-column: 1 / -1;
}
.setting-label {
  font-size: 12px;
  font-weight: 700;
  color: #55708f;
}
.setting-pill,
.setting-hint {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.setting-pill {
  color: #35577f;
  background: #edf4ff;
  border: 1px solid #d7e4fb;
}
.setting-pill.ok {
  color: #11754f;
  background: #eefaf3;
  border-color: #ccefd8;
}
.setting-pill.warning {
  color: #9a5a07;
  background: #fff6e8;
  border-color: #f4dfb0;
}
.setting-pill.danger {
  color: #b44535;
  background: #fff1ef;
  border-color: #f4cbc4;
}
.setting-hint {
  color: #4f6684;
  background: #f4f6fa;
  border: 1px solid #e3e8f0;
}
.workbench-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 18px;
}
.workbench-summary {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.workbench-stat {
  display: grid;
  gap: 4px;
  min-width: 92px;
  padding: 10px 12px;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f3f8ff 100%);
  border: 1px solid #dce9fb;
  box-shadow: 0 8px 18px rgba(62, 102, 168, 0.08);
}
.workbench-stat.danger {
  background: linear-gradient(180deg, #fff8f7 0%, #fff1ef 100%);
  border-color: #ffd8d4;
}
.workbench-stat-label {
  font-size: 11px;
  font-weight: 700;
  color: #71839c;
}
.workbench-stat-value {
  font-size: 22px;
  line-height: 1;
  color: #1f3759;
}
.workbench-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.workbench-action-btn {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
  transition: transform .16s ease, box-shadow .2s ease, background .2s ease, border-color .2s ease, color .2s ease;
}
.workbench-action-btn::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, rgba(255,255,255,0) 18%, rgba(255,255,255,0.28) 50%, rgba(255,255,255,0) 82%);
  opacity: 0;
  transform: translateX(-24%);
  transition: opacity .18s ease, transform .28s ease;
  pointer-events: none;
}
.workbench-action-btn:hover {
  transform: translateY(-1px);
}
.workbench-action-btn:hover::after {
  opacity: 1;
  transform: translateX(14%);
}
.workbench-action-btn:active {
  transform: translateY(0) scale(0.985);
}
.workbench-action-btn.is-refresh {
  background: linear-gradient(180deg, #f5f9ff 0%, #e7f0ff 100%);
  border-color: #c4d8fb;
  color: #1d5fbc;
  box-shadow: 0 8px 16px rgba(39, 101, 190, 0.10);
}
.workbench-action-btn.is-refresh:hover {
  background: linear-gradient(180deg, #e8f3ff 0%, #d6e8ff 100%);
  border-color: #9fc4ff;
  color: #0f56b8;
  box-shadow: 0 12px 22px rgba(28, 95, 188, 0.16);
}
.workbench-action-btn.is-background {
  background: linear-gradient(180deg, #ffffff 0%, #f3f6fb 100%);
  border-color: #d5dfeb;
  color: #5a6f89;
  box-shadow: 0 6px 14px rgba(83, 101, 132, 0.08);
}
.workbench-action-btn.is-background:hover {
  background: linear-gradient(180deg, #f8fbff 0%, #e9eff7 100%);
  border-color: #b9cde3;
  color: #425977;
  box-shadow: 0 10px 18px rgba(83, 101, 132, 0.12);
}
.workbench-action-btn.is-close {
  background: linear-gradient(180deg, #fff9f8 0%, #ffefec 100%);
  border-color: #efc8c2;
  color: #b84d40;
  box-shadow: 0 6px 14px rgba(184, 77, 64, 0.08);
}
.workbench-action-btn.is-close:hover {
  background: linear-gradient(180deg, #fff1ee 0%, #ffe2dd 100%);
  border-color: #e2aea6;
  color: #a33a2e;
  box-shadow: 0 10px 18px rgba(184, 77, 64, 0.14);
}
.download-task-list {
  display: grid;
  gap: 14px;
  max-height: 68vh;
  overflow: auto;
  padding-right: 4px;
}
.download-task-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border-radius: 20px;
  border: 1px solid #dfebfb;
  background:
    radial-gradient(circle at top right, rgba(92, 154, 255, 0.12), transparent 24%),
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  box-shadow: 0 14px 28px rgba(45, 86, 145, 0.08);
}
.download-task-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.download-task-heading {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.download-task-rj {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #3070d8;
}
.download-task-rj-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.download-state-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .02em;
}
.download-state-chip.is-downloaded {
  background: linear-gradient(180deg, #effcf3 0%, #e4f7eb 100%);
  border: 1px solid #bfe7cb;
  color: #22824d;
}
.download-task-title {
  font-size: 19px;
  line-height: 1.4;
  font-weight: 800;
  color: #1d3557;
  word-break: break-word;
}
.download-task-step {
  font-size: 13px;
  font-weight: 700;
  color: #51657f;
}
.download-task-error {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: linear-gradient(180deg, #fff7f5 0%, #fff1ee 100%);
  border: 1px solid #ffd8d1;
}
.download-task-error-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #b94a3a;
}
.download-task-error-text {
  font-size: 13px;
  line-height: 1.6;
  color: #8f3427;
  word-break: break-word;
}
.download-task-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: -2px;
}
.download-failed-list {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid #f2d7d2;
  background: linear-gradient(180deg, #fffaf9 0%, #fff4f2 100%);
}
.download-failed-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(232, 191, 182, 0.58);
}
.download-failed-main {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.download-failed-reason {
  font-size: 12px;
  color: #9b4a40;
  line-height: 1.5;
  word-break: break-word;
}
.download-task-action-btn {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid #d4dfec;
  background: linear-gradient(180deg, #ffffff 0%, #f4f7fb 100%);
  color: #566b86;
  font-size: 12px;
  font-weight: 800;
  transition: transform .16s ease, box-shadow .2s ease, border-color .2s ease, background .2s ease, color .2s ease;
}
.download-task-action-btn:hover {
  transform: translateY(-1px);
  background: linear-gradient(180deg, #fbfdff 0%, #ebf1f8 100%);
  border-color: #c0d2e6;
  color: #425b79;
  box-shadow: 0 10px 18px rgba(77, 100, 132, 0.10);
}
.download-task-action-btn.is-primary {
  border-color: #c6d9fb;
  background: linear-gradient(180deg, #f4f9ff 0%, #e7f0ff 100%);
  color: #1b60c3;
}
.download-task-action-btn.is-primary:hover {
  background: linear-gradient(180deg, #e9f3ff 0%, #d9e9ff 100%);
  border-color: #aac8fa;
  color: #0f56b8;
  box-shadow: 0 12px 20px rgba(27, 96, 195, 0.14);
}
.download-task-action-btn.is-upload {
  border-color: #bfe2cb;
  background: linear-gradient(180deg, #f1fbf4 0%, #e6f7eb 100%);
  color: #21814c;
}
.download-task-action-btn.is-upload:hover {
  background: linear-gradient(180deg, #e8f7ed 0%, #d9f1e1 100%);
  border-color: #9fd3b1;
  color: #186e3f;
  box-shadow: 0 12px 20px rgba(33, 129, 76, 0.14);
}
.download-task-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.download-task-meta-item {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(244, 248, 254, 0.9);
  border: 1px solid #e1eaf7;
}
.download-task-meta-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #7486a0;
}
.download-task-meta-value {
  font-size: 13px;
  line-height: 1.5;
  color: #294563;
  word-break: break-all;
}
.download-file-list {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  background: #f6f9fd;
  border: 1px solid #e3ebf6;
}
.download-file-list.upload-stage {
  background: #f4fcf7;
  border-color: #d9efe1;
}
.download-file-title {
  font-size: 12px;
  font-weight: 800;
  color: #526983;
}
.download-result-list,
.download-log-list {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: 16px;
  background: #fbfcfe;
  border: 1px solid #e6edf7;
}
.download-result-item {
  display: grid;
  gap: 4px;
}
.download-result-name {
  font-size: 13px;
  font-weight: 700;
  color: #294563;
}
.download-result-path {
  font-size: 12px;
  color: #69809a;
  word-break: break-all;
}
.download-log-item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  line-height: 1.6;
}
.download-log-time {
  color: #7a8ca4;
  font-weight: 700;
}
.download-log-message {
  color: #4f6684;
  word-break: break-word;
}
.download-log-item.error .download-log-message {
  color: #b44535;
}
.download-log-item.success .download-log-message {
  color: #17704a;
}
.download-file-item {
  display: grid;
  gap: 8px;
}
.download-file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.download-file-name {
  min-width: 0;
  font-size: 13px;
  color: #294563;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.download-file-size {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: #6a7e97;
}
/* .circle-download-floating-* 已迁移至 index.css 全局 .floating-card 规范 */
:deep(.circle-reimport-dialog .el-dialog) {
  border-radius: 22px;
  overflow: hidden;
  max-width: calc(100vw - 32px);
}
:deep(.circle-reimport-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 20px 22px 12px;
  border-bottom: 1px solid #e7eef8;
  background: linear-gradient(180deg, #fcfdff 0%, #f6f9ff 100%);
}
:deep(.circle-reimport-dialog .el-dialog__title) {
  font-size: 18px;
  font-weight: 800;
  color: #193455;
}
:deep(.circle-reimport-dialog .el-dialog__body) {
  padding: 18px 22px 10px;
  background: #f8fbff;
}
:deep(.circle-reimport-dialog .el-dialog__footer) {
  padding: 0 22px 20px;
  background: #f8fbff;
}
.reimport-dialog-body {
  display: grid;
  gap: 16px;
}
.circle-reimport-dialog .setting-field {
  margin-top: 2px;
}
.reimport-progress-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid #d7e6fb;
  background:
    radial-gradient(circle at top right, rgba(87, 149, 255, 0.12), transparent 34%),
    linear-gradient(180deg, #fcfdff 0%, #f3f8ff 100%);
  box-shadow: 0 12px 24px rgba(39, 72, 118, 0.08);
}
.reimport-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.reimport-progress-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.reimport-progress-metric {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #d9e5f5;
  font-size: 12px;
  font-weight: 700;
  color: #4d6888;
}
.reimport-progress-title {
  font-size: 14px;
  font-weight: 800;
  color: #24415f;
}
.reimport-progress-status {
  font-size: 12px;
  font-weight: 700;
  color: #3f628a;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #d8e5f7;
}
.reimport-progress-step {
  font-size: 12px;
  line-height: 1.6;
  color: #5d7390;
  word-break: break-word;
}
.reimport-file-progress-list,
.reimport-file-result-list {
  display: grid;
  gap: 10px;
  padding-top: 4px;
}
.reimport-file-progress-title {
  font-size: 12px;
  font-weight: 800;
  color: #35506f;
}
.reimport-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.reimport-summary-item {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid rgba(214, 229, 246, 0.96);
}
.reimport-summary-label {
  font-size: 11px;
  font-weight: 700;
  color: #7287a1;
}
.reimport-summary-value {
  font-size: 13px;
  font-weight: 800;
  color: #284767;
  word-break: break-word;
}
.reimport-file-progress-item {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #dce8f7;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}
.reimport-file-progress-row,
.reimport-file-result-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.reimport-file-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  color: #6a8099;
}
.reimport-file-progress-name,
.reimport-file-result-name {
  min-width: 0;
  flex: 1;
  font-size: 12px;
  font-weight: 700;
  color: #32516f;
  overflow-wrap: anywhere;
}
.reimport-file-progress-size,
.reimport-file-result-path {
  min-width: 0;
  font-size: 11px;
  color: #6b809a;
  text-align: right;
  overflow-wrap: anywhere;
}
.reimport-file-result-item {
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(243, 251, 246, 0.92);
  border: 1px solid #d6ecd8;
}
.reimport-file-result-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}
.reimport-file-result-path {
  text-align: left;
}
/* 页头现在走共享组件 components/common/AppPageHeader.vue，这里只保留原 circle-hero 外边距与右侧 slot 内嵌样式 */
.circle-page-header {
  margin: 8px 8px 0;
}
.hero-search-wrap {
  position: relative;
}
.hero-search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: rgb(148 163 184);
  z-index: 1;
  pointer-events: none;
}
.hero-search-input :deep(.el-input__wrapper) {
  min-height: 28px;
  min-width: 240px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(226 232 240) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
  padding: 0 8px 0 26px;
  transition: box-shadow 0.3s ease;
}
.hero-search-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgb(203 213 225) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
}
.hero-search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgb(148 163 184) inset, 0 0 0 3px rgb(241 245 249);
}
.hero-search-input :deep(.el-input__inner) {
  height: 26px;
  font-size: 11.5px;
  color: rgb(30 41 59);
}
.hero-search-input :deep(.el-input__inner::placeholder) {
  color: rgb(148 163 184);
}
.hero-btn {
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  margin: 0 !important;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.hero-btn-primary {
  background: rgb(15 23 42);
  color: #fff;
  border: 1px solid rgb(15 23 42);
  box-shadow: 0 2px 6px -2px rgba(15, 23, 42, 0.35);
}
.hero-btn-primary:hover:not(.is-disabled):not(:disabled) {
  background: rgb(30 41 59);
  transform: translateY(-1px);
}
.hero-btn-primary:active:not(.is-disabled):not(:disabled) {
  transform: translateY(0) scale(0.96);
}
.hero-btn-secondary {
  background: #fff;
  color: rgb(51 65 85);
  border: 1px solid rgb(226 232 240);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.hero-btn-secondary:hover:not(.is-disabled):not(:disabled) {
  background: rgb(248 250 252);
  border-color: rgb(203 213 225);
  color: rgb(15 23 42);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}
.hero-btn-secondary:active:not(.is-disabled):not(:disabled) {
  transform: translateY(0) scale(0.96);
}
.hero-btn-email {
  background: linear-gradient(135deg, #e0f2fe 0%, #f0fdf4 100%);
  color: #0369a1;
  border: 1px solid #bae6fd;
  box-shadow: 0 1px 3px rgba(3, 105, 161, 0.08);
  display: flex;
  align-items: center;
}
.hero-btn-email:hover:not(.is-disabled):not(:disabled) {
  background: linear-gradient(135deg, #bae6fd 0%, #bbf7d0 100%);
  border-color: #7dd3fc;
  color: #075985;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px -4px rgba(3, 105, 161, 0.22);
}
.hero-btn-email:active:not(.is-disabled):not(:disabled) {
  transform: translateY(0) scale(0.96);
}
.sidebar-refresh-button {
  font-weight: 600;
  color: #6b7280;
  font-size: 12px;
}

.sidebar-filter-stack {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.sidebar-filter-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sidebar-filter-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  min-width: 52px;
  padding: 0 12px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #ffffff;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sidebar-filter-chip:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
}

.sidebar-filter-chip:active {
  transform: scale(0.96);
}

.sidebar-filter-chip.active {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.08), inset 0 0 0 1px rgba(147, 197, 253, 0.35);
}

.sidebar-filter-chip.new-work.active {
  border-color: rgba(249, 115, 22, 0.5);
  background: rgba(255, 248, 240, 0.95);
  color: #ea580c;
  box-shadow: 0 1px 2px rgba(249, 115, 22, 0.1), inset 0 0 0 1px rgba(249, 115, 22, 0.2);
}

.sidebar-filter-chip.new-work:not(.active):hover {
  border-color: rgba(249, 115, 22, 0.3);
  background: rgba(255, 248, 240, 0.6);
  color: #ea580c;
}

.sidebar-sort-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sidebar-sort-label {
  flex-shrink: 0;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.sidebar-sort-select {
  flex: 1;
}
.index-progress-card {
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
  display: grid;
  gap: 0;
  padding: 14px 20px 12px;
  margin: 12px 24px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
.index-progress-head {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 0;
}
.index-progress-head-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.index-progress-bar-wrap {
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
  padding-top: 48px;
  margin-bottom: 8px;
}
.index-progress-meta {
  margin-top: 2px;
}
.refresh-progress-card {
  margin: -1px -1px 12px;
  border-radius: 8px 8px 0 0;
  border: 1px solid #e5e7eb;
  background: #fafafa;
  max-height: 156px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 16px 9px;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}
.refresh-progress-card::-webkit-scrollbar {
  width: 6px;
}
.refresh-progress-card::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #cbd5e1;
}
.refresh-progress-card .index-progress-head {
  align-items: center;
}
.refresh-progress-card .index-progress-title {
  font-size: 13px;
}
.refresh-progress-card .index-progress-subtitle {
  max-width: min(920px, 70vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.refresh-progress-card .index-progress-bar-wrap {
  padding-top: 28px;
  margin-bottom: 6px;
}
.refresh-progress-card :deep(.app-lottie-progress) {
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
  padding-right: 10px;
}
.refresh-progress-card :deep(.app-lottie-progress-worm) {
  max-width: 44px;
}
.refresh-progress-card :deep(.app-lottie-progress-flag) {
  right: 0;
}
.refresh-progress-card .index-progress-meta {
  gap: 5px;
}
.index-cancel-button {
  border-radius: 6px;
  font-size: 12px;
}
.index-progress-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}
.index-progress-subtitle {
  min-width: 0;
  margin-top: 2px;
  font-size: 12px;
  color: #6b7280;
  overflow-wrap: anywhere;
}
.index-progress-status,
.progress-meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
.index-progress-status {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #dbeafe;
}
.index-progress-status.completed {
  background: #ecfdf5;
  color: #059669;
  border-color: #d1fae5;
}
.index-progress-status.failed {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
}
.index-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.progress-meta-pill {
  background: #ffffff;
  color: #334155;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.progress-meta-pill svg {
  color: #64748b;
  stroke-width: 2.2;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.progress-meta-pill:hover svg {
  transform: scale(1.14) rotate(-4deg);
}
.progress-meta-pill.time svg {
  color: #64748b;
}
.progress-meta-pill.total svg,
.progress-meta-pill.merged svg,
.progress-meta-pill.current svg {
  color: #475569;
}
.progress-meta-pill.batch svg {
  color: #2563eb;
}
.progress-meta-pill.local svg {
  color: #0f766e;
}
.progress-meta-pill.kikoeru svg {
  color: #7c3aed;
}
.progress-meta-pill.dlsite svg {
  color: #0284c7;
}
.progress-meta-pill.changed svg {
  color: #f59e0b;
}
.progress-meta-pill.ok {
  background: #ffffff;
  color: #334155;
  border-color: #d1fae5;
}
.progress-meta-pill.ok svg {
  color: #10b981;
}
.progress-meta-pill.warn {
  background: #ffffff;
  color: #334155;
  border-color: #fde68a;
}
.progress-meta-pill.warn svg {
  color: #ef4444;
}
.index-progress-error {
  font-size: 12px;
  color: #dc2626;
  line-height: 1.5;
}
.refresh-progress-log-list {
  display: grid;
  gap: 4px;
}
.refresh-progress-log-list.compact {
  margin-top: 6px;
  max-height: 54px;
  overflow-y: auto;
}
.refresh-progress-log-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  color: #4b5563;
  font-size: 12px;
}
.refresh-progress-log-item.success {
  background: #ecfdf5;
  border-color: #d1fae5;
  color: #065f46;
}
.refresh-progress-log-item.warning {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}
.refresh-progress-log-item.error {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}
.refresh-progress-log-time {
  flex: 0 0 auto;
  color: #9ca3af;
  font-variant-numeric: tabular-nums;
}
.refresh-progress-log-message {
  min-width: 0;
  overflow-wrap: anywhere;
}
.circle-shell {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 8px;
  padding: 8px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.circle-sidebar {
  min-height: 0;
  overflow: hidden;
}
.sidebar-card,
.circle-main {
  background: #fff;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 6px 16px -10px rgba(15, 23, 42, 0.10);
}
.circle-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.circle-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 0;
  color: #94a3b8;
}
.sidebar-card {
  padding: 20px 16px;
  display: grid;
  grid-template-rows: auto auto auto 1fr;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.sidebar-card > .app-empty-state {
  align-self: stretch;
  min-height: 100%;
}
.sidebar-head,
.toolbar-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
}
.toolbar-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}
.toolbar-card {
  padding: 14px 18px 10px;
  display: grid;
  align-content: start;
  gap: 6px;
  min-height: 94px;
  border-bottom: 1px solid #f3f4f6;
}
.toolbar-subtitle {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 2px;
}
.toolbar-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.toolbar-stats-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.metric-pill,
.tag-chip,
.reason-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.metric-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  background: #ffffff;
  color: #475569;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  cursor: default;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.metric-pill:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #cbd5e1;
}
.metric-pill svg {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.metric-pill:hover svg {
  transform: scale(1.2) rotate(5deg);
}
.metric-pill.owned {
  background: #f0f7ff;
  color: #2563eb;
  border-color: #dbeafe;
}
.metric-pill.owned:hover {
  background: #e0efff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}
.metric-pill.warn {
  background: #fffbeb;
  color: #d97706;
  border-color: #fef3c7;
}
.metric-pill.warn:hover {
  background: #fef3c7;
  border-color: #fde68a;
  color: #b45309;
}
.metric-pill.ok {
  background: #f0fdf4;
  color: #16a34a;
  border-color: #dcfce7;
}
.metric-pill.ok:hover {
  background: #dcfce7;
  border-color: #bbf7d0;
  color: #15803d;
}
.metric-pill.muted {
  background: #f8fafc;
  color: #64748b;
  border-color: #f1f5f9;
}
.metric-pill.muted:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
  color: #475569;
}
.metric-pill.unreleased {
  background: #eff6ff;
  color: #2563eb;
  border-color: rgba(52, 120, 246, 0.18);
}
.metric-pill.unreleased:hover {
  background: #dbeafe;
  border-color: rgba(52, 120, 246, 0.30);
}
.metric-pill.bonus {
  background: #faf5ff;
  color: #7e22ce;
  border-color: #e9d5ff;
  box-shadow: 0 1px 4px rgba(126, 34, 206, 0.12);
}
.metric-pill.bonus:hover {
  background: rgba(250, 245, 255, 0.90);
  border-color: rgba(168, 85, 247, 0.24);
  color: #7e22ce;
}
.metric-pill.new-work {
  background: rgba(255, 248, 240, 0.9);
  color: #ea580c;
  border-color: rgba(249, 115, 22, 0.22);
}
.metric-pill.new-work:hover {
  background: #fed7aa;
  border-color: rgba(249, 115, 22, 0.35);
}
.toolbar-right-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.work-status-filter-dropdown {
  flex-shrink: 0;
}
.status-filter-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  height: 32px;
  padding: 0 9px 0 11px;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 13px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.94) 100%);
  color: #334155;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 1px 2px rgba(15, 23, 42, 0.035);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-trigger:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(148, 163, 184, 0.92);
  background: #ffffff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.96),
    0 8px 18px rgba(15, 23, 42, 0.075);
}
.status-filter-trigger:active {
  transform: scale(0.96);
}
.status-filter-trigger.is-open {
  border-color: rgba(148, 163, 184, 0.96);
  background: #ffffff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.96),
    0 0 0 3px rgba(148, 163, 184, 0.13),
    0 8px 18px rgba(15, 23, 42, 0.075);
}
.status-filter-trigger__content {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}
.status-filter-trigger__content.has-overflow::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 14px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.98) 100%);
  pointer-events: none;
}
.status-filter-trigger__tags {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
}
.status-filter-trigger__placeholder {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(100, 116, 139, 0.82);
  font-size: 12px;
  font-weight: 600;
}
.status-filter-token {
  flex-shrink: 0;
  min-width: 0;
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  height: 20px;
  padding: 0 7px;
  border-radius: 6px;
  background: rgba(241, 245, 249, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.86);
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  transition: all 0.2s ease;
}
.status-filter-overflow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 22px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.86);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}
.status-filter-trigger__caret {
  flex-shrink: 0;
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-trigger:hover .status-filter-trigger__caret {
  color: #334155;
  transform: translateY(-1px);
}
.status-filter-trigger__caret.is-open {
  transform: rotate(180deg);
  color: #334155;
}
.status-filter-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 12px;
}
.status-filter-option__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.status-filter-option__meta {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 56px;
  flex-shrink: 0;
}
.status-filter-option__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 21px;
  padding: 0 7px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.78);
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-option__check {
  flex-shrink: 0;
  color: #64748b;
  opacity: 0.82;
}
:global(.circle-status-filter-menu.app-dd-menu) {
  padding: 6px;
  border-radius: 14px;
  border-color: rgba(203, 213, 225, 0.92);
  box-shadow:
    0 20px 42px -18px rgba(15, 23, 42, 0.28),
    0 8px 16px -12px rgba(15, 23, 42, 0.16);
}
:global(.circle-status-filter-menu .app-dd-item) {
  min-height: 38px;
  padding: 7px 9px 7px 10px;
  border-radius: 10px;
}
:global(.circle-status-filter-menu .app-dd-item:hover) {
  background: rgba(248, 250, 252, 0.98);
}
:global(.circle-status-filter-menu .app-dd-item.is-active) {
  background: linear-gradient(90deg, rgba(248, 250, 252, 0.98) 0%, rgba(241, 245, 249, 0.58) 100%);
  color: #0f172a;
  font-weight: 600;
}
:global(.circle-status-filter-menu .app-dd-item.is-active:hover) {
  background: linear-gradient(90deg, rgba(241, 245, 249, 0.98) 0%, rgba(226, 232, 240, 0.48) 100%);
}
:global(.circle-status-filter-menu .app-dd-item.is-active .status-filter-option__count) {
  background: #ffffff;
  border-color: rgba(203, 213, 225, 0.84);
  color: #334155;
}
.filter-toggles {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}
.filter-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 26px;
  padding: 0 10px;
  background: transparent;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.filter-toggle-btn:hover {
  color: #1e293b;
  background: rgba(255, 255, 255, 0.5);
}
.filter-toggle-btn:active {
  transform: scale(0.96);
}
.filter-toggle-btn.active {
  color: #1e293b;
  background: #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

.release-sort-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.release-sort-button:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #bfdbfe;
  color: #1d4ed8;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12);
}
.release-sort-button:active {
  transform: scale(0.96);
}
.release-sort-icon-stack {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
}
.release-sort-icon {
  position: absolute;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.release-sort-icon.base {
  color: #3b82f6;
}
.release-sort-icon.hover {
  opacity: 0;
  transform: translateY(5px) scale(0.72) rotate(-16deg);
}
.release-sort-icon.hover.asc {
  color: #10b981;
}
.release-sort-icon.hover.desc {
  color: #f97316;
}
.release-sort-button:hover .release-sort-icon.base {
  opacity: 0;
  transform: translateY(-5px) scale(0.72) rotate(16deg);
}
.release-sort-button:hover .release-sort-icon.hover {
  opacity: 1;
  transform: translateY(0) scale(1.08) rotate(0deg);
}
.release-sort-direction {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.release-sort-direction.asc {
  color: #10b981;
}
.release-sort-direction.desc {
  color: #f97316;
}
.release-sort-button:hover .release-sort-direction {
  transform: translateY(-1px) scale(1.12);
}
.circle-list {
  display: grid;
  gap: 6px;
  padding: 4px 6px 4px 2px;
  min-height: 0;
  max-height: none;
  /* 数量少时不要被 1fr 行拉伸，按内容高度堆在顶部 */
  align-content: start;
  grid-auto-rows: max-content;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  /* 顶部底部渐隐遮罩，暗示可滚动 */
  mask-image: linear-gradient(to bottom, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
}
.circle-list::-webkit-scrollbar {
  display: none;
}
.circle-list-item {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.circle-list-item:hover {
  background: #ffffff;
  border-color: #cbd5e1;
  box-shadow: 0 8px 16px rgba(0,0,0,0.08);
  transform: translateY(-3px);
}
.circle-list-item.active {
  background: #eff6ff;
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
  transform: translateY(-1px);
}
.circle-list-item:active {
  transform: scale(0.97) translateY(0);
  transition-duration: 0.1s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.circle-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  gap: 8px;
  min-width: 0;
}
.circle-list-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.circle-inline-new-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 14px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: .08em;
  color: #047857;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.18);
  flex-shrink: 0;
}
.circle-list-id {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.circle-list-progress-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
}
.circle-list-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}
.circle-list-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 17px;
  padding: 0 5px;
  border-radius: 5px;
  font-size: 9px;
  font-weight: 650;
  letter-spacing: .02em;
  line-height: 1;
  border: 1px solid transparent;
}
.circle-list-tag.unreleased {
  background: rgba(237, 244, 255, 0.85);
  color: #2563eb;
  border-color: rgba(52, 120, 246, 0.18);
}
.circle-list-tag.new-work {
  background: rgba(16, 185, 129, 0.07);
  color: #047857;
  border-color: rgba(16, 185, 129, 0.16);
}
.circle-list-refresh-row {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 5px;
  font-size: 10px;
  color: rgba(100, 116, 139, 0.78);
  font-weight: 500;
}
.circle-list-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.circle-count-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.6;
  background: #f3f4f6;
  color: #6b7280;
  border: none;
}
.circle-count-pill.owned {
  background: #eff6ff;
  color: #2563eb;
}
.circle-count-pill.dl {
  background: #f0fdf4;
  color: #16a34a;
}
.circle-count-pill.warn {
  background: #fef2f2;
  color: #dc2626;
}
.circle-list-meta {
  margin-top: 6px;
  font-size: 10px;
  color: #94a3b8;
  display: flex;
  justify-content: flex-end;
}

/* ---- 侧边栏社团统计行（设计图新布局） ---- */
.circle-list-stats-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  min-width: 0;
}

.circle-list-status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 52px;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  border: 1px solid transparent;
}

.circle-list-status-pill.completed {
  color: #047857;
  background: rgba(236, 253, 245, 0.95);
  border-color: rgba(110, 231, 183, 0.9);
}

.circle-list-status-pill.incomplete {
  color: #b91c1c;
  background: rgba(254, 242, 242, 0.95);
  border-color: rgba(252, 165, 165, 0.9);
}

.circle-list-counts {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.circle-stat-dot {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 600;
  color: #374151;
  line-height: 1;
}

.circle-stat-dot::before {
  content: '';
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.circle-stat-dot.total::before { background: #3b82f6; }
.circle-stat-dot.owned::before { background: #10b981; }
.circle-stat-dot.missing::before { background: #ef4444; }
.circle-stat-dot.missing { color: #ef4444; }

/* icon 版侧边栏统计（当前使用） */
.circle-stat-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.circle-stat-item:hover {
  transform: translateY(-1px);
}
.circle-stat-item svg {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.circle-stat-item:hover svg {
  transform: scale(1.15) rotate(-3deg);
}
.circle-stat-item.total { 
  color: #2563eb; 
  background: #eff6ff;
}
.circle-stat-item.owned { 
  color: #059669; 
  background: #ecfdf5;
}
.circle-stat-item.missing { 
  color: #dc2626; 
  background: #fef2f2;
}

.circle-list-progress {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 1;
  min-width: 0;
}

.circle-list-progress-track {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: #e5e7eb;
  overflow: hidden;
}

.circle-list-progress-fill {
  height: 100%;
  border-radius: 2px;
  background: #10b981;
  transition: width 0.4s ease;
}

.circle-list-percent {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  white-space: nowrap;
  min-width: 28px;
  text-align: right;
}

/* ---- Tab 标签自定义样式 ---- */
.circle-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.circle-tab-icon {
  opacity: 0.7;
}

.circle-tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  border-radius: 8px;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
  line-height: 1;
  background: #f3f4f6;
  color: #6b7280;
  border: 1px solid #e5e7eb;
}

.circle-tab-badge.missing {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
}

.circle-tab-badge.owned {
  background: #ecfdf5;
  color: #059669;
  border-color: #d1fae5;
}
.works-card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 14px;
}
.batch-bar {
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, #f7f9fb 0%, #ffffff 100%);
  border: 1px solid rgba(29, 29, 31, 0.06);
}
.batch-count {
  font-size: 15px;
  font-weight: 800;
  color: #1d1d1f;
}
.batch-hint {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.56);
}
.batch-bar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.batch-action-button {
  min-width: 100px;
  height: 34px;
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  border-radius: 8px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.batch-action-button:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #1e293b;
  box-shadow: 0 6px 15px rgba(0, 0, 0, 0.08);
}
.batch-action-button:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
  transition-duration: 0.1s;
}
.batch-action-button:disabled {
  cursor: not-allowed;
  opacity: 0.56;
  transform: none;
  box-shadow: none;
}
.batch-action-button svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.batch-action-button:hover:not(:disabled) svg:not(.batch-action-spinner) {
  transform: rotate(-6deg) scale(1.08);
}
.batch-action-spinner {
  animation: batchActionSpin 0.82s linear infinite;
}
.batch-action-button.primary {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
.batch-action-button.primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.3);
}
.batch-action-button.refresh {
  background: linear-gradient(135deg, #334155 0%, #0f172a 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.2);
}
.batch-action-button.refresh:hover:not(:disabled) {
  background: linear-gradient(135deg, #475569 0%, #1e293b 100%);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.3);
}
.batch-action-button.ghost {
  background: transparent;
  border: 1px dashed #cbd5e1;
  color: #64748b;
  box-shadow: none;
}
.batch-action-button.ghost:hover:not(:disabled) {
  background: #f1f5f9;
  border-style: solid;
  border-color: #94a3b8;
  color: #334155;
}
@keyframes batchActionSpin {
  to { transform: rotate(360deg); }
}
.work-action-button:hover {
  background: linear-gradient(180deg, #f2f7ff 0%, #e9f2ff 100%);
  border-color: rgba(0, 113, 227, 0.24);
  color: #0f63c8;
}
.work-action-button.primary:hover {
  background: linear-gradient(180deg, #dcecff 0%, #cfe3ff 100%);
  border-color: rgba(0, 113, 227, 0.28);
  color: #005ecb;
}
.work-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(152px, 1fr));
  grid-auto-rows: max-content;
  gap: 10px;
  flex: 1;
  min-height: 0;
  padding-bottom: 14px;
  box-sizing: border-box;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.work-grid::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

/* ── 列表视图 ── */
.work-list {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 6px;
  padding-bottom: 14px;
  box-sizing: border-box;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.work-list::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

.owned-works-list,
.compare-works-list {
  flex: 1;
  min-height: 0;
  align-content: start;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}



/* ── 卡片/列表视图切换 ── */
.view-toggle-group {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}
.view-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 26px;
  background: transparent;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.view-toggle-btn svg {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.view-toggle-btn:hover {
  color: #1e293b;
  background: rgba(255, 255, 255, 0.5);
}
.view-toggle-btn:hover svg {
  transform: scale(1.1);
}
.view-toggle-btn:active {
  transform: scale(0.96);
}
.view-toggle-btn.active {
  color: #1e293b;
  background: #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}
.owned-card,
.info-card,
.preview-plan {
  border-radius: 14px;
  border: 1px solid rgba(29, 29, 31, 0.06);
  background: #fcfcfd;
}
.owned-title {
  font-size: 11px;
  font-weight: 800;
  color: #1f3554;
  line-height: 1.38;
}
.owned-meta,
.owned-path {
  font-size: 9px;
  color: rgba(29, 29, 31, 0.40);
  line-height: 1.4;
  word-break: break-word;
}
.preview-presets,
.preview-plan-meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.info-card,
.preview-plan {
  padding: 14px;
}
.info-grid,
.preview-plan-list {
  display: grid;
  gap: 10px;
}
.works-pager {
  display: flex;
  justify-content: flex-end;
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 16px;
}
.circle-complete-state {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 14px;
  min-height: 360px;
  margin: 10px 2px 4px;
  padding: 34px 24px 30px;
  border-radius: 24px;
}
.circle-complete-visual {
  position: relative;
  display: grid;
  place-items: center;
  width: 320px;
  height: 320px;
}
.circle-complete-confetti {
  position: absolute;
  inset: -22px;
  z-index: 2;
  pointer-events: none;
}
.circle-complete-confetti-player {
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 12px 30px rgba(96, 165, 250, 0.12));
}
.circle-complete-image {
  position: relative;
  z-index: 1;
  width: 320px;
  height: 320px;
  object-fit: contain;
  filter: drop-shadow(0 16px 24px rgba(20, 83, 45, 0.12));
  opacity: 0;
  transform: translateY(14px) scale(0.94);
  transition:
    opacity 0.5s ease,
    transform 0.7s cubic-bezier(.22, 1, .36, 1),
    filter 0.4s ease;
}
.circle-complete-image.is-revealed {
  opacity: 1;
  transform: translateY(0) scale(1);
  animation: completeFloat 3.6s ease-in-out 0.28s infinite;
}
.circle-complete-copy {
  position: relative;
  z-index: 1;
  display: grid;
  justify-items: center;
  gap: 0;
  text-align: center;
}
.circle-complete-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: -6px;
}
.circle-complete-pill {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid transparent;
}
.circle-complete-pill.owned {
  background: rgba(239, 246, 255, 0.96);
  border-color: rgba(191, 219, 254, 0.95);
  color: #2563eb;
}
.circle-complete-pill.success {
  background: rgba(236, 253, 245, 0.96);
  border-color: rgba(167, 243, 208, 0.95);
  color: #059669;
}
.complete-confetti-enter-active,
.complete-confetti-leave-active {
  transition: opacity 0.32s ease, transform 0.42s ease;
}
.complete-confetti-enter-from,
.complete-confetti-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
@keyframes completeFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.owned-list {
  grid-template-columns: 1fr;
}
.owned-card {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(10, 132, 255, 0.08), transparent 26%),
    linear-gradient(180deg, #fbfdff 0%, #f5f9ff 100%);
  border: 1px solid rgba(184, 207, 235, 0.62);
  box-shadow: 0 8px 18px rgba(44, 88, 147, 0.06);
  will-change: transform;
  transform: translateZ(0);
}
.owned-card-top,
.owned-card-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.owned-state-pill,
.owned-rj-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}
.owned-state-pill {
  background: linear-gradient(180deg, #eef7ff 0%, #e3f0ff 100%);
  border: 1px solid rgba(89, 141, 214, 0.22);
  color: #2f68b7;
}
.owned-rj-pill {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(177, 198, 224, 0.76);
  color: #48698f;
}
.owned-title {
  font-size: 15px;
  line-height: 1.36;
  color: #18385e;
  display: -webkit-box;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.owned-meta,
.owned-path {
  font-size: 12px;
  line-height: 1.4;
  color: #667b94;
}
.owned-separator {
  color: #9cafc5;
  font-size: 12px;
  line-height: 1;
}
.info-grid {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.info-label {
  font-size: 12px;
  color: #70819b;
}
.info-value {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #233d60;
  line-height: 1.6;
  word-break: break-all;
}
.circle-tabs-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.circle-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.circle-tabs-wrapper .toolbar-right-actions {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 10;
  height: 38px; /* 对齐 .el-tabs__item 的高度 */
  display: flex;
  align-items: center;
}
.circle-tabs :deep(.el-tabs__nav-wrap) {
  padding-right: 292px; /* 为右侧按钮留出空间 */
}
.circle-tabs :deep(.el-tabs__header) {
  margin: 0 0 12px;
  padding-top: 2px;
}
.circle-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.circle-tabs :deep(.el-tabs__item) {
  height: 38px;
  font-weight: 800;
  color: #60748d;
}
.circle-tabs :deep(.el-tabs__item.is-active) {
  color: #2d6ec0;
}
.circle-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-top: 2px;
}
.circle-tabs :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.owned-panel {
  position: relative;
  z-index: 30;
  flex: 0 0 auto;
}
.owned-filter-row {
  position: relative;
  z-index: 31;
  pointer-events: auto;
}
.owned-filter-tabs {
  position: relative;
  z-index: 32;
  align-items: center;
  gap: 4px;
  pointer-events: auto;
}
.owned-filter-chip {
  position: relative;
  z-index: 1;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 1;
  cursor: pointer;
  transition: all .22s cubic-bezier(.34, 1.56, .64, 1);
}
.owned-filter-chip:hover {
  background: rgba(248, 250, 252, .92);
  color: #1f2937;
  transform: translateY(-1px);
}
.owned-filter-chip.is-active {
  background: rgba(255, 255, 255, .96);
  border-color: rgba(148, 163, 184, .28);
  color: #0f172a;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .92),
    0 4px 12px rgba(15, 23, 42, .08);
}
.owned-filter-chip.is-simplified.is-active {
  border-color: rgba(14, 165, 233, .24);
  color: #0369a1;
  background: rgba(240, 249, 255, .78);
}
.owned-filter-chip.is-traditional.is-active {
  border-color: rgba(124, 58, 237, .20);
  color: #6d28d9;
  background: rgba(245, 243, 255, .68);
}
.owned-filter-chip.is-subtitle.is-active {
  border-color: rgba(79, 70, 229, .20);
  color: #4338ca;
  background: rgba(238, 242, 255, .72);
}
.owned-filter-chip.is-bonus.is-active {
  border-color: rgba(168, 85, 247, .18);
  color: #7e22ce;
  background: rgba(250, 245, 255, .66);
}
.owned-filter-count {
  min-width: 20px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(241, 245, 249, .92);
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}
.owned-filter-chip.is-active .owned-filter-count {
  background: rgba(15, 23, 42, .08);
  color: currentColor;
}
.preview-dialog-shell {
  display: grid;
  gap: 18px;
  min-height: 660px;
}
.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.preview-header-title {
  font-size: 26px;
  line-height: 1.1;
  font-weight: 900;
  color: #16181d;
  letter-spacing: -0.04em;
}
.preview-close-button {
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: rgba(22, 24, 29, 0.56);
  font-size: 28px;
  line-height: 1;
  cursor: pointer;
  transition: background .18s ease, color .18s ease, transform .18s ease;
}
.preview-close-button:hover {
  background: rgba(255,255,255,0.52);
  color: #22262d;
  transform: rotate(90deg);
}
.preview-layout {
  display: grid;
  grid-template-columns: 380px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}
.preview-side-column {
  display: grid;
  gap: 20px;
}
.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.preview-presets {
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
}
.preset-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.62) 0%, rgba(231, 236, 242, 0.52) 100%);
  color: #667085;
  border-radius: 999px;
  padding: 8px 18px;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.88),
    0 12px 24px rgba(148, 163, 184, 0.12);
  transition: transform .2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow .2s ease, background .2s ease, color .2s ease, border-color .2s ease, opacity .2s ease;
  white-space: nowrap;
}
.preset-chip:hover {
  transform: translateY(-1px);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.72) 0%, rgba(236, 240, 245, 0.66) 100%);
  color: #1f2937;
  border-color: rgba(255,255,255,0.75);
}
.preset-chip:active {
  transform: scale(0.98);
}
.preset-chip.ghost {
  color: #6b7280;
  margin-left: 4px;
}
.preset-chip.state-all {
  background: linear-gradient(180deg, rgba(255,255,255,0.92) 0%, rgba(223, 228, 235, 0.9) 100%);
  color: #111827;
  border-color: rgba(255,255,255,0.78);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 10px 22px rgba(148, 163, 184, 0.16);
  animation: chipActivate 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.preset-chip.state-all .preset-chip-count {
  background: rgba(255, 255, 255, 0.56);
  color: #374151;
}
.preset-chip.state-all:hover {
  background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(229, 234, 240, 0.92) 100%);
  color: #111827;
  border-color: rgba(255,255,255,0.82);
}
.preset-chip.state-partial {
  background: linear-gradient(180deg, rgba(234, 238, 244, 0.94) 0%, rgba(209, 216, 225, 0.92) 100%);
  color: #374151;
  border-color: rgba(255,255,255,0.72);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.78),
    0 8px 18px rgba(148, 163, 184, 0.12);
  animation: chipPartial 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.preset-chip.state-none {
  color: #6b7280;
  background: linear-gradient(180deg, rgba(243, 245, 248, 0.78) 0%, rgba(227, 232, 238, 0.72) 100%);
  border-color: rgba(255,255,255,0.5);
  box-shadow: none;
}
@keyframes chipActivate {
  0%   { transform: scale(0.92); opacity: 0.7; }
  55%  { transform: scale(1.06); }
  80%  { transform: scale(0.98); }
  100% { transform: scale(1);    opacity: 1; }
}
@keyframes chipPartial {
  0%   { transform: scale(0.95); }
  60%  { transform: scale(1.04); }
  100% { transform: scale(1); }
}
.preset-chip-indicator {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: currentColor;
  color: #fff;
  font-size: 10px;
  line-height: 1;
  font-weight: 900;
}
.preset-chip-count {
  min-width: 22px;
  height: 22px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 7px;
  background: rgba(255, 255, 255, 0.34);
  font-size: 12px;
  line-height: 1;
  color: inherit;
}
.preview-stats {
  font-size: 15px;
  color: #20252d;
  font-weight: 800;
}
.preview-panel-card {
  padding: 22px 20px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.56);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.28) 0%, rgba(239, 243, 248, 0.14) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.74),
    0 22px 44px rgba(148, 163, 184, 0.16);
  backdrop-filter: blur(28px) saturate(130%);
  -webkit-backdrop-filter: blur(28px) saturate(130%);
}
.download-settings-card {
  display: grid;
  gap: 18px;
}
.download-settings-head {
  display: grid;
  gap: 4px;
}
.download-settings-title {
  font-size: 16px;
  font-weight: 900;
  color: #15181d;
}
.download-settings-subtitle {
  font-size: 12px;
  color: rgba(53, 59, 68, 0.64);
  line-height: 1.5;
}
.download-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 14px;
}
.setting-field {
  display: grid;
  gap: 8px;
}
.setting-field-wide {
  grid-column: 1 / -1;
}
.setting-label {
  font-size: 12px;
  font-weight: 700;
  color: #303641;
}
.preview-panel-card :deep(.el-input__wrapper),
.preview-panel-card :deep(.el-select__wrapper) {
  min-height: 40px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.88),
    0 0 0 1px rgba(203, 213, 225, 0.5);
}
.preview-panel-card :deep(.el-input__inner),
.preview-panel-card :deep(.el-select__placeholder),
.preview-panel-card :deep(.el-select__selected-item),
.preview-panel-card :deep(.el-input__inner::placeholder) {
  color: #1b2027;
}
.preview-panel-card :deep(.el-select__caret),
.preview-panel-card :deep(.el-input__icon) {
  color: #79879c;
}
.preview-action-card {
  align-content: start;
}
.preview-action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.preview-action-pill {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 0 16px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.64);
  background: rgba(255, 255, 255, 0.72);
  color: #334155;
  font-size: 14px;
  font-weight: 800;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.88),
    0 10px 22px rgba(148, 163, 184, 0.08);
}
.preview-action-pill.is-primary {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(232, 237, 243, 0.86) 100%);
  color: #111827;
}
.preview-target-root {
  font-size: 12px;
  color: rgba(38, 44, 52, 0.72);
  line-height: 1.6;
  word-break: break-all;
}
.preview-tree-panel {
  display: grid;
  min-height: 0;
  overflow: hidden;
  align-content: start;
}
.preview-plan-list {
  display: grid;
  gap: 0;
  max-height: 100%;
  overflow: auto;
  padding-right: 0;
  overflow-x: hidden;
}
.preview-plan {
  display: grid;
  gap: 0;
  align-content: start;
}
.preview-plan-title {
  font-size: 15px;
  font-weight: 900;
  color: #14181d;
  line-height: 1.4;
}
.preview-plan-heading {
  min-width: 0;
}
.preview-plan-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.preview-plan-folder-icon {
  margin-top: 0;
  font-size: 20px;
  color: #f4c54d;
  flex: 0 0 auto;
}
.preview-plan-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px 10px;
}
.preview-plan-meta {
  color: #5f6b7b;
  font-size: 14px;
  font-weight: 700;
  display: grid;
  gap: 8px;
  text-align: right;
}
.tree-shell {
  margin: 0 6px 6px;
  border: 1px solid rgba(255, 255, 255, 0.46);
  border-radius: 20px;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.12) 0%, rgba(248, 250, 252, 0.06) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.42),
    0 18px 34px rgba(148, 163, 184, 0.08);
  min-width: 0;
}
.tree-head,
.tree-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 112px;
  align-items: center;
  padding: 0 18px;
  min-width: 0;
}
.tree-head {
  display: none;
}
.tree-body {
  max-height: 360px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 0 12px;
}
.tree-row {
  min-height: 40px;
  border-bottom: none;
  cursor: pointer;
  border-radius: 12px;
  transition: background .16s ease, box-shadow .16s ease;
}
.tree-row.dir {
  margin-bottom: 2px;
}
.tree-row-root {
  min-height: 44px;
  margin-bottom: 8px;
  background: transparent;
}
.tree-row.selected {
  background: rgba(213, 221, 232, 0.78);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.36);
}
.tree-row:hover {
  background: rgba(255,255,255,0.4);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.28);
}
.tree-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}
.tree-arrow,
.tree-arrow-placeholder,
.tree-arrow-spacer {
  width: 16px;
  flex: 0 0 16px;
}
.tree-arrow {
  border: none;
  background: transparent;
  color: #7b8798;
  cursor: pointer;
  transition: transform .18s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}
.tree-arrow.open {
  transform: rotate(0deg);
}
.tree-arrow-glyph {
  display: inline-block;
  transform: rotate(90deg);
  line-height: 1;
}
.tree-arrow.open .tree-arrow-glyph {
  transform: rotate(0deg);
}
.tree-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #243041;
  font-size: 14px;
  font-weight: 500;
  min-width: 0;
}
.tree-col-size {
  text-align: right;
  font-size: 13px;
  color: #5f6b7b;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tree-file-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  font-size: 17px;
  color: #7a8fa6;
  transition: color 0.15s ease;
}
.tree-file-icon.is-file {
  color: #7a8fa6;
}
.tree-file-icon.is-folder {
  color: #f4c54d;
}
.tree-file-icon.is-audio {
  color: #775dd0;
}
.tree-file-icon.is-subtitle {
  color: #667085;
}
.tree-file-icon.is-image {
  color: #4d99f0;
}
.tree-file-icon.is-document {
  color: #7b8798;
}
.tree-col-check :deep(.el-checkbox__input.is-checked .el-checkbox__inner),
.tree-col-check :deep(.el-checkbox__input.is-indeterminate .el-checkbox__inner) {
  background-color: #5fa2ee;
  border-color: #5fa2ee;
}
.tree-col-check :deep(.el-checkbox__inner) {
  background: rgba(255,255,255,0.74);
  border-color: rgba(137, 158, 187, 0.52);
  border-radius: 6px;
}
.preview-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.preview-footer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.preview-footer-btn {
  min-width: 164px;
  min-height: 52px;
  border-radius: 18px;
  font-size: 14px;
  font-weight: 800;
}
.preview-footer-btn.is-ghost {
  border-color: rgba(255,255,255,0.72);
  background: linear-gradient(180deg, rgba(255,255,255,0.7) 0%, rgba(235, 239, 244, 0.58) 100%);
  color: #1f2937;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 16px 30px rgba(148, 163, 184, 0.12);
}
.preview-footer-btn.is-primary {
  border: 1px solid rgba(255,255,255,0.3);
  background: linear-gradient(180deg, #84baf5 0%, #6ea8ed 100%);
  color: #ffffff;
  box-shadow: 0 20px 38px rgba(109, 168, 237, 0.28);
}
:deep(.circle-preview-dialog .el-dialog) {
  border-radius: 26px;
  overflow: hidden;
  max-width: calc(100vw - 32px);
  background:
    radial-gradient(circle at 20% 12%, rgba(255,255,255,0.28), transparent 34%),
    radial-gradient(circle at 80% 18%, rgba(255,255,255,0.24), transparent 26%),
    radial-gradient(circle at 54% 82%, rgba(255,255,255,0.18), transparent 24%),
    linear-gradient(180deg, rgba(224, 231, 240, 0.56) 0%, rgba(212, 220, 231, 0.42) 100%);
  border: 1px solid rgba(255,255,255,0.56);
  box-shadow:
    0 34px 72px rgba(148, 163, 184, 0.22),
    inset 0 1px 0 rgba(255,255,255,0.76);
  backdrop-filter: blur(36px) saturate(138%);
  -webkit-backdrop-filter: blur(36px) saturate(138%);
}
:deep(.circle-preview-dialog .el-dialog__header) {
  display: none;
}
:deep(.circle-preview-dialog .el-dialog__body) {
  padding: 28px 28px 14px;
  background: transparent;
}
:deep(.circle-preview-dialog .el-dialog__footer) {
  padding: 8px 28px 28px;
  background: transparent;
}
@media (max-width: 1100px) {
  .preview-layout {
    grid-template-columns: 1fr;
  }
  .preview-side-column {
    order: 2;
  }
  .preview-tree-panel {
    order: 1;
  }
}
@media (max-width: 720px) {
  .preview-dialog-shell {
    min-height: auto;
  }
  .preview-header-title {
    font-size: 22px;
  }
  .preview-layout {
    gap: 16px;
  }
  .download-settings-grid,
  .preview-action-grid {
    grid-template-columns: 1fr;
  }
  .preview-dialog-footer {
    flex-direction: column;
    align-items: stretch;
  }
  .preview-footer-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
}
.tree-check {
  width: 14px;
  height: 14px;
  accent-color: #409eff;
}
.dialog-loading {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6c7d95;
}
.compare-work-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.compare-work-rj {
  font-weight: 800;
  color: #223754;
}
.compare-work-title {
  margin-top: 6px;
  color: #24364f;
  line-height: 1.55;
}
.compare-work-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #7b8797;
}
.compare-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}
.compare-status-pill.is-owned {
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}
.compare-status-pill.is-downloadable {
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
}
.compare-status-pill.is-dl_only {
  background: rgba(255, 59, 48, 0.10);
  color: #c2410c;
}
.compare-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.compare-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #d8e4f2;
  color: #23406f;
  font-size: 12px;
  line-height: 1.2;
}
.compare-chip.is-kikoeru-tag {
  border-color: rgba(10, 132, 255, 0.16);
  background: rgba(239, 246, 255, 0.96);
  color: #005fcc;
  font-weight: 800;
}
.compare-chip.has-icon {
  gap: 4px;
}
.kikoeru-tag-icon {
  width: 12px;
  height: 12px;
  display: inline-block;
  fill: currentColor;
  flex: 0 0 auto;
}
.compare-chip.is-asmr {
  border-color: rgba(52, 199, 89, 0.16);
  background: rgba(236, 253, 245, 0.98);
  color: #248a3d;
  font-weight: 800;
}
.compare-chip.is-asmr-badge {
  border-color: rgba(52, 199, 89, 0.14);
  background: rgba(220, 252, 231, 0.94);
  color: #1f8f51;
  font-weight: 800;
}
.compare-empty {
  color: #8a97aa;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .circle-shell {
    grid-template-columns: 1fr;
  }
  .index-progress-head {
    flex-direction: column;
    align-items: stretch;
  }
  .workbench-toolbar,
  .download-task-head,
  .download-file-row {
    flex-direction: column;
    align-items: stretch;
  }
  .download-task-meta-grid,
  .download-settings-grid,
  .reimport-summary-grid {
    grid-template-columns: 1fr;
  }
  /* .floating-card 已在全局 index.css 用 min(92vw, 420px) 自适应宽度，无需 mobile 覆盖 */
}

/* ============================================================
 * Phase 3 CircleCompletion 移动端适配（≤640）
 * 桌面零改动：所有规则严格闭合在 @media 内
 *
 * 核心修复（"内容看不到 + 划不动"）：
 *   桌面 .circle-page 是 height:100% + overflow-y:auto 的固定高度滚动容器，
 *   内部 .circle-shell / .circle-main / .works-card / .circle-tabs-wrapper /
 *   .circle-tabs / .work-grid / .work-list 全都 flex:1 + min-height:0，
 *   桌面端是让 work-grid 自己滚作品。
 *   移动端这种嵌套 flex:1 + 内部 work-grid 自己滚的结构，会出现两个症状：
 *     1. 每个区只分到屏幕的一小部分高度，work-grid 几乎看不见
 *     2. 嵌套滚动让外层手势"划不动"，触发不到 work-grid 的内部 scroll
 *   解法（与 Conflicts.vue / SubtitleImport.vue 一致）：
 *     - 整页 stream 模式：解锁 .circle-page 高度，让外层 .content-shell 滚
 *     - 内部 flex:1 全部改 flex:0 0 auto，overflow 全部 visible
 *     - work-grid / work-list 自然撑开，跟着整页一起滚
 *
 * 其他视觉痛点（顺带）：
 *   - circle-page-header / index-progress-card margin & padding 太大
 *   - sidebar-card padding 20/16 浪费空间，circle-list 限高 320 防侧栏吃满
 *   - toolbar-right-actions absolute 在移动会重叠 tabs 标签
 *   - filter-toggles / view-toggle-group / release-sort-button 在窄屏挤压
 *   - batch-bar 操作按钮太多需要 grid 平分
 *   - circle-preview-dialog / circle-reimport-dialog ≤640 全屏覆盖
 *   - compare-head / compare-row 4 列横向溢出，改 1 列 stack
 * ============================================================ */
@media (max-width: 640px) {
  /* ============================================================
   * 关键：整页 stream 模式 — 解锁外层 .circle-page 与内部所有 flex:1 容器
   * 让 work-grid 自然撑开，由 App 外层滚动容器（.content-shell）统一滚
   * ============================================================ */
  .circle-page {
    height: auto !important;
    min-height: 100%;
    overflow-y: visible !important;
    overflow-x: hidden !important;
  }
  .circle-shell {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    overflow-y: visible !important;
    overflow-x: hidden !important;
  }
  .circle-main {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    overflow-y: visible !important;
    overflow-x: hidden !important;
  }
  .works-card {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    overflow-y: visible !important;
    overflow-x: hidden !important;
  }
  .circle-tabs-wrapper {
    flex: 0 0 auto !important;
    min-height: 0 !important;
  }
  .circle-tabs {
    flex: 0 0 auto !important;
    min-height: 0 !important;
  }
  .work-grid,
  .work-list {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow-y: visible !important;
    overflow-x: hidden !important;
    padding-bottom: 0;
  }
  /* el-tabs 内部 pane 容器也松绑 */
  .circle-tabs :deep(.el-tabs__content),
  .circle-tabs :deep(.el-tab-pane) {
    overflow: visible !important;
    min-height: 0;
  }
  /* 侧栏卡片本身也不再争夺整页高度 */
  .sidebar-card {
    height: auto !important;
    min-height: 0 !important;
  }

  /* 顶部页头紧凑 margin */
  .circle-page-header { margin: 4px 6px 0; }

  /* index-progress-card：margin 紧凑，padding 缩小 */
  .index-progress-card {
    margin: 8px 6px;
    padding: 10px 12px 10px;
    border-radius: 12px;
  }
  .index-progress-head { gap: 8px; }
  .index-progress-title { font-size: 13px; }
  .index-progress-subtitle { font-size: 11px; }
  .index-progress-bar-wrap { padding-top: 36px; }
  .index-progress-meta { gap: 4px; }
  .progress-meta-pill { height: 20px; padding: 0 6px; font-size: 10px; }
  .refresh-progress-card { padding: 8px 10px 8px; max-height: 132px; }
  .refresh-progress-card .index-progress-subtitle {
    max-width: calc(100vw - 60px);
    white-space: nowrap;
  }

  /* circle-shell：进一步紧凑 padding/gap（≤1100 已 stack） */
  .circle-shell {
    padding: 6px;
    gap: 8px;
  }

  /* 侧栏卡片 padding + 控件紧凑 */
  .sidebar-card {
    padding: 12px 12px;
    gap: 10px;
  }
  .sidebar-head { gap: 6px; }
  .sidebar-overline { font-size: 10px; }
  .sidebar-title { font-size: 13px; }
  .sidebar-refresh-button { font-size: 11px; }
  .sidebar-filter-chip {
    height: 26px;
    min-width: 46px;
    padding: 0 10px;
    font-size: 11px;
  }
  .sidebar-sort-row { gap: 6px; }
  .sidebar-sort-label { font-size: 11px; }
  /* 社团列表限制高度，避免在移动端整张页面只有侧栏可视 */
  .circle-list {
    max-height: 320px;
    overflow-y: auto;
  }
  .circle-list-item { padding: 8px 10px; }
  .circle-list-name { font-size: 12px; }
  .circle-list-id { font-size: 10px; padding: 1px 4px; }
  .circle-list-counts { gap: 3px; }
  .circle-stat-item { font-size: 10px; height: 18px; padding: 0 4px; }
  .circle-list-status-pill { height: 18px; padding: 0 6px; font-size: 10px; }

  /* 主区 toolbar-card 紧凑 padding + 工具按钮折行 */
  .toolbar-card {
    padding: 10px 12px 8px;
    min-height: 0;
    gap: 6px;
  }
  .toolbar-title { font-size: 13px; }
  .toolbar-subtitle { font-size: 11px; }
  .toolbar-main { gap: 6px; flex-wrap: wrap; }
  .toolbar-stats-row {
    gap: 6px;
    flex-direction: column;
    align-items: stretch;
  }
  .toolbar-metrics { gap: 4px; }

  /* circle-tabs-wrapper 内的 toolbar-right-actions：默认 absolute 会和 tabs 标签重叠，
   * 移动端改 static、独占一行并允许 wrap */
  .circle-tabs-wrapper .toolbar-right-actions {
    position: static;
    flex-wrap: wrap;
    gap: 6px;
    padding: 0 0 6px;
  }
  /* 移除 tabs nav 右侧为绝对定位按钮预留的空间（移动端已改 static）*/
  .circle-tabs :deep(.el-tabs__nav-wrap) {
    padding-right: 0 !important;
  }
  .release-sort-button {
    height: 30px;
    padding: 0 10px;
    font-size: 11px;
  }
  .filter-toggles { flex-wrap: wrap; gap: 4px; }
  .filter-toggle-btn { font-size: 11px; padding: 4px 8px; }
  .view-toggle-group { margin-left: auto; }
  .view-toggle-btn { padding: 4px 6px; }

  /* works-card padding 紧凑 */
  .works-card { padding: 12px; gap: 10px; }

  /* batch-bar：内部 flex 横向元素改 stack；按钮 grid 2 列平分 */
  .batch-bar {
    padding: 10px 12px;
    border-radius: 12px;
  }
  /* 模板里的 Tailwind utility 包装：flex items-center justify-between 在 ≤640 改 column */
  .works-card > div.flex.items-center.justify-between {
    flex-direction: column;
    align-items: stretch !important;
    gap: 8px;
  }
  .works-card > div.flex.items-center.justify-between > .flex.items-center.gap-2 {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
    width: 100%;
  }
  .works-card > div.flex.items-center.justify-between > .flex.items-center.gap-2 > .el-button {
    width: 100%;
  }
  /* 下载选中项按钮独占整行，强调主操作 */
  .works-card > div.flex.items-center.justify-between > .flex.items-center.gap-2 > .batch-action-button.primary {
    grid-column: 1 / -1;
  }

  /* work-grid 紧凑：414px - padding 24 - gap 8 ≈ 380，可容下 2 列 152px */
  .work-grid {
    width: 100%;
    max-width: 100%;
    gap: 8px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow-x: hidden !important;
  }

  /* 已满足 tab：统计条 / 本地筛选 / 搜索框避免撑出屏幕 */
  .owned-panel,
  .owned-stats-strip,
  .owned-filter-row {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }
  .owned-stats-strip {
    padding: 6px !important;
  }
  .owned-stats-list {
    width: 100%;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }
  .owned-stats-list > div {
    min-width: 0;
    padding: 8px 10px !important;
    border-right: 0 !important;
    border-radius: 12px;
    background: rgba(248, 250, 252, 0.72);
  }
  .owned-filter-row {
    flex-direction: column;
    align-items: stretch !important;
    gap: 8px !important;
  }
  .owned-filter-tabs {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    display: grid !important;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 4px;
    overflow-x: hidden;
  }
  .owned-filter-chip {
    min-width: 0;
    padding: 6px 5px !important;
    font-size: 12px;
    justify-content: center;
    white-space: nowrap;
    line-height: 1.15;
  }
  .owned-filter-count {
    min-width: 18px;
    height: 17px;
    padding: 0 5px;
    font-size: 10px;
  }
  .owned-search-wrap {
    width: 100% !important;
    max-width: 100%;
    min-width: 0;
  }

  /* 来源对比 tab：统计 / 筛选 / 行内容移动端单列化，避免三来源列撑宽 */
  .compare-panel,
  .compare-stats-list,
  .compare-filter-row,
  .compare-works-list,
  .compare-work-item,
  .compare-work-row,
  .compare-work-main {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }
  .compare-stats-list {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    padding: 6px;
  }
  .compare-stats-list > div {
    min-width: 0;
    padding: 8px 10px !important;
    border-right: 0 !important;
    border-radius: 12px;
    background: rgba(248, 250, 252, 0.72);
  }
  .compare-filter-row {
    flex-direction: column;
    align-items: stretch !important;
    gap: 8px;
  }
  .compare-filter-tabs {
    width: 100%;
    max-width: 100%;
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 4px;
    overflow-x: hidden;
  }
  .compare-filter-tabs > button {
    min-width: 0;
    padding: 7px 4px !important;
    font-size: 12px !important;
    white-space: normal;
    line-height: 1.15;
  }
  .compare-search-wrap {
    width: 100% !important;
    max-width: 100%;
    min-width: 0;
  }
  .compare-head {
    display: none !important;
  }
  .compare-work-item {
    padding: 12px 10px !important;
  }
  .compare-work-row {
    flex-direction: column;
    align-items: stretch !important;
    gap: 8px !important;
  }
  .compare-work-title {
    white-space: normal !important;
    overflow: hidden;
    text-overflow: clip;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .compare-work-tags {
    flex-wrap: wrap;
    min-width: 0;
    max-width: 100%;
    gap: 5px !important;
  }
  .compare-source-cols {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px !important;
    overflow: hidden;
  }
  .compare-source-cols > div {
    min-width: 0;
  }
  .compare-source-cols > div[class*="w-px"] {
    display: none !important;
  }
  .compare-source-cols > div[class*="w-20"] {
    width: auto !important;
    min-width: 0;
    align-items: flex-start !important;
    padding: 6px;
    border-radius: 10px;
    background: rgba(248, 250, 252, 0.86);
    overflow: hidden;
  }
  .compare-source-cols span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* works-pager 居中 */
  .works-pager { justify-content: center; }
  .works-pager :deep(.el-pagination__sizes),
  .works-pager :deep(.el-pagination__jump) { display: none !important; }

  .compare-head { display: none !important; }

  /* Preview Dialog ≤640 全屏（沿用已有 :deep selector） */
  :deep(.circle-preview-dialog .el-dialog) {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  :deep(.circle-preview-dialog .el-dialog__body) {
    padding: 14px 14px 8px !important;
    height: calc(100dvh - 56px) !important;
    overflow-y: auto !important;
  }
  :deep(.circle-preview-dialog .el-dialog__footer) {
    padding: 6px 14px 14px !important;
  }

  /* Reimport Dialog ≤640 全屏 */
  :deep(.circle-reimport-dialog .el-dialog) {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  :deep(.circle-reimport-dialog .el-dialog__header) {
    padding: 12px 14px 8px !important;
  }
  :deep(.circle-reimport-dialog .el-dialog__title) {
    font-size: 15px !important;
  }
  :deep(.circle-reimport-dialog .el-dialog__body) {
    padding: 12px 14px 8px !important;
    height: calc(100dvh - 110px) !important;
    overflow-y: auto !important;
  }
  :deep(.circle-reimport-dialog .el-dialog__footer) {
    padding: 0 14px 14px !important;
  }

  /* hero-search-wrap：移动端独占整行（已在 index.css 全局规则，但 padding 微调更紧） */
  .hero-search-wrap {
    width: 100%;
  }
}
</style>
