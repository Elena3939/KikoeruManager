<template>
  <div class="circle-page">
    <section class="circle-hero relative overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-white border-b border-blue-100/50">
      <!-- Background Decorations (Optimized with radial gradients instead of expensive CSS blur) -->
      <div class="absolute top-0 right-0 -mt-20 -mr-20 w-96 h-96 pointer-events-none" style="background: radial-gradient(circle, rgba(96, 165, 250, 0.15) 0%, transparent 70%);"></div>
      <div class="absolute bottom-0 left-10 -mb-20 w-72 h-72 pointer-events-none" style="background: radial-gradient(circle, rgba(129, 140, 248, 0.15) 0%, transparent 70%);"></div>

      <div class="hero-copy relative z-10">
        <div class="hero-eyebrow inline-flex items-center px-3 py-1 rounded-full bg-blue-100/90 text-blue-700 text-xs font-bold tracking-wider mb-4 border border-blue-200/50 shadow-sm">
          <span class="w-1.5 h-1.5 rounded-full bg-blue-500 mr-2 animate-pulse"></span>
          Circle Completion
        </div>
        <h1 class="text-4xl md:text-5xl font-extrabold text-slate-800 tracking-tight mb-4 drop-shadow-sm">社团补全</h1>
        <p class="text-slate-600 text-base md:text-lg leading-relaxed max-w-2xl mb-6">
          按社团建立索引，以 <span class="font-semibold text-slate-700">Kikoeru 服务器是否已收录</span>作为缺失判断，再结合 <span class="font-semibold text-blue-600">DLsite 关联链</span>和 <span class="font-semibold text-emerald-600">asmr.one 下载能力</span>，把真正缺的作品批量送进下载队列。
        </p>
        <div class="hero-inline-metrics flex flex-wrap gap-3">
          <span class="hero-inline-pill flex items-center px-3 py-1.5 bg-white/95 border border-slate-200/60 rounded-lg text-xs font-medium text-slate-600 shadow-sm hover:shadow hover:-translate-y-0.5 transition-all cursor-default">
            <LibraryBig :size="14" class="mr-1.5 text-blue-500" />
            索引优先复用现有社团
          </span>
          <span class="hero-inline-pill flex items-center px-3 py-1.5 bg-white/95 border border-slate-200/60 rounded-lg text-xs font-medium text-slate-600 shadow-sm hover:shadow hover:-translate-y-0.5 transition-all cursor-default">
            <CheckCircle2 :size="14" class="mr-1.5 text-emerald-500" />
            下载后自动按社团入库
          </span>
          <span class="hero-inline-pill flex items-center px-3 py-1.5 bg-white/95 border border-slate-200/60 rounded-lg text-xs font-medium text-slate-600 shadow-sm hover:shadow hover:-translate-y-0.5 transition-all cursor-default">
            <PlayCircle :size="14" class="mr-1.5 text-indigo-500" />
            仅蓝色操作可交互
          </span>
        </div>
      </div>
      <div class="hero-actions relative z-10 bg-white/90 p-3 rounded-2xl shadow-sm border border-white/60 flex items-center gap-3">
        <div class="relative flex-1">
          <Search :size="18" class="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <el-input
            v-model="circleQuery"
            class="hero-search-input !bg-transparent"
            placeholder="输入社团名，例如 こぐま座 / C_Realization"
            clearable
            @keyup.enter="handleIndexCircle"
          />
        </div>
        <el-button class="hero-search-button !h-11 !rounded-xl !px-6 !font-bold shadow-md hover:shadow-lg transition-all" type="primary" :loading="indexing" @click="handleIndexCircle">建立 / 刷新索引</el-button>
        <el-button class="batch-action-button !h-11 !rounded-xl !px-5 !font-bold" :disabled="indexing" @click="openBatchIndexPrompt">批量建立</el-button>
      </div>
    </section>

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

      <AppLottieProgressBar :percentage="getJobProgressPercent(indexJob)" />

      <div class="index-progress-meta">
        <span class="progress-meta-pill">耗时 {{ formatElapsed(indexJob.elapsed_seconds) }}</span>
        <span v-if="indexJob.meta?.is_batch" class="progress-meta-pill">{{ indexJob.meta.completed_queries || 0 }}/{{ indexJob.meta.batch_total || 0 }} 已完成</span>
        <span v-if="indexJob.meta?.is_batch && indexJob.meta.failed_queries" class="progress-meta-pill warn">失败 {{ indexJob.meta.failed_queries }}</span>
        <span class="progress-meta-pill">本地 {{ indexJob.meta.local_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">Kikoeru {{ indexJob.meta.kikoeru_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">DLsite {{ indexJob.meta.dlsite_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">候选 {{ indexJob.meta.combined_candidates_count || indexJob.meta.aggregated_count || 0 }}</span>
        <span class="progress-meta-pill ok">可下载 {{ indexJob.meta.asmr_available_count || 0 }}</span>
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
          <div v-if="circleList.length" class="circle-list">
            <button
              v-for="circle in circleList"
              :key="circle.circle_id"
              type="button"
              class="circle-list-item"
              :class="{ active: activeCircleId === circle.circle_id }"
              @click="selectCircle(circle.circle_id)"
            >
              <div class="circle-list-topline">{{ circle.circle_id }}</div>
              <div class="circle-list-name">{{ circle.circle_name || circle.circle_id }}</div>
              <div class="circle-list-meta">
                <span>{{ formatDateTime(circle.last_indexed_at) }}</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="还没有社团索引" :image-size="74" />
        </div>
      </aside>

      <main class="circle-main">
        <section class="toolbar-card">
          <div class="toolbar-main">
            <div class="toolbar-copy flex-1">
              <div class="flex items-center justify-between mb-1">
                <div class="flex items-center gap-3">
                  <div class="toolbar-title !text-xl">{{ detail.circle_name || '未选择社团' }}</div>
                  <div class="toolbar-subtitle flex items-center gap-2">
                    <span v-if="detail.last_indexed_at" class="text-xs text-slate-400">上次刷新 {{ formatDateTime(detail.last_indexed_at) }}</span>
                  </div>
                </div>
              </div>
              <div class="toolbar-metrics mt-3">
                <span class="metric-pill owned">服务器已有 {{ detail.owned_count || 0 }}</span>
                <span class="metric-pill warn">服务器缺失 {{ detail.missing_count || 0 }}</span>
                <span class="metric-pill ok">可下载 {{ detail.downloadable_count || 0 }}</span>
                <span class="metric-pill muted">暂不可下载 {{ detail.dl_only_count || 0 }}</span>
              </div>
            </div>
            <div v-if="detail.works?.length" class="toolbar-actions shrink-0 pl-6 flex flex-col gap-2">
              <div class="flex items-center gap-2 mt-auto">
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
              <div v-if="refreshForceRefreshHint" class="toolbar-subtext">{{ refreshForceRefreshHint }}</div>
            </div>
          </div>

          <div class="toolbar-filters mt-2 pt-1 flex items-center justify-between">
            <div class="flex items-center gap-4">
              <el-checkbox v-model="filters.onlyMissing" @change="refreshActiveCircle">仅看缺失</el-checkbox>
              <el-checkbox v-model="filters.onlyDownloadable" @change="refreshActiveCircle">仅看可下载</el-checkbox>
              <el-checkbox v-model="filters.includeDlOnly" @change="refreshActiveCircle">包含仅DL</el-checkbox>
            </div>
          </div>
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

            <AppLottieProgressBar :percentage="getJobProgressPercent(refreshJob)" />

            <div class="index-progress-meta">
              <span class="progress-meta-pill">耗时 {{ formatElapsed(refreshJob.elapsed_seconds) }}</span>
              <span class="progress-meta-pill">总数 {{ refreshJob.selected_count || refreshJob.meta.total_count || 0 }}</span>
              <span class="progress-meta-pill">已处理 {{ refreshJob.meta.processed_count || 0 }}</span>
              <span class="progress-meta-pill ok">有变化 {{ refreshJob.meta.changed_count || 0 }}</span>
              <span v-if="refreshJob.meta.force_refresh" class="progress-meta-pill warn">强制刷新</span>
              <span class="progress-meta-pill">Kikoeru {{ refreshJob.meta.kikoeru_owned_count || 0 }}</span>
              <span class="progress-meta-pill">asmr.one {{ refreshJob.meta.asmr_available_count || 0 }}</span>
              <span v-if="refreshJob.meta.current_rjcode" class="progress-meta-pill">当前 {{ refreshJob.meta.current_rjcode }}</span>
            </div>

            <div v-if="refreshJob.progress_log?.length" class="refresh-progress-log-list">
              <div
                v-for="entry in refreshJob.progress_log.slice(-6)"
                :key="`${refreshJob.job_id}-${entry.time}-${entry.message}`"
                class="refresh-progress-log-item"
                :class="entry.level || 'info'"
              >
                <span class="refresh-progress-log-time">{{ formatLogTime(entry.time) }}</span>
                <span class="refresh-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>

            <div v-if="refreshJob.error_message" class="index-progress-error">{{ refreshJob.error_message }}</div>
          </section>

          <el-tabs v-model="activeTab" class="circle-tabs">
            <el-tab-pane label="缺失作品" name="missing">
              <div v-if="missingWorks.length > 0" class="flex items-center justify-between bg-slate-50/80 border border-slate-200/80 rounded-xl px-4 py-3 mb-4 mt-2 shadow-sm backdrop-blur-sm">
                <div class="flex items-center gap-3">
                  <span class="text-sm font-bold text-slate-700 tracking-wide">批量操作</span>
                  <span class="text-xs font-semibold text-slate-500 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm">已选 {{ selectedCanonicalRJCodes.length }} / {{ missingWorks.length }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <el-button class="batch-action-button" size="small" @click="selectAllVisibleWorks">全选</el-button>
                  <el-button class="batch-action-button ghost" size="small" @click="clearSelection">清空</el-button>
                  <el-button class="batch-action-button primary ml-2" type="primary" size="small" :disabled="selectedDownloadableRJCodes.length === 0" :loading="previewing" @click="openBatchPreview()">下载选中项</el-button>
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
                    <span class="circle-complete-pill owned">服务器已收录 {{ detail.owned_count || 0 }}</span>
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
              <template v-else>
                <div class="work-grid">
                <article
                  v-for="item in pagedMissingWorks"
                  :key="item.canonical_rjcode"
                  class="work-card group flex flex-col"
                  :class="{ selected: selectedCanonicals.has(item.canonical_rjcode), 'is-downloaded': item.local_download_ready, 'status-flash': flashedWorkCodes.has(item.canonical_rjcode) }"
                  @click="toggleSelection(item)"
                >
                  <div class="work-cover-wrapper relative w-full aspect-[4/3] bg-slate-50 flex items-center justify-center border-b border-slate-100">
                    <img v-if="item.image_url" :src="item.image_url" class="work-cover w-full h-full object-contain bg-white transition-transform duration-500 group-hover:scale-105" referrerpolicy="no-referrer" />
                    <div v-else class="work-cover-placeholder w-full h-full flex items-center justify-center text-slate-300 bg-slate-50">
                      <LibraryBig :size="32" class="opacity-50" />
                    </div>
                    <div v-if="item.local_download_ready" class="work-corner-flag">已下载</div>
                    <div class="absolute inset-0 bg-gradient-to-t from-slate-900/10 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>
                  </div>

                  <div class="flex flex-col flex-1 p-3 gap-2.5">
                    <div class="work-card-head">
                      <div class="work-card-copy">
                        <div class="work-rj">{{ item.source_compare?.work_rjcode || item.canonical_rjcode }}</div>
                        <div class="work-title group-hover:text-blue-600 transition-colors" :title="item.title">{{ item.title || '未命名作品' }}</div>
                      </div>
                    </div>

                    <div class="work-linked">优先版本 {{ item.preferred_variant?.group_short_label || '原作' }} · {{ item.download_plan?.rjcode || item.display_rjcode || item.canonical_rjcode }}</div>

                    <div class="work-tags mt-auto pt-1">
                      <span v-if="item.local_download_ready" class="tag-chip is-success">已下载</span>
                      <span class="tag-chip" :class="item.server_owned ? 'is-primary' : 'is-danger'">{{ formatServerOwnedLabel(item) }}</span>
                      <span class="tag-chip is-info">DLsite {{ item.has_dlsite ? '有' : '未知' }}</span>
                      <span class="tag-chip" :class="item.has_asmr_one ? 'is-success' : 'is-disabled'">asmr.one {{ item.has_asmr_one ? '可下载' : '无资源' }}</span>
                    </div>

                    <div v-if="item.has_asmr_one || item.local_download_ready" class="work-actions mt-2">
                      <el-button v-if="item.local_download_ready" size="small" class="work-action-button upload" @click.stop="openReimportDialogForWork(item)">直接入库</el-button>
                      <el-button size="small" class="work-action-button" @click.stop="openBatchPreview(item.canonical_rjcode)">预览下载</el-button>
                    </div>
                  </div>
                </article>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="missingPage"
                  v-model:page-size="worksPageSize"
                  :page-sizes="worksPageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="missingWorks.length"
                  background
                />
              </div>
              </template>
            </el-tab-pane>

            <el-tab-pane label="服务器已拥有" name="owned">
              <!-- Header Stats & Actions -->
              <div class="mb-4 space-y-4">
                <div class="flex items-center justify-between bg-white rounded-xl border border-slate-200/60 p-1.5 shadow-sm">
                  <div class="flex items-center divide-x divide-slate-200/60">
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
                  </div>
                </div>

                <div class="flex items-center justify-between gap-4">
                  <div class="flex bg-white rounded-lg border border-slate-200/60 p-1 shadow-sm">
                    <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="ownedWorksFilterType === 'all' ? 'bg-slate-800 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="ownedWorksFilterType = 'all'">全部</button>
                    <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="ownedWorksFilterType === 'original' ? 'bg-slate-800 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="ownedWorksFilterType = 'original'">仅原作</button>
                    <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="ownedWorksFilterType === 'simplified' ? 'bg-sky-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="ownedWorksFilterType = 'simplified'">简中</button>
                    <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="ownedWorksFilterType === 'traditional' ? 'bg-violet-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="ownedWorksFilterType = 'traditional'">繁中</button>
                    <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5" :class="ownedWorksFilterType === 'subtitle' ? 'bg-indigo-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="ownedWorksFilterType = 'subtitle'">
                      <MessageSquareText :size="14" stroke-width="2.5" />
                      字幕
                    </button>
                  </div>
                  
                  <div class="relative w-64">
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

              <!-- List -->
              <div v-auto-animate class="grid grid-cols-1 xl:grid-cols-2 gap-3 pb-2 min-h-[300px] content-start">
                <div v-if="pagedOwnedWorks.length === 0" class="col-span-full flex flex-col items-center justify-center py-12 text-slate-400 bg-white/50 rounded-xl border border-slate-200/50 border-dashed">
                  <LibraryBig :size="32" class="mb-3 opacity-40" />
                  <p class="text-sm font-medium">没有找到符合条件的作品</p>
                </div>
                
                <article v-for="item in pagedOwnedWorks" :key="item.canonical_rjcode" class="group flex items-center justify-between p-3.5 rounded-xl border border-slate-200/60 bg-white hover:border-slate-300 hover:shadow-sm transition-all duration-200">
                  <div class="flex items-center gap-3.5 min-w-0">
                    <div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-50/80 border border-emerald-100/50 flex items-center justify-center text-emerald-500">
                      <CheckCircle2 :size="16" stroke-width="2" />
                    </div>
                    <div class="flex flex-col gap-0.5 min-w-0">
                      <h3 class="text-[14px] font-semibold text-slate-800 truncate" :title="item.title || item.canonical_rjcode">
                        {{ item.title || item.canonical_rjcode }}
                      </h3>
                      <div class="flex items-center gap-2 text-xs text-slate-500">
                        <span class="font-mono text-slate-500">{{ item.source_compare?.work_rjcode || item.canonical_rjcode }}</span>
                        <template v-if="true">
                          <span class="text-slate-300">•</span>
                          <span
                            class="inline-flex items-center px-1.5 py-0.5 rounded-md font-medium border"
                            :class="[
                              (item.preferred_variant?.group_short_label || '原作') === '简中' ? 'text-sky-600 bg-sky-50/80 border-sky-100/50' :
                              (item.preferred_variant?.group_short_label || '原作') === '繁中' ? 'text-violet-600 bg-violet-50/80 border-violet-100/50' :
                              (item.preferred_variant?.group_short_label || '原作') === '英' || (item.preferred_variant?.group_short_label || '原作') === '英文' ? 'text-rose-600 bg-rose-50/80 border-rose-100/50' :
                              'text-slate-500 bg-slate-100/50 border-slate-200/50'
                            ]"
                          >
                            {{ item.preferred_variant?.group_short_label || '原作' }}
                          </span>
                        </template>
                        <template v-if="(!item.preferred_variant?.group_short_label || item.preferred_variant?.group_short_label === '原作') && item.subtitle_present">
                          <span class="text-slate-300">•</span>
                          <span class="inline-flex items-center gap-1 text-indigo-600 bg-indigo-50/80 px-1.5 py-0.5 rounded-md font-medium border border-indigo-100/50">
                            <MessageSquareText :size="12" stroke-width="2.5" />
                            字幕
                          </span>
                        </template>
                      </div>
                    </div>
                  </div>
                  <div class="flex-shrink-0 ml-4 flex items-center">
                    <span class="inline-flex items-center px-2 py-1 rounded-md bg-emerald-50 text-emerald-600 text-[11px] font-medium border border-emerald-100/50">
                      已收录
                    </span>
                  </div>
                </article>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="ownedPage"
                  v-model:page-size="worksPageSize"
                  :page-sizes="worksPageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="ownedWorks.length"
                  background
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="来源对比" name="compare">
              <!-- Stats Row -->
              <div class="mb-4">
                <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden flex flex-wrap divide-x divide-slate-100">
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
              <div class="flex items-center justify-between mb-4">
                <div class="flex bg-white rounded-lg border border-slate-200/60 p-1 shadow-sm">
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'all' ? 'bg-slate-800 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'all'; comparePage = 1">全部</button>
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'kikoeru' ? 'bg-emerald-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'kikoeru'; comparePage = 1">已拥有(Kikoeru)</button>
                  <button type="button" class="px-3 py-1.5 rounded-md text-sm font-medium transition-all" :class="compareSourceFilter === 'asmr_one' ? 'bg-indigo-600 text-white shadow' : 'text-slate-600 hover:bg-slate-100/80'" @click="compareSourceFilter = 'asmr_one'; comparePage = 1">可下载(ASMR.ONE)</button>
                </div>
                
                <div class="relative w-64">
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

              <!-- Header -->
              <div class="flex items-center gap-4 px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 border border-slate-200/60 rounded-t-lg">
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
              <div class="border-x border-b border-slate-200/60 rounded-b-lg mb-4 divide-y divide-slate-100/80 bg-white" v-auto-animate>
                <div v-for="item in pagedCompareWorks" :key="`compare-${item.workRjcode}`" class="p-4 hover:bg-slate-50/50 transition-colors">
                  <div class="flex items-start justify-between gap-4">
                    <!-- Title & Badges -->
                    <div class="flex-1 min-w-0">
                      <h4 class="text-[14px] font-semibold text-slate-800 truncate mb-1.5" :title="item.title || item.workRjcode || '未命名作品'">{{ item.title || item.workRjcode || '未命名作品' }}</h4>
                      <div class="flex items-center gap-2">
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
                    <div class="flex items-center gap-4 text-xs shrink-0 mt-0.5">
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

            <el-tab-pane label="索引信息" name="info">
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
        </section>

        <el-empty v-else description="先建立一个社团索引" :image-size="86" />
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
    />

    <UploadTaskWorkbenchDialog
      v-model:visible="uploadWorkbenchVisible"
      :tasks="trackedUploadTasks"
      :refreshing="uploadWorkbenchRefreshing"
      @refresh="refreshUploadWorkbench"
      @background="hideUploadWorkbenchToBackground"
      @close="closeUploadWorkbench"
    />

    <div v-if="showDownloadBackgroundCard" class="circle-download-floating-card">
      <div class="circle-download-floating-head">
        <div>
          <div class="circle-download-floating-title">社团补全下载正在后台运行</div>
          <div class="circle-download-floating-mode">
            {{ activeBackgroundDownloadTask ? `${activeBackgroundDownloadTask.rjcode || 'RJ'} · ${activeBackgroundDownloadTask.work_title || activeBackgroundDownloadTask.source_label || '-'}` : '保留当前下载队列与进度状态' }}
          </div>
        </div>
        <div class="circle-download-floating-count">{{ backgroundDownloadPercent }}%</div>
      </div>
      <el-progress
        :percentage="backgroundDownloadPercent"
        :status="failedDownloadTasks.length && !processingDownloadTasks.length && !pendingDownloadTasks.length ? 'exception' : (completedDownloadTasks.length === trackedDownloadTasks.length && trackedDownloadTasks.length ? 'success' : '')"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="circle-download-floating-chip-row">
        <span class="circle-download-floating-chip">进行中 {{ processingDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip">等待中 {{ pendingDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip">完成 {{ completedDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip danger">失败 {{ failedDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip">速度 {{ formatSpeed(getDownloadSpeedBytes(activeBackgroundDownloadTask)) }}</span>
        <span class="circle-download-floating-chip">剩余 {{ formatDownloadTaskEta(activeBackgroundDownloadTask) }}</span>
      </div>
      <div class="circle-download-floating-text">
        {{ activeBackgroundDownloadTask?.current_step || '隐藏后继续保留下载队列和进度。' }}
      </div>
      <div class="circle-download-floating-actions">
        <el-button size="small" type="primary" @click="resumeDownloadWorkbenchFromBackground">恢复工作台</el-button>
        <el-button size="small" @click="closeDownloadWorkbench">关闭</el-button>
      </div>
    </div>

    <div v-if="showUploadBackgroundCard" class="circle-download-floating-card reimport-floating-card">
      <div class="circle-download-floating-head">
        <div>
          <div class="circle-download-floating-title">直接入库上传正在后台运行</div>
          <div class="circle-download-floating-mode">
            {{ activeBackgroundUploadTask ? `${activeBackgroundUploadTask.work_title || activeBackgroundUploadTask.source_label || '-'} · ${getUploadBackgroundTargetLabel(activeBackgroundUploadTask)}` : '保留当前上传队列与进度状态' }}
          </div>
        </div>
        <div class="circle-download-floating-count">{{ uploadBackgroundPercent }}%</div>
      </div>
      <el-progress
        :percentage="uploadBackgroundPercent"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="circle-download-floating-chip-row">
        <span class="circle-download-floating-chip">进行中 {{ processingUploadTasks.length }}</span>
        <span class="circle-download-floating-chip">等待中 {{ pendingUploadTasks.length }}</span>
        <span class="circle-download-floating-chip">完成 {{ completedUploadTasks.length }}</span>
        <span class="circle-download-floating-chip danger">失败 {{ failedUploadTasks.length }}</span>
        <span class="circle-download-floating-chip">速度 {{ formatSpeed(getUploadBackgroundSpeed(activeBackgroundUploadTask)) }}</span>
        <span class="circle-download-floating-chip">剩余 {{ formatTaskEta(activeBackgroundUploadTask) }}</span>
      </div>
      <div class="circle-download-floating-text">
        {{ activeBackgroundUploadTask?.current_step || '隐藏后继续保留上传队列和进度。' }}
      </div>
      <div class="circle-download-floating-actions">
        <el-button size="small" type="primary" @click="resumeUploadWorkbenchFromBackground">恢复工作台</el-button>
        <el-button size="small" @click="closeUploadWorkbench">关闭</el-button>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import celebrateImg from '../assets/celebrate.png'
import confettiAnimation from '../assets/anime/Confetti.lottie'
import { CheckCircle2, MessageSquareText, Search, LibraryBig, Languages, PlayCircle, Subtitles, X, FileText, XCircle, AlertCircle, MinusCircle } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api, { asmrSyncApi, circleCompletionApi, libraryApi, localUploadApi } from '../api'
import CircleDownloadPreviewDialog from '../components/circle/CircleDownloadPreviewDialog.vue'
import DownloadTaskWorkbenchDialog from '../components/download/DownloadTaskWorkbenchDialog.vue'
import ServerUploadPreviewDialog from '../components/common/ServerUploadPreviewDialog.vue'
import UploadTaskWorkbenchDialog from '../components/upload/UploadTaskWorkbenchDialog.vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import { showSystemPrompt } from '../composables/useSystemPrompt'

const CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY = 'prekikoeru.circleCompletion.targetSubdirs'
const CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY = 'prekikoeru.circleCompletion.downloadWorkbench'
const CIRCLE_COMPLETION_REFRESH_JOB_KEY = 'prekikoeru.circleCompletion.refreshJob'
const CIRCLE_COMPLETION_INDEX_JOB_KEY = 'prekikoeru.circleCompletion.indexJob'
const CIRCLE_COMPLETION_UPLOAD_WORKBENCH_KEY = 'prekikoeru.circleCompletion.uploadWorkbench'
function getJobProgressPercent(job) {
  const value = Number(job?.progress || 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

const circleQuery = ref('')
const circleSearch = ref('')
const indexing = ref(false)
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
const filters = reactive({
  onlyMissing: false,
  onlyDownloadable: false,
  includeDlOnly: false
})
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
const uploadWorkbenchBackgroundActive = ref(false)
const uploadWorkbenchRefreshing = ref(false)
const worksPageSizes = [12, 24, 48, 96]
const comparePageSizes = [10, 20, 50, 100]
const worksPageSize = ref(24)
const comparePageSize = ref(10)
const missingPage = ref(1)
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
  classifyMode: 'circle'
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

const missingWorks = computed(() => (detail.works || []).filter(item => isPreferredMissingWorkVisible(item)))
const showMissingWorksCompleteState = computed(() =>
  Boolean(activeCircleId.value)
  && circleDetailLoaded.value
  && !circleDetailLoading.value
  && missingWorks.value.length === 0
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
const ownedWorksFilterType = ref('all') // 'all', 'original', 'simplified', 'traditional', 'subtitle'
const compareSearchQuery = ref('')
const compareSourceFilter = ref('all') // 'all', 'kikoeru', 'dlsite', 'asmr_one', 'missing'

const ownedWorks = computed(() => {
  let list = (detail.works || []).filter(item => item.owned)

  // Filter
  if (ownedWorksFilterType.value !== 'all') {
    list = list.filter(item => {
      const groupLabel = item.preferred_variant?.group_short_label || '原作'
      const hasSubtitle = (!item.preferred_variant?.group_short_label || item.preferred_variant?.group_short_label === '原作') && item.subtitle_present

      switch (ownedWorksFilterType.value) {
        case 'original': return groupLabel === '原作' && !hasSubtitle
        case 'simplified': return groupLabel === '简中'
        case 'traditional': return groupLabel === '繁中'
        case 'subtitle': return hasSubtitle
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

  return list
})

const ownedWorksStats = computed(() => {
  const all = (detail.works || []).filter(item => item.owned)
  return {
    total: all.length,
    original: all.filter(item => {
      const groupLabel = item.preferred_variant?.group_short_label || '原作'
      const hasSubtitle = (!item.preferred_variant?.group_short_label || item.preferred_variant?.group_short_label === '原作') && item.subtitle_present
      return groupLabel === '原作' && !hasSubtitle
    }).length,
    simplified: all.filter(item => (item.preferred_variant?.group_short_label || '原作') === '简中').length,
    traditional: all.filter(item => (item.preferred_variant?.group_short_label || '原作') === '繁中').length,
    subtitle: all.filter(item => (!item.preferred_variant?.group_short_label || item.preferred_variant?.group_short_label === '原作') && item.subtitle_present).length,
  }
})

const pagedMissingWorks = computed(() => {
  const size = Number(worksPageSize.value || 24)
  const start = (missingPage.value - 1) * size
  return missingWorks.value.slice(start, start + size)
})
const pagedOwnedWorks = computed(() => {
  const size = Number(worksPageSize.value || 24)
  const start = (ownedPage.value - 1) * size
  return ownedWorks.value.slice(start, start + size)
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
  detail.owned_count = (detail.works || []).filter(item => item?.server_owned).length
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
  if (completeConfettiTimer) {
    clearTimeout(completeConfettiTimer)
    completeConfettiTimer = null
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
    if (isCancelledJobState(raw)) {
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
    if (String(raw.status || '').trim() === 'failed') {
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
        ElMessage.success(`批量建立完成，成功 ${result.meta.completed_queries || 0} 个，失败 ${result.meta.failed_queries || 0} 个`)
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
  const result = await circleCompletionApi.searchCircles(circleSearch.value || '', 24)
  circleList.value = result.circles || []
}

async function handleIndexCircle() {
  await startIndexCircleJob({
    circleQuery: circleQuery.value.trim(),
    onlyNewWorks: false
  })
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
      title: '批量建立社团索引',
      description: '一行一个社团名，提交后会按顺序批量建立或刷新索引。',
      badge: '社团补全',
      mode: 'prompt',
      inputType: 'textarea',
      placeholder: '例如：\nリリムワークス/兎月りりむ。\n耳かき屋\nしろくまだんご',
      confirmText: '开始批量建立',
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
      force_refresh: true,
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

async function refreshSelectedCircleIndex() {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  const codes = selectedCanonicalRJCodes.value
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
  activeCircleId.value = circleId
  circleDetailLoaded.value = false
  selectedCanonicals.value = new Set()
  await refreshActiveCircle()
}

async function refreshActiveCircle() {
  if (!activeCircleId.value) return
  circleDetailLoading.value = true
  try {
    const result = await circleCompletionApi.getCircleDetail(activeCircleId.value, {
      onlyMissing: filters.onlyMissing,
      onlyDownloadable: filters.onlyDownloadable,
      includeDlOnly: filters.includeDlOnly
    })
    Object.assign(detail, {
      circle_id: result.circle_id || '',
      circle_name: result.circle_name || '',
      source_mask: result.source_mask || '',
      last_indexed_at: result.last_indexed_at || '',
      owned_count: result.owned_count || 0,
      missing_count: result.missing_count || 0,
      downloadable_count: result.downloadable_count || 0,
      dl_only_count: result.dl_only_count || 0,
      works: result.works || []
    })
    circleDetailLoaded.value = true
    selectedCanonicals.value = new Set(
      [...selectedCanonicals.value].filter(code => (result.works || []).some(item => item.canonical_rjcode === code))
    )
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载社团详情失败')
  } finally {
    circleDetailLoading.value = false
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
    missingWorks.value.map(item => item.canonical_rjcode).filter(Boolean)
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
  const codes = singleCanonical ? [singleCanonical] : selectedDownloadableRJCodes.value
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
        circle_name: detail.circle_name || ''
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
  display: grid;
  gap: 16px;
  padding: 6px;
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
.circle-download-floating-card {
  position: fixed;
  right: 18px;
  bottom: 18px;
  width: min(420px, calc(100vw - 32px));
  z-index: 90;
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid #d7e6fb;
  background:
    radial-gradient(circle at top right, rgba(87, 149, 255, 0.16), transparent 28%),
    linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(246,250,255,0.98) 100%);
  box-shadow: 0 18px 40px rgba(32, 62, 105, 0.18);
  backdrop-filter: blur(12px);
}
.circle-download-floating-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.circle-download-floating-title {
  font-size: 14px;
  font-weight: 800;
  color: #203d61;
}
.circle-download-floating-mode {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.5;
  color: #6a7f98;
  word-break: break-all;
}
.circle-download-floating-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 36px;
  padding: 0 10px;
  border-radius: 999px;
  background: #edf4ff;
  color: #2458a6;
  border: 1px solid #d3e2ff;
  font-size: 13px;
  font-weight: 800;
}
.circle-download-floating-chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.circle-download-floating-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  background: #f3f7fd;
  border: 1px solid #dde7f4;
  font-size: 12px;
  font-weight: 700;
  color: #536a84;
}
.circle-download-floating-chip.danger {
  background: #fff3f1;
  border-color: #ffd7d2;
  color: #bf4636;
}
.circle-download-floating-text {
  font-size: 12px;
  line-height: 1.6;
  color: #51657f;
  word-break: break-all;
}
.circle-download-floating-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
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
.circle-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 420px);
  gap: 20px;
  padding: 30px 34px;
  border-radius: 28px;
  background: linear-gradient(180deg, #fbfcfe 0%, #f5f6f8 100%);
  border: 1px solid rgba(29, 29, 31, 0.08);
  box-shadow: 0 12px 28px rgba(29, 29, 31, 0.05);
}
.hero-eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: #0071e3;
}
.circle-hero h1 {
  margin: 6px 0 8px;
  font-size: 34px;
  line-height: 1.08;
  letter-spacing: -0.03em;
  color: #1d1d1f;
}
.circle-hero p {
  margin: 0;
  max-width: 720px;
  color: rgba(29, 29, 31, 0.7);
  line-height: 1.62;
}
.hero-actions {
  display: grid;
  gap: 12px;
  align-content: center;
  padding: 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(29, 29, 31, 0.06);
}
.hero-search-input :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 14px;
  box-shadow: none;
  background: transparent;
  padding-left: 32px;
}
.hero-search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: none;
}
.hero-search-button,
.batch-action-button,
.work-action-button {
  border-radius: 12px;
  font-weight: 800;
  position: relative;
  overflow: hidden;
  transition: transform .18s ease, box-shadow .22s ease, border-color .18s ease, background .22s ease, color .22s ease, filter .18s ease;
}
.hero-search-button {
  min-height: 46px;
  border: 1px solid #0071e3;
  background: linear-gradient(135deg, #0a84ff 0%, #0071e3 100%);
  box-shadow: 0 10px 22px rgba(0, 113, 227, 0.24);
}
.hero-search-button::after,
.batch-action-button::after,
.work-action-button::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(120deg, rgba(255,255,255,0) 20%, rgba(255,255,255,0.22) 50%, rgba(255,255,255,0) 80%);
  opacity: 0;
  transform: translateX(-18%);
  transition: opacity .2s ease, transform .28s ease;
  pointer-events: none;
}
.hero-search-button:hover,
.batch-action-button:hover,
.work-action-button:hover {
  transform: translateY(-2px);
  filter: saturate(1.05);
}
.hero-search-button:hover::after,
.batch-action-button:hover::after,
.work-action-button:hover::after {
  opacity: 1;
  transform: translateX(12%);
}
.hero-search-button:active,
.batch-action-button:active,
.work-action-button:active {
  transform: translateY(0) scale(0.985);
  box-shadow: 0 6px 14px rgba(0, 113, 227, 0.14);
}
.sidebar-refresh-button {
  font-weight: 800;
  color: #4f73ab;
}
.index-progress-card {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
  border-radius: 20px;
  border: 1px solid #d8e6fb;
  background: linear-gradient(135deg, rgba(244, 249, 255, 0.96) 0%, rgba(255, 254, 250, 0.96) 100%);
  box-shadow: 0 14px 28px rgba(55, 93, 152, 0.08);
}
.index-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.index-progress-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.refresh-progress-card {
  margin: 0 20px 18px;
}
.index-cancel-button {
  border-radius: 999px;
}
.index-progress-title {
  font-size: 16px;
  font-weight: 800;
  color: #1f3759;
}
.index-progress-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #637892;
}
.index-progress-status,
.progress-meta-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.index-progress-status {
  background: #edf4ff;
  color: #265aa7;
  border: 1px solid #d4e5ff;
}
.index-progress-status.completed {
  background: #ecfaf1;
  color: #19744b;
  border-color: #cdeedb;
}
.index-progress-status.failed {
  background: #fff1f0;
  color: #c0392b;
  border-color: #ffd4d1;
}
.index-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.progress-meta-pill {
  background: rgba(255, 255, 255, 0.82);
  color: #556b86;
  border: 1px solid #e0e8f4;
}
.progress-meta-pill.ok {
  background: #ecfaf1;
  color: #19744b;
  border-color: #cdeedb;
}
.index-progress-error {
  font-size: 13px;
  color: #bb3f33;
  line-height: 1.6;
}
.refresh-progress-log-list {
  display: grid;
  gap: 8px;
}
.refresh-progress-log-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 9px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid #dfe8f4;
  color: #506784;
  font-size: 12px;
}
.refresh-progress-log-item.success {
  background: rgba(236, 250, 241, 0.9);
  border-color: #cdeedb;
  color: #1f7a52;
}
.refresh-progress-log-item.warning {
  background: rgba(255, 248, 233, 0.9);
  border-color: #f3dfb0;
  color: #8c641a;
}
.refresh-progress-log-item.error {
  background: rgba(255, 241, 240, 0.9);
  border-color: #ffd4d1;
  color: #b74237;
}
.refresh-progress-log-time {
  flex: 0 0 auto;
  color: #8092a9;
  font-variant-numeric: tabular-nums;
}
.refresh-progress-log-message {
  min-width: 0;
  overflow-wrap: anywhere;
}
.circle-shell {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.sidebar-card,
.circle-main {
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e3edf9;
  box-shadow: 0 14px 30px rgba(46, 74, 120, 0.07);
}
.circle-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-card {
  padding: 22px 20px;
  display: grid;
  gap: 14px;
}
.sidebar-head,
.toolbar-main,
.batch-bar,
.preview-toolbar,
.preview-plan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.sidebar-title,
.toolbar-title {
  font-size: 18px;
  font-weight: 800;
  color: #1d1d1f;
}
.toolbar-card {
  padding: 20px 20px 16px;
  display: grid;
  gap: 14px;
}
.toolbar-subtitle {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.58);
  margin-top: 4px;
}
.toolbar-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.metric-pill,
.tag-chip,
.reason-pill {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}
.metric-pill {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: linear-gradient(180deg, #ffffff 0%, #f6faff 100%);
  color: #48617d;
  border: 1px solid rgba(72, 97, 125, 0.16);
}
.metric-pill.owned {
  background: linear-gradient(180deg, #f7fbff 0%, #eef5ff 100%);
  color: #245ea6;
  border-color: rgba(0, 113, 227, 0.2);
}
.metric-pill.warn {
  background: linear-gradient(180deg, #fff9f0 0%, #fff2df 100%);
  color: #9a5809;
  border-color: rgba(214, 145, 31, 0.26);
}
.metric-pill.ok,
.tag-chip.ok,
.reason-pill.ok {
  background: linear-gradient(180deg, #f3fcf6 0%, #e8f7ee 100%);
  color: #1c7a4d;
  border: 1px solid rgba(68, 162, 104, 0.24);
}
.metric-pill.muted {
  background: linear-gradient(180deg, #fbfcfe 0%, #f3f6fa 100%);
  color: #5f6f83;
  border-color: rgba(95, 111, 131, 0.16);
}
.toolbar-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding-top: 2px;
}
.toolbar-filters :deep(.el-checkbox__label) {
  font-weight: 700;
  color: #546b87;
}
.circle-list {
  display: grid;
  gap: 8px;
  padding: 4px 2px 2px;
  max-height: calc(100vh - 320px);
  overflow: auto;
}
.circle-list-item {
  width: 100%;
  padding: 14px 12px;
  border: 1px solid rgba(29, 29, 31, 0.07);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.84);
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease, transform .18s ease;
}
.circle-list-item:hover {
  border-color: rgba(0, 113, 227, 0.16);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 18px rgba(29, 29, 31, 0.05);
  transform: translateY(-1px);
}
.circle-list-item.active {
  border-color: rgba(0, 113, 227, 0.18);
  background: linear-gradient(180deg, #f8fbff 0%, #eff5fc 100%);
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.12), 0 8px 18px rgba(29, 29, 31, 0.04);
  transform: none;
}
.circle-list-name {
  font-size: 15px;
  font-weight: 700;
  color: #1d1d1f;
}
.circle-list-meta {
  margin-top: 4px;
  display: grid;
  gap: 2px;
  font-size: 11px;
  color: rgba(29, 29, 31, 0.5);
}
.works-card {
  padding: 18px;
  display: grid;
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
  min-width: 112px;
  min-height: 38px;
  border: 1px solid rgba(0, 113, 227, 0.16);
  background: linear-gradient(180deg, #ffffff 0%, #f6faff 100%);
  color: #235ea8;
}
.batch-action-button.ghost {
  border-color: rgba(29, 29, 31, 0.08);
  background: #fff;
  color: rgba(29, 29, 31, 0.6);
}
.batch-action-button.refresh {
  border-color: rgba(35, 93, 126, 0.18);
  background: linear-gradient(180deg, #f3fbff 0%, #e7f5fb 100%);
  color: #1f6a86;
}
.batch-action-button.primary {
  border-color: #0071e3;
  background: linear-gradient(135deg, #0a84ff 0%, #0071e3 100%);
  color: #fff;
  box-shadow: 0 10px 20px rgba(0, 113, 227, 0.18);
}
.batch-action-button:hover {
  background: linear-gradient(180deg, #f3f8ff 0%, #e7f1ff 100%);
  border-color: rgba(0, 113, 227, 0.24);
  color: #0c5ec2;
}
.batch-action-button.primary:hover {
  background: linear-gradient(135deg, #2997ff 0%, #0077ed 100%);
  border-color: #0077ed;
  color: #fff;
}
.batch-action-button.refresh:hover {
  background: linear-gradient(180deg, #eaf8ff 0%, #dceff7 100%);
  border-color: rgba(31, 106, 134, 0.26);
  color: #155a73;
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
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}
.work-card,
.owned-card,
.info-card,
.preview-plan {
  border-radius: 18px;
  border: 1px solid rgba(29, 29, 31, 0.07);
  background: #fcfcfd;
}
.work-card {
  position: relative;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 240px;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .22s ease, transform .18s ease, background-color .18s ease;
  will-change: transform;
  transform: translateZ(0);
}
.work-card.is-downloaded {
  border-color: rgba(67, 160, 94, 0.22);
  background:
    radial-gradient(circle at top right, rgba(93, 193, 122, 0.16), transparent 28%),
    linear-gradient(180deg, #fbfefb 0%, #f3fbf5 100%);
  box-shadow:
    0 14px 28px rgba(53, 102, 72, 0.08),
    inset 0 0 0 1px rgba(93, 193, 122, 0.08);
}
.work-card.is-downloaded:hover {
  border-color: rgba(67, 160, 94, 0.3);
  box-shadow:
    0 18px 30px rgba(53, 102, 72, 0.10),
    inset 0 0 0 1px rgba(93, 193, 122, 0.1);
  background:
    radial-gradient(circle at top right, rgba(93, 193, 122, 0.2), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, #f1fbf4 100%);
}
.work-card:hover {
  transform: translateY(-2px);
  border-color: rgba(52, 120, 246, 0.16);
  box-shadow: 0 12px 24px rgba(38, 74, 134, 0.08);
  background: #ffffff;
}
.work-card.selected {
  border-color: rgba(52, 120, 246, 0.36);
  box-shadow: 0 0 0 2px rgba(52, 120, 246, 0.14), 0 16px 30px rgba(52, 120, 246, 0.12);
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
}
.work-card.status-flash {
  animation: workStatusFlash 2.4s ease;
  border-color: rgba(82, 170, 103, 0.54);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.18),
    0 18px 32px rgba(73, 137, 91, 0.16);
  background:
    radial-gradient(circle at top right, rgba(115, 205, 134, 0.22), transparent 32%),
    linear-gradient(180deg, #fcfffb 0%, #eefaf0 100%);
}
.work-card.status-flash.selected {
  border-color: rgba(82, 170, 103, 0.6);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.22),
    0 18px 32px rgba(73, 137, 91, 0.18);
}
.work-card.disabled {
  opacity: .96;
  filter: saturate(0.56) grayscale(0.12);
  background: linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%);
  border-color: rgba(29, 29, 31, 0.07);
  cursor: default;
}
.work-card.disabled:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 16px rgba(29, 29, 31, 0.05);
  background: linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%);
  border-color: rgba(29, 29, 31, 0.08);
}
@keyframes workStatusFlash {
  0% {
    transform: translateY(0) scale(0.992);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0.34),
      0 8px 18px rgba(73, 137, 91, 0.10);
  }
  18% {
    transform: translateY(-2px) scale(1.008);
    box-shadow:
      0 0 0 6px rgba(82, 170, 103, 0.16),
      0 18px 30px rgba(73, 137, 91, 0.18);
  }
  100% {
    transform: translateY(0) scale(1);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0),
      0 12px 22px rgba(73, 137, 91, 0.10);
  }
}
.work-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.work-corner-flag {
  position: absolute;
  top: 0;
  right: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 68px;
  height: 24px;
  padding: 0 10px;
  border-bottom-left-radius: 12px;
  background: rgba(34, 197, 94, 0.95);
  backdrop-filter: blur(8px);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.25);
  z-index: 10;
}
.work-corner-flag::after {
  content: '';
  position: absolute;
  left: -8px;
  top: 0;
  width: 14px;
  height: 100%;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.4) 0%, rgba(255, 255, 255, 0.05) 100%);
  transform: skewX(-24deg);
  opacity: 0.8;
}
.work-card-copy {
  min-height: 72px;
}
.work-rj {
  font-size: 11px;
  font-weight: 700;
  color: #5d7caa;
}
.work-card.disabled .work-rj,
.work-card.disabled .work-title,
.work-card.disabled .work-linked {
  color: rgba(29, 29, 31, 0.4);
}
.work-title,
.owned-title {
  font-size: 13px;
  font-weight: 800;
  color: #1f3554;
  line-height: 1.42;
}
.work-title {
  display: -webkit-box;
  min-height: calc(1.42em * 3);
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.work-linked,
.owned-meta,
.owned-path {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.46);
  line-height: 1.5;
  word-break: break-word;
}
.work-linked {
  min-height: 17px;
}
.work-tags,
.work-actions,
.preview-presets,
.preview-plan-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.work-tags {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.work-actions {
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  gap: 6px;
  flex-wrap: wrap;
  width: 100%;
}
.tag-chip {
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.02em;
}
.tag-chip.is-primary {
  background: #edf4ff;
  color: #3b70c4;
  border: 1px solid #cce0ff;
}
.tag-chip.is-success {
  background: #edf9f1;
  color: #2b804e;
  border: 1px solid #cdeedb;
}
.tag-chip.is-danger {
  background: #fff4f2;
  color: #c44733;
  border: 1px solid #fbd8d3;
}
.tag-chip.is-warning {
  background: #fff8eb;
  color: #b06f13;
  border: 1px solid #fbe6c4;
}
.tag-chip.is-info {
  background: #f4f6f9;
  color: #5d6d81;
  border: 1px solid #e2e8f0;
}
.tag-chip.is-disabled {
  background: #fafafa;
  color: #94a3b8;
  border: 1px solid #e2e8f0;
}
.work-action-button {
  border: 1px solid #b9d7ff;
  background: #ffffff;
  color: #1f6fd6;
  width: auto;
  min-width: 84px;
  min-height: 26px;
  padding: 0 12px;
  justify-content: center;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 2px 6px rgba(31, 111, 214, 0.08);
}
.work-action-button:hover {
  background: linear-gradient(180deg, #2997ff 0%, #0077ed 100%);
  border-color: #0077ed;
  color: #fff;
  box-shadow: 0 8px 16px rgba(31, 111, 214, 0.18);
}
.work-action-button.upload {
  border-color: #cde4d4;
  background: #edf8f1;
  color: #237849;
  box-shadow: 0 2px 6px rgba(35, 120, 73, 0.08);
}
.work-action-button.upload:hover {
  background: linear-gradient(180deg, #45b36a 0%, #2f8b54 100%);
  border-color: #2f8b54;
  color: #fff;
  box-shadow: 0 8px 16px rgba(35, 120, 73, 0.18);
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
  margin-top: 6px;
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
  padding-top: 2px;
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
.compare-board {
  border: 1px solid #e6edf7;
  border-radius: 18px;
  overflow: auto;
  background: #fff;
}
.compare-head,
.compare-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.4fr) repeat(3, minmax(180px, 1fr));
}
.compare-head {
  background: #f5f8fd;
  border-bottom: 1px solid #e8eef6;
  font-size: 12px;
  font-weight: 800;
  color: #61748d;
}
.compare-row + .compare-row {
  border-top: 1px solid #eff3f8;
}
.compare-col {
  padding: 14px 16px;
  min-width: 0;
}
.compare-col + .compare-col {
  border-left: 1px solid #eff3f8;
}
.compare-col.source.kikoeru {
  background: rgba(239, 246, 255, 0.56);
}
.compare-col.source.dlsite {
  background: rgba(255, 247, 237, 0.62);
}
.compare-col.source.asmr {
  background: rgba(236, 253, 245, 0.66);
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
  .circle-shell,
  .circle-hero {
    grid-template-columns: 1fr;
  }
  .index-progress-head {
    flex-direction: column;
    align-items: stretch;
  }
  .workbench-toolbar,
  .download-task-head,
  .download-file-row,
  .circle-download-floating-head {
    flex-direction: column;
    align-items: stretch;
  }
  .download-task-meta-grid,
  .download-settings-grid,
  .reimport-summary-grid {
    grid-template-columns: 1fr;
  }
  .compare-head,
  .compare-row {
    grid-template-columns: minmax(220px, 1.2fr) repeat(3, minmax(150px, 1fr));
  }
  .circle-download-floating-card {
    right: 12px;
    left: 12px;
    bottom: 12px;
    width: auto;
  }
}
</style>
