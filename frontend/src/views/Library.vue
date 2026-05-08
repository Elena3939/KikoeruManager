<template>

  <div

    class="library library-page-loading-shell"

    v-app-loading="{ loading, text: '正在刷新库存内容...', description: '同步目录、搜索结果和当前作用域', size: 176, minHeight: 360, delay: 0, minVisible: 360, maskClass: 'library-page-loading-mask' }"

  >

    <header class="lib-page-header">

      <div class="lib-page-head-left">

        <div class="lib-page-icon"><IconDatabase :size="20" :stroke-width="2.2" /></div>

        <div>

          <h1 class="lib-page-title">{{ labels.pageTitle }}</h1>

          <p class="lib-page-subtitle">多库存、本地 + 群晖、搜索定位、批量处理的一体化工作台</p>

        </div>

      </div>

      <div class="lib-page-head-right" v-if="currentLibrary">

        <span class="lib-chip" :class="isRemoteCurrentLibrary ? 'lib-chip-warning' : 'lib-chip-success'">

          <IconHardDrive :size="12" :stroke-width="2.4" />{{ currentLibraryScopeLabel }}

        </span>

        <span class="lib-chip" :class="`lib-chip-${healthTagType(currentLibrary.health?.status) || 'info'}`">

          {{ healthStatusLabel(currentLibrary.health?.status) }}

        </span>

        <LibraryIndexBadge :library="currentLibrary" />

      </div>

    </header>



    <section class="lib-info-strip">

      <div class="lib-info-item">

        <IconHardDrive :size="15" :stroke-width="2.2" class="lib-info-icon text-blue-500" />

        <div class="lib-info-body">

          <div class="lib-info-label">{{ labels.currentLibrary }}</div>

          <div class="lib-info-value">

            <b>{{ currentLibrary?.name || '-' }}</b>

            <span class="lib-info-meta">· {{ currentLibraryTypeLabel }}</span>

          </div>

          <div class="lib-info-sub" :title="currentLibrary?.path || ''">{{ currentLibrary?.path || '-' }}</div>

        </div>

      </div>



      <div class="lib-info-divider"></div>



      <div class="lib-info-item">

        <IconBarChart :size="15" :stroke-width="2.2" class="lib-info-icon text-violet-500" />

        <div class="lib-info-body">

          <div class="lib-info-label">{{ labels.currentLibraryStats }}</div>

          <div class="lib-info-value"><b>{{ statsSizeCardText(currentStats) }}</b></div>

          <div v-if="showCurrentStatsProgress" class="lib-info-progress">

            <el-progress :percentage="currentStatsProgress" :stroke-width="4" :show-text="false" />

          </div>

          <div class="lib-info-sub">{{ statsStatusCardText(currentStats) }}</div>

        </div>

      </div>



      <div class="lib-info-divider"></div>



      <div class="lib-info-item">

        <IconLayers :size="15" :stroke-width="2.2" class="lib-info-icon text-amber-500" />

        <div class="lib-info-body">

          <div class="lib-info-label">{{ labels.allLibraries }}</div>

          <div class="lib-info-value"><b>{{ aggregateSizeText }}</b></div>

          <div v-if="showAggregateProgress" class="lib-info-progress">

            <el-progress :percentage="aggregateProgress" :stroke-width="4" :show-text="false" />

          </div>

          <div class="lib-info-sub">{{ aggregateSummary }}{{ aggregateDetail ? ' · ' + aggregateDetail : '' }}</div>

        </div>

      </div>

    </section>



    <el-card shadow="never" class="main-card">

      <template #header>

        <div class="lib-card-header">

          <span class="lib-card-title">库内文件列表</span>

          <div class="lib-toolbar">

            <el-select v-model="selectedLibraryId" class="lib-library-select !w-[220px]" placeholder="选择库存">

              <el-option v-for="library in libraries" :key="library.id" :label="library.name" :value="library.id">

                <div class="flex items-center justify-between gap-3">

                  <span class="truncate">{{ library.name }}</span>

                  <el-tag size="small" effect="plain" :type="library.type === 'synology_filestation' ? 'warning' : 'success'">

                    {{ library.type === 'synology_filestation' ? '远程' : '本地' }}

                  </el-tag>

                </div>

              </el-option>

            </el-select>



            <div class="lib-search">

              <IconSearch :size="14" :stroke-width="2.2" class="lib-search-icon" />

              <input

                v-model="searchQuery"

                type="text"

                class="lib-search-input"

                placeholder="搜索文件名或 RJ 号"

                @keyup.enter="handleSearch"

              />

              <button v-if="searchQuery" type="button" class="lib-search-clear" @click="searchQuery = ''; handleSearch()" title="清除">

                <IconX :size="13" :stroke-width="2.4" />

              </button>

            </div>



            <el-select v-model="searchResultKind" class="!w-[96px]">

              <el-option label="全部" value="all" />

              <el-option label="文件夹" value="folder" />

              <el-option label="文件" value="file" />

            </el-select>

            <AppLottieSwitch v-model="searchExact" :show-text="true" active-text="精确" inactive-text="模糊" />



            <button type="button" class="lib-btn lib-btn-primary" @click="handleSearch">

              <IconSearch :size="14" :stroke-width="2.4" />

              <span>查询</span>

            </button>



            <button

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-refresh"

              :disabled="isRefreshingCurrentView"

              @click="refreshCurrentView"

              :title="isRefreshingCurrentView ? '刷新中…' : '刷新当前视图'"

            >

              <IconRefreshCw :size="14" :stroke-width="2.2" :class="{ 'animate-spin': isRefreshingCurrentView }" />

              <span>{{ isRefreshingCurrentView ? '刷新中' : '刷新' }}</span>

            </button>



            <button

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-stats"

              :disabled="statsLoading && !canCancelStats"

              @click="handleStatsAction"

            >

              <IconBarChart :size="14" :stroke-width="2.2" />

              <span>{{ canCancelStats ? '取消统计' : '刷新统计' }}</span>

            </button>



            <button type="button" class="lib-btn lib-btn-icon-tinted lib-icon-select" @click="toggleAllSelection">

              <IconCheckSquare :size="14" :stroke-width="2.2" />

              <span>{{ isAllSelected ? '取消全选' : '全选' }}</span>

            </button>

          </div>

        </div>

      </template>



      <el-alert
        v-if="synologyOtpRequired"
        type="error"
        title="群晖二步验证（OTP）已过期，无法连接群晖库存"
        :closable="true"
        show-icon
        style="margin-bottom: 10px"
        @close="synologyOtpRequired = false"
      >
        <template #default>
          请前往
          <router-link to="/settings" class="text-blue-500 underline">设置页</router-link>
          在「群晖连接」中填写新的一次性验证码（OTP），并开启 Device Token，避免每次登录都需要验证。
        </template>
      </el-alert>

      <el-alert

        v-if="currentLibrary?.health?.warnings?.length || currentLibrary?.health?.errors?.length"

        :title="healthDetailText(currentLibrary?.health)"

        :type="currentLibrary?.health?.errors?.length ? 'error' : 'warning'"

        :closable="false"

        show-icon

        style="margin-bottom: 14px"

      />



      <div v-if="!selectedRowPaths.size" class="lib-path-toolbar">

        <div class="lib-path-left">

          <button type="button" class="lib-btn lib-btn-ghost lib-btn-compact" :disabled="!canGoParent" @click="goToParent">

            <IconArrowLeft :size="14" :stroke-width="2.4" />

            <span>{{ backButtonLabel }}</span>

          </button>

          <span class="lib-path-label">当前层级</span>

          <code class="lib-path-code">{{ currentPathDisplay }}</code>

        </div>

        <div class="lib-path-right">

          <div class="lib-scope-switch" role="tablist" aria-label="工具栏作用范围">

            <button

              type="button"

              class="lib-scope-option"

              :class="{ 'is-active': toolbarActionScope === 'page' }"

              :aria-pressed="toolbarActionScope === 'page'"

              @click="toolbarActionScope = 'page'"

            >

              当前页

            </button>

            <button

              type="button"

              class="lib-scope-option"

              :class="{ 'is-active': toolbarActionScope === 'all' }"

              :aria-pressed="toolbarActionScope === 'all'"

              @click="toolbarActionScope = 'all'"

            >

              当前目录

            </button>

          </div>

          <button

            type="button"

            class="lib-btn lib-btn-icon-tinted lib-icon-subtitle"

            :disabled="!canProcessCurrentFolder"

            @click="startCurrentFolderRJSubtitle"

          >

            <IconCaptions :size="14" :stroke-width="2.2" />

            <span>{{ toolbarActionScope === 'page' ? '当前页抓字幕' : '当前目录抓字幕' }}</span>

          </button>

          <button

            type="button"

            class="lib-btn lib-btn-icon-tinted lib-icon-filter-delete"

            :disabled="!canFilterDeleteCurrentFolder"

            @click="openFilterDeleteDialog"

          >

            <IconFilterX :size="14" :stroke-width="2.2" />

            <span>{{ toolbarActionScope === 'page' ? '当前页删过滤' : '删除过滤文件' }}</span>

          </button>

          <button

            type="button"

            class="lib-btn lib-btn-icon-tinted lib-icon-task-panel"

            @click="openSubtitleTaskPanel"

          >

            <IconListTodo :size="14" :stroke-width="2.2" />

            <span>字幕任务面板</span>

          </button>

          <button

            v-if="!isRemoteCurrentLibrary"

            type="button"

            class="lib-btn lib-btn-icon-tinted lib-icon-upload"

            :disabled="selectedUploadCount === 0 || !hasRemoteUploadLibraries"

            @click="openLocalUploadDialog"

          >

            <IconUpload :size="14" :stroke-width="2.2" />

            <span>上传到服务器</span>

          </button>

        </div>

      </div>



      <el-alert

        v-if="librarySearchState.active"

        :title="librarySearchSummary"

        type="info"

        :closable="false"

        show-icon

        style="margin-bottom: 14px"

      />



      <transition name="lib-batch-slide">

        <div v-if="selectedRowPaths.size" class="lib-batch-bar">

          <div class="lib-batch-info">

            <div class="lib-batch-count-pill">

              <IconCheckSquare :size="14" :stroke-width="2.4" />

              <span>已选 <b>{{ selectedRowPaths.size }}</b> 项</span>

            </div>

            <button type="button" class="lib-batch-clear" @click="clearSelection" title="取消选择">

              <IconX :size="13" :stroke-width="2.4" />

              <span>清空</span>

            </button>

          </div>

          <div class="lib-batch-actions">

            <button

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-subtitle-batch"

              :disabled="!selectedSubtitleCandidates.length || subtitleSubmitting"

              @click="openRJSubtitleDialog(selectedSubtitleCandidates)"

            >

              <IconCaptions :size="14" :stroke-width="2.2" />

              <span>批量抓字幕</span>

              <span v-if="selectedSubtitleCandidates.length" class="lib-badge">{{ selectedSubtitleCandidates.length }}</span>

            </button>

            <button

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-filter-delete"

              :disabled="!selectedFilterDeleteRows.length || !isWritableCurrentLibrary"

              @click="openSelectedFilterDeleteDialog"

            >

              <IconFilterX :size="14" :stroke-width="2.2" />

              <span>删过滤预审</span>

            </button>

            <button

              v-if="!isRemoteCurrentLibrary && isAtComputeSizeRoot"

              type="button"


              :class="['lib-btn lib-btn-icon-tinted lib-icon-compute-size lib-batch-action-btn', { 'is-executing': batchComputingSize }]"

              :disabled="batchComputingSize || !selectedDirectoryRows.length"

              @click="handleBatchComputeSize"

            >

              <IconHardDrive :size="14" :stroke-width="2.2" />

              <span>批量计算大小</span>

              <span v-if="batchComputingSize" class="lib-badge">计算中</span>

            </button>

            <button

              type="button"

              :class="['lib-btn lib-btn-icon-tinted lib-icon-batch-delete lib-batch-action-btn', { 'is-executing': batchDeleting }]"

              :disabled="!isWritableCurrentLibrary || batchDeleting"

              @click="handleBatchDelete"

            >

              <IconTrash :size="14" :stroke-width="2.2" />

              <span>批量删除</span>

            </button>

            <button

              v-if="!isRemoteCurrentLibrary"

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-batch-move lib-batch-action-btn"

              :disabled="!isWritableCurrentLibrary || moveDialogState.submitting || !selectedRows.length"

              @click="openMoveDialog(selectedRows)"

            >

              <IconFolderInput :size="14" :stroke-width="2.2" />

              <span>批量移动</span>

            </button>

            <button

              type="button"

              :class="['lib-btn lib-btn-icon-tinted lib-icon-api-rename lib-batch-action-btn', { 'is-executing': batchRenaming }]"

              :disabled="!selectedApiRenameRows.length || apiRenameBusy"

              @click="handleBatchApiRename"

            >

              <IconPencil :size="14" :stroke-width="2.2" />

              <span>批量 API 重命名</span>

            </button>

            <button

              v-if="!isRemoteCurrentLibrary"

              type="button"

              class="lib-btn lib-btn-icon-tinted lib-icon-upload"

              :disabled="selectedUploadCount === 0 || !hasRemoteUploadLibraries"

              @click="openLocalUploadDialog"

            >

              <IconUpload :size="14" :stroke-width="2.2" />

              <span>上传到服务器</span>

            </button>

          </div>

        </div>

      </transition>



      <el-table

        :key="libraryTableKey"

        ref="tableRef"

        :data="files"

        :row-key="libraryRowKey"

        :row-class-name="libraryRowClassName"

        empty-text="暂无文件"

        @selection-change="handleSelectionChange"

        @sort-change="handleSortChange"

        @row-click="handleLibraryRowClick"

        @row-contextmenu="handleLibraryRowContextMenu"

      >

        <el-table-column type="selection" width="55" :selectable="isLibraryRowSelectable" />

        <el-table-column prop="name" label="文件名" sortable="custom" show-overflow-tooltip>

          <template #default="{ row }">

            <div class="file-cell">

              <div class="file-main-line">

                <span class="file-icon-shell">
                  <component :is="getLibraryRowIconComponent(row)" class="file-icon" :class="getLibraryRowIconClass(row)" :size="18" :stroke-width="2.2" />
                </span>

                <button v-if="isSearchResultRow(row)" type="button" class="file-link-btn" @click.stop="locateLibrarySearchResult(row)" v-html="renderLibrarySearchHighlight(row.name)"></button>

                <button v-else-if="row.is_directory" type="button" class="file-link-btn" @click.stop="openFolder(row)" v-html="renderLibrarySearchHighlight(row.name)"></button>

                <span v-else class="file-name" v-html="renderLibrarySearchHighlight(row.name)"></span>

              </div>

              <div v-if="isSearchResultRow(row) && getSearchResultLibraryLabel(row)" class="search-result-library">

                来源库：{{ getSearchResultLibraryLabel(row) }}

              </div>

            </div>

          </template>

        </el-table-column>

        <el-table-column prop="rjcode" label="RJ 号" width="120">

          <template #default="{ row }">

            <el-tag v-if="row.rjcode" size="small" type="primary" effect="light">{{ row.rjcode }}</el-tag>

            <span v-else class="empty-text">-</span>

          </template>

        </el-table-column>

        <el-table-column prop="size" label="大小" sortable="custom" width="120">

          <template #default="{ row }">{{ formatRowSize(row) }}</template>

        </el-table-column>

        <el-table-column prop="modified_time" label="时间" sortable="custom" width="180">

          <template #default="{ row }">{{ formatDate(row.unzip_time || row.modified_time) }}</template>

        </el-table-column>

      </el-table>

      <LibraryRowContextMenu

        :key="libraryRowContextMenu.renderKey"

        :visible="libraryRowContextMenu.visible"

        :x="libraryRowContextMenu.x"

        :y="libraryRowContextMenu.y"

        :row="libraryRowContextMenu.row"

        :show-locate="Boolean(libraryRowContextMenu.row && isSearchResultRow(libraryRowContextMenu.row) && !libraryRowContextMenu.row.is_directory)"

        :show-open="Boolean(libraryRowContextMenu.row && !isRemoteCurrentLibrary)"

        :show-open-direct="Boolean(libraryRowContextMenu.row && !isRemoteCurrentLibrary)"

        :disable-rename="!isWritableCurrentLibrary || apiRenameBusy"

        :disable-api-rename="!canApiRenameRow(libraryRowContextMenu.row) || apiRenameBusy"

        :api-rename-running="Boolean(libraryRowContextMenu.row && (apiRenamingId === libraryRowContextMenu.row.id || isBatchApiRenameRunning(libraryRowContextMenu.row)))"

        :api-batch-target="Boolean(libraryRowContextMenu.row && isBatchApiRenameTarget(libraryRowContextMenu.row))"

        :disable-subtitle="!canFetchRJSubtitle(libraryRowContextMenu.row)"

        :disable-manage="!libraryRowContextMenu.row?.is_directory"

        :disable-delete="!isWritableCurrentLibrary"

        :show-move="Boolean(libraryRowContextMenu.row && !isRemoteCurrentLibrary)"

        :disable-move="!isWritableCurrentLibrary || moveDialogState.submitting"

        :show-compute-size="Boolean(libraryRowContextMenu.row?.is_directory && !isRemoteCurrentLibrary && (!currentPath.value || currentPath.value === browseRootPath.value))"

        :computing-size-id="computingSizeId"

        @close="closeLibraryRowContextMenu"

        @action="handleLibraryRowContextMenuAction"

      />





      <div class="pagination-wrap">

        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="PAGE_SIZES" :total="totalFiles" layout="total, sizes, prev, pager, next, jumper" background />

      </div>

    </el-card>



    <ServerUploadPreviewDialog

      :visible="localUploadDialogVisible"

      :starting="localUploadSubmitting"

      title="上传到服务器"

      :source-library-id="selectedLibraryId"

      :source-library-name="currentLibrary?.name || ''"

      :source-items="selectedUploadSourceItems"

      :libraries="libraries"

      :initial-target-library-id="localUploadForm.targetLibraryId"

      :initial-target-subdir="localUploadForm.targetSubdir"

      @update:visible="value => localUploadDialogVisible = value"

      @submit="submitLocalUpload"

    />



    <UploadTaskWorkbenchDialog

      v-model:visible="uploadWorkbenchVisible"

      :tasks="trackedUploadTasks"

      :refreshing="uploadWorkbenchRefreshing"

      @refresh="refreshUploadWorkbench"

      @background="hideUploadWorkbenchToBackground"

      @close="closeUploadWorkbench"

    />



    <div v-if="showUploadBackgroundCard" class="floating-card floating-card-upload">

      <div class="upload-floating-head">

        <div class="flex items-center gap-2.5 min-w-0 pr-2">

          <div class="floating-hero-icon">
            <DotLottieVue
              :src="uploadToCloudAnimation"
              autoplay
              loop
              background="transparent"
              class="floating-hero-lottie"
            />
          </div>

          <div class="min-w-0">

            <div class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-900 leading-tight">
              <span class="upload-floating-title">{{ uploadBackgroundTitleText }}</span>
              <span v-if="trackedUploadTasks.length" class="floating-chip floating-chip-title">上传 {{ formatFileSize(uploadBackgroundTotalBytes) }}</span>
            </div>

            <div class="mt-0.5 text-[11px] text-slate-500 leading-snug break-all">
              {{ activeBackgroundUploadTask ? `上传到目录: ${getUploadBackgroundTargetLabel(activeBackgroundUploadTask)}` : '上传到目录: -' }}
            </div>

            <div class="mt-1 text-[11px] font-medium text-slate-400 leading-none">
              预计剩余: {{ uploadBackgroundEtaText }}
            </div>

          </div>

        </div>

      </div>

      <DotLottieVue
        v-if="uploadBackgroundCompleted"
        ref="uploadProgressLottieRef"
        :src="uploadBackgroundStatusAnimation"
        :autoplay="uploadBackgroundAnimationAutoplay"
        :loop="uploadBackgroundAnimationLoop"
        :render-config="{ autoResize: true, devicePixelRatio: 2 }"
        background="transparent"
        :class="[
          'floating-progress-lottie',
          'floating-progress-lottie-success'
        ]"
      />

      <DotLottieVue
        v-else
        ref="uploadProgressLottieRef"
        :key="uploadBackgroundProgressLottieKey"
        :src="uploadProgressBarAnimation"
        :autoplay="false"
        :loop="false"
        :render-config="{ autoResize: true, devicePixelRatio: 2 }"
        background="transparent"
        class="floating-progress-lottie floating-progress-lottie-progress"
      />

      <div class="floating-chip-row-compact">

        <span class="floating-chip"><IconRefreshCw class="floating-chip-icon chip-blue" :stroke-width="2.2" />进行中 <b>{{ processingUploadTasks.length }}</b></span>

        <span class="floating-chip"><IconListTodo class="floating-chip-icon chip-amber" :stroke-width="2.2" />等待中 <b>{{ pendingUploadTasks.length }}</b></span>

        <span class="floating-chip"><IconCheckSquare class="floating-chip-icon chip-emerald" :stroke-width="2.2" />完成 <b>{{ completedUploadTasks.length }}</b></span>

        <span class="floating-chip" :class="{ 'floating-chip-danger': failedUploadTasks.length > 0 }"><IconX class="floating-chip-icon chip-rose" :stroke-width="2.2" />失败 <b>{{ failedUploadTasks.length }}</b></span>

        <span class="floating-chip"><IconBarChart class="floating-chip-icon chip-indigo" :stroke-width="2.2" />{{ formatSpeed(uploadBackgroundSpeedValue) }}</span>

      </div>

      <div v-if="uploadBackgroundDetailText" class="rounded-xl bg-slate-50 border border-slate-100/80 px-3 py-2 text-[11px] leading-relaxed text-slate-500 line-clamp-2">

        {{ uploadBackgroundDetailText }}

      </div>

      <div class="flex items-center justify-end gap-2 pt-0.5">

        <button type="button" class="floating-action-btn" @click="closeUploadWorkbench">关闭</button>

        <button type="button" class="floating-action-btn floating-action-btn-primary" @click="resumeUploadWorkbenchFromBackground">

          <IconUpload class="h-3 w-3" :stroke-width="2.3" />恢复工作台

        </button>

      </div>

    </div>



    <el-dialog

      v-model="subtitleDialogVisible"

      :show-close="false"

      :destroy-on-close="false"

      :close-on-click-modal="false"

      :close-on-press-escape="false"

      :before-close="handleSubtitleDialogBeforeClose"

      class="subtitle-workbench-dialog"

      align-center

      modal-class="subtitle-workbench-overlay"

    >

      <div class="subtitle-workbench-shell relative flex w-full min-h-[78vh] max-h-[92vh] flex-col overflow-hidden rounded-[20px] border border-slate-200/80 bg-white shadow-[0_20px_60px_rgba(15,23,42,0.1)]">

        <header class="subtitle-workbench-header relative flex items-center justify-between gap-4 px-6 py-4 flex-shrink-0 border-b border-slate-100 bg-white">

          <div class="flex items-center gap-3.5 min-w-0">

            <div class="subtitle-workbench-brand group flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px] border border-slate-200 bg-slate-900 text-white shadow-[0_4px_12px_rgba(15,23,42,0.18)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(15,23,42,0.28)]">

              <Captions class="h-[18px] w-[18px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:rotate-[-4deg]" :stroke-width="2.1" />

            </div>

            <div class="min-w-0">

              <div class="flex items-center gap-2">

                <h2 class="text-[17px] font-semibold tracking-[-0.02em] leading-tight text-slate-900">RJ 字幕抓取工作台</h2>

                <span class="inline-flex items-center gap-1 rounded-full border border-emerald-200/70 bg-emerald-50 px-2 py-0.5 text-[10.5px] font-medium text-emerald-700">

                  <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>Live

                </span>

              </div>

              <p class="mt-0.5 text-[11.5px] leading-snug text-slate-500 truncate">沉浸式单舞台工作台，焦点只保留当前阶段、当前任务和当前操作。</p>

            </div>

          </div>

          <div class="flex items-center gap-2 flex-shrink-0">

            <button

              type="button"

              class="subtitle-workbench-btn group inline-flex items-center gap-1.5 rounded-[10px] border border-slate-200 bg-white px-3.5 py-2 text-[12.5px] font-medium text-slate-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 hover:shadow-[0_8px_16px_rgba(15,23,42,0.08)] active:translate-y-0 active:scale-[0.96]"

              @click="hideSubtitleTaskPanelToBackground"

            >

              <Minimize2 class="h-[13px] w-[13px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:rotate-[-8deg]" :stroke-width="2.2" />

              <span>隐藏到后台</span>

            </button>

            <button

              type="button"

              class="subtitle-workbench-btn subtitle-workbench-btn-close group inline-flex items-center gap-1.5 rounded-[10px] border border-slate-200/70 bg-slate-50/70 px-3.5 py-2 text-[12.5px] font-medium text-slate-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 hover:shadow-[0_8px_16px_rgba(0,0,0,0.08)] active:translate-y-0 active:scale-[0.96]"

              @click="hideSubtitleTaskPanelToBackground"

            >

              <IconX class="h-[13px] w-[13px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:rotate-90" :stroke-width="2.4" />

              <span>关闭</span>

            </button>

          </div>

        </header>

        <div class="subtitle-workbench-body subtitle-workbench-scrollbar flex-1 min-h-0 overflow-auto bg-gradient-to-b from-[#fafcff] via-white to-[#f6f8ff] p-4">

          <SubtitleWorkbenchStage :ctx="subtitleWorkbenchStageCtx" />

        </div>

      </div>

    </el-dialog>



    <el-dialog v-model="subtitleRenameDialogVisible" title="重命名字幕文件" width="500px">

      <el-form :model="subtitleRenameForm" label-width="80px">

        <el-form-item label="当前名称"><el-input v-model="subtitleRenameForm.currentName" disabled /></el-form-item>

        <el-form-item label="新名称"><el-input v-model="subtitleRenameForm.newName" placeholder="输入新的字幕文件名" /></el-form-item>

        <el-form-item label="预览"><div class="name-preview">{{ subtitleRenameForm.newName || subtitleRenameForm.currentName }}</div></el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="subtitleRenameDialogVisible = false">取消</el-button>

        <el-button type="primary" :loading="subtitleRenameLoading" @click="confirmSubtitleRename">确认重命名</el-button>

      </template>

    </el-dialog>





    <el-dialog v-model="mappedPathDialogVisible" title="跨设备访问 - 路径映射" width="620px">

      <el-alert title="检测到跨设备部署环境" type="info" :closable="false" show-icon style="margin-bottom: 16px">

        <template #default>后端无法直接替你打开本地路径，请使用下面的映射路径手动访问。</template>

      </el-alert>

      <el-descriptions :column="1" border>

        <el-descriptions-item label="远程路径"><code class="path-code">{{ mappedPathInfo.originalPath }}</code></el-descriptions-item>

        <el-descriptions-item label="本地映射路径">

          <div class="mapped-path-box">

            <code class="path-code">{{ mappedPathInfo.mappedPath }}</code>

            <div class="path-actions">

              <el-button size="small" type="primary" @click="copyMappedPath">复制路径</el-button>

              <el-button size="small" type="success" @click="openWithBrowser">尝试打开</el-button>

            </div>

          </div>

        </el-descriptions-item>

      </el-descriptions>

    </el-dialog>



    <FolderContentsDialog

      ref="folderDialogRef"

      v-model="folderDialogVisible"

      :library-id="folderDialogLibraryId || selectedLibraryId"

      :folder-path="folderDialogPath"

      :folder-name="folderDialogName"

      @mutated="handleFolderDialogMutated"

    />



    <FilterDeleteDialog

      ref="filterDeleteDialogRef"

      v-model="filterDeleteDialogVisible"

      :library-id="filterDeleteDialogLibraryId"

      :current-path="filterDeleteDialogPath"

      :target-paths="filterDeleteDialogTargetPaths"

      :rules="filterDeleteDialogRules"

      :scope-label="filterDeleteDialogScopeLabel"

      :is-remote="filterDeleteDialogIsRemote"

      :initial-job-id="filterDeleteDialogInitialJobId"

      @deleted="handleFilterDeleteDeleted"

      @dismiss-background="handleFilterDeleteDialogDismissBackground"

      @state-change="handleFilterDeleteDialogStateChange"

    />



    <LibraryMoveDialog

      :visible="moveDialogState.visible"

      :source-library-id="moveDialogState.sourceLibraryId"

      :items="moveDialogState.items"

      :libraries="libraries"

      :submitting="moveDialogState.submitting"

      @update:visible="value => { if (!value) closeMoveDialog() }"

      @close="closeMoveDialog"

      @submit="handleMoveSubmit"

    />



    <div v-if="showSubtitleBackgroundCard" class="floating-card">

      <div class="flex items-start justify-between gap-3">

        <div class="flex items-center gap-2.5 min-w-0">

          <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10">

            <IconCaptions class="h-3.5 w-3.5 text-emerald-600" :stroke-width="2.2" />

          </div>

          <div class="min-w-0">

            <div class="text-[13px] font-semibold text-slate-900 leading-tight">RJ 字幕工作台正在后台运行</div>

            <div class="mt-0.5 text-[11px] text-slate-500 line-clamp-2 leading-snug">

              {{ subtitleBackgroundActiveTask ? `${getTaskDisplayRJCode(subtitleBackgroundActiveTask)} · ${subtitleBackgroundActiveTask.folder_name || getFileName(subtitleBackgroundActiveTask.folder_path) || '-'}` : '保留当前扫描与任务状态' }}

            </div>

          </div>

        </div>

        <div class="shrink-0 rounded-xl bg-emerald-50 border border-emerald-100 px-2.5 py-1 text-[13px] font-bold text-emerald-600 tabular-nums">{{ subtitleTasks.length }}</div>

      </div>

      <div class="flex flex-wrap gap-1.5">

        <span class="floating-chip">任务 <b>{{ subtitleTasks.length }}</b></span>

        <span class="floating-chip">执行中 <b>{{ subtitleTasks.filter(t => t.status === 'processing').length }}</b></span>

        <span class="floating-chip">等待中 <b>{{ subtitleTasks.filter(t => t.status === 'pending').length }}</b></span>

        <span class="floating-chip">扫描命中 <b>{{ subtitleDialogSelection.length }}</b></span>

      </div>

      <div class="rounded-xl bg-slate-50 border border-slate-100/80 px-3 py-2 text-[11px] leading-relaxed text-slate-500 line-clamp-2">

        {{ subtitleBackgroundActiveTask?.current_step || subtitleSelectionProgressText || '隐藏后继续保留任务队列和当前焦点。' }}

      </div>

      <div class="flex items-center justify-end gap-2 pt-0.5">

        <button type="button" class="floating-action-btn" @click="dismissSubtitleBackground">关闭</button>

        <button type="button" class="floating-action-btn floating-action-btn-emerald" @click="resumeSubtitleTaskPanelFromBackground">

          <IconCaptions class="h-3 w-3" :stroke-width="2.3" />恢复工作台

        </button>

      </div>

    </div>



    <div v-if="showFilterDeleteBackgroundCard" class="filter-delete-floating-card">

      <div class="filter-delete-floating-head">

        <div>

          <div class="filter-delete-floating-title">{{ filterDeleteBackgroundState.scopeLabel || '删除过滤任务' }}</div>

          <div class="filter-delete-floating-mode">{{ filterDeleteBackgroundState.mode === 'delete' ? '后台删除中' : '后台预审中' }}</div>

        </div>

        <div class="filter-delete-floating-percent">{{ filterDeleteBackgroundState.percentage }}%</div>

      </div>

      <el-progress

        :percentage="filterDeleteBackgroundState.percentage"

        :status="filterDeleteBackgroundState.progressStatus || undefined"

        :stroke-width="8"

        :show-text="false"

      />

      <div class="filter-delete-floating-text">

        {{ filterDeleteBackgroundPrimaryText }}

      </div>

      <div class="filter-delete-floating-chip-row">

        <span class="filter-delete-floating-chip">状态 {{ filterDeleteBackgroundState.statusLabel }}</span>

        <span v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-chip">命中 {{ filterDeleteBackgroundState.selectedCount }}</span>

        <span v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-chip">规则 {{ filterDeleteBackgroundState.ruleCount }}</span>

        <span v-if="filterDeleteBackgroundState.mode === 'preview' && filterDeleteBackgroundState.previewTargetTotal > 0" class="filter-delete-floating-chip">

          目录 {{ filterDeleteBackgroundState.previewTargetIndex }} / {{ filterDeleteBackgroundState.previewTargetTotal }}

        </span>

        <span v-if="filterDeleteBackgroundState.mode === 'delete' && filterDeleteBackgroundState.deleteTotal" class="filter-delete-floating-chip">

          已删 {{ filterDeleteBackgroundState.deleteDone }} / {{ filterDeleteBackgroundState.deleteTotal }}

        </span>

      </div>

      <div v-if="filterDeleteBackgroundState.currentPath" class="filter-delete-floating-path">

        {{ filterDeleteBackgroundState.currentPath }}

      </div>

      <div v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-stats">

        已扫描 {{ filterDeleteBackgroundState.scannedEntries }}

        <span v-if="filterDeleteBackgroundState.discoveredEntries"> / 已发现 {{ filterDeleteBackgroundState.discoveredEntries }}</span>

        <span v-if="filterDeleteBackgroundState.pendingDirectories"> / 待扫目录 {{ filterDeleteBackgroundState.pendingDirectories }}</span>

        <span v-if="filterDeleteBackgroundState.selectedSizeText"> / 预计 {{ filterDeleteBackgroundState.selectedSizeText }}</span>

      </div>

      <div v-if="filterDeleteBackgroundState.startedAt" class="filter-delete-floating-stats">

        开始 {{ filterDeleteBackgroundState.startedAtText }} / 已运行 {{ filterDeleteBackgroundElapsedText }}

      </div>

      <div v-if="filterDeleteBackgroundState.mode === 'delete' && filterDeleteBackgroundState.deleteTotal" class="filter-delete-floating-stats">

        成功 {{ filterDeleteBackgroundState.deleteDone }} / {{ filterDeleteBackgroundState.deleteTotal }}，失败 {{ filterDeleteBackgroundState.deleteFailed || 0 }}

      </div>

      <div class="filter-delete-floating-actions">

        <el-button size="small" type="primary" @click="resumeFilterDeleteDialog">{{ filterDeleteBackgroundState.reviewable ? '打开预审结果' : '打开' }}</el-button>

        <el-button v-if="filterDeleteBackgroundState.canCancelPreview" size="small" @click="cancelBackgroundFilterDeletePreview">取消预审</el-button>

        <el-button v-if="filterDeleteBackgroundState.canStopDelete" size="small" @click="stopBackgroundFilterDelete">停止删除</el-button>

        <el-button v-if="!filterDeleteBackgroundState.active && filterDeleteBackgroundState.reviewable" size="small" @click="dismissFilterDeleteBackgroundCard">收起</el-button>

      </div>

    </div>

  </div>

</template>



<script setup>

import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'

import { useRoute, useRouter } from 'vue-router'

import { Refresh, Search, Folder, FolderOpened, Delete, Edit, Files, Document, Picture, VideoPlay, Headset, Tickets, ArrowDown } from '@element-plus/icons-vue'

import {

  Captions,

  Minimize2,

  X as IconX,

  Search as IconSearch,

  RefreshCw as IconRefreshCw,

  BarChart3 as IconBarChart,

  CheckSquare as IconCheckSquare,

  ArrowLeft as IconArrowLeft,

  FilterX as IconFilterX,

  Upload as IconUpload,

  ListTodo as IconListTodo,

  Trash2 as IconTrash,

  Pencil as IconPencil,
  File as IconFile,
  FileText as IconFileText,
  Folder as IconFolderTree,
  Music as IconMusic,

  Captions as IconCaptions,

  Sparkles as IconSparkles,

  HardDrive as IconHardDrive,

  Database as IconDatabase,

  Layers as IconLayers,

  FolderInput as IconFolderInput,

} from 'lucide-vue-next'

import { ElMessage } from 'element-plus'

import { configApi, libraryApi, localUploadApi, rjSubtitleApi, taskApi, synologyOtpRequired } from '../api'

import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../composables/useSystemPrompt'

import { useSubtitleTask } from '../composables/useSubtitleTask'

import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'

import AppLottieIcon from '../components/common/AppLottieIcon.vue'

import AppLottieSwitch from '../components/common/AppLottieSwitch.vue'

import AppEmptyState from '../components/common/AppEmptyState.vue'

import clipboardIconAnimation from '../assets/anime/Clipboard.lottie'

import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'
import uploadToCloudAnimation from '../assets/anime/Uploading to cloud.lottie'
import uploadProgressBarAnimation from '../assets/anime/Loading Bar  Progress Bar.lottie'
import successConfettiAnimation from '../assets/anime/success confetti.lottie'

import ServerUploadPreviewDialog from '../components/common/ServerUploadPreviewDialog.vue'

import UploadTaskWorkbenchDialog from '../components/upload/UploadTaskWorkbenchDialog.vue'

import FilterDeleteDialog from '../components/library/FilterDeleteDialog.vue'

import FolderContentsDialog from '../components/library/FolderContentsDialog.vue'

import LibraryMoveDialog from '../components/library/LibraryMoveDialog.vue'

import LibraryRowContextMenu from '../components/library/LibraryRowContextMenu.vue'

import LibraryIndexBadge from '../components/library/LibraryIndexBadge.vue'

import SubtitleWorkbenchStage from '../components/library/subtitle-workbench/SubtitleWorkbenchStage.vue'



const PAGE_SIZES = [10, 20, 50, 100]

const PAGE_SIZE_KEY = 'kikoeru.ui.library.pageSize'

const LIBRARY_ACTION_SCOPE_KEY = 'kikoeru.ui.library.toolbarActionScope'

const SEARCH_RESULT_KIND_KEY = 'kikoeru.ui.library.searchResultKind'

const SEARCH_EXACT_KEY = 'kikoeru.ui.library.searchExact'

const SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'

const SUBTITLE_SCAN_WORKSPACE_KEY = 'kikoeru.ui.library.rjSubtitleScanWorkspace'

const DEFAULT_SORT_BY = 'size'

const DEFAULT_SORT_ORDER = 'desc'

const route = useRoute()

const router = useRouter()

const loading = ref(false)

const statsLoading = ref(false)

const listPolling = ref(false)

const statsPolling = ref(false)

const files = ref([])

const totalFiles = ref(0)

const libraries = ref([])

const selectedLibraryId = ref('')

const searchQuery = ref('')

const searchResultKind = ref(loadString(SEARCH_RESULT_KIND_KEY, 'all'))

const searchExact = ref(loadString(SEARCH_EXACT_KEY, '0') === '1')

const currentPage = ref(loadNumber('kikoeru.ui.library.page', 1))

const pageSize = ref(loadNumber(PAGE_SIZE_KEY, 20))

const toolbarActionScope = ref(loadString(LIBRARY_ACTION_SCOPE_KEY, 'page') === 'all' ? 'all' : 'page')

const sortBy = ref(DEFAULT_SORT_BY)

const sortOrder = ref(DEFAULT_SORT_ORDER)

const selectedRows = ref([])

const selectedRowPaths = ref(new Set())

const batchDeleting = ref(false)

const batchComputingSize = ref(false)

const batchRenaming = ref(false)

const tableRef = ref(null)

const libraryRowContextMenu = ref({ visible: false, x: 0, y: 0, row: null, renderKey: 0 })

const moveDialogState = ref({ visible: false, sourceLibraryId: '', items: [], submitting: false })

const filterDeleteDialogRef = ref(null)

const folderDialogRef = ref(null)

const suppressSortChange = ref(false)

const suppressSelectionChange = ref(false)

const apiRenamingId = ref(null)

const batchApiRenameRunningIds = ref(new Set())

const currentPath = ref('')

const browseRootPath = ref('')

const parentPath = ref('')

const computingSizeId = ref(null)

function createLibrarySearchState (overrides = {}) {

  return {

    active: false,

    query: '',

    rootPath: '',

    truncated: false,

    scannedDirectories: 0,

    globalRemote: false,

    searchedLibraries: 0,

    hitLibraries: 0,

    exactSearch: false,

    resultKind: 'all',

    ...overrides

  }

}

function createSearchResultReturnState (overrides = {}) {

  return {

    active: false,

    libraryId: '',

    searchQuery: '',

    currentPath: '',

    browseRootPath: '',

    page: 1,

    sortBy: DEFAULT_SORT_BY,

    sortOrder: DEFAULT_SORT_ORDER,

    searchExact: false,

    searchResultKind: 'all',

    searchState: createLibrarySearchState(),

    ...overrides

  }

}

const librarySearchState = ref(createLibrarySearchState())

const locatedLibraryPath = ref('')

const pendingLibraryLocate = ref(null)

const pendingLibrarySearchRestore = ref(null)

const searchResultReturnState = ref(createSearchResultReturnState())

const renameDialogVisible = ref(false)

const renameForm = ref({ currentName: '', newName: '', path: '', libraryId: '' })

const isRenaming = ref(false)

const localUploadDialogVisible = ref(false)

const localUploadSubmitting = ref(false)

const localUploadForm = ref({ targetLibraryId: '', targetSubdir: '' })

const trackedUploadTaskIds = ref([])

const trackedUploadTasks = ref([])

const uploadCompletionSyncedTaskIds = ref(new Set())

const uploadWorkbenchVisible = ref(false)

const uploadWorkbenchBackgroundActive = ref(false)

const uploadWorkbenchRefreshing = ref(false)

const LOCAL_UPLOAD_WORKBENCH_KEY = 'prekikoeru.library.uploadWorkbench'

let uploadWorkbenchTimer = null

const processingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'processing'))

const pendingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))))

const completedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'completed'))

const failedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'failed'))

const showUploadBackgroundCard = computed(() => uploadWorkbenchBackgroundActive.value && !uploadWorkbenchVisible.value && trackedUploadTaskIds.value.length > 0)

const activeBackgroundUploadTask = computed(() => processingUploadTasks.value[0] || pendingUploadTasks.value[0] || trackedUploadTasks.value[0] || null)

const uploadBackgroundAggregate = computed(() => {
  const tasks = Array.isArray(trackedUploadTasks.value) ? trackedUploadTasks.value : []
  let totalBytes = 0
  let transferredBytes = 0
  let speedBytes = 0

  tasks.forEach((task) => {
    const runtime = task?.upload_runtime || {}
    const status = String(task?.status || '')
    const taskTotal = Math.max(0, Number(runtime?.total_bytes || task?.task_metadata?.total_bytes || task?.total_bytes || task?.size_bytes || 0))
    let taskTransferred = Math.max(0, Number(runtime?.transferred_bytes || 0))
    if (taskTotal > 0 && ['completed', 'failed'].includes(status)) {
      taskTransferred = Math.max(taskTransferred, taskTotal)
    }
    totalBytes += taskTotal
    transferredBytes += Math.min(taskTransferred, taskTotal || taskTransferred)
    if (status === 'processing') {
      speedBytes += Math.max(0, Number(runtime?.speed_bytes_per_sec || 0))
    }
  })

  if (uploadBackgroundCompleted.value) {
    return {
      totalBytes,
      transferredBytes,
      speedBytes: 0,
    }
  }

  if (speedBytes <= 0) {
    const fallbackTask = processingUploadTasks.value[0] || pendingUploadTasks.value[0] || null
    speedBytes = Math.max(0, Number(fallbackTask?.upload_runtime?.speed_bytes_per_sec || fallbackTask?.upload_runtime?.last_non_zero_speed_bytes_per_sec || 0))
  }

  return {
    totalBytes,
    transferredBytes,
    speedBytes,
  }
})

const uploadBackgroundTotalBytes = computed(() => uploadBackgroundAggregate.value.totalBytes)

const uploadBackgroundSpeedValue = computed(() => uploadBackgroundAggregate.value.speedBytes)

const uploadBackgroundRemainingBytes = computed(() => {
  const total = Math.max(0, Number(uploadBackgroundAggregate.value.totalBytes || 0))
  const transferred = Math.max(0, Number(uploadBackgroundAggregate.value.transferredBytes || 0))
  return Math.max(0, total - transferred)
})

const uploadBackgroundCompleted = computed(() => {
  if (!trackedUploadTasks.value.length) return false
  if (processingUploadTasks.value.length > 0 || pendingUploadTasks.value.length > 0) return false
  return completedUploadTasks.value.length > 0 && failedUploadTasks.value.length === 0
})

const uploadBackgroundTitleText = computed(() => (
  uploadBackgroundCompleted.value ? '上传任务已完成' : '上传任务正在后台运行'
))

const uploadBackgroundDetailText = computed(() => {
  if (uploadBackgroundCompleted.value) {
    const completedCount = completedUploadTasks.value.length
    return completedCount > 0 ? `本批上传已完成，共 ${completedCount} 个任务` : '本批上传已完成'
  }
  return String(activeBackgroundUploadTask.value?.current_step || '').trim()
})

const uploadBackgroundStatusAnimation = computed(() => (
  uploadBackgroundCompleted.value ? successConfettiAnimation : uploadProgressBarAnimation
))

const uploadBackgroundAnimationAutoplay = computed(() => uploadBackgroundCompleted.value)

const uploadBackgroundAnimationLoop = computed(() => uploadBackgroundCompleted.value)

const uploadBackgroundSpeedText = computed(() => {
  const speed = uploadBackgroundSpeedValue.value
  if (speed > 0) return formatSpeed(speed)
  if (uploadBackgroundCompleted.value) return '0 B/s'
  return '—'
})

const uploadBackgroundEtaText = computed(() => {
  if (uploadBackgroundCompleted.value) return '完成'
  const speed = Math.max(0, Number(uploadBackgroundSpeedValue.value || 0))
  const remaining = Math.max(0, Number(uploadBackgroundRemainingBytes.value || 0))
  if (speed > 0 && remaining > 0) {
    return formatEtaSeconds(Math.ceil(remaining / speed))
  }
  if (remaining <= 0 && trackedUploadTasks.value.length > 0) return '已接近完成'
  return '—'
})

const uploadBackgroundPercent = computed(() => {
  const total = Number(uploadBackgroundAggregate.value.totalBytes || 0)
  const transferred = Number(uploadBackgroundAggregate.value.transferredBytes || 0)
  const remaining = Math.max(0, total - transferred)
  const hasProcessing = processingUploadTasks.value.length > 0

  let percent = 0
  if (total > 0) {
    percent = Math.max(0, Math.min(100, Math.floor((transferred / total) * 100)))
  } else if (trackedUploadTasks.value.length > 0) {
    const totalProgress = trackedUploadTasks.value.reduce((sum, task) => sum + Math.max(0, Math.min(100, Number(task?.progress || 0))), 0)
    percent = Math.floor(totalProgress / Math.max(trackedUploadTasks.value.length, 1))
  }

  if (!uploadBackgroundCompleted.value && hasProcessing && remaining > 0) {
    return Math.min(percent, 99)
  }

  return percent

})

const uploadProgressLottieRef = ref(null)
const uploadProgressLottieInstance = ref(null)
const uploadBackgroundProgressLottieKey = computed(() => `${showUploadBackgroundCard.value ? 'visible' : 'hidden'}-${trackedUploadTaskIds.value.join(',')}`)
const uploadProgressAnimatedFrame = ref(0)
const uploadProgressTargetFrame = ref(0)
let uploadProgressAnimationRaf = null

function cancelUploadProgressFrameAnimation() {
  if (uploadProgressAnimationRaf) {
    window.cancelAnimationFrame(uploadProgressAnimationRaf)
    uploadProgressAnimationRaf = null
  }
}

function getUploadProgressLottieInstance() {
  return uploadProgressLottieRef.value?.getDotLottieInstance?.() || null
}

function unbindUploadProgressLottieListeners() {
  cancelUploadProgressFrameAnimation()
  const instance = uploadProgressLottieInstance.value
  if (!instance) return
  instance.removeEventListener?.('ready', syncUploadProgressLottieFrame)
  instance.removeEventListener?.('load', syncUploadProgressLottieFrame)
  uploadProgressLottieInstance.value = null
}

function bindUploadProgressLottieListeners() {
  const instance = getUploadProgressLottieInstance()
  if (!instance || uploadProgressLottieInstance.value === instance) return
  cancelUploadProgressFrameAnimation()
  unbindUploadProgressLottieListeners()
  uploadProgressLottieInstance.value = instance
  instance.addEventListener?.('ready', syncUploadProgressLottieFrame)
  instance.addEventListener?.('load', syncUploadProgressLottieFrame)
}

async function syncUploadProgressLottieFrame() {
  if (uploadBackgroundCompleted.value) return
  const instance = getUploadProgressLottieInstance()
  if (!instance) return

  const percent = Math.max(0, Math.min(99, Number(uploadBackgroundPercent.value || 0)))
  const totalFrames = Number(instance.totalFrames || instance.total_frames || 0)
  if (!Number.isFinite(totalFrames) || totalFrames <= 1) return

  const frame = Math.floor((percent / 100) * (totalFrames - 1))
  uploadProgressTargetFrame.value = frame
  try {
    await instance.setLoop?.(false)
    await instance.pause?.()
    if (!Number.isFinite(uploadProgressAnimatedFrame.value)) {
      uploadProgressAnimatedFrame.value = frame
    }
    if (Math.abs(uploadProgressAnimatedFrame.value - frame) < 0.5) {
      uploadProgressAnimatedFrame.value = frame
      await instance.setFrame?.(frame)
      return
    }
    cancelUploadProgressFrameAnimation()
    const animate = async () => {
      const nextFrame = uploadProgressAnimatedFrame.value + ((uploadProgressTargetFrame.value - uploadProgressAnimatedFrame.value) * 0.18)
      if (Math.abs(uploadProgressTargetFrame.value - nextFrame) < 0.35) {
        uploadProgressAnimatedFrame.value = uploadProgressTargetFrame.value
        uploadProgressAnimationRaf = null
        try {
          await instance.setFrame?.(Math.round(uploadProgressAnimatedFrame.value))
        } catch {
          // 忽略动画实例尚未完全就绪时的瞬时错误
        }
        return
      }
      uploadProgressAnimatedFrame.value = nextFrame
      try {
        await instance.setFrame?.(Math.round(uploadProgressAnimatedFrame.value))
      } catch {
        uploadProgressAnimationRaf = null
        return
      }
      uploadProgressAnimationRaf = window.requestAnimationFrame(() => {
        animate()
      })
    }
    uploadProgressAnimationRaf = window.requestAnimationFrame(() => {
      animate()
    })
  } catch {
    // 忽略动画实例尚未完全就绪时的瞬时错误
  }
}

watch(uploadBackgroundPercent, () => {
  syncUploadProgressLottieFrame()
})

watch(uploadBackgroundCompleted, () => {
  if (uploadBackgroundCompleted.value) {
    cancelUploadProgressFrameAnimation()
  }
  nextTick(() => {
    bindUploadProgressLottieListeners()
    syncUploadProgressLottieFrame()
  })
})

watch(showUploadBackgroundCard, visible => {
  if (!visible) return
  nextTick(() => {
    bindUploadProgressLottieListeners()
    syncUploadProgressLottieFrame()
  })
})

watch(uploadProgressLottieRef, () => {
  uploadProgressAnimatedFrame.value = 0
  uploadProgressTargetFrame.value = 0
  nextTick(() => {
    bindUploadProgressLottieListeners()
    syncUploadProgressLottieFrame()
  })
})

const mappedPathDialogVisible = ref(false)

const mappedPathInfo = ref({ originalPath: '', mappedPath: '', isMapped: false })

const tampermonkeyLoaded = ref(false)

const statsMap = ref({})

const aggregateStats = ref({ folder_count: 0, total_size_gb: 0, total_size_bytes: 0 })

const libraryState = ref({})



function normalizeLibraryPathKey (path) {

  return String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')

}



function getLibraryPageStateKey (path = currentPath.value, rootPath = browseRootPath.value) {

  const normalizedPath = normalizeLibraryPathKey(path)

  const normalizedRootPath = normalizeLibraryPathKey(rootPath)

  return normalizedPath || normalizedRootPath || '__root__'

}



function rememberCurrentDirectoryPage () {

  const libraryId = selectedLibraryId.value

  if (!libraryId) return

  const state = libraryState.value[libraryId] || {}

  const pageByPath = { ...(state.pageByPath || {}) }

  pageByPath[getLibraryPageStateKey()] = currentPage.value

  libraryState.value[libraryId] = {

    ...state,

    pageByPath

  }

}



function getRememberedDirectoryPage (path, fallback = 1, rootPath = browseRootPath.value) {

  const libraryId = selectedLibraryId.value

  if (!libraryId) return fallback

  const state = libraryState.value[libraryId] || {}

  const pageByPath = state.pageByPath || {}

  const remembered = Number(pageByPath[getLibraryPageStateKey(path, rootPath)] || 0)

  return remembered > 0 ? remembered : fallback

}

const labels = {

  pageTitle: '\u5e93\u5b58\u6587\u4ef6\u7ba1\u7406',

  currentLibrary: '\u5f53\u524d\u5e93',

  currentLibraryStats: '\u5f53\u524d\u5e93\u7edf\u8ba1',

  allLibraries: '\u5168\u90e8\u5e93\u5b58'

}

let statsPollTimer = null

let listPollTimer = null

let libraryInitialized = false

let libraryViewActive = false

let libraryKeydownBound = false

let forceLibraryRefreshOnce = false

function createSubtitleScanSessionState () {

  return {

    scannedTargets: 0,

    foundDirectories: 0,

    existingSubtitles: 0,

    noSubtitleTargets: 0,

    createdTasks: 0,

    existingTasks: 0,

    createFailed: 0,

    noAudioTargets: 0,

    noMatchTargets: 0,

    failedTargets: 0

  }

}

const folderDialogVisible = ref(false)

const folderDialogLibraryId = ref('')

const folderDialogPath = ref('')

const folderDialogName = ref('')

const FILTER_DELETE_BG_STORAGE_KEY = 'prekikoeru.library.filterDeleteBackground'

const filterDeleteDialogVisible = ref(false)

const filterDeleteDialogLibraryId = ref('')

const filterDeleteDialogPath = ref('')

const filterDeleteDialogTargetPaths = ref([])

const filterDeleteDialogRules = ref([])

const filterDeleteDialogScopeLabel = ref('')

const filterDeleteDialogIsRemote = ref(false)

const filterDeleteDialogInitialJobId = ref('')

const filterDeleteBackgroundState = ref({

  active: false,

  mode: 'preview',

  status: 'idle',

  statusLabel: '等待中',

  scopeLabel: '',

  progressMessage: '',

  currentPath: '',

  percentage: 0,

  progressStatus: '',

  startedAt: 0,

  startedAtText: '',

  previewTargetIndex: 0,

  previewTargetTotal: 0,

  reviewable: false,

  selectedCount: 0,

  selectedSize: 0,

  selectedSizeText: '',

  scannedEntries: 0,

  discoveredEntries: 0,

  pendingDirectories: 0,

  ruleCount: 0,

  deleteDone: 0,

  deleteTotal: 0,

  deleteFailed: 0,

  canCancelPreview: false,

  canStopDelete: false

})

const filterDeleteBackgroundNow = ref(Date.now())

let filterDeleteBackgroundTimer = null

const filterDeleteBackgroundDismissed = ref(false)

const filterDeleteBackgroundSessionKey = ref('')

const showFilterDeleteBackgroundCard = computed(() => (

  !filterDeleteDialogVisible.value

  && !filterDeleteBackgroundDismissed.value

  && (filterDeleteBackgroundState.value.active || filterDeleteBackgroundState.value.reviewable)

))

const filterDeleteBackgroundElapsedText = computed(() => {

  const startedAt = Number(filterDeleteBackgroundState.value.startedAt || 0)

  if (!startedAt) return '00:00'

  const diffSeconds = Math.max(0, Math.floor((filterDeleteBackgroundNow.value - startedAt) / 1000))

  const hours = Math.floor(diffSeconds / 3600)

  const minutes = Math.floor((diffSeconds % 3600) / 60)

  const seconds = diffSeconds % 60

  if (hours > 0) return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`

  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`

})

const filterDeleteBackgroundPrimaryText = computed(() => {

  if (filterDeleteBackgroundState.value.reviewable && !filterDeleteBackgroundState.value.active) {

    if (filterDeleteBackgroundState.value.selectedCount > 0) {

      return `预审完成，命中 ${filterDeleteBackgroundState.value.selectedCount} 项，点“继续确认”继续删除。`

    }

    return '预审完成，没有需要删除的命中项。'

  }

  return filterDeleteBackgroundState.value.progressMessage || (filterDeleteBackgroundState.value.mode === 'delete' ? '正在后台删除…' : '正在后台预审…')

})

const subtitleDialogVisible = ref(false)

const subtitleDialogBackgroundActive = ref(false)

const subtitleSubmitting = ref(false)

const subtitleConnectivityLoading = ref(false)

const subtitlePreferredSelectionKey = ref('')

const subtitleSelectionLoading = ref(false)

const subtitleSelectionScanDone = ref(0)

const subtitleSelectionScanTotal = ref(0)

const subtitleSelectionScanCurrent = ref('')

const subtitleSelectionRequestToken = ref(0)

const subtitleSelectionSourceItems = ref([])

const subtitleScannedSelectionItems = ref([])

const subtitleScanTargetResults = ref([])

const subtitleScanRetryingPath = ref('')

const subtitleScanSession = ref(createSubtitleScanSessionState())

const isRefreshingCurrentView = ref(false)

const batchApiRenameTargetIds = ref(new Set())

const subtitleDialogSelection = ref([])

const subtitleExecutableCollapsed = ref(false)

const subtitleSkippedCollapsed = ref(false)

const subtitleScanTargetsCollapsed = ref(true)

const subtitleInspectorLoading = ref(false)

const subtitleInspectorDeleting = ref(false)

const subtitleInspectorSearch = ref('')

const subtitleInspectorItems = ref([])

const subtitleInspectorAudioItems = ref([])

const subtitleInspectorAudioSearch = ref('')

const subtitleInspectorSubtitleSearch = ref('')

const subtitleInspectorExpandedIds = ref(new Set())

const subtitleInspectorSelectedIds = ref(new Set())

const subtitleInspectorInfo = ref({

  taskId: '',

  libraryId: '',

  audioLibraryId: '',

  subtitleLibraryId: '',

  folderPath: '',

  subtitleDir: '',

  sourceMode: '',

  sourceLabel: '',

  restoredAt: '',

  activityContext: null,

  manualMatchCompleted: false,

  manualMatchAppliedPairs: 0,

  manualMatchDeletedSubtitles: 0,

  manualMatchMessage: '',

  totalFiles: 0,

  totalSize: 0

})

const subtitleMatchSelection = ref({ audioPath: '', subtitlePath: '' })

const subtitleSequenceMode = ref(false)

const subtitleSequenceSelection = ref({ audioPaths: [], subtitlePaths: [] })

const subtitleLastPairBuildMode = ref('')

const subtitleManualPairs = ref([])

const subtitleSelectedManualPairId = ref('')

const subtitlePairApplying = ref(false)

const subtitleRenameDialogVisible = ref(false)

const subtitleRenameForm = ref({ currentName: '', newName: '', path: '' })

const subtitleRenameLoading = ref(false)

const subtitleInspectorLastSelectedId = ref('')

const subtitleRouteFocusKey = ref('')

const subtitleInspectorLoadSeq = ref(0)

const subtitlePreferencesLoaded = ref(false)

let subtitlePreferencesSaveTimer = null

const subtitleOptions = ref({

  overwriteExisting: false,

  scanDepth: 3,

  enableMetadataMatch: true,

  skipIfExistingSubtitles: false,

  namingStrategy: 'audio',

  useFilterRules: false,

  subtitleFilterRules: [],

  showSourceSearch: true,

  showWrittenFiles: true,

  showDownloadedFiles: true,

  showIssues: true

})

const subtitleSelectionPage = ref(1)

const subtitleSelectionPageSize = 6

const subtitleSelectionFilter = ref('all')

const subtitleScanSkipFilter = ref('all')

const subtitleSkippedSelectionFilter = ref([])

const subtitleForceQueueKey = ref('')

const subtitleAudioFilterMode = ref('all')

const subtitleSubtitleFilterMode = ref('all')

const activeSubtitleWorkbenchStage = ref('overview')

const subtitleWorkbenchRailMode = ref('scan')

const subtitleWorkbenchContextMode = ref('settings')

const subtitleWorkbenchDrawerCollapsed = ref(false)



const {

  sortSubtitleTasksByCreatedAt,

  sortSubtitleTasksForWorkbench,

  subtitleTasks,

  subtitleActiveTaskId,

  subtitleTaskFilter,

  subtitleTaskManualFilter,

  subtitleCancelingId,

  subtitleTasksLoading,

  subtitleBulkClearingScope,

  subtitleTaskDetailPanels,

  subtitleDownloadExpandedMap,

  subtitleIssueExpandedMap,

  subtitleTaskRerunId,

  subtitleDialogSessionActive,

  showSubtitleBackgroundCard,

  visibleSubtitleTasks,

  subtitleTaskSummary,

  subtitleTaskOverview,

  subtitleTaskManualOverview,

  orderedSubtitleTasks,

  subtitleQueueTasks,

  inspectableSubtitleTasks,

  activeSubtitleTask,

  compactSubtitleTasks,

  subtitleClearableTaskCounts,

  activeSubtitleInspectTask,

  subtitleBackgroundActiveTask,

  activeSubtitleTaskProgressLogs,

  linkedSubtitleImportSourceModes,

  normalizeSubtitleTaskSourceMode,

  isLinkedSubtitleImportSourceMode,

  isRJSubtitleTaskCancelled,

  isSubtitleTaskAwaitingManualWork,

  matchesSubtitleTaskFilter,

  matchesSubtitleTaskManualFilter,

  getSubtitleTaskFilterResultCount,

  normalizeSubtitleTaskFilterSelection,

  estimateSubtitleTaskAudioCount,

  estimateSubtitleTaskExistingCount,

  buildSubtitleSelectionKey,

  buildSubtitleTaskSelectionKey,

  findSubtitleTaskBySelection,

  findTaskMatchingPreferredSelection,

  buildSubtitleSelectionItemFromTask,

  getTaskDisplayRJCode,

  getTaskSourceRJCode,

  isHistoryRestoredSubtitleTask,

  isSelectionBackfillSubtitleTask,

  getRJSubtitleTaskStatusLabel,

  getRJSubtitleTaskBaseStatusLabel,

  getRJSubtitleTaskStatusType,

  getRJSubtitleTaskBaseStatusType,

  getRJSubtitleTaskStatusClass,

  getRJSubtitleProgressStatus,

  canCancelRJSubtitleTask,

  canClearCurrentSubtitleTask,

  canRerunSubtitleTask,

  isSubtitleTaskRerunLocked,

  getSubtitleTaskInspectLabel,

  getSubtitleTaskManualStateText,

  getSubtitleTaskManualStateChipClass,

  buildDefaultSubtitleTaskDetailPanels,

  buildSubtitleManualMatchSummary,

  isSubtitleTaskSelected,

  getRJSubtitleLangLabel,

  formatRJSubtitleAttempt,

  getProgressLogLevelLabel,

  formatProgressLogTime,

  normalizeSubtitleWriteError,

  normalizeSubtitleWriteErrors,

  isAudioFileName,

  isSubtitleFileName,

  isSubtitleRelativePath,

  compareSubtitleWorkbenchNames,

  normalizeSubtitleDownloadKey,

  getSubtitleDownloadFiles,

  getSubtitleDownloadDisplayName,

  allSubtitleDownloadsCompleted,

  isSubtitleDownloadExpanded,

  toggleSubtitleDownloadExpanded,

  visibleSubtitleDownloadFiles,

  hiddenSubtitleDownloadCount,

  isSubtitleIssueExpanded,

  toggleSubtitleIssueExpanded,

  visibleSubtitleWriteErrors,

  visibleSubtitleFailedFiles,

  hiddenSubtitleIssueCount,

  sanitizeSubtitleFilterRules,

  resolveAutoActiveSubtitleTask,

  resolveCurrentSubtitleTaskId,

  setSubtitleTaskFilter,

  setSubtitleTaskManualFilter,

  syncSubtitleTaskListState,

  focusSubtitleTask,

  getSubtitleTasksByClearScope,

  markSubtitleTaskManualMatchCompleted,

  markSubtitleSelectionManualMatchCompleted,

  upsertSubtitleSelectionEntry,

  syncSubtitleSelectionState,

  upsertSubtitleTaskLocal,

  normalizeRJSubtitleTaskPayload,

  mergeSubtitleTasksWithOptimistic,

  createOptimisticSubtitleTask,

  clearSubtitleStatusPoll,

  scheduleSubtitleStatusPoll,

  refreshRJSubtitleStatus,

  clearCurrentSubtitleTask,

  clearSubtitleTasksByScope,

  cancelRJSubtitleTask,

  rerunSubtitleTask

} = useSubtitleTask({

  selectedLibraryId,

  subtitleDialogVisible,

  subtitleDialogBackgroundActive,

  subtitleInspectorInfo,

  subtitlePreferredSelectionKey,

  subtitleDialogSelection,

  subtitleForceQueueKey,

  subtitleOptions,

  clearSubtitleInspectorState,

  syncSubtitleInspectorTaskState,

  ensureSubtitleInspectorFocus

})



const currentLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value) || null)

const currentStats = computed(() => statsMap.value[selectedLibraryId.value] || null)

const isRemoteCurrentLibrary = computed(() => currentLibrary.value?.type === 'synology_filestation')

const currentLibraryTypeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b\u670d\u52a1\u5668\u5e93\u5b58' : '\u672c\u5730\u5e93\u5b58')

const currentLibraryScopeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b' : '\u672c\u5730')

const isWritableCurrentLibrary = computed(() => !!currentLibrary.value?.writable)

const remoteUploadLibraries = computed(() => (Array.isArray(libraries.value) ? libraries.value : []).filter(item => item?.type === 'synology_filestation' && item?.enabled !== false))

const hasRemoteUploadLibraries = computed(() => remoteUploadLibraries.value.length > 0)

const isAllSelected = computed(() => files.value.length > 0 && selectedRows.value.length === files.value.length)

// 是否处于根目录层（社团层），只有这一层需要"计算大小"入口
const isAtComputeSizeRoot = computed(() => !currentPath.value || currentPath.value === browseRootPath.value)

// 当前选中行中的目录行（供批量计算使用）
const selectedDirectoryRows = computed(() => selectedRows.value.filter(r => r?.is_directory))

const aggregatePending = computed(() => Object.values(statsMap.value).some(item => item?.status === 'pending'))

const remoteIdleLibraries = computed(() => libraries.value.filter(item => item.type === 'synology_filestation' && ['idle', undefined].includes(statsMap.value[item.id]?.status)).length)

const countedLibraries = computed(() => libraries.value.filter(item => {

  const status = statsMap.value[item.id]?.status

  return status && status !== 'idle'

}).length)

const currentStatsProgress = computed(() => Math.max(0, Math.min(100, Number(currentStats.value?.progress_percent || 0))))

const showCurrentStatsProgress = computed(() => currentStats.value?.status === 'pending' && currentStatsProgress.value > 0)

const canCancelStats = computed(() => currentStats.value?.status === 'pending')

const aggregateProgress = computed(() => {

  const relevant = libraries.value

    .map(item => statsMap.value[item.id])

    .filter(item => item && ['ready', 'pending'].includes(item.status))

  if (!relevant.length) return 0

  const total = relevant.reduce((sum, item) => sum + (item.status === 'ready' ? 100 : Number(item.progress_percent || 0)), 0)

  return Math.max(0, Math.min(100, Number((total / relevant.length).toFixed(2))))

})

const showAggregateProgress = computed(() => aggregatePending.value && aggregateProgress.value > 0)

const aggregateLastCompletedAt = computed(() => {

  const timestamps = Object.values(statsMap.value)

    .map(item => Number(item?.last_completed_at || item?.updated_at || 0))

    .filter(value => Number.isFinite(value) && value > 0)

  return timestamps.length ? Math.max(...timestamps) : null

})

const aggregateSizeText = computed(() => {

  const base = formatGB(aggregateStats.value.total_size_gb)

  return remoteIdleLibraries.value > 0 ? `${base}\uff08\u4ec5\u5df2\u7edf\u8ba1\u5e93\uff09` : base

})

const aggregateSummary = computed(() => {

  if (aggregatePending.value) return `\u7edf\u8ba1\u8fdb\u884c\u4e2d\uff0c\u5df2\u5b8c\u6210 ${aggregateProgress.value.toFixed(0)}%`

  if (remoteIdleLibraries.value > 0) return `\u5f53\u524d\u4ec5\u5305\u542b ${countedLibraries.value}/${libraries.value.length} \u4e2a\u5df2\u7edf\u8ba1\u5e93`

  return `\u5171 ${libraries.value.length} \u4e2a\u5e93`

})

const aggregateDetail = computed(() => {

  if (aggregatePending.value) {

    const ts = aggregateLastCompletedAt.value

    return ts

      ? `\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u5f53\u524d\u4f18\u5148\u663e\u793a\u5df2\u4fdd\u5b58\u7ed3\u679c\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}`

      : '\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u7edf\u8ba1\u7ed3\u679c\u4f1a\u81ea\u52a8\u5237\u65b0'

  }

  if (remoteIdleLibraries.value > 0) return '\u672a\u624b\u52a8\u7edf\u8ba1\u7684\u8fdc\u7a0b\u5e93\u4e0d\u4f1a\u8ba1\u5165\u603b\u6587\u4ef6\u5939\u6570\u548c\u603b\u5927\u5c0f'

  const ts = aggregateLastCompletedAt.value

  return ts ? `\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : ''

})

const canGoParent = computed(() => {

  if (searchResultReturnState.value.active) return true

  return !!parentPath.value && currentPath.value && currentPath.value !== browseRootPath.value

})

const backButtonLabel = computed(() => (searchResultReturnState.value.active ? '返回搜索结果' : '返回上级'))

const currentPathDisplay = computed(() => {

  const normalizedCurrent = (currentPath.value || '').replace(/\\/g, '/')

  const normalizedRoot = (browseRootPath.value || '').replace(/\\/g, '/')

  if (!normalizedCurrent) return '/'

  if (!normalizedRoot) return normalizedCurrent

  if (normalizedCurrent === normalizedRoot) return '/'

  if (normalizedCurrent.startsWith(`${normalizedRoot}/`)) return normalizedCurrent.slice(normalizedRoot.length)

  return normalizedCurrent

})

const librarySearchSummary = computed(() => {

  if (!librarySearchState.value.active) return ''

  const query = librarySearchState.value.query || searchQuery.value.trim()

  const exactText = librarySearchState.value.exactSearch ? '精确' : '模糊'

  const kindText = librarySearchState.value.resultKind === 'folder'

    ? '文件夹'

    : librarySearchState.value.resultKind === 'file'

      ? '文件'

      : '全部'

  const suffix = librarySearchState.value.truncated ? '，结果已按上限截断' : ''

  if (librarySearchState.value.globalRemote) {

    const searchedLibraries = Number(librarySearchState.value.searchedLibraries || 0)

    const hitLibraries = Number(librarySearchState.value.hitLibraries || 0)

    return `真实搜索：跨 ${searchedLibraries} 个远程库搜索 “${query}” (${exactText} / ${kindText}，命中 ${hitLibraries} 个库)${suffix}`

  }

  const scope = currentPathDisplay.value || '/'

  return `真实搜索：在 ${scope} 下搜索 “${query}” (${exactText} / ${kindText})${suffix}`

})



const currentFolderRJCode = computed(() => extractRJCode(currentPath.value || ''))

const currentPageDirectoryRows = computed(() => files.value.filter(row => row?.is_directory))

const toolbarActionScopeLabel = computed(() => toolbarActionScope.value === 'page' ? '当前页目录' : '当前目录')

function normalizeRemoteActionPath (path = '') {

  const normalized = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')

  return normalized || '/'

}



function joinRemoteActionPath (basePath = '', name = '') {

  const normalizedBase = normalizeRemoteActionPath(basePath)

  const normalizedName = String(name || '').trim().replace(/^\/+|\/+$/g, '')

  if (!normalizedName) return normalizedBase

  if (normalizedBase === '/') return `/${normalizedName}`

  return `${normalizedBase}/${normalizedName}`

}



function resolveDirectoryActionPath (row) {

  const rawPath = String(row?.path || '').trim()

  if (!isRemoteCurrentLibrary.value) return rawPath



  const currentDir = normalizeRemoteActionPath(currentPath.value)

  const browseRoot = normalizeRemoteActionPath(browseRootPath.value)

  const parentPath = normalizeRemoteActionPath(row?.parent_path || '')

  const rowPath = normalizeRemoteActionPath(rawPath)

  const rowName = String(row?.name || getFileName(rawPath)).trim()

  const rebuiltPath = rowName ? joinRemoteActionPath(currentDir, rowName) : currentDir

  const withinBrowseRoot = browseRoot === '/' || rowPath === browseRoot || rowPath.startsWith(`${browseRoot}/`)



  if (rowName && parentPath === currentDir) {

    return rebuiltPath

  }

  if (rowName && rawPath && !withinBrowseRoot && currentDir && currentDir !== '/') {

    return rebuiltPath

  }

  return rawPath

}



const toolbarSubtitleScopeRows = computed(() => {

  if (toolbarActionScope.value === 'page') {

    if (currentPageDirectoryRows.value.length) return currentPageDirectoryRows.value

    return currentPath.value ? [{ path: currentPath.value, name: getFileName(currentPath.value), is_directory: true }] : []

  }

  return []

})

const toolbarFilterDeletePaths = computed(() => {

  if (toolbarActionScope.value === 'page') {

    const pagePaths = currentPageDirectoryRows.value.map(resolveDirectoryActionPath).filter(Boolean)

    if (pagePaths.length) return [...new Set(pagePaths)]

    return currentPath.value ? [currentPath.value] : []

  }

  return currentPath.value ? [currentPath.value] : []

})

const canProcessCurrentFolder = computed(() => {

  if (!isWritableCurrentLibrary.value) return false

  if (toolbarActionScope.value === 'page') return toolbarSubtitleScopeRows.value.length > 0

  return !!currentPath.value

})

const selectedFilterDeleteRows = computed(() => selectedRows.value.filter(row => row?.is_directory))

const selectedUploadRows = computed(() => (Array.isArray(selectedRows.value) ? selectedRows.value : []).filter(row => row?.is_directory && row?.path))

const selectedUploadCount = computed(() => selectedUploadRows.value.length)

const selectedUploadSourceItems = computed(() => selectedUploadRows.value.map(row => ({

  name: row?.name || getFileName(row?.path || ''),

  path: row?.path || '',

  size: Number(row?.size || 0),

})).filter(item => item.path))

const canFilterDeleteCurrentFolder = computed(() => {

  if (!isWritableCurrentLibrary.value) return false

  if (toolbarActionScope.value === 'page') return toolbarFilterDeletePaths.value.length > 0

  return !!currentPath.value

})

const libraryTableKey = computed(() => [

  selectedLibraryId.value || 'default',

  currentPath.value || browseRootPath.value || '/',

  currentPage.value,

  pageSize.value,

  sortBy.value,

  sortOrder.value,

  searchQuery.value.trim()

].join('::'))







function createSubtitleFilterRule (overrides = {}) {

  return {

    id: `subtitle-filter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,

    target: 'name',

    name: '',

    pattern: '',

    enabled: true,

    ...overrides

  }

}



function normalizeSubtitleFilterRule (rule = {}) {

  return createSubtitleFilterRule({

    id: rule.id || undefined,

    target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',

    name: String(rule.name || ''),

    pattern: String(rule.pattern || ''),

    enabled: rule.enabled !== false

  })

}



function addSubtitleFilterRule () {

  subtitleOptions.value.subtitleFilterRules = [

    ...(subtitleOptions.value.subtitleFilterRules || []),

    createSubtitleFilterRule()

  ]

}



function removeSubtitleFilterRule (ruleId) {

  subtitleOptions.value.subtitleFilterRules = (subtitleOptions.value.subtitleFilterRules || []).filter(rule => rule.id !== ruleId)

}

function getSubtitleSelectionExistingChips (item) {

  const localExistingCount = Math.max(0, Number(item?.existing_subtitle_count || 0))

  const chips = [{ key: 'local-existing', label: `本地字幕 ${localExistingCount}` }]

  if (item?.kikoeru_has_existing_subtitles) {

    chips.push({ key: 'kikoeru-flag', label: 'Kikoeru 命中' })

  }

  return chips

}



function clearSubtitleInspectorState () {

  subtitleInspectorLoadSeq.value += 1

  subtitleInspectorLoading.value = false

  subtitleInspectorInfo.value = {

    taskId: '',

    libraryId: '',

    audioLibraryId: '',

    subtitleLibraryId: '',

    folderPath: '',

    subtitleDir: '',

    sourceMode: '',

    sourceLabel: '',

    restoredAt: '',

    activityContext: null,

    manualMatchCompleted: false,

    manualMatchAppliedPairs: 0,

    manualMatchDeletedSubtitles: 0,

    manualMatchMessage: '',

    totalFiles: 0,

    totalSize: 0

  }

  subtitleInspectorItems.value = []

  subtitleInspectorAudioItems.value = []

  subtitleInspectorExpandedIds.value = new Set()

  subtitleInspectorSelectedIds.value = new Set()

  subtitleInspectorLastSelectedId.value = ''

  resetSubtitleManualMatchState()

}

const canOpenSubtitleInspectorFilterDeleteDialog = computed(() => {

  const libraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value

  return Boolean(libraryId && String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim())

})

const isLinkedSubtitleImportWorkbench = computed(() => isLinkedSubtitleImportSourceMode(activeSubtitleInspectTask.value?.source_mode || subtitleInspectorInfo.value.sourceMode || ''))

const subtitleManualApplyLabel = computed(() => isLinkedSubtitleImportWorkbench.value ? '重命名并导入' : '一键应用同名')

function matchesSubtitleExecutableFilter (item, filter = subtitleSelectionFilter.value) {

  if (filter === 'all') return true

  if (filter === 'ready') return !item?.queue_state || ['ready', 'checking_subtitle'].includes(item?.queue_state)

  if (filter === 'checking_subtitle') return item?.queue_state === 'checking_subtitle'

  if (filter === 'queued') return item?.queue_state === 'queued'

  if (filter === 'creating') return item?.queue_state === 'creating'

  if (filter === 'skipped_existing') return item?.queue_state === 'skipped_existing'

  if (filter === 'existing_task') return item?.queue_state === 'existing_task'

  if (filter === 'create_failed') return item?.queue_state === 'create_failed'

  return true

}

function isSubtitleSkippedSelectionFilterActive (key) {

  return Array.isArray(subtitleSkippedSelectionFilter.value) && subtitleSkippedSelectionFilter.value.includes(key)

}

function toggleSubtitleSkippedSelectionFilter (key) {

  const current = Array.isArray(subtitleSkippedSelectionFilter.value) ? [...subtitleSkippedSelectionFilter.value] : []

  if (current.includes(key)) {

    subtitleSkippedSelectionFilter.value = current.filter(item => item !== key)

    return

  }

  subtitleSkippedSelectionFilter.value = [...current, key]

}

function matchesSubtitleSkippedSelectionFilter (item, filter = subtitleSkippedSelectionFilter.value) {

  const activeFilters = Array.isArray(filter) ? filter : []

  if (!activeFilters.length) return true

  if (activeFilters.includes('skipped_existing') && ['skipped_existing', 'skipped_kikoeru_existing'].includes(item?.queue_state || '')) {

    return true

  }

  return activeFilters.includes(item?.queue_state || '')

}

const subtitleSelectionDisplayItems = computed(() => subtitleDialogSelection.value)

const subtitleExecutableSelectionItems = computed(() => subtitleDialogSelection.value.filter(item => !String(item?.queue_state || '').startsWith('skipped_')))

const subtitleSelectionFilterOptions = computed(() => ([

  { key: 'all', label: '全部', value: subtitleExecutableSelectionItems.value.length },

  { key: 'ready', label: '待处理', value: subtitleExecutableSelectionItems.value.filter(item => !item?.queue_state || item?.queue_state === 'ready' || item?.queue_state === 'checking_subtitle').length },

  { key: 'checking_subtitle', label: '检测中', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'checking_subtitle').length },

  { key: 'queued', label: '已入任务', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'queued').length },

  { key: 'creating', label: '加入中', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'creating').length },

  { key: 'existing_task', label: '任务已存在', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'existing_task').length },

  { key: 'create_failed', label: '加入失败', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'create_failed').length }

]).filter(item => item.key === 'all' || item.value > 0))

const subtitleExecutableDisplayItems = computed(() => subtitleExecutableSelectionItems.value.filter(item => matchesSubtitleExecutableFilter(item)))

const subtitleSkippedSelectionItems = computed(() => subtitleDialogSelection.value.filter(item => String(item?.queue_state || '').startsWith('skipped_')))

const subtitleSkippedSelectionFilterOptions = computed(() => ([

  { key: 'skipped_existing', label: '已有字幕跳过', value: subtitleSkippedSelectionItems.value.filter(item => ['skipped_existing', 'skipped_kikoeru_existing'].includes(item?.queue_state)).length },

  { key: 'skipped_no_subtitle', label: '远程无字幕', value: subtitleSkippedSelectionItems.value.filter(item => item?.queue_state === 'skipped_no_subtitle').length }

]).filter(item => item.value > 0))

const filteredSubtitleSkippedSelectionItems = computed(() => subtitleSkippedSelectionItems.value.filter(item => matchesSubtitleSkippedSelectionFilter(item)))

const subtitleSelectionTotalPages = computed(() => Math.max(1, Math.ceil(Math.max(subtitleExecutableDisplayItems.value.length, 1) / subtitleSelectionPageSize)))

const subtitleSelectionProgressText = computed(() => {

  if (!subtitleSelectionLoading.value || !subtitleSelectionScanTotal.value) return ''

  const currentName = getFileName(subtitleSelectionScanCurrent.value)

  return currentName

    ? `扫描中 ${subtitleSelectionScanDone.value}/${subtitleSelectionScanTotal.value} · ${currentName}`

    : `扫描中 ${subtitleSelectionScanDone.value}/${subtitleSelectionScanTotal.value}`

})

const subtitlePendingScanResults = computed(() => subtitleScanTargetResults.value.filter(item => item.status === 'pending'))

const subtitleSkippedScanResults = computed(() => subtitleScanTargetResults.value.filter(item => ['no_audio', 'no_match', 'failed'].includes(item.status)))

function matchesSubtitleSkipFilter (item, filter = subtitleScanSkipFilter.value) {

  if (filter === 'all') return true

  return item?.status === filter

}

const subtitleSkippedScanFilterOptions = computed(() => ([

  { key: 'all', label: '全部', value: subtitleSkippedScanResults.value.length },

  { key: 'no_audio', label: '无音频', value: subtitleSkippedScanResults.value.filter(item => item.status === 'no_audio').length },

  { key: 'no_match', label: '未识别', value: subtitleSkippedScanResults.value.filter(item => item.status === 'no_match').length },

  { key: 'failed', label: '失败', value: subtitleSkippedScanResults.value.filter(item => item.status === 'failed').length }

]).filter(item => item.key === 'all' || item.value > 0))

const filteredSubtitleSkippedScanResults = computed(() => subtitleSkippedScanResults.value.filter(item => matchesSubtitleSkipFilter(item)))

const subtitleScanSummary = computed(() => ({

  pending: subtitlePendingScanResults.value.length,

  success: subtitleScanTargetResults.value.filter(item => item.status === 'success').length,

  noAudio: subtitleScanTargetResults.value.filter(item => item.status === 'no_audio').length,

  noMatch: subtitleScanTargetResults.value.filter(item => item.status === 'no_match').length,

  failed: subtitleScanTargetResults.value.filter(item => item.status === 'failed').length

}))

const subtitleScanSessionSummary = computed(() => ([

  { key: 'found', label: '识别RJ', value: subtitleScanSession.value.foundDirectories },

  { key: 'existing', label: '已有字幕跳过', value: subtitleScanSession.value.existingSubtitles },

  { key: 'noSubtitle', label: '远程无字幕跳过', value: subtitleScanSession.value.noSubtitleTargets },

  { key: 'created', label: '加入任务成功', value: subtitleScanSession.value.createdTasks },

  { key: 'exists', label: '任务已存在', value: subtitleScanSession.value.existingTasks },

  { key: 'failed', label: '加入失败', value: subtitleScanSession.value.createFailed }

]).filter(item => item.value > 0))

const pagedSubtitleSelectionItems = computed(() => {

  const start = (subtitleSelectionPage.value - 1) * subtitleSelectionPageSize

  return subtitleExecutableDisplayItems.value.slice(start, start + subtitleSelectionPageSize)

})

const focusedSubtitleSelectionItem = computed(() => {

  if (!subtitleSelectionDisplayItems.value.length) return null

  return subtitleSelectionDisplayItems.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value) || subtitleSelectionDisplayItems.value[0]

})

const activeSubtitleWorkbenchStageLabel = computed(() => ({

  overview: '任务概览',

  pairing: '字幕筛选与配对',

  tree: '字幕树'

}[activeSubtitleWorkbenchStage.value] || '任务概览'))

const subtitleWorkbenchFocusTask = computed(() => activeSubtitleInspectTask.value || activeSubtitleTask.value || null)

const subtitleWorkbenchFocusSelection = computed(() => focusedSubtitleSelectionItem.value || currentFolderSubtitleItem.value || null)

const subtitleWorkbenchFocusTitle = computed(() => {

  const task = subtitleWorkbenchFocusTask.value

  if (task) return getTaskDisplayRJCode(task)

  return subtitleWorkbenchFocusSelection.value?.rjcode || '等待焦点任务'

})

const subtitleWorkbenchFocusSubtitle = computed(() => {

  const task = subtitleWorkbenchFocusTask.value

  if (task) return task.folder_name || getFileName(task.folder_path)

  const selection = subtitleWorkbenchFocusSelection.value

  if (selection) return selection.folder_name || getFileName(selection.folder_path)

  return '从左侧扫描结果或任务队列里选一个焦点项'

})

const subtitleWorkbenchFocusStep = computed(() => {

  const task = subtitleWorkbenchFocusTask.value

  if (task?.current_step) return task.current_step

  const selection = subtitleWorkbenchFocusSelection.value

  if (selection?.queue_message) return selection.queue_message

  return '当前还没有进行中的字幕处理步骤'

})

const subtitleWorkbenchFocusChips = computed(() => {

  const task = subtitleWorkbenchFocusTask.value

  const chips = []

  if (isHistoryRestoredSubtitleTask(task)) chips.push({ key: 'restored', label: '历史恢复', class: 'is-info' })

  if (isSelectionBackfillSubtitleTask(task)) chips.push({ key: 'backfill', label: '结果回填', class: 'is-info' })

  if (task?.awaiting_manual_match) chips.push({ key: 'manual', label: '待手动配对', class: 'is-warning' })

  if (task?.manual_match_completed) chips.push({ key: 'done', label: `已匹配 ${task.manual_match_applied_pairs || 0}`, class: 'is-success' })

  if (task?.subtitle_dir) chips.push({ key: 'tree', label: '可进入字幕树' })

  if (!chips.length && subtitleWorkbenchFocusSelection.value?.queue_state) {

    chips.push({ key: 'selection', label: getSubtitleSelectionQueueLabel(subtitleWorkbenchFocusSelection.value) })

  }

  return chips

})

const subtitleRestoredContextCard = computed(() => {

  const task = activeSubtitleInspectTask.value || subtitleWorkbenchFocusTask.value

  if (!task || (!isHistoryRestoredSubtitleTask(task) && !isSelectionBackfillSubtitleTask(task))) return null

  const normalizedMode = normalizeSubtitleTaskSourceMode(task.source_mode || '')

  const sourceModeLabel = ({

    linked_translation_archive_import: '关联字幕压缩包导入',

    subtitle_folder_import: '字幕目录导入',

    activity_history_restore: '操作记录恢复'

  })[normalizedMode] || (normalizedMode ? normalizedMode.replace(/[_-]+/g, ' / ') : '')

  const restoredAtValue = String(task.restored_at || task.activity_context?.restored_at || task.activity_context?.created_at || task.created_at || '').trim()

  const restoredAtDate = restoredAtValue ? new Date(restoredAtValue) : null

  const restoredAt = restoredAtDate && !Number.isNaN(restoredAtDate.getTime())

    ? restoredAtDate.toLocaleString('zh-CN', { hour12: false })

    : restoredAtValue

  const parseTime = (value) => {

    const ts = Date.parse(String(value || '').trim())

    return Number.isFinite(ts) ? ts : 0

  }

  const start = parseTime(task.started_at || task.activity_context?.started_at || task.created_at || task.restored_at || task.activity_context?.created_at)

  const end = parseTime(task.completed_at || task.activity_context?.completed_at)

  const totalSeconds = start ? Math.max(0, Math.floor(((end || Date.now()) - start) / 1000)) : 0

  const duration = totalSeconds <= 0

    ? (end ? '0秒' : '')

    : totalSeconds >= 3600

      ? `${Math.floor(totalSeconds / 3600)}时${Math.floor((totalSeconds % 3600) / 60)}分${totalSeconds % 60}秒`

      : totalSeconds >= 60

        ? `${Math.floor(totalSeconds / 60)}分${totalSeconds % 60}秒`

        : `${totalSeconds}秒`

  return {

    title: isHistoryRestoredSubtitleTask(task) ? '恢复任务上下文' : '回填任务上下文',

    badge: isHistoryRestoredSubtitleTask(task) ? '操作记录恢复' : '扫描命中回填',

    badgeTone: isHistoryRestoredSubtitleTask(task) ? 'violet' : 'slate',

    statusLabel: getRJSubtitleTaskStatusLabel(task),

    inspectLabel: getSubtitleTaskInspectLabel(task),

    sourceLabel: String(task.source_label || task.activity_context?.source_label || task.snapshot?.source_label || '').trim(),

    sourceModeLabel,

    restoredAt,

    duration,

    folderPath: String(task.folder_path || '').trim(),

    subtitleDir: String(task.subtitle_dir || '').trim(),

    step: String(task.current_step || task.activity_context?.summary || '').trim()

  }

})

const subtitleInspectorRoot = computed(() => buildTree(subtitleInspectorItems.value))

const subtitleInspectorFilteredRoot = computed(() => {

  const keyword = subtitleInspectorSearch.value.trim().toLowerCase()

  return keyword ? filterTree(subtitleInspectorRoot.value, keyword) : subtitleInspectorRoot.value

})

const subtitleInspectorFlatTree = computed(() => flattenTree(subtitleInspectorFilteredRoot.value, 0, subtitleInspectorExpandedIds.value))

const subtitleInspectorHasDirectories = computed(() => subtitleInspectorItems.value.some(item => item?.type === 'dir'))

const subtitleInspectorBusy = computed(() => subtitleInspectorLoading.value || subtitleInspectorDeleting.value || subtitlePairApplying.value)

const subtitleInspectorAudioFiles = computed(() => (

  (subtitleInspectorAudioItems.value || [])

    .filter(item => isAudioFileName(item?.name || '') && !isSubtitleRelativePath(item?.relative_path || item?.name || ''))

    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))

))

const subtitleInspectorSubtitleFiles = computed(() => (

  (subtitleInspectorItems.value || [])

    .filter(item => isSubtitleFileName(item?.name || ''))

    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))

))

const filteredSubtitleInspectorAudioFiles = computed(() => {

  const keyword = subtitleInspectorAudioSearch.value.trim().toLowerCase()

  const items = subtitleInspectorAudioFiles.value.filter(item => {

    if (subtitleAudioFilterMode.value === 'paired') return isAudioPaired(item.path)

    if (subtitleAudioFilterMode.value === 'unpaired') return !isAudioPaired(item.path)

    return true

  })

  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items

})

const filteredSubtitleInspectorSubtitleFiles = computed(() => {

  const keyword = subtitleInspectorSubtitleSearch.value.trim().toLowerCase()

  const items = subtitleInspectorSubtitleFiles.value.filter(item => {

    if (subtitleSubtitleFilterMode.value === 'paired') return isSubtitlePaired(item.path)

    if (subtitleSubtitleFilterMode.value === 'unpaired') return !isSubtitlePaired(item.path)

    return true

  })

  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items

})

const canAddSubtitleManualPair = computed(() => Boolean(subtitleMatchSelection.value.audioPath && subtitleMatchSelection.value.subtitlePath))

const canBuildSequenceSubtitlePairs = computed(() => {

  const audioCount = subtitleSequenceSelection.value.audioPaths.length

  const subtitleCount = subtitleSequenceSelection.value.subtitlePaths.length

  return audioCount > 0 && audioCount === subtitleCount

})

const subtitleInspectorSelectableRows = computed(() => subtitleInspectorFlatTree.value.filter(row => row?.type === 'file' || row?.type === 'dir'))

const subtitleInspectorAllSelected = computed(() => subtitleInspectorSelectableRows.value.length > 0 && subtitleInspectorSelectableRows.value.every(row => subtitleInspectorSelectedIds.value.has(row.id)))

const subtitleInspectorSomeSelected = computed(() => !subtitleInspectorAllSelected.value && subtitleInspectorSelectableRows.value.some(row => subtitleInspectorSelectedIds.value.has(row.id)))

const subtitleInspectorSelectedRows = computed(() => subtitleInspectorFlatTree.value.filter(row => subtitleInspectorSelectedIds.value.has(row.id)))

const subtitleWorkbenchCtx = computed(() => ({

  subtitleInspectorInfo: subtitleInspectorInfo.value,

  subtitleInspectorBusy: subtitleInspectorBusy.value,

  subtitleInspectorLoading: subtitleInspectorLoading.value,

  subtitleInspectorDeleting: subtitleInspectorDeleting.value,

  subtitleInspectorHasDirectories: subtitleInspectorHasDirectories.value,

  subtitleInspectorAudioFiles: subtitleInspectorAudioFiles.value,

  subtitleInspectorFlatTree: subtitleInspectorFlatTree.value,

  subtitleInspectorSelectedRows: subtitleInspectorSelectedRows.value,

  subtitleInspectorSelectedIds: subtitleInspectorSelectedIds.value,

  subtitleInspectorExpandedIds: subtitleInspectorExpandedIds.value,

  activeSubtitleTaskProgressLogs: activeSubtitleTaskProgressLogs.value,

  subtitleInspectorSearch: subtitleInspectorSearch.value,

  subtitleInspectorAudioSearch: subtitleInspectorAudioSearch.value,

  subtitleInspectorSubtitleSearch: subtitleInspectorSubtitleSearch.value,

  subtitleInspectorAllSelected: subtitleInspectorAllSelected.value,

  subtitleInspectorSomeSelected: subtitleInspectorSomeSelected.value,

  inspectableSubtitleTasks: inspectableSubtitleTasks.value,

  activeSubtitleInspectTask: activeSubtitleInspectTask.value,

  activeSubtitleTask: activeSubtitleTask.value,

  subtitleBackgroundActiveTask: subtitleBackgroundActiveTask.value,

  subtitleSequenceMode: subtitleSequenceMode.value,

  subtitleSequenceSelection: subtitleSequenceSelection.value,

  subtitleManualPairs: subtitleManualPairs.value,

  subtitleNamingStrategy: subtitleOptions.value.namingStrategy,

  subtitleSelectedManualPairId: subtitleSelectedManualPairId.value,

  subtitlePairApplying: subtitlePairApplying.value,

  subtitleManualApplyLabel: subtitleManualApplyLabel.value,

  isLinkedSubtitleImportWorkbench: isLinkedSubtitleImportWorkbench.value,

  canOpenSubtitleInspectorFilterDeleteDialog: canOpenSubtitleInspectorFilterDeleteDialog.value,

  subtitleCancelingId: subtitleCancelingId.value,

  subtitleTaskRerunId: subtitleTaskRerunId.value,

  subtitleAudioFilterMode: subtitleAudioFilterMode.value,

  subtitleSubtitleFilterMode: subtitleSubtitleFilterMode.value,

  subtitleMatchSelection: subtitleMatchSelection.value,

  filteredSubtitleInspectorAudioFiles: filteredSubtitleInspectorAudioFiles.value,

  filteredSubtitleInspectorSubtitleFiles: filteredSubtitleInspectorSubtitleFiles.value,

  canBuildSequenceSubtitlePairs: canBuildSequenceSubtitlePairs.value,

  canAddSubtitleManualPair: canAddSubtitleManualPair.value,

  pairingAudioSelectedCount: subtitleSequenceSelection.value.audioPaths.length,

  pairingSubtitleSelectedCount: subtitleSequenceSelection.value.subtitlePaths.length,

  pairingPairCount: subtitleManualPairs.value.length,

  reloadSubtitleInspector,

  expandSubtitleInspectorTree,

  collapseSubtitleInspectorTree,

  inspectSubtitleTask: handleSubtitleWorkbenchInspectTask,

  getTaskDisplayRJCode,

  getTaskSourceRJCode,

  getSubtitleTaskInspectLabel,

  getFileName,

  formatFileSize,

  canCancelRJSubtitleTask,

  canClearCurrentSubtitleTask,

  canRerunSubtitleTask,

  buildAutoSubtitlePairs,

  buildSequenceOrOrderedSubtitlePairs,

  applySubtitleManualPairs,

  openSubtitleInspectorFilterDeleteDialog,

  cancelRJSubtitleTask,

  clearCurrentSubtitleTask,

  rerunSubtitleTask,

  setSubtitleSequenceMode: value => { subtitleSequenceMode.value = value },

  setSubtitleAudioFilterMode: value => { subtitleAudioFilterMode.value = value },

  setSubtitleSubtitleFilterMode: value => { subtitleSubtitleFilterMode.value = value },

  setSubtitleInspectorAudioSearch: value => { subtitleInspectorAudioSearch.value = value },

  setSubtitleInspectorSubtitleSearch: value => { subtitleInspectorSubtitleSearch.value = value },

  setSubtitleInspectorSearch: value => {

    subtitleInspectorSearch.value = value

    onSubtitleInspectorSearchInput()

  },

  setSubtitleSelectedManualPairId: value => { subtitleSelectedManualPairId.value = value },

  isAudioPaired,

  isAudioSuspicious,

  getSubtitleSequenceIndex,

  selectSubtitleAudio,

  addSubtitleManualPair,

  clearSubtitleSequenceSelection,

  clearSubtitleManualPairs,

  getSubtitlePairConfidenceLabel,

  removeSubtitleManualPair,

  isSubtitlePaired,

  isSubtitleSuspicious,

  selectSubtitleFile,

  batchDeleteSubtitleTreeEntries,

  clearSubtitleInspectorSelection,

  toggleAllSubtitleInspectorRows,

  handleSubtitleInspectorRowClick,

  toggleSubtitleInspectorSelect,

  toggleSubtitleInspectorExpand,

  resolveSubtitleTreeIcon,

  formatDate,

  formatProgressLogTime,

  getProgressLogLevelLabel,

  openSubtitleRenameDialog,

  deleteSubtitleTreeEntry

}))



const subtitleScanCtx = computed(() => ({

  subtitleDialogSelection: subtitleDialogSelection.value,

  subtitleExecutableSelectionItems: subtitleExecutableSelectionItems.value,

  subtitleSkippedSelectionItems: subtitleSkippedSelectionItems.value,

  subtitleExecutableDisplayItems: subtitleExecutableDisplayItems.value,

  filteredSubtitleSkippedSelectionItems: filteredSubtitleSkippedSelectionItems.value,

  pagedSubtitleSelectionItems: pagedSubtitleSelectionItems.value,

  subtitleScanTargetResults: subtitleScanTargetResults.value,

  subtitleSkippedScanResults: subtitleSkippedScanResults.value,

  filteredSubtitleSkippedScanResults: filteredSubtitleSkippedScanResults.value,

  subtitleScanSessionSummary: subtitleScanSessionSummary.value,

  subtitleScanSummary: subtitleScanSummary.value,

  subtitleSelectionFilterOptions: subtitleSelectionFilterOptions.value,

  subtitleSkippedSelectionFilterOptions: subtitleSkippedSelectionFilterOptions.value,

  subtitleSkippedScanFilterOptions: subtitleSkippedScanFilterOptions.value,

  subtitleSelectionLoading: subtitleSelectionLoading.value,

  subtitleSelectionProgressText: subtitleSelectionProgressText.value,

  subtitleSelectionTotalPages: subtitleSelectionTotalPages.value,

  subtitleSelectionPage: subtitleSelectionPage.value,

  subtitleSelectionFilter: subtitleSelectionFilter.value,

  subtitleScanSkipFilter: subtitleScanSkipFilter.value,

  subtitleExecutableCollapsed: subtitleExecutableCollapsed.value,

  subtitleSkippedCollapsed: subtitleSkippedCollapsed.value,

  subtitleScanTargetsCollapsed: subtitleScanTargetsCollapsed.value,

  subtitleForceQueueKey: subtitleForceQueueKey.value,

  subtitleScanRetryingPath: subtitleScanRetryingPath.value,

  buildSubtitleSelectionKey,

  buildSubtitleScanTargetResultKey,

  isSubtitleSelectionActive,

  isSubtitleSkippedSelectionFilterActive,

  toggleSubtitleSkippedSelectionFilter,

  getSubtitleSelectionQueueLabel,

  getSubtitleSelectionQueueClass,

  getSubtitleSelectionExistingChips,

  getLibraryLabelById,

  canInspectSubtitleSelectionFolder,

  canRetryCreateSubtitleTaskForSelection,

  canForceCreateSubtitleTaskForSelection,

  focusSubtitleSelectionItem: handleSubtitleWorkbenchSelectSelection,

  inspectSubtitleSelectionFolder: handleSubtitleWorkbenchInspectSelectionFolder,

  forceCreateSubtitleTaskForSelection,

  rescanSubtitleSelectionTarget,

  canRetrySubtitleScanResult,

  getSubtitleScanResultLabel,

  setSubtitleSelectionPage: (v) => { subtitleSelectionPage.value = v },

  setSubtitleSelectionFilter: (v) => { subtitleSelectionFilter.value = v },

  setSubtitleScanSkipFilter: (v) => { subtitleScanSkipFilter.value = v },

  setSubtitleExecutableCollapsed: (v) => { subtitleExecutableCollapsed.value = v },

  setSubtitleSkippedCollapsed: (v) => { subtitleSkippedCollapsed.value = v },

  setSubtitleScanTargetsCollapsed: (v) => { subtitleScanTargetsCollapsed.value = v }

}))



const subtitleConfigCtx = computed(() => ({

  subtitleOptions: subtitleOptions.value,

  restoredContext: subtitleRestoredContextCard.value,

  canOpenSubtitleInspectorFilterDeleteDialog: canOpenSubtitleInspectorFilterDeleteDialog.value,

  pairingAudioSelectedCount: subtitleSequenceSelection.value.audioPaths.length,

  pairingSubtitleSelectedCount: subtitleSequenceSelection.value.subtitlePaths.length,

  pairingPairCount: subtitleManualPairs.value.length,

  canClearSequenceSelection: Boolean(subtitleSequenceSelection.value.audioPaths.length || subtitleSequenceSelection.value.subtitlePaths.length),

  canClearManualPairs: Boolean(subtitleManualPairs.value.length),

  treeSelectedCount: subtitleInspectorSelectedRows.value.length,

  treeVisibleCount: subtitleInspectorFlatTree.value.length,

  treeSearchText: subtitleInspectorSearch.value,

  setTreeSearch: value => {

    subtitleInspectorSearch.value = value

    onSubtitleInspectorSearchInput()

  },

  addSubtitleFilterRule,

  removeSubtitleFilterRule,

  setSubtitleOption: (key, value) => { subtitleOptions.value[key] = value },

  clearSubtitleSequenceSelection,

  clearSubtitleManualPairs,

  openSubtitleInspectorFilterDeleteDialog

}))



const subtitleTaskStageCtx = computed(() => ({

  subtitleQueueTasks: subtitleQueueTasks.value,

  visibleSubtitleTasks: visibleSubtitleTasks.value,

  activeSubtitleTask: activeSubtitleTask.value,

  selectedSubtitleTaskId: String(subtitleInspectorInfo.value.taskId || activeSubtitleTask.value?.id || ''),

  subtitleClearableTaskCounts: subtitleClearableTaskCounts.value,

  subtitleBulkClearingScope: subtitleBulkClearingScope.value,

  subtitleTaskDetailPanels: subtitleTaskDetailPanels.value,

  subtitleOptions: subtitleOptions.value,

  subtitleCancelingId: subtitleCancelingId.value,

  subtitleTaskRerunId: subtitleTaskRerunId.value,

  subtitleTaskManualOverview: subtitleTaskManualOverview.value,

  subtitleTaskManualFilter: subtitleTaskManualFilter.value,

  activeSubtitleTaskProgressLogs: activeSubtitleTaskProgressLogs.value,

  getTaskDisplayRJCode,

  getTaskSourceRJCode,

  getRJSubtitleTaskBaseStatusType,

  getRJSubtitleTaskBaseStatusLabel,

  getRJSubtitleTaskStatusLabel,

  getRJSubtitleTaskStatusClass,

  getRJSubtitleProgressStatus,

  getRJSubtitleLangLabel,

  getFileName,

  getLibraryLabelById,

  isHistoryRestoredSubtitleTask,

  isSelectionBackfillSubtitleTask,

  isSubtitleTaskSelected,

  canCancelRJSubtitleTask,

  canClearCurrentSubtitleTask,

  canRerunSubtitleTask,

  getSubtitleTaskInspectLabel,

  cancelRJSubtitleTask,

  clearCurrentSubtitleTask,

  rerunSubtitleTask,

  clearSubtitleTasksByScope,

  inspectSubtitleTask: handleSubtitleWorkbenchInspectTask,

  selectSubtitleTask: handleSubtitleWorkbenchSelectTask,

  setSubtitleTaskManualFilter,

  getSubtitleDownloadFiles,

  getSubtitleDownloadDisplayName,

  allSubtitleDownloadsCompleted,

  isSubtitleDownloadExpanded,

  toggleSubtitleDownloadExpanded,

  visibleSubtitleDownloadFiles,

  hiddenSubtitleDownloadCount,

  isSubtitleIssueExpanded,

  toggleSubtitleIssueExpanded,

  visibleSubtitleWriteErrors,

  visibleSubtitleFailedFiles,

  hiddenSubtitleIssueCount,

  formatRJSubtitleAttempt,

  formatProgressLogTime,

  getProgressLogLevelLabel

}))

const subtitleWorkbenchStageCtx = computed(() => ({

  railModes: [

    { key: 'scan', label: '扫描命中' },

    { key: 'tasks', label: '执行队列' }

  ],

  railMode: subtitleWorkbenchRailMode.value,

  setRailMode: setSubtitleWorkbenchRailMode,

  stageTabs: [

    { key: 'overview', label: '任务总览', tip: '阶段进度、下载写入和异常回看' },

    { key: 'pairing', label: '筛选与配对', tip: '音频轨、字幕轨和预配对工位' },

    { key: 'tree', label: '字幕文件树', tip: '检索、改名与批量清理' }

  ],

  activeStage: activeSubtitleWorkbenchStage.value,

  activeStageLabel: activeSubtitleWorkbenchStageLabel.value,

  setActiveStage: setActiveSubtitleWorkbenchStage,

  focusTitle: subtitleWorkbenchFocusTitle.value,

  focusSubtitle: subtitleWorkbenchFocusSubtitle.value,

  focusStep: subtitleWorkbenchFocusStep.value,

  focusChips: subtitleWorkbenchFocusChips.value,

  contextMode: subtitleWorkbenchContextMode.value,

  scanCtx: subtitleScanCtx.value,

  taskNavigatorCtx: subtitleTaskStageCtx.value,

  taskOverviewCtx: subtitleTaskStageCtx.value,

  workbenchCtx: subtitleWorkbenchCtx.value,

  configCtx: subtitleConfigCtx.value,

  contextDrawerCtx: {

    modeTitle: ({

      settings: '参数面板',

      pairing: '配对助手',

      tree: '文件工具'

    })[subtitleWorkbenchContextMode.value] || '参数面板',

    modeTip: ({

      settings: '执行策略、过滤规则和任务展示都在这里统一控制。',

      pairing: '顺序点选、配对数量和关键动作提示都集中在右侧。',

      tree: '搜索范围、选中规模和删除风险提示在这里查看。'

    })[subtitleWorkbenchContextMode.value] || '',

    drawerCollapsed: subtitleWorkbenchDrawerCollapsed.value,

    contextMode: subtitleWorkbenchContextMode.value,

    modeOptions: [

      { key: 'settings', label: '参数', shortLabel: '参' },

      { key: 'pairing', label: '配对', shortLabel: '配' },

      { key: 'tree', label: '文件', shortLabel: '文' }

    ],

    setContextMode: setSubtitleWorkbenchContextMode,

    toggleDrawer: toggleSubtitleWorkbenchDrawer

  }

}))



const currentFolderSubtitleItem = computed(() => {

  if (!canProcessCurrentFolder.value || !currentFolderRJCode.value) return null

  return {

    rjcode: currentFolderRJCode.value,

    folder_name: getFileName(currentPath.value),

    folder_path: currentPath.value,

    library_id: selectedLibraryId.value

  }

})

const selectedSubtitleCandidates = computed(() => selectedRows.value.filter(row => canFetchRJSubtitle(row)))

const selectedApiRenameRows = computed(() => selectedRows.value.filter(row => canApiRenameRow(row)))

const apiRenameBusy = computed(() => Boolean(apiRenamingId.value) || batchRenaming.value)



function isBatchApiRenameTarget (row) {

  return batchRenaming.value && batchApiRenameTargetIds.value.has(row?.id)

}



function isBatchApiRenameRunning (row) {

  return batchApiRenameRunningIds.value.has(row?.id)

}



function bindLibraryKeydown () {

  if (libraryKeydownBound) return

  window.addEventListener('keydown', handleSubtitleDialogKeydown)

  libraryKeydownBound = true

}



function unbindLibraryKeydown () {

  if (!libraryKeydownBound) return

  window.removeEventListener('keydown', handleSubtitleDialogKeydown)

  libraryKeydownBound = false

}



function stopLibraryPolling () {

  clearStatsPoll()

  clearListPoll()

  clearSubtitleStatusPoll()

}



async function initializeLibraryPage () {

  if (libraryInitialized) return

  restoreUploadWorkbenchState()

  await loadLibraries()

  await loadRJSubtitlePreferences()

  restoreSubtitleScanWorkspace()

  if (selectedLibraryId.value) {

    await refreshStats(false, { silent: true })

  }

  if (trackedUploadTaskIds.value.length) {

    await refreshUploadWorkbench({ silent: true })

  }

  libraryInitialized = true

}



async function resumeLibraryPage () {

  bindLibraryKeydown()

  await refreshLibrary({ silent: true })

  await refreshStats(false, { silent: true })

  if (trackedUploadTaskIds.value.length) {

    await refreshUploadWorkbench({ silent: true })

  }

  if (subtitleDialogSessionActive.value) {

    await refreshRJSubtitleStatus(false, { silent: true })

  }

}



onMounted(async () => {

  bindLibraryContextMenuDismiss()

  bindLibraryKeydown()

  // \u5148\u6062\u590d\u5220\u9664\u8fc7\u6ee4\u540e\u53f0\u72b6\u6001\uff0c\u907f\u514d\u9875\u9762\u521d\u59cb\u5316\u540e\u88ab\u8986\u76d6

  try {

    const raw = localStorage.getItem(FILTER_DELETE_BG_STORAGE_KEY)

    if (raw) {

      const saved = JSON.parse(raw)

      // \u53ea\u6062\u590d 8 \u5c0f\u65f6\u5185\u7684\u672a\u7ed3\u675f\u72b6\u6001

      const age = Date.now() - Number(saved.savedAt || 0)

      const isStale = age > 8 * 60 * 60 * 1000

      if (!isStale && saved.dialogConfig && (saved.backgroundState?.active || saved.backgroundState?.reviewable)) {

        const cfg = saved.dialogConfig

        filterDeleteDialogLibraryId.value = cfg.libraryId || ''

        filterDeleteDialogPath.value = cfg.path || ''

        filterDeleteDialogTargetPaths.value = cfg.targetPaths || []

        filterDeleteDialogRules.value = cfg.rules || []

        filterDeleteDialogScopeLabel.value = cfg.scopeLabel || ''

        filterDeleteDialogIsRemote.value = !!cfg.isRemote

        filterDeleteDialogInitialJobId.value = saved.jobId || ''

        const bg = saved.backgroundState || {}

        filterDeleteBackgroundState.value = {

          active: Boolean(bg.active),

          mode: bg.mode || 'preview',

          status: bg.status || 'idle',

          statusLabel: bg.status === 'running' ? '\u6267\u884c\u4e2d' : bg.status === 'completed' ? '\u5df2\u5b8c\u6210' : '\u7b49\u5f85\u4e2d',

          scopeLabel: bg.scopeLabel || cfg.scopeLabel || '',

          progressMessage: bg.progressMessage || '',

          currentPath: cfg.path || '',

          percentage: Number(bg.percentage || 0),

          progressStatus: '',

          startedAt: 0,

          startedAtText: '',

          previewTargetIndex: 0,

          previewTargetTotal: 0,

          reviewable: Boolean(bg.reviewable),

          selectedCount: Number(bg.selectedCount || 0),

          selectedSize: Number(bg.selectedSize || 0),

          selectedSizeText: '',

          scannedEntries: 0,

          discoveredEntries: 0,

          pendingDirectories: 0,

          ruleCount: Number(bg.ruleCount || 0),

          deleteDone: Number(bg.deleteDone || 0),

          deleteTotal: Number(bg.deleteTotal || 0),

          deleteFailed: 0,

          canCancelPreview: false,

          canStopDelete: false

        }

        filterDeleteBackgroundDismissed.value = false

      }

    }

  } catch (_) {}

  await initializeLibraryPage()

  libraryViewActive = true

  await consumeSubtitleRouteFocus()

  await consumeSubtitleBatchSelectionRoute()

})



onActivated(async () => {

  bindLibraryContextMenuDismiss()

  if (libraryViewActive) return

  libraryViewActive = true

  await resumeLibraryPage()

  await consumeSubtitleRouteFocus()

  await consumeSubtitleBatchSelectionRoute()

})



onDeactivated(() => {

  libraryViewActive = false

  closeLibraryRowContextMenu()

  unbindLibraryContextMenuDismiss()

  stopLibraryPolling()

  stopUploadWorkbenchPolling()

  unbindLibraryKeydown()

  if (filterDeleteBackgroundTimer) {

    clearInterval(filterDeleteBackgroundTimer)

    filterDeleteBackgroundTimer = null

  }

  cancelUploadProgressFrameAnimation()
  unbindUploadProgressLottieListeners()

})



onBeforeUnmount(() => {

  libraryViewActive = false

  closeLibraryRowContextMenu()

  unbindLibraryContextMenuDismiss()

  stopLibraryPolling()

  stopUploadWorkbenchPolling()

  unbindLibraryKeydown()

  if (subtitlePreferencesSaveTimer) {

    clearTimeout(subtitlePreferencesSaveTimer)

    subtitlePreferencesSaveTimer = null

    configApi.save({ rj_subtitle: buildRJSubtitleConfigPayload(subtitleOptions.value) }).catch(error => {

      console.warn('卸载页面时保存 RJ 字幕设置失败', error)

    })

  }

  if (filterDeleteBackgroundTimer) {

    clearInterval(filterDeleteBackgroundTimer)

    filterDeleteBackgroundTimer = null

  }

  unbindUploadProgressLottieListeners()

})



watch(uploadWorkbenchVisible, () => {

  persistUploadWorkbenchState()

  if (uploadWorkbenchVisible.value) {

    clearStatsPoll()

    clearListPoll()

  }

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



watch(pageSize, async value => {

  storeNumber(PAGE_SIZE_KEY, value)

  currentPage.value = 1

  if (selectedLibraryId.value) await refreshLibrary()

})



watch(currentPage, async (value, oldValue) => {

  if (value === oldValue || !selectedLibraryId.value) return

  storeNumber('kikoeru.ui.library.page', value)

  const forceRefresh = forceLibraryRefreshOnce

  forceLibraryRefreshOnce = false

  await refreshLibrary({ forceRefresh })

})



watch(toolbarActionScope, value => {

  storeString(LIBRARY_ACTION_SCOPE_KEY, value)

})



watch(searchResultKind, value => {

  storeString(SEARCH_RESULT_KIND_KEY, value || 'all')

})



watch(searchExact, value => {

  storeString(SEARCH_EXACT_KEY, value ? '1' : '0')

})



watch(selectedLibraryId, async (newId, oldId) => {

  if (!newId) return

  if (oldId) saveLibraryState(oldId)

  restoreLibraryState(newId)

  if (pendingLibrarySearchRestore.value?.libraryId === newId) {

    const restoreState = pendingLibrarySearchRestore.value

    searchQuery.value = restoreState.searchQuery || ''

    searchExact.value = Boolean(restoreState.searchExact)

    searchResultKind.value = restoreState.searchResultKind || 'all'

    currentPath.value = restoreState.currentPath || ''

    browseRootPath.value = restoreState.browseRootPath || ''

    currentPage.value = Number(restoreState.page || 1)

    sortBy.value = restoreState.sortBy || DEFAULT_SORT_BY

    sortOrder.value = restoreState.sortOrder || DEFAULT_SORT_ORDER

    librarySearchState.value = createLibrarySearchState({

      active: true,

      query: restoreState.searchState?.query || restoreState.searchQuery || '',

      rootPath: restoreState.searchState?.rootPath || restoreState.currentPath || '',

      truncated: Boolean(restoreState.searchState?.truncated),

      scannedDirectories: Number(restoreState.searchState?.scannedDirectories || 0),

      globalRemote: Boolean(restoreState.searchState?.globalRemote),

      searchedLibraries: Number(restoreState.searchState?.searchedLibraries || 0),

      hitLibraries: Number(restoreState.searchState?.hitLibraries || 0),

      exactSearch: Boolean(restoreState.searchState?.exactSearch ?? restoreState.searchExact),

      resultKind: restoreState.searchState?.resultKind || restoreState.searchResultKind || 'all'

    })

    locatedLibraryPath.value = ''

    pendingLibrarySearchRestore.value = null

  }

  if (pendingLibraryLocate.value?.libraryId === newId) {

    const targetPath = pendingLibraryLocate.value.path || ''

    const highlightPath = pendingLibraryLocate.value.highlightPath || targetPath

    searchQuery.value = ''

    librarySearchState.value = createLibrarySearchState()

    currentPath.value = targetPath

    currentPage.value = 1

    locatedLibraryPath.value = highlightPath

    pendingLibraryLocate.value = null

  }

  clearSelection()

  subtitlePreferredSelectionKey.value = ''

  clearSubtitleInspectorState()

  await refreshLibrary()

  refreshStats(false, { silent: true })

})



watch(subtitleExecutableDisplayItems, items => {

  if (!items.length) {

    subtitleSelectionPage.value = 1

    return

  }

  if (subtitleSelectionPage.value > subtitleSelectionTotalPages.value) {

    subtitleSelectionPage.value = subtitleSelectionTotalPages.value

  }

})



watch(subtitleOptions, value => {

  if (!subtitlePreferencesLoaded.value) return

  storeJson(SUBTITLE_OPTIONS_KEY, value)

  scheduleSaveRJSubtitlePreferences(value)

}, { deep: true })



watch([

  subtitleDialogVisible,

  subtitleDialogBackgroundActive,

  subtitleSelectionLoading,

  subtitleSelectionScanDone,

  subtitleSelectionScanTotal,

  subtitleSelectionScanCurrent,

  subtitleSelectionSourceItems,

  subtitleScannedSelectionItems,

  subtitleScanTargetResults,

  subtitleScanRetryingPath,

  subtitleScanSession,

  subtitleDialogSelection,

  subtitlePreferredSelectionKey,

  subtitleSelectionPage,

  subtitleSelectionFilter,

  subtitleScanSkipFilter,

  subtitleSkippedSelectionFilter,

  subtitleExecutableCollapsed,

  subtitleSkippedCollapsed,

  subtitleScanTargetsCollapsed

], () => {

  persistSubtitleScanWorkspace()

}, { deep: true })



watch(() => subtitleOptions.value.namingStrategy, () => {

  syncSubtitlePairTargetNames()

})



watch(subtitleTasks, tasks => {

  hydrateSubtitleSelectionFromTasks(tasks, { sync: true })

}, { deep: true })



watch([subtitleDialogVisible, subtitleDialogBackgroundActive], async ([visible, backgroundActive]) => {

  if (!visible && !backgroundActive) {

    clearSubtitleStatusPoll()

    subtitleActiveTaskId.value = ''

    subtitleScanRetryingPath.value = ''

    subtitleSelectionScanCurrent.value = ''

    return

  }

  if (visible) subtitleActiveTaskId.value = ''

  await refreshRJSubtitleStatus(false, { silent: true })

})



watch(

  () => route.fullPath,

  async () => {

    if (!libraryViewActive) return

    await consumeSubtitleRouteFocus()

  }

)



function loadNumber (key, fallback) {

  try {

    const value = Number(localStorage.getItem(key))

    return Number.isFinite(value) && value > 0 ? value : fallback

  } catch (_) {

    return fallback

  }

}



function storeNumber (key, value) {

  try { localStorage.setItem(key, String(value)) } catch (_) {}

}



function loadString (key, fallback) {

  try {

    const value = localStorage.getItem(key)

    return value || fallback

  } catch (_) {

    return fallback

  }

}



function storeString (key, value) {

  try { localStorage.setItem(key, String(value)) } catch (_) {}

}



function loadJson (key, fallback) {

  try {

    const raw = localStorage.getItem(key)

    return raw ? JSON.parse(raw) : fallback

  } catch (_) {

    return fallback

  }

}



function storeJson (key, value) {

  try { localStorage.setItem(key, JSON.stringify(value)) } catch (_) {}

}



function normalizeRJSubtitleOptions (source = {}) {

  const scanDepth = source?.scanDepth ?? source?.scan_depth ?? (source?.scanOneLevelOnly === true || source?.scan_one_level_only === true ? 1 : 3)

  const namingStrategy = source?.namingStrategy ?? source?.naming_strategy

  const subtitleFilterRules = source?.subtitleFilterRules ?? source?.subtitle_filter_rules

  return {

    overwriteExisting: source?.overwriteExisting ?? source?.overwrite_existing ?? false,

    scanDepth: normalizeRJSubtitleScanDepth(scanDepth),

    enableMetadataMatch: source?.enableMetadataMatch ?? source?.enable_metadata_match ?? true,

    skipIfExistingSubtitles: source?.skipIfExistingSubtitles ?? source?.skip_if_existing_subtitles ?? false,

    namingStrategy: ['audio', 'subtitle'].includes(namingStrategy) ? namingStrategy : 'audio',

    useFilterRules: source?.useFilterRules ?? source?.use_filter_rules ?? false,

    subtitleFilterRules: Array.isArray(subtitleFilterRules) ? subtitleFilterRules.map(rule => normalizeSubtitleFilterRule(rule)) : [],

    showSourceSearch: source?.showSourceSearch ?? source?.show_source_search ?? true,

    showWrittenFiles: source?.showWrittenFiles ?? source?.show_written_files ?? true,

    showDownloadedFiles: source?.showDownloadedFiles ?? source?.show_download_progress ?? true,

    showIssues: source?.showIssues ?? source?.show_issues ?? true

  }

}



function buildRJSubtitleConfigPayload (options = subtitleOptions.value) {

  const scanDepth = normalizeRJSubtitleScanDepth(options.scanDepth)

  return {

    overwrite_existing: Boolean(options.overwriteExisting),

    scan_one_level_only: scanDepth <= 1,

    scan_depth: scanDepth,

    enable_metadata_match: options.enableMetadataMatch !== false,

    skip_if_existing_subtitles: Boolean(options.skipIfExistingSubtitles),

    naming_strategy: options.namingStrategy === 'subtitle' ? 'subtitle' : 'audio',

    use_filter_rules: Boolean(options.useFilterRules),

    subtitle_filter_rules: (options.subtitleFilterRules || []).map(rule => {

      const normalized = normalizeSubtitleFilterRule(rule)

      return {

        name: normalized.name,

        pattern: normalized.pattern,

        target: normalized.target,

        enabled: normalized.enabled !== false

      }

    }),

    show_source_search: options.showSourceSearch !== false,

    show_written_files: options.showWrittenFiles !== false,

    show_download_progress: options.showDownloadedFiles !== false,

    show_issues: options.showIssues !== false

  }

}



function scheduleSaveRJSubtitlePreferences (value = subtitleOptions.value) {

  if (subtitlePreferencesSaveTimer) clearTimeout(subtitlePreferencesSaveTimer)

  const snapshot = normalizeRJSubtitleOptions(value)

  subtitlePreferencesSaveTimer = window.setTimeout(async () => {

    subtitlePreferencesSaveTimer = null

    try {

      await configApi.save({ rj_subtitle: buildRJSubtitleConfigPayload(snapshot) })

    } catch (error) {

      console.warn('RJ 字幕设置保存到后端失败，已保留浏览器本地副本', error)

    }

  }, 450)

}



async function loadLibraries () {

  const data = await libraryApi.listLibraries()

  libraries.value = data.libraries || []

  const validIds = new Set(libraries.value.map(item => item.id))

  const fallbackId = data.default_library_id || libraries.value[0]?.id || ''

  if (!selectedLibraryId.value || !validIds.has(selectedLibraryId.value)) {

    selectedLibraryId.value = fallbackId

    restoreLibraryState(selectedLibraryId.value)

  }

}



function saveLibraryState (libraryId) {

  const existingState = libraryState.value[libraryId] || {}

  const pageByPath = { ...(existingState.pageByPath || {}) }

  pageByPath[getLibraryPageStateKey()] = currentPage.value

  libraryState.value[libraryId] = {

    ...existingState,

    searchQuery: searchQuery.value,

    searchExact: searchExact.value,

    searchResultKind: searchResultKind.value,

    currentPage: currentPage.value,

    currentPath: currentPath.value,

    browseRootPath: browseRootPath.value,

    sortBy: sortBy.value,

    sortOrder: sortOrder.value,

    pageByPath

  }

}



function restoreLibraryState (libraryId) {

  const state = libraryState.value[libraryId] || {}

  searchQuery.value = state.searchQuery || ''

  searchExact.value = Boolean(state.searchExact ?? (loadString(SEARCH_EXACT_KEY, '0') === '1'))

  searchResultKind.value = state.searchResultKind || loadString(SEARCH_RESULT_KIND_KEY, 'all')

  currentPath.value = state.currentPath || ''

  browseRootPath.value = state.browseRootPath || ''

  currentPage.value = getRememberedDirectoryPage(currentPath.value, state.currentPage || 1, browseRootPath.value)

  sortBy.value = state.sortBy || loadString('kikoeru.ui.library.sortBy', DEFAULT_SORT_BY)

  sortOrder.value = state.sortOrder || loadString('kikoeru.ui.library.sortOrder', DEFAULT_SORT_ORDER)

}



function clearStatsPoll () {

  if (statsPollTimer) {

    clearTimeout(statsPollTimer)

    statsPollTimer = null

  }

}



function scheduleStatsPoll (items) {

  clearStatsPoll()

  if (uploadWorkbenchVisible.value) return

  if ((items || []).some(item => item?.status === 'pending')) {

    statsPollTimer = setTimeout(() => refreshStats(false, { silent: true }), 1500)

  }

}



function clearListPoll () {

  if (listPollTimer) {

    clearTimeout(listPollTimer)

    listPollTimer = null

  }

}



function scheduleListPoll (items) {

  clearListPoll()

  if (uploadWorkbenchVisible.value) return

  if (isRemoteCurrentLibrary.value) return

  if ((items || []).some(item => item?.size_status && item.size_status !== 'ready')) {

    listPollTimer = setTimeout(() => refreshLibrary({ silent: true }), 2000)

  }

}



async function refreshStats (forceRefresh = false, options = {}) {

  const { silent = false, refreshLibraryId = null } = options

  clearStatsPoll()

  if (silent) statsPolling.value = true

  else statsLoading.value = true

  try {

    const data = await libraryApi.getStats(forceRefresh, refreshLibraryId)

    const nextMap = {}

    for (const item of data.libraries || []) nextMap[item.library_id] = item

    statsMap.value = nextMap

    aggregateStats.value = data.all_libraries || { folder_count: 0, total_size_gb: 0, total_size_bytes: 0 }

    scheduleStatsPoll(data.libraries || [])

  } catch (error) {

    ElMessage.error(error.response?.data?.detail || error.message || '获取统计失败')

  } finally {

    if (silent) statsPolling.value = false

    else statsLoading.value = false

  }

}



async function handleStatsAction () {

  if (canCancelStats.value) {

    await cancelStats()

    return

  }

  await refreshStats(true, { refreshLibraryId: selectedLibraryId.value })

}



async function cancelStats () {

  if (!selectedLibraryId.value) return

  statsLoading.value = true

  try {

    const data = await libraryApi.cancelStats(selectedLibraryId.value)

    ElMessage.success(data.message || '统计任务已取消')

    await refreshStats(false, { silent: true })

  } catch (error) {

    ElMessage.error(error.response?.data?.detail || error.message || '取消统计失败')

  } finally {

    statsLoading.value = false

  }

}



async function refreshLibrary (options = {}) {

  const { silent = false, forceRefresh = false } = options

  if (!selectedLibraryId.value) return

  const prevSelectedPaths = new Set(selectedRowPaths.value)

  if (prevSelectedPaths.size) {
    suppressSelectionChange.value = true
  }

  clearListPoll()

  if (silent) listPolling.value = true

  else loading.value = true

  try {

    const data = await libraryApi.browseFiles({

      libraryId: selectedLibraryId.value,

      page: currentPage.value,

      pageSize: pageSize.value,

      search: searchQuery.value.trim(),

      searchExact: searchExact.value,

      searchResultKind: searchResultKind.value,

      currentPath: currentPath.value,

      sortBy: sortBy.value,

      sortOrder: sortOrder.value,

      forceRefresh

    })

    files.value = data.files || []

    totalFiles.value = data.total || 0

    if (data.libraries?.length) libraries.value = data.libraries

    if (data.library_id && data.library_id !== selectedLibraryId.value) {

      if (data.auto_locate_path) {

        pendingLibraryLocate.value = {

          libraryId: data.library_id,

          path: data.auto_locate_path,

          highlightPath: data.auto_locate_highlight_path || data.auto_locate_path

        }

      }

      selectedLibraryId.value = data.library_id

      return

    }

    currentPath.value = data.current_path || currentPath.value || data.browse_root_path || ''

    browseRootPath.value = data.browse_root_path || browseRootPath.value || currentPath.value

    parentPath.value = data.parent_path || ''

    librarySearchState.value = createLibrarySearchState({

      active: Boolean(data.search_mode),

      query: data.search_query || searchQuery.value.trim(),

      rootPath: data.search_root_path || '',

      truncated: Boolean(data.search_truncated),

      scannedDirectories: Number(data.scanned_directories || 0),

      globalRemote: Boolean(data.search_global_remote),

      searchedLibraries: Number(data.searched_library_count || 0),

      hitLibraries: Number(data.hit_library_count || 0),

      exactSearch: Boolean(data.search_exact ?? searchExact.value),

      resultKind: data.search_result_kind || searchResultKind.value || 'all'

    })

    scheduleListPoll(files.value)

    const maxPage = Math.max(1, Math.ceil(Math.max(totalFiles.value, 1) / pageSize.value))

    if (currentPage.value > maxPage) currentPage.value = maxPage

    await applyTableSortIndicator()

    await nextTick()

    if (prevSelectedPaths.size) {
      try {
        files.value.forEach(row => {
          if (row?.path && prevSelectedPaths.has(row.path)) {
            tableRef.value?.toggleRowSelection(row, true)
          }
        })
        selectedRows.value = files.value.filter(row => row?.path && prevSelectedPaths.has(row.path))
        selectedRowPaths.value = new Set(selectedRows.value.map(row => row.path).filter(Boolean))
      } finally {
        await nextTick()
      }
    } else {
      selectedRows.value = []
      selectedRowPaths.value = new Set()
    }

  } catch (error) {

    ElMessage.error(error.response?.data?.detail || error.message || '获取库存文件失败')

  } finally {

    if (suppressSelectionChange.value) {
      await nextTick()
      suppressSelectionChange.value = false
    }

    if (silent) listPolling.value = false

    else loading.value = false

  }

}



async function applyTableSortIndicator () {

  await nextTick()

  const order = sortOrder.value === 'asc' ? 'ascending' : 'descending'

  const prop = sortBy.value === 'time' ? 'modified_time' : sortBy.value

  suppressSortChange.value = true

  tableRef.value?.sort(prop, order)

  await nextTick()

  suppressSortChange.value = false

}



async function handleSearch () {

  searchResultReturnState.value = createSearchResultReturnState()

  pendingLibrarySearchRestore.value = null

  locatedLibraryPath.value = ''

  const shouldRefreshNow = currentPage.value === 1

  forceLibraryRefreshOnce = true

  currentPage.value = 1

  if (shouldRefreshNow) {

    await refreshLibrary({ forceRefresh: true })

    forceLibraryRefreshOnce = false

  }

}



async function handleSortChange ({ prop, order }) {

  if (suppressSortChange.value) return

  const nextSortBy = prop === 'modified_time' ? 'time' : (prop || DEFAULT_SORT_BY)

  const nextSortOrder = order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : DEFAULT_SORT_ORDER

  sortBy.value = nextSortBy

  sortOrder.value = nextSortOrder

  storeString('kikoeru.ui.library.sortBy', sortBy.value)

  storeString('kikoeru.ui.library.sortOrder', sortOrder.value)

  saveLibraryState(selectedLibraryId.value)

  const shouldRefreshNow = currentPage.value === 1

  currentPage.value = 1

  if (shouldRefreshNow) await refreshLibrary()

}



function handleSelectionChange (selection) {

  if (suppressSelectionChange.value) return

  selectedRows.value = Array.isArray(selection) ? selection : []

  selectedRowPaths.value = new Set(selectedRows.value.map(row => row?.path).filter(Boolean))

}



function getFileName (path) {

  if (!path) return ''

  return String(path).split(/[\\/]/).pop()

}

function getLibraryRowIconComponent (row) {
  if (row?.is_directory) return IconFolderTree
  const name = String(row?.name || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|ogg|aac|wma)$/.test(name)) return IconMusic
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc)$/.test(name)) return IconFileText
  return IconFile
}

function getLibraryRowIconClass (row) {
  if (row?.is_directory) return 'icon-folder'
  const name = String(row?.name || '').toLowerCase()
  if (/\.(wav|flac)$/.test(name)) return 'icon-audio-lossless'
  if (/\.(mp3|m4a|ogg|aac|wma)$/.test(name)) return 'icon-audio'
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc)$/.test(name)) return 'icon-text'
  return 'icon-file'
}



function getParentPath (path) {

  const normalized = String(path || '').replace(/[\\/]+$/, '')

  if (!normalized) return ''

  const index = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))

  return index >= 0 ? normalized.slice(0, index) : ''

}



function normalizeConflictPathKey (path) {

  return String(path || '')

    .replace(/\\/g, '/')

    .replace(/\/+/g, '/')

    .replace(/\/$/, '')

    .toLowerCase()

}



function buildRenameConflictKey (path, targetName) {

  return `${normalizeConflictPathKey(getParentPath(path))}::${String(targetName || '').trim().toLowerCase()}`

}



function escapeLibrarySearchHtml (value) {

  return String(value ?? '')

    .replace(/&/g, '&amp;')

    .replace(/</g, '&lt;')

    .replace(/>/g, '&gt;')

    .replace(/"/g, '&quot;')

    .replace(/'/g, '&#39;')

}



function escapeLibrarySearchRegExp (value) {

  return String(value ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

}



function renderLibrarySearchHighlight (value) {

  const text = String(value ?? '')

  const keyword = String((librarySearchState.value.query || searchQuery.value || '').trim())

  const escaped = escapeLibrarySearchHtml(text)

  if (!librarySearchState.value.active || !keyword) return escaped

  const pattern = new RegExp(`(${escapeLibrarySearchRegExp(keyword)})`, 'ig')

  return escaped.replace(pattern, '<mark class="library-search-mark">$1</mark>')

}



function extractRJCode (value) {

  if (!value) return null

  const match = String(value).match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)

  return match ? match[0].toUpperCase() : null

}



function formatSize (bytes) {

  const value = Number(bytes || 0)

  if (!value) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']

  let current = value

  let index = 0

  while (current >= 1024 && index < units.length - 1) {

    current /= 1024

    index += 1

  }

  const digits = current >= 100 || index === 0 ? 0 : current >= 10 ? 1 : 2

  return `${current.toFixed(digits)} ${units[index]}`

}



function formatSpeed (bytesPerSec) {

  const value = Number(bytesPerSec || 0)

  return value > 0 ? `${formatSize(value)}/s` : '—'

}



function formatEtaSeconds (seconds) {

  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)))

  if (!totalSeconds) return '—'

  const hours = Math.floor(totalSeconds / 3600)

  const mins = Math.floor(totalSeconds / 60)

  const secs = totalSeconds % 60

  if (hours > 0) return `${hours}时${Math.floor((totalSeconds % 3600) / 60)}分`

  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`

}



function canFetchRJSubtitle (row) {

  return !!row?.is_directory && isWritableCurrentLibrary.value

}



function canApiRenameRow (row) {

  if (!row?.is_directory || !isWritableCurrentLibrary.value) return false

  const detectedRJ = String(row?.rjcode || extractRJCode(row?.path || row?.name) || '').trim()

  return Boolean(detectedRJ)

}



function toRJSubtitleItem (row) {

  if (!row) return null

  return {

    rjcode: row.rjcode || extractRJCode(row.path || row.name),

    folder_name: row.name || getFileName(row.path),

    folder_path: row.path,

    library_id: row.library_id || selectedLibraryId.value,

    search_hit: Boolean(row.search_hit)

  }

}



function toggleAllSelection () {

  if (!files.value.length) return

  if (isAllSelected.value) return clearSelection()

  files.value.forEach(row => tableRef.value?.toggleRowSelection(row, true))

}



function clearSelection () {

  tableRef.value?.clearSelection()

  selectedRows.value = []

  selectedRowPaths.value = new Set()

}



function openLocalUploadDialog () {

  if (isRemoteCurrentLibrary.value) {

    ElMessage.warning('请先切换到本地库存后再上传到服务器')

    return

  }

  if (!selectedUploadRows.value.length) {

    ElMessage.warning('请先选中要上传的目录')

    return

  }

  if (!remoteUploadLibraries.value.length) {

    ElMessage.warning('当前没有可用的服务器库存')

    return

  }

  localUploadForm.value = {

    targetLibraryId: localUploadForm.value.targetLibraryId || remoteUploadLibraries.value[0]?.id || '',

    targetSubdir: localUploadForm.value.targetSubdir || ''

  }

  localUploadDialogVisible.value = true

}



async function submitLocalUpload () {

  const payload = arguments[0] && typeof arguments[0] === 'object' ? arguments[0] : null

  const selectedPaths = Array.isArray(payload?.selected_paths) && payload.selected_paths.length

    ? payload.selected_paths

    : selectedUploadRows.value.map(row => row.path)

  const targetLibraryId = String(payload?.target_library_id || localUploadForm.value.targetLibraryId || '').trim()

  const targetSubdir = String(payload?.target_subdir || localUploadForm.value.targetSubdir || '').trim()



  if (!selectedPaths.length) {

    ElMessage.warning('请先选中要上传的目录')

    return

  }

  if (!targetLibraryId) {

    ElMessage.warning('请选择目标服务器库存')

    return

  }

  localUploadForm.value = {

    targetLibraryId,

    targetSubdir,

  }

  localUploadSubmitting.value = true

  try {

    const sourceBasePath = currentPath.value || browseRootPath.value || currentLibrary.value?.path || ''

    const createdTaskIds = []



    for (const selectedPath of selectedPaths) {

      const requestPayload = {

        source_library_id: selectedLibraryId.value,

        source_base_path: sourceBasePath,

        selected_paths: [selectedPath],

        target_library_id: targetLibraryId,

        target_subdir: targetSubdir,

        circle_name: ''

      }

      const result = await localUploadApi.start(requestPayload)

      if (result?.task_id) {

        createdTaskIds.push(result.task_id)

        rememberUploadTaskId(result.task_id)

      }

    }



    uploadWorkbenchVisible.value = true

    uploadWorkbenchBackgroundActive.value = false

    localUploadDialogVisible.value = false

    persistUploadWorkbenchState()

    await refreshUploadWorkbench()

    ElMessage.success(`已创建 ${createdTaskIds.length || selectedPaths.length} 个目录上传任务`)

    clearSelection()

  } catch (error) {

    ElMessage.error(error.response?.data?.detail || error.message || '上传失败')

  } finally {

    localUploadSubmitting.value = false

  }

}



function persistUploadWorkbenchState () {

  try {

    localStorage.setItem(LOCAL_UPLOAD_WORKBENCH_KEY, JSON.stringify({

      taskIds: trackedUploadTaskIds.value,

      visible: uploadWorkbenchVisible.value,

      background: uploadWorkbenchBackgroundActive.value

    }))

  } catch (_) {}

}



function restoreUploadWorkbenchState () {

  try {

    const raw = JSON.parse(localStorage.getItem(LOCAL_UPLOAD_WORKBENCH_KEY) || '{}')

    trackedUploadTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []

    uploadWorkbenchVisible.value = Boolean(raw.visible && trackedUploadTaskIds.value.length)

    uploadWorkbenchBackgroundActive.value = Boolean(raw.background && trackedUploadTaskIds.value.length)

  } catch (_) {

    trackedUploadTaskIds.value = []

    uploadWorkbenchVisible.value = false

    uploadWorkbenchBackgroundActive.value = false

  }

}



function stopUploadWorkbenchPolling () {

  if (uploadWorkbenchTimer) {

    window.clearTimeout(uploadWorkbenchTimer)

    uploadWorkbenchTimer = null

  }

}



function startUploadWorkbenchPolling () {

  if (!trackedUploadTaskIds.value.length) return

  stopUploadWorkbenchPolling()

  uploadWorkbenchTimer = window.setTimeout(() => {

    refreshUploadWorkbench({ silent: true })

  }, 2000)

}



function rememberUploadTaskId (nextTaskId) {

  const normalized = String(nextTaskId || '').trim()

  if (!normalized) return

  if (trackedUploadTaskIds.value.includes(normalized)) return

  trackedUploadTaskIds.value = [normalized, ...trackedUploadTaskIds.value]

}



async function refreshUploadWorkbench (options = {}) {

  const silent = Boolean(options?.silent)

  if (!trackedUploadTaskIds.value.length) {

    trackedUploadTasks.value = []

    uploadCompletionSyncedTaskIds.value = new Set()

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
    const requestedTaskIds = trackedUploadTaskIds.value.map(id => String(id || '').trim()).filter(Boolean)
    const matchedRequestedTasks = requestedTaskIds
      .map(id => allTasks.find(task => String(task?.id || '').trim() === id))
      .filter(Boolean)
    const matchedRequestedIds = new Set(matchedRequestedTasks.map(task => String(task?.id || '').trim()).filter(Boolean))
    const extraActiveTasks = allTasks.filter((task) => {
      const taskId = String(task?.id || '').trim()
      const status = String(task?.status || '').trim()
      if (!taskId || matchedRequestedIds.has(taskId)) return false
      return ['pending', 'processing', 'paused', 'waiting_retry'].includes(status)
    })
    const nextTrackedTasks = [...matchedRequestedTasks, ...extraActiveTasks]

    trackedUploadTasks.value = nextTrackedTasks

    if (nextTrackedTasks.length) {

      trackedUploadTaskIds.value = nextTrackedTasks.map(task => task.id)

    }



    const knownCompletionIds = new Set(uploadCompletionSyncedTaskIds.value)

    const activeTaskIds = new Set(nextTrackedTasks.map(task => String(task?.id || '').trim()).filter(Boolean))

    knownCompletionIds.forEach((taskId) => {

      if (!activeTaskIds.has(taskId)) knownCompletionIds.delete(taskId)

    })



    let shouldSyncMainView = false

    nextTrackedTasks.forEach((task) => {

      const taskId = String(task?.id || '').trim()

      const status = String(task?.status || '')

      if (!taskId) return

      if (['completed', 'failed'].includes(status) && !knownCompletionIds.has(taskId)) {

        shouldSyncMainView = true

        knownCompletionIds.add(taskId)

      }

      if (['pending', 'processing', 'paused', 'waiting_retry'].includes(status)) {

        knownCompletionIds.delete(taskId)

      }

    })

    uploadCompletionSyncedTaskIds.value = knownCompletionIds



    if (shouldSyncMainView) {

      await Promise.allSettled([refreshLibrary(), refreshStats()])

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



function hideUploadWorkbenchToBackground () {

  uploadWorkbenchVisible.value = false

  uploadWorkbenchBackgroundActive.value = true

  persistUploadWorkbenchState()

}



function resumeUploadWorkbenchFromBackground () {

  uploadWorkbenchBackgroundActive.value = false

  uploadWorkbenchVisible.value = true

  persistUploadWorkbenchState()

}



async function closeUploadWorkbench () {

  const cancellableTaskIds = trackedUploadTasks.value

    .filter(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))

    .map(task => String(task?.id || '').trim())

    .filter(Boolean)



  if (cancellableTaskIds.length) {

    await Promise.allSettled(cancellableTaskIds.map(taskId => taskApi.cancel(taskId)))

  }



  uploadWorkbenchVisible.value = false

  uploadWorkbenchBackgroundActive.value = false

  uploadCompletionSyncedTaskIds.value = new Set()

  trackedUploadTaskIds.value = []

  trackedUploadTasks.value = []

  stopUploadWorkbenchPolling()

  persistUploadWorkbenchState()

}



function getUploadBackgroundSpeed (task) {

  const runtime = task?.upload_runtime || {}

  return Number(runtime?.speed_bytes_per_sec || runtime?.last_non_zero_speed_bytes_per_sec || 0)

}



function formatUploadBackgroundEta (task) {

  if (!task) return '—'

  const status = String(task?.status || '')

  if (['completed', 'failed'].includes(status)) return '完成'

  return formatEtaSeconds(task?.upload_runtime?.eta_seconds || 0)

}



function getUploadBackgroundTargetLabel (task) {

  return String(task?.task_metadata?.final_output_path || task?.task_metadata?.target_path || task?.output_path || '目标路径处理中').trim()

}

function getUploadBackgroundTaskTotalBytes (task) {
  const runtime = task?.upload_runtime || {}
  const metadata = task?.task_metadata || {}
  return Number(runtime?.total_bytes || metadata?.total_bytes || task?.total_bytes || task?.size_bytes || 0)
}



function uniqueSubtitleItems (items) {

  const seen = new Set()

  return items.filter(item => {

    if (!item?.folder_path || !item?.rjcode) return false

    const dedupeKey = `${item.library_id || ''}::${item.folder_path}`

    if (seen.has(dedupeKey)) return false

    seen.add(dedupeKey)

    return true

  })

}



function buildSubtitleScanTargetInput (target) {

  if (!target) return null

  if (typeof target === 'string') {

    return {

      path: target,

      library_id: selectedLibraryId.value,

      name: getFileName(target)

    }

  }

  const path = String(target.scan_target_path || target.folder_path || target.path || '').trim()

  if (!path) return null

  return {

    path,

    library_id: target.library_id || selectedLibraryId.value,

    name: target.folder_name || target.name || getFileName(path)

  }

}



function uniqueSubtitleScanTargets (items) {

  const seen = new Set()

  return (Array.isArray(items) ? items : []).map(buildSubtitleScanTargetInput).filter(item => {

    if (!item?.path) return false

    const key = `${item.library_id || ''}::${item.path}`

    if (seen.has(key)) return false

    seen.add(key)

    return true

  })

}



function buildSubtitleScanTargetResultKey (item = {}) {

  return `${item.library_id || ''}::${item.path || ''}`

}



function normalizeRJSubtitleScanDepth (value) {

  const normalized = Number.parseInt(value, 10)

  if (Number.isNaN(normalized)) return 3

  return Math.max(1, Math.min(normalized, 10))

}



async function loadRJSubtitlePreferences () {

  const localSaved = loadJson(SUBTITLE_OPTIONS_KEY, {})

  let nextOptions = normalizeRJSubtitleOptions(localSaved)

  let loadedFromBackend = false



  try {

    const data = await configApi.get()

    if (data?.rj_subtitle) {

      nextOptions = normalizeRJSubtitleOptions(data.rj_subtitle)

      loadedFromBackend = true

    }

  } catch (error) {

    console.warn('读取后端 RJ 字幕设置失败，使用浏览器本地副本', error)

  }



  const localHasRules = Array.isArray(localSaved?.subtitleFilterRules) && localSaved.subtitleFilterRules.length > 0

  const backendHasRules = Array.isArray(nextOptions.subtitleFilterRules) && nextOptions.subtitleFilterRules.length > 0

  if (loadedFromBackend && !backendHasRules && localHasRules) {

    nextOptions = normalizeRJSubtitleOptions({

      ...nextOptions,

      useFilterRules: localSaved.useFilterRules ?? nextOptions.useFilterRules,

      subtitleFilterRules: localSaved.subtitleFilterRules

    })

  }



  subtitleOptions.value = nextOptions

  storeJson(SUBTITLE_OPTIONS_KEY, nextOptions)

  subtitlePreferencesLoaded.value = true



  if (!loadedFromBackend || (loadedFromBackend && localHasRules && !backendHasRules)) {

    scheduleSaveRJSubtitlePreferences(nextOptions)

  }

}



function normalizeStoredSubtitleScanSession (value = {}) {

  const base = createSubtitleScanSessionState()

  return Object.keys(base).reduce((acc, key) => {

    acc[key] = Math.max(0, Number(value?.[key] || 0))

    return acc

  }, {})

}



function normalizeStoredSubtitleSkippedSelectionFilter (value = []) {

  const allowed = new Set(['skipped_existing', 'skipped_no_subtitle'])

  return Array.isArray(value) ? value.filter(item => allowed.has(String(item || ''))) : []

}



function buildSubtitleScanWorkspaceSnapshot () {

  return {

    dialogVisible: Boolean(subtitleDialogVisible.value),

    backgroundActive: Boolean(subtitleDialogBackgroundActive.value),

    subtitleSelectionLoading: Boolean(subtitleSelectionLoading.value),

    subtitleSelectionScanDone: Math.max(0, Number(subtitleSelectionScanDone.value || 0)),

    subtitleSelectionScanTotal: Math.max(0, Number(subtitleSelectionScanTotal.value || 0)),

    subtitleSelectionScanCurrent: String(subtitleSelectionScanCurrent.value || ''),

    subtitleSelectionSourceItems: uniqueSubtitleItems(subtitleSelectionSourceItems.value || []),

    subtitleScannedSelectionItems: uniqueSubtitleItems(subtitleScannedSelectionItems.value || []),

    subtitleScanTargetResults: (subtitleScanTargetResults.value || []).map(item => normalizeSubtitleScanTargetResult(item)),

    subtitleScanRetryingPath: String(subtitleScanRetryingPath.value || ''),

    subtitleScanSession: normalizeStoredSubtitleScanSession(subtitleScanSession.value),

    subtitleDialogSelection: uniqueSubtitleItems(subtitleDialogSelection.value || []),

    subtitlePreferredSelectionKey: String(subtitlePreferredSelectionKey.value || ''),

    subtitleSelectionPage: Math.max(1, Number(subtitleSelectionPage.value || 1)),

    subtitleSelectionFilter: String(subtitleSelectionFilter.value || 'all'),

    subtitleScanSkipFilter: String(subtitleScanSkipFilter.value || 'all'),

    subtitleSkippedSelectionFilter: normalizeStoredSubtitleSkippedSelectionFilter(subtitleSkippedSelectionFilter.value),

    subtitleExecutableCollapsed: Boolean(subtitleExecutableCollapsed.value),

    subtitleSkippedCollapsed: Boolean(subtitleSkippedCollapsed.value),

    subtitleScanTargetsCollapsed: Boolean(subtitleScanTargetsCollapsed.value)

  }

}



function persistSubtitleScanWorkspace () {

  storeJson(SUBTITLE_SCAN_WORKSPACE_KEY, buildSubtitleScanWorkspaceSnapshot())

}



function restoreSubtitleScanWorkspace () {

  const saved = loadJson(SUBTITLE_SCAN_WORKSPACE_KEY, null)

  if (!saved || typeof saved !== 'object') return



  subtitleSelectionLoading.value = Boolean(saved.subtitleSelectionLoading)

  subtitleSelectionScanDone.value = Math.max(0, Number(saved.subtitleSelectionScanDone || 0))

  subtitleSelectionScanTotal.value = Math.max(0, Number(saved.subtitleSelectionScanTotal || 0))

  subtitleSelectionScanCurrent.value = String(saved.subtitleSelectionScanCurrent || '')

  subtitleSelectionSourceItems.value = uniqueSubtitleItems(saved.subtitleSelectionSourceItems || [])

  subtitleScannedSelectionItems.value = uniqueSubtitleItems(saved.subtitleScannedSelectionItems || [])

  subtitleScanTargetResults.value = Array.isArray(saved.subtitleScanTargetResults)

    ? saved.subtitleScanTargetResults.map(item => normalizeSubtitleScanTargetResult(item))

    : []

  subtitleScanRetryingPath.value = String(saved.subtitleScanRetryingPath || '')

  subtitleScanSession.value = normalizeStoredSubtitleScanSession(saved.subtitleScanSession)

  subtitleDialogSelection.value = uniqueSubtitleItems(saved.subtitleDialogSelection || [])

  subtitlePreferredSelectionKey.value = String(saved.subtitlePreferredSelectionKey || '')

  subtitleSelectionPage.value = Math.max(1, Number(saved.subtitleSelectionPage || 1))

  subtitleSelectionFilter.value = String(saved.subtitleSelectionFilter || 'all')

  subtitleScanSkipFilter.value = String(saved.subtitleScanSkipFilter || 'all')

  subtitleSkippedSelectionFilter.value = normalizeStoredSubtitleSkippedSelectionFilter(saved.subtitleSkippedSelectionFilter)

  subtitleExecutableCollapsed.value = Boolean(saved.subtitleExecutableCollapsed)

  subtitleSkippedCollapsed.value = Boolean(saved.subtitleSkippedCollapsed)

  subtitleScanTargetsCollapsed.value = Boolean(saved.subtitleScanTargetsCollapsed)

  subtitleDialogBackgroundActive.value = Boolean(saved.backgroundActive)

  subtitleDialogVisible.value = Boolean(saved.dialogVisible)

  syncSubtitleSelectionState()

}



async function loadConfiguredFilterRules () {

  try {

    const data = await configApi.get()

    return Array.isArray(data?.filter?.rules)

      ? data.filter.rules.filter(rule => rule?.enabled !== false && String(rule?.pattern || '').trim())

      : []

  } catch (error) {

    console.error('加载过滤规则失败:', error)

    return []

  }

}



function buildMergedSubtitleSelection (directItems, scannedItems) {

  const scannedByKey = new Map(scannedItems.map(item => [buildSubtitleSelectionKey(item), item]))

  const mergedDirectItems = directItems.map(item => {

    const scanned = scannedByKey.get(buildSubtitleSelectionKey(item)) || null

    return {

      ...(scanned || {}),

      ...item,

      rjcode: item.rjcode || scanned?.rjcode || '',

      folder_name: item.folder_name || scanned?.folder_name || getFileName(item.folder_path),

      folder_path: item.folder_path || scanned?.folder_path || '',

      library_id: item.library_id || scanned?.library_id || selectedLibraryId.value,

      audio_count: scanned?.audio_count ?? item.audio_count,

      existing_subtitle_count: scanned?.existing_subtitle_count ?? item.existing_subtitle_count ?? 0,

      status: scanned?.status || item.status || ''

    }

  })

  const directKeys = new Set(mergedDirectItems.map(item => buildSubtitleSelectionKey(item)))

  const additionalScannedItems = scannedItems.filter(item => !directKeys.has(buildSubtitleSelectionKey(item)))

  return uniqueSubtitleItems([...mergedDirectItems, ...additionalScannedItems])

}



function mergeSubtitleSelectionRuntimeState (items, previousItems = subtitleDialogSelection.value) {

  const previousByKey = new Map((Array.isArray(previousItems) ? previousItems : []).map(item => [buildSubtitleSelectionKey(item), item]))

  return uniqueSubtitleItems((Array.isArray(items) ? items : []).map(item => {

    const previous = previousByKey.get(buildSubtitleSelectionKey(item))

    if (!previous) return item

    return {

      ...previous,

      ...item,

      rjcode: item.rjcode || previous.rjcode || '',

      folder_name: item.folder_name || previous.folder_name || getFileName(item.folder_path),

      folder_path: item.folder_path || previous.folder_path || '',

      library_id: item.library_id || previous.library_id || selectedLibraryId.value,

      audio_count: item.audio_count ?? previous.audio_count ?? null,

      downloaded_count: Math.max(Number(item.downloaded_count || 0), Number(previous.downloaded_count || 0)),

      existing_subtitle_count: Math.max(Number(item.existing_subtitle_count || 0), Number(previous.existing_subtitle_count || 0)),

      status: item.status || previous.status || '',

      queue_state: item.queue_state || previous.queue_state || '',

      queue_message: item.queue_message || previous.queue_message || '',

      task_id: item.task_id || previous.task_id || '',

      task_created_at: item.task_created_at || previous.task_created_at || '',

      awaiting_manual_match: Boolean(item.awaiting_manual_match ?? previous.awaiting_manual_match),

      manual_match_completed: Boolean(item.manual_match_completed ?? previous.manual_match_completed),

      manual_match_applied_pairs: Math.max(0, Number(item.manual_match_applied_pairs ?? (previous.manual_match_applied_pairs || 0))),

      manual_match_deleted_subtitles: Math.max(0, Number(item.manual_match_deleted_subtitles ?? (previous.manual_match_deleted_subtitles || 0)))

    }

  }))

}



function updateSubtitleSelectionFromScanned (directItems, scannedItems, { sync = true } = {}) {

  const nextSelection = directItems.length

    ? buildMergedSubtitleSelection(directItems, scannedItems)

    : uniqueSubtitleItems(scannedItems)

  subtitleDialogSelection.value = mergeSubtitleSelectionRuntimeState(nextSelection)

  if (!subtitlePreferredSelectionKey.value) {

    subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(subtitleDialogSelection.value[0]) || ''

  }

  if (sync) syncSubtitleSelectionState()

  return subtitleDialogSelection.value

}



function buildSubtitleSelectionItemsFromTasks (tasks = subtitleTasks.value) {

  return sortSubtitleTasksByCreatedAt(tasks)

    .filter(task => Boolean(task?.folder_path) && Boolean(task?.rjcode || task?.actual_rjcode))

    .map(task => {

      const baseItem = buildSubtitleSelectionItemFromTask(task)

      const existingSubtitleCount = Math.max(

        Number(baseItem.existing_subtitle_count || 0),

        Number(estimateSubtitleTaskExistingCount(task) || 0)

      )

      const awaitingManualMatch = Boolean(task.awaiting_manual_match) && !task.manual_match_completed

      return {

        ...baseItem,

        task_id: task.id || '',

        queue_state: task.manual_match_completed

          ? 'manual_match_completed'

          : (awaitingManualMatch ? 'awaiting_manual_match' : 'queued'),

        queue_message: task.current_step || getRJSubtitleTaskStatusLabel(task),

        downloaded_count: Number(task.downloaded_count || 0),

        existing_subtitle_count: existingSubtitleCount,

        audio_count: baseItem.audio_count ?? estimateSubtitleTaskAudioCount(task),

        status: existingSubtitleCount > 0 ? 'existing' : (baseItem.status || 'ready'),

        awaiting_manual_match: awaitingManualMatch,

        manual_match_completed: Boolean(task.manual_match_completed),

        manual_match_applied_pairs: Math.max(0, Number(task.manual_match_applied_pairs || 0)),

        manual_match_deleted_subtitles: Math.max(0, Number(task.manual_match_deleted_subtitles || 0))

      }

    })

}



function hydrateSubtitleSelectionFromTasks (tasks = subtitleTasks.value, { sync = true } = {}) {

  const taskSelectionItems = buildSubtitleSelectionItemsFromTasks(tasks)

  if (!taskSelectionItems.length) return false



  const existingKeys = new Set((subtitleDialogSelection.value || []).map(item => buildSubtitleSelectionKey(item)))

  const missingTaskItems = taskSelectionItems.filter(item => !existingKeys.has(buildSubtitleSelectionKey(item)))

  if (!missingTaskItems.length) return false



  subtitleSelectionSourceItems.value = uniqueSubtitleItems([

    ...(subtitleSelectionSourceItems.value || []),

    ...missingTaskItems

  ])

  subtitleScannedSelectionItems.value = uniqueSubtitleItems([

    ...(subtitleScannedSelectionItems.value || []),

    ...missingTaskItems

  ])

  subtitleDialogSelection.value = mergeSubtitleSelectionRuntimeState([

    ...(subtitleDialogSelection.value || []),

    ...missingTaskItems

  ])

  if (!subtitlePreferredSelectionKey.value) {

    subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(subtitleDialogSelection.value[0]) || ''

  }

  if (sync) syncSubtitleSelectionState()

  return true

}



function resetSubtitleScanSession () {

  subtitleScanSession.value = createSubtitleScanSessionState()

}



function resetSubtitleScanRunIndicators () {

  subtitleSelectionScanDone.value = 0

  subtitleSelectionScanTotal.value = 0

  subtitleSelectionScanCurrent.value = ''

  subtitleScanTargetResults.value = []

  subtitleScanRetryingPath.value = ''

  resetSubtitleScanSession()

}



function clearSubtitleScanWorkspace () {

  subtitleSelectionLoading.value = false

  subtitleSelectionScanDone.value = 0

  subtitleSelectionScanTotal.value = 0

  subtitleSelectionScanCurrent.value = ''

  subtitleSelectionSourceItems.value = []

  subtitleScannedSelectionItems.value = []

  subtitleScanTargetResults.value = []

  subtitleScanRetryingPath.value = ''

  resetSubtitleScanSession()

  subtitleSelectionPage.value = 1

  subtitleSelectionFilter.value = 'all'

  subtitleScanSkipFilter.value = 'all'

  subtitleSkippedSelectionFilter.value = []

  subtitleForceQueueKey.value = ''

  subtitleDialogSelection.value = []

  subtitlePreferredSelectionKey.value = ''

}



function patchSubtitleScanSession (patch = {}) {

  subtitleScanSession.value = {

    ...subtitleScanSession.value,

    ...patch

  }

}



function incrementSubtitleScanSession (key, amount = 1) {

  subtitleScanSession.value = {

    ...subtitleScanSession.value,

    [key]: Number(subtitleScanSession.value[key] || 0) + amount

  }

}



function buildSubtitleScanTargetSummary (summary = {}) {

  return {

    found: Number(summary.found || 0),

    ready: Number(summary.ready || 0),

    existing: Number(summary.existing || 0),

    noAudio: Number(summary.no_audio || summary.noAudio || 0),

    queued: Number(summary.queued || 0),

    skippedExisting: Number(summary.skipped_existing || summary.skippedExisting || 0),

    skippedNoSubtitle: Number(summary.skipped_no_subtitle || summary.skippedNoSubtitle || 0),

    existingTask: Number(summary.existing_task || summary.existingTask || 0),

    createFailed: Number(summary.create_failed || summary.createFailed || 0)

  }

}



function mergeSubtitleScanTargetSummary (current = {}, patch = {}) {

  const left = buildSubtitleScanTargetSummary(current)

  const right = buildSubtitleScanTargetSummary(patch)

  return {

    found: Math.max(left.found, right.found),

    ready: Math.max(left.ready, right.ready),

    existing: Math.max(left.existing, right.existing),

    noAudio: Math.max(left.noAudio, right.noAudio),

    queued: Math.max(left.queued, right.queued),

    skippedExisting: Math.max(left.skippedExisting, right.skippedExisting),

    skippedNoSubtitle: Math.max(left.skippedNoSubtitle, right.skippedNoSubtitle),

    existingTask: Math.max(left.existingTask, right.existingTask),

    createFailed: Math.max(left.createFailed, right.createFailed)

  }

}



function buildSubtitleScanTargetMessage (status, summary = {}, fallback = '') {

  if (status === 'pending') return fallback || '正在扫描...'

  if (status === 'failed' && !buildSubtitleScanTargetSummary(summary).found) return fallback || '扫描失败'

  const normalized = buildSubtitleScanTargetSummary(summary)

  const parts = []

  if (normalized.found) parts.push(`识别到 ${normalized.found} 个 RJ 目录`)

  if (normalized.queued) parts.push(`已入任务 ${normalized.queued} 个`)

  if (normalized.skippedExisting) parts.push(`已有字幕跳过 ${normalized.skippedExisting} 个`)

  if (normalized.skippedNoSubtitle) parts.push(`远程无字幕跳过 ${normalized.skippedNoSubtitle} 个`)

  if (normalized.existingTask) parts.push(`任务已存在 ${normalized.existingTask} 个`)

  if (normalized.createFailed) parts.push(`加入失败 ${normalized.createFailed} 个`)

  if (!parts.length && fallback) return fallback

  return parts.join('，')

}



function normalizeSubtitleScanTargetResult (result = {}) {

  const path = String(result.path || '')

  const name = String(result.name || getFileName(path) || '未命名目录')

  const status = ['pending', 'success', 'no_audio', 'no_match', 'failed'].includes(result.status) ? result.status : 'pending'

  const summary = buildSubtitleScanTargetSummary(result.summary || {})

  return {

    path,

    library_id: result.library_id || '',

    name,

    status,

    summary,

    message: String(result.message || buildSubtitleScanTargetMessage(status, summary))

  }

}



function upsertSubtitleScanTargetResult (result = {}) {

  const normalized = normalizeSubtitleScanTargetResult(result)

  const next = [...subtitleScanTargetResults.value]

  const targetKey = buildSubtitleScanTargetResultKey(normalized)

  const index = next.findIndex(item => buildSubtitleScanTargetResultKey(item) === targetKey)

  if (index >= 0) {

    const mergedSummary = mergeSubtitleScanTargetSummary(next[index].summary, normalized.summary)

    next[index] = {

      ...next[index],

      ...normalized,

      summary: mergedSummary,

      message: buildSubtitleScanTargetMessage(normalized.status || next[index].status, mergedSummary, normalized.message || next[index].message)

    }

  } else {

    next.push({

      ...normalized,

      message: buildSubtitleScanTargetMessage(normalized.status, normalized.summary, normalized.message)

    })

  }

  subtitleScanTargetResults.value = next

}



function incrementSubtitleScanTargetCounter (target, key, amount = 1, extras = {}) {

  const targetInput = buildSubtitleScanTargetInput(target)

  if (!targetInput?.path) return

  const targetKey = buildSubtitleScanTargetResultKey(targetInput)

  const current = subtitleScanTargetResults.value.find(item => buildSubtitleScanTargetResultKey(item) === targetKey)

  const currentSummary = buildSubtitleScanTargetSummary(current?.summary || {})

  const nextSummary = {

    ...currentSummary,

    [key]: Number(currentSummary[key] || 0) + amount

  }

  upsertSubtitleScanTargetResult({

    path: targetInput.path,

    library_id: extras.library_id || targetInput.library_id || current?.library_id || '',

    name: extras.name || current?.name || targetInput.name || getFileName(targetInput.path),

    status: extras.status || current?.status || 'pending',

    summary: nextSummary,

    message: buildSubtitleScanTargetMessage(extras.status || current?.status || 'pending', nextSummary, extras.message || current?.message || '')

  })

}



function removeSubtitleScanTargetResult (path) {

  const target = buildSubtitleScanTargetInput(path)

  const targetKey = buildSubtitleScanTargetResultKey(target || {})

  subtitleScanTargetResults.value = subtitleScanTargetResults.value.filter(item => buildSubtitleScanTargetResultKey(item) !== targetKey)

}



function getSubtitleScanResultLabel (status) {

  switch (status) {

    case 'success':

      return '成功'

    case 'no_audio':

      return '无音频'

    case 'no_match':

      return '未识别'

    case 'failed':

      return '扫描失败'

    default:

      return '扫描中'

  }

}



function getSubtitleSelectionStatusLabel (status) {

  if (status === 'existing') return '已有字幕'

  return '可执行'

}



function getSubtitleSelectionQueueLabel (item) {

  switch (item?.queue_state) {

    case 'awaiting_manual_match':

      return '待手动配对'

    case 'manual_match_completed':

      return '已匹配完成'

    case 'checking_subtitle':

      return '检测远程字幕中'

    case 'creating':

      return '加入任务中'

    case 'queued':

      return '已入任务'

    case 'existing_task':

      return '任务已存在'

    case 'skipped_existing':

      return '已有字幕跳过'

    case 'skipped_kikoeru_existing':

      return 'Kikoeru字幕跳过'

    case 'skipped_no_subtitle':

      return '远程无字幕跳过'

    case 'create_failed':

      return '加入失败'

    default:

      return getSubtitleSelectionStatusLabel(item?.status || 'ready')

  }

}



function getSubtitleSelectionQueueClass (item) {

  switch (item?.queue_state) {

    case 'manual_match_completed':

      return 'subtitle-mini-chip-success'

    case 'awaiting_manual_match':

    case 'checking_subtitle':

    case 'creating':

      return 'subtitle-mini-chip-warning'

    case 'queued':

    case 'existing_task':

      return 'subtitle-mini-chip-primary'

    case 'create_failed':

      return 'subtitle-mini-chip-danger'

    case 'skipped_existing':

    case 'skipped_kikoeru_existing':

    case 'skipped_no_subtitle':

      return 'subtitle-mini-chip-muted'

    default:

      return item?.status === 'existing' ? 'subtitle-mini-chip-muted' : 'subtitle-mini-chip-success'

  }

}



function canRetrySubtitleScanResult (item) {

  return Boolean(item?.path) && ['no_audio', 'no_match', 'failed', 'error'].includes(String(item?.status || ''))

}



function shouldDelayAutoInspectSelectionFolder (item) {

  const matchedTask = findSubtitleTaskBySelection(item)

  if (!matchedTask?.id) return false

  if (!matchedTask.force_rerun) return false

  if (matchedTask.subtitle_dir) return false

  return ['pending', 'processing'].includes(String(matchedTask.status || ''))

}



function canInspectSubtitleSelectionFolder(item) {

  if (!item?.folder_path) return false

  const matchedTask = findSubtitleTaskBySelection(item)

  if (item?.task_id && matchedTask?.subtitle_dir) return false

  if (shouldDelayAutoInspectSelectionFolder(item)) return false

  if (item?.status === 'existing') return true

  if (Number(item?.existing_subtitle_count || 0) > 0) return true

  if (Boolean(item?.awaiting_manual_match)) return true

  return ['skipped_existing', 'manual_match_completed', 'awaiting_manual_match'].includes(String(item?.queue_state || ''))

}



function canForceCreateSubtitleTaskForSelection(item) {

  return canInspectSubtitleSelectionFolder(item)

}



function canRetryCreateSubtitleTaskForSelection(item) {

  return Boolean(item?.folder_path) && String(item?.queue_state || '') === 'create_failed'

}



async function ensureRJSubtitleAvailabilityForItem (item) {

  const rjcode = String(item?.rjcode || '').trim().toUpperCase()

  if (!rjcode) {

    return {

      hasSubtitle: false,

      message: '未识别到 RJ 号，已跳过',

      attempts: []

    }

  }



  const data = await rjSubtitleApi.checkSubtitleAvailability(rjcode)

  const selectedSource = data?.selected_source || null

  if (data?.has_subtitle && selectedSource) {

    const subtitleCount = Number(selectedSource.subtitle_count || 0)

    return {

      hasSubtitle: true,

      message: subtitleCount > 0 ? `asmr.one 检测到 ${subtitleCount} 个字幕文件` : 'asmr.one 已检测到可用字幕',

      attempts: data?.attempts || [],

      selectedSource

    }

  }



  const attempts = Array.isArray(data?.attempts) ? data.attempts : []

  const readableReason = attempts.length

    ? '远程无字幕（asmr.one 未发现可用字幕）'

    : (data?.error || '远程无字幕（asmr.one 未发现可用字幕）')

  return {

    hasSubtitle: false,

    message: readableReason,

    attempts

  }

}



async function ensureRJSubtitleExistingStateForItem (item) {

  const folderPath = String(item?.folder_path || '').trim()

  const libraryId = String(item?.library_id || selectedLibraryId.value || '').trim()

  if (!folderPath || !libraryId) {

    return {

      hasExistingSubtitles: Number(item?.existing_subtitle_count || 0) > 0,

      existingSubtitleCount: Number(item?.existing_subtitle_count || 0),

      subtitleDir: '',

      message: ''

    }

  }



  const data = await rjSubtitleApi.checkFolderSubtitleState(folderPath, {

    libraryId

  })

  const existingSubtitleCount = Number(data?.existing_subtitle_count || 0)

  return {

    hasExistingSubtitles: Boolean(data?.has_existing_subtitles),

    existingSubtitleCount,

    subtitleDir: String(data?.subtitle_dir || ''),

    message: existingSubtitleCount > 0 ? `现有字幕 ${existingSubtitleCount} 个` : ''

  }

}



async function resolveRJSubtitleItems (paths, options = {}) {

  const { onChunk, onProgress, onTargetResult } = options

  const scanTargets = uniqueSubtitleScanTargets(paths)

  const collected = []

  const total = scanTargets.length

  let done = 0

  for (const target of scanTargets) {

    const path = target.path

    const libraryId = target.library_id || selectedLibraryId.value

    onProgress?.({ done, total, currentPath: path, libraryId })

    try {

      await rjSubtitleApi.scanStream(path, {

        libraryId,

        scanDepth: normalizeRJSubtitleScanDepth(subtitleOptions.value.scanDepth),

        onEvent: async event => {

          if (!event || typeof event !== 'object') return

          if (event.type === 'progress') {

            onProgress?.({

              done,

              total,

              currentPath: event.current_path || event.path || path,

              libraryId

            })

            onTargetResult?.({

              path: event.path || path,

              library_id: libraryId,

              name: target.name || getFileName(path),

              status: 'pending',

              message: event.message || '正在扫描...'

            })

            return

          }

          if (event.type === 'target_result') {

            const result = normalizeSubtitleScanTargetResult({

              path: event.path || path,

              library_id: libraryId,

              name: event.name || target.name || getFileName(path),

              status: event.status || 'pending',

              summary: event.summary || {},

              message: event.message || ''

            })

            if (result.status === 'no_match') incrementSubtitleScanSession('noMatchTargets')

            if (result.status === 'failed') incrementSubtitleScanSession('failedTargets')

            onTargetResult?.(result)

            return

          }

          if (event.type === 'item') {

            const item = event.item || {}

            const resolvedItem = {

              rjcode: item.rjcode,

              folder_name: item.folder_name,

              folder_path: item.folder_path,

              library_id: libraryId,

              scan_target_path: path,

              audio_count: item.audio_count,

              existing_subtitle_count: item.existing_subtitle_count,

              status: item.status

            }

            if (resolvedItem.status === 'no_audio') {

              incrementSubtitleScanSession('noAudioTargets')

              return

            }

            collected.push(resolvedItem)

            await Promise.resolve(onChunk?.(resolvedItem, path))

            await nextTick()

            return

          }

          if (event.type === 'error') {

            throw new Error(event.error || '扫描失败')

          }

        }

      })

    } catch (error) {

      console.error('扫描 RJ 字幕候选失败:', path, error)

      onTargetResult?.({

        path,

        library_id: libraryId,

        name: target.name || getFileName(path),

        status: 'failed',

        message: error.response?.data?.detail || error.message || '扫描失败'

      })

    } finally {

      done += 1

      onProgress?.({ done, total, currentPath: path, libraryId })

    }

  }

  return uniqueSubtitleItems(collected)

}



async function autoQueueScannedSubtitleItem (item, options = {}) {

  const { requestToken = 0, batchContext = null } = options

  if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return



  incrementSubtitleScanSession('foundDirectories')

  incrementSubtitleScanTargetCounter(item, 'found', 1, { name: getFileName(item.scan_target_path) })

  const existingTask = findSubtitleTaskBySelection(item)

  if (existingTask) {

    incrementSubtitleScanSession('existingTasks')

    incrementSubtitleScanTargetCounter(item, 'existingTask', 1)

    upsertSubtitleSelectionEntry(item, {

      task_id: existingTask.id,

      queue_state: 'existing_task',

      queue_message: '任务已存在'

    })

    return

  }



  upsertSubtitleSelectionEntry(item, {

    queue_state: 'checking_subtitle',

    queue_message: '正在检测远程字幕'

  })



  try {

    const availability = await ensureRJSubtitleAvailabilityForItem(item)

    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return

    if (!availability.hasSubtitle) {

      incrementSubtitleScanSession('noSubtitleTargets')

      incrementSubtitleScanTargetCounter(item, 'skippedNoSubtitle', 1)

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_no_subtitle',

        queue_message: availability.message || '远程无字幕'

      })

      return

    }



    upsertSubtitleSelectionEntry(item, {

      queue_state: 'creating',

      queue_message: availability.message || '检测到可用字幕，正在加入任务'

    })

    const data = await submitRJSubtitleTasks([item], {

      silent: true,

      refresh: false,

      batchContext: batchContext

        ? {

            ...batchContext,

            log_parent: false

          }

        : null

    })

    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return

    const skippedItem = Array.isArray(data?.skipped_items)

      ? data.skipped_items.find(entry => buildSubtitleSelectionKey(entry) === buildSubtitleSelectionKey(item))

      : null

    if (skippedItem?.queue_state === 'skipped_existing') {

      incrementSubtitleScanSession('existingSubtitles')

      incrementSubtitleScanTargetCounter(item, 'skippedExisting', 1)

      upsertSubtitleSelectionEntry(item, {

        existing_subtitle_count: skippedItem.existing_subtitle_count ?? item.existing_subtitle_count ?? 0,

        status: 'existing',

        queue_state: 'skipped_existing',

        queue_message: skippedItem.queue_message || '已有字幕，未加入抓取任务'

      })

      return

    }

    if (skippedItem?.queue_state === 'skipped_kikoeru_existing') {

      incrementSubtitleScanSession('existingSubtitles')

      incrementSubtitleScanTargetCounter(item, 'skippedExisting', 1)

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_kikoeru_existing',

        queue_message: skippedItem.queue_message || 'Kikoeru 已有字幕，未加入抓取任务'

      })

      return

    }

    if (skippedItem?.queue_state === 'skipped_no_subtitle') {

      incrementSubtitleScanSession('noSubtitleTargets')

      incrementSubtitleScanTargetCounter(item, 'skippedNoSubtitle', 1)

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_no_subtitle',

        queue_message: skippedItem.queue_message || '远程无字幕'

      })

      return

    }

    if (skippedItem?.queue_state === 'existing_task') {

      incrementSubtitleScanSession('existingTasks')

      incrementSubtitleScanTargetCounter(item, 'existingTask', 1)

      upsertSubtitleSelectionEntry(item, {

        task_id: skippedItem.task_id || '',

        queue_state: 'existing_task',

        queue_message: skippedItem.queue_message || '任务已存在'

      })

      if (skippedItem.task_id && !subtitleActiveTaskId.value) subtitleActiveTaskId.value = skippedItem.task_id

      return

    }

    const createdTask = data?.tasks?.[0] || null

    if (!createdTask?.task_id) {

      incrementSubtitleScanSession('createFailed')

      incrementSubtitleScanTargetCounter(item, 'createFailed', 1)

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'create_failed',

        queue_message: data?.message || '未创建任务'

      })

      return

    }

    incrementSubtitleScanSession('createdTasks')

    incrementSubtitleScanTargetCounter(item, 'queued', 1)

    const taskCreatedAt = new Date().toISOString()

    upsertSubtitleTaskLocal({

      ...createOptimisticSubtitleTask(item, createdTask.task_id),

      created_at: taskCreatedAt

    })

    upsertSubtitleSelectionEntry(item, {

      task_id: createdTask.task_id,

      task_created_at: taskCreatedAt,

      queue_state: 'queued',

      queue_message: '已加入任务'

    })

    if (!subtitleActiveTaskId.value) subtitleActiveTaskId.value = createdTask.task_id

  } catch (error) {

    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return

    incrementSubtitleScanSession('createFailed')

    incrementSubtitleScanTargetCounter(item, 'createFailed', 1)

    upsertSubtitleSelectionEntry(item, {

      queue_state: 'create_failed',

      queue_message: error.response?.data?.detail || error.message || '加入任务失败'

    })

  }

}



function startAutoQueueScannedSubtitleItem (item, pendingJobs, options = {}, logLabel = '扫描命中目录自动入任务失败') {

  const job = Promise.resolve(autoQueueScannedSubtitleItem(item, options)).catch(error => {

    console.error(`${logLabel}:`, item?.folder_path, error)

  })

  if (Array.isArray(pendingJobs)) pendingJobs.push(job)

  return job

}



function resumeSubtitleTaskPanelFromBackground () {

  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

}



function hideSubtitleTaskPanelToBackground () {

  subtitleDialogBackgroundActive.value = true

  subtitleDialogVisible.value = false

}



function dismissSubtitleBackground () {

  // 只收掉浮动片，不取消、不删除任务；任务继续在后台保持

  subtitleDialogBackgroundActive.value = false

}



function handleSubtitleDialogBeforeClose () {

  hideSubtitleTaskPanelToBackground()

}



async function closeSubtitleTaskPanel () {

  const liveTasks = subtitleTasks.value

    .map(task => ({ ...task, id: String(task?.id || '').trim() }))

    .filter(task => task.id)

  const cancellableTaskIds = liveTasks

    .filter(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))

    .map(task => task.id)

  if (cancellableTaskIds.length) {

    await Promise.allSettled(cancellableTaskIds.map(taskId => rjSubtitleApi.cancel(taskId)))

  }

  if (liveTasks.length) {

    await Promise.allSettled(liveTasks.map(task => rjSubtitleApi.clearTask(task.id)))

  }



  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = false

  clearSubtitleStatusPoll()

  subtitleTasks.value = []

  subtitleActiveTaskId.value = ''

  subtitleScanRetryingPath.value = ''

  subtitleSelectionScanCurrent.value = ''

  setSubtitleWorkbenchRailMode('scan')

  setActiveSubtitleWorkbenchStage('overview')

  subtitleWorkbenchDrawerCollapsed.value = false

  clearSubtitleScanWorkspace()

  clearSubtitleInspectorState()

  persistSubtitleScanWorkspace()

}



async function openSubtitleTaskPanel () {

  subtitleSelectionRequestToken.value += 1

  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

  setSubtitleWorkbenchRailMode('tasks')

  setActiveSubtitleWorkbenchStage(activeSubtitleTask.value ? resolvePreferredSubtitleWorkbenchStageForTask(activeSubtitleTask.value) : 'overview')

  clearSubtitleScanWorkspace()

  await nextTick()

  await refreshRJSubtitleStatus(false, { silent: true })

}



function getSubtitleRouteFocusPayload () {

  const subtitleDialog = route.query.subtitleDialog

  const subtitleTaskId = route.query.subtitleTaskId

  const subtitleFolderPath = route.query.subtitleFolderPath

  const subtitleLibraryId = route.query.subtitleLibraryId

  const subtitleRjcode = route.query.subtitleRjcode

  const subtitleSourceLabel = route.query.subtitleSourceLabel

  const subtitleSummary = route.query.subtitleSummary

  const subtitleRestoredAt = route.query.subtitleRestoredAt

  const shouldOpen = subtitleDialog === '1'

  const taskId = typeof subtitleTaskId === 'string' ? subtitleTaskId.trim() : ''

  const folderPath = typeof subtitleFolderPath === 'string' ? subtitleFolderPath.trim() : ''

  const libraryId = typeof subtitleLibraryId === 'string' ? subtitleLibraryId.trim() : ''

  const rjcode = typeof subtitleRjcode === 'string' ? subtitleRjcode.trim().toUpperCase() : ''

  const sourceLabel = typeof subtitleSourceLabel === 'string' ? subtitleSourceLabel.trim() : ''

  const summary = typeof subtitleSummary === 'string' ? subtitleSummary.trim() : ''

  const restoredAt = typeof subtitleRestoredAt === 'string' ? subtitleRestoredAt.trim() : ''

  return {

    shouldOpen,

    taskId,

    folderPath,

    libraryId,

    rjcode,

    sourceLabel,

    summary,

    restoredAt,

    focusKey: shouldOpen ? `${subtitleDialog}:${taskId}:${libraryId}:${folderPath}` : ''

  }

}



function getSubtitleBatchSelectionRouteFlag () {

  return String(route.query.subtitleBatchSelection || '').trim() === '1'

}



function normalizeLibraryMatchPath(path = '', isRemote = false) {

  const value = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')

  if (!value) return ''

  return isRemote ? value : value.toLowerCase()

}



function isPathWithinLibraryRoot(targetPath = '', library = null) {

  if (!targetPath || !library) return false

  const isRemote = String(library.type || '') === 'synology_filestation'

  const rootCandidate = library.browse_root_path || library.root_path || library.path || ''

  const normalizedTarget = normalizeLibraryMatchPath(targetPath, isRemote)

  const normalizedRoot = normalizeLibraryMatchPath(rootCandidate, isRemote)

  if (!normalizedTarget || !normalizedRoot) return false

  return normalizedTarget === normalizedRoot || normalizedTarget.startsWith(`${normalizedRoot}/`)

}



function resolveLibraryIdByPath(targetPath = '', preferredLibraryId = '') {

  const normalizedPreferred = String(preferredLibraryId || '').trim()

  const preferred = normalizedPreferred ? libraries.value.find(item => item.id === normalizedPreferred) || null : null

  if (preferred && isPathWithinLibraryRoot(targetPath, preferred)) {

    return preferred.id

  }

  const matched = libraries.value.find(item => isPathWithinLibraryRoot(targetPath, item))

  return matched?.id || normalizedPreferred || ''

}



async function clearSubtitleRouteFocusQuery () {

  const nextQuery = { ...route.query }

  delete nextQuery.subtitleDialog

  delete nextQuery.subtitleTaskId

  delete nextQuery.subtitleFolderPath

  delete nextQuery.subtitleLibraryId

  delete nextQuery.subtitleRjcode

  delete nextQuery.subtitleSourceLabel

  delete nextQuery.subtitleSummary

  delete nextQuery.subtitleRestoredAt

  delete nextQuery.subtitleBatchSelection

  delete nextQuery.subtitleImport

  await router.replace({

    path: route.path,

    query: nextQuery

  })

}



async function openSubtitleDialogWithPresetSelection (items = [], preferredKey = '') {

  const normalizedItems = uniqueSubtitleItems((Array.isArray(items) ? items : [])

    .map(item => ({

      library_id: item.library_id || selectedLibraryId.value,

      folder_path: item.folder_path || '',

      folder_name: item.folder_name || getFileName(item.folder_path),

      rjcode: item.rjcode || extractRJCode(item.folder_path || '') || '',

      task_id: item.task_id || '',

      queue_state: String(item.queue_state || ''),

      queue_message: item.queue_message || '',

      downloaded_count: Number(item.downloaded_count || 0),

      existing_subtitle_count: Number(item.existing_subtitle_count || 0),

      awaiting_manual_match: Boolean(item.awaiting_manual_match),

      manual_match_completed: Boolean(item.manual_match_completed),

      manual_match_applied_pairs: Number(item.manual_match_applied_pairs || 0),

      manual_match_deleted_subtitles: Number(item.manual_match_deleted_subtitles || 0),

      source_label: String(item.source_label || '').trim(),

      source_mode: String(item.source_mode || '').trim(),

      restored_at: String(item.restored_at || '').trim(),

      activity_context: item.activity_context && typeof item.activity_context === 'object'

        ? { ...item.activity_context }

        : null

    }))

    .filter(item => item.folder_path))

  if (!normalizedItems.length) return



  const firstLibraryId = normalizedItems[0]?.library_id || ''

  if (firstLibraryId && selectedLibraryId.value !== firstLibraryId) {

    selectedLibraryId.value = firstLibraryId

  }



  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

  setSubtitleWorkbenchRailMode('scan')

  setActiveSubtitleWorkbenchStage(resolvePreferredSubtitleWorkbenchStageForSelection(normalizedItems[0]))

  clearSubtitleScanWorkspace()

  subtitleSelectionLoading.value = false

  subtitleSelectionSourceItems.value = normalizedItems

  subtitleScannedSelectionItems.value = normalizedItems

  subtitleDialogSelection.value = mergeSubtitleSelectionRuntimeState(normalizedItems, normalizedItems)

  subtitlePreferredSelectionKey.value = preferredKey || buildSubtitleSelectionKey(normalizedItems[0]) || ''

  clearSubtitleInspectorState()

  await nextTick()

  await refreshRJSubtitleStatus(false, { silent: true })



  normalizedItems

    .filter(item => item.task_id && !findSubtitleTaskBySelection(item))

    .forEach(item => {

      const awaitingManualMatch = Boolean(item.awaiting_manual_match)

      const manualMatchCompleted = Boolean(item.manual_match_completed)

      const downloadedCount = Number(item.downloaded_count || 0)

      const existingSubtitleCount = Math.max(Number(item.existing_subtitle_count || 0), downloadedCount)

      const subtitleDir = awaitingManualMatch || manualMatchCompleted || downloadedCount > 0 || existingSubtitleCount > 0

        ? joinFolderPath(item.folder_path, 'subtitles')

        : ''

      const optimisticTask = {

        ...createOptimisticSubtitleTask(item, item.task_id),

        task_view_mode: 'selection_backfill',

        live_task: null,

        snapshot: {

          task_id: String(item.task_id || '').trim(),

          queue_state: String(item.queue_state || '').trim(),

          queue_message: item.queue_message || '',

          source_label: String(item.source_label || '').trim(),

          downloaded_count: downloadedCount,

          existing_subtitle_count: existingSubtitleCount,

          subtitle_dir: subtitleDir,

          awaiting_manual_match: awaitingManualMatch,

          manual_match_completed: manualMatchCompleted,

          manual_match_applied_pairs: Number(item.manual_match_applied_pairs || 0),

          manual_match_deleted_subtitles: Number(item.manual_match_deleted_subtitles || 0)

        },

        source_label: String(item.source_label || '').trim(),

        source_mode: String(item.source_mode || '').trim(),

        restored_at: String(item.restored_at || '').trim(),

        activity_context: item.activity_context && typeof item.activity_context === 'object'

          ? { ...item.activity_context }

          : null,

        status: 'selection_backfill',

        progress: 0,

        current_step: item.queue_message || (awaitingManualMatch ? '待继续配对' : '已回填'),

        downloaded_count: downloadedCount,

        existing_subtitle_count: existingSubtitleCount,

        subtitle_dir: subtitleDir,

        awaiting_manual_match: awaitingManualMatch,

        manual_match_completed: manualMatchCompleted,

        manual_match_applied_pairs: Number(item.manual_match_applied_pairs || 0),

        manual_match_deleted_subtitles: Number(item.manual_match_deleted_subtitles || 0)

      }

      upsertSubtitleTaskLocal(optimisticTask)

    })

}



async function consumeSubtitleBatchSelectionRoute () {

  if (!getSubtitleBatchSelectionRouteFlag()) return

  const payload = loadJson('activity-history-subtitle-batch-selection', null)

  try { localStorage.removeItem('activity-history-subtitle-batch-selection') } catch (_) {}

  if (!payload || !Array.isArray(payload.items) || !payload.items.length) {

    await clearSubtitleRouteFocusQuery()

    return

  }

  await openSubtitleDialogWithPresetSelection(payload.items, String(payload.preferred_key || '').trim())

  await clearSubtitleRouteFocusQuery()

}



async function consumeSubtitleRouteFocus () {

  const { shouldOpen, taskId, folderPath, libraryId, rjcode, sourceLabel, summary, restoredAt, focusKey } = getSubtitleRouteFocusPayload()

  if (!shouldOpen || (!taskId && !folderPath)) return

  if (subtitleRouteFocusKey.value === focusKey && subtitleDialogVisible.value) return



  subtitleRouteFocusKey.value = focusKey

  const resolvedLibraryId = resolveLibraryIdByPath(folderPath, libraryId)

  if (resolvedLibraryId && selectedLibraryId.value !== resolvedLibraryId) {

    selectedLibraryId.value = resolvedLibraryId

  }

  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

  setSubtitleWorkbenchRailMode(taskId ? 'tasks' : 'scan')

  await nextTick()

  await refreshRJSubtitleStatus(false, { silent: true })



  const matchedTask = subtitleTasks.value.find(item => item.id === taskId)

  if (matchedTask) {

    if (matchedTask.subtitle_dir) {

      if (sourceLabel || restoredAt) {

        subtitleInspectorInfo.value = {

          ...subtitleInspectorInfo.value,

          sourceLabel: sourceLabel || matchedTask.source_label || subtitleInspectorInfo.value.sourceLabel || '',

          restoredAt: restoredAt || subtitleInspectorInfo.value.restoredAt || '',

          activityContext: {

            ...(subtitleInspectorInfo.value.activityContext || {}),

            source_label: sourceLabel || matchedTask.source_label || '',

            summary: summary || matchedTask.current_step || '',

            created_at: restoredAt || ''

          }

        }

      }

      await handleSubtitleWorkbenchInspectTask(matchedTask)

    } else {

      focusSubtitleTask(matchedTask.id)

      setSubtitleWorkbenchRailMode('tasks')

      setActiveSubtitleWorkbenchStage(resolvePreferredSubtitleWorkbenchStageForTask(matchedTask))

    }

    await clearSubtitleRouteFocusQuery()

    return

  }



  if (folderPath) {

    await handleSubtitleWorkbenchInspectSelectionFolder({

      library_id: resolvedLibraryId || selectedLibraryId.value,

      folder_path: folderPath,

      folder_name: getFileName(folderPath),

      rjcode: rjcode || extractRJCode(folderPath) || '',

      queue_message: summary || '来自操作记录',

      source_label: sourceLabel || '操作记录',

      source_mode: 'activity_history_restore',

      restored_at: restoredAt || '',

      activity_context: {

        source_label: sourceLabel || '操作记录',

        summary: summary || '',

        created_at: restoredAt || ''

      }

    }, { force: true, preferredTaskId: taskId })

  }



  await clearSubtitleRouteFocusQuery()

}



async function openRJSubtitleDialog (rows = [], options = {}) {

  const { scanCurrentFolder = false } = options

  const requestToken = ++subtitleSelectionRequestToken.value

  const pendingAutoQueueJobs = []

  const sourceRows = Array.isArray(rows) ? rows : []

  const directItems = sourceRows

    .map(item => item?.folder_path ? item : toRJSubtitleItem(item))

    .filter(Boolean)

  const shouldScanCurrentFolder = scanCurrentFolder && directItems.length === 0 && Boolean(currentPath.value)

  const batchContext = {

    batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,

    source_directories: [],

    scan_targets: [],

    requested_count: 0,

    recognized_rj_count: 0,

    scan_directory_count: 0,

    summary: buildSubtitleScanTargetSummary({})

  }

  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

  setSubtitleWorkbenchRailMode('scan')

  setActiveSubtitleWorkbenchStage('overview')

  clearSubtitleScanWorkspace()

  subtitleSelectionLoading.value = true

  subtitleSelectionSourceItems.value = uniqueSubtitleItems(directItems)

  clearSubtitleInspectorState()

  await nextTick()



  try {

    await refreshRJSubtitleStatus(false, { silent: true })

    const scanTargets = uniqueSubtitleScanTargets(directItems)

    batchContext.source_directories = uniqueSubtitleItems(directItems).map(item => ({

      folder_path: item.folder_path || '',

      folder_name: item.folder_name || getFileName(item.folder_path),

      library_id: item.library_id || selectedLibraryId.value || ''

    })).filter(item => item.folder_path)

    batchContext.scan_directory_count = scanTargets.length || (shouldScanCurrentFolder ? 1 : 0)

    subtitleSelectionScanTotal.value = scanTargets.length || (shouldScanCurrentFolder ? 1 : 0)

    let scannedItems = []

    let incrementalScannedItems = []

    if (scanTargets.length) {

      scannedItems = await resolveRJSubtitleItems(scanTargets, {

        onChunk: async chunkItem => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          incrementalScannedItems = uniqueSubtitleItems([...incrementalScannedItems, chunkItem])

          subtitleScannedSelectionItems.value = incrementalScannedItems

          updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, incrementalScannedItems, { sync: true })

          startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext })

        },

        onTargetResult: result => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          upsertSubtitleScanTargetResult(result)

        },

        onProgress: progress => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          subtitleSelectionScanDone.value = Number(progress?.done || 0)

          subtitleSelectionScanTotal.value = Number(progress?.total || scanTargets.length)

          subtitleSelectionScanCurrent.value = progress?.currentPath || ''

          patchSubtitleScanSession({ scannedTargets: Number(progress?.done || 0) })

        }

      })

    }



    if (shouldScanCurrentFolder && !scannedItems.length) {

      scannedItems = await resolveRJSubtitleItems([currentPath.value], {

        onChunk: async chunkItem => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          subtitleScannedSelectionItems.value = uniqueSubtitleItems([...subtitleScannedSelectionItems.value, chunkItem])

          updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })

          startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext }, '当前目录扫描命中后自动入任务失败')

        },

        onTargetResult: result => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          upsertSubtitleScanTargetResult(result)

        },

        onProgress: progress => {

          if (subtitleSelectionRequestToken.value !== requestToken) return

          subtitleSelectionScanDone.value = Number(progress?.done || 0)

          subtitleSelectionScanTotal.value = Number(progress?.total || 1)

          subtitleSelectionScanCurrent.value = progress?.currentPath || currentPath.value

          patchSubtitleScanSession({ scannedTargets: Number(progress?.done || 0) })

        }

      })

    }



    if (subtitleSelectionRequestToken.value !== requestToken) return

    if (pendingAutoQueueJobs.length) {

      await Promise.allSettled(pendingAutoQueueJobs)

    }

    if (subtitleSelectionRequestToken.value !== requestToken) return

    subtitleScannedSelectionItems.value = uniqueSubtitleItems(scannedItems)

    syncSubtitleSelectionState()

    batchContext.requested_count = subtitleDialogSelection.value.length

    batchContext.recognized_rj_count = subtitleScanSession.value.foundDirectories

    batchContext.scan_targets = (subtitleScanTargetResults.value || []).map(item => ({

      path: item.path || '',

      name: item.name || getFileName(item.path),

      library_id: item.library_id || '',

      status: item.status || 'pending',

      message: item.message || '',

      summary: buildSubtitleScanTargetSummary(item.summary || {})

    })).filter(item => item.path)

    batchContext.summary = batchContext.scan_targets.reduce((acc, item) => {

      const summary = buildSubtitleScanTargetSummary(item.summary || {})

      return mergeSubtitleScanTargetSummary(acc, summary)

    }, buildSubtitleScanTargetSummary({}))

    await submitRJSubtitleTasks([], {

      silent: true,

      refresh: false,

      batchContext: {

        ...batchContext,

        log_parent: true

      }

    })

    await refreshRJSubtitleStatus(false, { silent: true })

  } finally {

    if (subtitleSelectionRequestToken.value === requestToken) {

      subtitleSelectionLoading.value = false

      subtitleSelectionScanCurrent.value = ''

    }

  }

}



async function startCurrentFolderRJSubtitle () {

  if (!canProcessCurrentFolder.value) return

  if (toolbarActionScope.value === 'page') {

    await openRJSubtitleDialog(toolbarSubtitleScopeRows.value)

    return

  }

  if (!currentPath.value) return

  await openRJSubtitleDialog([], { scanCurrentFolder: true })

}



async function rescanSubtitleSelectionTarget (target) {

  if (!canRetrySubtitleScanResult(target) || subtitleScanRetryingPath.value) return

  subtitleScanRetryingPath.value = buildSubtitleScanTargetResultKey(target)

  subtitleSelectionScanTotal.value = 1

  subtitleSelectionScanDone.value = 0

  subtitleSelectionScanCurrent.value = target.path

  upsertSubtitleScanTargetResult({

    path: target.path,

    library_id: target.library_id || selectedLibraryId.value,

    name: target.name,

    status: 'pending',

    message: '正在重新扫描...'

  })

  try {

    const rescannedItems = await resolveRJSubtitleItems([target], {

      onChunk: chunkItem => {

        subtitleScannedSelectionItems.value = uniqueSubtitleItems([

          ...subtitleScannedSelectionItems.value.filter(item => !(item.folder_path === target.path && (item.library_id || '') === (target.library_id || ''))),

          chunkItem

        ])

        updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })

      },

      onTargetResult: result => {

        upsertSubtitleScanTargetResult(result)

      },

      onProgress: progress => {

        subtitleSelectionScanDone.value = Number(progress?.done || 0)

        subtitleSelectionScanTotal.value = Number(progress?.total || 1)

        subtitleSelectionScanCurrent.value = progress?.currentPath || target.path

      }

    })

    if (rescannedItems.length) {

      subtitleScannedSelectionItems.value = uniqueSubtitleItems([

        ...subtitleScannedSelectionItems.value.filter(item => !(item.folder_path === target.path && (item.library_id || '') === (target.library_id || ''))),

        ...rescannedItems

      ])

      for (const rescannedItem of rescannedItems) {

        await autoQueueScannedSubtitleItem(rescannedItem)

      }

      removeSubtitleScanTargetResult(target)

      ElMessage.success('该目录已重新扫描并重新尝试加入任务')

      return

    }

  } catch (error) {

    upsertSubtitleScanTargetResult({

      path: target.path,

      library_id: target.library_id || selectedLibraryId.value,

      name: target.name,

      status: 'failed',

      message: error.response?.data?.detail || error.message || '重新扫描失败'

    })

  } finally {

    subtitleScanRetryingPath.value = ''

    subtitleSelectionScanCurrent.value = ''

  }

}



async function submitRJSubtitleTasks (items, options = {}) {

  const { silent = false, refresh = true, skipIfExistingSubtitlesOverride = null, forceRerun = false, batchContext: batchContextOverride = null } = options

  const rawItems = Array.isArray(items) ? items : []

  const buildBatchContext = () => {

    const sourceDirectories = uniqueSubtitleItems(subtitleSelectionSourceItems.value || []).map(item => ({

      folder_path: item.folder_path || '',

      folder_name: item.folder_name || getFileName(item.folder_path),

      library_id: item.library_id || selectedLibraryId.value || ''

    })).filter(item => item.folder_path)

    const scanTargets = (subtitleScanTargetResults.value || []).map(item => ({

      path: item.path || '',

      name: item.name || getFileName(item.path),

      library_id: item.library_id || '',

      status: item.status || 'pending',

      message: item.message || '',

      summary: buildSubtitleScanTargetSummary(item.summary || {})

    })).filter(item => item.path)

    const batchSummary = scanTargets.reduce((acc, item) => {

      const summary = buildSubtitleScanTargetSummary(item.summary || {})

      return mergeSubtitleScanTargetSummary(acc, summary)

    }, buildSubtitleScanTargetSummary({}))

    const sourceCount = sourceDirectories.length

    const scanCount = scanTargets.length

    const itemCount = rawItems.length

    const hasScanContext = sourceCount > 0 || scanCount > 0

    if (!hasScanContext && itemCount <= 1) return null

    return {

      batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,

      requested_count: itemCount,

      recognized_rj_count: Math.max(Number(batchSummary.found || 0), itemCount),

      scan_directory_count: Math.max(sourceCount, scanCount, 0),

      source_directories: sourceDirectories,

      scan_targets: scanTargets,

      summary: batchSummary

    }

  }

  const batchContext = batchContextOverride || buildBatchContext()

  if (!Array.isArray(items) || !items.length) {

    if (!batchContext) {

      if (!silent) ElMessage.warning('没有可执行的 RJ 文件夹')

      return null

    }

  }



  const effectiveSkipIfExistingSubtitles = forceRerun

    ? false

    : typeof skipIfExistingSubtitlesOverride === 'boolean'

      ? skipIfExistingSubtitlesOverride

      : subtitleOptions.value.skipIfExistingSubtitles

  const executableItems = [...rawItems]

  const executableItemByPath = new Map(

    executableItems

      .filter(item => String(item?.folder_path || '').trim())

      .map(item => [normalizeLibraryPathKey(item.folder_path), item])

  )



  subtitleSubmitting.value = true

  try {

    const data = await rjSubtitleApi.start(executableItems, {

      overwriteExisting: subtitleOptions.value.overwriteExisting,

      enableMetadataMatch: subtitleOptions.value.enableMetadataMatch,

      skipIfExistingSubtitles: effectiveSkipIfExistingSubtitles,

      forceRerun,

      namingStrategy: subtitleOptions.value.namingStrategy,

      useFilterRules: subtitleOptions.value.useFilterRules,

      subtitleFilterRules: sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules),

      batchContext

    })

    ;(Array.isArray(data?.tasks) ? data.tasks : []).forEach(createdTask => {

      const taskId = String(createdTask?.task_id || '').trim()

      if (!taskId) return

      const sourcePath = normalizeLibraryPathKey(createdTask?.source_path || '')

      const matchedItem = executableItemByPath.get(sourcePath)

      if (!matchedItem) return

      const taskCreatedAt = new Date().toISOString()

      upsertSubtitleTaskLocal({

        ...createOptimisticSubtitleTask(matchedItem, taskId),

        created_at: taskCreatedAt

      })

      upsertSubtitleSelectionEntry(matchedItem, {

        task_id: taskId,

        task_created_at: taskCreatedAt,

        queue_state: 'queued',

        queue_message: '已加入任务'

      })

    })

    ;(Array.isArray(data?.skipped_items) ? data.skipped_items : []).forEach(skippedItem => {

      const queueState = String(skippedItem?.queue_state || '').trim()

      if (!queueState) return

      const sourcePath = normalizeLibraryPathKey(skippedItem?.source_path || '')

      const matchedItem = executableItemByPath.get(sourcePath)

      if (!matchedItem) return

      upsertSubtitleSelectionEntry(matchedItem, {

        task_id: String(skippedItem?.task_id || '').trim(),

        queue_state: queueState,

        queue_message: skippedItem?.queue_message || matchedItem.queue_message || ''

      })

    })

    if (refresh) await refreshRJSubtitleStatus(false, { silent: true })

    const firstCreatedTaskId = data.tasks?.[0]?.task_id

    if (firstCreatedTaskId) {

      subtitleActiveTaskId.value = firstCreatedTaskId

    }

    if (!silent) {

      if (data.tasks?.length) ElMessage.success(data.message || '已创建字幕任务')

      else if (Array.isArray(data.skipped_items) && data.skipped_items.length) {

        const firstSkippedItem = data.skipped_items[0] || {}

        if (String(firstSkippedItem.queue_state || '').startsWith('skipped_')) {

          ElMessage.info(firstSkippedItem.queue_message || '该目录已跳过')

        } else {

          ElMessage.warning(firstSkippedItem.queue_message || '没有创建新任务')

        }

      }

      else ElMessage.warning('没有创建新任务，可能已存在字幕或当前目录不满足执行条件')

    }

    return data

  } catch (error) {

    if (!silent) ElMessage.error('创建字幕任务失败: ' + (error.response?.data?.detail || error.message))

    throw error

  } finally {

    subtitleSubmitting.value = false

  }

}



async function startSingleRJSubtitle (item) {

  if (!item?.folder_path) return

  const requestToken = ++subtitleSelectionRequestToken.value

  const pendingAutoQueueJobs = []

  const batchContext = {

    batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,

    source_directories: [{

      folder_path: item.folder_path || '',

      folder_name: item.folder_name || getFileName(item.folder_path),

      library_id: item.library_id || selectedLibraryId.value || ''

    }].filter(entry => entry.folder_path),

    scan_targets: [],

    requested_count: 0,

    recognized_rj_count: 0,

    scan_directory_count: 1,

    summary: buildSubtitleScanTargetSummary({})

  }

  subtitleDialogBackgroundActive.value = false

  subtitleDialogVisible.value = true

  resetSubtitleScanRunIndicators()

  subtitleSelectionLoading.value = true

  subtitleSelectionScanDone.value = 0

  subtitleSelectionScanTotal.value = 1

  subtitleSelectionScanCurrent.value = item.folder_path

  subtitleSelectionSourceItems.value = uniqueSubtitleItems([item])

  subtitleScannedSelectionItems.value = []

  subtitleScanTargetResults.value = []

  subtitleScanRetryingPath.value = ''

  subtitleDialogSelection.value = uniqueSubtitleItems([item])

  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)

  clearSubtitleInspectorState()

  await nextTick()



  try {

    await refreshRJSubtitleStatus(false, { silent: true })

    const existingTask = findSubtitleTaskBySelection(item)

    if (existingTask) {

      subtitleActiveTaskId.value = existingTask.id

      if (existingTask.subtitle_dir) await inspectSubtitleTask(existingTask)

      ElMessage.success('已定位到现有字幕任务')

      return

    }



    const scannedItems = await resolveRJSubtitleItems([item], {

      onChunk: async chunkItem => {

        if (subtitleSelectionRequestToken.value !== requestToken) return

        subtitleScannedSelectionItems.value = uniqueSubtitleItems([...subtitleScannedSelectionItems.value, chunkItem])

        updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })

        startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext }, '单项扫描命中后自动入任务失败')

      },

      onTargetResult: result => {

        if (subtitleSelectionRequestToken.value !== requestToken) return

        upsertSubtitleScanTargetResult(result)

      },

      onProgress: progress => {

        if (subtitleSelectionRequestToken.value !== requestToken) return

        subtitleSelectionScanDone.value = Number(progress?.done || 0)

        subtitleSelectionScanTotal.value = Number(progress?.total || 1)

        subtitleSelectionScanCurrent.value = progress?.currentPath || item.folder_path

      }

    })

    if (pendingAutoQueueJobs.length) {

      await Promise.allSettled(pendingAutoQueueJobs)

    }

    if (subtitleSelectionRequestToken.value !== requestToken) return

    subtitleScannedSelectionItems.value = uniqueSubtitleItems(scannedItems)

    syncSubtitleSelectionState()

    batchContext.requested_count = subtitleDialogSelection.value.length

    batchContext.recognized_rj_count = subtitleScanSession.value.foundDirectories

    batchContext.scan_targets = (subtitleScanTargetResults.value || []).map(entry => ({

      path: entry.path || '',

      name: entry.name || getFileName(entry.path),

      library_id: entry.library_id || '',

      status: entry.status || 'pending',

      message: entry.message || '',

      summary: buildSubtitleScanTargetSummary(entry.summary || {})

    })).filter(entry => entry.path)

    batchContext.summary = batchContext.scan_targets.reduce((acc, entry) => {

      const summary = buildSubtitleScanTargetSummary(entry.summary || {})

      return mergeSubtitleScanTargetSummary(acc, summary)

    }, buildSubtitleScanTargetSummary({}))

    await submitRJSubtitleTasks([], {

      silent: true,

      refresh: false,

      batchContext: {

        ...batchContext,

        log_parent: true

      }

    })

    await refreshRJSubtitleStatus(false, { silent: true })

    const resolvedItem = scannedItems.find(candidate => buildSubtitleSelectionKey(candidate) === buildSubtitleSelectionKey(item)) || null

    if (!resolvedItem) {

      if (subtitleScanSession.value.foundDirectories || subtitleScanSession.value.existingSubtitles || subtitleScanSession.value.noSubtitleTargets || subtitleScanSession.value.noAudioTargets || subtitleScanSession.value.noMatchTargets || subtitleScanSession.value.failedTargets) {

        return

      }

      return

    }

    if (subtitleOptions.value.skipIfExistingSubtitles && (resolvedItem.status === 'existing' || Number(resolvedItem.existing_subtitle_count || 0) > 0)) {

      await inspectSubtitleSelectionFolder(resolvedItem, { force: true })

      ElMessage.info('该目录已有字幕，已打开字幕检查工作台；如需重新抓取可点“创建一次任务”')

    }

  } catch (error) {

    ElMessage.error('启动字幕任务失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    subtitleSelectionLoading.value = false

    subtitleSelectionScanCurrent.value = ''

  }

}



function isAudioPaired (audioPath) {

  return subtitleManualPairs.value.some(pair => pair.audio_path === audioPath)

}



function isSubtitlePaired (subtitlePath) {

  return subtitleManualPairs.value.some(pair => pair.subtitle_path === subtitlePath)

}



function findSubtitlePairByAudioPath (audioPath) {

  return subtitleManualPairs.value.find(pair => pair.audio_path === audioPath) || null

}



function findSubtitlePairBySubtitlePath (subtitlePath) {

  return subtitleManualPairs.value.find(pair => pair.subtitle_path === subtitlePath) || null

}



function isAudioSuspicious (audioPath) {

  return findSubtitlePairByAudioPath(audioPath)?.confidenceLevel === 'low'

}



function isSubtitleSuspicious (subtitlePath) {

  return findSubtitlePairBySubtitlePath(subtitlePath)?.confidenceLevel === 'low'

}



function getSubtitlePairConfidenceLabel (level) {

  if (level === 'high') return '高置信'

  if (level === 'low') return '低置信'

  return '中等'

}



function clearSubtitleSequenceSelection () {

  subtitleSequenceSelection.value = { audioPaths: [], subtitlePaths: [] }

}



function toggleSubtitleSequencePath (kind, path) {

  if (!path) return

  const current = kind === 'audio'

    ? [...subtitleSequenceSelection.value.audioPaths]

    : [...subtitleSequenceSelection.value.subtitlePaths]

  const existingIndex = current.indexOf(path)

  if (existingIndex >= 0) {

    current.splice(existingIndex, 1)

  } else {

    current.push(path)

  }

  subtitleSequenceSelection.value = {

    ...subtitleSequenceSelection.value,

    [kind === 'audio' ? 'audioPaths' : 'subtitlePaths']: current

  }

}



function getSubtitleSequenceIndex (kind, path) {

  const list = kind === 'audio' ? subtitleSequenceSelection.value.audioPaths : subtitleSequenceSelection.value.subtitlePaths

  const index = list.indexOf(path)

  return index >= 0 ? index + 1 : 0

}



function selectSubtitleAudio (audio) {

  if (subtitleSequenceMode.value) {

    toggleSubtitleSequencePath('audio', audio?.path || '')

    return

  }

  subtitleMatchSelection.value = {

    ...subtitleMatchSelection.value,

    audioPath: audio?.path || ''

  }

}



function selectSubtitleFile (subtitle) {

  if (subtitleSequenceMode.value) {

    toggleSubtitleSequencePath('subtitle', subtitle?.path || '')

    return

  }

  subtitleMatchSelection.value = {

    ...subtitleMatchSelection.value,

    subtitlePath: subtitle?.path || ''

  }

}



function buildSubtitlePairTargets (audio, subtitle) {

  const audioExt = String(audio?.name || '').match(/\.[^.]+$/)?.[0] || ''

  const subtitleExt = String(subtitle?.name || '').match(/\.[^.]+$/)?.[0] || '.vtt'

  const subtitleBase = stripTrailingAudioExtension(String(subtitle?.name || '').replace(/\.[^.]+$/, ''))

  const audioBase = String(audio?.name || '').replace(/\.[^.]+$/, '')

  const targetBase = subtitleOptions.value.namingStrategy === 'subtitle' ? subtitleBase : audioBase

  return {

    targetBase,

    targetAudioName: `${targetBase}${audioExt}`,

    targetSubtitleName: `${targetBase}${subtitleExt}`

  }

}



function stripTrailingAudioExtension (value = '') {

  let current = String(value || '')

  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {

    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')

  }

  return current

}



function normalizeSubtitleMatchName (value = '') {

  return stripTrailingAudioExtension(String(value || '').replace(/\.[^.]+$/, ''))

    .toLowerCase()

    .replace(/^(track|trk|tr)[_\-\s]*/i, '')

    .replace(/[\s_\-]+/g, '')

    .replace(/[^\w\u4e00-\u9fff\u3040-\u30ff]+/g, '')

}



function extractSubtitleTrackNumber (value = '') {

  const match = String(value || '').match(/(?:^|[^0-9])(?:tr|track)?[_\-\s]*0*([0-9]{1,3})(?![0-9])/i)

  return match ? Number(match[1]) : null

}



function createSubtitlePair (audio, subtitle, options = {}) {

  const targets = buildSubtitlePairTargets(audio, subtitle)

  return {

    id: `${audio.path}::${subtitle.path}`,

    audio_path: audio.path,

    audio_name: audio.name,

    audio_relative_path: audio.relative_path || audio.name,

    subtitle_path: subtitle.path,

    subtitle_name: subtitle.name,

    subtitle_relative_path: subtitle.relative_path || subtitle.name,

    target_base: targets.targetBase,

    target_audio_name: targets.targetAudioName,

    target_subtitle_name: targets.targetSubtitleName,

    confidenceLevel: options.confidenceLevel || 'medium',

    matchReason: options.matchReason || '手动配对'

  }

}



function syncSubtitlePairTargetNames () {

  subtitleManualPairs.value = subtitleManualPairs.value.map(pair => ({

    ...pair,

    ...buildSubtitlePairTargets(

      { name: pair.audio_name, path: pair.audio_path, relative_path: pair.audio_relative_path },

      { name: pair.subtitle_name, path: pair.subtitle_path, relative_path: pair.subtitle_relative_path }

    )

  }))

}



function cloneSubtitleManualPairsSnapshot() {

  return subtitleManualPairs.value.map(pair => ({ ...pair }))

}



function createSubtitleManualMatchSnapshot() {

  return {

    audioSearch: subtitleInspectorAudioSearch.value,

    subtitleSearch: subtitleInspectorSubtitleSearch.value,

    audioFilterMode: subtitleAudioFilterMode.value,

    subtitleFilterMode: subtitleSubtitleFilterMode.value,

    matchSelection: { ...subtitleMatchSelection.value },

    sequenceMode: Boolean(subtitleSequenceMode.value),

    sequenceSelection: {

      audioPaths: [...subtitleSequenceSelection.value.audioPaths],

      subtitlePaths: [...subtitleSequenceSelection.value.subtitlePaths]

    },

    lastPairBuildMode: subtitleLastPairBuildMode.value,

    manualPairs: cloneSubtitleManualPairsSnapshot(),

    selectedManualPairId: subtitleSelectedManualPairId.value

  }

}



function restoreSubtitleManualMatchSnapshot(snapshot) {

  if (!snapshot) return

  subtitleInspectorAudioSearch.value = snapshot.audioSearch || ''

  subtitleInspectorSubtitleSearch.value = snapshot.subtitleSearch || ''

  subtitleAudioFilterMode.value = snapshot.audioFilterMode || 'all'

  subtitleSubtitleFilterMode.value = snapshot.subtitleFilterMode || 'all'

  subtitleMatchSelection.value = {

    audioPath: snapshot.matchSelection?.audioPath || '',

    subtitlePath: snapshot.matchSelection?.subtitlePath || ''

  }

  subtitleSequenceMode.value = Boolean(snapshot.sequenceMode)

  subtitleSequenceSelection.value = {

    audioPaths: [...(snapshot.sequenceSelection?.audioPaths || [])],

    subtitlePaths: [...(snapshot.sequenceSelection?.subtitlePaths || [])]

  }

  subtitleLastPairBuildMode.value = snapshot.lastPairBuildMode || ''

  subtitleManualPairs.value = Array.isArray(snapshot.manualPairs) ? snapshot.manualPairs.map(pair => ({ ...pair })) : []

  subtitleSelectedManualPairId.value = snapshot.selectedManualPairId || subtitleManualPairs.value[0]?.id || ''

}



function resetSubtitleManualMatchState () {

  subtitleInspectorAudioSearch.value = ''

  subtitleInspectorSubtitleSearch.value = ''

  subtitleAudioFilterMode.value = 'all'

  subtitleSubtitleFilterMode.value = 'all'

  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }

  subtitleSequenceMode.value = false

  clearSubtitleSequenceSelection()

  subtitleLastPairBuildMode.value = ''

  subtitleManualPairs.value = []

  subtitleSelectedManualPairId.value = ''

}



function addSubtitleManualPair () {

  const audio = subtitleInspectorAudioFiles.value.find(item => item.path === subtitleMatchSelection.value.audioPath)

  const subtitle = subtitleInspectorSubtitleFiles.value.find(item => item.path === subtitleMatchSelection.value.subtitlePath)

  if (!audio || !subtitle) {

    ElMessage.warning('请先分别选择音频和字幕')

    return

  }



  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.audio_path !== audio.path && pair.subtitle_path !== subtitle.path)

  subtitleManualPairs.value.push({

    ...createSubtitlePair(audio, subtitle, { confidenceLevel: 'medium', matchReason: '手动指定' })

  })

  subtitleLastPairBuildMode.value = 'manual'

  subtitleSelectedManualPairId.value = `${audio.path}::${subtitle.path}`

  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }

}



function removeSubtitleManualPair (pairId) {

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.id !== pairId)

  if (subtitleSelectedManualPairId.value === pairId) subtitleSelectedManualPairId.value = ''

}



function buildOrderedSubtitlePairs () {

  const audioList = filteredSubtitleInspectorAudioFiles.value

  const subtitleList = filteredSubtitleInspectorSubtitleFiles.value

  const pairCount = Math.min(audioList.length, subtitleList.length)

  if (!pairCount) {

    ElMessage.warning('当前没有可用于顺序配对的音频或字幕')

    return

  }

  const nextPairs = []

  for (let index = 0; index < pairCount; index++) {

    const audio = audioList[index]

    const subtitle = subtitleList[index]

    nextPairs.push(createSubtitlePair(audio, subtitle, { confidenceLevel: 'low', matchReason: '顺序配对' }))

  }

  subtitleManualPairs.value = nextPairs

  subtitleLastPairBuildMode.value = 'ordered'

  subtitleSelectedManualPairId.value = nextPairs[0]?.id || ''

}



function buildSequenceSubtitlePairs () {

  const audioList = subtitleSequenceSelection.value.audioPaths

    .map(path => subtitleInspectorAudioFiles.value.find(item => item.path === path))

    .filter(Boolean)

  const subtitleList = subtitleSequenceSelection.value.subtitlePaths

    .map(path => subtitleInspectorSubtitleFiles.value.find(item => item.path === path))

    .filter(Boolean)



  if (!audioList.length || audioList.length !== subtitleList.length) {

    ElMessage.warning('请先按顺序点选数量一致的音频和字幕')

    return

  }



  const nextPairs = []

  for (let index = 0; index < audioList.length; index++) {

    nextPairs.push(createSubtitlePair(audioList[index], subtitleList[index], {

      confidenceLevel: 'medium',

      matchReason: '点选顺序'

    }))

  }

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => (

    !audioList.some(item => item.path === pair.audio_path) &&

    !subtitleList.some(item => item.path === pair.subtitle_path)

  ))

  subtitleManualPairs.value.push(...nextPairs)

  subtitleLastPairBuildMode.value = 'sequence'

  subtitleSelectedManualPairId.value = nextPairs[0]?.id || subtitleSelectedManualPairId.value

  clearSubtitleSequenceSelection()

  subtitleSequenceMode.value = false

}



function buildSequenceOrOrderedSubtitlePairs () {

  if (subtitleSequenceMode.value) {

    buildSequenceSubtitlePairs()

    return

  }

  buildOrderedSubtitlePairs()

}



function buildAutoSubtitlePairs () {

  const audioList = [...subtitleInspectorAudioFiles.value]

  const subtitleList = [...subtitleInspectorSubtitleFiles.value]

  const usedSubtitlePaths = new Set()

  const pairs = []



  const subtitleByExact = new Map()

  const subtitleByNormalized = new Map()

  const subtitleByTrack = new Map()

  for (const subtitle of subtitleList) {

    const name = String(subtitle.name || '')

    const baseName = stripTrailingAudioExtension(name.replace(/\.[^.]+$/, ''))

    const normalized = normalizeSubtitleMatchName(name)

    const trackNumber = extractSubtitleTrackNumber(name)

    subtitleByExact.set(baseName.toLowerCase(), subtitleByExact.get(baseName.toLowerCase()) || [])

    subtitleByExact.get(baseName.toLowerCase()).push(subtitle)

    if (normalized) {

      subtitleByNormalized.set(normalized, subtitleByNormalized.get(normalized) || [])

      subtitleByNormalized.get(normalized).push(subtitle)

    }

    if (trackNumber !== null) {

      subtitleByTrack.set(trackNumber, subtitleByTrack.get(trackNumber) || [])

      subtitleByTrack.get(trackNumber).push(subtitle)

    }

  }



  function consumeCandidate (candidates = []) {

    for (const item of candidates) {

      if (usedSubtitlePaths.has(item.path)) continue

      usedSubtitlePaths.add(item.path)

      return item

    }

    return null

  }



  for (const audio of audioList) {

    const audioName = String(audio.name || '')

    const audioBase = audioName.replace(/\.[^.]+$/, '')

    const audioNormalized = normalizeSubtitleMatchName(audioName)

    const audioTrack = extractSubtitleTrackNumber(audioName)

    let matchedSubtitle = consumeCandidate(subtitleByExact.get(audioBase.toLowerCase()))

    let confidenceLevel = 'high'

    let matchReason = '精确文件名'

    if (!matchedSubtitle && audioTrack !== null) {

      matchedSubtitle = consumeCandidate(subtitleByTrack.get(audioTrack))

      if (matchedSubtitle) {

        confidenceLevel = 'high'

        matchReason = `轨道号 ${audioTrack}`

      }

    }

    if (!matchedSubtitle && audioNormalized) {

      matchedSubtitle = consumeCandidate(subtitleByNormalized.get(audioNormalized))

      if (matchedSubtitle) {

        confidenceLevel = 'medium'

        matchReason = '规范化标题'

      }

    }

    if (!matchedSubtitle) continue

    pairs.push(createSubtitlePair(audio, matchedSubtitle, { confidenceLevel, matchReason }))

  }



  if (!pairs.length) {

    ElMessage.warning('没有生成可用的自动预匹配结果')

    return

  }

  subtitleManualPairs.value = pairs

  subtitleLastPairBuildMode.value = 'auto'

  subtitleSelectedManualPairId.value = pairs[0]?.id || ''

}



function clearSubtitleManualPairs () {

  subtitleManualPairs.value = []

  subtitleLastPairBuildMode.value = ''

  subtitleSelectedManualPairId.value = ''

  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }

  clearSubtitleSequenceSelection()

}



function joinPath (basePath, name) {

  return `${String(basePath || '').replace(/[\\/]+$/, '')}/${String(name || '').replace(/^[/\\]+/, '')}`

}



async function rollbackSubtitleManualRenamePairs (pairs, audioLibraryId, subtitleLibraryId) {

  if (!Array.isArray(pairs) || !pairs.length) return { restored: 0, failed: [] }

  const failed = []

  let restored = 0



  for (const pair of [...pairs].reverse()) {

    const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId

    const rollbackSourcePath = pair.final_path || pair.temp_path

    if (!rollbackSourcePath || !pair.current_name) continue

    try {

      await libraryApi.browserRename(operationLibraryId, rollbackSourcePath, pair.current_name, {

        skipActivityLog: true,

        renameContext: 'subtitle_manual_match_pair'

      })

      restored += 1

    } catch (error) {

      failed.push({

        kind: pair.kind,

        source: rollbackSourcePath,

        target: pair.current_name,

        error: error.response?.data?.detail || error.message || '回滚失败'

      })

    }

  }



  return { restored, failed }

}



async function applySubtitleManualPairs () {

  if (!subtitleManualPairs.value.length) {

    ElMessage.warning('请先添加至少一组配对')

    return

  }



  const audioLibraryId = subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value

  const subtitleLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || audioLibraryId

  const isLinkedImport = isLinkedSubtitleImportWorkbench.value

  const effectiveNamingStrategy = isLinkedImport ? (subtitleOptions.value.namingStrategy || 'audio') : subtitleOptions.value.namingStrategy

  const appliedPairCount = subtitleManualPairs.value.length

  const unusedSubtitleRows = subtitleInspectorSubtitleFiles.value.filter(

    item => !subtitleManualPairs.value.some(pair => pair.subtitle_path === item.path)

  )

  const unusedSubtitlePathSet = new Set(unusedSubtitleRows.map(item => item.path).filter(Boolean))

  const audioPairConflictMap = new Map()

  const subtitlePairConflictMap = new Map()



  subtitleManualPairs.value.forEach(pair => {

    const audioKey = buildRenameConflictKey(pair.audio_path, pair.target_audio_name)

    const subtitleKey = buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name)

    audioPairConflictMap.set(audioKey, (audioPairConflictMap.get(audioKey) || 0) + 1)

    subtitlePairConflictMap.set(subtitleKey, (subtitlePairConflictMap.get(subtitleKey) || 0) + 1)

  })



  const audioConflicts = subtitleManualPairs.value.filter(pair => {

    const targetKey = buildRenameConflictKey(pair.audio_path, pair.target_audio_name)

    if ((audioPairConflictMap.get(targetKey) || 0) > 1) return true

    const existing = subtitleInspectorAudioFiles.value.find(item => (

      item.name === pair.target_audio_name &&

      buildRenameConflictKey(item.path, item.name) === targetKey

    ))

    return existing && existing.path !== pair.audio_path

  })

  if (audioConflicts.length) {

    ElMessage.error(`存在目标音频名冲突，无法直接应用：${audioConflicts[0].target_audio_name}`)

    return

  }

  const subtitleConflicts = subtitleManualPairs.value.filter(pair => {

    const targetKey = buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name)

    if ((subtitlePairConflictMap.get(targetKey) || 0) > 1) return true

    const existing = subtitleInspectorSubtitleFiles.value.find(item => (

      item.name === pair.target_subtitle_name &&

      buildRenameConflictKey(item.path, item.name) === targetKey

    ))

    if (existing?.path && unusedSubtitlePathSet.has(existing.path)) return false

    return existing && existing.path !== pair.subtitle_path

  })

  if (subtitleConflicts.length) {

    ElMessage.error(`存在目标字幕名冲突，无法直接应用：${subtitleConflicts[0].target_subtitle_name}`)

    return

  }



  const namingStrategyLabel = subtitleOptions.value.namingStrategy === 'subtitle' ? '以字幕名为准' : '以音频名为准'

  const applyActionLabel = isLinkedImport ? '重命名并导入' : '确定应用'

  try {

    await showSystemConfirm({

      title: '应用配对确认',

      message: `确定处理 ${subtitleManualPairs.value.length} 组配对结果吗？\n\n同名依据：${namingStrategyLabel}${unusedSubtitleRows.length ? `\n当前未使用的 ${unusedSubtitleRows.length} 个原始字幕会一并删除。` : ''}${isLinkedImport ? '\n确认后会先在本地工作区完成重命名，再导入目标库存。' : ''}`,

      tone: 'warning',

      confirmText: applyActionLabel,

      cancelText: '取消'

    })

  } catch (_) {

    return

  }



  subtitlePairApplying.value = true

  const phaseOneCompleted = []

  const phaseTwoCompleted = []

  const preApplySnapshot = createSubtitleManualMatchSnapshot()

  try {

    const currentSubtitleFiles = [...subtitleInspectorSubtitleFiles.value]

    const resolveCurrentSubtitleSourcePath = (pair) => {

      const exactMatch = currentSubtitleFiles.find(item => item.path === pair.subtitle_path)

      if (exactMatch?.path) return exactMatch.path



      const sameNameMatches = currentSubtitleFiles.filter(item => item.name === pair.subtitle_name)

      if (sameNameMatches.length === 1) return sameNameMatches[0].path



      const sameRelativeMatches = currentSubtitleFiles.filter(item => (item.relative_path || item.name) === pair.subtitle_relative_path)

      if (sameRelativeMatches.length === 1) return sameRelativeMatches[0].path



      return pair.subtitle_path

    }



    const operations = subtitleManualPairs.value.flatMap(pair => {

      const next = []

      if (pair.audio_name !== pair.target_audio_name) {

        next.push({

          kind: 'audio',

          source_path: pair.audio_path,

          current_name: pair.audio_name,

          target_name: pair.target_audio_name

        })

      }

      if (pair.subtitle_name !== pair.target_subtitle_name) {

        next.push({

          kind: 'subtitle',

          source_path: resolveCurrentSubtitleSourcePath(pair),

          current_name: pair.subtitle_name,

          target_name: pair.target_subtitle_name

        })

      }

      return next

    })

    const phaseOne = operations

      .filter(item => item.current_name !== item.target_name)

      .map((pair, index) => ({

        ...pair,

        temp_name: `__manual_match_${pair.kind}_${String(index + 1).padStart(3, '0')}_${Date.now()}.tmp${pair.current_name.match(/\.[^.]+$/)?.[0] || ''}`

      }))



    for (const pair of phaseOne) {

      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId

      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.source_path, pair.temp_name, {

        skipActivityLog: true,

        renameContext: 'subtitle_manual_match_pair'

      })

      pair.temp_path = renameResult?.new_path || joinPath(String(pair.source_path || '').replace(/[\\/][^\\/]+$/, ''), pair.temp_name)

      phaseOneCompleted.push(pair)

    }



    for (const pair of phaseOne) {

      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId

      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.temp_path, pair.target_name, {

        skipActivityLog: true,

        renameContext: 'subtitle_manual_match_pair'

      })

      pair.final_path = renameResult?.new_path || joinPath(String(pair.temp_path || '').replace(/[\\/][^\\/]+$/, ''), pair.target_name)

      phaseTwoCompleted.push(pair)

    }



    for (const subtitle of unusedSubtitleRows) {

      await libraryApi.browserDelete(subtitleLibraryId, resolveSubtitleEntryPath(subtitle), true)

    }



    const currentTaskId = subtitleInspectorInfo.value.taskId

    const matchedSelectionItem = subtitleDialogSelection.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value) || {

      library_id: subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

      folder_path: subtitleInspectorInfo.value.folderPath,

      folder_name: getFileName(subtitleInspectorInfo.value.folderPath),

      rjcode: extractRJCode(subtitleInspectorInfo.value.folderPath || '') || '',

      source_label: subtitleInspectorInfo.value.sourceLabel || '',

      source_mode: subtitleInspectorInfo.value.sourceMode || '',

      restored_at: subtitleInspectorInfo.value.restoredAt || '',

      activity_context: subtitleInspectorInfo.value.activityContext || null

    }

    const fallbackTask = currentTaskId

      ? null

      : findSubtitleTaskBySelection(matchedSelectionItem)

    const effectiveTaskId = currentTaskId || fallbackTask?.id || ''

    if (effectiveTaskId) {

      const pairChanges = subtitleManualPairs.value.map(pair => ({

        audio_before: pair.audio_name || '',

        audio_after: pair.target_audio_name || '',

        subtitle_before: pair.subtitle_name || '',

        subtitle_after: pair.target_subtitle_name || ''

      }))

      await rjSubtitleApi.completeManual(effectiveTaskId, {

        appliedPairs: appliedPairCount,

        deletedSubtitles: unusedSubtitleRows.length,

        namingStrategy: effectiveNamingStrategy,

        pairChanges,

        folderPath: subtitleInspectorInfo.value.folderPath || matchedSelectionItem.folder_path || '',

        libraryId: subtitleInspectorInfo.value.libraryId || matchedSelectionItem.library_id || selectedLibraryId.value,

        rjcode: matchedSelectionItem.rjcode || extractRJCode(subtitleInspectorInfo.value.folderPath || '') || ''

      })

      markSubtitleTaskManualMatchCompleted(effectiveTaskId, {

        appliedPairs: appliedPairCount,

        deletedSubtitles: unusedSubtitleRows.length,

        namingStrategy: effectiveNamingStrategy,

        currentStep: `${buildSubtitleManualMatchSummary({ appliedPairs: appliedPairCount, deletedSubtitles: unusedSubtitleRows.length })}，可继续重新筛选后再次应用`

      })



      await Promise.all([

        refreshLibrary({ silent: true }),

        refreshRJSubtitleStatus(false, { silent: true })

      ])



      if (isLinkedImport) {

        const refreshedTask = subtitleTasks.value.find(task => task.id === effectiveTaskId)

        if (refreshedTask?.subtitle_dir) {

          await inspectSubtitleTask(refreshedTask, { force: true })

        } else {

          clearSubtitleInspectorState()

        }

      } else {

        await reloadSubtitleInspector()

      }

    } else {

      markSubtitleSelectionManualMatchCompleted(matchedSelectionItem, {

        appliedPairs: appliedPairCount,

        deletedSubtitles: unusedSubtitleRows.length

      })

      subtitleInspectorInfo.value = {

        ...subtitleInspectorInfo.value,

        manualMatchCompleted: true,

        manualMatchAppliedPairs: appliedPairCount,

        manualMatchDeletedSubtitles: unusedSubtitleRows.length,

        manualMatchMessage: `${buildSubtitleManualMatchSummary({ appliedPairs: appliedPairCount, deletedSubtitles: unusedSubtitleRows.length })}，可继续重新筛选后再次应用`

      }

      await reloadSubtitleInspector()

      await Promise.all([

        refreshLibrary({ silent: true }),

        refreshRJSubtitleStatus(false, { silent: true })

      ])

    }



    ElMessage.success(`${isLinkedImport ? '已重命名并导入' : '已应用'} ${appliedPairCount} 组配对${unusedSubtitleRows.length ? `，并删除 ${unusedSubtitleRows.length} 个未使用字幕` : ''}。当前目录已标记为已执行过配对，可继续调整后再次应用。`)

    clearSubtitleManualPairs()

  } catch (error) {

    const rollbackPairs = [

      ...phaseTwoCompleted,

      ...phaseOneCompleted.filter(pair => !phaseTwoCompleted.includes(pair))

    ]

    let rollbackSummary = ''

    if (rollbackPairs.length) {

      const rollbackResult = await rollbackSubtitleManualRenamePairs(rollbackPairs, audioLibraryId, subtitleLibraryId)

      rollbackSummary = rollbackResult.failed.length

        ? `；已回滚 ${rollbackResult.restored} 项，仍有 ${rollbackResult.failed.length} 项需要手动恢复`

        : `；已自动回滚 ${rollbackResult.restored} 项`

      if (!rollbackResult.failed.length) {

        await Promise.all([

          refreshLibrary({ silent: true }),

          refreshRJSubtitleStatus(false, { silent: true }),

          reloadSubtitleInspector()

        ])

        restoreSubtitleManualMatchSnapshot(preApplySnapshot)

      }

    }

    ElMessage.error(`${isLinkedImport ? '重命名并导入' : '应用配对'}失败: ${(error.response?.data?.detail || error.message)}${rollbackSummary}`)

  } finally {

    subtitlePairApplying.value = false

  }

}



function escapeHtml (value) {

  return String(value ?? '')

    .replace(/&/g, '&amp;')

    .replace(/</g, '&lt;')

    .replace(/>/g, '&gt;')

    .replace(/"/g, '&quot;')

    .replace(/'/g, '&#39;')

}



function decodePossibleMojibake (value) {

  const text = String(value || '')

  if (!/[ÃÂÐæçéèêïîöôåäüë鈥]/.test(text) && !/[鐩鍙彇瀛]/.test(text)) return text

  try {

    const bytes = Uint8Array.from(Array.from(text).map(char => char.charCodeAt(0) & 0xff))

    const decoded = new TextDecoder('utf-8', { fatal: false }).decode(bytes)

    return decoded && /[\u4e00-\u9fff]/.test(decoded) ? decoded : text

  } catch (_) {

    return text

  }

}



function isSubtitleDirectoryMissingError (error) {

  const detail = decodePossibleMojibake(error?.response?.data?.detail || error?.message || '')

  return /目标文件夹不存在|未找到目录摘要/.test(detail)

}



function syncRemoteStatsDeletion ({ deletedBytes = 0, deletedFolderCount = 0, libraryId = selectedLibraryId.value } = {}) {

  if (!libraryId) return

  const current = statsMap.value[libraryId]

  if (!current) return



  const sizeDelta = Math.max(0, Number(deletedBytes || 0))

  const folderDelta = Math.max(0, Number(deletedFolderCount || 0))

  const nextLibraryStats = {

    ...current,

    total_size_bytes: Math.max(0, Number(current.total_size_bytes || 0) - sizeDelta),

    folder_count: Math.max(0, Number(current.folder_count || 0) - folderDelta),

    updated_at: Date.now() / 1000,

    total_size_gb: 0

  }

  nextLibraryStats.total_size_gb = Number((nextLibraryStats.total_size_bytes / (1024 ** 3)).toFixed(2))



  statsMap.value = {

    ...statsMap.value,

    [libraryId]: nextLibraryStats

  }



  aggregateStats.value = {

    ...aggregateStats.value,

    total_size_bytes: Math.max(0, Number(aggregateStats.value.total_size_bytes || 0) - sizeDelta),

    folder_count: Math.max(0, Number(aggregateStats.value.folder_count || 0) - folderDelta),

    total_size_gb: 0

  }

  aggregateStats.value.total_size_gb = Number((aggregateStats.value.total_size_bytes / (1024 ** 3)).toFixed(2))

}



async function refreshStatsAfterMutation (options = {}) {

  const { deletedBytes = 0, deletedFolderCount = 0, libraryId = selectedLibraryId.value } = options

  if (isRemoteCurrentLibrary.value) {

    syncRemoteStatsDeletion({ deletedBytes, deletedFolderCount, libraryId })

    return

  }

  await refreshStats(false, { silent: true, refreshLibraryId: libraryId })

}



function resolvePreferredSubtitleWorkbenchStageForTask (task) {

  if (!task) return 'overview'

  if (task.awaiting_manual_match) return 'pairing'

  if (task.manual_match_completed && task.subtitle_dir) return 'tree'

  if (task.subtitle_dir) return 'pairing'

  return 'overview'

}



function resolvePreferredSubtitleWorkbenchStageForSelection (item) {

  if (!item) return 'overview'

  const matchedTask = findSubtitleTaskBySelection(item)

  if (matchedTask) return resolvePreferredSubtitleWorkbenchStageForTask(matchedTask)

  if (canInspectSubtitleSelectionFolder(item)) return 'pairing'

  return 'overview'

}



function setSubtitleWorkbenchContextMode (mode) {

  subtitleWorkbenchContextMode.value = ['settings', 'pairing', 'tree'].includes(mode) ? mode : 'settings'

}



function setActiveSubtitleWorkbenchStage (stage, options = {}) {

  const nextStage = ['overview', 'pairing', 'tree'].includes(stage) ? stage : 'overview'

  activeSubtitleWorkbenchStage.value = nextStage

  if (options.syncContext === false) return

  if (nextStage === 'pairing') setSubtitleWorkbenchContextMode('pairing')

  else if (nextStage === 'tree') setSubtitleWorkbenchContextMode('tree')

  else setSubtitleWorkbenchContextMode('settings')

}



function setSubtitleWorkbenchRailMode (mode) {

  subtitleWorkbenchRailMode.value = mode === 'tasks' ? 'tasks' : 'scan'

}



function toggleSubtitleWorkbenchDrawer () {

  subtitleWorkbenchDrawerCollapsed.value = !subtitleWorkbenchDrawerCollapsed.value

}



async function focusSubtitleSelectionItem (item) {

  if (!item?.folder_path) return

  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)

  syncSubtitleTaskListState()

  const matchedTask = findSubtitleTaskBySelection(item)

  if (matchedTask?.subtitle_dir) {

    await inspectSubtitleTask(matchedTask)

    return

  }

  if (canInspectSubtitleSelectionFolder(item)) {

    await inspectSubtitleSelectionFolder(item)

    return

  }

  if (!matchedTask || subtitleInspectorInfo.value.taskId !== matchedTask.id) {

    clearSubtitleInspectorState()

  }

}



async function forceCreateSubtitleTaskForSelection (item) {

  if (!item?.folder_path) return

  const forceKey = buildSubtitleSelectionKey(item)

  subtitleForceQueueKey.value = forceKey

  resetSubtitleScanRunIndicators()

  incrementSubtitleScanSession('foundDirectories')

  try {

    upsertSubtitleSelectionEntry(item, {

      queue_state: 'checking_subtitle',

      queue_message: '正在检测远程字幕'

    })

    const availability = await ensureRJSubtitleAvailabilityForItem(item)

    if (!availability.hasSubtitle) {

      incrementSubtitleScanSession('noSubtitleTargets')

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_no_subtitle',

        queue_message: availability.message || 'asmr.one 没字幕'

      })

      ElMessage.warning(availability.message || 'asmr.one 没字幕，无法创建任务')

      return

    }



    upsertSubtitleSelectionEntry(item, {

      queue_state: 'creating',

      queue_message: availability.message || '检测到可用字幕，正在加入任务'

    })

    const data = await submitRJSubtitleTasks([item], {

      silent: false,

      refresh: true,

      skipIfExistingSubtitlesOverride: true

    })

    const skippedItem = Array.isArray(data?.skipped_items)

      ? data.skipped_items.find(entry => buildSubtitleSelectionKey(entry) === buildSubtitleSelectionKey(item))

      : null

    if (skippedItem?.queue_state === 'skipped_kikoeru_existing') {

      incrementSubtitleScanSession('existingSubtitles')

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_kikoeru_existing',

        queue_message: skippedItem.queue_message || 'Kikoeru 已有字幕，未加入抓取任务'

      })

      ElMessage.info(skippedItem.queue_message || 'Kikoeru 已有字幕，已跳过')

      return

    }

    if (skippedItem?.queue_state === 'existing_task') {

      incrementSubtitleScanSession('existingTasks')

      upsertSubtitleSelectionEntry(item, {

        task_id: skippedItem.task_id || '',

        queue_state: 'existing_task',

        queue_message: skippedItem.queue_message || '任务已存在'

      })

      if (skippedItem.task_id) subtitleActiveTaskId.value = skippedItem.task_id

      ElMessage.info(skippedItem.queue_message || '任务已存在')

      return

    }

    if (skippedItem?.queue_state === 'skipped_no_subtitle') {

      incrementSubtitleScanSession('noSubtitleTargets')

      upsertSubtitleSelectionEntry(item, {

        queue_state: 'skipped_no_subtitle',

        queue_message: skippedItem.queue_message || '远程无字幕'

      })

      ElMessage.warning(skippedItem.queue_message || '远程无字幕，无法创建任务')

      return

    }

    const createdTask = data?.tasks?.[0] || null

    if (createdTask?.task_id) {

      incrementSubtitleScanSession('createdTasks')

      upsertSubtitleTaskLocal(createOptimisticSubtitleTask(item, createdTask.task_id))

      upsertSubtitleSelectionEntry(item, {

        task_id: createdTask.task_id,

        queue_state: 'queued',

        queue_message: '已加入任务'

      })

      subtitleActiveTaskId.value = createdTask.task_id

      return

    }

    incrementSubtitleScanSession('createFailed')

    upsertSubtitleSelectionEntry(item, {

      queue_state: 'create_failed',

      queue_message: data?.message || '未创建任务'

    })

  } catch (error) {

    incrementSubtitleScanSession('createFailed')

    upsertSubtitleSelectionEntry(item, {

      queue_state: 'create_failed',

      queue_message: error.response?.data?.detail || error.message || '加入任务失败'

    })

  } finally {

    subtitleForceQueueKey.value = ''

  }

}



async function handleSubtitleWorkbenchSelectSelection (item, options = {}) {

  await focusSubtitleSelectionItem(item)

  setSubtitleWorkbenchRailMode('scan')

  setActiveSubtitleWorkbenchStage(options.stage || resolvePreferredSubtitleWorkbenchStageForSelection(item))

}



async function handleSubtitleWorkbenchInspectSelectionFolder (item, options = {}) {

  await inspectSubtitleSelectionFolder(item, options)

  setSubtitleWorkbenchRailMode('scan')

  setActiveSubtitleWorkbenchStage(options.stage || 'tree')

}



function isSubtitleSelectionActive (item) {

  return buildSubtitleSelectionKey(item) === buildSubtitleSelectionKey(focusedSubtitleSelectionItem.value)

}



async function selectSubtitleTask (task) {

  if (!task?.id) return

  subtitleActiveTaskId.value = task.id

  subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)

  if (canLockSubtitleTaskToRuntimeOnly(task)) {

    clearSubtitleInspectorState()

    return

  }

  if (task.subtitle_dir) {

    await inspectSubtitleTask(task)

    return

  }

  clearSubtitleInspectorState()

}



function canLockSubtitleTaskToRuntimeOnly (task) {

  return Boolean(isSubtitleTaskRerunLocked(task))

}



async function handleSubtitleWorkbenchSelectTask (task, options = {}) {

  await selectSubtitleTask(task)

  setSubtitleWorkbenchRailMode('tasks')

  setActiveSubtitleWorkbenchStage(options.stage || resolvePreferredSubtitleWorkbenchStageForTask(task))

}



async function handleSubtitleWorkbenchInspectTask (task, options = {}) {

  await inspectSubtitleTask(task, options)

  setSubtitleWorkbenchRailMode('tasks')

  setActiveSubtitleWorkbenchStage(options.stage || resolvePreferredSubtitleWorkbenchStageForTask(task))

}



async function refreshCurrentView () {

  if (isRefreshingCurrentView.value) return

  isRefreshingCurrentView.value = true

  try {

    const jobs = [refreshLibrary({ silent: true })]

    if (folderDialogVisible.value && folderDialogRef.value?.reload) {

      jobs.push(folderDialogRef.value.reload())

    }

    if (filterDeleteDialogVisible.value && filterDeleteDialogRef.value?.reload) {

      jobs.push(filterDeleteDialogRef.value.reload())

    }

    if (subtitleDialogSessionActive.value) {

      jobs.push(refreshRJSubtitleStatus(false, { silent: true }))

      if (subtitleInspectorInfo.value.subtitleDir && activeSubtitleInspectTask.value) {

        jobs.push(inspectSubtitleTask(activeSubtitleInspectTask.value, { force: true }))

      }

    }

    await Promise.all(jobs)

    ElMessage.success('当前页面信息已刷新')

  } catch (error) {

    ElMessage.error('刷新当前页面失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    isRefreshingCurrentView.value = false

  }

}



function resolveSubtitleAvailabilityTarget () {

  if (activeSubtitleTask.value) {

    return {

      rjcode: getTaskDisplayRJCode(activeSubtitleTask.value),

      folderName: activeSubtitleTask.value.folder_name || getFileName(activeSubtitleTask.value.folder_path)

    }

  }

  if (focusedSubtitleSelectionItem.value) {

    return {

      rjcode: focusedSubtitleSelectionItem.value.rjcode || '',

      folderName: focusedSubtitleSelectionItem.value.folder_name || getFileName(focusedSubtitleSelectionItem.value.folder_path)

    }

  }

  if (currentFolderSubtitleItem.value) {

    return {

      rjcode: currentFolderSubtitleItem.value.rjcode || '',

      folderName: currentFolderSubtitleItem.value.folder_name || getFileName(currentFolderSubtitleItem.value.folder_path)

    }

  }

  return null

}



function getSubtitleAttemptTypeLabel (value) {

  const mapping = {

    requested: '当前作品',

    original: '原作',

    parent: '母作品',

    child: '关联子作品',

    translation: '关联译版'

  }

  return mapping[String(value || '')] || '关联作品'

}



async function checkRJSubtitleAvailability () {

  subtitleConnectivityLoading.value = true

  try {

    const target = resolveSubtitleAvailabilityTarget()

    if (!target?.rjcode) {

      ElMessage.warning('请先选中一个待处理目录或字幕任务')

      return

    }

    const data = await rjSubtitleApi.checkSubtitleAvailability(target.rjcode)

    const attempts = data.attempts || []

    const found = attempts.filter(item => Number(item.subtitle_count || 0) > 0)

    const summaryBlock = `<div style="margin-bottom:12px;padding:10px 12px;border:1px solid #d9ecff;background:#f4faff;border-radius:8px;color:#245b96;">

      目标目录: ${escapeHtml(target.folderName || '-') }<br>

      检测 RJ: ${escapeHtml(data.rjcode || target.rjcode)}<br>

      结果: ${found.length ? `找到 ${found.length} 个有字幕的版本` : '未发现可用字幕版本'}

    </div>`

    const listHtml = attempts.length

      ? attempts.map(item => {

          const subtitleCount = Number(item.subtitle_count || 0)

          const hasSubtitle = subtitleCount > 0

          return `<div style="padding:10px 0;border-bottom:1px solid #ebeef5;">

            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">

              <span style="font-weight:700;color:#303133;">${escapeHtml(item.rjcode || '-')}</span>

              <span style="padding:2px 8px;border-radius:999px;background:${hasSubtitle ? '#ecfdf3' : '#f5f7fa'};color:${hasSubtitle ? '#2f855a' : '#606266'};font-size:12px;font-weight:700;">

                ${hasSubtitle ? `有字幕 ${subtitleCount}` : '无字幕'}

              </span>

              <span style="padding:2px 8px;border-radius:999px;background:#eef4ff;color:#31599b;font-size:12px;">

                ${escapeHtml(getSubtitleAttemptTypeLabel(item.work_type))}

              </span>

              <span style="padding:2px 8px;border-radius:999px;background:#fff7e6;color:#b7791f;font-size:12px;">

                ${escapeHtml(getRJSubtitleLangLabel(item.lang || 'JPN'))}

              </span>

            </div>

            <div style="margin-top:6px;color:#303133;line-height:1.5;">${escapeHtml(item.title || item.reason || '未返回作品标题')}</div>

          </div>`

        }).join('')

      : '<div>没有返回作品检测结果</div>'

    const html = `${summaryBlock}${listHtml}`



    await showSystemAlert({

      title: '作品字幕检测结果',

      message: html,

      html: true,

      confirmText: '知道了'

    })

  } catch (error) {

    ElMessage.error('字幕检测失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    subtitleConnectivityLoading.value = false

  }

}



async function navigateToPath (path) {

  const targetPath = path || browseRootPath.value || currentPath.value

  const targetPage = getRememberedDirectoryPage(targetPath, 1)

  const shouldRefreshNow = currentPage.value === targetPage

  rememberCurrentDirectoryPage()

  locatedLibraryPath.value = ''

  currentPath.value = targetPath

  currentPage.value = targetPage

  clearSelection()

  if (shouldRefreshNow) await refreshLibrary()

}



async function goToParent () {

  if (!canGoParent.value) return

  if (searchResultReturnState.value.active) {

    const restoreState = { ...searchResultReturnState.value }

    searchResultReturnState.value = createSearchResultReturnState()

    clearSelection()

    locatedLibraryPath.value = ''

    if (restoreState.libraryId && restoreState.libraryId !== selectedLibraryId.value) {

      pendingLibrarySearchRestore.value = restoreState

      selectedLibraryId.value = restoreState.libraryId

      return

    }

    searchQuery.value = restoreState.searchQuery || ''

    searchExact.value = Boolean(restoreState.searchExact)

    searchResultKind.value = restoreState.searchResultKind || 'all'

    currentPath.value = restoreState.currentPath || ''

    browseRootPath.value = restoreState.browseRootPath || ''

    currentPage.value = Number(restoreState.page || 1)

    sortBy.value = restoreState.sortBy || DEFAULT_SORT_BY

    sortOrder.value = restoreState.sortOrder || DEFAULT_SORT_ORDER

    librarySearchState.value = createLibrarySearchState({

      active: true,

      query: restoreState.searchState?.query || restoreState.searchQuery || '',

      rootPath: restoreState.searchState?.rootPath || restoreState.currentPath || '',

      truncated: Boolean(restoreState.searchState?.truncated),

      scannedDirectories: Number(restoreState.searchState?.scannedDirectories || 0),

      globalRemote: Boolean(restoreState.searchState?.globalRemote),

      searchedLibraries: Number(restoreState.searchState?.searchedLibraries || 0),

      hitLibraries: Number(restoreState.searchState?.hitLibraries || 0),

      exactSearch: Boolean(restoreState.searchState?.exactSearch ?? restoreState.searchExact),

      resultKind: restoreState.searchState?.resultKind || restoreState.searchResultKind || 'all'

    })

    await refreshLibrary({ forceRefresh: true })

    return

  }

  await navigateToPath(parentPath.value)

}



function isSearchResultRow (row) {

  return Boolean(librarySearchState.value.active && row?.search_hit)

}



function getSearchResultLibraryLabel (row) {

  const directName = String(row?.library_name || '').trim()

  if (directName) return directName

  const libraryId = String(row?.library_id || '').trim()

  if (!libraryId) return ''

  return libraries.value.find(item => item.id === libraryId)?.name || libraryId

}



function getLibraryLabelById (libraryId) {

  const normalized = String(libraryId || '').trim()

  if (!normalized) return ''

  return libraries.value.find(item => item.id === normalized)?.name || normalized

}



async function locateLibrarySearchResult (row) {

  if (!row?.path) return

  if (librarySearchState.value.active) {

    searchResultReturnState.value = createSearchResultReturnState({

      active: true,

      libraryId: selectedLibraryId.value,

      searchQuery: searchQuery.value,

      currentPath: currentPath.value,

      browseRootPath: browseRootPath.value,

      page: currentPage.value,

      sortBy: sortBy.value,

      sortOrder: sortOrder.value,

      searchExact: searchExact.value,

      searchResultKind: searchResultKind.value,

      searchState: { ...librarySearchState.value }

    })

  }

  const targetLibraryId = row.library_id || selectedLibraryId.value

  const targetPath = row.is_directory ? row.path : (row.parent_path || row.path)

  const highlightPath = row.path

  locatedLibraryPath.value = row.path

  searchQuery.value = ''

  librarySearchState.value = createLibrarySearchState()

  clearSelection()

  if (targetLibraryId && targetLibraryId !== selectedLibraryId.value) {

    pendingLibraryLocate.value = {

      libraryId: targetLibraryId,

      path: targetPath,

      highlightPath

    }

    selectedLibraryId.value = targetLibraryId

    return

  }

  currentPath.value = targetPath

  locatedLibraryPath.value = highlightPath

  const shouldRefreshNow = currentPage.value === 1

  currentPage.value = 1

  if (shouldRefreshNow) await refreshLibrary()

}



async function openFolder (row) {

  if (isSearchResultRow(row)) {

    await locateLibrarySearchResult(row)

    return

  }

  if (row?.is_directory) {

    locatedLibraryPath.value = ''

    await navigateToPath(row.path)

    return

  }

  if (isRemoteCurrentLibrary.value) {

    const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)

    await showSystemAlert({

      title: '远程库存',

      message: `请在群晖 FileStation 中打开以下路径：<br><br>${escapeHtml(data.path || row.path)}<br><br>${escapeHtml(data.remote_url || '')}`,

      html: true,

      confirmText: '知道了'

    })

    return

  }

  const data = await libraryApi.openFolder(row.path)

  if (data.mode === 'mapped') {

    mappedPathInfo.value = { originalPath: data.original_path, mappedPath: data.mapped_path, isMapped: data.is_mapped }

    mappedPathDialogVisible.value = true

    return

  }

  ElMessage.success('已打开文件夹')

}



async function openFolderDirect (row) {

  if (isRemoteCurrentLibrary.value) {

    try {

      const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)

      if (data.web_url) {

        window.open(data.web_url, '_blank', 'noopener')

        ElMessage.success('已打开群晖目录')

        return

      }

      await showSystemAlert({

        title: '远程库存',

        message: `请在群晖 FileStation 中打开以下路径：<br><br>${escapeHtml(data.path || row.path)}`,

        html: true,

        confirmText: '知道了'

      })

    } catch (error) {

      ElMessage.error(error.response?.data?.detail || error.message || '打开群晖目录失败')

    }

    return

  }

  const data = await libraryApi.openFolder(row.path)

  if (data.mode !== 'mapped') {

    ElMessage.success('已打开文件夹')

    return

  }

  const path = data.mapped_path

  const hasHelper = window.kikoeruHelperLoaded || tampermonkeyLoaded.value

  window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))

  hasHelper ? ElMessage.success('正在打开文件夹...') : ElMessage.info('正在尝试打开文件夹...')

}



async function copyMappedPath () {

  try {

    await navigator.clipboard.writeText(mappedPathInfo.value.mappedPath)

    ElMessage.success('已复制')

  } catch (_) {

    ElMessage.error('复制失败')

  }

}



function openWithBrowser () {

  const path = mappedPathInfo.value.mappedPath

  if (window.kikoeruHelperLoaded || tampermonkeyLoaded.value) {

    window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))

    return

  }

  let url = path.replace(/\\/g, '/')

  url = /^[a-zA-Z]:/.test(url) ? `file:///${url}` : `file://${url}`

  try { window.open(url, '_blank') } catch (_) {}

}



function syncSubtitleInspectorTaskState () {

  if (!subtitleInspectorInfo.value.taskId) return

  const task = subtitleTasks.value.find(item => item.id === subtitleInspectorInfo.value.taskId)

  if (!task?.subtitle_dir) {

    if (subtitleInspectorInfo.value.subtitleDir && subtitleInspectorInfo.value.folderPath) {

      return

    }

    clearSubtitleInspectorState()

    return

  }

  subtitleInspectorInfo.value = {

    ...subtitleInspectorInfo.value,

    taskId: task.id,

    libraryId: task.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

    audioLibraryId: task.library_id || subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

    subtitleLibraryId: task.subtitle_library_id || subtitleInspectorInfo.value.subtitleLibraryId || task.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

    folderPath: task.folder_path,

    subtitleDir: task.subtitle_dir,

    sourceMode: task.source_mode || subtitleInspectorInfo.value.sourceMode || '',

    sourceLabel: task.source_label || subtitleInspectorInfo.value.sourceLabel || '',

    restoredAt: task.restored_at || subtitleInspectorInfo.value.restoredAt || '',

    activityContext: task.activity_context || subtitleInspectorInfo.value.activityContext || null,

    manualMatchCompleted: Boolean(task.manual_match_completed),

    manualMatchAppliedPairs: Number(task.manual_match_applied_pairs || 0),

    manualMatchDeletedSubtitles: Number(task.manual_match_deleted_subtitles || 0),

    manualMatchMessage: task.current_step || ''

  }

}



async function ensureSubtitleInspectorFocus () {

  if (!subtitleDialogVisible.value) return

  if (subtitleInspectorBusy.value || subtitleInspectorInfo.value.subtitleDir) return

  const preferredTaskId = resolveCurrentSubtitleTaskId(subtitleTasks.value)

  const preferredTask = subtitleTasks.value.find(task => task.id === preferredTaskId)

  if (preferredTask?.subtitle_dir) {

    await inspectSubtitleTask(preferredTask)

    return

  }



  const preferredSelectionItem = subtitleDialogSelection.value.find(

    item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value

  ) || null

  if (preferredSelectionItem && !shouldDelayAutoInspectSelectionFolder(preferredSelectionItem) && canInspectSubtitleSelectionFolder(preferredSelectionItem)) {

    await inspectSubtitleSelectionFolder(preferredSelectionItem, {

      force: true,

      preferredTaskId: preferredSelectionItem.task_id || ''

    })

    return

  }



  const inspectableSelectionItem = subtitleDialogSelection.value.find(item => (

    !shouldDelayAutoInspectSelectionFolder(item) && canInspectSubtitleSelectionFolder(item)

  )) || null

  if (inspectableSelectionItem) {

    await inspectSubtitleSelectionFolder(inspectableSelectionItem, {

      force: true,

      preferredTaskId: inspectableSelectionItem.task_id || ''

    })

    return

  }



  const nextTask = sortSubtitleTasksByCreatedAt(subtitleTasks.value.filter(task => task.subtitle_dir && isSubtitleTaskAwaitingManualWork(task)))[0]

    || sortSubtitleTasksByCreatedAt(subtitleTasks.value.filter(task => task.subtitle_dir))[0]

  if (nextTask?.subtitle_dir) {

    await inspectSubtitleTask(nextTask)

  }

}



async function inspectSubtitleSelectionFolder (item, options = {}) {

  const { force = false, preferredTaskId = '' } = options

  if (!item?.folder_path) return

  const loadSeq = ++subtitleInspectorLoadSeq.value



  const inspectorLibraryId = item.library_id || selectedLibraryId.value

  let subtitleDir = joinFolderPath(item.folder_path, 'subtitles')

  const matchedTask = findSubtitleTaskBySelection(item)

  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)



  if (

    !force &&

    !subtitleInspectorInfo.value.taskId &&

    subtitleInspectorInfo.value.folderPath === item.folder_path &&

    subtitleInspectorInfo.value.subtitleDir === subtitleDir &&

    !subtitleInspectorLoading.value

  ) {

    return

  }



  subtitleInspectorLoading.value = true

  try {

    const existingState = await ensureRJSubtitleExistingStateForItem(item)

    if (loadSeq !== subtitleInspectorLoadSeq.value) return

    if (existingState?.subtitleDir) {

      subtitleDir = existingState.subtitleDir

    }

    if (!existingState?.hasExistingSubtitles && !Number(item.existing_subtitle_count || 0) && item.status !== 'existing') {

      ElMessage.info('当前目录还没有本地字幕，暂时无法打开字幕树工作台')

      return

    }

    upsertSubtitleSelectionEntry(item, {

      status: existingState?.hasExistingSubtitles ? 'existing' : (item.status || ''),

      existing_subtitle_count: Math.max(

        Number(item.existing_subtitle_count || 0),

        Number(existingState?.existingSubtitleCount || 0)

      )

    })

    const [subtitleData, audioData] = await Promise.all([

      libraryApi.browserFolderContents(inspectorLibraryId, subtitleDir),

      libraryApi.browserFolderContents(inspectorLibraryId, item.folder_path)

    ])

    if (loadSeq !== subtitleInspectorLoadSeq.value) return

    subtitleInspectorSearch.value = ''

    subtitleInspectorItems.value = subtitleData.items || []

    subtitleInspectorAudioItems.value = audioData.items || []

    resetSubtitleManualMatchState()

    subtitleInspectorInfo.value = {

      taskId: matchedTask?.id || String(preferredTaskId || item.task_id || '').trim(),

      libraryId: inspectorLibraryId,

      audioLibraryId: matchedTask?.library_id || inspectorLibraryId,

      subtitleLibraryId: matchedTask?.subtitle_library_id || inspectorLibraryId,

      folderPath: item.folder_path || '',

      subtitleDir: subtitleData.folder_path || subtitleDir,

      sourceMode: matchedTask?.source_mode || '',

      sourceLabel: matchedTask?.source_label || item.source_label || '',

      restoredAt: matchedTask?.restored_at || item.restored_at || '',

      activityContext: matchedTask?.activity_context || item.activity_context || null,

      manualMatchCompleted: Boolean(matchedTask?.manual_match_completed ?? item.manual_match_completed),

      manualMatchAppliedPairs: Number(matchedTask?.manual_match_applied_pairs ?? item.manual_match_applied_pairs ?? 0),

      manualMatchDeletedSubtitles: Number(matchedTask?.manual_match_deleted_subtitles ?? item.manual_match_deleted_subtitles ?? 0),

      manualMatchMessage: String(matchedTask?.current_step || item.queue_message || ''),

      totalFiles: subtitleData.total_files || 0,

      totalSize: (subtitleData.items || []).reduce((sum, child) => sum + (child.size || 0), 0)

    }

    const opened = new Set()

    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })

    subtitleInspectorExpandedIds.value = opened

    subtitleInspectorSelectedIds.value = new Set()

    subtitleInspectorLastSelectedId.value = ''

    syncSubtitleSelectionState()

    await nextTick()

    if (loadSeq !== subtitleInspectorLoadSeq.value) return

    buildAutoSubtitlePairs()

  } catch (error) {

    if (error instanceof TypeError && /parentNode/.test(error.message || '')) {

      console.warn('[subtitle-inspector] 忽略 Vue 过渡残留错误:', error.message)

    } else if (isSubtitleDirectoryMissingError(error)) {

      clearSubtitleInspectorState()

      ElMessage.info('当前字幕目录还未生成，或历史恢复的旧目录已失效')

    } else {

      ElMessage.error('加载现有字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))

    }

  } finally {

    if (loadSeq === subtitleInspectorLoadSeq.value) {

      subtitleInspectorLoading.value = false

    }

  }

}



async function inspectSubtitleTask (task, options = {}) {

  const { force = false } = options

  if (!task?.subtitle_dir) {

    ElMessage.warning('当前任务还没有生成字幕目录')

    return

  }

  const loadSeq = ++subtitleInspectorLoadSeq.value



  focusSubtitleTask(task.id)

  subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)

  if (

    !force &&

    subtitleInspectorInfo.value.taskId === task.id &&

    subtitleInspectorInfo.value.subtitleDir === task.subtitle_dir &&

    !subtitleInspectorLoading.value

  ) {

    return

  }

  subtitleInspectorLoading.value = true

  try {

    const audioLibraryId = task.library_id || selectedLibraryId.value

    const subtitleLibraryId = task.subtitle_library_id || audioLibraryId

    const [subtitleData, audioData] = await Promise.all([

      libraryApi.browserFolderContents(subtitleLibraryId, task.subtitle_dir),

      libraryApi.browserFolderContents(audioLibraryId, task.folder_path)

    ])

    if (loadSeq !== subtitleInspectorLoadSeq.value) return

    subtitleInspectorSearch.value = ''

    subtitleInspectorItems.value = subtitleData.items || []

    subtitleInspectorAudioItems.value = audioData.items || []

    resetSubtitleManualMatchState()

    subtitleInspectorInfo.value = {

      taskId: task.id,

      libraryId: audioLibraryId,

      audioLibraryId,

      subtitleLibraryId,

      folderPath: task.folder_path || '',

      subtitleDir: subtitleData.folder_path || task.subtitle_dir,

      sourceMode: task.source_mode || '',

      sourceLabel: task.source_label || subtitleInspectorInfo.value.sourceLabel || '',

      restoredAt: task.restored_at || subtitleInspectorInfo.value.restoredAt || '',

      activityContext: task.activity_context || subtitleInspectorInfo.value.activityContext || null,

      manualMatchCompleted: Boolean(task.manual_match_completed),

      manualMatchAppliedPairs: Number(task.manual_match_applied_pairs || 0),

      manualMatchDeletedSubtitles: Number(task.manual_match_deleted_subtitles || 0),

      manualMatchMessage: task.current_step || '',

      totalFiles: subtitleData.total_files || 0,

      totalSize: (subtitleData.items || []).reduce((sum, item) => sum + (item.size || 0), 0)

    }

    const opened = new Set()

    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })

    subtitleInspectorExpandedIds.value = opened

    subtitleInspectorSelectedIds.value = new Set()

    subtitleInspectorLastSelectedId.value = ''

    syncSubtitleSelectionState()

    await nextTick()

    if (loadSeq !== subtitleInspectorLoadSeq.value) return

    buildAutoSubtitlePairs()

  } catch (error) {

    if (error instanceof TypeError && /parentNode/.test(error.message || '')) {

      console.warn('[subtitle-inspector] 忽略 Vue 过渡残留错误:', error.message)

    } else if (isSubtitleDirectoryMissingError(error)) {

      clearSubtitleInspectorState()

      ElMessage.info(task.status === 'processing'

        ? '字幕任务仍在执行，目录生成后会自动可见'

        : '当前字幕目录还未生成，或历史恢复的旧目录已失效')

    } else {

      ElMessage.error('加载字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))

    }

  } finally {

    if (loadSeq === subtitleInspectorLoadSeq.value) {

      subtitleInspectorLoading.value = false

    }

  }

}



async function reloadSubtitleInspector () {

  if (activeSubtitleInspectTask.value) {

    await inspectSubtitleTask(activeSubtitleInspectTask.value, { force: true })

    return

  }

  if (subtitleInspectorInfo.value.subtitleDir && subtitleInspectorInfo.value.folderPath) {

    const matchedItem = subtitleDialogSelection.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value)

    await inspectSubtitleSelectionFolder({

      library_id: matchedItem?.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

      folder_path: matchedItem?.folder_path || subtitleInspectorInfo.value.folderPath,

      folder_name: matchedItem?.folder_name || getFileName(subtitleInspectorInfo.value.folderPath),

      rjcode: matchedItem?.rjcode || extractRJCode(subtitleInspectorInfo.value.folderPath || '') || '',

      source_label: matchedItem?.source_label || subtitleInspectorInfo.value.sourceLabel || '',

      source_mode: matchedItem?.source_mode || subtitleInspectorInfo.value.sourceMode || '',

      restored_at: matchedItem?.restored_at || subtitleInspectorInfo.value.restoredAt || '',

      activity_context: matchedItem?.activity_context || subtitleInspectorInfo.value.activityContext || null,

      manual_match_completed: matchedItem?.manual_match_completed || subtitleInspectorInfo.value.manualMatchCompleted,

      manual_match_applied_pairs: matchedItem?.manual_match_applied_pairs || subtitleInspectorInfo.value.manualMatchAppliedPairs,

      manual_match_deleted_subtitles: matchedItem?.manual_match_deleted_subtitles || subtitleInspectorInfo.value.manualMatchDeletedSubtitles,

      queue_message: matchedItem?.queue_message || subtitleInspectorInfo.value.manualMatchMessage

    }, { force: true })

  }

}



function isTextInputElement (target) {

  if (!target) return false

  const tagName = String(target.tagName || '').toUpperCase()

  return tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT' || target.isContentEditable

}



function getSubtitleInspectorSelectableIds () {

  return subtitleInspectorSelectableRows.value.map(row => row.id)

}



function selectSubtitleInspectorRange (targetId, preserveExisting = true) {

  const rowIds = getSubtitleInspectorSelectableIds()

  const targetIndex = rowIds.indexOf(targetId)

  if (targetIndex < 0) return

  const anchorId = subtitleInspectorLastSelectedId.value && rowIds.includes(subtitleInspectorLastSelectedId.value)

    ? subtitleInspectorLastSelectedId.value

    : targetId

  const anchorIndex = rowIds.indexOf(anchorId)

  const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex]

  const next = preserveExisting ? new Set(subtitleInspectorSelectedIds.value) : new Set()

  rowIds.slice(start, end + 1).forEach(id => next.add(id))

  subtitleInspectorSelectedIds.value = next

  subtitleInspectorLastSelectedId.value = targetId

}



function toggleSubtitleInspectorSelect (row, event = null) {

  if (subtitleInspectorBusy.value) return

  if (!row?.id) return

  if (event?.shiftKey) {

    selectSubtitleInspectorRange(row.id, true)

    return

  }

  const next = new Set(subtitleInspectorSelectedIds.value)

  next.has(row.id) ? next.delete(row.id) : next.add(row.id)

  subtitleInspectorSelectedIds.value = next

  subtitleInspectorLastSelectedId.value = row.id

}



function toggleAllSubtitleInspectorRows (event) {

  if (subtitleInspectorBusy.value) return

  const checked = !subtitleInspectorAllSelected.value

  subtitleInspectorSelectedIds.value = checked

    ? new Set(subtitleInspectorSelectableRows.value.map(row => row.id))

    : new Set()

  subtitleInspectorLastSelectedId.value = checked ? subtitleInspectorSelectableRows.value.at(-1)?.id || '' : ''

}



function clearSubtitleInspectorSelection () {

  if (subtitleInspectorBusy.value) return

  subtitleInspectorSelectedIds.value = new Set()

  subtitleInspectorLastSelectedId.value = ''

}



function handleSubtitleInspectorRowClick (row, event) {

  if (subtitleInspectorBusy.value) return

  if (!row?.id) return

  toggleSubtitleInspectorSelect(row, event)

}



function handleSubtitleDialogKeydown (event) {

  if (isTextInputElement(event.target)) return



  const key = String(event.key || '').toLowerCase()

  if ((event.ctrlKey || event.metaKey) && key === 'a') {

    event.preventDefault()

    if (!subtitleDialogVisible.value || !subtitleInspectorInfo.value.subtitleDir || subtitleInspectorBusy.value) return

    subtitleInspectorSelectedIds.value = new Set(getSubtitleInspectorSelectableIds())

    subtitleInspectorLastSelectedId.value = subtitleInspectorSelectableRows.value.at(-1)?.id || ''

  }

}



async function batchDeleteSubtitleTreeEntries () {

  const rows = [...subtitleInspectorSelectedRows.value]

  if (!rows.length) {

    ElMessage.warning('请先选择要删除的字幕文件或目录')

    return

  }

  const sortedRows = rows.sort((left, right) => (right.path || right.relative_path || '').length - (left.path || left.relative_path || '').length)

  try {

    await showSystemConfirm({

      title: '批量删除确认',

      message: `确定批量删除 ${sortedRows.length} 项字幕文件/目录吗？此操作不可恢复。`,

      tone: 'danger',

      confirmText: '确定删除',

      cancelText: '取消'

    })

  } catch (_) {

    return

  }



  subtitleInspectorDeleting.value = true

  try {

    const batchId = `subtitle-delete-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

    for (const row of sortedRows) {

      const path = resolveSubtitleEntryPath(row)

      await libraryApi.browserDelete(

        subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,

        path,

        true,

        { batchId }

      )

    }



    clearSubtitleInspectorSelection()

    ElMessage.success(`已删除 ${sortedRows.length} 项`)

    await Promise.all([reloadSubtitleInspector(), refreshLibrary({ silent: true }), refreshRJSubtitleStatus(false)])

  } catch (error) {

    ElMessage.error(`删除失败: ${decodePossibleMojibake(error.response?.data?.detail || error.message)}`)

  } finally {

    subtitleInspectorDeleting.value = false

  }

}



function onSubtitleInspectorSearchInput () {

  if (subtitleInspectorSearch.value.trim()) expandSubtitleInspectorTree()

}



function toggleSubtitleInspectorExpand (node) {

  const next = new Set(subtitleInspectorExpandedIds.value)

  next.has(node.id) ? next.delete(node.id) : next.add(node.id)

  subtitleInspectorExpandedIds.value = next

}



function expandSubtitleInspectorTree () {

  const next = new Set()

  const walk = nodes => nodes.forEach(node => { if (node.type === 'dir') { next.add(node.id); walk(node.children || []) } })

  walk(subtitleInspectorFilteredRoot.value)

  subtitleInspectorExpandedIds.value = next

}



function collapseSubtitleInspectorTree () {

  subtitleInspectorExpandedIds.value = new Set()

}



function resolveSubtitleTreeIcon (row) {

  if (row?.type === 'dir') {

    return subtitleInspectorExpandedIds.value.has(row.id) ? FolderOpened : Folder

  }

  return fileIcon(row?.name || '')

}



function openSubtitleRenameDialog (row) {

  if (row?.type !== 'file') return

  subtitleRenameForm.value = { currentName: row.name, newName: row.name, path: row.path }

  subtitleRenameDialogVisible.value = true

}



async function confirmSubtitleRename () {

  if (!subtitleRenameForm.value.newName || subtitleRenameForm.value.newName === subtitleRenameForm.value.currentName) {

    ElMessage.warning('请输入不同的新名称')

    return

  }



  subtitleRenameLoading.value = true

  try {

    await libraryApi.browserRename(subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value, subtitleRenameForm.value.path, subtitleRenameForm.value.newName)

    subtitleRenameDialogVisible.value = false

    ElMessage.success('字幕文件重命名成功')

    await Promise.all([reloadSubtitleInspector(), refreshLibrary({ silent: true })])

  } catch (error) {

    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    subtitleRenameLoading.value = false

  }

}



function resolveSubtitleEntryPath (row) {

  const rowPath = String(row?.path || '').replace(/\\/g, '/')

  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').replace(/\\/g, '/')

  if (rowPath && subtitleDir && rowPath.startsWith(subtitleDir)) return row.path

  return joinFolderPath(

    subtitleInspectorInfo.value.subtitleDir,

    row.relative_path || row.name || ''

  )

}



async function deleteSubtitleTreeEntry (row) {

  if (subtitleInspectorBusy.value) return

  const path = resolveSubtitleEntryPath(row)

  const inspectorLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value

  try {

    const preview = await libraryApi.browserDelete(inspectorLibraryId, path, false)

    await showSystemConfirm({

      title: '删除确认',

      message: buildDeletePreviewMessage(preview),

      tone: 'danger',

      confirmText: '确定删除',

      cancelText: '取消'

    })

    subtitleInspectorDeleting.value = true

    try {

      await libraryApi.browserDelete(inspectorLibraryId, path, true)

      ElMessage.success('删除成功')

      await Promise.all([

        reloadSubtitleInspector(),

        refreshLibrary({ silent: true }),

        refreshRJSubtitleStatus(false),

        refreshStatsAfterMutation({

          deletedBytes: preview.size || 0,

          deletedFolderCount: preview.folder_count || 0,

          libraryId: inspectorLibraryId

        })

      ])

    } finally {

      subtitleInspectorDeleting.value = false

    }

  } catch (error) {

    if (error === 'cancel' || error?.message === 'cancel') return

    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))

  }

}



function buildDeletePreviewMessage (preview) {

  if (preview?.size_disabled) {

    return `确定删除 ${preview?.name || '该项'} 吗？\n\n此操作不可恢复！`

  }

  return `确定删除 ${preview?.name || '该项'} 吗？\n大小: ${formatFileSize(preview?.size)}\n\n此操作不可恢复！`

}



function buildDeleteItemMessage (preview) {

  const targetLabel = preview?.type === 'folder' ? '文件夹' : '文件'

  if (preview?.size_disabled) {

    return `确定删除此${targetLabel}吗？\n名称: ${preview?.name || '-'}\n\n此操作不可恢复！`

  }

  return `确定删除此${targetLabel}吗？\n名称: ${preview?.name || '-'}\n大小: ${formatFileSize(preview?.size)}\n\n此操作不可恢复！`

}



function buildBatchDeletePreviewMessage (preview, count) {

  const totalCount = preview?.total_count || count

  if (preview?.size_disabled) {

    return `确定删除 ${totalCount} 项吗？\n\n此操作不可恢复！`

  }

  return `确定删除 ${totalCount} 项？总大小: ${formatFileSize(preview?.total_size || 0)}\n\n此操作不可恢复！`

}


function closeLibraryRowContextMenu () {

  tableRef.value?.setCurrentRow?.(null)

  libraryRowContextMenu.value = {
    visible: false,
    x: 0,
    y: 0,
    row: null,
    renderKey: Number(libraryRowContextMenu.value.renderKey || 0)
  }

}


function openLibraryRowContextMenuAtPosition (row, x, y) {

  if (!row) return

  tableRef.value?.setCurrentRow?.(row)

  const menuWidth = 180

  const menuHeight = 360

  const viewportPadding = 10

  const viewportWidth = window.innerWidth || 0

  const viewportHeight = window.innerHeight || 0

  const safeX = Math.min(Math.max(viewportPadding, Number(x || 0)), Math.max(viewportPadding, viewportWidth - menuWidth - viewportPadding))

  const safeY = Math.min(Math.max(viewportPadding, Number(y || 0)), Math.max(viewportPadding, viewportHeight - menuHeight - viewportPadding))

  libraryRowContextMenu.value = {
    visible: true,
    x: safeX,
    y: safeY,
    row,
    renderKey: Number(libraryRowContextMenu.value.renderKey || 0) + 1
  }

}


function handleLibraryRowContextMenu (row, _column, event) {

  if (!row || !event) return

  event.preventDefault()

  event.stopPropagation()

  openLibraryRowContextMenuAtPosition(row, event.clientX, event.clientY)

}


function handleLibraryRowClick (row, _column, event) {

  if (libraryRowContextMenu.value.visible) closeLibraryRowContextMenu()

  const target = event?.target

  if (target instanceof Element && target.closest('input,textarea,select,a,.el-checkbox,.el-tag')) return

  if (row?.is_directory) {

    openFolder(row)

  }

}


function handleLibraryPageClickCloseContextMenu (event) {

  if (!libraryRowContextMenu.value.visible) return

  const target = event?.target

  if (target instanceof Element && target.closest('[data-library-row-menu="1"]')) return

  closeLibraryRowContextMenu()

}


function bindLibraryContextMenuDismiss () {

  document.removeEventListener('click', handleLibraryPageClickCloseContextMenu, true)

  document.addEventListener('click', handleLibraryPageClickCloseContextMenu, true)

}


function unbindLibraryContextMenuDismiss () {

  document.removeEventListener('click', handleLibraryPageClickCloseContextMenu, true)

}


async function handleLibraryRowContextMenuAction (action) {

  const row = libraryRowContextMenu.value.row

  closeLibraryRowContextMenu()

  if (!row) return

  if (action === 'locate') return locateLibrarySearchResult(row)

  if (action === 'open') return openFolder(row)

  if (action === 'open_direct') return openFolderDirect(row)

  if (action === 'copy_name') return copyRowName(row)

  if (action === 'rename') return renameItem(row)

  if (action === 'move') return openMoveDialog([row])

  if (action === 'api_rename') return apiRenameItem(row)

  if (action === 'subtitle') return startSingleRJSubtitle(toRJSubtitleItem(row))

  if (action === 'manage') return openFolderContentsDialog(row)

  if (action === 'compute_size') return computeFolderSize(row)

  if (action === 'delete') return deleteItem(row)

}



async function copyRowName (row) {

  const name = String(row?.name || '').trim()

  if (!name) {

    ElMessage.warning('该行没有可复制的名称')

    return

  }

  try {

    if (navigator?.clipboard?.writeText) {

      await navigator.clipboard.writeText(name)

    } else {

      const textarea = document.createElement('textarea')

      textarea.value = name

      textarea.setAttribute('readonly', '')

      textarea.style.position = 'fixed'

      textarea.style.left = '-9999px'

      document.body.appendChild(textarea)

      textarea.select()

      document.execCommand('copy')

      document.body.removeChild(textarea)

    }

    ElMessage.success('已复制：' + name)

  } catch (_err) {

    ElMessage.error('复制失败：浏览器拒绝访问剪贴板')

  }

}



function openMoveDialog (rows) {

  if (isRemoteCurrentLibrary.value) {

    ElMessage.warning('远程库存暂不支持此操作')

    return

  }

  if (!isWritableCurrentLibrary.value) {

    ElMessage.warning('当前库存只读，无法移动')

    return

  }

  const sourceRows = (Array.isArray(rows) ? rows : []).filter(row => row?.path)

  if (!sourceRows.length) {

    ElMessage.warning('未选中可移动的项')

    return

  }

  moveDialogState.value = {

    visible: true,

    sourceLibraryId: selectedLibraryId.value,

    items: sourceRows.map(row => ({

      path: row.path,

      name: row.name || '',

      is_directory: !!row.is_directory

    })),

    submitting: false

  }

}



function closeMoveDialog () {

  moveDialogState.value = { visible: false, sourceLibraryId: '', items: [], submitting: false }

}



async function handleMoveSubmit (payload) {

  if (!payload?.targetLibraryId || !payload?.targetPath) return

  if (moveDialogState.value.submitting) return

  const items = moveDialogState.value.items.slice()

  if (!items.length) return

  const sourceLibraryId = moveDialogState.value.sourceLibraryId

  const targetLibraryId = payload.targetLibraryId

  const targetPath = payload.targetPath

  moveDialogState.value = { ...moveDialogState.value, submitting: true }

  try {

    const result = await libraryApi.browserMove(

      sourceLibraryId,

      items.map(item => item.path),

      targetLibraryId,

      targetPath

    )

    const successCount = Number(result?.success_count || 0)

    const skippedCount = Number(result?.skipped_count || (Array.isArray(result?.skipped) ? result.skipped.length : 0))

    const failedCount = Number(result?.failed_count || (Array.isArray(result?.failed) ? result.failed.length : 0))

    if (failedCount > 0) {

      const firstError = (Array.isArray(result?.failed) && result.failed[0]?.error) || ''

      ElMessage.warning(`移动完成：成功 ${successCount} 项，跳过 ${skippedCount} 项，失败 ${failedCount} 项${firstError ? '。首个错误：' + firstError : ''}`)

    } else if (skippedCount > 0) {

      ElMessage.success(`移动完成：成功 ${successCount} 项，跳过 ${skippedCount} 项`)

    } else {

      ElMessage.success(`移动完成：成功 ${successCount} 项`)

    }

    closeMoveDialog()

    clearSelection()

    const refreshJobs = [refreshLibrary({ silent: true })]

    refreshJobs.push(refreshStats(false, { silent: true, refreshLibraryId: sourceLibraryId }))

    if (targetLibraryId !== sourceLibraryId) {

      refreshJobs.push(refreshStats(false, { silent: true, refreshLibraryId: targetLibraryId }))

    }

    await Promise.all(refreshJobs)

  } catch (error) {

    ElMessage.error('批量移动失败：' + (error?.response?.data?.detail || error?.message || '未知错误'))

    moveDialogState.value = { ...moveDialogState.value, submitting: false }

  }

}



async function renameItem (row) {

  const form = {

    currentName: row.name,

    newName: row.name,

    path: row.path,

    libraryId: row.library_id || selectedLibraryId.value

  }

  let nextName = ''

  try {

    nextName = await showSystemPrompt({

      title: '重命名',

      message: '请输入新的文件或目录名称。',

      currentLabel: '当前名称',

      currentValue: form.currentName,

      modelValue: form.newName,

      placeholder: '输入新名称',

      confirmText: '确认重命名',

      validator: value => {

        const name = String(value || '').trim()

        if (!name) return '请输入新名称'

        if (name === form.currentName) return '请输入不同的新名称'

        return true

      }

    })

  } catch (_) {

    return

  }

  renameForm.value = { ...form, newName: String(nextName || '').trim() }

  isRenaming.value = true

  try {

    await libraryApi.browserRename(renameForm.value.libraryId || selectedLibraryId.value, renameForm.value.path, renameForm.value.newName)

    ElMessage.success('重命名成功')

    await Promise.all([

      refreshLibrary(),

      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(false, { silent: true, refreshLibraryId: selectedLibraryId.value })

    ])

  } catch (error) {

    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    isRenaming.value = false

  }

}



async function apiRenameItem (row) {

  if (apiRenameBusy.value) return

  apiRenamingId.value = row.id

  try {

    const data = await libraryApi.apiRename(row.path, selectedLibraryId.value)

    ElMessage.success(data.message || 'API 重命名成功')

    await Promise.all([

      refreshLibrary(),

      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(false, { silent: true, refreshLibraryId: selectedLibraryId.value })

    ])

  } catch (error) {

    ElMessage.error('API重命名失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    apiRenamingId.value = null

  }

}



async function computeFolderSize (row) {

  if (!row?.path || !row?.is_directory) return

  computingSizeId.value = row.id

  try {

    const result = await libraryApi.computeFolderSize(row.path)

      const sizeBytes = result?.size ?? 0

      // 更新当前列表中对应行的 size 字段，避免重新加载整页

      const target = files.value.find(f => f.id === row.id)

      if (target) {
        target.size = sizeBytes
        target.size_status = 'ready'
      }

    const gb = (sizeBytes / 1073741824).toFixed(2)

    ElMessage.success(`"${row.name}" 大小：${formatFileSize(sizeBytes)}`)

  } catch (err) {

    ElMessage.error('计算文件夹大小失败：' + (err.response?.data?.detail || err.message || '未知错误'))

  } finally {

    computingSizeId.value = null

  }

}



async function deleteItem (row) {

  try {

    const preview = await libraryApi.browserDelete(selectedLibraryId.value, row.path, false)

    await showSystemConfirm({

      title: '删除确认',

      message: buildDeleteItemMessage(preview),

      tone: 'danger',

      confirmText: '确定删除',

      cancelText: '取消'

    })

    await libraryApi.browserDelete(selectedLibraryId.value, row.path, true)

    ElMessage.success('删除成功')

    await Promise.all([

      refreshLibrary(),

      refreshStatsAfterMutation({

        deletedBytes: preview.size || 0,

        deletedFolderCount: preview.folder_count || 0,

        libraryId: selectedLibraryId.value

      })

    ])

  } catch (error) {

    if (error === 'cancel' || error?.message === 'cancel') return

    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))

  }

}



async function handleBatchComputeSize () {

  const targets = selectedDirectoryRows.value

  if (!targets.length) return

  batchComputingSize.value = true

  let successCount = 0

  let failCount = 0

  for (const row of targets) {

    computingSizeId.value = row.id

    try {

      const result = await libraryApi.computeFolderSize(row.path)

      const sizeBytes = result?.size ?? 0

      const target = files.value.find(f => f.id === row.id)

      if (target) {
        target.size = sizeBytes
        target.size_status = 'ready'
      }

      successCount++

    } catch {

      failCount++

    }

  }

  computingSizeId.value = null

  batchComputingSize.value = false

  if (failCount === 0) {

    ElMessage.success(`批量计算完成：${successCount} 个文件夹大小已更新`)

  } else {

    ElMessage.warning(`批量计算：${successCount} 个成功，${failCount} 个失败`)

  }

}



async function handleBatchDelete () {

  if (!selectedRows.value.length) return

  batchDeleting.value = true

  try {

    const paths = selectedRows.value.map(row => row.path)

    const preview = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, false)

    await showSystemConfirm({

      title: '批量删除确认',

      message: buildBatchDeletePreviewMessage(preview, paths.length),

      tone: 'danger',

      confirmText: '确定删除',

      cancelText: '取消'

    })

    const result = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, true)

    ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 项`)

    clearSelection()

    await Promise.all([

      refreshLibrary(),

      refreshStatsAfterMutation({

        deletedBytes: preview.total_size || 0,

        deletedFolderCount: preview.total_folder_count || 0,

        libraryId: selectedLibraryId.value

      })

    ])

  } catch (error) {

    if (error === 'cancel' || error?.message === 'cancel') return

    ElMessage.error('批量删除失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    batchDeleting.value = false

  }

}



async function handleBatchApiRename () {

  if (!selectedApiRenameRows.value.length || apiRenameBusy.value) return

  const targetRows = selectedApiRenameRows.value

  const skippedCount = selectedRows.value.length - targetRows.length

  try {

    await showSystemConfirm({

      title: '批量 API重命名确认',

      badge: `${targetRows.length} 项`,

      message: skippedCount > 0

        ? `将对已选 ${targetRows.length} 个目录执行批量 API 重命名，并跳过 ${skippedCount} 个非目录项。`

        : `将对已选 ${targetRows.length} 个目录执行批量 API 重命名。`,

      currentLabel: '执行范围',

      currentValue: targetRows.map(row => row.name).slice(0, 3).join(' / ') + (targetRows.length > 3 ? ` 等 ${targetRows.length} 项` : ''),

      confirmText: '确认批量重命名'

    })

  } catch (_) {

    return

  }

  batchRenaming.value = true

  batchApiRenameTargetIds.value = new Set(targetRows.map(row => row.id))

  batchApiRenameRunningIds.value = new Set()

  try {

    const concurrency = Math.min(4, Math.max(1, targetRows.length))

    const results = []

    let cursor = 0

    const runNext = async () => {

      while (cursor < targetRows.length) {

        const currentIndex = cursor

        cursor += 1

        const row = targetRows[currentIndex]

        batchApiRenameRunningIds.value = new Set([...batchApiRenameRunningIds.value, row.id])

        try {

          const data = await libraryApi.apiRename(row.path, selectedLibraryId.value)

          results.push({ path: row.path, success: true, message: data.message || 'API 重命名成功' })

        } catch (error) {

          results.push({ path: row.path, success: false, error: error.response?.data?.detail || error.message })

        } finally {

          const nextRunning = new Set(batchApiRenameRunningIds.value)

          nextRunning.delete(row.id)

          batchApiRenameRunningIds.value = nextRunning

        }

      }

    }

    await Promise.all(Array.from({ length: concurrency }, () => runNext()))

    const successCount = results.filter(item => item.success).length

    const failed = results.filter(item => !item.success)

    clearSelection()

    if (failed.length) {

      const firstError = failed[0]?.error ? `，首个失败：${failed[0].error}` : ''

      ElMessage.warning(`批量 API重命名完成：成功 ${successCount}，失败 ${failed.length}${firstError}`)

    } else {

      ElMessage.success(`批量 API重命名完成：成功 ${successCount} 项`)

    }

    await Promise.all([

      refreshLibrary(),

      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(false, { silent: true, refreshLibraryId: selectedLibraryId.value })

    ])

  } catch (error) {

    ElMessage.error('批量 API重命名失败: ' + (error.response?.data?.detail || error.message))

  } finally {

    batchApiRenameTargetIds.value = new Set()

    batchApiRenameRunningIds.value = new Set()

    apiRenamingId.value = null

    batchRenaming.value = false

  }

}



function isLibraryRowSelectable () {

  return !apiRenameBusy.value

}



async function openFolderContentsDialog (row) {

  if (!row?.is_directory) return

  folderDialogLibraryId.value = row.library_id || selectedLibraryId.value

  folderDialogPath.value = row.path

  folderDialogName.value = row.name

  folderDialogVisible.value = true

}



async function handleFolderDialogMutated ({ deletedBytes = 0, deletedFolderCount = 0 } = {}) {

  await Promise.all([

    refreshLibrary({ silent: true }),

    refreshStatsAfterMutation({

      deletedBytes,

      deletedFolderCount,

      libraryId: folderDialogLibraryId.value || selectedLibraryId.value

    })

  ])

}



function joinFolderPath (basePath, relativePath) {

  if (!relativePath) return basePath

  return `${basePath.replace(/[\\/]+$/, '')}/${relativePath.replace(/^[/\\]+/, '')}`

}



function buildTree (items) {

  const root = []

  const dirMap = new Map()

  const sorted = [...items].sort((a, b) => (a.relative_path || '').localeCompare(b.relative_path || ''))

  for (const item of sorted) {

    const parts = (item.relative_path || item.name).split('/').filter(Boolean)

    let children = root

    let path = ''

    for (let index = 0; index < parts.length - 1; index++) {

      path = path ? `${path}/${parts[index]}` : parts[index]

      const key = `dir:${path}`

      if (!dirMap.has(key)) {

        const node = { id: key, name: parts[index], type: 'dir', relative_path: path, size: 0, modified_time: null, children: [] }

        dirMap.set(key, node)

        children.push(node)

      }

      children = dirMap.get(key).children

    }

    children.push({ ...item, id: `file:${item.path}`, type: 'file' })

  }

  const walk = node => {

    let total = 0

    let latest = null

    for (const child of node.children || []) {

      if (child.type === 'dir') walk(child)

      total += child.size || 0

      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time

    }

    node.size = total

    node.modified_time = latest

  }

  root.forEach(node => { if (node.type === 'dir') walk(node) })

  return root

}



function filterTree (nodes, keyword) {

  const result = []

  for (const node of nodes) {

    const matched = (node.name || '').toLowerCase().includes(keyword) || (node.relative_path || '').toLowerCase().includes(keyword)

    if (node.type === 'file') {

      if (matched) result.push(node)

      continue

    }

    const children = filterTree(node.children || [], keyword)

    if (matched || children.length) result.push({ ...node, children })

  }

  return result

}



function flattenTree (nodes, depth, openIds) {

  const result = []

  for (const node of nodes) {

    result.push({ ...node, depth })

    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) result.push(...flattenTree(node.children, depth + 1, openIds))

  }

  return result

}



async function openFilterDeleteDialog () {

  if (filterDeleteBackgroundState.value.active) {

    filterDeleteDialogVisible.value = true

    return

  }

  if (!currentPath.value || !isWritableCurrentLibrary.value) return

  filterDeleteDialogLibraryId.value = selectedLibraryId.value

  filterDeleteDialogPath.value = currentPath.value

  filterDeleteDialogTargetPaths.value = [...toolbarFilterDeletePaths.value]

  filterDeleteDialogRules.value = await loadConfiguredFilterRules()

  filterDeleteDialogScopeLabel.value = toolbarActionScopeLabel.value

  filterDeleteDialogIsRemote.value = isRemoteCurrentLibrary.value

  filterDeleteDialogVisible.value = true

}



async function openSelectedFilterDeleteDialog () {

  if (filterDeleteBackgroundState.value.active) {

    filterDeleteDialogVisible.value = true

    return

  }

  const targetRows = selectedFilterDeleteRows.value

  if (!targetRows.length || !selectedLibraryId.value) return

  const skippedCount = selectedRows.value.length - targetRows.length

  if (skippedCount > 0) {

    ElMessage.warning(`已跳过 ${skippedCount} 个非目录项，删除过滤预审只支持目录`)

  }

  filterDeleteDialogLibraryId.value = selectedLibraryId.value

  filterDeleteDialogPath.value = currentPath.value

  filterDeleteDialogTargetPaths.value = [...new Set(targetRows.map(resolveDirectoryActionPath).filter(Boolean))]

  filterDeleteDialogRules.value = await loadConfiguredFilterRules()

  filterDeleteDialogScopeLabel.value = `已选目录（${filterDeleteDialogTargetPaths.value.length} 项）`

  filterDeleteDialogIsRemote.value = isRemoteCurrentLibrary.value

  filterDeleteDialogVisible.value = true

}



async function openSubtitleInspectorFilterDeleteDialog () {

  if (filterDeleteBackgroundState.value.active) {

    filterDeleteDialogVisible.value = true

    return

  }

  const libraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value

  const folderPath = String(subtitleInspectorInfo.value.folderPath || '').trim()

  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').trim()

  const targetPath = folderPath || subtitleDir

  if (!libraryId || !targetPath) return

  const library = libraries.value.find(item => item.id === libraryId) || null

  filterDeleteDialogLibraryId.value = libraryId

  filterDeleteDialogPath.value = targetPath

  filterDeleteDialogTargetPaths.value = [targetPath]

  filterDeleteDialogRules.value = subtitleOptions.value.useFilterRules ? sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules || []) : []

  filterDeleteDialogScopeLabel.value = `${getTaskDisplayRJCode(activeSubtitleInspectTask.value) || getFileName(targetPath) || '当前任务'} RJ 目录`

  filterDeleteDialogIsRemote.value = library?.type === 'synology_filestation'

  filterDeleteDialogVisible.value = true

}



async function handleFilterDeleteDeleted ({ deletedBytes = 0, deletedFolderCount = 0 } = {}) {

  await Promise.all([

    refreshLibrary({ silent: true }),

    folderDialogVisible.value && folderDialogRef.value?.reload ? folderDialogRef.value.reload() : Promise.resolve(),

    subtitleDialogVisible.value &&

    String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim() &&

    filterDeleteDialogTargetPaths.value.includes(String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim())

      ? reloadSubtitleInspector()

      : Promise.resolve(),

    refreshStatsAfterMutation({

      deletedBytes,

      deletedFolderCount,

      libraryId: filterDeleteDialogLibraryId.value || selectedLibraryId.value

    })

  ])

}



function handleFilterDeleteDialogStateChange (state = {}) {

  const status = state.status || 'idle'

  const startedAt = Number(state.startedAt || 0)

  const nextHasBackground = Boolean(state.active) || Boolean(state.reviewable)

  const prevHasBackground = Boolean(filterDeleteBackgroundState.value.active) || Boolean(filterDeleteBackgroundState.value.reviewable)

  const nextSessionKey = nextHasBackground

    ? [

        state.mode || 'preview',

        startedAt,

        state.scopeLabel || '',

        filterDeleteDialogLibraryId.value || '',

        filterDeleteDialogPath.value || ''

      ].join('::')

    : ''

  if (nextHasBackground) {

    if (!prevHasBackground || nextSessionKey !== filterDeleteBackgroundSessionKey.value) {

      filterDeleteBackgroundDismissed.value = false

    }

    filterDeleteBackgroundSessionKey.value = nextSessionKey

    // 持久化后台状态到 localStorage，页面刷新后恢复悬浮卡

    try {

      localStorage.setItem(FILTER_DELETE_BG_STORAGE_KEY, JSON.stringify({

        backgroundState: {

          active: Boolean(state.active),

          mode: state.mode || 'preview',

          status,

          scopeLabel: state.scopeLabel || '',

          percentage: Number(state.percentage || 0),

          reviewable: Boolean(state.reviewable),

          selectedCount: Number(state.selectedCount || 0),

          selectedSize: Number(state.selectedSize || 0),

          ruleCount: Number(state.ruleCount || 0),

          deleteDone: Number(state.deleteDone || 0),

          deleteTotal: Number(state.deleteTotal || 0),

          progressMessage: state.progressMessage || ''

        },

        jobId: state.jobId || '',

        dialogConfig: {

          libraryId: filterDeleteDialogLibraryId.value || '',

          path: filterDeleteDialogPath.value || '',

          targetPaths: filterDeleteDialogTargetPaths.value || [],

          rules: filterDeleteDialogRules.value || [],

          scopeLabel: filterDeleteDialogScopeLabel.value || '',

          isRemote: filterDeleteDialogIsRemote.value || false

        },

        savedAt: Date.now()

      }))

    } catch (_) {}

  } else {

    filterDeleteBackgroundSessionKey.value = ''

    // 任务结束（非活跃且非可审阅）时清除持久化状态

    try { localStorage.removeItem(FILTER_DELETE_BG_STORAGE_KEY) } catch (_) {}

  }

  filterDeleteBackgroundState.value = {

    active: Boolean(state.active),

    mode: state.mode || 'preview',

    status,

    statusLabel: (

      status === 'pending' ? '等待中'

        : status === 'running' ? '执行中'

          : status === 'completed' ? '已完成'

            : status === 'canceled' ? '已取消'

              : status === 'error' ? '失败'

                : '空闲'

    ),

    scopeLabel: state.scopeLabel || '',

    progressMessage: state.progressMessage || '',

    currentPath: state.currentPath || '',

    percentage: Number(state.percentage || 0),

    progressStatus: state.progressStatus || '',

    startedAt,

    startedAtText: startedAt ? formatDate(startedAt) : '',

    previewTargetIndex: Number(state.previewTargetIndex || 0),

    previewTargetTotal: Number(state.previewTargetTotal || 0),

    reviewable: Boolean(state.reviewable),

    selectedCount: Number(state.selectedCount || 0),

    selectedSize: Number(state.selectedSize || 0),

    selectedSizeText: formatFileSize(Number(state.selectedSize || 0)),

    scannedEntries: Number(state.scannedEntries || 0),

    discoveredEntries: Number(state.discoveredEntries || 0),

    pendingDirectories: Number(state.pendingDirectories || 0),

    ruleCount: Number(state.ruleCount || 0),

    deleteDone: Number(state.deleteDone || 0),

    deleteTotal: Number(state.deleteTotal || 0),

    deleteFailed: Number(state.deleteFailed || 0),

    canCancelPreview: Boolean(state.canCancelPreview),

    canStopDelete: Boolean(state.canStopDelete)

  }

  if (filterDeleteBackgroundState.value.active) {

    filterDeleteBackgroundNow.value = Date.now()

    if (!filterDeleteBackgroundTimer) {

      filterDeleteBackgroundTimer = window.setInterval(() => {

        filterDeleteBackgroundNow.value = Date.now()

      }, 1000)

    }

  } else if (filterDeleteBackgroundTimer) {

    clearInterval(filterDeleteBackgroundTimer)

    filterDeleteBackgroundTimer = null

  }

}



function resumeFilterDeleteDialog () {

  filterDeleteBackgroundDismissed.value = false

  filterDeleteDialogVisible.value = true

}



function handleFilterDeleteDialogDismissBackground () {

  filterDeleteBackgroundDismissed.value = true

}



function dismissFilterDeleteBackgroundCard () {

  filterDeleteBackgroundDismissed.value = true

}



async function cancelBackgroundFilterDeletePreview () {

  try {

    await filterDeleteDialogRef.value?.cancelPreviewTask?.()

  } catch (_) {}

}



function stopBackgroundFilterDelete () {

  filterDeleteDialogRef.value?.requestStopDeletion?.()

}



function fileIcon (name = '') {

  const lower = name.toLowerCase()

  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset

  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture

  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay

  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets

  return Document

}



function formatFileSize (bytes) {

  if (bytes === null || bytes === undefined) return '-'

  if (!bytes) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']

  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)

  return `${(bytes / (1024 ** index)).toFixed(2)} ${units[index]}`

}



function libraryRowKey (row) {

  return [

    selectedLibraryId.value || 'default',

    row?.path || row?.id || row?.name || 'unknown'

  ].join('::')

}



function libraryRowClassName ({ row }) {

  const classes = []

  if (locatedLibraryPath.value && row?.path === locatedLibraryPath.value) classes.push('library-row-located')

  if (isLibraryRowOperating(row)) classes.push('library-row-operating')

  if (libraryRowContextMenu.value.visible && libraryRowContextMenu.value.row?.path && row?.path === libraryRowContextMenu.value.row.path) classes.push('library-row-context-active')

  return classes.join(' ')

}

function isLibraryRowOperating (row) {

  if (!row) return false

  return apiRenamingId.value === row.id ||
    computingSizeId.value === row.id ||
    isBatchApiRenameRunning(row)

}



function formatRowSize (row) {

  if (row?.is_directory && isAtComputeSizeRoot.value && row?.size_status !== 'ready') return '-'

  if (row?.size_status === 'pending' && (row.size === null || row.size === undefined)) return '统计中'

  if (row?.size_status === 'stale' && row.size !== null && row.size !== undefined) return `${formatFileSize(row.size)} *`

  return formatFileSize(row?.size)

}



function formatDate (value) {

  if (!value) return '-'

  const date = new Date(value)

  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })

}



function formatGB (value) {

  if (value === null || value === undefined) return '统计中'

  const sizeInGb = Number(value)

  if (sizeInGb > 1000) return `${(sizeInGb / 1000).toFixed(2)} TB`

  return `${sizeInGb.toFixed(2)} GB`

}



function statsSizeText (stats) {

  if (!stats || stats.status === 'pending') return '统计更新中'

  if (stats.status === 'unsupported') return '暂不支持远程容量统计'

  return formatGB(stats.total_size_gb)

}



function statsStatusText (status) {

  if (status === 'ready') return '统计已就绪'

  if (status === 'pending') return '后台正在更新'

  if (status === 'unsupported') return '当前仅显示健康状态'

  return '等待统计'

}



function statsSizeCardText (stats) {

  if (!stats) return '\u7b49\u5f85\u7edf\u8ba1'

  if (stats.status === 'pending') return '\u7edf\u8ba1\u66f4\u65b0\u4e2d'

  if (stats.status === 'idle') return '\u672a\u624b\u52a8\u7edf\u8ba1'

  if (stats.status === 'canceled') return '\u5df2\u53d6\u6d88\uff0c\u4fdd\u7559\u5f53\u524d\u8fdb\u5ea6'

  if (stats.status === 'error') return '\u7edf\u8ba1\u4e2d\u65ad\uff0c\u4fdd\u7559\u5df2\u5b8c\u6210\u6570\u636e'

  if (stats.status === 'unsupported') return '\u6682\u4e0d\u652f\u6301\u5f53\u524d\u7edf\u8ba1'

  return formatGB(stats.total_size_gb)

}



function statsStatusCardText (stats) {

  const status = stats?.status

  if (status === 'ready') {

    const ts = stats?.last_completed_at || stats?.updated_at

    return ts ? `\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u7edf\u8ba1\u5df2\u5b8c\u6210'

  }

  if (status === 'pending') {

    const ts = stats?.last_completed_at

    return ts ? `\u540e\u53f0\u66f4\u65b0\u4e2d\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u540e\u53f0\u6b63\u5728\u66f4\u65b0'

  }

  if (status === 'canceled') return '\u5df2\u624b\u52a8\u53d6\u6d88\uff0c\u4ecd\u4fdd\u7559\u5df2\u7edf\u8ba1\u8fdb\u5ea6'

  if (status === 'error') return stats?.last_error || '\u7edf\u8ba1\u4e2d\u9014\u51fa\u73b0\u5f02\u5e38\uff0c\u8bf7\u67e5\u770b\u8fdc\u7a0b\u7edf\u8ba1\u65e5\u5fd7'

  if (status === 'idle') return '\u8fdc\u7a0b\u5e93\u9ed8\u8ba4\u4e0d\u81ea\u52a8\u5168\u91cf\u7edf\u8ba1\uff0c\u8bf7\u624b\u52a8\u70b9\u5237\u65b0\u7edf\u8ba1'

  if (status === 'unsupported') return '\u5f53\u524d\u4ec5\u663e\u793a\u5065\u5eb7\u72b6\u6001'

  return '\u7b49\u5f85\u7edf\u8ba1'

}



function healthStatusLabel (status) {

  if (status === 'healthy') return '\u5065\u5eb7'

  if (status === 'warning') return '\u9884\u8b66'

  return '\u5f02\u5e38'

}



function healthDetailText (health) {

  if (!health) return ''

  if (health.errors?.length) return health.errors.map(item => decodePossibleMojibake(item)).join('\uff1b')

  if (health.warnings?.length) return health.warnings.map(item => decodePossibleMojibake(item)).join('\uff1b')

  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `\u5269\u4f59\u7a7a\u95f4 ${health.free_space_gb} GB`

  return '\u8bfb\u5199\u6743\u9650\u6b63\u5e38'

}



function healthTagType (status) {

  if (status === 'healthy') return 'success'

  if (status === 'warning') return 'warning'

  return 'danger'

}



function healthText (status) {

  if (status === 'healthy') return '健康'

  if (status === 'warning') return '预警'

  return '异常'

}



function healthDetail (health) {

  if (!health) return ''

  if (health.errors?.length) return health.errors.map(item => decodePossibleMojibake(item)).join('；')

  if (health.warnings?.length) return health.warnings.map(item => decodePossibleMojibake(item)).join('；')

  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `剩余空间 ${health.free_space_gb} GB`

  return '读写权限正常'

}

function statsSizeLabel (stats) {

  if (!stats || stats.status === 'pending') return '统计更新中'

  if (stats.status === 'idle') return '未统计'

  if (stats.status === 'unsupported') return '暂不支持远程容量统计'

  return formatGB(stats.total_size_gb)

}



function statsStatusLabel (stats) {

  const status = stats?.status

  if (status === 'ready') {

    const ts = stats?.last_completed_at || stats?.updated_at

    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'

  }

  if (status === 'pending') {

    const ts = stats?.last_completed_at

    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'

  }

  if (status === 'idle') return '未手动统计，沿用已保存结果'

  if (status === 'unsupported') return '当前仅显示健康状态'

  return '等待统计'

}



function statsSizeTextDisplay (stats) {

  if (!stats || stats.status === 'pending') return '统计更新中'

  if (stats.status === 'idle') return '未统计'

  if (stats.status === 'unsupported') return '暂不支持远程容量统计'

  return formatGB(stats.total_size_gb)

}



function statsStatusTextDisplay (stats) {

  const status = stats?.status

  if (status === 'ready') {

    const ts = stats?.last_completed_at || stats?.updated_at

    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'

  }

  if (status === 'pending') {

    const ts = stats?.last_completed_at

    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'

  }

  if (status === 'idle') return '未手动统计，沿用已保存结果'

  if (status === 'unsupported') return '当前仅显示健康状态'

  return '等待统计'

}

</script>



<style scoped>

/* ============================================================

 * Library refactor (Tailwind + lucide, modern clean)

 * ============================================================ */



/* 页面头部 */

.lib-page-header {

  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 14px;

  margin-bottom: 14px;

}

.lib-page-head-left { display: flex; align-items: center; gap: 12px; }

.lib-page-head-right { display: flex; flex-wrap: wrap; gap: 6px; }

.lib-page-icon {

  display: grid;

  place-items: center;

  width: 44px;

  height: 44px;

  border-radius: 14px;

  background: linear-gradient(135deg, rgba(219, 234, 254, 0.9), rgba(196, 181, 253, 0.7));

  color: #1d4ed8;

  box-shadow: 0 6px 16px -6px rgba(59, 130, 246, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.6) inset;

}

.lib-page-title {

  margin: 0;

  font-size: 22px;

  font-weight: 700;

  letter-spacing: -0.4px;

  color: #0f172a;

  line-height: 1.2;

}

.lib-page-subtitle {

  margin: 2px 0 0;

  font-size: 12.5px;

  color: #64748b;

}



/* 汇总信息条（替代原 3 张大卡片） */

.lib-info-strip {

  display: grid;

  grid-template-columns: minmax(0, 1.2fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);

  align-items: stretch;

  gap: 0;

  margin-bottom: 18px;

  padding: 14px 18px;

  border-radius: 16px;

  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 250, 252, 0.92));

  border: 1px solid rgba(226, 232, 240, 0.8);

  box-shadow: 0 6px 20px -12px rgba(15, 23, 42, 0.1);

}

.lib-info-item {

  display: flex;

  align-items: flex-start;

  gap: 10px;

  min-width: 0;

  padding: 0 14px;

}

.lib-info-item:first-child { padding-left: 0; }

.lib-info-item:last-child { padding-right: 0; }

.lib-info-icon { flex-shrink: 0; margin-top: 3px; }

.lib-info-body { min-width: 0; flex: 1 1 auto; }

.lib-info-label {

  font-size: 10.5px;

  font-weight: 600;

  letter-spacing: 0.08em;

  text-transform: uppercase;

  color: #94a3b8;

  margin-bottom: 3px;

}

.lib-info-value {

  font-size: 14.5px;

  color: #0f172a;

  line-height: 1.3;

  display: flex;

  align-items: baseline;

  gap: 6px;

  flex-wrap: wrap;

}

.lib-info-value b { font-weight: 700; font-size: 15.5px; letter-spacing: -0.2px; }

.lib-info-meta { color: #94a3b8; font-size: 12px; }

.lib-info-sub {

  margin-top: 3px;

  font-size: 11.5px;

  color: #94a3b8;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}

.lib-info-progress { margin-top: 6px; }

.lib-info-divider {

  width: 1px;

  background: linear-gradient(180deg, transparent, rgba(226, 232, 240, 0.9), transparent);

  align-self: stretch;

}



@media (max-width: 980px) {

  .lib-info-strip { grid-template-columns: 1fr; gap: 12px; padding: 12px 14px; }

  .lib-info-divider { display: none; }

  .lib-info-item { padding: 0; }

}



/* 小 chip */

/* lib-chip：库存类型 / 健康状态等小标签
   渐变底 + inset 1px 顶部高光 + 同色微 glow，告别"纯色塑料感" */

.lib-chip {

  display: inline-flex;

  align-items: center;

  gap: 4px;

  height: 22px;

  padding: 0 9px;

  border-radius: 999px;

  font-size: 11px;

  font-weight: 500;

  letter-spacing: 0.01em;

  border: 1px solid transparent;

  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);

}

.lib-chip:hover { transform: translateY(-1px) scale(1.04); }

.lib-chip-success {

  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);

  color: #047857;

  border-color: rgba(110, 231, 183, 0.55);

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.7),

    0 1px 2px rgba(16, 185, 129, 0.1);

}

.lib-chip-success:hover {

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.85),

    0 4px 10px -2px rgba(16, 185, 129, 0.28);

}

.lib-chip-warning {

  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);

  color: #b45309;

  border-color: rgba(251, 191, 36, 0.5);

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.7),

    0 1px 2px rgba(245, 158, 11, 0.1);

}

.lib-chip-warning:hover {

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.85),

    0 4px 10px -2px rgba(245, 158, 11, 0.3);

}

.lib-chip-danger {

  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);

  color: #b91c1c;

  border-color: rgba(248, 113, 113, 0.5);

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.65),

    0 1px 2px rgba(239, 68, 68, 0.12);

}

.lib-chip-danger:hover {

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.8),

    0 4px 10px -2px rgba(239, 68, 68, 0.32);

}

.lib-chip-info {

  background: linear-gradient(180deg, #eef2ff 0%, #e0e7ff 100%);

  color: #4338ca;

  border-color: rgba(165, 180, 252, 0.55);

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.7),

    0 1px 2px rgba(99, 102, 241, 0.12);

}

.lib-chip-info:hover {

  box-shadow:

    inset 0 1px 0 rgba(255, 255, 255, 0.85),

    0 4px 10px -2px rgba(99, 102, 241, 0.3);

}



/* 行内操作按钮 */

.lib-row-action-btn {

  position: relative;

  z-index: 1;

  display: inline-flex;

  align-items: center;

  gap: 5px;

  padding: 5px 10px;

  border-radius: 8px;

  border: 1px solid rgba(203, 213, 225, 0.7);

  background: rgba(248, 250, 252, 0.85);

  color: #334155;

  font-size: 12.5px;

  font-weight: 500;

  cursor: pointer;

  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);

}

.lib-row-action-btn:hover {

  transform: scale(1.02);

  background: linear-gradient(135deg, #eff6ff 0%, #fff 100%);

  border-color: rgba(59, 130, 246, 0.55);

  color: #1d4ed8;

  box-shadow: 0 8px 18px -10px rgba(59, 130, 246, 0.4), 0 0 0 3px rgba(59, 130, 246, 0.08);

}

.lib-row-action-btn:hover svg { transform: scale(1.1); }

.lib-row-action-btn svg { transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }

.lib-row-action-btn:active { transform: scale(0.97); }

/* 让 fixed 列的单元格不裁剪 hover shadow/ring */

:deep(.main-card .el-table .el-table__fixed-right td.el-table__cell),

:deep(.main-card .el-table td.el-table__cell.is-last-column),

:deep(.main-card .el-table .el-table__fixed-right .cell),

:deep(.main-card .el-table td.el-table__cell.is-last-column .cell) { overflow: visible !important; }



:deep(.lib-row-dropdown .el-dropdown-menu) {

  min-width: 180px;

}

:deep(.lib-row-dropdown .el-dropdown-menu__item.lib-row-dropdown-danger) {

  color: #be123c !important;

}

:deep(.lib-row-dropdown .el-dropdown-menu__item.lib-row-dropdown-danger:not(.is-disabled):hover) {

  background: rgba(254, 226, 226, 0.6) !important;

  color: #9f1239 !important;

}

:deep(.lib-row-dropdown .el-dropdown-menu__item.is-api-batch-target) {

  background: rgba(254, 243, 199, 0.4) !important;

}

.lib-row-dropdown-loading {

  margin-left: auto;

  font-size: 11px;

  color: #f59e0b;

}



/* 表格美化 */

:deep(.main-card .el-table) {

  --el-table-header-bg-color: #f8fafc;

  --el-table-row-hover-bg-color: #f8fafc;

  --el-table-border-color: rgba(226, 232, 240, 0.7);

  border-radius: 14px;

  overflow: visible;

  border: 1px solid rgba(226, 232, 240, 0.6);

}

:deep(.main-card .el-table__inner-wrapper::before) { display: none; }

:deep(.main-card .el-table__inner-wrapper) {

  border-radius: 14px;

  overflow: visible;

}

:deep(.main-card .el-table .el-table__body-wrapper),

:deep(.main-card .el-table .el-table__fixed),

:deep(.main-card .el-table .el-table__fixed-right),

:deep(.main-card .el-table .el-table__fixed-body-wrapper) {

  overflow: visible !important;

}

:deep(.main-card .el-table th.el-table__cell) {

  font-size: 11px;

  font-weight: 600;

  letter-spacing: 0.05em;

  text-transform: uppercase;

  color: #64748b;

  background: #f8fafc !important;

  border-bottom: 1px solid rgba(226, 232, 240, 0.8);

}

:deep(.main-card .el-table td.el-table__cell) {

  border-bottom-color: rgba(241, 245, 249, 0.9);

}

:deep(.main-card .el-table .el-table__row) {

  transition: background-color 0.2s ease;

}

:deep(.main-card .el-table .el-table__row:hover > td) {

  background: #f8fafc !important;

}



/* 主卡片壳 */

:deep(.main-card) {

  border-radius: 20px;

  border: 1px solid rgba(226, 232, 240, 0.7);

  box-shadow: 0 10px 30px -14px rgba(15, 23, 42, 0.12);

  overflow: hidden;

}

:deep(.main-card .el-card__header) {

  padding: 14px 18px;

  border-bottom: 1px solid rgba(226, 232, 240, 0.7);

  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 250, 252, 0.95));

}

:deep(.main-card .el-card__body) {

  padding: 16px 18px 20px;

}



@media (max-width: 1100px) {

  .lib-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

}

@media (max-width: 680px) {

  .lib-summary-grid { grid-template-columns: 1fr; }

}



.lib-card-header {

  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 16px;

  flex-wrap: wrap;

}



.lib-card-title {

  flex: 0 0 auto;

  font-size: 15px;

  font-weight: 600;

  letter-spacing: -0.2px;

  color: #1e293b;

}



.lib-toolbar {

  flex: 1 1 auto;

  display: flex;

  align-items: center;

  justify-content: flex-end;

  flex-wrap: wrap;

  gap: 21px;

  min-width: 0;

}



.lib-library-select :deep(.el-select__wrapper),

.lib-toolbar :deep(.el-select__wrapper) {

  border-radius: 10px;

  box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.7);

  background: rgba(248, 250, 252, 0.7);

  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);

}

.lib-toolbar :deep(.el-select__wrapper:hover) {

  background: #fff;

  box-shadow: inset 0 0 0 1px #94a3b8;

}

.lib-toolbar :deep(.el-select__wrapper.is-focused) {

  box-shadow: inset 0 0 0 2px rgba(59, 130, 246, 0.5) !important;

  background: #fff;

}



/* 搜索框 */

.lib-search {

  position: relative;

  flex: 1 1 240px;

  min-width: 220px;

  max-width: 360px;

}

.lib-search-icon {

  position: absolute;

  left: 11px;

  top: 50%;

  transform: translateY(-50%);

  color: #94a3b8;

  pointer-events: none;

  transition: color 0.25s ease;

}

.lib-search:focus-within .lib-search-icon { color: #3b82f6; }

.lib-search-input {

  width: 100%;

  height: 34px;

  padding: 0 32px 0 34px;

  border-radius: 10px;

  border: 1px solid rgba(203, 213, 225, 0.8);

  background: rgba(248, 250, 252, 0.7);

  font-size: 13px;

  color: #0f172a;

  outline: none;

  transition: all 0.25s ease;

}

.lib-search-input::placeholder { color: #94a3b8; }

.lib-search-input:hover {

  border-color: #94a3b8;

  background: #fff;

}

.lib-search-input:focus {

  border-color: #3b82f6;

  background: #fff;

  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);

}

.lib-search-clear {

  position: absolute;

  right: 6px;

  top: 50%;

  transform: translateY(-50%);

  width: 22px;

  height: 22px;

  display: grid;

  place-items: center;

  border: 0;

  background: transparent;

  color: #94a3b8;

  border-radius: 6px;

  cursor: pointer;

  transition: all 0.2s ease;

}

.lib-search-clear:hover {

  color: #0f172a;

  background: rgba(148, 163, 184, 0.15);

}



/* 按钮基础 */

.lib-btn {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  gap: 6px;

  min-height: 34px;

  padding: 0 13px;

  border-radius: 10px;

  font-size: 13px;

  font-weight: 500;

  letter-spacing: -0.1px;

  white-space: nowrap;

  border: 1px solid transparent;

  background: transparent;

  cursor: pointer;

  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);

}

.lib-btn:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); }

.lib-btn:active:not(:disabled) { transform: scale(0.96); }

.lib-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.lib-btn-compact { min-height: 30px; padding: 0 10px; font-size: 12.5px; }



.lib-btn-primary {

  color: #fff;

  background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);

  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);

}

.lib-btn-primary:hover:not(:disabled) { box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35); }



.lib-btn-ghost {

  color: #334155;

  background: rgba(248, 250, 252, 0.85);

  border-color: rgba(203, 213, 225, 0.7);

}

.lib-btn-ghost:hover:not(:disabled) {

  background: #fff;

  color: #0f172a;

  border-color: rgba(148, 163, 184, 0.8);

  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);

}



.lib-btn-success {

  color: #047857;

  background: rgba(236, 253, 245, 0.85);

  border-color: rgba(110, 231, 183, 0.6);

}

.lib-btn-success:hover:not(:disabled) {

  background: #fff;

  color: #065f46;

  border-color: rgba(16, 185, 129, 0.6);

  box-shadow: 0 6px 14px rgba(16, 185, 129, 0.18);

}



.lib-btn-danger {

  color: #be123c;

  background: rgba(255, 241, 242, 0.85);

  border-color: rgba(251, 113, 133, 0.45);

}

.lib-btn-danger:hover:not(:disabled) {

  background: #fff;

  color: #9f1239;

  border-color: rgba(244, 63, 94, 0.65);

  box-shadow: 0 6px 14px rgba(220, 38, 38, 0.15);

}



.lib-badge {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  min-width: 20px;

  height: 18px;

  padding: 0 5px;

  border-radius: 999px;

  background: rgba(15, 23, 42, 0.08);

  color: #0f172a;

  font-size: 11px;

  font-weight: 600;

  letter-spacing: 0;

  margin-left: 2px;

}



/* 图标上色按钮（白底 + 按类型染色的图标） */

.lib-btn-icon-tinted {

  color: #334155;

  background: linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));

  border-color: rgba(226, 232, 240, 0.78);

  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.95) inset, 0 5px 14px rgba(15, 23, 42, 0.045);

}

.lib-btn-icon-tinted:hover:not(:disabled) {

  background: linear-gradient(135deg, rgba(239, 246, 255, 0.98), rgba(255, 255, 255, 0.96));

  color: #1e293b;

  border-color: rgba(191, 219, 254, 0.92);

  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.12), 0 1px 0 rgba(255, 255, 255, 0.96) inset;

}

.lib-btn-icon-tinted svg { transition: transform 0.25s ease, color 0.25s ease; }

.lib-btn-icon-tinted:hover:not(:disabled) svg { transform: scale(1.08); }



/* 每个类型不同的图标颜色 */

.lib-btn-icon-tinted svg { color: #4f46e5; }

.lib-btn-icon-tinted.lib-icon-refresh svg { color: #2563eb; }
.lib-btn-icon-tinted.lib-icon-stats svg { color: #4f46e5; }
.lib-btn-icon-tinted.lib-icon-select svg { color: #0f766e; }
.lib-btn-icon-tinted.lib-icon-subtitle svg,
.lib-btn-icon-tinted.lib-icon-subtitle-batch svg { color: #059669; }
.lib-btn-icon-tinted.lib-icon-filter-delete svg { color: #d97706; }
.lib-btn-icon-tinted.lib-icon-task-panel svg { color: #7c3aed; }
.lib-btn-icon-tinted.lib-icon-upload svg { color: #0284c7; }
.lib-btn-icon-tinted.lib-icon-compute-size svg { color: #0ea5e9; }
.lib-btn-icon-tinted.lib-icon-batch-delete svg { color: #e11d48; }
.lib-btn-icon-tinted.lib-icon-batch-move svg { color: #0ea5e9; }
.lib-btn-icon-tinted.lib-icon-api-rename svg { color: #7c3aed; }

.lib-batch-action-btn {

  position: relative;

  overflow: hidden;

}

.lib-batch-action-btn.is-executing {

  color: #312e81;

  border-color: rgba(165, 180, 252, 0.9);

  background:
    linear-gradient(135deg, rgba(238, 242, 255, 0.98), rgba(255, 255, 255, 0.94)),
    linear-gradient(90deg, rgba(99, 102, 241, 0), rgba(99, 102, 241, 0.2), rgba(99, 102, 241, 0));

  box-shadow: 0 10px 26px rgba(79, 70, 229, 0.16), 0 1px 0 rgba(255, 255, 255, 0.95) inset;

}

.lib-batch-action-btn.is-executing::before {

  content: "";

  position: absolute;

  inset: 0;

  transform: translateX(-120%);

  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.72), transparent);

  animation: library-row-operating-sweep 1.35s ease-in-out infinite;

  pointer-events: none;

}

.lib-batch-action-btn.is-executing svg {

  color: #4338ca;

  animation: library-row-operating-pulse 0.95s ease-in-out infinite;

}

.lib-batch-action-btn.is-executing .lib-badge {

  color: #3730a3;

  background: rgba(199, 210, 254, 0.72);

}



/* 下拉菜单 */

:deep(.lib-dropdown-popper .el-dropdown-menu) {

  border-radius: 14px !important;

  padding: 7px !important;

  border: 1px solid rgba(226, 232, 240, 0.9) !important;

  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98)) !important;

  box-shadow: 0 18px 40px -14px rgba(15, 23, 42, 0.24), 0 10px 24px -16px rgba(59, 130, 246, 0.18) !important;

  transform-origin: top right !important;

  animation: lib-dropdown-enter 0.22s cubic-bezier(0.21, 1.02, 0.35, 1) !important;

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item) {

  min-height: 34px !important;

  border-radius: 10px !important;

  font-size: 13px !important;

  font-weight: 500 !important;

  padding: 7px 10px !important;

  gap: 8px !important;

  color: #475569 !important;

  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease !important;

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item:not(.is-disabled):hover) {

  transform: translateX(2px);

  background: linear-gradient(135deg, rgba(239, 246, 255, 0.95), rgba(248, 250, 252, 0.98)) !important;

  color: #1d4ed8 !important;

  box-shadow: inset 0 0 0 1px rgba(191, 219, 254, 0.75);

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item.is-divided) {

  margin-top: 8px !important;

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item.is-divided::before) {

  left: 8px !important;

  right: 8px !important;

  top: -5px !important;

  background: linear-gradient(90deg, rgba(226, 232, 240, 0), rgba(226, 232, 240, 0.95), rgba(226, 232, 240, 0)) !important;

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item.is-disabled) {

  color: #94a3b8 !important;

}

.lib-dropdown-icon {

  margin-right: 4px;

  color: #64748b;

  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.2s ease;

}

:deep(.lib-dropdown-popper .el-dropdown-menu__item:not(.is-disabled):hover .lib-dropdown-icon) {

  transform: scale(1.08) rotate(-4deg);

}

.lib-row-dropdown-item-pin .lib-dropdown-icon { color: #2563eb; }

.lib-row-dropdown-item-open .lib-dropdown-icon { color: #0f766e; }

.lib-row-dropdown-item-link .lib-dropdown-icon { color: #4f46e5; }

.lib-row-dropdown-item-rename .lib-dropdown-icon { color: #6366f1; }

.lib-row-dropdown-item-api-rename .lib-dropdown-icon { color: #f59e0b; }

.lib-row-dropdown-item-subtitle .lib-dropdown-icon { color: #059669; }

.lib-row-dropdown-item-manage .lib-dropdown-icon { color: #0f766e; }

:deep(.lib-row-dropdown-danger .lib-dropdown-icon) { color: #e11d48; }



@keyframes lib-dropdown-enter {

  from {

    opacity: 0;

    transform: translateY(-6px) scale(0.96);

  }

  to {

    opacity: 1;

    transform: translateY(0) scale(1);

  }

}



/* 路径工具栏 */

.lib-path-toolbar {

  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 14px;

  flex-wrap: wrap;

  padding: 10px 14px;

  margin-bottom: 14px;

  border-radius: 14px;

  background: linear-gradient(180deg, rgba(248, 250, 252, 0.9), rgba(241, 245, 249, 0.6));

  border: 1px solid rgba(226, 232, 240, 0.8);

  backdrop-filter: blur(8px);

  -webkit-backdrop-filter: blur(8px);

}

.lib-path-left {

  display: flex;

  align-items: center;

  gap: 10px;

  min-width: 0;

  flex: 1 1 auto;

}

.lib-path-right {

  display: flex;

  align-items: center;

  gap: 8px;

  flex-wrap: wrap;

}

.lib-path-label {

  font-size: 11px;

  font-weight: 600;

  letter-spacing: 0.04em;

  text-transform: uppercase;

  color: #64748b;

  flex-shrink: 0;

}

.lib-path-code {

  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  font-size: 12px;

  color: #1e293b;

  background: #fff;

  padding: 4px 10px;

  border-radius: 8px;

  border: 1px solid rgba(226, 232, 240, 0.8);

  min-width: 0;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

  max-width: 520px;

}



/* scope 切换 */

.lib-scope-switch {

  display: inline-flex;

  align-items: center;

  padding: 3px;

  background: rgba(241, 245, 249, 0.85);

  border-radius: 10px;

  border: 1px solid rgba(226, 232, 240, 0.8);

}

.lib-scope-option {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  padding: 4px 12px;

  border-radius: 7px;

  font-size: 12.5px;

  font-weight: 500;

  color: #64748b;

  background: transparent;

  border: 0;

  cursor: pointer;

  transition: all 0.25s ease;

}

.lib-scope-option:hover:not(.is-active) { color: #0f172a; }

.lib-scope-option.is-active {

  background: #fff;

  color: #1d4ed8;

  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06), 0 0 0 1px rgba(59, 130, 246, 0.2);

  font-weight: 600;

}



/* 批量选择栏（顶部浮动）— 简洁中性 */

.lib-batch-bar {

  position: sticky;

  top: 0;

  z-index: 20;

  display: flex;

  align-items: center;

  justify-content: space-between;

  flex-wrap: wrap;

  gap: 12px;

  padding: 10px 14px;

  margin-bottom: 14px;

  border-radius: 14px;

  background: rgba(255, 255, 255, 0.96);

  border: 1px solid rgba(226, 232, 240, 0.85);

  box-shadow: 0 8px 20px -12px rgba(15, 23, 42, 0.12);

  backdrop-filter: blur(10px);

  -webkit-backdrop-filter: blur(10px);

}

.lib-batch-info { display: flex; align-items: center; gap: 10px; }

.lib-batch-count-pill {

  display: inline-flex;

  align-items: center;

  gap: 6px;

  padding: 5px 12px;

  border-radius: 999px;

  background: rgba(241, 245, 249, 0.9);

  border: 1px solid rgba(203, 213, 225, 0.8);

  color: #334155;

  font-size: 13px;

  font-weight: 500;

}

.lib-batch-count-pill b { font-weight: 700; font-size: 14px; color: #0f172a; }

.lib-batch-clear {

  display: inline-flex;

  align-items: center;

  gap: 4px;

  padding: 4px 10px;

  border-radius: 8px;

  background: transparent;

  border: 1px solid transparent;

  color: #475569;

  font-size: 12.5px;

  cursor: pointer;

  transition: all 0.25s ease;

}

.lib-batch-clear:hover {

  background: rgba(255, 255, 255, 0.6);

  border-color: rgba(203, 213, 225, 0.8);

  color: #0f172a;

}

.lib-batch-actions {

  display: flex;

  align-items: center;

  gap: 8px;

  flex-wrap: wrap;

}



/* 批量栏滑入/滑出 */

.lib-batch-slide-enter-active,

.lib-batch-slide-leave-active {

  transition: opacity 0.25s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);

}

.lib-batch-slide-enter-from,

.lib-batch-slide-leave-to {

  opacity: 0;

  transform: translateY(-8px);

}



@media (max-width: 860px) {

  .lib-search { max-width: none; }

  .lib-path-toolbar,

  .lib-batch-bar { flex-direction: column; align-items: stretch; }

  .lib-path-right,

  .lib-batch-actions,

  .lib-batch-info { flex-wrap: wrap; }

  .lib-path-code { max-width: none; }

}



.library-page-loading-shell {

  position: relative;

  min-height: 100%;

}



:deep(.library-page-loading-mask) {

  inset: 0;

  border-radius: 0;

  background: rgba(250, 251, 255, 0.84);

  backdrop-filter: blur(3px);

  -webkit-backdrop-filter: blur(3px);

  z-index: 50;

}



.library {

  max-width: 1480px;

  margin: 0 auto;

  padding: 16px;

  color: #1d1d1f;

  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;

}



.page-title {

  margin: 0 0 18px;

  font-size: 29px;

  font-weight: 600;

  line-height: 1.12;

  letter-spacing: -0.2px;

  color: #1d1d1f;

}



.summary-grid {

  display: grid;

  grid-template-columns: repeat(3, minmax(0, 1fr));

  gap: 14px;

  margin-bottom: 14px;

}



.summary-card {

  min-height: 160px;

  border: none;

  border-radius: 22px;

  background: rgba(255, 255, 255, 0.94);

  box-shadow: 0 12px 30px rgba(0, 0, 0, .05);

}



.summary-card :deep(.el-card__header) {

  padding: 18px 18px 0;

  border-bottom: none;

  font-size: 12px;

  font-weight: 600;

  color: rgba(29, 29, 31, .52);

}



.summary-card :deep(.el-card__body) {

  padding: 14px 18px 18px;

}



.summary-value {

  font-size: 22px;

  font-weight: 600;

  line-height: 1.18;

  letter-spacing: -0.16px;

  color: #1d1d1f;

}



.summary-meta,

.summary-caption {

  margin-top: 8px;

  font-size: 13px;

}



.summary-meta {

  color: rgba(29, 29, 31, .66);

}



.summary-caption {

  color: rgba(29, 29, 31, .5);

  line-height: 1.58;

}



.summary-progress { margin-top: 10px; }



.path-text { word-break: break-all; }

.summary-tags { display: flex; gap: 8px; margin-top: 12px; }

.main-card {

  border: none;

  border-radius: 18px;

  background: rgba(255, 255, 255, 0.94);

  box-shadow: 0 12px 30px rgba(0, 0, 0, .05) !important;

}



.main-card :deep(.el-card__header) {

  padding: 18px 18px 0;

  border-bottom: none;

}



.main-card :deep(.el-card__body) {

  padding: 12px 18px 18px;

}



.card-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }

.header-title {

  font-size: 16px;

  font-weight: 600;

  line-height: 1.15;

  letter-spacing: -0.08px;

  color: #1d1d1f;

  white-space: nowrap;

}

.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }

.toolbar-action-btn,

.toolbar-tight-btn { width: 88px; }



:deep(.el-input__wrapper),

:deep(.el-select__wrapper) {

  min-height: 34px;

  border-radius: 12px;

  background: #f5f5f7;

  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, .06);

}



:deep(.el-input__inner),

:deep(.el-select__selected-item),

:deep(.el-select__placeholder) {

  font-size: 12px;

  color: #1d1d1f;

}



:deep(.toolbar-action-btn.el-button),

:deep(.toolbar-tight-btn.el-button) {

  min-height: 34px;

  padding: 0 !important;

  border-radius: 999px;

  border-color: rgba(29, 29, 31, .08);

  background: #f5f5f7;

  color: #1d1d1f;

  box-shadow: none;

  --el-button-padding-horizontal: 0 !important;

  --el-button-padding-vertical: 0 !important;

  font-size: 12px;

  font-weight: 500;

  cursor: pointer;

  transition: background .18s ease, color .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;

}

:deep(.toolbar-action-btn.el-button > span),

:deep(.toolbar-tight-btn.el-button > span) {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  width: 100%;

  height: 100%;

  padding: 0 !important;

}



.toolbar-refresh-content {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  gap: 6px;

  width: 100%;

}



.toolbar-refresh-icon,

.toolbar-refresh-label {

  transition: color .22s ease, opacity .22s ease, transform .22s ease;

}



.toolbar-refresh-icon {

  font-size: 13px;

  color: rgba(29, 29, 31, .56);

}



.toolbar-refresh-label {

  min-width: 36px;

  letter-spacing: .02em;

}



:deep(.toolbar-refresh-btn.el-button:hover .toolbar-refresh-icon) {

  color: #0071e3;

  transform: rotate(-18deg);

}



:deep(.toolbar-refresh-btn.el-button.is-refreshing),

:deep(.toolbar-refresh-btn.el-button.is-disabled.is-refreshing) {

  opacity: 1;

  cursor: default;

  color: #0b63ce;

  border-color: rgba(0, 113, 227, .16);

  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);

}



:deep(.toolbar-refresh-btn.el-button.is-refreshing > span),

:deep(.toolbar-refresh-btn.el-button.is-disabled.is-refreshing > span) {

  opacity: 1;

}



:deep(.toolbar-refresh-btn.el-button.is-refreshing .toolbar-refresh-icon) {

  color: #0b63ce;

  animation: library-refresh-spin .95s cubic-bezier(.55, .08, .38, .96) infinite;

}



:deep(.toolbar-action-btn.el-button--primary:hover) {

  background: #0077ed;

  border-color: #0077ed;

  color: #fff;

}



:deep(.toolbar-action-btn.el-button--primary:active) {

  background: #0068d1;

  border-color: #0068d1;

}



:deep(.toolbar-action-btn.el-button--primary) {

  background: #0071e3;

  border-color: #0071e3;

  color: #fff;

}



@keyframes library-refresh-spin {

  0% { transform: rotate(0deg); }

  42% { transform: rotate(160deg); }

  58% { transform: rotate(210deg); }

  100% { transform: rotate(360deg); }

}



:deep(.el-switch__core) {

  border-color: rgba(29, 29, 31, .08);

  background: #e9e9ed;

}



:deep(.el-switch.is-checked .el-switch__core) {

  background: #0071e3;

  border-color: #0071e3;

}



.library-option { display: flex; justify-content: space-between; align-items: center; gap: 8px; }

.path-toolbar {

  display: flex;

  justify-content: space-between;

  align-items: center;

  gap: 12px;

  margin-bottom: 14px;

  padding: 10px 12px;

  background: #f5f5f7;

  border: none;

  border-radius: 16px;

}

.path-toolbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; }

.path-toolbar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }

.toolbar-scope-toggle {

  display: inline-flex;

  align-items: center;

  gap: 3px;

  margin-right: 4px;

  padding: 3px;

  border-radius: 999px;

  background: #f5f5f7;

  box-shadow:

    inset 0 0 0 1px rgba(29, 29, 31, .08),

    0 1px 2px rgba(0, 0, 0, .04);

}



.toolbar-scope-option {

  min-width: 72px;

  padding: 6px 14px;

  border: none;

  border-radius: 999px;

  background: transparent;

  color: rgba(29, 29, 31, .72);

  font-size: 12px;

  font-weight: 500;

  line-height: 1;

  letter-spacing: -0.12px;

  cursor: pointer;

  -webkit-font-smoothing: antialiased;

  transition: background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;

}



.toolbar-scope-option:hover {

  color: #1d1d1f;

  background: rgba(255, 255, 255, .78);

}



.toolbar-scope-option:focus-visible {

  outline: 2px solid #0071e3;

  outline-offset: 2px;

}



.toolbar-scope-option.is-active {

  background: #0071e3;

  color: #fff;

  box-shadow:

    inset 0 0 0 1px rgba(255, 255, 255, .08),

    0 1px 3px rgba(0, 0, 0, .12);

}



.toolbar-scope-option.is-active:hover {

  background: #0077ed;

  color: #fff;

}



.toolbar-utility-btn,

.batch-action-btn {

  --apple-btn-bg: #fafafc;

  --apple-btn-bg-hover: #ffffff;

  --apple-btn-text: rgba(0, 0, 0, .8);

  --apple-btn-border: rgba(0, 0, 0, .06);

  --apple-btn-border-hover: rgba(0, 0, 0, .1);

  --apple-btn-shadow: rgba(0, 0, 0, .08) 0 1px 3px;

}



:deep(.toolbar-utility-btn.el-button),

:deep(.batch-action-btn.el-button) {

  min-height: 30px;

  padding: 0 14px !important;

  border-radius: 999px;

  border-color: transparent !important;

  background: var(--apple-btn-bg) !important;

  color: var(--apple-btn-text) !important;

  box-shadow:

    inset 0 0 0 1px var(--apple-btn-border),

    0 1px 2px rgba(0, 0, 0, .04);

  font-size: 12px;

  font-weight: 500;

  letter-spacing: -0.12px;

  transition: background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease;

}



:deep(.toolbar-utility-btn.el-button:hover),

:deep(.batch-action-btn.el-button:hover) {

  background: var(--apple-btn-bg-hover) !important;

  color: var(--apple-btn-text) !important;

  box-shadow:

    inset 0 0 0 1px var(--apple-btn-border-hover),

    var(--apple-btn-shadow);

  transform: translateY(-1px);

}



:deep(.toolbar-utility-btn.el-button:active),

:deep(.batch-action-btn.el-button:active) {

  transform: translateY(0);

  box-shadow:

    inset 0 0 0 1px var(--apple-btn-border-hover),

    0 1px 2px rgba(0, 0, 0, .04);

}



:deep(.toolbar-utility-btn.el-button:focus-visible),

:deep(.batch-action-btn.el-button:focus-visible) {

  outline: 2px solid #0071e3;

  outline-offset: 2px;

}



:deep(.toolbar-utility-btn.el-button > span),

:deep(.batch-action-btn.el-button > span) {

  display: inline-flex;

  align-items: center;

  gap: 4px;

}



:deep(.toolbar-utility-btn.el-button .el-icon),

:deep(.batch-action-btn.el-button .el-icon) {

  font-size: 12px;

}



:deep(.toolbar-utility-btn.el-button.is-disabled),

:deep(.toolbar-utility-btn.el-button.is-disabled:hover),

:deep(.batch-action-btn.el-button.is-disabled),

:deep(.batch-action-btn.el-button.is-disabled:hover),

:deep(.batch-action-btn.el-button.is-loading),

:deep(.batch-action-btn.el-button.is-loading:hover) {

  transform: none;

  opacity: .64;

  box-shadow:

    inset 0 0 0 1px var(--apple-btn-border),

    0 1px 2px rgba(0, 0, 0, .03);

}



.toolbar-utility-btn-primary,

.batch-action-btn-primary {

  --apple-btn-bg: #0071e3;

  --apple-btn-bg-hover: #0077ed;

  --apple-btn-text: #fff;

  --apple-btn-border: rgba(255, 255, 255, .08);

  --apple-btn-border-hover: rgba(255, 255, 255, .12);

  --apple-btn-shadow: rgba(0, 113, 227, .24) 0 6px 16px;

}



.toolbar-utility-btn-danger,

.batch-action-btn-danger {

  --apple-btn-bg: #fff5f5;

  --apple-btn-bg-hover: #fff;

  --apple-btn-text: #d70015;

  --apple-btn-border: rgba(215, 0, 21, .2);

  --apple-btn-border-hover: rgba(215, 0, 21, .28);

  --apple-btn-shadow: rgba(215, 0, 21, .12) 0 6px 16px;

}



.toolbar-utility-btn-neutral,

.batch-action-btn-neutral {

  --apple-btn-bg: #fafafc;

  --apple-btn-bg-hover: #ffffff;

  --apple-btn-text: rgba(0, 0, 0, .8);

  --apple-btn-border: rgba(0, 0, 0, .06);

  --apple-btn-border-hover: rgba(0, 0, 0, .1);

  --apple-btn-shadow: rgba(0, 0, 0, .08) 0 6px 16px;

}



.path-label { font-size: 12px; color: rgba(29, 29, 31, .48); white-space: nowrap; }

.path-code {

  padding: 6px 10px;

  border-radius: 999px;

  background: rgba(255, 255, 255, .92);

  color: rgba(29, 29, 31, .7);

  font-size: 11px;

}



:deep(.path-toolbar .el-button--small) {

  min-height: 30px;

  border-radius: 999px;

  font-size: 12px;

}



:deep(.el-table) {

  --el-table-header-bg-color: #f5f5f7;

  --el-table-row-hover-bg-color: #fafafc;

  border-radius: 14px;

  overflow: hidden;

}



:deep(.el-table th.el-table__cell) {

  font-weight: 600;

  font-size: 12px;

  color: rgba(29, 29, 31, .54);

}



:deep(.el-table td.el-table__cell) {

  border-bottom-color: rgba(29, 29, 31, .06);

}



.file-cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.file-main-line { display: flex; align-items: center; gap: 6px; min-width: 0; }

.file-icon-shell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
}

.file-icon {
  flex-shrink: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.file-icon.icon-folder {
  color: #f59e0b;
  fill: currentColor;
  stroke: currentColor;
}

.file-icon.icon-audio-lossless { color: #0f766e; }

.file-icon.icon-audio { color: #0ea5e9; }

.file-icon.icon-text { color: #8b5cf6; }

.file-icon.icon-file { color: #64748b; }

.file-name { vertical-align: middle; font-weight: 500; color: #1d1d1f; }

.file-link-btn { padding: 0; border: none; background: transparent; color: #1d1d1f; font: inherit; font-weight: 500; cursor: pointer; }

.file-link-btn:hover { color: #0066cc; }

.search-result-library { padding-left: 22px; font-size: 11px; line-height: 1.4; color: #7a8ba5; }

:deep(.library-search-mark) { background: #fff1a8; color: #7a4b00; padding: 0 2px; border-radius: 4px; }

:deep(.el-table .library-row-located > td.el-table__cell) { background: #eef7ff !important; }

:deep(.el-table .library-row-context-active > td.el-table__cell) { background: #f1f5f9 !important; }

:deep(.el-table .library-row-operating) {
  background:
    linear-gradient(
      105deg,
      rgba(239, 246, 255, 0.98) 0%,
      rgba(219, 234, 254, 0.92) 24%,
      rgba(96, 165, 250, 0.5) 42%,
      rgba(191, 219, 254, 0.86) 58%,
      rgba(147, 197, 253, 0.42) 72%,
      rgba(239, 246, 255, 0.98) 100%
    ) !important;
  background-size: 300% 100%;
  animation: library-row-operating-flow 1.25s linear infinite;
}

:deep(.el-table .library-row-operating > td.el-table__cell) {
  position: relative;
  overflow: hidden;
  background: transparent !important;
}

:deep(.el-table .library-row-operating > td.el-table__cell > .cell) {
  position: relative;
  z-index: 1;
}

:deep(.el-table .library-row-operating .file-icon-shell) {
  position: relative;
}

:deep(.el-table .library-row-operating .file-icon) {
  transform: rotate(-8deg) scale(1.08);
  filter: drop-shadow(0 4px 8px rgba(37, 99, 235, 0.18));
}

@keyframes library-row-operating-sweep {
  0% { transform: translateX(-120%); opacity: 0; }
  18% { opacity: 1; }
  100% { transform: translateX(120%); opacity: 0; }
}

@keyframes library-row-operating-flow {
  0% { background-position: 0% 0; }
  100% { background-position: 300% 0; }
}

@keyframes library-row-operating-pulse {
  0%, 100% { opacity: 0.72; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.08); }
}

.empty-text { color: #c0c4cc; }

.action-grid { display: inline-flex; flex-direction: column; gap: 4px; align-items: center; width: 100%; min-width: 0; }

.action-row { display: flex; gap: 4px; width: 100%; max-width: 228px; min-width: 0; }

.action-btn {

  --action-btn-bg: #fafafc;

  --action-btn-bg-hover: #ffffff;

  --action-btn-text: rgba(0, 0, 0, .8);

  --action-btn-border: rgba(0, 0, 0, .06);

  --action-btn-border-hover: rgba(0, 0, 0, .1);

  --action-btn-hover-shadow: rgba(0, 0, 0, .08) 0 6px 16px;

  flex: 1 1 0;

  margin: 0 !important;

  min-width: 0;

  border-radius: 999px;

  border-color: transparent !important;

  font-size: 12px;

  font-weight: 500;

  padding: 5px 0;

  background: var(--action-btn-bg) !important;

  color: var(--action-btn-text) !important;

  letter-spacing: -0.12px;

  box-shadow: inset 0 0 0 1px var(--action-btn-border);

  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease, color .18s ease;

}



.action-btn:hover {

  transform: translateY(-1px);

  background: var(--action-btn-bg-hover) !important;

  color: var(--action-btn-text) !important;

  box-shadow:

    inset 0 0 0 1px var(--action-btn-border-hover),

    var(--action-btn-hover-shadow);

}

.action-btn.is-loading,

.action-btn.is-loading:hover {

  transform: none;

  box-shadow: inset 0 0 0 1px var(--action-btn-border);

  cursor: wait;

}

.action-btn.is-loading :deep(.el-icon),

.action-btn.is-loading :deep(.el-icon svg) {

  color: currentColor !important;

}

:deep(.action-btn.el-button.is-loading),

:deep(.action-btn.el-button.is-disabled) {

  opacity: .66;

}

:deep(.action-btn.el-button.is-loading > span),

:deep(.action-btn.el-button.is-disabled > span) {

  opacity: .95;

}

.action-btn-open,

.action-btn-direct,

.action-btn-rename,

.action-btn-api,

.action-btn-manage {

  --action-btn-bg: #fafafc;

  --action-btn-bg-hover: #ffffff;

  --action-btn-text: rgba(0, 0, 0, .8);

  --action-btn-border: rgba(0, 0, 0, .06);

  --action-btn-border-hover: rgba(0, 0, 0, .1);

  --action-btn-hover-shadow: rgba(0, 0, 0, .08) 0 6px 16px;

}



.action-btn-subtitle {

  --action-btn-bg: #0071e3;

  --action-btn-bg-hover: #0077ed;

  --action-btn-text: #fff;

  --action-btn-border: rgba(255, 255, 255, .08);

  --action-btn-border-hover: rgba(255, 255, 255, .12);

  --action-btn-hover-shadow: rgba(0, 113, 227, .24) 0 6px 16px;

}



.action-btn-delete {

  --action-btn-bg: #fff5f5;

  --action-btn-bg-hover: #ffffff;

  --action-btn-text: #d70015;

  --action-btn-border: rgba(215, 0, 21, .2);

  --action-btn-border-hover: rgba(215, 0, 21, .28);

  --action-btn-hover-shadow: rgba(215, 0, 21, .12) 0 6px 16px;

}



:deep(.action-btn-api.el-button.is-batch-target),

:deep(.action-btn-api.el-button.is-batch-target:hover) {

  transform: none;

  opacity: .92;

  background: #f2f5f9 !important;

  color: rgba(29, 29, 31, .46) !important;

  box-shadow:

    inset 0 0 0 1px rgba(29, 29, 31, .08),

    0 1px 2px rgba(0, 0, 0, .03);

}



:deep(.action-btn-api.el-button.is-batch-target > span) {

  position: relative;

}



:deep(.action-btn-api.el-button.is-batch-target:not(.is-loading) > span::before) {

  content: '';

  width: 10px;

  height: 10px;

  margin-right: 6px;

  border-radius: 50%;

  border: 1.5px solid rgba(29, 29, 31, .12);

  border-top-color: rgba(29, 29, 31, .34);

  display: inline-block;

  vertical-align: middle;

}

.batch-bar {

  display: flex;

  justify-content: space-between;

  align-items: center;

  margin-top: 12px;

  padding: 10px 16px;

  background: #f5f5f7;

  border: none;

  border-radius: 14px;

}

.batch-actions { display: flex; align-items: center; gap: 8px; }

.selected-count {

  font-weight: 600;

  color: #0066cc;

  font-size: 12px;

  background: rgba(255, 255, 255, .92);

  padding: 5px 10px;

  border-radius: 999px;

}



.pagination-wrap { margin-top: 18px; display: flex; justify-content: flex-end; }



:deep(.el-pagination) {

  gap: 6px;

  font-size: 12px;

}



:deep(.el-pagination .btn-prev),

:deep(.el-pagination .btn-next),

:deep(.el-pagination .el-pager li) {

  min-width: 30px;

  height: 30px;

  line-height: 30px;

  border-radius: 10px;

  background: #f5f5f7;

}



:deep(.el-pagination .el-pager li.is-active) {

  background: #0071e3;

  color: #fff;

}



:deep(.el-pagination .el-pagination__sizes .el-select__wrapper),

:deep(.el-pagination .el-pagination__jump .el-input__wrapper) {

  min-height: 30px;

  border-radius: 10px;

  background: #f5f5f7;

}



:deep(.el-tag) {

  border-radius: 999px;

}

.filter-delete-floating-card {

  position: fixed;

  right: 22px;

  bottom: 22px;

  z-index: 2100;

  width: 360px;

  display: grid;

  gap: 10px;

  padding: 14px 16px;

  border: 1px solid #d7e6ff;

  border-radius: 16px;

  background: rgba(255, 255, 255, .98);

  box-shadow: 0 18px 42px rgba(38, 68, 110, .18);

  backdrop-filter: blur(8px);

}

.filter-delete-floating-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }

.filter-delete-floating-title { font-size: 14px; font-weight: 700; color: #23426c; }

.filter-delete-floating-mode { margin-top: 2px; font-size: 12px; color: #71839d; }

.filter-delete-floating-percent { font-size: 20px; font-weight: 700; color: #2458a6; line-height: 1; }

.filter-delete-floating-text { font-size: 12px; line-height: 1.5; color: #51657f; }

.filter-delete-floating-chip-row { display: flex; gap: 6px; flex-wrap: wrap; }

.filter-delete-floating-chip {

  display: inline-flex;

  align-items: center;

  padding: 4px 8px;

  border-radius: 999px;

  border: 1px solid #d8e5f8;

  background: #f5f9ff;

  font-size: 11px;

  font-weight: 600;

  color: #4f6787;

}

.filter-delete-floating-path {

  font-size: 11px;

  line-height: 1.45;

  color: #8090a6;

  word-break: break-all;

  padding: 8px 10px;

  border-radius: 10px;

  background: #f6f9fe;

}

.filter-delete-floating-stats { font-size: 12px; font-weight: 600; color: #466182; }

.filter-delete-floating-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }

.name-preview, .path-code { font-family: monospace; font-size: 13px; word-break: break-all; }

.name-preview { padding: 8px 12px; background: #f8f9fa; border: 1px solid #e4e7ed; border-radius: 4px; color: #606266; }

.floating-card {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2100;
  isolation: isolate;
  overflow: hidden;
  width: min(92vw, 420px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.10), 0 2px 8px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(16px);
  animation: floating-card-in 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes floating-card-in {
  from { opacity: 0; transform: translateY(10px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.floating-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #ffffff;
  font-size: 10.5px;
  color: #64748b;
  letter-spacing: -0.01em;
}

.floating-chip-row-compact {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
}

.floating-chip-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

.floating-chip-icon.chip-blue { color: #2563eb; }
.floating-chip-icon.chip-amber { color: #d97706; }
.floating-chip-icon.chip-emerald { color: #059669; }
.floating-chip-icon.chip-rose { color: #e11d48; }
.floating-chip-icon.chip-indigo { color: #4f46e5; }
.floating-chip-icon.chip-violet { color: #7c3aed; }

.floating-chip b {
  font-weight: 600;
  color: #334155;
}

.floating-chip-danger {
  color: #b91c1c;
  background: #fff1f2;
  border-color: #fecaca;
}

.floating-chip-danger b {
  color: #b91c1c;
}

.floating-chip-title {
  padding: 1px 6px;
  font-size: 10px;
  border-radius: 999px;
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.floating-card-upload {
  position: fixed;
}

.upload-floating-head {
  display: flex;
  align-items: flex-start;
  padding-right: 90px;
  min-width: 0;
}

.upload-floating-title {
  min-width: 0;
  white-space: normal;
  word-break: break-word;
}

.floating-hero-icon {
  display: inline-flex;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 0;
  border: 0;
  background: transparent;
  overflow: hidden;
}

.floating-hero-lottie {
  width: 36px;
  height: 36px;
}

.floating-progress-lottie {
  position: absolute;
  right: 10px;
  top: 7px;
  width: 56px;
  height: 56px;
  display: block;
  pointer-events: none;
  object-fit: contain;
  transform-origin: top right;
}

.floating-progress-lottie-progress {
  width: 56px;
  height: 56px;
}

.floating-progress-lottie-success {
  right: 4px;
  top: 2px;
  width: 72px;
  height: 72px;
}

.floating-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 13px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.floating-action-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(15, 23, 42, 0.08);
}

.floating-action-btn:active {
  transform: scale(0.96);
}

.floating-action-btn-primary {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.30);
}

.floating-action-btn-primary:hover {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.38);
}

.floating-action-btn-emerald {
  background: linear-gradient(135deg, #10b981, #059669);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.30);
}

.floating-action-btn-emerald:hover {
  background: linear-gradient(135deg, #059669, #047857);
  color: #fff;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.38);
}

.mapped-path-box { display: flex; flex-direction: column; gap: 10px; }

.path-actions { display: flex; gap: 8px; }

:deep(.fm-dialog .el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,.18); }

:deep(.fm-dialog .el-dialog__header) { padding: 0; margin: 0; }

:deep(.fm-dialog .el-dialog__body) { padding: 0; }

.fm-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 12px 20px; border-bottom: 1px solid #e4e7ed; }

.fm-title { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; color: #303133; min-width: 0; }

.fm-badge { font-size: 12px; color: #909399; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 10px; padding: 2px 8px; }

.fm-count { font-size: 12px; color: #606266; background: #f0f7ff; border: 1px solid #c6e2ff; border-radius: 12px; padding: 2px 10px; }

.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }

.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-bottom: 1px solid #e4e7ed; }

.fm-toolbar-left { display: flex; align-items: center; gap: 6px; }

.fm-btn { padding: 4px 11px; font-size: 12px; border-radius: 5px; border: 1px solid #dcdfe6; background: #fff; cursor: pointer; }

.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }

.fm-btn-ghost:hover { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }

.fm-search-input { width: 260px; height: 30px; padding: 0 10px; font-size: 12px; border: 1px solid #dcdfe6; border-radius: 5px; outline: none; }

.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }

.fm-head { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }

.fm-scroll { flex: 1; overflow: auto; contain: strict; }

.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; contain: layout paint style; }

.fm-row-dir { background: #fafbfc; cursor: pointer; }

.fm-row-selected { background: linear-gradient(90deg, rgba(226, 232, 240, 0.72), rgba(248, 250, 252, 0.96)) !important; }

.fm-row-disabled { background: #fbfbfc; color: #a5afbc; }

.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }

.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }

.fm-arrow { width: 14px; display: inline-flex; align-items: center; justify-content: center; color: #909399; transition: transform .16s; white-space: nowrap; }

.fm-arrow.open { transform: rotate(90deg); color: #409eff; }

.fm-arrow-toggle { border: 0; background: transparent; padding: 0; cursor: pointer; }

.fm-arrow-placeholder { width: 14px; flex: 0 0 14px; }

.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }

.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.fm-link-edit { background: #ffffff; color: #475569; border: 1px solid #d7dfec; border-radius: 8px; padding: 4px 10px; cursor: pointer; }

.fm-link-danger { background: #fff0f0; color: #f56c6c; border: 1px solid #fbc4c4; border-radius: 4px; padding: 2px 8px; cursor: pointer; }

.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }

@media (max-width: 1280px) {

  .summary-grid { grid-template-columns: 1fr; }

  .card-header { flex-direction: column; align-items: flex-start; }

  .header-actions { width: 100%; justify-content: flex-start; }

  .batch-bar,

  .path-toolbar { flex-direction: column; align-items: flex-start; }

  .batch-actions,

  .path-toolbar-right { width: 100%; justify-content: flex-start; flex-wrap: wrap; }

  .filter-delete-floating-card { left: 12px; right: 12px; bottom: 12px; width: auto; }

}

</style>



