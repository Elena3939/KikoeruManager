<template>
  <div class="asmr-page">
    <!-- 页头：和库存页 / 操作记录页保持一致 -->
    <AppPageHeader
      :icon="DownloadIcon"
      icon-color="#1d4ed8"
      title="ASMR 同步下载"
      subtitle="根据字幕文件自动下载并匹配，或手动输入 RJ 号查询下载"
    >
      <button
        class="page-head-btn ghost btn-scan"
        type="button"
        :disabled="scanning || !subtitleFolder"
        @click="scanFolder"
      >
        <span class="page-head-btn-icon-wrap">
          <Transition name="page-head-icon-swap" mode="out-in">
            <Loader2 v-if="scanning" key="loader" :size="13" :stroke-width="2.4" class="animate-spin" />
            <Search v-else key="default" :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
          </Transition>
        </span>
        <span class="page-head-btn-label">{{ scanning ? '扫描中…' : '扫描' }}</span>
      </button>
      <button
        class="page-head-btn primary btn-download"
        type="button"
        :disabled="syncing || selectedItems.length === 0"
        @click="startSync"
      >
        <span class="page-head-btn-icon-wrap">
          <Transition name="page-head-icon-swap" mode="out-in">
            <Loader2 v-if="syncing" key="loader" :size="13" :stroke-width="2.6" class="animate-spin" />
            <DownloadIcon v-else key="default" :size="13" :stroke-width="2.6" class="page-head-btn-icon" />
          </Transition>
        </span>
        <span class="page-head-btn-label">{{ syncing ? '同步中…' : '开始同步下载' }}</span>
      </button>
      <button
        class="page-head-btn ghost btn-refresh"
        type="button"
        :disabled="refreshing"
        title="刷新状态"
        @click="refreshStatus"
      >
        <span class="page-head-btn-icon-wrap">
          <RefreshCw
            :size="13"
            :stroke-width="2.6"
            class="page-head-btn-icon"
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

    <!-- 字幕文件夹扫描 -->
    <section class="asmr-card">
      <header class="asmr-card-head">
        <div class="asmr-card-head-title">
          <FolderSearch :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
          <h2>字幕文件夹扫描</h2>
        </div>
      </header>
      <div class="asmr-card-body">
        <div class="flex items-center gap-3">
          <el-input v-model="subtitleFolder" placeholder="输入包含字幕文件的文件夹路径" clearable class="flex-1" />
        </div>
      </div>
    </section>

    <!-- 增强下载工作台 -->
    <section class="asmr-card">
      <header class="asmr-card-head">
        <div class="asmr-card-head-title">
          <Sparkles :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
          <div>
            <h2>增强下载工作台</h2>
            <p class="asmr-card-head-subtitle">手动输入 RJ 号直接查询并下载</p>
          </div>
        </div>
        <div class="asmr-card-head-actions">
          <button
            class="asmr-mini-btn"
            type="button"
            :disabled="enhancedPlanning"
            @click="buildEnhancedPlans"
          >
            <Search :size="12" :stroke-width="2.4" />
            {{ enhancedPlanning ? '查询中…' : '查询 RJ' }}
          </button>
          <button
            v-if="enhancedDownloadWorkbenchTaskIds.length"
            class="asmr-mini-btn"
            type="button"
            @click="enhancedDownloadWorkbenchVisible = true"
          >
            <DownloadIcon :size="12" :stroke-width="2.4" />
            下载工作台
          </button>
        </div>
      </header>
      <div class="asmr-card-body">
        <el-input
          v-model="enhancedInput"
          type="textarea"
          :rows="3"
          placeholder="支持粘贴 RJ123456、RJ234567，空格 / 换行 / 逗号分隔"
          class="mb-4"
        />

        <!-- 计划列表 -->
        <Transition name="asmr-section">
          <div v-if="enhancedPlans.length > 0" class="space-y-4">
            <!-- 批量操作工具条 -->
            <div class="asmr-batch-toolbar">
              <div class="asmr-batch-toolbar-info">
                <span class="asmr-batch-toolbar-title">批量操作</span>
                <span class="lib-chip lib-chip-info">已选 {{ selectedPlanRjcodes.length }} / {{ enhancedPlans.length }}</span>
              </div>
              <div class="asmr-batch-toolbar-actions">
                <button class="asmr-mini-btn" type="button" @click="selectAllPlans">全选</button>
                <button class="asmr-mini-btn" type="button" @click="clearPlanSelection">清空</button>
                <button
                  class="asmr-mini-btn is-primary"
                  type="button"
                  :disabled="enhancedStarting || selectedPlanRjcodes.length === 0"
                  @click="openEnhancedPreview"
                >
                  <DownloadIcon :size="12" :stroke-width="2.4" />
                  {{ enhancedStarting ? '创建中…' : `下载选中 (${selectedPlanRjcodes.length})` }}
                </button>
              </div>
            </div>

            <!-- Plan Cards Grid -->
            <TransitionGroup
              tag="div"
              name="asmr-grid"
              class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3"
            >
              <WorkCard
                v-for="(plan, idx) in enhancedPlans"
                :key="plan.rjcode"
                :item="plan"
                :card-index="idx"
                :selected="selectedPlanSet.has(plan.rjcode)"
                image-field="cover_url"
                code-field="rjcode"
                size="default"
                class="enhanced-plan-card"
                :style="{ '--asmr-grid-delay': `${Math.min(idx, 12) * 35}ms` }"
                @select="(p) => togglePlanSelect(p.rjcode)"
              >
                <template #cover-placeholder>
                  <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow">
                    <DownloadIcon class="w-5 h-5 text-white" />
                  </div>
                </template>
                <template #meta>
                  <div class="enhanced-plan-meta">
                    <span class="enhanced-plan-meta-pill is-code">RJ {{ plan.rjcode }}</span>
                    <span class="enhanced-plan-meta-pill is-downloadable">{{ plan.summary?.selectable_total || 0 }} 个可下载</span>
                  </div>
                </template>
                <template #tags>
                  <div class="enhanced-plan-tags">
                    <span class="enhanced-plan-tag is-primary">资源构成</span>
                    <span v-for="group in (plan.grouped_resources || []).slice(0, 3)" :key="group.group_key" class="enhanced-plan-tag is-soft">
                      {{ getResourceTypeLabel(group.resource_type) }} ×{{ group.count }}
                    </span>
                    <span v-if="(plan.grouped_resources || []).length > 3" class="enhanced-plan-tag is-muted">
                      +{{ (plan.grouped_resources || []).length - 3 }}
                    </span>
                  </div>
                </template>
                <template #actions><span /></template>
              </WorkCard>
            </TransitionGroup>
          </div>
        </Transition>
      </div>
    </section>

    <!-- Enhanced Download Workbench Dialog -->
    <DownloadTaskWorkbenchDialog
      v-model:visible="enhancedDownloadWorkbenchVisible"
      :tasks="enhancedDownloadWorkbenchTasks"
      :refreshing="enhancedDownloadWorkbenchRefreshing"
      :retrying-keys="[...enhancedRetryingTaskIds]"
      title="ASMR 增强下载"
      subtitle="增强下载任务进度"
      @refresh="refreshEnhancedDownloadWorkbench({ silent: true })"
      @background="hideEnhancedDownloadWorkbenchToBackground"
      @close="closeEnhancedDownloadWorkbench"
      @retry-task="retryEnhancedDownloadTask"
      @pause-task="handlePauseEnhancedDownloadTask"
      @resume-task="handleResumeEnhancedDownloadTask"
      @cancel-task="handleCancelEnhancedDownloadTask"
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

    <!-- 增强下载后台浮窗（统一 floating-card 规范） -->
    <Transition name="floating-card">
      <div v-if="showEnhancedDownloadBackgroundCard" class="floating-card">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-2.5 min-w-0">
            <div class="floating-icon-box is-violet">
              <CloudDownload class="h-3.5 w-3.5" :stroke-width="2.2" />
            </div>
            <div class="min-w-0">
              <div class="text-[13px] font-semibold text-slate-900 leading-tight">增强下载正在后台运行</div>
              <div class="mt-0.5 text-[11px] text-slate-500 leading-snug break-all">
                {{ enhancedActiveBackgroundTask ? `${enhancedActiveBackgroundTask.rjcode || 'RJ'} · ${enhancedActiveBackgroundTask.work_title || '-'}` : '保留下载队列与进度' }}
              </div>
            </div>
          </div>
          <div class="floating-percent-badge"
               :class="{
                 'is-emerald': enhancedCompletedTasks.length === enhancedDownloadWorkbenchTasks.length && enhancedDownloadWorkbenchTasks.length > 0,
                 'is-rose': enhancedFailedTasks.length > 0 && !enhancedProcessingTasks.length && !enhancedPendingTasks.length
               }">
            {{ enhancedBackgroundPercent }}%
          </div>
        </div>

        <div class="floating-progress-bar">
          <div class="floating-progress-bar-fill"
               :class="{
                 'is-emerald': enhancedCompletedTasks.length === enhancedDownloadWorkbenchTasks.length && enhancedDownloadWorkbenchTasks.length > 0,
                 'is-danger': enhancedFailedTasks.length > 0 && !enhancedProcessingTasks.length && !enhancedPendingTasks.length
               }"
               :style="{ width: enhancedBackgroundPercent + '%' }" />
        </div>

        <div class="floating-chip-row-compact">
          <span class="floating-chip"><RefreshCw class="floating-chip-icon chip-blue" :stroke-width="2.2" />进行中 <b>{{ enhancedProcessingTasks.length }}</b></span>
          <span class="floating-chip"><Clock class="floating-chip-icon chip-amber" :stroke-width="2.2" />等待 <b>{{ enhancedPendingTasks.length }}</b></span>
          <span class="floating-chip"><CheckCircle2 class="floating-chip-icon chip-emerald" :stroke-width="2.2" />完成 <b>{{ enhancedCompletedTasks.length }}</b></span>
          <span class="floating-chip" :class="{ 'floating-chip-danger': enhancedFailedTasks.length > 0 }"><X class="floating-chip-icon chip-rose" :stroke-width="2.2" />失败 <b>{{ enhancedFailedTasks.length }}</b></span>
        </div>

        <div class="floating-actions-row">
          <button type="button" class="floating-action-btn" @click="closeEnhancedDownloadWorkbench">关闭</button>
          <button type="button" class="floating-action-btn floating-action-btn-primary" @click="resumeEnhancedDownloadWorkbench">
            <CloudDownload class="h-3 w-3" :stroke-width="2.3" />恢复工作台
          </button>
        </div>
      </div>
    </Transition>

    <!-- 扫描结果 -->
    <Transition name="asmr-section">
    <section v-if="scanResults.length > 0" class="asmr-card">
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
                <FolderIcon :size="14" :stroke-width="2.2" class="text-slate-400 shrink-0" />
                <span class="text-sm text-slate-700 truncate">{{ row.folder_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="subtitle_count" label="字幕数" width="80" align="center">
            <template #default="{ row }">
              <span class="text-sm text-slate-600">{{ row.subtitle_count }}</span>
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
        <span v-if="nextRetryTime" class="text-xs text-slate-500">下次：{{ formatNextRetryTime(nextRetryTime) }}</span>
      </header>
      <TransitionGroup tag="div" name="asmr-list" class="asmr-card-body asmr-list">
        <div v-for="task in waitingRetryTasks" :key="task.id" class="asmr-list-row">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="asmr-rjcode">{{ task.rjcode }}</span>
              <span class="text-sm text-slate-600 truncate">{{ task.work_title || task.task_metadata?.work_title }}</span>
            </div>
            <div class="flex items-center gap-3 mt-1 text-xs text-slate-500">
              <span class="text-amber-600">{{ task.task_metadata?.retry_reason || task.current_step || '未找到版本' }}</span>
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
              <span v-if="task.actual_rjcode && task.actual_rjcode !== task.rjcode" class="text-xs text-slate-400">(原: {{ task.rjcode }})</span>
              <span class="text-sm text-slate-600 truncate">{{ task.work_title }}</span>
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
              <button v-if="task.failed_files && task.failed_files.length > 0" class="asmr-mini-btn xs is-warning" type="button" @click="retryFailed(task.id)">
                重试失败 ({{ task.failed_files.length }})
              </button>
            </div>
          </div>

          <!-- 进度条 -->
          <div class="mt-3">
            <AppLottieProgressBar :percentage="task.progress" size="sm" />
          </div>

          <!-- 当前步骤 -->
          <div class="flex items-center gap-1.5 mt-2 text-xs text-slate-500">
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
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">原音频</span><span class="text-amber-600 font-medium truncate">{{ item.original }}</span></div>
                <div class="asmr-task-mapping-arrow">↓</div>
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">重命名</span><span class="text-blue-600 font-medium truncate">{{ item.new }}</span></div>
                <div class="flex items-baseline gap-2"><span class="asmr-task-mapping-label">字幕</span><span class="text-emerald-600 font-medium truncate">{{ item.subtitle }}</span></div>
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
                <span class="text-slate-600 truncate">{{ file.title || file.path }}</span>
                <span class="text-red-600 shrink-0 ml-2">{{ file.reason }}</span>
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
                <span class="flex-1 min-w-0 truncate text-slate-700">{{ file.name }}</span>
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
    <el-dialog v-model="previewDialogVisible" title="下载预览" width="900px" class="rounded-2xl">
      <div v-if="previewLoading" class="flex items-center justify-center py-10">
        <AppLoadingAnimation label="正在获取作品信息..." :size="132" :min-height="180" />
      </div>
      <div v-else-if="previewData" class="space-y-5">
        <div class="grid grid-cols-3 gap-4">
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">请求 RJ 号</div>
            <div class="font-mono font-semibold text-slate-900">{{ previewData.rjcode }}</div>
          </div>
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">实际下载</div>
            <div class="flex items-center gap-2">
              <span class="font-mono font-semibold" :class="previewData.actual_rjcode !== previewData.rjcode ? 'text-amber-600' : 'text-emerald-600'">{{ previewData.actual_rjcode || '未找到' }}</span>
              <span v-if="previewData.lang" class="text-xs text-slate-500">({{ previewData.lang }})</span>
            </div>
          </div>
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">预计大小</div>
            <div class="font-semibold text-blue-600">{{ formatSize(previewData.total_size) }}</div>
          </div>
        </div>
        <div class="flex items-center gap-4 text-sm text-slate-600">
          <span>标题: <strong class="text-slate-900">{{ previewData.title }}</strong></span>
          <span>文件: {{ previewData.total_files }} → <strong class="text-emerald-600">{{ previewData.filtered_files }}</strong></span>
        </div>

        <!-- Available Versions -->
        <div v-if="previewData.available_versions?.length">
          <h4 class="text-sm font-semibold text-slate-700 mb-2">可用版本</h4>
          <div class="space-y-1.5">
            <div v-for="ver in previewData.available_versions" :key="ver.rjcode"
              class="flex items-center gap-3 px-3 py-2 bg-slate-50 rounded-lg border border-slate-100 text-sm"
            >
              <span class="font-mono font-semibold text-slate-900 w-24">{{ ver.rjcode }}</span>
              <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border" :class="{
                'bg-emerald-50 text-emerald-700 border-emerald-200': ver.priority <= 1,
                'bg-amber-50 text-amber-700 border-amber-200': ver.priority === 2,
                'bg-slate-100 text-slate-600 border-slate-200': ver.priority > 2,
              }">{{ getLangName(ver.lang) }}</span>
              <span class="text-slate-500">{{ ver.file_count }} 文件</span>
              <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[11px]" :class="ver.available ? 'text-emerald-600 bg-emerald-50' : 'text-red-600 bg-red-50'">{{ ver.available ? '可用' : '不可用' }}</span>
              <span class="text-slate-500 truncate flex-1">{{ ver.title }}</span>
            </div>
          </div>
        </div>

        <!-- File List -->
        <div>
          <h4 class="text-sm font-semibold text-slate-700 mb-2">下载文件 ({{ previewData.filtered_files }})</h4>
          <div class="overflow-auto" style="max-height: 350px;">
            <el-table :data="previewData.files" size="small">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="文件路径" min-width="300">
                <template #default="{ row }">
                  <div class="flex items-center gap-1.5 text-sm">
                    <FileIcon class="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span class="truncate" :title="row.path || row.title">{{ row.title }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="type" label="类型" width="80">
                <template #default="{ row }">
                  <span class="text-xs text-slate-500">{{ row.type || '文件' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  <span class="text-xs font-mono text-slate-600">{{ formatSize(row.size) }}</span>
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
    <el-drawer v-model="enhancedSessionDrawerVisible" size="55%" :title="enhancedSessionDetail?.rjcode ? `${enhancedSessionDetail.rjcode} 会话详情` : '会话详情'">
      <div v-app-loading="{ loading: enhancedSessionDetailLoading, text: '正在加载增强下载详情...', size: 124 }">
        <template v-if="enhancedSessionDetail">
          <div class="flex flex-wrap gap-2 mb-4">
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">{{ getSessionStatusLabel(enhancedSessionDetail.status) }}</span>
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">优先级 {{ enhancedSessionDetail.queue_priority }}</span>
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">{{ getUploadModeLabel(enhancedSessionDetail.upload_mode) }}</span>
          </div>

          <div class="grid grid-cols-2 gap-3 mb-4">
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">标题</div>
              <div class="text-sm text-slate-900 font-medium mt-0.5">{{ enhancedSessionDetail.source_label || '未命名会话' }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">目标路径</div>
              <div class="text-sm text-slate-900 font-mono mt-0.5 break-all">{{ enhancedSessionDetail.target_path || '未设置' }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">已选/已上传</div>
              <div class="text-sm text-slate-900 font-medium mt-0.5">{{ enhancedSessionDetail.statistics?.selected_resource_count || 0 }} / {{ enhancedSessionDetail.statistics?.uploaded_count || 0 }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">成功/失败/MD5失败</div>
              <div class="text-sm font-medium mt-0.5">
                <span class="text-emerald-600">{{ enhancedSessionDetail.statistics?.success_count || 0 }}</span>
                <span class="text-slate-400 mx-1">/</span>
                <span class="text-red-600">{{ enhancedSessionDetail.statistics?.failed_count || 0 }}</span>
                <span class="text-slate-400 mx-1">/</span>
                <span class="text-amber-600">{{ enhancedSessionDetail.statistics?.verify_summary?.failed || 0 }}</span>
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
  CheckCircle2,
  Sparkles,
  ListChecks,
  Database,
  Package,
  CloudDownload,
  Upload,
  Activity,
  Hourglass,
  Loader2,
  X,
} from 'lucide-vue-next'
import { asmrSyncApi, configApi, libraryApi, taskApi } from '../api'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import DownloadTaskWorkbenchDialog from '../components/download/DownloadTaskWorkbenchDialog.vue'
import CircleDownloadPreviewDialog from '../components/circle/CircleDownloadPreviewDialog.vue'
import WorkCard from '../components/circle/WorkCard.vue'

const ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY = 'kikoerumanager.asmrSync.downloadWorkbench'

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
const enhancedDownloadWorkbenchTaskIds = ref([])
const enhancedDownloadWorkbenchTasks = ref([])
const enhancedDownloadWorkbenchVisible = ref(false)
const enhancedDownloadWorkbenchBackgroundActive = ref(false)
const enhancedDownloadWorkbenchRefreshing = ref(false)
const enhancedRetryingTaskIds = ref(new Set())
let enhancedDownloadWorkbenchTimer = null

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
      iconClass: 'text-blue-500',
    },
    {
      label: '资源条目',
      value: dashboard.total_resources || 0,
      help: '已抓取并落库的远端资源',
      icon: Package,
      iconClass: 'text-indigo-500',
    },
    {
      label: '已下载',
      value: dashboard.downloaded_resources || 0,
      help: '已完成下载的文件数',
      icon: CloudDownload,
      iconClass: 'text-emerald-500',
    },
    {
      label: '已上传',
      value: dashboard.uploaded_resources || 0,
      help: '已进入自动上传管道的文件数',
      icon: Upload,
      iconClass: 'text-cyan-500',
    },
    {
      label: '处理中',
      value: dashboard.processing_tasks || 0,
      help: '当前运行中的增强下载任务',
      icon: Activity,
      iconClass: 'text-amber-500',
    },
    {
      label: '待处理 / 失败',
      value: `${dashboard.pending_tasks || 0} / ${dashboard.failed_tasks || 0}`,
      help: '当前排队与失败任务概况',
      icon: Hourglass,
      iconClass: 'text-rose-500',
    },
  ]
})

const hasEnhancedSelections = computed(() => {
  return enhancedPlans.value.some(plan => (plan.selectable_resources || []).some(item => item.selected))
})

const selectedPlanRjcodes = computed(() => [...selectedPlanSet.value])
const enhancedProcessingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'processing'))
const enhancedPendingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => ['pending', 'paused', 'waiting_retry'].includes(String(t.status || ''))))
const enhancedCompletedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'completed'))
const enhancedFailedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'failed'))
const showEnhancedDownloadBackgroundCard = computed(() => enhancedDownloadWorkbenchBackgroundActive.value && !enhancedDownloadWorkbenchVisible.value && enhancedDownloadWorkbenchTaskIds.value.length > 0)
const enhancedActiveBackgroundTask = computed(() => enhancedProcessingTasks.value[0] || enhancedPendingTasks.value[0] || enhancedDownloadWorkbenchTasks.value[0] || null)
const enhancedBackgroundPercent = computed(() => {
  if (!enhancedDownloadWorkbenchTasks.value.length) return 0
  const total = enhancedDownloadWorkbenchTasks.value.reduce((sum, t) => sum + Number(t.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / enhancedDownloadWorkbenchTasks.value.length)))
})

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
  const map = { audio: '音频', subtitle: '字幕', cover: '封面', other: '其他' }
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
  if (!enhancedDownloadWorkbenchTaskIds.value.length) {
    enhancedDownloadWorkbenchTasks.value = []
    stopEnhancedDownloadWorkbenchPolling()
    return
  }
  if (!silent) enhancedDownloadWorkbenchRefreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    enhancedDownloadWorkbenchTasks.value = enhancedDownloadWorkbenchTaskIds.value
      .map(id => allTasks.find(t => t.id === id))
      .filter(Boolean)
    enhancedDownloadWorkbenchTaskIds.value = enhancedDownloadWorkbenchTasks.value.map(t => t.id)
    const stillActive = enhancedDownloadWorkbenchTasks.value.some(t => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(t.status || '')))
    if (stillActive || enhancedDownloadWorkbenchVisible.value || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
    else stopEnhancedDownloadWorkbenchPolling()
  } catch (error) {
    console.error('刷新增强下载工作台失败:', error)
    startEnhancedDownloadWorkbenchPolling()
  } finally {
    if (!silent) enhancedDownloadWorkbenchRefreshing.value = false
  }
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

async function retryEnhancedDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const taskId = String(task?.id || '').trim()
  const next = new Set(enhancedRetryingTaskIds.value)
  next.add(taskId)
  enhancedRetryingTaskIds.value = next
  try {
    if (sessionId) {
      const response = await asmrSyncApi.retryFailedSession(sessionId)
      const nextTaskId = String(response?.session?.task_id || '').trim()
      if (nextTaskId && nextTaskId !== taskId) {
        enhancedDownloadWorkbenchTaskIds.value = [
          nextTaskId,
          ...enhancedDownloadWorkbenchTaskIds.value.filter(id => id !== nextTaskId && id !== taskId)
        ]
      }
    } else if (taskId) {
      await asmrSyncApi.retry(taskId)
    }
    ElMessage.success('已提交重试')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(enhancedRetryingTaskIds.value)
    done.delete(taskId)
    enhancedRetryingTaskIds.value = done
  }
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
  try {
    await asmrSyncApi.retryFailedSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重试失败资源失败')
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
  try {
    const result = await asmrSyncApi.retry(taskId)
    ElMessage.success(result.message)
    await refreshStatus()
  } catch (error) {
    ElMessage.error('重试失败')
  }
}

const retryWaitingTask = async (taskId) => {
  try {
    const result = await asmrSyncApi.retryWaiting(taskId)
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
  refreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    tasks.value = result.tasks
    result.tasks.forEach(task => {
      const item = scanResults.value.find(i => i.rjcode === task.rjcode)
      if (item) item.status = task.status === 'processing' ? 'downloading' : task.status
    })
  } catch (error) {
    console.error('获取状态失败:', error)
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

function stopStatusPolling () {
  if (statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
  }
}

function startStatusPolling () {
  stopStatusPolling()
  statusInterval = setInterval(refreshStatus, 3000)
}

async function initializeASMRSyncPage () {
  if (asmrSyncInitialized) return
  hydrateEnhancedDownloadWorkbenchState()
  await loadSavedFolder()
  await loadWaitingRetryTasks()
  await refreshStatus()
  if (enhancedDownloadWorkbenchTaskIds.value.length) await refreshEnhancedDownloadWorkbench()
  if (subtitleFolder.value) {
    await scanFolder()
  }
  asmrSyncInitialized = true
}

onMounted(async () => {
  await initializeASMRSyncPage()
  asmrSyncViewActive = true
  startStatusPolling()
})

onActivated(async () => {
  if (asmrSyncViewActive) return
  asmrSyncViewActive = true
  await loadWaitingRetryTasks()
  await refreshStatus()
  await loadEnhancedSessions()
  if (enhancedDownloadWorkbenchTaskIds.value.length) refreshEnhancedDownloadWorkbench()
  startStatusPolling()
})

onDeactivated(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
})

onBeforeUnmount(() => {
  stopEnhancedDownloadWorkbenchPolling()
})

onUnmounted(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
  stopEnhancedDownloadWorkbenchPolling()
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
</script>

<style scoped>
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }

/* ==============================================================
 * 页面整体布局：与库存页 / 操作记录页保持一致
 * ============================================================ */
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
 * 页头按钮：page-head-btn 规范（对齐 ActivityHistory.vue）
 *  - 基础 ghost 白底
 *  - .primary 黑灰渐变 + 软阴影
 * ============================================================ */
.page-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
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
.page-head-btn :deep(.page-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.page-head-btn :deep(svg) { flex-shrink: 0; }

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
.page-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.page-head-btn:active:not(:disabled) {
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
.page-head-btn:active:not(:disabled) :deep(.page-head-btn-icon) {
  transform: scale(0.82);
  transition: transform 0.12s ease;
}
/* disabled：仅改 opacity / cursor，不重置 transform / box-shadow，让 hover 视觉与 enabled 一致，消除点击瞬间跳变 */
.page-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* === Primary 黑灰渐变按钮 + shimmer 高光扫光 === */
.page-head-btn.primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.page-head-btn.primary::before {
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
.page-head-btn.primary:hover {
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow:
    0 14px 28px rgba(15, 23, 42, 0.28),
    0 0 0 4px rgba(15, 23, 42, 0.05);
}
.page-head-btn.primary:hover::before {
  left: 130%;
}

/* === Ghost 白底按钮 hover 时纯色变化（避免 gradient 不能 transition 造成瞬切）=== */
.page-head-btn.ghost {
  background-color: #fff;
}
.page-head-btn.ghost:hover {
  background-color: #f8fafc;
  border-color: rgba(15, 23, 42, 0.2);
}

/* === 各按钮专属图标动效 === */
/* 扫描：Search 图标 hover 时左摆 + 放大（模拟搜索动作） */
.page-head-btn.btn-scan:hover:not(:disabled) :deep(.page-head-btn-icon) {
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
.page-head-btn.btn-download:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: translateY(2px) scale(1.18);
  filter: drop-shadow(0 2px 5px rgba(255, 255, 255, 0.45));
  animation: download-icon-bob 1.2s ease-in-out infinite;
}
@keyframes download-icon-bob {
  0%, 100% { transform: translateY(2px) scale(1.18); }
  50%      { transform: translateY(4px) scale(1.18); }
}

/* 刷新：RefreshCw 图标 hover 时旋转一整圈（非 loading 态）*/
.page-head-btn.btn-refresh:hover:not(:disabled) :deep(.page-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 文本 label：min-width + 居中，避免「扫描」→「扫描中…」宽度跳变 */
.page-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.page-head-btn.primary .page-head-btn-label { min-width: 86px; }
.page-head-btn.ghost .page-head-btn-label { min-width: 42px; }
/* hover 时文字微微展开间距（不依赖 :not(:disabled)，避免点击瞬间跳变） */
.page-head-btn:hover .page-head-btn-label {
  letter-spacing: 0.04em;
}

/* === 图标 swap Transition：Loader2 ↔ Search/DownloadIcon 切换时平滑过渡 === */
.page-head-btn :deep(.page-head-icon-swap-enter-active) {
  transition:
    opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.page-head-btn :deep(.page-head-icon-swap-leave-active) {
  transition:
    opacity 0.14s ease,
    transform 0.18s ease;
  position: absolute;
}
.page-head-btn :deep(.page-head-icon-swap-enter-from) {
  opacity: 0;
  transform: scale(0.4) rotate(-90deg);
}
.page-head-btn :deep(.page-head-icon-swap-leave-to) {
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

/* WorkCard 网格 TransitionGroup name="asmr-grid"，按 idx 阶梯延迟入场 */
.asmr-grid-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.55s cubic-bezier(0.34, 1.56, 0.64, 1);
  transition-delay: var(--asmr-grid-delay, 0ms);
}
.asmr-grid-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
  position: absolute;
}
.asmr-grid-enter-from {
  opacity: 0;
  transform: translateY(20px) scale(0.92);
}
.asmr-grid-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.95);
}
.asmr-grid-move {
  transition: transform 0.45s cubic-bezier(0.22, 1, 0.36, 1);
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
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
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
  color: #94a3b8;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lib-info-value {
  font-size: 13.5px;
  color: #475569;
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
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.lib-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(15, 23, 42, 0.1), transparent);
  align-self: stretch;
}
@media (max-width: 1180px) {
  .asmr-info-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px 0;
    padding: 16px 18px;
  }
  .lib-info-divider { display: none; }
  .lib-info-item { padding: 0 14px; border-right: 1px solid rgba(15, 23, 42, 0.06); }
  .lib-info-item:nth-child(3n) { border-right: 0; }
}
@media (max-width: 720px) {
  .asmr-info-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lib-info-item:nth-child(3n) { border-right: 1px solid rgba(15, 23, 42, 0.06); }
  .lib-info-item:nth-child(2n) { border-right: 0; }
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
.lib-chip-success { background: rgba(220, 252, 231, 0.85); color: #047857; border: 1px solid rgba(134, 239, 172, 0.5); }
.lib-chip-warning { background: rgba(254, 243, 199, 0.85); color: #b45309; border: 1px solid rgba(253, 224, 71, 0.5); }
.lib-chip-danger  { background: rgba(254, 226, 226, 0.85); color: #b91c1c; border: 1px solid rgba(252, 165, 165, 0.5); }
.lib-chip-info    { background: rgba(224, 231, 255, 0.85); color: #4338ca; border: 1px solid rgba(165, 180, 252, 0.5); }
.lib-chip-slate   { background: rgba(241, 245, 249, 0.85); color: #475569; border: 1px solid rgba(203, 213, 225, 0.55); }

/* ==============================================================
 * 主卡片 asmr-card：和 conflicts-info-card / subtitle-info-card 同款
 * ============================================================ */
.asmr-card {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}
.asmr-card-amber {
  background: rgba(255, 251, 235, 0.6);
  border-color: rgba(245, 158, 11, 0.25);
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, #fbfcfe 0%, #f8fafc 100%);
}
.asmr-card-head-amber {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.85) 0%, rgba(254, 243, 199, 0.55) 100%);
  border-bottom-color: rgba(245, 158, 11, 0.18);
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
  color: #0f172a;
}
.asmr-card-head-subtitle {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: #94a3b8;
  letter-spacing: 0.01em;
}
.asmr-card-head-icon { color: #2563eb; flex-shrink: 0; }
.asmr-card-head-icon-amber { color: #b45309; flex-shrink: 0; }
.asmr-card-head-count { color: #94a3b8; font-weight: 500; font-size: 12.5px; }
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
  color: #64748b;
  cursor: pointer;
  user-select: none;
}
.asmr-card-head-checkbox input { width: 14px; height: 14px; accent-color: #1e293b; }
.asmr-card-body {
  padding: 16px 18px;
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
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.15s ease, box-shadow 0.18s ease;
}
.asmr-mini-btn:hover {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.22);
  color: #0f172a;
}
.asmr-mini-btn:active:not(:disabled) { transform: scale(0.96); }
.asmr-mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.asmr-mini-btn.is-primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.18);
}
.asmr-mini-btn.is-primary:hover {
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.22);
  color: #fff;
}

.asmr-mini-btn.is-warning {
  background: linear-gradient(180deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border-color: rgba(245, 158, 11, 0.4);
}
.asmr-mini-btn.is-warning:hover {
  background: linear-gradient(180deg, #fde68a 0%, #fcd34d 100%);
  color: #78350f;
  border-color: rgba(217, 119, 6, 0.55);
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
 * 增强工作台 - 批量操作工具栏
 * ============================================================ */
.asmr-batch-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: linear-gradient(180deg, #fbfcfe 0%, #f5f7fb 100%);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.asmr-batch-toolbar-info {
  display: flex;
  align-items: center;
  gap: 10px;
}
.asmr-batch-toolbar-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  letter-spacing: -0.1px;
}
.asmr-batch-toolbar-actions {
  display: flex;
  gap: 6px;
}

/* ==============================================================
 * 后台浮窗（.asmr-bg-card-*）已迁移至 index.css 全局 .floating-card 规范
 * ============================================================ */

/* ==============================================================
 * 下载任务 asmr-task 卡片
 * ============================================================ */
.asmr-task {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  transition: border-color 0.18s ease, background-color 0.18s ease;
}
.asmr-task.is-completed {
  border-color: rgba(16, 185, 129, 0.32);
  background: rgba(220, 252, 231, 0.22);
}
.asmr-task.is-failed {
  border-color: rgba(248, 113, 113, 0.32);
  background: rgba(254, 226, 226, 0.22);
}
.asmr-task.is-paused {
  border-color: rgba(148, 163, 184, 0.32);
  background: rgba(241, 245, 249, 0.45);
}
.asmr-task.is-processing {
  border-color: rgba(59, 130, 246, 0.32);
  background: rgba(219, 234, 254, 0.18);
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
  background: rgba(254, 226, 226, 0.6);
  border: 1px solid rgba(248, 113, 113, 0.25);
  color: #991b1b;
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
.asmr-task-details-summary:hover { background: rgba(15, 23, 42, 0.04); }
.asmr-task-details-summary.is-success { color: #047857; }
.asmr-task-details-summary.is-success:hover { color: #065f46; }
.asmr-task-details-summary.is-danger { color: #b91c1c; }
.asmr-task-details-summary.is-danger:hover { color: #991b1b; }
.asmr-task-details-summary.is-slate { color: #334155; }
.asmr-task-details-summary.is-slate:hover { color: #0f172a; }
.asmr-task-details-body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.asmr-task-mapping {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(220, 252, 231, 0.32);
  border: 1px solid rgba(167, 243, 208, 0.45);
  font-size: 11.5px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.asmr-task-mapping-label {
  width: 56px;
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.asmr-task-mapping-arrow { text-align: center; color: #10b981; font-weight: 700; font-size: 10px; }

.asmr-task-failed-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(254, 226, 226, 0.4);
  font-size: 11.5px;
}

.asmr-task-file-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f8fafc;
  font-size: 11.5px;
  min-width: 0;
}
.asmr-task-file-progress {
  width: 80px;
  flex-shrink: 0;
}
.asmr-task-file-progress-bar {
  height: 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.8);
  position: relative;
  overflow: hidden;
}
.asmr-task-file-progress-bar::after {
  content: '';
  position: absolute;
  inset: 0;
  width: var(--w, 0%);
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  border-radius: 999px;
  transition: width 0.4s ease;
}
.asmr-task-file-progress-bar { background: rgba(226, 232, 240, 0.8); }
.asmr-task-file-progress-bar > div,
.asmr-task-file-row .asmr-task-file-progress > div {
  height: 6px;
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  border-radius: 999px;
  transition: width 0.4s ease;
}
.asmr-task-file-size {
  color: #94a3b8;
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
  background: #fff;
  border: 1px solid rgba(245, 158, 11, 0.18);
}

/* ==============================================================
 * 通用辅助：RJ 号 / 链接按钮
 * ============================================================ */
.asmr-rjcode {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-weight: 600;
  font-size: 13px;
  color: #2563eb;
  letter-spacing: -0.2px;
  flex-shrink: 0;
}
.asmr-rjcode.is-bold { font-weight: 700; }

.asmr-link-btn {
  background: transparent;
  border: 0;
  color: #2563eb;
  font-size: 12.5px;
  font-weight: 500;
  transition: color 0.18s ease, text-decoration 0.18s ease;
  padding: 4px 6px;
}
.asmr-link-btn:hover {
  color: #1d4ed8;
  text-decoration: underline;
}
.asmr-link-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ==============================================================
 * 增强计划卡片（保留原 enhanced-plan）
 * ============================================================ */
.enhanced-plan-card {
  max-width: 248px;
}
.enhanced-plan-card :deep(.work-cover-wrapper) {
  aspect-ratio: 1 / 0.82;
}
.enhanced-plan-card :deep(.work-card-body) {
  gap: 6px;
  padding: 10px 10px 12px;
}
.enhanced-plan-card :deep(.work-title) {
  font-size: 12px;
  line-height: 1.45;
}
.enhanced-plan-card :deep(.work-rj) {
  display: none;
}
.enhanced-plan-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.enhanced-plan-meta-pill,
.enhanced-plan-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid transparent;
}
.enhanced-plan-meta-pill.is-code {
  color: #4f6b95;
  background: #f8fbff;
  border-color: #d8e6fb;
}
.enhanced-plan-meta-pill.is-downloadable {
  color: #216e56;
  background: #edf9f3;
  border-color: #cbeedd;
}
.enhanced-plan-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
}
.enhanced-plan-tag.is-primary {
  color: #2b63c8;
  background: #edf4ff;
  border-color: #cadeff;
}
.enhanced-plan-tag.is-soft {
  color: #5d6d81;
  background: #f6f8fb;
  border-color: #e2e8f0;
}
.enhanced-plan-tag.is-muted {
  color: #7b8797;
  background: #fafafa;
  border-color: #e5e7eb;
}

/* ==============================================================
 * el-dialog 圆角保留
 * ============================================================ */
:deep(.el-dialog) {
  border-radius: 16px !important;
}
</style>
