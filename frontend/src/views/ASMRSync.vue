<template>
  <div class="asmr-page">
    <!-- 页头：和库存页 / 操作记录页保持一致 -->
    <AppPageHeader
      :icon="DownloadIcon"
      icon-color="var(--km-nav-asmr-icon)"
      title="ASMR 同步下载"
      subtitle="根据字幕文件自动下载并匹配，或手动输入 RJ 号查询下载"
    >
      <button
        class="asmr-head-btn ghost btn-scan"
        type="button"
        :disabled="scanning || !subtitleFolder"
        @click="scanFolder"
      >
        <span class="page-head-btn-icon-swap-container">
          <Loader2 :size="13" :stroke-width="2.4" class="page-head-btn-icon-slot animate-spin" :class="{ 'is-visible': scanning }" />
          <Search :size="13" :stroke-width="2.4" class="page-head-btn-icon-slot asmr-head-btn-icon" :class="{ 'is-visible': !scanning }" />
        </span>
        <span class="page-head-btn-label">{{ scanning ? '扫描中…' : '扫描' }}</span>
      </button>
      <button
        class="asmr-head-btn primary btn-download"
        type="button"
        :disabled="syncing || selectedItems.length === 0"
        @click="startSync"
      >
        <span class="page-head-btn-icon-swap-container">
          <Loader2 :size="13" :stroke-width="2.6" class="page-head-btn-icon-slot animate-spin" :class="{ 'is-visible': syncing }" />
          <DownloadIcon :size="13" :stroke-width="2.6" class="page-head-btn-icon-slot asmr-head-btn-icon" :class="{ 'is-visible': !syncing }" />
        </span>
        <span class="page-head-btn-label">{{ syncing ? '同步中…' : '开始同步下载' }}</span>
      </button>
      <button
        class="asmr-head-btn ghost btn-refresh"
        type="button"
        :disabled="refreshing"
        title="刷新状态"
        @click="refreshStatus"
      >
        <span class="page-head-btn-icon-wrap">
          <RefreshCw
            :size="13"
            :stroke-width="2.6"
            class="asmr-head-btn-icon"
            :class="{ 'animate-spin': refreshing }"
          />
        </span>
        <span class="page-head-btn-label">刷新</span>
      </button>
    </AppPageHeader>

    <!-- 顶部状态条：6 列指标（接入 enhancedMetricCards） -->
    <section class="lib-info-strip asmr-info-strip">
      <template v-for="(metric, idx) in enhancedMetricCards" :key="metric.label">
        <div class="lib-info-item" :title="metric.help">
          <component
            :is="metric.icon"
            :size="15"
            :stroke-width="2.2"
            class="lib-info-icon"
            :class="metric.iconClass"
          />
          <div class="lib-info-body">
            <div class="lib-info-label">{{ metric.label }}</div>
            <div class="lib-info-value">
              <Transition name="asmr-num-flip" mode="out-in">
                <b :key="String(metric.value)">{{ metric.value }}</b>
              </Transition>
            </div>
          </div>
        </div>
        <div v-if="idx < enhancedMetricCards.length - 1" class="lib-info-divider"></div>
      </template>
    </section>

    <section class="asmr-workspace-tabs" role="tablist" aria-label="ASMR 下载工作台">
      <button
        v-for="tab in workspaceTabs"
        :key="tab.key"
        type="button"
        class="asmr-workspace-tab"
        :class="{ 'is-active': activeWorkspaceTab === tab.key }"
        role="tab"
        :aria-selected="activeWorkspaceTab === tab.key"
        @click="activeWorkspaceTab = tab.key"
      >
        <component :is="tab.icon" :size="14" :stroke-width="2.4" />
        <span>{{ tab.label }}</span>
        <b v-if="tab.badge">{{ tab.badge }}</b>
      </button>
    </section>

    <Transition name="asmr-workspace-panel" mode="out-in" :duration="180">
      <AsmrEnhancedDownloadPanel
        v-if="activeWorkspaceTab === 'enhanced'"
        v-model:input="enhancedInput"
        :plans="enhancedPlans"
        :selected-rjcodes="selectedPlanRjcodes"
        :selected-set="selectedPlanSet"
        :planning="enhancedPlanning"
        :starting="enhancedStarting"
        :has-workbench-tasks="enhancedDownloadWorkbenchTaskIds.length > 0"
        :get-resource-type-label="getResourceTypeLabel"
        @query="buildEnhancedPlans"
        @open-workbench="enhancedDownloadWorkbenchVisible = true"
        @select-all="selectAllPlans"
        @clear-selection="clearPlanSelection"
        @download-selected="openEnhancedPreview"
        @toggle-plan="togglePlanSelect"
      />

      <HttpDownloadPanel
        v-else-if="activeWorkspaceTab === 'http'"
        v-model:draft="httpDownloadDraft"
        :has-tasks="httpDownloadWorkbenchTaskIds.length > 0"
        @started="handleHttpDownloadStarted"
        @open-workbench="resumeHttpDownloadWorkbench"
      />

      <BaiduNetdiskPanel
        v-else-if="activeWorkspaceTab === 'baidu'"
        v-model:draft="baiduNetdiskDraft"
        :has-tasks="baiduNetdiskWorkbenchTaskIds.length > 0"
        @started="handleBaiduNetdiskStarted"
        @open-workbench="resumeBaiduNetdiskWorkbench"
      />

      <AsmrSubtitleScanPanel v-else v-model="subtitleFolder" />
    </Transition>

    <DownloadTaskWorkbenchDialog
      v-model:visible="httpDownloadWorkbenchVisible"
      :tasks="httpDownloadWorkbenchTasks"
      :refreshing="httpDownloadWorkbenchRefreshing"
      :retrying-keys="[...httpDownloadRetryingTaskIds]"
      title="HTTP 外链下载"
      subtitle="aria2 下载任务进度"
      source-path-label="下载根目录"
      :merge-tasks="false"
      :compact="true"
      :enable-file-retry="true"
      @refresh="refreshHttpDownloadWorkbench({ silent: true })"
      @background="hideHttpDownloadWorkbenchToBackground"
      @close="closeHttpDownloadWorkbench"
      @retry-task="retryHttpDownloadTask"
      @retry-file="retryHttpDownloadFile"
      @pause-task="pauseHttpDownloadTask"
      @resume-task="resumeHttpDownloadTask"
      @cancel-task="cancelHttpDownloadTask"
      @load-files="task => loadFullWorkbenchTaskFiles(task, httpDownloadWorkbenchTasks)"
    />

    <DownloadTaskWorkbenchDialog
      v-model:visible="baiduNetdiskWorkbenchVisible"
      :tasks="baiduNetdiskWorkbenchTasks"
      :refreshing="baiduNetdiskWorkbenchRefreshing"
      :retrying-keys="[...baiduNetdiskRetryingTaskIds]"
      title="百度网盘下载"
      subtitle="百度网盘直下任务进度"
      source-path-label="下载根目录"
      :merge-tasks="false"
      :compact="true"
      :enable-file-retry="true"
      @refresh="refreshBaiduNetdiskWorkbench({ silent: true })"
      @background="hideBaiduNetdiskWorkbenchToBackground"
      @close="closeBaiduNetdiskWorkbench"
      @retry-task="retryBaiduNetdiskTask"
      @retry-file="retryBaiduNetdiskFile"
      @pause-task="pauseBaiduNetdiskTask"
      @resume-task="resumeBaiduNetdiskTask"
      @cancel-task="cancelBaiduNetdiskTask"
      @load-files="task => loadFullWorkbenchTaskFiles(task, baiduNetdiskWorkbenchTasks)"
    />

    <Transition name="floating-card">
      <div v-if="visibleBackgroundFloatingCards.length" class="asmr-floating-pager">
        <div v-if="visibleBackgroundFloatingCards.length > 1" class="asmr-floating-pager-controls">
          <button
            type="button"
            class="asmr-floating-page-btn"
            title="上一张"
            @click="switchBackgroundFloatingCard(-1)"
          >
            <ChevronLeft :size="15" :stroke-width="2.4" />
          </button>
          <div class="asmr-floating-page-dots">
            <button
              v-for="(card, index) in visibleBackgroundFloatingCards"
              :key="card.id"
              type="button"
              class="asmr-floating-page-dot"
              :class="{ 'is-active': index === activeBackgroundFloatingCardIndex }"
              :title="card.label"
              @click="setBackgroundFloatingCardIndex(index)"
            />
          </div>
          <button
            type="button"
            class="asmr-floating-page-btn"
            title="下一张"
            @click="switchBackgroundFloatingCard(1)"
          >
            <ChevronRight :size="15" :stroke-width="2.4" />
          </button>
        </div>
        <Transition :name="backgroundFloatingCardTransitionName" mode="out-in">
          <BackgroundFloatingCard
            v-if="activeBackgroundFloatingCard"
            :key="activeBackgroundFloatingCard.id"
            v-bind="activeBackgroundFloatingCard.props"
            :hosted="true"
            @action="handleVisibleBackgroundFloatingCardAction"
          />
        </Transition>
      </div>
    </Transition>

    <!-- Enhanced Download Workbench Dialog -->
    <DownloadTaskWorkbenchDialog
      v-model:visible="enhancedDownloadWorkbenchVisible"
      :tasks="enhancedDownloadWorkbenchTasks"
      :refreshing="enhancedDownloadWorkbenchRefreshing"
      :retrying-keys="[...enhancedRetryingTaskIds]"
      :retrying-session-ids="[...enhancedRetryingSessionIds]"
      title="ASMR 增强下载"
      subtitle="增强下载任务进度"
      :enable-file-retry="true"
      @refresh="refreshEnhancedDownloadWorkbench({ silent: true })"
      @background="hideEnhancedDownloadWorkbenchToBackground"
      @close="closeEnhancedDownloadWorkbench"
      @retry-task="retryEnhancedDownloadTask"
      @retry-file="retryEnhancedDownloadFile"
      @pause-task="handlePauseEnhancedDownloadTask"
      @resume-task="handleResumeEnhancedDownloadTask"
      @cancel-task="handleCancelEnhancedDownloadTask"
      @load-files="task => loadFullWorkbenchTaskFiles(task, enhancedDownloadWorkbenchTasks)"
    />

    <!-- Enhanced Download Preview Dialog -->
    <CircleDownloadPreviewDialog
      v-model:visible="enhancedPreviewVisible"
      :starting="previewStarting"
      :plans="previewPlans"
      :libraries="libraries"
      :target-subdir-options="[]"
      :settings="downloadSettings"
      circle-name=""
      :enable-direct-mode="true"
      :existing-paths="existingRJPaths"
      :direct-loading="locatingRJ"
      @submit="handlePreviewSubmit"
    />

    <!-- 扫描结果 -->
    <Transition name="asmr-section">
    <section v-if="activeWorkspaceTab === 'subtitle' && scanResults.length > 0" class="asmr-card">
      <header class="asmr-card-head">
        <div class="asmr-card-head-title">
          <ListChecks :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
          <div>
            <h2>扫描结果</h2>
            <p class="asmr-card-head-subtitle">{{ scanResults.length }} 个作品</p>
          </div>
        </div>
        <label class="asmr-card-head-checkbox">
          <input type="checkbox" v-model="selectAll" @change="handleSelectAll($event.target.checked)" />
          <span>全选</span>
        </label>
      </header>
      <div class="asmr-table-wrap">
        <el-table :data="scanResults" style="width: 100%" row-key="rjcode" @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="rjcode" label="RJ号" width="120">
            <template #default="{ row }">
              <span class="asmr-rjcode">{{ row.rjcode }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="folder_name" label="文件夹名称" min-width="250">
            <template #default="{ row }">
              <div class="flex items-center gap-2">
                <FolderIcon :size="14" :stroke-width="2.2" class="asmr-muted-icon shrink-0" />
                <span class="asmr-cell-text text-sm truncate">{{ row.folder_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="subtitle_count" label="字幕数" width="80" align="center">
            <template #default="{ row }">
              <span class="asmr-cell-text text-sm">{{ row.subtitle_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="预览" width="80" align="center">
            <template #default="{ row }">
              <button
                class="asmr-link-btn"
                type="button"
                :disabled="row.previewing"
                @click="previewDownload(row)"
              >
                {{ row.previewing ? '…' : '预览' }}
              </button>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <span class="lib-chip" :class="{
                'lib-chip-slate': row.status === 'pending',
                'lib-chip-warning': row.status === 'downloading',
                'lib-chip-success': row.status === 'completed',
                'lib-chip-danger': row.status === 'failed',
              }">{{ { pending: '待下载', downloading: '下载中', completed: '已完成', failed: '失败' }[row.status] || row.status }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>
    </Transition>

    <!-- 等待重试 -->
    <Transition name="asmr-section">
    <section v-if="waitingRetryTasks.length > 0" class="asmr-card asmr-card-amber">
      <header class="asmr-card-head asmr-card-head-amber">
        <div class="asmr-card-head-title">
          <Clock :size="14" :stroke-width="2.4" class="asmr-card-head-icon-amber" />
          <h2>等待重试 <span class="asmr-card-head-count">({{ waitingRetryTasks.length }})</span></h2>
        </div>
        <span v-if="nextRetryTime" class="asmr-muted-text text-xs">下次：{{ formatNextRetryTime(nextRetryTime) }}</span>
      </header>
      <TransitionGroup tag="div" name="asmr-list" class="asmr-card-body asmr-list">
        <div v-for="task in waitingRetryTasks" :key="task.id" class="asmr-list-row">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="asmr-rjcode">{{ task.rjcode }}</span>
              <span class="asmr-cell-text text-sm truncate">{{ task.work_title || task.task_metadata?.work_title }}</span>
            </div>
            <div class="asmr-muted-text flex items-center gap-3 mt-1 text-xs">
              <span class="asmr-warning-text">{{ task.task_metadata?.retry_reason || task.current_step || '未找到版本' }}</span>
              <span>已重试 {{ task.task_metadata?.retry_count || 0 }} 次</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            <button class="asmr-mini-btn is-primary" type="button" @click="retryWaitingTask(task.id)">重试</button>
            <button class="asmr-mini-btn" type="button" @click="cancelWaitingTask(task.id)">取消</button>
          </div>
        </div>
      </TransitionGroup>
    </section>
    </Transition>

    <!-- 下载任务 -->
    <Transition name="asmr-section">
    <section v-if="activeTasks.length > 0" class="asmr-card">
      <header class="asmr-card-head">
        <div class="asmr-card-head-title">
          <ListChecks :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
          <div>
            <h2>下载任务</h2>
            <p class="asmr-card-head-subtitle">{{ activeTasks.length }} 个进行中 / 历史任务</p>
          </div>
        </div>
      </header>
      <TransitionGroup tag="div" name="asmr-list" class="asmr-card-body asmr-list">
        <div
          v-for="task in activeTasks"
          :key="task.id"
          class="asmr-task"
          :class="{
            'is-completed': task.status === 'completed',
            'is-failed': task.status === 'failed',
            'is-paused': task.status === 'paused',
            'is-processing': task.status === 'processing',
          }"
        >
          <!-- 任务头：RJ + 标题 + 状态 chip + 操作 -->
          <div class="asmr-task-head">
            <div class="asmr-task-head-info">
              <span class="asmr-rjcode is-bold">{{ task.actual_rjcode || task.rjcode }}</span>
              <span v-if="task.actual_rjcode && task.actual_rjcode !== task.rjcode" class="asmr-muted-text text-xs">(原: {{ task.rjcode }})</span>
              <span class="asmr-cell-text text-sm truncate">{{ task.work_title }}</span>
            </div>
            <div class="asmr-task-head-actions">
              <span class="lib-chip" :class="{
                'lib-chip-success': task.status === 'completed',
                'lib-chip-danger': task.status === 'failed',
                'lib-chip-slate': task.status === 'paused' || task.status === 'pending',
                'lib-chip-warning': task.status === 'waiting_retry',
                'lib-chip-info': task.status === 'processing',
              }">{{ getStatusText(task.status) }}</span>
              <button v-if="task.status === 'processing'" class="asmr-mini-btn xs" type="button" @click="pauseTask(task.id)">暂停</button>
              <button v-if="task.status === 'paused'" class="asmr-mini-btn xs is-primary" type="button" @click="resumeTask(task.id)">继续</button>
              <button v-if="task.status === 'waiting_retry'" class="asmr-mini-btn xs is-primary" type="button" @click="retryWaitingTask(task.id)">立即重试</button>
              <button
                v-if="task.failed_files && task.failed_files.length > 0"
                class="asmr-mini-btn xs is-warning"
                type="button"
                :disabled="isEnhancedRetryTaskBlocked(task)"
                @click="retryFailed(task.id)"
              >
                {{ isEnhancedRetryTaskBlocked(task) ? '重试提交中' : `重试失败 (${task.failed_files.length})` }}
              </button>
            </div>
          </div>

          <!-- 进度条 -->
          <div class="mt-3">
            <AppLottieProgressBar :percentage="task.progress" size="sm" />
          </div>

          <!-- 当前步骤 -->
          <div class="asmr-muted-text flex items-center gap-1.5 mt-2 text-xs">
            <AppLoadingAnimation v-if="task.status === 'processing'" variant="inline" :size="20" />
            <span>{{ task.current_step }}</span>
          </div>

          <!-- 错误提示 -->
          <div v-if="task.error_message" class="asmr-task-alert is-error">
            <AlertTriangle :size="14" :stroke-width="2.4" />
            <span>{{ task.error_message }}</span>
          </div>

          <!-- 字幕同步映射 -->
          <details v-if="task.sync_result?.renamed_files?.length" class="asmr-task-details">
            <summary class="asmr-task-details-summary is-success">
              <FileText :size="13" :stroke-width="2.4" />
              字幕同步映射 ({{ task.sync_result.renamed_files.length }} 对)
            </summary>
            <div class="asmr-task-details-body">
              <div v-for="(item, idx) in task.sync_result.renamed_files" :key="idx" class="asmr-task-mapping">
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">原音频</span><span class="asmr-warning-text font-medium truncate">{{ item.original }}</span></div>
                <div class="asmr-task-mapping-arrow">↓</div>
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">重命名</span><span class="asmr-accent-text font-medium truncate">{{ item.new }}</span></div>
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">字幕</span><span class="asmr-success-text font-medium truncate">{{ item.subtitle }}</span></div>
              </div>
            </div>
          </details>

          <!-- 失败文件 -->
          <details v-if="task.failed_files?.length" class="asmr-task-details">
            <summary class="asmr-task-details-summary is-danger">
              <AlertTriangle :size="13" :stroke-width="2.4" />
              失败文件 ({{ task.failed_files.length }})
            </summary>
            <div class="asmr-task-details-body">
              <div v-for="(file, idx) in task.failed_files" :key="idx" class="asmr-task-failed-item">
                <span class="asmr-cell-text truncate">{{ file.title || file.path }}</span>
                <span class="asmr-danger-text shrink-0 ml-2">{{ file.reason }}</span>
              </div>
            </div>
          </details>

          <!-- 下载文件进度 -->
          <details v-if="task.download_files?.length" class="asmr-task-details">
            <summary class="asmr-task-details-summary is-slate">
              <FolderIcon :size="13" :stroke-width="2.4" />
              文件下载进度 ({{ task.download_files.length }})
            </summary>
            <div class="asmr-task-details-body">
              <div v-for="file in task.download_files" :key="file.name" class="asmr-task-file-row">
                <span class="asmr-cell-text flex-1 min-w-0 truncate">{{ file.name }}</span>
                <div class="asmr-task-file-progress">
                  <div class="asmr-task-file-progress-bar" :style="{ width: file.progress + '%' }" />
                </div>
                <span class="asmr-task-file-size">{{ formatSize(file.downloaded) }} / {{ formatSize(file.total) }}</span>
              </div>
            </div>
          </details>
        </div>
      </TransitionGroup>
    </section>
    </Transition>

    <!-- Preview Dialog -->
    <!-- mobile-full-dialog 类让 ≤640 自动 100vw/100dvh，桌面 width=900px 不变 -->
    <el-dialog v-model="previewDialogVisible" title="下载预览" width="900px" class="asmr-dialog-theme rounded-2xl mobile-full-dialog">
      <div v-if="previewLoading" class="flex items-center justify-center py-10">
        <AppLoadingAnimation label="正在获取作品信息..." :size="132" :min-height="180" />
      </div>
      <div v-else-if="previewData" class="space-y-5">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div class="asmr-preview-stat rounded-xl p-3">
            <div class="asmr-muted-text text-xs mb-1">请求 RJ 号</div>
            <div class="asmr-strong-text font-mono font-semibold">{{ previewData.rjcode }}</div>
          </div>
          <div class="asmr-preview-stat rounded-xl p-3">
            <div class="asmr-muted-text text-xs mb-1">实际下载</div>
            <div class="flex items-center gap-2">
              <span class="font-mono font-semibold" :class="previewData.actual_rjcode !== previewData.rjcode ? 'asmr-warning-text' : 'asmr-success-text'">{{ previewData.actual_rjcode || '未找到' }}</span>
              <span v-if="previewData.lang" class="asmr-muted-text text-xs">({{ previewData.lang }})</span>
            </div>
          </div>
          <div class="asmr-preview-stat rounded-xl p-3">
            <div class="asmr-muted-text text-xs mb-1">预计大小</div>
            <div class="asmr-accent-text font-semibold">{{ formatSize(previewData.total_size) }}</div>
          </div>
        </div>
        <div class="asmr-cell-text flex items-center gap-4 text-sm">
          <span>标题: <strong class="asmr-strong-text">{{ previewData.title }}</strong></span>
          <span>文件: {{ previewData.total_files }} → <strong class="asmr-success-text">{{ previewData.filtered_files }}</strong></span>
        </div>

        <!-- Available Versions -->
        <div v-if="previewData.available_versions?.length">
          <h4 class="asmr-section-title text-sm font-semibold mb-2">可用版本</h4>
          <div class="space-y-1.5">
            <div v-for="ver in previewData.available_versions" :key="ver.rjcode"
              class="asmr-preview-row flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
            >
              <span class="asmr-strong-text font-mono font-semibold w-24">{{ ver.rjcode }}</span>
              <span class="asmr-dialog-chip" :class="{
                'is-success': ver.priority <= 1,
                'is-warning': ver.priority === 2,
                'is-muted': ver.priority > 2,
              }">{{ getLangName(ver.lang) }}</span>
              <span class="asmr-muted-text">{{ ver.file_count }} 文件</span>
              <span class="asmr-dialog-chip is-compact" :class="ver.available ? 'is-success' : 'is-danger'">{{ ver.available ? '可用' : '不可用' }}</span>
              <span class="asmr-muted-text truncate flex-1">{{ ver.title }}</span>
            </div>
          </div>
        </div>

        <!-- File List -->
        <div>
          <h4 class="asmr-section-title text-sm font-semibold mb-2">下载文件 ({{ previewData.filtered_files }})</h4>
          <div class="overflow-auto" style="max-height: 350px;">
            <el-table :data="previewData.files" size="small">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="文件路径" min-width="300">
                <template #default="{ row }">
                  <div class="flex items-center gap-1.5 text-sm">
                    <FileIcon class="asmr-muted-icon w-3.5 h-3.5 shrink-0" />
                    <span class="truncate" :title="row.path || row.title">{{ row.title }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="type" label="类型" width="80">
                <template #default="{ row }">
                  <span class="asmr-muted-text text-xs">{{ row.type || '文件' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  <span class="asmr-cell-text text-xs font-mono">{{ formatSize(row.size) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
      <div v-else class="py-10">
        <AppEmptyState description="无法获取预览信息" size="sm" />
      </div>
    </el-dialog>

    <!-- Enhanced Session Drawer -->
    <!-- ≤640 抽屉占满整屏，桌面端保留 55% 侧滑 -->
    <el-drawer v-model="enhancedSessionDrawerVisible" class="asmr-dialog-theme" :size="isMobileViewport ? '100%' : '55%'" :title="enhancedSessionDetail?.rjcode ? `${enhancedSessionDetail.rjcode} 会话详情` : '会话详情'">
      <div v-app-loading="{ loading: enhancedSessionDetailLoading, text: '正在加载增强下载详情...', size: 124 }">
        <template v-if="enhancedSessionDetail">
          <div class="flex flex-wrap gap-2 mb-4">
            <span class="asmr-dialog-chip is-info">{{ getSessionStatusLabel(enhancedSessionDetail.status) }}</span>
            <span class="asmr-dialog-chip is-muted">优先级 {{ enhancedSessionDetail.queue_priority }}</span>
            <span class="asmr-dialog-chip is-muted">{{ getUploadModeLabel(enhancedSessionDetail.upload_mode) }}</span>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <div class="asmr-preview-stat rounded-lg p-3">
              <div class="asmr-muted-text text-xs">标题</div>
              <div class="asmr-strong-text text-sm font-medium mt-0.5">{{ enhancedSessionDetail.source_label || '未命名会话' }}</div>
            </div>
            <div class="asmr-preview-stat rounded-lg p-3">
              <div class="asmr-muted-text text-xs">目标路径</div>
              <div class="asmr-strong-text text-sm font-mono mt-0.5 break-all">{{ enhancedSessionDetail.target_path || '未设置' }}</div>
            </div>
            <div class="asmr-preview-stat rounded-lg p-3">
              <div class="asmr-muted-text text-xs">已选/已上传</div>
              <div class="asmr-strong-text text-sm font-medium mt-0.5">{{ enhancedSessionDetail.statistics?.selected_resource_count || 0 }} / {{ enhancedSessionDetail.statistics?.uploaded_count || 0 }}</div>
            </div>
            <div class="asmr-preview-stat rounded-lg p-3">
              <div class="asmr-muted-text text-xs">成功/失败/MD5失败</div>
              <div class="text-sm font-medium mt-0.5">
                <span class="asmr-success-text">{{ enhancedSessionDetail.statistics?.success_count || 0 }}</span>
                <span class="asmr-muted-text mx-1">/</span>
                <span class="asmr-danger-text">{{ enhancedSessionDetail.statistics?.failed_count || 0 }}</span>
                <span class="asmr-muted-text mx-1">/</span>
                <span class="asmr-warning-text">{{ enhancedSessionDetail.statistics?.verify_summary?.failed || 0 }}</span>
              </div>
            </div>
          </div>

          <el-table v-if="enhancedSessionDetail.resources?.length" :data="enhancedSessionDetail.resources" max-height="420" size="small">
            <el-table-column prop="file_name" label="文件" min-width="240" show-overflow-tooltip />
            <el-table-column prop="resource_type" label="类型" width="90" />
            <el-table-column prop="download_status" label="下载" width="100" />
            <el-table-column prop="verify_status" label="校验" width="100" />
            <el-table-column prop="upload_status" label="上传" width="100" />
            <el-table-column label="匹配依据" min-width="180">
              <template #default="{ row }">{{ row.extra_metadata?.match_basis?.join(' / ') || '-' }}</template>
            </el-table-column>
            <el-table-column prop="upload_path" label="上传目标" min-width="220" show-overflow-tooltip />
            <el-table-column prop="last_error" label="异常" min-width="180" show-overflow-tooltip />
          </el-table>
          <AppEmptyState v-else description="暂无资源详情" size="sm" />
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Search,
  Download as DownloadIcon,
  Folder as FolderIcon,
  RefreshCw,
  FolderSearch,
  Clock,
  AlertTriangle,
  FileText,
  File as FileIcon,
  Sparkles,
  ListChecks,
  Database,
  Package,
  CloudDownload,
  Upload,
  Activity,
  Hourglass,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-vue-next'
import { asmrSyncApi, baiduNetdiskApi, configApi, httpDownloadApi, libraryApi, taskApi, taskCenterApi } from '../api'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { useViewport } from '../composables/useViewport'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import BackgroundFloatingCard from '../components/common/BackgroundFloatingCard.vue'
import DownloadTaskWorkbenchDialog from '../components/download/DownloadTaskWorkbenchDialog.vue'
import CircleDownloadPreviewDialog from '../components/circle/CircleDownloadPreviewDialog.vue'
import AsmrEnhancedDownloadPanel from '../components/asmr/AsmrEnhancedDownloadPanel.vue'
import BaiduNetdiskPanel from '../components/asmr/BaiduNetdiskPanel.vue'
import HttpDownloadPanel from '../components/asmr/HttpDownloadPanel.vue'
import AsmrSubtitleScanPanel from '../components/asmr/AsmrSubtitleScanPanel.vue'
import {
  createLatestRequestGuard,
  mergeTrackedDownloadTaskIds,
  replaceTrackedDownloadTaskId,
  selectTrackedDownloadTasks,
} from './_downloadWorkbenchTracking.js'

const { isMobile: isMobileViewport } = useViewport()
const route = useRoute()
const router = useRouter()

const ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.asmrSync.downloadWorkbench'
const ASMR_SYNC_HTTP_DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.asmrSync.httpDownloadWorkbench'
const ASMR_SYNC_BAIDU_NETDISK_WORKBENCH_KEY = 'kikoerumanager.asmrSync.baiduNetdiskWorkbench'
const ASMR_SYNC_HTTP_DOWNLOAD_DRAFT_KEY = 'kikoerumanager.asmrSync.httpDownloadDraft'
const ASMR_SYNC_BAIDU_NETDISK_DRAFT_KEY = 'kikoerumanager.asmrSync.baiduNetdiskDraft'
const ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_VERSION = 3
const ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_TTL_MS = 30 * 60 * 1000
const ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_SESSION_ID = getDownloadPreviewCacheSessionId()
const ASMR_SYNC_STATUS_POLL_MS = 3000
const ASMR_SYNC_STATUS_POLL_MAX_MS = 120000

function getDownloadPreviewCacheSessionId() {
  const key = '__KIKOERUMANAGER_DOWNLOAD_PREVIEW_CACHE_SESSION_ID__'
  if (typeof window === 'undefined') return 'server'
  if (!window[key]) window[key] = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return window[key]
}

function normalizeDownloadDraft(value = {}) {
  const policy = String(value?.conflictPolicy || '').trim()
  return {
    urlText: String(value?.urlText || ''),
    targetSubdir: String(value?.targetSubdir || ''),
    outputFolderName: String(value?.outputFolderName || ''),
    batchName: String(value?.batchName || ''),
    conflictPolicy: ['resume', 'rename', 'skip'].includes(policy) ? policy : 'resume',
    previewCache: normalizeDownloadPreviewCache(value?.previewCache)
  }
}

function normalizeDownloadPreviewCache(value = {}) {
  if (!value || typeof value !== 'object') return null
  if (Number(value.version || 0) !== ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_VERSION) return null
  if (String(value.sessionId || '') !== ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_SESSION_ID) return null
  const cachedAt = Number(value.cachedAt || 0)
  if (!Number.isFinite(cachedAt) || cachedAt <= 0) return null
  const age = Date.now() - cachedAt
  if (age < -60 * 1000 || age > ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_TTL_MS) return null
  const items = Array.isArray(value.items) ? value.items.filter(item => item && typeof item === 'object') : []
  if (!items.length) return null
  return {
    version: ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_VERSION,
    sessionId: ASMR_SYNC_DOWNLOAD_PREVIEW_CACHE_SESSION_ID,
    provider: String(value.provider || ''),
    inputSignature: String(value.inputSignature || ''),
    items,
    selectedKeys: Array.isArray(value.selectedKeys) ? value.selectedKeys.map(key => String(key || '')).filter(Boolean) : [],
    needsMaterialize: Boolean(value.needsMaterialize),
    logs: Array.isArray(value.logs) ? value.logs.slice(-80) : [],
    progress: Number(value.progress || 100),
    expandedKeys: Array.isArray(value.expandedKeys) ? value.expandedKeys.map(key => String(key || '')).filter(Boolean) : [],
    cachedAt,
  }
}

function readDownloadDraft(key) {
  try {
    if (typeof window === 'undefined') return normalizeDownloadDraft()
    return normalizeDownloadDraft(JSON.parse(window.sessionStorage.getItem(key) || '{}'))
  } catch (_) {
    return normalizeDownloadDraft()
  }
}

function persistDownloadDraft(key, value) {
  try {
    if (typeof window === 'undefined') return
    const draft = normalizeDownloadDraft(value)
    const hasDraft = Boolean(
      draft.urlText
      || draft.targetSubdir
      || draft.outputFolderName
      || draft.batchName
      || draft.conflictPolicy !== 'resume'
      || draft.previewCache
    )
    if (hasDraft) window.sessionStorage.setItem(key, JSON.stringify(draft))
    else window.sessionStorage.removeItem(key)
  } catch (_) {}
}

const subtitleFolder = ref('')
const scanning = ref(false)
const syncing = ref(false)
const refreshing = ref(false)
const scanResults = ref([])
const selectedItems = ref([])
const selectAll = ref(false)
const previewDialogVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref(null)
const tasks = ref([])
const nextRetryTime = ref('')
const enhancedInput = ref('')
const enhancedFolderPath = ref('')
const enhancedPlanning = ref(false)
const enhancedStarting = ref(false)
const enhancedDashboardLoading = ref(false)
const enhancedSessionsLoading = ref(false)
const enhancedSessionDrawerVisible = ref(false)
const enhancedSessionDetailLoading = ref(false)
const enhancedSessionDetail = ref(null)
const enhancedPlans = ref([])
const enhancedSessions = ref([])
const selectedPlanSet = ref(new Set())
const normalizeWorkspaceTab = (value) => {
  const tab = String(value || '').trim().toLowerCase()
  return ['enhanced', 'http', 'baidu', 'subtitle'].includes(tab) ? tab : 'enhanced'
}
const activeWorkspaceTab = ref(normalizeWorkspaceTab(route.query?.tab))
const enhancedDownloadWorkbenchTaskIds = ref([])
const enhancedDownloadWorkbenchTasks = ref([])
const enhancedDownloadWorkbenchVisible = ref(false)
const enhancedDownloadWorkbenchBackgroundActive = ref(false)
const enhancedDownloadWorkbenchRefreshing = ref(false)
const enhancedRetryingTaskIds = ref(new Set())
const enhancedRetryingSessionIds = ref(new Set())
const enhancedActiveRetryScopes = new Map()
const enhancedRetryReleaseTimers = new Set()
let enhancedDownloadWorkbenchTimer = null
const enhancedDownloadWorkbenchRequestGuard = createLatestRequestGuard()
const httpDownloadWorkbenchTaskIds = ref([])
const httpDownloadWorkbenchTasks = ref([])
const httpDownloadWorkbenchVisible = ref(false)
const httpDownloadWorkbenchBackgroundActive = ref(false)
const httpDownloadWorkbenchRefreshing = ref(false)
const httpDownloadRetryingTaskIds = ref(new Set())
const httpDownloadDraft = ref(readDownloadDraft(ASMR_SYNC_HTTP_DOWNLOAD_DRAFT_KEY))
let httpDownloadWorkbenchTimer = null
const httpDownloadWorkbenchRequestGuard = createLatestRequestGuard()
const baiduNetdiskWorkbenchTaskIds = ref([])
const baiduNetdiskWorkbenchTasks = ref([])
const baiduNetdiskWorkbenchVisible = ref(false)
const baiduNetdiskWorkbenchBackgroundActive = ref(false)
const baiduNetdiskWorkbenchRefreshing = ref(false)
const baiduNetdiskRetryingTaskIds = ref(new Set())
const baiduNetdiskDraft = ref(readDownloadDraft(ASMR_SYNC_BAIDU_NETDISK_DRAFT_KEY))
let baiduNetdiskWorkbenchTimer = null
const baiduNetdiskWorkbenchRequestGuard = createLatestRequestGuard()

// Enhanced preview dialog state
const enhancedPreviewVisible = ref(false)
const previewStarting = ref(false)
const previewPlans = ref([])
const libraries = ref([])
const downloadSettings = ref({
  mode: 'classify',
  targetLibraryId: '',
  targetSubdir: '',
  namingMode: 'api',
  classifyMode: 'none',
  downloadBasePath: '',
  directLibraryId: '',
  directBasePath: '',
  directLibraryType: '',
  directSubPath: ''
})
const existingRJPaths = ref({})
const locatingRJ = ref(false)
const enhancedDashboard = ref({
  total_rj: 0,
  total_resources: 0,
  downloaded_resources: 0,
  uploaded_resources: 0,
  processing_tasks: 0,
  pending_tasks: 0,
  failed_tasks: 0
})
const enhancedFilters = ref({
  resourceTypes: ['audio', 'subtitle', 'cover'],
  audioFormats: [],
  subtitleLanguages: [],
  includeExisting: false
})
const enhancedUpload = ref({
  mode: 'disabled',
  targetPath: '',
  libraryId: ''
})
let statusInterval = null
let statusFailureCount = 0
let asmrSyncInitialized = false
let asmrSyncViewActive = false

// 计算属性：分离等待重试的任务和活动任务
const waitingRetryTasks = computed(() => {
  return tasks.value.filter(t => t.status === 'waiting_retry')
})

const activeTasks = computed(() => {
  return tasks.value.filter(t => t.status !== 'waiting_retry')
})

const enhancedMetricCards = computed(() => {
  const dashboard = enhancedDashboard.value || {}
  return [
    {
      label: '已建档 RJ',
      value: dashboard.total_rj || 0,
      help: '资源库中已记录的作品数',
      icon: Database,
      iconClass: 'asmr-metric-icon-info',
    },
    {
      label: '资源条目',
      value: dashboard.total_resources || 0,
      help: '已抓取并落库的远端资源',
      icon: Package,
      iconClass: 'asmr-metric-icon-info',
    },
    {
      label: '已下载',
      value: dashboard.downloaded_resources || 0,
      help: '已完成下载的文件数',
      icon: CloudDownload,
      iconClass: 'asmr-metric-icon-success',
    },
    {
      label: '已上传',
      value: dashboard.uploaded_resources || 0,
      help: '已进入自动上传管道的文件数',
      icon: Upload,
      iconClass: 'asmr-metric-icon-info',
    },
    {
      label: '处理中',
      value: dashboard.processing_tasks || 0,
      help: '当前运行中的增强下载任务',
      icon: Activity,
      iconClass: 'asmr-metric-icon-warning',
    },
    {
      label: '待处理 / 失败',
      value: `${dashboard.pending_tasks || 0} / ${dashboard.failed_tasks || 0}`,
      help: '当前排队与失败任务概况',
      icon: Hourglass,
      iconClass: 'asmr-metric-icon-danger',
    },
  ]
})

const hasEnhancedSelections = computed(() => {
  return enhancedPlans.value.some(plan => (plan.selectable_resources || []).some(item => item.selected))
})

const selectedPlanRjcodes = computed(() => [...selectedPlanSet.value])
const workspaceTabs = computed(() => [
  {
    key: 'enhanced',
    label: 'RJ 增强下载',
    icon: Sparkles,
    badge: selectedPlanRjcodes.value.length ? String(selectedPlanRjcodes.value.length) : ''
  },
  {
    key: 'http',
    label: 'HTTP 外链下载',
    icon: CloudDownload,
    badge: httpDownloadWorkbenchTaskIds.value.length ? String(httpDownloadWorkbenchTaskIds.value.length) : ''
  },
  {
    key: 'baidu',
    label: '百度网盘下载',
    icon: CloudDownload,
    badge: baiduNetdiskWorkbenchTaskIds.value.length ? String(baiduNetdiskWorkbenchTaskIds.value.length) : ''
  },
  {
    key: 'subtitle',
    label: '字幕扫描',
    icon: FolderSearch,
    badge: scanResults.value.length ? String(scanResults.value.length) : ''
  }
])
const enhancedProcessingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'processing'))
const enhancedPendingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => ['pending', 'paused', 'waiting_retry'].includes(String(t.status || ''))))
const enhancedCompletedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'completed' && String(t.display_status || '') !== 'partial_failed'))
const enhancedFailedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => ['failed', 'partial_failed'].includes(String(t.display_status || t.status || ''))))
const showEnhancedDownloadBackgroundCard = computed(() => enhancedDownloadWorkbenchBackgroundActive.value && !enhancedDownloadWorkbenchVisible.value && enhancedDownloadWorkbenchTaskIds.value.length > 0)
const enhancedActiveBackgroundTask = computed(() => enhancedProcessingTasks.value[0] || enhancedPendingTasks.value[0] || enhancedDownloadWorkbenchTasks.value[0] || null)
const enhancedBackgroundPercent = computed(() => {
  if (!enhancedDownloadWorkbenchTasks.value.length) return 0
  const stats = enhancedDownloadWorkbenchTasks.value.reduce((summary, task) => {
    const runtime = getDownloadRuntime(task)
    const files = Array.isArray(task?.download_files) ? task.download_files : []
    const total = Number(runtime?.total_bytes || 0) || files.reduce((sum, file) => sum + Number(file?.total || file?.size_bytes || file?.size || 0), 0)
    const transferred = Number(runtime?.transferred_bytes || 0) || files.reduce((sum, file) => sum + Number(file?.downloaded || 0), 0)
    return {
      total: summary.total + Math.max(0, total),
      transferred: summary.transferred + Math.min(Math.max(0, transferred), Math.max(0, total)),
    }
  }, { total: 0, transferred: 0 })
  if (stats.total > 0) {
    return Math.max(0, Math.min(100, Math.round(stats.transferred / stats.total * 100)))
  }
  const total = enhancedDownloadWorkbenchTasks.value.reduce((sum, t) => sum + Number(t.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / enhancedDownloadWorkbenchTasks.value.length)))
})
const enhancedBackgroundCompleted = computed(() => (
  enhancedDownloadWorkbenchTasks.value.length > 0
  && enhancedCompletedTasks.value.length === enhancedDownloadWorkbenchTasks.value.length
  && enhancedFailedTasks.value.length === 0
))
const enhancedBackgroundFailed = computed(() => (
  enhancedFailedTasks.value.length > 0
  && enhancedProcessingTasks.value.length === 0
  && enhancedPendingTasks.value.length === 0
))
const enhancedBackgroundMetaText = computed(() => backgroundDownloadMetaText(enhancedBackgroundPercent.value, enhancedProcessingTasks.value, enhancedActiveBackgroundTask.value, enhancedBackgroundFailed.value))
const enhancedDownloadBackgroundCardProps = computed(() => ({
  kind: 'asmr',
  tone: enhancedBackgroundFailed.value ? 'amber' : 'violet',
  title: enhancedBackgroundCompleted.value
    ? 'ASMR 增强下载已完成'
    : enhancedBackgroundFailed.value
      ? 'ASMR 增强下载需要处理'
      : 'ASMR 增强下载正在后台运行',
  badgeText: `下载 ${enhancedDownloadWorkbenchTasks.value.length} 项`,
  subtitle: enhancedActiveBackgroundTask.value
    ? `${enhancedActiveBackgroundTask.value.rjcode || 'RJ'} · ${enhancedActiveBackgroundTask.value.work_title || '-'}`
    : '保留下载队列与进度',
  metaText: enhancedBackgroundMetaText.value,
  percentage: enhancedBackgroundPercent.value,
  completed: enhancedBackgroundCompleted.value,
  metrics: [
    { key: 'processing', label: '进行中', value: enhancedProcessingTasks.value.length, tone: 'info' },
    { key: 'pending', label: '等待中', value: enhancedPendingTasks.value.length, tone: 'warning' },
    { key: 'completed', label: '完成', value: enhancedCompletedTasks.value.length, tone: 'success' },
    { key: 'failed', label: '失败', value: enhancedFailedTasks.value.length, tone: enhancedFailedTasks.value.length ? 'danger' : 'neutral' }
  ],
  detailText: enhancedActiveBackgroundTask.value?.current_step || '隐藏后继续保留增强下载队列和进度。',
  actions: [
    { key: 'close', label: '关闭' },
    { key: 'resume', label: '恢复工作台', variant: 'violet' }
  ]
}))

const httpDownloadProcessingTasks = computed(() => httpDownloadWorkbenchTasks.value.filter(t => t.status === 'processing'))
const httpDownloadPendingTasks = computed(() => httpDownloadWorkbenchTasks.value.filter(t => ['pending', 'paused', 'waiting_retry'].includes(String(t.status || ''))))
const httpDownloadCompletedTasks = computed(() => httpDownloadWorkbenchTasks.value.filter(t => t.status === 'completed' && String(t.display_status || '') !== 'partial_failed'))
const httpDownloadFailedTasks = computed(() => httpDownloadWorkbenchTasks.value.filter(t => ['failed', 'partial_failed'].includes(String(t.display_status || t.status || ''))))
const showHttpDownloadBackgroundCard = computed(() => httpDownloadWorkbenchBackgroundActive.value && !httpDownloadWorkbenchVisible.value && httpDownloadWorkbenchTaskIds.value.length > 0)
const httpDownloadActiveBackgroundTask = computed(() => httpDownloadProcessingTasks.value[0] || httpDownloadPendingTasks.value[0] || httpDownloadWorkbenchTasks.value[0] || null)
const httpDownloadBackgroundPercent = computed(() => {
  if (!httpDownloadWorkbenchTasks.value.length) return 0
  const total = httpDownloadWorkbenchTasks.value.reduce((sum, t) => sum + Number(t.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / httpDownloadWorkbenchTasks.value.length)))
})
const httpDownloadBackgroundCompleted = computed(() => (
  httpDownloadWorkbenchTasks.value.length > 0
  && httpDownloadCompletedTasks.value.length === httpDownloadWorkbenchTasks.value.length
  && httpDownloadFailedTasks.value.length === 0
))
const httpDownloadBackgroundFailed = computed(() => (
  httpDownloadFailedTasks.value.length > 0
  && httpDownloadProcessingTasks.value.length === 0
  && httpDownloadPendingTasks.value.length === 0
))
const httpDownloadBackgroundMetaText = computed(() => backgroundDownloadMetaText(httpDownloadBackgroundPercent.value, httpDownloadProcessingTasks.value, httpDownloadActiveBackgroundTask.value, httpDownloadBackgroundFailed.value))
const httpDownloadBackgroundCardProps = computed(() => ({
  kind: 'download',
  tone: httpDownloadBackgroundFailed.value ? 'amber' : 'blue',
  title: httpDownloadBackgroundCompleted.value
    ? 'HTTP 外链下载已完成'
    : httpDownloadBackgroundFailed.value
      ? 'HTTP 外链下载需要处理'
      : 'HTTP 外链下载正在后台运行',
  badgeText: `下载 ${httpDownloadWorkbenchTasks.value.length} 项`,
  subtitle: httpDownloadActiveBackgroundTask.value
    ? `${httpDownloadActiveBackgroundTask.value.work_title || httpDownloadActiveBackgroundTask.value.source_label || 'HTTP 下载'}`
    : '保留 aria2 下载队列与进度',
  metaText: httpDownloadBackgroundMetaText.value,
  percentage: httpDownloadBackgroundPercent.value,
  completed: httpDownloadBackgroundCompleted.value,
  metrics: [
    { key: 'processing', label: '进行中', value: httpDownloadProcessingTasks.value.length, tone: 'info' },
    { key: 'pending', label: '等待中', value: httpDownloadPendingTasks.value.length, tone: 'warning' },
    { key: 'completed', label: '完成', value: httpDownloadCompletedTasks.value.length, tone: 'success' },
    { key: 'failed', label: '失败', value: httpDownloadFailedTasks.value.length, tone: httpDownloadFailedTasks.value.length ? 'danger' : 'neutral' }
  ],
  detailText: httpDownloadBackgroundFailed.value
    ? (httpDownloadActiveBackgroundTask.value?.failure_reason || httpDownloadActiveBackgroundTask.value?.current_step || '下载失败，需要打开工作台处理。')
    : (httpDownloadActiveBackgroundTask.value?.current_step || '隐藏后继续保留 HTTP 下载队列和进度。'),
  actions: [
    { key: 'close', label: '关闭' },
    { key: 'resume', label: '恢复工作台', variant: 'blue' }
  ]
}))

const baiduNetdiskProcessingTasks = computed(() => baiduNetdiskWorkbenchTasks.value.filter(t => t.status === 'processing'))
const baiduNetdiskPendingTasks = computed(() => baiduNetdiskWorkbenchTasks.value.filter(t => ['pending', 'paused', 'waiting_retry'].includes(String(t.status || ''))))
const baiduNetdiskCompletedTasks = computed(() => baiduNetdiskWorkbenchTasks.value.filter(t => t.status === 'completed' && String(t.display_status || '') !== 'partial_failed'))
const baiduNetdiskFailedTasks = computed(() => baiduNetdiskWorkbenchTasks.value.filter(t => ['failed', 'partial_failed'].includes(String(t.display_status || t.status || ''))))
const showBaiduNetdiskBackgroundCard = computed(() => baiduNetdiskWorkbenchBackgroundActive.value && !baiduNetdiskWorkbenchVisible.value && baiduNetdiskWorkbenchTaskIds.value.length > 0)
const baiduNetdiskActiveBackgroundTask = computed(() => baiduNetdiskProcessingTasks.value[0] || baiduNetdiskPendingTasks.value[0] || baiduNetdiskWorkbenchTasks.value[0] || null)
const baiduNetdiskBackgroundPercent = computed(() => {
  if (!baiduNetdiskWorkbenchTasks.value.length) return 0
  const total = baiduNetdiskWorkbenchTasks.value.reduce((sum, t) => sum + Number(t.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / baiduNetdiskWorkbenchTasks.value.length)))
})
const baiduNetdiskBackgroundCompleted = computed(() => (
  baiduNetdiskWorkbenchTasks.value.length > 0
  && baiduNetdiskCompletedTasks.value.length === baiduNetdiskWorkbenchTasks.value.length
  && baiduNetdiskFailedTasks.value.length === 0
))
const baiduNetdiskBackgroundFailed = computed(() => (
  baiduNetdiskFailedTasks.value.length > 0
  && baiduNetdiskProcessingTasks.value.length === 0
  && baiduNetdiskPendingTasks.value.length === 0
))
const baiduNetdiskBackgroundMetaText = computed(() => backgroundDownloadMetaText(baiduNetdiskBackgroundPercent.value, baiduNetdiskProcessingTasks.value, baiduNetdiskActiveBackgroundTask.value, baiduNetdiskBackgroundFailed.value))
const baiduNetdiskBackgroundCardProps = computed(() => ({
  kind: 'download',
  tone: baiduNetdiskBackgroundFailed.value ? 'amber' : 'blue',
  title: baiduNetdiskBackgroundCompleted.value
    ? '百度网盘下载已完成'
    : baiduNetdiskBackgroundFailed.value
      ? '百度网盘下载需要处理'
      : '百度网盘下载正在后台运行',
  badgeText: `下载 ${baiduNetdiskWorkbenchTasks.value.length} 项`,
  subtitle: baiduNetdiskActiveBackgroundTask.value
    ? `${baiduNetdiskActiveBackgroundTask.value.work_title || baiduNetdiskActiveBackgroundTask.value.source_label || '百度网盘下载'}`
    : '保留百度网盘直下队列与进度',
  metaText: baiduNetdiskBackgroundMetaText.value,
  percentage: baiduNetdiskBackgroundPercent.value,
  completed: baiduNetdiskBackgroundCompleted.value,
  metrics: [
    { key: 'processing', label: '进行中', value: baiduNetdiskProcessingTasks.value.length, tone: 'info' },
    { key: 'pending', label: '等待中', value: baiduNetdiskPendingTasks.value.length, tone: 'warning' },
    { key: 'completed', label: '完成', value: baiduNetdiskCompletedTasks.value.length, tone: 'success' },
    { key: 'failed', label: '失败', value: baiduNetdiskFailedTasks.value.length, tone: baiduNetdiskFailedTasks.value.length ? 'danger' : 'neutral' }
  ],
  detailText: baiduNetdiskBackgroundFailed.value
    ? (baiduNetdiskActiveBackgroundTask.value?.failure_reason || baiduNetdiskActiveBackgroundTask.value?.current_step || '下载失败，需要打开工作台处理。')
    : (baiduNetdiskActiveBackgroundTask.value?.current_step || '隐藏后继续保留百度网盘下载队列和进度。'),
  actions: [
    { key: 'close', label: '关闭' },
    { key: 'resume', label: '恢复工作台', variant: 'blue' }
  ]
}))

const activeBackgroundFloatingCardIndex = ref(0)
const backgroundFloatingCardDirection = ref(1)
const visibleBackgroundFloatingCards = computed(() => {
  const cards = []
  if (showBaiduNetdiskBackgroundCard.value) {
    cards.push({
      id: 'baidu-netdisk',
      label: '百度网盘下载',
      props: baiduNetdiskBackgroundCardProps.value,
      onAction: handleBaiduNetdiskBackgroundCardAction
    })
  }
  if (showHttpDownloadBackgroundCard.value) {
    cards.push({
      id: 'http-download',
      label: 'HTTP 外链下载',
      props: httpDownloadBackgroundCardProps.value,
      onAction: handleHttpDownloadBackgroundCardAction
    })
  }
  if (showEnhancedDownloadBackgroundCard.value) {
    cards.push({
      id: 'enhanced-download',
      label: 'ASMR 增强下载',
      props: enhancedDownloadBackgroundCardProps.value,
      onAction: handleEnhancedDownloadBackgroundCardAction
    })
  }
  return cards
})
const activeBackgroundFloatingCard = computed(() => visibleBackgroundFloatingCards.value[activeBackgroundFloatingCardIndex.value] || visibleBackgroundFloatingCards.value[0] || null)
const backgroundFloatingCardTransitionName = computed(() => (
  backgroundFloatingCardDirection.value >= 0
    ? 'asmr-floating-card-page-next'
    : 'asmr-floating-card-page-prev'
))

function setBackgroundFloatingCardIndex(index) {
  const cards = visibleBackgroundFloatingCards.value
  if (!cards.length) return
  const nextIndex = Math.max(0, Math.min(cards.length - 1, Number(index || 0)))
  if (nextIndex === activeBackgroundFloatingCardIndex.value) return
  backgroundFloatingCardDirection.value = nextIndex > activeBackgroundFloatingCardIndex.value ? 1 : -1
  activeBackgroundFloatingCardIndex.value = nextIndex
}

function switchBackgroundFloatingCard(step) {
  const cards = visibleBackgroundFloatingCards.value
  if (cards.length <= 1) return
  const direction = Number(step || 1) >= 0 ? 1 : -1
  backgroundFloatingCardDirection.value = direction
  activeBackgroundFloatingCardIndex.value = (activeBackgroundFloatingCardIndex.value + direction + cards.length) % cards.length
}

function handleVisibleBackgroundFloatingCardAction(action) {
  activeBackgroundFloatingCard.value?.onAction?.(action)
}

watch(visibleBackgroundFloatingCards, (cards, previousCards = []) => {
  if (!cards.length) {
    activeBackgroundFloatingCardIndex.value = 0
    return
  }
  const activeId = previousCards[activeBackgroundFloatingCardIndex.value]?.id
  const nextIndex = activeId ? cards.findIndex(card => card.id === activeId) : -1
  activeBackgroundFloatingCardIndex.value = nextIndex >= 0
    ? nextIndex
    : Math.min(activeBackgroundFloatingCardIndex.value, cards.length - 1)
}, { flush: 'sync' })

// 格式化下次重试时间
const formatNextRetryTime = (isoString) => {
  if (!isoString) return '未知'
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = date - now
  if (diffMs <= 0) return '即将重试'

  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffDays > 0) {
    return `${diffDays}天${diffHours % 24}小时后`
  } else if (diffHours > 0) {
    return `${diffHours}小时${diffMins % 60}分钟后`
  } else {
    return `${diffMins}分钟后`
  }
}

const getLangName = (lang) => {
  const map = { 'CHI_HANS': '简中', 'CHI_SIMP': '简中', 'CHI_HANT': '繁中', 'CHI_TRAD': '繁中', 'JPN': '日文', 'JAP': '日文', 'ENG': '英文' }
  return map[lang] || lang
}

const getStatusText = (status) => {
  const map = { 'pending': '等待中', 'processing': '处理中', 'completed': '已完成', 'failed': '失败', 'paused': '已暂停', 'waiting_retry': '等待重试' }
  return map[status] || status
}

const getResourceTypeLabel = (type) => {
  const map = { audio: '音频', subtitle: '字幕', cover: '图片', other: '其他' }
  return map[type] || type || '资源'
}

const parseEnhancedRJCodes = () => {
  return [...new Set(
    (enhancedInput.value || '')
      .split(/[\s,，;；]+/)
      .map(item => item.trim().toUpperCase())
      .filter(Boolean)
  )]
}

const getSelectedResourceCount = (plan) => {
  return (plan?.selectable_resources || []).filter(item => item.selected).length
}

const summarizePlanResources = (resources = []) => {
  const summary = {}
  for (const item of Array.isArray(resources) ? resources : []) {
    const key = getResourceTypeLabel(item?.resource_type)
    summary[key] = (summary[key] || 0) + 1
  }
  return Object.entries(summary)
    .map(([label, count]) => `${label} ${count}`)
    .join(' / ')
}

const getUploadModeLabel = (mode) => {
  const map = { disabled: '仅下载', local: '本地复制', synology: '群晖上传' }
  return map[mode] || mode || '未设置'
}

const getSessionStatusLabel = (status) => {
  const map = {
    planning: '规划中',
    queued: '排队中',
    downloading: '下载中',
    verifying: '校验中',
    uploading: '上传中',
    completed: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    paused: '已暂停'
  }
  return map[status] || status || '未知'
}

const togglePlanSelection = (plan, checked) => {
  ;(plan.selectable_resources || []).forEach(item => {
    item.selected = Boolean(checked)
  })
}

const applyPlanPreset = (plan, presetKey) => {
  const preset = new Set(plan?.selection_presets?.[presetKey] || [])
  ;(plan.selectable_resources || []).forEach(item => {
    item.selected = preset.has(item.relative_path)
  })
}

const loadEnhancedDashboard = async () => {
  enhancedDashboardLoading.value = true
  try {
    const result = await asmrSyncApi.dashboardEnhanced()
    enhancedDashboard.value = result.dashboard || enhancedDashboard.value
  } catch (error) {
    console.error('加载增强看板失败:', error)
  } finally {
    enhancedDashboardLoading.value = false
  }
}

const loadEnhancedSessions = async () => {
  enhancedSessionsLoading.value = true
  try {
    const result = await asmrSyncApi.sessionsEnhanced()
    enhancedSessions.value = result.sessions || []
  } catch (error) {
    console.error('加载增强会话失败:', error)
  } finally {
    enhancedSessionsLoading.value = false
  }
}

const buildEnhancedPlans = async () => {
  const rjcodes = parseEnhancedRJCodes()
  if (rjcodes.length === 0) return ElMessage.warning('请先输入至少一个 RJ 号')
  enhancedPlanning.value = true
  try {
    const result = await asmrSyncApi.planEnhanced({
      rjcodes,
      folder_path: '',
      resource_types: ['audio', 'subtitle', 'cover'],
      audio_formats: [],
      subtitle_languages: [],
      include_existing: false
    })
    enhancedPlans.value = (result.plans || []).map(plan => ({
      ...plan,
      selectable_resources: (plan.selectable_resources || []).map(item => ({
        ...item,
        selected: item.selected !== false
      }))
    }))
    if (result.errors?.length) {
      ElMessage.warning(`已生成 ${result.planned_count} 个计划，${result.errors.length} 个 RJ 失败`)
    } else {
      ElMessage.success(`已生成 ${result.planned_count} 个增强下载计划`)
    }
    await loadEnhancedDashboard()
    // Auto-select all plans after query
    selectedPlanSet.value = new Set(enhancedPlans.value.map(p => p.rjcode))
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '生成下载计划失败')
  } finally {
    enhancedPlanning.value = false
  }
}

function togglePlanSelect(rjcode) {
  const next = new Set(selectedPlanSet.value)
  if (next.has(rjcode)) next.delete(rjcode)
  else next.add(rjcode)
  selectedPlanSet.value = next
}

function selectAllPlans() {
  selectedPlanSet.value = new Set(enhancedPlans.value.map(p => p.rjcode))
}

function clearPlanSelection() {
  selectedPlanSet.value = new Set()
}

async function loadLibraries() {
  try {
    const result = await libraryApi.listLibraries()
    libraries.value = result.libraries || result || []
  } catch { /* ignore */ }
}

async function openEnhancedPreview() {
  const selectedRjs = selectedPlanSet.value
  const plans = enhancedPlans.value.filter(plan => selectedRjs.has(plan.rjcode))
  if (!plans.length) return ElMessage.warning('请先选中至少一个计划')
  previewPlans.value = plans
  enhancedPreviewVisible.value = true
  loadLibraries()
  loadExistingRJPaths(plans.map(plan => plan.rjcode))
}

async function loadExistingRJPaths(rjcodes) {
  const list = Array.from(new Set((rjcodes || []).map(rj => String(rj || '').trim().toUpperCase()).filter(Boolean)))
  if (!list.length) {
    existingRJPaths.value = {}
    return
  }
  locatingRJ.value = true
  try {
    const data = await asmrSyncApi.locateRJ(list)
    const map = {}
    ;(data?.results || []).forEach(item => {
      const rj = String(item?.rjcode || '').toUpperCase()
      if (!rj) return
      map[rj] = { matches: Array.isArray(item?.matches) ? item.matches : [] }
    })
    existingRJPaths.value = map
  } catch (error) {
    console.error('locate-rj 失败:', error)
    existingRJPaths.value = {}
  } finally {
    locatingRJ.value = false
  }
}

async function handlePreviewSubmit(payload) {
  const items = Array.isArray(payload.items) ? payload.items : []
  if (!items.length) return ElMessage.warning('没有选中任何文件')
  previewStarting.value = true
  enhancedStarting.value = true
  try {
    const result = await asmrSyncApi.startEnhanced(items)
    const newTaskIds = (result.tasks || []).map(t => t.task_id).filter(Boolean)
    enhancedDownloadWorkbenchTaskIds.value = [
      ...newTaskIds,
      ...enhancedDownloadWorkbenchTaskIds.value.filter(id => !newTaskIds.includes(id))
    ]
    enhancedDownloadWorkbenchVisible.value = newTaskIds.length > 0
    enhancedDownloadWorkbenchBackgroundActive.value = false
    persistEnhancedDownloadWorkbenchState()
    await refreshEnhancedDownloadWorkbench()
    ElMessage.success(result.message || '增强下载任务已创建')
    enhancedPreviewVisible.value = false
    await refreshStatus()
    await loadEnhancedSessions()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动增强下载失败')
  } finally {
    enhancedStarting.value = false
    previewStarting.value = false
  }
}

// --- Enhanced Download Workbench Management ---

function persistEnhancedDownloadWorkbenchState() {
  try {
    localStorage.setItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: enhancedDownloadWorkbenchTaskIds.value,
      visible: enhancedDownloadWorkbenchVisible.value,
      background: enhancedDownloadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function hydrateEnhancedDownloadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY) || '{}')
    enhancedDownloadWorkbenchTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    enhancedDownloadWorkbenchVisible.value = Boolean(raw.visible && enhancedDownloadWorkbenchTaskIds.value.length)
    enhancedDownloadWorkbenchBackgroundActive.value = Boolean(raw.background && enhancedDownloadWorkbenchTaskIds.value.length)
  } catch (_) {
    enhancedDownloadWorkbenchTaskIds.value = []
    enhancedDownloadWorkbenchVisible.value = false
    enhancedDownloadWorkbenchBackgroundActive.value = false
  }
}

function clearEnhancedDownloadWorkbenchState() {
  enhancedDownloadWorkbenchRequestGuard.invalidate()
  enhancedDownloadWorkbenchTaskIds.value = []
  enhancedDownloadWorkbenchTasks.value = []
  enhancedDownloadWorkbenchVisible.value = false
  enhancedDownloadWorkbenchBackgroundActive.value = false
  stopEnhancedDownloadWorkbenchPolling()
  try { localStorage.removeItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY) } catch (_) {}
}

function stopEnhancedDownloadWorkbenchPolling() {
  if (enhancedDownloadWorkbenchTimer) {
    window.clearTimeout(enhancedDownloadWorkbenchTimer)
    enhancedDownloadWorkbenchTimer = null
  }
}

function startEnhancedDownloadWorkbenchPolling() {
  if (!enhancedDownloadWorkbenchTaskIds.value.length) return
  stopEnhancedDownloadWorkbenchPolling()
  enhancedDownloadWorkbenchTimer = window.setTimeout(() => {
    refreshEnhancedDownloadWorkbench()
  }, 2000)
}

async function refreshEnhancedDownloadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  const requestSeq = enhancedDownloadWorkbenchRequestGuard.begin()
  if (!enhancedDownloadWorkbenchTaskIds.value.length) {
    enhancedDownloadWorkbenchTasks.value = []
    stopEnhancedDownloadWorkbenchPolling()
    return
  }
  if (!silent) enhancedDownloadWorkbenchRefreshing.value = true
  try {
    const result = await asmrSyncApi.status([], { compact: true })
    if (!enhancedDownloadWorkbenchRequestGuard.isLatest(requestSeq)) return
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    enhancedDownloadWorkbenchTasks.value = mergeWorkbenchTaskRows(enhancedDownloadWorkbenchTasks.value, selectTrackedDownloadTasks(
      enhancedDownloadWorkbenchTaskIds.value,
      allTasks,
    ))
    const stillActive = enhancedDownloadWorkbenchTasks.value.some(t => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(t.status || '')))
    if (stillActive || enhancedDownloadWorkbenchVisible.value || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
    else stopEnhancedDownloadWorkbenchPolling()
  } catch (error) {
    if (!enhancedDownloadWorkbenchRequestGuard.isLatest(requestSeq)) return
    console.error('刷新增强下载工作台失败:', error)
    startEnhancedDownloadWorkbenchPolling()
  } finally {
    if (!silent && enhancedDownloadWorkbenchRequestGuard.isLatest(requestSeq)) enhancedDownloadWorkbenchRefreshing.value = false
  }
}

async function loadFullWorkbenchTaskFiles(task, targetRef) {
  const taskId = String(task?.active_task_id || task?.id || '').trim()
  if (!taskId || !task?.download_files_truncated || !targetRef) return
  const rows = Array.isArray(task.download_files) ? task.download_files : []
  const total = Number(task.download_files_total || rows.length) || rows.length
  if (rows.length >= total) return
  try {
    let offset = rows.length
    const mergedRows = [...rows]
    let result = null
    while (offset < total) {
      result = await taskCenterApi.getItemFiles({ engine_task_id: taskId, offset, limit: 500 })
      const nextRows = Array.isArray(result?.items) ? result.items : []
      if (!nextRows.length) break
      mergedRows.push(...nextRows)
      offset += nextRows.length
      if (!result?.has_more) break
    }
    if (mergedRows.length <= rows.length) return
    const merged = {
      ...task,
      download_files: mergedRows,
      download_files_total: Number(result?.total || total),
      download_files_truncated: Boolean(result?.has_more && offset < total),
    }
    targetRef.value = targetRef.value.map(item => (
      item.id === task.id || item.active_task_id === taskId ? merged : item
    ))
  } catch (error) {
    console.error('加载下载文件明细失败:', error)
  }
}

function mergeWorkbenchTaskRows(previousRows = [], nextRows = []) {
  const previousMap = new Map((previousRows || []).map(task => [String(task?.id || ''), task]))
  return (nextRows || []).map(next => {
    const previous = previousMap.get(String(next?.id || ''))
    if (previous && previous.download_files_truncated === false && next?.download_files_truncated) {
      return {
        ...next,
        download_files: previous.download_files,
        download_files_total: previous.download_files_total,
        download_files_truncated: false,
      }
    }
    return next
  })
}

function hideEnhancedDownloadWorkbenchToBackground() {
  enhancedDownloadWorkbenchVisible.value = false
  enhancedDownloadWorkbenchBackgroundActive.value = true
}

function resumeEnhancedDownloadWorkbench() {
  enhancedDownloadWorkbenchVisible.value = true
  enhancedDownloadWorkbenchBackgroundActive.value = false
}

function closeEnhancedDownloadWorkbench() {
  clearEnhancedDownloadWorkbenchState()
}

function handleEnhancedDownloadBackgroundCardAction(action) {
  if (action === 'resume') {
    resumeEnhancedDownloadWorkbench()
    return
  }
  if (action === 'close') {
    closeEnhancedDownloadWorkbench()
  }
}

// --- HTTP Download Workbench Management ---

function persistHttpDownloadWorkbenchState() {
  try {
    localStorage.setItem(ASMR_SYNC_HTTP_DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: httpDownloadWorkbenchTaskIds.value,
      visible: httpDownloadWorkbenchVisible.value,
      background: httpDownloadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function hydrateHttpDownloadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ASMR_SYNC_HTTP_DOWNLOAD_WORKBENCH_KEY) || '{}')
    httpDownloadWorkbenchTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    httpDownloadWorkbenchVisible.value = Boolean(raw.visible && httpDownloadWorkbenchTaskIds.value.length)
    httpDownloadWorkbenchBackgroundActive.value = Boolean(raw.background && httpDownloadWorkbenchTaskIds.value.length)
  } catch (_) {
    httpDownloadWorkbenchTaskIds.value = []
    httpDownloadWorkbenchVisible.value = false
    httpDownloadWorkbenchBackgroundActive.value = false
  }
}

function clearHttpDownloadWorkbenchState() {
  httpDownloadWorkbenchRequestGuard.invalidate()
  httpDownloadWorkbenchTaskIds.value = []
  httpDownloadWorkbenchTasks.value = []
  httpDownloadWorkbenchVisible.value = false
  httpDownloadWorkbenchBackgroundActive.value = false
  stopHttpDownloadWorkbenchPolling()
  try { localStorage.removeItem(ASMR_SYNC_HTTP_DOWNLOAD_WORKBENCH_KEY) } catch (_) {}
}

function stopHttpDownloadWorkbenchPolling() {
  if (httpDownloadWorkbenchTimer) {
    window.clearTimeout(httpDownloadWorkbenchTimer)
    httpDownloadWorkbenchTimer = null
  }
}

function startHttpDownloadWorkbenchPolling() {
  if (!httpDownloadWorkbenchTaskIds.value.length) return
  stopHttpDownloadWorkbenchPolling()
  httpDownloadWorkbenchTimer = window.setTimeout(() => {
    refreshHttpDownloadWorkbench()
  }, 2000)
}

async function refreshHttpDownloadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  const requestSeq = httpDownloadWorkbenchRequestGuard.begin()
  if (!httpDownloadWorkbenchTaskIds.value.length) {
    httpDownloadWorkbenchTasks.value = []
    stopHttpDownloadWorkbenchPolling()
    return
  }
  if (!silent) httpDownloadWorkbenchRefreshing.value = true
  try {
    const result = await httpDownloadApi.status({ compact: true })
    if (!httpDownloadWorkbenchRequestGuard.isLatest(requestSeq)) return
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    httpDownloadWorkbenchTasks.value = mergeWorkbenchTaskRows(httpDownloadWorkbenchTasks.value, selectTrackedDownloadTasks(
      httpDownloadWorkbenchTaskIds.value,
      allTasks,
    ))
    const stillActive = httpDownloadWorkbenchTasks.value.some(t => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(t.status || '')))
    if (stillActive || httpDownloadWorkbenchVisible.value || httpDownloadWorkbenchBackgroundActive.value) startHttpDownloadWorkbenchPolling()
    else stopHttpDownloadWorkbenchPolling()
  } catch (error) {
    if (!httpDownloadWorkbenchRequestGuard.isLatest(requestSeq)) return
    console.error('刷新 HTTP 下载工作台失败:', error)
    startHttpDownloadWorkbenchPolling()
  } finally {
    if (httpDownloadWorkbenchRequestGuard.isLatest(requestSeq)) httpDownloadWorkbenchRefreshing.value = false
  }
}

async function handleHttpDownloadStarted(taskIds = []) {
  const newTaskIds = Array.isArray(taskIds) ? taskIds.filter(Boolean) : []
  if (!newTaskIds.length) return
  httpDownloadWorkbenchTaskIds.value = mergeTrackedDownloadTaskIds(
    httpDownloadWorkbenchTaskIds.value,
    newTaskIds,
  )
  httpDownloadWorkbenchVisible.value = true
  httpDownloadWorkbenchBackgroundActive.value = false
  persistHttpDownloadWorkbenchState()
  await refreshHttpDownloadWorkbench()
}

function hideHttpDownloadWorkbenchToBackground() {
  httpDownloadWorkbenchVisible.value = false
  httpDownloadWorkbenchBackgroundActive.value = true
}

function resumeHttpDownloadWorkbench() {
  httpDownloadWorkbenchVisible.value = true
  httpDownloadWorkbenchBackgroundActive.value = false
}

function closeHttpDownloadWorkbench() {
  clearHttpDownloadWorkbenchState()
}

function handleHttpDownloadBackgroundCardAction(action) {
  if (action === 'resume') {
    resumeHttpDownloadWorkbench()
    return
  }
  if (action === 'close') {
    closeHttpDownloadWorkbench()
  }
}

async function pauseHttpDownloadTask(task) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  if (!taskId) return ElMessage.warning('无法识别 HTTP 下载任务')
  try {
    await httpDownloadApi.pause(taskId)
    ElMessage.success('已暂停')
    await refreshHttpDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '暂停失败')
  }
}

async function resumeHttpDownloadTask(task) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  if (!taskId) return ElMessage.warning('无法识别 HTTP 下载任务')
  try {
    await httpDownloadApi.resume(taskId)
    ElMessage.success('已恢复')
    await refreshHttpDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '恢复失败')
  }
}

async function cancelHttpDownloadTask(task) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  if (!taskId) return ElMessage.warning('无法识别 HTTP 下载任务')
  const title = String(task?.work_title || task?.source_label || '此下载任务').trim()
  try {
    await showSystemConfirm({
      title: '取消 HTTP 下载',
      message: `确定要取消 ${title} 吗？`,
      description: '取消后 aria2 会停止对应下载，已下载的部分文件和 .aria2 控制文件会保留用于后续续传。',
      tone: 'danger',
      confirmText: '取消下载',
    })
  } catch {
    return
  }
  try {
    await httpDownloadApi.cancel(taskId)
    ElMessage.success('已取消')
    await refreshHttpDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消失败')
  }
}

async function retryHttpDownloadTask(task) {
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  if (!taskId) return ElMessage.warning('无法识别 HTTP 下载任务')
  const next = new Set(httpDownloadRetryingTaskIds.value)
  next.add(taskId)
  httpDownloadRetryingTaskIds.value = next
  try {
    await httpDownloadApi.retry(taskId)
    ElMessage.success('已提交重试')
    await refreshHttpDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(httpDownloadRetryingTaskIds.value)
    done.delete(taskId)
    httpDownloadRetryingTaskIds.value = done
  }
}

async function retryHttpDownloadFile(payload) {
  const task = payload?.task || {}
  const file = payload?.file || {}
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  if (!taskId) return ElMessage.warning('无法识别 HTTP 下载任务')
  const retryFile = {
    ...(file?.rawFile || {}),
    ...file,
  }
  delete retryFile.rawFile
  const key = `${taskId}:${file?.relative_path || file?.name || file?.selection_key || 'file'}`
  const next = new Set(httpDownloadRetryingTaskIds.value)
  next.add(key)
  httpDownloadRetryingTaskIds.value = next
  try {
    await httpDownloadApi.retryFile(taskId, retryFile)
    ElMessage.success('已提交该文件重试')
    await refreshHttpDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交单文件重试失败')
  } finally {
    const done = new Set(httpDownloadRetryingTaskIds.value)
    done.delete(key)
    httpDownloadRetryingTaskIds.value = done
  }
}

// --- Baidu Netdisk Workbench Management ---

function persistBaiduNetdiskWorkbenchState() {
  try {
    localStorage.setItem(ASMR_SYNC_BAIDU_NETDISK_WORKBENCH_KEY, JSON.stringify({
      taskIds: baiduNetdiskWorkbenchTaskIds.value,
      visible: baiduNetdiskWorkbenchVisible.value,
      background: baiduNetdiskWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function hydrateBaiduNetdiskWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ASMR_SYNC_BAIDU_NETDISK_WORKBENCH_KEY) || '{}')
    baiduNetdiskWorkbenchTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    baiduNetdiskWorkbenchVisible.value = Boolean(raw.visible && baiduNetdiskWorkbenchTaskIds.value.length)
    baiduNetdiskWorkbenchBackgroundActive.value = Boolean(raw.background && baiduNetdiskWorkbenchTaskIds.value.length)
  } catch (_) {
    baiduNetdiskWorkbenchTaskIds.value = []
    baiduNetdiskWorkbenchVisible.value = false
    baiduNetdiskWorkbenchBackgroundActive.value = false
  }
}

function clearBaiduNetdiskWorkbenchState() {
  baiduNetdiskWorkbenchRequestGuard.invalidate()
  baiduNetdiskWorkbenchTaskIds.value = []
  baiduNetdiskWorkbenchTasks.value = []
  baiduNetdiskWorkbenchVisible.value = false
  baiduNetdiskWorkbenchBackgroundActive.value = false
  stopBaiduNetdiskWorkbenchPolling()
  try { localStorage.removeItem(ASMR_SYNC_BAIDU_NETDISK_WORKBENCH_KEY) } catch (_) {}
}

function stopBaiduNetdiskWorkbenchPolling() {
  if (baiduNetdiskWorkbenchTimer) {
    window.clearTimeout(baiduNetdiskWorkbenchTimer)
    baiduNetdiskWorkbenchTimer = null
  }
}

function startBaiduNetdiskWorkbenchPolling() {
  if (!baiduNetdiskWorkbenchTaskIds.value.length) return
  stopBaiduNetdiskWorkbenchPolling()
  baiduNetdiskWorkbenchTimer = window.setTimeout(() => {
    refreshBaiduNetdiskWorkbench()
  }, 2000)
}

async function refreshBaiduNetdiskWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  const requestSeq = baiduNetdiskWorkbenchRequestGuard.begin()
  if (!baiduNetdiskWorkbenchTaskIds.value.length) {
    baiduNetdiskWorkbenchTasks.value = []
    stopBaiduNetdiskWorkbenchPolling()
    return
  }
  if (!silent) baiduNetdiskWorkbenchRefreshing.value = true
  try {
    const result = await baiduNetdiskApi.status({ compact: true })
    if (!baiduNetdiskWorkbenchRequestGuard.isLatest(requestSeq)) return
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    baiduNetdiskWorkbenchTasks.value = mergeWorkbenchTaskRows(baiduNetdiskWorkbenchTasks.value, selectTrackedDownloadTasks(
      baiduNetdiskWorkbenchTaskIds.value,
      allTasks,
    ))
    const stillActive = baiduNetdiskWorkbenchTasks.value.some(t => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(t.status || '')))
    if (stillActive || baiduNetdiskWorkbenchVisible.value || baiduNetdiskWorkbenchBackgroundActive.value) startBaiduNetdiskWorkbenchPolling()
    else stopBaiduNetdiskWorkbenchPolling()
  } catch (error) {
    if (!baiduNetdiskWorkbenchRequestGuard.isLatest(requestSeq)) return
    console.error('刷新百度网盘下载工作台失败:', error)
    startBaiduNetdiskWorkbenchPolling()
  } finally {
    if (baiduNetdiskWorkbenchRequestGuard.isLatest(requestSeq)) baiduNetdiskWorkbenchRefreshing.value = false
  }
}

async function handleBaiduNetdiskStarted(taskIds = []) {
  const newTaskIds = Array.isArray(taskIds) ? taskIds.filter(Boolean) : []
  if (!newTaskIds.length) return
  baiduNetdiskWorkbenchTaskIds.value = mergeTrackedDownloadTaskIds(
    baiduNetdiskWorkbenchTaskIds.value,
    newTaskIds,
  )
  baiduNetdiskWorkbenchVisible.value = true
  baiduNetdiskWorkbenchBackgroundActive.value = false
  persistBaiduNetdiskWorkbenchState()
  await refreshBaiduNetdiskWorkbench()
}

function hideBaiduNetdiskWorkbenchToBackground() {
  baiduNetdiskWorkbenchVisible.value = false
  baiduNetdiskWorkbenchBackgroundActive.value = true
}

function resumeBaiduNetdiskWorkbench() {
  baiduNetdiskWorkbenchVisible.value = true
  baiduNetdiskWorkbenchBackgroundActive.value = false
}

function closeBaiduNetdiskWorkbench() {
  clearBaiduNetdiskWorkbenchState()
}

function handleBaiduNetdiskBackgroundCardAction(action) {
  if (action === 'resume') {
    resumeBaiduNetdiskWorkbench()
    return
  }
  if (action === 'close') {
    closeBaiduNetdiskWorkbench()
  }
}

function resolveBaiduNetdiskTaskId(task) {
  return String(task?.id || task?.active_task_id || '').trim()
}

async function pauseBaiduNetdiskTask(task) {
  const taskId = resolveBaiduNetdiskTaskId(task)
  if (!taskId) return ElMessage.warning('无法识别百度网盘下载任务')
  try {
    await baiduNetdiskApi.pause(taskId)
    ElMessage.success('已暂停')
    await refreshBaiduNetdiskWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '暂停失败')
  }
}

async function resumeBaiduNetdiskTask(task) {
  const taskId = resolveBaiduNetdiskTaskId(task)
  if (!taskId) return ElMessage.warning('无法识别百度网盘下载任务')
  try {
    await baiduNetdiskApi.resume(taskId)
    ElMessage.success('已恢复')
    await refreshBaiduNetdiskWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '恢复失败')
  }
}

async function cancelBaiduNetdiskTask(task) {
  const taskId = resolveBaiduNetdiskTaskId(task)
  if (!taskId) return ElMessage.warning('无法识别百度网盘下载任务')
  const title = String(task?.work_title || task?.source_label || '此下载任务').trim()
  try {
    await showSystemConfirm({
      title: '取消百度网盘下载',
      message: `确定要取消 ${title} 吗？`,
      description: '取消会停止当前直链下载，临时目录会保留，之后可重新开始利用已有分片续传。',
      tone: 'danger',
      confirmText: '取消下载',
    })
  } catch {
    return
  }
  try {
    await baiduNetdiskApi.cancel(taskId)
    ElMessage.success('已取消')
    await refreshBaiduNetdiskWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消失败')
  }
}

async function retryBaiduNetdiskTask(task) {
  const taskId = resolveBaiduNetdiskTaskId(task)
  if (!taskId) return ElMessage.warning('无法识别百度网盘下载任务')
  const next = new Set(baiduNetdiskRetryingTaskIds.value)
  next.add(taskId)
  baiduNetdiskRetryingTaskIds.value = next
  try {
    await baiduNetdiskApi.retry(taskId)
    ElMessage.success('已提交重试')
    await refreshBaiduNetdiskWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(baiduNetdiskRetryingTaskIds.value)
    done.delete(taskId)
    baiduNetdiskRetryingTaskIds.value = done
  }
}

async function retryBaiduNetdiskFile(payload) {
  const task = payload?.task || {}
  const file = payload?.file || {}
  const taskId = resolveBaiduNetdiskTaskId(task)
  const relativePath = String(file?.relative_path || file?.rawFile?.relative_path || file?.rawFile?.name || file?.name || '').trim()
  if (!taskId || !relativePath) return ElMessage.warning('没有找到可重试的百度网盘失败文件')

  const retryKey = `${taskId}:${relativePath}`
  const next = new Set(baiduNetdiskRetryingTaskIds.value)
  next.add(retryKey)
  baiduNetdiskRetryingTaskIds.value = next
  try {
    await baiduNetdiskApi.retryFile(taskId, file?.rawFile || file)
    ElMessage.success('已提交单文件重试')
    await refreshBaiduNetdiskWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交单文件重试失败')
  } finally {
    const done = new Set(baiduNetdiskRetryingTaskIds.value)
    done.delete(retryKey)
    baiduNetdiskRetryingTaskIds.value = done
  }
}

function getEnhancedRetrySessionId(task) {
  return String(task?.task_metadata?.session_id || task?.session_id || '').trim()
}

function isEnhancedRetryTaskBlocked(task) {
  const taskId = String(task?.id || '').trim()
  const sessionId = getEnhancedRetrySessionId(task)
  return Boolean(
    (sessionId && enhancedRetryingSessionIds.value.has(sessionId))
    || enhancedRetryingTaskIds.value.has(taskId)
    || [...enhancedRetryingTaskIds.value].some(key => key.startsWith(`${taskId}:`))
  )
}

function acquireEnhancedRetryScope({
  sessionId = '',
  scopeKey,
  visibleKey,
  wholeSession = false,
}) {
  const normalizedSessionId = String(sessionId || '').trim()
  const normalizedScopeKey = String(scopeKey || '').trim()
  const normalizedVisibleKey = String(visibleKey || '').trim()
  if (!normalizedScopeKey || enhancedActiveRetryScopes.has(normalizedScopeKey)) return ''

  const sameSessionScopes = [...enhancedActiveRetryScopes.values()]
    .filter(item => normalizedSessionId && item.sessionId === normalizedSessionId)
  if (wholeSession && sameSessionScopes.length > 0) return ''
  if (!wholeSession && sameSessionScopes.some(item => item.wholeSession)) return ''

  enhancedActiveRetryScopes.set(normalizedScopeKey, {
    sessionId: normalizedSessionId,
    visibleKey: normalizedVisibleKey,
    wholeSession,
  })
  if (normalizedVisibleKey) {
    const nextKeys = new Set(enhancedRetryingTaskIds.value)
    nextKeys.add(normalizedVisibleKey)
    enhancedRetryingTaskIds.value = nextKeys
  }
  if (wholeSession && normalizedSessionId) {
    const nextSessions = new Set(enhancedRetryingSessionIds.value)
    nextSessions.add(normalizedSessionId)
    enhancedRetryingSessionIds.value = nextSessions
  }
  return normalizedScopeKey
}

function releaseEnhancedRetryScope(scopeKey) {
  const normalizedScopeKey = String(scopeKey || '').trim()
  if (!normalizedScopeKey) return
  const timer = setTimeout(() => {
    enhancedRetryReleaseTimers.delete(timer)
    const scope = enhancedActiveRetryScopes.get(normalizedScopeKey)
    enhancedActiveRetryScopes.delete(normalizedScopeKey)
    if (!scope) return

    if (scope.visibleKey) {
      const nextKeys = new Set(enhancedRetryingTaskIds.value)
      nextKeys.delete(scope.visibleKey)
      enhancedRetryingTaskIds.value = nextKeys
    }
    if (scope.wholeSession && scope.sessionId) {
      const stillLocked = [...enhancedActiveRetryScopes.values()]
        .some(item => item.wholeSession && item.sessionId === scope.sessionId)
      if (!stillLocked) {
        const nextSessions = new Set(enhancedRetryingSessionIds.value)
        nextSessions.delete(scope.sessionId)
        enhancedRetryingSessionIds.value = nextSessions
      }
    }
  }, 2000)
  enhancedRetryReleaseTimers.add(timer)
}

async function retryEnhancedDownloadTask(task) {
  const sessionId = getEnhancedRetrySessionId(task)
  const taskId = String(task?.id || '').trim()
  if (!taskId) return
  const scopeKey = acquireEnhancedRetryScope({
    sessionId,
    scopeKey: sessionId ? `session:${sessionId}:*` : `task:${taskId}`,
    visibleKey: taskId,
    wholeSession: Boolean(sessionId),
  })
  if (!scopeKey) return
  try {
    if (sessionId) {
      const response = await asmrSyncApi.retryFailedSession(sessionId)
      focusEnhancedRetryWorkbench(response?.session?.task_id, taskId)
      if (response?.session?.retry_reused_active_task) {
        ElMessage.info('已有相同重试任务正在执行，已定位到该任务')
      } else {
        ElMessage.success('已提交重试')
      }
    } else if (taskId) {
      await asmrSyncApi.retry(taskId)
      ElMessage.success('已提交重试')
    }
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    releaseEnhancedRetryScope(scopeKey)
  }
}

async function retryEnhancedDownloadFile(payload) {
  const task = payload?.task || {}
  const file = payload?.file || {}
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const taskId = String(task?.id || '').trim()
  const relativePath = String(file?.relative_path || file?.rawFile?.relative_path || file?.rawFile?.name || file?.name || '').trim()
  if (!sessionId || !relativePath) return ElMessage.warning('没有找到可重试的失败文件')

  const retryKey = `${taskId}:${relativePath}`
  const scopeKey = acquireEnhancedRetryScope({
    sessionId,
    scopeKey: `session:${sessionId}:file:${relativePath}`,
    visibleKey: retryKey,
  })
  if (!scopeKey) return
  try {
    const response = await asmrSyncApi.retrySessionFiles(sessionId, [relativePath])
    focusEnhancedRetryWorkbench(response?.session?.task_id, taskId)
    ElMessage[response?.session?.retry_reused_active_task ? 'info' : 'success'](
      response?.session?.retry_reused_active_task ? '已有相同重试任务正在执行，已定位到该任务' : '已提交单文件重试',
    )
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交单文件重试失败')
  } finally {
    releaseEnhancedRetryScope(scopeKey)
  }
}

function focusEnhancedRetryWorkbench(nextTaskId, previousTaskId = '') {
  const normalizedTaskId = String(nextTaskId || '').trim()
  if (!normalizedTaskId) return
  enhancedDownloadWorkbenchTaskIds.value = replaceTrackedDownloadTaskId(
    enhancedDownloadWorkbenchTaskIds.value,
    previousTaskId,
    normalizedTaskId,
  )
  enhancedDownloadWorkbenchVisible.value = true
  enhancedDownloadWorkbenchBackgroundActive.value = false
  persistEnhancedDownloadWorkbenchState()
}

async function handlePauseEnhancedDownloadTask(task) {
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.pauseSession(sessionId)
    } else if (taskId) {
      await taskApi.pause(taskId)
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已暂停')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] pause failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '暂停失败')
  }
}

async function handleResumeEnhancedDownloadTask(task) {
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.resumeSession(sessionId)
    } else if (taskId) {
      await taskApi.resume(taskId)
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已恢复')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] resume failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '恢复失败')
  }
}

async function handleCancelEnhancedDownloadTask(task) {
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
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
    } else if (taskId) {
      await taskApi.batchCancelCleanup([taskId])
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已取消并清理')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] cancel failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '取消失败')
  }
}

const openEnhancedSession = async (session) => {
  enhancedSessionDrawerVisible.value = true
  enhancedSessionDetailLoading.value = true
  try {
    const result = await asmrSyncApi.sessionEnhanced(session.id)
    enhancedSessionDetail.value = result.session || null
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载会话详情失败')
  } finally {
    enhancedSessionDetailLoading.value = false
  }
}

const changeSessionPriority = async (session, delta) => {
  const nextPriority = Math.max(1, Number(session.queue_priority || 100) + delta)
  try {
    await asmrSyncApi.updateSessionPriority(session.id, nextPriority)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '调整优先级失败')
  }
}

const pauseEnhancedSession = async (session) => {
  try {
    await asmrSyncApi.pauseSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '暂停会话失败')
  }
}

const resumeEnhancedSession = async (session) => {
  try {
    await asmrSyncApi.resumeSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '恢复会话失败')
  }
}

const retryEnhancedSession = async (session) => {
  const sessionId = String(session?.id || '').trim()
  if (!sessionId) return
  const retryKey = `session:${sessionId}`
  const scopeKey = acquireEnhancedRetryScope({
    sessionId,
    scopeKey: `session:${sessionId}:*`,
    visibleKey: retryKey,
    wholeSession: true,
  })
  if (!scopeKey) return
  try {
    const response = await asmrSyncApi.retryFailedSession(sessionId)
    ElMessage[response?.session?.retry_reused_active_task ? 'info' : 'success'](
      response?.session?.retry_reused_active_task ? '已有相同重试任务正在执行' : '已提交重试',
    )
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重试失败资源失败')
  } finally {
    releaseEnhancedRetryScope(scopeKey)
  }
}

const pauseTask = async (taskId) => {
  try {
    await asmrSyncApi.pause(taskId)
    ElMessage.success('任务已暂停')
    await refreshStatus()
  } catch (error) {
    ElMessage.error('暂停失败')
  }
}

const resumeTask = async (taskId) => {
  try {
    await asmrSyncApi.resume(taskId)
    ElMessage.success('任务已恢复')
    await refreshStatus()
  } catch (error) {
    ElMessage.error('恢复失败')
  }
}

const retryFailed = async (taskId) => {
  const normalizedTaskId = String(taskId || '').trim()
  if (!normalizedTaskId) return
  const task = tasks.value.find(item => String(item.id || '') === normalizedTaskId)
  const sessionId = getEnhancedRetrySessionId(task)
  const scopeKey = acquireEnhancedRetryScope({
    sessionId,
    scopeKey: sessionId ? `session:${sessionId}:*` : `task:${normalizedTaskId}`,
    visibleKey: normalizedTaskId,
    wholeSession: Boolean(sessionId),
  })
  if (!scopeKey) return
  try {
    if (sessionId) {
      const response = await asmrSyncApi.retryFailedSession(sessionId)
      focusEnhancedRetryWorkbench(response?.session?.task_id, taskId)
      ElMessage[response?.session?.retry_reused_active_task ? 'info' : 'success'](
        response?.session?.retry_reused_active_task ? '已有相同重试任务正在执行，已定位到该任务' : '已重新提交失败文件',
      )
      await refreshEnhancedDownloadWorkbench({ silent: true })
    } else {
      const result = await asmrSyncApi.retry(taskId)
      ElMessage.success(result.message)
    }
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重试失败')
  } finally {
    releaseEnhancedRetryScope(scopeKey)
  }
}

const retryWaitingTask = async (taskId) => {
  try {
    const result = await asmrSyncApi.retryWaiting(taskId)
    focusEnhancedRetryWorkbench(
      result?.task_id || taskId,
      result?.superseded_task_id || taskId,
    )
    ElMessage.success(result.message)
    await refreshStatus()
  } catch (error) {
    ElMessage.error('重试失败')
  }
}

const cancelWaitingTask = async (taskId) => {
  try {
    // 从数据库和内存中删除等待重试的任务
    await asmrSyncApi.deleteWaitingRetry(taskId)
    ElMessage.success('任务已取消')
    // 从本地列表中移除
    const index = tasks.value.findIndex(t => t.id === taskId)
    if (index > -1) {
      tasks.value.splice(index, 1)
    }
  } catch (error) {
    ElMessage.error('取消失败')
  }
}

const loadSavedFolder = async () => {
  try {
    const config = await configApi.get()
    if (config.storage?.asmr_subtitle_path) {
      subtitleFolder.value = config.storage.asmr_subtitle_path
    }
    if (config.storage?.temp_path && !downloadSettings.value.downloadBasePath) {
      downloadSettings.value.downloadBasePath = config.storage.temp_path.replace(/[\\/]$/, '') + '/asmr_enhanced'
    }
    enhancedUpload.value = {
      mode: config.asmr_sync?.auto_upload_enabled ? (config.asmr_sync?.auto_upload_mode || 'local') : 'disabled',
      targetPath: config.asmr_sync?.auto_upload_target_path || '',
      libraryId: config.asmr_sync?.auto_upload_library_id || ''
    }
  } catch (error) {
    console.error('加载配置失败:', error)
  }
}

// 加载等待重试任务
const loadWaitingRetryTasks = async () => {
  try {
    const result = await asmrSyncApi.getWaitingRetry()
    nextRetryTime.value = result.next_retry_time || ''

    // 将等待重试任务添加到任务列表
    if (result.tasks && result.tasks.length > 0) {
      const waitingTasks = result.tasks.map(t => ({
        id: t.id,
        rjcode: t.rjcode,
        work_title: t.work_title,
        status: 'waiting_retry',
        progress: 0,
        current_step: `等待重试: ${t.retry_reason || '未找到版本'}`,
        task_metadata: {
          retry_reason: t.retry_reason,
          retry_count: t.retry_count,
          retry_after: t.retry_after,
          subtitle_folder: t.subtitle_folder
        }
      }))

      // 合并到任务列表（避免重复）
      const existingIds = new Set(tasks.value.map(t => t.id))
      for (const task of waitingTasks) {
        if (!existingIds.has(task.id)) {
          tasks.value.push(task)
        }
      }
    }
  } catch (error) {
    console.error('加载等待重试任务失败:', error)
  }
}

const selectFolder = () => ElMessage.info('请手动输入文件夹路径')

const scanFolder = async () => {
  if (!subtitleFolder.value) return ElMessage.warning('请先选择字幕文件夹')
  scanning.value = true
  scanResults.value = []
  try {
    const result = await asmrSyncApi.scan(subtitleFolder.value)
    if (result.success) {
      scanResults.value = result.items.map(item => ({ ...item, status: 'pending', previewing: false }))
      ElMessage.success(`发现 ${result.total_found} 个作品`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

const previewDownload = async (row) => {
  previewLoading.value = true
  previewDialogVisible.value = true
  previewData.value = null
  row.previewing = true
  try {
    const result = await asmrSyncApi.preview(row.rjcode)
    previewData.value = result
    if (!result.success) ElMessage.warning(result.error || '未找到可用版本')
  } catch (error) {
    ElMessage.error('获取预览信息失败')
  } finally {
    previewLoading.value = false
    row.previewing = false
  }
}

const startSync = async () => {
  if (selectedItems.value.length === 0) return ElMessage.warning('请先选择要下载的作品')
  syncing.value = true
  try {
    const items = selectedItems.value.map(item => ({ rjcode: item.rjcode, subtitle_folder: item.folder_path, work_title: item.folder_name }))
    const result = await asmrSyncApi.start(items)
    if (result.success) {
      ElMessage.success(result.message)
      await refreshStatus()
      result.tasks.forEach(task => {
        const item = scanResults.value.find(i => i.rjcode === task.rjcode)
        if (item) { item.status = 'downloading'; item.taskId = task.task_id }
      })
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动下载失败')
  } finally {
    syncing.value = false
  }
}

const handleSelectAll = (val) => {
  selectedItems.value = val ? scanResults.value.filter(item => item.status === 'pending') : []
}

const handleSelectionChange = (selection) => {
  selectedItems.value = selection
  selectAll.value = selection.length === scanResults.value.filter(i => i.status === 'pending').length
}

const refreshStatus = async () => {
  if (refreshing.value) return true
  refreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    tasks.value = result.tasks
    result.tasks.forEach(task => {
      const item = scanResults.value.find(i => i.rjcode === task.rjcode)
      if (item) item.status = task.status === 'processing' ? 'downloading' : task.status
    })
    statusFailureCount = 0
    return true
  } catch (error) {
    statusFailureCount += 1
    console.error('获取状态失败:', error)
    return false
  } finally {
    refreshing.value = false
  }
}

const formatSize = (bytes) => {
  if (!bytes) return '未知'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0, size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(2)} ${units[i]}`
}

const formatSpeed = (bytesPerSec) => {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatSize(value)}/s` : ''
}

function getDownloadRuntime(task) {
  const runtime = task?.download_runtime || task?.performance_metrics?.download_runtime || task?.task_metadata?.performance_metrics?.download_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function getTaskDownloadSpeed(task) {
  return Math.max(0, Number(getDownloadRuntime(task)?.speed_bytes_per_sec || 0))
}

function getBackgroundDownloadSpeed(tasks, activeTask) {
  const activeSpeed = getTaskDownloadSpeed(activeTask)
  if (activeSpeed > 0) return activeSpeed
  return (tasks || []).reduce((sum, task) => sum + getTaskDownloadSpeed(task), 0)
}

function backgroundDownloadMetaText(percent, processingTasks, activeTask, failed) {
  const parts = [`总进度: ${Math.max(0, Math.min(100, Number(percent || 0)))}%`]
  const speedText = formatSpeed(getBackgroundDownloadSpeed(processingTasks, activeTask))
  if (speedText) parts.push(`当前速度: ${speedText}`)
  if (failed) parts.push('需要处理')
  return parts.join(' · ')
}

function stopStatusPolling () {
  if (statusInterval) {
    clearTimeout(statusInterval)
    statusInterval = null
  }
}

function startStatusPolling () {
  if (!asmrSyncViewActive) return
  scheduleStatusPolling(ASMR_SYNC_STATUS_POLL_MS)
}

function scheduleStatusPolling (delay = ASMR_SYNC_STATUS_POLL_MS) {
  stopStatusPolling()
  statusInterval = setTimeout(async () => {
    statusInterval = null
    if (!asmrSyncViewActive) return
    if (typeof document !== 'undefined' && document.hidden) {
      return
    }
    const ok = await refreshStatus()
    const nextDelay = ok
      ? ASMR_SYNC_STATUS_POLL_MS
      : Math.min(ASMR_SYNC_STATUS_POLL_MAX_MS, ASMR_SYNC_STATUS_POLL_MS * 2 ** Math.min(statusFailureCount, 5))
    scheduleStatusPolling(nextDelay)
  }, delay)
}

function handleASMRSyncVisibilityChange () {
  if (!asmrSyncViewActive || (typeof document !== 'undefined' && document.hidden)) return
  statusFailureCount = 0
  refreshStatus()
  if (!statusInterval) startStatusPolling()
}

async function initializeASMRSyncPage () {
  if (asmrSyncInitialized) return
  hydrateEnhancedDownloadWorkbenchState()
  hydrateHttpDownloadWorkbenchState()
  hydrateBaiduNetdiskWorkbenchState()
  await loadSavedFolder()
  await loadWaitingRetryTasks()
  await refreshStatus()
  if (enhancedDownloadWorkbenchTaskIds.value.length) await refreshEnhancedDownloadWorkbench()
  if (httpDownloadWorkbenchTaskIds.value.length) await refreshHttpDownloadWorkbench()
  if (baiduNetdiskWorkbenchTaskIds.value.length) await refreshBaiduNetdiskWorkbench()
  activeWorkspaceTab.value = normalizeWorkspaceTab(route.query?.tab)
  if (subtitleFolder.value) {
    await scanFolder()
  }
  asmrSyncInitialized = true
}

onMounted(async () => {
  await initializeASMRSyncPage()
  asmrSyncViewActive = true
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleASMRSyncVisibilityChange)
  }
  startStatusPolling()
})

onActivated(async () => {
  if (asmrSyncViewActive) return
  asmrSyncViewActive = true
  await loadWaitingRetryTasks()
  await refreshStatus()
  await loadEnhancedSessions()
  if (enhancedDownloadWorkbenchTaskIds.value.length) refreshEnhancedDownloadWorkbench()
  if (httpDownloadWorkbenchTaskIds.value.length) refreshHttpDownloadWorkbench()
  if (baiduNetdiskWorkbenchTaskIds.value.length) refreshBaiduNetdiskWorkbench()
  activeWorkspaceTab.value = normalizeWorkspaceTab(route.query?.tab)
  startStatusPolling()
})

onDeactivated(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
})

onBeforeUnmount(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleASMRSyncVisibilityChange)
  }
  stopEnhancedDownloadWorkbenchPolling()
  stopHttpDownloadWorkbenchPolling()
  stopBaiduNetdiskWorkbenchPolling()
  for (const timer of enhancedRetryReleaseTimers) clearTimeout(timer)
  enhancedRetryReleaseTimers.clear()
  enhancedActiveRetryScopes.clear()
})

onUnmounted(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleASMRSyncVisibilityChange)
  }
  stopEnhancedDownloadWorkbenchPolling()
  stopHttpDownloadWorkbenchPolling()
  stopBaiduNetdiskWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchVisible, (visible) => {
  persistEnhancedDownloadWorkbenchState()
  if (visible || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
  else stopEnhancedDownloadWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchBackgroundActive, () => {
  persistEnhancedDownloadWorkbenchState()
  if (enhancedDownloadWorkbenchVisible.value || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
  else stopEnhancedDownloadWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchTaskIds, () => {
  persistEnhancedDownloadWorkbenchState()
}, { deep: true })

watch(httpDownloadWorkbenchVisible, (visible) => {
  persistHttpDownloadWorkbenchState()
  if (visible || httpDownloadWorkbenchBackgroundActive.value) startHttpDownloadWorkbenchPolling()
  else stopHttpDownloadWorkbenchPolling()
})

watch(httpDownloadWorkbenchBackgroundActive, () => {
  persistHttpDownloadWorkbenchState()
  if (httpDownloadWorkbenchVisible.value || httpDownloadWorkbenchBackgroundActive.value) startHttpDownloadWorkbenchPolling()
  else stopHttpDownloadWorkbenchPolling()
})

watch(httpDownloadWorkbenchTaskIds, () => {
  persistHttpDownloadWorkbenchState()
}, { deep: true })

watch(httpDownloadDraft, (value) => {
  persistDownloadDraft(ASMR_SYNC_HTTP_DOWNLOAD_DRAFT_KEY, value)
}, { deep: true })

watch(baiduNetdiskWorkbenchVisible, (visible) => {
  persistBaiduNetdiskWorkbenchState()
  if (visible || baiduNetdiskWorkbenchBackgroundActive.value) startBaiduNetdiskWorkbenchPolling()
  else stopBaiduNetdiskWorkbenchPolling()
})

watch(baiduNetdiskWorkbenchBackgroundActive, () => {
  persistBaiduNetdiskWorkbenchState()
  if (baiduNetdiskWorkbenchVisible.value || baiduNetdiskWorkbenchBackgroundActive.value) startBaiduNetdiskWorkbenchPolling()
  else stopBaiduNetdiskWorkbenchPolling()
})

watch(baiduNetdiskWorkbenchTaskIds, () => {
  persistBaiduNetdiskWorkbenchState()
}, { deep: true })

watch(baiduNetdiskDraft, (value) => {
  persistDownloadDraft(ASMR_SYNC_BAIDU_NETDISK_DRAFT_KEY, value)
}, { deep: true })

watch(() => route.query?.tab, (value) => {
  activeWorkspaceTab.value = normalizeWorkspaceTab(value)
})

watch(activeWorkspaceTab, (value) => {
  const nextTab = normalizeWorkspaceTab(value)
  if (nextTab !== value) {
    activeWorkspaceTab.value = nextTab
    return
  }
  const currentTab = normalizeWorkspaceTab(route.query?.tab)
  if (currentTab === nextTab) return
  router.replace({ path: route.path, query: { ...route.query, tab: nextTab } }).catch(() => {})
})
</script>

<style scoped>
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }

/* ==============================================================
 * 页面整体布局：与库存页 / 操作记录页保持一致
 * ============================================================ */
.asmr-page,
:global(.asmr-dialog-theme) {
  --asmr-surface: #ffffff;
  --asmr-surface-soft: #f8fafc;
  --asmr-surface-muted: #f1f5f9;
  --asmr-surface-hover: #f8fafc;
  --asmr-field-bg: rgba(248, 250, 252, 0.92);
  --asmr-field-bg-focus: #ffffff;
  --asmr-field-placeholder: #94a3b8;
  --asmr-focus-ring: rgba(59, 130, 246, 0.12);
  --asmr-border: rgba(15, 23, 42, 0.08);
  --asmr-border-strong: rgba(15, 23, 42, 0.16);
  --asmr-divider: rgba(15, 23, 42, 0.1);
  --asmr-text: #475569;
  --asmr-text-strong: #0f172a;
  --asmr-text-muted: #94a3b8;
  --asmr-accent: #2563eb;
  --asmr-accent-hover: #1d4ed8;
  --asmr-card-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  --asmr-control-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
  --asmr-primary-bg: linear-gradient(135deg, #111827, #1e293b);
  --asmr-primary-bg-hover: linear-gradient(135deg, #1e293b, #334155);
  --asmr-primary-text: #ffffff;
  --asmr-tab-active-bg: linear-gradient(180deg, #eff6ff, #ffffff);
  --asmr-tab-active-border: rgba(37, 99, 235, 0.16);
  --asmr-tab-active-text: #0f172a;
  --asmr-tab-badge-bg: rgba(37, 99, 235, 0.1);
  --asmr-tab-badge-text: #1d4ed8;
  --asmr-info-bg: rgba(224, 231, 255, 0.85);
  --asmr-info-text: #4338ca;
  --asmr-info-border: rgba(165, 180, 252, 0.5);
  --asmr-success-bg: rgba(220, 252, 231, 0.85);
  --asmr-success-text: #047857;
  --asmr-success-border: rgba(134, 239, 172, 0.5);
  --asmr-warning-bg: rgba(254, 243, 199, 0.85);
  --asmr-warning-text: #b45309;
  --asmr-warning-border: rgba(253, 224, 71, 0.5);
  --asmr-danger-bg: rgba(254, 226, 226, 0.85);
  --asmr-danger-text: #b91c1c;
  --asmr-danger-border: rgba(252, 165, 165, 0.5);
  --asmr-chip-muted-bg: rgba(241, 245, 249, 0.85);
  --asmr-chip-muted-text: #475569;
  --asmr-chip-muted-border: rgba(203, 213, 225, 0.55);
}

:global(html.kikoerumanager-dark .asmr-page),
:global(html.kikoerumanager-dark .asmr-dialog-theme) {
  --asmr-surface: #111216;
  --asmr-surface-soft: #17181d;
  --asmr-surface-muted: #24252a;
  --asmr-surface-hover: #202126;
  --asmr-field-bg: #17181d;
  --asmr-field-bg-focus: #1d1e23;
  --asmr-field-placeholder: rgba(228, 228, 231, 0.45);
  --asmr-focus-ring: rgba(255, 255, 255, 0.1);
  --asmr-border: rgba(255, 255, 255, 0.11);
  --asmr-border-strong: rgba(255, 255, 255, 0.2);
  --asmr-divider: rgba(255, 255, 255, 0.12);
  --asmr-text: rgba(228, 228, 231, 0.78);
  --asmr-text-strong: #f4f4f5;
  --asmr-text-muted: rgba(228, 228, 231, 0.58);
  --asmr-accent: #e7e7eb;
  --asmr-accent-hover: #ffffff;
  --asmr-card-shadow: none;
  --asmr-control-shadow: none;
  --asmr-primary-bg: #2b2c30;
  --asmr-primary-bg-hover: #333438;
  --asmr-primary-text: #f5f5f5;
  --asmr-tab-active-bg: #2b2c30;
  --asmr-tab-active-border: rgba(255, 255, 255, 0.2);
  --asmr-tab-active-text: #f5f5f5;
  --asmr-tab-badge-bg: rgba(255, 255, 255, 0.12);
  --asmr-tab-badge-text: #f5f5f5;
  --asmr-info-bg: rgba(255, 255, 255, 0.1);
  --asmr-info-text: rgba(244, 244, 245, 0.88);
  --asmr-info-border: rgba(255, 255, 255, 0.14);
  --asmr-success-bg: rgba(16, 185, 129, 0.16);
  --asmr-success-text: #a7f3d0;
  --asmr-success-border: rgba(110, 231, 183, 0.24);
  --asmr-warning-bg: rgba(245, 158, 11, 0.16);
  --asmr-warning-text: #fde68a;
  --asmr-warning-border: rgba(251, 191, 36, 0.24);
  --asmr-danger-bg: rgba(244, 63, 94, 0.16);
  --asmr-danger-text: #fecdd3;
  --asmr-danger-border: rgba(251, 113, 133, 0.24);
  --asmr-chip-muted-bg: rgba(255, 255, 255, 0.08);
  --asmr-chip-muted-text: rgba(228, 228, 231, 0.72);
  --asmr-chip-muted-border: rgba(255, 255, 255, 0.12);
}
.asmr-page {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 18px 24px 24px;
  gap: 14px;
}
.asmr-page > section,
.asmr-page > div { flex-shrink: 0; }

/* ==============================================================
 * 页头按钮：ASMR 自有按钮源样式
 *  - 基础 ghost 白底
 *  - .primary 黑灰渐变 + 软阴影
 * ============================================================ */
.asmr-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--asmr-border-strong);
  background: var(--asmr-surface);
  color: var(--asmr-text-strong);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden; /* 容纳 shimmer ::before */
  /* 拆分 transition：transform/shadow 走 spring，颜色/opacity 走线性 */
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background 0.35s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
  will-change: transform, opacity;
}
/* 通用图标动画基线（Loader2 spin 不在此选择器范围，避免冲突） */
.asmr-head-btn :deep(.asmr-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.asmr-head-btn :deep(svg) { flex-shrink: 0; }

/* 图标包裹层：固定尺寸 + 居中，让 swap Transition 不影响按钮整体宽高 */
.page-head-btn-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  position: relative;
}

/* 关键：hover 不依赖 :not(:disabled)，避免点击瞬间 disabled 切换导致按钮塌回 base 闪烁 */
.asmr-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: var(--asmr-control-shadow);
}
.asmr-head-btn:active:not(:disabled) {
  transform: scale(0.96);
  transition:
    transform 0.12s ease,
    box-shadow 0.18s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    opacity 0.2s ease;
}
/* 按下瞬间图标短暂缩放反馈 */
.asmr-head-btn:active:not(:disabled) :deep(.asmr-head-btn-icon) {
  transform: scale(0.82);
  transition: transform 0.12s ease;
}
/* disabled：仅改 opacity / cursor，不重置 transform / box-shadow，让 hover 视觉与 enabled 一致，消除点击瞬间跳变 */
.asmr-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* === Primary 黑灰渐变按钮 + shimmer 高光扫光 === */
.asmr-head-btn.primary {
  background: var(--asmr-primary-bg);
  color: var(--asmr-primary-text);
  border-color: transparent;
  box-shadow: var(--asmr-control-shadow);
}
.asmr-head-btn.primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -120%;
  width: 60%;
  height: 100%;
  background: linear-gradient(
    100deg,
    transparent 0%,
    rgba(255, 255, 255, 0.05) 30%,
    rgba(255, 255, 255, 0.28) 50%,
    rgba(255, 255, 255, 0.05) 70%,
    transparent 100%
  );
  transform: skewX(-18deg);
  transition: left 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
.asmr-head-btn.primary:hover {
  background: var(--asmr-primary-bg-hover);
  box-shadow: var(--asmr-control-shadow);
}
.asmr-head-btn.primary:hover::before {
  left: 130%;
}

/* === Ghost 白底按钮 hover 时纯色变化（避免 gradient 不能 transition 造成瞬切）=== */
.asmr-head-btn.ghost {
  background-color: var(--asmr-surface);
}
.asmr-head-btn.ghost:hover {
  background-color: var(--asmr-surface-hover);
  border-color: var(--asmr-border-strong);
}

/* === 各按钮专属图标动效 === */
/* 扫描：Search 图标 hover 时左摆 + 放大（模拟搜索动作） */
.asmr-head-btn.btn-scan:hover:not(:disabled) :deep(.asmr-head-btn-icon) {
  animation: scan-icon-wiggle 0.7s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes scan-icon-wiggle {
  0%   { transform: rotate(0deg) scale(1); }
  25%  { transform: rotate(-15deg) scale(1.18); }
  55%  { transform: rotate(10deg) scale(1.15); }
  80%  { transform: rotate(-4deg) scale(1.12); }
  100% { transform: rotate(0deg) scale(1.1); }
}

/* 开始同步下载：DownloadIcon 箭头 hover 时下移 + 缩放（模拟下载方向）+ 白色发光 */
.asmr-head-btn.btn-download:hover:not(:disabled) :deep(.asmr-head-btn-icon) {
  transform: translateY(2px) scale(1.18);
  filter: drop-shadow(0 2px 5px rgba(255, 255, 255, 0.45));
  animation: download-icon-bob 1.2s ease-in-out infinite;
}
@keyframes download-icon-bob {
  0%, 100% { transform: translateY(2px) scale(1.18); }
  50%      { transform: translateY(4px) scale(1.18); }
}

/* 刷新：RefreshCw 图标 hover 时旋转一整圈（非 loading 态）*/
.asmr-head-btn.btn-refresh:hover:not(:disabled) :deep(.asmr-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 文本 label：min-width + 居中，避免「扫描」→「扫描中…」宽度跳变 */
.page-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.asmr-head-btn.primary .page-head-btn-label { min-width: 86px; }
.asmr-head-btn.ghost .page-head-btn-label { min-width: 42px; }
/* hover 时文字微微展开间距（不依赖 :not(:disabled)，避免点击瞬间跳变） */
.asmr-head-btn:hover .page-head-btn-label {
  letter-spacing: 0.04em;
}

/* === 图标 swap Transition：Loader2 ↔ Search/DownloadIcon 切换时平滑过渡 === */
.asmr-head-btn :deep(.page-head-icon-swap-enter-active) {
  transition:
    opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-head-btn :deep(.page-head-icon-swap-leave-active) {
  transition:
    opacity 0.14s ease,
    transform 0.18s ease;
  position: absolute;
}
.asmr-head-btn :deep(.page-head-icon-swap-enter-from) {
  opacity: 0;
  transform: scale(0.4) rotate(-90deg);
}
.asmr-head-btn :deep(.page-head-icon-swap-leave-to) {
  opacity: 0;
  transform: scale(0.4) rotate(90deg);
}

/* ==============================================================
 * 区块 / 列表 / 数字 进出过渡：让点击刷新 / 扫描后内容出现更平滑
 * ============================================================ */

/* Section v-if 进出：fade + 上滑 + 微缩放（弹性曲线） */
.asmr-section-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1),
    max-height 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}
.asmr-section-leave-active {
  transition:
    opacity 0.25s ease,
    transform 0.3s ease,
    max-height 0.35s cubic-bezier(0.4, 0, 0.6, 1);
  overflow: hidden;
}
.asmr-section-enter-from {
  opacity: 0;
  transform: translateY(-14px) scale(0.985);
}
.asmr-section-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.99);
}

.asmr-workspace-panel-enter-active,
.asmr-workspace-panel-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.asmr-workspace-panel-enter-from,
.asmr-workspace-panel-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* 列表项进出（TransitionGroup name="asmr-list"） */
.asmr-list-enter-active {
  transition:
    opacity 0.4s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-list-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
  /* leave 阶段 absolute 定位避免后续元素跳动 */
  position: absolute;
  width: calc(100% - 36px); /* 抵扣 .asmr-card-body 的 padding 估值 */
}
.asmr-list-enter-from {
  opacity: 0;
  transform: translateX(-18px) scale(0.97);
}
.asmr-list-leave-to {
  opacity: 0;
  transform: translateX(18px) scale(0.97);
}
.asmr-list-move {
  transition: transform 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}

/* lib-info-strip 数字翻页过渡（mode="out-in"）*/
.asmr-num-flip-enter-active {
  transition:
    opacity 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-num-flip-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.2s ease;
}
.asmr-num-flip-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.85);
}
.asmr-num-flip-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.85);
}
/* 数字过渡需要相对父级稳定的尺寸，避免 leave/enter 期间塌陷 */
.lib-info-value { min-height: 1.45em; position: relative; }
.lib-info-value > b { display: inline-block; transform-origin: center; }

/* 后台浮动卡片 transition 已迁移至 index.css 全局 .floating-card-* 规范 */

.asmr-floating-pager {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2120;
  width: min(92vw, 440px);
  perspective: 1200px;
  pointer-events: auto;
}

.asmr-floating-pager :deep(.floating-card) {
  position: relative;
  right: auto;
  bottom: auto;
  width: 100%;
  transform-origin: center right;
}

.asmr-floating-pager-controls {
  position: absolute;
  right: 12px;
  top: -34px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.10);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.asmr-floating-page-btn,
.asmr-floating-page-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  outline: none;
  box-shadow: none;
  color: #64748b;
  background: transparent;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.asmr-floating-page-btn:focus,
.asmr-floating-page-btn:focus-visible,
.asmr-floating-page-dot:focus,
.asmr-floating-page-dot:focus-visible {
  outline: none;
  box-shadow: none;
}

.asmr-floating-page-btn {
  width: 24px;
  height: 24px;
  border-radius: 999px;
}

.asmr-floating-page-btn:hover {
  color: #2563eb;
  background: rgba(37, 99, 235, 0.09);
  transform: translateY(-1px) scale(1.05);
}

.asmr-floating-page-btn:active {
  transform: scale(0.94);
}

.asmr-floating-page-dots {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.asmr-floating-page-dot {
  width: 7px;
  height: 7px;
  padding: 0;
  border-radius: 999px;
  background: #cbd5e1;
}

.asmr-floating-page-dot.is-active {
  width: 17px;
  background: #2563eb;
}

.asmr-floating-card-page-next-enter-active,
.asmr-floating-card-page-next-leave-active,
.asmr-floating-card-page-prev-enter-active,
.asmr-floating-card-page-prev-leave-active {
  transition:
    opacity 0.24s ease,
    transform 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

.asmr-floating-card-page-next-enter-from {
  opacity: 0;
  transform: translateX(26px) rotateY(-16deg) scale(0.96);
}

.asmr-floating-card-page-next-leave-to {
  opacity: 0;
  transform: translateX(-26px) rotateY(16deg) scale(0.96);
}

.asmr-floating-card-page-prev-enter-from {
  opacity: 0;
  transform: translateX(-26px) rotateY(16deg) scale(0.96);
}

.asmr-floating-card-page-prev-leave-to {
  opacity: 0;
  transform: translateX(26px) rotateY(-16deg) scale(0.96);
}

html.kikoerumanager-dark .asmr-floating-pager-controls {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(28, 29, 34, 0.92);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.32);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

html.kikoerumanager-dark .asmr-floating-page-btn,
html.kikoerumanager-dark .asmr-floating-page-dot {
  color: rgba(244, 244, 245, 0.7);
}

html.kikoerumanager-dark .asmr-floating-page-btn:hover {
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.10);
}

html.kikoerumanager-dark .asmr-floating-page-dot {
  background: rgba(255, 255, 255, 0.28);
}

html.kikoerumanager-dark .asmr-floating-page-dot.is-active {
  background: #93c5fd;
}

@media (max-width: 640px) {
  .asmr-floating-pager {
    left: 12px;
    right: 12px;
    bottom: max(12px, env(safe-area-inset-bottom));
    width: auto;
  }

  .asmr-floating-pager-controls {
    right: 10px;
    top: -32px;
  }
}

/* ==============================================================
 * 顶部状态条 lib-info-strip（对齐 Library / Conflicts / SubtitleImport）
 * ============================================================ */
.lib-info-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr) 1px) minmax(0, 1fr);
  /* fallback for browsers that don't auto-trim trailing 1px */
  align-items: stretch;
  gap: 0;
  margin-bottom: 0;
  padding: 16px 20px;
  border-radius: 14px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-border);
  box-shadow: var(--asmr-card-shadow);
}
/* 6 项：5 条 divider 即可 */
.asmr-info-strip {
  grid-template-columns:
    minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr) 1px
    minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);
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
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--asmr-text-muted);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lib-info-value {
  font-size: 13.5px;
  color: var(--asmr-text);
  line-height: 1.3;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.lib-info-value :deep(b),
.lib-info-value b {
  font-weight: 700;
  font-size: 20px;
  letter-spacing: -0.4px;
  color: var(--asmr-text-strong);
  font-variant-numeric: tabular-nums;
}
.lib-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--asmr-divider), transparent);
  align-self: stretch;
}

.asmr-workspace-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border-radius: 14px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-border);
  box-shadow: var(--asmr-card-shadow);
}
.asmr-workspace-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--asmr-text);
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}
.asmr-workspace-tab:hover {
  transform: translateY(-1px);
  color: var(--asmr-text-strong);
  background: var(--asmr-surface-hover);
}
.asmr-workspace-tab.is-active {
  color: var(--asmr-tab-active-text);
  border-color: var(--asmr-tab-active-border);
  background: var(--asmr-tab-active-bg);
  box-shadow: 0 8px 18px -14px rgba(37, 99, 235, 0.45);
}
.asmr-workspace-tab b {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--asmr-tab-badge-bg);
  color: var(--asmr-tab-badge-text);
  font-size: 11px;
  font-weight: 800;
}
@media (max-width: 1180px) {
  .asmr-info-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px 0;
    padding: 16px 18px;
  }
  .lib-info-divider { display: none; }
  .lib-info-item { padding: 0 14px; border-right: 1px solid var(--asmr-border); }
  .lib-info-item:nth-child(3n) { border-right: 0; }
}
@media (max-width: 720px) {
  .asmr-info-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lib-info-item:nth-child(3n) { border-right: 1px solid var(--asmr-border); }
  .lib-info-item:nth-child(2n) { border-right: 0; }
  .asmr-workspace-tabs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .asmr-workspace-tab {
    min-width: 0;
    padding: 0 8px;
  }
  .asmr-workspace-tab span {
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

/* ==============================================================
 * lib-chip 通用徽章
 * ============================================================ */
.lib-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.lib-chip-success { background: var(--asmr-success-bg); color: var(--asmr-success-text); border: 1px solid var(--asmr-success-border); }
.lib-chip-warning { background: var(--asmr-warning-bg); color: var(--asmr-warning-text); border: 1px solid var(--asmr-warning-border); }
.lib-chip-danger  { background: var(--asmr-danger-bg); color: var(--asmr-danger-text); border: 1px solid var(--asmr-danger-border); }
.lib-chip-info    { background: var(--asmr-info-bg); color: var(--asmr-info-text); border: 1px solid var(--asmr-info-border); }
.lib-chip-slate   { background: var(--asmr-chip-muted-bg); color: var(--asmr-chip-muted-text); border: 1px solid var(--asmr-chip-muted-border); }

/* ==============================================================
 * 主卡片 asmr-card：和 conflicts-info-card / subtitle-info-card 同款
 * ============================================================ */
.asmr-card {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-border);
  box-shadow: var(--asmr-card-shadow);
  overflow: hidden;
}
.asmr-card-amber {
  background: var(--asmr-warning-bg);
  border-color: var(--asmr-warning-border);
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
}
.asmr-card-head-amber {
  background: var(--asmr-warning-bg);
  border-bottom-color: var(--asmr-warning-border);
}
.asmr-card-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.asmr-card-head-title h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--asmr-text-strong);
}
.asmr-card-head-subtitle {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--asmr-text-muted);
  letter-spacing: 0.01em;
}
.asmr-card-head-icon { color: var(--asmr-accent); flex-shrink: 0; }
.asmr-card-head-icon-amber { color: var(--asmr-warning-text); flex-shrink: 0; }
.asmr-card-head-count { color: var(--asmr-text-muted); font-weight: 500; font-size: 12.5px; }
.asmr-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.asmr-card-head-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--asmr-text);
  cursor: pointer;
  user-select: none;
}
.asmr-card-head-checkbox input { width: 14px; height: 14px; accent-color: var(--asmr-accent); }
.asmr-card-body {
  padding: 16px 18px;
}
.asmr-cell-text {
  color: var(--asmr-text);
}
.asmr-strong-text,
.asmr-section-title {
  color: var(--asmr-text-strong);
}
.asmr-muted-text,
.asmr-muted-icon {
  color: var(--asmr-text-muted);
}
.asmr-accent-text {
  color: var(--asmr-accent);
}
.asmr-success-text {
  color: var(--asmr-success-text);
}
.asmr-warning-text {
  color: var(--asmr-warning-text);
}
.asmr-danger-text {
  color: var(--asmr-danger-text);
}
.asmr-preview-stat,
.asmr-preview-row {
  background: var(--asmr-surface-soft);
  border: 1px solid var(--asmr-border);
}
.asmr-dialog-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}
.asmr-dialog-chip.is-compact {
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 11px;
}
.asmr-dialog-chip.is-info {
  background: var(--asmr-info-bg);
  color: var(--asmr-info-text);
  border-color: var(--asmr-info-border);
}
.asmr-dialog-chip.is-success {
  background: var(--asmr-success-bg);
  color: var(--asmr-success-text);
  border-color: var(--asmr-success-border);
}
.asmr-dialog-chip.is-warning {
  background: var(--asmr-warning-bg);
  color: var(--asmr-warning-text);
  border-color: var(--asmr-warning-border);
}
.asmr-dialog-chip.is-danger {
  background: var(--asmr-danger-bg);
  color: var(--asmr-danger-text);
  border-color: var(--asmr-danger-border);
}
.asmr-dialog-chip.is-muted {
  background: var(--asmr-chip-muted-bg);
  color: var(--asmr-chip-muted-text);
  border-color: var(--asmr-chip-muted-border);
}
.asmr-metric-icon-info {
  color: var(--asmr-info-text);
}
.asmr-metric-icon-success {
  color: var(--asmr-success-text);
}
.asmr-metric-icon-warning {
  color: var(--asmr-warning-text);
}
.asmr-metric-icon-danger {
  color: var(--asmr-danger-text);
}
.asmr-list { display: flex; flex-direction: column; gap: 10px; }
.asmr-table-wrap {
  max-height: 400px;
  overflow: auto;
}

/* ==============================================================
 * asmr-mini-btn：通用小按钮 28px ghost / is-primary 黑色 / is-warning amber / xs 小尺寸
 * ============================================================ */
.asmr-mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border-strong);
  background: var(--asmr-surface);
  color: var(--asmr-text);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.15s ease, box-shadow 0.18s ease;
}
.asmr-mini-btn:hover {
  background: var(--asmr-surface-hover);
  border-color: var(--asmr-border-strong);
  color: var(--asmr-text-strong);
}
.asmr-mini-btn:active:not(:disabled) { transform: scale(0.96); }
.asmr-mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.asmr-mini-btn.is-primary {
  background: var(--asmr-primary-bg);
  color: var(--asmr-primary-text);
  border-color: transparent;
  box-shadow: var(--asmr-control-shadow);
}
.asmr-mini-btn.is-primary:hover {
  background: var(--asmr-primary-bg-hover);
  box-shadow: var(--asmr-control-shadow);
  color: var(--asmr-primary-text);
}

.asmr-mini-btn.is-warning {
  background: var(--asmr-warning-bg);
  color: var(--asmr-warning-text);
  border-color: var(--asmr-warning-border);
}
.asmr-mini-btn.is-warning:hover {
  background: var(--asmr-warning-bg);
  color: var(--asmr-warning-text);
  border-color: var(--asmr-warning-border);
}

/* xs：更小的尺寸（任务卡片 / 等待重试列表用）*/
.asmr-mini-btn.xs {
  height: 24px;
  padding: 0 8px;
  font-size: 11px;
  border-radius: 7px;
  gap: 4px;
}

/* ==============================================================
 * 后台浮窗（.asmr-bg-card-*）已迁移至 index.css 全局 .floating-card 规范
 * ============================================================ */

/* ==============================================================
 * 下载任务 asmr-task 卡片
 * ============================================================ */
.asmr-task {
  position: relative;
  overflow: hidden;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-surface);
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.asmr-task::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--asmr-text-muted);
  opacity: 0.72;
}
.asmr-task:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}
.asmr-task.is-completed {
  border-color: var(--asmr-success-border);
  background: var(--asmr-surface);
}
.asmr-task.is-completed::before {
  background: var(--asmr-success-text);
}
.asmr-task.is-failed {
  border-color: var(--asmr-danger-border);
  background: linear-gradient(90deg, var(--asmr-danger-bg), var(--asmr-surface) 18%);
}
.asmr-task.is-failed::before {
  background: var(--asmr-danger-text);
}
.asmr-task.is-paused {
  border-color: var(--asmr-chip-muted-border);
  background: var(--asmr-surface);
}
.asmr-task.is-paused::before {
  background: var(--asmr-text-muted);
}
.asmr-task.is-processing {
  border-color: var(--asmr-info-border);
  background: linear-gradient(90deg, var(--asmr-info-bg), var(--asmr-surface) 18%);
}
.asmr-task.is-processing::before {
  background: var(--asmr-accent);
}
.asmr-task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.asmr-task-head-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 auto;
}
.asmr-task-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.asmr-task-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.asmr-task-alert.is-error {
  background: var(--asmr-danger-bg);
  border: 1px solid var(--asmr-danger-border);
  color: var(--asmr-danger-text);
}
.asmr-task-alert :deep(svg) { flex-shrink: 0; margin-top: 1px; color: currentColor; }

.asmr-task-details { margin-top: 10px; }
.asmr-task-details-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  user-select: none;
  padding: 4px 6px;
  border-radius: 6px;
  transition: background-color 0.18s ease, color 0.18s ease;
}
.asmr-task-details-summary:hover { background: var(--asmr-surface-hover); }
.asmr-task-details-summary.is-success { color: var(--asmr-success-text); }
.asmr-task-details-summary.is-success:hover { color: var(--asmr-success-text); }
.asmr-task-details-summary.is-danger { color: var(--asmr-danger-text); }
.asmr-task-details-summary.is-danger:hover { color: var(--asmr-danger-text); }
.asmr-task-details-summary.is-slate { color: var(--asmr-text); }
.asmr-task-details-summary.is-slate:hover { color: var(--asmr-text-strong); }
.asmr-task-details-body {
  margin-top: 8px;
  display: grid;
  gap: 6px;
}

.asmr-task-mapping {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--asmr-success-bg);
  border: 1px solid var(--asmr-success-border);
  font-size: 11.5px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.asmr-task-mapping-label {
  width: 56px;
  flex-shrink: 0;
  color: var(--asmr-text-muted);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.asmr-task-mapping-arrow { text-align: center; color: var(--asmr-success-text); font-weight: 700; font-size: 10px; }

.asmr-task-failed-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 9px;
  background: var(--asmr-danger-bg);
  border: 1px solid var(--asmr-danger-border);
  font-size: 11.5px;
}

.asmr-task-file-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-surface);
  font-size: 11.5px;
  min-width: 0;
}
.asmr-task-file-progress {
  width: 92px;
  flex-shrink: 0;
}
.asmr-task-file-progress-bar {
  height: 6px;
  border-radius: 999px;
  background: var(--asmr-surface-muted);
  position: relative;
  overflow: hidden;
}
.asmr-task-file-progress-bar::after {
  content: '';
  position: absolute;
  inset: 0;
  width: var(--w, 0%);
  background: linear-gradient(90deg, var(--asmr-accent), var(--asmr-accent-hover));
  border-radius: 999px;
  transition: width 0.4s ease;
}
.asmr-task-file-progress-bar { background: var(--asmr-surface-muted); }
.asmr-task-file-progress-bar > div,
.asmr-task-file-row .asmr-task-file-progress > div {
  height: 6px;
  background: linear-gradient(90deg, var(--asmr-accent), var(--asmr-accent-hover));
  border-radius: 999px;
  transition: width 0.4s ease;
}
.asmr-task-file-size {
  color: var(--asmr-text-muted);
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-size: 10.5px;
  white-space: nowrap;
  min-width: 132px;
  text-align: right;
  flex-shrink: 0;
}

/* ==============================================================
 * 列表行（等待重试卡片 / 通用列表行）
 * ============================================================ */
.asmr-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-warning-border);
}

/* ==============================================================
 * 通用辅助：RJ 号 / 链接按钮
 * ============================================================ */
.asmr-rjcode {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-weight: 600;
  font-size: 13px;
  color: var(--asmr-accent);
  letter-spacing: -0.2px;
  flex-shrink: 0;
}
.asmr-rjcode.is-bold { font-weight: 700; }

.asmr-link-btn {
  background: transparent;
  border: 0;
  color: var(--asmr-accent);
  font-size: 12.5px;
  font-weight: 500;
  transition: color 0.18s ease, text-decoration 0.18s ease;
  padding: 4px 6px;
}
.asmr-link-btn:hover {
  color: var(--asmr-accent-hover);
  text-decoration: underline;
}
.asmr-link-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ==============================================================
 * el-dialog 圆角保留
 * ============================================================ */
:deep(.el-dialog) {
  border-radius: 16px !important;
}
:deep(.el-dialog),
:deep(.el-drawer) {
  background: var(--asmr-surface);
  color: var(--asmr-text);
}
:deep(.el-dialog__header),
:deep(.el-drawer__header) {
  color: var(--asmr-text-strong);
  border-bottom: 1px solid var(--asmr-border);
}
:deep(.el-dialog__body),
:deep(.el-drawer__body) {
  color: var(--asmr-text);
}
.asmr-page :deep(.el-table),
:deep(.el-dialog .el-table),
:deep(.el-drawer .el-table) {
  --el-table-bg-color: var(--asmr-surface);
  --el-table-tr-bg-color: var(--asmr-surface);
  --el-table-header-bg-color: var(--asmr-surface-soft);
  --el-table-row-hover-bg-color: var(--asmr-surface-hover);
  --el-table-border-color: var(--asmr-border);
  --el-table-text-color: var(--asmr-text);
  --el-table-header-text-color: var(--asmr-text-strong);
  background: var(--asmr-surface);
  color: var(--asmr-text);
}
.asmr-page :deep(.el-table th.el-table__cell),
:deep(.el-dialog .el-table th.el-table__cell),
:deep(.el-drawer .el-table th.el-table__cell) {
  background: var(--asmr-surface-soft);
  color: var(--asmr-text-strong);
}
.asmr-page :deep(.el-table td.el-table__cell),
:deep(.el-dialog .el-table td.el-table__cell),
:deep(.el-drawer .el-table td.el-table__cell) {
  background: var(--asmr-surface);
  color: var(--asmr-text);
}

/* ==============================================================
 * Phase 3 ASMRSync 移动端适配（≤640）
 * 桌面零改动：所有规则严格闭合在 @media 内
 * 主要痛点：
 *   - .asmr-page padding 18/24/24 太大
 *   - .asmr-card-head/body padding 14/18 浪费空间
 *   - .asmr-task / .asmr-list-row 横向 flex 在窄屏挤压标题
 *   - .asmr-task-mapping label/value 横排在窄屏挤
 *   - Preview Dialog 已加 .mobile-full-dialog 全屏；表格内允许横向滚动
 *   - Enhanced Session Drawer ≤640 size 已经动态切到 100%
 * ============================================================ */
@media (max-width: 640px) {
  /* 整页：紧凑 padding + gap */
  .asmr-page {
    padding: 8px 10px 14px;
    gap: 10px;
  }

  /* AppPageHeader 内的 ASMR 页头按钮：≤640 三个按钮均分整行 */
  .asmr-head-btn {
    height: 34px;
    padding: 0 10px;
    font-size: 12px;
  }
  .asmr-head-btn.primary .page-head-btn-label,
  .asmr-head-btn.ghost .page-head-btn-label {
    min-width: 0;
  }

  /* 信息条：≤720 已有 2 列规则；≤640 进一步紧凑 padding/gap */
  .asmr-info-strip {
    padding: 10px 12px !important;
    gap: 8px 0 !important;
    border-radius: 12px;
  }
  .lib-info-item { padding: 0 10px !important; gap: 6px; }
  .lib-info-label { font-size: 10px; }
  .lib-info-value { font-size: 14px; }
  .lib-info-value :deep(b) { font-size: 14px; }

  /* asmr-card：紧凑卡片 */
  .asmr-card { border-radius: 12px; }
  .asmr-card-head {
    padding: 10px 12px;
    gap: 8px;
  }
  .asmr-card-head-title h2 { font-size: 13px; }
  .asmr-card-head-subtitle { font-size: 11px; }
  .asmr-card-body {
    padding: 12px;
  }

  /* asmr-card-head-actions 在 ≤640 改 grid 平分，避免挤成一团 */
  .asmr-card-head-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    width: 100%;
  }
  .asmr-card-head-actions > .asmr-mini-btn {
    width: 100%;
    justify-content: center;
  }

  /* 字幕文件夹扫描卡片：el-input 撑满 */
  .asmr-card-body .flex.items-center {
    gap: 8px !important;
  }
  .asmr-card-body :deep(.el-input) {
    width: 100% !important;
  }

  /* el-table 包装：max-height 缩小 + 可横滑（el-table 内列宽是固定 px，必然溢出） */
  .asmr-table-wrap {
    max-height: 320px;
    border-radius: 10px;
    border: 1px solid var(--asmr-border);
  }

  /* 任务卡：紧凑 padding + 标题区可换行 */
  .asmr-task {
    padding: 10px 12px;
    border-radius: 10px;
  }
  .asmr-task-head {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .asmr-task-head-info {
    flex-wrap: wrap;
    gap: 6px;
  }
  .asmr-task-head-info > .text-sm {
    width: 100%;
    white-space: normal;
  }
  .asmr-task-head-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .asmr-task-head-actions > .asmr-mini-btn {
    flex: 1 1 calc(50% - 3px);
    justify-content: center;
    min-width: 0;
  }
  .asmr-task-mapping {
    padding: 8px;
    font-size: 11px;
  }
  .asmr-task-mapping-label { width: 48px; font-size: 10px; }
  .asmr-task-failed-item,
  .asmr-task-file-row {
    padding: 6px 8px;
    font-size: 11px;
  }
  .asmr-task-file-progress { width: 60px; }
  .asmr-task-file-size { min-width: 96px; font-size: 10px; }

  /* 等待重试列表行：stack */
  .asmr-list-row {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    padding: 8px 10px;
  }
  .asmr-list-row > .min-w-0 { width: 100%; }
  .asmr-list-row > .flex.items-center.gap-1\.5 {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .asmr-list-row > .flex.items-center.gap-1\.5 > .asmr-mini-btn {
    width: 100%;
    justify-content: center;
  }

  /* Drawer 内 el-table：横滑 */
  :deep(.el-drawer__body) {
    padding: 12px;
  }
  :deep(.el-drawer .el-table) {
    overflow-x: auto;
  }
}
</style>





