<template>
  <div class="circle-page">
    <AppPageHeader
      :icon="Tags"
      icon-color="var(--km-nav-circle-icon)"
      title="社团补全"
      subtitle="按社团建立索引，结合库存收录态、DLsite 关联与 asmr.one 下载能力补全缺失作品"
      class="circle-page-header"
    >
      <div class="hero-search-wrap">
        <Search :size="13" class="hero-search-icon" />
        <el-input
          v-model="heroWorkSearchQuery"
          class="hero-search-input"
          placeholder="搜索 RJ / 作品标题"
          clearable
          @keyup.enter="jumpToFirstHeroWorkSearchResult"
          @clear="clearHeroWorkSearch"
        />
        <div v-if="showHeroWorkSearchPanel" class="hero-work-search-panel">
          <div v-if="heroWorkSearchLoading" class="hero-work-search-state">搜索中...</div>
          <div v-else-if="heroWorkSearchQuery.trim() && heroWorkSearchSearched && !heroWorkSearchResults.length" class="hero-work-search-state no-data">
            <Hash :size="14" />
            <span>No Data</span>
          </div>
          <template v-else>
            <button
              v-for="item in heroWorkSearchResults"
              :key="`${item.circle_id}-${item.canonical_rjcode}`"
              type="button"
              class="hero-work-search-item"
              @click="jumpToHeroWorkSearchResult(item)"
            >
              <div class="hero-work-search-cover">
                <img v-if="item.thumb_image_url || item.image_url" :src="item.thumb_image_url || item.image_url" alt="" loading="lazy" decoding="async" />
                <Hash v-else :size="14" />
              </div>
              <div class="hero-work-search-main">
                <div class="hero-work-search-title" :title="item.title || item.display_rjcode">{{ item.title || item.display_rjcode }}</div>
                <div class="hero-work-search-meta">
                  <span>{{ item.display_rjcode || item.canonical_rjcode }}</span>
                  <span>{{ item.circle_name || item.circle_id }}</span>
                </div>
              </div>
              <span class="hero-work-search-status" :class="{ owned: item.owned }">{{ item.owned ? '已收录' : (item.has_asmr_one ? '可下载' : '未收录') }}</span>
            </button>
          </template>
        </div>
      </div>
      <el-button class="hero-btn hero-btn-primary" :loading="indexing" @click="openIndexPrompt">批量建立 / 刷新</el-button>
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
            {{ indexJob.circle_query || '当前社团' }} · {{ indexJob.current_step || '处理中' }}
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
        <span class="progress-meta-pill kikoeru" title="库存候选"><Headphones :size="10" /> {{ indexJob.meta.kikoeru_candidates_count || 0 }}</span>
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
            <div class="sidebar-head-actions">
              <el-button
                text
                class="sidebar-refresh-button"
                :loading="batchBonusProbeRunning"
                :disabled="indexing || isRefreshJobActive || isBonusProbeJobActive"
                @click="startBonusProbeForVisibleCircles"
              >
                <Gift :size="12" />
                批量特典
              </el-button>
              <el-button text class="sidebar-refresh-button" @click="loadRecentCircles">刷新</el-button>
            </div>
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
              :class="{ active: activeCircleId === circle.circle_id, 'has-new-work': (circle.new_works_48h_count || 0) > 0 }"
              @click="selectCircle(circle.circle_id)"
            >
              <div class="circle-list-header">
                <div class="circle-list-name">
                  <span class="circle-list-name-shell" :class="{ 'has-title-new-badge': (circle.new_works_48h_count || 0) > 0 }">
                    <span class="circle-list-name-text">{{ circle.circle_name || circle.circle_id }}</span>
                    <span v-if="(circle.new_works_48h_count || 0) > 0" class="circle-title-new-badge">NEW</span>
                  </span>
                </div>
                <div class="circle-list-id">{{ circle.circle_id }}</div>
              </div>
              <div class="circle-list-stats-row">
                <div class="circle-list-counts">
                  <span class="circle-stat-item total" title="DLsite作品数"><LibraryBig :size="10" /> {{ circle.dl_works || circle.total_works || 0 }}</span>
                  <span class="circle-stat-item owned" title="库存已收录"><Server :size="10" /> {{ circle.server_owned || 0 }}</span>
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
                <span v-if="(circle.new_works_48h_count || 0) > 0" class="circle-list-tag new-work">
                  <Mail :size="9" />
                  {{ circle.new_works_48h_count }} 新作
                </span>
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
            <div v-if="detail.total_works || circleWorksPage.total || detail.works?.length" class="toolbar-actions">
              <el-button
                class="batch-action-button"
                :disabled="!activeCircleId || indexing || isRefreshJobActive"
                :loading="indexing"
                @click="handleIndexOnlyNewWorks"
              >
                仅索引新作
              </el-button>
              <el-button
                class="batch-action-button bonus"
                :disabled="!activeCircleId || indexing || isRefreshJobActive || isBonusProbeJobActive"
                :loading="bonusProbeRunning"
                @click="startBonusProbeFromToolbar"
              >
                <Gift :size="13" style="margin-right:4px" />
                {{ bonusProbeActionLabel }}
              </el-button>
              <el-button
                class="batch-action-button bonus-refresh"
                :disabled="!activeCircleId || bonusWorksCount <= 0 || indexing || isRefreshJobActive || isBonusProbeJobActive || refreshingCurrentCircleBonuses"
                :loading="refreshingCurrentCircleBonuses"
                @click="refreshCurrentCircleBonusOwnedState"
              >
                <RefreshCw :size="13" style="margin-right:4px" />
                刷新特典拥有
              </el-button>
              <el-button
                class="batch-action-button refresh"
                :disabled="!activeCircleId || indexing || isRefreshJobActive || isBonusProbeJobActive"
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
          <div v-if="circleWorksPage.loading && circleDetailLoaded" class="circle-works-page-loading" aria-live="polite">
            <RefreshCw :size="13" class="circle-works-page-loading-icon" />
            <span>更新中</span>
          </div>
          <section v-if="bonusProbeJob.visible" class="index-progress-card refresh-progress-card bonus-progress-card">
            <div class="index-progress-head">
              <div>
                <div class="index-progress-title">特典补全进度</div>
                <div class="index-progress-subtitle">
                  {{ bonusProbeJob.circle_name || detail.circle_name || '当前社团' }} · {{ bonusProbeJob.current_step || '处理中' }}
                </div>
              </div>
              <div class="index-progress-head-actions">
                <el-button
                  v-if="canCancelBonusProbeJob"
                  size="small"
                  class="index-cancel-button"
                  :loading="cancellingBonusProbeJob"
                  @click="cancelBonusProbeJob"
                >
                  取消探测
                </el-button>
                <div class="index-progress-status" :class="bonusProbeJob.status">{{ bonusProbeJobStatusText }}</div>
              </div>
            </div>

            <div class="index-progress-bar-wrap">
              <AppLottieProgressBar :percentage="getJobProgressPercent(bonusProbeJob)" size="sm" :show-text="false" />
            </div>

            <div class="index-progress-meta">
              <span class="progress-meta-pill time" title="耗时"><Clock :size="10" /> {{ formatElapsed(bonusProbeJob.elapsed_seconds) }}</span>
              <span class="progress-meta-pill total" title="发售日"><Calendar :size="10" /> {{ bonusProbeJob.meta.release_dates_count || bonusProbeJob.release_dates.length || 0 }} 日</span>
              <span class="progress-meta-pill batch" title="已查 RJ"><Hash :size="10" /> {{ formatBonusProbeRjProgress(bonusProbeJob.meta, bonusProbeJob.current_step) }}</span>
              <span class="progress-meta-pill bonus" title="命中特典"><Gift :size="10" /> {{ bonusProbeJob.meta.hit_count || 0 }}</span>
              <span class="progress-meta-pill ok" title="写入数量"><CheckCircle2 :size="10" /> {{ bonusProbeJob.meta.inserted_count || 0 }}</span>
              <span class="progress-meta-pill dlsite" title="DLsite 请求"><Globe :size="10" /> {{ bonusProbeJob.meta.request_count || 0 }}</span>
            </div>

            <div v-if="bonusProbeJob.progress_log?.length" class="refresh-progress-log-list compact">
              <div
                v-for="entry in bonusProbeJob.progress_log.slice(-2)"
                :key="`${bonusProbeJob.job_id}-${entry.time}-${entry.message}`"
                class="refresh-progress-log-item"
                :class="entry.level || 'info'"
              >
                <span class="refresh-progress-log-time">{{ formatLogTime(entry.time) }}</span>
                <span class="refresh-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>

            <div v-if="bonusProbeJob.error_message" class="index-progress-error">{{ bonusProbeJob.error_message }}</div>
          </section>

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
              <span class="progress-meta-pill kikoeru" title="库存已收录"><Headphones :size="10" /> {{ refreshJob.meta.kikoeru_owned_count || 0 }}</span>
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

          <div class="circle-tabs-wrapper" :class="{ 'has-owned-search': activeTab === 'owned' }">
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
              <div v-if="activeTab === 'owned'" class="owned-search-wrap owned-search-wrap--top">
                <div class="owned-search-icon">
                  <Search :size="16" />
                </div>
                <input
                  v-model="ownedWorksSearchQuery"
                  type="text"
                  class="owned-search-input"
                  placeholder="搜索作品名或 RJ 号..."
                />
                <button
                  v-if="ownedWorksSearchQuery"
                  type="button"
                  class="owned-search-clear"
                  @click="ownedWorksSearchQuery = ''"
                >
                  <X :size="14" />
                </button>
              </div>
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

              <div v-if="missingWorks.length > 0 && selectedActiveCanonicalRJCodes.length > 0" class="selection-bar">
                <span class="selection-count">已选 {{ selectedActiveCanonicalRJCodes.length }} / {{ activeSelectableWorksTotal }}</span>
                <div class="flex items-center gap-2">
                  <button type="button" class="batch-action-button" @click="selectAllVisibleWorks">全选</button>
                  <button type="button" class="batch-action-button ghost" @click="clearSelection">清空</button>
                  <button
                    type="button"
                    class="batch-action-button refresh"
                    :class="{ 'is-busy': refreshingCurrentCircle }"
                    :disabled="isRefreshJobActive || isBonusProbeJobActive"
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
                  description="正在同步缺失作品、库存收录态和可下载信息"
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
                :total-items="circleWorksPage.tab === 'missing' ? circleWorksPage.total : missingWorks.length"
                server-paging
                :mode="viewMode"
                :page-sizes="worksPageSizes"
                :selected-codes="selectedCanonicals"
                :flashed-codes="flashedWorkCodes"
                :located-codes="locatedWorkCodes"
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
              <div class="owned-panel">
                <div class="owned-stats-strip">
                  <div class="owned-stats-list">
                    <button
                      type="button"
                      class="owned-stat-item is-total"
                      :class="{ 'is-active': ownedWorksFilterType === 'all' }"
                      :aria-pressed="ownedWorksFilterType === 'all'"
                      title="筛选全部已满足作品"
                      @click="setOwnedWorksFilter('all')"
                    >
                      <div class="owned-stat-icon is-total">
                        <LibraryBig :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">总收录</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.total }}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      class="owned-stat-item is-simplified"
                      :class="{ 'is-active': ownedWorksFilterType === 'simplified' }"
                      :aria-pressed="ownedWorksFilterType === 'simplified'"
                      title="筛选简中作品"
                      @click="setOwnedWorksFilter('simplified')"
                    >
                      <div class="owned-stat-icon is-simplified">
                        <Languages :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">简中</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.simplified }}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      class="owned-stat-item is-traditional"
                      :class="{ 'is-active': ownedWorksFilterType === 'traditional' }"
                      :aria-pressed="ownedWorksFilterType === 'traditional'"
                      title="筛选繁中作品"
                      @click="setOwnedWorksFilter('traditional')"
                    >
                      <div class="owned-stat-icon is-traditional">
                        <Languages :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">繁中</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.traditional }}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      class="owned-stat-item is-original"
                      :class="{ 'is-active': ownedWorksFilterType === 'original' }"
                      :aria-pressed="ownedWorksFilterType === 'original'"
                      title="筛选原作"
                      @click="setOwnedWorksFilter('original')"
                    >
                      <div class="owned-stat-icon is-original">
                        <PlayCircle :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">原作</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.original }}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      class="owned-stat-item is-subtitle"
                      :class="{ 'is-active': ownedWorksFilterType === 'subtitle' }"
                      :aria-pressed="ownedWorksFilterType === 'subtitle'"
                      title="筛选含字幕作品"
                      @click="setOwnedWorksFilter('subtitle')"
                    >
                      <div class="owned-stat-icon is-subtitle">
                        <Subtitles :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">含字幕</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.subtitle }}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      class="owned-stat-item is-bonus"
                      :class="{ 'is-active': ownedWorksFilterType === 'bonus' }"
                      :aria-pressed="ownedWorksFilterType === 'bonus'"
                      title="筛选特典作品"
                      @click="setOwnedWorksFilter('bonus')"
                    >
                      <div class="owned-stat-icon is-bonus">
                        <Gift :size="14" stroke-width="2.5" />
                      </div>
                      <div class="flex flex-col">
                        <span class="owned-stat-label">特典</span>
                        <span class="owned-stat-value">{{ ownedWorksStats.bonus }}</span>
                      </div>
                    </button>
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
                <div class="owned-empty-state">
                  <LibraryBig :size="32" class="mb-3 opacity-40" />
                  <p class="text-sm font-medium">没有找到符合条件的作品</p>
                </div>
              </template>
              <template v-else>
                <div v-if="ownedWorks.length > 0 && selectedActiveCanonicalRJCodes.length > 0" class="selection-bar">
                  <span class="selection-count">已选 {{ selectedActiveCanonicalRJCodes.length }} / {{ activeSelectableWorksTotal }}</span>
                  <div class="flex items-center gap-2">
                    <button type="button" class="batch-action-button" @click="selectAllVisibleWorks">全选</button>
                    <button type="button" class="batch-action-button ghost" @click="clearSelection">清空</button>
                    <button
                      type="button"
                      class="batch-action-button refresh"
                      :class="{ 'is-busy': refreshingCurrentCircle }"
                      :disabled="isRefreshJobActive || isBonusProbeJobActive"
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
                  :total-items="circleWorksPage.tab === 'owned' ? circleWorksPage.total : ownedWorks.length"
                  server-paging
                  :mode="viewMode"
                  :page-sizes="worksPageSizes"
                  :selected-codes="selectedCanonicals"
                  :flashed-codes="flashedWorkCodes"
                  :located-codes="locatedWorkCodes"
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
                <div class="compare-stats-list">
                  <div class="compare-stat-item">
                    <div class="compare-stat-icon is-total">
                      <LibraryBig :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="compare-stat-label">总数</span>
                      <span class="compare-stat-value">{{ compareWorksStats.total }}</span>
                    </div>
                  </div>
                  <div class="compare-stat-item">
                    <div class="compare-stat-icon is-kikoeru">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="compare-stat-label">库存</span>
                      <span class="compare-stat-value">{{ compareWorksStats.kikoeru }}</span>
                    </div>
                  </div>
                  <div class="compare-stat-item">
                    <div class="compare-stat-icon is-dlsite">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="compare-stat-label">DLsite</span>
                      <span class="compare-stat-value">{{ compareWorksStats.dlsite }}</span>
                    </div>
                  </div>
                  <div class="compare-stat-item">
                    <div class="compare-stat-icon is-asmr">
                      <CheckCircle2 :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="compare-stat-label">ASMR.ONE</span>
                      <span class="compare-stat-value">{{ compareWorksStats.asmr_one }}</span>
                    </div>
                  </div>
                  <div class="compare-stat-item">
                    <div class="compare-stat-icon is-missing">
                      <XCircle :size="14" stroke-width="2.5" />
                    </div>
                    <div class="flex flex-col">
                      <span class="compare-stat-label">暂无来源</span>
                      <span class="compare-stat-value">{{ compareWorksStats.missing }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Actions Toolbar -->
              <div class="compare-filter-row flex items-center justify-between mb-4">
                <div class="compare-filter-tabs">
                  <button type="button" class="compare-filter-chip" :class="{ 'is-active': compareSourceFilter === 'all' }" @click="compareSourceFilter = 'all'; comparePage = 1">全部</button>
                  <button type="button" class="compare-filter-chip is-kikoeru" :class="{ 'is-active': compareSourceFilter === 'kikoeru' }" @click="compareSourceFilter = 'kikoeru'; comparePage = 1">库存已收录</button>
                  <button type="button" class="compare-filter-chip is-asmr" :class="{ 'is-active': compareSourceFilter === 'asmr_one' }" @click="compareSourceFilter = 'asmr_one'; comparePage = 1">可下载(ASMR.ONE)</button>
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

                  <div class="compare-search-wrap">
                  <div class="compare-search-icon">
                    <Search :size="16" />
                  </div>
                  <input
                    v-model="compareSearchQuery"
                    type="text"
                    @input="comparePage = 1"
                    class="compare-search-input"
                    placeholder="搜索作品名或 RJ 号..."
                  />
                  <button 
                    v-if="compareSearchQuery" 
                    @click="compareSearchQuery = ''; comparePage = 1" 
                    class="compare-search-clear"
                  >
                    <X :size="14" />
                  </button>
                </div>
                </div>
              </div>

              <!-- Header -->
              <div class="compare-head">
                <div class="compare-head-main">资源信息</div>
                <div class="compare-head-sources">
                  <div class="compare-source-col">库存</div>
                  <div class="compare-source-divider is-transparent"></div>
                  <div class="compare-source-col">DLsite</div>
                  <div class="compare-source-divider is-transparent"></div>
                  <div class="compare-source-col">ASMR.ONE</div>
                </div>
              </div>

              <!-- List -->
              <div class="compare-works-list" v-auto-animate="compareAutoAnimateOptions">
                <div v-for="item in pagedCompareWorks" :key="`compare-${item.workRjcode}`" class="compare-work-item">
                  <div class="compare-work-row flex items-start justify-between gap-4">
                    <!-- Title & Badges -->
                    <div class="compare-work-main flex-1 min-w-0">
                      <h4 class="compare-work-title" :title="item.title || item.workRjcode || '未命名作品'">{{ item.title || item.workRjcode || '未命名作品' }}</h4>
                      <div class="compare-work-tags flex items-center gap-2">
                        <!-- Status Badge -->
                        <span v-if="item.statusKey === 'owned'" class="compare-status-inline is-owned" title="库存已收录">
                          <CheckCircle2 :size="14" stroke-width="2.5" />
                          已拥有
                        </span>
                        <span v-else-if="item.statusKey === 'missing'" class="compare-status-inline is-missing" title="未拥有">
                          <XCircle :size="14" stroke-width="2.5" />
                          未拥有
                        </span>
                        <span v-else-if="item.statusKey === 'partial'" class="compare-status-inline is-partial" title="部分拥有">
                          <AlertCircle :size="14" stroke-width="2.5" />
                          部分拥有
                        </span>
                        <span v-else class="compare-status-inline">
                          <MinusCircle :size="14" stroke-width="2.5" />
                          {{ item.statusLabel }}
                        </span>

                        <span class="compare-work-code">{{ item.workRjcode || '—' }}</span>

                        <!-- Variant Tags -->
                        <span v-if="item.preferredVariantLabel && item.preferredVariantLabel !== '—'" class="compare-variant-badge" :class="getVariantBadgeClass(item.preferredVariantLabel)">
                          {{ item.preferredVariantLabel }}
                        </span>

                        <!-- Subtitle Icon (compat source tags contain 字幕) -->
                        <span v-if="normalizeKikoeruTags(item.sourceCompare.kikoeru.tags).includes('字幕')" class="compare-variant-badge is-subtitle">
                          <MessageSquareText :size="12" stroke-width="2.5" />
                          字幕
                        </span>
                      </div>
                    </div>

                    <!-- Source Info -->
                    <div class="compare-source-cols flex items-center gap-4 text-xs shrink-0 mt-0.5">
                      <!-- 库存收录 -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <span v-if="item.sourceCompare.kikoeru.primary_rjcode" class="compare-source-code">{{ item.sourceCompare.kikoeru.primary_rjcode }}</span>
                        <span v-else class="compare-source-empty">—</span>
                        <div v-if="item.sourceCompare.kikoeru.variantBadges.length || normalizeKikoeruTags(item.sourceCompare.kikoeru.tags).length" class="flex flex-wrap items-center justify-center gap-1 mt-0.5">
                          <span v-for="badge in item.sourceCompare.kikoeru.variantBadges" :key="`kb-${item.workRjcode}-${badge}`" class="compare-source-badge" :class="getVariantBadgeClass(badge)">{{ badge }}</span>
                        </div>
                      </div>
                      
                      <div class="compare-source-divider"></div>
                      
                      <!-- DLsite -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <div v-if="item.sourceCompare.dlsite.all_rjcodes.length" class="flex flex-col items-center gap-0.5">
                          <span v-for="code in item.sourceCompare.dlsite.all_rjcodes" :key="`d-${item.workRjcode}-${code}`" class="compare-source-code">{{ code }}</span>
                        </div>
                        <span v-else class="compare-source-empty">—</span>
                      </div>
                      
                      <div class="compare-source-divider"></div>

                      <!-- ASMR.ONE -->
                      <div class="flex flex-col items-center gap-1 w-20">
                        <div v-if="item.sourceCompare.asmr_one.primary_rjcode" class="flex flex-col items-center">
                          <span class="compare-source-code">{{ item.sourceCompare.asmr_one.primary_rjcode }}</span>
                          <span v-if="item.sourceCompare.asmr_one.primaryBadge" class="compare-source-badge mt-0.5" :class="getVariantBadgeClass(item.sourceCompare.asmr_one.primaryBadge)">{{ item.sourceCompare.asmr_one.primaryBadge }}</span>
                        </div>
                        <span v-else class="compare-source-empty">—</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="works-pager km-pagination-wrap">
                <el-pagination
                  v-model:current-page="comparePage"
                  v-model:page-size="comparePageSize"
                  :page-sizes="comparePageSizes"
                  :total="compareWorksFilteredCount"
                  layout="total, sizes, prev, pager, next, jumper"
                  popper-class="km-pagination-size-popper"
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
                  <div class="info-value">{{ detail.total_works || circleWorksPage.total || detail.works?.length || 0 }}</div>
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
      :loading-label="previewProgressLabel"
      :loading-description="previewProgressDescription"
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
      :enable-file-retry="true"
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
import { useRoute } from 'vue-router'
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
import { normalizeTaskCenterRealtimePayloads } from '../composables/taskCenterEventUtils'
import { showSystemConfirm, showSystemPrompt } from '../composables/useSystemPrompt'
import { useRealtimeEvents } from '../composables/useRealtimeEvents'

const route = useRoute()
const CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY = 'kikoerumanager.circleCompletion.targetSubdirs'
const CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.downloadWorkbench'
const CIRCLE_COMPLETION_REFRESH_JOB_KEY = 'kikoerumanager.circleCompletion.refreshJob'
const CIRCLE_COMPLETION_INDEX_JOB_KEY = 'kikoerumanager.circleCompletion.indexJob'
const CIRCLE_COMPLETION_BONUS_PROBE_JOB_KEY = 'kikoerumanager.circleCompletion.bonusProbeJob'
const CIRCLE_COMPLETION_UPLOAD_WORKBENCH_KEY = 'kikoerumanager.circleCompletion.uploadWorkbench'
const realtimeEvents = useRealtimeEvents()
function getJobProgressPercent(job) {
  const value = Number(job?.progress || 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

function toProgressCount(value) {
  const count = Number(value || 0)
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0
}

function formatBonusProbeRjProgress(meta = {}, currentStep = '') {
  const total = toProgressCount(meta.probe_count)
  const checked = Math.min(toProgressCount(meta.checked_probe_count), total || Number.MAX_SAFE_INTEGER)
  if (total > 0) return `${checked} / ${total}`
  const stepMatch = String(currentStep || '').match(/[：:]\s*(\d+)\s*\/\s*(\d+)/)
  if (stepMatch) return `${Number(stepMatch[1] || 0)} / ${Number(stepMatch[2] || 0)}`
  return String(checked)
}

function mergeBonusProbeMeta(current = {}, incoming = {}) {
  const next = { ...(current || {}) }
  const source = incoming && typeof incoming === 'object' ? incoming : {}
  for (const [key, value] of Object.entries(source)) {
    if (value == null || value === '') continue
    next[key] = value
  }
  if (toProgressCount(next.current_probe_total_count) > 0) {
    next.probe_count = toProgressCount(next.probe_count) || toProgressCount(next.current_probe_total_count)
  }
  if (toProgressCount(next.current_probe_checked_count) > 0) {
    next.checked_probe_count = Math.max(
      toProgressCount(next.checked_probe_count),
      toProgressCount(next.current_probe_checked_count),
    )
  }
  return next
}

const circleSearch = ref('')
const circleSearchRequestSeq = ref(0)
const heroWorkSearchQuery = ref('')
const heroWorkSearchResults = ref([])
const heroWorkSearchLoading = ref(false)
const heroWorkSearchSearched = ref(false)
const heroWorkSearchRequestSeq = ref(0)
const circleCompletionFilter = ref('all')
const circleSortKey = ref('refreshed_at')

// 侧边栏「排序」下拉选项
const circleSortKeyOptions = [
  { value: 'completion', label: '收集程度' },
  { value: 'refreshed_at', label: '刷新时间' },
  { value: 'works', label: '作品数量' },
  { value: 'missing', label: '缺失数量' },
  { value: 'owned', label: '库存收录数量' },
]
const indexing = ref(false)
const emailCheckLoading = ref(false)
const batchBonusProbeRunning = ref(false)
const previewing = ref(false)
const previewLoading = ref(false)
const previewProgressLabel = ref('正在分析资源结构并生成下载计划...')
const previewProgressDescription = ref('聚合资源分组、语言版本和推荐项')
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
  filtered_count: 0,
  total_works: 0,
  unreleased_count: 0,
  new_works_count: 0,
  bonus_works_count: 0,
  owned_stats: { total: 0, original: 0, simplified: 0, traditional: 0, subtitle: 0, bonus: 0 },
  compare_stats: { total: 0, kikoeru: 0, dlsite: 0, asmr_one: 0, missing: 0 },
  status_filter_counts: { missing: {}, owned: {} },
  works: []
})
const CIRCLE_DETAIL_CACHE_TTL = 5 * 60 * 1000
const CIRCLE_DETAIL_PREFETCH_LIMIT = 1
const DOWNLOAD_PREVIEW_JOB_THRESHOLD = 8
const circleDetailCache = new Map()
const circleWorksPageCache = new Map()
let circleDetailRequestSeq = 0
let circleDetailAbortController = null
let circleDetailPrefetchTimer = null
let circleDetailPrefetchIdleId = null
let circleDetailPrefetchIdleIsTimeout = false
let circleDetailPrefetchRunning = false
let circleWorksFetchTimer = null
let circleSearchFetchTimer = null
let heroWorkSearchFetchTimer = null
let heroWorkSearchAbortController = null
let lastAppliedRouteCircleKey = ''
let suppressCircleWorksRefresh = false
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
  { value: 'has_early_bonus', label: '有早期特典' },
  { value: 'no_early_bonus', label: '无早期特典' },
]
const statusFilterExclusiveGroups = [
  ['downloadable', 'no_source'],
  ['repairable', 'missing'],
  ['has_early_bonus', 'no_early_bonus'],
]
const statusFilterOptions = computed(() => {
  const counts = detail.status_filter_counts?.[activeTab.value] || {}
  return statusFilterBaseOptions.map(option => ({
    ...option,
    suffix: Number(counts[option.value] || 0),
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
    filtered_count: 0,
    total_works: 0,
    unreleased_count: 0,
    new_works_count: 0,
    bonus_works_count: 0,
    owned_stats: { total: 0, original: 0, simplified: 0, traditional: 0, subtitle: 0, bonus: 0 },
    compare_stats: { total: 0, kikoeru: 0, dlsite: 0, asmr_one: 0, missing: 0 },
    status_filter_counts: { missing: {}, owned: {} },
    works: []
  })
  circleDetailLoaded.value = false
  circleDetailLoading.value = false
  selectedCanonicals.value = new Set()
  selectedDownloadableCanonicals.value = new Set()
  selectedRequestedRjcodes.value = {}
  locatedWorkCodes.value = new Set()
  Object.assign(circleWorksPage, { tab: 'missing', total: 0, page: 1, page_size: 10, page_count: 1, loading: false })
}

function getCircleDetailCacheKey(circleId) {
  return `${String(circleId || '').trim()}::dlOnly=${filters.includeDlOnly ? 1 : 0}::view=${viewMode.value === 'card' ? 'card' : 'list'}`
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
    filtered_count: Number(payload.filtered_count || 0),
    total_works: Number(payload.total_works || payload.dl_count || 0),
    unreleased_count: Number(payload.unreleased_count || 0),
    new_works_count: Number(payload.new_works_count || 0),
    bonus_works_count: Number(payload.bonus_works_count || 0),
    owned_stats: { total: 0, original: 0, simplified: 0, traditional: 0, subtitle: 0, bonus: 0, ...(payload.owned_stats || {}) },
    compare_stats: { total: 0, kikoeru: 0, dlsite: 0, asmr_one: 0, missing: 0, ...(payload.compare_stats || {}) },
    status_filter_counts: {
      missing: { ...(payload.status_filter_counts?.missing || {}) },
      owned: { ...(payload.status_filter_counts?.owned || {}) },
    },
    works_page: {
      tab: String(payload.works_page?.tab || payload.tab || 'missing'),
      total: Number(payload.works_page?.total ?? payload.total ?? payload.missing_count ?? 0),
      page: Number(payload.works_page?.page ?? payload.page ?? 1),
      page_size: Number(payload.works_page?.page_size ?? payload.page_size ?? worksPageSize.value ?? 10),
      page_count: Number(payload.works_page?.page_count ?? payload.page_count ?? 1),
    },
    works: Array.isArray(payload.works) ? payload.works.map(item => ({ ...item })) : []
  }
}

function buildCachedCircleDetailPayload(summary = {}, works = {}) {
  const pageTotal = Number(works?.total ?? works?.filtered_count ?? summary?.missing_count ?? 0)
  const pageSize = Number(works?.page_size ?? worksPageSize.value ?? 10)
  return {
    ...summary,
    works: Array.isArray(works?.items) ? works.items : [],
    works_page: {
      tab: String(works?.tab || 'missing'),
      total: pageTotal,
      page: Number(works?.page || 1),
      page_size: pageSize,
      page_count: Number(works?.page_count || Math.max(1, Math.ceil(pageTotal / Math.max(1, pageSize)))),
    },
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

function getCircleWorksPageCacheKey(circleId, query = buildCircleWorksQuery()) {
  const normalizedQuery = {
    tab: String(query?.tab || activeTab.value || 'missing'),
    page: Number(query?.page || 1),
    pageSize: Number(query?.pageSize || query?.page_size || 10),
    includeDlOnly: Boolean(query?.includeDlOnly),
    statusFilters: Array.isArray(query?.statusFilters) ? [...query.statusFilters].sort() : [],
    ownedFilter: String(query?.ownedFilter || 'all'),
    compareFilter: String(query?.compareFilter || 'all'),
    search: String(query?.search || '').trim(),
    sort: String(query?.sort || 'updated_desc'),
    viewMode: String(query?.viewMode || (viewMode.value === 'card' ? 'card' : 'list')),
  }
  return `${String(circleId || '').trim()}::${JSON.stringify(normalizedQuery)}`
}

function cloneCircleWorksPagePayload(payload = {}) {
  return {
    ...payload,
    items: Array.isArray(payload.items) ? payload.items.map(item => ({ ...item })) : [],
    owned_stats: payload.owned_stats ? { ...payload.owned_stats } : undefined,
    compare_stats: payload.compare_stats ? { ...payload.compare_stats } : undefined,
    status_filter_counts: payload.status_filter_counts ? {
      missing: { ...(payload.status_filter_counts.missing || {}) },
      owned: { ...(payload.status_filter_counts.owned || {}) },
    } : undefined,
  }
}

function getCachedCircleWorksPage(circleId, query = buildCircleWorksQuery()) {
  const key = getCircleWorksPageCacheKey(circleId, query)
  const cached = circleWorksPageCache.get(key)
  if (!cached) return null
  if (Date.now() - cached.cachedAt > CIRCLE_DETAIL_CACHE_TTL) {
    circleWorksPageCache.delete(key)
    return null
  }
  return cloneCircleWorksPagePayload(cached.payload)
}

function setCachedCircleWorksPage(circleId, query, payload) {
  const key = getCircleWorksPageCacheKey(circleId, query)
  circleWorksPageCache.set(key, {
    cachedAt: Date.now(),
    payload: cloneCircleWorksPagePayload(payload),
  })
  while (circleWorksPageCache.size > 48) {
    const oldestKey = circleWorksPageCache.keys().next().value
    if (!oldestKey) break
    circleWorksPageCache.delete(oldestKey)
  }
}

function invalidateCircleWorksPageCache(circleId = '') {
  const target = String(circleId || '').trim()
  if (!target) {
    circleWorksPageCache.clear()
    return
  }
  for (const key of [...circleWorksPageCache.keys()]) {
    if (key.startsWith(`${target}::`)) circleWorksPageCache.delete(key)
  }
}

function invalidateCircleDetailCache(circleId = '') {
  const target = String(circleId || '').trim()
  if (!target) {
    circleDetailCache.clear()
    circleWorksPageCache.clear()
    return
  }
  for (const key of [...circleDetailCache.keys()]) {
    if (key.startsWith(`${target}::`)) circleDetailCache.delete(key)
  }
  invalidateCircleWorksPageCache(target)
}

function applyCircleDetailPayload(payload, { loaded = true } = {}) {
  const normalized = cloneCircleDetailPayload(payload)
  Object.assign(detail, normalized)
  circleDetailLoaded.value = loaded
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
    filtered_count: 0,
    total_works: Number(circle?.dl_works || circle?.total_works || 0),
    unreleased_count: Number(circle?.unreleased_count || 0),
    new_works_count: Number(circle?.new_works_48h_count || circle?.new_works_count || 0),
    bonus_works_count: 0,
    owned_stats: { total: Number(circle?.owned_count ?? circle?.server_owned ?? 0), original: 0, simplified: 0, traditional: 0, subtitle: 0, bonus: 0 },
    compare_stats: { total: Number(circle?.dl_works || circle?.total_works || 0), kikoeru: Number(circle?.owned_count ?? circle?.server_owned ?? 0), dlsite: Number(circle?.dl_works || 0), asmr_one: Number(circle?.asmr_available || 0), missing: 0 },
    status_filter_counts: { missing: {}, owned: {} },
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
const selectedDownloadableCanonicals = ref(new Set())
const selectedRequestedRjcodes = ref({})
const flashedWorkCodes = ref(new Set())
const locatedWorkCodes = ref(new Set())
const circleWorksPage = reactive({
  tab: 'missing',
  total: 0,
  page: 1,
  page_size: 10,
  page_count: 1,
  loading: false
})
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
const worksPageSizes = [10, 20, 50, 100]
const comparePageSizes = [10, 20, 50, 100]
const worksPageSize = ref(10)
const comparePageSize = ref(10)
const missingPage = ref(1)
const missingSort = ref('default') // 'default' | 'downloadable' | 'title'
const worksReleaseSort = ref('desc')
const viewMode = ref('card') // 'card' | 'list'
watch(missingSort, () => { missingPage.value = 1; scheduleCircleWorksRefresh() })
watch(worksReleaseSort, () => { missingPage.value = 1; ownedPage.value = 1; comparePage.value = 1; scheduleCircleWorksRefresh() })
watch([circleCompletionFilter, circleSortKey], () => {
  syncActiveCircleWithList({ preserveActiveWhenEmpty: true })
})
const ownedPage = ref(1)
const comparePage = ref(1)
function getActiveWorksPage() {
  if (activeTab.value === 'owned') return ownedPage.value
  if (activeTab.value === 'compare') return comparePage.value
  return missingPage.value
}

function getActiveWorksPageSize() {
  return activeTab.value === 'compare'
    ? Number(comparePageSize.value || 10)
    : Number(worksPageSize.value || 10)
}

function getCircleWorksSort() {
  if (worksReleaseSort.value === 'asc') return 'release_asc'
  if (worksReleaseSort.value === 'desc') return 'release_desc'
  return 'updated_desc'
}

function buildCircleWorksQuery(options = {}) {
  const includePage = options.includePage !== false
  const tab = options.tab || activeTab.value || 'missing'
  return {
    tab,
    page: includePage ? getActiveWorksPage() : 1,
    pageSize: includePage ? getActiveWorksPageSize() : 1,
    includeDlOnly: filters.includeDlOnly,
    statusFilters: [...statusFilters.value],
    ownedFilter: ownedWorksFilterType.value,
    compareFilter: compareSourceFilter.value,
    search: tab === 'owned'
      ? ownedWorksSearchQuery.value.trim()
      : (tab === 'compare' ? compareSearchQuery.value.trim() : ''),
    sort: getCircleWorksSort(),
    viewMode: viewMode.value === 'card' ? 'card' : 'list',
  }
}

function applyCircleSummaryPayload(payload = {}) {
  const normalized = cloneCircleDetailPayload({ ...payload, works: detail.works || [] })
  Object.assign(detail, {
    ...normalized,
    works: detail.works || []
  })
  circleDetailLoaded.value = true
}

function applyCircleWorksPayload(payload = {}) {
  detail.works = Array.isArray(payload.items) ? payload.items.map(item => ({ ...item })) : []
  detail.filtered_count = Number(payload.total || payload.filtered_count || 0)
  Object.assign(circleWorksPage, {
    tab: String(payload.tab || activeTab.value || 'missing'),
    total: Number(payload.total || 0),
    page: Number(payload.page || getActiveWorksPage()),
    page_size: Number(payload.page_size || getActiveWorksPageSize()),
    page_count: Number(payload.page_count || 1),
    loading: false
  })
  for (const key of ['owned_count', 'missing_count', 'downloadable_count', 'dl_only_count', 'total_works', 'unreleased_count', 'new_works_count', 'bonus_works_count']) {
    if (payload[key] !== undefined) detail[key] = Number(payload[key] || 0)
  }
  if (payload.owned_stats) detail.owned_stats = { total: 0, original: 0, simplified: 0, traditional: 0, subtitle: 0, bonus: 0, ...payload.owned_stats }
  if (payload.compare_stats) detail.compare_stats = { total: 0, kikoeru: 0, dlsite: 0, asmr_one: 0, missing: 0, ...payload.compare_stats }
  if (payload.status_filter_counts) {
    detail.status_filter_counts = {
      missing: { ...(payload.status_filter_counts.missing || {}) },
      owned: { ...(payload.status_filter_counts.owned || {}) },
    }
  }
}

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
let indexJobElapsedTimer = null
let indexJobLastRealtimeAt = 0
let refreshJobLastRealtimeAt = 0
let bonusProbeJobLastRealtimeAt = 0
const cancellingIndexJob = ref(false)
const refreshingCurrentCircle = ref(false)
const refreshingCurrentCircleBonuses = ref(false)
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
const bonusProbeRunning = ref(false)
const cancellingBonusProbeJob = ref(false)
const bonusProbeJob = reactive({
  visible: false,
  job_id: '',
  status: '',
  progress: 0,
  current_step: '',
  circle_id: '',
  circle_name: '',
  release_dates: [],
  elapsed_seconds: 0,
  error_message: '',
  meta: {},
  result: {},
  progress_log: []
})
let bonusProbeJobTimer = null
let bonusProbeJobAutoHideTimer = null
const JOB_FALLBACK_POLL_INTERVAL_MS = 30000
const JOB_SSE_STALE_MS = 45000
const handledCircleTerminalTasks = new Set()
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
let locatedWorkTimer = null
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
    case 'has_early_bonus':
      return String(item?.early_bonus_status || '').trim() === 'has_bonus'
    case 'no_early_bonus':
      return String(item?.early_bonus_status || '').trim() === 'no_bonus'
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
  return activeTab.value === 'missing' ? (detail.works || []) : []
})

const missingWorksTotal = computed(() =>
  Math.max(0, Number(detail.missing_count || 0))
)

const unreleasedWorksCount = computed(() =>
  Number(detail.unreleased_count || 0)
)

// 工具栏"新作 N"统计：直接读后端打的 item.is_new_work（与 WorkCard / WorkListRow
// 同一来源），保证左侧 search_circles 的 new_works_48h_count、右侧卡片特效、
// 以及这里的工具栏数字三方永远对齐，不会再出现"卡片闪新作但左侧没标记"。
const newWorksCount = computed(() =>
  Number(detail.new_works_count || 0)
)
const bonusWorksCount = computed(() =>
  Number(detail.bonus_works_count || 0)
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

function normalizeReleaseDateForBonusProbe(raw) {
  const text = String(raw || '').trim()
  if (!text) return ''

  const fullDateMatch = text.match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/)
  if (fullDateMatch) {
    const year = Number(fullDateMatch[1])
    const month = Number(fullDateMatch[2])
    const day = Number(fullDateMatch[3])
    const date = new Date(year, month - 1, day)
    if (
      year > 0
      && month >= 1
      && month <= 12
      && day >= 1
      && day <= 31
      && date.getFullYear() === year
      && date.getMonth() === month - 1
      && date.getDate() === day
    ) {
      return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    }
  }

  const compactMatch = text.match(/(?:^|\D)(\d{4})(\d{2})(\d{2})(?:\D|$)/)
  if (compactMatch) {
    return normalizeReleaseDateForBonusProbe(`${compactMatch[1]}-${compactMatch[2]}-${compactMatch[3]}`)
  }

  return ''
}

function getWorkBonusProbeDate(item) {
  return normalizeReleaseDateForBonusProbe(item?.original_release_date || item?.release_date || item?.date || item?.release_at || '')
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
const compareAutoAnimateOptions = {
  duration: 240,
  easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
}

function scheduleCircleSearchRefresh() {
  if (circleSearchFetchTimer) {
    clearTimeout(circleSearchFetchTimer)
    circleSearchFetchTimer = null
  }
  circleSearchFetchTimer = setTimeout(() => {
    circleSearchFetchTimer = null
    scheduleCircleWorksRefresh()
  }, 260)
}

watch(ownedWorksSearchQuery, () => {
  ownedPage.value = 1
  if (activeTab.value === 'owned') scheduleCircleSearchRefresh()
})
watch(compareSearchQuery, () => {
  comparePage.value = 1
  if (activeTab.value === 'compare') scheduleCircleSearchRefresh()
})
watch(compareSourceFilter, () => {
  comparePage.value = 1
  if (activeTab.value === 'compare') scheduleCircleWorksRefresh()
})
const showHeroWorkSearchPanel = computed(() =>
  Boolean(heroWorkSearchQuery.value.trim())
  && (heroWorkSearchLoading.value || heroWorkSearchSearched.value || heroWorkSearchResults.value.length > 0)
)

watch(heroWorkSearchQuery, () => {
  scheduleHeroWorkSearch()
})

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

function hasAttachedBonusWorks(item) {
  return Array.isArray(item?.bonus_works) && item.bonus_works.some(bonus => isBonusDisplayWork(bonus))
}

const detailWorksByCanonical = computed(() => {
  const map = new Map()
  for (const item of Array.isArray(detail.works) ? detail.works : []) {
    const code = String(item?.canonical_rjcode || '').trim()
    if (code) map.set(code, item)
  }
  return map
})

function setOwnedWorksFilter(type) {
  if (ownedWorksFilterType.value === type) return
  ownedWorksFilterType.value = type
  ownedPage.value = 1
  if (activeTab.value === 'owned') scheduleCircleWorksRefresh()
}

const ownedWorks = computed(() => {
  return activeTab.value === 'owned' ? (detail.works || []) : []
})

const ownedWorksStats = computed(() => {
  return {
    total: Number(detail.owned_stats?.total || 0),
    original: Number(detail.owned_stats?.original || 0),
    simplified: Number(detail.owned_stats?.simplified || 0),
    traditional: Number(detail.owned_stats?.traditional || 0),
    subtitle: Number(detail.owned_stats?.subtitle || 0),
    bonus: Number(detail.owned_stats?.bonus || 0),
  }
})

const compareWorks = computed(() => activeTab.value === 'compare' ? (detail.works || []) : [])

function formatServerOwnedLabel(item) {
  if (!item?.server_owned) return '库存未收录'
  const matched = String(
    item?.server_match_primary_rjcode ||
    item?.source_compare?.kikoeru?.matched_rjcode ||
    item?.source_compare?.kikoeru?.primary_rjcode ||
    ''
  ).trim()
  return matched ? `库存已收录 · ${matched}` : '库存已收录'
}

function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  const match = text.match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)
  return match ? match[0].toUpperCase() : text
}

function firstRouteQueryValue(value) {
  if (Array.isArray(value)) return String(value[0] || '').trim()
  return String(value || '').trim()
}

function getRouteCircleTarget() {
  const query = route.query || {}
  return {
    circleId: firstRouteQueryValue(query.circle_id || query.circleId),
    circleName: firstRouteQueryValue(query.circle_name || query.circleName),
    rjcode: normalizeRjcode(firstRouteQueryValue(query.rjcode || query.rj)),
  }
}

function getRouteCircleTargetKey(target) {
  return [target.circleId, target.circleName, target.rjcode].filter(Boolean).join('|')
}

function findRouteCircleCandidate(circleId, circleName, source = circleList.value) {
  const normalizedId = String(circleId || '').trim()
  const normalizedName = String(circleName || '').trim()
  const lowerName = normalizedName.toLowerCase()
  const list = Array.isArray(source) ? source : []
  if (normalizedId) {
    const byId = list.find(circle => String(circle?.circle_id || '').trim() === normalizedId)
    if (byId) return byId
  }
  if (!normalizedName) return null
  return list.find(circle => String(circle?.circle_name || '').trim() === normalizedName)
    || list.find(circle => String(circle?.circle_name || '').trim().toLowerCase() === lowerName)
    || list.find(circle => String(circle?.circle_id || '').trim() === normalizedName)
    || null
}

async function resolveRouteCircleCandidate(circleId, circleName) {
  const existing = findRouteCircleCandidate(circleId, circleName)
  if (existing) return existing

  const keyword = String(circleName || circleId || '').trim()
  if (!keyword) return null
  const result = await circleCompletionApi.searchCircles(keyword, 24)
  const circles = Array.isArray(result.circles) ? result.circles : []
  if (!circles.length) return null

  const candidate = findRouteCircleCandidate(circleId, circleName, circles) || circles[0]
  const hasCandidate = circleList.value.some(circle => String(circle?.circle_id || '').trim() === String(candidate?.circle_id || '').trim())
  circleList.value = hasCandidate ? circleList.value : [candidate, ...circles.filter(circle => String(circle?.circle_id || '').trim() !== String(candidate?.circle_id || '').trim())]
  return candidate
}

async function jumpToRouteRjcode(rjcode, circleName = '') {
  heroWorkSearchQuery.value = rjcode
  await searchHeroWork(rjcode)
  const normalizedName = String(circleName || '').trim()
  const lowerName = normalizedName.toLowerCase()
  const matched = heroWorkSearchResults.value.find(item => (
    normalizedName &&
    (
      String(item?.circle_name || '').trim() === normalizedName ||
      String(item?.circle_name || '').trim().toLowerCase() === lowerName ||
      String(item?.circle_id || '').trim() === normalizedName
    )
  ))
  const target = matched || heroWorkSearchResults.value[0]
  if (target) await jumpToHeroWorkSearchResult(target)
}

async function applyRouteCircleTarget(options = {}) {
  const target = getRouteCircleTarget()
  const routeKey = getRouteCircleTargetKey(target)
  if (!routeKey || (!options.force && routeKey === lastAppliedRouteCircleKey)) return false
  lastAppliedRouteCircleKey = routeKey

  const candidate = await resolveRouteCircleCandidate(target.circleId, target.circleName)
  const circleId = String(candidate?.circle_id || target.circleId || '').trim()
  const circleName = String(candidate?.circle_name || target.circleName || circleId).trim()

  if (target.rjcode) {
    if (circleId) {
      await jumpToHeroWorkSearchResult({
        circle_id: circleId,
        circle_name: circleName,
        canonical_rjcode: target.rjcode,
        display_rjcode: target.rjcode,
        owned: false
      })
    } else {
      await jumpToRouteRjcode(target.rjcode, circleName)
    }
    return true
  }

  if (!circleId) return false
  await ensureHeroSearchCircleVisible({ circle_id: circleId, circle_name: circleName }, { syncActive: false })
  await selectCircle(circleId)
  return true
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
        '库存已收录',
        ...(item.has_asmr_one ? ['可下载'] : ['暂不可下载']),
      ]
    }
  })
  if (!changed) return
  refreshActiveCircle({ summaryOnly: false }).catch(() => {})
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

function getVariantBadgeClass(label) {
  const text = String(label || '').trim()
  if (text === '简中') return 'is-simplified'
  if (text === '繁中') return 'is-traditional'
  if (text === '原作') return 'is-original'
  return 'is-generic'
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

function flashLocatedWork(code) {
  const normalized = String(code || '').trim()
  if (!normalized) return
  locatedWorkCodes.value = new Set([normalized])
  if (locatedWorkTimer) {
    window.clearTimeout(locatedWorkTimer)
    locatedWorkTimer = null
  }
  locatedWorkTimer = window.setTimeout(() => {
    locatedWorkCodes.value = new Set()
    locatedWorkTimer = null
  }, 3600)
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

const filteredCompareWorks = computed(() => {
  return compareWorks.value
})

const pagedCompareWorks = computed(() => {
  return filteredCompareWorks.value
})

const compareWorksFilteredCount = computed(() => circleWorksPage.tab === 'compare' ? circleWorksPage.total : Number(detail.compare_stats?.total || 0))

const compareWorksStats = computed(() => {
  return {
    total: Number(detail.compare_stats?.total || 0),
    kikoeru: Number(detail.compare_stats?.kikoeru || 0),
    dlsite: Number(detail.compare_stats?.dlsite || 0),
    asmr_one: Number(detail.compare_stats?.asmr_one || 0),
    missing: Number(detail.compare_stats?.missing || 0)
  }
})
const selectedCanonicalRJCodes = computed(() => [...selectedCanonicals.value])
const selectedDownloadableRJCodes = computed(() => selectedCanonicalRJCodes.value.filter(code => {
  return selectedDownloadableCanonicals.value.has(code)
}))
const activeSelectableWorks = computed(() => {
  if (activeTab.value === 'owned') return ownedWorks.value
  if (activeTab.value === 'missing') return missingWorks.value
  return []
})
const activeSelectableWorksTotal = computed(() => (
  ['missing', 'owned'].includes(activeTab.value) && circleWorksPage.tab === activeTab.value
    ? Number(circleWorksPage.total || activeSelectableWorks.value.length)
    : activeSelectableWorks.value.length
))
const selectedActiveCanonicalRJCodes = computed(() => selectedCanonicalRJCodes.value)
const activeSelectableWorksByCanonical = computed(() => {
  const map = new Map()
  for (const item of activeSelectableWorks.value) {
    const code = String(item?.canonical_rjcode || '').trim()
    if (code) map.set(code, item)
  }
  return map
})
const selectedActiveDownloadableRJCodes = computed(() => selectedActiveCanonicalRJCodes.value.filter(code => {
  return selectedDownloadableCanonicals.value.has(code)
}))
const bonusProbeActionLabel = computed(() => {
  const count = selectedActiveCanonicalRJCodes.value.length
  return count > 0 ? `选中特典 ${count}` : '特典补全'
})
function getPreviewRequestedRjcodes(canonicalCodes = []) {
  const mapping = {}
  canonicalCodes.forEach(code => {
    if (Array.isArray(selectedRequestedRjcodes.value?.[code]) && selectedRequestedRjcodes.value[code].length) {
      mapping[code] = [...selectedRequestedRjcodes.value[code]]
      return
    }
    const item = detailWorksByCanonical.value.get(code)
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
  tone: uploadBackgroundFailed.value ? 'amber' : 'primary',
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
    { key: 'resume', label: '恢复工作台', variant: 'primary' }
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
const bonusProbeJobStatusText = computed(() => {
  if (bonusProbeJob.error_message === '用户取消' || bonusProbeJob.current_step === '已取消') return '已取消'
  if (bonusProbeJob.status === 'completed') return '已完成'
  if (bonusProbeJob.status === 'failed') return '失败'
  if (bonusProbeJob.status === 'processing') return '进行中'
  return '等待中'
})
const isBonusProbeJobActive = computed(() =>
  Boolean(bonusProbeJob.job_id) && ['pending', 'processing'].includes(String(bonusProbeJob.status || ''))
)
const canCancelBonusProbeJob = computed(() => isBonusProbeJobActive.value)

onMounted(async () => {
  window.addEventListener('kikoerumanager:notification:new', handleNewReleaseNotification)
  window.addEventListener('kikoerumanager:circle:owned-synced', handleCircleOwnedSynced)
  window.addEventListener('kikoerumanager:circle:subtitle-synced', handleCircleOwnedSynced)
  window.addEventListener('kikoerumanager:events:message', handleCircleTaskRealtimeEvent)
  hydrateIndexJobState()
  hydrateRefreshJobState()
  hydrateBonusProbeJobState()
  hydrateDownloadWorkbenchState()
  restoreUploadWorkbenchState()
  loadCachedTargetSubdirs()
  await Promise.all([loadRecentCircles(), loadLibraries()])
  await applyRouteCircleTarget()
  if (trackedDownloadTaskIds.value.length) await refreshDownloadWorkbench()
  if (trackedUploadTaskIds.value.length) await refreshUploadWorkbench({ silent: true })
  if (indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || ''))) {
    await pollIndexJob(indexJob.job_id)
  }
  if (isRefreshJobActive.value) await pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length) {
      await refreshActiveCircle({ summaryOnly: false })
      flashChangedWorks(refreshJob.changed_codes)
    }
    resumeRefreshJobAutoHide()
  }
  if (isBonusProbeJobActive.value) await pollBonusProbeJob(bonusProbeJob.job_id, { silentFinish: true })
})

watch(() => route.fullPath, () => {
  applyRouteCircleTarget().catch(() => {})
})

onActivated(() => {
  applyRouteCircleTarget({ force: true }).catch(() => {})
  if (indexJob.job_id && ['pending', 'processing'].includes(String(indexJob.status || ''))) {
    indexing.value = true
    pollIndexJob(indexJob.job_id)
  }
  if (isRefreshJobActive.value) {
    refreshingCurrentCircle.value = true
    pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  } else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length && activeCircleId.value) {
      refreshActiveCircle({ summaryOnly: false }).then(() => {
        flashChangedWorks(refreshJob.changed_codes)
      }).catch(() => {})
    }
    resumeRefreshJobAutoHide()
  }
  if (isBonusProbeJobActive.value) {
    bonusProbeRunning.value = true
    pollBonusProbeJob(bonusProbeJob.job_id, { silentFinish: true })
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
  window.removeEventListener('kikoerumanager:circle:subtitle-synced', handleCircleOwnedSynced)
  window.removeEventListener('kikoerumanager:events:message', handleCircleTaskRealtimeEvent)
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
  if (circleDetailPrefetchIdleId !== null) {
    if (!circleDetailPrefetchIdleIsTimeout && typeof window.cancelIdleCallback === 'function') window.cancelIdleCallback(circleDetailPrefetchIdleId)
    else clearTimeout(circleDetailPrefetchIdleId)
    circleDetailPrefetchIdleId = null
    circleDetailPrefetchIdleIsTimeout = false
  }
  if (circleDetailAbortController) {
    circleDetailAbortController.abort()
    circleDetailAbortController = null
  }
  if (circleWorksFetchTimer) {
    clearTimeout(circleWorksFetchTimer)
    circleWorksFetchTimer = null
  }
  if (circleSearchFetchTimer) {
    clearTimeout(circleSearchFetchTimer)
    circleSearchFetchTimer = null
  }
  if (heroWorkSearchFetchTimer) {
    clearTimeout(heroWorkSearchFetchTimer)
    heroWorkSearchFetchTimer = null
  }
  if (heroWorkSearchAbortController) {
    heroWorkSearchAbortController.abort()
    heroWorkSearchAbortController = null
  }
  if (locatedWorkTimer) {
    clearTimeout(locatedWorkTimer)
    locatedWorkTimer = null
  }
  stopIndexJobPolling()
  stopRefreshJobPolling()
  stopBonusProbeJobPolling()
  stopBonusProbeJobAutoHide()
  stopRefreshJobAutoHide()
  stopDownloadWorkbenchPolling()
  stopUploadWorkbenchPolling()
})

function scheduleCircleWorksRefresh(delay = 0) {
  if (!activeCircleId.value) return
  if (suppressCircleWorksRefresh) return
  if (circleWorksFetchTimer) {
    clearTimeout(circleWorksFetchTimer)
    circleWorksFetchTimer = null
  }
  circleWorksFetchTimer = setTimeout(() => {
    circleWorksFetchTimer = null
    refreshActiveCircleWorks({ showLoading: false })
  }, Math.max(0, Number(delay || 0)))
}

watch(activeTab, (tab) => {
  selectedCanonicals.value = new Set()
  selectedDownloadableCanonicals.value = new Set()
  selectedRequestedRjcodes.value = {}
  if (tab === 'missing') missingPage.value = 1
  if (tab === 'owned') ownedPage.value = 1
  if (tab === 'compare') comparePage.value = 1
  scheduleCircleWorksRefresh()
})

watch([missingPage, ownedPage, comparePage, worksPageSize, comparePageSize], () => {
  scheduleCircleWorksRefresh()
})

watch([statusFilterModel, () => filters.includeDlOnly], () => {
  if (suppressCircleWorksRefresh) return
  missingPage.value = 1
  ownedPage.value = 1
  comparePage.value = 1
  clearSelection()
  refreshActiveCircle()
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

watch(
  () => [bonusProbeJob.job_id, bonusProbeJob.status, bonusProbeJob.progress, bonusProbeJob.current_step, bonusProbeJob.elapsed_seconds].join(':'),
  () => {
    persistBonusProbeJobState()
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
      await refreshActiveCircle({ summaryOnly: false })
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
      await refreshActiveCircle({ summaryOnly: false })
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
    if (indexing.value) startIndexJobElapsedTick()
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
  stopIndexJobElapsedTick()
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

function persistBonusProbeJobState() {
  try {
    if (!bonusProbeJob.job_id) {
      localStorage.removeItem(CIRCLE_COMPLETION_BONUS_PROBE_JOB_KEY)
      return
    }
    localStorage.setItem(CIRCLE_COMPLETION_BONUS_PROBE_JOB_KEY, JSON.stringify({
      job_id: bonusProbeJob.job_id,
      status: bonusProbeJob.status,
      progress: bonusProbeJob.progress,
      current_step: bonusProbeJob.current_step,
      circle_id: bonusProbeJob.circle_id,
      circle_name: bonusProbeJob.circle_name,
      release_dates: Array.isArray(bonusProbeJob.release_dates) ? bonusProbeJob.release_dates : [],
      elapsed_seconds: bonusProbeJob.elapsed_seconds,
      error_message: bonusProbeJob.error_message,
      meta: bonusProbeJob.meta || {},
      visible: bonusProbeJob.visible,
    }))
  } catch (_) {}
}

function hydrateBonusProbeJobState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_BONUS_PROBE_JOB_KEY) || '{}')
    const status = String(raw.status || '').trim()
    if (isCancelledJobState(raw) || ['completed', 'failed', 'cancelled'].includes(status)) {
      clearBonusProbeJobState()
      return
    }
    bonusProbeJob.visible = Boolean(raw.job_id && raw.visible !== false)
    bonusProbeJob.job_id = String(raw.job_id || '').trim()
    bonusProbeJob.status = status
    bonusProbeJob.progress = Number(raw.progress || 0)
    bonusProbeJob.current_step = String(raw.current_step || '').trim()
    bonusProbeJob.circle_id = String(raw.circle_id || '').trim()
    bonusProbeJob.circle_name = String(raw.circle_name || '').trim()
    bonusProbeJob.release_dates = Array.isArray(raw.release_dates) ? raw.release_dates.filter(Boolean) : []
    bonusProbeJob.elapsed_seconds = Number(raw.elapsed_seconds || 0)
    bonusProbeJob.error_message = String(raw.error_message || '').trim()
    bonusProbeJob.meta = raw.meta && typeof raw.meta === 'object' ? raw.meta : {}
    bonusProbeRunning.value = Boolean(bonusProbeJob.job_id && ['pending', 'processing'].includes(status))
  } catch (_) {
    clearBonusProbeJobState()
  }
}

function clearBonusProbeJobState() {
  bonusProbeJob.visible = false
  bonusProbeJob.job_id = ''
  bonusProbeJob.status = ''
  bonusProbeJob.progress = 0
  bonusProbeJob.current_step = ''
  bonusProbeJob.circle_id = ''
  bonusProbeJob.circle_name = ''
  bonusProbeJob.release_dates = []
  bonusProbeJob.elapsed_seconds = 0
  bonusProbeJob.error_message = ''
  bonusProbeJob.meta = {}
  bonusProbeJob.result = {}
  bonusProbeJob.progress_log = []
  bonusProbeRunning.value = false
  stopBonusProbeJobPolling()
  stopBonusProbeJobAutoHide()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_BONUS_PROBE_JOB_KEY)
  } catch (_) {}
}

function stopBonusProbeJobAutoHide() {
  if (bonusProbeJobAutoHideTimer) {
    window.clearTimeout(bonusProbeJobAutoHideTimer)
    bonusProbeJobAutoHideTimer = null
  }
}

function scheduleBonusProbeJobAutoHide(delayMs = 10000) {
  stopBonusProbeJobAutoHide()
  bonusProbeJobAutoHideTimer = window.setTimeout(() => {
    clearBonusProbeJobState()
  }, Math.max(0, Number(delayMs || 0)))
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

function stopBonusProbeJobPolling() {
  if (bonusProbeJobTimer) {
    window.clearTimeout(bonusProbeJobTimer)
    bonusProbeJobTimer = null
  }
}

function stopIndexJobPolling() {
  if (indexJobTimer) {
    window.clearTimeout(indexJobTimer)
    indexJobTimer = null
  }
}

function stopIndexJobElapsedTick() {
  if (indexJobElapsedTimer) {
    window.clearInterval(indexJobElapsedTimer)
    indexJobElapsedTimer = null
  }
}

function startIndexJobElapsedTick() {
  stopIndexJobElapsedTick()
  if (!indexJob.job_id || !['pending', 'processing'].includes(String(indexJob.status || ''))) return
  indexJobElapsedTimer = window.setInterval(() => {
    if (!indexJob.job_id || !['pending', 'processing'].includes(String(indexJob.status || ''))) {
      stopIndexJobElapsedTick()
      return
    }
    indexJob.elapsed_seconds = Number(indexJob.elapsed_seconds || 0) + 1
    persistIndexJobState()
  }, 1000)
}

function applyIndexJob(payload = {}) {
  indexJob.visible = true
  indexJob.job_id = payload.job_id || ''
  indexJob.status = payload.status || ''
  indexJob.progress = Number(payload.progress || 0)
  indexJob.current_step = payload.current_step || ''
  indexJob.circle_query = payload.circle_query || ''
  const remoteElapsed = Number(payload.elapsed_seconds || 0)
  indexJob.elapsed_seconds = Math.max(Number(indexJob.elapsed_seconds || 0), remoteElapsed)
  indexJob.error_message = payload.error_message || ''
  indexJob.meta = payload.meta || {}
  if (['pending', 'processing'].includes(String(indexJob.status || ''))) {
    indexing.value = true
    startIndexJobElapsedTick()
  } else {
    stopIndexJobElapsedTick()
  }
  persistIndexJobState()
}

function isJobRealtimeFresh(lastAt) {
  return realtimeEvents.connected.value
    && Number(lastAt || 0) > 0
    && Date.now() - Number(lastAt || 0) < JOB_SSE_STALE_MS
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

function applyBonusProbeJob(payload = {}) {
  bonusProbeJob.visible = true
  bonusProbeJob._retryCount = 0
  bonusProbeJob.job_id = payload.job_id || bonusProbeJob.job_id || ''
  bonusProbeJob.status = payload.status || ''
  bonusProbeJob.progress = Number(payload.progress || 0)
  bonusProbeJob.current_step = payload.current_step || ''
  bonusProbeJob.circle_id = payload.circle_id || payload.result?.circle_id || bonusProbeJob.circle_id || ''
  bonusProbeJob.circle_name = payload.circle_name || payload.result?.circle_name || bonusProbeJob.circle_name || detail.circle_name || ''
  bonusProbeJob.release_dates = Array.isArray(payload.release_dates)
    ? payload.release_dates.filter(Boolean)
    : (Array.isArray(payload.meta?.release_dates) ? payload.meta.release_dates.filter(Boolean) : bonusProbeJob.release_dates)
  bonusProbeJob.elapsed_seconds = Number(payload.elapsed_seconds || 0)
  bonusProbeJob.error_message = payload.error_message || ''
  bonusProbeJob.meta = mergeBonusProbeMeta(bonusProbeJob.meta, payload.meta || {})
  bonusProbeJob.result = payload.result || {}
  bonusProbeJob.progress_log = Array.isArray(payload.progress_log) ? payload.progress_log : []
  bonusProbeRunning.value = ['pending', 'processing'].includes(String(bonusProbeJob.status || ''))
  persistBonusProbeJobState()
}

function patchIndexJobFromTaskEvent(payload = {}) {
  indexJobLastRealtimeAt = Date.now()
  indexJob.visible = true
  indexJob.job_id = String(payload.engine_task_id || payload.entity_id || indexJob.job_id || '')
  indexJob.status = payload.status || indexJob.status || ''
  indexJob.progress = Number(payload.progress ?? indexJob.progress ?? 0)
  indexJob.current_step = payload.current_step || indexJob.current_step || ''
  if (['pending', 'processing'].includes(String(indexJob.status || ''))) {
    indexing.value = true
    startIndexJobElapsedTick()
  } else if (isTerminalTaskStatus(indexJob.status)) {
    stopIndexJobElapsedTick()
  }
  persistIndexJobState()
}

function patchRefreshJobFromTaskEvent(payload = {}) {
  refreshJobLastRealtimeAt = Date.now()
  refreshJob.visible = true
  refreshJob.job_id = String(payload.engine_task_id || payload.entity_id || refreshJob.job_id || '')
  refreshJob.status = payload.status || refreshJob.status || ''
  refreshJob.progress = Number(payload.progress ?? refreshJob.progress ?? 0)
  refreshJob.current_step = payload.current_step || refreshJob.current_step || ''
  if (refreshJob.status !== 'completed') {
    stopRefreshJobAutoHide()
    refreshJob.auto_hide_at = ''
  }
  persistRefreshJobState()
}

function patchBonusProbeJobFromTaskEvent(payload = {}) {
  bonusProbeJobLastRealtimeAt = Date.now()
  bonusProbeJob.visible = true
  bonusProbeJob.job_id = String(payload.engine_task_id || payload.entity_id || bonusProbeJob.job_id || '')
  bonusProbeJob.status = payload.status || bonusProbeJob.status || ''
  bonusProbeJob.progress = Number(payload.progress ?? bonusProbeJob.progress ?? 0)
  bonusProbeJob.current_step = payload.current_step || bonusProbeJob.current_step || ''
  bonusProbeJob.meta = mergeBonusProbeMeta(bonusProbeJob.meta, payload.bonus_probe_meta || payload.meta || {})
  bonusProbeRunning.value = ['pending', 'processing'].includes(String(bonusProbeJob.status || ''))
  persistBonusProbeJobState()
}

function isTerminalTaskStatus(status) {
  return ['completed', 'failed', 'cancelled', 'canceled'].includes(String(status || '').trim().toLowerCase())
}

function handleCircleTaskRealtimeEvent(event) {
  const payloads = normalizeTaskCenterRealtimePayloads(event?.detail || {})
    .filter(payload => payload?.type === 'task_center_changed')
  for (const payload of payloads) {
    handleCircleTaskPayload(payload)
  }
}

function handleCircleTaskPayload(payload) {
  if (payload?.type !== 'task_center_changed') return
  const taskId = String(payload.engine_task_id || payload.entity_id || '').trim()
  if (!taskId) return
  const domain = String(payload.domain || '').trim()
  if (domain && domain !== 'circle_completion') return

  if (indexJob.job_id && taskId === indexJob.job_id) {
    patchIndexJobFromTaskEvent(payload)
    if (isTerminalTaskStatus(payload.status)) {
      const key = `index:${taskId}:${payload.status}`
      if (!handledCircleTerminalTasks.has(key)) {
        handledCircleTerminalTasks.add(key)
        stopIndexJobPolling()
        pollIndexJob(taskId)
      }
    }
    return
  }

  if (refreshJob.job_id && taskId === refreshJob.job_id) {
    patchRefreshJobFromTaskEvent(payload)
    if (isTerminalTaskStatus(payload.status)) {
      const key = `refresh:${taskId}:${payload.status}`
      if (!handledCircleTerminalTasks.has(key)) {
        handledCircleTerminalTasks.add(key)
        stopRefreshJobPolling()
        pollRefreshJob(taskId, { silentFinish: true })
      }
    }
    return
  }

  if (bonusProbeJob.job_id && taskId === bonusProbeJob.job_id) {
    patchBonusProbeJobFromTaskEvent(payload)
    if (isTerminalTaskStatus(payload.status)) {
      const key = `bonus:${taskId}:${payload.status}`
      if (!handledCircleTerminalTasks.has(key)) {
        handledCircleTerminalTasks.add(key)
        stopBonusProbeJobPolling()
        pollBonusProbeJob(taskId, { silentFinish: true })
      }
    }
  }
}

function scheduleIndexJobFallbackPoll(jobId) {
  stopIndexJobPolling()
  indexJobTimer = window.setTimeout(() => {
    indexJobTimer = null
    if (!indexJob.job_id || String(indexJob.job_id) !== String(jobId)) return
    if (isJobRealtimeFresh(indexJobLastRealtimeAt)) {
      scheduleIndexJobFallbackPoll(jobId)
      return
    }
    pollIndexJob(jobId)
  }, JOB_FALLBACK_POLL_INTERVAL_MS)
}

function scheduleRefreshJobFallbackPoll(jobId) {
  stopRefreshJobPolling()
  refreshJobTimer = window.setTimeout(() => {
    refreshJobTimer = null
    if (!refreshJob.job_id || String(refreshJob.job_id) !== String(jobId)) return
    if (isJobRealtimeFresh(refreshJobLastRealtimeAt)) {
      scheduleRefreshJobFallbackPoll(jobId)
      return
    }
    pollRefreshJob(jobId, { silentFinish: true })
  }, JOB_FALLBACK_POLL_INTERVAL_MS)
}

function scheduleBonusProbeJobFallbackPoll(jobId) {
  stopBonusProbeJobPolling()
  bonusProbeJobTimer = window.setTimeout(() => {
    bonusProbeJobTimer = null
    if (!bonusProbeJob.job_id || String(bonusProbeJob.job_id) !== String(jobId)) return
    if (isJobRealtimeFresh(bonusProbeJobLastRealtimeAt)) {
      scheduleBonusProbeJobFallbackPoll(jobId)
      return
    }
    pollBonusProbeJob(jobId, { silentFinish: true })
  }, JOB_FALLBACK_POLL_INTERVAL_MS)
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
      stopIndexJobElapsedTick()
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        clearIndexJobState()
        ElMessage.info('社团索引已取消')
      } else {
        persistIndexJobState()
        ElMessage.error(result.error_message || '社团索引失败')
      }
      return
    }
    scheduleIndexJobFallbackPoll(jobId)
  } catch (error) {
    // 404 说明任务已不存在（后端重启），直接清除进度卡
    if (error?.response?.status === 404) {
      clearIndexJobState()
      return
    }
    indexing.value = Boolean(indexJob.job_id)
    indexJob.visible = Boolean(indexJob.job_id)
    if (!indexJob.status) indexJob.status = 'processing'
    if (!indexJob.current_step) indexJob.current_step = '等待服务端进度恢复'
    startIndexJobElapsedTick()
    persistIndexJobState()
    scheduleIndexJobFallbackPoll(jobId)
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
      await Promise.all([refreshActiveCircle({ summaryOnly: false }), loadRecentCircles()])
      const changedCodes = (Array.isArray(result.result?.items) ? result.result.items : [])
        .filter(item => item?.changed)
        .map(item => item.canonical_rjcode)
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
    scheduleRefreshJobFallbackPoll(jobId)
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
    scheduleRefreshJobFallbackPoll(jobId)
  }
}

async function pollBonusProbeJob(jobId, options = {}) {
  stopBonusProbeJobPolling()
  const silentFinish = Boolean(options?.silentFinish)
  try {
    const result = await circleCompletionApi.getBonusProbeJobStatus(jobId)
    applyBonusProbeJob(result)
    if (result.status === 'completed') {
      bonusProbeRunning.value = false
      await Promise.all([refreshActiveCircle({ summaryOnly: false }), loadRecentCircles()])
      const summary = result.summary || result.result || result.meta || {}
      const hitCount = Number(summary.hit_count || result.meta?.hit_count || 0)
      const insertedCount = Number(summary.inserted_count || result.meta?.inserted_count || 0)
      const incompleteCount = Number(summary.incomplete_count || result.meta?.incomplete_count || 0)
      bonusProbeJob.current_step = incompleteCount
        ? `特典探测完成，命中 ${hitCount} 个，写入 ${insertedCount} 个，${incompleteCount} 个发售日未产出无特典结论`
        : `特典探测完成，命中 ${hitCount} 个，写入 ${insertedCount} 个`
      bonusProbeJob.status = 'completed'
      bonusProbeJob.progress = 100
      bonusProbeJob.error_message = ''
      const probeCount = Number(summary.probe_count || result.meta?.probe_count || 0)
      bonusProbeJob.meta = mergeBonusProbeMeta(bonusProbeJob.meta, {
        probe_count: probeCount,
        checked_probe_count: Number(summary.checked_probe_count || result.meta?.checked_probe_count || probeCount),
        hit_count: hitCount,
        inserted_count: insertedCount,
        incomplete_count: incompleteCount,
      })
      persistBonusProbeJobState()
      scheduleBonusProbeJobAutoHide(10000)
      if (!silentFinish) {
        if (incompleteCount) {
          ElMessage.warning(`特典补全完成，但 ${incompleteCount} 个发售日超出 RJ 预算，未产出无特典结论`)
        } else {
          ElMessage.success(`特典补全完成，命中 ${hitCount} 个，写入 ${insertedCount} 个`)
        }
      }
      return
    }
    if (result.status === 'failed') {
      bonusProbeRunning.value = false
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        ElMessage.info('特典探测已取消')
      } else if (!silentFinish) {
        ElMessage.error(result.error_message || '特典探测失败')
      }
      clearBonusProbeJobState()
      return
    }
    scheduleBonusProbeJobFallbackPoll(jobId)
  } catch (error) {
    bonusProbeRunning.value = false
    if (error?.response?.status === 404) {
      clearBonusProbeJobState()
      return
    }
    bonusProbeJob._retryCount = (bonusProbeJob._retryCount || 0) + 1
    if (bonusProbeJob._retryCount >= 10) {
      clearBonusProbeJobState()
      return
    }
    if (!silentFinish) {
      ElMessage.error(error.response?.data?.detail || '查询特典探测进度失败')
    }
    scheduleBonusProbeJobFallbackPoll(jobId)
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

async function cancelBonusProbeJob() {
  if (!bonusProbeJob.job_id || cancellingBonusProbeJob.value) return
  cancellingBonusProbeJob.value = true
  try {
    await api.task.cancel(bonusProbeJob.job_id)
    clearBonusProbeJobState()
    ElMessage.success('已发送取消请求')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消特典探测失败')
  } finally {
    cancellingBonusProbeJob.value = false
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

function scheduleHeroWorkSearch() {
  if (heroWorkSearchFetchTimer) {
    clearTimeout(heroWorkSearchFetchTimer)
    heroWorkSearchFetchTimer = null
  }
  const keyword = String(heroWorkSearchQuery.value || '').trim()
  if (!keyword) {
    if (heroWorkSearchAbortController) {
      heroWorkSearchAbortController.abort()
      heroWorkSearchAbortController = null
    }
    heroWorkSearchResults.value = []
    heroWorkSearchLoading.value = false
    heroWorkSearchSearched.value = false
    return
  }
  heroWorkSearchFetchTimer = setTimeout(() => {
    heroWorkSearchFetchTimer = null
    searchHeroWork(keyword)
  }, 240)
}

async function searchHeroWork(keyword) {
  const query = String(keyword || heroWorkSearchQuery.value || '').trim()
  if (!query) return
  const requestSeq = ++heroWorkSearchRequestSeq.value
  if (heroWorkSearchAbortController) {
    heroWorkSearchAbortController.abort()
  }
  heroWorkSearchAbortController = new AbortController()
  heroWorkSearchLoading.value = true
  try {
    const result = await circleCompletionApi.searchWorks(query, 12, {
      signal: heroWorkSearchAbortController.signal
    })
    if (requestSeq !== heroWorkSearchRequestSeq.value) return
    heroWorkSearchResults.value = Array.isArray(result.items) ? result.items : []
    heroWorkSearchSearched.value = true
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    heroWorkSearchResults.value = []
    heroWorkSearchSearched.value = true
    ElMessage.error(error.response?.data?.detail || '搜索 RJ 失败')
  } finally {
    if (requestSeq === heroWorkSearchRequestSeq.value) {
      heroWorkSearchLoading.value = false
      heroWorkSearchAbortController = null
    }
  }
}

function clearHeroWorkSearch() {
  heroWorkSearchQuery.value = ''
}

async function jumpToFirstHeroWorkSearchResult() {
  const keyword = String(heroWorkSearchQuery.value || '').trim()
  if (!keyword) return
  if (!heroWorkSearchResults.value.length) {
    await searchHeroWork(keyword)
  }
  const first = heroWorkSearchResults.value[0]
  if (first) await jumpToHeroWorkSearchResult(first)
}

function rjcodeMatchesWork(item, rjcode) {
  const target = normalizeRjcode(rjcode)
  if (!target) return false
  const candidates = [
    item?.canonical_rjcode,
    item?.display_rjcode,
    item?.server_match_primary_rjcode,
    item?.asmr_available_rjcode,
    item?.download_plan?.rjcode,
    item?.owned_variant?.rjcode,
    item?.preferred_variant?.rjcode,
    ...(Array.isArray(item?.linked_rjcodes) ? item.linked_rjcodes : []),
  ]
  if (candidates.some(candidate => normalizeRjcode(candidate) === target)) return true
  return (Array.isArray(item?.bonus_works) ? item.bonus_works : [])
    .some(bonus => rjcodeMatchesWork(bonus, target))
}

async function locateWorkPageInCircle(circleId, item, targetTab, rjcode) {
  const pageSize = Number(worksPageSize.value || 10)
  const result = await circleCompletionApi.getCircleWorkLocation(circleId, {
    ...buildCircleWorksQuery({ includePage: false, tab: targetTab }),
    rjcode,
    tab: targetTab,
    pageSize,
    includeDlOnly: filters.includeDlOnly,
    statusFilters: [],
    ownedFilter: 'all',
    compareFilter: 'all',
    search: '',
    sort: getCircleWorksSort()
  })
  return {
    page: Math.max(1, Number(result?.page || 1)),
    canonical: normalizeRjcode(result?.canonical_rjcode || item?.canonical_rjcode || rjcode),
    matched: Boolean(result?.matched),
  }
}

async function ensureHeroSearchCircleVisible(item, options = {}) {
  const circleId = String(item?.circle_id || '').trim()
  if (!circleId) return
  const syncActive = options.syncActive !== false
  const exists = circleList.value.some(circle => String(circle?.circle_id || '').trim() === circleId)
  if (exists) return
  try {
    const result = await circleCompletionApi.searchCircles(item.circle_name || circleId, 24)
    const circles = Array.isArray(result.circles) ? result.circles : []
    if (circles.length) {
      const hasTarget = circles.some(circle => String(circle?.circle_id || '').trim() === circleId)
      circleList.value = hasTarget ? circles : [buildHeroSearchCircleListItem(item), ...circles]
      if (syncActive) await syncActiveCircleWithList({ preserveActiveWhenEmpty: true })
      return
    }
  } catch (_) {}
  circleList.value = [buildHeroSearchCircleListItem(item), ...circleList.value]
}

function buildHeroSearchCircleListItem(item) {
  const circleId = String(item?.circle_id || '').trim()
  return {
    circle_id: circleId,
    circle_name: item?.circle_name || circleId,
    total_works: 0,
    dl_works: 0,
    server_owned: 0,
    missing: 0,
    last_indexed_at: item?.last_indexed_at || '',
  }
}

async function jumpToHeroWorkSearchResult(item) {
  const circleId = String(item?.circle_id || '').trim()
  const rjcode = normalizeRjcode(item?.display_rjcode || item?.canonical_rjcode || heroWorkSearchQuery.value)
  if (!circleId || !rjcode) return
  heroWorkSearchQuery.value = rjcode
  heroWorkSearchResults.value = []
  heroWorkSearchSearched.value = false
  let targetTab = item?.owned ? 'owned' : 'missing'
  suppressCircleWorksRefresh = true
  try {
    clearSelection()
    flashedWorkCodes.value = new Set()
    locatedWorkCodes.value = new Set()
    ownedWorksSearchQuery.value = ''
    compareSearchQuery.value = ''
    statusFilters.value = []
    ownedWorksFilterType.value = 'all'
    filters.includeDlOnly = true
    compareSourceFilter.value = 'all'
    activeTab.value = targetTab
    await ensureHeroSearchCircleVisible(item, { syncActive: false })
    await selectCircle(circleId, { deferLoad: true })
    let location = await locateWorkPageInCircle(circleId, item, targetTab, rjcode)
    if (!location.matched) {
      const fallbackTab = targetTab === 'owned' ? 'missing' : 'owned'
      const fallbackLocation = await locateWorkPageInCircle(circleId, item, fallbackTab, rjcode)
      if (fallbackLocation.matched) {
        targetTab = fallbackTab
        activeTab.value = targetTab
        location = fallbackLocation
      }
    }
    if (targetTab === 'owned') {
      ownedPage.value = location.page
    } else {
      missingPage.value = location.page
    }
    if (circleWorksFetchTimer) {
      clearTimeout(circleWorksFetchTimer)
      circleWorksFetchTimer = null
    }
    await refreshActiveCircle({ preferCache: false })
    const canonical = location.canonical || normalizeRjcode(item?.canonical_rjcode || rjcode)
    const visibleMatch = (detail.works || []).some(work => (
      String(work?.canonical_rjcode || '').trim() === canonical || rjcodeMatchesWork(work, rjcode)
    ))
    const targetLabel = targetTab === 'owned' ? '已满足作品' : '缺失作品'
    if (visibleMatch) {
      flashLocatedWork(canonical)
      ElMessage.success('已找到')
    } else {
      ElMessage.warning('未找到')
    }
  } finally {
    suppressCircleWorksRefresh = false
  }
}

function scheduleCircleDetailPrefetch() {
  if (circleDetailLoading.value || circleDetailAbortController) return
  if (circleDetailPrefetchTimer) {
    window.clearTimeout(circleDetailPrefetchTimer)
    circleDetailPrefetchTimer = null
  }
  if (circleDetailPrefetchIdleId !== null) {
    if (!circleDetailPrefetchIdleIsTimeout && typeof window.cancelIdleCallback === 'function') window.cancelIdleCallback(circleDetailPrefetchIdleId)
    else window.clearTimeout(circleDetailPrefetchIdleId)
    circleDetailPrefetchIdleId = null
    circleDetailPrefetchIdleIsTimeout = false
  }
  circleDetailPrefetchTimer = window.setTimeout(() => {
    circleDetailPrefetchTimer = null
    const run = () => {
      circleDetailPrefetchIdleId = null
      circleDetailPrefetchIdleIsTimeout = false
      if (circleDetailLoading.value || circleDetailAbortController) return
      prefetchNeighborCircleDetails().catch(() => {})
    }
    if (typeof window.requestIdleCallback === 'function') {
      circleDetailPrefetchIdleIsTimeout = false
      circleDetailPrefetchIdleId = window.requestIdleCallback(run, { timeout: 1200 })
    } else {
      circleDetailPrefetchIdleIsTimeout = true
      circleDetailPrefetchIdleId = window.setTimeout(run, 300)
    }
  }, 450)
}

async function prefetchNeighborCircleDetails() {
  if (circleDetailPrefetchRunning || circleDetailLoading.value || circleDetailAbortController) return
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
      const worksQuery = {
        tab: 'missing',
        page: 1,
        pageSize: worksPageSize.value,
        includeDlOnly: filters.includeDlOnly,
        statusFilters: [],
        sort: getCircleWorksSort(),
        viewMode: viewMode.value === 'card' ? 'card' : 'list',
      }
      const works = await circleCompletionApi.getCircleWorks(circleId, worksQuery)
      if (circleDetailLoading.value || circleDetailAbortController) break
      setCachedCircleWorksPage(circleId, worksQuery, works)
      setCachedCircleDetail(circleId, buildCachedCircleDetailPayload(works, works))
    }
  } finally {
    circleDetailPrefetchRunning = false
  }
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

async function openIndexPrompt() {
  try {
    const value = await showSystemPrompt({
      title: '建立 / 刷新社团索引',
      description: '输入社团名，一行一个。单个社团和批量社团都在这里提交。',
      badge: '社团补全',
      mode: 'prompt',
      inputType: 'textarea',
      width: 680,
      closeOnClickModal: false,
      placeholder: '例如：\nリリムワークス/兎月りりむ。\n耳かき屋\nしろくまだんご',
      confirmText: '开始建立 / 刷新',
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
  const targetQuery = String(detail.circle_name || '').trim()
  await startIndexCircleJob({
    circleQuery: targetQuery,
    onlyNewWorks: true
  })
}

async function startBonusProbeForCircle(circleId, options = {}) {
  const normalizedCircleId = String(circleId || '').trim()
  if (!normalizedCircleId) {
    ElMessage.warning('当前还没有选中社团')
    return null
  }
  const releaseDates = Array.isArray(options.releaseDates)
    ? options.releaseDates.map(normalizeReleaseDateForBonusProbe).filter(Boolean)
    : []
  const result = await circleCompletionApi.startBonusProbe({
    circle_id: normalizedCircleId,
    release_dates: releaseDates,
    selected_rjcodes_by_date: options.selectedRjcodesByDate || {},
    mode: 'deep',
    gap_limit: 500,
  })
  return {
    ...result,
    circle_name: result.circle_name || options.circleName || '',
    current_step: result.current_step || options.currentStep || '正在探测 DLsite 隐藏特典',
  }
}

async function startBonusProbeForActiveCircle() {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  if (isBonusProbeJobActive.value) {
    ElMessage.warning('已有特典探测任务在跑')
    return
  }
  if (indexing.value || isRefreshJobActive.value) {
    ElMessage.warning('社团索引或批量刷新正在运行')
    return
  }
  bonusProbeRunning.value = true
  try {
    const result = await startBonusProbeForCircle(circleId, {
      circleName: detail.circle_name || '',
      currentStep: '正在探测 DLsite 隐藏特典',
    })
    if (result?.already_completed) {
      bonusProbeRunning.value = false
      ElMessage.info('当前社团的发售日已完成特典探测，无需重复查找')
      return
    }
    applyBonusProbeJob({
      ...result,
    })
    if (result.duplicate) {
      ElMessage.info('已有同范围特典探测任务，已恢复进度')
    }
    if (result.job_id) scheduleBonusProbeJobFallbackPoll(result.job_id)
  } catch (error) {
    bonusProbeRunning.value = false
    clearBonusProbeJobState()
    ElMessage.error(error.response?.data?.detail || '启动特典补全失败')
  }
}

async function getSelectedBonusProbeDates() {
  const selectedCodes = selectedActiveCanonicalRJCodes.value
    .map(code => String(code || '').trim())
    .filter(Boolean)
  if (!selectedCodes.length) {
    return { dates: [], selectedRjcodesByDate: {}, selectedCount: 0, skippedBonusCount: 0, skippedHasBonusCount: 0, skippedNoBonusCount: 0, skippedCompletedDateCount: 0, missingDateCount: 0 }
  }

  const releaseDatesByCode = {}
  const selectedRjcodesByDate = {}
  const bonusCodes = new Set()
  const hasBonusCodes = new Set()
  const noBonusCodes = new Set()
  const completedDates = new Set()
  for (const code of selectedCodes) {
    const item = activeSelectableWorksByCanonical.value.get(code)
    if (!item) continue
    if (isBonusDisplayWork(item)) bonusCodes.add(code)
    if (!isBonusDisplayWork(item) && hasAttachedBonusWorks(item)) hasBonusCodes.add(code)
    const releaseDate = getWorkBonusProbeDate(item)
    if (releaseDate) releaseDatesByCode[code] = releaseDate
  }

  try {
    const result = await circleCompletionApi.getCircleWorkCodes(activeCircleId.value, buildCircleWorksQuery({ includePage: false }))
    const releaseMap = result.release_dates_by_rjcode || {}
    for (const code of selectedCodes) {
      const normalizedDate = normalizeReleaseDateForBonusProbe(releaseMap[code])
      if (normalizedDate) releaseDatesByCode[code] = normalizedDate
    }
    for (const code of result.bonus_rjcodes || []) {
      const normalizedCode = String(code || '').trim()
      if (normalizedCode) bonusCodes.add(normalizedCode)
    }
    for (const code of result.has_bonus_rjcodes || []) {
      const normalizedCode = String(code || '').trim()
      if (normalizedCode) hasBonusCodes.add(normalizedCode)
    }
    for (const code of result.no_bonus_rjcodes || []) {
      const normalizedCode = String(code || '').trim()
      if (normalizedCode) noBonusCodes.add(normalizedCode)
    }
    for (const date of result.completed_bonus_probe_dates || []) {
      const normalizedDate = normalizeReleaseDateForBonusProbe(date)
      if (normalizedDate) completedDates.add(normalizedDate)
    }
  } catch (_) {}

  const dates = []
  let missingDateCount = 0
  let skippedBonusCount = 0
  let skippedHasBonusCount = 0
  let skippedNoBonusCount = 0
  let skippedCompletedDateCount = 0
  for (const code of selectedCodes) {
    if (bonusCodes.has(code)) {
      skippedBonusCount += 1
      continue
    }
    if (hasBonusCodes.has(code)) {
      skippedHasBonusCount += 1
      continue
    }
    const releaseDate = normalizeReleaseDateForBonusProbe(releaseDatesByCode[code])
    if (!releaseDate) {
      missingDateCount += 1
      continue
    }
    if (noBonusCodes.has(code)) skippedNoBonusCount += 1
    if (completedDates.has(releaseDate)) skippedCompletedDateCount += 1
    if (!dates.includes(releaseDate)) dates.push(releaseDate)
    if (!Array.isArray(selectedRjcodesByDate[releaseDate])) selectedRjcodesByDate[releaseDate] = []
    if (!selectedRjcodesByDate[releaseDate].includes(code)) selectedRjcodesByDate[releaseDate].push(code)
  }

  return {
    dates,
    selectedRjcodesByDate,
    selectedCount: selectedCodes.length,
    skippedBonusCount,
    skippedHasBonusCount,
    skippedNoBonusCount,
    skippedCompletedDateCount,
    missingDateCount,
  }
}

async function startBonusProbeForSelectedWorks() {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  if (!selectedActiveCanonicalRJCodes.value.length) {
    ElMessage.warning('先选择要查特典的作品')
    return
  }
  if (isBonusProbeJobActive.value) {
    ElMessage.warning('已有特典探测任务在跑')
    return
  }
  if (indexing.value || isRefreshJobActive.value) {
    ElMessage.warning('社团索引或批量刷新正在运行')
    return
  }
  bonusProbeRunning.value = true
  try {
    const {
      dates,
      selectedRjcodesByDate,
      selectedCount,
      skippedBonusCount,
      skippedHasBonusCount,
      skippedNoBonusCount,
      skippedCompletedDateCount,
      missingDateCount,
    } = await getSelectedBonusProbeDates()
    if (!dates.length) {
      bonusProbeRunning.value = false
      const skippedText = [
        skippedBonusCount ? `特典本体 ${skippedBonusCount}` : '',
        skippedHasBonusCount ? `已有特典 ${skippedHasBonusCount}` : '',
        skippedNoBonusCount ? `已确认无特典 ${skippedNoBonusCount}` : '',
        skippedCompletedDateCount ? `已查日期 ${skippedCompletedDateCount}` : '',
        missingDateCount ? `无明确日期 ${missingDateCount}` : '',
      ].filter(Boolean).join('，')
      ElMessage.warning(skippedText ? `选中作品无需重复查特典（${skippedText}）` : '选中作品里没有可用于查特典的原作发售日')
      return
    }
    const result = await startBonusProbeForCircle(circleId, {
      circleName: detail.circle_name || '',
      releaseDates: dates,
      selectedRjcodesByDate,
      currentStep: `正在探测选中作品的 ${dates.length} 个发售日`,
    })
    if (result?.already_completed) {
      bonusProbeRunning.value = false
      ElMessage.info('选中作品的发售日已完成特典探测，无需重复查找')
      return
    }
    applyBonusProbeJob(result)
    if (result.job_id) scheduleBonusProbeJobFallbackPoll(result.job_id)
    const skippedText = [
      skippedBonusCount ? `跳过特典本体 ${skippedBonusCount}` : '',
      skippedHasBonusCount ? `已有特典 ${skippedHasBonusCount}` : '',
      skippedNoBonusCount ? `已确认无特典 ${skippedNoBonusCount}` : '',
      skippedCompletedDateCount ? `已查日期 ${skippedCompletedDateCount}` : '',
      missingDateCount ? `无明确日期 ${missingDateCount}` : '',
    ].filter(Boolean).join('，')
    ElMessage.success(`已按 ${selectedCount} 个选中作品提交 ${dates.length} 个发售日特典查找${skippedText ? `（${skippedText}）` : ''}`)
  } catch (error) {
    bonusProbeRunning.value = false
    clearBonusProbeJobState()
    ElMessage.error(error.response?.data?.detail || '启动选中作品特典查找失败')
  }
}

async function startBonusProbeFromToolbar() {
  if (selectedActiveCanonicalRJCodes.value.length > 0) {
    await startBonusProbeForSelectedWorks()
    return
  }
  await startBonusProbeForActiveCircle()
}

async function startBonusProbeForVisibleCircles() {
  if (batchBonusProbeRunning.value) return
  if (indexing.value || isRefreshJobActive.value) {
    ElMessage.warning('社团索引或批量刷新正在运行')
    return
  }
  if (isBonusProbeJobActive.value) {
    ElMessage.warning('已有特典探测任务在跑')
    return
  }

  const visibleCircles = (Array.isArray(displayCircleList.value) ? displayCircleList.value : [])
    .map(circle => ({
      circle_id: String(circle?.circle_id || '').trim(),
      circle_name: String(circle?.circle_name || '').trim(),
    }))
    .filter(circle => circle.circle_id)
  if (!visibleCircles.length) {
    ElMessage.warning('左侧当前没有可提交的社团')
    return
  }

  let targets = visibleCircles
  if (targets.length > 100) {
    try {
      await showSystemConfirm({
        title: '批量查找特典',
        message: `当前筛选出了 ${targets.length} 个社团，一次最多提交前 100 个。`,
        description: '这些任务会进入后台任务队列；当前页面只显示正在查看社团的进度，其他社团可在任务中心查看。',
        tone: 'warning',
        confirmText: '提交前 100 个',
      })
      targets = targets.slice(0, 100)
    } catch (_) {
      return
    }
  }

  batchBonusProbeRunning.value = true
  let submittedCount = 0
  let duplicateCount = 0
  let alreadyCompletedCount = 0
  let failedCount = 0
  let activeCircleApplied = false
  let firstErrorMessage = ''

  try {
    for (const circle of targets) {
      try {
        const result = await startBonusProbeForCircle(circle.circle_id, {
          circleName: circle.circle_name,
          currentStep: '正在探测 DLsite 隐藏特典',
        })
        if (result?.already_completed) {
          alreadyCompletedCount += 1
          continue
        }
        submittedCount += 1
        if (result?.duplicate) duplicateCount += 1
        if (!activeCircleApplied && String(circle.circle_id) === String(activeCircleId.value || detail.circle_id || '')) {
          applyBonusProbeJob(result)
          if (result.job_id) scheduleBonusProbeJobFallbackPoll(result.job_id)
          activeCircleApplied = true
        }
      } catch (error) {
        failedCount += 1
        if (!firstErrorMessage) {
          firstErrorMessage = error.response?.data?.detail || error.message || ''
        }
      }
    }

    if (!submittedCount && !alreadyCompletedCount) {
      ElMessage.error(firstErrorMessage || '批量特典任务提交失败')
      return
    }
    const suffix = [
      alreadyCompletedCount ? `已查跳过 ${alreadyCompletedCount}` : '',
      duplicateCount ? `复用 ${duplicateCount}` : '',
      failedCount ? `失败 ${failedCount}` : '',
    ].filter(Boolean).join('，')
    ElMessage.success(
      submittedCount > 0
        ? `已提交 ${submittedCount} 个社团特典任务${suffix ? `（${suffix}）` : ''}`
        : `当前批量社团都已完成特典探测${suffix ? `（${suffix}）` : ''}`
    )
  } finally {
    batchBonusProbeRunning.value = false
  }
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
    scheduleIndexJobFallbackPoll(result.job_id)
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

async function refreshCurrentCircleBonusOwnedState() {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  if (indexing.value || isBonusProbeJobActive.value) {
    ElMessage.warning('社团索引或特典补全正在运行')
    return
  }
  if (isRefreshJobActive.value) {
    ElMessage.warning('已有批量刷新任务在跑')
    return
  }

  refreshingCurrentCircleBonuses.value = true
  try {
    const result = await circleCompletionApi.getCircleBonusWorkCodes(circleId)
    const codes = [...new Set((result.canonical_rjcodes || [])
      .map(code => String(code || '').trim())
      .filter(Boolean))]
    if (!codes.length) {
      ElMessage.warning('当前社团没有可刷新的特典')
      return
    }
    ElMessage.info(`已找到 ${codes.length} 个特典，开始刷新本地拥有状态`)
    await refreshSelectedCircleIndex(codes)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '获取当前社团特典失败')
  } finally {
    refreshingCurrentCircleBonuses.value = false
  }
}

async function selectCircle(circleId, options = {}) {
  const targetCircleId = String(circleId || '').trim()
  if (!targetCircleId) return
  const deferLoad = Boolean(options.deferLoad)
  if (activeCircleId.value === targetCircleId && circleDetailLoaded.value && !circleDetailLoading.value) {
    return
  }

  activeCircleId.value = targetCircleId
  selectedCanonicals.value = new Set()
  selectedDownloadableCanonicals.value = new Set()
  selectedRequestedRjcodes.value = {}
  flashedWorkCodes.value = new Set()
  locatedWorkCodes.value = new Set()
  missingPage.value = 1
  ownedPage.value = 1
  comparePage.value = 1

  if (deferLoad) {
    applyCircleSummaryPlaceholder(targetCircleId)
    return
  }

  const cached = activeTab.value === 'missing' && !statusFilters.value.length ? getCachedCircleDetail(targetCircleId) : null
  if (cached) {
    applyCircleDetailPayload(cached)
    const cachedPage = cached.works_page || {}
    const cachedTotal = Number(cachedPage.total ?? cached.missing_count ?? 0)
    const cachedPageSize = Number(cachedPage.page_size ?? worksPageSize.value ?? 10)
    Object.assign(circleWorksPage, {
      tab: String(cachedPage.tab || 'missing'),
      total: cachedTotal,
      page: Number(cachedPage.page || 1),
      page_size: cachedPageSize,
      page_count: Number(cachedPage.page_count || Math.max(1, Math.ceil(cachedTotal / Math.max(1, cachedPageSize)))),
      loading: false
    })
    circleDetailLoading.value = false
    scheduleCircleDetailPrefetch()
    return
  }

  applyCircleSummaryPlaceholder(targetCircleId)
  await refreshActiveCircle({ preferCache: true })
}

async function refreshActiveCircle(options = {}) {
  if (!activeCircleId.value) return
  const { preferCache = false, summaryOnly = false } = options
  const requestCircleId = String(activeCircleId.value || '').trim()
  if (!requestCircleId) return

  if (preferCache && activeTab.value === 'missing' && !statusFilters.value.length) {
    const cached = getCachedCircleDetail(requestCircleId)
    if (cached) {
      applyCircleDetailPayload(cached)
      const cachedPage = cached.works_page || {}
      const cachedTotal = Number(cachedPage.total ?? cached.missing_count ?? 0)
      const cachedPageSize = Number(cachedPage.page_size ?? worksPageSize.value ?? 10)
      Object.assign(circleWorksPage, {
        tab: String(cachedPage.tab || 'missing'),
        total: cachedTotal,
        page: Number(cachedPage.page || 1),
        page_size: cachedPageSize,
        page_count: Number(cachedPage.page_count || Math.max(1, Math.ceil(cachedTotal / Math.max(1, cachedPageSize)))),
        loading: false
      })
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
  circleDetailLoading.value = !circleDetailLoaded.value
  circleWorksPage.loading = true
  try {
    if (summaryOnly) {
      const summary = await circleCompletionApi.getCircleSummary(requestCircleId, {
        includeDlOnly: filters.includeDlOnly,
        signal: circleDetailAbortController.signal
      })
      if (requestSeq !== circleDetailRequestSeq || activeCircleId.value !== requestCircleId) return
      applyCircleSummaryPayload(summary)
      scheduleCircleDetailPrefetch()
      return
    }

    const worksQuery = buildCircleWorksQuery()
    const cachedWorks = preferCache ? getCachedCircleWorksPage(requestCircleId, worksQuery) : null
    if (cachedWorks) {
      applyCircleSummaryPayload(cachedWorks)
      applyCircleWorksPayload(cachedWorks)
      setCachedCircleDetail(requestCircleId, buildCachedCircleDetailPayload(cachedWorks, cachedWorks))
      scheduleCircleDetailPrefetch()
      return
    }

    const works = await circleCompletionApi.getCircleWorks(requestCircleId, worksQuery, {
      signal: circleDetailAbortController.signal
    })
    if (requestSeq !== circleDetailRequestSeq || activeCircleId.value !== requestCircleId) return
    applyCircleSummaryPayload(works)
    applyCircleWorksPayload(works)
    setCachedCircleWorksPage(requestCircleId, worksQuery, works)
    if (activeTab.value === 'missing' && missingPage.value === 1 && !statusFilters.value.length) {
      setCachedCircleDetail(requestCircleId, buildCachedCircleDetailPayload(works, works))
    }
    scheduleCircleDetailPrefetch()
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    ElMessage.error(error.response?.data?.detail || '加载社团详情失败')
  } finally {
    if (requestSeq === circleDetailRequestSeq) {
      circleDetailLoading.value = false
      circleWorksPage.loading = false
      circleDetailAbortController = null
    }
  }
}

async function refreshActiveCircleWorks(options = {}) {
  const circleId = String(activeCircleId.value || '').trim()
  if (!circleId) return
  const requestSeq = ++circleDetailRequestSeq
  if (circleDetailAbortController) {
    circleDetailAbortController.abort()
  }
  const worksQuery = buildCircleWorksQuery()
  const cachedWorks = getCachedCircleWorksPage(circleId, worksQuery)
  if (cachedWorks) {
    applyCircleSummaryPayload(cachedWorks)
    applyCircleWorksPayload(cachedWorks)
    circleWorksPage.loading = false
    circleDetailLoading.value = false
    circleDetailAbortController = null
    return
  }

  circleDetailAbortController = new AbortController()
  circleWorksPage.loading = true
  if (options.showLoading !== false) circleDetailLoading.value = !circleDetailLoaded.value
  try {
    const result = await circleCompletionApi.getCircleWorks(circleId, worksQuery, {
      signal: circleDetailAbortController.signal
    })
    if (requestSeq !== circleDetailRequestSeq || activeCircleId.value !== circleId) return
    applyCircleSummaryPayload(result)
    applyCircleWorksPayload(result)
    setCachedCircleWorksPage(circleId, worksQuery, result)
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    ElMessage.error(error.response?.data?.detail || '加载社团作品失败')
  } finally {
    if (requestSeq === circleDetailRequestSeq) {
      circleWorksPage.loading = false
      circleDetailLoading.value = false
      circleDetailAbortController = null
    }
  }
}

function toggleSelection(item) {
  if (!item?.canonical_rjcode) return
  const code = String(item.canonical_rjcode || '').trim()
  const next = new Set(selectedCanonicals.value)
  const nextDownloadable = new Set(selectedDownloadableCanonicals.value)
  const nextRequested = { ...selectedRequestedRjcodes.value }
  if (next.has(code)) {
    next.delete(code)
    nextDownloadable.delete(code)
    delete nextRequested[code]
  } else {
    next.add(code)
    if (item?.has_asmr_one) nextDownloadable.add(code)
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
    if (candidates.length) nextRequested[code] = candidates
  }
  selectedCanonicals.value = next
  selectedDownloadableCanonicals.value = nextDownloadable
  selectedRequestedRjcodes.value = nextRequested
}

async function selectAllVisibleWorks() {
  if (!activeCircleId.value) return
  try {
    const result = await circleCompletionApi.getCircleWorkCodes(activeCircleId.value, buildCircleWorksQuery({ includePage: false }))
    selectedCanonicals.value = new Set((result.canonical_rjcodes || []).filter(Boolean))
    selectedDownloadableCanonicals.value = new Set((result.downloadable_rjcodes || []).filter(Boolean))
    selectedRequestedRjcodes.value = result.requested_rjcodes || {}
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '全选当前筛选结果失败')
  }
}

function clearSelection() {
  selectedCanonicals.value = new Set()
  selectedDownloadableCanonicals.value = new Set()
  selectedRequestedRjcodes.value = {}
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

function waitForPreviewPoll(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

async function requestBatchDownloadPreview(payload, selectedCount) {
  if (selectedCount <= DOWNLOAD_PREVIEW_JOB_THRESHOLD) {
    previewProgressLabel.value = '正在分析资源结构并生成下载计划...'
    previewProgressDescription.value = '聚合资源分组、语言版本和推荐项'
    return await circleCompletionApi.previewBatchDownload(payload)
  }

  const started = await circleCompletionApi.startPreviewBatchDownload(payload)
  let job = started
  while (job && ['pending', 'processing'].includes(String(job.status || ''))) {
    previewProgressLabel.value = `${job.current_step || '正在生成下载预览'} · ${Math.max(0, Math.min(100, Number(job.progress || 0)))}%`
    previewProgressDescription.value = `已提交 ${Number(job.selected_count || selectedCount)} 个作品，耗时 ${formatElapsed(job.elapsed_seconds || 0)}`
    await waitForPreviewPoll(800)
    job = await circleCompletionApi.getPreviewBatchDownloadJobStatus(started.job_id)
  }
  if (job?.status === 'completed') {
    previewProgressLabel.value = '下载预览已生成'
    previewProgressDescription.value = `共生成 ${Number(job.result?.planned_count || 0)} 个下载计划`
    return job.result || {}
  }
  throw new Error(job?.error_message || '生成下载预览失败')
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
    const result = await requestBatchDownloadPreview({
      circle_id: detail.circle_id,
      canonical_rjcodes: codes,
      requested_rjcodes: getPreviewRequestedRjcodes(codes)
    }, codes.length)
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
    ElMessage.error(error.response?.data?.detail || error.message || '生成下载预览失败')
  } finally {
    previewing.value = false
    previewLoading.value = false
    previewProgressLabel.value = '正在分析资源结构并生成下载计划...'
    previewProgressDescription.value = '聚合资源分组、语言版本和推荐项'
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
    await refreshActiveCircle({ summaryOnly: false })
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
    await refreshActiveCircle({ summaryOnly: false })
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
      await refreshActiveCircle({ summaryOnly: false })
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
  --circle-page-bg: transparent;
  --circle-surface: #ffffff;
  --circle-surface-soft: #f8fafc;
  --circle-surface-muted: rgba(248, 250, 252, 0.86);
  --circle-surface-elevated: rgba(255, 255, 255, 0.96);
  --circle-field-bg: #ffffff;
  --circle-hover-bg: #f1f5f9;
  --circle-selected-bg: #eff6ff;
  --circle-selected-strong-bg: #0f172a;
  --circle-border: rgba(15, 23, 42, 0.12);
  --circle-border-soft: #e2e8f0;
  --circle-border-strong: #94a3b8;
  --circle-text: #334155;
  --circle-text-strong: #111827;
  --circle-text-muted: #64748b;
  --circle-text-subtle: #94a3b8;
  --circle-placeholder: #94a3b8;
  --circle-primary: #2563eb;
  --circle-primary-soft: #eff6ff;
  --circle-success: #059669;
  --circle-success-soft: #ecfdf5;
  --circle-danger: #dc2626;
  --circle-danger-soft: #fef2f2;
  --circle-warning: #d97706;
  --circle-warning-soft: #fffbeb;
  --circle-orange: #ea580c;
  --circle-orange-soft: rgba(255, 248, 240, 0.95);
  --circle-violet: #7e22ce;
  --circle-violet-soft: #faf5ff;
  --circle-sky: #0284c7;
  --circle-sky-soft: #f0f9ff;
  --circle-indigo: #4f46e5;
  --circle-indigo-soft: #eef2ff;
  --circle-rose: #e11d48;
  --circle-rose-soft: #fff1f2;
  --circle-tag-primary: #2563eb;
  --circle-tag-primary-soft: #eff6ff;
  --circle-tag-success: #059669;
  --circle-tag-success-soft: #ecfdf5;
  --circle-tag-danger: #dc2626;
  --circle-tag-danger-soft: #fef2f2;
  --circle-tag-warning: #d97706;
  --circle-tag-warning-soft: #fffbeb;
  --circle-tag-orange: #ea580c;
  --circle-tag-orange-soft: rgba(255, 248, 240, 0.95);
  --circle-tag-violet: #7e22ce;
  --circle-tag-violet-soft: #faf5ff;
  --circle-tag-sky: #0284c7;
  --circle-tag-sky-soft: #f0f9ff;
  --circle-tag-indigo: #4f46e5;
  --circle-tag-indigo-soft: #eef2ff;
  --circle-tag-rose: #e11d48;
  --circle-tag-rose-soft: #fff1f2;
  --circle-shadow-soft: 0 1px 2px rgba(15, 23, 42, 0.04), 0 6px 16px -10px rgba(15, 23, 42, 0.10);
  --circle-shadow-lift: 0 8px 18px rgba(15, 23, 42, 0.08);
  --circle-work-card-bg: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(248, 251, 255, 0.94) 100%);
  --circle-work-card-hover-bg: linear-gradient(180deg, rgba(255, 255, 255, 1) 0%, rgba(246, 250, 255, 0.98) 100%);
  --circle-work-card-selected-bg: radial-gradient(circle at top right, rgba(37, 99, 235, 0.08), transparent 38%), linear-gradient(180deg, rgba(255, 255, 255, 0.99) 0%, rgba(244, 248, 255, 0.98) 100%);
  --circle-work-card-border: rgba(148, 163, 184, 0.22);
  --circle-work-card-hover-border: rgba(52, 120, 246, 0.28);
  --circle-work-card-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.88), 0 8px 20px rgba(15, 23, 42, 0.045);
  --circle-work-card-hover-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92), 0 14px 30px rgba(38, 74, 134, 0.12);
  --circle-work-cover-bg: linear-gradient(135deg, rgba(241, 245, 249, 0.96), rgba(248, 250, 252, 0.82));
  --circle-chip-bg: rgba(248, 250, 252, 0.72);
  --circle-chip-border: rgba(203, 213, 225, 0.72);
  --circle-label-surface: rgba(248, 250, 252, 0.82);
  --circle-label-border: rgba(203, 213, 225, 0.72);
  --circle-label-shadow: none;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  color: var(--circle-text);
  background: var(--circle-page-bg);
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}

:global(html.kikoerumanager-dark .circle-page),
:global(body.kikoerumanager-dark .circle-page) {
  --circle-page-bg: linear-gradient(180deg, #121316 0%, #0c0d10 100%);
  --circle-surface: #17191d;
  --circle-surface-soft: #202226;
  --circle-surface-muted: #25282d;
  --circle-surface-elevated: rgba(32, 34, 38, 0.94);
  --circle-field-bg: #101114;
  --circle-hover-bg: #262a30;
  --circle-selected-bg: rgba(255, 255, 255, 0.12);
  --circle-selected-strong-bg: linear-gradient(180deg, #56575e 0%, #3a3b40 100%);
  --circle-border: rgba(255, 255, 255, 0.12);
  --circle-border-soft: rgba(255, 255, 255, 0.10);
  --circle-border-strong: rgba(148, 163, 184, 0.36);
  --circle-text: rgba(244, 244, 245, 0.88);
  --circle-text-strong: #ffffff;
  --circle-text-muted: rgba(212, 212, 216, 0.68);
  --circle-text-subtle: rgba(161, 161, 170, 0.62);
  --circle-placeholder: rgba(161, 161, 170, 0.62);
  --circle-primary: #d4d4d8;
  --circle-primary-soft: rgba(255, 255, 255, 0.075);
  --circle-success: #d4d4d8;
  --circle-success-soft: rgba(255, 255, 255, 0.075);
  --circle-danger: #fda4af;
  --circle-danger-soft: rgba(244, 63, 94, 0.09);
  --circle-warning: #fcd34d;
  --circle-warning-soft: rgba(245, 158, 11, 0.10);
  --circle-orange: #fdba74;
  --circle-orange-soft: rgba(249, 115, 22, 0.10);
  --circle-violet: #d8b4fe;
  --circle-violet-soft: rgba(168, 85, 247, 0.10);
  --circle-sky: #7dd3fc;
  --circle-sky-soft: rgba(14, 165, 233, 0.10);
  --circle-indigo: #a5b4fc;
  --circle-indigo-soft: rgba(99, 102, 241, 0.10);
  --circle-rose: #fda4af;
  --circle-rose-soft: rgba(244, 63, 94, 0.09);
  --circle-tag-primary: #60a5fa;
  --circle-tag-primary-soft: rgba(59, 130, 246, 0.13);
  --circle-tag-success: #34d399;
  --circle-tag-success-soft: rgba(16, 185, 129, 0.13);
  --circle-tag-danger: #fb7185;
  --circle-tag-danger-soft: rgba(244, 63, 94, 0.12);
  --circle-tag-warning: #fbbf24;
  --circle-tag-warning-soft: rgba(245, 158, 11, 0.13);
  --circle-tag-orange: #fb923c;
  --circle-tag-orange-soft: rgba(249, 115, 22, 0.13);
  --circle-tag-violet: #c084fc;
  --circle-tag-violet-soft: rgba(168, 85, 247, 0.13);
  --circle-tag-sky: #38bdf8;
  --circle-tag-sky-soft: rgba(14, 165, 233, 0.13);
  --circle-tag-indigo: #a5b4fc;
  --circle-tag-indigo-soft: rgba(99, 102, 241, 0.13);
  --circle-tag-rose: #fb7185;
  --circle-tag-rose-soft: rgba(244, 63, 94, 0.12);
  --circle-shadow-soft: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  --circle-shadow-lift: 0 18px 38px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  --circle-work-card-bg: linear-gradient(180deg, #202226 0%, #17191d 100%);
  --circle-work-card-hover-bg: linear-gradient(180deg, #252a30 0%, #191b20 100%);
  --circle-work-card-selected-bg: radial-gradient(circle at top right, rgba(255, 255, 255, 0.12), transparent 38%), linear-gradient(180deg, #24282e 0%, #17191d 100%);
  --circle-work-card-border: rgba(255, 255, 255, 0.12);
  --circle-work-card-hover-border: rgba(255, 255, 255, 0.24);
  --circle-work-card-shadow: 0 10px 24px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  --circle-work-card-hover-shadow: 0 16px 34px rgba(0, 0, 0, 0.30), 0 0 0 1px rgba(255, 255, 255, 0.08);
  --circle-work-cover-bg: linear-gradient(135deg, #111214, #23262b);
  --circle-chip-bg: rgba(255, 255, 255, 0.045);
  --circle-chip-border: rgba(255, 255, 255, 0.09);
  --circle-label-surface: rgba(255, 255, 255, 0.045);
  --circle-label-border: rgba(255, 255, 255, 0.10);
  --circle-label-shadow: none;
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

.circle-works-loading-state :deep(.app-loading-animation__copy) {
  display: grid;
  gap: 8px;
  text-align: center;
}

.circle-works-loading-state :deep(.app-loading-animation__label) {
  color: var(--circle-text, #111827);
  font-size: 15px;
  font-weight: 800;
  line-height: 1.35;
  letter-spacing: 0;
}

.circle-works-loading-state :deep(.app-loading-animation__description) {
  color: var(--circle-text-secondary, #64748b);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.55;
  letter-spacing: 0;
}

.works-card {
  position: relative;

}

.circle-works-page-loading {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 8;
  display: block;
  height: 2px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  box-shadow: none;
  overflow: hidden;
  pointer-events: none;

}

.circle-works-page-loading::before {
  content: "";
  position: absolute;
  top: 0;
  left: -34%;
  width: 34%;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(96, 165, 250, 0.88), transparent);
  animation: circle-works-page-loading-slide 1s ease-in-out infinite;

}

.circle-works-page-loading-icon {
  display: none;

}

.circle-works-page-loading span {
  display: none;

}

:global(html.kikoerumanager-dark) .circle-works-page-loading,
:global(body.kikoerumanager-dark) .circle-works-page-loading {
  background: transparent;
  box-shadow: none;

}

@keyframes circle-works-page-loading-slide {
  from { transform: translateX(0); }
  to { transform: translateX(394%); }

}

:global(html.kikoerumanager-dark) .circle-works-loading-state :deep(.app-loading-animation__label),
:global(body.kikoerumanager-dark) .circle-works-loading-state :deep(.app-loading-animation__label) {
  color: rgba(244, 247, 255, 0.95);
  text-shadow: 0 1px 10px rgba(0, 0, 0, 0.26);
}

:global(html.kikoerumanager-dark) .circle-works-loading-state :deep(.app-loading-animation__description),
:global(body.kikoerumanager-dark) .circle-works-loading-state :deep(.app-loading-animation__description) {
  color: rgba(192, 206, 235, 0.84);
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.22);
}

.circle-complete-state {
  flex: 1;
  min-height: 340px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 24px 16px;
  overflow: hidden;
}

.circle-complete-visual {
  position: relative;
  width: min(320px, 42vw);
  max-width: 100%;
  aspect-ratio: 1.05;
  display: grid;
  place-items: end center;
  overflow: visible;
}

.circle-complete-visual::before {
  content: '';
  position: absolute;
  inset: 2% -18% -10%;
  z-index: 0;
  border-radius: 46% 46% 42% 42%;
  background:
    radial-gradient(ellipse at 50% 62%, rgba(255, 255, 255, 0.76) 0%, rgba(248, 245, 255, 0.48) 34%, rgba(196, 185, 220, 0.18) 58%, rgba(196, 185, 220, 0) 78%);
  filter: blur(18px);
  opacity: 0.9;
  transform: translateY(6px);
  pointer-events: none;
}

.circle-complete-visual::after {
  content: '';
  position: absolute;
  inset: 22% -4% 6%;
  z-index: 0;
  border-radius: 999px;
  background:
    radial-gradient(ellipse at 50% 70%, color-mix(in srgb, var(--circle-tag-success, #059669) 16%, transparent) 0%, transparent 62%);
  filter: blur(26px);
  opacity: 0.72;
  pointer-events: none;
}

.circle-complete-image {
  display: block;
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: min(320px, 42vw, 48vh);
  height: auto;
  object-fit: contain;
  opacity: 0;
  transform: translateY(8px) scale(0.96);
  transition:
    opacity 0.28s ease,
    transform 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

.circle-complete-image.is-revealed {
  opacity: 1;
  transform: translateY(0) scale(1);
}

.circle-complete-confetti {
  position: absolute;
  inset: -22% -24% -8%;
  z-index: 2;
  pointer-events: none;
}

.circle-complete-confetti-player {
  width: 100%;
  height: 100%;
}

.complete-confetti-enter-active,
.complete-confetti-leave-active {
  transition:
    opacity 0.24s ease,
    transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.complete-confetti-enter-from,
.complete-confetti-leave-to {
  opacity: 0;
  transform: scale(0.96);
}

.circle-complete-copy {
  display: flex;
  justify-content: center;
}

.circle-complete-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.circle-complete-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--circle-label-border, rgba(226, 232, 240, 0.72));
  background: var(--circle-label-surface, rgba(248, 250, 252, 0.86));
  color: var(--circle-text-muted, #64748b);
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}

.circle-complete-pill.owned {
  color: var(--circle-tag-success, #059669);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-success, #059669) 8%, transparent);
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-state),
:global(body.kikoerumanager-dark .circle-page .circle-complete-state) {
  min-height: 180px;
  padding: 32px 16px;
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-visual),
:global(body.kikoerumanager-dark .circle-page .circle-complete-visual) {
  display: none;
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-visual::before),
:global(body.kikoerumanager-dark .circle-page .circle-complete-visual::before) {
  display: none;
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-visual::after),
:global(body.kikoerumanager-dark .circle-page .circle-complete-visual::after) {
  display: none;
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-confetti),
:global(body.kikoerumanager-dark .circle-page .circle-complete-confetti) {
  display: none;
}

:global(html.kikoerumanager-dark .circle-page .circle-complete-image),
:global(body.kikoerumanager-dark .circle-page .circle-complete-image) {
  display: none;
  filter: none;
}

/* 页头现在走共享组件 components/common/AppPageHeader.vue，这里只保留原 circle-hero 外边距与右侧 slot 内嵌样式 */
.circle-page-header {
  margin: 8px 8px 0;
}
.hero-search-wrap {
  position: relative;
  width: min(360px, 38vw);
  min-width: 260px;
}
.hero-search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--circle-text-subtle, rgb(148 163 184));
  z-index: 1;
  pointer-events: none;
}
.hero-search-input :deep(.el-input__wrapper) {
  min-height: 28px;
  width: 100%;
  min-width: 0;
  border-radius: 8px;
  --el-input-bg-color: var(--circle-field-bg, #fff);
  --el-input-text-color: var(--circle-text-strong, rgb(30 41 59));
  --el-input-placeholder-color: var(--circle-placeholder, rgb(148 163 184));
  background: var(--circle-field-bg, #fff);
  box-shadow: 0 0 0 1px var(--circle-border-soft, rgb(226 232 240)) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
  padding: 0 8px 0 26px;
  transition: box-shadow 0.3s ease;
}
.hero-search-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--circle-border-strong, rgb(203 213 225)) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
}
.hero-search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--circle-primary, rgb(148 163 184)) inset, 0 0 0 3px color-mix(in srgb, var(--circle-primary, #2563eb) 14%, transparent);
}
.hero-search-input :deep(.el-input__inner) {
  height: 26px;
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--circle-text-strong, rgb(30 41 59));
}
.hero-search-input :deep(.el-input__inner::placeholder) {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--circle-placeholder, rgb(148 163 184));
}
.hero-work-search-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 30;
  display: grid;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.85));
  border-radius: 10px;
  background: var(--circle-surface-elevated, rgba(255, 255, 255, 0.98));
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16);
  backdrop-filter: blur(10px);
}
.hero-work-search-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 52px;
  color: var(--circle-text-subtle, #94a3b8);
  font-size: 12px;
  font-weight: 750;
}
.hero-work-search-state.no-data {
  color: var(--circle-text-muted, #64748b);
}
.hero-work-search-item {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  padding: 7px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.hero-work-search-item:hover {
  border-color: var(--circle-border-strong, #cbd5e1);
  background: var(--circle-hover-bg, #f8fafc);
  transform: translateY(-1px) scale(1.01);
}
.hero-work-search-item:active {
  transform: scale(0.96);
}
.hero-work-search-cover {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  overflow: hidden;
  border-radius: 7px;
  background: var(--circle-work-cover-bg, #f1f5f9);
  color: var(--circle-text-subtle, #94a3b8);
}
.hero-work-search-cover img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.hero-work-search-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.hero-work-search-title {
  overflow: hidden;
  color: var(--circle-text-strong, #111827);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hero-work-search-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--circle-text-muted, #64748b);
  font-size: 10px;
  font-weight: 700;
}
.hero-work-search-meta span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hero-work-search-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  height: 20px;
  padding: 0 6px;
  border-radius: 5px;
  border: 1px solid color-mix(in srgb, var(--circle-tag-warning, #d97706) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-warning, #d97706) 8%, transparent);
  color: var(--circle-tag-warning, #d97706);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
}
.hero-work-search-status.owned {
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-success, #059669) 8%, transparent);
  color: var(--circle-tag-success, #059669);
}
.hero-btn {
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  margin: 0 !important;
  border-radius: 8px;
  font-size: 12px !important;
  font-weight: 700 !important;
  line-height: 1 !important;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.hero-btn-primary {
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
  background: var(--circle-selected-strong-bg, rgb(15 23 42));
  color: #fff;
  border: 1px solid color-mix(in srgb, var(--circle-text-strong, rgb(15 23 42)) 70%, transparent);
  box-shadow: 0 2px 6px -2px rgba(15, 23, 42, 0.35);
}
.hero-btn-primary:hover:not(.is-disabled):not(:disabled) {
  background: var(--circle-selected-strong-bg, rgb(30 41 59));
  filter: brightness(1.08);
  transform: translateY(-1px);
}
.hero-btn-primary:active:not(.is-disabled):not(:disabled) {
  transform: translateY(0) scale(0.96);
}
.hero-btn-email {
  background: var(--circle-surface, #ffffff);
  color: var(--circle-text, rgb(51 65 85));
  border: 1px solid var(--circle-border-soft, rgb(226 232 240));
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  display: flex;
  align-items: center;
}
.hero-btn-email:hover:not(.is-disabled):not(:disabled) {
  background: var(--circle-hover-bg, rgb(248 250 252));
  border-color: var(--circle-border-strong, rgb(203 213 225));
  color: var(--circle-text-strong, rgb(15 23 42));
  transform: translateY(-1px);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}
.hero-btn-email:active:not(.is-disabled):not(:disabled) {
  transform: translateY(0) scale(0.96);
}
.sidebar-refresh-button {
  font-weight: 600;
  color: var(--circle-text-muted, #6b7280);
  font-size: 12px;
}
.sidebar-head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.sidebar-head-actions .sidebar-refresh-button {
  display: inline-flex;
  align-items: center;
  gap: 3px;
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
  border: 1px solid var(--circle-border-soft, #e2e8f0);
  border-radius: 999px;
  background: var(--circle-surface, #ffffff);
  color: var(--circle-text, #334155);
  font-size: 12px !important;
  font-weight: 700 !important;
  line-height: 1 !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sidebar-filter-chip:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--circle-border-strong, #cbd5e1);
  background: var(--circle-hover-bg, #f8fafc);
  color: var(--circle-text-strong, #0f172a);
  box-shadow: var(--circle-shadow-lift, 0 8px 18px rgba(15, 23, 42, 0.08));
}

.sidebar-filter-chip:active {
  transform: scale(0.96);
}

.sidebar-filter-chip.active {
  border-color: color-mix(in srgb, var(--circle-primary, #1d4ed8) 44%, transparent);
  background: var(--circle-selected-bg, #eff6ff);
  color: var(--circle-primary, #1d4ed8);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--circle-primary, #1d4ed8) 14%, transparent), inset 0 0 0 1px color-mix(in srgb, var(--circle-primary, #1d4ed8) 22%, transparent);
}

.sidebar-filter-chip.new-work.active {
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 50%, transparent);
  background: var(--circle-tag-orange-soft, rgba(255, 248, 240, 0.95));
  color: var(--circle-tag-orange, #ea580c);
  box-shadow: 0 1px 2px rgba(249, 115, 22, 0.1), inset 0 0 0 1px rgba(249, 115, 22, 0.2);
}

.sidebar-filter-chip.new-work:not(.active):hover {
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 34%, transparent);
  background: color-mix(in srgb, var(--circle-tag-orange-soft, rgba(255, 248, 240, 0.6)) 72%, transparent);
  color: var(--circle-tag-orange, #ea580c);
}

.sidebar-sort-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sidebar-sort-label {
  flex-shrink: 0;
  color: var(--circle-text-muted, #64748b);
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
  border: 1px solid var(--circle-border-soft, #e5e7eb);
  background: var(--circle-surface, #fff);
  box-shadow: var(--circle-shadow-soft, 0 1px 4px rgba(0,0,0,0.05));
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
  border: 1px solid var(--circle-border-soft, #e5e7eb);
  background: var(--circle-surface-soft, #fafafa);
  max-height: 156px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 16px 9px;
  scrollbar-width: thin;
  scrollbar-color: var(--circle-border-strong, #cbd5e1) transparent;
}
.refresh-progress-card::-webkit-scrollbar {
  width: 6px;
}
.refresh-progress-card::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--circle-border-strong, #cbd5e1);
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
  color: var(--circle-text-strong, #111827);
}
.index-progress-subtitle {
  min-width: 0;
  margin-top: 2px;
  font-size: 12px;
  color: var(--circle-text-muted, #6b7280);
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
  background: var(--circle-tag-primary-soft, #eff6ff);
  color: var(--circle-tag-primary, #2563eb);
  border: 1px solid color-mix(in srgb, var(--circle-tag-primary, #2563eb) 22%, transparent);
}
.index-progress-status.completed {
  background: var(--circle-tag-success-soft, #ecfdf5);
  color: var(--circle-tag-success, #059669);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 22%, transparent);
}
.index-progress-status.failed {
  background: var(--circle-tag-danger-soft, #fef2f2);
  color: var(--circle-tag-danger, #dc2626);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 22%, transparent);
}
.index-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.progress-meta-pill {
  background: var(--circle-surface-elevated, #ffffff);
  color: var(--circle-text, #334155);
  border: 1px solid var(--circle-border-soft, #e5e7eb);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.progress-meta-pill svg {
  color: var(--circle-text-muted, #64748b);
  stroke-width: 2.2;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.progress-meta-pill:hover svg {
  transform: scale(1.14) rotate(-4deg);
}
.progress-meta-pill.time svg {
  color: var(--circle-text-muted, #64748b);
}
.progress-meta-pill.total svg,
.progress-meta-pill.merged svg,
.progress-meta-pill.current svg {
  color: var(--circle-text, #475569);
}
.progress-meta-pill.batch svg {
  color: var(--circle-tag-primary, #2563eb);
}
.progress-meta-pill.local svg {
  color: var(--circle-tag-success, #0f766e);
}
.progress-meta-pill.kikoeru svg {
  color: var(--circle-tag-violet, #7c3aed);
}
.progress-meta-pill.dlsite svg {
  color: var(--circle-tag-sky, #0284c7);
}
.progress-meta-pill.changed svg {
  color: var(--circle-tag-warning, #f59e0b);
}
.progress-meta-pill.ok {
  background: var(--circle-surface-elevated, #ffffff);
  color: var(--circle-text, #334155);
  border-color: color-mix(in srgb, var(--circle-tag-success, #10b981) 24%, transparent);
}
.progress-meta-pill.ok svg {
  color: var(--circle-tag-success, #10b981);
}
.progress-meta-pill.warn {
  background: var(--circle-surface-elevated, #ffffff);
  color: var(--circle-text, #334155);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 30%, transparent);
}
.progress-meta-pill.warn svg {
  color: var(--circle-tag-danger, #ef4444);
}
.index-progress-error {
  font-size: 12px;
  color: var(--circle-tag-danger, #dc2626);
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
  background: var(--circle-surface-muted, #f9fafb);
  border: 1px solid var(--circle-border-soft, #f3f4f6);
  color: var(--circle-text, #4b5563);
  font-size: 12px;
}
.refresh-progress-log-item.success {
  background: var(--circle-tag-success-soft, #ecfdf5);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 24%, transparent);
  color: var(--circle-tag-success, #065f46);
}
.refresh-progress-log-item.warning {
  background: var(--circle-tag-warning-soft, #fffbeb);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #d97706) 28%, transparent);
  color: var(--circle-tag-warning, #92400e);
}
.refresh-progress-log-item.error {
  background: var(--circle-tag-danger-soft, #fef2f2);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 24%, transparent);
  color: var(--circle-tag-danger, #991b1b);
}
.refresh-progress-log-time {
  flex: 0 0 auto;
  color: var(--circle-text-subtle, #9ca3af);
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
  background: var(--circle-surface, #fff);
  border-radius: 14px;
  border: 1px solid var(--circle-border, rgba(15, 23, 42, 0.12));
  box-shadow: var(--circle-shadow-soft, 0 1px 2px rgba(15, 23, 42, 0.04), 0 6px 16px -10px rgba(15, 23, 42, 0.10));
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
  color: var(--circle-text-subtle, #94a3b8);
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
  color: var(--circle-text-strong, #111827);
}
.toolbar-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--circle-text-strong, #111827);
}
.toolbar-card {
  padding: 8px 14px 6px;
  display: grid;
  align-content: start;
  gap: 4px;
  min-height: 0;
  border-bottom: 1px solid var(--circle-border-soft, #f3f4f6);
}
.toolbar-subtitle {
  font-size: 11px;
  color: var(--circle-text-subtle, #9ca3af);
  margin-top: 1px;
}
.toolbar-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.toolbar-stats-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  flex-shrink: 0;
}
.toolbar-actions .batch-action-button {
  min-width: 88px;
  height: 28px;
  padding: 0 11px;
  font-size: 11px !important;
  font-weight: 700 !important;
  line-height: 1 !important;
}
.metric-pill {
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
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  font-size: 10.5px;
  font-weight: 700;
  background: var(--circle-label-surface, var(--circle-surface-elevated, #ffffff));
  color: var(--circle-text, #475569);
  border: 1px solid var(--circle-label-border, var(--circle-border-soft, #e2e8f0));
  box-shadow: var(--circle-label-shadow, none);
  cursor: default;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.metric-pill:hover {
  transform: translateY(-1px);
  box-shadow: var(--circle-label-shadow, none);
  border-color: var(--circle-border-strong, #cbd5e1);
}
.metric-pill svg {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.metric-pill:hover svg {
  transform: scale(1.2) rotate(5deg);
}
.metric-pill.owned {
  color: var(--circle-tag-primary, #2563eb);
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 24%, transparent);
}
.metric-pill.owned:hover {
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 12%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 36%, transparent);
  color: var(--circle-tag-primary, #1d4ed8);
}
.metric-pill.warn {
  color: var(--circle-tag-warning, #d97706);
  background: color-mix(in srgb, var(--circle-tag-warning, #d97706) 9%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #d97706) 24%, transparent);
}
.metric-pill.warn:hover {
  background: color-mix(in srgb, var(--circle-tag-warning, #d97706) 13%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #d97706) 36%, transparent);
  color: var(--circle-tag-warning, #b45309);
}
.metric-pill.ok {
  color: var(--circle-tag-success, #16a34a);
  background: color-mix(in srgb, var(--circle-tag-success, #16a34a) 9%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-success, #16a34a) 24%, transparent);
}
.metric-pill.ok:hover {
  background: color-mix(in srgb, var(--circle-tag-success, #16a34a) 13%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-success, #16a34a) 36%, transparent);
  color: var(--circle-tag-success, #15803d);
}
.metric-pill.muted {
  color: var(--circle-text-muted, #64748b);
  background: var(--circle-label-surface, var(--circle-surface-soft, #f8fafc));
  border-color: var(--circle-border-soft, #f1f5f9);
}
.metric-pill.muted:hover {
  background: var(--circle-hover-bg, #f1f5f9);
  border-color: var(--circle-border-soft, #e2e8f0);
  color: var(--circle-text, #475569);
}
.metric-pill.unreleased {
  color: var(--circle-tag-primary, #2563eb);
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 24%, transparent);
}
.metric-pill.unreleased:hover {
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 12%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 36%, transparent);
}
.metric-pill.bonus {
  color: var(--circle-tag-violet, #7e22ce);
  background: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 24%, transparent);
  box-shadow: var(--circle-label-shadow, none);
}
.metric-pill.bonus:hover {
  background: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 12%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 34%, transparent);
  color: var(--circle-tag-violet, #7e22ce);
}
.metric-pill.new-work {
  color: var(--circle-tag-orange, #ea580c);
  background: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 24%, transparent);
}
.metric-pill.new-work:hover {
  background: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 12%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 36%, transparent);
}
.toolbar-right-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.work-status-filter-dropdown {
  flex-shrink: 0;
}
.status-filter-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  flex: 0 0 auto;
  width: 100%;
  height: 30px;
  padding: 0 9px 0 11px;
  box-sizing: border-box;
  border: 1px solid var(--circle-border-soft, rgba(203, 213, 225, 0.9));
  border-radius: 10px;
  background: var(--circle-surface-elevated, linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.94) 100%));
  color: var(--circle-text, #334155);
  line-height: 1;
  box-shadow: none;
  cursor: pointer;
  overflow: visible;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-trigger:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--circle-border-strong, rgba(148, 163, 184, 0.92));
  background: var(--circle-hover-bg, #ffffff);
  box-shadow: none;
}
.status-filter-trigger:active {
  transform: scale(0.96);
}
.status-filter-trigger.is-open {
  border-color: var(--circle-border-strong, rgba(148, 163, 184, 0.96));
  background: var(--circle-surface-elevated, #ffffff);
  box-shadow: none;
}
.status-filter-trigger__content {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  height: 100%;
  min-width: 0;
  line-height: 1;
  overflow: hidden;
}
.status-filter-trigger__content.has-overflow::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 14px;
  background: linear-gradient(90deg, transparent 0%, var(--circle-surface-elevated, rgba(255, 255, 255, 0.98)) 100%);
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
  color: var(--circle-text-muted, rgba(100, 116, 139, 0.82));
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
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
  background: var(--circle-surface-soft, rgba(241, 245, 249, 0.92));
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.86));
  color: var(--circle-text, #334155);
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
  background: var(--circle-surface-soft, rgba(241, 245, 249, 0.86));
  color: var(--circle-text-muted, #64748b);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}
.status-filter-trigger__caret {
  flex-shrink: 0;
  color: var(--circle-text-muted, #64748b);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-trigger:hover .status-filter-trigger__caret {
  color: var(--circle-text, #334155);
  transform: translateY(-1px);
}
.status-filter-trigger__caret.is-open {
  transform: rotate(180deg);
  color: var(--circle-text, #334155);
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
  color: var(--circle-text, #334155);
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
  background: var(--circle-surface-soft, rgba(248, 250, 252, 0.72));
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.78));
  color: var(--circle-text-muted, #64748b);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.status-filter-option__check {
  flex-shrink: 0;
  color: var(--circle-text-muted, #64748b);
  opacity: 0.82;
}
:global(.circle-status-filter-menu.app-dd-menu) {
  --circle-surface: #ffffff;
  --circle-surface-soft: #f8fafc;
  --circle-hover-bg: #f1f5f9;
  --circle-selected-bg: #f1f5f9;
  --circle-border-soft: #e2e8f0;
  --circle-border-strong: #94a3b8;
  --circle-text: #334155;
  --circle-text-strong: #0f172a;
  --circle-text-muted: #64748b;
  padding: 6px;
  border-radius: 14px;
  border-color: var(--circle-border-soft, rgba(203, 213, 225, 0.92));
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
  background: var(--circle-hover-bg, rgba(248, 250, 252, 0.98));
}
:global(.circle-status-filter-menu .app-dd-item.is-active) {
  background: var(--circle-selected-bg, linear-gradient(90deg, rgba(248, 250, 252, 0.98) 0%, rgba(241, 245, 249, 0.58) 100%));
  color: var(--circle-text-strong, #0f172a);
  font-weight: 600;
}
:global(html.kikoerumanager-dark .circle-status-filter-menu.app-dd-menu),
:global(body.kikoerumanager-dark .circle-status-filter-menu.app-dd-menu) {
  --circle-surface: #17191d;
  --circle-surface-soft: #202226;
  --circle-hover-bg: #262a30;
  --circle-selected-bg: #24252a;
  --circle-border-soft: rgba(255, 255, 255, 0.12);
  --circle-border-strong: rgba(148, 163, 184, 0.36);
  --circle-text: rgba(244, 244, 245, 0.82);
  --circle-text-strong: #f4f4f5;
  --circle-text-muted: rgba(212, 212, 216, 0.66);
}
:global(.circle-status-filter-menu .app-dd-item.is-active:hover) {
  background: var(--circle-hover-bg, linear-gradient(90deg, rgba(241, 245, 249, 0.98) 0%, rgba(226, 232, 240, 0.48) 100%));
}
:global(.circle-status-filter-menu .app-dd-item.is-active .status-filter-option__label),
:global(.circle-status-filter-menu .app-dd-item.is-active .status-filter-option__check) {
  color: var(--circle-text-strong, #0f172a);
}
:global(.circle-status-filter-menu .app-dd-item.is-active .status-filter-option__count) {
  background: var(--circle-surface, #ffffff);
  border-color: var(--circle-border-strong, rgba(203, 213, 225, 0.84));
  color: var(--circle-text, #334155);
}
.release-sort-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 0 0 auto;
  height: 30px;
  padding: 0 12px;
  box-sizing: border-box;
  border: 1px solid var(--circle-border-soft, #e2e8f0);
  border-radius: 10px;
  background: var(--circle-surface-elevated, #ffffff);
  color: var(--circle-text, #334155);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
  box-shadow: none;
  cursor: pointer;
  overflow: visible;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.release-sort-button:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: color-mix(in srgb, var(--circle-primary, #2563eb) 30%, transparent);
  color: var(--circle-primary, #1d4ed8);
  box-shadow: none;
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
  color: var(--circle-primary, #3b82f6);
}
.release-sort-icon.hover {
  opacity: 0;
  transform: translateY(5px) scale(0.72) rotate(-16deg);
}
.release-sort-icon.hover.asc {
  color: var(--circle-tag-success, #10b981);
}
.release-sort-icon.hover.desc {
  color: var(--circle-tag-orange, #f97316);
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
  flex-shrink: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.release-sort-direction.asc {
  color: var(--circle-tag-success, #10b981);
}
.release-sort-direction.desc {
  color: var(--circle-tag-orange, #f97316);
}
.release-sort-button:hover .release-sort-direction {
  transform: translateY(-1px) scale(1.12);
}
.view-toggle-group {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
  height: 30px;
  padding: 2px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 13px;
  background: rgba(20, 22, 26, 0.72);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 8px 18px rgba(0, 0, 0, 0.18);
}
.view-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: rgba(244, 244, 245, 0.66);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.view-toggle-btn:hover {
  color: #f4f4f5;
  background: rgba(244, 244, 245, 0.055);
  transform: translateY(-1px) scale(1.04);
}
.view-toggle-btn:active {
  transform: scale(0.94);
}
.view-toggle-btn.active {
  color: #f4f4f5;
  border-color: rgba(244, 244, 245, 0.16);
  background: linear-gradient(180deg, rgba(244, 244, 245, 0.060) 0%, rgba(244, 244, 245, 0.032) 100%);
  box-shadow:
    inset 0 1px 0 rgba(244, 244, 245, 0.07),
    0 6px 14px rgba(0, 0, 0, 0.20);
}
.view-toggle-btn.active:hover {
  color: #ffffff;
  border-color: rgba(244, 244, 245, 0.22);
}
:global(html.kikoerumanager-dark .circle-page .view-toggle-group),
:global(body.kikoerumanager-dark .circle-page .view-toggle-group),
:global(html.dark .circle-page .view-toggle-group),
:global(body.dark .circle-page .view-toggle-group),
:global(.kikoerumanager-dark .circle-page .view-toggle-group),
:global(.dark .circle-page .view-toggle-group) {
  background: rgba(20, 22, 26, 0.92);
  border-color: rgba(255, 255, 255, 0.10);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 8px 18px rgba(0, 0, 0, 0.22);
}
:global(html.kikoerumanager-dark .circle-page .view-toggle-btn.active),
:global(body.kikoerumanager-dark .circle-page .view-toggle-btn.active),
:global(html.dark .circle-page .view-toggle-btn.active),
:global(body.dark .circle-page .view-toggle-btn.active),
:global(.kikoerumanager-dark .circle-page .view-toggle-btn.active),
:global(.dark .circle-page .view-toggle-btn.active) {
  color: #f4f4f5 !important;
  background: linear-gradient(180deg, rgba(244, 244, 245, 0.060) 0%, rgba(244, 244, 245, 0.032) 100%) !important;
  border-color: rgba(244, 244, 245, 0.16) !important;
  box-shadow:
    inset 0 1px 0 rgba(244, 244, 245, 0.07),
    0 6px 14px rgba(0, 0, 0, 0.20) !important;
}
.circle-list {
  display: grid;
  gap: 6px;
  padding: 8px 6px 8px 2px;
  min-height: 0;
  max-height: none;
  /* 数量少时不要被 1fr 行拉伸，按内容高度堆在顶部 */
  align-content: start;
  grid-auto-rows: max-content;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  /* 只保留底部滚动暗示，避免第一张卡片被顶部遮罩吃掉 */
  mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 14px), transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 14px), transparent 100%);
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
  background: var(--circle-surface-elevated, #fff);
  text-align: left;
  cursor: pointer;
  position: relative;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.circle-list-item.has-new-work {
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 18%, var(--circle-border-soft, #e2e8f0));
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--circle-tag-success, #059669) 3%, transparent), transparent 48%),
    var(--circle-surface-elevated, #fff);
}
.circle-list-item:hover {
  background: var(--circle-hover-bg, #ffffff);
  border-color: var(--circle-border-strong, #cbd5e1);
  box-shadow: var(--circle-shadow-lift, 0 8px 16px rgba(0,0,0,0.08));
  transform: translateY(-3px);
}
.circle-list-item.has-new-work:hover {
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--circle-tag-success, #059669) 5%, transparent), transparent 52%),
    var(--circle-hover-bg, #ffffff);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 28%, var(--circle-border-strong, #cbd5e1));
}
.circle-list-item.active {
  background: var(--circle-selected-bg, #eff6ff);
  border-color: var(--circle-primary, #3b82f6);
  box-shadow: 0 4px 12px color-mix(in srgb, var(--circle-primary, #3b82f6) 22%, transparent);
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
.circle-list-item.has-new-work .circle-list-header {
  padding-left: 0;
}
.circle-list-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--circle-text-strong, #111827);
  line-height: 1.4;
  white-space: nowrap;
  overflow: visible;
  text-overflow: ellipsis;
  flex: 1;
}
.circle-list-name-shell {
  position: relative;
  display: inline-block;
  max-width: 100%;
  min-width: 0;
  padding-top: 9px;
  vertical-align: top;
}
.circle-list-name-shell.has-title-new-badge {
  padding-right: 30px;
}
.circle-list-name-text {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.circle-title-new-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: absolute;
  top: -1px;
  right: 0;
  height: 12px;
  padding: 0 4px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--circle-tag-success, #059669) 26%, transparent);
  background: color-mix(in srgb, var(--circle-tag-success, #059669) 10%, var(--circle-surface-elevated, #fff));
  color: color-mix(in srgb, var(--circle-tag-success, #059669) 88%, var(--circle-text-strong, #111827));
  font-size: 7px;
  font-weight: 850;
  line-height: 1;
  letter-spacing: .04em;
  pointer-events: none;
}
.circle-list-id {
  font-size: 11px;
  font-weight: 600;
  color: var(--circle-text-muted, #64748b);
  background: color-mix(in srgb, var(--circle-surface-soft, #f1f5f9) 58%, transparent);
  border: 1px solid var(--circle-border-soft, transparent);
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
  border: 1px solid var(--circle-label-border, transparent);
  background: var(--circle-label-surface, transparent);
}
.circle-list-tag.unreleased {
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 8%, transparent);
  color: var(--circle-tag-primary, #2563eb);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 22%, transparent);
}
.circle-list-tag.new-work {
  background: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 8%, transparent);
  color: var(--circle-tag-orange, #ea580c);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 20%, transparent);
}
.circle-list-refresh-row {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 5px;
  font-size: 10px;
  color: var(--circle-text-muted, rgba(100, 116, 139, 0.78));
  font-weight: 500;
}
.circle-list-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.circle-list-meta {
  margin-top: 6px;
  font-size: 10px;
  color: var(--circle-text-subtle, #94a3b8);
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
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  border: 1px solid var(--circle-label-border, transparent);
  background: var(--circle-label-surface, transparent);
}

.circle-list-status-pill.completed {
  color: var(--circle-tag-success, #047857);
  background: color-mix(in srgb, var(--circle-tag-success, #10b981) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-success, #10b981) 22%, transparent);
}

.circle-list-status-pill.incomplete {
  color: var(--circle-tag-danger, #b91c1c);
  background: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 22%, transparent);
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
  color: var(--circle-text, #374151);
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

.circle-stat-dot.total::before { background: var(--circle-tag-primary, #3b82f6); }
.circle-stat-dot.owned::before { background: var(--circle-tag-success, #10b981); }
.circle-stat-dot.missing::before { background: var(--circle-tag-danger, #ef4444); }
.circle-stat-dot.missing { color: var(--circle-tag-danger, #ef4444); }

/* icon 版侧边栏统计（当前使用） */
.circle-stat-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 5px;
  border: 1px solid var(--circle-label-border, transparent);
  background: var(--circle-label-surface, transparent);
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
  color: var(--circle-tag-primary, #2563eb);
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 20%, transparent);
}
.circle-stat-item.owned {
  color: var(--circle-tag-success, #059669);
  background: color-mix(in srgb, var(--circle-tag-success, #059669) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 20%, transparent);
}
.circle-stat-item.missing {
  color: var(--circle-tag-danger, #dc2626);
  background: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 20%, transparent);
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
  background: var(--circle-border-soft, #e5e7eb);
  overflow: hidden;
}

.circle-list-progress-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--circle-tag-success, #10b981);
  transition: width 0.4s ease;
}

.circle-list-percent {
  font-size: 11px;
  font-weight: 700;
  color: var(--circle-text-subtle, #9ca3af);
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
  border-radius: 5px;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
  line-height: 1;
  background: var(--circle-label-surface, var(--circle-surface-soft, #f3f4f6));
  color: var(--circle-text-muted, #6b7280);
  border: 1px solid var(--circle-label-border, var(--circle-border-soft, #e5e7eb));
}

.circle-tab-badge.missing {
  background: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 8%, transparent);
  color: var(--circle-tag-danger, #dc2626);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #dc2626) 22%, transparent);
}

.circle-tab-badge.owned {
  background: color-mix(in srgb, var(--circle-tag-success, #059669) 8%, transparent);
  color: var(--circle-tag-success, #059669);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 22%, transparent);
}
.works-card {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 8px;
}
.selection-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 4px 0 8px;
  padding: 8px 12px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.8));
  border-radius: 12px;
  background: var(--circle-surface-muted, rgba(248, 250, 252, 0.8));
  box-shadow: var(--circle-shadow-soft, 0 1px 2px rgba(15, 23, 42, 0.04));
  backdrop-filter: blur(10px);
}
.selection-count {
  font-size: 14px;
  font-weight: 700;
  color: var(--circle-text, #334155);
}
.owned-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  border: 1px dashed var(--circle-border-soft, rgba(226, 232, 240, 0.5));
  border-radius: 12px;
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 56%, transparent);
  color: var(--circle-text-subtle, #94a3b8);
}
.batch-action-button {
  min-width: 100px;
  height: 34px;
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--circle-border-soft, #e2e8f0);
  background: var(--circle-surface-elevated, #ffffff);
  color: var(--circle-text, #475569);
  border-radius: 8px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.batch-action-button:not(.primary):not(.refresh):not(.bonus-refresh):not(.ghost):hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: var(--circle-hover-bg, #f8fafc);
  border-color: var(--circle-border-strong, #cbd5e1);
  color: var(--circle-text-strong, #1e293b);
  box-shadow: var(--circle-shadow-lift, 0 6px 15px rgba(0, 0, 0, 0.08));
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
  --el-button-text-color: #ffffff;
  --el-button-hover-text-color: #ffffff;
  --el-button-active-text-color: #ffffff;
  background: linear-gradient(135deg, color-mix(in srgb, var(--circle-primary, #3b82f6) 88%, #ffffff) 0%, var(--circle-primary, #2563eb) 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--circle-primary, #2563eb) 24%, transparent);
}
.batch-action-button.primary:hover:not(:disabled) {
  background: linear-gradient(135deg, color-mix(in srgb, var(--circle-primary, #60a5fa) 70%, #ffffff) 0%, var(--circle-primary, #3b82f6) 100%);
  box-shadow: 0 8px 20px color-mix(in srgb, var(--circle-primary, #2563eb) 30%, transparent);
}
.batch-action-button.refresh {
  --el-button-text-color: #ffffff;
  --el-button-hover-text-color: #ffffff;
  --el-button-active-text-color: #ffffff;
  background: var(--circle-selected-strong-bg, linear-gradient(135deg, #334155 0%, #0f172a 100%));
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.2);
}
.batch-action-button.refresh:hover:not(:disabled) {
  background: var(--circle-selected-strong-bg, #1e293b);
  filter: brightness(1.08);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.3);
}
.batch-action-button.bonus-refresh {
  --el-button-text-color: #ffffff;
  --el-button-hover-text-color: #ffffff;
  --el-button-active-text-color: #ffffff;
  background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px rgba(109, 40, 217, 0.24);
}
.batch-action-button.bonus-refresh:hover:not(:disabled) {
  background: linear-gradient(135deg, #a78bfa 0%, #7c3aed 100%);
  box-shadow: 0 8px 20px rgba(109, 40, 217, 0.32);
}
.batch-action-button.ghost {
  background: transparent;
  border: 1px dashed var(--circle-border-strong, #cbd5e1);
  color: var(--circle-text-muted, #64748b);
  box-shadow: none;
}
.batch-action-button.ghost:hover:not(:disabled) {
  background: var(--circle-hover-bg, #f1f5f9);
  border-style: solid;
  border-color: var(--circle-border-strong, #94a3b8);
  color: var(--circle-text, #334155);
}
:global(html.kikoerumanager-dark .circle-page .selection-bar),
:global(body.kikoerumanager-dark .circle-page .selection-bar) {
  background: rgba(255, 255, 255, 0.045);
  border-color: rgba(255, 255, 255, 0.10);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 14px 28px rgba(0, 0, 0, 0.22);
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button),
:global(body.kikoerumanager-dark .circle-page .batch-action-button) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.070) 0%, rgba(255, 255, 255, 0.045) 100%) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: rgba(244, 244, 245, 0.88) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 18px rgba(0, 0, 0, 0.18) !important;
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button:not(.primary):not(.refresh):not(.bonus-refresh):not(.ghost):hover:not(:disabled)),
:global(body.kikoerumanager-dark .circle-page .batch-action-button:not(.primary):not(.refresh):not(.bonus-refresh):not(.ghost):hover:not(:disabled)) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.11) 0%, rgba(255, 255, 255, 0.065) 100%) !important;
  border-color: rgba(255, 255, 255, 0.20) !important;
  color: #ffffff !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 12px 24px rgba(0, 0, 0, 0.26) !important;
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button.refresh),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.refresh),
:global(html.kikoerumanager-dark .circle-page .batch-action-button.bonus-refresh),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.bonus-refresh),
:global(html.kikoerumanager-dark .circle-page .batch-action-button.primary),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.primary) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.13) 0%, rgba(255, 255, 255, 0.075) 100%) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  color: #ffffff !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 10px 22px rgba(0, 0, 0, 0.24) !important;
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button.refresh:hover:not(:disabled)),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.refresh:hover:not(:disabled)),
:global(html.kikoerumanager-dark .circle-page .batch-action-button.bonus-refresh:hover:not(:disabled)),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.bonus-refresh:hover:not(:disabled)),
:global(html.kikoerumanager-dark .circle-page .batch-action-button.primary:hover:not(:disabled)),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.primary:hover:not(:disabled)) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0.10) 100%) !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  filter: none;
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button.ghost),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.ghost) {
  background: rgba(255, 255, 255, 0.035) !important;
  border: 1px dashed rgba(255, 255, 255, 0.18) !important;
  color: rgba(244, 244, 245, 0.74) !important;
  box-shadow: none !important;
}
:global(html.kikoerumanager-dark .circle-page .batch-action-button.ghost:hover:not(:disabled)),
:global(body.kikoerumanager-dark .circle-page .batch-action-button.ghost:hover:not(:disabled)) {
  background: rgba(255, 255, 255, 0.075) !important;
  border-style: solid !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
  color: #ffffff !important;
}
@keyframes batchActionSpin {
  to { transform: rotate(360deg); }
}

.circle-tabs-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.circle-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.circle-tabs-wrapper .toolbar-right-actions {
  position: absolute;
  top: 3px;
  right: 0;
  z-index: 10;
  height: 30px; /* 给顶部 hover / scale 动效留出不被裁切的安全边界 */
  display: flex;
  align-items: center;
  overflow: visible;
}
.circle-tabs :deep(.el-tabs__nav-wrap) {
  padding-right: 344px; /* 为排序、状态筛选、视图切换留出空间 */
}
.circle-tabs-wrapper.has-owned-search .circle-tabs :deep(.el-tabs__nav-wrap) {
  padding-right: 610px;
}
.circle-tabs :deep(.el-tabs__header) {
  margin: 0 0 8px;
  padding-top: 0;
}
.circle-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.circle-tabs :deep(.el-tabs__item) {
  height: 34px;
  font-weight: 800;
  color: var(--circle-text-muted, #60748d);
}
.circle-tabs :deep(.el-tabs__item.is-active) {
  color: var(--circle-primary, #2d6ec0);
}
.circle-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-top: 0;
}
.circle-tabs :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  padding: 2px 0 4px;
}
.info-card {
  position: relative;
  min-width: 0;
  min-height: 96px;
  display: grid;
  align-content: space-between;
  gap: 14px;
  padding: 16px 18px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.72));
  border-radius: 12px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--circle-surface-elevated, #ffffff) 96%, transparent) 0%, color-mix(in srgb, var(--circle-surface-soft, #f8fafc) 82%, transparent) 100%);
  box-shadow: var(--circle-shadow-soft, 0 1px 2px rgba(15, 23, 42, 0.04));
  overflow: hidden;
}
.info-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, var(--circle-text-subtle, #94a3b8), transparent);
  opacity: 0.45;
}
.info-label {
  color: var(--circle-text-subtle, #94a3b8);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.info-value {
  min-width: 0;
  color: var(--circle-text-strong, #111827);
  font-size: 18px;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
:global(html.kikoerumanager-dark .circle-page .info-card),
:global(body.kikoerumanager-dark .circle-page .info-card) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.060) 0%, rgba(255, 255, 255, 0.035) 100%);
  border-color: rgba(255, 255, 255, 0.10);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 12px 26px rgba(0, 0, 0, 0.20);
}
:global(html.kikoerumanager-dark .circle-page .info-card::before),
:global(body.kikoerumanager-dark .circle-page .info-card::before) {
  background: linear-gradient(90deg, rgba(244, 244, 245, 0.34), transparent);
}
:global(html.kikoerumanager-dark .circle-page .info-label),
:global(body.kikoerumanager-dark .circle-page .info-label) {
  color: rgba(212, 212, 216, 0.62);
}
:global(html.kikoerumanager-dark .circle-page .info-value),
:global(body.kikoerumanager-dark .circle-page .info-value) {
  color: rgba(255, 255, 255, 0.94);
}
.owned-panel {
  position: relative;
  z-index: 30;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.owned-stats-strip,
.compare-stats-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  overflow: hidden;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
  border-radius: 12px;
  background: var(--circle-surface-elevated, #ffffff);
  box-shadow: var(--circle-shadow-soft, 0 1px 2px rgba(15, 23, 42, 0.04));
}
.owned-stats-strip {
  flex: 0 1 auto;
  justify-content: space-between;
  min-width: 0;
  width: fit-content;
  max-width: 100%;
  min-height: 36px;
  padding: 3px 4px;
}
.owned-stats-list {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  min-width: 0;
  gap: 2px;
  overflow-x: auto;
  scrollbar-width: none;
}
.owned-stats-list::-webkit-scrollbar {
  display: none;
}
.owned-stat-item,
.compare-stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  min-width: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
}
.owned-stat-item > .flex.flex-col {
  flex-direction: row;
  align-items: baseline;
  gap: 4px;

}
.owned-stat-item {
  min-height: 30px;
  border-radius: 8px;
  cursor: pointer;
  transition: all .22s cubic-bezier(.34, 1.56, .64, 1);
}
.owned-stat-item:hover {
  background: var(--circle-hover-bg, rgba(248, 250, 252, .92));
  transform: translateY(-1px);

}
.owned-stat-item:active {
  transform: scale(.96);

}
.owned-stat-item:focus,
.owned-stat-item:focus-visible {
  outline: none;
  box-shadow: none;

}
.owned-stat-item.is-active {
  background: var(--circle-surface, rgba(255, 255, 255, .96));
  color: var(--circle-text-strong, #0f172a);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--circle-surface, #fff) 70%, transparent),
    0 4px 12px rgba(15, 23, 42, .08);

}
.owned-stat-item.is-simplified.is-active {
  color: var(--circle-tag-sky, #0369a1);
  background: var(--circle-tag-sky-soft, rgba(240, 249, 255, .78));

}
.owned-stat-item.is-traditional.is-active,
.owned-stat-item.is-bonus.is-active {
  color: var(--circle-tag-violet, #6d28d9);
  background: var(--circle-tag-violet-soft, rgba(245, 243, 255, .68));

}
.owned-stat-item.is-original.is-active {
  color: var(--circle-text-strong, #111827);
  background: color-mix(in srgb, var(--circle-text-strong, #111827) 7%, transparent);

}
.owned-stat-item.is-subtitle.is-active {
  color: var(--circle-tag-indigo, #4338ca);
  background: var(--circle-tag-indigo-soft, rgba(238, 242, 255, .72));

}
.owned-stat-item + .owned-stat-item,
.compare-stat-item + .compare-stat-item {
  border-left: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
}
.owned-stat-icon,
.compare-stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.5));
  background: var(--circle-surface-soft, #f8fafc);
  color: var(--circle-text-muted, #64748b);
}
.owned-stat-icon.is-simplified,
.compare-stat-icon.is-dlsite {
  background: var(--circle-tag-sky-soft, #f0f9ff);
  color: var(--circle-tag-sky, #0284c7);
  border-color: color-mix(in srgb, var(--circle-tag-sky, #0284c7) 20%, transparent);
}
.owned-stat-icon.is-traditional,
.owned-stat-icon.is-bonus,
.compare-stat-icon.is-asmr {
  background: var(--circle-tag-violet-soft, #faf5ff);
  color: var(--circle-tag-violet, #7e22ce);
  border-color: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 20%, transparent);
}
.owned-stat-icon.is-subtitle {
  background: var(--circle-tag-indigo-soft, #eef2ff);
  color: var(--circle-tag-indigo, #4f46e5);
  border-color: color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 20%, transparent);
}
.compare-stat-icon.is-kikoeru {
  background: var(--circle-tag-success-soft, #ecfdf5);
  color: var(--circle-tag-success, #059669);
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 20%, transparent);
}
.compare-stat-icon.is-missing {
  background: var(--circle-tag-rose-soft, #fff1f2);
  color: var(--circle-tag-rose, #e11d48);
  border-color: color-mix(in srgb, var(--circle-tag-rose, #e11d48) 20%, transparent);
}
.owned-stat-label,
.compare-stat-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--circle-text-subtle, #94a3b8);
  text-transform: none;
}
.owned-stat-value,
.compare-stat-value {
  font-size: 13px;
  font-weight: 800;
  color: var(--circle-text-strong, #111827);
  line-height: 1;
}
.owned-search-wrap,
.compare-search-wrap {
  position: relative;
  width: 236px;
}
.owned-search-wrap--top {
  flex: 0 0 250px;
  width: 250px;
  height: 30px;
  align-self: center;
}
 .owned-search-wrap--top .owned-search-input {
  height: 30px;
  min-height: 30px;
  padding-top: 0;
  padding-bottom: 0;
  box-sizing: border-box;
 }
 .owned-search-wrap--top .owned-search-icon,
 .owned-search-wrap--top .owned-search-clear {
  height: 30px;
 }
.owned-search-icon,
.compare-search-icon {
  position: absolute;
  inset: 0 auto 0 0;
  display: flex;
  align-items: center;
  padding-left: 12px;
  color: var(--circle-text-subtle, #94a3b8);
  pointer-events: none;
}
.owned-search-input,
.compare-search-input {
  display: block;
  width: 100%;
  min-height: 32px;
  padding: 6px 32px 6px 34px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
  border-radius: 10px;
  background: var(--circle-field-bg, #ffffff);
  color: var(--circle-text-strong, #111827);
  font-size: 13px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.owned-search-input::placeholder,
.compare-search-input::placeholder {
  color: var(--circle-placeholder, #94a3b8);
}
.owned-search-input:focus,
.compare-search-input:focus {
  outline: none;
  border-color: var(--circle-primary, #2563eb);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--circle-primary, #2563eb) 14%, transparent);
}
.owned-search-clear,
.compare-search-clear {
  position: absolute;
  inset: 0 0 0 auto;
  display: flex;
  align-items: center;
  padding-right: 12px;
  color: var(--circle-text-subtle, #94a3b8);
  transition: color 0.2s ease, transform 0.2s ease;
}
.owned-search-clear:hover,
.compare-search-clear:hover {
  color: var(--circle-text, #334155);
  transform: scale(1.08);
}
.compare-filter-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
  border-radius: 10px;
  background: var(--circle-surface-elevated, #ffffff);
  box-shadow: var(--circle-shadow-soft, 0 1px 2px rgba(15, 23, 42, 0.04));
}
.compare-filter-chip {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--circle-text, #475569);
  font-size: 14px;
  font-weight: 700;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.compare-filter-chip:hover {
  transform: translateY(-1px);
  background: var(--circle-hover-bg, rgba(248, 250, 252, 0.9));
  color: var(--circle-text-strong, #111827);
}
.compare-filter-chip.is-active {
  background: var(--circle-selected-strong-bg, #0f172a);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
}
.compare-filter-chip.is-kikoeru.is-active {
  background: linear-gradient(135deg, color-mix(in srgb, var(--circle-tag-success, #059669) 82%, #ffffff) 0%, var(--circle-tag-success, #059669) 100%);
}
.compare-filter-chip.is-asmr.is-active {
  background: linear-gradient(135deg, color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 82%, #ffffff) 0%, var(--circle-tag-indigo, #4f46e5) 100%);
}

.compare-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
  border-radius: 10px 10px 0 0;
  background: var(--circle-surface-soft, #f8fafc);
  color: var(--circle-text-muted, #64748b);
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}
.compare-head-main {
  flex: 1;
  min-width: 0;
}
.compare-head-sources {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  text-align: center;
}
.compare-source-col {
  width: 80px;
}
.compare-works-list {
  margin-bottom: 16px;
  border: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.6));
  border-top: 0;
  border-radius: 0 0 10px 10px;
  background: var(--circle-surface-elevated, #ffffff);
  overflow: hidden;
  contain: layout paint;
  isolation: isolate;
}
.compare-work-item {
  padding: 16px;
  color: var(--circle-text, #334155);
  backface-visibility: hidden;
  transform: translateZ(0);
  will-change: transform, opacity;
  transition: background-color 0.2s ease;
}
.compare-work-item + .compare-work-item {
  border-top: 1px solid var(--circle-border-soft, rgba(226, 232, 240, 0.7));
}
.compare-work-item:hover {
  background: var(--circle-hover-bg, rgba(248, 250, 252, 0.5));
}
.compare-work-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.compare-work-rj {
  font-weight: 800;
  color: var(--circle-text-strong, #223754);
}
.compare-work-title {
  margin: 0 0 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--circle-text-strong, #24364f);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.55;
}
.compare-work-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--circle-text-muted, #7b8797);
}
.compare-status-inline {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--circle-text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
}
.compare-status-inline.is-owned {
  color: var(--circle-tag-success, #059669);
}
.compare-status-inline.is-missing {
  color: var(--circle-tag-rose, #e11d48);
}
.compare-status-inline.is-partial {
  color: var(--circle-tag-warning, #d97706);
}
.compare-work-code,
.compare-source-code {
  color: var(--circle-text, #475569);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  font-weight: 700;
}
.compare-source-empty {
  color: var(--circle-text-subtle, #94a3b8);
  transform: scale(0.9);
}
.compare-variant-badge,
.compare-source-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--circle-label-border, #e2e8f0);
  border-radius: 5px;
  background: var(--circle-label-surface, #f8fafc);
  color: var(--circle-text-muted, #64748b);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
}
.compare-variant-badge {
  padding: 3px 6px;
}
.compare-source-badge {
  padding: 2px 4px;
  font-size: 9px;
}
.compare-variant-badge.is-simplified,
.compare-source-badge.is-simplified {
  background: color-mix(in srgb, var(--circle-tag-sky, #0284c7) 8%, transparent);
  color: var(--circle-tag-sky, #0284c7);
  border-color: color-mix(in srgb, var(--circle-tag-sky, #0284c7) 22%, transparent);
}
.compare-variant-badge.is-traditional,
.compare-source-badge.is-traditional {
  background: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 8%, transparent);
  color: var(--circle-tag-violet, #7e22ce);
  border-color: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 22%, transparent);
}
.compare-variant-badge.is-original,
.compare-source-badge.is-original {
  background: var(--circle-label-surface, #f1f5f9);
  color: var(--circle-text, #475569);
  border-color: var(--circle-label-border, #e2e8f0);
}
.compare-variant-badge.is-subtitle {
  background: color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 8%, transparent);
  color: var(--circle-tag-indigo, #4f46e5);
  border-color: color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 22%, transparent);
}
.compare-source-divider {
  width: 1px;
  height: 24px;
  background: var(--circle-border-soft, rgba(226, 232, 240, 0.6));
}
.compare-source-divider.is-transparent {
  background: transparent;
}
.compare-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border: 1px solid var(--circle-label-border, transparent);
  border-radius: 5px;
  background: var(--circle-label-surface, transparent);
  font-size: 11px;
  font-weight: 800;
}
.compare-status-pill.is-owned {
  background: color-mix(in srgb, var(--circle-tag-primary, #005fcc) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #005fcc) 22%, transparent);
  color: var(--circle-tag-primary, #005fcc);
}
.compare-status-pill.is-downloadable {
  background: color-mix(in srgb, var(--circle-tag-success, #248a3d) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-success, #248a3d) 22%, transparent);
  color: var(--circle-tag-success, #248a3d);
}
.compare-status-pill.is-dl_only {
  background: color-mix(in srgb, var(--circle-tag-orange, #c2410c) 8%, transparent);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #c2410c) 22%, transparent);
  color: var(--circle-tag-orange, #c2410c);
}
@media (max-width: 1100px) {
  .circle-shell {
    grid-template-columns: 1fr;
  }
  .index-progress-head {
    flex-direction: column;
    align-items: stretch;
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
 *   .circle-tabs 全都 flex:1 + min-height:0。
 *   移动端这种嵌套 flex:1 结构会导致内容只分到一小部分高度，
 *   并出现外层手势划不动的问题。
 *   解法（与 Conflicts.vue / SubtitleImport.vue 一致）：
 *     - 整页 stream 模式：解锁 .circle-page 高度，让外层 .content-shell 滚
 *     - 内部 flex:1 全部改 flex:0 0 auto，overflow 全部 visible
 *     - 作品视口自然撑开，跟着整页一起滚
 *
 * 其他视觉痛点（顺带）：
 *   - circle-page-header / index-progress-card margin & padding 太大
 *   - sidebar-card padding 20/16 浪费空间，circle-list 限高 320 防侧栏吃满
 *   - toolbar-right-actions absolute 在移动会重叠 tabs 标签
 *   - view-toggle-group / release-sort-button 在窄屏挤压
 *   - compare-head / compare-row 4 列横向溢出，改 1 列 stack
 * ============================================================ */
@media (max-width: 640px) {
  /* ============================================================
   * 关键：整页 stream 模式 — 解锁外层 .circle-page 与内部所有 flex:1 容器
   * 让作品视口自然撑开，由 App 外层滚动容器（.content-shell）统一滚
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
  .view-toggle-group { margin-left: auto; }
  .view-toggle-btn { padding: 4px 6px; }

  /* works-card padding 紧凑 */
  .works-card { padding: 12px; gap: 10px; }

  .circle-complete-state {
    min-height: 260px;
    padding: 16px 10px;
  }
  .circle-complete-visual {
    width: min(220px, 72vw);
  }
  .circle-complete-image {
    max-width: min(220px, 72vw, 36vh);
  }
  .circle-complete-pill {
    min-height: 24px;
    padding: 0 9px;
    font-size: 11px;
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
    background: var(--circle-surface-soft, rgba(248, 250, 252, 0.72));
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
    background: var(--circle-surface-soft, rgba(248, 250, 252, 0.72));
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
    background: var(--circle-surface-soft, rgba(248, 250, 252, 0.86));
    overflow: hidden;
  }
  .compare-source-cols span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* works-pager 居中 */
  .works-pager { justify-content: center; }

  .compare-head { display: none !important; }

  /* hero-search-wrap：移动端独占整行（已在 index.css 全局规则，但 padding 微调更紧） */
  .hero-search-wrap {
    width: 100%;
  }
}
</style>
